from __future__ import annotations

import os
from pathlib import Path
from typing import Any

REGISTRY_URL="https://registry.modelcontextprotocol.io"


def _npx(*args: str) -> str:
    command = " ".join(["npx", *args])
    return f"cmd /c {command}" if os.name == "nt" else command


def _repo_path() -> str:return str(Path.cwd())
def _workspace_path() -> str:return str((Path.cwd() / "workspace").resolve())
def _python() -> str:return "py" if os.name == "nt" else "python"

def _preset(id,name,description,command,requires,capabilities,auto_route=False,**extra):
    return {"id":id,"name":name,"description":description,"transport":"stdio","command":command,"requires":requires,"capabilities":capabilities,"auto_route":auto_route,"source":"curated","registry_url":REGISTRY_URL,**extra}


def presets() -> list[dict[str, Any]]:
    """Curated MCP registration templates. Nothing here is silently installed or granted to agents."""
    return [
        _preset("filesystem","Filesystem","MCP filesystem server scoped to Agentie's workspace.",_npx("-y","@modelcontextprotocol/server-filesystem",f'"{_workspace_path()}"'),"Node.js / npx",["files","folders","search","read","write"],True,permission_groups=["files_read","files_write"]),
        _preset("playwright","Playwright","Microsoft Playwright MCP for browser navigation, interaction and screenshots.",_npx("-y","@playwright/mcp@latest","--headless"),"Node.js 20+ / npx",["browser","navigation","web_automation","screenshot"],False,permission_groups=["web_read","web_interact"]),
        _preset("github","GitHub","GitHub's official MCP server for repositories, issues, pull requests and Actions.",f"{_python()} -m agentie.mcp_github_wrapper","Docker · GitHub OAuth or GITHUB_PERSONAL_ACCESS_TOKEN",["github","repositories","issues","pull_requests","actions"],True,permission_groups=["github_read","github_write"],registry_name="io.github.github/github-mcp-server",setup={
            "title":"GitHub setup",
            "description":"Connect GitHub with a personal access token when OAuth is not already configured.",
            "fields":[{"env":"GITHUB_PERSONAL_ACCESS_TOKEN","label":"Personal access token","placeholder":"github_pat_...","secret":True}],
            "get_key_url":"https://github.com/settings/personal-access-tokens/new",
            "connect_url":"https://github.com/settings/personal-access-tokens",
            "docs_url":"https://docs.github.com/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens",
        }),
        _preset("agentmail","AgentMail","Email MCP for agent inboxes, messages, threads, drafts and attachments.",_npx("-y","agentmail-mcp"),"Node.js / npx · AGENTMAIL_API_KEY",["email","inboxes","messages","threads","drafts","attachments"],True,permission_groups=["email_read","email_write","send"],sensitive_tools=["send_message","reply_to_message","forward_message","send_draft","delete_message","delete_thread","delete_draft","delete_inbox"],setup={
            "title":"AgentMail setup",
            "description":"Add your AgentMail API key, then Agentie can connect to the real AgentMail inbox tools.",
            "fields":[{"env":"AGENTMAIL_API_KEY","label":"AgentMail API key","placeholder":"am_...","secret":True}],
            "get_key_url":"https://console.agentmail.to",
            "connect_url":"https://console.agentmail.to",
            "docs_url":"https://docs.agentmail.to/knowledge-base/getting-api-key",
        }),
        _preset("google-workspace","Google Workspace","Real Google Workspace tools for Gmail, Drive, Docs, Sheets, Slides, Calendar and Contacts.",_npx("-y","@dguido/google-workspace-mcp"),"Node.js / npx · Google OAuth desktop client",["gmail","drive","docs","sheets","slides","calendar","contacts"],True,permission_groups=["google_read","google_write","email_read","email_write","calendar_read","calendar_write","files_read","files_write"],sensitive_tools=["sendEmail","deleteEmail","modifyEmail","createEvent","updateEvent","deleteEvent","deleteItem","emptyTrash","shareFile","removePermission","createContact","updateContact","deleteContact"],environment={"GOOGLE_WORKSPACE_SERVICES":"drive,docs,sheets,slides,calendar,gmail,contacts","GOOGLE_WORKSPACE_TOON_FORMAT":"true"},setup={
            "title":"Google Workspace setup",
            "description":"Create a Google OAuth Desktop app, save its client ID and secret here, then connect your Google account. Gmail, Drive, Docs, Sheets, Slides, Calendar and Contacts are enabled.",
            "auth_mode":"oauth_with_credentials",
            "connect_label":"Connect Google account",
            "fields":[
                {"env":"GOOGLE_CLIENT_ID","label":"Google OAuth client ID","placeholder":"...apps.googleusercontent.com","secret":False},
                {"env":"GOOGLE_CLIENT_SECRET","label":"Google OAuth client secret","placeholder":"GOCSPX-...","secret":True},
            ],
            "oauth_command":_npx("-y","@dguido/google-workspace-mcp","auth"),
            "get_key_url":"https://console.cloud.google.com/apis/credentials",
            "connect_url":"https://console.cloud.google.com/apis/credentials",
            "docs_url":"https://github.com/dguido/google-workspace-mcp",
        }),
        _preset("canva","Canva","Canva's official remote MCP for designs, assets, brand resources, exports and collaboration.",_npx("-y","mcp-remote@latest","https://mcp.canva.com/mcp"),"Node.js / npx · Canva account",["designs","design_generation","design_editing","assets","brand","export","comments"],True,permission_groups=["design_read","design_write"],setup={
            "title":"Canva setup",
            "description":"Connect your Canva account through Canva's official OAuth approval page. No Canva API secret is stored by Agentie for this connection.",
            "auth_mode":"oauth",
            "connect_label":"Connect Canva account",
            "oauth_command":_npx("-y","-p","mcp-remote@latest","mcp-remote-client","https://mcp.canva.com/mcp"),
            "connect_url":"https://www.canva.com",
            "docs_url":"https://www.canva.dev/docs/mcp/",
        }),
        _preset("memory","Memory","Knowledge-graph memory for entities, observations and relations.",_npx("-y","@modelcontextprotocol/server-memory"),"Node.js / npx",["knowledge_graph","entities","relations","memory"],True,permission_groups=["memory_read","memory_write"]),
        _preset("sequential-thinking","Sequential Thinking","Structured multi-step problem solving and reflective reasoning.",_npx("-y","@modelcontextprotocol/server-sequential-thinking"),"Node.js / npx",["reasoning","planning","sequential_thinking"],True,permission_groups=["read"]),
        _preset("fetch","Fetch","Fetch and convert web content through an MCP server.","uvx mcp-server-fetch","uv / uvx",["url_fetch","web_page","web_content"],True,permission_groups=["web_read"]),
        _preset("time-mcp","Time","Timezone-aware time queries and timezone conversion.","uvx mcp-server-time","uv / uvx",["timezone","time_conversion"],False,permission_groups=["read"]),
        _preset("git","Git","Read, search and manipulate the current local Git repository.",f'uvx mcp-server-git --repository "{_repo_path()}"',"uv / uvx",["git","repository","commit","branch","diff","log"],True,permission_groups=["git_read","git_write"]),
        _preset("everything","Everything","MCP reference/test server exposing tools, resources and prompts.",_npx("-y","@modelcontextprotocol/server-everything"),"Node.js / npx",["mcp_testing","tools","resources","prompts"],False,permission_groups=["read"]),
    ]


def preset_by_id(preset_id: str) -> dict[str, Any] | None:
    needle = str(preset_id or "").strip().lower()
    for item in presets():
        if item["id"] == needle:return item
    return None


def registration_command(preset_id: str) -> str | None:
    item = preset_by_id(preset_id)
    if not item:return None
    return f"Add MCP server {item['id']} using {item['command']}"
