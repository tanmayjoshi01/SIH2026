"""
routers/predictions.py

STUB (Day 1). Fixed anomaly and prediction payloads in the shapes the
Day 2 scikit-learn detector/forecaster will emit. No model is loaded and
no detection runs here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

router = APIRouter(tags=["predictions"])


def _stamp(seconds_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


@router.get("/anomalies")
def get_anomalies() -> list[dict]:
    return [
        {"id": 1, "timestamp": _stamp(45), "node_id": "router-7", "anomaly_score": 0.87, "severity": "high"},
        {"id": 2, "timestamp": _stamp(120), "node_id": "switch-3", "anomaly_score": 0.54, "severity": "medium"},
        {"id": 3, "timestamp": _stamp(310), "node_id": "gs-1", "anomaly_score": 0.21, "severity": "low"},
    ]


@router.get("/predictions")
def get_predictions() -> list[dict]:
    return [
        {"id": 1, "node_id": "router-7", "failure_probability": 0.74, "eta_minutes": 12},
        {"id": 2, "node_id": "switch-3", "failure_probability": 0.38, "eta_minutes": 47},
    ]
