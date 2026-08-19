import os

from agents import Runner
from agents.mcp import MCPServerStreamableHttp

from agentie.agents.assistant import build_assistant
from agentie.core.memory_store import add_message, build_context_prompt


async def run_agent(message: str, agent_type: str = "general", session_id: str | None = None) -> str:
    """Run one Agentie turn with persisted conversational context."""
    # Build context BEFORE storing the current turn, otherwise the current user
    # message would appear twice in the prompt.
    effective_message = build_context_prompt(session_id, message) if session_id else message
    if session_id:
        add_message(session_id, "user", message, {"agent_type": agent_type})

    mcp_url = os.getenv("AGENTIE_MCP_URL", "").strip()
    if mcp_url and agent_type in {"general", "manager"}:
        headers = {}
        token = os.getenv("AGENTIE_MCP_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with MCPServerStreamableHttp(
            name="Agentie MCP",
            params={"url": mcp_url, "headers": headers},
            cache_tools_list=True,
        ) as server:
            assistant = build_assistant(agent_type, mcp_servers=[server])
            result = await Runner.run(assistant, effective_message)
            output = str(result.final_output)
            if session_id:
                add_message(session_id, "assistant", output, {"agent_type": agent_type})
            return output

    assistant = build_assistant(agent_type)
    result = await Runner.run(assistant, effective_message)
    output = str(result.final_output)
    if session_id:
        add_message(session_id, "assistant", output, {"agent_type": agent_type})
    return output
