from __future__ import annotations

import re
from pathlib import Path

from agentie.core.agent_registry import get_agent


def creator_from_session(session_id: str | None) -> str:
    match=re.match(r"^agent:(agt_[a-z0-9]+):",str(session_id or ""),re.I)
    if not match:return "Agentie"
    agent=get_agent(match.group(1))
    return str((agent or {}).get("name") or "Agentie").strip() or "Agentie"


def _slug(value: str, limit: int = 44) -> str:
    text=re.sub(r"[^A-Za-z0-9._ -]+","-",str(value or "")).strip(" .-_\t")
    text=re.sub(r"\s+","-",text)
    text=re.sub(r"-+","-",text)
    return text[:limit].strip("-_") or "file"


def artifact_filename(creator: str, explicit_name: str | None, suffix: str, kind: str) -> str:
    suffix=suffix if suffix.startswith(".") else "."+suffix
    owner=_slug(creator,24)
    if explicit_name:
        base=Path(str(explicit_name).strip()).name
        if base.lower().endswith(suffix.lower()):base=base[:-len(suffix)]
        base=_slug(base,58)
        if base.lower().startswith(owner.lower()+"-"):return f"{base}{suffix}"
        return f"{owner}-{base}{suffix}"
    label=_slug(kind,24)
    return f"{owner}-Agentie-{label}{suffix}"
