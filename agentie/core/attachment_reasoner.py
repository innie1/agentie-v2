import os
import time
from typing import Any

from agents import Agent, ModelSettings, Runner

from agentie.core.file_service import extract_text, inspect_file, resolve_upload
from agentie.models.provider import get_model


MAX_ATTACHMENT_CONTEXT_CHARS = 32_000


def _settings() -> ModelSettings:
    value = int(os.getenv("AGENTIE_MAX_OUTPUT_TOKENS", "4096"))
    return ModelSettings(max_tokens=max(256, min(value, 8192)))


def prepare_documents(filenames: list[str]) -> tuple[list[dict[str, Any]], str]:
    """Inspect and extract user-selected uploads without touching chat routing state."""
    cards: list[dict[str, Any]] = []
    sections: list[str] = []
    remaining = MAX_ATTACHMENT_CONTEXT_CHARS

    for raw_name in filenames[:8]:
        path = resolve_upload(raw_name)
        card = inspect_file(path)
        cards.append(card)

        lines = [
            "DOCUMENT METADATA",
            f"Filename: {card.get('name', path.name)}",
            f"Type: {card.get('kind') or card.get('suffix') or 'file'}",
            f"Size bytes: {card.get('size_bytes', path.stat().st_size)}",
        ]
        if card.get("pages") is not None:
            lines.append(f"Page count: {card['pages']}")
        if card.get("inspection_error"):
            lines.append(f"Inspection error: {card['inspection_error']}")
            sections.append("\n".join(lines))
            continue

        try:
            extracted = extract_text(path)
            text = str(extracted.get("text") or "").strip()
        except Exception as exc:
            lines.append(f"Text extraction error: {exc}")
            sections.append("\n".join(lines))
            continue

        if not text:
            lines.append("Document content: [No extractable text found]")
            sections.append("\n".join(lines))
            continue

        if remaining <= 0:
            lines.append("Document content: [Context limit reached before this document]")
            sections.append("\n".join(lines))
            continue

        chunk = text[:remaining]
        remaining -= len(chunk)
        lines.extend(["", "DOCUMENT CONTENT", chunk])
        if len(chunk) < len(text):
            lines.append("\n[Document content truncated locally to stay within the attachment context budget]")
        sections.append("\n".join(lines))

    return cards, "\n\n--- DOCUMENT BREAK ---\n\n".join(sections)


async def reason_about_documents(question: str, filenames: list[str]) -> tuple[list[dict[str, Any]], str]:
    """Answer only from locally prepared attachment content using a tool-less model."""
    cards, context = prepare_documents(filenames)
    readable = "DOCUMENT CONTENT" in context and "[No extractable text found]" not in context
    if not readable:
        return cards, "I could inspect the attachment metadata, but I couldn't extract readable text to answer that request."

    instructions = (
        "You are Agentie's isolated attachment reader. Answer only from the supplied document metadata and content. "
        "Do not use conversation history, memory, roles, tools, workspace listings, clocks, routines, or outside knowledge. "
        "Never claim a file was modified. Follow the user's requested format exactly. If the supplied content is insufficient, say so clearly."
    )
    prompt = f"USER REQUEST\n{question.strip()}\n\n{context}"
    agent = Agent(
        name="Agentie Attachment Reader",
        instructions=instructions,
        model=get_model(),
        model_settings=_settings(),
        tools=[],
    )
    result = await Runner.run(agent, prompt)
    return cards, str(result.final_output).strip()
