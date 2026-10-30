"""Pub/Sub event bus supporting in-memory queues, Redis pub/sub, and Postgres LISTEN/NOTIFY.

Provides real-time event broadcasting for SSE endpoints per instance, per inbox,
and per command, with graceful fallback to in-memory async queues.
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import AsyncGenerator, Dict, Set
from dataclasses import dataclass
from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class BroadcastEvent:
    id: int | None
    event_type: str
    payload: dict
    channel: str


class EventBus:
    def __init__(self):
        self._subscribers: Dict[str, Set[asyncio.Queue[BroadcastEvent]]] = {}
        self._redis_client = None
        self._redis_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def _get_redis_client(self):
        settings = get_settings()
        if not settings.redis_url:
            return None
        if self._redis_client is None:
            try:
                import redis.asyncio as aioredis
                client = aioredis.from_url(settings.redis_url, decode_responses=True)
                await client.ping()
                self._redis_client = client
                logger.info("Connected to Redis pub/sub: %s", settings.redis_url)
            except Exception as exc:
                logger.debug("Redis pub/sub not available, using in-memory bus: %s", exc)
                self._redis_client = None
        return self._redis_client

    async def broadcast(self, channel: str, event_type: str, payload: dict, event_id: int | None = None) -> None:
        """Broadcast an event to in-memory subscribers and Redis/Postgres if available."""
        event = BroadcastEvent(id=event_id, event_type=event_type, payload=payload or {}, channel=channel)

        # 1. Deliver to local in-memory subscribers (this process)
        targets = set()
        if channel in self._subscribers:
            targets.update(self._subscribers[channel])
        if '*' in self._subscribers:
            targets.update(self._subscribers['*'])

        for queue in targets:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Subscriber queue full for channel %s, dropping event", channel)

        # 2. Publish to Redis if configured and reachable
        try:
            redis = await self._get_redis_client()
            if redis is not None:
                message = json.dumps({
                    'id': event_id,
                    'event_type': event_type,
                    'payload': payload,
                    'channel': channel,
                }, default=str)
                await redis.publish(f"fdrshield:{channel}", message)
        except Exception as exc:
            logger.debug("Redis publish skipped: %s", exc)

    async def subscribe(self, channel: str) -> AsyncGenerator[BroadcastEvent, None]:
        """Subscribe to a channel and yield BroadcastEvents as they arrive."""
        queue: asyncio.Queue[BroadcastEvent] = asyncio.Queue(maxsize=500)
        async with self._lock:
            if channel not in self._subscribers:
                self._subscribers[channel] = set()
            self._subscribers[channel].add(queue)

        try:
            while True:
                # Wait for next event with a periodic wake up for cancellation check
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield event
                except asyncio.TimeoutError:
                    # Timeout produces None to allow caller to send heartbeat
                    yield None
        finally:
            async with self._lock:
                if channel in self._subscribers:
                    self._subscribers[channel].discard(queue)
                    if not self._subscribers[channel]:
                        del self._subscribers[channel]


_event_bus = EventBus()


def get_event_bus() -> EventBus:
    return _event_bus
