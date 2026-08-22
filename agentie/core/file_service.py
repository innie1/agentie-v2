import csv
import hashlib
import io
import json
import mimetypes
import shutil
import zipfile
from pathlib import Path
from typing import Any

import yaml
from PIL import Image
from pypdf import PdfReader

WORKSPACE = Path.cwd() / "workspace"
UPLOADS = WORKSPACE / "uploads"
EXTRACTED = WORKSPACE / "extracted"
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TEXT_CHARS = 40_000


def ensure_dirs() -> None:
    UPLOADS.mkdir(parents=True, exist_ok=True)
    EXTRACTED.mkdir(parents=True, exist_ok=True)


def safe_name(name: str) -> str:
    cleaned = Path(name or "upload.bin").name.replace("\x00", "").strip()
    return cleaned[:180] or "upload.bin"


def unique_path(name: str) -> Path:
    ensure_dirs();path = UPLOADS / safe_name(name)
    if not path.exists():return path
    stem, suffix = path.stem, path.suffix;index = 2
    while True:
        candidate = UPLOADS / f"{stem}-{index}{suffix}"
        if not candidate.exists():return candidate
        index += 1


def resolve_upload(name: str) -> Path:
    ensure_dirs();target = (UPLOADS / safe_name(name)).resolve();root = UPLOADS.resolve()
    if target.parent != root:raise ValueError("Invalid file path")
    if not target.exists() or not target.is_file():raise FileNotFoundError(name)
    return target


def _base_card(path: Path) -> dict[str, Any]:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return {"type": "uploaded_file","name": path.name,"size_bytes": path.stat().st_size,"suffix": path.suffix.lower(),"mime_type": mime}


def inspect_file(path: Path) -> dict[str, Any]:
    card = _base_card(path);suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            reader = PdfReader(str(path));card.update({"kind": "pdf", "pages": len(reader.pages)})
        elif suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                files = [i for i in archive.infolist() if not i.is_dir()];card.update({"kind": "zip", "entries": len(files),"uncompressed_bytes": sum(i.file_size for i in files),"preview": [i.filename for i in files[:8]]})
        elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
            with Image.open(path) as image:card.update({"kind": "image", "width": image.width, "height": image.height, "format": image.format, "mode": image.mode})
        elif suffix == ".csv":
            with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                reader = csv.reader(handle);rows = []
                for _, row in zip(range(6), reader): rows.append(row)
            card.update({"kind": "csv", "columns": len(rows[0]) if rows else 0, "preview_rows": rows})
        elif suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"));card.update({"kind": "json", "root_type": type(data).__name__, "items": len(data) if isinstance(data, (dict, list)) else None})
        elif suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(path.read_text(encoding="utf-8"));card.update({"kind": "yaml", "root_type": type(data).__name__, "items": len(data) if isinstance(data, (dict, list)) else None})
        elif suffix in {".txt", ".md", ".py", ".js", ".html", ".css", ".toml", ".ini", ".log"}:card.update({"kind": "text"})
        else:card.update({"kind": "file"})
    except Exception as exc:card["inspection_error"] = str(exc)
    return card


def save_upload(filename: str, content: bytes) -> dict[str, Any]:
    if len(content) > MAX_FILE_BYTES:raise ValueError("File is larger than the 50 MB local upload limit.")
    path = unique_path(filename);path.write_bytes(content);card=inspect_file(path)
    try:
        from agentie.core.external_triggers import publish_external_event
        digest=hashlib.sha256(content).hexdigest();publish_external_event("file.uploaded",{"name":card.get("name"),"size_bytes":card.get("size_bytes"),"suffix":card.get("suffix"),"mime_type":card.get("mime_type"),"kind":card.get("kind"),"sha256":digest},source="file_service",external_id=f"{card.get('name')}:{digest}")
    except Exception:pass
    return card


def checksum(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):digest.update(chunk)
    return {"type": "checksum", "filename": path.name, "algorithm": "sha256", "checksum": digest.hexdigest()}


def extract_zip(path: Path) -> dict[str, Any]:
    if path.suffix.lower() != ".zip": raise ValueError("That file is not a ZIP archive.")
    destination = EXTRACTED / path.stem
    if destination.exists(): shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True);extracted = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir(): continue
            member = Path(info.filename)
            if member.is_absolute() or ".." in member.parts: continue
            target = (destination / member).resolve()
            if destination.resolve() not in target.parents: continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, target.open("wb") as dst: shutil.copyfileobj(src, dst)
            extracted.append(str(member))
            if len(extracted) >= 500: break
    return {"type": "zip_extract", "filename": path.name, "destination": str(destination.relative_to(WORKSPACE)), "files": extracted, "count": len(extracted)}


def extract_text(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower();text = "";metadata: dict[str, Any] = {}
    if suffix == ".pdf":
        reader = PdfReader(str(path)); metadata["pages"] = len(reader.pages);chunks = []
        for page in reader.pages[:100]:
            chunks.append(page.extract_text() or "")
            if sum(len(c) for c in chunks) >= MAX_TEXT_CHARS: break
        text = "\n\n".join(chunks)
    elif suffix == ".csv":text = path.read_text(encoding="utf-8-sig", errors="replace")
    elif suffix in {".json", ".yaml", ".yml", ".txt", ".md", ".py", ".js", ".html", ".css", ".toml", ".ini", ".log"}:text = path.read_text(encoding="utf-8", errors="replace")
    else:raise ValueError("Text extraction is not available for this file type.")
    truncated = len(text) > MAX_TEXT_CHARS
    return {"type": "file_text", "filename": path.name, "text": text[:MAX_TEXT_CHARS], "truncated": truncated, **metadata}


def preview_data(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.reader(handle); rows = []
            for _, row in zip(range(21), reader): rows.append(row)
        return {"type": "data_preview", "filename": path.name, "format": "csv", "rows": rows}
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"));return {"type": "data_preview", "filename": path.name, "format": "json", "text": json.dumps(data, indent=2, ensure_ascii=False)[:MAX_TEXT_CHARS]}
    if suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(path.read_text(encoding="utf-8"));return {"type": "data_preview", "filename": path.name, "format": "yaml", "text": yaml.safe_dump(data, sort_keys=False, allow_unicode=True)[:MAX_TEXT_CHARS]}
    raise ValueError("Preview is only available for CSV, JSON, and YAML files.")


def run_action(name: str, action: str) -> tuple[str, dict[str, Any]]:
    path = resolve_upload(name)
    if action == "inspect": return f"Here’s {path.name}.", inspect_file(path)
    if action == "checksum": return f"SHA-256 calculated for {path.name}.", checksum(path)
    if action == "extract": return f"Extracted {path.name}.", extract_zip(path)
    if action == "text": return f"Extracted text from {path.name}.", extract_text(path)
    if action == "preview": return f"Here’s a preview of {path.name}.", preview_data(path)
    raise ValueError("Unknown file action")
