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

reset() delegates to FaultInjector.reset() on the live generator's
injector, which clears active episodes and snaps affected nodes back to
baseline in place -- no rebuilding of the generator/topology/injector
required.

_lock also serializes every mutation of the shared NetworkX graph
(inject, reset, and each background tick) against each other. Without
this, a reset() running on the FastAPI request thread could race the
background tick loop mid-tick -- the tick's in-flight fault-ramp write
for a node could land after reset()'s baseline write, leaving the node
briefly degraded again until the next tick self-corrects. It's an RLock
because get_generator() (which inject/reset/the loop all call first)
also acquires it, and a plain Lock would deadlock on that reentry.
"""

from __future__ import annotations

import logging
import threading

from simulation.telemetry_generator import TICK_SECONDS, TelemetryGenerator

logger = logging.getLogger("simulation_service")

_lock = threading.RLock()
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
    with _lock:
        return get_generator().inject_fault(node_id, fault_type)


def reset() -> None:
    """Drops all active fault episodes and snaps affected nodes back to baseline."""
    with _lock:
        get_generator().injector.reset()


def _run_loop() -> None:
    logger.info("Telemetry tick loop started (tick=%ss)", TICK_SECONDS)
    while not _stop_event.is_set():
        try:
            with _lock:
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
