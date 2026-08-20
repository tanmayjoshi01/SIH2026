"""
rag/ingest.py

Chunks each runbook in data/runbooks/ by its ## sections, embeds every
chunk via Ollama's mxbai-embed-large HTTP endpoint, and upserts into a
local persistent ChromaDB collection called "runbooks". Chunk ids are
deterministic (`{filename}::{section-slug}`).

Run (from the repository root, with Ollama serving on 127.0.0.1:11434 and
mxbai-embed-large already pulled):
    python backend/rag/ingest.py

Day 4 grounding fix: general_troubleshooting.md's Recovery Procedure
section packs four independent, unordered policies (confidence gating,
escalation, human approval, retry policy) into one bulleted list. As a
single chunk it's ~1170 chars -- the eval harness's real failure review
(backend/rag/eval_results.json, questions gen-2/gen-3) found the specific
bullet a question asked about sitting far enough into that chunk that no
reasonable per-chunk prompt budget reached it, so the model answered
without ever seeing the right sentence. _split_bulleted_items() now
splits a `- **Label:** ...` bulleted section into one chunk per bullet at
ingest time, so a question about "escalation policy" retrieves the
Escalation bullet directly instead of a truncated slice of the whole
list. Numbered Recovery Procedure sections (bgp_flap.md, high_cpu.md,
packet_loss.md) are deliberately NOT split this way -- those are ordered
step-by-step procedures, not independent facts, and
routers/copilot.py's _recovery_steps_from_chunks() depends on retrieving
the whole sequence together to build a coherent recommended_actions list.
Because this changes how many chunks a section produces, ingest() now
deletes and recreates the collection on every run instead of upserting in
place, so a re-chunked section's old single-chunk id doesn't linger as an
orphaned, near-duplicate chunk alongside its new split ones.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import chromadb
import requests
import yaml

RUNBOOKS_DIR = Path(__file__).resolve().parents[2] / "data" / "runbooks"
CHROMA_PATH = Path(__file__).resolve().parent / "chroma_store"
COLLECTION_NAME = "runbooks"

OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_MODEL = "mxbai-embed-large"

_SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_BULLET_ITEM_RE = re.compile(r"^-\s+", re.MULTILINE)
_BOLD_LABEL_RE = re.compile(r"^-\s+\*\*(.+?)\*\*")


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


def _split_bulleted_items(body: str) -> Optional[List[Tuple[str, str]]]:
    """
    If `body` is a top-level bulleted list (>=2 `- ` items), returns one
    (label, item_text) pair per bullet -- label is the bullet's leading
    **bold** phrase if it has one, else "item N". Returns None for
    anything else (numbered lists, prose), which callers chunk whole.
    """
    starts = [m.start() for m in _BULLET_ITEM_RE.finditer(body)]
    if len(starts) < 2:
        return None

    items: List[Tuple[str, str]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(body)
        item_text = body[start:end].strip()
        if not item_text:
            continue
        bold_match = _BOLD_LABEL_RE.match(item_text)
        label = bold_match.group(1).rstrip(":").strip() if bold_match else f"item {index + 1}"
        items.append((label, item_text))
    return items if len(items) >= 2 else None


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
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass  # no prior collection to delete -- fine on a first run
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

            sub_items = _split_bulleted_items(body)
            pieces = (
                [(f"{title} — {label}", item_text) for label, item_text in sub_items]
                if sub_items
                else [(title, body)]
            )

            for chunk_title, chunk_body in pieces:
                chunk_text = f"{frontmatter.get('title', path.stem)} - {chunk_title}\n{chunk_body}"
                ids.append(f"{path.name}::{_slug(chunk_title)}")
                embeddings.append(_embed(chunk_text))
                documents.append(chunk_body)
                metadatas.append(
                    {
                        "runbook_file": path.name,
                        "section_title": chunk_title,
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
