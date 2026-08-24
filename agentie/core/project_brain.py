from __future__ import annotations
import json,re,threading,uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from agentie.core.deletion_registry import find_deleted,remember_deleted
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
    aid=str(agent_id or "");candidates=[p for p in list_projects(limit) if aid and (p.get("owner_agent_id")==aid or aid in (p.get("assigned_agent_ids") or []))];chosen={}
    for p in candidates:
        key=str(p.get("name") or p.get("id") or "").casefold().strip();has_work=1 if any(str(x.get("agent_id"))==aid for x in (p.get("agent_work") or []) if isinstance(x,dict)) else 0;score=(has_work,str(p.get("updated_at") or ""))
        if key not in chosen or score>chosen[key][0]:chosen[key]=(score,p)
    return [row[1] for row in sorted(chosen.values(),key=lambda x:str(x[1].get("updated_at") or ""),reverse=True)]
def _kind(text):
    l=text.casefold()
    if any(x in l for x in ("novel","book","fiction","story")):return "novel"
    if any(x in l for x in ("screenplay","movie script","film script","script")):return "screenplay"
    if any(x in l for x in ("app","software","website","platform","product")):return "app"
    if any(x in l for x in ("business","company","shop","startup")):return "business"
    if any(x in l for x in ("lose weight","fitness","habit","learn ","study ","personal goal","life project")):return "life"
    return "general"
def create_project(name,goal,kind=None,owner_agent_id=None):
    clean_name=str(name or "").strip()[:120];clean_goal=str(goal or "").strip()[:4000]
    with _LOCK:
        items=_load();existing=next((x for x in reversed(items) if str(x.get("name","")).casefold()==clean_name.casefold() and x.get("status")=="active"),None)
        if existing:
            if owner_agent_id and owner_agent_id not in (existing.get("assigned_agent_ids") or []):existing.setdefault("assigned_agent_ids",[]).append(owner_agent_id);existing["updated_at"]=_now();_save(items)
            return dict(existing)
        k=kind or _kind(f"{clean_name} {clean_goal}");preset=PROJECT_TYPES.get(k,PROJECT_TYPES["general"]);now=_now();assigned=[owner_agent_id] if owner_agent_id else []
        item={"id":"proj_"+uuid.uuid4().hex[:10],"name":clean_name,"goal":clean_goal,"kind":k,"status":"active","owner_agent_id":owner_agent_id,"assigned_agent_ids":assigned,"assigned_agents":[],"agent_work":[],"skill":preset["skill"],"specialists":preset["specialists"],"goals":[clean_goal[:1000]],"decisions":[],"knowledge":[],"milestones":[],"artifacts":[],"handoffs":[],"summaries":[],"share_mode":"scoped","created_at":now,"updated_at":now};items.append(item);_save(items);return dict(item)
def set_share_mode(pid,mode):
    """Set project context sharing: scoped by default, or full team sharing."""
    clean=str(mode or "").strip().casefold()
    if clean not in {"scoped","full"}:raise ValueError('share_mode must be "scoped" or "full".')
    with _LOCK:
        items=_load();p=next((x for x in items if x.get("id")==pid),None)
        if not p:return None
        p["share_mode"]=clean;p["updated_at"]=_now();_save(items);return dict(p)
def update_project(pid,**changes):
    with _LOCK:
        items=_load();p=next((x for x in items if x.get("id")==pid),None)
        if not p:return None
        for k,v in changes.items():
            if k in {"name","goal","status","owner_agent_id"}:p[k]=v
        p["updated_at"]=_now();_save(items);return dict(p)
def delete_project(pid):
    """Delete a Project Brain once. Historical agent chats remain historical chat."""
    key=str(pid or "").strip();store=PROJECTS_FILE.parent/"deletions.json"
    with _LOCK:
        items=_load();index=next((i for i,x in enumerate(items) if x.get("id")==key),None)
        if index is None:
            tomb=find_deleted("project",key,store);return {"already_deleted":True,"id":tomb.get("entity_id"),"name":tomb.get("name"),"deleted_at":tomb.get("deleted_at")} if tomb else None
        deleted=items.pop(index);_save(items)
    remember_deleted("project",str(deleted.get("id")),str(deleted.get("name") or ""),{"kind":deleted.get("kind")},store);return deleted
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
def set_agent_work(pid,agent,task,team_job_id=None,from_agent=None,status="queued",scoped_brief=None):
    aid=str(agent.get("id") or "");name=str(agent.get("name") or "");role=str(agent.get("role") or agent.get("base") or "general")
    if not aid:return None
    with _LOCK:
        items=_load();p=next((x for x in items if x.get("id")==pid),None)
        if not p:return None
        work=list(p.get("agent_work") or []);row=next((x for x in work if str(x.get("agent_id"))==aid),None);now=_now();value={"agent_id":aid,"agent_name":name,"role":role,"task":str(task or "").strip(),"team_job_id":team_job_id,"from_agent":from_agent,"status":status,"scoped_brief":str(scoped_brief or "").strip(),"updated_at":now}
        if row:row.update(value)
        else:work.append(value)
        p["agent_work"]=work;p["updated_at"]=now;_save(items);return dict(p)
def update_agent_work_status(pid,agent_id_or_name,status,summary=None):
    key=str(agent_id_or_name or "").casefold();now=_now()
    with _LOCK:
        items=_load();p=next((x for x in items if x.get("id")==pid),None)
        if not p:return None
        row=next((x for x in (p.get("agent_work") or []) if str(x.get("agent_id","")).casefold()==key or str(x.get("agent_name","")).casefold()==key),None)
        if not row:return dict(p)
        row["status"]=status;row["updated_at"]=now
        if summary:row["latest_summary"]=str(summary)[:900]
        p["updated_at"]=now;_save(items);return dict(p)
def append_project_item(pid,section,value,metadata=None):
    if section not in {"goals","decisions","knowledge","milestones","artifacts","handoffs","summaries"}:raise ValueError("Unsupported project section.")
    with _LOCK:
        items=_load();p=next((x for x in items if x.get("id")==pid),None)
        if not p:return None
        p.setdefault(section,[]).append({"value":value,"at":_now(),**(metadata or {})});p["updated_at"]=_now();_save(items);return dict(p)
def _knowledge_allowed(x,role_l,agent_name=None):
    audience=str(x.get("audience") or "all").casefold();source=str(x.get("source_agent") or "").casefold();viewer=str(agent_name or "").casefold()
    if source and not x.get("shared") and source!=viewer:return False
    return audience in {"all",role_l} or any(w and w in role_l for w in audience.split(','))
def project_context(project,role,task,max_items=8,agent_name=None):
    full=str(project.get("share_mode") or "scoped").casefold()=="full"
    role_l=str(role or "").casefold();parts=[f"PROJECT: {project.get('name')}",f"GOAL: {project.get('goal')}",f"YOUR ASSIGNMENT: {task}"];skill=activate_project_skill(project.get("skill"))
    if skill:parts.append(f"ACTIVATED SKILL — {skill['name']}:\n{skill['instructions']}")
    decisions=[str(x.get("value",x)) for x in project.get("decisions",[])[-max_items:]]
    if decisions:parts.append("DECISIONS:\n- "+"\n- ".join(decisions))
    knowledge=[]
    for x in project.get("knowledge",[])[-max_items*2:]:
        if not isinstance(x,dict):continue
        if full or _knowledge_allowed(x,role_l,agent_name):knowledge.append(str(x.get("value",x)))
    if knowledge:parts.append("RELEVANT PROJECT KNOWLEDGE:\n- "+"\n- ".join(knowledge[-max_items:]))
    milestones=[str(x.get("value",x)) for x in project.get("milestones",[])[-max_items:]]
    if milestones:parts.append("MILESTONES:\n- "+"\n- ".join(milestones))
    if full:
        updates=[]
        for w in project.get("agent_work",[]) or []:
            if not isinstance(w,dict):continue
            if str(w.get("agent_name") or "").casefold()==str(agent_name or "").casefold():continue
            summary=w.get("latest_summary")
            if summary:updates.append(f"{w.get('agent_name')} ({w.get('role')}): {summary}")
        if updates:parts.append("TEAM UPDATES (shared, full-context mode):\n- "+"\n- ".join(updates[-max_items:]))
        parts.append("CONTEXT RULE: This project is set to full sharing. You can see every specialist's knowledge and latest result summary, same as a shared team thread.")
    else:parts.append("CONTEXT RULE: Use only this scoped project brief plus your own agent memory. Do not import another specialist's private conversation.")
    return "\n\n".join(parts)
def record_handoff(pid,from_agent,to_agent,task,team_job_id=None):
    append_project_item(pid,"handoffs",{"from":from_agent,"to":to_agent,"task":task,"team_job_id":team_job_id})
    try:
        from agentie.core.agent_registry import get_agent
        agent=get_agent(to_agent);project=get_project(pid)
        if agent and project:assign_agents(pid,[agent]);brief=project_context(project,agent.get("role") or agent.get("base"),task,agent_name=agent.get("name"));set_agent_work(pid,agent,task,team_job_id,from_agent,"queued",brief)
    except Exception:pass
def record_worker_result(pid,agent_name,role,task,result):
    compact=re.sub(r"\s+"," ",str(result or "")).strip();compact=compact if len(compact)<=900 else compact[:899].rstrip()+"…";append_project_item(pid,"summaries",compact,{"agent":agent_name,"role":role,"task":task});update_agent_work_status(pid,agent_name,"completed",compact)
def _item_values(p,section,limit=8):return [str(x.get("value",x)) if isinstance(x,dict) else str(x) for x in (p.get(section) or [])[-limit:]]
def _scoped_values(p,role,max_items=8,viewer_name=None):
    role_l=str(role or "").casefold();decisions=_item_values(p,"decisions",max_items);milestones=_item_values(p,"milestones",max_items);knowledge=[]
    for x in (p.get("knowledge") or [])[-max_items*2:]:
        if not isinstance(x,dict):continue
        if _knowledge_allowed(x,role_l,viewer_name):knowledge.append(str(x.get("value",x)))
    return decisions,knowledge[-max_items:],milestones
def project_card(p,viewer_agent_id=None):
    base={"type":"project","id":p["id"],"name":p["name"],"goal":p["goal"],"kind":p["kind"],"status":p["status"],"skill":p.get("skill"),"specialists":p.get("specialists",[]),"assigned_agents":p.get("assigned_agents",[]),"assigned_to_viewer":bool(viewer_agent_id and viewer_agent_id in (p.get("assigned_agent_ids") or [])),"updated_at":p.get("updated_at"),"share_mode":p.get("share_mode","scoped")}
    if viewer_agent_id:
        full=str(p.get("share_mode") or "scoped").casefold()=="full"
        work=next((dict(x) for x in (p.get("agent_work") or []) if str(x.get("agent_id"))==str(viewer_agent_id)),None);role=(work or {}).get("role") or "general";task=(work or {}).get("task") or "Work on this project";display_goal=f"Your delegated task: {task}. Project goal: {p.get('goal','')}";own_summary=(work or {}).get("latest_summary")
        if full:decisions=_item_values(p,"decisions");context=_item_values(p,"knowledge");milestones=_item_values(p,"milestones");summaries=_item_values(p,"summaries",8)
        else:decisions,context,milestones=_scoped_values(p,role,viewer_name=(work or {}).get("agent_name"));summaries=[own_summary] if own_summary else []
        return {**base,"goal":display_goal,"viewer_assignment":work,"goals":[f"Your delegated task: {task}"],"decisions":decisions,"context":context,"milestones":milestones,"summaries":summaries}
    return {**base,"goals":_item_values(p,"goals"),"decisions":_item_values(p,"decisions"),"context":_item_values(p,"knowledge"),"milestones":_item_values(p,"milestones"),"summaries":p.get("summaries",[])[-8:]}
def _name_from_goal(goal,kind):
    clean=re.sub(r"^(i\s+(want|plan|need)\s+to\s+|i('m| am)\s+)","",goal.strip(),flags=re.I);clean=re.sub(r"\s+"," ",clean).strip(" .?!");return clean[:70] or f"{kind.title()} project"
def _project_from_reference(text):
    lower=text.casefold()
    for p in list_projects():
        if str(p.get("name","")).casefold() in lower:return p
    if re.search(r"\b(this|that|the)\s+project\b",lower):return latest_project()
    m=re.search(r"\bproject\s+([\w][\w ._-]{1,100})",text,re.I)
    if m:
        guess=m.group(1).strip(' .?!');hit=get_project(guess)
        if hit:return hit
    return None
def _delegated_task(detail,project_name):
    value=re.sub(r"\s+"," ",str(detail or "")).strip(' .?!\"“”')
    if not value:return f"Work on project {project_name}"
    value=re.sub(re.escape(project_name),"",value,count=1,flags=re.I).strip(' .?!:;,-')
    value=re.sub(r"^(?:project\s+|for\s+|on\s+|about\s+)","",value,flags=re.I).strip(' .?!:;,-')
    value=re.sub(r"\b(?:for|on|about|of)\s*$","",value,flags=re.I).strip(' .?!:;,-')
    return value or f"Work on project {project_name}"
def _project_delegation(text):
    project=_project_from_reference(text)
    if not project:return None
    from agentie.core.agent_registry import get_agent
    from agentie.core.team_orchestrator import create_team_job,start_team_job,team_job_card
    patterns=[re.match(r"^(?:delegate|assign|give)\s+(?:(?:project\s+)?(.+?)\s+)?to\s+(.+?)[.!?]?$",text,re.I),re.match(r"^(?:have|ask|tell)\s+(.+?)\s+(?:to\s+)?work\s+together\s+(?:on|for)\s+(?:project\s+)?(.+?)[.!?]?$",text,re.I)]
    raw_agents=None;task=f"Work on project {project['name']}"
    if patterns[0]:raw_agents=patterns[0].group(2);task=_delegated_task(patterns[0].group(1),project['name'])
    elif patterns[1]:raw_agents=patterns[1].group(1);task=_delegated_task(patterns[1].group(2),project['name'])
    if not raw_agents:return None
    names=[x.strip(' .?!\"“”') for x in re.split(r"\s*,\s*|\s+and\s+",raw_agents,flags=re.I) if x.strip()];agents=[]
    for name in names:
        a=get_agent(name)
        if not a:return {"message":f"Agent {name} was not found.","card":None}
        if all(x['id']!=a['id'] for x in agents):agents.append(a)
    assign_agents(project['id'],agents);job=create_team_job(task,agents,project_id=project['id']);start_team_job(job['id']);return {"message":f"Assigned {project['name']} to {', '.join(a['name'] for a in agents)}. Task: {task}. The project is now visible from each assigned agent's workspace.","card":team_job_card(job)}
def _delete_picker():
    items=list_projects();return {"message":"Choose the project or projects you want to delete.","card":{"type":"project_delete_picker","items":[project_card(x) for x in items]}}
def _delete_request(raw):
    from agentie.tools.approval_tools import create_approval
    bits=[x.strip() for x in re.split(r"\s*,\s*|\s*;\s*",str(raw or "")) if x.strip()];projects=[];already=[];store=PROJECTS_FILE.parent/"deletions.json"
    for bit in bits:
        p=get_project(bit)
        if not p and bit.casefold().startswith("project "):p=get_project(bit[8:].strip())
        if not p:
            tomb=find_deleted("project",bit,store) or (find_deleted("project",bit[8:].strip(),store) if bit.casefold().startswith("project ") else None)
            if tomb:already.append(tomb.get("name") or bit);continue
            return {"message":f"Project {bit} was not found.","card":None}
        if all(x['id']!=p['id'] for x in projects):projects.append(p)
    if not projects:
        if already:return {"message":("Already deleted: "+", ".join(str(x) for x in already)+"."),"card":{"type":"already_deleted","entity_type":"project","names":already}}
        return _delete_picker()
    ids=[p['id'] for p in projects];names=[p['name'] for p in projects];action="delete_projects:"+",".join(ids);approval=create_approval(action,"Permanently delete "+(", ".join(names))+" from Project Brain? Historical agent chat messages are not deleted.",{"kind":"project_delete","project_ids":ids,"project_names":names});prefix=("Already deleted: "+", ".join(str(x) for x in already)+". " if already else "");return {"message":prefix+"Project deletion requires approval.","card":{"type":"approvals","items":[approval]}}
def route_project_command(message):
    text=" ".join(message.strip().split());lower=text.casefold().strip(" .?!");delegated=_project_delegation(text)
    if delegated is not None:return delegated
    m_share=re.match(r"^(?:make|set)\s+project\s+(.+?)\s+(?:fully shared|full(?:ly)? sharing|share everything|share mode full)[.!?]?$",text,re.I) or re.match(r"^(?:enable )?full (?:context )?sharing (?:for|on) project\s+(.+?)[.!?]?$",text,re.I)
    if m_share:
        p=get_project(m_share.group(1).strip())
        if not p:return {"message":"Project was not found.","card":None}
        updated=set_share_mode(p["id"],"full");return {"message":f"{updated['name']} is now fully shared — every specialist sees every other specialist's knowledge and latest result, like a shared team thread.","card":project_card(updated)}
    m_scope=re.match(r"^(?:make|set)\s+project\s+(.+?)\s+(?:scoped|scope sharing|share mode scoped)[.!?]?$",text,re.I)
    if m_scope:
        p=get_project(m_scope.group(1).strip())
        if not p:return {"message":"Project was not found.","card":None}
        updated=set_share_mode(p["id"],"scoped");return {"message":f"{updated['name']} is back to scoped sharing — each specialist gets a curated brief, no raw peer conversation.","card":project_card(updated)}
    if lower in {"delete project","delete a project","remove project","delete projects","remove projects"}:return _delete_picker()
    m_delete=re.match(r"^(?:delete|remove)\s+projects?\s+(.+?)[.!?]?$",text,re.I)
    if m_delete:return _delete_request(m_delete.group(1))
    m_rename=re.match(r"^rename\s+project\s+(.+?)\s+to\s+(.+?)[.!?]?$",text,re.I)
    if m_rename:
        p=get_project(m_rename.group(1).strip())
        if not p:return {"message":"Project was not found.","card":None}
        updated=update_project(p['id'],name=m_rename.group(2).strip(' \"“”'));return {"message":f"Renamed project to {updated['name']}.","card":project_card(updated)}
    m_goal=re.match(r"^(?:set|change|update)\s+project\s+(.+?)\s+goal\s+(?:to|as)\s+(.+?)[.!?]?$",text,re.I)
    if m_goal:
        p=get_project(m_goal.group(1).strip())
        if not p:return {"message":"Project was not found.","card":None}
        goal=m_goal.group(2).strip();update_project(p['id'],goal=goal);append_project_item(p['id'],"goals",goal,{"source":"manual"});updated=get_project(p['id']);return {"message":f"Updated {updated['name']}'s goal.","card":project_card(updated)}
    m_add=re.match(r"^add\s+(?:to\s+)?project\s+(.+?)\s+(context|decision|milestone|goal)\s*:\s*(.+)$",text,re.I)
    if not m_add:m_add=re.match(r"^add\s+(context|decision|milestone|goal)\s+to\s+project\s+(.+?)\s*:\s*(.+)$",text,re.I)
    if m_add:
        if m_add.group(1).casefold() in {"context","decision","milestone","goal"}:kind,name,value=m_add.group(1),m_add.group(2),m_add.group(3)
        else:name,kind,value=m_add.group(1),m_add.group(2),m_add.group(3)
        p=get_project(name.strip())
        if not p:return {"message":"Project was not found.","card":None}
        section={"context":"knowledge","decision":"decisions","milestone":"milestones","goal":"goals"}[kind.casefold()];updated=append_project_item(p['id'],section,value.strip(),{"source":"manual","audience":"all"} if section=="knowledge" else {"source":"manual"});return {"message":f"Added {kind.casefold()} to {p['name']}.","card":project_card(updated)}
    m_agent=re.match(r"^(?:show|list)\s+(?:the\s+)?projects?\s+(?:for|assigned to)\s+(.+?)[.!?]?$",text,re.I)
    if m_agent:
        from agentie.core.agent_registry import get_agent
        a=get_agent(m_agent.group(1).strip())
        if not a:return {"message":"Agent was not found.","card":None}
        items=projects_for_agent(a['id']);return {"message":f"{a['name']} has {len(items)} assigned project(s).","card":{"type":"projects","agent_id":a['id'],"agent_name":a['name'],"items":[project_card(x,a['id']) for x in items]}}
    m_show=re.match(r"^(?:show|open|view|inspect)\s+project\s+(.+?)[.!?]?$",text,re.I)
    if m_show:
        p=get_project(m_show.group(1).strip());return {"message":"Project was not found.","card":None} if not p else {"message":f"Here is {p['name']}.","card":project_card(p)}
    if lower in {"show projects","list projects","my projects","show my projects"}:
        items=list_projects();return {"message":f"You have {len(items)} project(s).","card":{"type":"projects","items":[project_card(x) for x in items]}}
    if re.search(r"\b(where are we|project status|how is the project|where are we so far)\b",lower):
        p=latest_project()
        if not p:return None
        return {"message":f"{p['name']} is {p['status']}. It has {len(p.get('summaries',[]))} specialist update(s) and {len(p.get('milestones',[]))} milestone(s).","card":project_card(p)}
    m=re.match(r"^(create|start|make)\s+(a\s+)?project(\s+called|\s+named)?\s+(.+?)\s+(to|for|about)\s+(.+)$",text,re.I)
    if m:
        name=m.group(4).strip(' \"“”');existing=get_project(name)
        if existing and existing.get("status")=="active":return {"message":f"Project {existing['name']} already exists. I reused the existing Project Brain instead of creating a duplicate.","card":project_card(existing)}
        p=create_project(name,m.group(6).strip());return {"message":f"Created project {p['name']}. I’ll keep specialist work separated and store only useful project summaries here.","card":project_card(p)}
    long_term=re.match(r"^(i\s+(want|plan|need)\s+to|i('m| am)\s+)(.+)$",text,re.I)
    if long_term:
        goal=text;k=_kind(goal);signals=("novel","screenplay","book","build an app","build a website","start a business","lose weight","learn ","study ","for the next month","every day","daily","weekly")
        if k!="general" and any(s in lower for s in signals):
            existing=latest_project();p=existing if existing and existing.get("goal","").casefold()==goal.casefold() else create_project(_name_from_goal(goal,k),goal,k);suggestions=PROJECT_TYPES[k]["suggestions"];return {"message":f"I’ve treated this as a long-running {k} project so it doesn’t depend on one giant chat. I activated {p['skill']} and will delegate only role-relevant context. I’ll ask only for genuinely missing information; routines/reminders still require your approval.","card":{**project_card(p),"suggested_next_steps":suggestions,"proactive":True}}
    return None