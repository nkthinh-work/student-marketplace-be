import asyncio
import json
import logging
from typing import Any, Optional
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.database import SessionLocal
from app.core.redis import redis_client
from app.modules.auth.dependencies import authenticate_user_token

logger = logging.getLogger("app.orders.ws")


class UserConnectionManager:
    def __init__(self):
        # Maps user_id -> set of active WebSocket connections
        self._connections: dict[int, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._redis_tasks: dict[int, asyncio.Task] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = set()
                if redis_client is not None:
                    self._redis_tasks[user_id] = asyncio.create_task(
                        self._listen_redis_channel(user_id)
                    )
            self._connections[user_id].add(websocket)
        logger.info(f"Private user socket connected for user_id={user_id}. Connections: {len(self._connections[user_id])}")

    async def disconnect(self, user_id: int, websocket: WebSocket):
        async with self._lock:
            if user_id in self._connections:
                self._connections[user_id].discard(websocket)
                if not self._connections[user_id]:
                    del self._connections[user_id]
                    if user_id in self._redis_tasks:
                        task = self._redis_tasks.pop(user_id)
                        task.cancel()
        logger.info(f"Private user socket disconnected for user_id={user_id}")

    async def send_to_user_local(self, user_id: int, message: dict[str, Any]):
        async with self._lock:
            connections = list(self._connections.get(user_id, set()))

        dead_connections = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.debug(f"Failed to send private event to user {user_id}: {e}")
                dead_connections.append(ws)

        if dead_connections:
            async with self._lock:
                if user_id in self._connections:
                    for dead in dead_connections:
                        self._connections[user_id].discard(dead)

    async def _listen_redis_channel(self, user_id: int):
        channel_name = f"user:{user_id}:events"
        try:
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(channel_name)
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await self.send_to_user_local(user_id, data)
                    except Exception as e:
                        logger.error(f"Error parsing redis message for user {user_id}: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Redis pubsub listener failed for user {user_id}: {e}")


user_ws_manager = UserConnectionManager()


async def publish_user_event(user_id: int, event_data: dict[str, Any]) -> None:
    """
    Publishes a private event to a specific user:
    1. First delivers to local connected WebSockets.
    2. Then publishes to Redis pub/sub channel for multi-instance scalability if Redis is configured.
    """
    try:
        await user_ws_manager.send_to_user_local(user_id, event_data)
        if redis_client is not None:
            channel_name = f"user:{user_id}:events"
            await redis_client.publish(channel_name, json.dumps(event_data, default=str))
    except Exception as e:
        logger.error(f"Failed to publish private event for user {user_id}: {e}")


async def publish_order_updated(buyer_id: int, seller_id: int, order_id: int, reason: Optional[str] = None) -> None:
    """
    Publishes an ORDER_UPDATED event to both buyer and seller.
    """
    event_data = {
        "type": "ORDER_UPDATED",
        "order_id": order_id,
        "reason": reason,
    }
    await publish_user_event(buyer_id, event_data)
    if seller_id != buyer_id:
        await publish_user_event(seller_id, event_data)


async def publish_order_created(seller_id: int, order_id: int) -> None:
    """
    Publishes an ORDER_CREATED event to seller.
    """
    event_data = {
        "type": "ORDER_CREATED",
        "order_id": order_id,
    }
    await publish_user_event(seller_id, event_data)


async def publish_auction_winner_checked_out(seller_id: int, auction_id: int, order_id: int) -> None:
    """
    Publishes an AUCTION_WINNER_CHECKED_OUT event to seller.
    """
    event_data = {
        "type": "AUCTION_WINNER_CHECKED_OUT",
        "auction_id": auction_id,
        "order_id": order_id,
    }
    await publish_user_event(seller_id, event_data)


ws_router = APIRouter(tags=["user-ws"])


@ws_router.websocket("/ws/me")
async def user_websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
):
    resolved_token = token
    # If token not in query param, await first message within 5s
    if not resolved_token:
        await websocket.accept()
        try:
            auth_msg_raw = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            auth_msg = json.loads(auth_msg_raw)
            if auth_msg.get("type") == "AUTH" and auth_msg.get("token"):
                resolved_token = auth_msg["token"]
            else:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
        except Exception:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    # Authenticate token against Firebase & DB
    try:
        async with SessionLocal() as db:
            user = await authenticate_user_token(resolved_token, db)
            user_id = user.user_id
    except Exception as e:
        logger.warning(f"Private user socket auth failed: {e}")
        try:
            if websocket.client_state.name == "CONNECTING":
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            else:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        except Exception:
            pass
        return

    # If was connected via query param, accept connection now
    if websocket.client_state.name == "CONNECTING":
        await user_ws_manager.connect(user_id, websocket)
    else:
        async with user_ws_manager._lock:
            if user_id not in user_ws_manager._connections:
                user_ws_manager._connections[user_id] = set()
                if redis_client is not None:
                    user_ws_manager._redis_tasks[user_id] = asyncio.create_task(
                        user_ws_manager._listen_redis_channel(user_id)
                    )
            user_ws_manager._connections[user_id].add(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await user_ws_manager.disconnect(user_id, websocket)
    except Exception:
        await user_ws_manager.disconnect(user_id, websocket)
