import html
import re
from datetime import datetime
from pathlib import Path

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from agentie.core.file_service import UPLOADS, inspect_file, unique_path
from agentie.core.memory_store import latest_assistant_text


_PDF_INTENT_RE = re.compile(r"\b(?:create|make|generate|export|save|turn|convert)\b.*\bpdf\b|\bpdf\b.*\b(?:create|make|generate|export|save|turn|convert)\b", re.I)
_REFERENCE_RE = re.compile(r"\b(?:this|that|it|the previous answer|previous answer|last answer|above|what you just wrote|what you wrote)\b", re.I)


def _clean_filename(name: str | None) -> str:
    if not name:
        return f"agentie-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.pdf"
    value = Path(name.strip()).name
    if not value.lower().endswith('.pdf'):
        value += '.pdf'
    return re.sub(r"[^A-Za-z0-9._ -]+", "-", value)[:160] or "agentie-report.pdf"


def _extract_filename(message: str) -> str | None:
    match = re.search(r"\b(?:called|named|as)\s+[\"']?([^\"']+?\.pdf)\b", message, re.I)
    if match:
        return match.group(1).strip()
    return None


def _explicit_content(message: str) -> str | None:
    match = re.search(r"\b(?:with|using|from)\s+(?:the\s+)?(?:text|content)\s*[:\-]?\s*(.+)$", message, re.I | re.S)
    if match:
        value = match.group(1).strip()
        if value and not _REFERENCE_RE.fullmatch(value.strip(" .?!\"'")):
            return value.strip(" \"'")
    return None


def _markdown_inline(text: str) -> str:
    value = html.escape(text)
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"__(.+?)__", r"<b>\1</b>", value)
    value = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", value)
    value = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", value)
    return value


def create_pdf(content: str, filename: str | None = None) -> dict:
    if not content or not content.strip():
        raise ValueError("PDF content is empty.")
    UPLOADS.mkdir(parents=True, exist_ok=True)
    path = unique_path(_clean_filename(filename))

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('AgentieTitle', parent=styles['Title'], alignment=TA_CENTER, spaceAfter=10)
    h1 = ParagraphStyle('AgentieH1', parent=styles['Heading1'], spaceBefore=8, spaceAfter=5)
    h2 = ParagraphStyle('AgentieH2', parent=styles['Heading2'], spaceBefore=7, spaceAfter=4)
    body = ParagraphStyle('AgentieBody', parent=styles['BodyText'], leading=15, spaceAfter=6)
    bullet = ParagraphStyle('AgentieBullet', parent=body, leftIndent=13, firstLineIndent=-7)

    doc = SimpleDocTemplate(
        str(path), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=path.stem.replace('-', ' ').title(), author='Agentie',
    )
    story = []
    lines = content.replace('\r\n', '\n').split('\n')
    title_used = False
    for raw in lines:
        line = raw.strip()
        if not line:
            story.append(Spacer(1, 4))
            continue
        if line.startswith('### '):
            story.append(Paragraph(_markdown_inline(line[4:]), h2))
        elif line.startswith('## '):
            story.append(Paragraph(_markdown_inline(line[3:]), h2))
        elif line.startswith('# '):
            style = title_style if not title_used else h1
            story.append(Paragraph(_markdown_inline(line[2:]), style)); title_used = True
        elif re.match(r"^[-*]\s+", line):
            story.append(Paragraph('• ' + _markdown_inline(re.sub(r"^[-*]\s+", '', line)), bullet))
        elif re.match(r"^\d+[.)]\s+", line):
            story.append(Paragraph(_markdown_inline(line), bullet))
        else:
            story.append(Paragraph(_markdown_inline(line), body))
    if not story:
        story.append(Paragraph(_markdown_inline(content), body))
    doc.build(story)
    return inspect_file(path)


def try_pdf_request(session_id: str, message: str) -> dict | None:
    """Handle deterministic PDF creation locally, including references to the previous answer."""
    if not _PDF_INTENT_RE.search(message):
        return None

    filename = _extract_filename(message)
    content = _explicit_content(message)
    if content is None and (_REFERENCE_RE.search(message) or len(message.split()) <= 12):
        content = latest_assistant_text(session_id, max_chars=40000)

    if not content:
        return {
            "message": "What should I put in the PDF? You can paste the content or say “use the previous answer.”",
            "card": None,
            "needs_content": True,
        }

    card = create_pdf(content, filename)
    return {"message": f"Created {card['name']}.", "card": card, "needs_content": False}
