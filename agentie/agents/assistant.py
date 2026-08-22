import os

from agents import Agent,ModelSettings

from agentie.models.provider import get_model
from agentie.tools.registry import tools_for
from agentie.tools.persistent_tools import tools_for_persistent_agent

SYSTEM_INSTRUCTIONS="""
You are Agentie, a capable digital worker.

Your job is to understand the user's goal, use available tools when they improve accuracy or are required to complete the task, and return a clear final result.

Rules:
- Never claim a tool or action succeeded unless it actually ran successfully.
- Prefer tools over guessing when a tool can provide the answer.
- Use web search, browser, HTTP, MCP, or another available real capability for current or externally verifiable information when it matters to the decision.
- Use memory only for useful non-sensitive preferences, goals, and durable facts.
- Use task/job tools for multi-step work that benefits from explicit progress tracking; do not turn ordinary advice or conversation into a background job unnecessarily.
- Respect approval gates for consequential or irreversible actions.
- Advice is not authorization: recommending a send, post, delete, payment, purchase, transfer, hire/fire, commit, push, merge, or similar consequential action must not execute it without the normal permission/approval path.
- For judgment questions, distinguish supported facts from opinions, recommendations, and risks/uncertainty. Never present assumptions, estimates, or predictions as facts.
- Do not agree just to be agreeable. Respectfully challenge a weak plan when evidence, configured ownership, constraints, or the user's stated goal support a better option.
- A job/title describes ownership; it never silently grants tools or permissions.
- Keep answers concise unless the user asks for detail.
""".strip()


def _model_settings()->ModelSettings:
    max_tokens=int(os.getenv("AGENTIE_MAX_OUTPUT_TOKENS","4096"));max_tokens=max(256,min(max_tokens,16384));return ModelSettings(max_tokens=max_tokens)


def _specialist(profile:str,provider_info:dict|None=None)->Agent:
    return Agent(name=f"Agentie {profile.title()} Specialist",instructions=SYSTEM_INSTRUCTIONS+f"\n\nYou are the {profile} compatibility specialist. Focus on that specialty.",model=get_model(provider_info),model_settings=_model_settings(),tools=tools_for(profile))


def build_assistant(agent_type:str="general",mcp_servers=None,role_info:dict|None=None,persistent_instructions:str|None=None,persistent_agent:dict|None=None,provider_info:dict|None=None)->Agent:
    if persistent_agent:
        name=str(persistent_agent.get("name") or "Agent")
        job=str(persistent_agent.get("role") or "configured job")
        instructions=SYSTEM_INSTRUCTIONS+f"\n\nYou are {name}. Your configured job/ownership is: {job}."
        if persistent_instructions:instructions+="\n\nPersistent identity, rules, memory preferences and configured responsibilities:\n"+str(persistent_instructions).strip()
        return Agent(name=name,instructions=instructions,model=get_model(provider_info),model_settings=_model_settings(),tools=tools_for_persistent_agent(persistent_agent),mcp_servers=list(mcp_servers or []))
    # Backward-compatible base-agent runtime. This path is not the model for a
    # user-created persistent agent.
    profile=agent_type if agent_type in {"general","research","coding","manager","github"} else "general";role_info=role_info or {"name":profile,"base":profile,"instruction":f"Act in the {profile} role."};tool_profile=str(role_info.get("base") or profile)
    if tool_profile not in {"general","research","coding","manager","github"}:tool_profile=profile
    tools=list(tools_for(tool_profile))
    if tool_profile=="manager":
        research=_specialist("research",provider_info);coding=_specialist("coding",provider_info);github=_specialist("github",provider_info);tools.extend([research.as_tool(tool_name="delegate_research",tool_description="Delegate bounded evidence or research work."),coding.as_tool(tool_name="delegate_coding",tool_description="Delegate bounded coding, file, data, or document work."),github.as_tool(tool_name="delegate_github",tool_description="Delegate bounded GitHub repository inspection work.")])
    role_name=str(role_info.get("name") or profile);role_instruction=str(role_info.get("instruction") or "");instructions=SYSTEM_INSTRUCTIONS+f"\n\nCompatibility base agent: {profile}. Runtime role: {role_name}.\n{role_instruction}"
    if persistent_instructions:instructions+="\n\nPersistent instructions:\n"+str(persistent_instructions).strip()
    return Agent(name=f"Agentie {role_name.title()} Agent",instructions=instructions,model=get_model(provider_info),model_settings=_model_settings(),tools=tools,mcp_servers=list(mcp_servers or []) if tool_profile in {"general","manager"} else [])
