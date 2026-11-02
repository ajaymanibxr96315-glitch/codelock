# CodeLock

**A student desktop app with DSA Focus Mode and AI Exam Preparation.**

CodeLock is a Python/Tkinter kiosk app for students who keep losing focus. It blocks
distracting websites through the operating system hosts file, terminates blacklisted desktop apps,
and only unlocks the PC after your code passes hidden test cases and you confirm the unlock in a
separate dialog.

At launch it asks which track you are studying — **Engineering**, **Maths**, **School** or
**Biology** — and pulls every challenge from that track. A student account records each attempt,
how many seconds the challenge took, and your progress per track. Accounts and progress live in
Oracle (via PL/SQL) when configured, or in a local SQLite database otherwise.

Exam Preparation workspaces share the signed-in student and database. Syllabus files are extracted
locally from PDF, Word (`.docx`) or TXT, topics remain editable until approved, and AI generation
uses only an explicitly configured provider. The app does not silently make up notes or questions
when a provider is unavailable.

---

## Contents

- [How it works](#how-it-works)
- [Tech stack](#tech-stack)
- [Requirements](#requirements)
- [Installation](#installation)
- [Running CodeLock](#running-codelock)
- [Using the kiosk](#using-the-kiosk)
- [The challenges](#the-challenges)
- [AI Exam Preparation](#ai-exam-preparation)
- [Command-line reference](#command-line-reference)
- [Configuration](#configuration)
- [Student accounts and progress](#student-accounts-and-progress)
- [The coding judge](#the-coding-judge)
- [Project structure](#project-structure)
- [Safety and crash recovery](#safety-and-crash-recovery)
- [Troubleshooting](#troubleshooting)
- [Limitations and responsible use](#limitations-and-responsible-use)
- [Verification](#verification)

---

## How it works

```
                         +--------------------------------------+
                         |        Tkinter kiosk window          |
                         | topmost - close trapped - anti-paste |
                         +------------------+-------------------+
                                            |
              watchdog thread (daemon)      |      submit -> judge thread
        +-------------------+---------------+--------------------+
        |                   |                                    |
        v                   v                                    v
 HostsAuthority     ProcessKiller                        Judge
 -> UAC -> PS1      psutil / taskkill                    python -I subprocess
 Program Files      kills blacklisted                    temp cwd, 3 s timeout
 hosts file         desktop apps                         visible + hidden tests
 verifies state
```

1. **Sign in.** Create a student account or log in. The local SQLite store always works; Oracle is
   used when it is configured.
2. **Choose a mode.** After sign-in, choose **1. DSA Practice** to start an Engineering coding session
   and lock the PC immediately, or **2. Exam Preparation** to open the exam workspace without locking
   the PC. The choice window cannot be closed until one mode is selected.
3. **Locked (DSA Practice only).** Windows shows one administrator prompt. The previously installed fixed PowerShell
   helper in `%ProgramFiles%\CodeLock` writes the marked hosts block; CodeLock verifies the helper
   installation, then verifies the block by re-reading the hosts file. Blacklisted desktop processes
   are terminated every 2.5 seconds. If the prompt is declined, the helper cannot be verified, or
   the write cannot be verified, the HOSTS FILE badge reports the observed state and, when no block
   exists, says **NOT BLOCKED**.
4. **The judge.** Your code runs in a fresh Python interpreter in a throw-away working directory.
   The parent process keeps every expected answer, sends one test at a time, and compares the
   result itself; the submission receives neither the expected output nor the hidden-test list.
   All tests must pass within 3 seconds.
5. **Reward.** On success Windows asks for approval once more to remove the block, the removal is
   verified, and the window stops being topmost for 15 minutes. A live countdown is shown.
6. **Re-lock.** When the timer hits zero, websites are blocked again (another approval prompt), the
   next challenge from the DSA track is loaded, and the editor resets.

Every graded submission stores the elapsed time and outcome. Progress is per student and per track,
so a later session resumes at the challenge you reached.

The GUI is a real kiosk-style window: it pins itself above other windows, traps the close button
(the title-bar X is greyed out with the Win32 system menu), and disables paste in the editor.

---

## Tech stack

| Layer | Technology |
| --- | --- |
| Language | Python 3.10+ (developed and self-tested on 3.14) |
| GUI | `tkinter` / `ttk` (kiosk window, built-in editor, judge console) |
| PC control | hosts-file I/O, `psutil`, `subprocess` / `taskkill` fallback, `ctypes` |
| Concurrency | `threading` watchdog + Tkinter-safe event queue, timer via `after()` |
| Accounts | Oracle Database 19c+ via `python-oracledb` + `codelock_api` PL/SQL package; SQLite fallback |
| Grading | trusted-parent subprocess protocol, generated hidden tests, hard timeout, Job Object / process-group cleanup |
| Exam documents | `pypdf` for PDFs; standard-library ZIP/XML for DOCX; text files |
| AI generation | Configurable Gemini, Ollama, or OpenAI-compatible chat endpoint via `urllib` |

---

## Requirements

- **PC:** Windows 10/11 (primary) or a Linux desktop.
- **Python 3.10+** with Tkinter. Windows installers include Tkinter; on Debian/Ubuntu use
  `sudo apt install python3-tk`.
- **pypdf** (installed from `requirements.txt`) for PDF text extraction. DOCX parsing uses the
  standard library and does not require `python-docx`. When CodeLock runs under a system Python
  that does not have pypdf, it automatically loads the copy installed in the project `.venv`; if
  neither location has it, PDF upload shows an actionable message while TXT and DOCX still work.
- **psutil** (optional). Install it with `pip install psutil` for the faster process sweep. If it
  is unavailable, CodeLock falls back to `tasklist` / `taskkill` on Windows and `pkill` on Linux;
  this is automatic and logged.
- **Oracle Database 19c+ (optional)** for a shared student database. Run `database/schema.sql`,
  install `oracledb` (already in `requirements.txt`) and set the `CODELOCK_ORACLE_*` variables. If
  Oracle is not configured the app uses a local SQLite database, so no external database is needed
  to run CodeLock.
- **Windows UAC approval** for hosts-file changes plus a one-time administrator installation of the
  fixed helper. CodeLock itself runs as a standard user; each block or unblock asks Windows for one
  administrator approval and runs the installed helper. The helper is never copied from the project
  folder at runtime and CodeLock never installs it automatically. If the installation is missing,
  modified, or world-writable, blocking is disabled; the badge reports the actually observed hosts
  state (usually **NOT BLOCKED**) and the log explains the verification failure.

> Windows note: if you use an MSYS2/MinGW build of Python, `psutil` may fail to build from source.
> Use the official python.org build, or let CodeLock use the native fallback (it is automatic and
> logged).

---

## Installation

Open a terminal in the project folder (the folder containing `main.py`).

```bash
python -m venv .venv

# Standard python.org Windows build:
.venv\Scripts\activate

# MSYS2 / MinGW Python (the layout used by this project's existing .venv):
#   cmd.exe:    .venv\bin\activate.bat
#   Git Bash:   source .venv/bin/activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

The launcher below handles both venv layouts automatically, so activation is optional when you use
`run_codelock.bat`.

### Quick start on Windows

Double-click **`run_codelock.bat`**, or run it from a terminal:

```bat
run_codelock.bat --dry-run
```

The launcher uses `.venv\Scripts\python.exe` or `.venv\bin\python.exe` when present, otherwise the
system `py -3` / `python`. It checks for Tkinter and prints a clear error if Python or Tkinter is
missing. Arguments are passed through to `main.py`.

Run an offline sanity check before enabling enforcement:

```bash
python main.py --self-test
```

You should see `SELF-TEST PASSED`. Then launch the kiosk:

```bash
python main.py
```

CodeLock does not run as administrator. If started manually as administrator/root, the launcher
refuses to open the GUI because submitted solutions must not inherit elevated privileges. Run from a
standard user account.

On Windows, install the fixed helper once from an **administrator** PowerShell before using website
blocking. CodeLock does not install it and never refreshes it from the project folder:

```powershell
# Run in an elevated PowerShell, from the repository root:
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\install_hosts_helper.ps1
```

The installer copies `codelock\hosts_helper.ps1` to `%ProgramFiles%\CodeLock\`, writes
`hosts_helper.manifest.json` with the SHA-256 and size of the installed file, and applies a
protected ACL (SYSTEM and Administrators full control; Users read/execute). It does not run the
helper or touch the hosts file. Every elevated launch re-verifies the installation directory ACL,
the manifest, and the helper hash; if any check fails, the operation is refused before UAC is
requested. Python is never started elevated from the project folder. The helper accepts only
**block**, **unblock**, **status**, **recover** and **repair**, and its websites, markers and
redirect address are compiled into it.

Without an installed, verified helper, CodeLock still runs and grades challenges, but the HOSTS FILE
badge shows **NOT BLOCKED** and the log explains why website blocking is unavailable.

On Linux, do not start CodeLock with `sudo`; the launcher refuses to open the GUI as root. Website
blocking may therefore be unavailable unless configured through a separate privileged service.

---

## Running CodeLock

```bat
run_codelock.bat              :: run without administrator/root privileges
run_codelock.bat --dry-run    :: safe demo: GUI works, nothing is blocked
```

The same commands work with `python main.py` when the virtual environment is active:

```bash
python main.py                # run without administrator/root privileges
python main.py --dry-run      # safe demo: GUI works, nothing is blocked
```

`--dry-run` is the recommended way to try the UI or record a demo video. It simulates enforcement
and lets you close the window normally: use the **EXIT DRY RUN** button or the title-bar X. The
mode chooser can also be closed with **Esc** (which exits the dry run) in this mode. In normal mode without the installed
helper, CodeLock still opens; the HOSTS FILE badge reports **NOT BLOCKED** and the log explains that
website blocking is unavailable. No UAC prompt is raised when the helper installation is missing or
fails verification.

On launch the student sign-in dialog opens first. Create an account (username, optional display
name, password) or sign in, and the mode chooser follows:

| Choice | What opens | PC lock |
| --- | --- | --- |
| **1. DSA Practice** | Engineering coding session (6 challenges, starting with the Addition warm-up) | Yes |
| **2. Exam Preparation** | Exam workspace: syllabus, notes, question bank, practice and mock tests | No |

Choosing DSA starts the Engineering track immediately; the other track definitions (Maths, School,
Biology) remain in `codelock/problems.py` but are not offered by the current chooser. The DSA
session starts with the **Addition** warm-up, so you can exercise the full lock → judge → reward
loop in seconds before the domain challenges begin. Opening Exam Preparation never applies the
hosts block or the process killer; closing its window exits CodeLock.

CodeLock runs fullscreen: the main window, the exam workspace, practice/mock runners and the result
window all cover the desktop, so no previously opened window stays visible behind them. The exam
workspace has an **EXIT CODELOCK** button, the runner has **LEAVE SESSION**, and the result window
has **CLOSE**, so every fullscreen window keeps a visible way out.

## AI Exam Preparation

After signing in, choose **2. EXAM PREPARATION** from the mode chooser. Create a subject workspace
with its course level, examination date, marks, and duration. Upload a PDF, Word (`.docx`), or TXT
syllabus, then review the extracted unit/topic tree. The file picker lists **PDF or Word documents**
first, followed by PDF-only, Word-only, text, and all-files filters. Add, rename, and remove units
or topics, save a draft, and approve it only after the structure looks right. Manual outlines are
also supported. Generated study material is unavailable until the syllabus is approved.

Legacy `.doc` files are not parsed: saving the document as `.docx` or PDF gives a clear message in
the workspace instead of a generic error. PDF text extraction is local. Image-only or scanned PDFs
are detected when no selectable text is available; OCR is not configured, so OCR the document
separately and upload a text-based copy.
DOCX extraction reads paragraph and table text. Extraction is bounded to 20 MiB per file, 500 PDF
pages, and 500,000 extracted characters.

Notes support very short, standard, and detailed styles. Generated notes cover every approved
syllabus unit and topic point-wise: each topic gets a short explanation followed by numbered
points drawn from the uploaded source, and the visible notes never show the source filename or
where the material was extracted from (provenance is kept only as internal metadata). Unsupported
topics are marked as not specified in the supplied sources. The question bank supports MCQ,
true/false, fill-in, one-word, short-answer, long-answer, practical, programming, and viva
questions. Questions are validated for type, difficulty, Bloom level, answer, explanation, marks,
source topic, and duplicates before saving. Generated text remains editable, and saved content is
scoped to the signed-in student. The notes and question-bank editors use a 14-point monospace font
so long study material stays readable.

The **Practice** tab builds a topic-wise test from the approved question bank. Choose one or more
topics, a difficulty and a question count. Objective answers (multiple choice, true/false, fill-in,
one-word) are checked immediately with the awarded marks, reference answer and explanation. Written
answers are stored and flagged for manual review.

The **Mock Exam** tab builds a configurable paper: topic filter, difficulty, question count,
duration in minutes, and an optional target marks value. The countdown starts when the session
opens, answers can be changed until submission, and the paper submits automatically when time runs
out. Each session snapshots its questions, so editing the question bank later cannot change a paper
that is in progress or already submitted.

Objective answers are scored automatically on submission: option letters or option text for MCQ,
common True/False spellings, case- and whitespace-insensitive fill-in answers with `|` or `;`
alternatives, and numeric matching. Short-answer, long-answer, practical, programming and viva
responses are never auto-marked; they stay at zero marks with `needs_review` status until a person
grades them.

The **Results** tab lists every session for the workspace with score, accuracy and review count.
Open a finished session for a per-topic breakdown (questions, correct, incorrect, needs review,
unanswered, marks, awarded, accuracy) and a full answer review with reference answers and
explanations. An in-progress session can be resumed from the same tab.

The **Analytics** tab summarizes submitted practice and mock sessions for the workspace. It reads
only sessions that were actually submitted; abandoned or in-progress sessions never affect the
figures. Choose **Last 7 Days**, **Last 30 Days**, or **All Time**; the filter applies to every card,
chart, table and recommendation on the tab.

- **Stat cards:** sessions, questions attempted, overall accuracy, marks scored against total, and
  answers waiting for review.
- **Topic chart and table:** accuracy, graded answers, a recent-accuracy value, marks, and a
  mastery indicator per topic.
- **Trend chart:** graded accuracy per submitted session in the selected range, with a written
  improving / declining / steady summary when enough sessions exist.
- **Question types and Bloom levels:** accuracy bars per objective question type and per Bloom
  level, with the hardest groups named only when they have enough graded answers.
- **Recommendations:** weak topics to practice next, each with the evidence behind it (graded
  answers, accuracy, recent drop) and a **PRACTICE THIS TOPIC** button that opens a 10-question
  practice session restricted to that topic.

Analytics are evidence-based; nothing is estimated from a handful of answers.

- Accuracy counts only auto-graded objective responses. Written answers awaiting review are
  excluded from both the numerator and the denominator, never counted as wrong.
- A topic needs at least **5** graded answers before it is classified as critical, weak, developing
  or strong. Below that it is **insufficient data**, and its accuracy is shown for information only
  (marked with `*` in the table).
- Topic status thresholds: critical below **45%**, weak below **60%**, developing below **75%**,
  strong at **75%** and above. A recent drop of **15** points or more against the preceding sessions
  is called out separately.
- "Recent" combines the latest session with preceding sessions, up to three, until at least **3**
  graded answers are included. This avoids calling a topic weak from a single answer.
- The overall accuracy card and the session-trend chart stay hidden until at least **5** graded
  answers exist. Trend classification needs at least two graded sessions and **5** graded answers,
  and uses a **5**-point change threshold.
- **Mastery:** *Not Started* with no attempts; *Needs Improvement* for a critical or weak topic, or
  evidence of a recent decline; *Mastered* at **8** or more graded answers with **80%** accuracy and
  no decline; *Learning* for everything else with enough evidence.
- Recommendations appear only for *Needs Improvement* topics with at least **5** graded answers.
  Topics with fewer answers are listed under evidence needed instead. With no submitted sessions in
  the range, the tab shows the topics as Not Started and states that no estimates or
  recommendations are available.

Analytics records are filtered by student and workspace in the database query, so one account can
never read another student's history, and a workspace shows only its own sessions.

Generation works without any API key. When no AI provider is configured, the built-in offline
generator extracts notes and questions directly from the uploaded source; an AI provider is optional
and is tried first when configured. API keys are read from environment variables and are not written
to the database. For example, local Ollama:

```powershell
$env:CODELOCK_AI_PROVIDER = "ollama"
$env:CODELOCK_AI_MODEL = "your-local-model"
# Optional; defaults to http://localhost:11434/api/chat
$env:CODELOCK_AI_ENDPOINT = "http://localhost:11434/api/chat"
python main.py
```

For Gemini, set `CODELOCK_AI_PROVIDER=gemini`, `CODELOCK_AI_MODEL`, and
`CODELOCK_AI_API_KEY`. For another compatible endpoint, set
`CODELOCK_AI_PROVIDER=openai-compatible`, `CODELOCK_AI_ENDPOINT`, `CODELOCK_AI_MODEL`, and
`CODELOCK_AI_API_KEY` when required. Remote providers receive relevant extracted source excerpts
for the selected topics; use Ollama when source material should stay on the local machine.

The offline generator is extractive rather than generative: notes quote and organize sentences from
the uploaded source, and questions are built from those sentences with validated answers and source
quotes. It does not invent facts, call the network, or require a model download. If a configured AI
provider fails, the status line reports the failure and the offline generator is used instead. If
the source itself is unsuitable, the error is shown and nothing is saved.

SQLite creates the exam tables automatically. For an existing Oracle schema, run
`database/migrations/001_exam_workspaces.sql` and then `database/migrations/002_exam_core.sql` once.
Fresh Oracle installations receive the same tables from `database/schema.sql`. Live Oracle execution
has not been verified in this environment.

Not implemented yet: previous-year question-paper analysis, personalized revision scheduling, and a
manual marking screen for written answers. Analytics covers topic weakness, mastery, trends, and
question-type/Bloom difficulty; the recommendations are informational and are not a scheduled study
plan.

---

## Using the kiosk

On launch the sign-in dialog and then the mode chooser take over the screen. You must sign in and
choose Exam Preparation or DSA Practice before the main window is usable; closing the chooser is
blocked in real mode (use the admin exit if you need to abort). Exam Preparation leaves the PC
unlocked and exits CodeLock when its window closes. Enforcement starts only when DSA Practice is
chosen, so no website or app is touched while you are still signing in or deciding.

The student badge shows who is signed in. Submitting a challenge stores the elapsed time and
outcome, and the console reports when progress is saved. The next launch for that account resumes
at its saved challenge for the selected track.

While locked:

- The window stays on top and re-asserts itself every 1.5 seconds.
- Closing (X, Alt+F4) is blocked and shows a warning.
- Ctrl+V, Shift+Insert, middle-click paste, right-click and the virtual paste event are all blocked.
- **RUN SAMPLES** checks only the visible examples and does **not** unlock anything.
- **SUBMIT & UNLOCK PC** runs all hidden tests. A pass is not enough on its own: CodeLock asks for
  explicit confirmation before restoring website access.

On confirmation, the PC unlocks for **15 minutes**. When the timer expires websites are blocked
again, the next challenge from the same track loads, and the editor resets to that challenge's
starter code. Declining the confirmation leaves the PC locked and records the passing attempt.

### The challenges

| Track | Challenge | Function | Focus |
| --- | --- | --- | --- |
| All | Warm-up: Addition | `add(a, b)` | smoke-test the full reward loop |
| Engineering | Two Sum (distinct indices) | `two_sum(nums, target)` | hashing / sets |
| Engineering | Balanced Brackets | `is_valid(s)` | stacks |
| Engineering | Maximum Subarray | `max_subarray(nums)` | Kadane's algorithm |
| Engineering | Binary Search | `binary_search(nums, target)` | divide and conquer |
| Engineering | Matrix Transpose | `transpose(matrix)` | nested lists / `zip` |
| Maths | Greatest Common Divisor | `gcd(a, b)` | Euclid's algorithm |
| Maths | Prime Check | `is_prime(n)` | trial division up to √n |
| Maths | Fibonacci Number | `fibonacci(n)` | iteration vs recursion |
| School | Digit Sum | `digit_sum(n)` | string/number conversion |
| School | Vowel Count | `count_vowels(text)` | string traversal |
| School | Palindrome Check | `is_palindrome(text)` | normalizing text |
| Biology | DNA Complement | `dna_complement(seq)` | base pairing |
| Biology | GC Content | `gc_count(seq)` | sequence statistics |
| Biology | Hamming Distance | `hamming_distance(first, second)` | sequence comparison |

Each submission is graded against the visible examples plus 24-38 generated hidden cases
(30 for the addition warm-up), randomized with fixed seeds and checked against reference answers.
Hardcoding sample outputs cannot pass.

---

## Command-line reference

| Command | What it does |
| --- | --- |
| `run_codelock.bat [args]` | Windows launcher; selects the project venv or system Python and passes arguments to `main.py`. |
| `python main.py` | Start the kiosk as a standard user (website blocking needs the separately installed helper). |
| `python main.py --dry-run` | Start the GUI without enforcing anything. Closable via **EXIT DRY RUN** or X. |
| `python main.py --restore` | Remove the CodeLock block from the hosts file, then exit. |
| `python main.py --self-test` | Run offline checks (hosts round-trip, judge, problem bank, exam sessions, analytics) and exit. |
| `python main.py --self-test-ui` | Run the Analytics dashboard GUI smoke test in a temporary database and exit. |
| `python main.py --no-elevate` | Deprecated compatibility flag; CodeLock never requests elevation. |
| `python main.py --version` | Print the version. |

Use `--restore` after a crash, after force-killing the app, or whenever you want to be sure the
hosts file is back to normal. On Windows it asks for one UAC approval, runs the installed helper and
then verifies that the managed block is gone. Damaged or incomplete markers are removed by the
`recover` operation rather than refusing outright. If Windows approval is declined, the observed
state is reported (a previous complete block remains **HOSTS FILE BLOCKED**) and the command exits
with a failure message and, where possible, a recovery file. If the helper installation cannot be
verified, `--restore` refuses to elevate and prints the verification failure. On Linux it needs root
rights.

### Emergency exit

While locked, use the **EMERGENCY EXIT** button or press **Ctrl + Alt + Shift + Q**. When
`CODELOCK_ADMIN_PASSWORD` is set, the exit requires that password. Without one, CodeLock asks for
confirmation before restoring website access and quitting. Set a unique password before a real
session if you want that additional password gate:

```bash
# Windows PowerShell
$env:CODELOCK_ADMIN_PASSWORD = "something-only-you-know"
python main.py
```

The emergency exit is a safety hatch, not a feature for the student to use during a session.

---

## Configuration

Edit `codelock/config.py` (no restart needed beyond relaunching the app):

| Constant | Default | Purpose |
| --- | --- | --- |
| `BLOCKED_WEBSITES` | social media + streaming domains | Entries written to the hosts block. The compiled list in `codelock/hosts_helper.ps1` must match; the self-test enforces this. |
| `BLOCKED_PC_PROCESSES` | Discord, Steam, Spotify, WhatsApp, Telegram, Epic | Executables terminated by the watchdog. |
| `REWARD_SECONDS` | `15 * 60` | Length of the reward after a passing submission. |
| `JUDGE_TIMEOUT_SECONDS` | `3.0` | Hard limit for one judge run. |
| `JUDGE_CASE_TIMEOUT_SECONDS` | `2.0` | Maximum wait for one test case, capped by the overall limit. |
| `WATCHDOG_INTERVAL_SECONDS` | `2.5` | Process sweep / hosts re-check interval. |
| `HOSTS_RETRY_SECONDS` | `60` | How often the hosts block is re-verified. |
| `ADMIN_PASSWORD` | empty | Emergency exit password; no public default is provided. |

Environment variables:

| Variable | Effect |
| --- | --- |
| `CODELOCK_ADMIN_PASSWORD` | Overrides the emergency-exit password. |
| `CODELOCK_ORACLE_USER` | Oracle schema user for the PL/SQL backend. |
| `CODELOCK_ORACLE_PASSWORD` | Oracle password. |
| `CODELOCK_ORACLE_DSN` | Oracle DSN. Setting it enables the Oracle backend; unset means SQLite. |
| `CODELOCK_DB_PATH` | SQLite file path (default `data/codelock.db`). |
| `CODELOCK_DATA_DIR` | Folder for the default SQLite file. |

The managed hosts block is delimited, so CodeLock never rewrites unrelated lines:

```
# >>> CodeLock block (managed automatically) >>>
0.0.0.0 instagram.com
...
# <<< CodeLock block (managed automatically) <<<
```

The first modification saves a backup as `hosts.codelock.bak` next to the hosts file. On Windows the
block is written by the separately installed and verified
`%ProgramFiles%\CodeLock\hosts_helper.ps1`. The helper writes to a same-directory temporary file,
flushes it to disk, replaces the hosts file atomically with `File.Replace` (never a copy fallback),
and re-reads the result before reporting success. It keeps the file's existing encoding (UTF-8 with
or without BOM, UTF-16, or ANSI) and newline style. Stale `hosts.codelock-*.tmp` files older than one
hour are removed at the start of an operation. After a successful block or unblock the helper flushes
the DNS cache with `ipconfig /flushdns`; a flush failure is reported separately and does not change
the verified hosts-file result.

---

## Student accounts and progress

Each launch asks for a student account. CodeLock stores:

| Table | Contents |
| --- | --- |
| `students` | username, display name, PBKDF2-SHA256 password hash, random salt, created/last login |
| `attempts` | one row per graded submission: track, challenge, elapsed seconds, pass/fail, tests passed/total, timestamp |
| `progress` | one row per student and track: current challenge index, solved count, attempts, total seconds, best seconds |

Passwords are hashed in the app with PBKDF2-SHA256 (200,000 iterations) before they reach the
database. No plaintext password is stored, and there is no password-recovery flow built in; create
a new account or update the row manually if a password is lost.

### Oracle / PL-SQL backend

1. Install the driver and run the schema once in the app user's schema:

   ```bash
   pip install -r requirements.txt
   sqlplus codelock/your_password@//localhost:1521/FREEPDB1 @database/schema.sql
   ```

2. Point CodeLock at the database and start it:

   ```powershell
   # Windows PowerShell
   $env:CODELOCK_ORACLE_USER = "codelock"
   $env:CODELOCK_ORACLE_PASSWORD = "your_password"
   $env:CODELOCK_ORACLE_DSN = "localhost:1521/FREEPDB1"
   python main.py
   ```

   ```bash
   # Linux / macOS
   export CODELOCK_ORACLE_USER=codelock
   export CODELOCK_ORACLE_PASSWORD=your_password
   export CODELOCK_ORACLE_DSN=localhost:1521/FREEPDB1
   python main.py
   ```

`database/schema.sql` creates the student tables (`students`, `progress`, `attempts`), an index on
attempts, a `student_overview` view for reporting, and the `codelock_api` PL/SQL package:
`register_student`, `get_credentials`, `touch_login`, `record_attempt` and `get_progress`. The app
calls that package for every account and progress operation, including a `MERGE` that accumulates
attempts, total time, best time and the next challenge index.

The exam workspace tables are also part of the schema:

| Table | Contents |
| --- | --- |
| `exam_workspaces` | subject metadata, extracted syllabus text, approved topic tree, revision notes, generated questions and the question-bank fingerprint |
| `exam_questions` | normalized, student-owned question bank rows with unit, topic, type, difficulty, Bloom level, marks, options, answer and source references |
| `exam_sessions` | practice/mock session blueprint, status, total marks, score, review count, time limit and elapsed time |
| `exam_responses` | one row per session question: snapshot, student answer, correctness, awarded marks and review status |

The normalized rows are derived from the approved question JSON by `sync_question_bank`; the JSON
stays the editable source document. Sessions keep their own question snapshots so later edits or
syllabus changes cannot alter historical papers. Saving an unchanged syllabus draft only refreshes
the timestamp; changing the syllabus or question bank revokes approval and empties the active bank.

### Local SQLite fallback

When `CODELOCK_ORACLE_DSN` is unset, or `oracledb` is missing, or the connection fails, CodeLock
logs a warning and uses `data/codelock.db`. The sign-in dialog shows which store is active. The
SQLite database is created automatically with the same tables and columns; delete the file to reset
all local accounts. It is gitignored. Override its location with `CODELOCK_DB_PATH`, or the whole
data folder with `CODELOCK_DATA_DIR`.

The SQLite file is per machine. Use the Oracle backend when several computers must share accounts
and progress.

---

## The coding judge

- **Process separation:** the submission is sent over stdin to `python -I -c <harness>` running in
  a temporary directory. This does not prevent access to files or network available to the user.
- **Trusted-parent grading:** the GUI process owns every expected answer and both visible and
  hidden test metadata. The worker receives only its code, the function name and one case's
  arguments at a time. It sends back a type-tagged value; the parent reconstructs the exact
  built-in type and performs the comparison itself. The worker never receives an expected value,
  the test list, a hidden/sample flag, or a verdict field.
- **Strict protocol:** result frames use a per-session prefix and a strict sequence. Missing,
  duplicate, extra, malformed, out-of-order or oversized frames are rejected. Forged `ok`/`passed`
  fields, clearing a harness list, rewriting stdout and calling `os._exit()` cannot produce a pass;
  every one of those attacks is a regression test.
- **Timeout:** 3 seconds overall by default and 2 seconds per case, whichever is lower. On timeout
  or protocol failure the process tree is terminated; the UI reports a time-limit failure.
- **Cleanup:** on Windows each worker is assigned to a Job Object with `KILL_ON_JOB_CLOSE`, a CPU
  limit and a 256 MiB process-memory limit. On POSIX the worker gets its own process group and
  CPU/address-space/file-size/open-file/core limits. `Judge.shutdown()` terminates active workers.
- **Environment:** the judge subprocess receives a small allowlist of runtime variables, so
  database and emergency-password environment variables are not inherited.
- **Privilege check:** the launcher refuses to open the GUI as administrator/root. Start the app
  from a standard user account. `--restore` can still be run elevated for hosts-file cleanup.
- **Malformed code:** syntax errors, import-time exceptions, `sys.exit()`, missing functions, and
  unsupported return types are reported as failures instead of crashing the judge.
- **Strict results:** the returned value must equal the expected value **and** have the same type
  (`1` does not count as `True`). Non-primitive objects are rejected rather than compared.
- **Output:** anything the solution prints is shown in the judge console (truncated).
- **Hidden tests:** generated per submission with seeded `random` plus fixed edge cases
  (empty input, duplicates, negatives). Expected answers come from brute-force reference logic.

**What this does not do:** the worker is not a security sandbox. It runs as the same user, can read
its own arguments when the function is called, and can attempt to read the parent process's memory
or automate GUI input. No restricted-token, AppContainer, Windows Sandbox or VM isolation is
implemented. Because of that, a local judge pass alone never unlocks the PC: the student must
confirm the unlock, and that confirmation is a user-interaction safeguard, not a security boundary.
Do not run hostile code with CodeLock; use a dedicated VM or OS sandbox.

---

## Project structure

```
main.py                  entry point: CLI, --restore, --self-test (never auto-elevates)
codelock/
  __init__.py            version
  ai.py                  configurable provider transport; no stored keys
  config.py              blocked sites/apps, timings, database settings, password
  db.py                  accounts, progress, exam workspaces, question bank and sessions (Oracle + SQLite)
  exam.py                bounded PDF/DOCX/TXT extraction and topic validation
  exam_engine.py         question selection, objective scoring and session submission
  exam_analytics.py       topic accuracy, mastery, trends and evidence-based recommendations
  exam_charts.py         Tk Canvas topic bars and session-trend chart
  exam_ui.py             subject workspaces, editable syllabus/notes/questions, practice/mock/results/analytics tabs
  exam_runner.py         practice and mock exam windows, countdown and result review
  study_generation.py    source-grounded notes and validated question banks
  problems.py            track registry + challenge bank + hidden-test generators
  judge.py               subprocess harness, timeout, result formatting
  hosts_helper.ps1       fixed elevated helper: block / unblock / status / recover / repair
  hosts_elevation.py     manifest + ACL verification, one-shot UAC launcher, observed state, recovery
  windows_acl.py         read-only Windows DACL inspection for the installed helper
  pc_blocker.py          direct hosts blocker (non-Windows/elevated use), process killer
  gui.py                 kiosk window, sign-in, study mode chooser, watchdog, reward timer
  selftest.py            offline verification used by --self-test
  ui_smoke.py            temporary-database GUI smoke test used by --self-test-ui
tools/
  install_hosts_helper.ps1  manual administrator installer and manifest writer
database/
  schema.sql             Oracle student/exam tables, view and codelock_api PL/SQL package
  migrations/            001 exam workspaces; 002 normalized question bank and sessions
data/                    local SQLite store (created at runtime, gitignored)
requirements.txt
.gitignore
```

---

## Safety and crash recovery

CodeLock changes one thing outside its own folder: the **hosts file**. On Windows an administrator
must separately install the fixed helper under `%ProgramFiles%\CodeLock`; CodeLock never installs or
refreshes it and never executes anything elevated from the project folder.

- **Status vocabulary:** the HOSTS FILE badge reports the state read from disk after the operation:
  **BLOCKED** (complete managed block), **PARTIAL** (some managed entries missing), **DAMAGED**
  (incomplete or mismatched markers, or managed entries outside the block), **NOT BLOCKED**, or
  **STATUS UNKNOWN** (the file could not be read). A failed helper never overwrites an observed
  active block with NOT BLOCKED.
- **Separate network note:** `HOSTS FILE BLOCKED` only means the hosts file contains the verified
  block. It does not claim that websites are unreachable; real reachability is not tested.
- **Graceful exit:** the hosts block is removed on exit (normal close during a reward, or the admin
  emergency exit), and the removal is verified by re-reading the file. DNS is flushed after a
  successful change; a flush failure is reported and does not masquerade as a file failure.
- **Verification failure:** if the block or removal cannot be verified, the observed state is shown,
  the app explains what happened, and it writes `%LOCALAPPDATA%\CodeLock\RECOVERY_REQUIRED.txt` with
  the exact `--restore` command and the marker lines to remove manually. If that file cannot be
  created, the UI says so and prints the command instead.
- **Damaged markers:** **REPAIR HOSTS** runs the helper's `repair` operation, which removes damaged
  CodeLock entries and writes a fresh verified block in one elevated run. `--restore` uses `recover`,
  which removes only exact CodeLock markers and exact managed `0.0.0.0 <site>` lines, saves a
  forensic copy of the damaged file, and verifies the result.
- **Crash / force-kill:** the hosts block may remain.
- **Next launch:** CodeLock only *detects* an existing marked or damaged block and logs it. It does
  not remove the block at startup, because the GUI is unprivileged. Selecting a track reuses/replaces
  the block for the new session; unlocking or exiting removes it.
- **Manual recovery:** run `python main.py --restore` from the project folder. On Windows this asks
  for one UAC approval and verifies the result; from an administrator terminal it needs no second
  approval. If the helper installation is not authentic, it refuses to elevate and prints the reason.
  On Linux run it as root.
- **No silent elevation:** the watchdog never opens a UAC prompt on its own. If a block fails, the
  UI shows **RETRY BLOCK**; only that button, the next lock/unlock, or `--restore` starts a new
  elevated operation.
- **Interrupted operations:** the helper never copies over the hosts file. It writes a temporary file
  in the same directory, flushes it, replaces the target atomically, and verifies the bytes by
  re-reading. A failed or interrupted replace leaves the previous hosts file in place. Stale
  `hosts.codelock-*.tmp` files older than one hour are cleaned up safely at the start of a later
  operation. Client timeouts terminate the elevated helper and wait for it; if termination cannot be
  confirmed, the result requires recovery instead of claiming success.

The original hosts file is backed up once as `hosts.codelock.bak` the first time CodeLock modifies
it, and an existing backup is never overwritten. A pre-existing zero-byte or incomplete
`hosts.codelock.bak` is left untouched; verify or replace it yourself before relying on it for
manual restoration.

> **Upgrading from the old phone-locking build:** this version no longer manages Android devices.
> If you previously suspended apps with that build, restore them manually while the phone is
> connected: `adb shell pm unsuspend --user 0 <package>` (fallback:
> `adb shell pm enable --user 0 <package>`).

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| HOSTS FILE shows `NOT BLOCKED` | Windows approval was declined, the helper failed, the helper installation is missing or failed verification, or the hosts file is read-only. Click **RETRY BLOCK** and approve the prompt, or run `python main.py --restore` and retry. The console line names the exact reason. |
| HOSTS FILE shows `DAMAGED` or `PARTIAL` | Click **REPAIR HOSTS** to remove damaged CodeLock entries and write a fresh verified block in one approval, or run `python main.py --restore` to remove the entries without re-blocking. |
| `Refused to run the elevated helper` | The installed helper does not match its manifest, or the installation directory ACL is writable by a standard user. Re-run `tools/install_hosts_helper.ps1` from an elevated PowerShell on a trusted copy of the project. |
| UAC prompt appears every lock/unlock | Expected: CodeLock never keeps an elevated process running. Each hosts change is one approved helper operation. |
| `--restore` says the block is still present | Windows approval was declined, the helper installation could not be verified, or the hosts file could not be verified. Follow the path printed by `--restore` and in `%LOCALAPPDATA%\CodeLock\RECOVERY_REQUIRED.txt`, or remove the marker lines manually as Administrator. |
| Websites still open | Chrome/Edge/Firefox may use DNS-over-HTTPS, which bypasses the hosts file. Turn DoH off, or use an extension/firewall rule as a second layer. |
| A blocked app reopens | The watchdog runs every 2.5 seconds; a just-opened app may appear briefly. Force-killing CodeLock stops the watchdog. |
| `psutil` will not install | It is optional. Without psutil the app uses `tasklist`/`taskkill` on Windows and `pkill` on Linux; this is automatic and logged. |
| `run_codelock.bat` says Python was not found | Install Python 3.10+ from python.org with "Add python.exe to PATH", or create `.venv` as shown in Installation. The launcher checks `.venv\Scripts`, `.venv\bin`, `py -3`, then `python`. |
| Activation path `.venv\Scripts\activate` does not exist | This project's existing venv was created by MSYS2 Python and uses `.venv\bin`. Use `.venv\bin\activate.bat` in cmd, `source .venv/bin/activate` in Git Bash, or just use `run_codelock.bat`. |
| PDF upload says PDF support is unavailable | pypdf was not found in either the running interpreter or the project `.venv`. Install it with `python -m pip install pypdf`, or start the app with `run_codelock.bat`, which uses the venv. TXT and DOCX uploads do not need it. |
| Launcher prints an error but the window never opens | Run `run_codelock.bat --self-test` and `run_codelock.bat --self-test-ui`; the failure text identifies the missing module or Tk problem. |
| Cannot close the window | That is the kiosk. Solve the challenge, or use Ctrl+Alt+Shift+Q with the admin password. |
| Buttons clipped on a small screen | The window needs at least 820x620; the editor shrinks first. |
| Reward timer shows `--:--` | The PC is locked. Solve a challenge to start a reward. |
| Sign-in dialog says SQLite even though Oracle is configured | Install `oracledb`, check the three `CODELOCK_ORACLE_*` variables and the DSN; CodeLock falls back and logs the reason. |
| Forgot a student password | There is no recovery flow. Create a new account, or delete/update the student row in Oracle or `data/codelock.db`. |
| Accounts disappeared | The local SQLite store was deleted or a different `CODELOCK_DB_PATH` is in use. Use Oracle if progress must be shared. |

---

## Limitations and responsible use

CodeLock is a **commitment device**, not a prison or a security product:

- It stops impulsive tab-switching and app-opening, not a determined user. Anyone with admin
  rights can edit the hosts file or uninstall Python.
- The helper is installed once by an administrator from `tools/install_hosts_helper.ps1`, and every
  elevated launch re-verifies the installed helper's SHA-256 against the protected manifest plus the
  installation ACL. Runtime code never reads or executes the project copy. This protects against a
  standard user modifying the project or the installed files; it does not protect against an
  administrator, who can replace the helper, its manifest, and the ACL. The installer is not code-
  signed; verify the project copy you install. The DACL check accepts the default
  `%ProgramFiles%` protections and fails closed on unknown writable trustees or reparse points.
- UAC approval is required for each block and unblock. CodeLock deliberately does not keep a
  long-running elevated service or a scheduled task.
- Force-killing CodeLock stops the process watchdog, so desktop apps can be relaunched. The hosts
  block remains until you run `--restore`.
- The window is topmost but not a full-screen OS kiosk. Alt+Tab still works. For stricter setups,
  combine it with OS-level account controls or a full-screen kiosk session.
- Hosts blocking does not stop DNS-over-HTTPS, VPNs, or direct IP access.
- Without Oracle, accounts and progress live in a local SQLite file; anyone with file access can
  read or alter it. The Oracle backend centralizes accounts but is only as secure as the database
  account and network you give it.
- Password recovery is not implemented. A lost password means creating a new account or editing the
  `students` row directly.
- AI notes and question generation require a configured provider (`CODELOCK_AI_*`). No live AI
  provider was used during the final submission check; the unavailable-provider path is tested and
  shows a clear error. Practice and mock sessions can still be demonstrated by saving a question
  bank manually in the Question Bank tab.
- The Oracle backend has not been executed against a live Oracle instance in development. The final
  check used the local SQLite store and its fallback path.
- Real UAC approval, `%ProgramFiles%` helper installation, and real hosts-file writes were not
  performed during the final check. The demo uses `--dry-run`, which never touches the hosts file.
- Analytics accuracy uses auto-graded objective answers only. Written answers awaiting review are
  excluded until a manual marking screen exists, so accuracy can look higher than a fully marked
  paper would show.
- Date-range filtering compares stored timestamps as UTC. SQLite stores UTC, but an Oracle
  `SYSTIMESTAMP` written in local time can shift sessions across a 7- or 30-day boundary; the
  difference is at most the server's UTC offset.
- Only use this on **your own PC** and with accounts you are allowed to collect.

---

## Verification

`python main.py --self-test` runs offline checks:

- hosts: block install, idempotence, preserved entries, single marker block, all sites present,
  unblock restores the original file, unblock idempotence;
- hosts helper (temporary files only): PowerShell block/status/unblock/recover/repair round trips,
  repeated block/unblock calls, cp1252 + CRLF preservation, malformed-marker refusal, forced write
  failure with the original left intact, post-write verification failure reporting the observed
  block, read-only hosts file, UAC cancellation (including when a block already exists), helper exit
  failure, "success" without a state change, operation allowlist, compiled site/config equality,
  atomic `File.Replace` with no copy fallback, stale temporary-file cleanup, and the helper's refusal
  to touch the real system hosts file;
- helper authenticity: a valid manifest verifies, tampering with the project copy has no effect,
  modifying the installed helper invalidates the hash, and product/algorithm/hash/malformed/missing
  manifests are rejected; a writable installation ACL, a user-writable temporary directory and a
  non-Program-Files path are rejected in production mode; the manual installer writes the protected
  manifest;
- hosts status and recovery: PARTIAL is not reported as BLOCKED, damaged markers are classified
  DAMAGED, recover removes exact markers and stray managed lines while preserving unrelated entries
  and a forensic copy, repair rewrites and verifies a block, DNS flush failures are reported while
  skipped flushes are not, and an unreconciled timeout requires recovery;
- GUI checks confirm a failed or cancelled block never shows BLOCKED, a failed helper never hides an
  observed active block, damaged state offers **REPAIR HOSTS**, and the watchdog's retry is
  read-only;
- problems: each of the 15 challenges has visible examples, at least 20 hidden tests, and
  `two_sum` hidden tests mix `True` and `False`;
- tracks: unique keys, every challenge key resolves, no track repeats a challenge, every problem is
  reachable from at least one track, and each track offers at least 3 challenges;
- database: account creation, username normalization, duplicate rejection, wrong-password
  rejection, login, per-track progress, attempt/total-time/best-time accumulation, hashed-only
-  password storage, workspace ownership, syllabus approval gating, content persistence, and
  persistence across a reopen;
- exam preparation: TXT/DOCX extraction, PDF extraction when pypdf is installed, topic parsing and
  validation, stub-provider notes/question generation, explanatory point-wise notes with hidden
  source references, unsupported-source marking, duplicate-question rejection, and
  structured-content persistence;
- exam data safety: an unchanged syllabus draft preserves approval, notes and questions, while a
  changed syllabus revokes approval and empties the active question bank;
- exam bank and scoring: approved questions sync into normalized rows without duplicates, MCQ
  letters and option text score correctly, fill-in alternatives and one-word answers normalize,
  written answers stay in review, and blank answers remain unanswered;
- practice and mock sessions: question snapshots, immediate practice feedback, incorrect-answer
  scoring, cross-student isolation, session abandonment, duration/target-marks blueprints, mock
  auto-grading, history, per-topic accuracy, and SQLite/Oracle timestamp handling;
- analytics: submitted-session filtering, cross-student and cross-workspace isolation, topic
  accuracy/attempts/marks/incorrect counts, mastery states, recent-decline detection, evidence-based
  recommendations, hardest question type and Bloom level, 7-day/30-day/all-time filtering, session
  trends, empty-history behaviour, snapshot persistence, and migration/schema column checks;
- judge: all 15 reference solutions pass; wrong answers, missing functions, syntax errors,
  import-time crashes and infinite loops are rejected correctly;
- judge forgery: frame reading, list clearing, forged frames, legacy verdict output, `os._exit`,
  unsupported return types and wrong primitive types cannot force a pass; the worker payload
  contains no test data; the Windows Job Object exists and spawned descendants are terminated;
  `Judge.shutdown()` stops an active worker;
- GUI unlock: a judge pass requires explicit confirmation and declining keeps the PC locked;
- process blocklist normalization.

The suite runs 237 checks. When the running interpreter has no `pypdf` but the project `.venv`
does, the PDF checks use the venv copy; on a machine with neither, the PDF path instead reports an
actionable missing-dependency message. Verification on
2026-11-02: `py_compile` passed for all Python modules; both PowerShell scripts parsed cleanly;
`--self-test` 234/234 with system Python and 235/235 through the launcher/venv; `--self-test-ui`
13/13; a live GUI run against the real student database registered a new student, uploaded and
approved a syllabus, generated five grounded notes and a validated question bank offline, and
completed MCQ, written and mock sessions (34/34 live checks, hosts file hash unchanged); the real
`main.py --dry-run` entry point opened, showed SIMULATED hosts/process badges, and exited 0 when its
window was closed.

`python main.py --self-test-ui` runs 18 additional Tk smoke checks in a temporary database: the
Analytics tab and all three range filters exist, empty history shows Not Started topics with no
estimates or recommendations, a real submitted practice populates the cards/chart/mastery, a weak
topic exposes **PRACTICE THIS TOPIC**, each range includes the submitted session, that button opens
a practice runner containing only the selected topic, and abandoning it does not change submitted
statistics. It also checks that the workspace, runner and result windows are fullscreen with a
visible exit/leave/close control, that the syllabus picker lists PDF and Word documents first, and
that the notes and question-bank editors use a 14-point font.

The GUI was exercised in `--dry-run`: creating an account opens the mode chooser, choosing DSA
Practice loads the Engineering warm-up and locks, paste is blocked, addition passes, the attempt and
completion time are written to the database, the reward timer counts down, the window un-pins,
auto-relocks at zero, rotates to the next challenge, and a failed attempt is logged without advancing
progress. Relaunching and signing in as the same student resumes at the saved challenge. The **EXIT
DRY RUN** button and **Esc** end a test run (the fullscreen window hides the title bar). The same run
also opened Exam Preparation from the chooser (with no lock applied), created a workspace, submitted
a practice session, and confirmed the analytics cards, mastery and topic-practice action; closing
the exam window ended the application. Real-mode gating was verified with fake hosts/process
backends: nothing is enforced while the dialogs are open, enforcement starts after DSA selection,
and shutdown restores the hosts file and stops the watchdog. The Win32 close-item graying was
verified at the API level.

The exam workspace was exercised through Tk in a temporary database: the seven tabs build (including
Analytics), topic lists populate from the approved syllabus, a practice session opens and scores
answers with immediate feedback, submission opens the result window, a timed mock session starts its
countdown, the results history refreshes, analytics renders real submitted data in every range, and
shutdown closes all child windows. The Oracle backend was verified through the fallback path and
schema inspection, including the analytics query's CLOB handling; it has not been executed against a
live Oracle instance in development, including the exam CLOB columns and analytics.

What was **not** exercised in the development environment: approving a real UAC prompt, installing
the helper into `%ProgramFiles%`, changing Windows permissions, writing or restoring the real system
hosts file, and killing real desktop apps. The PowerShell helper was executed against temporary
hosts files only; cancellation, timeout, ACL and manifest failures were simulated at the client or
test-fixture boundary. The real hosts file was hash-checked before and after and was not modified.
Verify the real paths once on your own machine with `--dry-run` first, then run the elevated
installer on a trusted copy, then a short real session with `--restore` ready. Real Windows
enforcement is not certified by the offline suite.

Run both commands from the project directory before making changes to system settings:

```bash
python main.py --self-test
python main.py --self-test-ui
```

These checks use temporary databases and do not modify the system hosts file. They cover the
offline application logic and Tk workflows; they do not certify real UAC prompts, helper
installation, hosts-file enforcement, or process blocking. Use `python main.py --dry-run` to
exercise the application without enabling enforcement.
