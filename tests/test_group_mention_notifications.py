import json
from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.conversations.models import (
    Conversation,
    ConversationMember,
    Message,
    MessageMention,
)
from app.modules.notifications.models import Notification, NotificationType
from app.modules.users.models import User, UserRole, UserStatus


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
async def user_a(db_session: AsyncSession) -> User:
    u = User(
        email="user_a_8c@ptit.edu.vn",
        full_name="Nguyễn Khắc Thịnh",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    u = User(
        email="user_b_8c@ptit.edu.vn",
        full_name="Trần Thị B",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def user_c(db_session: AsyncSession) -> User:
    u = User(
        email="user_c_8c@ptit.edu.vn",
        full_name="Lê Văn C",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def user_d(db_session: AsyncSession) -> User:
    u = User(
        email="user_d_8c@ptit.edu.vn",
        full_name="Hoàng Thị D",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def group_conv(
    db_session: AsyncSession, user_a: User, user_b: User, user_c: User
) -> Conversation:
    conv = Conversation(
        type="GROUP",
        title="Nhóm Học Tập Kỹ Thuật",
    )
    db_session.add(conv)
    await db_session.flush()

    m_a = ConversationMember(conversation_id=conv.conversation_id, user_id=user_a.user_id, role="OWNER")
    m_b = ConversationMember(conversation_id=conv.conversation_id, user_id=user_b.user_id, role="MEMBER")
    m_c = ConversationMember(conversation_id=conv.conversation_id, user_id=user_c.user_id, role="MEMBER")
    db_session.add_all([m_a, m_b, m_c])
    await db_session.commit()
    return conv


@pytest.mark.asyncio
async def test_group_message_without_mentions_creates_zero_notifications(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
    db_session: AsyncSession,
):
    """1. Normal message in group without @mention creates ZERO notifications."""
    conv_id = group_conv.conversation_id
    content = "Chào mọi người trong nhóm nhé!"
    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={"content": content},
        )
    assert resp.status_code == 201

    notifs = (
        await db_session.scalars(
            select(Notification).where(
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == conv_id,
            )
        )
    ).all()
    assert len(notifs) == 0


@pytest.mark.asyncio
async def test_group_message_single_mention_success(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
    db_session: AsyncSession,
):
    """2. User A mentions User B -> 1 NEW_MESSAGE notification for User B, 0 for User A."""
    conv_id = group_conv.conversation_id
    group_title = group_conv.title
    user_b_id = user_b.user_id
    user_a_id = user_a.user_id
    user_a_name = user_a.full_name

    mention_token = f"@{user_b.full_name}"
    content = f"Xin chào {mention_token} bạn có ở đó không?"
    start_offset = content.index(mention_token)
    end_offset = start_offset + len(mention_token)

    mentions_payload = [
        {
            "mentioned_user_id": user_b_id,
            "display_text": mention_token,
            "start_offset": start_offset,
            "end_offset": end_offset,
        }
    ]

    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={
                "content": content,
                "mentions": json.dumps(mentions_payload),
            },
        )
    assert resp.status_code == 201
    msg_data = resp.json()
    assert len(msg_data["mentions"]) == 1

    # Verify notifications in DB
    notifs = (
        await db_session.scalars(
            select(Notification).where(
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == conv_id,
            )
        )
    ).all()
    assert len(notifs) == 1

    notif = notifs[0]
    assert notif.user_id == user_b_id
    assert notif.type == NotificationType.NEW_MESSAGE.value
    assert notif.title == "Bạn được nhắc đến trong nhóm"
    assert notif.body == f"{user_a_name} đã nhắc đến bạn trong {group_title}."
    assert notif.ref_type == "CONVERSATION"
    assert notif.ref_id == conv_id
    assert notif.is_read is False

    # Verify sender receives 0 notifications
    sender_notifs = (
        await db_session.scalars(
            select(Notification).where(Notification.user_id == user_a_id)
        )
    ).all()
    assert len(sender_notifs) == 0


@pytest.mark.asyncio
async def test_group_message_multiple_distinct_mentions(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    user_c: User,
    group_conv: Conversation,
    db_session: AsyncSession,
):
    """3. Mentioning both User B and User C creates exactly 1 notification for each."""
    conv_id = group_conv.conversation_id
    user_b_id = user_b.user_id
    user_c_id = user_c.user_id

    m_b = f"@{user_b.full_name}"
    m_c = f"@{user_c.full_name}"
    content = f"Alo {m_b} và {m_c} vào họp nhé!"
    b_start = content.index(m_b)
    b_end = b_start + len(m_b)
    c_start = content.index(m_c)
    c_end = c_start + len(m_c)

    mentions_payload = [
        {
            "mentioned_user_id": user_b_id,
            "display_text": m_b,
            "start_offset": b_start,
            "end_offset": b_end,
        },
        {
            "mentioned_user_id": user_c_id,
            "display_text": m_c,
            "start_offset": c_start,
            "end_offset": c_end,
        },
    ]

    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={
                "content": content,
                "mentions": json.dumps(mentions_payload),
            },
        )
    assert resp.status_code == 201

    notifs = (
        await db_session.scalars(
            select(Notification)
            .where(
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == conv_id,
            )
            .order_by(Notification.notification_id)
        )
    ).all()
    assert len(notifs) == 2

    recipient_ids = {n.user_id for n in notifs}
    assert recipient_ids == {user_b_id, user_c_id}


@pytest.mark.asyncio
async def test_group_message_duplicate_mention_deduplication(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
    db_session: AsyncSession,
):
    """4. Mentioning the same user multiple times in one message produces only 1 notification."""
    conv_id = group_conv.conversation_id
    user_b_id = user_b.user_id

    m_b = f"@{user_b.full_name}"
    content = f"Alo {m_b}, nhớ check mail nhé {m_b}!"
    first_start = content.index(m_b)
    first_end = first_start + len(m_b)
    second_start = content.rindex(m_b)
    second_end = second_start + len(m_b)

    mentions_payload = [
        {
            "mentioned_user_id": user_b_id,
            "display_text": m_b,
            "start_offset": first_start,
            "end_offset": first_end,
        },
        {
            "mentioned_user_id": user_b_id,
            "display_text": m_b,
            "start_offset": second_start,
            "end_offset": second_end,
        },
    ]

    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={
                "content": content,
                "mentions": json.dumps(mentions_payload),
            },
        )
    assert resp.status_code == 201

    notifs = (
        await db_session.scalars(
            select(Notification).where(
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == conv_id,
            )
        )
    ).all()
    assert len(notifs) == 1
    assert notifs[0].user_id == user_b_id


@pytest.mark.asyncio
async def test_group_message_self_mention_excluded(
    test_client: AsyncClient,
    user_a: User,
    group_conv: Conversation,
    db_session: AsyncSession,
):
    """5. Self-mention is excluded and produces 0 notifications."""
    conv_id = group_conv.conversation_id
    user_a_id = user_a.user_id

    m_a = f"@{user_a.full_name}"
    content = f"Tôi tự tag bản thân {m_a}"
    start = content.index(m_a)
    end = start + len(m_a)

    mentions_payload = [
        {
            "mentioned_user_id": user_a_id,
            "display_text": m_a,
            "start_offset": start,
            "end_offset": end,
        }
    ]

    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={
                "content": content,
                "mentions": json.dumps(mentions_payload),
            },
        )
    assert resp.status_code == 201

    notifs = (
        await db_session.scalars(
            select(Notification).where(
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == conv_id,
            )
        )
    ).all()
    assert len(notifs) == 0


@pytest.mark.asyncio
async def test_mention_left_member_rejected(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
    db_session: AsyncSession,
):
    """6. Mentioning a member who has left the group -> 422, 0 notifications."""
    conv_id = group_conv.conversation_id
    user_b_id = user_b.user_id

    # User B leaves the group
    with auth_patch(user_b):
        leave_resp = await test_client.post(
            f"/api/v1/conversations/groups/{conv_id}/leave"
        )
    assert leave_resp.status_code == 200

    m_b = f"@{user_b.full_name}"
    content = f"Chào {m_b} quay lại đi!"
    start = content.index(m_b)
    end = start + len(m_b)

    mentions_payload = [
        {
            "mentioned_user_id": user_b_id,
            "display_text": m_b,
            "start_offset": start,
            "end_offset": end,
        }
    ]

    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={
                "content": content,
                "mentions": json.dumps(mentions_payload),
            },
        )
    assert resp.status_code == 422

    notifs = (
        await db_session.scalars(
            select(Notification).where(
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == conv_id,
            )
        )
    ).all()
    assert len(notifs) == 0


@pytest.mark.asyncio
async def test_mention_non_member_rejected(
    test_client: AsyncClient,
    user_a: User,
    user_d: User,
    group_conv: Conversation,
    db_session: AsyncSession,
):
    """7. Mentioning a user who is not in the group -> 422, 0 notifications."""
    conv_id = group_conv.conversation_id
    user_d_id = user_d.user_id

    m_d = f"@{user_d.full_name}"
    content = f"Chào {m_d} bạn mới!"
    start = content.index(m_d)
    end = start + len(m_d)

    mentions_payload = [
        {
            "mentioned_user_id": user_d_id,
            "display_text": m_d,
            "start_offset": start,
            "end_offset": end,
        }
    ]

    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={
                "content": content,
                "mentions": json.dumps(mentions_payload),
            },
        )
    assert resp.status_code == 422

    notifs = (
        await db_session.scalars(
            select(Notification).where(
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == conv_id,
            )
        )
    ).all()
    assert len(notifs) == 0


@pytest.mark.asyncio
async def test_mentions_in_direct_chat_rejected(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    db_session: AsyncSession,
):
    """8. Mentions in DIRECT conversation -> 400 Bad Request, 0 notifications."""
    direct_conv = Conversation(
        type="DIRECT",
        user_one_id=user_a.user_id,
        user_two_id=user_b.user_id,
    )
    db_session.add(direct_conv)
    await db_session.flush()
    direct_id = direct_conv.conversation_id

    m_a = ConversationMember(conversation_id=direct_id, user_id=user_a.user_id, role="MEMBER")
    m_b = ConversationMember(conversation_id=direct_id, user_id=user_b.user_id, role="MEMBER")
    db_session.add_all([m_a, m_b])
    await db_session.commit()

    token = f"@{user_b.full_name}"
    content = f"Này {token}"
    mentions_payload = [
        {
            "mentioned_user_id": user_b.user_id,
            "display_text": token,
            "start_offset": content.index(token),
            "end_offset": content.index(token) + len(token),
        }
    ]

    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/{direct_id}/messages",
            data={
                "content": content,
                "mentions": json.dumps(mentions_payload),
            },
        )
    assert resp.status_code == 400

    notifs = (
        await db_session.scalars(
            select(Notification).where(
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == direct_id,
            )
        )
    ).all()
    assert len(notifs) == 0


@pytest.mark.asyncio
async def test_mentions_in_community_persists_without_notifications(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    db_session: AsyncSession,
):
    """9. Mentions in COMMUNITY persist mentions metadata, but produce ZERO notifications."""
    with auth_patch(user_a):
        comm_resp = await test_client.get("/api/v1/conversations/community")
        assert comm_resp.status_code == 200
        comm_id = comm_resp.json()["conversation_id"]
        await test_client.post(f"/api/v1/conversations/community/{comm_id}/join")

    with auth_patch(user_b):
        await test_client.post(f"/api/v1/conversations/community/{comm_id}/join")

    token = f"@{user_b.full_name}"
    content = f"Xin chào cộng đồng và {token}"
    mentions_payload = [
        {
            "mentioned_user_id": user_b.user_id,
            "display_text": token,
            "start_offset": content.index(token),
            "end_offset": content.index(token) + len(token),
        }
    ]

    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/{comm_id}/messages",
            data={
                "content": content,
                "mentions": json.dumps(mentions_payload),
            },
        )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["mentions"]) == 1

    # In Phase 8C, mention notifications are GROUP only; COMMUNITY produces 0 notifications
    notifs = (
        await db_session.scalars(
            select(Notification).where(
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == comm_id,
            )
        )
    ).all()
    assert len(notifs) == 0


@pytest.mark.asyncio
async def test_system_message_in_group_creates_zero_notifications(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
    db_session: AsyncSession,
):
    """10. System message in group produces 0 notifications."""
    conv_id = group_conv.conversation_id
    with auth_patch(user_a):
        # Update group title generates a SYSTEM message
        resp = await test_client.patch(
            f"/api/v1/conversations/groups/{conv_id}",
            json={"title": "Nhóm Đã Đổi Tên"},
        )
    assert resp.status_code == 200

    notifs = (
        await db_session.scalars(
            select(Notification).where(
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == conv_id,
            )
        )
    ).all()
    assert len(notifs) == 0


@pytest.mark.asyncio
async def test_atomicity_pre_commit_failure_rolls_back_all(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
    db_session: AsyncSession,
):
    """11. Atomicity: Forced pre-commit failure -> 0 Message, 0 MessageMention, 0 Notification rows."""
    conv_id = group_conv.conversation_id
    user_b_id = user_b.user_id

    token = f"@{user_b.full_name}"
    content = f"Thử nghiệm rollback {token}"
    mentions_payload = [
        {
            "mentioned_user_id": user_b_id,
            "display_text": token,
            "start_offset": content.index(token),
            "end_offset": content.index(token) + len(token),
        }
    ]

    initial_msg_count = await db_session.scalar(
        select(func.count(Message.message_id)).where(Message.conversation_id == conv_id)
    )
    initial_notif_count = await db_session.scalar(
        select(func.count(Notification.notification_id)).where(Notification.ref_id == conv_id)
    )

    from app.modules.conversations.service import ConversationService
    original_send = ConversationService.send_message

    async def crashing_send(self, *args, **kwargs):
        orig_commit = self.db.commit
        async def mock_commit():
            raise RuntimeError("CRITICAL_SIMULATED_DB_COMMIT_FAILURE")
        self.db.commit = mock_commit
        try:
            return await original_send(self, *args, **kwargs)
        finally:
            self.db.commit = orig_commit

    with patch.object(ConversationService, "send_message", crashing_send):
        with auth_patch(user_a):
            resp = await test_client.post(
                f"/api/v1/conversations/{conv_id}/messages",
                data={
                    "content": content,
                    "mentions": json.dumps(mentions_payload),
                },
            )
        assert resp.status_code == 500

    # Ensure clean rollback: message count and notification count unchanged
    current_msg_count = await db_session.scalar(
        select(func.count(Message.message_id)).where(Message.conversation_id == conv_id)
    )
    current_notif_count = await db_session.scalar(
        select(func.count(Notification.notification_id)).where(Notification.ref_id == conv_id)
    )
    assert current_msg_count == initial_msg_count
    assert current_notif_count == initial_notif_count


@pytest.mark.asyncio
async def test_persisted_recipients_equal_notification_recipients(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    user_c: User,
    group_conv: Conversation,
    db_session: AsyncSession,
):
    """12. Persisted MessageMention recipients exactly equal distinct Notification recipients."""
    conv_id = group_conv.conversation_id
    user_b_id = user_b.user_id
    user_c_id = user_c.user_id

    m_b = f"@{user_b.full_name}"
    m_c = f"@{user_c.full_name}"
    content = f"Xin chào {m_b} và {m_c}!"
    mentions_payload = [
        {
            "mentioned_user_id": user_b_id,
            "display_text": m_b,
            "start_offset": content.index(m_b),
            "end_offset": content.index(m_b) + len(m_b),
        },
        {
            "mentioned_user_id": user_c_id,
            "display_text": m_c,
            "start_offset": content.index(m_c),
            "end_offset": content.index(m_c) + len(m_c),
        },
    ]

    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={
                "content": content,
                "mentions": json.dumps(mentions_payload),
            },
        )
    assert resp.status_code == 201
    msg_id = resp.json()["message_id"]

    # Check MessageMention rows
    persisted_mentions = (
        await db_session.scalars(
            select(MessageMention.mentioned_user_id).where(MessageMention.message_id == msg_id)
        )
    ).all()

    # Check Notification rows
    persisted_notif_uids = (
        await db_session.scalars(
            select(Notification.user_id).where(
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == conv_id,
            )
        )
    ).all()

    assert set(persisted_mentions) == {user_b_id, user_c_id}
    assert set(persisted_notif_uids) == {user_b_id, user_c_id}
    assert set(persisted_mentions) == set(persisted_notif_uids)


@pytest.mark.asyncio
async def test_realtime_isolation_message_created_failure_does_not_block_notification(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
    db_session: AsyncSession,
):
    """13. Realtime isolation: MESSAGE_CREATED broadcast failure does NOT block NOTIFICATION_CREATED delivery."""
    conv_id = group_conv.conversation_id
    user_b_id = user_b.user_id

    token = f"@{user_b.full_name}"
    content = f"Test realtime isolation {token}"
    mentions_payload = [
        {
            "mentioned_user_id": user_b_id,
            "display_text": token,
            "start_offset": content.index(token),
            "end_offset": content.index(token) + len(token),
        }
    ]

    published_events = []

    async def mock_publish(user_id, event):
        published_events.append((user_id, event))
        if event.get("type") == "MESSAGE_CREATED":
            raise RuntimeError("Simulated MESSAGE_CREATED websocket broadcast failure")

    with patch("app.modules.conversations.service.publish_user_event", side_effect=mock_publish):
        with auth_patch(user_a):
            resp = await test_client.post(
                f"/api/v1/conversations/{conv_id}/messages",
                data={
                    "content": content,
                    "mentions": json.dumps(mentions_payload),
                },
            )
        assert resp.status_code == 201

    # Verify NOTIFICATION_CREATED event was attempted for User B
    notif_events = [
        (uid, ev) for uid, ev in published_events if ev.get("type") == "NOTIFICATION_CREATED"
    ]
    assert len(notif_events) == 1
    assert notif_events[0][0] == user_b_id
    assert notif_events[0][1]["notification"]["type"] == "NEW_MESSAGE"


@pytest.mark.asyncio
async def test_realtime_isolation_recipient_failure_does_not_block_other_recipients(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    user_c: User,
    group_conv: Conversation,
    db_session: AsyncSession,
):
    """14. Realtime isolation: User B notification publish failure does NOT block User C notification publish."""
    conv_id = group_conv.conversation_id
    user_b_id = user_b.user_id
    user_c_id = user_c.user_id

    m_b = f"@{user_b.full_name}"
    m_c = f"@{user_c.full_name}"
    content = f"Test recipient isolation {m_b} {m_c}"
    mentions_payload = [
        {
            "mentioned_user_id": user_b_id,
            "display_text": m_b,
            "start_offset": content.index(m_b),
            "end_offset": content.index(m_b) + len(m_b),
        },
        {
            "mentioned_user_id": user_c_id,
            "display_text": m_c,
            "start_offset": content.index(m_c),
            "end_offset": content.index(m_c) + len(m_c),
        },
    ]

    published_events = []

    async def mock_publish(user_id, event):
        published_events.append((user_id, event))
        if event.get("type") == "NOTIFICATION_CREATED" and user_id == user_b_id:
            raise RuntimeError("Simulated User B notification websocket failure")

    with patch("app.modules.conversations.service.publish_user_event", side_effect=mock_publish):
        with auth_patch(user_a):
            resp = await test_client.post(
                f"/api/v1/conversations/{conv_id}/messages",
                data={
                    "content": content,
                    "mentions": json.dumps(mentions_payload),
                },
            )
        assert resp.status_code == 201

    # Verify both User B and User C notification publish calls were attempted
    notif_uids = [
        uid for uid, ev in published_events if ev.get("type") == "NOTIFICATION_CREATED"
    ]
    assert user_b_id in notif_uids
    assert user_c_id in notif_uids

    # Both notifications remain persisted in DB
    db_notif_uids = (
        await db_session.scalars(
            select(Notification.user_id).where(
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == conv_id,
            )
        )
    ).all()
    assert set(db_notif_uids) == {user_b_id, user_c_id}


@pytest.mark.asyncio
async def test_same_display_name_distinguished_by_user_id(
    test_client: AsyncClient,
    user_a: User,
    db_session: AsyncSession,
):
    """15. Two users with identical display name 'Nguyễn Văn Test' are distinguished strictly by user_id."""
    u1 = User(
        email="dup1_8c@ptit.edu.vn",
        full_name="Nguyễn Văn Test",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    u2 = User(
        email="dup2_8c@ptit.edu.vn",
        full_name="Nguyễn Văn Test",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add_all([u1, u2])
    await db_session.flush()
    u1_id = u1.user_id
    u2_id = u2.user_id

    conv = Conversation(
        type="GROUP",
        title="Nhóm Trùng Tên Thành Viên",
    )
    db_session.add(conv)
    await db_session.flush()
    conv_id = conv.conversation_id

    m_a = ConversationMember(conversation_id=conv_id, user_id=user_a.user_id, role="OWNER")
    m_1 = ConversationMember(conversation_id=conv_id, user_id=u1_id, role="MEMBER")
    m_2 = ConversationMember(conversation_id=conv_id, user_id=u2_id, role="MEMBER")
    db_session.add_all([m_a, m_1, m_2])
    await db_session.commit()

    token = "@Nguyễn Văn Test"
    content = f"Chào {token} nhé!"
    # User A explicitly selects u1 (u1.user_id)
    mentions_payload = [
        {
            "mentioned_user_id": u1_id,
            "display_text": token,
            "start_offset": content.index(token),
            "end_offset": content.index(token) + len(token),
        }
    ]

    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={
                "content": content,
                "mentions": json.dumps(mentions_payload),
            },
        )
    assert resp.status_code == 201

    notifs = (
        await db_session.scalars(
            select(Notification).where(
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == conv_id,
            )
        )
    ).all()
    assert len(notifs) == 1
    assert notifs[0].user_id == u1_id  # Only u1 receives notification
