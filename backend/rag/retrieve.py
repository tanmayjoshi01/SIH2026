"""
rag/retrieve.py

Embeds a query the same way ingest.py embeds runbook chunks (Ollama's
mxbai-embed-large), then does top-k cosine similarity search against the
persistent "runbooks" ChromaDB collection ingest.py populates. Chunks
below SIMILARITY_THRESHOLD are dropped rather than returned as weak
"evidence" -- Chroma always returns its k nearest neighbours regardless of
how unrelated they are, so callers must treat an empty result as "no
runbook evidence found" (e.g. a healthy node, or an off-topic question)
rather than always citing something.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, TypedDict

import chromadb
import requests

CHROMA_PATH = Path(__file__).resolve().parent / "chroma_store"
COLLECTION_NAME = "runbooks"

OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_MODEL = "mxbai-embed-large"

DEFAULT_K = 5
SIMILARITY_THRESHOLD = 0.5

_client = None
_collection = None


class RetrievedChunk(TypedDict):
    runbook_file: str
    section_title: str
    excerpt: str
    score: float


def _embed_query(text: str) -> List[float]:
    # mxbai-embed-large is an asymmetric retrieval model: prefixing the
    # query (but not the indexed documents, see ingest.py) with this
    # instruction improves query/passage matching, per the model's card.
    prefixed = f"Represent this sentence for searching relevant passages: {text}"
    response = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": prefixed},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["embedding"]


def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        _collection = _client.get_or_create_collection(name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    return _collection


def retrieve(query: str, k: int = DEFAULT_K, threshold: Optional[float] = None) -> List[RetrievedChunk]:
    """Top-k runbook chunks for `query`, filtered to those above the similarity threshold."""
    collection = _get_collection()
    count = collection.count()
    if count == 0:
        return []

    embedding = _embed_query(query)
    results = collection.query(query_embeddings=[embedding], n_results=min(k, count))
    min_score = SIMILARITY_THRESHOLD if threshold is None else threshold

    chunks: List[RetrievedChunk] = []
    for document, metadata, distance in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        score = 1.0 - distance
        if score < min_score:
            continue
        chunks.append(
            RetrievedChunk(
                runbook_file=metadata["runbook_file"],
                section_title=metadata["section_title"],
                excerpt=document,
                score=round(score, 4),
            )
        )
    return chunks
