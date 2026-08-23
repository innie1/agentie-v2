from __future__ import annotations
import json,re
from datetime import datetime
from pathlib import Path
from typing import Any
from agentie.core.agent_registry import get_agent,update_agent_profile
WORKSPACE=Path.cwd()/"workspace";PROMPTS_FILE=WORKSPACE/"agent_instruction_profiles.json"
def _now():return datetime.now().astimezone().isoformat(timespec="seconds")
def _load():
    try:
        value=json.loads(PROMPTS_FILE.read_text(encoding="utf-8")) if PROMPTS_FILE.exists() else {"agents":{}};return value if isinstance(value,dict) else {"agents":{}}
    except Exception:return {"agents":{}}
def _save(data):PROMPTS_FILE.parent.mkdir(parents=True,exist_ok=True);PROMPTS_FILE.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
def agent_from_session(session_id):
    m=re.match(r"^agent:(agt_[a-z0-9]+):",str(session_id or ""),re.I);return get_agent(m.group(1)) if m else None
def _identity_snapshot(agent):return {"name":agent.get("name"),"role":str(agent.get("role") or "general"),"purpose":str(agent.get("purpose") or "").strip(),"personality":str(agent.get("personality") or "").strip(),"goal":str(agent.get("goal") or "").strip(),"responsibilities":list(agent.get("responsibilities") or []),"company_identity":str(agent.get("company_identity") or "").strip()}
def _base_profile(agent):return {"agent_id":agent["id"],**_identity_snapshot(agent),"manual_instructions":"","communication":{},"task_preferences":{},"durable_context":[],"learned_rules":[],"learning_candidates":{},"learning_audit":[],"updated_at":_now()}
def _looks_like_generated_builder_text(value):
    text=str(value or "").strip();low=text.casefold()
    if not text:return False
    generated_signature=("do not assume a predefined profession or department" in low and "never claim an action succeeded unless" in low)
    older_signature=(text.startswith("Job ownership:") or text.startswith("Configured work:")) and "work from the user's configured goal" in low
    return bool(generated_signature or older_signature)
def get_instruction_profile(agent):
    data=_load();profiles=data.setdefault("agents",{});profile=profiles.get(agent["id"])
    if not isinstance(profile,dict):profile=_base_profile(agent);profiles[agent["id"]]=profile;_save(data)
    changed=False
    for key,default in (("manual_instructions",""),("communication",{}),("task_preferences",{}),("durable_context",[]),("learned_rules",[]),("learning_candidates",{}),("learning_audit",[])):
        if key not in profile:profile[key]=default;changed=True
    # A previous creator version stored Agentie's generated builder boilerplate in
    # the user-authored field. Clear only that recognizable generated text; real
    # user instructions are preserved untouched.
    if _looks_like_generated_builder_text(profile.get("manual_instructions")):
        profile["manual_instructions"]="";changed=True
    for key,value in _identity_snapshot(agent).items():
        if profile.get(key)!=value:profile[key]=value;changed=True
    if changed:profile["updated_at"]=_now();_save(data)
    return profile
def _audit(profile,kind,summary,source="conversation",confidence="high",metadata=None):
    items=profile.setdefault("learning_audit",[]);items.append({"at":_now(),"kind":kind,"summary":summary,"source":source,"confidence":confidence,"metadata":metadata or {}});profile["learning_audit"]=items[-100:]
def set_manual_instructions(agent,instructions):
    data=_load();profiles=data.setdefault("agents",{});profile=profiles.get(agent["id"]) or _base_profile(agent);value=str(instructions or "").strip()[:12000]
    if profile.get("manual_instructions","")!=value:_audit(profile,"manual_instruction","User-edited instructions updated.","manual","explicit")
    profile["manual_instructions"]=value;profile["updated_at"]=_now();profiles[agent["id"]]=profile;_save(data);return profile
def learning_audit(agent,limit=50):return list(reversed(get_instruction_profile(agent).get("learning_audit",[])[-max(1,min(int(limit),100)):]))
def instruction_card(agent):
    p=get_instruction_profile(agent);return {"type":"agent_instructions","agent_id":agent["id"],"name":agent.get("name"),"role":agent.get("role"),"manual_instructions":p.get("manual_instructions","") or "","generated_prompt":build_agent_instructions(agent),"learned":{"communication":p.get("communication",{}),"task_preferences":p.get("task_preferences",{}),"learned_rules":p.get("learned_rules",[])},"learning_audit":learning_audit(agent)}
def purge_instruction_profile(agent_id):
    data=_load();profiles=data.setdefault("agents",{});existed=1 if str(agent_id) in profiles else 0;profiles.pop(str(agent_id),None)
    if existed:_save(data)
    return existed
def _promote(profile,section,key,value,summary,explicit=False):
    bucket=profile.setdefault(section,{})
    if bucket.get(key)==value:return False
    candidates=profile.setdefault("learning_candidates",{});cid=f"{section}.{key}={value}";entry=candidates.get(cid,{"count":0});entry["count"]=int(entry.get("count",0))+1;entry["last_seen"]=_now();candidates[cid]=entry
    if not explicit and entry["count"]<2:return False
    bucket[key]=value;candidates.pop(cid,None);_audit(profile,"learned_preference",summary,"conversation","explicit" if explicit else "repeated",{"section":section,"key":key,"value":value});return True
def _profile_value(value,limit=1200):return " ".join(str(value or "").strip(" .").split())[:limit]
def _learn_employee_profile(agent,text,profile):
    updates={};labels=[]
    m=re.search(r"\b(?:your personality(?: and working style)?|i want your personality)\s+(?:is|to be|should be|as)\s+(.+)$",text,re.I)
    if m:
        value=_profile_value(m.group(1),800)
        if value:updates["personality"]=value;labels.append("personality")
    m=re.search(r"\b(?:your (?:primary )?(?:goal|objective)|i want your (?:primary )?(?:goal|objective))\s+(?:is|to be|should be|as)\s+(.+)$",text,re.I)
    if m:
        value=_profile_value(m.group(1),1200)
        if value:updates["goal"]=value;labels.append("goal")
    m=re.search(r"\byour (?:responsibilities|duties)\s*(?:are|include|should be|:)?\s+(.+)$",text,re.I) or re.search(r"\byou are responsible for\s+(.+)$",text,re.I)
    if m:
        raw=_profile_value(m.group(1),2400);values=[_profile_value(x,400) for x in re.split(r"\s*(?:\||;|,\s+|\band\b)\s*",raw,flags=re.I)];values=[x for x in values if x]
        if values:updates["responsibilities"]=values;labels.append("responsibilities")
    m=re.search(r"\b(?:your company(?: identity)?|company identity)\s+(?:is|to be|should be|as|:)\s+(.+)$",text,re.I) or re.search(r"\byou (?:work for|represent)\s+(.+)$",text,re.I)
    if m:
        value=_profile_value(m.group(1),400)
        if value:updates["company_identity"]=value;labels.append("company identity")
    if not updates:return []
    try:updated=update_agent_profile(str(agent.get("id") or agent.get("name") or ""),**updates)
    except ValueError:return []
    agent.update(updated)
    for key,value in _identity_snapshot(updated).items():profile[key]=value
    for field in labels:_audit(profile,"employee_profile_update",f"Updated employee profile {field} from an explicit user instruction.","conversation","explicit",{"field":field})
    return [f"Updated employee profile {field}." for field in labels]
def learn_from_user_message(agent,message):
    text=" ".join(str(message or "").strip().split());low=text.casefold();data=_load();profiles=data.setdefault("agents",{});profile=profiles.get(agent["id"]) or _base_profile(agent);changes=[]
    changes.extend(_learn_employee_profile(agent,text,profile))
    stable=bool(re.search(r"\b(?:i\s+(?:like|prefer|want)|from now on|always|whenever|usually|in general|my preference)\b",low));temporary=bool(re.search(r"\b(?:this time|this one|for this|just this|only this|right now|today only)\b",low));explicit=stable and not temporary
    concise=bool(re.search(r"\b(?:repl(?:y|ies)|answers?|responses?)\b",low)) and bool(re.search(r"\b(?:short|brief|concise|compact)\b",low))
    if concise and not temporary and _promote(profile,"communication","default_length","concise","Default replies should be concise.",explicit):changes.append("Default replies should be concise.")
    detailed=bool(re.search(r"\b(?:reports?|analysis|research|breakdowns?)\b.{0,35}\b(?:detailed|thorough|comprehensive|long)\b|\b(?:detailed|thorough|comprehensive)\b.{0,25}\b(?:reports?|analysis|research|breakdowns?)\b",low))
    if detailed and not temporary and _promote(profile,"task_preferences","reports","detailed","Reports and analysis should be detailed.",explicit):changes.append("Reports and analysis should be detailed.")
    bullets=bool(re.search(r"\b(?:use|prefer|want)\b.{0,20}\b(?:bullet|bullets|bullet points)\b",low));no_bullets=bool(re.search(r"\b(?:do not|don't|dont|avoid|prefer no)\b.{0,20}\b(?:bullet|bullets|lists?)\b",low))
    if bullets and not temporary and _promote(profile,"communication","format","bullets_when_useful","Use bullets when useful.",explicit):changes.append("Use bullets when useful.")
    if no_bullets and not temporary and _promote(profile,"communication","format","prose","Prefer prose over lists.",explicit):changes.append("Prefer prose over lists.")
    formal=bool(re.search(r"\b(?:prefer|want|use)\b.{0,20}\bformal\b",low));casual=bool(re.search(r"\b(?:prefer|want|use)\b.{0,20}\b(?:casual|friendly|conversational)\b",low))
    if formal and not temporary and _promote(profile,"communication","tone","formal","Use a formal tone.",explicit):changes.append("Use a formal tone.")
    elif casual and not temporary and _promote(profile,"communication","tone","conversational","Use a conversational tone.",explicit):changes.append("Use a conversational tone.")
    copyable=bool(re.search(r"\b(?:prompt|commands?|code)\b.{0,30}\b(?:copyable|easy to copy|copy and paste)\b|\b(?:copyable|copy and paste)\b.{0,30}\b(?:prompt|commands?|code)\b",low))
    if copyable and not temporary and _promote(profile,"task_preferences","implementation_output","copyable","Implementation prompts/commands should be easy to copy.",explicit):changes.append("Implementation prompts/commands should be easy to copy.")
    durable=re.match(r"^(?:remember that |from now on |always |when you |whenever you )(.{8,220})$",text,re.I)
    if durable and not temporary and not (concise or detailed or bullets or no_bullets or formal or casual or copyable):
        rule=durable.group(1).strip(" .");rules=profile.setdefault("learned_rules",[])
        if rule and rule.casefold() not in {str(x).casefold() for x in rules}:rules.append(rule);profile["learned_rules"]=rules[-20:];changes.append("Saved a durable instruction.");_audit(profile,"learned_rule","Saved a durable user-authored rule.","conversation","explicit",{"rule_length":len(rule)})
    if changes or profile.get("learning_candidates"):
        profile["updated_at"]=_now();profiles[agent["id"]]=profile;_save(data)
    return changes
def build_agent_instructions(agent):
    p=get_instruction_profile(agent);name=str(agent.get("name") or "Agent");role=str(agent.get("role") or "general");personality=str(agent.get("personality") or "").strip();goal=str(agent.get("goal") or "").strip();company_identity=str(agent.get("company_identity") or "").strip();responsibilities=[str(x).strip() for x in (agent.get("responsibilities") or []) if str(x).strip()];permissions=agent.get("permissions") or {}
    lines=[f"You are {name}, a persistent Agentie AI employee.",f"Role: {role}."]
    if goal:lines.append(f"Goal: {goal}.")
    if personality:lines.append(f"Working personality: {personality}.")
    if responsibilities:lines.append("Responsibilities:\n- "+"\n- ".join(responsibilities[:8]))
    if company_identity:lines.append(f"Company identity: {company_identity}. When communicating externally, identify yourself consistently as {name} from {company_identity} unless the user explicitly instructs otherwise.")
    lines.append("Keep private memory and task context scoped to this agent. Use professional judgment, make useful recommendations, and surface meaningful uncertainty or risks instead of pretending certainty.")
    if permissions.get("delegate"):lines.append("You may delegate bounded work to another Agentie agent when that agent clearly owns the work better.")
    else:lines.append("If another agent clearly owns a task better, recommend the better owner rather than pretending this role owns it.")
    comm=p.get("communication") or {};tasks=p.get("task_preferences") or {}
    if comm.get("default_length")=="concise":lines.append("Default conversational replies should be concise unless the task requires depth.")
    if tasks.get("reports")=="detailed":lines.append("Reports, research and analysis should be detailed when needed.")
    if comm.get("format")=="bullets_when_useful":lines.append("Use bullet points when they improve clarity.")
    elif comm.get("format")=="prose":lines.append("Prefer cohesive prose over list-heavy formatting.")
    if comm.get("tone"):lines.append(f"Preferred communication tone: {comm['tone']}.")
    if tasks.get("implementation_output")=="copyable":lines.append("Implementation prompts, commands and code should be easy to copy and paste.")
    rules=[str(x).strip() for x in p.get("learned_rules",[]) if str(x).strip()]
    if rules:lines.append("Learned durable preferences:\n- "+"\n- ".join(rules[-12:]))
    manual=str(p.get("manual_instructions") or "").strip()
    if manual:lines.append("User instructions:\n"+manual)
    lines.append("The user's current explicit request wins over defaults. User-authored instructions outrank automatically learned preferences.")
    return "\n".join(lines)
