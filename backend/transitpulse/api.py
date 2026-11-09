"""HTTP and WebSocket API.

uv run uvicorn transitpulse.api:app --reload
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import asyncpg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from . import db
from .alerts import LineStatus, Status
from .commutes import Commute, evaluate
from .config import get_settings
from .hub import Client, Hub
from .ingest import ARRIVALS_KEY, SNAPSHOT_KEY, STATS_KEY, STATUS_KEY, get_str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.pool = await db.connect(settings.database_url)
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.hub = Hub(app.state.redis)
    await app.state.hub.start()
    try:
        yield
    finally:
        await app.state.hub.stop()
        await app.state.redis.aclose()
        await app.state.pool.close()


app = FastAPI(title="TransitPulse", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["*"], allow_headers=["*"]
)


def pool(request: Request) -> asyncpg.Pool:
    p: asyncpg.Pool = request.app.state.pool
    return p


def redis(request: Request) -> Redis:
    r: Redis = request.app.state.redis
    return r


Pool = Annotated[asyncpg.Pool, Depends(pool)]
RedisDep = Annotated[Redis, Depends(redis)]


def client_id(x_client_id: Annotated[str, Header()]) -> str:
    try:
        return str(uuid.UUID(x_client_id))
    except ValueError:
        raise HTTPException(400, "X-Client-Id must be a UUID") from None


ClientId = Annotated[str, Depends(client_id)]


async def read_json(r: Redis, key: str) -> Any:
    raw = await get_str(r, key)
    return json.loads(raw) if raw else None


@app.get("/api/health")
async def health(p: Pool, r: RedisDep) -> dict[str, Any]:
    await p.fetchval("SELECT 1")
    stats = await read_json(r, STATS_KEY)
    # Stale data means the ingest worker is down; report it rather than serving a frozen map silently.
    fresh = bool(stats) and time.time() - stats["at"] < 120
    return {"ok": True, "ingest_fresh": fresh, "last_tick": stats}


@app.get("/api/lines")
async def lines(p: Pool, r: RedisDep) -> list[dict[str, Any]]:
    routes, _, _ = await db.load_reference(p)
    status = await read_json(r, STATUS_KEY) or {}
    good = {"status": "good", "label": "Good service", "summary": None}
    return [{**rt, "color": rt["color"], **status.get(rt["route_id"], good)} for rt in routes]


@app.get("/api/stations")
async def stations(p: Pool) -> list[dict[str, Any]]:
    return await db.list_stations(p)


@app.get("/api/stations/near")
async def near(
    p: Pool,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> list[dict[str, Any]]:
    return await db.stations_near(p, lat, lon, limit)


@app.get("/api/stations/{stop_id}/arrivals")
async def arrivals(stop_id: str, p: Pool, r: RedisDep) -> dict[str, Any]:
    station = await db.station(p, stop_id)
    if not station:
        raise HTTPException(404, "station not found")
    data = await read_json(r, ARRIVALS_KEY) or {"t": int(time.time()), "stops": {}}
    now = data["t"]
    directions = {
        d: {
            route: [max(0, round((t - now) / 60)) for t in times[:4]]
            for route, times in data["stops"].get(stop_id + d, {}).items()
        }
        for d in ("N", "S")
    }
    return {**station, "updated": now, "arrivals": directions}


class NewCommute(BaseModel):
    route_id: str = Field(min_length=1, max_length=4)
    stop_id: str = Field(pattern=r"^[A-Z0-9]{2,5}[NS]$", description="Station id plus direction, e.g. A27N")
    label: str = Field(min_length=1, max_length=60)
    threshold_minutes: int = Field(default=12, ge=2, le=60)


async def with_status(r: Redis, commutes: list[Commute]) -> list[dict[str, Any]]:
    data = await read_json(r, ARRIVALS_KEY) or {"t": int(time.time()), "stops": {}}
    raw_status = await read_json(r, STATUS_KEY) or {}
    lines = {k: LineStatus(k, Status[v["status"].upper()], v["summary"]) for k, v in raw_status.items()}
    out = []
    for c in commutes:
        s = evaluate(c, data["t"], data["stops"], lines)
        out.append(
            {
                "id": c.id,
                "route_id": c.route_id,
                "stop_id": c.stop_id,
                "label": c.label,
                "threshold_minutes": c.threshold_minutes,
                "state": s.state.value,
                "next_minutes": s.next_minutes,
                "reason": s.reason,
            }
        )
    return out


@app.get("/api/commutes")
async def list_commutes(cid: ClientId, p: Pool, r: RedisDep) -> list[dict[str, Any]]:
    return await with_status(r, await db.client_commutes(p, cid))


@app.post("/api/commutes", status_code=201)
async def create_commute(body: NewCommute, cid: ClientId, p: Pool, r: RedisDep) -> dict[str, Any]:
    station = await db.station(p, body.stop_id[:-1])
    if not station or body.route_id not in station["routes"]:
        raise HTTPException(422, f"The {body.route_id} doesn't stop at that station")
    if len(await db.client_commutes(p, cid)) >= 10:
        raise HTTPException(422, "You can save up to 10 commutes")
    c = await db.add_commute(p, cid, body.route_id, body.stop_id, body.label, body.threshold_minutes)
    return (await with_status(r, [c]))[0]


@app.delete("/api/commutes/{commute_id}", status_code=204)
async def remove_commute(commute_id: uuid.UUID, cid: ClientId, p: Pool) -> None:
    if not await db.delete_commute(p, cid, str(commute_id)):
        raise HTTPException(404, "commute not found")


@app.websocket("/ws")
async def live(ws: WebSocket, client_id: str | None = None) -> None:
    """Sends a snapshot of every train, then deltas, line status changes, and this client's
    commute alerts as they happen."""
    await ws.accept()
    hub: Hub = ws.app.state.hub
    r: Redis = ws.app.state.redis
    client = Client(client_id)
    hub.add(client)  # register before reading the snapshot so no delta is missed in between
    try:
        snapshot = await get_str(r, SNAPSHOT_KEY)
        if snapshot:
            await ws.send_text(snapshot)
        status = await get_str(r, STATUS_KEY)
        if status:
            await ws.send_text(json.dumps({"type": "status", "lines": json.loads(status)}))

        async def pump() -> None:
            while True:
                await ws.send_text(await client.queue.get())

        async def drain_incoming() -> None:
            while True:
                await ws.receive_text()  # we don't expect messages, but this notices disconnects

        tasks = [
            asyncio.create_task(pump()),
            asyncio.create_task(drain_incoming()),
            asyncio.create_task(client.overflowed.wait()),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        if client.overflowed.is_set():
            await ws.close(code=1013, reason="too slow; reconnect to resync")
        for t in done:
            if (exc := t.exception()) and not isinstance(exc, WebSocketDisconnect):
                raise exc
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(client)
        with contextlib.suppress(Exception):
            await ws.close()
