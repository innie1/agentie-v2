import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agents import function_tool

STORE = Path.cwd() / "workspace" / "approvals.json"

_READ_ONLY_PREFIXES = (
    "read_", "list_", "get_", "search_", "find_", "inspect_", "fetch_",
    "show_", "describe_", "query_",
)
_READ_ONLY_EXACT = {
    "fetch", "directory_tree", "git_status", "git_log", "git_diff", "git_diff_unstaged",
    "git_diff_staged", "git_show", "status", "log", "diff",
}
_MUTATING_WORDS = {
    "write", "edit", "create", "delete", "remove", "move", "rename", "update", "set", "add",
    "send", "post", "put", "patch", "execute", "run", "commit", "push", "merge", "apply",
}


def _load():
    if not STORE.exists(): return []
    try: return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception: return []
def _save(items):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
def _mcp_parts(action: str) -> tuple[str, str] | None:
    match = re.match(r"^mcp:([^:]+):([^:]+):", str(action or ""));return (match.group(1), match.group(2)) if match else None
def mcp_tool_is_read_only(tool_name: str) -> bool:
    name = str(tool_name or "").lower().strip()
    if not name:return False
    tokens = {token for token in re.split(r"[^a-z0-9]+", name) if token}
    if tokens & _MUTATING_WORDS:return False
    return name in _READ_ONLY_EXACT or name.startswith(_READ_ONLY_PREFIXES)
def get_approval(approval_id: str):
    clean_id = str(approval_id or "").removesuffix(":always")
    for item in _load():
        if item.get("id") == clean_id:return item
    return None
def recent_approvals(*,agent_id: str | None = None,status: str | None = None,limit: int = 100) -> list[dict]:
    """Public read-only approval history used by activity and workflow runtimes."""
    items=[dict(x) for x in _load()]
    if agent_id:items=[x for x in items if str((x.get("metadata") or {}).get("agent_id") or "")==str(agent_id)]
    if status:items=[x for x in items if str(x.get("status") or "")==str(status)]
    return list(reversed(items[-max(1,min(int(limit),500)):]))
def approval_is_granted(action: str, approval_id: str | None = None) -> bool:
    parts = _mcp_parts(action)
    if parts and mcp_tool_is_read_only(parts[1]):return True
    items = _load()
    if parts:
        server, tool = parts
        for item in items:
            if item.get("status") != "always":continue
            meta = item.get("metadata") or {}
            if meta.get("kind") == "mcp" and meta.get("server") == server and meta.get("tool") == tool:return True
    clean_id = str(approval_id or "").removesuffix(":always") if approval_id else None
    for item in items:
        if item.get("action") == action and item.get("status") == "approved" and not item.get("consumed_at") and (clean_id is None or item.get("id") == clean_id):
            if parts:item["consumed_at"] = datetime.now(timezone.utc).isoformat();item["status"] = "consumed";_save(items)
            return True
    return False
def consume_approval(action: str) -> bool:
    items = _load()
    for item in items:
        if item.get("action") == action and item.get("status") == "approved" and not item.get("consumed_at"):
            item["consumed_at"] = datetime.now(timezone.utc).isoformat();item["status"] = "consumed";_save(items);return True
    return False
def create_approval(action: str, reason: str, metadata: dict | None = None):
    items = _load()
    for item in items:
        if item.get("action") == action and item.get("status") == "pending":return item
    item = {"id": str(uuid.uuid4())[:8],"action": action[:500],"reason": reason[:1000],"status": "pending","created_at": datetime.now(timezone.utc).isoformat()}
    if metadata:item["metadata"] = metadata
    else:
        parts = _mcp_parts(action)
        if parts:item["metadata"] = {"kind": "mcp", "server": parts[0], "tool": parts[1]}
    items.append(item);_save(items);return item
def create_background_mcp_approval(action: str, reason: str, *, agent_id: str, agent_name: str, server: str, tool: str, command: str = ""):
    item=create_approval(action,reason,{"kind":"mcp","server":server,"tool":tool,"background":True,"agent_id":agent_id,"agent_name":agent_name,"command":command})
    return item
def poll_background_approval_events(limit: int = 20) -> list[dict]:
    """Surface background/delegated MCP approvals once through the normal approval card."""
    items=_load();events=[];changed=False;now=datetime.now(timezone.utc).isoformat()
    for item in items:
        meta=item.get("metadata") or {}
        if item.get("status")!="pending" or not meta.get("background") or item.get("background_notified_at"):continue
        events.append({"message":f"{meta.get('agent_name') or 'An agent'} needs approval to use {meta.get('server') or 'a plugin'} / {meta.get('tool') or 'tool'}.","card":{"type":"approvals","items":[item]}});item["background_notified_at"]=now;changed=True
        if len(events)>=max(1,limit):break
    if changed:_save(items)
    return events
def _execute_approved_action(item: dict):
    meta = item.get("metadata") or {};kind=meta.get("kind")
    if kind == "agent_delete":
        agent_id = str(meta.get("agent_id") or "").strip()
        if not agent_id:raise ValueError("Approved agent deletion is missing the agent id.")
        from agentie.core.agent_registry import delete_agent
        result = delete_agent(agent_id)
    elif kind == "project_delete":
        project_ids=[str(x).strip() for x in (meta.get("project_ids") or []) if str(x).strip()]
        if not project_ids:raise ValueError("Approved project deletion is missing project ids.")
        from agentie.core.project_brain import delete_project
        deleted=[];already=[]
        for project_id in project_ids:
            row=delete_project(project_id)
            if not row:continue
            if row.get("already_deleted"):already.append({"id":row.get("id"),"name":row.get("name"),"deleted_at":row.get("deleted_at")})
            else:deleted.append({"id":row.get("id"),"name":row.get("name")})
        result={"deleted_projects":deleted,"already_deleted":already,"count":len(deleted)}
    elif kind == "company_knowledge_delete":
        knowledge_id=str(meta.get("knowledge_id") or "").strip()
        if not knowledge_id:raise ValueError("Approved company knowledge deletion is missing the knowledge id.")
        from agentie.core.company_knowledge import delete_company_knowledge
        result={"knowledge_id":knowledge_id,"deleted":bool(delete_company_knowledge(knowledge_id))}
    elif kind == "company_knowledge_duplicate_add":
        statement=str(meta.get("statement") or "").strip()
        if not statement:raise ValueError("Approved repeated company knowledge is missing the statement.")
        from agentie.core.company_knowledge import force_add_duplicate_company_knowledge
        result={"added":True,"knowledge":force_add_duplicate_company_knowledge(statement),"repeated":True}
    else:return None
    item["status"] = "consumed";item["consumed_at"] = datetime.now(timezone.utc).isoformat();item["execution_result"] = result;return result
def resolve_approval(approval_id: str, approved: bool, remember: bool = False):
    raw_id = str(approval_id or "")
    if raw_id.endswith(":always"):remember = True;raw_id = raw_id[:-7]
    items = _load()
    for item in items:
        if item.get("id") == raw_id:
            if item.get("status") != "pending":raise ValueError("Approval has already been resolved.")
            if approved and remember:
                parts = _mcp_parts(str(item.get("action") or ""))
                if not parts:raise ValueError("Persistent approval is only supported for MCP tool actions.")
                item["status"] = "always";item["metadata"] = {"kind": "mcp", "server": parts[0], "tool": parts[1]}
            else:item["status"] = "approved" if approved else "denied"
            item["resolved_at"] = datetime.now(timezone.utc).isoformat()
            if approved and not remember:_execute_approved_action(item)
            _save(items)
            try:
                from agentie.core.automation_events import publish_event
                meta=item.get("metadata") or {};publish_event("approval.resolved",{"approval_id":item.get("id"),"status":item.get("status"),"approved":bool(approved),"remember":bool(remember),"agent_id":meta.get("agent_id"),"agent_name":meta.get("agent_name"),"kind":meta.get("kind"),"server":meta.get("server"),"tool":meta.get("tool")},source="approval_tools",dedupe_key=f"approval:{item.get('id')}:resolved")
            except Exception:pass
            return item
    raise ValueError("Approval not found.")
def list_persistent_mcp_permissions() -> list[dict]:
    out = []
    for item in _load():
        if item.get("status") != "always":continue
        meta = item.get("metadata") or {}
        if meta.get("kind") == "mcp":out.append({"id": item.get("id"), "server": meta.get("server"), "tool": meta.get("tool"), "created_at": item.get("resolved_at") or item.get("created_at")})
    return out
def revoke_persistent_mcp_permission(approval_id: str) -> bool:
    items = _load()
    for item in items:
        if item.get("id") == approval_id and item.get("status") == "always":item["status"] = "revoked";item["revoked_at"] = datetime.now(timezone.utc).isoformat();_save(items);return True
    return False
@function_tool
def request_approval(action: str, reason: str) -> str:return json.dumps(create_approval(action, reason))
@function_tool
def list_approvals() -> str:return json.dumps(_load(), indent=2)
