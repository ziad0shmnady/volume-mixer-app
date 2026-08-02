"""Load application-wide GTK CSS."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk  # noqa: E402

from mixer.util.logging import get_logger

logger = get_logger("util.styles")

_STYLE_CANDIDATES = (
    Path(__file__).resolve().parents[3] / "data" / "style.css",
    Path(__file__).resolve().parents[1] / "data" / "style.css",
)

_loaded = False


def load_app_css(display: Gdk.Display | None = None) -> None:
    """Load mixer CSS once for all windows."""
    global _loaded
    if _loaded:
        return
    css_path = next((p for p in _STYLE_CANDIDATES if p.is_file()), None)
    if css_path is None:
        return
    display = display or Gdk.Display.get_default()
    if display is None:
        return
    provider = Gtk.CssProvider()
    try:
        provider.load_from_path(str(css_path))
        Gtk.StyleContext.add_provider_for_display(
            display,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        _loaded = True
    except Exception:  # noqa: BLE001
        logger.exception("Failed to load CSS from %s", css_path)
