"""Friendly application naming helpers for audio streams."""

from __future__ import annotations

# Engine / host names that should not be shown as the app title.
_GENERIC_APP_NAMES = frozenset(
    {
        "webrtc voiceengine",
        "webrtc",
        "chromium input",
        "chromium",
        "audioipc server",
        "audioipc-server",
        "pulseaudio",
        "pipewire",
        "alsa plug-in",
        "alsa plug-in [wine-preloader]",
    }
)

# Known process binary / snap id → display name.
_BINARY_DISPLAY_NAMES: dict[str, str] = {
    "discord": "Discord",
    "slack": "Slack",
    "firefox": "Firefox",
    "chrome": "Google Chrome",
    "chromium": "Chromium",
    "code": "VS Code",
    "cursor": "Cursor",
    "spotify": "Spotify",
    "vlc": "VLC",
    "telegram-desktop": "Telegram",
    "telegram": "Telegram",
    "zoom": "Zoom",
    "teams": "Microsoft Teams",
    "steam": "Steam",
    "obs": "OBS Studio",
    "mpv": "mpv",
    "rhythmbox": "Rhythmbox",
    "firefox-bin": "Firefox",
}

# Extra icon theme names to try for a process binary.
BINARY_ICON_ALIASES: dict[str, tuple[str, ...]] = {
    "discord": ("discord", "com.discordapp.Discord", "webcord"),
    "slack": ("slack", "com.slack.Slack"),
    "firefox": ("firefox", "org.mozilla.firefox"),
    "chrome": ("google-chrome", "google-chrome-stable", "chromium-browser"),
    "spotify": ("spotify", "com.spotify.Client"),
    "telegram-desktop": ("telegram", "org.telegram.desktop"),
    "vlc": ("vlc", "org.videolan.VLC"),
}


def _norm(value: str | None) -> str:
    return (value or "").strip().casefold()


def _title_case_binary(binary: str) -> str:
    mapped = _BINARY_DISPLAY_NAMES.get(binary.casefold())
    if mapped:
        return mapped
    return " ".join(part.capitalize() for part in binary.replace("_", "-").split("-") if part)


def resolve_stream_display_name(
    *,
    application_name: str | None,
    process_binary: str | None,
    snap_id: str | None = None,
    media_name: str | None = None,
    fallback: str = "Application",
) -> str:
    """Pick a user-facing app name, preferring real binaries over engine names."""
    app = (application_name or "").strip()
    binary = (process_binary or "").strip().split("/")[-1]
    snap = (snap_id or "").strip()

    app_generic = _norm(app) in _GENERIC_APP_NAMES or not app

    if binary and (app_generic or _norm(app) == _norm(binary)):
        return _title_case_binary(binary)

    if snap and app_generic:
        return _title_case_binary(snap)

    if app:
        return app

    if binary:
        return _title_case_binary(binary)

    if media_name:
        return media_name.strip()

    return fallback


def is_transient_system_stream(props: dict[str, str]) -> bool:
    """True for short system event sounds that should not clutter the mixer."""
    role = _norm(props.get("media.role"))
    if role in {"event", "test"}:
        return True
    binary = _norm(props.get("application.process.binary"))
    media = _norm(props.get("media.name"))
    # gnome-shell / Mutter one-shot UI sounds
    if binary in {"gnome-shell", "gsd-media-keys"} and props.get("media.filename"):
        return True
    if binary == "gnome-shell" and media in {
        "screen-capture",
        "bell",
        "message-new-instant",
        "audio-volume-change",
    }:
        return True
    return False
