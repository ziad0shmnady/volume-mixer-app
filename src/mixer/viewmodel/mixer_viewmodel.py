"""View-model: snapshot diffing, sorting, debounce, feedback-loop guard."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Callable

from mixer.models.audio import AudioSnapshot, DeviceInfo, StreamInfo, VolumeMath
from mixer.services.backend import (
    AudioBackend,
    AudioCommand,
    MoveStream,
    SetDefaultDevice,
    SetMute,
    SetVolume,
)
from mixer.util.logging import get_logger

logger = get_logger("viewmodel")

Listener = Callable[["MixerViewModel"], None]

# Debounce window for volume slider writes (seconds).
_VOLUME_DEBOUNCE_S = 0.05
# Ignore incoming snapshot values for a key while a write is in flight,
# for this many seconds (or until generation catches up).
_FEEDBACK_GUARD_S = 0.4


@dataclass(slots=True)
class PendingVolume:
    """A debounced volume write waiting to be flushed."""

    target: str
    index: int
    volume: float
    generation: int
    due_at: float


@dataclass(frozen=True, slots=True)
class ChannelKey:
    """Stable identity for a controllable channel."""

    kind: str  # "sink" | "source" | "stream"
    index: int


@dataclass(slots=True)
class MixerViewModel:
    """Pure-Python state held between backend snapshots and the GTK UI."""

    backend: AudioBackend
    allow_overamplification: bool = False
    _snapshot: AudioSnapshot = field(default_factory=AudioSnapshot)
    _listeners: list[Listener] = field(default_factory=list)
    _pending_volumes: dict[tuple[str, int], PendingVolume] = field(default_factory=dict)
    _write_generations: dict[tuple[str, int], int] = field(default_factory=dict)
    _write_times: dict[tuple[str, int], float] = field(default_factory=dict)
    _gen_counter: int = 0
    _started: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self.backend.start(self._on_snapshot)
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self.backend.stop()
        self._started = False

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

    def _notify(self) -> None:
        for listener in list(self._listeners):
            try:
                listener(self)
            except Exception:  # noqa: BLE001
                logger.exception("View-model listener failed")

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    @property
    def snapshot(self) -> AudioSnapshot:
        return self._snapshot

    @property
    def connected(self) -> bool:
        return self._snapshot.connected

    @property
    def max_volume(self) -> float:
        return 1.5 if self.allow_overamplification else 1.0

    def sorted_streams(self) -> tuple[StreamInfo, ...]:
        """Streams sorted by name (case-insensitive), then index."""
        return tuple(
            sorted(
                self._snapshot.streams,
                key=lambda s: (s.name.casefold(), s.index),
            )
        )

    def sorted_sinks(self) -> tuple[DeviceInfo, ...]:
        return tuple(
            sorted(
                self._snapshot.sinks,
                key=lambda d: (not d.is_default, d.description.casefold(), d.index),
            )
        )

    def sorted_sources(self) -> tuple[DeviceInfo, ...]:
        return tuple(
            sorted(
                self._snapshot.sources,
                key=lambda d: (not d.is_default, d.description.casefold(), d.index),
            )
        )

    def default_sink(self) -> DeviceInfo | None:
        for sink in self._snapshot.sinks:
            if sink.is_default or sink.name == self._snapshot.default_sink_name:
                return sink
        return self._snapshot.sinks[0] if self._snapshot.sinks else None

    def default_source(self) -> DeviceInfo | None:
        for source in self._snapshot.sources:
            if source.is_default or source.name == self._snapshot.default_source_name:
                return source
        return self._snapshot.sources[0] if self._snapshot.sources else None

    def stream_by_index(self, index: int) -> StreamInfo | None:
        for stream in self._snapshot.streams:
            if stream.index == index:
                return stream
        return None

    def sink_by_index(self, index: int) -> DeviceInfo | None:
        for sink in self._snapshot.sinks:
            if sink.index == index:
                return sink
        return None

    # ------------------------------------------------------------------
    # Diff helpers (for UI row reuse)
    # ------------------------------------------------------------------

    def stream_keys(self) -> set[int]:
        return {s.index for s in self._snapshot.streams}

    def sink_keys(self) -> set[int]:
        return {s.index for s in self._snapshot.sinks}

    def source_keys(self) -> set[int]:
        return {s.index for s in self._snapshot.sources}

    # ------------------------------------------------------------------
    # Write API (commands)
    # ------------------------------------------------------------------

    def set_volume(self, target: str, index: int, volume: float, *, immediate: bool = False) -> None:
        """Queue a volume change. Debounced unless immediate=True."""
        volume = round(VolumeMath.clamp(volume, maximum=self.max_volume), 4)
        key = (target, index)
        self._gen_counter += 1
        generation = self._gen_counter
        self._write_generations[key] = generation
        self._write_times[key] = time.monotonic()

        # Optimistically update local snapshot so the UI stays responsive.
        self._apply_local_volume(target, index, volume)

        if immediate:
            self._pending_volumes.pop(key, None)
            self._submit(
                SetVolume(target=target, index=index, volume=volume, generation=generation)
            )
            self._notify()
            return

        due = time.monotonic() + _VOLUME_DEBOUNCE_S
        self._pending_volumes[key] = PendingVolume(
            target=target,
            index=index,
            volume=volume,
            generation=generation,
            due_at=due,
        )
        self._notify()

    def flush_pending(self, now: float | None = None) -> int:
        """Flush debounced volume writes that are due. Returns count flushed."""
        now = time.monotonic() if now is None else now
        due: list[PendingVolume] = []
        remaining: dict[tuple[str, int], PendingVolume] = {}
        for key, pending in self._pending_volumes.items():
            if pending.due_at <= now:
                due.append(pending)
            else:
                remaining[key] = pending
        self._pending_volumes = remaining
        for pending in due:
            self._submit(
                SetVolume(
                    target=pending.target,
                    index=pending.index,
                    volume=pending.volume,
                    generation=pending.generation,
                )
            )
        return len(due)

    def set_mute(self, target: str, index: int, muted: bool) -> None:
        self._apply_local_mute(target, index, muted)
        self._submit(SetMute(target=target, index=index, muted=muted))
        self._notify()

    def toggle_mute(self, target: str, index: int) -> None:
        current: bool | None = None
        if target == "stream":
            stream = self.stream_by_index(index)
            current = stream.muted if stream else None
        elif target == "sink":
            sink = self.sink_by_index(index)
            current = sink.muted if sink else None
        elif target == "source":
            for source in self._snapshot.sources:
                if source.index == index:
                    current = source.muted
                    break
        if current is None:
            return
        self.set_mute(target, index, not current)

    def move_stream(self, stream_index: int, sink_index: int) -> None:
        streams = tuple(
            replace(s, sink_index=sink_index) if s.index == stream_index else s
            for s in self._snapshot.streams
        )
        self._snapshot = replace(self._snapshot, streams=streams)
        self._submit(MoveStream(stream_index=stream_index, sink_index=sink_index))
        self._notify()

    def set_default_device(self, kind: str, name: str) -> None:
        if kind == "sink":
            sinks = tuple(replace(d, is_default=(d.name == name)) for d in self._snapshot.sinks)
            self._snapshot = replace(
                self._snapshot,
                sinks=sinks,
                default_sink_name=name,
            )
        elif kind == "source":
            sources = tuple(
                replace(d, is_default=(d.name == name)) for d in self._snapshot.sources
            )
            self._snapshot = replace(
                self._snapshot,
                sources=sources,
                default_source_name=name,
            )
        self._submit(SetDefaultDevice(kind=kind, name=name))
        self._notify()

    def set_overamplification(self, enabled: bool) -> None:
        self.allow_overamplification = enabled
        self._notify()

    # ------------------------------------------------------------------
    # Snapshot ingestion
    # ------------------------------------------------------------------

    def _on_snapshot(self, snapshot: AudioSnapshot) -> None:
        # Flush any due debounced writes before merging, so we don't lose them.
        self.flush_pending()
        merged = self._merge_with_guards(snapshot)
        self._snapshot = merged
        self._notify()

    def _merge_with_guards(self, incoming: AudioSnapshot) -> AudioSnapshot:
        """Apply feedback-loop guards so in-flight writes aren't overwritten."""
        now = time.monotonic()

        def guarded_volume(kind: str, index: int, incoming_vol: float, local_vol: float) -> float:
            key = (kind, index)
            write_gen = self._write_generations.get(key)
            write_time = self._write_times.get(key)
            if write_gen is None or write_time is None:
                return incoming_vol
            # Still within guard window: keep local optimistic value.
            if now - write_time < _FEEDBACK_GUARD_S:
                # If pending debounce exists, prefer that volume.
                pending = self._pending_volumes.get(key)
                if pending is not None:
                    return pending.volume
                return local_vol
            # Guard expired — clear and accept incoming.
            self._write_generations.pop(key, None)
            self._write_times.pop(key, None)
            return incoming_vol

        local = self._snapshot
        local_streams = {s.index: s for s in local.streams}
        local_sinks = {s.index: s for s in local.sinks}
        local_sources = {s.index: s for s in local.sources}

        streams = tuple(
            replace(
                s,
                volume=guarded_volume(
                    "stream",
                    s.index,
                    s.volume,
                    local_streams[s.index].volume if s.index in local_streams else s.volume,
                ),
            )
            for s in incoming.streams
        )
        sinks = tuple(
            replace(
                d,
                volume=guarded_volume(
                    "sink",
                    d.index,
                    d.volume,
                    local_sinks[d.index].volume if d.index in local_sinks else d.volume,
                ),
            )
            for d in incoming.sinks
        )
        sources = tuple(
            replace(
                d,
                volume=guarded_volume(
                    "source",
                    d.index,
                    d.volume,
                    local_sources[d.index].volume if d.index in local_sources else d.volume,
                ),
            )
            for d in incoming.sources
        )
        return replace(incoming, streams=streams, sinks=sinks, sources=sources)

    def _apply_local_volume(self, target: str, index: int, volume: float) -> None:
        snap = self._snapshot
        if target == "stream":
            streams = tuple(
                replace(s, volume=volume) if s.index == index else s for s in snap.streams
            )
            self._snapshot = replace(snap, streams=streams)
        elif target == "sink":
            sinks = tuple(
                replace(d, volume=volume) if d.index == index else d for d in snap.sinks
            )
            self._snapshot = replace(snap, sinks=sinks)
        elif target == "source":
            sources = tuple(
                replace(d, volume=volume) if d.index == index else d for d in snap.sources
            )
            self._snapshot = replace(snap, sources=sources)

    def _apply_local_mute(self, target: str, index: int, muted: bool) -> None:
        snap = self._snapshot
        if target == "stream":
            streams = tuple(
                replace(s, muted=muted) if s.index == index else s for s in snap.streams
            )
            self._snapshot = replace(snap, streams=streams)
        elif target == "sink":
            sinks = tuple(
                replace(d, muted=muted) if d.index == index else d for d in snap.sinks
            )
            self._snapshot = replace(snap, sinks=sinks)
        elif target == "source":
            sources = tuple(
                replace(d, muted=muted) if d.index == index else d for d in snap.sources
            )
            self._snapshot = replace(snap, sources=sources)

    def _submit(self, command: AudioCommand) -> None:
        logger.debug("Submit %s", command)
        self.backend.submit(command)
