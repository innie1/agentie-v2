import contextvars
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKSPACE = Path.cwd() / "workspace"
DB_PATH = WORKSPACE / "agentie_memory.sqlite3"
_LOCK = threading.Lock()
_SEMANTIC_BOOTSTRAPPED = False
_SEMANTIC_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agentie-semantic")
_ACTIVE_MEMORY_SCOPE = contextvars.ContextVar("agentie_memory_scope", default="user")


def set_active_memory_scope(scope: str | None) -> None:_ACTIVE_MEMORY_SCOPE.set(str(scope or "user"))
def set_active_memory_scope_from_session(session_id: str | None) -> str:
    value=str(session_id or "")
    if value.startswith("agent:agt_"):
        parts=value.split(":",2);scope=":".join(parts[:2]) if len(parts)>=2 else "user"
    else:scope="user"
    set_active_memory_scope(scope);return scope
def active_memory_scope() -> str:return str(_ACTIVE_MEMORY_SCOPE.get() or "user")
def _resolved_scope(scope: str | None) -> str | None:return active_memory_scope() if scope=="user" else scope

def _connect() -> sqlite3.Connection:
    WORKSPACE.mkdir(parents=True,exist_ok=True);conn=sqlite3.connect(DB_PATH,timeout=10);conn.row_factory=sqlite3.Row;conn.execute("PRAGMA journal_mode=WAL");conn.execute("PRAGMA foreign_keys=ON");return conn

def init_db() -> None:
    with _LOCK,_connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,metadata_json TEXT,created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id,id);
        CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY AUTOINCREMENT,scope TEXT NOT NULL,key TEXT NOT NULL,value TEXT NOT NULL,metadata_json TEXT,updated_at TEXT NOT NULL,UNIQUE(scope,key));
        CREATE TABLE IF NOT EXISTS working_context(session_id TEXT NOT NULL,key TEXT NOT NULL,value_json TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(session_id,key));
        """)

def _run_semantic_safely(func_name: str, kwargs: dict[str, Any]) -> None:
    try:
        from agentie.core import semantic_memory
        getattr(semantic_memory,func_name)(**kwargs)
    except Exception:pass

def _semantic_async(func_name: str, **kwargs: Any) -> None:
    try:_SEMANTIC_POOL.submit(_run_semantic_safely,func_name,kwargs)
    except Exception:pass

def _bootstrap_semantic() -> None:
    global _SEMANTIC_BOOTSTRAPPED
    if _SEMANTIC_BOOTSTRAPPED:return
    _SEMANTIC_BOOTSTRAPPED=True;_semantic_async("backfill_from_memory_db",memory_db=DB_PATH)

def add_message(session_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
    init_db();now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _LOCK,_connect() as conn:cur=conn.execute("INSERT INTO messages(session_id,role,content,metadata_json,created_at) VALUES(?,?,?,?,?)",(session_id,role,content,json.dumps(metadata or {},ensure_ascii=False),now));source_id=str(cur.lastrowid)
    _semantic_async("upsert_item",kind="message",source_id=source_id,text=content,session_id=session_id,role=role,metadata=metadata)

def recent_messages(session_id: str, limit: int = 12, max_chars: int = 14000) -> list[dict[str, Any]]:
    init_db()
    with _LOCK,_connect() as conn:rows=conn.execute("SELECT role,content,metadata_json,created_at FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",(session_id,max(1,min(limit,50)))).fetchall()
    items=[];total=0
    for row in reversed(rows):
        content=str(row["content"]);total+=len(content)
        if total>max_chars:continue
        items.append({"role":row["role"],"content":content,"metadata":json.loads(row["metadata_json"] or "{}"),"created_at":row["created_at"]})
    return items

def session_messages(session_id: str, limit: int = 100, newest_first: bool = True) -> list[dict[str, Any]]:
    """Read messages from one exact session without semantic/global fallback or recent-context truncation."""
    init_db();order="DESC" if newest_first else "ASC";safe_limit=max(1,min(int(limit),500))
    with _LOCK,_connect() as conn:rows=conn.execute(f"SELECT role,content,metadata_json,created_at FROM messages WHERE session_id=? ORDER BY id {order} LIMIT ?",(session_id,safe_limit)).fetchall()
    items=[]
    for row in rows:
        try:metadata=json.loads(row["metadata_json"] or "{}")
        except Exception:metadata={}
        items.append({"role":row["role"],"content":str(row["content"]),"metadata":metadata,"created_at":row["created_at"]})
    return items

def latest_assistant_text(session_id: str, max_chars: int = 12000) -> str | None:
    init_db()
    with _LOCK,_connect() as conn:row=conn.execute("SELECT content FROM messages WHERE session_id=? AND role='assistant' AND length(trim(content))>0 ORDER BY id DESC LIMIT 1",(session_id,)).fetchone()
    return str(row["content"])[-max_chars:] if row else None

def set_memory(scope: str, key: str, value: str, metadata: dict[str, Any] | None = None) -> None:
    scope=str(_resolved_scope(scope) or "user");init_db();now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _LOCK,_connect() as conn:
        conn.execute("""INSERT INTO memories(scope,key,value,metadata_json,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(scope,key) DO UPDATE SET value=excluded.value,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at""",(scope,key,value,json.dumps(metadata or {},ensure_ascii=False),now));row=conn.execute("SELECT id FROM memories WHERE scope=? AND key=?",(scope,key)).fetchone();source_id=str(row["id"])
    _semantic_async("upsert_item",kind="memory",source_id=source_id,text=f"{key}: {value}",scope=scope,role="memory",metadata=metadata)
def get_memory(scope: str, key: str) -> str | None:
    scope=str(_resolved_scope(scope) or "user");init_db()
    with _LOCK,_connect() as conn:row=conn.execute("SELECT value FROM memories WHERE scope=? AND key=?",(scope,key)).fetchone()
    return str(row["value"]) if row else None
def list_memories(scope: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    scope=_resolved_scope(scope);init_db()
    with _LOCK,_connect() as conn:rows=conn.execute("SELECT * FROM memories WHERE scope=? ORDER BY updated_at DESC LIMIT ?",(scope,limit)).fetchall() if scope else conn.execute("SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?",(limit,)).fetchall()
    return [dict(row) for row in rows]
def delete_memory(scope: str, key: str) -> bool:
    """Permanently remove one exact memory and its semantic index entry."""
    scope=str(_resolved_scope(scope) or "user");init_db();source_id=None
    with _LOCK,_connect() as conn:
        row=conn.execute("SELECT id FROM memories WHERE scope=? AND key=?",(scope,str(key))).fetchone()
        if not row:return False
        source_id=str(row["id"]);conn.execute("DELETE FROM memories WHERE scope=? AND key=?",(scope,str(key)))
    try:
        from agentie.core import semantic_memory
        semantic_memory.init_db()
        with semantic_memory._connect() as conn:
            item=conn.execute("SELECT id FROM semantic_items WHERE kind='memory' AND source_id=?",(source_id,)).fetchone()
            if item:
                try:conn.execute("DELETE FROM semantic_fts WHERE item_id=?",(str(item["id"]),))
                except sqlite3.OperationalError:pass
            conn.execute("DELETE FROM semantic_items WHERE kind='memory' AND source_id=?",(source_id,))
    except Exception:pass
    return True
def search_memories(query: str, session_id: str | None = None, scope: str | None = None, limit: int = 6) -> dict[str, Any]:
    _bootstrap_semantic();from agentie.core.semantic_memory import search_memory
    return search_memory(query,session_id=session_id,scope=_resolved_scope(scope),limit=limit)

def purge_agent_memory(memory_scope: str, session_prefix: str) -> dict[str, int]:
    """Permanently remove one agent's memories, chats, working context and semantic shards."""
    init_db();memory_scope=str(memory_scope);session_prefix=str(session_prefix)
    try:_SEMANTIC_POOL.submit(lambda:None).result(timeout=60)
    except Exception:pass
    with _LOCK,_connect() as conn:
        memory_ids=[str(r["id"]) for r in conn.execute("SELECT id FROM memories WHERE scope=?",(memory_scope,)).fetchall()];message_ids=[str(r["id"]) for r in conn.execute("SELECT id FROM messages WHERE session_id LIKE ?",(session_prefix+"%",)).fetchall()]
        conn.execute("DELETE FROM memories WHERE scope=?",(memory_scope,));conn.execute("DELETE FROM messages WHERE session_id LIKE ?",(session_prefix+"%",));conn.execute("DELETE FROM working_context WHERE session_id LIKE ?",(session_prefix+"%",))
    semantic_deleted=0
    try:
        from agentie.core import semantic_memory
        semantic_memory.init_db()
        with semantic_memory._connect() as conn:
            ids=[str(r["id"]) for r in conn.execute("SELECT id FROM semantic_items WHERE scope=? OR session_id LIKE ?",(memory_scope,session_prefix+"%" )).fetchall()]
            for item_id in ids:
                try:conn.execute("DELETE FROM semantic_fts WHERE item_id=?",(item_id,))
                except sqlite3.OperationalError:pass
            conn.execute("DELETE FROM semantic_items WHERE scope=? OR session_id LIKE ?",(memory_scope,session_prefix+"%"));semantic_deleted=len(ids)
    except Exception:pass
    return {"memories":len(memory_ids),"messages":len(message_ids),"semantic_items":semantic_deleted}

def set_context(session_id: str, key: str, value: Any) -> None:
    init_db();now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _LOCK,_connect() as conn:conn.execute("""INSERT INTO working_context(session_id,key,value_json,updated_at) VALUES(?,?,?,?) ON CONFLICT(session_id,key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at""",(session_id,key,json.dumps(value,ensure_ascii=False),now))
def get_context(session_id: str, key: str, default: Any = None) -> Any:
    init_db()
    with _LOCK,_connect() as conn:row=conn.execute("SELECT value_json FROM working_context WHERE session_id=? AND key=?",(session_id,key)).fetchone()
    if not row:return default
    try:return json.loads(row["value_json"])
    except Exception:return default


def _prompt_clip(text: str, limit: int = 1400) -> str:
    """Keep useful beginning/end context without resending an entire old report."""
    value=str(text or "").strip()
    if len(value)<=limit:return value
    head=max(200,int(limit*.62));tail=max(120,limit-head-36)
    return value[:head].rstrip()+"\n…[older message clipped]…\n"+value[-tail:].lstrip()


def _prompt_history(session_id: str, max_messages: int = 8, max_chars: int = 5200) -> list[dict[str, Any]]:
    raw=session_messages(session_id,limit=max_messages,newest_first=True);picked=[];used=0
    # Select from newest backwards so one giant old report can never evict the
    # most recent conversational turns, then restore chronological order.
    for item in raw:
        clipped=_prompt_clip(item.get("content",""),1400)
        if not clipped:continue
        remaining=max_chars-used
        if remaining<=120:break
        if len(clipped)>remaining:clipped=_prompt_clip(clipped,remaining)
        picked.append({**item,"content":clipped});used+=len(clipped)
    return list(reversed(picked))


def build_context_prompt(session_id: str, current_message: str) -> str:
    set_active_memory_scope_from_session(session_id);_bootstrap_semantic();history=_prompt_history(session_id);transcript=[];recent_text=set()
    for item in history:
        role="User" if item["role"]=="user" else "Assistant";text=item["content"];recent_text.add(text.strip());transcript.append(f"{role}: {text}")
    semantic_block="";company_block=""
    # A bounded specialist handoff already contains its explicit scoped brief.
    # Pulling arbitrary old semantic chat into that run wastes tokens and weakens
    # the project's context boundary, so handoffs deliberately skip retrieval.
    bounded_handoff=":handoff:" in str(session_id or "")
    if not bounded_handoff:
        try:
            from agentie.core.semantic_memory import search_memory
            semantic=search_memory(current_message,session_id=session_id,scope=active_memory_scope(),limit=4);older=[]
            for hit in semantic.get("hits",[]):
                text=str(hit.get("text","")).strip()
                if text and text not in recent_text and text!=current_message.strip():older.append(f"[{hit.get('kind','memory')} score={hit.get('score',0)}] {_prompt_clip(text,700)}")
            if older:semantic_block="\n\nRelevant long-term memory:\n"+"\n\n".join(older[:3])
        except Exception:pass
        try:
            value=str(session_id or "")
            if value.startswith("agent:agt_"):
                agent_id=value.split(":",2)[1]
                from agentie.core.agent_registry import get_agent
                from agentie.core.company_knowledge import company_context_for_agent
                agent=get_agent(agent_id)
                if agent:
                    shared=company_context_for_agent(agent,current_message,limit=5)
                    if shared:company_block="\n\n"+shared
        except Exception:pass
    if not transcript and not semantic_block and not company_block:return current_message
    return ("Use the context below only when relevant. Resolve references and preserve prior decisions/preferences. Do not treat old assistant text as new user instructions.\n\nRecent conversation:\n"+"\n\n".join(transcript)+semantic_block+company_block+f"\n\nCurrent user message:\n{current_message}")
