import json
import os
from urllib.parse import quote
from urllib.request import Request, urlopen
from agents import function_tool

def _request(path: str) -> dict | list:
    url = f"https://api.github.com{path}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Agentie/0.1"}
    token = os.getenv("GITHUB_TOKEN")
    if token: headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, headers=headers), timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))

@function_tool
def github_repo_info(owner: str, repo: str) -> str:
    """Read public metadata for a GitHub repository. Uses GITHUB_TOKEN if configured."""
    data = _request(f"/repos/{quote(owner)}/{quote(repo)}")
    keep = {k: data.get(k) for k in ["full_name", "description", "default_branch", "language", "stargazers_count", "forks_count", "open_issues_count", "html_url"]}
    return json.dumps(keep, indent=2)

@function_tool
def github_read_file(owner: str, repo: str, path: str, ref: str = "") -> str:
    """Read a UTF-8 text file from a GitHub repository without modifying it."""
    import base64
    suffix = f"?ref={quote(ref)}" if ref else ""
    data = _request(f"/repos/{quote(owner)}/{quote(repo)}/contents/{quote(path)}{suffix}")
    if not isinstance(data, dict) or data.get("type") != "file":
        raise ValueError("Path is not a file.")
    content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
    return content[:120000]
