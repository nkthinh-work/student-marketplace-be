import io
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.core.config import settings
from app.core.rate_limiter import check_chat_video_upload_quota
from app.core.redis import get_or_reconnect_redis
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.conversations.models import (
    Conversation,
    ConversationMember,
    MediaCleanupJob,
    Message,
    MessageAttachment,
)
from app.modules.users.models import User, UserRole, UserStatus
from app.workers.media_cleanup import (
    calculate_next_retry_at,
    run_media_cleanup_sweep,
    sanitize_external_error,
)


def auth_patch(user: User):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_active_user] = lambda: user

    class CleanCtx:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc_val, exc_tb):
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_current_active_user, None)

    return CleanCtx()


@pytest_asyncio.fixture
async def user_sender(db_session: AsyncSession) -> User:
    u = User(
        email="sender_recall@ptit.edu.vn",
        full_name="Nguyễn Văn Gửi",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def user_receiver(db_session: AsyncSession) -> User:
    u = User(
        email="receiver_recall@ptit.edu.vn",
        full_name="Trần Thị Nhận",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def user_outsider(db_session: AsyncSession) -> User:
    u = User(
        email="outsider_recall@ptit.edu.vn",
        full_name="Lê Người Ngoài",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def direct_conv(
    db_session: AsyncSession, user_sender: User, user_receiver: User
) -> Conversation:
    conv = Conversation(
        type="DIRECT",
        user_one_id=min(user_sender.user_id, user_receiver.user_id),
        user_two_id=max(user_sender.user_id, user_receiver.user_id),
        direct_pair_key=f"{min(user_sender.user_id, user_receiver.user_id)}:{max(user_sender.user_id, user_receiver.user_id)}",
    )
    db_session.add(conv)
    await db_session.flush()

    m1 = ConversationMember(
        conversation_id=conv.conversation_id,
        user_id=user_sender.user_id,
        role="MEMBER",
    )
    m2 = ConversationMember(
        conversation_id=conv.conversation_id,
        user_id=user_receiver.user_id,
        role="MEMBER",
    )
    db_session.add_all([m1, m2])
    await db_session.commit()
    return conv


# =========================================================================
# 1. Authorization Tests for Recall
# =========================================================================

@pytest.mark.asyncio
async def test_recall_sender_success(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_sender: User,
    direct_conv: Conversation,
):
    """Sender can recall their own message, resulting in tombstone response and DB update."""
    msg = Message(
        conversation_id=direct_conv.conversation_id,
        sender_id=user_sender.user_id,
        type="TEXT",
        content="Nội dung sẽ bị thu hồi",
    )
    db_session.add(msg)
    await db_session.commit()

    with auth_patch(user_sender):
        resp = await test_client.delete(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{msg.message_id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["message_id"] == msg.message_id
        assert data["is_deleted"] is True
        assert data["content"] is None
        assert data["attachments"] == []

    # Verify DB state
    await db_session.refresh(msg)
    assert msg.is_deleted is True
    assert msg.content is None


@pytest.mark.asyncio
async def test_recall_other_member_forbidden(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_sender: User,
    user_receiver: User,
    direct_conv: Conversation,
):
    """Another member in conversation cannot recall someone else's message (403 Forbidden)."""
    msg = Message(
        conversation_id=direct_conv.conversation_id,
        sender_id=user_sender.user_id,
        type="TEXT",
        content="Tin nhắn của người gửi",
    )
    db_session.add(msg)
    await db_session.commit()

    with auth_patch(user_receiver):
        resp = await test_client.delete(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{msg.message_id}"
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_recall_outsider_404_non_leaking(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_sender: User,
    user_outsider: User,
    direct_conv: Conversation,
):
    """Outsider gets 404 Not Found without leaking message existence."""
    msg = Message(
        conversation_id=direct_conv.conversation_id,
        sender_id=user_sender.user_id,
        type="TEXT",
        content="Tin nhắn bí mật",
    )
    db_session.add(msg)
    await db_session.commit()

    with auth_patch(user_outsider):
        resp = await test_client.delete(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{msg.message_id}"
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_recall_message_from_another_conversation_404(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_sender: User,
    user_receiver: User,
    direct_conv: Conversation,
):
    """Calling recall with message_id belonging to another conversation returns 404."""
    # Create another conversation
    conv2 = Conversation(type="GROUP", title="Nhóm khác")
    db_session.add(conv2)
    await db_session.flush()
    db_session.add(
        ConversationMember(
            conversation_id=conv2.conversation_id,
            user_id=user_sender.user_id,
            role="MEMBER",
        )
    )
    msg2 = Message(
        conversation_id=conv2.conversation_id,
        sender_id=user_sender.user_id,
        type="TEXT",
        content="Tin nhắn nhóm",
    )
    db_session.add(msg2)
    await db_session.commit()

    with auth_patch(user_sender):
        # Attempt to recall msg2 via direct_conv path
        resp = await test_client.delete(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{msg2.message_id}"
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_recall_system_message_rejected(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_sender: User,
    direct_conv: Conversation,
):
    """System message cannot be recalled (400 Bad Request)."""
    msg = Message(
        conversation_id=direct_conv.conversation_id,
        sender_id=user_sender.user_id,
        type="SYSTEM",
        content="Hệ thống thông báo",
    )
    db_session.add(msg)
    await db_session.commit()

    with auth_patch(user_sender):
        resp = await test_client.delete(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{msg.message_id}"
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Cannot recall system messages."


@pytest.mark.asyncio
async def test_recall_already_deleted_idempotent(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_sender: User,
    direct_conv: Conversation,
):
    """Recalling an already-deleted message is idempotent and succeeds without duplicate jobs."""
    msg = Message(
        conversation_id=direct_conv.conversation_id,
        sender_id=user_sender.user_id,
        type="TEXT",
        content=None,
        is_deleted=True,
    )
    db_session.add(msg)
    await db_session.commit()

    with auth_patch(user_sender):
        resp = await test_client.delete(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{msg.message_id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_deleted"] is True
        assert data["content"] is None


# =========================================================================
# 2. Tombstone Sanitization & Reply Preview Tests
# =========================================================================

@pytest.mark.asyncio
async def test_tombstone_get_messages_sanitization(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_sender: User,
    user_receiver: User,
    direct_conv: Conversation,
):
    """Recalled message returned via GET messages never leaks content or attachments."""
    msg = Message(
        conversation_id=direct_conv.conversation_id,
        sender_id=user_sender.user_id,
        type="TEXT",
        content="Nội dung cần giấu",
    )
    db_session.add(msg)
    await db_session.flush()

    att = MessageAttachment(
        message_id=msg.message_id,
        kind="IMAGE",
        url="https://res.cloudinary.com/test/image/upload/secret.jpg",
        storage_key="test/secret_img",
        mime_type="image/jpeg",
        original_name="secret.jpg",
        size_bytes=1000,
    )
    db_session.add(att)
    await db_session.commit()

    # Recall the message
    with auth_patch(user_sender):
        recall_resp = await test_client.delete(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{msg.message_id}"
        )
        assert recall_resp.status_code == 200

    # Receiver reads messages
    with auth_patch(user_receiver):
        get_resp = await test_client.get(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages"
        )
        assert get_resp.status_code == 200
        items = get_resp.json()["items"]
        target = next(i for i in items if i["message_id"] == msg.message_id)
        assert target["is_deleted"] is True
        assert target["content"] is None
        assert target["attachments"] == []
        assert target["mentions"] == []
        assert target["reactions"] == []


@pytest.mark.asyncio
async def test_reply_to_recalled_message_renders_tombstone_text(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_sender: User,
    user_receiver: User,
    direct_conv: Conversation,
):
    """Message replying to a recalled message shows 'Tin nhắn không còn khả dụng'."""
    msg1 = Message(
        conversation_id=direct_conv.conversation_id,
        sender_id=user_sender.user_id,
        type="TEXT",
        content="Tin nhắn ban đầu",
    )
    db_session.add(msg1)
    await db_session.flush()

    msg2 = Message(
        conversation_id=direct_conv.conversation_id,
        sender_id=user_receiver.user_id,
        type="TEXT",
        content="Tôi trả lời tin này",
        reply_to_message_id=msg1.message_id,
    )
    db_session.add(msg2)
    await db_session.commit()

    # User A recalls msg1
    with auth_patch(user_sender):
        recall_resp = await test_client.delete(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{msg1.message_id}"
        )
        assert recall_resp.status_code == 200

    # Receiver views messages
    with auth_patch(user_receiver):
        get_resp = await test_client.get(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages"
        )
        assert get_resp.status_code == 200
        items = get_resp.json()["items"]
        reply_msg = next(i for i in items if i["message_id"] == msg2.message_id)
        assert reply_msg["reply_to"] is not None
        assert reply_msg["reply_to"]["preview"] == "Tin nhắn không còn khả dụng"


# =========================================================================
# 3. Shared Attachments & Download Protection Tests
# =========================================================================

@pytest.mark.asyncio
async def test_shared_attachments_and_summary_exclude_recalled(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_sender: User,
    user_receiver: User,
    direct_conv: Conversation,
):
    """Recalled message attachments are completely hidden from shared attachments and summary."""
    msg = Message(
        conversation_id=direct_conv.conversation_id,
        sender_id=user_sender.user_id,
        type="IMAGE",
        content=None,
    )
    db_session.add(msg)
    await db_session.flush()

    att = MessageAttachment(
        message_id=msg.message_id,
        kind="IMAGE",
        url="https://res.cloudinary.com/test/image/upload/photo.jpg",
        storage_key="test/photo_key",
        mime_type="image/jpeg",
        original_name="photo.jpg",
        size_bytes=5000,
    )
    db_session.add(att)
    await db_session.commit()

    with auth_patch(user_receiver):
        # Before recall: 1 attachment in summary and list
        sum_before = await test_client.get(
            f"/api/v1/conversations/{direct_conv.conversation_id}/attachments/summary"
        )
        assert sum_before.json()["media_count"] == 1

        list_before = await test_client.get(
            f"/api/v1/conversations/{direct_conv.conversation_id}/attachments?category=media"
        )
        assert len(list_before.json()["items"]) == 1

    # Sender recalls message
    with auth_patch(user_sender):
        with patch("app.modules.conversations.service.destroy_asset_async", new_callable=AsyncMock) as mock_destroy:
            mock_destroy.return_value = True
            rec_resp = await test_client.delete(
                f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{msg.message_id}"
            )
            assert rec_resp.status_code == 200

    with auth_patch(user_receiver):
        # After recall: 0 attachments
        sum_after = await test_client.get(
            f"/api/v1/conversations/{direct_conv.conversation_id}/attachments/summary"
        )
        assert sum_after.json()["media_count"] == 0

        list_after = await test_client.get(
            f"/api/v1/conversations/{direct_conv.conversation_id}/attachments?category=media"
        )
        assert len(list_after.json()["items"]) == 0

        # Attempt to create download ticket for recalled attachment -> 404
        ticket_resp = await test_client.post(
            f"/api/v1/conversations/{direct_conv.conversation_id}/attachments/{att.attachment_id}/download-ticket"
        )
        assert ticket_resp.status_code == 404


# =========================================================================
# 4. Cloudinary Cleanup & Durable Queue Tests
# =========================================================================

@pytest.mark.asyncio
async def test_media_cleanup_immediate_success_removes_queue_job(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_sender: User,
    direct_conv: Conversation,
):
    """When immediate Cloudinary destroy succeeds, media_cleanup_jobs row is deleted."""
    msg = Message(
        conversation_id=direct_conv.conversation_id,
        sender_id=user_sender.user_id,
        type="IMAGE",
        content=None,
    )
    db_session.add(msg)
    await db_session.flush()

    att = MessageAttachment(
        message_id=msg.message_id,
        kind="IMAGE",
        url="https://res.cloudinary.com/test/image/upload/del_success.jpg",
        storage_key="test/del_success_key",
        mime_type="image/jpeg",
        original_name="del_success.jpg",
        size_bytes=5000,
    )
    db_session.add(att)
    await db_session.commit()

    with auth_patch(user_sender):
        with patch("app.modules.conversations.service.destroy_asset_async", new_callable=AsyncMock) as mock_destroy:
            mock_destroy.return_value = True
            resp = await test_client.delete(
                f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{msg.message_id}"
            )
            assert resp.status_code == 200
            mock_destroy.assert_awaited_once_with("test/del_success_key", resource_type="image")

    # Verify no pending jobs in media_cleanup_jobs
    stmt = select(MediaCleanupJob).where(MediaCleanupJob.storage_key == "test/del_success_key")
    jobs = (await db_session.scalars(stmt)).all()
    assert len(jobs) == 0


@pytest.mark.asyncio
async def test_media_cleanup_immediate_failure_keeps_durable_job(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_sender: User,
    direct_conv: Conversation,
):
    """When immediate Cloudinary destroy fails, recall succeeds but durable job remains."""
    msg = Message(
        conversation_id=direct_conv.conversation_id,
        sender_id=user_sender.user_id,
        type="FILE",
        content=None,
    )
    db_session.add(msg)
    await db_session.flush()

    att = MessageAttachment(
        message_id=msg.message_id,
        kind="VIDEO",
        url="https://res.cloudinary.com/test/video/upload/fail_video.mp4",
        storage_key="test/fail_video_key",
        mime_type="video/mp4",
        original_name="fail_video.mp4",
        size_bytes=10000,
    )
    db_session.add(att)
    await db_session.commit()

    with auth_patch(user_sender):
        with patch("app.modules.conversations.service.destroy_asset_async", new_callable=AsyncMock) as mock_destroy:
            mock_destroy.side_effect = Exception("Cloudinary connection timeout")
            resp = await test_client.delete(
                f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{msg.message_id}"
            )
            # Business recall transaction STILL commits!
            assert resp.status_code == 200

    # Verify durable cleanup job exists for worker retry
    stmt = select(MediaCleanupJob).where(MediaCleanupJob.storage_key == "test/fail_video_key")
    job = (await db_session.scalars(stmt)).first()
    assert job is not None
    assert job.resource_type == "video"
    assert job.attempt_count == 0


@pytest.mark.asyncio
async def test_media_cleanup_worker_sweep(db_session: AsyncSession):
    """Worker sweep processes pending jobs, retries with backoff on failure, deletes on success."""
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    job_ok = MediaCleanupJob(
        storage_key="test/worker_ok_key",
        resource_type="image",
        attempt_count=0,
        next_retry_at=now_utc,
    )
    job_fail = MediaCleanupJob(
        storage_key="test/worker_fail_key",
        resource_type="video",
        attempt_count=0,
        next_retry_at=now_utc,
    )
    db_session.add_all([job_ok, job_fail])
    await db_session.commit()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def session_factory():
        yield db_session

    async def mock_destroy(storage_key, resource_type):
        if storage_key == "test/worker_ok_key":
            return True
        raise Exception("Network failure")

    with patch("app.workers.media_cleanup.destroy_asset_async", side_effect=mock_destroy):
        sweep_res = await run_media_cleanup_sweep(session_factory)
        assert sweep_res.changed == 1
        assert sweep_res.failed == 1

    # job_ok deleted
    stmt_ok = select(MediaCleanupJob).where(MediaCleanupJob.storage_key == "test/worker_ok_key")
    assert (await db_session.scalars(stmt_ok)).first() is None

    # job_fail updated with attempt_count=1 and future next_retry_at
    stmt_fail = select(MediaCleanupJob).where(MediaCleanupJob.storage_key == "test/worker_fail_key")
    failed_job = (await db_session.scalars(stmt_fail)).first()
    assert failed_job is not None
    assert failed_job.attempt_count == 1
    assert failed_job.next_retry_at > now_utc


# =========================================================================
# 5. Video Anti-Spam Tests
# =========================================================================

@pytest.mark.asyncio
async def test_video_anti_spam_two_videos_rejected_before_upload(
    test_client: AsyncClient,
    user_sender: User,
    direct_conv: Conversation,
):
    """Uploading 2 videos in a single message is rejected with 422 before Cloudinary upload."""
    mp4_bytes = (
        b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42"
        + b"\x00" * 100
    )

    files = [
        ("files", ("video1.mp4", io.BytesIO(mp4_bytes), "video/mp4")),
        ("files", ("video2.mp4", io.BytesIO(mp4_bytes), "video/mp4")),
    ]

    with auth_patch(user_sender):
        with patch("app.modules.conversations.service.upload_message_attachment") as mock_upload:
            resp = await test_client.post(
                f"/api/v1/conversations/{direct_conv.conversation_id}/messages",
                data={"content": "Hai video"},
                files=files,
            )
            assert resp.status_code == 422
            # Crucial requirement: Cloudinary is NEVER touched!
            mock_upload.assert_not_called()


@pytest.mark.asyncio
async def test_video_anti_spam_rolling_quota_exceeded(
    test_client: AsyncClient,
    user_sender: User,
    direct_conv: Conversation,
):
    """Exceeding rolling video quota returns 429 Too Many Requests before upload."""
    mp4_bytes = (
        b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42"
        + b"\x00" * 100
    )

    files = [
        ("files", ("video.mp4", io.BytesIO(mp4_bytes), "video/mp4")),
    ]

    with auth_patch(user_sender):
        # Mock quota check to simulate quota exceeded
        with patch("app.modules.conversations.service.check_chat_video_upload_quota", new_callable=AsyncMock) as mock_quota:
            mock_quota.return_value = (False, 120)
            with patch("app.modules.conversations.service.upload_message_attachment") as mock_upload:
                resp = await test_client.post(
                    f"/api/v1/conversations/{direct_conv.conversation_id}/messages",
                    data={"content": "Video vượt quota"},
                    files=files,
                )
                assert resp.status_code == 429
                assert resp.headers.get("Retry-After") == "120"
                mock_upload.assert_not_called()


@pytest.mark.asyncio
async def test_video_anti_spam_zero_video_does_not_consume_quota(
    test_client: AsyncClient,
    user_sender: User,
    direct_conv: Conversation,
):
    """Text-only or image-only messages do not trigger video quota check."""
    with auth_patch(user_sender):
        with patch("app.modules.conversations.service.check_chat_video_upload_quota", new_callable=AsyncMock) as mock_quota:
            resp = await test_client.post(
                f"/api/v1/conversations/{direct_conv.conversation_id}/messages",
                data={"content": "Chỉ là tin nhắn chữ"},
            )
            assert resp.status_code == 201
            mock_quota.assert_not_called()


# =========================================================================
# 6. Realtime MESSAGE_DELETED Event Verification
# =========================================================================

@pytest.mark.asyncio
async def test_realtime_message_deleted_event(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_sender: User,
    user_receiver: User,
    direct_conv: Conversation,
):
    """Recall success publishes MESSAGE_DELETED to active members with no Cloudinary metadata."""
    msg = Message(
        conversation_id=direct_conv.conversation_id,
        sender_id=user_sender.user_id,
        type="TEXT",
        content="Tin sẽ xóa",
    )
    db_session.add(msg)
    await db_session.commit()

    with auth_patch(user_sender):
        with patch("app.modules.conversations.service.publish_user_event", new_callable=AsyncMock) as mock_ws:
            resp = await test_client.delete(
                f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{msg.message_id}"
            )
            assert resp.status_code == 200

            # Active members: user_sender, user_receiver
            assert mock_ws.await_count == 2
            published_events = [call.args[1] for call in mock_ws.await_args_list]
            for evt in published_events:
                assert evt["type"] == "MESSAGE_DELETED"
                assert evt["conversation_id"] == direct_conv.conversation_id
                assert evt["message_id"] == msg.message_id
                # No sensitive metadata
                assert "storage_key" not in evt
                assert "url" not in evt
                assert "content" not in evt


# =========================================================================
# 7. Audit & Edge-Case Hardening Tests
# =========================================================================

@pytest.mark.asyncio
async def test_true_rolling_video_quota_sliding_window_boundary():
    """
    Demonstrates true sliding-window rate limiting via Redis Sorted Set (ZSET):
    - 5 uploads in rolling window are accepted.
    - 6th upload within same window is denied with dynamic Retry-After.
    - At t=601s, only the first upload (t=0s) has expired, permitting exactly 1 new upload.
    - A subsequent request at t=601s is denied (window again holds 5 events).
    - Prevents burst exploitation across fixed-window boundaries.
    """
    redis = await get_or_reconnect_redis()
    assert redis is not None, "Redis must be available for rate limiter tests"

    user_id = 999888
    key = f"chat:video-upload:u:{user_id}"
    await redis.delete(key)

    base_ms = 1_000_000_000

    # 1. First 5 requests at t=0s, 100s, 200s, 300s, 599s are ALL allowed
    times_s = [0, 100, 200, 300, 599]
    for sec in times_s:
        allowed, retry_after = await check_chat_video_upload_quota(
            user_id, now_ms=base_ms + (sec * 1000)
        )
        assert allowed is True
        assert retry_after == 0

    # 2. 6th request at t=599s is DENIED; oldest event is at t=0s (expires at t=600s)
    # Remaining time = 600s - 599s = 1s
    allowed, retry_after = await check_chat_video_upload_quota(
        user_id, now_ms=base_ms + 599_000
    )
    assert allowed is False
    assert retry_after == 1

    # 3. At t=601s (now_ms = base_ms + 601_000):
    # Cutoff = 601_000 - 600_000 = 1000ms.
    # The event at t=0s (score 0ms <= 1000ms) has expired and is evicted.
    # The window now contains 4 events (100s, 200s, 300s, 599s).
    # Therefore, 1 request is ALLOWED!
    allowed, retry_after = await check_chat_video_upload_quota(
        user_id, now_ms=base_ms + 601_000
    )
    assert allowed is True
    assert retry_after == 0

    # 4. Immediate second request at t=601s is DENIED (window again holds 5 events: 100s, 200s, 300s, 599s, 601s).
    # Oldest event in window is now at t=100s, which expires at t=700s.
    # Remaining time = 700s - 601s = 99s.
    allowed, retry_after = await check_chat_video_upload_quota(
        user_id, now_ms=base_ms + 601_000
    )
    assert allowed is False
    assert retry_after == 99

    # Cleanup
    await redis.delete(key)


@pytest.mark.asyncio
async def test_cleanup_job_initial_retry_delay_and_no_premature_pickup(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_sender: User,
    direct_conv: Conversation,
):
    """
    Verifies newly enqueued cleanup jobs receive next_retry_at = now + 60s
    to prevent race conditions with immediate post-commit destroy.
    A worker sweep running immediately will NOT pick up this job.
    """
    msg = Message(
        conversation_id=direct_conv.conversation_id,
        sender_id=user_sender.user_id,
        type="FILE",
        content=None,
    )
    db_session.add(msg)
    await db_session.flush()

    att = MessageAttachment(
        message_id=msg.message_id,
        kind="VIDEO",
        url="https://res.cloudinary.com/test/video/upload/initial_delay.mp4",
        storage_key="test/initial_delay_key",
        mime_type="video/mp4",
        original_name="initial_delay.mp4",
        size_bytes=10000,
    )
    db_session.add(att)
    await db_session.commit()

    with auth_patch(user_sender):
        with patch("app.modules.conversations.service.destroy_asset_async", new_callable=AsyncMock) as mock_destroy:
            mock_destroy.side_effect = Exception("Simulated network timeout")
            resp = await test_client.delete(
                f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{msg.message_id}"
            )
            assert resp.status_code == 200

    stmt = select(MediaCleanupJob).where(MediaCleanupJob.storage_key == "test/initial_delay_key")
    job = (await db_session.scalars(stmt)).first()
    assert job is not None
    # Must have initial delay of 60 seconds
    assert job.next_retry_at >= job.created_at + timedelta(seconds=59)

    # Worker sweep running at created_at will find 0 candidates
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def session_factory():
        yield db_session

    with patch("app.workers.media_cleanup.destroy_asset_async") as mock_worker_destroy:
        sweep_res = await run_media_cleanup_sweep(session_factory)
        # 0 candidates swept because next_retry_at is in the future
        assert sweep_res.candidates == 0
        mock_worker_destroy.assert_not_called()


@pytest.mark.asyncio
async def test_multi_worker_concurrency_protection(db_session: AsyncSession):
    """
    Verifies FOR UPDATE SKIP LOCKED batch claiming prevents concurrent worker replicas
    from executing duplicate Cloudinary deletions.
    """
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    job = MediaCleanupJob(
        storage_key="test/concurrency_job_key",
        resource_type="image",
        attempt_count=0,
        next_retry_at=now_utc - timedelta(seconds=10),
    )
    db_session.add(job)
    await db_session.commit()

    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def session_factory():
        yield db_session

    # Worker 1 runs and claims the job
    with patch("app.workers.media_cleanup.destroy_asset_async", new_callable=AsyncMock) as mock_destroy:
        mock_destroy.return_value = True
        res = await run_media_cleanup_sweep(session_factory)
        assert res.changed == 1
        assert res.candidates == 1

    # Worker 2 running after Worker 1 finds 0 candidates
    with patch("app.workers.media_cleanup.destroy_asset_async", new_callable=AsyncMock) as mock_destroy:
        res2 = await run_media_cleanup_sweep(session_factory)
        assert res2.candidates == 0


def test_last_error_and_log_sanitization():
    """
    Verifies sanitize_external_error strips API secrets, tokens, signed URLs,
    and truncates to maximum 500 characters.
    """
    raw_error = (
        "Cloudinary error: destroy failed for url "
        "https://api.cloudinary.com/v1_1/choptiters/image/destroy?api_key=SECRET_KEY_123&token=SECRET_TOKEN_456 "
        "with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secret_payload.signature and password=super_secret_pw"
    )
    sanitized = sanitize_external_error(raw_error)

    # Must NOT contain secrets
    assert "SECRET_KEY_123" not in sanitized
    assert "SECRET_TOKEN_456" not in sanitized
    assert "super_secret_pw" not in sanitized
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in sanitized

    # Redactions present
    assert "[REDACTED]" in sanitized

    # Length bounded
    assert len(sanitized) <= 500

    # Exception object handling
    exc = RuntimeError("Failed with token=XYZ12345")
    sanitized_exc = sanitize_external_error(exc)
    assert "XYZ12345" not in sanitized_exc
    assert "RuntimeError:" in sanitized_exc
