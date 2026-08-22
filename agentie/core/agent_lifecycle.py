from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from agentie.core import agent_registry
from agentie.core.agent_prompt import get_instruction_profile,set_manual_instructions
from agentie.core.agent_registry import create_agent,get_agent,set_agent_avatar
from agentie.core.routine_engine import create_event_routine,create_routine,list_routines


def _clone_routines(source:dict[str,Any],target:dict[str,Any])->list[dict[str,Any]]:
    cloned=[]
    for item in list_routines(str(source["id"])):
        if str(item.get("status") or "active")=="deleted":continue
        try:
            if item.get("trigger_type")=="event":
                row,_=create_event_routine(name=str(item.get("name") or "Routine"),event_type=str(item.get("event_type") or ""),action=str(item.get("action") or item.get("instructions") or ""),owner_agent_id=target["id"],skill_id=item.get("skill_id"),event_filters=dict(item.get("event_filters") or {}),approval_policy=dict(item.get("approval_policy") or {}),failure_policy=str(item.get("failure_policy") or "report"))
            else:
                trigger=str(item.get("trigger") or "daily at 09:00");action=str(item.get("action") or item.get("instructions") or "");name=str(item.get("name") or "Routine")
                row,_=create_routine(f"Create a routine called {name} that {trigger} {action}",owner_agent_id=target["id"],skill_id=item.get("skill_id"),approval_policy=dict(item.get("approval_policy") or {}),failure_policy=str(item.get("failure_policy") or "report"))
            if str(item.get("status") or "active")=="paused":
                from agentie.core.routine_engine import update_routine
                row=update_routine(row["id"],status="paused")
            cloned.append(row)
        except Exception:
            continue
    return cloned


def _clone_avatar(source:dict[str,Any],target:dict[str,Any])->bool:
    kind=str(source.get("avatar_kind") or "default")
    if kind=="generated":set_agent_avatar(target["id"],"generated");return True
    if kind!="uploaded" or not source.get("avatar_file"):return False
    root=agent_registry.WORKSPACE;source_file=root/"uploads"/Path(str(source["avatar_file"])).name
    if not source_file.exists() or not source_file.is_file():return False
    suffix=source_file.suffix.lower();new_name=f"agent-avatar-{target['id']}-duplicate{suffix}";dest=root/"uploads"/new_name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source_file,dest);set_agent_avatar(target["id"],"uploaded",new_name);return True


def duplicate_agent(source_id_or_name:str,new_name:str,*,copy_routines:bool=True)->dict[str,Any]:
    """Duplicate configuration, not private memory/conversation history."""
    source=get_agent(source_id_or_name)
    if not source:raise ValueError("Agent to duplicate was not found.")
    new_name=" ".join(str(new_name or "").strip().split())[:120]
    if not new_name:raise ValueError("Give the duplicated agent a new name.")
    result=create_agent(new_name,str(source.get("role") or "General ownership"),purpose=str(source.get("purpose") or ""),manager_id=source.get("manager_id"),skills=list(source.get("skills") or []),permissions=dict(source.get("permissions") or {}),personality=str(source.get("personality") or ""),goal=str(source.get("goal") or ""),responsibilities=list(source.get("responsibilities") or []),company_identity=str(source.get("company_identity") or ""),approval_policy=dict(source.get("approval_policy") or {}),memory_policy=dict(source.get("memory_policy") or {}))
    if not result.get("created"):return {"created":False,"agent":result["agent"],"routines":[],"avatar_copied":False}
    target=result["agent"]
    profile=get_instruction_profile(source);manual=str(profile.get("manual_instructions") or "").strip()
    if manual:set_manual_instructions(target,manual)
    try:avatar_copied=_clone_avatar(source,target)
    except Exception:avatar_copied=False
    routines=_clone_routines(source,target) if copy_routines else []
    return {"created":True,"agent":get_agent(target["id"]) or target,"source_agent":source,"routines":routines,"avatar_copied":avatar_copied,"memory_copied":False,"conversation_copied":False,"learned_preferences_copied":False}

def route_agent_lifecycle_command(message:str)->dict[str,Any]|None:
    import re
    text=" ".join(str(message or "").strip().split())
    m=re.match(r"^(?:duplicate|copy|clone)\s+(?:agent\s+)?(.+?)\s+(?:as|to|called|named)\s+(.+)$",text,re.I)
    if not m:return None
    try:result=duplicate_agent(m.group(1).strip(' .?!\"“”'),m.group(2).strip(' .?!\"“”'))
    except ValueError as exc:return {"message":str(exc),"card":None}
    agent=result["agent"];content=(f"Created {agent['name']} from {result['source_agent']['name']}.\n\nCopied: profile, explicit instructions, assigned Skills, plugin/tool permissions, approval policy"+(f", and {len(result['routines'])} routine(s)" if result['routines'] else "")+".\n\nNot copied: private memory, conversation history, automatically learned preferences.")
    return {"message":f"Duplicated {result['source_agent']['name']} as {agent['name']}.","card":{"type":"note","title":f"Duplicated agent · {agent['name']}","content":content}}
