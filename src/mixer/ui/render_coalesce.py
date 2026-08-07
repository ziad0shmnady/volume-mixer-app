"""Coalesce frequent view-model updates into a single GTK idle render."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import gi

gi.require_version("GLib", "2.0")

from gi.repository import GLib  # noqa: E402

if TYPE_CHECKING:
    RenderFn = Callable[[], None]


class CoalescedRenderer:
    """Schedule at most one pending idle callback for a render function."""

    def __init__(self, render_fn: RenderFn) -> None:
        self._render_fn = render_fn
        self._scheduled = False

    def schedule(self) -> None:
        if self._scheduled:
            return
        self._scheduled = True
        GLib.idle_add(self._run)

    def _run(self) -> bool:
        self._scheduled = False
        self._render_fn()
        return False
