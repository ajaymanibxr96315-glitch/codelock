"""Runs submitted code in a separate process and grades it in the parent.

The parent owns every expected value and compares results itself. The worker
only receives one test's arguments at a time and never receives expected
outputs, the hidden-test list, or a verdict field. This removes the original
"trust the child's answer" design, but it is still not a security sandbox:
submitted code runs as the same user, can inspect its own interpreter, and can
attempt to read the parent's memory or automate the GUI. The README and audit
report document those limits, and the GUI requires explicit confirmation before
a local judge result unlocks anything.
"""

from __future__ import annotations

import json
import math
import os
import queue
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .pc_blocker import is_admin
from .problems import Problem, TestCase

try:  # psutil is only needed to kill grandchildren; native fallbacks remain.
    import psutil
except ImportError:  # pragma: no cover - exercised on minimal Python installs
    psutil = None

FRAME_PREFIX = "@@CODELOCK_WORKER@@"
MAX_SOURCE_BYTES = 64 * 1024
MAX_MEMORY_BYTES = 256 * 1024 * 1024
MAX_CAPTURE_BYTES = 64 * 1024
MAX_FRAME_BYTES = 1024 * 1024
MAX_VALUE_DEPTH = 100

HARNESS = r'''
import json as _json
import os as _os
import sys as _sys

_control = _sys.stdin
_protocol_out = _sys.stdout
_dumps = _json.dumps
_loads = _json.loads
_type = type
_type_error = TypeError
_value_error = ValueError
_base_exception = BaseException
_writes = _protocol_out.write
_flush = _protocol_out.flush
_prefix = ""

def _send(payload):
    _writes(_prefix + _dumps(payload, allow_nan=False, separators=(",", ":")) + "\n")
    _flush()

def _encode(value, depth=0):
    if depth > 100:
        raise _value_error("the result is nested too deeply")
    kind = _type(value)
    if value is None:
        return {"t": "none"}
    if kind is bool:
        return {"t": "bool", "v": value}
    if kind is int:
        return {"t": "int", "v": value}
    if kind is float:
        if value != value:
            return {"t": "float", "v": "nan"}
        _inf = float("inf")
        if value == _inf:
            return {"t": "float", "v": "inf"}
        if value == -_inf:
            return {"t": "float", "v": "-inf"}
        return {"t": "float", "v": value}
    if kind is str:
        return {"t": "str", "v": value}
    if kind is list:
        return {"t": "list", "v": [_encode(item, depth + 1) for item in value]}
    if kind is tuple:
        return {"t": "tuple", "v": [_encode(item, depth + 1) for item in value]}
    if kind is dict:
        return {
            "t": "dict",
            "v": [[_encode(key, depth + 1), _encode(item, depth + 1)] for key, item in value.items()],
        }
    raise _type_error(kind.__name__)

try:
    _init = _loads(_control.readline())
except _base_exception:
    raise SystemExit(1)

_prefix = _init["prefix"]

# Bound accidental resource exhaustion on POSIX. This is defense in depth,
# not a security boundary against hostile code.
try:
    import resource
    _limits = (
        ("RLIMIT_CPU", _init["cpu_seconds"]),
        ("RLIMIT_FSIZE", 1024 * 1024),
        ("RLIMIT_NOFILE", 32),
        ("RLIMIT_NPROC", 16),
        ("RLIMIT_CORE", 0),
        ("RLIMIT_AS", _init["memory_bytes"]),
    )
    for _name, _limit in _limits:
        if hasattr(resource, _name):
            try:
                resource.setrlimit(getattr(resource, _name), (_limit, _limit))
            except (OSError, ValueError):
                continue
except (ImportError, OSError, ValueError):
    pass

# The student code must not be able to consume the control channel's input.
_sys.stdin = open(_os.devnull, "r")

_namespace = {"__name__": "__codelock_solution__"}
try:
    exec(compile(_init["code"], "<solution>", "exec"), _namespace)
except SystemExit:
    _send({"kind": "init", "error": "The code called sys.exit() while loading."})
    raise SystemExit(0)
except _base_exception as _exc:
    _send({"kind": "init", "error": "%s: %s" % (_type(_exc).__name__, _exc)})
    raise SystemExit(0)

_function = _namespace.get(_init["function_name"])
if not callable(_function):
    _send({
        "kind": "missing",
        "error": "No callable named '%s' was defined." % _init["function_name"],
    })
    raise SystemExit(0)

_send({"kind": "ready"})

while True:
    _line = _control.readline()
    if not _line:
        break
    try:
        _case = _loads(_line)
        _seq = _case["seq"]
        _args = _case["args"]
        if _type(_seq) is not int or _type(_args) is not list:
            raise ValueError("invalid case")
    except _base_exception:
        _send({"kind": "protocol", "error": "The judge sent an invalid test case."})
        break
    try:
        _actual = _function(*_args)
    except _base_exception as _exc:
        _send({
            "kind": "error",
            "seq": _seq,
            "error": "%s: %s" % (_type(_exc).__name__, _exc),
        })
        break
    try:
        _encoded = _encode(_actual)
    except _type_error as _exc:
        _send({"kind": "unsupported", "seq": _seq, "type": str(_exc)[:100]})
        break
    except _base_exception as _exc:
        _send({
            "kind": "error",
            "seq": _seq,
            "error": "The result could not be encoded: %s" % _type(_exc).__name__,
        })
        break
    _send({"kind": "result", "seq": _seq, "value": _encoded})
'''

_EOF = object()


class _WorkerTimeout(Exception):
    pass


class _WorkerGone(Exception):
    pass


class _ProtocolViolation(Exception):
    pass


@dataclass(frozen=True)
class JudgeResult:
    ok: bool
    message: str
    timed_out: bool = False
    tests_passed: int = 0
    tests_total: int = 0
    duration: float = 0.0
    student_output: str = ""
    details: str = field(default="")


@dataclass(frozen=True)
class _Frame:
    kind: str
    seq: int | None = None
    value: object = None
    error: str = ""
    type_name: str = ""


class _WorkerSession:
    def __init__(self, proc: subprocess.Popen, job: object, prefix: str) -> None:
        self.proc = proc
        self.job = job
        self.prefix = prefix
        self._prefix_bytes = prefix.encode("utf-8")
        self._frames: queue.Queue = queue.Queue(maxsize=1024)
        self._student_output = bytearray()
        self._stderr_output = bytearray()
        self._protocol_error = ""
        self._terminated = False
        self._job_closed = False
        self._readers = [
            threading.Thread(target=self._read_stdout, name="codelock-judge-out", daemon=True),
            threading.Thread(target=self._read_stderr, name="codelock-judge-err", daemon=True),
        ]
        for reader in self._readers:
            reader.start()

    # ------------------------------------------------------------------- input
    def send_init(self, payload: dict) -> None:
        self._write_line(payload)

    def send_case(self, seq: int, args: tuple) -> None:
        try:
            self._write_line({"seq": seq, "args": list(args)})
        except TypeError as exc:
            raise _ProtocolViolation(f"Test data could not be serialized: {exc}") from exc

    def _write_line(self, payload: dict) -> None:
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write(json.dumps(payload).encode("utf-8") + b"\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise _WorkerGone("The judge process stopped accepting input.") from exc

    # ------------------------------------------------------------------ output
    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        buffer = bytearray()
        discarding = False
        try:
            while True:
                chunk = (
                    self.proc.stdout.read1(8192)
                    if hasattr(self.proc.stdout, "read1")
                    else self.proc.stdout.read(8192)
                )
                if not chunk:
                    break
                if discarding:
                    newline = chunk.find(b"\n")
                    if newline < 0:
                        continue
                    chunk = chunk[newline + 1 :]
                    discarding = False
                buffer.extend(chunk)
                while True:
                    newline = buffer.find(b"\n")
                    if newline < 0:
                        break
                    line = bytes(buffer[:newline])
                    del buffer[: newline + 1]
                    self._handle_stdout_line(line)
                if len(buffer) > MAX_FRAME_BYTES:
                    self._set_protocol_error("The judge produced an oversized output line.")
                    buffer.clear()
                    discarding = True
            if buffer and not discarding:
                self._handle_stdout_line(bytes(buffer))
        except (OSError, ValueError):
            pass
        finally:
            try:
                self._frames.put_nowait(_EOF)
            except queue.Full:  # pragma: no cover - a full queue already fails
                pass

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        try:
            while True:
                chunk = (
                    self.proc.stderr.read1(8192)
                    if hasattr(self.proc.stderr, "read1")
                    else self.proc.stderr.read(8192)
                )
                if not chunk:
                    break
                self._stderr_output.extend(chunk)
                overflow = len(self._stderr_output) - MAX_CAPTURE_BYTES
                if overflow > 0:
                    del self._stderr_output[:overflow]
        except (OSError, ValueError):
            pass

    def _handle_stdout_line(self, line: bytes) -> None:
        if self._protocol_error:
            return
        if line.startswith(self._prefix_bytes):
            frame = self._parse_frame(line[len(self._prefix_bytes) :])
            self._put_frame(frame)
            return
        self._student_output.extend(line + b"\n")
        overflow = len(self._student_output) - MAX_CAPTURE_BYTES
        if overflow > 0:
            del self._student_output[:overflow]

    def _parse_frame(self, payload_bytes: bytes) -> _Frame:
        try:
            payload = json.loads(payload_bytes.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, RecursionError):
            return _Frame("protocol", error="The judge sent a malformed result frame.")
        if not isinstance(payload, dict):
            return _Frame("protocol", error="The judge sent a non-object result frame.")
        kind = payload.get("kind")
        if kind not in {"ready", "init", "missing", "result", "error", "unsupported"}:
            return _Frame("protocol", error="The judge sent an unknown result frame.")
        seq = payload.get("seq") if kind in {"result", "error", "unsupported"} else None
        if seq is not None and type(seq) is not int:
            return _Frame("protocol", error="The judge sent an invalid result sequence.")
        if kind == "result":
            return _Frame(kind, seq=seq, value=payload.get("value"))
        if kind in {"error", "init", "missing", "protocol"}:
            return _Frame(kind, seq=seq, error=str(payload.get("error", ""))[:300])
        if kind == "unsupported":
            return _Frame(kind, seq=seq, type_name=str(payload.get("type", ""))[:100])
        return _Frame(kind, seq=seq)

    def _put_frame(self, frame: _Frame) -> None:
        try:
            self._frames.put_nowait(frame)
        except queue.Full:
            self._set_protocol_error("The judge sent too many result frames.")

    def _set_protocol_error(self, message: str) -> None:
        if self._protocol_error:
            return
        self._protocol_error = message
        self._drain_and_report()

    def _drain_and_report(self) -> None:
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                break
        try:
            self._frames.put_nowait(_Frame("protocol", error=self._protocol_error))
        except queue.Full:  # pragma: no cover - queue was just drained
            pass

    # ------------------------------------------------------------------ waiting
    def _wait(self, expected_seq: int | None, timeout: float) -> _Frame:
        deadline = time.perf_counter() + max(0.0, timeout)
        while True:
            if self._protocol_error:
                raise _ProtocolViolation(self._protocol_error)
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise _WorkerTimeout
            try:
                item = self._frames.get(timeout=min(0.05, remaining))
            except queue.Empty:
                continue
            if item is _EOF:
                raise _WorkerGone
            assert isinstance(item, _Frame)
            if item.kind == "protocol":
                raise _ProtocolViolation(item.error or "The judge protocol was violated.")
            if expected_seq is None:
                if item.kind not in {"ready", "init", "missing"}:
                    raise _ProtocolViolation("The judge sent a result before it was ready.")
                return item
            if item.seq != expected_seq:
                raise _ProtocolViolation(
                    f"The judge sent an unexpected result sequence ({item.seq!r})."
                )
            return item

    def wait_for_ready(self, timeout: float) -> _Frame:
        return self._wait(None, timeout)

    def wait_for_case(self, seq: int, timeout: float) -> _Frame:
        return self._wait(seq, timeout)

    def finish(self) -> None:
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            returncode = self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired as exc:
            raise _WorkerTimeout from exc
        # Closing the job kills any descendants while the pipes are still open.
        if self.job is not None:
            self._close_job()
        else:
            _kill_tree(self.proc)
        for reader in self._readers:
            reader.join(timeout=2)
        while True:
            try:
                item = self._frames.get_nowait()
            except queue.Empty:
                break
            if item is _EOF:
                continue
            assert isinstance(item, _Frame)
            if item.kind == "protocol":
                raise _ProtocolViolation(item.error or "The judge protocol was violated.")
            raise _ProtocolViolation("The judge sent an extra result frame.")
        if returncode != 0:
            raise _WorkerGone(f"The judge process exited with code {returncode}.")

    # ---------------------------------------------------------------- lifecycle
    def student_output_text(self) -> str:
        text = self._student_output.decode("utf-8", errors="replace")
        return text.strip()[:2000]

    def stderr_text(self) -> str:
        text = self._stderr_output.decode("utf-8", errors="replace")
        return text.strip()[:400]

    def terminate(self) -> None:
        if self._terminated:
            return
        self._terminated = True
        try:
            self.proc.stdin.close()
        except (OSError, AttributeError):
            pass
        if self.job is not None and not self._job_closed:
            _terminate_job(self.job)
        _kill_tree(self.proc)
        try:
            self.proc.wait(timeout=2)
        except Exception:
            pass
        self._close_job()
        for reader in self._readers:
            reader.join(timeout=1)

    def close(self) -> None:
        self.terminate()

    def _close_job(self) -> None:
        if self.job is not None and not self._job_closed:
            self._job_closed = True
            _close_job(self.job)


class Judge:
    def __init__(self, timeout: float | None = None) -> None:
        self.timeout = config.JUDGE_TIMEOUT_SECONDS if timeout is None else timeout
        self.case_timeout = min(float(self.timeout), config.JUDGE_CASE_TIMEOUT_SECONDS)
        self._active: set[_WorkerSession] = set()
        self._active_lock = threading.Lock()
        self._closed = threading.Event()

    def shutdown(self) -> None:
        """Stop accepting work and terminate every active worker tree."""
        self._closed.set()
        with self._active_lock:
            sessions = list(self._active)
        for session in sessions:
            session.terminate()

    def evaluate(
        self, problem: Problem, code: str, include_hidden: bool = True
    ) -> JudgeResult:
        if is_admin():
            return JudgeResult(
                ok=False,
                message=(
                    "CodeLock will not run submitted code with administrator/root "
                    "privileges. Restart it from a standard user account."
                ),
            )
        if self._closed.is_set():
            return JudgeResult(
                ok=False,
                message="The judge is shutting down; this submission was not run.",
            )
        if len(code.encode("utf-8", errors="replace")) > MAX_SOURCE_BYTES:
            return JudgeResult(
                ok=False,
                message=f"Submission is too large (maximum {MAX_SOURCE_BYTES // 1024} KiB).",
            )

        tests: list[TestCase] = problem.visible_tests()
        if include_hidden:
            tests += problem.hidden_tests()

        prefix = f"{FRAME_PREFIX}:{secrets.token_hex(8)}:"
        cpu_seconds = max(1, math.ceil(self.timeout) + 1)
        init_payload = _build_init_payload(
            code, problem.function_name, prefix, cpu_seconds
        )

        workdir = Path(tempfile.mkdtemp(prefix="codelock-judge-"))
        started = time.perf_counter()
        session: _WorkerSession | None = None
        try:
            try:
                session = _start_session(workdir, init_payload, cpu_seconds)
            except OSError as exc:
                return JudgeResult(
                    ok=False,
                    message=f"Could not start the judge process: {exc}",
                    tests_total=len(tests),
                    duration=time.perf_counter() - started,
                )
            with self._active_lock:
                self._active.add(session)
            if self._closed.is_set():
                session.terminate()

            ready = session.wait_for_ready(
                min(self.timeout, self.case_timeout)
            )
            if ready.kind == "init":
                return JudgeResult(
                    ok=False,
                    message="Your code failed to load: " + _clean_text(ready.error),
                    tests_total=len(tests),
                    duration=time.perf_counter() - started,
                    student_output=session.student_output_text(),
                    details=session.stderr_text(),
                )
            if ready.kind == "missing":
                return JudgeResult(
                    ok=False,
                    message=_clean_text(ready.error) or "Required function is missing.",
                    tests_total=len(tests),
                    duration=time.perf_counter() - started,
                    student_output=session.student_output_text(),
                    details=session.stderr_text(),
                )

            for index, case in enumerate(tests):
                remaining = self.timeout - (time.perf_counter() - started)
                if remaining <= 0:
                    raise _WorkerTimeout
                session.send_case(index, case.args)
                frame = session.wait_for_case(index, min(self.case_timeout, remaining))
                if frame.kind == "error":
                    return _failed_result(
                        session,
                        tests,
                        index,
                        f"{_scope(case)} {index + 1} crashed with "
                        f"{_clean_text(frame.error) or 'an exception'}",
                        started,
                    )
                if frame.kind == "unsupported":
                    name = _clean_text(frame.type_name) or "unknown"
                    return _failed_result(
                        session,
                        tests,
                        index,
                        f"{_scope(case)} {index + 1} returned an unsupported type ({name}).",
                        started,
                    )
                if frame.kind != "result":
                    raise _ProtocolViolation("The judge sent an invalid case response.")
                try:
                    actual = _decode_value(frame.value)
                except _ProtocolViolation as exc:
                    raise _ProtocolViolation(str(exc)) from exc
                if type(actual) is not type(case.expected) or actual != case.expected:
                    return _failed_result(
                        session,
                        tests,
                        index,
                        _wrong_answer_message(index, case, actual),
                        started,
                    )

            session.finish()
            return JudgeResult(
                ok=True,
                message=f"All {len(tests)} tests passed.",
                tests_passed=len(tests),
                tests_total=len(tests),
                duration=time.perf_counter() - started,
                student_output=session.student_output_text(),
            )
        except _WorkerTimeout:
            return JudgeResult(
                ok=False,
                message=(
                    f"Time limit exceeded ({self.timeout:g}s). "
                    "Check for infinite loops or missing return statements."
                ),
                timed_out=True,
                tests_total=len(tests),
                duration=time.perf_counter() - started,
                student_output=session.student_output_text() if session else "",
            )
        except _ProtocolViolation as exc:
            return JudgeResult(
                ok=False,
                message="The judge result was rejected: " + _clean_text(str(exc)),
                tests_total=len(tests),
                duration=time.perf_counter() - started,
                student_output=session.student_output_text() if session else "",
                details=session.stderr_text() if session else "",
            )
        except _WorkerGone as exc:
            return JudgeResult(
                ok=False,
                message="The judge process ended without a result.",
                tests_total=len(tests),
                duration=time.perf_counter() - started,
                student_output=session.student_output_text() if session else "",
                details=(
                    session.stderr_text()
                    if session and session.stderr_text()
                    else _clean_text(str(exc))
                ),
            )
        finally:
            if session is not None:
                with self._active_lock:
                    self._active.discard(session)
                session.close()
            shutil.rmtree(workdir, ignore_errors=True)


def _build_init_payload(
    code: str, function_name: str, prefix: str, cpu_seconds: int
) -> dict:
    """The worker receives code and resource settings, never test data."""
    return {
        "code": code,
        "function_name": function_name,
        "prefix": prefix,
        "cpu_seconds": cpu_seconds,
        "memory_bytes": MAX_MEMORY_BYTES,
    }


def _start_session(workdir: Path, init_payload: dict, cpu_seconds: int) -> _WorkerSession:
    job = _create_job(cpu_seconds)
    try:
        proc = subprocess.Popen(
            [sys.executable, "-I", "-c", HARNESS],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(workdir),
            env=_judge_environment(),
            start_new_session=(os.name != "nt"),
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )
    except Exception:
        if job is not None:
            _close_job(job)
        raise
    if job is not None and not _assign_job(job, proc):
        _close_job(job)
        job = None
    session = _WorkerSession(proc, job, init_payload["prefix"])
    try:
        session.send_init(init_payload)
    except Exception:
        session.close()
        raise
    return session


def _failed_result(
    session: _WorkerSession,
    tests: list[TestCase],
    index: int,
    message: str,
    started: float,
) -> JudgeResult:
    return JudgeResult(
        ok=False,
        message=message,
        tests_passed=index,
        tests_total=len(tests),
        duration=time.perf_counter() - started,
        student_output=session.student_output_text(),
        details=session.stderr_text(),
    )


def _scope(case: TestCase) -> str:
    return "Hidden test" if case.hidden else "Sample test"


def _wrong_answer_message(index: int, case: TestCase, actual: object) -> str:
    if case.hidden:
        return f"Hidden test {index + 1} failed: the returned value is incorrect."
    return (
        f"Sample test {index + 1} failed: for input {_short(case.args)} "
        f"expected {_short(case.expected)}, got {_short(actual)}."
    )


def _short(value: object, limit: int = 200) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "..."


def _clean_text(text: str) -> str:
    return " ".join(str(text).split())[:300]


def _decode_value(payload: object, depth: int = 0) -> object:
    if depth > MAX_VALUE_DEPTH:
        raise _ProtocolViolation("The judge returned a value nested too deeply.")
    if type(payload) is not dict:
        raise _ProtocolViolation("The judge returned a malformed value.")
    tag = payload.get("t")
    if tag == "none":
        if set(payload) != {"t"}:
            raise _ProtocolViolation("The judge returned a malformed value.")
        return None
    if tag == "bool" and type(payload.get("v")) is bool:
        return payload["v"]
    if tag == "int" and type(payload.get("v")) is int:
        return payload["v"]
    if tag == "float":
        value = payload.get("v")
        if type(value) is float:
            return value
        if value == "nan":
            return float("nan")
        if value == "inf":
            return float("inf")
        if value == "-inf":
            return float("-inf")
        raise _ProtocolViolation("The judge returned a malformed float.")
    if tag == "str" and type(payload.get("v")) is str:
        return payload["v"]
    if tag in {"list", "tuple"} and type(payload.get("v")) is list:
        items = [_decode_value(item, depth + 1) for item in payload["v"]]
        return tuple(items) if tag == "tuple" else items
    if tag == "dict" and type(payload.get("v")) is list:
        result = {}
        for pair in payload["v"]:
            if type(pair) is not list or len(pair) != 2:
                raise _ProtocolViolation("The judge returned a malformed dictionary.")
            key = _decode_value(pair[0], depth + 1)
            try:
                result[key] = _decode_value(pair[1], depth + 1)
            except TypeError as exc:
                raise _ProtocolViolation(
                    "The judge returned a dictionary with an invalid key."
                ) from exc
        return result
    raise _ProtocolViolation("The judge returned a value type that cannot be graded.")


def _judge_environment() -> dict[str, str]:
    """Pass only runtime essentials; never expose app/database credentials."""
    allowed = (
        {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC", "PATHEXT"}
        if os.name == "nt"
        else {"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR"}
    )
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _kill_tree(proc: subprocess.Popen) -> None:
    if psutil is not None:
        try:
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                try:
                    child.kill()
                except psutil.Error:
                    pass
            parent.kill()
            return
        except psutil.Error:
            pass
    if os.name != "nt":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    elif os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        proc.kill()
    except Exception:
        pass


# --------------------------------------------------------------- Windows jobs
if os.name == "nt":  # pragma: no cover - exercised by Windows self-tests
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
    _JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

    def _create_job(cpu_seconds: int) -> object | None:
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | _JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | _JOB_OBJECT_LIMIT_PROCESS_TIME
        )
        info.BasicLimitInformation.PerProcessUserTimeLimit = int(cpu_seconds) * 10_000_000
        info.ProcessMemoryLimit = MAX_MEMORY_BYTES
        if not _kernel32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            _kernel32.CloseHandle(job)
            return None
        return job

    def _assign_job(job: object, proc: subprocess.Popen) -> bool:
        handle = getattr(proc, "_handle", None)
        if not handle:
            return False
        return bool(_kernel32.AssignProcessToJobObject(job, handle))

    def _terminate_job(job: object) -> None:
        try:
            _kernel32.TerminateJobObject(job, 1)
        except Exception:
            pass

    def _close_job(job: object) -> None:
        try:
            _kernel32.CloseHandle(job)
        except Exception:
            pass

else:  # pragma: no cover - POSIX uses process groups and resource limits

    def _create_job(cpu_seconds: int) -> object | None:
        return None

    def _assign_job(job: object, proc: subprocess.Popen) -> bool:
        return False

    def _terminate_job(job: object) -> None:
        return None

    def _close_job(job: object) -> None:
        return None
