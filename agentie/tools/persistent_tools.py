from __future__ import annotations

from typing import Any

from agentie.core.agent_access import skill_allowed
from agentie.tools import registry
from agentie.tools.approval_tools import list_approvals,request_approval
from agentie.tools.basic_tools import get_current_utc_time


def _ids(items):return {id(x) for x in items}
def _remove(tools,blocked):
    ids=_ids(blocked);return [x for x in tools if id(x) not in ids]
def _add(tools,extra):
    seen=_ids(tools)
    for tool in extra:
        if id(tool) not in seen:tools.append(tool);seen.add(id(tool))
    return tools


def tools_for_persistent_agent(agent:dict[str,Any])->list:
    """Build the model tool list from this agent's effective grants.

    The job title never chooses a hard-coded profession/toolset. Legacy base-agent
    toolsets remain in registry.py only for non-persistent compatibility agents.
    """
    tools=[get_current_utc_time,request_approval,list_approvals]
    if skill_allowed(agent,"local-utils"):_add(tools,[*registry.LOCAL_UTILITY_TOOLS,*registry.PRODUCTIVITY_TOOLS,*registry.ADVANCED_LOCAL_TOOLS])
    if skill_allowed(agent,"research"):_add(tools,registry.RESEARCH_TOOLS)
    if skill_allowed(agent,"files"):_add(tools,registry.FILE_TOOLS)
    if skill_allowed(agent,"code-execution"):_add(tools,[registry.run_python])
    if skill_allowed(agent,"knowledge-memory"):_add(tools,registry.MEMORY_TOOLS)
    if skill_allowed(agent,"jobs"):_add(tools,registry.TASK_TOOLS)
    if skill_allowed(agent,"planning"):_add(tools,registry.WORK_TOOLS)
    if skill_allowed(agent,"github"):_add(tools,[registry.github_repo_info,registry.github_read_file])
    # Browser read is independently controllable from full research.
    if skill_allowed(agent,"browser-automation"):_add(tools,[registry.browser_read_page])
    return tools
