from agentie.core.skill_registry import skill_enabled
from agentie.tools.advanced_utility_tools import (
    cancel_recurring_schedule, compare_json_text, countdown_to, create_recurring_schedule,
    date_difference, detailed_system_status, file_checksum, format_json_text, format_yaml_text,
    image_metadata, list_recurring_schedules, local_datetime, rss_read, scratchpad_get,
    scratchpad_list, scratchpad_set, unzip_workspace_archive, wikipedia_lookup, zip_workspace_files,
)
from agentie.tools.approval_tools import list_approvals, request_approval
from agentie.tools.artifact_tools import create_excel_workbook, create_powerpoint_presentation, create_word_document
from agentie.tools.basic_tools import get_current_utc_time
from agentie.tools.browser_tools import browser_read_page
from agentie.tools.collection_tools import collection_context, collection_create, collection_index_file, collection_list, collection_search
from agentie.tools.document_tools import read_csv, read_pdf
from agentie.tools.file_tools import edit_text_file, list_workspace_files, read_text_file, write_text_file
from agentie.tools.github_tools import github_read_file, github_repo_info
from agentie.tools.http_tools import http_get
from agentie.tools.local_utility_tools import (
    cancel_timer, list_timers, set_alarm_at, set_timer, stopwatch_pause, stopwatch_reset,
    stopwatch_start, stopwatch_status, weather_lookup,
)
from agentie.tools.memory_tools import list_memories, recall_memory, remember, search_memory
from agentie.tools.productivity_tools import (
    calculate, cancel_reminder, convert_unit, create_reminder, list_notes, list_reminders,
    read_note, save_note, system_status,
)
from agentie.tools.python_tools import run_python
from agentie.tools.supabase_tools import supabase_insert, supabase_select
from agentie.tools.task_tools import (
    create_task, delete_task, find_duplicate_tasks, list_tasks, request_task_delete_approval, update_task,
)
from agentie.tools.web_tools import search_web
from agentie.tools.work_tools import (
    create_calendar_event, create_website_monitor, find_contacts, list_calendar_events,
    list_website_monitors, plan_task, save_contact,
)

TASK_TOOLS=[create_task,list_tasks,update_task,find_duplicate_tasks,request_task_delete_approval,delete_task]
DOCUMENT_TOOLS=[read_pdf,read_csv]
ARTIFACT_TOOLS=[create_word_document,create_excel_workbook,create_powerpoint_presentation]
COLLECTION_TOOLS=[collection_create,collection_list,collection_index_file,collection_search,collection_context]
MEMORY_TOOLS=[remember,recall_memory,search_memory,list_memories]
LOCAL_UTILITY_TOOLS=[set_timer,set_alarm_at,list_timers,cancel_timer,stopwatch_start,stopwatch_pause,stopwatch_reset,stopwatch_status,weather_lookup]
PRODUCTIVITY_TOOLS=[calculate,convert_unit,create_reminder,list_reminders,cancel_reminder,save_note,list_notes,read_note,system_status]
ADVANCED_LOCAL_TOOLS=[local_datetime,date_difference,countdown_to,create_recurring_schedule,list_recurring_schedules,cancel_recurring_schedule,scratchpad_set,scratchpad_get,scratchpad_list,zip_workspace_files,unzip_workspace_archive,format_json_text,format_yaml_text,compare_json_text,file_checksum,image_metadata,detailed_system_status]
FREE_KNOWLEDGE_TOOLS=[rss_read,wikipedia_lookup]
FILE_TOOLS=[read_text_file,write_text_file,list_workspace_files,edit_text_file,*DOCUMENT_TOOLS,*COLLECTION_TOOLS,*ARTIFACT_TOOLS]
RESEARCH_TOOLS=[search_web,browser_read_page,http_get,*FREE_KNOWLEDGE_TOOLS]
WORK_TOOLS=[plan_task,save_contact,find_contacts,create_calendar_event,list_calendar_events,create_website_monitor,list_website_monitors]

BASE_TOOLSETS={
 "general":[get_current_utc_time,*LOCAL_UTILITY_TOOLS,*PRODUCTIVITY_TOOLS,*ADVANCED_LOCAL_TOOLS,*RESEARCH_TOOLS,*FILE_TOOLS,*WORK_TOOLS,run_python,*MEMORY_TOOLS,*TASK_TOOLS,supabase_select,supabase_insert,request_approval,list_approvals],
 "research":[get_current_utc_time,local_datetime,weather_lookup,calculate,convert_unit,save_note,list_notes,read_note,scratchpad_set,scratchpad_get,scratchpad_list,*RESEARCH_TOOLS,*FILE_TOOLS,plan_task,find_contacts,*MEMORY_TOOLS,*TASK_TOOLS],
 "coding":[get_current_utc_time,local_datetime,set_timer,list_timers,stopwatch_start,stopwatch_pause,stopwatch_reset,stopwatch_status,calculate,convert_unit,detailed_system_status,scratchpad_set,scratchpad_get,scratchpad_list,zip_workspace_files,unzip_workspace_archive,format_json_text,format_yaml_text,compare_json_text,file_checksum,image_metadata,*FILE_TOOLS,run_python,github_repo_info,github_read_file,plan_task,*MEMORY_TOOLS,*TASK_TOOLS,request_approval,list_approvals],
 "manager":[get_current_utc_time,*LOCAL_UTILITY_TOOLS,*PRODUCTIVITY_TOOLS,local_datetime,date_difference,countdown_to,create_recurring_schedule,list_recurring_schedules,cancel_recurring_schedule,scratchpad_set,scratchpad_get,scratchpad_list,detailed_system_status,*COLLECTION_TOOLS,*ARTIFACT_TOOLS,*WORK_TOOLS,*MEMORY_TOOLS,*TASK_TOOLS,supabase_select,supabase_insert,request_approval,list_approvals],
 "github":[github_repo_info,github_read_file,read_text_file,write_text_file,list_workspace_files,detailed_system_status,file_checksum,zip_workspace_files,unzip_workspace_archive,plan_task,*MEMORY_TOOLS,*TASK_TOOLS,request_approval,list_approvals],
}


def _remove(tools:list,blocked:list)->list:
    blocked_ids={id(x) for x in blocked};return [x for x in tools if id(x) not in blocked_ids]


def tools_for(agent_type:str):
    profile=agent_type if agent_type in BASE_TOOLSETS else "general";tools=list(BASE_TOOLSETS[profile])
    if not skill_enabled("local-utils"):tools=_remove(tools,[*LOCAL_UTILITY_TOOLS,*PRODUCTIVITY_TOOLS,*ADVANCED_LOCAL_TOOLS])
    if not skill_enabled("research"):tools=_remove(tools,RESEARCH_TOOLS)
    if not skill_enabled("files"):tools=_remove(tools,FILE_TOOLS)
    if not skill_enabled("github"):tools=_remove(tools,[github_repo_info,github_read_file])
    return tools
