import asyncio
import json
import logging
from typing import Any, Optional
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.database import SessionLocal
from app.core.realtime.presence import record_user_presence
from app.core.redis import get_redis_client, get_or_reconnect_redis, INSTANCE_ID
from app.modules.auth.dependencies import authenticate_user_token

logger = logging.getLogger("app.orders.ws")

# Module-level alias for backward compatibility with tests patching redis_client directly
redis_client: Any = None


class UserConnectionManager:
    def __init__(self):
        # Maps user_id -> set of active WebSocket connections (ref-counted)
        self._connections: dict[int, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        # Invariant: at most 1 Redis subscriber task per user_id
        self._redis_tasks: dict[int, asyncio.Task] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        if websocket.client_state.name == "CONNECTING":
            await websocket.accept()
        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = set()
            self._connections[user_id].add(websocket)
            
            # Invariant (Correction 1): First local connection for this user MUST create
            # exactly 1 subscriber task even if Redis is currently None.
            if user_id not in self._redis_tasks:
                self._redis_tasks[user_id] = asyncio.create_task(
                    self._listen_redis_channel(user_id)
                )
        await record_user_presence(user_id)
        logger.info(
            "Private user socket connected for user_id=%s. Active sockets: %s",
            user_id,
            len(self._connections.get(user_id, set())),
        )

    async def disconnect(self, user_id: int, websocket: WebSocket):
        task_to_cancel: asyncio.Task | None = None
        async with self._lock:
            if user_id in self._connections:
                self._connections[user_id].discard(websocket)
                # Invariant: cancel subscriber ONLY when the last socket of this user disconnects
                if not self._connections[user_id]:
                    del self._connections[user_id]
                    if user_id in self._redis_tasks:
                        task_to_cancel = self._redis_tasks.pop(user_id)

        if task_to_cancel is not None:
            task_to_cancel.cancel()
            try:
                await task_to_cancel
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug("Error awaiting cancelled user subscriber task: %s", e)

        logger.info("Private user socket disconnected for user_id=%s", user_id)

    async def revoke_user_connections(self, user_id: int, code: int = status.WS_1008_POLICY_VIOLATION):
        task_to_cancel: asyncio.Task | None = None
        async with self._lock:
            connections = list(self._connections.get(user_id, set()))
            if user_id in self._connections:
                del self._connections[user_id]
            if user_id in self._redis_tasks:
                task_to_cancel = self._redis_tasks.pop(user_id)

        if task_to_cancel is not None:
            task_to_cancel.cancel()
            try:
                await task_to_cancel
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug("Error awaiting cancelled user subscriber task on revoke: %s", e)

        for ws in connections:
            try:
                await ws.close(code=code)
            except Exception as e:
                logger.debug("Error closing revoked socket for user %s: %s", user_id, e)

        logger.info("Revoked all active sockets for banned/inactive user_id=%s", user_id)

    async def send_to_user_local(self, user_id: int, message: dict[str, Any]):
        async with self._lock:
            connections = list(self._connections.get(user_id, set()))

        dead_connections = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.debug("Failed to send private event to user %s: %s", user_id, e)
                dead_connections.append(ws)

        tasks_to_cancel: list[asyncio.Task] = []
        if dead_connections:
            async with self._lock:
                if user_id in self._connections:
                    for dead in dead_connections:
                        self._connections[user_id].discard(dead)
                    if not self._connections[user_id]:
                        del self._connections[user_id]
                        if user_id in self._redis_tasks:
                            tasks_to_cancel.append(self._redis_tasks.pop(user_id))

            for t in tasks_to_cancel:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

    async def _listen_redis_channel(self, user_id: int):
        channel_name = f"user:{user_id}:events"
        logger.info("Redis subscriber task started for %s", channel_name)
        backoff = 1.0
        max_backoff = 10.0
        pubsub = None

        try:
            while True:
                # If no local connections remain for this user, terminate subscriber
                async with self._lock:
                    if user_id not in self._connections or not self._connections[user_id]:
                        break

                # Close any previous or broken pubsub before retrying
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

                                if isinstance(clean_payload, dict) and clean_payload.get("type") == "_DISCONNECT":
                                    await self.revoke_user_connections(user_id)
                                    break

                                await self.send_to_user_local(user_id, clean_payload)
                            except Exception as parse_err:
                                logger.error("Error parsing redis message for user %s: %s", user_id, parse_err)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(
                        "Redis subscriber error for user %s (%s). Reconnecting in %ss...",
                        user_id,
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


user_ws_manager = UserConnectionManager()


async def publish_user_event(user_id: int, event_data: dict[str, Any]) -> None:
    """
    Publishes a private event to a specific user:
    1. First delivers pristine event_data to local connected WebSockets.
    2. Then packages into an internal transport envelope and publishes to Redis
       for multi-instance fan-out if Redis is configured.
    """
    # 1. Local delivery: local clients always receive the pristine event_data
    try:
        await user_ws_manager.send_to_user_local(user_id, event_data)
    except Exception as e:
        logger.error("Failed local delivery for user %s: %s", user_id, e)

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
            channel_name = f"user:{user_id}:events"
            await rc.publish(channel_name, json.dumps(envelope, default=str))
    except Exception as e:
        logger.warning(
            "Redis publish failed for user %s (%s); local broadcast already delivered.",
            user_id,
            e,
        )


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


async def revoke_user_sessions(user_id: int) -> None:
    """
    Revokes any active WebSocket connections for a user across all instances.
    Best-effort delivery; MUST be called ONLY AFTER the DB transaction commits.
    """
    # 1. Revoke local connections
    try:
        await user_ws_manager.revoke_user_connections(user_id)
    except Exception as e:
        logger.error("Failed local socket revocation for user %s: %s", user_id, e)

    # 2. Fan-out disconnect control signal to other instances via Redis pub/sub
    try:
        rc = redis_client or get_redis_client()
        if rc is None:
            rc = await get_or_reconnect_redis()
        if rc is not None:
            envelope = {
                "_meta": {
                    "origin": INSTANCE_ID,
                },
                "payload": {"type": "_DISCONNECT"},
            }
            channel_name = f"user:{user_id}:events"
            await rc.publish(channel_name, json.dumps(envelope, default=str))
    except Exception as e:
        logger.warning("Redis disconnect publish failed for user %s: %s", user_id, e)


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

    await user_ws_manager.connect(user_id, websocket)

    try:
        while True:
            data = await websocket.receive_text()
            if data in ("ping", "heartbeat"):
                await record_user_presence(user_id)
                await websocket.send_text("pong")
            else:
                try:
                    payload = json.loads(data)
                    if payload.get("type") in ("PING", "HEARTBEAT"):
                        await record_user_presence(user_id)
                        await websocket.send_text(json.dumps({"type": "PONG"}))
                except Exception:
                    pass
    except WebSocketDisconnect:
        await user_ws_manager.disconnect(user_id, websocket)
    except Exception:
        await user_ws_manager.disconnect(user_id, websocket)

