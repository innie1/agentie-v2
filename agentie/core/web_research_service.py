from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse

from agents import Agent, ModelSettings, Runner
from ddgs import DDGS

from agentie.models.provider import get_model


def _settings() -> ModelSettings:
    raw = int(os.getenv("AGENTIE_MAX_OUTPUT_TOKENS", "4096"))
    return ModelSettings(max_tokens=max(256, min(raw, 4096)))


def _domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _clean_query(message: str) -> tuple[str, str] | None:
    text = re.sub(r"\s+", " ", str(message or "").strip())
    patterns = [
        ("deep", r"^(?:please\s+)?(?:deep\s+search|deep\s+research|research deeply|investigate deeply)\s+(?:for|about|on)?\s*(.+)$"),
        ("web", r"^(?:please\s+)?(?:search|search the web|web search|look up online|find online)\s+(?:for|about|on)?\s*(.+)$"),
    ]
    for mode, pattern in patterns:
        m = re.match(pattern, text, re.I)
        if m and m.group(1).strip():
            return mode, m.group(1).strip(" .?!")
    return None


def parse_research_command(message: str) -> tuple[str, str] | None:
    return _clean_query(message)


def search_sources(query: str, max_results: int = 8) -> list[dict[str, Any]]:
    limit = max(1, min(int(max_results), 10))
    rows = DDGS(timeout=12).text(query, safesearch="moderate", max_results=limit, backend="auto")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in rows or []:
        url = str(item.get("href") or item.get("url") or "").strip()
        if not url:
            continue
        canonical = url.split("#", 1)[0].rstrip("/")
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append({
            "id": f"S{len(out)+1}",
            "title": str(item.get("title") or url).strip(),
            "url": url,
            "domain": _domain(url),
            "snippet": str(item.get("body") or item.get("snippet") or "").strip(),
        })
        if len(out) >= limit:
            break
    return out


async def answer_web_search(query: str, max_results: int = 8) -> dict[str, Any]:
    sources = search_sources(query, max_results)
    if not sources:
        return {
            "message": "I couldn't retrieve usable web results for that search.",
            "card": {"type": "web_search", "query": query, "sources": [], "answer": ""},
        }

    source_pack = "\n\n".join(
        f"[{s['id']}] {s['title']}\nURL: {s['url']}\nSnippet: {s['snippet']}" for s in sources
    )
    instructions = (
        "You are Agentie's isolated web-search synthesizer. Answer only from the supplied search-result evidence. "
        "Use compact factual prose. Cite every externally grounded factual claim with source IDs like [S1] or [S2][S4]. "
        "Never invent source IDs or URLs. If snippets are insufficient for a claim, say so. Do not use tools or conversation memory."
    )
    prompt = f"USER SEARCH\n{query}\n\nSEARCH RESULTS\n{source_pack}"
    agent = Agent(
        name="Agentie Web Search",
        instructions=instructions,
        model=get_model(),
        model_settings=_settings(),
        tools=[],
    )
    result = await Runner.run(agent, prompt)
    answer = str(result.final_output).strip()
    return {
        "message": "",
        "card": {
            "type": "web_search",
            "query": query,
            "answer": answer,
            "sources": sources,
            "provider_calls": 1,
        },
    }
