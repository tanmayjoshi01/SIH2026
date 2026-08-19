"""
routers/health.py

Liveness plus the air-gap posture strip rendered by the UI's
TopHeaderBar. Deliberately does not touch the database: this endpoint
must answer even when Postgres is down, so the header can still tell the
operator the system is air-gapped.
"""

from __future__ import annotations

from fastapi import APIRouter

from config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def get_health() -> dict:
    return {
        "status": "ok",
        "air_gap": {
            "network": settings.air_gap_network,
            "llm": settings.air_gap_llm,
            "rag": settings.air_gap_rag,
            "db": settings.air_gap_db,
        },
    }
