import os

from agents import Runner
from agents.mcp import MCPServerStreamableHttp

from agentie.agents.assistant import build_assistant
from agentie.core.memory_store import add_message, build_context_prompt
from agentie.core.role_store import resolve_role


async def run_agent(message: str, agent_type: str = "general", session_id: str | None = None) -> str:
    """Run one Agentie turn with persisted context and runtime role assignment."""
    effective_message=build_context_prompt(session_id,message) if session_id else message
    role_info=resolve_role(agent_type)
    if session_id:add_message(session_id,"user",message,{"agent_type":agent_type,"runtime_role":role_info.get("name")})

    mcp_url=os.getenv("AGENTIE_MCP_URL","").strip()
    if mcp_url and str(role_info.get("base")) in {"general","manager"}:
        headers={};token=os.getenv("AGENTIE_MCP_TOKEN","").strip()
        if token:headers["Authorization"]=f"Bearer {token}"
        async with MCPServerStreamableHttp(name="Agentie MCP",params={"url":mcp_url,"headers":headers},cache_tools_list=True) as server:
            assistant=build_assistant(agent_type,mcp_servers=[server],role_info=role_info);result=await Runner.run(assistant,effective_message);output=str(result.final_output)
            if session_id:add_message(session_id,"assistant",output,{"agent_type":agent_type,"runtime_role":role_info.get("name")})
            return output

    assistant=build_assistant(agent_type,role_info=role_info);result=await Runner.run(assistant,effective_message);output=str(result.final_output)
    if session_id:add_message(session_id,"assistant",output,{"agent_type":agent_type,"runtime_role":role_info.get("name")})
    return output
