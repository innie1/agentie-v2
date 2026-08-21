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
)

_TEACH_TASK: asyncio.Task | None = None
_LAST_URL = ""
_PROBED_PAGE_IDS: set[int] = set()

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
  const text = value => String(value || '').replace(/\s+/g,' ').trim();
  const fieldLabel = el => {
    if (!el) return 'field';
    const id = el.getAttribute?.('id') || '';
    let linked = '';
    if (id) {
      try {
        const escaped = window.CSS && CSS.escape ? CSS.escape(id) : id.replace(/["\\]/g,'\\$&');
        linked = document.querySelector(`label[for="${escaped}"]`)?.innerText || '';
      } catch (_) {}
    }
    const wrapping = el.closest?.('label')?.innerText || '';
    return text(linked || el.getAttribute?.('aria-label') || el.getAttribute?.('placeholder') || el.getAttribute?.('name') || wrapping || id || el.getAttribute?.('title') || el.tagName || 'field').slice(0,180) || 'field';
  };
  const actionLabel = raw => {
    const el = target(raw);
    if (!el) return 'screen item';
    const tag = String(el.tagName || '').toLowerCase();
    if (['input','textarea','select'].includes(tag)) return fieldLabel(el);
    return text(el.innerText || el.getAttribute?.('aria-label') || el.getAttribute?.('title') || el.getAttribute?.('name') || el.id || el.tagName || 'screen item').slice(0,180) || 'screen item';
  };
  document.addEventListener('click', event => {
    const el = target(event.target);
    if (!el) return;
    const tag = String(el.tagName || '').toLowerCase();
    const clickable = ['button','a'].includes(tag) || el.getAttribute?.('role') === 'button' || !!el.onclick;
    if (clickable) push({kind:'click',target:actionLabel(el)});
  }, true);
  document.addEventListener('change', event => {
    const el = target(event.target);
    if (!el) return;
    const tag = String(el.tagName || '').toLowerCase();
    if (!['input','textarea','select'].includes(tag)) return;
    const type = String(el.getAttribute?.('type') || '').toLowerCase();
    push({kind:'fill',field:fieldLabel(el),value:type === 'password' ? '' : String(el.value || ''),secret:type === 'password'});
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


def _workflow_note(item: dict[str, Any], title_prefix: str = "Taught workflow") -> dict[str, Any]:
    steps = item.get("steps") or []
    commands = [str(step.get("command") or "").strip() for step in steps if str(step.get("command") or "").strip()]
    lines = [f"{len(steps)} recorded step(s) · ran {int(item.get('run_count') or 0)} time(s)"]
    lines.extend(f"{index}. {command}" for index, command in enumerate(commands[:10], 1))
    if len(commands) > 10:
        lines.append(f"…and {len(commands)-10} more step(s)")
    return {"type": "note", "title": f"{title_prefix}: {item.get('name') or 'Workflow'}", "content": "\n".join(lines)}


def _workflow_list_note(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        content = "No taught workflows yet. Start with: Teach Agentie: <workflow name>"
    else:
        content = "\n".join(
            f"{index}. {item.get('name')} · {len(item.get('steps') or [])} steps · ran {int(item.get('run_count') or 0)} time(s)"
            for index, item in enumerate(items, 1)
        )
    return {"type": "note", "title": "Taught workflows", "content": content}


def _reset_probe_state() -> None:
    global _LAST_URL
    _LAST_URL = ""
    _PROBED_PAGE_IDS.clear()


async def _install_probe(page) -> None:
    page_id = id(page)
    if page_id not in _PROBED_PAGE_IDS:
        try:
            await page.add_init_script(script=_TEACH_SCRIPT)
            _PROBED_PAGE_IDS.add(page_id)
        except Exception:
            pass
    try:
        installed = await page.evaluate("() => Boolean(window.__agentieTeachInstalled)")
        if not installed:
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


async def _flush_focused_field(page) -> None:
    try:
        await page.evaluate("""() => {
          const el=document.activeElement;
          if(el && ['INPUT','TEXTAREA','SELECT'].includes(String(el.tagName||'').toUpperCase()))
            el.dispatchEvent(new Event('change',{bubbles:true}));
        }""")
    except Exception:
        pass


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
        _reset_probe_state()


def _ensure_polling() -> None:
    global _TEACH_TASK
    if _TEACH_TASK is None or _TEACH_TASK.done():
        _TEACH_TASK = asyncio.create_task(_poll_teaching())


async def _start(name: str, session_id: str | None) -> dict[str, Any]:
    owner = _owner_from_session(session_id)
    item = start_recording(name, owner)
    try:
        page = await browser._ensure_page()
        if not browser._USING_WSL_CHROME:
            cancel_recording();_reset_probe_state()
            return {"message": "Teach mode needs the visible browser inside Agentie Computer. Start the Computer/browser and try again.", "card": None}
        _reset_probe_state()
        await _install_probe(page)
        await _drain(page)
        _ensure_polling()
        recording = active_recording() or item
        card = {"type":"note","title":f"Teaching: {recording['name']}","content":"Recording visible browser actions locally. Perform the workflow once in Agentie Computer, then say “Stop teaching”.\n\nPasswords/secrets are never stored."}
        return {"message": f"Teach mode is recording “{item['name']}”. Perform the workflow once in the visible browser, then say “Stop teaching”.", "card": card}
    except Exception as exc:
        cancel_recording();_reset_probe_state()
        return {"message": f"Teach mode could not attach to the visible browser: {exc}", "card": None}


async def _stop() -> dict[str, Any]:
    page = browser._PAGE
    if page is not None and not page.is_closed():
        await _flush_focused_field(page)
        await _drain(page)
    item = stop_recording();_reset_probe_state()
    return {"message": f"Learned “{item['name']}” from {len(item.get('steps') or [])} browser step(s). You can now say “Run workflow {item['name']}”.", "card": _workflow_note(item,"Learned workflow")}


async def _run(name: str, session_id: str | None) -> dict[str, Any]:
    owner = _owner_from_session(session_id)
    item = get_workflow(name, owner)
    if not item:
        return {"message": "Taught workflow was not found.", "card": None}
    blocked = [step for step in item.get("steps") or [] if (step.get("metadata") or {}).get("requires_input")]
    if blocked:
        fields = ", ".join(str((step.get("metadata") or {}).get("field") or "secret field") for step in blocked)
        return {"message": f"This workflow contains a protected value ({fields}). Agentie intentionally did not save the secret. Complete the protected field manually before replay or re-teach that step without a secret.", "card": _workflow_note(item)}
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
        return {"message": f"Completed taught workflow “{item['name']}” locally.", "card": {"type":"browser_actions","title":f"Workflow · {item['name']}","url":page.url,"actions":actions,"workflow_id":item.get("id"),"provider_calls":0}}
    except browser.BrowserApprovalRequired as exc:
        return {"message": "This taught workflow reached an action that needs your approval before it can continue.", "card": {"type": "browser_approval", "url": browser._PAGE.url if browser._PAGE else "", "step": exc.step, "approval": exc.approval, "command": f"Run workflow {item['name']}"}}
    except Exception as exc:
        return {"message": f"Taught workflow failed: {str(exc)[:500]}", "card": {"type":"browser_actions","title":f"Workflow failed · {item['name']}","actions":actions+[f"Failed: {str(exc)[:300]}"],"provider_calls":0}}


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
            item = cancel_recording();_reset_probe_state()
            return {"message": f"Discarded teach recording “{item.get('name')}”." if item else "Teach mode was not recording anything.", "card": None}
        if action == "list":
            owner = _owner_from_session(session_id)
            items = list_workflows(owner)
            return {"message": f"You have {len(items)} taught workflow(s).", "card": _workflow_list_note(items)}
        if action == "show":
            item = get_workflow(str(value or ""), _owner_from_session(session_id))
            return {"message": "Taught workflow was not found.", "card": None} if not item else {"message": f"Here is “{item['name']}”.", "card": _workflow_note(item)}
        if action == "delete":
            item = delete_workflow(str(value or ""), _owner_from_session(session_id))
            return {"message": f"Deleted taught workflow “{item['name']}”.", "card": _workflow_note(item,"Deleted workflow")}
        if action == "run":
            return await _run(str(value or ""), session_id)
    except ValueError as exc:
        return {"message": str(exc), "card": None}
    return None
