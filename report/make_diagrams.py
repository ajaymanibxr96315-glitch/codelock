"""Generate the diagram figures used by the CodeLock project report."""

from __future__ import annotations

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent / "assets"
OUT.mkdir(parents=True, exist_ok=True)

FONT = "Segoe UI, Arial, sans-serif"
MONO = "Consolas, monospace"


def text(x: float, y: float, value: str, cls: str = "t") -> str:
    return f'<text x="{x}" y="{y}" class="{cls}">{escape(value)}</text>'


def box(
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    lines: list[str],
    cls: str = "box",
    title_cls: str = "bt",
    line_cls: str = "bs",
    line_gap: float = 20,
) -> str:
    parts = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" class="{cls}"/>']
    parts.append(text(x + 15, y + 28, title, title_cls))
    ty = y + 28 + line_gap + 5
    for line in lines:
        parts.append(text(x + 15, ty, line, line_cls))
        ty += line_gap
    return "\n".join(parts)


def arrow(
    points: list[tuple[float, float]],
    cls: str = "arrow",
    label: str | None = None,
    label_at: tuple[float, float] | None = None,
) -> str:
    d = " ".join(("M" if i == 0 else "L") + f"{x},{y}" for i, (x, y) in enumerate(points))
    out = f'<path d="{d}" class="{cls}"/>'
    if label and label_at:
        out += f'<text x="{label_at[0]}" y="{label_at[1]}" class="edge">{escape(label)}</text>'
    return out


HEAD = """<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<defs>
  <marker id="head" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">
    <path d="M0,0 L10,4 L0,8 z" fill="#475569"/>
  </marker>
  <marker id="headred" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">
    <path d="M0,0 L10,4 L0,8 z" fill="#b91c1c"/>
  </marker>
  <style>
    .t {{ font: 13px {font}; fill: #1f2937; }}
    .bt {{ font: 700 15px {font}; fill: #0f172a; }}
    .bs {{ font: 12.5px {font}; fill: #334155; }}
    .layer {{ font: 700 11px {font}; fill: #64748b; letter-spacing: 1.6px; }}
    .edge {{ font: 600 11px {font}; fill: #475569; paint-order: stroke; stroke: #ffffff; stroke-width: 5px; }}
    .box {{ fill: #ffffff; stroke: #475569; stroke-width: 1.6; }}
    .gui {{ fill: #eff6ff; stroke: #1d4ed8; stroke-width: 1.7; }}
    .svc {{ fill: #f8fafc; stroke: #334155; stroke-width: 1.6; }}
    .exam {{ fill: #ecfdf5; stroke: #047857; stroke-width: 1.6; }}
    .lock {{ fill: #fef2f2; stroke: #b91c1c; stroke-width: 1.6; }}
    .data {{ fill: #f0fdf4; stroke: #15803d; stroke-width: 1.6; }}
    .ai {{ fill: #f5f3ff; stroke: #6d28d9; stroke-width: 1.6; stroke-dasharray: 6 4; }}
    .note {{ font: 11.5px {font}; fill: #64748b; }}
    .arrow {{ fill: none; stroke: #475569; stroke-width: 1.9; marker-end: url(#head); }}
    .dash {{ fill: none; stroke: #6d28d9; stroke-width: 1.8; stroke-dasharray: 6 4; marker-end: url(#head); }}
    .arrow-red {{ fill: none; stroke: #b91c1c; stroke-width: 1.9; marker-end: url(#headred); }}
  </style>
</defs>
<rect width="{w}" height="{h}" fill="#ffffff"/>
"""


def write(name: str, svg: str) -> None:
    (OUT / name).write_text(svg, encoding="utf-8")
    print(name, "written")


# ------------------------------------------------------------------ architecture
w, h = 1200, 800
svg = HEAD.format(w=w, h=h, font=FONT)
svg += text(40, 30, "PRESENTATION LAYER", "layer")
svg += text(40, 236, "APPLICATION SERVICES", "layer")
svg += text(40, 436, "OPTIONAL INTEGRATION", "layer")
svg += text(40, 566, "OPERATING SYSTEM AND DATA", "layer")

svg += box(
    40, 44, 1120, 158, "Tkinter kiosk GUI",
    ["main.py  ·  codelock/gui.py  ·  always-on-top window · anti-paste editor · judge console"],
    cls="gui", line_gap=21,
)
sub = [
    (60, 100, 340, "Sign-in and mode chooser", "student account · Exam / DSA question"),
    (420, 100, 340, "DSA practice", "engineering track · editor · judge console"),
    (780, 100, 360, "Exam Preparation workspace", "syllabus · notes · bank · practice · mock"),
]
for x, y, bw, title, line in sub:
    svg += f'<rect x="{x}" y="{y}" width="{bw}" height="72" rx="8" class="box"/>'
    svg += text(x + 14, y + 28, title, "bt")
    svg += text(x + 14, y + 52, line, "bs")

services = [
    ("Judge", ["subprocess harness", "3 s timeout", "trusted-parent grading"]),
    ("Problem bank", ["15 challenges", "visible + hidden tests", "reference answers"]),
    ("Exam engine", ["questions and scoring", "sessions and snapshots", "mastery analytics"]),
    ("Study generation", ["source-grounded notes", "validated question banks", "opt-in AI transport"]),
    ("StudentStore", ["accounts and progress", "exam workspaces", "SQLite or Oracle"]),
]
svc_x = [40 + i * 227 for i in range(5)]
for x, (title, lines) in zip(svc_x, services):
    svg += box(x, 250, 209, 104, title, lines, cls="svc", line_gap=19)
    svg += arrow([(x + 104.5, 202), (x + 104.5, 250)])

svg += box(
    40, 448, 460, 80, "AI provider (optional)",
    ["Ollama · Gemini · OpenAI-compatible · receives only workspace text"],
    cls="ai", title_cls="bs", line_cls="note",
)
svg += arrow([(824, 354), (824, 414), (270, 414), (270, 448)], cls="dash")

os_layout = [
    (40, 265, "HostsAuthority", ["fixed PowerShell helper", "manifest + ACL checks", "one-shot UAC request"], "lock"),
    (335, 205, "Windows hosts file", ["managed marker block", "re-read verification", "original restored"], "lock"),
    (570, 200, "ProcessKiller", ["psutil / tasklist", "blocklisted apps", "every 2.5 seconds"], "svc"),
    (800, 175, "SQLite", ["default local store", "data/codelock.db", "student and exam records"], "data"),
    (1005, 155, "Oracle 19c+", ["optional shared store", "PL/SQL package", "same logical schema"], "ai"),
]
for x, bw, title, lines, cls in os_layout:
    svg += box(x, 580, bw, 110, title, lines, cls=cls, line_gap=19)

svg += arrow([(40, 170), (26, 170), (26, 635), (40, 635)])
svg += '<text x="22" y="470" class="edge" transform="rotate(-90 22 470)">lock / unlock</text>'
svg += arrow([(305, 635), (335, 635)])
svg += arrow([(1000, 354), (1000, 400), (887, 400), (887, 580)])
svg += arrow([(1085, 354), (1085, 580)], cls="dash")
svg += text(
    40, 736,
    "The hosts helper is installed separately by an administrator. The GUI never installs or elevates itself;",
    "note",
)
svg += text(
    40, 756,
    "if the helper is unavailable, website blocking reports an honest unavailable status and the rest of the app still starts.",
    "note",
)
write("fig-4-1-architecture.svg", svg + "</svg>")

# ---------------------------------------------------------------------- workflow
w, h = 1200, 960
svg = HEAD.format(w=w, h=h, font=FONT)
svg += box(470, 26, 260, 66, "Student signs in", ["username + password"], cls="gui")
svg += box(430, 132, 340, 68, "Choose how to study", ["two-button mode chooser"], cls="box")
svg += arrow([(600, 92), (600, 132)])
svg += arrow([(430, 166), (330, 166), (330, 248)], label="1. Exam Preparation", label_at=(300, 158))
svg += arrow([(770, 166), (870, 166), (870, 248)], label="2. DSA Practice", label_at=(782, 158))

exam_boxes = [
    (90, 248, 400, 74, "Exam Preparation", ["PC remains unlocked"], "exam"),
    (90, 358, 400, 74, "Create workspace", ["upload PDF / DOCX / TXT · review and approve topics"], "exam"),
    (90, 468, 400, 74, "Study tools", ["revision notes · question bank · practice · mock"], "exam"),
    (90, 578, 400, 66, "Close the exam window", ["CodeLock exits; no lock was applied"], "box"),
]
for x, y, bw, bh, title, lines, cls in exam_boxes:
    svg += box(x, y, bw, bh, title, lines, cls=cls)
for y in (322, 432, 542):
    svg += arrow([(290, y), (290, y + 36)])

dsa_boxes = [
    (710, 248, 400, 74, "DSA Practice", ["Engineering track starts immediately + PC lock"], "lock"),
    (710, 358, 400, 74, "Write a solution", ["editor blocks paste; submit when ready"], "lock"),
    (710, 468, 400, 74, "Judge the submission", ["hidden tests · strict protocol · 3 s timeout"], "lock"),
]
for x, y, bw, bh, title, lines, cls in dsa_boxes:
    svg += box(x, y, bw, bh, title, lines, cls=cls)
svg += arrow([(910, 322), (910, 358)])
svg += arrow([(910, 432), (910, 468)])
svg += arrow([(910, 542), (910, 578)])

svg += '<path d="M910,578 L1005,628 L910,678 L815,628 Z" fill="#fff7ed" stroke="#c2410c" stroke-width="1.8"/>'
svg += text(866, 633, "All tests pass?", "bt")
svg += arrow([(910, 678), (910, 718)], label="yes", label_at=(920, 704))
svg += box(710, 718, 400, 66, "Unlock reward", ["student confirms · 15-minute countdown"], cls="data")
svg += box(710, 818, 400, 66, "Auto-relock", ["timer expires · next challenge · block returns"], cls="lock")
svg += arrow([(910, 784), (910, 818)])
svg += arrow([(815, 628), (640, 628), (640, 395), (710, 395)], cls="arrow-red", label="retry", label_at=(646, 612))
svg += text(
    40, 936,
    "The final check exercised this flow in --dry-run. No real hosts-file write, UAC approval or helper installation was performed.",
    "note",
)
write("fig-4-2-workflow.svg", svg + "</svg>")

# --------------------------------------------------------------------- data model
w, h = 1200, 880
svg = HEAD.format(w=w, h=h, font=FONT)
svg += text(40, 40, "Logical schema shared by SQLite (default) and Oracle (optional)", "bt")
svg += text(40, 62, "Primary keys identify rows; foreign keys carry student ownership into every dependent table.", "note")
svg += text(40, 82, "student_id is also stored on sessions, questions and responses so reads can enforce ownership.", "note")

tables = [
    (40, 350, 250, 190, "students", ["id  (PK)", "username  (unique)", "display_name", "password_hash, salt", "created_at, last_login"], "data"),
    (350, 130, 270, 175, "progress", ["student_id  (PK, FK)", "track_key  (PK)", "current_index, completed", "attempts, total_seconds", "best_seconds, updated_at"], "data"),
    (350, 360, 270, 185, "attempts", ["id  (PK)", "student_id  (FK)", "track_key, problem_key", "duration_seconds, passed", "tests_passed / tests_total", "created_at"], "data"),
    (350, 600, 270, 210, "exam_workspaces", ["workspace_id  (PK)", "student_id  (FK)", "subject, course_level, exam_date", "source_text, topics_json", "syllabus_approved, notes_json", "questions_json, fingerprint"], "exam"),
    (690, 130, 290, 200, "exam_sessions", ["session_id  (PK)", "student_id  (FK)", "workspace_id  (FK)", "mode, status, blueprint_json", "total_marks, score_marks", "needs_review, duration_limit"], "exam"),
    (690, 370, 290, 195, "exam_questions", ["question_id  (PK)", "workspace_id  (FK)", "student_id, unit_title, topic", "type, difficulty, bloom_level", "prompt, options_json, answer", "source_quote, is_active"], "exam"),
    (690, 610, 290, 195, "exam_responses", ["response_id  (PK)", "session_id  (FK)", "question_id  (FK)", "student_answer, is_correct", "awarded_marks, review_status", "question_snapshot_json"], "exam"),
]
for x, y, bw, bh, title, cols, cls in tables:
    svg += f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="8" class="{cls}"/>'
    svg += f'<rect x="{x}" y="{y}" width="{bw}" height="34" rx="8" fill="#dbeafe" stroke="#475569" stroke-width="1.4"/>'
    svg += text(x + 12, y + 23, title, "bt")
    yy = y + 58
    for col in cols:
        svg += text(x + 12, yy, col, "bs")
        yy += 21

svg += arrow([(290, 380), (320, 380), (320, 210), (350, 210)], label="1:N", label_at=(300, 296))
svg += arrow([(290, 445), (350, 445)], label="1:N", label_at=(304, 437))
svg += arrow([(290, 500), (320, 500), (320, 700), (350, 700)], label="1:N", label_at=(300, 540))
svg += arrow([(835, 330), (835, 370)], label="1:N", label_at=(843, 358))
svg += arrow([(620, 700), (655, 700), (655, 200), (690, 200)], cls="dash", label="blueprint", label_at=(598, 470))
svg += arrow([(835, 610), (835, 565)], cls="dash", label="snapshot", label_at=(843, 595))
svg += arrow([(620, 740), (670, 740), (670, 690), (690, 690)], label="sync", label_at=(628, 730))
svg += text(40, 848, "PK  primary key   ·   FK  foreign key   ·   dashed  =   derived or snapshot relationship", "note")
write("fig-7-1-data-model.svg", svg + "</svg>")

# ---------------------------------------------------------------- verification
w, h = 1100, 580
svg = HEAD.format(w=w, h=h, font=FONT)
svg += '<rect x="20" y="20" width="1060" height="540" rx="14" fill="#0d1117" stroke="#30363d" stroke-width="2"/>'
for i, color in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
    svg += f'<circle cx="{48 + i * 24}" cy="48" r="7" fill="{color}"/>'
svg += '<text x="128" y="55" style="font:700 17px Segoe UI, Arial, sans-serif; fill:#e6edf3">CodeLock - final offline verification</text>'
svg += '<style>.cons { font: 15px Consolas, monospace; fill: #e6edf3; } .ok { font: 15px Consolas, monospace; fill: #3fb950; } .dim { font: 14px Consolas, monospace; fill: #8b949e; }</style>'
lines = [
    (100, "PS> python main.py --self-test", "cons"),
    (130, "SELF-TEST PASSED: all checks passed.                    227 checks", "ok"),
    (170, "PS> .venv\\bin\\python.exe main.py --self-test", "cons"),
    (200, "SELF-TEST PASSED: all checks passed.                    228 checks", "ok"),
    (240, "PS> python main.py --self-test-ui", "cons"),
    (270, "UI SELF-TEST PASSED: all checks passed.                  13 checks", "ok"),
    (310, "PS> python -m py_compile codelock\\gui.py codelock\\exam_ui.py", "cons"),
    (340, "exit code 0", "ok"),
    (380, "PS> mode-chooser flow harness (temporary database)", "cons"),
    (410, "RESULT 23/23 passed  ·  Exam: no lock  ·  DSA: Engineering + lock", "ok"),
]
for y, value, cls in lines:
    svg += f'<text x="52" y="{y}" class="{cls}">{escape(value)}</text>'

cards = [
    ("23 / 23", "mode-chooser flow checks"),
    ("46 / 46", "backup manifest files verified"),
    ("0", "real hosts or UAC operations in the final check"),
]
for i, (big, small) in enumerate(cards):
    cx = 40 + i * 348
    svg += f'<rect x="{cx}" y="470" width="320" height="64" rx="10" fill="#161b22" stroke="#30363d" stroke-width="1.5"/>'
    svg += f'<text x="{cx + 16}" y="498" style="font:700 19px {FONT}; fill:#58a6ff">{escape(big)}</text>'
    svg += f'<text x="{cx + 16}" y="520" style="font:12px {FONT}; fill:#8b949e">{escape(small)}</text>'
write("fig-13-1-verification.svg", svg + "</svg>")

print("done")
