from __future__ import annotations

import json,re,uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agentie.core.agent_registry import get_agent,list_agents

WORKSPACE=Path.cwd()/"workspace";TEAMS=WORKSPACE/"agent_teams.json"

def _now()->str:return datetime.now().astimezone().isoformat(timespec="seconds")
def _load()->list[dict[str,Any]]:
    try:
        value=json.loads(TEAMS.read_text(encoding="utf-8")) if TEAMS.exists() else []
        return value if isinstance(value,list) else []
    except Exception:return []
def _save(items:list[dict[str,Any]])->None:TEAMS.parent.mkdir(parents=True,exist_ok=True);TEAMS.write_text(json.dumps(items,indent=2,ensure_ascii=False),encoding="utf-8")
def _clean(value:str,limit:int=1200)->str:return " ".join(str(value or "").strip().split())[:limit]

def _sanitize(items:list[dict[str,Any]])->list[dict[str,Any]]:
    existing={str(a["id"]):a for a in list_agents()};changed=False
    for team in items:
        ids=[]
        for aid in team.get("member_ids") or []:
            if str(aid) in existing and str(aid) not in ids:ids.append(str(aid))
        if ids!=list(team.get("member_ids") or []):team["member_ids"]=ids;changed=True
        lead=str(team.get("lead_agent_id") or "")
        if lead and lead not in ids:team["lead_agent_id"]=None;changed=True
        team["member_names"]=[existing[aid]["name"] for aid in ids]
        lead_id=team.get("lead_agent_id");team["lead_agent_name"]=existing.get(str(lead_id),{}).get("name") if lead_id else None
    if changed:_save(items)
    return items

def list_teams(agent_id:str|None=None)->list[dict[str,Any]]:
    items=_sanitize(_load())
    if agent_id:items=[x for x in items if str(agent_id) in {str(y) for y in x.get("member_ids") or []}]
    return sorted((dict(x) for x in items),key=lambda x:str(x.get("name") or "").casefold())
def get_team(name_or_id:str)->dict[str,Any]|None:
    key=_clean(name_or_id,160).casefold()
    for item in list_teams():
        if str(item.get("id") or "").casefold()==key or str(item.get("name") or "").casefold()==key:return item
    return None
def _resolve_members(values:list[str])->list[dict[str,Any]]:
    out=[]
    for value in values:
        agent=get_agent(value)
        if not agent:raise ValueError(f"Agent {value} was not found.")
        if all(x["id"]!=agent["id"] for x in out):out.append(agent)
    if not out:raise ValueError("Add at least one existing agent to the team.")
    return out
def _validate_lead(lead:str|None,members:list[dict[str,Any]])->dict[str,Any]|None:
    if not lead:return None
    agent=get_agent(lead)
    if not agent:raise ValueError("Team lead agent was not found.")
    if agent["id"] not in {x["id"] for x in members}:raise ValueError("Team lead must be a member of the team.")
    if not bool((agent.get("permissions") or {}).get("delegate")):raise ValueError(f"{agent['name']} cannot be team lead until delegation permission is enabled. A title alone does not grant authority.")
    return agent

def create_team(name:str,members:list[str],*,lead_agent_id:str|None=None,goal:str="",instructions:str="")->dict[str,Any]:
    name=_clean(name,120)
    if not name:raise ValueError("Team name is required.")
    existing=get_team(name)
    if existing:return existing
    resolved=_resolve_members(members);lead=_validate_lead(lead_agent_id,resolved);now=_now();item={"id":"team_"+uuid.uuid4().hex[:10],"name":name,"goal":_clean(goal,1600),"instructions":str(instructions or "").strip()[:6000],"member_ids":[x["id"] for x in resolved],"member_names":[x["name"] for x in resolved],"lead_agent_id":lead.get("id") if lead else None,"lead_agent_name":lead.get("name") if lead else None,"created_at":now,"updated_at":now}
    items=_load();items.append(item);_save(items);return dict(item)
def update_team(team_id_or_name:str,*,name:str|None=None,goal:str|None=None,instructions:str|None=None,lead_agent_id:str|None|object=...)->dict[str,Any]:
    items=_load();key=_clean(team_id_or_name,160).casefold();item=next((x for x in items if str(x.get("id") or "").casefold()==key or str(x.get("name") or "").casefold()==key),None)
    if not item:raise ValueError("Team was not found.")
    members=_resolve_members([str(x) for x in item.get("member_ids") or []])
    if name is not None:
        clean=_clean(name,120)
        if not clean:raise ValueError("Team name is required.")
        if any(x is not item and str(x.get("name") or "").casefold()==clean.casefold() for x in items):raise ValueError("Another team already uses that name.")
        item["name"]=clean
    if goal is not None:item["goal"]=_clean(goal,1600)
    if instructions is not None:item["instructions"]=str(instructions or "").strip()[:6000]
    if lead_agent_id is not ...:
        lead=_validate_lead(str(lead_agent_id) if lead_agent_id else None,members);item["lead_agent_id"]=lead.get("id") if lead else None;item["lead_agent_name"]=lead.get("name") if lead else None
    item["updated_at"]=_now();_save(items);return get_team(str(item["id"])) or dict(item)
def add_team_member(team_id_or_name:str,agent_id_or_name:str)->dict[str,Any]:
    items=_load();key=_clean(team_id_or_name,160).casefold();item=next((x for x in items if str(x.get("id") or "").casefold()==key or str(x.get("name") or "").casefold()==key),None)
    if not item:raise ValueError("Team was not found.")
    agent=get_agent(agent_id_or_name)
    if not agent:raise ValueError("Agent was not found.")
    ids=item.setdefault("member_ids",[])
    if agent["id"] not in ids:ids.append(agent["id"]);item["updated_at"]=_now();_save(items)
    return get_team(str(item["id"])) or dict(item)
def remove_team_member(team_id_or_name:str,agent_id_or_name:str)->dict[str,Any]:
    items=_load();key=_clean(team_id_or_name,160).casefold();item=next((x for x in items if str(x.get("id") or "").casefold()==key or str(x.get("name") or "").casefold()==key),None)
    if not item:raise ValueError("Team was not found.")
    agent=get_agent(agent_id_or_name);aid=str(agent.get("id")) if agent else str(agent_id_or_name)
    item["member_ids"]=[x for x in item.get("member_ids") or [] if str(x)!=aid]
    if str(item.get("lead_agent_id") or "")==aid:item["lead_agent_id"]=None;item["lead_agent_name"]=None
    item["updated_at"]=_now();_save(items);return get_team(str(item["id"])) or dict(item)
def delete_team(team_id_or_name:str)->dict[str,Any]:
    items=_load();key=_clean(team_id_or_name,160).casefold();item=next((x for x in items if str(x.get("id") or "").casefold()==key or str(x.get("name") or "").casefold()==key),None)
    if not item:raise ValueError("Team was not found.")
    _save([x for x in items if x is not item]);return dict(item)
def teams_for_agent(agent_id:str)->list[dict[str,Any]]:return list_teams(agent_id)
def team_context(agent:dict[str,Any])->str:
    teams=teams_for_agent(str(agent.get("id") or ""));blocks=[]
    for team in teams:
        members=", ".join(team.get("member_names") or []);lead=team.get("lead_agent_name") or "No lead"
        lines=[f"TEAM: {team.get('name')}",f"Members: {members}",f"Lead: {lead}"]
        if team.get("goal"):lines.append(f"Team goal: {team['goal']}")
        if team.get("instructions"):lines.append(f"Team instructions: {team['instructions']}")
        lines.append("Team membership provides collaboration context only. It does not grant tools, plugin access, delegation authority, or approval bypasses.")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
def team_note(team:dict[str,Any])->dict[str,Any]:
    lines=[f"Members: {', '.join(team.get('member_names') or []) or 'None'}",f"Lead: {team.get('lead_agent_name') or 'None'}"]
    if team.get("goal"):lines.extend(["",f"Goal: {team['goal']}"])
    if team.get("instructions"):lines.extend(["",f"Instructions: {team['instructions']}"])
    return {"type":"note","title":f"Team · {team.get('name') or 'Team'}","content":"\n".join(lines)}
def teams_note(items:list[dict[str,Any]])->dict[str,Any]:
    content="\n\n".join(f"{x.get('name')} · lead: {x.get('lead_agent_name') or 'none'} · members: {', '.join(x.get('member_names') or []) or 'none'}" for x in items) or "No user-created teams yet."
    return {"type":"note","title":"Agent teams","content":content}

def route_team_structure_command(message:str)->dict[str,Any]|None:
    text=" ".join(str(message or "").strip().split());lower=text.casefold().strip(" .?!")
    if lower in {"teams","show teams","list teams","show departments","list departments","departments"}:
        items=list_teams();return {"message":f"You have {len(items)} user-created team(s).","card":teams_note(items)}
    m=re.match(r"^(?:create|make|start)\s+(?:a\s+)?(?:team|department)\s+(?:called|named)\s+(.+?)\s+with\s+(.+)$",text,re.I)
    if m:
        name=m.group(1).strip(' .?!\"“”');members=[x.strip(' .?!\"“”') for x in re.split(r"\s*,\s*|\s+and\s+",m.group(2),flags=re.I) if x.strip()]
        try:item=create_team(name,members)
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"Created team “{item['name']}”.","card":team_note(item)}
    m=re.match(r"^(?:show|open)\s+(?:team|department)\s+(.+)$",text,re.I)
    if m:
        item=get_team(m.group(1).strip(' .?!\"“”'));return {"message":"Team was not found.","card":None} if not item else {"message":f"Here is team “{item['name']}”.","card":team_note(item)}
    m=re.match(r"^(?:set|make)\s+(.+?)\s+(?:the\s+)?lead\s+(?:of|for)\s+(?:team|department)\s+(.+)$",text,re.I)
    if m:
        try:item=update_team(m.group(2).strip(),lead_agent_id=m.group(1).strip())
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"{item.get('lead_agent_name')} now leads “{item['name']}”.","card":team_note(item)}
    m=re.match(r"^(?:add)\s+(.+?)\s+to\s+(?:team|department)\s+(.+)$",text,re.I)
    if m:
        try:item=add_team_member(m.group(2).strip(),m.group(1).strip())
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"Added {m.group(1).strip()} to “{item['name']}”.","card":team_note(item)}
    m=re.match(r"^(?:remove)\s+(.+?)\s+from\s+(?:team|department)\s+(.+)$",text,re.I)
    if m:
        try:item=remove_team_member(m.group(2).strip(),m.group(1).strip())
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"Removed {m.group(1).strip()} from “{item['name']}”.","card":team_note(item)}
    return None
