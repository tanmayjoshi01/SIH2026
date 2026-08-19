"""
services/simulation_service.py

Process-wide holder for Developer 1's TelemetryGenerator (which owns the
NetworkX topology graph and its FaultInjector) plus the background thread
that drives its tick loop.

This module contains NO simulation logic of its own. It exists only so
that the FastAPI lifespan and the /api/simulation router operate on the
same generator instance -- if the router injected into a different object
than the one writing telemetry_logs, an injected fault would never reach
the database the UI polls.

reset() is implemented by constructing a fresh TelemetryGenerator, which
re-runs Developer 1's own build_topology() + FaultInjector() setup. The
simulation package does not currently expose a reset entry point of its
own; rebuilding via its constructor avoids duplicating any ramp,
topology, or telemetry logic here.
"""

from __future__ import annotations

import logging
import threading

from simulation.telemetry_generator import TICK_SECONDS, TelemetryGenerator

logger = logging.getLogger("simulation_service")

_lock = threading.Lock()
_generator: TelemetryGenerator | None = None
_loop_thread: threading.Thread | None = None
_stop_event = threading.Event()


def get_generator() -> TelemetryGenerator:
    """Returns the process-wide generator, creating it on first use."""
    global _generator
    with _lock:
        if _generator is None:
            _generator = TelemetryGenerator()
        return _generator


def inject(node_id: str, fault_type: str):
    """Thin pass-through to Developer 1's TelemetryGenerator.inject_fault()."""
    return get_generator().inject_fault(node_id, fault_type)


def reset() -> None:
    """Drops all active fault episodes by rebuilding Developer 1's generator."""
    global _generator
    with _lock:
        _generator = TelemetryGenerator()


def _run_loop() -> None:
    logger.info("Telemetry tick loop started (tick=%ss)", TICK_SECONDS)
    while not _stop_event.is_set():
        try:
            get_generator().tick()
        except Exception:
            logger.exception("Telemetry tick failed; continuing")
        _stop_event.wait(TICK_SECONDS)
    logger.info("Telemetry tick loop stopped")


def start_background_loop() -> None:
    """Starts the tick loop in a daemon thread (idempotent)."""
    global _loop_thread
    with _lock:
        if _loop_thread is not None and _loop_thread.is_alive():
            return
        _stop_event.clear()
        _loop_thread = threading.Thread(target=_run_loop, name="telemetry-loop", daemon=True)
        _loop_thread.start()


def stop_background_loop() -> None:
    _stop_event.set()
    thread = _loop_thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=TICK_SECONDS + 1)
