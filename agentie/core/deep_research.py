from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import urlparse

from agentie.core.citation_verifier import annotate_report, verify_report
from agentie.tools.web_tools import search_web_json
from agentie.tools.browser_tools import browser_read_page_text


@dataclass
class Source:
    id: str
    title: str
    url: str
    snippet: str = ""
    text: str = ""
    query: str = ""


def _domain(url: str) -> str:
    try: return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception: return ""


def build_queries(question: str, breadth: int = 5) -> list[str]:
    clean=re.sub(r"\s+"," ",question).strip()
    seeds=[clean,f"{clean} primary sources",f"{clean} evidence data",f"{clean} criticism limitations",f"{clean} recent developments",f"{clean} expert analysis"]
    out=[]
    for q in seeds:
        if q.lower() not in {x.lower() for x in out}: out.append(q)
    return out[:max(2,min(int(breadth),8))]


def parse_search_payload(payload: str, query: str) -> list[Source]:
    try:data=json.loads(payload)
    except Exception:return []
    out=[]
    for item in data.get("results") or []:
        url=str(item.get("url") or "").strip()
        if url: out.append(Source("",str(item.get("title") or url),url,str(item.get("snippet") or ""),query=query))
    return out


def _search_error(payload: str) -> str | None:
    try:data=json.loads(payload)
    except Exception:return "Web search returned an unreadable response."
    error=str(data.get("error") or "").strip()
    return error or None


def dedupe_sources(sources:list[Source],max_sources:int=18)->list[Source]:
    seen=set();out=[]
    for source in sources:
        key=source.url.split("#",1)[0].rstrip("/")
        if key in seen:continue
        seen.add(key);source.id=f"S{len(out)+1}";out.append(source)
        if len(out)>=max_sources:break
    return out


async def collect_sources(question:str,breadth:int=5,max_sources:int=18)->tuple[list[str],list[Source],list[str]]:
    queries=build_queries(question,breadth);errors=[]
    async def search(q:str)->list[Source]:
        try:
            payload=await asyncio.to_thread(search_web_json,q,8)
            error=_search_error(payload)
            if error:errors.append(f"{q}: {error}")
            return parse_search_payload(payload,q)
        except Exception as exc:
            errors.append(f"{q}: {exc}")
            return []
    batches=await asyncio.gather(*(search(q) for q in queries));sources=dedupe_sources([s for b in batches for s in b],max_sources)
    chosen=[];domains={}
    for source in sources:
        d=_domain(source.url)
        if domains.get(d,0)>=2:continue
        domains[d]=domains.get(d,0)+1;chosen.append(source)
    sources=chosen[:max_sources];sem=asyncio.Semaphore(5)
    async def read(source:Source)->None:
        async with sem:
            try:source.text=(await asyncio.to_thread(browser_read_page_text,source.url))[:16000]
            except Exception:source.text=""
    await asyncio.gather(*(read(s) for s in sources));return queries,sources,errors


def context_pack(question:str,queries:list[str],sources:list[Source])->str:
    blocks=[]
    for s in sources:
        evidence=(s.text or s.snippet).strip();blocks.append(f"[{s.id}] {s.title}\nURL: {s.url}\nFound via: {s.query}\nEvidence:\n{evidence[:12000]}")
    return f"Research question: {question}\n\nSearch queries used:\n- "+"\n- ".join(queries)+"\n\nSOURCE PACK\n\n"+"\n\n---\n\n".join(blocks)


def synthesis_prompt(question:str,queries:list[str],sources:list[Source])->str:
    return f"""You are Agentie's research synthesis specialist.
Produce a rigorous answer using ONLY the source pack below.
Every externally grounded factual claim must cite source IDs like [S1] or [S2][S5].
Never invent a citation. Prefer primary/authoritative sources, distinguish fact from inference, explain disagreements and limitations, and end with a Sources section containing source IDs, titles, and URLs.

{context_pack(question,queries,sources)}
"""


async def run_deep_research(question:str,runner,session_id:str,breadth:int=5,max_sources:int=18)->dict[str,Any]:
    queries,sources,errors=await collect_sources(question,breadth,max_sources)
    if not sources:
        detail=(errors[-1].split(": ",1)[-1] if errors else "No search backend produced usable results.")
        return {"question":question,"queries":queries,"sources":[],"errors":errors,"report":f"I couldn't retrieve usable web sources for this research task. {detail}","verification":{"passed":False,"unsupported_claims":0,"weak_claims":0,"citation_count":0}}
    draft=await runner(synthesis_prompt(question,queries,sources),"research",session_id)
    verification=verify_report(draft,sources)
    report=annotate_report(draft,verification)
    return {"question":question,"queries":queries,"sources":[asdict(s)|{"text":""} for s in sources],"errors":errors,"report":report,"verification":verification}
