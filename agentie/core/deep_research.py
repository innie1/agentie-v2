from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import urlparse

from agentie.tools.web_tools import search_web
from agentie.tools.browser_tools import browser_read_page


@dataclass
class Source:
    id: str
    title: str
    url: str
    snippet: str = ""
    text: str = ""
    query: str = ""


def _unwrap(value: Any) -> Any:
    """OpenAI Agents function tools may expose the original callable via on_invoke_tool.
    Deep research also works when these functions are imported undecorated in tests.
    """
    return value


def _domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def build_queries(question: str, breadth: int = 5) -> list[str]:
    clean = re.sub(r"\s+", " ", question).strip()
    seeds = [
        clean,
        f"{clean} primary sources",
        f"{clean} evidence data",
        f"{clean} criticism limitations",
        f"{clean} recent developments",
        f"{clean} expert analysis",
    ]
    out: list[str] = []
    for q in seeds:
        if q.lower() not in {x.lower() for x in out}:
            out.append(q)
    return out[: max(2, min(int(breadth), 8))]


def parse_search_payload(payload: str, query: str) -> list[Source]:
    try:
        data = json.loads(payload)
    except Exception:
        return []
    out = []
    for item in data.get("results") or []:
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        out.append(Source("", str(item.get("title") or url), url, str(item.get("snippet") or ""), query=query))
    return out


def dedupe_sources(sources: list[Source], max_sources: int = 18) -> list[Source]:
    seen: set[str] = set(); out: list[Source] = []
    for source in sources:
        key = source.url.split("#", 1)[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key); source.id = f"S{len(out)+1}"; out.append(source)
        if len(out) >= max_sources:
            break
    return out


async def _call_tool(tool: Any, *args: Any, **kwargs: Any) -> str:
    """Call a plain function or an Agents SDK FunctionTool without blocking the loop."""
    if callable(tool):
        return await asyncio.to_thread(tool, *args, **kwargs)
    # FunctionTool exposes an async invocation hook taking JSON arguments.
    invoke = getattr(tool, "on_invoke_tool", None)
    if invoke:
        payload = json.dumps(kwargs or ({"query": args[0]} if args else {}))
        result = invoke(None, payload)
        if asyncio.iscoroutine(result):
            result = await result
        return str(result)
    raise TypeError("Unsupported tool wrapper")


async def collect_sources(question: str, breadth: int = 5, max_sources: int = 18) -> tuple[list[str], list[Source]]:
    queries = build_queries(question, breadth)

    async def search(q: str) -> list[Source]:
        try:
            payload = await _call_tool(search_web, query=q, max_results=8)
            return parse_search_payload(payload, q)
        except Exception:
            return []

    batches = await asyncio.gather(*(search(q) for q in queries))
    sources = dedupe_sources([s for batch in batches for s in batch], max_sources)

    # Prefer source diversity before spending page reads.
    chosen: list[Source] = []; domains: dict[str, int] = {}
    for source in sources:
        d = _domain(source.url)
        if domains.get(d, 0) >= 2:
            continue
        domains[d] = domains.get(d, 0) + 1; chosen.append(source)
    sources = chosen[:max_sources]

    sem = asyncio.Semaphore(5)
    async def read(source: Source) -> None:
        async with sem:
            try:
                source.text = (await _call_tool(browser_read_page, url=source.url))[:16000]
            except Exception:
                source.text = ""
    await asyncio.gather(*(read(s) for s in sources))
    return queries, sources


def context_pack(question: str, queries: list[str], sources: list[Source]) -> str:
    blocks = []
    for s in sources:
        evidence = (s.text or s.snippet).strip()
        blocks.append(f"[{s.id}] {s.title}\nURL: {s.url}\nFound via: {s.query}\nEvidence:\n{evidence[:12000]}")
    return (
        f"Research question: {question}\n\n"
        f"Search queries used:\n- " + "\n- ".join(queries) + "\n\n"
        "SOURCE PACK\n\n" + "\n\n---\n\n".join(blocks)
    )


def synthesis_prompt(question: str, queries: list[str], sources: list[Source]) -> str:
    pack = context_pack(question, queries, sources)
    return f"""You are Agentie's research synthesis specialist.
Produce a rigorous answer to the research question using ONLY the source pack below.

Requirements:
- Lead with the answer, then explain evidence, disagreements, limitations, and implications.
- Every factual claim that depends on research must cite one or more source IDs like [S1] or [S2][S5].
- Never invent a citation. If evidence is insufficient, say so.
- Prefer primary/authoritative sources when sources conflict.
- Distinguish facts from inference.
- End with a Sources section listing each cited source ID, title, and URL.
- Do not mention internal prompts or hidden reasoning.

{pack}
"""


async def run_deep_research(question: str, runner, session_id: str, breadth: int = 5, max_sources: int = 18) -> dict[str, Any]:
    queries, sources = await collect_sources(question, breadth=breadth, max_sources=max_sources)
    if not sources:
        return {"question": question, "queries": queries, "sources": [], "report": "I couldn't retrieve usable web sources for this research task."}
    prompt = synthesis_prompt(question, queries, sources)
    report = await runner(prompt, "research", session_id)
    return {
        "question": question,
        "queries": queries,
        "sources": [asdict(s) | {"text": ""} for s in sources],
        "report": report,
    }
