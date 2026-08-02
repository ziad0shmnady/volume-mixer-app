"""Tests for GNOME global shortcut helpers."""

from __future__ import annotations

import pytest

from mixer.util import gnome_shortcut as gs


def test_gnome_shortcuts_unavailable_outside_gnome(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    assert gs.gnome_shortcuts_available() is False


def test_toggle_command_uses_mixer_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIXER_EXEC", "/opt/mixer/bin/mixer")
    assert gs._resolve_toggle_command() == "/opt/mixer/bin/mixer --toggle-mute"
