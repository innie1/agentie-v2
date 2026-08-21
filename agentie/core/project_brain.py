from __future__ import annotations
import json,re,threading,uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from agentie.core.project_skills import activate as activate_project_skill

WORKSPACE=Path.cwd()/"workspace";PROJECTS_FILE=WORKSPACE/"projects.json";_LOCK=threading.Lock()
PROJECT_TYPES={"novel":{"skill":"novel-writing","specialists":["writer","researcher","critic"],"suggestions":["Create a story bible","Define characters and arcs","Outline chapters","Set a writing routine"]},"screenplay":{"skill":"screenwriting","specialists":["writer","researcher","critic"],"suggestions":["Define premise and genre","Build character arcs","Outline acts and scenes","Set a writing routine"]},"app":{"skill":"product-building","specialists":["researcher","planner","coder","verifier"],"suggestions":["Research users and competitors","Define requirements","Plan architecture","Build and verify"]},"business":{"skill":"business-builder","specialists":["researcher","planner","data analyst","critic"],"suggestions":["Research market","Define business model","Plan launch","Track milestones"]},"life":{"skill":"life-project-coach","specialists":["researcher","planner"],"suggestions":["Define measurable goal","Research safe options","Create milestones","Offer a routine or reminder"]},"general":{"skill":"project-planning","specialists":["researcher","planner","verifier"],"suggestions":["Clarify outcome","Break into milestones","Delegate specialist work","Review progress"]}}
def _now():return datetime.now().astimezone().isoformat(timespec="seconds")
def _load():
    try:v=json.loads(PROJECTS_FILE.read_text(encoding="utf-8")) if PROJECTS_FILE.exists() else [];return v if isinstance(v,list) else []
    except Exception:return []
def _save(v):PROJECTS_FILE.parent.mkdir(parents=True,exist_ok=True);PROJECTS_FILE.write_text(json.dumps(v,indent=2,ensure_ascii=False),encoding="utf-8")
def list_projects(limit=50):
    with _LOCK:return [dict(x) for x in reversed(_load()[-max(1,limit):])]
def get_project(key):
    k=str(key or "").casefold().strip()
    with _LOCK:return next((dict(x) for x in reversed(_load()) if str(x.get("id","")).casefold()==k or str(x.get("name","")).casefold()==k),None)
def latest_project(active_only=True):return next((x for x in list_projects() if not active_only or x.get("status")=="active"),None)
def projects_for_agent(agent_id,limit=50):
    aid=str(agent_id or "")
    return [p for p in list_projects(limit) if aid and (p.get("owner_agent_id")==aid or aid in (p.get("assigned_agent_ids") or []))]
def _kind(text):
    l=text.casefold()
    if any(x in l for x in ("novel","book","fiction","story")):return "novel"
    if any(x in l for x in ("screenplay","movie script","film script","script")):return "screenplay"
    if any(x in l for x in ("app","software","website","platform","product")):return "app"
    if any(x in l for x in ("business","company","shop","startup")):return "business"
    if any(x in l for x in ("lose weight","fitness","habit","learn ","study ","personal goal","life project")):return "life"
    return "general"
def create_project(name,goal,kind=None,owner_agent_id=None):
    k=kind or _kind(f"{name} {goal}");p=PROJECT_TYPES.get(k,PROJECT_TYPES["general"]);now=_now();assigned=[owner_agent_id] if owner_agent_id else []
    item={"id":"proj_"+uuid.uuid4().hex[:10],"name":name.strip()[:120],"goal":goal.strip()[:4000],"kind":k,"status":"active","owner_agent_id":owner_agent_id,"assigned_agent_ids":assigned,"assigned_agents":[],"skill":p["skill"],"specialists":p["specialists"],"goals":[goal.strip()[:1000]],"decisions":[],"knowledge":[],"milestones":[],"artifacts":[],"handoffs":[],"summaries":[],"created_at":now,"updated_at":now}
    with _LOCK:items=_load();items.append(item);_save(items)
    return item
def update_project(pid,**changes):
    with _LOCK:
        items=_load();p=next((x for x in items if x.get("id")==pid),None)
        if not p:return None
        for k,v in changes.items():
            if k in {"name","goal","status","owner_agent_id"}:p[k]=v
        p["updated_at"]=_now();_save(items);return dict(p)
def assign_agents(pid,agents):
    with _LOCK:
        items=_load();p=next((x for x in items if x.get("id")==pid),None)
        if not p:return None
        ids=list(p.get("assigned_agent_ids") or []);rows=list(p.get("assigned_agents") or []);known={str(x.get("id") or "") for x in rows if isinstance(x,dict)}
        for a in agents or []:
            aid=str(a.get("id") or "")
            if aid and aid not in ids:ids.append(aid)
            if aid and aid not in known:rows.append({"id":aid,"name":a.get("name"),"role":a.get("role")});known.add(aid)
        p["assigned_agent_ids"]=ids;p["assigned_agents"]=rows;p["updated_at"]=_now();_save(items);return dict(p)
def append_project_item(pid,section,value,metadata=None):
    if section not in {"goals","decisions","knowledge","milestones","artifacts","handoffs","summaries"}:raise ValueError("Unsupported project section.")
    with _LOCK:
        items=_load();p=next((x for x in items if x.get("id")==pid),None)
        if not p:return None
        p.setdefault(section,[]).append({"value":value,"at":_now(),**(metadata or {})});p["updated_at"]=_now();_save(items);return dict(p)
def project_context(project,role,task,max_items=8):
    role_l=str(role or "").casefold();parts=[f"PROJECT: {project.get('name')}",f"GOAL: {project.get('goal')}",f"YOUR ASSIGNMENT: {task}"]
    skill=activate_project_skill(project.get("skill"))
    if skill:parts.append(f"ACTIVATED SKILL — {skill['name']}:\n{skill['instructions']}")
    decisions=[str(x.get("value",x)) for x in project.get("decisions",[])[-max_items:]]
    if decisions:parts.append("DECISIONS:\n- "+"\n- ".join(decisions))
    knowledge=[]
    for x in project.get("knowledge",[])[-max_items*2:]:
        audience=str(x.get("audience") or "all").casefold()
        if audience in {"all",role_l} or any(w in role_l for w in audience.split(',')):knowledge.append(str(x.get("value",x)))
    if knowledge:parts.append("RELEVANT PROJECT KNOWLEDGE:\n- "+"\n- ".join(knowledge[-max_items:]))
    milestones=[str(x.get("value",x)) for x in project.get("milestones",[])[-max_items:]]
    if milestones:parts.append("MILESTONES:\n- "+"\n- ".join(milestones))
    parts.append("CONTEXT RULE: Use only this scoped project brief plus your own agent memory. Do not import another specialist's private conversation.");return "\n\n".join(parts)
def record_handoff(pid,from_agent,to_agent,task,team_job_id=None):append_project_item(pid,"handoffs",{"from":from_agent,"to":to_agent,"task":task,"team_job_id":team_job_id})
def record_worker_result(pid,agent_name,role,task,result):
    compact=re.sub(r"\s+"," ",str(result or "")).strip();compact=compact if len(compact)<=900 else compact[:899].rstrip()+"…";append_project_item(pid,"summaries",compact,{"agent":agent_name,"role":role,"task":task});append_project_item(pid,"knowledge",compact,{"source_agent":agent_name,"audience":"all","task":task})
def project_card(p,viewer_agent_id=None):return {"type":"project","id":p["id"],"name":p["name"],"goal":p["goal"],"kind":p["kind"],"status":p["status"],"skill":p.get("skill"),"specialists":p.get("specialists",[]),"assigned_agents":p.get("assigned_agents",[]),"assigned_to_viewer":bool(viewer_agent_id and viewer_agent_id in (p.get("assigned_agent_ids") or [])),"milestones":p.get("milestones",[])[-8:],"summaries":p.get("summaries",[])[-8:],"updated_at":p.get("updated_at")}
def _name_from_goal(goal,kind):
    clean=re.sub(r"^(i\s+(want|plan|need)\s+to\s+|i('m| am)\s+)","",goal.strip(),flags=re.I);clean=re.sub(r"\s+"," ",clean).strip(" .?!");return clean[:70] or f"{kind.title()} project"
def route_project_command(message):
    text=" ".join(message.strip().split());lower=text.casefold().strip(" .?!")
    if lower in {"show projects","list projects","my projects","show my projects"}:
        items=list_projects();return {"message":f"You have {len(items)} project(s).","card":{"type":"projects","items":[project_card(x) for x in items]}}
    if re.search(r"\b(where are we|project status|how is the project|where are we so far)\b",lower):
        p=latest_project()
        if not p:return None
        return {"message":f"{p['name']} is {p['status']}. It has {len(p.get('summaries',[]))} specialist update(s) and {len(p.get('milestones',[]))} milestone(s).","card":project_card(p)}
    m=re.match(r"^(create|start|make)\s+(a\s+)?project(\s+called|\s+named)?\s+(.+?)\s+(to|for|about)\s+(.+)$",text,re.I)
    if m:
        p=create_project(m.group(4).strip(' \"“”'),m.group(6).strip());return {"message":f"Created project {p['name']}. I’ll keep specialist work separated and store only useful project summaries here.","card":project_card(p)}
    long_term=re.match(r"^(i\s+(want|plan|need)\s+to|i('m| am)\s+)(.+)$",text,re.I)
    if long_term:
        goal=text;k=_kind(goal);signals=("novel","screenplay","book","build an app","build a website","start a business","lose weight","learn ","study ","for the next month","every day","daily","weekly")
        if k!="general" and any(s in lower for s in signals):
            existing=latest_project();p=existing if existing and existing.get("goal","").casefold()==goal.casefold() else create_project(_name_from_goal(goal,k),goal,k);suggestions=PROJECT_TYPES[k]["suggestions"]
            return {"message":f"I’ve treated this as a long-running {k} project so it doesn’t depend on one giant chat. I activated {p['skill']} and will delegate only role-relevant context. I’ll ask only for genuinely missing information; routines/reminders still require your approval.","card":{**project_card(p),"suggested_next_steps":suggestions,"proactive":True}}
    return None
