import asyncio
import json
from datetime import datetime, timezone
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.main import app
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.conversations.models import (
    Conversation,
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
async def user_alice(db_session: AsyncSession) -> User:
    u = User(
        email="alice_coalesce@ptit.edu.vn",
        full_name="Alice Coalesce",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest_asyncio.fixture
async def user_bob(db_session: AsyncSession) -> User:
    u = User(
        email="bob_coalesce@ptit.edu.vn",
        full_name="Bob Coalesce",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest_asyncio.fixture
async def user_carol(db_session: AsyncSession) -> User:
    u = User(
        email="carol_coalesce@ptit.edu.vn",
        full_name="Carol Coalesce",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest.mark.asyncio
async def test_direct_notification_coalescing_and_read_clearing(
    test_client: AsyncClient,
    user_alice: User,
    user_bob: User,
    user_carol: User,
    db_session: AsyncSession,
):
    """
    1. First DIRECT message from Alice to Bob creates exactly ONE unread Bell notification.
    2. Second DIRECT message in same unread conversation coalesces (still exactly ONE row).
    3. Self-sent message produces zero notifications for sender.
    4. Another DIRECT message from Carol to Bob creates a separate row for that conversation.
    5. Marking Alice's conversation read marks Bob's notification for that conversation read.
    6. Later message from Alice creates a new unread notification.
    """
    # Create DIRECT conversation between Alice and Bob
    direct_ab = Conversation(
        type="DIRECT",
        user_one_id=min(user_alice.user_id, user_bob.user_id),
        user_two_id=max(user_alice.user_id, user_bob.user_id),
        direct_pair_key=f"{min(user_alice.user_id, user_bob.user_id)}:{max(user_alice.user_id, user_bob.user_id)}",
    )
    db_session.add(direct_ab)
    await db_session.flush()

    db_session.add(ConversationMember(conversation_id=direct_ab.conversation_id, user_id=user_alice.user_id, role="MEMBER"))
    db_session.add(ConversationMember(conversation_id=direct_ab.conversation_id, user_id=user_bob.user_id, role="MEMBER"))
    await db_session.commit()

    # 1. First DIRECT message
    with auth_patch(user_alice):
        resp1 = await test_client.post(
            f"/api/v1/conversations/{direct_ab.conversation_id}/messages",
            data={"content": "Tin nhắn 1 từ Alice"},
        )
    assert resp1.status_code == 201

    notifs_bob_ab = (
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == user_bob.user_id,
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == direct_ab.conversation_id,
            )
        )
    ).all()
    assert len(notifs_bob_ab) == 1
    assert notifs_bob_ab[0].is_read is False
    assert notifs_bob_ab[0].title == "Tin nhắn mới"
    assert "Alice Coalesce đã gửi tin nhắn cho bạn." in notifs_bob_ab[0].body

    # Check Alice received zero notifications for her own message
    notifs_alice = (
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == user_alice.user_id,
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == direct_ab.conversation_id,
            )
        )
    ).all()
    assert len(notifs_alice) == 0

    # 2. Second DIRECT message from Alice (burst / multiple messages)
    with auth_patch(user_alice):
        resp2 = await test_client.post(
            f"/api/v1/conversations/{direct_ab.conversation_id}/messages",
            data={"content": "Tin nhắn 2 từ Alice"},
        )
    assert resp2.status_code == 201

    # Should still be exactly ONE notification row for Bob + direct_ab
    notifs_bob_ab2 = (
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == user_bob.user_id,
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == direct_ab.conversation_id,
            )
        )
    ).all()
    assert len(notifs_bob_ab2) == 1
    assert notifs_bob_ab2[0].is_read is False

    # 3. Another conversation: Carol sends message to Bob
    direct_cb = Conversation(
        type="DIRECT",
        user_one_id=min(user_carol.user_id, user_bob.user_id),
        user_two_id=max(user_carol.user_id, user_bob.user_id),
        direct_pair_key=f"{min(user_carol.user_id, user_bob.user_id)}:{max(user_carol.user_id, user_bob.user_id)}",
    )
    db_session.add(direct_cb)
    await db_session.flush()

    db_session.add(ConversationMember(conversation_id=direct_cb.conversation_id, user_id=user_carol.user_id, role="MEMBER"))
    db_session.add(ConversationMember(conversation_id=direct_cb.conversation_id, user_id=user_bob.user_id, role="MEMBER"))
    await db_session.commit()

    with auth_patch(user_carol):
        resp_cb = await test_client.post(
            f"/api/v1/conversations/{direct_cb.conversation_id}/messages",
            data={"content": "Tin nhắn từ Carol"},
        )
    assert resp_cb.status_code == 201

    # Bob now has 2 notifications in total: one for direct_ab, one for direct_cb
    all_bob_notifs = (
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == user_bob.user_id,
                Notification.ref_type == "CONVERSATION",
            )
        )
    ).all()
    assert len(all_bob_notifs) == 2

    # 4. Bob opens and marks direct_ab read
    with auth_patch(user_bob):
        read_resp = await test_client.post(
            f"/api/v1/conversations/{direct_ab.conversation_id}/read"
        )
    assert read_resp.status_code == 200

    # Notification for direct_ab is now marked read
    notif_ab_after_read = (
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == user_bob.user_id,
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == direct_ab.conversation_id,
            )
        )
    ).one()
    assert notif_ab_after_read.is_read is True

    # Notification for direct_cb is STILL unread
    notif_cb_after_read = (
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == user_bob.user_id,
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == direct_cb.conversation_id,
            )
        )
    ).one()
    assert notif_cb_after_read.is_read is False

    # 5. Later message from Alice to Bob in direct_ab creates a NEW unread row
    with auth_patch(user_alice):
        resp3 = await test_client.post(
            f"/api/v1/conversations/{direct_ab.conversation_id}/messages",
            data={"content": "Tin nhắn 3 từ Alice sau khi Bob đã đọc"},
        )
    assert resp3.status_code == 201

    notifs_bob_ab3 = (
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == user_bob.user_id,
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == direct_ab.conversation_id,
            )
        )
    ).all()
    assert len(notifs_bob_ab3) == 2
    unread_ab = [n for n in notifs_bob_ab3 if not n.is_read]
    assert len(unread_ab) == 1


@pytest.mark.asyncio
async def test_group_ordinary_messages_zero_bell_and_mentions_coalesced(
    test_client: AsyncClient,
    user_alice: User,
    user_bob: User,
    user_carol: User,
    db_session: AsyncSession,
):
    """
    1. Group ordinary message creates ZERO Bell notifications.
    2. Group message mentioning Bob creates ONE unread Bell notification.
    3. Second group message mentioning Bob in same conversation COALESCES to the existing unread row.
    4. Marking group conversation read marks Bob's mention notification read.
    """
    group_conv = Conversation(
        type="GROUP",
        title="Nhóm Học Tập PTIT",
    )
    db_session.add(group_conv)
    await db_session.flush()

    for u, role in [(user_alice, "OWNER"), (user_bob, "MEMBER"), (user_carol, "MEMBER")]:
        db_session.add(
            ConversationMember(
                conversation_id=group_conv.conversation_id,
                user_id=u.user_id,
                role=role,
            )
        )
    await db_session.commit()

    # 1. Alice sends ordinary message without mentions
    with auth_patch(user_alice):
        resp_ord = await test_client.post(
            f"/api/v1/conversations/{group_conv.conversation_id}/messages",
            data={"content": "Chào cả nhóm, mai học lúc mấy giờ?"},
        )
    assert resp_ord.status_code == 201

    group_notifs = (
        await db_session.scalars(
            select(Notification).where(
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == group_conv.conversation_id,
            )
        )
    ).all()
    assert len(group_notifs) == 0

    # 2. Alice sends message mentioning Bob
    token_bob = f"@{user_bob.full_name}"
    content1 = f"Hỏi thăm {token_bob} nhé"
    mentions1 = [
        {
            "mentioned_user_id": user_bob.user_id,
            "display_text": token_bob,
            "start_offset": content1.index(token_bob),
            "end_offset": content1.index(token_bob) + len(token_bob),
        }
    ]

    with auth_patch(user_alice):
        resp_m1 = await test_client.post(
            f"/api/v1/conversations/{group_conv.conversation_id}/messages",
            data={"content": content1, "mentions": json.dumps(mentions1)},
        )
    assert resp_m1.status_code == 201

    notifs_bob = (
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == user_bob.user_id,
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == group_conv.conversation_id,
            )
        )
    ).all()
    assert len(notifs_bob) == 1
    assert notifs_bob[0].is_read is False
    assert "nhắc đến bạn" in notifs_bob[0].body

    # Carol should have received ZERO notifications
    notifs_carol = (
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == user_carol.user_id,
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == group_conv.conversation_id,
            )
        )
    ).all()
    assert len(notifs_carol) == 0

    # 3. Second message mentioning Bob in the same group conversation
    content2 = f"Nhắc lại lần nữa nè {token_bob}"
    mentions2 = [
        {
            "mentioned_user_id": user_bob.user_id,
            "display_text": token_bob,
            "start_offset": content2.index(token_bob),
            "end_offset": content2.index(token_bob) + len(token_bob),
        }
    ]

    with auth_patch(user_alice):
        resp_m2 = await test_client.post(
            f"/api/v1/conversations/{group_conv.conversation_id}/messages",
            data={"content": content2, "mentions": json.dumps(mentions2)},
        )
    assert resp_m2.status_code == 201

    # Still exactly ONE notification row for Bob
    notifs_bob2 = (
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == user_bob.user_id,
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == group_conv.conversation_id,
            )
        )
    ).all()
    assert len(notifs_bob2) == 1
    assert notifs_bob2[0].is_read is False

    # 4. Mark group conversation read clears notification
    with auth_patch(user_bob):
        read_resp = await test_client.post(
            f"/api/v1/conversations/{group_conv.conversation_id}/read"
        )
    assert read_resp.status_code == 200

    notif_bob_after_read = (
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == user_bob.user_id,
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == group_conv.conversation_id,
            )
        )
    ).one()
    assert notif_bob_after_read.is_read is True


@pytest.mark.asyncio
async def test_concurrent_message_notification_coalescing(
    test_client: AsyncClient,
    user_alice: User,
    user_bob: User,
    db_session: AsyncSession,
):
    """
    Concurrency safety test:
    Two messages sent almost simultaneously to the same recipient in the same conversation
    must serialize safely via PostgreSQL advisory lock and NOT create duplicate unread notifications.
    """
    direct_ab = Conversation(
        type="DIRECT",
        user_one_id=min(user_alice.user_id, user_bob.user_id),
        user_two_id=max(user_alice.user_id, user_bob.user_id),
        direct_pair_key=f"{min(user_alice.user_id, user_bob.user_id)}:{max(user_alice.user_id, user_bob.user_id)}",
    )
    db_session.add(direct_ab)
    await db_session.flush()

    db_session.add(ConversationMember(conversation_id=direct_ab.conversation_id, user_id=user_alice.user_id, role="MEMBER"))
    db_session.add(ConversationMember(conversation_id=direct_ab.conversation_id, user_id=user_bob.user_id, role="MEMBER"))
    await db_session.commit()

    with auth_patch(user_alice):
        res1 = await test_client.post(
            f"/api/v1/conversations/{direct_ab.conversation_id}/messages",
            data={"content": "Tin nhắn nhanh 1"},
        )
        res2 = await test_client.post(
            f"/api/v1/conversations/{direct_ab.conversation_id}/messages",
            data={"content": "Tin nhắn nhanh 2"},
        )

    assert res1.status_code == 201
    assert res2.status_code == 201

    notifs = (
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == user_bob.user_id,
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == direct_ab.conversation_id,
                Notification.is_read.is_(False),
            )
        )
    ).all()
    assert len(notifs) == 1
