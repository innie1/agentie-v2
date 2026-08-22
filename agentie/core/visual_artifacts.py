from __future__ import annotations

import html
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from agentie.core.artifact_naming import artifact_filename, creator_from_session
from agentie.core.file_service import UPLOADS, inspect_file, unique_path
from agentie.core.memory_store import latest_assistant_text

_VISUAL_RE = re.compile(
    r"\b(?:create|make|generate|draw|design|render|turn|convert)\b.*\b(?:flowchart|diagram|architecture diagram|process diagram|mind map|motion graphic|motion graphics|animated diagram|animation)\b"
    r"|\b(?:flowchart|diagram|architecture diagram|process diagram|mind map|motion graphic|motion graphics|animated diagram|animation)\b.*\b(?:create|make|generate|draw|design|render|turn|convert)\b",
    re.I,
)
_REFERENCE_RE = re.compile(r"\b(?:this|that|it|the previous answer|previous answer|last answer|above|what you just wrote|what you wrote)\b", re.I)
_MOTION_RE = re.compile(r"\b(?:motion graphic|motion graphics|animated|animation|animate)\b", re.I)


def _clean_label(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n-–—>|:;,.\"'`")
    return text[:90]


def _extract_filename(message: str, suffix: str) -> str | None:
    match = re.search(rf"\b(?:called|named|as)\s+[\"']?([^\"']+?\{re.escape(suffix)})\b", message, re.I)
    return match.group(1).strip() if match else None


def _duration_seconds(message: str) -> float:
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:seconds?|secs?)\b", message, re.I)
    if not match:
        return 8.0
    return max(2.0, min(float(match.group(1)), 60.0))


def _title(message: str, source: str, animated: bool) -> str:
    explicit = re.search(r"\b(?:called|named|titled)\s+[\"']?(.+?)(?=[\"']?(?:\s+(?:showing|with|from|using)|\s*[:;]|$))", message, re.I)
    if explicit:
        value = _clean_label(explicit.group(1))
        if value:
            return value
    before = message.split(":", 1)[0]
    before = re.sub(r"^(?:please\s+)?(?:create|make|generate|draw|design|render|turn|convert)\s+(?:an?\s+)?", "", before, flags=re.I)
    before = re.sub(r"\b(?:flowchart|architecture diagram|process diagram|mind map|motion graphics?|animated diagram|animation|diagram)\b", "", before, flags=re.I)
    before = _clean_label(before)
    if 3 <= len(before) <= 70:
        return before.title()
    return "Animated Process" if animated else "Process Diagram"


def _source_text(session_id: str, message: str) -> str:
    text = str(message or "")
    if _REFERENCE_RE.search(text):
        previous = latest_assistant_text(session_id, max_chars=30000)
        if previous:
            return previous
    if ":" in text:
        return text.split(":", 1)[1].strip()
    match = re.search(r"\b(?:showing|with|using)\s+(.+)$", text, re.I | re.S)
    if match:
        return match.group(1).strip()
    match = re.search(r"\bsteps?\s+(?:are\s+)?(.+)$", text, re.I | re.S)
    if match:
        return match.group(1).strip()
    return text


def _parse_graph(source: str) -> tuple[list[str], list[tuple[str, str]]]:
    raw = str(source or "").replace("⇒", "->").replace("→", "->").replace("➜", "->").replace("=>", "->")
    nodes: list[str] = []
    edges: list[tuple[str, str]] = []

    def add_node(value: str) -> str:
        label = _clean_label(value)
        if label and label.casefold() not in {x.casefold() for x in nodes}:
            nodes.append(label)
        return next((x for x in nodes if x.casefold() == label.casefold()), label)

    segments = [x.strip() for x in re.split(r"[;\n]+", raw) if x.strip()]
    for segment in segments:
        if "->" not in segment:
            continue
        chain = [add_node(x) for x in segment.split("->") if _clean_label(x)]
        for left, right in zip(chain, chain[1:]):
            if left and right and (left, right) not in edges:
                edges.append((left, right))

    if len(nodes) < 2:
        items: list[str] = []
        for line in raw.splitlines():
            match = re.match(r"^\s*(?:[-*•]|\d+[.)])\s+(.+)$", line)
            if match:
                items.append(_clean_label(match.group(1)))
        if len(items) < 2:
            candidate = re.sub(r"^.*?\b(?:steps?|nodes?|stages?|process)\b\s*(?:are|:)?\s*", "", raw, flags=re.I | re.S)
            items = [_clean_label(x) for x in re.split(r"\s*,\s*|\s+then\s+|\s+and then\s+", candidate) if _clean_label(x)]
        if len(items) >= 2:
            nodes = []
            for item in items[:12]:
                add_node(item)
            edges = [(nodes[i], nodes[i + 1]) for i in range(len(nodes) - 1)]

    return nodes[:18], [(a, b) for a, b in edges if a in nodes and b in nodes][:30]


def _levels(nodes: list[str], edges: list[tuple[str, str]]) -> list[list[str]]:
    indegree = {node: 0 for node in nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for left, right in edges:
        outgoing[left].append(right)
        indegree[right] = indegree.get(right, 0) + 1
    queue = deque([node for node in nodes if indegree.get(node, 0) == 0])
    level = {node: 0 for node in queue}
    seen = 0
    while queue:
        node = queue.popleft();seen += 1
        for child in outgoing.get(node, []):
            level[child] = max(level.get(child, 0), level.get(node, 0) + 1)
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if seen != len(nodes):
        return [[node] for node in nodes]
    buckets: dict[int, list[str]] = defaultdict(list)
    for node in nodes:
        buckets[level.get(node, 0)].append(node)
    return [buckets[idx] for idx in sorted(buckets)]


def _wrap(label: str, width: int = 24) -> list[str]:
    words = label.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width or not current:
            current = candidate
        else:
            lines.append(current);current = word
    if current:
        lines.append(current)
    return lines[:3]


def _layout(nodes: list[str], edges: list[tuple[str, str]]) -> tuple[int, int, dict[str, tuple[float, float]]]:
    levels = _levels(nodes, edges)
    max_row = max((len(row) for row in levels), default=1)
    width = max(960, min(1680, 220 + max_row * 260))
    height = max(520, 170 + len(levels) * 160)
    positions: dict[str, tuple[float, float]] = {}
    for y_idx, row in enumerate(levels):
        gap = width / (len(row) + 1)
        for x_idx, node in enumerate(row, 1):
            positions[node] = (gap * x_idx, 150 + y_idx * 150)
    return width, height, positions


def _svg_document(title: str, creator: str, nodes: list[str], edges: list[tuple[str, str]], animated: bool = False, duration: float = 8.0) -> str:
    width, height, positions = _layout(nodes, edges)
    node_w, node_h = 210, 76
    title_e = html.escape(title)
    creator_e = html.escape(creator)
    edge_parts = []
    for idx, (left, right) in enumerate(edges):
        x1, y1 = positions[left];x2, y2 = positions[right]
        start_y = y1 + node_h / 2;end_y = y2 - node_h / 2
        delay = round((idx / max(1, len(edges) + len(nodes))) * duration * 0.7, 2)
        cls = 'edge animated-edge' if animated else 'edge'
        edge_parts.append(f'<path class="{cls}" style="--delay:{delay}s" d="M {x1:.1f} {start_y:.1f} C {x1:.1f} {(start_y+end_y)/2:.1f}, {x2:.1f} {(start_y+end_y)/2:.1f}, {x2:.1f} {end_y:.1f}" marker-end="url(#arrow)"/>')
    node_parts = []
    for idx, node in enumerate(nodes):
        x, y = positions[node];lines = _wrap(node);delay = round(((len(edges) + idx) / max(1, len(edges) + len(nodes))) * duration * 0.7, 2)
        cls = 'node animated-node' if animated else 'node'
        text_y = y - ((len(lines)-1) * 10)
        tspans = ''.join(f'<tspan x="{x:.1f}" dy="{0 if j == 0 else 20}">{html.escape(line)}</tspan>' for j, line in enumerate(lines))
        node_parts.append(f'<g class="{cls}" style="--delay:{delay}s"><rect x="{x-node_w/2:.1f}" y="{y-node_h/2:.1f}" width="{node_w}" height="{node_h}" rx="18"/><text x="{x:.1f}" y="{text_y:.1f}">{tspans}</text></g>')
    animation_css = ''
    if animated:
        animation_css = '''
        .animated-node{opacity:0;transform:translateY(14px);animation:nodeIn .55s cubic-bezier(.2,.8,.2,1) forwards;animation-delay:var(--delay)}
        .animated-edge{stroke-dasharray:900;stroke-dashoffset:900;animation:edgeIn .8s ease forwards;animation-delay:var(--delay)}
        @keyframes nodeIn{to{opacity:1;transform:translateY(0)}}
        @keyframes edgeIn{to{stroke-dashoffset:0}}
        '''
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="{title_e}">
    <defs><marker id="arrow" markerWidth="11" markerHeight="11" refX="9" refY="5.5" orient="auto"><path d="M0,0 L11,5.5 L0,11 Z" fill="#0B84FF"/></marker></defs>
    <style>
      .bg{{fill:#fff}} .edge{{fill:none;stroke:#0B84FF;stroke-width:3;opacity:.72}}
      .node rect{{fill:#fff;stroke:#0B84FF;stroke-width:2;filter:drop-shadow(0 8px 14px rgba(17,24,39,.08))}}
      .node text{{font:600 17px Arial,sans-serif;fill:#111827;text-anchor:middle;dominant-baseline:middle}}
      .title{{font:700 30px Arial,sans-serif;fill:#111827}} .meta{{font:14px Arial,sans-serif;fill:#6B7280}}
      {animation_css}
    </style>
    <rect class="bg" width="100%" height="100%"/>
    <text class="title" x="48" y="54">{title_e}</text>
    <text class="meta" x="48" y="82">Generated by {creator_e} · Agentie</text>
    {''.join(edge_parts)}
    {''.join(node_parts)}
    </svg>'''


def create_svg_diagram(title: str, nodes: list[str], edges: list[tuple[str, str]], filename: str | None = None, creator: str = "Agentie") -> dict[str, Any]:
    if len(nodes) < 2:
        raise ValueError("A diagram needs at least two nodes or steps.")
    UPLOADS.mkdir(parents=True, exist_ok=True)
    name = artifact_filename(creator, filename, ".svg", "diagram")
    path = unique_path(name)
    path.write_text(_svg_document(title, creator, nodes, edges), encoding="utf-8")
    card = inspect_file(path)
    card.update({"visual_kind":"diagram","creator":creator,"document_name":title,"nodes":len(nodes),"edges":len(edges),"animated":False})
    return card


def create_motion_graphic(title: str, nodes: list[str], edges: list[tuple[str, str]], filename: str | None = None, creator: str = "Agentie", duration: float = 8.0) -> dict[str, Any]:
    if len(nodes) < 2:
        raise ValueError("A motion graphic needs at least two nodes or steps.")
    UPLOADS.mkdir(parents=True, exist_ok=True)
    name = artifact_filename(creator, filename, ".html", "motion-graphic")
    path = unique_path(name)
    svg = _svg_document(title, creator, nodes, edges, animated=True, duration=duration)
    title_e = html.escape(title)
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title_e}</title><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#f7f8fa;color:#111827;font-family:Arial,sans-serif;display:grid;min-height:100vh;place-items:center;padding:24px}}
    .frame{{width:min(1200px,100%);background:#fff;border:1px solid #e5e7eb;border-radius:22px;box-shadow:0 20px 55px rgba(17,24,39,.12);overflow:hidden}}
    .stage{{overflow:auto}}svg{{width:100%;height:auto;display:block}}.bar{{height:4px;background:#e5e7eb;overflow:hidden}}.bar:after{{content:"";display:block;width:100%;height:100%;background:#0B84FF;transform-origin:left;animation:progress {duration:.2f}s linear forwards}}
    .controls{{padding:12px 16px;border-top:1px solid #eef0f3;display:flex;justify-content:flex-end}}button{{border:0;border-radius:10px;background:#0B84FF;color:#fff;padding:9px 14px;font-weight:650;cursor:pointer}}@keyframes progress{{from{{transform:scaleX(0)}}to{{transform:scaleX(1)}}}}
    </style></head><body><main class="frame" id="frame"><div class="bar"></div><div class="stage">{svg}</div><div class="controls"><button id="replay" type="button">Replay</button></div></main><script>
    document.getElementById('replay').addEventListener('click',()=>{{const old=document.getElementById('frame');const clone=old.cloneNode(true);old.replaceWith(clone);clone.querySelector('#replay').addEventListener('click',()=>location.reload())}});
    </script></body></html>'''
    path.write_text(document, encoding="utf-8")
    card = inspect_file(path)
    card.update({"visual_kind":"motion_graphic","creator":creator,"document_name":title,"nodes":len(nodes),"edges":len(edges),"animated":True,"duration_seconds":duration})
    return card


def try_visual_request(session_id: str, message: str) -> dict[str, Any] | None:
    text = " ".join(str(message or "").strip().split())
    if not _VISUAL_RE.search(text):
        return None
    try:
        from agentie.core.skill_registry import skill_enabled
        if not skill_enabled("visuals-motion"):
            return {"message":"The Visuals & Motion skill is disabled. Enable it first to create diagrams or motion graphics.","card":None}
    except Exception:
        pass
    animated = bool(_MOTION_RE.search(text))
    source = _source_text(session_id, message)
    nodes, edges = _parse_graph(source)
    if len(nodes) < 2:
        return {"message":"Tell me the diagram structure or steps, for example: `Lead -> Qualify -> Proposal -> Close`.","card":None,"needs_content":True}
    creator = creator_from_session(session_id)
    title = _title(message, source, animated)
    if animated:
        filename = _extract_filename(message, ".html")
        duration = _duration_seconds(message)
        card = create_motion_graphic(title, nodes, edges, filename, creator, duration)
        return {"message":f"Created an animated motion graphic with {len(nodes)} step(s).", "card":card}
    filename = _extract_filename(message, ".svg")
    card = create_svg_diagram(title, nodes, edges, filename, creator)
    return {"message":f"Created a diagram with {len(nodes)} node(s).", "card":card}
