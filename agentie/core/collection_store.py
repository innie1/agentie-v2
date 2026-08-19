from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from agentie.core.embedding_engine import backend_name, cosine, embed_many, embed_text
from agentie.core.file_service import UPLOADS, ensure_dirs

WORKSPACE=Path.cwd()/"workspace"
DB_PATH=WORKSPACE/"agentie_collections.sqlite3"
SUPPORTED={".pdf",".csv",".json",".yaml",".yml",".txt",".md",".py",".js",".html",".css",".toml",".ini",".log"}
MAX_INDEX_CHARS=2_000_000


def _now()->str:return datetime.now().astimezone().isoformat(timespec="seconds")
def _connect()->sqlite3.Connection:
    WORKSPACE.mkdir(parents=True,exist_ok=True);c=sqlite3.connect(DB_PATH,timeout=10);c.row_factory=sqlite3.Row;return c

def init_db()->None:
    with _connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS collections(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE COLLATE NOCASE,description TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,collection_id TEXT NOT NULL,filename TEXT NOT NULL,source_path TEXT NOT NULL,indexed_at TEXT NOT NULL,chars INTEGER NOT NULL DEFAULT 0,UNIQUE(collection_id,filename));
        CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY,document_id TEXT NOT NULL,collection_id TEXT NOT NULL,filename TEXT NOT NULL,position INTEGER NOT NULL,text TEXT NOT NULL,embedding_json TEXT);
        CREATE INDEX IF NOT EXISTS idx_chunks_collection ON chunks(collection_id,position);
        """)
        cols={str(r[1]) for r in c.execute("PRAGMA table_info(chunks)").fetchall()}
        if "embedding_json" not in cols:c.execute("ALTER TABLE chunks ADD COLUMN embedding_json TEXT")
        try:c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, collection_id UNINDEXED, filename UNINDEXED, text, tokenize='porter unicode61')")
        except sqlite3.OperationalError:pass

def _slug(text:str)->str:return re.sub(r"\s+"," ",str(text or "").strip())
def create_collection(name:str,description:str=""):
    init_db();clean=_slug(name)
    if not clean:raise ValueError("Collection name is required.")
    with _connect() as c:
        row=c.execute("SELECT * FROM collections WHERE name=? COLLATE NOCASE",(clean,)).fetchone()
        if row:return dict(row),False
        cid=uuid.uuid4().hex[:10];now=_now();c.execute("INSERT INTO collections(id,name,description,created_at,updated_at) VALUES(?,?,?,?,?)",(cid,clean[:120],description[:1000],now,now));row=c.execute("SELECT * FROM collections WHERE id=?",(cid,)).fetchone()
    return dict(row),True

def list_collections()->list[dict[str,Any]]:
    init_db()
    with _connect() as c:rows=c.execute("SELECT c.*,COUNT(d.id) document_count FROM collections c LEFT JOIN documents d ON d.collection_id=c.id GROUP BY c.id ORDER BY c.updated_at DESC").fetchall()
    return [dict(r) for r in rows]
def find_collection(name_or_id:str):
    init_db();q=_slug(name_or_id)
    with _connect() as c:
        row=c.execute("SELECT * FROM collections WHERE id=? OR name=? COLLATE NOCASE",(q,q)).fetchone()
        if row:return dict(row)
        row=c.execute("SELECT * FROM collections WHERE name LIKE ? COLLATE NOCASE ORDER BY updated_at DESC LIMIT 1",(f"%{q}%",)).fetchone()
    return dict(row) if row else None

def _read_index_text(path:Path)->str:
    if path.suffix.lower()==".pdf":
        parts=[];total=0
        for page in PdfReader(str(path)).pages[:500]:
            text=page.extract_text() or "";parts.append(text);total+=len(text)
            if total>=MAX_INDEX_CHARS:break
        return "\n\n".join(parts)[:MAX_INDEX_CHARS]
    return path.read_text(encoding="utf-8-sig",errors="replace")[:MAX_INDEX_CHARS]
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
    text=_read_index_text(path);pieces=_chunks(text)
    if not pieces:raise ValueError("No indexable text was found in that file.")
    vectors=embed_many(pieces);doc_id=uuid.uuid4().hex[:12]
    with _connect() as c:
        old=c.execute("SELECT id FROM documents WHERE collection_id=? AND filename=?",(col["id"],path.name)).fetchone()
        if old:
            old_id=str(old["id"]);old_chunks=[str(r["id"]) for r in c.execute("SELECT id FROM chunks WHERE document_id=?",(old_id,)).fetchall()]
            if old_chunks:
                try:c.executemany("DELETE FROM chunks_fts WHERE chunk_id=?",[(x,) for x in old_chunks])
                except sqlite3.OperationalError:pass
            c.execute("DELETE FROM chunks WHERE document_id=?",(old_id,));c.execute("DELETE FROM documents WHERE id=?",(old_id,))
        c.execute("INSERT INTO documents(id,collection_id,filename,source_path,indexed_at,chars) VALUES(?,?,?,?,?,?)",(doc_id,col["id"],path.name,str(path),_now(),len(text)))
        for pos,(piece,vector) in enumerate(zip(pieces,vectors)):
            cid=f"{doc_id}:{pos}";c.execute("INSERT INTO chunks(id,document_id,collection_id,filename,position,text,embedding_json) VALUES(?,?,?,?,?,?,?)",(cid,doc_id,col["id"],path.name,pos,piece,json.dumps(vector)))
            try:c.execute("INSERT INTO chunks_fts(chunk_id,collection_id,filename,text) VALUES(?,?,?,?)",(cid,col["id"],path.name,piece))
            except sqlite3.OperationalError:pass
        c.execute("UPDATE collections SET updated_at=? WHERE id=?",(_now(),col["id"]))
    return {"collection":col["name"],"collection_id":col["id"],"filename":path.name,"chunks":len(pieces),"chars":len(text),"embedding_backend":backend_name()}

def _query_terms(query:str)->list[str]:return [w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{1,}",query.lower()) if w not in {"the","a","an","of","to","in","for","and","or","is","are","this","that","what","how","why"}][:24]

def _ensure_vectors(rows:list[sqlite3.Row])->dict[str,list[float]]:
    missing=[];ids=[];out={}
    for r in rows:
        raw=r["embedding_json"] if "embedding_json" in r.keys() else None
        if raw:
            try:out[str(r["id"])]=json.loads(raw);continue
            except Exception:pass
        ids.append(str(r["id"]));missing.append(str(r["text"]))
    if missing:
        vectors=embed_many(missing)
        with _connect() as c:
            for cid,vector in zip(ids,vectors):
                out[cid]=vector;c.execute("UPDATE chunks SET embedding_json=? WHERE id=?",(json.dumps(vector),cid))
    return out

def search_collection(collection:str,query:str,limit:int=6)->dict[str,Any]:
    init_db();col=find_collection(collection)
    if not col:raise ValueError("Collection not found.")
    limit=max(1,min(int(limit),12));terms=_query_terms(query);qset=set(terms);qvec=list(embed_text(query));lexical_ids=[];bm25_map={}
    with _connect() as c:
        if terms:
            fts_query=" OR ".join(f'"{t}"' for t in terms)
            try:
                frows=c.execute("SELECT chunk_id,bm25(chunks_fts) rank FROM chunks_fts WHERE collection_id=? AND chunks_fts MATCH ? ORDER BY rank LIMIT ?",(col["id"],fts_query,max(30,limit*6))).fetchall()
                lexical_ids=[str(r["chunk_id"]) for r in frows];bm25_map={str(r["chunk_id"]):float(r["rank"] or 0) for r in frows}
            except sqlite3.OperationalError:pass
        rows=c.execute("SELECT id,filename,position,text,embedding_json FROM chunks WHERE collection_id=? ORDER BY position LIMIT 5000",(col["id"],)).fetchall()
    vectors=_ensure_vectors(rows);scored=[]
    for r in rows:
        cid=str(r["id"]);body=str(r["text"]);words=set(_query_terms(body));lexical=len(qset&words)/max(1,len(qset));phrase=1.0 if query.lower() in body.lower() else 0.0;semantic=max(0.0,cosine(qvec,vectors.get(cid,[])))
        fts_bonus=0.12 if cid in bm25_map else 0.0
        score=0.60*semantic+0.25*lexical+0.10*phrase+fts_bonus
        if score>0.04:scored.append((score,semantic,lexical,dict(r)))
    scored.sort(key=lambda x:x[0],reverse=True);hits=[];seen_files={}
    for score,semantic,lexical,r in scored:
        filename=str(r["filename"]);seen_files[filename]=seen_files.get(filename,0)+1
        if seen_files[filename]>3 and len(scored)>limit:continue
        hits.append({"id":f"C{len(hits)+1}","chunk_id":r["id"],"filename":filename,"position":r["position"],"score":round(score,3),"semantic_score":round(semantic,3),"lexical_score":round(lexical,3),"text":r["text"][:2600]})
        if len(hits)>=limit:break
    return {"collection":{"id":col["id"],"name":col["name"]},"query":query,"retrieval":"hybrid","embedding_backend":backend_name(),"hits":hits}
def build_rag_context(collection:str,query:str,limit:int=6)->str:
    result=search_collection(collection,query,limit);blocks=[f"[{h['id']}] {h['filename']} · chunk {h.get('position',0)} · score {h['score']}\n{h['text']}" for h in result["hits"]];return f"Collection: {result['collection']['name']}\nQuestion: {query}\nRetrieval: {result.get('retrieval')} / {result.get('embedding_backend')}\n\n"+"\n\n---\n\n".join(blocks)
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
        return {"message":f"Indexed {info['filename']} into {info['collection']} using {info['embedding_backend']} retrieval vectors.","card":{"type":"collection_index",**info}}
    m=re.match(r"^(?:search|find in|ask)\s+(?:collection\s+)?(.+?)\s+(?:for|about|:)\s+(.+)$",text,re.I)
    if m:
        try:result=search_collection(m.group(1).strip(' \"“”'),m.group(2).strip(),6)
        except Exception as exc:return {"message":str(exc),"card":None}
        return {"message":f"Found {len(result['hits'])} relevant passage(s) with hybrid retrieval.","card":{"type":"collection_search",**result}}
    return None
