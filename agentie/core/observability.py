from __future__ import annotations

import contextvars
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE=Path.cwd()/"workspace";DB_PATH=WORKSPACE/"agentie_observability.sqlite3";_CURRENT_TRACE=contextvars.ContextVar("agentie_trace_id",default=None)
def _price_table():
    raw=os.getenv("AGENTIE_MODEL_PRICING_JSON","").strip()
    if raw:
        try:return {str(k):(float(v.get("input",0)),float(v.get("output",0))) for k,v in json.loads(raw).items() if isinstance(v,dict)}
        except Exception:pass
    return {}
def _now():return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
def _connect():WORKSPACE.mkdir(parents=True,exist_ok=True);c=sqlite3.connect(DB_PATH,timeout=10);c.row_factory=sqlite3.Row;return c
def init_db():
    with _connect() as c:c.executescript("""
    CREATE TABLE IF NOT EXISTS traces(id TEXT PRIMARY KEY,session_id TEXT,agent_type TEXT,user_message TEXT,status TEXT NOT NULL,routed_by TEXT,started_at TEXT NOT NULL,finished_at TEXT,latency_ms REAL,provider_calls INTEGER NOT NULL DEFAULT 0,input_tokens INTEGER NOT NULL DEFAULT 0,output_tokens INTEGER NOT NULL DEFAULT 0,total_tokens INTEGER NOT NULL DEFAULT 0,estimated_cost_usd REAL,error TEXT);
    CREATE TABLE IF NOT EXISTS trace_events(id INTEGER PRIMARY KEY AUTOINCREMENT,trace_id TEXT NOT NULL,kind TEXT NOT NULL,name TEXT,status TEXT,started_at TEXT NOT NULL,latency_ms REAL,metadata_json TEXT NOT NULL DEFAULT '{}');
    CREATE INDEX IF NOT EXISTS idx_trace_session ON traces(session_id,started_at DESC);CREATE INDEX IF NOT EXISTS idx_trace_events ON trace_events(trace_id,id);
    """)
def start_trace(session_id,agent_type,user_message):
    from agentie.core.memory_store import set_active_memory_scope_from_session
    set_active_memory_scope_from_session(session_id)
    init_db();tid=uuid.uuid4().hex[:12];now=_now()
    with _connect() as c:c.execute("INSERT INTO traces(id,session_id,agent_type,user_message,status,started_at) VALUES(?,?,?,?,?,?)",(tid,session_id,agent_type,user_message[:20000],"running",now))
    _CURRENT_TRACE.set(tid);return tid
def current_trace_id():return _CURRENT_TRACE.get()
def set_current_trace(trace_id):_CURRENT_TRACE.set(trace_id)
def record_event(kind,name="",status="ok",latency_ms=None,metadata=None,trace_id=None):
    tid=trace_id or current_trace_id()
    if not tid:return
    init_db()
    with _connect() as c:c.execute("INSERT INTO trace_events(trace_id,kind,name,status,started_at,latency_ms,metadata_json) VALUES(?,?,?,?,?,?,?)",(tid,kind[:80],name[:160],status[:40],_now(),latency_ms,json.dumps(metadata or {},ensure_ascii=False,default=str)[:50000]))
def record_route(routed_by,metadata=None,trace_id=None):
    tid=trace_id or current_trace_id()
    if not tid:return
    with _connect() as c:c.execute("UPDATE traces SET routed_by=? WHERE id=?",(routed_by[:80],tid))
    record_event("route",routed_by,metadata=metadata,trace_id=tid)
def _value(obj,*names):
    for name in names:
        v=getattr(obj,name,None)
        if v is None and isinstance(obj,dict):v=obj.get(name)
        if v is not None:return v
    return None
def _usage_tuple(usage):
    if usage is None:return (0,0,0,None)
    def integer(*names):
        v=_value(usage,*names)
        try:return int(v or 0)
        except Exception:return 0
    inp=integer("input_tokens","prompt_tokens");out=integer("output_tokens","completion_tokens");total=integer("total_tokens") or inp+out
    raw_cost=_value(usage,"cost","total_cost","cost_usd")
    try:cost=float(raw_cost) if raw_cost is not None else None
    except Exception:cost=None
    return inp,out,total,cost
def _result_accounting(result,configured_model):
    raw=list(getattr(result,"raw_responses",[]) or []);calls=max(1,len(raw))
    aggregate=getattr(result,"usage",None);ctx=getattr(result,"context_wrapper",None)
    if aggregate is None and ctx is not None:aggregate=getattr(ctx,"usage",None)
    if aggregate is not None:
        inp,out,total,cost=_usage_tuple(aggregate)
    else:
        inp=out=total=0;cost_values=[]
        for response in raw:
            i,o,t,c=_usage_tuple(getattr(response,"usage",None));inp+=i;out+=o;total+=t
            if c is not None:cost_values.append(c)
        cost=sum(cost_values) if cost_values else None
    actual_models=[]
    for response in raw:
        model=_value(response,"model","model_name")
        if model and str(model) not in actual_models:actual_models.append(str(model))
    model_name=actual_models[-1] if actual_models else configured_model
    if cost is None:
        prices=_price_table();price=prices.get(model_name) or prices.get(configured_model)
        if price:
            pi,po=price;cost=(inp*pi+out*po)/1_000_000
    return {"provider_calls":calls,"input_tokens":inp,"output_tokens":out,"total_tokens":total,"cost":cost,"model":model_name,"models":actual_models}
def _record_result_items(result,tid):
    for item in getattr(result,"new_items",[]) or []:
        kind=item.__class__.__name__.lower();raw=getattr(item,"raw_item",None);name=""
        for obj in (item,raw):
            if obj is None:continue
            for attr in ("tool_name","name","type"):
                v=getattr(obj,attr,None)
                if v:name=str(v);break
            if name:break
        if "toolcall" in kind or "tool_call" in kind:record_event("tool",name or "tool",metadata={"item_type":item.__class__.__name__},trace_id=tid)
        elif "handoff" in kind:record_event("handoff",name or "agent",metadata={"item_type":item.__class__.__name__},trace_id=tid)
def record_model_result(result,model,latency_ms,trace_id=None):
    tid=trace_id or current_trace_id();a=_result_accounting(result,model);cost=a["cost"]
    if tid:
        with _connect() as c:
            row=c.execute("SELECT estimated_cost_usd FROM traces WHERE id=?",(tid,)).fetchone();previous=row["estimated_cost_usd"] if row and row["estimated_cost_usd"] is not None else None;merged=(float(previous or 0)+float(cost)) if cost is not None else previous
            c.execute("UPDATE traces SET provider_calls=provider_calls+?,input_tokens=input_tokens+?,output_tokens=output_tokens+?,total_tokens=total_tokens+?,estimated_cost_usd=? WHERE id=?",(a["provider_calls"],a["input_tokens"],a["output_tokens"],a["total_tokens"],merged,tid))
        record_event("model",a["model"],latency_ms=latency_ms,metadata={"provider_calls":a["provider_calls"],"models":a["models"],"input_tokens":a["input_tokens"],"output_tokens":a["output_tokens"],"total_tokens":a["total_tokens"],"estimated_cost_usd":cost},trace_id=tid);_record_result_items(result,tid)
    return a
def record_model_error(model,error,latency_ms,trace_id=None):
    tid=trace_id or current_trace_id()
    if tid:
        with _connect() as c:c.execute("UPDATE traces SET provider_calls=provider_calls+1 WHERE id=?",(tid,))
    record_event("model",model,status="error",latency_ms=latency_ms,metadata={"error":str(error)[:5000]},trace_id=tid)
def finish_trace(trace_id,status="completed",error=None):
    init_db();now=_now()
    with _connect() as c:
        row=c.execute("SELECT started_at FROM traces WHERE id=?",(trace_id,)).fetchone();latency=None
        if row:
            try:latency=(datetime.fromisoformat(now)-datetime.fromisoformat(str(row["started_at"]))).total_seconds()*1000
            except Exception:pass
        c.execute("UPDATE traces SET status=?,finished_at=?,latency_ms=?,error=? WHERE id=?",(status,now,latency,error[:5000] if error else None,trace_id))
    if current_trace_id()==trace_id:_CURRENT_TRACE.set(None)
def get_trace(trace_id):
    init_db()
    with _connect() as c:row=c.execute("SELECT * FROM traces WHERE id=?",(trace_id,)).fetchone();events=c.execute("SELECT * FROM trace_events WHERE trace_id=? ORDER BY id",(trace_id,)).fetchall()
    if not row:raise KeyError(trace_id)
    item=dict(row);item["events"]=[]
    for e in events:
        d=dict(e)
        try:d["metadata"]=json.loads(d.pop("metadata_json") or "{}")
        except Exception:d["metadata"]={}
        item["events"].append(d)
    return item
def recent_traces(session_id=None,limit=20):
    init_db();limit=max(1,min(int(limit),100))
    with _connect() as c:rows=c.execute("SELECT * FROM traces WHERE session_id=? ORDER BY started_at DESC LIMIT ?",(session_id,limit)).fetchall() if session_id else c.execute("SELECT * FROM traces ORDER BY started_at DESC LIMIT ?",(limit,)).fetchall()
    return [dict(r) for r in rows]
def trace_card(trace,detailed=False):return {"type":"observability","id":trace["id"],"status":trace.get("status"),"routed_by":trace.get("routed_by"),"agent_type":trace.get("agent_type"),"latency_ms":trace.get("latency_ms"),"provider_calls":trace.get("provider_calls",0),"input_tokens":trace.get("input_tokens",0),"output_tokens":trace.get("output_tokens",0),"total_tokens":trace.get("total_tokens",0),"estimated_cost_usd":trace.get("estimated_cost_usd"),"error":trace.get("error"),"events":trace.get("events",[]) if detailed else []}
def summary_card(session_id=None,limit=20):
    current=current_trace_id();items=[x for x in recent_traces(session_id,limit+1) if x.get("id")!=current][:limit]
    return {"type":"observability_summary","items":items,"requests":len(items),"provider_calls":sum(int(x.get("provider_calls") or 0) for x in items),"tokens":sum(int(x.get("total_tokens") or 0) for x in items),"known_cost_usd":round(sum(float(x.get("estimated_cost_usd") or 0) for x in items if x.get("estimated_cost_usd") is not None),6),"unknown_cost_requests":sum(1 for x in items if int(x.get("provider_calls") or 0)>0 and x.get("estimated_cost_usd") is None)}
