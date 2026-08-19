import json,re,uuid
from datetime import datetime,timedelta
from typing import Any
from agentie.core.memory_store import get_context,set_context
from agentie.tools import local_utility_tools as local_utils
from agentie.tools import productivity_tools as productivity

_DURATION_RE=re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:-|\s)?\s*(seconds?|secs?|sec|s|minutes?|mins?|min|m|hours?|hrs?|hr|h)\b",re.I)
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

def _direct_role_command(message):
    try:
        from agentie.core.role_store import route_role_command
        return route_role_command(message)
    except Exception:return None

def _direct_timer_create(message):
    """Handle explicit timer creation before any stale active reminder can see the request."""
    text=' '.join(message.strip().split())
    patterns=[
        re.compile(r"^(?:please\s+)?(?:set|start|make|give me)\s+(?:a\s+)?timer\s+(?:for\s+)?(\d+(?:\.\d+)?)\s*(seconds?|secs?|sec|s|minutes?|mins?|min|m|hours?|hrs?|hr|h)(?:\s+(?:to|for|because|so i can|so that i can)\s+(.+))?$",re.I),
        re.compile(r"^(?:please\s+)?(?:set|start|make|give me)\s+(?:a\s+)?(\d+(?:\.\d+)?)\s*[- ]?\s*(seconds?|secs?|sec|s|minutes?|mins?|min|m|hours?|hrs?|hr|h)\s+timer(?:\s+(?:to|for|because|so i can|so that i can)\s+(.+))?$",re.I),
    ]
    m=next((p.match(text) for p in patterns if p.match(text)),None)
    if not m:return None
    value=float(m.group(1));unit=m.group(2).lower();reason=(m.group(3) or '').strip(' .?!"“”')
    sec=value*(3600 if unit.startswith('h') else 60 if unit.startswith('m') else 1)
    if sec<=0 or sec>7*24*3600:return {'message':'Timer must be between 1 second and 7 days.','card':None,'routed_by':'timer'}
    item=local_utils._create_timer(sec,reason or 'Timer','timer');card={'type':'timer','id':item['id'],'status':item['status'],'duration_seconds':sec,'due_at':item['due_at']}
    if reason:card['reason']=reason
    pretty=int(sec) if float(sec).is_integer() else round(sec,1)
    return {'message':f"Timer set for {pretty} seconds"+(f" — {reason}." if reason else '.'),'card':card,'routed_by':'timer'}

def _clean_memory_words(text):
    stop={'what','is','was','were','the','a','an','my','i','did','do','you','me','tell','told','remember','recall','earlier','important','detail','details','name','chose','choose','call','called','for','about','again','please'}
    return {w for w in re.findall(r"[a-z0-9][a-z0-9_-]*",text.lower()) if w not in stop}

def _best_saved_memory(query):
    from agentie.core.memory_store import get_memory,list_memories,search_memories
    q=query.strip(' .?!"“”');exact=get_memory('user',q)
    if exact is not None:return {'key':q,'value':exact,'score':1.0}
    qwords=_clean_memory_words(q);best=None
    for item in list_memories('user',100):
        key=str(item.get('key',''));value=str(item.get('value',''));words=_clean_memory_words(key+' '+value);overlap=len(qwords & words)/max(1,len(qwords))
        if q.lower() in key.lower() or key.lower() in q.lower():overlap=max(overlap,.92)
        candidate={'key':key,'value':value,'score':overlap}
        if best is None or candidate['score']>best['score']:best=candidate
    if best and best['score']>=.45:return best
    try:result=search_memories(q,scope='user',limit=8)
    except Exception:return best if best and best['score']>=.25 else None
    memory_hits=[h for h in result.get('hits',[]) if h.get('kind')=='memory']
    if not memory_hits:return best if best and best['score']>=.25 else None
    top=memory_hits[0];text=str(top.get('text',''));key,value=text.split(': ',1) if ': ' in text else ('memory',text)
    return {'key':key,'value':value,'score':float(top.get('score') or 0),'backend':result.get('backend')}

def _direct_memory_query(message):
    text=' '.join(message.strip().split());low=text.lower().strip(' .?!')
    if re.match(r"^(?:please\s+)?remember\b",low):return None
    query=None;patterns=[r"^(?:what(?:'s| is| was)|tell me)\s+my\s+(.+)$",r"^what did i (?:call|name)\s+(?:my|the)\s+(.+)$",r"^what was the name i (?:chose|choose|picked|gave) for (?:my|the)\s+(.+)$",r"^what (?:important )?(?:project )?detail did i tell you (?:earlier|before)$",r"^what (?:important )?project detail did i (?:tell|give) you.*$",r"^what do you remember about (.+)$",r"^(?:search|check|look in) (?:your )?memory (?:for|about) (.+)$"]
    for i,p in enumerate(patterns):
        m=re.match(p,low,re.I)
        if m:query='project' if i in {3,4} else m.group(1).strip();break
    if query is None:
        if re.search(r"\b(?:memory|told you earlier|told you before|said earlier|said before)\b",low):query=low
        else:return None
    aliases=['project codename','project name','project'] if query in {'project','project name'} else ([query,'project codename'] if 'codename' in query else [query]);best=None
    for q in aliases:
        hit=_best_saved_memory(q)
        if hit and (best is None or hit.get('score',0)>best.get('score',0)):best=hit
    if not best:return {'message':"I couldn't find a relevant saved memory.",'card':{'type':'semantic_memory','query':query,'hits':[]},'routed_by':'memory'}
    return {'message':f"I remember {best['key']}: {best['value']}",'card':{'type':'memory','key':best['key'],'value':best['value'],'scope':'user'},'routed_by':'memory'}

def _direct_reminder_create(message):
    text=' '.join(message.strip().split());patterns=[re.compile(r"^(?:please\s+)?remind\s+me\s+in\s+(\d+(?:\.\d+)?)\s*(seconds?|secs?|sec|s|minutes?|mins?|min|m|hours?|hrs?|hr|h)\s+(?:to\s+)?(.+)$",re.I),re.compile(r"^(?:please\s+)?remind\s+me\s+(?:to\s+)?(.+?)\s+in\s+(\d+(?:\.\d+)?)\s*(seconds?|secs?|sec|s|minutes?|mins?|min|m|hours?|hrs?|hr|h)$",re.I)]
    m=patterns[0].match(text)
    if m:value=float(m.group(1));unit=m.group(2);reminder_text=m.group(3)
    else:
        m=patterns[1].match(text)
        if not m:return None
        reminder_text=m.group(1);value=float(m.group(2));unit=m.group(3)
    sec=value*(3600 if unit.lower().startswith('h') else 60 if unit.lower().startswith('m') else 1)
    if sec<=0:return {'message':'Reminder duration must be greater than zero.','card':None,'routed_by':'reminder'}
    reminder_text=reminder_text.strip(' .?!"“”')
    if not reminder_text:return {'message':'What should I remind you about?','card':None,'routed_by':'reminder'}
    items=_load_reminders();now=datetime.now().astimezone();item={'id':uuid.uuid4().hex[:8],'text':reminder_text,'status':'scheduled','created_at':now.isoformat(timespec='seconds'),'due_at':(now+timedelta(seconds=sec)).isoformat(timespec='seconds'),'repeat_minutes':0};items.append(item);productivity._save(productivity.REMINDERS,items);card={'type':'reminder',**item}
    return {'message':f"Reminder set for {value:g} {unit.lower()} from now — {reminder_text}.",'card':card,'routed_by':'reminder'}

def _looks_like_background_job(message):
    text=re.sub(r"\s+"," ",message.strip());low=text.lower();local_hits=len(re.findall(r"\b(timer|alarm|remind|reminder|time|weather|calculate|convert|note|system status|stopwatch|routine)\b",low));complex_hits=len(_JOB_SIGNAL_RE.findall(low))
    if re.search(r"\b(delegate|deep search|run (?:this )?as a job|background job|parallel agents?)\b",low):return True
    # A compound utility request is never auto-promoted to a background job merely because
    # one local clause contains words such as "build" or "report".
    if local_hits>=2:return False
    return complex_hits>=2 or (complex_hits>=1 and len(text)>=180)

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

def remember_active_from_card(session_id,card):
    if not isinstance(card,dict):return
    if card.get('type')=='multi':
        # Last meaningful action becomes the conversational referent.
        for item in reversed(card.get('items') or []):
            child=item.get('card') if isinstance(item,dict) else None
            if isinstance(child,dict):remember_active_from_card(session_id,child);return
        return
    t=str(card.get('type') or '')
    if t in {'timer','alarm','reminder','schedule','uploaded_file','note','task','tasks','job_progress','routine','routines','agent_role','agent_roles','memory'}:
        set_context(session_id,'active_object',{'type':t,'card':card})
        if t=='job_progress' and card.get('id'):set_context(session_id,'active_job_id',str(card['id']))

def try_active_reference(session_id,message):
    _ensure_jobs_resumed();text_raw=' '.join(message.strip().split());low_raw=text_raw.lower().strip(' .?!')
    # Explicit new objects always outrank stale conversational context.
    timer=_direct_timer_create(text_raw)
    if timer is not None:return timer
    role=_direct_role_command(text_raw)
    if role is not None:role['routed_by']='role';return role
    reminder=_direct_reminder_create(text_raw)
    if reminder is not None:return reminder
    memory=_direct_memory_query(text_raw)
    if memory is not None:return memory
    # Explicit job commands/status commands may run before reference resolution; heuristic jobs wait.
    if re.match(r"^(?:delegate|start (?:a )?(?:background )?job|run (?:this )?as a job|(?:show|check )?(?:job )?(?:status|progress)|(?:cancel|stop)\s+(?:the\s+)?job|(?:show )?(?:job )?trace)\b",low_raw,re.I):
        job=_job_command(session_id,text_raw)
        if job is not None:return job
    active=get_context(session_id,'active_object')
    if isinstance(active,dict):
        card=active.get('card') if isinstance(active.get('card'),dict) else {};typ=str(active.get('type') or card.get('type') or '');text=low_raw;duration=_DURATION_RE.search(text);change=bool(re.search(r"\b(?:make|change|set|restart|reset|instead|again)\b",text));add=bool(re.search(r"\b(?:add|plus|increase|extend)\b",text));ref=bool(re.search(r"\b(?:it|that|this|timer|alarm|reminder|routine)\b",text))
        # Reference mutation is intentionally limited to short follow-ups. Long compound commands
        # must go through the normal local router instead of mutating whichever card happened to be active.
        followup_like=len(text.split())<=14 and not re.search(r"\b(?:set|start|create|make)\s+(?:a\s+)?(?:timer|alarm|reminder|routine)\b|\bremind\s+me\b",text)
        if followup_like and typ in {'timer','alarm'}:
            tid=str(card.get('id') or '')
            if tid and duration and ref and (change or add):
                requested=_seconds(duration)+(float(card.get('duration_seconds') or 0) if add else 0);r=local_utils._restart_timer(tid,requested)
                if r:
                    nc=dict(card);nc.update({'type':typ,'id':tid,'status':r.get('status','running'),'duration_seconds':requested,'due_at':r.get('due_at')});set_context(session_id,'active_object',{'type':typ,'card':nc});p=int(requested) if float(requested).is_integer() else round(requested,1);return {'message':f"{'Timer' if typ=='timer' else 'Alarm'} updated to {p} seconds.",'card':nc,'routed_by':'active_reference'}
            if tid and ref and re.search(r"\b(?:cancel|stop|dismiss)\b",text):
                with local_utils._TIMER_LOCK:
                    item=local_utils._TIMERS.get(tid)
                    if not item:return None
                    item['status']='cancelled'
                nc=dict(card);nc['status']='cancelled';set_context(session_id,'active_object',{'type':typ,'card':nc});return {'message':f"{'Timer' if typ=='timer' else 'Alarm'} cancelled.",'card':nc,'routed_by':'active_reference'}
        if followup_like and typ=='reminder':
            rid=str(card.get('id') or '')
            if rid and duration and ref and (change or add):
                sec=_seconds(duration);items=_load_reminders();target=next((x for x in items if str(x.get('id'))==rid),None)
                if target is not None:
                    try:old=datetime.fromisoformat(str(target.get('due_at')));now=datetime.now(old.tzinfo) if old.tzinfo else datetime.now()
                    except Exception:now=datetime.now();old=now
                    nd=old+timedelta(seconds=sec) if add else now+timedelta(seconds=sec);target['due_at']=nd.isoformat(timespec='seconds');target['status']='scheduled';productivity._save(productivity.REMINDERS,items);nc={'type':'reminder',**target};set_context(session_id,'active_object',{'type':'reminder','card':nc});return {'message':f"Updated that reminder for {nd.strftime('%H:%M:%S')}.",'card':nc,'routed_by':'active_reference'}
            if rid and ref and re.search(r"\b(?:cancel|delete|remove|dismiss)\b",text):
                items=_load_reminders();target=next((x for x in items if str(x.get('id'))==rid),None)
                if target is not None:
                    target['status']='cancelled';productivity._save(productivity.REMINDERS,items);nc={'type':'reminder',**target};set_context(session_id,'active_object',{'type':'reminder','card':nc});return {'message':'Reminder cancelled.','card':nc,'routed_by':'active_reference'}
        if followup_like and typ=='routine' and ref:
            from agentie.core.routine_engine import _parse_trigger,update_routine
            rid=str(card.get('id') or '')
            if rid:
                try:
                    if re.search(r"\b(?:pause|disable)\b",text):item=update_routine(rid,status='paused')
                    elif re.search(r"\b(?:resume|enable)\b",text):item=update_routine(rid,status='active')
                    elif re.search(r"\b(?:delete|remove)\b",text):item=update_routine(rid,status='deleted')
                    else:
                        parsed=_parse_trigger(text_raw)
                        if not parsed:return None
                        item=update_routine(rid,trigger=parsed[0])
                except (KeyError,ValueError) as exc:return {'message':str(exc),'card':None,'routed_by':'active_reference'}
                nc={'type':'routine',**item};set_context(session_id,'active_object',{'type':'routine','card':nc});return {'message':f"Updated routine “{item['name']}”.",'card':nc,'routed_by':'active_reference'}
    # Heuristic background delegation is deliberately last. This gives explicit/local parsing
    # a chance to win and prevents mixed utility requests from becoming coding jobs.
    job=_job_command(session_id,text_raw)
    if job is not None:return job
    return None
