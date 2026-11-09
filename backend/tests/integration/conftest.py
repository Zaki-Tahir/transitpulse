"""Integration tests run against real PostGIS and Redis (`docker compose up -d db redis`).

They use a separate database and Redis db so they never touch development data.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault(
    "TP_DATABASE_URL", "postgresql://transitpulse:transitpulse@localhost:5432/transitpulse_test"
)
os.environ.setdefault("TP_REDIS_URL", "redis://localhost:6379/15")

if "test" not in os.environ["TP_DATABASE_URL"]:
    raise RuntimeError("Integration tests wipe the database; TP_DATABASE_URL must point at a *test* database")

from redis.asyncio import Redis

from transitpulse import db
from transitpulse.gtfs_static import read_static

from ..feeds import write_static_zip

DATABASE_URL = os.environ["TP_DATABASE_URL"]
REDIS_URL = os.environ["TP_REDIS_URL"]


async def _reset(tmp: Path) -> None:
    pool = await db.connect(DATABASE_URL)
    try:
        await pool.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
        await db.migrate(pool)
        await db.replace_static(pool, read_static(write_static_zip(tmp / "gtfs.zip")))
    finally:
        await pool.close()
    redis = Redis.from_url(REDIS_URL)
    await redis.flushdb()
    await redis.aclose()


@pytest.fixture(autouse=True)
def fresh_state(tmp_path: Path) -> Iterator[None]:
    """Every test starts from a freshly migrated database with the tiny test network loaded."""
    asyncio.run(_reset(tmp_path))
    yield
