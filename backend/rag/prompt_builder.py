"""
rag/prompt_builder.py

Builds the single prompt string sent to gemma3:4b: the operator's question
(or an auto-generated "why is {node} at risk" query), the node's current
telemetry snapshot, Developer 1's anomaly scoring row, and the retrieved
runbook chunks. Deliberately kept short -- no telemetry history, and
callers are expected to pass at most 3 chunks -- because on this
CPU-only Ollama deployment, prompt length is a direct multiplier on
response latency (measured ~20s warm for a prompt this size).
"""

from __future__ import annotations

from typing import Optional

SYSTEM_PREAMBLE = (
    "You are a NOC copilot operating fully offline inside an air-gapped network. "
    "Answer ONLY using the evidence below -- never invent facts, log lines, or "
    "runbook content that isn't given to you. Respond with strict minified JSON "
    "only, no markdown fences, no commentary, matching exactly these keys: "
    "summary (string), root_cause (string), risk (number 0-1), affected_component "
    "(string), recommended_action (string), confidence (number 0-1). If the "
    "evidence below does not support a fault-specific answer, or the node shows "
    "no active anomaly, say so plainly in summary, set risk near the given "
    "anomaly_score (or 0 if none), and lower confidence accordingly rather than "
    "inventing a cause."
)


def _telemetry_line(snapshot: Optional[dict]) -> str:
    if not snapshot:
        return "no live telemetry available for this node"
    return (
        f"cpu={snapshot['cpu']:.1f}% memory={snapshot['memory']:.1f}% "
        f"packet_loss={snapshot['packet_loss']:.1f}% latency_ms={snapshot['latency_ms']:.1f}ms "
        f"status={snapshot['status']}"
    )


def _anomaly_line(anomaly: Optional[dict]) -> str:
    if not anomaly:
        return "no anomaly scoring available for this node"
    signals = ", ".join(anomaly.get("contributing_signals") or []) or "none above noise threshold"
    eta = anomaly.get("eta_minutes")
    eta_text = f"{eta:.1f} min" if eta is not None else "not currently rising"
    anomaly_score = anomaly.get("anomaly_score") or 0.0
    failure_probability = anomaly.get("failure_probability") or 0.0
    return (
        f"anomaly_score={anomaly_score:.2f} failure_probability={failure_probability:.2f} "
        f"eta_to_critical={eta_text} contributing_signals=[{signals}] "
        f"fault_type={anomaly.get('fault_type')} status={anomaly.get('status')}"
    )


# Retrieved chunks are full runbook sections (can run 1000+ chars each) --
# fine for the evidence panel in the UI, but 3 of them verbatim triples
# gemma3:4b's prompt size and pushed measured warm latency from ~20s to
# 60s+ on this CPU-only deployment. The LLM only needs enough of each
# chunk to ground its answer; the frontend still gets the untruncated
# excerpt via the evidence list built separately in routers/copilot.py.
EXCERPT_CHAR_BUDGET = 280


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "..."


def _evidence_block(chunks: list[dict]) -> str:
    if not chunks:
        return "No runbook evidence retrieved above the relevance threshold."
    lines = [
        f"[{i}] {c['runbook_file']} / {c['section_title']}: {_truncate(c['excerpt'], EXCERPT_CHAR_BUDGET)}"
        for i, c in enumerate(chunks, start=1)
    ]
    return "\n".join(lines)


def build_prompt(
    question: str,
    node_id: Optional[str],
    telemetry_snapshot: Optional[dict],
    anomaly: Optional[dict],
    chunks: list[dict],
) -> str:
    return (
        f"{SYSTEM_PREAMBLE}\n\n"
        f"Question: {question}\n\n"
        f"Node: {node_id or 'unspecified'}\n"
        f"Current telemetry snapshot: {_telemetry_line(telemetry_snapshot)}\n\n"
        f"Anomaly scoring: {_anomaly_line(anomaly)}\n\n"
        f"Evidence:\n{_evidence_block(chunks)}\n\n"
        f"JSON:"
    )
