"""CodeLock entry point.

Usage:
    python main.py                 # kiosk mode (never auto-elevates)
    python main.py --dry-run       # simulate everything, touch nothing
    python main.py --restore       # remove the website block
    python main.py --self-test     # offline checks of the judge, hosts and accounts
    python main.py --self-test-ui  # analytics dashboard GUI smoke test
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from codelock import config
from codelock import __version__
from codelock.pc_blocker import AppInstanceLock, is_admin


def _enable_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def restore_all() -> int:
    if os.name == "nt":
        from codelock.hosts_elevation import (
            STATUS_DAMAGED,
            STATUS_UNBLOCKED,
            HostsAuthority,
            clear_recovery_file,
            status_label,
            write_recovery_file,
        )

        authority = HostsAuthority()
        state = authority.state()
        if state.error:
            print(
                "Hosts file: FAILED - "
                f"{status_label(state)} ({state.error}). No change was made."
            )
            return 1
        observed = status_label(state)
        if state.status in (STATUS_UNBLOCKED, "missing"):
            print(f"Hosts file: no CodeLock block found. {observed}.")
            clear_recovery_file()
            return 0

        if state.status == STATUS_DAMAGED:
            print(
                "Hosts file: damaged CodeLock entries found; running the "
                "recovery procedure."
            )
            result = authority.recover(keep_block=False)
        else:
            result = authority.unblock()

        if result.ok:
            print(f"Hosts file: CodeLock entries removed and verified. {status_label(result.observed)}.")
            if result.dns_flushed is False:
                print(
                    "  DNS cache flush FAILED: "
                    f"{result.dns_message or 'unknown error'}."
                )
            clear_recovery_file()
            return 0

        print(f"Hosts file: FAILED - {result.message}")
        print(f"  Observed state: {status_label(result.observed)}.")
        if result.dns_flushed is False:
            print(
                f"  DNS cache flush FAILED: {result.dns_message or 'unknown error'}."
            )
        path = write_recovery_file(result.message)
        if path is not None:
            print(f"  Recovery instructions: {path}")
        else:
            print(
                "  Recovery instructions could NOT be created. Edit "
                f"{config.HOSTS_PATH} manually as Administrator."
            )
        return 1

    from codelock.pc_blocker import HostsBlocker

    hosts = HostsBlocker()
    if hosts.unblock():
        print("Hosts file: CodeLock block removed.")
        return 0

    print(f"Hosts file: FAILED - {hosts.last_error}")
    if not is_admin():
        print("  Hint: run this command from an administrator terminal.")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="codelock",
        description="PC distraction blocker with a Python/DSA judge.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run the GUI without touching hosts or processes",
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="remove the website block, then exit",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run offline checks (hosts, accounts, judge, problem bank) and exit",
    )
    parser.add_argument(
        "--self-test-ui",
        action="store_true",
        help="run the analytics dashboard GUI smoke test and exit",
    )
    parser.add_argument(
        "--no-elevate",
        action="store_true",
        help="deprecated; CodeLock no longer requests administrator rights",
    )
    parser.add_argument("--version", action="version", version=f"CodeLock {__version__}")
    args = parser.parse_args(argv)

    if args.self_test:
        if is_admin():
            print(
                "CodeLock: self-tests launch submitted code and cannot run as administrator/root.",
                file=sys.stderr,
            )
            return 2
        from codelock.selftest import run_self_test

        return 0 if run_self_test() else 1

    if args.self_test_ui:
        from codelock.ui_smoke import run_ui_smoke_test

        return 0 if run_ui_smoke_test() else 1

    if args.restore:
        return restore_all()

    if is_admin():
        print(
            "CodeLock will not start its GUI as administrator/root because the judge "
            "executes submitted code. Start it from a standard user account. "
            "Use --restore separately when elevated hosts-file cleanup is needed.",
            file=sys.stderr,
        )
        return 2

    instance_id = hashlib.sha256(str(config.BASE_DIR).casefold().encode("utf-8")).hexdigest()[:16]
    lock_path = Path(tempfile.gettempdir()) / f"codelock-{instance_id}.lock"
    instance_lock = AppInstanceLock(lock_path)
    try:
        acquired = instance_lock.acquire()
    except OSError as exc:
        print(f"CodeLock: could not acquire the session lock: {exc}", file=sys.stderr)
        return 1
    if not acquired:
        print("CodeLock is already running; refusing a second session.", file=sys.stderr)
        return 2

    try:
        _enable_dpi_awareness()

        import tkinter as tk

        from codelock.gui import CodeLockApp

        try:
            root = tk.Tk()
        except tk.TclError as exc:
            print(f"CodeLock: could not start the GUI: {exc}", file=sys.stderr)
            return 1

        app = CodeLockApp(root, dry_run=args.dry_run)
        try:
            root.mainloop()
        except KeyboardInterrupt:
            app.shutdown()
        return 0
    finally:
        instance_lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
