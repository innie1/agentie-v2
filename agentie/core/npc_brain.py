from __future__ import annotations
import re
from difflib import get_close_matches
from typing import Any
from agentie.core.agent_prompt import get_instruction_profile,learn_from_user_message
_ACKS={"got it":"Got it.","understood":"Understood.","okay":"Okay.","ok":"Okay.","sure":"Sure.","yes":"Got it.","no":"Okay.","thanks":"You’re welcome.","thank you":"You’re welcome.","hi":"Hi. What would you like to work on?","hello":"Hello. What would you like to work on?","hey":"Hey. What would you like to work on?"}
ROLE_PROFILES={"coding":{"roles":{"cto","developer","coder","engineer","programmer","software engineer","technical lead"},"focus":"engineering"},"research":{"roles":{"researcher","analyst","market researcher","research analyst"},"focus":"research"},"writing":{"roles":{"writer","content writer","content creator","copywriter","social media manager"},"focus":"writing"},"planning":{"roles":{"ceo","manager","chief of staff","planner","project manager","operations manager"},"focus":"planning"}}
def _normalized(text):
    value=str(text or "").casefold().strip();value=re.sub(r"[^a-z0-9 ]+"," ",value);return re.sub(r"\s+"," ",value).strip()
def role_profile(agent):
    role=_normalized(agent.get("role"));joined=" ".join(_normalized(agent.get(k)) for k in ("role","name","purpose","base"));best=(0,"general")
    for kind,p in ROLE_PROFILES.items():
        score=(4 if role in p["roles"] else 0)+sum(1 for r in p["roles"] if r and r in joined)
        if score>best[0]:best=(score,kind)
    return best[1]
def _adapt(agent,message):
    p=get_instruction_profile(agent);comm=p.get("communication") or {};manual=_normalized(p.get("manual_instructions"));text=str(message)
    if comm.get("default_length")=="concise" and len(text)>220:text=text.split(". ")[0].rstrip(".")+"."
    if comm.get("tone")=="formal":text=text.replace("I’m","I am").replace("I’ll","I will")
    if "concise" in manual or "short replies" in manual:
        if len(text)>220:text=text[:217].rstrip()+"..."
    return text
def _result(agent,message,kind):return {"message":_adapt(agent,message),"routed_by":"npc_brain","npc_role":kind}
def _role_local_response(agent,message):
    kind=role_profile(agent);norm=_normalized(message);words=set(norm.split())
    if kind=="general" or not norm:return None
    if re.fullmatch(r"(?:what is|whats|what s) your role",norm):return _result(agent,f"I’m your {agent.get('role') or kind} agent. I focus on {ROLE_PROFILES[kind]['focus']} work and hand off tasks that belong to another specialist.",kind)
    if re.fullmatch(r"(?:what are|whats|what s) you working on",norm):return _result(agent,f"I’m ready for the next {ROLE_PROFILES[kind]['focus']} task. If it needs another specialty, I’ll route it instead of pretending it is mine.",kind)
    if kind=="coding" and ("checklist" in words or re.search(r"\b(?:how should|how do we) (?:test|debug|deploy)\b",norm)):return _result(agent,"Engineering checklist: reproduce the issue, inspect the existing implementation first, make the smallest safe change, run targeted tests, then run the full regression suite before deployment.",kind)
    if kind=="research" and ("checklist" in words or re.search(r"\bhow should (?:i|we) research\b",norm)):return _result(agent,"Research checklist: define the question, gather multiple credible sources, compare claims and dates, note disagreements, then summarize findings with evidence and uncertainty.",kind)
    if kind=="writing" and re.search(r"\b(?:writing|content|post) checklist\b",norm):return _result(agent,"Content checklist: define the audience and goal, lead with one clear idea, keep the wording on-brand, remove filler, then finish with the intended action or takeaway.",kind)
    if kind=="planning" and ("checklist" in words or re.search(r"\b(?:how should|how do we) plan\b",norm)):return _result(agent,"Planning checklist: define the outcome, identify constraints, break work into owners and milestones, order the dependencies, then track risks and next actions.",kind)
    return None
def try_npc_response(agent,message):
    learned=learn_from_user_message(agent,message)
    if learned:return _result(agent,"Got it. I’ll remember that for how I work with you.",role_profile(agent))|{"learned":learned}
    norm=_normalized(message)
    if not norm:return None
    if len(norm.split())<=10:
        if norm in _ACKS:return _result(agent,_ACKS[norm],role_profile(agent))
        hit=get_close_matches(norm,list(_ACKS),n=1,cutoff=.88)
        if hit:return _result(agent,_ACKS[hit[0]],role_profile(agent))
        if re.fullmatch(r"(?:are you|you) (?:there|ready)",norm):return _result(agent,"Yes. I’m ready.",role_profile(agent))
        if re.fullmatch(r"(?:continue|go on|proceed|carry on)",norm):return _result(agent,"Okay. I’ll continue from the current task context.",role_profile(agent))
    return _role_local_response(agent,message)
