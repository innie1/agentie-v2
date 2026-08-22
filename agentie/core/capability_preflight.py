from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentie.core import agent_registry
from agentie.core.mcp_client import _approval_response, _error_text, _filesystem_root, execute_tool, inspect_server, list_servers

_FILE_EXTENSIONS = ("pdf","json","txt","md","csv","tsv","xlsx","xls","docx","doc","pptx","ppt","py","js","ts","yaml","yml","toml","ini","log","zip","sqlite","sqlite3")
_EXT_PATTERN = "|".join(_FILE_EXTENSIONS)
WORKSPACE = Path.cwd() / "workspace"


def _filesystem_server():
    return next((s for s in list_servers() if str(s.get("name") or "").lower()=="filesystem"),None)


def _agentmail_server():
    return next((s for s in list_servers() if str(s.get("name") or "").lower()=="agentmail"),None)


def _agentmail_settings_path(): return WORKSPACE/"agentmail_settings.json"
def _agentmail_history_path(): return WORKSPACE/"agentmail_history.json"


def _load_agentmail_settings():
    path=_agentmail_settings_path()
    if not path.exists(): return {}
    try:
        value=json.loads(path.read_text(encoding="utf-8"));return value if isinstance(value,dict) else {}
    except Exception:return {}


def _save_agentmail_settings(settings):
    path=_agentmail_settings_path();path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(settings,indent=2,ensure_ascii=False),encoding="utf-8")


def _load_agentmail_history():
    path=_agentmail_history_path()
    if not path.exists():return []
    try:
        value=json.loads(path.read_text(encoding="utf-8"));return value if isinstance(value,list) else []
    except Exception:return []


def _save_agentmail_history(items):
    path=_agentmail_history_path();path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(items[-500:],indent=2,ensure_ascii=False),encoding="utf-8")


def _agent_from_session(session_id):
    match=re.match(r"^agent:(agt_[a-z0-9]+):",str(session_id or ""),re.I);return agent_registry.get_agent(match.group(1)) if match else None


def _scoped_agentmail_settings(session_id):
    settings=_load_agentmail_settings();scoped={k:v for k,v in settings.items() if k!="agents"};agent=_agent_from_session(session_id)
    if agent:
        specific=(settings.get("agents") or {}).get(str(agent["id"]),{})
        if isinstance(specific,dict):scoped.update(specific)
    return scoped


def _set_scoped_agentmail_setting(session_id,key,value):
    settings=_load_agentmail_settings();agent=_agent_from_session(session_id)
    if agent:settings.setdefault("agents",{}).setdefault(str(agent["id"]),{})[key]=value
    else:settings[key]=value
    _save_agentmail_settings(settings);return settings,agent


def _email_address(text):
    match=re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",text,re.I);return match.group(0) if match else None


def _history_card(session_id):
    agent=_agent_from_session(session_id);items=_load_agentmail_history()
    if agent:items=[x for x in items if str(x.get("agent_id") or "")==str(agent["id"])]
    lines=[]
    for item in reversed(items[-20:]):
        line=f"{str(item.get('at') or '').replace('T',' ')[:19]} · {item.get('action') or 'email'}"
        if item.get("subject"):line+=f" · {item['subject']}"
        other=item.get("to") or item.get("from") or item.get("inbox_id") or ""
        if other:line+=f" · {other if isinstance(other,str) else ', '.join(map(str,other))}"
        route=item.get("routed_agent") or {}
        if route:line+=f" → {route.get('name')} ({route.get('role')})"
        lines.append(line)
    return {"message":f"Here is {'this agent’s' if agent else 'local'} recent email history.","card":{"type":"note","title":f"Email · {agent['name']} history" if agent else "Email · History","content":"\n".join(lines) if lines else "No email activity recorded yet."}}


def _agentmail_config(text,session_id=None):
    compact=" ".join(str(text or "").strip().split());low=compact.lower().strip(" .?!")
    if low in {"show email history","email history","show my email history","show agentmail history"}:return _history_card(session_id)
    m=re.match(r"^(?:set|save|remember)\s+(?:my\s+)?(?:notification|personal|destination)\s+email\s+(?:to|as)\s+(.+)$",compact,re.I)
    if m:
        address=_email_address(m.group(1))
        if not address:return {"message":"Please provide a valid email address.","card":None}
        _,agent=_set_scoped_agentmail_setting(session_id,"notification_email",address);owner=f" for {agent['name']}" if agent else ""
        return {"message":f"Saved {address} as the AgentMail notification email{owner}.","card":{"type":"note","title":"AgentMail settings","content":f"Notification email: {address}{owner}"}}
    m=re.match(r"^(?:set|save|remember)\s+(?:my\s+)?(?:agentmail\s+)?(?:sender\s+)?inbox(?:\s+id)?\s+(?:to|as)\s+([^\s]+)$",compact,re.I)
    if m:
        inbox_id=m.group(1).strip(" .?!\"'`")
        if not inbox_id:return {"message":"Please provide an AgentMail inbox ID.","card":None}
        _,agent=_set_scoped_agentmail_setting(session_id,"inbox_id",inbox_id);owner=f" for {agent['name']}" if agent else ""
        return {"message":f"Saved the AgentMail sender inbox{owner}.","card":{"type":"note","title":"AgentMail settings","content":f"Sender inbox: {inbox_id}{owner}"}}
    if low in {"show agentmail settings","agentmail settings","show my agentmail settings"}:
        settings=_scoped_agentmail_settings(session_id);agent=_agent_from_session(session_id);lines=[f"Scope: {agent['name']} ({agent['role']})" if agent else "Scope: default",f"Notification email: {settings.get('notification_email') or 'not set'}",f"Sender inbox: {settings.get('inbox_id') or 'not set'}"]
        return {"message":"Here are the local AgentMail settings.","card":{"type":"note","title":"AgentMail settings","content":"\n".join(lines)}}
    return None


def _agentmail_intent(text):
    low=" ".join(str(text or "").lower().split())
    if re.search(r"\b(?:gmail|google\s+(?:mail|email))\b",low):return False
    return bool(re.search(r"\b(?:email|e-mail|mail)\b",low) or "agentmail" in low or (re.search(r"\b(?:inbox|inboxes|message|messages|thread|threads)\b",low) and re.search(r"\b(?:check|list|show|read|open|search|reply)\b",low)))


def _agentmail_body(text):
    for pattern in (r"\b(?:saying|that says|with (?:the )?(?:message|body|text)|message|body)\s*[:=-]?\s*(.+)$",r"\bemail\s+me\s+(.+)$"):
        m=re.search(pattern,text,re.I)
        if m:
            value=m.group(1).strip().strip("\"'`")
            if value:return value
    return None


def _agentmail_subject(text):
    m=re.search(r"\bsubject\s*[:=-]?\s*[\"']?(.+?)[\"']?(?=\s+(?:saying|that says|with (?:the )?(?:message|body|text)|message|body)\b|$)",text,re.I);return m.group(1).strip(" .\"'`") if m else None


def _agentmail_recipient(text,settings):
    if re.search(r"\b(?:email|mail|send(?: an?)? email)\s+me\b",text.lower()):return str(settings.get("notification_email") or "") or None
    return _email_address(text)


def _tool_name(info,*names):
    available={str(x.get("name") or "").lower():str(x.get("name") or "") for x in info.get("tools") or []}
    return next((available[n.lower()] for n in names if n.lower() in available),None)


def _tool_schema(info,tool_name):
    for item in info.get("tools") or []:
        if str(item.get("name") or "").lower()==str(tool_name or "").lower():
            schema=item.get("input_schema") or item.get("inputSchema") or {};return schema if isinstance(schema,dict) else {}
    return {}


def _supported_arguments(info,tool_name,arguments):
    properties=_tool_schema(info,tool_name).get("properties")
    if not isinstance(properties,dict) or not properties:return arguments
    return {k:v for k,v in arguments.items() if k in properties}


def _email_signature(agent):
    if not agent:return ""
    name=str(agent.get("name") or "Agent").strip();role=str(agent.get("role") or "Agent").strip();role_line=role if re.search(r"\bAI\b",role,re.I) else f"AI {role} Agent";company=str(agent.get("company_identity") or "").strip();lines=["—",name,role_line]
    if company:lines.append(company)
    return "\n".join(lines)


def _sign_email_body(body,agent):
    text=str(body or "").strip();signature=_email_signature(agent)
    if not signature:return text
    name=str(agent.get("name") or "").strip()
    if name and name.casefold() in text[-250:].casefold() and re.search(r"\bAI\b",text[-250:],re.I):return text
    return f"{text}\n\n{signature}".strip()


def _message_or_thread_id(text):
    m=re.search(r"\b(?:email|message|thread)(?:\s+(?:id|#))?\s+([A-Za-z0-9._:-]{3,})\b",text,re.I);return m.group(1).strip() if m else None


def _search_query(text):
    m=re.search(r"\bsearch(?:\s+(?:my\s+)?(?:email|emails|messages|inbox|threads?))?\s+(?:for\s+)?(.+)$",text,re.I);return m.group(1).strip(" .?!\"'`") if m else ""


def _agentmail_choice(text,info,session_id=None):
    low=" ".join(text.lower().split());settings=_scoped_agentmail_settings(session_id);agent=_agent_from_session(session_id)
    if re.search(r"\b(?:list|show|what are|check)\b.*\b(?:agentmail\s+)?inboxes\b",low) or low in {"agentmail inboxes","list agentmail inboxes","list my agentmail inboxes"}:
        tool=_tool_name(info,"list_inboxes");return (tool,_supported_arguments(info,tool,{"limit":10})) if tool else None
    if re.search(r"\bsearch\b.*\b(?:email|emails|messages|inbox|threads?)\b",low):
        inbox_id=settings.get("inbox_id")
        if not inbox_id:return {"message":"Set your AgentMail inbox first.","card":None}
        query=_search_query(text)
        if not query:return {"message":"What should I search for in the inbox?","card":None}
        tool=_tool_name(info,"search_messages")
        if tool:return tool,_supported_arguments(info,tool,{"inboxId":inbox_id,"q":query,"query":query,"limit":30})
        tool=_tool_name(info,"list_threads")
        if tool:
            args={"inboxId":inbox_id,"limit":50};sender=re.search(r"\bfrom\s+(.+)$",query,re.I);recipient=re.search(r"\bto\s+(.+)$",query,re.I)
            if sender:args["senders"]=[sender.group(1).strip()]
            elif recipient:args["recipients"]=[recipient.group(1).strip()]
            else:args["subject"]=[query]
            return tool,_supported_arguments(info,tool,args)
        return None
    read_id=_message_or_thread_id(text) if re.search(r"\b(?:read|open|get|show)\b",low) else None
    if read_id:
        inbox_id=settings.get("inbox_id")
        if not inbox_id:return {"message":"Set your AgentMail inbox first.","card":None}
        tool=_tool_name(info,"get_message","read_message")
        if tool:return tool,_supported_arguments(info,tool,{"inboxId":inbox_id,"messageId":read_id,"id":read_id})
        tool=_tool_name(info,"get_thread")
        if tool:return tool,_supported_arguments(info,tool,{"inboxId":inbox_id,"threadId":read_id,"id":read_id})
    reply=re.search(r"\breply\s+to\s+(?:email|message|thread)(?:\s+(?:id|#))?\s+([A-Za-z0-9._:-]{3,})\s+(?:saying|with(?:\s+message)?|message|body)\s+(.+)$",text,re.I)
    if reply:
        inbox_id=settings.get("inbox_id")
        if not inbox_id:return {"message":"Set your AgentMail inbox first.","card":None}
        tool=_tool_name(info,"reply_to_message","reply_message")
        if not tool:return None
        return tool,_supported_arguments(info,tool,{"inboxId":inbox_id,"messageId":reply.group(1),"text":_sign_email_body(reply.group(2).strip(" \"'`"),agent)})
    if re.search(r"\b(?:check|list|show|read)\b.*\b(?:email|emails|messages|inbox|threads?)\b",low):
        inbox_id=settings.get("inbox_id")
        if not inbox_id:return {"message":"I need your AgentMail inbox ID first. Say “List my AgentMail inboxes”, then “Set my AgentMail inbox to <inboxId>”.","card":None}
        tool=_tool_name(info,"list_messages","list_threads")
        if tool:return tool,_supported_arguments(info,tool,{"inboxId":inbox_id,"limit":10})
    if re.match(r"^(?:please\s+)?(?:send(?:\s+an?)?\s+email|email|mail)\b",low):
        inbox_id=settings.get("inbox_id")
        if not inbox_id:return {"message":"I need the AgentMail inbox to send from. Say “List my AgentMail inboxes”, then “Set my AgentMail inbox to <inboxId>”.","card":None}
        recipient=_agentmail_recipient(text,settings)
        if not recipient:
            if re.search(r"\b(?:email|mail)\s+me\b",low):return {"message":"I need your destination email first. Say “Set my notification email to you@example.com”.","card":None}
            return {"message":"Tell me who to email, for example “Email person@example.com saying hello”.","card":None}
        tool=_tool_name(info,"send_message")
        if not tool:return None
        args={"inboxId":inbox_id,"to":[recipient],"subject":_agentmail_subject(text) or "Agentie update","text":_sign_email_body(_agentmail_body(text) or "Message from Agentie.",agent)}
        return tool,_supported_arguments(info,tool,args)
    return None


def _parse_mcp_payload(result):
    card=result.get("card") if isinstance(result,dict) else None;raw=str(card.get("content") or "") if isinstance(card,dict) else ""
    if not raw:return None
    for candidate in (raw,raw[raw.find("{"):] if "{" in raw else "",raw[raw.find("["):] if "[" in raw else ""):
        if not candidate:continue
        try:return json.loads(candidate)
        except Exception:continue
    return None


def _value(item,*keys):
    if not isinstance(item,dict):return None
    for key in keys:
        if item.get(key) not in (None,""):return item.get(key)
    return None


def _address_text(value):
    if isinstance(value,str):return value
    if isinstance(value,list):return ", ".join(_address_text(x) for x in value if _address_text(x))
    if isinstance(value,dict):return str(value.get("address") or value.get("email") or value.get("name") or "")
    return ""


def _routing_for_message(item):
    if not isinstance(item,dict):return None
    subject=str(_value(item,"subject","title") or "");sender=_address_text(_value(item,"from","sender","fromAddress"));recipients=_address_text(_value(item,"to","recipients","toAddresses"));preview=str(_value(item,"preview","snippet","text","body") or "")[:1600];content=" ".join([subject,sender,recipients,preview]).lower();words=set(re.findall(r"[a-z0-9]+",content));domain=(sender.rsplit("@",1)[-1].split(">",1)[0].strip() if "@" in sender else "").lower();scored=[]
    for agent in agent_registry.list_agents():
        if not agent.get("active",True):continue
        role=str(agent.get("role") or "").lower();name=str(agent.get("name") or "").lower();goal=str(agent.get("goal") or "").lower();responsibilities=" ".join(map(str,agent.get("responsibilities") or [])).lower();profile=" ".join([role,goal,responsibilities]);profile_words=set(re.findall(r"[a-z0-9]+",profile));score=0
        if name and re.search(rf"\b{re.escape(name)}\b",content):score+=8
        vocab=set()
        if re.search(r"sales|outreach|business development|lead",profile):vocab|={"sales","lead","leads","client","customer","prospect","quote","pricing","outreach"}
        if re.search(r"marketing|content|social|brand",profile):vocab|={"marketing","content","social","campaign","brand","copy","post"}
        if re.search(r"finance|account|bookkeep",profile):vocab|={"invoice","payment","expense","finance","accounting","receipt","budget"}
        if re.search(r"research|analyst|critic|verify",profile):vocab|={"research","source","evidence","report","verify","analysis"}
        if re.search(r"technical|cto|engineer|developer|coding",profile):vocab|={"technical","github","code","bug","deploy","server","api","software"}
        if words&vocab and (domain in profile or profile_words&vocab):score+=4
        scored.append((score,agent))
    scored.sort(key=lambda x:(-x[0],str(x[1].get("name") or "").casefold()))
    if not scored or scored[0][0]<4 or (len(scored)>1 and scored[1][0]==scored[0][0]):return None
    agent=scored[0][1];return {"id":str(agent.get("id") or ""),"name":str(agent.get("name") or ""),"role":str(agent.get("role") or "")}


def _collect_email_items(payload):
    if isinstance(payload,list):return [x for x in payload if isinstance(x,dict)]
    if not isinstance(payload,dict):return []
    for key in ("messages","threads","inboxes","items","results"):
        if isinstance(payload.get(key),list):return [x for x in payload[key] if isinstance(x,dict)]
    if isinstance(payload.get("thread"),dict):
        thread=payload["thread"]
        if isinstance(thread.get("messages"),list):return [x for x in thread["messages"] if isinstance(x,dict)]
        return [thread]
    return [payload] if any(k in payload for k in ("messageId","threadId","inboxId","subject")) else []


def _email_note(tool_name,payload,arguments):
    tool=str(tool_name or "").lower();items=_collect_email_items(payload);lines=[];routed_first=None
    if tool=="list_inboxes":
        for item in items[:20]:
            email=_address_text(_value(item,"email","address"));display=str(_value(item,"displayName","name") or "").strip();inbox_id=str(_value(item,"inboxId","id") or "").strip();lines.append(f"{display+' · ' if display else ''}{email or 'Inbox'}"+(f"\nInbox ID: {inbox_id}" if inbox_id else ""))
        return "Email · Inboxes","\n\n".join(lines) or "No inboxes returned.",None
    for item in items[:20]:
        subject=str(_value(item,"subject","title") or "(no subject)").strip();sender=_address_text(_value(item,"from","sender","fromAddress"));date=str(_value(item,"createdAt","sentAt","receivedAt","date","updatedAt") or "").replace("T"," ")[:19];ident=str(_value(item,"messageId","threadId","id") or "").strip();preview=str(_value(item,"preview","snippet","text","body") or "").strip().replace("\n"," ")
        if len(preview)>220:preview=preview[:217].rstrip()+"..."
        route=_routing_for_message(item);routed_first=routed_first or route;meta=" · ".join(x for x in (f"From: {sender}" if sender else "",date,f"ID: {ident}" if ident else "") if x);block=subject+(f"\n{meta}" if meta else "")
        if preview:block+=f"\n{preview}"
        if route:block+=f"\n→ Routed to {route['name']} ({route['role']})"
        lines.append(block)
    if tool in {"send_message","reply_to_message","reply_message","forward_message","send_draft"}:
        title="Email · Sent"
        if not lines:lines=[str(arguments.get("subject") or "Email")+(f"\nTo: {_address_text(arguments.get('to'))}" if arguments.get("to") else "")+"\nSent through AgentMail."]
    elif "search" in tool:title="Email · Search"
    elif tool in {"get_message","read_message","get_thread"}:title="Email · Message"
    else:title="Email · Inbox"
    return title,"\n\n".join(lines) or "AgentMail completed without a structured message list.",routed_first


def _record_email_history(tool_name,arguments,session_id,payload,routed=None):
    agent=_agent_from_session(session_id);items=_collect_email_items(payload);first=items[0] if items else {};row={"at":datetime.now(timezone.utc).isoformat(),"action":str(tool_name or ""),"agent_id":agent.get("id") if agent else None,"agent_name":agent.get("name") if agent else None,"inbox_id":arguments.get("inboxId"),"subject":arguments.get("subject") or _value(first,"subject","title"),"to":arguments.get("to"),"from":_address_text(_value(first,"from","sender","fromAddress")) or None,"message_id":arguments.get("messageId") or _value(first,"messageId","id"),"thread_id":arguments.get("threadId") or _value(first,"threadId"),"routed_agent":routed};history=_load_agentmail_history();history.append({k:v for k,v in row.items() if v not in (None,"",[],{})});_save_agentmail_history(history)


def finalize_agentmail_result(tool_name,arguments,result,session_id=None):
    payload=_parse_mcp_payload(result);title,content,routed=_email_note(tool_name,payload,arguments);_record_email_history(tool_name,arguments,session_id,payload,routed)
    if payload is None:return result
    return {"message":f"AgentMail {str(tool_name).replace('_',' ')} completed.","card":{"type":"note","title":title,"content":content}}


def _filename(text):
    quoted=re.search(rf"[\"'`]([^\"'`\r\n]+\.(?:{_EXT_PATTERN}))[\"'`]",text,re.I)
    if quoted:return quoted.group(1).strip()
    match=re.search(rf"([\w][\w .()\-]*\.(?:{_EXT_PATTERN}))(?=$|[\s,;:!?]|\.(?:\s|$))",text,re.I)
    if not match:return None
    candidate=match.group(1).strip(" .?!\"'`");candidate=re.sub(r"^(?:please\s+)?(?:read|open|display|view|inspect|create|make|write|edit|update|append to|move|rename)\s+(?:(?:a|another|the)\s+)?(?:file\s+)?(?:called|named)?\s*","",candidate,flags=re.I);candidate=re.sub(r"^(?:please\s+)?show\s+me\s+(?:(?:information|info|details|metadata)\s+about\s+)?(?:the\s+)?","",candidate,flags=re.I);candidate=re.sub(r"^(?:(?:information|info|details|metadata)\s+about\s+)(?:the\s+)?","",candidate,flags=re.I);return candidate.strip(" .?!\"'`") or None


def _folder_name(text):
    match=re.search(r"\b(?:create|make)\s+(?:(?:a|another|the)\s+)?(?:folder|directory)\s+(?:called|named)\s+(.+?)(?=\s+(?:in|inside|under)\s+(?:the\s+)?(?:workspace|folder|directory)\b|[.!?]?$)",text,re.I)
    if not match:return None
    value=match.group(1).strip().strip("\"'` .!?");return None if not value or value in {".",".."} or "/" in value or "\\" in value else value


def _extension_search(text):
    low=text.lower()
    if not re.search(r"\b(?:find|search|locate)\b",low):return None
    wildcard=re.search(rf"\*\.({_EXT_PATTERN})\b",low)
    if wildcard:return f"*.{wildcard.group(1).lower()}"
    named=re.search(rf"\b({_EXT_PATTERN})\s+files?\b",low);return f"*.{named.group(1).lower()}" if named else None


def _allowed_directories_request(text):
    low=" ".join(text.lower().split()).strip(" .?!");return bool(re.search(r"\b(?:what|which|show|list|tell me)\b.*\b(?:directories|folders)\b.*\b(?:can|allowed|access|accessible)\b",low) or re.search(r"\b(?:directories|folders)\b.*\b(?:can i|am i allowed to)\b.*\baccess\b",low))


def _mutation_request(text):
    low=" ".join(text.lower().split());return bool(re.search(r"\b(?:create|make|write|edit|update|append|move|rename)\b",low) and (_filename(text) or _folder_name(text) or re.search(r"\b(?:file|folder|directory|workspace)\b",low)))


def _content_after_marker(text):
    m=re.search(r"\b(?:containing|with content|with the content|that says|saying)\s+(.+)$",text,re.I);return m.group(1).strip().strip("\"'`") if m else None


def _rename_target(text):
    m=re.search(rf"\b(?:to|as)\s+([\w][\w .()\-]*\.(?:{_EXT_PATTERN}))\b",text,re.I);return m.group(1).strip(" .?!\"'`") if m else None


def _join_root(root,filename):
    if re.match(r"^[A-Za-z]:\\",filename) or filename.startswith("/"):return filename
    return str(Path(root)/filename) if root else None


def _choice(text,server,info):
    low=text.lower();root=_filesystem_root(server)
    if _allowed_directories_request(text):
        tool=_tool_name(info,"list_allowed_directories")
        if tool:return tool,{}
    pattern=_extension_search(text)
    if pattern and root:
        tool=_tool_name(info,"search_files")
        if tool:return tool,{"path":root,"pattern":pattern}
    folder=_folder_name(text)
    if folder and root and re.search(r"\b(?:create|make)\b",low):
        tool=_tool_name(info,"create_directory")
        if tool:return tool,{"path":str(Path(root)/folder)}
    filename=_filename(text)
    if not filename:return None
    path=_join_root(root,filename)
    if not path:return None
    if re.search(r"\b(?:create|make|write)\b",low):
        tool=_tool_name(info,"write_file");content=_content_after_marker(text)
        if tool and content is not None:return tool,{"path":path,"content":content}
    if re.search(r"\b(?:move|rename)\b",low):
        tool=_tool_name(info,"move_file");target=_rename_target(text)
        if tool and target:
            destination=_join_root(root,target)
            if destination:return tool,{"source":path,"destination":destination}
    if re.search(r"\b(?:information|info|details|metadata|size|modified|created)\b",low):
        tool=_tool_name(info,"get_file_info")
        if tool:return tool,{"path":path}
    if re.search(r"\b(?:read|open|show|display|inspect|view)\b",low):
        tool=_tool_name(info,"read_text_file","read_file")
        if tool:return tool,{"path":path}
    return None


async def _route_agentmail(text,session_id=None):
    configured=_agentmail_config(text,session_id)
    if configured is not None:return configured
    if not _agentmail_intent(text):return None
    if not _agentmail_server():return {"message":"AgentMail is not registered yet. Add it from Plugins, then try the email request again.","card":None}
    try:info=await inspect_server("agentmail")
    except Exception as exc:return {"message":f"AgentMail is registered but not connected: {_error_text(exc)}. Make sure AGENTMAIL_API_KEY is set and restart Agentie.","card":None}
    choice=_agentmail_choice(text,info,session_id)
    if isinstance(choice,dict):return choice
    if not choice:return None
    tool_name,arguments=choice;canonical=f"Call MCP agentmail tool {tool_name} with {json.dumps(arguments,ensure_ascii=False)}";approval=_approval_response("agentmail",tool_name,arguments,canonical,natural=True)
    if approval.get("approved"):
        try:return finalize_agentmail_result(tool_name,arguments,await execute_tool("agentmail",tool_name,arguments),session_id)
        except Exception as exc:return {"message":f"The approved AgentMail action could not complete: {_error_text(exc)}","card":None}
    if isinstance(approval.get("card"),dict):
        approval["card"]["command"] = text
    return approval


async def route_capability_preflight(message,session_id=None):
    text=" ".join(str(message or "").strip().split())
    if not text:return None
    agentmail=await _route_agentmail(text,session_id)
    if agentmail is not None:return agentmail
    if not (_filename(text) or _extension_search(text) or _allowed_directories_request(text) or _mutation_request(text)):return None
    server=_filesystem_server()
    if not server:return None
    try:info=await inspect_server("filesystem")
    except Exception:return None
    choice=_choice(text,server,info)
    if not choice:return None
    tool_name,arguments=choice;canonical=f"Call MCP filesystem tool {tool_name} with {json.dumps(arguments,ensure_ascii=False)}";approval=_approval_response("filesystem",tool_name,arguments,canonical,natural=True)
    if approval.get("approved"):
        try:return await execute_tool("filesystem",tool_name,arguments)
        except Exception as exc:return {"message":f"The approved MCP tool call could not complete: {_error_text(exc)}","card":None}
    return approval
