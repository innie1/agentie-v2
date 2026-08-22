from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from agentie.core.deletion_registry import find_deleted, remember_deleted

WORKSPACE = Path.cwd() / "workspace"
AGENTS_FILE = WORKSPACE / "agents.json"
# Legacy execution profiles remain an internal compatibility layer for the old
# base-agent runtime. A user's persistent agent is defined by its configured job,
# goal, responsibilities, skills, plugins and permissions instead.
VALID_BASES = {"general", "research", "coding", "manager", "github"}
VALID_AVATAR_KINDS = {"default", "generated", "uploaded"}
AVATAR_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def _load() -> dict[str, Any]:
    try:
        value = json.loads(AGENTS_FILE.read_text(encoding="utf-8")) if AGENTS_FILE.exists() else {"agents": []}
        return value if isinstance(value, dict) else {"agents": []}
    except Exception:
        return {"agents": []}


def _save(data: dict[str, Any]) -> None:
    AGENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    AGENTS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _clean(value: str, limit: int = 240) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _clean_list(values: list[str] | tuple[str, ...] | None, *, item_limit: int = 240, max_items: int = 30) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        item = _clean(str(value), item_limit)
        key = item.casefold()
        if not item or key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= max_items:
            break
    return out


def _generated_employee_profile(role: str, base: str = "general", purpose: str = "") -> dict[str, Any]:
    """Generate a neutral starting profile without guessing a predefined profession."""
    job = _clean(role, 300) or "the work assigned by the user"
    focus = _clean(purpose, 1200)
    goal = f"Own and complete the work described by the user for: {job}"
    if focus:
        goal += f". Current focus: {focus}"
    return {
        "personality": "Proactive, reliable, clear about uncertainty, and willing to recommend a better approach when evidence supports it",
        "goal": _clean(goal, 1600),
        "responsibilities": [
            f"Own work that falls within: {job}",
            "Use assigned skills, plugins, knowledge and tools only within granted permissions",
            "Report progress, blockers, meaningful risks and recommendations clearly",
        ],
        "company_identity": "",
    }


def _public(agent: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": agent.get("id"),
        "name": agent.get("name"),
        "role": agent.get("role"),
        # Kept for backward compatibility with old sessions; new UI does not
        # expose this as the user's definition of the agent.
        "base": agent.get("base", "general"),
        "runtime_profile": agent.get("runtime_profile", agent.get("base", "general")),
        "purpose": agent.get("purpose", ""),
        "personality": agent.get("personality", ""),
        "goal": agent.get("goal", ""),
        "responsibilities": list(agent.get("responsibilities") or []),
        "company_identity": agent.get("company_identity", ""),
        "avatar_kind": agent.get("avatar_kind", "default"),
        "avatar_file": agent.get("avatar_file"),
        "manager_id": agent.get("manager_id"),
        "status": agent.get("status", "idle"),
        "pinned": bool(agent.get("pinned", False)),
        "pin_order": agent.get("pin_order"),
        "memory_scope": agent.get("memory_scope"),
        "session_prefix": agent.get("session_prefix"),
        "skills": list(agent.get("skills") or []),
        "permissions": dict(agent.get("permissions") or {}),
        "approval_policy": dict(agent.get("approval_policy") or {}),
        "memory_policy": dict(agent.get("memory_policy") or {}),
        "created_at": agent.get("created_at"),
        "updated_at": agent.get("updated_at"),
    }


def list_agents() -> list[dict[str, Any]]:
    items = [_public(item) for item in _load().get("agents", [])]
    return sorted(items, key=lambda a: (0 if a.get("pinned") else 1, int(a.get("pin_order") or 10**9) if a.get("pinned") else 10**9, str(a.get("created_at") or "")))


def get_agent(agent_id_or_name: str) -> dict[str, Any] | None:
    key = _clean(agent_id_or_name, 240).casefold()
    if not key:
        return None
    for item in _load().get("agents", []):
        if str(item.get("id", "")).casefold() == key or str(item.get("name", "")).casefold() == key:
            return _public(item)
    return None


def create_agent(
    name: str,
    role: str,
    base: str = "general",
    purpose: str = "",
    manager_id: str | None = None,
    skills: list[str] | None = None,
    permissions: dict[str, Any] | None = None,
    *,
    personality: str | None = None,
    goal: str | None = None,
    responsibilities: list[str] | tuple[str, ...] | None = None,
    company_identity: str = "",
    approval_policy: dict[str, Any] | None = None,
    memory_policy: dict[str, Any] | None = None,
    runtime_profile: str = "general",
) -> dict[str, Any]:
    name = _clean(name, 120)
    role = _clean(role, 500) or "General ownership"
    purpose = _clean(purpose, 1600)
    if not name:
        raise ValueError("Agent name is required.")
    data = _load()
    agents = data.setdefault("agents", [])
    existing = next((x for x in agents if str(x.get("name", "")).casefold() == name.casefold()), None)
    if existing:
        return {"created": False, "agent": _public(existing)}
    if manager_id:
        manager = get_agent(manager_id)
        if not manager:
            raise ValueError("Manager agent was not found.")
        manager_id = str(manager["id"])
    generated = _generated_employee_profile(role, "general", purpose)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    agent_id = "agt_" + uuid.uuid4().hex[:10]
    # All newly created persistent agents are permission-driven. Existing agents
    # saved before this platform model remain legacy unless the user migrates them.
    safe_permissions = {
        "delegate": False,
        "shared_company_memory": "read",
        "capability_mode": "explicit",
        "mcp_servers": [],
        "blocked_skills": [],
        "blocked_mcp_servers": [],
    }
    safe_permissions.update(dict(permissions or {}))
    safe_permissions["capability_mode"] = "explicit"
    item = {
        "id": agent_id,
        "name": name,
        "role": role,
        # New persistent agents always use the neutral runtime. Legacy base/runtime
        # fields remain only for older stored agents and compatibility callers.
        "base": "general",
        "runtime_profile": "general",
        "purpose": purpose,
        "personality": _clean(personality if personality is not None else generated["personality"], 800),
        "goal": _clean(goal if goal is not None else generated["goal"], 1600),
        "responsibilities": _clean_list(responsibilities if responsibilities is not None else generated["responsibilities"], item_limit=500, max_items=30),
        "company_identity": _clean(company_identity, 400),
        "avatar_kind": "default",
        "avatar_file": None,
        "manager_id": manager_id,
        "status": "idle",
        "pinned": False,
        "pin_order": None,
        "memory_scope": f"agent:{agent_id}",
        "session_prefix": f"agent:{agent_id}:",
        "skills": sorted(set(str(x).strip().lower() for x in (skills or []) if str(x).strip())),
        "permissions": safe_permissions,
        "approval_policy": dict(approval_policy or {}),
        "memory_policy": dict(memory_policy or {"private_context": True, "company_knowledge": "read", "project_knowledge": "scoped"}),
        "created_at": now,
        "updated_at": now,
    }
    agents.append(item)
    data["updated_at"] = now
    _save(data)
    return {"created": True, "agent": _public(item)}


def set_agent_pinned(agent_id_or_name: str, pinned: bool = True) -> dict[str, Any]:
    data = _load();agents = data.setdefault("agents", []);key = _clean(agent_id_or_name).casefold()
    target = next((x for x in agents if str(x.get("id", "")).casefold() == key or str(x.get("name", "")).casefold() == key), None)
    if not target:raise ValueError("Agent was not found.")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    if pinned:
        if not target.get("pinned"):
            orders = [int(x.get("pin_order") or 0) for x in agents if x.get("pinned")]
            target["pin_order"] = (max(orders) if orders else 0) + 1
        target["pinned"] = True
    else:
        target["pinned"] = False;target["pin_order"] = None
    target["updated_at"] = now;data["updated_at"] = now;_save(data);return _public(target)


def _owned_avatar_path(agent_id: str, filename: str | None) -> Path | None:
    if not filename:return None
    safe = Path(str(filename)).name
    if safe != filename or not safe.startswith(f"agent-avatar-{agent_id}-"):return None
    return WORKSPACE / "uploads" / safe


def _delete_owned_avatar_file(agent: dict[str, Any]) -> int:
    path = _owned_avatar_path(str(agent.get("id") or ""), agent.get("avatar_file"))
    if path and path.exists() and path.is_file():path.unlink(missing_ok=True);return 1
    return 0


def update_agent_profile(
    agent_id_or_name: str,
    *,
    name: str | None = None,
    role: str | None = None,
    base: str | None = None,
    purpose: str | None = None,
    personality: str | None = None,
    goal: str | None = None,
    responsibilities: list[str] | tuple[str, ...] | None = None,
    company_identity: str | None = None,
    approval_policy: dict[str, Any] | None = None,
    memory_policy: dict[str, Any] | None = None,
    runtime_profile: str | None = None,
) -> dict[str, Any]:
    data = _load();agents = data.setdefault("agents", []);key = _clean(agent_id_or_name).casefold()
    target = next((x for x in agents if str(x.get("id", "")).casefold() == key or str(x.get("name", "")).casefold() == key), None)
    if not target:raise ValueError("Agent was not found.")
    if name is not None:
        clean = _clean(name, 120)
        if not clean:raise ValueError("Agent name is required.")
        if any(x is not target and str(x.get("name", "")).casefold() == clean.casefold() for x in agents):raise ValueError("Another agent already uses that name.")
        target["name"] = clean
    if role is not None:target["role"] = _clean(role, 500) or "General ownership"
    # base/runtime remain accepted for existing legacy data migrations, but new
    # persistent agents do not infer or switch them from a job title.
    if base is not None and base in VALID_BASES:target["base"] = base
    if runtime_profile is not None and runtime_profile in VALID_BASES:target["runtime_profile"] = runtime_profile
    if purpose is not None:target["purpose"] = _clean(purpose, 1600)
    if personality is not None:target["personality"] = _clean(personality, 800)
    if goal is not None:target["goal"] = _clean(goal, 1600)
    if responsibilities is not None:target["responsibilities"] = _clean_list(responsibilities, item_limit=500, max_items=30)
    if company_identity is not None:target["company_identity"] = _clean(company_identity, 400)
    if approval_policy is not None:target["approval_policy"] = dict(approval_policy)
    if memory_policy is not None:target["memory_policy"] = dict(memory_policy)
    target.setdefault("avatar_kind", "default");target.setdefault("avatar_file", None);target.setdefault("runtime_profile", target.get("base", "general"));target.setdefault("approval_policy", {});target.setdefault("memory_policy", {})
    target["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds");data["updated_at"] = target["updated_at"];_save(data);return _public(target)


def set_agent_avatar(agent_id_or_name: str, kind: str, filename: str | None = None) -> dict[str, Any]:
    mode = _clean(kind, 40).casefold()
    if mode not in VALID_AVATAR_KINDS:raise ValueError("Avatar type must be default, generated, or uploaded.")
    data = _load();agents = data.setdefault("agents", []);key = _clean(agent_id_or_name).casefold()
    target = next((x for x in agents if str(x.get("id", "")).casefold() == key or str(x.get("name", "")).casefold() == key), None)
    if not target:raise ValueError("Agent was not found.")
    previous_file = target.get("avatar_file");next_file: str | None = None
    if mode == "uploaded":
        safe = Path(str(filename or "")).name
        if not safe or safe != str(filename or ""):raise ValueError("Avatar upload was not found.")
        owned = _owned_avatar_path(str(target["id"]), safe)
        if not owned or not owned.exists() or not owned.is_file():raise ValueError("Avatar upload was not found or is not owned by this agent.")
        if owned.suffix.lower() not in AVATAR_SUFFIXES:raise ValueError("Avatar must be an image file.")
        if owned.stat().st_size > 8 * 1024 * 1024:raise ValueError("Avatar image must be 8 MB or smaller.")
        try:
            with Image.open(owned) as image:image.verify()
        except Exception as exc:raise ValueError("Avatar file is not a valid image.") from exc
        next_file = safe
    target["avatar_kind"] = mode;target["avatar_file"] = next_file;target["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds");data["updated_at"] = target["updated_at"];_save(data)
    if previous_file and previous_file != next_file:
        old = _owned_avatar_path(str(target["id"]), previous_file)
        if old and old.exists() and old.is_file():old.unlink(missing_ok=True)
    return _public(target)


def update_agent_manager(agent_id_or_name: str, manager_id_or_name: str | None) -> dict[str, Any]:
    data = _load();agents = data.setdefault("agents", []);key = _clean(agent_id_or_name).casefold()
    target = next((x for x in agents if str(x.get("id", "")).casefold() == key or str(x.get("name", "")).casefold() == key), None)
    if not target:raise ValueError("Agent was not found.")
    manager_id = None
    if manager_id_or_name:
        manager = get_agent(manager_id_or_name)
        if not manager:raise ValueError("Manager agent was not found.")
        if manager["id"] == target.get("id"):raise ValueError("An agent cannot manage itself.")
        manager_id = manager["id"]
    target["manager_id"] = manager_id;target["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds");_save(data);return _public(target)


def delete_agent(agent_id_or_name: str) -> dict[str, Any]:
    """Permanently delete an agent and every Agentie-owned resource scoped to it."""
    data = _load();agents = data.setdefault("agents", []);key = _clean(agent_id_or_name).casefold();target = next((x for x in agents if str(x.get("id", "")).casefold() == key or str(x.get("name", "")).casefold() == key), None);deletion_file = WORKSPACE / "deletions.json"
    if not target:
        tombstone = find_deleted("agent", key, deletion_file)
        if tombstone:return {"deleted": False, "already_deleted": True, "agent": {"id": tombstone.get("entity_id"), "name": tombstone.get("name")}, "deleted_at": tombstone.get("deleted_at")}
        raise ValueError("Agent was not found.")
    public = _public(target);agent_id = str(target["id"]);now = datetime.now().astimezone().isoformat(timespec="seconds")
    for item in agents:
        if item.get("manager_id") == agent_id:item["manager_id"] = None;item["updated_at"] = now
    data["agents"] = [x for x in agents if x is not target];data["updated_at"] = now;_save(data)
    from agentie.core.memory_store import purge_agent_memory
    from agentie.core.agent_prompt import purge_instruction_profile
    purged = purge_agent_memory(str(target.get("memory_scope") or f"agent:{agent_id}"), str(target.get("session_prefix") or f"agent:{agent_id}:"));instruction_profiles = purge_instruction_profile(agent_id);removed = _delete_owned_avatar_file(target)
    routine_count=0;thread_count=0
    try:
        from agentie.core.routine_engine import delete_routines_for_agent
        routine_count=delete_routines_for_agent(agent_id)
    except Exception:pass
    try:
        from agentie.core.agent_threads import remove_agent_from_threads
        thread_count=remove_agent_from_threads(agent_id)
    except Exception:pass
    for path in (WORKSPACE / "agents" / agent_id, WORKSPACE / "agent_data" / agent_id):
        if path.exists():shutil.rmtree(path, ignore_errors=True);removed += 1
    remember_deleted("agent", agent_id, public.get("name"), {"role": public.get("role")}, deletion_file)
    return {"deleted": True, "already_deleted": False, "agent": public, "purged": {**purged, "instruction_profiles": instruction_profiles, "directories": removed, "routines": routine_count, "thread_memberships": thread_count}}


def hierarchy() -> list[dict[str, Any]]:
    items = list_agents();by_manager: dict[str | None, list[dict[str, Any]]] = {}
    for item in items:by_manager.setdefault(item.get("manager_id"), []).append(item)
    def build(agent: dict[str, Any]) -> dict[str, Any]:return {**agent, "reports": [build(child) for child in by_manager.get(agent["id"], [])]}
    return [build(item) for item in by_manager.get(None, [])]
