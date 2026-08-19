import os

from agents import Runner
from agents.mcp import MCPServerStreamableHttp

from agentie.agents.assistant import build_assistant


async def run_agent(message: str, agent_type: str = "general") -> str:
    """Run one Agentie turn using the selected permissioned agent profile.

    If AGENTIE_MCP_URL is configured, general and manager agents receive that
    Streamable HTTP MCP server for the duration of the turn.
    """
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
            result = await Runner.run(assistant, message)
            return str(result.final_output)

    assistant = build_assistant(agent_type)
    result = await Runner.run(assistant, message)
    return str(result.final_output)
