"""Build and open the CVE/CWE knowledge base: a local Chroma vector store.

Two phases of RAG:
  - Indexing (run once via ``build_knowledge_base``): read the curated corpus, embed
    each entry with Chroma's local embedder, and persist the vectors to ``chroma_db/``.
  - Querying (every triage): handled by the ``lookup_cve`` tool in
    ``app/agent/tools.py``, which opens this store via ``get_collection``.

The embedding model is pre-fetched robustly on first build, because chromadb's own
downloader uses too short a timeout and does not retry on timeout (see Phase 6 notes).
"""

import hashlib
import json
from pathlib import Path

import chromadb

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
PERSIST_DIR = _PROJECT_ROOT / "chroma_db"
CORPUS_PATH = _PROJECT_ROOT / "data" / "kb" / "knowledge_base.jsonl"
COLLECTION_NAME = "knowledge_base"

# Chroma's default embedding model (we mirror its constants to pre-fetch reliably).
_MODEL_URL = "https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz"
_MODEL_SHA256 = "913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3"
_MODEL_DIR = Path.home() / ".cache" / "chroma" / "onnx_models" / "all-MiniLM-L6-v2"


def _sha256_ok(path: Path) -> bool:
    if not path.exists():
        return False
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(8192), b""):
            h.update(block)
    return h.hexdigest() == _MODEL_SHA256


def ensure_embedding_model() -> None:
    """Fetch Chroma's embedding-model archive with a generous timeout if it's missing.

    chromadb downloads this on first use but with a short timeout and no retry on
    timeout, which fails on slow links. Fetching it ourselves makes the build reliable
    and offline afterwards.
    """
    archive = _MODEL_DIR / "onnx.tar.gz"
    if (_MODEL_DIR / "onnx").is_dir() or _sha256_ok(archive):
        return  # already extracted, or a valid archive Chroma can extract itself

    import httpx

    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", _MODEL_URL, timeout=300.0, follow_redirects=True) as resp:
        resp.raise_for_status()
        with open(archive, "wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=256 * 1024):
                fh.write(chunk)
    if not _sha256_ok(archive):
        archive.unlink(missing_ok=True)
        raise RuntimeError("Embedding model download failed SHA256 verification.")


def _load_corpus(path: Path) -> list[dict]:
    rows: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _metadata(row: dict) -> dict:
    """Flat Chroma metadata (str/int/float/bool only); the embedded text is dropped."""
    return {k: v for k, v in row.items() if k != "text" and v is not None}


def build_knowledge_base(
    corpus_path: Path = CORPUS_PATH,
    persist_dir: Path = PERSIST_DIR,
) -> int:
    """Index the corpus into a persistent Chroma collection; return the entry count."""
    ensure_embedding_model()
    rows = _load_corpus(corpus_path)

    client = chromadb.PersistentClient(path=str(persist_dir))
    collection = client.get_or_create_collection(COLLECTION_NAME)
    collection.upsert(
        ids=[row["id"] for row in rows],
        documents=[row["text"] for row in rows],
        metadatas=[_metadata(row) for row in rows],
    )
    return collection.count()


def get_collection(persist_dir: Path = PERSIST_DIR):
    """Open the persisted knowledge-base collection for querying."""
    client = chromadb.PersistentClient(path=str(persist_dir))
    return client.get_collection(COLLECTION_NAME)


if __name__ == "__main__":
    count = build_knowledge_base()
    print(f"Indexed {count} entries into {PERSIST_DIR}")
