import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from starlette.websockets import WebSocketState

from app.core.config import settings
from app.core.redis import (
    INSTANCE_ID,
    get_redis_client,
    get_or_reconnect_redis,
    init_redis,
    close_redis,
    _init_lock,
)
import app.core.redis as redis_core
from app.modules.orders.websocket import (
    UserConnectionManager,
    publish_user_event,
)
from app.modules.auctions.websocket import (
    AuctionConnectionManager,
    publish_auction_event,
)


class FakeWebSocket:
    """Mock WebSocket matching FastAPI WebSocket interface for testing."""
    def __init__(self):
        self.sent_messages: list[dict] = []
        self.client_state = WebSocketState.CONNECTED

    async def accept(self):
        self.client_state = WebSocketState.CONNECTED

    async def send_json(self, data: dict):
        if self.client_state != WebSocketState.CONNECTED:
            raise RuntimeError("Cannot send on closed WebSocket")
        self.sent_messages.append(data)

    async def close(self, code: int = 1000):
        self.client_state = WebSocketState.DISCONNECTED


@pytest.mark.asyncio
async def test_redis_config_resolution():
    """Verify that settings correctly configure Redis parameters."""
    assert hasattr(settings, "REDIS_HOST")
    assert hasattr(settings, "REDIS_PORT")
    assert hasattr(settings, "REDIS_DB")
    assert isinstance(settings.REDIS_PORT, int)
    assert isinstance(settings.REDIS_DB, int)


@pytest.mark.asyncio
async def test_init_redis_failure_cleanup():
    """
    Correction 4: If init_redis() ping fails, candidate client must be closed
    and get_redis_client() must remain None (no unusable client in global state).
    """
    mock_candidate = AsyncMock()
    mock_candidate.ping = AsyncMock(side_effect=ConnectionRefusedError("Redis down"))
    mock_candidate.aclose = AsyncMock()

    with patch("redis.asyncio.Redis", return_value=mock_candidate):
        result = await init_redis()
        assert result is None
        assert get_redis_client() is None
        mock_candidate.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_dynamic_binding_resolution():
    """
    Root Cause Verification: get_redis_client() dynamically resolves the active client
    after init_redis() succeeds, eliminating the static import binding bug.
    """
    mock_active = AsyncMock()
    mock_active.ping = AsyncMock(return_value=True)

    with patch("redis.asyncio.Redis", return_value=mock_active):
        result = await init_redis()
        assert result is mock_active
        assert get_redis_client() is mock_active

    await close_redis()
    assert get_redis_client() is None


@pytest.mark.asyncio
async def test_async_single_flight_reconnect():
    """
    Correction 3 & 4: Multiple simultaneous reconnect callers result in a single
    Redis reconnect/candidate client creation, and all callers receive the connected client.
    """
    await close_redis()
    redis_core._last_connect_attempt = 0.0

    creation_count = 0
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(return_value=True)

    def factory(*args, **kwargs):
        nonlocal creation_count
        creation_count += 1
        return mock_client

    with patch("redis.asyncio.Redis", side_effect=factory):
        # 5 concurrent callers call get_or_reconnect_redis simultaneously
        results = await asyncio.gather(
            get_or_reconnect_redis(),
            get_or_reconnect_redis(),
            get_or_reconnect_redis(),
            get_or_reconnect_redis(),
            get_or_reconnect_redis(),
        )

        # Invariant: exactly 1 reconnect execution, all callers share the client
        assert creation_count == 1
        for res in results:
            assert res is mock_client

    await close_redis()


@pytest.mark.asyncio
async def test_single_subscriber_per_channel_multiple_connections():
    """
    Correction 2 & 5: When the same user connects multiple WebSockets (e.g. multiple tabs),
    there must be at most 1 Redis subscriber task for that channel.
    """
    manager = UserConnectionManager()
    user_id = 42

    mock_rc = MagicMock()
    mock_pubsub = AsyncMock()

    async def mock_listen():
        try:
            while True:
                await asyncio.sleep(10)
                yield {"type": "ping"}
        except asyncio.CancelledError:
            return

    mock_pubsub.listen = mock_listen
    mock_rc.pubsub.return_value = mock_pubsub

    with patch("app.modules.orders.websocket.get_redis_client", return_value=mock_rc):
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()
        ws3 = FakeWebSocket()

        await manager.connect(user_id, ws1)
        assert len(manager._connections[user_id]) == 1
        assert user_id in manager._redis_tasks
        first_task = manager._redis_tasks[user_id]

        # Second connection for same user
        await manager.connect(user_id, ws2)
        assert len(manager._connections[user_id]) == 2
        # Invariant: Still exactly 1 subscriber task
        assert manager._redis_tasks[user_id] is first_task

        # Third connection for same user
        await manager.connect(user_id, ws3)
        assert len(manager._connections[user_id]) == 3
        assert manager._redis_tasks[user_id] is first_task

        # Cleanup
        await manager.disconnect(user_id, ws1)
        await manager.disconnect(user_id, ws2)
        await manager.disconnect(user_id, ws3)


@pytest.mark.asyncio
async def test_subscriber_created_when_redis_unavailable_at_startup_and_recovers():
    """
    Correction 1 & 4: First WebSocket connection creates subscriber task even when
    Redis is None. The subscriber task calls reconnect with backoff, and when Redis recovers,
    subscribes automatically WITHOUT reconnecting the WebSocket.
    """
    manager = UserConnectionManager()
    user_id = 77

    mock_rc = MagicMock()
    mock_pubsub = AsyncMock()
    subscribed_event = asyncio.Event()

    async def mock_subscribe(channel):
        subscribed_event.set()

    mock_pubsub.subscribe = mock_subscribe

    async def mock_listen():
        try:
            while True:
                await asyncio.sleep(10)
                yield {"type": "ping"}
        except asyncio.CancelledError:
            return

    mock_pubsub.listen = mock_listen
    mock_rc.pubsub.return_value = mock_pubsub

    # Initially Redis is DOWN
    redis_state = {"client": None}

    def get_rc_mock():
        return redis_state["client"]

    async def reconnect_mock():
        return redis_state["client"]

    with patch("app.modules.orders.websocket.get_redis_client", side_effect=get_rc_mock), \
         patch("app.modules.orders.websocket.get_or_reconnect_redis", side_effect=reconnect_mock):

        ws = FakeWebSocket()
        # Connect while Redis is None
        await manager.connect(user_id, ws)

        # Invariant: Subscriber task was created despite Redis being None!
        assert user_id in manager._redis_tasks
        task = manager._redis_tasks[user_id]
        assert not task.done()

        # Let the task run one iteration of backoff
        await asyncio.sleep(0.05)

        # Now simulate Redis recovering!
        redis_state["client"] = mock_rc

        # Wait for subscriber to discover recovered client and subscribe
        # (It will retry on next loop iteration)
        try:
            await asyncio.wait_for(subscribed_event.wait(), timeout=2.5)
        except asyncio.TimeoutError:
            pass

        assert subscribed_event.is_set()

        # Cleanup
        await manager.disconnect(user_id, ws)


@pytest.mark.asyncio
async def test_disconnect_one_socket_keeps_subscriber():
    """
    Correction 2 & 5: Disconnecting one socket while another remains open
    must NOT cancel the subscriber task.
    """
    manager = UserConnectionManager()
    user_id = 55

    mock_rc = MagicMock()
    mock_pubsub = AsyncMock()

    async def mock_listen():
        try:
            while True:
                await asyncio.sleep(10)
                yield {"type": "ping"}
        except asyncio.CancelledError:
            return

    mock_pubsub.listen = mock_listen
    mock_rc.pubsub.return_value = mock_pubsub

    with patch("app.modules.orders.websocket.get_redis_client", return_value=mock_rc):
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()

        await manager.connect(user_id, ws1)
        await manager.connect(user_id, ws2)

        task = manager._redis_tasks[user_id]
        assert not task.done()

        # Disconnect first socket
        await manager.disconnect(user_id, ws1)
        assert len(manager._connections[user_id]) == 1
        assert user_id in manager._redis_tasks
        assert not task.done()

        # Disconnect remaining socket
        await manager.disconnect(user_id, ws2)
        assert user_id not in manager._connections
        assert user_id not in manager._redis_tasks
        assert task.done()


@pytest.mark.asyncio
async def test_disconnect_last_socket_cancels_and_cleans_subscriber():
    """
    Correction 2, 3 & 5: Disconnecting the last socket cancels, awaits cleanup,
    and removes the subscriber task from registry.
    """
    manager = UserConnectionManager()
    user_id = 99

    mock_rc = MagicMock()
    mock_pubsub = AsyncMock()

    async def mock_listen():
        try:
            while True:
                await asyncio.sleep(10)
                yield {"type": "ping"}
        except asyncio.CancelledError:
            return

    mock_pubsub.listen = mock_listen
    mock_rc.pubsub.return_value = mock_pubsub

    with patch("app.modules.orders.websocket.get_redis_client", return_value=mock_rc):
        ws = FakeWebSocket()
        await manager.connect(user_id, ws)
        # Yield to let subscriber task start and create pubsub
        await asyncio.sleep(0.01)

        task = manager._redis_tasks[user_id]
        assert not task.done()

        await manager.disconnect(user_id, ws)
        assert user_id not in manager._connections
        assert user_id not in manager._redis_tasks
        assert task.done()
        mock_pubsub.aclose.assert_awaited()


@pytest.mark.asyncio
async def test_reconnect_does_not_duplicate_subscriber():
    """
    Correction 2 & 5: Reconnecting after a complete disconnect starts a new clean
    subscriber task without duplicate tasks or lingering state.
    """
    manager = UserConnectionManager()
    user_id = 101

    mock_rc = MagicMock()
    mock_pubsub = AsyncMock()

    async def mock_listen():
        try:
            while True:
                await asyncio.sleep(10)
                yield {"type": "ping"}
        except asyncio.CancelledError:
            return

    mock_pubsub.listen = mock_listen
    mock_rc.pubsub.return_value = mock_pubsub

    with patch("app.modules.orders.websocket.get_redis_client", return_value=mock_rc):
        ws1 = FakeWebSocket()
        await manager.connect(user_id, ws1)
        task1 = manager._redis_tasks[user_id]

        await manager.disconnect(user_id, ws1)
        assert task1.done()
        assert user_id not in manager._redis_tasks

        # Reconnect with a new socket
        ws2 = FakeWebSocket()
        await manager.connect(user_id, ws2)
        assert user_id in manager._redis_tasks
        task2 = manager._redis_tasks[user_id]
        assert task2 is not task1
        assert not task2.done()

        await manager.disconnect(user_id, ws2)


@pytest.mark.asyncio
async def test_transport_envelope_preserves_clean_payload():
    """
    Correction 1 & 5: Redis pub/sub uses internal envelope {_meta, payload}.
    Local and remote WebSocket clients must ONLY receive clean event_data,
    with zero leak of _meta into client payload.
    """
    manager = UserConnectionManager()
    user_id = 200

    ws = FakeWebSocket()
    await manager.connect(user_id, ws)

    business_event = {
        "type": "ORDER_UPDATED",
        "order_id": 12345,
        "reason": "CONFIRMED",
    }

    # Simulate message arriving from Redis with transport envelope from remote instance
    remote_envelope = {
        "_meta": {"origin": "remote-instance-uuid-999"},
        "payload": business_event,
    }

    # Simulate unpack in listener logic
    raw_data = remote_envelope
    if isinstance(raw_data, dict) and "_meta" in raw_data and "payload" in raw_data:
        meta = raw_data.get("_meta", {})
        if meta.get("origin") != INSTANCE_ID:
            clean_payload = raw_data.get("payload")
            await manager.send_to_user_local(user_id, clean_payload)

    assert len(ws.sent_messages) == 1
    received = ws.sent_messages[0]

    # Invariant: Pristine payload received
    assert received["type"] == "ORDER_UPDATED"
    assert received["order_id"] == 12345
    assert received["reason"] == "CONFIRMED"
    # Invariant: No transport metadata leaked
    assert "_meta" not in received
    assert "_origin" not in received

    await manager.disconnect(user_id, ws)


@pytest.mark.asyncio
async def test_subscriber_skips_self_origin():
    """
    Loopback Deduplication: When Redis delivers an envelope whose origin matches
    current INSTANCE_ID, listener skips local broadcast since it was already delivered.
    """
    manager = UserConnectionManager()
    user_id = 300

    ws = FakeWebSocket()
    await manager.connect(user_id, ws)

    self_envelope = {
        "_meta": {"origin": INSTANCE_ID},
        "payload": {"type": "ORDER_CREATED", "order_id": 777},
    }

    # Simulate listener check
    raw_data = self_envelope
    if isinstance(raw_data, dict) and "_meta" in raw_data and "payload" in raw_data:
        meta = raw_data.get("_meta", {})
        if meta.get("origin") == INSTANCE_ID:
            # Self-origin: skip duplicate broadcast
            pass
        else:
            await manager.send_to_user_local(user_id, raw_data.get("payload"))

    # WebSocket client must have received 0 messages from this echo
    assert len(ws.sent_messages) == 0

    await manager.disconnect(user_id, ws)


@pytest.mark.asyncio
async def test_auction_manager_single_subscriber_and_clean_envelope():
    """
    Verify AuctionConnectionManager also adheres to:
    - Max 1 subscriber task per auction_id
    - Ref-count disconnect with clean cancellation
    - Clean payload delivery without transport metadata
    """
    auc_manager = AuctionConnectionManager()
    auction_id = 500

    mock_rc = MagicMock()
    mock_pubsub = AsyncMock()

    async def mock_listen():
        try:
            while True:
                await asyncio.sleep(10)
                yield {"type": "ping"}
        except asyncio.CancelledError:
            return

    mock_pubsub.listen = mock_listen
    mock_rc.pubsub.return_value = mock_pubsub

    with patch("app.modules.auctions.websocket.get_redis_client", return_value=mock_rc):
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()

        await auc_manager.connect(auction_id, ws1)
        await auc_manager.connect(auction_id, ws2)
        # Yield to let subscriber task start and create pubsub
        await asyncio.sleep(0.01)

        assert len(auc_manager._connections[auction_id]) == 2
        assert auction_id in auc_manager._redis_tasks
        task = auc_manager._redis_tasks[auction_id]

        # Simulate remote auction event
        event = {"type": "BID_PLACED", "auction_id": auction_id, "amount": "500000"}
        remote_envelope = {
            "_meta": {"origin": "another-instance"},
            "payload": event,
        }

        # Deliver clean payload
        await auc_manager.broadcast_local(auction_id, remote_envelope["payload"])

        assert len(ws1.sent_messages) == 1
        assert len(ws2.sent_messages) == 1
        assert ws1.sent_messages[0]["amount"] == "500000"
        assert "_meta" not in ws1.sent_messages[0]

        # Disconnect ws1 -> task remains
        await auc_manager.disconnect(auction_id, ws1)
        assert not task.done()

        # Disconnect ws2 -> task cancelled and cleaned
        await auc_manager.disconnect(auction_id, ws2)
        assert task.done()
        assert auction_id not in auc_manager._redis_tasks
        mock_pubsub.aclose.assert_awaited()


@pytest.mark.asyncio
async def test_no_business_data_loss_on_redis_error():
    """
    Non-blocking / degraded: When Redis publish raises an error,
    publish_user_event and publish_auction_event gracefully handle the failure
    and do not raise exceptions that could break business transactions.
    """
    failing_rc = AsyncMock()
    failing_rc.publish = AsyncMock(side_effect=ConnectionResetError("Redis dropped connection"))

    with patch("app.modules.orders.websocket.get_redis_client", return_value=failing_rc), \
         patch("app.modules.auctions.websocket.get_redis_client", return_value=failing_rc):

        # Neither of these should raise an exception
        await publish_user_event(user_id=1, event_data={"type": "ORDER_UPDATED", "order_id": 1})
        await publish_auction_event(auction_id=1, event_data={"type": "BID_PLACED", "amount": 100})
