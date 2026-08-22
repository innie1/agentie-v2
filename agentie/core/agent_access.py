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
WORKSPACE=Path.cwd()/"workspace";GLOBAL_ACCESS_FILE=WORKSPACE/"capability_access.json"
def _now():return datetime.now().astimezone().isoformat(timespec="seconds")
def _load_global():
    try:data=json.loads(GLOBAL_ACCESS_FILE.read_text(encoding="utf-8")) if GLOBAL_ACCESS_FILE.exists() else {}
    except Exception:data={}
    return {"skills":sorted({str(x).lower() for x in data.get("skills",[])}),"mcp_servers":sorted({str(x).lower() for x in data.get("mcp_servers",[])}),"updated_at":data.get("updated_at")}
def _save_global(data):GLOBAL_ACCESS_FILE.parent.mkdir(parents=True,exist_ok=True);data["updated_at"]=_now();GLOBAL_ACCESS_FILE.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
def agent_from_session(session_id):
    m=re.match(r"^agent:(agt_[a-z0-9]+):",str(session_id or ""),re.I);return agent_registry.get_agent(m.group(1)) if m else None
def _mutate_agent(key,fn):
    data=agent_registry._load();needle=str(key).casefold();target=next((x for x in data.get("agents",[]) if str(x.get("id","")).casefold()==needle or str(x.get("name","")).casefold()==needle),None)
    if not target:raise ValueError("Agent was not found.")
    fn(target);target["updated_at"]=_now();data["updated_at"]=target["updated_at"];agent_registry._save(data);return agent_registry.get_agent(target["id"]) or {}
def global_skill_allowed(x):return str(x).lower() in set(_load_global()["skills"])
def global_mcp_allowed(x):return str(x).lower() in set(_load_global()["mcp_servers"])
def set_global_skill_access(x,allowed):
    sid=str(x).lower();
    if sid not in all_skills():raise ValueError("Skill was not found.")
    data=_load_global();s=set(data["skills"]);(s.add if allowed else s.discard)(sid);data["skills"]=sorted(s);_save_global(data);return global_access_snapshot()
def set_global_mcp_access(x,allowed):
    sid=str(x).lower();registered={str(i.get("name") or "").lower() for i in list_servers()}
    if sid not in registered:raise ValueError("MCP server is not registered.")
    data=_load_global();s=set(data["mcp_servers"]);(s.add if allowed else s.discard)(sid);data["mcp_servers"]=sorted(s);_save_global(data);return global_access_snapshot()
def _sets(agent):
    p=dict(agent.get("permissions") or {});return ({str(x).lower() for x in agent.get("skills",[])},{str(x).lower() for x in p.get("blocked_skills",[])},{str(x).lower() for x in p.get("mcp_servers",[])},{str(x).lower() for x in p.get("blocked_mcp_servers",[])})
def skill_allowed(agent,sid):
    sid=str(sid).lower();skill=all_skills().get(sid)
    if not skill or not skill.get("enabled"):return False
    allow,block,_,_=_sets(agent)
    if sid in block:return False
    if sid in allow or global_skill_allowed(sid):return True
    bases={str(x).lower() for x in skill.get("agents",[])};return "*" in bases or str(agent.get("base") or "general").lower() in bases
def mcp_allowed(agent,name):
    key=str(name).lower();_,_,allow,block=_sets(agent)
    if key in block:return False
    return key in allow or global_mcp_allowed(key)
def set_skill_access(agent_id,sid,mode):
    sid=str(sid).lower();mode=str(mode or "inherit").lower()
    if sid not in all_skills():raise ValueError("Skill was not found.")
    def fn(t):
        skills={str(x).lower() for x in t.get("skills",[])};p=dict(t.get("permissions") or {});block={str(x).lower() for x in p.get("blocked_skills",[])};skills.discard(sid);block.discard(sid)
        if mode=="allow":skills.add(sid)
        elif mode=="block":block.add(sid)
        t["skills"]=sorted(skills);p["blocked_skills"]=sorted(block);t["permissions"]=p
    return _mutate_agent(agent_id,fn)
def set_mcp_access(agent_id,name,mode):
    key=str(name).lower();registered={str(i.get("name") or "").lower() for i in list_servers()}
    if key not in registered:raise ValueError("MCP server is not registered.")
    if isinstance(mode,bool):mode="allow" if mode else "block"
    mode=str(mode or "inherit").lower()
    def fn(t):
        p=dict(t.get("permissions") or {});allow={str(x).lower() for x in p.get("mcp_servers",[])};block={str(x).lower() for x in p.get("blocked_mcp_servers",[])};allow.discard(key);block.discard(key)
        if mode=="allow":allow.add(key)
        elif mode=="block":block.add(key)
        p["mcp_servers"]=sorted(allow);p["blocked_mcp_servers"]=sorted(block);t["permissions"]=p
    return _mutate_agent(agent_id,fn)
def global_access_snapshot():
    p=_load_global();return {"skills":[{"id":sid,"name":s.get("name",sid),"allowed":sid in p["skills"]} for sid,s in all_skills().items()],"mcp_servers":[{"name":str(i.get("name") or ""),"allowed":str(i.get("name") or "").lower() in p["mcp_servers"]} for i in list_servers()],"updated_at":p.get("updated_at")}
def access_snapshot(agent_id):
    agent=agent_registry.get_agent(agent_id)
    if not agent:raise ValueError("Agent was not found.")
    allow,block,mallow,mblock=_sets(agent);skills=[]
    for sid,s in sorted(all_skills().items(),key=lambda x:str(x[1].get("name",x[0])).lower()):
        role="*" in s.get("agents",[]) or str(agent.get("base")) in s.get("agents",[]);mode="block" if sid in block else "allow" if sid in allow else "inherit";skills.append({"id":sid,"name":s.get("name",sid),"description":s.get("description",""),"capabilities":list(s.get("capabilities") or []),"permissions":list(s.get("permissions") or []),"enabled":bool(s.get("enabled")),"inherited":role,"global_allowed":global_skill_allowed(sid),"mode":mode,"effective":skill_allowed(agent,sid),"runtime":s.get("runtime")})
    servers=[]
    for i in list_servers():
        name=str(i.get("name") or "");key=name.lower();mode="block" if key in mblock else "allow" if key in mallow else "inherit";servers.append({"name":name,"transport":i.get("transport","streamable_http"),"global_allowed":global_mcp_allowed(name),"mode":mode,"allowed":mcp_allowed(agent,name)})
    return {"agent":agent,"skills":skills,"mcp_servers":servers}
def _mentioned_mcp(message):
    low=str(message or "").lower()
    if re.match(r"^\s*(?:add|remove|inspect|list|show)\s+(?:an?\s+)?mcp\b",low):return None
    servers=list_servers()
    agentmail=next((str(i.get("name") or "").strip() for i in servers if str(i.get("name") or "").lower()=="agentmail"),None)
    local_agentmail_setting=bool(re.match(r"^\s*(?:set|save|remember)\b",low) or re.search(r"\b(?:agentmail settings|email history|agentmail history)\b",low))
    natural_email=bool(re.search(r"\b(?:check|list|read|open|search|send|email|mail|reply)\b",low) and re.search(r"\b(?:email|emails|e-mail|mail|inbox|inboxes|message|messages|thread|threads)\b",low))
    if agentmail and natural_email and not local_agentmail_setting:return agentmail
    for i in servers:
        name=str(i.get("name") or "").strip()
        if name and name.lower() in low and ("mcp" in low or "plugin" in low or f"using {name.lower()}" in low):return name
    return None
def _mentioned_skill(message):
    low=str(message or "").lower()
    if re.match(r"^\s*(?:install|add|update|check|show)\s+last30days",low):return None
    if re.match(r"^\s*/?last30days\b",low):return "last30days"
    if re.match(r"^\s*(?:search(?:\s+the)?\s+web|web search|search online|look up online|find online)\b",low):return "research"
    if re.match(r"^\s*(?:run|execute)\s+(?:this\s+)?(?:python|code)\b",low):return "code-execution"
    for sid,s in all_skills().items():
        if "skill" in low and (sid.replace("-"," ") in low or str(s.get("name") or "").lower() in low):return sid
    return None
def _permission_card(agent,kind,cid,command):
    action=f"agent_access:{agent['id']}:{kind}:{cid.lower()}"
    if approval_is_granted(action):return {"approved":True}
    approval=create_approval(action,f"Allow {agent['name']} to use {kind.upper()} '{cid}' for this request.");return {"message":f"{agent['name']} needs permission to use {cid}. Allow it once, allow it for all agents, or deny it.","card":{"type":"agent_capability_approval","approval":approval,"agent_id":agent["id"],"agent_name":agent["name"],"capability_kind":kind,"capability_id":cid,"command":command}}
def guard_agent_capability(session_id,message):
    agent=agent_from_session(session_id)
    if not agent:return None
    server=_mentioned_mcp(message)
    if server and not mcp_allowed(agent,server):
        d=_permission_card(agent,"mcp",server,message);return None if d.get("approved") else d
    sid=_mentioned_skill(message)
    if sid and not skill_allowed(agent,sid):
        d=_permission_card(agent,"skill",sid,message);return None if d.get("approved") else d
    return None
