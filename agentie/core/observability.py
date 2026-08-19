from __future__ import annotations

import contextvars
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKSPACE = Path.cwd() / "workspace"
DB_PATH = WORKSPACE / "agentie_observability.sqlite3"
_CURRENT_TRACE: contextvars.ContextVar[str | None] = contextvars.ContextVar("agentie_trace_id", default=None)

# Optional user-configurable pricing. Format: input USD / 1M tokens and output USD / 1M tokens.
# Unknown/auto-routed models intentionally report estimated_cost_usd=None unless configured.
def _price_table() -> dict[str, tuple[float, float]]:
    raw = os.getenv("AGENTIE_MODEL_PRICING_JSON", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            return {str(k): (float(v.get("input", 0)), float(v.get("output", 0))) for k, v in data.items() if isinstance(v, dict)}
        except Exception:
            pass
    return {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _connect() -> sqlite3.Connection:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS traces(
          id TEXT PRIMARY KEY,
          session_id TEXT,
          agent_type TEXT,
          user_message TEXT,
          status TEXT NOT NULL,
          routed_by TEXT,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          latency_ms REAL,
          provider_calls INTEGER NOT NULL DEFAULT 0,
          input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          total_tokens INTEGER NOT NULL DEFAULT 0,
          estimated_cost_usd REAL,
          error TEXT
        );
        CREATE TABLE IF NOT EXISTS trace_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          trace_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          name TEXT,
          status TEXT,
          started_at TEXT NOT NULL,
          latency_ms REAL,
          metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_trace_session ON traces(session_id, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_trace_events ON trace_events(trace_id, id);
        """)


def start_trace(session_id: str | None, agent_type: str, user_message: str) -> str:
    init_db(); tid = uuid.uuid4().hex[:12]; now = _now()
    with _connect() as conn:
        conn.execute("INSERT INTO traces(id,session_id,agent_type,user_message,status,started_at) VALUES(?,?,?,?,?,?)", (tid, session_id, agent_type, user_message[:20000], "running", now))
    _CURRENT_TRACE.set(tid)
    return tid


def current_trace_id() -> str | None:
    return _CURRENT_TRACE.get()


def set_current_trace(trace_id: str | None) -> None:
    _CURRENT_TRACE.set(trace_id)


def record_event(kind: str, name: str = "", status: str = "ok", latency_ms: float | None = None, metadata: dict[str, Any] | None = None, trace_id: str | None = None) -> None:
    tid = trace_id or current_trace_id()
    if not tid: return
    init_db()
    with _connect() as conn:
        conn.execute("INSERT INTO trace_events(trace_id,kind,name,status,started_at,latency_ms,metadata_json) VALUES(?,?,?,?,?,?,?)", (tid, kind[:80], name[:160], status[:40], _now(), latency_ms, json.dumps(metadata or {}, ensure_ascii=False, default=str)[:50000]))


def record_route(routed_by: str, metadata: dict[str, Any] | None = None, trace_id: str | None = None) -> None:
    tid = trace_id or current_trace_id()
    if not tid: return
    with _connect() as conn:
        conn.execute("UPDATE traces SET routed_by=? WHERE id=?", (routed_by[:80], tid))
    record_event("route", routed_by, metadata=metadata, trace_id=tid)


def _usage_from_result(result: Any) -> tuple[int, int, int]:
    inp = out = total = 0
    # Agents SDK versions expose usage in different places. Inspect conservatively.
    candidates = [getattr(result, "usage", None)]
    ctx = getattr(result, "context_wrapper", None)
    if ctx is not None: candidates.append(getattr(ctx, "usage", None))
    for response in getattr(result, "raw_responses", []) or []:
        candidates.append(getattr(response, "usage", None))
    for usage in candidates:
        if usage is None: continue
        def val(*names: str) -> int:
            for n in names:
                v = getattr(usage, n, None)
                if v is None and isinstance(usage, dict): v = usage.get(n)
                if v is not None:
                    try: return int(v)
                    except Exception: pass
            return 0
        inp += val("input_tokens", "prompt_tokens")
        out += val("output_tokens", "completion_tokens")
        t = val("total_tokens")
        if t: total += t
    if total == 0: total = inp + out
    return inp, out, total


def record_model_result(result: Any, model: str, latency_ms: float, trace_id: str | None = None) -> dict[str, Any]:
    tid = trace_id or current_trace_id(); inp, out, total = _usage_from_result(result)
    prices = _price_table(); cost = None
    if model in prices:
        pi, po = prices[model]; cost = (inp * pi + out * po) / 1_000_000
    if tid:
        with _connect() as conn:
            row = conn.execute("SELECT estimated_cost_usd FROM traces WHERE id=?", (tid,)).fetchone()
            previous = row["estimated_cost_usd"] if row and row["estimated_cost_usd"] is not None else None
            merged_cost = (float(previous or 0) + float(cost)) if cost is not None else previous
            conn.execute("UPDATE traces SET provider_calls=provider_calls+1,input_tokens=input_tokens+?,output_tokens=output_tokens+?,total_tokens=total_tokens+?,estimated_cost_usd=? WHERE id=?", (inp, out, total, merged_cost, tid))
        record_event("model", model, latency_ms=latency_ms, metadata={"input_tokens":inp,"output_tokens":out,"total_tokens":total,"estimated_cost_usd":cost}, trace_id=tid)
    return {"input_tokens":inp,"output_tokens":out,"total_tokens":total,"estimated_cost_usd":cost}


def record_model_error(model: str, error: Exception | str, latency_ms: float, trace_id: str | None = None) -> None:
    tid = trace_id or current_trace_id()
    if tid:
        with _connect() as conn: conn.execute("UPDATE traces SET provider_calls=provider_calls+1 WHERE id=?", (tid,))
    record_event("model", model, status="error", latency_ms=latency_ms, metadata={"error":str(error)[:5000]}, trace_id=tid)


def finish_trace(trace_id: str, status: str = "completed", error: str | None = None) -> None:
    init_db(); now = _now()
    with _connect() as conn:
        row = conn.execute("SELECT started_at FROM traces WHERE id=?", (trace_id,)).fetchone()
        latency = None
        if row:
            try:
                start = datetime.fromisoformat(str(row["started_at"])); end = datetime.fromisoformat(now); latency = (end-start).total_seconds()*1000
            except Exception: pass
        conn.execute("UPDATE traces SET status=?,finished_at=?,latency_ms=?,error=? WHERE id=?", (status, now, latency, error[:5000] if error else None, trace_id))
    if current_trace_id() == trace_id: _CURRENT_TRACE.set(None)


def get_trace(trace_id: str) -> dict[str, Any]:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM traces WHERE id=?", (trace_id,)).fetchone()
        events = conn.execute("SELECT * FROM trace_events WHERE trace_id=? ORDER BY id", (trace_id,)).fetchall()
    if not row: raise KeyError(trace_id)
    item = dict(row); item["events"] = []
    for e in events:
        d = dict(e)
        try: d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
        except Exception: d["metadata"] = {}
        item["events"].append(d)
    return item


def recent_traces(session_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    init_db(); limit=max(1,min(int(limit),100))
    with _connect() as conn:
        if session_id:
            rows=conn.execute("SELECT * FROM traces WHERE session_id=? ORDER BY started_at DESC LIMIT ?",(session_id,limit)).fetchall()
        else:
            rows=conn.execute("SELECT * FROM traces ORDER BY started_at DESC LIMIT ?",(limit,)).fetchall()
    return [dict(r) for r in rows]


def trace_card(trace: dict[str, Any], detailed: bool = False) -> dict[str, Any]:
    return {"type":"observability","id":trace["id"],"status":trace.get("status"),"routed_by":trace.get("routed_by"),"agent_type":trace.get("agent_type"),"latency_ms":trace.get("latency_ms"),"provider_calls":trace.get("provider_calls",0),"input_tokens":trace.get("input_tokens",0),"output_tokens":trace.get("output_tokens",0),"total_tokens":trace.get("total_tokens",0),"estimated_cost_usd":trace.get("estimated_cost_usd"),"error":trace.get("error"),"events":trace.get("events",[]) if detailed else []}


def summary_card(session_id: str | None = None, limit: int = 20) -> dict[str, Any]:
    items=recent_traces(session_id,limit); return {"type":"observability_summary","items":items,"requests":len(items),"provider_calls":sum(int(x.get("provider_calls") or 0) for x in items),"tokens":sum(int(x.get("total_tokens") or 0) for x in items),"known_cost_usd":round(sum(float(x.get("estimated_cost_usd") or 0) for x in items if x.get("estimated_cost_usd") is not None),6),"unknown_cost_requests":sum(1 for x in items if int(x.get("provider_calls") or 0)>0 and x.get("estimated_cost_usd") is None)}
