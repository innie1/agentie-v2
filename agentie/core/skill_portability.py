from __future__ import annotations

import json,re
from typing import Any

from agentie.core.file_service import resolve_upload,save_upload
from agentie.core.workflow_skills import create_workflow_skill,get_workflow_skill,skill_card

FORMAT="agentie.workflow-skill";VERSION=1
_FIELDS=("name","description","when_to_use","required_inputs","required_access","steps","decision_rules","expected_output","validation_rules","approval_boundaries","failure_handling")
_LIST_FIELDS=("required_inputs","required_access","steps","decision_rules","validation_rules","approval_boundaries")

def export_skill(name_or_id:str)->dict[str,Any]:
    skill=get_workflow_skill(name_or_id)
    if not skill:raise ValueError("Workflow skill was not found.")
    payload={"format":FORMAT,"format_version":VERSION,"skill":{key:skill.get(key) for key in _FIELDS},"source":{"kind":"taught" if skill.get("source_workflow_id") else "manual"}}
    safe=re.sub(r"[^a-z0-9_-]+","-",str(skill.get("name") or "skill").casefold()).strip("-") or "skill";card=save_upload(f"agentie-skill-{safe}.json",json.dumps(payload,indent=2,ensure_ascii=False).encode("utf-8"));return {"skill":skill,"manifest":payload,"card":card}
def _manifest(data:Any)->dict[str,Any]:
    if not isinstance(data,dict):raise ValueError("Skill import must be a JSON object.")
    if data.get("format")!=FORMAT:raise ValueError("This JSON is not an Agentie workflow Skill export.")
    try:version=int(data.get("format_version") or 0)
    except Exception:version=0
    if version!=VERSION:raise ValueError(f"Unsupported Agentie Skill export version: {version}.")
    skill=data.get("skill")
    if not isinstance(skill,dict):raise ValueError("Skill export is missing its skill object.")
    for field in _LIST_FIELDS:
        value=skill.get(field,[])
        if value is not None and not isinstance(value,list):raise ValueError(f"Imported Skill field '{field}' must be a list.")
    return skill
def _items(raw:dict[str,Any],field:str)->list[str]:return [str(x) for x in (raw.get(field) or []) if str(x).strip()]
def import_skill_from_upload(filename:str,*,status:str="draft")->dict[str,Any]:
    path=resolve_upload(filename)
    if path.suffix.lower()!=".json":raise ValueError("Skill import currently accepts an Agentie JSON export.")
    try:data=json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:raise ValueError("Skill export is not valid JSON.") from exc
    raw=_manifest(data);name=str(raw.get("name") or "").strip()
    if not name:raise ValueError("Imported Skill has no name.")
    existing=get_workflow_skill(name)
    if existing:raise ValueError(f"A workflow Skill named “{name}” already exists. Rename or remove the existing Skill first.")
    item=create_workflow_skill(name=name,description=str(raw.get("description") or ""),when_to_use=str(raw.get("when_to_use") or ""),required_inputs=_items(raw,"required_inputs"),required_access=_items(raw,"required_access"),steps=_items(raw,"steps"),decision_rules=_items(raw,"decision_rules"),expected_output=str(raw.get("expected_output") or ""),validation_rules=_items(raw,"validation_rules"),approval_boundaries=_items(raw,"approval_boundaries"),failure_handling=str(raw.get("failure_handling") or ""),source_workflow_id=None,status=status)
    return item
def route_skill_portability_command(message:str)->dict[str,Any]|None:
    text=" ".join(str(message or "").strip().split())
    m=re.match(r"^(?:export|share)\s+(?:workflow\s+)?skill\s+(.+)$",text,re.I)
    if m:
        try:result=export_skill(m.group(1).strip(' .?!\"“”'))
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"Exported Skill “{result['skill']['name']}” as a portable Agentie JSON file.","card":result["card"]}
    m=re.match(r"^(?:import|install)\s+(?:workflow\s+)?skill\s+(?:from\s+)?(.+\.json)$",text,re.I)
    if m:
        try:item=import_skill_from_upload(m.group(1).strip(' .?!\"“”'))
        except (ValueError,FileNotFoundError) as exc:return {"message":str(exc),"card":None}
        return {"message":f"Imported Skill “{item['name']}” as a draft. Review it before activation.","card":skill_card(item)}
    return None
