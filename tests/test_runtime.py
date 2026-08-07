"""Tests for runtime / snap launcher helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from mixer.util import runtime


def test_mixer_launcher_prefers_mixer_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIXER_EXEC", "/opt/mixer/bin/mixer")
    assert runtime.mixer_launcher() == "/opt/mixer/bin/mixer"


def test_mixer_launcher_uses_snap_when_inside_snap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MIXER_EXEC", raising=False)
    monkeypatch.setenv("SNAP", "/snap/volume-mixer/1")
    monkeypatch.setenv("SNAP_NAME", "volume-mixer")
    assert runtime.mixer_launcher() == "/snap/bin/volume-mixer"


def test_mixer_launcher_detects_snap_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MIXER_EXEC", raising=False)
    monkeypatch.delenv("SNAP", raising=False)

    real_is_file = Path.is_file

    def fake_is_file(self: Path) -> bool:
        if str(self) == f"/snap/bin/{runtime.SNAP_NAME}":
            return True
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", fake_is_file)
    assert runtime.mixer_launcher() == f"/snap/bin/{runtime.SNAP_NAME}"


def test_mixer_command_joins_args(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIXER_EXEC", "/bin/mixer")
    assert runtime.mixer_command("--toggle-mute") == "/bin/mixer --toggle-mute"
    assert runtime.mixer_command("--background") == "/bin/mixer --background"
