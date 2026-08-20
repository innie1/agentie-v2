from __future__ import annotations

import re
from difflib import get_close_matches
from typing import Any

from agentie.core.agent_prompt import learn_from_user_message


_ACKS={
    "got it":"Got it.","understood":"Understood.","okay":"Okay.","ok":"Okay.","sure":"Sure.",
    "yes":"Got it.","no":"Okay.","thanks":"You’re welcome.","thank you":"You’re welcome.",
    "hi":"Hi. What would you like to work on?","hello":"Hello. What would you like to work on?","hey":"Hey. What would you like to work on?",
}

ROLE_PROFILES={
    "coding":{
        "roles":{"cto","developer","coder","engineer","programmer","software engineer","technical lead"},
        "focus":"engineering",
        "keywords":{"code","bug","debug","test","tests","github","deploy","architecture","api","database","frontend","backend","implementation"},
    },
    "research":{
        "roles":{"researcher","analyst","market researcher","research analyst"},
        "focus":"research",
        "keywords":{"research","compare","sources","evidence","competitor","market","investigate","verify","findings"},
    },
    "writing":{
        "roles":{"writer","content writer","content creator","copywriter","social media manager"},
        "focus":"writing",
        "keywords":{"write","post","caption","script","copy","blog","headline","content","rewrite"},
    },
    "planning":{
        "roles":{"ceo","manager","chief of staff","planner","project manager","operations manager"},
        "focus":"planning",
        "keywords":{"plan","roadmap","priority","priorities","organize","coordinate","delegate","launch","strategy","next steps"},
    },
}


def _normalized(text:str)->str:
    value=text.casefold().strip();value=re.sub(r"[^a-z0-9 ]+"," ",value);return re.sub(r"\s+"," ",value).strip()


def role_profile(agent:dict[str,Any])->str:
    role=_normalized(str(agent.get("role") or ""));name=_normalized(str(agent.get("name") or ""));purpose=_normalized(str(agent.get("purpose") or ""));base=_normalized(str(agent.get("base") or ""))
    joined=f"{role} {name} {purpose} {base}"
    best=(0,"general")
    for kind,profile in ROLE_PROFILES.items():
        score=4 if role in profile["roles"] else 0
        score+=sum(1 for r in profile["roles"] if r and r in joined)
        if score>best[0]:best=(score,kind)
    return best[1]


def _task_words(message:str)->set[str]:return set(_normalized(message).split())


def _role_local_response(agent:dict[str,Any],message:str)->dict[str,Any]|None:
    """Small role-aware reasoning templates. Only answer when intent is narrow and deterministic."""
    kind=role_profile(agent);norm=_normalized(message);words=_task_words(message)
    if kind=="general" or not norm:return None

    if re.fullmatch(r"(?:what is|whats|what s) your role",norm):
        return {"message":f"I’m your {agent.get('role') or kind} agent. I focus on {ROLE_PROFILES[kind]['focus']} work and hand off tasks that belong to another specialist.","routed_by":"npc_brain","npc_role":kind}
    if re.fullmatch(r"(?:what are|whats|what s) you working on",norm):
        return {"message":f"I’m ready for the next {ROLE_PROFILES[kind]['focus']} task. If it needs another specialty, I’ll route it instead of pretending it is mine.","routed_by":"npc_brain","npc_role":kind}

    if kind=="coding" and ("checklist" in words or re.search(r"\b(?:how should|how do we) (?:test|debug|deploy)\b",norm)):
        return {"message":"Engineering checklist: reproduce the issue, inspect the existing implementation first, make the smallest safe change, run targeted tests, then run the full regression suite before deployment.","routed_by":"npc_brain","npc_role":kind}
    if kind=="research" and ("checklist" in words or re.search(r"\bhow should (?:i|we) research\b",norm)):
        return {"message":"Research checklist: define the question, gather multiple credible sources, compare claims and dates, note disagreements, then summarize findings with evidence and uncertainty.","routed_by":"npc_brain","npc_role":kind}
    if kind=="writing" and re.search(r"\b(?:writing|content|post) checklist\b",norm):
        return {"message":"Content checklist: define the audience and goal, lead with one clear idea, keep the wording on-brand, remove filler, then finish with the intended action or takeaway.","routed_by":"npc_brain","npc_role":kind}
    if kind=="planning" and ("checklist" in words or re.search(r"\b(?:how should|how do we) plan\b",norm)):
        return {"message":"Planning checklist: define the outcome, identify constraints, break work into owners and milestones, order the dependencies, then track risks and next actions.","routed_by":"npc_brain","npc_role":kind}
    return None


def try_npc_response(agent:dict[str,Any],message:str)->dict[str,Any]|None:
    """Cheap deterministic local brain: learns preferences, chats lightly, then uses role-specific local reasoning before provider fallback."""
    learned=learn_from_user_message(agent,message)
    if learned:
        return {"message":"Got it. I’ll remember that for how I work with you.","routed_by":"npc_brain","learned":learned}
    norm=_normalized(message)
    if not norm:return None
    if len(norm.split())<=10:
        if norm in _ACKS:return {"message":_ACKS[norm],"routed_by":"npc_brain","npc_role":role_profile(agent)}
        hit=get_close_matches(norm,list(_ACKS),n=1,cutoff=.88)
        if hit:return {"message":_ACKS[hit[0]],"routed_by":"npc_brain","npc_role":role_profile(agent)}
        if re.fullmatch(r"(?:are you|you) (?:there|ready)",norm):return {"message":"Yes. I’m ready.","routed_by":"npc_brain","npc_role":role_profile(agent)}
        if re.fullmatch(r"(?:continue|go on|proceed|carry on)",norm):return {"message":"Okay. I’ll continue from the current task context.","routed_by":"npc_brain","npc_role":role_profile(agent)}
    return _role_local_response(agent,message)
