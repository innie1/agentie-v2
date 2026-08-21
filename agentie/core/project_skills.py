from __future__ import annotations

"""Small built-in project skills following progressive-disclosure principles.

Only metadata is cheap to list. Full instructions are returned only when a project
activates a matching skill. Larger references/templates can be added later without
putting them into every agent prompt.
"""

SKILLS={
 "novel-writing":{"name":"Novel Writing","description":"Long-form fiction projects: story bible, characters, world rules, outline, chapters, continuity and revision.","instructions":"Maintain a story bible, character states, timeline, unresolved setups/payoffs, chapter summaries and current outline. Before drafting, retrieve only the relevant story state. After drafting, update the chapter summary and continuity state. Never rewrite established canon silently; flag contradictions."},
 "screenwriting":{"name":"Screenwriting","description":"Film/TV scripts: premise, acts, sequences, scenes, dialogue, character arcs and screenplay continuity.","instructions":"Track premise, genre promise, character wants/needs, act turns, scene objectives, conflict, reveals and continuity. Draft scene-by-scene; keep dialogue character-specific; record scene summaries and changed story facts after each writing session."},
 "product-building":{"name":"Product Building","description":"Apps and software projects from research through requirements, architecture, implementation and verification.","instructions":"Separate product vision from specialist execution. Research owns evidence, planner/CTO owns requirements and architecture, coder owns implementation details, verifier owns validation. Pass bounded handoff briefs and return compact summaries to the project owner."},
 "business-builder":{"name":"Business Builder","description":"Long-running business projects: market research, model, launch, operations, metrics and reviews.","instructions":"Keep goals, assumptions, market evidence, decisions, milestones, financial facts and experiments separate. Use research for evidence, planning for strategy, analysis for numbers and critique for risks. Update the project brain with decisions and concise outcomes."},
 "life-project-coach":{"name":"Life Project Coach","description":"Long-running personal goals such as learning, habits and fitness with milestones and optional reminders.","instructions":"Clarify the measurable goal, constraints and time horizon. Prefer evidence-based, low-risk planning. Break work into milestones and reviews. Suggest reminders/routines when useful, but never create them without user approval. For health-related goals, avoid diagnosis and unsafe prescriptive claims."},
 "project-planning":{"name":"Project Planning","description":"General long-running project decomposition, delegation, milestones and progress tracking.","instructions":"Clarify the desired outcome and missing constraints, create milestones, delegate by specialty, keep worker chats isolated, and store only durable decisions and concise handoff summaries in shared project memory."},
}

def catalog():return [{"id":k,"name":v["name"],"description":v["description"]} for k,v in SKILLS.items()]
def activate(skill_id:str)->dict|None:
    item=SKILLS.get(str(skill_id or "").strip().lower());return {"id":skill_id,**item} if item else None
