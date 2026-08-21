from __future__ import annotations
import json,re
from datetime import datetime
from pathlib import Path
from typing import Any
from agentie.core.agent_registry import create_agent,delete_agent,get_agent,hierarchy,list_agents,set_agent_avatar,set_agent_pinned,update_agent_manager,update_agent_profile
from agentie.core.agent_prompt import instruction_card,learning_audit,set_manual_instructions
from agentie.core.deletion_registry import find_deleted
from agentie.core.team_orchestrator import route_team_command
from agentie.tools.approval_tools import approval_is_granted,create_approval
WORKSPACE=Path.cwd()/"workspace";ROLES=WORKSPACE/"agent_roles.json";BASE_AGENTS={"general","research","coding","manager","github"}
ROLE_PRESETS={"researcher":{"base":"research","instruction":"Act as a rigorous researcher. Gather evidence, compare sources, and distinguish fact from inference."},"critic":{"base":"research","instruction":"Act as a skeptical critic. Look for weaknesses, contradictions, missing evidence, and failure modes."},"verifier":{"base":"research","instruction":"Act as a verifier. Check claims against evidence and flag unsupported assertions."},"data analyst":{"base":"coding","instruction":"Act as a data analyst. Prefer reproducible calculations, code, tables, and explicit assumptions."},"document writer":{"base":"general","instruction":"Act as a professional document writer. Turn source material into clear, structured deliverables."},"planner":{"base":"manager","instruction":"Act as a planner. Decompose goals, assign work, track dependencies, and minimize unnecessary provider calls."},"coder":{"base":"coding","instruction":"Act as a software engineer. Inspect, implement, test, and explain code changes carefully."},"github reviewer":{"base":"github","instruction":"Act as a GitHub reviewer. Inspect repository state, changes, issues, and implementation risks."}}
def _load():
    try:return json.loads(ROLES.read_text(encoding="utf-8")) if ROLES.exists() else {"assignments":{},"custom_roles":{}}
    except Exception:return {"assignments":{},"custom_roles":{}}
def _save(data):ROLES.parent.mkdir(parents=True,exist_ok=True);ROLES.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
def resolve_role(agent_name):
    key=agent_name.lower().strip();data=_load();roles={**ROLE_PRESETS,**data.get("custom_roles",{})};assigned=str(data.get("assignments",{}).get(key,"")).strip().lower()
    if assigned and assigned in roles:return {"name":assigned,**roles[assigned]}
    if key in roles:return {"name":key,**roles[key]}
    base=key if key in BASE_AGENTS else "general";return {"name":base,"base":base,"instruction":f"Act in the {base} role for this task."}
def assign_role(agent_name,role_name):
    agent_name=agent_name.lower().strip();role_name=role_name.lower().strip();data=_load();roles={**ROLE_PRESETS,**data.get("custom_roles",{})}
    if role_name not in roles:
        base="general"
        for candidate in ["research","coding","github","manager"]:
            if candidate in role_name:base=candidate;break
        data.setdefault("custom_roles",{})[role_name]={"base":base,"instruction":f"Act as {role_name}. Adapt your approach and communication to that role while obeying Agentie safety and tool rules."}
    data.setdefault("assignments",{})[agent_name]=role_name;data["updated_at"]=datetime.now().astimezone().isoformat(timespec="seconds");_save(data);return resolve_role(agent_name)
def clear_role(agent_name):
    data=_load();data.setdefault("assignments",{}).pop(agent_name.lower().strip(),None);_save(data);return resolve_role(agent_name)
def list_roles():
    data=_load();return {"assignments":data.get("assignments",{}),"available":sorted(set(ROLE_PRESETS)|set(data.get("custom_roles",{})))}
def _base_for_role(role_name):
    role=role_name.lower().strip();data=_load();roles={**ROLE_PRESETS,**data.get("custom_roles",{})}
    if role in roles:return str(roles[role].get("base") or "general")
    if any(x in role for x in ("cto","chief technology","engineering manager","tech lead","manager","chief of staff","ceo","director","lead")):return "manager"
    if any(x in role for x in ("research","analyst","critic","verifier")):return "research"
    if any(x in role for x in ("coder","developer","engineer","programmer","data")):return "coding"
    if "github" in role:return "github"
    return "general"
def _agent_creation_command(text):
    named=re.match(r"^(?:please\s+)?(?:create|make|add)\s+(?:an?\s+)?agent\s+(?:called|named)\s+(.+?)\s+(?:who\s+is|as|to\s+be)\s+(?:my\s+|the\s+)?(.+?)[.!?]?$",text,re.I)
    if named:
        name=named.group(1).strip(' \"“”');role=named.group(2).strip(' \"“”');result=create_agent(name,role,_base_for_role(role));agent=result["agent"];return {"message":f"{'Created' if result['created'] else 'Found existing'} agent {agent['name']} as {agent['role']}.","card":{"type":"agent_profile",**agent}}
    simple=re.match(r"^(?:please\s+)?(?:create|make|add)\s+(?:an?\s+)?agent\s+(?:called|named)\s+(.+?)[.!?]?$",text,re.I)
    if simple:
        name=simple.group(1).strip(' \"“”');result=create_agent(name,"general","general");agent=result["agent"];return {"message":f"{'Created' if result['created'] else 'Found existing'} agent {agent['name']}.","card":{"type":"agent_profile",**agent}}
    role_only=re.match(r"^(?:please\s+)?(?:create|make|add)\s+(?:me\s+)?(?:an?\s+)?(.+?)\s+agent(?:\s+for\s+(.+?))?[.!?]?$",text,re.I)
    if role_only:
        role=role_only.group(1).strip(' \"“”');purpose=(role_only.group(2) or "").strip(' \"“”');name=role.title();result=create_agent(name,role,_base_for_role(role),purpose=purpose);agent=result["agent"];return {"message":f"{'Created' if result['created'] else 'Found existing'} {agent['name']} agent.","card":{"type":"agent_profile",**agent}}
    return None
def _manual_instruction_payload(agent_name,payload):
    value=str(payload or "").strip();nested=re.match(rf"^(?:set|update|change|edit)\s+(?:agent\s+)?{re.escape(str(agent_name))}(?:['’]s)?\s+(?:system\s+prompt|instructions|prompt)\s+(?:to|as)\s+(.+)$",value,re.I);return (nested.group(1) if nested else value).strip()
def _profile_response(agent,message):return {"message":message,"card":{"type":"agent_profile",**agent}}
def route_role_command(message):
    text=" ".join(message.strip().split());lower=text.lower().strip(" .?!");team=route_team_command(text)
    if team is not None:return team
    created=_agent_creation_command(text)
    if created is not None:return created
    pin_match=re.match(r"^(pin|unpin)\s+(?:agent\s+)?(.+?)[.!?]?$",text,re.I)
    if pin_match:
        requested=pin_match.group(2).strip(' .?!\"“”');target=get_agent(requested)
        if not target:return {"message":"Agent was not found.","card":None}
        pinned=pin_match.group(1).casefold()=="pin";agent=set_agent_pinned(target["id"],pinned)
        return {"message":f"{agent['name']} {'pinned to the top' if pinned else 'unpinned'}.","card":{"type":"agent_profile",**agent}}
    audit=re.match(r"^(?:show|view|what has|what did)\s+(?:agent\s+)?(.+?)(?:['’]s)?\s+(?:learning audit|learned history|instruction history|learned)[.!?]?$",text,re.I)
    if audit:
        agent=get_agent(audit.group(1).strip())
        if not agent:return {"message":"Agent was not found.","card":None}
        items=learning_audit(agent);return {"message":f"{agent['name']} has {len(items)} recorded instruction-learning change(s).","card":{"type":"agent_learning_audit","agent_id":agent['id'],"name":agent['name'],"items":items}}
    view=re.match(r"^(?:show|view|open|inspect)\s+(?:agent\s+)?(.+?)(?:['’]s)?\s+(?:system\s+prompt|instructions|prompt)[.!?]?$",text,re.I)
    if view:
        agent=get_agent(view.group(1).strip())
        if not agent:return {"message":"Agent was not found.","card":None}
        return {"message":f"Here are {agent['name']}'s instructions.","card":instruction_card(agent)}
    edit=re.match(r"^(?:set|update|change|edit)\s+(?:agent\s+)?(.+?)(?:['’]s)?\s+(?:system\s+prompt|instructions|prompt)\s+(?:to|as)\s+(.+)$",text,re.I)
    if edit:
        agent=get_agent(edit.group(1).strip())
        if not agent:return {"message":"Agent was not found.","card":None}
        payload=_manual_instruction_payload(agent['name'],edit.group(2));set_manual_instructions(agent,payload);return {"message":f"Updated {agent['name']}'s user instructions.","card":instruction_card(agent)}
    avatar_file=re.match(r"^(?:set|update|change)\s+(?:agent\s+)?(.+?)(?:['’]s)?\s+avatar\s+file\s+(?:to|as)\s+(.+?)[.!?]?$",text,re.I)
    if avatar_file:
        try:agent=set_agent_avatar(avatar_file.group(1).strip(),"uploaded",avatar_file.group(2).strip(' \"“”'))
        except ValueError as exc:return {"message":str(exc),"card":None}
        return _profile_response(agent,f"Updated {agent['name']}'s avatar.")
    avatar_mode=re.match(r"^(?:set|update|change)\s+(?:agent\s+)?(.+?)(?:['’]s)?\s+avatar\s+(?:to|as)\s+(default|generated)[.!?]?$",text,re.I)
    if avatar_mode:
        try:agent=set_agent_avatar(avatar_mode.group(1).strip(),avatar_mode.group(2).lower())
        except ValueError as exc:return {"message":str(exc),"card":None}
        return _profile_response(agent,f"Updated {agent['name']}'s avatar.")
    responsibilities=re.match(r"^(?:set|update|change|edit)\s+(?:agent\s+)?(.+?)(?:['’]s)?\s+responsibilities\s+(?:to|as)\s+(.+)$",text,re.I)
    if responsibilities:
        values=[x.strip() for x in re.split(r"\s*[|;]\s*",responsibilities.group(2)) if x.strip()]
        try:agent=update_agent_profile(responsibilities.group(1).strip(),responsibilities=values)
        except ValueError as exc:return {"message":str(exc),"card":None}
        return _profile_response(agent,f"Updated {agent['name']}'s responsibilities.")
    field_edit=re.match(r"^(?:set|update|change|edit)\s+(?:agent\s+)?(.+?)(?:['’]s)?\s+(personality|goal|company identity)\s+(?:to|as)\s+(.+)$",text,re.I)
    if field_edit:
        target=field_edit.group(1).strip();field=field_edit.group(2).lower();value=field_edit.group(3).strip()
        kwargs={"personality":value} if field=="personality" else {"goal":value} if field=="goal" else {"company_identity":value}
        try:agent=update_agent_profile(target,**kwargs)
        except ValueError as exc:return {"message":str(exc),"card":None}
        label="company identity" if field=="company identity" else field
        return _profile_response(agent,f"Updated {agent['name']}'s {label}.")
    field_clear=re.match(r"^(?:clear|remove)\s+(?:agent\s+)?(.+?)(?:['’]s)?\s+(personality|goal|company identity|responsibilities)[.!?]?$",text,re.I)
    if field_clear:
        target=field_clear.group(1).strip();field=field_clear.group(2).lower();kwargs={"responsibilities":[]} if field=="responsibilities" else {"company_identity":""} if field=="company identity" else {field:""}
        try:agent=update_agent_profile(target,**kwargs)
        except ValueError as exc:return {"message":str(exc),"card":None}
        return _profile_response(agent,f"Cleared {agent['name']}'s {field}.")
    rename=re.match(r"^(?:rename|change (?:the )?name of)\s+(?:agent\s+)?(.+?)\s+(?:to|as)\s+(.+?)[.!?]?$",text,re.I)
    if rename:
        try:agent=update_agent_profile(rename.group(1).strip(),name=rename.group(2).strip())
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"Renamed agent to {agent['name']}.","card":{"type":"agent_profile",**agent}}
    role_edit=re.match(r"^(?:change|set|update)\s+(?:agent\s+)?(.+?)(?:['’]s)?\s+(?:title|role)\s+(?:to|as)\s+(.+?)[.!?]?$",text,re.I)
    if role_edit:
        try:agent=update_agent_profile(role_edit.group(1).strip(),role=role_edit.group(2).strip(),base=_base_for_role(role_edit.group(2)))
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"Updated {agent['name']} to {agent['role']}.","card":{"type":"agent_profile",**agent}}
    delete_match=re.match(r"^(?:please\s+)?(?:delete|remove)\s+agent\s+(.+?)[.!?]?$",text,re.I)
    if delete_match:
        requested=delete_match.group(1).strip(' .?!\"“”');target=get_agent(requested)
        if not target:
            tomb=find_deleted("agent",requested,Path.cwd()/"workspace"/"deletions.json")
            if tomb:return {"message":f"{tomb.get('name') or requested} was already deleted. No second delete action was performed.","card":{"type":"already_deleted","entity_type":"agent","names":[tomb.get('name') or requested],"deleted_at":tomb.get('deleted_at')}}
            return {"message":"Agent was not found.","card":None}
        action=f"delete_agent:{target['id']}"
        if not approval_is_granted(action):approval=create_approval(action,f"Permanently delete {target['name']} and all of this agent's private memories, chats, semantic shards and agent-owned data.",{"kind":"agent_delete","agent_id":target["id"],"agent_name":target["name"]});return {"message":f"Deleting {target['name']} is permanent. Approve the deletion to continue.","card":{"type":"approvals","items":[approval]}}
        result=delete_agent(target["id"])
        if result.get("already_deleted"):return {"message":f"{target['name']} was already deleted. No second delete action was performed.","card":{"type":"already_deleted","entity_type":"agent","names":[target['name']]}}
        p=result["purged"];return {"message":f"Deleted {target['name']} permanently, including {p.get('memories',0)} memories, {p.get('messages',0)} chat messages and {p.get('semantic_items',0)} semantic memory items.","card":{"type":"agent_deleted","id":target["id"],"name":target["name"],"purged":p}}
    if lower in {"agents","show agents","list agents","show my agents","list my agents","agent directory","show agent directory"}:items=list_agents();return {"message":f"You have {len(items)} persistent agent(s).","card":{"type":"agents","items":items}}
    m=re.match(r"^(?:show|inspect|open)\s+(?:agent\s+)?(.+)$",text,re.I)
    if m and "roles" not in lower:
        agent=get_agent(m.group(1).strip(' .?!\"“”'))
        if agent:return {"message":f"Here is {agent['name']}.","card":{"type":"agent_profile",**agent}}
    if lower in {"show agent hierarchy","agent hierarchy","show company hierarchy","company hierarchy","org chart","show org chart"}:return {"message":"Here is the current agent hierarchy.","card":{"type":"agent_hierarchy","items":hierarchy()}}
    manager=re.match(r"^(?:set|make|assign)\s+(.+?)['’]?s\s+manager\s+(?:to|as)\s+(.+?)[.!?]?$",text,re.I) or re.match(r"^(?:make|set)\s+(.+?)\s+report\s+to\s+(.+?)[.!?]?$",text,re.I)
    if manager:
        try:agent=update_agent_manager(manager.group(1).strip(),manager.group(2).strip())
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"{agent['name']} now reports to {manager.group(2).strip()}.","card":{"type":"agent_profile",**agent}}
    if re.search(r"\b(show|list|what are)\b.*\b(agent )?roles?\b",lower):state=list_roles();return {"message":"Here are the current agent role assignments.","card":{"type":"agent_roles",**state}}
    patterns=[r"\b(?:make|set|assign|change)\s+(?:the\s+)?(general|research|coding|manager|github)(?:\s+agent)?\s+(?:to|as|into)\s+(?:a|an|the)?\s*([a-z][a-z0-9 -]{1,50})$",r"\b(?:make|set|assign|change)\s+(?:the\s+)?(general|research|coding|manager|github)(?:\s+agent)?\s+(?:to\s+)?(?:the\s+)?role\s+of\s+(?:a|an|the)?\s*([a-z][a-z0-9 -]{1,50})$",r"\b(?:assign|give)\s+(?:the\s+)?(general|research|coding|manager|github)(?:\s+agent)?\s+(?:the\s+)?role\s+(?:of\s+)?(?:a|an|the)?\s*([a-z][a-z0-9 -]{1,50})$",r"\b(general|research|coding|manager|github)(?:\s+agent)?\s+should\s+(?:act|work|serve)\s+as\s+(?:a|an|the)?\s*([a-z][a-z0-9 -]{1,50})$"]
    m=next((re.search(p,lower) for p in patterns if re.search(p,lower)),None)
    if m:
        agent,role=m.group(1),m.group(2).strip(" .");resolved=assign_role(agent,role);return {"message":f"{agent.title()} agent is now acting as {resolved['name']}.","card":{"type":"agent_role","agent":agent,**resolved}}
    m=re.search(r"\b(?:reset|clear|remove)\s+(?:the\s+)?(general|research|coding|manager|github)(?:\s+agent)?\s+role\b",lower)
    if m:resolved=clear_role(m.group(1));return {"message":f"Reset {m.group(1)} agent to its default role.","card":{"type":"agent_role","agent":m.group(1),**resolved}}
    return None
