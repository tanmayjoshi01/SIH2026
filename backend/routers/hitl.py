"""
routers/hitl.py

STUB (Day 1). Accepts an approve/reject decision and returns a fixed
acknowledgement in the contracted shape. The Day 3 implementation will
persist the decision to the audit_log table and return the real row id;
nothing is written to the database today.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/hitl", tags=["hitl"])


class DecisionRequest(BaseModel):
    recommendation_id: int | None = None
    operator: str = "demo_operator"
    note: str = ""


@router.post("/approve")
def post_approve(payload: DecisionRequest) -> dict:
    return {"status": "approved", "audit_log_id": 1}


@router.post("/reject")
def post_reject(payload: DecisionRequest) -> dict:
    return {"status": "rejected", "audit_log_id": 2}
