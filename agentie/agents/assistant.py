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
- Use web search or HTTP tools for current, recent, changing, or externally verifiable information.
- Use memory only for useful non-sensitive preferences, goals, and durable facts.
- Use task tools for multi-step work that benefits from explicit progress tracking.
- GitHub tools are read-only in this phase.
- For any externally consequential or irreversible action, create an approval request instead of performing the action.
- Keep answers concise unless the user asks for detail.
""".strip()


def build_assistant(agent_type: str = "general") -> Agent:
    profile = agent_type if agent_type in {"general", "research", "coding", "manager", "github"} else "general"
    return Agent(
        name=f"Agentie {profile.title()} Agent",
        instructions=SYSTEM_INSTRUCTIONS + f"\n\nCurrent agent profile: {profile}.",
        model=get_model(),
        tools=tools_for(profile),
    )
