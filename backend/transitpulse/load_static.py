"""Downloads the MTA static schedule and loads it into Postgres.

    uv run python -m transitpulse.load_static              # download the current schedule
    uv run python -m transitpulse.load_static gtfs.zip     # or load a local file

Runs as a Kubernetes CronJob once a week; MTA publishes schedule changes ahead of time.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
import time
from pathlib import Path

import httpx

from . import db
from .config import get_settings
from .gtfs_static import read_static

log = logging.getLogger("transitpulse.load_static")


async def main(source: str | None = None) -> None:
    settings = get_settings()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(source) if source else Path(tmp) / "gtfs.zip"
        if not source:
            log.info("downloading %s", settings.static_url)
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                res = await client.get(settings.static_url)
                res.raise_for_status()
                path.write_bytes(res.content)

        started = time.perf_counter()
        data = read_static(path)
        log.info(
            "parsed %d stations, %d routes, %d hops in %.1fs",
            len(data.stations),
            len(data.routes),
            len(data.segments),
            time.perf_counter() - started,
        )

    pool = await db.connect(settings.database_url)
    try:
        await db.migrate(pool)
        await db.replace_static(pool, data)
    finally:
        await pool.close()
    log.info("static schedule loaded")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
