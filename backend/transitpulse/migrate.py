"""Applies database migrations. Runs as a Helm pre-install/pre-upgrade hook Job."""

import asyncio
import logging

from . import db
from .config import get_settings


async def main() -> None:
    pool = await db.connect(get_settings().database_url)
    try:
        applied = await db.migrate(pool)
        logging.info("applied %s", applied or "nothing (up to date)")
    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
