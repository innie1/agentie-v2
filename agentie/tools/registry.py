from agentie.tools.advanced_utility_tools import (
    cancel_recurring_schedule,
    compare_json_text,
    countdown_to,
    create_recurring_schedule,
    date_difference,
    detailed_system_status,
    file_checksum,
    format_json_text,
    format_yaml_text,
    image_metadata,
    list_recurring_schedules,
    local_datetime,
    rss_read,
    scratchpad_get,
    scratchpad_list,
    scratchpad_set,
    unzip_workspace_archive,
    wikipedia_lookup,
    zip_workspace_files,
)
from agentie.tools.approval_tools import list_approvals, request_approval
from agentie.tools.basic_tools import get_current_utc_time
from agentie.tools.browser_tools import browser_read_page
from agentie.tools.document_tools import read_csv, read_pdf
from agentie.tools.file_tools import edit_text_file, list_workspace_files, read_text_file, write_text_file
from agentie.tools.github_tools import github_read_file, github_repo_info
from agentie.tools.http_tools import http_get
from agentie.tools.local_utility_tools import (
    cancel_timer,
    list_timers,
    set_alarm_at,
    set_timer,
    stopwatch_pause,
    stopwatch_reset,
    stopwatch_start,
    stopwatch_status,
    weather_lookup,
)
from agentie.tools.memory_tools import list_memories, recall_memory, remember
from agentie.tools.productivity_tools import (
    calculate,
    cancel_reminder,
    convert_unit,
    create_reminder,
    list_notes,
    list_reminders,
    read_note,
    save_note,
    system_status,
)
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

TASK_TOOLS = [create_task, list_tasks, update_task, find_duplicate_tasks, request_task_delete_approval, delete_task]
DOCUMENT_TOOLS = [read_pdf, read_csv]
LOCAL_UTILITY_TOOLS = [set_timer, set_alarm_at, list_timers, cancel_timer, stopwatch_start, stopwatch_pause, stopwatch_reset, stopwatch_status, weather_lookup]
PRODUCTIVITY_TOOLS = [calculate, convert_unit, create_reminder, list_reminders, cancel_reminder, save_note, list_notes, read_note, system_status]
ADVANCED_LOCAL_TOOLS = [
    local_datetime,
    date_difference,
    countdown_to,
    create_recurring_schedule,
    list_recurring_schedules,
    cancel_recurring_schedule,
    scratchpad_set,
    scratchpad_get,
    scratchpad_list,
    zip_workspace_files,
    unzip_workspace_archive,
    format_json_text,
    format_yaml_text,
    compare_json_text,
    file_checksum,
    image_metadata,
    detailed_system_status,
]
FREE_KNOWLEDGE_TOOLS = [rss_read, wikipedia_lookup]

TOOLSETS = {
    "general": [get_current_utc_time, *LOCAL_UTILITY_TOOLS, *PRODUCTIVITY_TOOLS, *ADVANCED_LOCAL_TOOLS, *FREE_KNOWLEDGE_TOOLS, search_web, browser_read_page, http_get, read_text_file, write_text_file, list_workspace_files, edit_text_file, *DOCUMENT_TOOLS, run_python, remember, recall_memory, list_memories, *TASK_TOOLS, supabase_select, supabase_insert, request_approval, list_approvals],
    "research": [get_current_utc_time, local_datetime, weather_lookup, calculate, convert_unit, save_note, list_notes, read_note, scratchpad_set, scratchpad_get, scratchpad_list, rss_read, wikipedia_lookup, search_web, browser_read_page, http_get, read_text_file, write_text_file, list_workspace_files, *DOCUMENT_TOOLS, remember, recall_memory, list_memories, *TASK_TOOLS],
    "coding": [get_current_utc_time, local_datetime, set_timer, list_timers, stopwatch_start, stopwatch_pause, stopwatch_reset, stopwatch_status, calculate, convert_unit, detailed_system_status, scratchpad_set, scratchpad_get, scratchpad_list, zip_workspace_files, unzip_workspace_archive, format_json_text, format_yaml_text, compare_json_text, file_checksum, image_metadata, read_text_file, write_text_file, list_workspace_files, edit_text_file, *DOCUMENT_TOOLS, run_python, github_repo_info, github_read_file, *TASK_TOOLS, request_approval, list_approvals],
    "manager": [get_current_utc_time, *LOCAL_UTILITY_TOOLS, *PRODUCTIVITY_TOOLS, local_datetime, date_difference, countdown_to, create_recurring_schedule, list_recurring_schedules, cancel_recurring_schedule, scratchpad_set, scratchpad_get, scratchpad_list, detailed_system_status, remember, recall_memory, list_memories, *TASK_TOOLS, supabase_select, supabase_insert, request_approval, list_approvals],
    "github": [github_repo_info, github_read_file, read_text_file, write_text_file, list_workspace_files, detailed_system_status, file_checksum, zip_workspace_files, unzip_workspace_archive, *TASK_TOOLS, request_approval, list_approvals],
}


def tools_for(agent_type: str):
    return TOOLSETS.get(agent_type, TOOLSETS["general"])
