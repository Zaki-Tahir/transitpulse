from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis

from transitpulse import db
from transitpulse.api import app
from transitpulse.config import Settings
from transitpulse.ingest import Ingestor

from ..feeds import alerts_feed, vehicle_feed
from .conftest import DATABASE_URL, REDIS_URL

pytestmark = pytest.mark.integration
CLIENT = "0b6c3f6e-3d4f-4a52-9a0e-1c9a3b8d2f10"


def ingest_once(
    tmp: Path,
    trains: list[dict[str, object]],
    alerts: list[dict[str, object]] | None = None,
    now: int | None = None,
) -> None:
    """Runs one ingest tick. Each call is a fresh worker, like a restart; it resumes from Redis."""
    import time

    now = now or int(time.time())

    async def go() -> None:
        feed = tmp / "v.pb"
        feed.write_bytes(
            vehicle_feed([{**t, "upcoming": [(s, now + eta) for s, eta in t["upcoming"]]} for t in trains])  # type: ignore[attr-defined]
        )
        al = tmp / "a.pb"
        al.write_bytes(alerts_feed(alerts or []))
        settings = Settings(
            feed_urls=[feed.as_uri()], alerts_url=al.as_uri(), database_url=DATABASE_URL, redis_url=REDIS_URL
        )
        pool = await db.connect(DATABASE_URL)
        redis = Redis.from_url(REDIS_URL, decode_responses=True)
        try:
            async with httpx.AsyncClient() as http:
                await Ingestor(settings, pool, redis, http).tick(now=now)
        finally:
            await redis.aclose()
            await pool.close()

    asyncio.run(go())


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_lines_and_stations(client: TestClient, tmp_path: Path):
    ingest_once(tmp_path, [{"id": "t1", "route": "A", "upcoming": [("102N", 60)]}])
    with client:
        health = client.get("/api/health").json()
        assert health["ok"] and health["ingest_fresh"] and health["last_tick"]["vehicles"] == 1

        lines = client.get("/api/lines").json()
        assert [(line["route_id"], line["status"]) for line in lines] == [("A", "good"), ("B", "good")]

        stations = client.get("/api/stations").json()
        assert {s["id"] for s in stations} == {"101", "102", "103", "201"}


def test_nearest_stations_use_postgis(client: TestClient):
    with client:
        # Just north of station 102 (40.710, -74.000).
        near = client.get("/api/stations/near", params={"lat": 40.7105, "lon": -74.0, "limit": 2}).json()
    assert near[0]["id"] == "102"
    assert near[0]["meters"] < 100


def test_station_arrivals(client: TestClient, tmp_path: Path):
    ingest_once(
        tmp_path,
        [
            {"id": "t1", "route": "A", "upcoming": [("102N", 120), ("103N", 300)]},
            {"id": "t2", "route": "B", "upcoming": [("102N", 600)]},
        ],
    )
    with client:
        res = client.get("/api/stations/102/arrivals").json()
        assert res["name"] == "Bravo"
        assert res["arrivals"]["N"] == {"A": [2], "B": [10]}
        assert client.get("/api/stations/nope/arrivals").status_code == 404


def test_commutes_are_per_client_and_validated(client: TestClient, tmp_path: Path):
    ingest_once(tmp_path, [{"id": "t1", "route": "A", "upcoming": [("103N", 240)]}])
    headers = {"X-Client-Id": CLIENT}
    with client:
        created = client.post(
            "/api/commutes", headers=headers, json={"route_id": "A", "stop_id": "103N", "label": "Work"}
        )
        assert created.status_code == 201
        body = created.json()
        assert body["state"] == "on_time" and body["next_minutes"] == [4]

        # The B doesn't stop at station 103.
        bad = client.post(
            "/api/commutes", headers=headers, json={"route_id": "B", "stop_id": "103N", "label": "x"}
        )
        assert bad.status_code == 422

        other = {"X-Client-Id": "5d2f0f5e-7c4b-4f0e-8a2e-0d3f6e9b1a22"}
        assert client.get("/api/commutes", headers=other).json() == []
        assert client.delete(f"/api/commutes/{body['id']}", headers=other).status_code == 404
        assert client.delete(f"/api/commutes/{body['id']}", headers=headers).status_code == 204
        assert client.get("/api/commutes", headers={"X-Client-Id": "not-a-uuid"}).status_code == 400


def test_websocket_sends_snapshot_then_deltas(client: TestClient, tmp_path: Path):
    import time

    now = int(time.time())
    ingest_once(tmp_path, [{"id": "t1", "route": "A", "upcoming": [("102N", 60)]}], now=now)
    with client, client.websocket_connect(f"/ws?client_id={CLIENT}") as ws:
        first = json.loads(ws.receive_text())
        assert first["type"] == "snapshot" and [v[0] for v in first["v"]] == ["t1"]
        assert json.loads(ws.receive_text())["type"] == "status"

        # A new train appears. The restarted worker resumes from Redis, so only t9 is sent.
        trains = [
            {"id": "t1", "route": "A", "upcoming": [("102N", 60)]},
            {"id": "t9", "route": "B", "upcoming": [("102N", 90)]},
        ]
        ingest_once(tmp_path, trains, now=now)
        msg = json.loads(ws.receive_text())
        while msg["type"] != "delta":
            msg = json.loads(ws.receive_text())
        assert [v[0] for v in msg["u"]] == ["t9"]
