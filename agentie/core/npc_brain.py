from __future__ import annotations
import re
from difflib import get_close_matches
from typing import Any
from agentie.core.agent_prompt import get_instruction_profile,learn_from_user_message
from agentie.core.memory_store import latest_assistant_text,recent_messages,set_context

_ACKS={
    "got it":"Got it.","understood":"Understood.","okay":"Okay.","ok":"Okay.","sure":"Sure.",
    "yes":"Got it.","no":"Okay.","thanks":"You’re welcome.","thank you":"You’re welcome.",
    "hi":"Hi. What would you like to work on?","hello":"Hello. What would you like to work on?",
    "hey":"Hey. What would you like to work on?","how are you":"I’m ready and working normally. What would you like to do?",
    "can you help me":"Yes. Tell me what you want to accomplish.","are you there":"Yes. I’m here.",
}

ROLE_PROFILES={
    "coding":{"roles":{"cto","developer","coder","engineer","programmer","software engineer","technical lead"},"focus":"engineering"},
    "research":{"roles":{"researcher","analyst","market researcher","research analyst"},"focus":"research"},
    "writing":{"roles":{"writer","content writer","content creator","copywriter","social media manager","document writer"},"focus":"writing"},
    "planning":{"roles":{"ceo","manager","chief of staff","planner","project manager","operations manager"},"focus":"planning"},
    "critique":{"roles":{"critic","reviewer","risk reviewer"},"focus":"critique and risk review"},
    "verification":{"roles":{"verifier","fact checker","qa verifier","quality verifier"},"focus":"verification"},
    "data":{"roles":{"data analyst","business analyst","analytics specialist"},"focus":"data analysis"},
}

def _normalized(text):
    value=str(text or "").casefold().strip();value=value.replace("what's","what is").replace("whats","what is")
    value=re.sub(r"[^a-z0-9 ]+"," ",value);return re.sub(r"\s+"," ",value).strip()

def role_profile(agent):
    role=_normalized(agent.get("role"));joined=" ".join(_normalized(agent.get(k)) for k in ("role","name","purpose","base"));best=(0,"general")
    for kind,p in ROLE_PROFILES.items():
        score=(5 if role in p["roles"] else 0)+sum(1 for r in p["roles"] if r and r in joined)
        if score>best[0]:best=(score,kind)
    return best[1]

def _adapt(agent,message):
    p=get_instruction_profile(agent);comm=p.get("communication") or {};manual=_normalized(p.get("manual_instructions"));text=str(message)
    if comm.get("default_length")=="concise" and len(text)>220:text=text.split(". ")[0].rstrip(".")+"."
    if comm.get("tone")=="formal":text=text.replace("I’m","I am").replace("I’ll","I will")
    if "concise" in manual or "short replies" in manual:
        if len(text)>220:text=text[:217].rstrip()+"..."
    return text

def _result(agent,message,kind,confidence=.95,**extra):
    return {"message":_adapt(agent,message),"routed_by":"npc_brain","npc_role":kind,"confidence":confidence,**extra}

def _escalate(agent,message,kind,confidence=.55):
    return {"escalate_message":message,"routed_by":"npc_context","npc_role":kind,"confidence":confidence}

def _preference_statement(message):
    low=_normalized(message)
    if not low:return False
    if re.search(r"\b(?:this time|this one|for this|just this|only this|right now|today only)\b",low):return False
    explicit=bool(re.search(r"\b(?:i prefer|i like|i want|from now on|always|whenever|usually|in general|my preference)\b",low))
    known=bool(re.search(r"\b(?:repl(?:y|ies)|answers?|responses?|reports?|analysis|research|bullets?|lists?|formal|casual|friendly|conversational|commands?|code|copyable|copy and paste|implementation)\b",low))
    directive=bool(re.match(r"^(?:always|from now on|whenever|when you|keep|use|avoid|prefer|give|make)\b",low))
    return (explicit and known) or (directive and known)

def _shorten(text,max_chars=180):
    clean=" ".join(str(text or "").split())
    if len(clean)<=max_chars:return clean
    sentences=re.split(r"(?<=[.!?])\s+",clean);out=[];size=0
    for sentence in sentences:
        if out and size+len(sentence)+1>max_chars:break
        out.append(sentence);size+=len(sentence)+1
    if out:return " ".join(out)[:max_chars].rstrip()
    return clean[:max_chars-3].rstrip()+"..."

def _contextual_followup(agent,message,session_id):
    if not session_id:return None
    norm=_normalized(message);kind=role_profile(agent);latest=latest_assistant_text(session_id,4000)
    if not latest:return None
    if re.fullmatch(r"(?:make (?:it|that) (?:shorter|short|concise)|shorter|make it brief|brief version|summarize that briefly)",norm):
        return _result(agent,_shorten(latest),kind,.98,context_action="shorten_previous")
    if re.fullmatch(r"(?:repeat that|say that again|repeat it|show that again)",norm):
        return _result(agent,latest,kind,.99,context_action="repeat_previous")
    if re.fullmatch(r"(?:what do you mean|what did you mean|explain that simply)",norm):
        return _result(agent,"In simpler terms: "+_shorten(latest,220),kind,.9,context_action="clarify_previous")
    if re.fullmatch(r"(?:do that|do it|go ahead|go ahead with that|proceed with that|continue with that|the second one|second one|use the second one|the first one|first one|use the first one)",norm):
        history=recent_messages(session_id,limit=6,max_chars=5000);context=[]
        for item in history[-5:]:context.append(("User" if item.get("role")=="user" else "Assistant")+": "+str(item.get("content") or ""))
        if context:
            expanded="Resolve the user's follow-up using the immediately preceding conversation. The user said: "+message+"\n\nRecent context:\n"+"\n".join(context)
            set_context(session_id,"npc_last_followup",{"message":message,"kind":"context_reference"})
            return _escalate(agent,expanded,kind,.72)
    return None

def _role_local_response(agent,message):
    kind=role_profile(agent);norm=_normalized(message);words=set(norm.split())
    if kind=="general" or not norm:return None
    if re.fullmatch(r"(?:what is|what s) your role",norm):return _result(agent,f"I’m your {agent.get('role') or kind} agent. I focus on {ROLE_PROFILES[kind]['focus']} work and hand off tasks that belong to another specialist.",kind)
    if re.fullmatch(r"(?:what are|what re|what is) you working on",norm):return _result(agent,f"I’m ready for the next {ROLE_PROFILES[kind]['focus']} task. If it needs another specialty, I’ll route it instead of pretending it is mine.",kind)
    checklist=("checklist" in words or re.search(r"\b(?:how should|how do we|how do i)\b",norm))
    if kind=="coding" and checklist and re.search(r"\b(?:test|debug|deploy|build|implement|release|code|engineering)\b",norm):return _result(agent,"Engineering checklist: reproduce or define the goal, inspect the existing implementation, make the smallest safe change, run targeted tests, then run the full regression suite before deployment.",kind)
    if kind=="research" and checklist and re.search(r"\b(?:research|investigate|compare|verify|sources?)\b",norm):return _result(agent,"Research checklist: define the question, gather multiple credible sources, compare claims and dates, note disagreements, then summarize findings with evidence and uncertainty.",kind)
    if kind=="writing" and checklist and re.search(r"\b(?:writing|content|post|article|copy|document)\b",norm):return _result(agent,"Content checklist: define the audience and goal, lead with one clear idea, keep the wording on-brand, remove filler, then finish with the intended action or takeaway.",kind)
    if kind=="planning" and checklist and re.search(r"\b(?:plan|launch|project|roadmap|organize|strategy)\b",norm):return _result(agent,"Planning checklist: define the outcome, identify constraints, break work into owners and milestones, order dependencies, then track risks and next actions.",kind)
    if kind=="critique" and checklist:return _result(agent,"Critique checklist: identify the intended goal, test assumptions, look for contradictions and failure modes, rank the biggest risks, then suggest the smallest improvements that address them.",kind)
    if kind=="verification" and checklist:return _result(agent,"Verification checklist: define the claim or expected result, reproduce the evidence, check independent signals, flag anything unsupported, then state what is verified, uncertain, or false.",kind)
    if kind=="data" and checklist:return _result(agent,"Data-analysis checklist: define the decision question, inspect data quality, choose the relevant measures, calculate reproducibly, compare segments or periods, then report the result with assumptions and limitations.",kind)
    return None

def try_npc_response(agent,message,session_id=None):
    """Return a confident local response, a context-enriched escalation, or None.

    Local answers are deliberately conservative. Complex/open-ended generation is
    escalated rather than faked by the lightweight NPC layer.
    """
    learned=learn_from_user_message(agent,message)
    if learned:return _result(agent,"Got it. I’ll remember that for how I work with you.",role_profile(agent),.99,learned=learned)
    if _preference_statement(message):return _result(agent,"Got it. I already have that preference and I’ll keep following it.",role_profile(agent),.99)
    contextual=_contextual_followup(agent,message,session_id)
    if contextual is not None:return contextual
    norm=_normalized(message)
    if not norm:return None
    if len(norm.split())<=12:
        if norm in _ACKS:return _result(agent,_ACKS[norm],role_profile(agent),.99)
        hit=get_close_matches(norm,list(_ACKS),n=1,cutoff=.86)
        if hit:return _result(agent,_ACKS[hit[0]],role_profile(agent),.92)
        if re.fullmatch(r"(?:are you|you) (?:there|ready|working)",norm):return _result(agent,"Yes. I’m ready.",role_profile(agent),.99)
        # "continue" alone is ambiguous: preserve context but let the larger brain
        # execute the actual continuation instead of pretending locally.
        if re.fullmatch(r"(?:continue|go on|proceed|carry on)",norm) and session_id:
            history=recent_messages(session_id,limit=5,max_chars=4000)
            if history:
                context="\n".join(("User" if x["role"]=="user" else "Assistant")+": "+x["content"] for x in history[-4:])
                return _escalate(agent,"Continue the current task from this recent context without restarting it:\n"+context,role_profile(agent),.7)
    return _role_local_response(agent,message)
