from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

WORKSPACE=Path.cwd()/"workspace"
PROJECTS_FILE=WORKSPACE/"projects.json"
_LOCK=threading.Lock()

PROJECT_TYPES={
    "novel":{"skill":"novel-writing","specialists":["writer","researcher","critic"],"suggestions":["Create a story bible","Define characters and arcs","Outline chapters","Set a writing routine"]},
    "screenplay":{"skill":"screenwriting","specialists":["writer","researcher","critic"],"suggestions":["Define premise and genre","Build character arcs","Outline acts and scenes","Set a writing routine"]},
    "app":{"skill":"product-building","specialists":["researcher","planner","coder","verifier"],"suggestions":["Research users and competitors","Define requirements","Plan architecture","Build and verify"]},
    "business":{"skill":"business-builder","specialists":["researcher","planner","data analyst","critic"],"suggestions":["Research market","Define business model","Plan launch","Track milestones"]},
    "life":{"skill":"life-project-coach","specialists":["researcher","planner"],"suggestions":["Define measurable goal","Research safe options","Create milestones","Offer a routine or reminder"]},
    "general":{"skill":"project-planning","specialists":["researcher","planner","verifier"],"suggestions":["Clarify outcome","Break into milestones","Delegate specialist work","Review progress"]},
}


def _now()->str:return datetime.now().astimezone().isoformat(timespec="seconds")
def _load()->list[dict[str,Any]]:
    try:
        value=json.loads(PROJECTS_FILE.read_text(encoding="utf-8")) if PROJECTS_FILE.exists() else []
        return value if isinstance(value,list) else []
    except Exception:return []
def _save(items:list[dict[str,Any]])->None:
    PROJECTS_FILE.parent.mkdir(parents=True,exist_ok=True);PROJECTS_FILE.write_text(json.dumps(items,indent=2,ensure_ascii=False),encoding="utf-8")
def list_projects(limit:int=50)->list[dict[str,Any]]:
    with _LOCK:return [dict(x) for x in reversed(_load()[-max(1,limit):])]
def get_project(project_id_or_name:str)->dict[str,Any]|None:
    key=str(project_id_or_name or "").casefold().strip()
    with _LOCK:return next((dict(x) for x in reversed(_load()) if str(x.get("id","")).casefold()==key or str(x.get("name","")).casefold()==key),None)
def latest_project(active_only:bool=True)->dict[str,Any]|None:
    items=list_projects()
    return next((x for x in items if not active_only or x.get("status")=="active"),None)
def _kind(text:str)->str:
    lower=text.casefold()
    if any(x in lower for x in ("novel","book","fiction","story")):return "novel"
    if any(x in lower for x in ("screenplay","movie script","film script","script")):return "screenplay"
    if any(x in lower for x in ("app","software","website","platform","product")):return "app"
    if any(x in lower for x in ("business","company","shop","startup")):return "business"
    if any(x in lower for x in ("lose weight","fitness","habit","learn ","study ","personal goal","life project")):return "life"
    return "general"
def create_project(name:str,goal:str,kind:str|None=None,owner_agent_id:str|None=None)->dict[str,Any]:
    project_kind=kind or _kind(f"{name} {goal}");preset=PROJECT_TYPES.get(project_kind,PROJECT_TYPES["general"]);now=_now()
    item={"id":"proj_"+uuid.uuid4().hex[:10],"name":name.strip()[:120],"goal":goal.strip()[:4000],"kind":project_kind,"status":"active","owner_agent_id":owner_agent_id,"skill":preset["skill"],"specialists":preset["specialists"],"goals":[goal.strip()[:1000]],"decisions":[],"knowledge":[],"milestones":[],"artifacts":[],"handoffs":[],"summaries":[],"created_at":now,"updated_at":now}
    with _LOCK:
        items=_load();items.append(item);_save(items)
    return item
def update_project(project_id:str,**changes:Any)->dict[str,Any]|None:
    with _LOCK:
        items=_load();item=next((x for x in items if x.get("id")==project_id),None)
        if not item:return None
        for key,value in changes.items():
            if key in {"name","goal","status","owner_agent_id"}:item[key]=value
        item["updated_at"]=_now();_save(items);return dict(item)
def append_project_item(project_id:str,section:str,value:Any,metadata:dict[str,Any]|None=None)->dict[str,Any]|None:
    allowed={"goals","decisions","knowledge","milestones","artifacts","handoffs","summaries"}
    if section not in allowed:raise ValueError("Unsupported project section.")
    with _LOCK:
        items=_load();item=next((x for x in items if x.get("id")==project_id),None)
        if not item:return None
        entry={"value":value,"at":_now(),**(metadata or {})};item.setdefault(section,[]).append(entry);item["updated_at"]=_now();_save(items);return dict(item)
def project_context(project:dict[str,Any],role:str,task:str,max_items:int=8)->str:
    """Return a role-scoped project brief, never another worker's full chat."""
    role_l=str(role or "").casefold();parts=[f"PROJECT: {project.get('name')}",f"GOAL: {project.get('goal')}",f"YOUR ASSIGNMENT: {task}"]
    decisions=[str(x.get("value",x)) for x in project.get("decisions",[])[-max_items:]]
    if decisions:parts.append("DECISIONS:\n- "+"\n- ".join(decisions))
    knowledge=[]
    for x in project.get("knowledge",[])[-max_items*2:]:
        audience=str(x.get("audience") or "all").casefold()
        if audience in {"all",role_l} or any(word in role_l for word in audience.split(',')):knowledge.append(str(x.get("value",x)))
    if knowledge:parts.append("RELEVANT PROJECT KNOWLEDGE:\n- "+"\n- ".join(knowledge[-max_items:]))
    milestones=[str(x.get("value",x)) for x in project.get("milestones",[])[-max_items:]]
    if milestones:parts.append("MILESTONES:\n- "+"\n- ".join(milestones))
    parts.append("CONTEXT RULE: Use only this scoped project brief plus your own agent memory. Do not import another specialist's private conversation.")
    return "\n\n".join(parts)
def record_handoff(project_id:str,from_agent:str,to_agent:str,task:str,team_job_id:str|None=None)->None:
    append_project_item(project_id,"handoffs",{"from":from_agent,"to":to_agent,"task":task,"team_job_id":team_job_id})
def record_worker_result(project_id:str,agent_name:str,role:str,task:str,result:str)->None:
    compact=re.sub(r"\s+"," ",str(result or "")).strip()
    if len(compact)>900:compact=compact[:899].rstrip()+"…"
    append_project_item(project_id,"summaries",compact,{"agent":agent_name,"role":role,"task":task})
    append_project_item(project_id,"knowledge",compact,{"source_agent":agent_name,"audience":"all","task":task})
def project_card(project:dict[str,Any])->dict[str,Any]:
    return {"type":"project","id":project["id"],"name":project["name"],"goal":project["goal"],"kind":project["kind"],"status":project["status"],"skill":project.get("skill"),"specialists":project.get("specialists",[]),"milestones":project.get("milestones",[])[-8:],"summaries":project.get("summaries",[])[-8:],"updated_at":project.get("updated_at")}
def _name_from_goal(goal:str,kind:str)->str:
    clean=re.sub(r"^(?:i\s+(?:want|plan|need)\s+to\s+|i(?:'m| am)\s+)","",goal.strip(),flags=re.I);clean=re.sub(r"\s+"," ",clean).strip(" .?!")
    return (clean[:70] or f"{kind.title()} project")
def route_project_command(message:str)->dict[str,Any]|None:
    text=" ".join(message.strip().split());lower=text.casefold().strip(" .?!")
    if lower in {"show projects","list projects","my projects","show my projects"}:
        items=list_projects();return {"message":f"You have {len(items)} project(s).","card":{"type":"projects","items":[project_card(x) for x in items]}}
    if re.search(r"\b(where are we|project status|how is the project|where are we so far)\b",lower):
        p=latest_project()
        if not p:return None
        return {"message":f"{p['name']} is {p['status']}. It has {len(p.get('summaries',[]))} specialist update(s) and {len(p.get('milestones',[]))} milestone(s).","card":project_card(p)}
    explicit=re.match(r"^(?:create|start|make)\s+(?:a\s+)?project(?:\s+called|\s+named)?\s+(.+?)\s+(?:to|for|about)\s+(.+)$",text,re.I)
    if explicit:
        p=create_project(explicit.group(1).strip(' \"“”'),explicit.group(2).strip());return {"message":f"Created project {p['name']}. I’ll keep specialist work separated and store only useful project summaries here.","card":project_card(p)}
    long_term=re.match(r"^(?:i\s+(?:want|plan|need)\s+to|i(?:'m| am)\s+)(.+)$",text,re.I)
    if long_term:
        goal=text;kind=_kind(goal)
        signals=("novel","screenplay","book","build an app","build a website","start a business","lose weight","learn ","study ","for the next month","every day","daily","weekly")
        if kind!="general" and any(s in lower for s in signals):
            existing=latest_project()
            if existing and existing.get("goal","").casefold()==goal.casefold():p=existing
            else:p=create_project(_name_from_goal(goal,kind),goal,kind)
            suggestions=PROJECT_TYPES[kind]["suggestions"]
            return {"message":f"I’ve treated this as a long-running {kind} project so it doesn’t depend on one giant chat. I can use {p['skill']} and delegate only role-relevant context. I’ll ask only for information that is genuinely missing; routines/reminders will still require your approval.","card":{**project_card(p),"suggested_next_steps":suggestions,"proactive":True}}
    return None
