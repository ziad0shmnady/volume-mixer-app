"""Audio backend protocol and command types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from mixer.models.audio import AudioSnapshot


# ---------------------------------------------------------------------------
# Commands (UI -> backend)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SetVolume:
    """Set volume for a sink, source, or sink-input."""

    target: str  # "sink" | "source" | "stream"
    index: int
    volume: float  # 0.0 - 1.5
    generation: int = 0


@dataclass(frozen=True, slots=True)
class SetMute:
    """Mute or unmute a sink, source, or sink-input."""

    target: str  # "sink" | "source" | "stream"
    index: int
    muted: bool


@dataclass(frozen=True, slots=True)
class MoveStream:
    """Move a sink-input to another sink."""

    stream_index: int
    sink_index: int


@dataclass(frozen=True, slots=True)
class SetDefaultDevice:
    """Set the default sink or source by name."""

    kind: str  # "sink" | "source"
    name: str


AudioCommand = SetVolume | SetMute | MoveStream | SetDefaultDevice

SnapshotCallback = Callable[[AudioSnapshot], None]


@runtime_checkable
class AudioBackend(Protocol):
    """Protocol for audio backends used by the view-model / UI."""

    def start(self, on_snapshot: SnapshotCallback) -> None:
        """Start the backend and begin delivering snapshots."""
        ...

    def stop(self) -> None:
        """Stop the backend and release resources."""
        ...

    def submit(self, command: AudioCommand) -> None:
        """Enqueue a command for asynchronous execution."""
        ...

    def request_snapshot(self) -> None:
        """Request an immediate snapshot refresh."""
        ...
