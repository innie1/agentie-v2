import os
import time

from agents import Runner
from agents.mcp import MCPServerStreamableHttp

from agentie.agents.assistant import build_assistant
from agentie.core.memory_store import add_message, build_context_prompt
from agentie.core.observability import current_trace_id, record_event, record_model_error, record_model_result, start_trace, finish_trace
from agentie.core.role_store import resolve_role


async def run_agent(message: str, agent_type: str = "general", session_id: str | None = None) -> str:
    """Run one Agentie turn with persisted context, runtime role assignment and local observability."""
    own_trace = False
    trace_id = current_trace_id()
    if not trace_id:
        trace_id = start_trace(session_id, agent_type, message)
        own_trace = True

    effective_message = build_context_prompt(session_id, message) if session_id else message
    role_info = resolve_role(agent_type)
    model_name = os.getenv("OPENROUTER_MODEL", "openrouter/auto")
    if session_id:
        add_message(session_id, "user", message, {"agent_type":agent_type,"runtime_role":role_info.get("name")})
    record_event("agent", str(role_info.get("name") or agent_type), metadata={"base":role_info.get("base"),"session_id":session_id})

    started = time.perf_counter()
    try:
        mcp_url = os.getenv("AGENTIE_MCP_URL", "").strip()
        if mcp_url and str(role_info.get("base")) in {"general", "manager"}:
            headers = {}; token = os.getenv("AGENTIE_MCP_TOKEN", "").strip()
            if token: headers["Authorization"] = f"Bearer {token}"
            record_event("mcp", "connect", metadata={"url":mcp_url})
            async with MCPServerStreamableHttp(name="Agentie MCP", params={"url":mcp_url,"headers":headers}, cache_tools_list=True) as server:
                assistant = build_assistant(agent_type, mcp_servers=[server], role_info=role_info)
                result = await Runner.run(assistant, effective_message)
        else:
            assistant = build_assistant(agent_type, role_info=role_info)
            result = await Runner.run(assistant, effective_message)

        latency_ms = (time.perf_counter()-started)*1000
        record_model_result(result, model_name, latency_ms, trace_id)
        output = str(result.final_output)
        if session_id:
            add_message(session_id, "assistant", output, {"agent_type":agent_type,"runtime_role":role_info.get("name")})
        if own_trace: finish_trace(trace_id, "completed")
        return output
    except Exception as exc:
        latency_ms = (time.perf_counter()-started)*1000
        record_model_error(model_name, exc, latency_ms, trace_id)
        if own_trace: finish_trace(trace_id, "failed", str(exc))
        raise
