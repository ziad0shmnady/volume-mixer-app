"""GNOME Settings global keybinding for mute input (works from any app)."""

from __future__ import annotations

import os

from gi.repository import Gio, GLib

from mixer.util.logging import get_logger
from mixer.util.runtime import mixer_command

logger = get_logger("util.gnome_shortcut")

MEDIA_KEYS_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_BINDING_SCHEMA = (
    "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
)
BINDING_NAME = "mixer-mute-input"
BINDING_PATH = (
    f"/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
    f"{BINDING_NAME}/"
)


def _is_gnome_session() -> bool:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    return "GNOME" in desktop.upper()


def _schema_available(schema_id: str) -> bool:
    source = Gio.SettingsSchemaSource.get_default()
    if source is None:
        return False
    return source.lookup(schema_id, recursive=True) is not None


def gnome_shortcuts_available() -> bool:
    """Return True when GNOME custom keybindings can be registered."""
    return _is_gnome_session() and _schema_available(MEDIA_KEYS_SCHEMA)


def _resolve_toggle_command() -> str:
    return mixer_command("--toggle-mute")


def sync_mute_input_shortcut(accel: str) -> bool:
    """Register or update the GNOME global mute shortcut."""
    if not accel or not gnome_shortcuts_available():
        return False

    try:
        media = Gio.Settings.new(MEDIA_KEYS_SCHEMA)
        paths = list(media.get_strv("custom-keybindings"))
        if BINDING_PATH not in paths:
            paths.append(BINDING_PATH)
            media.set_strv("custom-keybindings", paths)

        binding = Gio.Settings.new_with_path(CUSTOM_BINDING_SCHEMA, BINDING_PATH)
        binding.set_string("name", "Volume Mixer: Mute Input")
        binding.set_string("command", _resolve_toggle_command())
        binding.set_string("binding", accel)
        logger.info("Registered GNOME global shortcut %s", accel)
        return True
    except GLib.Error as exc:
        logger.warning("Could not register GNOME global shortcut: %s", exc)
        return False


def clear_mute_input_shortcut() -> None:
    """Remove the GNOME global mute shortcut."""
    if not gnome_shortcuts_available():
        return

    try:
        media = Gio.Settings.new(MEDIA_KEYS_SCHEMA)
        paths = [p for p in media.get_strv("custom-keybindings") if p != BINDING_PATH]
        media.set_strv("custom-keybindings", paths)
        logger.info("Removed GNOME global mute shortcut")
    except GLib.Error as exc:
        logger.warning("Could not clear GNOME global shortcut: %s", exc)
