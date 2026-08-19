from __future__ import annotations

import re
from typing import Any

_STOP={"the","a","an","and","or","of","to","in","on","for","with","is","are","was","were","be","as","at","by","that","this","it","from","has","have","had","will","can","could","would","should","may","might","into","their","its"}
_CITE_RE=re.compile(r"\[(S\d+)\]")
_SENTENCE_RE=re.compile(r"(?<=[.!?])\s+|\n+")


def _tokens(text:str)->set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9-]{2,}",text.lower()) if w not in _STOP}

def _support_score(claim:str,evidence:str)->float:
    c=_tokens(_CITE_RE.sub("",claim)); e=_tokens(evidence)
    if not c:return 1.0
    return len(c & e)/max(1,len(c))

def verify_report(report:str,sources:list[Any])->dict[str,Any]:
    by_id={str(getattr(s,"id",None) or (s.get("id") if isinstance(s,dict) else "")):s for s in sources}
    details=[];cited=set();unsupported=[];weak=[]
    for sentence in _SENTENCE_RE.split(report):
        ids=_CITE_RE.findall(sentence)
        if not ids:continue
        cited.update(ids);scores=[];missing=[]
        for sid in ids:
            src=by_id.get(sid)
            if not src: missing.append(sid);continue
            evidence=str(getattr(src,"text","") or (src.get("text","") if isinstance(src,dict) else "") or getattr(src,"snippet","") or (src.get("snippet","") if isinstance(src,dict) else ""))
            scores.append(_support_score(sentence,evidence))
        best=max(scores) if scores else 0.0
        status="verified" if best>=0.34 and not missing else "weak" if best>=0.18 and not missing else "unsupported"
        item={"claim":sentence.strip(),"citations":ids,"support_score":round(best,3),"status":status,"missing_sources":missing};details.append(item)
        if status=="unsupported":unsupported.append(item)
        elif status=="weak":weak.append(item)
    uncited=[]
    for sentence in _SENTENCE_RE.split(report):
        clean=sentence.strip()
        if len(clean)<45 or clean.lower().startswith("sources") or _CITE_RE.search(clean):continue
        # Mark likely factual prose rather than headings/opinions.
        if re.search(r"\b(is|are|was|were|has|have|increased|decreased|launched|reported|found|shows?|uses?|supports?|adopted)\b",clean,re.I):uncited.append(clean)
    return {"verified_claims":sum(d["status"]=="verified" for d in details),"weak_claims":len(weak),"unsupported_claims":len(unsupported),"citation_count":len(cited),"details":details,"uncited_claims":uncited[:20],"passed":not unsupported}

def annotate_report(report:str,verification:dict[str,Any])->str:
    if verification.get("passed") and not verification.get("weak_claims"):
        return report+f"\n\nCitation verification: {verification.get('verified_claims',0)} cited claims checked; no unsupported citations detected."
    notes=[]
    if verification.get("unsupported_claims"):notes.append(f"{verification['unsupported_claims']} unsupported citation(s)")
    if verification.get("weak_claims"):notes.append(f"{verification['weak_claims']} weak citation(s)")
    if verification.get("uncited_claims"):notes.append(f"{len(verification['uncited_claims'])} potentially uncited factual claim(s)")
    return report+"\n\nCitation verification warning: "+", ".join(notes)+". Review the cited evidence before relying on these claims."
