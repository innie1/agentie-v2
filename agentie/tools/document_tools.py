import csv
import io
from pathlib import Path

from agents import function_tool
from pypdf import PdfReader

WORKSPACE_DIR = Path.cwd() / "workspace"


def _safe_path(filename: str) -> Path:
    safe_name = Path(filename).name.strip()
    if not safe_name:
        raise ValueError("A filename is required.")
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    return WORKSPACE_DIR / safe_name


@function_tool
def read_pdf(filename: str) -> str:
    """Extract text from a PDF stored in Agentie's workspace."""
    target = _safe_path(filename)
    if not target.exists():
        raise FileNotFoundError(target.name)
    reader = PdfReader(str(target))
    pages: list[str] = []
    for index, page in enumerate(reader.pages[:100]):
        text = page.extract_text() or ""
        pages.append(f"--- Page {index + 1} ---\n{text}")
    return "\n\n".join(pages)[:50000]


@function_tool
def read_csv(filename: str, max_rows: int = 100) -> str:
    """Read a CSV file from Agentie's workspace and return rows as text."""
    target = _safe_path(filename)
    if not target.exists():
        raise FileNotFoundError(target.name)
    text = target.read_text(encoding="utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))[: max(1, min(max_rows, 500))]
    return "\n".join(" | ".join(row) for row in rows)[:30000]
