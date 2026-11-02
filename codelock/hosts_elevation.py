"""One-shot elevated helper client for Windows hosts-file blocking.

Trust model
-----------
The GUI runs as a standard user. The elevated helper is installed once, by an
administrator, under ``%ProgramFiles%\\CodeLock`` together with
``hosts_helper.manifest.json``. Before every elevated launch this module:

* checks that the installation directory, manifest and helper are regular
  files inside the canonical Program Files location;
* parses their ACLs read-only and rejects any write access for a trustee that
  is not SYSTEM, Administrators, TrustedInstaller or (when already elevated)
  the current user;
* compares the helper's SHA-256 with the digest stored in that protected
  manifest.

A digest taken from the project folder at run time is deliberately not used:
that folder is writable by the same standard user, so it cannot establish
trust. If verification fails, the helper is not launched and no UAC prompt is
shown. Every operation is followed by a read-only re-read of the hosts file so
the reported status reflects what is actually on disk.

The helper accepts only ``block``, ``unblock``, ``status`` and ``recover``; it
never receives a hosts path, hostname or file content from this process.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import config
from .pc_blocker import HostsBlocker, is_admin
from .windows_acl import inspect_installation_acl

HELPER_FILENAME = "hosts_helper.ps1"
MANIFEST_FILENAME = "hosts_helper.manifest.json"
INSTALL_DIRECTORY_NAME = "CodeLock"
MANIFEST_PRODUCT = "CodeLock"
MANIFEST_FORMAT = 1
MANIFEST_ALGORITHM = "sha256"
MAX_MANIFEST_BYTES = 64 * 1024
ALLOWED_OPERATIONS = ("block", "unblock", "status", "recover", "repair")
ELEVATED_OPERATIONS = ("block", "unblock", "recover", "repair")

STATUS_BLOCKED = "blocked"
STATUS_PARTIAL = "partial"
STATUS_DAMAGED = "damaged"
STATUS_UNBLOCKED = "unblocked"
STATUS_MISSING = "missing"
STATUS_UNKNOWN = "unknown"

STATUS_LABELS = {
    STATUS_BLOCKED: "HOSTS FILE BLOCKED",
    STATUS_PARTIAL: "HOSTS FILE PARTIAL",
    STATUS_DAMAGED: "HOSTS FILE DAMAGED",
    STATUS_UNBLOCKED: "HOSTS FILE NOT BLOCKED",
    STATUS_MISSING: "HOSTS FILE MISSING",
    STATUS_UNKNOWN: "HOSTS FILE STATUS UNKNOWN",
}

WEBSITE_ACCESS_NOTE = (
    "This status describes the hosts file only. Network reachability was not "
    "tested, so CodeLock does not claim that websites are unreachable."
)

ERROR_CANCELLED = 1223
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_NOASYNC = 0x00000100
SW_HIDE = 0
WAIT_TIMEOUT = 258
CREATE_NO_WINDOW = 0x08000000
HELPER_TIMEOUT_SECONDS = 180.0
TERMINATE_WAIT_SECONDS = 5.0


@dataclass(frozen=True)
class HostsState:
    exists: bool
    blocked: bool
    well_formed: bool
    complete: bool
    error: str = ""
    damaged: bool = False
    managed_outside: int = 0
    status: str = ""


@dataclass(frozen=True)
class HostsOperationResult:
    ok: bool
    blocked: bool
    message: str
    cancelled: bool = False
    recovery_required: bool = False
    detail: str = ""
    observed: str = ""
    dns_flushed: bool | None = None
    dns_message: str = ""
    timed_out: bool = False
    terminated: bool = False


@dataclass(frozen=True)
class HelperVerification:
    ok: bool
    problems: tuple[str, ...] = ()
    helper_sha256: str = ""
    manifest_sha256: str = ""
    install_directory: str = ""

    @property
    def summary(self) -> str:
        return "; ".join(self.problems) if self.problems else "verified"


@dataclass(frozen=True)
class _RunOutcome:
    returncode: int | None
    cancelled: bool = False
    error: str = ""
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    terminated: bool = False
    reconciled: bool = True
    refused: bool = False


def classify_state(state: HostsState) -> str:
    if state.status:
        return state.status
    if state.error:
        return STATUS_UNKNOWN
    if not state.exists:
        return STATUS_MISSING
    if state.damaged or not state.well_formed:
        return STATUS_DAMAGED
    if state.blocked:
        return STATUS_BLOCKED if state.complete else STATUS_PARTIAL
    return STATUS_UNBLOCKED


def status_label(state: HostsState | str) -> str:
    key = state if isinstance(state, str) else classify_state(state)
    return STATUS_LABELS.get(key, STATUS_LABELS[STATUS_UNKNOWN])


def read_hosts_state(
    path: str | Path,
    websites: tuple[str, ...] | None = None,
    redirect_ip: str | None = None,
) -> HostsState:
    """Read and classify a hosts file without writing anything."""
    hosts_path = Path(path)
    sites = tuple(config.BLOCKED_WEBSITES if websites is None else websites)
    redirect = redirect_ip or config.BLOCK_REDIRECT_IP

    try:
        raw = hosts_path.read_bytes()
    except FileNotFoundError:
        return HostsState(
            exists=False,
            blocked=False,
            well_formed=True,
            complete=False,
            status=STATUS_MISSING,
        )
    except OSError as exc:
        return HostsState(
            exists=False,
            blocked=False,
            well_formed=False,
            complete=False,
            error=f"{type(exc).__name__}: {exc}",
            status=STATUS_UNKNOWN,
        )

    if raw.startswith(b"\xef\xbb\xbf"):
        text = raw.decode("utf-8-sig", errors="replace")
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16", errors="replace")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")

    inside = False
    begins = 0
    ends = 0
    bad = False
    found: set[str] = set()
    managed_outside = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == config.HOSTS_BLOCK_BEGIN:
            if inside:
                bad = True
            else:
                inside = True
                begins += 1
            continue
        if stripped == config.HOSTS_BLOCK_END:
            if not inside:
                bad = True
            else:
                inside = False
                ends += 1
            continue
        matched = next(
            (site for site in sites if stripped == f"{redirect} {site}"), None
        )
        if matched is None:
            continue
        if inside:
            found.add(matched)
        else:
            managed_outside += 1
    if inside:
        bad = True

    damaged = bad or begins != ends or begins > 1 or managed_outside > 0
    well_formed = not damaged
    blocked = well_formed and begins == 1
    complete = blocked and all(site in found for site in sites)
    if damaged:
        status = STATUS_DAMAGED
    elif blocked and complete:
        status = STATUS_BLOCKED
    elif blocked:
        status = STATUS_PARTIAL
    else:
        status = STATUS_UNBLOCKED
    return HostsState(
        exists=True,
        blocked=blocked,
        well_formed=well_formed,
        complete=complete,
        damaged=damaged,
        managed_outside=managed_outside,
        status=status,
    )


# --------------------------------------------------------------- installation
def _windows_directory() -> Path:
    if os.name != "nt":
        return Path(r"C:\Windows")
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetWindowsDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
        kernel32.GetWindowsDirectoryW.restype = wintypes.UINT
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel32.GetWindowsDirectoryW(buffer, len(buffer))
        if 0 < length < len(buffer):
            return Path(buffer.value)
    except (OSError, AttributeError):
        pass
    return Path(os.environ.get("SystemRoot", r"C:\Windows"))


def powershell_path() -> Path:
    return (
        _windows_directory()
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )


def program_files_directory() -> Path:
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "ProgramFilesDir")
            if value:
                return Path(value)
        except (OSError, ValueError):
            pass
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files"))


def default_install_directory() -> Path:
    return program_files_directory() / INSTALL_DIRECTORY_NAME


def default_install_path() -> Path:
    return default_install_directory() / HELPER_FILENAME


def default_manifest_path() -> Path:
    return default_install_directory() / MANIFEST_FILENAME


def _is_regular_file(path: Path) -> bool:
    try:
        if path.is_symlink() or not path.is_file():
            return False
        os.stat(path)
    except OSError:
        return False
    return True


def _is_hex_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(character in "0123456789abcdef" for character in value)


def _same_path(left: Path, right: Path) -> bool:
    try:
        left_resolved = left.resolve()
        right_resolved = right.resolve()
    except OSError:
        left_resolved = left.absolute()
        right_resolved = right.absolute()
    if os.name == "nt":
        return str(left_resolved).casefold() == str(right_resolved).casefold()
    return left_resolved == right_resolved


def verify_helper_installation(
    install_directory: str | Path,
    *,
    helper_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    acl_inspector: Callable[..., list[str]] | None = None,
    require_program_files: bool = False,
) -> HelperVerification:
    """Verify the installed helper against its administrator-written manifest."""
    directory = Path(install_directory)
    helper = Path(helper_path) if helper_path is not None else directory / HELPER_FILENAME
    manifest = (
        Path(manifest_path)
        if manifest_path is not None
        else directory / MANIFEST_FILENAME
    )
    inspector = acl_inspector or inspect_installation_acl
    problems: list[str] = []

    if require_program_files:
        expected = default_install_directory()
        if not _same_path(directory, expected):
            problems.append(f"unexpected_install_directory:{directory}")

    if not directory.is_dir():
        problems.append(f"install_directory_missing:{directory}")
    if not _is_regular_file(helper):
        problems.append(f"helper_missing_or_not_regular:{helper}")
    if not _is_regular_file(manifest):
        problems.append(f"manifest_missing_or_not_regular:{manifest}")

    try:
        acl_problems = list(inspector(directory, [helper, manifest]))
        acl_problems.extend(
            f"parent:{item}" for item in inspector(directory.parent, [])
        )
    except (OSError, ValueError) as exc:
        acl_problems = [f"acl_inspection_failed:{type(exc).__name__}:{exc}"]
    problems.extend(acl_problems)

    helper_digest = ""
    manifest_digest = ""
    if _is_regular_file(helper):
        try:
            helper_digest = hashlib.sha256(helper.read_bytes()).hexdigest()
        except OSError as exc:
            problems.append(f"helper_unreadable:{type(exc).__name__}")

    if _is_regular_file(manifest):
        try:
            manifest_bytes = manifest.read_bytes()
            manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        except OSError as exc:
            problems.append(f"manifest_unreadable:{type(exc).__name__}")
            manifest_bytes = b""
        if manifest_bytes:
            if len(manifest_bytes) > MAX_MANIFEST_BYTES:
                problems.append("manifest_too_large")
            else:
                try:
                    payload = json.loads(manifest_bytes.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    payload = None
                    problems.append("manifest_not_valid_json")
                if payload is not None:
                    if not isinstance(payload, dict):
                        problems.append("manifest_not_an_object")
                    else:
                        if payload.get("product") != MANIFEST_PRODUCT:
                            problems.append("manifest_product_mismatch")
                        if payload.get("format") != MANIFEST_FORMAT:
                            problems.append("manifest_format_mismatch")
                        if payload.get("helper") != HELPER_FILENAME:
                            problems.append("manifest_helper_name_mismatch")
                        if payload.get("algorithm") != MANIFEST_ALGORITHM:
                            problems.append("manifest_algorithm_mismatch")
                        recorded = payload.get("sha256")
                        if not _is_hex_sha256(recorded):
                            problems.append("manifest_hash_malformed")
                        elif helper_digest and recorded != helper_digest:
                            problems.append("manifest_hash_mismatch")
                        recorded_size = payload.get("size")
                        if recorded_size is not None:
                            try:
                                actual_size = helper.stat().st_size
                            except OSError:
                                actual_size = -1
                            if recorded_size != actual_size:
                                problems.append("manifest_size_mismatch")

    return HelperVerification(
        ok=not problems,
        problems=tuple(problems),
        helper_sha256=helper_digest,
        manifest_sha256=manifest_digest,
        install_directory=str(directory),
    )


# --------------------------------------------------------------------- recovery
def recovery_file_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "CodeLock" / "RECOVERY_REQUIRED.txt"


def restore_command() -> str:
    main_script = config.BASE_DIR / "main.py"
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --restore'
    return f'"{sys.executable}" "{main_script}" --restore'


def write_recovery_file(reason: str, path: str | Path | None = None) -> Path | None:
    """Write visible recovery instructions; never raises."""
    target = Path(path) if path is not None else recovery_file_path()
    text = f"""CodeLock could not confirm that the hosts file was restored.

Reason:
  {reason}

What to do now
--------------
1. Close CodeLock (use the emergency exit if the window is still locked).
2. Open PowerShell or Command Prompt as Administrator.
3. Run:
      {restore_command()}
   If the markers are damaged, --restore performs the recovery procedure:
   it removes the exact CodeLock marker lines and the exact managed
   ``{config.BLOCK_REDIRECT_IP} <blocked-site>`` lines, saves a copy of the
   damaged file, then reads the file back and verifies the result.
4. If you cannot open an administrator terminal, edit
      {config.HOSTS_PATH}
   in Notepad as Administrator and delete every line between:
      {config.HOSTS_BLOCK_BEGIN}
      {config.HOSTS_BLOCK_END}
   Also delete any stray exact lines of the form
      {config.BLOCK_REDIRECT_IP} instagram.com
   Keep every other line exactly as it is.
5. Run: ipconfig /flushdns
6. Reopen your browser. CodeLock only verifies the hosts file; it does not
   test whether websites are reachable, so check that yourself.

This file is an instruction note only. The elevated helper is installed at
{default_install_path()} and is never copied from the project folder.

If recovery still fails, CodeLock reports the observed hosts-file state and
tries to leave this file in place.
"""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except OSError:
        return None
    return target


def clear_recovery_file(path: str | Path | None = None) -> None:
    target = Path(path) if path is not None else recovery_file_path()
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


# ------------------------------------------------------------ elevated launch
class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def _shell_execute(
    executable: str, parameters: str, timeout: float
) -> _RunOutcome:
    """Run one UAC-elevated command, wait, and reconcile a timeout."""
    if os.name != "nt":
        return _RunOutcome(None, error="UAC elevation is only available on Windows.")
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SHELLEXECUTEINFOW)]
        shell32.ShellExecuteExW.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
    except (OSError, AttributeError) as exc:
        return _RunOutcome(None, error=f"Windows APIs unavailable: {exc}")

    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.lpVerb = "runas"
    info.lpFile = executable
    info.lpParameters = parameters
    # Start the elevated process in the protected system folder, not the
    # writable project directory.
    info.lpDirectory = str(Path(executable).parent)
    info.nShow = SW_HIDE

    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        code = ctypes.get_last_error()
        if code == ERROR_CANCELLED:
            return _RunOutcome(None, cancelled=True, error="The UAC prompt was cancelled.")
        return _RunOutcome(
            None, error=f"ShellExecuteExW failed with Windows error {code}."
        )

    handle = info.hProcess
    if not handle:
        return _RunOutcome(None, error="The elevated helper returned no process handle.")

    try:
        result = kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        if result == WAIT_TIMEOUT:
            terminated = bool(kernel32.TerminateProcess(handle, 1))
            terminate_error = 0 if terminated else ctypes.get_last_error()
            second = kernel32.WaitForSingleObject(
                handle, int(TERMINATE_WAIT_SECONDS * 1000)
            )
            reconciled = second != WAIT_TIMEOUT
            code = wintypes.DWORD()
            have_code = bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code)))
            if not reconciled:
                return _RunOutcome(
                    None,
                    error=(
                        "The elevated helper did not finish within "
                        f"{timeout:.0f} seconds and could not be stopped "
                        f"(TerminateProcess error {terminate_error}). It may still "
                        "change the hosts file."
                    ),
                    timed_out=True,
                    terminated=terminated,
                    reconciled=False,
                )
            return _RunOutcome(
                int(code.value) if have_code else None,
                error=(
                    "The elevated helper exceeded the "
                    f"{timeout:.0f}-second limit and was terminated; the process "
                    "was reconciled before the hosts file was re-read."
                ),
                timed_out=True,
                terminated=terminated,
                reconciled=True,
            )
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return _RunOutcome(
                None, error="The elevated helper exit code could not be read."
            )
        return _RunOutcome(int(code.value))
    finally:
        kernel32.CloseHandle(handle)


class HostsAuthority:
    """GUI-facing hosts control; elevated writes only through the fixed helper."""

    def __init__(
        self,
        *,
        hosts_path: str | Path | None = None,
        websites: tuple[str, ...] | None = None,
        redirect_ip: str | None = None,
        powershell: str | Path | None = None,
        install_path: str | Path | None = None,
        manifest_path: str | Path | None = None,
        launcher=None,
        acl_inspector: Callable[..., list[str]] | None = None,
        enforce_program_files: bool = True,
        test_mode: bool = False,
        test_force_error: str = "",
        test_helper: str | Path | None = None,
    ) -> None:
        self.hosts_path = Path(config.HOSTS_PATH if hosts_path is None else hosts_path)
        self.websites = tuple(
            config.BLOCKED_WEBSITES if websites is None else websites
        )
        self.redirect_ip = redirect_ip or config.BLOCK_REDIRECT_IP
        self.powershell = (
            Path(powershell) if powershell is not None else powershell_path()
        )
        self.install_path = (
            Path(install_path) if install_path is not None else default_install_path()
        )
        self.manifest_path = (
            Path(manifest_path)
            if manifest_path is not None
            else self.install_path.parent / MANIFEST_FILENAME
        )
        self.enforce_program_files = bool(enforce_program_files)
        self.test_mode = bool(test_mode)
        self.test_force_error = test_force_error
        self.test_helper = (
            Path(test_helper)
            if test_helper is not None
            else Path(__file__).with_name(HELPER_FILENAME)
        )
        self.last_error = ""
        self._launcher = launcher or _shell_execute
        self._acl_inspector = acl_inspector or inspect_installation_acl
        if self.test_mode:
            self._refuse_real_hosts_file()

    # -------------------------------------------------------------- inspection
    @property
    def install_directory(self) -> Path:
        return self.install_path.parent

    def verify_installation(self) -> HelperVerification:
        return verify_helper_installation(
            self.install_directory,
            helper_path=self.install_path,
            manifest_path=self.manifest_path,
            acl_inspector=self._acl_inspector,
            require_program_files=self.enforce_program_files,
        )

    @property
    def available(self) -> bool:
        if self.test_mode:
            return self.test_helper.is_file() and self.powershell.is_file()
        return self.installed

    @property
    def installed(self) -> bool:
        return self.verify_installation().ok

    def state(self) -> HostsState:
        return read_hosts_state(
            self.hosts_path, websites=self.websites, redirect_ip=self.redirect_ip
        )

    def describe(self) -> str:
        if self.test_mode:
            return f"offline test helper at {self.test_helper} (never elevated)"
        if os.name != "nt":
            return "direct hosts writes (non-Windows)"
        verification = self.verify_installation()
        if verification.ok:
            return f"verified trusted helper at {self.install_path}"
        return (
            f"helper installation at {self.install_path} is not trusted: "
            f"{verification.summary}"
        )

    # --------------------------------------------------------------- operations
    def block(self) -> HostsOperationResult:
        outcome = self._run("block")
        after = self.state()
        self.last_error = ""
        detail = outcome.error or self._helper_message(outcome)

        if outcome.cancelled:
            self.last_error = detail or "the administrator prompt was cancelled"
            if classify_state(after) == STATUS_BLOCKED:
                message = (
                    "Administrator approval was cancelled. The existing CodeLock "
                    "block is still in place. HOSTS FILE BLOCKED (observed, not "
                    "re-verified by the helper)."
                )
            else:
                message = (
                    "Administrator approval was cancelled, so the hosts file was "
                    f"not changed. {status_label(after)} (observed)."
                )
            return self._result(
                classify_state(after) == STATUS_BLOCKED,
                after,
                message,
                cancelled=True,
                detail=detail,
                outcome=outcome,
            )

        if outcome.refused:
            self.last_error = detail
            message = (
                "Refused to run the elevated helper because its installation "
                f"could not be verified: {detail}. {status_label(after)}."
            )
            return self._result(False, after, message, detail=detail, outcome=outcome)

        if outcome.error:
            self.last_error = detail
            observed = classify_state(after)
            if outcome.timed_out and not outcome.reconciled:
                prefix = (
                    "Website blocking timed out and the elevated helper could not "
                    "be stopped"
                )
            else:
                prefix = "Website blocking did not complete"
            message = f"{prefix}: {detail} {status_label(after)} (observed)."
            return self._result(
                observed == STATUS_BLOCKED and outcome.reconciled,
                after,
                message,
                recovery_required=observed in (STATUS_DAMAGED, STATUS_PARTIAL)
                or not outcome.reconciled,
                detail=detail,
                outcome=outcome,
            )

        if outcome.returncode != 0:
            self.last_error = detail or f"helper exit code {outcome.returncode}"
            observed = classify_state(after)
            message = (
                "Website blocking did not complete: "
                f"{self.last_error}. {status_label(after)} (observed)."
            )
            return self._result(
                observed == STATUS_BLOCKED and outcome.reconciled,
                after,
                message,
                recovery_required=observed in (STATUS_DAMAGED, STATUS_PARTIAL),
                detail=detail,
                outcome=outcome,
            )

        observed = classify_state(after)
        if observed == STATUS_BLOCKED:
            return self._result(
                True,
                after,
                "Website blocking is installed and verified from the hosts file.",
                outcome=outcome,
            )
        if observed == STATUS_PARTIAL:
            self.last_error = "the managed block is incomplete"
            return self._result(
                False,
                after,
                (
                    "The helper reported success but the managed block is "
                    "incomplete. HOSTS FILE PARTIAL (observed)."
                ),
                recovery_required=True,
                detail=self.last_error,
                outcome=outcome,
            )
        if observed == STATUS_DAMAGED:
            self.last_error = "the hosts file contains damaged CodeLock entries"
            return self._result(
                False,
                after,
                (
                    "The helper reported success but the hosts file contains "
                    "damaged CodeLock entries. HOSTS FILE DAMAGED (observed)."
                ),
                recovery_required=True,
                detail=self.last_error,
                outcome=outcome,
            )
        if observed == STATUS_UNKNOWN:
            self.last_error = after.error or "the hosts file could not be read"
            return self._result(
                False,
                after,
                f"The hosts file could not be verified: {self.last_error}.",
                detail=self.last_error,
                outcome=outcome,
            )
        self.last_error = "the managed block could not be verified"
        return self._result(
            False,
            after,
            (
                "The helper reported success but the managed block could not be "
                "verified. HOSTS FILE NOT BLOCKED (observed)."
            ),
            recovery_required=after.damaged,
            detail=self.last_error,
            outcome=outcome,
        )

    def unblock(self) -> HostsOperationResult:
        outcome = self._run("unblock")
        after = self.state()
        self.last_error = ""
        detail = outcome.error or self._helper_message(outcome)
        observed = classify_state(after)

        if outcome.cancelled:
            self.last_error = detail or "the administrator prompt was cancelled"
            if observed == STATUS_UNBLOCKED:
                message = (
                    "Administrator approval was cancelled. No CodeLock block is "
                    "present. HOSTS FILE NOT BLOCKED (observed)."
                )
            else:
                message = (
                    "Administrator approval was cancelled. "
                    f"{status_label(after)} (observed)."
                )
            return self._result(
                observed == STATUS_UNBLOCKED,
                after,
                message,
                cancelled=True,
                recovery_required=observed in (STATUS_DAMAGED, STATUS_PARTIAL),
                detail=detail,
                outcome=outcome,
            )

        if outcome.refused:
            self.last_error = detail
            message = (
                "Refused to run the elevated helper because its installation "
                f"could not be verified: {detail}. {status_label(after)}."
            )
            return self._result(False, after, message, detail=detail, outcome=outcome)

        if outcome.error:
            self.last_error = detail
            message = (
                "Restoring the hosts file did not complete: "
                f"{detail}. {status_label(after)} (observed)."
            )
            return self._result(
                observed == STATUS_UNBLOCKED and outcome.reconciled,
                after,
                message,
                recovery_required=observed != STATUS_UNBLOCKED
                or not outcome.reconciled,
                detail=detail,
                outcome=outcome,
            )

        if outcome.returncode != 0:
            self.last_error = detail or f"helper exit code {outcome.returncode}"
            message = (
                "Restoring the hosts file did not complete: "
                f"{self.last_error}. {status_label(after)} (observed)."
            )
            return self._result(
                observed == STATUS_UNBLOCKED and outcome.reconciled,
                after,
                message,
                recovery_required=observed != STATUS_UNBLOCKED,
                detail=detail,
                outcome=outcome,
            )

        if observed == STATUS_UNBLOCKED:
            return self._result(
                True,
                after,
                "Website blocking is removed and verified from the hosts file.",
                outcome=outcome,
            )
        if observed == STATUS_DAMAGED:
            self.last_error = "the hosts file still contains damaged CodeLock entries"
            return self._result(
                False,
                after,
                (
                    "The helper reported success but the hosts file still "
                    "contains damaged CodeLock entries. HOSTS FILE DAMAGED "
                    "(observed). Run recovery to repair it."
                ),
                recovery_required=True,
                detail=self.last_error,
                outcome=outcome,
            )
        self.last_error = "the managed block is still present"
        return self._result(
            False,
            after,
            (
                "The helper reported success but the CodeLock block is still "
                f"present. {status_label(after)} (observed)."
            ),
            recovery_required=observed != STATUS_UNBLOCKED,
            detail=self.last_error,
            outcome=outcome,
        )

    def recover(self, keep_block: bool = False) -> HostsOperationResult:
        """Remove damaged or stray CodeLock entries and verify the result.

        ``keep_block`` uses the helper's ``repair`` operation, which removes
        the damaged entries and writes a fresh block in the same elevated run.
        It is used while the PC is locked; plain ``recover`` is used by
        ``--restore`` and by shutdown.
        """
        operation = "repair" if keep_block else "recover"
        outcome = self._run(operation)
        after = self.state()
        self.last_error = ""
        detail = outcome.error or self._helper_message(outcome)
        observed = classify_state(after)
        expected = STATUS_BLOCKED if keep_block else STATUS_UNBLOCKED

        if outcome.cancelled:
            self.last_error = detail or "the administrator prompt was cancelled"
            return self._result(
                False,
                after,
                f"Administrator approval was cancelled. {status_label(after)}.",
                cancelled=True,
                recovery_required=True,
                detail=detail,
                outcome=outcome,
            )
        if outcome.refused:
            self.last_error = detail
            return self._result(
                False,
                after,
                (
                    "Refused to run the elevated helper because its installation "
                    f"could not be verified: {detail}. {status_label(after)}."
                ),
                recovery_required=True,
                detail=detail,
                outcome=outcome,
            )
        if outcome.error:
            self.last_error = detail
            desired_ok = observed == expected and outcome.reconciled
            return self._result(
                desired_ok,
                after,
                (
                    "The recovery helper did not finish cleanly, but the hosts "
                    f"file was verified in the expected state. {status_label(after)} "
                    "(observed)."
                    if desired_ok
                    else "Hosts-file recovery did not complete: "
                    f"{detail}. {status_label(after)} (observed)."
                ),
                recovery_required=not desired_ok,
                detail=detail,
                outcome=outcome,
            )
        if outcome.returncode != 0:
            self.last_error = detail or f"helper exit code {outcome.returncode}"
            desired_ok = observed == expected and outcome.reconciled
            return self._result(
                desired_ok,
                after,
                (
                    "The recovery helper reported an error, but the hosts file "
                    f"was verified in the expected state. {status_label(after)} "
                    "(observed)."
                    if desired_ok
                    else "Hosts-file recovery did not complete: "
                    f"{self.last_error}. {status_label(after)} (observed)."
                ),
                recovery_required=not desired_ok,
                detail=detail,
                outcome=outcome,
            )
        if observed == expected:
            message = (
                "Damaged CodeLock entries were removed and a fresh block was "
                "verified. HOSTS FILE BLOCKED."
                if keep_block
                else "CodeLock entries were removed and the hosts file was "
                "verified. HOSTS FILE NOT BLOCKED."
            )
            return self._result(True, after, message, outcome=outcome)
        self.last_error = f"the hosts file is still {observed}"
        return self._result(
            False,
            after,
            (
                "The helper reported success but the hosts file is not in the "
                f"expected state. {status_label(after)} (observed)."
            ),
            recovery_required=True,
            detail=self.last_error,
            outcome=outcome,
        )

    # ----------------------------------------------------------------- internals
    def _refuse_real_hosts_file(self) -> None:
        try:
            candidate = self.hosts_path.resolve()
            real = Path(config.HOSTS_PATH).resolve()
        except OSError:
            candidate = self.hosts_path.absolute()
            real = Path(config.HOSTS_PATH).absolute()
        if os.name == "nt":
            same = str(candidate).casefold() == str(real).casefold()
        else:
            same = candidate == real
        if same:
            raise ValueError(
                "HostsAuthority test mode refuses the real system hosts file."
            )

    def _run(self, operation: str) -> _RunOutcome:
        if operation not in ALLOWED_OPERATIONS:
            raise ValueError(f"Unsupported hosts operation: {operation!r}")
        if self.test_mode:
            return self._run_test_helper(operation)
        if os.name == "nt":
            return self._run_elevated(operation)
        return self._run_direct(operation)

    def _run_direct(self, operation: str) -> _RunOutcome:
        if operation in ("recover", "repair"):
            return _RunOutcome(
                None, error="Hosts-file recovery needs the elevated helper."
            )
        blocker = HostsBlocker(
            hosts_path=self.hosts_path,
            websites=self.websites,
            redirect_ip=self.redirect_ip,
            flush_resolver=not self.test_mode,
        )
        ok = blocker.block() if operation == "block" else blocker.unblock()
        if ok:
            return _RunOutcome(0)
        return _RunOutcome(3, error=blocker.last_error or "hosts write failed")

    def _run_test_helper(self, operation: str) -> _RunOutcome:
        if is_admin():
            return _RunOutcome(
                None,
                error="The hosts helper test mode refuses an elevated process.",
            )
        if not self.powershell.is_file():
            return _RunOutcome(None, error="PowerShell was not found.")
        if not self.test_helper.is_file():
            return _RunOutcome(None, error="The bundled hosts helper is missing.")

        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith("CODELOCK_HELPER_TEST_")
        }
        environment["CODELOCK_HELPER_TEST_HOSTS_PATH"] = str(self.hosts_path)
        if self.test_force_error:
            environment["CODELOCK_HELPER_TEST_FORCE_ERROR"] = self.test_force_error

        command = [
            str(self.powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.test_helper),
            "-Operation",
            operation,
            "-TestMode",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=90,
                env=environment,
                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired:
            return _RunOutcome(
                None,
                error=(
                    "The hosts helper timed out and was terminated by the test "
                    "runner."
                ),
                timed_out=True,
                terminated=True,
                reconciled=True,
            )
        except OSError as exc:
            return _RunOutcome(None, error=f"{type(exc).__name__}: {exc}")
        return _RunOutcome(
            completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def _run_elevated(self, operation: str) -> _RunOutcome:
        if operation not in ELEVATED_OPERATIONS:
            raise ValueError(
                "Only block, unblock, recover and repair are elevated operations."
            )
        if not self.powershell.is_file():
            return _RunOutcome(
                None, error="PowerShell was not found at the protected system path."
            )
        verification = self.verify_installation()
        if not verification.ok:
            return _RunOutcome(
                None,
                error=(
                    "the trusted helper installation could not be verified "
                    f"({verification.summary})"
                ),
                refused=True,
            )
        try:
            parameters = self._build_elevated_parameters(operation)
        except ValueError as exc:
            return _RunOutcome(None, error=str(exc), refused=True)
        return self._launcher(str(self.powershell), parameters, HELPER_TIMEOUT_SECONDS)

    def _build_elevated_parameters(self, operation: str) -> str:
        if operation not in ELEVATED_OPERATIONS:
            raise ValueError(f"Unsupported elevated hosts operation: {operation!r}")
        # Only the installed helper is executed. The project folder is never
        # read, copied or executed by the elevated process.
        return (
            "-NoProfile -NonInteractive -WindowStyle Hidden "
            "-ExecutionPolicy Bypass "
            f'-File "{self.install_path}" -Operation {operation}'
        )

    @staticmethod
    def _helper_payload(outcome: _RunOutcome | None) -> dict:
        if outcome is None:
            return {}
        for line in reversed(outcome.stdout.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        return {}

    def _helper_message(self, outcome: _RunOutcome) -> str:
        payload = self._helper_payload(outcome)
        message = str(payload.get("message") or "").strip()
        if message:
            return message
        tail = (outcome.stderr or "").strip().splitlines()
        return tail[-1].strip() if tail else ""

    def _result(
        self,
        ok: bool,
        state: HostsState,
        message: str,
        *,
        cancelled: bool = False,
        recovery_required: bool = False,
        detail: str = "",
        outcome: _RunOutcome | None = None,
    ) -> HostsOperationResult:
        payload = self._helper_payload(outcome)
        dns = payload.get("dns")
        dns_flushed: bool | None = None
        dns_message = ""
        if isinstance(dns, dict):
            dns_flushed = bool(dns.get("ok"))
            dns_message = str(dns.get("message") or "")
            if not dns.get("attempted", True):
                dns_flushed = None
            elif dns_flushed is False and dns_message:
                message = f"{message} DNS cache flush failed: {dns_message}"
                detail = f"{detail} {dns_message}".strip()
        if outcome is not None and outcome.timed_out and not outcome.reconciled:
            recovery_required = True
        return HostsOperationResult(
            ok=ok,
            blocked=state.blocked,
            message=message,
            cancelled=cancelled,
            recovery_required=recovery_required or state.damaged,
            detail=detail,
            observed=classify_state(state),
            dns_flushed=dns_flushed,
            dns_message=dns_message,
            timed_out=bool(outcome.timed_out) if outcome is not None else False,
            terminated=bool(outcome.terminated) if outcome is not None else False,
        )
