import json

from agents import function_tool

from agentie.core.memory_store import get_memory, list_memories as list_memory_rows, search_memories, set_memory


@function_tool
def remember(key: str, value: str) -> str:
    """Save a useful non-sensitive user preference, goal, decision, or durable fact."""
    set_memory("user", key[:120], value[:4000], {"source": "agent_tool", "pinned": True})
    return f"Remembered: {key[:120]}"


@function_tool
def recall_memory(key: str) -> str:
    """Recall a saved memory by exact key, falling back to semantic retrieval."""
    exact = get_memory("user", key)
    if exact is not None:
        return exact
    result = search_memories(key, scope="user", limit=5)
    hits = result.get("hits", [])
    if not hits:
        return "No relevant memory found."
    return json.dumps({"query": key, "backend": result.get("backend"), "matches": hits}, ensure_ascii=False)


@function_tool
def search_memory(query: str, limit: int = 6) -> str:
    """Semantically search persistent user memories and relevant conversation history."""
    return json.dumps(search_memories(query, scope="user", limit=limit), ensure_ascii=False)


@function_tool
def list_memories() -> str:
    """List saved persistent user memories."""
    rows = list_memory_rows("user", 100)
    if not rows:
        return "No saved memories."
    return json.dumps([{"key": r["key"], "value": r["value"], "updated_at": r["updated_at"]} for r in rows], ensure_ascii=False)
