from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

WORKSPACE=Path.cwd()/"workspace"
ROLES=WORKSPACE/"agent_roles.json"
BASE_AGENTS={"general","research","coding","manager","github"}

ROLE_PRESETS={
    "researcher":{"base":"research","instruction":"Act as a rigorous researcher. Gather evidence, compare sources, and distinguish fact from inference."},
    "critic":{"base":"research","instruction":"Act as a skeptical critic. Look for weaknesses, contradictions, missing evidence, and failure modes."},
    "verifier":{"base":"research","instruction":"Act as a verifier. Check claims against evidence and flag unsupported assertions."},
    "data analyst":{"base":"coding","instruction":"Act as a data analyst. Prefer reproducible calculations, code, tables, and explicit assumptions."},
    "document writer":{"base":"general","instruction":"Act as a professional document writer. Turn source material into clear, structured deliverables."},
    "planner":{"base":"manager","instruction":"Act as a planner. Decompose goals, assign work, track dependencies, and minimize unnecessary provider calls."},
    "coder":{"base":"coding","instruction":"Act as a software engineer. Inspect, implement, test, and explain code changes carefully."},
    "github reviewer":{"base":"github","instruction":"Act as a GitHub reviewer. Inspect repository state, changes, issues, and implementation risks."},
}


def _load()->dict[str,Any]:
    try:return json.loads(ROLES.read_text(encoding="utf-8")) if ROLES.exists() else {"assignments":{},"custom_roles":{}}
    except Exception:return {"assignments":{},"custom_roles":{}}
def _save(data:dict[str,Any])->None:
    ROLES.parent.mkdir(parents=True,exist_ok=True);ROLES.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
def resolve_role(agent_name:str)->dict[str,str]:
    key=agent_name.lower().strip();data=_load();roles={**ROLE_PRESETS,**data.get("custom_roles",{})};assigned=str(data.get("assignments",{}).get(key,"")).strip().lower()
    if assigned and assigned in roles:return {"name":assigned,**roles[assigned]}
    if key in roles:return {"name":key,**roles[key]}
    base=key if key in BASE_AGENTS else "general";return {"name":base,"base":base,"instruction":f"Act in the {base} role for this task."}
def configure_custom_role(agent_name:str,role_name:str,instruction:str,base:str|None=None)->dict[str,str]:
    agent_name=agent_name.lower().strip();role_name=role_name.lower().strip();base=(base or agent_name).lower().strip()
    if base not in BASE_AGENTS:base="general"
    instruction=" ".join(str(instruction or "").strip().split())[:8000]
    if not instruction:instruction=f"Act as {role_name}. Adapt your approach and communication to that role while obeying Agentie safety and tool rules."
    data=_load();data.setdefault("custom_roles",{})[role_name]={"base":base,"instruction":instruction};data.setdefault("assignments",{})[agent_name]=role_name;data["updated_at"]=datetime.now().astimezone().isoformat(timespec="seconds");_save(data);return resolve_role(agent_name)
def assign_role(agent_name:str,role_name:str)->dict[str,str]:
    agent_name=agent_name.lower().strip();role_name=role_name.lower().strip();data=_load();roles={**ROLE_PRESETS,**data.get("custom_roles",{})}
    if role_name not in roles:
        base="general"
        for candidate in ["research","coding","github","manager"]:
            if candidate in role_name:base=candidate;break
        data.setdefault("custom_roles",{})[role_name]={"base":base,"instruction":f"Act as {role_name}. Adapt your approach and communication to that role while obeying Agentie safety and tool rules."}
    data.setdefault("assignments",{})[agent_name]=role_name;data["updated_at"]=datetime.now().astimezone().isoformat(timespec="seconds");_save(data);return resolve_role(agent_name)
def clear_role(agent_name:str)->dict[str,str]:
    data=_load();data.setdefault("assignments",{}).pop(agent_name.lower().strip(),None);_save(data);return resolve_role(agent_name)
def list_roles()->dict[str,Any]:
    data=_load();return {"assignments":data.get("assignments",{}),"available":sorted(set(ROLE_PRESETS)|set(data.get("custom_roles",{})))}
def route_role_command(message:str)->dict[str,Any]|None:
    text=" ".join(message.strip().split());lower=text.lower().strip(" .?!")
    if re.search(r"\b(show|list|what are)\b.*\b(agent )?roles?\b",lower):
        state=list_roles();return {"message":"Here are the current agent role assignments.","card":{"type":"agent_roles",**state}}
    # UI/runtime configuration path for conversationally-created agents. This is
    # deliberately a local command so creating or switching an Agentie persona
    # never burns a provider call and the generated instruction becomes the
    # actual system-level runtime role used by build_assistant().
    m=re.match(r'^configure agent (general|research|coding|manager|github) role ([a-z0-9][a-z0-9_-]{1,63}) base (general|research|coding|manager|github) instruction (.+)$',text,re.I)
    if m:
        agent,role,base,instruction=m.group(1),m.group(2),m.group(3),m.group(4).strip()
        resolved=configure_custom_role(agent,role,instruction,base)
        return {"message":f"Configured {agent.title()} agent as {resolved['name']}.","card":{"type":"agent_role","agent":agent,**resolved}}
    patterns=[
        r"\b(?:make|set|assign|change)\s+(?:the\s+)?(general|research|coding|manager|github)(?:\s+agent)?\s+(?:to|as|into)\s+(?:a|an|the)?\s*([a-z][a-z0-9 -]{1,50})$",
        r"\b(?:make|set|assign|change)\s+(?:the\s+)?(general|research|coding|manager|github)(?:\s+agent)?\s+(?:to\s+)?(?:the\s+)?role\s+of\s+(?:a|an|the)?\s*([a-z][a-z0-9 -]{1,50})$",
        r"\b(?:assign|give)\s+(?:the\s+)?(general|research|coding|manager|github)(?:\s+agent)?\s+(?:the\s+)?role\s+(?:of\s+)?(?:a|an|the)?\s*([a-z][a-z0-9 -]{1,50})$",
        r"\b(general|research|coding|manager|github)(?:\s+agent)?\s+should\s+(?:act|work|serve)\s+as\s+(?:a|an|the)?\s*([a-z][a-z0-9 -]{1,50})$",
    ]
    m=None
    for pattern in patterns:
        m=re.search(pattern,lower)
        if m:break
    if m:
        agent,role=m.group(1),m.group(2).strip(" .");resolved=assign_role(agent,role);return {"message":f"{agent.title()} agent is now acting as {resolved['name']}.","card":{"type":"agent_role","agent":agent,**resolved}}
    m=re.search(r"\b(?:reset|clear|remove)\s+(?:the\s+)?(general|research|coding|manager|github)(?:\s+agent)?\s+role\b",lower)
    if m:
        resolved=clear_role(m.group(1));return {"message":f"Reset {m.group(1)} agent to its default role.","card":{"type":"agent_role","agent":m.group(1),**resolved}}
    return None