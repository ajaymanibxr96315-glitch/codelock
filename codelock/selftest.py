"""Offline verification: hosts round-trip, judge pipeline, problem bank."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import sqlite3
import stat
import tempfile
import os
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from . import config
from . import exam_analytics
from . import exam_engine
from .db import Progress, StudentStore, StoreError
from .exam import DocumentError, extract_document, extract_topics, validate_topic_tree
from .study_generation import (
    _contains_source_quote,
    generate_local_notes,
    generate_local_question_bank,
    generate_notes,
    generate_question_bank,
    validate_questions,
)
from .ai import AIError, AIProvider
from . import gui as gui_module
from .hosts_elevation import (
    MANIFEST_FILENAME,
    STATUS_BLOCKED,
    STATUS_DAMAGED,
    STATUS_PARTIAL,
    STATUS_UNBLOCKED,
    STATUS_UNKNOWN,
    HostsAuthority,
    HostsOperationResult,
    HostsState,
    _RunOutcome,
    classify_state,
    clear_recovery_file,
    default_install_directory,
    default_install_path,
    default_manifest_path,
    read_hosts_state,
    status_label,
    verify_helper_installation,
    write_recovery_file,
)
from .windows_acl import inspect_installation_acl, inspect_path_acl
from . import judge as judge_module
from .judge import Judge, JudgeResult
from .pc_blocker import AppInstanceLock, HostsBlocker, ProcessKiller, is_admin
from .problems import PROBLEM_BY_KEY, PROBLEMS, TRACKS, get_problem

REFERENCE_SOLUTIONS = {
    "addition": (
        "def add(a, b):\n"
        "    return a + b\n"
    ),
    "two_sum": (
        "def two_sum(nums, target):\n"
        "    seen = set()\n"
        "    for value in nums:\n"
        "        if target - value in seen:\n"
        "            return True\n"
        "        seen.add(value)\n"
        "    return False\n"
    ),
    "valid_parentheses": (
        "def is_valid(s):\n"
        "    pairs = {')': '(', ']': '[', '}': '{'}\n"
        "    stack = []\n"
        "    for char in s:\n"
        "        if char in '([{':\n"
        "            stack.append(char)\n"
        "        elif not stack or stack.pop() != pairs[char]:\n"
        "            return False\n"
        "    return not stack\n"
    ),
    "max_subarray": (
        "def max_subarray(nums):\n"
        "    best = current = nums[0]\n"
        "    for value in nums[1:]:\n"
        "        current = max(value, current + value)\n"
        "        best = max(best, current)\n"
        "    return best\n"
    ),
    "digit_sum": (
        "def digit_sum(n):\n"
        "    return sum(int(char) for char in str(n))\n"
    ),
    "count_vowels": (
        "def count_vowels(text):\n"
        "    return sum(1 for char in text if char in 'aeiouAEIOU')\n"
    ),
    "palindrome": (
        "def is_palindrome(text):\n"
        "    cleaned = ''.join(char.lower() for char in text if char.isalnum())\n"
        "    return cleaned == cleaned[::-1]\n"
    ),
    "gcd": (
        "def gcd(a, b):\n"
        "    while b:\n"
        "        a, b = b, a % b\n"
        "    return a\n"
    ),
    "is_prime": (
        "def is_prime(n):\n"
        "    if n < 2:\n"
        "        return False\n"
        "    factor = 2\n"
        "    while factor * factor <= n:\n"
        "        if n % factor == 0:\n"
        "            return False\n"
        "        factor += 1\n"
        "    return True\n"
    ),
    "fibonacci": (
        "def fibonacci(n):\n"
        "    a, b = 0, 1\n"
        "    for _ in range(n):\n"
        "        a, b = b, a + b\n"
        "    return a\n"
    ),
    "binary_search": (
        "def binary_search(nums, target):\n"
        "    low, high = 0, len(nums) - 1\n"
        "    while low <= high:\n"
        "        middle = (low + high) // 2\n"
        "        if nums[middle] == target:\n"
        "            return middle\n"
        "        if nums[middle] < target:\n"
        "            low = middle + 1\n"
        "        else:\n"
        "            high = middle - 1\n"
        "    return -1\n"
    ),
    "transpose": (
        "def transpose(matrix):\n"
        "    return [list(row) for row in zip(*matrix)]\n"
    ),
    "dna_complement": (
        "def dna_complement(seq):\n"
        "    return seq.translate(str.maketrans('ATCG', 'TAGC'))\n"
    ),
    "gc_count": (
        "def gc_count(seq):\n"
        "    return sum(1 for base in seq if base in 'GC')\n"
    ),
    "hamming_distance": (
        "def hamming_distance(first, second):\n"
        "    return sum(1 for a, b in zip(first, second) if a != b)\n"
    ),
}


def _write_pdf(path: Path, objects: list[bytes]) -> None:
    data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref_offset = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(data)


def _write_test_pdf(path: Path) -> None:
    stream = (
        b"BT /F1 12 Tf 50 750 Td (UNIT 1: Algorithms) Tj "
        b"0 -20 Td (Arrays and searching) Tj ET"
    )
    _write_pdf(path, [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream + b"\nendstream",
    ])


def _write_blank_pdf(path: Path) -> None:
    _write_pdf(path, [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
    ])


class _FakeAIProvider:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def generate_json(self, system_prompt, user_prompt):
        self.prompts.append((system_prompt, user_prompt))
        return self.responses.pop(0)


def run_self_test() -> bool:
    failures = 0

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal failures
        if condition:
            print(f"PASS  {name}")
        else:
            failures += 1
            print(f"FAIL  {name}" + (f" - {detail}" if detail else ""))

    print(f"CodeLock self-test | Python {sys.version.split()[0]} | admin={is_admin()}")
    print()

    with tempfile.TemporaryDirectory() as tmp:
        first_lock = AppInstanceLock(Path(tmp) / "instance.lock")
        second_lock = AppInstanceLock(Path(tmp) / "instance.lock")
        first_acquired = first_lock.acquire()
        second_denied = not second_lock.acquire()
        first_lock.release()
        retry_after_release = second_lock.acquire()
        second_lock.release()
        check(
            "session lock: prevents a second live instance and releases cleanly",
            first_acquired and second_denied and retry_after_release,
        )

    # ----------------------------------------------------------- hosts round-trip
    with tempfile.TemporaryDirectory() as tmp:
        hosts_file = Path(tmp) / "hosts"
        hosts_file.write_text("127.0.0.1 localhost\n", encoding="utf-8")
        blocker = HostsBlocker(hosts_path=hosts_file, flush_resolver=False)

        check("hosts: block installs marker", blocker.block() and blocker.is_blocked())
        check("hosts: block is idempotent", blocker.block() and blocker.is_blocked())
        content = hosts_file.read_text(encoding="utf-8")
        check(
            "hosts: existing entries preserved",
            content.startswith("127.0.0.1 localhost"),
        )
        check(
            "hosts: markers are not duplicated",
            content.count(config.HOSTS_BLOCK_BEGIN) == 1
            and content.count(config.HOSTS_BLOCK_END) == 1,
        )
        check(
            "hosts: every configured site is present",
            all(f"{config.BLOCK_REDIRECT_IP} {site}" in content for site in config.BLOCKED_WEBSITES),
        )
        check("hosts: unblock succeeds", blocker.unblock())
        check(
            "hosts: unblock restores the original file",
            hosts_file.read_text(encoding="utf-8") == "127.0.0.1 localhost\n",
        )
        check("hosts: unblock is idempotent", blocker.unblock())

        hosts_file.write_bytes(
            "127.0.0.1 localhost\r\n# caf\xe9\r\n".encode("cp1252")
        )
        legacy_blocker = HostsBlocker(hosts_path=hosts_file, flush_resolver=False)
        legacy_round_trip = legacy_blocker.block() and legacy_blocker.unblock()
        legacy_bytes = hosts_file.read_bytes()
        check(
            "hosts: non-UTF-8 entries and CRLF survive a block/unblock round trip",
            legacy_round_trip
            and b"# caf\xe9\r\n" in legacy_bytes
            and b"localhost\r\n" in legacy_bytes,
        )
        hosts_file.write_text("127.0.0.1 localhost\n", encoding="utf-8")
        blocker._encoding, blocker._newline = "utf-8", "\n"

        check("hosts recovery: no stale block is a no-op", blocker.recover_stale_block() is None)
        check("hosts recovery: fixture block installs", blocker.block())
        check(
            "hosts recovery: stale managed block is removed",
            blocker.recover_stale_block() is True and not blocker.is_blocked(),
        )
        check(
            "hosts recovery: unrelated entries survive",
            hosts_file.read_text(encoding="utf-8") == "127.0.0.1 localhost\n",
        )

        damaged = (
            "127.0.0.1 localhost\n"
            + config.HOSTS_BLOCK_BEGIN
            + "\n0.0.0.0 example.com\n"
            + "192.0.2.5 user-managed.example\n"
        )
        hosts_file.write_text(damaged, encoding="utf-8")
        check(
            "hosts recovery: incomplete marker refuses destructive restore",
            not blocker.recover_stale_block()
            and hosts_file.read_text(encoding="utf-8") == damaged,
        )

        class _FakeHostsControl:
            def __init__(self, result: HostsOperationResult) -> None:
                self.result = result
                self.block_calls = 0
                self.unblock_calls = 0
                self.state_calls = 0

            def block(self) -> HostsOperationResult:
                self.block_calls += 1
                return self.result

            def unblock(self) -> HostsOperationResult:
                self.unblock_calls += 1
                return self.result

            def state(self) -> HostsState:
                self.state_calls += 1
                return HostsState(
                    exists=True,
                    blocked=self.result.blocked,
                    well_formed=True,
                    complete=self.result.blocked,
                    status=(
                        STATUS_BLOCKED if self.result.blocked else STATUS_UNBLOCKED
                    ),
                )

        recovery_writes: list[str] = []
        original_writer = gui_module.write_recovery_file
        original_clearer = gui_module.clear_recovery_file
        gui_module.write_recovery_file = lambda reason, path=None: (
            recovery_writes.append(reason) or Path(tmp) / "RECOVERY_REQUIRED.txt"
        )
        gui_module.clear_recovery_file = lambda path=None: None

        def make_app(control: _FakeHostsControl) -> gui_module.CodeLockApp:
            app = gui_module.CodeLockApp.__new__(gui_module.CodeLockApp)
            app.dry_run = False
            app._shutting_down = False
            app.locked = True
            app._unlocking = False
            app._enforce_lock = threading.Lock()
            app._hosts_error_logged = False
            app.hosts_control = control
            app.statuses: list[str] = []
            app.retry_visibility: list[bool] = []
            app.repair_flags: list[bool] = []
            app.logs: list[tuple[str, str]] = []
            app.unlock_events: list[bool] = []

            def ui(callback, *args, **kwargs):
                if getattr(callback, "__name__", "") == "_finish_unlock":
                    app.unlock_events.append(args[0])
                else:
                    callback(*args, **kwargs)

            app._ui = ui
            app._set_hosts_status = lambda text, color: app.statuses.append(text)
            app._show_hosts_retry = lambda visible, repair=False: (
                app.retry_visibility.append(bool(visible)),
                app.repair_flags.append(bool(repair)),
            )
            app._hosts_display = lambda key: gui_module.HOSTS_DISPLAY.get(
                key, gui_module.HOSTS_DISPLAY[STATUS_UNKNOWN]
            )
            app._log = lambda message, level="info": app.logs.append((message, level))
            return app

        try:
            unlocked = HostsOperationResult(
                True, False, "Website blocking is removed and verified."
            )
            unlock_control = _FakeHostsControl(unlocked)
            unlock_app = make_app(unlock_control)
            unlock_app._apply_unlock()
            check(
                "unlock: verified hosts restoration approves reward",
                unlock_app.unlock_events == [True]
                and unlock_control.unblock_calls == 1
                and unlock_app.statuses == ["NOT BLOCKED"],
            )

            locked = HostsOperationResult(
                False,
                True,
                "The CodeLock block is still present. WEBSITES ARE STILL BLOCKED.",
                recovery_required=True,
                observed=STATUS_BLOCKED,
            )
            fail_control = _FakeHostsControl(locked)
            fail_app = make_app(fail_control)
            fail_app._apply_unlock()
            check(
                "unlock: failed restoration withholds reward and reports observed block",
                fail_app.unlock_events == [False]
                and fail_app.statuses == ["BLOCKED"]
                and fail_app.retry_visibility == [True]
                and bool(recovery_writes)
                and "WEBSITES ARE STILL BLOCKED" in fail_app.logs[-1][0],
            )

            cancelled = HostsOperationResult(
                False,
                False,
                "Administrator approval was cancelled, so the hosts file was not "
                "changed. HOSTS FILE NOT BLOCKED.",
                cancelled=True,
                observed=STATUS_UNBLOCKED,
            )
            cancel_control = _FakeHostsControl(cancelled)
            cancel_app = make_app(cancel_control)
            cancel_app._apply_lock()
            check(
                "lock: failed or cancelled block never displays BLOCKED",
                cancel_app.statuses == ["NOT BLOCKED"]
                and cancel_app.retry_visibility == [True]
                and "HOSTS FILE NOT BLOCKED" in cancel_app.logs[-1][0],
            )

            blocked = HostsOperationResult(
                True, True, "Website blocking is installed and verified."
            )
            block_control = _FakeHostsControl(blocked)
            block_app = make_app(block_control)
            block_app._apply_lock()
            check(
                "lock: verified block displays BLOCKED and hides retry",
                block_app.statuses == ["BLOCKED"]
                and block_app.retry_visibility == [False],
            )

            failed_but_blocked = HostsOperationResult(
                False,
                True,
                "The helper failed, but the existing block is still present.",
                observed=STATUS_BLOCKED,
            )
            failed_block_control = _FakeHostsControl(failed_but_blocked)
            failed_block_app = make_app(failed_block_control)
            failed_block_app._apply_lock()
            check(
                "lock: a failed helper never hides an observed active block",
                failed_block_app.statuses == ["BLOCKED"]
                and failed_block_app.retry_visibility == [False],
            )

            damaged = HostsOperationResult(
                False,
                False,
                "The hosts file contains damaged CodeLock entries.",
                recovery_required=True,
                observed=STATUS_DAMAGED,
            )
            damaged_control = _FakeHostsControl(damaged)
            damaged_app = make_app(damaged_control)
            damaged_app._apply_lock()
            check(
                "lock: damaged state displays DAMAGED and offers REPAIR HOSTS",
                damaged_app.statuses == ["DAMAGED"]
                and damaged_app.retry_visibility == [True]
                and damaged_app.repair_flags == [True]
                and bool(recovery_writes),
            )

            no_state = HostsOperationResult(
                False, False, "The helper failed without a readable state."
            )
            no_state_control = _FakeHostsControl(no_state)
            no_state_app = make_app(no_state_control)
            no_state_app._apply_lock()
            check(
                "lock: a failure without an observed state shows STATUS UNKNOWN",
                no_state_app.statuses == ["STATUS UNKNOWN"]
                and no_state_app.retry_visibility == [True],
            )

            retry_control = _FakeHostsControl(
                HostsOperationResult(False, False, "not blocked")
            )
            retry_app = make_app(retry_control)
            retry_app._enforce_hosts(initial=False)
            check(
                "watchdog: read-only retry never triggers UAC",
                retry_control.block_calls == 0
                and retry_app.statuses == ["NOT BLOCKED"]
                and retry_app.retry_visibility == [True],
            )

            present_control = _FakeHostsControl(blocked)
            present_app = make_app(present_control)
            present_app._enforce_hosts(initial=False)
            check(
                "watchdog: a complete block is reported without rewriting",
                present_control.block_calls == 0
                and present_app.statuses == ["BLOCKED"]
                and present_app.retry_visibility == [False],
            )
        finally:
            gui_module.write_recovery_file = original_writer
            gui_module.clear_recovery_file = original_clearer

    # ------------------------------------------ elevated hosts helper (temp only)
    helper_source = Path(gui_module.__file__).with_name("hosts_helper.ps1")
    if os.name == "nt" and helper_source.is_file():
        helper_text = helper_source.read_text(encoding="utf-8")
        website_match = re.search(
            r"\$script:Websites = @\((.*?)\n\)", helper_text, re.DOTALL
        )
        compiled_sites = (
            tuple(re.findall(r"'([^']+)'", website_match.group(1)))
            if website_match
            else ()
        )
        check(
            "hosts helper: compiled sites, markers and redirect match config",
            compiled_sites == tuple(config.BLOCKED_WEBSITES)
            and f"$script:BeginMarker = '{config.HOSTS_BLOCK_BEGIN}'" in helper_text
            and f"$script:EndMarker = '{config.HOSTS_BLOCK_END}'" in helper_text
            and f"$script:RedirectIp = '{config.BLOCK_REDIRECT_IP}'" in helper_text,
        )

        with tempfile.TemporaryDirectory() as tmp:
            helper_hosts = Path(tmp) / "hosts"
            original_text = "127.0.0.1 localhost\n"
            helper_hosts.write_text(original_text, encoding="utf-8")
            authority = HostsAuthority(
                hosts_path=helper_hosts,
                test_helper=helper_source,
                test_mode=True,
            )
            check("hosts helper: PowerShell and bundled script are available", authority.available)

            first = authority.block()
            state = authority.state()
            content = helper_hosts.read_text(encoding="utf-8")
            check(
                "hosts helper: block installs a complete, verified managed block",
                first.ok
                and state.blocked
                and state.complete
                and content.startswith("127.0.0.1 localhost")
                and content.count(config.HOSTS_BLOCK_BEGIN) == 1
                and content.count(config.HOSTS_BLOCK_END) == 1
                and all(
                    f"{config.BLOCK_REDIRECT_IP} {site}" in content
                    for site in config.BLOCKED_WEBSITES
                ),
                first.message,
            )

            repeated_blocks = [authority.block() for _ in range(3)]
            repeated_text = helper_hosts.read_text(encoding="utf-8")
            check(
                "hosts helper: repeated block calls stay idempotent",
                all(item.ok for item in repeated_blocks)
                and repeated_text.count(config.HOSTS_BLOCK_BEGIN) == 1,
            )

            removed = authority.unblock()
            check(
                "hosts helper: unblock restores the original file",
                removed.ok
                and helper_hosts.read_text(encoding="utf-8") == original_text
                and not authority.state().blocked,
                removed.message,
            )
            check(
                "hosts helper: repeated unblock calls stay idempotent",
                authority.unblock().ok and authority.unblock().ok,
            )

            helper_hosts.write_bytes(
                "127.0.0.1 localhost\r\n# caf\xe9\r\n".encode("cp1252")
            )
            encoded_round_trip = authority.block() and authority.unblock()
            encoded_bytes = helper_hosts.read_bytes()
            check(
                "hosts helper: cp1252 text and CRLF survive a round trip",
                encoded_round_trip.ok
                and b"# caf\xe9\r\n" in encoded_bytes
                and b"localhost\r\n" in encoded_bytes,
            )

            damaged_text = (
                "127.0.0.1 localhost\n"
                + config.HOSTS_BLOCK_BEGIN
                + "\n0.0.0.0 example.com\n"
            )
            helper_hosts.write_text(damaged_text, encoding="utf-8")
            damaged_result = authority.block()
            check(
                "hosts helper: malformed markers are refused and left untouched",
                not damaged_result.ok
                and helper_hosts.read_text(encoding="utf-8") == damaged_text,
                damaged_result.message,
            )

            helper_hosts.write_text(original_text, encoding="utf-8")
            forced = HostsAuthority(
                hosts_path=helper_hosts,
                test_helper=helper_source,
                test_mode=True,
                test_force_error="write",
            )
            forced_result = forced.block()
            check(
                "hosts helper: forced write failure is reported as NOT BLOCKED",
                not forced_result.ok
                and "HOSTS FILE NOT BLOCKED" in forced_result.message
                and helper_hosts.read_text(encoding="utf-8") == original_text,
                forced_result.message,
            )

            helper_hosts.write_text(original_text, encoding="utf-8")
            verify_failed = HostsAuthority(
                hosts_path=helper_hosts,
                test_helper=helper_source,
                test_mode=True,
                test_force_error="verify",
            )
            verify_result = verify_failed.block()
            check(
                "hosts helper: failed post-write verification reports the observed block",
                verify_result.ok
                and verify_result.observed == STATUS_BLOCKED
                and "HOSTS FILE BLOCKED" in verify_result.message,
                verify_result.message,
            )
            helper_hosts.write_text(original_text, encoding="utf-8")

            dns_failed = authority._result(
                True,
                authority.state(),
                "Website blocking is installed and verified.",
                outcome=_RunOutcome(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "ok": True,
                            "dns": {
                                "attempted": True,
                                "ok": False,
                                "message": "simulated ipconfig failure",
                            },
                        }
                    ),
                ),
            )
            dns_skipped = authority._result(
                True,
                authority.state(),
                "Website blocking is installed and verified.",
                outcome=_RunOutcome(
                    returncode=0,
                    stdout=json.dumps(
                        {"ok": True, "dns": {"attempted": False, "ok": False}}
                    ),
                ),
            )
            check(
                "hosts status: DNS failures are reported and skipped flushes are not",
                dns_failed.dns_flushed is False
                and "DNS cache flush failed" in dns_failed.message
                and "simulated ipconfig failure" in dns_failed.message
                and dns_skipped.dns_flushed is None,
                dns_failed.message,
            )

            os.chmod(helper_hosts, stat.S_IREAD)
            try:
                readonly_result = authority.block()
                readonly_text = helper_hosts.read_text(encoding="utf-8")
            finally:
                os.chmod(helper_hosts, stat.S_IWRITE | stat.S_IREAD)
            check(
                "hosts helper: a read-only hosts file fails closed",
                not readonly_result.ok
                and "HOSTS FILE NOT BLOCKED" in readonly_result.message
                and readonly_text == original_text,
                readonly_result.message,
            )

            def complete_block_text(base: str = "127.0.0.1 localhost\n") -> str:
                lines = [config.HOSTS_BLOCK_BEGIN]
                lines.extend(
                    f"{config.BLOCK_REDIRECT_IP} {site}"
                    for site in config.BLOCKED_WEBSITES
                )
                lines.append(config.HOSTS_BLOCK_END)
                return base + "\n".join(lines) + "\n"

            def write_manifest(
                install_dir: Path, helper: Path, **overrides
            ) -> Path:
                digest = hashlib.sha256(helper.read_bytes()).hexdigest()
                payload = {
                    "product": "CodeLock",
                    "format": 1,
                    "helper": "hosts_helper.ps1",
                    "algorithm": "sha256",
                    "sha256": digest,
                    "size": helper.stat().st_size,
                }
                payload.update(overrides)
                manifest = install_dir / MANIFEST_FILENAME
                manifest.write_text(json.dumps(payload), encoding="utf-8")
                return manifest

            install_counter = 0

            def make_authority(
                hosts: Path,
                launcher,
                *,
                helper_bytes: bytes | None = None,
                manifest_overrides: dict | None = None,
                acl_inspector=None,
            ):
                nonlocal install_counter
                install_counter += 1
                install_dir = (
                    Path(validation_tmp) / f"install{install_counter}" / "CodeLock"
                )
                install_dir.mkdir(parents=True)
                helper = install_dir / "hosts_helper.ps1"
                helper.write_bytes(
                    helper_source.read_bytes()
                    if helper_bytes is None
                    else helper_bytes
                )
                manifest = write_manifest(
                    install_dir, helper, **(manifest_overrides or {})
                )
                authority = HostsAuthority(
                    hosts_path=hosts,
                    install_path=helper,
                    manifest_path=manifest,
                    launcher=launcher,
                    acl_inspector=acl_inspector
                    or (lambda directory, files: []),
                    enforce_program_files=False,
                )
                return authority, install_dir, helper, manifest

            with tempfile.TemporaryDirectory() as validation_tmp:
                clean_hosts = Path(validation_tmp) / "hosts"
                clean_hosts.write_text(original_text, encoding="utf-8")

                cancel_launcher = lambda executable, parameters, timeout: _RunOutcome(
                    None, cancelled=True, error="cancelled"
                )
                cancelled_authority, _, _, _ = make_authority(
                    clean_hosts, cancel_launcher
                )
                cancelled_result = cancelled_authority.block()
                check(
                    "hosts helper: UAC cancellation never reports a successful lock",
                    not cancelled_result.ok
                    and cancelled_result.cancelled
                    and "HOSTS FILE NOT BLOCKED" in cancelled_result.message
                    and not read_hosts_state(clean_hosts).blocked,
                    cancelled_result.message,
                )

                existing_hosts = Path(validation_tmp) / "hosts-existing"
                existing_hosts.write_text(complete_block_text(), encoding="utf-8")
                existing_authority, _, _, _ = make_authority(
                    existing_hosts, cancel_launcher
                )
                existing_result = existing_authority.block()
                check(
                    "hosts helper: UAC cancellation with an existing block keeps BLOCKED",
                    existing_result.ok
                    and existing_result.cancelled
                    and existing_result.observed == STATUS_BLOCKED
                    and "existing CodeLock block" in existing_result.message
                    and read_hosts_state(existing_hosts).complete,
                    existing_result.message,
                )

                silent_launcher = lambda executable, parameters, timeout: _RunOutcome(0)
                silent_authority, _, _, _ = make_authority(
                    clean_hosts, silent_launcher
                )
                silent_result = silent_authority.block()
                check(
                    "hosts helper: helper success without a state change is a failure",
                    not silent_result.ok
                    and "could not be verified" in silent_result.message
                    and "HOSTS FILE NOT BLOCKED" in silent_result.message,
                    silent_result.message,
                )

                failure_launcher = lambda executable, parameters, timeout: _RunOutcome(
                    3, stdout='{"message": "simulated helper failure"}'
                )
                failure_authority, _, _, _ = make_authority(
                    clean_hosts, failure_launcher
                )
                failure_result = failure_authority.block()
                check(
                    "hosts helper: non-zero helper exit is reported as NOT BLOCKED",
                    not failure_result.ok
                    and "simulated helper failure" in failure_result.message
                    and "HOSTS FILE NOT BLOCKED" in failure_result.message,
                    failure_result.message,
                )

                blocked_existing, _, _, _ = make_authority(
                    existing_hosts, failure_launcher
                )
                blocked_existing_result = blocked_existing.block()
                check(
                    "hosts helper: a failed helper never hides an existing block",
                    blocked_existing_result.ok
                    and blocked_existing_result.blocked
                    and blocked_existing_result.observed == STATUS_BLOCKED
                    and "HOSTS FILE BLOCKED" in blocked_existing_result.message,
                    blocked_existing_result.message,
                )

                elevated_parameters = failure_authority._build_elevated_parameters(
                    "block"
                )
                check(
                    "hosts helper: elevated command runs only the installed script",
                    "-File" in elevated_parameters
                    and str(failure_authority.install_path) in elevated_parameters
                    and "EncodedCommand" not in elevated_parameters
                    and str(config.BASE_DIR) not in elevated_parameters
                    and sys.executable not in elevated_parameters,
                    elevated_parameters,
                )
                try:
                    failure_authority._build_elevated_parameters("erase")
                except ValueError:
                    unsupported_rejected = True
                else:
                    unsupported_rejected = False
                check(
                    "hosts helper: unsupported operations are rejected client-side",
                    unsupported_rejected,
                )

                timeout_hosts = Path(validation_tmp) / "hosts-timeout"
                timeout_hosts.write_text(original_text, encoding="utf-8")

                def orphan_launcher(executable, parameters, timeout):
                    return _RunOutcome(
                        None,
                        error="could not be stopped",
                        timed_out=True,
                        terminated=False,
                        reconciled=False,
                    )

                orphan_authority, _, _, _ = make_authority(
                    timeout_hosts, orphan_launcher
                )
                orphan_result = orphan_authority.block()
                check(
                    "hosts helper: an unreconciled timeout requires recovery",
                    not orphan_result.ok
                    and orphan_result.recovery_required
                    and orphan_result.timed_out
                    and "could not be stopped" in orphan_result.message
                    and orphan_result.observed == STATUS_UNBLOCKED,
                    orphan_result.message,
                )

                def reconciled_timeout_launcher(executable, parameters, timeout):
                    timeout_hosts.write_text(
                        complete_block_text(), encoding="utf-8"
                    )
                    return _RunOutcome(
                        None,
                        error="exceeded the time limit and was terminated",
                        timed_out=True,
                        terminated=True,
                        reconciled=True,
                    )

                reconciled_authority, _, _, _ = make_authority(
                    timeout_hosts, reconciled_timeout_launcher
                )
                reconciled_result = reconciled_authority.block()
                check(
                    "hosts helper: a reconciled timeout reports the observed block",
                    reconciled_result.ok
                    and reconciled_result.observed == STATUS_BLOCKED
                    and not reconciled_result.recovery_required
                    and "terminated" in reconciled_result.message,
                    reconciled_result.message,
                )

                # Trust: runtime verification never reads the project folder.
                source_copy = Path(validation_tmp) / "project" / "hosts_helper.ps1"
                source_copy.parent.mkdir()
                source_copy.write_bytes(helper_source.read_bytes())
                trust_install, trust_helper, trust_manifest = make_authority(
                    clean_hosts,
                    lambda executable, parameters, timeout: _RunOutcome(0),
                )[1:]
                check(
                    "trust: installed helper verifies against its protected manifest",
                    verify_helper_installation(
                        trust_install,
                        acl_inspector=lambda directory, files: [],
                    ).ok,
                )
                source_copy.write_bytes(b"tampered project copy")
                check(
                    "trust: tampering with the project copy does not affect trust",
                    verify_helper_installation(
                        trust_install,
                        acl_inspector=lambda directory, files: [],
                    ).ok,
                )

                trust_helper.write_bytes(b"tampered installed helper")
                tampered = verify_helper_installation(
                    trust_install,
                    acl_inspector=lambda directory, files: [],
                )
                check(
                    "trust: modifying the installed helper invalidates the manifest",
                    not tampered.ok
                    and "manifest_hash_mismatch" in tampered.problems,
                    tampered.summary,
                )

                launch_calls: list[str] = []

                def counting_launcher(executable, parameters, timeout):
                    launch_calls.append(parameters)
                    return _RunOutcome(0)

                tampered_authority = HostsAuthority(
                    hosts_path=clean_hosts,
                    install_path=trust_helper,
                    manifest_path=trust_manifest,
                    launcher=counting_launcher,
                    acl_inspector=lambda directory, files: [],
                    enforce_program_files=False,
                )
                refused_result = tampered_authority.block()
                check(
                    "trust: an invalid helper signature refuses elevated execution",
                    not refused_result.ok
                    and refused_result.detail
                    and "could not be verified" in refused_result.message
                    and launch_calls == [],
                    refused_result.message,
                )

                manifest_cases = {
                    "manifest_product_mismatch": {"product": "Other"},
                    "manifest_algorithm_mismatch": {"algorithm": "md5"},
                    "manifest_hash_mismatch": {"sha256": "0" * 64},
                }
                for expected_problem, overrides in manifest_cases.items():
                    case_dir = Path(validation_tmp) / expected_problem / "CodeLock"
                    case_dir.mkdir(parents=True)
                    case_helper = case_dir / "hosts_helper.ps1"
                    case_helper.write_bytes(helper_source.read_bytes())
                    write_manifest(case_dir, case_helper, **overrides)
                    case_verification = verify_helper_installation(
                        case_dir,
                        acl_inspector=lambda directory, files: [],
                    )
                    check(
                        f"trust: {expected_problem} is rejected",
                        not case_verification.ok
                        and expected_problem in case_verification.problems,
                        case_verification.summary,
                    )

                bad_json_dir = Path(validation_tmp) / "bad-json" / "CodeLock"
                bad_json_dir.mkdir(parents=True)
                (bad_json_dir / "hosts_helper.ps1").write_bytes(
                    helper_source.read_bytes()
                )
                (bad_json_dir / MANIFEST_FILENAME).write_text(
                    "{not json", encoding="utf-8"
                )
                bad_json = verify_helper_installation(
                    bad_json_dir, acl_inspector=lambda directory, files: []
                )
                check(
                    "trust: malformed manifests are rejected",
                    not bad_json.ok
                    and "manifest_not_valid_json" in bad_json.problems,
                    bad_json.summary,
                )

                missing_manifest_dir = Path(validation_tmp) / "no-manifest" / "CodeLock"
                missing_manifest_dir.mkdir(parents=True)
                (missing_manifest_dir / "hosts_helper.ps1").write_bytes(
                    helper_source.read_bytes()
                )
                missing_manifest = verify_helper_installation(
                    missing_manifest_dir, acl_inspector=lambda directory, files: []
                )
                check(
                    "trust: a missing manifest is rejected",
                    not missing_manifest.ok
                    and any(
                        problem.startswith("manifest_missing")
                        for problem in missing_manifest.problems
                    ),
                    missing_manifest.summary,
                )

                acl_rejected = verify_helper_installation(
                    trust_install,
                    acl_inspector=lambda directory, files: [
                        "writable_by:S-1-5-21-evil"
                    ],
                )
                check(
                    "trust: a writable installation ACL is rejected",
                    not acl_rejected.ok
                    and "writable_by:S-1-5-21-evil" in acl_rejected.problems,
                    acl_rejected.summary,
                )
                real_acl = verify_helper_installation(trust_install)
                check(
                    "trust: a user-writable temp installation fails the real ACL check",
                    not real_acl.ok
                    and any(
                        problem.startswith(("dir:", "hosts_helper"))
                        for problem in real_acl.problems
                    ),
                    real_acl.summary,
                )
                wrong_location = verify_helper_installation(
                    trust_install,
                    acl_inspector=lambda directory, files: [],
                    require_program_files=True,
                )
                check(
                    "trust: a non-Program-Files installation is rejected in production",
                    not wrong_location.ok
                    and any(
                        problem.startswith("unexpected_install_directory")
                        for problem in wrong_location.problems
                    ),
                    wrong_location.summary,
                )

                if os.name == "nt":
                    program_files_acl = inspect_path_acl(
                        default_install_directory().parent
                    )
                    project_acl = inspect_path_acl(config.BASE_DIR)
                    temp_acl = inspect_installation_acl(
                        trust_install, [trust_helper, trust_manifest]
                    )
                    check(
                        "ACL: Program Files is read-only for a standard user",
                        program_files_acl == [],
                        str(program_files_acl),
                    )
                    check(
                        "ACL: the project folder is detected as user-writable",
                        any(
                            "writable_by" in problem
                            or "owner_not_protected" in problem
                            for problem in project_acl
                        ),
                        str(project_acl),
                    )
                    check(
                        "ACL: a temporary install directory is rejected",
                        any(
                            "writable_by" in problem
                            or "owner_not_protected" in problem
                            for problem in temp_acl
                        ),
                        str(temp_acl),
                    )

                check(
                    "hosts helper: writes use an atomic replace, never a copy fallback",
                    "File]::Replace($temp, $Path, $backup" in helper_text
                    and "File]::Copy($temp, $Path" not in helper_text
                    and "$stream.Flush($true)" in helper_text
                    and "FileStream(" in helper_text
                    and "Remove-StaleTemps" in helper_text,
                )

                stale_hosts = Path(validation_tmp) / "hosts-stale"
                stale_hosts.write_text(original_text, encoding="utf-8")
                stale_file = Path(validation_tmp) / "hosts.codelock-stale.tmp"
                fresh_file = Path(validation_tmp) / "hosts.codelock-fresh.tmp"
                stale_file.write_text("stale", encoding="utf-8")
                fresh_file.write_text("fresh", encoding="utf-8")
                old_time = time.time() - 7200
                os.utime(stale_file, (old_time, old_time))
                stale_authority = HostsAuthority(
                    hosts_path=stale_hosts,
                    test_helper=helper_source,
                    test_mode=True,
                )
                stale_result = stale_authority.block()
                check(
                    "hosts helper: stale temporary files are cleaned, fresh ones kept",
                    stale_result.ok
                    and not stale_file.exists()
                    and fresh_file.exists(),
                    stale_result.message,
                )
                fresh_file.unlink()

                recovery_hosts = Path(validation_tmp) / "hosts-recovery"
                damaged_text = (
                    "127.0.0.1 localhost\n"
                    "0.0.0.0 example.com\n"
                    + config.HOSTS_BLOCK_BEGIN
                    + "\n0.0.0.0 instagram.com\n"
                )
                recovery_hosts.write_text(damaged_text, encoding="utf-8")
                recovery_authority = HostsAuthority(
                    hosts_path=recovery_hosts,
                    test_helper=helper_source,
                    test_mode=True,
                )
                check(
                    "hosts recovery: damaged markers are classified as DAMAGED",
                    read_hosts_state(recovery_hosts).status == STATUS_DAMAGED
                    and status_label(STATUS_DAMAGED) == "HOSTS FILE DAMAGED",
                )
                recovered = recovery_authority.recover(keep_block=False)
                recovered_text = recovery_hosts.read_text(encoding="utf-8")
                check(
                    "hosts recovery: malformed markers are repaired and verified",
                    recovered.ok
                    and recovered.observed == STATUS_UNBLOCKED
                    and config.HOSTS_BLOCK_BEGIN not in recovered_text
                    and "0.0.0.0 instagram.com" not in recovered_text
                    and "0.0.0.0 example.com" in recovered_text
                    and bool(
                        list(
                            Path(validation_tmp).glob(
                                "hosts-recovery.codelock-damaged-*.bak"
                            )
                        )
                    ),
                    recovered.message,
                )

                repair_hosts = Path(validation_tmp) / "hosts-repair"
                repair_hosts.write_text(damaged_text, encoding="utf-8")
                repair_authority = HostsAuthority(
                    hosts_path=repair_hosts,
                    test_helper=helper_source,
                    test_mode=True,
                )
                repaired = repair_authority.recover(keep_block=True)
                repaired_state = read_hosts_state(repair_hosts)
                check(
                    "hosts recovery: repair removes damage and re-verifies a block",
                    repaired.ok
                    and repaired.observed == STATUS_BLOCKED
                    and repaired_state.complete
                    and "0.0.0.0 example.com" in repair_hosts.read_text(
                        encoding="utf-8"
                    ),
                    repaired.message,
                )

                outside_hosts = Path(validation_tmp) / "hosts-outside"
                outside_hosts.write_text(
                    "127.0.0.1 localhost\n0.0.0.0 instagram.com\n",
                    encoding="utf-8",
                )
                outside_state = read_hosts_state(outside_hosts)
                outside_authority = HostsAuthority(
                    hosts_path=outside_hosts,
                    test_helper=helper_source,
                    test_mode=True,
                )
                outside_recovered = outside_authority.recover(keep_block=False)
                check(
                    "hosts recovery: stray managed entries are detected and removed",
                    outside_state.status == STATUS_DAMAGED
                    and outside_state.managed_outside == 1
                    and outside_recovered.ok
                    and outside_hosts.read_text(encoding="utf-8")
                    == "127.0.0.1 localhost\n",
                    outside_recovered.message,
                )

                partial_hosts = Path(validation_tmp) / "hosts-partial"
                partial_hosts.write_text(
                    "127.0.0.1 localhost\n"
                    + config.HOSTS_BLOCK_BEGIN
                    + "\n0.0.0.0 instagram.com\n"
                    + config.HOSTS_BLOCK_END
                    + "\n",
                    encoding="utf-8",
                )
                partial_state = read_hosts_state(partial_hosts)
                check(
                    "hosts status: an incomplete block is PARTIAL, not BLOCKED",
                    partial_state.status == STATUS_PARTIAL
                    and partial_state.blocked
                    and not partial_state.complete
                    and status_label(partial_state) == "HOSTS FILE PARTIAL",
                )

                install_path = default_install_path()
                check(
                    "hosts helper: install target is outside the writable project folder",
                    config.BASE_DIR not in install_path.parents
                    and install_path.name == "hosts_helper.ps1"
                    and install_path.parent.name == "CodeLock"
                    and default_manifest_path().name == MANIFEST_FILENAME,
                    str(install_path),
                )

                installer_path = (
                    Path(__file__).resolve().parent.parent
                    / "tools"
                    / "install_hosts_helper.ps1"
                )
                installer_text = (
                    installer_path.read_text(encoding="utf-8")
                    if installer_path.is_file()
                    else ""
                )
                check(
                    "hosts helper: a manual installer creates the protected manifest",
                    "setowner" in installer_text
                    and "inheritance:r" in installer_text
                    and "hosts_helper.manifest.json" in installer_text
                    and "sha256" in installer_text,
                )

            with tempfile.TemporaryDirectory() as recovery_tmp:
                recovery_path = Path(recovery_tmp) / "RECOVERY_REQUIRED.txt"
                written = write_recovery_file(
                    "simulated restore failure", path=recovery_path
                )
                recovery_text = (
                    recovery_path.read_text(encoding="utf-8")
                    if written is not None
                    else ""
                )
                check(
                    "hosts recovery: instructions name --restore and the markers",
                    written == recovery_path
                    and "--restore" in recovery_text
                    and config.HOSTS_BLOCK_BEGIN in recovery_text
                    and config.HOSTS_BLOCK_END in recovery_text
                    and "ipconfig /flushdns" in recovery_text,
                )
                clear_recovery_file(recovery_path)
                check(
                    "hosts recovery: instructions are removed after a verified restore",
                    not recovery_path.exists(),
                )

            try:
                HostsAuthority(
                    hosts_path=config.HOSTS_PATH,
                    test_helper=helper_source,
                    test_mode=True,
                )
            except ValueError:
                real_hosts_refused = True
            else:
                real_hosts_refused = False
            check(
                "hosts helper: test mode refuses the real system hosts file",
                real_hosts_refused,
            )

    # ------------------------------------------------------------- problem bank
    for problem in PROBLEMS:
        visible = problem.visible_tests()
        hidden = problem.hidden_tests()
        check(f"problems: {problem.key} has visible examples", len(visible) >= 2)
        check(f"problems: {problem.key} has >= 20 hidden tests", len(hidden) >= 20)

    two_sum_hidden = get_problem("two_sum").hidden_tests()
    outcomes = {case.expected for case in two_sum_hidden}
    check("problems: two_sum hidden tests mix True and False", outcomes == {True, False})

    # ------------------------------------------------------------------- tracks
    check(
        "tracks: keys are unique",
        len({track.key for track in TRACKS}) == len(TRACKS),
    )
    check(
        "tracks: every challenge key resolves and no track repeats one",
        all(
            track.problem_keys
            and len(track.problem_keys) == len(set(track.problem_keys))
            and all(key in PROBLEM_BY_KEY for key in track.problem_keys)
            for track in TRACKS
        ),
    )
    check(
        "tracks: every problem is reachable from at least one track",
        {key for track in TRACKS for key in track.problem_keys} == set(PROBLEM_BY_KEY),
    )
    check(
        "tracks: each track offers at least 3 challenges",
        all(len(track.problem_keys) >= 3 for track in TRACKS),
    )

    # --------------------------------------------------------- student accounts
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "codelock.db"
        store = StudentStore(prefer_oracle=False, db_path=db_path)
        check("db: local fallback backend is active", "SQLite" in store.backend_name)

        alice = store.register("Alice_01", "Alice", "hunter22")
        check(
            "db: registration normalises the username",
            alice.username == "alice_01" and alice.display_name == "Alice",
        )

        duplicate = False
        try:
            store.register("alice_01", "Copy", "hunter22")
        except StoreError:
            duplicate = True
        check("db: duplicate usernames are rejected", duplicate)

        wrong = False
        try:
            store.login("alice_01", "wrongpass")
        except StoreError:
            wrong = True
        check("db: wrong passwords are rejected", wrong)
        check(
            "db: correct login succeeds",
            store.login("alice_01", "hunter22").id == alice.id,
        )
        check(
            "db: a new track starts at challenge 0",
            store.get_progress(alice.id, "maths") == Progress("maths"),
        )

        workspace_id = store.create_exam_workspace(
            alice.id, "Computer Networks", "B.Tech", "2027-04-15", 100, 180
        )
        check(
            "exam db: workspace is student-owned and reloadable",
            store.get_exam_workspace(alice.id, workspace_id)["subject"] == "Computer Networks"
            and store.get_exam_workspace(alice.id + 1000, workspace_id) is None,
        )
        outline = [{"title": "Unit 1: Foundations", "topics": ["OSI layers", "TCP/IP"]}]
        check(
            "exam db: syllabus save reports success and missing workspaces report failure",
            store.save_syllabus(
                alice.id, workspace_id, "networks.txt",
                "Unit 1: Foundations\nOSI layers\nTCP/IP", outline,
            ) is True
            and store.save_syllabus(
                alice.id, workspace_id + 999, "missing.txt", "text", outline
            ) is False,
        )
        check(
            "exam db: generation is blocked until syllabus approval",
            not store.save_exam_content(alice.id, workspace_id, "notes", [{"topic": "x"}]),
        )
        check(
            "exam db: reviewed syllabus approval enables saved content",
            store.approve_syllabus(alice.id, workspace_id, outline)
            and store.save_exam_content(alice.id, workspace_id, "notes", [{"topic": "OSI layers"}])
            and store.get_exam_workspace(alice.id, workspace_id)["notes"][0]["topic"] == "OSI layers",
        )

        foreign_session = False
        try:
            store.create_exam_session(
                alice.id + 1000, workspace_id, "practice",
                [{"question_id": 1}], {},
            )
        except StoreError:
            foreign_session = True
        check(
            "exam db: a session cannot be created against another student's workspace",
            foreign_session,
        )

        store.record_attempt(alice.id, "maths", "addition", 41.5, True, 30, 30, 1)
        store.record_attempt(alice.id, "maths", "gcd", 30.0, False, 2, 30, 1)
        store.record_attempt(alice.id, "maths", "gcd", 22.25, True, 30, 30, 2)
        progress = store.get_progress(alice.id, "maths")
        check(
            "db: attempts, solves and next challenge are accumulated",
            progress.attempts == 3
            and progress.completed == 2
            and progress.current_index == 2,
        )
        check(
            "db: total completion time is summed",
            abs(progress.total_seconds - 93.75) < 1e-6,
            str(progress.total_seconds),
        )
        check(
            "db: best completion time keeps the fastest pass",
            progress.best_seconds is not None
            and abs(progress.best_seconds - 22.25) < 1e-6,
            str(progress.best_seconds),
        )
        check(
            "db: plaintext passwords are not stored",
            b"hunter22" not in db_path.read_bytes(),
        )

        store.close()
        reopened = StudentStore(prefer_oracle=False, db_path=db_path)
        check(
            "db: accounts and progress survive a restart",
            reopened.login("alice_01", "hunter22").id == alice.id
            and reopened.get_progress(alice.id, "maths").completed == 2,
        )
        check(
            "exam db: workspace and approved syllabus survive a restart",
            reopened.get_exam_workspace(alice.id, workspace_id)["syllabus_approved"] == 1
            and reopened.get_exam_workspace(alice.id, workspace_id)["topics"] == outline,
        )
        reopened.close()

    # ----------------------------------------------------- document extraction
    with tempfile.TemporaryDirectory() as tmp:
        txt_path = Path(tmp) / "syllabus.txt"
        txt_path.write_text(
            "UNIT 1: Foundations\n- OSI layers\n- TCP/IP model\nUNIT 2: Routing\n1. Distance vector\n",
            encoding="utf-8",
        )
        txt_document = extract_document(txt_path)
        txt_topics = extract_topics(txt_document.text)
        check(
            "exam extraction: TXT text and unit/topic headings extracted",
            len(txt_topics) == 2
            and txt_topics[0]["title"] == "Unit 1 Foundations"
            and "OSI layers" in txt_topics[0]["topics"],
        )

        docx_path = Path(tmp) / "syllabus.docx"
        docx_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>UNIT 1: Data</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Relational model</w:t></w:r></w:p></w:body></w:document>'
        )
        with zipfile.ZipFile(docx_path, "w") as archive:
            archive.writestr("word/document.xml", docx_xml)
        docx_document = extract_document(docx_path)
        check(
            "exam extraction: DOCX paragraphs extracted",
            "Relational model" in docx_document.text
            and "Data" in extract_topics(docx_document.text)[0]["title"],
        )

        pdf_path = Path(tmp) / "syllabus.pdf"
        _write_test_pdf(pdf_path)
        try:
            pdf_document = extract_document(pdf_path)
        except DocumentError as exc:
            check(
                "exam extraction: PDF reports a clear missing dependency",
                "PDF support is unavailable" in str(exc)
                and "pip install pypdf" in str(exc),
            )
        else:
            check(
                "exam extraction: PDF text and page count extracted",
                "Algorithms" in pdf_document.text and pdf_document.page_count == 1,
            )
            scanned_pdf = Path(tmp) / "scanned.pdf"
            _write_blank_pdf(scanned_pdf)
            try:
                extract_document(scanned_pdf)
                scan_detected = False
            except DocumentError as exc:
                scan_detected = "OCR is not configured" in str(exc)
            check("exam extraction: image-only PDF is identified for OCR", scan_detected)

        legacy_path = Path(tmp) / "syllabus.doc"
        legacy_path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
        try:
            extract_document(legacy_path)
            legacy_message = ""
        except DocumentError as exc:
            legacy_message = str(exc)
        check(
            "exam extraction: legacy .doc files explain the .docx/PDF conversion",
            ".docx" in legacy_message and "PDF" in legacy_message,
        )
        unsupported_path = Path(tmp) / "syllabus.rtf"
        unsupported_path.write_text("{\\rtf1 UNIT 1}", encoding="utf-8")
        try:
            extract_document(unsupported_path)
            unsupported_message = ""
        except DocumentError as exc:
            unsupported_message = str(exc)
        check(
            "exam extraction: unsupported formats list the accepted file types",
            "PDF" in unsupported_message
            and ".docx" in unsupported_message
            and "TXT" in unsupported_message,
        )

        valid_outline = validate_topic_tree([{"title": "Unit 1", "topics": ["Manual topic"]}])
        rejects_empty_topic = False
        try:
            validate_topic_tree([{"title": "Unit 1", "topics": [""]}])
        except DocumentError:
            rejects_empty_topic = True
        check(
            "exam topics: edits validate and empty topic names are rejected",
            valid_outline[0]["topics"] == ["Manual topic"] and rejects_empty_topic,
        )

    # ------------------------------------------------------ grounded generation
    generation_units = [{"title": "Unit 1: Networks", "topics": ["OSI layers"]}]
    note_provider = _FakeAIProvider({
        "notes": "The source states that the OSI model has seven layers.",
        "source_status": "supported",
        "source_quote": "The OSI model organizes communication into seven layers.",
    })
    notes = generate_notes(
        note_provider, "Computer Networks", "networks.txt",
        "The OSI model organizes communication into seven layers.",
        generation_units, "standard",
    )
    check(
        "exam notes: AI notes stay grounded, point-wise, and reference-free",
        "seven layers" in notes["text"]
        and "Source:" not in notes["text"]
        and "networks.txt" not in notes["text"]
        and notes["items"][0]["source_reference"] == "networks.txt — Unit 1: Networks / OSI layers"
        and "SOURCE EXCERPT" in note_provider.prompts[0][1]
        and "point-wise" in note_provider.prompts[0][1]
        and "Source file:" not in note_provider.prompts[0][1],
    )
    unavailable_provider = _FakeAIProvider({"notes": "No supporting detail was found.", "source_status": "not_found"})
    unavailable_notes = generate_notes(
        unavailable_provider, "Computer Networks", "networks.txt", "", generation_units, "very short"
    )
    check(
        "exam notes: unsupported material is clearly marked",
        "Not specified in the provided sources." in unavailable_notes["text"],
    )
    manual_notes = generate_notes(
        _FakeAIProvider(), "Computer Networks", "", "Manual syllabus outline\nOSI layers",
        generation_units, "standard",
    )
    check(
        "exam notes: topic-only manual outlines do not generate unsupported facts",
        manual_notes["items"][0]["source_status"] == "not_found"
        and "Upload reference material" in manual_notes["text"],
    )
    invented_quote_provider = _FakeAIProvider({
        "notes": "Unsupported claim.", "source_status": "supported", "source_quote": "invented source quote"
    })
    invented_quote_rejected = False
    try:
        generate_notes(
            invented_quote_provider, "Computer Networks", "networks.txt",
            "The OSI model organizes communication into seven layers.", generation_units, "standard",
        )
    except AIError:
        invented_quote_rejected = True
    check("exam notes: unverifiable source quotes are rejected", invented_quote_rejected)
    # The generation path rejects incomplete output instead of saving fabricated content.
    empty_provider = _FakeAIProvider({"notes": "", "source_status": "not_found"})
    missing_notes_rejected = False
    try:
        generate_notes(
            empty_provider, "Computer Networks", "networks.txt", "",
            generation_units, "very short",
        )
    except AIError:
        missing_notes_rejected = True
    check("exam notes: malformed or empty AI output is rejected", missing_notes_rejected)

    mcq = {
        "question": "How many layers are in the OSI model?",
        "question_type": "multiple choice", "difficulty": "easy", "bloom_level": "remember",
        "marks": 1, "answer": "Seven", "options": ["Five", "Six", "Seven", "Eight"],
        "explanation": "The source states there are seven layers.", "source_topic": "OSI layers",
        "source_quote": "The OSI model organizes communication into seven layers.",
    }
    question_provider = _FakeAIProvider({"questions": [mcq]})
    questions = generate_question_bank(
        question_provider, "Computer Networks", "networks.txt",
        "The OSI model organizes communication into seven layers.",
        generation_units, 1, "easy", "multiple choice",
    )
    check(
        "exam question bank: validates type, answer, Bloom level and source topic",
        len(questions) == 1 and questions[0]["answer"] == "Seven"
        and questions[0]["bloom_level"] == "Remember",
    )
    manual_questions_rejected = False
    try:
        generate_question_bank(
            _FakeAIProvider(), "Computer Networks", "", "Manual syllabus outline\nOSI layers",
            generation_units, 1, "easy", "multiple choice",
        )
    except AIError:
        manual_questions_rejected = True
    check("exam question bank: outline alone cannot produce unsupported answers", manual_questions_rejected)
    duplicate_rejected = False
    try:
        validate_questions([mcq, dict(mcq)], generation_units)
    except AIError as exc:
        duplicate_rejected = "Duplicate" in str(exc)
    check("exam question bank: duplicate questions are rejected", duplicate_rejected)

    # Offline generation keeps the feature usable without any provider or API key.
    local_source = (
        "The OSI model organizes communication into seven layers. "
        "Each OSI layer has a specific responsibility. "
        "The physical layer transmits raw bits over a medium. "
        "The data link layer provides framing and error detection. "
        "The network layer routes packets between networks. "
        "The transport layer provides end-to-end delivery. "
        "The session layer manages dialogues between applications."
    )
    local_notes = generate_local_notes(
        "Computer Networks", "networks.txt", local_source, generation_units, "detailed"
    )
    check(
        "exam notes: offline notes are explanatory, point-wise, and reference-free",
        local_notes["items"][0]["source_status"] == "supported"
        and _contains_source_quote(local_source, local_notes["items"][0]["source_quote"])
        and "seven layers" in local_notes["text"]
        and "**Explanation:**" in local_notes["text"]
        and "**Points:**" in local_notes["text"]
        and "\n1. " in local_notes["text"]
        and "Source:" not in local_notes["text"]
        and "networks.txt" not in local_notes["text"],
    )
    local_manual_notes = generate_local_notes(
        "Computer Networks", "", "Manual syllabus outline\nOSI layers", generation_units, "standard"
    )
    check(
        "exam notes: offline generator does not invent notes for an outline",
        local_manual_notes["items"][0]["source_status"] == "not_found",
    )
    local_mcq = generate_local_question_bank(
        "Computer Networks", "networks.txt", local_source, generation_units,
        5, "medium", "multiple choice",
    )
    check(
        "exam question bank: offline generator returns validated MCQs",
        len(local_mcq) == 5
        and all(
            item["question_type"] == "Multiple Choice"
            and item["difficulty"] == "Medium"
            and len(item["options"]) == 4
            and item["answer"] in item["options"]
            and _contains_source_quote(local_source, item["source_quote"])
            for item in local_mcq
        ),
    )
    local_formats_ok = True
    for local_type in ("true or false", "fill in the blanks", "short answer"):
        try:
            bank = generate_local_question_bank(
                "Computer Networks", "networks.txt", local_source, generation_units,
                3, "easy", local_type,
            )
            local_formats_ok = local_formats_ok and len(bank) == 3 and all(
                item["question_type"].casefold() == local_type for item in bank
            )
        except AIError:
            local_formats_ok = False
    check("exam question bank: offline generator supports several formats", local_formats_ok)
    short_bank = generate_local_question_bank(
        "Computer Networks", "networks.txt", local_source, generation_units,
        2, "easy", "short answer",
    )
    check(
        "exam question bank: short answers carry a substantive reference answer",
        len(short_bank) == 2
        and all(
            item["answer"] != item["source_topic"]
            and len(item["answer"].split()) >= 4
            for item in short_bank
        ),
    )
    structured_source = (
        "Unit 1: OSI Model\n"
        "OSI model layers\n"
        "Encapsulation\n"
        "The OSI model organizes network communication into seven layers. "
        "Encapsulation adds a header at each layer as data moves down the stack."
    )
    structured_units = [{"title": "Unit 1 OSI Model", "topics": ["OSI model layers", "Encapsulation"]}]
    structured_notes = generate_local_notes(
        "Computer Networks", "structured.txt", structured_source, structured_units, "standard"
    )
    structured_quote = structured_notes["items"][0]["source_quote"]
    check(
        "exam notes: syllabus headings are not merged into source evidence",
        "seven layers" in structured_quote
        and not structured_quote.casefold().startswith("unit 1")
        and "Encapsulation\n" not in structured_quote
        and "OSI model layers" in structured_notes["text"]
        and "Encapsulation" in structured_notes["text"],
    )
    local_manual_rejected = False
    try:
        generate_local_question_bank(
            "Computer Networks", "", "Manual syllabus outline\nOSI layers", generation_units,
            1, "easy", "multiple choice",
        )
    except AIError:
        local_manual_rejected = True
    check(
        "exam question bank: offline generator still requires source material",
        local_manual_rejected,
    )

    with tempfile.TemporaryDirectory() as tmp:
        workflow_store = StudentStore(prefer_oracle=False, db_path=Path(tmp) / "exam.db")
        student = workflow_store.register("exam_user", "Exam User", "study123")
        workspace_id = workflow_store.create_exam_workspace(
            student.id, "Computer Networks", "B.Tech", "2027-04-15", 100, 180
        )
        workflow_store.save_syllabus(
            student.id, workspace_id, "networks.txt",
            "The OSI model organizes communication into seven layers.", generation_units,
        )
        approved = workflow_store.approve_syllabus(student.id, workspace_id, generation_units)
        notes_saved = workflow_store.save_exam_content(student.id, workspace_id, "notes", notes)
        questions_saved = workflow_store.save_exam_content(student.id, workspace_id, "questions", questions)
        persisted = workflow_store.get_exam_workspace(student.id, workspace_id)
        check(
            "exam workflow: approved syllabus through generated notes/questions persists",
            approved and notes_saved and questions_saved
            and len(persisted["notes"]["items"]) == 1
            and len(persisted["questions"]) == 1,
        )
        workflow_store.close()

    # ------------------------------------------------ exam practice and mock flow
    check(
        "exam scoring: multiple choice accepts option letters",
        exam_engine.score_answer(
            exam_engine.MCQ, "Seven", "C",
            ["Five", "Six", "Seven", "Eight"],
        ) is True,
    )
    check(
        "exam scoring: fill-in alternatives and one-word answers are normalised",
        exam_engine.score_answer(exam_engine.TRUE_FALSE, "True", "false") is False
        and exam_engine.score_answer(exam_engine.FILL_BLANKS, "seven|7", "7") is True
        and exam_engine.score_answer(exam_engine.ONE_WORD, "OSI", "  osi ") is True,
    )
    check(
        "exam scoring: written and blank answers defer to review",
        exam_engine.score_answer("Long Answer", "reference", "own words") is None
        and exam_engine.score_answer(exam_engine.MCQ, "Seven", "   ") is None,
    )

    session_questions = [
        {
            "question": "How many layers are in the OSI model?", "question_type": "Multiple Choice",
            "options": ["Five", "Seven"], "answer": "Seven", "source_topic": "OSI layers",
            "marks": 2, "difficulty": "Easy", "bloom_level": "Remember",
            "explanation": "The OSI model has seven layers.",
        },
        {
            "question": "TCP/IP has five layers.", "question_type": "True Or False",
            "options": ["True", "False"], "answer": "False", "source_topic": "OSI layers",
            "marks": 1, "difficulty": "Easy", "bloom_level": "Remember",
            "explanation": "The TCP/IP model is commonly described with four layers.",
        },
        {
            "question": "The OSI model has ___ layers.", "question_type": "Fill In The Blanks",
            "options": [], "answer": "seven|7", "source_topic": "OSI layers",
            "marks": 1, "difficulty": "Easy", "bloom_level": "Remember",
            "explanation": "There are seven layers.",
        },
        {
            "question": "Which model is used on the internet?", "question_type": "One-Word Answer",
            "options": [], "answer": "TCP/IP", "source_topic": "TCP/IP",
            "marks": 2, "difficulty": "Easy", "bloom_level": "Remember",
            "explanation": "The internet uses TCP/IP.",
        },
        {
            "question": "Explain distance vector routing.", "question_type": "Long Answer",
            "options": [], "answer": "Neighbours share hop counts.", "source_topic": "Distance vector",
            "marks": 5, "difficulty": "Medium", "bloom_level": "Understand",
            "explanation": "Routers exchange distance vectors with their neighbours.",
        },
    ]

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        sessions_db = Path(tmp) / "sessions.db"
        store = StudentStore(prefer_oracle=False, db_path=sessions_db)
        student = store.register("exam_runner", "Exam Runner", "study123")
        other = store.register("exam_other", "Other Student", "study123")
        workspace_id = store.create_exam_workspace(
            student.id, "Computer Networks", "B.Tech", "2027-05-01", 100, 120
        )
        outline = [
            {"title": "Unit 1: Networks", "topics": ["OSI layers", "TCP/IP"]},
            {"title": "Unit 2: Routing", "topics": ["Distance vector"]},
        ]
        syllabus_text = (
            "UNIT 1: Networks\nThe OSI model has seven layers. "
            "TCP/IP is used on the internet.\n"
            "UNIT 2: Routing\nDistance vector routing shares hop counts."
        )
        store.save_syllabus(student.id, workspace_id, "networks.txt", syllabus_text, outline)
        approved = store.approve_syllabus(student.id, workspace_id, outline)
        store.save_exam_content(student.id, workspace_id, "questions", session_questions)
        synced = store.sync_question_bank(student.id, workspace_id)
        bank = store.list_exam_questions(student.id, workspace_id)
        check(
            "exam bank: approved questions become reviewed rows with unit/topic metadata",
            approved and synced == 5 and len(bank) == 5
            and {item["topic"] for item in bank} == {"OSI layers", "TCP/IP", "Distance vector"},
        )
        check(
            "exam bank: re-syncing an unchanged bank is idempotent",
            store.sync_question_bank(student.id, workspace_id) == 5
            and len(store.list_exam_questions(student.id, workspace_id)) == 5,
        )
        store.save_syllabus(student.id, workspace_id, "networks.txt", syllabus_text, outline)
        unchanged = store.get_exam_workspace(student.id, workspace_id)
        check(
            "exam data safety: re-saving an unchanged draft keeps approval and content",
            unchanged["syllabus_approved"] == 1
            and len(unchanged["questions"]) == 5
            and len(store.list_exam_questions(student.id, workspace_id)) == 5,
        )

        practice = exam_engine.create_session(
            store, student.id, workspace_id, "practice", count=5, seed=7
        )
        practice_id = practice["session"]["session_id"]
        by_type = {
            item["question_type"]: item for item in practice["responses"]
        }
        check(
            "practice: every selected question is snapshotted into the session",
            len(practice["responses"]) == 5
            and practice["session"]["status"] == "in_progress",
        )
        practice_ok = True
        for question_type, answer, status, marks in (
            (exam_engine.MCQ, "Seven", "auto_correct", 2.0),
            (exam_engine.TRUE_FALSE, "false", "auto_correct", 1.0),
            (exam_engine.FILL_BLANKS, "7", "auto_correct", 1.0),
            (exam_engine.ONE_WORD, " tcp/ip ", "auto_correct", 2.0),
            ("Long Answer", "Neighbours exchange hop counts.", "needs_review", 0.0),
        ):
            response = by_type[question_type]
            outcome = exam_engine.practice_check(
                store, student.id, practice_id, response["response_id"], answer
            )
            practice_ok = practice_ok and (
                outcome["status"] == status
                and abs(outcome["awarded_marks"] - marks) < 1e-9
            )
        check(
            "practice: immediate feedback grades objective answers and queues written answers",
            practice_ok,
        )

        wrong = exam_engine.create_session(
            store, student.id, workspace_id, "practice", count=5, seed=11
        )
        wrong_id = wrong["session"]["session_id"]
        wrong_mcq = next(
            item for item in wrong["responses"]
            if item["question_type"] == exam_engine.MCQ
        )
        wrong_outcome = exam_engine.practice_check(
            store, student.id, wrong_id, wrong_mcq["response_id"], "Five"
        )
        check(
            "practice: incorrect objective answers earn no marks",
            wrong_outcome["status"] == "auto_incorrect"
            and wrong_outcome["awarded_marks"] == 0.0
            and wrong_outcome["correct_answer"] == "Seven",
        )
        check(
            "practice: another student cannot read or alter a session",
            store.get_exam_session(other.id, wrong_id) is None
            and not store.save_exam_response(
                other.id, wrong_id, wrong_mcq["response_id"],
                "Seven", True, 2.0, "auto_correct",
            ),
        )

        result = exam_engine.submit_session(store, student.id, practice_id)
        breakdown = {item["topic"]: item for item in result["topics"]}
        check(
            "results: submitted practice reports score, marks and per-topic accuracy",
            result["session"]["status"] == "submitted"
            and abs(result["score"] - 6.0) < 1e-9
            and result["total_marks"] == 11
            and result["needs_review"] == 1
            and breakdown["OSI layers"]["questions"] == 3
            and breakdown["OSI layers"]["correct"] == 3
            and breakdown["Distance vector"]["needs_review"] == 1
            and breakdown["Distance vector"]["accuracy"] is None,
        )
        history = store.list_exam_sessions(student.id, workspace_id)
        check(
            "results: finished sessions appear in history",
            sum(1 for row in history if row["status"] == "submitted") == 1,
        )
        check(
            "practice: abandoning a session preserves it outside scoring",
            exam_engine.abandon_session(store, student.id, wrong_id)
            and store.get_exam_session(student.id, wrong_id)["status"] == "abandoned",
        )

        mock = exam_engine.create_session(
            store, student.id, workspace_id, "mock", count=10,
            target_marks=8, duration_minutes=2, seed=3,
        )
        mock_session = mock["session"]
        mock_id = mock_session["session_id"]
        remaining = exam_engine.remaining_seconds(mock_session)
        check(
            "mock: duration limit, blueprint and target marks are stored",
            mock_session["mode"] == "mock"
            and mock_session["duration_limit_seconds"] == 120
            and mock_session["total_marks"] >= 8
            and mock_session["blueprint"]["target_marks"] == 8
            and remaining is not None and 0 < remaining <= 120,
        )
        expected_score = 0.0
        expected_review = 0
        for response in mock["responses"]:
            snapshot = response["snapshot"]
            if response["question_type"] in exam_engine.OBJECTIVE_TYPES:
                answer = str(snapshot["answer"])
                if response["question_type"] in {
                    exam_engine.FILL_BLANKS, exam_engine.ONE_WORD
                }:
                    answer = answer.split("|")[0].strip() or answer
                expected_score += max(1, int(response["marks"]))
            else:
                answer = "Routes are chosen from neighbours' hop counts."
                expected_review += 1
            store.save_exam_response(
                student.id, mock_id, response["response_id"],
                answer, None, 0.0, "unanswered",
            )
        mock_result = exam_engine.submit_session(store, student.id, mock_id)
        check(
            "mock: submission auto-grades objective answers and flags written answers",
            abs(mock_result["score"] - expected_score) < 1e-9
            and mock_result["needs_review"] == expected_review
            and mock_result["session"]["status"] == "submitted",
        )

        submitted_rows = [
            row for row in store.list_exam_sessions(student.id, workspace_id)
            if row["status"] == "submitted"
        ]
        expected_analytics_rows = sum(
            len(store.list_exam_responses(student.id, int(row["session_id"])))
            for row in submitted_rows
        )
        analytics_records = store.list_exam_analytics_records(
            student.id, workspace_id
        )
        check(
            "analytics db: only submitted session responses are returned",
            len(analytics_records) == expected_analytics_rows
            and len(submitted_rows) == 2
            and all(
                row["session_id"] != wrong_id for row in analytics_records
            )
            and all(row["snapshot"].get("bloom_level") for row in analytics_records),
        )
        check(
            "analytics db: another student cannot read analytics records",
            store.list_exam_analytics_records(other.id, workspace_id) == [],
        )
        empty_workspace = store.create_exam_workspace(
            student.id, "Physics", "", "", 50, 60
        )
        check(
            "analytics db: workspace filtering protects other subjects",
            store.list_exam_analytics_records(student.id, empty_workspace) == [],
        )
        analytics_dashboard = exam_analytics.build_dashboard(
            analytics_records,
            ["OSI layers", "TCP/IP", "Distance vector"],
            "Computer Networks",
        )
        graded_records = [
            row for row in analytics_records
            if row["review_status"] in exam_analytics.GRADED_STATUSES
        ]
        graded_correct = sum(
            1 for row in graded_records
            if row["review_status"] == "auto_correct"
        )
        check(
            "analytics db: dashboard uses the real submitted history",
            analytics_dashboard["has_data"]
            and analytics_dashboard["session_count"] == 2
            and analytics_dashboard["questions_attempted"]
            == sum(
                1 for row in analytics_records
                if row["review_status"] != "unanswered"
            )
            and analytics_dashboard["needs_review"]
            == sum(
                1 for row in analytics_records
                if row["review_status"] == "needs_review"
            )
            and abs(
                analytics_dashboard["accuracy"]
                - graded_correct / len(graded_records) * 100
            ) < 1e-9
            and {"OSI layers", "TCP/IP", "Distance vector"}
            <= {topic["topic"] for topic in analytics_dashboard["topics"]},
        )
        check(
            "analytics db: mastery and trend outputs stay inside defined states",
            all(
                topic["mastery"] in {
                    exam_analytics.MASTERY_NOT_STARTED,
                    exam_analytics.MASTERY_LEARNING,
                    exam_analytics.MASTERY_NEEDS_IMPROVEMENT,
                    exam_analytics.MASTERY_MASTERED,
                }
                for topic in analytics_dashboard["topics"]
            )
            and analytics_dashboard["trend"]["status"] in {
                "insufficient_data", "improving", "declining", "steady",
            },
        )
        store.close()
        reopened_analytics = StudentStore(
            prefer_oracle=False, db_path=sessions_db
        )
        check(
            "analytics db: analytics records survive a restart",
            len(reopened_analytics.list_exam_analytics_records(
                student.id, workspace_id
            )) == len(analytics_records),
        )
        reopened_analytics.close()
        schema_conn = sqlite3.connect(sessions_db)
        try:
            response_columns = {
                row[1] for row in schema_conn.execute(
                    "PRAGMA table_info(exam_responses)"
                )
            }
            session_columns = {
                row[1] for row in schema_conn.execute(
                    "PRAGMA table_info(exam_sessions)"
                )
            }
            question_columns = {
                row[1] for row in schema_conn.execute(
                    "PRAGMA table_info(exam_questions)"
                )
            }
            response_indexes = {
                row[1] for row in schema_conn.execute(
                    "PRAGMA index_list(exam_responses)"
                )
            }
            session_indexes = {
                row[1] for row in schema_conn.execute(
                    "PRAGMA index_list(exam_sessions)"
                )
            }
        finally:
            schema_conn.close()
        check(
            "analytics migration: Phase 1 columns and indexes are sufficient",
            {"topic", "question_type", "review_status", "awarded_marks",
             "question_snapshot_json"} <= response_columns
            and {"mode", "status", "total_marks", "score_marks",
                 "needs_review", "submitted_at"} <= session_columns
            and "bloom_level" in question_columns
            and "idx_exam_responses_topic" in response_indexes
            and "idx_exam_sessions_student" in session_indexes,
        )

        store = StudentStore(prefer_oracle=False, db_path=sessions_db)
        store.save_syllabus(
            student.id, workspace_id, "networks-v2.txt",
            syllabus_text + "\nUnit 3: Extra", [{"title": "Unit 1: Networks", "topics": ["OSI layers"]}],
        )
        changed = store.get_exam_workspace(student.id, workspace_id)
        check(
            "exam data safety: a changed syllabus revokes approval and empties the bank",
            changed["syllabus_approved"] == 0
            and changed["questions"] == []
            and changed["notes"] == []
            and store.list_exam_questions(student.id, workspace_id) == [],
        )
        store.close()

    now = datetime.now(timezone.utc)
    check(
        "exam timing: countdown accepts SQLite strings and Oracle datetimes",
        exam_engine.remaining_seconds(
            {"duration_limit_seconds": 120, "started_at": now}
        ) <= 120
        and exam_engine.remaining_seconds(
            {"duration_limit_seconds": 120, "started_at": now.isoformat()}
        ) <= 120,
    )

    analytics_now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)

    def analytics_entry(
        topic, status="auto_correct", question_type="Multiple Choice",
        bloom="Remember", marks=1,
    ):
        return {
            "topic": topic,
            "status": status,
            "question_type": question_type,
            "bloom": bloom,
            "marks": marks,
        }

    def analytics_session(session_id, days_ago, entries, mode="practice"):
        stamp = (analytics_now - timedelta(days=days_ago)).isoformat()
        total_marks = sum(max(1, int(entry["marks"])) for entry in entries)
        score = sum(
            max(1, int(entry["marks"]))
            for entry in entries if entry["status"] == "auto_correct"
        )
        return [
            {
                "session_id": session_id,
                "workspace_id": 1,
                "mode": mode,
                "total_marks": total_marks,
                "score_marks": score,
                "needs_review": sum(
                    1 for entry in entries
                    if entry["status"] == "needs_review"
                ),
                "started_at": stamp,
                "submitted_at": stamp,
                "response_id": session_id * 1000 + position,
                "position": position,
                "unit_title": "",
                "topic": entry["topic"],
                "question_type": entry["question_type"],
                "marks": max(1, int(entry["marks"])),
                "is_correct": (
                    True if entry["status"] == "auto_correct"
                    else False if entry["status"] == "auto_incorrect"
                    else None
                ),
                "awarded_marks": (
                    max(1, int(entry["marks"]))
                    if entry["status"] == "auto_correct" else 0.0
                ),
                "review_status": entry["status"],
                "snapshot": {"bloom_level": entry["bloom"]},
                "answered_at": (
                    None if entry["status"] == "unanswered" else stamp
                ),
            }
            for position, entry in enumerate(entries)
        ]

    range_records = (
        analytics_session(101, 2, [analytics_entry("Recent")])
        + analytics_session(102, 10, [analytics_entry("Earlier")])
        + analytics_session(103, 40, [analytics_entry("Old")])
    )
    check(
        "analytics range: 7-day, 30-day and all-time filters use submission dates",
        len(exam_analytics.apply_range_filter(
            range_records, "Last 7 Days", analytics_now
        )) == 1
        and len(exam_analytics.apply_range_filter(
            range_records, "Last 30 Days", analytics_now
        )) == 2
        and len(exam_analytics.apply_range_filter(
            range_records, "All Time", analytics_now
        )) == 3
        and exam_analytics.build_dashboard(
            range_records, ["Recent", "Earlier", "Old"], "Maths",
            "Last 7 Days", analytics_now,
        )["session_count"] == 1,
    )

    empty_dashboard = exam_analytics.build_dashboard(
        [], ["Algebra", "Geometry"], "Maths", "All Time", analytics_now
    )
    check(
        "analytics sufficiency: no history produces no fabricated stats or advice",
        empty_dashboard["has_data"] is False
        and empty_dashboard["accuracy"] is None
        and len(empty_dashboard["topics"]) == 2
        and all(
            topic["mastery"] == exam_analytics.MASTERY_NOT_STARTED
            and topic["accuracy"] is None
            for topic in empty_dashboard["topics"]
        )
        and empty_dashboard["recommendations"] == []
        and empty_dashboard["trend"]["status"] == "insufficient_data"
        and "nothing is estimated" in empty_dashboard["notes"][0],
    )

    mastery_records = (
        analytics_session(201, 20, [
            analytics_entry("Weak topic"),
            analytics_entry("Weak topic"),
            analytics_entry("Weak topic", "auto_incorrect"),
            analytics_entry("Weak topic", "auto_incorrect"),
            *[analytics_entry(
                "Declining topic", bloom="Analyze"
            ) for _ in range(6)],
            *[analytics_entry(
                "Mastered topic", question_type="One-Word Answer",
                bloom="Understand",
            ) for _ in range(4)],
            analytics_entry(
                "Learning topic", question_type="True Or False"
            ),
            analytics_entry(
                "Learning topic", question_type="True Or False"
            ),
            analytics_entry(
                "Learning topic", question_type="True Or False"
            ),
            analytics_entry(
                "Learning topic", "auto_incorrect",
                question_type="True Or False",
            ),
            analytics_entry(
                "Small sample", "auto_incorrect", bloom="Apply"
            ),
            analytics_entry("Missing Bloom", bloom=""),
        ])
        + analytics_session(202, 10, [
            analytics_entry("Weak topic"),
            analytics_entry("Weak topic"),
            analytics_entry("Weak topic", "auto_incorrect"),
            analytics_entry("Weak topic", "auto_incorrect"),
            analytics_entry("Declining topic", bloom="Analyze"),
            analytics_entry("Declining topic", "auto_incorrect", bloom="Analyze"),
            analytics_entry("Declining topic", "auto_incorrect", bloom="Analyze"),
            analytics_entry("Declining topic", "auto_incorrect", bloom="Analyze"),
            *[analytics_entry(
                "Mastered topic", question_type="One-Word Answer",
                bloom="Understand",
            ) for _ in range(4)],
            analytics_entry(
                "Learning topic", question_type="True Or False"
            ),
            analytics_entry(
                "Learning topic", "needs_review",
                question_type="Long Answer", bloom="", marks=5,
            ),
        ])
    )
    mastery_dashboard = exam_analytics.build_dashboard(
        mastery_records,
        ["Weak topic", "Declining topic", "Mastered topic", "Learning topic",
         "Small sample", "Missing Bloom", "Not started"],
        "Networks",
        "All Time",
        analytics_now,
    )
    topics = {topic["topic"]: topic for topic in mastery_dashboard["topics"]}
    check(
        "analytics accuracy: attempts, correct/incorrect and marks are aggregated",
        abs(mastery_dashboard["accuracy"] - (24 / 33) * 100) < 1e-9
        and mastery_dashboard["graded_answers"] == 33
        and mastery_dashboard["questions_attempted"] == 34
        and mastery_dashboard["questions_total"] == 34
        and mastery_dashboard["needs_review"] == 1
        and mastery_dashboard["marks_total"] == 38
        and abs(mastery_dashboard["marks_awarded"] - 24.0) < 1e-9
        and topics["Weak topic"]["graded"] == 8
        and topics["Weak topic"]["incorrect"] == 4
        and abs(topics["Weak topic"]["accuracy"] - 50.0) < 1e-9,
    )
    check(
        "analytics mastery: evidence-based states distinguish weakness and mastery",
        topics["Weak topic"]["status"] == "weak"
        and topics["Weak topic"]["mastery"]
        == exam_analytics.MASTERY_NEEDS_IMPROVEMENT
        and topics["Declining topic"]["status"] == "developing"
        and topics["Declining topic"]["declining"] is True
        and topics["Declining topic"]["mastery"]
        == exam_analytics.MASTERY_NEEDS_IMPROVEMENT
        and topics["Mastered topic"]["mastery"]
        == exam_analytics.MASTERY_MASTERED
        and topics["Learning topic"]["mastery"]
        == exam_analytics.MASTERY_LEARNING
        and topics["Not started"]["mastery"]
        == exam_analytics.MASTERY_NOT_STARTED
        and topics["Small sample"]["status"] == "insufficient_data"
        and topics["Small sample"]["mastery"]
        == exam_analytics.MASTERY_LEARNING,
    )
    check(
        "analytics recommendations: only sufficient weak topics get practice actions",
        [item["topic"] for item in mastery_dashboard["recommendations"]]
        == ["Declining topic", "Weak topic"]
        and all(
            "10-question practice" in item["action"]
            for item in mastery_dashboard["recommendations"]
        )
        and all(
            item["topic"] != "Small sample"
            for item in mastery_dashboard["recommendations"]
        )
        and {"Small sample", "Missing Bloom"} <= {
            item["topic"] for item in mastery_dashboard["evidence_needed"]
        },
    )
    check(
        "analytics difficulty: type and Bloom levels are compared only with enough data",
        mastery_dashboard["hardest_question_type"]["name"] == "Multiple Choice"
        and abs(
            mastery_dashboard["hardest_question_type"]["accuracy"] - 60.0
        ) < 1e-9
        and mastery_dashboard["hardest_bloom_level"]["name"] == "Remember"
        and any(
            item["name"] == "Unspecified" and item["graded"] == 1
            for item in mastery_dashboard["bloom_levels"]
        ),
    )
    check(
        "analytics range: the selected range changes mastery evidence",
        exam_analytics.build_dashboard(
            mastery_records, ["Weak topic"], "Networks",
            "Last 7 Days", analytics_now,
        )["has_data"] is False
        and exam_analytics.build_dashboard(
            mastery_records, ["Weak topic"], "Networks",
            "Last 30 Days", analytics_now,
        )["session_count"] == 2,
    )

    improve_dashboard = exam_analytics.build_dashboard(
        analytics_session(301, 10, [
            analytics_entry("Trend", "auto_incorrect") for _ in range(3)
        ] + [analytics_entry("Trend") for _ in range(2)])
        + analytics_session(302, 2, [
            analytics_entry("Trend") for _ in range(5)
        ]),
        ["Trend"], "Trends", "All Time", analytics_now,
    )
    decline_dashboard = exam_analytics.build_dashboard(
        analytics_session(311, 10, [
            analytics_entry("Trend") for _ in range(5)
        ])
        + analytics_session(312, 2, [
            analytics_entry("Trend", "auto_incorrect") for _ in range(3)
        ] + [analytics_entry("Trend") for _ in range(2)]),
        ["Trend"], "Trends", "All Time", analytics_now,
    )
    steady_dashboard = exam_analytics.build_dashboard(
        analytics_session(321, 10, [
            analytics_entry("Trend") for _ in range(3)
        ] + [analytics_entry("Trend", "auto_incorrect") for _ in range(2)])
        + analytics_session(322, 2, [
            analytics_entry("Trend") for _ in range(3)
        ] + [analytics_entry("Trend", "auto_incorrect") for _ in range(2)]),
        ["Trend"], "Trends", "All Time", analytics_now,
    )
    short_dashboard = exam_analytics.build_dashboard(
        analytics_session(331, 2, [
            analytics_entry("Trend") for _ in range(5)
        ]),
        ["Trend"], "Trends", "All Time", analytics_now,
    )
    check(
        "analytics trend: improvement, decline, steady and insufficient history",
        improve_dashboard["trend"]["status"] == "improving"
        and decline_dashboard["trend"]["status"] == "declining"
        and steady_dashboard["trend"]["status"] == "steady"
        and short_dashboard["trend"]["status"] == "insufficient_data"
        and short_dashboard["recommendations"] == [],
    )

    coverage_dashboard = exam_analytics.build_dashboard(
        analytics_session(341, 5, [
            analytics_entry("Coverage") for _ in range(8)
        ] + [
            analytics_entry("Coverage", "unanswered") for _ in range(3)
        ]),
        ["Coverage"], "Coverage", "All Time", analytics_now,
    )
    coverage_topic = coverage_dashboard["topics"][0]
    check(
        "analytics mastery: skipped questions block Mastered until coverage is sufficient",
        coverage_topic["mastery"] != exam_analytics.MASTERY_MASTERED
        and coverage_topic["unanswered"] == 3
        and "coverage" in coverage_topic["mastery_evidence"],
    )

    tiny_latest_dashboard = exam_analytics.build_dashboard(
        analytics_session(351, 8, [
            analytics_entry("Trend") for _ in range(5)
        ])
        + analytics_session(352, 6, [
            analytics_entry("Trend") for _ in range(5)
        ])
        + analytics_session(353, 4, [
            analytics_entry("Trend") for _ in range(5)
        ])
        + analytics_session(354, 1, [
            analytics_entry("Trend", "auto_incorrect")
        ]),
        ["Trend"], "Trends", "All Time", analytics_now,
    )
    check(
        "analytics trend: a one-answer session cannot reverse a stable trend",
        tiny_latest_dashboard["trend"]["status"] != "declining",
    )
    check(
        "analytics labels: percentages show enough precision to match thresholds",
        exam_analytics.format_percent(79.59) == "79.6%"
        and exam_analytics.format_percent(80.0) == "80%",
    )

    old_ai_env = {key: os.environ.get(key) for key in (
        "CODELOCK_AI_PROVIDER", "CODELOCK_AI_MODEL", "CODELOCK_AI_API_KEY", "CODELOCK_AI_ENDPOINT"
    )}
    try:
        for key in old_ai_env:
            os.environ.pop(key, None)
        unavailable = False
        try:
            AIProvider.from_environment()
        except AIError:
            unavailable = True
    finally:
        for key, value in old_ai_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    check("AI provider: unavailable configuration fails clearly without fallback content", unavailable)

    check(
        "grounding: a short generic quote cannot certify source support",
        not _contains_source_quote("The OSI model has seven layers.", "the")
        and _contains_source_quote(
            "The OSI model has seven layers.", "OSI model has seven layers"
        ),
    )

    class _FixtureProvider:
        def __init__(self, payload):
            self.payload = payload

        def generate_json(self, _system, _prompt):
            return self.payload

    untrusted_notes = generate_notes(
        _FixtureProvider({
            "notes": "OSI actually has nine layers.",
            "source_status": "not_found",
            "source_quote": "",
        }),
        "Networks", "networks.txt", "The OSI model has seven layers.",
        [{"title": "Unit 1", "topics": ["OSI model"]}], "standard",
    )["items"][0]
    check(
        "grounding: not_found notes cannot carry invented facts into the saved bank",
        "nine layers" not in untrusted_notes["notes"]
        and "Not specified" in untrusted_notes["notes"],
    )

    key_env = {key: os.environ.get(key) for key in (
        "CODELOCK_AI_PROVIDER", "CODELOCK_AI_MODEL",
        "CODELOCK_AI_API_KEY", "CODELOCK_AI_ENDPOINT",
    )}
    try:
        os.environ.update({
            "CODELOCK_AI_PROVIDER": "openai-compatible",
            "CODELOCK_AI_MODEL": "fixture",
            "CODELOCK_AI_ENDPOINT": "http://127.0.0.1:1/v1/chat/completions",
            "CODELOCK_AI_API_KEY": "key\ninjected",
        })
        invalid_key_rejected = False
        try:
            AIProvider.from_environment()
        except AIError:
            invalid_key_rejected = True
    finally:
        for key, value in key_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    check(
        "AI provider: control characters in the API key are rejected before use",
        invalid_key_rejected,
    )

    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _ProviderStub(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            if self.path == "/shape":
                body = b'{"choices": []}'
                status = 200
            elif self.path == "/rate":
                body = b'{"error": "slow down"}'
                status = 429
            elif self.path == "/malformed":
                body = b"not json at all"
                status = 200
            elif self.path == "/slow":
                time.sleep(1.0)
                body = b'{"choices": [{"message": {"content": "{}"}}]}'
                status = 200
            else:
                body = b"upstream rejected key-123456"
                status = 400
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderStub)
    server.handle_error = lambda *_args: None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        key_provider = AIProvider(
            "openai-compatible",
            f"http://127.0.0.1:{server.server_port}/reject",
            "fixture",
            "key-123456",
            timeout_seconds=5,
        )
        try:
            key_provider.generate_json("system", "prompt")
            key_error = ""
        except AIError as exc:
            key_error = str(exc)
        shape_provider = AIProvider(
            "openai-compatible",
            f"http://127.0.0.1:{server.server_port}/shape",
            "fixture",
            "",
            timeout_seconds=5,
        )
        try:
            shape_provider.generate_json("system", "prompt")
            shape_error = ""
        except AIError as exc:
            shape_error = str(exc)
        rate_provider = AIProvider(
            "openai-compatible",
            f"http://127.0.0.1:{server.server_port}/rate",
            "fixture",
            "",
            timeout_seconds=5,
        )
        try:
            rate_provider.generate_json("system", "prompt")
            rate_error = ""
        except AIError as exc:
            rate_error = str(exc)
        malformed_provider = AIProvider(
            "openai-compatible",
            f"http://127.0.0.1:{server.server_port}/malformed",
            "fixture",
            "",
            timeout_seconds=5,
        )
        try:
            malformed_provider.generate_json("system", "prompt")
            malformed_error = ""
        except AIError as exc:
            malformed_error = str(exc)
        unreachable_provider = AIProvider(
            "openai-compatible",
            "http://127.0.0.1:1/chat/completions",
            "fixture",
            "",
            timeout_seconds=2,
        )
        try:
            unreachable_provider.generate_json("system", "prompt")
            unreachable_error = ""
        except AIError as exc:
            unreachable_error = str(exc)
        slow_provider = AIProvider(
            "openai-compatible",
            f"http://127.0.0.1:{server.server_port}/slow",
            "fixture",
            "",
            timeout_seconds=0.2,
        )
        try:
            slow_provider.generate_json("system", "prompt")
            slow_error = ""
        except AIError as exc:
            slow_error = str(exc)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    check(
        "AI provider: API keys are redacted from surfaced HTTP errors",
        "key-123456" not in key_error
        and "[redacted]" in key_error
        and "HTTP 400" in key_error,
        key_error,
    )
    check(
        "AI provider: a valid JSON envelope with no message is reported accurately",
        "missing the expected chat message" in shape_error
        and "did not return valid JSON" not in shape_error,
        shape_error,
    )
    check(
        "AI provider: a rate limit is reported without provider detail",
        "rate limit" in rate_error.lower(),
        rate_error,
    )
    check(
        "AI provider: non-JSON output is rejected as invalid",
        "did not return valid JSON" in malformed_error,
        malformed_error,
    )
    check(
        "AI provider: an unreachable endpoint fails clearly",
        "Could not reach the AI provider" in unreachable_error,
        unreachable_error,
    )
    check(
        "AI provider: a slow endpoint hits the configured timeout",
        "Could not reach the AI provider" in slow_error,
        slow_error,
    )

    # ------------------------------------------------------------- judge pipeline
    judge = Judge()
    original_admin_check = judge_module.is_admin
    try:
        judge_module.is_admin = lambda: True
        privileged_result = judge.evaluate(
            get_problem("addition"), "raise RuntimeError('must not execute')"
        )
    finally:
        judge_module.is_admin = original_admin_check
    check(
        "judge: elevated execution is refused before launching code",
        not privileged_result.ok and "administrator/root" in privileged_result.message,
    )

    sentinel_name = "CODELOCK_SELFTEST_SECRET"
    previous_secret = os.environ.get(sentinel_name)
    os.environ[sentinel_name] = "must-not-reach-submission"
    try:
        result = judge.evaluate(
            get_problem("addition"),
            "import os\n"
            "secret_visible = 'CODELOCK_SELFTEST_SECRET' in os.environ\n"
            "def add(a, b):\n"
            "    return 0 if secret_visible else a + b\n",
        )
    finally:
        if previous_secret is None:
            os.environ.pop(sentinel_name, None)
        else:
            os.environ[sentinel_name] = previous_secret
    check("judge: parent environment secrets are not inherited", result.ok)

    for problem in PROBLEMS:
        result = judge.evaluate(problem, REFERENCE_SOLUTIONS[problem.key])
        check(f"judge: {problem.key} reference solution passes", result.ok, result.message)

    result = judge.evaluate(
        get_problem("two_sum"), "def two_sum(nums, target):\n    return False\n"
    )
    check("judge: wrong answer is rejected", not result.ok, result.message)

    result = judge.evaluate(
        get_problem("addition"),
        "def add(a, b):\n    return 0 if a < 0 and b < 0 else a + b\n",
        include_hidden=False,
    )
    samples_only = result.ok and result.tests_total == 3
    result = judge.evaluate(
        get_problem("addition"),
        "def add(a, b):\n    return 0 if a < 0 and b < 0 else a + b\n",
        include_hidden=True,
    )
    check(
        "judge: hidden tests reject sample-only solutions",
        samples_only
        and not result.ok
        and result.tests_total > 3
        and 3 < result.tests_passed < result.tests_total
        and "Hidden test" in result.message,
        result.message,
    )

    result = judge.evaluate(
        get_problem("addition"),
        "calls = 0\n"
        "def add(a, b):\n"
        "    global calls\n"
        "    calls += 1\n"
        "    if calls == 2:\n"
        "        raise RuntimeError('second case')\n"
        "    return a + b\n",
    )
    check(
        "judge: failed attempts retain the number of earlier passing tests",
        not result.ok and result.tests_passed == 1 and result.tests_total == 33,
        f"passed={result.tests_passed}, total={result.tests_total}",
    )

    result = judge.evaluate(
        get_problem("addition"),
        "def add(a, b):\n    print('x' * 500000)\n    return a + b\n",
    )
    check(
        "judge: large stdout is drained without unbounded capture",
        result.ok and len(result.student_output) <= 2000,
        f"ok={result.ok}, captured={len(result.student_output)}",
    )

    result = judge.evaluate(get_problem("addition"), "#" + ("x" * 65536))
    check("judge: oversized source is rejected", not result.ok and "too large" in result.message)

    result = judge.evaluate(
        get_problem("max_subarray"), "def something_else(nums):\n    return 0\n"
    )
    check("judge: missing function is rejected", not result.ok, result.message)

    result = judge.evaluate(get_problem("two_sum"), "def two_sum(:\n")
    check("judge: syntax error is reported, not crashed", not result.ok, result.message)

    result = judge.evaluate(
        get_problem("two_sum"), "raise RuntimeError('boom')\n"
    )
    check("judge: import-time crash is reported", not result.ok, result.message)

    quick_judge = Judge(timeout=0.6)
    result = quick_judge.evaluate(
        get_problem("two_sum"),
        "def two_sum(nums, target):\n    while True:\n        pass\n",
    )
    check("judge: infinite loop hits the timeout", result.timed_out, result.message)

    # -------------------------------------------- judge forgery regressions
    init_payload = judge_module._build_init_payload("code", "fn", "prefix", 3)
    check(
        "judge: worker init payload contains no test data",
        set(init_payload)
        == {"code", "function_name", "prefix", "cpu_seconds", "memory_bytes"},
        repr(sorted(init_payload)),
    )
    check(
        "judge: harness source contains no expected values or test list",
        "expected" not in judge_module.HARNESS
        and "tests" not in judge_module.HARNESS,
    )

    frame_read_attack = (
        "import sys\n"
        "def add(a, b):\n"
        "    data = sys._getframe(1).f_globals\n"
        "    print('GLOBALS:' + ','.join(sorted(data)))\n"
        "    cases = data.get('tests')\n"
        "    if cases:\n"
        "        for case in cases:\n"
        "            if tuple(case['args']) == (a, b):\n"
        "                return case['expected']\n"
        "    return -999999\n"
    )
    result = judge.evaluate(get_problem("addition"), frame_read_attack)
    check(
        "judge: frame-reading attack cannot reach hidden tests or expected values",
        not result.ok
        and "tests" not in result.student_output
        and "expected" not in result.student_output,
        result.message,
    )

    clear_attack = (
        "import sys\n"
        "def add(a, b):\n"
        "    data = sys._getframe(1).f_globals\n"
        "    for name in ('tests', 'cases', 'expected'):\n"
        "        value = data.get(name)\n"
        "        if isinstance(value, list):\n"
        "            value[:] = []\n"
        "    return 0\n"
    )
    result = judge.evaluate(get_problem("addition"), clear_attack)
    check(
        "judge: clearing harness lists cannot force a pass",
        not result.ok,
        result.message,
    )

    forged_ready_attack = (
        "import json, os, sys\n"
        "def add(a, b):\n"
        "    prefix = sys._getframe(1).f_globals.get('_prefix', '')\n"
        "    if prefix:\n"
        "        sys.stdout.write(prefix + json.dumps({'kind': 'ready'}) + chr(10))\n"
        "        sys.stdout.flush()\n"
        "    os._exit(0)\n"
    )
    result = judge.evaluate(get_problem("addition"), forged_ready_attack)
    check(
        "judge: forged ready frame plus os._exit is rejected",
        not result.ok,
        result.message,
    )

    forged_result_attack = (
        "import json, os, sys\n"
        "def add(a, b):\n"
        "    prefix = sys._getframe(1).f_globals.get('_prefix', '')\n"
        "    if prefix:\n"
        "        frame = {'kind': 'result', 'seq': 0, 'value': {'t': 'int', 'v': a + b},"
        " 'ok': True, 'passed': 999}\n"
        "        sys.stdout.write(prefix + json.dumps(frame) + chr(10))\n"
        "        sys.stdout.flush()\n"
        "    os._exit(0)\n"
    )
    result = judge.evaluate(get_problem("addition"), forged_result_attack)
    check(
        "judge: forged result frame and os._exit cannot pass",
        not result.ok,
        result.message,
    )

    legacy_marker_attack = (
        "import json, os\n"
        "def add(a, b):\n"
        "    print('@@CODELOCK_RESULT@@:deadbeef:' +"
        " json.dumps({'ok': True, 'passed': 999}))\n"
        "    os._exit(0)\n"
    )
    result = judge.evaluate(get_problem("addition"), legacy_marker_attack)
    check(
        "judge: legacy forged verdict output is ignored",
        not result.ok,
        result.message,
    )

    result = judge.evaluate(
        get_problem("addition"),
        "class AlwaysEqual:\n"
        "    def __eq__(self, other):\n"
        "        return True\n"
        "\n"
        "def add(a, b):\n"
        "    return AlwaysEqual()\n",
    )
    check(
        "judge: non-primitive results are rejected",
        not result.ok and "unsupported type" in result.message,
        result.message,
    )

    result = judge.evaluate(
        get_problem("addition"), "def add(a, b):\n    return True\n"
    )
    check(
        "judge: bool is not accepted as an int",
        not result.ok and "Sample test 1 failed" in result.message,
        result.message,
    )

    if os.name == "nt":
        job = judge_module._create_job(3)
        try:
            check("judge: Windows Job Object with limits is available", bool(job))
        finally:
            if job:
                judge_module._close_job(job)

    with tempfile.TemporaryDirectory() as cleanup_dir:
        marker = Path(cleanup_dir) / "grandchild-alive.txt"
        child_code = (
            "import time, pathlib; "
            f"time.sleep(2); pathlib.Path({str(marker)!r}).write_text('alive')"
        )
        spawner = (
            "def add(a, b):\n"
            "    import subprocess, sys\n"
            f"    kwargs = {{'creationflags': 0x08000000}} if sys.platform == 'win32' else {{}}\n"
            f"    subprocess.Popen([sys.executable, '-c', {child_code!r}], **kwargs)\n"
            "    return a + b\n"
        )
        result = judge.evaluate(
            get_problem("addition"), spawner, include_hidden=False
        )
        time.sleep(2.5)
        check(
            "judge: spawned descendants are terminated with the worker",
            result.ok and not marker.exists(),
            f"ok={result.ok}, marker={marker.exists()}",
        )

    shutdown_judge = Judge(timeout=10)
    shutdown_results = []
    shutdown_thread = threading.Thread(
        target=lambda: shutdown_results.append(
            shutdown_judge.evaluate(
                get_problem("addition"),
                "import time\ndef add(a, b):\n    time.sleep(9)\n    return a + b\n",
            )
        )
    )
    shutdown_thread.start()
    time.sleep(0.4)
    shutdown_started = time.perf_counter()
    shutdown_judge.shutdown()
    shutdown_thread.join(5)
    check(
        "judge: shutdown terminates an active worker promptly",
        not shutdown_thread.is_alive()
        and bool(shutdown_results)
        and not shutdown_results[0].ok
        and time.perf_counter() - shutdown_started < 3,
        f"alive={shutdown_thread.is_alive()}",
    )

    confirmation = gui_module.CodeLockApp.__new__(gui_module.CodeLockApp)
    confirmation._shutting_down = False
    confirmation.judging = True
    confirmation.locked = True
    confirmation.root = object()
    label_states = []
    confirmation.judge_state_label = SimpleNamespace(
        configure=lambda **kwargs: label_states.append(kwargs.get("text"))
    )
    confirmation._set_controls_enabled = lambda enabled: None
    confirmation._log = lambda *args, **kwargs: None
    recorded_results = []
    confirmation._record_attempt = lambda passed, result: recorded_results.append(passed)
    unlock_calls = []
    confirmation._unlock = lambda: unlock_calls.append(True)
    pass_result = JudgeResult(
        ok=True,
        message="All 3 tests passed.",
        tests_passed=3,
        tests_total=3,
        duration=0.1,
    )
    old_confirm = gui_module.messagebox.askyesno
    try:
        gui_module.messagebox.askyesno = lambda *args, **kwargs: False
        confirmation._judge_finished(pass_result, None, True)
        declined_stays_locked = (
            not unlock_calls and recorded_results == [True] and "PASSED - LOCKED" in label_states
        )
        gui_module.messagebox.askyesno = lambda *args, **kwargs: True
        confirmation._judge_finished(pass_result, None, True)
        confirmed_unlocks = unlock_calls == [True]
    finally:
        gui_module.messagebox.askyesno = old_confirm
    check(
        "gui: a judge pass requires explicit confirmation before unlocking",
        declined_stays_locked and confirmed_unlocks,
        f"declined={declined_stays_locked}, confirmed={confirmed_unlocks}",
    )

    # ---------------------------------------------------------- emergency exit
    emergency = gui_module.CodeLockApp.__new__(gui_module.CodeLockApp)
    emergency._shutting_down = False
    emergency.locked = True
    emergency.root = object()
    emergency._active_modal = lambda: None
    emergency._log = lambda *args, **kwargs: None
    exit_calls = []
    emergency._shutdown = lambda: exit_calls.append(True)
    old_password = config.ADMIN_PASSWORD
    old_askyesno = gui_module.messagebox.askyesno
    old_askstring = gui_module.simpledialog.askstring
    old_showerror = gui_module.messagebox.showerror
    try:
        config.ADMIN_PASSWORD = ""
        gui_module.messagebox.askyesno = lambda *args, **kwargs: True
        no_password_exit = emergency._emergency_exit() == "break" and bool(exit_calls)
        exit_calls.clear()
        config.ADMIN_PASSWORD = "test-emergency-secret"
        gui_module.simpledialog.askstring = lambda *args, **kwargs: "wrong"
        gui_module.messagebox.showerror = lambda *args, **kwargs: None
        wrong_password_stays = emergency._emergency_exit() == "break" and not exit_calls
        gui_module.simpledialog.askstring = lambda *args, **kwargs: "test-emergency-secret"
        configured_password_exits = emergency._emergency_exit() == "break" and bool(exit_calls)
        exit_calls.clear()
        config.ADMIN_PASSWORD = "pässwörd"
        gui_module.simpledialog.askstring = lambda *args, **kwargs: "pässwörd"
        non_ascii_password_exits = (
            emergency._emergency_exit() == "break" and bool(exit_calls)
        )
        exit_calls.clear()
        gui_module.simpledialog.askstring = lambda *args, **kwargs: "wrong"
        non_ascii_mismatch_safe = (
            emergency._emergency_exit() == "break" and not exit_calls
        )
    finally:
        config.ADMIN_PASSWORD = old_password
        gui_module.messagebox.askyesno = old_askyesno
        gui_module.simpledialog.askstring = old_askstring
        gui_module.messagebox.showerror = old_showerror
    check("emergency exit: unconfigured exit is recoverable by confirmation", no_password_exit)
    check("emergency exit: incorrect password does not exit", wrong_password_stays)
    check("emergency exit: configured password exits", configured_password_exits)
    check(
        "emergency exit: non-ASCII passwords compare without raising",
        non_ascii_password_exits and non_ascii_mismatch_safe,
    )

    # ---------------------------------------------------------------- appliance
    killer = ProcessKiller()
    check(
        "processes: blocklist normalised for .exe and Linux names",
        {"discord", "steam", "spotify"} <= killer.blocked_stems,
    )
    check(
        "processes: an explicit empty blocklist stays empty",
        ProcessKiller(blocked=()).blocked_stems == set(),
    )

    print()
    if failures:
        print(f"SELF-TEST FAILED: {failures} check(s) failed.")
        return False
    print("SELF-TEST PASSED: all checks passed.")
    return True
