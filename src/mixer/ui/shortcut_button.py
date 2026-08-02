"""Click-to-capture keyboard shortcut button."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk  # noqa: E402

AccelChangedHandler = Callable[[str], None]


def accel_to_label(accel: str) -> str:
    """Convert a GTK accelerator name to a human-readable label."""
    if not accel:
        return "Disabled"
    ok, keyval, mods = Gtk.accelerator_parse(accel)
    if not ok or not keyval:
        return accel
    return Gtk.accelerator_get_label(keyval, mods)


def is_valid_accel(accel: str) -> bool:
    """Return True if accel parses to a usable key binding."""
    if not accel:
        return False
    ok, keyval, _mods = Gtk.accelerator_parse(accel)
    return bool(ok and keyval)


class ShortcutButton(Gtk.Button):
    """Button that records a new accelerator when activated."""

    def __init__(
        self,
        accel: str,
        *,
        action_label: str = "Shortcut",
        on_changed: AccelChangedHandler | None = None,
    ) -> None:
        super().__init__()
        self.add_css_class("flat")
        self.add_css_class("mixer-shortcut-btn")
        self._accel = accel
        self._action_label = action_label
        self._on_changed = on_changed
        self._capturing = False
        self._controller: Gtk.EventControllerKey | None = None
        self._refresh_label()
        self._set_idle_tooltip()
        self.connect("clicked", self._on_clicked)

    @property
    def accel(self) -> str:
        return self._accel

    def set_accel(self, accel: str) -> None:
        self._accel = accel
        self._capturing = False
        self.remove_css_class("suggested-action")
        self._refresh_label()
        self._set_idle_tooltip()

    def _set_idle_tooltip(self) -> None:
        self.set_tooltip_text(
            f"Keyboard shortcut for {self._action_label.lower()}. "
            "Click to change it."
        )

    def _refresh_label(self) -> None:
        if self._capturing:
            self.set_label(f"{self._action_label}: press a key…")
            return
        key = accel_to_label(self._accel)
        self.set_label(f"{self._action_label}: {key}")

    def _on_clicked(self, *_args: object) -> None:
        if self._capturing:
            self._stop_capture(apply=False)
            return
        self._start_capture()

    def _start_capture(self) -> None:
        self._capturing = True
        self.add_css_class("suggested-action")
        self._refresh_label()
        self.set_tooltip_text(
            f"Press the new {self._action_label.lower()} shortcut "
            "(Esc to cancel, Backspace to clear)"
        )
        if self._controller is None:
            self._controller = Gtk.EventControllerKey()
            self._controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            self._controller.connect("key-pressed", self._on_key_pressed)
            self.add_controller(self._controller)
        self.grab_focus()

    def _stop_capture(self, *, apply: bool) -> None:
        self._capturing = False
        self.remove_css_class("suggested-action")
        self._refresh_label()
        self._set_idle_tooltip()

    def _on_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        if not self._capturing:
            return False

        if keyval in (Gdk.KEY_Escape,):
            self._stop_capture(apply=False)
            return True

        if keyval in (Gdk.KEY_BackSpace, Gdk.KEY_Delete):
            self._commit("")
            return True

        # Ignore modifier-only key presses.
        if keyval in (
            Gdk.KEY_Shift_L,
            Gdk.KEY_Shift_R,
            Gdk.KEY_Control_L,
            Gdk.KEY_Control_R,
            Gdk.KEY_Alt_L,
            Gdk.KEY_Alt_R,
            Gdk.KEY_Meta_L,
            Gdk.KEY_Meta_R,
            Gdk.KEY_Super_L,
            Gdk.KEY_Super_R,
            Gdk.KEY_Hyper_L,
            Gdk.KEY_Hyper_R,
            Gdk.KEY_ISO_Level3_Shift,
            Gdk.KEY_Caps_Lock,
        ):
            return True

        mods = state & Gtk.accelerator_get_default_mod_mask()
        accel = Gtk.accelerator_name(keyval, mods)
        if not accel or not is_valid_accel(accel):
            return True
        self._commit(accel)
        return True

    def _commit(self, accel: str) -> None:
        self._accel = accel
        self._stop_capture(apply=True)
        if self._on_changed is not None:
            self._on_changed(accel)
