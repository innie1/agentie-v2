from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from agentie.core.mcp_catalog import preset_by_id

WORKSPACE = Path.cwd() / "workspace"
CREDENTIALS_FILE = WORKSPACE / "plugin_credentials.json"
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SETUP_ERROR = re.compile(
    r"(?:connection closed|not connected|could not connect|api[_ -]?key|authentication|authorization|unauthori[sz]ed|forbidden|credential|access token|oauth|login required|sign.?in|required.*(?:key|token|login)|missing.*(?:key|token)|\b401\b|\b403\b)",
    re.I,
)


def _load() -> dict[str, dict[str, str]]:
    try:
        value = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8")) if CREDENTIALS_FILE.exists() else {}
        if not isinstance(value, dict):
            return {}
        clean: dict[str, dict[str, str]] = {}
        for server, values in value.items():
            if isinstance(values, dict):
                clean[str(server).lower()] = {str(k): str(v) for k, v in values.items() if str(v)}
        return clean
    except Exception:
        return {}


def _save(data: dict[str, dict[str, str]]) -> None:
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(CREDENTIALS_FILE, 0o600)
    except OSError:
        pass


def _preset(server_name: str) -> dict[str, Any]:
    return dict(preset_by_id(server_name) or {})


def _preset_setup(server_name: str) -> dict[str, Any]:
    return dict(_preset(server_name).get("setup") or {})


def server_environment(server_name: str) -> dict[str, str]:
    """Return only environment values assigned to this MCP server.

    Curated non-secret defaults are merged first, then locally saved credentials,
    then existing launch-environment values for declared fields. Nothing is copied
    into Agentie's global process environment.
    """
    server = str(server_name or "").strip().lower()
    preset = _preset(server)
    values = {
        str(k): str(v)
        for k, v in dict(preset.get("environment") or {}).items()
        if _ENV_NAME.fullmatch(str(k)) and str(v)
    }
    values.update(_load().get(server, {}))
    for field in _preset_setup(server).get("fields") or []:
        env_name = str(field.get("env") or field.get("id") or "").strip()
        if env_name and env_name not in values and os.environ.get(env_name):
            values[env_name] = str(os.environ[env_name])
    return {k: v for k, v in values.items() if _ENV_NAME.fullmatch(k) and v}


def apply_all_credentials() -> None:
    """Load/validate the local credential store at startup.

    Secrets are not copied into Agentie's global process environment. The MCP
    client requests server_environment(name) and passes only those values to
    that specific stdio server process.
    """
    _load()


def save_credentials(server_name: str, values: dict[str, str]) -> dict[str, Any]:
    server = str(server_name or "").strip().lower()
    if not server:
        raise ValueError("MCP server name is required.")
    if not isinstance(values, dict) or not values:
        raise ValueError("Provide at least one API key or environment credential.")
    if len(values) > 12:
        raise ValueError("Too many credential fields.")
    data = _load();stored = data.setdefault(server, {});changed = False
    for raw_name, raw_value in values.items():
        name = str(raw_name or "").strip();value = str(raw_value or "").strip()
        if not _ENV_NAME.fullmatch(name):
            raise ValueError(f"Invalid environment variable name: {name or '(blank)'}")
        if len(value) > 20000:
            raise ValueError(f"Credential for {name} is too long.")
        if not value:
            continue
        stored[name] = value;changed = True
    if not changed:
        raise ValueError("Enter a credential before saving.")
    _save(data)
    return public_setup_state(server)


def clear_credentials(server_name: str) -> dict[str, Any]:
    server = str(server_name or "").strip().lower();data = _load();data.pop(server, None);_save(data);return public_setup_state(server)


def public_setup_state(server_name: str, error: str | None = None) -> dict[str, Any]:
    server = str(server_name or "").strip().lower();setup = _preset_setup(server);stored = _load().get(server, {});fields = []
    for field in setup.get("fields") or []:
        env_name = str(field.get("env") or field.get("id") or "").strip()
        if not env_name:continue
        fields.append({
            "id":env_name,
            "env":env_name,
            "label":str(field.get("label") or env_name),
            "placeholder":str(field.get("placeholder") or ""),
            "help":str(field.get("help") or ""),
            "secret":bool(field.get("secret",True)),
            "required":bool(field.get("required",True)),
            "configured":bool(stored.get(env_name) or os.environ.get(env_name)),
        })
    required=[x for x in fields if x.get("required")]
    configured=(all(bool(x.get("configured")) for x in required) if required else bool(stored))
    auth_mode=str(setup.get("auth_mode") or "").strip().lower() or None
    custom_env_supported=bool(fields) or not auth_mode
    return {
        "type":"mcp_setup",
        "server":server,
        "title":str(setup.get("title") or f"{server or 'MCP'} setup"),
        "description":str(setup.get("description") or "Configure the credentials this MCP server needs, then test the connection."),
        "fields":fields,
        "configured":configured,
        "requires_credentials":bool(required),
        "has_saved_credentials":bool(stored),
        "custom_env_supported":custom_env_supported,
        "auth_mode":auth_mode,
        "oauth_supported":bool(setup.get("oauth_command")),
        "connect_label":str(setup.get("connect_label") or "Connect account"),
        "get_key_url":setup.get("get_key_url"),
        "connect_url":setup.get("connect_url"),
        "docs_url":setup.get("docs_url"),
        "webhook_path":setup.get("webhook_path"),
        "webhook_help":setup.get("webhook_help"),
        "error":str(error or "")[:700] or None,
        "secret_storage":"local",
    }


def setup_response(server_name: str, error: str | None = None) -> dict[str, Any]:
    state=public_setup_state(server_name,error);label=state.get("title") or f"{server_name} setup";return {"message":f"{label} needs configuration before Agentie can connect.","card":state}


def start_oauth_connection(server_name: str) -> dict[str, Any]:
    """Launch a curated provider OAuth helper without exposing credentials.

    The command must live in Agentie's curated MCP catalog; user-supplied MCP
    commands can never opt themselves into this execution path.
    """
    server=str(server_name or "").strip().lower();setup=_preset_setup(server);command=str(setup.get("oauth_command") or "").strip()
    if not command:
        raise ValueError("This MCP does not provide an Agentie-managed OAuth connection flow.")
    state=public_setup_state(server)
    if state.get("requires_credentials") and not state.get("configured"):
        raise ValueError("Save the required OAuth client credentials before connecting the account.")
    env=os.environ.copy();env.update(server_environment(server))
    try:
        process=subprocess.Popen(
            command,
            shell=True,
            cwd=str(Path.cwd()),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise ValueError(f"Could not start the OAuth connection helper: {exc}") from exc
    return {"started":True,"server":server,"pid":process.pid,"auth_mode":state.get("auth_mode"),"message":f"Opened the {state.get('title') or server} account connection flow. Finish approval in your browser, then test the connection."}


def _registered_server_names() -> list[str]:
    try:
        from agentie.core.mcp_client import list_servers
        return [str(item.get("name") or "").strip().lower() for item in list_servers() if item.get("name")]
    except Exception:return []


def infer_server_name(request_text: str, result_message: str = "") -> str | None:
    combined=f"{request_text} {result_message}".lower()
    for name in sorted(_registered_server_names(),key=len,reverse=True):
        if name and re.search(rf"(?<![a-z0-9_-]){re.escape(name)}(?![a-z0-9_-])",combined):return name
    return None


def enrich_setup_failure(request_text: str, result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(result,dict) or result.get("card") is not None:return result
    message=str(result.get("message") or result.get("result") or "")
    if not _SETUP_ERROR.search(message):return result
    server=infer_server_name(request_text,message)
    if not server:return result
    response=setup_response(server,message)
    if isinstance(response.get("card"),dict):response["card"]["retry_command"]=str(request_text or "").strip()[:20000]
    return response
