import asyncio
import json
import logging
from typing import Any
from fastapi import WebSocket, WebSocketDisconnect

from app.core.redis import get_redis_client, get_or_reconnect_redis, INSTANCE_ID

logger = logging.getLogger("app.auctions.ws")

# Module-level alias for backward compatibility with tests patching redis_client directly
redis_client: Any = None


class AuctionConnectionManager:
    def __init__(self):
        # Maps auction_id -> set of active WebSocket connections (ref-counted)
        self._connections: dict[int, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        # Invariant: at most 1 Redis subscriber task per auction_id
        self._redis_tasks: dict[int, asyncio.Task] = {}

    async def connect(self, auction_id: int, websocket: WebSocket):
        if websocket.client_state.name == "CONNECTING":
            await websocket.accept()
        async with self._lock:
            if auction_id not in self._connections:
                self._connections[auction_id] = set()
            self._connections[auction_id].add(websocket)
            
            # Invariant (Correction 1): First local connection for this auction MUST create
            # exactly 1 subscriber task even if Redis is currently None.
            if auction_id not in self._redis_tasks:
                self._redis_tasks[auction_id] = asyncio.create_task(
                    self._listen_redis_channel(auction_id)
                )
        logger.info(
            "WebSocket client connected to auction %s. Active sockets: %s",
            auction_id,
            len(self._connections.get(auction_id, set())),
        )

    async def disconnect(self, auction_id: int, websocket: WebSocket):
        task_to_cancel: asyncio.Task | None = None
        async with self._lock:
            if auction_id in self._connections:
                self._connections[auction_id].discard(websocket)
                # Invariant: cancel subscriber ONLY when the last socket of this auction disconnects
                if not self._connections[auction_id]:
                    del self._connections[auction_id]
                    if auction_id in self._redis_tasks:
                        task_to_cancel = self._redis_tasks.pop(auction_id)

        if task_to_cancel is not None:
            task_to_cancel.cancel()
            try:
                await task_to_cancel
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug("Error awaiting cancelled auction subscriber task: %s", e)

        logger.info("WebSocket client disconnected from auction %s", auction_id)

    async def broadcast_local(self, auction_id: int, message: dict[str, Any]):
        async with self._lock:
            connections = list(self._connections.get(auction_id, set()))

        dead_connections = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.debug("Failed to send to client on auction %s: %s", auction_id, e)
                dead_connections.append(ws)

        tasks_to_cancel: list[asyncio.Task] = []
        if dead_connections:
            async with self._lock:
                if auction_id in self._connections:
                    for dead in dead_connections:
                        self._connections[auction_id].discard(dead)
                    if not self._connections[auction_id]:
                        del self._connections[auction_id]
                        if auction_id in self._redis_tasks:
                            tasks_to_cancel.append(self._redis_tasks.pop(auction_id))

            for t in tasks_to_cancel:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

    async def _listen_redis_channel(self, auction_id: int):
        channel_name = f"auction:{auction_id}:events"
        logger.info("Redis subscriber task started for %s", channel_name)
        backoff = 1.0
        max_backoff = 10.0
        pubsub = None

        try:
            while True:
                # If no local connections remain for this auction, terminate subscriber
                async with self._lock:
                    if auction_id not in self._connections or not self._connections[auction_id]:
                        break

                # Close previous/broken pubsub before retrying
                if pubsub is not None:
                    try:
                        await pubsub.unsubscribe(channel_name)
                        await pubsub.aclose()
                    except Exception:
                        pass
                    pubsub = None

                try:
                    rc = redis_client or get_redis_client()
                    if rc is None:
                        rc = await get_or_reconnect_redis()
                        if rc is None:
                            await asyncio.sleep(backoff)
                            backoff = min(backoff * 2, max_backoff)
                            continue

                    pubsub = rc.pubsub()
                    await pubsub.subscribe(channel_name)
                    backoff = 1.0  # Reset backoff on successful subscribe
                    logger.debug("Subscribed to Redis channel %s", channel_name)

                    async for message in pubsub.listen():
                        if message["type"] == "message":
                            try:
                                raw_data = json.loads(message["data"])
                                # Parse transport envelope
                                if isinstance(raw_data, dict) and "_meta" in raw_data and "payload" in raw_data:
                                    meta = raw_data.get("_meta", {})
                                    if meta.get("origin") == INSTANCE_ID:
                                        # Self-origin: local broadcast already happened, skip duplicate
                                        continue
                                    clean_payload = raw_data.get("payload")
                                else:
                                    clean_payload = raw_data

                                await self.broadcast_local(auction_id, clean_payload)
                            except Exception as parse_err:
                                logger.error("Error parsing redis pubsub message for auction %s: %s", auction_id, parse_err)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(
                        "Redis subscriber error for auction %s (%s). Reconnecting in %ss...",
                        auction_id,
                        e,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)
        except asyncio.CancelledError:
            logger.info("Redis subscriber task cancelled for %s", channel_name)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(channel_name)
                    await pubsub.aclose()
                except Exception:
                    pass


manager = AuctionConnectionManager()


async def publish_auction_event(auction_id: int, event_data: dict[str, Any]) -> None:
    """
    Publish an auction event:
    1. First broadcast clean event_data to local connected WebSocket clients.
    2. Then package into an internal transport envelope and publish to Redis
       for multi-instance distribution if Redis is configured.
    """
    # 1. Local delivery: local clients always receive the pristine event_data
    try:
        await manager.broadcast_local(auction_id, event_data)
    except Exception as e:
        logger.error("Failed local delivery for auction %s: %s", auction_id, e)

    # 2. Redis pub/sub delivery: wrapped in internal transport envelope
    try:
        rc = redis_client or get_redis_client()
        if rc is None:
            rc = await get_or_reconnect_redis()
        if rc is not None:
            envelope = {
                "_meta": {
                    "origin": INSTANCE_ID,
                },
                "payload": event_data,
            }
            channel_name = f"auction:{auction_id}:events"
            await rc.publish(channel_name, json.dumps(envelope, default=str))
    except Exception as e:
        logger.warning(
            "Redis publish failed for auction %s (%s); local broadcast already delivered.",
            auction_id,
            e,
        )

