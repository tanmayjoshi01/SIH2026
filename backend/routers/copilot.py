"""
routers/copilot.py

Real Day 2 pipeline: picks the node the question is about (or the most
at-risk one currently in the anomalies table), retrieves runbook evidence,
builds the prompt, calls gemma3:4b via services/llm_service.py, and falls
back to a deterministic template built straight from taxonomy + anomaly
data if the LLM is unreachable or never produces valid JSON -- the UI
must never see a raw error or a blank response. Keeps the exact Day 1
response shape (summary, root_cause, risk, affected_component,
recommended_action, evidence, confidence, requires_human_approval) that
AICopilot.jsx and CitationBadge.jsx already consume; `mode` is an extra,
optional field the frontend may use to flag a fallback answer.

Day 3 additions (all additive -- no existing field is renamed or removed):
  - Reads Developer 1's `incidents` table (read-only; incident lifecycle
    stays entirely in services/incident_manager.py) to find the picked
    node's open/acknowledged incident, if any, and folds it into the
    prompt and the response (incident_id, affected_node, status, severity).
  - `recommended_actions` (a short list) is assembled deterministically
    from the retrieved runbook's "Recovery Procedure" section, falling
    back to the fault taxonomy's single mitigation action when no such
    section clears the retrieval similarity threshold -- the LLM never
    supplies these steps, matching the Day 3 "grounded recommendations"
    requirement.
  - Bounded per-session conversation memory (last 4 turns, in-process
    dict) is threaded into the prompt so follow-up questions like "what
    should I do?" resolve pronouns against the prior turn.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from core.taxonomy import ID_TO_INFO
from db.database import SessionLocal
from db.models import Anomaly, Incident, Node, Recommendation
from rag.prompt_builder import build_prompt
from rag.retrieve import retrieve
from services.llm_service import generate_json
from simulation.topology_def import NODE_DEFS

logger = logging.getLogger("copilot")
router = APIRouter(tags=["copilot"])

_NODE_IDS = [node_id for node_id, _, _ in NODE_DEFS]
RETRIEVAL_K = 3
# Only the top 2 retrieved chunks go into the LLM prompt (see
# rag/prompt_builder.py's module docstring) -- the evidence panel in the
# UI still gets all RETRIEVAL_K chunks via _to_evidence() below.
PROMPT_CHUNK_LIMIT = 2

ACTIVE_INCIDENT_STATUSES = ("open", "acknowledged")

# Day 3: bounded, in-memory-only conversation history, matching
# services/incident_manager.py's precedent of process-local state for a
# single-demo-process deployment (no Redis, no DB-backed table). One
# process owns this dict, same as IncidentManager owns its tick counters.
_SESSION_HISTORY: Dict[str, Deque[dict]] = defaultdict(lambda: deque(maxlen=4))
HISTORY_TURNS_IN_PROMPT = 2

_RECOVERY_STEP_HEADER_RE = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
RECOVERY_STEPS_MAX = 4


class ChatRequest(BaseModel):
    question: str = ""
    session_id: Optional[str] = None


def _pick_node(session, question: str, session_id: Optional[str] = None) -> Optional[str]:
    """
    The node named in the question; else the node from this session's last
    turn (so "what should I do?" resolves to the incident just discussed,
    not whatever node is worst system-wide); else the node with the
    currently most-at-risk open/acknowledged incident; else, if nothing is
    open at all, whichever node's scoring tick was written most recently.

    Day 5 fix: the third branch used to be `WHERE Anomaly.status == "open"
    ORDER BY anomaly_score DESC` -- but the anomalies table is append-only
    (one row per node per scoring tick, never pruned), and
    Anomaly.status is a raw per-tick flag (services/anomaly_scoring_
    service.py sets it from whatever fault is injected *at that instant*),
    not Developer 1's stabilized, 3-consecutive-tick-gated incident state.
    A node whose fault resolved an hour ago still has old rows sitting in
    the table with status="open" from when it was active; if that old
    episode's peak score happened to beat whatever's actually active now,
    that query would resurrect it as "the" answer to a no-node-named
    question -- exactly the staleness this fix closes. Querying the
    `incidents` table instead means only Developer 1's real, current
    open/acknowledged incidents are ever candidates.
    """
    lowered = question.lower()
    for node_id in _NODE_IDS:
        if node_id in lowered:
            return node_id

    if session_id and session_id in _SESSION_HISTORY and _SESSION_HISTORY[session_id]:
        last_node_id = _SESSION_HISTORY[session_id][-1].get("node_id")
        if last_node_id:
            return last_node_id

    incident_row = session.execute(
        select(Incident.node_id)
        .where(Incident.status.in_(ACTIVE_INCIDENT_STATUSES))
        .order_by(Incident.peak_anomaly_score.desc().nullslast(), Incident.id.desc())
        .limit(1)
    ).first()
    if incident_row:
        return incident_row[0]

    row = session.execute(select(Anomaly.node_id).order_by(Anomaly.detected_at.desc()).limit(1)).first()
    return row[0] if row else None


def _latest_anomaly(session, node_id: str) -> Optional[Anomaly]:
    return session.scalars(
        select(Anomaly).where(Anomaly.node_id == node_id).order_by(Anomaly.detected_at.desc()).limit(1)
    ).first()


def _active_incident(session, node_id: Optional[str]) -> Optional[Incident]:
    """Read-only lookup of the node's current open/acknowledged incident. Never writes -- lifecycle stays in services/incident_manager.py."""
    if not node_id:
        return None
    return session.scalars(
        select(Incident)
        .where(Incident.node_id == node_id, Incident.status.in_(ACTIVE_INCIDENT_STATUSES))
        .order_by(Incident.id.desc())
    ).first()


def _incident_summary(incident: Optional[Incident], current_anomaly_score: Optional[float]) -> Optional[dict]:
    if incident is None:
        return None
    duration_minutes = None
    if incident.opened_at is not None:
        now = dt.datetime.now(dt.timezone.utc)
        duration_minutes = round(max(0.0, (now - incident.opened_at).total_seconds() / 60.0), 1)
    return {
        "id": incident.id,
        "status": incident.status,
        "severity": incident.severity,
        "opened_at": incident.opened_at.isoformat() if incident.opened_at else None,
        "duration_minutes": duration_minutes,
        "peak_anomaly_score": incident.peak_anomaly_score,
        "current_anomaly_score": current_anomaly_score,
        "root_cause_signal": incident.root_cause_signal,
    }


def _recovery_steps_from_chunks(chunks: list[dict]) -> list[str]:
    """Numbered steps parsed straight out of a retrieved 'Recovery Procedure' runbook section -- never LLM-authored. Continuation lines of a wrapped step are joined and whitespace-collapsed, not truncated at the first newline."""
    for chunk in chunks:
        if chunk["section_title"].strip().lower() == "recovery procedure":
            text = chunk["excerpt"]
            headers = list(_RECOVERY_STEP_HEADER_RE.finditer(text))
            if not headers:
                continue
            steps = []
            for index, match in enumerate(headers):
                start = match.end()
                end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
                step_text = " ".join(text[start:end].split())
                if step_text:
                    steps.append(step_text)
            if steps:
                return steps[:RECOVERY_STEPS_MAX]
    return []


def _recommended_actions(fault_type: Optional[str], chunks: list[dict]) -> list[str]:
    """Grounded action list: retrieved runbook steps first, else the taxonomy's single mitigation action. The LLM never supplies these."""
    steps = _recovery_steps_from_chunks(chunks)
    if steps:
        return steps
    info = ID_TO_INFO.get(fault_type or "healthy", ID_TO_INFO["healthy"])
    return [] if info["action"] == "none" else [info["action"]]


def _history_for_prompt(session_id: Optional[str]) -> list[dict]:
    if not session_id or session_id not in _SESSION_HISTORY:
        return []
    return list(_SESSION_HISTORY[session_id])[-HISTORY_TURNS_IN_PROMPT:]


def _remember_turn(session_id: Optional[str], question: str, summary: str, node_id: Optional[str]) -> None:
    if not session_id or not question:
        return
    _SESSION_HISTORY[session_id].append({"question": question, "summary": summary, "node_id": node_id})


def _to_evidence(chunks: list[dict]) -> list[dict]:
    # Carries both the Day 1 shape CitationBadge.jsx already reads
    # (source/snippet/score) and the runbook_file/section_title/excerpt
    # shape from the written data contract -- extra keys are harmless to
    # the frontend and let either be relied on.
    return [
        {
            "source": f"{chunk['runbook_file']} § {chunk['section_title']}",
            "snippet": chunk["excerpt"],
            "score": chunk["score"],
            "runbook_file": chunk["runbook_file"],
            "section_title": chunk["section_title"],
            "excerpt": chunk["excerpt"],
        }
        for chunk in chunks
    ]


def _fallback_response(node_id: Optional[str], anomaly: Optional[Anomaly], evidence: list[dict]) -> dict:
    if anomaly is None or anomaly.fault_type == "healthy":
        score = float(anomaly.anomaly_score) if anomaly and anomaly.anomaly_score is not None else 0.0
        return {
            "summary": f"[Offline fallback] No active anomaly detected on {node_id or 'the network'}; telemetry looks nominal.",
            "root_cause": "No fault currently attributed by the anomaly scorer.",
            "risk": round(max(0.0, min(1.0, score)), 4),
            "affected_component": node_id or "network",
            "recommended_action": "none",
            "evidence": evidence,
            "confidence": 0.0,
            "requires_human_approval": False,
            "mode": "fallback",
        }

    info = ID_TO_INFO.get(anomaly.fault_type, ID_TO_INFO["healthy"])
    signals = ", ".join(anomaly.contributing_signals or []) or "no single dominant signal"
    risk = anomaly.failure_probability if anomaly.failure_probability is not None else (anomaly.anomaly_score or 0.0)
    return {
        "summary": f"[Offline fallback] {info['display']} detected on {node_id} (anomaly_score={anomaly.anomaly_score:.2f}).",
        "root_cause": f"{info['display']} -- contributing signals: {signals}.",
        "risk": round(max(0.0, min(1.0, risk)), 4),
        "affected_component": node_id or "network",
        "recommended_action": info["action"],
        "evidence": evidence,
        "confidence": 0.0,
        "requires_human_approval": True,
        "mode": "fallback",
    }


@router.post("/chat")
def post_chat(payload: ChatRequest) -> dict:
    question = payload.question.strip()
    session_id = payload.session_id
    incident_id: Optional[int] = None
    node_id: Optional[str] = None
    status = "healthy"
    severity = "none"
    recommended_actions: list[str] = []

    try:
        with SessionLocal() as session:
            node_id = _pick_node(session, question, session_id)
            anomaly = _latest_anomaly(session, node_id) if node_id else None
            node_row = session.get(Node, node_id) if node_id else None
            incident = _active_incident(session, node_id)

            if not question:
                question = (
                    f"Why is {node_id} at risk?"
                    if anomaly and anomaly.fault_type != "healthy"
                    else "Summarise the current network risk."
                )

            retrieval_query = question
            if anomaly and anomaly.fault_type != "healthy" and anomaly.fault_type in ID_TO_INFO:
                retrieval_query = f"{question} {ID_TO_INFO[anomaly.fault_type]['display']}"

            try:
                chunks = retrieve(retrieval_query, k=RETRIEVAL_K)
            except Exception:
                logger.exception("Runbook retrieval failed; continuing with no evidence")
                chunks = []

            evidence = _to_evidence(chunks)
            recommended_actions = _recommended_actions(anomaly.fault_type if anomaly else None, chunks)

            incident_summary = _incident_summary(incident, anomaly.anomaly_score if anomaly else None)
            if incident is not None:
                incident_id = incident.id
                status = incident.status
                severity = incident.severity

            telemetry_snapshot = None
            if node_row is not None:
                telemetry_snapshot = {
                    "cpu": node_row.cpu,
                    "memory": node_row.memory,
                    "packet_loss": node_row.packet_loss,
                    "latency_ms": node_row.latency_ms,
                    "status": node_row.status,
                }

            anomaly_summary = None
            if anomaly is not None:
                anomaly_summary = {
                    "anomaly_score": anomaly.anomaly_score,
                    "failure_probability": anomaly.failure_probability,
                    "eta_minutes": anomaly.eta_minutes,
                    "contributing_signals": anomaly.contributing_signals or [],
                    "fault_type": anomaly.fault_type,
                    "status": anomaly.status,
                }

            history = _history_for_prompt(session_id)

            prompt = build_prompt(
                question=question,
                node_id=node_id,
                telemetry_snapshot=telemetry_snapshot,
                anomaly=anomaly_summary,
                chunks=chunks[:PROMPT_CHUNK_LIMIT],
                incident=incident_summary,
                history=history,
            )

            llm_result = generate_json(prompt)

            if llm_result is not None:
                recommended_action = llm_result["recommended_action"] or "none"
                result = {
                    "summary": llm_result["summary"],
                    "root_cause": llm_result["root_cause"],
                    "risk": llm_result["risk"],
                    "affected_component": llm_result["affected_component"] or node_id or "network",
                    "recommended_action": recommended_action,
                    "evidence": evidence,
                    "confidence": llm_result["confidence"],
                    "requires_human_approval": recommended_action.lower() not in ("none", ""),
                    "mode": "llm",
                }
            else:
                result = _fallback_response(node_id, anomaly, evidence)

            _remember_turn(session_id, question, result["summary"], node_id)

            if anomaly is not None and anomaly.id is not None:
                try:
                    session.add(
                        Recommendation(
                            anomaly_id=anomaly.id,
                            action=result["recommended_action"],
                            confidence=result["confidence"],
                            status="pending",
                        )
                    )
                    session.commit()
                except SQLAlchemyError:
                    logger.exception("Failed to log recommendation row; continuing without it")
                    session.rollback()

    except SQLAlchemyError as exc:
        logger.exception("Database unavailable while answering /api/chat")
        result = _fallback_response(None, None, [])
        result["summary"] = f"{result['summary']} (database unavailable: {exc.__class__.__name__})"

    result["incident_id"] = incident_id
    result["affected_node"] = node_id or result.get("affected_component")
    result["status"] = status
    result["severity"] = severity
    result["recommended_actions"] = recommended_actions
    return result
