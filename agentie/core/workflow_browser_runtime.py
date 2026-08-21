from __future__ import annotations

import asyncio
import re
from typing import Any

from agentie.core import browser_automation as browser
from agentie.core.workflow_teaching import (
    active_recording,
    cancel_recording,
    delete_workflow,
    get_workflow,
    list_workflows,
    mark_run,
    record_browser_event,
    start_recording,
    stop_recording,
    workflow_card,
)

_TEACH_TASK: asyncio.Task | None = None
_LAST_URL = ""

_TEACH_SCRIPT = r"""
(() => {
  if (window.__agentieTeachInstalled) return;
  window.__agentieTeachInstalled = true;
  window.__agentieTeachEvents = window.__agentieTeachEvents || [];
  const push = item => {
    item.at = Date.now();
    window.__agentieTeachEvents.push(item);
    if (window.__agentieTeachEvents.length > 200) window.__agentieTeachEvents.splice(0, 80);
  };
  const target = raw => raw && raw.closest ? (raw.closest('button,a,input,textarea,select,[role="button"],[contenteditable="true"]') || raw) : raw;
  const label = raw => {
    const el = target(raw);
    if (!el) return 'screen item';
    const aria = el.getAttribute && el.getAttribute('aria-label');
    const placeholder = el.getAttribute && el.getAttribute('placeholder');
    const name = el.getAttribute && el.getAttribute('name');
    const title = el.getAttribute && el.getAttribute('title');
    const text = (el.innerText || el.value || aria || placeholder || title || name || el.id || el.tagName || 'screen item');
    return String(text).replace(/\s+/g,' ').trim().slice(0,180) || 'screen item';
  };
  document.addEventListener('click', event => {
    const el = target(event.target);
    if (!el) return;
    const tag = String(el.tagName || '').toLowerCase();
    const clickable = ['button','a'].includes(tag) || el.getAttribute?.('role') === 'button' || !!el.onclick;
    if (clickable) push({kind:'click',target:label(el)});
  }, true);
  document.addEventListener('change', event => {
    const el = target(event.target);
    if (!el) return;
    const tag = String(el.tagName || '').toLowerCase();
    if (!['input','textarea','select'].includes(tag)) return;
    const type = String(el.getAttribute?.('type') || '').toLowerCase();
    push({kind:'fill',field:label(el),value:type === 'password' ? '' : String(el.value || ''),secret:type === 'password'});
  }, true);
  document.addEventListener('keydown', event => {
    if (['Enter','Tab','Escape'].includes(event.key)) push({kind:'key',key:event.key});
  }, true);
})();
"""


def _owner_from_session(session_id: str | None) -> str | None:
    m = re.match(r"^agent:(agt_[a-z0-9]+):", str(session_id or ""), re.I)
    return m.group(1) if m else None


def _teach_command(message: str) -> tuple[str, str | None] | None:
    text = " ".join(str(message or "").strip().split())
    lower = text.casefold().strip(" .?!")
    m = re.match(r"^(?:teach agentie|teach me|start teaching|start teach mode|teach workflow)\s*(?::|-)?\s+(.+)$", text, re.I)
    if m:
        return "start", m.group(1).strip(" .?!\"“”")
    if lower in {"stop teaching", "finish teaching", "save taught workflow", "stop teach mode"}:
        return "stop", None
    if lower in {"cancel teaching", "cancel teach mode", "discard taught workflow"}:
        return "cancel", None
    if lower in {"show taught workflows", "list taught workflows", "show workflows", "list workflows", "my workflows"}:
        return "list", None
    m = re.match(r"^(?:run|replay|do)\s+(?:taught\s+)?workflow\s+(.+)$", text, re.I)
    if m:
        return "run", m.group(1).strip(" .?!\"“”")
    m = re.match(r"^(?:delete|remove)\s+(?:taught\s+)?workflow\s+(.+)$", text, re.I)
    if m:
        return "delete", m.group(1).strip(" .?!\"“”")
    m = re.match(r"^(?:show|open|inspect)\s+(?:taught\s+)?workflow\s+(.+)$", text, re.I)
    if m:
        return "show", m.group(1).strip(" .?!\"“”")
    return None


async def _install_probe(page) -> None:
    try:
        await page.add_init_script(script=_TEACH_SCRIPT)
    except Exception:
        pass
    try:
        await page.evaluate(_TEACH_SCRIPT)
    except Exception:
        pass


async def _drain(page) -> None:
    global _LAST_URL
    url = str(getattr(page, "url", "") or "")
    if url.startswith(("http://", "https://")) and url != _LAST_URL:
        record_browser_event({"kind": "open", "url": url})
        _LAST_URL = url
    try:
        events = await page.evaluate("() => { const a = window.__agentieTeachEvents || []; window.__agentieTeachEvents = []; return a; }")
    except Exception:
        await _install_probe(page)
        return
    for event in events or []:
        if isinstance(event, dict):
            record_browser_event(event)


async def _poll_teaching() -> None:
    global _TEACH_TASK
    try:
        while active_recording():
            page = browser._PAGE
            if page is not None and not page.is_closed():
                await _install_probe(page)
                await _drain(page)
            await asyncio.sleep(0.35)
    finally:
        _TEACH_TASK = None


def _ensure_polling() -> None:
    global _TEACH_TASK
    if _TEACH_TASK is None or _TEACH_TASK.done():
        _TEACH_TASK = asyncio.create_task(_poll_teaching())


async def _start(name: str, session_id: str | None) -> dict[str, Any]:
    global _LAST_URL
    owner = _owner_from_session(session_id)
    item = start_recording(name, owner)
    try:
        page = await browser._ensure_page()
        if not browser._USING_WSL_CHROME:
            cancel_recording()
            return {"message": "Teach mode needs the visible browser inside Agentie Computer. Start the Computer/browser and try again.", "card": None}
        _LAST_URL = ""
        await _install_probe(page)
        await _drain(page)
        _ensure_polling()
        card = workflow_card(active_recording() or item, "workflow_teach")
        return {"message": f"Teach mode is recording “{item['name']}”. Perform the workflow once in the visible browser, then say “Stop teaching”.", "card": card}
    except Exception as exc:
        cancel_recording()
        return {"message": f"Teach mode could not attach to the visible browser: {exc}", "card": None}


async def _stop() -> dict[str, Any]:
    page = browser._PAGE
    if page is not None and not page.is_closed():
        await _drain(page)
    item = stop_recording()
    return {"message": f"Learned “{item['name']}” from {len(item.get('steps') or [])} browser step(s). You can now say “Run workflow {item['name']}”.", "card": workflow_card(item)}


async def _run(name: str, session_id: str | None) -> dict[str, Any]:
    owner = _owner_from_session(session_id)
    item = get_workflow(name, owner)
    if not item:
        return {"message": "Taught workflow was not found.", "card": None}
    blocked = [step for step in item.get("steps") or [] if (step.get("metadata") or {}).get("requires_input")]
    if blocked:
        fields = ", ".join(str((step.get("metadata") or {}).get("field") or "secret field") for step in blocked)
        return {"message": f"This workflow contains a protected value ({fields}). Agentie intentionally did not save the secret. Re-teach that step using a non-secret value or complete the protected field manually before replay.", "card": workflow_card(item)}
    actions: list[str] = []
    try:
        page = await browser._ensure_page()
        for step in item.get("steps") or []:
            command = str(step.get("command") or "").strip()
            if not command:
                continue
            if str(step.get("kind")) == "open":
                url = str((step.get("metadata") or {}).get("url") or "").strip()
                if url:
                    page = await browser._ensure_page(url)
                    actions.append(f"Opened {url}")
                    continue
            result, page = await browser._perform(page, command)
            actions.append(result)
            await browser._publish_frame(page, status="working", url=page.url, detail=result)
        mark_run(str(item.get("id")))
        await browser._publish_frame(page, status="done", url=page.url, detail=f"Workflow {item['name']} complete")
        return {"message": f"Completed taught workflow “{item['name']}” locally.", "card": {**workflow_card(get_workflow(str(item.get('id'))) or item, "workflow_run"), "actions": actions, "url": page.url}}
    except browser.BrowserApprovalRequired as exc:
        return {"message": "This taught workflow reached an action that needs your approval before it can continue.", "card": {"type": "browser_approval", "url": browser._PAGE.url if browser._PAGE else "", "step": exc.step, "approval": exc.approval, "command": f"Run workflow {item['name']}"}}
    except Exception as exc:
        return {"message": f"Taught workflow failed: {str(exc)[:500]}", "card": {**workflow_card(item, "workflow_run"), "status": "failed", "error": str(exc)[:500], "actions": actions}}


async def route_taught_workflow_request(message: str, session_id: str | None = None) -> dict[str, Any] | None:
    parsed = _teach_command(message)
    if not parsed:
        return None
    action, value = parsed
    try:
        if action == "start":
            return await _start(str(value or ""), session_id)
        if action == "stop":
            return await _stop()
        if action == "cancel":
            item = cancel_recording()
            return {"message": f"Discarded teach recording “{item.get('name')}”." if item else "Teach mode was not recording anything.", "card": None}
        if action == "list":
            owner = _owner_from_session(session_id)
            items = list_workflows(owner)
            return {"message": f"You have {len(items)} taught workflow(s).", "card": {"type": "taught_workflows", "items": [workflow_card(x) for x in items]}}
        if action == "show":
            item = get_workflow(str(value or ""), _owner_from_session(session_id))
            return {"message": "Taught workflow was not found.", "card": None} if not item else {"message": f"Here is “{item['name']}”.", "card": workflow_card(item)}
        if action == "delete":
            item = delete_workflow(str(value or ""), _owner_from_session(session_id))
            return {"message": f"Deleted taught workflow “{item['name']}”.", "card": {**workflow_card(item), "status": "deleted"}}
        if action == "run":
            return await _run(str(value or ""), session_id)
    except ValueError as exc:
        return {"message": str(exc), "card": None}
    return None
