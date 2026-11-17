"""Icon resolution helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from mixer.util.stream_names import BINARY_ICON_ALIASES


class IconSource(Protocol):
    """Anything that identifies an app: a StreamInfo, ClientInfo or AppInfo."""

    @property
    def name(self) -> str: ...
    @property
    def icon_name(self) -> str | None: ...
    @property
    def application_id(self) -> str | None: ...
    @property
    def process_binary(self) -> str | None: ...
    @property
    def snap_id(self) -> str | None: ...

_FALLBACK = "application-x-executable-symbolic"
_GENERIC_CANDIDATES = (
    "audio-x-generic",
    "audio-volume-high-symbolic",
    "multimedia-player",
    _FALLBACK,
)

_DESKTOP_DIRS = (
    Path("/var/lib/snapd/desktop/applications"),
    Path("/usr/share/applications"),
    Path("/var/lib/flatpak/exports/share/applications"),
    Path.home() / ".local/share/flatpak/exports/share/applications",
    Path.home() / ".local/share/applications",
)

_desktop_icon_cache: dict[str, str] | None = None
_icon_name_cache: dict[tuple[object, ...], str] = {}


def candidate_icon_names(stream: IconSource) -> list[str]:
    """Ordered icon theme name candidates for an application."""
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

    if stream.snap_id:
        _add(stream.snap_id)
        _add(f"{stream.snap_id}_{stream.snap_id}")

    display_key = stream.name.casefold().replace(" ", "-")
    for alias in BINARY_ICON_ALIASES.get(display_key, ()):
        _add(alias)
    _add(display_key)

    for generic in _GENERIC_CANDIDATES:
        _add(generic)
    return names


def _snap_icon_path(snap_id: str) -> str | None:
    snap = snap_id.strip().casefold()
    if not snap:
        return None
    candidates = (
        Path(f"/snap/{snap}/current/meta/gui/icon.png"),
        Path(f"/snap/{snap}/current/usr/share/pixmaps/{snap}.png"),
        Path(f"/snap/{snap}/current/usr/share/pixmaps/{snap_id}.png"),
    )
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def _parse_desktop_icon(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("Icon="):
            icon = line.split("=", 1)[1].strip()
            return icon or None
    return None


def _desktop_icon_index() -> dict[str, str]:
    global _desktop_icon_cache
    if _desktop_icon_cache is not None:
        return _desktop_icon_cache

    index: dict[str, str] = {}
    for desktop_dir in _DESKTOP_DIRS:
        if not desktop_dir.is_dir():
            continue
        try:
            entries = list(desktop_dir.glob("*.desktop"))
        except OSError:
            continue
        for desktop_path in entries:
            icon = _parse_desktop_icon(desktop_path)
            if not icon:
                continue
            stem = desktop_path.stem.casefold()
            index.setdefault(stem, icon)
            try:
                text = desktop_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                if line.startswith("X-SnapAppName="):
                    index.setdefault(line.split("=", 1)[1].strip().casefold(), icon)
                elif line.startswith("StartupWMClass="):
                    index.setdefault(line.split("=", 1)[1].strip().casefold(), icon)
    _desktop_icon_cache = index
    return index


def _resolve_desktop_icon(*keys: str | None) -> str | None:
    index = _desktop_icon_index()
    for key in keys:
        if not key:
            continue
        icon = index.get(key.strip().casefold())
        if icon:
            if Path(icon).is_file():
                return icon
            return icon
    return None


def resolve_icon_file(stream: IconSource) -> str | None:
    """Return an absolute icon file path when theme icons are unavailable."""
    if stream.snap_id:
        snap_icon = _snap_icon_path(stream.snap_id)
        if snap_icon:
            return snap_icon

    binary = (stream.process_binary or "").split("/")[-1]
    desktop_icon = _resolve_desktop_icon(
        stream.snap_id,
        stream.application_id,
        binary,
        binary.casefold(),
        stream.name,
        stream.name.casefold().replace(" ", "-"),
        f"{stream.snap_id}_{stream.snap_id}" if stream.snap_id else None,
    )
    if desktop_icon and Path(desktop_icon).is_file():
        return desktop_icon
    return None


def _stream_icon_cache_key(stream: IconSource) -> tuple[object, ...]:
    return (
        stream.snap_id,
        stream.process_binary,
        stream.name,
        stream.icon_name,
        stream.application_id,
    )


def resolve_icon_name(
    stream: IconSource,
    has_icon: Callable[[str], bool] | None = None,
) -> str:
    """Pick the first icon theme name that exists, or a fallback.

    ``has_icon`` is optional: ``Callable[[str], bool]``. When omitted, the
    first candidate is returned (useful in tests without GTK).
    """
    cache_key = _stream_icon_cache_key(stream)
    if has_icon is not None:
        cached = _icon_name_cache.get(cache_key)
        if cached is not None:
            return cached

    icon_file = resolve_icon_file(stream)
    if icon_file:
        result = icon_file
    else:
        candidates = candidate_icon_names(stream)
        if has_icon is None:
            result = candidates[0]
        else:
            result = _FALLBACK
            for name in candidates:
                if Path(name).is_file():
                    result = name
                    break
                try:
                    if has_icon(name):
                        result = name
                        break
                except Exception:  # noqa: BLE001
                    continue

    if has_icon is not None:
        _icon_name_cache[cache_key] = result
    return result


def apply_icon(image: object, icon: str) -> None:
    """Set a Gtk.Image from a theme name or absolute file path."""
    if Path(icon).is_file():
        image.set_from_file(icon)  # type: ignore[attr-defined]
    else:
        image.set_from_icon_name(icon)  # type: ignore[attr-defined]
