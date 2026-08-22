from __future__ import annotations

import re
from typing import Any

from agentie.core.agent_lifecycle import route_agent_lifecycle_command
from agentie.core.agent_teams import route_team_structure_command
from agentie.core.capability_planner import route_capability_gap_command
from agentie.core.external_triggers import event_alias,normalize_event_type
from agentie.core.failure_recovery import route_recovery_command
from agentie.core.routine_engine import create_event_routine
from agentie.core.skill_library import route_skill_library_command
from agentie.core.skill_portability import route_skill_portability_command

_EVENT_ALIASES={
    "group chat message":"agent_thread.message","agent chat message":"agent_thread.message","team chat message":"agent_thread.message",
    "agent reply":"agent_thread.agent_reply","team reply":"agent_thread.agent_reply","group chat reply":"agent_thread.agent_reply",
    "file upload":"file.uploaded","file uploaded":"file.uploaded","new file":"file.uploaded",
    "whatsapp message":"whatsapp.message.received","incoming whatsapp message":"whatsapp.message.received",
    "email":"email.received","incoming email":"email.received","new email":"email.received",
    "calendar event":"calendar.event.started","calendar event starts":"calendar.event.started",
}

def _owner_from_action(action:str)->tuple[str,str|None]:
    owner_id=None;owner_match=re.search(r"\s+for\s+agent\s+([A-Za-z0-9 _.-]{1,80})$",action,re.I)
    if owner_match:
        from agentie.core.agent_registry import get_agent
        owner=get_agent(owner_match.group(1).strip())
        if not owner:raise ValueError("Routine owner agent was not found.")
        owner_id=owner["id"];action=action[:owner_match.start()].strip(" ,.;:-")
    return action,owner_id

def _event_routine_command(message:str)->dict[str,Any]|None:
    text=" ".join(str(message or "").strip().split())
    aliases="|".join(re.escape(x) for x in sorted(_EVENT_ALIASES,key=len,reverse=True))
    m=re.match(rf"^(?:create|make|set up|setup|add)\s+(?:a\s+)?routine\s+(?:called|named|titled)\s+(.+?)\s+(?:that|which)\s+when\s+(?:a|an|the)?\s*({aliases})\s+(.+)$",text,re.I)
    event_type=None
    if m:name=m.group(1).strip(' .?!\"“”');alias=m.group(2).casefold();action=m.group(3).strip(' .?!\"“”');event_type=_EVENT_ALIASES[alias]
    else:
        # Generic external webhook syntax: "when webhook crm.lead.created arrives ..."
        generic=re.match(r"^(?:create|make|set up|setup|add)\s+(?:a\s+)?routine\s+(?:called|named|titled)\s+(.+?)\s+(?:that|which)\s+when\s+webhook\s+([a-zA-Z0-9._-]+)\s+(?:arrives?|fires?|happens?)\s+(.+)$",text,re.I)
        if not generic:return None
        name=generic.group(1).strip(' .?!\"“”');event_type=normalize_event_type(generic.group(2));action=generic.group(3).strip(' .?!\"“”')
    try:action,owner_id=_owner_from_action(action);item,created=create_event_routine(name=name,event_type=event_type,action=action,owner_agent_id=owner_id)
    except ValueError as exc:return {"message":str(exc),"card":None}
    owner_text=f" · owner: {item.get('owner_agent_name')}" if item.get("owner_agent_name") else ""
    return {"message":f"{'Created' if created else 'Reused existing'} event routine “{item['name']}” for {event_type} events{owner_text}.","card":{"type":"routine",**item,"duplicate_prevented":not created}}

def route_platform_command(message:str)->dict[str,Any]|None:
    for router in (route_agent_lifecycle_command,route_team_structure_command,route_skill_library_command,route_skill_portability_command,route_capability_gap_command,route_recovery_command,_event_routine_command):
        result=router(message)
        if result is not None:return result
    return None
