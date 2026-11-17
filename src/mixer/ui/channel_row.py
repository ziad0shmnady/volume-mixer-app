"""Reusable volume channel row (stream or device)."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from mixer.models.audio import AppInfo, DeviceInfo, StreamInfo, VolumeMath
from mixer.util.icons import apply_icon, resolve_icon_name

MuteHandler = Callable[[bool], None]
VolumeHandler = Callable[[float], None]
OutputHandler = Callable[[int], None]  # sink index


class ChannelRow(Adw.ActionRow):
    """A row with icon, mute toggle, volume slider, percent label, optional output menu."""

    def __init__(
        self,
        *,
        title: str,
        subtitle: str = "",
        icon_name: str = "audio-volume-high-symbolic",
        volume: float = 0.0,
        muted: bool = False,
        max_volume: float = 1.0,
        show_output_picker: bool = False,
        sinks: tuple[DeviceInfo, ...] = (),
        current_sink_index: int | None = None,
        compact: bool = False,
        scale_width: int | None = None,
        on_mute: MuteHandler | None = None,
        on_volume: VolumeHandler | None = None,
        on_output: OutputHandler | None = None,
    ) -> None:
        super().__init__()
        self.set_title(title)
        if subtitle:
            self.set_subtitle(subtitle)

        self._on_mute = on_mute
        self._on_volume = on_volume
        self._on_output = on_output
        self._max_volume = max_volume
        self._updating = False
        self._sinks = sinks
        self._current_sink_index = current_sink_index
        self._compact = compact
        self._last_icon: str | None = icon_name
        self._menu_sink_signature: tuple[tuple[int, str], ...] | None = None
        self._menu_sink_index: int | None = None

        self._icon = Gtk.Image()
        apply_icon(self._icon, icon_name)
        self._icon.set_pixel_size(22)
        self._icon.add_css_class("mixer-app-icon")
        self.add_prefix(self._icon)

        self._mute_btn = Gtk.ToggleButton()
        self._mute_btn.add_css_class("flat")
        self._mute_btn.add_css_class("circular")
        self._mute_btn.set_valign(Gtk.Align.CENTER)
        self._mute_btn.connect("toggled", self._handle_mute)
        self.add_prefix(self._mute_btn)

        self._scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL,
            0.0,
            max_volume,
            0.01,
        )
        self._scale.set_draw_value(False)
        self._scale.set_valign(Gtk.Align.CENTER)
        self._scale.add_css_class("mixer-volume-scale")
        if scale_width is not None:
            # Fixed width keeps sliders aligned down a list of rows.
            self._scale.set_size_request(scale_width, -1)
        else:
            self._scale.set_hexpand(True)
            self._scale.set_size_request(120 if compact else 160, -1)
        self._scale.connect("value-changed", self._handle_volume)
        self.add_suffix(self._scale)

        self._percent = Gtk.Label(label="0%")
        self._percent.add_css_class("mixer-volume-label")
        self._percent.add_css_class("dim-label")
        self._percent.set_xalign(1.0)
        self._percent.set_valign(Gtk.Align.CENTER)
        self.add_suffix(self._percent)

        self._output_btn: Gtk.MenuButton | None = None
        if show_output_picker:
            self._output_btn = Gtk.MenuButton()
            self._output_btn.set_icon_name("audio-speakers-symbolic")
            self._output_btn.set_valign(Gtk.Align.CENTER)
            self._output_btn.add_css_class("flat")
            self._output_btn.set_tooltip_text("Move to output")
            self.add_suffix(self._output_btn)
            self._rebuild_output_menu()
            self._menu_sink_signature = tuple(
                (sink.index, sink.description) for sink in self._sinks
            )
            self._menu_sink_index = self._current_sink_index

        self.update_state(
            title=title,
            subtitle=subtitle,
            icon_name=icon_name,
            volume=volume,
            muted=muted,
            max_volume=max_volume,
            sinks=sinks,
            current_sink_index=current_sink_index,
        )

    # ------------------------------------------------------------------
    # Public update
    # ------------------------------------------------------------------

    def update_state(
        self,
        *,
        title: str | None = None,
        subtitle: str | None = None,
        icon_name: str | None = None,
        volume: float | None = None,
        muted: bool | None = None,
        max_volume: float | None = None,
        sinks: tuple[DeviceInfo, ...] | None = None,
        current_sink_index: int | None = None,
    ) -> None:
        self._updating = True
        try:
            if title is not None:
                self.set_title(title)
            if subtitle is not None and subtitle != self.get_subtitle():
                self.set_subtitle(subtitle)
            if icon_name is not None and icon_name != self._last_icon:
                self._last_icon = icon_name
                apply_icon(self._icon, icon_name)
            if max_volume is not None and max_volume != self._max_volume:
                self._max_volume = max_volume
                self._scale.set_range(0.0, max_volume)
            if volume is not None:
                self._scale.set_value(VolumeMath.clamp(volume, maximum=self._max_volume))
                self._percent.set_label(VolumeMath.format_percent(volume))
            if muted is not None:
                self._mute_btn.set_active(muted)
                self._sync_mute_icon(muted, volume if volume is not None else self._scale.get_value())
            if sinks is not None:
                self._sinks = sinks
            if current_sink_index is not None:
                self._current_sink_index = current_sink_index
            if self._output_btn is not None and self._sinks_changed():
                self._rebuild_output_menu()
        finally:
            self._updating = False

    def update_from_stream(
        self,
        stream: StreamInfo,
        sinks: tuple[DeviceInfo, ...],
        max_volume: float,
        has_icon: Callable[[str], bool] | None = None,
    ) -> None:
        icon = resolve_icon_name(stream, has_icon=has_icon)
        subtitle = stream.media_name
        self.update_state(
            title=stream.name,
            subtitle=subtitle,
            icon_name=icon,
            volume=stream.volume,
            muted=stream.muted,
            max_volume=max_volume,
            sinks=sinks,
            current_sink_index=stream.sink_index,
        )

    def update_from_app(
        self,
        app: AppInfo,
        sinks: tuple[DeviceInfo, ...],
        max_volume: float,
        has_icon: Callable[[str], bool] | None = None,
    ) -> None:
        """Show an application; silent apps stay adjustable but look idle."""
        self.update_state(
            title=app.name,
            subtitle=app.subtitle,
            icon_name=resolve_icon_name(app, has_icon=has_icon),
            volume=app.volume,
            muted=app.muted,
            max_volume=max_volume,
            sinks=sinks,
            current_sink_index=app.sink_index,
        )
        if app.active:
            self.remove_css_class("mixer-app-idle")
            self._scale.set_tooltip_text(None)
        else:
            self.add_css_class("mixer-app-idle")
            self._scale.set_tooltip_text("Applied when the app starts playing")
        if self._output_btn is not None:
            self._output_btn.set_sensitive(app.active)
            self._output_btn.set_tooltip_text(
                "Move to output" if app.active else "Available while the app is playing"
            )

    def update_from_device(
        self,
        device: DeviceInfo,
        max_volume: float,
        icon_name: str = "audio-volume-high-symbolic",
        *,
        compact_title: str | None = None,
    ) -> None:
        # In compact device cards the picker already shows the device name.
        title = compact_title if compact_title is not None else device.description
        subtitle = "" if compact_title is not None else ("Default" if device.is_default else "")
        self.update_state(
            title=title,
            subtitle=subtitle,
            icon_name=icon_name,
            volume=device.volume,
            muted=device.muted,
            max_volume=max_volume,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _sync_mute_icon(self, muted: bool, volume: float) -> None:
        if muted or volume <= 0.001:
            icon = "audio-volume-muted-symbolic"
        elif volume < 0.33:
            icon = "audio-volume-low-symbolic"
        elif volume < 0.66:
            icon = "audio-volume-medium-symbolic"
        else:
            icon = "audio-volume-high-symbolic"
        self._mute_btn.set_icon_name(icon)

    def _handle_mute(self, button: Gtk.ToggleButton) -> None:
        if self._updating:
            return
        muted = button.get_active()
        self._sync_mute_icon(muted, self._scale.get_value())
        if self._on_mute is not None:
            self._on_mute(muted)

    def _handle_volume(self, scale: Gtk.Scale) -> None:
        if self._updating:
            return
        value = scale.get_value()
        self._percent.set_label(VolumeMath.format_percent(value))
        if not self._mute_btn.get_active():
            self._sync_mute_icon(False, value)
        if self._on_volume is not None:
            self._on_volume(value)

    def _sinks_changed(self) -> bool:
        signature = tuple((sink.index, sink.description) for sink in self._sinks)
        if (
            signature == self._menu_sink_signature
            and self._current_sink_index == self._menu_sink_index
        ):
            return False
        self._menu_sink_signature = signature
        self._menu_sink_index = self._current_sink_index
        return True

    def _rebuild_output_menu(self) -> None:
        if self._output_btn is None:
            return
        menu = Gtk.PopoverMenu()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        # Use a simple popover with buttons instead of GMenu for easier callbacks.
        popover = Gtk.Popover()
        popover.set_child(box)

        for sink in self._sinks:
            label = sink.description
            if sink.index == self._current_sink_index:
                label = f"✓ {label}"
            btn = Gtk.Button(label=label)
            btn.add_css_class("flat")
            btn.set_halign(Gtk.Align.FILL)
            sink_index = sink.index

            def _make_handler(idx: int) -> Callable[[Gtk.Button], None]:
                def _handler(_btn: Gtk.Button) -> None:
                    popover.popdown()
                    if self._on_output is not None:
                        self._on_output(idx)

                return _handler

            btn.connect("clicked", _make_handler(sink_index))
            box.append(btn)

        self._output_btn.set_popover(popover)
