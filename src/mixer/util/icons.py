"""Icon resolution helpers."""

from __future__ import annotations

from collections.abc import Callable

from mixer.models.audio import StreamInfo
from mixer.util.stream_names import BINARY_ICON_ALIASES

_FALLBACK = "application-x-executable-symbolic"
_GENERIC_CANDIDATES = (
    "audio-x-generic",
    "audio-volume-high-symbolic",
    "multimedia-player",
    _FALLBACK,
)


def candidate_icon_names(stream: StreamInfo) -> list[str]:
    """Ordered icon name candidates for a playback stream."""
    names: list[str] = []

    def _add(value: str | None) -> None:
        if not value:
            return
        if value not in names:
            names.append(value)
        base = value.split("/")[-1]
        if base and base not in names:
            names.append(base)

    _add(stream.icon_name)
    _add(stream.application_id)
    _add(stream.process_binary)

    binary = (stream.process_binary or "").split("/")[-1].casefold()
    for alias in BINARY_ICON_ALIASES.get(binary, ()):
        _add(alias)

    display_key = stream.name.casefold().replace(" ", "-")
    for alias in BINARY_ICON_ALIASES.get(display_key, ()):
        _add(alias)
    _add(display_key)

    for generic in _GENERIC_CANDIDATES:
        _add(generic)
    return names


def resolve_icon_name(
    stream: StreamInfo,
    has_icon: Callable[[str], bool] | None = None,
) -> str:
    """Pick the first icon theme name that exists, or a fallback.

    ``has_icon`` is optional: ``Callable[[str], bool]``. When omitted, the
    first candidate is returned (useful in tests without GTK).
    """
    candidates = candidate_icon_names(stream)
    if has_icon is None:
        return candidates[0]
    for name in candidates:
        try:
            if has_icon(name):
                return name
        except Exception:  # noqa: BLE001
            continue
    return _FALLBACK
