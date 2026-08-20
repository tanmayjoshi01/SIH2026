"""
rag/prompt_builder.py

Builds the single prompt string sent to gemma3:4b: the operator's question
(or an auto-generated "why is {node} at risk" query), the node's current
telemetry snapshot, Developer 1's anomaly scoring row, the node's active
incident (if any, from Developer 1's incidents table), bounded conversation
history, and the retrieved runbook chunks. Deliberately kept short -- no
telemetry history, and callers are expected to pass at most 2-3 chunks --
because on this CPU-only Ollama deployment, prompt length is a direct
multiplier on response latency.

Day 3 measurement (routers/copilot.py callers, this machine, telemetry
loop running concurrently): the Day 2 prompt shape (3 chunks @ 280-char
budget, no incident/history) already measured ~489 tokens / 1956 chars and
took the full 50s request timeout on a single call before generate_json()
gave up -- prompt evaluation throughput on this CPU is the bottleneck, not
generation. EXCERPT_CHAR_BUDGET is trimmed further here (280 -> 220) and
callers pass at most 2 chunks into build_prompt (the UI evidence panel
still gets all retrieved chunks separately) specifically to make room for
the incident line and history block below without growing the prompt
past what Day 2 was already sending.
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
    "inventing a cause. If an active incident is given below, use its status, "
    "severity, and score fields to answer questions about how long it has been "
    "open, whether it has been acknowledged, and whether it is improving -- "
    "never invent an incident that isn't given to you."
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
# fine for the evidence panel in the UI, but verbatim triples gemma3:4b's
# prompt size and pushed measured warm latency from ~20s to 60s+ on this
# CPU-only deployment. The LLM only needs enough of each chunk to ground
# its answer; the frontend still gets the untruncated excerpt via the
# evidence list built separately in routers/copilot.py. Trimmed further
# for Day 3 (280 -> 220) to make room for the incident line and history
# block without growing the prompt past the Day 2 baseline -- see the
# module docstring for the measured numbers this budget is sized against.
EXCERPT_CHAR_BUDGET = 220

# Day 3: caps on the two new prompt sections below, same reasoning as
# EXCERPT_CHAR_BUDGET -- each is small enough that even the worst case
# (an incident line plus 2 history turns) stays well under one retrieved
# chunk's budget.
HISTORY_TURN_CHAR_BUDGET = 90


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


def _incident_line(incident: Optional[dict]) -> str:
    if not incident:
        return "no active incident is open for this node"
    duration = incident.get("duration_minutes")
    duration_text = f"{duration:.1f} min" if duration is not None else "unknown"
    current = incident.get("current_anomaly_score")
    current_text = f"{current:.2f}" if current is not None else "unknown"
    return (
        f"incident #{incident['id']} status={incident['status']} severity={incident['severity']} "
        f"open_for={duration_text} peak_anomaly_score={incident['peak_anomaly_score']:.2f} "
        f"current_anomaly_score={current_text} root_cause_signal={incident.get('root_cause_signal') or 'unknown'}"
    )


def _history_block(history: Optional[list[dict]]) -> str:
    if not history:
        return ""
    lines = [
        f"Q: {_truncate(turn['question'], HISTORY_TURN_CHAR_BUDGET)}\n"
        f"A: {_truncate(turn['summary'], HISTORY_TURN_CHAR_BUDGET)}"
        for turn in history
    ]
    return "Recent conversation (most recent last):\n" + "\n".join(lines) + "\n\n"


def build_prompt(
    question: str,
    node_id: Optional[str],
    telemetry_snapshot: Optional[dict],
    anomaly: Optional[dict],
    chunks: list[dict],
    incident: Optional[dict] = None,
    history: Optional[list[dict]] = None,
) -> str:
    return (
        f"{SYSTEM_PREAMBLE}\n\n"
        f"{_history_block(history)}"
        f"Question: {question}\n\n"
        f"Node: {node_id or 'unspecified'}\n"
        f"Current telemetry snapshot: {_telemetry_line(telemetry_snapshot)}\n\n"
        f"Anomaly scoring: {_anomaly_line(anomaly)}\n\n"
        f"Active incident: {_incident_line(incident)}\n\n"
        f"Evidence:\n{_evidence_block(chunks)}\n\n"
        f"JSON:"
    )
