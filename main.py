import json,os,re
from datetime import datetime,timedelta
from pathlib import Path
from typing import Any
import uvicorn
from fastapi import FastAPI,File,HTTPException,Request,UploadFile
from fastapi.responses import FileResponse,HTMLResponse,Response
from pydantic import BaseModel,Field
from agentie.core.conversation_loop import consume_followup,detect_incomplete_intent
from agentie.core.file_service import MAX_FILE_BYTES,resolve_upload,run_action,save_upload
from agentie.core.local_router import route_local_actions
from agentie.core.memory_store import add_message
from agentie.core.office_artifacts import try_office_request
from agentie.core.pdf_service import try_pdf_request
from agentie.core.provider_gate import local_fallback_message,provider_allowed
from agentie.core.reference_router import remember_active_from_card,try_active_reference
from agentie.core.routine_worker import poll_routine_events,start_routine_worker
from agentie.core.runner import run_agent
from agentie.tools import local_utility_tools as local_utils
from agentie.tools.approval_tools import resolve_approval
from agentie.tools.advanced_utility_tools import SCHEDULES
from agentie.tools.productivity_tools import REMINDERS

app=FastAPI(title="Agentie API",version="1.6.0",description="Local-first Agentie runtime with memory, routines, dynamic roles, deep research, jobs, RAG, skills and local artifact generation")
FRONTEND_DIR=Path(__file__).parent/"frontend";FRONTEND_FILE=FRONTEND_DIR/"index.html";CARDS_JS=FRONTEND_DIR/"cards.js";EVENTS_JS=FRONTEND_DIR/"events.js";UPLOAD_JS=FRONTEND_DIR/"upload.js"
class AgentRequest(BaseModel):
    message:str=Field(min_length=1,max_length=20_000);agent_type:str=Field(default="general",pattern="^(general|research|coding|manager|github)$");session_id:str|None=Field(default=None,max_length=200)
class AgentResponse(BaseModel):
    message:str;result:str;card:dict[str,Any]|None=None;agent_type:str;routed_by:str
class ApprovalDecision(BaseModel):approved:bool
class FileAction(BaseModel):action:str=Field(pattern="^(inspect|checksum|extract|text|preview)$")

def _load(path,default):
    if not path.exists():return default
    try:return json.loads(path.read_text(encoding="utf-8"))
    except Exception:return default
def _save(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding="utf-8")
def _record_local(session_id,user_message,assistant_message,card,agent_type,routed_by):
    add_message(session_id,"user",user_message,{"agent_type":agent_type,"routed_by":routed_by});add_message(session_id,"assistant",assistant_message,{"agent_type":agent_type,"routed_by":routed_by});remember_active_from_card(session_id,card)
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

@app.on_event("startup")
async def startup_event():start_routine_worker()
@app.get("/")
async def chat_ui():
    if not FRONTEND_FILE.exists():raise HTTPException(404,"Frontend not found.")
    html=FRONTEND_FILE.read_text(encoding="utf-8")+'\n<script src="/cards.js?v=160"></script>\n<script src="/events.js?v=160"></script>\n<script src="/upload.js?v=160"></script>\n';return HTMLResponse(html,headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0"})
@app.get("/cards.js")
async def cards_js():return Response(CARDS_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/events.js")
async def events_js():return Response(EVENTS_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/upload.js")
async def upload_js():return Response(UPLOAD_JS.read_text(encoding="utf-8"),media_type="application/javascript",headers={"Cache-Control":"no-store"})
@app.get("/health")
async def health():return {"status":"ok","service":"agentie-v2","version":"1.6.0"}
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
    try:
        path=resolve_upload(filename);return FileResponse(path=str(path),filename=path.name,media_type="application/octet-stream")
    except FileNotFoundError as exc:raise HTTPException(404,"File not found.") from exc
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
@app.post("/files/{filename}/action")
async def file_action(filename:str,request:FileAction):
    try:message,card=run_action(filename,request.action);return {"message":message,"card":card}
    except FileNotFoundError as exc:raise HTTPException(404,"Uploaded file not found.") from exc
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    except Exception as exc:raise HTTPException(500,f"File action failed: {exc}") from exc
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
    try:
        session_key=request.session_id or f"{http_request.client.host if http_request.client else 'local'}:{request.agent_type}"
        ref=try_active_reference(session_key,request.message)
        if ref is not None:
            message=str(ref.get("message",""));card=ref.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"active_reference");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="active_reference")
        office=try_office_request(session_key,request.message)
        if office is not None:
            message=str(office.get("message",""));card=office.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"local_artifact");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="local_artifact")
        pdf=try_pdf_request(session_key,request.message)
        if pdf is not None:
            message=str(pdf.get("message",""));card=pdf.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"local_pdf");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="local_pdf")
        follow=consume_followup(session_key,request.message);effective=request.message
        if follow:
            if follow.get("cancelled") or not follow.get("command"):
                message=str(follow.get("message",""));_record_local(session_key,request.message,message,None,request.agent_type,"clarification");return AgentResponse(message=message,result=message,card=None,agent_type=request.agent_type,routed_by="clarification")
            effective=str(follow["command"])
        routed=_route_request_actions(effective);local_results=routed.get("results",[]);unresolved=routed.get("unresolved",[]);clarification=None;remaining=[]
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
                item=local_results[0];message=str(item.get("message",""));card=item.get("card");_record_local(session_key,request.message,message,card,request.agent_type,"local");return AgentResponse(message=message,result=message,card=card,agent_type=request.agent_type,routed_by="local")
            card=_multi_card(local_results);summary=_result_summary(local_results);_record_local(session_key,request.message,summary,card,request.agent_type,"local");return AgentResponse(message="",result="",card=card,agent_type=request.agent_type,routed_by="local")
        if not local_results and clarification and not unresolved:
            _record_local(session_key,request.message,clarification,None,request.agent_type,"clarification");return AgentResponse(message=clarification,result=clarification,card=None,agent_type=request.agent_type,routed_by="clarification")
        if local_results and unresolved:
            prompt="Handle only the following unresolved parts of the user's request. Do not repeat or redo other actions.\n\n"+"\n".join(f"- {p}" for p in unresolved)
            try:llm=await run_agent(prompt,request.agent_type,session_key)
            except Exception as exc:llm="I completed the other actions, but I couldn't process: "+"; ".join(unresolved)+f". ({exc})"
            if clarification:llm=(llm+"\n\n"+clarification).strip()
            _refresh_timer_cards(local_results);card=_multi_card(local_results,llm);remember_active_from_card(session_key,card);return AgentResponse(message="",result=llm,card=card,agent_type=request.agent_type,routed_by="hybrid")
        if clarification and not unresolved:
            _record_local(session_key,request.message,clarification,None,request.agent_type,"clarification");return AgentResponse(message=clarification,result=clarification,card=None,agent_type=request.agent_type,routed_by="clarification")
        if not provider_allowed(effective):
            message=local_fallback_message(effective);_record_local(session_key,request.message,message,None,request.agent_type,"local_guard");return AgentResponse(message=message,result=message,card=None,agent_type=request.agent_type,routed_by="local_guard")
        result=await run_agent(effective,request.agent_type,session_key);return AgentResponse(message=result,result=result,card=None,agent_type=request.agent_type,routed_by="llm")
    except RuntimeError as exc:raise HTTPException(500,str(exc)) from exc
    except Exception as exc:raise HTTPException(502,f"Agent run failed: {exc}") from exc
@app.post("/approvals/{approval_id}/resolve")
async def approval_resolve(approval_id:str,decision:ApprovalDecision):
    try:return resolve_approval(approval_id,decision.approved)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
if __name__=="__main__":uvicorn.run("main:app",host="0.0.0.0",port=int(os.getenv("PORT","8000")),reload=False)
