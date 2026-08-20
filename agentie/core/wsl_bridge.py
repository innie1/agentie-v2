from __future__ import annotations

import base64
import re
from pathlib import PurePosixPath
from typing import Any

from agentie.core.wsl_desktop import _run_wsl

LINUX_WORKSPACE = "$HOME/AgentieWorkspace"
MAX_OUTPUT_CHARS = 50_000
MAX_FILE_CHARS = 200_000

_DANGEROUS_PATTERNS = (
    r"(^|[;&|]\s*)sudo\b",
    r"(^|[;&|]\s*)su\b",
    r"\brm\s+-[^\n]*r[^\n]*f\b",
    r"\bmkfs(?:\.|\s)",
    r"\bdd\s+if=",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bpoweroff\b",
    r"\bhalt\b",
    r"\bmount\b",
    r"\bumount\b",
    r"\bchown\b",
    r"\bchmod\s+-R\b",
    r"\buserdel\b",
    r"\bgroupdel\b",
    r"\bpasswd\b",
    r">\s*/(?:etc|usr|bin|sbin|boot|proc|sys|dev)/",
)


def _validate_shell(command: str) -> str:
    raw = str(command or "").strip()
    if not raw:
        return ""
    if len(raw) > 4_000:
        raise ValueError("Linux terminal command is too long.")
    for pattern in _DANGEROUS_PATTERNS:
        if re.search(pattern, raw, re.I):
            raise ValueError(
                "That command can make destructive or system-level changes, so Agentie will not run it automatically. "
                "Use the visible Linux Terminal for this action."
            )
    return raw


def _safe_relative_path(path: str) -> str:
    value = str(path or "").strip().strip('"\'')
    value = value.replace("\\", "/")
    posix = PurePosixPath(value)
    if posix.is_absolute() or ".." in posix.parts:
        raise ValueError("Linux file paths must stay inside AgentieWorkspace.")
    cleaned = str(posix).strip("./")
    if not cleaned or cleaned == ".":
        raise ValueError("A file or folder path is required.")
    return cleaned[:240]


def _encode(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def run_terminal(command: str, timeout: int = 25) -> dict[str, Any]:
    raw = _validate_shell(command)
    if not raw:
        return {"command": "", "output": "", "exit_code": 0, "workspace": "~/AgentieWorkspace"}
    payload = _encode(raw)
    script = f'''set +e
mkdir -p {LINUX_WORKSPACE}
cd {LINUX_WORKSPACE}
command="$(printf '%s' '{payload}' | base64 -d)"
bash -lc "$command"
exit $?
'''
    try:
        proc = _run_wsl(script, timeout=max(1, min(int(timeout), 60)))
    except Exception as exc:
        raise RuntimeError(f"Could not run the Linux command: {exc}") from exc
    output = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
    return {
        "command": raw,
        "output": output[:MAX_OUTPUT_CHARS],
        "exit_code": int(proc.returncode),
        "workspace": "~/AgentieWorkspace",
    }


def list_files(path: str = "") -> dict[str, Any]:
    relative = "" if not str(path or "").strip() else _safe_relative_path(path)
    encoded = _encode(relative)
    script = f'''set -eu
mkdir -p {LINUX_WORKSPACE}
cd {LINUX_WORKSPACE}
rel="$(printf '%s' '{encoded}' | base64 -d)"
target="."
[ -n "$rel" ] && target="$rel"
[ -e "$target" ] || {{ echo "__NOT_FOUND__"; exit 44; }}
if [ -f "$target" ]; then
  printf 'FILE\t%s\t%s\n' "$(basename "$target")" "$(wc -c < "$target")"
else
  find "$target" -mindepth 1 -maxdepth 1 -printf '%y\t%f\t%s\n' | sort -f
fi
'''
    proc = _run_wsl(script, timeout=15)
    if proc.returncode == 44:
        raise FileNotFoundError(relative or ".")
    if proc.returncode != 0:
        raise RuntimeError(((proc.stderr or proc.stdout or "Linux file listing failed.").strip())[-1200:])
    items: list[dict[str, Any]] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        kind_raw, name, size_raw = parts[0], parts[1], parts[2]
        kind = "folder" if kind_raw == "d" else "file"
        try:
            size = int(size_raw)
        except Exception:
            size = 0
        items.append({"name": name, "kind": kind, "size_bytes": 0 if kind == "folder" else size})
    return {"path": relative or ".", "workspace": "~/AgentieWorkspace", "items": items}


def read_text_file(path: str) -> dict[str, Any]:
    relative = _safe_relative_path(path)
    encoded = _encode(relative)
    script = f'''set -eu
mkdir -p {LINUX_WORKSPACE}
cd {LINUX_WORKSPACE}
rel="$(printf '%s' '{encoded}' | base64 -d)"
[ -f "$rel" ] || {{ echo "__NOT_FOUND__"; exit 44; }}
python3 - "$rel" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
data=p.read_bytes()
if b'\\x00' in data[:4096]:
    print('__BINARY__')
else:
    print(data.decode('utf-8', errors='replace')[:{MAX_FILE_CHARS}], end='')
PY
'''
    proc = _run_wsl(script, timeout=15)
    text = proc.stdout or ""
    if proc.returncode == 44 or text.strip() == "__NOT_FOUND__":
        raise FileNotFoundError(relative)
    if proc.returncode != 0:
        raise RuntimeError(((proc.stderr or text or "Linux file read failed.").strip())[-1200:])
    if text.strip() == "__BINARY__":
        return {"path": relative, "binary": True, "content": None, "workspace": "~/AgentieWorkspace"}
    return {"path": relative, "binary": False, "content": text[:MAX_FILE_CHARS], "workspace": "~/AgentieWorkspace"}


def write_text_file(path: str, content: str) -> dict[str, Any]:
    relative = _safe_relative_path(path)
    if len(str(content)) > MAX_FILE_CHARS:
        raise ValueError(f"Linux text writes are limited to {MAX_FILE_CHARS:,} characters.")
    path64 = _encode(relative)
    content64 = _encode(str(content))
    script = f'''set -eu
mkdir -p {LINUX_WORKSPACE}
cd {LINUX_WORKSPACE}
rel="$(printf '%s' '{path64}' | base64 -d)"
mkdir -p "$(dirname "$rel")"
printf '%s' '{content64}' | base64 -d > "$rel"
wc -c < "$rel"
'''
    proc = _run_wsl(script, timeout=15)
    if proc.returncode != 0:
        raise RuntimeError(((proc.stderr or proc.stdout or "Linux file write failed.").strip())[-1200:])
    try:
        size = int((proc.stdout or "0").strip().splitlines()[-1])
    except Exception:
        size = len(str(content).encode("utf-8"))
    return {"path": relative, "size_bytes": size, "workspace": "~/AgentieWorkspace"}
