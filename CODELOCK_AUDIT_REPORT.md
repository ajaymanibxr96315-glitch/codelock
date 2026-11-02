# CodeLock - Complete Product Audit, Functional Testing and Bug Fixing

**Audit date:** 2026-11-01  
**Application version:** CodeLock 1.0.0  
**Audited build:** `D:\blocker` (no git repository present)  
**Environment:** Windows 10 x64 (10.0.19045), Python 3.14.7, Tk 8.6, SQLite, Git Bash  
**Scope:** Existing application only. No Phase 3 work, no redesign, no new product features.

---

## Status labels

Every feature below uses exactly one of these labels:

- **Verified working** - exercised successfully by automated tests and/or real GUI runs.
- **Partially working** - the implemented path works, but part of the requested feature is missing, unverified, or limited.
- **Not working** - exercised and failed, or known absent.
- **Not tested** - not exercised in this audit, usually for safety or environment reasons.

Evidence types are stated separately so that an automated test is never presented as proof of a real Windows behaviour:

- **Automated:** offline checks (`python main.py --self-test`), no GUI.
- **GUI (in-process Tk):** real Tk widgets, event loop and temporary SQLite database, driven programmatically on the real desktop; screenshots captured.
- **Real entry point (dry-run):** the actual `main.py --dry-run` process, measured and closed normally.
- **Real Windows enforcement:** actual hosts-file edit / app termination / admin session. **Not run in this audit** (requires explicit approval).

---

## 1. Project architecture overview

CodeLock is a single-process Python desktop application with one Tk main window, child Tk windows, a subprocess coding judge, an OS-level hosts blocker, a process killer, a local SQLite store, and an optional Oracle/PL-SQL backend.

```
main.py                     CLI entry, --dry-run, --restore, --self-test, --self-test-ui
codelock/
  config.py                 blocked sites/apps, timings, DB path, emergency password
  gui.py                    kiosk window, sign-in, track picker, watchdog, reward timer
  problems.py               4 study tracks, 15 challenges, hidden-test generators
  judge.py                  isolated subprocess harness, timeout, output cap, env allowlist
  pc_blocker.py             marker-scoped hosts blocker, encoding-safe writes, recovery,
                            cross-process instance lock, process killer
  db.py                     account/progress/exam persistence (SQLite + Oracle backends)
  exam.py                   PDF/DOCX/TXT extraction and topic validation
  study_generation.py       source-grounded notes and validated question generation
  exam_engine.py            question selection, objective scoring, session submission
  exam_runner.py            practice/mock windows, countdown, immediate feedback, results
  exam_analytics.py         accuracy, mastery, trends, recommendations, range filters
  exam_charts.py            Tk Canvas topic bars and session-trend chart
  exam_ui.py                7-tab exam workspace (Syllabus, Revision Notes, Question Bank,
                            Practice, Mock Exam, Results, Analytics)
  ai.py                     Gemini / Ollama / OpenAI-compatible transport; env-only keys
  selftest.py               159 offline checks
  ui_smoke.py               13 analytics/data-safety GUI checks
database/
  schema.sql                Oracle student/exam schema, view and PL/SQL API package
  migrations/001, 002       exam workspace and normalized exam-core migrations
data/                       local SQLite store created at runtime
```

**DSA Focus Mode flow:** sign-in -> track picker -> lock (hosts + app killer + topmost
watchdog) -> solve -> RUN SAMPLES (no unlock) -> SUBMIT (hidden tests) -> 15-minute reward ->
automatic relock -> next challenge. Progress is stored per student and track.

**Exam flow:** workspace -> upload/extract syllabus -> edit/approve -> generate notes/questions
from approved sources -> practice or mock -> submit -> result review -> analytics/history/resume.

**Storage:** SQLite by default (`data/codelock.db` or `CODELOCK_DB_PATH`); Oracle when
`CODELOCK_ORACLE_DSN` and credentials are configured and `oracledb` is installed.

---

## 2. Features actually tested

### 2.1 Application launch, login and navigation

| Feature | Status | Evidence |
| --- | --- | --- |
| Application starts from the real entry point | Verified working | Real entry point (dry-run): sign-in visible in 0.69-0.75 s |
| Login and registration | Verified working | GUI (in-process Tk): account creation, sign-in, picker |
| Screen/tab navigation | Verified working | GUI: all 7 exam tabs; focus picker/locked/reward/relock |
| Windows open/close without exceptions | Verified working | GUI harnesses; no traceback in any run |
| Clean exit | Verified working | Real entry point (dry-run): exit code 0 in 0.094 s |
| Every button exhaustively clicked | Partially working | Principal controls exercised (see section 3); not every low-risk button |
| Real-mode kiosk launch | Not tested | Would modify the real hosts file / terminate apps; not approved |

### 2.2 DSA Focus Mode

| # | Workflow step | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Student registration and login | Verified working | GUI; automated account tests |
| 2 | Track selection | Verified working | GUI: 4 tracks shown, selection locks session |
| 3 | Challenge selection | Verified working | GUI: Engineering track loaded challenge 1 |
| 4 | Code editor input | Verified working | GUI: real text widget used for submissions |
| 5 | Sample test execution | Verified working | GUI: RUN SAMPLES -> "SAMPLES PASSED", stays locked |
| 6 | Hidden test evaluation | Verified working | Automated: all 15 reference solutions; GUI submit |
| 7 | Incorrect submission handling | Verified working | GUI: "FAILED", session stays locked |
| 8 | Successful submission | Verified working | GUI: submit -> reward mode |
| 9 | Reward timer | Verified working | GUI dry-run: 14:59 countdown, UNLOCKED header |
| 10 | PC relocking | Verified working | GUI dry-run: forced deadline -> LOCKED, next challenge |
| 11 | Progress persistence after restart | Verified working | GUI: closed and reopened app; completed=1, attempts=2, resumed at challenge 2 |
| 12 | Emergency exit and recovery | Partially working | Automated logic for password/confirmation paths; hosts recovery on a temp file; real keypress and real hosts not tested |
| - | Actual Windows website blocking | Not tested | Requires admin and real hosts modification (not approved) |
| - | Actual desktop app termination | Not tested | Would kill real applications (not approved) |
| - | Anti-paste editor | Partially working | Bindings present and code-reviewed; not exercised by real keyboard/clipboard input |

### 2.3 AI Exam Preparation

| Feature | Status | Evidence |
| --- | --- | --- |
| Workspace creation | Verified working | GUI: subject/level/date/marks/duration -> CREATE |
| Workspace deletion | Not working | No delete action exists (observation, not added per Rule 1) |
| TXT upload and extraction | Verified working | GUI: two units/topics parsed |
| DOCX upload and extraction | Verified working | GUI: stdlib ZIP/XML extraction |
| PDF upload and extraction | Verified working | Automated under `.venv` (pypdf 6.21.4): text + page count + image-only detection |
| Syllabus editing (add unit/topic, rename, remove) | Verified working | GUI: ADD UNIT, REMOVE, RENAME, ADD TOPIC |
| Draft saving | Verified working | GUI: SAVE DRAFT persists; unsaved edits preserved |
| Topic approval | Verified working | GUI: approval unlocks generation |
| Notes generation | Verified working | GUI with deterministic provider; grounding tests |
| Question generation | Verified working | GUI: 5 validated questions saved |
| Duplicate question rejection | Verified working | GUI: error shown, existing bank unchanged |
| Practice sessions | Verified working | GUI: 3 questions, immediate feedback, 3/3 score |
| Mock examinations | Verified working | GUI: countdown, auto-submit at zero |
| Answer evaluation | Verified working | Automated scoring + GUI immediate feedback |
| Results and answer review | Verified working | GUI: topic performance and answer review tabs |
| Session resume | Verified working | GUI: history lists in-progress session; saved answer restored |
| Student data isolation | Verified working | Automated + GUI: other student's workspace invisible/unloadable |
| Live AI provider generation | Not tested | No credentials/network used; transport tested with local HTTP stubs |

### 2.4 Analytics

| Feature | Status | Evidence |
| --- | --- | --- |
| Overall accuracy | Verified working | Automated known-data check: 24/33 = 72.7% |
| Topic-wise accuracy | Verified working | Automated: Weak topic 4/8 = 50% |
| Weak-topic classification | Verified working | Automated + GUI recommendation |
| Mastery indicators | Verified working | Automated + GUI; coverage and minimum-evidence rules |
| Recent performance | Verified working | Automated improvement/decline/steady cases |
| Session trends | Verified working | Automated; sessions with <3 graded answers excluded |
| Question-type analysis | Verified working | Automated: Multiple Choice 60% |
| Bloom-level analysis | Verified working | Automated: Remember; "Unspecified" bucket |
| 7-day / 30-day / all-time filters | Verified working | GUI smoke: all three ranges |
| Practice This Topic action | Verified working | GUI smoke: opens topic-specific practice |
| Empty-state behaviour | Verified working | GUI smoke: not-started topics, no estimates |
| Insufficient-data handling | Verified working | Automated: "Not enough history", no recommendations |
| Analytics visual layout | Partially working | Text/columns clip at 980 px (open P3, section 6) |

### 2.5 AI providers

| Provider / scenario | Status | Evidence |
| --- | --- | --- |
| Gemini - valid configuration | Not tested | No live key |
| Ollama - valid configuration | Not tested | No live daemon |
| OpenAI-compatible - valid configuration | Not tested | No live endpoint |
| Missing configuration | Verified working | Automated clear AIError, no fallback content |
| Invalid API key | Partially working | Local HTTP 400 stub; key redaction verified; real provider mapping not tested |
| Network failure | Verified working | Automated unreachable-endpoint check |
| Rate limit (HTTP 429) | Verified working | Automated local stub |
| Timeout | Verified working | Automated slow-endpoint check (0.2 s timeout) |
| Malformed response | Verified working | Automated non-JSON and missing-message checks |
| No fabricated fallback | Verified working | Automated grounding/not-found tests |

### 2.6 Database

| Feature | Status | Evidence |
| --- | --- | --- |
| SQLite creation | Verified working | Automated temporary databases |
| Student registration/login | Verified working | Automated + GUI |
| Progress storage | Verified working | Automated; GUI restart check |
| Workspace/question-bank storage | Verified working | Automated + GUI |
| Session and response persistence | Verified working | Automated + GUI history/resume |
| Restart recovery | Verified working | Automated reopen + GUI app restart |
| Duplicate record rejection | Verified working | Automated duplicate question IDs / questions |
| Student ownership isolation | Verified working | Automated + GUI |
| Oracle live compatibility | Not tested | `oracledb` not installed; no live database |

### 2.7 UI and usability

Problems found are listed in section 6 (P3). No redesign was performed.

---

## 3. Passed tests

Final verification results:

| Suite | Result | Checks |
| --- | --- | --- |
| `python -m py_compile codelock/*.py main.py` | PASS | all modules compile (global Python and `.venv`) |
| `python main.py --self-test` | PASS | 159 passed, 0 failed |
| `python main.py --self-test-ui` | PASS | 13 passed, 0 failed |
| Exam GUI audit harness (temporary) | PASS | 24 passed, plus 1 feature observation |
| Focus/dry-run GUI harness (temporary) | PASS | 8 passed |
| Real entry point `main.py --dry-run` | PASS | exit code 0 |
| Analytics performance probe (temporary) | PASS | 300 sessions / 3,600 responses |
| PDF extraction under `.venv` | PASS | pypdf path exercised |

The 159 offline checks cover: hosts round-trip and encoding preservation; crash recovery; accounts
and progress; exam extraction (TXT/DOCX/PDF where available); syllabus approval gating and data
safety; normalized question bank; scoring; practice/mock sessions; analytics (known-value
calculations, ranges, mastery coverage, trends); AI failure paths; all 15 judge reference
solutions plus malformed/slow/hostile submissions; emergency exit logic; and process blocklist
normalization.

The exam GUI harness exercised the real Tk application, real extraction workers, real SQLite
writes and the real judge for: workspace creation, TXT/DOCX upload, unit/topic editing, approval,
note and question generation, duplicate rejection, practice scoring, mock auto-submit, history
resume, and cross-student isolation.

The focus harness exercised the real `CodeLockApp` in dry-run: registration, track picker,
challenge load, wrong submission, sample run, hidden-test pass, reward, forced timer expiry,
relock, and application restart with progress resume.

---

## 4. Failed tests

**No automated or GUI check failed in the final run.** One expected feature gap was recorded as an
observation rather than a failed test:

- **Workspace deletion is not implemented** (reported as Not working in section 2.3). It was not
  added because the audit explicitly prohibits new features.

---

## 5. Features that are only partially working

1. **Real Windows enforcement.** The hosts blocker, process killer and watchdog are implemented and
   tested against a temporary hosts file / blocklist normalization, but the real hosts file was not
   modified and no real process was terminated in this audit. Their real-world effect is **Not
   tested**.
2. **Emergency exit.** Password, wrong-password, unconfigured-confirmation and non-ASCII paths pass
   automated logic tests. The actual `Ctrl+Alt+Shift+Q` keypress in a real kiosk was not exercised.
3. **Anti-paste editor.** Blocking handlers exist for Ctrl+V, Shift+Insert, middle-click, right-click
   and the virtual paste event; they were code-reviewed, not driven by the real clipboard.
4. **Workspace deletion.** No UI action or DB method is exposed.
5. **Manual marking of written answers.** Written answers remain `needs_review`; session score is
   flagged partial, and accuracy excludes unmarked answers. No manual-marking screen exists.
6. **Live AI generation.** Transport and failure handling are tested with a local stub; Gemini,
   Ollama and OpenAI-compatible services were not contacted.
7. **Oracle backend.** Schema, migrations and code paths exist; no live Oracle instance or driver is
   available here.
8. **Exhaustive button coverage.** Principal controls were exercised; not every button on every tab
   was clicked individually.
9. **Analytics presentation.** Numbers are correct; at 980 px the topic table truncates long topic
   names and the trend explanation is clipped.

---

## 6. Bugs and severity

Severity follows the requested classification. All P0/P1 items and the actionable P2 items were
fixed; P3 presentation issues are reported and left for approval.

### P0 - Critical data loss

| ID | Problem | Status | Regression evidence |
| --- | --- | --- | --- |
| P0-1 | Saving a syllabus draft reloaded the workspace and overwrote unsaved Notes/Question Bank edits | Fixed | `ui_smoke`: draft save preserves unsaved note edits |
| P0-2 | Saving the question bank with no valid questions could erase the previously saved bank | Fixed | `ui_smoke`: empty bank cannot erase saved questions |
| P0-3 | Creating or switching a workspace silently discarded unsaved edits | Fixed | `ui_smoke`: declining a switch keeps workspace and edits |

### P1 - Major feature incorrect

| ID | Problem | Status | Regression evidence |
| --- | --- | --- | --- |
| P1-1 | Source grounding accepted very short/generic quotes (e.g. "the"), so invented notes could be certified as grounded | Fixed | `selftest`: short generic quote rejected |
| P1-2 | `not_found` notes could still carry invented facts into the saved bank; nearest-context fallback could return unrelated source text | Fixed | `selftest`: not_found notes cannot carry invented facts |
| P1-3 | Exam sessions could be created with duplicate question IDs, foreign-workspace questions or removed questions | Fixed | `selftest`: duplicate and foreign-session rejection |
| P1-4 | Exam runner allowed overlapping submissions and practice feedback could leave stale response fields | Fixed | GUI practice/mock runs; submission guard code |
| P1-5 | Provider HTTP error text could expose the configured API key | Fixed | `selftest`: key redacted, `[redacted]` present |

### P2 - Incorrect behaviour / usability

| ID | Problem | Status | Regression evidence |
| --- | --- | --- | --- |
| P2-1 | Hosts blocker rewrote non-UTF-8 files as UTF-8 and normalized CRLF, risking corruption of existing entries | Fixed | `selftest`: cp1252 + CRLF round trip |
| P2-2 | An explicit empty process blocklist fell back to the default list | Fixed | `selftest`: empty blocklist stays empty |
| P2-3 | SQLite `record_attempt` could partially write attempt/progress rows on failure | Fixed | Transactional write (code inspection) |
| P2-4 | Non-ASCII emergency passwords could raise during comparison | Fixed | `selftest`: non-ASCII passwords compare without raising |
| P2-5 | Startup log claimed emergency exit was disabled when no password was set (it is confirmation-only) | Fixed | Code inspection |
| P2-6 | Watchdog could re-apply the hosts block while an unlock was in progress | Fixed | Lock + state re-check (code inspection) |
| P2-7 | Mastery could be granted without sufficient answer coverage; trends could be drawn from a single small session; percentages had inconsistent rounding | Fixed | `selftest`: coverage, tiny-latest trend, `format_percent` |
| P2-8 | API keys containing control characters were accepted; a valid JSON envelope with no message was misreported as "not valid JSON" | Fixed | `selftest`: control-character and envelope-shape checks |
| P2-9 | AI transport did not treat `ValueError` during request as a clean provider error | Fixed | Covered by provider failure tests |

### P3 - Cosmetic / presentation

| ID | Problem | Status | Proposed correction (not applied) |
| --- | --- | --- | --- |
| P3-1 | After unlock, the judge-status label still read "RESTORING PC" | Fixed | Label now reads "UNLOCKED"; focus harness asserts it |
| P3-2 | Analytics topic table truncates long topic names; trend explanation text is clipped at 980 px | Open | Increase column widths/wraplength or enable horizontal scrolling in the topic table and trend card |
| P3-3 | Question bank editing is a raw JSON text area | Open | Out of scope for this audit (would be a redesign); a structured editor is a future feature |
| P3-4 | Workspace selector row is tight at minimum width; upload button text touches the control edge | Open | Add a small padx/gap in the row layout |

No P0/P1 issue remains open. The only functional gap is workspace deletion (not implemented), which
is a missing feature rather than a regression.

---

## 7. Screenshots of important UI screens

All screenshots are in `docs/audit/screenshots/`, captured from real Tk windows on the audit
machine. The second group was produced in dry-run mode, so the banner explicitly says nothing is
blocked.

| Screenshot | Screen |
| --- | --- |
| `01-login.png` | Sign-in dialog over the main window |
| `02-exam-empty.png` | AI Exam Preparation, empty workspace |
| `03-exam-syllabus.png` | Syllabus extraction, topic tree and controls |
| `04-exam-notes.png` | Generated revision notes |
| `05-exam-questions.png` | Question bank and duplicate-question warning |
| `06-exam-practice.png` | Practice runner with immediate feedback |
| `07-exam-result.png` | Session result, topic performance |
| `08-track-picker.png` | Track picker before locking |
| `09-focus-locked.png` | Locked dry-run session and challenge editor |
| `10-focus-reward.png` | 15-minute reward state after a real judge pass |
| `11-focus-relocked.png` | Re-locked state after reward expiry |
| `12-exam-analytics.png` | Analytics dashboard with known session data |

**Visual findings:** the analytics topic table clips long topic names and the trend explanation is
cut off at the right edge (P3-2); the workspace selector/upload row is tight (P3-4). No broken
layout prevents a workflow.

---

## 8. Performance measurements

Measured on the audit machine (Windows 10, 8 GB RAM target class). The launch numbers come from the
real `main.py --dry-run` process; generation numbers come from the in-process exam GUI harness.

| Metric | Result |
| --- | --- |
| Startup to sign-in dialog | 0.69-0.75 s (two measured runs) |
| Idle working set | 35.5 MB |
| Idle private memory | 21.3 MB |
| Idle CPU | 0.0% of one core |
| Shutdown time (WM_CLOSE) | 0.09 s |
| Exit code | 0 |
| Exam window + stub note/question generation | 49.2 MB -> 49.8 MB (+0.6 MB) |
| Analytics read: 300 sessions / 3,600 responses | 35.78 ms |
| Analytics dashboard build over those rows | 22.97 ms |
| Analytics UI refresh after a submission | sub-second (observed) |

**Assessment for 8 GB RAM:** the application is light. Idle memory is well under 50 MB, startup and
shutdown are sub-second, and analytics remains fast with years of realistic session volume. AI
responses are capped at 2 MB, so a live generation cannot grow memory without bound.

---

## 9. Security and recovery findings

**Hosts blocking**
- Only a marker-delimited CodeLock section is added/removed; unrelated entries are preserved.
- Encoding (UTF-8 BOM, UTF-16, UTF-8, cp1252) and CRLF/LF are preserved on round trip.
- A one-time `hosts.codelock.bak` backup is created before the first modification.
- Windows writes run through a fixed elevated helper separately installed in
  `%ProgramFiles%\CodeLock\hosts_helper.ps1` by `tools/install_hosts_helper.ps1`; the GUI and Python
  stay unprivileged. Every elevated launch verifies the installation ACL, the manifest and the
  helper SHA-256, then runs only block/unblock/status/recover/repair. The sites, markers and redirect
  address are compiled into the helper. Every result is re-read and verified from the unprivileged
  process. See section 14.
- Hosts writes are atomic (`File.Replace` with an explicit backup, no copy fallback), stale
  `hosts.codelock-*.tmp` files older than one hour are cleaned up, and a failed post-write
  verification reports the observed state.
- Startup detection is read-only. A stale block is reported and reused; it is not removed by the
  unprivileged GUI. Damaged/mismatched markers are classified **DAMAGED**, reported, and repaired
  only through the explicit **REPAIR HOSTS** action or `--restore`.
- Status is the observed file state: **HOSTS FILE BLOCKED / PARTIAL / DAMAGED / NOT BLOCKED /
  STATUS UNKNOWN**. A failed or cancelled block never displays BLOCKED unless a complete block is
  actually present; a failed restore shows the observed state and withholds the reward. The badge
  does not claim network reachability.
- `--restore` remains the documented manual recovery path and uses the same helper on Windows,
  including a `recover` operation for damaged markers. DNS is flushed after a successful change and
  failures are reported separately.
- Real hosts testing was **not** performed; all hosts and helper tests used temporary files.

**Kiosk and emergency exit**
- The emergency password is read only from `CODELOCK_ADMIN_PASSWORD`; there is no default.
- Comparisons use `hmac.compare_digest` over UTF-8 bytes, with non-ASCII handling tested.
- With no password configured, exit requires explicit confirmation rather than being silently
  disabled.
- The window is topmost but not an OS-level kiosk; Alt+Tab and admin tools remain available.

**Coding judge**
- Submissions run via `python -I` in a temporary directory with a 3-second timeout, output caps,
  source-size limit, and an environment allowlist; elevated execution is refused.
- The original audit found a forged-pass vulnerability: the worker held every hidden test and
  expected answer and the parent trusted the worker's verdict. This was remediated on 2026-11-01;
  see section 12 for the new protocol and test evidence.
- It is **not a security sandbox**: submitted code runs as the local user, sees each argument when
  the function is called, and may attempt to read parent memory or automate GUI input. Those limits
  are documented; no attempt is made to claim isolation.

**AI credentials**
- Keys come only from environment variables; they are not stored in the database or source.
- Control characters are rejected before use.
- Provider error text is redacted (key and `Bearer ...`), and HTTP details are truncated.
- No key appeared in any screenshot, log or this report.

**Database**
- Passwords are stored as salted hashes.
- Workspace, session and response reads are scoped by `student_id`; cross-student access was tested.
- SQLite is a local file and is not encrypted; anyone with file access can read or modify it.
- Oracle compatibility was not verified live.

**Recovery**
- Crash/force-kill may leave the hosts block in place; the next launch detects it read-only and
  reuses it. Removing it requires an approved operation or `--restore`.
- A failed hosts restore withholds the reward rather than pretending the PC is unlocked, shows the
  observed state and a modal explanation, and writes `%LOCALAPPDATA%\CodeLock\RECOVERY_REQUIRED.txt`
  (or reports that the file could not be written and prints `--restore` instead).
- The watchdog re-checks hosts read-only; it never re-opens a UAC prompt on its own. **RETRY BLOCK**
  is the explicit retry path.
- The watchdog/unlock race was closed with a lock and state re-check.

---

## 10. Changes made during bug fixing

No features were added. No schema was redesigned. No Phase 3 work was started. DSA Focus Mode
architecture was preserved.

| File | Change |
| --- | --- |
| `codelock/study_generation.py` | Require a meaningful verbatim quote (>=12 chars, >=2 words, word-boundary match); stop returning unrelated whole-source context; replace `not_found` text without invented facts |
| `codelock/ai.py` | Redact keys/Bearer tokens from surfaced errors; reject non-printable keys; catch `ValueError`; distinguish missing-envelope from invalid JSON |
| `codelock/exam_ui.py` | Confirm before discarding unsaved content; preserve note/question drafts across draft save/approval; refuse to save an empty question bank; refresh topic filters; info messages for empty selections; skip attaching an already-submitted runner |
| `codelock/exam_runner.py` | Add submission guard/finally; populate review fields in immediate practice feedback; avoid timer re-entry during submission; fix constructor/focus ordering |
| `codelock/exam_analytics.py` | Add mastery coverage threshold; require 3 graded answers for trend sessions; consistent one-decimal `format_percent`; deduplicate response IDs |
| `codelock/pc_blocker.py` | Preserve hosts encoding/newline style; treat an explicit empty blocklist as empty; keep marker logic strict |
| `codelock/db.py` | Reject duplicate/foreign/removed question IDs in session creation; make SQLite attempt recording transactional |
| `codelock/gui.py` | Serialize hosts enforcement and re-check state; compare emergency password as UTF-8 bytes; correct the startup log; set judge status to UNLOCKED after reward |
| `codelock/selftest.py` | Add regression checks: hosts cp1252/CRLF, syllabus save success/failure, foreign-session rejection, analytics coverage/tiny-trend/formatting, grounding short quotes and not-found, AI control chars, HTTP 400 redaction, missing envelope, 429, malformed JSON, unreachable endpoint, timeout, non-ASCII emergency password, empty blocklist; the local provider stub drains POST bodies to avoid Windows connection-reset flakiness |
| `codelock/ui_smoke.py` | Add regression checks for unsaved-note preservation, empty-bank protection and workspace-switch confirmation; update mastery column index |

Temporary audit harnesses used for evidence: `_audit_launch.py`, `_audit_focus_gui.py`,
`_audit_exam_gui.py`, `_audit_perf.py`. They are not part of the product and were removed after the
report was produced; the screenshots and this report remain.

---

## 11. Remaining limitations

1. **Real enforcement was not tested.** No real hosts-file edit, no real process termination and no
   administrator session were used. Code paths and isolated tests are green, but real Windows
   blocking remains unverified until an approved admin test with a tested recovery path.
2. Hosts blocking does not stop DNS-over-HTTPS, VPNs or direct-IP access.
3. The window is topmost, not a full-screen OS kiosk; Alt+Tab still works.
4. Force-killing CodeLock stops the watchdog; the hosts block remains until `--restore` or the next
   launch.
5. The judge is not a security sandbox; do not run untrusted code with it. The forged-pass path is
   closed (section 12), but same-user memory access and GUI automation remain possible, so a judge
   pass alone no longer unlocks the PC.
6. Oracle/PL-SQL is implemented but not verified against a live database.
7. Gemini, Ollama and OpenAI-compatible providers were not contacted; only transport/failure
   behaviour was verified with local stubs.
8. Workspace deletion is absent; manual marking of written answers is absent; written answers are
   excluded from accuracy until reviewed.
9. Analytics labels/columns clip at the minimum window width (P3).
10. Password recovery does not exist; a lost password requires a new account or direct DB edit.
11. SQLite data is local and unencrypted; shared/multi-user use requires the Oracle backend.
12. Oracle timestamps written in local time can shift sessions across 7/30-day boundaries by the
    server UTC offset.
13. The emergency-exit key binding was tested at logic level, not with a real keypress in a real
    kiosk session.

---

## 12. Post-audit remediation — Priority 1 (2026-11-01)

Backup: `backups/v1.0-remediation-20261101-191023/` with `SHA256SUMS.txt` (25 files).

**Original vulnerability reproduced before the fix.** Four payloads returned `ok=True` against the
old judge: reading `request["tests"]` through `sys._getframe(1)`, clearing the harness test list,
forging the marker line and calling `os._exit(0)`, and rewriting stdout with `os._exit(0)`. A
further probe showed submitted code could open its parent with `PROCESS_VM_READ`.

**Implemented in `codelock/judge.py`, `codelock/gui.py`, `codelock/config.py`, `codelock/selftest.py`:**

| Control | Result |
| --- | --- |
| Trusted-parent oracle | Parent keeps all expected values and hidden metadata; worker receives code, function name and one case's arguments at a time |
| Strict type transport | Only None/bool/int/float/str/list/tuple/dict cross the boundary, tagged and reconstructed in the parent; non-primitives fail |
| Parent-side comparison | The child sends an actual value, never a verdict; `ok`/`passed` fields are ignored |
| Strict framing | Per-session prefix, sequence checks, duplicate/extra/malformed/oversized frame rejection, bounded output |
| Timeouts | 3 s overall and 2 s per case by default; timeout kills the worker tree |
| Windows cleanup | Job Object with `KILL_ON_JOB_CLOSE`, CPU limit and 256 MiB process-memory limit; POSIX process group and rlimits |
| Shutdown | `Judge.shutdown()` terminates active workers; a regression test verifies prompt termination |
| Unlock policy | A judge pass records the attempt, then requires an explicit confirmation dialog; declining keeps the PC locked |

**Verification actually run:**

- `python -m py_compile main.py codelock/*.py` — passed.
- `python main.py --self-test` — **172 checks, 172 pass, 0 fail**. This includes the four attack
  payloads, forged frames, `os._exit`, unsupported types, wrong primitive types, the no-test-data
  init payload, the Windows Job Object, descendant termination and judge shutdown.
- `python main.py --self-test-ui` — **13 checks, 13 pass**.
- Real Tk confirmation check (temporary harness, removed afterwards): declining kept
  `locked=True` with label `PASSED - LOCKED`; confirming called `_unlock`; `_shutdown` completed.

**Remaining limitations (not fixed and not claimed as fixed):**

1. The worker runs as the same user and can still attempt to read the parent process's memory. No
   test in this pass attempted a parent-memory write. True confidentiality needs a separate user,
   restricted token/AppContainer, Windows Sandbox or VM; none is implemented.
2. Each test argument is necessarily visible to the function being called. Only expected outputs
   and the test list are withheld.
3. A same-user process may automate GUI input. The confirmation dialog prevents automatic unlocking
   by the judge code path but is not a security boundary.
4. Job Object assignment is not verified as a security boundary; it is a cleanup and resource-limit
   mechanism. If assignment fails, the code falls back to process-tree termination.
5. The real Windows hosts file was still not modified in this priority.

---

## 13. Post-audit remediation — Priority 2 (2026-11-01)

> **Historical record.** The installation model described in this section (install on the first
> approved operation, source read from the project folder) was rejected in review and replaced by
> section 14. Section 13 remains as the record of the first P2 pass; its one-shot UAC, fixed
> interface, verification and recovery-file controls still apply.

Backup: `backups/v1.0-remediation-p2-20261101-192516/` with `SHA256SUMS.txt` (25 files).

**Threat addressed.** The GUI previously called `HostsBlocker.block()`/`unblock()` in-process, so
blocking only worked if CodeLock itself was elevated — which conflicts with never elevating the
process that runs submitted code. A non-admin session could therefore show a lock while websites
were not blocked, and startup recovery could not remove a stale block either.

**Implemented in `codelock/hosts_helper.ps1` (new), `codelock/hosts_elevation.py` (new),
`codelock/gui.py`, `main.py`, `codelock/selftest.py`, `README.md` and this report:**

| Control | Result |
| --- | --- |
| One-shot UAC | Each block/unblock is one `ShellExecuteExW(..., "runas")` operation; no persistent elevated service, scheduled task or startup change |
| Protected install | The helper is written to `%ProgramFiles%\CodeLock` (resolved through the Windows known folder inside the elevated script) before the operation; no elevated Python runs from the project folder |
| Fixed interface | Only `block`, `unblock`, `status`; sites, markers and redirect IP are compiled in; no caller-provided path, hostname, command or hosts content |
| Unprivileged GUI | Python and Tk never run elevated; `main.py` still refuses an elevated GUI |
| Fail closed | Non-zero helper exit, cancelled UAC, timeout or state mismatch reports **WEBSITES NOT BLOCKED** / **STILL BLOCKED**, never BLOCKED |
| Verified writes | After every operation the client re-reads the hosts file and requires the full managed block (block) or its absence (unblock) |
| Encoding safety | The helper preserves UTF-8/BOM, UTF-16, ANSI and CRLF/LF; a malformed marker pair is refused |
| Recovery | Modal explanation plus `%LOCALAPPDATA%\CodeLock\RECOVERY_REQUIRED.txt` containing `--restore` and the marker lines; the file is removed after a verified restore |
| Read-only watchdog | Re-checks state only; **RETRY BLOCK** is the only automatic-path retry that can prompt UAC |
| Test isolation | `-TestMode` requires a non-real hosts path, is refused in an elevated process, and the helper explicitly refuses the real system hosts path |

**Verification actually run (2026-11-01):**

- `python -m py_compile codelock/*.py main.py` — passed.
- `python main.py --self-test` — **195 checks, 195 pass, 0 fail** at the time of this first pass
  (superseded by 227 checks after section 14):
  - PowerShell helper round trips against temporary hosts: block, status, unblock, three repeated
    blocks (single marker pair), repeated unblocks, cp1252 + CRLF preservation;
  - malformed markers refused with the file untouched; forced write failure; read-only hosts file;
  - UAC cancellation, non-zero helper exit, and "helper says success but state unchanged" all fail;
  - unsupported operations rejected client-side; the elevated command contains no project path or
    Python executable;
  - install target is `...\CodeLock\hosts_helper.ps1` outside the project folder; test mode refuses
    the real hosts path; compiled helper sites/markers/redirect equal `config.py`;
  - GUI: a failed/cancelled block displays only NOT BLOCKED, a verified block displays BLOCKED, a
    failed unlock shows STILL BLOCKED and writes recovery, and the watchdog retry makes no `block()`
    call;
  - the recovery file names `--restore` and both markers and is removed after a verified restore.
- `python main.py --self-test-ui` — **13 checks, 13 pass**.
- Real Tk screenshots using a fake helper result (no hosts access):
  `docs/audit/screenshots/11-p2-websites-not-blocked.png` (LOCKED header, red WEBSITES NOT BLOCKED,
  visible RETRY BLOCK, console reason) and `12-p2-websites-blocked.png` (green BLOCKED after a
  verified retry).
- Real entry point `main.main(["--dry-run"])` with a timer closing the window — exit code 0.
- Consolidated command output: `docs/audit/p2-verification.log`.

**Not tested (requires the separately approved real-system pass):**

- Approving a real UAC prompt and installing the helper into `%ProgramFiles%`;
- Writing/unblocking the real hosts file and confirming browser behavior;
- Real UAC cancellation at the consent dialog (cancellation was simulated at the launcher boundary)
  and real Windows/antivirus file-lock failures;
- `--restore` against the real hosts file (the logic was reviewed; the helper and state verification
  were tested on temporary files only);
- The Program Files ACL was not audited or modified. The design relies on the default machine-wide
  ACL that prevents standard users from writing there.

**Observation about the machine state:** a read-only check made before implementation found two
lines containing `CodeLock block` in the real hosts file. The P2 code path did not write them: every
helper run used temporary files, test mode refuses the real path, and no elevated operation was
executed. The origin is not known from this session. This report does not claim the real hosts file
is clean or blocked; confirming that requires the approved real-system test.

**Remaining limitations:**

1. Each block/unblock needs a UAC approval. This is intentional: no persistent elevated service is
   kept. A user who declines every prompt gets no website blocking, visibly.
2. ~~The first installation trusts the project folder as its source.~~ Superseded by section 14:
   installation is a separate administrator step, and runtime execution verifies the installed
   helper against its protected manifest and ACL.
3. The helper is unsigned PowerShell invoked through the protected `powershell.exe` with
   `-NoProfile -ExecutionPolicy Bypass`; it is not protection against an administrator.
4. Same-user code can still automate the UAC dialog, modify the project, or edit the hosts file
   directly when elevated. The helper does not make the machine tamper-proof.
5. Hosts blocking still does not stop DNS-over-HTTPS, VPNs, direct-IP access or uninstallation.
6. The UAC consent wait is unbounded (the user can leave the prompt open); the helper process itself
   has a 180-second client wait. Shutdown ordering while an operation is pending is Priority 3.
7. Real Windows enforcement and real recovery remain uncertified until the approved admin test.

---

## 14. Priority 2 remediation — trusted installation, recovery and status (2026-11-01)

Backup created before changes: `backups/v1.0-remediation-p2-security-20261101-202455/` with
`SHA256SUMS.txt` covering 45 files; the manifest was re-verified after the backup. The real hosts
file was **not** modified. Its pre- and post-remediation identity is
`SHA-256 2880c05574eac2a0143fb43b9281352ec0bca46024e92efe7593ff3894698b17`, size 552 bytes,
last write 2026-10-30 05:08:44. No helper was installed (`C:\Program Files\CodeLock` remains absent),
no Windows permission was changed, and `--restore` was never run against the real hosts file. All
hosts and helper tests below used temporary files.

### 14.1 P0 — elevated helper source trust

The previous implementation embedded the helper script in the client, refreshed it on every
operation, and computed its hash from the same writable source. That made the hash a consistency
check, not an authenticity check. The remediation removes that path entirely.

| Requirement | Implementation | Evidence |
| --- | --- | --- |
| No refresh from the project on every operation | `HostsAuthority` no longer reads `codelock\hosts_helper.ps1`; elevated execution only runs `self.install_path` | `hosts helper: elevated command runs only the installed script` |
| Trusted installation mechanism | New `tools/install_hosts_helper.ps1` (manual, elevated-only) copies the helper to `%ProgramFiles%\CodeLock\` and writes `hosts_helper.manifest.json` with product, format, helper name, algorithm, SHA-256 and size; it never runs the helper or touches hosts | `hosts helper: a manual installer creates the protected manifest` |
| Verify authenticity before elevated execution | `verify_helper_installation()` runs before every elevated launch; manifest schema and SHA-256 must match the installed file; a hash from the project copy is never used | `trust: installed helper verifies against its protected manifest`; `trust: modifying the installed helper invalidates the manifest`; `trust: an invalid helper signature refuses elevated execution` |
| Installed helper cannot be replaced by a standard user | Installer applies a protected ACL (inheritance disabled, SYSTEM/Administrators full control, Users read/execute, owner Administrators) and the client verifies the DACL before every elevated launch | `trust: a writable installation ACL is rejected`; `trust: a user-writable temp installation fails the real ACL check` |
| Verify the ACL of an existing installation | New read-only `codelock/windows_acl.py` uses `GetNamedSecurityInfoW`/`GetAclInformation`/`GetAce`/`ConvertSidToStringSidW`; checks install directory, its parent, the helper and the manifest | ACL checks above; parser smoke-checked read-only on `C:\Program Files` and `C:\Windows\System32` |
| Clear refusal on verification failure | `_RunOutcome.refused=True`, no UAC, no helper launch; the client reports the exact reason and the observed hosts state | `trust: manifest_product_mismatch/algorithm_mismatch/hash_mismatch/malformed/missing are rejected`; GUI refusal path |
| No UAC or installation in development testing | All tests injected temporary install directories, manifests and ACL inspectors; the real installer was never run | See 14.5 |

Accepted trustees are SYSTEM, Administrators and TrustedInstaller. CREATOR OWNER and OWNER RIGHTS are
accepted only when they resolve to an accepted owner; the current user is accepted only when the
helper is elevated. Unknown write trustees, a missing DACL, a null DACL, and reparse points fail
closed. In production mode the install path must also be under the real Program Files directory.
If verification fails, CodeLock does not fall back to the project copy; website blocking is
unavailable and reported as such.

### 14.2 P1 — recovery safety

- `Write-HostsDocument` writes a GUID-named temporary file in the hosts directory, opens it with
  `FileStream`, flushes with `Flush($true)`, replaces the target with
  `[IO.File]::Replace($temp, $Path, $backup, $true)` using an explicit backup path (required on
  .NET Framework 4.0), or uses `Move` only when the destination does not exist, then reads the file
  back and compares the bytes. There is **no `File.Copy` fallback**.
- A failed replace leaves the original hosts file untouched; forced-write testing confirms the
  original content is unchanged (`hosts helper: forced write failure is reported as NOT BLOCKED`).
- `Remove-StaleTemps` removes only regular `hosts.codelock-*.tmp` files older than one hour and
  ignores errors (`hosts helper: stale temporary files are cleaned, fresh ones kept`).
- Client timeouts call `TerminateProcess`, wait a second time, and mark `reconciled`. An unreconciled
  timeout forces `recovery_required=True`; a reconciled timeout still reports the freshly observed
  state (`hosts helper: an unreconciled timeout requires recovery`;
  `hosts helper: a reconciled timeout reports the observed block`).
- `recover` removes exact CodeLock markers and exact managed `0.0.0.0 <site>` lines, preserves
  unrelated entries, saves a forensic damaged-file copy, and verifies the result. `repair` performs
  recover + fresh block in one elevated run. Tests cover malformed markers, damaged markers, stray
  managed lines, repair verification and unrelated-entry preservation.
- Block/unblock refuse malformed markers and managed entries outside the block rather than guessing.
- After a successful block or unblock the helper runs `ipconfig /flushdns` and returns
  `{attempted, ok, message}`. Failures are appended to the result message; skipped flushes in test
  mode are not reported as failures (`hosts status: DNS failures are reported and skipped flushes
  are not`).
- No success is claimed without a post-operation readback; a simulated failure after the write still
  reports the observed block, not a false NOT BLOCKED (`hosts helper: failed post-write verification
  reports the observed block`).
- The non-Windows direct writer (`pc_blocker.HostsBlocker._write`, unused by the Windows GUI path)
  also no longer falls back to `write_text` when `os.replace` fails; it now fails with an error and
  leaves the original file intact.

### 14.3 P1 — status reporting

| Requirement | Result |
| --- | --- |
| Report observed state after failures | `block()`, `unblock()` and `recover()` re-read the hosts file after the helper outcome and classify it; tests cover failed-but-blocked and cancelled-with-existing-block |
| Never show NOT BLOCKED while a valid block remains | `classify_state()` returns BLOCKED/PARTIAL/DAMAGED/NOT BLOCKED/UNKNOWN; GUI maps them with `HOSTS_DISPLAY`; `a failed helper never hides an observed active block` |
| UAC cancellation with an existing block | Cancellation reports **HOSTS FILE BLOCKED (observed)** when the previous valid block is present (`UAC cancellation with an existing block keeps BLOCKED`) |
| Recovery file must be real or reported missing | `write_recovery_file()` result is checked; GUI and `--restore` say "Recovery instructions could not be saved" and print the `--restore` command if no file could be written |
| Flush DNS honestly | DNS payload parsed separately; failure text is appended, success is not claimed (`dns_flushed`/`dns_message`) |
| Distinguish hosts block from network reachability | Badge is titled **HOSTS FILE**; `WEBSITE_ACCESS_NOTE` states that network reachability was not tested and is shown after lock/unlock logs |

The GUI now offers **REPAIR HOSTS** for a damaged marker set, keeps **RETRY BLOCK** visible after a
failed unlock, and reports the observed status in `_finish_unlock`. `main.py --restore` reports
damaged markers separately, invokes `recover`, verifies the outcome, and reports DNS failures.

### 14.4 Files changed

`codelock/hosts_elevation.py`, `codelock/hosts_helper.ps1`, `codelock/windows_acl.py` (new),
`tools/install_hosts_helper.ps1` (new), `codelock/gui.py`, `main.py`, `codelock/selftest.py`,
`README.md`, `CODELOCK_AUDIT_REPORT.md`.

### 14.5 Verification actually run (2026-11-01)

```
python -m py_compile main.py codelock/*.py          # PASS
PowerShell parser (both .ps1 files)                 # PASS
python main.py --self-test                          # PASS - 227/227
python main.py --self-test-ui                       # PASS - 13/13
python main.py --dry-run                            # PASS - opened, SIMULATED badges, exit 0
```

Consolidated output: `docs/audit/p2-verification.log` (remediation section appended to the earlier
Priority 2 log). The in-process Tk dry-run showed `HOSTS_BADGE=SIMULATED` and
`KILLER_BADGE=SIMULATED`; the real entry point closed via `WM_CLOSE` with exit code 0.

New regression areas, all passing in `--self-test`:

- Trust: valid manifest, project-copy tampering ignored, installed-helper tampering rejected,
  product/algorithm/hash/malformed/missing manifests rejected, writable ACL rejected,
  user-writable temp directory rejected by the real ACL inspector, non-Program-Files path rejected
  in production, manual installer writes the manifest.
- Recovery: atomic replace with no copy fallback, stale temp cleanup, forced write failure leaves
  the original intact, failed post-write verification reports the observed block, malformed/damaged
  markers classified and repaired, stray managed entries removed, incomplete block is PARTIAL.
- Timeout: reconciled and unreconciled timeout reporting.
- Status: UAC cancellation with an existing block keeps BLOCKED, failed helper does not hide an
  active block, failed unlock withholds the reward, damaged state offers REPAIR HOSTS, DNS failure
  reporting, read-only watchdog retry.
- GUI: `--dry-run` startup showed `HOSTS: SIMULATED` and `KILLER: SIMULATED`; the real entry point
  accepted a window close and exited 0.

The real hosts file hash, size and mtime were re-checked after all tests and are unchanged. No
`C:\Program Files\CodeLock` directory was created. No real UAC prompt was raised.

A read-only inspection confirmed the reviewer's finding about the existing machine state: the real
hosts file has **23 lines**, consisting of exactly one CodeLock begin marker, 21 managed
`0.0.0.0 <site>` lines and one CodeLock end marker. It has **no localhost entries** and no other
non-empty lines. `hosts.codelock.bak` exists and is **0 bytes**. This remediation did not modify,
restore, delete or replace the real hosts file or its backup, and did not run `--restore` against
it. Repairing that pre-existing machine state (adding default localhost entries or rebuilding the
backup) is outside the approved scope and requires a separate, explicitly approved procedure.
`Backup-Original` never overwrites an existing `hosts.codelock.bak`, so the zero-byte backup will
remain until an administrator handles it deliberately; CodeLock does not claim that backup is a
usable copy of a normal hosts file.

### 14.6 Not tested in this environment

- Approving a real UAC prompt and running the elevated installer; the real Program Files ACL was not
  inspected because no installation exists and the constraint forbade creating one.
- Real hosts-file replacement under Windows file locks, antivirus interference or a crash between
  temp write and replace. The atomic API path was exercised on temporary files, including a forced
  pre-write failure, but not real power loss.
- Real UAC cancellation at the consent dialog and real `ipconfig /flushdns` behavior (test mode
  skips the flush; payload handling is unit-tested).
- Same-user attack against the installed directory (only fixture ACLs were exercised).

### 14.7 Remaining limitations

1. **Administrator trust boundary.** An administrator can replace the helper, its manifest and the
   ACL. The verification protects against standard-user replacement and accidental corruption, not
   against an administrator. The installer itself is unsigned.
2. **No real-install certification.** `%ProgramFiles%\CodeLock` did not exist, so the production
   ACL path, installer behavior and real integrity check have not been executed on a real install.
   The read-only ACL parser was smoke-checked on `C:\Program Files` and `C:\Windows\System32`.
3. **UAC automation.** Same-user code can still automate the consent dialog. One-shot UAC reduces
   exposure but is not an OS security boundary against a hostile same-user process.
4. **Timeout race.** If the elevated process cannot be terminated, a late write is still possible;
   the client marks the result as requiring recovery and never claims success.
5. **Network reachability.** `HOSTS FILE BLOCKED` is a file-state claim only. DoH, VPNs, direct IP
   access and browser caches are outside this check.
6. **Shutdown ordering while an operation is pending** is still Priority 3 and was not changed.

---

## 15. Final product readiness assessment

| Area | Readiness |
| --- | --- |
| Launch, login, navigation, exit | Ready. Verified through the real entry point in dry-run and real Tk windows. |
| DSA Focus Mode (in dry-run/isolated) | Ready. Full lock -> wrong attempt -> samples -> hidden tests -> reward -> relock -> restart loop passes. |
| DSA Focus Mode (Windows hosts blocking) | Implemented with the one-shot UAC helper and a separately installed, manifest- and ACL-verified helper (section 14). Verified on temporary hosts files. A real installation, real UAC approval and real hosts writes are not certified until the approved admin test. |
| DSA Focus Mode (real Windows enforcement) | Not certified. Requires an explicitly approved admin test; the app itself stays unprivileged. |
| AI Exam Preparation | Ready with SQLite and a configured provider. Creation, extraction, editing, generation, practice, mock, results, history/resume and isolation pass. Deletion and manual marking are not implemented. |
| Analytics | Ready. Known-data calculations and edge cases pass. Presentation clipping is cosmetic. |
| AI providers | Transport and failure handling are ready; live provider compatibility is unverified. |
| SQLite persistence | Ready. Restart persistence and isolation pass. |
| Oracle persistence | Not certified (no live test). |
| Security/recovery | Priority 1 forged-pass path closed (section 12); Priority 2 remediation (section 14) adds a protected, manifest- and ACL-verified helper installation, atomic hosts replacement, stale-temp cleanup, timeout reconciliation, damaged-marker repair and observed-state reporting. Documented limits remain: administrator trust boundary, same-user UAC automation, hosts bypass, local SQLite, topmost not kiosk. |

**Overall:** The application is functionally coherent and stable for personal, single-user use in
dry-run and for exam workflows with the local SQLite store. The P0 and P1 issues raised in the
Priority 2 review were addressed in section 14 and verified with offline and temporary-file tests;
acceptance is the reviewer's decision. It should **not** be described as having "working real Windows
enforcement" or "secure code execution" until an approved administrator test verifies UAC approval,
the real Program Files installation and ACL, hosts blocking, process termination, emergency exit and
crash recovery, and until OS-level isolation is implemented for hostile code.

### Final verification commands (run after all fixes)

```
python -m py_compile main.py codelock/*.py     # PASS
PowerShell parser, both .ps1 files             # PASS
python main.py --self-test                     # PASS - 227 checks (after P2 remediation)
python main.py --self-test-ui                  # PASS - 13 checks
python main.py --dry-run                       # PASS - real entry point, SIMULATED badges, exit 0
```

Supplementary evidence: 24 exam GUI checks, 8 focus GUI checks, PDF extraction under `.venv`, and the
analytics performance probe. The two P2 screenshots in `docs/audit/screenshots/` predate the badge
rename from WEBSITES to HOSTS FILE and the observed-state changes; they are historical, not current
evidence. Real UAC approval, Program Files installation, real hosts writes, real process termination
and live Oracle/AI services remain **Not tested** by design of the safety constraint.

The overall assessment is unchanged: CodeLock is coherent for personal, single-user use and for
exam workflows. The reported P0/P1 issues are remediated and evidenced to the extent possible without
a real-system pass, but real Windows enforcement and the trusted-installation path are not certified
until the approved administrator test and OS-level isolation exist.
