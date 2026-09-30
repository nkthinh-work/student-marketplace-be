from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.core.database import get_db
from app.modules.auctions.models import AuctionStatus
from app.modules.auctions.websocket import manager, publish_auction_event


class MockAuctionDb:
    """Mock database session that inspects Auction query and returns mapped status."""

    def __init__(self, auction_map: dict[int, str]):
        self.auction_map = auction_map

    async def execute(self, stmt):
        mock_res = MagicMock()
        target_id = None
        for criterion in getattr(stmt, "_where_criteria", []):
            if hasattr(criterion, "right") and hasattr(criterion.right, "value"):
                target_id = criterion.right.value
        mock_res.scalar_one_or_none.return_value = self.auction_map.get(target_id)
        return mock_res


@pytest.fixture
def mock_auction_db():
    status_map = {
        101: AuctionStatus.ACTIVE.value,
        102: AuctionStatus.SCHEDULED.value,
        201: AuctionStatus.ENDED.value,
        202: AuctionStatus.CANCELLED.value,
    }
    mock_db = MockAuctionDb(status_map)
    app.dependency_overrides[get_db] = lambda: mock_db
    yield mock_db
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client():
    return TestClient(app)


def test_valid_active_auction_connects_successfully(mock_auction_db, client):
    """A. Valid active auction connects cleanly, registers in manager, and handles ping/pong."""
    active_auc_id = 101

    with client.websocket_connect(f"/ws/auctions/{active_auc_id}") as ws:
        assert active_auc_id in manager._connections
        assert len(manager._connections[active_auc_id]) >= 1

        ws.send_text("ping")
        assert ws.receive_text() == "pong"

    # On exit/disconnect, socket is removed from manager
    assert active_auc_id not in manager._connections


def test_valid_scheduled_auction_connects_successfully(mock_auction_db, client):
    """A. Valid scheduled auction connects cleanly and is registered in manager."""
    scheduled_auc_id = 102

    with client.websocket_connect(f"/ws/auctions/{scheduled_auc_id}") as ws:
        assert scheduled_auc_id in manager._connections
        ws.send_text("ping")
        assert ws.receive_text() == "pong"

    assert scheduled_auc_id not in manager._connections


def test_non_existent_auction_is_rejected_cleanly_and_not_stored(mock_auction_db, client):
    """B. Non-existent auction is rejected with close code 1008 and never stored in manager."""
    non_existent_id = 999999

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/auctions/{non_existent_id}"):
            pass

    assert exc_info.value.code == 1008
    assert non_existent_id not in manager._connections
    assert non_existent_id not in manager._redis_tasks


def test_invalid_syntactic_auction_id_is_rejected_safely(mock_auction_db, client):
    """A & B. Syntactically invalid auction_id values (<= 0 or non-int) are rejected before DB/manager."""
    for invalid_id in [0, -1, -500]:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/ws/auctions/{invalid_id}"):
                pass

        assert exc_info.value.code == 1008
        assert invalid_id not in manager._connections
        assert invalid_id not in manager._redis_tasks

    # String parameter rejected by FastAPI
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/auctions/invalid_string_id"):
            pass
    assert exc_info.value.code == 1008


def test_inactive_auction_states_are_rejected_cleanly(mock_auction_db, client):
    """B. Auctions with status CANCELLED or ENDED are rejected as ineligible for realtime subscription."""
    for inactive_id in [201, 202]:  # 201: ENDED, 202: CANCELLED
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/ws/auctions/{inactive_id}"):
                pass

        assert exc_info.value.code == 1008
        assert inactive_id not in manager._connections
        assert inactive_id not in manager._redis_tasks


def test_valid_auction_realtime_broadcast_flow(mock_auction_db, client):
    """C. Valid auction realtime event broadcast works end-to-end through connection manager."""
    active_auc_id = 101

    with client.websocket_connect(f"/ws/auctions/{active_auc_id}") as ws:
        event_payload = {
            "event": "BID_PLACED",
            "auction_id": active_auc_id,
            "current_price": "250000",
            "bid_count": 2,
            "server_time": datetime.now(timezone.utc).isoformat(),
        }
        # Publish event locally to this auction's subscribers via AnyIO portal
        ws.portal.call(publish_auction_event, active_auc_id, event_payload)

        received = ws.receive_json()
        assert received["event"] == "BID_PLACED"
        assert received["auction_id"] == active_auc_id
        assert received["current_price"] == "250000"
        assert received["bid_count"] == 2
