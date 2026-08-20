"""
simulation/fault_injector.py

Drives active fault episodes against the live NetworkX topology.
inject(node_id, fault_id) starts a ramp; tick(now) advances every
active episode, mutates the graph's node attributes in place, and
emits a deterministic log line whenever a metric crosses a
warning/critical threshold (or recovers back to normal). Episodes end
themselves once their profile's duration elapses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import networkx as nx

from simulation.fault_profiles import FaultProfile, build_profile
from simulation.log_templates import classify_band, render_threshold_line
from simulation.topology_def import BASELINES, get_neighbor


@dataclass
class FaultEpisode:
    node_id: str
    fault_id: str
    profile: FaultProfile
    started_at: datetime
    last_band: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.last_band:
            self.last_band = {metric.metric_name: "normal" for metric in self.profile.metrics}

    def elapsed(self, now: datetime) -> float:
        return (now - self.started_at).total_seconds()

    def is_complete(self, now: datetime) -> bool:
        return self.profile.is_complete(self.elapsed(now))


@dataclass
class FaultTelemetryEvent:
    node_id: str
    metric_name: str
    value: float
    log_line: Optional[str]


class FaultInjector:
    """Owns the set of currently-active fault episodes for a topology graph."""

    def __init__(self, graph: nx.Graph):
        self.graph = graph
        self.active_episodes: Dict[str, FaultEpisode] = {}

    def reset(self) -> List[str]:
        """
        Clears every active fault episode and immediately snaps affected
        nodes' telemetry back to baseline (the same values build_topology()
        seeds a fresh graph with -- cpu/memory come from BASELINES by node
        type, the rest are the fixed healthy-network defaults). Returns the
        list of node_ids that were reset.
        """
        affected = list(self.active_episodes.keys())
        for node_id in affected:
            node = self.graph.nodes[node_id]
            baseline = BASELINES.get(node.get("type"), {})
            node["cpu"] = baseline.get("cpu", node.get("cpu", 0.0))
            node["memory"] = baseline.get("memory", node.get("memory", 0.0))
            node["packet_loss"] = 0.2
            node["latency_ms"] = 8.0
            node["interface_errors"] = 0
            node["bgp_flap_count"] = 0
            node["status"] = "healthy"
        self.active_episodes.clear()
        return affected

    def inject(self, node_id: str, fault_id: str, now: Optional[datetime] = None) -> FaultEpisode:
        if node_id not in self.graph.nodes:
            raise ValueError(f"Unknown node_id: {node_id!r}. Known nodes: {sorted(self.graph.nodes)}")

        now = now or datetime.now(timezone.utc)
        profile = build_profile(fault_id)
        episode = FaultEpisode(node_id=node_id, fault_id=fault_id, profile=profile, started_at=now)
        self.active_episodes[node_id] = episode
        self.graph.nodes[node_id]["status"] = "degraded"
        return episode

    def tick(self, now: Optional[datetime] = None) -> Tuple[List[FaultTelemetryEvent], List[str]]:
        """
        Advances all active episodes by one step. Returns
        (telemetry_events, node_ids_whose_episode_just_completed).
        """
        now = now or datetime.now(timezone.utc)
        events: List[FaultTelemetryEvent] = []
        completed_nodes: List[str] = []

        for node_id, episode in list(self.active_episodes.items()):
            elapsed = episode.elapsed(now)
            values = episode.profile.sample(elapsed)
            neighbor = get_neighbor(self.graph, node_id)

            for metric in episode.profile.metrics:
                value = values[metric.metric_name]
                self.graph.nodes[node_id][metric.metric_name] = value

                band = classify_band(value, metric.warning_threshold, metric.critical_threshold)
                last_band = episode.last_band[metric.metric_name]

                log_line = None
                if band != last_band:
                    label = "recovered" if band == "normal" else band
                    log_line = render_threshold_line(metric.metric_name, node_id, value, neighbor, label)
                    episode.last_band[metric.metric_name] = band

                events.append(FaultTelemetryEvent(node_id, metric.metric_name, value, log_line))

            if episode.is_complete(now):
                completed_nodes.append(node_id)

        for node_id in completed_nodes:
            self.graph.nodes[node_id]["status"] = "healthy"
            del self.active_episodes[node_id]

        return events, completed_nodes
