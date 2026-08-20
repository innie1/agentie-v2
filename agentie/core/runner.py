import os
import time

from agents import Runner
from agents.mcp import MCPServerStreamableHttp

from agentie.agents.assistant import build_assistant
from agentie.core.agent_prompt import agent_from_session, build_agent_instructions
from agentie.core.memory_store import add_message, build_context_prompt
from agentie.core.npc_brain import try_npc_response
from agentie.core.observability import current_trace_id, record_event, record_model_error, record_model_result, start_trace, finish_trace
from agentie.core.role_store import resolve_role
from agentie.models.provider import get_provider_info


def _friendly_provider_error(exc: Exception) -> str | None:
    """Return a short user-facing message for known provider failures.

    The full provider exception is still written to Agentie's trace before this
    helper is used, so chat stays clean without losing debugging detail.
    """
    text = str(exc or "")
    lower = text.lower()
    if "429" in lower or "resource_exhausted" in lower or "quota exceeded" in lower or "rate limit" in lower:
        return "The AI model is temporarily at its usage limit. Please try again shortly."
    if "402" in lower or "requires more credits" in lower or "insufficient" in lower and "credit" in lower:
        return "The AI provider is out of credits right now. Add credits or switch providers to continue."
    if "404" in lower and ("model" in lower or "not found" in lower):
        return "The configured AI model is unavailable. Please update the model setting and try again."
    if "timeout" in lower or "timed out" in lower:
        return "The AI provider took too long to respond. Please try again."
    return None


async def run_agent(message: str, agent_type: str = "general", session_id: str | None = None) -> str:
    """Run one Agentie turn with persisted context, evolving agent identity and local-first NPC fallback."""
    own_trace = False
    trace_id = current_trace_id()
    if not trace_id:
        trace_id = start_trace(session_id, agent_type, message)
        own_trace = True

    original_message = message
    persistent_agent = agent_from_session(session_id)
    persistent_instructions = None
    if persistent_agent:
        # NPC v2 is the first local intelligence layer. It may either answer
        # confidently on-device or enrich an ambiguous contextual follow-up for
        # the larger model. It never invents completion of work it cannot do.
        npc = try_npc_response(persistent_agent, message, session_id=session_id)
        if npc is not None and npc.get("message") is not None:
            output = str(npc.get("message") or "")
            if session_id:
                add_message(session_id,"user",original_message,{"agent_type":agent_type,"routed_by":"npc_brain","npc_confidence":npc.get("confidence")})
                add_message(session_id,"assistant",output,{"agent_type":agent_type,"routed_by":"npc_brain","npc_confidence":npc.get("confidence")})
            record_event("npc_brain", str(persistent_agent.get("name") or "agent"), metadata={"session_id":session_id,"provider_calls":0,"npc_role":npc.get("npc_role"),"confidence":npc.get("confidence")})
            if own_trace:finish_trace(trace_id,"completed")
            return output
        if npc is not None and npc.get("escalate_message"):
            message = str(npc["escalate_message"])
            record_event("npc_context",str(persistent_agent.get("name") or "agent"),metadata={"session_id":session_id,"npc_role":npc.get("npc_role"),"confidence":npc.get("confidence"),"provider_calls":0})
        persistent_instructions = build_agent_instructions(persistent_agent)

    effective_message = build_context_prompt(session_id, message) if session_id else message
    role_info = resolve_role(agent_type)
    provider_info = get_provider_info()
    model_name = provider_info["model"]
    if session_id:
        add_message(session_id, "user", original_message, {"agent_type":agent_type,"runtime_role":role_info.get("name")})
    record_event("agent", str(role_info.get("name") or agent_type), metadata={"base":role_info.get("base"),"session_id":session_id})
    record_event("provider", provider_info["provider"], metadata={"model":model_name})

    started = time.perf_counter()
    try:
        mcp_url = os.getenv("AGENTIE_MCP_URL", "").strip()
        if mcp_url and str(role_info.get("base")) in {"general", "manager"}:
            headers = {}; token = os.getenv("AGENTIE_MCP_TOKEN", "").strip()
            if token: headers["Authorization"] = f"Bearer {token}"
            record_event("mcp", "connect", metadata={"url":mcp_url})
            async with MCPServerStreamableHttp(name="Agentie MCP", params={"url":mcp_url,"headers":headers}, cache_tools_list=True) as server:
                assistant = build_assistant(agent_type, mcp_servers=[server], role_info=role_info, persistent_instructions=persistent_instructions)
                result = await Runner.run(assistant, effective_message)
        else:
            assistant = build_assistant(agent_type, role_info=role_info, persistent_instructions=persistent_instructions)
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
        friendly = _friendly_provider_error(exc)
        if friendly:
            raise RuntimeError(friendly) from exc
        raise