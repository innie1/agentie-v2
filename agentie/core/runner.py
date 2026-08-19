from agents import Runner

from agentie.agents.assistant import build_assistant


async def run_agent(message: str, agent_type: str = "general") -> str:
    """Run one Agentie turn using the selected permissioned agent profile."""
    assistant = build_assistant(agent_type)
    result = await Runner.run(assistant, message)
    return str(result.final_output)
