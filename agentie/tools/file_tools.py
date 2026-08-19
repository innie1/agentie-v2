from pathlib import Path

from agents import function_tool


WORKSPACE_DIR = Path.cwd() / "workspace"
MAX_READ_CHARS = 20000


def _safe_workspace_path(filename: str) -> Path:
    safe_name = Path(filename).name.strip()
    if not safe_name or safe_name in {".", ".."}:
        raise ValueError("A valid filename is required.")
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    return WORKSPACE_DIR / safe_name


@function_tool
def write_text_file(filename: str, content: str) -> str:
    """Write UTF-8 text content to a file inside Agentie's local workspace folder."""
    target = _safe_workspace_path(filename)
    target.write_text(content, encoding="utf-8")
    return f"Saved file successfully: {target}"


@function_tool
def read_text_file(filename: str) -> str:
    """Read a UTF-8 text file from Agentie's local workspace folder."""
    target = _safe_workspace_path(filename)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"File not found: {target.name}")
    content = target.read_text(encoding="utf-8")
    if len(content) > MAX_READ_CHARS:
        return content[:MAX_READ_CHARS] + "\n\n[truncated]"
    return content


@function_tool
def list_workspace_files() -> str:
    """List files currently available in Agentie's local workspace folder."""
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(path.name for path in WORKSPACE_DIR.iterdir() if path.is_file())
    if not files:
        return "Workspace is empty."
    return "\n".join(files)


@function_tool
def edit_text_file(filename: str, old_text: str, new_text: str) -> str:
    """Replace one exact block of text inside an existing workspace text file.

    This is intentionally narrow: the old text must exist exactly once so edits
    are predictable and do not accidentally modify multiple sections.
    """
    target = _safe_workspace_path(filename)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"File not found: {target.name}")

    content = target.read_text(encoding="utf-8")
    occurrences = content.count(old_text)
    if occurrences == 0:
        raise ValueError("The requested old_text was not found in the file.")
    if occurrences > 1:
        raise ValueError("old_text appears more than once; provide a more specific block.")

    updated = content.replace(old_text, new_text, 1)
    target.write_text(updated, encoding="utf-8")
    return f"Edited file successfully: {target}"
