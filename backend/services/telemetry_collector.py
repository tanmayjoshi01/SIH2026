"""
telemetry_collector.py

Collects REAL, LIVE system telemetry (CPU, memory, disk, network) using psutil.
No fake/synthetic data - every value here is read directly from the actual machine.

This module is the foundation of the whole pipeline:
telemetry_collector -> anomaly_detector -> forecaster -> rag_pipeline -> dashboard
"""

import psutil
import time
from datetime import datetime, timezone
from typing import Dict, List


class TelemetryCollector:
    """Collects live system metrics from the host machine (and optionally remote hosts via ping)."""

    def __init__(self, host_label: str = "local-ground-station"):
        self.host_label = host_label
        # Prime psutil's CPU percent calculation (first call is always inaccurate)
        psutil.cpu_percent(interval=None)

    def collect_snapshot(self) -> Dict:
        """
        Returns one real-time snapshot of system health.
        Called repeatedly (e.g. every 3-5 seconds) by the monitor loop.
        """
        cpu_percent = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        net = psutil.net_io_counters()

        snapshot = {
            "host": self.host_label,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cpu_percent": cpu_percent,
            "memory_percent": mem.percent,
            "memory_used_mb": round(mem.used / (1024 * 1024), 2),
            "memory_total_mb": round(mem.total / (1024 * 1024), 2),
            "disk_percent": disk.percent,
            "disk_used_gb": round(disk.used / (1024 ** 3), 2),
            "net_bytes_sent": net.bytes_sent,
            "net_bytes_recv": net.bytes_recv,
            "net_packets_sent": net.packets_sent,
            "net_packets_recv": net.packets_recv,
        }
        return snapshot

    def collect_network_health(self, targets: List[str]) -> List[Dict]:
        """
        Pings a list of real hosts (e.g. teammates' laptops on the same network,
        or gateway IPs) and returns real latency/packet-loss data.
        Requires the 'ping3' library.
        """
        from ping3 import ping

        results = []
        for target in targets:
            try:
                latency = ping(target, timeout=2, unit="ms")
                results.append({
                    "target": target,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "reachable": latency is not None,
                    "latency_ms": round(latency, 2) if latency else None,
                })
            except Exception as e:
                results.append({
                    "target": target,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "reachable": False,
                    "latency_ms": None,
                    "error": str(e),
                })
        return results


if __name__ == "__main__":
    # Quick manual test - run this file directly to confirm real data is being collected
    collector = TelemetryCollector()
    print("Collecting 5 live snapshots (one every 2 seconds)...\n")
    for i in range(5):
        snap = collector.collect_snapshot()
        print(f"[{i+1}] CPU: {snap['cpu_percent']}% | "
              f"Memory: {snap['memory_percent']}% | "
              f"Disk: {snap['disk_percent']}%")
        time.sleep(2)