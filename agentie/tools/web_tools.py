from __future__ import annotations

import json

from agents import function_tool
from ddgs import DDGS


@function_tool
def search_web(query: str, max_results: int = 5) -> str:
    """Search the public web and return concise search results with titles, URLs, and snippets."""
    clean_query = str(query or "").strip()
    if not clean_query:
        return json.dumps({"error": "A search query is required."})

    limit = max(1, min(int(max_results), 8))

    try:
        raw_results = DDGS(timeout=10).text(
            clean_query,
            safesearch="moderate",
            max_results=limit,
            backend="auto",
        )
    except Exception as exc:
        return json.dumps({"error": f"Web search failed: {exc}"})

    results = []
    for item in raw_results or []:
        results.append(
            {
                "title": str(item.get("title") or "").strip(),
                "url": str(item.get("href") or item.get("url") or "").strip(),
                "snippet": str(item.get("body") or item.get("snippet") or "").strip(),
            }
        )

    return json.dumps({"query": clean_query, "results": results}, ensure_ascii=False)
