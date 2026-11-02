"""Central configuration. Edit this file to tune what CodeLock blocks."""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------- PC websites
# Blocked through the operating system hosts file, so it applies to every browser.
BLOCKED_WEBSITES = (
    "instagram.com",
    "www.instagram.com",
    "facebook.com",
    "www.facebook.com",
    "x.com",
    "www.x.com",
    "twitter.com",
    "www.twitter.com",
    "reddit.com",
    "www.reddit.com",
    "tiktok.com",
    "www.tiktok.com",
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "netflix.com",
    "www.netflix.com",
    "twitch.tv",
    "www.twitch.tv",
    "primevideo.com",
    "www.primevideo.com",
)

HOSTS_PATH = (
    Path(r"C:\Windows\System32\drivers\etc\hosts")
    if os.name == "nt"
    else Path("/etc/hosts")
)
BLOCK_REDIRECT_IP = "0.0.0.0"
HOSTS_BLOCK_BEGIN = "# >>> CodeLock block (managed automatically) >>>"
HOSTS_BLOCK_END = "# <<< CodeLock block (managed automatically) <<<"

# ---------------------------------------------------------------- PC processes
# Compared case-insensitively against the executable name, with or without ".exe".
BLOCKED_PC_PROCESSES = (
    "Discord.exe",
    "DiscordCanary.exe",
    "Steam.exe",
    "Spotify.exe",
    "WhatsApp.exe",
    "Telegram.exe",
    "EpicGamesLauncher.exe",
)

# ---------------------------------------------------------------- Session rules
REWARD_SECONDS = 15 * 60
WATCHDOG_INTERVAL_SECONDS = 2.5
HOSTS_RETRY_SECONDS = 60.0
JUDGE_TIMEOUT_SECONDS = 3.0
JUDGE_CASE_TIMEOUT_SECONDS = 2.0

# ------------------------------------------------------- Student progress store
# Oracle is used when CODELOCK_ORACLE_DSN is set (run database/schema.sql first).
# Otherwise accounts and progress live in a local SQLite database.
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("CODELOCK_DATA_DIR") or (BASE_DIR / "data"))
DB_PATH = Path(os.environ.get("CODELOCK_DB_PATH") or (DATA_DIR / "codelock.db"))

ORACLE_USER = os.environ.get("CODELOCK_ORACLE_USER", "")
ORACLE_PASSWORD = os.environ.get("CODELOCK_ORACLE_PASSWORD", "")
ORACLE_DSN = os.environ.get("CODELOCK_ORACLE_DSN", "")

# Emergency exit password (Ctrl+Alt+Shift+Q). There is deliberately no public
# default: set CODELOCK_ADMIN_PASSWORD before starting a real kiosk session.
ADMIN_PASSWORD = os.environ.get("CODELOCK_ADMIN_PASSWORD", "")
