"""
simulation/fault_profiles.py

Ramp functions for the 3 in-scope fault types (bgp_flap, high_cpu,
packet_loss). Each profile ramps a set of metrics from baseline to a
peak value and back down to baseline over a 20-40 real-second episode,
so a manual fault_injector.inject() call produces a visible rise and
recovery rather than an instant step change.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List

MIN_DURATION_SECONDS = 20.0
MAX_DURATION_SECONDS = 40.0
RAMP_UP_FRACTION = 0.55  # fraction of the episode spent climbing to peak; the rest is recovery


@dataclass(frozen=True)
class MetricRamp:
    metric_name: str
    subsystem: str
    unit: str
    baseline: float
    peak: float
    warning_threshold: float
    critical_threshold: float


@dataclass
class FaultProfile:
    fault_id: str
    duration_seconds: float
    ramp_up_fraction: float
    metrics: List[MetricRamp]

    def sample(self, elapsed_seconds: float) -> Dict[str, float]:
        """Returns each metric's value at the given elapsed time using a linear ramp-up-then-recover shape."""
        t = max(0.0, min(elapsed_seconds, self.duration_seconds))
        ramp_up_end = self.duration_seconds * self.ramp_up_fraction

        values: Dict[str, float] = {}
        for metric in self.metrics:
            if t <= ramp_up_end:
                frac = (t / ramp_up_end) if ramp_up_end > 0 else 1.0
                value = metric.baseline + (metric.peak - metric.baseline) * frac
            else:
                ramp_down_span = self.duration_seconds - ramp_up_end
                frac = ((t - ramp_up_end) / ramp_down_span) if ramp_down_span > 0 else 1.0
                value = metric.peak + (metric.baseline - metric.peak) * frac
            values[metric.metric_name] = round(value, 2)
        return values

    def is_complete(self, elapsed_seconds: float) -> bool:
        return elapsed_seconds >= self.duration_seconds


def _duration() -> float:
    return round(random.uniform(MIN_DURATION_SECONDS, MAX_DURATION_SECONDS), 1)


def _bgp_flap() -> FaultProfile:
    return FaultProfile(
        fault_id="bgp_flap",
        duration_seconds=_duration(),
        ramp_up_fraction=RAMP_UP_FRACTION,
        metrics=[
            MetricRamp("bgp_flap_count", "bgp", "flaps", baseline=0, peak=14, warning_threshold=3, critical_threshold=8),
            MetricRamp("packet_loss", "network", "percent", baseline=0.2, peak=9.0, warning_threshold=2.0, critical_threshold=5.0),
            MetricRamp("latency_ms", "network", "ms", baseline=8.0, peak=48.0, warning_threshold=20.0, critical_threshold=35.0),
        ],
    )


def _high_cpu() -> FaultProfile:
    return FaultProfile(
        fault_id="high_cpu",
        duration_seconds=_duration(),
        ramp_up_fraction=RAMP_UP_FRACTION,
        metrics=[
            MetricRamp("cpu", "compute", "percent", baseline=28.0, peak=97.0, warning_threshold=70.0, critical_threshold=90.0),
            MetricRamp("memory", "compute", "percent", baseline=38.0, peak=72.0, warning_threshold=60.0, critical_threshold=68.0),
        ],
    )


def _packet_loss() -> FaultProfile:
    return FaultProfile(
        fault_id="packet_loss",
        duration_seconds=_duration(),
        ramp_up_fraction=RAMP_UP_FRACTION,
        metrics=[
            MetricRamp("packet_loss", "network", "percent", baseline=0.3, peak=23.0, warning_threshold=5.0, critical_threshold=15.0),
            MetricRamp("interface_errors", "network", "count", baseline=0, peak=140, warning_threshold=30, critical_threshold=90),
            MetricRamp("latency_ms", "network", "ms", baseline=9.0, peak=55.0, warning_threshold=25.0, critical_threshold=40.0),
        ],
    )


_BUILDERS = {
    "bgp_flap": _bgp_flap,
    "high_cpu": _high_cpu,
    "packet_loss": _packet_loss,
}


def build_profile(fault_id: str) -> FaultProfile:
    builder = _BUILDERS.get(fault_id)
    if builder is None:
        raise ValueError(f"Unknown fault_id: {fault_id!r}. Known: {sorted(_BUILDERS)}")
    return builder()
