from __future__ import annotations
import re
from difflib import get_close_matches
from typing import Any
from agentie.core.agent_prompt import get_instruction_profile,learn_from_user_message
from agentie.core.agent_registry import list_agents
from agentie.core.memory_store import get_context,latest_assistant_text,recent_messages,set_context

_ACKS={
    "got it":"Got it.","understood":"Understood.","okay":"Okay.","ok":"Okay.","sure":"Sure.",
    "yes":"Got it.","no":"Okay.","thanks":"You’re welcome.","thank you":"You’re welcome.",
    "hi":"Hi. What would you like to work on?","hello":"Hello. What would you like to work on?",
    "hey":"Hey. What would you like to work on?","how are you":"I’m ready and working normally. What would you like to do?",
    "can you help me":"Yes. Tell me what you want to accomplish.","are you there":"Yes. I’m here.",
}

# Local deterministic response profiles are capability behaviors, not employee
# classes. A title such as CTO, Researcher or Chief of Staff does not select one.
_CAPABILITY_FOCUS={"coding":"engineering","research":"research","planning":"planning"}

def _normalized(text):
    value=str(text or "").casefold().strip();value=value.replace("what's","what is").replace("whats","what is")
    value=re.sub(r"[^a-z0-9 ]+"," ",value);return re.sub(r"\s+"," ",value).strip()

def job_title(goal,max_words=8):
    """Create a short human title locally for a job without spending a provider call."""
    original=re.sub(r"\s+"," ",str(goal or "")).strip(" .?!:-")
    if not original:return "Agent Job"
    clean=re.sub(r"^(?:please\s+)?(?:delegate|start|run|do|perform|research|investigate|analy[sz]e|build|implement|create|make|write|generate|prepare|compare|find)\s+(?:this\s+|a\s+|an\s+|the\s+)?","",original,flags=re.I)
    words=re.findall(r"[A-Za-z0-9][A-Za-z0-9.+#/-]*",clean)
    stop={"a","an","the","and","then","to","for","of","on","in","with","using","please","this","that","it","job","task","write","create","make","generate","prepare","research","investigate","analyze","analyse","build","implement","compare","find"}
    chosen=[]
    for word in words:
        if word.casefold() in stop:continue
        chosen.append(word)
        if len(chosen)>=max_words:break
    low=original.casefold();suffix=None
    if re.search(r"\b(slide deck|slides|presentation|pptx)\b",low):suffix="Presentation"
    elif re.search(r"\b(pdf|report)\b",low):suffix="Report"
    elif re.search(r"\b(docx|word document|document)\b",low):suffix="Document"
    elif re.search(r"\b(test|tests|verify|verification|qa)\b",low):suffix="Verification"
    acronyms={"ai":"AI","api":"API","ui":"UI","ux":"UX","pdf":"PDF","csv":"CSV","json":"JSON","github":"GitHub","sql":"SQL","seo":"SEO","mcp":"MCP"}
    display=[]
    for word in chosen:
        key=word.casefold();display.append(acronyms.get(key,word if (word.isupper() and len(word)<=6) else word.capitalize()))
    if suffix and suffix.casefold() not in {x.casefold() for x in display}:
        if len(display)>=max_words:display=display[:max_words-1]
        display.append(suffix)
    return " ".join(display[:max_words]).strip() or "Agent Job"

def role_profile(agent):
    """Return only an explicitly granted local capability profile.

    Job titles remain identity/context. They do not silently grant coding,
    research, planning, delegation, or any other runtime behavior.
    """
    permissions=dict(agent.get("permissions") or {})
    if bool(permissions.get("delegate")):return "planning"
    try:
        from agentie.core.agent_access import skill_allowed
        if skill_allowed(agent,"code-execution"):return "coding"
        if skill_allowed(agent,"research"):return "research"
        if skill_allowed(agent,"planning"):return "planning"
    except Exception:
        skills={str(x).casefold() for x in agent.get("skills") or []}
        if "code-execution" in skills:return "coding"
        if "research" in skills:return "research"
        if "planning" in skills:return "planning"
    return "general"

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

def _failed_turn_is_latest(session_id):
    failed=get_context(session_id,"last_provider_failure",None)
    if not isinstance(failed,dict) or not failed.get("user_message"):return False
    history=recent_messages(session_id,limit=4,max_chars=4000)
    if not history:return False
    last=history[-1]
    return last.get("role")=="user" and str(last.get("content") or "").strip()==str(failed.get("user_message") or "").strip()

def _active_team_followup(agent,norm,session_id):
    commands=r"(?:do that|do it|go ahead|go ahead with that|proceed with that|continue|continue with that|go on|what happened|what is happening|how is that going|check that|status of that|retry that|retry it|try that again|try it again)"
    if not re.fullmatch(commands,norm):return None
    job_id=str(get_context(session_id,"active_team_job_id","") or "")
    if not job_id:return None
    try:
        from agentie.core.team_orchestrator import get_team_job,retry_team_worker,team_job_card
        job=get_team_job(job_id)
    except Exception:return None
    if not job:return None
    status=str(job.get("status") or "unknown");names=", ".join(job.get("agent_names") or []) or "the delegated agent";task=str(job.get("task") or get_context(session_id,"active_team_job_task","") or "the task")
    if re.fullmatch(r"(?:retry that|retry it|try that again|try it again)",norm):
        failed=next((h for h in job.get("handoffs",[]) if h.get("status")=="failed"),None)
        if not failed:return _result(agent,f"That handoff is {status}; there isn’t a failed worker to retry right now.",role_profile(agent),.99,context_action="retry_active_team_job",card=team_job_card(job))
        try:retried=retry_team_worker(job_id,str(failed.get("to_agent_name") or ""))
        except ValueError as exc:return _result(agent,str(exc),role_profile(agent),.99,context_action="retry_active_team_job",card=team_job_card(job))
        return _result(agent,f"Retrying {failed.get('to_agent_name') or 'the delegated agent'} on {job_id}.",role_profile(agent),.99,context_action="retry_active_team_job",card=team_job_card(retried))
    if status in {"queued","working"}:msg=f"That is already in progress with {names}: {task}. Status: {status}."
    elif status in {"completed","partial"}:msg=f"That handoff is {status}. {names} worked on: {task}."
    else:msg=f"That handoff is {status}. The task is still saved as {job_id}, so you can inspect or retry it."
    return _result(agent,msg,role_profile(agent),.99,context_action="active_team_job",card=team_job_card(job))

def _contextual_followup(agent,message,session_id):
    if not session_id:return None
    norm=_normalized(message);kind=role_profile(agent)
    active_team=_active_team_followup(agent,norm,session_id)
    if active_team is not None:return active_team
    latest=latest_assistant_text(session_id,4000)
    shorten_match=re.fullmatch(r"(?:make (?:it|that) (?:shorter|short|concise)|shorter|make it brief|brief version|summarize that briefly)",norm)
    repeat_match=re.fullmatch(r"(?:repeat that|say that again|repeat it|show that again)",norm)
    if (shorten_match or repeat_match) and _failed_turn_is_latest(session_id):
        return _result(agent,"There isn’t a successful answer from that last request to reuse yet. The model call failed, so retry the request when the provider is available.",kind,.99,context_action="failed_previous_turn")
    if not latest:return None
    if shorten_match:return _result(agent,_shorten(latest),kind,.98,context_action="shorten_previous")
    if repeat_match:return _result(agent,latest,kind,.99,context_action="repeat_previous")
    if re.fullmatch(r"(?:what do you mean|what did you mean|explain that simply)",norm):return _result(agent,"In simpler terms: "+_shorten(latest,220),kind,.9,context_action="clarify_previous")
    if re.fullmatch(r"(?:do that|do it|go ahead|go ahead with that|proceed with that|continue with that|the second one|second one|use the second one|the first one|first one|use the first one)",norm):
        history=recent_messages(session_id,limit=6,max_chars=5000);context=[]
        for item in history[-5:]:context.append(("User" if item.get("role")=="user" else "Assistant")+": "+str(item.get("content") or ""))
        if context:
            expanded="Resolve the user's follow-up using the immediately preceding conversation. The user said: "+message+"\n\nRecent context:\n"+"\n".join(context)
            set_context(session_id,"npc_last_followup",{"message":message,"kind":"context_reference"});return _escalate(agent,expanded,kind,.72)
    return None

def _judgment_request(norm):
    if not norm:return False
    patterns=(
        r"\bwhat do you think\b",r"\bdo you think\b",r"\byour opinion\b",r"\bwhat is your opinion\b",
        r"\bshould (?:we|i)\b",r"\bwould you recommend\b",r"\bdo you recommend\b",r"\brecommend(?:ation|ations)?\b",
        r"\bwhich (?:one )?is better\b",r"\bwhich should (?:we|i)\b",r"\bbest option\b",r"\bgood idea\b",r"\bbad idea\b",
        r"\bworth it\b",r"\bwhat should (?:we|i) (?:do|choose|prioritize|prioritise)\b",r"\bwhat would you do\b",
        r"\bwhat (?:are|is) the (?:main |biggest |key )?risks?\b",r"\bprioriti[sz]e\b",r"\btradeoffs?\b",
    )
    return any(re.search(pattern,norm) for pattern in patterns)

def _consequential_subject(norm):
    return bool(re.search(r"\b(?:send|email|publish|post|delete|remove|pay|spend|purchase|buy|transfer|refund|hire|fire|cancel|commit|push|merge|deploy|sign|submit)\b",norm))

def _team_snapshot(agent):
    rows=[]
    for item in list_agents():
        if str(item.get("id"))==str(agent.get("id")):continue
        name=str(item.get("name") or "Agent").strip();role=str(item.get("role") or item.get("base") or "general").strip()
        rows.append(f"{name} ({role})")
    return ", ".join(rows[:20]) or "No other persistent agents are currently configured."

def _judgment_escalation(agent,message):
    norm=_normalized(message)
    if not _judgment_request(norm):return None
    kind=role_profile(agent);name=str(agent.get("name") or "Agent");role=str(agent.get("role") or kind);goal=str(agent.get("goal") or agent.get("purpose") or "").strip();responsibilities=[str(x).strip() for x in (agent.get("responsibilities") or []) if str(x).strip()]
    lines=[
        "This is an advice/judgment request, not an instruction to execute the proposed action.",
        f"Answer as {name}, whose role is {role}. Use the persistent agent identity plus the company/project/memory context supplied with this turn.",
        "Exercise real role-based judgment. Do not agree merely to be agreeable; if the proposed plan is weak, say so respectfully and recommend the better path.",
        "Keep supported FACTS separate from your OPINION, your RECOMMENDATION, and the important RISKS/UNCERTAINTY. Use explicit labels when that distinction would otherwise be unclear.",
        "Never invent supporting facts or confidence. If current/external evidence materially affects the recommendation, use an available real tool/MCP/research capability when appropriate or clearly say what still needs verification.",
        "Keep the explanation proportionate: give the strongest reasons and tradeoffs, not generic filler.",
    ]
    if goal:lines.append(f"Agent goal to optimize for: {goal}")
    if responsibilities:lines.append("Relevant responsibilities: "+"; ".join(responsibilities[:8]))
    if bool((agent.get("permissions") or {}).get("delegate")):
        lines.append("This agent has explicit delegation authority. Prioritize by expected goal impact, urgency, dependencies, reversibility, and risk. Challenge poor sequencing or low-value work. Identify a capability gap only when the existing team truly lacks it; do not recommend a duplicate agent.")
        lines.append("Existing Agentie team: "+_team_snapshot(agent))
    if _consequential_subject(norm):lines.append("The proposed subject includes a potentially consequential action. You may recommend for or against it, but do not execute it from this advice request. If execution is later chosen, state that Agentie's normal permission/approval gate still applies.")
    lines.append("User's original judgment question: "+str(message).strip())
    return _escalate(agent,"\n".join(lines),kind,.86)

def _role_local_response(agent,message):
    kind=role_profile(agent);norm=_normalized(message);words=set(norm.split())
    if not norm:return None
    if re.fullmatch(r"(?:what is|what s) your role",norm):
        role=str(agent.get("role") or "configured agent");goal=str(agent.get("goal") or agent.get("purpose") or "").strip()
        suffix=f" My configured goal is: {goal}" if goal else ""
        return _result(agent,f"I’m your {role} agent.{suffix}",kind)
    if re.fullmatch(r"(?:what are|what re|what is) you working on",norm):return _result(agent,f"I’m ready for work within my configured job: {agent.get('role') or 'general ownership'}.",kind)
    if kind=="general":return None
    checklist=("checklist" in words or re.search(r"\b(?:how should|how do we|how do i)\b",norm))
    if kind=="coding" and checklist and re.search(r"\b(?:test|debug|deploy|build|implement|release|code|engineering)\b",norm):return _result(agent,"Engineering checklist: reproduce or define the goal, inspect the existing implementation, make the smallest safe change, run targeted tests, then run the full regression suite before deployment.",kind)
    if kind=="research" and checklist and re.search(r"\b(?:research|investigate|compare|verify|sources?)\b",norm):return _result(agent,"Research checklist: define the question, gather multiple credible sources, compare claims and dates, note disagreements, then summarize findings with evidence and uncertainty.",kind)
    if kind=="planning" and checklist and re.search(r"\b(?:plan|launch|project|roadmap|organize|strategy)\b",norm):return _result(agent,"Planning checklist: define the outcome, identify constraints, break work into owners and milestones, order dependencies, then track risks and next actions.",kind)
    return None

def try_npc_response(agent,message,session_id=None):
    """Return a confident local response, a context-enriched escalation, or None."""
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
        if re.fullmatch(r"(?:continue|go on|proceed|carry on)",norm) and session_id:
            active_team=_active_team_followup(agent,norm,session_id)
            if active_team is not None:return active_team
            history=recent_messages(session_id,limit=5,max_chars=4000)
            if history:
                context="\n".join(("User" if x["role"]=="user" else "Assistant")+": "+x["content"] for x in history[-4:]);return _escalate(agent,"Continue the current task from this recent context without restarting it:\n"+context,role_profile(agent),.7)
    local=_role_local_response(agent,message)
    if local is not None:return local
    judgment=_judgment_escalation(agent,message)
    if judgment is not None:return judgment
    return None
