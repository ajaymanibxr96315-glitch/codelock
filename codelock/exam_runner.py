"""Practice and mock exam windows with objective scoring and result review."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from . import exam_engine
from .db import StudentStore, StoreError
from .ui_common import enable_fullscreen

_BG = "#0d1117"
_PANEL = "#161b22"
_TEXT = "#e6edf3"
_MUTED = "#8b949e"
_ACCENT = "#58a6ff"
_GREEN = "#3fb950"
_RED = "#f85149"
_AMBER = "#d29922"

_STATUS_TEXT = {
    "auto_correct": "Correct",
    "auto_incorrect": "Incorrect",
    "needs_review": "Awaiting review",
    "unanswered": "Not answered",
}


def _format_seconds(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    return f"{total // 60:02d}:{total % 60:02d}"


class ExamRunnerWindow:
    """Runs one saved practice or mock session."""

    def __init__(
        self,
        parent: tk.Misc,
        store: StudentStore,
        student_id: int,
        session: dict,
        responses: list[dict],
        subject: str = "",
        notice: str = "",
        on_finish: Callable[[dict | None], None] | None = None,
    ) -> None:
        self.store = store
        self.student_id = student_id
        self.session = session
        self.responses = list(responses)
        self.mode = str(session.get("mode", "practice"))
        self.on_finish = on_finish
        self.index = 0
        self.answers: dict[int, str] = {}
        self.saved_answers: dict[int, str] = {}
        self.checked: set[int] = set()
        self.submitted = False
        self._submitting = False
        self._closing = False
        self._timer_job: str | None = None
        self._answer_reader: Callable[[], str] | None = None
        for response in self.responses:
            answer = str(response.get("student_answer", "") or "")
            self.answers[int(response["response_id"])] = answer
            self.saved_answers[int(response["response_id"])] = answer

        self.window = tk.Toplevel(parent)
        self.window.title(
            "CodeLock - Practice" if self.mode == "practice" else "CodeLock - Mock Exam"
        )
        self.window.configure(bg=_BG)
        self.window.geometry("900x720")
        self.window.minsize(760, 600)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        enable_fullscreen(self.window)

        header = tk.Frame(self.window, bg=_BG)
        header.pack(fill="x", padx=18, pady=(14, 4))
        tk.Label(
            header,
            text=("PRACTICE SESSION" if self.mode == "practice" else "MOCK EXAMINATION"),
            bg=_BG, fg=_TEXT, font=("Consolas", 16, "bold"),
        ).pack(side="left")
        self.timer_label = tk.Label(header, text="", bg=_BG, fg=_AMBER,
                                    font=("Consolas", 14, "bold"))
        self.timer_label.pack(side="right")

        details = f"{subject} · {len(self.responses)} questions · {int(session.get('total_marks') or 0)} marks"
        if notice:
            details += f" · {notice}"
        tk.Label(self.window, text=details, bg=_BG, fg=_MUTED,
                 wraplength=840, justify="left").pack(anchor="w", padx=18, pady=(0, 8))

        self.progress_label = tk.Label(self.window, text="", bg=_BG, fg=_ACCENT,
                                       font=("Consolas", 10, "bold"))
        self.progress_label.pack(anchor="w", padx=18)

        body = tk.Frame(self.window, bg=_BG)
        body.pack(fill="both", expand=True, padx=18, pady=(4, 8))
        self.meta_label = tk.Label(body, text="", bg=_BG, fg=_MUTED, anchor="w")
        self.meta_label.pack(fill="x")
        self.prompt_label = tk.Label(body, text="", bg=_BG, fg=_TEXT, anchor="w",
                                     justify="left", wraplength=820,
                                     font=("Consolas", 12))
        self.prompt_label.pack(fill="x", pady=(6, 10))
        self.answer_frame = tk.Frame(body, bg=_BG)
        self.answer_frame.pack(fill="both", expand=True)
        self.feedback_label = tk.Label(body, text="", bg=_BG, fg=_GREEN, anchor="w",
                                       justify="left", wraplength=820)
        self.feedback_label.pack(fill="x", pady=(8, 0))

        actions = tk.Frame(self.window, bg=_BG)
        actions.pack(fill="x", padx=18, pady=(4, 14))
        self.previous_btn = self._button(actions, "PREVIOUS", lambda: self._go(-1), _PANEL, _TEXT)
        self.previous_btn.pack(side="left")
        self.check_btn = self._button(actions, "CHECK ANSWER", self._check, _ACCENT, "#07111d")
        if self.mode == "practice":
            self.check_btn.pack(side="left", padx=6)
        self.next_btn = self._button(actions, "NEXT", lambda: self._go(1), _PANEL, _TEXT)
        self.next_btn.pack(side="left", padx=6)
        self.submit_btn = self._button(
            actions,
            "SUBMIT PRACTICE" if self.mode == "practice" else "SUBMIT EXAM",
            self._submit, _GREEN, "#07130a",
        )
        self.submit_btn.pack(side="right")
        self.leave_btn = self._button(
            actions, "LEAVE SESSION", self._on_close, _PANEL, _TEXT
        )
        self.leave_btn.pack(side="right", padx=6)

        self._render()
        self.window.grab_set()
        self.window.lift()
        self.window.focus_force()
        self._tick()

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _button(parent, label: str, command, bg: str, fg: str) -> tk.Button:
        return tk.Button(parent, text=label, command=command, bg=bg, fg=fg,
                         activebackground=bg, activeforeground=fg, relief="flat",
                         font=("Consolas", 9, "bold"), padx=14, pady=7,
                         cursor="hand2")

    def _current_response(self) -> dict | None:
        if 0 <= self.index < len(self.responses):
            return self.responses[self.index]
        return None

    def _current_answer(self) -> str:
        if self._answer_reader is None:
            return ""
        try:
            return self._answer_reader().strip()
        except tk.TclError:
            return ""

    def _clear(self, frame: tk.Widget) -> None:
        for child in frame.winfo_children():
            child.destroy()

    # ----------------------------------------------------------------- rendering
    def _render(self) -> None:
        response = self._current_response()
        if response is None:
            return
        snapshot = response.get("snapshot") or {}
        count = len(self.responses)
        self.progress_label.configure(text=f"Question {self.index + 1} of {count}")
        meta = (
            f"{response.get('topic') or 'Unspecified'} · "
            f"{response.get('question_type') or 'Question'} · "
            f"{max(1, int(response.get('marks', 1)))} mark(s)"
        )
        difficulty = str(snapshot.get("difficulty", "")).strip()
        if difficulty:
            meta += f" · {difficulty}"
        self.meta_label.configure(text=meta)
        self.prompt_label.configure(text=str(snapshot.get("question", "")))
        self.feedback_label.configure(text="")
        self._answer_reader = None
        self._clear(self.answer_frame)
        self._build_answer_widgets(response)

        response_id = int(response["response_id"])
        if response_id in self.checked:
            self._show_saved_feedback(response)

        self.previous_btn.configure(state="normal" if self.index > 0 else "disabled")
        self.next_btn.configure(
            state="normal" if self.index < count - 1 else "disabled"
        )
        self.check_btn.configure(
            state="normal" if self.mode == "practice" else "disabled"
        )
        self._update_timer()

    def _build_answer_widgets(self, response: dict) -> None:
        snapshot = response.get("snapshot") or {}
        question_type = str(response.get("question_type", ""))
        response_id = int(response["response_id"])
        current = self.answers.get(response_id, "")

        if question_type == exam_engine.MCQ:
            options = [
                str(option) for option in snapshot.get("options", [])
                if str(option).strip()
            ]
            if not options:
                self._build_text_answer(current)
                return
            variable = tk.StringVar(value=current)
            for position, option in enumerate(options):
                tk.Radiobutton(
                    self.answer_frame, text=f"{chr(65 + position)}.  {option}",
                    variable=variable, value=option, bg=_BG, fg=_TEXT,
                    selectcolor=_PANEL, activebackground=_BG,
                    activeforeground=_TEXT, anchor="w", justify="left",
                    wraplength=780, font=("Consolas", 11),
                ).pack(fill="x", anchor="w", pady=2)
            self._answer_reader = variable.get
            return

        if question_type == exam_engine.TRUE_FALSE:
            values = [
                str(option) for option in snapshot.get("options", [])
                if str(option).strip()
            ]
            if len(values) != 2:
                values = ["True", "False"]
            variable = tk.StringVar(value=current)
            for option in values:
                tk.Radiobutton(
                    self.answer_frame, text=option, variable=variable, value=option,
                    bg=_BG, fg=_TEXT, selectcolor=_PANEL, activebackground=_BG,
                    activeforeground=_TEXT, anchor="w", font=("Consolas", 11),
                ).pack(fill="x", anchor="w", pady=2)
            self._answer_reader = variable.get
            return

        if question_type in {exam_engine.FILL_BLANKS, exam_engine.ONE_WORD}:
            entry = tk.Entry(self.answer_frame, bg="#0b0f14", fg=_TEXT,
                             insertbackground=_TEXT, relief="flat",
                             font=("Consolas", 12))
            entry.insert(0, current)
            entry.pack(fill="x", ipady=6)
            self._answer_reader = entry.get
            return

        self._build_text_answer(current)

    def _build_text_answer(self, current: str) -> None:
        frame = tk.Frame(self.answer_frame, bg=_BG)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, height=9, wrap="word", undo=True, bg="#0b0f14",
                       fg=_TEXT, insertbackground=_TEXT, relief="flat",
                       padx=10, pady=8, font=("Consolas", 11))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        text.insert("1.0", current)
        self._answer_reader = lambda: text.get("1.0", "end-1c")
        tk.Label(
            self.answer_frame,
            text="Written answers are saved for manual review; no automatic marks are awarded.",
            bg=_BG, fg=_MUTED, anchor="w",
        ).pack(fill="x", pady=(4, 0))

    def _show_saved_feedback(self, response: dict) -> None:
        snapshot = response.get("snapshot") or {}
        status = str(response.get("review_status", "unanswered"))
        awarded = float(response.get("awarded_marks") or 0)
        marks = max(1, int(response.get("marks", 1)))
        correct = str(snapshot.get("answer", ""))
        explanation = str(snapshot.get("explanation", "")).strip()
        if status == "auto_correct":
            text = f"CORRECT · {awarded:g}/{marks} marks awarded."
            color = _GREEN
        elif status == "auto_incorrect":
            text = f"INCORRECT · correct answer: {correct}"
            color = _RED
        else:
            text = "Saved for review · written answers receive manual marks."
            color = _AMBER
        if status != "auto_correct" and explanation and status == "auto_incorrect":
            text += f"\n{explanation}"
        self.feedback_label.configure(text=text, fg=color)

    # ---------------------------------------------------------------- operations
    def _record_current(self) -> None:
        response = self._current_response()
        if response is None:
            return
        response_id = int(response["response_id"])
        answer = self._current_answer()
        previous = self.answers.get(response_id, "")
        if answer == previous and (
            response_id in self.checked
            or self.saved_answers.get(response_id, "") == answer
        ):
            return

        self.answers[response_id] = answer
        self.checked.discard(response_id)
        self.feedback_label.configure(text="")
        if not answer and not previous:
            return
        try:
            self.store.save_exam_response(
                self.student_id, self.session["session_id"], response_id,
                answer, None, 0.0, "unanswered",
            )
            self.saved_answers[response_id] = answer
        except StoreError as exc:
            messagebox.showerror("Exam session", str(exc), parent=self.window)

    def _go(self, delta: int) -> None:
        if self._closing:
            return
        self._record_current()
        target = self.index + delta
        if 0 <= target < len(self.responses):
            self.index = target
            self._render()

    def _check(self) -> None:
        if self._closing or self.submitted:
            return
        response = self._current_response()
        if response is None:
            return
        self._record_current()
        answer = self._current_answer()
        if not answer.strip():
            self.feedback_label.configure(text="Enter an answer before checking.", fg=_AMBER)
            return
        response_id = int(response["response_id"])
        try:
            result = exam_engine.practice_check(
                self.store, self.student_id, self.session["session_id"],
                response_id, answer,
            )
        except (exam_engine.ExamError, StoreError) as exc:
            messagebox.showerror("Practice", str(exc), parent=self.window)
            return
        self.checked.add(response_id)
        self.saved_answers[response_id] = answer
        response["review_status"] = result["status"]
        response["awarded_marks"] = result["awarded_marks"]
        response["is_correct"] = result["is_correct"]
        response["student_answer"] = answer
        if result["status"] == "auto_correct":
            text = f"CORRECT · {result['awarded_marks']:g}/{result['marks']} marks awarded."
            color = _GREEN
        elif result["status"] == "auto_incorrect":
            text = f"INCORRECT · correct answer: {result['correct_answer']}"
            color = _RED
        else:
            text = "Saved for review · written answers receive manual marks."
            color = _AMBER
        self.feedback_label.configure(text=text, fg=color)

    def _submit(self) -> None:
        if self._closing or self.submitted or self._submitting:
            return
        self._submitting = True
        try:
            self._submit_confirmed()
        finally:
            self._submitting = False

    def _submit_confirmed(self) -> None:
        self._record_current()
        unanswered = sum(
            1 for response in self.responses
            if not self.answers.get(int(response["response_id"]), "").strip()
        )
        prompt = "Submit this session now?"
        if unanswered:
            prompt += f" {unanswered} question(s) are unanswered."
        if not messagebox.askyesno("Submit session", prompt, parent=self.window):
            return
        try:
            result = exam_engine.submit_session(
                self.store, self.student_id, self.session["session_id"]
            )
        except (exam_engine.ExamError, StoreError) as exc:
            messagebox.showerror("Submit session", str(exc), parent=self.window)
            return
        self.submitted = True
        self._stop_timer()
        self._destroy()
        if self.on_finish:
            self.on_finish(result)

    def _tick(self) -> None:
        if self._closing or self.submitted:
            return
        try:
            self._update_timer()
        except tk.TclError:
            return
        if self.mode == "mock" and not self._submitting:
            remaining = exam_engine.remaining_seconds(self.session)
            if remaining is not None and remaining <= 0:
                self._auto_submit()
                return
        try:
            self._timer_job = self.window.after(1000, self._tick)
        except tk.TclError:
            self._timer_job = None

    def _update_timer(self) -> None:
        if self.mode == "mock":
            remaining = exam_engine.remaining_seconds(self.session)
            if remaining is None:
                self.timer_label.configure(text="")
                return
            color = _RED if remaining <= 60 else _AMBER
            self.timer_label.configure(text=f"TIME LEFT {_format_seconds(remaining)}",
                                       fg=color)
        else:
            elapsed = exam_engine._elapsed_seconds(self.session.get("started_at"))
            self.timer_label.configure(text=f"ELAPSED {_format_seconds(elapsed)}",
                                       fg=_MUTED)

    def _auto_submit(self) -> None:
        if self._closing or self.submitted or self._submitting:
            return
        self._stop_timer()
        self._record_current()
        try:
            result = exam_engine.submit_session(
                self.store, self.student_id, self.session["session_id"]
            )
        except (exam_engine.ExamError, StoreError) as exc:
            messagebox.showerror("Mock exam", str(exc), parent=self.window)
            return
        self.submitted = True
        messagebox.showinfo(
            "Time is up", "The time limit has ended. Your answers were submitted.",
            parent=self.window,
        )
        self._destroy()
        if self.on_finish:
            self.on_finish(result)

    def _stop_timer(self) -> None:
        if self._timer_job is not None:
            try:
                self.window.after_cancel(self._timer_job)
            except tk.TclError:
                pass
            self._timer_job = None

    def _on_close(self) -> None:
        if self._closing:
            return
        if self.submitted:
            self._destroy()
            return
        if not messagebox.askyesno(
            "Leave session",
            "Leave this session? It will be marked abandoned; saved answers stay in history.",
            parent=self.window,
        ):
            return
        self._abandon_and_close(notify=True)

    def _abandon_and_close(self, notify: bool) -> None:
        self._closing = True
        self._stop_timer()
        if not self.submitted:
            try:
                exam_engine.abandon_session(
                    self.store, self.student_id, self.session["session_id"]
                )
            except (exam_engine.ExamError, StoreError):
                pass
        self.submitted = True
        self._destroy()
        if notify and self.on_finish:
            self.on_finish(None)

    def force_close(self) -> None:
        """Close without prompts, e.g. when the app is shutting down."""
        self._closing = True
        self._stop_timer()
        self._destroy()

    def _destroy(self) -> None:
        self._closing = True
        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        try:
            self.window.destroy()
        except tk.TclError:
            pass


class ExamResultWindow:
    """Score summary, topic breakdown and answer review for a finished session."""

    def __init__(
        self,
        parent: tk.Misc,
        result: dict,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.on_close = on_close
        session = result["session"]
        mode = str(session.get("mode", "practice"))
        self.window = tk.Toplevel(parent)
        self.window.title("CodeLock - Session Result")
        self.window.configure(bg=_BG)
        self.window.geometry("920x720")
        self.window.minsize(760, 580)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        enable_fullscreen(self.window)

        tk.Label(self.window, text="SESSION RESULT", bg=_BG, fg=_TEXT,
                 font=("Consolas", 16, "bold")).pack(anchor="w", padx=18, pady=(14, 2))
        score = float(result["score"])
        total = int(result["total_marks"])
        percentage = float(result["percentage"])
        summary = (
            f"{'Practice' if mode == 'practice' else 'Mock examination'} · "
            f"{score:g}/{total} marks · {percentage:.1f}%"
        )
        if result["needs_review"]:
            summary += f" · {result['needs_review']} written answer(s) awaiting review"
        tk.Label(self.window, text=summary, bg=_BG, fg=_GREEN if percentage >= 40 else _AMBER,
                 font=("Consolas", 11, "bold")).pack(anchor="w", padx=18, pady=(0, 10))

        notebook = ttk.Notebook(self.window)
        notebook.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        overview = tk.Frame(notebook, bg=_BG)
        review = tk.Frame(notebook, bg=_BG)
        notebook.add(overview, text="Topic performance")
        notebook.add(review, text="Answer review")
        self._build_overview(overview, result["topics"])
        self._build_review(review, result["responses"])

        actions = tk.Frame(self.window, bg=_BG)
        actions.pack(fill="x", padx=14, pady=(0, 14))
        tk.Button(actions, text="CLOSE", command=self.close, bg=_PANEL, fg=_TEXT,
                  relief="flat", font=("Consolas", 9, "bold"), padx=18, pady=7,
                  cursor="hand2").pack(side="right")
        self.window.grab_set()
        self.window.lift()
        self.window.focus_force()

    def _build_overview(self, parent: tk.Frame, topics: list[dict]) -> None:
        columns = ("topic", "questions", "correct", "incorrect", "review",
                   "unanswered", "marks", "awarded", "accuracy")
        headings = {
            "topic": "Topic", "questions": "Questions", "correct": "Correct",
            "incorrect": "Incorrect", "review": "Needs review",
            "unanswered": "Unanswered", "marks": "Marks", "awarded": "Awarded",
            "accuracy": "Accuracy",
        }
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=12)
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=200 if column == "topic" else 88,
                        anchor="w" if column == "topic" else "center")
        for topic in topics:
            accuracy = topic["accuracy"]
            tree.insert("", "end", values=(
                topic["topic"], topic["questions"], topic["correct"],
                topic["incorrect"], topic["needs_review"], topic["unanswered"],
                topic["marks"], f"{topic['awarded']:g}",
                "-" if accuracy is None else f"{accuracy:.0f}%",
            ))
        scroll = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scroll.pack(side="right", fill="y", pady=10, padx=(0, 10))
        if not topics:
            tk.Label(parent, text="No questions were part of this session.",
                     bg=_BG, fg=_MUTED).pack(padx=14, pady=14)

    def _build_review(self, parent: tk.Frame, responses: list[dict]) -> None:
        frame = tk.Frame(parent, bg=_BG)
        frame.pack(fill="both", expand=True, padx=12, pady=10)
        text = tk.Text(frame, wrap="word", bg="#0b0f14", fg=_TEXT, relief="flat",
                       padx=12, pady=10, font=("Consolas", 10))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        text.tag_configure("ok", foreground=_GREEN)
        text.tag_configure("bad", foreground=_RED)
        text.tag_configure("review", foreground=_AMBER)
        text.tag_configure("muted", foreground=_MUTED)
        text.tag_configure("head", foreground=_ACCENT, font=("Consolas", 10, "bold"))

        for position, response in enumerate(responses, start=1):
            snapshot = response.get("snapshot") or {}
            marks = max(1, int(response.get("marks", 1)))
            status = str(response.get("review_status", "unanswered"))
            awarded = float(response.get("awarded_marks") or 0)
            tag = {
                "auto_correct": "ok",
                "auto_incorrect": "bad",
                "needs_review": "review",
            }.get(status, "muted")
            text.insert("end", f"Q{position}. ", "head")
            text.insert(
                "end",
                f"{response.get('topic') or 'Unspecified'} · "
                f"{response.get('question_type')} · {marks} mark(s)\n",
                "muted",
            )
            text.insert("end", f"{snapshot.get('question', '')}\n")
            given = str(response.get("student_answer", "") or "").strip()
            text.insert("end", "Your answer: ", "muted")
            text.insert("end", (given if given else "(not answered)") + "\n")
            text.insert(
                "end",
                f"{_STATUS_TEXT.get(status, status)} · {awarded:g}/{marks} marks\n",
                tag,
            )
            expected = str(snapshot.get("answer", "")).strip()
            if status in {"auto_incorrect", "needs_review", "unanswered"} and expected:
                text.insert("end", f"Reference answer: {expected}\n", "muted")
            explanation = str(snapshot.get("explanation", "")).strip()
            if explanation:
                text.insert("end", f"Explanation: {explanation}\n", "muted")
            text.insert("end", "\n")
        text.configure(state="disabled")

    def close(self) -> None:
        try:
            self.window.grab_release()
            self.window.destroy()
        except tk.TclError:
            pass
        if self.on_close:
            self.on_close()

    def force_close(self) -> None:
        try:
            self.window.destroy()
        except tk.TclError:
            pass
