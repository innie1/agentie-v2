from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from agentie.core import agent_registry
from agentie.core.mcp_client import list_servers
from agentie.core.skill_registry import all_skills

WORKSPACE=Path.cwd()/"workspace";GLOBAL_ACCESS_FILE=WORKSPACE/"capability_access.json"


def _now():return datetime.now().astimezone().isoformat(timespec="seconds")

def _load_global():
    try:data=json.loads(GLOBAL_ACCESS_FILE.read_text(encoding="utf-8")) if GLOBAL_ACCESS_FILE.exists() else {}
    except Exception:data={}
    # Agentie previously stored allow-lists here. The current model is the inverse:
    # connected/enabled capabilities are shared by default and can only be disabled
    # at the workspace level. Old allow-lists are intentionally ignored.
    return {
        "blocked_skills":sorted({str(x).lower() for x in data.get("blocked_skills",[])}),
        "blocked_mcp_servers":sorted({str(x).lower() for x in data.get("blocked_mcp_servers",[])}),
        "updated_at":data.get("updated_at"),
    }
def _save_global(data):GLOBAL_ACCESS_FILE.parent.mkdir(parents=True,exist_ok=True);data["updated_at"]=_now();GLOBAL_ACCESS_FILE.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")

def agent_from_session(session_id):
    m=re.match(r"^agent:(agt_[a-z0-9]+):",str(session_id or ""),re.I);return agent_registry.get_agent(m.group(1)) if m else None

def _mutate_agent(key,fn):
    """Compatibility helper for agent metadata/behavior such as delegation or preferred Skills."""
    data=agent_registry._load();needle=str(key).casefold();target=next((x for x in data.get("agents",[]) if str(x.get("id","")).casefold()==needle or str(x.get("name","")).casefold()==needle),None)
    if not target:raise ValueError("Agent was not found.")
    fn(target);target["updated_at"]=_now();data["updated_at"]=target["updated_at"];agent_registry._save(data);return agent_registry.get_agent(target["id"]) or {}

def _mentioned_mcp(message):
    """Detect which connected shared MCP a natural request is referring to.

    This is routing only. It does not grant access or create an agent-level
    approval. Consequential actions are still approved by the tool/action path.
    """
    text=" ".join(str(message or "").strip().split());low=text.casefold()
    if not low:return None
    names={str(item.get("name") or "").casefold():str(item.get("name") or "") for item in list_servers()}
    if not names:return None
    # Local AgentMail history/settings commands are handled by the email preflight
    # and must not be mistaken for a remote inbox operation.
    if re.search(r"\b(?:show|view|list)\s+email\s+history\b|\bset\s+(?:my\s+)?agentmail\s+inbox\b",low):return None
    def connected(name):return names.get(name.casefold())
    google=connected("google-workspace")
    if google and re.search(r"\b(?:gmail|google\s+mail|google\s+drive|drive\s+file|google\s+docs?|google\s+sheets?|google\s+calendar)\b",low):return google
    canva=connected("canva")
    if canva and re.search(r"\bcanva\b",low):return canva
    whatsapp=connected("whatsapp")
    if whatsapp and re.search(r"\bwhats\s*app\b|\bwhatsapp\b",low):return whatsapp
    agentmail=connected("agentmail")
    if agentmail and re.search(r"\b(?:email|e-mail|inbox|mail)\b",low):return agentmail
    # If a connected MCP is named explicitly, route to it without inventing an
    # agent-level permission decision.
    for key,display in names.items():
        if key and re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])",low):return display
    return None

def global_skill_allowed(skill_id):
    sid=str(skill_id or "").lower();skill=all_skills().get(sid)
    return bool(skill and skill.get("enabled") and sid not in set(_load_global()["blocked_skills"]))

def global_mcp_allowed(name):
    key=str(name or "").lower();registered={str(item.get("name") or "").lower() for item in list_servers()}
    return bool(key and key in registered and key not in set(_load_global()["blocked_mcp_servers"]))

def set_global_skill_access(skill_id,allowed):
    sid=str(skill_id or "").lower()
    if sid not in all_skills():raise ValueError("Skill or capability was not found.")
    data=_load_global();blocked=set(data["blocked_skills"])
    (blocked.discard if allowed else blocked.add)(sid);data["blocked_skills"]=sorted(blocked);_save_global(data);return global_access_snapshot()

def set_global_mcp_access(name,allowed):
    key=str(name or "").lower();registered={str(item.get("name") or "").lower() for item in list_servers()}
    if key not in registered:raise ValueError("MCP server is not registered.")
    data=_load_global();blocked=set(data["blocked_mcp_servers"])
    (blocked.discard if allowed else blocked.add)(key);data["blocked_mcp_servers"]=sorted(blocked);_save_global(data);return global_access_snapshot()

def skill_allowed(agent,skill_id):
    """Enabled workspace Skills are available to every agent; job scope decides when to use them."""
    return global_skill_allowed(skill_id)

def mcp_allowed(agent,name):
    """Connected workspace MCP/plugins are available to every agent; action approvals still apply."""
    return global_mcp_allowed(name)

def set_skill_access(agent_id,skill_id,mode):
    if not agent_registry.get_agent(agent_id):raise ValueError("Agent was not found.")
    if str(skill_id or "").lower() not in all_skills():raise ValueError("Skill or capability was not found.")
    raise ValueError("Per-agent tool access has been removed. Manage the capability once in the workspace Plugins/Skills catalog.")

def set_mcp_access(agent_id,name,mode):
    if not agent_registry.get_agent(agent_id):raise ValueError("Agent was not found.")
    registered={str(item.get("name") or "").lower() for item in list_servers()}
    if str(name or "").lower() not in registered:raise ValueError("MCP server is not registered.")
    raise ValueError("Per-agent tool access has been removed. Manage the connected tool once in the workspace Plugins catalog.")

def global_access_snapshot():
    state=_load_global();skills=[]
    for sid,skill in sorted(all_skills().items(),key=lambda x:str(x[1].get("name",x[0])).lower()):
        skills.append({"id":sid,"name":skill.get("name",sid),"allowed":global_skill_allowed(sid),"kind":skill.get("kind"),"enabled":bool(skill.get("enabled"))})
    servers=[{"name":str(item.get("name") or ""),"allowed":global_mcp_allowed(item.get("name")),"transport":item.get("transport","streamable_http")} for item in list_servers()]
    return {"skills":skills,"mcp_servers":servers,"mode":"shared","updated_at":state.get("updated_at")}

def access_snapshot(agent_id):
    agent=agent_registry.get_agent(agent_id)
    if not agent:raise ValueError("Agent was not found.")
    skills=[]
    for sid,skill in sorted(all_skills().items(),key=lambda x:str(x[1].get("name",x[0])).lower()):
        effective=global_skill_allowed(sid);skills.append({"id":sid,"name":skill.get("name",sid),"description":skill.get("description",""),"capabilities":list(skill.get("capabilities") or []),"permissions":list(skill.get("permissions") or []),"kind":skill.get("kind"),"status":skill.get("status"),"enabled":bool(skill.get("enabled")),"inherited":True,"global_allowed":effective,"mode":"shared","effective":effective,"runtime":skill.get("runtime")})
    servers=[]
    for item in list_servers():
        name=str(item.get("name") or "");allowed=global_mcp_allowed(name);servers.append({"name":name,"transport":item.get("transport","streamable_http"),"global_allowed":allowed,"mode":"shared","allowed":allowed})
    return {"agent":agent,"capability_mode":"shared","skills":skills,"mcp_servers":servers}

def guard_agent_capability(session_id,message):
    """Tool selection is no longer an agent-level approval gate.

    Connected tools are shared workspace capabilities. Approval is attached to
    consequential actions (send, publish, delete, payment, permission change,
    etc.), not to an agent merely selecting a connected tool.
    """
    return None
