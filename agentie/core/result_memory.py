from __future__ import annotations

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


def resolve_result_reference(session_id: str, user_message: str) -> str | None:
    text=re.sub(r"\s+"," ",str(user_message or "").strip()).lower();last30=r"(?:last\s*30\s*days?|last30days|30[- ]?days?)";research_word=r"(?:research|search(?:e|es|ed)?|result|report|findings?)"
    if re.search(rf"\b{last30}\b.*\b{research_word}\b|\b{research_word}\b.*\b{last30}\b",text):return result_content(_last(session_id,{"last30days"}))
    if re.search(r"\b(?:team job|team result|collaboration|handoff result|agents? working)\b",text):return result_content(_last(session_id,{"team_job"}))
    if re.search(r"\b(?:research|research result|research findings|research report)\b",text):
        item=_last(session_id,{"last30days","web_search","deep_research","research"})
        if item:return result_content(item)
    return None
