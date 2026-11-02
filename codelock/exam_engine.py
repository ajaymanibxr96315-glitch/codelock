"""Practice and mock exam sessions with deterministic objective scoring."""

from __future__ import annotations

import math
import random
import re
from datetime import datetime, timezone

from .db import StudentStore, StoreError

MCQ = "Multiple Choice"
TRUE_FALSE = "True Or False"
FILL_BLANKS = "Fill In The Blanks"
ONE_WORD = "One-Word Answer"
SUBJECTIVE_TYPES = {
    "Short Answer",
    "Long Answer",
    "Practical",
    "Programming",
    "Viva",
}
OBJECTIVE_TYPES = {MCQ, TRUE_FALSE, FILL_BLANKS, ONE_WORD}
DIFFICULTIES = {"Beginner", "Easy", "Medium", "Hard"}

_TRUE_VALUES = {"true", "t", "yes", "y", "1", "correct"}
_FALSE_VALUES = {"false", "f", "no", "n", "0", "incorrect"}
_OPTION_LABELS = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4}


class ExamError(ValueError):
    """A practice or mock session cannot be created or scored."""


def normalize_text(value: object) -> str:
    text = str(value or "").strip().casefold()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,;:!?\"'")


def _alternatives(answer: str) -> list[str]:
    parts = re.split(r"\s*[|;]\s*", str(answer))
    return [normalize_text(part) for part in parts if normalize_text(part)]


def _as_number(value: object) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_boolean(value: object) -> bool | None:
    text = normalize_text(value)
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    return None


def _option_index(value: str, options: list[str]) -> int | None:
    text = normalize_text(value)
    if text in _OPTION_LABELS:
        return _OPTION_LABELS[text]
    if text.isdigit():
        index = int(text) - 1
        return index if 0 <= index < len(options) else None
    for index, option in enumerate(options):
        if normalize_text(option) == text:
            return index
    return None


def score_answer(
    question_type: str,
    expected: str,
    given: str,
    options: list[str] | None = None,
) -> bool | None:
    """Return True/False for objective answers, or None when review is needed."""
    if not str(given or "").strip():
        return None
    kind = str(question_type or "").strip()
    options = [str(option) for option in (options or []) if str(option).strip()]

    if kind == MCQ:
        if normalize_text(expected) == normalize_text(given):
            return True
        if options:
            expected_index = _option_index(expected, options)
            given_index = _option_index(given, options)
            return (
                expected_index is not None
                and given_index is not None
                and expected_index == given_index
            )
        return False

    if kind == TRUE_FALSE:
        expected_value = _parse_boolean(expected)
        given_value = _parse_boolean(given)
        if expected_value is None:
            return False
        if given_value is None:
            return False
        return expected_value == given_value

    if kind in {FILL_BLANKS, ONE_WORD}:
        given_text = normalize_text(given)
        if given_text in _alternatives(expected):
            return True
        expected_number = _as_number(expected)
        given_number = _as_number(given)
        if expected_number is not None and given_number is not None:
            return math.isclose(expected_number, given_number, rel_tol=1e-9, abs_tol=1e-9)
        return False

    return None


def _elapsed_seconds(started_at) -> float:
    if isinstance(started_at, datetime):
        started = started_at
    else:
        try:
            started = datetime.fromisoformat(started_at)
        except (TypeError, ValueError):
            return 0.0
    now = datetime.now() if started.tzinfo is None else datetime.now(timezone.utc)
    return max(0.0, (now - started).total_seconds())


def remaining_seconds(session: dict) -> float | None:
    limit = int(session.get("duration_limit_seconds") or 0)
    if limit <= 0:
        return None
    started = session.get("started_at")
    return max(0.0, limit - _elapsed_seconds(started))


def _select_questions(
    questions: list[dict],
    mode: str,
    count: int,
    target_marks: int | None,
    rng: random.Random,
) -> tuple[list[dict], str]:
    pool = list(questions)
    rng.shuffle(pool)
    if mode == "practice":
        selected = pool[:count]
        notice = ""
        if len(selected) < count:
            notice = f"Only {len(selected)} matching question(s) were available."
        return selected, notice

    selected: list[dict] = []
    marks = 0
    for question in pool:
        if len(selected) >= count:
            break
        selected.append(question)
        marks += max(1, int(question.get("marks", 1)))
        if target_marks and marks >= target_marks:
            break
    notice = ""
    if target_marks and marks < target_marks:
        notice = (
            f"The question bank totals {marks} marks; the requested target was "
            f"{target_marks}."
        )
    return selected, notice


def create_session(
    store: StudentStore,
    student_id: int,
    workspace_id: int,
    mode: str,
    *,
    count: int = 10,
    topics: list[str] | None = None,
    difficulty: str | None = None,
    duration_minutes: int = 0,
    target_marks: int | None = None,
    seed: int | None = None,
) -> dict:
    if mode not in {"practice", "mock"}:
        raise ExamError("Choose practice or mock mode.")
    count = int(count)
    if not 1 <= count <= 100:
        raise ExamError("Question count must be between 1 and 100.")
    if duration_minutes and not 1 <= int(duration_minutes) <= 600:
        raise ExamError("Mock duration must be between 1 and 600 minutes.")
    if target_marks is not None and not 1 <= int(target_marks) <= 1_000_000:
        raise ExamError("Target marks must be between 1 and 1,000,000.")

    try:
        store.sync_question_bank(student_id, workspace_id)
        questions = store.list_exam_questions(student_id, workspace_id)
    except StoreError as exc:
        raise ExamError(str(exc)) from exc
    if not questions:
        raise ExamError(
            "The question bank is empty. Generate or save approved questions first."
        )

    topic_filter = {
        str(topic).strip().casefold() for topic in (topics or []) if str(topic).strip()
    }
    if topic_filter:
        questions = [
            question
            for question in questions
            if str(question.get("topic", "")).casefold() in topic_filter
        ]
    if difficulty and difficulty.casefold() != "any":
        questions = [
            question
            for question in questions
            if str(question.get("difficulty", "")).casefold() == difficulty.casefold()
        ]
    if not questions:
        raise ExamError("No questions match the selected topic and difficulty.")

    rng = random.Random(seed)
    selected, notice = _select_questions(
        questions, mode, count, int(target_marks) if target_marks else None, rng
    )
    if not selected:
        raise ExamError("No questions could be selected.")

    blueprint = {
        "mode": mode,
        "count": count,
        "topics": sorted(topic_filter),
        "difficulty": difficulty or "Any",
        "duration_minutes": int(duration_minutes or 0),
        "target_marks": int(target_marks) if target_marks else None,
        "notice": notice,
    }
    try:
        session_id = store.create_exam_session(
            student_id,
            workspace_id,
            mode,
            selected,
            blueprint,
            int(duration_minutes or 0) * 60 if mode == "mock" else 0,
        )
    except StoreError as exc:
        raise ExamError(str(exc)) from exc
    session = store.get_exam_session(student_id, session_id)
    if session is None:
        raise ExamError("The exam session could not be loaded after creation.")
    return {
        "session": session,
        "responses": store.list_exam_responses(student_id, session_id),
        "notice": notice,
    }


def practice_check(
    store: StudentStore,
    student_id: int,
    session_id: int,
    response_id: int,
    answer: str,
) -> dict:
    session = store.get_exam_session(student_id, session_id)
    if session is None:
        raise ExamError("That practice session no longer exists.")
    if session["status"] != "in_progress":
        raise ExamError("This practice session has already finished.")
    response = next(
        (
            item
            for item in store.list_exam_responses(student_id, session_id)
            if int(item["response_id"]) == int(response_id)
        ),
        None,
    )
    if response is None:
        raise ExamError("That question does not belong to this session.")

    snapshot = response["snapshot"]
    correct = score_answer(
        response["question_type"],
        snapshot.get("answer", ""),
        answer,
        snapshot.get("options", []),
    )
    marks = max(1, int(response["marks"]))
    if correct is None:
        status = "needs_review"
        awarded = 0.0
    else:
        status = "auto_correct" if correct else "auto_incorrect"
        awarded = float(marks) if correct else 0.0
    saved = store.save_exam_response(
        student_id,
        session_id,
        response_id,
        answer,
        correct,
        awarded,
        status,
    )
    if not saved:
        raise ExamError("The answer could not be saved; the session may have ended.")
    return {
        "is_correct": correct,
        "status": status,
        "awarded_marks": awarded,
        "marks": marks,
        "correct_answer": snapshot.get("answer", ""),
        "explanation": snapshot.get("explanation", ""),
    }


def topic_breakdown(responses: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for response in responses:
        topic = str(response.get("topic") or "Unspecified").strip() or "Unspecified"
        entry = groups.setdefault(
            topic,
            {
                "topic": topic,
                "questions": 0,
                "answered": 0,
                "correct": 0,
                "incorrect": 0,
                "needs_review": 0,
                "unanswered": 0,
                "marks": 0,
                "awarded": 0.0,
            },
        )
        entry["questions"] += 1
        entry["marks"] += max(1, int(response.get("marks", 1)))
        entry["awarded"] += float(response.get("awarded_marks", 0) or 0)
        if str(response.get("student_answer", "")).strip():
            entry["answered"] += 1
        status = response.get("review_status")
        if status == "auto_correct":
            entry["correct"] += 1
        elif status == "auto_incorrect":
            entry["incorrect"] += 1
        elif status == "needs_review":
            entry["needs_review"] += 1
        else:
            entry["unanswered"] += 1

    result = []
    for entry in groups.values():
        graded = entry["correct"] + entry["incorrect"]
        entry["accuracy"] = (
            (entry["correct"] / graded) * 100 if graded else None
        )
        result.append(entry)
    result.sort(key=lambda item: (-item["questions"], item["topic"].casefold()))
    return result


def session_result(
    store: StudentStore, student_id: int, session_id: int
) -> dict:
    session = store.get_exam_session(student_id, session_id)
    if session is None:
        raise ExamError("That exam session no longer exists.")
    responses = store.list_exam_responses(student_id, session_id)
    topics = topic_breakdown(responses)
    total = max(0, int(session.get("total_marks") or 0))
    score = float(session.get("score_marks") or 0)
    return {
        "session": session,
        "responses": responses,
        "topics": topics,
        "score": score,
        "total_marks": total,
        "percentage": (score / total * 100) if total else 0.0,
        "needs_review": int(session.get("needs_review") or 0),
    }


def submit_session(
    store: StudentStore,
    student_id: int,
    session_id: int,
    elapsed_seconds: float | None = None,
) -> dict:
    session = store.get_exam_session(student_id, session_id)
    if session is None:
        raise ExamError("That exam session no longer exists.")
    if session["status"] != "in_progress":
        return session_result(store, student_id, session_id)

    responses = store.list_exam_responses(student_id, session_id)
    score = 0.0
    needs_review = 0
    for response in responses:
        snapshot = response["snapshot"]
        answer = str(response.get("student_answer", "") or "")
        if not answer.strip():
            store.save_exam_response(
                student_id,
                session_id,
                response["response_id"],
                "",
                None,
                0.0,
                "unanswered",
            )
            continue
        correct = score_answer(
            response["question_type"],
            snapshot.get("answer", ""),
            answer,
            snapshot.get("options", []),
        )
        marks = max(1, int(response["marks"]))
        if correct is None:
            needs_review += 1
            store.save_exam_response(
                student_id,
                session_id,
                response["response_id"],
                answer,
                None,
                0.0,
                "needs_review",
            )
        else:
            awarded = float(marks) if correct else 0.0
            score += awarded
            store.save_exam_response(
                student_id,
                session_id,
                response["response_id"],
                answer,
                correct,
                awarded,
                "auto_correct" if correct else "auto_incorrect",
            )

    elapsed = (
        float(elapsed_seconds)
        if elapsed_seconds is not None
        else _elapsed_seconds(session.get("started_at", ""))
    )
    store.finish_exam_session(student_id, session_id, score, needs_review, elapsed)
    return session_result(store, student_id, session_id)


def abandon_session(store: StudentStore, student_id: int, session_id: int) -> bool:
    return store.abandon_exam_session(student_id, session_id)
