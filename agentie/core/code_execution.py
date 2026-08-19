from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from agentie.core.file_service import UPLOADS, ensure_dirs, inspect_file, unique_path
from agentie.core.observability import record_event

WORKSPACE = Path.cwd() / "workspace"
RUNS = WORKSPACE / "code_runs"
MAX_CODE_CHARS = 20_000
MAX_CAPTURE_CHARS = 12_000
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 10

_BLOCKED_IMPORT_ROOTS = {
    "os", "sys", "subprocess", "socket", "http", "urllib", "requests", "httpx",
    "pathlib", "shutil", "glob", "tempfile", "importlib", "ctypes", "multiprocessing",
    "threading", "asyncio", "signal", "resource", "winreg", "webbrowser", "ftplib",
    "telnetlib", "smtplib", "pickle", "shelve",
}
_ALLOWED_IMPORT_ROOTS = {
    "math", "statistics", "decimal", "fractions", "random", "re", "json", "csv",
    "datetime", "collections", "itertools", "functools", "operator", "string",
}
_BLOCKED_CALLS = {
    "open", "exec", "eval", "compile", "__import__", "input", "breakpoint",
    "getattr", "setattr", "delattr", "vars", "globals", "locals",
}


def _timeout_seconds() -> int:
    try:
        return max(1, min(int(os.getenv("AGENTIE_CODE_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))), 30))
    except Exception:
        return DEFAULT_TIMEOUT_SECONDS


def _validate_code(code: str) -> None:
    if not code.strip():
        raise ValueError("No Python code was provided.")
    if len(code) > MAX_CODE_CHARS:
        raise ValueError(f"Python code is limited to {MAX_CODE_CHARS:,} characters per run.")
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise ValueError(f"Python syntax error on line {exc.lineno}: {exc.msg}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in _BLOCKED_IMPORT_ROOTS or root not in _ALLOWED_IMPORT_ROOTS:
                    raise ValueError(f"Import '{alias.name}' is not allowed in local code execution.")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root in _BLOCKED_IMPORT_ROOTS or root not in _ALLOWED_IMPORT_ROOTS:
                raise ValueError(f"Import from '{node.module}' is not allowed in local code execution.")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _BLOCKED_CALLS:
            raise ValueError(f"Call '{node.func.id}(...)' is not allowed in local code execution.")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError("Dunder attribute access is not allowed in local code execution.")
        elif isinstance(node, ast.Name) and node.id in {"__builtins__", "__loader__", "__spec__"}:
            raise ValueError(f"Name '{node.id}' is not allowed in local code execution.")


def _extract_code(message: str) -> str | None:
    text = str(message or "").strip()
    fenced = re.search(r"```(?:python|py)?\s*\n?(.*?)```", text, re.I | re.S)
    if fenced:
        prefix = text[: fenced.start()].lower()
        if re.search(r"\b(?:run|execute|python|code)\b", prefix) or prefix.strip() == "":
            return fenced.group(1).strip()
    patterns = [
        r"^(?:please\s+)?(?:run|execute)\s+(?:this\s+)?(?:python\s+)?(?:code\s*)?:\s*(.+)$",
        r"^(?:please\s+)?python\s*:\s*(.+)$",
        r"^(?:please\s+)?run\s+python\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, re.I | re.S)
        if match:
            return match.group(1).strip()
    return None


def _bootstrap(user_code: str) -> str:
    return f'''import json as _json\nfrom pathlib import Path as _Path\n\n_RUN_DIR = _Path.cwd().resolve()\n_UPLOADS = _Path({str(UPLOADS.resolve())!r})\n\ndef _safe_basename(name):\n    value = _Path(str(name)).name\n    if not value or value in {{'.', '..'}}:\n        raise ValueError('A simple filename is required.')\n    return value[:180]\n\ndef read_text(name, max_chars=100000):\n    path = (_UPLOADS / _safe_basename(name)).resolve()\n    if path.parent != _UPLOADS.resolve() or not path.is_file():\n        raise FileNotFoundError(_safe_basename(name))\n    return path.read_text(encoding='utf-8', errors='replace')[:int(max_chars)]\n\ndef read_json(name):\n    return _json.loads(read_text(name))\n\ndef write_text(name, content):\n    path = (_RUN_DIR / _safe_basename(name)).resolve()\n    if path.parent != _RUN_DIR:\n        raise ValueError('Invalid output path.')\n    path.write_text(str(content), encoding='utf-8')\n    return path.name\n\ndef write_json(name, value):\n    return write_text(name, _json.dumps(value, indent=2, ensure_ascii=False))\n\n# ----- user code -----\n{user_code}\n'''


def _publish_artifacts(run_dir: Path, script_name: str) -> list[dict[str, Any]]:
    ensure_dirs()
    artifacts: list[dict[str, Any]] = []
    for path in sorted(run_dir.iterdir()):
        if not path.is_file() or path.name == script_name:
            continue
        try:
            size = path.stat().st_size
            if size <= 0 or size > MAX_ARTIFACT_BYTES:
                continue
            destination = unique_path(path.name)
            destination.write_bytes(path.read_bytes())
            card = inspect_file(destination)
            card["download_url"] = f"/files/{destination.name}/download"
            artifacts.append(card)
        except Exception:
            continue
    return artifacts[:12]


def execute_python(code: str) -> dict[str, Any]:
    _validate_code(code)
    RUNS.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:10]
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    script_name = "run.py"
    (run_dir / script_name).write_text(_bootstrap(code), encoding="utf-8")
    timeout = _timeout_seconds()
    env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "WINDIR": os.environ.get("WINDIR", ""),
    }
    started = time.perf_counter()
    timed_out = False
    try:
        completed = subprocess.run(
            [sys.executable, "-I", script_name],
            cwd=str(run_dir),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
        exit_code = int(completed.returncode)
        stdout = (completed.stdout or "")[:MAX_CAPTURE_CHARS]
        stderr = (completed.stderr or "")[:MAX_CAPTURE_CHARS]
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
        stdout = ((exc.stdout or "") if isinstance(exc.stdout, str) else "")[:MAX_CAPTURE_CHARS]
        stderr = f"Execution stopped after {timeout} seconds."
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    artifacts = _publish_artifacts(run_dir, script_name)
    status = "timed_out" if timed_out else ("completed" if exit_code == 0 else "failed")
    record_event(
        "code_execution",
        "python",
        status="ok" if status == "completed" else "error",
        metadata={"run_id": run_id, "status": status, "duration_ms": duration_ms, "exit_code": exit_code, "artifacts": len(artifacts)},
    )
    return {
        "run_id": run_id,
        "status": status,
        "language": "python",
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "timeout_seconds": timeout,
        "artifacts": artifacts,
    }


def route_code_command(message: str) -> dict[str, Any] | None:
    code = _extract_code(message)
    if code is None:
        return None
    try:
        result = execute_python(code)
    except ValueError as exc:
        return {"message": str(exc), "card": None}
    except Exception:
        return {"message": "Local Python execution could not start. Check the trace for details.", "card": None}

    status = result["status"]
    if status == "completed":
        message = f"Python completed locally in {result['duration_ms']:.0f} ms."
    elif status == "timed_out":
        message = f"Python was stopped after the {result['timeout_seconds']}-second execution limit."
    else:
        message = f"Python exited with code {result['exit_code']}."

    output_text = result["stdout"].strip()
    error_text = result["stderr"].strip()
    sections = []
    if output_text:
        sections.append("Output\n" + output_text)
    if error_text:
        sections.append("Error\n" + error_text)
    if not sections:
        sections.append("Execution finished without console output.")

    items: list[dict[str, Any]] = [{
        "message": message,
        "card": {
            "type": "note",
            "title": f"Python · {status} · {result['duration_ms']:.0f} ms · exit {result['exit_code']}",
            "content": "\n\n".join(sections),
        },
    }]
    for artifact in result["artifacts"]:
        items.append({"message": f"Created {artifact['name']}.", "card": artifact})

    return {"message": message, "card": {"type": "multi", "items": items}}
