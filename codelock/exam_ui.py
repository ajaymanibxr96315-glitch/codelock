"""Tkinter workspace for syllabus extraction and editable topic approval."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable
import json

from . import exam_analytics
from . import exam_engine
from .db import StudentStore, StoreError
from .exam import DocumentError, extract_document, extract_topics, validate_topic_tree
from .exam_charts import HorizontalBarChart, SessionLineChart
from .ui_common import enable_fullscreen

_BG = "#0d1117"
_PANEL = "#161b22"
_TEXT = "#e6edf3"
_MUTED = "#8b949e"
_ACCENT = "#58a6ff"
_GREEN = "#3fb950"
_RED = "#b62324"
_AMBER = "#d29922"

UPLOAD_FILETYPES = (
    ("PDF or Word documents", "*.pdf *.docx"),
    ("PDF documents", "*.pdf"),
    ("Word documents", "*.docx"),
    ("Text files", "*.txt"),
    ("All files", "*.*"),
)


class ExamPreparationWindow:
    def __init__(self, parent: tk.Tk, store: StudentStore, student_id: int,
                 on_close: Callable[[], None] | None = None) -> None:
        self.parent = parent
        self.on_close = on_close
        self.store = store
        self.student_id = student_id
        self.window = tk.Toplevel(parent)
        self.window.title("CodeLock — Exam Preparation")
        self.window.configure(bg=_BG)
        self.window.geometry("980x700")
        self.window.minsize(820, 600)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        enable_fullscreen(self.window)
        self._events: queue.Queue[tuple] = queue.Queue()
        self._busy = False
        self._closing = False
        self.workspace_id: int | None = None
        self.workspace: dict | None = None
        self.units: list[dict] = []
        self._workspace_items: dict[str, int] = {}
        self._runner = None
        self._result_windows: list = []
        self._session_items: dict[str, int] = {}
        self._session_buttons: list[tk.Button] = []
        self._analytics_buttons: list[tk.Button] = []
        self._topic_rows: dict[str, dict] = {}
        self._outline_cleared_content = False
        self.analytics_range = tk.StringVar(value="All Time")

        header = tk.Frame(self.window, bg=_BG)
        header.pack(fill="x", padx=18, pady=(14, 2))
        tk.Label(header, text="AI EXAM PREPARATION", bg=_BG, fg=_TEXT,
                 font=("Consolas", 17, "bold")).pack(side="left")
        self.exit_btn = tk.Button(header, text="EXIT CODELOCK", command=self.close,
                                  bg=_PANEL, fg=_TEXT, relief="flat",
                                  font=("Consolas", 9, "bold"), padx=12, pady=6,
                                  cursor="hand2")
        self.exit_btn.pack(side="right")
        tk.Label(self.window, text="Create a subject workspace, review extracted topics, and approve the syllabus.",
                 bg=_BG, fg=_MUTED, font=("Consolas", 9)).pack(anchor="w", padx=18, pady=(0, 10))

        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self.syllabus_tab = tk.Frame(self.notebook, bg=_BG)
        self.notes_tab = tk.Frame(self.notebook, bg=_BG)
        self.questions_tab = tk.Frame(self.notebook, bg=_BG)
        self.practice_tab = tk.Frame(self.notebook, bg=_BG)
        self.mock_tab = tk.Frame(self.notebook, bg=_BG)
        self.results_tab = tk.Frame(self.notebook, bg=_BG)
        self.analytics_tab = tk.Frame(self.notebook, bg=_BG)
        self.notebook.add(self.syllabus_tab, text="Syllabus")
        self.notebook.add(self.notes_tab, text="Revision Notes")
        self.notebook.add(self.questions_tab, text="Question Bank")
        self.notebook.add(self.practice_tab, text="Practice")
        self.notebook.add(self.mock_tab, text="Mock Exam")
        self.notebook.add(self.results_tab, text="Results")
        self.notebook.add(self.analytics_tab, text="Analytics")
        self._build_syllabus_tab()
        self._build_generation_placeholders()
        self._build_session_tabs()
        self._build_analytics_tab()
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self._refresh_workspaces()
        self.window.after(80, self._drain_events)
        self.window.grab_set()
        # The topmost picker is withdrawn just before this window opens, so
        # Windows can give the foreground back to another application and leave
        # this workspace hidden behind it (the user sees no CREATE form).
        try:
            self.window.attributes("-topmost", True)
            self.window.lift()
            self.window.focus_force()
            self.window.after(1200, self._release_topmost)
        except tk.TclError:
            pass

    def _release_topmost(self) -> None:
        try:
            if self.window.winfo_exists():
                self.window.attributes("-topmost", False)
        except tk.TclError:
            pass

    def _build_syllabus_tab(self) -> None:
        create = tk.LabelFrame(self.syllabus_tab, text="New subject workspace", bg=_BG, fg=_TEXT,
                               padx=8, pady=6, font=("Consolas", 9, "bold"))
        create.pack(fill="x", padx=10, pady=(10, 6))
        self.subject_entry = self._entry(create, "Subject", 0, 0, "")
        self.level_entry = self._entry(create, "Course / level", 0, 2, "")
        self.date_entry = self._entry(create, "Exam date (YYYY-MM-DD)", 1, 0, "")
        self.marks_entry = self._entry(create, "Total marks", 1, 2, "100")
        self.duration_entry = self._entry(create, "Duration (minutes)", 1, 4, "180")
        self.create_workspace_btn = tk.Button(create, text="CREATE", command=self._create_workspace,
                                              bg=_GREEN, fg="#07130a", relief="flat", padx=14)
        self.create_workspace_btn.grid(row=0, column=6, rowspan=2, padx=8)

        selector = tk.Frame(self.syllabus_tab, bg=_BG)
        selector.pack(fill="x", padx=12, pady=(4, 8))
        tk.Label(selector, text="Workspace", bg=_BG, fg=_TEXT).pack(side="left")
        self.workspace_combo = ttk.Combobox(selector, state="readonly", width=64)
        self.workspace_combo.pack(side="left", padx=8, fill="x", expand=True)
        self.workspace_combo.bind("<<ComboboxSelected>>", self._choose_workspace)
        self.upload_btn = tk.Button(selector, text="UPLOAD SYLLABUS", command=self._choose_file,
                                    bg=_ACCENT, fg="#07111d", relief="flat", padx=12)
        self.upload_btn.pack(side="right")

        self.document_status = tk.Label(self.syllabus_tab, text="Create or select a workspace.",
                                        bg=_BG, fg=_MUTED, anchor="w")
        self.document_status.pack(fill="x", padx=14, pady=(0, 5))
        tree_frame = tk.Frame(self.syllabus_tab, bg=_BG)
        tree_frame.pack(fill="both", expand=True, padx=12)
        self.topic_tree = ttk.Treeview(tree_frame, columns=("kind",), show="tree headings", selectmode="browse")
        self.topic_tree.heading("#0", text="Unit / topic")
        self.topic_tree.heading("kind", text="Type")
        self.topic_tree.column("#0", width=690, anchor="w")
        self.topic_tree.column("kind", width=100, anchor="center")
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.topic_tree.yview)
        self.topic_tree.configure(yscrollcommand=scroll.set)
        self.topic_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        actions = tk.Frame(self.syllabus_tab, bg=_BG)
        actions.pack(fill="x", padx=12, pady=8)
        self.outline_buttons = []
        for label, command in (("ADD UNIT", self._add_unit), ("ADD TOPIC", self._add_topic),
                               ("RENAME", self._rename_selected), ("REMOVE", self._remove_selected),
                               ("SAVE DRAFT", self._save_draft), ("APPROVE SYLLABUS", self._approve)):
            button = tk.Button(actions, text=label, command=command, bg=_PANEL, fg=_TEXT,
                               relief="flat", padx=10, pady=7)
            button.pack(side="left", padx=(0, 5))
            self.outline_buttons.append(button)
        self.progress_label = tk.Label(actions, text="0 units · 0 topics", bg=_BG, fg=_MUTED)
        self.progress_label.pack(side="right", padx=4)

    def _build_generation_placeholders(self) -> None:
        from .ai import AIError, AIProvider

        try:
            provider = AIProvider.from_environment()
            provider_text = f"AI provider: {provider.provider} · model: {provider.model}"
            provider_color = _GREEN
        except AIError:
            provider_text = (
                "No AI provider is configured. Notes and questions will be generated "
                "offline from your uploaded source."
            )
            provider_color = _MUTED
        for frame in (self.notes_tab, self.questions_tab):
            tk.Label(frame, text=provider_text, bg=_BG, fg=provider_color,
                     justify="left", wraplength=850).pack(anchor="w", padx=14, pady=(12, 4))

        notes_controls = tk.Frame(self.notes_tab, bg=_BG)
        notes_controls.pack(fill="x", padx=14, pady=5)
        tk.Label(notes_controls, text="Length", bg=_BG, fg=_TEXT).pack(side="left")
        self.note_style = ttk.Combobox(notes_controls, state="readonly", width=16,
                                       values=("very short", "standard", "detailed"))
        self.note_style.set("standard")
        self.note_style.pack(side="left", padx=8)
        self.generate_notes_btn = tk.Button(notes_controls, text="GENERATE NOTES", command=self._generate_notes,
                                            bg=_ACCENT, fg="#07111d", relief="flat", padx=12, pady=6)
        self.generate_notes_btn.pack(side="left")
        self.save_notes_btn = tk.Button(notes_controls, text="SAVE EDITS", command=self._save_notes_edits,
                                        bg=_PANEL, fg=_TEXT, relief="flat", padx=12, pady=6)
        self.save_notes_btn.pack(side="left", padx=6)
        self.notes_status = tk.Label(self.notes_tab, text="Review and approve a syllabus first.",
                                     bg=_BG, fg=_MUTED, anchor="w")
        self.notes_status.pack(fill="x", padx=14, pady=3)
        self.notes_text = self._content_text(self.notes_tab)

        question_controls = tk.Frame(self.questions_tab, bg=_BG)
        question_controls.pack(fill="x", padx=14, pady=8)
        tk.Label(question_controls, text="Type", bg=_BG, fg=_TEXT).pack(side="left")
        self.question_type = ttk.Combobox(
            question_controls, state="readonly", width=20,
            values=("Multiple choice", "True or false", "Fill in the blanks", "One-word answer",
                    "Short answer", "Long answer", "Practical", "Programming", "Viva"),
        )
        self.question_type.set("Multiple choice")
        self.question_type.pack(side="left", padx=6)
        tk.Label(question_controls, text="Difficulty", bg=_BG, fg=_TEXT).pack(side="left", padx=(8, 0))
        self.question_difficulty = ttk.Combobox(question_controls, state="readonly", width=10,
                                                values=("Beginner", "Easy", "Medium", "Hard"))
        self.question_difficulty.set("Medium")
        self.question_difficulty.pack(side="left", padx=6)
        tk.Label(question_controls, text="Count", bg=_BG, fg=_TEXT).pack(side="left", padx=(8, 0))
        self.question_count = tk.Spinbox(question_controls, from_=1, to=50, width=4)
        self.question_count.delete(0, "end")
        self.question_count.insert(0, "5")
        self.question_count.pack(side="left", padx=6)
        self.generate_questions_btn = tk.Button(question_controls, text="GENERATE", command=self._generate_questions,
                                                bg=_ACCENT, fg="#07111d", relief="flat", padx=12, pady=6)
        self.generate_questions_btn.pack(side="left", padx=4)
        self.save_questions_btn = tk.Button(question_controls, text="SAVE EDITS", command=self._save_question_edits,
                                            bg=_PANEL, fg=_TEXT, relief="flat", padx=12, pady=6)
        self.save_questions_btn.pack(side="left", padx=4)
        self.questions_status = tk.Label(self.questions_tab, text="Review and approve a syllabus first.",
                                          bg=_BG, fg=_MUTED, anchor="w")
        self.questions_status.pack(fill="x", padx=14, pady=(4, 3))
        self.questions_text = self._content_text(self.questions_tab)

    def _content_text(self, parent: tk.Widget) -> tk.Text:
        frame = tk.Frame(parent, bg=_BG)
        frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        text = tk.Text(frame, wrap="word", undo=True, bg="#0b0f14", fg=_TEXT,
                       insertbackground=_TEXT, relief="flat", padx=10, pady=8,
                       font=("Consolas", 14))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return text

    def _build_session_tabs(self) -> None:
        tk.Label(
            self.practice_tab,
            text="Topic-wise practice. Every answer is checked immediately, and written answers are saved for review.",
            bg=_BG, fg=_MUTED, justify="left", wraplength=880,
        ).pack(anchor="w", padx=14, pady=(12, 2))
        (self.practice_topics, self.practice_difficulty, self.practice_count,
         _, _) = self._session_config(self.practice_tab, include_timing=False)
        practice_actions = tk.Frame(self.practice_tab, bg=_BG)
        practice_actions.pack(fill="x", padx=14, pady=(2, 4))
        start_practice = tk.Button(
            practice_actions, text="START PRACTICE",
            command=lambda: self._start_session("practice"),
            bg=_ACCENT, fg="#07111d", relief="flat",
            font=("Consolas", 9, "bold"), padx=16, pady=8, cursor="hand2",
        )
        start_practice.pack(side="left")
        self._session_buttons.append(start_practice)
        self.practice_status = tk.Label(practice_actions, text="", bg=_BG, fg=_MUTED,
                                        anchor="w")
        self.practice_status.pack(side="left", padx=10)

        tk.Label(
            self.mock_tab,
            text=(
                "Full-length mock examination. The countdown starts as soon as the session "
                "opens and answers submit automatically when time runs out."
            ),
            bg=_BG, fg=_MUTED, justify="left", wraplength=880,
        ).pack(anchor="w", padx=14, pady=(12, 2))
        (self.mock_topics, self.mock_difficulty, self.mock_count,
         self.mock_duration, self.mock_target) = self._session_config(
            self.mock_tab, include_timing=True
        )
        mock_actions = tk.Frame(self.mock_tab, bg=_BG)
        mock_actions.pack(fill="x", padx=14, pady=(2, 4))
        start_mock = tk.Button(
            mock_actions, text="START MOCK EXAM",
            command=lambda: self._start_session("mock"),
            bg=_GREEN, fg="#07130a", relief="flat",
            font=("Consolas", 9, "bold"), padx=16, pady=8, cursor="hand2",
        )
        start_mock.pack(side="left")
        self._session_buttons.append(start_mock)
        self.mock_status = tk.Label(mock_actions, text="", bg=_BG, fg=_MUTED,
                                    anchor="w")
        self.mock_status.pack(side="left", padx=10)

        toolbar = tk.Frame(self.results_tab, bg=_BG)
        toolbar.pack(fill="x", padx=14, pady=(12, 6))
        tk.Button(toolbar, text="REFRESH", command=self._refresh_history,
                  bg=_PANEL, fg=_TEXT, relief="flat", font=("Consolas", 9, "bold"),
                  padx=12, pady=6, cursor="hand2").pack(side="left")
        tk.Button(toolbar, text="VIEW / RESUME SELECTED",
                  command=self._view_selected_session,
                  bg=_ACCENT, fg="#07111d", relief="flat",
                  font=("Consolas", 9, "bold"), padx=12, pady=6,
                  cursor="hand2").pack(side="left", padx=6)
        self.results_status = tk.Label(toolbar, text="", bg=_BG, fg=_MUTED)
        self.results_status.pack(side="left", padx=10)

        columns = ("session", "started", "mode", "status", "score", "accuracy", "review")
        self.session_tree = ttk.Treeview(
            self.results_tab, columns=columns, show="headings", selectmode="browse"
        )
        headings = {
            "session": "Session", "started": "Started", "mode": "Mode",
            "status": "Status", "score": "Score", "accuracy": "Accuracy",
            "review": "Needs review",
        }
        for column in columns:
            self.session_tree.heading(column, text=headings[column])
            self.session_tree.column(
                column, width=230 if column == "started" else 100,
                anchor="w" if column in {"started", "status"} else "center",
            )
        scroll = ttk.Scrollbar(self.results_tab, orient="vertical",
                               command=self.session_tree.yview)
        self.session_tree.configure(yscrollcommand=scroll.set)
        self.session_tree.pack(side="left", fill="both", expand=True,
                               padx=(14, 0), pady=(0, 14))
        scroll.pack(side="right", fill="y", pady=(0, 14), padx=(0, 14))

    def _build_analytics_tab(self) -> None:
        outer = tk.Frame(self.analytics_tab, bg=_BG)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=_BG, highlightthickness=0, bd=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        inner = tk.Frame(canvas, bg=_BG)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window_id, width=event.width),
        )

        toolbar = tk.Frame(inner, bg=_BG)
        toolbar.pack(fill="x", padx=14, pady=(10, 4))
        tk.Label(
            toolbar, text="PERFORMANCE ANALYTICS", bg=_BG, fg=_TEXT,
            font=("Consolas", 12, "bold"),
        ).pack(side="left")
        tk.Label(toolbar, text="Range", bg=_BG, fg=_MUTED).pack(
            side="left", padx=(16, 4)
        )
        self.analytics_range_combo = ttk.Combobox(
            toolbar, textvariable=self.analytics_range, state="readonly",
            width=13, values=exam_analytics.RANGE_OPTIONS,
        )
        self.analytics_range_combo.pack(side="left")
        self.analytics_range_combo.bind(
            "<<ComboboxSelected>>", self._analytics_range_changed
        )
        tk.Button(
            toolbar, text="REFRESH", command=self._refresh_analytics,
            bg=_PANEL, fg=_TEXT, relief="flat", font=("Consolas", 9, "bold"),
            padx=12, pady=5, cursor="hand2",
        ).pack(side="left", padx=8)
        self.analytics_status = tk.Label(
            toolbar, text="", bg=_BG, fg=_MUTED, anchor="w",
        )
        self.analytics_status.pack(side="left", fill="x", expand=True, padx=8)

        cards = tk.Frame(inner, bg=_BG)
        cards.pack(fill="x", padx=14, pady=(2, 6))
        self._analytics_card_values: dict[str, tuple[tk.Label, tk.Label]] = {}
        for key, title in (
            ("sessions", "SESSIONS"),
            ("accuracy", "ACCURACY"),
            ("attempted", "ATTEMPTED"),
            ("review", "NEEDS REVIEW"),
            ("trend", "TREND"),
        ):
            card = tk.Frame(cards, bg=_PANEL, padx=10, pady=6)
            card.pack(side="left", fill="x", expand=True, padx=(0, 6))
            tk.Label(
                card, text=title, bg=_PANEL, fg=_MUTED,
                font=("Consolas", 8, "bold"),
            ).pack(anchor="w")
            value = tk.Label(
                card, text="—", bg=_PANEL, fg=_TEXT,
                font=("Consolas", 13, "bold"),
            )
            value.pack(anchor="w")
            detail = tk.Label(
                card, text="", bg=_PANEL, fg=_MUTED,
                font=("Consolas", 7),
            )
            detail.pack(anchor="w")
            self._analytics_card_values[key] = (value, detail)

        content = tk.Frame(inner, bg=_BG)
        content.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)

        topic_frame = tk.LabelFrame(
            content, text="Topic accuracy and mastery", bg=_BG, fg=_TEXT,
            font=("Consolas", 9, "bold"), padx=6, pady=4,
        )
        topic_frame.grid(row=0, column=0, sticky="nsew", padx=4, pady=3)
        self.topic_chart = HorizontalBarChart(topic_frame, height=140, max_rows=8)
        self.topic_chart.pack(fill="x", padx=2, pady=(2, 4))
        table_wrap = tk.Frame(topic_frame, bg=_BG)
        table_wrap.pack(fill="both", expand=True)
        columns = (
            "topic", "graded", "unanswered", "accuracy", "recent", "marks",
            "mastery",
        )
        self.analytics_topic_tree = ttk.Treeview(
            table_wrap, columns=columns, show="headings", height=5,
            selectmode="browse",
        )
        headings = {
            "topic": "Topic", "graded": "Graded", "unanswered": "Skipped",
            "accuracy": "Accuracy", "recent": "Recent", "marks": "Marks",
            "mastery": "Mastery",
        }
        widths = {
            "topic": 170, "graded": 55, "unanswered": 62, "accuracy": 74,
            "recent": 100, "marks": 72, "mastery": 110,
        }
        for column in columns:
            self.analytics_topic_tree.heading(column, text=headings[column])
            self.analytics_topic_tree.column(
                column, width=widths[column],
                anchor="w" if column == "topic" else "center",
                stretch=column == "topic",
            )
        for tag, colour in (
            ("critical", _RED), ("weak", _RED), ("developing", _AMBER),
            ("strong", _GREEN), ("insufficient_data", _MUTED),
            ("not_started", _MUTED),
        ):
            self.analytics_topic_tree.tag_configure(tag, foreground=colour)
        tree_scroll = ttk.Scrollbar(
            table_wrap, orient="vertical",
            command=self.analytics_topic_tree.yview,
        )
        self.analytics_topic_tree.configure(yscrollcommand=tree_scroll.set)
        self.analytics_topic_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.analytics_topic_tree.bind("<<TreeviewSelect>>", self._on_topic_select)
        self.mastery_summary = tk.Label(
            topic_frame, text="", bg=_BG, fg=_MUTED, anchor="w",
            font=("Consolas", 8),
        )
        self.mastery_summary.pack(fill="x", padx=2, pady=(4, 3))
        self.mastery_detail = tk.Label(
            topic_frame, text="Select a topic to see its mastery evidence.",
            bg=_BG, fg=_MUTED, anchor="w", justify="left",
            wraplength=520, font=("Consolas", 8),
        )
        self.mastery_detail.pack(fill="x", padx=2, pady=(0, 2))

        trend_frame = tk.LabelFrame(
            content, text="Session trend", bg=_BG, fg=_TEXT,
            font=("Consolas", 9, "bold"), padx=6, pady=4,
        )
        trend_frame.grid(row=0, column=1, sticky="nsew", padx=4, pady=3)
        self.analytics_trend_label = tk.Label(
            trend_frame, text="Not enough history", bg=_BG, fg=_TEXT,
            anchor="w", font=("Consolas", 10, "bold"),
        )
        self.analytics_trend_label.pack(fill="x", padx=2, pady=(2, 0))
        self.analytics_trend_detail = tk.Label(
            trend_frame, text="", bg=_BG, fg=_MUTED, anchor="w",
            justify="left", wraplength=320, font=("Consolas", 8),
        )
        self.analytics_trend_detail.pack(fill="x", padx=2, pady=(0, 3))
        self.session_chart = SessionLineChart(trend_frame, height=185)
        self.session_chart.pack(fill="both", expand=True, padx=2, pady=(2, 2))
        self.session_chart.set_sessions([])

        type_frame = tk.LabelFrame(
            content, text="Question types", bg=_BG, fg=_TEXT,
            font=("Consolas", 9, "bold"), padx=6, pady=4,
        )
        type_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=3)
        self.type_chart = HorizontalBarChart(type_frame, height=95, max_rows=4)
        self.type_chart.pack(fill="x", padx=2, pady=(2, 2))
        self.type_hardest = tk.Label(
            type_frame, text="", bg=_BG, fg=_MUTED, anchor="w",
            font=("Consolas", 8),
        )
        self.type_hardest.pack(fill="x", padx=2, pady=(0, 2))

        bloom_frame = tk.LabelFrame(
            content, text="Bloom's Taxonomy levels", bg=_BG, fg=_TEXT,
            font=("Consolas", 9, "bold"), padx=6, pady=4,
        )
        bloom_frame.grid(row=1, column=1, sticky="nsew", padx=4, pady=3)
        self.bloom_chart = HorizontalBarChart(bloom_frame, height=95, max_rows=4)
        self.bloom_chart.pack(fill="x", padx=2, pady=(2, 2))
        self.bloom_hardest = tk.Label(
            bloom_frame, text="", bg=_BG, fg=_MUTED, anchor="w",
            font=("Consolas", 8),
        )
        self.bloom_hardest.pack(fill="x", padx=2, pady=(0, 2))

        recommendation_frame = tk.LabelFrame(
            content, text="Recommended next practice", bg=_BG, fg=_TEXT,
            font=("Consolas", 9, "bold"), padx=6, pady=4,
        )
        recommendation_frame.grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=4, pady=3
        )
        self.recommendation_container = tk.Frame(recommendation_frame, bg=_BG)
        self.recommendation_container.pack(fill="x", padx=2, pady=2)
        self.recommendation_note = tk.Label(
            recommendation_frame, text="", bg=_BG, fg=_MUTED, anchor="w",
            justify="left", wraplength=880, font=("Consolas", 8),
        )
        self.recommendation_note.pack(fill="x", padx=2, pady=(0, 2))

        self.analytics_notes = tk.Label(
            inner, text="", bg=_BG, fg=_MUTED, anchor="w", justify="left",
            wraplength=900, font=("Consolas", 8),
        )
        self.analytics_notes.pack(fill="x", padx=18, pady=(2, 10))

    def _session_config(self, parent: tk.Frame, include_timing: bool):
        body = tk.Frame(parent, bg=_BG)
        body.pack(fill="x", padx=14, pady=(8, 4))
        topics_frame = tk.Frame(body, bg=_BG)
        topics_frame.grid(row=0, column=0, rowspan=4, sticky="nsew", padx=(0, 20))
        tk.Label(topics_frame, text="Topics (select none for all)", bg=_BG,
                 fg=_MUTED).pack(anchor="w")
        list_frame = tk.Frame(topics_frame, bg=_BG)
        list_frame.pack(fill="both", expand=True)
        topics = tk.Listbox(
            list_frame, selectmode="extended", height=6, width=34,
            exportselection=False, bg="#0b0f14", fg=_TEXT,
            selectbackground=_ACCENT, selectforeground="#07111d", relief="flat",
        )
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=topics.yview)
        topics.configure(yscrollcommand=scroll.set)
        topics.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        tk.Label(body, text="Difficulty", bg=_BG, fg=_MUTED).grid(
            row=0, column=1, sticky="w", pady=2
        )
        difficulty = ttk.Combobox(
            body, state="readonly", width=12,
            values=("Any", *sorted(exam_engine.DIFFICULTIES)),
        )
        difficulty.set("Any")
        difficulty.grid(row=0, column=2, sticky="w", padx=6, pady=2)
        tk.Label(body, text="Questions", bg=_BG, fg=_MUTED).grid(
            row=1, column=1, sticky="w", pady=2
        )
        count = tk.Spinbox(body, from_=1, to=100, width=7)
        count.delete(0, "end")
        count.insert(0, "10")
        count.grid(row=1, column=2, sticky="w", padx=6, pady=2)

        duration = target = None
        if include_timing:
            tk.Label(body, text="Duration (min)", bg=_BG, fg=_MUTED).grid(
                row=2, column=1, sticky="w", pady=2
            )
            duration = tk.Spinbox(body, from_=1, to=600, width=7)
            duration.delete(0, "end")
            duration.insert(0, "180")
            duration.grid(row=2, column=2, sticky="w", padx=6, pady=2)
            tk.Label(body, text="Target marks (0 = all)", bg=_BG, fg=_MUTED).grid(
                row=3, column=1, sticky="w", pady=2
            )
            target = tk.Spinbox(body, from_=0, to=10000, width=7)
            target.delete(0, "end")
            target.insert(0, "0")
            target.grid(row=3, column=2, sticky="w", padx=6, pady=2)
        body.columnconfigure(0, weight=1)
        return topics, difficulty, count, duration, target

    @staticmethod
    def _selected_topics(listbox: tk.Listbox) -> list[str]:
        return [listbox.get(index) for index in listbox.curselection()]

    def _refresh_topic_filters(self) -> None:
        topics: list[str] = []
        seen: set[str] = set()
        for unit in self.units:
            for topic in unit.get("topics", []):
                name = str(topic).strip()
                if name and name.casefold() not in seen:
                    seen.add(name.casefold())
                    topics.append(name)
        for listbox in (self.practice_topics, self.mock_topics):
            selected = set(self._selected_topics(listbox))
            listbox.delete(0, "end")
            for topic in topics:
                listbox.insert("end", topic)
            for index, topic in enumerate(topics):
                if topic in selected:
                    listbox.selection_set(index)

    def _start_session(
        self,
        mode: str,
        topics_override: list[str] | None = None,
        count_override: int | None = None,
        difficulty_override: str | None = None,
    ) -> bool:
        if self._closing:
            return False
        if self._runner is not None:
            messagebox.showinfo("Exam session",
                                "Finish or submit the active session first.",
                                parent=self.window)
            return False
        workspace = self._require_approved()
        if workspace is None:
            return False
        if self.workspace_id is None:
            return False
        status = self.practice_status if mode == "practice" else self.mock_status
        listbox = self.practice_topics if mode == "practice" else self.mock_topics
        difficulty_combo = (
            self.practice_difficulty if mode == "practice" else self.mock_difficulty
        )
        count_field = self.practice_count if mode == "practice" else self.mock_count
        try:
            count = (
                int(count_field.get())
                if count_override is None else int(count_override)
            )
            topics = (
                self._selected_topics(listbox)
                if topics_override is None else list(topics_override)
            )
            difficulty = (
                difficulty_combo.get()
                if difficulty_override is None else difficulty_override
            )
            duration = int(self.mock_duration.get()) if mode == "mock" else 0
            target = int(self.mock_target.get()) if mode == "mock" else 0
            target_marks = target if target > 0 else None
            for button in self._session_buttons + self._analytics_buttons:
                button.configure(state="disabled")
            status.configure(text="Preparing the session…", fg=_MUTED)
            created = exam_engine.create_session(
                self.store, self.student_id, self.workspace_id, mode,
                count=count, topics=topics, difficulty=difficulty,
                duration_minutes=duration, target_marks=target_marks,
            )
        except (ValueError, exam_engine.ExamError, StoreError) as exc:
            status.configure(text=str(exc), fg=_RED)
            for button in self._session_buttons + self._analytics_buttons:
                button.configure(state="normal")
            return False
        try:
            self._start_runner(
                created["session"], created["responses"], workspace.get("subject", ""),
                created.get("notice", ""), status,
            )
        except Exception as exc:
            try:
                exam_engine.abandon_session(
                    self.store, self.student_id, created["session"]["session_id"]
                )
            except Exception:
                pass
            self._runner = None
            status.configure(text=str(exc), fg=_RED)
            for button in self._session_buttons + self._analytics_buttons:
                button.configure(state="normal")
            return False
        return True

    def _start_runner(self, session: dict, responses: list[dict], subject: str,
                      notice: str, status: tk.Label) -> None:
        from .exam_runner import ExamRunnerWindow

        runner = ExamRunnerWindow(
            self.window, self.store, self.student_id, session, responses,
            subject=subject, notice=notice, on_finish=self._runner_finished,
        )
        if runner.submitted:
            # An expired mock can submit itself during construction.
            self._runner = None
            return
        self._runner = runner
        session_label = "Practice" if session.get("mode") == "practice" else "Mock exam"
        status.configure(
            text=f"{session_label} session started · {len(responses)} question(s).",
            fg=_GREEN,
        )

    def _runner_finished(self, result: dict | None) -> None:
        self._runner = None
        for button in self._session_buttons + self._analytics_buttons:
            try:
                button.configure(state="normal")
            except tk.TclError:
                pass
        self._refresh_history()
        self._refresh_analytics()
        if result is not None:
            self.notebook.select(self.results_tab)
            self._open_result(result)
        else:
            self._restore_grab()

    def _open_result(self, result: dict) -> None:
        from .exam_runner import ExamResultWindow

        window = ExamResultWindow(self.window, result)
        self._result_windows.append(window)
        window.on_close = lambda: self._forget_result(window)

    def _forget_result(self, window) -> None:
        if window in self._result_windows:
            self._result_windows.remove(window)
        self._restore_grab()

    def _restore_grab(self) -> None:
        if self._closing:
            return
        try:
            self.window.grab_set()
            self.window.lift()
        except tk.TclError:
            pass

    def _refresh_history(self) -> None:
        if self._closing or not hasattr(self, "session_tree"):
            return
        self.session_tree.delete(*self.session_tree.get_children())
        self._session_items = {}
        if self.workspace_id is None:
            self.results_status.configure(text="Create or select a workspace.", fg=_MUTED)
            return
        try:
            rows = self.store.list_exam_sessions(self.student_id, self.workspace_id)
        except StoreError as exc:
            self.results_status.configure(text=str(exc), fg=_RED)
            return
        for row in rows:
            total = int(row.get("total_marks") or 0)
            score = float(row.get("score_marks") or 0)
            percentage = f"{score / total * 100:.0f}%" if total else "-"
            started = row.get("started_at")
            if hasattr(started, "strftime"):
                started_text = started.strftime("%Y-%m-%d %H:%M")
            else:
                started_text = str(started or "")[:16].replace("T", " ")
            iid = self.session_tree.insert("", "end", values=(
                row.get("session_id"), started_text, row.get("mode"),
                str(row.get("status", "")).replace("_", " "),
                f"{score:g}/{total}", percentage, row.get("needs_review", 0),
            ))
            self._session_items[iid] = int(row["session_id"])
        self.results_status.configure(
            text=f"{len(rows)} session(s) for this workspace.", fg=_MUTED
        )

    def _on_tab_changed(self, _event=None) -> None:
        if self._closing:
            return
        try:
            selected = self.notebook.select()
        except tk.TclError:
            return
        if selected == str(self.analytics_tab):
            self._refresh_analytics()

    def _analytics_range_changed(self, _event=None) -> None:
        self._refresh_analytics()

    def _refresh_analytics(self) -> None:
        if self._closing or not hasattr(self, "analytics_topic_tree"):
            return
        range_label = self.analytics_range.get() or "All Time"
        if self.workspace_id is None:
            dashboard = exam_analytics.build_dashboard(
                [], [], "", range_label
            )
            self._render_analytics(dashboard)
            self.analytics_status.configure(
                text="Create or select a workspace.", fg=_MUTED
            )
            return
        subject = (self.workspace or {}).get("subject", "")
        syllabus_topics = [
            str(topic)
            for unit in self.units
            for topic in unit.get("topics", [])
            if str(topic).strip()
        ]
        try:
            records = self.store.list_exam_analytics_records(
                self.student_id, self.workspace_id
            )
        except StoreError as exc:
            self.analytics_status.configure(text=str(exc), fg=_RED)
            return
        dashboard = exam_analytics.build_dashboard(
            records, syllabus_topics, subject, range_label
        )
        self._render_analytics(dashboard)

    def _render_analytics(self, dashboard: dict) -> None:
        has_data = dashboard["has_data"]
        self.analytics_status.configure(
            text=(
                f"{dashboard['subject'] or 'Workspace'} · "
                f"{dashboard['range_label']} · "
                f"{dashboard['session_count']} submitted session(s)"
            ),
            fg=_GREEN if has_data else _MUTED,
        )

        accuracy = dashboard["accuracy"]
        sufficient_overall = (
            accuracy is not None
            and dashboard["graded_answers"] >= exam_analytics.MIN_TOPIC_GRADED
        )
        self._set_card(
            "sessions", str(dashboard["session_count"]),
            f"{dashboard['practice_sessions']} practice · "
            f"{dashboard['mock_sessions']} mock",
        )
        self._set_card(
            "accuracy",
            exam_analytics.format_percent(accuracy) if sufficient_overall else "—",
            (
                f"{dashboard['graded_answers']} graded answer(s)"
                if sufficient_overall else
                f"{dashboard['graded_answers']} graded; "
                f"{exam_analytics.MIN_TOPIC_GRADED} needed to judge"
            ),
        )
        self._set_card(
            "attempted", str(dashboard["questions_attempted"]),
            f"of {dashboard['questions_total']} question(s)",
        )
        self._set_card(
            "review", str(dashboard["needs_review"]), "awaiting manual review",
        )
        trend = dashboard["trend"]
        self._set_card(
            "trend", trend["label"],
            f"{trend['delta']:+.0f} points" if trend["delta"] is not None else "",
        )

        trend_colors = {
            "improving": _GREEN, "declining": _RED, "steady": _AMBER,
            "insufficient_data": _MUTED,
        }
        self.analytics_trend_label.configure(
            text=trend["label"],
            fg=trend_colors.get(trend["status"], _TEXT),
        )
        self.analytics_trend_detail.configure(text=trend["evidence"])
        self.session_chart.set_sessions(dashboard["sessions"])

        topic_rows = [
            {
                "label": topic["topic"],
                "value": (
                    topic["accuracy"]
                    if topic["graded"] >= exam_analytics.MIN_TOPIC_GRADED
                    else None
                ),
                "color_key": topic["mastery"],
            }
            for topic in dashboard["topics"]
            if topic["attempted"] > 0
        ]
        self.topic_chart.set_rows(
            topic_rows,
            empty_text="No graded topic data in this range.",
        )

        self.analytics_topic_tree.delete(*self.analytics_topic_tree.get_children())
        self._topic_rows = {}
        for topic in dashboard["topics"]:
            recent = (
                f"{exam_analytics.format_percent(topic['recent_accuracy'])} "
                f"({topic['recent_graded']})"
                if topic["recent_accuracy"] is not None else "—"
            )
            accuracy_text = (
                exam_analytics.format_percent(topic["accuracy"])
                if topic["accuracy"] is not None else "—"
            )
            if (
                topic["accuracy"] is not None
                and topic["graded"] < exam_analytics.MIN_TOPIC_GRADED
            ):
                accuracy_text = f"{accuracy_text}*"
            iid = self.analytics_topic_tree.insert(
                "", "end",
                values=(
                    topic["topic"], topic["graded"], topic["unanswered"],
                    accuracy_text, recent,
                    f"{topic['marks_awarded']:g}/{topic['marks_total']:g}",
                    topic["mastery"],
                ),
                tags=(topic["status"],),
            )
            self._topic_rows[iid] = topic
        self.mastery_detail.configure(
            text="Select a topic to see its mastery evidence."
        )

        counts = {name: 0 for name in (
            exam_analytics.MASTERY_NOT_STARTED,
            exam_analytics.MASTERY_LEARNING,
            exam_analytics.MASTERY_NEEDS_IMPROVEMENT,
            exam_analytics.MASTERY_MASTERED,
        )}
        for topic in dashboard["topics"]:
            counts[topic["mastery"]] = counts.get(topic["mastery"], 0) + 1
        self.mastery_summary.configure(
            text=" · ".join(f"{name}: {count}" for name, count in counts.items())
        )

        type_rows = [
            {
                "label": entry["name"],
                "value": (
                    entry["accuracy"]
                    if entry["graded"] >= exam_analytics.MIN_TYPE_GRADED
                    else None
                ),
                "color_key": entry["status"],
            }
            for entry in dashboard["question_types"]
        ]
        bloom_rows = [
            {
                "label": entry["name"],
                "value": (
                    entry["accuracy"]
                    if entry["graded"] >= exam_analytics.MIN_TYPE_GRADED
                    else None
                ),
                "color_key": entry["status"],
            }
            for entry in dashboard["bloom_levels"]
        ]
        self.type_chart.set_rows(
            type_rows, empty_text="No auto-graded question types yet."
        )
        self.bloom_chart.set_rows(
            bloom_rows, empty_text="No Bloom level data yet."
        )
        hardest_type = dashboard["hardest_question_type"]
        hardest_bloom = dashboard["hardest_bloom_level"]
        self.type_hardest.configure(
            text=(
                f"Hardest with enough evidence: {hardest_type['name']} "
                f"({exam_analytics.format_percent(hardest_type['accuracy'])})"
                if hardest_type else
                "Need at least 2 question types with 3+ graded answers."
            )
        )
        self.bloom_hardest.configure(
            text=(
                f"Hardest with enough evidence: {hardest_bloom['name']} "
                f"({exam_analytics.format_percent(hardest_bloom['accuracy'])})"
                if hardest_bloom else
                "Need at least 2 Bloom levels with 3+ graded answers."
            )
        )

        self._render_recommendations(dashboard)
        self.analytics_notes.configure(
            text="\n".join(dashboard["notes"])
        )

    def _set_card(self, key: str, value: str, detail: str) -> None:
        labels = self._analytics_card_values.get(key)
        if labels is None:
            return
        labels[0].configure(text=value)
        labels[1].configure(text=detail)

    def _clear_recommendations(self) -> None:
        self._analytics_buttons = []
        for child in self.recommendation_container.winfo_children():
            child.destroy()

    def _render_recommendations(self, dashboard: dict) -> None:
        self._clear_recommendations()
        recommendations = dashboard["recommendations"]
        for recommendation in recommendations:
            row = tk.Frame(self.recommendation_container, bg=_BG)
            row.pack(fill="x", pady=1)
            button = tk.Button(
                row, text="PRACTICE THIS TOPIC",
                command=lambda topic=recommendation["topic"]:
                    self._start_topic_practice(topic),
                bg=_ACCENT, fg="#07111d", relief="flat",
                font=("Consolas", 8, "bold"), padx=10, pady=3,
                cursor="hand2",
            )
            button.pack(side="right", padx=(8, 0))
            self._analytics_buttons.append(button)
            tk.Label(
                row,
                text=(
                    f"{recommendation['priority_label']} · "
                    f"{recommendation['topic']} — {recommendation['reason']}"
                ),
                bg=_BG, fg=_TEXT if recommendation["priority"] <= 2 else _AMBER,
                anchor="w", justify="left", wraplength=690,
                font=("Consolas", 8),
            ).pack(side="left", fill="x", expand=True)

        evidence = dashboard["evidence_needed"]
        if recommendations:
            note = (
                "Recommendations use only topics with at least "
                f"{exam_analytics.MIN_TOPIC_GRADED} graded answers."
            )
        elif not dashboard["has_data"]:
            note = (
                "No submitted sessions in this range. Complete a practice or "
                "mock exam; nothing is estimated."
            )
        else:
            note = (
                "No topic currently has enough evidence for a weakness "
                "recommendation."
            )
        if evidence:
            preview = ", ".join(
                f"{item['topic']} ({item['graded']}/"
                f"{exam_analytics.MIN_TOPIC_GRADED})"
                for item in evidence[:6]
            )
            suffix = "…" if len(evidence) > 6 else ""
            note += f" Evidence needed: {preview}{suffix}."
        self.recommendation_note.configure(text=note)

    def _on_topic_select(self, _event=None) -> None:
        selection = self.analytics_topic_tree.selection()
        if not selection:
            return
        topic = self._topic_rows.get(selection[0])
        if topic is None:
            return
        colours = {
            exam_analytics.MASTERY_MASTERED: _GREEN,
            exam_analytics.MASTERY_LEARNING: _ACCENT,
            exam_analytics.MASTERY_NEEDS_IMPROVEMENT: _RED,
            exam_analytics.MASTERY_NOT_STARTED: _MUTED,
        }
        self.mastery_detail.configure(
            text=f"{topic['mastery']} · {topic['mastery_evidence']}",
            fg=colours.get(topic["mastery"], _MUTED),
        )

    def _start_topic_practice(self, topic: str) -> None:
        if self._closing:
            return
        self.analytics_status.configure(
            text=f"Preparing practice on {topic}…", fg=_MUTED
        )
        started = self._start_session(
            "practice",
            topics_override=[topic],
            count_override=10,
            difficulty_override="Any",
        )
        if started:
            self.analytics_status.configure(
                text=f"Practice started for {topic}.", fg=_GREEN
            )
        else:
            self.analytics_status.configure(
                text=f"Could not start practice for {topic}.", fg=_AMBER
            )

    def _view_selected_session(self) -> None:
        selected = self.session_tree.selection()
        if not selected:
            self.results_status.configure(text="Select a session first.", fg=_AMBER)
            return
        session_id = self._session_items.get(selected[0])
        if session_id is None:
            return
        try:
            session = self.store.get_exam_session(self.student_id, session_id)
            if session is None:
                self.results_status.configure(text="That session no longer exists.", fg=_RED)
                return
            if session["status"] == "in_progress":
                if self._runner is not None:
                    messagebox.showinfo("Exam session",
                                        "Finish or submit the active session first.",
                                        parent=self.window)
                    return
                workspace = (
                    self.workspace
                    if self.workspace and self.workspace_id == session["workspace_id"]
                    else self.store.get_exam_workspace(
                        self.student_id, int(session["workspace_id"])
                    )
                )
                responses = self.store.list_exam_responses(self.student_id, session_id)
                status = (
                    self.practice_status if session["mode"] == "practice"
                    else self.mock_status
                )
                try:
                    self._start_runner(
                        session, responses,
                        (workspace or {}).get("subject", ""), "", status,
                    )
                except Exception as exc:
                    self._runner = None
                    status.configure(text=str(exc), fg=_RED)
                return
            result = exam_engine.session_result(self.store, self.student_id, session_id)
        except (exam_engine.ExamError, StoreError) as exc:
            self.results_status.configure(text=str(exc), fg=_RED)
            return
        self._open_result(result)

    def _entry(self, parent, label: str, row: int, column: int, default: str) -> tk.Entry:
        tk.Label(parent, text=label, bg=_BG, fg=_MUTED).grid(row=row, column=column, sticky="w", padx=4, pady=3)
        entry = tk.Entry(parent, width=22)
        entry.insert(0, default)
        entry.grid(row=row, column=column + 1, sticky="ew", padx=4, pady=3)
        parent.columnconfigure(column + 1, weight=1)
        return entry

    def _create_workspace(self) -> None:
        if not self._confirm_discard_content(
            "Creating and switching to a new workspace"
        ):
            return
        try:
            workspace_id = self.store.create_exam_workspace(
                self.student_id, self.subject_entry.get(), self.level_entry.get(),
                self.date_entry.get(), int(self.marks_entry.get()), int(self.duration_entry.get()),
            )
            self._refresh_workspaces(workspace_id)
        except (ValueError, StoreError) as exc:
            messagebox.showerror("Exam Preparation", str(exc), parent=self.window)

    def _refresh_workspaces(self, select_id: int | None = None) -> None:
        try:
            rows = self.store.list_exam_workspaces(self.student_id)
        except StoreError as exc:
            self.document_status.configure(text=str(exc), fg=_RED)
            return
        self._workspace_items = {}
        labels = []
        for row in rows:
            label = f"{row['workspace_id']} | {row['subject']} ({row['exam_date'] or 'date not set'})"
            labels.append(label)
            self._workspace_items[label] = int(row["workspace_id"])
        self.workspace_combo["values"] = labels
        if select_id is not None:
            match = next((label for label, value in self._workspace_items.items() if value == select_id), "")
            self.workspace_combo.set(match)
            if match:
                self._load_workspace(select_id)
        elif labels and self.workspace_id is None:
            self.workspace_combo.current(0)
            self._load_workspace(self._workspace_items[labels[0]])
        elif not labels and self.workspace_id is None:
            self._refresh_topic_filters()
            self._refresh_history()
            self._refresh_analytics()

    def _choose_workspace(self, _event=None) -> None:
        workspace_id = self._workspace_items.get(self.workspace_combo.get())
        if workspace_id is None:
            return
        if workspace_id != self.workspace_id and not self._confirm_discard_content(
            "Switching workspace"
        ):
            current = next(
                (
                    label for label, value in self._workspace_items.items()
                    if value == self.workspace_id
                ),
                "",
            )
            self.workspace_combo.set(current)
            return
        self._load_workspace(workspace_id)

    def _load_workspace(self, workspace_id: int, preserve_generation: bool = False) -> None:
        try:
            workspace = self.store.get_exam_workspace(self.student_id, workspace_id)
        except StoreError as exc:
            messagebox.showerror("Exam Preparation", str(exc), parent=self.window)
            return
        if workspace is None:
            return
        self.workspace_id, self.workspace = workspace_id, workspace
        self.units = [
            {
                "title": str(unit.get("title", "")),
                "topics": [str(topic) for topic in unit.get("topics", [])],
            }
            for unit in workspace["topics"]
            if isinstance(unit, dict)
        ]
        self._render_topics()
        file_label = workspace["syllabus_filename"] or "manual outline"
        status = "APPROVED" if workspace["syllabus_approved"] else "Needs review"
        self.document_status.configure(text=f"{workspace['subject']} · {file_label} · {status}", fg=_GREEN if workspace["syllabus_approved"] else _MUTED)
        if preserve_generation:
            self._update_generation_statuses(workspace)
        else:
            self._populate_generation_fields(workspace)
        self._update_progress()
        self._refresh_topic_filters()
        if self.mock_duration is not None:
            self.mock_duration.delete(0, "end")
            self.mock_duration.insert(0, str(workspace.get("duration_minutes") or 180))
        self._refresh_history()
        self._refresh_analytics()

    def _populate_generation_fields(self, workspace: dict) -> None:
        notes = workspace.get("notes") or {}
        self.notes_text.delete("1.0", "end")
        if isinstance(notes, dict):
            self.note_style.set(notes.get("style", "standard"))
            self.notes_text.insert("1.0", notes.get("text", ""))
        else:
            self.note_style.set("standard")
        questions = workspace.get("questions") or []
        self.questions_text.delete("1.0", "end")
        self.questions_text.insert("1.0", json.dumps(questions, ensure_ascii=False, indent=2))
        self._update_generation_statuses(workspace)

    def _update_generation_statuses(self, workspace: dict) -> None:
        approved = bool(workspace.get("syllabus_approved"))
        note_status = "Syllabus approved. Generate grounded notes or edit this area." if approved else "Review and approve a syllabus first."
        question_status = "Syllabus approved. Generate a validated question bank." if approved else "Review and approve a syllabus first."
        self.notes_status.configure(text=note_status, fg=_GREEN if approved else _MUTED)
        self.questions_status.configure(text=question_status, fg=_GREEN if approved else _MUTED)

    def _saved_notes_text(self) -> str:
        notes = (self.workspace or {}).get("notes")
        return str(notes.get("text", "")) if isinstance(notes, dict) else str(notes or "")

    def _saved_questions_text(self) -> str:
        questions = (self.workspace or {}).get("questions") or []
        return json.dumps(questions, ensure_ascii=False, indent=2)

    def _has_unsaved_content(self) -> bool:
        if self.workspace_id is None or self.workspace is None:
            return False
        notes_changed = (
            self.notes_text.get("1.0", "end-1c").strip()
            != self._saved_notes_text().strip()
        )
        questions_changed = (
            self.questions_text.get("1.0", "end-1c").strip()
            != self._saved_questions_text().strip()
        )
        return notes_changed or questions_changed

    def _confirm_discard_content(self, action: str) -> bool:
        if not self._has_unsaved_content():
            return True
        return messagebox.askyesno(
            "Unsaved edits",
            f"You have unsaved revision-note or question-bank edits. {action} "
            "will discard them. Continue?",
            parent=self.window,
        )

    def _confirm_generation(self, kind: str, label: str) -> bool:
        if not self._confirm_discard_content(f"Generating new {label}"):
            return False
        existing = (self.workspace or {}).get(kind)
        has_existing = (
            bool(existing.get("text"))
            if kind == "notes" and isinstance(existing, dict)
            else bool(existing)
        )
        if not has_existing:
            return True
        return messagebox.askyesno(
            "Replace existing content",
            f"Generating will replace the existing {label} in this workspace. Continue?",
            parent=self.window,
        )

    def _require_approved(self) -> dict | None:
        if self.workspace_id is None:
            messagebox.showinfo("Exam Preparation", "Create or select a workspace first.", parent=self.window)
            return None
        try:
            workspace = self.store.get_exam_workspace(self.student_id, self.workspace_id)
        except StoreError as exc:
            messagebox.showerror("Exam Preparation", str(exc), parent=self.window)
            return None
        if not workspace or not workspace.get("syllabus_approved"):
            messagebox.showinfo("Exam Preparation", "Review and approve the syllabus first.", parent=self.window)
            return None
        return workspace

    def _generate_notes(self) -> None:
        workspace = self._require_approved()
        if workspace is None:
            return
        if not self._confirm_generation("notes", "revision notes"):
            return
        style = self.note_style.get()
        self._set_busy(True, "Generating source-grounded notes…")
        threading.Thread(target=self._generation_worker, args=("notes", workspace, style),
                         name="codelock-notes", daemon=True).start()

    def _generate_questions(self) -> None:
        workspace = self._require_approved()
        if workspace is None:
            return
        if not self._confirm_generation("questions", "question bank"):
            return
        try:
            count = int(self.question_count.get())
        except ValueError:
            messagebox.showerror("Question Bank", "Question count must be an integer.", parent=self.window)
            return
        options = (count, self.question_difficulty.get(), self.question_type.get())
        self._set_busy(True, "Generating and validating questions…")
        threading.Thread(target=self._generation_worker, args=("questions", workspace, options),
                         name="codelock-question-bank", daemon=True).start()

    def _generation_worker(self, kind: str, workspace: dict, options) -> None:
        from .ai import AIError, AIProvider
        from .study_generation import (
            generate_local_notes,
            generate_local_question_bank,
            generate_notes,
            generate_question_bank,
        )

        meta = {"generator": "local", "provider": "", "ai_error": ""}
        try:
            if self._closing:
                return
            try:
                provider = AIProvider.from_environment()
            except AIError:
                provider = None

            def run_ai():
                if kind == "notes":
                    return generate_notes(
                        provider, workspace["subject"], workspace["syllabus_filename"],
                        workspace["source_text"], workspace["topics"], options,
                    )
                count, difficulty, question_type = options
                return generate_question_bank(
                    provider, workspace["subject"], workspace["syllabus_filename"],
                    workspace["source_text"], workspace["topics"], count,
                    difficulty, question_type, workspace.get("questions", []),
                )

            def run_local():
                if kind == "notes":
                    return generate_local_notes(
                        workspace["subject"], workspace["syllabus_filename"],
                        workspace["source_text"], workspace["topics"], options,
                    )
                count, difficulty, question_type = options
                return generate_local_question_bank(
                    workspace["subject"], workspace["syllabus_filename"],
                    workspace["source_text"], workspace["topics"], count,
                    difficulty, question_type, workspace.get("questions", []),
                )

            content = None
            if provider is not None:
                try:
                    content = run_ai()
                    meta["generator"] = "ai"
                    meta["provider"] = provider.provider
                except AIError as exc:
                    meta["ai_error"] = str(exc)
            if content is None:
                content = run_local()
            if self._closing:
                return
            if not self.store.save_exam_content(self.student_id, workspace["workspace_id"], kind, content):
                raise StoreError("Syllabus approval changed before the content could be saved.")
            self._events.put(("generated", kind, workspace["workspace_id"], content, None, meta))
        except Exception as exc:
            self._events.put(("generated", kind, workspace["workspace_id"], None, str(exc), meta))

    def _save_notes_edits(self) -> None:
        workspace = self._require_approved()
        if workspace is None:
            return
        content = {"style": self.note_style.get(), "text": self.notes_text.get("1.0", "end-1c").strip()}
        if not content["text"]:
            messagebox.showerror("Revision Notes", "Notes cannot be empty.", parent=self.window)
            return
        saved_notes = workspace.get("notes")
        if isinstance(saved_notes, dict):
            content["items"] = saved_notes.get("items", [])
        try:
            saved = self.store.save_exam_content(self.student_id, self.workspace_id, "notes", content)
            if saved:
                self.notes_status.configure(text="Notes saved.", fg=_GREEN)
            else:
                self.notes_status.configure(text="Syllabus is no longer approved; review it before saving.", fg=_RED)
        except StoreError as exc:
            messagebox.showerror("Revision Notes", str(exc), parent=self.window)

    def _save_question_edits(self) -> None:
        workspace = self._require_approved()
        if workspace is None:
            return
        try:
            questions = json.loads(self.questions_text.get("1.0", "end-1c"))
            from .study_generation import validate_questions

            validated = validate_questions(
                questions, workspace["topics"], source_text=workspace["source_text"]
            )
            if not validated:
                raise ValueError(
                    "The question bank is empty. Add at least one validated question "
                    "or generate a new bank; nothing was saved."
                )
            if self.store.save_exam_content(self.student_id, self.workspace_id, "questions", validated):
                self.questions_status.configure(text=f"Saved {len(validated)} validated questions.", fg=_GREEN)
            else:
                self.questions_status.configure(text="Syllabus is no longer approved; review it before saving.", fg=_RED)
        except Exception as exc:
            messagebox.showerror("Question Bank", str(exc), parent=self.window)

    def _has_generated_content(self) -> bool:
        workspace = self.workspace or {}
        notes = workspace.get("notes")
        has_notes = bool(notes.get("text")) if isinstance(notes, dict) else bool(notes)
        return (
            bool(workspace.get("syllabus_approved"))
            or bool(workspace.get("questions"))
            or has_notes
        )

    @staticmethod
    def _canonical_outline(units: list[dict]) -> list[tuple[str, tuple[str, ...]]]:
        return [
            (
                str(unit.get("title", "")).strip(),
                tuple(str(topic).strip() for topic in unit.get("topics", []) or []),
            )
            for unit in units
            if isinstance(unit, dict)
        ]

    def _choose_file(self) -> None:
        if self.workspace_id is None:
            messagebox.showinfo("Exam Preparation", "Create or select a workspace first.", parent=self.window)
            return
        path = filedialog.askopenfilename(
            parent=self.window,
            filetypes=UPLOAD_FILETYPES,
        )
        if not path:
            return
        if self._has_generated_content() and not messagebox.askyesno(
            "Replace syllabus",
            "Uploading a new syllabus clears the approved outline, revision notes and "
            "question bank for this workspace. Continue?",
            parent=self.window,
        ):
            return
        workspace_id = self.workspace_id
        self._set_busy(True, "Extracting document text…")
        threading.Thread(target=self._extract_worker, args=(path, workspace_id), name="codelock-syllabus", daemon=True).start()

    def _extract_worker(self, path: str, workspace_id: int) -> None:
        try:
            document = extract_document(path)
            topics = extract_topics(document.text)
            self._events.put(("extracted", workspace_id, document, topics, None))
        except Exception as exc:
            self._events.put(("extracted", workspace_id, None, None, str(exc)))

    def _drain_events(self) -> None:
        if self._closing:
            return
        try:
            while True:
                event = self._events.get_nowait()
                if event[0] == "extracted":
                    _, target_workspace_id, document, topics, error = event
                    self._set_busy(False)
                    if error:
                        self.document_status.configure(text=error, fg=_RED)
                        continue
                    assert document is not None and topics is not None
                    try:
                        saved = self.store.save_syllabus(
                            self.student_id, target_workspace_id,
                            document.filename, document.text, topics,
                        )
                    except StoreError as exc:
                        self.document_status.configure(text=str(exc), fg=_RED)
                        continue
                    if not saved:
                        self.document_status.configure(
                            text="That workspace no longer exists.",
                            fg=_RED,
                        )
                        continue
                    if self.workspace_id != target_workspace_id:
                        continue
                    self._load_workspace(target_workspace_id)
                    if document.scanned_suspected:
                        self.document_status.configure(
                            text=f"{document.filename}: little selectable text found; this may be a scan. OCR is not configured.", fg="#d29922"
                        )
                    else:
                        self.document_status.configure(text=f"Extracted {len(document.text):,} characters from {document.filename}. Review and edit before approval.", fg=_ACCENT)
                elif event[0] == "generated":
                    _, kind, target_workspace_id, content, error, meta = event
                    self._set_busy(False)
                    if error:
                        status = self.notes_status if kind == "notes" else self.questions_status
                        status.configure(text=error, fg=_RED)
                        messagebox.showerror("Study Generation", error, parent=self.window)
                        continue
                    assert content is not None
                    workspace = self.store.get_exam_workspace(self.student_id, target_workspace_id)
                    if self.workspace_id != target_workspace_id:
                        continue
                    if workspace:
                        self.workspace = workspace
                        generator = (meta or {}).get("generator", "local")
                        ai_error = (meta or {}).get("ai_error", "")
                        if kind == "notes":
                            self.notes_text.delete("1.0", "end")
                            self.notes_text.insert("1.0", content.get("text", ""))
                            if generator == "ai":
                                text = f"AI-generated and saved {len(content.get('items', []))} topic notes. You can edit and save them."
                                color = _GREEN
                            elif ai_error:
                                text = f"AI failed; generated {len(content.get('items', []))} topic notes offline and saved them."
                                color = _AMBER
                            else:
                                text = f"Generated {len(content.get('items', []))} topic notes offline from your source and saved them."
                                color = _GREEN
                            self.notes_status.configure(text=text, fg=color)
                        else:
                            self.questions_text.delete("1.0", "end")
                            self.questions_text.insert("1.0", json.dumps(content, ensure_ascii=False, indent=2))
                            if generator == "ai":
                                text = f"AI-generated and saved {len(content)} questions. Review or edit the JSON and save."
                                color = _GREEN
                            elif ai_error:
                                text = f"AI failed; generated {len(content)} questions offline and saved them."
                                color = _AMBER
                            else:
                                text = f"Generated {len(content)} questions offline from your source and saved them."
                                color = _GREEN
                            self.questions_status.configure(text=text, fg=color)
        except queue.Empty:
            pass
        except Exception as exc:
            try:
                self.document_status.configure(text=f"Workflow error: {exc}", fg=_RED)
            except tk.TclError:
                pass
        if self.window.winfo_exists():
            self.window.after(80, self._drain_events)

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        self.upload_btn.configure(state="disabled" if busy else "normal")
        self.workspace_combo.configure(state="disabled" if busy else "readonly")
        self.create_workspace_btn.configure(state="disabled" if busy else "normal")
        for button in self.outline_buttons:
            button.configure(state="disabled" if busy else "normal")
        for button in (getattr(self, "generate_notes_btn", None), getattr(self, "save_notes_btn", None),
                       getattr(self, "generate_questions_btn", None), getattr(self, "save_questions_btn", None)):
            if button is not None:
                button.configure(state="disabled" if busy else "normal")
        for button in self._session_buttons + self._analytics_buttons:
            try:
                button.configure(state="disabled" if busy else "normal")
            except tk.TclError:
                pass
        if text:
            self.document_status.configure(text=text, fg=_MUTED)

    def _render_topics(self) -> None:
        self.topic_tree.delete(*self.topic_tree.get_children())
        for unit_index, unit in enumerate(self.units):
            unit_id = f"u{unit_index}"
            self.topic_tree.insert("", "end", iid=unit_id, text=unit["title"], values=("Unit",), open=True)
            for topic_index, topic in enumerate(unit.get("topics", [])):
                self.topic_tree.insert(unit_id, "end", iid=f"{unit_id}t{topic_index}", text=topic, values=("Topic",))
        self._update_progress()
        if hasattr(self, "practice_topics"):
            try:
                self._refresh_topic_filters()
            except tk.TclError:
                pass

    def _update_progress(self) -> None:
        topic_count = sum(len(unit.get("topics", [])) for unit in self.units)
        self.progress_label.configure(text=f"{len(self.units)} units · {topic_count} topics")

    def _add_unit(self) -> None:
        title = simpledialog.askstring("Add unit", "Unit title:", parent=self.window)
        if title and title.strip():
            self.units.append({"title": title.strip(), "topics": []})
            self._render_topics()

    def _add_topic(self) -> None:
        if not self.units:
            self.units.append({"title": "Unit 1", "topics": []})
        selected = self.topic_tree.selection()
        unit_index = 0
        if selected:
            item = selected[0]
            unit_id = item.split("t", 1)[0] if "t" in item else item
            if unit_id.startswith("u"):
                unit_index = int(unit_id[1:])
        topic = simpledialog.askstring("Add topic", "Topic or subtopic title:", parent=self.window)
        if topic and topic.strip():
            self.units[unit_index]["topics"].append(topic.strip())
            self._render_topics()

    def _rename_selected(self) -> None:
        selected = self.topic_tree.selection()
        if not selected:
            messagebox.showinfo(
                "Syllabus", "Select a unit or topic to rename.", parent=self.window
            )
            return
        item = selected[0]
        current = self.topic_tree.item(item, "text")
        renamed = simpledialog.askstring("Rename", "Updated title:", initialvalue=current, parent=self.window)
        if not renamed or not renamed.strip():
            return
        if "t" in item:
            unit_id, topic_index = item.split("t", 1)
            self.units[int(unit_id[1:])]["topics"][int(topic_index)] = renamed.strip()
        else:
            self.units[int(item[1:])]["title"] = renamed.strip()
        self._render_topics()

    def _remove_selected(self) -> None:
        selected = self.topic_tree.selection()
        if not selected:
            messagebox.showinfo(
                "Syllabus", "Select a unit or topic to remove.", parent=self.window
            )
            return
        item = selected[0]
        if "t" in item:
            unit_id, topic_index = item.split("t", 1)
            del self.units[int(unit_id[1:])]["topics"][int(topic_index)]
        else:
            del self.units[int(item[1:])]
        self._render_topics()

    def _persist_outline(self) -> bool:
        if self.workspace_id is None:
            messagebox.showinfo("Exam Preparation", "Create a workspace first.", parent=self.window)
            return False
        self._outline_cleared_content = False
        try:
            # Drafts may have units without topics; approval re-validates below.
            units = validate_topic_tree(self.units, require_topics=False)
            current_outline = (self.workspace or {}).get("topics", [])
            if (
                self._has_generated_content()
                and self._canonical_outline(units)
                != self._canonical_outline(current_outline)
                and not messagebox.askyesno(
                    "Change syllabus outline",
                    "Changing the unit/topic outline clears the approved status, revision "
                    "notes and question bank for this workspace. Continue?",
                    parent=self.window,
                )
            ):
                return False
            source = self.workspace.get("source_text", "") if self.workspace else ""
            filename = self.workspace.get("syllabus_filename", "") if self.workspace else ""
            if not source:
                source = "Manual syllabus outline\n" + "\n".join(
                    f"{unit['title']}\n" + "\n".join(unit["topics"]) for unit in units
                )
            previous = self.workspace or {}
            had_content = bool(previous.get("syllabus_approved")) or bool(
                previous.get("questions")
            ) or bool(self._saved_notes_text().strip())
            if not self.store.save_syllabus(
                self.student_id, self.workspace_id, filename, source, units
            ):
                messagebox.showerror(
                    "Exam Preparation",
                    "That workspace no longer exists. Select another workspace.",
                    parent=self.window,
                )
                return False
            self.units = units
            self.workspace = self.store.get_exam_workspace(self.student_id, self.workspace_id)
            self._outline_cleared_content = had_content and not bool(
                (self.workspace or {}).get("syllabus_approved")
            )
            return True
        except (DocumentError, StoreError) as exc:
            messagebox.showerror("Exam Preparation", str(exc), parent=self.window)
            return False

    def _save_draft(self) -> None:
        if not self._persist_outline():
            return
        self._load_workspace(
            self.workspace_id,
            preserve_generation=not self._outline_cleared_content,
        )
        self.document_status.configure(
            text="Syllabus draft saved. Review and approve it to enable generation.",
            fg=_ACCENT,
        )

    def _approve(self) -> None:
        if not self._persist_outline():
            return
        try:
            approved = self.store.approve_syllabus(self.student_id, self.workspace_id, self.units)
        except StoreError as exc:
            messagebox.showerror("Exam Preparation", str(exc), parent=self.window)
            return
        if not approved:
            messagebox.showerror("Exam Preparation", "Upload a syllabus or add manual topics before approval.", parent=self.window)
            return
        self._load_workspace(
            self.workspace_id,
            preserve_generation=not self._outline_cleared_content,
        )
        messagebox.showinfo("Exam Preparation", "Syllabus approved. Notes and question generation are now enabled.", parent=self.window)

    def _show_generation_status(self, _event=None) -> None:
        if not self.workspace or not self.workspace.get("syllabus_approved"):
            messagebox.showinfo("Exam Preparation", "Review and approve the syllabus first.", parent=self.window)

    def close(self) -> None:
        if self._closing:
            return
        if self._runner is not None:
            messagebox.showinfo(
                "Exam Preparation",
                "Finish or submit the active exam session before closing this workspace.",
                parent=self.window,
            )
            try:
                self._runner.window.lift()
                self._runner.window.focus_force()
            except tk.TclError:
                pass
            return
        self._closing = True
        for window in list(self._result_windows):
            window.force_close()
        self._result_windows.clear()
        try:
            self.window.grab_release()
            self.window.destroy()
            if self.on_close:
                self.on_close()
        except tk.TclError:
            pass

    def shutdown(self) -> None:
        """Force-close the workspace and any child session windows."""
        if self._closing:
            return
        self._closing = True
        if self._runner is not None:
            self._runner.force_close()
            self._runner = None
        for window in list(self._result_windows):
            window.force_close()
        self._result_windows.clear()
        try:
            self.window.grab_release()
            self.window.destroy()
        except tk.TclError:
            pass
