"""Tools the triage agent can call, and a tiny abstraction describing them.

A "tool" is a plain Python function plus a JSON-Schema description of its arguments.
The description is what we advertise to the model; the function is what *we* run when
the model asks for it. ``lookup_cve`` now retrieves real reference data from the RAG
knowledge base (Chroma) -- the agent loop and the tool's schema are unchanged from
when it was a stub, which is exactly the point of the seam.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Tool:
    """A callable the model may invoke, plus the schema we advertise to it."""

    name: str
    description: str
    parameters: dict  # JSON Schema for the arguments object
    func: Callable[..., str]

    def to_openai(self) -> dict:
        """Render the tool in the OpenAI/Groq ``tools`` format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# Open the knowledge-base collection lazily and cache it, so importing this module
# doesn't require a built KB and we don't reopen the store on every tool call.
_collection = None


def _kb_collection():
    global _collection
    if _collection is None:
        from app.rag import get_collection

        _collection = get_collection()
    return _collection


def lookup_cve(cve_id: str) -> str:
    """Retrieve reference details for a CVE (or CWE) id from the knowledge base.

    Returns the exact entry for ``cve_id`` if present, plus the most semantically
    related entries (e.g. the relevant CWE), giving the agent real data to ground its
    judgment. Reads from the RAG store; the model never sees the retrieval machinery.
    """
    try:
        col = _kb_collection()
    except Exception as exc:  # e.g. the KB hasn't been built yet
        return f"Knowledge base unavailable ({exc}). Build it with build_knowledge_base()."

    exact = col.get(ids=[cve_id], include=["documents"])
    sections: list[str] = []
    if exact["ids"]:
        sections.append(f"{cve_id}: {exact['documents'][0]}")
        query_text = exact["documents"][0]
    else:
        sections.append(f"No exact entry for {cve_id} in the knowledge base.")
        query_text = cve_id

    # Semantic search for related references (relevant CWEs, similar CVEs).
    related = col.query(query_texts=[query_text], n_results=3, include=["documents"])
    related_lines = [
        f"- {rid}: {related['documents'][0][i]}"
        for i, rid in enumerate(related["ids"][0])
        if rid != cve_id
    ][:2]
    if related_lines:
        sections.append("Related references:\n" + "\n".join(related_lines))

    return "\n\n".join(sections)


LOOKUP_CVE_TOOL = Tool(
    name="lookup_cve",
    description=(
        "Look up authoritative reference details (description, CVSS score, affected "
        "versions, and the fixed version) for a specific CVE id. Call this before "
        "judging any finding that has a CVE id, rather than relying on memory."
    ),
    parameters={
        "type": "object",
        "properties": {
            "cve_id": {
                "type": "string",
                "description": "The CVE identifier, e.g. CVE-2021-44228.",
            }
        },
        "required": ["cve_id"],
    },
    func=lookup_cve,
)

# Name -> Tool registry the loop dispatches through.
TOOLS: dict[str, Tool] = {LOOKUP_CVE_TOOL.name: LOOKUP_CVE_TOOL}
