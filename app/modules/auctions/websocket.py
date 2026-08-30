import asyncio
import json
import logging
from typing import Any
from fastapi import WebSocket, WebSocketDisconnect

from app.core.redis import redis_client

logger = logging.getLogger("app.auctions.ws")


class AuctionConnectionManager:
    def __init__(self):
        # Maps auction_id -> set of active WebSocket connections
        self._connections: dict[int, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._redis_tasks: dict[int, asyncio.Task] = {}

    async def connect(self, auction_id: int, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            if auction_id not in self._connections:
                self._connections[auction_id] = set()
                # Start redis listener for this auction_id if redis is available
                if redis_client is not None:
                    self._redis_tasks[auction_id] = asyncio.create_task(
                        self._listen_redis_channel(auction_id)
                    )
            self._connections[auction_id].add(websocket)
        logger.info(f"WebSocket client connected to auction {auction_id}. Total: {len(self._connections[auction_id])}")

    async def disconnect(self, auction_id: int, websocket: WebSocket):
        async with self._lock:
            if auction_id in self._connections:
                self._connections[auction_id].discard(websocket)
                if not self._connections[auction_id]:
                    del self._connections[auction_id]
                    # Cancel redis listener task if no clients left
                    if auction_id in self._redis_tasks:
                        task = self._redis_tasks.pop(auction_id)
                        task.cancel()
        logger.info(f"WebSocket client disconnected from auction {auction_id}")

    async def broadcast_local(self, auction_id: int, message: dict[str, Any]):
        async with self._lock:
            connections = list(self._connections.get(auction_id, set()))

        dead_connections = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.debug(f"Failed to send to client on auction {auction_id}: {e}")
                dead_connections.append(ws)

        if dead_connections:
            async with self._lock:
                if auction_id in self._connections:
                    for dead in dead_connections:
                        self._connections[auction_id].discard(dead)

    async def _listen_redis_channel(self, auction_id: int):
        channel_name = f"auction:{auction_id}:events"
        try:
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(channel_name)
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await self.broadcast_local(auction_id, data)
                    except Exception as e:
                        logger.error(f"Error parsing redis pubsub message for auction {auction_id}: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Redis pubsub listener failed for auction {auction_id}: {e}")


manager = AuctionConnectionManager()


async def publish_auction_event(auction_id: int, event_data: dict[str, Any]) -> None:
    """
    Publish an auction event:
    1. First broadcast to local connected WebSocket clients.
    2. Then publish to Redis pub/sub for multi-instance distribution if Redis is configured.
    """
    try:
        await manager.broadcast_local(auction_id, event_data)
        if redis_client is not None:
            channel_name = f"auction:{auction_id}:events"
            await redis_client.publish(channel_name, json.dumps(event_data, default=str))
    except Exception as e:
        logger.error(f"Failed to publish auction event for auction {auction_id}: {e}")
