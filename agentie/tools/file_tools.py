from pathlib import Path

from agents import function_tool


WORKSPACE_DIR = Path.cwd() / "workspace"


@function_tool
def write_text_file(filename: str, content: str) -> str:
    """Write UTF-8 text content to a file inside Agentie's local workspace folder.

    The filename must be a simple filename such as `research.txt` or `notes.md`.
    Parent directories and absolute paths are intentionally not allowed.
    """
    safe_name = Path(filename).name.strip()
    if not safe_name or safe_name in {".", ".."}:
        raise ValueError("A valid filename is required.")

    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    target = WORKSPACE_DIR / safe_name
    target.write_text(content, encoding="utf-8")
    return f"Saved file successfully: {target}"
