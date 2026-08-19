"""
config.py

Application settings for the FastAPI layer. Reads the same DATABASE_URL
env var that db/database.py already honours (defaulting to the Postgres
instance in backend/docker-compose.yml) and carries the air-gap status
strip values surfaced by GET /api/health.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Air-Gapped AI Predictive NOC Copilot"
    api_prefix: str = "/api"

    # Vite dev server origins allowed to call this API from the browser.
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]

    # Air-gap posture reported to the UI header strip. These are static
    # facts about how the system is deployed, not measured values.
    air_gap_network: str = "OFFLINE"
    air_gap_llm: str = "LOCAL"
    air_gap_rag: str = "LOCAL"
    air_gap_db: str = "LOCAL"

    # Run Developer 1's telemetry generator loop inside the API process so
    # that an injected fault is reflected in the database the UI polls.
    run_telemetry_loop: bool = True

    # Default page size for GET /api/telemetry when no explicit limit is given.
    telemetry_default_limit: int = 200
    telemetry_max_limit: int = 2000


settings = Settings()
