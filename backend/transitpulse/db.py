"""Postgres/PostGIS access: migrations, the static schedule, and saved commutes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import asyncpg

from .commutes import Commute
from .gtfs_static import Segment, StaticData

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


async def connect(dsn: str) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10)
    assert pool is not None
    return pool


async def migrate(pool: asyncpg.Pool) -> list[str]:
    """Applies migrations/*.sql in order, once each. Safe to run from several pods: an advisory
    lock makes the others wait."""
    applied: list[str] = []
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(7243)")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations"
            " (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())"
        )
        done = {r["name"] for r in await conn.fetch("SELECT name FROM schema_migrations")}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name not in done:
                await conn.execute(path.read_text())
                await conn.execute("INSERT INTO schema_migrations (name) VALUES ($1)", path.name)
                applied.append(path.name)
    return applied


async def replace_static(pool: asyncpg.Pool, data: StaticData) -> None:
    """Swaps in a new schedule in one transaction, so readers never see a half-loaded one."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("TRUNCATE routes, stations, segments")
        await conn.executemany(
            "INSERT INTO routes VALUES ($1, $2, $3, $4, $5, $6)",
            [
                (r.route_id, r.short_name, r.long_name, r.color, r.text_color, r.sort_order)
                for r in data.routes
            ],
        )
        await conn.executemany(
            "INSERT INTO stations VALUES ($1, $2, ST_SetSRID(ST_MakePoint($3, $4), 4326)::geography, $5)",
            [(s.stop_id, s.name, s.lon, s.lat, list(s.routes)) for s in data.stations],
        )
        await conn.copy_records_to_table(
            "segments",
            records=[(s.route_id, s.from_stop, s.to_stop, s.typical_seconds, s.trips) for s in data.segments],
        )


async def load_reference(
    pool: asyncpg.Pool,
) -> tuple[list[dict[str, Any]], dict[str, tuple[float, float]], list[Segment]]:
    async with pool.acquire() as conn:
        routes = [dict(r) for r in await conn.fetch("SELECT * FROM routes ORDER BY sort_order")]
        stations = await conn.fetch(
            "SELECT stop_id, ST_Y(location::geometry) lat, ST_X(location::geometry) lon FROM stations"
        )
        segments = await conn.fetch("SELECT * FROM segments")
    coords = {s["stop_id"]: (s["lat"], s["lon"]) for s in stations}
    return routes, coords, [Segment(**dict(s)) for s in segments]


async def list_stations(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """SELECT stop_id AS id, name, routes,
                  ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lon
           FROM stations WHERE cardinality(routes) > 0 ORDER BY name"""
    )
    return [dict(r) for r in rows]


async def stations_near(pool: asyncpg.Pool, lat: float, lon: float, limit: int) -> list[dict[str, Any]]:
    """Nearest stations by walking-ish distance, using the GiST index (<-> is a KNN search)."""
    rows = await pool.fetch(
        """SELECT stop_id AS id, name, routes,
                  ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lon,
                  round(ST_Distance(location, ST_MakePoint($2, $1)::geography)) AS meters
           FROM stations
           WHERE cardinality(routes) > 0
           ORDER BY location <-> ST_MakePoint($2, $1)::geography
           LIMIT $3""",
        lat,
        lon,
        limit,
    )
    return [dict(r) for r in rows]


async def station(pool: asyncpg.Pool, stop_id: str) -> dict[str, Any] | None:
    row = await pool.fetchrow("SELECT stop_id AS id, name, routes FROM stations WHERE stop_id = $1", stop_id)
    return dict(row) if row else None


def _commute(row: asyncpg.Record) -> Commute:
    return Commute(
        id=str(row["id"]),
        client_id=str(row["client_id"]),
        route_id=row["route_id"],
        stop_id=row["stop_id"],
        label=row["label"],
        threshold_minutes=row["threshold_minutes"],
    )


async def all_commutes(pool: asyncpg.Pool) -> list[Commute]:
    return [_commute(r) for r in await pool.fetch("SELECT * FROM commutes")]


async def client_commutes(pool: asyncpg.Pool, client_id: str) -> list[Commute]:
    rows = await pool.fetch("SELECT * FROM commutes WHERE client_id = $1 ORDER BY created_at", client_id)
    return [_commute(r) for r in rows]


async def add_commute(
    pool: asyncpg.Pool, client_id: str, route_id: str, stop_id: str, label: str, threshold: int
) -> Commute:
    row = await pool.fetchrow(
        """INSERT INTO commutes (client_id, route_id, stop_id, label, threshold_minutes)
           VALUES ($1, $2, $3, $4, $5) RETURNING *""",
        client_id,
        route_id,
        stop_id,
        label,
        threshold,
    )
    assert row is not None
    return _commute(row)


async def delete_commute(pool: asyncpg.Pool, client_id: str, commute_id: str) -> bool:
    result: str = await pool.execute(
        "DELETE FROM commutes WHERE id = $1 AND client_id = $2", commute_id, client_id
    )
    return result.endswith("1")
