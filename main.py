import os

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agentie.core.runner import run_agent


app = FastAPI(
    title="Agentie API",
    version="0.1.0",
    description="Python-first Agentie agent runtime",
)


class AgentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)


class AgentResponse(BaseModel):
    result: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "agentie-v2"}


@app.post("/agent/run", response_model=AgentResponse)
async def agent_run(request: AgentRequest) -> AgentResponse:
    try:
        result = await run_agent(request.message)
        return AgentResponse(result=result)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Agent run failed: {exc}") from exc


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
