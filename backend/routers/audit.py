"""
routers/audit.py

STUB (Day 1). Fixed audit entries in the shape the Day 3 hash-chained
audit log will produce. The real implementation will read the audit_log
table and verify prev_hash/hash continuity; nothing is chained here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

router = APIRouter(tags=["audit"])


def _stamp(seconds_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


@router.get("/audit-logs")
def get_audit_logs() -> list[dict]:
    return [
        {
            "id": 3,
            "timestamp": _stamp(30),
            "event_type": "hitl_approved",
            "payload": {"operator": "demo_operator", "action": "restart_bgp_session", "target": "router-7"},
            "hash": "9f2c4b7d1ae05c83f6b90d2e4471aa6c5d3e8f01b2c7a94d6e0f3b85c1729dae",
        },
        {
            "id": 2,
            "timestamp": _stamp(95),
            "event_type": "recommendation_generated",
            "payload": {"anomaly_id": 1, "action": "restart_bgp_session", "confidence": 0.82},
            "hash": "4d81ea0c6b3f27519ac4de08b7f6215390cc7ea1b4d829f60537ea2cb9418d7f",
        },
        {
            "id": 1,
            "timestamp": _stamp(180),
            "event_type": "fault_injected",
            "payload": {"node_id": "router-7", "fault_type": "bgp_flap", "triggered_by": "manual"},
            "hash": "1a7bc93e5f2048d6ea3197c4b085f27d6e3a05198cf47b2d0916ae83c5d340f2b",
        },
    ]
