"""Shared window helpers for the exam flow."""

from __future__ import annotations

import tkinter as tk


def enable_fullscreen(window: tk.Misc) -> None:
    """Cover the desktop so no previously opened window stays visible."""
    try:
        window.attributes("-fullscreen", True)
    except tk.TclError:
        try:
            window.state("zoomed")
        except tk.TclError:
            pass
