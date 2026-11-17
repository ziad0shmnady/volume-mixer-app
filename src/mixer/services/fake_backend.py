"""In-memory audio backend for tests and UI development without Pulse."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from mixer.models.audio import AudioSnapshot, ClientInfo, DeviceInfo, StreamInfo, VolumeMath
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
            app_key="bin:chrome",
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
            app_key="bin:firefox",
        ),
    )
    clients = (
        ClientInfo(index=50, name="Google Chrome", app_key="bin:chrome", process_binary="chrome"),
        ClientInfo(index=51, name="Firefox", app_key="bin:firefox", process_binary="firefox"),
        # Connected but silent: shown as idle apps.
        ClientInfo(
            index=52,
            name="Discord",
            app_key="snap:discord",
            icon_name="discord",
            process_binary="Discord",
            snap_id="discord",
        ),
        ClientInfo(index=53, name="Slack", app_key="bin:slack", icon_name="slack", process_binary="slack"),
    )
    return AudioSnapshot(
        sinks=sinks,
        sources=sources,
        streams=streams,
        clients=clients,
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
                self._snapshot = replace(default_snapshot(), generation=self._generation)
            snap = self._snapshot
            callback = self._on_snapshot
        if callback is not None:
            callback(snap)

    def push_snapshot(self, snapshot: AudioSnapshot) -> None:
        """Replace the current snapshot and notify listeners."""
        with self._lock:
            self._generation += 1
            self._snapshot = replace(snapshot, generation=self._generation)
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
            volume = VolumeMath.clamp(command.volume)
            snap = self._map_target(
                snap, command.target, command.index, lambda obj: replace(obj, volume=volume)
            )
        elif isinstance(command, SetMute):
            snap = self._map_target(
                snap, command.target, command.index, lambda obj: replace(obj, muted=command.muted)
            )
        elif isinstance(command, MoveStream):
            snap = self._map_target(
                snap,
                "stream",
                command.stream_index,
                lambda obj: replace(obj, sink_index=command.sink_index),
            )
        elif isinstance(command, SetDefaultDevice):
            if command.kind == "sink":
                snap = replace(
                    snap,
                    sinks=tuple(replace(d, is_default=(d.name == command.name)) for d in snap.sinks),
                    default_sink_name=command.name,
                )
            else:
                snap = replace(
                    snap,
                    sources=tuple(
                        replace(d, is_default=(d.name == command.name)) for d in snap.sources
                    ),
                    default_source_name=command.name,
                )

        self._snapshot = replace(snap, generation=self._generation)

    @staticmethod
    def _map_target(
        snap: AudioSnapshot,
        target: str,
        index: int,
        update: Callable[[Any], Any],
    ) -> AudioSnapshot:
        if target == "sink":
            return replace(
                snap, sinks=tuple(update(d) if d.index == index else d for d in snap.sinks)
            )
        if target == "source":
            return replace(
                snap, sources=tuple(update(d) if d.index == index else d for d in snap.sources)
            )
        return replace(
            snap, streams=tuple(update(s) if s.index == index else s for s in snap.streams)
        )
