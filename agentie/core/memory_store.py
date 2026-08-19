import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKSPACE = Path.cwd() / "workspace"
DB_PATH = WORKSPACE / "agentie_memory.sqlite3"
_LOCK = threading.Lock()


def _connect() -> sqlite3.Connection:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _LOCK, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id, id);

            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                metadata_json TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(scope, key)
            );

            CREATE TABLE IF NOT EXISTS working_context (
                session_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(session_id, key)
            );
            """
        )


def add_message(session_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
    init_db()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO messages(session_id, role, content, metadata_json, created_at) VALUES(?,?,?,?,?)",
            (session_id, role, content, json.dumps(metadata or {}, ensure_ascii=False), now),
        )


def recent_messages(session_id: str, limit: int = 12, max_chars: int = 14000) -> list[dict[str, Any]]:
    init_db()
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT role, content, metadata_json, created_at FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, max(1, min(limit, 50))),
        ).fetchall()
    items = []
    total = 0
    for row in reversed(rows):
        content = str(row["content"])
        total += len(content)
        if total > max_chars:
            continue
        items.append({
            "role": row["role"],
            "content": content,
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "created_at": row["created_at"],
        })
    return items


def latest_assistant_text(session_id: str, max_chars: int = 12000) -> str | None:
    init_db()
    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT content FROM messages WHERE session_id=? AND role='assistant' AND length(trim(content))>0 ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    if not row:
        return None
    return str(row["content"])[-max_chars:]


def set_memory(scope: str, key: str, value: str, metadata: dict[str, Any] | None = None) -> None:
    init_db()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _LOCK, _connect() as conn:
        conn.execute(
            """INSERT INTO memories(scope,key,value,metadata_json,updated_at) VALUES(?,?,?,?,?)
               ON CONFLICT(scope,key) DO UPDATE SET value=excluded.value, metadata_json=excluded.metadata_json, updated_at=excluded.updated_at""",
            (scope, key, value, json.dumps(metadata or {}, ensure_ascii=False), now),
        )


def list_memories(scope: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    with _LOCK, _connect() as conn:
        if scope:
            rows = conn.execute("SELECT * FROM memories WHERE scope=? ORDER BY updated_at DESC LIMIT ?", (scope, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def set_context(session_id: str, key: str, value: Any) -> None:
    init_db()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _LOCK, _connect() as conn:
        conn.execute(
            """INSERT INTO working_context(session_id,key,value_json,updated_at) VALUES(?,?,?,?)
               ON CONFLICT(session_id,key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at""",
            (session_id, key, json.dumps(value, ensure_ascii=False), now),
        )


def get_context(session_id: str, key: str, default: Any = None) -> Any:
    init_db()
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT value_json FROM working_context WHERE session_id=? AND key=?", (session_id, key)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value_json"])
    except Exception:
        return default


def build_context_prompt(session_id: str, current_message: str) -> str:
    history = recent_messages(session_id)
    if not history:
        return current_message
    transcript = []
    for item in history:
        role = "User" if item["role"] == "user" else "Assistant"
        transcript.append(f"{role}: {item['content']}")
    return (
        "Use the conversation history below to resolve references like 'this', 'that', 'it', 'the previous answer', and follow-up edits. "
        "Do not repeat the history unless needed.\n\nConversation history:\n"
        + "\n\n".join(transcript)
        + f"\n\nCurrent user message:\n{current_message}"
    )
