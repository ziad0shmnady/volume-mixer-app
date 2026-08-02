"""Threaded PulseAudio / pipewire-pulse backend."""

from __future__ import annotations

import queue
import threading
import time
from typing import Any

from mixer.models.audio import AudioSnapshot, DeviceInfo, StreamInfo, VolumeMath
from mixer.services.backend import (
    AudioCommand,
    MoveStream,
    SetDefaultDevice,
    SetMute,
    SetVolume,
    SnapshotCallback,
)
from mixer.util.logging import get_logger
from mixer.util.stream_names import is_transient_system_stream, resolve_stream_display_name

logger = get_logger("services.pulse")

_MIN_BACKOFF = 0.5
_MAX_BACKOFF = 8.0
_EVENT_TIMEOUT = 0.15
# Safety-net poll so streams are not missed if a subscribe event is dropped.
_SNAPSHOT_POLL_S = 1.5


def _mean_volume(obj: Any) -> float:
    """Extract a linear volume (0-1+) from a pulsectl object."""
    try:
        return float(obj.volume.value_flat)
    except Exception:  # noqa: BLE001
        values = getattr(getattr(obj, "volume", None), "values", None)
        if values:
            return float(sum(values) / len(values))
        return 0.0


def _prop(props: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = props.get(key)
        if value:
            return value
    return None


class PulseService:
    """Owns a single libpulse connection on a dedicated worker thread."""

    def __init__(self, client_name: str = "mixer") -> None:
        self._client_name = client_name
        self._commands: queue.Queue[AudioCommand | object] = queue.Queue()
        self._on_snapshot: SnapshotCallback | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._generation = 0
        self._snapshot_requested = threading.Event()
        self._dirty = threading.Event()
        self._dirty.set()
        self._connected = False

    # ------------------------------------------------------------------
    # AudioBackend API
    # ------------------------------------------------------------------

    def start(self, on_snapshot: SnapshotCallback) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("PulseService already started")
        self._on_snapshot = on_snapshot
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="pulse-service",
            daemon=True,
        )
        self._thread.start()
        logger.info("PulseService started")

    def stop(self) -> None:
        self._stop.set()
        # Wake the worker if blocked in event_listen
        self._commands.put(_Wake())
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        self._on_snapshot = None
        logger.info("PulseService stopped")

    def submit(self, command: AudioCommand) -> None:
        self._commands.put(command)

    def request_snapshot(self) -> None:
        self._snapshot_requested.set()
        self._dirty.set()
        self._commands.put(_Wake())

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _run(self) -> None:
        backoff = _MIN_BACKOFF
        while not self._stop.is_set():
            try:
                self._session_loop()
                backoff = _MIN_BACKOFF
            except Exception as exc:  # noqa: BLE001
                logger.warning("Pulse session ended: %s", exc)
                self._emit_disconnected()
                if self._stop.is_set():
                    break
                time.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF)

    def _session_loop(self) -> None:
        try:
            import pulsectl
        except ImportError as exc:
            raise RuntimeError(
                "pulsectl is not installed. Run ./install.sh or "
                "`pip install pulsectl` / `sudo apt install python3-pulsectl`."
            ) from exc

        with pulsectl.Pulse(self._client_name) as pulse:
            self._connected = True
            logger.info("Connected to PulseAudio / pipewire-pulse")
            pulse.event_mask_set("all")
            pulse.event_callback_set(self._on_pulse_event)
            self._dirty.set()
            self._emit_snapshot(pulse)
            last_poll = time.monotonic()

            while not self._stop.is_set():
                self._drain_commands(pulse)
                now = time.monotonic()
                if now - last_poll >= _SNAPSHOT_POLL_S:
                    self._dirty.set()
                    last_poll = now
                if self._snapshot_requested.is_set() or self._dirty.is_set():
                    self._snapshot_requested.clear()
                    self._dirty.clear()
                    self._emit_snapshot(pulse)
                    last_poll = time.monotonic()
                try:
                    pulse.event_listen(timeout=_EVENT_TIMEOUT)
                except pulsectl.PulseLoopStop:
                    continue
                except pulsectl.PulseDisconnected as exc:
                    self._connected = False
                    raise RuntimeError("Disconnected from Pulse") from exc

    def _on_pulse_event(self, _event: object) -> None:
        self._dirty.set()
        # Raise PulseLoopStop so event_listen returns and we can drain commands.
        raise __import__("pulsectl").PulseLoopStop()

    def _drain_commands(self, pulse: object) -> None:
        while True:
            try:
                item = self._commands.get_nowait()
            except queue.Empty:
                return
            if isinstance(item, _Wake):
                continue
            try:
                self._apply_command(pulse, item)
                self._dirty.set()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Command failed (%s): %s", type(item).__name__, exc)

    def _apply_command(self, pulse: Any, command: AudioCommand) -> None:
        if isinstance(command, SetVolume):
            obj = self._resolve_target(pulse, command.target, command.index)
            if obj is None:
                logger.warning("SetVolume: target %s#%s not found", command.target, command.index)
                return
            volume = VolumeMath.clamp(command.volume)
            pulse.volume_set_all_chans(obj, volume)
            logger.debug(
                "SetVolume %s#%s -> %.3f (gen=%s)",
                command.target,
                command.index,
                volume,
                command.generation,
            )
        elif isinstance(command, SetMute):
            obj = self._resolve_target(pulse, command.target, command.index)
            if obj is None:
                logger.warning("SetMute: target %s#%s not found", command.target, command.index)
                return
            pulse.mute(obj, command.muted)
            logger.debug("SetMute %s#%s -> %s", command.target, command.index, command.muted)
        elif isinstance(command, MoveStream):
            pulse.sink_input_move(command.stream_index, command.sink_index)
            logger.debug(
                "MoveStream #%s -> sink #%s",
                command.stream_index,
                command.sink_index,
            )
        elif isinstance(command, SetDefaultDevice):
            if command.kind == "sink":
                pulse.sink_default_set(command.name)
            elif command.kind == "source":
                pulse.source_default_set(command.name)
            else:
                logger.warning("Unknown default device kind: %s", command.kind)
                return
            logger.debug("SetDefaultDevice %s -> %s", command.kind, command.name)
        else:
            logger.warning("Unknown command: %s", command)

    def _resolve_target(self, pulse: Any, target: str, index: int) -> Any | None:
        if target == "sink":
            for sink in pulse.sink_list():
                if sink.index == index:
                    return sink
        elif target == "source":
            for source in pulse.source_list():
                if source.index == index:
                    return source
        elif target == "stream":
            for stream in pulse.sink_input_list():
                if stream.index == index:
                    return stream
        return None

    def _emit_disconnected(self) -> None:
        self._connected = False
        self._generation += 1
        callback = self._on_snapshot
        if callback is None:
            return
        snapshot = AudioSnapshot(connected=False, generation=self._generation)
        try:
            callback(snapshot)
        except Exception:  # noqa: BLE001
            logger.exception("Snapshot callback failed (disconnected)")

    def _emit_snapshot(self, pulse: Any) -> None:
        callback = self._on_snapshot
        if callback is None:
            return
        try:
            snapshot = self._build_snapshot(pulse)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to build snapshot")
            return
        try:
            callback(snapshot)
        except Exception:  # noqa: BLE001
            logger.exception("Snapshot callback failed")

    def _build_snapshot(self, pulse: Any) -> AudioSnapshot:
        self._generation += 1
        server_info = pulse.server_info()
        default_sink = getattr(server_info, "default_sink_name", None)
        default_source = getattr(server_info, "default_source_name", None)

        sinks = tuple(
            DeviceInfo(
                index=sink.index,
                name=sink.name,
                description=sink.description or sink.name,
                volume=VolumeMath.clamp(_mean_volume(sink)),
                muted=bool(sink.mute),
                is_default=(sink.name == default_sink),
            )
            for sink in pulse.sink_list()
        )

        sources = tuple(
            DeviceInfo(
                index=source.index,
                name=source.name,
                description=source.description or source.name,
                volume=VolumeMath.clamp(_mean_volume(source)),
                muted=bool(source.mute),
                is_default=(source.name == default_source),
            )
            for source in pulse.source_list()
            if not source.name.endswith(".monitor")
        )

        streams: list[StreamInfo] = []
        for si in pulse.sink_input_list():
            props = dict(getattr(si, "proplist", {}) or {})
            if is_transient_system_stream(props):
                continue
            process_binary = _prop(props, "application.process.binary")
            snap_id = _prop(props, "pipewire.snap.id", "snap.id", "application.id")
            application_name = _prop(props, "application.name")
            media_name = _prop(props, "media.name", "media.title") or ""
            name = resolve_stream_display_name(
                application_name=application_name,
                process_binary=process_binary,
                snap_id=snap_id,
                media_name=media_name,
                fallback=si.name or f"Stream {si.index}",
            )
            icon_name = _prop(props, "application.icon_name", "window.icon_name")
            if icon_name is None and process_binary:
                icon_name = process_binary.split("/")[-1]
            application_id = _prop(props, "application.id")
            streams.append(
                StreamInfo(
                    index=si.index,
                    name=name,
                    media_name=media_name,
                    icon_name=icon_name,
                    volume=VolumeMath.clamp(_mean_volume(si)),
                    muted=bool(si.mute),
                    sink_index=int(si.sink),
                    corked=bool(getattr(si, "corked", False)),
                    application_id=application_id,
                    process_binary=process_binary,
                    snap_id=snap_id,
                )
            )

        return AudioSnapshot(
            sinks=sinks,
            sources=sources,
            streams=tuple(streams),
            default_sink_name=default_sink,
            default_source_name=default_source,
            connected=True,
            generation=self._generation,
        )


class _Wake:
    """Sentinel to wake the worker from event_listen / empty queue wait."""
