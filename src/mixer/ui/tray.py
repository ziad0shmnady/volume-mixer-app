"""StatusNotifierItem (system tray) via session D-Bus — no extra packages."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from gi.repository import Gio, GLib

from mixer.util.logging import get_logger

logger = get_logger("ui.tray")

PopupHandler = Callable[[int, int], None]

APP_ID = "io.github.ziad.Mixer"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/com/canonical/dbusmenu"

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="u" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu">
      <arg direction="in" type="i" name="x"/>
      <arg direction="in" type="i" name="y"/>
    </method>
    <method name="Activate">
      <arg direction="in" type="i" name="x"/>
      <arg direction="in" type="i" name="y"/>
    </method>
    <method name="SecondaryActivate">
      <arg direction="in" type="i" name="x"/>
      <arg direction="in" type="i" name="y"/>
    </method>
    <method name="Scroll">
      <arg direction="in" type="i" name="delta"/>
      <arg direction="in" type="s" name="orientation"/>
    </method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewOverlayIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus">
      <arg name="status" type="s"/>
    </signal>
  </interface>
</node>
"""

DBUSMENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg direction="in" type="i" name="parentId"/>
      <arg direction="in" type="i" name="recursionDepth"/>
      <arg direction="in" type="as" name="propertyNames"/>
      <arg direction="out" type="u" name="revision"/>
      <arg direction="out" type="(ia{sv}av)" name="layout"/>
    </method>
    <method name="GetGroupProperties">
      <arg direction="in" type="ai" name="ids"/>
      <arg direction="in" type="as" name="propertyNames"/>
      <arg direction="out" type="a(ia{sv})" name="properties"/>
    </method>
    <method name="GetProperty">
      <arg direction="in" type="i" name="id"/>
      <arg direction="in" type="s" name="name"/>
      <arg direction="out" type="v" name="value"/>
    </method>
    <method name="Event">
      <arg direction="in" type="i" name="id"/>
      <arg direction="in" type="s" name="eventId"/>
      <arg direction="in" type="v" name="data"/>
      <arg direction="in" type="u" name="timestamp"/>
    </method>
    <method name="EventGroup">
      <arg direction="in" type="a(isvu)" name="events"/>
      <arg direction="out" type="ai" name="idErrors"/>
    </method>
    <method name="AboutToShow">
      <arg direction="in" type="i" name="id"/>
      <arg direction="out" type="b" name="needUpdate"/>
    </method>
    <method name="AboutToShowGroup">
      <arg direction="in" type="ai" name="ids"/>
      <arg direction="out" type="ai" name="updatesNeeded"/>
      <arg direction="out" type="ai" name="idErrors"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})" name="updatedProps"/>
      <arg type="a(ias)" name="removedProps"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg type="u" name="revision"/>
      <arg type="i" name="parent"/>
    </signal>
  </interface>
</node>
"""


_WATCHER_NAME = "org.kde.StatusNotifierWatcher"


class TrayIcon:
    """Session-bus StatusNotifierItem with a small DBusMenu."""

    def __init__(
        self,
        *,
        on_popup: PopupHandler,
        on_mute_input: Callable[[], None],
        on_open_mixer: Callable[[], None],
        on_toggle_autostart: Callable[[], None],
        on_quit: Callable[[], None],
        start_on_login: bool = False,
        icon_name: str = "audio-volume-high",
        title: str = "Volume Mixer",
    ) -> None:
        self._on_popup = on_popup
        self._on_mute_input = on_mute_input
        self._on_open_mixer = on_open_mixer
        self._on_toggle_autostart = on_toggle_autostart
        self._on_quit = on_quit
        self._start_on_login = start_on_login
        self._icon_name = icon_name
        self._title = title
        self._tooltip = title
        self._muted = False
        self._revision = 1
        self._connection: Gio.DBusConnection | None = None
        self._sni_reg: int | None = None
        self._menu_reg: int | None = None
        self._bus_name: str | None = None
        self._own_name_id: int | None = None
        self._watcher_watch_id: int | None = None
        self._registered = False

    def start(self) -> bool:
        """Export the tray item. Returns False if the watcher is unavailable."""
        try:
            self._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as exc:
            logger.warning("No session bus for tray icon: %s", exc)
            return False

        self._bus_name = f"org.kde.StatusNotifierItem-{os_getpid()}-1"
        self._own_name_id = Gio.bus_own_name_on_connection(
            self._connection,
            self._bus_name,
            Gio.BusNameOwnerFlags.NONE,
            None,
            None,
        )

        sni_node = Gio.DBusNodeInfo.new_for_xml(SNI_XML)
        menu_node = Gio.DBusNodeInfo.new_for_xml(DBUSMENU_XML)
        assert sni_node.interfaces and menu_node.interfaces

        self._sni_reg = self._connection.register_object(
            ITEM_PATH,
            sni_node.interfaces[0],
            self._sni_method,
            self._sni_get_property,
            None,
        )
        self._menu_reg = self._connection.register_object(
            MENU_PATH,
            menu_node.interfaces[0],
            self._menu_method,
            self._menu_get_property,
            None,
        )

        # Register whenever the tray host appears. At login the AppIndicator
        # extension may not be up yet when we autostart, and GNOME Shell
        # restarts drop every registered item; watching covers both.
        self._watcher_watch_id = Gio.bus_watch_name_on_connection(
            self._connection,
            _WATCHER_NAME,
            Gio.BusNameWatcherFlags.NONE,
            self._on_watcher_appeared,
            self._on_watcher_vanished,
        )
        return True

    def _on_watcher_appeared(self, *_args: object) -> None:
        if self._connection is None:
            return
        if self._register_with_watcher():
            self._registered = True
            logger.info("Tray icon registered as %s", self._bus_name)
        else:
            logger.warning("Tray host present but registration failed")

    def _on_watcher_vanished(self, *_args: object) -> None:
        if self._registered:
            logger.info("Tray host went away; will re-register when it returns")
        else:
            logger.info("Waiting for a tray host (AppIndicator extension)…")
        self._registered = False

    def stop(self) -> None:
        if self._watcher_watch_id is not None:
            Gio.bus_unwatch_name(self._watcher_watch_id)
            self._watcher_watch_id = None
        self._registered = False
        if self._connection is None:
            return
        if self._sni_reg is not None:
            self._connection.unregister_object(self._sni_reg)
            self._sni_reg = None
        if self._menu_reg is not None:
            self._connection.unregister_object(self._menu_reg)
            self._menu_reg = None
        if self._own_name_id is not None:
            Gio.bus_unown_name(self._own_name_id)
            self._own_name_id = None
        self._connection = None

    def set_mic_muted(self, muted: bool) -> None:
        """Update icon/tooltip to reflect microphone mute state."""
        if self._muted == muted:
            return
        self._muted = muted
        self._icon_name = (
            "microphone-sensitivity-muted"
            if muted
            else "audio-volume-high"
        )
        self._tooltip = (
            "Volume Mixer — Microphone muted"
            if muted
            else "Volume Mixer"
        )
        self._emit_sni("NewIcon")
        self._emit_sni("NewToolTip")
        self._revision += 1
        self._emit_menu_layout()

    def _register_with_watcher(self) -> bool:
        assert self._connection is not None and self._bus_name is not None
        try:
            self._connection.call_sync(
                "org.kde.StatusNotifierWatcher",
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (self._bus_name,)),
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            return True
        except GLib.Error as exc:
            logger.warning("RegisterStatusNotifierItem failed: %s", exc)
            # Some hosts want the object path instead of the bus name.
            try:
                self._connection.call_sync(
                    "org.kde.StatusNotifierWatcher",
                    "/StatusNotifierWatcher",
                    "org.kde.StatusNotifierWatcher",
                    "RegisterStatusNotifierItem",
                    GLib.Variant("(s)", (ITEM_PATH,)),
                    None,
                    Gio.DBusCallFlags.NONE,
                    -1,
                    None,
                )
                return True
            except GLib.Error as exc2:
                logger.warning("RegisterStatusNotifierItem (path) failed: %s", exc2)
                return False

    # ------------------------------------------------------------------
    # SNI
    # ------------------------------------------------------------------

    def _sni_get_property(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _iface: str,
        name: str,
    ) -> GLib.Variant | None:
        mapping: dict[str, GLib.Variant] = {
            "Category": GLib.Variant("s", "Hardware"),
            "Id": GLib.Variant("s", APP_ID),
            "Title": GLib.Variant("s", self._title),
            "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("u", 0),
            "IconName": GLib.Variant("s", self._icon_name),
            "IconThemePath": GLib.Variant("s", ""),
            "ToolTip": GLib.Variant(
                "(sa(iiay)ss)",
                (self._icon_name, [], self._title, self._tooltip),
            ),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", MENU_PATH),
        }
        return mapping.get(name)

    def _sni_method(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _iface: str,
        method: str,
        params: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method == "Activate":
            x, y = params.unpack()
            GLib.idle_add(self._on_popup, int(x), int(y))
            invocation.return_value(None)
            return
        if method in ("ContextMenu", "SecondaryActivate"):
            # GNOME Shell shows the DBusMenu natively on right-click.
            invocation.return_value(None)
            return
        if method == "Scroll":
            invocation.return_value(None)
            return
        invocation.return_error_literal(
            Gio.dbus_error_quark(),
            Gio.DBusError.UNKNOWN_METHOD,
            f"Unknown method {method}",
        )

    def _emit_sni(self, signal: str) -> None:
        if self._connection is None:
            return
        try:
            self._connection.emit_signal(
                None,
                ITEM_PATH,
                "org.kde.StatusNotifierItem",
                signal,
                None,
            )
        except GLib.Error:
            logger.exception("Failed to emit %s", signal)

    # ------------------------------------------------------------------
    # DBusMenu
    # ------------------------------------------------------------------

    def set_start_on_login(self, enabled: bool) -> None:
        if self._start_on_login == enabled:
            return
        self._start_on_login = enabled
        self._revision += 1
        self._emit_menu_layout()

    def _menu_items(self) -> list[tuple[int, dict[str, Any]]]:
        mute_label = "Unmute Input" if self._muted else "Mute Input"
        return [
            (
                1,
                {
                    "label": GLib.Variant("s", "Application Volumes"),
                    "type": GLib.Variant("s", "standard"),
                    "enabled": GLib.Variant("b", True),
                },
            ),
            (
                2,
                {
                    "label": GLib.Variant("s", mute_label),
                    "type": GLib.Variant("s", "standard"),
                    "enabled": GLib.Variant("b", True),
                },
            ),
            (
                3,
                {
                    "label": GLib.Variant("s", "Open Full Mixer"),
                    "type": GLib.Variant("s", "standard"),
                    "enabled": GLib.Variant("b", True),
                },
            ),
            (4, {"type": GLib.Variant("s", "separator")}),
            (
                5,
                {
                    "label": GLib.Variant("s", "Open at Startup"),
                    "type": GLib.Variant("s", "toggle"),
                    "toggle-type": GLib.Variant("s", "check"),
                    "toggle-state": GLib.Variant("u", 1 if self._start_on_login else 0),
                    "enabled": GLib.Variant("b", True),
                },
            ),
            (6, {"type": GLib.Variant("s", "separator")}),
            (
                7,
                {
                    "label": GLib.Variant("s", "Quit"),
                    "type": GLib.Variant("s", "standard"),
                    "enabled": GLib.Variant("b", True),
                },
            ),
        ]

    def _menu_get_property(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _iface: str,
        name: str,
    ) -> GLib.Variant | None:
        mapping = {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }
        return mapping.get(name)

    def _build_layout(self) -> tuple[int, dict[str, GLib.Variant], list[GLib.Variant]]:
        # Children must be (ia{sv}av) variants — not wrapped in an extra "v", or
        # GNOME Shell's appindicator DBusMenu client cannot parse the layout.
        children: list[GLib.Variant] = []
        for item_id, props in self._menu_items():
            children.append(GLib.Variant("(ia{sv}av)", (item_id, props, [])))
        root_props = {"children-display": GLib.Variant("s", "submenu")}
        return (0, root_props, children)

    def _menu_method(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _iface: str,
        method: str,
        params: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method == "GetLayout":
            invocation.return_value(
                GLib.Variant("(u(ia{sv}av))", (self._revision, self._build_layout()))
            )
            return
        if method == "GetGroupProperties":
            ids, _names = params.unpack()
            wanted = set(ids)
            result = [
                (item_id, props)
                for item_id, props in self._menu_items()
                if item_id in wanted
            ]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (result,)))
            return
        if method == "GetProperty":
            item_id, prop = params.unpack()
            for mid, props in self._menu_items():
                if mid == item_id and prop in props:
                    invocation.return_value(GLib.Variant("(v)", (props[prop],)))
                    return
            invocation.return_value(
                GLib.Variant("(v)", (GLib.Variant("s", ""),))
            )
            return
        if method == "Event":
            item_id, event_id, _data, _ts = params.unpack()
            if event_id == "clicked":
                self._handle_menu_click(item_id)
            invocation.return_value(None)
            return
        if method == "EventGroup":
            events = params.unpack()[0]
            for item_id, event_id, _data, _ts in events:
                if event_id == "clicked":
                    self._handle_menu_click(item_id)
            invocation.return_value(GLib.Variant("(ai)", ([],)))
            return
        if method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (True,)))
            return
        if method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
            return
        invocation.return_error_literal(
            Gio.dbus_error_quark(),
            Gio.DBusError.UNKNOWN_METHOD,
            f"Unknown method {method}",
        )

    def _handle_menu_click(self, item_id: int) -> None:
        if item_id == 1:
            GLib.idle_add(self._on_popup, 0, 0)
        elif item_id == 2:
            GLib.idle_add(self._on_mute_input)
        elif item_id == 3:
            GLib.idle_add(self._on_open_mixer)
        elif item_id == 5:
            GLib.idle_add(self._on_toggle_autostart)
        elif item_id == 7:
            GLib.idle_add(self._on_quit)

    def _emit_menu_layout(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.emit_signal(
                None,
                MENU_PATH,
                "com.canonical.dbusmenu",
                "LayoutUpdated",
                GLib.Variant("(ui)", (self._revision, 0)),
            )
        except GLib.Error:
            logger.exception("Failed to emit LayoutUpdated")


def os_getpid() -> int:
    import os

    return os.getpid()

