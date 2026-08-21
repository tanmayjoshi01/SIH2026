"""
scripts/stress_test_lifecycle.py

Day 4: drives the full incident lifecycle (inject -> tick -> open ->
acknowledge -> reset -> resolve) back-to-back, 20 times per fault type,
against a running backend (default http://127.0.0.1:8000). Looks
specifically for the failure modes that only show up under repetition:

  - orphaned incidents: still open/acknowledged after a reset that should
    have closed them
  - double-open incidents: two open/acknowledged rows for the same node
    at once, especially when re-injecting before the previous episode
    has resolved
  - stale severity/peak_anomaly_score left over from a previous incident
    on the same node
  - drift between GET /api/incidents and GET /metrics's incident counts

Also runs a rapid-reinjection check per fault type and one concurrent-
multi-node scenario (two different fault types on two different nodes at
the same time).

This is a read/write *client* of the API -- it starts no server of its
own and contains no incident logic. Run against an already-running
`uvicorn main:app` (see backend/README or Day 3/4 report for how this
project starts it on Windows).

Usage:
    python backend/scripts/stress_test_lifecycle.py
    python backend/scripts/stress_test_lifecycle.py --cycles 20 --base-url http://127.0.0.1:8000

Exit code is 0 iff zero bugs were recorded; a non-zero exit means at
least one orphaned incident, double-open, stale-field, or metrics-drift
finding was recorded (see the printed summary for details).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("stress_test")

FAULT_TYPES = ["bgp_flap", "high_cpu", "packet_loss"]
# One dedicated node per fault type, kept distinct so the 3 fault types'
# cycles never interfere with each other's open/resolve counters.
NODE_FOR_FAULT = {"bgp_flap": "router-7", "high_cpu": "gs-1", "packet_loss": "gs-2"}
CONCURRENT_NODE_A, CONCURRENT_FAULT_A = "router-5", "bgp_flap"
CONCURRENT_NODE_B, CONCURRENT_FAULT_B = "switch-3", "high_cpu"

OPEN_TIMEOUT_SECONDS = 20.0
RESOLVE_TIMEOUT_SECONDS = 15.0
POLL_INTERVAL_SECONDS = 0.5
REINJECT_SETTLE_SECONDS = 7.0  # >= 3 ticks at 2s, so the open-gate has a real chance to fire twice if it's going to


@dataclass
class Bug:
    kind: str
    detail: str


@dataclass
class Results:
    cycles_completed: dict = field(default_factory=lambda: {f: 0 for f in FAULT_TYPES})
    bugs: list = field(default_factory=list)

    def record(self, kind: str, detail: str) -> None:
        bug = Bug(kind, detail)
        self.bugs.append(bug)
        logger.error("BUG [%s]: %s", kind, detail)


class ApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def inject(self, node_id: str, fault_type: str) -> None:
        resp = self.session.post(
            f"{self.base_url}/api/simulation/fault",
            json={"node_id": node_id, "fault_type": fault_type},
            timeout=10,
        )
        resp.raise_for_status()

    def reset(self) -> None:
        resp = self.session.post(f"{self.base_url}/api/simulation/reset", timeout=10)
        resp.raise_for_status()

    def get_incidents(self, node_id: Optional[str] = None, status: Optional[str] = None) -> list:
        params = {}
        if node_id:
            params["node_id"] = node_id
        if status:
            params["status"] = status
        resp = self.session.get(f"{self.base_url}/api/incidents", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def acknowledge(self, incident_id: int) -> dict:
        resp = self.session.post(f"{self.base_url}/api/incidents/{incident_id}/acknowledge", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def active_incidents(self, node_id: str) -> list:
        """Every currently open-or-acknowledged incident row for node_id."""
        return self.get_incidents(node_id=node_id, status="open") + self.get_incidents(node_id=node_id, status="acknowledged")

    def metrics_incident_counts(self) -> dict:
        """Parses GET /metrics text output into {"total": n, "by_severity": {...}}."""
        resp = self.session.get(f"{self.base_url}/metrics", timeout=10)
        resp.raise_for_status()
        total = None
        by_severity = {}
        for line in resp.text.splitlines():
            if line.startswith("#"):
                continue
            if line.startswith("noc_open_incidents_total"):
                total = float(line.split()[-1])
            elif line.startswith("noc_open_incidents_by_severity"):
                label = line.split("severity=\"")[1].split("\"")[0]
                by_severity[label] = float(line.split()[-1])
        return {"total": total, "by_severity": by_severity}


def wait_until(predicate, timeout: float, interval: float = POLL_INTERVAL_SECONDS):
    """Polls predicate() until it returns a truthy value or timeout elapses. Returns the truthy value or None."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def wait_for_open_incident(api: ApiClient, node_id: str, timeout: float = OPEN_TIMEOUT_SECONDS) -> Optional[dict]:
    def check():
        rows = api.get_incidents(node_id=node_id, status="open")
        return rows[0] if rows else None

    return wait_until(check, timeout)


def wait_for_resolved(api: ApiClient, incident_id: int, node_id: str, timeout: float = RESOLVE_TIMEOUT_SECONDS) -> Optional[dict]:
    def check():
        for row in api.get_incidents(node_id=node_id):
            if row["id"] == incident_id and row["status"] == "resolved":
                return row
        return None

    return wait_until(check, timeout)


def check_metrics_drift(api: ApiClient, results: Results, label: str, retries: int = 1) -> None:
    """
    Compares GET /api/incidents' open+acknowledged count/severity breakdown
    against GET /metrics' gauges. Both are computed by independent DB
    queries a few milliseconds apart, so a live background tick loop could
    legitimately change state between the two calls -- one retry absorbs
    that timing noise before a mismatch is recorded as a real bug.
    """
    for attempt in range(retries + 1):
        active = api.get_incidents(status="open") + api.get_incidents(status="acknowledged")
        expected_total = len(active)
        expected_by_severity: dict = {}
        for row in active:
            expected_by_severity[row["severity"]] = expected_by_severity.get(row["severity"], 0) + 1

        metrics = api.metrics_incident_counts()
        actual_total = metrics["total"]
        actual_by_severity = {k: v for k, v in metrics["by_severity"].items() if v}

        if actual_total == expected_total and actual_by_severity == {k: float(v) for k, v in expected_by_severity.items()}:
            return
        if attempt < retries:
            time.sleep(0.5)
            continue
        results.record(
            "METRICS_DRIFT",
            f"[{label}] /api/incidents says total={expected_total} by_severity={expected_by_severity}; "
            f"/metrics says total={actual_total} by_severity={actual_by_severity}",
        )


def run_cycle(api: ApiClient, results: Results, fault_type: str, node_id: str, cycle_num: int) -> None:
    label = f"{fault_type}#{cycle_num}"

    pre_existing = api.active_incidents(node_id)
    if pre_existing:
        results.record(
            "ORPHANED_BEFORE_CYCLE",
            f"[{label}] node={node_id} already had open/acknowledged incident(s) before injecting: {pre_existing}",
        )

    api.inject(node_id, fault_type)

    incident = wait_for_open_incident(api, node_id)
    if incident is None:
        results.record("OPEN_NEVER_HAPPENED", f"[{label}] no incident opened for node={node_id} within {OPEN_TIMEOUT_SECONDS}s")
        return
    logger.info("[%s] OPEN id=%s severity=%s peak=%.3f opened_at=%s", label, incident["id"], incident["severity"], incident["peak_anomaly_score"], incident["opened_at"])

    active = api.active_incidents(node_id)
    if len(active) != 1:
        results.record("DOUBLE_OPEN", f"[{label}] node={node_id} has {len(active)} open/acknowledged incidents at once: {active}")

    ack = api.acknowledge(incident["id"])
    if ack["status"] != "acknowledged":
        results.record("ACK_FAILED", f"[{label}] acknowledge returned status={ack['status']!r}, expected 'acknowledged'")

    api.reset()

    resolved = wait_for_resolved(api, incident["id"], node_id)
    if resolved is None:
        still_active = api.active_incidents(node_id)
        results.record(
            "ORPHANED_AFTER_RESET",
            f"[{label}] incident id={incident['id']} did not resolve within {RESOLVE_TIMEOUT_SECONDS}s after reset; "
            f"still active for node={node_id}: {still_active}",
        )
        return

    if resolved["closed_at"] is None:
        results.record("MISSING_CLOSED_AT", f"[{label}] incident id={incident['id']} is resolved but closed_at is null")
    if resolved["peak_anomaly_score"] < incident["peak_anomaly_score"]:
        results.record(
            "PEAK_SCORE_REGRESSED",
            f"[{label}] incident id={incident['id']} peak_anomaly_score dropped from {incident['peak_anomaly_score']} to {resolved['peak_anomaly_score']}",
        )
    logger.info("[%s] RESOLVE id=%s severity=%s peak=%.3f closed_at=%s", label, resolved["id"], resolved["severity"], resolved["peak_anomaly_score"], resolved["closed_at"])

    remaining = api.active_incidents(node_id)
    if remaining:
        results.record("ORPHANED_AFTER_RESET", f"[{label}] node={node_id} still has active incidents after resolve confirmed: {remaining}")

    check_metrics_drift(api, results, label)
    results.cycles_completed[fault_type] += 1


def run_rapid_reinjection_test(api: ApiClient, results: Results, fault_type: str, node_id: str) -> None:
    label = f"{fault_type}#reinject"
    api.reset()
    time.sleep(1.0)

    api.inject(node_id, fault_type)
    first = wait_for_open_incident(api, node_id)
    if first is None:
        results.record("OPEN_NEVER_HAPPENED", f"[{label}] first injection never opened an incident for node={node_id}")
        return
    logger.info("[%s] first incident OPEN id=%s", label, first["id"])

    # Re-inject on the same node before acknowledging or resetting -- the
    # previous episode/incident is still fully live at this point.
    api.inject(node_id, fault_type)
    time.sleep(REINJECT_SETTLE_SECONDS)

    active = api.active_incidents(node_id)
    if len(active) != 1:
        results.record("DOUBLE_OPEN_ON_REINJECT", f"[{label}] node={node_id} has {len(active)} open/acknowledged incidents after re-injecting mid-episode: {active}")
    else:
        logger.info("[%s] still exactly one active incident after re-injection: id=%s", label, active[0]["id"])

    api.reset()
    for row in active:
        resolved = wait_for_resolved(api, row["id"], node_id)
        if resolved is None:
            results.record("ORPHANED_AFTER_RESET", f"[{label}] incident id={row['id']} did not resolve after reset")

    check_metrics_drift(api, results, label)


def run_concurrent_multi_node_test(api: ApiClient, results: Results) -> None:
    label = "concurrent_multi_node"
    api.reset()
    time.sleep(1.0)

    api.inject(CONCURRENT_NODE_A, CONCURRENT_FAULT_A)
    api.inject(CONCURRENT_NODE_B, CONCURRENT_FAULT_B)

    incident_a = wait_for_open_incident(api, CONCURRENT_NODE_A)
    incident_b = wait_for_open_incident(api, CONCURRENT_NODE_B)

    if incident_a is None:
        results.record("OPEN_NEVER_HAPPENED", f"[{label}] node={CONCURRENT_NODE_A} ({CONCURRENT_FAULT_A}) never opened")
    if incident_b is None:
        results.record("OPEN_NEVER_HAPPENED", f"[{label}] node={CONCURRENT_NODE_B} ({CONCURRENT_FAULT_B}) never opened")
    if incident_a is None or incident_b is None:
        return

    logger.info("[%s] concurrent OPEN a=%s (node=%s) b=%s (node=%s)", label, incident_a["id"], CONCURRENT_NODE_A, incident_b["id"], CONCURRENT_NODE_B)

    # Both must be independently open at the same time, on the correct nodes.
    both_open = api.get_incidents(status="open")
    ids_open = {row["id"] for row in both_open}
    if incident_a["id"] not in ids_open or incident_b["id"] not in ids_open:
        results.record("CONCURRENT_STATE_WRONG", f"[{label}] expected both {incident_a['id']} and {incident_b['id']} open simultaneously; open set was {ids_open}")

    check_metrics_drift(api, results, label)

    api.reset()
    resolved_a = wait_for_resolved(api, incident_a["id"], CONCURRENT_NODE_A)
    resolved_b = wait_for_resolved(api, incident_b["id"], CONCURRENT_NODE_B)
    if resolved_a is None:
        results.record("ORPHANED_AFTER_RESET", f"[{label}] incident a id={incident_a['id']} did not resolve after reset")
    if resolved_b is None:
        results.record("ORPHANED_AFTER_RESET", f"[{label}] incident b id={incident_b['id']} did not resolve after reset")

    check_metrics_drift(api, results, label)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--cycles", type=int, default=20)
    args = parser.parse_args()

    api = ApiClient(args.base_url)
    results = Results()

    logger.info("Resetting simulation to a clean baseline before starting")
    api.reset()
    time.sleep(1.0)

    for fault_type in FAULT_TYPES:
        node_id = NODE_FOR_FAULT[fault_type]
        logger.info("=== Starting %d cycles of %s on %s ===", args.cycles, fault_type, node_id)
        for cycle_num in range(1, args.cycles + 1):
            run_cycle(api, results, fault_type, node_id, cycle_num)
        logger.info("=== Rapid re-injection check: %s on %s ===", fault_type, node_id)
        run_rapid_reinjection_test(api, results, fault_type, node_id)

    logger.info("=== Concurrent multi-node fault check ===")
    run_concurrent_multi_node_test(api, results)

    logger.info("=== SUMMARY ===")
    for fault_type in FAULT_TYPES:
        logger.info("%s: %d/%d cycles completed cleanly", fault_type, results.cycles_completed[fault_type], args.cycles)
    logger.info("Total bugs recorded: %d", len(results.bugs))
    for bug in results.bugs:
        logger.info("  - [%s] %s", bug.kind, bug.detail)

    return 0 if not results.bugs else 1


if __name__ == "__main__":
    sys.exit(main())
