import json,mimetypes,os,re
from types import SimpleNamespace
from datetime import datetime,timedelta
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

load_dotenv()

import uvicorn
from fastapi import FastAPI,File,HTTPException,Request,UploadFile
from fastapi.responses import FileResponse,HTMLResponse,Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from agentie.core.agent_access import access_snapshot,guard_agent_capability,set_mcp_access,set_skill_access
from agentie.core.agent_builder import draft_agent_spec,normalize_create_spec
from agentie.core.agent_prompt import set_manual_instructions
from agentie.core.agent_registry import create_agent,get_agent,list_agents
from agentie.core.agent_threads import create_thread,get_thread,list_threads,post_message,route_thread_command,thread_card,threads_card
from agentie.core.attachment_reasoner import reason_about_documents
from agentie.core.browser_monitor import LIVE_FRAME_FILE,SNAPSHOT_DIR,get_live_state,request_browser_stop,route_browser_request
from agentie.core.capability_preflight import route_capability_preflight
from agentie.core.capability_router import route_capability_request
from agentie.core.code_execution import route_code_command
from agentie.core.conversation_loop import consume_followup,detect_incomplete_intent
from agentie.core.file_service import MAX_FILE_BYTES,resolve_upload,run_action,save_upload
from agentie.core.local_router import route_local_actions
from agentie.core.mcp_catalog import presets as mcp_presets
from agentie.core.mcp_client import get_server,inspect_server,list_servers,plugin_state,route_mcp_command
from agentie.core.memory_store import add_message,recent_messages
from agentie.core.observability import finish_trace,get_trace,record_event,record_route,recent_traces,start_trace,summary_card,trace_card
from agentie.core.office_artifacts import try_office_request
from agentie.core.pdf_service import try_pdf_request
from agentie.core.platform_next4_api import router as platform_next4_router
from agentie.core.plugin_credentials import apply_all_credentials,clear_credentials,enrich_setup_failure,public_setup_state,save_credentials,start_oauth_connection
from agentie.core.provider_gate import local_fallback_message,provider_allowed
from agentie.core.reference_router import remember_active_from_card,try_active_reference
from agentie.core.routine_engine import list_routines
from agentie.core.routine_worker import poll_routine_events,start_routine_worker
from agentie.core.runner import run_agent
from agentie.core.skill_registry import list_skills
from agentie.core.specialty_router import maybe_auto_delegate
from agentie.core.team_orchestrator import create_team_job,start_team_job
from agentie.core.telegram_channel import configure as configure_telegram,create_pair_code as create_telegram_pair_code,disconnect as disconnect_telegram,public_state as telegram_public_state,set_handler as set_telegram_handler,start_all as start_telegram_channels
from agentie.core.telegram_channel import queue_proactive as queue_telegram_proactive
from agentie.core.whatsapp_cloud import poll_events as poll_whatsapp_events
from agentie.core.whatsapp_webhook import router as whatsapp_router
from agentie.core.workflow_skills import create_workflow_skill,skill_card
from agentie.tools import local_utility_tools as local_utils
from agentie.tools.approval_tools import resolve_approval
from agentie.tools.advanced_utility_tools import SCHEDULES
from agentie.tools.productivity_tools import REMINDERS

app=FastAPI(title="Agentie API",version="1.10.1",description="Local-first Agentie runtime with persistent user-defined agents, skills, routines, collaboration, plugins, approvals, memory and local artifact generation")
app.include_router(whatsapp_router)
app.include_router(platform_next4_router)
FRONTEND_DIR=Path(__file__).parent/"frontend";FRONTEND_FILE=FRONTEND_DIR/"index.html";FRONTEND_DIST=FRONTEND_DIR/"dist";CARDS_JS=FRONTEND_DIR/"cards.js";EVENTS_JS=FRONTEND_DIR/"events.js";UPLOAD_JS=FRONTEND_DIR/"upload.js";PLUGINS_JS=FRONTEND_DIR/"plugins.js";PLUGIN_SETUP_JS=FRONTEND_DIR/"plugin_setup.js";PLUGIN_ACCESS_JS=FRONTEND_DIR/"plugin_access.js";TELEGRAM_JS=FRONTEND_DIR/"telegram_plugin.js";BROWSER_SCREEN_JS=FRONTEND_DIR/"browser_screen.js";UI_UPGRADE_JS=FRONTEND_DIR/"ui_upgrade.js";PLATFORM_JS=FRONTEND_DIR/"platform.js"
if (FRONTEND_DIST/"assets").exists():app.mount("/assets",StaticFiles(directory=FRONTEND_DIST/"assets"),name="frontend-assets")
class AgentRequest(BaseModel):
    message:str=Field(min_length=1,max_length=20_000);agent_type:str=Field(default="general",pattern="^(general|research|coding|manager|github)$");session_id:str|None=Field(default=None,max_length=200)
class AgentResponse(BaseModel):
    message:str;result:str;card:dict[str,Any]|None=None;agent_type:str;routed_by:str
class AttachmentReasonRequest(BaseModel):question:str=Field(min_length=1,max_length=12_000);filenames:list[str]=Field(min_length=1,max_length=8)
class ApprovalDecision(BaseModel):approved:bool
class FileAction(BaseModel):action:str=Field(pattern="^(inspect|checksum|extract|text|preview)$")
class AgentAccessUpdate(BaseModel):kind:str=Field(pattern="^(skill|mcp)$");capability_id:str=Field(min_length=1,max_length=120);mode:str|None=Field(default=None,pattern="^(inherit|allow|block)$");allowed:bool|None=None
class PluginSetupUpdate(BaseModel):values:dict[str,str]=Field(default_factory=dict)
class TelegramSetupRequest(BaseModel):token:str=Field(min_length=20,max_length=256)
class AgentBuilderDraftRequest(BaseModel):description:str=Field(min_length=1,max_length=5000);name:str="";job:str=""
class AgentBuilderCreateRequest(BaseModel):
    name:str=Field(min_length=1,max_length=120);job:str=Field(min_length=1,max_length=500);description:str="";goal:str="";working_style:str="";responsibilities:list[str]=Field(default_factory=list);instructions:str="";skills:list[str]=Field(default_factory=list);plugins:list[str]=Field(default_factory=list);approval_policy:dict[str,Any]=Field(default_factory=dict);memory_policy:dict[str,Any]=Field(default_factory=dict);can_delegate:bool=False;manager_id:str|None=None
class WorkflowSkillCreateRequest(BaseModel):
    name:str=Field(min_length=1,max_length=120);description:str="";when_to_use:str="";required_inputs:list[str]=Field(default_factory=list);required_access:list[str]=Field(default_factory=list);steps:list[str]=Field(default_factory=list);decision_rules:list[str]=Field(default_factory=list);expected_output:str="";validation_rules:list[str]=Field(default_factory=list);approval_boundaries:list[str]=Field(default_factory=list);failure_handling:str="";status:str=Field(default="draft",pattern="^(draft|active|paused)$")
class ThreadCreateRequest(BaseModel):name:str=Field(min_length=1,max_length=120);participants:list[str]=Field(min_length=1,max_length=30)
class ThreadMessageRequest(BaseModel):message:str=Field(min_length=1,max_length=12000);target_agent_id:str|None=None

def _load(path,default):
    if not path.exists():return default
    try:return json.loads(path.read_text(encoding="utf-8"))
    except Exception:return default
def _save(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding="utf-8")
def _record_local(session_id,user_message,assistant_message,card,agent_type,routed_by):
    add_message(session_id,"user",user_message,{"agent_type":agent_type,"routed_by":routed_by});add_message(session_id,"assistant",assistant_message,{"agent_type":agent_type,"routed_by":routed_by});remember_active_from_card(session_id,card);record_route(routed_by,{"card_type":card.get("type") if isinstance(card,dict) else None});record_event("local_action",card.get("type") if isinstance(card,dict) else routed_by,metadata={"agent_type":agent_type})
def _schedule_due(item,now):
    if item.get("status")!="active":return False
    cadence=str(item.get("cadence","")).lower();hhmm=item.get("time_hhmm") or "09:00"
    try:hour,minute=map(int,hhmm.split(":"))
    except Exception:hour,minute=9,0
    last_raw=item.get("last_fired_at");last=datetime.fromisoformat(last_raw) if last_raw else None
    if cadence.startswith("every "):
        m=re.match(r"every\s+(\d+(?:\.\d+)?)\s*(minutes?|hours?)",cadence)
        if not m:return False
        seconds=float(m.group(1))*(3600 if m.group(2).startswith("hour") else 60);base=last or datetime.fromisoformat(item.get("created_at"));return (now-base).total_seconds()>=seconds
    target=now.replace(hour=hour,minute=minute,second=0,microsecond=0)
    if now<target or (last and last.date()==now.date()):return False
    if cadence=="daily":return True
    if cadence=="weekdays":return now.weekday()<5
    if cadence.startswith("weekly "):
        names={"monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4,"saturday":5,"sunday":6};return now.weekday()==names.get(cadence.split(" ",1)[1],-1)
    return False
def _route_request_actions(message):
    start=r"(?:calculate|calculator|calc|convert|set|start|pause|stop|reset|remind|reminder|show|list|what|whats|tell|give|weather|wheather|forecast|temperature|wiki|wikipedia|look|rss|system|countdown|sha256|checksum|image|inspect|scratchpad|note|save|cancel|time|clock|hey|routine|create|make|assign|change|agent)";normalized=re.sub(r"\s+"," ",message.strip());sentences=re.split(rf"(?<=[.!?])\s+(?={start}\b)",normalized,flags=re.I);results=[];unresolved=[]
    for sentence in sentences:
        if not sentence.strip():continue
        routed=route_local_actions(sentence.strip());results.extend(routed.get("results",[]));unresolved.extend(routed.get("unresolved",[]))
    return {"results":results,"unresolved":unresolved}
def _refresh_timer_cards(results):
    for result in results:
        card=result.get("card")
        if not isinstance(card,dict) or card.get("type")!="timer":continue
        tid=str(card.get("id",''));seconds=float(card.get("duration_seconds") or 0)
        if tid and seconds>0:
            refreshed=local_utils._restart_timer(tid,seconds)
            if refreshed:card.update({"status":refreshed.get("status","running"),"due_at":refreshed.get("due_at"),"duration_seconds":seconds})
def _multi_card(results,extra_message=None):
    items=[{"message":r.get("message",""),"card":r.get("card")} for r in results]
    if extra_message:items.append({"message":extra_message,"card":None})
    return {"type":"multi","items":items}
def _result_summary(results,fallback=""):return "\n".join(str(x.get("message","")).strip() for x in results if str(x.get("message","")).strip()) or fallback
def _observability_command(session_id,message):
    text=" ".join(message.strip().split());lower=text.lower().strip(" .?!");m=re.match(r"^(?:show|open|inspect)?\s*(?:trace|request trace)\s+([a-f0-9]{8,16})$",lower)
    if m:
        try:item=get_trace(m.group(1))
        except KeyError:return {"message":"I couldn't find that trace.","card":None}
        return {"message":f"Trace {item['id']}.","card":trace_card(item,True)}
    if lower in {"trace","show trace","show last trace","last trace","why did you call the api","why did that use the api"}:
        items=recent_traces(session_id,5);current=items[0] if items else None
        if current and current.get("status")=="running" and len(items)>1:current=items[1]
        if not current:return {"message":"No traces yet.","card":None}
        return {"message":f"Trace {current['id']}.","card":trace_card(get_trace(current['id']),True)}
    if lower in {"usage","show usage","cost","show cost","show costs","observability","show observability","request history","show request history"}:return {"message":"Here is recent Agentie usage and routing.","card":summary_card(session_id,20)}
    return None

async def _telegram_route(owner_id:str,agent_id:str,message:str)->dict[str,Any]:
    agent=get_agent(agent_id);agent_type=str((agent or {}).get("base") or agent_id or "general");agent_type=agent_type if agent_type in {"general","research","coding","manager","github"} else "general";session=(str((agent or {}).get("session_prefix") or f"telegram:{owner_id}:{agent_id}:")+"main")
    response=await agent_run(AgentRequest(message=message,agent_type=agent_type,session_id=session),SimpleNamespace(client=SimpleNamespace(host="telegram")))
    return response.model_dump()
@app.on_event("startup")
async def startup_event():apply_all_credentials();start_routine_worker();set_telegram_handler(_telegram_route);await start_telegram_channels()
@app.get("/")
async def chat_ui():
    built=FRONTEND_DIST/"index.html"
    if built.exists():return HTMLResponse(built.read_text(encoding="utf-8"),headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0"})
    if not FRONTEND_FILE.exists():raise HTTPException(404,"Frontend not found.")
    html=FRONTEND_FILE.read_text(encoding="utf-8")+'\n<script src="/cards.js?v=201"></script>\n<script src="/events.js?v=201"></script>\n<script src="/upload.js?v=201"></script>\n<script src="/plugins.js?v=208"></script>\n<script src="/plugin-setup.js?v=207"></script>\n<script src="/telegram-plugin.js?v=201"></script>\n<script src="/plugin-access.js?v=203"></script>\n<script src="/browser-screen.js?v=201"></script>\n<script src="/ui-upgrade.js?v=203"></script>\n<script src="/platform.js?v=211"></script>\n';return HTMLResponse(html,headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0"})
@app.get("/legacy-core.js")
async def legacy_core_js():
    source=FRONTEND_FILE.read_text(encoding="utf-8");match=re.search(r"<script>(.*?)</script>",source,re.S)
    if not match:raise HTTPException(404,"Legacy runtime not found.")
    return Response(match.group(1),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/legacy-app.css")
async def legacy_app_css():
    source=FRONTEND_FILE.read_text(encoding="utf-8");match=re.search(r"<style>(.*?)</style>",source,re.S)
    if not match:raise HTTPException(404,"Legacy styles not found.")
    return Response(match.group(1),media_type="text/css",headers={"Cache-Control":"no-store"})
@app.get("/cards.js")
async def cards_js():return Response(CARDS_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/events.js")
async def events_js():return Response(EVENTS_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/upload.js")
async def upload_js():return Response(UPLOAD_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/plugins.js")
async def plugins_js():return Response(PLUGINS_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/plugin-setup.js")
async def plugin_setup_js():return Response(PLUGIN_SETUP_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/plugin-access.js")
async def plugin_access_js():return Response(PLUGIN_ACCESS_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/telegram-plugin.js")
async def telegram_plugin_js():return Response(TELEGRAM_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/browser-screen.js")
async def browser_screen_js():return Response(BROWSER_SCREEN_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/ui-upgrade.js")
async def ui_upgrade_js():return Response(UI_UPGRADE_JS.read_text(encoding="utf-8")+"\n"+(FRONTEND_DIR/"project_workspace.js").read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/platform.js")
async def platform_js():return Response(PLATFORM_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})

@app.post("/agent-builder/draft")
async def agent_builder_draft(request:AgentBuilderDraftRequest):
    try:return draft_agent_spec(request.description,name=request.name,job=request.job)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
@app.post("/agent-builder/create")
async def agent_builder_create(request:AgentBuilderCreateRequest):
    try:spec=normalize_create_spec(request.model_dump())
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    installed={str(x.get("name") or "").casefold() for x in list_servers()};selected_plugins=[x for x in spec["plugins"] if x.casefold() in installed];connection_needed=[x for x in spec["plugins"] if x.casefold() not in installed];permissions={"delegate":spec["can_delegate"],"shared_company_memory":"read","capability_mode":"explicit","mcp_servers":selected_plugins,"blocked_skills":[],"blocked_mcp_servers":[]}
    try:result=create_agent(spec["name"],spec["role"],"general",purpose=spec["purpose"],manager_id=spec.get("manager_id"),skills=spec["skills"],permissions=permissions,personality=spec["personality"],goal=spec["goal"],responsibilities=spec["responsibilities"],approval_policy=spec["approval_policy"],memory_policy=spec["memory_policy"],runtime_profile="general")
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    agent=result["agent"]
    if result.get("created") and spec.get("manual_instructions"):set_manual_instructions(agent,spec["manual_instructions"])
    return {"created":bool(result.get("created")),"agent":get_agent(agent["id"]) or agent,"connection_needed":connection_needed}
@app.post("/workflow-skills")
async def create_workflow_skill_api(request:WorkflowSkillCreateRequest):
    try:item=create_workflow_skill(**request.model_dump())
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    return skill_card(item)
@app.get("/agent-threads")
async def agent_threads_list():return threads_card(list_threads())
@app.post("/agent-threads")
async def agent_threads_create(request:ThreadCreateRequest):
    try:return thread_card(create_thread(request.name,request.participants))
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
@app.get("/agent-threads/{thread_id}")
async def agent_thread_get(thread_id:str):
    thread=get_thread(thread_id)
    if not thread:raise HTTPException(404,"Agent chat was not found.")
    return thread_card(thread)
@app.post("/agent-threads/{thread_id}/messages")
async def agent_thread_message(thread_id:str,request:ThreadMessageRequest):
    thread=get_thread(thread_id)
    if not thread:raise HTTPException(404,"Agent chat was not found.")
    if request.target_agent_id:
        agent=get_agent(request.target_agent_id)
        if not agent or agent["id"] not in thread.get("participant_ids",[]):raise HTTPException(400,"Target agent is not a participant in this chat.")
        job=create_team_job(request.message,[agent],requested_by="user");start_team_job(job["id"]);post_message(thread["id"],"user",None,"User",f"@{agent['name']} {request.message}",{"team_job_id":job["id"],"to_agent_id":agent["id"]})
    else:post_message(thread["id"],"user",None,"User",request.message)
    return thread_card(get_thread(thread["id"]) or thread)
@app.get("/routines")
async def routines_list(agent_id:str|None=None):return {"items":[x for x in list_routines(agent_id) if x.get("status")!="deleted"]}

@app.get("/plugins/state")
async def plugins_state():
    state=plugin_state();state["plugins"]=list_skills();state["agents"]=list_agents();state["channels"]=[{"id":"telegram","name":"Telegram","description":"Two-way private conversations, proactive updates, routines and approval buttons through your own Telegram bot.","setup":telegram_public_state()}];registered={str(x.get("name") or "").lower() for x in state.get("mcp_servers",[])};state["mcp_servers"]=[{**item,"setup":public_setup_state(str(item.get("name") or ""))} for item in state.get("mcp_servers",[])];state["mcp_presets"]=[{**item,"installed":item["id"].lower() in registered,"setup_state":public_setup_state(item["id"])} for item in mcp_presets()];return state
@app.get("/plugins/telegram")
async def telegram_state(request:Request):return telegram_public_state(request.headers.get("X-Agentie-User") or "local-user")
@app.post("/plugins/telegram")
async def telegram_setup(body:TelegramSetupRequest,request:Request):
    try:return await configure_telegram(request.headers.get("X-Agentie-User") or "local-user",body.token)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    except Exception as exc:raise HTTPException(502,str(exc)) from exc
@app.post("/plugins/telegram/pair")
async def telegram_pair(request:Request):
    try:return create_telegram_pair_code(request.headers.get("X-Agentie-User") or "local-user")
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
@app.delete("/plugins/telegram")
async def telegram_disconnect(request:Request,revoke_token:bool=False):return await disconnect_telegram(request.headers.get("X-Agentie-User") or "local-user",revoke_token=revoke_token)
@app.get("/plugins/setup/{server_name}")
async def plugin_setup_state(server_name:str):
    if not get_server(server_name):raise HTTPException(404,"MCP server is not registered.")
    return public_setup_state(server_name)
@app.post("/plugins/setup/{server_name}")
async def plugin_setup_save(server_name:str,request:PluginSetupUpdate):
    if not get_server(server_name):raise HTTPException(404,"MCP server is not registered.")
    try:state=save_credentials(server_name,request.values)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    if state.get("requires_credentials") and not state.get("configured"):return {"connected":False,"message":"Credentials saved, but required setup fields are still missing.","setup":state}
    if state.get("oauth_supported"):return {"connected":False,"oauth_required":True,"message":"Credentials saved. Connect your account to finish OAuth approval.","setup":state}
    try:await inspect_server(server_name);return {"connected":True,"message":f"Connected to {server_name}.","setup":public_setup_state(server_name)}
    except Exception as exc:error=str(exc)[:700];return {"connected":False,"message":f"Saved the credential, but {server_name} still could not connect.","error":error,"setup":public_setup_state(server_name,error)}
@app.post("/plugins/connect/{server_name}")
async def plugin_connect(server_name:str):
    if not get_server(server_name):raise HTTPException(404,"MCP server is not registered.")
    try:return start_oauth_connection(server_name)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
@app.post("/plugins/test/{server_name}")
async def plugin_test(server_name:str):
    if not get_server(server_name):raise HTTPException(404,"MCP server is not registered.")
    state=public_setup_state(server_name)
    if state.get("requires_credentials") and not state.get("configured"):return {"connected":False,"message":f"{server_name} still needs required setup fields.","setup":state}
    try:await inspect_server(server_name);return {"connected":True,"message":f"Connected to {server_name}.","setup":public_setup_state(server_name)}
    except Exception as exc:error=str(exc)[:700];return {"connected":False,"message":f"{server_name} is not connected yet.","error":error,"setup":public_setup_state(server_name,error)}
@app.delete("/plugins/setup/{server_name}")
async def plugin_setup_clear(server_name:str):
    if not get_server(server_name):raise HTTPException(404,"MCP server is not registered.")
    return {"cleared":True,"setup":clear_credentials(server_name)}
@app.get("/plugins/agent-access/{agent_id}")
async def plugin_agent_access(agent_id:str):
    try:return access_snapshot(agent_id)
    except ValueError as exc:raise HTTPException(404,str(exc)) from exc
@app.post("/plugins/agent-access/{agent_id}")
async def plugin_agent_access_update(agent_id:str,request:AgentAccessUpdate):
    try:
        if request.kind=="skill":set_skill_access(agent_id,request.capability_id,request.mode or "inherit")
        else:set_mcp_access(agent_id,request.capability_id,bool(request.allowed))
        return access_snapshot(agent_id)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
@app.get("/agents/{agent_id}/handoff-chat")
async def agent_handoff_chat(agent_id:str):
    agent=get_agent(agent_id)
    if not agent:raise HTTPException(404,"Agent not found.")
    session=f"{agent['session_prefix']}main";items=[]
    for item in recent_messages(session,limit=50,max_chars=100000):
        metadata=item.get("metadata") or {};route=str(metadata.get("routed_by") or "")
        if route not in {"project_handoff","project_handoff_result"}:continue
        items.append({"role":item.get("role"),"content":item.get("content"),"created_at":item.get("created_at"),"team_job_id":metadata.get("team_job_id"),"project_id":metadata.get("project_id"),"failed":bool(metadata.get("failed"))})
    return {"agent_id":agent["id"],"agent_name":agent["name"],"items":items}
@app.get("/health")
async def health():return {"status":"ok","service":"agentie-v2","version":"1.10.1"}
@app.get("/web-snapshots/{filename}")
async def web_snapshot(filename:str):
    name=Path(filename).name
    if name!=filename or not name.lower().endswith(".png"):raise HTTPException(400,"Invalid snapshot filename.")
    path=SNAPSHOT_DIR/name
    if not path.exists() or not path.is_file():raise HTTPException(404,"Website snapshot not found.")
    return FileResponse(path=str(path),media_type="image/png",headers={"Cache-Control":"no-store, max-age=0"})
@app.get("/browser/live/state")
async def browser_live_state():return get_live_state()
@app.get("/browser/live/frame")
async def browser_live_frame():
    if not LIVE_FRAME_FILE.exists() or not LIVE_FRAME_FILE.is_file():raise HTTPException(404,"No live browser frame yet.")
    return FileResponse(path=str(LIVE_FRAME_FILE),media_type="image/png",headers={"Cache-Control":"no-store, max-age=0"})
@app.post("/browser/live/stop")
async def browser_live_stop():return request_browser_stop()
@app.post("/files/upload")
async def file_upload(file:UploadFile=File(...)):
    try:
        content=await file.read(MAX_FILE_BYTES+1)
        if len(content)>MAX_FILE_BYTES:raise HTTPException(413,"File exceeds the 50 MB local upload limit.")
        card=save_upload(file.filename or "upload.bin",content);return {"message":f"Uploaded {card['name']}.","card":card}
    except HTTPException:raise
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    except Exception as exc:raise HTTPException(500,f"Upload failed: {exc}") from exc
    finally:await file.close()
@app.get("/files/{filename}/download")
async def file_download(filename:str):
    try:path=resolve_upload(filename);return FileResponse(path=str(path),filename=path.name,media_type="application/octet-stream")
    except FileNotFoundError as exc:raise HTTPException(404,"File not found.") from exc
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
@app.get("/files/{filename}/view")
async def file_view(filename:str):
    try:
        path=resolve_upload(filename);mime=mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path=str(path),media_type=mime,headers={"Content-Disposition":f'inline; filename="{path.name}"',"Cache-Control":"no-store"})
    except FileNotFoundError as exc:raise HTTPException(404,"File not found.") from exc
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
@app.post("/files/{filename}/action")
async def file_action(filename:str,request:FileAction):
    try:message,card=run_action(filename,request.action);return {"message":message,"card":card}
    except FileNotFoundError as exc:raise HTTPException(404,"Uploaded file not found.") from exc
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    except Exception as exc:raise HTTPException(500,f"File action failed: {exc}") from exc
@app.post("/files/reason")
async def file_reason(request:AttachmentReasonRequest):
    try:cards,answer=await reason_about_documents(request.question,request.filenames);return {"message":answer,"cards":cards,"routed_by":"attachment_reasoner"}
    except FileNotFoundError as exc:raise HTTPException(404,f"Uploaded file not found: {exc}") from exc
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    except Exception as exc:raise HTTPException(502,f"Attachment reasoning failed: {exc}") from exc
@app.get("/local/events/poll")
async def poll_local_events():
    now=datetime.now().astimezone();events=[];reminders=_load(REMINDERS,[]);changed=False
    for item in reminders:
        if item.get("status")!="scheduled":continue
        try:due=datetime.fromisoformat(item.get("due_at")).astimezone()
        except Exception:continue
        if due<=now:event={"message":f"Reminder: {item.get('text','')}","card":{"type":"reminder",**item}};events.append(event);queue_telegram_proactive(event["message"],event["card"]);repeat=float(item.get("repeat_minutes") or 0);item["due_at"]=(now+timedelta(minutes=repeat)).isoformat(timespec="seconds") if repeat>0 else item.get("due_at");item["status"]="scheduled" if repeat>0 else "delivered";item["last_fired_at"]=now.isoformat(timespec="seconds");changed=True
    if changed:_save(REMINDERS,reminders)
    schedules=_load(SCHEDULES,[]);changed=False
    for item in schedules:
        try:
            if _schedule_due(item,now):event={"message":f"Scheduled reminder: {item.get('text','')}","card":{"type":"schedule",**item}};events.append(event);queue_telegram_proactive(event["message"],event["card"]);item["last_fired_at"]=now.isoformat(timespec="seconds");changed=True
        except Exception:continue
    if changed:_save(SCHEDULES,schedules)
    events.extend(poll_routine_events());events.extend(poll_whatsapp_events());return {"events":events}
@app.post("/agent/run",response_model=AgentResponse)
async def agent_run(request:AgentRequest,http_request:Request):
    trace_id=None;failed=None
    try:
        session_key=request.session_id or f"{http_request.client.host if http_request.client else 'local'}:{request.agent_type}";trace_id=start_trace(session_key,request.agent_type,request.message);access=guard_agent_capability(session_key,request.message)
        if access is not None:message=str(access.get("message",""));card=access.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"capability_permission");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="capability_permission")
        thread=route_thread_command(request.message)
        if thread is not None:message=str(thread.get("message",""));card=thread.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"agent_thread");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="agent_thread")
        mcp=await route_mcp_command(request.message)
        if mcp is not None:mcp=enrich_setup_failure(request.message,mcp) or mcp;message=str(mcp.get("message",""));card=mcp.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"mcp");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="mcp")
        code=route_code_command(request.message)
        if code is not None:message=str(code.get("message",""));card=code.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"local_code");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="local_code")
        obs=_observability_command(session_key,request.message)
        if obs is not None:message=str(obs.get("message",""));card=obs.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"observability");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="observability")
        ref=try_active_reference(session_key,request.message)
        if ref is not None:message=str(ref.get("message",""));card=ref.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"active_reference");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="active_reference")
        office=try_office_request(session_key,request.message)
        if office is not None:message=str(office.get("message",""));card=office.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"local_artifact");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="local_artifact")
        pdf=try_pdf_request(session_key,request.message)
        if pdf is not None:message=str(pdf.get("message",""));card=pdf.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"local_pdf");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="local_pdf")
        browser=await route_browser_request(request.message,session_key)
        if browser is not None:message=str(browser.get("message",""));card=browser.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"local_browser");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="local_browser")
        follow=consume_followup(session_key,request.message);effective=request.message
        if follow:
            if follow.get("cancelled") or not follow.get("command"):message=str(follow.get("message",""));_record_local(session_key,request.message,message,None,request.agent_type,"clarification");return AgentResponse(message=message,result=message,card=None,agent_type=request.agent_type,routed_by="clarification")
            effective=str(follow["command"])
        preflight=await route_capability_preflight(effective,session_key)
        if preflight is not None:preflight=enrich_setup_failure(effective,preflight) or preflight;message=str(preflight.get("message",""));card=preflight.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"capability");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="capability")
        direct_capability=await route_capability_request(effective,request.agent_type)
        if direct_capability is not None:direct_capability=enrich_setup_failure(effective,direct_capability) or direct_capability;message=str(direct_capability.get("message",""));card=direct_capability.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"capability");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="capability")
        routed=_route_request_actions(effective);local_results=routed.get("results",[]);unresolved=routed.get("unresolved",[])
        if not local_results and unresolved:
            handoff=maybe_auto_delegate(effective,session_key)
            if handoff is not None:message=str(handoff.get("message",""));card=handoff.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"agent_handoff");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="agent_handoff")
        capability_remaining=[]
        for clause in unresolved:
            capability=await route_capability_request(clause,request.agent_type)
            if capability is not None:local_results.append(capability)
            else:capability_remaining.append(clause)
        unresolved=capability_remaining;clarification=None;remaining=[]
        for clause in unresolved:
            incomplete=detect_incomplete_intent(session_key,clause)
            if incomplete and clarification is None:clarification=str(incomplete.get("message",""))
            else:remaining.append(clause)
        unresolved=remaining;provider_unresolved=[];blocked=[]
        for clause in unresolved:(provider_unresolved if provider_allowed(clause) else blocked).append(clause)
        unresolved=provider_unresolved
        if blocked and not clarification:clarification=local_fallback_message(blocked[0])
        if local_results and not unresolved:
            _refresh_timer_cards(local_results)
            if clarification:card=_multi_card(local_results,clarification);summary=_result_summary(local_results,clarification);_record_local(session_key,request.message,summary,card,request.agent_type,"clarification");return AgentResponse(message="",result=clarification,card=card,agent_type=request.agent_type,routed_by="clarification")
            if len(local_results)==1:item=local_results[0];message=str(item.get("message",""));card=item.get("card");route="capability" if isinstance(card,dict) and card.get("type")=="mcp_approval" else "local";_record_local(session_key,request.message,message,card,request.agent_type,route);return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by=route)
            card=_multi_card(local_results);summary=_result_summary(local_results);_record_local(session_key,request.message,summary,card,request.agent_type,"local");return AgentResponse(message="",result="",card=card,agent_type=request.agent_type,routed_by="local")
        if not local_results and clarification and not unresolved:_record_local(session_key,request.message,clarification,None,request.agent_type,"clarification");return AgentResponse(message=clarification,result=clarification,card=None,agent_type=request.agent_type,routed_by="clarification")
        if local_results and unresolved:
            record_route("hybrid",{"local_actions":len(local_results),"provider_clauses":len(unresolved)});prompt="Handle only the following unresolved parts of the user's request. Do not repeat or redo other actions.\n\n"+"\n".join(f"- {p}" for p in unresolved)
            try:llm=await run_agent(prompt,request.agent_type,session_key)
            except Exception as exc:llm="I completed the other actions, but I couldn't process: "+"; ".join(unresolved)+f". ({exc})"
            if clarification:llm=(llm+"\n\n"+clarification).strip()
            _refresh_timer_cards(local_results);card=_multi_card(local_results,llm);remember_active_from_card(session_key,card);return AgentResponse(message="",result=llm,card=card,agent_type=request.agent_type,routed_by="hybrid")
        if clarification and not unresolved:_record_local(session_key,request.message,clarification,None,request.agent_type,"clarification");return AgentResponse(message=clarification,result=clarification,card=None,agent_type=request.agent_type,routed_by="clarification")
        if not provider_allowed(effective):message=local_fallback_message(effective);_record_local(session_key,request.message,message,None,request.agent_type,"local_guard");return AgentResponse(message=message,result=message,card=None,agent_type=request.agent_type,routed_by="local_guard")
        record_route("llm",{"agent_type":request.agent_type});result=await run_agent(effective,request.agent_type,session_key);return AgentResponse(message=result,result=result,card=None,agent_type=request.agent_type,routed_by="llm")
    except RuntimeError as exc:failed=str(exc);raise HTTPException(500,str(exc)) from exc
    except Exception as exc:failed=str(exc);raise HTTPException(502,f"Agent run failed: {exc}") from exc
    finally:
        if trace_id:finish_trace(trace_id,"failed" if failed else "completed",failed)
@app.post("/approvals/{approval_id}/resolve")
async def approval_resolve(approval_id:str,decision:ApprovalDecision):
    try:return resolve_approval(approval_id,decision.approved)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
if __name__=="__main__":uvicorn.run("main:app",host="0.0.0.0",port=int(os.getenv("PORT","8000")),reload=False)
