"""
rag/eval_harness.py

Offline-only RAG evaluation harness for the Day 3 copilot pipeline. Not
imported by, or reachable from, any live API route -- run manually from
the repository root (Ollama must be serving on 127.0.0.1:11434 and the
runbooks must already be ingested via rag/ingest.py):

    backend/venv/Scripts/python.exe backend/rag/eval_harness.py

For each question in golden_questions.json, this measures two things
against the same retrieval/prompt shape routers/copilot.py actually uses
(same RETRIEVAL_K, same PROMPT_CHUNK_LIMIT):

  1. Retrieval hit rate -- did the runbook file the question is actually
     about (`expected_runbook`) appear anywhere in the top-k chunks
     retrieve() returned, above the existing 0.5 similarity threshold?

  2. Grounding -- is the LLM's answer text lexically grounded in the
     retrieved evidence? grounding_score() is a simple word-overlap
     heuristic (what fraction of the answer's significant words also
     appear in the evidence it was given), not a claim-by-claim fact
     checker -- deliberately simple per the Day 3 scope. A fallback-mode
     answer (LLM unreachable or invalid JSON) is trivially grounded,
     since routers/copilot.py's fallback template is built straight from
     taxonomy + anomaly data with no LLM involved -- it cannot hallucinate.

Each question can take 20-90s on this CPU-only deployment (prompt
evaluation, not just generation, is the measured bottleneck -- see
rag/prompt_builder.py's module docstring), so a full run over the golden
set can take 15-30 minutes. Progress prints per-question; full structured
results are written to rag/eval_results.json alongside the summary
printed at the end.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from rag.prompt_builder import build_prompt  # noqa: E402
from rag.retrieve import retrieve  # noqa: E402
from services.llm_service import generate_json  # noqa: E402

GOLDEN_QUESTIONS_PATH = Path(__file__).resolve().parent / "golden_questions.json"
RESULTS_PATH = Path(__file__).resolve().parent / "eval_results.json"

# Mirrors routers/copilot.py's RETRIEVAL_K / PROMPT_CHUNK_LIMIT so this
# harness measures the pipeline that actually runs in production, not a
# hypothetical one.
RETRIEVAL_K = 3
PROMPT_CHUNK_LIMIT = 2
GROUNDING_THRESHOLD = 0.3

_STOPWORDS = {
    "the", "a", "an", "and", "or", "is", "are", "of", "to", "in", "on", "for",
    "with", "this", "that", "it", "was", "be", "as", "by", "at", "from", "its",
    "which", "not", "no", "currently", "than", "into", "over", "will", "has",
    "have", "had", "been", "being", "does", "do", "did", "can", "could",
}
_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_%]*")


def _content_words(text: str) -> set[str]:
    words = _WORD_RE.findall(text.lower())
    return {w for w in words if len(w) > 3 and w not in _STOPWORDS}


def grounding_score(answer_text: str, evidence_text: str) -> float:
    """Fraction of the answer's significant words that also appear somewhere in the evidence it was given. 1.0 if the answer has no significant words to check."""
    answer_words = _content_words(answer_text)
    if not answer_words:
        return 1.0
    evidence_words = _content_words(evidence_text)
    overlap = answer_words & evidence_words
    return len(overlap) / len(answer_words)


def evaluate_question(item: dict) -> dict:
    question = item["question"]

    try:
        chunks = retrieve(question, k=RETRIEVAL_K)
    except Exception as exc:  # pragma: no cover - offline diagnostic path
        return {
            "id": item["id"],
            "question": question,
            "retrieval_hit": False,
            "retrieved_files": [],
            "mode": "error",
            "grounded": False,
            "grounding_score": None,
            "elapsed_seconds": 0.0,
            "error": f"retrieval failed: {exc.__class__.__name__}: {exc}",
        }

    retrieved_files = sorted({c["runbook_file"] for c in chunks})
    retrieval_hit = item["expected_runbook"] in retrieved_files

    prompt = build_prompt(
        question=question,
        node_id=item.get("node_id"),
        telemetry_snapshot=None,
        anomaly=item.get("anomaly"),
        chunks=chunks[:PROMPT_CHUNK_LIMIT],
    )

    t0 = time.time()
    llm_result = generate_json(prompt)
    elapsed = time.time() - t0

    if llm_result is None:
        return {
            "id": item["id"],
            "question": question,
            "retrieval_hit": retrieval_hit,
            "retrieved_files": retrieved_files,
            "mode": "fallback",
            "grounded": True,
            "grounding_score": None,
            "elapsed_seconds": round(elapsed, 1),
        }

    evidence_text = "\n".join(c["excerpt"] for c in chunks[:PROMPT_CHUNK_LIMIT])
    answer_text = f"{llm_result['summary']} {llm_result['root_cause']}"
    score = grounding_score(answer_text, evidence_text)

    return {
        "id": item["id"],
        "question": question,
        "retrieval_hit": retrieval_hit,
        "retrieved_files": retrieved_files,
        "mode": "llm",
        "grounded": score >= GROUNDING_THRESHOLD,
        "grounding_score": round(score, 3),
        "elapsed_seconds": round(elapsed, 1),
    }


def main() -> None:
    questions = json.loads(GOLDEN_QUESTIONS_PATH.read_text(encoding="utf-8"))
    results = []

    for index, item in enumerate(questions, start=1):
        print(f"[{index}/{len(questions)}] {item['id']}: {item['question']}")
        result = evaluate_question(item)
        results.append(result)
        print(
            f"    retrieval_hit={result['retrieval_hit']} mode={result['mode']} "
            f"grounded={result['grounded']} score={result['grounding_score']} "
            f"({result['elapsed_seconds']}s)"
        )

    total = len(results)
    hits = sum(1 for r in results if r["retrieval_hit"])
    grounded = sum(1 for r in results if r["grounded"])
    llm_count = sum(1 for r in results if r["mode"] == "llm")
    fallback_count = sum(1 for r in results if r["mode"] == "fallback")
    error_count = sum(1 for r in results if r["mode"] == "error")

    print("\n=== RAG Eval Summary ===")
    print(f"Questions: {total}")
    print(f"Retrieval hit rate: {hits}/{total} ({hits / total:.0%})")
    print(f"Grounding pass rate: {grounded}/{total} ({grounded / total:.0%})")
    print(f"Mode: {llm_count} llm / {fallback_count} fallback / {error_count} error")

    RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nFull results written to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
