"""
ml/feature_engineering.py

Builds the feature vector anomaly_scoring_service.py feeds into the
Isolation Forest: for each of the 6 core telemetry metrics, the rolling
mean, rolling std, and first difference (latest - previous) over the
last WINDOW_SIZE telemetry_logs samples for a node.

Shared by both sides of the model:
  - the live scorer, which reads a window from telemetry_logs via
    fetch_window() (needs a DB session);
  - train_anomaly_model.py, which builds windows directly from
    fault_profiles.py's ramp functions and never touches the DB.
compute_features() is the pure function in the middle so both paths
produce identical vectors from identical inputs.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import TelemetryLog

# Order matters: it defines the feature vector's column order, and must
# match FEATURE_NAMES / what train_anomaly_model.py fits on.
METRICS: List[str] = ["cpu", "memory", "packet_loss", "latency_ms", "interface_errors", "bgp_flap_count"]
WINDOW_SIZE = 5

FEATURE_NAMES: List[str] = [f"{metric}_{stat}" for metric in METRICS for stat in ("mean", "std", "diff")]


def fetch_window(session: Session, node_id: str, window_size: int = WINDOW_SIZE) -> Dict[str, List[float]]:
    """Returns, per metric, the last `window_size` telemetry_logs values for node_id in chronological order."""
    window: Dict[str, List[float]] = {}
    for metric in METRICS:
        rows = session.scalars(
            select(TelemetryLog.value)
            .where(TelemetryLog.node_id == node_id, TelemetryLog.metric_name == metric)
            .order_by(TelemetryLog.timestamp.desc(), TelemetryLog.id.desc())
            .limit(window_size)
        ).all()
        window[metric] = list(reversed(rows))
    return window


def compute_features(window: Dict[str, List[float]]) -> np.ndarray:
    """
    Turns a metric -> chronological-values window into the flat feature
    vector matching FEATURE_NAMES. Metrics with fewer than 2 samples get
    std=0/diff=0 (nothing to compare yet) rather than raising, since a
    node early in its history has a short window.
    """
    features: List[float] = []
    for metric in METRICS:
        values = window.get(metric) or [0.0]
        arr = np.asarray(values[-WINDOW_SIZE:], dtype=float)
        mean = float(arr.mean())
        std = float(arr.std()) if arr.size > 1 else 0.0
        diff = float(arr[-1] - arr[-2]) if arr.size > 1 else 0.0
        features.extend([mean, std, diff])
    return np.array(features, dtype=float)
