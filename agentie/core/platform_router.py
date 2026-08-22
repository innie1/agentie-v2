from __future__ import annotations

import re
from typing import Any

from agentie.core.agent_lifecycle import route_agent_lifecycle_command
from agentie.core.agent_teams import route_team_structure_command
from agentie.core.capability_planner import route_capability_gap_command
from agentie.core.routine_engine import create_event_routine
from agentie.core.skill_portability import route_skill_portability_command

_EVENT_ALIASES={
    "group chat message":"agent_thread.message",
    "agent chat message":"agent_thread.message",
    "team chat message":"agent_thread.message",
    "agent reply":"agent_thread.agent_reply",
    "team reply":"agent_thread.agent_reply",
    "group chat reply":"agent_thread.agent_reply",
}

def _event_routine_command(message:str)->dict[str,Any]|None:
    text=" ".join(str(message or "").strip().split())
    m=re.match(r"^(?:create|make|set up|setup|add)\s+(?:a\s+)?routine\s+(?:called|named|titled)\s+(.+?)\s+(?:that|which)\s+when\s+(?:a|an|the)?\s*(group chat message|agent chat message|team chat message|agent reply|team reply|group chat reply)\s+(.+)$",text,re.I)
    if not m:return None
    name=m.group(1).strip(' .?!\"“”');alias=m.group(2).casefold();action=m.group(3).strip(' .?!\"“”')
    event_type=_EVENT_ALIASES[alias]
    try:item,created=create_event_routine(name=name,event_type=event_type,action=action)
    except ValueError as exc:return {"message":str(exc),"card":None}
    return {"message":f"{'Created' if created else 'Reused existing'} event routine “{item['name']}” for {alias} events.","card":{"type":"routine",**item,"duplicate_prevented":not created}}

def route_platform_command(message:str)->dict[str,Any]|None:
    for router in (route_agent_lifecycle_command,route_team_structure_command,route_skill_portability_command,route_capability_gap_command,_event_routine_command):
        result=router(message)
        if result is not None:return result
    return None
