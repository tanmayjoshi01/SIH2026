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
generation.

Day 4 grounding-fix finding (backend/rag/eval_harness.py, read the literal
failing question/chunk/answer triples, not just the pass rate): the eval
harness's 4 real LLM-mode grounding failures all shared the same shape --
when telemetry_snapshot or incident was None, the OLD prompt stated that
plainly ("no live telemetry available for this node" / "no active incident
is open for this node") as its own sentence, and gemma3:4b would echo that
sentence verbatim into summary/root_cause instead of composing an answer
from the retrieved evidence -- even when the evidence plainly contained
the answer (confirmed: bgp-3's correct recommended_action="restart_bgp_
session" was extracted into that field, but summary/root_cause were still
just the telemetry non-answer). The fix below is to omit those lines
entirely when there's nothing to say, rather than stating an absence the
model then treats as the headline. Two more failures (gen-2, gen-3) traced
to the answer sitting past this module's truncation point inside a
multi-policy Recovery Procedure chunk -- fixed at the source instead, by
rag/ingest.py now splitting a list-structured section into one chunk per
step/bullet, so the specific policy a question asks about is directly
retrievable rather than needing a much larger per-chunk char budget here.
"""

from __future__ import annotations

from typing import Optional

SYSTEM_PREAMBLE = (
    "You are a NOC copilot operating fully offline inside an air-gapped network. "
    "Answer ONLY using the Evidence section below -- never invent facts, log lines, "
    "or procedures not present there. A missing telemetry snapshot or missing active "
    "incident is NOT a reason to ignore the Evidence -- use it to answer procedural "
    "or policy questions regardless of what telemetry/incident data is available. "
    "Only treat evidence as insufficient if the Evidence section itself does not "
    "address the question asked; in that case, or if the node shows no active "
    "anomaly, say so plainly in summary rather than inventing a cause, set risk near "
    "the given anomaly_score (or 0 if none), and lower confidence accordingly. "
    "Respond with strict minified JSON only, no markdown fences, no commentary, "
    "matching exactly these keys: summary (string), root_cause (string), risk "
    "(number 0-1), affected_component (string), recommended_action (string), "
    "confidence (number 0-1). Example of a correct response when Evidence does not "
    "address the question: "
    '{"summary":"No runbook evidence addresses this question.",'
    '"root_cause":"Not covered by the available evidence.","risk":0.0,'
    '"affected_component":"unspecified","recommended_action":"none","confidence":0.1}'
)


def _telemetry_line(snapshot: Optional[dict]) -> Optional[str]:
    if not snapshot:
        return None
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
# evidence list built separately in routers/copilot.py. Bumped slightly
# for Day 4 (220 -> 260) now that omitting empty telemetry/incident lines
# (see module docstring) frees up the room this needs -- see the module
# docstring for the measured numbers this budget is sized against.
EXCERPT_CHAR_BUDGET = 260

# Day 3: cap on the history block below, same reasoning as
# EXCERPT_CHAR_BUDGET -- small enough that even 2 history turns stay well
# under one retrieved chunk's budget.
HISTORY_TURN_CHAR_BUDGET = 90

def _truncate(text: str, limit: int) -> str:
    """
    Word-boundary truncation. Deliberately simple -- rag/ingest.py now
    splits a runbook's Recovery Procedure / policy-bullet sections into
    one chunk per step or bullet (see its module docstring), so a
    retrieved chunk here is normally already a single, short, complete
    thought and rarely needs truncating at all. An earlier version of
    this function tried to be clever about preferring whole-item
    boundaries when a chunk still ran long, but that requires generous
    slack to avoid cutting a chunk off exactly where the answer starts --
    the real fix for "the answer is past the truncation point" turned out
    to be chunking granularity at ingest time, not truncation logic here.
    """
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


def _incident_line(incident: Optional[dict]) -> Optional[str]:
    if not incident:
        return None
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
    # Day 4: telemetry/incident lines are omitted entirely when there's
    # nothing to report, rather than stating the absence as a sentence --
    # see the module docstring for why a stated absence became bait the
    # model would echo instead of using the evidence.
    telemetry_text = _telemetry_line(telemetry_snapshot)
    telemetry_part = f"Current telemetry snapshot: {telemetry_text}\n\n" if telemetry_text else ""

    incident_text = _incident_line(incident)
    incident_part = f"Active incident: {incident_text}\n\n" if incident_text else ""

    return (
        f"{SYSTEM_PREAMBLE}\n\n"
        f"{_history_block(history)}"
        f"Question: {question}\n\n"
        f"Node: {node_id or 'unspecified'}\n"
        f"{telemetry_part}"
        f"Anomaly scoring: {_anomaly_line(anomaly)}\n\n"
        f"{incident_part}"
        f"Evidence:\n{_evidence_block(chunks)}\n\n"
        f"JSON:"
    )
