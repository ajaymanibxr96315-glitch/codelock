"""GUI smoke test for the exam analytics dashboard.

Run with ``python main.py --self-test-ui``. It uses a temporary SQLite database
and never touches the real hosts file, desktop applications or student data.
"""

from __future__ import annotations

import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

from . import exam_analytics, exam_engine
from . import exam_ui as exam_ui_module
from .db import StudentStore
from .exam_runner import ExamResultWindow
from .exam_ui import ExamPreparationWindow


def _is_fullscreen(window: tk.Misc) -> bool:
    try:
        if bool(window.attributes("-fullscreen")):
            return True
    except tk.TclError:
        pass
    try:
        return str(window.state()) == "zoomed"
    except tk.TclError:
        return False


def _algebra_questions(count: int = 10) -> list[dict]:
    questions = []
    for index in range(count):
        questions.append(
            {
                "question": f"Algebra check {index + 1}: what is {index + 1} + 1?",
                "question_type": exam_engine.MCQ,
                "options": ["1", "2", "3", "4"],
                "answer": "2",
                "source_topic": "Algebra",
                "marks": 1,
                "difficulty": "Easy",
                "bloom_level": "Remember",
                "explanation": f"{index + 1} + 1 equals {index + 2}.",
            }
        )
    return questions


def run_ui_smoke_test() -> bool:
    checks: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        message = f"{'PASS' if condition else 'FAIL'}  {name}"
        if detail and not condition:
            message += f" | {detail}"
        checks.append(message)
        print(message)

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"UI SELF-TEST SKIPPED: Tk could not start: {exc}")
        return False
    root.withdraw()

    window = None
    store = None
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = StudentStore(
                prefer_oracle=False, db_path=Path(tmp) / "analytics_ui.db"
            )
            student = store.register("analytics_ui", "Analytics UI", "study123")
            workspace_id = store.create_exam_workspace(
                student.id, "Mathematics", "Class 10", "2027-03-01", 100, 180
            )
            outline = [{"title": "Unit 1: Algebra", "topics": ["Algebra"]}]
            store.save_syllabus(
                student.id, workspace_id, "algebra.txt",
                "Algebra basics.\nAlgebra practice questions.", outline,
            )
            store.approve_syllabus(student.id, workspace_id, outline)
            questions = _algebra_questions(10)
            store.save_exam_content(
                student.id, workspace_id, "questions", questions
            )

            window = ExamPreparationWindow(root, store, student.id)
            window.window.update_idletasks()
            window.window.update()
            window._refresh_analytics()
            window.window.update_idletasks()

            tabs = {str(tab) for tab in window.notebook.tabs()}
            check(
                "analytics UI: workspace exposes an Analytics tab",
                str(window.analytics_tab) in tabs,
            )
            check(
                "exam UI: workspace opens fullscreen with a visible exit control",
                _is_fullscreen(window.window)
                and window.exit_btn.cget("text") == "EXIT CODELOCK",
            )
            check(
                "exam UI: syllabus upload offers PDF and Word documents first",
                exam_ui_module.UPLOAD_FILETYPES[0]
                == ("PDF or Word documents", "*.pdf *.docx")
                and any(
                    "*.pdf" in pattern and "*.docx" in pattern
                    for _, pattern in exam_ui_module.UPLOAD_FILETYPES
                ),
            )
            check(
                "exam UI: notes and question bank text use a 14-point font",
                tkfont.Font(font=window.notes_text.cget("font")).actual("size") == 14
                and tkfont.Font(font=window.questions_text.cget("font")).actual("size") == 14,
            )
            check(
                "analytics UI: range filters include 7 days, 30 days and all time",
                set(window.analytics_range_combo.cget("values"))
                == set(exam_analytics.RANGE_OPTIONS),
            )
            empty_rows = [
                window.analytics_topic_tree.item(iid, "values")
                for iid in window.analytics_topic_tree.get_children()
            ]
            check(
                "analytics UI: empty history shows not-started topics and no estimates",
                window._analytics_card_values["accuracy"][0].cget("text") == "—"
                and not window._analytics_buttons
                and "No submitted sessions" in window.recommendation_note.cget("text")
                and any(
                    row[0] == "Algebra"
                    and row[6] == exam_analytics.MASTERY_NOT_STARTED
                    for row in empty_rows
                ),
            )

            created = exam_engine.create_session(
                store, student.id, workspace_id, "practice", count=10, seed=5
            )
            session_id = created["session"]["session_id"]
            for response in created["responses"]:
                exam_engine.practice_check(
                    store, student.id, session_id, response["response_id"],
                    "1",
                )
            exam_engine.submit_session(store, student.id, session_id)

            window._refresh_history()
            window._refresh_analytics()
            window.window.update_idletasks()
            window.window.update()
            rows = [
                window.analytics_topic_tree.item(iid, "values")
                for iid in window.analytics_topic_tree.get_children()
            ]
            check(
                "analytics UI: submitted practice populates cards, chart and mastery",
                window._analytics_card_values["accuracy"][0].cget("text") == "0%"
                and window._analytics_card_values["sessions"][0].cget("text") == "1"
                and len(window.topic_chart.find_all()) > 0
                and len(window.session_chart.find_all()) > 0
                and len(window.type_chart.find_all()) > 0
                and len(window.bloom_chart.find_all()) > 0
                and any(
                    row[0] == "Algebra"
                    and row[6] == exam_analytics.MASTERY_NEEDS_IMPROVEMENT
                    for row in rows
                ),
            )
            check(
                "analytics UI: weak-topic recommendation has a practice action",
                len(window._analytics_buttons) == 1
                and window._analytics_buttons[0].cget("text") == "PRACTICE THIS TOPIC"
                and "at least 5 graded answers"
                in window.recommendation_note.cget("text"),
            )

            window.analytics_range.set("Last 7 Days")
            window._refresh_analytics()
            window.window.update_idletasks()
            check(
                "analytics UI: Last 7 Days uses the submitted session",
                window._analytics_card_values["sessions"][0].cget("text") == "1",
            )
            window.analytics_range.set("Last 30 Days")
            window._refresh_analytics()
            check(
                "analytics UI: Last 30 Days uses the submitted session",
                window._analytics_card_values["sessions"][0].cget("text") == "1",
            )
            window.analytics_range.set("All Time")
            window._refresh_analytics()
            check(
                "analytics UI: All Time uses the submitted session",
                window._analytics_card_values["sessions"][0].cget("text") == "1",
            )

            action = window._analytics_buttons[0]
            action.invoke()
            window.window.update_idletasks()
            runner = window._runner
            check(
                "analytics UI: Practice This Topic opens a topic-specific practice",
                runner is not None
                and runner.session.get("mode") == "practice"
                and bool(runner.responses)
                and all(
                    response.get("topic") == "Algebra"
                    for response in runner.responses
                ),
            )
            if runner is not None:
                check(
                    "exam UI: practice runner is fullscreen with a leave control",
                    _is_fullscreen(runner.window)
                    and runner.leave_btn.cget("text") == "LEAVE SESSION",
                )
                runner._abandon_and_close(notify=False)
                window._runner = None
            window._refresh_analytics()
            check(
                "analytics UI: abandoning that practice does not change submitted stats",
                window._analytics_card_values["sessions"][0].cget("text") == "1",
            )

            saved_questions = store.list_exam_questions(student.id, workspace_id)
            window.notes_text.delete("1.0", "end")
            window.notes_text.insert("1.0", "Unsaved revision note")
            window._save_draft()
            saved_notes = store.get_exam_workspace(
                student.id, workspace_id
            ).get("notes") or {}
            check(
                "exam UI: saving the syllabus draft preserves unsaved note edits",
                "Unsaved revision note"
                in window.notes_text.get("1.0", "end-1c")
                and not saved_notes.get("text"),
            )

            errors = []
            original_error = exam_ui_module.messagebox.showerror
            exam_ui_module.messagebox.showerror = (
                lambda title, message, **kwargs: errors.append(message)
            )
            try:
                window.questions_text.delete("1.0", "end")
                window.questions_text.insert("1.0", "[]")
                window._save_question_edits()
            finally:
                exam_ui_module.messagebox.showerror = original_error
            check(
                "exam UI: an empty question bank cannot erase saved questions",
                bool(errors)
                and "empty" in errors[0].casefold()
                and len(store.list_exam_questions(student.id, workspace_id))
                == len(saved_questions),
            )

            result_window = ExamResultWindow(
                root,
                {
                    "session": {"mode": "practice"},
                    "score": 1.0,
                    "total_marks": 1,
                    "percentage": 100.0,
                    "needs_review": 0,
                    "topics": [],
                    "responses": [],
                },
            )
            try:
                result_buttons = [
                    button
                    for container in result_window.window.winfo_children()
                    for button in container.winfo_children()
                    if isinstance(button, tk.Button)
                ]
                check(
                    "result UI: session result opens fullscreen with a close control",
                    _is_fullscreen(result_window.window)
                    and any(
                        button.cget("text") == "CLOSE"
                        for button in result_buttons
                    ),
                )
            finally:
                result_window.force_close()

            other_workspace = store.create_exam_workspace(
                student.id, "Physics", "Class 10", "2027-04-01", 100, 180
            )
            window._refresh_workspaces()
            other_label = next(
                label for label, value in window._workspace_items.items()
                if value == other_workspace
            )
            window.workspace_combo.set(other_label)
            original_ask = exam_ui_module.messagebox.askyesno
            exam_ui_module.messagebox.askyesno = lambda *args, **kwargs: False
            try:
                window._choose_workspace()
            finally:
                exam_ui_module.messagebox.askyesno = original_ask
            check(
                "exam UI: declining a workspace switch keeps the current workspace and edits",
                window.workspace_id == workspace_id
                and "Unsaved revision note"
                in window.notes_text.get("1.0", "end-1c"),
            )
            window._load_workspace(workspace_id)
    except Exception as exc:
        print(f"FAIL  analytics UI smoke test crashed | {type(exc).__name__}: {exc}")
        checks.append("FAIL")
    finally:
        try:
            if window is not None:
                window.shutdown()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass
        try:
            if store is not None:
                store.close()
        except Exception:
            pass

    passed = bool(checks) and all(item.startswith("PASS") for item in checks)
    print(
        "UI SELF-TEST PASSED: all checks passed."
        if passed else "UI SELF-TEST FAILED."
    )
    return passed
