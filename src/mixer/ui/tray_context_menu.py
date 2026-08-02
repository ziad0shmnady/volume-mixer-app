"""GTK context menu shown on tray right-click."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from mixer.util.logging import get_logger

logger = get_logger("ui.tray_context_menu")

_MENU_WIDTH = 240


class TrayContextMenu(Gtk.Window):
    """Small popup menu window anchored near the tray icon."""

    def __init__(
        self,
        application: Gtk.Application,
        *,
        on_volumes: Callable[[int, int], None],
        on_mute: Callable[[], None],
        on_open: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        super().__init__(application=application)
        self._on_volumes = on_volumes
        self._on_mute = on_mute
        self._on_open = on_open
        self._on_quit = on_quit
        self._anchor_x = 0
        self._anchor_y = 0

        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(_MENU_WIDTH, -1)
        self.add_css_class("mixer-tray-popup")
        self.add_css_class("mixer-tray-menu")

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body.set_margin_top(6)
        body.set_margin_bottom(6)
        body.set_margin_start(6)
        body.set_margin_end(6)
        self.set_child(body)

        body.append(self._row("Application Volumes", self._open_volumes))
        body.append(self._row("Mute / Unmute Input", self._on_mute))
        body.append(self._row("Open Full Mixer", self._on_open))

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(6)
        sep.set_margin_bottom(6)
        body.append(sep)

        quit_row = self._row("Quit", self._on_quit)
        quit_row.add_css_class("destructive-action")
        body.append(quit_row)

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-released", self._on_key_released)
        self.add_controller(key_ctrl)

        self.connect("realize", self._on_realize)
        self.connect("notify::is-active", self._on_active_changed)

    def popup_at(self, x: int, y: int) -> None:
        if self.is_visible():
            self.hide()
            return
        self._anchor_x = x
        self._anchor_y = y
        logger.debug("Tray context menu at %s,%s", x, y)
        self.present()
        if self.get_realized():
            self._apply_position()

    def _row(self, label: str, handler: Callable[[], None]) -> Gtk.Button:
        btn = Gtk.Button(label=label)
        btn.add_css_class("flat")
        btn.set_halign(Gtk.Align.FILL)

        def _activate(*_args: object) -> None:
            self.hide()
            handler()

        btn.connect("clicked", _activate)
        return btn

    def _open_volumes(self) -> None:
        self._on_volumes(self._anchor_x, self._anchor_y)

    def _on_key_released(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: Gdk.ModifierType,
    ) -> None:
        if keyval == Gdk.KEY_Escape:
            self.hide()

    def _on_active_changed(self, window: Gtk.Window, _pspec: object) -> None:
        if window.is_visible() and not window.is_active():
            window.hide()

    def _on_realize(self, *_args: object) -> None:
        self._apply_position()

    def _apply_position(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        monitors = display.get_monitors()
        if monitors is None or monitors.get_n_items() == 0:
            return
        monitor = monitors.get_item(0)
        geo = monitor.get_geometry()
        margin = 8
        x = self._anchor_x
        y = self._anchor_y

        if x > 0 or y > 0:
            popup_x = max(geo.x + margin, x - _MENU_WIDTH + 24)
            popup_y = y + 6
            if popup_y < geo.y + 20:
                popup_y = geo.y + 32
        else:
            popup_x = geo.x + geo.width - _MENU_WIDTH - margin
            popup_y = geo.y + 32

        popup_x = min(popup_x, geo.x + geo.width - _MENU_WIDTH - margin)
        popup_x = max(popup_x, geo.x + margin)
        _move_surface(self, int(popup_x), int(popup_y))


def _move_surface(window: Gtk.Window, x: int, y: int) -> None:
    surface = window.get_surface()
    if surface is None:
        return
    try:
        surface.move(x, y)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        logger.debug("Could not position context menu at %s,%s", x, y)
