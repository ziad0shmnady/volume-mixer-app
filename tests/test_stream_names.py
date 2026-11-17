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


from mixer.util.stream_names import (  # noqa: E402
    app_identity_key,
    is_system_client,
    known_app_name,
    strip_role_suffix,
)


def test_app_key_prefers_snap_id() -> None:
    props = {
        "pipewire.snap.id": "discord",
        "application.name": "WEBRTC VoiceEngine",
        "application.process.binary": "Discord",
    }
    assert app_identity_key(props) == "snap:discord"


def test_app_key_groups_capture_client_with_playback() -> None:
    playback = {"application.name": "Google Chrome", "application.process.binary": "chrome"}
    capture = {"application.name": "Google Chrome input", "application.process.binary": "chrome"}
    assert app_identity_key(playback) == app_identity_key(capture) == "bin:chrome"


def test_app_key_splits_generic_runtimes_by_name() -> None:
    dbeaver = {"application.name": "DBeaver", "application.process.binary": "java"}
    other = {"application.name": "IntelliJ IDEA", "application.process.binary": "java"}
    assert app_identity_key(dbeaver) == "bin:java/dbeaver"
    assert app_identity_key(dbeaver) != app_identity_key(other)


def test_app_key_flatpak_and_fallbacks() -> None:
    assert (
        app_identity_key({"pipewire.access.portal.app_id": "com.spotify.Client"})
        == "flatpak:com.spotify.client"
    )
    assert app_identity_key({"application.name": "Some App"}) == "app:some app"
    assert app_identity_key({}) is None


def test_strip_role_suffix() -> None:
    assert strip_role_suffix("Google Chrome input") == "Google Chrome"
    assert strip_role_suffix("discord_capture") == "discord"
    assert strip_role_suffix("Firefox") == "Firefox"
    assert strip_role_suffix(" input") == "input"
    assert strip_role_suffix(None) == ""


def test_system_clients_hidden() -> None:
    assert is_system_client({"application.process.binary": "wireplumber"})
    assert is_system_client({"application.process.binary": "gsd-media-keys"})
    assert is_system_client({"application.process.binary": "xdg-desktop-portal"})
    assert is_system_client({"application.name": "Mutter", "application.process.binary": "x"})
    assert not is_system_client({"application.name": "Slack", "application.process.binary": "slack"})


def test_known_app_name() -> None:
    assert known_app_name("whatsapp-desktop-linux") == "WhatsApp"
    assert known_app_name(None, "/usr/bin/chrome") == "Google Chrome"
    assert known_app_name("unknown-thing") is None
