from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agentie.core import agent_registry
from agentie.core.mcp_client import list_servers
from agentie.core.skill_registry import all_skills
from agentie.tools.approval_tools import approval_is_granted, create_approval

WORKSPACE = Path.cwd() / "workspace"
GLOBAL_ACCESS_FILE = WORKSPACE / "capability_access.json"

def _now()->str:return datetime.now().astimezone().isoformat(timespec="seconds")
def _load_global()->dict[str,Any]:
    try:data=json.loads(GLOBAL_ACCESS_FILE.read_text(encoding="utf-8")) if GLOBAL_ACCESS_FILE.exists() else {}
    except Exception:data={}
    return {"skills":sorted({str(x).lower() for x in data.get("skills",[])}),"mcp_servers":sorted({str(x).lower() for x in data.get("mcp_servers",[])}),"updated_at":data.get("updated_at")}
def _save_global(data):GLOBAL_ACCESS_FILE.parent.mkdir(parents=True,exist_ok=True);data["updated_at"]=_now();GLOBAL_ACCESS_FILE.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
def agent_from_session(session_id):
    match=re.match(r"^agent:(agt_[a-z0-9]+):",str(session_id or ""),re.I);return agent_registry.get_agent(match.group(1)) if match else None
def _mutate_agent(agent_id_or_name,mutator):
    data=agent_registry._load();key=str(agent_id_or_name or "").strip().casefold();target=next((x for x in data.get("agents",[]) if str(x.get("id","")).casefold()==key or str(x.get("name","")).casefold()==key),None)
    if not target:raise ValueError("Agent was not found.")
    mutator(target);target["updated_at"]=_now();data["updated_at"]=target["updated_at"];agent_registry._save(data);return agent_registry.get_agent(str(target["id"])) or {}
def global_skill_allowed(skill_id):return str(skill_id).lower() in set(_load_global()["skills"])
def global_mcp_allowed(server_name):return str(server_name).lower() in set(_load_global()["mcp_servers"])
def set_global_skill_access(skill_id,allowed):
    sid=str(skill_id or "").strip().lower()
    if sid not in all_skills():raise ValueError("Skill was not found.")
    data=_load_global();items=set(data["skills"]);(items.add if allowed else items.discard)(sid);data["skills"]=sorted(items);_save_global(data);return global_access_snapshot()
def set_global_mcp_access(server_name,allowed):
    server=str(server_name or "").strip().lower();registered={str(x.get("name") or "").lower() for x in list_servers()}
    if server not in registered:raise ValueError("MCP server is not registered.")
    data=_load_global();items=set(data["mcp_servers"]);(items.add if allowed else items.discard)(server);data["mcp_servers"]=sorted(items);_save_global(data);return global_access_snapshot()
def _permission_sets(agent):
    p=dict(agent.get("permissions") or {});return ({str(x).lower() for x in agent.get("skills",[])},{str(x).lower() for x in p.get("blocked_skills",[])},{str(x).lower() for x in p.get("mcp_servers",[])},{str(x).lower() for x in p.get("blocked_mcp_servers",[])})
def skill_allowed(agent,skill_id):
    sid=str(skill_id).lower();skill=all_skills().get(sid)
    if not skill or not skill.get("enabled"):return False
    explicit,blocked,_,_=_permission_sets(agent)
    if sid in blocked:return False
    if sid in explicit or global_skill_allowed(sid):return True
    bases={str(x).lower() for x in skill.get("agents",[])};return "*" in bases or str(agent.get("base") or "general").lower() in bases
def mcp_allowed(agent,server_name):
    server=str(server_name).lower();_,_,explicit,blocked=_permission_sets(agent)
    if server in blocked:return False
    return server in explicit or global_mcp_allowed(server)
def set_skill_access(agent_id,skill_id,mode):
    sid=str(skill_id or "").strip().lower()
    if sid not in all_skills():raise ValueError("Skill was not found.")
    mode=str(mode or "inherit").lower()
    if mode not in {"inherit","allow","block"}:raise ValueError("Skill mode must be inherit, allow, or block.")
    def mutate(target):
        skills={str(x).lower() for x in target.get("skills",[])};p=dict(target.get("permissions") or {});blocked={str(x).lower() for x in p.get("blocked_skills",[])};skills.discard(sid);blocked.discard(sid)
        if mode=="allow":skills.add(sid)
        elif mode=="block":blocked.add(sid)
        target["skills"]=sorted(skills);p["blocked_skills"]=sorted(blocked);target["permissions"]=p
    return _mutate_agent(agent_id,mutate)
def set_mcp_access(agent_id,server_name,mode):
    server=str(server_name or "").strip().lower();registered={str(x.get("name") or "").lower() for x in list_servers()}
    if server not in registered:raise ValueError("MCP server is not registered.")
    if isinstance(mode,bool):mode="allow" if mode else "inherit"
    mode=str(mode or "inherit").lower()
    if mode not in {"inherit","allow","block"}:raise ValueError("MCP mode must be inherit, allow, or block.")
    def mutate(target):
        p=dict(target.get("permissions") or {});allowed={str(x).lower() for x in p.get("mcp_servers",[])};blocked={str(x).lower() for x in p.get("blocked_mcp_servers",[])};allowed.discard(server);blocked.discard(server)
        if mode=="allow":allowed.add(server)
        elif mode=="block":blocked.add(server)
        p["mcp_servers"]=sorted(allowed);p["blocked_mcp_servers"]=sorted(blocked);target["permissions"]=p
    return _mutate_agent(agent_id,mutate)
def global_access_snapshot():
    policy=_load_global();skills=[{"id":sid,"name":skill.get("name",sid),"description":skill.get("description",""),"allowed":sid in policy["skills"],"enabled":bool(skill.get("enabled")),"capabilities":list(skill.get("capabilities") or [])} for sid,skill in sorted(all_skills().items(),key=lambda item:str(item[1].get("name",item[0])).lower())];servers=[{"name":str(x.get("name") or ""),"transport":x.get("transport","streamable_http"),"allowed":str(x.get("name") or "").lower() in policy["mcp_servers"]} for x in list_servers()];return {"skills":skills,"mcp_servers":servers,"updated_at":policy.get("updated_at")}
def access_snapshot(agent_id_or_name):
    agent=agent_registry.get_agent(agent_id_or_name)
    if not agent:raise ValueError("Agent was not found.")
    explicit,blocked,explicit_mcps,blocked_mcps=_permission_sets(agent);skills=[]
    for sid,skill in sorted(all_skills().items(),key=lambda item:str(item[1].get("name",item[0])).lower()):
        role_default="*" in skill.get("agents",[]) or str(agent.get("base")) in skill.get("agents",[]);mode="block" if sid in blocked else "allow" if sid in explicit else "inherit";skills.append({"id":sid,"name":skill.get("name",sid),"description":skill.get("description",""),"capabilities":list(skill.get("capabilities") or []),"permissions":list(skill.get("permissions") or []),"enabled":bool(skill.get("enabled")),"inherited":role_default,"global_allowed":global_skill_allowed(sid),"mode":mode,"effective":skill_allowed(agent,sid),"runtime":skill.get("runtime")})
    servers=[]
    for item in list_servers():
        name=str(item.get("name") or "");key=name.lower();mode="block" if key in blocked_mcps else "allow" if key in explicit_mcps else "inherit";servers.append({"name":name,"transport":item.get("transport","streamable_http"),"global_allowed":global_mcp_allowed(name),"mode":mode,"allowed":mcp_allowed(agent,name)})
    return {"agent":agent,"skills":skills,"mcp_servers":servers}
def _mentioned_mcp(message):
    low=str(message or "").lower()
    if re.match(r"^\s*(?:add|remove|inspect|list|show)\s+(?:an?\s+)?mcp\b",low):return None
    for item in list_servers():
        name=str(item.get("name") or "").strip()
        if name and re.search(rf"\b{re.escape(name.lower())}\b",low) and ("mcp" in low or "plugin" in low or f"using {name.lower()}" in low or f"with {name.lower()}" in low):return name
    return None
def _mentioned_skill(message):
    low=str(message or "").lower()
    if re.match(r"^\s*(?:install|add|update|check|show)\s+last30days",low):return None
    for sid,skill in all_skills().items():
        labels={sid.replace("-"," "),str(skill.get("name") or "").lower()}
        if any(label and re.search(rf"\b{re.escape(label)}\b",low) for label in labels) and ("skill" in low or sid=="last30days"):return sid
    if re.match(r"^\s*(?:last30days|/last30days)\b",low):return "last30days"
    if re.match(r"^\s*(?:search(?:\s+the)?\s+web|web search|search online|look up online|find online)\b",low):return "research"
    if re.match(r"^\s*(?:run|execute)\s+(?:this\s+)?(?:python|code)\b",low):return "code-execution"
    return None
def _permission_card(agent,kind,capability_id,command):
    action=f"agent_access:{agent['id']}:{kind}:{capability_id.lower()}"
    if approval_is_granted(action):return {"approved":True}
    approval=create_approval(action,f"Allow {agent['name']} to use {kind.upper()} '{capability_id}' for this request.");return {"message":f"{agent['name']} needs permission to use {capability_id}. Allow it once, allow it for all agents, or deny it.","card":{"type":"agent_capability_approval","approval":approval,"agent_id":agent["id"],"agent_name":agent["name"],"capability_kind":kind,"capability_id":capability_id,"command":command}}
def guard_agent_capability(session_id,message):
    agent=agent_from_session(session_id)
    if not agent:return None
    server=_mentioned_mcp(message)
    if server and not mcp_allowed(agent,server):
        decision=_permission_card(agent,"mcp",server,message);return None if decision.get("approved") else decision
    skill_id=_mentioned_skill(message)
    if skill_id and not skill_allowed(agent,skill_id):
        decision=_permission_card(agent,"skill",skill_id,message);return None if decision.get("approved") else decision
    return None
