"""Runtime environment helpers (snap vs native install)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SNAP_NAME = "volume-mixer"


def is_snap() -> bool:
    """Return True when running inside a Snap confinement."""
    return bool(os.environ.get("SNAP"))


def mixer_launcher() -> str:
    """Return the command used for autostart and GNOME global shortcuts."""
    env = os.environ.get("MIXER_EXEC", "").strip()
    if env:
        return env

    if is_snap():
        return f"/snap/bin/{os.environ.get('SNAP_NAME', SNAP_NAME)}"

    snap_bin = Path(f"/snap/bin/{SNAP_NAME}")
    if snap_bin.is_file():
        return str(snap_bin)

    argv0 = Path(sys.argv[0]).resolve()
    if argv0.is_file() and argv0.name == "mixer":
        return str(argv0)

    venv = Path(__file__).resolve().parents[3] / ".venv" / "bin" / "mixer"
    if venv.is_file():
        return str(venv)

    return "mixer"


def mixer_command(*args: str) -> str:
    """Build a shell command line for the mixer launcher."""
    parts = [mixer_launcher(), *args]
    return " ".join(parts)
