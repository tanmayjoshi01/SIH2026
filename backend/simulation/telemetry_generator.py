"""
simulation/telemetry_generator.py

Background generator loop: every ~2 seconds, reads the current graph
state (baseline drift plus any active fault episodes from
fault_injector), writes telemetry_logs rows, and keeps the nodes table
in sync with current status/metrics. A single failed tick (e.g. a
transient DB connection issue) is logged and skipped - it never kills
the loop.

Day 2: every node is also scored every tick (not just nodes with an
active fault) via services/anomaly_scoring_service.py, producing one
`anomalies` row per (node, tick) in the same transaction as the
telemetry writes above -- this is what gives Developer 2's UI/LLM a
continuous anomaly_score/failure_probability stream instead of only a
row at fault-injection time. A scoring failure for one node is caught
inside score_node() itself and never aborts the tick.

Standalone manual test:
    python backend/simulation/telemetry_generator.py
Injects a bgp_flap fault on router-7 and prints rising
packet_loss/bgp_flap_count values tick by tick until the episode ends.
"""

from __future__ import annotations

import logging
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy.exc import SQLAlchemyError

from db.database import SessionLocal, init_db
from db.models import Node, TelemetryLog
from services import anomaly_scoring_service
from simulation.fault_injector import FaultInjector
from simulation.topology_def import build_topology

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("telemetry_generator")

TICK_SECONDS = 2.0

# Small per-tick jitter applied to nodes with no active fault, so baseline
# telemetry drifts slightly instead of sitting dead flat.
JITTER = {
    "cpu": 1.5,
    "memory": 1.0,
    "packet_loss": 0.1,
    "latency_ms": 0.5,
    "interface_errors": 0.0,
    "bgp_flap_count": 0.0,
}
UNITS = {
    "cpu": "percent",
    "memory": "percent",
    "packet_loss": "percent",
    "latency_ms": "ms",
    "interface_errors": "count",
    "bgp_flap_count": "flaps",
}
SUBSYSTEMS = {
    "cpu": "compute",
    "memory": "compute",
    "packet_loss": "network",
    "latency_ms": "network",
    "interface_errors": "network",
    "bgp_flap_count": "bgp",
}


class TelemetryGenerator:
    def __init__(self, session_factory=SessionLocal):
        self.graph = build_topology()
        self.injector = FaultInjector(self.graph)
        self.session_factory = session_factory

    def inject_fault(self, node_id: str, fault_id: str):
        return self.injector.inject(node_id, fault_id)

    def _make_log_row(self, node_id: str, metric_name: str, value: float, now: datetime, log_line=None) -> TelemetryLog:
        return TelemetryLog(
            timestamp=now,
            node_id=node_id,
            subsystem=SUBSYSTEMS[metric_name],
            metric_name=metric_name,
            value=float(value),
            unit=UNITS[metric_name],
            raw_log_line=log_line,
        )

    def _apply_baseline_jitter(self, now: datetime) -> list[TelemetryLog]:
        rows: list[TelemetryLog] = []
        for node_id in self.graph.nodes:
            if node_id in self.injector.active_episodes:
                continue  # this node's metrics are driven by its active fault profile instead
            for metric_name, spread in JITTER.items():
                current = self.graph.nodes[node_id].get(metric_name, 0.0)
                delta = random.uniform(-spread, spread) if spread else 0.0
                new_value = max(0.0, round(current + delta, 2))
                self.graph.nodes[node_id][metric_name] = new_value
                rows.append(self._make_log_row(node_id, metric_name, new_value, now))
        return rows

    def _sync_node_row(self, session, node_id: str) -> None:
        data = self.graph.nodes[node_id]
        db_node = session.get(Node, node_id)
        if db_node is None:
            return
        db_node.status = data.get("status", "healthy")
        db_node.cpu = data.get("cpu", 0.0)
        db_node.memory = data.get("memory", 0.0)
        db_node.packet_loss = data.get("packet_loss", 0.0)
        db_node.latency_ms = data.get("latency_ms", 0.0)
        db_node.interface_errors = int(data.get("interface_errors", 0))
        db_node.bgp_flap_count = int(data.get("bgp_flap_count", 0))

    def tick(self) -> list[TelemetryLog]:
        now = datetime.now(timezone.utc)
        rows = self._apply_baseline_jitter(now)

        fault_events, completed = self.injector.tick(now)
        for event in fault_events:
            rows.append(self._make_log_row(event.node_id, event.metric_name, event.value, now, event.log_line))
            if event.log_line:
                logger.info(event.log_line)
        for node_id in completed:
            logger.info("Fault episode on %s resolved", node_id)

        try:
            with self.session_factory() as session:
                session.add_all(rows)
                # Flush so this tick's freshly-written telemetry rows are
                # visible to the scorer's SELECT-based feature window below.
                session.flush()
                for node_id in self.graph.nodes:
                    self._sync_node_row(session, node_id)
                for node_id in self.graph.nodes:
                    episode = self.injector.active_episodes.get(node_id)
                    anomaly_scoring_service.score_node(session, node_id, episode.fault_id if episode else None)
                session.commit()
        except SQLAlchemyError:
            logger.exception("Telemetry tick failed to write to the database; continuing")

        return rows

    def run_forever(self) -> None:
        logger.info("Telemetry generator started (tick=%ss)", TICK_SECONDS)
        while True:
            try:
                self.tick()
            except Exception:
                logger.exception("Unhandled error in generator tick; continuing")
            time.sleep(TICK_SECONDS)


def _manual_test() -> None:
    """
    Standalone smoke test: injects bgp_flap on router-7 and prints
    packet_loss/bgp_flap_count each tick until the episode resolves.
    """
    init_db()
    generator = TelemetryGenerator()
    episode = generator.inject_fault("router-7", "bgp_flap")
    print(f"Injected {episode.fault_id} on {episode.node_id}, duration={episode.profile.duration_seconds}s")

    while "router-7" in generator.injector.active_episodes:
        rows = generator.tick()
        node_data = generator.graph.nodes["router-7"]
        print(
            f"t+{episode.elapsed(datetime.now(timezone.utc)):5.1f}s  "
            f"packet_loss={node_data['packet_loss']:6.2f}%  "
            f"bgp_flap_count={node_data['bgp_flap_count']:5.1f}  "
            f"latency_ms={node_data['latency_ms']:6.2f}  "
            f"rows_written={len(rows)}"
        )
        time.sleep(TICK_SECONDS)

    print(f"Episode complete. router-7 status={generator.graph.nodes['router-7']['status']}")


if __name__ == "__main__":
    _manual_test()
