"""View-model: snapshot diffing, sorting, debounce, feedback-loop guard."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Callable

from mixer.models.audio import (
    AppInfo,
    AppPreference,
    AudioSnapshot,
    ClientInfo,
    DeviceInfo,
    StreamInfo,
    VolumeMath,
)
from mixer.services.backend import (
    AudioBackend,
    AudioCommand,
    MoveStream,
    SetDefaultDevice,
    SetMute,
    SetVolume,
)
from mixer.util.logging import get_logger
from mixer.util.stream_names import known_app_name

logger = get_logger("viewmodel")

Listener = Callable[["MixerViewModel"], None]

# Debounce window for volume slider writes (seconds).
_VOLUME_DEBOUNCE_S = 0.05
# Ignore incoming snapshot values for a key while a write is in flight,
# for this many seconds (or until generation catches up).
_FEEDBACK_GUARD_S = 0.4
# Volume differences below this are treated as equal (pulse rounds volumes).
_VOLUME_EPSILON = 0.005


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
    # Volume/mute the user chose per app (keyed by app key); applied to the
    # app's new streams so silent apps can be set ahead of time.
    app_preferences: dict[str, AppPreference] = field(default_factory=dict)
    # Called whenever app_preferences changes (for persistence).
    on_app_preferences_changed: Callable[[], None] | None = None
    _snapshot: AudioSnapshot = field(default_factory=AudioSnapshot)
    _listeners: list[Listener] = field(default_factory=list)
    _pending_volumes: dict[tuple[str, int], PendingVolume] = field(default_factory=dict)
    _write_generations: dict[tuple[str, int], int] = field(default_factory=dict)
    _write_times: dict[tuple[str, int], float] = field(default_factory=dict)
    _mute_write_times: dict[tuple[str, int], float] = field(default_factory=dict)
    _known_streams: set[int] = field(default_factory=set)
    # Last volume/mute each app actually played at, shown while it is silent.
    _last_heard: dict[str, AppPreference] = field(default_factory=dict)
    # The first snapshot of a connection only records which streams exist;
    # remembered app volumes are applied to streams that appear after it.
    _awaiting_baseline: bool = True
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

    def apps(self) -> tuple[AppInfo, ...]:
        """Every application with sound: playing ones and silent connected ones.

        Streams and clients of the same app are merged into one entry, sorted
        by name so rows don't jump around as apps start and stop playing.
        """
        streams_by_key: dict[str, list[StreamInfo]] = {}
        for stream in sorted(self._snapshot.streams, key=lambda s: s.index):
            streams_by_key.setdefault(stream.group_key, []).append(stream)
        clients_by_key: dict[str, list[ClientInfo]] = {}
        for client in sorted(self._snapshot.clients, key=lambda c: c.index):
            clients_by_key.setdefault(client.app_key, []).append(client)

        apps = [
            self._build_app(key, streams_by_key.get(key, []), clients_by_key.get(key, []))
            for key in streams_by_key.keys() | clients_by_key.keys()
        ]
        return tuple(sorted(apps, key=lambda a: (a.name.casefold(), a.key)))

    def app_by_key(self, key: str) -> AppInfo | None:
        for app in self.apps():
            if app.key == key:
                return app
        return None

    def _build_app(
        self,
        key: str,
        streams: list[StreamInfo],
        clients: list[ClientInfo],
    ) -> AppInfo:
        # Prefer client metadata for naming: clients outlive individual streams,
        # so the title stays put when the app starts/stops playing.
        members: list[StreamInfo | ClientInfo] = [*clients, *streams]
        ref = members[0]
        name = known_app_name(ref.snap_id, ref.process_binary) or ref.name

        def _first(attr: str) -> str | None:
            for member in members:
                value = getattr(member, attr)
                if value:
                    return value
            return None

        if streams:
            volume = max(s.volume for s in streams)
            muted = all(s.muted for s in streams)
            sink_index: int | None = streams[0].sink_index
            media = list(dict.fromkeys(s.media_name for s in streams if s.media_name))
            if len(streams) > 1 and len(media) != 1:
                subtitle = f"{len(streams)} streams"
            else:
                subtitle = media[0] if media else "Playing"
        else:
            pref = self.app_preferences.get(key) or self._last_heard.get(key) or AppPreference()
            volume = pref.volume
            muted = pref.muted
            sink_index = None
            subtitle = "Not playing"

        return AppInfo(
            key=key,
            name=name,
            subtitle=subtitle,
            volume=volume,
            muted=muted,
            stream_indices=tuple(s.index for s in streams),
            sink_index=sink_index,
            icon_name=_first("icon_name"),
            application_id=_first("application_id"),
            process_binary=_first("process_binary"),
            snap_id=_first("snap_id"),
        )

    def _streams_for_app(self, key: str) -> list[StreamInfo]:
        return [s for s in self._snapshot.streams if s.group_key == key]

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
        self._mute_write_times[(target, index)] = time.monotonic()
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

    def set_app_volume(self, key: str, volume: float) -> None:
        """Set an app's volume: all its streams now, and new ones later."""
        volume = round(VolumeMath.clamp(volume, maximum=self.max_volume), 4)
        self._remember_app(key, volume=volume)
        streams = self._streams_for_app(key)
        for stream in streams:
            self.set_volume("stream", stream.index, volume)
        if not streams:
            self._notify()

    def set_app_mute(self, key: str, muted: bool) -> None:
        """Mute/unmute an app: all its streams now, and new ones later."""
        self._remember_app(key, muted=muted)
        streams = self._streams_for_app(key)
        for stream in streams:
            self.set_mute("stream", stream.index, muted)
        if not streams:
            self._notify()

    def move_app(self, key: str, sink_index: int) -> None:
        """Move every playing stream of an app to another output."""
        for stream in self._streams_for_app(key):
            self.move_stream(stream.index, sink_index)

    def _remember_app(
        self,
        key: str,
        *,
        volume: float | None = None,
        muted: bool | None = None,
    ) -> None:
        current = self.app_preferences.get(key)
        if current is None:
            app = self.app_by_key(key)
            current = AppPreference(
                volume=app.volume if app is not None else 1.0,
                muted=app.muted if app is not None else False,
            )
        updated = AppPreference(
            volume=current.volume if volume is None else volume,
            muted=current.muted if muted is None else muted,
        )
        if updated != self.app_preferences.get(key):
            self.app_preferences[key] = updated
            self._app_preferences_changed()

    def _app_preferences_changed(self) -> None:
        if self.on_app_preferences_changed is None:
            return
        try:
            self.on_app_preferences_changed()
        except Exception:  # noqa: BLE001
            logger.exception("App preference listener failed")

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

        if not merged.connected:
            # Stream indices are per connection; start over after reconnect.
            self._known_streams = set()
            self._awaiting_baseline = True
            self._notify()
            return

        current = {s.index for s in merged.streams}
        new_streams = [s for s in merged.streams if s.index not in self._known_streams]
        self._known_streams = current
        self._forget_vanished_streams(current)
        if self._awaiting_baseline:
            self._awaiting_baseline = False
        else:
            self._apply_app_preferences(new_streams)
        self._sync_app_preferences()
        self._remember_last_heard()
        self._notify()

    def _remember_last_heard(self) -> None:
        by_key: dict[str, list[StreamInfo]] = {}
        for stream in self._snapshot.streams:
            by_key.setdefault(stream.group_key, []).append(stream)
        for key, streams in by_key.items():
            self._last_heard[key] = AppPreference(
                volume=max(s.volume for s in streams),
                muted=all(s.muted for s in streams),
            )

    def _apply_app_preferences(self, new_streams: list[StreamInfo]) -> None:
        """Give freshly started streams the volume/mute the user chose for the app."""
        for stream in new_streams:
            pref = self.app_preferences.get(stream.group_key)
            if pref is None:
                continue
            volume = VolumeMath.clamp(pref.volume, maximum=self.max_volume)
            if abs(stream.volume - volume) > _VOLUME_EPSILON:
                logger.debug("Applying remembered volume %.2f to stream #%s", volume, stream.index)
                self.set_volume("stream", stream.index, volume, immediate=True)
            if stream.muted != pref.muted:
                self.set_mute("stream", stream.index, pref.muted)

    def _sync_app_preferences(self) -> None:
        """Track changes made elsewhere (other mixers, the app itself).

        Without this a stale remembered value would override, on the next new
        stream, a volume the user picked in another tool.
        """
        changed = False
        for key, pref in list(self.app_preferences.items()):
            streams = self._streams_for_app(key)
            if not streams or any(self._write_in_flight(s.index) for s in streams):
                continue
            observed = AppPreference(
                volume=max(s.volume for s in streams),
                muted=all(s.muted for s in streams),
            )
            if (
                abs(observed.volume - pref.volume) > _VOLUME_EPSILON
                or observed.muted != pref.muted
            ):
                self.app_preferences[key] = observed
                changed = True
        if changed:
            self._app_preferences_changed()

    def _write_in_flight(self, stream_index: int) -> bool:
        key = ("stream", stream_index)
        if key in self._pending_volumes:
            return True
        now = time.monotonic()
        for times in (self._write_times, self._mute_write_times):
            written = times.get(key)
            if written is not None and now - written < _FEEDBACK_GUARD_S:
                return True
        return False

    def _forget_vanished_streams(self, current: set[int]) -> None:
        for table in (
            self._pending_volumes,
            self._write_generations,
            self._write_times,
            self._mute_write_times,
        ):
            for key in [k for k in table if k[0] == "stream" and k[1] not in current]:
                table.pop(key, None)

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

        def guarded_mute(kind: str, index: int, incoming_muted: bool, local_muted: bool) -> bool:
            key = (kind, index)
            write_time = self._mute_write_times.get(key)
            if write_time is None:
                return incoming_muted
            if now - write_time < _FEEDBACK_GUARD_S:
                return local_muted
            self._mute_write_times.pop(key, None)
            return incoming_muted

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
                muted=guarded_mute(
                    "stream",
                    s.index,
                    s.muted,
                    local_streams[s.index].muted if s.index in local_streams else s.muted,
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
                muted=guarded_mute(
                    "sink",
                    d.index,
                    d.muted,
                    local_sinks[d.index].muted if d.index in local_sinks else d.muted,
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
                muted=guarded_mute(
                    "source",
                    d.index,
                    d.muted,
                    local_sources[d.index].muted if d.index in local_sources else d.muted,
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
