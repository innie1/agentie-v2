from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

WORKSPACE=Path.cwd()/"workspace";SKILLS_DIR=WORKSPACE/"skills"

def _now():return datetime.now().astimezone().isoformat(timespec="seconds")
def _clean(value,limit=4000):return " ".join(str(value or "").strip().split())[:limit]
def _sid(value):
    base=re.sub(r"[^a-z0-9_-]+","-",str(value or "").casefold()).strip("-")[:80]
    return base or "skill-"+uuid.uuid4().hex[:8]
def _path(sid):return SKILLS_DIR/_sid(sid)/"skill.json"
def _write(item):
    path=_path(item["id"]);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(item,indent=2,ensure_ascii=False),encoding="utf-8");return item

def create_workflow_skill(*,name:str,description:str="",when_to_use:str="",required_inputs:list[str]|None=None,required_access:list[str]|None=None,steps:list[str]|None=None,decision_rules:list[str]|None=None,expected_output:str="",validation_rules:list[str]|None=None,approval_boundaries:list[str]|None=None,failure_handling:str="",source_workflow_id:str|None=None,status:str="draft",skill_id:str|None=None)->dict[str,Any]:
    name=_clean(name,120)
    if not name:raise ValueError("Skill name is required.")
    sid=_sid(skill_id or name);path=_path(sid)
    existing=None
    if path.exists():
        try:existing=json.loads(path.read_text(encoding="utf-8"))
        except Exception:existing=None
    item={
        "id":sid,"name":name,"description":_clean(description or f"Reusable workflow: {name}",1200),
        "agents":["*"],"capabilities":["workflow_skill"],"permissions":[],"enabled":status=="active",
        "kind":"workflow","status":status if status in {"draft","active","paused"} else "draft","version":"2.0",
        "when_to_use":_clean(when_to_use or description,1200),
        "required_inputs":[_clean(x,300) for x in (required_inputs or []) if _clean(x,300)],
        "required_access":[_clean(x,200) for x in (required_access or []) if _clean(x,200)],
        "steps":[_clean(x,1000) for x in (steps or []) if _clean(x,1000)],
        "decision_rules":[_clean(x,700) for x in (decision_rules or []) if _clean(x,700)],
        "expected_output":_clean(expected_output,1200),
        "validation_rules":[_clean(x,700) for x in (validation_rules or []) if _clean(x,700)],
        "approval_boundaries":[_clean(x,700) for x in (approval_boundaries or []) if _clean(x,700)],
        "failure_handling":_clean(failure_handling or "Stop on a real failure, report what failed, and ask for missing input or permission instead of pretending the workflow completed.",1200),
        "source_workflow_id":source_workflow_id,
        "created_at":(existing or {}).get("created_at") or _now(),"updated_at":_now(),
    }
    return _write(item)

def get_workflow_skill(name_or_id:str)->dict[str,Any]|None:
    needle=str(name_or_id or "").strip().casefold()
    if not needle:return None
    for item in list_workflow_skills():
        if str(item.get("id") or "").casefold()==needle or str(item.get("name") or "").casefold()==needle:return item
    return None

def list_workflow_skills(status:str|None=None)->list[dict[str,Any]]:
    SKILLS_DIR.mkdir(parents=True,exist_ok=True);items=[]
    for path in SKILLS_DIR.glob("*/skill.json"):
        try:item=json.loads(path.read_text(encoding="utf-8"))
        except Exception:continue
        if str(item.get("kind") or "")!="workflow":continue
        if status and str(item.get("status") or "")!=status:continue
        items.append(item)
    return sorted(items,key=lambda x:str(x.get("name") or "").casefold())

def set_workflow_skill_status(name_or_id:str,status:str)->dict[str,Any]:
    item=get_workflow_skill(name_or_id)
    if not item:raise ValueError("Workflow skill was not found.")
    status=str(status or "").casefold()
    if status not in {"draft","active","paused"}:raise ValueError("Skill status must be draft, active, or paused.")
    item["status"]=status;item["enabled"]=status=="active";item["updated_at"]=_now();return _write(item)

def delete_workflow_skill(name_or_id:str)->dict[str,Any]:
    item=get_workflow_skill(name_or_id)
    if not item:raise ValueError("Workflow skill was not found.")
    path=_path(str(item["id"]));shutil.rmtree(path.parent,ignore_errors=True);return item

def draft_skill_from_taught_workflow(workflow:dict[str,Any])->dict[str,Any]:
    steps=[str(step.get("command") or "").strip() for step in workflow.get("steps") or [] if str(step.get("command") or "").strip()]
    protected=[str((step.get("metadata") or {}).get("field") or "protected value") for step in workflow.get("steps") or [] if (step.get("metadata") or {}).get("requires_input")]
    boundaries=["Request normal Agentie approval before consequential actions encountered during replay."]
    if protected:boundaries.append("Never store protected values. Ask the user to provide them at runtime: "+", ".join(protected))
    return create_workflow_skill(name=str(workflow.get("name") or "Taught workflow"),description=f"Reusable skill learned from a user demonstration of {workflow.get('name') or 'a browser workflow'}.",when_to_use=f"Use when the user asks to perform or repeat {workflow.get('name') or 'this taught workflow'}.",required_inputs=protected,required_access=["browser/computer session"],steps=steps,decision_rules=["Use the recorded sequence as the default path; if the target UI has changed, stop and report the mismatch rather than clicking uncertain controls."],expected_output=f"Complete {workflow.get('name') or 'the workflow'} and report the real result.",validation_rules=["Confirm each required page/action was reached before reporting completion."],approval_boundaries=boundaries,failure_handling="Stop at the first unsafe or unresolvable UI mismatch and report the last successful step.",source_workflow_id=str(workflow.get("id") or "") or None,status="draft")

def skill_card(item:dict[str,Any])->dict[str,Any]:
    return {"type":"workflow_skill","id":item.get("id"),"name":item.get("name"),"description":item.get("description"),"status":item.get("status"),"when_to_use":item.get("when_to_use"),"required_inputs":item.get("required_inputs") or [],"required_access":item.get("required_access") or [],"steps":item.get("steps") or [],"decision_rules":item.get("decision_rules") or [],"expected_output":item.get("expected_output"),"validation_rules":item.get("validation_rules") or [],"approval_boundaries":item.get("approval_boundaries") or [],"failure_handling":item.get("failure_handling"),"source_workflow_id":item.get("source_workflow_id"),"enabled":bool(item.get("enabled"))}

def _words(value):return {x for x in re.findall(r"[a-z0-9]+",str(value or "").casefold()) if len(x)>2}
def matching_workflow_skills(message:str,agent:dict[str,Any]|None=None,limit:int=3)->list[dict[str,Any]]:
    q=_words(message);scored=[]
    for item in list_workflow_skills("active"):
        if agent:
            try:
                from agentie.core.agent_access import skill_allowed
                if not skill_allowed(agent,str(item["id"])):continue
            except Exception:pass
        text=" ".join([str(item.get("name") or ""),str(item.get("description") or ""),str(item.get("when_to_use") or "")," ".join(map(str,item.get("steps") or []))]);words=_words(text);score=len(q&words)
        if score:scored.append((score,item))
    scored.sort(key=lambda x:(-x[0],str(x[1].get("name") or "").casefold()));return [item for _,item in scored[:max(1,limit)]]

def instruction_block(item:dict[str,Any])->str:
    lines=[f"REUSABLE SKILL: {item.get('name')}"]
    if item.get("when_to_use"):lines.append("When to use: "+str(item["when_to_use"]))
    if item.get("required_inputs"):lines.append("Required inputs: "+", ".join(map(str,item["required_inputs"])))
    if item.get("required_access"):lines.append("Required access: "+", ".join(map(str,item["required_access"])))
    if item.get("steps"):lines.append("Steps:\n- "+"\n- ".join(map(str,item["steps"])))
    if item.get("decision_rules"):lines.append("Decision rules:\n- "+"\n- ".join(map(str,item["decision_rules"])))
    if item.get("expected_output"):lines.append("Expected output: "+str(item["expected_output"]))
    if item.get("validation_rules"):lines.append("Validation:\n- "+"\n- ".join(map(str,item["validation_rules"])))
    if item.get("approval_boundaries"):lines.append("Approval boundaries:\n- "+"\n- ".join(map(str,item["approval_boundaries"])))
    if item.get("failure_handling"):lines.append("Failure handling: "+str(item["failure_handling"]))
    return "\n".join(lines)
