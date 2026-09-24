import json
from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.conversations.models import (
    Conversation,
    ConversationInvite,
    ConversationMember,
    Message,
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
        email="owner_inv@ptit.edu.vn",
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
        email="invitee_b@ptit.edu.vn",
        full_name="Trần Văn Nam",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def user_c(db_session: AsyncSession) -> User:
    u = User(
        email="invitee_c@ptit.edu.vn",
        full_name="Lê Thị Mai",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def group_conv(db_session: AsyncSession, user_a: User) -> Conversation:
    conv = Conversation(
        type="GROUP",
        title="Nhóm D24CT01",
    )
    db_session.add(conv)
    await db_session.flush()

    mem = ConversationMember(
        conversation_id=conv.conversation_id,
        user_id=user_a.user_id,
        role="OWNER",
    )
    db_session.add(mem)
    await db_session.commit()
    return conv


@pytest.mark.asyncio
async def test_single_valid_invite_creates_one_durable_system_notification(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
):
    """1. Single valid group invite creates exactly one invite row and one durable SYSTEM notification."""
    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/invites",
            json={"invitee_ids": [user_b.user_id]},
        )
    assert resp.status_code == 200, resp.text
    invites_data = resp.json()
    assert len(invites_data) == 1
    invite_id = invites_data[0]["invite_id"]

    # Verify conversation_invites row in DB
    inv_stmt = select(ConversationInvite).where(ConversationInvite.invite_id == invite_id)
    inv_row = await db_session.scalar(inv_stmt)
    assert inv_row is not None
    assert inv_row.invitee_id == user_b.user_id
    assert inv_row.status == "PENDING"

    # Verify notifications row in DB
    notif_stmt = select(Notification).where(
        Notification.user_id == user_b.user_id,
        Notification.ref_type == "GROUP_INVITE",
    )
    notifications = (await db_session.scalars(notif_stmt)).all()
    assert len(notifications) == 1
    notif = notifications[0]

    # Verify notification attributes
    assert notif.type == NotificationType.SYSTEM.value
    assert notif.ref_type == "GROUP_INVITE"
    assert notif.ref_id == invite_id
    assert notif.is_read is False
    assert notif.title == "Bạn có lời mời tham gia nhóm"
    assert notif.body == f"{user_a.full_name} đã mời bạn tham gia {group_conv.title}."


@pytest.mark.asyncio
async def test_inviter_gets_no_self_action_notification(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
):
    """2. Inviter does not receive a self-action notification."""
    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/invites",
            json={"invitee_ids": [user_b.user_id]},
        )
    assert resp.status_code == 200

    notif_stmt = select(Notification).where(Notification.user_id == user_a.user_id)
    inviter_notifs = (await db_session.scalars(notif_stmt)).all()
    assert len(inviter_notifs) == 0


@pytest.mark.asyncio
async def test_notification_copy_is_privacy_safe(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
):
    """3. Notification copy contains no private/sensitive profile details."""
    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/invites",
            json={"invitee_ids": [user_b.user_id]},
        )
    assert resp.status_code == 200

    notif_stmt = select(Notification).where(
        Notification.user_id == user_b.user_id,
        Notification.ref_type == "GROUP_INVITE",
    )
    notif = await db_session.scalar(notif_stmt)
    assert notif is not None
    # Verify no email, phone, or private tokens leaked into title/body
    assert user_a.email not in notif.body
    assert "@" not in notif.body
    assert notif.title == "Bạn có lời mời tham gia nhóm"


@pytest.mark.asyncio
async def test_duplicate_invite_creates_no_duplicate_notification(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
):
    """4. Duplicate rejected invite creates 0 additional notifications."""
    with auth_patch(user_a):
        resp1 = await test_client.post(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/invites",
            json={"invitee_ids": [user_b.user_id]},
        )
    assert resp1.status_code == 200
    assert len(resp1.json()) == 1

    # Attempt second invite while first is still PENDING
    with auth_patch(user_a):
        resp2 = await test_client.post(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/invites",
            json={"invitee_ids": [user_b.user_id]},
        )
    assert resp2.status_code == 200
    assert len(resp2.json()) == 0  # Filtered as duplicate

    # Verify exactly one notification exists for user_b
    notif_stmt = select(Notification).where(
        Notification.user_id == user_b.user_id,
        Notification.ref_type == "GROUP_INVITE",
    )
    notifs = (await db_session.scalars(notif_stmt)).all()
    assert len(notifs) == 1


@pytest.mark.asyncio
async def test_accept_invite_does_not_create_invite_created_notification(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
):
    """5. Accepting invite joins group and does not create an invite-created notification."""
    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/invites",
            json={"invitee_ids": [user_b.user_id]},
        )
    invite_id = resp.json()[0]["invite_id"]

    # User B accepts
    with auth_patch(user_b):
        resp_acc = await test_client.post(
            f"/api/v1/conversations/invites/{invite_id}/respond",
            json={"action": "ACCEPT"},
        )
    assert resp_acc.status_code == 200

    # Verify no new GROUP_INVITE notification was created
    notif_stmt = select(Notification).where(
        Notification.user_id == user_b.user_id,
        Notification.ref_type == "GROUP_INVITE",
    )
    notifs = (await db_session.scalars(notif_stmt)).all()
    assert len(notifs) == 1


@pytest.mark.asyncio
async def test_decline_invite_does_not_create_invite_created_notification(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
):
    """6. Declining invite updates status and does not create an invite-created notification."""
    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/invites",
            json={"invitee_ids": [user_b.user_id]},
        )
    invite_id = resp.json()[0]["invite_id"]

    # User B declines
    with auth_patch(user_b):
        resp_dec = await test_client.post(
            f"/api/v1/conversations/invites/{invite_id}/respond",
            json={"action": "DECLINE"},
        )
    assert resp_dec.status_code == 200

    notif_stmt = select(Notification).where(
        Notification.user_id == user_b.user_id,
        Notification.ref_type == "GROUP_INVITE",
    )
    notifs = (await db_session.scalars(notif_stmt)).all()
    assert len(notifs) == 1


@pytest.mark.asyncio
async def test_pre_commit_failure_atomic_rollback(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
):
    """7. Pre-commit failure guarantees 0 committed invites, 0 notifications, 0 realtime events."""
    published_events = []
    conv_id = group_conv.conversation_id
    target_uid = user_b.user_id

    async def mock_publish(uid, ev):
        published_events.append((uid, ev))

    with patch("app.modules.conversations.service.publish_user_event", side_effect=mock_publish):
        with patch.object(AsyncSession, "commit", side_effect=RuntimeError("DB_CONNECTION_LOST")):
            with auth_patch(user_a):
                with pytest.raises(RuntimeError, match="DB_CONNECTION_LOST"):
                    await test_client.post(
                        f"/api/v1/conversations/groups/{conv_id}/invites",
                        json={"invitee_ids": [target_uid]},
                    )

    # Clean session verification: failed transaction leaves 0 rows persisted
    await db_session.rollback()
    inv_stmt = select(ConversationInvite).where(
        ConversationInvite.conversation_id == conv_id,
        ConversationInvite.invitee_id == target_uid,
    )
    invites = (await db_session.scalars(inv_stmt)).all()
    assert len(invites) == 0

    notif_stmt = select(Notification).where(
        Notification.user_id == target_uid,
        Notification.ref_type == "GROUP_INVITE",
    )
    notifs = (await db_session.scalars(notif_stmt)).all()
    assert len(notifs) == 0
    assert len(published_events) == 0


@pytest.mark.asyncio
async def test_realtime_events_dispatched_post_commit(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
):
    """8. GROUP_INVITE_CREATED and NOTIFICATION_CREATED are published post-commit with correct payloads."""
    published_events = []

    async def mock_publish(uid, ev):
        published_events.append((uid, ev))

    with patch("app.modules.conversations.service.publish_user_event", side_effect=mock_publish):
        with auth_patch(user_a):
            resp = await test_client.post(
                f"/api/v1/conversations/groups/{group_conv.conversation_id}/invites",
                json={"invitee_ids": [user_b.user_id]},
            )
    assert resp.status_code == 200
    invite_id = resp.json()[0]["invite_id"]

    # Verify GROUP_INVITE_CREATED
    invite_events = [
        ev for uid, ev in published_events
        if uid == user_b.user_id and ev.get("type") == "GROUP_INVITE_CREATED"
    ]
    assert len(invite_events) == 1
    assert invite_events[0]["invite_id"] == invite_id
    assert invite_events[0]["conversation_id"] == group_conv.conversation_id

    # Verify NOTIFICATION_CREATED
    notif_events = [
        ev for uid, ev in published_events
        if uid == user_b.user_id and ev.get("type") == "NOTIFICATION_CREATED"
    ]
    assert len(notif_events) == 1
    notif_payload = notif_events[0]["notification"]
    assert notif_payload["type"] == "SYSTEM"
    assert notif_payload["ref_type"] == "GROUP_INVITE"
    assert notif_payload["ref_id"] == invite_id
    assert notif_payload["title"] == "Bạn có lời mời tham gia nhóm"


@pytest.mark.asyncio
async def test_realtime_failure_does_not_rollback_database(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
):
    """9. Realtime delivery failure does not roll back committed invite and notification rows."""
    with patch("app.modules.conversations.service.publish_user_event", side_effect=Exception("WS_UNAVAILABLE")):
        with auth_patch(user_a):
            resp = await test_client.post(
                f"/api/v1/conversations/groups/{group_conv.conversation_id}/invites",
                json={"invitee_ids": [user_b.user_id]},
            )
    assert resp.status_code == 200
    invite_id = resp.json()[0]["invite_id"]

    # Verify database rows remain securely committed
    inv = await db_session.scalar(
        select(ConversationInvite).where(ConversationInvite.invite_id == invite_id)
    )
    assert inv is not None
    assert inv.status == "PENDING"

    notif = await db_session.scalar(
        select(Notification).where(
            Notification.user_id == user_b.user_id,
            Notification.ref_type == "GROUP_INVITE",
        )
    )
    assert notif is not None
    assert notif.ref_id == invite_id


@pytest.mark.asyncio
async def test_one_realtime_failure_does_not_prevent_other_delivery(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
):
    """10. GROUP_INVITE_CREATED failure does not block NOTIFICATION_CREATED from being attempted."""
    notification_attempted = []

    async def selective_publish(uid, ev):
        if ev.get("type") == "GROUP_INVITE_CREATED":
            raise RuntimeError("GROUP_INVITE_WS_FAILED")
        if ev.get("type") == "NOTIFICATION_CREATED":
            notification_attempted.append((uid, ev))

    with patch("app.modules.conversations.service.publish_user_event", side_effect=selective_publish):
        with auth_patch(user_a):
            resp = await test_client.post(
                f"/api/v1/conversations/groups/{group_conv.conversation_id}/invites",
                json={"invitee_ids": [user_b.user_id]},
            )
    assert resp.status_code == 200
    # NOTIFICATION_CREATED was still attempted despite GROUP_INVITE_CREATED failing
    assert len(notification_attempted) == 1
    assert notification_attempted[0][0] == user_b.user_id


@pytest.mark.asyncio
async def test_batch_invite_creates_one_notification_per_new_invite(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    user_c: User,
    group_conv: Conversation,
):
    """11. Multi-invite creates exactly one durable notification per actually created invite without leak."""
    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/invites",
            json={"invitee_ids": [user_b.user_id, user_c.user_id]},
        )
    assert resp.status_code == 200
    invites = resp.json()
    assert len(invites) == 2

    # Verify B's notification
    notif_b = await db_session.scalar(
        select(Notification).where(
            Notification.user_id == user_b.user_id,
            Notification.ref_type == "GROUP_INVITE",
        )
    )
    assert notif_b is not None

    # Verify C's notification
    notif_c = await db_session.scalar(
        select(Notification).where(
            Notification.user_id == user_c.user_id,
            Notification.ref_type == "GROUP_INVITE",
        )
    )
    assert notif_c is not None

    # Ref IDs match their respective invites
    b_invite = next(i for i in invites if i["invite_id"] == notif_b.ref_id)
    c_invite = next(i for i in invites if i["invite_id"] == notif_c.ref_id)
    assert b_invite is not None
    assert c_invite is not None
    assert notif_b.ref_id != notif_c.ref_id


@pytest.mark.asyncio
async def test_batch_invite_with_existing_member_only_notifies_new_target(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    user_c: User,
    group_conv: Conversation,
):
    """12. If one user in batch is already active member, only the new invitee receives an invite and notification."""
    # Add User B as member
    mem_b = ConversationMember(
        conversation_id=group_conv.conversation_id,
        user_id=user_b.user_id,
        role="MEMBER",
    )
    db_session.add(mem_b)
    await db_session.commit()

    # User A invites B and C
    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/invites",
            json={"invitee_ids": [user_b.user_id, user_c.user_id]},
        )
    assert resp.status_code == 200
    invites = resp.json()
    # Only C gets invited
    assert len(invites) == 1
    assert invites[0]["inviter_id"] == user_a.user_id

    # User B got 0 notifications
    notif_b = await db_session.scalar(
        select(Notification).where(
            Notification.user_id == user_b.user_id,
            Notification.ref_type == "GROUP_INVITE",
        )
    )
    assert notif_b is None

    # User C got exactly 1 notification
    notif_c = await db_session.scalar(
        select(Notification).where(
            Notification.user_id == user_c.user_id,
            Notification.ref_type == "GROUP_INVITE",
        )
    )
    assert notif_c is not None
    assert notif_c.ref_id == invites[0]["invite_id"]


@pytest.mark.asyncio
async def test_group_system_timeline_message_creates_zero_notifications(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
    group_conv: Conversation,
):
    """13. Invariant: Group SYSTEM timeline messages (Message.type == SYSTEM) do not create Notification rows."""
    # Add User B to group
    mem_b = ConversationMember(
        conversation_id=group_conv.conversation_id,
        user_id=user_b.user_id,
        role="MEMBER",
    )
    db_session.add(mem_b)
    # Insert system message
    msg = Message(
        conversation_id=group_conv.conversation_id,
        sender_id=user_a.user_id,
        content="Nguyễn Khắc Thịnh đã đổi tên nhóm.",
        type="SYSTEM",
    )
    db_session.add(msg)
    await db_session.commit()

    # Verify zero notifications created from this message for group member
    notifs = (
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == user_b.user_id,
                Notification.ref_id == group_conv.conversation_id,
            )
        )
    ).all()
    assert len(notifs) == 0
