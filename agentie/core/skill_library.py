from __future__ import annotations

import re
from typing import Any

from agentie.core.agent_registry import get_agent
from agentie.core.agent_access import set_skill_access
from agentie.core.skill_portability import export_skill,import_skill_from_upload
from agentie.core.workflow_skills import create_workflow_skill,get_workflow_skill,list_workflow_skills,set_workflow_skill_status,skill_card

_TEMPLATES={
    "weekly-report":{"name":"Weekly Report","description":"Collect the week's relevant results, summarize changes, risks, wins and next actions.","when_to_use":"When a recurring weekly operating report is needed.","required_inputs":["report scope"],"required_access":[],"steps":["Gather authoritative results for the requested scope","Separate facts from recommendations","Summarize wins, problems, metrics and unresolved risks","List next actions and owners","Validate that every claimed result is supported by available context"],"decision_rules":["Do not invent missing metrics; mark them unavailable","Escalate consequential recommendations for approval before execution"],"expected_output":"A concise verified weekly report with facts, risks, recommendations and next actions.","validation_rules":["No fabricated metrics","Owners and unresolved blockers are explicit"]},
    "competitor-research":{"name":"Competitor Research","description":"Research competitors and produce a sourced comparison and actionable gaps.","when_to_use":"When comparing a market, product or competitor set.","required_inputs":["market or competitor scope"],"required_access":["research"],"steps":["Define the comparison criteria","Gather current sources","Compare competitors against the criteria","Separate sourced facts from inference","Identify defensible opportunities and risks"],"decision_rules":["Prefer recent primary or reputable sources","Say when a claim cannot be verified"],"expected_output":"A sourced competitor comparison with opportunities, risks and recommended next actions.","validation_rules":["Material factual claims are sourced","Recommendations are clearly labeled"]},
    "inbox-triage":{"name":"Inbox Triage","description":"Review an inbox, prioritize messages, draft replies and surface items needing approval.","when_to_use":"When an assigned agent needs to process incoming email or support messages.","required_inputs":["inbox scope"],"required_access":["email"],"steps":["Read the new messages in scope","Group by urgency and ownership","Draft safe replies where appropriate","Flag consequential sends, refunds, legal or financial issues for approval","Return a prioritized action list"],"decision_rules":["Never send externally without the configured approval boundary","Escalate ambiguous high-risk messages"],"expected_output":"Prioritized inbox summary, drafts and approval-needed actions.","validation_rules":["Every action maps to a real message","No external send is falsely reported"]},
    "quality-review":{"name":"Quality Review","description":"Review a deliverable against explicit requirements before release.","when_to_use":"Before publishing, shipping, submitting or handing off important work.","required_inputs":["deliverable","requirements"],"required_access":[],"steps":["Extract the acceptance criteria","Check the deliverable criterion by criterion","Record defects or uncertainty","Recommend fixes in priority order","Re-check critical criteria before declaring ready"],"decision_rules":["A failed critical criterion blocks a ready recommendation","Do not call unverified work complete"],"expected_output":"Pass/fail review with defects, evidence and release recommendation.","validation_rules":["Each acceptance criterion has a result"]},
    "customer-follow-up":{"name":"Customer Follow-up","description":"Prepare a context-aware customer follow-up while preserving approval boundaries.","when_to_use":"When following up with a customer after an order, conversation or unresolved issue.","required_inputs":["customer context","follow-up goal"],"required_access":[],"steps":["Review the bounded customer context","Identify the unresolved need or desired outcome","Draft a concise personalized follow-up","Flag promises, discounts, refunds or commitments that need approval","Return the draft and recommended next step"],"decision_rules":["Do not invent customer history","Do not make unapproved commitments"],"expected_output":"A customer-specific follow-up draft plus recommended next action.","validation_rules":["Draft only uses available customer context"]},
}

def list_library()->dict[str,Any]:
    skills=list_workflow_skills();return {"skills":[skill_card(x) for x in skills],"templates":[{"id":sid,**{k:v for k,v in item.items() if k in {"name","description","when_to_use","required_access"}},"installed":bool(get_workflow_skill(item["name"]))} for sid,item in _TEMPLATES.items()]}
def install_template(template_id:str)->dict[str,Any]:
    tid=str(template_id or "").strip().casefold();template=_TEMPLATES.get(tid)
    if not template:raise ValueError("Skill template was not found.")
    existing=get_workflow_skill(template["name"])
    if existing:return existing
    return create_workflow_skill(**template,status="draft",approval_boundaries=["Use Agentie's normal approval path for consequential actions."],failure_handling="Stop on a real failure, report what failed, and ask for missing input or permission instead of pretending completion.")
def duplicate_skill(name_or_id:str,new_name:str)->dict[str,Any]:
    source=get_workflow_skill(name_or_id)
    if not source:raise ValueError("Workflow skill was not found.")
    clean=" ".join(str(new_name or "").strip().split())[:120]
    if not clean:raise ValueError("Give the duplicated Skill a new name.")
    if get_workflow_skill(clean):raise ValueError("A workflow Skill with that name already exists.")
    return create_workflow_skill(name=clean,description=str(source.get("description") or ""),when_to_use=str(source.get("when_to_use") or ""),required_inputs=list(source.get("required_inputs") or []),required_access=list(source.get("required_access") or []),steps=list(source.get("steps") or []),decision_rules=list(source.get("decision_rules") or []),expected_output=str(source.get("expected_output") or ""),validation_rules=list(source.get("validation_rules") or []),approval_boundaries=list(source.get("approval_boundaries") or []),failure_handling=str(source.get("failure_handling") or ""),source_workflow_id=None,status="draft")
def assign_skill(name_or_id:str,agent_id_or_name:str)->dict[str,Any]:
    skill=get_workflow_skill(name_or_id);agent=get_agent(agent_id_or_name)
    if not skill:raise ValueError("Workflow skill was not found.")
    if not agent:raise ValueError("Agent was not found.")
    set_skill_access(agent["id"],skill["id"],"allow")
    return {"skill":skill_card(skill),"agent":{"id":agent["id"],"name":agent["name"],"job":agent.get("role")}}
def route_skill_library_command(message:str)->dict[str,Any]|None:
    text=" ".join(str(message or "").strip().split());lower=text.casefold().strip(" .?!")
    if lower in {"skill library","show skill library","open skill library","list reusable skills","browse skills"}:
        data=list_library();return {"message":f"Skill Library has {len(data['skills'])} reusable Skill(s) and {len(data['templates'])} starter template(s).","card":{"type":"note","title":"Skill Library","content":"\n".join([f"Installed: {len(data['skills'])}",f"Starter templates: {len(data['templates'])}","Use the Skill Library UI to install, assign, duplicate, export or import Skills."])},"library":data}
    m=re.match(r"^(?:install|add)\s+(?:skill\s+)?template\s+(.+)$",text,re.I)
    if m:
        wanted=m.group(1).strip(' .?!\"“”');tid=next((k for k,v in _TEMPLATES.items() if k==wanted.casefold() or v['name'].casefold()==wanted.casefold()),wanted.casefold())
        try:item=install_template(tid)
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"Installed “{item['name']}” as a draft Skill. Review it before activation.","card":skill_card(item)}
    m=re.match(r"^(?:duplicate|copy)\s+skill\s+(.+?)\s+(?:as|to|called|named)\s+(.+)$",text,re.I)
    if m:
        try:item=duplicate_skill(m.group(1).strip(),m.group(2).strip())
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"Duplicated Skill as “{item['name']}” in draft state.","card":skill_card(item)}
    m=re.match(r"^(?:assign|give)\s+skill\s+(.+?)\s+(?:to|for)\s+(?:agent\s+)?(.+)$",text,re.I)
    if m:
        try:result=assign_skill(m.group(1).strip(),m.group(2).strip())
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"Assigned “{result['skill']['name']}” to {result['agent']['name']}.","card":result['skill']}
    return None
