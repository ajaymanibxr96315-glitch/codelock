"""Evidence-based performance analytics for submitted exam sessions.

Accuracy is calculated only from auto-marked objective answers. Written answers
waiting for review are reported separately and never counted as mistakes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

MIN_TOPIC_GRADED = 5
MIN_RECENT_GRADED = 3
RECENT_SESSION_WINDOW = 3
MIN_TYPE_GRADED = 3
MIN_TREND_SESSIONS = 2
MIN_TREND_GRADED = 5
MIN_TREND_SESSION_GRADED = 3
WEAK_ACCURACY = 60.0
CRITICAL_ACCURACY = 45.0
STRONG_ACCURACY = 75.0
RECENT_DROP = 15.0
TREND_DELTA = 5.0
MASTERY_MIN_GRADED = 8
MASTERY_ACCURACY = 80.0
MIN_MASTERY_COVERAGE = 0.8

RANGE_DAYS = {"Last 7 Days": 7, "Last 30 Days": 30, "All Time": None}
RANGE_OPTIONS = tuple(RANGE_DAYS)

GRADED_STATUSES = {"auto_correct", "auto_incorrect"}

TOPIC_STATUS_LABELS = {
    "not_started": "Not started",
    "insufficient_data": "Insufficient data",
    "critical": "Critical",
    "weak": "Weak",
    "developing": "Developing",
    "strong": "Strong",
}

MASTERY_NOT_STARTED = "Not Started"
MASTERY_LEARNING = "Learning"
MASTERY_NEEDS_IMPROVEMENT = "Needs Improvement"
MASTERY_MASTERED = "Mastered"


def _topic_name(value: object) -> str:
    name = str(value or "").strip()
    return name or "Unspecified"


def _bloom_name(value: object) -> str:
    name = str(value or "").strip()
    return name or "Unspecified"


def _as_utc(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except (TypeError, ValueError):
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _record_time(record: dict) -> datetime | None:
    return _as_utc(record.get("submitted_at")) or _as_utc(record.get("started_at"))


def apply_range_filter(
    records: list[dict], range_label: str, now: datetime | None = None
) -> list[dict]:
    """Keep records whose session was submitted inside the selected range."""
    days = RANGE_DAYS.get(range_label)
    if days is None:
        return list(records)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current.astimezone(timezone.utc) - timedelta(days=days)
    kept = []
    for record in records:
        submitted = _record_time(record)
        if submitted is not None and submitted >= cutoff:
            kept.append(record)
    return kept


def _graded(record: dict) -> bool:
    return record.get("review_status") in GRADED_STATUSES


def _attempted(record: dict) -> bool:
    return record.get("review_status") != "unanswered"


def _accuracy(correct: int, graded: int) -> float | None:
    return (correct / graded) * 100 if graded else None


def format_percent(value: float) -> str:
    """Show one decimal for non-round values so labels never contradict thresholds."""
    text = f"{value:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return text + "%"


def _group_sessions(records: list[dict]) -> list[dict]:
    sessions: dict[object, dict] = {}
    for record in records:
        session_id = record.get("session_id")
        entry = sessions.get(session_id)
        if entry is None:
            entry = {
                "session_id": session_id,
                "mode": str(record.get("mode") or ""),
                "total_marks": int(record.get("total_marks") or 0),
                "score_marks": float(record.get("score_marks") or 0),
                "stored_needs_review": int(record.get("needs_review") or 0),
                "started_at": record.get("started_at"),
                "submitted_at": record.get("submitted_at"),
                "responses": [],
                "_response_ids": set(),
            }
            sessions[session_id] = entry
        response_id = record.get("response_id")
        if response_id is not None:
            if response_id in entry["_response_ids"]:
                continue
            entry["_response_ids"].add(response_id)
        entry["responses"].append(record)

    grouped = list(sessions.values())
    grouped.sort(key=_session_sort_key)
    return grouped


def _session_sort_key(session: dict):
    stamp = _as_utc(session.get("submitted_at")) or _as_utc(session.get("started_at"))
    fallback = datetime.min.replace(tzinfo=timezone.utc)
    try:
        session_id = int(session.get("session_id") or 0)
    except (TypeError, ValueError):
        session_id = 0
    return (stamp or fallback, session_id)


def _session_summary(session: dict) -> dict:
    responses = session["responses"]
    graded = [record for record in responses if _graded(record)]
    correct = sum(1 for record in graded if record.get("review_status") == "auto_correct")
    attempted = sum(1 for record in responses if _attempted(record))
    needs_review = sum(
        1 for record in responses if record.get("review_status") == "needs_review"
    )
    total_marks = int(session.get("total_marks") or 0)
    score = float(session.get("score_marks") or 0)
    return {
        "session_id": session.get("session_id"),
        "mode": session.get("mode") or "",
        "started_at": session.get("started_at"),
        "submitted_at": session.get("submitted_at"),
        "total_marks": total_marks,
        "score": score,
        "score_percentage": (score / total_marks * 100) if total_marks else None,
        "attempted": attempted,
        "graded": len(graded),
        "correct": correct,
        "incorrect": len(graded) - correct,
        "needs_review": needs_review,
        "accuracy": _accuracy(correct, len(graded)),
        "score_is_partial": needs_review > 0,
    }


def _topic_stats(
    topics: list[str], sessions: list[dict]
) -> list[dict]:
    canonical = {topic.casefold(): topic for topic in topics}
    topic_map = {
        topic: {
            "topic": topic,
            "unit_title": "",
            "questions": 0,
            "attempted": 0,
            "graded": 0,
            "correct": 0,
            "incorrect": 0,
            "needs_review": 0,
            "unanswered": 0,
            "marks_total": 0,
            "marks_awarded": 0.0,
            "sessions": [],
        }
        for topic in topics
    }

    for session in sessions:
        per_topic: dict[str, list[dict]] = {}
        for record in session["responses"]:
            raw_name = _topic_name(record.get("topic"))
            name = canonical.get(raw_name.casefold(), raw_name)
            canonical.setdefault(name.casefold(), name)
            entry = topic_map.setdefault(
                name,
                {
                    "topic": name,
                    "unit_title": "",
                    "questions": 0,
                    "attempted": 0,
                    "graded": 0,
                    "correct": 0,
                    "incorrect": 0,
                    "needs_review": 0,
                    "unanswered": 0,
                    "marks_total": 0,
                    "marks_awarded": 0.0,
                    "sessions": [],
                },
            )
            if not entry["unit_title"] and record.get("unit_title"):
                entry["unit_title"] = str(record["unit_title"])
            entry["questions"] += 1
            entry["marks_total"] += max(1, int(record.get("marks") or 1))
            entry["marks_awarded"] += float(record.get("awarded_marks") or 0)
            status = record.get("review_status")
            if _attempted(record):
                entry["attempted"] += 1
            if status == "auto_correct":
                entry["correct"] += 1
                entry["graded"] += 1
            elif status == "auto_incorrect":
                entry["incorrect"] += 1
                entry["graded"] += 1
            elif status == "needs_review":
                entry["needs_review"] += 1
            else:
                entry["unanswered"] += 1
            per_topic.setdefault(name, []).append(record)
        for name, records in per_topic.items():
            topic_map[name]["sessions"].append(
                {
                    "session_id": session.get("session_id"),
                    "records": records,
                }
            )

    result = []
    for entry in topic_map.values():
        entry["accuracy"] = _accuracy(entry["correct"], entry["graded"])
        recent_sources = []
        recent_graded_count = 0
        for source in reversed(entry.pop("sessions")):
            if len(recent_sources) >= RECENT_SESSION_WINDOW:
                break
            recent_sources.append(source)
            recent_graded_count += sum(
                1 for record in source["records"] if _graded(record)
            )
            if recent_graded_count >= MIN_RECENT_GRADED:
                break
        recent_sources.reverse()
        recent_records = [
            record
            for source in recent_sources
            for record in source["records"]
            if _graded(record)
        ]
        entry["recent_graded"] = len(recent_records)
        recent_correct = sum(
            1 for record in recent_records
            if record.get("review_status") == "auto_correct"
        )
        entry["recent_accuracy"] = (
            _accuracy(recent_correct, len(recent_records))
            if len(recent_records) >= MIN_RECENT_GRADED
            else None
        )
        entry["recent_sessions"] = len(recent_sources)

        if entry["attempted"] == 0:
            status = "not_started"
        elif entry["graded"] < MIN_TOPIC_GRADED:
            status = "insufficient_data"
        elif entry["accuracy"] < CRITICAL_ACCURACY:
            status = "critical"
        elif entry["accuracy"] < WEAK_ACCURACY:
            status = "weak"
        elif entry["accuracy"] < STRONG_ACCURACY:
            status = "developing"
        else:
            status = "strong"
        entry["status"] = status
        entry["status_label"] = TOPIC_STATUS_LABELS[status]

        drop = None
        if entry["accuracy"] is not None and entry["recent_accuracy"] is not None:
            drop = entry["accuracy"] - entry["recent_accuracy"]
        entry["recent_drop"] = drop
        entry["declining"] = bool(
            status not in {"not_started", "insufficient_data"}
            and drop is not None
            and drop >= RECENT_DROP
        )

        entry["coverage"] = (
            entry["attempted"] / entry["questions"] if entry["questions"] else 0.0
        )
        if status == "not_started":
            mastery = MASTERY_NOT_STARTED
            evidence = "No submitted answers in the selected range."
        elif status in {"critical", "weak"} or entry["declining"]:
            mastery = MASTERY_NEEDS_IMPROVEMENT
            evidence = (
                f"{format_percent(entry['accuracy'])} accuracy across "
                f"{entry['graded']} graded answers."
            )
            if entry["declining"]:
                evidence += (
                    f" Recent accuracy {format_percent(entry['recent_accuracy'])} over "
                    f"{entry['recent_graded']} answers, down {drop:.0f} points."
                )
        elif (
            entry["graded"] >= MASTERY_MIN_GRADED
            and entry["accuracy"] >= MASTERY_ACCURACY
            and entry["coverage"] >= MIN_MASTERY_COVERAGE
        ):
            mastery = MASTERY_MASTERED
            evidence = (
                f"{format_percent(entry['accuracy'])} accuracy across "
                f"{entry['graded']} graded answers; "
                f"{format_percent(entry['coverage'] * 100)} of questions answered."
            )
        else:
            mastery = MASTERY_LEARNING
            if entry["graded"] < MASTERY_MIN_GRADED:
                if entry["needs_review"]:
                    evidence = (
                        f"{entry['needs_review']} answer(s) are awaiting manual "
                        "review; mastery cannot be judged yet."
                    )
                else:
                    evidence = (
                        f"{entry['graded']} of {MASTERY_MIN_GRADED} graded answers "
                        "needed before mastery can be judged."
                    )
            elif entry["accuracy"] < MASTERY_ACCURACY:
                evidence = (
                    f"{format_percent(entry['accuracy'])} accuracy; mastery requires "
                    f"{MASTERY_ACCURACY:.0f}% or better."
                )
            else:
                evidence = (
                    f"{format_percent(entry['accuracy'])} accuracy, but only "
                    f"{entry['attempted']} of {entry['questions']} questions were "
                    f"answered; mastery requires {MIN_MASTERY_COVERAGE * 100:.0f}% coverage."
                )
        entry["mastery"] = mastery
        entry["mastery_evidence"] = evidence
        result.append(entry)

    status_order = {
        "critical": 0,
        "weak": 1,
        "insufficient_data": 2,
        "developing": 3,
        "strong": 4,
        "not_started": 5,
    }
    result.sort(
        key=lambda item: (
            status_order.get(item["status"], 9),
            item["accuracy"] if item["accuracy"] is not None else 101,
            item["topic"].casefold(),
        )
    )
    return result


def _graded_breakdown(records: list[dict], key: str) -> list[dict]:
    groups: dict[str, dict] = {}
    for record in records:
        if not _graded(record):
            continue
        if key == "bloom":
            snapshot = record.get("snapshot") or {}
            name = _bloom_name(
                snapshot.get("bloom_level") or snapshot.get("bloom")
            )
        else:
            name = str(record.get("question_type") or "Unspecified").strip() or "Unspecified"
        entry = groups.setdefault(
            name,
            {"name": name, "graded": 0, "correct": 0, "incorrect": 0},
        )
        entry["graded"] += 1
        if record.get("review_status") == "auto_correct":
            entry["correct"] += 1
        else:
            entry["incorrect"] += 1

    result = []
    for entry in groups.values():
        entry["accuracy"] = _accuracy(entry["correct"], entry["graded"])
        if entry["graded"] < MIN_TYPE_GRADED:
            entry["status"] = "insufficient_data"
        elif entry["accuracy"] < CRITICAL_ACCURACY:
            entry["status"] = "critical"
        elif entry["accuracy"] < WEAK_ACCURACY:
            entry["status"] = "weak"
        elif entry["accuracy"] < STRONG_ACCURACY:
            entry["status"] = "developing"
        else:
            entry["status"] = "strong"
        entry["status_label"] = TOPIC_STATUS_LABELS[entry["status"]]
        result.append(entry)
    result.sort(
        key=lambda item: (
            item["accuracy"] if item["accuracy"] is not None else 101,
            -item["graded"],
            item["name"].casefold(),
        )
    )
    return result


def _hardest(entries: list[dict], exclude: str | None = None) -> dict | None:
    qualified = [
        entry for entry in entries
        if entry["graded"] >= MIN_TYPE_GRADED
        and entry["name"] != exclude
    ]
    if len(qualified) < 2:
        return None
    return qualified[0]


def _session_trend(sessions: list[dict]) -> dict:
    graded_sessions = [
        session for session in sessions
        if session["graded"] >= MIN_TREND_SESSION_GRADED
        and session["accuracy"] is not None
    ]
    total_graded = sum(session["graded"] for session in graded_sessions)
    if (
        len(graded_sessions) < MIN_TREND_SESSIONS
        or total_graded < MIN_TREND_GRADED
    ):
        return {
            "status": "insufficient_data",
            "label": "Not enough history",
            "delta": None,
            "latest_accuracy": graded_sessions[-1]["accuracy"] if graded_sessions else None,
            "previous_accuracy": None,
            "sessions_compared": len(graded_sessions),
            "evidence": (
                "A trend needs at least 2 submitted sessions with "
                f"{MIN_TREND_SESSION_GRADED}+ graded answers each and "
                f"{MIN_TREND_GRADED} graded answers in total. So far: "
                f"{len(graded_sessions)} eligible session(s), "
                f"{total_graded} graded answer(s)."
            ),
        }

    latest = graded_sessions[-1]
    previous = graded_sessions[:-1][-3:]
    previous_mean = sum(item["accuracy"] for item in previous) / len(previous)
    delta = latest["accuracy"] - previous_mean
    if delta >= TREND_DELTA:
        status, label = "improving", "Improving"
    elif delta <= -TREND_DELTA:
        status, label = "declining", "Declining"
    else:
        status, label = "steady", "Steady"
    return {
        "status": status,
        "label": label,
        "delta": delta,
        "latest_accuracy": latest["accuracy"],
        "previous_accuracy": previous_mean,
        "sessions_compared": len(previous) + 1,
        "evidence": (
            f"Latest session {format_percent(latest['accuracy'])} versus "
            f"{format_percent(previous_mean)} across the previous "
            f"{len(previous)} session(s)."
        ),
    }


def _recommendations(topics: list[dict], has_data: bool) -> tuple[list[dict], list[dict]]:
    recommendations = []
    for topic in topics:
        if topic["mastery"] != MASTERY_NEEDS_IMPROVEMENT:
            continue
        if topic["graded"] < MIN_TOPIC_GRADED:
            continue
        priority = 3
        if topic["status"] == "critical":
            priority = 1
        elif topic["declining"]:
            priority = 2
        reasons = [
            f"{format_percent(topic['accuracy'])} accuracy across "
            f"{topic['graded']} graded answers."
        ]
        if topic["declining"]:
            reasons.append(
                f"Recent accuracy is {format_percent(topic['recent_accuracy'])} "
                f"({topic['recent_graded']} answers), down "
                f"{topic['recent_drop']:.0f} points."
            )
        if topic["incorrect"]:
            reasons.append(f"{topic['incorrect']} graded answer(s) were wrong.")
        recommendations.append(
            {
                "topic": topic["topic"],
                "priority": priority,
                "priority_label": (
                    "Critical" if priority == 1
                    else "Declining" if priority == 2
                    else "Weak"
                ),
                "accuracy": topic["accuracy"],
                "graded": topic["graded"],
                "incorrect": topic["incorrect"],
                "recent_accuracy": topic["recent_accuracy"],
                "reason": " ".join(reasons),
                "action": (
                    f"Start a 10-question practice session on "
                    f"{topic['topic']}, then review the explanations for "
                    "the answers you miss."
                ),
            }
        )
    recommendations.sort(
        key=lambda item: (
            item["priority"],
            item["accuracy"] if item["accuracy"] is not None else 101,
            item["topic"].casefold(),
        )
    )

    evidence_needed = [
        {
            "topic": topic["topic"],
            "graded": topic["graded"],
            "needed": max(0, MIN_TOPIC_GRADED - topic["graded"]),
            "mastery": topic["mastery"],
            "note": (
                "No submitted answers yet."
                if topic["attempted"] == 0
                else (
                    f"{topic['graded']} graded answer(s); "
                    f"{max(0, MIN_TOPIC_GRADED - topic['graded'])} more needed "
                    "before weakness can be judged."
                )
            ),
        }
        for topic in topics
        if topic["mastery"] != MASTERY_NEEDS_IMPROVEMENT
        and topic["graded"] < MIN_TOPIC_GRADED
        and topic["attempted"] > 0
    ]
    if not has_data:
        return [], evidence_needed
    return recommendations[:5], evidence_needed


def build_dashboard(
    records: list[dict],
    syllabus_topics: list[str] | tuple[str, ...] = (),
    subject: str = "",
    range_label: str = "All Time",
    now: datetime | None = None,
) -> dict:
    if range_label not in RANGE_DAYS:
        range_label = "All Time"
    filtered = apply_range_filter(records, range_label, now=now)
    sessions = _group_sessions(filtered)
    summaries = [_session_summary(session) for session in sessions]

    topics: list[str] = []
    seen: set[str] = set()
    for name in list(syllabus_topics) + [
        _topic_name(record.get("topic")) for record in filtered
    ]:
        clean = _topic_name(name)
        if clean.casefold() not in seen:
            seen.add(clean.casefold())
            topics.append(clean)
    topic_stats = _topic_stats(topics, sessions)

    graded_records = [record for record in filtered if _graded(record)]
    correct = sum(
        1 for record in graded_records
        if record.get("review_status") == "auto_correct"
    )
    attempted = sum(1 for record in filtered if _attempted(record))
    needs_review = sum(
        1 for record in filtered
        if record.get("review_status") == "needs_review"
    )
    question_types = _graded_breakdown(filtered, "type")
    bloom_levels = _graded_breakdown(filtered, "bloom")
    trend = _session_trend(summaries)
    has_data = bool(sessions)
    recommendations, evidence_needed = _recommendations(topic_stats, has_data)

    weak_topics = [
        topic for topic in topic_stats
        if topic["mastery"] == MASTERY_NEEDS_IMPROVEMENT
        and topic["graded"] >= MIN_TOPIC_GRADED
    ]

    days = RANGE_DAYS[range_label]
    range_start = None
    if days is not None:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        range_start = (
            current.astimezone(timezone.utc) - timedelta(days=days)
        ).isoformat(timespec="seconds")

    notes = [
        "Accuracy uses auto-marked objective answers only. "
        "Written answers awaiting review are excluded, not counted as wrong.",
        "Marks are auto-marked awards; questions awaiting review are not yet credited.",
        f"Topics with fewer than {MIN_TOPIC_GRADED} graded answers are marked "
        "insufficient; their accuracy is shown for information only (*).",
        "Mastery reflects the selected date range: Mastered requires at least "
        f"{MASTERY_MIN_GRADED} graded answers at {MASTERY_ACCURACY:.0f}% or better "
        f"and {MIN_MASTERY_COVERAGE * 100:.0f}% of questions answered.",
        f"Trends ignore sessions with fewer than {MIN_TREND_SESSION_GRADED} "
        "graded answers so a single answer cannot reverse the trend.",
    ]
    if needs_review:
        notes.append(
            f"{needs_review} written answer(s) are awaiting manual review and "
            "are not included in accuracy."
        )
    if not has_data:
        notes.insert(
            0,
            "No submitted sessions in the selected range. Complete a practice "
            "or mock exam to unlock analytics; nothing is estimated.",
        )
    elif not graded_records:
        notes.append(
            "No auto-graded objective answers yet, so accuracy and weakness "
            "cannot be judged."
        )

    return {
        "subject": subject,
        "range_label": range_label,
        "range_days": days,
        "range_start": range_start,
        "has_data": has_data,
        "session_count": len(summaries),
        "practice_sessions": sum(
            1 for session in summaries if session["mode"] == "practice"
        ),
        "mock_sessions": sum(
            1 for session in summaries if session["mode"] == "mock"
        ),
        "questions_attempted": attempted,
        "questions_total": len(filtered),
        "graded_answers": len(graded_records),
        "correct": correct,
        "incorrect": len(graded_records) - correct,
        "needs_review": needs_review,
        "accuracy": _accuracy(correct, len(graded_records)),
        "marks_awarded": sum(
            float(record.get("awarded_marks") or 0) for record in filtered
        ),
        "marks_total": sum(
            max(1, int(record.get("marks") or 1)) for record in filtered
        ),
        "sessions": summaries,
        "topics": topic_stats,
        "weak_topics": weak_topics,
        "recommendations": recommendations,
        "evidence_needed": evidence_needed,
        "question_types": question_types,
        "bloom_levels": bloom_levels,
        "hardest_question_type": _hardest(question_types),
        "hardest_bloom_level": _hardest(bloom_levels, exclude="Unspecified"),
        "trend": trend,
        "notes": notes,
    }
