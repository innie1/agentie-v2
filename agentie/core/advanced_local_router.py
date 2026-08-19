import json
import re
import zipfile
from datetime import datetime
from difflib import get_close_matches
from pathlib import Path

import yaml

from agentie.tools import advanced_utility_tools as advanced
from agentie.tools import productivity_tools as productivity
from agentie.tools import local_utility_tools as utilities


def _save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")

def _load(path: Path, default):
    if not path.exists(): return default
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default

def _looks_like_time_question(lower: str) -> bool:
    words=re.findall(r"[a-z]+",lower); corrected=[]
    for word in words:
        if word in {"tiem","teim","tme","tim"}: corrected.append("time")
        elif word in {"wats","wat","whts"}: corrected.append("what")
        else:
            hit=get_close_matches(word,["time","clock"],n=1,cutoff=.78); corrected.append(hit[0] if hit and len(word)>=3 else word)
    bag=set(corrected); return ("time" in bag or "clock" in bag) and bool(bag & {"what","whats","hey","tell","give","show","current","now","please","time","clock"})

def _timer_with_reason(text: str) -> dict | None:
    m=re.search(r"\b(?:set|start|make|give me)\s+(?:a\s+)?timer\s+(?:for\s+)?(\d+(?:\.\d+)?)\s*(seconds?|secs?|sec|s|minutes?|mins?|min|m|hours?|hrs?|hr|h)\b(?:\s+(?:for|to|because|so i can|so that i can)\s+(.+))?$",text,re.I)
    if not m:return None
    value=float(m.group(1)); unit=m.group(2).lower(); seconds=value*(3600 if unit.startswith('h') else 60 if unit.startswith('m') else 1)
    if seconds<=0 or seconds>7*24*3600:return {"message":"Timer must be between 1 second and 7 days.","card":None}
    reason=(m.group(3) or '').strip(' .?!'); item=utilities._create_timer(seconds,reason or "Timer","timer")
    pretty=int(seconds) if seconds.is_integer() else seconds
    card={"type":"timer","id":item["id"],"status":item["status"],"duration_seconds":seconds,"due_at":item["due_at"]}
    if reason:card["reason"]=reason
    return {"message":f"Timer set for {pretty} seconds"+(f" — {reason}." if reason else "."),"card":card}

def try_advanced_local_command(message: str) -> dict | None:
    text=" ".join(message.strip().split()); lower=text.lower().strip(" .?!")
    if _looks_like_time_question(lower) and "timer" not in lower:
        now=datetime.now().astimezone(); return {"message":f"It is {now.strftime('%H:%M:%S')} on {now.strftime('%Y-%m-%d')}.","card":{"type":"datetime","datetime":now.isoformat(timespec="seconds"),"timezone":str(now.tzinfo)}}
    timer=_timer_with_reason(text)
    if timer:return timer
    note=re.match(r"^(?:please\s+)?(?:save|make|create|write)\s+(?:me\s+)?(?:a\s+)?note\s+(?:called|named|titled)\s+(.+?)\s+(?:saying|that says|with(?: the)? text|about)\s+(.+)$",text,re.I)
    if not note:note=re.match(r"^(?:note)\s+(.+?)\s+(?:saying|that says)\s+(.+)$",text,re.I)
    if note:
        title,content=note.group(1).strip(' \"“”'),note.group(2).strip(' \"“”'); notes=_load(productivity.NOTES,{})
        notes[title[:120]]={"content":content[:10000],"updated_at":datetime.now().isoformat(timespec="seconds")}; productivity._save(productivity.NOTES,notes)
        return {"message":f"Saved note “{title}”.","card":{"type":"note","title":title,"content":content}}
    if re.search(r"\bwhat did i (?:just )?(?:ask you to )?save\b|\bwhat did i just save\b",lower):
        notes=_load(productivity.NOTES,{})
        if not notes:return {"message":"You don't have any saved notes yet.","card":None}
        title,item=max(notes.items(),key=lambda kv:str((kv[1] or {}).get("updated_at",""))); content=str((item or {}).get("content",""))
        return {"message":f"You most recently saved “{title}”.","card":{"type":"note","title":title,"content":content}}
    conversion=re.match(r"^(?:convert\s+)?(-?\d+(?:\.\d+)?)\s*(km|mi|m|ft|kg|lb|c|f|l|gal)\s+(?:to|in)\s+(km|mi|m|ft|kg|lb|c|f|l|gal)$",lower)
    if conversion:
        value=float(conversion.group(1));src=conversion.group(2);dst=conversion.group(3);fn=productivity._CONVERSIONS.get((src,dst))
        if not fn:return {"message":"That conversion is not supported yet.","card":None}
        result=fn(value);return {"message":f"{value:g} {src} is {result:.6g} {dst}.","card":{"type":"conversion","value":value,"from_unit":src,"to_unit":dst,"result":result}}
    date_diff=re.match(r"^(?:date difference|difference between)\s+(\d{4}-\d{2}-\d{2}(?:t\d{2}:\d{2}(?::\d{2})?)?)\s+(?:and|to)\s+(\d{4}-\d{2}-\d{2}(?:t\d{2}:\d{2}(?::\d{2})?)?)$",lower)
    if date_diff:
        start=datetime.fromisoformat(date_diff.group(1));end=datetime.fromisoformat(date_diff.group(2));sec=(end-start).total_seconds();return {"message":f"The difference is {sec/86400:.4g} days.","card":{"type":"date_difference","start":start.isoformat(),"end":end.isoformat(),"seconds":sec,"days":sec/86400}}
    json_match=re.match(r"^format json:\s*(.+)$",text,re.I)
    if json_match:
        try:formatted=json.dumps(json.loads(json_match.group(1)),indent=2,ensure_ascii=False,sort_keys=True)
        except Exception as exc:return {"message":f"Invalid JSON: {exc}","card":None}
        return {"message":"JSON is valid and formatted.","card":{"type":"formatted_text","format":"JSON","text":formatted}}
    yaml_match=re.match(r"^format yaml:\s*(.+)$",text,re.I)
    if yaml_match:
        try:formatted=yaml.safe_dump(yaml.safe_load(yaml_match.group(1)),sort_keys=True,allow_unicode=True)
        except Exception as exc:return {"message":f"Invalid YAML: {exc}","card":None}
        return {"message":"YAML is valid and formatted.","card":{"type":"formatted_text","format":"YAML","text":formatted}}
    scratch_get=re.match(r"^(?:scratchpad get|read scratchpad)\s+(.+)$",text,re.I)
    if scratch_get:
        data=_load(advanced.SCRATCHPAD,{});key=scratch_get.group(1).strip();value=data.get(key);return {"message":f"Scratchpad value for “{key}”." if value is not None else "Scratchpad key not found.","card":{"type":"scratchpad","key":key,"value":value} if value is not None else None}
    if lower in {"list scratchpad","show scratchpad","scratchpad keys"}:
        keys=sorted(_load(advanced.SCRATCHPAD,{}).keys());return {"message":f"Scratchpad has {len(keys)} key(s).","card":{"type":"scratchpad_list","keys":keys}}
    zip_match=re.match(r"^zip\s+(.+?)\s+(?:into|to)\s+([\w.-]+\.zip)$",text,re.I)
    if zip_match:
        files=[x.strip() for x in zip_match.group(1).split(',') if x.strip()];target=advanced._safe_path(zip_match.group(2))
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for name in files:
                src=advanced._safe_path(name)
                if src.exists() and src.is_file():z.write(src,arcname=src.name)
        return {"message":f"Created {target.name}.","card":{"type":"archive","filename":target.name,"files":files}}
    unzip_match=re.match(r"^(?:unzip|extract)\s+([\w.-]+\.zip)$",text,re.I)
    if unzip_match:
        src=advanced._safe_path(unzip_match.group(1));dest=advanced.WORKSPACE/f"extracted_{src.stem}";dest.mkdir(parents=True,exist_ok=True);extracted=[]
        try:
            with zipfile.ZipFile(src) as z:
                for member in z.infolist()[:200]:
                    candidate=(dest/member.filename).resolve()
                    if dest.resolve() in candidate.parents or candidate==dest.resolve():z.extract(member,dest);extracted.append(member.filename)
        except Exception as exc:return {"message":f"Could not extract archive: {exc}","card":None}
        return {"message":f"Extracted {len(extracted)} item(s).","card":{"type":"archive","filename":src.name,"destination":str(dest),"files":extracted}}
    return None
