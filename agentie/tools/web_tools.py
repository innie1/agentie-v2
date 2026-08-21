from __future__ import annotations

import json

from agents import function_tool
from ddgs import DDGS


def _search_attempt(query: str, limit: int, backend: str | None) -> list[dict]:
    kwargs = {
        "safesearch": "moderate",
        "max_results": limit,
    }
    if backend:
        kwargs["backend"] = backend
    rows = DDGS(timeout=12).text(query, **kwargs)
    return list(rows or [])


def search_web_json(query: str, max_results: int = 5) -> str:
    """Plain Python web-search implementation for internal systems and tests."""
    clean_query = str(query or "").strip()
    if not clean_query:
        return json.dumps({"error": "A search query is required."})

    limit = max(1, min(int(max_results), 8))
    errors: list[str] = []
    raw_results: list[dict] = []
    used_backend = None

    for backend in ("auto", "duckduckgo", "brave", None):
        try:
            raw_results = _search_attempt(clean_query, limit, backend)
            if raw_results:
                used_backend = backend or "default"
                break
            errors.append(f"{backend or 'default'} returned no results")
        except Exception as exc:
            errors.append(f"{backend or 'default'}: {exc}")

    results = []
    for item in raw_results:
        url = str(item.get("href") or item.get("url") or "").strip()
        if not url:
            continue
        results.append(
            {
                "title": str(item.get("title") or url).strip(),
                "url": url,
                "snippet": str(item.get("body") or item.get("snippet") or "").strip(),
            }
        )

    payload = {
        "query": clean_query,
        "results": results,
        "backend": used_backend,
    }
    if not results:
        payload["error"] = "Web search returned no usable results. " + (" | ".join(errors[-4:]) if errors else "No backend produced results.")
    elif errors:
        payload["warnings"] = errors
    return json.dumps(payload, ensure_ascii=False)


@function_tool
def search_web(query: str, max_results: int = 5) -> str:
    """Search the public web and return concise search results with titles, URLs, and snippets."""
    return search_web_json(query, max_results)
