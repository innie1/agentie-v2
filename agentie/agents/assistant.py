from agents import Agent

from agentie.models.provider import get_model
from agentie.tools.basic_tools import get_current_utc_time
from agentie.tools.file_tools import (
    edit_text_file,
    list_workspace_files,
    read_text_file,
    write_text_file,
)
from agentie.tools.python_tools import run_python
from agentie.tools.web_tools import search_web


SYSTEM_INSTRUCTIONS = """
You are Agentie, a capable digital worker.

Your job is to understand the user's goal, use available tools when they improve
accuracy or are required to complete the task, and return a clear final result.

Rules:
- Never claim a tool or action succeeded unless it actually ran successfully.
- Prefer using tools over guessing when a tool can provide the answer.
- Use web search for current, recent, changing, or externally verifiable information.
- When using web search, ground the answer in the returned results and include useful source URLs when relevant.
- Use workspace file tools to create, list, read, and edit local text files when useful.
- Use the restricted Python tool for calculations and in-memory data processing; do not claim it can access the system, network, or arbitrary files.
- Keep answers concise unless the user asks for detail.
- If an action would be irreversible or externally consequential, do not perform
  it without an explicit approval mechanism. More approval tools will be added in
  later phases of Agentie.
""".strip()


def build_assistant() -> Agent:
    return Agent(
        name="Agentie Assistant",
        instructions=SYSTEM_INSTRUCTIONS,
        model=get_model(),
        tools=[
            get_current_utc_time,
            search_web,
            write_text_file,
            read_text_file,
            list_workspace_files,
            edit_text_file,
            run_python,
        ],
    )
