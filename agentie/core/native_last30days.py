from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlparse

from agents import Agent, ModelSettings, Runner
from ddgs import DDGS

from agentie.models.provider import get_model

SOURCE_LANES = [
    ("reddit", "site:reddit.com"),
    ("x", "site:x.com"),
    ("youtube", "site:youtube.com"),
    ("hackernews", "site:news.ycombinator.com"),
    ("github", "site:github.com"),
    ("web", ""),
]


def status() -> dict[str, Any]:
    return {"id":"last30days-native","ready":True,"installed":True,"python":"3.11+","engine":"Agentie native","window_days":30,"sources":[x[0] for x in SOURCE_LANES],"requires":["ddgs"],"optional":["AI provider for richer synthesis"]}


def _domain(url: str) -> str:
    try:return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:return ""


def _search_lane(topic: str, lane: str, qualifier: str, max_results: int = 4) -> list[dict[str, Any]]:
    since=(date.today()-timedelta(days=30)).isoformat();q=f"{topic} {qualifier} after:{since}".strip()
    try:rows=DDGS(timeout=12).text(q,safesearch="moderate",timelimit="m",max_results=max_results,backend="auto")
    except TypeError:
        try:rows=DDGS(timeout=12).text(q,safesearch="moderate",max_results=max_results,backend="auto")
        except Exception:return []
    except Exception:return []
    out=[]
    for item in rows or []:
        url=str(item.get("href") or item.get("url") or "").strip()
        if not url:continue
        out.append({"source":lane,"title":str(item.get("title") or url).strip(),"url":url,"domain":_domain(url),"snippet":str(item.get("body") or item.get("snippet") or "").strip()})
    return out


def gather(topic: str, per_lane: int = 4) -> list[dict[str, Any]]:
    seen=set();results=[]
    for lane,qualifier in SOURCE_LANES:
        for item in _search_lane(topic,lane,qualifier,per_lane):
            key=item["url"].split("#",1)[0].rstrip("/")
            if key in seen:continue
            seen.add(key);item["id"]=f"L{len(results)+1}";results.append(item)
    return results


def _clean_output(value:str)->str:
    text=str(value or "").replace("\r\n","\n").strip()
    text=re.sub(r"(?m)^#{1,6}\s*","",text)
    text=text.replace("**","").replace("__","").replace("`","")
    text=re.sub(r"(?m)^\s*[-*]\s+","• ",text)
    text=re.sub(r"\n{3,}","\n\n",text)
    return text.strip()


def _fallback_summary(topic: str, sources: list[dict[str, Any]]) -> str:
    counts={}
    for s in sources:counts[s["source"]]=counts.get(s["source"],0)+1
    lines=["What I learned",""]
    if not sources:return "\n".join(lines+["I could not retrieve enough recent public evidence to make a reliable summary."])
    lines.append(f"Recent coverage: {sum(counts.values())} sources across {len(counts)} source types.");lines.append("")
    for s in sources[:7]:
        snippet=re.sub(r"\s+"," ",s.get("snippet","")).strip()
        if len(snippet)>190:snippet=snippet[:187]+"..."
        lines.append(f"• [{s['id']}] {s['title']}"+(f" — {snippet}" if snippet else ""))
    return "\n".join(lines)


async def _synthesize(topic: str, sources: list[dict[str, Any]]) -> str:
    pack="\n\n".join(f"[{s['id']}] SOURCE={s['source']}\nTITLE={s['title']}\nURL={s['url']}\nSNIPPET={s['snippet']}" for s in sources[:24])
    instructions=("You are Agentie's Last30Days Native synthesizer. Use only the supplied evidence from the last-30-days search lanes. "
                  "Write for a clean chat UI, not Markdown. Do not use # headings, asterisks, backticks, tables, or long blocks. "
                  "Use this readable structure: first line 'What I learned'; blank line; 3 to 5 short sections with plain section names; "
                  "under each section use short bullet lines beginning with the bullet character •. Keep paragraphs to at most 3 sentences. "
                  "Focus on recurring themes, disagreements, recent changes, and practical signals. Cite claims using only supplied IDs like [L1] or [L2][L5]. "
                  "Do not invent facts, source IDs, dates, or URLs. Mention evidence gaps when coverage is weak. Do not add a Sources section because the UI renders sources below.")
    prompt=f"TOPIC\n{topic}\n\nLAST-30-DAYS EVIDENCE\n{pack}"
    agent=Agent(name="Agentie Last30Days Native",instructions=instructions,model=get_model(),model_settings=ModelSettings(max_tokens=1600),tools=[])
    result=await Runner.run(agent,prompt)
    return _clean_output(str(result.final_output or ""))


async def research(topic: str) -> dict[str, Any]:
    sources=gather(topic);counts={}
    for s in sources:counts[s["source"]]=counts.get(s["source"],0)+1
    if not sources:
        answer=_fallback_summary(topic,[]);return {"message":"","card":{"type":"last30days","engine":"native","topic":topic,"window_days":30,"answer":answer,"sources":[],"source_counts":{},"provider_calls":0}}
    try:answer=await _synthesize(topic,sources);provider_calls=1 if answer else 0
    except Exception:answer="";provider_calls=0
    if not answer:answer=_fallback_summary(topic,sources)
    return {"message":"","card":{"type":"last30days","engine":"native","topic":topic,"window_days":30,"answer":_clean_output(answer),"sources":sources,"source_counts":counts,"provider_calls":provider_calls}}


def run(topic: str) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix="agentie-last30days") as pool:return pool.submit(lambda:asyncio.run(research(topic))).result()


def _topic(message: str) -> str | None:
    text=str(message or "").strip();m=re.match(r"^/?last30days(?:\s+(?:about|on|for))?\s+(.+)$",text,re.I)
    if m:return m.group(1).strip()
    m=re.match(r"^(?:research|find|show me|tell me)\s+(?:what people (?:are saying|say)|the last 30 days)\s+(?:about|on|for)\s+(.+)$",text,re.I)
    return m.group(1).strip() if m else None


def route(message: str) -> dict[str, Any] | None:
    low=str(message or "").lower().strip(" .?!")
    if low in {"last30days status","show last30days status","check last30days","native last30days status"}:return {"message":"Agentie Last30Days Native is ready on Python 3.11+.","card":{"type":"skill_runtime","skill":"last30days","status":status()}}
    if low.startswith(("install last30days","update last30days","upstream last30days")):return None
    topic=_topic(message)
    if not topic:return None
    return run(topic)
