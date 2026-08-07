"""XDG autostart (.desktop) helpers."""

from __future__ import annotations

from pathlib import Path

from mixer.util.logging import get_logger
from mixer.util.runtime import mixer_launcher

logger = get_logger("util.autostart")

AUTOSTART_ID = "io.github.ziad.Mixer.desktop"


def _autostart_dir() -> Path:
    return Path.home() / ".config" / "autostart"


def autostart_path() -> Path:
    return _autostart_dir() / AUTOSTART_ID


def is_autostart_enabled() -> bool:
    path = autostart_path()
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    for line in text.splitlines():
        if line.strip().lower() == "hidden=true":
            return False
        if line.strip().lower() == "x-gnome-autostart-enabled=false":
            return False
    return "Type=Application" in text


def _resolve_exec() -> str:
    """Best-effort path to the mixer launcher."""
    return mixer_launcher()


def set_autostart_enabled(enabled: bool, *, minimized: bool = True) -> None:
    """Create or remove the XDG autostart entry."""
    path = autostart_path()
    if not enabled:
        try:
            if path.is_file():
                path.unlink()
                logger.info("Removed autostart entry %s", path)
        except OSError as exc:
            logger.warning("Failed to remove autostart entry: %s", exc)
        return

    exec_path = _resolve_exec()
    args = f"{exec_path} --background" if minimized else exec_path
    icon = "io.github.ziad.Mixer"
    content = f"""[Desktop Entry]
Type=Application
Name=Volume Mixer
Comment=Per-application volume mixer (start on login)
Exec={args}
Icon={icon}
Terminal=false
Categories=AudioVideo;Audio;Settings;
X-GNOME-Autostart-enabled=true
StartupNotify=false
"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info("Wrote autostart entry %s", path)
    except OSError as exc:
        logger.warning("Failed to write autostart entry: %s", exc)
