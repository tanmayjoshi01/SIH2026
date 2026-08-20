"""
rag/ingest.py

Chunks each runbook in data/runbooks/ by its ## sections, embeds every
chunk via Ollama's mxbai-embed-large HTTP endpoint, and upserts into a
local persistent ChromaDB collection called "runbooks". Chunk ids are
deterministic (`{filename}::{section-slug}`), so re-running this script
after editing a runbook overwrites its old chunks instead of duplicating
them -- safe to run as often as needed.

Run (from the repository root, with Ollama serving on 127.0.0.1:11434 and
mxbai-embed-large already pulled):
    python backend/rag/ingest.py
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

import chromadb
import requests
import yaml

RUNBOOKS_DIR = Path(__file__).resolve().parents[2] / "data" / "runbooks"
CHROMA_PATH = Path(__file__).resolve().parent / "chroma_store"
COLLECTION_NAME = "runbooks"

OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_MODEL = "mxbai-embed-large"

_SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _embed(text: str) -> List[float]:
    response = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["embedding"]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _parse_runbook(path: Path) -> Tuple[Dict, List[Tuple[str, str]]]:
    """Returns (frontmatter dict, [(section_title, section_body), ...])."""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        _, frontmatter_raw, body = text.split("---", 2)
        frontmatter = yaml.safe_load(frontmatter_raw) or {}
    else:
        frontmatter, body = {}, text

    matches = list(_SECTION_RE.finditer(body))
    sections: List[Tuple[str, str]] = []
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.append((title, body[start:end].strip()))
    return frontmatter, sections


def ingest() -> int:
    CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = client.get_or_create_collection(name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})

    runbook_paths = sorted(RUNBOOKS_DIR.glob("*.md"))
    if not runbook_paths:
        print(f"No runbooks found in {RUNBOOKS_DIR}")
        return 0

    total_chunks = 0
    for path in runbook_paths:
        frontmatter, sections = _parse_runbook(path)
        ids, embeddings, documents, metadatas = [], [], [], []
        for title, body in sections:
            if not body:
                continue
            chunk_text = f"{frontmatter.get('title', path.stem)} - {title}\n{body}"
            ids.append(f"{path.name}::{_slug(title)}")
            embeddings.append(_embed(chunk_text))
            documents.append(body)
            metadatas.append(
                {
                    "runbook_file": path.name,
                    "section_title": title,
                    "doc_title": frontmatter.get("title", path.stem),
                    "subsystem": frontmatter.get("subsystem", ""),
                    "severity": frontmatter.get("severity", ""),
                }
            )
        if ids:
            collection.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
            total_chunks += len(ids)
            print(f"  {path.name}: {len(ids)} chunks")

    print(f"Ingested {total_chunks} chunks across {len(runbook_paths)} runbooks into '{COLLECTION_NAME}' at {CHROMA_PATH}")
    return total_chunks


if __name__ == "__main__":
    ingest()
