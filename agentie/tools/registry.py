from agentie.tools.approval_tools import list_approvals, request_approval
from agentie.tools.basic_tools import get_current_utc_time
from agentie.tools.browser_tools import browser_read_page
from agentie.tools.document_tools import read_csv, read_pdf
from agentie.tools.file_tools import edit_text_file, list_workspace_files, read_text_file, write_text_file
from agentie.tools.github_tools import github_read_file, github_repo_info
from agentie.tools.http_tools import http_get
from agentie.tools.memory_tools import list_memories, recall_memory, remember
from agentie.tools.python_tools import run_python
from agentie.tools.supabase_tools import supabase_insert, supabase_select
from agentie.tools.task_tools import (
    create_task,
    delete_task,
    find_duplicate_tasks,
    list_tasks,
    request_task_delete_approval,
    update_task,
)
from agentie.tools.web_tools import search_web

TASK_TOOLS = [
    create_task,
    list_tasks,
    update_task,
    find_duplicate_tasks,
    request_task_delete_approval,
    delete_task,
]

DOCUMENT_TOOLS = [read_pdf, read_csv]

TOOLSETS = {
    "general": [get_current_utc_time, search_web, browser_read_page, http_get, read_text_file, write_text_file, list_workspace_files, edit_text_file, *DOCUMENT_TOOLS, run_python, remember, recall_memory, list_memories, *TASK_TOOLS, supabase_select, supabase_insert, request_approval, list_approvals],
    "research": [get_current_utc_time, search_web, browser_read_page, http_get, read_text_file, write_text_file, list_workspace_files, *DOCUMENT_TOOLS, remember, recall_memory, list_memories, *TASK_TOOLS],
    "coding": [get_current_utc_time, read_text_file, write_text_file, list_workspace_files, edit_text_file, *DOCUMENT_TOOLS, run_python, github_repo_info, github_read_file, *TASK_TOOLS, request_approval, list_approvals],
    "manager": [get_current_utc_time, remember, recall_memory, list_memories, *TASK_TOOLS, supabase_select, supabase_insert, request_approval, list_approvals],
    "github": [github_repo_info, github_read_file, read_text_file, write_text_file, list_workspace_files, *TASK_TOOLS, request_approval, list_approvals],
}


def tools_for(agent_type: str):
    return TOOLSETS.get(agent_type, TOOLSETS["general"])
