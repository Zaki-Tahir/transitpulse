"""The ingest worker. Every 15 seconds it polls the MTA feeds, works out where every train is,
and publishes only what changed to Redis, where the API pods pick it up and push it to browsers.

Run exactly one of these (the Helm chart uses a single-replica Deployment with Recreate strategy).

    uv run python -m transitpulse.ingest
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import asyncpg
import httpx
from redis.asyncio import Redis

from . import db
from .alerts import LineStatus, line_statuses
from .commutes import CommuteState, evaluate, should_notify
from .config import Settings, get_settings
from .delta import Packed, delta_message, diff, dumps, naive_message, pack, snapshot_message
from .gtfs_static import SegmentIndex
from .realtime import TripState, arrivals_by_stop, parse_feed, to_motion

log = logging.getLogger("transitpulse.ingest")

# Redis keys and channels shared with the API.
SNAPSHOT_KEY = "tp:snapshot"
STATUS_KEY = "tp:status"
ARRIVALS_KEY = "tp:arrivals"
STATS_KEY = "tp:stats"
COMMUTE_STATE_KEY = "tp:commute-state"
VEHICLES_CHANNEL = "tp:vehicles"
STATUS_CHANNEL = "tp:status"


async def get_str(redis: Redis, key: str) -> str | None:
    """redis-py types every read as bytes | str; the clients here use decode_responses=True."""
    value = await redis.get(key)
    return value.decode() if isinstance(value, bytes) else value


def commute_channel(client_id: str) -> str:
    return f"tp:commute:{client_id}"


def status_payload(statuses: dict[str, LineStatus]) -> dict[str, dict[str, str | None]]:
    return {
        r: {"status": s.status.name.lower(), "label": s.status.label, "summary": s.summary}
        for r, s in statuses.items()
    }


@dataclass(slots=True)
class TickStats:
    at: int
    vehicles: int
    updated: int
    removed: int
    feeds_ok: int
    feeds_failed: int
    naive_bytes: int
    delta_bytes: int
    commute_alerts: int


class Ingestor:
    def __init__(self, settings: Settings, pool: asyncpg.Pool, redis: Redis, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.pool = pool
        self.redis = redis
        self.http = http
        self.previous: dict[str, Packed] = {}
        self.statuses: dict[str, LineStatus] = {}
        self.route_ids: list[str] = []
        self.coords: dict[str, tuple[float, float]] = {}
        self.segments = SegmentIndex([])
        self.reference_loaded_at = 0.0
        self.resumed = False

    async def resume(self) -> None:
        """Picks up where the last worker left off, so a restart or deploy doesn't re-send every
        train to every connected browser."""
        self.resumed = True
        raw = await get_str(self.redis, SNAPSHOT_KEY)
        if raw:
            vehicles = json.loads(raw)["v"]
            self.previous = {v[0]: tuple(v) for v in vehicles}
            log.info("resumed from snapshot with %d trains", len(self.previous))

    async def load_reference(self) -> None:
        routes, self.coords, segments = await db.load_reference(self.pool)
        self.route_ids = [r["route_id"] for r in routes]
        self.segments = SegmentIndex(segments)
        self.reference_loaded_at = time.monotonic()
        log.info(
            "reference data: %d stations, %d lines, %d hops",
            len(self.coords),
            len(routes),
            len(self.segments),
        )

    async def fetch(self, url: str) -> bytes:
        if url.startswith("file://"):
            return await asyncio.to_thread(Path(unquote(urlparse(url).path)).read_bytes)
        headers = {"x-api-key": self.settings.mta_api_key} if self.settings.mta_api_key else {}
        res = await self.http.get(url, headers=headers)
        res.raise_for_status()
        return res.content

    async def tick(self, now: int | None = None) -> TickStats:
        now = now or int(time.time())
        if not self.resumed:
            await self.resume()
        if not self.coords or time.monotonic() - self.reference_loaded_at > 3600:
            await self.load_reference()

        # One slow or broken feed shouldn't take the other lines off the map.
        results = await asyncio.gather(
            *(self.fetch(u) for u in self.settings.feed_urls), return_exceptions=True
        )
        trips: list[TripState] = []
        failed = 0
        for url, result in zip(self.settings.feed_urls, results, strict=True):
            if isinstance(result, BaseException):
                failed += 1
                log.warning("feed failed: %s: %s", url, result)
            else:
                trips.extend(parse_feed(result))

        motions = [m for t in trips if (m := to_motion(t, now, self.segments, set(self.coords)))]
        current = {m.id: pack(m) for m in motions}
        # If every feed failed, keep showing the last known trains rather than emptying the map.
        if failed == len(self.settings.feed_urls):
            current = self.previous
        updated, removed, current = diff(self.previous, current)

        delta = delta_message(now, updated, removed)
        arrivals = arrivals_by_stop(trips, now)
        pipe = self.redis.pipeline()
        pipe.set(SNAPSHOT_KEY, snapshot_message(now, current))
        pipe.set(ARRIVALS_KEY, dumps({"t": now, "stops": arrivals}))
        if updated or removed:
            pipe.publish(VEHICLES_CHANNEL, delta)
        await pipe.execute()

        await self.update_statuses(now)
        alerts = await self.check_commutes(now, arrivals)

        stats = TickStats(
            at=now,
            vehicles=len(current),
            updated=len(updated),
            removed=len(removed),
            feeds_ok=len(results) - failed,
            feeds_failed=failed,
            naive_bytes=len(naive_message(now, motions, self.coords)),
            delta_bytes=len(delta),
            commute_alerts=alerts,
        )
        await self.redis.set(STATS_KEY, dumps(asdict(stats)))
        self.previous = current
        return stats

    async def update_statuses(self, now: int) -> None:
        try:
            statuses = line_statuses(await self.fetch(self.settings.alerts_url), self.route_ids, now)
        except Exception as err:  # alerts are nice to have; never fail the tick over them
            log.warning("alerts feed failed: %s", err)
            return
        if statuses != self.statuses:
            payload = dumps(status_payload(statuses))
            await self.redis.set(STATUS_KEY, payload)
            await self.redis.publish(STATUS_CHANNEL, dumps({"type": "status", "lines": json.loads(payload)}))
            self.statuses = statuses

    async def check_commutes(self, now: int, arrivals: dict[str, dict[str, list[int]]]) -> int:
        commutes = await db.all_commutes(self.pool)
        if not commutes:
            return 0
        raw_states = await self.redis.hgetall(COMMUTE_STATE_KEY)
        previous = {str(k): str(v) for k, v in raw_states.items()}
        sent = 0
        pipe = self.redis.pipeline()
        for c in commutes:
            status = evaluate(c, now, arrivals, self.statuses)
            before = previous.get(c.id)
            if should_notify(CommuteState(before) if before else None, status.state):
                message = {
                    "type": "commute",
                    "id": c.id,
                    "label": c.label,
                    "route": c.route_id,
                    "state": status.state.value,
                    "reason": status.reason,
                    "next": status.next_minutes,
                }
                pipe.publish(commute_channel(c.client_id), dumps(message))
                sent += 1
            pipe.hset(COMMUTE_STATE_KEY, c.id, status.state.value)
        await pipe.execute()
        return sent

    async def run_forever(self) -> None:
        while True:
            started = time.monotonic()
            try:
                s = await self.tick()
                log.info(
                    "tick: %d trains, %d changed, %d gone, %d/%d bytes (delta/naive), %d alerts, "
                    "%d feeds failed",
                    s.vehicles,
                    s.updated,
                    s.removed,
                    s.delta_bytes,
                    s.naive_bytes,
                    s.commute_alerts,
                    s.feeds_failed,
                )
            except Exception:
                log.exception("tick failed")
            await asyncio.sleep(max(0.0, self.settings.poll_seconds - (time.monotonic() - started)))


async def main() -> None:
    settings = get_settings()
    pool = await db.connect(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    async with httpx.AsyncClient(timeout=10) as http:
        await Ingestor(settings, pool, redis, http).run_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
