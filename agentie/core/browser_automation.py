from __future__ import annotations

import asyncio
import re
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from agentie.core.browser_monitor import _publish_frame, _set_live_state, _stop_requested, _url, _validate_url, get_live_state
from agentie.tools.approval_tools import approval_is_granted, consume_approval, create_approval

_PLAYWRIGHT: Playwright | None = None
_BROWSER: Browser | None = None
_CONTEXT: BrowserContext | None = None
_PAGE: Page | None = None
_LOCK = asyncio.Lock()

_CONSEQUENTIAL = re.compile(
    r"\b(?:buy|purchase|pay|checkout|place order|submit|send|delete|remove account|confirm order|transfer|publish|post)\b",
    re.I,
)
_CONTROL_PREFIX = "browser control:"


class BrowserApprovalRequired(Exception):
    def __init__(self, action: str, step: str, approval: dict[str, Any]):
        super().__init__(step)
        self.action = action
        self.step = step
        self.approval = approval


def _is_interactive_request(text: str) -> bool:
    low = " ".join(str(text or "").lower().split())
    if low.startswith(_CONTROL_PREFIX):
        return True
    has_url = bool(_url(text))
    explicit = bool(re.search(r"\b(?:click|type|fill|enter|search for|scroll|press|go back|back|go forward|forward|new tab|close tab|browse|navigate)\b", low))
    continuation = bool(re.match(r"^(?:please\s+)?(?:click|type|fill|enter|search for|scroll|press|go back|back|go forward|forward|new tab|close tab)\b", low))
    return explicit and (has_url or continuation)


async def _ensure_page(url: str | None = None) -> Page:
    global _PLAYWRIGHT, _BROWSER, _CONTEXT, _PAGE
    if _PLAYWRIGHT is None:
        _PLAYWRIGHT = await async_playwright().start()
    if _BROWSER is None or not _BROWSER.is_connected():
        _BROWSER = await _PLAYWRIGHT.chromium.launch(headless=True)
    if _CONTEXT is None:
        _CONTEXT = await _BROWSER.new_context(viewport={"width": 1440, "height": 900})
    if _PAGE is None or _PAGE.is_closed():
        _PAGE = await _CONTEXT.new_page()
    recovery_url = None
    if not url and (_PAGE.url in {"", "about:blank"}):
        previous = str(get_live_state().get("url") or "").strip()
        if previous.startswith(("http://", "https://")):
            recovery_url = previous
    navigate_to = url or recovery_url
    if navigate_to:
        safe = _validate_url(navigate_to)
        _set_live_state(active=True, status="opening", url=safe, detail="Opening page")
        await _PAGE.goto(safe, wait_until="domcontentloaded", timeout=30000)
        try:
            await _PAGE.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            pass
        await _publish_frame(_PAGE, status="ready", url=_PAGE.url, detail="Page ready")
    return _PAGE


async def _locator_for_text(page: Page, target: str):
    target = target.strip().strip('"\'`')
    candidates = [page.get_by_role("button", name=target, exact=False), page.get_by_role("link", name=target, exact=False), page.get_by_text(target, exact=False)]
    for locator in candidates:
        try:
            if await locator.count():
                return locator.first
        except Exception:
            continue
    return None


def _ordinal(target: str) -> int | None:
    words = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}
    low = target.lower()
    for word, index in words.items():
        if re.search(rf"\b{word}\b", low):
            return index
    m = re.search(r"\b(\d+)(?:st|nd|rd|th)\b", low)
    return max(0, int(m.group(1)) - 1) if m else None


def _requested_color(target: str) -> str | None:
    for color in ("blue", "red", "green", "yellow", "orange", "purple", "pink", "black", "white", "gray", "grey"):
        if re.search(rf"\b{color}\b", target, re.I):
            return "gray" if color == "grey" else color
    return None


def _requested_position(target: str) -> str | None:
    low = target.lower().replace(" ", "-")
    for position in ("top-right", "top-left", "bottom-right", "bottom-left", "top", "bottom", "left", "right", "center", "middle"):
        if position in low:
            return "center" if position == "middle" else position
    return None


async def _visual_locator(page: Page, target: str):
    selector = 'button,a,[role="button"],input[type="button"],input[type="submit"],[onclick]'
    candidates = await page.locator(selector).evaluate_all(
        """els => els.map((el,index) => {const r=el.getBoundingClientRect(),s=getComputedStyle(el);const visible=r.width>1&&r.height>1&&r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth&&s.visibility!=='hidden'&&s.display!=='none';const rgb=(s.backgroundColor.match(/\d+/g)||[]).slice(0,3).map(Number);let color='unknown';if(rgb.length===3){const [rr,g,b]=rgb,max=Math.max(rr,g,b),min=Math.min(rr,g,b);if(max<55)color='black';else if(min>220)color='white';else if(max-min<30)color='gray';else if(b>rr*1.15&&b>g*1.08)color='blue';else if(rr>g*1.25&&rr>b*1.2)color='red';else if(g>rr*1.12&&g>b*1.05)color='green';else if(rr>180&&g>130&&b<120)color='orange';else if(rr>160&&g>150&&b<100)color='yellow';else if(rr>120&&b>120&&g<130)color='purple';}return {index,visible,color,text:(el.innerText||el.value||el.getAttribute('aria-label')||el.title||'').trim().slice(0,200),tag:el.tagName.toLowerCase(),role:el.getAttribute('role')||'',x:r.left+r.width/2,y:r.top+r.height/2};}).filter(x=>x.visible)"""
    )
    if not candidates:
        return None
    low = target.lower(); wanted_color = _requested_color(target); wanted_position = _requested_position(target); wanted_kind = "button" if "button" in low else "link" if "link" in low else None
    filtered = []
    for item in candidates:
        if wanted_color and item.get("color") != wanted_color: continue
        if wanted_kind == "button" and not (item.get("tag") in {"button", "input"} or item.get("role") == "button"): continue
        if wanted_kind == "link" and item.get("tag") != "a": continue
        filtered.append(item)
    if not filtered: filtered = candidates
    width,height=1440.0,900.0
    points={"top-right":(width,0),"top-left":(0,0),"bottom-right":(width,height),"bottom-left":(0,height),"top":(width/2,0),"bottom":(width/2,height),"left":(0,height/2),"right":(width,height/2),"center":(width/2,height/2)}
    if wanted_position:
        px,py=points.get(wanted_position,(width/2,height/2)); filtered.sort(key=lambda item:(float(item.get("x") or 0)-px)**2+(float(item.get("y") or 0)-py)**2)
    index=_ordinal(target); chosen=filtered[index] if index is not None and index<len(filtered) else filtered[0]
    return page.locator(selector).nth(int(chosen["index"])),chosen


async def _field(page: Page, name: str):
    name = name.strip().strip('"\'`')
    if name.lower() in {"search", "search box", "search field", "query"}:
        for locator in [page.get_by_role("searchbox"), page.locator('input[type="search"]'), page.locator('input[name*="search" i]')]:
            try:
                if await locator.count(): return locator.first
            except Exception: pass
    for locator in [page.get_by_label(name, exact=False), page.get_by_placeholder(name, exact=False), page.get_by_role("textbox", name=name, exact=False)]:
        try:
            if await locator.count(): return locator.first
        except Exception: pass
    generic=page.locator('input:not([type="hidden"]), textarea'); return generic.first if await generic.count() else None


def _strip_open_prefix(text: str, url: str | None) -> str:
    value=text
    if url: value=value.replace(url," ",1)
    value=re.sub(r"^\s*(?:please\s+)?(?:open|visit|go to|navigate to|browse)\s+","",value,flags=re.I)
    value=re.sub(r"^\s*(?:(?:and\s+)?then)\s+","",value,flags=re.I)
    return value.strip(" ,.;:-")


def _steps(text: str, url: str | None) -> list[str]:
    body=_strip_open_prefix(text,url)
    if not body:return []
    parts=re.split(r"\s+(?:and\s+then|then)\s+|\s*;\s*",body,flags=re.I)
    return [p.strip(" ,.;") for p in parts if p.strip(" ,.;")]


def _click_target(step: str) -> str | None:
    m=re.search(r"\bclick\s+(?:on\s+)?(.+)$",step,re.I);return m.group(1).strip(" .") if m else None


def _type_parts(step: str) -> tuple[str,str] | None:
    m=re.search(r"\b(?:type|enter|fill)\s+[\"']?(.+?)[\"']?\s+(?:into|in)\s+(?:the\s+)?(.+)$",step,re.I)
    if m:return m.group(1).strip(' "\''),m.group(2).strip(" .")
    m=re.search(r"\bfill\s+(?:the\s+)?(.+?)\s+with\s+[\"']?(.+?)[\"']?$",step,re.I)
    if m:return m.group(2).strip(' "\''),m.group(1).strip(" .")
    return None


def _browser_action(page:Page,step:str)->str:return f"browser:{page.url}:{' '.join(step.lower().split())}"[:500]
def _require_consequential_approval(page:Page,step:str)->None:
    if not _CONSEQUENTIAL.search(step):return
    action=_browser_action(page,step)
    if approval_is_granted(action):consume_approval(action);return
    item=create_approval(action,f"Allow this browser action once: {step}",{"kind":"browser","url":page.url,"step":step});raise BrowserApprovalRequired(action,step,item)


async def _coordinate_click(page:Page,x:float,y:float)->str:
    info=await page.evaluate("""([x,y])=>{const el=document.elementFromPoint(x,y);if(!el)return {label:'screen item'};const t=el.closest('button,a,[role=button],input,[onclick]')||el;return {label:(t.innerText||t.value||t.getAttribute('aria-label')||t.title||t.tagName||'screen item').trim().slice(0,160)}}""",[x,y]);label=str((info or {}).get("label") or "screen item");_require_consequential_approval(page,f"click {label}");_set_live_state(active=True,status="clicking",url=page.url,detail=f"Clicking {label}");await page.mouse.click(x,y);return f"Clicked {label}"


async def _perform(page: Page, step: str) -> tuple[str,Page]:
    global _PAGE
    low=step.lower().strip()
    control=re.match(r"^browser control:\s*click at\s+(\d+(?:\.\d+)?)[, ]+(\d+(?:\.\d+)?)$",step,re.I)
    if control:return await _coordinate_click(page,float(control.group(1)),float(control.group(2))),page
    control=re.match(r"^browser control:\s*type focused:\s*(.*)$",step,re.I|re.S)
    if control:
        value=control.group(1)[:5000];_set_live_state(active=True,status="typing",url=page.url,detail="Typing into focused field");await page.keyboard.insert_text(value);return "Typed into focused field",page
    control=re.match(r"^browser control:\s*key\s+(\w+)$",step,re.I)
    if control:
        key={"esc":"Escape"}.get(control.group(1).lower(),control.group(1));allowed={"Enter","Tab","Escape","Backspace","Delete","ArrowUp","ArrowDown","ArrowLeft","ArrowRight","PageUp","PageDown","Home","End"}
        if key not in allowed:raise RuntimeError("Unsupported browser key")
        _set_live_state(active=True,status="key",url=page.url,detail=f"Pressing {key}");await page.keyboard.press(key);return f"Pressed {key}",page
    control=re.match(r"^browser control:\s*scroll\s+(-?\d+(?:\.\d+)?)$",step,re.I)
    if control:
        dy=max(-3000,min(3000,float(control.group(1))));_set_live_state(active=True,status="scrolling",url=page.url,detail="Scrolling");await page.mouse.wheel(0,dy);return "Scrolled",page
    control=re.match(r"^browser control:\s*(back|forward|reload)$",step,re.I)
    if control:
        action=control.group(1).lower();_set_live_state(active=True,status="navigating",url=page.url,detail=action.title())
        if action=="back":await page.go_back(wait_until="domcontentloaded",timeout=10000)
        elif action=="forward":await page.go_forward(wait_until="domcontentloaded",timeout=10000)
        else:await page.reload(wait_until="domcontentloaded",timeout=15000)
        return action.title(),page
    if re.search(r"\bnew tab\b",low):
        assert _CONTEXT is not None;_set_live_state(active=True,status="tab",url=page.url,detail="Opening new tab");_PAGE=await _CONTEXT.new_page();return "Opened new tab",_PAGE
    if re.search(r"\bclose tab\b",low):
        if _CONTEXT is None:return "No browser tab to close",page
        _set_live_state(active=True,status="tab",url=page.url,detail="Closing tab");await page.close();pages=[p for p in _CONTEXT.pages if not p.is_closed()];_PAGE=pages[-1] if pages else await _CONTEXT.new_page();return "Closed tab",_PAGE
    target=_click_target(step)
    if target:
        locator=await _locator_for_text(page,target);visual=None
        if locator is None:visual=await _visual_locator(page,target);locator=visual[0] if visual else None
        if locator is None:raise RuntimeError(f"I couldn't find a clickable element matching “{target}”.")
        label=(visual[1].get("text") if visual else target) or target;_require_consequential_approval(page,f"click {label}");_set_live_state(active=True,status="clicking",url=page.url,detail=f"Clicking {label}");await locator.click(timeout=10000)
        try:await page.wait_for_load_state("domcontentloaded",timeout=5000)
        except Exception:pass
        return f"Clicked {label}",page
    typed=_type_parts(step)
    if typed:
        value,field_name=typed;field=await _field(page,field_name)
        if field is None:raise RuntimeError(f"I couldn't find a field matching “{field_name}”.")
        _set_live_state(active=True,status="typing",url=page.url,detail=f"Typing into {field_name}");await field.fill(value);return f"Typed into {field_name}",page
    m=re.search(r"\bsearch\s+for\s+[\"']?(.+?)[\"']?$",step,re.I)
    if m:
        query=m.group(1).strip(' "\'');field=await _field(page,"search")
        if field is None:raise RuntimeError("I couldn't find a search field on this page.")
        _set_live_state(active=True,status="typing",url=page.url,detail=f"Searching for {query}");await field.fill(query);await field.press("Enter")
        try:await page.wait_for_load_state("domcontentloaded",timeout=5000)
        except Exception:pass
        return f"Searched for {query}",page
    if re.search(r"\bscroll\s+(?:down|lower)\b",low):_set_live_state(active=True,status="scrolling",url=page.url,detail="Scrolling down");await page.mouse.wheel(0,700);return "Scrolled down",page
    if re.search(r"\bscroll\s+(?:up|higher)\b",low):_set_live_state(active=True,status="scrolling",url=page.url,detail="Scrolling up");await page.mouse.wheel(0,-700);return "Scrolled up",page
    m=re.search(r"\bpress\s+(enter|tab|escape|esc|arrowdown|arrowup|pagedown|pageup)\b",low,re.I)
    if m:
        key={"esc":"Escape","enter":"Enter","tab":"Tab","arrowdown":"ArrowDown","arrowup":"ArrowUp","pagedown":"PageDown","pageup":"PageUp"}.get(m.group(1).lower(),m.group(1));_set_live_state(active=True,status="key",url=page.url,detail=f"Pressing {key}");await page.keyboard.press(key);return f"Pressed {key}",page
    if re.search(r"\b(?:go back|back)\b",low):_set_live_state(active=True,status="navigating",url=page.url,detail="Going back");await page.go_back(wait_until="domcontentloaded",timeout=10000);return "Went back",page
    if re.search(r"\b(?:go forward|forward)\b",low):_set_live_state(active=True,status="navigating",url=page.url,detail="Going forward");await page.go_forward(wait_until="domcontentloaded",timeout=10000);return "Went forward",page
    return f"Skipped unrecognized step: {step}",page


async def browser_session_command(message:str)->dict[str,Any]|None:
    from agentie.core.desktop_runtime import route_desktop_request
    desktop = route_desktop_request(message)
    if desktop is not None:
        return desktop
    if not _is_interactive_request(message):return None
    async with _LOCK:
        target=_url(message)
        try:
            page=await _ensure_page(target);actions=[]
            if target:actions.append(f"Opened {target}")
            steps=[message] if message.lower().strip().startswith(_CONTROL_PREFIX) else _steps(message,target)
            for step in steps:
                if _stop_requested():raise RuntimeError("Browser task stopped by user.")
                result,page=await _perform(page,step);actions.append(result);await _publish_frame(page,status="working",url=page.url,detail=result)
            title=await page.title();await _publish_frame(page,status="done",url=page.url,detail="Browser actions complete");_set_live_state(active=False,status="done",url=page.url,detail="Browser actions complete")
            return {"message":"Completed the browser actions.","card":{"type":"browser_actions","title":title or "Browser","url":page.url,"actions":actions,"internal_control":message.lower().strip().startswith(_CONTROL_PREFIX)}}
        except BrowserApprovalRequired as exc:
            page_url=_PAGE.url if _PAGE and not _PAGE.is_closed() else (target or "");_set_live_state(active=False,status="paused",url=page_url,detail=f"Approval required: {exc.step}")
            return {"message":"This browser action needs your approval before I continue.","card":{"type":"browser_approval","url":page_url,"step":exc.step,"approval":exc.approval,"command":message}}
        except Exception as exc:
            page_url=_PAGE.url if _PAGE and not _PAGE.is_closed() else (target or "");_set_live_state(active=False,status="error",url=page_url,detail="Browser action failed",error=str(exc)[:500]);return {"message":f"Browser action failed: {str(exc)[:500]}","card":None}
