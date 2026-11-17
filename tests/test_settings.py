"""Tests for persistent MixerSettings."""

from __future__ import annotations

from pathlib import Path

from mixer.util.settings import DEFAULT_MUTE_INPUT_ACCEL, MixerSettings


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    settings = MixerSettings(
        mute_input_accel="<Control>i",
        show_tray=False,
        start_on_login=True,
        start_minimized=False,
    )
    settings.save(path)
    loaded = MixerSettings.load(path)
    assert loaded.mute_input_accel == "<Control>i"
    assert loaded.show_tray is False
    assert loaded.start_on_login is True
    assert loaded.start_minimized is False


def test_load_missing_file(tmp_path: Path) -> None:
    loaded = MixerSettings.load(tmp_path / "missing.json")
    assert loaded.mute_input_accel == DEFAULT_MUTE_INPUT_ACCEL
    assert loaded.show_tray is True
    assert loaded.start_on_login is False


def test_load_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not-json", encoding="utf-8")
    loaded = MixerSettings.load(path)
    assert loaded.mute_input_accel == DEFAULT_MUTE_INPUT_ACCEL


def test_empty_accel_normalized_on_load(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"mute_input_accel": "   "}\n', encoding="utf-8")
    loaded = MixerSettings.load(path)
    assert loaded.mute_input_accel == DEFAULT_MUTE_INPUT_ACCEL


def test_default_settings() -> None:
    settings = MixerSettings()
    assert settings.mute_input_accel == DEFAULT_MUTE_INPUT_ACCEL
    assert settings.show_tray is True
    assert settings.start_on_login is False
    assert settings.start_minimized is True


def test_app_volumes_roundtrip(tmp_path: Path) -> None:
    from mixer.models.audio import AppPreference

    path = tmp_path / "settings.json"
    MixerSettings(
        app_volumes={
            "snap:discord": AppPreference(volume=0.4, muted=True),
            "bin:chrome": AppPreference(volume=0.75, muted=False),
        }
    ).save(path)
    loaded = MixerSettings.load(path)
    assert loaded.app_volumes == {
        "snap:discord": AppPreference(volume=0.4, muted=True),
        "bin:chrome": AppPreference(volume=0.75, muted=False),
    }


def test_app_volumes_invalid_entries_dropped(tmp_path: Path) -> None:
    import json

    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "app_volumes": {
                    "bin:ok": {"volume": 9, "muted": "yes"},
                    "bin:bad-volume": {"volume": "loud"},
                    "bin:bool-volume": {"volume": True},
                    "bin:not-a-dict": 0.5,
                    "": {"volume": 0.5},
                }
            }
        ),
        encoding="utf-8",
    )
    loaded = MixerSettings.load(path)
    assert list(loaded.app_volumes) == ["bin:ok"]
    assert loaded.app_volumes["bin:ok"].volume == 1.5  # clamped
    assert loaded.app_volumes["bin:ok"].muted is False
