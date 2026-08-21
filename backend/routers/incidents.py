"""
routers/incidents.py

Day 3: REST + WebSocket surface over the `incidents` table services/
incident_manager.py owns. Two router objects, mounted differently in
main.py:
  - `router`   -- REST, mounted under settings.api_prefix ("/api"), so
                  endpoints land at /api/incidents and
                  /api/incidents/{id}/acknowledge.
  - `ws_router` -- the /ws/incidents WebSocket, mounted with no prefix
                  (the Day 3 brief specifies that exact path, not
                  /api/ws/incidents).

An incident's contributing anomaly rows are a time-range query, not a
foreign key -- node_id matches and detected_at falls between opened_at
and (closed_at or now()). See services/incident_manager.py's module
docstring for why.
"""

from __future__ import annotations

import asyncio
import logging
import queue
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.websockets import WebSocketState

from db.database import SessionLocal
from db.models import Incident
from services import incident_manager

logger = logging.getLogger("incidents_router")

router = APIRouter(prefix="/incidents", tags=["incidents"])
ws_router = APIRouter()

# How often the /ws/incidents loop wakes from its blocking queue.get() to
# check the connection is still alive. See ws_incidents()'s docstring for
# why this is needed at all.
WS_LIVENESS_CHECK_SECONDS = 10.0


class IncidentOut(BaseModel):
    id: int
    node_id: str
    opened_at: str
    closed_at: Optional[str]
    status: str
    severity: str
    peak_anomaly_score: float
    root_cause_signal: Optional[str]


def _to_incident_out(row: Incident) -> IncidentOut:
    return IncidentOut(
        id=row.id,
        node_id=row.node_id,
        opened_at=row.opened_at.isoformat() if row.opened_at else None,
        closed_at=row.closed_at.isoformat() if row.closed_at else None,
        status=row.status,
        severity=row.severity,
        peak_anomaly_score=row.peak_anomaly_score,
        root_cause_signal=row.root_cause_signal,
    )


def _db_unavailable(exc: SQLAlchemyError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"error": f"Database unavailable: {exc.__class__.__name__}", "code": "DB_UNAVAILABLE"},
    )


@router.get("", response_model=list[IncidentOut])
def get_incidents(
    status: Optional[str] = Query(default=None, description="Filter by status: open|acknowledged|resolved"),
    node_id: Optional[str] = Query(default=None, description="Filter to a single node id"),
) -> list[IncidentOut]:
    statement = select(Incident)
    if status:
        statement = statement.where(Incident.status == status)
    if node_id:
        statement = statement.where(Incident.node_id == node_id)
    statement = statement.order_by(Incident.opened_at.desc(), Incident.id.desc())

    try:
        with SessionLocal() as session:
            rows = session.scalars(statement).all()
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc

    return [_to_incident_out(row) for row in rows]


@router.post("/{incident_id}/acknowledge", response_model=IncidentOut)
def acknowledge_incident(incident_id: int) -> IncidentOut:
    try:
        with SessionLocal() as session:
            try:
                incident = incident_manager.acknowledge_incident(session, incident_id)
            except LookupError as exc:
                raise HTTPException(
                    status_code=404,
                    detail={"error": str(exc), "code": "INCIDENT_NOT_FOUND"},
                ) from exc
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail={"error": str(exc), "code": "INCIDENT_ALREADY_RESOLVED"},
                ) from exc
            session.commit()
            session.refresh(incident)
            result = _to_incident_out(incident)
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc

    return result


@ws_router.websocket("/ws/incidents")
async def ws_incidents(websocket: WebSocket) -> None:
    """
    Pushes {"event": "OPEN"|"UPDATE"|"RESOLVE", "incident": {...}} as they
    happen. Best-effort: if this connection can't keep up or drops, the
    REST endpoint above remains the source of truth (polling still works).

    We never call websocket.receive(), so nothing here observes a client
    that vanishes without a clean close handshake (a killed tab, a dropped
    Wi-Fi connection, etc.) -- a plain `await asyncio.to_thread(queue.get)`
    would then block forever, permanently pinning both this connection's
    subscriber queue in incident_manager and a thread-pool worker thread
    for the rest of the process's life. Found under Day 4 stress testing
    (repeated connect/kill/reconnect cycles). Fixed by polling get() with
    a timeout and checking websocket.client_state each time it's empty,
    so a dead peer is reclaimed within WS_LIVENESS_CHECK_SECONDS instead
    of leaking indefinitely.
    """
    await websocket.accept()
    subscriber_queue = incident_manager.subscribe()
    try:
        while True:
            try:
                event = await asyncio.to_thread(subscriber_queue.get, True, WS_LIVENESS_CHECK_SECONDS)
            except queue.Empty:
                if websocket.client_state != WebSocketState.CONNECTED:
                    break
                continue
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Unexpected error on /ws/incidents connection; closing")
    finally:
        incident_manager.unsubscribe(subscriber_queue)
