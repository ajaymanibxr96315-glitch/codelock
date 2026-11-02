# CodeLock v1.0 — Final Submission Report

**Date:** 2026-11-01
**Updated:** 2026-11-02
**Version:** 1.0.0
**Scope:** Final stabilization for a college project demonstration
**Verdict:** **Ready for local demonstration and code review.** The application launches, the
DSA and AI Exam Preparation workflows run end to end, and the full offline test suite passes.
Real Windows enforcement (hosts file, UAC, helper installation) was deliberately **not**
performed and is **not certified** by this report.

---

## 1. Status

| Item | Result |
| --- | --- |
| Application starts and exits cleanly | **Passed** (system Python, project venv, and launcher) |
| Login / registration / mode chooser | **Passed** |
| Complete DSA challenge workflow | **Passed** (wrong answer → correct answer → unlock → reward → relock) |
| Complete exam workflow | **Passed** (workspace → TXT upload → approval → question bank → practice → mock → analytics) |
| SQLite storage | **Passed** (temporary databases; Oracle fallback only) |
| Offline self-tests | **Passed** (227/227 system, 228/228 venv, 13/13 UI in both) |
| Real hosts-file blocking | **Not performed / unverified by design** |
| Live AI provider | **Not performed / unverified** |
| Live Oracle backend | **Not performed / unverified** |

No application source file was changed during the initial freeze; the work was release packaging and
documentation only: a launcher, corrected dependency classification, README corrections, backups, and
this report. After the freeze, a user-reported navigation defect was fixed with a three-line change
in `codelock/gui.py`: the topmost track picker stayed above Exam Preparation, and its close button
refused to exit setup. The picker is now hidden while the exam window is open, restored when it
closes, and an unstarted setup can exit cleanly. A second report — workspace creation with “no
option visible” — was a window-stacking defect: after the topmost picker was hidden, the Exam
Preparation window stayed behind the previously active application. It now raises itself for 1.2 s
and takes focus (`codelock/exam_ui.py`). A third, requested change replaced the four-track picker
with a two-button mode chooser: after sign-in, **1. Exam Preparation** opens the exam workspace
without locking, and **2. DSA Practice** starts an Engineering session and locks immediately. The
chooser cannot be closed with X, and closing the Exam Preparation window exits CodeLock. The judge,
unlock, database, and AI behavior are unchanged. No architecture, database, AI, or judge behavior
was changed.

**Stop condition:** development stops here. No Priority 3/4 expansion, real Windows integration
testing, or further optimization was started.

---

## 2. Implemented Features

- **Student accounts:** registration and sign-in, display name, per-student progress, SQLite by
  default with an optional Oracle/PL-SQL backend and automatic fallback.
- **Four DSA study tracks:** Engineering, Maths, School, Biology, with ordered challenges and saved
  resume position.
- **Coding judge:** hidden tests, per-test timeouts, output limits, subprocess isolation with a
  Windows Job Object, anti-forgery checks, and explicit confirmation before unlock.
- **Focus/reward cycle:** challenge lock state, 15-minute reward timer, automatic relock, next
  challenge rotation, attempt and completion timing.
- **Optional real blocking:** website blocking through a protected, elevated hosts-file helper;
  optional process blocking through `psutil` or `tasklist`/`taskkill`. When the helper is absent,
  the app reports the real observed status instead of pretending to block.
- **Emergency recovery:** admin exit, recovery instructions, and the existing `--restore` path are
  preserved.
- **AI Exam Preparation:** TXT and DOCX extraction with the standard library, PDF extraction with
  `pypdf`, topic/unit extraction and editing, explicit syllabus approval, source-grounded note and
  question generation through a configured provider, manual validated question banks, practice and
  timed mock sessions, immediate objective scoring, manual review for written answers, result
  windows, history, and analytics/mastery views.
- **Dry-run mode:** exercises the full UI and workflows while simulating enforcement and never
  touching the hosts file or requesting elevation.
- **Self-tests:** 227–228 backend checks plus 13 Tk smoke checks.

---

## 3. Files Changed in This Phase

| File | Change | SHA-256 |
| --- | --- | --- |
| `run_codelock.bat` | **New.** Project-relative launcher; detects `.venv\Scripts` or MSYS2 `.venv\bin`, then `py -3`, then `python`; checks Tkinter and warns (but continues) if `pypdf` is missing; passes arguments through; pauses on failure. | `c5354321c2d37f71b4f71b07558ec34ec91ed96fdaa1517e867856f5d1277c94` |
| `requirements.txt` | Rewritten to classify dependencies: `pypdf` required for PDF upload; `psutil` optional with fallback; `oracledb` optional for Oracle. | `094a5487b8bf7b80e510f36c924a9eb67d373f3dcb7ed9ecb5a83fe67924216d` |
| `README.md` | Corrected install/launch instructions for both venv layouts, launcher usage, optional-dependency behavior, troubleshooting, limitations, self-test counts, final verification notes, and the two-button Exam/DSA mode chooser. | `d694d7c72b96f1fa4cb5a4d953ceffa0ed33412e05ff49ad493559eaba73f70e` |
| `CODELOCK_FINAL_SUBMISSION_REPORT.md` | **New.** This report. | — |
| `codelock/gui.py` | **Post-freeze navigation fix, then two-button mode chooser.** Replaced the four-track picker with Exam Preparation (no lock) first and DSA Practice (Engineering + lock) second; blocked closing the chooser; made the exam window’s X exit CodeLock. | `58afe065a36a8e6dd0beb97b60006315b7ac379b8b615f08b408500f0dbc8e57` |
| `codelock/exam_ui.py` | **Post-freeze visibility fix.** Raise the Exam Preparation window (`-topmost`, `lift`, `focus_force`, released after 1.2 s) so its CREATE-workspace form is not hidden behind the previously active application after the topmost picker is withdrawn. | `2f66aad6118c4243068690cbf6f172b884ce391182c7dfc0b63045231de27397` |

`main.py` was not changed; its hash still matches the pre-edit backup:
`689f47ce554b5ad454f948301742ea439d67b24017ac05cbea20e1ec22b17e68`.

### Launch/demo problems found and fixed

The inspection found **no launch-blocking source defect**. The only demo blockers were packaging and
documentation:

1. The documented venv activation path assumed `.venv\Scripts`, but this project’s venv uses the
   MSYS2 `.venv\bin` layout.
2. No one-click launcher existed, so a student had to know the correct interpreter.
3. `requirements.txt` did not distinguish required from optional dependencies.
4. The README hardcoded an absolute project path, which conflicts with the portability requirement.
5. The README reported a single self-test count although the PDF checks add one test when `pypdf`
   is installed.

---

## 4. Backup and Manifest Verification

### Pre-edit backup (created before this phase’s edits)

- Location: `backups/v1.0-final-submission-20261101-220202`
- Contents: 31 tracked files (source, docs, tools, schema/migrations, data DB), plus the manifest
- Manifest: `SHA256SUMS.txt`, LF line endings
- Verification: `sha256sum -c SHA256SUMS.txt` → exit 0, **31/31 OK**

### Final-state snapshot (created after all packaging/doc edits, before this report)

- Location: `backups/v1.0-final-submission-final-20261101-221842`
- Contents: 46 tracked files, including `run_codelock.bat` and the corrected `README.md`/`requirements.txt`, plus the manifest
- Manifest: `SHA256SUMS.txt`, LF line endings
- Verification: `sha256sum -c SHA256SUMS.txt` → exit 0, **46/46 OK**

### Post-fix snapshot (created after the navigation fix and this report update)

- Location: `backups/v1.0-final-submission-navfix-20261102-010641`
- Contents: 47 tracked files, including the fixed `codelock/gui.py` and this report, plus the manifest
- Verification: `sha256sum -c SHA256SUMS.txt` → exit 0, **47/47 OK**

### Exam-visibility snapshot (created after the focus fix and this report update)

- Location: `backups/v1.0-final-submission-examfocus-20261102-0127`
- Contents: 47 tracked files, including the fixed `codelock/exam_ui.py` and this report, plus the manifest
- Verification: `sha256sum -c SHA256SUMS.txt` → exit 0, **47/47 OK**

### Mode-chooser snapshot (created after the two-button change and this report update)

- Location: `backups/v1.0-final-submission-modechooser-20261102-210121`
- Contents: 46 tracked files (source, docs, tools, schema/migrations); the runtime `data/` store is
  intentionally excluded, plus the manifest
- Verification: `sha256sum -c SHA256SUMS.txt` → exit 0, **46/46 OK**

Stray files created outside the project during testing were moved to
`backups/stray-outside-cleanup-20261101-230822` (a test `codelock.db` and a drive-root
`.gitignore`), and all temporary test scripts, logs, and databases were removed.

Three earlier remediation backups remain untouched:
`v1.0-remediation-20261101-191023`, `v1.0-remediation-p2-20261101-192516`,
`v1.0-remediation-p2-security-20261101-202455`.

### Real Windows state (read-only checks before and after testing)

| Check | Result |
| --- | --- |
| Real hosts file SHA-256 | `2880c05574eac2a0143fb43b9281352ec0bca46024e92efe7593ff3894698b17` (identical before and after) |
| Real hosts file size | 552 bytes (unchanged) |
| Real hosts file modification time | Unchanged |
| `C:\Program Files\CodeLock` | Absent (`False`) |
| UAC prompts triggered | None |
| Windows permissions / registry / startup changed | None |
| Elevated helper installed | No |

---

## 5. Tests and Exact Results

Environment: Windows 10 x64, Python 3.14.7, Tk 8.6. System Python has no `pypdf`; the project venv
(Msys2 layout) has `pypdf`.

### 5.1 Compilation

| Command | Result |
| --- | --- |
| `python -m py_compile main.py codelock/*.py` | exit 0 |
| `.venv/bin/python -m py_compile main.py codelock/*.py` | exit 0 |

### 5.2 Offline suite

| Command | Result |
| --- | --- |
| `python main.py --self-test` | exit 0, **227 PASS, 0 FAIL** |
| `python main.py --self-test-ui` | exit 0, **13 PASS, 0 FAIL** |
| `.venv/bin/python main.py --self-test` | exit 0, **228 PASS, 0 FAIL** (both PDF checks run) |
| `.venv/bin/python main.py --self-test-ui` | exit 0, **13 PASS, 0 FAIL** |

The count difference is intentional: without `pypdf`, one check verifies the clear missing-dependency
message; with `pypdf`, two checks verify PDF text extraction and image-only-PDF detection.

### 5.3 Launcher

| Command | Result |
| --- | --- |
| `run_codelock.bat --version` | exit 0; selected `"D:\blocker\.venv\bin\python.exe"`; printed `CodeLock 1.0.0` |
| `run_codelock.bat --self-test` | exit 0, **228 PASS, 0 FAIL** |
| `run_codelock.bat --self-test-ui` | exit 0, **13 PASS, 0 FAIL** |
| `run_codelock.bat --dry-run` + window close | Window `CodeLock - PC Distraction Blocker` found; WM_CLOSE posted; **launcher exit 0** |

### 5.4 Complete end-to-end workflow harness

Run in a temporary database with `dry_run=True`; no privileged calls. Result: **30/30 checks passed,
0 failed.** The harness was run before the two-button chooser was added; its judge, reward, relock
and exam results are unaffected by that entry-point change. The new chooser paths were re-verified
separately in §5.8 (23/23).

| Check | Observed evidence |
| --- | --- |
| Login dialog opens | present |
| Database backend | `SQLite (local)` |
| Registration opens the study entry | user `finaldemo` created |
| Engineering entry works | `Warm-up: Addition` loaded, starter code present |
| Wrong submission | verdict **FAILED**; progress attempts=1, completed=0, index=0 |
| Correct submission | verdict **UNLOCKED** after explicit confirmation |
| Reward timer | `14:59` |
| Progress advancement | attempts=2, completed=1, index=1 |
| Reward expiry / relock | locked=True, timer `--:--`, challenge index=1 |
| Exam window | opens with **7 tabs** |
| Workspace | created (ID 1) |
| TXT upload | `Extracted 186 characters from networks.txt...`; 2 units extracted |
| Syllabus approval | approved |
| AI without provider | honest error: `AI generation is unavailable. Set CODELOCK_AI_PROVIDER to ollama, gemini, or openai-compatible and configure its model.` |
| Manual question bank | `Saved 3 validated questions.` (3 in DB) |
| Practice session | 3 questions; all three answers checked **CORRECT** |
| Practice submission | result window opened; scored **3.0/3** |
| Mock session | 3 questions; submit opened result window |
| Results history | **2 sessions** listed |
| Analytics | `Computer Networks · All Time · 2 submitted session(s)` |
| Shutdown | clean; root window destroyed |

A separate SQLite check (earlier in the same phase, source unchanged) confirmed register/login and
progress persistence in a temporary database, with the Oracle path exercised only through its
fallback and schema inspection.

### 5.5 Test classification

- **Passed:** compilation; 227/228 backend checks; 13 UI checks; launcher; dry-run launch/close;
  complete DSA workflow; complete exam practice and mock workflows; SQLite; shutdown; hosts file
  unchanged.
- **Failed:** none.
- **Simulated / mocked:** all enforcement in `--dry-run`; hosts/process backends in the offline
  suite; PowerShell helper tests against temporary hosts files; message-box confirmations answered
  programmatically by the harness.
- **External services not tested live:** AI providers (Ollama/Gemini/OpenAI-compatible), Oracle.
- **Not performed:** real hosts modification, UAC approval, helper installation, Windows permission
  changes, registry/startup changes, real process termination, real OCR.

### 5.6 Post-freeze navigation fix

A user reported that after sign-in the setup window would not close and that Exam Preparation opened
behind the topmost track picker, leaving no way back. Reproduced with a fake hosts backend and a
temporary database (no real hosts/UAC access):

| Before fix | After fix |
| --- | --- |
| Picker stayed visible and `-topmost=1` above the exam window (`-topmost=0`) | Picker is hidden while the exam window is open and restored on close |
| Picker X in normal mode left the app running (`_shutting_down=False`) | Picker X during setup shuts down cleanly (`_shutting_down=True`, root destroyed) |

After the fix, the full offline suite was rerun: `py_compile` exit 0; `--self-test` 227/227 (system)
and 228/228 (venv); `--self-test-ui` 13/13 in both. A dry-run navigation regression confirmed:
login → picker → exam opens (picker hidden) → exam closes → Engineering tile selects the first
challenge → clean shutdown. Temporary probe databases and scripts were removed afterward.

The picker’s exit behavior described above was later superseded by the mode chooser in §5.8: the
chooser’s X now keeps the window open, and the exam window’s X exits CodeLock.

### 5.7 Post-freeze exam-window visibility fix

A second report said workspace creation was unusable because “no option is visible”. The running
application was inspected live, read-only, without interacting with it: `EnumWindows` reported
`CodeLock — Exam Preparation` as `visible=True` at 0,0–996×739, but `GetForegroundWindow()` was
another application whose window covered it completely. Withdrawing the topmost picker handed the
foreground back to that application, and the new Toplevel never raised itself — so the entire
Syllabus tab, including the CREATE button, was hidden behind it.

Fix in `codelock/exam_ui.py`: after the window is built, it sets `-topmost`, calls `lift()` and
`focus_force()`, and releases `-topmost` after 1.2 s.

| Check | Before | After |
| --- | --- | --- |
| Exam window relative to other application | Behind it (foreground = other app) | Topmost at z-order index 0 and foreground |
| CREATE-workspace controls | Covered with the window | Window mapped, CREATE button topmost at its screen coordinates |
| `-topmost` release | — | Cleared after 1.6 s; window stays above |
| Window closed before 1.2 s | — | Delayed callback exits without error |

`py_compile` (both interpreters), `--self-test` 227/227 and 228/228, and `--self-test-ui` 13/13 in
both were rerun after this change. Temporary probe databases, screenshots and scripts were removed.

### 5.8 Post-freeze two-button mode chooser

Requested change: after student login, show two buttons — Exam Preparation first and DSA Practice
second — where DSA starts the DSA session and the other choice does not initiate a lock. Confirmed
behavior choices: DSA starts Engineering directly; closing the chooser keeps it open; closing the
Exam Preparation window exits CodeLock.

Changes in `codelock/gui.py`:

- `_show_mode_picker()` replaces the four-track grid with two stacked full-width buttons.
- **1. Exam Preparation** opens the existing workspace with `track=None`; no watchdog, hosts write,
  or process-killer start is triggered.
- **2. DSA Practice** calls `_select_track(ENGINEERING)` directly.
- `_on_picker_close()` and the root-X guard keep the chooser open until a mode is chosen; dry-run
  **Esc** still exits.
- `_exam_closed()` now shuts CodeLock down; an active exam session still refuses its own close.
- The setup placeholder, sign-in footer, and header text now describe the two modes.

Verification in a temporary database with `dry_run=True` (no privileged calls): **23/23 checks
passed**.

| Check | Result |
| --- | --- |
| Exactly two buttons; Exam first, DSA second | Passed |
| Picker X and root X while choosing | Blocked; app stays open |
| Exam path | Workspace opens, `track=None`, no watchdog, picker hidden |
| Exam window X | CodeLock shuts down, root destroyed |
| DSA path | Engineering selected, `Warm-up: Addition`, DRY RUN header, picker closed |
| Dry-run close after DSA | Clean exit |

Regression after the change: `py_compile` clean; `--self-test` 227/227 (system) and 228/228 (venv);
`--self-test-ui` 13/13 in both. No hosts file, UAC, helper, registry, or permission operation was
performed.

---

## 6. How to Run

### Recommended for the demonstration

```bat
run_codelock.bat --dry-run
```

This shows every screen and workflow, displays SIMULATED enforcement, and never touches the hosts
file or asks for elevation. Use **EXIT DRY RUN**, the main window’s title-bar X, or **Esc** on a
dialog to exit with code 0. The mode chooser’s X is blocked, and closing the exam window exits
CodeLock.

### Normal launcher

```bat
run_codelock.bat
```

The launcher uses the project venv if present, otherwise `py -3` or `python`. If the elevated helper
is not installed, the session still starts and reports the real status (**NOT BLOCKED**); no UAC
prompt is raised merely by starting the app.

### Manual setup

```bat
python -m venv .venv
```

Standard Windows layout:

```bat
.venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py --dry-run
```

MSYS2 layout used by this project:

```bat
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py --dry-run
```

`pypdf` is required only for PDF syllabus upload; TXT and DOCX use the standard library. `psutil` and
`oracledb` are optional.

### Useful commands

| Command | Purpose |
| --- | --- |
| `python main.py` | Normal mode |
| `python main.py --dry-run` | Simulated session, no hosts/UAC changes |
| `python main.py --self-test` | Backend test suite |
| `python main.py --self-test-ui` | Tk smoke checks |
| `python main.py --restore` | Existing recovery path (needs administrator rights when a real block exists) |
| `run_codelock.bat [args]` | Launcher with argument passthrough |

Default data location: `data/codelock.db` (override with `CODELOCK_DB_PATH`). Accounts and progress
persist between runs.

---

## 7. Limitations

1. **The judge is not a security sandbox.** Submitted student code runs as the current user. The
   app says this explicitly before unlocking; it must not be described as a secure sandbox.
2. **Real website blocking requires the elevated helper.** The helper was not installed or tested
   live. Without it the app truthfully reports **NOT BLOCKED**.
3. **Real UAC, hosts-file writes, permissions, and process termination were not exercised.** Those
   paths are covered only by offline tests and temporary-file simulations.
4. **No live AI provider was tested.** Without configuration, generation correctly reports that it
   is unavailable; the manual question-bank path works.
5. **No live Oracle instance was tested.** SQLite is the operating backend; Oracle is a fallback
   path verified only by schema/query inspection.
6. **OCR is not configured.** Image-only PDFs are detected and reported; their text is not extracted.
7. **Written answers are saved for manual review.** Only objective types are auto-scored.
8. **Analytics suppresses accuracy estimates until enough graded answers exist.**
9. **Blocking is hosts-based.** DNS-over-HTTPS or applications that ignore the hosts file are not
   guaranteed to be covered.
10. **Desktop only.** There is no phone/ADB control in this version.

---

## 8. Future Enhancements (Not Started)

- Priority 3: shutdown/recovery ordering hardening.
- Priority 4: full integration test matrix, including real hosts/UAC/helper behavior on a disposable
  machine with `--restore` prepared.
- Live-provider tests for notes and question generation, with explicit provider configuration.
- Live Oracle verification of exam CLOB columns and analytics.
- Signed helper installer and automated ACL verification.
- Question-bank import/export and accessibility improvements.

None of these were implemented, by instruction.

---

## 9. Suggested Demonstration Flow (About 6–8 Minutes)

1. Start `run_codelock.bat --dry-run`. Point out the **DRY RUN / TEST MODE** header.
2. Create an account with a fresh username. The mode chooser opens with **1. Exam Preparation** and
   **2. DSA Practice**.
3. Click **1. EXAM PREPARATION** (the PC stays unlocked):
   - Create a workspace (subject, level, exam date).
   - Upload a short TXT syllabus, for example:

     ```text
     Unit 1: Networks
     The OSI model organizes communication into seven layers.
     The application layer is closest to the user.
     Unit 2: Addressing
     An IP address identifies a device on a network.
     ```

   - Review the extracted units/topics, then click **APPROVE SYLLABUS**.
   - Click **GENERATE** to show the honest “AI generation is unavailable” message (no provider
     configured), then save a small manual MCQ bank and explain source checks.
   - Start **PRACTICE**, answer a question and click **CHECK ANSWER**, then submit and show the
     result window. Start and submit a **MOCK** session, then show Results and Analytics.
   - Close Exam Preparation (this exits CodeLock by design). Start `run_codelock.bat --dry-run`
     again and sign in as the same student.
4. Choose **2. DSA PRACTICE**. Show the locked Engineering challenge screen.
5. Submit a wrong solution first (`return a - b`) to show **FAILED** and that progress does not
   advance. Then submit the correct one:

   ```python
   def add(a, b):
       return a + b
   ```

6. Confirm the unlock prompt. Show **UNLOCKED**, the 15-minute timer, and the saved progress. Explain
   that dry-run simulates enforcement; real mode would restore the hosts file through the helper.
7. Close the window while unlocked (or let the timer expire to show relock and challenge rotation).
   The launcher exits 0.
8. If asked about real blocking, state honestly: the helper was not installed during testing, the
   app reports **NOT BLOCKED**, the real hosts file was hash-verified unchanged, and no UAC prompt
   was raised.

---

## 10. Final Statement

The CodeLock application is runnable and demonstrable today with `run_codelock.bat --dry-run`.
Compilation, the full offline suite, the launcher, GUI startup/shutdown, and the major DSA and exam
workflows have been exercised successfully. Privileged Windows enforcement and external AI/Oracle
services remain unverified and are reported as such rather than claimed as complete.

**Development stops here.**
