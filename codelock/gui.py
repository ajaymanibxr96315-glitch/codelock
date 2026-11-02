"""Kiosk GUI: always-on-top window, anti-paste editor and the reward cycle."""

from __future__ import annotations

import ctypes
import hmac
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Callable

from . import config
from .db import Progress, Student, StudentStore, StoreError
from .hosts_elevation import (
    STATUS_BLOCKED,
    STATUS_DAMAGED,
    STATUS_PARTIAL,
    STATUS_UNBLOCKED,
    STATUS_UNKNOWN,
    WEBSITE_ACCESS_NOTE,
    HostsAuthority,
    clear_recovery_file,
    recovery_file_path,
    restore_command,
    write_recovery_file,
)
from .judge import Judge, JudgeResult
from .pc_blocker import ProcessKiller, is_admin
from .problems import ENGINEERING, PROBLEMS, Problem, Track
from .ui_common import enable_fullscreen

COLORS = {
    "bg": "#0d1117",
    "panel": "#161b22",
    "panel_alt": "#21262d",
    "border": "#30363d",
    "text": "#e6edf3",
    "muted": "#8b949e",
    "accent": "#58a6ff",
    "green": "#3fb950",
    "green_dark": "#14532d",
    "red": "#b62324",
    "red_dark": "#7f1d1d",
    "amber": "#d29922",
    "editor": "#0b0f14",
    "white": "#ffffff",
}

HOSTS_DISPLAY = {
    STATUS_BLOCKED: ("BLOCKED", COLORS["green"]),
    STATUS_PARTIAL: ("PARTIAL", COLORS["amber"]),
    STATUS_DAMAGED: ("DAMAGED", COLORS["amber"]),
    STATUS_UNBLOCKED: ("NOT BLOCKED", COLORS["red"]),
    "missing": ("NOT BLOCKED", COLORS["red"]),
    STATUS_UNKNOWN: ("STATUS UNKNOWN", COLORS["amber"]),
}


class CodeLockApp:
    def __init__(self, root: tk.Tk, dry_run: bool = False) -> None:
        self.root = root
        self.dry_run = dry_run

        self.hosts_control = HostsAuthority(hosts_path=config.HOSTS_PATH)
        self._startup_block_present: bool | None = None
        self._startup_status = ""
        self._startup_hosts_error = ""
        self._startup_verification = None
        self._last_recovery_path = None
        self._last_unlock_status = ""
        if not dry_run:
            # Read-only: never elevate or rewrite hosts during startup.
            startup_state = self.hosts_control.state()
            self._startup_status = startup_state.status
            self._startup_hosts_error = startup_state.error
            self._startup_block_present = (
                None
                if startup_state.error
                else startup_state.status == STATUS_BLOCKED
            )
            self._startup_verification = self.hosts_control.verify_installation()
        self.killer = ProcessKiller()
        self.judge = Judge()
        self.store = StudentStore()

        self.locked = True
        self.judging = False
        self.reward_deadline = 0.0
        self.track: Track | None = None
        self.problems: tuple[Problem, ...] = ()
        self.problem_index = 0
        self.problem: Problem = PROBLEMS[0]
        self.student: Student | None = None
        self.progress: Progress | None = None
        self._challenge_started = 0.0
        self._login_dialog: tk.Toplevel | None = None
        self._picker: tk.Toplevel | None = None
        self._exam_window = None

        self._events: queue.Queue[tuple[Callable, tuple, dict]] = queue.Queue()
        self._stop_event = threading.Event()
        self._enforce_lock = threading.Lock()
        self._shutting_down = False
        self._hosts_error_logged = False
        self._header_bg_widgets: list[tk.Widget] = []

        self._configure_window()
        self._configure_scrollbars()
        self._build_ui()
        self._bind_shortcuts()
        self._show_setup_placeholder()
        self._set_controls_enabled(False)
        self._log_startup()

        self.root.after(80, self._drain_events)
        self.root.after(200, lambda: self._set_close_enabled(self.track is None or not self.locked))
        self.root.after(1200, self._tick_kiosk)
        self.root.after(150, self._show_login)

    # ================================================================ window
    def _configure_window(self) -> None:
        self.root.title("CodeLock - PC Distraction Blocker")
        self.root.configure(bg=COLORS["bg"])
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = max(820, min(1000, screen_w - 120))
        height = max(620, min(780, screen_h - 120))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2 - 20)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(820, 620)
        enable_fullscreen(self.root)
        # Setup dialogs remain usable before a study session starts.
        self.root.attributes("-topmost", False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self.root.bind("<Configure>", self._on_resize)

    def _configure_scrollbars(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "CodeLock.Vertical.TScrollbar",
            background=COLORS["panel_alt"],
            troughcolor=COLORS["bg"],
            bordercolor=COLORS["border"],
            arrowcolor=COLORS["muted"],
            relief="flat",
            borderwidth=0,
        )

    def _set_close_enabled(self, enabled: bool) -> None:
        """Grey out / restore the title-bar X on Windows (WM_DELETE is also trapped)."""
        if os.name != "nt" or self.dry_run:
            return
        try:
            hwnd = int(self.root.wm_frame(), 16)
            menu = ctypes.windll.user32.GetSystemMenu(hwnd, False)
            if not menu:
                return
            flags = 0x00000000 if enabled else 0x00000001  # MF_ENABLED / MF_GRAYED
            ctypes.windll.user32.EnableMenuItem(menu, 0xF060, flags)  # SC_CLOSE
            ctypes.windll.user32.DrawMenuBar(hwnd)
        except Exception:
            pass

    def _on_resize(self, event: tk.Event) -> None:
        if event.widget is self.root and hasattr(self, "problem_desc"):
            wrap = max(480, event.width - 100)
            self.problem_desc.configure(wraplength=wrap)
            self.problem_examples.configure(wraplength=wrap)

    # ==================================================================== UI
    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=COLORS["red"])
        header.pack(fill="x")
        header_inner = tk.Frame(header, bg=COLORS["red"], padx=18, pady=12)
        header_inner.pack(fill="x")
        title_block = tk.Frame(header_inner, bg=COLORS["red"])
        title_block.pack(side="left")
        self.header_title = tk.Label(
            title_block,
            text="CodeLock",
            font=("Consolas", 19, "bold"),
            fg="white",
            bg=COLORS["red"],
        )
        self.header_title.pack(anchor="w")
        self.header_sub = tk.Label(
            title_block,
            text="PC DISTRACTION BLOCKER",
            font=("Consolas", 8, "bold"),
            fg="#ffd7d5",
            bg=COLORS["red"],
        )
        self.header_sub.pack(anchor="w")
        self.header_status = tk.Label(
            header_inner,
            text="LOCKED",
            font=("Consolas", 10, "bold"),
            fg="white",
            bg=COLORS["red_dark"],
            padx=14,
            pady=6,
        )
        self.header_status.pack(side="right")
        self._header_bg_widgets = [header, header_inner, title_block, self.header_title, self.header_sub]

        telemetry = tk.Frame(self.root, bg=COLORS["bg"])
        telemetry.pack(fill="x", padx=16, pady=(12, 0))
        self.hosts_badge = self._badge(telemetry, "HOSTS FILE", "checking...")
        self.killer_badge = self._badge(telemetry, "APP KILLER", "starting...")
        self.track_badge = self._badge(telemetry, "TRACK", "not chosen")
        self.student_badge = self._badge(telemetry, "STUDENT", "not signed in")
        self.admin_badge = self._badge(
            telemetry, "ADMIN", "yes" if is_admin() else "no"
        )
        self.admin_badge.configure(fg=COLORS["green"] if is_admin() else COLORS["amber"])
        self.timer_badge = self._badge(telemetry, "REWARD", "--:--")
        self.hosts_retry_button = self._button(
            telemetry,
            "RETRY BLOCK",
            self._retry_block,
            COLORS["amber"],
            COLORS["bg"],
            bold=True,
        )

        card = tk.Frame(
            self.root,
            bg=COLORS["panel"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        card.pack(fill="x", padx=16, pady=(12, 10))
        card_inner = tk.Frame(card, bg=COLORS["panel"], padx=16, pady=12)
        card_inner.pack(fill="x")
        card_top = tk.Frame(card_inner, bg=COLORS["panel"])
        card_top.pack(fill="x")
        self.problem_title = tk.Label(
            card_top,
            text="",
            font=("Consolas", 12, "bold"),
            fg=COLORS["text"],
            bg=COLORS["panel"],
        )
        self.problem_title.pack(side="left")
        self.challenge_count = tk.Label(
            card_top,
            text="",
            font=("Consolas", 9, "bold"),
            fg=COLORS["muted"],
            bg=COLORS["panel"],
        )
        self.challenge_count.pack(side="right")
        self.problem_desc = tk.Label(
            card_inner,
            text="",
            font=("Consolas", 10),
            fg="#c9d1d9",
            bg=COLORS["panel"],
            justify="left",
            anchor="w",
            wraplength=860,
        )
        self.problem_desc.pack(fill="x", pady=(8, 4))
        self.problem_examples = tk.Label(
            card_inner,
            text="",
            font=("Consolas", 9),
            fg=COLORS["accent"],
            bg=COLORS["panel"],
            justify="left",
            anchor="w",
            wraplength=860,
        )
        self.problem_examples.pack(fill="x")

        editor_head = tk.Frame(self.root, bg=COLORS["bg"])
        editor_head.pack(fill="x", padx=16)
        tk.Label(
            editor_head,
            text="SOLUTION",
            font=("Consolas", 9, "bold"),
            fg=COLORS["muted"],
            bg=COLORS["bg"],
        ).pack(side="left")
        tk.Label(
            editor_head,
            text="paste disabled  |  TAB = 4 spaces",
            font=("Consolas", 9),
            fg=COLORS["muted"],
            bg=COLORS["bg"],
        ).pack(side="right")
        editor_frame, self.editor = self._scrolled_text(
            self.root, height=8, font=("Consolas", 11), fg="#c9d1d9", editable=True
        )
        editor_frame.pack(fill="both", expand=True, padx=16, pady=(6, 8))

        console_head = tk.Frame(self.root, bg=COLORS["bg"])
        console_head.pack(fill="x", padx=16)
        tk.Label(
            console_head,
            text="JUDGE OUTPUT",
            font=("Consolas", 9, "bold"),
            fg=COLORS["muted"],
            bg=COLORS["bg"],
        ).pack(side="left")
        self.judge_state_label = tk.Label(
            console_head,
            text="AWAITING SUBMISSION",
            font=("Consolas", 9, "bold"),
            fg=COLORS["muted"],
            bg=COLORS["bg"],
        )
        self.judge_state_label.pack(side="right")
        console_frame, self.console = self._scrolled_text(
            self.root, height=5, font=("Consolas", 9), fg="#9da7b3", editable=False
        )
        console_frame.pack(fill="x", padx=16, pady=(6, 8))

        footer = tk.Frame(self.root, bg=COLORS["bg"])
        footer.pack(fill="x", padx=16, pady=(0, 12))
        if self.dry_run:
            self.dry_exit_btn = self._button(
                footer,
                "EXIT DRY RUN",
                self._shutdown,
                COLORS["red_dark"],
                "#ffd7d5",
            )
            self.dry_exit_btn.pack(side="left", padx=(0, 8))
        else:
            self.emergency_exit_btn = self._button(
                footer,
                "EMERGENCY EXIT",
                self._emergency_exit,
                COLORS["red_dark"],
                "#ffd7d5",
            )
            self.emergency_exit_btn.pack(side="left", padx=(0, 8))
        self.sample_btn = self._button(
            footer, "RUN SAMPLES", self._run_samples, COLORS["panel_alt"], COLORS["text"]
        )
        self.sample_btn.pack(side="left", padx=(0, 8))
        self.submit_btn = self._button(
            footer,
            "SUBMIT & UNLOCK PC",
            self._submit,
            COLORS["green"],
            "#04120a",
            bold=True,
        )
        self.submit_btn.pack(side="right")
        if self.dry_run:
            self.header_status.configure(text="DRY RUN")
            self.header_sub.configure(text="TEST MODE - NOTHING IS BLOCKED")

    # ============================================================ student login
    def _show_login(self) -> None:
        if self._shutting_down or self.student is not None:
            return

        dialog = tk.Toplevel(self.root)
        self._login_dialog = dialog
        dialog.title("CodeLock - Student sign in")
        dialog.configure(bg=COLORS["bg"])
        dialog.attributes("-topmost", True)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.protocol("WM_DELETE_WINDOW", self._on_login_close)
        dialog.bind("<Control-Alt-Shift-q>", self._emergency_exit)
        dialog.bind("<Control-Alt-Shift-Q>", self._emergency_exit)
        dialog.bind("<Return>", lambda _event: self._submit_login(create=False))
        if self.dry_run:
            dialog.bind("<Escape>", lambda _event: self._shutdown())

        body = tk.Frame(dialog, bg=COLORS["bg"], padx=24, pady=20)
        body.pack(fill="both", expand=True)
        tk.Label(
            body,
            text="Student sign in",
            font=("Consolas", 16, "bold"),
            fg=COLORS["text"],
            bg=COLORS["bg"],
        ).pack(anchor="w")
        tk.Label(
            body,
            text=(
                "Create an account or sign in. CodeLock stores your attempts, "
                "completion time and DSA progress, and keeps your exam workspaces."
            ),
            font=("Consolas", 10),
            fg=COLORS["muted"],
            bg=COLORS["bg"],
            justify="left",
            wraplength=460,
        ).pack(anchor="w", pady=(4, 16))

        form = tk.Frame(body, bg=COLORS["bg"])
        form.pack(fill="x")
        self.username_entry = self._form_entry(form, 0, "Username")
        self.display_entry = self._form_entry(form, 1, "Display name (optional)")
        self.password_entry = self._form_entry(form, 2, "Password", show="*")
        form.columnconfigure(1, weight=1)

        status_text = f"Progress store: {self.store.backend_name}"
        status_color = COLORS["muted"]
        if self.store.backend_warning:
            status_text += "\n" + self.store.backend_warning
            status_color = COLORS["amber"]
        self.login_status = tk.Label(
            body,
            text=status_text,
            font=("Consolas", 8),
            fg=status_color,
            bg=COLORS["bg"],
            justify="left",
            anchor="w",
            wraplength=460,
        )
        self.login_status.pack(fill="x", pady=(12, 10))

        buttons = tk.Frame(body, bg=COLORS["bg"])
        buttons.pack(fill="x")
        self._button(
            buttons,
            "LOG IN",
            lambda: self._submit_login(create=False),
            COLORS["panel_alt"],
            COLORS["text"],
        ).pack(side="left")
        self._button(
            buttons,
            "CREATE ACCOUNT",
            lambda: self._submit_login(create=True),
            COLORS["green"],
            "#04120a",
            bold=True,
        ).pack(side="left", padx=(8, 0))

        footer = (
            "Esc exits dry run."
            if self.dry_run
            else "Sign in to choose Exam Preparation or DSA Practice."
        )
        tk.Label(
            body,
            text=footer,
            font=("Consolas", 8),
            fg=COLORS["muted"],
            bg=COLORS["bg"],
        ).pack(anchor="w", pady=(14, 0))

        self.username_entry.focus_set()
        width, height = 520, 390
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
        try:
            dialog.grab_set()
        except tk.TclError:
            pass
        dialog.lift()
        dialog.focus_force()

    def _form_entry(
        self, parent: tk.Widget, row: int, label: str, show: str | None = None
    ) -> tk.Entry:
        tk.Label(
            parent,
            text=label,
            font=("Consolas", 9, "bold"),
            fg=COLORS["muted"],
            bg=COLORS["bg"],
        ).grid(row=row, column=0, sticky="w", pady=6)
        entry = tk.Entry(
            parent,
            font=("Consolas", 11),
            bg=COLORS["editor"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
        )
        if show:
            entry.configure(show=show)
        entry.grid(row=row, column=1, sticky="ew", padx=(12, 0), pady=6, ipady=4)
        return entry

    def _on_login_close(self) -> None:
        if self._shutting_down:
            return
        if self.dry_run:
            self._shutdown()
            return
        self._log("Sign in to start the session.", "warn")
        if self._login_dialog is not None:
            self._login_dialog.lift()

    def _submit_login(self, create: bool) -> None:
        if self._shutting_down:
            return
        username = self.username_entry.get().strip()
        display_name = self.display_entry.get().strip()
        password = self.password_entry.get()
        try:
            if create:
                student = self.store.register(username, display_name, password)
            else:
                student = self.store.login(username, password)
        except StoreError as exc:
            self.login_status.configure(text=str(exc), fg=COLORS["red"])
            return

        self.student = student
        self.student_badge.configure(
            text=student.display_name[:16], fg=COLORS["green"]
        )
        self._log(f"Signed in as {student.display_name} (@{student.username}).", "ok")
        if create:
            self._log("Student account created. Progress starts at challenge 1.", "info")

        dialog, self._login_dialog = self._login_dialog, None
        if dialog is not None:
            try:
                dialog.grab_release()
                dialog.destroy()
            except tk.TclError:
                pass
        self._show_mode_picker()

    def _active_modal(self) -> tk.Toplevel | None:
        return self._login_dialog or self._picker

    # =========================================================== study mode
    def _show_mode_picker(self) -> None:
        if self._shutting_down or self.student is None or self.track is not None:
            return
        if not self.dry_run:
            self.header_sub.configure(text="CHOOSE HOW TO STUDY")

        picker = tk.Toplevel(self.root)
        self._picker = picker
        picker.title("CodeLock - Choose how to study")
        picker.configure(bg=COLORS["bg"])
        picker.attributes("-topmost", True)
        picker.transient(self.root)
        picker.resizable(False, False)
        picker.protocol("WM_DELETE_WINDOW", self._on_picker_close)
        picker.bind("<Control-Alt-Shift-q>", self._emergency_exit)
        picker.bind("<Control-Alt-Shift-Q>", self._emergency_exit)
        if self.dry_run:
            picker.bind("<Escape>", lambda _event: self._shutdown())

        body = tk.Frame(picker, bg=COLORS["bg"], padx=22, pady=18)
        body.pack(fill="both", expand=True)
        tk.Label(
            body,
            text="How do you want to study?",
            font=("Consolas", 16, "bold"),
            fg=COLORS["text"],
            bg=COLORS["bg"],
        ).pack(anchor="w")
        tk.Label(
            body,
            text=(
                "DSA Practice starts an Engineering coding session and locks the PC "
                "until you solve the challenge. Exam Preparation opens your exam "
                "workspace without locking the PC."
            ),
            font=("Consolas", 10),
            fg=COLORS["muted"],
            bg=COLORS["bg"],
            justify="left",
            wraplength=600,
        ).pack(anchor="w", pady=(4, 14))

        self._mode_button(
            body,
            "1. DSA PRACTICE",
            "Block the PC and start practice.",
            "Solve the challenge to unlock.",
            lambda: self._select_track(ENGINEERING),
            COLORS["red"],
            COLORS["white"],
        ).pack(fill="x", pady=(0, 10))
        self._mode_button(
            body,
            "2. EXAM PREPARATION",
            "Start your exam journey.",
            "Your PC stays unlocked.",
            self._open_exam_preparation,
            COLORS["green"],
            "#04120a",
        ).pack(fill="x")

        footer_text = "Choose one of the two modes to continue."
        if self.dry_run:
            footer_text += "  Press Esc to exit dry run."
        tk.Label(
            body,
            text=footer_text,
            font=("Consolas", 8),
            fg=COLORS["muted"],
            bg=COLORS["bg"],
        ).pack(anchor="w", pady=(12, 0))

        width, height = 660, 430
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        picker.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
        try:
            picker.grab_set()
        except tk.TclError:
            pass
        picker.lift()
        picker.focus_force()

    def _mode_button(
        self,
        parent: tk.Widget,
        title: str,
        description: str,
        note: str,
        command: Callable,
        bg: str,
        fg: str,
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=f"{title}\n{description}\n{note}",
            command=command,
            bg=bg,
            fg=fg,
            activebackground=COLORS["panel_alt"],
            activeforeground=COLORS["text"],
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
            font=("Consolas", 11, "bold"),
            justify="left",
            anchor="w",
            padx=18,
            pady=14,
            cursor="hand2",
            height=4,
        )

    def _open_exam_preparation(self) -> None:
        if self.student is None or self._shutting_down:
            return
        if self._exam_window is not None:
            try:
                if self._exam_window.window.winfo_exists():
                    self._exam_window.window.lift()
                    self._exam_window.window.focus_force()
                    return
            except tk.TclError:
                pass
            self._exam_window = None
        picker = self._picker
        if picker is not None:
            try:
                picker.grab_release()
                picker.withdraw()
            except tk.TclError:
                pass
        try:
            from .exam_ui import ExamPreparationWindow

            self._exam_window = ExamPreparationWindow(
                self.root, self.store, self.student.id,
                on_close=self._exam_closed,
            )
        except Exception as exc:
            self._exam_window = None
            self._restore_picker_grab()
            messagebox.showerror("Exam Preparation", str(exc), parent=self.root)

    def _exam_closed(self) -> None:
        self._exam_window = None
        self._shutdown()

    def _restore_picker_grab(self) -> None:
        if self._picker is None:
            return
        try:
            self._picker.deiconify()
            self._picker.grab_set()
            self._picker.lift()
        except tk.TclError:
            pass

    def _on_picker_close(self) -> None:
        if self._shutting_down:
            return
        self._log("Choose Exam Preparation or DSA Practice to continue.", "warn")
        if self._picker is not None:
            try:
                self._picker.lift()
                self._picker.focus_force()
            except tk.TclError:
                pass

    def _select_track(self, track: Track) -> None:
        if self._shutting_down or self.track is not None or self.student is None:
            return
        self.track = track
        self.problems = track.problems()
        self.progress = self._load_progress(track.key)
        start_index = self.progress.current_index
        if not 0 <= start_index < len(self.problems):
            start_index = 0
        self.track_badge.configure(text=track.title, fg=COLORS["accent"])

        picker, self._picker = self._picker, None
        if picker is not None:
            try:
                picker.grab_release()
                picker.destroy()
            except tk.TclError:
                pass

        self._load_problem(start_index, reset_editor=True)
        self.root.attributes("-topmost", True)
        self._set_close_enabled(False)
        self._set_controls_enabled(True)
        self._set_header(
            COLORS["red"],
            COLORS["red_dark"],
            "DRY RUN" if self.dry_run else "LOCKED",
            "TEST MODE - NOTHING IS BLOCKED" if self.dry_run else "PC DISTRACTION BLOCKER",
            "#ffd7d5",
        )
        self._log(
            f"Track: {track.title} ({track.tagline}) - "
            f"{len(self.problems)} challenges queued.",
            "ok",
        )
        if self.progress.attempts:
            best = (
                f"{self.progress.best_seconds:.1f}s"
                if self.progress.best_seconds is not None
                else "-"
            )
            self._log(
                f"Your progress on {track.title}: {self.progress.completed} solved, "
                f"{self.progress.attempts} attempts, best {best}. "
                f"Resuming at challenge {start_index + 1}.",
                "info",
            )
        self._log(
            "Write a solution to the coding challenge, then submit to unlock your PC.",
            "info",
        )
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

        if not self.dry_run:
            self._watchdog = threading.Thread(
                target=self._watchdog_loop, name="codelock-watchdog", daemon=True
            )
            self._watchdog.start()

    def _load_progress(self, track_key: str) -> Progress:
        if self.student is None:
            return Progress(track_key)
        try:
            return self.store.get_progress(self.student.id, track_key)
        except StoreError as exc:
            self._log(f"Could not load saved progress: {exc}", "warn")
            return Progress(track_key)

    def _badge(self, parent: tk.Widget, title: str, value: str) -> tk.Label:
        frame = tk.Frame(
            parent,
            bg=COLORS["panel"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        frame.pack(side="left", padx=(0, 8))
        tk.Label(
            frame,
            text=title,
            font=("Consolas", 8, "bold"),
            fg=COLORS["muted"],
            bg=COLORS["panel"],
            padx=10,
            pady=3,
        ).pack(anchor="w")
        value_label = tk.Label(
            frame,
            text=value,
            font=("Consolas", 9, "bold"),
            fg=COLORS["text"],
            bg=COLORS["panel"],
            padx=10,
            pady=2,
        )
        value_label.pack(anchor="w")
        return value_label

    def _button(
        self,
        parent: tk.Widget,
        text: str,
        command: Callable,
        bg: str,
        fg: str,
        bold: bool = False,
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=COLORS["border"],
            activeforeground=COLORS["text"],
            disabledforeground=COLORS["muted"],
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=("Consolas", 10, "bold" if bold else "normal"),
            padx=16,
            pady=10,
            cursor="hand2",
        )

    def _scrolled_text(
        self,
        parent: tk.Widget,
        height: int,
        font: tuple,
        fg: str,
        editable: bool,
    ) -> tuple[tk.Frame, tk.Text]:
        frame = tk.Frame(
            parent,
            bg=COLORS["editor"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        text = tk.Text(
            frame,
            height=height,
            font=font,
            fg=fg,
            bg=COLORS["editor"],
            insertbackground=COLORS["text"],
            insertwidth=2,
            selectbackground="#264f78",
            selectforeground=COLORS["white"],
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=10,
            wrap="none",
            undo=editable,
        )
        scroll = ttk.Scrollbar(
            frame,
            orient="vertical",
            command=text.yview,
            style="CodeLock.Vertical.TScrollbar",
        )
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        if not editable:
            text.configure(state="disabled")
        return frame, text

    # ============================================================== shortcuts
    def _bind_shortcuts(self) -> None:
        for sequence in (
            "<<Paste>>",
            "<<PasteSelection>>",
            "<Control-v>",
            "<Control-V>",
            "<Control-Shift-v>",
            "<Control-Shift-V>",
            "<Shift-Insert>",
            "<Button-2>",
            "<Button-3>",
        ):
            self.editor.bind(sequence, self._block_paste)
        self.editor.bind("<Tab>", self._insert_tab)
        self.root.bind("<Control-Alt-Shift-q>", self._emergency_exit)
        self.root.bind("<Control-Alt-Shift-Q>", self._emergency_exit)
        if self.dry_run:
            # Fullscreen hides the title-bar X; Esc still ends a test run.
            self.root.bind("<Escape>", lambda _event: self._shutdown())

    def _block_paste(self, _event: tk.Event | None = None) -> str:
        self._log("Paste is disabled inside the CodeLock editor.", "warn")
        return "break"

    def _insert_tab(self, _event: tk.Event | None = None) -> str:
        self.editor.insert("insert", "    ")
        return "break"

    # ================================================================== events
    def _ui(self, callback: Callable, *args, **kwargs) -> None:
        self._events.put((callback, args, kwargs))

    def _drain_events(self) -> None:
        if self._shutting_down:
            return
        try:
            while True:
                callback, args, kwargs = self._events.get_nowait()
                try:
                    callback(*args, **kwargs)
                except tk.TclError:
                    pass
        except queue.Empty:
            pass
        self.root.after(80, self._drain_events)

    def _log(self, message: str, level: str = "info") -> None:
        prefix = {"info": "", "ok": "[OK] ", "warn": "[WARN] ", "err": "[FAIL] "}.get(level, "")
        stamp = time.strftime("%H:%M:%S")
        lines = str(message).splitlines() or [""]
        try:
            self.console.configure(state="normal")
            self.console.insert("end", f"{stamp}  {prefix}{lines[0]}\n")
            for line in lines[1:]:
                self.console.insert("end", f"          {line}\n")
            total = int(self.console.index("end-1c").split(".")[0])
            if total > 700:
                self.console.delete("1.0", f"{total - 500}.0")
            self.console.see("end")
            self.console.configure(state="disabled")
        except tk.TclError:
            pass

    # ============================================================== telemetry
    def _hosts_display(self, key: str) -> tuple[str, str]:
        return HOSTS_DISPLAY.get(key, HOSTS_DISPLAY[STATUS_UNKNOWN])

    def _set_hosts_status(self, text: str, color: str) -> None:
        self.hosts_badge.configure(text=text, fg=color)

    def _set_killer_status(self, text: str, color: str) -> None:
        self.killer_badge.configure(text=text, fg=color)

    def _set_header(
        self, bg: str, status_bg: str, status_text: str, sub_text: str, sub_fg: str
    ) -> None:
        for widget in self._header_bg_widgets:
            widget.configure(bg=bg)
        self.header_status.configure(bg=status_bg, text=status_text)
        self.header_sub.configure(text=sub_text, fg=sub_fg)

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.sample_btn.configure(state=state)
        self.submit_btn.configure(
            state=state,
            bg=COLORS["green"] if enabled else COLORS["panel_alt"],
            fg="#04120a" if enabled else COLORS["muted"],
        )

    # =============================================================== problems
    def _show_setup_placeholder(self) -> None:
        if not self.dry_run:
            self._set_header(
                COLORS["red"],
                COLORS["amber"],
                "SETUP",
                "SIGN IN TO START",
                "#ffd7d5",
            )
        self.problem_title.configure(text="Sign in to begin")
        self.challenge_count.configure(text="CHALLENGE - / -")
        self.problem_desc.configure(
            text=(
                "Sign in with a student account, then choose Exam Preparation or "
                "DSA Practice. DSA starts an Engineering session and locks your PC; "
                "Exam Preparation keeps your PC unlocked."
            )
        )
        self.problem_examples.configure(text="")

    def _load_problem(self, index: int, reset_editor: bool) -> None:
        if not self.problems:
            return
        self.problem_index = index % len(self.problems)
        self.problem = self.problems[self.problem_index]
        self.problem_title.configure(
            text=f"{self.problem.title}  [{self.problem.difficulty}]"
        )
        self.challenge_count.configure(
            text=f"CHALLENGE {self.problem_index + 1} / {len(self.problems)}"
        )
        self.problem_desc.configure(text=self.problem.description)
        rendered = "    ".join(
            f"{self.problem.function_name}({', '.join(repr(arg) for arg in args)})"
            f" -> {expected!r}"
            for args, expected in self.problem.examples
        )
        self.problem_examples.configure(text="Examples:  " + rendered)
        if reset_editor:
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", self.problem.starter)
            self.editor.edit_reset()
            self._challenge_started = time.monotonic()

    def _advance_problem(self) -> None:
        self._load_problem(self.problem_index + 1, reset_editor=True)
        self._log(f"Next challenge loaded: {self.problem.title}.", "info")

    # ================================================================ checker
    def _run_samples(self) -> None:
        self._start_judge(include_hidden=False)

    def _submit(self) -> None:
        self._start_judge(include_hidden=True)

    def _start_judge(self, include_hidden: bool) -> None:
        if self.judging or not self.locked or self.track is None or self._shutting_down:
            return
        code = self.editor.get("1.0", "end-1c")
        if not code.strip():
            messagebox.showwarning(
                "CodeLock", "The editor is empty. Write a solution first.", parent=self.root
            )
            return
        self.judging = True
        self._set_controls_enabled(False)
        self.judge_state_label.configure(text="RUNNING...", fg=COLORS["amber"])
        self._log(
            "Judging against hidden tests..." if include_hidden else "Running sample tests...",
            "info",
        )
        problem = self.problem
        threading.Thread(
            target=self._judge_worker,
            args=(code, include_hidden, problem),
            name="codelock-judge",
            daemon=True,
        ).start()

    def _judge_worker(self, code: str, include_hidden: bool, problem: Problem) -> None:
        try:
            result = self.judge.evaluate(problem, code, include_hidden=include_hidden)
        except Exception as exc:  # defensive: never leave the UI stuck
            self._ui(self._judge_finished, None, f"Judge error: {exc}", include_hidden)
            return
        self._ui(self._judge_finished, result, None, include_hidden)

    def _judge_finished(
        self,
        result: JudgeResult | None,
        error: str | None,
        include_hidden: bool,
    ) -> None:
        if self._shutting_down:
            return
        self.judging = False
        if self.locked:
            self._set_controls_enabled(True)

        if error:
            self.judge_state_label.configure(text="BLOCKED", fg=COLORS["red"])
            self._log(error, "err")
            messagebox.showerror("CodeLock", error, parent=self.root)
            return

        assert result is not None
        if result.student_output:
            self._log("Your code printed:", "info")
            self._log(result.student_output[:1200], "info")

        if result.timed_out:
            self.judge_state_label.configure(text="TIME LIMIT", fg=COLORS["red"])
            self._log(result.message, "err")
            if include_hidden:
                self._record_attempt(False, result)
            return

        if not result.ok:
            self.judge_state_label.configure(text="FAILED", fg=COLORS["red"])
            self._log(result.message, "err")
            if result.details:
                self._log("stderr: " + result.details, "err")
            if include_hidden:
                self._record_attempt(False, result)
            return

        if not include_hidden:
            self.judge_state_label.configure(text="SAMPLES PASSED", fg=COLORS["green"])
            self._log(
                f"All {result.tests_total} sample tests passed. "
                "Submit to unlock your PC.",
                "ok",
            )
            return

        self.judge_state_label.configure(text="PASSED", fg=COLORS["green"])
        self._log(
            f"All {result.tests_total} tests passed in {result.duration:.2f}s.", "ok"
        )
        self._record_attempt(True, result)
        if not self.locked:
            return
        self._log(
            "A local judge result is not a security guarantee. "
            "Unlocking needs explicit confirmation.",
            "warn",
        )
        confirmed = messagebox.askyesno(
            "CodeLock - Confirm unlock",
            "The local judge passed all tests.\n\n"
            "The judge is not a security sandbox: submitted code runs as your "
            "user. Confirm that you want to unlock the PC for 15 minutes.",
            parent=self.root,
        )
        if confirmed:
            self._unlock()
        else:
            self.judge_state_label.configure(
                text="PASSED - LOCKED", fg=COLORS["amber"]
            )
            self._log("Unlock declined; the PC stays locked.", "warn")

    def _record_attempt(self, passed: bool, result: JudgeResult | None) -> None:
        if self.student is None or self.track is None:
            return
        started = self._challenge_started or time.monotonic()
        duration = max(0.0, time.monotonic() - started)
        student = self.student
        track_key = self.track.key
        problem_key = self.problem.key
        next_index = self.problem_index + 1
        if next_index >= len(self.problems):
            next_index = 0
        tests_passed = result.tests_passed if result is not None else 0
        tests_total = result.tests_total if result is not None else 0
        message = (
            f"Result saved in {duration:.1f}s. Progress updated."
            if passed
            else f"Attempt saved ({duration:.1f}s). Progress kept."
        )
        level = "ok" if passed else "info"

        def worker() -> None:
            try:
                self.store.record_attempt(
                    student.id,
                    track_key,
                    problem_key,
                    duration,
                    passed,
                    tests_passed,
                    tests_total,
                    next_index,
                )
            except Exception as exc:
                self._ui(self._log, f"Progress not saved: {exc}", "warn")
            else:
                self._ui(self._log, message, level)

        threading.Thread(target=worker, name="codelock-progress", daemon=True).start()

    # ============================================================ enforcement
    def _watchdog_loop(self) -> None:
        self._ui(self._set_killer_status, "ACTIVE", COLORS["green"])
        self._enforce_hosts(initial=True)
        last_hosts_check = time.monotonic()

        while not self._stop_event.is_set():
            try:
                if self.locked:
                    killed = self.killer.sweep()
                    if killed:
                        self._ui(
                            self._log,
                            "Closed distracting app(s): " + ", ".join(sorted(set(killed))),
                            "warn",
                        )
                    if (
                        not getattr(self, "_unlocking", False)
                        and time.monotonic() - last_hosts_check
                        > config.HOSTS_RETRY_SECONDS
                    ):
                        last_hosts_check = time.monotonic()
                        self._enforce_hosts(initial=False)
            except Exception as exc:
                self._ui(self._log, f"Watchdog error: {exc}", "err")
            self._stop_event.wait(config.WATCHDOG_INTERVAL_SECONDS)

    def _enforce_hosts(self, initial: bool) -> None:
        if (
            self.dry_run
            or self._shutting_down
            or not self.locked
            or getattr(self, "_unlocking", False)
        ):
            return

        if initial:
            if not self._enforce_lock.acquire(timeout=0.5):
                return
            try:
                if self._shutting_down or not self.locked:
                    return
                self._handle_block_result(self.hosts_control.block(), announce=True)
            finally:
                self._enforce_lock.release()
            return

        # Retry checks are read-only: a declined UAC prompt must never be
        # repeated automatically by the watchdog.
        state = self.hosts_control.state()
        if state.error:
            text, color = self._hosts_display(STATUS_UNKNOWN)
            self._ui(self._set_hosts_status, text, color)
            self._ui(self._show_hosts_retry, True, False)
            if not self._hosts_error_logged:
                self._ui(
                    self._log,
                    f"Could not read the hosts file: {state.error}. "
                    "HOSTS FILE STATUS UNKNOWN. " + WEBSITE_ACCESS_NOTE,
                    "err",
                )
                self._hosts_error_logged = True
            return

        key = state.status
        text, color = self._hosts_display(key)
        self._ui(self._set_hosts_status, text, color)
        blocked = key == STATUS_BLOCKED
        self._ui(self._show_hosts_retry, not blocked, key == STATUS_DAMAGED)
        if blocked:
            self._hosts_error_logged = False
            return
        if not self._hosts_error_logged:
            if key == STATUS_DAMAGED:
                message = (
                    "The hosts file contains damaged CodeLock entries. Click "
                    "REPAIR HOSTS and approve the administrator prompt. " + WEBSITE_ACCESS_NOTE
                )
            elif key == STATUS_PARTIAL:
                message = (
                    "The hosts file contains an incomplete CodeLock block. Click "
                    "RETRY BLOCK to rewrite it. " + WEBSITE_ACCESS_NOTE
                )
            else:
                message = (
                    "The hosts file does not contain a CodeLock block. Click "
                    "RETRY BLOCK and approve the administrator prompt, or run "
                    "--restore if an old block is stuck. " + WEBSITE_ACCESS_NOTE
                )
            self._ui(self._log, message, "err")
            self._hosts_error_logged = True

    def _handle_block_result(self, result, announce: bool) -> None:
        observed = result.observed or (
            STATUS_BLOCKED if result.ok else STATUS_UNKNOWN
        )
        text, color = self._hosts_display(observed)
        self._ui(self._set_hosts_status, text, color)
        blocked = observed == STATUS_BLOCKED
        self._ui(self._show_hosts_retry, not blocked, observed == STATUS_DAMAGED)
        recovery_note = ""
        if result.recovery_required:
            path = write_recovery_file(result.message)
            self._last_recovery_path = path
            if path is not None:
                recovery_note = f" Recovery instructions: {path}."
            else:
                recovery_note = (
                    " Recovery instructions could not be saved; run --restore "
                    "from an administrator terminal."
                )
        dns_note = ""
        if result.dns_flushed is False:
            dns_note = (
                " DNS cache flush failed: "
                f"{result.dns_message or 'unknown error'}. The hosts file state "
                "above was still verified."
            )
        if result.ok and blocked:
            self._hosts_error_logged = False
            clear_recovery_file()
            self._last_recovery_path = None
            if announce:
                self._ui(self._log, result.message + dns_note, "ok")
                self._ui(self._log, WEBSITE_ACCESS_NOTE, "info")
            return
        if announce or not self._hosts_error_logged:
            self._ui(self._log, result.message + dns_note + recovery_note, "err")
            if not result.ok and not getattr(self.hosts_control, "installed", True):
                self._ui(
                    self._log,
                    "The trusted helper is not installed or failed verification. "
                    "Run tools\\install_hosts_helper.ps1 once from an elevated "
                    "PowerShell, then retry.",
                    "err",
                )
            self._hosts_error_logged = True

    def _show_hosts_retry(self, visible: bool, repair: bool = False) -> None:
        try:
            self.hosts_retry_button.configure(
                text="REPAIR HOSTS" if repair else "RETRY BLOCK"
            )
            mapped = bool(self.hosts_retry_button.winfo_ismapped())
            if visible and not mapped:
                self.hosts_retry_button.pack(side="right", padx=(8, 0))
            elif not visible and mapped:
                self.hosts_retry_button.pack_forget()
        except tk.TclError:
            pass

    def _retry_block(self) -> None:
        if self.dry_run or self._shutting_down or not self.locked:
            return
        if getattr(self, "_unlocking", False):
            return
        if getattr(self, "_block_retry_running", False):
            return
        self._block_retry_running = True
        self._hosts_error_logged = False
        state = self.hosts_control.state()
        repair = state.status == STATUS_DAMAGED
        if repair:
            self._log(
                "Repairing damaged CodeLock hosts entries and re-applying the "
                "block. Windows will ask for administrator approval.",
                "warn",
            )
        else:
            self._log(
                "Retrying website blocking. Windows will ask for administrator "
                "approval.",
                "info",
            )

        def worker() -> None:
            try:
                if repair:
                    self._apply_recover(keep_block=True)
                else:
                    self._apply_lock()
            finally:
                self._block_retry_running = False

        threading.Thread(
            target=worker, name="codelock-retry-block", daemon=True
        ).start()

    def _apply_lock(self) -> None:
        if self.dry_run:
            self._ui(self._log, "DRY RUN: skipped website blocking.", "warn")
            return
        if self._shutting_down:
            return
        if not self._enforce_lock.acquire(timeout=30):
            self._ui(
                self._log,
                "Enforcement busy; website blocking was not attempted. "
                "WEBSITES ARE NOT CONFIRMED BLOCKED.",
                "warn",
            )
            return
        try:
            if self._shutting_down:
                return
            self._handle_block_result(self.hosts_control.block(), announce=True)
        finally:
            self._enforce_lock.release()

    def _apply_recover(self, keep_block: bool) -> None:
        if self.dry_run:
            self._ui(self._log, "DRY RUN: skipped hosts-file recovery.", "warn")
            return
        if self._shutting_down and keep_block:
            return
        if not self._enforce_lock.acquire(timeout=30):
            self._ui(
                self._log,
                "Enforcement busy; hosts-file recovery was not attempted.",
                "warn",
            )
            return
        try:
            if self._shutting_down and keep_block:
                return
            result = self.hosts_control.recover(keep_block=keep_block)
            self._handle_block_result(result, announce=True)
        finally:
            self._enforce_lock.release()

    def _apply_unlock(self) -> None:
        if self.dry_run:
            self._ui(self._log, "DRY RUN: reward granted without touching hosts.", "ok")
            self._ui(self._finish_unlock, True)
            return
        if self._shutting_down:
            return
        if not self._enforce_lock.acquire(timeout=30):
            path = write_recovery_file(
                "The unlock operation could not run because enforcement was busy."
            )
            self._last_recovery_path = path
            self._last_unlock_status = STATUS_UNKNOWN
            self._ui(self._set_hosts_status, *self._hosts_display(STATUS_UNKNOWN))
            self._ui(
                self._log,
                "Enforcement busy; hosts-file state was not changed."
                + (
                    f" Recovery instructions: {path}."
                    if path is not None
                    else " Recovery instructions could not be saved; run --restore "
                    "from an administrator terminal."
                ),
                "warn",
            )
            self._ui(self._finish_unlock, False)
            return
        success = False
        try:
            if self._shutting_down:
                return
            result = self.hosts_control.unblock()
            success = result.ok
            observed = result.observed or (
                STATUS_UNBLOCKED if success else STATUS_UNKNOWN
            )
            self._last_unlock_status = observed
            self._ui(self._set_hosts_status, *self._hosts_display(observed))
            self._ui(
                self._show_hosts_retry,
                not success,
                observed == STATUS_DAMAGED,
            )
            dns_note = ""
            if result.dns_flushed is False:
                dns_note = (
                    " DNS cache flush failed: "
                    f"{result.dns_message or 'unknown error'}; the hosts file "
                    "state was still verified."
                )
            if success:
                self._last_recovery_path = None
                clear_recovery_file()
                self._ui(self._log, result.message + dns_note, "ok")
                self._ui(self._log, WEBSITE_ACCESS_NOTE, "info")
            else:
                path = write_recovery_file(result.message)
                self._last_recovery_path = path
                self._ui(
                    self._log,
                    result.message
                    + dns_note
                    + (
                        f" Recovery instructions: {path}."
                        if path is not None
                        else " Recovery instructions could not be saved; run "
                        "--restore from an administrator terminal."
                    ),
                    "err",
                )
        finally:
            self._enforce_lock.release()
            if not self._shutting_down:
                self._ui(self._finish_unlock, success)

    # ================================================================ reward
    def _unlock(self) -> None:
        if not self.locked or getattr(self, "_unlocking", False):
            return
        self._unlocking = True
        self._set_controls_enabled(False)
        self.judge_state_label.configure(text="RESTORING PC", fg=COLORS["amber"])
        self._log("Solution passed. Restoring website access...", "info")
        threading.Thread(
            target=self._apply_unlock, name="codelock-unlock", daemon=True
        ).start()

    def _finish_unlock(self, success: bool) -> None:
        self._unlocking = False
        if not success:
            self._set_controls_enabled(True)
            self.judge_state_label.configure(text="RESTORE FAILED", fg=COLORS["red"])
            observed = self._last_unlock_status or STATUS_UNKNOWN
            self._set_hosts_status(*self._hosts_display(observed))
            self._show_hosts_retry(True, observed == STATUS_DAMAGED)
            self._log(
                "The hosts file was not verified as restored, so the reward has "
                "not started. " + WEBSITE_ACCESS_NOTE,
                "err",
            )
            self._show_recovery_dialog(
                "The CodeLock block is still present, damaged, or its removal "
                "could not be verified.",
                self._last_recovery_path,
            )
            return
        self.locked = False
        self._set_controls_enabled(False)
        self._set_close_enabled(True)
        self.root.attributes("-topmost", False)
        self.judge_state_label.configure(text="UNLOCKED", fg=COLORS["green"])
        self._set_header(
            COLORS["green_dark"],
            COLORS["green"],
            "UNLOCKED",
            "DRY RUN - REWARD SIMULATED" if self.dry_run else "REWARD MODE - 15 MINUTES",
            "#d7ffdd",
        )
        self._log("Access granted. Unlocking your PC for 15 minutes.", "ok")
        self._set_killer_status("PAUSED", COLORS["amber"])
        self.reward_deadline = time.monotonic() + config.REWARD_SECONDS
        self._tick_reward()

    def _tick_reward(self) -> None:
        if self._shutting_down or self.locked:
            return
        remaining = self.reward_deadline - time.monotonic()
        if remaining <= 0:
            self.timer_badge.configure(text="00:00", fg=COLORS["red"])
            self._relock()
            return
        minutes, seconds = divmod(int(remaining), 60)
        self.timer_badge.configure(
            text=f"{minutes:02d}:{seconds:02d}", fg=COLORS["green"]
        )
        self.root.after(250, self._tick_reward)

    def _relock(self) -> None:
        if self.locked:
            return
        self.locked = True
        self.timer_badge.configure(text="--:--", fg=COLORS["muted"])
        self._set_close_enabled(False)
        self.root.attributes("-topmost", True)
        self._set_header(
            COLORS["red"],
            COLORS["red_dark"],
            "DRY RUN" if self.dry_run else "LOCKED",
            "TEST MODE - NOTHING IS BLOCKED" if self.dry_run else "PC DISTRACTION BLOCKER",
            "#ffd7d5",
        )
        self.judge_state_label.configure(text="AWAITING SUBMISSION", fg=COLORS["muted"])
        self._set_controls_enabled(True)
        self._set_killer_status(
            "SIMULATED" if self.dry_run else "ACTIVE",
            COLORS["amber"] if self.dry_run else COLORS["green"],
        )
        self._log("Reward time expired. Re-locking your PC.", "warn")
        self._advance_problem()
        threading.Thread(
            target=self._apply_lock, name="codelock-relock", daemon=True
        ).start()

    # ================================================================ actions
    def _on_close_request(self) -> None:
        if self._shutting_down:
            return
        if self.dry_run:
            self._shutdown()
            return
        # The mode chooser is setup, not an enforced study session.
        if self.student is not None and self.track is None and self._exam_window is None:
            self._log("Choose Exam Preparation or DSA Practice to continue.", "warn")
            if self._picker is None:
                self._show_mode_picker()
            else:
                try:
                    self._picker.lift()
                    self._picker.focus_force()
                except tk.TclError:
                    pass
            return
        # Signup and mode selection are setup, not an enforced study session.
        if self.locked and self.student is not None and self.track is not None:
            self._log("Close attempt blocked: the session is still locked.", "warn")
            body = (
                "Study mode is active.\n\n"
                "Solve the coding challenge to unlock your PC.\n"
                "Admin exit: Ctrl + Alt + Shift + Q"
            )
            messagebox.showwarning(
                "CodeLock", body, parent=self._active_modal() or self.root
            )
            return
        self._shutdown()

    def _emergency_exit(self, _event: tk.Event | None = None) -> str:
        if self._shutting_down:
            return "break"
        if not self.locked:
            self._shutdown()
            return "break"
        if not config.ADMIN_PASSWORD:
            confirmed = messagebox.askyesno(
                "Emergency Exit",
                "No emergency password is configured. Exit CodeLock and restore "
                "website access now?",
                parent=self._active_modal() or self.root,
            )
            if confirmed:
                self._log("Emergency exit confirmed. Restoring the PC.", "warn")
                self._shutdown()
            return "break"
        password = simpledialog.askstring(
            "Emergency Exit",
            "Admin password (restores your PC and quits):",
            show="*",
            parent=self._active_modal() or self.root,
        )
        modal = self._active_modal()
        if modal is not None and not self._shutting_down:
            try:
                modal.grab_set()
            except tk.TclError:
                pass
        if password is None:
            return "break"
        try:
            approved = hmac.compare_digest(
                password.encode("utf-8"), config.ADMIN_PASSWORD.encode("utf-8")
            )
        except (AttributeError, UnicodeError):
            approved = False
        if approved:
            self._log("Admin exit approved. Restoring the PC.", "warn")
            self._shutdown()
        else:
            self._log("Incorrect admin password.", "err")
            messagebox.showerror(
                "CodeLock", "Incorrect admin password.", parent=self.root
            )
        return "break"

    def _tick_kiosk(self) -> None:
        if self._shutting_down:
            return
        if self.locked and self.track is not None:
            try:
                self.root.attributes("-topmost", True)
                if self.root.state() == "iconic":
                    self.root.deiconify()
                    self.root.lift()
            except tk.TclError:
                return
        self.root.after(1500, self._tick_kiosk)

    # =============================================================== shutdown
    def shutdown(self) -> None:
        self._shutdown()

    def _shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._stop_event.set()
        self._log(
            "Exiting dry run..." if self.dry_run else "Restoring your PC before exit...",
            "info",
        )
        try:
            self.root.update_idletasks()
        except tk.TclError:
            pass
        if not self.dry_run:
            self._restore_now()
        exam_window, self._exam_window = self._exam_window, None
        if exam_window is not None:
            try:
                exam_window.shutdown()
            except Exception:
                pass
        try:
            self.store.close()
        except Exception:
            pass
        try:
            for after_id in self.root.tk.splitlist(
                self.root.tk.call("after", "info")
            ):
                self.root.after_cancel(after_id)
        except tk.TclError:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _restore_now(self) -> None:
        acquired = self._enforce_lock.acquire(timeout=8)
        if not acquired:
            self._log("Restore raced with the watchdog; attempting anyway.", "warn")
        try:
            try:
                state = self.hosts_control.state()
                if state.status in (STATUS_UNBLOCKED, "missing"):
                    self._log(
                        "No CodeLock hosts block is present; nothing to restore. "
                        "HOSTS FILE NOT BLOCKED (observed).",
                        "ok",
                    )
                    clear_recovery_file()
                    return
                if state.status == STATUS_DAMAGED:
                    self._log(
                        "Damaged CodeLock hosts entries found; running the "
                        "recovery procedure.",
                        "warn",
                    )
                    result = self.hosts_control.recover(keep_block=False)
                else:
                    result = self.hosts_control.unblock()
                dns_note = ""
                if result.dns_flushed is False:
                    dns_note = (
                        " DNS cache flush failed: "
                        f"{result.dns_message or 'unknown error'}; the hosts file "
                        "state was still verified."
                    )
                if result.ok:
                    self._log(
                        "Hosts file restored and verified. HOSTS FILE NOT BLOCKED."
                        + dns_note,
                        "ok",
                    )
                    clear_recovery_file()
                else:
                    path = write_recovery_file(result.message)
                    self._log(result.message + dns_note, "err")
                    if path is not None:
                        self._log(f"Recovery instructions saved to {path}.", "err")
                    else:
                        self._log(
                            "Recovery instructions could not be saved. Run "
                            "--restore from an administrator terminal.",
                            "err",
                        )
                    self._show_recovery_dialog(result.message, path)
            except Exception as exc:
                path = write_recovery_file(f"{type(exc).__name__}: {exc}")
                self._log(f"Hosts restore error: {exc}", "err")
                if path is None:
                    self._log(
                        "Recovery instructions could not be saved. Run --restore "
                        "from an administrator terminal.",
                        "err",
                    )
                self._show_recovery_dialog(str(exc), path)
        finally:
            if acquired:
                self._enforce_lock.release()

    def _show_recovery_dialog(self, reason: str, path) -> None:
        try:
            messagebox.showwarning(
                "CodeLock - Hosts file not restored",
                "CodeLock could not verify that the CodeLock hosts entries were "
                "removed.\n\n"
                f"Reason: {reason}\n\n"
                "To restore access:\n"
                "1. Open PowerShell or Command Prompt as Administrator.\n"
                "2. Run:\n"
                f"   {restore_command()}\n\n"
                + (
                    f"Full instructions: {path}"
                    if path is not None
                    else "Recovery instructions could not be saved; use the "
                    f"command above or inspect {config.HOSTS_PATH} manually."
                ),
                parent=self.root,
            )
        except tk.TclError:
            pass

    # ================================================================ startup
    def _log_startup(self) -> None:
        if self.dry_run:
            self._set_hosts_status("SIMULATED", COLORS["amber"])
            self._set_killer_status("SIMULATED", COLORS["amber"])
            self._log(
                "DRY RUN: no hosts or process enforcement in this mode.",
                "warn",
            )
            self._log("Use EXIT DRY RUN (or the window X) to quit testing.", "info")
        else:
            self._set_hosts_status("waiting", COLORS["muted"])
            self._set_killer_status("waiting", COLORS["muted"])
            self._log(
                "CodeLock started. Enforcement begins after you choose a track.",
                "info",
            )
            if self._startup_status == STATUS_BLOCKED:
                self._log(
                    "The hosts file currently contains a complete CodeLock block. "
                    "It will be reused when this session locks and removed when it "
                    "unlocks. " + WEBSITE_ACCESS_NOTE,
                    "warn",
                )
            elif self._startup_status == STATUS_PARTIAL:
                self._log(
                    "The hosts file contains an incomplete CodeLock block. The "
                    "first lock will rewrite and verify it.",
                    "warn",
                )
            elif self._startup_status == STATUS_DAMAGED:
                self._log(
                    "The hosts file contains damaged CodeLock entries. Use REPAIR "
                    "HOSTS while locked or run --restore from an administrator "
                    "terminal.",
                    "err",
                )
            elif self._startup_status == STATUS_UNKNOWN:
                self._log(
                    "Could not read the hosts file; HOSTS FILE STATUS UNKNOWN "
                    f"({self._startup_hosts_error or 'access error'}). "
                    + WEBSITE_ACCESS_NOTE,
                    "warn",
                )
            else:
                self._log(
                    "The hosts file does not contain a CodeLock block. "
                    + WEBSITE_ACCESS_NOTE,
                    "info",
                )
            verification = self._startup_verification
            if verification is None or not verification.ok:
                problems = (
                    verification.summary if verification is not None else "not checked"
                )
                self._log(
                    "The trusted hosts helper is not installed or failed "
                    f"verification ({problems}). Website blocking will be refused. "
                    "Install it once from an elevated PowerShell with "
                    "tools\\install_hosts_helper.ps1.",
                    "err",
                )
            else:
                self._log(
                    "Trusted hosts helper verified (SHA-256 "
                    f"{verification.helper_sha256[:16]}... at "
                    f"{self.hosts_control.install_path}).",
                    "ok",
                )
            self._log(
                "CodeLock stays unprivileged. Every elevated launch verifies the "
                "installed helper's manifest and ACLs; every change is verified by "
                "re-reading the hosts file.",
                "info",
            )
            if not config.ADMIN_PASSWORD:
                self._log(
                    "No admin password is set: emergency exit asks for confirmation "
                    "only. Set CODELOCK_ADMIN_PASSWORD to require a password.",
                    "warn",
                )
            if self.killer.available:
                self._log("App killer: watching the process blocklist.", "info")
            else:
                self._log(
                    "App killer: psutil is missing; using tasklist/taskkill.",
                    "warn",
                )
        self._log(f"Accounts: {self.store.backend_name}.", "info")
        if self.store.backend_warning:
            self._log(self.store.backend_warning, "warn")
        self._log("Sign in with a student account to begin.", "info")
