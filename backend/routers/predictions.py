"""
routers/predictions.py

Real queries over Developer 1's anomalies table (Day 2 scoring columns:
anomaly_score, failure_probability, eta_minutes). One row per (node,
scoring tick) is written every ~2s by the telemetry loop, so "latest row
per node_id" is a node's current reading for both endpoints below.

Day 3: GET /predictions additionally folds in each node's open/
acknowledged incident (status, severity) from Developer 1's incidents
table -- a read-only lookup, same pattern as routers/copilot.py's
_active_incident(). Nodes with no active incident get status="healthy",
severity="none", incident_id=None rather than a null gap, matching what
routers/copilot.py already does for /api/chat's equivalent fields. No
anomaly scoring or incident lifecycle logic lives here -- this only reads
values Developer 1's services already wrote.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from db.database import SessionLocal
from db.models import Anomaly, Incident

router = APIRouter(tags=["predictions"])

ACTIVE_INCIDENT_STATUSES = ("open", "acknowledged")

# Below this, a node's latest reading isn't worth surfacing as a
# "detected anomaly" / forecast row -- it's just baseline jitter.
ANOMALY_SCORE_FLOOR = 0.4
FAILURE_PROBABILITY_FLOOR = 0.2


class AnomalyOut(BaseModel):
    id: int
    timestamp: str
    node_id: str
    anomaly_score: float
    severity: str


class PredictionOut(BaseModel):
    id: int
    node_id: str
    failure_probability: float
    eta_minutes: Optional[float]
    incident_id: Optional[int] = None
    status: str = "healthy"
    severity: str = "none"


def _severity(score: float) -> str:
    if score >= 0.7:
        return "high"
    if score >= ANOMALY_SCORE_FLOOR:
        return "medium"
    return "low"


def _db_unavailable(exc: SQLAlchemyError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"error": f"Database unavailable: {exc.__class__.__name__}", "code": "DB_UNAVAILABLE"},
    )


def _latest_per_node(session) -> list[Anomaly]:
    """One row per node_id: its highest-id (== most recent) anomalies row."""
    latest_ids = select(func.max(Anomaly.id)).group_by(Anomaly.node_id).scalar_subquery()
    return session.scalars(select(Anomaly).where(Anomaly.id.in_(latest_ids))).all()


def _active_incidents_by_node(session, node_ids: list[str]) -> dict[str, Incident]:
    """Read-only: each node_id's open/acknowledged incident, if any. Exactly one per node_id per services/incident_manager.py's invariant."""
    if not node_ids:
        return {}
    rows = session.scalars(
        select(Incident).where(Incident.node_id.in_(node_ids), Incident.status.in_(ACTIVE_INCIDENT_STATUSES))
    ).all()
    return {row.node_id: row for row in rows}


@router.get("/anomalies", response_model=list[AnomalyOut])
def get_anomalies() -> list[AnomalyOut]:
    try:
        with SessionLocal() as session:
            rows = _latest_per_node(session)
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc

    surfaced = [row for row in rows if row.status == "open" or (row.anomaly_score or 0.0) >= ANOMALY_SCORE_FLOOR]
    surfaced.sort(key=lambda row: row.anomaly_score or 0.0, reverse=True)

    return [
        AnomalyOut(
            id=row.id,
            timestamp=row.detected_at.isoformat(),
            node_id=row.node_id,
            anomaly_score=row.anomaly_score or 0.0,
            severity=_severity(row.anomaly_score or 0.0),
        )
        for row in surfaced
    ]


@router.get("/predictions", response_model=list[PredictionOut])
def get_predictions() -> list[PredictionOut]:
    try:
        with SessionLocal() as session:
            rows = _latest_per_node(session)
            surfaced = [row for row in rows if (row.failure_probability or 0.0) >= FAILURE_PROBABILITY_FLOOR]
            incidents_by_node = _active_incidents_by_node(session, [row.node_id for row in surfaced])
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc

    surfaced.sort(key=lambda row: row.failure_probability or 0.0, reverse=True)

    result = []
    for row in surfaced:
        incident = incidents_by_node.get(row.node_id)
        result.append(
            PredictionOut(
                id=row.id,
                node_id=row.node_id,
                failure_probability=row.failure_probability or 0.0,
                eta_minutes=row.eta_minutes,
                incident_id=incident.id if incident else None,
                status=incident.status if incident else "healthy",
                severity=incident.severity if incident else "none",
            )
        )
    return result
