from __future__ import annotations

import re
from difflib import get_close_matches
from typing import Any

from agentie.core.agent_prompt import learn_from_user_message


_ACKS={
    "got it":"Got it.","understood":"Understood.","okay":"Okay.","ok":"Okay.","sure":"Sure.",
    "yes":"Got it.","no":"Okay.","thanks":"You’re welcome.","thank you":"You’re welcome.",
    "hi":"Hi. What would you like to work on?","hello":"Hello. What would you like to work on?","hey":"Hey. What would you like to work on?",
}


def _normalized(text:str)->str:
    value=text.casefold().strip();value=re.sub(r"[^a-z0-9 ]+"," ",value);return re.sub(r"\s+"," ",value).strip()


def try_npc_response(agent:dict[str,Any],message:str)->dict[str,Any]|None:
    """Cheap, deterministic local brain for preference learning and tiny conversational turns."""
    learned=learn_from_user_message(agent,message)
    if learned:
        return {"message":"Got it. I’ll remember that for how I work with you.","routed_by":"npc_brain","learned":learned}
    norm=_normalized(message)
    if not norm or len(norm.split())>10:return None
    if norm in _ACKS:return {"message":_ACKS[norm],"routed_by":"npc_brain"}
    hit=get_close_matches(norm,list(_ACKS),n=1,cutoff=.88)
    if hit:return {"message":_ACKS[hit[0]],"routed_by":"npc_brain"}
    if re.fullmatch(r"(?:are you|you) (?:there|ready)",norm):return {"message":"Yes. I’m ready.","routed_by":"npc_brain"}
    if re.fullmatch(r"(?:continue|go on|proceed|carry on)",norm):return {"message":"Okay. I’ll continue from the current task context.","routed_by":"npc_brain"}
    return None
