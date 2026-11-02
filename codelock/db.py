"""Student accounts, attempt history and per-track progress.

Oracle is the intended backend: `database/schema.sql` creates the tables and the
`codelock_api` PL/SQL package that this module calls. When Oracle is not
configured (or unreachable) the same interface runs on a local SQLite file so the
app still works offline. Passwords are hashed with PBKDF2-SHA256 in Python; the
database never sees a plaintext password.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from . import config

try:
    import oracledb
except ImportError:  # optional: only needed for the Oracle backend
    oracledb = None

PBKDF2_ITERATIONS = 200_000
USERNAME_PATTERN = re.compile(r"^[a-z0-9_-]{3,24}$")


class StoreError(Exception):
    """A user-facing account or progress failure."""


@dataclass(frozen=True)
class Student:
    id: int
    username: str
    display_name: str


@dataclass(frozen=True)
class Progress:
    track_key: str
    current_index: int = 0
    completed: int = 0
    attempts: int = 0
    total_seconds: float = 0.0
    best_seconds: float | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash_password(password: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), PBKDF2_ITERATIONS
    ).hex()


class StudentStore:
    """Account and progress API shared by the Oracle and SQLite backends."""

    def __init__(self, prefer_oracle: bool = True, db_path: str | Path | None = None) -> None:
        self.backend_warning = ""
        self._backend: "SQLiteBackend | OracleBackend"

        if prefer_oracle and config.ORACLE_DSN and oracledb is not None:
            try:
                self._backend = OracleBackend()
                self.backend_name = "Oracle (PL/SQL)"
                return
            except Exception as exc:  # connection/config problems fall back
                self.backend_warning = (
                    f"Oracle is unavailable ({type(exc).__name__}: {exc}). "
                    "Progress will use the local SQLite database instead."
                )
        elif prefer_oracle and config.ORACLE_DSN and oracledb is None:
            self.backend_warning = (
                "CODELOCK_ORACLE_DSN is set but the oracledb package is not "
                "installed. Progress will use the local SQLite database instead."
            )

        self._backend = SQLiteBackend(Path(db_path or config.DB_PATH))
        self.backend_name = "SQLite (local)"

    # ----------------------------------------------------------------- public
    def register(self, username: str, display_name: str, password: str) -> Student:
        username = (username or "").strip().lower()
        display_name = (display_name or "").strip() or username
        self._validate_username(username)
        self._validate_password(password)
        if len(display_name) > 60:
            display_name = display_name[:60]
        salt = secrets.token_hex(16)
        password_hash = _hash_password(password, salt)
        try:
            return self._backend.register(username, display_name, password_hash, salt)
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"Could not create the account: {exc}") from exc

    def login(self, username: str, password: str) -> Student:
        username = (username or "").strip().lower()
        if not username or not password:
            raise StoreError("Enter both a username and a password.")
        try:
            credentials = self._backend.credentials(username)
        except Exception as exc:
            raise StoreError(f"Could not check the account: {exc}") from exc
        if credentials is None:
            raise StoreError("Unknown username or wrong password.")
        student, password_hash, salt = credentials
        candidate = _hash_password(password, salt)
        if not hmac.compare_digest(candidate, password_hash):
            raise StoreError("Unknown username or wrong password.")
        try:
            self._backend.touch_login(student.id)
        except Exception as exc:
            raise StoreError(f"Could not update the login time: {exc}") from exc
        return student

    def get_progress(self, student_id: int, track_key: str) -> Progress:
        try:
            return self._backend.get_progress(student_id, track_key)
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"Could not load progress: {exc}") from exc

    def record_attempt(
        self,
        student_id: int,
        track_key: str,
        problem_key: str,
        duration_seconds: float,
        passed: bool,
        tests_passed: int,
        tests_total: int,
        next_index: int,
    ) -> None:
        duration = float(duration_seconds)
        if not math.isfinite(duration) or duration < 0:
            duration = 0.0
        try:
            self._backend.record_attempt(
                student_id,
                track_key,
                problem_key,
                duration,
                bool(passed),
                max(0, int(tests_passed)),
                max(0, int(tests_total)),
                max(0, int(next_index)),
            )
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"Could not save the attempt: {exc}") from exc

    def create_exam_workspace(
        self, student_id: int, subject: str, course_level: str,
        exam_date: str, total_marks: int, duration_minutes: int,
    ) -> int:
        subject = (subject or "").strip()
        course_level = (course_level or "").strip()
        exam_date = (exam_date or "").strip()
        if not subject or len(subject) > 160:
            raise StoreError("Subject name must be between 1 and 160 characters.")
        if len(course_level) > 120:
            raise StoreError("Course or level must be 120 characters or fewer.")
        if exam_date:
            try:
                date.fromisoformat(exam_date)
            except ValueError as exc:
                raise StoreError("Examination date must use YYYY-MM-DD.") from exc
        if not 1 <= int(total_marks) <= 1_000_000:
            raise StoreError("Total marks must be between 1 and 1,000,000.")
        if not 1 <= int(duration_minutes) <= 10_000:
            raise StoreError("Duration must be between 1 and 10,000 minutes.")
        try:
            return self._backend.create_exam_workspace(
                student_id, subject.strip(), course_level.strip(), exam_date,
                int(total_marks), int(duration_minutes),
            )
        except Exception as exc:
            raise StoreError(f"Could not create the examination workspace: {exc}") from exc

    def list_exam_workspaces(self, student_id: int) -> list[dict]:
        try:
            return self._backend.list_exam_workspaces(student_id)
        except Exception as exc:
            raise StoreError(f"Could not load examination workspaces: {exc}") from exc

    def get_exam_workspace(self, student_id: int, workspace_id: int) -> dict | None:
        try:
            row = self._backend.get_exam_workspace(student_id, workspace_id)
            if row is None:
                return None
            for key in ("topics", "notes", "questions"):
                try:
                    row[key] = json.loads(row.pop(f"{key}_json") or "[]")
                except (TypeError, json.JSONDecodeError):
                    row[key] = []
            return row
        except Exception as exc:
            raise StoreError(f"Could not load the examination workspace: {exc}") from exc

    def save_syllabus(
        self, student_id: int, workspace_id: int, filename: str,
        source_text: str, topics: list[dict],
    ) -> bool:
        from .exam import validate_topic_tree

        topics = validate_topic_tree(topics, require_topics=False)
        try:
            return bool(self._backend.save_syllabus(
                student_id, workspace_id, filename, source_text,
                json.dumps(topics, ensure_ascii=False),
            ))
        except Exception as exc:
            raise StoreError(f"Could not save the extracted syllabus: {exc}") from exc

    def approve_syllabus(self, student_id: int, workspace_id: int, topics: list[dict]) -> bool:
        from .exam import validate_topic_tree

        topics = validate_topic_tree(topics)
        try:
            return self._backend.approve_syllabus(
                student_id, workspace_id, json.dumps(topics, ensure_ascii=False)
            )
        except Exception as exc:
            raise StoreError(f"Could not approve the syllabus: {exc}") from exc

    def save_exam_content(
        self, student_id: int, workspace_id: int, kind: str, content: list | dict,
    ) -> bool:
        if kind not in {"notes", "questions"}:
            raise StoreError("Unsupported exam content type.")
        try:
            return self._backend.save_exam_content(
                student_id, workspace_id, kind, json.dumps(content, ensure_ascii=False)
            )
        except Exception as exc:
            raise StoreError(f"Could not save generated {kind}: {exc}") from exc

    def sync_question_bank(self, student_id: int, workspace_id: int) -> int:
        try:
            return self._backend.sync_question_bank(student_id, workspace_id)
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"Could not prepare the question bank: {exc}") from exc

    def list_exam_questions(self, student_id: int, workspace_id: int) -> list[dict]:
        try:
            return self._backend.list_exam_questions(student_id, workspace_id)
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"Could not load the question bank: {exc}") from exc

    def create_exam_session(
        self,
        student_id: int,
        workspace_id: int,
        mode: str,
        questions: list[dict],
        blueprint: dict,
        duration_limit_seconds: int = 0,
    ) -> int:
        if mode not in {"practice", "mock"}:
            raise StoreError("Exam mode must be practice or mock.")
        if not questions or not isinstance(questions, list):
            raise StoreError("Select at least one question before starting.")
        if any(not isinstance(item, dict) or "question_id" not in item for item in questions):
            raise StoreError("The selected question list is invalid.")
        question_ids = [int(item["question_id"]) for item in questions]
        if len(question_ids) != len(set(question_ids)):
            raise StoreError("The selected question list contains duplicates.")
        workspace = self.get_exam_workspace(student_id, workspace_id)
        if workspace is None or not workspace.get("syllabus_approved"):
            raise StoreError("Select an approved workspace before starting a session.")
        active_ids = {
            int(item["question_id"])
            for item in self.list_exam_questions(student_id, workspace_id)
        }
        if any(question_id not in active_ids for question_id in question_ids):
            raise StoreError(
                "The selected questions no longer belong to this workspace."
            )
        duration = max(0, int(duration_limit_seconds))
        try:
            return self._backend.create_exam_session(
                student_id,
                workspace_id,
                mode,
                questions,
                json.dumps(blueprint, ensure_ascii=False),
                duration,
            )
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"Could not start the exam session: {exc}") from exc

    def get_exam_session(self, student_id: int, session_id: int) -> dict | None:
        try:
            return self._backend.get_exam_session(student_id, session_id)
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"Could not load the exam session: {exc}") from exc

    def list_exam_sessions(
        self, student_id: int, workspace_id: int | None = None
    ) -> list[dict]:
        try:
            return self._backend.list_exam_sessions(student_id, workspace_id)
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"Could not load exam history: {exc}") from exc

    def list_exam_responses(self, student_id: int, session_id: int) -> list[dict]:
        try:
            return self._backend.list_exam_responses(student_id, session_id)
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"Could not load exam answers: {exc}") from exc

    def list_exam_analytics_records(
        self, student_id: int, workspace_id: int | None = None
    ) -> list[dict]:
        try:
            return self._backend.list_exam_analytics_records(student_id, workspace_id)
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"Could not load performance history: {exc}") from exc

    def save_exam_response(
        self,
        student_id: int,
        session_id: int,
        response_id: int,
        answer: str,
        is_correct: bool | None = None,
        awarded_marks: float = 0.0,
        review_status: str = "unanswered",
    ) -> bool:
        answer = "" if answer is None else str(answer)
        if len(answer) > 20_000:
            raise StoreError("An answer cannot exceed 20,000 characters.")
        if review_status not in {
            "unanswered",
            "auto_correct",
            "auto_incorrect",
            "needs_review",
        }:
            raise StoreError("Unknown answer review status.")
        marks = float(awarded_marks)
        if not math.isfinite(marks) or marks < 0:
            marks = 0.0
        try:
            return self._backend.save_exam_response(
                student_id,
                session_id,
                response_id,
                answer,
                None if is_correct is None else bool(is_correct),
                marks,
                review_status,
            )
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"Could not save the answer: {exc}") from exc

    def finish_exam_session(
        self,
        student_id: int,
        session_id: int,
        score_marks: float,
        needs_review: int,
        elapsed_seconds: float,
    ) -> bool:
        score = float(score_marks)
        elapsed = float(elapsed_seconds)
        if not math.isfinite(score) or score < 0:
            score = 0.0
        if not math.isfinite(elapsed) or elapsed < 0:
            elapsed = 0.0
        try:
            return self._backend.finish_exam_session(
                student_id,
                session_id,
                score,
                max(0, int(needs_review)),
                elapsed,
            )
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"Could not submit the exam session: {exc}") from exc

    def abandon_exam_session(self, student_id: int, session_id: int) -> bool:
        try:
            return self._backend.abandon_exam_session(student_id, session_id)
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"Could not close the exam session: {exc}") from exc

    def close(self) -> None:
        self._backend.close()

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _validate_username(username: str) -> None:
        if not USERNAME_PATTERN.match(username):
            raise StoreError(
                "Username must be 3-24 characters using letters, numbers, '_' or '-'."
            )

    @staticmethod
    def _validate_password(password: str) -> None:
        if not password or len(password) < 6:
            raise StoreError("Password must be at least 6 characters.")
        if len(password) > 128:
            raise StoreError("Password must be 128 characters or fewer.")


class SQLiteBackend:
    """Local fallback that mirrors the Oracle tables."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_login TEXT
            );
            CREATE TABLE IF NOT EXISTS progress (
                student_id INTEGER NOT NULL,
                track_key TEXT NOT NULL,
                current_index INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                total_seconds REAL NOT NULL DEFAULT 0,
                best_seconds REAL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (student_id, track_key),
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                track_key TEXT NOT NULL,
                problem_key TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                passed INTEGER NOT NULL,
                tests_passed INTEGER NOT NULL DEFAULT 0,
                tests_total INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_attempts_student
                ON attempts(student_id, created_at);
            CREATE TABLE IF NOT EXISTS exam_workspaces (
                workspace_id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                course_level TEXT NOT NULL DEFAULT '',
                exam_date TEXT NOT NULL DEFAULT '',
                total_marks INTEGER NOT NULL DEFAULT 100,
                duration_minutes INTEGER NOT NULL DEFAULT 180,
                syllabus_filename TEXT NOT NULL DEFAULT '',
                source_text TEXT NOT NULL DEFAULT '',
                topics_json TEXT NOT NULL DEFAULT '[]',
                syllabus_approved INTEGER NOT NULL DEFAULT 0,
                notes_json TEXT NOT NULL DEFAULT '[]',
                questions_json TEXT NOT NULL DEFAULT '[]',
                question_bank_fingerprint TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_exam_workspaces_student
                ON exam_workspaces(student_id, updated_at);
            CREATE TABLE IF NOT EXISTS exam_questions (
                question_id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                unit_title TEXT NOT NULL DEFAULT '',
                topic TEXT NOT NULL,
                question_type TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                bloom_level TEXT NOT NULL,
                marks INTEGER NOT NULL,
                prompt TEXT NOT NULL,
                options_json TEXT NOT NULL DEFAULT '[]',
                answer TEXT NOT NULL,
                explanation TEXT NOT NULL DEFAULT '',
                source_quote TEXT NOT NULL DEFAULT '',
                source_kind TEXT NOT NULL DEFAULT 'ai',
                source_ref TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES exam_workspaces(workspace_id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_exam_questions_workspace
                ON exam_questions(workspace_id, is_active, topic);
            CREATE TABLE IF NOT EXISTS exam_sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                workspace_id INTEGER NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'in_progress',
                blueprint_json TEXT NOT NULL DEFAULT '{}',
                total_marks INTEGER NOT NULL DEFAULT 0,
                score_marks REAL NOT NULL DEFAULT 0,
                needs_review INTEGER NOT NULL DEFAULT 0,
                duration_limit_seconds INTEGER NOT NULL DEFAULT 0,
                elapsed_seconds REAL NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                submitted_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
                FOREIGN KEY (workspace_id) REFERENCES exam_workspaces(workspace_id) ON DELETE CASCADE,
                CONSTRAINT ck_exam_sessions_mode CHECK (mode IN ('practice', 'mock')),
                CONSTRAINT ck_exam_sessions_status
                    CHECK (status IN ('in_progress', 'submitted', 'abandoned'))
            );
            CREATE INDEX IF NOT EXISTS idx_exam_sessions_student
                ON exam_sessions(student_id, workspace_id, created_at);
            CREATE TABLE IF NOT EXISTS exam_responses (
                response_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                workspace_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                unit_title TEXT NOT NULL DEFAULT '',
                topic TEXT NOT NULL,
                question_type TEXT NOT NULL,
                marks INTEGER NOT NULL,
                student_answer TEXT NOT NULL DEFAULT '',
                is_correct INTEGER,
                awarded_marks REAL NOT NULL DEFAULT 0,
                review_status TEXT NOT NULL DEFAULT 'unanswered',
                question_snapshot_json TEXT NOT NULL,
                answered_at TEXT,
                CONSTRAINT uq_exam_response_question UNIQUE (session_id, question_id),
                FOREIGN KEY (session_id) REFERENCES exam_sessions(session_id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
                FOREIGN KEY (workspace_id) REFERENCES exam_workspaces(workspace_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_exam_responses_session
                ON exam_responses(session_id, position);
            CREATE INDEX IF NOT EXISTS idx_exam_responses_topic
                ON exam_responses(student_id, workspace_id, topic);
            """
        )
        columns = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(exam_workspaces)").fetchall()
        }
        if "question_bank_fingerprint" not in columns:
            self._conn.execute(
                "ALTER TABLE exam_workspaces "
                "ADD COLUMN question_bank_fingerprint TEXT NOT NULL DEFAULT ''"
            )
        self._conn.commit()

    def register(
        self, username: str, display_name: str, password_hash: str, salt: str
    ) -> Student:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "INSERT INTO students "
                    "(username, display_name, password_hash, salt, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (username, display_name, password_hash, salt, _utc_now()),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                raise StoreError("That username is already taken.") from None
            return Student(int(cursor.lastrowid), username, display_name)

    def credentials(self, username: str) -> tuple[Student, str, str] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, username, display_name, password_hash, salt "
                "FROM students WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None:
            return None
        return Student(int(row[0]), row[1], row[2]), row[3], row[4]

    def touch_login(self, student_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE students SET last_login = ? WHERE id = ?",
                (_utc_now(), student_id),
            )
            self._conn.commit()

    def get_progress(self, student_id: int, track_key: str) -> Progress:
        with self._lock:
            row = self._conn.execute(
                "SELECT current_index, completed, attempts, total_seconds, best_seconds "
                "FROM progress WHERE student_id = ? AND track_key = ?",
                (student_id, track_key),
            ).fetchone()
        if row is None:
            return Progress(track_key)
        return Progress(
            track_key=track_key,
            current_index=int(row[0]),
            completed=int(row[1]),
            attempts=int(row[2]),
            total_seconds=float(row[3]),
            best_seconds=None if row[4] is None else float(row[4]),
        )

    def record_attempt(
        self,
        student_id: int,
        track_key: str,
        problem_key: str,
        duration_seconds: float,
        passed: bool,
        tests_passed: int,
        tests_total: int,
        next_index: int,
    ) -> None:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT current_index, completed, attempts, total_seconds, best_seconds "
                "FROM progress WHERE student_id = ? AND track_key = ?",
                (student_id, track_key),
            ).fetchone()
            if row is None:
                current_index = next_index if passed else 0
                completed = 1 if passed else 0
                attempts = 1
                total_seconds = duration_seconds
                best_seconds = duration_seconds if passed else None
            else:
                current_index = next_index if passed else int(row[0])
                completed = int(row[1]) + (1 if passed else 0)
                attempts = int(row[2]) + 1
                total_seconds = float(row[3]) + duration_seconds
                best_seconds = row[4]
                if passed and (best_seconds is None or duration_seconds < best_seconds):
                    best_seconds = duration_seconds

            now = _utc_now()
            self._conn.execute(
                "INSERT INTO attempts "
                "(student_id, track_key, problem_key, duration_seconds, passed, "
                "tests_passed, tests_total, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    student_id,
                    track_key,
                    problem_key,
                    duration_seconds,
                    int(passed),
                    tests_passed,
                    tests_total,
                    now,
                ),
            )
            self._conn.execute(
                "INSERT INTO progress "
                "(student_id, track_key, current_index, completed, attempts, "
                "total_seconds, best_seconds, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(student_id, track_key) DO UPDATE SET "
                "current_index = excluded.current_index, "
                "completed = excluded.completed, "
                "attempts = excluded.attempts, "
                "total_seconds = excluded.total_seconds, "
                "best_seconds = excluded.best_seconds, "
                "updated_at = excluded.updated_at",
                (
                    student_id,
                    track_key,
                    current_index,
                    completed,
                    attempts,
                    total_seconds,
                    best_seconds,
                    now,
                ),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def create_exam_workspace(self, student_id, subject, course_level, exam_date, total_marks, duration_minutes):
        now = _utc_now()
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO exam_workspaces (student_id, subject, course_level, exam_date, "
                "total_marks, duration_minutes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (student_id, subject, course_level, exam_date, total_marks, duration_minutes, now, now),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def list_exam_workspaces(self, student_id):
        with self._lock:
            rows = self._conn.execute(
                "SELECT workspace_id, subject, course_level, exam_date, syllabus_approved, updated_at "
                "FROM exam_workspaces WHERE student_id=? ORDER BY updated_at DESC, workspace_id DESC",
                (student_id,),
            ).fetchall()
        return [dict(zip(("workspace_id", "subject", "course_level", "exam_date", "syllabus_approved", "updated_at"), row)) for row in rows]

    def get_exam_workspace(self, student_id, workspace_id):
        with self._lock:
            row = self._conn.execute(
                "SELECT workspace_id, subject, course_level, exam_date, total_marks, duration_minutes, "
                "syllabus_filename, source_text, topics_json, syllabus_approved, notes_json, questions_json "
                "FROM exam_workspaces WHERE student_id=? AND workspace_id=?",
                (student_id, workspace_id),
            ).fetchone()
        if row is None:
            return None
        return dict(zip(("workspace_id", "subject", "course_level", "exam_date", "total_marks", "duration_minutes", "syllabus_filename", "source_text", "topics_json", "syllabus_approved", "notes_json", "questions_json"), row))

    def save_syllabus(self, student_id, workspace_id, filename, source_text, topics_json):
        with self._lock:
            row = self._conn.execute(
                "SELECT syllabus_filename, source_text, topics_json FROM exam_workspaces "
                "WHERE student_id=? AND workspace_id=?",
                (student_id, workspace_id),
            ).fetchone()
            if row is None:
                return False
            unchanged = tuple(row) == (filename, source_text, topics_json)
            if unchanged:
                self._conn.execute(
                    "UPDATE exam_workspaces SET updated_at=? "
                    "WHERE student_id=? AND workspace_id=?",
                    (_utc_now(), student_id, workspace_id),
                )
            else:
                self._conn.execute(
                    "UPDATE exam_workspaces SET syllabus_filename=?, source_text=?, "
                    "topics_json=?, syllabus_approved=0, notes_json='[]', "
                    "questions_json='[]', question_bank_fingerprint='', updated_at=? "
                    "WHERE student_id=? AND workspace_id=?",
                    (filename, source_text, topics_json, _utc_now(), student_id, workspace_id),
                )
                self._conn.execute(
                    "UPDATE exam_questions SET is_active=0 "
                    "WHERE student_id=? AND workspace_id=?",
                    (student_id, workspace_id),
                )
            self._conn.commit()
            return True

    def approve_syllabus(self, student_id, workspace_id, topics_json):
        with self._lock:
            self._conn.execute(
                "UPDATE exam_workspaces SET topics_json=?, syllabus_approved=1, updated_at=? "
                "WHERE student_id=? AND workspace_id=? AND source_text<>''",
                (topics_json, _utc_now(), student_id, workspace_id),
            )
            changed = self._conn.execute("SELECT changes()").fetchone()[0]
            self._conn.commit()
            return bool(changed)

    def save_exam_content(self, student_id, workspace_id, kind, content_json):
        column = "notes_json" if kind == "notes" else "questions_json"
        with self._lock:
            self._conn.execute(
                f"UPDATE exam_workspaces SET {column}=?, updated_at=? "
                "WHERE student_id=? AND workspace_id=? AND syllabus_approved=1",
                (content_json, _utc_now(), student_id, workspace_id),
            )
            changed = self._conn.execute("SELECT changes()").fetchone()[0]
            if changed and kind == "questions":
                self._conn.execute(
                    "UPDATE exam_workspaces SET question_bank_fingerprint='' "
                    "WHERE student_id=? AND workspace_id=?",
                    (student_id, workspace_id),
                )
                self._conn.execute(
                    "UPDATE exam_questions SET is_active=0 "
                    "WHERE student_id=? AND workspace_id=?",
                    (student_id, workspace_id),
                )
            self._conn.commit()
            return bool(changed)

    def sync_question_bank(self, student_id, workspace_id):
        with self._lock:
            row = self._conn.execute(
                "SELECT questions_json, topics_json, syllabus_filename, "
                "question_bank_fingerprint FROM exam_workspaces "
                "WHERE student_id=? AND workspace_id=?",
                (student_id, workspace_id),
            ).fetchone()
            if row is None:
                return 0
            try:
                questions = json.loads(row[0] or "[]")
                topics = json.loads(row[1] or "[]")
            except (TypeError, json.JSONDecodeError):
                questions = []
                topics = []
            if not isinstance(questions, list) or not questions:
                self._conn.execute(
                    "UPDATE exam_questions SET is_active=0 "
                    "WHERE student_id=? AND workspace_id=?",
                    (student_id, workspace_id),
                )
                self._conn.execute(
                    "UPDATE exam_workspaces SET question_bank_fingerprint='' "
                    "WHERE student_id=? AND workspace_id=?",
                    (student_id, workspace_id),
                )
                self._conn.commit()
                return 0
            fingerprint = hashlib.sha256(
                json.dumps(
                    {"questions": questions, "topics": topics},
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            if row[3] == fingerprint:
                count = self._conn.execute(
                    "SELECT COUNT(*) FROM exam_questions "
                    "WHERE student_id=? AND workspace_id=? AND is_active=1",
                    (student_id, workspace_id),
                ).fetchone()[0]
                return int(count)

            unit_by_topic: dict[str, str] = {}
            if isinstance(topics, list):
                for unit in topics:
                    if not isinstance(unit, dict):
                        continue
                    title = str(unit.get("title", "")).strip()
                    for topic in unit.get("topics", []) or []:
                        unit_by_topic[str(topic).casefold()] = title
            now = _utc_now()
            self._conn.execute(
                "UPDATE exam_questions SET is_active=0 WHERE student_id=? AND workspace_id=?",
                (student_id, workspace_id),
            )
            inserted = 0
            seen: set[str] = set()
            for item in questions:
                if not isinstance(item, dict):
                    continue
                prompt = str(item.get("question", "")).strip()
                answer = str(item.get("answer", "")).strip()
                topic = str(item.get("source_topic", "")).strip()
                question_type = str(item.get("question_type", "")).strip()
                if not prompt or not answer or not topic or not question_type:
                    continue
                normalized = re.sub(r"\W+", " ", prompt.casefold()).strip()
                if normalized in seen:
                    continue
                seen.add(normalized)
                marks = item.get("marks", 1)
                if isinstance(marks, bool) or not isinstance(marks, int):
                    marks = 1
                marks = max(1, min(100, marks))
                options = item.get("options")
                if not isinstance(options, list):
                    options = []
                self._conn.execute(
                    "INSERT INTO exam_questions "
                    "(workspace_id, student_id, unit_title, topic, question_type, "
                    "difficulty, bloom_level, marks, prompt, options_json, answer, "
                    "explanation, source_quote, source_kind, source_ref, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        workspace_id,
                        student_id,
                        unit_by_topic.get(topic.casefold(), ""),
                        topic,
                        question_type,
                        str(item.get("difficulty", "")).strip(),
                        str(item.get("bloom_level", "")).strip(),
                        marks,
                        prompt,
                        json.dumps(options, ensure_ascii=False),
                        answer,
                        str(item.get("explanation", "")).strip(),
                        str(item.get("source_quote", "")).strip(),
                        str(item.get("source_kind", "ai")).strip() or "ai",
                        str(item.get("source_ref", row[2] or "")).strip(),
                        now,
                    ),
                )
                inserted += 1
            self._conn.execute(
                "UPDATE exam_workspaces SET question_bank_fingerprint=?, updated_at=? "
                "WHERE student_id=? AND workspace_id=?",
                (fingerprint, now, student_id, workspace_id),
            )
            self._conn.commit()
            return inserted

    def list_exam_questions(self, student_id, workspace_id):
        with self._lock:
            rows = self._conn.execute(
                "SELECT question_id, unit_title, topic, question_type, difficulty, "
                "bloom_level, marks, prompt, options_json, answer, explanation, "
                "source_quote, source_kind, source_ref FROM exam_questions "
                "WHERE student_id=? AND workspace_id=? AND is_active=1 "
                "ORDER BY question_id",
                (student_id, workspace_id),
            ).fetchall()
        keys = (
            "question_id", "unit_title", "topic", "question_type", "difficulty",
            "bloom_level", "marks", "prompt", "options_json", "answer",
            "explanation", "source_quote", "source_kind", "source_ref",
        )
        result = []
        for row in rows:
            item = dict(zip(keys, row))
            try:
                item["options"] = json.loads(item.pop("options_json") or "[]")
            except (TypeError, json.JSONDecodeError):
                item["options"] = []
            result.append(item)
        return result

    def create_exam_session(
        self, student_id, workspace_id, mode, questions, blueprint_json,
        duration_limit_seconds,
    ):
        now = _utc_now()
        total_marks = sum(max(1, int(item.get("marks", 1))) for item in questions)
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO exam_sessions "
                "(student_id, workspace_id, mode, status, blueprint_json, total_marks, "
                "duration_limit_seconds, started_at, created_at) "
                "VALUES (?, ?, ?, 'in_progress', ?, ?, ?, ?, ?)",
                (
                    student_id,
                    workspace_id,
                    mode,
                    blueprint_json,
                    total_marks,
                    max(0, int(duration_limit_seconds)),
                    now,
                    now,
                ),
            )
            session_id = int(cursor.lastrowid)
            for position, item in enumerate(questions):
                self._conn.execute(
                    "INSERT INTO exam_responses "
                    "(session_id, student_id, workspace_id, question_id, position, "
                    "unit_title, topic, question_type, marks, question_snapshot_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        session_id,
                        student_id,
                        workspace_id,
                        int(item["question_id"]),
                        position,
                        str(item.get("unit_title", "")),
                        str(item.get("topic", "")),
                        str(item.get("question_type", "")),
                        max(1, int(item.get("marks", 1))),
                        json.dumps(item, ensure_ascii=False),
                    ),
                )
            self._conn.commit()
            return session_id

    def get_exam_session(self, student_id, session_id):
        with self._lock:
            row = self._conn.execute(
                "SELECT session_id, student_id, workspace_id, mode, status, "
                "blueprint_json, total_marks, score_marks, needs_review, "
                "duration_limit_seconds, elapsed_seconds, started_at, submitted_at "
                "FROM exam_sessions WHERE student_id=? AND session_id=?",
                (student_id, session_id),
            ).fetchone()
        if row is None:
            return None
        keys = (
            "session_id", "student_id", "workspace_id", "mode", "status",
            "blueprint_json", "total_marks", "score_marks", "needs_review",
            "duration_limit_seconds", "elapsed_seconds", "started_at", "submitted_at",
        )
        result = dict(zip(keys, row))
        try:
            result["blueprint"] = json.loads(result.pop("blueprint_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            result["blueprint"] = {}
        return result

    def list_exam_sessions(self, student_id, workspace_id=None):
        query = (
            "SELECT s.session_id, s.workspace_id, w.subject, s.mode, s.status, "
            "s.total_marks, s.score_marks, s.needs_review, s.started_at, "
            "s.submitted_at FROM exam_sessions s "
            "JOIN exam_workspaces w ON w.workspace_id=s.workspace_id "
            "WHERE s.student_id=?"
        )
        params: list[object] = [student_id]
        if workspace_id is not None:
            query += " AND s.workspace_id=?"
            params.append(workspace_id)
        query += " ORDER BY s.created_at DESC, s.session_id DESC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        keys = (
            "session_id", "workspace_id", "subject", "mode", "status",
            "total_marks", "score_marks", "needs_review", "started_at", "submitted_at",
        )
        return [dict(zip(keys, row)) for row in rows]

    def list_exam_responses(self, student_id, session_id):
        with self._lock:
            rows = self._conn.execute(
                "SELECT response_id, question_id, position, unit_title, topic, "
                "question_type, marks, student_answer, is_correct, awarded_marks, "
                "review_status, question_snapshot_json, answered_at "
                "FROM exam_responses WHERE student_id=? AND session_id=? "
                "ORDER BY position",
                (student_id, session_id),
            ).fetchall()
        keys = (
            "response_id", "question_id", "position", "unit_title", "topic",
            "question_type", "marks", "student_answer", "is_correct",
            "awarded_marks", "review_status", "question_snapshot_json", "answered_at",
        )
        result = []
        for row in rows:
            item = dict(zip(keys, row))
            try:
                item["snapshot"] = json.loads(item.pop("question_snapshot_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                item["snapshot"] = {}
            item["is_correct"] = (
                None if item["is_correct"] is None else bool(item["is_correct"])
            )
            result.append(item)
        return result

    def list_exam_analytics_records(self, student_id, workspace_id=None):
        query = (
            "SELECT s.session_id, s.workspace_id, s.mode, s.total_marks, "
            "s.score_marks, s.needs_review, s.started_at, s.submitted_at, "
            "r.response_id, r.position, r.unit_title, r.topic, r.question_type, "
            "r.marks, r.is_correct, r.awarded_marks, r.review_status, "
            "r.question_snapshot_json, r.answered_at "
            "FROM exam_sessions s "
            "JOIN exam_responses r ON r.session_id=s.session_id "
            "AND r.student_id=s.student_id "
            "WHERE s.student_id=? AND s.status='submitted'"
        )
        params: list[object] = [student_id]
        if workspace_id is not None:
            query += " AND s.workspace_id=?"
            params.append(workspace_id)
        query += " ORDER BY s.submitted_at, s.session_id, r.position"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        keys = (
            "session_id", "workspace_id", "mode", "total_marks", "score_marks",
            "needs_review", "started_at", "submitted_at", "response_id", "position",
            "unit_title", "topic", "question_type", "marks", "is_correct",
            "awarded_marks", "review_status", "question_snapshot_json", "answered_at",
        )
        result = []
        for row in rows:
            item = dict(zip(keys, row))
            try:
                item["snapshot"] = json.loads(
                    item.pop("question_snapshot_json") or "{}"
                )
            except (TypeError, json.JSONDecodeError):
                item["snapshot"] = {}
            item["is_correct"] = (
                None if item["is_correct"] is None else bool(item["is_correct"])
            )
            result.append(item)
        return result

    def save_exam_response(
        self, student_id, session_id, response_id, answer, is_correct,
        awarded_marks, review_status,
    ):
        with self._lock:
            status = self._conn.execute(
                "SELECT status FROM exam_sessions WHERE student_id=? AND session_id=?",
                (student_id, session_id),
            ).fetchone()
            if status is None or status[0] != "in_progress":
                return False
            self._conn.execute(
                "UPDATE exam_responses SET student_answer=?, is_correct=?, "
                "awarded_marks=?, review_status=?, answered_at=? "
                "WHERE student_id=? AND session_id=? AND response_id=?",
                (
                    answer,
                    None if is_correct is None else int(is_correct),
                    awarded_marks,
                    review_status,
                    _utc_now() if answer else None,
                    student_id,
                    session_id,
                    response_id,
                ),
            )
            changed = self._conn.execute("SELECT changes()").fetchone()[0]
            self._conn.commit()
            return bool(changed)

    def finish_exam_session(
        self, student_id, session_id, score_marks, needs_review, elapsed_seconds
    ):
        with self._lock:
            self._conn.execute(
                "UPDATE exam_sessions SET status='submitted', score_marks=?, "
                "needs_review=?, elapsed_seconds=?, submitted_at=? "
                "WHERE student_id=? AND session_id=? AND status='in_progress'",
                (
                    score_marks,
                    needs_review,
                    elapsed_seconds,
                    _utc_now(),
                    student_id,
                    session_id,
                ),
            )
            changed = self._conn.execute("SELECT changes()").fetchone()[0]
            self._conn.commit()
            return bool(changed)

    def abandon_exam_session(self, student_id, session_id):
        with self._lock:
            self._conn.execute(
                "UPDATE exam_sessions SET status='abandoned', submitted_at=? "
                "WHERE student_id=? AND session_id=? AND status='in_progress'",
                (_utc_now(), student_id, session_id),
            )
            changed = self._conn.execute("SELECT changes()").fetchone()[0]
            self._conn.commit()
            return bool(changed)


class OracleBackend:
    """Calls the `codelock_api` PL/SQL package from database/schema.sql."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._conn = oracledb.connect(
            user=config.ORACLE_USER,
            password=config.ORACLE_PASSWORD,
            dsn=config.ORACLE_DSN,
        )

    def register(
        self, username: str, display_name: str, password_hash: str, salt: str
    ) -> Student:
        with self._lock, self._conn.cursor() as cursor:
            try:
                student_id = cursor.callfunc(
                    "codelock_api.register_student",
                    int,
                    [username, display_name, password_hash, salt],
                )
                self._conn.commit()
            except oracledb.Error as exc:
                self._conn.rollback()
                if "ORA-00001" in str(exc):
                    raise StoreError("That username is already taken.") from None
                raise StoreError(f"Oracle rejected the account: {exc}") from None
        return Student(int(student_id), username, display_name)

    def credentials(self, username: str) -> tuple[Student, str, str] | None:
        with self._lock, self._conn.cursor() as cursor:
            student_id = cursor.var(int)
            display_name = cursor.var(str, 80)
            password_hash = cursor.var(str, 128)
            salt = cursor.var(str, 64)
            cursor.callproc(
                "codelock_api.get_credentials",
                [username, student_id, display_name, password_hash, salt],
            )
            if student_id.getvalue() is None:
                return None
            return (
                Student(int(student_id.getvalue()), username, display_name.getvalue()),
                password_hash.getvalue(),
                salt.getvalue(),
            )

    def touch_login(self, student_id: int) -> None:
        with self._lock, self._conn.cursor() as cursor:
            cursor.callproc("codelock_api.touch_login", [student_id])
            self._conn.commit()

    def get_progress(self, student_id: int, track_key: str) -> Progress:
        with self._lock, self._conn.cursor() as cursor:
            current_index = cursor.var(int)
            completed = cursor.var(int)
            attempts = cursor.var(int)
            total_seconds = cursor.var(float)
            best_seconds = cursor.var(float)
            cursor.callproc(
                "codelock_api.get_progress",
                [
                    student_id,
                    track_key,
                    current_index,
                    completed,
                    attempts,
                    total_seconds,
                    best_seconds,
                ],
            )
            best = best_seconds.getvalue()
            return Progress(
                track_key=track_key,
                current_index=int(current_index.getvalue() or 0),
                completed=int(completed.getvalue() or 0),
                attempts=int(attempts.getvalue() or 0),
                total_seconds=float(total_seconds.getvalue() or 0.0),
                best_seconds=None if best is None else float(best),
            )

    def record_attempt(
        self,
        student_id: int,
        track_key: str,
        problem_key: str,
        duration_seconds: float,
        passed: bool,
        tests_passed: int,
        tests_total: int,
        next_index: int,
    ) -> None:
        with self._lock, self._conn.cursor() as cursor:
            cursor.callproc(
                "codelock_api.record_attempt",
                [
                    student_id,
                    track_key,
                    problem_key,
                    duration_seconds,
                    int(passed),
                    tests_passed,
                    tests_total,
                    next_index,
                ],
            )
            self._conn.commit()

    def create_exam_workspace(self, student_id, subject, course_level, exam_date, total_marks, duration_minutes):
        with self._lock, self._conn.cursor() as cursor:
            workspace_id = cursor.var(int)
            cursor.execute(
                "INSERT INTO exam_workspaces (student_id, subject, course_level, exam_date, "
                "total_marks, duration_minutes) VALUES (:1, :2, :3, :4, :5, :6) "
                "RETURNING workspace_id INTO :7",
                [student_id, subject, course_level, exam_date, total_marks, duration_minutes, workspace_id],
            )
            self._conn.commit()
            return int(workspace_id.getvalue())

    def list_exam_workspaces(self, student_id):
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT workspace_id, subject, course_level, exam_date, syllabus_approved, updated_at "
                "FROM exam_workspaces WHERE student_id=:1 ORDER BY updated_at DESC, workspace_id DESC",
                [student_id],
            )
            return [dict(zip(("workspace_id", "subject", "course_level", "exam_date", "syllabus_approved", "updated_at"), row)) for row in cursor.fetchall()]

    def get_exam_workspace(self, student_id, workspace_id):
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT workspace_id, subject, course_level, exam_date, total_marks, duration_minutes, "
                "syllabus_filename, source_text, topics_json, syllabus_approved, notes_json, questions_json "
                "FROM exam_workspaces WHERE student_id=:1 AND workspace_id=:2",
                [student_id, workspace_id],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            keys = ("workspace_id", "subject", "course_level", "exam_date", "total_marks", "duration_minutes", "syllabus_filename", "source_text", "topics_json", "syllabus_approved", "notes_json", "questions_json")
            result = dict(zip(keys, row))
            for key in ("source_text", "topics_json", "notes_json", "questions_json"):
                value = result.get(key)
                if hasattr(value, "read"):
                    result[key] = value.read()
            return result

    def save_syllabus(self, student_id, workspace_id, filename, source_text, topics_json):
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT syllabus_filename, source_text, topics_json FROM exam_workspaces "
                "WHERE student_id=:1 AND workspace_id=:2",
                [student_id, workspace_id],
            )
            row = cursor.fetchone()
            if row is None:
                return False
            existing = tuple(
                value.read() if hasattr(value, "read") else (value or "")
                for value in row
            )
            if existing == (filename, source_text, topics_json):
                cursor.execute(
                    "UPDATE exam_workspaces SET updated_at=SYSTIMESTAMP "
                    "WHERE student_id=:1 AND workspace_id=:2",
                    [student_id, workspace_id],
                )
            else:
                cursor.setinputsizes(
                    None, oracledb.DB_TYPE_CLOB, oracledb.DB_TYPE_CLOB, None, None
                )
                cursor.execute(
                    "UPDATE exam_workspaces SET syllabus_filename=:1, source_text=:2, "
                    "topics_json=:3, syllabus_approved=0, notes_json='[]', "
                    "questions_json='[]', question_bank_fingerprint='', "
                    "updated_at=SYSTIMESTAMP "
                    "WHERE student_id=:4 AND workspace_id=:5",
                    [filename, source_text, topics_json, student_id, workspace_id],
                )
                cursor.execute(
                    "UPDATE exam_questions SET is_active=0 "
                    "WHERE student_id=:1 AND workspace_id=:2",
                    [student_id, workspace_id],
                )
            self._conn.commit()
            return True

    def approve_syllabus(self, student_id, workspace_id, topics_json):
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute(
                "UPDATE exam_workspaces SET topics_json=:1, syllabus_approved=1, updated_at=SYSTIMESTAMP "
                "WHERE student_id=:2 AND workspace_id=:3 AND DBMS_LOB.GETLENGTH(source_text)>0",
                [topics_json, student_id, workspace_id],
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def save_exam_content(self, student_id, workspace_id, kind, content_json):
        column = "notes_json" if kind == "notes" else "questions_json"
        fingerprint_reset = ", question_bank_fingerprint=''" if kind == "questions" else ""
        with self._lock, self._conn.cursor() as cursor:
            cursor.setinputsizes(oracledb.DB_TYPE_CLOB, None, None)
            cursor.execute(
                f"UPDATE exam_workspaces SET {column}=:1{fingerprint_reset}, "
                "updated_at=SYSTIMESTAMP "
                "WHERE student_id=:2 AND workspace_id=:3 AND syllabus_approved=1",
                [content_json, student_id, workspace_id],
            )
            changed = cursor.rowcount > 0
            if changed and kind == "questions":
                cursor.execute(
                    "UPDATE exam_questions SET is_active=0 "
                    "WHERE student_id=:1 AND workspace_id=:2",
                    [student_id, workspace_id],
                )
            self._conn.commit()
            return changed

    def sync_question_bank(self, student_id, workspace_id):
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT questions_json, topics_json, syllabus_filename, "
                "question_bank_fingerprint FROM exam_workspaces "
                "WHERE student_id=:1 AND workspace_id=:2",
                [student_id, workspace_id],
            )
            row = cursor.fetchone()
            if row is None:
                return 0
            questions_json, topics_json, filename, stored_fingerprint = row
            questions_text = (
                questions_json.read()
                if hasattr(questions_json, "read")
                else (questions_json or "[]")
            )
            topics_text = (
                topics_json.read()
                if hasattr(topics_json, "read")
                else (topics_json or "[]")
            )
            try:
                questions = json.loads(questions_text or "[]")
                topics = json.loads(topics_text or "[]")
            except (TypeError, json.JSONDecodeError):
                questions = []
                topics = []
            if not isinstance(questions, list) or not questions:
                cursor.execute(
                    "UPDATE exam_questions SET is_active=0 "
                    "WHERE student_id=:1 AND workspace_id=:2",
                    [student_id, workspace_id],
                )
                cursor.execute(
                    "UPDATE exam_workspaces SET question_bank_fingerprint='' "
                    "WHERE student_id=:1 AND workspace_id=:2",
                    [student_id, workspace_id],
                )
                self._conn.commit()
                return 0
            fingerprint = hashlib.sha256(
                json.dumps(
                    {"questions": questions, "topics": topics},
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            if stored_fingerprint == fingerprint:
                cursor.execute(
                    "SELECT COUNT(*) FROM exam_questions "
                    "WHERE student_id=:1 AND workspace_id=:2 AND is_active=1",
                    [student_id, workspace_id],
                )
                return int(cursor.fetchone()[0])

            unit_by_topic: dict[str, str] = {}
            if isinstance(topics, list):
                for unit in topics:
                    if not isinstance(unit, dict):
                        continue
                    title = str(unit.get("title", "")).strip()
                    for topic in unit.get("topics", []) or []:
                        unit_by_topic[str(topic).casefold()] = title
            cursor.execute(
                "UPDATE exam_questions SET is_active=0 "
                "WHERE student_id=:1 AND workspace_id=:2",
                [student_id, workspace_id],
            )
            inserted = 0
            seen: set[str] = set()
            for item in questions:
                if not isinstance(item, dict):
                    continue
                prompt = str(item.get("question", "")).strip()
                answer = str(item.get("answer", "")).strip()
                topic = str(item.get("source_topic", "")).strip()
                question_type = str(item.get("question_type", "")).strip()
                if not prompt or not answer or not topic or not question_type:
                    continue
                normalized = re.sub(r"\W+", " ", prompt.casefold()).strip()
                if normalized in seen:
                    continue
                seen.add(normalized)
                marks = item.get("marks", 1)
                if isinstance(marks, bool) or not isinstance(marks, int):
                    marks = 1
                marks = max(1, min(100, marks))
                options = item.get("options")
                if not isinstance(options, list):
                    options = []
                cursor.setinputsizes(
                    None, None, None, None, None, None, None, None, None,
                    oracledb.DB_TYPE_CLOB, None, oracledb.DB_TYPE_CLOB,
                    oracledb.DB_TYPE_CLOB, None, None,
                )
                cursor.execute(
                    "INSERT INTO exam_questions "
                    "(workspace_id, student_id, unit_title, topic, question_type, "
                    "difficulty, bloom_level, marks, prompt, options_json, answer, "
                    "explanation, source_quote, source_kind, source_ref) "
                    "VALUES (:1, :2, :3, :4, :5, :6, :7, :8, :9, :10, :11, :12, :13, :14, :15)",
                    [
                        workspace_id,
                        student_id,
                        unit_by_topic.get(topic.casefold(), ""),
                        topic,
                        question_type,
                        str(item.get("difficulty", "")).strip(),
                        str(item.get("bloom_level", "")).strip(),
                        marks,
                        prompt,
                        json.dumps(options, ensure_ascii=False),
                        answer,
                        str(item.get("explanation", "")).strip(),
                        str(item.get("source_quote", "")).strip(),
                        str(item.get("source_kind", "ai")).strip() or "ai",
                        str(item.get("source_ref", filename or "")).strip(),
                    ],
                )
                inserted += 1
            cursor.execute(
                "UPDATE exam_workspaces SET question_bank_fingerprint=:1, "
                "updated_at=SYSTIMESTAMP WHERE student_id=:2 AND workspace_id=:3",
                [fingerprint, student_id, workspace_id],
            )
            self._conn.commit()
            return inserted

    def list_exam_questions(self, student_id, workspace_id):
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT question_id, unit_title, topic, question_type, difficulty, "
                "bloom_level, marks, prompt, options_json, answer, explanation, "
                "source_quote, source_kind, source_ref FROM exam_questions "
                "WHERE student_id=:1 AND workspace_id=:2 AND is_active=1 "
                "ORDER BY question_id",
                [student_id, workspace_id],
            )
            rows = cursor.fetchall()
        keys = (
            "question_id", "unit_title", "topic", "question_type", "difficulty",
            "bloom_level", "marks", "prompt", "options_json", "answer",
            "explanation", "source_quote", "source_kind", "source_ref",
        )
        result = []
        for row in rows:
            item = dict(zip(keys, row))
            for field in ("options_json", "explanation", "source_quote"):
                value = item.get(field)
                if hasattr(value, "read"):
                    item[field] = value.read()
            try:
                item["options"] = json.loads(item.pop("options_json") or "[]")
            except (TypeError, json.JSONDecodeError):
                item["options"] = []
            result.append(item)
        return result

    def create_exam_session(
        self, student_id, workspace_id, mode, questions, blueprint_json,
        duration_limit_seconds,
    ):
        total_marks = sum(max(1, int(item.get("marks", 1))) for item in questions)
        with self._lock, self._conn.cursor() as cursor:
            session_id = cursor.var(int)
            cursor.setinputsizes(None, None, None, oracledb.DB_TYPE_CLOB, None, None)
            cursor.execute(
                "INSERT INTO exam_sessions "
                "(student_id, workspace_id, mode, status, blueprint_json, total_marks, "
                "duration_limit_seconds, started_at) "
                "VALUES (:1, :2, :3, 'in_progress', :4, :5, :6, SYSTIMESTAMP) "
                "RETURNING session_id INTO :7",
                [
                    student_id,
                    workspace_id,
                    mode,
                    blueprint_json,
                    total_marks,
                    max(0, int(duration_limit_seconds)),
                    session_id,
                ],
            )
            session_id = int(session_id.getvalue())
            for position, item in enumerate(questions):
                cursor.setinputsizes(
                    None, None, None, None, None, None, None, None, None,
                    oracledb.DB_TYPE_CLOB,
                )
                cursor.execute(
                    "INSERT INTO exam_responses "
                    "(session_id, student_id, workspace_id, question_id, position, "
                    "unit_title, topic, question_type, marks, question_snapshot_json) "
                    "VALUES (:1, :2, :3, :4, :5, :6, :7, :8, :9, :10)",
                    [
                        session_id,
                        student_id,
                        workspace_id,
                        int(item["question_id"]),
                        position,
                        str(item.get("unit_title", "")),
                        str(item.get("topic", "")),
                        str(item.get("question_type", "")),
                        max(1, int(item.get("marks", 1))),
                        json.dumps(item, ensure_ascii=False),
                    ],
                )
            self._conn.commit()
            return session_id

    def get_exam_session(self, student_id, session_id):
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT session_id, student_id, workspace_id, mode, status, "
                "blueprint_json, total_marks, score_marks, needs_review, "
                "duration_limit_seconds, elapsed_seconds, started_at, submitted_at "
                "FROM exam_sessions WHERE student_id=:1 AND session_id=:2",
                [student_id, session_id],
            )
            row = cursor.fetchone()
        if row is None:
            return None
        keys = (
            "session_id", "student_id", "workspace_id", "mode", "status",
            "blueprint_json", "total_marks", "score_marks", "needs_review",
            "duration_limit_seconds", "elapsed_seconds", "started_at", "submitted_at",
        )
        result = dict(zip(keys, row))
        blueprint = result.pop("blueprint_json")
        if hasattr(blueprint, "read"):
            blueprint = blueprint.read()
        try:
            result["blueprint"] = json.loads(blueprint or "{}")
        except (TypeError, json.JSONDecodeError):
            result["blueprint"] = {}
        return result

    def list_exam_sessions(self, student_id, workspace_id=None):
        query = (
            "SELECT s.session_id, s.workspace_id, w.subject, s.mode, s.status, "
            "s.total_marks, s.score_marks, s.needs_review, s.started_at, "
            "s.submitted_at FROM exam_sessions s "
            "JOIN exam_workspaces w ON w.workspace_id=s.workspace_id "
            "WHERE s.student_id=:1"
        )
        params: list[object] = [student_id]
        if workspace_id is not None:
            query += " AND s.workspace_id=:2"
            params.append(workspace_id)
        query += " ORDER BY s.created_at DESC, s.session_id DESC"
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
        keys = (
            "session_id", "workspace_id", "subject", "mode", "status",
            "total_marks", "score_marks", "needs_review", "started_at", "submitted_at",
        )
        return [dict(zip(keys, row)) for row in rows]

    def list_exam_responses(self, student_id, session_id):
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT response_id, question_id, position, unit_title, topic, "
                "question_type, marks, student_answer, is_correct, awarded_marks, "
                "review_status, question_snapshot_json, answered_at "
                "FROM exam_responses WHERE student_id=:1 AND session_id=:2 "
                "ORDER BY position",
                [student_id, session_id],
            )
            rows = cursor.fetchall()
        keys = (
            "response_id", "question_id", "position", "unit_title", "topic",
            "question_type", "marks", "student_answer", "is_correct",
            "awarded_marks", "review_status", "question_snapshot_json", "answered_at",
        )
        result = []
        for row in rows:
            item = dict(zip(keys, row))
            if hasattr(item.get("student_answer"), "read"):
                item["student_answer"] = item["student_answer"].read()
            snapshot = item.pop("question_snapshot_json")
            if hasattr(snapshot, "read"):
                snapshot = snapshot.read()
            try:
                item["snapshot"] = json.loads(snapshot or "{}")
            except (TypeError, json.JSONDecodeError):
                item["snapshot"] = {}
            item["is_correct"] = (
                None if item["is_correct"] is None else bool(item["is_correct"])
            )
            result.append(item)
        return result

    def list_exam_analytics_records(self, student_id, workspace_id=None):
        query = (
            "SELECT s.session_id, s.workspace_id, s.mode, s.total_marks, "
            "s.score_marks, s.needs_review, s.started_at, s.submitted_at, "
            "r.response_id, r.position, r.unit_title, r.topic, r.question_type, "
            "r.marks, r.is_correct, r.awarded_marks, r.review_status, "
            "r.question_snapshot_json, r.answered_at "
            "FROM exam_sessions s "
            "JOIN exam_responses r ON r.session_id=s.session_id "
            "AND r.student_id=s.student_id "
            "WHERE s.student_id=:1 AND s.status='submitted'"
        )
        params: list[object] = [student_id]
        if workspace_id is not None:
            query += " AND s.workspace_id=:2"
            params.append(workspace_id)
        query += " ORDER BY s.submitted_at, s.session_id, r.position"
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
        keys = (
            "session_id", "workspace_id", "mode", "total_marks", "score_marks",
            "needs_review", "started_at", "submitted_at", "response_id", "position",
            "unit_title", "topic", "question_type", "marks", "is_correct",
            "awarded_marks", "review_status", "question_snapshot_json", "answered_at",
        )
        result = []
        for row in rows:
            item = dict(zip(keys, row))
            snapshot = item.pop("question_snapshot_json")
            if hasattr(snapshot, "read"):
                snapshot = snapshot.read()
            try:
                item["snapshot"] = json.loads(snapshot or "{}")
            except (TypeError, json.JSONDecodeError):
                item["snapshot"] = {}
            item["is_correct"] = (
                None if item["is_correct"] is None else bool(item["is_correct"])
            )
            result.append(item)
        return result

    def save_exam_response(
        self, student_id, session_id, response_id, answer, is_correct,
        awarded_marks, review_status,
    ):
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM exam_sessions WHERE student_id=:1 AND session_id=:2",
                [student_id, session_id],
            )
            status = cursor.fetchone()
            if status is None or status[0] != "in_progress":
                return False
            cursor.setinputsizes(
                oracledb.DB_TYPE_CLOB, None, None, None, None, None, None, None
            )
            cursor.execute(
                "UPDATE exam_responses SET student_answer=:1, is_correct=:2, "
                "awarded_marks=:3, review_status=:4, "
                "answered_at=CASE WHEN :5 IS NOT NULL THEN SYSTIMESTAMP ELSE NULL END "
                "WHERE student_id=:6 AND session_id=:7 AND response_id=:8",
                [
                    answer,
                    None if is_correct is None else int(is_correct),
                    awarded_marks,
                    review_status,
                    answer or None,
                    student_id,
                    session_id,
                    response_id,
                ],
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def finish_exam_session(
        self, student_id, session_id, score_marks, needs_review, elapsed_seconds
    ):
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute(
                "UPDATE exam_sessions SET status='submitted', score_marks=:1, "
                "needs_review=:2, elapsed_seconds=:3, submitted_at=SYSTIMESTAMP "
                "WHERE student_id=:4 AND session_id=:5 AND status='in_progress'",
                [score_marks, needs_review, elapsed_seconds, student_id, session_id],
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def abandon_exam_session(self, student_id, session_id):
        with self._lock, self._conn.cursor() as cursor:
            cursor.execute(
                "UPDATE exam_sessions SET status='abandoned', submitted_at=SYSTIMESTAMP "
                "WHERE student_id=:1 AND session_id=:2 AND status='in_progress'",
                [student_id, session_id],
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
