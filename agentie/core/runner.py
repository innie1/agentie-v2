from agents import Runner

from agentie.agents.assistant import build_assistant


async def run_agent(message: str) -> str:
    """Run one Agentie turn and return the final text output."""
    assistant = build_assistant()
    result = await Runner.run(assistant, message)
    return str(result.final_output)
