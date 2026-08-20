"""
db/models.py

Full 8-table SQLAlchemy 2.0 schema for the NOC copilot data layer.
Only nodes, telemetry_logs, and links receive real writes on Day 1
(from telemetry_generator.py); fault_events, anomalies,
recommendations, operators, and audit_log are modeled now so the
schema is stable for Developer 2's UI and for Day 2/3 work, and are
populated with sample rows by scripts/seed_demo_data.py.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="healthy")
    cpu: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    memory: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    packet_loss: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    interface_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bgp_flap_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Python attribute can't be named `metadata` (reserved by DeclarativeBase);
    # the DB column is still literally named "metadata" per the data contract.
    node_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class Link(Base):
    __tablename__ = "links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(64), ForeignKey("nodes.id"), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), ForeignKey("nodes.id"), nullable=False)
    link_type: Mapped[str] = mapped_column(String(32), nullable=False, default="ethernet")
    bandwidth_mbps: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="up")


class TelemetryLog(Base):
    __tablename__ = "telemetry_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    node_id: Mapped[str] = mapped_column(String(64), ForeignKey("nodes.id"), nullable=False, index=True)
    subsystem: Mapped[str] = mapped_column(String(32), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_log_line: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class FaultEvent(Base):
    __tablename__ = "fault_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(String(64), ForeignKey("nodes.id"), nullable=False)
    fault_type: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ended_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    triggered_by: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")


class Anomaly(Base):
    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(String(64), ForeignKey("nodes.id"), nullable=False)
    fault_event_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("fault_events.id"), nullable=True)
    fault_type: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    detected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")

    # Day 2: populated by services/anomaly_scoring_service.py on the same
    # row as the detection fields above -- one row per (node, scoring
    # tick), not a separate table Developer 2's routers would need to join.
    anomaly_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    failure_probability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    eta_minutes: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    contributing_signals: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    model_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


class Incident(Base):
    __tablename__ = "incidents"

    # Day 3: the persistent incident lifecycle built on top of Day 2's
    # per-tick anomalies stream. Exactly one open/acknowledged row per
    # node_id at a time (enforced by services/incident_manager.py, not a
    # DB constraint, since "open" here means "not yet resolved" across
    # two possible statuses). Anomaly rows in an incident's active window
    # are found by time-range (node_id + detected_at between opened_at
    # and closed_at-or-now), not a foreign key -- see incident_manager.py
    # for why. Field names below are the Day 3 contract Developer 2's UI
    # builds against; do not rename.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(String(64), ForeignKey("nodes.id"), nullable=False, index=True)
    opened_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    peak_anomaly_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    root_cause_signal: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    anomaly_id: Mapped[int] = mapped_column(Integer, ForeignKey("anomalies.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Operator(Base):
    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="operator")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operator_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("operators.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    prev_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
