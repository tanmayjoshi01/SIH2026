"""
services/anomaly_scoring_service.py

Day 2 scoring: turns a node's recent telemetry_logs window into one
`anomalies` row carrying anomaly_score, failure_probability, eta_minutes,
contributing_signals and model_version -- on the SAME row the existing
detection fields (fault_type, confidence, status) already use, per the
Day 2 data contract of one row per (node, scoring_tick).

Two scoring paths, chosen automatically each call:
  - isolation_forest_v1: the trained model ml/train_anomaly_model.py
    saves to ml/models/anomaly_isolation_forest.pkl, if present.
  - heuristic_v1: a plain "how close is the worst metric to its critical
    threshold" ratio, used only if that .pkl is missing (e.g. training
    hasn't been run yet) so the live loop never crashes for lack of a
    model file. This is NOT a learned anomaly score -- it is literally
    the same ratio failure_probability uses. Never presented as the
    trained classifier; model_version always says which path produced
    a given row.

fault_type/confidence are populated from the simulation's own
ground-truth (which fault, if any, is currently injected on this node)
since Day 2 ships unsupervised anomaly detection, not a fault-type
classifier -- there is no model here deciding WHICH fault this is, only
how anomalous/how failure-prone the node's telemetry currently looks.

A scoring failure for one node/tick is caught, logged, and skipped here
-- the same "log and skip" pattern telemetry_generator.py already uses
for DB writes -- so one bad node never kills the tick loop.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

import joblib
import numpy as np
from sqlalchemy.orm import Session

from core.taxonomy import ID_TO_INFO
from db.models import Anomaly
from ml.feature_engineering import METRICS, compute_features, fetch_window
from simulation.fault_profiles import build_profile

logger = logging.getLogger("anomaly_scoring_service")

TICK_SECONDS = 2.0  # mirrors simulation/telemetry_generator.py's TICK_SECONDS
CONTRIBUTING_SIGNAL_TOP_N = 3
CONTRIBUTING_SIGNAL_MIN_PCT = 5.0  # ignore sub-noise moves
HEURISTIC_MODEL_VERSION = "heuristic_v1"

_MODEL_PATH = Path(__file__).resolve().parents[1] / "ml" / "models" / "anomaly_isolation_forest.pkl"
_model_artifact: Optional[dict] = None
_model_load_attempted = False


def _canonical_critical_thresholds() -> Dict[str, float]:
    """
    Per metric, the most conservative (lowest) critical_threshold defined
    across the 3 fault_profiles.py profiles that touch it. Sourced from
    fault_profiles.py rather than a second hardcoded set of thresholds,
    per the Day 2 brief.
    """
    thresholds: Dict[str, float] = {}
    for fault_id in ("bgp_flap", "high_cpu", "packet_loss"):
        for metric in build_profile(fault_id).metrics:
            current = thresholds.get(metric.metric_name)
            if current is None or metric.critical_threshold < current:
                thresholds[metric.metric_name] = metric.critical_threshold
    return thresholds


CRITICAL_THRESHOLDS: Dict[str, float] = _canonical_critical_thresholds()


def _load_model() -> Optional[dict]:
    """Lazily loads and caches the trained model artifact; None if it hasn't been trained yet."""
    global _model_artifact, _model_load_attempted
    if _model_load_attempted:
        return _model_artifact
    _model_load_attempted = True
    if _MODEL_PATH.exists():
        try:
            _model_artifact = joblib.load(_MODEL_PATH)
            logger.info("Loaded anomaly model %s from %s", _model_artifact.get("version"), _MODEL_PATH)
        except Exception:
            logger.exception("Failed to load anomaly model at %s; falling back to %s", _MODEL_PATH, HEURISTIC_MODEL_VERSION)
            _model_artifact = None
    else:
        logger.warning("No trained model at %s yet; scoring with %s until train_anomaly_model.py is run", _MODEL_PATH, HEURISTIC_MODEL_VERSION)
    return _model_artifact


def _isolation_forest_score(artifact: dict, window: Dict[str, List[float]]) -> float:
    features = compute_features(window).reshape(1, -1)
    raw = float(-artifact["model"].score_samples(features)[0])
    span = artifact["raw_max"] - artifact["raw_min"]
    if span <= 0:
        return 0.0
    return float(np.clip((raw - artifact["raw_min"]) / span, 0.0, 1.0))


def _worst_case_ratio(window: Dict[str, List[float]]) -> float:
    """How close the node's worst metric currently is to its critical threshold, clipped to [0,1]."""
    ratios = []
    for metric in METRICS:
        threshold = CRITICAL_THRESHOLDS.get(metric)
        values = window.get(metric)
        if not threshold or not values:
            continue
        ratios.append(max(0.0, values[-1]) / threshold)
    return float(min(1.0, max(ratios))) if ratios else 0.0


def _eta_minutes(window: Dict[str, List[float]]) -> Optional[float]:
    """
    Linear extrapolation of the fastest-rising metric's most recent
    single-tick slope to its critical threshold. None if nothing in the
    window is currently rising toward its threshold.
    """
    best_eta: Optional[float] = None
    for metric in METRICS:
        threshold = CRITICAL_THRESHOLDS.get(metric)
        values = window.get(metric)
        if not threshold or not values or len(values) < 2:
            continue
        latest, previous = values[-1], values[-2]
        slope_per_tick = latest - previous
        if slope_per_tick <= 0:
            continue
        remaining = threshold - latest
        eta = 0.0 if remaining <= 0 else (remaining / slope_per_tick) * TICK_SECONDS / 60.0
        if best_eta is None or eta < best_eta:
            best_eta = eta
    return best_eta


def _contributing_signals(window: Dict[str, List[float]]) -> List[str]:
    """["cpu +34%", "packet_loss +12%"]-style summary of what moved most over the window."""
    moves = []
    for metric in METRICS:
        values = window.get(metric)
        if not values or len(values) < 2:
            continue
        first, last = values[0], values[-1]
        baseline = abs(first) if abs(first) > 1e-6 else 1.0
        pct = (last - first) / baseline * 100.0
        if abs(pct) >= CONTRIBUTING_SIGNAL_MIN_PCT:
            moves.append((abs(pct), f"{metric} {pct:+.0f}%"))
    moves.sort(key=lambda item: item[0], reverse=True)
    return [label for _, label in moves[:CONTRIBUTING_SIGNAL_TOP_N]]


def score_node(session: Session, node_id: str, active_fault_id: Optional[str]) -> Optional[Anomaly]:
    """
    Builds and stages (session.add -- the caller's tick owns commit) one
    anomalies row for node_id from its current telemetry_logs window.
    `active_fault_id` is the simulation's own ground truth for what's
    currently injected on this node, or None for a healthy node. Returns
    None (having logged) on any failure so one bad node never kills the
    tick loop.
    """
    try:
        window = fetch_window(session, node_id)
        artifact = _load_model()
        if artifact is not None:
            score = _isolation_forest_score(artifact, window)
            version = artifact["version"]
        else:
            score = _worst_case_ratio(window)
            version = HEURISTIC_MODEL_VERSION

        failure_probability = _worst_case_ratio(window)
        eta = _eta_minutes(window)
        signals = _contributing_signals(window)
        fault_type = active_fault_id if active_fault_id in ID_TO_INFO else "healthy"

        anomaly = Anomaly(
            node_id=node_id,
            fault_type=fault_type,
            confidence=round(score, 4),
            status="open" if active_fault_id else "resolved",
            anomaly_score=round(score, 4),
            failure_probability=round(failure_probability, 4),
            eta_minutes=round(eta, 2) if eta is not None else None,
            contributing_signals=signals,
            model_version=version,
        )
        session.add(anomaly)
        return anomaly
    except Exception:
        logger.exception("Anomaly scoring failed for node %s; skipping this tick", node_id)
        return None
