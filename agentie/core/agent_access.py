from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from agentie.core import agent_registry
from agentie.core.mcp_client import list_servers
from agentie.core.skill_registry import all_skills
from agentie.tools.approval_tools import approval_is_granted, create_approval


def agent_from_session(session_id: str | None) -> dict[str, Any] | None:
    match = re.match(r"^agent:(agt_[a-z0-9]+):", str(session_id or ""), re.I)
    return agent_registry.get_agent(match.group(1)) if match else None


def _mutate_agent(agent_id_or_name: str, mutator) -> dict[str, Any]:
    data = agent_registry._load()
    key = str(agent_id_or_name or "").strip().casefold()
    target = next((x for x in data.get("agents", []) if str(x.get("id", "")).casefold() == key or str(x.get("name", "")).casefold() == key), None)
    if not target:
        raise ValueError("Agent was not found.")
    mutator(target)
    target["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    data["updated_at"] = target["updated_at"]
    agent_registry._save(data)
    return agent_registry.get_agent(str(target["id"])) or {}


def skill_allowed(agent: dict[str, Any], skill_id: str) -> bool:
    skill = all_skills().get(str(skill_id).lower())
    if not skill or not skill.get("enabled"):
        return False
    permissions = dict(agent.get("permissions") or {})
    blocked = {str(x).lower() for x in permissions.get("blocked_skills", [])}
    if skill_id.lower() in blocked:
        return False
    explicit = {str(x).lower() for x in agent.get("skills", [])}
    if skill_id.lower() in explicit:
        return True
    bases = {str(x).lower() for x in skill.get("agents", [])}
    return "*" in bases or str(agent.get("base") or "general").lower() in bases


def mcp_allowed(agent: dict[str, Any], server_name: str) -> bool:
    allowed = {str(x).lower() for x in dict(agent.get("permissions") or {}).get("mcp_servers", [])}
    return str(server_name).lower() in allowed


def set_skill_access(agent_id: str, skill_id: str, mode: str) -> dict[str, Any]:
    sid = str(skill_id or "").strip().lower()
    if sid not in all_skills():
        raise ValueError("Skill was not found.")
    mode = str(mode or "inherit").lower()
    if mode not in {"inherit", "allow", "block"}:
        raise ValueError("Skill mode must be inherit, allow, or block.")
    def mutate(target):
        skills = {str(x).lower() for x in target.get("skills", [])}
        permissions = dict(target.get("permissions") or {})
        blocked = {str(x).lower() for x in permissions.get("blocked_skills", [])}
        skills.discard(sid); blocked.discard(sid)
        if mode == "allow": skills.add(sid)
        elif mode == "block": blocked.add(sid)
        target["skills"] = sorted(skills)
        permissions["blocked_skills"] = sorted(blocked)
        target["permissions"] = permissions
    return _mutate_agent(agent_id, mutate)


def set_mcp_access(agent_id: str, server_name: str, allowed: bool) -> dict[str, Any]:
    server = str(server_name or "").strip().lower()
    registered = {str(x.get("name") or "").lower() for x in list_servers()}
    if server not in registered:
        raise ValueError("MCP server is not registered.")
    def mutate(target):
        permissions = dict(target.get("permissions") or {})
        servers = {str(x).lower() for x in permissions.get("mcp_servers", [])}
        (servers.add if allowed else servers.discard)(server)
        permissions["mcp_servers"] = sorted(servers)
        target["permissions"] = permissions
    return _mutate_agent(agent_id, mutate)


def access_snapshot(agent_id_or_name: str) -> dict[str, Any]:
    agent = agent_registry.get_agent(agent_id_or_name)
    if not agent:
        raise ValueError("Agent was not found.")
    permissions = dict(agent.get("permissions") or {})
    blocked = {str(x).lower() for x in permissions.get("blocked_skills", [])}
    explicit = {str(x).lower() for x in agent.get("skills", [])}
    skills = []
    for sid, skill in sorted(all_skills().items(), key=lambda item: str(item[1].get("name", item[0])).lower()):
        inherited = "*" in skill.get("agents", []) or str(agent.get("base")) in skill.get("agents", [])
        mode = "block" if sid in blocked else "allow" if sid in explicit else "inherit"
        skills.append({"id": sid, "name": skill.get("name", sid), "description": skill.get("description", ""), "capabilities": list(skill.get("capabilities") or []), "permissions": list(skill.get("permissions") or []), "enabled": bool(skill.get("enabled")), "inherited": inherited, "mode": mode, "effective": skill_allowed(agent, sid)})
    servers = []
    for item in list_servers():
        name = str(item.get("name") or "")
        servers.append({"name": name, "transport": item.get("transport", "streamable_http"), "allowed": mcp_allowed(agent, name)})
    return {"agent": agent, "skills": skills, "mcp_servers": servers}


def _mentioned_mcp(message: str) -> str | None:
    low = str(message or "").lower()
    if re.match(r"^\s*(?:add|remove|inspect|list|show)\s+(?:an?\s+)?mcp\b", low):
        return None
    for item in list_servers():
        name = str(item.get("name") or "").strip()
        if name and re.search(rf"\b{re.escape(name.lower())}\b", low) and ("mcp" in low or "plugin" in low or f"using {name.lower()}" in low or f"with {name.lower()}" in low):
            return name
    return None


def _mentioned_skill(message: str) -> str | None:
    low = str(message or "").lower()
    for sid, skill in all_skills().items():
        labels = {sid.replace("-", " "), str(skill.get("name") or "").lower()}
        if any(label and re.search(rf"\b{re.escape(label)}\b", low) for label in labels) and "skill" in low:
            return sid
    if re.match(r"^\s*(?:search(?:\s+the)?\s+web|web search|search online|look up online|find online)\b", low):
        return "research"
    if re.match(r"^\s*(?:run|execute)\s+(?:this\s+)?(?:python|code)\b", low):
        return "code-execution"
    return None


def _permission_card(agent: dict[str, Any], kind: str, capability_id: str, command: str) -> dict[str, Any]:
    action = f"agent_access:{agent['id']}:{kind}:{capability_id.lower()}"
    if approval_is_granted(action):
        return {"approved": True}
    approval = create_approval(action, f"Allow {agent['name']} to use {kind.upper()} '{capability_id}' for this request.")
    return {"message": f"{agent['name']} needs permission to use {capability_id}. Allow it once or grant ongoing access.", "card": {"type": "agent_capability_approval", "approval": approval, "agent_id": agent["id"], "agent_name": agent["name"], "capability_kind": kind, "capability_id": capability_id, "command": command}}


def guard_agent_capability(session_id: str | None, message: str) -> dict[str, Any] | None:
    agent = agent_from_session(session_id)
    if not agent:
        return None
    server = _mentioned_mcp(message)
    if server and not mcp_allowed(agent, server):
        decision = _permission_card(agent, "mcp", server, message)
        return None if decision.get("approved") else decision
    skill_id = _mentioned_skill(message)
    if skill_id and not skill_allowed(agent, skill_id):
        decision = _permission_card(agent, "skill", skill_id, message)
        return None if decision.get("approved") else decision
    return None
