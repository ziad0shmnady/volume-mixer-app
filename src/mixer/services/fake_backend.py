"""In-memory audio backend for tests and UI development without Pulse."""

from __future__ import annotations

import threading

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

logger = get_logger("services.fake")


def default_snapshot() -> AudioSnapshot:
    """A realistic starter snapshot for FakeBackend."""
    sinks = (
        DeviceInfo(
            index=1,
            name="alsa_output.speakers",
            description="Built-in Speakers",
            volume=0.75,
            muted=False,
            is_default=True,
        ),
        DeviceInfo(
            index=2,
            name="alsa_output.headphones",
            description="Headphones",
            volume=1.0,
            muted=False,
            is_default=False,
        ),
    )
    sources = (
        DeviceInfo(
            index=10,
            name="alsa_input.mic",
            description="Built-in Microphone",
            volume=0.5,
            muted=False,
            is_default=True,
        ),
    )
    streams = (
        StreamInfo(
            index=100,
            name="Google Chrome",
            media_name="YouTube",
            icon_name="google-chrome",
            volume=0.8,
            muted=False,
            sink_index=1,
            corked=False,
            application_id="google-chrome",
            process_binary="chrome",
        ),
        StreamInfo(
            index=101,
            name="Firefox",
            media_name="Playback",
            icon_name="firefox",
            volume=0.4,
            muted=False,
            sink_index=1,
            corked=False,
            application_id="firefox",
            process_binary="firefox",
        ),
    )
    return AudioSnapshot(
        sinks=sinks,
        sources=sources,
        streams=streams,
        default_sink_name="alsa_output.speakers",
        default_source_name="alsa_input.mic",
        connected=True,
        generation=1,
    )


class FakeBackend:
    """Scriptable AudioBackend used by unit tests."""

    def __init__(self, snapshot: AudioSnapshot | None = None) -> None:
        self._lock = threading.RLock()
        self._snapshot = snapshot or default_snapshot()
        self._on_snapshot: SnapshotCallback | None = None
        self._commands: list[AudioCommand] = []
        self._started = False
        self._generation = self._snapshot.generation

    @property
    def commands(self) -> list[AudioCommand]:
        with self._lock:
            return list(self._commands)

    @property
    def snapshot(self) -> AudioSnapshot:
        with self._lock:
            return self._snapshot

    def start(self, on_snapshot: SnapshotCallback) -> None:
        with self._lock:
            self._on_snapshot = on_snapshot
            self._started = True
            snap = self._snapshot
        on_snapshot(snap)

    def stop(self) -> None:
        with self._lock:
            self._started = False
            self._on_snapshot = None

    def submit(self, command: AudioCommand) -> None:
        with self._lock:
            self._commands.append(command)
            self._apply(command)
            snap = self._snapshot
            callback = self._on_snapshot
        if callback is not None:
            callback(snap)

    def request_snapshot(self) -> None:
        with self._lock:
            callback = self._on_snapshot
            snap = self._snapshot
        if callback is not None:
            callback(snap)

    def set_connected(self, connected: bool) -> None:
        """Simulate disconnect / reconnect for tests."""
        with self._lock:
            self._generation += 1
            if not connected:
                self._snapshot = AudioSnapshot(
                    connected=False,
                    generation=self._generation,
                )
            else:
                base = default_snapshot()
                self._snapshot = AudioSnapshot(
                    sinks=base.sinks,
                    sources=base.sources,
                    streams=base.streams,
                    default_sink_name=base.default_sink_name,
                    default_source_name=base.default_source_name,
                    connected=True,
                    generation=self._generation,
                )
            snap = self._snapshot
            callback = self._on_snapshot
        if callback is not None:
            callback(snap)

    def push_snapshot(self, snapshot: AudioSnapshot) -> None:
        """Replace the current snapshot and notify listeners."""
        with self._lock:
            self._generation += 1
            self._snapshot = AudioSnapshot(
                sinks=snapshot.sinks,
                sources=snapshot.sources,
                streams=snapshot.streams,
                default_sink_name=snapshot.default_sink_name,
                default_source_name=snapshot.default_source_name,
                connected=snapshot.connected,
                generation=self._generation,
            )
            snap = self._snapshot
            callback = self._on_snapshot
        if callback is not None:
            callback(snap)

    def clear_commands(self) -> None:
        with self._lock:
            self._commands.clear()

    def _apply(self, command: AudioCommand) -> None:
        self._generation += 1
        snap = self._snapshot

        if isinstance(command, SetVolume):
            snap = self._map_volume(snap, command)
        elif isinstance(command, SetMute):
            snap = self._map_mute(snap, command)
        elif isinstance(command, MoveStream):
            streams = tuple(
                StreamInfo(
                    index=s.index,
                    name=s.name,
                    media_name=s.media_name,
                    icon_name=s.icon_name,
                    volume=s.volume,
                    muted=s.muted,
                    sink_index=command.sink_index if s.index == command.stream_index else s.sink_index,
                    corked=s.corked,
                    application_id=s.application_id,
                    process_binary=s.process_binary,
                )
                for s in snap.streams
            )
            snap = AudioSnapshot(
                sinks=snap.sinks,
                sources=snap.sources,
                streams=streams,
                default_sink_name=snap.default_sink_name,
                default_source_name=snap.default_source_name,
                connected=snap.connected,
                generation=self._generation,
            )
        elif isinstance(command, SetDefaultDevice):
            if command.kind == "sink":
                sinks = tuple(
                    DeviceInfo(
                        index=d.index,
                        name=d.name,
                        description=d.description,
                        volume=d.volume,
                        muted=d.muted,
                        is_default=(d.name == command.name),
                    )
                    for d in snap.sinks
                )
                snap = AudioSnapshot(
                    sinks=sinks,
                    sources=snap.sources,
                    streams=snap.streams,
                    default_sink_name=command.name,
                    default_source_name=snap.default_source_name,
                    connected=snap.connected,
                    generation=self._generation,
                )
            else:
                sources = tuple(
                    DeviceInfo(
                        index=d.index,
                        name=d.name,
                        description=d.description,
                        volume=d.volume,
                        muted=d.muted,
                        is_default=(d.name == command.name),
                    )
                    for d in snap.sources
                )
                snap = AudioSnapshot(
                    sinks=snap.sinks,
                    sources=sources,
                    streams=snap.streams,
                    default_sink_name=snap.default_sink_name,
                    default_source_name=command.name,
                    connected=snap.connected,
                    generation=self._generation,
                )

        self._snapshot = snap

    def _map_volume(self, snap: AudioSnapshot, command: SetVolume) -> AudioSnapshot:
        volume = VolumeMath.clamp(command.volume)
        if command.target == "sink":
            sinks = tuple(
                DeviceInfo(
                    index=d.index,
                    name=d.name,
                    description=d.description,
                    volume=volume if d.index == command.index else d.volume,
                    muted=d.muted,
                    is_default=d.is_default,
                )
                for d in snap.sinks
            )
            return AudioSnapshot(
                sinks=sinks,
                sources=snap.sources,
                streams=snap.streams,
                default_sink_name=snap.default_sink_name,
                default_source_name=snap.default_source_name,
                connected=snap.connected,
                generation=self._generation,
            )
        if command.target == "source":
            sources = tuple(
                DeviceInfo(
                    index=d.index,
                    name=d.name,
                    description=d.description,
                    volume=volume if d.index == command.index else d.volume,
                    muted=d.muted,
                    is_default=d.is_default,
                )
                for d in snap.sources
            )
            return AudioSnapshot(
                sinks=snap.sinks,
                sources=sources,
                streams=snap.streams,
                default_sink_name=snap.default_sink_name,
                default_source_name=snap.default_source_name,
                connected=snap.connected,
                generation=self._generation,
            )
        streams = tuple(
            StreamInfo(
                index=s.index,
                name=s.name,
                media_name=s.media_name,
                icon_name=s.icon_name,
                volume=volume if s.index == command.index else s.volume,
                muted=s.muted,
                sink_index=s.sink_index,
                corked=s.corked,
                application_id=s.application_id,
                process_binary=s.process_binary,
            )
            for s in snap.streams
        )
        return AudioSnapshot(
            sinks=snap.sinks,
            sources=snap.sources,
            streams=streams,
            default_sink_name=snap.default_sink_name,
            default_source_name=snap.default_source_name,
            connected=snap.connected,
            generation=self._generation,
        )

    def _map_mute(self, snap: AudioSnapshot, command: SetMute) -> AudioSnapshot:
        if command.target == "sink":
            sinks = tuple(
                DeviceInfo(
                    index=d.index,
                    name=d.name,
                    description=d.description,
                    volume=d.volume,
                    muted=command.muted if d.index == command.index else d.muted,
                    is_default=d.is_default,
                )
                for d in snap.sinks
            )
            return AudioSnapshot(
                sinks=sinks,
                sources=snap.sources,
                streams=snap.streams,
                default_sink_name=snap.default_sink_name,
                default_source_name=snap.default_source_name,
                connected=snap.connected,
                generation=self._generation,
            )
        if command.target == "source":
            sources = tuple(
                DeviceInfo(
                    index=d.index,
                    name=d.name,
                    description=d.description,
                    volume=d.volume,
                    muted=command.muted if d.index == command.index else d.muted,
                    is_default=d.is_default,
                )
                for d in snap.sources
            )
            return AudioSnapshot(
                sinks=snap.sinks,
                sources=sources,
                streams=snap.streams,
                default_sink_name=snap.default_sink_name,
                default_source_name=snap.default_source_name,
                connected=snap.connected,
                generation=self._generation,
            )
        streams = tuple(
            StreamInfo(
                index=s.index,
                name=s.name,
                media_name=s.media_name,
                icon_name=s.icon_name,
                volume=s.volume,
                muted=command.muted if s.index == command.index else s.muted,
                sink_index=s.sink_index,
                corked=s.corked,
                application_id=s.application_id,
                process_binary=s.process_binary,
            )
            for s in snap.streams
        )
        return AudioSnapshot(
            sinks=snap.sinks,
            sources=snap.sources,
            streams=streams,
            default_sink_name=snap.default_sink_name,
            default_source_name=snap.default_source_name,
            connected=snap.connected,
            generation=self._generation,
        )
