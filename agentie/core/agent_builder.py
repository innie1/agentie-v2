from __future__ import annotations

import re
from typing import Any

from agentie.core.agent_matching import match_identity_score
from agentie.core.agent_registry import list_agents
from agentie.core.mcp_catalog import presets as mcp_presets
from agentie.core.mcp_client import list_servers
from agentie.core.skill_registry import list_skills

_STOP={"a","an","and","are","as","at","be","by","for","from","in","is","it","my","of","on","or","our","that","the","their","this","to","user","with","who","will","agent","bot","employee","work","job"}
_DEFAULT_APPROVAL_POLICY={"send_external":"approval","publish":"approval","delete_or_overwrite":"approval","purchase_or_payment":"approval","financial_transfer":"approval","permission_change":"approval","production_change":"approval","accept_legal_terms":"approval","safe_read":"automatic","draft_or_recommend":"automatic"}
_SCHEDULE_RE=re.compile(r"\b(?:every\s+(?:weekday|day|morning|afternoon|evening|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d+(?:\.\d+)?\s*(?:minutes?|mins?|hours?|hrs?))|daily|weekly)\b(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?",re.I)
_COORDINATE_RE=re.compile(r"\b(?:coordinate|delegate|manage\s+(?:the\s+)?team|oversee\s+(?:the\s+)?team|assign\s+work|manage\s+other\s+agents|chief\s+of\s+staff)\b",re.I)
_REPORTING_RE=re.compile(r"\b(?:reports?\s+to|reporting\s+to|managed\s+by|work(?:s|ing)?\s+under|under\s+(?:the\s+)?management\s+of)\b",re.I)
_REQUEST_PREFIX_RE=re.compile(r"^(?:hey[, ]+)?(?:(?:i\s+)?(?:need|want|would\s+like)\s+)?(?:(?:someone|somebody|a\s+person|an?\s+(?:agent|bot))\s+)?(?:who\s+|to\s+)?",re.I)
_ACTION_WORDS={"answer","automate","build","check","compare","coordinate","create","design","draft","escalate","find","help","investigate","keep","log","manage","monitor","organize","plan","prioritize","research","respond","review","track","verify","watch","write"}
_VERB_NORMAL={"answers":"answer","automates":"automate","builds":"build","checks":"check","compares":"compare","coordinates":"coordinate","creates":"create","designs":"design","drafts":"draft","escalates":"escalate","finds":"find","helps":"help","investigates":"investigate","keeps":"keep","logs":"log","manages":"manage","monitors":"monitor","organizes":"organize","plans":"plan","prioritizes":"prioritize","researches":"research","responds":"respond","reviews":"review","tracks":"track","verifies":"verify","watches":"watch","writes":"write"}
_SKILL_HINTS={
    "planning":{"organize","plan","prioritize","compare","decide","coordinate","manage","review","strategy","ideas"},
    "knowledge-memory":{"track","monitor","remember","log","maintain","organize","follow","notes","history","ideas","records"},
    "research":{"research","find","investigate","verify","compare","market","information","facts"},
    "files":{"document","report","spreadsheet","file","write","draft","log","record","records"},
    "browser-automation":{"website","browser","web","online","login","form","navigate","automate"},
    "jobs":{"routine","schedule","recurring","background","delegate","monitor","coordinate"},
    "email":{"email","inbox","message","messages","reply","respond"},
    "code-execution":{"code","python","calculate","analyse","analyze","data"},
    "visuals-motion":{"diagram","visual","flowchart","animation","design"},
}
_GENERIC_SUBJECTS={"work","task","tasks","thing","things","area","stuff","help"}


def _clean(value: str, limit: int = 1200) -> str:return " ".join(str(value or "").strip().split())[:limit]
def _words(value: str) -> set[str]:return {w for w in re.findall(r"[a-z0-9]+", str(value or "").casefold()) if len(w)>1 and w not in _STOP}
def _score(query: str, item: dict[str, Any]) -> int:
    q=_words(query)
    if not q:return 0
    fields=[item.get("name"),item.get("description")," ".join(map(str,item.get("capabilities") or [])),item.get("requires")];text=" ".join(str(x or "") for x in fields).casefold();words=_words(text);score=len(q & words)*3
    for token in q:
        if token in text:score+=1
    return score

def recommend_skills(description: str, limit: int = 6) -> list[dict[str, Any]]:
    query_words=_words(description);scored=[]
    for skill in list_skills():
        if skill.get("enabled") is False:continue
        sid=str(skill.get("id") or "").casefold();score=_score(description,skill)
        score+=2*len(query_words & _SKILL_HINTS.get(sid,set()))
        if score>0:scored.append((score,skill))
    scored.sort(key=lambda x:(-x[0],str(x[1].get("name") or x[1].get("id") or "").casefold()))
    return [{"id":str(item.get("id")),"name":str(item.get("name") or item.get("id")),"description":str(item.get("description") or ""),"kind":str(item.get("kind") or "capability"),"score":score} for score,item in scored[:max(1,limit)]]

def recommend_plugins(description: str, limit: int = 6) -> list[dict[str, Any]]:
    installed={str(x.get("name") or "").casefold() for x in list_servers()};scored=[]
    for preset in mcp_presets():
        score=_score(description,preset)
        if score>0:scored.append((score,preset))
    scored.sort(key=lambda x:(-x[0],str(x[1].get("name") or x[1].get("id") or "").casefold()))
    return [{"id":str(item.get("id")),"name":str(item.get("name") or item.get("id")),"description":str(item.get("description") or ""),"installed":str(item.get("id") or "").casefold() in installed,"setup_required":str(item.get("id") or "").casefold() not in installed,"score":score} for score,item in scored[:max(1,limit)]]

def recommend_collaborators(description:str,limit:int=4)->list[dict[str,Any]]:
    scored=[]
    for agent in list_agents():
        score=match_identity_score(description,agent)
        if score>=.12:scored.append((score,agent))
    scored.sort(key=lambda x:(-x[0],str(x[1].get("name") or "").casefold()))
    return [{"id":a["id"],"name":a["name"],"job":a.get("role"),"goal":a.get("goal"),"score":round(float(score),3),"can_delegate":bool((a.get("permissions") or {}).get("delegate"))} for score,a in scored[:max(1,limit)]]

def recommend_manager(description:str)->dict[str,Any]|None:
    if not _REPORTING_RE.search(str(description or "")):return None
    coordinators=[a for a in list_agents() if bool((a.get("permissions") or {}).get("delegate"))]
    if not coordinators:return None
    low=str(description or "").casefold();explicitly_named=[a for a in coordinators if str(a.get("name") or "").casefold() in low];candidates=explicitly_named or coordinators;ranked=sorted(((match_identity_score(description,a),a) for a in candidates),key=lambda x:(-x[0],str(x[1].get("name") or "").casefold()));score,agent=ranked[0]
    return {"id":agent["id"],"name":agent["name"],"job":agent.get("role"),"score":round(float(score),3),"reason":"The job description explicitly described a reporting relationship and this existing agent has delegation authority. The title itself does not grant that authority."}

def routine_suggestions(description:str)->list[dict[str,Any]]:
    out=[]
    for m in _SCHEDULE_RE.finditer(str(description or "")):
        trigger=_clean(m.group(0),120);action=_clean(str(description or "").replace(m.group(0)," "),700).strip(" ,.;:-")
        if action:
            name=" ".join(re.findall(r"[A-Za-z0-9]+",action)[:6]).title() or "Agent Routine";item={"name":name,"trigger":trigger,"action":action,"reason":"The job description explicitly includes a recurring schedule."}
            if not any(x["trigger"].casefold()==trigger.casefold() and x["action"].casefold()==action.casefold() for x in out):out.append(item)
        if len(out)>=3:break
    return out

def capability_gaps(description:str)->list[dict[str,Any]]:return [{"kind":"plugin","id":x["id"],"name":x["name"],"reason":"Relevant to this job but not connected yet."} for x in recommend_plugins(description,8) if x.get("setup_required")]

def _sentences(description: str) -> list[str]:
    parts=[_clean(x,400) for x in re.split(r"[\n;]+|(?<=[.!?])\s+",str(description or ""))];return [x.strip(" .") for x in parts if len(x.strip(" ."))>=4]

def _task_text(description:str)->str:
    raw=re.split(r"\bUseful capability areas:\s*|\bHelpful capability areas selected by the user:\s*",str(description or ""),maxsplit=1,flags=re.I)[0]
    raw=_clean(raw,1200).strip(" .")
    if raw.casefold().startswith("help with these areas:"):
        raw=raw.split(":",1)[1].strip()
    raw=_REQUEST_PREFIX_RE.sub("",raw,count=1).strip(" ,.;:-")
    parts=raw.split()
    if not parts:return "general support"
    first=parts[0].casefold().strip(" ,.;:-")
    normalized=_VERB_NORMAL.get(first,first)
    if normalized!=first:parts[0]=normalized
    if parts and parts[0].casefold()=="help" and len(parts)>1:
        second=_VERB_NORMAL.get(parts[1].casefold(),parts[1].casefold())
        if second in _ACTION_WORDS:parts=parts[1:];parts[0]=second
    return _clean(" ".join(parts).strip(" ."),900) or "general support"

def _first_clause(task:str)->str:
    return _clean(re.split(r"\s*(?:,|;|\band\b)\s*",task,maxsplit=1,flags=re.I)[0],300).strip(" .")

def _action_subject(task:str)->tuple[str,str]:
    clause=_first_clause(task);parts=clause.split();action=""
    if parts:
        candidate=_VERB_NORMAL.get(parts[0].casefold(),parts[0].casefold())
        if candidate in _ACTION_WORDS:action=candidate;parts=parts[1:]
    subject=" ".join(parts).strip(" .")
    subject=re.sub(r"\b(?:for|to)\s+me$","",subject,flags=re.I).strip()
    if not subject:subject=clause or "the assigned work"
    return action,subject

def _display_title(text:str)->str:
    words=[w.strip(" ,.;:!?()[]{}") for w in text.split() if w.strip(" ,.;:!?()[]{}")]
    words=[w for w in words if w.casefold() not in {"the","a","an","my","our","some","someone","something"}]
    if not words:return "General Support"
    words=words[:5]
    rendered=[]
    for word in words:
        if any(c.isupper() for c in word[1:]):rendered.append(word)
        elif word.isupper() and len(word)<=5:rendered.append(word)
        else:rendered.append(word.capitalize())
    return _clean(" ".join(rendered),70)

def _role_title(task:str,explicit_job:str="")->str:
    explicit=_clean(explicit_job,100).strip(" .")
    if explicit and len(explicit.split())<=7 and not re.search(r"\b(?:i need|i want|someone who|someone to)\b",explicit,re.I):return explicit
    action,subject=_action_subject(task)
    subject=re.sub(r"\b(?:readings|records|information|data)\b$","",subject,flags=re.I).strip()
    if subject.casefold() in _GENERIC_SUBJECTS or not subject:
        fallback={"research":"Research","organize":"Organization","manage":"Coordination","coordinate":"Coordination","monitor":"Monitoring","track":"Tracking","automate":"Automation","create":"Creation","write":"Writing","build":"Building","plan":"Planning"}.get(action,"General Support")
        return fallback
    return _display_title(subject)

def _goal_for(task:str)->str:
    action,subject=_action_subject(task);subject=subject or "the assigned work";s=subject[0].lower()+subject[1:] if subject else "the assigned work"
    if action in {"organize","plan","prioritize","manage","coordinate","review","compare"}:return f"Keep {s} organized, clear, prioritized, and easy to act on."
    if action in {"monitor","track","watch","check","log","keep"}:return f"Keep {s} accurately tracked and surface changes or issues that need attention."
    if action in {"research","find","investigate","verify"}:return f"Build a clear, evidence-based view of {s} so the user can make good decisions."
    if action in {"create","write","build","design","draft"}:return f"Turn {s} into useful, high-quality work that is ready for the user to use or review."
    if action in {"answer","respond","escalate"}:return f"Handle {s} reliably and surface anything that needs the user's attention."
    return f"Take ownership of {s} and keep it moving toward a useful result."

def _imperative(clause:str)->str:
    clause=_clean(clause,350).strip(" .")
    if not clause:return ""
    parts=clause.split();first=_VERB_NORMAL.get(parts[0].casefold(),parts[0].casefold());parts[0]=first
    text=" ".join(parts);return text[0].upper()+text[1:]+("" if text.endswith(('.', '!', '?')) else ".")

def _responsibilities_for(task:str)->list[str]:
    clauses=[_clean(x,320).strip(" .") for x in re.split(r"\s*(?:,|;|\band\b)\s*",task,flags=re.I) if _clean(x,320).strip(" .")]
    out=[]
    for clause in clauses[:3]:
        item=_imperative(clause)
        if item and item.casefold() not in {x.casefold() for x in out}:out.append(item)
    action,subject=_action_subject(task);subject=subject or "the assigned work"
    extras=[]
    if action in {"organize","plan","prioritize","manage","coordinate","review","compare"}:extras=["Keep priorities, decisions, notes, and next steps clear and up to date.","Flag duplicates, gaps, blockers, or decisions that need user input."]
    elif action in {"monitor","track","watch","check","log","keep"}:extras=[f"Maintain an accurate running record of {subject}.","Surface meaningful changes, exceptions, or follow-ups promptly."]
    elif action in {"research","find","investigate","verify"}:extras=["Gather relevant evidence and distinguish verified facts from assumptions.","Compare useful options and explain the important trade-offs."]
    elif action in {"create","write","build","design","draft"}:extras=["Produce clear deliverables that match the requested outcome.","Check the work for quality, completeness, and obvious errors before reporting it done."]
    elif action in {"answer","respond","escalate"}:extras=["Handle routine requests clearly and consistently.","Escalate sensitive, uncertain, or consequential issues instead of guessing."]
    else:extras=["Keep the work current and report meaningful progress or blockers.","Ask for user input when a decision or permission is genuinely required."]
    for item in extras:
        if len(out)>=3:break
        if item.casefold() not in {x.casefold() for x in out}:out.append(item)
    return out[:3]

def draft_agent_spec(description: str, *, name: str = "", job: str = "") -> dict[str, Any]:
    raw_description=str(description or "").strip()
    description=_clean(raw_description,5000)
    if not description:raise ValueError("Describe what this agent should own or be responsible for.")
    task=_task_text(raw_description);job_text=_role_title(task,job);goal=_goal_for(task);responsibilities=_responsibilities_for(task)
    working_style="Proactive, reliable, clear about uncertainty, and willing to recommend a better approach when evidence supports it"
    instructions=(f"Job ownership: {job_text}.\nConfigured work: {task}.\nWork from the user's configured goal, responsibilities, knowledge, skills, plugins and approval boundaries. Do not assume a predefined profession or department beyond what the user configured. Use the least costly real capability that can complete the work, and never claim an action succeeded unless it actually did.")
    plugins=recommend_plugins(description);manager=recommend_manager(description);routines=routine_suggestions(description);delegate=bool(_COORDINATE_RE.search(description))
    return {"name":_clean(name,120),"job":job_text,"description":description,"goal":goal,"working_style":working_style,"responsibilities":responsibilities,"instructions":instructions,"skills":recommend_skills(description),"plugins":plugins,"approval_policy":dict(_DEFAULT_APPROVAL_POLICY),"memory_policy":{"private_context":True,"company_knowledge":"read","project_knowledge":"scoped"},"can_delegate":False,"can_delegate_recommended":delegate,"manager_id":None,"recommended_manager":manager,"recommended_collaborators":recommend_collaborators(description),"routine_suggestions":routines,"capability_gaps":capability_gaps(description),"connection_needed":[x["id"] for x in plugins if x.get("setup_required")],"runtime_profile":"general"}

def _explicit_ids(values)->list[str]:
    """Strings are explicit selections. Draft recommendation objects are not grants unless selected=True."""
    out=[]
    for value in values or []:
        if isinstance(value,dict):
            if value.get("selected") is not True:continue
            raw=value.get("id")
        else:raw=value
        sid=str(raw or "").strip().lower()
        if sid:out.append(sid)
    return sorted(set(out))

def normalize_create_spec(spec: dict[str, Any]) -> dict[str, Any]:
    name=_clean(spec.get("name") or "",120)
    if not name:raise ValueError("Agent name is required.")
    job=_clean(spec.get("job") or spec.get("role") or "",500)
    if not job:raise ValueError("Describe the agent's job or area of ownership.")
    responsibilities=[]
    for value in spec.get("responsibilities") or []:
        item=_clean(value,400)
        if item and item.casefold() not in {x.casefold() for x in responsibilities}:responsibilities.append(item)
    approval=dict(_DEFAULT_APPROVAL_POLICY);approval.update({str(k):str(v) for k,v in dict(spec.get("approval_policy") or {}).items()});routines=[dict(x) for x in spec.get("routines") or [] if isinstance(x,dict)]
    return {"name":name,"role":job,"purpose":_clean(spec.get("description") or job,1600),"goal":_clean(spec.get("goal") or f"Own and complete: {job}",1600),"personality":_clean(spec.get("working_style") or "Proactive, reliable, and clear about uncertainty",800),"responsibilities":responsibilities,"manual_instructions":str(spec.get("instructions") or "").strip()[:12000],"skills":_explicit_ids(spec.get("skills")),"plugins":_explicit_ids(spec.get("plugins")),"approval_policy":approval,"memory_policy":dict(spec.get("memory_policy") or {}),"manager_id":spec.get("manager_id") or None,"can_delegate":bool(spec.get("can_delegate")),"routines":routines,"runtime_profile":"general"}
