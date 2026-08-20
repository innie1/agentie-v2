from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlparse

from ddgs import DDGS

from agentie.core.web_research_service import answer_web_search

SOURCE_LANES = [
    ("reddit", "site:reddit.com"),
    ("x", "site:x.com"),
    ("youtube", "site:youtube.com"),
    ("hackernews", "site:news.ycombinator.com"),
    ("github", "site:github.com"),
    ("web", ""),
]


def status() -> dict[str, Any]:
    return {
        "id": "last30days-native",
        "ready": True,
        "installed": True,
        "python": "3.11+",
        "engine": "Agentie native",
        "sources": [x[0] for x in SOURCE_LANES],
        "requires": ["ddgs"],
        "optional": ["AI provider for richer synthesis"],
    }


def _domain(url: str) -> str:
    try:return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:return ""


def _search_lane(topic: str, lane: str, qualifier: str, max_results: int = 4) -> list[dict[str, Any]]:
    since = (date.today() - timedelta(days=30)).isoformat()
    q = f"{topic} {qualifier} after:{since}".strip()
    try:
        rows = DDGS(timeout=12).text(q, safesearch="moderate", timelimit="m", max_results=max_results, backend="auto")
    except TypeError:
        rows = DDGS(timeout=12).text(q, safesearch="moderate", max_results=max_results, backend="auto")
    except Exception:
        return []
    out=[]
    for item in rows or []:
        url=str(item.get("href") or item.get("url") or "").strip()
        if not url:continue
        out.append({
            "source":lane,
            "title":str(item.get("title") or url).strip(),
            "url":url,
            "domain":_domain(url),
            "snippet":str(item.get("body") or item.get("snippet") or "").strip(),
        })
    return out


def gather(topic: str, per_lane: int = 4) -> list[dict[str, Any]]:
    seen=set();results=[]
    for lane,qualifier in SOURCE_LANES:
        for item in _search_lane(topic,lane,qualifier,per_lane):
            key=item["url"].split("#",1)[0].rstrip("/")
            if key in seen:continue
            seen.add(key);item["id"]=f"L{len(results)+1}";results.append(item)
    return results


def _fallback_summary(topic: str, sources: list[dict[str, Any]]) -> str:
    counts={}
    for s in sources:counts[s["source"]]=counts.get(s["source"],0)+1
    coverage=", ".join(f"{k} {v}" for k,v in counts.items()) or "no usable sources"
    lines=[f"🌐 Agentie Last30Days Native · {date.today().isoformat()}","",f"What I learned about {topic}:",f"Coverage: {coverage}."]
    for s in sources[:8]:
        snippet=re.sub(r"\s+"," ",s.get("snippet","")).strip()
        if len(snippet)>220:snippet=snippet[:217]+"..."
        lines.append(f"- [{s['id']}] {s['title']} ({s['source']})"+(f": {snippet}" if snippet else ""))
    if not sources:lines.append("- I could not retrieve enough recent public evidence to make a reliable summary.")
    return "\n".join(lines)


async def research(topic: str) -> dict[str, Any]:
    sources=gather(topic)
    if not sources:
        return {"message":_fallback_summary(topic,[]),"card":{"type":"last30days","engine":"native","topic":topic,"sources":[],"source_counts":{},"provider_calls":0}}
    query = f"What are people saying about {topic} in the last 30 days? Focus on recent community reaction, recurring themes, disagreements, and practical signals."
    try:
        synthesized=await answer_web_search(query,8)
        answer=((synthesized.get("card") or {}).get("answer") or "").strip()
        provider_calls=int((synthesized.get("card") or {}).get("provider_calls") or 0)
    except Exception:
        answer="";provider_calls=0
    if not answer:answer=_fallback_summary(topic,sources)
    counts={}
    for s in sources:counts[s["source"]]=counts.get(s["source"],0)+1
    return {"message":answer,"card":{"type":"last30days","engine":"native","topic":topic,"window_days":30,"sources":sources,"source_counts":counts,"provider_calls":provider_calls}}


def run(topic: str) -> dict[str, Any]:
    return asyncio.run(research(topic))
