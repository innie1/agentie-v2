from __future__ import annotations

from typing import Any

from agentie.core.agent_registry import create_agent, get_agent, list_agents
from agentie.core.project_brain import create_project, get_project, list_projects
from agentie.core.routine_engine import list_routines
from agentie.core.team_orchestrator import (
    create_team_job,
    get_team_job,
    list_team_jobs,
    start_team_job,
)
from agentie.mcp_runtime import make_server, require_approval
from agentie.tools.approval_tools import recent_approvals

SERVER_ID = "agentie-company"
mcp = make_server("Agentie Company")


def _limit(value: int, maximum: int = 100) -> int:
    return max(1, min(int(value), maximum))


@mcp.tool()
def list_company_agents(limit: int = 50) -> list[dict[str, Any]]:
    """List Agentie's persistent AI employees."""
    return list_agents()[: _limit(limit)]


@mcp.tool()
def get_company_agent(agent: str) -> dict[str, Any]:
    """Get one Agentie employee by ID or name."""
    item = get_agent(agent)
    if not item:
        raise ValueError("Agentie employee was not found.")
    return item


@mcp.tool()
def list_company_projects(limit: int = 50) -> list[dict[str, Any]]:
    """List Project Brain projects."""
    return list_projects(_limit(limit))


@mcp.tool()
def get_company_project(project: str) -> dict[str, Any]:
    """Get one Project Brain project by ID or name."""
    item = get_project(project)
    if not item:
        raise ValueError("Project was not found.")
    return item


@mcp.tool()
def list_company_jobs(limit: int = 20) -> list[dict[str, Any]]:
    """List recent multi-agent team jobs."""
    return list_team_jobs(_limit(limit))


@mcp.tool()
def get_company_job(job_id: str) -> dict[str, Any]:
    """Get one multi-agent team job."""
    item = get_team_job(job_id)
    if not item:
        raise ValueError("Team job was not found.")
    return item


@mcp.tool()
def list_company_routines(limit: int = 50) -> list[dict[str, Any]]:
    """List active and paused Agentie routines."""
    return list_routines()[: _limit(limit)]


@mcp.tool()
def list_company_approvals(status: str = "pending", limit: int = 50) -> list[dict[str, Any]]:
    """List Agentie's approval requests without resolving them."""
    clean_status = str(status or "").strip() or None
    return recent_approvals(status=clean_status, limit=_limit(limit, 500))


@mcp.tool()
def create_company_agent(
    name: str,
    role: str,
    purpose: str = "",
    goal: str = "",
    personality: str = "",
    responsibilities: list[str] | None = None,
    manager_id: str = "",
    approval_id: str = "",
) -> dict[str, Any]:
    """Create a persistent Agentie employee after explicit approval."""
    payload = {
        "name": name,
        "role": role,
        "purpose": purpose,
        "goal": goal,
        "personality": personality,
        "responsibilities": responsibilities or [],
        "manager_id": manager_id,
    }
    pending = require_approval(
        SERVER_ID,
        "create_company_agent",
        payload,
        f"Create a new Agentie employee named {name!r} with role {role!r}.",
        approval_id,
    )
    if pending:
        return pending
    item = create_agent(
        name=name,
        role=role,
        purpose=purpose,
        manager_id=manager_id or None,
        personality=personality or None,
        goal=goal or None,
        responsibilities=responsibilities or [],
    )
    return {"created": True, "agent": item}


@mcp.tool()
def create_company_project(
    name: str,
    goal: str,
    kind: str = "",
    owner_agent_id: str = "",
    approval_id: str = "",
) -> dict[str, Any]:
    """Create a Project Brain project after explicit approval."""
    payload = {"name": name, "goal": goal, "kind": kind, "owner_agent_id": owner_agent_id}
    pending = require_approval(
        SERVER_ID,
        "create_company_project",
        payload,
        f"Create Project Brain project {name!r}.",
        approval_id,
    )
    if pending:
        return pending
    item = create_project(name, goal, kind or None, owner_agent_id or None)
    return {"created": True, "project": item}


@mcp.tool()
def delegate_company_job(
    task: str,
    agents: list[str],
    project_id: str = "",
    requested_by: str = "mcp",
    approval_id: str = "",
) -> dict[str, Any]:
    """Delegate a real Agentie team job to existing employees after approval."""
    resolved = []
    for value in agents:
        item = get_agent(value)
        if not item:
            raise ValueError(f"Agentie employee {value!r} was not found.")
        resolved.append(item)
    if not resolved:
        raise ValueError("Choose at least one Agentie employee.")
    payload = {
        "task": task,
        "agent_ids": [str(item.get("id")) for item in resolved],
        "project_id": project_id,
        "requested_by": requested_by,
    }
    pending = require_approval(
        SERVER_ID,
        "delegate_company_job",
        payload,
        "Start a multi-agent Agentie job that can run tools and produce work in the background.",
        approval_id,
    )
    if pending:
        return pending
    job = create_team_job(
        task,
        resolved,
        requested_by=requested_by or "mcp",
        project_id=project_id or None,
    )
    start_team_job(str(job["id"]))
    return {"started": True, "job": job}


if __name__ == "__main__":
    mcp.run(transport="stdio")
