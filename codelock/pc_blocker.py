"""PC-side enforcement: hosts-file blocking plus process termination."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from . import config

try:
    import psutil
except ImportError:  # pragma: no cover - fallback uses native tools
    psutil = None


def is_admin() -> bool:
    try:
        if os.name == "nt":
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False


def _no_window_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def flush_dns() -> None:
    """Best-effort resolver cache flush; failures are non-fatal."""
    commands: list[list[str]] = []
    if os.name == "nt":
        commands.append(["ipconfig", "/flushdns"])
    elif sys.platform == "darwin":
        commands.append(["dscacheutil", "-flushcache"])
    else:
        commands.extend(
            [
                ["resolvectl", "flush-caches"],
                ["systemd-resolve", "--flush-caches"],
                ["nscd", "-i", "hosts"],
            ]
        )
    for command in commands:
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                creationflags=_no_window_flags(),
            )
            if result.returncode == 0:
                return
        except (OSError, subprocess.TimeoutExpired):
            continue


class HostsBlocker:
    """Adds and removes one delimited block in the system hosts file."""

    def __init__(
        self,
        hosts_path: str | Path | None = None,
        websites: tuple[str, ...] | None = None,
        redirect_ip: str | None = None,
        flush_resolver: bool = True,
    ) -> None:
        self.hosts_path = Path(hosts_path or config.HOSTS_PATH)
        self.websites = tuple(
            config.BLOCKED_WEBSITES if websites is None else websites
        )
        self.redirect_ip = redirect_ip or config.BLOCK_REDIRECT_IP
        self.flush_resolver = flush_resolver
        self.last_error = ""
        self._encoding = "utf-8"
        self._newline = "\n"
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ public
    def is_blocked(self) -> bool:
        return any(
            line.strip() == config.HOSTS_BLOCK_BEGIN
            for line in self._read().splitlines()
        )

    def recover_stale_block(self) -> bool | None:
        """Remove an existing managed block; return None when recovery is unnecessary."""
        try:
            if not self.is_blocked():
                return None
            return self.unblock()
        except OSError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False

    def block(self) -> bool:
        with self._lock:
            try:
                current = self._read()
                if not self._markers_well_formed(current):
                    self.last_error = "CodeLock hosts markers are incomplete or mismatched."
                    return False
                base = self._strip_block(current)
                if base and not base.endswith(self._newline):
                    base += self._newline
                if base and not base.endswith(self._newline * 2):
                    base += self._newline
                updated = base + self._block_section()
                if updated == current:
                    self.last_error = ""
                    return True
                self._backup(current)
                self._write(updated)
                self.last_error = ""
            except OSError as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                return False
        if self.flush_resolver:
            flush_dns()
        return True

    def unblock(self) -> bool:
        with self._lock:
            try:
                current = self._read()
                if not self._markers_well_formed(current):
                    self.last_error = "CodeLock hosts markers are incomplete or mismatched."
                    return False
                if not self.is_blocked():
                    self.last_error = ""
                    return True
                updated = self._strip_block(current)
                if updated == current:
                    self.last_error = ""
                    return True
                self._write(updated)
                self.last_error = ""
            except OSError as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                return False
        if self.flush_resolver:
            flush_dns()
        return True

    # ----------------------------------------------------------------- internal
    def _read(self) -> str:
        try:
            raw = self.hosts_path.read_bytes()
        except FileNotFoundError:
            return ""
        if raw.startswith(b"\xef\xbb\xbf"):
            encoding, text = "utf-8-sig", raw.decode("utf-8-sig")
        elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            encoding, text = "utf-16", raw.decode("utf-16")
        else:
            try:
                encoding, text = "utf-8", raw.decode("utf-8")
            except UnicodeDecodeError:
                encoding, text = "cp1252", raw.decode("cp1252")
        self._encoding = encoding
        self._newline = "\r\n" if b"\r\n" in raw else "\n"
        return text

    def _block_section(self) -> str:
        lines = [config.HOSTS_BLOCK_BEGIN]
        lines.extend(f"{self.redirect_ip} {site}" for site in self.websites)
        lines.append(config.HOSTS_BLOCK_END)
        return self._newline.join(lines) + self._newline

    @staticmethod
    def _markers_well_formed(text: str) -> bool:
        inside = False
        for line in text.splitlines():
            marker = line.strip()
            if marker == config.HOSTS_BLOCK_BEGIN:
                if inside:
                    return False
                inside = True
            elif marker == config.HOSTS_BLOCK_END:
                if not inside:
                    return False
                inside = False
        return not inside

    def _strip_block(self, text: str) -> str:
        kept: list[str] = []
        inside = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped == config.HOSTS_BLOCK_BEGIN:
                inside = True
                continue
            if stripped == config.HOSTS_BLOCK_END:
                inside = False
                continue
            if not inside:
                kept.append(line)
        if not kept:
            return ""
        return self._newline.join(kept).rstrip("\r\n") + self._newline

    def _backup(self, content: str) -> None:
        if not self.hosts_path.exists() or config.HOSTS_BLOCK_BEGIN in content:
            return
        backup = self.hosts_path.with_name(self.hosts_path.name + ".codelock.bak")
        if backup.exists():
            return
        shutil.copy2(self.hosts_path, backup)

    def _write(self, text: str) -> None:
        """Atomically replace the hosts file; a failed replace leaves it intact."""
        descriptor, tmp_name = tempfile.mkstemp(
            prefix=".codelock-", dir=str(self.hosts_path.parent)
        )
        try:
            with os.fdopen(
                descriptor, "w", encoding=self._encoding, newline=""
            ) as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            if self.hosts_path.exists():
                shutil.copymode(self.hosts_path, tmp_name)
            os.replace(tmp_name, self.hosts_path)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass


class AppInstanceLock:
    """Cross-process lock that prevents startup recovery racing a live session."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._handle = None

    def acquire(self) -> bool:
        if self._handle is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ImportError):
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (OSError, ImportError):
            pass
        finally:
            handle.close()


class ProcessKiller:
    """Terminates blacklisted desktop apps; new instances are caught each sweep."""

    def __init__(self, blocked: tuple[str, ...] | None = None) -> None:
        names = config.BLOCKED_PC_PROCESSES if blocked is None else blocked
        # Compare executable stems so "Discord.exe" also matches Linux "discord".
        self.blocked_stems = {Path(name).stem.lower() for name in names}

    @property
    def available(self) -> bool:
        """True when psutil is installed; otherwise the native tools are used."""
        return psutil is not None

    def sweep(self) -> list[str]:
        if psutil is not None:
            return self._sweep_psutil()
        return self._sweep_native()

    def _sweep_psutil(self) -> list[str]:
        killed: list[str] = []
        for process in psutil.process_iter(["name"]):
            name = process.info.get("name") or ""
            if Path(name).stem.lower() not in self.blocked_stems:
                continue
            try:
                process.kill()
                killed.append(name)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except psutil.Error:
                continue
        return killed

    def _sweep_native(self) -> list[str]:
        killed: list[str] = []
        if os.name == "nt":
            try:
                listing = subprocess.run(
                    ["tasklist", "/FO", "CSV", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    creationflags=_no_window_flags(),
                )
            except (OSError, subprocess.TimeoutExpired):
                return []
            targets: list[tuple[str, str]] = []
            for line in listing.stdout.splitlines():
                if not line.startswith('"'):
                    continue
                fields = line.split('","')
                if len(fields) < 2:
                    continue
                name = fields[0].strip('"')
                pid = fields[1].strip('"')
                if Path(name).stem.lower() in self.blocked_stems:
                    targets.append((name, pid))
            for name, pid in targets:
                try:
                    result = subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", pid],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        creationflags=_no_window_flags(),
                    )
                except (OSError, subprocess.TimeoutExpired):
                    continue
                if result.returncode == 0:
                    killed.append(name)
        else:
            for stem in self.blocked_stems:
                try:
                    result = subprocess.run(
                        ["pkill", "-x", stem],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    continue
                if result.returncode == 0:
                    killed.append(stem)
        return killed
