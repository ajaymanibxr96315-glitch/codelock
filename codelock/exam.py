"""Exam preparation foundations: safe document extraction and syllabus topics."""

from __future__ import annotations

import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_EXTRACTED_CHARS = 500_000
MAX_PDF_PAGES = 500
_UNIT = re.compile(r"^\s*(?:unit|module)\s+([\wIVXLCDM-]+)\s*[:.\-–—]?\s*(.*)$", re.I)
_CHAPTER = re.compile(r"^\s*(?:chapter|chap\.?|section)\s+([\wIVXLCDM.-]+)\s*[:.\-–—]?\s*(.*)$", re.I)
_LEADER = re.compile(r"^\s*(?:(?:\d+(?:\.\d+)*|[A-Z])\s*[).:-]|[-*•▪◦])\s*")
_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocumentError(ValueError):
    """A document cannot be safely extracted or parsed."""


def _load_pypdf_module():
    """Import pypdf, falling back to the project virtualenv when available.

    Launchers that use a system Python cannot see packages installed only in
    ``.venv``; appending that site-packages keeps PDF uploads working either way.
    """
    try:
        import pypdf
        return pypdf
    except ImportError as direct_error:
        project_root = Path(__file__).resolve().parent.parent
        candidates = list((project_root / ".venv" / "lib").glob("*/site-packages"))
        candidates.append(project_root / ".venv" / "Lib" / "site-packages")
        for site_packages in candidates:
            if not (site_packages / "pypdf").is_dir():
                continue
            if str(site_packages) not in sys.path:
                sys.path.append(str(site_packages))
            try:
                import pypdf
                return pypdf
            except ImportError:
                continue
        raise DocumentError(
            "PDF support is unavailable. Install pypdf with "
            "'python -m pip install pypdf', or start CodeLock with "
            "run_codelock.bat so the project virtualenv is used."
        ) from direct_error


@dataclass(frozen=True)
class ExtractedDocument:
    filename: str
    text: str
    page_count: int | None
    scanned_suspected: bool


def extract_document(path: str | Path) -> ExtractedDocument:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".doc":
        raise DocumentError(
            "Legacy .doc files are not supported. Save the document as .docx or PDF, then upload it."
        )
    if suffix not in {".pdf", ".docx", ".txt"}:
        raise DocumentError("Choose a PDF, Word (.docx), or TXT file.")
    try:
        size = file_path.stat().st_size
    except OSError as exc:
        raise DocumentError(f"Could not read the selected file: {exc}") from exc
    if size > MAX_DOCUMENT_BYTES:
        raise DocumentError("The selected document is larger than the 20 MiB limit.")
    if size == 0:
        raise DocumentError("The selected document is empty.")

    page_count: int | None = None
    try:
        if suffix == ".txt":
            raw = file_path.read_bytes()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("cp1252")
        elif suffix == ".docx":
            text = _extract_docx(file_path)
        else:
            pypdf = _load_pypdf_module()
            reader = pypdf.PdfReader(str(file_path), strict=False)
            if reader.is_encrypted:
                raise DocumentError("Encrypted PDFs are not supported.")
            page_count = len(reader.pages)
            if page_count > MAX_PDF_PAGES:
                raise DocumentError(f"PDF has more than {MAX_PDF_PAGES} pages.")
            parts: list[str] = []
            total = 0
            for page in reader.pages:
                page_text = page.extract_text() or ""
                total += len(page_text)
                if total > MAX_EXTRACTED_CHARS:
                    raise DocumentError("Extracted text exceeds the 500,000 character limit.")
                parts.append(page_text)
            text = "\n\n".join(parts)
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError(f"Could not extract {suffix[1:].upper()} text: {exc}") from exc

    text = _clean_text(text)
    if len(text) > MAX_EXTRACTED_CHARS:
        raise DocumentError("Extracted text exceeds the 500,000 character limit.")
    if not text.strip():
        if suffix == ".pdf":
            raise DocumentError(
                "No selectable text was found. This PDF is likely scanned or image-only; "
                "OCR is not configured. Use a text-based PDF or OCR the document first."
            )
        raise DocumentError("No text was found in the selected document.")
    words = re.findall(r"[A-Za-z]{2,}", text)
    scanned = suffix == ".pdf" and (len(words) < 12 or len(text) < 80)
    return ExtractedDocument(file_path.name, text, page_count, scanned)


def _extract_docx(path: Path) -> str:
    """Extract body paragraphs and table cells without a native DOCX dependency."""
    with zipfile.ZipFile(path) as archive:
        try:
            member = archive.getinfo("word/document.xml")
            if member.file_size > 10 * 1024 * 1024:
                raise DocumentError("The DOCX document body exceeds the 10 MiB extraction limit.")
            xml = archive.read(member)
        except KeyError as exc:
            raise DocumentError("The DOCX package has no document body.") from exc
    root = ElementTree.fromstring(xml)
    body = root.find(f"{_WORD_NS}body")
    if body is None:
        return ""
    chunks: list[str] = []
    for paragraph in body.iter(f"{_WORD_NS}p"):
        value = "".join(node.text or "" for node in paragraph.iter(f"{_WORD_NS}t"))
        if value.strip():
            chunks.append(value)
    return "\n".join(chunks)


def _clean_text(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def extract_topics(text: str) -> list[dict[str, object]]:
    """Create a conservative editable unit/topic outline from headings and lines."""
    units: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or len(line) > 240:
            continue
        unit_match = _UNIT.match(line)
        if unit_match:
            title = " ".join(part for part in (unit_match.group(1), unit_match.group(2)) if part).strip()
            current = {"title": f"Unit {title}".strip(), "topics": []}
            units.append(current)
            continue
        chapter_match = _CHAPTER.match(line)
        if chapter_match:
            if current is None:
                current = {"title": "Unit 1", "topics": []}
                units.append(current)
            chapter = " ".join(part for part in chapter_match.groups() if part).strip()
            _append_topic(current, f"Chapter {chapter}".strip())
            continue
        if current is None:
            current = {"title": "Extracted topics", "topics": []}
            units.append(current)
        candidate = _LEADER.sub("", line).strip()
        candidate = re.sub(r"\s*[:;]+$", "", candidate)
        if len(candidate) >= 2 and not re.fullmatch(r"\d+", candidate):
            _append_topic(current, candidate)

    if not units:
        return [{"title": "Unit 1", "topics": []}]
    return units


def _append_topic(unit: dict[str, object], topic: str) -> None:
    topics = unit["topics"]
    assert isinstance(topics, list)
    normalized = topic.casefold()
    if all(str(existing).casefold() != normalized for existing in topics):
        topics.append(topic)


def validate_topic_tree(
    units: list[dict[str, object]], require_topics: bool = True
) -> list[dict[str, object]]:
    if not isinstance(units, list) or len(units) > 100:
        raise DocumentError("Syllabus must contain between 1 and 100 units.")
    cleaned: list[dict[str, object]] = []
    topic_count = 0
    for unit in units:
        if not isinstance(unit, dict):
            raise DocumentError("Each syllabus unit must be an editable unit record.")
        title = str(unit.get("title", "")).strip()
        topics = unit.get("topics", [])
        if not title or len(title) > 160 or not isinstance(topics, list):
            raise DocumentError("Unit titles must be 1–160 characters and topics must be a list.")
        normalized_topics = []
        for topic in topics:
            value = str(topic).strip()
            if not value or len(value) > 240:
                raise DocumentError("Topic text must be 1–240 characters.")
            normalized_topics.append(value)
        topic_count += len(normalized_topics)
        cleaned.append({"title": title, "topics": normalized_topics})
    if topic_count > 1000:
        raise DocumentError("Syllabus cannot contain more than 1,000 topics.")
    if not cleaned:
        raise DocumentError("Add at least one unit before saving the syllabus.")
    if require_topics and topic_count == 0:
        raise DocumentError("Add at least one topic before approving the syllabus.")
    return cleaned
