"""Main mixer window."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from mixer.ui.channel_row import ChannelRow
from mixer.ui.device_row import DevicePickerRow
from mixer.ui.shortcut_button import ShortcutButton, accel_to_label
from mixer.util.logging import get_logger
from mixer.util.settings import DEFAULT_MUTE_INPUT_ACCEL, MixerSettings
from mixer.util.styles import load_app_css
from mixer.viewmodel.mixer_viewmodel import MixerViewModel

logger = get_logger("ui.window")

_STYLE_CANDIDATES = (
    Path(__file__).resolve().parents[3] / "data" / "style.css",  # repo checkout
    Path(__file__).resolve().parents[1] / "data" / "style.css",  # packaged
)


class MixerWindow(Adw.ApplicationWindow):
    """Primary application window."""

    def __init__(
        self,
        app: Adw.Application,
        viewmodel: MixerViewModel,
        *,
        settings: MixerSettings | None = None,
    ) -> None:
        super().__init__(application=app, title="Volume Mixer")
        self.set_default_size(780, 560)
        self.set_size_request(520, 360)

        self._vm = viewmodel
        self._settings = settings or MixerSettings.load()
        self._stream_rows: dict[int, ChannelRow] = {}
        self._sink_row: ChannelRow | None = None
        self._source_row: ChannelRow | None = None
        self._sink_picker: DevicePickerRow | None = None
        self._source_picker: DevicePickerRow | None = None
        self._debounce_source: int | None = None
        self._shortcut_btn: ShortcutButton | None = None
        self._icon_theme = Gtk.IconTheme.get_for_display(self.get_display())

        self._build_chrome()
        self._load_css()

        self._vm.add_listener(self._on_viewmodel_changed)
        # Periodic debounce flush (also covers edge cases).
        GLib.timeout_add(50, self._tick_debounce)

        # Initial render (may be empty until first snapshot).
        self._render()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_chrome(self) -> None:
        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._toast_overlay.set_child(self._stack)

        # --- Connected view ---
        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header = Adw.HeaderBar()
        self._content_box.append(header)

        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu = Gio.Menu()
        menu.append("Mute / Unmute Input", "app.mute-input")
        menu.append("Reset Input Mute Shortcut", "win.reset-mute-shortcut")
        menu.append("Allow Over-Amplification", "win.overamp")
        menu.append("Show Tray Icon", "app.show-tray")
        menu.append("Open at Startup", "app.start-on-login")
        menu.append("Refresh", "win.refresh")
        menu.append("About Volume Mixer", "win.about")
        menu.append("Quit", "app.quit")
        menu_btn.set_menu_model(menu)
        header.pack_end(menu_btn)

        self._install_actions()

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        self._content_box.append(scrolled)

        self._clamp = Adw.Clamp()
        self._clamp.set_maximum_size(920)
        self._clamp.set_tightening_threshold(720)
        scrolled.set_child(self._clamp)

        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self._page.set_margin_top(12)
        self._page.set_margin_bottom(24)
        self._page.set_margin_start(16)
        self._page.set_margin_end(16)
        self._clamp.set_child(self._page)

        # Output + Input: shared header row, then cards row (keeps titles aligned)
        headers_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        headers_row.add_css_class("mixer-section-header")
        headers_row.set_homogeneous(True)
        headers_row.set_valign(Gtk.Align.CENTER)
        self._page.append(headers_row)

        out_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        out_header.set_valign(Gtk.Align.CENTER)
        out_label = Gtk.Label(label="Output", xalign=0.0)
        out_label.add_css_class("heading")
        out_label.set_hexpand(True)
        out_label.set_halign(Gtk.Align.START)
        out_label.set_valign(Gtk.Align.CENTER)
        out_header.append(out_label)
        headers_row.append(out_header)

        in_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        in_header.set_valign(Gtk.Align.CENTER)
        in_label = Gtk.Label(label="Input", xalign=0.0)
        in_label.add_css_class("heading")
        in_label.set_hexpand(True)
        in_label.set_halign(Gtk.Align.START)
        in_label.set_valign(Gtk.Align.CENTER)
        in_header.append(in_label)

        self._input_mute_btn = Gtk.Button()
        self._input_mute_btn.add_css_class("flat")
        self._input_mute_btn.add_css_class("circular")
        self._input_mute_btn.set_icon_name("microphone-sensitivity-high-symbolic")
        self._input_mute_btn.set_valign(Gtk.Align.CENTER)
        self._input_mute_btn.connect("clicked", self._on_input_mute_clicked)
        in_header.append(self._input_mute_btn)

        self._shortcut_btn = ShortcutButton(
            self._settings.mute_input_accel,
            action_label="Mute/Unmute",
            on_changed=self._on_mute_shortcut_changed,
        )
        self._shortcut_btn.set_valign(Gtk.Align.CENTER)
        in_header.append(self._shortcut_btn)
        self._refresh_mute_tooltips()
        headers_row.append(in_header)

        devices_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        devices_row.add_css_class("mixer-devices-row")
        devices_row.set_homogeneous(True)
        devices_row.set_valign(Gtk.Align.START)
        self._page.append(devices_row)

        self._output_group = Adw.PreferencesGroup()
        self._output_group.add_css_class("mixer-device-card")
        self._output_group.set_hexpand(True)
        devices_row.append(self._output_group)

        self._sink_picker = DevicePickerRow(
            title="Device",
            on_selected=lambda name: self._vm.set_default_device("sink", name),
        )
        self._output_group.add(self._sink_picker)

        self._input_group = Adw.PreferencesGroup()
        self._input_group.add_css_class("mixer-device-card")
        self._input_group.set_hexpand(True)
        devices_row.append(self._input_group)

        self._source_picker = DevicePickerRow(
            title="Device",
            on_selected=lambda name: self._vm.set_default_device("source", name),
        )
        self._input_group.add(self._source_picker)

        # Applications section (full width)
        apps_label = Gtk.Label(label="Applications", xalign=0.0)
        apps_label.add_css_class("heading")
        self._page.append(apps_label)

        self._apps_group = Adw.PreferencesGroup()
        self._apps_group.add_css_class("mixer-apps-card")
        self._page.append(self._apps_group)

        self._empty_apps = Gtk.Label(
            label="No applications are playing audio right now.\n"
            "Open media in an app (YouTube, Discord call, Spotify…) to control it here."
        )
        self._empty_apps.add_css_class("mixer-empty-apps")
        self._empty_apps.set_halign(Gtk.Align.CENTER)
        self._empty_apps.set_justify(Gtk.Justification.CENTER)
        self._page.append(self._empty_apps)

        self._stack.add_named(self._content_box, "connected")

        # --- Disconnected view ---
        status = Adw.StatusPage(
            title="Audio service unavailable",
            description=(
                "Could not connect to PipeWire / PulseAudio. "
                "Waiting to reconnect…"
            ),
            icon_name="audio-volume-muted-symbolic",
        )
        self._stack.add_named(status, "disconnected")
        self._stack.set_visible_child_name("disconnected")

    def _install_actions(self) -> None:
        overamp = Gio.SimpleAction.new_stateful(
            "overamp",
            None,
            GLib.Variant.new_boolean(self._vm.allow_overamplification),
        )
        overamp.connect("change-state", self._on_overamp)
        self.add_action(overamp)

        refresh = Gio.SimpleAction.new("refresh", None)
        refresh.connect("activate", lambda *_: self._vm.backend.request_snapshot())
        self.add_action(refresh)

        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._on_about)
        self.add_action(about)

        reset_shortcut = Gio.SimpleAction.new("reset-mute-shortcut", None)
        reset_shortcut.connect("activate", self._on_reset_mute_shortcut)
        self.add_action(reset_shortcut)

    def _on_mute_shortcut_changed(self, accel: str) -> None:
        app = self.get_application()
        if app is not None and hasattr(app, "set_mute_input_accel"):
            app.set_mute_input_accel(accel)  # type: ignore[attr-defined]
        self._refresh_mute_tooltips()
        label = accel_to_label(accel) if accel else "Disabled"
        self._toast_overlay.add_toast(
            Adw.Toast(title=f"Input mute shortcut: {label}", timeout=2)
        )

    def _on_reset_mute_shortcut(self, *_args: object) -> None:
        if self._shortcut_btn is not None:
            self._shortcut_btn.set_accel(DEFAULT_MUTE_INPUT_ACCEL)
        self._on_mute_shortcut_changed(DEFAULT_MUTE_INPUT_ACCEL)

    def _refresh_mute_tooltips(self) -> None:
        accel = self._settings.mute_input_accel
        if accel:
            label = accel_to_label(accel)
            tip_mute = f"Mute microphone ({label})"
            tip_unmute = f"Unmute microphone ({label})"
        else:
            tip_mute = "Mute microphone"
            tip_unmute = "Unmute microphone"
        self._tip_mute = tip_mute
        self._tip_unmute = tip_unmute
        # Icon/state refreshed by _sync_input_mute_button on next render.
        source = self._vm.default_source()
        muted = bool(source and source.muted)
        self._sync_input_mute_button(muted)

    def _on_mute_input(self, *_args: object) -> None:
        app = self.get_application()
        if app is not None:
            app.activate_action("mute-input", None)

    def refresh_input_mute_ui(self) -> None:
        source = self._vm.default_source()
        if source is not None:
            self._sync_input_mute_button(source.muted)

    def _on_input_mute_clicked(self, *_args: object) -> None:
        self._on_mute_input()

    def _sync_input_mute_button(self, muted: bool) -> None:
        btn = getattr(self, "_input_mute_btn", None)
        if btn is None:
            return
        tip_mute = getattr(self, "_tip_mute", "Mute microphone")
        tip_unmute = getattr(self, "_tip_unmute", "Unmute microphone")
        if muted:
            btn.set_icon_name("microphone-sensitivity-muted-symbolic")
            btn.set_tooltip_text(tip_unmute)
            btn.add_css_class("error")
        else:
            btn.set_icon_name("microphone-sensitivity-high-symbolic")
            btn.set_tooltip_text(tip_mute)
            btn.remove_css_class("error")

    def _load_css(self) -> None:
        load_app_css(self.get_display())

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_overamp(self, action: Gio.SimpleAction, value: GLib.Variant) -> None:
        enabled = value.get_boolean()
        action.set_state(value)
        self._vm.set_overamplification(enabled)

    def _on_about(self, *_args: object) -> None:
        dialog = Adw.AboutDialog(
            application_name="Volume Mixer",
            application_icon="audio-volume-high",
            developer_name="Ziad",
            version="1.0.0",
            comments="Per-application volume control for Ubuntu (PipeWire / PulseAudio).",
            license_type=Gtk.License.MIT_X11,
        )
        dialog.present(self)

    # ------------------------------------------------------------------
    # View-model bridge
    # ------------------------------------------------------------------

    def _on_viewmodel_changed(self, _vm: MixerViewModel) -> None:
        # Always marshal onto the GTK main loop.
        GLib.idle_add(self._render, priority=GLib.PRIORITY_DEFAULT_IDLE)

    def _tick_debounce(self) -> bool:
        self._vm.flush_pending()
        return True  # keep timer

    def _has_icon(self, name: str) -> bool:
        return self._icon_theme.has_icon(name)

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def _render(self) -> bool:
        if not self._vm.connected:
            self._stack.set_visible_child_name("disconnected")
            return False

        self._stack.set_visible_child_name("connected")
        max_vol = self._vm.max_volume
        sinks = self._vm.sorted_sinks()
        sources = self._vm.sorted_sources()

        # Default sink picker + master row
        default_sink = self._vm.default_sink()
        if self._sink_picker is not None:
            self._sink_picker.set_devices(
                sinks,
                selected_name=self._vm.snapshot.default_sink_name,
            )

        if default_sink is not None:
            if self._sink_row is None:
                self._sink_row = ChannelRow(
                    title="Volume",
                    icon_name="audio-speakers-symbolic",
                    volume=default_sink.volume,
                    muted=default_sink.muted,
                    max_volume=max_vol,
                    compact=True,
                    on_mute=lambda muted, idx=default_sink.index: self._vm.set_mute(
                        "sink", idx, muted
                    ),
                    on_volume=lambda v, idx=default_sink.index: self._vm.set_volume(
                        "sink", idx, v
                    ),
                )
                self._output_group.add(self._sink_row)
            else:
                sink_index = default_sink.index
                self._sink_row._on_mute = (
                    lambda muted, idx=sink_index: self._vm.set_mute("sink", idx, muted)
                )
                self._sink_row._on_volume = lambda v, idx=sink_index: self._vm.set_volume(
                    "sink", idx, v
                )
                self._sink_row.update_from_device(
                    default_sink,
                    max_volume=max_vol,
                    icon_name="audio-speakers-symbolic",
                    compact_title="Volume",
                )

        # Default source picker + mic row
        default_source = self._vm.default_source()
        if self._source_picker is not None:
            self._source_picker.set_devices(
                sources,
                selected_name=self._vm.snapshot.default_source_name,
            )

        if default_source is not None:
            self._sync_input_mute_button(default_source.muted)
            if self._source_row is None:
                self._source_row = ChannelRow(
                    title="Volume",
                    icon_name="audio-input-microphone-symbolic",
                    volume=default_source.volume,
                    muted=default_source.muted,
                    max_volume=max_vol,
                    compact=True,
                    on_mute=lambda muted, idx=default_source.index: self._vm.set_mute(
                        "source", idx, muted
                    ),
                    on_volume=lambda v, idx=default_source.index: self._vm.set_volume(
                        "source", idx, v
                    ),
                )
                self._input_group.add(self._source_row)
            else:
                source_index = default_source.index
                self._source_row._on_mute = (
                    lambda muted, idx=source_index: self._vm.set_mute(
                        "source", idx, muted
                    )
                )
                self._source_row._on_volume = (
                    lambda v, idx=source_index: self._vm.set_volume("source", idx, v)
                )
                self._source_row.update_from_device(
                    default_source,
                    max_volume=max_vol,
                    icon_name="audio-input-microphone-symbolic",
                    compact_title="Volume",
                )

        # Application streams — reuse rows by index
        desired = {s.index for s in self._vm.sorted_streams()}
        for index in list(self._stream_rows.keys()):
            if index not in desired:
                row = self._stream_rows.pop(index)
                self._apps_group.remove(row)

        for stream in self._vm.sorted_streams():
            row = self._stream_rows.get(stream.index)
            if row is None:
                stream_index = stream.index
                row = ChannelRow(
                    title=stream.name,
                    subtitle=stream.media_name,
                    volume=stream.volume,
                    muted=stream.muted,
                    max_volume=max_vol,
                    show_output_picker=True,
                    sinks=sinks,
                    current_sink_index=stream.sink_index,
                    on_mute=lambda muted, idx=stream_index: self._vm.set_mute(
                        "stream", idx, muted
                    ),
                    on_volume=lambda v, idx=stream_index: self._vm.set_volume(
                        "stream", idx, v
                    ),
                    on_output=lambda sink_idx, idx=stream_index: self._vm.move_stream(
                        idx, sink_idx
                    ),
                )
                self._stream_rows[stream.index] = row
                self._apps_group.add(row)
            row.update_from_stream(
                stream,
                sinks=sinks,
                max_volume=max_vol,
                has_icon=self._has_icon,
            )

        self._empty_apps.set_visible(len(desired) == 0)
        return False  # for idle_add: do not repeat
