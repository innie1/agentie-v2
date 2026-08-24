from __future__ import annotations

"""Conservative SportyBet Nigeria Playwright adapter.

This adapter reuses Agentie's persistent, visible Chromium session inside the
Company Computer. It does not use stealth plugins, fingerprint spoofing,
residential proxies, or anti-bot bypass techniques. Human verification is
handed back to the user, page actions are paced conservatively, and live bet
submission is never retried automatically after the final click.
"""

import asyncio
import re
import time
from typing import Any, Awaitable, Callable, TypeVar

from agentie.core.sportsbook_adapters import SportsbookAdapter, SportsbookAdapterError, register_adapter

SPORTYBET_NG_URL = "https://www.sportybet.com/ng/m/"
_MIN_ACTION_GAP_SECONDS = 0.35
_READ_RETRY_DELAYS = (0.0, 0.5, 1.25)
_T = TypeVar("_T")


def _event_teams(event: str) -> list[str]:
    text = " ".join(str(event or "").split())
    parts = [p.strip() for p in re.split(r"\s+(?:vs?\.?|versus)\s+|\s+-\s+", text, flags=re.I) if p.strip()]
    return parts[:2] if len(parts) >= 2 else ([text] if text else [])


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


class SportyBetAdapter(SportsbookAdapter):
    sportsbook_id = "sportybet"
    display_name = "SportyBet Nigeria"

    def __init__(self) -> None:
        self._pace_lock = asyncio.Lock()
        self._last_action_at = 0.0

    def diagnostics(self) -> dict[str, Any]:
        return {
            "browser_mode": "persistent_visible_chromium",
            "human_takeover": True,
            "approval_required": True,
            "recheck_before_submit": True,
            "automatic_submit_retry": False,
            "anti_bot_evasion": False,
            "official_domain_only": True,
        }

    async def _pace(self) -> None:
        """Keep Agentie from hammering the sportsbook with rapid page actions."""
        async with self._pace_lock:
            now = time.monotonic()
            remaining = _MIN_ACTION_GAP_SECONDS - (now - self._last_action_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_action_at = time.monotonic()

    async def _guard_human(self, page) -> None:
        from agentie.core.browser_automation import _maybe_require_human

        await _maybe_require_human(page, None)

    async def _read_with_backoff(self, operation: Callable[[], Awaitable[_T]], label: str) -> _T:
        """Retry transient page reads only; never retry a final wager submission."""
        last_error: Exception | None = None
        for delay in _READ_RETRY_DELAYS:
            if delay:
                await asyncio.sleep(delay)
            try:
                await self._pace()
                return await operation()
            except Exception as exc:
                last_error = exc
        raise SportsbookAdapterError(f"SportyBet {label} failed after conservative retries: {last_error}")

    async def _page(self, url: str | None = None):
        # Reuse Agentie's persistent, user-visible Chromium and normal profile.
        # Import lazily so paper betting never depends on Company Computer startup.
        from agentie.core.browser_automation import _ensure_page

        await self._pace()
        page = await _ensure_page(url or SPORTYBET_NG_URL)
        await self._guard_human(page)
        return page

    async def _find_live_selection(self, page, leg: dict[str, Any]):
        event = str(leg.get("event") or "").strip()
        selection = str(leg.get("selection") or "").strip()
        expected_odds = float(leg.get("odds") or 0)
        teams = _event_teams(event)
        if not teams or not selection:
            raise SportsbookAdapterError("SportyBet needs an event and selection before it can prepare a bet.")

        async def read_body() -> str:
            return _clean_text(await page.locator("body").inner_text(timeout=10000))

        body_text = await self._read_with_backoff(read_body, "page read")
        await self._guard_human(page)
        missing = [team for team in teams if _clean_text(team) not in body_text]
        if missing:
            raise SportsbookAdapterError(
                "SportyBet could not find the requested event on the currently loaded sports page: " + event
            )

        async def find_marker():
            return await page.evaluate(
                """({teams,selection,expectedOdds}) => {
                  const norm = s => (s || '').toLowerCase().replace(/\s+/g,' ').trim();
                  const teamTokens = teams.map(norm).filter(Boolean);
                  const wanted = norm(selection);
                  const expected = Number(expectedOdds || 0);
                  const nodes = [...document.querySelectorAll('button,a,[role="button"],[class*="odd" i],[class*="selection" i],[class*="market" i]')];
                  const scored = [];
                  for (const el of nodes) {
                    const r = el.getBoundingClientRect();
                    if (r.width < 2 || r.height < 2) continue;
                    const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
                    if (!text) continue;
                    let score = 0;
                    if (text === wanted) score += 8;
                    else if (wanted && text.includes(wanted)) score += 4;
                    const nums = (text.match(/\b\d+(?:\.\d+)?\b/g) || []).map(Number);
                    if (expected && nums.some(n => Math.abs(n - expected) < 0.0001)) score += 6;
                    let cur = el;
                    let context = text;
                    for (let i=0; i<7 && cur; i++, cur=cur.parentElement) {
                      context = norm((cur.innerText || cur.textContent || '').slice(0,2500));
                      if (teamTokens.every(t => context.includes(t))) { score += 12; break; }
                    }
                    if (score >= 12) scored.push({el,score,text,context});
                  }
                  scored.sort((a,b)=>b.score-a.score);
                  if (!scored.length) return {ok:false,reason:'no candidate'};
                  if (scored.length > 1 && scored[0].score === scored[1].score && scored[0].text !== scored[1].text)
                    return {ok:false,reason:'ambiguous candidate'};
                  const id = 'agentie-sporty-' + Math.random().toString(36).slice(2);
                  scored[0].el.setAttribute('data-agentie-sporty-selection', id);
                  return {ok:true,id,text:scored[0].text};
                }""",
                {"teams": teams, "selection": selection, "expectedOdds": expected_odds},
            )

        marker = await self._read_with_backoff(find_marker, "selection lookup")
        if not marker or not marker.get("ok"):
            raise SportsbookAdapterError(
                f"SportyBet could not unambiguously match {selection} for {event}; nothing was clicked."
            )
        return page.locator(f'[data-agentie-sporty-selection="{marker["id"]}"]').first, marker

    async def _stake_input(self, page):
        selectors = (
            'input[placeholder*="stake" i]',
            'input[placeholder*="amount" i]',
            'input[name*="stake" i]',
            'input[name*="amount" i]',
        )
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = await locator.count()
                for index in range(count):
                    item = locator.nth(index)
                    if await item.is_visible():
                        return item
            except Exception:
                continue
        raise SportsbookAdapterError("SportyBet betslip opened, but Agentie could not find the real stake/amount field.")

    async def prepare_bet(self, leg: dict[str, Any]) -> dict[str, Any]:
        url = str(leg.get("url") or leg.get("sportybet_url") or SPORTYBET_NG_URL).strip()
        if not url.startswith("https://www.sportybet.com/ng/"):
            raise SportsbookAdapterError("SportyBet adapter only permits the official Nigeria sportybet.com domain.")
        page = await self._page(url)
        target, marker = await self._find_live_selection(page, leg)
        await self._pace()
        await target.click(timeout=10000)
        await page.wait_for_timeout(350)
        await self._guard_human(page)
        stake_input = await self._stake_input(page)
        await self._pace()
        await stake_input.fill(f"{float(leg['stake']):.2f}")
        await page.wait_for_timeout(250)
        await self._guard_human(page)
        return {
            "sportsbook": self.sportsbook_id,
            "page_url": page.url,
            "event": str(leg.get("event") or ""),
            "market": str(leg.get("market") or ""),
            "selection": str(leg.get("selection") or ""),
            "odds": float(leg.get("odds")),
            "stake": float(leg.get("stake")),
            "matched_text": marker.get("text"),
        }

    async def recheck_bet(self, prepared: dict[str, Any]) -> dict[str, Any]:
        page = await self._page(str(prepared.get("page_url") or SPORTYBET_NG_URL))
        selection = str(prepared.get("selection") or "").strip()
        event = str(prepared.get("event") or "").strip()
        expected = float(prepared.get("odds") or 0)
        teams = _event_teams(event)

        async def snapshot_market():
            return await page.evaluate(
                """({teams,selection,expected}) => {
                  const norm=s=>(s||'').toLowerCase().replace(/\s+/g,' ').trim();
                  const body=norm(document.body.innerText||'');
                  const available=teams.map(norm).filter(Boolean).every(t=>body.includes(t)) && body.includes(norm(selection));
                  if(!available) return {available:false};
                  const nodes=[...document.querySelectorAll('body *')].filter(el=>norm(el.innerText||'').includes(norm(selection)));
                  let best=null;
                  for(const el of nodes.slice(0,80)){
                    let cur=el;
                    for(let i=0;i<5&&cur;i++,cur=cur.parentElement){
                      const text=(cur.innerText||'').slice(0,1500);
                      const nums=(text.match(/\b\d+(?:\.\d+)?\b/g)||[]).map(Number).filter(n=>n>1&&n<10000);
                      if(nums.length){
                        const chosen=nums.sort((a,b)=>Math.abs(a-expected)-Math.abs(b-expected))[0];
                        if(best===null||Math.abs(chosen-expected)<Math.abs(best-expected)) best=chosen;
                      }
                    }
                  }
                  return {available:true,odds:best===null?expected:best,max_stake:null};
                }""",
                {"teams": teams, "selection": selection, "expected": expected},
            )

        snapshot = await self._read_with_backoff(snapshot_market, "odds recheck")
        await self._guard_human(page)
        return {
            "available": bool((snapshot or {}).get("available")),
            "odds": (snapshot or {}).get("odds", expected),
            "max_stake": (snapshot or {}).get("max_stake"),
        }

    async def submit_bet(self, prepared: dict[str, Any]) -> dict[str, Any]:
        """Submit once after approval/recheck. Never auto-retry these clicks."""
        page = await self._page(str(prepared.get("page_url") or SPORTYBET_NG_URL))
        await self._guard_human(page)
        place = page.get_by_role("button", name=re.compile(r"^\s*place\s*bet\s*$", re.I))
        if not await place.count():
            place = page.get_by_text(re.compile(r"^\s*place\s*bet\s*$", re.I)).first
        if not await place.count() or not await place.first.is_visible():
            raise SportsbookAdapterError("SportyBet Place Bet button was not available; nothing was submitted.")

        await self._pace()
        await place.first.click(timeout=10000)
        await page.wait_for_timeout(350)
        await self._guard_human(page)

        confirm = page.get_by_role("button", name=re.compile(r"^\s*confirm\s*$", re.I))
        if await confirm.count() and await confirm.first.is_visible():
            await self._pace()
            await confirm.first.click(timeout=10000)
        await page.wait_for_timeout(700)
        await self._guard_human(page)

        body = _clean_text(await page.locator("body").inner_text(timeout=10000))
        accepted = any(text in body for text in ("bet successful", "bet accepted", "successfully placed"))
        if not accepted:
            raise SportsbookAdapterError(
                "SportyBet did not show a successful/accepted confirmation after submission. Do not retry automatically; check the visible browser and betting history first."
            )
        return {
            "accepted": True,
            "sportsbook": self.sportsbook_id,
            "confirmation": "SportyBet showed bet accepted/successful",
        }

    async def abandon_prepared_bet(self, prepared: dict[str, Any]) -> None:
        try:
            page = await self._page(str(prepared.get("page_url") or SPORTYBET_NG_URL))
            selection = str(prepared.get("selection") or "").strip()
            if selection:
                node = page.get_by_text(selection, exact=False)
                if await node.count():
                    parent = node.first.locator("xpath=ancestor::*[.//button][1]")
                    buttons = parent.locator('button[aria-label*="remove" i],button[title*="remove" i],button')
                    if await buttons.count():
                        for i in range(await buttons.count()):
                            text = _clean_text(await buttons.nth(i).inner_text())
                            aria = _clean_text(await buttons.nth(i).get_attribute("aria-label"))
                            if text in {"×", "x", "remove"} or "remove" in aria:
                                await self._pace()
                                await buttons.nth(i).click(timeout=3000)
                                break
        except Exception:
            return None


def ensure_sportybet_registered() -> dict[str, str]:
    return register_adapter(SportyBetAdapter())
