"""
routers/simulation.py

Thin HTTP wrapper around Developer 1's simulation package. This module
contains no fault ramps, no topology handling and no telemetry
generation: it validates the request body, calls into
services/simulation_service.py (which holds Developer 1's
TelemetryGenerator / FaultInjector instance) and maps failures onto the
{"error", "code"} envelope.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import simulation_service

router = APIRouter(prefix="/simulation", tags=["simulation"])


class FaultRequest(BaseModel):
    node_id: str
    fault_type: str


@router.post("/fault")
def post_fault(payload: FaultRequest) -> dict:
    try:
        simulation_service.inject(payload.node_id, payload.fault_type)
    except ValueError as exc:
        # Raised by FaultInjector.inject / build_profile for an unknown
        # node id or fault id; the message already lists the valid values.
        raise HTTPException(
            status_code=400,
            detail={"error": str(exc), "code": "INVALID_FAULT_REQUEST"},
        ) from exc
    return {"status": "injecting"}


@router.post("/reset")
def post_reset() -> dict:
    simulation_service.reset()
    return {"status": "reset"}
