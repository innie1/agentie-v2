import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agentie.core.local_router import try_local_command
from agentie.core.runner import run_agent
from agentie.tools.approval_tools import resolve_approval
from agentie.tools.advanced_utility_tools import SCHEDULES
from agentie.tools.productivity_tools import REMINDERS

app = FastAPI(title="Agentie API", version="0.7.0", description="Local-first Agentie runtime with inline cards and persistent local utilities")
FRONTEND_FILE = Path(__file__).parent / "frontend" / "index.html"


class AgentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    agent_type: str = Field(default="general", pattern="^(general|research|coding|manager|github)$")


class AgentResponse(BaseModel):
    message: str
    result: str
    card: dict[str, Any] | None = None
    agent_type: str
    routed_by: str


class ApprovalDecision(BaseModel):
    approved: bool


def _load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _schedule_due(item: dict, now: datetime) -> bool:
    if item.get("status") != "active":
        return False
    cadence = str(item.get("cadence", "")).lower()
    hhmm = item.get("time_hhmm") or "09:00"
    try:
        hour, minute = map(int, hhmm.split(":"))
    except Exception:
        hour, minute = 9, 0
    last_raw = item.get("last_fired_at")
    last = datetime.fromisoformat(last_raw) if last_raw else None
    if cadence.startswith("every "):
        m = re.match(r"every\s+(\d+(?:\.\d+)?)\s*(minutes?|hours?)", cadence)
        if not m:
            return False
        seconds = float(m.group(1)) * (3600 if m.group(2).startswith("hour") else 60)
        base = last or datetime.fromisoformat(item.get("created_at"))
        if base.tzinfo and now.tzinfo is None:
            now = now.astimezone(base.tzinfo)
        return (now - base).total_seconds() >= seconds
    today_trigger = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < today_trigger:
        return False
    if last and last.date() == now.date():
        return False
    if cadence == "daily":
        return True
    if cadence == "weekdays":
        return now.weekday() < 5
    if cadence.startswith("weekly "):
        names = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
        return now.weekday() == names.get(cadence.split(" ", 1)[1], -1)
    return False


@app.get("/")
async def chat_ui():
    if not FRONTEND_FILE.exists():
        raise HTTPException(status_code=404, detail="Frontend not found.")
    return FileResponse(FRONTEND_FILE, media_type="text/html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "agentie-v2", "version": "0.7.0"}


@app.get("/local/events/poll")
async def poll_local_events() -> dict[str, Any]:
    now = datetime.now().astimezone()
    events: list[dict[str, Any]] = []

    reminders = _load(REMINDERS, [])
    reminders_changed = False
    for item in reminders:
        if item.get("status") != "scheduled":
            continue
        try:
            due = datetime.fromisoformat(item.get("due_at"))
            if due.tzinfo is None:
                due = due.astimezone()
        except Exception:
            continue
        if due <= now:
            events.append({"message": f"Reminder: {item.get('text', '')}", "card": {"type": "reminder", **item}})
            repeat = float(item.get("repeat_minutes") or 0)
            if repeat > 0:
                item["due_at"] = (now + timedelta(minutes=repeat)).isoformat(timespec="seconds")
            else:
                item["status"] = "delivered"
            item["last_fired_at"] = now.isoformat(timespec="seconds")
            reminders_changed = True
    if reminders_changed:
        _save(REMINDERS, reminders)

    schedules = _load(SCHEDULES, [])
    schedules_changed = False
    for item in schedules:
        try:
            if _schedule_due(item, now):
                events.append({"message": f"Scheduled reminder: {item.get('text', '')}", "card": {"type": "schedule", **item}})
                item["last_fired_at"] = now.isoformat(timespec="seconds")
                schedules_changed = True
        except Exception:
            continue
    if schedules_changed:
        _save(SCHEDULES, schedules)

    return {"events": events}


@app.post("/agent/run", response_model=AgentResponse)
async def agent_run(request: AgentRequest) -> AgentResponse:
    try:
        local_result = try_local_command(request.message)
        if local_result is not None:
            message = str(local_result.get("message", ""))
            return AgentResponse(message=message, result=message, card=local_result.get("card"), agent_type=request.agent_type, routed_by="local")
        result = await run_agent(request.message, request.agent_type)
        return AgentResponse(message=result, result=result, card=None, agent_type=request.agent_type, routed_by="llm")
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Agent run failed: {exc}") from exc


@app.post("/approvals/{approval_id}/resolve")
async def approval_resolve(approval_id: str, decision: ApprovalDecision) -> dict:
    try:
        return resolve_approval(approval_id, decision.approved)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
