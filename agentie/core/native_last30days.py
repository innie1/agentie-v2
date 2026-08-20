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


async def _synthesize(topic: str, sources: list[dict[str, Any]]) -> str:
    pack="\n\n".join(f"[{s['id']}] SOURCE={s['source']}\nTITLE={s['title']}\nURL={s['url']}\nSNIPPET={s['snippet']}" for s in sources[:24])
    instructions=("You are Agentie's Last30Days Native synthesizer. Use only the supplied evidence from the last-30-days search lanes. "
                  "Start with 'What I learned:' and give a compact, useful synthesis of recurring themes, disagreements, recent changes, and practical signals. "
                  "Cite claims using only the supplied IDs such as [L1] or [L2][L5]. Do not invent facts, source IDs, dates, or URLs. "
                  "Mention evidence gaps when a lane has little or no coverage. Do not append a separate Sources section because the UI renders sources.")
    prompt=f"TOPIC\n{topic}\n\nLAST-30-DAYS EVIDENCE\n{pack}"
    agent=Agent(name="Agentie Last30Days Native",instructions=instructions,model=get_model(),model_settings=ModelSettings(max_tokens=1800),tools=[])
    result=await Runner.run(agent,prompt)
    return str(result.final_output or "").strip()


async def research(topic: str) -> dict[str, Any]:
    sources=gather(topic)
    if not sources:return {"message":_fallback_summary(topic,[]),"card":{"type":"last30days","engine":"native","topic":topic,"window_days":30,"sources":[],"source_counts":{},"provider_calls":0}}
    try:answer=await _synthesize(topic,sources);provider_calls=1 if answer else 0
    except Exception:answer="";provider_calls=0
    if not answer:answer=_fallback_summary(topic,sources)
    counts={}
    for s in sources:counts[s["source"]]=counts.get(s["source"],0)+1
    return {"message":answer,"card":{"type":"last30days","engine":"native","topic":topic,"window_days":30,"sources":sources,"source_counts":counts,"provider_calls":provider_calls}}


def run(topic: str) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix="agentie-last30days") as pool:return pool.submit(lambda:asyncio.run(research(topic))).result()


def _topic(message: str) -> str | None:
    text=str(message or "").strip()
    m=re.match(r"^/?last30days(?:\s+(?:about|on|for))?\s+(.+)$",text,re.I)
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
