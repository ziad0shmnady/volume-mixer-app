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
