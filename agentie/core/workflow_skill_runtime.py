from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agentie.core.agent_access import mcp_allowed,skill_allowed
from agentie.core.agent_registry import get_agent
from agentie.core.mcp_client import list_servers
from agentie.core.skill_registry import all_skills
from agentie.core.workflow_skills import get_workflow_skill,instruction_block,skill_card
from agentie.tools import approval_tools

WORKSPACE=Path.cwd()/"workspace"
RUNS=WORKSPACE/"skill_runs.json"
_LOCK=threading.Lock()
_SENSITIVE=re.compile(r"\b(?:password|passcode|pin|secret|api[ _-]?key|access[ _-]?token|auth(?:entication)?[ _-]?token|private[ _-]?key|cvv|cvc|card[ _-]?number)\b",re.I)
_ACCESS_ALIASES={
    "files":"files","file":"files","documents":"files","pdf":"files","docx":"files","xlsx":"files","pptx":"files",
    "research":"research","web":"research","web search":"research",
    "browser":"browser-automation","browser automation":"browser-automation","computer session":"browser-automation","browser/computer session":"browser-automation",
    "code":"code-execution","python":"code-execution","code execution":"code-execution",
    "email":"email","mail":"email","github":"github","memory":"knowledge-memory","knowledge":"knowledge-memory",
    "jobs":"jobs","delegation":"jobs","planning":"planning",
}


def _now()->str:return datetime.now().astimezone().isoformat(timespec="seconds")
def _load()->list[dict[str,Any]]:
    try:
        value=json.loads(RUNS.read_text(encoding="utf-8")) if RUNS.exists() else []
        return value if isinstance(value,list) else []
    except Exception:return []
def _save(items:list[dict[str,Any]])->None:
    RUNS.parent.mkdir(parents=True,exist_ok=True);RUNS.write_text(json.dumps(items[-1000:],indent=2,ensure_ascii=False),encoding="utf-8")
def _mutate(run_id:str,**changes)->dict[str,Any]|None:
    with _LOCK:
        items=_load();item=next((x for x in items if str(x.get("id"))==str(run_id)),None)
        if not item:return None
        item.update(changes);item["updated_at"]=_now();_save(items);return dict(item)


def list_skill_runs(*,skill_id:str|None=None,agent_id:str|None=None,limit:int=100)->list[dict[str,Any]]:
    with _LOCK:items=[dict(x) for x in _load()]
    if skill_id:items=[x for x in items if str(x.get("skill_id"))==str(skill_id)]
    if agent_id:items=[x for x in items if str(x.get("agent_id"))==str(agent_id)]
    return list(reversed(items[-max(1,min(int(limit),500)):]))
def get_skill_run(run_id:str)->dict[str,Any]|None:
    return next((x for x in list_skill_runs(limit=500) if str(x.get("id"))==str(run_id)),None)

def _safe_inputs(inputs:dict[str,Any]|None)->dict[str,Any]:
    out={}
    for key,value in dict(inputs or {}).items():
        name=str(key).strip()[:120]
        if not name:continue
        if _SENSITIVE.search(name):out[name]="<provided at runtime; not stored>"
        else:out[name]=str(value)[:4000]
    return out

def _required_input_names(skill:dict[str,Any])->list[str]:return [str(x).strip() for x in skill.get("required_inputs") or [] if str(x).strip()]
def missing_inputs(skill:dict[str,Any],inputs:dict[str,Any]|None)->list[str]:
    supplied={str(k).casefold() for k,v in dict(inputs or {}).items() if v is not None and str(v).strip()}
    return [name for name in _required_input_names(skill) if name.casefold() not in supplied]

def _known_access_id(requirement:str)->tuple[str,str]|None:
    low=" ".join(str(requirement or "").casefold().replace("/"," ").split())
    if not low:return None
    skills=all_skills()
    if low in skills:return "skill",low
    for sid,item in skills.items():
        names={str(item.get("name") or "").casefold(),*(str(x).casefold() for x in item.get("capabilities") or [])}
        if low in names:return "skill",sid
    if low in _ACCESS_ALIASES:return "skill",_ACCESS_ALIASES[low]
    servers={str(x.get("name") or "").casefold():str(x.get("name") or "") for x in list_servers()}
    if low in servers:return "mcp",servers[low]
    return None

def missing_access(skill:dict[str,Any],agent:dict[str,Any])->list[str]:
    missing=[]
    for raw in skill.get("required_access") or []:
        known=_known_access_id(str(raw))
        if not known:continue
        kind,cid=known
        allowed=skill_allowed(agent,cid) if kind=="skill" else mcp_allowed(agent,cid)
        if not allowed:missing.append(str(raw))
    return missing

def _new_run(skill:dict[str,Any],agent:dict[str,Any],inputs:dict[str,Any]|None,requested_by:str,source:str)->dict[str,Any]:
    now=_now();item={"id":"skillrun_"+uuid.uuid4().hex[:10],"skill_id":skill["id"],"skill_name":skill["name"],"agent_id":agent["id"],"agent_name":agent["name"],"status":"queued","inputs":_safe_inputs(inputs),"requested_by":str(requested_by or "user")[:120],"source":str(source or "chat")[:80],"result":None,"error":None,"approval_ids":[],"created_at":now,"updated_at":now,"started_at":None,"finished_at":None}
    with _LOCK:items=_load();items.append(item);_save(items)
    return dict(item)
def _event(run:dict[str,Any])->None:
    try:
        from agentie.core.automation_events import publish_event
        publish_event(f"skill_run.{run.get('status')}",{k:run.get(k) for k in ("id","skill_id","skill_name","agent_id","agent_name","status","result","error","source","requested_by")},source="workflow_skill_runtime",dedupe_key=f"skillrun:{run.get('id')}:{run.get('status')}")
    except Exception:pass

def skill_run_note(run:dict[str,Any])->dict[str,Any]:
    status=str(run.get("status") or "unknown").replace("_"," ").title();lines=[f"Agent: {run.get('agent_name') or 'Agent'}",f"Status: {status}"]
    if run.get("result"):lines.extend(["","Result",str(run["result"])])
    if run.get("error"):lines.extend(["","Problem",str(run["error"])])
    if run.get("approval_ids"):lines.extend(["",f"Approval required: {', '.join(map(str,run['approval_ids']))}"])
    return {"type":"note","title":f"Skill · {run.get('skill_name') or 'Workflow'}","content":"\n".join(lines),"skill_run_id":run.get("id"),"skill_id":run.get("skill_id"),"agent_id":run.get("agent_id"),"status":run.get("status")}

def _input_prompt(skill:dict[str,Any],missing:list[str])->dict[str,Any]:
    return {"message":f"Skill “{skill['name']}” needs these inputs before it can run: {', '.join(missing)}. Run it again with the missing values, for example: Run skill {skill['name']} with {missing[0]}=<value>.","card":skill_card(skill),"status":"needs_input","missing_inputs":missing}


async def execute_workflow_skill(skill_name_or_id:str,session_id:str|None,*,inputs:dict[str,Any]|None=None,requested_by:str="user",source:str="chat")->dict[str,Any]:
    """Execute an active workflow Skill through a real persistent agent.

    Active Skills live in the shared workspace catalog. Agent association is only
    an organizational preference, not a permission gate. Required capabilities
    must still be enabled/connected globally, and consequential actions still use
    Agentie's normal approval system.
    """
    skill=get_workflow_skill(skill_name_or_id)
    if not skill:return {"message":"Reusable Skill was not found.","card":None,"status":"not_found"}
    if str(skill.get("status") or "draft")!="active":return {"message":f"Skill “{skill['name']}” is {skill.get('status') or 'draft'}. Review and activate it before execution.","card":skill_card(skill),"status":"inactive"}
    if skill.get("source_workflow_id"):return {"message":"This Skill has a deterministic taught workflow and must run through the taught-workflow replay path.","card":skill_card(skill),"status":"deterministic_replay"}
    m=re.match(r"^agent:(agt_[a-z0-9]+):",str(session_id or ""),re.I);agent=get_agent(m.group(1)) if m else None
    if not agent:return {"message":f"Select an agent that should run “{skill['name']}”. Skills execute through a real agent so its identity, memory and approvals remain scoped correctly.","card":skill_card(skill),"status":"needs_agent"}
    missing=missing_inputs(skill,inputs)
    if missing:return _input_prompt(skill,missing)
    access=missing_access(skill,agent)
    if access:return {"message":f"Workspace access required for Skill “{skill['name']}” is not available: {', '.join(access)}. Enable or connect it in the shared Plugins/Skills catalog first.","card":skill_card(skill),"status":"needs_access","missing_access":access}
    run=_new_run(skill,agent,inputs,requested_by,source);run=_mutate(run["id"],status="working",started_at=_now()) or run
    before={str(x.get("id")) for x in approval_tools.recent_approvals(agent_id=agent["id"],limit=200)}
    safe_inputs={str(k):str(v) for k,v in dict(inputs or {}).items() if not _SENSITIVE.search(str(k))}
    input_block="\n".join(f"- {k}: {v}" for k,v in safe_inputs.items()) or "- No extra runtime inputs."
    prompt=(instruction_block(skill)+"\n\nRUNTIME INPUTS:\n"+input_block+"\n\nEXECUTION CONTRACT:\n"
            "Execute this reusable Skill now as the configured agent. Choose relevant capabilities from the shared workspace catalog when the task requires them. Follow the steps and decision rules, validate the expected result, and obey every approval boundary. "
            "If a required action needs approval, request the normal Agentie approval and stop at that boundary. If something cannot be verified, report the real failure instead of claiming success. Return the verified work result, not a description of what you would do.")
    try:
        from agentie.core.runner import run_agent
        output=await run_agent(prompt,"general",f"{agent['session_prefix']}skill:{run['id']}")
        approvals=[x for x in approval_tools.recent_approvals(agent_id=agent["id"],status="pending",limit=200) if str(x.get("id")) not in before]
        if approvals:
            run=_mutate(run["id"],status="awaiting_approval",result=str(output),approval_ids=[str(x.get("id")) for x in approvals]) or run;_event(run)
            return {"message":f"Skill “{skill['name']}” reached an action that needs your approval before it can continue.","card":skill_run_note(run),"run":run,"status":"awaiting_approval"}
        run=_mutate(run["id"],status="completed",result=str(output),finished_at=_now()) or run;_event(run)
        return {"message":str(output),"card":skill_run_note(run),"run":run,"status":"completed"}
    except Exception as exc:
        run=_mutate(run["id"],status="failed",error=str(exc)[:1200],finished_at=_now()) or run;_event(run)
        return {"message":f"Skill “{skill['name']}” failed: {str(exc)[:500]}","card":skill_run_note(run),"run":run,"status":"failed"}
