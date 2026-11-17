"""Tests for XDG autostart helpers."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from mixer.util import autostart


def test_enable_and_disable_autostart(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(autostart, "_autostart_dir", lambda: tmp_path)
    monkeypatch.setattr(autostart, "_resolve_exec", lambda: "/tmp/fake-mixer")

    assert autostart.is_autostart_enabled() is False
    autostart.set_autostart_enabled(True, minimized=True)
    path = tmp_path / autostart.AUTOSTART_ID
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "Exec=/tmp/fake-mixer --background" in text
    assert autostart.is_autostart_enabled() is True

    autostart.set_autostart_enabled(False)
    assert not path.exists()
    assert autostart.is_autostart_enabled() is False


def test_refresh_repairs_stale_launcher_path(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(autostart, "_autostart_dir", lambda: tmp_path)
    launcher = tmp_path / "bin" / "mixer"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(autostart, "_resolve_exec", lambda: str(launcher))

    path = tmp_path / autostart.AUTOSTART_ID
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Volume Mixer\n"
        "Exec=/home/someone/old-location/.venv/bin/mixer --background\n"
        "X-GNOME-Autostart-Delay=5\n",
        encoding="utf-8",
    )

    assert autostart.refresh_autostart_entry(minimized=True) is True
    text = path.read_text(encoding="utf-8")
    assert f"Exec={launcher} --background" in text
    assert "old-location" not in text
    assert "X-GNOME-Autostart-Delay=5" in text  # user tweaks kept
    # Already correct: nothing to do.
    assert autostart.refresh_autostart_entry(minimized=True) is False


def test_refresh_skips_disabled_or_unrunnable(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(autostart, "_autostart_dir", lambda: tmp_path)
    monkeypatch.setattr(autostart, "_resolve_exec", lambda: "/nonexistent/mixer")

    # No entry: never creates one.
    assert autostart.refresh_autostart_entry() is False
    assert not (tmp_path / autostart.AUTOSTART_ID).exists()

    # Entry exists but the current launcher can't be found: leave it alone.
    path = tmp_path / autostart.AUTOSTART_ID
    original = "[Desktop Entry]\nType=Application\nExec=/old/mixer --background\n"
    path.write_text(original, encoding="utf-8")
    assert autostart.refresh_autostart_entry() is False
    assert path.read_text(encoding="utf-8") == original
