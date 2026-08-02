"""Persistent user settings (JSON under XDG config)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from mixer.util.logging import get_logger

logger = get_logger("util.settings")

DEFAULT_MUTE_INPUT_ACCEL = "<Primary><Shift>m"


def _config_path() -> Path:
    base = Path.home() / ".config" / "mixer"
    return base / "settings.json"


@dataclass
class MixerSettings:
    """User-configurable mixer preferences."""

    mute_input_accel: str = DEFAULT_MUTE_INPUT_ACCEL
    show_tray: bool = True
    start_on_login: bool = False
    start_minimized: bool = True

    @classmethod
    def load(cls, path: Path | None = None) -> MixerSettings:
        config = path or _config_path()
        if not config.is_file():
            return cls()
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read settings from %s: %s", config, exc)
            return cls()

        accel = data.get("mute_input_accel", DEFAULT_MUTE_INPUT_ACCEL)
        if not isinstance(accel, str) or not accel.strip():
            accel = DEFAULT_MUTE_INPUT_ACCEL

        def _bool(key: str, default: bool) -> bool:
            value = data.get(key, default)
            return bool(value) if isinstance(value, bool) else default

        return cls(
            mute_input_accel=accel.strip(),
            show_tray=_bool("show_tray", True),
            start_on_login=_bool("start_on_login", False),
            start_minimized=_bool("start_minimized", True),
        )

    def save(self, path: Path | None = None) -> None:
        config = path or _config_path()
        try:
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(
                json.dumps(asdict(self), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to write settings to %s: %s", config, exc)
