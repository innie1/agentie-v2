from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

WORKSPACE = Path.cwd() / "workspace"
RESULTS_FILE = WORKSPACE / "result_memory.json"
GLOBAL_RESULTS = "__global__"
MAX_RESULTS_PER_SESSION = 60


def _load() -> dict[str, list[dict[str, Any]]]:
    try:
        value = json.loads(RESULTS_FILE.read_text(encoding="utf-8")) if RESULTS_FILE.exists() else {}
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save(data: dict[str, list[dict[str, Any]]]) -> None:
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def remember_result(session_id: str, message: str, card: dict[str, Any] | None) -> None:
    if not isinstance(card, dict):return
    card_type = str(card.get("type") or "").strip()
    if not card_type:return
    data = _load();items = data.setdefault(session_id, [])
    items.append({"type": card_type,"message": str(message or ""),"card": card,"at": datetime.now().astimezone().isoformat(timespec="seconds")})
    data[session_id] = items[-MAX_RESULTS_PER_SESSION:];_save(data)


def remember_global_result(message: str, card: dict[str, Any] | None) -> None:remember_result(GLOBAL_RESULTS, message, card)


def _last(session_id: str, wanted: set[str] | None = None) -> dict[str, Any] | None:
    data = _load()
    for bucket in (session_id, GLOBAL_RESULTS):
        for item in reversed(data.get(bucket, [])):
            if wanted is None or item.get("type") in wanted:return item
    return None


def _last30days_markdown(item: dict[str, Any]) -> str:
    card=item.get("card") or {};topic=str(card.get("topic") or "Recent research").strip();answer=str(card.get("answer") or item.get("message") or "").strip();counts=card.get("source_counts") or {};sources=card.get("sources") or [];lines=[f"# Last30Days Research: {topic}"]
    if counts:lines.extend(["",f"**Coverage:** {', '.join(f'{name}: {count}' for name,count in counts.items())}"])
    if answer:lines.extend(["",answer])
    if sources:
        lines.extend(["","## Sources"])
        for source in sources[:20]:
            sid=str(source.get("id") or "").strip();title=str(source.get("title") or source.get("url") or "Source").strip();url=str(source.get("url") or "").strip();lane=str(source.get("source") or "web").strip();prefix=f"[{sid}] " if sid else "";lines.append(f"- {prefix}{title} — {lane}"+(f" — {url}" if url else ""))
    return "\n".join(lines).strip()


def _team_markdown(item: dict[str, Any]) -> str:
    card=item.get("card") or {};lines=[f"# Team Job: {card.get('task') or 'Collaborative work'}","",f"**Status:** {card.get('status') or 'unknown'}"];agents=card.get("agents") or []
    if agents:lines.append(f"**Agents:** {', '.join(map(str,agents))}")
    final_output=str(card.get("final_output") or "").strip();lines.extend(["","## Result",final_output] if final_output else ["","The team job has not produced a final result yet."]);return "\n".join(lines)


def result_content(item: dict[str, Any] | None) -> str | None:
    if not item:return None
    kind=item.get("type")
    if kind=="last30days":return _last30days_markdown(item)
    if kind=="team_job":return _team_markdown(item)
    card=item.get("card") or {}
    for key in ("answer","final_output","content","text","summary"):
        value=card.get(key)
        if isinstance(value,str) and value.strip():return value.strip()
    message=str(item.get("message") or "").strip();return message or None


def source_fingerprint(content: str) -> str:
    clean=str(content or "").strip().encode("utf-8",errors="ignore")
    return hashlib.sha256(clean).hexdigest()[:20]


def _clean_preview(text: str) -> str:
    value=str(text or "")
    value=re.sub(r"```[\s\S]*?```"," ",value)
    value=re.sub(r"^#{1,6}\s*","",value,flags=re.M)
    value=re.sub(r"\*\*([^*]+)\*\*",r"\1",value)
    value=re.sub(r"`([^`]+)`",r"\1",value)
    value=re.sub(r"\s+"," ",value).strip(" -|#")
    return value


def _candidate_title(content: str) -> str:
    raw=str(content or "").strip()
    heading=re.search(r"^#{1,6}\s+(.+)$",raw,re.M)
    if heading:return _clean_preview(heading.group(1))[:100] or "Result"
    first=next((x.strip() for x in raw.splitlines() if x.strip()),"Result")
    return _clean_preview(first)[:100] or "Result"


def _append_typed_candidates(out:list[dict[str,Any]],seen:set[str],items:list[dict[str,Any]],limit:int)->None:
    for item in reversed(items):
        content=result_content(item)
        if not content:continue
        fid=source_fingerprint(content)
        if fid in seen:continue
        seen.add(fid);clean=_clean_preview(content)
        out.append({"id":fid,"title":_candidate_title(content),"summary":clean[:220]+("…" if len(clean)>220 else ""),"content":content,"route":str(item.get("type") or "result"),"created_at":item.get("at")})
        if len(out)>=max(1,limit):return


def list_result_candidates(session_id: str, limit: int = 8) -> list[dict[str, Any]]:
    """Return substantive result-like outputs from this exact chat, newest first; use global results only as fallback."""
    from agentie.core.memory_store import recent_messages
    seen=set();out=[]
    excluded={"local_artifact","local_pdf","project_handoff","capability_permission","observability","clarification"}
    rows=recent_messages(session_id,limit=50,max_chars=300000)
    for row in reversed(rows):
        if row.get("role")!="assistant":continue
        content=str(row.get("content") or "").strip();meta=row.get("metadata") or {};route=str(meta.get("routed_by") or "")
        if not content or route in excluded:continue
        if route!="project_handoff_result" and len(content)<120:continue
        fid=source_fingerprint(content)
        if fid in seen:continue
        seen.add(fid);clean=_clean_preview(content)
        out.append({"id":fid,"title":_candidate_title(content),"summary":clean[:220]+("…" if len(clean)>220 else ""),"content":content,"route":route or "assistant","created_at":row.get("created_at"),"team_job_id":meta.get("team_job_id"),"project_id":meta.get("project_id")})
        if len(out)>=max(1,limit):return out
    data=_load();_append_typed_candidates(out,seen,data.get(session_id,[]),limit)
    if out:return out[:max(1,limit)]
    _append_typed_candidates(out,seen,data.get(GLOBAL_RESULTS,[]),limit)
    return out[:max(1,limit)]


def resolve_candidate(session_id: str, candidate_id: str) -> str | None:
    wanted=str(candidate_id or "").strip().lower()
    return next((str(x.get("content") or "") for x in list_result_candidates(session_id,20) if str(x.get("id"))==wanted),None)


def artifact_source_picker(session_id: str, kind: str, candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows=candidates if candidates is not None else list_result_candidates(session_id)
    return {"type":"artifact_source_picker","format":str(kind).lower(),"items":[{"id":x["id"],"title":x["title"],"summary":x["summary"],"route":x.get("route"),"created_at":x.get("created_at")} for x in rows]}


def existing_artifact(session_id: str, kind: str, content: str) -> dict[str, Any] | None:
    from agentie.core.memory_store import get_context
    from agentie.core.file_service import UPLOADS
    registry=get_context(session_id,"artifact_registry",{})
    if not isinstance(registry,dict):return None
    row=registry.get(f"{str(kind).lower()}:{source_fingerprint(content)}")
    if not isinstance(row,dict):return None
    card=row.get("card") if isinstance(row.get("card"),dict) else None
    if not card:return None
    name=str(card.get("name") or card.get("filename") or "")
    if name and not (UPLOADS/name).exists():return None
    return dict(card)


def remember_artifact(session_id: str, kind: str, content: str, card: dict[str, Any]) -> None:
    from agentie.core.memory_store import get_context,set_context
    registry=get_context(session_id,"artifact_registry",{})
    if not isinstance(registry,dict):registry={}
    key=f"{str(kind).lower()}:{source_fingerprint(content)}"
    registry[key]={"source_id":source_fingerprint(content),"kind":str(kind).lower(),"card":dict(card),"created_at":datetime.now().astimezone().isoformat(timespec="seconds")}
    set_context(session_id,"artifact_registry",registry)


def resolve_result_reference(session_id: str, user_message: str) -> str | None:
    text=re.sub(r"\s+"," ",str(user_message or "").strip()).lower();last30=r"(?:last\s*30\s*days?|last30days|30[- ]?days?)";research_word=r"(?:research|search(?:e|es|ed)?|result|report|findings?)"
    selected=re.search(r"\bresult\s+([a-f0-9]{12,24})\b",text)
    if selected:
        hit=resolve_candidate(session_id,selected.group(1))
        if hit:return hit
    if re.search(r"\b(?:this|that|it|the previous answer|previous answer|last answer|above|what you just wrote|what you wrote)\b",text):
        candidates=list_result_candidates(session_id,2)
        if len(candidates)==1:return str(candidates[0].get("content") or "") or None
    if re.search(rf"\b{last30}\b.*\b{research_word}\b|\b{research_word}\b.*\b{last30}\b",text):return result_content(_last(session_id,{"last30days"}))
    if re.search(r"\b(?:team job|team result|collaboration|handoff result|agents? working)\b",text):return result_content(_last(session_id,{"team_job"}))
    if re.search(r"\b(?:research|research result|research findings|research report)\b",text):
        item=_last(session_id,{"last30days","web_search","deep_research","research"})
        if item:return result_content(item)
    return None
