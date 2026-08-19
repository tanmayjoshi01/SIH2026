"""
simulation/log_templates.py

Deterministic syslog-style log lines produced when a metric crosses a
threshold band (normal -> warning -> critical, or back down to
"recovered"). Templates are keyed by (metric_name, band) and filled in
purely from the real computed metric value - never randomly generated
text - so the same inputs always produce the same log line.
"""

from __future__ import annotations

from typing import Optional

_THRESHOLD_TEMPLATES = {
    ("bgp_flap_count", "warning"): "%BGP-4-FLAP_WARN: {node}: BGP session to {neighbor} flapped {value:.0f} times in the last interval - monitoring",
    ("bgp_flap_count", "critical"): "%BGP-2-FLAP_CRIT: {node}: BGP session to {neighbor} flapping ({value:.0f} flaps) - session unstable, dampening applied",
    ("bgp_flap_count", "recovered"): "%BGP-5-ADJCHANGE: {node}: BGP session to {neighbor} Up - flapping stopped",

    ("cpu", "warning"): "%SYS-4-CPUHIGH: {node}: CPU utilization at {value:.1f}% - above warning threshold",
    ("cpu", "critical"): "%SYS-1-CPUCRIT: {node}: CPU utilization at {value:.1f}% - process scheduling degraded",
    ("cpu", "recovered"): "%SYS-5-CPUNORMAL: {node}: CPU utilization back to {value:.1f}% - nominal",

    ("memory", "warning"): "%SYS-4-MEMHIGH: {node}: memory utilization at {value:.1f}% - above warning threshold",
    ("memory", "critical"): "%SYS-1-MEMCRIT: {node}: memory utilization at {value:.1f}% - risk of OOM",
    ("memory", "recovered"): "%SYS-5-MEMNORMAL: {node}: memory utilization back to {value:.1f}% - nominal",

    ("packet_loss", "warning"): "%IF-4-PKTLOSS_WARN: {node}: packet loss at {value:.1f}% on uplink to {neighbor}",
    ("packet_loss", "critical"): "%IF-1-PKTLOSS_CRIT: {node}: packet loss at {value:.1f}% on uplink to {neighbor} - link degraded",
    ("packet_loss", "recovered"): "%IF-5-LINKUP: {node}: packet loss recovered to {value:.1f}% on uplink to {neighbor}",

    ("interface_errors", "warning"): "%IF-4-ERRWARN: {node}: interface error count at {value:.0f} - above warning threshold",
    ("interface_errors", "critical"): "%IF-2-ERRCRIT: {node}: interface error count at {value:.0f} - CRC/input errors climbing rapidly",
    ("interface_errors", "recovered"): "%IF-5-ERRCLEAR: {node}: interface error count back to {value:.0f} - nominal",

    ("latency_ms", "warning"): "%QOS-4-LATENCY_WARN: {node}: round-trip latency at {value:.1f}ms - above baseline",
    ("latency_ms", "critical"): "%QOS-2-LATENCY_CRIT: {node}: round-trip latency at {value:.1f}ms - SLA breach",
    ("latency_ms", "recovered"): "%QOS-5-LATENCY_OK: {node}: round-trip latency back to {value:.1f}ms - nominal",
}


def classify_band(value: float, warning_threshold: float, critical_threshold: float) -> str:
    """Classifies a metric value into "normal", "warning", or "critical" based on its profile's thresholds."""
    if value >= critical_threshold:
        return "critical"
    if value >= warning_threshold:
        return "warning"
    return "normal"


def render_threshold_line(
    metric_name: str,
    node_id: str,
    value: float,
    neighbor: Optional[str],
    band: str,
) -> Optional[str]:
    """
    Renders the deterministic log line for a metric's band transition.
    `band` must be "warning", "critical", or "recovered" (the label used
    when a metric drops back to "normal"). Returns None if no template
    is defined for this (metric_name, band) pair.
    """
    template = _THRESHOLD_TEMPLATES.get((metric_name, band))
    if template is None:
        return None
    return template.format(node=node_id, neighbor=neighbor or "peer", value=value)
