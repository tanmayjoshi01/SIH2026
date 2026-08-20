"""
main.py

FastAPI application for the air-gapped predictive NOC copilot.

Mounts the live routers (which read Developer 1's Postgres schema), the
thin simulation wrapper, and the Day 1 stub routers. On startup it also
starts Developer 1's telemetry generator loop in a background thread, so
that a fault injected through POST /api/simulation/fault is written to
the database the UI polls -- the same process must own the generator for
the injection to be visible.

Run (from the repository root):
    uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Developer 1's modules import each other as top-level packages (`db.*`,
# `simulation.*`, `core.*`), so backend/ must be importable as a root.
_BACKEND_ROOT = Path(__file__).resolve().parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.exc import SQLAlchemyError

from config import settings
from routers import audit, copilot, health, hitl, monitoring, predictions, simulation
from services import simulation_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.run_telemetry_loop:
        try:
            from db.database import init_db

            init_db()  # idempotent create_all from Developer 1's data layer
        except SQLAlchemyError:
            logger.exception("Could not reach the database at startup; telemetry writes will retry each tick")
        simulation_service.start_background_loop()
    yield
    simulation_service.stop_background_loop()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Error envelope: every failure answers with {"error": ..., "code": ...}
# --------------------------------------------------------------------------


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": str(exc.detail), "code": f"HTTP_{exc.status_code}"},
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request, exc: SQLAlchemyError):
    logger.exception("Unhandled database error")
    return JSONResponse(
        status_code=503,
        content={"error": f"Database unavailable: {exc.__class__.__name__}", "code": "DB_UNAVAILABLE"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    logger.exception("Unhandled server error")
    return JSONResponse(
        status_code=500,
        content={"error": f"Internal server error: {exc.__class__.__name__}", "code": "INTERNAL_ERROR"},
    )


# --------------------------------------------------------------------------
# Routers
# --------------------------------------------------------------------------

for module in (health, monitoring, simulation, copilot, predictions, audit, hitl):
    app.include_router(module.router, prefix=settings.api_prefix)


@app.get("/")
def root() -> dict:
    return {"name": settings.app_name, "docs": "/docs", "api_prefix": settings.api_prefix}


@app.get("/metrics")
def metrics() -> Response:
    # Root path, not under settings.api_prefix -- backend/prometheus.yml
    # scrapes host.docker.internal:8000/metrics with no metrics_path
    # override, so Prometheus expects it exactly here.
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
