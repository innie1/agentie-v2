from agents import Agent

from agentie.models.provider import get_model
from agentie.tools.registry import tools_for


SYSTEM_INSTRUCTIONS = """
You are Agentie, a capable digital worker.

Your job is to understand the user's goal, use available tools when they improve
accuracy or are required to complete the task, and return a clear final result.

Rules:
- Never claim a tool or action succeeded unless it actually ran successfully.
- Use only the tools assigned to this agent profile.
- Prefer tools over guessing when a tool can provide the answer.
- Use web search, browser, or HTTP tools for current or externally verifiable information.
- Use memory only for useful non-sensitive preferences, goals, and durable facts.
- Use task tools for multi-step work that benefits from explicit progress tracking.
- GitHub tools are read-only in this phase.
- Supabase writes require an explicit approved action before execution.
- For externally consequential or irreversible actions, create an approval request instead of performing the action.
- Keep answers concise unless the user asks for detail.
""".strip()


def _specialist(profile: str) -> Agent:
    return Agent(
        name=f"Agentie {profile.title()} Specialist",
        instructions=SYSTEM_INSTRUCTIONS + f"\n\nYou are the {profile} specialist. Focus only on that specialty.",
        model=get_model(),
        tools=tools_for(profile),
    )


def build_assistant(agent_type: str = "general", mcp_servers=None) -> Agent:
    profile = agent_type if agent_type in {"general", "research", "coding", "manager", "github"} else "general"
    tools = list(tools_for(profile))

    # Manager-style orchestration: the manager remains user-facing and can call
    # specialists for bounded subtasks. This is the Agents SDK "agents as tools" pattern.
    if profile == "manager":
        research = _specialist("research")
        coding = _specialist("coding")
        github = _specialist("github")
        tools.extend([
            research.as_tool(
                tool_name="delegate_research",
                tool_description="Delegate a bounded research or web investigation task to the research specialist.",
            ),
            coding.as_tool(
                tool_name="delegate_coding",
                tool_description="Delegate a bounded code, file, Python, or document task to the coding specialist.",
            ),
            github.as_tool(
                tool_name="delegate_github",
                tool_description="Delegate a bounded GitHub repository inspection task to the GitHub specialist.",
            ),
        ])

    return Agent(
        name=f"Agentie {profile.title()} Agent",
        instructions=SYSTEM_INSTRUCTIONS + f"\n\nCurrent agent profile: {profile}.",
        model=get_model(),
        tools=tools,
        mcp_servers=list(mcp_servers or []) if profile in {"general", "manager"} else [],
    )
