"""
simulation/topology_def.py

Fixed NetworkX topology for the demo network: 2 ground stations,
3 routers, 2 switches, 1 gateway, 1 server (9 nodes total), wired
together with satellite/fiber/ethernet links. Every node carries the
per-node telemetry attributes that fault_injector.py and
telemetry_generator.py read and mutate each tick.
"""

from typing import Optional

import networkx as nx

NODE_DEFS = [
    ("gs-1", "Ground Station Alpha", "ground_station"),
    ("gs-2", "Ground Station Bravo", "ground_station"),
    ("router-5", "Core Router 5", "router"),
    ("router-6", "Core Router 6", "router"),
    ("router-7", "Edge Router 7", "router"),
    ("switch-3", "Aggregation Switch 3", "switch"),
    ("switch-4", "Access Switch 4", "switch"),
    ("gateway-1", "Site Gateway 1", "gateway"),
    ("server-1", "Application Server 1", "server"),
]

# Baseline (healthy) telemetry values per node type, used to seed the
# graph and as the "resting" value fault ramps return to on recovery.
BASELINES = {
    "ground_station": {"cpu": 15.0, "memory": 30.0},
    "router": {"cpu": 32.0, "memory": 40.0},
    "switch": {"cpu": 18.0, "memory": 25.0},
    "gateway": {"cpu": 22.0, "memory": 35.0},
    "server": {"cpu": 38.0, "memory": 55.0},
}

# (source, target, link_type, bandwidth_mbps)
LINK_DEFS = [
    ("gs-1", "router-5", "satellite_link", 50),
    ("gs-2", "router-6", "satellite_link", 50),
    ("router-5", "switch-3", "fiber", 1000),
    ("router-6", "switch-3", "fiber", 1000),
    ("router-5", "router-7", "fiber", 1000),
    ("router-6", "router-7", "fiber", 1000),
    ("switch-3", "switch-4", "fiber", 1000),
    ("router-7", "switch-4", "ethernet", 1000),
    ("switch-4", "gateway-1", "ethernet", 1000),
    ("gateway-1", "server-1", "ethernet", 1000),
]


def build_topology() -> nx.Graph:
    """Builds a fresh copy of the fixed demo topology with baseline telemetry."""
    graph = nx.Graph()

    for node_id, name, node_type in NODE_DEFS:
        baseline = BASELINES[node_type]
        graph.add_node(
            node_id,
            id=node_id,
            name=name,
            type=node_type,
            status="healthy",
            cpu=baseline["cpu"],
            memory=baseline["memory"],
            packet_loss=0.2,
            latency_ms=8.0,
            interface_errors=0,
            bgp_flap_count=0,
            metadata={},
        )

    for source, target, link_type, bandwidth_mbps in LINK_DEFS:
        graph.add_edge(
            source,
            target,
            link_type=link_type,
            bandwidth_mbps=bandwidth_mbps,
            status="up",
        )

    return graph


def get_neighbor(graph: nx.Graph, node_id: str) -> Optional[str]:
    """Deterministically picks the "primary" neighbor of a node (lowest id), used to name a peer/uplink in log lines."""
    neighbors = sorted(graph.neighbors(node_id))
    return neighbors[0] if neighbors else None
