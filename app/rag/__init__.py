"""RAG: build and query the CVE/CWE knowledge base (a local Chroma vector store)."""

from app.rag.knowledge_base import (
    build_knowledge_base,
    ensure_embedding_model,
    get_collection,
)

__all__ = ["build_knowledge_base", "ensure_embedding_model", "get_collection"]
