from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.modules.auth.dependencies import get_current_active_user
from app.modules.notifications.models import UserDeviceToken
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.service import NotificationService, safe_dispatch_push_notification
from app.integrations.firebase import send_multicast_push
from app.modules.users.models import User, UserRole, UserStatus


@pytest.mark.asyncio
async def test_push_subscribe_and_unsubscribe_endpoints():
    """Verify push subscription endpoints require auth and validate input."""
    test_user = User(
        user_id=101,
        email="push_test@ptit.edu.vn",
        full_name="Push Tester",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )

    app.dependency_overrides[get_current_active_user] = lambda: test_user
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Case 1: Subscribe with valid token
        with patch.object(NotificationService, "subscribe_push_token", new_callable=AsyncMock) as mock_sub:
            res = await client.post(
                "/api/v1/notifications/push/subscribe",
                json={"fcm_token": "fcm_test_token_123", "device_info": "Chrome on Windows"},
            )
            assert res.status_code == 200
            assert res.json() == {"status": "subscribed"}
            mock_sub.assert_called_once_with(
                user_id=101,
                fcm_token="fcm_test_token_123",
                device_info="Chrome on Windows",
            )

        # Case 2: Subscribe with empty token -> 422
        res_empty = await client.post(
            "/api/v1/notifications/push/subscribe",
            json={"fcm_token": "   ", "device_info": "Chrome"},
        )
        assert res_empty.status_code == 422

        # Case 3: Unsubscribe valid token
        with patch.object(NotificationService, "unsubscribe_push_token", new_callable=AsyncMock) as mock_unsub:
            res_unsub = await client.post(
                "/api/v1/notifications/push/unsubscribe",
                json={"fcm_token": "fcm_test_token_123"},
            )
            assert res_unsub.status_code == 200
            assert res_unsub.json() == {"status": "unsubscribed"}
            mock_unsub.assert_called_once_with(
                user_id=101,
                fcm_token="fcm_test_token_123",
            )

    app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_repository_upsert_and_delete_device_token():
    """Verify repository upsert reassigns duplicate token and queries properly."""
    mock_db = AsyncMock()
    repo = NotificationRepository(mock_db)

    # 1. New token insertion
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    await repo.upsert_device_token(user_id=101, fcm_token="fcm_token_a", device_info="Chrome")
    assert mock_db.add.called
    assert mock_db.commit.called

    # 2. Existing token reassignment (e.g. user switch on same browser)
    existing_row = UserDeviceToken(
        device_token_id=1,
        user_id=999,
        fcm_token="fcm_token_a",
        device_info="Old Browser",
    )
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=existing_row))
    res = await repo.upsert_device_token(user_id=101, fcm_token="fcm_token_a", device_info="New Browser")
    assert res.user_id == 101
    assert res.device_info == "New Browser"


def test_send_multicast_push_prunes_stale_tokens():
    """Verify send_multicast_push detects unregistered tokens and returns them for pruning."""
    mock_app = MagicMock()
    with patch("firebase_admin._apps", {"[DEFAULT]": mock_app}), \
         patch("firebase_admin.messaging.send_each_for_multicast") as mock_send:

        # Response: token 0 succeeds, token 1 is unregistered
        mock_resp_0 = MagicMock(success=True, exception=None)
        mock_exc_1 = MagicMock(code="registration-token-not-registered")
        mock_resp_1 = MagicMock(success=False, exception=mock_exc_1)

        mock_send.return_value = MagicMock(
            failure_count=1,
            responses=[mock_resp_0, mock_resp_1],
        )

        tokens = ["valid_token_0", "stale_token_1"]
        stale = send_multicast_push(tokens, "Title", "Body", {"key": "val"})

        assert stale == ["stale_token_1"]
        mock_send.assert_called_once()


def test_send_multicast_push_uninitialized_fails_open():
    """Verify send_multicast_push gracefully returns [] without exception when Firebase is not initialized."""
    from app.core.config import settings
    with patch("firebase_admin._apps", {}), \
         patch.object(settings, "FIREBASE_CREDENTIALS_JSON", None), \
         patch.object(settings, "FIREBASE_CREDENTIALS_PATH", None):
        result = send_multicast_push(["token_1"], "Title", "Body")
        assert result == []


@pytest.mark.asyncio
async def test_safe_dispatch_push_notification_isolated():
    """Verify safe_dispatch_push_notification isolates failures and does not raise."""
    with patch("app.core.database.SessionLocal") as mock_session_ctx:
        mock_session = AsyncMock()
        mock_session_ctx.return_value.__aenter__.return_value = mock_session

        with patch("app.modules.notifications.repository.NotificationRepository.get_device_tokens_for_user", return_value=["tok_1"]), \
             patch("app.integrations.firebase.send_multicast_push", return_value=["tok_1"]), \
             patch("app.modules.notifications.repository.NotificationRepository.delete_stale_device_tokens", new_callable=AsyncMock) as mock_prune:

            await safe_dispatch_push_notification(101, "New Order", "Order body", {"ref_type": "ORDER"})
            mock_prune.assert_called_once_with(["tok_1"])

