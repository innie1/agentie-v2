import json

from agents import function_tool

from agentie.core.collection_store import build_rag_context, create_collection, index_file, list_collections, search_collection


@function_tool
def collection_create(name: str, description: str = "") -> str:
    """Create or reuse a local document collection."""
    item, created = create_collection(name, description)
    return json.dumps({"created": created, "collection": item}, ensure_ascii=False)


@function_tool
def collection_list() -> str:
    """List local Agentie document collections."""
    return json.dumps({"collections": list_collections()}, ensure_ascii=False)


@function_tool
def collection_index_file(collection: str, filename: str) -> str:
    """Index an uploaded workspace file into a local document collection."""
    return json.dumps(index_file(collection, filename), ensure_ascii=False)


@function_tool
def collection_search(collection: str, query: str, limit: int = 6) -> str:
    """Retrieve relevant passages from a local document collection."""
    return json.dumps(search_collection(collection, query, limit), ensure_ascii=False)


@function_tool
def collection_context(collection: str, query: str, limit: int = 6) -> str:
    """Return a grounded context pack from a local collection for answering a question."""
    return build_rag_context(collection, query, limit)
