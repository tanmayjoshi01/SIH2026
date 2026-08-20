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
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from core.taxonomy import ID_TO_INFO
from db.database import SessionLocal
from db.models import Anomaly, Node, Recommendation
from rag.prompt_builder import build_prompt
from rag.retrieve import retrieve
from services.llm_service import generate_json
from simulation.topology_def import NODE_DEFS

logger = logging.getLogger("copilot")
router = APIRouter(tags=["copilot"])

_NODE_IDS = [node_id for node_id, _, _ in NODE_DEFS]
RETRIEVAL_K = 3


class ChatRequest(BaseModel):
    question: str = ""


def _pick_node(session, question: str) -> Optional[str]:
    """The node named in the question, or -- if none is named -- whichever node currently has the highest open anomaly score."""
    lowered = question.lower()
    for node_id in _NODE_IDS:
        if node_id in lowered:
            return node_id

    row = session.execute(
        select(Anomaly.node_id)
        .where(Anomaly.status == "open")
        .order_by(Anomaly.anomaly_score.desc().nullslast(), Anomaly.detected_at.desc())
        .limit(1)
    ).first()
    if row:
        return row[0]

    row = session.execute(select(Anomaly.node_id).order_by(Anomaly.detected_at.desc()).limit(1)).first()
    return row[0] if row else None


def _latest_anomaly(session, node_id: str) -> Optional[Anomaly]:
    return session.scalars(
        select(Anomaly).where(Anomaly.node_id == node_id).order_by(Anomaly.detected_at.desc()).limit(1)
    ).first()


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

    try:
        with SessionLocal() as session:
            node_id = _pick_node(session, question)
            anomaly = _latest_anomaly(session, node_id) if node_id else None
            node_row = session.get(Node, node_id) if node_id else None

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

            prompt = build_prompt(
                question=question,
                node_id=node_id,
                telemetry_snapshot=telemetry_snapshot,
                anomaly=anomaly_summary,
                chunks=chunks,
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

    return result
