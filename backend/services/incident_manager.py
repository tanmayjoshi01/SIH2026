"""
services/incident_manager.py

Day 3: turns the per-tick anomaly_score stream services/anomaly_scoring_
service.py already writes into a persistent incident lifecycle:
    NORMAL -> ANOMALY DETECTED -> INCIDENT OPEN -> ESCALATING/ACTIVE
           -> ACKNOWLEDGED -> RESOLVED

Design choices, so the reasoning doesn't have to be reverse-engineered
later:

- No FK from incidents to anomalies. anomalies gets a row per (node, ~2s
  tick) -- a hot-path table Developer 2 also reads. An incident's
  contributing anomaly rows are found by time-range instead: node_id
  matches and detected_at falls between opened_at and (closed_at or
  now()). This is documented here as the query pattern rather than
  wiring a second FK-maintenance path into the tick loop.

- Exactly one open-or-acknowledged incident per node_id, enforced here in
  Python (not a DB constraint) by always looking up the node's current
  active row before deciding whether to open a new one or update it.

- Opening/resolving both require N *consecutive* ticks past
  ANOMALY_THRESHOLD (config.settings.incident_open_after_n_ticks /
  incident_resolve_after_n_ticks) so one noisy tick can't flip status.
  The consecutive-tick counters live in IncidentManager instance state
  (per node_id), not the DB -- there is exactly one IncidentManager per
  TelemetryGenerator/process, matching how FaultInjector already keeps
  its active_episodes in memory rather than in Postgres.

- Severity is derived only from the existing anomaly_score /
  failure_probability / contributing_signals / taxonomy fields -- never
  a second parallel severity model. A heuristic-sourced score
  (model_version == anomaly_scoring_service.HEURISTIC_MODEL_VERSION) is
  capped one severity level below what the raw score alone would imply,
  per the Day 3 planning-review correction, since it's a plain
  worst-metric/threshold ratio, not a learned score. An incident's
  severity only ever escalates within its lifetime (mirrors
  peak_anomaly_score) -- it reflects the worst the incident has been,
  not just its current tick.

- WebSocket fan-out uses a plain thread-safe queue.Queue per subscriber,
  filled from the telemetry tick's background thread and drained by each
  /ws/incidents connection via asyncio.to_thread(queue.get) on the
  FastAPI event loop. No asyncio object is touched from the tick thread,
  so there's no cross-loop call_soon_threadsafe plumbing to get wrong.
  Events are only ever broadcast *after* the triggering DB transaction
  commits (see simulation/telemetry_generator.py), so a client reacting
  to a WS push by immediately calling GET /api/incidents always finds
  the row already committed.
"""

from __future__ import annotations

import datetime as dt
import logging
import queue
import threading
from typing import Dict, List, Optional

from prometheus_client import REGISTRY
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from config import settings
from core.taxonomy import ID_TO_INFO
from db.database import SessionLocal
from db.models import Anomaly, Incident
from services import alerting
from services.anomaly_scoring_service import HEURISTIC_MODEL_VERSION

logger = logging.getLogger("incident_manager")

SEVERITY_LEVELS: List[str] = ["low", "medium", "high", "critical"]
ACTIVE_STATUSES = ("open", "acknowledged")

_subscribers: "set[queue.Queue]" = set()
_subscribers_lock = threading.Lock()


# --------------------------------------------------------------------------
# WebSocket fan-out (see module docstring for the threading design)
# --------------------------------------------------------------------------


def subscribe() -> "queue.Queue":
    q: "queue.Queue" = queue.Queue(maxsize=200)
    with _subscribers_lock:
        _subscribers.add(q)
    return q


def unsubscribe(q: "queue.Queue") -> None:
    with _subscribers_lock:
        _subscribers.discard(q)


def broadcast(event: dict) -> None:
    """Fans an already-built event dict out to every /ws/incidents subscriber. Never raises."""
    with _subscribers_lock:
        subscribers = list(_subscribers)
    for q in subscribers:
        try:
            q.put_nowait(event)
        except queue.Full:
            logger.warning("Dropping incident event for a slow /ws/incidents subscriber")


def serialize(incident: Incident) -> dict:
    return {
        "id": incident.id,
        "node_id": incident.node_id,
        "opened_at": incident.opened_at.isoformat() if incident.opened_at else None,
        "closed_at": incident.closed_at.isoformat() if incident.closed_at else None,
        "status": incident.status,
        "severity": incident.severity,
        "peak_anomaly_score": incident.peak_anomaly_score,
        "root_cause_signal": incident.root_cause_signal,
    }


def _event(event_type: str, incident: Incident) -> dict:
    return {"event": event_type, "incident": serialize(incident)}


# --------------------------------------------------------------------------
# Severity derivation
# --------------------------------------------------------------------------


def _severity_for_score(score: float, fault_type: str) -> str:
    fault_info = ID_TO_INFO.get(fault_type, ID_TO_INFO["healthy"])
    if (
        score >= settings.incident_critical_severity_threshold
        and fault_info["critical"]
        and score >= fault_info["min_confidence"]
    ):
        return "critical"
    if score >= settings.incident_high_severity_threshold:
        return "high"
    if score >= settings.incident_anomaly_threshold:
        return "medium"
    return "low"


def _severity_for_anomaly(anomaly: Anomaly) -> str:
    level = _severity_for_score(anomaly.anomaly_score or 0.0, anomaly.fault_type)
    if anomaly.model_version == HEURISTIC_MODEL_VERSION:
        level = SEVERITY_LEVELS[max(0, SEVERITY_LEVELS.index(level) - 1)]
    return level


def _root_cause_signal(anomaly: Anomaly) -> str:
    signals = anomaly.contributing_signals or []
    dominant = signals[0] if signals else f"{anomaly.fault_type} (score {anomaly.anomaly_score or 0.0:.2f})"
    if anomaly.model_version == HEURISTIC_MODEL_VERSION:
        dominant = f"{dominant} [heuristic score]"
    return dominant


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------


class IncidentManager:
    """
    Owns per-node consecutive-tick counters gating open/resolve. One
    instance lives on TelemetryGenerator (simulation/telemetry_generator.py),
    so its counters share that generator's lifetime -- a fresh process (or
    a fresh TelemetryGenerator in a test) starts every node at zero, same
    as FaultInjector.active_episodes.
    """

    def __init__(self) -> None:
        self._above: Dict[str, int] = {}
        self._below: Dict[str, int] = {}
        self._alerted_incident_ids: "set[int]" = set()

    def _active_incident(self, session: Session, node_id: str) -> Optional[Incident]:
        return session.scalars(
            select(Incident)
            .where(Incident.node_id == node_id, Incident.status.in_(ACTIVE_STATUSES))
            .order_by(Incident.id.desc())
        ).first()

    def process_tick(self, session: Session, node_id: str, anomaly: Anomaly) -> Optional[dict]:
        """
        Advances node_id's open/resolve counters from one freshly-scored
        (not yet committed) anomaly row, and opens/updates/resolves its
        incident row as needed. Returns a pending event dict to broadcast
        *after* the caller commits, or None if nothing changed this tick.
        """
        score = anomaly.anomaly_score or 0.0
        above = score >= settings.incident_anomaly_threshold
        if above:
            self._above[node_id] = self._above.get(node_id, 0) + 1
            self._below[node_id] = 0
        else:
            self._below[node_id] = self._below.get(node_id, 0) + 1
            self._above[node_id] = 0

        incident = self._active_incident(session, node_id)

        if incident is None:
            if above and self._above[node_id] >= settings.incident_open_after_n_ticks:
                return self._open_incident(session, node_id, anomaly)
            return None

        event = self._update_incident(incident, anomaly)

        if not above and self._below[node_id] >= settings.incident_resolve_after_n_ticks:
            return self._resolve_incident(incident)

        return event

    def _open_incident(self, session: Session, node_id: str, anomaly: Anomaly) -> dict:
        # Wall-clock "now", not anomaly.detected_at: that column is
        # server_default=func.now() and anomaly is still a pending
        # (unflushed) object at this point in the tick, so its Python
        # attribute may not reflect the eventual DB-assigned value.
        incident = Incident(
            node_id=node_id,
            opened_at=dt.datetime.now(dt.timezone.utc),
            status="open",
            severity=_severity_for_anomaly(anomaly),
            peak_anomaly_score=anomaly.anomaly_score or 0.0,
            root_cause_signal=_root_cause_signal(anomaly),
        )
        session.add(incident)
        session.flush()  # assigns incident.id for the event payload below
        logger.info(
            "Incident OPEN node=%s id=%s severity=%s score=%.3f",
            node_id, incident.id, incident.severity, incident.peak_anomaly_score,
        )
        return _event("OPEN", incident)

    def _update_incident(self, incident: Incident, anomaly: Anomaly) -> Optional[dict]:
        score = anomaly.anomaly_score or 0.0
        changed = False

        if score > incident.peak_anomaly_score:
            incident.peak_anomaly_score = score
            changed = True

        new_severity = _severity_for_anomaly(anomaly)
        if SEVERITY_LEVELS.index(new_severity) > SEVERITY_LEVELS.index(incident.severity):
            incident.severity = new_severity
            changed = True

        new_root_cause = _root_cause_signal(anomaly)
        if new_root_cause != incident.root_cause_signal:
            incident.root_cause_signal = new_root_cause
            changed = True

        if not changed:
            return None

        if incident.severity == "critical" and incident.id not in self._alerted_incident_ids:
            self._alerted_incident_ids.add(incident.id)
            alerting.send_critical_alert(incident)

        return _event("UPDATE", incident)

    def _resolve_incident(self, incident: Incident) -> dict:
        incident.status = "resolved"
        incident.closed_at = dt.datetime.now(dt.timezone.utc)
        self._alerted_incident_ids.discard(incident.id)
        logger.info("Incident RESOLVE node=%s id=%s", incident.node_id, incident.id)
        return _event("RESOLVE", incident)

    def resolve_all(self, session: Session) -> List[dict]:
        """
        Used by the simulation reset path (/api/simulation/reset is a
        full-graph reset, not a per-node one -- FaultInjector.reset()
        clears every active episode at once). Force-resolves *every*
        currently open/acknowledged incident, not just ones on nodes
        FaultInjector.reset() still considered "active": a fault episode
        can finish its ramp and self-clear from active_episodes (see
        FaultInjector.tick()) before its incident has decayed back below
        threshold, and a "reset simulation" click is expected to leave a
        clean board either way. Also clears every node's open/resolve
        tick counters, so the next fault on any node opens a brand-new
        incident rather than reusing stale counter state.
        """
        incidents = session.scalars(select(Incident).where(Incident.status.in_(ACTIVE_STATUSES))).all()
        events = [self._resolve_incident(incident) for incident in incidents]
        self._above.clear()
        self._below.clear()
        return events


def acknowledge_incident(session: Session, incident_id: int) -> Incident:
    """
    Sets status=acknowledged on an open/acknowledged incident. Raises
    LookupError if no such incident exists, or ValueError if it's already
    resolved -- routers/incidents.py maps these onto 404/400 respectively.
    Caller owns commit.
    """
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise LookupError(f"No incident with id={incident_id}")
    if incident.status == "resolved":
        raise ValueError(f"Incident {incident_id} is already resolved and cannot be acknowledged")
    if incident.status != "acknowledged":
        incident.status = "acknowledged"
        session.flush()
        broadcast(_event("UPDATE", incident))
    return incident


# --------------------------------------------------------------------------
# Prometheus: GET /metrics (main.py) -- extends the existing scrape with
# open-incident counts, computed fresh from Postgres on every scrape
# rather than mirrored from tick-thread state, so it can never drift.
# --------------------------------------------------------------------------


class _IncidentMetricsCollector:
    def collect(self):
        total = GaugeMetricFamily("noc_open_incidents_total", "Currently open or acknowledged incidents")
        by_severity = GaugeMetricFamily(
            "noc_open_incidents_by_severity",
            "Currently open or acknowledged incidents, by severity",
            labels=["severity"],
        )
        counts = {level: 0 for level in SEVERITY_LEVELS}
        try:
            with SessionLocal() as session:
                rows = session.execute(
                    select(Incident.severity, func.count())
                    .where(Incident.status.in_(ACTIVE_STATUSES))
                    .group_by(Incident.severity)
                ).all()
            for severity, count in rows:
                counts[severity] = counts.get(severity, 0) + count
        except SQLAlchemyError:
            logger.exception("Could not compute incident metrics for /metrics scrape")

        total.add_metric([], sum(counts.values()))
        for level in SEVERITY_LEVELS:
            by_severity.add_metric([level], counts[level])
        yield total
        yield by_severity


_metrics_registered = False


def register_metrics() -> None:
    """Idempotent: registers the incident gauges with the default Prometheus registry once per process."""
    global _metrics_registered
    if not _metrics_registered:
        REGISTRY.register(_IncidentMetricsCollector())
        _metrics_registered = True
