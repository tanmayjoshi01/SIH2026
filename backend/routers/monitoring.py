"""
routers/monitoring.py

Read-only endpoints over Developer 1's existing schema (db/models.py).
No models are declared here -- the ORM classes are imported as-is and the
internal column names are mapped onto the agreed API contract in the
Pydantic response schemas below (e.g. Link.source_id -> source_node_id).

Every handler surfaces a real database failure as HTTP 503 with the
{"error", "code"} envelope rather than an empty 200, so the UI can show a
visible error state instead of a silently blank panel.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from db.database import SessionLocal
from db.models import Link, Node, TelemetryLog
from config import settings

router = APIRouter(tags=["monitoring"])


# --------------------------------------------------------------------------
# Response contracts
# --------------------------------------------------------------------------


class NodeOut(BaseModel):
    id: str
    name: str
    type: str
    status: str
    cpu: float
    memory: float
    packet_loss: float
    latency_ms: float


class LinkOut(BaseModel):
    id: str
    source_node_id: str
    destination_node_id: str
    status: str


class TopologyOut(BaseModel):
    nodes: list[NodeOut]
    links: list[LinkOut]


class TelemetryOut(BaseModel):
    timestamp: str
    node_id: str
    metric_name: str
    value: float


class HealthScoreOut(BaseModel):
    overall_pct: float
    active_alerts: int


def _to_node_out(row: Node) -> NodeOut:
    return NodeOut(
        id=row.id,
        name=row.name,
        type=row.type,
        status=row.status,
        cpu=row.cpu,
        memory=row.memory,
        packet_loss=row.packet_loss,
        latency_ms=row.latency_ms,
    )


def _to_link_out(row: Link) -> LinkOut:
    # The table uses integer ids and source_id/target_id; the API contract
    # uses string ids and source_node_id/destination_node_id.
    return LinkOut(
        id=str(row.id),
        source_node_id=row.source_id,
        destination_node_id=row.target_id,
        status=row.status,
    )


def _db_unavailable(exc: SQLAlchemyError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"error": f"Database unavailable: {exc.__class__.__name__}", "code": "DB_UNAVAILABLE"},
    )


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@router.get("/nodes", response_model=list[NodeOut])
def get_nodes() -> list[NodeOut]:
    try:
        with SessionLocal() as session:
            rows = session.scalars(select(Node).order_by(Node.id)).all()
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc
    return [_to_node_out(row) for row in rows]


@router.get("/links", response_model=list[LinkOut])
def get_links() -> list[LinkOut]:
    try:
        with SessionLocal() as session:
            rows = session.scalars(select(Link).order_by(Link.id)).all()
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc
    return [_to_link_out(row) for row in rows]


@router.get("/topology", response_model=TopologyOut)
def get_topology() -> TopologyOut:
    try:
        with SessionLocal() as session:
            nodes = session.scalars(select(Node).order_by(Node.id)).all()
            links = session.scalars(select(Link).order_by(Link.id)).all()
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc
    return TopologyOut(
        nodes=[_to_node_out(row) for row in nodes],
        links=[_to_link_out(row) for row in links],
    )


@router.get("/telemetry", response_model=list[TelemetryOut])
def get_telemetry(
    node_id: Optional[str] = Query(default=None, description="Filter to a single node id"),
    since: Optional[str] = Query(default=None, description="ISO-8601 timestamp; only rows strictly newer are returned"),
    limit: int = Query(default=settings.telemetry_default_limit, ge=1, le=settings.telemetry_max_limit),
) -> list[TelemetryOut]:
    """Most-recent-first telemetry rows, used by the live AnomalyFeed poller."""
    since_dt: Optional[dt.datetime] = None
    if since:
        try:
            since_dt = dt.datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"error": f"Invalid 'since' timestamp: {since!r}. Expected ISO-8601.", "code": "INVALID_SINCE"},
            ) from exc
        if since_dt.tzinfo is None:
            since_dt = since_dt.replace(tzinfo=dt.timezone.utc)

    statement = select(TelemetryLog)
    if node_id:
        statement = statement.where(TelemetryLog.node_id == node_id)
    if since_dt is not None:
        statement = statement.where(TelemetryLog.timestamp > since_dt)
    statement = statement.order_by(TelemetryLog.timestamp.desc(), TelemetryLog.id.desc()).limit(limit)

    try:
        with SessionLocal() as session:
            rows = session.scalars(statement).all()
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc

    return [
        TelemetryOut(
            timestamp=row.timestamp.isoformat(),
            node_id=row.node_id,
            metric_name=row.metric_name,
            value=row.value,
        )
        for row in rows
    ]


@router.get("/health-score", response_model=HealthScoreOut)
def get_health_score() -> HealthScoreOut:
    """
    Aggregate over the nodes table: the share of nodes currently reporting
    "healthy", and how many are not. Purely a SQL rollup of the status
    column the telemetry generator maintains -- no anomaly detection here.
    """
    try:
        with SessionLocal() as session:
            total = session.scalar(select(func.count()).select_from(Node)) or 0
            unhealthy = (
                session.scalar(select(func.count()).select_from(Node).where(Node.status != "healthy")) or 0
            )
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc

    overall_pct = round(100.0 * (total - unhealthy) / total, 1) if total else 0.0
    return HealthScoreOut(overall_pct=overall_pct, active_alerts=int(unhealthy))
