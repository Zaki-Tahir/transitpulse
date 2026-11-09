from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from redis.asyncio import Redis

from transitpulse import db
from transitpulse.config import Settings
from transitpulse.ingest import (
    ARRIVALS_KEY,
    SNAPSHOT_KEY,
    STATUS_KEY,
    VEHICLES_CHANNEL,
    Ingestor,
    commute_channel,
)

from ..feeds import alerts_feed, vehicle_feed
from .conftest import DATABASE_URL, REDIS_URL

pytestmark = pytest.mark.integration
NOW = 2_000_000_000
CLIENT = "6f1c2a52-8a3e-4b8e-9a51-2a0c9d3c1e11"


def write(tmp: Path, name: str, data: bytes) -> str:
    path = tmp / name
    path.write_bytes(data)
    return path.as_uri()


async def run_ticks(tmp: Path, ticks: list[tuple[list[dict[str, object]], list[dict[str, object]]]]):
    """Runs the ingestor once per (vehicle feed, alerts) pair and collects everything it published."""
    feed = tmp / "vehicles.pb"
    alerts = tmp / "alerts.pb"
    feed.write_bytes(vehicle_feed([]))
    alerts.write_bytes(alerts_feed([]))
    settings = Settings(
        feed_urls=[feed.as_uri()], alerts_url=alerts.as_uri(), database_url=DATABASE_URL, redis_url=REDIS_URL
    )

    pool = await db.connect(DATABASE_URL)
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe(VEHICLES_CHANNEL)
    await pubsub.psubscribe("tp:commute:*")
    published: list[tuple[str, dict[str, object]]] = []
    stats = []
    try:
        await db.add_commute(pool, CLIENT, "A", "103N", "To work", 5)
        async with httpx.AsyncClient() as http:
            ingestor = Ingestor(settings, pool, redis, http)
            for i, (trains, alert_list) in enumerate(ticks):
                feed.write_bytes(vehicle_feed(trains))
                alerts.write_bytes(alerts_feed(alert_list))
                stats.append(await ingestor.tick(now=NOW + i * 15))
        await asyncio.sleep(0.2)
        while msg := await pubsub.get_message(timeout=0.2):
            if msg["type"] in ("message", "pmessage"):
                published.append((msg["channel"], json.loads(msg["data"])))
        snapshot = json.loads(await redis.get(SNAPSHOT_KEY))
        status = json.loads(await redis.get(STATUS_KEY))
        arrivals = json.loads(await redis.get(ARRIVALS_KEY))
    finally:
        await pubsub.aclose()
        await redis.aclose()
        await pool.close()
    return stats, published, snapshot, status, arrivals


def train(tid: str, to: str, eta: int) -> dict[str, object]:
    return {"id": tid, "route": "A", "stop": to, "upcoming": [(to, NOW + eta)]}


def test_publishes_only_changes_between_ticks(tmp_path: Path):
    stats, published, snapshot, _, _ = asyncio.run(
        run_ticks(
            tmp_path,
            [
                ([train("t1", "102N", 60), train("t2", "103N", 90)], []),
                ([train("t1", "102N", 60), train("t2", "103N", 90)], []),  # same predictions, next poll
                ([train("t1", "102N", 105), train("t3", "103N", 80)], []),  # t1 delayed, t2 gone, t3 new
            ],
        )
    )
    vehicle_msgs = [m for ch, m in published if ch == VEHICLES_CHANNEL]

    assert stats[0].vehicles == 2 and stats[0].updated == 2
    assert stats[1].updated == 0  # nothing changed, so nothing was published
    assert len(vehicle_msgs) == 2
    last = vehicle_msgs[-1]
    assert [v[0] for v in last["u"]] == ["t1", "t3"]
    assert last["r"] == ["t2"]
    assert {v[0] for v in snapshot["v"]} == {"t1", "t3"}
    assert stats[2].delta_bytes < stats[2].naive_bytes


def test_line_status_and_commute_alert_on_delay(tmp_path: Path):
    delay = [
        {"id": "lmm:alert:1", "routes": ["A"], "text": "[A] trains are running with delays", "periods": []}
    ]
    stats, published, _, status, arrivals = asyncio.run(
        run_ticks(
            tmp_path,
            [
                ([train("t1", "103N", 120)], []),
                ([train("t1", "103N", 105)], delay),
                ([train("t1", "103N", 90)], delay),  # still late: no second alert
            ],
        )
    )
    alerts = [(ch, m) for ch, m in published if ch.startswith("tp:commute:")]

    assert status["A"] == {
        "status": "delays",
        "label": "Delays",
        "summary": "A trains are running with delays",
    }
    assert len(alerts) == 1
    channel, alert = alerts[0]
    assert channel == commute_channel(CLIENT)
    assert alert["label"] == "To work" and alert["state"] == "late"
    assert arrivals["stops"]["103N"]["A"] == [NOW + 30 + 90 - 30]
    assert [s.commute_alerts for s in stats] == [0, 1, 0]


def test_a_broken_feed_keeps_the_last_known_trains(tmp_path: Path):
    async def scenario():
        good = tmp_path / "good.pb"
        good.write_bytes(vehicle_feed([train("t1", "102N", 60)]))
        settings = Settings(
            feed_urls=[good.as_uri(), (tmp_path / "missing.pb").as_uri()],
            alerts_url=(tmp_path / "missing-alerts.pb").as_uri(),
            database_url=DATABASE_URL,
            redis_url=REDIS_URL,
        )
        pool = await db.connect(DATABASE_URL)
        redis = Redis.from_url(REDIS_URL, decode_responses=True)
        try:
            async with httpx.AsyncClient() as http:
                ing = Ingestor(settings, pool, redis, http)
                first = await ing.tick(now=NOW)
                good.unlink()  # now every feed fails
                second = await ing.tick(now=NOW + 15)
                snap = json.loads(await redis.get(SNAPSHOT_KEY))
        finally:
            await redis.aclose()
            await pool.close()
        return first, second, snap

    first, second, snap = asyncio.run(scenario())
    assert (first.feeds_ok, first.feeds_failed, first.vehicles) == (1, 1, 1)
    assert (second.feeds_ok, second.vehicles, second.removed) == (0, 1, 0)
    assert [v[0] for v in snap["v"]] == ["t1"]
