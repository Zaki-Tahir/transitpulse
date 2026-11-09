"""Fans Redis pub/sub messages out to connected WebSockets.

Each API pod holds ONE Redis subscription and forwards messages to its browsers in memory,
instead of one subscription per browser. Pods scale horizontally behind the load balancer;
every pod receives every vehicle delta.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict

from redis.asyncio import Redis

from .ingest import STATUS_CHANNEL, VEHICLES_CHANNEL

log = logging.getLogger("transitpulse.hub")

COMMUTE_PATTERN = "tp:commute:*"


class Client:
    """One browser. Messages queue up per client; a client that falls too far behind is
    disconnected and will resync from a fresh snapshot when it reconnects."""

    def __init__(self, client_id: str | None, max_queue: int = 200) -> None:
        self.client_id = client_id
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=max_queue)
        self.overflowed = asyncio.Event()

    def offer(self, message: str) -> None:
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.overflowed.set()


class Hub:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self.clients: set[Client] = set()
        self.by_client_id: dict[str, set[Client]] = defaultdict(set)
        self._task: asyncio.Task[None] | None = None

    def add(self, client: Client) -> None:
        self.clients.add(client)
        if client.client_id:
            self.by_client_id[client.client_id].add(client)

    def remove(self, client: Client) -> None:
        self.clients.discard(client)
        if client.client_id:
            self.by_client_id[client.client_id].discard(client)
            if not self.by_client_id[client.client_id]:
                del self.by_client_id[client.client_id]

    def dispatch(self, channel: str, data: str) -> None:
        if channel in (VEHICLES_CHANNEL, STATUS_CHANNEL):
            for c in self.clients:
                c.offer(data)
        elif channel.startswith("tp:commute:"):
            for c in self.by_client_id.get(channel.removeprefix("tp:commute:"), ()):
                c.offer(data)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _listen(self) -> None:
        while True:
            try:
                pubsub = self.redis.pubsub()
                await pubsub.subscribe(VEHICLES_CHANNEL, STATUS_CHANNEL)
                await pubsub.psubscribe(COMMUTE_PATTERN)
                async for msg in pubsub.listen():
                    if msg["type"] in ("message", "pmessage"):
                        self.dispatch(msg["channel"], msg["data"])
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("redis subscription lost; reconnecting")
                await asyncio.sleep(1)
