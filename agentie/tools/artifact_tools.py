import json

from agents import function_tool

from agentie.core.office_artifacts import create_docx, create_pptx, create_xlsx


@function_tool
def create_word_document(content: str, filename: str = "") -> str:
    """Create a downloadable DOCX file locally from text or markdown content."""
    return json.dumps(create_docx(content, filename or None), ensure_ascii=False)


@function_tool
def create_excel_workbook(content: str, filename: str = "") -> str:
    """Create a downloadable XLSX workbook locally from CSV-like, markdown-table, or plain text content."""
    return json.dumps(create_xlsx(content, filename or None), ensure_ascii=False)


@function_tool
def create_powerpoint_presentation(content: str, filename: str = "") -> str:
    """Create a downloadable PPTX presentation locally from structured text or markdown content."""
    return json.dumps(create_pptx(content, filename or None), ensure_ascii=False)
