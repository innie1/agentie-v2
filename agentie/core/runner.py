import os

from agents import Runner
from agents.mcp import MCPServerStreamableHttp

from agentie.agents.assistant import build_assistant
from agentie.core.memory_store import build_context_prompt


async def run_agent(message: str, agent_type: str = "general", session_id: str | None = None) -> str:
    """Run one Agentie turn using the selected permissioned agent profile.

    When a session_id is supplied, recent persisted conversation history is
    included so follow-ups such as "use this", "make it shorter", or "turn that
    into a PDF" retain their referent across browser/server restarts.
    """
    effective_message = build_context_prompt(session_id, message) if session_id else message
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
            return str(result.final_output)

    assistant = build_assistant(agent_type)
    result = await Runner.run(assistant, effective_message)
    return str(result.final_output)
