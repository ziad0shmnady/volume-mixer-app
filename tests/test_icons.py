"""Tests for icon candidate resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from mixer.models.audio import StreamInfo
from mixer.util.icons import candidate_icon_names, resolve_icon_file, resolve_icon_name


def _stream(**kwargs: object) -> StreamInfo:
    base = dict(
        index=1,
        name="App",
        media_name="",
        icon_name=None,
        volume=1.0,
        muted=False,
        sink_index=1,
    )
    base.update(kwargs)
    return StreamInfo(**base)  # type: ignore[arg-type]


def test_candidates_prefer_icon_name() -> None:
    names = candidate_icon_names(
        _stream(icon_name="firefox", process_binary="firefox-bin", application_id="org.mozilla.firefox")
    )
    assert names[0] == "firefox"


_DISCORD_SNAP_ICON = Path("/snap/discord/current/meta/gui/icon.png")


@pytest.mark.skipif(not _DISCORD_SNAP_ICON.is_file(), reason="discord snap not installed")
def test_resolve_discord_snap_icon_file() -> None:
    stream = _stream(
        name="Discord",
        process_binary="Discord",
        snap_id="discord",
        icon_name="Discord",
    )
    icon = resolve_icon_file(stream)
    assert icon is not None
    assert icon.endswith("icon.png")
    assert "discord" in icon.casefold()
    chosen = resolve_icon_name(stream, has_icon=lambda _n: False)
    assert chosen == icon


def test_resolve_with_has_icon() -> None:
    stream = _stream(icon_name="missing-icon", process_binary="chrome")
    chosen = resolve_icon_name(stream, has_icon=lambda n: n == "chrome")
    assert chosen == "chrome"


def test_resolve_fallback() -> None:
    stream = _stream()
    chosen = resolve_icon_name(stream, has_icon=lambda _n: False)
    assert "symbolic" in chosen or chosen.startswith("audio") or "executable" in chosen
