from __future__ import annotations

import asyncio
import re
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from agentie.core.browser_monitor import _publish_frame, _set_live_state, _stop_requested, _url, _validate_url

_PLAYWRIGHT: Playwright | None = None
_BROWSER: Browser | None = None
_CONTEXT: BrowserContext | None = None
_PAGE: Page | None = None
_LOCK = asyncio.Lock()

_CONSEQUENTIAL = re.compile(
    r"\b(?:buy|purchase|pay|checkout|place order|submit|send|delete|remove account|confirm order|transfer|publish|post)\b",
    re.I,
)


def _is_interactive_request(text: str) -> bool:
    low = " ".join(str(text or "").lower().split())
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
    if url:
        safe = _validate_url(url)
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
    candidates = [
        page.get_by_role("button", name=target, exact=False),
        page.get_by_role("link", name=target, exact=False),
        page.get_by_text(target, exact=False),
    ]
    for locator in candidates:
        try:
            if await locator.count():
                return locator.first
        except Exception:
            continue
    return None


async def _field(page: Page, name: str):
    name = name.strip().strip('"\'`')
    if name.lower() in {"search", "search box", "search field", "query"}:
        for locator in [page.get_by_role("searchbox"), page.locator('input[type="search"]'), page.locator('input[name*="search" i]')]:
            try:
                if await locator.count():
                    return locator.first
            except Exception:
                pass
    for locator in [page.get_by_label(name, exact=False), page.get_by_placeholder(name, exact=False), page.get_by_role("textbox", name=name, exact=False)]:
        try:
            if await locator.count():
                return locator.first
        except Exception:
            pass
    generic = page.locator('input:not([type="hidden"]), textarea')
    return generic.first if await generic.count() else None


def _strip_open_prefix(text: str, url: str | None) -> str:
    value = text
    if url:
        value = value.replace(url, " ", 1)
    value = re.sub(r"^\s*(?:please\s+)?(?:open|visit|go to|navigate to|browse)\s+", "", value, flags=re.I)
    return value.strip(" ,.;:-")


def _steps(text: str, url: str | None) -> list[str]:
    body = _strip_open_prefix(text, url)
    if not body:
        return []
    parts = re.split(r"\s+(?:and\s+then|then)\s+|\s*;\s*", body, flags=re.I)
    return [p.strip(" ,.;") for p in parts if p.strip(" ,.;")]


def _click_target(step: str) -> str | None:
    m = re.search(r"\bclick\s+(?:on\s+)?(.+)$", step, re.I)
    return m.group(1).strip(" .") if m else None


def _type_parts(step: str) -> tuple[str, str] | None:
    m = re.search(r"\b(?:type|enter|fill)\s+[\"']?(.+?)[\"']?\s+(?:into|in)\s+(?:the\s+)?(.+)$", step, re.I)
    if m:
        return m.group(1).strip(' "\''), m.group(2).strip(" .")
    m = re.search(r"\bfill\s+(?:the\s+)?(.+?)\s+with\s+[\"']?(.+?)[\"']?$", step, re.I)
    if m:
        return m.group(2).strip(' "\''), m.group(1).strip(" .")
    return None


async def _perform(page: Page, step: str) -> str:
    low = step.lower().strip()
    if _CONSEQUENTIAL.search(low):
        raise PermissionError(f"Stopped before consequential browser action: {step}")
    target = _click_target(step)
    if target:
        if _CONSEQUENTIAL.search(target):
            raise PermissionError(f"Stopped before consequential browser action: click {target}")
        locator = await _locator_for_text(page, target)
        if locator is None:
            raise RuntimeError(f"I couldn't find a clickable element matching “{target}”.")
        _set_live_state(active=True, status="clicking", url=page.url, detail=f"Clicking {target}")
        await locator.click(timeout=10000)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        return f"Clicked {target}"
    typed = _type_parts(step)
    if typed:
        value, field_name = typed
        field = await _field(page, field_name)
        if field is None:
            raise RuntimeError(f"I couldn't find a field matching “{field_name}”.")
        _set_live_state(active=True, status="typing", url=page.url, detail=f"Typing into {field_name}")
        await field.fill(value)
        return f"Typed into {field_name}"
    m = re.search(r"\bsearch\s+for\s+[\"']?(.+?)[\"']?$", step, re.I)
    if m:
        query = m.group(1).strip(' "\'')
        field = await _field(page, "search")
        if field is None:
            raise RuntimeError("I couldn't find a search field on this page.")
        _set_live_state(active=True, status="typing", url=page.url, detail=f"Searching for {query}")
        await field.fill(query)
        await field.press("Enter")
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        return f"Searched for {query}"
    if re.search(r"\bscroll\s+(?:down|lower)\b", low):
        _set_live_state(active=True, status="scrolling", url=page.url, detail="Scrolling down")
        await page.mouse.wheel(0, 700)
        return "Scrolled down"
    if re.search(r"\bscroll\s+(?:up|higher)\b", low):
        _set_live_state(active=True, status="scrolling", url=page.url, detail="Scrolling up")
        await page.mouse.wheel(0, -700)
        return "Scrolled up"
    m = re.search(r"\bpress\s+(enter|tab|escape|esc|arrowdown|arrowup|pagedown|pageup)\b", low, re.I)
    if m:
        key = {"esc": "Escape", "enter": "Enter", "tab": "Tab", "arrowdown": "ArrowDown", "arrowup": "ArrowUp", "pagedown": "PageDown", "pageup": "PageUp"}.get(m.group(1).lower(), m.group(1))
        _set_live_state(active=True, status="key", url=page.url, detail=f"Pressing {key}")
        await page.keyboard.press(key)
        return f"Pressed {key}"
    if re.search(r"\b(?:go back|back)\b", low):
        _set_live_state(active=True, status="navigating", url=page.url, detail="Going back")
        await page.go_back(wait_until="domcontentloaded", timeout=10000)
        return "Went back"
    if re.search(r"\b(?:go forward|forward)\b", low):
        _set_live_state(active=True, status="navigating", url=page.url, detail="Going forward")
        await page.go_forward(wait_until="domcontentloaded", timeout=10000)
        return "Went forward"
    return f"Skipped unrecognized step: {step}"


async def browser_session_command(message: str) -> dict[str, Any] | None:
    if not _is_interactive_request(message):
        return None
    async with _LOCK:
        target = _url(message)
        try:
            page = await _ensure_page(target)
            actions: list[str] = []
            if target:
                actions.append(f"Opened {target}")
            for step in _steps(message, target):
                if _stop_requested():
                    raise RuntimeError("Browser task stopped by user.")
                result = await _perform(page, step)
                actions.append(result)
                await _publish_frame(page, status="working", url=page.url, detail=result)
            title = await page.title()
            await _publish_frame(page, status="done", url=page.url, detail="Browser actions complete")
            _set_live_state(active=False, status="done", url=page.url, detail="Browser actions complete")
            return {
                "message": "Completed the browser actions.",
                "card": {"type": "browser_actions", "title": title or "Browser", "url": page.url, "actions": actions},
            }
        except PermissionError as exc:
            page_url = _PAGE.url if _PAGE and not _PAGE.is_closed() else (target or "")
            _set_live_state(active=False, status="paused", url=page_url, detail=str(exc))
            return {
                "message": str(exc) + ". I did not perform it.",
                "card": {"type": "browser_actions", "title": "Browser paused", "url": page_url, "actions": [str(exc)], "approval_needed": True},
            }
        except Exception as exc:
            page_url = _PAGE.url if _PAGE and not _PAGE.is_closed() else (target or "")
            _set_live_state(active=False, status="error", url=page_url, detail="Browser action failed", error=str(exc)[:500])
            return {"message": f"Browser action failed: {str(exc)[:500]}", "card": None}
