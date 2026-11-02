"""Small Tk Canvas charts used by the exam analytics dashboard."""

from __future__ import annotations

import tkinter as tk
from datetime import datetime

_BG = "#0b0f14"
_PANEL = "#161b22"
_TEXT = "#e6edf3"
_MUTED = "#8b949e"
_ACCENT = "#58a6ff"
_GRID = "#30363d"

_COLORS = {
    "strong": "#3fb950",
    "Mastered": "#3fb950",
    "developing": "#d29922",
    "Learning": "#58a6ff",
    "weak": "#f85149",
    "critical": "#f85149",
    "Needs Improvement": "#f85149",
    "insufficient_data": "#6e7681",
    "not_started": "#484f58",
}


def _truncate(text: str, limit: int) -> str:
    clean = str(text)
    return clean if len(clean) <= limit else clean[: max(1, limit - 1)] + "…"


def _short_time(value: object) -> str:
    if isinstance(value, datetime):
        stamp = value
    else:
        try:
            stamp = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return "—"
    return stamp.strftime("%d %b")


class HorizontalBarChart(tk.Canvas):
    """Horizontal 0-100% bars with an explicit insufficient-data state."""

    def __init__(self, parent: tk.Widget, height: int = 190, max_rows: int = 9):
        super().__init__(
            parent, height=height, bg=_BG, highlightthickness=0, bd=0,
        )
        self.max_rows = max_rows
        self._rows: list[dict] = []
        self._empty_text = "Not enough graded answers yet."
        self.bind("<Configure>", lambda _event: self.redraw())

    def set_rows(self, rows: list[dict], empty_text: str | None = None) -> None:
        self._rows = list(rows)[: self.max_rows]
        if empty_text:
            self._empty_text = empty_text
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        width = max(200, self.winfo_width())
        height = max(80, self.winfo_height())
        if not self._rows:
            self.create_text(
                width / 2, height / 2, text=self._empty_text,
                fill=_MUTED, font=("Consolas", 9), justify="center",
            )
            return

        top, bottom = 8, 8
        row_height = max(16, (height - top - bottom) / len(self._rows))
        left = min(180, max(110, int(width * 0.22)))
        right = max(left + 80, width - 52)
        for index, row in enumerate(self._rows):
            center_y = top + row_height * index + row_height / 2
            label = _truncate(row.get("label", ""), 26)
            self.create_text(
                6, center_y, text=label, anchor="w", fill=_TEXT,
                font=("Consolas", 8),
            )
            self.create_rectangle(
                left, center_y - 6, right, center_y + 6,
                fill=_PANEL, outline="",
            )
            value = row.get("value")
            color = _COLORS.get(
                str(row.get("color_key") or row.get("status") or ""), _ACCENT
            )
            if value is None:
                self.create_text(
                    left + 6, center_y, text="insufficient data",
                    anchor="w", fill=_MUTED, font=("Consolas", 8),
                )
                continue
            fraction = max(0.0, min(100.0, float(value))) / 100
            end = left + max(2, (right - left) * fraction)
            self.create_rectangle(
                left, center_y - 6, end, center_y + 6,
                fill=color, outline="",
            )
            self.create_text(
                min(right + 4, width - 4), center_y, text=f"{value:.0f}%",
                anchor="e", fill=_TEXT, font=("Consolas", 8, "bold"),
            )


class SessionLineChart(tk.Canvas):
    """Chronological auto-graded accuracy across submitted sessions."""

    def __init__(self, parent: tk.Widget, height: int = 190):
        super().__init__(
            parent, height=height, bg=_BG, highlightthickness=0, bd=0,
        )
        self._sessions: list[dict] = []
        self.bind("<Configure>", lambda _event: self.redraw())

    def set_sessions(self, sessions: list[dict]) -> None:
        self._sessions = [
            session for session in sessions
            if session.get("accuracy") is not None
        ]
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        width = max(240, self.winfo_width())
        height = max(100, self.winfo_height())
        if not self._sessions:
            self.create_text(
                width / 2, height / 2,
                text="No auto-graded sessions yet.",
                fill=_MUTED, font=("Consolas", 9),
            )
            return

        left, right = 42, width - 18
        top, bottom = 12, height - 24
        for value, label in ((100, "100"), (50, "50"), (0, "0")):
            y = bottom - (bottom - top) * value / 100
            self.create_line(left, y, right, y, fill=_GRID)
            self.create_text(
                left - 6, y, text=label, anchor="e", fill=_MUTED,
                font=("Consolas", 7),
            )

        count = len(self._sessions)
        if count == 1:
            xs = [(left + right) / 2]
        else:
            xs = [
                left + (right - left) * index / (count - 1)
                for index in range(count)
            ]
        points = [
            (
                x,
                bottom - (bottom - top) * float(session["accuracy"]) / 100,
            )
            for x, session in zip(xs, self._sessions)
        ]
        if len(points) > 1:
            flat = [coordinate for point in points for coordinate in point]
            self.create_line(*flat, fill=_ACCENT, width=2, smooth=False)
        for index, (point, session) in enumerate(zip(points, self._sessions)):
            x, y = point
            self.create_oval(
                x - 4, y - 4, x + 4, y + 4,
                fill=_ACCENT, outline=_BG, width=1,
            )
            if count <= 8 or index in {0, count - 1}:
                self.create_text(
                    x, bottom + 11,
                    text=f"{_short_time(session.get('submitted_at'))} "
                         f"{'P' if session.get('mode') == 'practice' else 'M'}",
                    fill=_MUTED, font=("Consolas", 7),
                )
            if index == count - 1:
                self.create_text(
                    x, y - 12, text=f"{session['accuracy']:.0f}%",
                    fill=_TEXT, font=("Consolas", 8, "bold"),
                )
        if count == 1:
            self.create_text(
                left, top, anchor="w", fill=_MUTED, font=("Consolas", 8),
                text="One session only; a trend needs another session.",
            )
