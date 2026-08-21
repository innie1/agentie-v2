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


def _generated_employee_profile(role: str, base: str, purpose: str = "") -> dict[str, Any]:
    """Generate a useful employee profile locally from creation inputs, with no provider/API call."""
    role_text = _clean(role, 160)
    purpose_text = _clean(purpose, 800)
    low = f"{role_text} {purpose_text} {base}".casefold()
    personality = "Professional, proactive, reliable, and willing to recommend better approaches when useful"
    goal = f"Perform the {role_text or 'assigned'} role reliably and help move the user's goals forward"
    responsibilities = [
        "Handle work that belongs to this role",
        "Use available tools and skills when they improve the result",
        "Report progress, risks, and useful recommendations clearly",
    ]

    if any(x in low for x in ("sales", "outreach", "business development", "lead generation", "crm")):
        personality = "Friendly, professional, proactive, persuasive without being pushy"
        goal = "Increase qualified sales opportunities and help convert them into revenue"
        responsibilities = ["Find and qualify opportunities", "Follow up leads and customers", "Track sales context and recommend next actions"]
    elif any(x in low for x in ("marketing", "social media", "content creator", "copywriter", "brand")):
        personality = "Creative, observant, concise, audience-focused, and commercially aware"
        goal = "Grow attention, trust, and demand for the user's products or business"
        responsibilities = ["Plan and create useful marketing content", "Study audience and channel performance", "Recommend campaigns, positioning, and improvements"]
    elif any(x in low for x in ("finance", "account", "bookkeep", "budget", "financial")):
        personality = "Careful, analytical, practical, and risk-aware"
        goal = "Improve financial visibility, discipline, and decision quality"
        responsibilities = ["Track and analyze financial information", "Flag unusual costs, risks, and missing data", "Prepare budgets, comparisons, and recommendations"]
    elif any(x in low for x in ("operations", "logistics", "inventory", "supply", "procurement")):
        personality = "Organized, practical, proactive, and detail-oriented"
        goal = "Keep operations efficient, reliable, and well coordinated"
        responsibilities = ["Coordinate operational work and dependencies", "Identify bottlenecks and process risks", "Recommend practical improvements and follow-up actions"]
    elif any(x in low for x in ("support", "customer service", "customer success", "helpdesk")):
        personality = "Patient, clear, helpful, empathetic, and solution-oriented"
        goal = "Resolve customer issues quickly while protecting trust and service quality"
        responsibilities = ["Understand and resolve customer requests", "Escalate issues that need human or specialist attention", "Keep communication clear, respectful, and consistent"]
    elif any(x in low for x in ("research", "analyst", "critic", "verifier", "market research")) or base == "research":
        personality = "Curious, rigorous, skeptical, evidence-focused, and clear about uncertainty"
        goal = "Produce reliable research and recommendations that improve decisions"
        responsibilities = ["Gather and compare relevant evidence", "Separate facts from inference and uncertainty", "Summarize findings, risks, and recommended next steps"]
    elif any(x in low for x in ("developer", "engineer", "coder", "cto", "programmer", "technical")) or base == "coding":
        personality = "Systematic, practical, quality-focused, and protective of backwards compatibility"
        goal = "Build and maintain reliable software with the smallest safe changes"
        responsibilities = ["Inspect existing implementations before changing them", "Implement and test working software", "Identify technical risks and recommend maintainable solutions"]
    elif any(x in low for x in ("chief of staff", "manager", "ceo", "director", "planner", "lead")) or base == "manager":
        personality = "Organized, decisive, proactive, collaborative, and comfortable challenging weak plans"
        goal = "Coordinate the AI company so the user's goals are turned into completed work"
        responsibilities = ["Break goals into clear work and delegate appropriately", "Coordinate agents and combine their results", "Track progress, risks, missing capabilities, and decisions needing approval"]
    elif any(x in low for x in ("email", "inbox", "mail")):
        personality = "Professional, concise, tactful, attentive, and consistent"
        goal = "Manage email communication accurately and help important conversations move forward"
        responsibilities = ["Draft and organize email communication", "Identify important messages and required responses", "Use the agent's identity consistently and request approval before sending when required"]
    elif "whatsapp" in low:
        personality = "Friendly, responsive, concise, and customer-focused"
        goal = "Handle WhatsApp conversations helpfully while escalating when needed"
        responsibilities = ["Understand and route incoming WhatsApp messages", "Reply within granted permissions and platform rules", "Escalate unresolved or sensitive conversations to a human"]

    if purpose_text:
        goal = f"{goal}. Current focus: {purpose_text}"

    return {
        "personality": _clean(personality, 800),
        "goal": _clean(goal, 1200),
        "responsibilities": _clean_list(responsibilities, item_limit=400, max_items=30),
        "company_identity": "",
    }


def _public(agent: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": agent.get("id"),
        "name": agent.get("name"),
        "role": agent.get("role"),
        "base": agent.get("base"),
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
        "created_at": agent.get("created_at"),
        "updated_at": agent.get("updated_at"),
    }


def list_agents() -> list[dict[str, Any]]:
    items = [_public(item) for item in _load().get("agents", [])]
    return sorted(
        items,
        key=lambda a: (
            0 if a.get("pinned") else 1,
            int(a.get("pin_order") or 10**9) if a.get("pinned") else 10**9,
            str(a.get("created_at") or ""),
        ),
    )


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
) -> dict[str, Any]:
    name = _clean(name, 120)
    role = _clean(role, 120) or "general"
    base = base if base in VALID_BASES else "general"
    purpose = _clean(purpose, 800)
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
    generated = _generated_employee_profile(role, base, purpose)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    agent_id = "agt_" + uuid.uuid4().hex[:10]
    item = {
        "id": agent_id,
        "name": name,
        "role": role,
        "base": base,
        "purpose": purpose,
        "personality": generated["personality"],
        "goal": generated["goal"],
        "responsibilities": generated["responsibilities"],
        "company_identity": generated["company_identity"],
        "avatar_kind": "default",
        "avatar_file": None,
        "manager_id": manager_id,
        "status": "idle",
        "pinned": False,
        "pin_order": None,
        "memory_scope": f"agent:{agent_id}",
        "session_prefix": f"agent:{agent_id}:",
        "skills": sorted(set(str(x).strip() for x in (skills or []) if str(x).strip())),
        "permissions": permissions or {"delegate": base == "manager", "shared_company_memory": "read"},
        "created_at": now,
        "updated_at": now,
    }
    agents.append(item)
    data["updated_at"] = now
    _save(data)
    return {"created": True, "agent": _public(item)}


def set_agent_pinned(agent_id_or_name: str, pinned: bool = True) -> dict[str, Any]:
    data = _load()
    agents = data.setdefault("agents", [])
    key = _clean(agent_id_or_name).casefold()
    target = next((x for x in agents if str(x.get("id", "")).casefold() == key or str(x.get("name", "")).casefold() == key), None)
    if not target:
        raise ValueError("Agent was not found.")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    if pinned:
        if not target.get("pinned"):
            orders = [int(x.get("pin_order") or 0) for x in agents if x.get("pinned")]
            target["pin_order"] = (max(orders) if orders else 0) + 1
        target["pinned"] = True
    else:
        target["pinned"] = False
        target["pin_order"] = None
    target["updated_at"] = now
    data["updated_at"] = now
    _save(data)
    return _public(target)


def _owned_avatar_path(agent_id: str, filename: str | None) -> Path | None:
    if not filename:
        return None
    safe = Path(str(filename)).name
    if safe != filename or not safe.startswith(f"agent-avatar-{agent_id}-"):
        return None
    return WORKSPACE / "uploads" / safe


def _delete_owned_avatar_file(agent: dict[str, Any]) -> int:
    path = _owned_avatar_path(str(agent.get("id") or ""), agent.get("avatar_file"))
    if path and path.exists() and path.is_file():
        path.unlink(missing_ok=True)
        return 1
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
) -> dict[str, Any]:
    data = _load()
    agents = data.setdefault("agents", [])
    key = _clean(agent_id_or_name).casefold()
    target = next((x for x in agents if str(x.get("id", "")).casefold() == key or str(x.get("name", "")).casefold() == key), None)
    if not target:
        raise ValueError("Agent was not found.")
    if name is not None:
        clean = _clean(name, 120)
        if not clean:
            raise ValueError("Agent name is required.")
        if any(x is not target and str(x.get("name", "")).casefold() == clean.casefold() for x in agents):
            raise ValueError("Another agent already uses that name.")
        target["name"] = clean
    if role is not None:
        target["role"] = _clean(role, 120) or "general"
    if base is not None and base in VALID_BASES:
        target["base"] = base
    if purpose is not None:
        target["purpose"] = _clean(purpose, 800)
    if personality is not None:
        target["personality"] = _clean(personality, 800)
    if goal is not None:
        target["goal"] = _clean(goal, 1200)
    if responsibilities is not None:
        target["responsibilities"] = _clean_list(responsibilities, item_limit=400, max_items=30)
    if company_identity is not None:
        target["company_identity"] = _clean(company_identity, 400)
    target.setdefault("avatar_kind", "default")
    target.setdefault("avatar_file", None)
    target["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    data["updated_at"] = target["updated_at"]
    _save(data)
    return _public(target)


def set_agent_avatar(agent_id_or_name: str, kind: str, filename: str | None = None) -> dict[str, Any]:
    mode = _clean(kind, 40).casefold()
    if mode not in VALID_AVATAR_KINDS:
        raise ValueError("Avatar type must be default, generated, or uploaded.")
    data = _load()
    agents = data.setdefault("agents", [])
    key = _clean(agent_id_or_name).casefold()
    target = next((x for x in agents if str(x.get("id", "")).casefold() == key or str(x.get("name", "")).casefold() == key), None)
    if not target:
        raise ValueError("Agent was not found.")
    previous_file = target.get("avatar_file")
    next_file: str | None = None
    if mode == "uploaded":
        safe = Path(str(filename or "")).name
        if not safe or safe != str(filename or ""):
            raise ValueError("Avatar upload was not found.")
        owned = _owned_avatar_path(str(target["id"]), safe)
        if not owned or not owned.exists() or not owned.is_file():
            raise ValueError("Avatar upload was not found or is not owned by this agent.")
        if owned.suffix.lower() not in AVATAR_SUFFIXES:
            raise ValueError("Avatar must be an image file.")
        if owned.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Avatar image must be 8 MB or smaller.")
        try:
            with Image.open(owned) as image:
                image.verify()
        except Exception as exc:
            raise ValueError("Avatar file is not a valid image.") from exc
        next_file = safe
    target["avatar_kind"] = mode
    target["avatar_file"] = next_file
    target["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    data["updated_at"] = target["updated_at"]
    _save(data)
    if previous_file and previous_file != next_file:
        old = _owned_avatar_path(str(target["id"]), previous_file)
        if old and old.exists() and old.is_file():
            old.unlink(missing_ok=True)
    return _public(target)


def update_agent_manager(agent_id_or_name: str, manager_id_or_name: str | None) -> dict[str, Any]:
    data = _load()
    agents = data.setdefault("agents", [])
    key = _clean(agent_id_or_name).casefold()
    target = next((x for x in agents if str(x.get("id", "")).casefold() == key or str(x.get("name", "")).casefold() == key), None)
    if not target:
        raise ValueError("Agent was not found.")
    manager_id = None
    if manager_id_or_name:
        manager = get_agent(manager_id_or_name)
        if not manager:
            raise ValueError("Manager agent was not found.")
        if manager["id"] == target.get("id"):
            raise ValueError("An agent cannot manage itself.")
        manager_id = manager["id"]
    target["manager_id"] = manager_id
    target["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    _save(data)
    return _public(target)


def delete_agent(agent_id_or_name: str) -> dict[str, Any]:
    """Permanently delete an agent once; repeated calls return an already-deleted result."""
    data = _load()
    agents = data.setdefault("agents", [])
    key = _clean(agent_id_or_name).casefold()
    target = next((x for x in agents if str(x.get("id", "")).casefold() == key or str(x.get("name", "")).casefold() == key), None)
    deletion_file = WORKSPACE / "deletions.json"
    if not target:
        tombstone = find_deleted("agent", key, deletion_file)
        if tombstone:
            return {"deleted": False, "already_deleted": True, "agent": {"id": tombstone.get("entity_id"), "name": tombstone.get("name")}, "deleted_at": tombstone.get("deleted_at")}
        raise ValueError("Agent was not found.")
    public = _public(target)
    agent_id = str(target["id"])
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for item in agents:
        if item.get("manager_id") == agent_id:
            item["manager_id"] = None
            item["updated_at"] = now
    data["agents"] = [x for x in agents if x is not target]
    data["updated_at"] = now
    _save(data)
    from agentie.core.memory_store import purge_agent_memory
    from agentie.core.agent_prompt import purge_instruction_profile
    purged = purge_agent_memory(str(target.get("memory_scope") or f"agent:{agent_id}"), str(target.get("session_prefix") or f"agent:{agent_id}:"))
    instruction_profiles = purge_instruction_profile(agent_id)
    removed = _delete_owned_avatar_file(target)
    for path in (WORKSPACE / "agents" / agent_id, WORKSPACE / "agent_data" / agent_id):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    remember_deleted("agent", agent_id, public.get("name"), {"role": public.get("role")}, deletion_file)
    return {"deleted": True, "already_deleted": False, "agent": public, "purged": {**purged, "instruction_profiles": instruction_profiles, "directories": removed}}


def hierarchy() -> list[dict[str, Any]]:
    items = list_agents()
    by_manager: dict[str | None, list[dict[str, Any]]] = {}
    for item in items:
        by_manager.setdefault(item.get("manager_id"), []).append(item)

    def build(agent: dict[str, Any]) -> dict[str, Any]:
        return {**agent, "reports": [build(child) for child in by_manager.get(agent["id"], [])]}

    return [build(item) for item in by_manager.get(None, [])]
