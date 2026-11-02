"""Build the CodeLock project report as paginated HTML for A4 printing."""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent
HTML = OUT / "CodeLock_Project_Report.html"

CSS = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #ffffff; }
body {
  font-family: "Segoe UI", Calibri, Arial, sans-serif;
  color: #1f2937; font-size: 9.8pt; line-height: 1.46;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.page {
  width: 210mm; height: 296.6mm; padding: 20mm 18mm 16mm;
  position: relative; overflow: hidden; background: #ffffff;
  page-break-after: always; break-after: page;
}
.page:last-child { page-break-after: auto; break-after: auto; }
.page-head {
  position: absolute; top: 8mm; left: 18mm; right: 18mm;
  display: flex; justify-content: space-between; align-items: baseline;
  font-size: 7.2pt; color: #64748b; letter-spacing: .08em; text-transform: uppercase;
  border-bottom: 0.4pt solid #d7dee8; padding-bottom: 1.6mm;
}
.page-head b { color: #0b2545; font-weight: 700; letter-spacing: .12em; }
.page-foot {
  position: absolute; bottom: 7mm; left: 18mm; right: 18mm;
  display: flex; justify-content: space-between; align-items: baseline;
  font-size: 7.4pt; color: #64748b;
  border-top: 0.4pt solid #e2e8f0; padding-top: 1.5mm;
}
.page-foot .pg { font-weight: 700; color: #0b2545; }
.kicker {
  font-size: 7.6pt; font-weight: 700; color: #0f766e;
  letter-spacing: .2em; text-transform: uppercase; margin: 0 0 1.2mm;
}
h2.sec {
  font-size: 17pt; line-height: 1.15; color: #0b2545;
  margin: 0; font-weight: 700; letter-spacing: -.015em;
}
.rule { width: 26mm; height: 1.1mm; background: #0f766e; margin: 2.2mm 0 4.6mm; }
h3 { font-size: 11pt; color: #0b2545; margin: 4.2mm 0 1.4mm; line-height: 1.25; }
h4 { font-size: 9.6pt; color: #0f766e; margin: 3mm 0 1mm; }
p { margin: 0 0 2.4mm; text-align: justify; }
ul, ol { margin: 0 0 2.4mm 0; padding-left: 4.6mm; }
li { margin-bottom: 1mm; text-align: justify; }
b, strong { color: #0b2545; }
.small { font-size: 8.6pt; color: #475569; }
.tiny { font-size: 7.8pt; color: #64748b; }
table { width: 100%; border-collapse: collapse; font-size: 8.3pt; line-height: 1.35; margin: 1.4mm 0 3mm; }
th {
  background: #0b2545; color: #ffffff; text-align: left;
  padding: 1.6mm 1.8mm; font-weight: 600; font-size: 8pt; letter-spacing: .02em;
}
td { padding: 1.35mm 1.8mm; border-bottom: 0.35pt solid #dbe3ec; vertical-align: top; }
tr:nth-child(even) td { background: #f7fafc; }
td.c, th.c { text-align: center; }
.compact { font-size: 7.9pt; }
.compact td { padding: 1.05mm 1.6mm; }
.compact th { padding: 1.3mm 1.6mm; }
.figure { margin: 2.6mm 0 3mm; text-align: center; page-break-inside: avoid; }
.figure img { max-width: 100%; border: 0.4pt solid #cbd5e1; background: #fff; }
.caption { font-size: 7.8pt; color: #475569; margin-top: 1.4mm; font-style: italic; }
.two { display: flex; gap: 6mm; align-items: flex-start; }
.two > div { flex: 1; min-width: 0; }
.note {
  background: #f1f5f9; border-left: 1.1mm solid #0f766e;
  padding: 2.4mm 3mm; font-size: 8.5pt; color: #334155; margin: 2.6mm 0 2.8mm;
}
.note b { color: #0b2545; }
.warn { border-left-color: #b45309; background: #fffbeb; }
.toc-row { display: flex; align-items: baseline; font-size: 9.6pt; padding: 1.55mm 0; border-bottom: 0.3pt solid #eef2f7; }
.toc-row .t { white-space: nowrap; }
.toc-row .dots { flex: 1; border-bottom: 0.35pt dotted #94a3b8; margin: 0 2.5mm 1.2mm; }
.toc-row .pg { font-weight: 700; color: #0b2545; }
.toc-row.front .t { color: #475569; }
.toc-row.head { border-bottom: 0.6pt solid #0b2545; font-size: 8pt; text-transform: uppercase; letter-spacing: .12em; color: #64748b; padding-bottom: 1.2mm; }
.toc-row.head .dots, .toc-row.head .pg { visibility: hidden; }
.tiles { display: flex; gap: 4mm; margin-top: 5mm; }
.tile { flex: 1; border: 0.5pt solid #d7dee8; border-top: 1.2mm solid #0f766e; padding: 2.6mm 3mm; }
.tile .n { font-size: 15pt; font-weight: 700; color: #0b2545; line-height: 1.1; }
.tile .l { font-size: 7.6pt; color: #64748b; text-transform: uppercase; letter-spacing: .09em; margin-top: .8mm; }
.tile.red { border-top-color: #b91c1c; }
.cover { padding: 0; }
.cover-band { height: 82mm; background: #0b2545; color: #ffffff; padding: 20mm 22mm 0; position: relative; }
.cover-band:after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 2.2mm; background: #0f766e; }
.cover-univ { font-size: 12pt; font-weight: 700; letter-spacing: .22em; }
.cover-inst { font-size: 9pt; color: #bfdbfe; margin-top: 2mm; letter-spacing: .06em; }
.cover-mark { position: absolute; right: 22mm; top: 22mm; opacity: .92; }
.cover-body { padding: 26mm 22mm 0; }
.cover-kicker { font-size: 8.4pt; font-weight: 700; letter-spacing: .28em; color: #0f766e; }
.cover-title { font-size: 38pt; line-height: 1.02; font-weight: 800; color: #0b2545; margin: 3mm 0 0; letter-spacing: -.03em; }
.cover-sub { font-size: 14.5pt; line-height: 1.35; color: #334155; margin: 5mm 0 0; max-width: 150mm; }
.cover-rule { width: 40mm; height: 1.4mm; background: #b91c1c; margin: 9mm 0; }
.cover-meta { display: flex; gap: 12mm; }
.cover-meta > div { flex: 1; }
.cover-meta span { display: block; font-size: 7.6pt; text-transform: uppercase; letter-spacing: .16em; color: #64748b; margin-bottom: 1.6mm; }
.cover-meta strong { display: block; font-size: 12.5pt; color: #0b2545; }
.cover-meta em { display: block; font-style: normal; font-size: 8.8pt; color: #475569; margin-top: 1mm; }
.cover-foot {
  position: absolute; left: 22mm; right: 22mm; bottom: 18mm;
  display: flex; justify-content: space-between; font-size: 9pt; color: #475569;
  border-top: 0.5pt solid #cbd5e1; padding-top: 3mm;
}
.cert-frame { border: 0.9pt solid #0b2545; outline: 0.45pt solid #0f766e; outline-offset: -3.2mm; padding: 16mm 14mm 12mm; height: 244mm; }
.cert-title { text-align: center; font-size: 22pt; letter-spacing: .3em; color: #0b2545; font-weight: 700; margin: 4mm 0 3mm; }
.cert-sub { text-align: center; font-size: 8.4pt; letter-spacing: .18em; color: #0f766e; text-transform: uppercase; margin-bottom: 10mm; }
.cert-body p { font-size: 10.6pt; line-height: 1.75; }
.cert-sign { display: flex; justify-content: space-between; margin-top: 24mm; }
.cert-sign > div { width: 70mm; border-top: 0.6pt solid #0b2545; padding-top: 2mm; font-size: 8.6pt; color: #475569; text-align: center; }
.cert-sign b { display: block; font-size: 9.4pt; color: #0b2545; }
.doc-title { font-size: 18pt; letter-spacing: .22em; color: #0b2545; font-weight: 700; margin: 0 0 1mm; }
.doc-sub { font-size: 7.8pt; letter-spacing: .16em; color: #0f766e; text-transform: uppercase; margin-bottom: 7mm; }
.code { font-family: Consolas, "Courier New", monospace; font-size: 8.2pt; background: #f1f5f9; padding: .3mm 1.1mm; border-radius: .8mm; color: #0b2545; }
ul.tight li { margin-bottom: .6mm; }
.two-tables { display: flex; gap: 5mm; }
.two-tables > div { flex: 1; min-width: 0; }
ul.checks { list-style: none; padding-left: 0; }
ul.checks li { padding-left: 5.2mm; position: relative; }
ul.checks li:before { content: "\\2713"; position: absolute; left: 0; color: #0f766e; font-weight: 700; }
"""


def tbl(headers: list[str], rows: list[list[str]], widths: list[str] | None = None,
        center: list[int] | None = None, cls: str = "") -> str:
    center = center or []
    cols = ""
    if widths:
        cols = "<colgroup>" + "".join(f'<col style="width:{w}">' for w in widths) + "</colgroup>"
    head = "".join(
        f'<th class="{"c" if i in center else ""}">{h}</th>' for i, h in enumerate(headers)
    )
    body = ""
    for row in rows:
        body += "<tr>" + "".join(
            f'<td class="{"c" if i in center else ""}">{cell}</td>' for i, cell in enumerate(row)
        ) + "</tr>"
    return f'<table class="{cls}">{cols}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def fig(src: str, num: str, caption: str, width: str) -> str:
    return (
        f'<figure class="figure"><img src="assets/{src}" style="width:{width}">'
        f'<figcaption class="caption">Figure {num}: {caption}</figcaption></figure>'
    )


def page(num: int, body: str, right: str, show_head: bool = True, show_foot: bool = True, cls: str = "") -> str:
    head = (
        f'<div class="page-head"><span><b>CodeLock</b> &middot; Project Report</span><span>{right}</span></div>'
        if show_head
        else ""
    )
    foot = (
        f'<div class="page-foot"><span>Abhinandan Upadhyay &middot; UID 26MCA20229</span>'
        f'<span class="pg">Page {num}</span></div>'
        if show_foot
        else ""
    )
    return f'<section class="page {cls}" id="p{num}">{head}{body}{foot}</section>'


TOC = [
    ("Certificate", "2", True),
    ("Acknowledgement", "3", True),
    ("Abstract", "4", True),
    ("Table of Contents", "5", True),
    ("Table of Images", "6", True),
    ("1.  Project Title and Basic Information", "7", False),
    ("2.  Executive Summary and Problem Statement", "8", False),
    ("3.  Case Study Description and Methodology", "9", False),
    ("4.  System Architecture and Workflow", "10", False),
    ("5.  Implementation and Functional Modules", "12", False),
    ("6.  User Interface and Project Evidence", "14", False),
    ("7.  Local Data Design and Data Management", "18", False),
    ("8.  Side-by-Side Comparison Tables", "20", False),
    ("9.  Research / Project Gap Analysis", "21", False),
    ("10. Expected Outcomes and Evaluation Criteria", "22", False),
    ("11. Limitations and Conclusion", "23", False),
    ("12. References and Appendices", "24", False),
    ("13. GitHub Proof and Source Inventory", "25", False),
]

FIGURES = [
    ("2.1", "DSA Practice with the desktop locked and the judge console active", "Screenshot", "8"),
    ("2.2", "Fifteen-minute reward countdown after a passing submission", "Screenshot", "8"),
    ("4.1", "Three-layer architecture of the CodeLock application", "Diagram", "10"),
    ("4.2", "Mode selection and the DSA lock, judge and reward workflow", "Diagram", "11"),
    ("6.1", "Student sign-in dialog with the active storage backend", "Screenshot", "14"),
    ("6.2", "Two-button mode chooser shown after sign-in", "Screenshot", "14"),
    ("6.3", "Exam Preparation workspace with the syllabus tab", "Screenshot", "15"),
    ("6.4", "Editable question bank generated from an approved syllabus", "Screenshot", "16"),
    ("6.5", "Topic-wise practice session with immediate feedback", "Screenshot", "16"),
    ("6.6", "Mock examination result with a per-topic breakdown", "Screenshot", "17"),
    ("6.7", "Analytics dashboard with mastery and recommendations", "Screenshot", "17"),
    ("7.1", "Relational data model used by SQLite and Oracle", "Diagram", "19"),
    ("13.1", "Final offline verification summary", "Screenshot", "25"),
]


def toc_html() -> str:
    out = '<div class="toc-row head"><span class="t">Section</span><span class="dots"></span><span class="pg">Page</span></div>'
    for title, pg, front in TOC:
        cls = "toc-row front" if front else "toc-row"
        out += f'<div class="{cls}"><span class="t">{title}</span><span class="dots"></span><span class="pg">{pg}</span></div>'
    return out


def figures_html() -> str:
    rows = [[f"<b>{n}</b>", cap, typ, f"<b>{pg}</b>"] for n, cap, typ, pg in FIGURES]
    return tbl(["Figure", "Title", "Type", "Page"], rows, ["15mm", "110mm", "22mm", "15mm"], [0, 2, 3])


pages: list[str] = []

# ---------------------------------------------------------------- 1 cover
cover = """
<div class="cover-band">
  <div class="cover-univ">CHANDIGARH UNIVERSITY</div>
  <div class="cover-inst">University Institute of Computing &middot; Mohali, Punjab</div>
  <svg class="cover-mark" width="104" height="104" viewBox="0 0 120 120" fill="none">
    <rect x="8" y="8" width="104" height="104" rx="24" stroke="#38bdf8" stroke-width="2" opacity="0.55"/>
    <rect x="31" y="53" width="58" height="45" rx="9" stroke="#ffffff" stroke-width="4"/>
    <path d="M42 53V41a18 18 0 0 1 36 0v12" stroke="#ffffff" stroke-width="4" stroke-linecap="round"/>
    <circle cx="60" cy="72" r="6" fill="#0f766e"/>
    <path d="M60 77v9" stroke="#0f766e" stroke-width="4" stroke-linecap="round"/>
  </svg>
</div>
<div class="cover-body">
  <div class="cover-kicker">PROJECT REPORT</div>
  <div class="cover-title">CodeLock</div>
  <div class="cover-sub">A Study-Focused Desktop Kiosk for Exam Preparation and DSA Practice</div>
  <div class="cover-rule"></div>
  <div class="cover-meta">
    <div>
      <span>Submitted by</span>
      <strong>Abhinandan Upadhyay</strong>
      <em>UID: 26MCA20229 &middot; Master of Computer Applications</em>
    </div>
    <div>
      <span>Under the guidance of</span>
      <strong>Mr. Randeep Singh Dhillon</strong>
      <em>University Institute of Computing</em>
    </div>
  </div>
</div>
<div class="cover-foot"><span>November 2026</span><span>Mohali, Punjab</span></div>
"""
pages.append(page(1, cover, "", show_head=False, show_foot=False, cls="cover"))

# ---------------------------------------------------------- 2 certificate
cert = """
<div class="cert-frame">
  <div class="doc-title" style="text-align:center">CERTIFICATE</div>
  <div class="cert-sub">University Institute of Computing &middot; Chandigarh University</div>
  <div class="cert-body">
    <p>This is to certify that <b>Abhinandan Upadhyay (UID: 26MCA20229)</b>, a student of the Master of
    Computer Applications (MCA) programme, has successfully completed the project entitled
    <b>&ldquo;CodeLock: A Study-Focused Desktop Kiosk for Exam Preparation and DSA Practice&rdquo;</b>
    under my supervision and guidance.</p>
    <p>The work presented in this report is submitted in partial fulfilment of the academic requirements
    of the MCA programme. To the best of my knowledge, the project work described herein is an authentic
    record of the student&rsquo;s work. The report distinguishes the paths that were verified offline from
    the privileged Windows operations that were intentionally not performed in the development
    environment.</p>
    <p style="margin-top:8mm">Date: ____________________<br>Place: Chandigarh University, Mohali, Punjab</p>
  </div>
  <div class="cert-sign">
    <div><b>Head of the Department</b>University Institute of Computing</div>
    <div><b>Mr. Randeep Singh Dhillon</b>Project Guide / Supervisor &middot; University Institute of Computing</div>
  </div>
</div>
"""
pages.append(page(2, cert, "Certificate"))

# ------------------------------------------------------- 3 acknowledgement
ack = """
<div class="doc-title">ACKNOWLEDGEMENT</div>
<div class="doc-sub">A note of thanks</div>
<p>I express my sincere gratitude to my project guide, <b>Mr. Randeep Singh Dhillon</b>, for his guidance,
feedback and encouragement throughout the development of CodeLock. His suggestions during planning,
implementation and documentation helped me separate the parts of the project that could be verified
offline from the privileged operating-system operations that required a controlled test machine.</p>
<p>I am thankful to the faculty members of the University Institute of Computing, Chandigarh University,
for providing the academic environment and learning resources required to complete this project. I also
acknowledge the support of my classmates and friends who reviewed the application and identified areas
for improvement, particularly around the two-mode navigation and the visibility of the exam workspace.</p>
<p>I would like to thank my family for their continuous encouragement and support. Finally, I acknowledge
the developers and maintainers of Python, Tkinter, pypdf, psutil, python-oracledb, SQLite and PowerShell,
whose documentation and open tools supported this work.</p>
<div class="note"><b>A note on scope.</b> CodeLock was built as a commitment device for a student&rsquo;s own
computer. It is not a surveillance product, a parental-control system or a security boundary. The report
states that limitation explicitly so that the project is evaluated for what it actually does.</div>
<p style="margin-top:18mm"><b>Abhinandan Upadhyay</b> &middot; UID 26MCA20229<br>
Master of Computer Applications<br>
Date: November 2026</p>
"""
pages.append(page(3, ack, "Acknowledgement"))

# --------------------------------------------------------------- 4 abstract
abstract = """
<div class="doc-title">ABSTRACT</div>
<div class="doc-sub">Project summary</div>
<p>CodeLock is a Python and Tkinter desktop application that turns a student&rsquo;s own computer into a
short, self-imposed focus session. It addresses two problems that often appear together in self-study:
distracting websites and applications break concentration, and examination preparation frequently becomes
passive reading without measurable feedback. After signing in, the student chooses between two modes.
<b>Exam Preparation</b> opens a workspace in which a syllabus document is imported, its topic tree is
reviewed and approved, study notes and a validated question bank are produced, and practice, mock
examinations, results and topic-level analytics are available without locking the computer.
<b>DSA Practice</b> selects the Engineering coding track and locks the PC: a verified PowerShell helper
writes a marked block into the hosts file, a watchdog terminates a small set of blacklisted desktop
processes, and only a solution that passes visible and hidden tests, followed by explicit student
confirmation, releases a fifteen-minute reward.</p>
<p>A submission runs in a separate Python interpreter under a trusted-parent protocol. The child process
never receives expected answers, hidden cases or a verdict field; the parent reconstructs the returned
value and performs the comparison itself. Accounts, attempts, exam workspaces, question banks and exam
sessions are stored in SQLite by default or in Oracle through a PL/SQL package. The final offline suite
passes 227 checks with system Python and 228 through the project virtual environment, the Analytics GUI
smoke test passes 13 of 13 checks, and a dedicated mode-chooser flow harness passes 23 of 23 checks.
Real UAC approval, helper installation and writes to the system hosts file were deliberately not performed
in the development environment; those paths are represented by dry-run behaviour, temporary-file tests
and simulated backends, and the report keeps that boundary visible.</p>
<p class="small"><b>Keywords:</b> digital self-control, kiosk application, Python, Tkinter, coding judge,
exam preparation, SQLite, Oracle, hosts file, responsible use.</p>
"""
pages.append(page(4, abstract, "Abstract"))

# -------------------------------------------------------------- 5 contents
toc_body = """
<div class="kicker">Navigation</div>
<h2 class="sec">Table of Contents</h2>
<div class="rule"></div>
""" + toc_html() + """
<div class="tiles">
  <div class="tile"><div class="n">25</div><div class="l">Pages</div></div>
  <div class="tile"><div class="n">13</div><div class="l">Figures</div></div>
  <div class="tile"><div class="n">16,570</div><div class="l">Lines of code</div></div>
  <div class="tile red"><div class="n">23/23</div><div class="l">Flow checks</div></div>
</div>
<div class="note" style="margin-top:6mm"><b>How to use this report.</b> Section page numbers refer to the
printed page number at the bottom of each page. The Table of Images on the following page lists every
figure with its number, caption and page. Figures 2.1 and 2.2 were captured in <span class="code">--dry-run</span>
mode, where the lock is simulated; Figures 6.1 to 6.7 were captured from the current build and a
temporary exam database.</div>
"""
pages.append(page(5, toc_body, "Contents"))

# --------------------------------------------------------- 6 table of images
loi_body = """
<div class="kicker">Navigation</div>
<h2 class="sec">Table of Images</h2>
<div class="rule"></div>
<p class="small">The report uses two kinds of image: diagrams drawn specifically for this document, and
screenshots captured from the submitted CodeLock build. Each figure is numbered by the section in which
it first appears.</p>
""" + figures_html() + """
<div class="two" style="margin-top:4mm">
  <div class="note"><b>Diagram figures</b> (4.1, 4.2, 7.1) are original vector drawings produced for this
  report and embedded as SVG. They describe the implemented layers, the user workflow and the relational
  schema.</div>
  <div class="note warn"><b>Screenshot provenance.</b> DSA screenshots come from a dry run in which no
  hosts entry is written. Exam screenshots come from a temporary SQLite database. No personal account
  data appears in any figure.</div>
</div>
"""
pages.append(page(6, loi_body, "Table of Images"))

# --------------------------------------------------------------- 7 section 1
s1 = """
<div class="kicker">Section 01</div>
<h2 class="sec">Project Title and Basic Information</h2>
<div class="rule"></div>
<h3>1.1 Project Overview</h3>
<p><b>Project title:</b> CodeLock: A Study-Focused Desktop Kiosk for Exam Preparation and DSA Practice.
CodeLock is a local Python/Tkinter desktop application that combines two capabilities usually kept
separate: a focus mode that applies an operating-system-level website block and terminates distracting
desktop applications during a coding challenge, and an examination-preparation workspace that turns an
imported syllabus into source-grounded notes, questions, scored practice and topic-level analytics.</p>
<p>The focus loop is deliberately short: solve one DSA challenge, confirm the unlock after a passing
submission, receive fifteen minutes of unrestricted use, then meet the next challenge. Exam Preparation
applies no lock; its purpose is measurable preparation, not restriction.</p>
<h3>1.2 Basic Project Information</h3>
""" + tbl(["Item", "Details"], [
    ["Project category", "Desktop commitment device and study workspace"],
    ["Language / runtime", "Python 3.10+ (developed on Python 3.14.7)"],
    ["GUI", "Tkinter / ttk kiosk window with a built-in code editor"],
    ["Focus controls", "Windows hosts file through a separately installed PowerShell helper; process watchdog"],
    ["Coding judge", "Trusted-parent subprocess protocol with generated hidden tests"],
    ["Exam documents", "PDF through pypdf; DOCX through the standard library; plain text"],
    ["Study generation", "Configurable Ollama, Gemini or OpenAI-compatible endpoint; no stored keys"],
    ["Accounts / storage", "SQLite by default; Oracle 19c+ with a PL/SQL package when configured"],
    ["Verification", "Offline self-test, Tk GUI smoke test and mode-chooser flow harness"],
    ["Contributor", "Abhinandan Upadhyay (26MCA20229)"],
    ["Project guide", "Mr. Randeep Singh Dhillon"],
], ["38mm", "118mm"], cls="compact") + """
<h3>1.3 Scope</h3>
<p><b>In scope:</b> accounts and sign-in, the two-mode chooser, an Engineering DSA session (warm-up plus
five challenges), hidden-test grading, reward and auto-relock, website and process enforcement, syllabus
import and approval, notes and questions, practice and mock sessions, results, analytics, SQLite/Oracle
persistence and recovery. <b>Out of scope:</b> mobile-device control, a secure code sandbox, live
proctoring, OCR, manual marking, password recovery and a hosted multi-user service.</p>
<h3>1.4 Repository and Submission Note</h3>
<p>At the time of writing, no public GitHub repository has been configured for CodeLock. This report
therefore does not present a repository URL. The complete source folder, documentation and a verified
backup snapshot are submitted together; Section 13 records the file inventory and backup result. A link
that does not resolve would be weaker evidence than a clear statement of what was submitted.</p>
<h3>1.5 How This Report Is Organised</h3>
<p>Sections 2 and 3 cover the problem, objectives and methodology. Sections 4 and 5 describe the
architecture and each module; Section 6 presents interface evidence and Section 7 the data design.
Sections 8 to 11 contain comparisons, gaps, evaluation and limitations, and Sections 12 and 13 provide
references, appendices and the source-inventory proof.</p>
"""
pages.append(page(7, s1, "Section 1 &middot; Project Information"))

# --------------------------------------------------------------- 8 section 2
s2 = """
<div class="kicker">Section 02</div>
<h2 class="sec">Executive Summary and Problem Statement</h2>
<div class="rule"></div>
<h3>2.1 Executive Summary</h3>
<p>CodeLock demonstrates how a small, locally installed application can combine a credible focus contract
with an evidence-producing study workspace. The focus contract is concrete: the hosts file contains a
marked block for nine distracting domains, a watchdog terminates seven blacklisted desktop applications
every 2.5 seconds, and the unlock is conditional on a coding submission that passes all hidden tests and a
separate confirmation dialog. The study workspace is equally concrete: an uploaded syllabus becomes an
editable topic tree, the approved tree gates generated notes and questions, and practice and mock sessions
produce scores, per-topic accuracy and mastery indicators.</p>
<p>The application runs as a standard user: it does not install the elevated helper, keep an elevated
process alive or invent study content when no AI provider is available. Privileged operations are single,
visible approvals and storage is scoped to the signed-in student.</p>
<h3>2.2 Problem Statement</h3>
<p>Study time on a personal computer is interrupted by low-friction escapes, while enterprise device
management is too heavy for a student who simply wants a focused hour. Examination preparation fails
differently: generated notes and questions appear quickly, but without a syllabus, a source reference and
a scoring record the student cannot tell whether the material matches the course or whether understanding
improved. CodeLock treats both as one design problem: a short commitment contract creates the session and
a measurable workspace gives it a purpose.</p>
<h3>2.3 Project Objectives</h3>
<ul class="tight">
<li>Provide a clear two-mode entry point: Exam Preparation without a lock, DSA Practice with a lock.</li>
<li>Block distracting sites and processes only during a DSA session, then restore them after the reward.</li>
<li>Grade submissions against hidden tests without exposing expected answers to student code.</li>
<li>Require explicit confirmation before an unlock and restore the block automatically after fifteen minutes.</li>
<li>Turn an uploaded syllabus into an approved topic tree, notes, a validated question bank, scored sessions
and topic-level mastery reporting.</li>
<li>Persist progress locally by default, with an optional shared Oracle backend, and keep privileged
operations visible and recoverable.</li>
</ul>
<h3>2.4 Intended Users</h3>
<p>MCA and engineering students preparing for examinations and coding interviews on their own Windows
computers; instructors demonstrating a local-first application with a real test suite; and reviewers
interested in the safety engineering around a privileged helper and untrusted submissions.</p>
""" + '<div class="two">' \
    '<div>' + fig("fig-2-1-dsa-locked.png", "2.1", "DSA Practice with the desktop locked (dry run).", "70mm") + '</div>' \
    '<div>' + fig("fig-2-2-reward.png", "2.2", "Reward countdown after a passing submission (dry run).", "70mm") + '</div>' \
    '</div>'
pages.append(page(8, s2, "Section 2 &middot; Problem Statement"))

# --------------------------------------------------------------- 9 section 3
s3 = """
<div class="kicker">Section 03</div>
<h2 class="sec">Case Study Description and Methodology</h2>
<div class="rule"></div>
<h3>3.1 Case Study Description</h3>
<p>The case study is the development and local operation of CodeLock on a Windows 10 machine with a
1366&times;768 display, Python 3.14.7, Tk 8.6 and PowerShell 5.1. The submitted folder contains
<span class="code">main.py</span>, 19 Python modules under <span class="code">codelock/</span>, a fixed
elevated helper, an installer, an Oracle schema and migrations: approximately 16,570 lines across Python,
PowerShell and SQL. The application starts as a standard user, opens a sign-in dialog and then the mode
chooser; no host or process change occurs before DSA Practice is selected. A final navigation change
replaced the original four-track picker with the two-button chooser described here.</p>
<h3>3.2 Development Methodology</h3>
<ol class="tight">
<li><b>Requirements and threat model:</b> define the modes, the unlock policy and the trust boundaries
between the standard-user GUI, the elevated helper, the student submission and the optional AI provider.</li>
<li><b>Core and interface:</b> build configuration, the problem bank, the judge, the hosts authority, the
process watchdog and the Tkinter kiosk with paste and close actions trapped.</li>
<li><b>Accounts and persistence:</b> implement PBKDF2 password storage, per-track progress and the
SQLite/Oracle backends behind one interface.</li>
<li><b>Exam workspace:</b> add syllabus extraction, topic approval, notes, the question bank, practice,
mock sessions, results and analytics.</li>
<li><b>Audit and remediation:</b> review the judge, helper verification, unlock policy and UI status
reporting, and add regression checks for each finding.</li>
<li><b>Verification and documentation:</b> run the offline suite, the GUI smoke test and the mode flow
harness, then record the results and the untested boundaries.</li>
</ol>
<h3>3.3 Local Setup and Reproduction</h3>
<p>The application requires Python 3.10 or later with Tkinter. From the project folder, create a virtual
environment, install the requirements, run the offline self-test, and then launch in dry-run mode before
using enforcement.</p>
""" + tbl(["Step", "Command", "Purpose"], [
    ["1", "python -m venv .venv", "Create the isolated environment"],
    ["2", "pip install -r requirements.txt", "Install pypdf, psutil and the optional Oracle driver"],
    ["3", "python main.py --self-test", "Run the offline verification suite"],
    ["4", "python main.py --dry-run", "Open the GUI with enforcement simulated"],
], ["12mm", "66mm", "78mm"], [0]) + """
<p class="small">The elevated helper is installed separately by an administrator; the GUI never installs
or elevates itself. Without it, CodeLock still starts and grades challenges, but the HOSTS FILE badge
reports the observed state and explains why blocking is unavailable.</p>
<h3>3.4 Evidence Basis</h3>
<p>This report uses the submitted source, README and audit records plus current-build screenshots. It
reports the offline suite (227 checks with system Python, 228 in the virtual environment), the Tk smoke
test (13/13) and the mode flow harness (23/23). Real UAC approval, helper installation, hosts writes,
Oracle execution and live AI generation were not performed; Sections 9 and 11 keep that visible.</p>
<h3>3.5 Responsible-Use Position</h3>
<p>CodeLock is intended for a student&rsquo;s own computer, with the student&rsquo;s knowledge. It is a
commitment device, not a monitoring tool: it collects no screenshots, keystrokes or browsing history, and
use by another person would require informed consent.</p>
"""
pages.append(page(9, s3, "Section 3 &middot; Methodology"))

# ------------------------------------------------------- 10 section 4 + fig 4.1
s4a = """
<div class="kicker">Section 04</div>
<h2 class="sec">System Architecture and Workflow</h2>
<div class="rule"></div>
<h3>4.1 Architecture</h3>
<p>CodeLock is a layered desktop application. The Tkinter presentation layer owns the window, the editor,
the judge console and the exam tabs. Application services implement grading, the problem bank, the exam
engine, study generation and the student store. A narrow privilege boundary separates the standard-user
application from the installed hosts helper, while the process watchdog runs inside the application and
terminates blacklisted desktop programs. SQLite is the default store; Oracle is an optional shared
backend.</p>
""" + tbl(["Layer", "Components", "Responsibility"], [
    ["Presentation", "main.py; codelock/gui.py; exam_ui.py; exam_runner.py", "Kiosk window, sign-in, mode chooser, editor, exam tabs"],
    ["Application", "judge.py; problems.py; exam_engine.py; study_generation.py", "Grading, challenge bank, scoring, notes and questions"],
    ["Data services", "db.py; exam_analytics.py; exam_charts.py", "Accounts, progress, sessions, analytics, charts"],
    ["Privilege boundary", "hosts_elevation.py; windows_acl.py; hosts_helper.ps1", "Manifest and ACL verification; one-shot UAC helper"],
    ["Operating system", "Windows hosts file; ProcessKiller", "Website block and desktop-process enforcement"],
    ["Persistence", "SQLite (default); Oracle 19c+ (optional)", "Student, progress, exam workspace and session records"],
], ["30mm", "72mm", "54mm"]) + fig("fig-4-1-architecture.svg", "4.1", "Three-layer architecture of CodeLock, including the optional AI provider and the privileged hosts helper.", "152mm") + """
<p class="small">The helper is installed once by an administrator and re-verified on every elevated launch.
The GUI never installs it, never executes the project copy and never keeps an elevated process alive.</p>
"""
pages.append(page(10, s4a, "Section 4 &middot; Architecture"))

# ---------------------------------------------------------- 11 section 4 cont.
s4b = """
<h3>4.2 Design Principles</h3>
<ul class="tight">
<li><b>Trusted-parent grading.</b> The GUI process owns the test data and the verdict; the submission
receives one case at a time and never sees expected values.</li>
<li><b>Least privilege.</b> The application runs as a standard user; each hosts change is one approved
helper operation, not a long-running elevated service.</li>
<li><b>Fail visible.</b> A failed or unverifiable operation reports the observed hosts state instead of
claiming success.</li>
<li><b>Local-first data.</b> Accounts and progress work without a server; Oracle is optional, and AI keys
are read from the environment rather than stored.</li>
<li><b>Honest scope.</b> The judge is not described as a security sandbox, and unverified paths are named
in the documentation.</li>
</ul>
<h3>4.3 Application Workflow</h3>
<p>After sign-in, the chooser is the only path into the application. The Exam branch opens the workspace
with <span class="code">track=None</span>, starts no watchdog and applies no lock; closing the exam window
exits CodeLock. The DSA branch selects the Engineering track, loads the Addition warm-up, pins the window,
starts the watchdog and applies the hosts block. A passing submission still requires confirmation before
the reward; declining leaves the machine locked. When the reward expires, the block returns and the next
challenge loads.</p>
""" + fig("fig-4-2-workflow.svg", "4.2", "Mode selection and the DSA lock, judge, reward and relock workflow.", "138mm") + """
<h3>4.4 Concurrency and Lifecycle</h3>
<p>A daemon watchdog sweeps the process blocklist and re-checks the hosts state every 2.5 seconds, posting
results to the Tk event queue rather than touching widgets from the thread. The reward countdown uses
Tk&rsquo;s <span class="code">after()</span> scheduler. Submissions run in a separate judge thread so the
window remains responsive during the three-second grading limit. Shutdown stops the watchdog, terminates
active judge workers, restores the hosts file when a block is active and then destroys the root window.</p>
"""
pages.append(page(11, s4b, "Section 4 &middot; Workflow"))

# ------------------------------------------------------- 12 section 5 part 1
s5a = """
<div class="kicker">Section 05</div>
<h2 class="sec">Implementation and Functional Modules</h2>
<div class="rule"></div>
<h3>5.1 Student Accounts and Mode Selection</h3>
<p>Accounts are created locally or in the configured Oracle schema. Passwords are hashed with
PBKDF2-SHA256 and 200,000 iterations before storage; the database holds the hash and a random salt, never
the plaintext. A student can create an account, sign in and resume per-track progress. After sign-in, the
mode chooser presents <b>1. DSA Practice</b> first and <b>2. Exam Preparation</b> second. In real mode the
chooser cannot be closed with its title-bar button; the student must select a mode. DSA Practice selects
Engineering, opens the Addition warm-up and starts enforcement. Exam Preparation opens the workspace without
a lock and closes CodeLock when its window closes.</p>
<h3>5.2 Focus Mode and Process Control</h3>
<p>The focus mode writes a delimited CodeLock block into the Windows hosts file. On Windows the write is
performed by a fixed PowerShell helper installed under <span class="code">%ProgramFiles%\\CodeLock</span>.
Before requesting UAC, the application verifies the installation directory ACL, the manifest and the
helper SHA-256; the helper accepts only block, unblock, status, recover and repair operations, and the
blocked domains are compiled into it. The application re-reads the hosts file after every operation and
reports BLOCKED, PARTIAL, DAMAGED, NOT BLOCKED or STATUS UNKNOWN. A watchdog terminates Discord, Steam,
Spotify, WhatsApp, Telegram, Epic Games Launcher and Discord Canary every 2.5 seconds.</p>
<h3>5.3 Coding Judge</h3>
<p>A submission is sent over standard input to a fresh <span class="code">python -I</span> process in a
temporary working directory. The parent owns the visible and hidden cases, sends one case at a time and
compares the returned, type-tagged value itself. The worker never receives an expected answer, the test
list or a hidden/sample flag. Frames use a per-session prefix and a strict order; missing, duplicate,
extra, malformed or oversized frames are rejected. A three-second overall limit and a two-second per-case
limit bound execution, and the process tree is terminated on timeout. On Windows the worker is assigned to
a Job Object with a CPU limit, a 256 MiB process-memory limit and kill-on-close; on POSIX it receives its
own process group and resource limits.</p>
<h3>5.4 Hidden Tests and Unlock Policy</h3>
<p>Every challenge has visible examples and 24 to 38 generated hidden cases (30 for the Addition warm-up).
Cases are seeded for reproducibility and include edge cases such as empty input, duplicates and negative
numbers; expected answers come from brute-force reference logic. <b>RUN SAMPLES</b> checks only the visible
examples and cannot unlock anything. <b>SUBMIT &amp; UNLOCK PC</b> runs the full set; even a complete pass
requires a separate confirmation. Declining the confirmation leaves the PC locked and still records the
passing attempt.</p>
<h3>5.5 Exam Workspace and Syllabus Approval</h3>
<p>An Exam Preparation workspace stores the subject, course level, examination date, total marks and
duration. A syllabus can be uploaded as PDF, DOCX or TXT, or entered as a manual outline. PDF text is
extracted locally with pypdf; DOCX paragraph and table text uses the standard library. Extraction is
bounded to 20 MiB per file, 500 PDF pages and 500,000 characters. The extracted unit/topic tree remains
editable until the student approves it. Generated notes and questions are unavailable before approval,
and changing an approved syllabus revokes approval and empties the active question bank.</p>
"""
pages.append(page(12, s5a, "Section 5 &middot; Modules"))

# ------------------------------------------------------- 13 section 5 part 2
s5b = """
<h3>5.6 Notes and Question Bank</h3>
<p>Notes can be generated in very short, standard or detailed styles. Each note keeps its source filename,
unit and topic reference and a support status; topics not covered by the supplied source are marked as not
specified rather than filled with invented content. The question bank supports multiple choice,
true/false, fill-in, one-word, short-answer, long-answer, practical, programming and viva questions.
Questions are validated for type, difficulty, Bloom level, answer, explanation, marks, source topic and
duplicates before saving. Generated text remains editable, and all rows are scoped to the signed-in
student. When no AI provider is configured, the interface shows an error and does not fall back to
fabricated material.</p>
<h3>5.7 Practice, Mock Examinations and Results</h3>
<p>Practice builds a topic-wise test from the approved bank: choose one or more topics, a difficulty and a
question count. Objective answers are checked immediately with the awarded marks, reference answer and
explanation; written answers are stored and flagged for review. Mock examinations add a duration, an
optional target score and a countdown that starts when the session opens. Answers can be changed until
submission, and the paper submits automatically when time runs out. Each session snapshots its questions,
so later edits to the bank cannot alter a paper in progress or already submitted.</p>
<h3>5.8 Results and Analytics</h3>
<p>The Results tab lists every session with score, accuracy and review count. A finished session opens a
per-topic breakdown and a full answer review. Analytics reads only submitted sessions; abandoned or
in-progress sessions never affect the figures. A topic needs at least five graded answers before it is
classified as critical (below 45%), weak (below 60%), developing (below 75%) or strong (75% and above).
A recent drop of 15 points is called out separately. Mastery is <i>Not Started</i>, <i>Needs Improvement</i>,
<i>Learning</i> or <i>Mastered</i> (at least 8 graded answers and 80% accuracy with no decline). The range
filter covers the last 7 days, the last 30 days or all time and applies to every card, chart, table and
recommendation. Written answers awaiting review are excluded from accuracy rather than counted as wrong.</p>
<h3>5.9 Persistence: SQLite and Oracle</h3>
<p>SQLite is created automatically at <span class="code">data/codelock.db</span>. When
<span class="code">CODELOCK_ORACLE_DSN</span> is set and the driver connects, the same logical schema is
served by Oracle through the <span class="code">codelock_api</span> PL/SQL package. Normalized question and
session rows are derived from the approved question JSON by <span class="code">sync_question_bank</span>;
the JSON remains the editable source document. Exam migrations are provided for an existing Oracle schema.</p>
<h3>5.10 Safety, Recovery and Emergency Exit</h3>
<p>The first modification saves <span class="code">hosts.codelock.bak</span>. The helper writes a temporary
file in the same directory, flushes it, replaces the hosts file atomically, preserves its encoding and
newline style and re-reads the result. Damaged markers can be repaired; <span class="code">--restore</span>
removes exact CodeLock markers and managed lines while preserving unrelated entries. If a result cannot be
verified, the application reports the observed state and writes a recovery note with the exact command.
The emergency exit (Ctrl+Alt+Shift+Q or the on-screen button) restores website access and quits; when an
admin password is configured, it is required. The watchdog never opens a UAC prompt on its own.</p>
"""
pages.append(page(13, s5b, "Section 5 &middot; Modules"))

# ------------------------------------------------------- 14 section 6 part 1
s6a = """
<div class="kicker">Section 06</div>
<h2 class="sec">User Interface and Project Evidence</h2>
<div class="rule"></div>
<h3>6.1 Sign-In and Mode Selection</h3>
<p>The sign-in dialog is the first screen. It reports which storage backend is active, so a reviewer can
see whether the session is using SQLite or Oracle before creating an account. The mode chooser then
presents the two journeys as full-width buttons with a short description, a consequence line and a colour
cue: green for Exam Preparation, red for DSA Practice. The chooser is intentionally modal; closing it does
not dismiss the application in real mode.</p>
<div class="two">
  <div>""" + fig("fig-6-1-login.png", "6.1", "Student sign-in dialog with the active storage backend.", "72mm") + """</div>
  <div>""" + fig("fig-6-2-mode-chooser.png", "6.2", "Two-button mode chooser shown after sign-in.", "88mm") + """</div>
</div>
<h3>Interface Characteristics</h3>
<ul class="checks tight">
<li>The window remains above other windows during a DSA session and re-asserts itself every 1.5 seconds.</li>
<li>The title-bar close action, Alt+F4 and paste shortcuts are trapped while the PC is locked.</li>
<li>The judge console reports sample runs, hidden-test progress, elapsed time and saved progress.</li>
<li>The exam workspace uses seven tabs so that long forms do not compete for one screen.</li>
<li>Error messages name the observed state and the next action instead of hiding a failed operation.</li>
<li>Dry-run mode uses a distinct header and simulated badges so a demonstration cannot be mistaken for a
real lock.</li>
</ul>
<div class="note"><b>Reading the screenshots.</b> Figures 6.1 and 6.2 were captured from the current build.
The DSA screenshots in Section 2 and the exam screenshots below were captured in a temporary environment;
no personal account data, host entry or desktop process was touched.</div>
"""
pages.append(page(14, s6a, "Section 6 &middot; Interface"))

# ------------------------------------------------------- 15 section 6 part 2
s6b = """
<h3>6.2 Exam Preparation Workspace</h3>
<p>Figure 6.3 shows the workspace after a syllabus has been imported and approved. The header carries the
subject, course level, examination date, total marks and duration, while the tabs separate the syllabus,
notes, question bank, practice, mock examination, results and analytics. The topic tree on the left is the
same structure that gates generation; a topic that is not approved cannot silently become a question.</p>
""" + fig("fig-6-3-exam-workspace.png", "6.3", "Exam Preparation workspace with the syllabus tab and approved topic tree.", "150mm") + """
<h4>Workspace tabs and their evidence</h4>
""" + tbl(["Tab", "What the student can do", "Evidence produced"], [
    ["Syllabus", "Upload PDF/DOCX/TXT, edit units and topics, save a draft, approve", "Approved topic tree and source text"],
    ["Notes", "Generate very short, standard or detailed revision notes", "Source filename, topic reference, support status"],
    ["Question Bank", "Generate, edit, validate and save nine question types", "Normalized rows and a bank fingerprint"],
    ["Practice", "Choose topics, difficulty and count; answer with immediate feedback", "Scored practice session and per-question review"],
    ["Mock Exam", "Choose topics, difficulty, count, duration and target marks", "Timed session with a question snapshot"],
    ["Results", "Open submitted or in-progress sessions", "Score, accuracy, review count and per-topic breakdown"],
    ["Analytics", "Filter by 7 days, 30 days or all time", "Accuracy, mastery, trends, recommendations"],
], ["24mm", "78mm", "54mm"]) + """
<p class="small">Generation is gated by approval: before the syllabus is approved, the notes and question
actions remain unavailable. Saving an unchanged draft only refreshes the timestamp; changing the syllabus
revokes approval and empties the active bank.</p>
"""
pages.append(page(15, s6b, "Section 6 &middot; Interface"))

# ------------------------------------------------------- 16 section 6 part 3
s6c = """
<h3>6.3 Question Bank and Practice</h3>
<p>Figure 6.4 shows the question bank after generation from an approved syllabus. Each row carries its
unit, topic, type, difficulty, Bloom level, marks and source reference, and the bank can still be edited
before a session uses it. Figure 6.5 shows a topic-wise practice session: objective answers are scored
immediately with the awarded marks, the reference answer and an explanation, while written answers are
stored for later review.</p>
""" + fig("fig-6-4-question-bank.png", "6.4", "Editable question bank generated from an approved syllabus.", "122mm") + fig("fig-6-5-practice.png", "6.5", "Topic-wise practice session with immediate objective feedback.", "122mm") + """
<div class="note"><b>Why a validated bank matters.</b> A generated question is only useful if its type,
answer, marks, Bloom level and source topic are coherent. CodeLock rejects duplicate or malformed rows
before they reach a session, and it keeps the approved JSON as the editable source while normalized rows
support filtering and scoring.</div>
"""
pages.append(page(16, s6c, "Section 6 &middot; Interface"))

# ------------------------------------------------------- 17 section 6 part 4
s6d = """
<h3>6.4 Mock Results and Analytics</h3>
<p>Figure 6.6 shows a submitted mock examination with a per-topic breakdown: questions, correct, incorrect,
needs review, unanswered, marks, awarded marks and accuracy. Figure 6.7 shows the analytics dashboard with
stat cards, a topic table, a session-trend chart and recommendations. The range selector applies to every
element on the tab, so a seven-day view cannot mix in older sessions.</p>
""" + fig("fig-6-6-result.png", "6.6", "Mock examination result with a per-topic breakdown and answer review.", "112mm") + fig("fig-6-7-analytics.png", "6.7", "Analytics dashboard with mastery indicators and a topic recommendation.", "124mm") + """
<p class="small">The dashboard deliberately hides overall accuracy and trend results until at least five
graded answers exist. A recommendation appears only for a topic classified as <i>Needs Improvement</i>
with at least five graded answers; otherwise the topic is listed under evidence needed. This prevents a
single lucky or unlucky answer from being presented as a learning diagnosis.</p>
"""
pages.append(page(17, s6d, "Section 6 &middot; Interface"))

# ------------------------------------------------------- 18 section 7 part 1
s7a = """
<div class="kicker">Section 07</div>
<h2 class="sec">Local Data Design and Data Management</h2>
<div class="rule"></div>
<h3>7.1 Data Overview</h3>
<p>CodeLock uses one logical schema with two physical backends. SQLite is the default and requires no
server; Oracle 19c+ is optional and is used when a DSN and credentials are configured. The schema separates
account and progress data from exam content, and every exam table carries a student identifier so that a
query can enforce ownership rather than filtering in the interface after loading another student&rsquo;s
rows.</p>
<h3>7.2 Core Account and Progress Tables</h3>
""" + tbl(["Table", "Key columns", "Purpose"], [
    ["students", "id, username, display_name, password_hash, salt, created_at, last_login", "One row per account; username is unique and normalized"],
    ["progress", "student_id, track_key, current_index, completed, attempts, total_seconds, best_seconds", "One row per student and track; resumes the saved challenge"],
    ["attempts", "id, student_id, track_key, problem_key, duration_seconds, passed, tests_passed, tests_total", "One row per graded submission; supports history and best time"],
], ["24mm", "84mm", "48mm"]) + """
<h3>7.3 Exam Workspace and Session Tables</h3>
""" + tbl(["Table", "Key columns", "Purpose"], [
    ["exam_workspaces", "workspace_id, student_id, subject, course_level, exam_date, total_marks, duration_minutes, source_text, topics_json, notes_json, questions_json, fingerprint", "Workspace metadata and the editable source documents"],
    ["exam_questions", "question_id, workspace_id, student_id, unit_title, topic, type, difficulty, bloom_level, prompt, options_json, answer, source_quote", "Normalized question bank rows derived from approved JSON"],
    ["exam_sessions", "session_id, student_id, workspace_id, mode, status, blueprint_json, total_marks, score_marks, needs_review, duration_limit", "Practice or mock session with its configuration and result"],
    ["exam_responses", "response_id, session_id, question_id, student_answer, is_correct, awarded_marks, review_status, question_snapshot_json", "One row per session question, including the frozen snapshot"],
], ["26mm", "96mm", "34mm"]) + """
<h3>7.4 Storage Backends</h3>
""" + tbl(["Aspect", "SQLite (default)", "Oracle 19c+ (optional)"], [
    ["Setup", "Created automatically at data/codelock.db", "Run database/schema.sql and set three environment variables"],
    ["Sharing", "Per machine and per user account", "Shared across computers through the database"],
    ["Access control", "Anyone with file access can read or alter it", "Depends on the database account and network"],
    ["Use case", "Single-student local use and demonstrations", "Several computers that must share accounts and progress"],
], ["28mm", "66mm", "62mm"])
pages.append(page(18, s7a, "Section 7 &middot; Data Design"))

# ------------------------------------------------------- 19 section 7 part 2
s7b = """
<h3>7.5 Relational Model</h3>
<p>Figure 7.1 shows the seven tables and their relationships. The students table is the ownership root;
progress and attempts are keyed by student and track, while workspaces, questions, sessions and responses
fan out from a workspace. Sessions retain their own question snapshots so that editing the bank cannot
rewrite history.</p>
""" + fig("fig-7-1-data-model.svg", "7.1", "Relational data model shared by SQLite and Oracle.", "146mm") + """
<h3>7.6 Ownership, Isolation and Privacy</h3>
<p>Analytics and result queries filter by both student and workspace, so one account cannot read another
student&rsquo;s history even if it guesses an identifier. Passwords are stored only as PBKDF2-SHA256 hashes
with random salts. The SQLite file is not encrypted, and anyone with access to it can read or modify it;
the Oracle path is only as secure as the database account and network it is given. AI providers receive
only the extracted source excerpts needed for the selected topics, and API keys are read from environment
variables rather than written to the database. Remote providers should not be used with confidential
syllabus material; the local Ollama option keeps generation on the machine.</p>
<h3>7.7 Migration, Reset and Retention</h3>
<p>Fresh Oracle installations receive the exam tables from <span class="code">database/schema.sql</span>;
existing schemas apply migrations 001 and 002 once. SQLite creates its tables on first use. Deleting the
SQLite file resets all local accounts and content; changing <span class="code">CODELOCK_DB_PATH</span> or
<span class="code">CODELOCK_DATA_DIR</span> selects a different store. There is no automatic retention or
purge policy, so a deployment should decide how long student records are kept.</p>
<div class="note warn"><b>Data boundary.</b> Student answers and generated study material are personal
academic records. They should be collected only from students who know what is stored, where it is stored
and how to remove it.</div>
"""
pages.append(page(19, s7b, "Section 7 &middot; Data Design"))

# ------------------------------------------------------- 20 section 8
s8 = """
<div class="kicker">Section 08</div>
<h2 class="sec">Side-by-Side Comparison Tables</h2>
<div class="rule"></div>
<h3>8.1 Focus and Locking Approaches</h3>
""" + tbl(["Feature", "Manual willpower", "Browser extension", "CodeLock"], [
    ["Scope", "No enforcement", "Browser tabs and sites", "Hosts file plus seven desktop processes"],
    ["Unlock condition", "None", "Timer or a settings toggle", "All hidden tests pass and the student confirms"],
    ["Active session", "Self-managed", "Usually a timer", "Challenge-based; reward is 15 minutes"],
    ["Evidence", "None", "Usage summary", "Attempt history, elapsed time, pass/fail and tests passed"],
    ["Privilege", "None", "Browser permission", "One approved helper operation per hosts change"],
    ["Failure mode", "Distraction", "Disabled extension or a new browser", "Reports the observed state; does not claim a block"],
], ["28mm", "40mm", "42mm", "46mm"], cls="compact") + """
<h3>8.2 Coding Assessment Approaches</h3>
""" + tbl(["Aspect", "Sample-only checker", "Online judge", "CodeLock judge"], [
    ["Hidden tests", "No", "Usually", "24 to 38 generated cases per submission"],
    ["Expected answers in the worker", "Often present", "Server-side", "Never; the parent owns and compares them"],
    ["Forged verdict", "Possible", "Server-side", "Rejected by frame order, prefix and type checks"],
    ["Timeout", "Varies", "Server policy", "3 s overall and 2 s per case; process tree terminated"],
    ["Isolation claim", "None", "Server sandbox", "Separate interpreter and Job Object, explicitly not a sandbox"],
    ["Unlock coupling", "None", "None", "A pass still requires explicit confirmation"],
], ["34mm", "36mm", "38mm", "48mm"], cls="compact") + """
<h3>8.3 Exam Preparation Approaches</h3>
""" + tbl(["Feature", "Static notes", "General chat assistant", "CodeLock workspace"], [
    ["Syllabus grounding", "Manual", "Prompt-dependent", "Imported syllabus and approved topic tree"],
    ["Source reference", "Sometimes", "Rarely", "Filename, unit and topic on generated content"],
    ["Question validation", "Manual", "None", "Type, marks, answer, Bloom level and duplicate checks"],
    ["Practice and mock", "Separate tools", "Ad hoc", "Scored sessions with snapshots and auto-submit"],
    ["Analytics", "None", "None", "Accuracy, mastery, trends and evidence-based recommendations"],
    ["Unsupported topics", "May be omitted", "May be invented", "Marked as not specified in the source"],
], ["30mm", "34mm", "44mm", "48mm"], cls="compact") + """
<p class="small">These tables position the implemented feature set against common approaches. They do not
rank commercial products, and they do not claim that CodeLock is a replacement for an institutional
learning platform or a production online judge.</p>
"""
pages.append(page(20, s8, "Section 8 &middot; Comparisons"))

# ------------------------------------------------------- 21 section 9
s9 = """
<div class="kicker">Section 09</div>
<h2 class="sec">Research / Project Gap Analysis</h2>
<div class="rule"></div>
<p>The following gaps are stated in the project documentation or follow directly from the implemented
scope. They are not confirmed defects in unseen code; they identify what a larger deployment would need.</p>
""" + tbl(["Observed gap or constraint", "Implication", "Potential improvement"], [
    ["Real UAC approval, helper installation and hosts writes were not performed in development", "Windows enforcement is demonstrated, not certified", "Supervised pilot on a dedicated PC with an administrator present"],
    ["Hosts blocking can be bypassed by DNS-over-HTTPS, a VPN or direct IP access", "The block is a commitment device, not a firewall", "Add an OS firewall policy as a second layer"],
    ["The judge is not a security sandbox", "Hostile code must not be run", "Use a VM, AppContainer or Windows Sandbox for untrusted code"],
    ["Enforcement is Windows-first", "Linux blocking is limited without a privileged service", "Provide a platform-specific privileged service"],
    ["Oracle was verified through schema and fallback inspection, not a live instance", "The shared-database path is unproven at runtime", "Run a staging Oracle instance and a full integration test"],
    ["No manual marking screen for written answers", "Accuracy covers objective answers only", "Add a marking workflow and recompute accuracy"],
    ["No AI provider was used in the final check", "Generated notes and questions are demonstrated through stubs", "Evaluate a configured provider on a real syllabus"],
    ["No password-recovery flow", "A forgotten password means a new account or a manual row edit", "Add an administrator reset path"],
    ["Analytics are informational, not scheduled", "No spaced-repetition plan is produced", "Add a revision scheduler driven by mastery data"],
    ["SQLite is local to one machine", "Accounts do not sync by default", "Pilot the Oracle backend for a shared lab"],
], ["62mm", "60mm", "42mm"]) + """
<div class="note"><b>Priority reading.</b> The first two rows matter most for an honest evaluation: CodeLock
has not been certified against a real Windows hosts file in this environment, and no hosts-file block can
stop every network path. The project is designed to make those limits visible rather than to hide them.</div>
"""
pages.append(page(21, s9, "Section 9 &middot; Gap Analysis"))

# ------------------------------------------------------- 22 section 10
s10 = """
<div class="kicker">Section 10</div>
<h2 class="sec">Expected Outcomes and Evaluation Criteria</h2>
<div class="rule"></div>
<p>The project is evaluated on observable behaviour rather than on feature count. Each criterion below has
a corresponding check in the offline suite, the GUI smoke test, the mode flow harness or the dry-run
walkthrough.</p>
""" + tbl(["Area", "Expected result or criterion", "Evidence"], [
    ["Accounts", "Create and sign in; reject duplicate usernames and wrong passwords; store hashes only", "Self-test"],
    ["Mode chooser", "DSA first, Exam second; X blocked; closing Exam exits CodeLock", "23/23 flow harness"],
    ["DSA lock", "Apply the block, verify the observed state and report honestly when unavailable", "Dry run and simulated backends"],
    ["Judge", "All 15 reference solutions pass; wrong, malformed and forged submissions fail", "Self-test"],
    ["Hidden tests", "24 to 38 cases per submission; visible samples alone cannot unlock", "Self-test and dry run"],
    ["Reward", "15-minute countdown, auto-relock, next challenge loaded, editor reset", "Dry run"],
    ["Syllabus import", "TXT, DOCX and PDF extraction with the stated size, page and character bounds", "Self-test"],
    ["Approval gate", "Generation blocked before approval; a changed syllabus revokes approval", "Self-test"],
    ["Practice and mock", "Immediate objective feedback, timed auto-submit, frozen question snapshots", "Self-test and GUI smoke test"],
    ["Analytics", "Submitted sessions only; five-answer minimum; 7/30/all-time filters", "13/13 UI smoke test"],
    ["Persistence", "Progress resumes after restart; student and workspace isolation", "Self-test"],
    ["Build health", "py_compile clean; 227/228 self-tests; 13/13 UI; 23/23 flow", "Final offline check"],
], ["28mm", "94mm", "36mm"]) + """
<h3>Final Verification Summary</h3>
""" + tbl(["Command", "Result", "Scope"], [
    ["python -m py_compile", "Exit 0", "All Python modules"],
    ["python main.py --self-test", "227/227", "Hosts, helper, judge, problems, database, exam, analytics"],
    [".venv/bin/python.exe main.py --self-test", "228/228", "Adds the two pypdf PDF-extraction checks"],
    ["python main.py --self-test-ui", "13/13", "Analytics tab, filters, recommendation action"],
    ["Mode-chooser flow harness", "23/23", "Temporary database; no privileged operation"],
], ["62mm", "24mm", "72mm"]) + """
<p class="small">The suite was run on 2026-11-01 and the flow harness on 2026-11-02. The real hosts file was
hash-checked before and after and was not modified. A real UAC prompt was not approved, the helper was not
installed and no real desktop application was killed.</p>
"""
pages.append(page(22, s10, "Section 10 &middot; Evaluation"))

# ------------------------------------------------------- 23 section 11
s11 = """
<div class="kicker">Section 11</div>
<h2 class="sec">Limitations and Conclusion</h2>
<div class="rule"></div>
<h3>11.1 Limitations</h3>
<p>CodeLock is a compact academic prototype and a commitment device, not a prison or a security product.
It stops impulsive tab-switching and app-opening, not a determined user. Anyone with administrator rights
can edit the hosts file, replace the helper or uninstall Python. The window is topmost but not a
full-screen operating-system kiosk; Alt+Tab still works. Hosts blocking does not stop DNS-over-HTTPS, VPNs
or direct IP access, and force-killing CodeLock stops the process watchdog.</p>
<p>The judge runs as the same user in a separate interpreter with resource limits; it is not a security
sandbox. Student code can still attempt to read files or automate input, so hostile code must not be run.
The real UAC prompt, the <span class="code">%ProgramFiles%</span> installation, writes to the system hosts
file and desktop-process termination were not exercised in the development environment; the PowerShell
helper was tested against temporary files only. The Oracle backend and a live AI provider were not
executed. There is no OCR for scanned PDFs, no manual marking screen, no password recovery and no
spaced-repetition scheduler. Analytics accuracy covers auto-graded objective answers only, so a fully
marked paper could show a lower figure.</p>
<h3>11.2 What the Project Demonstrates</h3>
<p>The project demonstrates a complete, locally runnable loop in which a focus contract and a study
workspace share one account and one database. It shows a trusted-parent judge that resists forged verdicts
and type confusion, a privileged helper that is verified before every elevation, an exam pipeline that
keeps generated material tied to an approved syllabus, and an analytics layer that refuses to diagnose a
topic from too few answers. It also demonstrates a documentation discipline: the verified results and the
unverified boundaries are recorded separately.</p>
<h3>11.3 Conclusion</h3>
<p>CodeLock meets its stated goal: a student can sit down, choose Exam Preparation for measurable study or
DSA Practice for a locked coding session, and leave with a record of what was attempted. The two-mode
chooser makes the consequence of each choice explicit before any enforcement begins. The project is
small enough to inspect, honest about its limits and structured so that the next step, a supervised pilot
on a real Windows machine, can be evaluated without changing the core design.</p>
<h3>11.4 Future Work</h3>
<ul class="tight">
<li>Run a supervised Windows pilot covering real UAC approval, helper installation and a verified restore.</li>
<li>Add a marking screen and a mastery-aware revision scheduler.</li>
<li>Evaluate a configured AI provider on real syllabi and add a content-quality rubric.</li>
<li>Pilot the Oracle backend in a shared lab and add account recovery.</li>
<li>Add an OS firewall layer for network paths that hosts blocking cannot cover.</li>
</ul>
"""
pages.append(page(23, s11, "Section 11 &middot; Limitations"))

# ------------------------------------------------------- 24 section 12
s12 = """
<div class="kicker">Section 12</div>
<h2 class="sec">References and Appendices</h2>
<div class="rule"></div>
<h3>References</h3>
<ol class="tight small">
<li>CodeLock project README and final submission report, submitted with the source folder (setup, features, verification and limitations).</li>
<li>Python Software Foundation. <i>The Python Tutorial</i> and <i>Python Standard Library</i>. https://docs.python.org/3/</li>
<li>Python Software Foundation. <i>tkinter &mdash; Python interface to Tcl/Tk</i>. https://docs.python.org/3/library/tkinter.html</li>
<li>pypdf contributors. <i>pypdf documentation</i>. https://pypdf.readthedocs.io/</li>
<li>psutil contributors. <i>psutil documentation</i>. https://psutil.readthedocs.io/</li>
<li>Oracle. <i>python-oracledb documentation</i>. https://python-oracledb.readthedocs.io/</li>
<li>SQLite. <i>SQLite Documentation</i>. https://www.sqlite.org/docs.html</li>
<li>Microsoft. <i>File.Replace Method</i>. https://learn.microsoft.com/dotnet/api/system.io.file.replace</li>
<li>Moriarty, K. (Ed.). <i>RFC 8018: PKCS #5: Password-Based Cryptography Specification Version 2.1</i>. https://www.rfc-editor.org/rfc/rfc8018</li>
<li>OWASP. <i>Password Storage Cheat Sheet</i>. https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html</li>
</ol>
<h3>Appendix A: Project Folder Structure</h3>
""" + tbl(["File or folder", "Purpose"], [
    ["main.py", "Entry point, command-line flags, restore, self-test and UI smoke test"],
    ["codelock/gui.py", "Kiosk window, sign-in, mode chooser, watchdog, reward timer"],
    ["codelock/judge.py", "Subprocess harness, strict protocol, timeout and worker cleanup"],
    ["codelock/problems.py", "Track registry, 15 challenges and hidden-test generators"],
    ["codelock/exam_ui.py; exam_runner.py", "Workspace tabs and practice/mock runner windows"],
    ["codelock/exam_engine.py; exam_analytics.py", "Question selection, scoring, mastery and trends"],
    ["codelock/db.py", "Accounts, progress, exam rows, SQLite and Oracle backends"],
    ["codelock/hosts_helper.ps1; hosts_elevation.py", "Fixed elevated helper and one-shot verification/UAC client"],
    ["codelock/selftest.py; ui_smoke.py", "Offline verification and temporary-database GUI smoke test"],
    ["database/schema.sql; database/migrations/", "Oracle student and exam schema, view and PL/SQL package"],
    ["tools/install_hosts_helper.ps1", "Administrator installer, manifest writer and ACL setup"],
], ["62mm", "92mm"]) + """
<h3>Appendix B: Submission Note</h3>
<p class="small">The complete source folder, this report and the documentation files are submitted together.
Section 13 records the source inventory and the verified backup snapshot. The project does not include a
public repository URL because none was configured at the time of writing.</p>
"""
pages.append(page(24, s12, "Section 12 &middot; References"))

# ------------------------------------------------------- 25 section 13
s13 = """
<div class="kicker">Section 13</div>
<h2 class="sec">GitHub Proof and Source Inventory</h2>
<div class="rule"></div>
<h3>13.1 Status of the Repository Proof</h3>
<p><b>No public GitHub repository has been configured for CodeLock at the time of writing.</b> The
repository field is therefore left without a URL rather than populated with a link that does not resolve.
The equivalent proof is the submitted project folder itself, a verified backup snapshot and the offline
verification record below. A reviewer can reproduce the checks from the folder without network access.</p>
""" + tbl(["Evidence item", "What it contains", "Result"], [
    ["Submitted folder and backup", "Source, 19 modules, helper, schema, documentation and a dated snapshot; SHA-256 manifest of every file", "46/46 verified"],
    ["Offline self-test", "Hosts, helper, judge, problems, database, exam and analytics checks", "227/227 and 228/228"],
    ["UI smoke test", "Analytics tab, range filters and recommendation action", "13/13"],
    ["Mode flow harness", "Exam and DSA paths in a temporary database", "23/23"],
], ["38mm", "96mm", "24mm"]) + fig("fig-13-1-verification.svg", "13.1", "Final offline verification summary from the submitted build.", "112mm") + """
<h3>13.2 Source Inventory</h3>
""" + tbl(["File", "Lines", "Role"], [
    ["main.py", "207", "Entry point and command-line operations"],
    ["codelock/gui.py", "1,878", "Kiosk window, sign-in, mode chooser, watchdog"],
    ["codelock/exam_ui.py", "1,736", "Seven-tab exam workspace"],
    ["codelock/db.py", "1,796", "Accounts, progress, exam rows and both backends"],
    ["codelock/selftest.py", "2,922", "Offline verification suite"],
    ["codelock/judge.py, problems.py", "1,806", "Grading protocol, challenge bank and hidden tests"],
    ["codelock/hosts_elevation.py, hosts_helper.ps1", "1,937", "Helper verification, UAC client, recovery and the fixed helper"],
    ["Other modules and SQL", "4,288", "Exam, analytics, charts, AI, installer and schema"],
], ["64mm", "18mm", "74mm"], [1]) + """
<div class="note"><b>What is verified.</b> In the submitted folder, py_compile exited 0, the self-test passed
227 checks with system Python and 228 through the virtual environment, the UI smoke test passed 13/13, and the
mode flow harness passed 23/23. The hosts file was hash-checked before and after: it was not modified, and no
UAC prompt or helper installation was performed.</div>
"""
pages.append(page(25, s13, "Section 13 &middot; Source Proof"))

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CodeLock Project Report</title>
<style>{CSS}</style>
</head>
<body>
{''.join(pages)}
</body>
</html>
"""

HTML.write_text(html, encoding="utf-8")
print(f"wrote {HTML} ({len(pages)} pages)")
