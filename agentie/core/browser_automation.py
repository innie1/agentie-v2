from __future__ import annotations

import asyncio
import re
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from agentie.core.browser_monitor import _publish_frame, _set_live_state, _stop_requested, _url, _validate_url, get_live_state
from agentie.core.company_computer import ComputerError, acquire_for_session, request_user_takeover_for_session, status as computer_status, touch_activity
from agentie.tools.approval_tools import approval_is_granted, consume_approval, create_approval

_PLAYWRIGHT: Playwright | None = None
_BROWSER: Browser | None = None
_CONTEXT: BrowserContext | None = None
_PAGE: Page | None = None
_LOCK = asyncio.Lock()
_USING_COMPANY_COMPUTER = False

_CONSEQUENTIAL = re.compile(r"\b(?:buy|purchase|pay|checkout|place order|submit|send|delete|remove account|confirm order|transfer|publish|post)\b", re.I)
_CONTROL_PREFIX = "browser control:"
_HUMAN_TEXT = re.compile(r"\b(?:captcha|verify you(?:'|’)re human|verify your identity|two[- ]factor|2fa|security key|passkey|one[- ]time code|authentication code)\b", re.I)


class BrowserApprovalRequired(Exception):
    def __init__(self, action: str, step: str, approval: dict[str, Any]):
        super().__init__(step); self.action = action; self.step = step; self.approval = approval


class BrowserHumanTakeoverRequired(Exception):
    def __init__(self, reason: str): super().__init__(reason); self.reason = reason


def _is_interactive_request(text: str) -> bool:
    low = " ".join(str(text or "").lower().split())
    if low.startswith(_CONTROL_PREFIX): return True
    has_url = bool(_url(text)); explicit = bool(re.search(r"\b(?:click|type|fill|enter|search for|scroll|press|go back|back|go forward|forward|new tab|close tab|browse|navigate)\b", low)); continuation = bool(re.match(r"^(?:please\s+)?(?:click|type|fill|enter|search for|scroll|press|go back|back|go forward|forward|new tab|close tab)\b", low))
    return explicit and (has_url or continuation)


def _ordinal(target: str) -> int | None:
    words = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}; low = target.lower()
    for word, index in words.items():
        if re.search(rf"\b{word}\b", low): return index
    m = re.search(r"\b(\d+)(?:st|nd|rd|th)\b", low); return max(0, int(m.group(1)) - 1) if m else None


def _requested_color(target: str) -> str | None:
    for color in ("blue", "red", "green", "yellow", "orange", "purple", "pink", "black", "white", "gray", "grey"):
        if re.search(rf"\b{color}\b", target, re.I): return "gray" if color == "grey" else color
    return None


def _requested_position(target: str) -> str | None:
    low = target.lower().replace(" ", "-")
    for position in ("top-right", "top-left", "bottom-right", "bottom-left", "top", "bottom", "left", "right", "center", "middle"):
        if position in low: return "center" if position == "middle" else position
    return None


def _strip_open_prefix(text: str, url: str | None) -> str:
    value = text
    if url: value = value.replace(url, " ", 1)
    value = re.sub(r"^\s*(?:please\s+)?(?:open|visit|go to|navigate to|browse)\s+", "", value, flags=re.I); value = re.sub(r"^\s*(?:(?:and\s+)?then)\s+", "", value, flags=re.I)
    return value.strip(" ,.;:-")


def _steps(text: str, url: str | None) -> list[str]:
    body = _strip_open_prefix(text, url)
    if not body: return []
    return [p.strip(" ,.;") for p in re.split(r"\s+(?:and\s+then|then)\s+|\s*;\s*", body, flags=re.I) if p.strip(" ,.;")]


def _click_target(step: str) -> str | None:
    m = re.search(r"\bclick\s+(?:on\s+)?(.+)$", step, re.I); return m.group(1).strip(" .") if m else None


def _type_parts(step: str) -> tuple[str, str] | None:
    m = re.search(r"\b(?:type|enter|fill)\s+[\"']?(.+?)[\"']?\s+(?:into|in)\s+(?:the\s+)?(.+)$", step, re.I)
    if m: return m.group(1).strip(' "\''), m.group(2).strip(" .")
    m = re.search(r"\bfill\s+(?:the\s+)?(.+?)\s+with\s+[\"']?(.+?)[\"']?$", step, re.I)
    if m: return m.group(2).strip(' "\''), m.group(1).strip(" .")
    return None


async def _connect_visible_chrome(session_id: str | None = None) -> bool:
    global _PLAYWRIGHT, _BROWSER, _CONTEXT, _PAGE, _USING_COMPANY_COMPUTER
    await asyncio.to_thread(acquire_for_session, session_id)
    deadline = asyncio.get_running_loop().time() + 120; info = computer_status()
    while asyncio.get_running_loop().time() < deadline:
        info = computer_status()
        if info.get("browser_ready") and info.get("cdp_url"): break
        await asyncio.sleep(.5)
    cdp_url = str(info.get("cdp_url") or "").strip()
    if not info.get("browser_ready") or not cdp_url: raise ComputerError("Agentie Computer is running, but Chromium is not ready. On first use the guest may still be installing its lightweight desktop and browser.")
    if _PLAYWRIGHT is None: _PLAYWRIGHT = await async_playwright().start()
    _BROWSER = await _PLAYWRIGHT.chromium.connect_over_cdp(cdp_url, timeout=10000); contexts = _BROWSER.contexts; _CONTEXT = contexts[0] if contexts else None
    if _CONTEXT is None: return False
    pages = [p for p in _CONTEXT.pages if not p.is_closed()]; _PAGE = pages[-1] if pages else await _CONTEXT.new_page(); _USING_COMPANY_COMPUTER = True; return True


async def _ensure_page(url: str | None = None, session_id: str | None = None) -> Page:
    global _BROWSER, _CONTEXT, _PAGE
    if _BROWSER is None or not _BROWSER.is_connected():
        if not await _connect_visible_chrome(session_id): raise ComputerError("Could not attach to Chromium inside Agentie Computer.")
    if _CONTEXT is None:
        contexts = _BROWSER.contexts if _BROWSER else []
        if not contexts: raise ComputerError("Chromium inside Agentie Computer has no browser context.")
        _CONTEXT = contexts[0]
    if _PAGE is None or _PAGE.is_closed():
        pages = [p for p in _CONTEXT.pages if not p.is_closed()]; _PAGE = pages[-1] if pages else await _CONTEXT.new_page()
    recovery_url = None
    if not url and _PAGE.url in {"", "about:blank"}:
        previous = str(get_live_state().get("url") or "").strip()
        if previous.startswith(("http://", "https://")): recovery_url = previous
    navigate_to = url or recovery_url
    if navigate_to:
        safe = _validate_url(navigate_to); _set_live_state(active=True, status="opening", url=safe, detail="Opening page on Agentie Computer"); await _PAGE.goto(safe, wait_until="domcontentloaded", timeout=30000)
        try: await _PAGE.wait_for_load_state("networkidle", timeout=6000)
        except Exception: pass
        await _publish_frame(_PAGE, status="ready", url=_PAGE.url, detail="Page ready"); await asyncio.to_thread(touch_activity, {"url": _PAGE.url, "title": await _PAGE.title()})
    return _PAGE


async def _takeover_reason(page: Page) -> str | None:
    try:
        if await page.locator('iframe[src*="captcha" i], [class*="captcha" i], [id*="captcha" i]').count(): return "CAPTCHA requires user action."
        if await page.locator('input[type="password"]').count(): return "Sign-in requires the user to enter or confirm credentials."
        if await page.locator('input[autocomplete="one-time-code"], input[name*="otp" i], input[name*="code" i]').count(): return "Two-factor or one-time-code verification requires user action."
        text = (await page.locator("body").inner_text(timeout=2500))[:12000]
        if _HUMAN_TEXT.search(text): return "This page requires human identity or verification action."
    except Exception: return None
    return None


async def _maybe_require_human(page: Page, session_id: str | None) -> None:
    reason = await _takeover_reason(page)
    if not reason: return
    await asyncio.to_thread(request_user_takeover_for_session, session_id, reason); raise BrowserHumanTakeoverRequired(reason)


async def _locator_for_text(page: Page, target: str):
    target = target.strip().strip('"\'`')
    for locator in (page.get_by_role("button", name=target, exact=False), page.get_by_role("link", name=target, exact=False), page.get_by_text(target, exact=False)):
        try:
            if await locator.count(): return locator.first
        except Exception: continue
    return None


async def _visual_locator(page: Page, target: str):
    selector = 'button,a,[role="button"],input[type="button"],input[type="submit"],[onclick]'; candidates = await page.locator(selector).evaluate_all("""els => els.map((el,index)=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);const visible=r.width>1&&r.height>1&&r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth&&s.visibility!=='hidden'&&s.display!=='none';const rgb=(s.backgroundColor.match(/\d+/g)||[]).slice(0,3).map(Number);let color='unknown';if(rgb.length===3){const [rr,g,b]=rgb,max=Math.max(rr,g,b),min=Math.min(rr,g,b);if(max<55)color='black';else if(min>220)color='white';else if(max-min<30)color='gray';else if(b>rr*1.15&&b>g*1.08)color='blue';else if(rr>g*1.25&&rr>b*1.2)color='red';else if(g>rr*1.12&&g>b*1.05)color='green';else if(rr>180&&g>130&&b<120)color='orange';else if(rr>160&&g>150&&b<100)color='yellow';else if(rr>120&&b>120&&g<130)color='purple';}return {index,visible,color,text:(el.innerText||el.value||el.getAttribute('aria-label')||el.title||'').trim().slice(0,200),tag:el.tagName.toLowerCase(),role:el.getAttribute('role')||'',x:r.left+r.width/2,y:r.top+r.height/2};}).filter(x=>x.visible)""")
    if not candidates: return None
    low = target.lower(); color = _requested_color(target); position = _requested_position(target); kind = "button" if "button" in low else "link" if "link" in low else None; filtered = []
    for item in candidates:
        if color and item.get("color") != color: continue
        if kind == "button" and not (item.get("tag") in {"button", "input"} or item.get("role") == "button"): continue
        if kind == "link" and item.get("tag") != "a": continue
        filtered.append(item)
    if not filtered: filtered = candidates
    points = {"top-right": (1440,0), "top-left": (0,0), "bottom-right": (1440,900), "bottom-left": (0,900), "top": (720,0), "bottom": (720,900), "left": (0,450), "right": (1440,450), "center": (720,450)}
    if position:
        px, py = points.get(position, (720,450)); filtered.sort(key=lambda i: (float(i.get("x") or 0)-px)**2 + (float(i.get("y") or 0)-py)**2)
    index = _ordinal(target); chosen = filtered[index] if index is not None and index < len(filtered) else filtered[0]; return page.locator(selector).nth(int(chosen["index"])), chosen


async def _field(page: Page, name: str):
    name = name.strip().strip('"\'`')
    if name.lower() in {"search", "search box", "search field", "query"}:
        for locator in (page.get_by_role("searchbox"), page.locator('input[type="search"]'), page.locator('input[name*="search" i]')):
            try:
                if await locator.count(): return locator.first
            except Exception: pass
    for locator in (page.get_by_label(name, exact=False), page.get_by_placeholder(name, exact=False), page.get_by_role("textbox", name=name, exact=False)):
        try:
            if await locator.count(): return locator.first
        except Exception: pass
    generic = page.locator('input:not([type="hidden"]), textarea'); return generic.first if await generic.count() else None


def _browser_action(page: Page, step: str) -> str: return f"browser:{page.url}:{' '.join(step.lower().split())}"[:500]


def _require_consequential_approval(page: Page, step: str) -> None:
    if not _CONSEQUENTIAL.search(step): return
    action = _browser_action(page, step)
    if approval_is_granted(action): consume_approval(action); return
    item = create_approval(action, f"Allow this browser action once: {step}", {"kind": "browser", "url": page.url, "step": step}); raise BrowserApprovalRequired(action, step, item)


async def _coordinate_click(page: Page, x: float, y: float) -> str:
    info = await page.evaluate("""([x,y])=>{const el=document.elementFromPoint(x,y);if(!el)return {label:'screen item'};const t=el.closest('button,a,[role=button],input,[onclick]')||el;return {label:(t.innerText||t.value||t.getAttribute('aria-label')||t.title||t.tagName||'screen item').trim().slice(0,160)}}""", [x,y]); label = str((info or {}).get("label") or "screen item"); _require_consequential_approval(page, f"click {label}"); await page.mouse.click(x, y); return f"Clicked {label}"


async def _perform(page: Page, step: str) -> tuple[str, Page]:
    global _PAGE
    low = step.lower().strip(); m = re.match(r"^browser control:\s*click at\s+(\d+(?:\.\d+)?)[, ]+(\d+(?:\.\d+)?)$", step, re.I)
    if m: return await _coordinate_click(page, float(m.group(1)), float(m.group(2))), page
    m = re.match(r"^browser control:\s*type focused:\s*(.*)$", step, re.I|re.S)
    if m: await page.keyboard.insert_text(m.group(1)[:5000]); return "Typed into focused field", page
    m = re.match(r"^browser control:\s*key\s+(\w+)$", step, re.I)
    if m:
        key = {"esc": "Escape"}.get(m.group(1).lower(), m.group(1)); allowed = {"Enter","Tab","Escape","Backspace","Delete","ArrowUp","ArrowDown","ArrowLeft","ArrowRight","PageUp","PageDown","Home","End"}
        if key not in allowed: raise RuntimeError("Unsupported browser key")
        await page.keyboard.press(key); return f"Pressed {key}", page
    m = re.match(r"^browser control:\s*scroll\s+(-?\d+(?:\.\d+)?)$", step, re.I)
    if m: await page.mouse.wheel(0, max(-3000, min(3000, float(m.group(1))))); return "Scrolled", page
    m = re.match(r"^browser control:\s*(back|forward|reload)$", step, re.I)
    if m:
        action = m.group(1).lower()
        if action == "back": await page.go_back(wait_until="domcontentloaded", timeout=10000)
        elif action == "forward": await page.go_forward(wait_until="domcontentloaded", timeout=10000)
        else: await page.reload(wait_until="domcontentloaded", timeout=15000)
        return action.title(), page
    if re.search(r"\bnew tab\b", low): assert _CONTEXT is not None; _PAGE = await _CONTEXT.new_page(); return "Opened new tab", _PAGE
    if re.search(r"\bclose tab\b", low):
        assert _CONTEXT is not None; await page.close(); pages = [p for p in _CONTEXT.pages if not p.is_closed()]; _PAGE = pages[-1] if pages else await _CONTEXT.new_page(); return "Closed tab", _PAGE
    target = _click_target(step)
    if target:
        locator = await _locator_for_text(page, target); visual = None
        if locator is None: visual = await _visual_locator(page, target); locator = visual[0] if visual else None
        if locator is None: raise RuntimeError(f"I couldn't find a clickable element matching “{target}”.")
        label = (visual[1].get("text") if visual else target) or target; _require_consequential_approval(page, f"click {label}"); await locator.click(timeout=10000)
        try: await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception: pass
        return f"Clicked {label}", page
    typed = _type_parts(step)
    if typed:
        value, field_name = typed; field = await _field(page, field_name)
        if field is None: raise RuntimeError(f"I couldn't find a field matching “{field_name}”.")
        await field.fill(value); return f"Typed into {field_name}", page
    m = re.search(r"\bsearch\s+for\s+[\"']?(.+?)[\"']?$", step, re.I)
    if m:
        query = m.group(1).strip(' "\''); field = await _field(page, "search")
        if field is None: raise RuntimeError("I couldn't find a search field on this page.")
        await field.fill(query); await field.press("Enter"); return f"Searched for {query}", page
    if re.search(r"\bscroll\s+(?:down|lower)\b", low): await page.mouse.wheel(0,700); return "Scrolled down", page
    if re.search(r"\bscroll\s+(?:up|higher)\b", low): await page.mouse.wheel(0,-700); return "Scrolled up", page
    m = re.search(r"\bpress\s+(enter|tab|escape|esc|arrowdown|arrowup|pagedown|pageup)\b", low, re.I)
    if m:
        key = {"esc":"Escape","enter":"Enter","tab":"Tab","arrowdown":"ArrowDown","arrowup":"ArrowUp","pagedown":"PageDown","pageup":"PageUp"}.get(m.group(1).lower(), m.group(1)); await page.keyboard.press(key); return f"Pressed {key}", page
    if re.search(r"\b(?:go back|back)\b", low): await page.go_back(wait_until="domcontentloaded", timeout=10000); return "Went back", page
    if re.search(r"\b(?:go forward|forward)\b", low): await page.go_forward(wait_until="domcontentloaded", timeout=10000); return "Went forward", page
    return f"Skipped unrecognized step: {step}", page


async def browser_session_command(message: str, session_id: str | None = None) -> dict[str, Any] | None:
    if not _is_interactive_request(message): return None
    async with _LOCK:
        target = _url(message)
        try:
            page = await _ensure_page(target, session_id); await _maybe_require_human(page, session_id); actions: list[str] = []
            if target: actions.append(f"Opened {target}")
            steps = [message] if message.lower().strip().startswith(_CONTROL_PREFIX) else _steps(message, target)
            for step in steps:
                if _stop_requested(): raise RuntimeError("Browser task stopped by user.")
                result, page = await _perform(page, step); actions.append(result); await _publish_frame(page, status="working", url=page.url, detail=result); await asyncio.to_thread(touch_activity, {"url": page.url, "title": await page.title()}); await _maybe_require_human(page, session_id)
            title = await page.title(); await _publish_frame(page, status="done", url=page.url, detail="Browser actions complete"); _set_live_state(active=False, status="done", url=page.url, detail="Browser actions complete")
            return {"message": "Completed the browser actions.", "card": {"type": "browser_actions", "title": title or "Browser", "url": page.url, "actions": actions, "computer_mode": "qemu"}}
        except BrowserHumanTakeoverRequired as exc:
            page_url = _PAGE.url if _PAGE and not _PAGE.is_closed() else (target or ""); _set_live_state(active=False, status="paused", url=page_url, detail=exc.reason); info = computer_status()
            return {"message": "User action required. Take control of the same Agentie Computer, complete the verification, then press Continue Agent.", "card": {"type": "computer_takeover", "reason": exc.reason, "url": page_url, "display_url": info.get("display_url"), "command": message, "state": info.get("state")}}
        except BrowserApprovalRequired as exc:
            page_url = _PAGE.url if _PAGE and not _PAGE.is_closed() else (target or ""); _set_live_state(active=False, status="paused", url=page_url, detail=f"Approval required: {exc.step}")
            return {"message": "This browser action needs your approval before I continue.", "card": {"type": "browser_approval", "url": page_url, "step": exc.step, "approval": exc.approval, "command": message}}
        except Exception as exc:
            page_url = _PAGE.url if _PAGE and not _PAGE.is_closed() else (target or ""); _set_live_state(active=False, status="error", url=page_url, detail="Browser action failed", error=str(exc)[:500])
            return {"message": f"Browser action failed: {str(exc)[:500]}", "card": None}
