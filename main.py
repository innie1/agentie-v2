import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from agentie.core.local_router import route_local_actions
from agentie.core.runner import run_agent
from agentie.tools import local_utility_tools as local_utils
from agentie.tools.approval_tools import resolve_approval
from agentie.tools.advanced_utility_tools import SCHEDULES
from agentie.tools.productivity_tools import REMINDERS

app = FastAPI(title="Agentie API", version="0.8.2", description="Local-first Agentie runtime with fuzzy intent routing, inline cards, and persistent utilities")
FRONTEND_DIR = Path(__file__).parent / "frontend"
FRONTEND_FILE = FRONTEND_DIR / "index.html"
CARDS_JS = FRONTEND_DIR / "cards.js"
EVENTS_JS = FRONTEND_DIR / "events.js"


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
    if not path.exists(): return default
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default


def _save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _schedule_due(item: dict, now: datetime) -> bool:
    if item.get("status") != "active": return False
    cadence = str(item.get("cadence", "")).lower(); hhmm = item.get("time_hhmm") or "09:00"
    try: hour, minute = map(int, hhmm.split(":"))
    except Exception: hour, minute = 9, 0
    last_raw = item.get("last_fired_at"); last = datetime.fromisoformat(last_raw) if last_raw else None
    if cadence.startswith("every "):
        m = re.match(r"every\s+(\d+(?:\.\d+)?)\s*(minutes?|hours?)", cadence)
        if not m: return False
        seconds = float(m.group(1)) * (3600 if m.group(2).startswith("hour") else 60)
        base = last or datetime.fromisoformat(item.get("created_at"))
        if base.tzinfo and now.tzinfo is None: now = now.astimezone(base.tzinfo)
        return (now - base).total_seconds() >= seconds
    today_trigger = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < today_trigger or (last and last.date() == now.date()): return False
    if cadence == "daily": return True
    if cadence == "weekdays": return now.weekday() < 5
    if cadence.startswith("weekly "):
        names = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4,"saturday":5,"sunday":6}
        return now.weekday() == names.get(cadence.split(" ",1)[1], -1)
    return False


def _route_request_actions(message: str) -> dict:
    """Route natural multi-sentence requests without forcing one giant clause.

    Split only on sentence punctuation followed by another obvious command-like
    phrase. This preserves decimal numbers and ordinary punctuation inside notes.
    Each sentence is then passed to the existing fuzzy/local router, which can
    still split on 'then', commas, and 'and'.
    """
    command_start = (
        r"(?:calculate|calculator|calc|convert|set|start|pause|stop|reset|remind|reminder|show|list|"
        r"what|whats|tell|give|weather|wheather|forecast|temperature|wiki|wikipedia|look|rss|system|"
        r"countdown|sha256|checksum|image|inspect|scratchpad|note|save|cancel|time|clock|hey)"
    )
    normalized = re.sub(r"\s+", " ", message.strip())
    sentences = re.split(rf"(?<=[.!?])\s+(?={command_start}\b)", normalized, flags=re.IGNORECASE)
    results: list[dict] = []
    unresolved: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        routed = route_local_actions(sentence)
        results.extend(routed.get("results", []))
        unresolved.extend(routed.get("unresolved", []))
    return {"results": results, "unresolved": unresolved}


def _refresh_timer_cards(results: list[dict]) -> None:
    """Re-arm relative timers immediately before returning the completed response.

    Multi-action requests may spend time on Wikipedia, weather, or an LLM fallback
    after the timer clause is parsed. Re-arming here makes a requested 15-second
    timer actually start when the user receives the result.
    """
    for result in results:
        card = result.get("card")
        if not isinstance(card, dict) or card.get("type") != "timer":
            continue
        timer_id = str(card.get("id", ""))
        seconds = float(card.get("duration_seconds") or 0)
        if not timer_id or seconds <= 0:
            continue
        refreshed = local_utils._restart_timer(timer_id, seconds)
        if refreshed:
            card["status"] = refreshed.get("status", "running")
            card["due_at"] = refreshed.get("due_at")
            card["duration_seconds"] = seconds


def _multi_card(results: list[dict], extra_message: str | None = None) -> dict:
    items = [{"message": r.get("message", ""), "card": r.get("card")} for r in results]
    if extra_message:
        items.append({"message": extra_message, "card": None})
    return {"type": "multi", "items": items}


@app.get("/")
async def chat_ui():
    if not FRONTEND_FILE.exists(): raise HTTPException(status_code=404, detail="Frontend not found.")
    html = FRONTEND_FILE.read_text(encoding="utf-8")
    html += '\n<script src="/cards.js?v=082"></script>\n<script src="/events.js?v=082"></script>\n'
    return HTMLResponse(html, headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/cards.js")
async def cards_js():
    if not CARDS_JS.exists(): raise HTTPException(status_code=404, detail="Card renderer not found.")
    return Response(CARDS_JS.read_text(encoding="utf-8"), media_type="application/javascript", headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/events.js")
async def events_js():
    if not EVENTS_JS.exists(): raise HTTPException(status_code=404, detail="Events script not found.")
    return Response(EVENTS_JS.read_text(encoding="utf-8"), media_type="application/javascript", headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status":"ok","service":"agentie-v2","version":"0.8.2"}


@app.get("/local/events/poll")
async def poll_local_events() -> dict[str, Any]:
    now = datetime.now().astimezone(); events: list[dict[str, Any]] = []
    reminders = _load(REMINDERS, []); changed = False
    for item in reminders:
        if item.get("status") != "scheduled": continue
        try:
            due = datetime.fromisoformat(item.get("due_at")); due = due.astimezone() if due.tzinfo else due.astimezone()
        except Exception: continue
        if due <= now:
            events.append({"message":f"Reminder: {item.get('text','')}","card":{"type":"reminder",**item}})
            repeat = float(item.get("repeat_minutes") or 0)
            item["due_at"] = (now + timedelta(minutes=repeat)).isoformat(timespec="seconds") if repeat > 0 else item.get("due_at")
            if repeat <= 0: item["status"] = "delivered"
            item["last_fired_at"] = now.isoformat(timespec="seconds"); changed = True
    if changed: _save(REMINDERS, reminders)
    schedules = _load(SCHEDULES, []); changed = False
    for item in schedules:
        try:
            if _schedule_due(item, now):
                events.append({"message":f"Scheduled reminder: {item.get('text','')}","card":{"type":"schedule",**item}})
                item["last_fired_at"] = now.isoformat(timespec="seconds"); changed = True
        except Exception: continue
    if changed: _save(SCHEDULES, schedules)
    return {"events": events}


@app.post("/agent/run", response_model=AgentResponse)
async def agent_run(request: AgentRequest) -> AgentResponse:
    try:
        routed = _route_request_actions(request.message)
        local_results: list[dict] = routed.get("results", [])
        unresolved: list[str] = routed.get("unresolved", [])

        if local_results and not unresolved:
            _refresh_timer_cards(local_results)
            if len(local_results) == 1:
                item = local_results[0]
                message = str(item.get("message", ""))
                return AgentResponse(message=message, result=message, card=item.get("card"), agent_type=request.agent_type, routed_by="local")
            return AgentResponse(message="", result="", card=_multi_card(local_results), agent_type=request.agent_type, routed_by="local")

        if local_results and unresolved:
            unresolved_prompt = (
                "Handle only the following unresolved parts of the user's request. Do not repeat or redo other actions.\n\n"
                + "\n".join(f"- {part}" for part in unresolved)
            )
            try:
                llm_result = await run_agent(unresolved_prompt, request.agent_type)
            except Exception as exc:
                llm_result = "I completed the other actions, but I couldn't process: " + "; ".join(unresolved) + f". ({exc})"
            _refresh_timer_cards(local_results)
            return AgentResponse(message="", result=llm_result, card=_multi_card(local_results, llm_result), agent_type=request.agent_type, routed_by="hybrid")

        result = await run_agent(request.message, request.agent_type)
        return AgentResponse(message=result, result=result, card=None, agent_type=request.agent_type, routed_by="llm")
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Agent run failed: {exc}") from exc


@app.post("/approvals/{approval_id}/resolve")
async def approval_resolve(approval_id: str, decision: ApprovalDecision) -> dict:
    try: return resolve_approval(approval_id, decision.approved)
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000")); uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
