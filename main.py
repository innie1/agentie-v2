import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from agentie.core.conversation_loop import consume_followup, detect_incomplete_intent
from agentie.core.file_service import MAX_FILE_BYTES, run_action, save_upload
from agentie.core.local_router import route_local_actions
from agentie.core.memory_store import add_message
from agentie.core.pdf_service import try_pdf_request
from agentie.core.provider_gate import local_fallback_message, provider_allowed
from agentie.core.reference_router import remember_active_from_card, try_active_reference
from agentie.core.runner import run_agent
from agentie.tools import local_utility_tools as local_utils
from agentie.tools.approval_tools import resolve_approval
from agentie.tools.advanced_utility_tools import SCHEDULES
from agentie.tools.productivity_tools import REMINDERS

app = FastAPI(title="Agentie API", version="1.4.0", description="Local-first Agentie runtime with provider gating, persistent memory, active-object references, local PDF creation, uploads, cards, and conversational routing")
FRONTEND_DIR = Path(__file__).parent / "frontend"
FRONTEND_FILE = FRONTEND_DIR / "index.html"
CARDS_JS = FRONTEND_DIR / "cards.js"
EVENTS_JS = FRONTEND_DIR / "events.js"
UPLOAD_JS = FRONTEND_DIR / "upload.js"


class AgentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    agent_type: str = Field(default="general", pattern="^(general|research|coding|manager|github)$")
    session_id: str | None = Field(default=None, max_length=200)


class AgentResponse(BaseModel):
    message: str
    result: str
    card: dict[str, Any] | None = None
    agent_type: str
    routed_by: str


class ApprovalDecision(BaseModel):
    approved: bool


class FileAction(BaseModel):
    action: str = Field(pattern="^(inspect|checksum|extract|text|preview)$")


def _load(path: Path, default):
    if not path.exists(): return default
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default


def _save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _record_local(session_id: str, user_message: str, assistant_message: str, card: dict[str, Any] | None, agent_type: str, routed_by: str) -> None:
    add_message(session_id, "user", user_message, {"agent_type": agent_type, "routed_by": routed_by})
    add_message(session_id, "assistant", assistant_message, {"agent_type": agent_type, "routed_by": routed_by})
    remember_active_from_card(session_id, card)


def _schedule_due(item: dict, now: datetime) -> bool:
    if item.get("status") != "active": return False
    cadence = str(item.get("cadence", "")).lower(); hhmm = item.get("time_hhmm") or "09:00"
    try: hour, minute = map(int, hhmm.split(":"))
    except Exception: hour, minute = 9, 0
    last_raw = item.get("last_fired_at"); last = datetime.fromisoformat(last_raw) if last_raw else None
    if cadence.startswith("every "):
        match = re.match(r"every\s+(\d+(?:\.\d+)?)\s*(minutes?|hours?)", cadence)
        if not match: return False
        seconds = float(match.group(1)) * (3600 if match.group(2).startswith("hour") else 60)
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
    command_start = (
        r"(?:calculate|calculator|calc|convert|set|start|pause|stop|reset|remind|reminder|show|list|"
        r"what|whats|tell|give|weather|wheather|forecast|temperature|wiki|wikipedia|look|rss|system|"
        r"countdown|sha256|checksum|image|inspect|scratchpad|note|save|cancel|time|clock|hey)"
    )
    normalized = re.sub(r"\s+", " ", message.strip())
    sentences = re.split(rf"(?<=[.!?])\s+(?={command_start}\b)", normalized, flags=re.IGNORECASE)
    results: list[dict] = []; unresolved: list[str] = []
    for sentence in sentences:
        if not sentence.strip(): continue
        routed = route_local_actions(sentence.strip())
        results.extend(routed.get("results", [])); unresolved.extend(routed.get("unresolved", []))
    return {"results": results, "unresolved": unresolved}


def _refresh_timer_cards(results: list[dict]) -> None:
    for result in results:
        card = result.get("card")
        if not isinstance(card, dict) or card.get("type") != "timer": continue
        timer_id = str(card.get("id", "")); seconds = float(card.get("duration_seconds") or 0)
        if not timer_id or seconds <= 0: continue
        refreshed = local_utils._restart_timer(timer_id, seconds)
        if refreshed:
            card["status"] = refreshed.get("status", "running")
            card["due_at"] = refreshed.get("due_at")
            card["duration_seconds"] = seconds


def _multi_card(results: list[dict], extra_message: str | None = None) -> dict:
    items = [{"message": r.get("message", ""), "card": r.get("card")} for r in results]
    if extra_message: items.append({"message": extra_message, "card": None})
    return {"type": "multi", "items": items}


def _result_summary(results: list[dict], fallback: str = "") -> str:
    messages = [str(item.get("message", "")).strip() for item in results if str(item.get("message", "")).strip()]
    return "\n".join(messages) or fallback


@app.get("/")
async def chat_ui():
    if not FRONTEND_FILE.exists(): raise HTTPException(status_code=404, detail="Frontend not found.")
    html = FRONTEND_FILE.read_text(encoding="utf-8")
    html += '\n<script src="/cards.js?v=140"></script>\n<script src="/events.js?v=140"></script>\n<script src="/upload.js?v=140"></script>\n'
    return HTMLResponse(html, headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/cards.js")
async def cards_js():
    if not CARDS_JS.exists(): raise HTTPException(status_code=404, detail="Card renderer not found.")
    return Response(CARDS_JS.read_text(encoding="utf-8"), media_type="application/javascript", headers={"Cache-Control": "no-store"})


@app.get("/events.js")
async def events_js():
    if not EVENTS_JS.exists(): raise HTTPException(status_code=404, detail="Events script not found.")
    return Response(EVENTS_JS.read_text(encoding="utf-8"), media_type="application/javascript", headers={"Cache-Control": "no-store"})


@app.get("/upload.js")
async def upload_js():
    if not UPLOAD_JS.exists(): raise HTTPException(status_code=404, detail="Upload script not found.")
    return Response(UPLOAD_JS.read_text(encoding="utf-8"), media_type="application/javascript", headers={"Cache-Control": "no-store"})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status":"ok","service":"agentie-v2","version":"1.4.0"}


@app.post("/files/upload")
async def file_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    try:
        content = await file.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES: raise HTTPException(status_code=413, detail="File exceeds the 50 MB local upload limit.")
        card = save_upload(file.filename or "upload.bin", content)
        return {"message": f"Uploaded {card['name']}.", "card": card}
    except HTTPException: raise
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc: raise HTTPException(status_code=500, detail=f"Upload failed: {exc}") from exc
    finally: await file.close()


@app.post("/files/{filename}/action")
async def file_action(filename: str, request: FileAction) -> dict[str, Any]:
    try:
        message, card = run_action(filename, request.action)
        return {"message": message, "card": card}
    except FileNotFoundError as exc: raise HTTPException(status_code=404, detail="Uploaded file not found.") from exc
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc: raise HTTPException(status_code=500, detail=f"File action failed: {exc}") from exc


@app.get("/local/events/poll")
async def poll_local_events() -> dict[str, Any]:
    now = datetime.now().astimezone(); events: list[dict[str, Any]] = []
    reminders = _load(REMINDERS, []); changed = False
    for item in reminders:
        if item.get("status") != "scheduled": continue
        try: due = datetime.fromisoformat(item.get("due_at")).astimezone()
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
async def agent_run(request: AgentRequest, http_request: Request) -> AgentResponse:
    try:
        session_key = request.session_id or f"{http_request.client.host if http_request.client else 'local'}:{request.agent_type}"

        reference_result = try_active_reference(session_key, request.message)
        if reference_result is not None:
            message = str(reference_result.get("message", "")); card = reference_result.get("card")
            _record_local(session_key, request.message, message, card, request.agent_type, "active_reference")
            return AgentResponse(message=message, result=message, card=card, agent_type=request.agent_type, routed_by="active_reference")

        pdf_result = try_pdf_request(session_key, request.message)
        if pdf_result is not None:
            message = str(pdf_result.get("message", "")); card = pdf_result.get("card")
            _record_local(session_key, request.message, message, card, request.agent_type, "local_pdf")
            return AgentResponse(message=message, result=message, card=card, agent_type=request.agent_type, routed_by="local_pdf")

        followup = consume_followup(session_key, request.message); effective_message = request.message
        if followup:
            if followup.get("cancelled") or not followup.get("command"):
                message = str(followup.get("message", ""))
                _record_local(session_key, request.message, message, None, request.agent_type, "clarification")
                return AgentResponse(message=message, result=message, card=None, agent_type=request.agent_type, routed_by="clarification")
            effective_message = str(followup["command"])

        routed = _route_request_actions(effective_message)
        local_results: list[dict] = routed.get("results", []); unresolved: list[str] = routed.get("unresolved", [])
        clarification_message: str | None = None; remaining_unresolved: list[str] = []
        for clause in unresolved:
            incomplete = detect_incomplete_intent(session_key, clause)
            if incomplete and clarification_message is None:
                clarification_message = str(incomplete.get("message", ""))
            else:
                remaining_unresolved.append(clause)
        unresolved = remaining_unresolved

        # Provider gate: a parser miss on a local/free-first capability must never
        # silently become a paid request. Keep only genuinely model-worthy clauses.
        provider_unresolved: list[str] = []
        blocked_local: list[str] = []
        for clause in unresolved:
            if provider_allowed(clause):
                provider_unresolved.append(clause)
            else:
                blocked_local.append(clause)
        unresolved = provider_unresolved
        if blocked_local and not clarification_message:
            clarification_message = local_fallback_message(blocked_local[0])

        if local_results and not unresolved:
            _refresh_timer_cards(local_results)
            if clarification_message:
                card = _multi_card(local_results, clarification_message); summary = _result_summary(local_results, clarification_message)
                _record_local(session_key, request.message, summary, card, request.agent_type, "clarification")
                return AgentResponse(message="", result=clarification_message, card=card, agent_type=request.agent_type, routed_by="clarification")
            if len(local_results) == 1:
                item = local_results[0]; message = str(item.get("message", "")); card = item.get("card")
                _record_local(session_key, request.message, message, card, request.agent_type, "local")
                return AgentResponse(message=message, result=message, card=card, agent_type=request.agent_type, routed_by="local")
            card = _multi_card(local_results); summary = _result_summary(local_results)
            _record_local(session_key, request.message, summary, card, request.agent_type, "local")
            return AgentResponse(message="", result="", card=card, agent_type=request.agent_type, routed_by="local")

        if not local_results and clarification_message and not unresolved:
            _record_local(session_key, request.message, clarification_message, None, request.agent_type, "clarification")
            return AgentResponse(message=clarification_message, result=clarification_message, card=None, agent_type=request.agent_type, routed_by="clarification")

        if local_results and unresolved:
            unresolved_prompt = "Handle only the following unresolved parts of the user's request. Do not repeat or redo other actions.\n\n" + "\n".join(f"- {part}" for part in unresolved)
            try: llm_result = await run_agent(unresolved_prompt, request.agent_type, session_key)
            except Exception as exc: llm_result = "I completed the other actions, but I couldn't process: " + "; ".join(unresolved) + f". ({exc})"
            if clarification_message: llm_result = (llm_result + "\n\n" + clarification_message).strip()
            _refresh_timer_cards(local_results)
            card = _multi_card(local_results, llm_result)
            remember_active_from_card(session_key, card)
            return AgentResponse(message="", result=llm_result, card=card, agent_type=request.agent_type, routed_by="hybrid")

        if clarification_message and not unresolved:
            _record_local(session_key, request.message, clarification_message, None, request.agent_type, "clarification")
            return AgentResponse(message=clarification_message, result=clarification_message, card=None, agent_type=request.agent_type, routed_by="clarification")

        # Last safety gate before any provider call.
        if not provider_allowed(effective_message):
            message = local_fallback_message(effective_message)
            _record_local(session_key, request.message, message, None, request.agent_type, "local_guard")
            return AgentResponse(message=message, result=message, card=None, agent_type=request.agent_type, routed_by="local_guard")

        result = await run_agent(effective_message, request.agent_type, session_key)
        return AgentResponse(message=result, result=result, card=None, agent_type=request.agent_type, routed_by="llm")
    except RuntimeError as exc: raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc: raise HTTPException(status_code=502, detail=f"Agent run failed: {exc}") from exc


@app.post("/approvals/{approval_id}/resolve")
async def approval_resolve(approval_id: str, decision: ApprovalDecision) -> dict:
    try: return resolve_approval(approval_id, decision.approved)
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000")); uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
