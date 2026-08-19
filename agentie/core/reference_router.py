import json,re
from datetime import datetime,timedelta
from typing import Any
from agentie.core.memory_store import get_context,set_context
from agentie.tools import local_utility_tools as local_utils
from agentie.tools import productivity_tools as productivity

_DURATION_RE=re.compile(r"\b(\d+(?:\.\d+)?)\s*(seconds?|secs?|sec|s|minutes?|mins?|min|m|hours?|hrs?|hr|h)\b",re.I)
_JOB_SIGNAL_RE=re.compile(r"\b(delegate|research|investigate|compare|analy[sz]e|build|implement|debug|refactor|github|repository|report|deep search|multi[- ]?step|parallel)\b",re.I)
_JOBS_RESUMED=False

def _seconds(m):
    v=float(m.group(1));u=m.group(2).lower();return v*3600 if u.startswith('h') else v*60 if u.startswith('m') else v
def _load_reminders():
    try:return json.loads(productivity.REMINDERS.read_text(encoding='utf-8')) if productivity.REMINDERS.exists() else []
    except Exception:return []
def _job_runner_session(s,j,sp):return f"{s}:job:{j}:{sp}"
async def _job_step_runner(instruction,specialist,session_id):
    from agentie.core.runner import run_agent
    active=get_context(session_id,'active_job_id','job');return await run_agent(instruction,specialist,_job_runner_session(session_id,str(active),specialist))
def _ensure_jobs_resumed():
    global _JOBS_RESUMED
    if _JOBS_RESUMED:return
    _JOBS_RESUMED=True
    try:
        from agentie.core.job_engine import resume_unfinished
        from agentie.core.routine_worker import start_routine_worker
        resume_unfinished(_job_step_runner);start_routine_worker()
    except RuntimeError:_JOBS_RESUMED=False
    except Exception:pass
def _looks_like_background_job(message):
    text=re.sub(r"\s+"," ",message.strip());low=text.lower();local_hits=len(re.findall(r"\b(timer|alarm|remind|time|weather|calculate|convert|note|system status|stopwatch|routine)\b",low));complex_hits=len(_JOB_SIGNAL_RE.findall(low))
    if re.search(r"\b(delegate|deep search|run (?:this )?as a job|background job|parallel agents?)\b",low):return True
    if local_hits>=2 and complex_hits==0:return False
    return complex_hits>=2 or (complex_hits>=1 and len(text)>=180)
def remember_active_from_card(session_id,card):
    if not isinstance(card,dict):return
    if card.get('type')=='multi':
        for item in reversed(card.get('items') or []):
            child=item.get('card') if isinstance(item,dict) else None
            if isinstance(child,dict):remember_active_from_card(session_id,child)
            if get_context(session_id,'active_object'):return
        return
    t=str(card.get('type') or '')
    if t in {'timer','alarm','reminder','schedule','uploaded_file','note','task','tasks','job_progress','routine','routines','agent_role','agent_roles'}:
        set_context(session_id,'active_object',{'type':t,'card':card})
        if t=='job_progress' and card.get('id'):set_context(session_id,'active_job_id',str(card['id']))
def _job_command(session_id,message):
    from agentie.core.job_engine import cancel_job,create_job,get_job,job_card,job_events,start_job
    text=re.sub(r"\s+"," ",message.strip());low=text.lower().strip(' .?!');active_id=str(get_context(session_id,'active_job_id','') or '')
    m=re.match(r"^(?:show |check )?(?:job )?(?:status|progress)(?: (?:for|of))?\s*([a-f0-9]{6,12})?$",low)
    if m:
        jid=m.group(1) or active_id
        if not jid:return {'message':'Which job should I check?','card':None,'routed_by':'job'}
        try:j=get_job(jid)
        except KeyError:return {'message':"I couldn't find that job.",'card':None,'routed_by':'job'}
        set_context(session_id,'active_job_id',jid);return {'message':f"Job {jid}: {j['status']}.",'card':job_card(j),'routed_by':'job'}
    m=re.match(r"^(?:cancel|stop)\s+(?:the\s+)?job(?:\s+([a-f0-9]{6,12}))?$",low)
    if m:
        jid=m.group(1) or active_id
        if not jid:return {'message':'Which job should I cancel?','card':None,'routed_by':'job'}
        try:j=cancel_job(jid)
        except KeyError:return {'message':"I couldn't find that job.",'card':None,'routed_by':'job'}
        return {'message':f'Job {jid} cancelled.','card':job_card(j),'routed_by':'job'}
    m=re.match(r"^(?:show )?(?:job )?trace(?:\s+([a-f0-9]{6,12}))?$",low)
    if m:
        jid=m.group(1) or active_id
        if not jid:return {'message':'Which job trace should I show?','card':None,'routed_by':'job'}
        try:events=job_events(jid)
        except Exception:return {'message':"I couldn't read that job trace.",'card':None,'routed_by':'job'}
        return {'message':f'Trace for job {jid}.','card':{'type':'job_trace','id':jid,'events':events},'routed_by':'job'}
    explicit=re.match(r"^(?:delegate|start (?:a )?(?:background )?job(?: to)?|run (?:this )?as a job)\s*[:\-]?\s*(.+)$",text,re.I);goal=explicit.group(1).strip() if explicit else text
    if explicit or _looks_like_background_job(text):
        j=create_job(session_id,goal);set_context(session_id,'active_job_id',j['id']);start_job(j['id'],_job_step_runner);card=job_card(j);set_context(session_id,'active_object',{'type':'job_progress','card':card});return {'message':f"Started job {j['id']} with {j['total_steps']} planned step(s). You can keep chatting while it runs.",'card':card,'routed_by':'job'}
    return None
def try_active_reference(session_id,message):
    _ensure_jobs_resumed();job=_job_command(session_id,message)
    if job is not None:return job
    active=get_context(session_id,'active_object')
    if not isinstance(active,dict):return None
    card=active.get('card') if isinstance(active.get('card'),dict) else {};typ=str(active.get('type') or card.get('type') or '');text=re.sub(r"\s+"," ",message.lower().strip());duration=_DURATION_RE.search(text);change=bool(re.search(r"\b(?:make|change|set|restart|reset|instead|again)\b",text));add=bool(re.search(r"\b(?:add|plus|increase|extend)\b",text));ref=bool(re.search(r"\b(?:it|that|this|timer|alarm|reminder|routine)\b",text))
    if typ in {'timer','alarm'}:
        tid=str(card.get('id') or '')
        if not tid:return None
        if duration and ref and (change or add):
            requested=_seconds(duration)
            if add:
                try:due=datetime.fromisoformat(str(card.get('due_at')));now=datetime.now(due.tzinfo) if due.tzinfo else datetime.now();requested+=max(0.0,(due-now).total_seconds())
                except Exception:requested+=float(card.get('duration_seconds') or 0)
            r=local_utils._restart_timer(tid,requested)
            if not r:return None
            nc=dict(card);nc.update({'type':typ,'id':tid,'status':r.get('status','running'),'duration_seconds':requested,'due_at':r.get('due_at')});set_context(session_id,'active_object',{'type':typ,'card':nc});p=int(requested) if float(requested).is_integer() else round(requested,1);return {'message':f"{'Timer' if typ=='timer' else 'Alarm'} updated to {p} seconds from now.",'card':nc,'routed_by':'active_reference'}
        if ref and re.search(r"\b(?:cancel|stop|dismiss)\b",text):
            with local_utils._TIMER_LOCK:
                item=local_utils._TIMERS.get(tid)
                if not item:return None
                item['status']='cancelled'
            nc=dict(card);nc['status']='cancelled';set_context(session_id,'active_object',{'type':typ,'card':nc});return {'message':f"{'Timer' if typ=='timer' else 'Alarm'} cancelled.",'card':nc,'routed_by':'active_reference'}
    if typ=='reminder':
        rid=str(card.get('id') or '')
        if not rid:return None
        if duration and ref and (change or add):
            sec=_seconds(duration);items=_load_reminders();target=next((x for x in items if str(x.get('id'))==rid),None)
            if target is None:return None
            try:old=datetime.fromisoformat(str(target.get('due_at')));now=datetime.now(old.tzinfo) if old.tzinfo else datetime.now()
            except Exception:now=datetime.now();old=now
            nd=old+timedelta(seconds=sec) if add else now+timedelta(seconds=sec);target['due_at']=nd.isoformat(timespec='seconds');target['status']='scheduled';productivity._save(productivity.REMINDERS,items);nc={'type':'reminder',**target};set_context(session_id,'active_object',{'type':'reminder','card':nc});return {'message':f"Updated that reminder for {nd.strftime('%H:%M:%S')}.",'card':nc,'routed_by':'active_reference'}
        if ref and re.search(r"\b(?:cancel|delete|remove|dismiss)\b",text):
            items=_load_reminders();target=next((x for x in items if str(x.get('id'))==rid),None)
            if target is None:return None
            target['status']='cancelled';productivity._save(productivity.REMINDERS,items);nc={'type':'reminder',**target};set_context(session_id,'active_object',{'type':'reminder','card':nc});return {'message':'Reminder cancelled.','card':nc,'routed_by':'active_reference'}
    if typ=='routine' and ref:
        from agentie.core.routine_engine import _parse_trigger,update_routine
        rid=str(card.get('id') or '')
        if not rid:return None
        try:
            if re.search(r"\b(?:pause|disable)\b",text):item=update_routine(rid,status='paused')
            elif re.search(r"\b(?:resume|enable)\b",text):item=update_routine(rid,status='active')
            elif re.search(r"\b(?:delete|remove)\b",text):item=update_routine(rid,status='deleted')
            else:
                parsed=_parse_trigger(message)
                if not parsed:return None
                item=update_routine(rid,trigger=parsed[0])
        except (KeyError,ValueError) as exc:return {'message':str(exc),'card':None,'routed_by':'active_reference'}
        nc={'type':'routine',**item};set_context(session_id,'active_object',{'type':'routine','card':nc});return {'message':f"Updated routine “{item['name']}”.",'card':nc,'routed_by':'active_reference'}
    return None
