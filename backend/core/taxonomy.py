"""
core/taxonomy.py

Single source of truth for fault classification. Every other module
(fault injection, log generation, and later anomaly detection / HITL
recommendations) reads fault metadata from here rather than hardcoding
labels, mitigation actions, or confidence thresholds inline.

Pattern adapted from ankamteja/air-gapped-mpls-copilot's
phase3-models/taxonomy.py, trimmed to the 3 fault types in scope for
Day 1 plus a "healthy" baseline entry.
"""

from typing import Dict, List, TypedDict


class FaultInfo(TypedDict):
    id: str
    label: str
    display: str
    action: str
    critical: bool
    min_confidence: float


FAULTS: List[FaultInfo] = [
    {
        "id": "healthy",
        "label": "healthy",
        "display": "Healthy",
        "action": "none",
        "critical": False,
        "min_confidence": 0.0,
    },
    {
        "id": "bgp_flap",
        "label": "bgp_flap",
        "display": "BGP Route Flap",
        "action": "restart_bgp_session",
        "critical": True,
        "min_confidence": 0.75,
    },
    {
        "id": "high_cpu",
        "label": "high_cpu",
        "display": "High CPU Utilization",
        "action": "restart_process_or_scale",
        "critical": False,
        "min_confidence": 0.65,
    },
    {
        "id": "packet_loss",
        "label": "packet_loss",
        "display": "Packet Loss",
        "action": "reroute_traffic",
        "critical": True,
        "min_confidence": 0.70,
    },
]

ID_TO_INFO: Dict[str, FaultInfo] = {fault["id"]: fault for fault in FAULTS}
LABEL_TO_ID: Dict[str, str] = {fault["label"]: fault["id"] for fault in FAULTS}


def policy_for_action(fault_id: str) -> Dict:
    """
    Returns the mitigation policy for a fault id: the action to take,
    the minimum model confidence required before that action may be
    recommended, and whether the fault is critical (paged immediately)
    or not (queued for normal review).
    """
    info = ID_TO_INFO.get(fault_id)
    if info is None:
        raise KeyError(f"Unknown fault id: {fault_id!r}. Known ids: {sorted(ID_TO_INFO)}")
    return {
        "action": info["action"],
        "min_confidence": info["min_confidence"],
        "critical": info["critical"],
    }
