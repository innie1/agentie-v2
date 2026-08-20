from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agentie.core.agent_registry import get_agent

WORKSPACE = Path.cwd() / "workspace"
PROMPTS_FILE = WORKSPACE / "agent_instruction_profiles.json"


def _load() -> dict[str, Any]:
    try:
        value=json.loads(PROMPTS_FILE.read_text(encoding="utf-8")) if PROMPTS_FILE.exists() else {"agents":{}}
        return value if isinstance(value,dict) else {"agents":{}}
    except Exception:return {"agents":{}}


def _save(data:dict[str,Any])->None:
    PROMPTS_FILE.parent.mkdir(parents=True,exist_ok=True)
    PROMPTS_FILE.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")


def agent_from_session(session_id:str|None)->dict[str,Any]|None:
    m=re.match(r"^agent:(agt_[a-z0-9]+):",str(session_id or ""),re.I)
    return get_agent(m.group(1)) if m else None


def _base_profile(agent:dict[str,Any])->dict[str,Any]:
    role=str(agent.get("role") or "general");purpose=str(agent.get("purpose") or "").strip()
    return {"agent_id":agent["id"],"name":agent.get("name"),"role":role,"purpose":purpose,"communication":{},"task_preferences":{},"durable_context":[],"learned_rules":[],"updated_at":datetime.now().astimezone().isoformat(timespec="seconds")}


def get_instruction_profile(agent:dict[str,Any])->dict[str,Any]:
    data=_load();profiles=data.setdefault("agents",{});profile=profiles.get(agent["id"])
    if not isinstance(profile,dict):profile=_base_profile(agent);profiles[agent["id"]]=profile;_save(data)
    changed=False
    for key,value in (("name",agent.get("name")),("role",agent.get("role")),("purpose",agent.get("purpose",""))):
        if profile.get(key)!=value:profile[key]=value;changed=True
    if changed:profile["updated_at"]=datetime.now().astimezone().isoformat(timespec="seconds");_save(data)
    return profile


def purge_instruction_profile(agent_id:str)->int:
    data=_load();profiles=data.setdefault("agents",{});existed=1 if str(agent_id) in profiles else 0;profiles.pop(str(agent_id),None)
    if existed:_save(data)
    return existed


def _set(profile:dict[str,Any],section:str,key:str,value:Any)->bool:
    bucket=profile.setdefault(section,{})
    if bucket.get(key)==value:return False
    bucket[key]=value;return True


def learn_from_user_message(agent:dict[str,Any],message:str)->list[str]:
    """Extract only explicit, durable preferences/context. Never copy the whole chat."""
    text=" ".join(str(message or "").strip().split());low=text.casefold();data=_load();profiles=data.setdefault("agents",{});profile=profiles.get(agent["id"]) or _base_profile(agent);changes=[]

    # Accept natural word order: "short concise replies", "replies concise", etc.
    has_reply_word=bool(re.search(r"\b(?:repl(?:y|ies)|answers?|responses?)\b",low))
    has_short_word=bool(re.search(r"\b(?:short|brief|concise|compact)\b",low))
    has_preference=bool(re.search(r"\b(?:i\s+(?:like|prefer|want)|keep|make|prefer|want|give|from now on|always)\b",low))
    concise=has_reply_word and has_short_word and has_preference
    if concise and _set(profile,"communication","default_length","concise"):changes.append("Default replies should be concise.")

    detailed=bool(re.search(r"\b(?:reports?|analysis|research|breakdowns?)\b.{0,35}\b(?:detailed|thorough|comprehensive|long)\b|\b(?:detailed|thorough|comprehensive)\b.{0,25}\b(?:reports?|analysis|research|breakdowns?)\b",low))
    if detailed and _set(profile,"task_preferences","reports","detailed"):changes.append("Reports and analysis should be detailed.")
    bullets=bool(re.search(r"\b(?:use|prefer|want)\b.{0,20}\b(?:bullet|bullets|bullet points)\b",low));no_bullets=bool(re.search(r"\b(?:do not|don't|dont|avoid)\b.{0,20}\b(?:bullet|bullets|lists?)\b",low))
    if bullets and _set(profile,"communication","format","bullets_when_useful"):changes.append("Use bullets when useful.")
    if no_bullets and _set(profile,"communication","format","prose"):changes.append("Prefer prose over lists.")
    formal=bool(re.search(r"\b(?:prefer|want|use)\b.{0,20}\bformal\b",low));casual=bool(re.search(r"\b(?:prefer|want|use)\b.{0,20}\b(?:casual|friendly|conversational)\b",low))
    if formal and _set(profile,"communication","tone","formal"):changes.append("Use a formal tone.")
    elif casual and _set(profile,"communication","tone","conversational"):changes.append("Use a conversational tone.")
    copyable=bool(re.search(r"\b(?:prompt|commands?|code)\b.{0,30}\b(?:copyable|easy to copy|copy and paste)\b|\b(?:copyable|copy and paste)\b.{0,30}\b(?:prompt|commands?|code)\b",low))
    if copyable and _set(profile,"task_preferences","implementation_output","copyable"):changes.append("Implementation prompts/commands should be easy to copy.")

    # Save a compact rule only for explicit durable instructions. Do not save the entire sentence
    # when a structured preference above already captures its meaning.
    explicit_rule=re.match(r"^(?:remember that |from now on |always |when you |whenever you )(.{8,220})$",text,re.I)
    if explicit_rule and not (concise or detailed or bullets or no_bullets or formal or casual or copyable):
        rule=explicit_rule.group(1).strip(" .");rules=profile.setdefault("learned_rules",[])
        if rule and rule.casefold() not in {str(x).casefold() for x in rules}:rules.append(rule);profile["learned_rules"]=rules[-20:];changes.append("Saved a durable instruction.")

    if changes:
        profile["updated_at"]=datetime.now().astimezone().isoformat(timespec="seconds");profiles[agent["id"]]=profile;_save(data)
    return changes


def build_agent_instructions(agent:dict[str,Any])->str:
    profile=get_instruction_profile(agent);name=str(agent.get("name") or "Agent");role=str(agent.get("role") or "general");purpose=str(agent.get("purpose") or "").strip();permissions=agent.get("permissions") or {};skills=agent.get("skills") or []
    lines=[f"You are {name}, a persistent Agentie agent.",f"Your role is {role}.","Keep your identity, private memory, and task context scoped to this agent. Do not pretend to remember another agent's private conversations.","If a task clearly belongs to another existing specialist, delegate or hand it off instead of stretching your role unnecessarily."]
    if purpose:lines.append(f"Primary purpose: {purpose}.")
    if permissions.get("delegate"):lines.append("You are allowed to coordinate and delegate work to other Agentie agents.")
    if skills:lines.append("Assigned skills: "+", ".join(map(str,skills))+".")
    comm=profile.get("communication") or {};tasks=profile.get("task_preferences") or {}
    if comm.get("default_length")=="concise":lines.append("Default conversational replies should be concise unless the task requires depth.")
    if tasks.get("reports")=="detailed":lines.append("For reports, research, analysis, and formal breakdowns, be detailed even though ordinary replies are concise.")
    if comm.get("format")=="bullets_when_useful":lines.append("Use bullet points when they improve clarity.")
    elif comm.get("format")=="prose":lines.append("Prefer cohesive prose over list-heavy formatting.")
    if comm.get("tone"):lines.append(f"Preferred communication tone: {comm['tone']}.")
    if tasks.get("implementation_output")=="copyable":lines.append("When giving implementation prompts, commands, or code, make them easy to copy and paste.")
    rules=[str(x).strip() for x in profile.get("learned_rules",[]) if str(x).strip()]
    if rules:lines.append("Learned durable user preferences:\n- " + "\n- ".join(rules[-12:]))
    lines.append("Treat these learned preferences as defaults, not absolute rules: the user's current explicit request always wins.")
    return "\n".join(lines)
