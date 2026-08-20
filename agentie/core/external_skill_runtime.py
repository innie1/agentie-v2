from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

WORKSPACE = Path.cwd() / "workspace"
EXTERNAL_SKILLS = WORKSPACE / "external_skills"
LAST30_REPO = "https://github.com/mvanhorn/last30days-skill.git"
LAST30_ROOT = EXTERNAL_SKILLS / "last30days-skill"
LAST30_SCRIPT = LAST30_ROOT / "skills" / "last30days" / "scripts" / "last30days.py"


def _python312() -> list[str] | None:
    candidates = [["py", "-3.12"], ["python3.12"], ["python3"], ["python"]]
    for cmd in candidates:
        if not shutil.which(cmd[0]):
            continue
        try:
            proc = subprocess.run([*cmd, "-c", "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')"], capture_output=True, text=True, timeout=8)
            if proc.returncode == 0 and proc.stdout.strip().startswith("3.12"):
                return cmd
        except Exception:
            continue
    return None


def last30days_status() -> dict[str, Any]:
    py = _python312(); installed = LAST30_SCRIPT.exists()
    return {
        "id": "last30days",
        "installed": installed,
        "ready": bool(installed and py),
        "repo": LAST30_REPO,
        "script": str(LAST30_SCRIPT),
        "python": " ".join(py) if py else None,
        "requires": ["git", "Python 3.12+", "Node.js"],
        "optional_env": ["SCRAPECREATORS_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "OPENROUTER_API_KEY", "PERPLEXITY_API_KEY", "PARALLEL_API_KEY", "BRAVE_API_KEY", "APIFY_API_TOKEN"],
        "error": None if installed and py else ("Not installed." if not installed else "Python 3.12+ was not found."),
    }


def install_last30days(update: bool = False) -> dict[str, Any]:
    if not shutil.which("git"):
        raise RuntimeError("Git is required to install Last30Days.")
    EXTERNAL_SKILLS.mkdir(parents=True, exist_ok=True)
    if LAST30_ROOT.exists():
        if update:
            proc = subprocess.run(["git", "-C", str(LAST30_ROOT), "pull", "--ff-only"], capture_output=True, text=True, timeout=120)
            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or proc.stdout or "Could not update Last30Days.")[-1200:])
    else:
        proc = subprocess.run(["git", "clone", "--depth", "1", LAST30_REPO, str(LAST30_ROOT)], capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "Could not install Last30Days.")[-1200:])
    return last30days_status()


def _topic_from_message(message: str) -> str | None:
    text = str(message or "").strip()
    m = re.match(r"^/?last30days(?:\s+(?:about|on|for))?\s+(.+)$", text, re.I)
    if m: return m.group(1).strip()
    m = re.match(r"^(?:research|find|show me|tell me)\s+(?:what people (?:are saying|say)|the last 30 days)\s+(?:about|on|for)\s+(.+)$", text, re.I)
    return m.group(1).strip() if m else None


def route_last30days(message: str) -> dict[str, Any] | None:
    low = str(message or "").lower().strip()
    if low in {"install last30days", "install last30days skill", "add last30days skill"}:
        try: status = install_last30days(False)
        except Exception as exc: return {"message": f"Last30Days installation failed: {exc}", "card": {"type":"skill_runtime","skill":"last30days","status":last30days_status()}}
        message = "Last30Days is installed and ready." if status["ready"] else "Last30Days is installed, but Python 3.12+ is still required before it can run."
        return {"message": message, "card": {"type":"skill_runtime","skill":"last30days","status":status}}
    if low in {"update last30days", "update last30days skill"}:
        try: status = install_last30days(True)
        except Exception as exc: return {"message": f"Last30Days update failed: {exc}", "card": {"type":"skill_runtime","skill":"last30days","status":last30days_status()}}
        return {"message":"Updated Last30Days.","card":{"type":"skill_runtime","skill":"last30days","status":status}}
    if low in {"last30days status", "show last30days status", "check last30days"}:
        status=last30days_status(); return {"message":"Last30Days is ready." if status["ready"] else f"Last30Days is not ready: {status['error']}","card":{"type":"skill_runtime","skill":"last30days","status":status}}
    topic = _topic_from_message(message)
    if not topic: return None
    status = last30days_status()
    if not status["installed"]:
        return {"message":"Last30Days is not installed yet. Install the skill first.","card":{"type":"skill_runtime","skill":"last30days","status":status,"install_command":"Install Last30Days skill"}}
    if not status["ready"]:
        return {"message":"Last30Days is installed but cannot run until Python 3.12+ is available.","card":{"type":"skill_runtime","skill":"last30days","status":status}}
    py = _python312()
    try:
        proc = subprocess.run([*py, str(LAST30_SCRIPT), topic, "--emit=compact"], cwd=str(LAST30_SCRIPT.parent), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240, env=os.environ.copy())
    except subprocess.TimeoutExpired:
        return {"message":"Last30Days research timed out after four minutes.","card":{"type":"skill_runtime","skill":"last30days","status":status}}
    if proc.returncode != 0:
        err=(proc.stderr or proc.stdout or "Last30Days failed.")[-1800:]
        return {"message":f"Last30Days could not complete the research: {err}","card":{"type":"skill_runtime","skill":"last30days","status":last30days_status()}}
    output=proc.stdout.strip()
    return {"message":output or "Last30Days completed without text output.","card":{"type":"skill_runtime","skill":"last30days","status":last30days_status(),"topic":topic}}
