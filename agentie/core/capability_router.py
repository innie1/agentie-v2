from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agentie.core.mcp_client import (
    _approval_response,
    _error_text,
    _filesystem_root,
    _infer_natural_tool,
    execute_tool,
    get_server,
    inspect_server,
    list_servers,
)
from agentie.core.plugin_credentials import setup_response
from agentie.core.skill_registry import skills_for_agent

_STOPWORDS = {
    "a", "an", "and", "are", "at", "be", "can", "do", "for", "from", "in", "into", "is",
    "it", "me", "my", "of", "on", "please", "the", "this", "to", "using", "want", "what",
    "with", "you", "your",
}

# Native Agentie behavior wins for these intents. The automatic external router only
# runs after normal local routing, but these guards provide another regression barrier.
_NATIVE_GUARDS = (
    r"\b(?:timer|stopwatch|alarm|remind|reminder)\b",
    r"\b(?:calculate|calculator|convert)\b",
    r"\brun\s+(?:this\s+)?python\b|\bpython\s*:",
    r"\b(?:what time is it|current time|local time)\b",
    r"\bremember\s+(?:that\s+)?(?:my|i)\b",
)


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9_+-]+", str(value or "").lower())
        if len(token) > 1 and token not in _STOPWORDS
    }


def _native_guarded(text: str) -> bool:
    lower = str(text or "").lower()
    return any(re.search(pattern, lower, re.I) for pattern in _NATIVE_GUARDS)


def _windows_path(text: str) -> str | None:
    match = re.search(r"([A-Za-z]:\\[^\n\r\"']+)", text)
    return match.group(1).strip().rstrip(" .?!") if match else None


def _unix_path(text: str) -> str | None:
    match = re.search(r"(?<!\w)(/[^\s\"']+/[^\s\"']*)", text)
    return match.group(1).strip().rstrip(" .?!") if match else None


def _url(text: str) -> str | None:
    match = re.search(r"https?://[^\s<>\"']+", text, re.I)
    return match.group(0).rstrip(".,;!?)") if match else None


def _explicit_path(text: str) -> str | None:
    return _windows_path(text) or _unix_path(text)


def _server_by_names(*names: str) -> dict[str, Any] | None:
    wanted = {x.lower() for x in names}
    for server in list_servers():
        if str(server.get("name") or "").lower() in wanted:
            return server
    return None


def _looks_filesystem(text: str) -> bool:
    low = text.lower()
    nouns = re.search(r"\b(?:file|files|folder|folders|directory|directories|workspace)\b", low)
    verbs = re.search(r"\b(?:look|show|list|read|open|inspect|find|search|create|make|write|edit|move|rename|tree|info|details)\b", low)
    place = _explicit_path(text) is not None or "workspace" in low or "this place" in low or "this folder" in low or "this directory" in low
    return bool(nouns and verbs and place)


def _looks_git(text: str) -> bool:
    low = text.lower()
    return bool(
        re.search(r"\b(?:git|repository|repo)\b", low)
        and re.search(r"\b(?:status|diff|commit|commits|branch|branches|log|history|show|list|inspect|search)\b", low)
    )


def _looks_fetch(text: str) -> bool:
    low = text.lower()
    return bool(_url(text) and re.search(r"\b(?:fetch|read|open|inspect|get|retrieve|page|website|url)\b", low))


def _looks_graph_memory(text: str) -> bool:
    low = text.lower()
    return bool(
        re.search(r"\b(?:knowledge graph|entity|entities|relation|relations|graph memory)\b", low)
        and re.search(r"\b(?:create|add|search|find|show|list|read|delete|remove)\b", low)
    )


def _looks_google_workspace(text: str) -> bool:
    low=text.lower()
    service=bool(re.search(r"\b(?:gmail|google\s+(?:mail|drive|docs?|sheets?|slides?|calendar|contacts?|workspace))\b",low))
    action=bool(re.search(r"\b(?:check|list|show|read|open|search|find|send|reply|draft|create|make|update|edit|delete|remove|share|upload|download|schedule|calendar|email)\b",low))
    return service and action


def _looks_canva(text: str) -> bool:
    low=text.lower();return bool("canva" in low and re.search(r"\b(?:show|list|search|find|create|make|generate|edit|update|export|download|comment|design)\b",low))


def _tool_map(info: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("name") or "").lower(): item for item in info.get("tools") or [] if item.get("name")}


def _pick_name(info: dict[str, Any], names: tuple[str, ...]) -> str | None:
    tools = _tool_map(info)
    for name in names:
        if name.lower() in tools:
            return str(tools[name.lower()].get("name"))
    return None


def _schema_for(info: dict[str, Any], tool_name: str) -> dict[str, Any]:
    for item in info.get("tools") or []:
        if str(item.get("name") or "").lower() == tool_name.lower():
            value = item.get("input_schema")
            return value if isinstance(value, dict) else {}
    return {}


def _required(schema: dict[str, Any]) -> list[str]:
    value = schema.get("required")
    return [str(x) for x in value] if isinstance(value, list) else []


def _set_schema_value(schema: dict[str, Any], args: dict[str, Any], names: tuple[str, ...], value: Any) -> bool:
    props=schema.get("properties") if isinstance(schema.get("properties"),dict) else {}
    by_lower={str(key).lower():str(key) for key in props}
    key=next((by_lower[name.lower()] for name in names if name.lower() in by_lower),None)
    if key is None and not props:key=names[0]
    if key is None:return False
    prop=props.get(key) if isinstance(props.get(key),dict) else {}
    if prop.get("type")=="array" and not isinstance(value,list):value=[value]
    args[key]=value;return True


def _arguments_complete(schema: dict[str, Any], args: dict[str, Any]) -> bool:
    return all(key in args for key in _required(schema))


def _after(text: str, pattern: str) -> str:
    match=re.search(pattern,text,re.I);return match.group(1).strip(" .?!\"'`") if match else ""


def _email_address(text: str) -> str | None:
    match=re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",text,re.I);return match.group(0) if match else None


def _infer_common_arguments(text: str, schema: dict[str, Any], server: dict[str, Any]) -> dict[str, Any] | None:
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = _required(schema)
    args: dict[str, Any] = {}
    path = _explicit_path(text)
    root = _filesystem_root(server)
    url = _url(text)

    for key in props:
        lower = key.lower()
        if lower in {"path", "directory", "directory_path", "file", "file_path"}:
            if path or root:
                args[key] = path or root
        elif lower in {"url", "uri"} and url:
            args[key] = url
        elif lower in {"query", "pattern", "search", "search_term"}:
            quoted = re.search(r"[\"']([^\"']+)[\"']", text)
            if quoted:
                args[key] = quoted.group(1)

    if any(key not in args for key in required):
        return None
    return args


def _lexical_tool(text: str, info: dict[str, Any], server: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    query = _tokens(text)
    if not query:
        return None
    best: tuple[int, str, dict[str, Any]] | None = None
    for item in info.get("tools") or []:
        name = str(item.get("name") or "")
        hay = " ".join([name, str(item.get("title") or ""), str(item.get("description") or "")])
        tool_tokens = _tokens(hay.replace("_", " ").replace("-"," "))
        overlap = len(query & tool_tokens)
        if overlap < 2:
            continue
        schema = item.get("input_schema") if isinstance(item.get("input_schema"), dict) else {}
        args = _infer_common_arguments(text, schema, server)
        if args is None:
            continue
        score = overlap * 2 + (1 if str(server.get("name") or "").lower() in query else 0)
        if best is None or score > best[0]:
            best = (score, name, args)
    if best and best[0] >= 4:
        return best[1], best[2]
    return None


def _filesystem_choice(text: str, server: dict[str, Any], info: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    direct = _infer_natural_tool(text, server, info)
    if direct:
        return direct
    low = text.lower();root=_filesystem_root(server);path=_explicit_path(text) or root
    if not path:return None
    if re.search(r"\b(?:look at|show|list|inspect)\b", low) and re.search(r"\b(?:files|folder|directory|workspace|place)\b", low):
        tool = _pick_name(info, ("list_directory", "list_directory_with_sizes"))
        if tool:return tool,{"path":path}
    return _lexical_tool(text, info, server)


def _git_choice(text: str, server: dict[str, Any], info: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    low = text.lower()
    mapping = [
        (("status",), ("git_status", "status")),
        (("diff", "changes"), ("git_diff_unstaged", "git_diff", "diff")),
        (("log", "history", "commits"), ("git_log", "log")),
        (("branches", "branch"), ("git_branch", "list_branches", "branches")),
    ]
    for words, names in mapping:
        if any(word in low for word in words):
            tool = _pick_name(info, names)
            if tool:
                schema = _schema_for(info, tool);args = _infer_common_arguments(text, schema, server)
                if args is not None:
                    for key in _required(schema):
                        if key.lower() in {"repo_path", "repository", "repository_path"} and key not in args:args[key]=str(Path.cwd())
                    if _arguments_complete(schema,args):return tool,args
    return _lexical_tool(text, info, server)


def _fetch_choice(text: str, server: dict[str, Any], info: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    url = _url(text)
    if not url:return None
    tool=_pick_name(info,("fetch","fetch_url","get_url"))
    if not tool:return _lexical_tool(text,info,server)
    schema=_schema_for(info,tool);props=schema.get("properties") if isinstance(schema.get("properties"),dict) else {};key="url" if "url" in props or not props else next((x for x in props if x.lower() in {"url","uri"}),"url");args={key:url}
    return (tool,args) if _arguments_complete(schema,args) else None


def _memory_choice(text: str, server: dict[str, Any], info: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    return _lexical_tool(text, info, server)


def _google_workspace_choice(text: str, server: dict[str, Any], info: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    low=text.lower()
    if re.search(r"\b(?:gmail|google\s+mail)\b",low):
        if re.search(r"\b(?:send|email|mail)\b",low) and _email_address(text):
            tool=_pick_name(info,("sendEmail","send_email"))
            if tool:
                schema=_schema_for(info,tool);args={};recipient=_email_address(text);subject=_after(text,r"\bsubject\s*[:=-]?\s*[\"']?(.+?)[\"']?(?=\s+(?:saying|message|body|with)\b|$)") or "Agentie message";body=_after(text,r"\b(?:saying|message|body|that says|with (?:the )?(?:message|body))\s*[:=-]?\s*(.+)$") or "Message from Agentie."
                _set_schema_value(schema,args,("to","recipient","recipients"),recipient);_set_schema_value(schema,args,("subject",),subject);_set_schema_value(schema,args,("body","text","message"),body)
                if _arguments_complete(schema,args):return tool,args
        if re.search(r"\b(?:read|open|get)\b",low):
            ident=_after(text,r"\b(?:email|message)(?:\s+(?:id|#))?\s+([A-Za-z0-9._:-]{3,})\b")
            tool=_pick_name(info,("readEmail","read_email"))
            if tool and ident:
                schema=_schema_for(info,tool);args={};_set_schema_value(schema,args,("messageId","message_id","id"),ident)
                if _arguments_complete(schema,args):return tool,args
        tool=_pick_name(info,("searchEmails","search_emails"))
        if tool:
            schema=_schema_for(info,tool);args={};query=_after(text,r"\b(?:search|find)\b.*?\b(?:gmail|emails?|mail)\b(?:\s+for)?\s+(.+)$") or "in:inbox"
            _set_schema_value(schema,args,("query","q","search"),query);_set_schema_value(schema,args,("maxResults","limit","pageSize"),10)
            if _arguments_complete(schema,args):return tool,args
    if "google drive" in low:
        if re.search(r"\b(?:search|find)\b",low):
            tool=_pick_name(info,("search","searchFiles","search_files"))
            if tool:
                schema=_schema_for(info,tool);args={};query=_after(text,r"\b(?:search|find)\b.*?\b(?:google\s+)?drive\b(?:\s+for)?\s+(.+)$")
                if query:_set_schema_value(schema,args,("query","q","name"),query)
                if _arguments_complete(schema,args):return tool,args
        if re.search(r"\b(?:list|show|open|check)\b",low):
            tool=_pick_name(info,("listFolder","list_folder"))
            if tool:
                schema=_schema_for(info,tool);args={};_set_schema_value(schema,args,("folderId","folder_id","id"),"root")
                if _arguments_complete(schema,args):return tool,args
    if "google calendar" in low:
        tool=_pick_name(info,("listEvents","list_events"))
        if tool and re.search(r"\b(?:check|list|show|read|events?|schedule)\b",low):
            schema=_schema_for(info,tool);args={};_set_schema_value(schema,args,("calendarId","calendar_id"),"primary")
            if _arguments_complete(schema,args):return tool,args
    if re.search(r"\bgoogle\s+contacts?\b",low):
        tool=_pick_name(info,("listContacts","list_contacts"))
        if tool and re.search(r"\b(?:check|list|show|read|contacts?)\b",low):
            schema=_schema_for(info,tool);args={};_set_schema_value(schema,args,("limit","pageSize","maxResults"),20)
            if _arguments_complete(schema,args):return tool,args
    create_specs=(("google doc","google docs"),("createGoogleDoc","create_google_doc")),(("google sheet","google sheets"),("createGoogleSheet","create_google_sheet")),(("google slide","google slides"),("createGoogleSlides","create_google_slides"))
    for labels,names in create_specs:
        if any(label in low for label in labels) and re.search(r"\b(?:create|make|new)\b",low):
            tool=_pick_name(info,names)
            if tool:
                schema=_schema_for(info,tool);args={};title=_after(text,r"\b(?:called|named|titled)\s+(.+)$") or _after(text,r"\b(?:doc|document|sheet|spreadsheet|slide|presentation)\s+(.+)$")
                if title:_set_schema_value(schema,args,("title","name"),title)
                if _arguments_complete(schema,args):return tool,args
    return _lexical_tool(text,info,server)


def _canva_choice(text: str, server: dict[str, Any], info: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    low=text.lower()
    if re.search(r"\b(?:search|find|show|list)\b",low) and re.search(r"\b(?:design|designs|canva)\b",low):
        tool=_pick_name(info,("search-designs","search_designs","list-designs","list_designs"))
        if tool:
            schema=_schema_for(info,tool);args={}
            query=_after(text,r"\b(?:search|find)\b.*?\bcanva\b(?:\s+designs?)?(?:\s+for)?\s+(.+)$")
            if not query:
                query=_after(text,r"\b(?:search|find)\b.*?\bdesigns?\b(?:\s+for)?\s+(.+)$")
            if query:_set_schema_value(schema,args,("query","search","term"),query)
            _set_schema_value(schema,args,("limit","pageSize"),10)
            if _arguments_complete(schema,args):return tool,args
    direct=_infer_natural_tool(text,server,info)
    if direct:return direct
    return _lexical_tool(text,info,server)


async def _prepare(server: dict[str, Any], text: str, chooser, *, surface_setup: bool=False) -> dict[str, Any] | None:
    name = str(server.get("name") or "")
    if not name:return None
    try:info=await inspect_server(name)
    except Exception as exc:
        return setup_response(name,_error_text(exc)) if surface_setup else None
    choice=chooser(text,server,info)
    if not choice:return None
    tool_name,arguments=choice;canonical=f"Call MCP {name} tool {tool_name} with {json.dumps(arguments, ensure_ascii=False)}";approval=_approval_response(name,tool_name,arguments,canonical,natural=True)
    if approval.get("approved"):
        try:return await execute_tool(name,tool_name,arguments)
        except Exception as exc:return {"message":f"The approved MCP tool call could not complete: {_error_text(exc)}","card":None}
    return approval


async def route_capability_request(message: str, agent_type: str = "general") -> dict[str, Any] | None:
    """Route an unresolved request to an installed capability without requiring its name."""
    text=" ".join(str(message or "").strip().split())
    if not text or _native_guarded(text):return None
    _=skills_for_agent(agent_type)

    if _looks_google_workspace(text):
        server=_server_by_names("google-workspace")
        if server:
            result=await _prepare(server,text,_google_workspace_choice,surface_setup=True)
            if result:return result

    if _looks_canva(text):
        server=_server_by_names("canva")
        if server:
            result=await _prepare(server,text,_canva_choice,surface_setup=True)
            if result:return result

    if _looks_filesystem(text):
        server=_server_by_names("filesystem")
        if server:
            result=await _prepare(server,text,_filesystem_choice)
            if result:return result

    if _looks_git(text):
        server=_server_by_names("git")
        if server:
            result=await _prepare(server,text,_git_choice)
            if result:return result

    if _looks_fetch(text):
        server=_server_by_names("fetch")
        if server:
            result=await _prepare(server,text,_fetch_choice)
            if result:return result

    if _looks_graph_memory(text):
        server=_server_by_names("memory")
        if server:
            result=await _prepare(server,text,_memory_choice)
            if result:return result

    return None
