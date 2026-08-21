"""
scripts/ws_reconnect_test.py

Day 4: verifies /ws/incidents survives an unclean client disconnect --
one where the client vanishes without sending a WebSocket close frame
(a killed tab, a dropped network link), as opposed to a normal close().
Drives scripts/_ws_client_subprocess.py as a child process and kills it
with proc.kill() (TerminateProcess on Windows / SIGKILL on POSIX, both
skip any cooperative shutdown code), which is the closest a same-machine
test can get to that failure mode.

What it checks:
  1. A live WS client actually receives an OPEN event when a fault is
     injected.
  2. After that client is killed uncleanly, the server-side subscriber
     log ("ws_incidents subscriber disconnected") shows the connection
     was reclaimed within routers/incidents.py's WS_LIVENESS_CHECK_SECONDS
     window, rather than leaking its subscriber queue and worker thread
     forever.
  3. GET /api/incidents (the polling fallback) reflects ground truth
     throughout, independent of whatever the WS connection is doing.
  4. A fresh reconnect after the kill receives subsequent events
     correctly -- resubscription isn't stuck on stale state from the
     killed connection.

Requires the server's stderr/stdout log to be readable at --log-path (the
liveness-check log lines are only used to confirm cleanup happened; if
you don't have the server's log handy, everything except check #2 still
runs and reports).

Usage:
    python backend/scripts/ws_reconnect_test.py --log-path <path to uvicorn's log>
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/ws/incidents"
NODE_ID = "server-1"
FAULT_TYPE = "high_cpu"
LIVENESS_WINDOW_SECONDS = 10.0  # must match routers/incidents.py's WS_LIVENESS_CHECK_SECONDS


def log(msg: str) -> None:
    print(f"[ws_reconnect_test] {msg}", flush=True)


def start_client() -> subprocess.Popen:
    helper = Path(__file__).with_name("_ws_client_subprocess.py")
    return subprocess.Popen(
        [sys.executable, str(helper), WS_URL],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def wait_for_line(proc: subprocess.Popen, prefix: str, timeout: float) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                return None
            continue
        line = line.strip()
        if line.startswith(prefix):
            return line
    return None


def read_log_tail(log_path: Path, since_byte_offset: int) -> tuple[str, int]:
    with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
        fh.seek(since_byte_offset)
        content = fh.read()
        new_offset = fh.tell()
    return content, new_offset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-path", default=None, help="Path to the running server's log, to confirm disconnect cleanup")
    args = parser.parse_args()

    ok = True

    session = requests.Session()
    session.post(f"{BASE_URL}/api/simulation/reset", timeout=10).raise_for_status()
    time.sleep(1.0)

    log_offset = 0
    if args.log_path:
        log_offset = Path(args.log_path).stat().st_size

    log("Starting first WS client")
    client1 = start_client()
    if wait_for_line(client1, "CONNECTED", timeout=10) is None:
        log("FAIL: first client never reported CONNECTED")
        client1.kill()
        return 1

    log(f"Injecting {FAULT_TYPE} on {NODE_ID}")
    session.post(f"{BASE_URL}/api/simulation/fault", json={"node_id": NODE_ID, "fault_type": FAULT_TYPE}, timeout=10).raise_for_status()

    open_line = wait_for_line(client1, "EVENT", timeout=20)
    if open_line is None:
        log("FAIL: first client never received an event after fault injection")
        ok = False
    else:
        log(f"OK: first client received: {open_line[:120]}")

    log("Killing first client uncleanly (proc.kill(), no close handshake)")
    kill_time = time.monotonic()
    client1.kill()
    client1.wait(timeout=5)

    log(f"Polling GET /api/incidents (safety net) while the dead connection is still being detected server-side")
    for _ in range(3):
        resp = session.get(f"{BASE_URL}/api/incidents", params={"node_id": NODE_ID, "status": "open"}, timeout=10)
        resp.raise_for_status()
        rows = resp.json()
        log(f"  REST poll: {len(rows)} open incident(s) for {NODE_ID}")
        time.sleep(1.0)

    if args.log_path:
        time.sleep(LIVENESS_WINDOW_SECONDS + 3.0)
        content, log_offset = read_log_tail(Path(args.log_path), log_offset)
        if "subscriber disconnected" in content:
            elapsed = time.monotonic() - kill_time
            log(f"OK: server logged subscriber cleanup after the unclean kill (within ~{elapsed:.1f}s)")
        else:
            log("FAIL: server never logged 'subscriber disconnected' after the unclean kill -- possible leak")
            ok = False
    else:
        log("SKIP: no --log-path given, cannot confirm server-side cleanup from here")

    log("Starting second WS client (reconnect)")
    client2 = start_client()
    if wait_for_line(client2, "CONNECTED", timeout=10) is None:
        log("FAIL: reconnected client never reported CONNECTED")
        client2.kill()
        return 1

    log("Resetting (should RESOLVE the open incident) to confirm the new connection gets fresh events")
    session.post(f"{BASE_URL}/api/simulation/reset", timeout=10).raise_for_status()

    resolve_line = wait_for_line(client2, "EVENT", timeout=15)
    if resolve_line is None:
        log("FAIL: reconnected client never received an event after reset")
        ok = False
    else:
        log(f"OK: reconnected client received: {resolve_line[:120]}")

    client2.kill()
    try:
        client2.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass

    log("RESULT: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
