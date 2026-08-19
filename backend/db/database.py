"""
db/database.py

Engine/session setup for the Postgres instance defined in
backend/docker-compose.yml (user=sih2026, password=sih2026pass,
db=sih2026, localhost:5432). No new database or ORM - SQLAlchemy 2.0
against the existing Postgres container. Override via the DATABASE_URL
env var if needed (e.g. running inside another container on the same
compose network).

Run directly to create all 8 tables and list what exists:
    python backend/db/database.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow `python backend/db/database.py` to work from any cwd by putting
# backend/ (this file's parent's parent) on sys.path, since the sibling
# `core` and `simulation` packages are imported from there.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from db.models import Base

DEFAULT_DATABASE_URL = "postgresql+psycopg2://sih2026:sih2026pass@localhost:5432/sih2026"
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Creates all tables defined in db/models.py if they don't already exist."""
    Base.metadata.create_all(bind=engine)


def list_tables() -> list[str]:
    return inspect(engine).get_table_names()


if __name__ == "__main__":
    init_db()
    tables = sorted(list_tables())
    print(f"Connected to {DATABASE_URL}")
    print(f"Tables present ({len(tables)}): {tables}")
