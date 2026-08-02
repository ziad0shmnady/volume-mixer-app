"""Tests for friendly stream naming."""

from __future__ import annotations

from mixer.util.stream_names import is_transient_system_stream, resolve_stream_display_name


def test_discord_webrtc_named_discord() -> None:
    assert (
        resolve_stream_display_name(
            application_name="WEBRTC VoiceEngine",
            process_binary="Discord",
            snap_id="discord",
            media_name="playStream",
        )
        == "Discord"
    )


def test_chrome_keeps_application_name() -> None:
    assert (
        resolve_stream_display_name(
            application_name="Google Chrome",
            process_binary="chrome",
            media_name="Playback",
        )
        == "Google Chrome"
    )


def test_snap_id_fallback() -> None:
    assert (
        resolve_stream_display_name(
            application_name="WEBRTC VoiceEngine",
            process_binary=None,
            snap_id="discord",
        )
        == "Discord"
    )


def test_hides_mutter_screen_capture() -> None:
    props = {
        "application.name": "Mutter",
        "application.process.binary": "gnome-shell",
        "media.name": "screen-capture",
        "media.role": "event",
        "media.filename": "/usr/share/sounds/freedesktop/stereo/screen-capture.oga",
    }
    assert is_transient_system_stream(props) is True


def test_keeps_normal_app_stream() -> None:
    props = {
        "application.name": "Google Chrome",
        "application.process.binary": "chrome",
        "media.name": "Playback",
    }
    assert is_transient_system_stream(props) is False
