from __future__ import annotations

import json
from typing import Any

from agents import function_tool

from agentie.core.agent_access import mcp_allowed,skill_allowed
from agentie.core.mcp_client import _approval_action,execute_tool,inspect_server,list_servers
from agentie.tools import registry
from agentie.tools.approval_tools import approval_is_granted,create_background_mcp_approval,list_approvals,request_approval
from agentie.tools.basic_tools import get_current_utc_time


def _ids(items):return {id(x) for x in items}
def _add(tools,extra):
    seen=_ids(tools)
    for tool in extra:
        if id(tool) not in seen:tools.append(tool);seen.add(id(tool))
    return tools


def _plugin_tool(agent:dict[str,Any]):
    @function_tool
    async def use_plugin(server: str, tool: str, arguments_json: str = "{}") -> str:
        """Use one real MCP/plugin granted to this agent.

        First inspect the provider's tools when needed, then call this with the exact
        server name, exact tool name, and a JSON object string for arguments.
        Read-only MCP tools can run automatically. Consequential tools create the
        normal Agentie approval request and must be retried after approval.
        """
        server=str(server or "").strip();tool=str(tool or "").strip()
        if not server or not tool:return "Plugin server and tool are required."
        if not mcp_allowed(agent,server):return f"{agent.get('name') or 'This agent'} is not allowed to use MCP/plugin '{server}'."
        try:arguments=json.loads(arguments_json or "{}")
        except Exception:return "Plugin arguments_json must be a valid JSON object."
        if not isinstance(arguments,dict):return "Plugin arguments_json must decode to a JSON object."
        try:info=await inspect_server(server)
        except Exception as exc:return f"Could not connect to plugin '{server}': {str(exc)[:500]}"
        discovered={str(x.get('name') or '') for x in info.get('tools') or []}
        if tool not in discovered:return f"Plugin '{server}' does not expose tool '{tool}'. Available tools: {', '.join(sorted(discovered)[:40]) or 'none'}."
        action=_approval_action(server,tool,arguments)
        if not approval_is_granted(action):
            approval=create_background_mcp_approval(action,f"Allow {agent.get('name') or 'this agent'} to run MCP {server}/{tool} with these arguments: {json.dumps(arguments,ensure_ascii=False)[:500]}",agent_id=str(agent.get('id') or ''),agent_name=str(agent.get('name') or 'Agent'),server=server,tool=tool,command=f"{server}/{tool}")
            return json.dumps({"status":"approval_required","approval_id":approval.get("id"),"server":server,"tool":tool,"message":"A real Agentie approval was created. Stop this action and tell the user approval is required before retrying."},ensure_ascii=False)
        try:result=await execute_tool(server,tool,arguments)
        except Exception as exc:return f"Plugin '{server}' tool '{tool}' failed: {str(exc)[:700]}"
        return json.dumps({"status":"completed","server":server,"tool":tool,"message":result.get("message"),"result":result.get("card")},ensure_ascii=False)
    return use_plugin


def tools_for_persistent_agent(agent:dict[str,Any])->list:
    """Build model tools from effective grants, never from a job-title class."""
    tools=[get_current_utc_time,request_approval,list_approvals]
    if skill_allowed(agent,"local-utils"):_add(tools,[*registry.LOCAL_UTILITY_TOOLS,*registry.PRODUCTIVITY_TOOLS,*registry.ADVANCED_LOCAL_TOOLS])
    if skill_allowed(agent,"research"):_add(tools,registry.RESEARCH_TOOLS)
    if skill_allowed(agent,"files"):_add(tools,registry.FILE_TOOLS)
    if skill_allowed(agent,"code-execution"):_add(tools,[registry.run_python])
    if skill_allowed(agent,"knowledge-memory"):_add(tools,registry.MEMORY_TOOLS)
    if skill_allowed(agent,"jobs"):_add(tools,registry.TASK_TOOLS)
    if skill_allowed(agent,"planning"):_add(tools,registry.WORK_TOOLS)
    if skill_allowed(agent,"github"):_add(tools,[registry.github_repo_info,registry.github_read_file])
    if skill_allowed(agent,"browser-automation"):_add(tools,[registry.browser_read_page])
    if any(mcp_allowed(agent,str(server.get("name") or "")) for server in list_servers()):tools.append(_plugin_tool(agent))
    return tools
