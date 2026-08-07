"""Device picker row for default sink / source selection."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from mixer.models.audio import DeviceInfo

DeviceHandler = Callable[[str], None]  # device name


class DevicePickerRow(Adw.ComboRow):
    """Dropdown to select the default sink or source."""

    def __init__(
        self,
        *,
        title: str,
        devices: tuple[DeviceInfo, ...] = (),
        selected_name: str | None = None,
        on_selected: DeviceHandler | None = None,
    ) -> None:
        super().__init__()
        self.set_title(title)
        self._on_selected = on_selected
        self._devices: tuple[DeviceInfo, ...] = ()
        self._devices_signature: tuple[tuple[str, str, bool], ...] | None = None
        self._selected_name: str | None = None
        self._updating = False
        self._string_list = Gtk.StringList.new([])
        self.set_model(self._string_list)
        self.connect("notify::selected", self._handle_selected)
        self.set_devices(devices, selected_name)

    def set_devices(
        self,
        devices: tuple[DeviceInfo, ...],
        selected_name: str | None = None,
    ) -> None:
        signature = tuple((device.name, device.description, device.is_default) for device in devices)
        if signature == self._devices_signature and selected_name == self._selected_name:
            return

        self._updating = True
        try:
            self._devices = devices
            self._devices_signature = signature
            self._selected_name = selected_name
            # Rebuild string list
            while self._string_list.get_n_items() > 0:
                self._string_list.remove(self._string_list.get_n_items() - 1)
            selected_idx = 0
            for i, device in enumerate(devices):
                self._string_list.append(device.description)
                if selected_name and device.name == selected_name:
                    selected_idx = i
                elif device.is_default and not selected_name:
                    selected_idx = i
            if devices:
                self.set_selected(selected_idx)
        finally:
            self._updating = False

    def _handle_selected(self, *_args: object) -> None:
        if self._updating or self._on_selected is None:
            return
        idx = self.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION or idx >= len(self._devices):
            return
        self._on_selected(self._devices[idx].name)
