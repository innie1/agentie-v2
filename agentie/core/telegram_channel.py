from __future__ import annotations

import asyncio
import json
import os
import random
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

WORKSPACE = Path.cwd() / "workspace"
STATE_FILE = WORKSPACE / "telegram_channels.json"
KEY_FILE = WORKSPACE / ".telegram_channel.key"
API_ROOT = "https://api.telegram.org"
_TASKS: dict[str, asyncio.Task] = {}
_LOCK = threading.RLock()
_HANDLER: Callable[[str, str, str], Awaitable[dict[str, Any]]] | None = None
_TOKEN_RE = re.compile(r"^\d{5,20}:[A-Za-z0-9_-]{20,}$")


class TelegramError(RuntimeError):
    def __init__(self, message: str, *, code: int = 0, retry_after: int = 0):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


def _chmod(path: Path) -> None:
    try: os.chmod(path, 0o600)
    except OSError: pass


def _fernet() -> Fernet:
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not KEY_FILE.exists():
        KEY_FILE.write_bytes(Fernet.generate_key());_chmod(KEY_FILE)
    return Fernet(KEY_FILE.read_bytes().strip())


def _encrypt(value: str) -> str:return _fernet().encrypt(value.encode()).decode()
def _decrypt(value: str) -> str:
    try:return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError) as exc:raise TelegramError("Telegram credential could not be decrypted.") from exc


def _load() -> dict[str, dict[str, Any]]:
    with _LOCK:
        try:
            data=json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
            return data if isinstance(data,dict) else {}
        except (OSError,json.JSONDecodeError,TypeError):return {}


def _save(data: dict[str, dict[str, Any]]) -> None:
    with _LOCK:
        STATE_FILE.parent.mkdir(parents=True,exist_ok=True)
        tmp=STATE_FILE.with_suffix(".tmp");tmp.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8");_chmod(tmp);tmp.replace(STATE_FILE);_chmod(STATE_FILE)


def _owner(value: str | None) -> str:
    value=str(value or "local-user").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}",value):raise ValueError("Invalid Agentie user id.")
    return value


def public_state(owner_id: str = "local-user") -> dict[str, Any]:
    owner=_owner(owner_id);row=_load().get(owner,{})
    return {"type":"telegram_setup","owner_id":owner,"configured":bool(row.get("token_ciphertext")),"connected":bool(row.get("paired_chat_id") and row.get("enabled")),"enabled":bool(row.get("enabled")),"bot_username":row.get("bot_username"),"paired_user":row.get("paired_user"),"paired_chat_id":str(row.get("paired_chat_id")) if row.get("paired_chat_id") else None,"active_agent_id":row.get("active_agent_id"),"pair_code":row.get("pair_code") if row.get("pair_expires_at",0)>time.time() else None,"pair_expires_at":row.get("pair_expires_at"),"last_error":row.get("last_error"),"has_saved_token":bool(row.get("token_ciphertext")),"secret_storage":"encrypted_local"}


def _request_sync(token: str, method: str, payload: dict[str, Any] | None = None, *, timeout: int = 40) -> Any:
    url=f"{API_ROOT}/bot{token}/{method}";body=json.dumps(payload or {}).encode()
    req=urllib.request.Request(url,data=body,headers={"Content-Type":"application/json","User-Agent":"Agentie-Telegram/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as response:data=json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        try:data=json.loads(exc.read().decode())
        except (json.JSONDecodeError,UnicodeDecodeError):data={"description":f"Telegram HTTP {exc.code}","error_code":exc.code}
    except (OSError,ValueError) as exc:raise TelegramError(f"Telegram request failed: {exc}") from exc
    if not data.get("ok"):
        params=data.get("parameters") or {};raise TelegramError(str(data.get("description") or "Telegram API error"),code=int(data.get("error_code") or 0),retry_after=int(params.get("retry_after") or 0))
    return data.get("result")


def _upload_sync(token: str, method: str, chat_id: Any, field: str, path: Path, caption: str = "") -> Any:
    boundary="----Agentie"+secrets.token_hex(12);parts=[]
    for name,value in (("chat_id",str(chat_id)),("caption",caption[:1024])):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    mime="image/jpeg" if path.suffix.lower() in {".jpg",".jpeg"} else "image/png" if path.suffix.lower()==".png" else "application/octet-stream"
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{path.name}\"\r\nContent-Type: {mime}\r\n\r\n".encode()+path.read_bytes()+b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode());req=urllib.request.Request(f"{API_ROOT}/bot{token}/{method}",data=b"".join(parts),headers={"Content-Type":f"multipart/form-data; boundary={boundary}","User-Agent":"Agentie-Telegram/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=90) as response:data=json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        try:data=json.loads(exc.read().decode())
        except (json.JSONDecodeError,UnicodeDecodeError):data={"description":f"Telegram HTTP {exc.code}","error_code":exc.code}
    if not data.get("ok"):
        params=data.get("parameters") or {};raise TelegramError(str(data.get("description") or "Telegram upload failed"),code=int(data.get("error_code") or 0),retry_after=int(params.get("retry_after") or 0))
    return data.get("result")


async def api_request(token: str, method: str, payload: dict[str, Any] | None = None, *, attempts: int = 4) -> Any:
    for attempt in range(attempts):
        try:return await asyncio.to_thread(_request_sync,token,method,payload)
        except TelegramError as exc:
            if exc.code in {401,403}:raise
            if attempt+1>=attempts:raise
            await asyncio.sleep(max(exc.retry_after, min(8,2**attempt))+random.random()/3)


async def configure(owner_id: str, token: str) -> dict[str, Any]:
    owner=_owner(owner_id);token=str(token or "").strip()
    if not _TOKEN_RE.fullmatch(token):raise ValueError("Enter a valid Telegram Bot API token from BotFather.")
    me=await api_request(token,"getMe");await api_request(token,"deleteWebhook",{"drop_pending_updates":False})
    data=_load();old=data.get(owner,{})
    data[owner]={"token_ciphertext":_encrypt(token),"bot_id":me.get("id"),"bot_username":me.get("username"),"enabled":True,"offset":int(old.get("offset") or 0),"paired_chat_id":old.get("paired_chat_id"),"paired_user_id":old.get("paired_user_id"),"paired_user":old.get("paired_user"),"active_agent_id":old.get("active_agent_id"),"last_error":None,"outbox":old.get("outbox") or []};_save(data)
    await start_owner(owner);return public_state(owner)


def create_pair_code(owner_id: str, *, ttl_seconds: int = 600) -> dict[str, Any]:
    owner=_owner(owner_id);data=_load();row=data.get(owner)
    if not row or not row.get("token_ciphertext"):raise ValueError("Save a Telegram bot token first.")
    row["pair_code"]="".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8));row["pair_expires_at"]=time.time()+ttl_seconds;_save(data)
    return public_state(owner)


async def disconnect(owner_id: str, *, revoke_token: bool = False) -> dict[str, Any]:
    owner=_owner(owner_id);task=_TASKS.pop(owner,None)
    if task:task.cancel()
    data=_load();row=data.get(owner,{})
    row.update({"enabled":False,"paired_chat_id":None,"paired_user_id":None,"paired_user":None,"pair_code":None,"pair_expires_at":0,"active_agent_id":None,"outbox":[]})
    if revoke_token:row.pop("token_ciphertext",None);row.pop("bot_username",None);row.pop("bot_id",None)
    data[owner]=row;_save(data);return public_state(owner)


def set_handler(handler: Callable[[str, str, str], Awaitable[dict[str, Any]]]) -> None:
    global _HANDLER;_HANDLER=handler


def _find_owner_by_token_bot(bot_id: Any) -> str | None:
    return next((owner for owner,row in _load().items() if str(row.get("bot_id"))==str(bot_id) and row.get("enabled")),None)


def _authorized(row: dict[str, Any], message: dict[str, Any]) -> bool:
    chat=message.get("chat") or {};user=message.get("from") or {}
    return str(chat.get("id"))==str(row.get("paired_chat_id")) and str(user.get("id"))==str(row.get("paired_user_id")) and str(chat.get("type"))=="private"


async def _send(token: str, chat_id: Any, text: str, reply_markup: dict[str, Any] | None = None) -> Any:
    payload={"chat_id":chat_id,"text":str(text or "")[:4096],"disable_web_page_preview":True}
    if reply_markup:payload["reply_markup"]=reply_markup
    return await api_request(token,"sendMessage",payload)


def _attachment_path(card: Any) -> tuple[Path | None, bool]:
    if not isinstance(card,dict):return None,False
    raw=card.get("path") or card.get("file_path") or card.get("artifact_path")
    if not raw and card.get("name"):raw=WORKSPACE/str(card["name"])
    if not raw:return None,False
    try:
        path=Path(raw);path=path if path.is_absolute() else (Path.cwd()/path);path=path.resolve();allowed=(WORKSPACE.resolve(),Path.cwd().resolve())
        if not any(path==root or root in path.parents for root in allowed) or not path.is_file():return None,False
    except OSError:return None,False
    image=card.get("kind")=="image" or path.suffix.lower() in {".png",".jpg",".jpeg",".webp"}
    return path,image


async def _send_attachment(token: str, chat_id: Any, card: Any) -> bool:
    path,image=_attachment_path(card)
    if not path:return False
    await asyncio.to_thread(_upload_sync,token,"sendPhoto" if image else "sendDocument",chat_id,"photo" if image else "document",path,str((card or {}).get("title") or path.name));return True


def _approval_keyboard(approval_id: str) -> dict[str, Any]:
    return {"inline_keyboard":[[{"text":"Approve","callback_data":f"approval:{approval_id}:approve"},{"text":"Reject","callback_data":f"approval:{approval_id}:reject"},{"text":"Edit","callback_data":f"approval:{approval_id}:edit"}]]}


def _card_text(card: Any) -> tuple[str, dict[str, Any] | None]:
    if not isinstance(card,dict):return "",None
    approval=None
    if card.get("type")=="mcp_approval":approval=card.get("approval")
    elif card.get("type")=="approvals" and card.get("items"):approval=card["items"][0]
    if isinstance(approval,dict):return f"\n\nApproval required\n{approval.get('reason') or approval.get('action') or 'Consequential action'}",_approval_keyboard(str(approval.get("id")))
    if card.get("type") in {"artifact","file","document","image"}:return f"\n\nFile: {card.get('name') or card.get('document_name') or card.get('title') or 'Agentie file'}",None
    return "",None


async def _commands(owner: str, row: dict[str, Any], token: str, message: dict[str, Any], text: str) -> bool:
    chat_id=(message.get("chat") or {}).get("id");low=text.strip().casefold()
    if low in {"/start","/help"}:
        await _send(token,chat_id,"Agentie is connected. Talk naturally, or use /manager, /agent <name>, /status, /routines, and /approvals.");return True
    if low.startswith("/manager"):
        row["active_agent_id"]="manager";await _send(token,chat_id,"Now talking to Manager.");return True
    if low.startswith("/agent"):
        from agentie.core.agent_registry import get_agent, list_agents
        query=text[len("/agent"):].strip()
        if not query:
            await _send(token,chat_id,"Agents: "+", ".join(str(a.get("name")) for a in list_agents()));return True
        agent=get_agent(query)
        if not agent:await _send(token,chat_id,f"I couldn't find agent “{query}”. Use /agent to list agents.");return True
        row["active_agent_id"]=agent["id"];await _send(token,chat_id,f"Now talking to {agent['name']}.");return True
    if low=="/status":
        from agentie.core.job_engine import list_jobs
        jobs=list_jobs()[:10];await _send(token,chat_id,"Recent tasks:\n"+("\n".join(f"• {j.get('status')} — {j.get('instruction','')[:100]}" for j in jobs) or "No tasks yet."));return True
    if low=="/routines":
        from agentie.core.routine_engine import list_routines
        items=[x for x in list_routines() if x.get("status")!="deleted"];await _send(token,chat_id,"Routines:\n"+("\n".join(f"• {x.get('name')} — {x.get('status')}" for x in items) or "No routines yet."));return True
    if low=="/approvals":
        from agentie.tools.approval_tools import recent_approvals
        items=recent_approvals(status="pending",limit=10)
        if not items:await _send(token,chat_id,"No pending approvals.")
        for item in items:await _send(token,chat_id,f"Approval required\n{item.get('reason') or item.get('action')}",_approval_keyboard(item["id"]))
        return True
    natural=re.match(r"^(?:talk|switch|connect)\s+(?:me\s+)?to\s+(.+?)[.!]?$",text,re.IGNORECASE)
    if natural:
        from agentie.core.agent_registry import get_agent
        agent=get_agent(natural.group(1).strip())
        if agent:row["active_agent_id"]=agent["id"];await _send(token,chat_id,f"Now talking to {agent['name']}.");return True
    return False


async def _callback(owner: str, row: dict[str, Any], token: str, callback: dict[str, Any]) -> None:
    message=callback.get("message") or {};chat=message.get("chat") or {};user=callback.get("from") or {}
    if str(chat.get("id"))!=str(row.get("paired_chat_id")) or str(user.get("id"))!=str(row.get("paired_user_id")):return
    callback_data=str(callback.get("data") or "");matched=re.fullmatch(r"approval:([A-Za-z0-9_-]+):(approve|reject|edit)",callback_data)
    if not matched:return
    aid,decision=matched.groups()
    await api_request(token,"answerCallbackQuery",{"callback_query_id":callback.get("id")})
    if decision=="edit":
        from agentie.tools.approval_tools import resolve_approval
        try:resolve_approval(aid,False)
        except ValueError:pass
        row["editing_approval_id"]=aid;await _send(token,chat.get("id"),"Send the revised instruction. The original action was rejected and was not executed.");return
    from agentie.tools.approval_tools import resolve_approval
    try:item=resolve_approval(aid,decision=="approve");status=item.get("status")
    except ValueError as exc:await _send(token,chat.get("id"),str(exc));return
    await api_request(token,"editMessageReplyMarkup",{"chat_id":chat.get("id"),"message_id":message.get("message_id"),"reply_markup":{"inline_keyboard":[]}})
    await _send(token,chat.get("id"),f"Approval {status}.")


async def process_update(owner: str, update: dict[str, Any], token: str | None = None) -> None:
    data=_load();row=data.get(owner)
    if not row:return
    token=token or _decrypt(row["token_ciphertext"])
    callback=update.get("callback_query")
    if callback:await _callback(owner,row,token,callback);data[owner]=row;_save(data);return
    message=update.get("message") or {};text=str(message.get("text") or message.get("caption") or "").strip();chat=message.get("chat") or {};user=message.get("from") or {}
    if row.get("pair_code") and time.time()<float(row.get("pair_expires_at") or 0) and secrets.compare_digest(text.upper(),str(row["pair_code"]).upper()):
        if chat.get("type")!="private":await _send(token,chat.get("id"),"Pairing is only allowed in a private chat with this bot.");return
        row.update({"paired_chat_id":chat.get("id"),"paired_user_id":user.get("id"),"paired_user":user.get("username") or user.get("first_name") or str(user.get("id")),"pair_code":None,"pair_expires_at":0,"enabled":True});data[owner]=row;_save(data);await _send(token,chat.get("id"),"Paired securely with Agentie. You can now talk to your agents.");return
    if not _authorized(row,message):return
    if not text:await _send(token,chat.get("id"),"I received the attachment, but this Agentie build needs a text or caption to route it.");return
    if row.pop("editing_approval_id",None):text="Revise the pending action instead of approving it: "+text
    if await _commands(owner,row,token,message,text):data[owner]=row;_save(data);return
    if not _HANDLER:await _send(token,chat.get("id"),"Agentie is still starting. Try again in a moment.");return
    result=await _HANDLER(owner,str(row.get("active_agent_id") or "general"),text);body=str(result.get("message") or result.get("result") or "Done.");extra,keyboard=_card_text(result.get("card"));await _send(token,chat.get("id"),body+extra,keyboard);await _send_attachment(token,chat.get("id"),result.get("card"))
    data=_load();data[owner].update({"active_agent_id":row.get("active_agent_id"),"last_error":None});_save(data)


async def poll_once(owner: str) -> int:
    data=_load();row=data.get(owner)
    if not row or not row.get("enabled") or not row.get("token_ciphertext"):return 0
    token=_decrypt(row["token_ciphertext"]);offset=int(row.get("offset") or 0)
    updates=await api_request(token,"getUpdates",{"offset":offset,"limit":100,"timeout":25,"allowed_updates":["message","callback_query"]},attempts=2)
    count=0
    for update in updates or []:
        uid=int(update.get("update_id") or 0)
        if uid<offset:continue
        await process_update(owner,update,token);offset=uid+1;count+=1
        latest=_load();latest[owner]["offset"]=offset;latest[owner]["last_error"]=None;_save(latest)
    return count


async def _poll_loop(owner: str) -> None:
    while True:
        try:await flush_outbox(owner);await poll_once(owner)
        except asyncio.CancelledError:raise
        except TelegramError as exc:
            data=_load();row=data.get(owner,{})
            row["last_error"]="Bot token was revoked or is invalid." if exc.code in {401,403} else str(exc)[:300]
            if exc.code in {401,403}:row["enabled"]=False
            data[owner]=row;_save(data)
            if exc.code in {401,403}:return
            await asyncio.sleep(max(2,exc.retry_after or 5))
        except Exception as exc:  # noqa: BLE001 - keep one bot failure from stopping other tenants
            data=_load();row=data.get(owner,{ });row["last_error"]=str(exc)[:300];data[owner]=row;_save(data);await asyncio.sleep(5)


async def start_owner(owner_id: str) -> None:
    owner=_owner(owner_id);row=_load().get(owner,{})
    if not row.get("enabled") or not row.get("token_ciphertext"):return
    task=_TASKS.get(owner)
    if not task or task.done():_TASKS[owner]=asyncio.create_task(_poll_loop(owner),name=f"telegram:{owner}")


async def start_all() -> None:
    for owner,row in _load().items():
        if row.get("enabled"):await start_owner(owner)


def queue_proactive(message: str, card: dict[str, Any] | None = None, *, owner_id: str | None = None) -> int:
    data=_load();count=0
    for owner,row in data.items():
        if owner_id and owner!=owner_id:continue
        if not row.get("enabled") or not row.get("paired_chat_id"):continue
        row.setdefault("outbox",[]).append({"id":secrets.token_hex(8),"message":str(message)[:12000],"card":card,"attempts":0,"next_attempt":0});row["outbox"]=row["outbox"][-500:];count+=1
    if count:_save(data)
    return count


async def flush_outbox(owner: str) -> int:
    data=_load();row=data.get(owner)
    if not row or not row.get("enabled") or not row.get("paired_chat_id"):return 0
    token=_decrypt(row["token_ciphertext"]);sent=0;remaining=[]
    for item in row.get("outbox") or []:
        if float(item.get("next_attempt") or 0)>time.time():remaining.append(item);continue
        try:
            extra,keyboard=_card_text(item.get("card"));await _send(token,row["paired_chat_id"],str(item.get("message") or "")+extra,keyboard);await _send_attachment(token,row["paired_chat_id"],item.get("card"));sent+=1
        except TelegramError as exc:
            item["attempts"]=int(item.get("attempts") or 0)+1
            if item["attempts"]<6 and exc.code not in {401,403}:item["next_attempt"]=time.time()+max(exc.retry_after,2**item["attempts"]);remaining.append(item)
    row["outbox"]=remaining;data[owner]=row;_save(data);return sent
