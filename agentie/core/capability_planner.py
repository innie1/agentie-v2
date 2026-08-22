from __future__ import annotations

import re
from typing import Any

from agentie.core.agent_builder import draft_agent_spec
from agentie.core.agent_matching import rank_agents


def analyze_capability_gap(goal:str,limit:int=4)->dict[str,Any]:
    goal=" ".join(str(goal or "").strip().split())[:5000]
    if not goal:raise ValueError("Describe the work or goal to analyze.")
    ranked=rank_agents(goal,limit=max(1,limit));matches=[]
    for row in ranked:
        agent=row.get("agent") if isinstance(row,dict) else None
        score=float(row.get("score") or 0) if isinstance(row,dict) else 0
        if agent:matches.append({"id":agent["id"],"name":agent["name"],"job":agent.get("role"),"score":round(score,3),"can_delegate":bool((agent.get("permissions") or {}).get("delegate"))})
    best=matches[0] if matches else None
    covered=bool(best and float(best.get("score") or 0)>=0.22)
    draft=None if covered else draft_agent_spec(goal)
    return {"goal":goal,"covered":covered,"best_match":best,"matches":matches,"suggested_agent":draft,"recommendation":"use_existing" if covered else "consider_new_agent"}
def _note(result:dict[str,Any])->dict[str,Any]:
    lines=[f"Goal: {result['goal']}"]
    if result.get("covered"):
        best=result.get("best_match") or {};lines.extend(["",f"Best existing owner: {best.get('name')} · {best.get('job') or 'configured agent'}",f"Match score: {best.get('score')}","Recommendation: use the existing agent before creating another one."])
    else:
        draft=result.get("suggested_agent") or {};lines.extend(["","No existing agent is a strong enough configured match.",f"Suggested job: {draft.get('job') or 'New work owner'}","Recommendation: review this draft and create a new agent only if you want a separate ownership boundary."])
        skills=[str(x.get("name") or x.get("id")) for x in draft.get("skills") or []]
        plugins=[str(x.get("name") or x.get("id")) for x in draft.get("plugins") or []]
        if skills:lines.append("Suggested capabilities: "+", ".join(skills[:6]))
        if plugins:lines.append("Suggested connections: "+", ".join(plugins[:6]))
    if len(result.get("matches") or [])>1:
        lines.extend(["","Other possible owners:"]+[f"- {x['name']} · {x.get('job') or ''} · score {x.get('score')}" for x in result['matches'][1:4]])
    return {"type":"note","title":"Capability gap analysis","content":"\n".join(lines)}
def route_capability_gap_command(message:str)->dict[str,Any]|None:
    text=" ".join(str(message or "").strip().split())
    patterns=[r"^(?:do|would)\s+(?:we|i)\s+need\s+(?:another|a new)\s+agent\s+(?:for|to)\s+(.+)$",r"^(?:who|which agent)\s+should\s+(?:handle|own|do)\s+(.+)$",r"^(?:find|show|analyze|analyse)\s+(?:the\s+)?capability\s+gaps?\s+(?:for|in)\s+(.+)$",r"^(?:should i hire|should we create)\s+(?:an?\s+)?agent\s+(?:for|to)\s+(.+)$"]
    m=next((re.match(p,text,re.I) for p in patterns if re.match(p,text,re.I)),None)
    if not m:return None
    try:result=analyze_capability_gap(m.group(1).strip(' .?!\"“”'))
    except ValueError as exc:return {"message":str(exc),"card":None}
    if result["covered"]:message=f"Use {result['best_match']['name']} first; an additional agent is not justified by the current configuration."
    else:message="There is a capability/ownership gap. I prepared a suggested agent configuration for review, but I did not create anything automatically."
    return {"message":message,"card":_note(result),"analysis":result}
