import json,os,re
from datetime import datetime,timedelta
from pathlib import Path
from typing import Any
import uvicorn
from fastapi import FastAPI,File,HTTPException,Request,UploadFile
from fastapi.responses import FileResponse,HTMLResponse,Response
from pydantic import BaseModel,Field
from agentie.core.attachment_reasoner import reason_about_documents
from agentie.core.browser_monitor import LIVE_FRAME_FILE,SNAPSHOT_DIR,get_live_state,request_browser_stop,route_browser_request
from agentie.core.capability_preflight import route_capability_preflight
from agentie.core.capability_router import route_capability_request
from agentie.core.code_execution import route_code_command
from agentie.core.conversation_loop import consume_followup,detect_incomplete_intent
from agentie.core.file_service import MAX_FILE_BYTES,resolve_upload,run_action,save_upload
from agentie.core.local_router import route_local_actions
from agentie.core.mcp_catalog import presets as mcp_presets
from agentie.core.mcp_client import plugin_state,route_mcp_command
from agentie.core.memory_store import add_message
from agentie.core.observability import finish_trace,get_trace,record_event,record_route,recent_traces,start_trace,summary_card,trace_card
from agentie.core.office_artifacts import try_office_request
from agentie.core.pdf_service import try_pdf_request
from agentie.core.provider_gate import local_fallback_message,provider_allowed
from agentie.core.reference_router import remember_active_from_card,try_active_reference
from agentie.core.routine_worker import poll_routine_events,start_routine_worker
from agentie.core.runner import run_agent
from agentie.core.skill_registry import list_skills
from agentie.core.specialty_router import maybe_auto_delegate
from agentie.tools import local_utility_tools as local_utils
from agentie.tools.approval_tools import resolve_approval
from agentie.tools.advanced_utility_tools import SCHEDULES
from agentie.tools.productivity_tools import REMINDERS

app=FastAPI(title="Agentie API",version="1.10.1",description="Local-first Agentie runtime with observability, cost tracking, memory, routines, jobs, RAG, browser monitoring, MCP, plugins, skills and local artifact generation")
FRONTEND_DIR=Path(__file__).parent/"frontend";FRONTEND_FILE=FRONTEND_DIR/"index.html";CARDS_JS=FRONTEND_DIR/"cards.js";EVENTS_JS=FRONTEND_DIR/"events.js";UPLOAD_JS=FRONTEND_DIR/"upload.js";PLUGINS_JS=FRONTEND_DIR/"plugins.js";BROWSER_SCREEN_JS=FRONTEND_DIR/"browser_screen.js";UI_UPGRADE_JS=FRONTEND_DIR/"ui_upgrade.js"
class AgentRequest(BaseModel):
    message:str=Field(min_length=1,max_length=20_000);agent_type:str=Field(default="general",pattern="^(general|research|coding|manager|github)$");session_id:str|None=Field(default=None,max_length=200)
class AgentResponse(BaseModel):
    message:str;result:str;card:dict[str,Any]|None=None;agent_type:str;routed_by:str
class AttachmentReasonRequest(BaseModel):
    question:str=Field(min_length=1,max_length=12_000);filenames:list[str]=Field(min_length=1,max_length=8)
class ApprovalDecision(BaseModel):approved:bool
class FileAction(BaseModel):action:str=Field(pattern="^(inspect|checksum|extract|text|preview)$")

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
    start=r"(?:calculate|calculator|calc|convert|set|start|pause|stop|reset|remind|reminder|show|list|what|whats|tell|give|weather|wheather|forecast|temperature|wiki|wikipedia|look|rss|system|countdown|sha256|checksum|image|inspect|scratchpad|note|save|cancel|time|clock|hey|routine|create|make|assign|change|agent)"
    normalized=re.sub(r"\s+"," ",message.strip());sentences=re.split(rf"(?<=[.!?])\s+(?={start}\b)",normalized,flags=re.I);results=[];unresolved=[]
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
    text=" ".join(message.strip().split());lower=text.lower().strip(" .?!")
    m=re.match(r"^(?:show|open|inspect)?\s*(?:trace|request trace)\s+([a-f0-9]{8,16})$",lower)
    if m:
        try:item=get_trace(m.group(1))
        except KeyError:return {"message":"I couldn't find that trace.","card":None}
        return {"message":f"Trace {item['id']}.","card":trace_card(item,True)}
    if lower in {"trace","show trace","show last trace","last trace","why did you call the api","why did that use the api"}:
        items=recent_traces(session_id,5);current=items[0] if items else None
        if current and current.get("status")=="running" and len(items)>1:current=items[1]
        if not current:return {"message":"No traces yet.","card":None}
        return {"message":f"Trace {current['id']}.","card":trace_card(get_trace(current['id']),True)}
    if lower in {"usage","show usage","cost","show cost","show costs","observability","show observability","request history","show request history"}:
        return {"message":"Here is recent Agentie usage and routing.","card":summary_card(session_id,20)}
    return None

@app.on_event("startup")
async def startup_event():start_routine_worker()
@app.get("/")
async def chat_ui():
    if not FRONTEND_FILE.exists():raise HTTPException(404,"Frontend not found.")
    html=FRONTEND_FILE.read_text(encoding="utf-8")+'\n<script src="/cards.js?v=201"></script>\n<script src="/events.js?v=201"></script>\n<script src="/upload.js?v=201"></script>\n<script src="/plugins.js?v=201"></script>\n<script src="/browser-screen.js?v=201"></script>\n<script src="/ui-upgrade.js?v=202"></script>\n';return HTMLResponse(html,headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0"})
@app.get("/cards.js")
async def cards_js():return Response(CARDS_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/events.js")
async def events_js():return Response(EVENTS_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/upload.js")
async def upload_js():return Response(UPLOAD_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/plugins.js")
async def plugins_js():return Response(PLUGINS_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/browser-screen.js")
async def browser_screen_js():return Response(BROWSER_SCREEN_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/ui-upgrade.js")
async def ui_upgrade_js():return Response(UI_UPGRADE_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/plugins/state")
async def plugins_state():
    state=plugin_state();state["plugins"]=list_skills();registered={str(x.get("name") or "").lower() for x in state.get("mcp_servers",[])};state["mcp_presets"]=[{**item,"installed":item["id"].lower() in registered} for item in mcp_presets()];return state
@app.get("/health")
async def health():return {"status":"ok","service":"agentie-v2","version":"1.10.1"}
@app.get("/web-snapshots/{filename}")
async def web_snapshot(filename:str):
    name=Path(filename).name
    if name!=filename or not name.lower().endswith(".png"):raise HTTPException(400,"Invalid snapshot filename.")
    path=SNAPSHOT_DIR/name
    if not path.exists() or not path.is_file():raise HTTPException(404,"Website snapshot not found.")
    return FileResponse(path=str(path),media_type="image/png",headers={"Cache-Control":"no-store"})
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
@app.post("/files/{filename}/action")
async def file_action(filename:str,request:FileAction):
    try:message,card=run_action(filename,request.action);return {"message":message,"card":card}
    except FileNotFoundError as exc:raise HTTPException(404,"Uploaded file not found.") from exc
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    except Exception as exc:raise HTTPException(500,f"File action failed: {exc}") from exc
@app.post("/files/reason")
async def file_reason(request:AttachmentReasonRequest):
    try:
        cards,answer=await reason_about_documents(request.question,request.filenames)
        return {"message":answer,"cards":cards,"routed_by":"attachment_reasoner"}
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
        if due<=now:
            events.append({"message":f"Reminder: {item.get('text','')}","card":{"type":"reminder",**item}});repeat=float(item.get("repeat_minutes") or 0);item["due_at"]=(now+timedelta(minutes=repeat)).isoformat(timespec="seconds") if repeat>0 else item.get("due_at");item["status"]="scheduled" if repeat>0 else "delivered";item["last_fired_at"]=now.isoformat(timespec="seconds");changed=True
    if changed:_save(REMINDERS,reminders)
    schedules=_load(SCHEDULES,[]);changed=False
    for item in schedules:
        try:
            if _schedule_due(item,now):events.append({"message":f"Scheduled reminder: {item.get('text','')}","card":{"type":"schedule",**item}});item["last_fired_at"]=now.isoformat(timespec="seconds");changed=True
        except Exception:continue
    if changed:_save(SCHEDULES,schedules)
    events.extend(poll_routine_events());return {"events":events}
@app.post("/agent/run",response_model=AgentResponse)
async def agent_run(request:AgentRequest,http_request:Request):
    trace_id=None;failed=None
    try:
        session_key=request.session_id or f"{http_request.client.host if http_request.client else 'local'}:{request.agent_type}"
        trace_id=start_trace(session_key,request.agent_type,request.message)
        mcp=await route_mcp_command(request.message)
        if mcp is not None:
            message=str(mcp.get("message",""));card=mcp.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"mcp");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="mcp")
        code=route_code_command(request.message)
        if code is not None:
            message=str(code.get("message",""));card=code.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"local_code");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="local_code")
        obs=_observability_command(session_key,request.message)
        if obs is not None:
            message=str(obs.get("message",""));card=obs.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"observability");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="observability")
        ref=try_active_reference(session_key,request.message)
        if ref is not None:
            message=str(ref.get("message",""));card=ref.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"active_reference");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="active_reference")
        office=try_office_request(session_key,request.message)
        if office is not None:
            message=str(office.get("message",""));card=office.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"local_artifact");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="local_artifact")
        pdf=try_pdf_request(session_key,request.message)
        if pdf is not None:
            message=str(pdf.get("message",""));card=pdf.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"local_pdf");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="local_pdf")
        browser=await route_browser_request(request.message)
        if browser is not None:
            message=str(browser.get("message",""));card=browser.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"local_browser");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="local_browser")
        follow=consume_followup(session_key,request.message);effective=request.message
        if follow:
            if follow.get("cancelled") or not follow.get("command"):
                message=str(follow.get("message",""));_record_local(session_key,request.message,message,None,request.agent_type,"clarification");return AgentResponse(message=message,result=message,card=None,agent_type=request.agent_type,routed_by="clarification")
            effective=str(follow["command"])
        preflight=await route_capability_preflight(effective)
        if preflight is not None:
            message=str(preflight.get("message",""));card=preflight.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"capability");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="capability")
        routed=_route_request_actions(effective);local_results=routed.get("results",[]);unresolved=routed.get("unresolved",[])
        if not local_results and unresolved:
            handoff=maybe_auto_delegate(effective,session_key)
            if handoff is not None:
                message=str(handoff.get("message",""));card=handoff.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"agent_handoff");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="agent_handoff")
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
            if clarification:
                card=_multi_card(local_results,clarification);summary=_result_summary(local_results,clarification);_record_local(session_key,request.message,summary,card,request.agent_type,"clarification");return AgentResponse(message="",result=clarification,card=card,agent_type=request.agent_type,routed_by="clarification")
            if len(local_results)==1:
                item=local_results[0];message=str(item.get("message",""));card=item.get("card");route="capability" if isinstance(card,dict) and card.get("type")=="mcp_approval" else "local";_record_local(session_key,request.message,message,card,request.agent_type,route);return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by=route)
            card=_multi_card(local_results);summary=_result_summary(local_results);_record_local(session_key,request.message,summary,card,request.agent_type,"local");return AgentResponse(message="",result="",card=card,agent_type=request.agent_type,routed_by="local")
        if not local_results and clarification and not unresolved:
            _record_local(session_key,request.message,clarification,None,request.agent_type,"clarification");return AgentResponse(message=clarification,result=clarification,card=None,agent_type=request.agent_type,routed_by="clarification")
        if local_results and unresolved:
            record_route("hybrid",{"local_actions":len(local_results),"provider_clauses":len(unresolved)})
            prompt="Handle only the following unresolved parts of the user's request. Do not repeat or redo other actions.\n\n"+"\n".join(f"- {p}" for p in unresolved)
            try:llm=await run_agent(prompt,request.agent_type,session_key)
            except Exception as exc:llm="I completed the other actions, but I couldn't process: "+"; ".join(unresolved)+f". ({exc})"
            if clarification:llm=(llm+"\n\n"+clarification).strip()
            _refresh_timer_cards(local_results);card=_multi_card(local_results,llm);remember_active_from_card(session_key,card);return AgentResponse(message="",result=llm,card=card,agent_type=request.agent_type,routed_by="hybrid")
        if clarification and not unresolved:
            _record_local(session_key,request.message,clarification,None,request.agent_type,"clarification");return AgentResponse(message=clarification,result=clarification,card=None,agent_type=request.agent_type,routed_by="clarification")
        if not provider_allowed(effective):
            message=local_fallback_message(effective);_record_local(session_key,request.message,message,None,request.agent_type,"local_guard");return AgentResponse(message=message,result=message,card=None,agent_type=request.agent_type,routed_by="local_guard")
        record_route("llm",{"agent_type":request.agent_type});result=await run_agent(effective,request.agent_type,session_key);return AgentResponse(message=result,result=result,card=None,agent_type=request.agent_type,routed_by="llm")
    except RuntimeError as exc:
        failed=str(exc);raise HTTPException(500,str(exc)) from exc
    except Exception as exc:
        failed=str(exc);raise HTTPException(502,f"Agent run failed: {exc}") from exc
    finally:
        if trace_id:finish_trace(trace_id,"failed" if failed else "completed",failed)
@app.post("/approvals/{approval_id}/resolve")
async def approval_resolve(approval_id:str,decision:ApprovalDecision):
    try:return resolve_approval(approval_id,decision.approved)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
if __name__=="__main__":uvicorn.run("main:app",host="0.0.0.0",port=int(os.getenv("PORT","8000")),reload=False)