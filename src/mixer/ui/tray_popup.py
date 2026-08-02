"""Compact tray dropdown with per-application volume controls."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from mixer.ui.channel_row import ChannelRow
from mixer.util.logging import get_logger
from mixer.viewmodel.mixer_viewmodel import MixerViewModel

logger = get_logger("ui.tray_popup")

_POPUP_WIDTH = 380
_POPUP_MAX_HEIGHT = 480


class TrayPopup(Gtk.Window):
    """Undecorated popup shown from the system tray icon."""

    def __init__(
        self,
        application: Gtk.Application,
        viewmodel: MixerViewModel,
        *,
        on_open_mixer: Callable[[], None],
        on_mute_input: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        super().__init__(application=application)
        self._vm = viewmodel
        self._on_open_mixer = on_open_mixer
        self._on_mute_input = on_mute_input
        self._on_quit = on_quit
        self._stream_rows: dict[int, ChannelRow] = {}
        self._anchor_x = 0
        self._anchor_y = 0

        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(_POPUP_WIDTH, 320)
        self.add_css_class("mixer-tray-popup")

        # Popup semantics: no taskbar entry, closes when it loses focus.
        self.set_hide_on_close(True)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(outer)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("mixer-tray-header")
        header.set_margin_top(10)
        header.set_margin_bottom(8)
        header.set_margin_start(14)
        header.set_margin_end(10)

        title = Gtk.Label(label="Applications", xalign=0.0)
        title.add_css_class("heading")
        title.set_hexpand(True)
        header.append(title)

        mic_btn = Gtk.Button()
        mic_btn.set_icon_name("microphone-sensitivity-high-symbolic")
        mic_btn.add_css_class("flat")
        mic_btn.add_css_class("circular")
        mic_btn.set_tooltip_text("Mute / unmute microphone")
        mic_btn.connect("clicked", lambda *_: self._on_mute_input())
        self._mic_btn = mic_btn
        header.append(mic_btn)

        open_btn = Gtk.Button()
        open_btn.set_icon_name("window-maximize-symbolic")
        open_btn.add_css_class("flat")
        open_btn.add_css_class("circular")
        open_btn.set_tooltip_text("Open full mixer")
        open_btn.connect("clicked", lambda *_: self._open_mixer())
        header.append(open_btn)

        outer.append(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_max_content_height(_POPUP_MAX_HEIGHT)
        outer.append(scrolled)

        self._apps_group = Adw.PreferencesGroup()
        self._apps_group.add_css_class("mixer-tray-apps")
        scrolled.set_child(self._apps_group)

        self._empty = Gtk.Label(
            label="No applications are playing audio",
            justify=Gtk.Justification.CENTER,
        )
        self._empty.add_css_class("mixer-empty-apps")
        self._empty.set_margin_top(24)
        self._empty.set_margin_bottom(24)
        outer.append(self._empty)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.add_css_class("mixer-tray-footer")
        footer.set_margin_top(6)
        footer.set_margin_bottom(10)
        footer.set_margin_start(14)
        footer.set_margin_end(14)
        footer.set_halign(Gtk.Align.END)

        quit_btn = Gtk.Button(label="Quit")
        quit_btn.add_css_class("flat")
        quit_btn.connect("clicked", lambda *_: self._on_quit())
        footer.append(quit_btn)

        full_btn = Gtk.Button(label="Open Mixer")
        full_btn.add_css_class("suggested-action")
        full_btn.connect("clicked", lambda *_: self._open_mixer())
        footer.append(full_btn)

        outer.append(footer)

        self._vm.add_listener(self._on_viewmodel_changed)

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-released", self._on_key_released)
        self.add_controller(key_ctrl)

        self.connect("realize", self._on_realize)
        self.connect("notify::is-active", self._on_active_changed)
        self._render()

    def toggle_at(self, x: int, y: int) -> None:
        """Show or hide the popup, anchored near the tray icon at (x, y)."""
        if self.is_visible():
            self.hide()
            return
        self._anchor_x = x
        self._anchor_y = y
        self.present()
        if self.get_realized():
            self._apply_position()
        self._render()

    def toggle(self) -> None:
        self.toggle_at(0, 0)

    def _on_active_changed(self, window: Gtk.Window, _pspec: object) -> None:
        if window.is_visible() and not window.is_active():
            window.hide()

    def _open_mixer(self) -> None:
        self.hide()
        self._on_open_mixer()

    def _on_key_released(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: Gdk.ModifierType,
    ) -> None:
        if keyval == Gdk.KEY_Escape:
            self.hide()

    def _on_realize(self, *_args: object) -> None:
        self._apply_position()

    def _apply_position(self) -> None:
        """Place the popup just below the tray icon (or top-right fallback)."""
        display = Gdk.Display.get_default()
        if display is None:
            return
        monitors = display.get_monitors()
        if monitors is None or monitors.get_n_items() == 0:
            return
        monitor = monitors.get_item(0)
        geo = monitor.get_geometry()
        width = _POPUP_WIDTH
        margin = 8

        x = self._anchor_x
        y = self._anchor_y

        if x > 0 or y > 0:
            # Anchor under the tray icon; align right edge near the click.
            popup_x = max(geo.x + margin, x - width + 24)
            popup_y = y + 6
            if popup_y < geo.y + 20:
                popup_y = geo.y + 32
        else:
            popup_x = geo.x + geo.width - width - margin
            popup_y = geo.y + 32

        popup_x = min(popup_x, geo.x + geo.width - width - margin)
        popup_x = max(popup_x, geo.x + margin)
        _move_surface(self, int(popup_x), int(popup_y))

    def _on_viewmodel_changed(self, _vm: MixerViewModel) -> None:
        GLib.idle_add(self._render)

    def _render(self) -> bool:
        if not self._vm.connected:
            self._empty.set_label("Audio service unavailable")
            self._empty.set_visible(True)
            return False

        max_vol = self._vm.max_volume
        sinks = self._vm.sorted_sinks()
        streams = self._vm.sorted_streams()

        source = self._vm.default_source()
        if source is not None:
            if source.muted:
                self._mic_btn.set_icon_name("microphone-sensitivity-muted-symbolic")
                self._mic_btn.add_css_class("error")
            else:
                self._mic_btn.set_icon_name("microphone-sensitivity-high-symbolic")
                self._mic_btn.remove_css_class("error")

        desired = {s.index for s in streams}
        for index in list(self._stream_rows.keys()):
            if index not in desired:
                row = self._stream_rows.pop(index)
                self._apps_group.remove(row)

        has_icon = Gtk.IconTheme.get_for_display(self.get_display()).has_icon

        for stream in streams:
            row = self._stream_rows.get(stream.index)
            if row is None:
                stream_index = stream.index
                row = ChannelRow(
                    title=stream.name,
                    subtitle=stream.media_name,
                    volume=stream.volume,
                    muted=stream.muted,
                    max_volume=max_vol,
                    compact=True,
                    on_mute=lambda muted, idx=stream_index: self._vm.set_mute(
                        "stream", idx, muted
                    ),
                    on_volume=lambda v, idx=stream_index: self._vm.set_volume(
                        "stream", idx, v
                    ),
                )
                self._stream_rows[stream.index] = row
                self._apps_group.add(row)
            row.update_from_stream(
                stream,
                sinks=sinks,
                max_volume=max_vol,
                has_icon=has_icon,
            )

        self._empty.set_visible(len(desired) == 0)
        if len(desired) == 0:
            self._empty.set_label("No applications are playing audio")
        return False


def _move_surface(window: Gtk.Window, x: int, y: int) -> None:
    surface = window.get_surface()
    if surface is None:
        return
    try:
        surface.move(x, y)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        logger.debug("Could not position tray popup at %s,%s", x, y)
