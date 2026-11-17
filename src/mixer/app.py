"""Application entrypoint."""

from __future__ import annotations

import argparse
import logging
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib  # noqa: E402

from mixer.services.fake_backend import FakeBackend
from mixer.services.pulse_service import PulseService
from mixer.ui.tray import TrayIcon
from mixer.ui.tray_popup import TrayPopup
from mixer.ui.window import MixerWindow
from mixer.util.autostart import (
    is_autostart_enabled,
    refresh_autostart_entry,
    set_autostart_enabled,
)
from mixer.util.gnome_shortcut import sync_mute_input_shortcut
from mixer.util.logging import get_logger, setup_logging
from mixer.util.runtime import mixer_launcher
from mixer.util.settings import MixerSettings
from mixer.util.styles import load_app_css
from mixer.viewmodel.mixer_viewmodel import MixerViewModel

logger = get_logger("app")

APP_ID = "io.github.ziad.Mixer"
# Coalesce per-app volume saves while a slider is being dragged.
_APP_VOLUME_SAVE_DELAY_MS = 750


class MixerApplication(Adw.Application):
    """Adw.Application that owns the view-model, window, and tray icon."""

    def __init__(
        self,
        viewmodel: MixerViewModel,
        *,
        settings: MixerSettings,
        start_background: bool = False,
        persist_app_volumes: bool = True,
    ) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self._viewmodel = viewmodel
        self._settings = settings
        self._start_background = start_background
        self._window: MixerWindow | None = None
        self._tray: TrayIcon | None = None
        self._tray_popup: TrayPopup | None = None
        self._hold_id: int | None = None
        self._audio_started = False
        self._app_volume_save_id: int | None = None
        if persist_app_volumes:
            viewmodel.app_preferences.update(settings.app_volumes)
            viewmodel.on_app_preferences_changed = self._schedule_app_volume_save

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:  # noqa: N802
        args = command_line.get_arguments()[1:]
        if "--toggle-mute" in args:
            self._ensure_audio_started()
            self._toggle_mute_input()
            return 0
        if "--background" in args or "--minimized" in args:
            self._start_background = True
        self.activate()
        return 0

    def do_startup(self) -> None:  # noqa: N802 - GTK override
        Adw.Application.do_startup(self)
        load_app_css()
        self._install_app_actions()
        if self._settings.show_tray:
            self._ensure_tray()

    def do_activate(self) -> None:  # noqa: N802 - GTK override
        self._ensure_window()
        assert self._window is not None
        if self._start_background and self._tray is not None:
            # First activation from --background: stay in tray.
            self._start_background = False
            self._window.hide()
            return
        self._window.present()

    def do_shutdown(self) -> None:  # noqa: N802 - GTK override
        if self._app_volume_save_id is not None:
            GLib.source_remove(self._app_volume_save_id)
            self._save_app_volumes()
        if self._tray is not None:
            self._tray.stop()
            self._tray = None
        try:
            self._viewmodel.stop()
        except Exception:  # noqa: BLE001
            logger.exception("Error stopping view-model")
        Adw.Application.do_shutdown(self)

    def _schedule_app_volume_save(self) -> None:
        if self._app_volume_save_id is None:
            self._app_volume_save_id = GLib.timeout_add(
                _APP_VOLUME_SAVE_DELAY_MS, self._save_app_volumes
            )

    def _save_app_volumes(self) -> bool:
        self._app_volume_save_id = None
        self._settings.app_volumes = dict(self._viewmodel.app_preferences)
        self._settings.save()
        return False

    def _install_app_actions(self) -> None:
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self._quit_app())
        self.add_action(quit_action)

        show = Gio.SimpleAction.new("show", None)
        show.connect("activate", lambda *_: self._show_window())
        self.add_action(show)

        tray = Gio.SimpleAction.new_stateful(
            "show-tray",
            None,
            GLib.Variant.new_boolean(self._settings.show_tray),
        )
        tray.connect("change-state", self._on_toggle_tray)
        self.add_action(tray)

        # The autostart file is the source of truth: it can also be toggled
        # from GNOME's "Startup Applications" / Tweaks.
        autostart_on = is_autostart_enabled()
        if autostart_on != self._settings.start_on_login:
            self._settings.start_on_login = autostart_on
            self._settings.save()
        if autostart_on:
            # Repair entries left pointing at an old install location.
            refresh_autostart_entry(minimized=self._settings.start_minimized)

        autostart = Gio.SimpleAction.new_stateful(
            "start-on-login",
            None,
            GLib.Variant.new_boolean(self._settings.start_on_login),
        )
        autostart.connect("change-state", self._on_toggle_autostart)
        self.add_action(autostart)

        mute_input = Gio.SimpleAction.new("mute-input", None)
        mute_input.connect("activate", lambda *_: self._toggle_mute_input())
        self.add_action(mute_input)

        self._apply_mute_input_accel(self._settings.mute_input_accel)

    def set_mute_input_accel(self, accel: str) -> None:
        """Update the mute shortcut from settings UI."""
        self._settings.mute_input_accel = accel or ""
        self._settings.save()
        self._apply_mute_input_accel(self._settings.mute_input_accel)

    def _apply_mute_input_accel(self, accel: str) -> None:
        """Register shortcuts so mute works while Mixer runs in the tray."""
        accels = [accel] if accel else []
        self.set_accels_for_action("app.mute-input", accels)
        sync_mute_input_shortcut(accel)

    def _toggle_mute_input(self) -> None:
        self._ensure_audio_started()
        source = self._viewmodel.default_source()
        if source is None:
            return
        self._viewmodel.toggle_mute("source", source.index)
        if self._window is not None:
            self._window.refresh_input_mute_ui()

    def _ensure_audio_started(self) -> None:
        if self._audio_started:
            return
        self._viewmodel.start()
        self._audio_started = True

    def _ensure_window(self) -> None:
        self._ensure_audio_started()
        if self._window is not None:
            return
        self._window = MixerWindow(self, self._viewmodel, settings=self._settings)
        self._window.connect("close-request", self._on_close)
        # Keep process alive when the window is hidden to tray.
        if self._hold_id is None and self._settings.show_tray:
            self._hold_id = self.hold()

    def _ensure_tray_popup(self) -> TrayPopup:
        self._ensure_audio_started()
        if self._tray_popup is None:
            self._tray_popup = TrayPopup(
                self,
                self._viewmodel,
                on_open_mixer=self._show_window,
                on_mute_input=self._mute_input_from_tray,
                on_quit=self._quit_app,
            )
        return self._tray_popup

    def _toggle_tray_popup(self, x: int = 0, y: int = 0) -> None:
        popup = self._ensure_tray_popup()
        popup.toggle_at(x, y)

    def _toggle_autostart_from_tray(self) -> None:
        enabled = not self._settings.start_on_login
        action = self.lookup_action("start-on-login")
        if action is not None:
            action.change_state(GLib.Variant.new_boolean(enabled))
            return
        self._settings.start_on_login = enabled
        self._settings.save()
        os.environ.setdefault("MIXER_EXEC", mixer_launcher())
        set_autostart_enabled(enabled, minimized=self._settings.start_minimized)
        if self._tray is not None:
            self._tray.set_start_on_login(enabled)

    def _ensure_tray(self) -> None:
        if self._tray is not None:
            return
        tray = TrayIcon(
            on_popup=self._toggle_tray_popup,
            on_mute_input=self._mute_input_from_tray,
            on_open_mixer=self._show_window,
            on_toggle_autostart=self._toggle_autostart_from_tray,
            on_quit=self._quit_app,
            start_on_login=self._settings.start_on_login,
            icon_name="io.github.ziad.Mixer",
        )
        if tray.start():
            self._tray = tray
            if self._hold_id is None:
                self._hold_id = self.hold()
            self._viewmodel.add_listener(self._on_vm_for_tray)
        else:
            logger.warning("Could not create tray icon")

    def _stop_tray(self) -> None:
        if self._tray is not None:
            self._tray.stop()
            self._tray = None
        try:
            self._viewmodel.remove_listener(self._on_vm_for_tray)
        except Exception:  # noqa: BLE001
            pass

    def _on_vm_for_tray(self, vm: MixerViewModel) -> None:
        if self._tray is None:
            return
        source = vm.default_source()
        muted = bool(source and source.muted)
        GLib.idle_add(self._tray.set_mic_muted, muted)

    def _mute_input_from_tray(self) -> None:
        self._toggle_mute_input()

    def _show_window(self) -> None:
        self._ensure_window()
        assert self._window is not None
        self._window.present()
        self._window.unminimize()

    def _toggle_window(self) -> None:
        self._ensure_window()
        assert self._window is not None
        if self._window.is_visible():
            self._window.hide()
        else:
            self._show_window()

    def _on_close(self, *_args: object) -> bool:
        """Hide to tray when enabled; otherwise quit."""
        if self._tray is not None and self._settings.show_tray:
            if self._window is not None:
                self._window.hide()
            return True  # stop default destroy
        self._quit_app()
        return False

    def _quit_app(self) -> None:
        if self._hold_id is not None:
            self.release()
            self._hold_id = None
        if self._tray_popup is not None:
            self._tray_popup.destroy()
            self._tray_popup = None
        self._stop_tray()
        if self._window is not None:
            self._window.destroy()
            self._window = None
        self.quit()

    def _on_toggle_tray(self, action: Gio.SimpleAction, value: GLib.Variant) -> None:
        enabled = value.get_boolean()
        action.set_state(value)
        self._settings.show_tray = enabled
        self._settings.save()
        if enabled:
            self._ensure_tray()
            if self._hold_id is None:
                self._hold_id = self.hold()
        else:
            self._stop_tray()

    def _on_toggle_autostart(self, action: Gio.SimpleAction, value: GLib.Variant) -> None:
        enabled = value.get_boolean()
        action.set_state(value)
        self._settings.start_on_login = enabled
        self._settings.save()
        # Ensure MIXER_EXEC points at our launcher for the desktop file.
        os.environ.setdefault("MIXER_EXEC", mixer_launcher())
        set_autostart_enabled(enabled, minimized=self._settings.start_minimized)
        if self._tray is not None:
            self._tray.set_start_on_login(enabled)


def build_backend(use_fake: bool) -> PulseService | FakeBackend:
    if use_fake:
        logger.info("Using FakeBackend")
        return FakeBackend()
    return PulseService()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Volume Mixer")
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Use an in-memory fake backend (no PulseAudio required)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--background",
        "--minimized",
        action="store_true",
        dest="background",
        help="Start hidden in the system tray (for login autostart)",
    )
    parser.add_argument(
        "--toggle-mute",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_known_args(argv)[0]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    os.environ["MIXER_EXEC"] = mixer_launcher()

    settings = MixerSettings.load()
    backend = build_backend(use_fake=args.fake)
    viewmodel = MixerViewModel(backend=backend)
    app = MixerApplication(
        viewmodel,
        settings=settings,
        start_background=args.background,
        # Fake app keys look like real ones; don't let --fake overwrite them.
        persist_app_volumes=not args.fake,
    )

    return app.run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
