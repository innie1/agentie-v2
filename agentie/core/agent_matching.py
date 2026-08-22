from __future__ import annotations

import re
from typing import Any

from agentie.core.agent_registry import list_agents
from agentie.core.embedding_engine import cosine, embed_text
from agentie.core.mcp_client import list_servers
from agentie.core.skill_registry import all_skills

_STOP={"a","an","and","are","as","at","be","by","for","from","i","in","is","it","my","of","on","or","our","the","this","to","we","with","you","your","agent","bot","task","work"}


def _words(value:str)->set[str]:
    return {x for x in re.findall(r"[a-z0-9]+",str(value or "").casefold()) if len(x)>1 and x not in _STOP}


def agent_identity_text(agent:dict[str,Any])->str:
    """Only the user's explicit employee/job configuration, never inherited tools.

    Use this for knowledge relevance and other identity decisions where common
    capabilities must not make unrelated agents look equivalent.
    """
    parts=[agent.get("name"),agent.get("role"),agent.get("purpose"),agent.get("goal"),agent.get("personality")]
    parts.extend(agent.get("responsibilities") or [])
    return " ".join(str(x or "") for x in parts).strip()


def agent_capability_text(agent:dict[str,Any])->str:
    parts=[agent_identity_text(agent)]
    skills=all_skills()
    try:
        from agentie.core.agent_access import skill_allowed
    except Exception:
        skill_allowed=lambda _a,_sid: _sid in set(_a.get("skills") or [])
    for sid,item in skills.items():
        try:allowed=skill_allowed(agent,sid)
        except Exception:allowed=sid in set(agent.get("skills") or [])
        if allowed:
            parts.extend([item.get("name"),item.get("description")," ".join(map(str,item.get("capabilities") or []))])
    permissions=agent.get("permissions") or {}
    allowed_mcp={str(x).casefold() for x in permissions.get("mcp_servers",[]) or []}
    for server in list_servers():
        name=str(server.get("name") or "")
        if name.casefold() in allowed_mcp:parts.append(name)
    return " ".join(str(x or "") for x in parts).strip()


def _score(task:str,profile:str,delegate:bool=False)->float:
    task=str(task or "").strip()
    if not task:return 0.0
    tw,pw=_words(task),_words(profile)
    overlap=len(tw&pw)
    lexical=(overlap/max(1,len(tw))) if tw else 0.0
    phrase=0.0
    low=profile.casefold()
    for token in tw:
        if token in low:phrase+=0.025
    semantic=0.0
    try:semantic=max(0.0,cosine(embed_text(task),embed_text(profile)))
    except Exception:pass
    delegate_bonus=.03 if delegate and re.search(r"\b(coordinate|delegate|manage|organize|organise|oversee|team)\b",task,re.I) else 0.0
    return round(min(1.0,lexical*.58+semantic*.38+min(.12,phrase)+delegate_bonus),4)


def match_identity_score(task:str,agent:dict[str,Any])->float:
    return _score(task,agent_identity_text(agent),bool((agent.get("permissions") or {}).get("delegate")))


def match_score(task:str,agent:dict[str,Any])->float:
    return _score(task,agent_capability_text(agent),bool((agent.get("permissions") or {}).get("delegate")))


def rank_agents(task:str,*,exclude_id:str|None=None,limit:int=5)->list[dict[str,Any]]:
    ranked=[]
    for agent in list_agents():
        if exclude_id and str(agent.get("id"))==str(exclude_id):continue
        score=match_score(task,agent)
        if score<=0:continue
        ranked.append({"agent":agent,"score":score})
    ranked.sort(key=lambda x:(-float(x["score"]),str(x["agent"].get("name") or "").casefold()))
    return ranked[:max(1,limit)]


def best_agent(task:str,*,exclude_id:str|None=None,min_score:float=.16)->dict[str,Any]|None:
    ranked=rank_agents(task,exclude_id=exclude_id,limit=1)
    if not ranked or float(ranked[0]["score"])<min_score:return None
    return ranked[0]["agent"]


def task_signature(task:str,limit:int=5)->str:
    words=sorted(_words(task))[:max(1,limit)]
    return "-".join(words)[:100] or "general"


def coordinator_agents()->list[dict[str,Any]]:
    return [a for a in list_agents() if bool((a.get("permissions") or {}).get("delegate"))]
