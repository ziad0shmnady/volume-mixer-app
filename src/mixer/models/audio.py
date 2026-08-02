"""Typed audio domain models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """A sink (output) or source (input) device."""

    index: int
    name: str
    description: str
    volume: float  # 0.0 - 1.5
    muted: bool
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class StreamInfo:
    """A playback (sink-input) or recording (source-output) stream."""

    index: int
    name: str
    media_name: str
    icon_name: str | None
    volume: float  # 0.0 - 1.5
    muted: bool
    sink_index: int
    corked: bool = False
    application_id: str | None = None
    process_binary: str | None = None
    snap_id: str | None = None


@dataclass(frozen=True, slots=True)
class AudioSnapshot:
    """Full audio graph snapshot pushed to the UI."""

    sinks: tuple[DeviceInfo, ...] = ()
    sources: tuple[DeviceInfo, ...] = ()
    streams: tuple[StreamInfo, ...] = ()  # sink inputs (playback)
    default_sink_name: str | None = None
    default_source_name: str | None = None
    connected: bool = True
    generation: int = 0


@dataclass(frozen=True, slots=True)
class VolumeMath:
    """Helpers for volume conversion and formatting."""

    @staticmethod
    def clamp(value: float, minimum: float = 0.0, maximum: float = 1.5) -> float:
        """Clamp a linear volume into [minimum, maximum]."""
        return max(minimum, min(maximum, value))

    @staticmethod
    def to_percent(volume: float) -> int:
        """Convert linear volume (1.0 = 100%) to nearest integer percent."""
        return int(round(VolumeMath.clamp(volume) * 100))

    @staticmethod
    def from_percent(percent: float, maximum: float = 1.0) -> float:
        """Convert percent (0-150) to linear volume, clamped to maximum."""
        return VolumeMath.clamp(percent / 100.0, maximum=maximum)

    @staticmethod
    def format_percent(volume: float) -> str:
        """Human-readable percent label."""
        return f"{VolumeMath.to_percent(volume)}%"
