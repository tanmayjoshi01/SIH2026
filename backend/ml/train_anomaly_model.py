"""
ml/train_anomaly_model.py

Offline training script (run once, by hand): builds a synthetic dataset
of healthy-jitter and fault-episode telemetry windows using this
project's OWN simulation code -- topology_def.py's per-type baselines,
the same per-tick jitter telemetry_generator.py applies to healthy
nodes, and fault_profiles.py's ramp functions for the 3 in-scope fault
types -- never hand-labeled data. Fits a scikit-learn IsolationForest on
the healthy windows only, so the model learns what normal jitter looks
like and anything outside that shape scores as anomalous. Fault
episodes are held out purely for the sanity-check report below; they
are never used to fit the model.

This ships a REAL trained classifier (isolation_forest_v1). See
services/anomaly_scoring_service.py for the heuristic_v1 fallback it
uses if this script hasn't been run yet / the .pkl is missing.

Run:
    python backend/ml/train_anomaly_model.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Dict, List, Tuple

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import classification_report

from ml.feature_engineering import FEATURE_NAMES, METRICS, WINDOW_SIZE, compute_features
from simulation.fault_profiles import build_profile
from simulation.log_templates import classify_band
from simulation.topology_def import BASELINES

RANDOM_SEED = 42
TICK_SECONDS = 2.0  # mirrors simulation/telemetry_generator.py's TICK_SECONDS
ANOMALY_SCORE_THRESHOLD = 0.5

MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_PATH = MODEL_DIR / "anomaly_isolation_forest.pkl"
MODEL_VERSION = "isolation_forest_v1"

# The 4 metrics build_topology() seeds identically for every node type,
# regardless of node type (only cpu/memory vary -- see topology_def.BASELINES).
GENERIC_BASELINE = {"packet_loss": 0.2, "latency_ms": 8.0, "interface_errors": 0.0, "bgp_flap_count": 0.0}

# Mirrors simulation/telemetry_generator.py's JITTER dict so synthetic
# healthy sequences have the same shape the live generator actually produces.
JITTER = {"cpu": 1.5, "memory": 1.0, "packet_loss": 0.1, "latency_ms": 0.5, "interface_errors": 0.0, "bgp_flap_count": 0.0}

HEALTHY_RUNS_PER_NODE_TYPE = 6
HEALTHY_TICKS_PER_RUN = 60
FAULT_EPISODES_PER_TYPE = 15


def _healthy_sequence(baseline: Dict[str, float], n_ticks: int, rng: random.Random) -> List[Dict[str, float]]:
    values = dict(baseline)
    sequence = []
    for _ in range(n_ticks):
        tick = {}
        for metric, spread in JITTER.items():
            delta = rng.uniform(-spread, spread) if spread else 0.0
            values[metric] = max(0.0, round(values[metric] + delta, 2))
            tick[metric] = values[metric]
        sequence.append(tick)
    return sequence


def _fault_sequence(fault_id: str, rng: random.Random) -> Tuple[List[Dict[str, float]], List[bool]]:
    """Samples a fault profile every TICK_SECONDS until it completes; returns (sequence, is_anomalous_tick)."""
    profile = build_profile(fault_id)
    values = dict(GENERIC_BASELINE)
    sequence = []
    labels = []
    n_ticks = int(profile.duration_seconds // TICK_SECONDS) + 1
    for i in range(n_ticks):
        elapsed = i * TICK_SECONDS
        sampled = profile.sample(elapsed)
        tick = dict(values)
        tick.update(sampled)
        # small jitter on metrics this profile doesn't touch, so they're not perfectly flat
        for metric, spread in JITTER.items():
            if metric in sampled:
                continue
            delta = rng.uniform(-spread, spread) if spread else 0.0
            tick[metric] = max(0.0, round(tick.get(metric, 0.0) + delta, 2))
        values = tick
        sequence.append(tick)
        labels.append(
            any(
                classify_band(sampled[m.metric_name], m.warning_threshold, m.critical_threshold) != "normal"
                for m in profile.metrics
            )
        )
    return sequence, labels


def _windows_from_sequence(sequence: List[Dict[str, float]]) -> List[Dict[str, List[float]]]:
    """Slides a WINDOW_SIZE lookback across a chronological sequence of tick readings."""
    history: Dict[str, List[float]] = {m: [] for m in METRICS}
    windows = []
    for tick in sequence:
        for metric in METRICS:
            history[metric].append(tick.get(metric, 0.0))
            history[metric] = history[metric][-WINDOW_SIZE:]
        windows.append({m: list(v) for m, v in history.items()})
    return windows


def build_dataset(rng: random.Random) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    healthy_features = []
    for node_type, baseline in BASELINES.items():
        full_baseline = {**GENERIC_BASELINE, **baseline}
        for _ in range(HEALTHY_RUNS_PER_NODE_TYPE):
            seq = _healthy_sequence(full_baseline, n_ticks=HEALTHY_TICKS_PER_RUN, rng=rng)
            for window in _windows_from_sequence(seq):
                healthy_features.append(compute_features(window))

    fault_features = []
    fault_labels = []
    for fault_id in ("bgp_flap", "high_cpu", "packet_loss"):
        for _ in range(FAULT_EPISODES_PER_TYPE):
            seq, labels = _fault_sequence(fault_id, rng)
            for window, label in zip(_windows_from_sequence(seq), labels):
                fault_features.append(compute_features(window))
                fault_labels.append(label)

    return np.array(healthy_features), np.array(fault_features), np.array(fault_labels)


def main() -> None:
    rng = random.Random(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    healthy_X, fault_X, fault_labels = build_dataset(rng)
    print(f"Healthy training windows: {healthy_X.shape[0]} (feature dim={healthy_X.shape[1]})")
    print(f"Held-out fault-episode windows: {fault_X.shape[0]} ({int(fault_labels.sum())} labeled warning/critical)")

    model = IsolationForest(n_estimators=200, contamination=0.05, random_state=RANDOM_SEED)
    model.fit(healthy_X)

    # sklearn convention: score_samples is high for normal points, low for
    # anomalies. Flip the sign and min-max normalize against the score
    # range actually observed this run so live scores land in [0,1] with
    # 1 = most anomalous.
    raw_healthy = -model.score_samples(healthy_X)
    raw_fault = -model.score_samples(fault_X)
    raw_min = float(min(raw_healthy.min(), raw_fault.min()))
    raw_max = float(max(raw_healthy.max(), raw_fault.max()))

    def to_score(raw: np.ndarray) -> np.ndarray:
        return np.clip((raw - raw_min) / (raw_max - raw_min + 1e-9), 0.0, 1.0)

    healthy_scores = to_score(raw_healthy)
    fault_scores = to_score(raw_fault)
    predicted = (fault_scores >= ANOMALY_SCORE_THRESHOLD).astype(int)

    print("\n--- Sanity check (held-out synthetic data, never used to fit the model) ---")
    print(f"Max anomaly_score seen during healthy jitter: {healthy_scores.max():.3f} (threshold={ANOMALY_SCORE_THRESHOLD})")
    print(f"False-positive rate on healthy windows @ threshold {ANOMALY_SCORE_THRESHOLD}: {(healthy_scores >= ANOMALY_SCORE_THRESHOLD).mean():.3%}")
    print(
        classification_report(
            fault_labels,
            predicted,
            target_names=["normal_band", "warning_or_critical_band"],
            zero_division=0,
        )
    )

    print("--- Per-fault-type detection latency (one representative episode each) ---")
    for fault_id in ("bgp_flap", "high_cpu", "packet_loss"):
        seq, labels = _fault_sequence(fault_id, rng)
        windows = _windows_from_sequence(seq)
        scores = to_score(-model.score_samples(np.array([compute_features(w) for w in windows])))
        first_anomalous_tick = next((i for i, is_anom in enumerate(labels) if is_anom), None)
        first_detected_tick = next((i for i, s in enumerate(scores) if s >= ANOMALY_SCORE_THRESHOLD), None)
        print(
            f"{fault_id:12s}: first warning/critical tick={first_anomalous_tick}  "
            f"first anomaly_score>={ANOMALY_SCORE_THRESHOLD} tick={first_detected_tick}  "
            f"episode_len={len(seq)} ticks"
        )

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "raw_min": raw_min,
            "raw_max": raw_max,
            "feature_names": FEATURE_NAMES,
            "metrics": METRICS,
            "window_size": WINDOW_SIZE,
            "version": MODEL_VERSION,
        },
        MODEL_PATH,
    )
    print(f"\nSaved {MODEL_VERSION} to {MODEL_PATH}")


if __name__ == "__main__":
    main()
