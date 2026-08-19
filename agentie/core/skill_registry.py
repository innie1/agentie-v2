from __future__ import annotations

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from agentie.core.code_execution import route_code_command
from agentie.core.observability import current_trace_id, set_current_trace
from agentie.core.web_research_service import answer_web_search, search_sources, source_card, sources_only_requested

WORKSPACE=Path.cwd()/"workspace"
SKILLS_DIR=WORKSPACE/"skills"
STATE=WORKSPACE/"skills_state.json"
DEFAULT_SKILLS={
  "local-utils":{"name":"Local Utilities","description":"Timers, reminders, calculations, conversions, notes and system utilities.","agents":["general","manager","coding"],"enabled":True,"capabilities":["timer","alarm","reminder","calculator","conversion","notes","system"]},
  "code-execution":{"name":"Code Execution","description":"Constrained local Python execution with captured output and downloadable artifacts.","agents":["general","coding","manager","research"],"enabled":True,"capabilities":["python","code_execution","local_analysis","artifacts"]},
  "research":{"name":"Research","description":"Web search, page reading and deep research with citations.","agents":["general","research","manager"],"enabled":True,"capabilities":["web_search","browser_read","deep_research","citation_verify"]},
  "files":{"name":"Files & Documents","description":"Upload, inspect, search, generate and download local artifacts including PDF, DOCX, XLSX and PPTX.","agents":["general","research","coding","manager"],"enabled":True,"capabilities":["files","pdf","docx","xlsx","pptx","zip","collections","rag"]},
  "jobs":{"name":"Jobs & Delegation","description":"Durable background jobs, parallel agents, routines and dynamic roles.","agents":["general","manager","research","coding","github"],"enabled":True,"capabilities":["jobs","delegation","routines","roles"]},
  "github":{"name":"GitHub","description":"Repository inspection and GitHub-specialist workflows.","agents":["github","coding","manager"],"enabled":True,"capabilities":["github_read"]},
}

def _load_state()->dict[str,Any]:
    try:return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"overrides":{}}
    except Exception:return {"overrides":{}}
def _save_state(data):STATE.parent.mkdir(parents=True,exist_ok=True);STATE.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
def _load_custom()->dict[str,dict[str,Any]]:
    SKILLS_DIR.mkdir(parents=True,exist_ok=True);out={}
    for path in SKILLS_DIR.glob("*/skill.json"):
        try:item=json.loads(path.read_text(encoding="utf-8"));sid=str(item.get("id") or path.parent.name).lower();item["id"]=sid;out[sid]=item
        except Exception:continue
    return out
def all_skills()->dict[str,dict[str,Any]]:
    state=_load_state();skills={k:{"id":k,**v} for k,v in DEFAULT_SKILLS.items()};skills.update(_load_custom())
    for sid,override in state.get("overrides",{}).items():
        if sid in skills:skills[sid].update(override)
    return skills
def list_skills()->list[dict[str,Any]]:return sorted(all_skills().values(),key=lambda x:str(x.get("name",x["id"])).lower())
def skill_enabled(skill_id:str)->bool:return bool(all_skills().get(skill_id,{}).get("enabled",False))
def set_skill_enabled(skill_id:str,enabled:bool)->dict[str,Any]:
    skills=all_skills();sid=skill_id.lower().strip()
    if sid not in skills:raise KeyError(sid)
    state=_load_state();state.setdefault("overrides",{}).setdefault(sid,{})["enabled"]=bool(enabled);state["updated_at"]=datetime.now().astimezone().isoformat(timespec="seconds");_save_state(state);return all_skills()[sid]
def create_skill_manifest(skill_id:str,name:str,description:str,agents:list[str],capabilities:list[str])->dict[str,Any]:
    sid=re.sub(r"[^a-z0-9_-]+","-",skill_id.lower()).strip("-")
    if not sid:raise ValueError("Skill id is required.")
    path=SKILLS_DIR/sid/"skill.json";path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise ValueError("That skill already exists.")
    valid_agents={"general","research","coding","manager","github","*"};agents=[a for a in agents if a in valid_agents] or ["general"]
    item={"id":sid,"name":name[:120],"description":description[:1000],"agents":sorted(set(agents)),"capabilities":sorted(set(capabilities)),"enabled":True,"version":"1.0","kind":"declarative"};path.write_text(json.dumps(item,indent=2,ensure_ascii=False),encoding="utf-8");return item
def skills_for_agent(agent_type:str)->list[dict[str,Any]]:return [s for s in list_skills() if s.get("enabled") and (agent_type in (s.get("agents") or []) or "*" in (s.get("agents") or []))]


def _run_web_synthesis(query:str)->dict[str,Any]:
    trace_id=current_trace_id()
    def worker():
        if trace_id:set_current_trace(trace_id)
        return asyncio.run(answer_web_search(query,8))
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix="agentie-web") as pool:
        return pool.submit(worker).result()


def _friendly_synthesis_failure(exc:Exception)->str:
    text=str(exc).lower()
    if "429" in text or "quota" in text or "resource_exhausted" in text or "rate limit" in text:
        return "I found the web sources, but the AI summary is temporarily unavailable because the model quota was reached. You can still open the sources below."
    return "I found the web sources, but I couldn't generate the AI summary right now. You can still open the sources below."


def route_skill_command(message:str)->dict[str,Any]|None:
    text=" ".join(message.strip().split());lower=text.lower().strip(" .?!")

    if skill_enabled("code-execution"):
        code_result=route_code_command(text)
        if code_result is not None:return code_result

    web=re.match(r"^(?:please\s+)?(?:search(?:\s+the)?\s+web|web search|search online|look up online|find online|look on the web)\s+(?:for|about|on)?\s*(.+)$",text,re.I)
    if web and skill_enabled("research"):
        query=web.group(1).strip(" .?!")
        if sources_only_requested(text):
            query=re.sub(r"\b(?:sources only|links only|results only|just (?:the )?(?:sources|links|results)|do not summarize|don't summarize|no summary)\b", "", query, flags=re.I).strip(" ,.-")
            try:sources=search_sources(query,8)
            except Exception as exc:return {"message":f"Web search failed: {exc}","card":None}
            return {"message":"","card":source_card(query,sources,"",0)}
        try:return _run_web_synthesis(query)
        except Exception as exc:
            try:sources=search_sources(query,8)
            except Exception:return {"message":"Web search is temporarily unavailable.","card":None}
            card=source_card(query,sources,"",0);card["synthesis_unavailable"]=True
            return {"message":_friendly_synthesis_failure(exc),"card":card}

    if lower in {"skills","show skills","list skills","my skills"}:
        items=list_skills();return {"message":f"Agentie has {len(items)} registered skill(s).","card":{"type":"skills","items":items}}
    m=re.match(r"^(?:create|make|add)\s+(?:a\s+)?skill(?:\s+called|\s+named)?\s+(.+?)\s+(?:for|usable by)\s+([a-z*, ]+?)\s+(?:with|using|that has)\s+(?:capabilities?\s+)?(.+)$",text,re.I)
    if m:
        name=m.group(1).strip(' \"“”');agents=[x.strip().lower() for x in re.split(r"[,/]|\band\b",m.group(2),flags=re.I) if x.strip()];caps=[x.strip().lower().replace(" ","_") for x in re.split(r"[,/]|\band\b",m.group(3),flags=re.I) if x.strip()]
        try:item=create_skill_manifest(name,name,f"Custom declarative skill: {name}",agents,caps)
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"Created declarative skill “{item['name']}”. It can group existing capabilities but will not auto-load arbitrary code.","card":{"type":"skill",**item}}
    m=re.match(r"^(?:enable|turn on)\s+(?:skill\s+)?(.+)$",text,re.I)
    if m:
        sid=m.group(1).strip().lower()
        try:item=set_skill_enabled(sid,True)
        except KeyError:return {"message":"I couldn't find that skill.","card":None}
        return {"message":f"Enabled {item['name']}.","card":{"type":"skill",**item}}
    m=re.match(r"^(?:disable|turn off)\s+(?:skill\s+)?(.+)$",text,re.I)
    if m:
        sid=m.group(1).strip().lower()
        try:item=set_skill_enabled(sid,False)
        except KeyError:return {"message":"I couldn't find that skill.","card":None}
        return {"message":f"Disabled {item['name']}.","card":{"type":"skill",**item}}
    return None
