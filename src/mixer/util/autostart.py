"""XDG autostart (.desktop) helpers."""

from __future__ import annotations

import shlex
import shutil
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


def _exec_line(minimized: bool) -> str:
    exec_path = _resolve_exec()
    return f"{exec_path} --background" if minimized else exec_path


def _launcher_runnable(exec_path: str) -> bool:
    """True if login can actually start this command."""
    if exec_path.startswith("/snap/bin/"):
        return True  # snapd wrapper; may not resolve from inside confinement
    if Path(exec_path).is_absolute():
        return Path(exec_path).is_file()
    return shutil.which(exec_path) is not None


def refresh_autostart_entry(*, minimized: bool = True) -> bool:
    """Point an enabled autostart entry at the launcher that is running now.

    The entry stores an absolute path; if the app was moved or reinstalled
    elsewhere it would silently fail at every login. Only the ``Exec=`` line is
    rewritten so hand-made tweaks (e.g. a start delay) survive. Returns True
    when the file was changed.
    """
    if not is_autostart_enabled():
        return False
    exec_line = _exec_line(minimized)
    if not _launcher_runnable(shlex.split(exec_line)[0]):
        logger.warning("Not updating autostart: launcher %r not found", exec_line)
        return False
    path = autostart_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    updated = [f"Exec={exec_line}" if line.startswith("Exec=") else line for line in lines]
    if not any(line.startswith("Exec=") for line in lines):
        updated.insert(1, f"Exec={exec_line}")
    if updated == lines:
        return False
    try:
        path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to update autostart entry: %s", exc)
        return False
    logger.info("Updated autostart entry to run %s", exec_line)
    return True


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

    args = _exec_line(minimized)
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
