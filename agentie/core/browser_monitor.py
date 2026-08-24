from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
import socket
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

WORKSPACE = Path.cwd() / "workspace"
SNAPSHOT_DIR = WORKSPACE / "web_snapshots"
STATE_FILE = WORKSPACE / "website_monitor_state.json"
LIVE_DIR = WORKSPACE / "browser_live"
LIVE_STATE_FILE = LIVE_DIR / "state.json"
LIVE_FRAME_FILE = LIVE_DIR / "frame.png"

_SERVICE_TARGETS = {
    "x": {"aliases": ("x", "twitter"), "url": "https://x.com", "plugins": ("x", "twitter")},
    "gmail": {"aliases": ("gmail", "google mail", "email"), "url": "https://mail.google.com", "plugins": ("gmail", "google mail", "agentmail", "google-workspace")},
    "calendar": {"aliases": ("google calendar", "calendar"), "url": "https://calendar.google.com", "plugins": ("google calendar", "calendar", "google-workspace")},
    "slack": {"aliases": ("slack",), "url": "https://app.slack.com", "plugins": ("slack",)},
    "notion": {"aliases": ("notion",), "url": "https://www.notion.so", "plugins": ("notion",)},
    "github": {"aliases": ("github",), "url": "https://github.com", "plugins": ("github", "git")},
}
_EXTERNAL_ACTION = re.compile(r"\b(?:open|check|read|search|find|post|publish|send|reply|message|create|edit|update|upload|download|schedule|comment|review)\b", re.I)
_CONSEQUENTIAL_EXTERNAL = re.compile(r"\b(?:post|publish|send|reply|message|create|edit|update|upload|schedule|comment)\b", re.I)
_COMPUTER_PREFIX = "use computer for:"


def _load_state() -> dict[str, dict[str, Any]]:
    try:return json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    except Exception:return {}
def _save_state(data: dict[str, dict[str, Any]]) -> None:STATE_FILE.parent.mkdir(parents=True, exist_ok=True);STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
def _set_live_state(*, active: bool, status: str, url: str = "", detail: str = "", error: str | None = None) -> None:
    LIVE_DIR.mkdir(parents=True, exist_ok=True);previous=get_live_state();state={"active":bool(active),"status":status,"url":url,"detail":detail,"error":error,"updated_at":datetime.now().astimezone().isoformat(timespec="milliseconds"),"frame_version":int(previous.get("frame_version") or 0),"stop_requested":bool(previous.get("stop_requested",False)) if active else False};LIVE_STATE_FILE.write_text(json.dumps(state,indent=2,ensure_ascii=False),encoding="utf-8")
def get_live_state() -> dict[str, Any]:
    try:return json.loads(LIVE_STATE_FILE.read_text(encoding="utf-8")) if LIVE_STATE_FILE.exists() else {"active":False,"status":"idle","url":"","detail":"","frame_version":0,"stop_requested":False}
    except Exception:return {"active":False,"status":"idle","url":"","detail":"","frame_version":0,"stop_requested":False}
def request_browser_stop() -> dict[str, Any]:
    state=get_live_state();state["stop_requested"]=True;state["updated_at"]=datetime.now().astimezone().isoformat(timespec="milliseconds");LIVE_DIR.mkdir(parents=True,exist_ok=True);LIVE_STATE_FILE.write_text(json.dumps(state,indent=2,ensure_ascii=False),encoding="utf-8");return state
def _stop_requested() -> bool:return bool(get_live_state().get("stop_requested"))
async def _publish_frame(page: Any, *, status: str, url: str, detail: str = "") -> None:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    try:await page.screenshot(path=str(LIVE_FRAME_FILE), full_page=False)
    except Exception:return
    state=get_live_state();state.update({"active":True,"status":status,"url":url,"detail":detail,"error":None,"frame_version":int(state.get("frame_version") or 0)+1,"updated_at":datetime.now().astimezone().isoformat(timespec="milliseconds")});LIVE_STATE_FILE.write_text(json.dumps(state,indent=2,ensure_ascii=False),encoding="utf-8")
def _url(text: str) -> str | None:
    m=re.search(r"https?://[^\s<>\"']+",str(text or ""),re.I);return m.group(0).rstrip(".,;!?)") if m else None
def _scheduled_request(text: str) -> bool:
    low=text.lower();return bool(re.search(r"\bevery\s+\d+(?:\.\d+)?\s*(?:minutes?|mins?|hours?|hrs?)\b",low) or re.search(r"\b(?:every day|daily|every morning|every afternoon|every evening|every weekday|every monday|every tuesday|every wednesday|every thursday|every friday|every saturday|every sunday)\b",low))
def _looks_browser_request(text: str) -> bool:return bool(_url(text) and re.search(r"\b(?:check|open|visit|inspect|look at|view|screenshot|snapshot|capture|monitor|watch)\b",text.lower()))
def website_routine_target(text: str) -> str | None:
    low=str(text or "").lower()
    if not _url(text) or not re.search(r"\b(?:monitor|monitors|watch|watches|check|checks|inspect|inspects|visit|visits|screenshot|screenshots|snapshot|snapshots|capture|captures)\b",low):return None
    return _url(text)
def routine_always_show(text: str) -> bool:return bool(re.search(r"\b(?:always show|show every|every screenshot|every check|always notify|notify every)\b",str(text or "").lower()))
def _blocked_ip(value: str) -> bool:
    try:ip=ipaddress.ip_address(value)
    except ValueError:return False
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified)
def _validate_url(url: str) -> str:
    parsed=urlparse(url)
    if parsed.scheme not in {"http","https"} or not parsed.hostname:raise ValueError("Website monitoring supports only http:// and https:// URLs.")
    if parsed.username or parsed.password:raise ValueError("URLs containing embedded credentials are not allowed.")
    host=parsed.hostname.lower()
    if host in {"localhost","0.0.0.0"} or host.endswith(".localhost") or _blocked_ip(host):raise ValueError("Private and local network addresses are blocked by the website monitor.")
    try:
        for item in socket.getaddrinfo(host,parsed.port or (443 if parsed.scheme=="https" else 80),type=socket.SOCK_STREAM):
            if _blocked_ip(item[4][0]):raise ValueError("Private and local network addresses are blocked by the website monitor.")
    except socket.gaierror:pass
    return url
def _safe_slug(url: str) -> str:
    host=urlparse(url).hostname or "website";host=re.sub(r"[^a-zA-Z0-9._-]+","-",host).strip("-")[:60] or "website";digest=hashlib.sha256(url.encode("utf-8")).hexdigest()[:10];stamp=datetime.now().astimezone().strftime("%Y%m%d-%H%M%S");return f"{host}-{digest}-{stamp}.png"
def _normalized_text(value: str) -> str:return re.sub(r"\s+"," ",str(value or "")).strip()[:120000]
def _meaningfully_changed(previous: dict[str, Any] | None,current_text: str,title: str)->tuple[bool,float|None]:
    if not previous:return True,None
    old=_normalized_text(previous.get("text",""));new=_normalized_text(current_text)
    if not old and not new:return previous.get("title")!=title,1.0
    ratio=SequenceMatcher(None,old[:50000],new[:50000]).ratio();title_changed=str(previous.get("title") or "")!=str(title or "");length_delta=abs(len(new)-len(old))/max(1,len(old));return title_changed or ratio<.985 or length_delta>.03,ratio
def _card(url: str,title: str,filename: str,changed: bool,similarity: float|None,excerpt: str)->dict[str,Any]:return {"type":"web_snapshot","url":url,"title":title or url,"image_url":f"/web-snapshots/{filename}","filename":filename,"changed":changed,"similarity":similarity,"excerpt":excerpt[:900],"captured_at":datetime.now().astimezone().isoformat(timespec="seconds")}
def _connected_plugin_names() -> set[str]:
    try:
        from agentie.core.mcp_client import list_servers
        return {str(item.get("name") or "").casefold() for item in list_servers()}
    except Exception:return set()
def _service_for_task(text: str, *, ignore_plugins: bool = False) -> dict[str, Any] | None:
    low=" ".join(str(text or "").casefold().split())
    if not low or not _EXTERNAL_ACTION.search(low):return None
    connected=_connected_plugin_names() if not ignore_plugins else set()
    for service,meta in _SERVICE_TARGETS.items():
        matched=False
        for alias in meta["aliases"]:
            if alias=="x":
                if re.search(r"(?:^|\s|@)x(?:\s|$)",low):matched=True;break
            elif alias=="email":
                if re.search(r"\bemail\b",low):matched=True;break
            elif re.search(rf"\b{re.escape(alias)}\b",low):matched=True;break
        if not matched:continue
        if connected and any(any(p in name or name in p for p in meta["plugins"]) for name in connected):return None
        return {"service":service,"url":meta["url"],"consequential":bool(_CONSEQUENTIAL_EXTERNAL.search(low)),"task":str(text).strip()}
    return None
def _fallback_proposal(text: str,candidate: dict[str,Any])->dict[str,Any]:
    service=str(candidate["service"]);task=str(candidate["task"]);return {"message":f"I don’t see a connected {service} capability for this task. Agentie can use its Computer instead.","card":{"type":"computer_fallback_proposal","service":service,"url":candidate["url"],"task":task,"consequential":candidate["consequential"],"actions":[{"action":"use_computer","label":"Use Computer","command":f"Use Computer for: {task}"},{"action":"keep_in_chat","label":"Keep in chat"}]}}
def _desktop_fallback_card(info:dict[str,Any],candidate:dict[str,Any],task:str,*,navigated_url:str|None=None)->dict[str,Any]:
    accel=info.get("acceleration") or {};profile=info.get("profile") or {};return {"type":"desktop_view","app":"desktop","mode":info.get("backend","qemu"),"backend":info.get("backend","qemu"),"computer_id":info.get("computer_id","company-default"),"state":info.get("state"),"running":bool(info.get("running")),"display_url":info.get("display_url"),"display_ready":bool(info.get("display_ready")),"browser_ready":bool(info.get("browser_ready")),"accelerator":accel.get("accelerator"),"vm_ram_mb":profile.get("vm_ram_mb"),"vm_vcpus":profile.get("vm_vcpus"),"fallback_service":candidate["service"],"fallback_task":task,"fallback_url":navigated_url or candidate["url"],"consequential":candidate["consequential"]}
async def _launch_computer_fallback(task:str,session_id:str|None=None)->dict[str,Any]:
    candidate=_service_for_task(task,ignore_plugins=True)
    if not candidate:return {"message":"I couldn’t determine which website the Computer should use for that task.","card":None}
    from agentie.core.company_computer_backend import acquire_for_session
    from agentie.core.company_computer_backend import status as company_status
    try:
        info=await asyncio.wait_for(asyncio.to_thread(acquire_for_session,session_id),timeout=45);navigated_url=None
        try:
            from agentie.core.browser_automation import _ensure_page
            page=await asyncio.wait_for(_ensure_page(str(candidate["url"]),session_id),timeout=125);navigated_url=page.url;await _publish_frame(page,status="ready",url=page.url,detail=f"Computer ready for: {task[:160]}")
        except Exception:info=company_status()
        _set_live_state(active=True,status="ready",url=navigated_url or str(candidate["url"]),detail=f"Company Computer ready for {candidate['service']}");message=f"Agentie Computer is open on {candidate['service']} and the task is staged there." if navigated_url else f"Agentie Computer is ready for {candidate['service']}. Chromium is still preparing, but the persistent desktop is available.";return {"message":message,"card":_desktop_fallback_card(info,candidate,task,navigated_url=navigated_url)}
    except asyncio.TimeoutError:
        _set_live_state(active=False,status="error",url=str(candidate["url"]),detail="Computer startup timed out",error="Computer startup timed out");return {"message":"Agentie Computer took too long to start. The request stopped instead of remaining stuck.","card":None}
    except Exception as exc:
        _set_live_state(active=False,status="error",url=str(candidate["url"]),detail="Computer fallback failed",error=str(exc)[:500]);return {"message":f"I couldn’t start the Computer fallback: {str(exc)[:500]}","card":None}
async def capture_website(url:str,*,track_change:bool=False,session_id:str|None=None)->dict[str,Any]:
    url=_validate_url(url);SNAPSHOT_DIR.mkdir(parents=True,exist_ok=True);filename=_safe_slug(url);path=SNAPSHOT_DIR/filename;_set_live_state(active=True,status="starting",url=url,detail="Starting Agentie Computer")
    try:
        from agentie.core.browser_automation import _ensure_page
        page=await _ensure_page(url,session_id)
        if _stop_requested():raise RuntimeError("Browser task stopped by user.")
        try:await page.wait_for_load_state("networkidle",timeout=8000)
        except Exception:pass
        await _publish_frame(page,status="ready",url=page.url,detail="Page ready on Agentie Computer");title=await page.title();text=_normalized_text(await page.locator("body").inner_text(timeout=10000));_set_live_state(active=True,status="capturing",url=page.url,detail="Capturing screenshot from Company Computer");await page.screenshot(path=str(path),full_page=True);await _publish_frame(page,status="captured",url=page.url,detail="Screenshot captured");status=None
    except Exception as exc:
        message=str(exc);_set_live_state(active=False,status="error",url=url,detail="Browser task ended",error=message[:500])
        if "stopped by user" in message.lower():raise RuntimeError("Browser task stopped by user.") from exc
        raise RuntimeError(f"Website capture failed: {message[:500]}") from exc
    key=hashlib.sha256(url.encode("utf-8")).hexdigest();state=_load_state();previous=state.get(key) if track_change else None
    if track_change:changed,similarity=_meaningfully_changed(previous,text,title);state[key]={"url":url,"title":title,"text":text,"filename":filename,"captured_at":datetime.now().astimezone().isoformat(timespec="seconds")};_save_state(state)
    else:changed,similarity=False,None
    excerpt=text[:900];_set_live_state(active=False,status="done",url=page.url,detail="Browser task complete");return {"message":f"Checked {url}. The page has meaningfully changed since the previous check." if track_change and changed and previous else f"Checked {url}. No meaningful change was detected." if track_change and previous else f"Captured a screenshot of {url}.","card":_card(url,title,filename,changed,similarity,excerpt),"status":status,"changed":changed,"first_check":previous is None if track_change else True}
async def route_browser_request(message:str,session_id:str|None=None)->dict[str,Any]|None:
    text=" ".join(str(message or "").strip().split())
    if not text:return None
    from agentie.core.workflow_browser_runtime import route_taught_workflow_request
    taught=await route_taught_workflow_request(text,session_id)
    if taught is not None:return taught
    if _scheduled_request(text):return None
    if text.casefold().startswith(_COMPUTER_PREFIX):return await _launch_computer_fallback(text[len(_COMPUTER_PREFIX):].strip(),session_id)
    from agentie.core.desktop_runtime import route_desktop_request
    desktop=await asyncio.to_thread(route_desktop_request,text,session_id)
    if desktop is not None:return desktop
    from agentie.core.browser_automation import browser_session_command
    interactive=await browser_session_command(text,session_id)
    if interactive is not None:return interactive
    candidate=_service_for_task(text)
    if candidate is not None:return _fallback_proposal(text,candidate)
    if not _looks_browser_request(text):return None
    target=_url(text)
    if not target:return None
    track=bool(re.search(r"\b(?:monitor|watch|change|changed|compare)\b",text,re.I))
    try:return await capture_website(target,track_change=track,session_id=session_id)
    except (ValueError,RuntimeError) as exc:return {"message":str(exc),"card":None}
