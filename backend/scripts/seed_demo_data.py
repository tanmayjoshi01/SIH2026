"""
scripts/seed_demo_data.py

Bootstraps every one of the 8 tables with realistic sample rows so
Developer 2 can build the FastAPI/React UI against real-shaped data
before the live generator loop is wired into the app. Safe to re-run:
it clears its own tables first (in FK-safe order) rather than
requiring a manual database edit between runs.

Run:
    python backend/scripts/seed_demo_data.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import func, select

from core.taxonomy import FAULTS
from db.database import SessionLocal, init_db
from db.models import (
    Anomaly,
    AuditLog,
    FaultEvent,
    Link,
    Node,
    Operator,
    Recommendation,
    TelemetryLog,
)
from simulation.topology_def import build_topology

ALL_MODELS = [Node, Link, TelemetryLog, FaultEvent, Anomaly, Recommendation, Operator, AuditLog]


def _clear_tables(session) -> None:
    # Reverse FK-dependency order so child rows are removed before parents.
    for model in [AuditLog, Recommendation, Anomaly, FaultEvent, TelemetryLog, Link, Operator, Node]:
        session.query(model).delete()
    session.commit()


def seed() -> None:
    init_db()
    graph = build_topology()
    now = datetime.now(timezone.utc)

    with SessionLocal() as session:
        _clear_tables(session)

        for node_id, data in graph.nodes(data=True):
            session.add(
                Node(
                    id=node_id,
                    name=data["name"],
                    type=data["type"],
                    status=data["status"],
                    cpu=data["cpu"],
                    memory=data["memory"],
                    packet_loss=data["packet_loss"],
                    latency_ms=data["latency_ms"],
                    interface_errors=data["interface_errors"],
                    bgp_flap_count=data["bgp_flap_count"],
                    node_metadata=data.get("metadata", {}),
                )
            )
        session.flush()  # nodes must exist before links/telemetry_logs/fault_events reference them by FK

        for source, target, data in graph.edges(data=True):
            session.add(
                Link(
                    source_id=source,
                    target_id=target,
                    link_type=data["link_type"],
                    bandwidth_mbps=data["bandwidth_mbps"],
                    status=data["status"],
                )
            )

        sample_node = "router-7"
        for i in range(5):
            session.add(
                TelemetryLog(
                    timestamp=now - timedelta(seconds=(5 - i) * 2),
                    node_id=sample_node,
                    subsystem="compute",
                    metric_name="cpu",
                    value=30.0 + i * 2,
                    unit="percent",
                    raw_log_line=None,
                )
            )

        fault_event = FaultEvent(
            node_id=sample_node,
            fault_type="bgp_flap",
            started_at=now - timedelta(minutes=5),
            ended_at=now - timedelta(minutes=4, seconds=30),
            status="resolved",
            triggered_by="manual",
        )
        session.add(fault_event)
        session.flush()  # populate fault_event.id for the FK below

        anomaly = Anomaly(
            node_id=sample_node,
            fault_event_id=fault_event.id,
            fault_type="bgp_flap",
            confidence=0.82,
            detected_at=now - timedelta(minutes=4, seconds=50),
            status="open",
        )
        session.add(anomaly)
        session.flush()  # populate anomaly.id for the FK below

        bgp_flap_action = next(fault["action"] for fault in FAULTS if fault["id"] == "bgp_flap")
        session.add(
            Recommendation(
                anomaly_id=anomaly.id,
                action=bgp_flap_action,
                confidence=0.82,
                status="pending",
            )
        )

        operator = Operator(username="demo_operator", role="noc_operator")
        session.add(operator)
        session.flush()  # populate operator.id for the FK below

        session.add(
            AuditLog(
                operator_id=operator.id,
                action="seed_demo_data",
                target="database",
                details={"note": "initial demo load"},
                prev_hash=None,
                hash=None,
            )
        )

        session.commit()

    _print_summary()


def _print_summary() -> None:
    with SessionLocal() as session:
        for model in ALL_MODELS:
            count = session.scalar(select(func.count()).select_from(model))
            print(f"{model.__tablename__:16s}: {count} rows")


if __name__ == "__main__":
    seed()
