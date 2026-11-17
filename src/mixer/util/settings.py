"""Persistent user settings (JSON under XDG config)."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mixer.models.audio import AppPreference
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
    # Per-app volume/mute chosen in the mixer, keyed by app key
    # (e.g. "snap:discord", "bin:chrome").
    app_volumes: dict[str, AppPreference] = field(default_factory=dict)

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
            app_volumes=_parse_app_volumes(data.get("app_volumes")),
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


def _parse_app_volumes(raw: object) -> dict[str, AppPreference]:
    if not isinstance(raw, dict):
        return {}
    result: dict[str, AppPreference] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key or not isinstance(value, dict):
            continue
        volume = value.get("volume", 1.0)
        muted = value.get("muted", False)
        if isinstance(volume, bool) or not isinstance(volume, (int, float)):
            continue
        if not math.isfinite(volume):
            continue
        result[key] = AppPreference(
            volume=max(0.0, min(1.5, float(volume))),
            muted=muted if isinstance(muted, bool) else False,
        )
    return result
