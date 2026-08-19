from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agentie.core.file_service import UPLOADS, extract_text, ensure_dirs

WORKSPACE = Path.cwd() / "workspace"
DB_PATH = WORKSPACE / "agentie_collections.sqlite3"
SUPPORTED = {".pdf", ".csv", ".json", ".yaml", ".yml", ".txt", ".md", ".py", ".js", ".html", ".css", ".toml", ".ini", ".log"}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS collections(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE COLLATE NOCASE,description TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,collection_id TEXT NOT NULL,filename TEXT NOT NULL,source_path TEXT NOT NULL,indexed_at TEXT NOT NULL,chars INTEGER NOT NULL DEFAULT 0,UNIQUE(collection_id, filename));
        CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY,document_id TEXT NOT NULL,collection_id TEXT NOT NULL,filename TEXT NOT NULL,position INTEGER NOT NULL,text TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_chunks_collection ON chunks(collection_id, position);
        """)
        try: conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, collection_id UNINDEXED, filename UNINDEXED, text, tokenize='porter unicode61')")
        except sqlite3.OperationalError: pass


def _slug(text: str) -> str: return re.sub(r"\s+", " ", str(text or "").strip())


def create_collection(name: str, description: str = "") -> tuple[dict[str, Any], bool]:
    init_db(); clean=_slug(name)
    if not clean: raise ValueError("Collection name is required.")
    with _connect() as conn:
        row=conn.execute("SELECT * FROM collections WHERE name=? COLLATE NOCASE",(clean,)).fetchone()
        if row:return dict(row),False
        cid=uuid.uuid4().hex[:10];now=_now();conn.execute("INSERT INTO collections(id,name,description,created_at,updated_at) VALUES(?,?,?,?,?)",(cid,clean[:120],description[:1000],now,now));row=conn.execute("SELECT * FROM collections WHERE id=?",(cid,)).fetchone()
    return dict(row),True


def list_collections()->list[dict[str,Any]]:
    init_db()
    with _connect() as conn:rows=conn.execute("SELECT c.*, COUNT(d.id) document_count FROM collections c LEFT JOIN documents d ON d.collection_id=c.id GROUP BY c.id ORDER BY c.updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def find_collection(name_or_id:str)->dict[str,Any]|None:
    init_db();q=_slug(name_or_id)
    with _connect() as conn:
        row=conn.execute("SELECT * FROM collections WHERE id=? OR name=? COLLATE NOCASE",(q,q)).fetchone()
        if row:return dict(row)
        row=conn.execute("SELECT * FROM collections WHERE name LIKE ? COLLATE NOCASE ORDER BY updated_at DESC LIMIT 1",(f"%{q}%",)).fetchone()
    return dict(row) if row else None


def _chunks(text:str,size:int=1400,overlap:int=220)->list[str]:
    text=re.sub(r"\r\n?","\n",text).strip()
    if not text:return []
    out=[];start=0
    while start<len(text):
        end=min(len(text),start+size)
        if end<len(text):
            cut=max(text.rfind("\n",start,end),text.rfind(". ",start,end))
            if cut>start+size//2:end=cut+1
        piece=text[start:end].strip()
        if piece:out.append(piece)
        if end>=len(text):break
        start=max(start+1,end-overlap)
    return out[:2000]


def index_file(collection:str,filename:str)->dict[str,Any]:
    ensure_dirs();col=find_collection(collection)
    if not col:col,_=create_collection(collection)
    path=(UPLOADS/Path(filename).name).resolve()
    if path.parent!=UPLOADS.resolve() or not path.exists():raise FileNotFoundError(filename)
    if path.suffix.lower() not in SUPPORTED:raise ValueError("That file type is not text-indexable yet.")
    payload=extract_text(path);text=str(payload.get("text") or "");pieces=_chunks(text)
    if not pieces:raise ValueError("No indexable text was found in that file.")
    doc_id=uuid.uuid4().hex[:12]
    with _connect() as conn:
        old=conn.execute("SELECT id FROM documents WHERE collection_id=? AND filename=?",(col["id"],path.name)).fetchone()
        if old:
            old_id=str(old["id"]);old_chunks=[str(r["id"]) for r in conn.execute("SELECT id FROM chunks WHERE document_id=?",(old_id,)).fetchall()]
            if old_chunks:
                try:conn.executemany("DELETE FROM chunks_fts WHERE chunk_id=?",[(x,) for x in old_chunks])
                except sqlite3.OperationalError:pass
            conn.execute("DELETE FROM chunks WHERE document_id=?",(old_id,));conn.execute("DELETE FROM documents WHERE id=?",(old_id,))
        conn.execute("INSERT INTO documents(id,collection_id,filename,source_path,indexed_at,chars) VALUES(?,?,?,?,?,?)",(doc_id,col["id"],path.name,str(path),_now(),len(text)))
        for pos,piece in enumerate(pieces):
            cid=f"{doc_id}:{pos}";conn.execute("INSERT INTO chunks(id,document_id,collection_id,filename,position,text) VALUES(?,?,?,?,?,?)",(cid,doc_id,col["id"],path.name,pos,piece))
            try:conn.execute("INSERT INTO chunks_fts(chunk_id,collection_id,filename,text) VALUES(?,?,?,?)",(cid,col["id"],path.name,piece))
            except sqlite3.OperationalError:pass
        conn.execute("UPDATE collections SET updated_at=? WHERE id=?",(_now(),col["id"]))
    return {"collection":col["name"],"collection_id":col["id"],"filename":path.name,"chunks":len(pieces),"chars":len(text)}


def _query_terms(query:str)->list[str]:return [w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{1,}",query.lower()) if w not in {"the","a","an","of","to","in","for","and","or","is","are","this","that","what","how","why"}][:16]


def search_collection(collection:str,query:str,limit:int=6)->dict[str,Any]:
    init_db();col=find_collection(collection)
    if not col:raise ValueError("Collection not found.")
    limit=max(1,min(int(limit),12));terms=_query_terms(query);rows=[]
    with _connect() as conn:
        if terms:
            fts_query=" OR ".join(f'"{t}"' for t in terms)
            try:rows=conn.execute("SELECT chunk_id,filename,text,bm25(chunks_fts) rank FROM chunks_fts WHERE collection_id=? AND chunks_fts MATCH ? ORDER BY rank LIMIT ?",(col["id"],fts_query,limit*3)).fetchall()
            except sqlite3.OperationalError:rows=[]
        if not rows:rows=conn.execute("SELECT id chunk_id,filename,text,0 rank FROM chunks WHERE collection_id=? ORDER BY position LIMIT ?",(col["id"],limit*3)).fetchall()
    qset=set(terms);scored=[]
    for r in rows:
        text=str(r["text"]);words=set(_query_terms(text));overlap=len(qset&words)/max(1,len(qset));phrase=1.0 if query.lower() in text.lower() else 0.0;score=max(0.0,min(1.0,overlap+phrase*.5));scored.append((score,dict(r)))
    scored.sort(key=lambda x:(-x[0],float(x[1].get("rank") or 0)));hits=[]
    for idx,(score,r) in enumerate(scored[:limit],1):hits.append({"id":f"C{idx}","chunk_id":r["chunk_id"],"filename":r["filename"],"score":round(score,3),"text":r["text"][:2200]})
    return {"collection":{"id":col["id"],"name":col["name"]},"query":query,"hits":hits}


def build_rag_context(collection:str,query:str,limit:int=6)->str:
    result=search_collection(collection,query,limit);blocks=[f"[{h['id']}] {h['filename']}\n{h['text']}" for h in result["hits"]];return f"Collection: {result['collection']['name']}\nQuestion: {query}\n\n"+"\n\n---\n\n".join(blocks)


def route_collection_command(message:str)->dict[str,Any]|None:
    text=" ".join(message.strip().split());lower=text.lower()
    m=re.match(r"^(?:create|make|add)\s+(?:a\s+)?collection(?:\s+called|\s+named)?\s+(.+)$",text,re.I)
    if m:
        item,created=create_collection(m.group(1).strip(' \"“”'));return {"message":f"{'Created' if created else 'Reused existing'} collection “{item['name']}”.","card":{"type":"collection","duplicate_prevented":not created,**item}}
    if lower in {"collections","show collections","list collections","my collections"}:
        items=list_collections();return {"message":f"You have {len(items)} collection(s).","card":{"type":"collections","items":items}}
    m=re.match(r"^(?:add|index)\s+(?:file\s+)?(.+?)\s+(?:to|into)\s+(?:collection\s+)?(.+)$",text,re.I)
    if m:
        try:info=index_file(m.group(2).strip(' \"“”'),m.group(1).strip(' \"“”'))
        except Exception as exc:return {"message":f"Could not index that file: {exc}","card":None}
        return {"message":f"Indexed {info['filename']} into {info['collection']}.","card":{"type":"collection_index",**info}}
    m=re.match(r"^(?:search|find in|ask)\s+(?:collection\s+)?(.+?)\s+(?:for|about|:)\s+(.+)$",text,re.I)
    if m:
        try:result=search_collection(m.group(1).strip(' \"“”'),m.group(2).strip(),6)
        except Exception as exc:return {"message":str(exc),"card":None}
        return {"message":f"Found {len(result['hits'])} relevant passage(s).","card":{"type":"collection_search",**result}}
    return None
