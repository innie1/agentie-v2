from __future__ import annotations

import json,re,uuid
from datetime import datetime
from pathlib import Path
from typing import Any

WORKSPACE=Path.cwd()/"workspace";ROUTINES=WORKSPACE/"routines.json";RUNS=WORKSPACE/"routine_runs.json"

def _load(path:Path,default):
    try:return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:return default
def _save(path:Path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding="utf-8")
def _norm(text:str)->str:return re.sub(r"[^a-z0-9: ]+","",re.sub(r"\s+"," ",str(text or "").strip().lower()))
def _signature(trigger:str,action:str)->str:return f"{_norm(trigger)}|{_norm(action)}"
def list_routines()->list[dict[str,Any]]:return _load(ROUTINES,[])
def _clock(raw:str|None,default="09:00")->str:
    if not raw:return default
    s=raw.lower().replace(" ","");m=re.match(r"(\d{1,2})(?::(\d{2}))?(am|pm)?$",s)
    if not m:return default
    h=int(m.group(1));minute=int(m.group(2) or 0);ap=m.group(3)
    if ap=="pm" and h<12:h+=12
    if ap=="am" and h==12:h=0
    return f"{h%24:02d}:{minute%60:02d}"
def _parse_trigger(text:str)->tuple[str,str]|None:
    rules=[
      (r"\bevery weekday(?:s)?(?: at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?\b",lambda m:f"weekdays at {_clock(m.group(1))}"),
      (r"\b(?:every day|daily)(?: at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?\b",lambda m:f"daily at {_clock(m.group(1))}"),
      (r"\bevery morning\b",lambda m:"daily at 08:00"),(r"\bevery afternoon\b",lambda m:"daily at 15:00"),(r"\bevery evening\b",lambda m:"daily at 19:00"),
      (r"\bevery\s+(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)\b",lambda m:f"every {m.group(1)} {'hours' if m.group(2).lower().startswith(('hour','hr')) else 'minutes'}"),
      (r"\bevery\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?: at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?\b",lambda m:f"weekly {m.group(1).lower()} at {_clock(m.group(2))}"),]
    for p,f in rules:
        m=re.search(p,text,re.I)
        if m:return f(m),m.group(0)
    return None
def _name_for(action:str)->str:return " ".join(re.findall(r"[A-Za-z0-9]+",action)[:7]).title() or "Routine"
def create_routine(text:str,agent_role:str|None=None):
    parsed=_parse_trigger(text)
    if not parsed:raise ValueError("Tell me when it should run, for example every weekday at 9, every morning, or every 30 minutes.")
    trigger,phrase=parsed;action=re.sub(re.escape(phrase),"",text,flags=re.I).strip(" ,.;:-");action=re.sub(r"^(?:create|make|set up|setup|add)\s+(?:me\s+)?(?:a\s+)?routine\s+(?:to|that|which)?\s*","",action,flags=re.I).strip();action=re.sub(r"^please\s+","",action,flags=re.I).strip()
    if not action:raise ValueError("Tell me what the routine should do.")
    sig=_signature(trigger,action);items=list_routines();existing=next((x for x in items if x.get("signature")==sig and x.get("status")!="deleted"),None)
    if existing:return existing,False
    now=datetime.now().astimezone().isoformat(timespec="seconds");item={"id":uuid.uuid4().hex[:8],"name":_name_for(action),"trigger":trigger,"action":action,"agent_role":agent_role or "auto","status":"active","created_at":now,"updated_at":now,"last_run":None,"signature":sig,"run_count":0};items.append(item);_save(ROUTINES,items);return item,True
def update_routine(routine_id:str,**changes):
    items=list_routines();item=next((x for x in items if x.get("id")==routine_id),None)
    if not item:raise KeyError(routine_id)
    for k in ["trigger","action","name","agent_role","status"]:
        if changes.get(k):item[k]=changes[k]
    item["signature"]=_signature(item["trigger"],item["action"]);item["updated_at"]=datetime.now().astimezone().isoformat(timespec="seconds");dup=next((x for x in items if x.get("id")!=routine_id and x.get("signature")==item["signature"] and x.get("status")!="deleted"),None)
    if dup:raise ValueError(f"That would duplicate routine {dup['id']} ({dup['name']}).")
    _save(ROUTINES,items);return item
def find_routine(query:str):
    q=_norm(query);items=[x for x in list_routines() if x.get("status")!="deleted"];exact=next((x for x in items if str(x.get("id")) in q),None)
    if exact:return exact
    qwords=set(q.split());scored=[(len(qwords & set(_norm(f"{x.get('name','')} {x.get('action','')} {x.get('trigger','')}").split())),x) for x in items];scored.sort(key=lambda p:p[0],reverse=True);return scored[0][1] if scored and scored[0][0]>0 else (items[-1] if len(items)==1 else None)
def route_routine_command(message:str):
    text=" ".join(message.strip().split());lower=text.lower()
    if re.search(r"\b(show|list|what are|my)\b.*\broutines?\b",lower) or lower in {"routines","show routines"}:
        items=[x for x in list_routines() if x.get("status")!="deleted"];return {"message":f"You have {len(items)} routine(s).","card":{"type":"routines","items":items}}
    if re.search(r"\b(create|make|set up|setup|add)\b.*\broutine\b",lower) or ("every " in lower and any(v in lower for v in ["check ","research ","summarize ","save ","run ","look ","tell ","remind "])):
        rm=re.search(r"\b(?:using|with|as)\s+(?:the\s+)?([a-z][a-z -]{1,40})\s+agent\b",lower);role=rm.group(1).strip() if rm else None
        try:item,created=create_routine(text,role)
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"{'Created' if created else 'Reused existing'} routine “{item['name']}”.","card":{"type":"routine",**item,"duplicate_prevented":not created}}
    if "routine" in lower and re.search(r"\b(pause|resume|enable|disable|delete|remove|change|edit|rename)\b",lower):
        item=find_routine(text)
        if not item:return {"message":"Which routine do you mean?","card":None}
        try:
            if re.search(r"\b(pause|disable)\b",lower):item=update_routine(item["id"],status="paused")
            elif re.search(r"\b(resume|enable)\b",lower):item=update_routine(item["id"],status="active")
            elif re.search(r"\b(delete|remove)\b",lower):item=update_routine(item["id"],status="deleted")
            else:
                parsed=_parse_trigger(text);rm=re.search(r"\b(?:rename|call)\b.*?\b(?:to|as)\b\s+(.+)$",text,re.I);am=re.search(r"\b(?:change|edit).*?\b(?:to do|action to|so it)\b\s+(.+)$",text,re.I);item=update_routine(item["id"],trigger=parsed[0] if parsed else None,name=rm.group(1).strip() if rm else None,action=am.group(1).strip() if am else None)
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"Updated routine “{item['name']}”.","card":{"type":"routine",**item}}
    return None
def _due(item:dict[str,Any],now:datetime)->bool:
    if item.get("status")!="active":return False
    last=datetime.fromisoformat(item["last_run"]) if item.get("last_run") else None;trig=str(item.get("trigger","")).lower();m=re.match(r"every (\d+(?:\.\d+)?) (minutes|hours)",trig)
    if m:
        sec=float(m.group(1))*(3600 if m.group(2)=="hours" else 60);base=last or datetime.fromisoformat(item["created_at"]);return (now-base).total_seconds()>=sec
    tm=re.search(r"at (\d{1,2}):(\d{2})",trig);hour,minute=(int(tm.group(1)),int(tm.group(2))) if tm else (9,0);target=now.replace(hour=hour,minute=minute,second=0,microsecond=0)
    if now<target or (last and last.date()==now.date()):return False
    if trig.startswith("daily"):return True
    if trig.startswith("weekdays"):return now.weekday()<5
    wm=re.match(r"weekly (\w+)",trig);names={"monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4,"saturday":5,"sunday":6};return bool(wm and now.weekday()==names.get(wm.group(1),-1))
def claim_due_routines(now:datetime|None=None):
    now=now or datetime.now().astimezone();items=list_routines();due=[]
    for item in items:
        if _due(item,now):item["last_run"]=now.isoformat(timespec="seconds");item["run_count"]=int(item.get("run_count") or 0)+1;due.append(dict(item))
    if due:_save(ROUTINES,items)
    return due
def record_run(routine_id:str,job_id:str|None,status="started"):
    runs=_load(RUNS,[]);runs.append({"routine_id":routine_id,"job_id":job_id,"status":status,"at":datetime.now().astimezone().isoformat(timespec="seconds")});_save(RUNS,runs[-1000:])
