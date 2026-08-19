from __future__ import annotations

import os
import re
import time
from typing import Any
from urllib.parse import urlparse

from agents import Agent, ModelSettings, Runner
from ddgs import DDGS

from agentie.core.observability import current_trace_id, record_event, record_model_error, record_model_result
from agentie.models.provider import get_model, get_provider_info


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
        ("deep", r"^(?:please\s+)?(?:deep\s+search|deeper\s+search|deep\s+research|research deeply|investigate deeply)\s+(?:for|about|on)?\s*(.+)$"),
        ("web", r"^(?:please\s+)?(?:search|search the web|web search|search online|look up online|find online)\s+(?:for|about|on)?\s*(.+)$"),
    ]
    for mode, pattern in patterns:
        m = re.match(pattern, text, re.I)
        if m and m.group(1).strip():
            return mode, m.group(1).strip(" .?!")
    return None


def parse_research_command(message: str) -> tuple[str, str] | None:
    return _clean_query(message)


def sources_only_requested(message: str) -> bool:
    text = re.sub(r"\s+", " ", str(message or "").strip()).lower()
    return bool(re.search(r"\b(sources only|links only|results only|just (?:the )?(?:sources|links|results)|do not summarize|don't summarize|no summary)\b", text))


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


def source_card(query: str, sources: list[dict[str, Any]], answer: str = "", provider_calls: int = 0) -> dict[str, Any]:
    return {
        "type": "web_search",
        "query": query,
        "answer": answer,
        "sources": sources,
        "provider_calls": provider_calls,
    }


async def answer_web_search(query: str, max_results: int = 8) -> dict[str, Any]:
    sources = search_sources(query, max_results)
    if not sources:
        return {
            "message": "I couldn't retrieve usable web results for that search.",
            "card": source_card(query, [], "", 0),
        }

    source_pack = "\n\n".join(
        f"[{s['id']}] {s['title']}\nURL: {s['url']}\nSnippet: {s['snippet']}" for s in sources
    )
    instructions = (
        "You are Agentie's isolated web-search synthesizer. Answer only from the supplied search-result evidence. "
        "Give the useful answer first, not a description of the search. Cite every externally grounded factual claim "
        "with source IDs like [S1] or [S2][S4]. Never invent source IDs, facts, or URLs. If snippets are insufficient "
        "for a claim, say so. Keep the answer concise unless the query asks for depth. Do not use tools, memory, or "
        "conversation history. Do not add a separate Sources section because the UI renders the source list below."
    )
    prompt = f"USER SEARCH\n{query}\n\nSEARCH RESULTS\n{source_pack}"
    provider = get_provider_info()
    model_name = provider["model"]
    trace_id = current_trace_id()
    record_event("provider", provider["provider"], metadata={"model": model_name, "purpose": "web_search_synthesis"}, trace_id=trace_id)
    started = time.perf_counter()
    try:
        agent = Agent(
            name="Agentie Web Search",
            instructions=instructions,
            model=get_model(),
            model_settings=_settings(),
            tools=[],
        )
        result = await Runner.run(agent, prompt)
        latency_ms = (time.perf_counter() - started) * 1000
        accounting = record_model_result(result, model_name, latency_ms, trace_id)
        answer = str(result.final_output).strip()
        return {
            "message": "",
            "card": source_card(query, sources, answer, int(accounting.get("provider_calls") or 1)),
        }
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        record_model_error(model_name, exc, latency_ms, trace_id)
        raise
