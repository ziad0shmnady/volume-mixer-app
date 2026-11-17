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
    "google-chrome": "Google Chrome",
    "brave": "Brave",
    "brave-browser": "Brave",
    "msedge": "Microsoft Edge",
    "microsoft-edge": "Microsoft Edge",
    "claude-desktop": "Claude",
    "whatsapp-desktop-linux": "WhatsApp",
    "whatsapp-for-linux": "WhatsApp",
    "signal-desktop": "Signal",
    "thunderbird": "Thunderbird",
    "audacity": "Audacity",
    "totem": "Videos",
}

# Binaries that host many unrelated apps; those are told apart by app name.
_GENERIC_RUNTIMES = frozenset(
    {
        "java",
        "node",
        "nodejs",
        "electron",
        "mono",
        "dotnet",
        "gjs",
        "bwrap",
        "sh",
        "bash",
        "perl",
        "ruby",
    }
)
_GENERIC_RUNTIME_PREFIXES = ("python", "wine", "electron", "qemu-system")

# Suffixes apps add to their name for secondary connections (mic capture etc.).
_ROLE_SUFFIXES = (" input", " output", " capture", "_capture", "_hardware_mute")

# Sound-server plumbing and desktop shells: connected, but not "apps".
_SYSTEM_CLIENT_BINARIES = frozenset(
    {
        "wireplumber",
        "pipewire",
        "pipewire-pulse",
        "pulseaudio",
        "gnome-shell",
        "gnome-control-center",
        "pactl",
        "pacmd",
        "pavucontrol",
        "pwvucontrol",
        "pw-cli",
        "pw-dump",
        "pw-top",
        "wpctl",
        "plasmashell",
        "kded5",
        "kded6",
        "kmix",
        "cinnamon",
        "xfce4-panel",
    }
)
_SYSTEM_CLIENT_BINARY_PREFIXES = ("gsd-", "xdg-desktop-portal")
_SYSTEM_CLIENT_NAMES = frozenset(
    {
        "libcanberra",
        "mutter",
        "gnome shell volume control",
        "gnome volume control media keys",
    }
)

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


def strip_role_suffix(name: str | None) -> str:
    """``"Google Chrome input"`` -> ``"Google Chrome"``, ``"discord_capture"`` -> ``"discord"``."""
    value = (name or "").strip()
    lowered = value.casefold()
    for suffix in _ROLE_SUFFIXES:
        if lowered.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)].strip()
    return value


def _is_generic_runtime(binary: str) -> bool:
    return binary in _GENERIC_RUNTIMES or binary.startswith(_GENERIC_RUNTIME_PREFIXES)


def _binary_base(props: dict[str, str]) -> str:
    return _norm((props.get("application.process.binary") or "").split("/")[-1])


def app_identity_key(props: dict[str, str]) -> str | None:
    """Stable key shared by every stream and client of one application.

    Apps open several connections (Discord: voice engine, capture, hardware
    mute; Chrome: playback + "Google Chrome input"), so the key is based on
    the sandbox id or process binary rather than ``application.name``.
    """
    snap = _norm(props.get("pipewire.snap.id") or props.get("snap.id"))
    if snap:
        return f"snap:{snap}"
    flatpak = _norm(props.get("pipewire.access.portal.app_id"))
    if flatpak:
        return f"flatpak:{flatpak}"
    binary = _binary_base(props)
    app = _norm(strip_role_suffix(props.get("application.name")))
    if binary and not _is_generic_runtime(binary):
        return f"bin:{binary}"
    if binary and app:
        return f"bin:{binary}/{app}"
    if app:
        return f"app:{app}"
    if binary:
        return f"bin:{binary}"
    return None


def known_app_name(*candidates: str | None) -> str | None:
    """Curated display name for a binary or snap id, if we have one."""
    for value in candidates:
        key = _norm((value or "").split("/")[-1])
        if key and key in _BINARY_DISPLAY_NAMES:
            return _BINARY_DISPLAY_NAMES[key]
    return None


def is_system_client(props: dict[str, str]) -> bool:
    """True for sound-server daemons, the desktop shell and volume tools."""
    binary = _binary_base(props)
    if binary in _SYSTEM_CLIENT_BINARIES or binary.startswith(_SYSTEM_CLIENT_BINARY_PREFIXES):
        return True
    return _norm(props.get("application.name")) in _SYSTEM_CLIENT_NAMES


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
