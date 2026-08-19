import os
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agentie.core.local_router import try_local_command
from agentie.core.runner import run_agent
from agentie.tools.approval_tools import resolve_approval


app = FastAPI(
    title="Agentie API",
    version="0.5.0",
    description="Python-first Agentie runtime with local-first routing and inline UI cards",
)

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


@app.get("/")
async def chat_ui():
    if not FRONTEND_FILE.exists():
        raise HTTPException(status_code=404, detail="Frontend not found.")
    return FileResponse(FRONTEND_FILE, media_type="text/html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "agentie-v2", "version": "0.5.0"}


@app.post("/agent/run", response_model=AgentResponse)
async def agent_run(request: AgentRequest) -> AgentResponse:
    try:
        local_result = try_local_command(request.message)
        if local_result is not None:
            message = str(local_result.get("message", ""))
            return AgentResponse(
                message=message,
                result=message,
                card=local_result.get("card"),
                agent_type=request.agent_type,
                routed_by="local",
            )

        result = await run_agent(request.message, request.agent_type)
        return AgentResponse(
            message=result,
            result=result,
            card=None,
            agent_type=request.agent_type,
            routed_by="llm",
        )
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
