"""Boxed list of per-application volume rows (main window and tray popup)."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk  # noqa: E402

from mixer.models.audio import AppInfo, DeviceInfo
from mixer.ui.channel_row import ChannelRow
from mixer.viewmodel.mixer_viewmodel import MixerViewModel

_SCALE_WIDTH = 240
_COMPACT_SCALE_WIDTH = 110


class AppList(Gtk.ListBox):
    """One row per application, kept in name order.

    Rows are keyed by app key and reused across renders, so a row survives
    its app starting/stopping playback (and a slider being dragged).
    """

    def __init__(
        self,
        viewmodel: MixerViewModel,
        *,
        compact: bool = False,
        show_output_picker: bool = False,
    ) -> None:
        super().__init__()
        self._vm = viewmodel
        self._compact = compact
        self._show_output_picker = show_output_picker
        self._rows: dict[str, ChannelRow] = {}
        self._sort_keys: dict[str, tuple[str, str]] = {}
        self.set_selection_mode(Gtk.SelectionMode.NONE)
        self.add_css_class("boxed-list")
        self.set_sort_func(self._compare_rows)

    def render(
        self,
        apps: tuple[AppInfo, ...],
        *,
        sinks: tuple[DeviceInfo, ...],
        max_volume: float,
        has_icon: Callable[[str], bool] | None = None,
    ) -> None:
        desired = {app.key for app in apps}
        for key in list(self._rows):
            if key not in desired:
                self.remove(self._rows.pop(key))
                self._sort_keys.pop(key, None)

        resort = False
        for app in apps:
            row = self._rows.get(app.key)
            if row is None:
                row = self._create_row(app, sinks, max_volume)
                row.app_key = app.key  # type: ignore[attr-defined]
                # One line each; long names ellipsize (full name in tooltip).
                row.set_title_lines(1)
                row.set_subtitle_lines(1)
                self._rows[app.key] = row
                self.append(row)
                resort = True
            sort_key = (app.name.casefold(), app.key)
            if self._sort_keys.get(app.key) != sort_key:
                self._sort_keys[app.key] = sort_key
                resort = True
            row.update_from_app(app, sinks=sinks, max_volume=max_volume, has_icon=has_icon)
            if row.get_tooltip_text() != app.name:
                row.set_tooltip_text(app.name)

        if resort:
            self.invalidate_sort()
        self.set_visible(bool(apps))

    def _create_row(
        self,
        app: AppInfo,
        sinks: tuple[DeviceInfo, ...],
        max_volume: float,
    ) -> ChannelRow:
        key = app.key
        return ChannelRow(
            title=app.name,
            subtitle=app.subtitle,
            volume=app.volume,
            muted=app.muted,
            max_volume=max_volume,
            compact=self._compact,
            scale_width=_COMPACT_SCALE_WIDTH if self._compact else _SCALE_WIDTH,
            show_output_picker=self._show_output_picker,
            sinks=sinks,
            current_sink_index=app.sink_index,
            on_mute=lambda muted: self._vm.set_app_mute(key, muted),
            on_volume=lambda volume: self._vm.set_app_volume(key, volume),
            on_output=lambda sink_index: self._vm.move_app(key, sink_index),
        )

    def _compare_rows(self, a: Gtk.ListBoxRow, b: Gtk.ListBoxRow) -> int:
        key_a = self._sort_keys.get(getattr(a, "app_key", ""), ("", ""))
        key_b = self._sort_keys.get(getattr(b, "app_key", ""), ("", ""))
        return (key_a > key_b) - (key_a < key_b)
