from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

WORKSPACE = Path.cwd() / "workspace"
AGENTS_FILE = WORKSPACE / "agents.json"
VALID_BASES = {"general", "research", "coding", "manager", "github"}


def _load() -> dict[str, Any]:
    try:
        value = json.loads(AGENTS_FILE.read_text(encoding="utf-8")) if AGENTS_FILE.exists() else {"agents": []}
        return value if isinstance(value, dict) else {"agents": []}
    except Exception:return {"agents": []}

def _save(data: dict[str, Any]) -> None:
    AGENTS_FILE.parent.mkdir(parents=True, exist_ok=True);AGENTS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
def _clean(value: str, limit: int = 240) -> str:return " ".join(str(value or "").strip().split())[:limit]
def _public(agent: dict[str, Any]) -> dict[str, Any]:
    return {"id":agent.get("id"),"name":agent.get("name"),"role":agent.get("role"),"base":agent.get("base"),"purpose":agent.get("purpose", ""),"manager_id":agent.get("manager_id"),"status":agent.get("status","idle"),"memory_scope":agent.get("memory_scope"),"session_prefix":agent.get("session_prefix"),"skills":list(agent.get("skills") or []),"permissions":dict(agent.get("permissions") or {}),"created_at":agent.get("created_at"),"updated_at":agent.get("updated_at")}
def list_agents() -> list[dict[str, Any]]:return [_public(item) for item in _load().get("agents", [])]
def get_agent(agent_id_or_name: str) -> dict[str, Any] | None:
    key=_clean(agent_id_or_name,240).casefold()
    if not key:return None
    for item in _load().get("agents",[]):
        if str(item.get("id","")).casefold()==key or str(item.get("name","")).casefold()==key:return _public(item)
    return None

def create_agent(name: str, role: str, base: str = "general", purpose: str = "", manager_id: str | None = None, skills: list[str] | None = None, permissions: dict[str, Any] | None = None) -> dict[str, Any]:
    name=_clean(name,120);role=_clean(role,120) or "general";base=base if base in VALID_BASES else "general"
    if not name:raise ValueError("Agent name is required.")
    data=_load();agents=data.setdefault("agents",[]);existing=next((x for x in agents if str(x.get("name","")).casefold()==name.casefold()),None)
    if existing:return {"created":False,"agent":_public(existing)}
    if manager_id:
        manager=get_agent(manager_id)
        if not manager:raise ValueError("Manager agent was not found.")
        manager_id=str(manager["id"])
    now=datetime.now().astimezone().isoformat(timespec="seconds");agent_id="agt_"+uuid.uuid4().hex[:10]
    item={"id":agent_id,"name":name,"role":role,"base":base,"purpose":_clean(purpose,800),"manager_id":manager_id,"status":"idle","memory_scope":f"agent:{agent_id}","session_prefix":f"agent:{agent_id}:","skills":sorted(set(str(x).strip() for x in (skills or []) if str(x).strip())),"permissions":permissions or {"delegate":base=="manager","shared_company_memory":"read"},"created_at":now,"updated_at":now}
    agents.append(item);data["updated_at"]=now;_save(data);return {"created":True,"agent":_public(item)}

def update_agent_profile(agent_id_or_name:str,*,name:str|None=None,role:str|None=None,base:str|None=None)->dict[str,Any]:
    data=_load();agents=data.setdefault("agents",[]);key=_clean(agent_id_or_name).casefold();target=next((x for x in agents if str(x.get("id","")).casefold()==key or str(x.get("name","")).casefold()==key),None)
    if not target:raise ValueError("Agent was not found.")
    if name is not None:
        clean=_clean(name,120)
        if not clean:raise ValueError("Agent name is required.")
        if any(x is not target and str(x.get("name","")).casefold()==clean.casefold() for x in agents):raise ValueError("Another agent already uses that name.")
        target["name"]=clean
    if role is not None:target["role"]=_clean(role,120) or "general"
    if base is not None and base in VALID_BASES:target["base"]=base
    target["updated_at"]=datetime.now().astimezone().isoformat(timespec="seconds");data["updated_at"]=target["updated_at"];_save(data);return _public(target)

def update_agent_manager(agent_id_or_name: str, manager_id_or_name: str | None) -> dict[str, Any]:
    data=_load();agents=data.setdefault("agents",[]);key=_clean(agent_id_or_name).casefold();target=next((x for x in agents if str(x.get("id","")).casefold()==key or str(x.get("name","")).casefold()==key),None)
    if not target:raise ValueError("Agent was not found.")
    manager_id=None
    if manager_id_or_name:
        manager=get_agent(manager_id_or_name)
        if not manager:raise ValueError("Manager agent was not found.")
        if manager["id"]==target.get("id"):raise ValueError("An agent cannot manage itself.")
        manager_id=manager["id"]
    target["manager_id"]=manager_id;target["updated_at"]=datetime.now().astimezone().isoformat(timespec="seconds");_save(data);return _public(target)

def delete_agent(agent_id_or_name: str) -> dict[str, Any]:
    """Permanently delete an agent plus its private memories, chats, context, semantic shards and learned instructions."""
    data=_load();agents=data.setdefault("agents",[]);key=_clean(agent_id_or_name).casefold();target=next((x for x in agents if str(x.get("id","")).casefold()==key or str(x.get("name","")).casefold()==key),None)
    if not target:raise ValueError("Agent was not found.")
    public=_public(target);agent_id=str(target["id"]);now=datetime.now().astimezone().isoformat(timespec="seconds")
    for item in agents:
        if item.get("manager_id")==agent_id:item["manager_id"]=None;item["updated_at"]=now
    data["agents"]=[x for x in agents if x is not target];data["updated_at"]=now;_save(data)
    from agentie.core.memory_store import purge_agent_memory
    from agentie.core.agent_prompt import purge_instruction_profile
    purged=purge_agent_memory(str(target.get("memory_scope") or f"agent:{agent_id}"),str(target.get("session_prefix") or f"agent:{agent_id}:"));instruction_profiles=purge_instruction_profile(agent_id)
    removed=0
    for path in (WORKSPACE/"agents"/agent_id,WORKSPACE/"agent_data"/agent_id):
        if path.exists():shutil.rmtree(path,ignore_errors=True);removed+=1
    return {"deleted":True,"agent":public,"purged":{**purged,"instruction_profiles":instruction_profiles,"directories":removed}}
def hierarchy() -> list[dict[str, Any]]:
    items=list_agents();by_manager:dict[str|None,list[dict[str,Any]]]={}
    for item in items:by_manager.setdefault(item.get("manager_id"),[]).append(item)
    def build(agent:dict[str,Any])->dict[str,Any]:return {**agent,"reports":[build(child) for child in by_manager.get(agent["id"],[])]}
    return [build(item) for item in by_manager.get(None,[])]
