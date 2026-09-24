import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.conversations.models import Conversation, ConversationMember, Message, MessageReaction
from app.modules.conversations.schemas import ReactionKey
from app.modules.notifications.models import Notification
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
        email="react_user_a@ptit.edu.vn",
        full_name="Nguyễn Văn A",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    u = User(
        email="react_user_b@ptit.edu.vn",
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
        email="react_user_c@ptit.edu.vn",
        full_name="Lê Văn C",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def direct_conv(db_session: AsyncSession, user_a: User, user_b: User) -> Conversation:
    u1 = min(user_a.user_id, user_b.user_id)
    u2 = max(user_a.user_id, user_b.user_id)
    conv = Conversation(
        type="DIRECT",
        direct_pair_key=f"{u1}:{u2}",
        user_one_id=u1,
        user_two_id=u2,
    )
    db_session.add(conv)
    await db_session.commit()
    return conv


@pytest_asyncio.fixture
async def group_conv(db_session: AsyncSession, user_a: User, user_b: User) -> Conversation:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    conv = Conversation(
        type="GROUP",
        title="Nhóm Học Tập PTIT",
    )
    db_session.add(conv)
    await db_session.flush()

    m_a = ConversationMember(
        conversation_id=conv.conversation_id,
        user_id=user_a.user_id,
        role="OWNER",
        joined_at=now - timedelta(days=2),
    )
    m_b = ConversationMember(
        conversation_id=conv.conversation_id,
        user_id=user_b.user_id,
        role="MEMBER",
        joined_at=now - timedelta(days=1),
    )
    db_session.add_all([m_a, m_b])
    await db_session.commit()
    return conv


@pytest_asyncio.fixture
async def community_conv(db_session: AsyncSession) -> Conversation:
    conv = await db_session.scalar(
        select(Conversation).where(Conversation.type == "COMMUNITY")
    )
    if not conv:
        conv = Conversation(
            type="COMMUNITY",
            title="Cộng đồng Chợ PTITers",
        )
        db_session.add(conv)
        await db_session.commit()
    return conv


@pytest_asyncio.fixture
async def direct_msg(db_session: AsyncSession, direct_conv: Conversation, user_a: User) -> Message:
    msg = Message(
        conversation_id=direct_conv.conversation_id,
        sender_id=user_a.user_id,
        type="TEXT",
        content="Xin chào bạn!",
        sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db_session.add(msg)
    await db_session.commit()
    return msg


@pytest_asyncio.fixture
async def group_msg(db_session: AsyncSession, group_conv: Conversation, user_a: User) -> Message:
    msg = Message(
        conversation_id=group_conv.conversation_id,
        sender_id=user_a.user_id,
        type="TEXT",
        content="Chào cả nhóm!",
        sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db_session.add(msg)
    await db_session.commit()
    return msg


# =====================================================================
# 1. DIRECT CONVERSATION TESTS (Instruction 1 & 20)
# =====================================================================

@pytest.mark.asyncio
async def test_direct_reaction_both_participants_succeed(
    test_client: AsyncClient,
    direct_conv: Conversation,
    direct_msg: Message,
    user_a: User,
    user_b: User,
):
    """Both participants in Direct chat can react successfully."""
    # User A reacts THICH
    with auth_patch(user_a):
        res_a = await test_client.put(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{direct_msg.message_id}/reaction",
            json={"reaction_key": "THICH"},
        )
        assert res_a.status_code == 200
        data_a = res_a.json()
        assert data_a["message_id"] == direct_msg.message_id
        assert data_a["my_reaction"] == "THICH"
        assert len(data_a["reactions"]) == 1
        assert data_a["reactions"][0]["reaction_key"] == "THICH"
        assert data_a["reactions"][0]["count"] == 1

    # User B reacts THICH
    with auth_patch(user_b):
        res_b = await test_client.put(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{direct_msg.message_id}/reaction",
            json={"reaction_key": "THICH"},
        )
        assert res_b.status_code == 200
        data_b = res_b.json()
        assert data_b["my_reaction"] == "THICH"
        assert len(data_b["reactions"]) == 1
        assert data_b["reactions"][0]["reaction_key"] == "THICH"
        assert data_b["reactions"][0]["count"] == 2


@pytest.mark.asyncio
async def test_direct_reaction_works_without_conversation_member_row(
    test_client: AsyncClient,
    direct_conv: Conversation,
    direct_msg: Message,
    user_a: User,
    db_session: AsyncSession,
):
    """Direct conversation has NO requirement for ConversationMember rows."""
    # Ensure there are zero ConversationMember rows for this conversation
    await db_session.execute(
        text("DELETE FROM conversation_members WHERE conversation_id = :cid"),
        {"cid": direct_conv.conversation_id},
    )
    await db_session.commit()

    with auth_patch(user_a):
        res = await test_client.put(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{direct_msg.message_id}/reaction",
            json={"reaction_key": "CAM_ON"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["my_reaction"] == "CAM_ON"
        assert data["reactions"][0]["reaction_key"] == "CAM_ON"
        assert data["reactions"][0]["count"] == 1


@pytest.mark.asyncio
async def test_direct_reaction_non_participant_forbidden_404(
    test_client: AsyncClient,
    direct_conv: Conversation,
    direct_msg: Message,
    user_c: User,
):
    """Non-participant receives non-leaking 404."""
    with auth_patch(user_c):
        res = await test_client.put(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{direct_msg.message_id}/reaction",
            json={"reaction_key": "THICH"},
        )
        assert res.status_code == 404


# =====================================================================
# 2. GROUP CONVERSATION TESTS (Instruction 1)
# =====================================================================

@pytest.mark.asyncio
async def test_group_reaction_active_member_succeeds(
    test_client: AsyncClient,
    group_conv: Conversation,
    group_msg: Message,
    user_b: User,
):
    """Active group member can react."""
    with auth_patch(user_b):
        res = await test_client.put(
            f"/api/v1/conversations/{group_conv.conversation_id}/messages/{group_msg.message_id}/reaction",
            json={"reaction_key": "HAHA"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["my_reaction"] == "HAHA"
        assert data["reactions"][0]["reaction_key"] == "HAHA"
        assert data["reactions"][0]["count"] == 1


@pytest.mark.asyncio
async def test_group_reaction_left_member_rejected_404(
    test_client: AsyncClient,
    group_conv: Conversation,
    group_msg: Message,
    user_b: User,
    db_session: AsyncSession,
):
    """Member who has left the group receives non-leaking 404."""
    await db_session.execute(
        text("UPDATE conversation_members SET left_at = :now WHERE conversation_id = :cid AND user_id = :uid"),
        {"now": datetime.now(timezone.utc).replace(tzinfo=None), "cid": group_conv.conversation_id, "uid": user_b.user_id},
    )
    await db_session.commit()

    with auth_patch(user_b):
        res = await test_client.put(
            f"/api/v1/conversations/{group_conv.conversation_id}/messages/{group_msg.message_id}/reaction",
            json={"reaction_key": "THICH"},
        )
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_group_reaction_pre_join_message_rejected_404(
    test_client: AsyncClient,
    group_conv: Conversation,
    user_a: User,
    user_c: User,
    db_session: AsyncSession,
):
    """User cannot react to messages sent before their joined_at timestamp."""
    old_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
    old_msg = Message(
        conversation_id=group_conv.conversation_id,
        sender_id=user_a.user_id,
        type="TEXT",
        content="Tin nhắn thời kỳ đầu",
        sent_at=old_time,
    )
    db_session.add(old_msg)

    # User C joins today
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    m_c = ConversationMember(
        conversation_id=group_conv.conversation_id,
        user_id=user_c.user_id,
        role="MEMBER",
        joined_at=now,
    )
    db_session.add(m_c)
    await db_session.commit()

    with auth_patch(user_c):
        res = await test_client.put(
            f"/api/v1/conversations/{group_conv.conversation_id}/messages/{old_msg.message_id}/reaction",
            json={"reaction_key": "WOW"},
        )
        assert res.status_code == 404


# =====================================================================
# 3. COMMUNITY EXCLUSION TEST (Instruction 15)
# =====================================================================

@pytest.mark.asyncio
async def test_community_conversation_rejected_400(
    test_client: AsyncClient,
    community_conv: Conversation,
    user_a: User,
    db_session: AsyncSession,
):
    """Community conversations reject reactions with 400 Bad Request."""
    msg = Message(
        conversation_id=community_conv.conversation_id,
        sender_id=user_a.user_id,
        type="TEXT",
        content="Tin cộng đồng",
        sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db_session.add(msg)
    await db_session.commit()

    with auth_patch(user_a):
        res = await test_client.put(
            f"/api/v1/conversations/{community_conv.conversation_id}/messages/{msg.message_id}/reaction",
            json={"reaction_key": "THICH"},
        )
        assert res.status_code == 400


# =====================================================================
# 4. MESSAGE ACCESS & VALIDATION TESTS (Instruction 2 & 7)
# =====================================================================

@pytest.mark.asyncio
async def test_cross_conversation_message_rejected_404(
    test_client: AsyncClient,
    direct_conv: Conversation,
    group_msg: Message,
    user_a: User,
):
    """Message from Group accessed via Direct URL returns 404 without leaking."""
    with auth_patch(user_a):
        res = await test_client.put(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{group_msg.message_id}/reaction",
            json={"reaction_key": "THICH"},
        )
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_system_message_reaction_rejected_400(
    test_client: AsyncClient,
    group_conv: Conversation,
    user_a: User,
    db_session: AsyncSession,
):
    """SYSTEM messages cannot be reacted to -> 400 Bad Request."""
    sys_msg = Message(
        conversation_id=group_conv.conversation_id,
        sender_id=user_a.user_id,
        type="SYSTEM",
        content="User A đã thêm User B vào nhóm",
        sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db_session.add(sys_msg)
    await db_session.commit()

    with auth_patch(user_a):
        res = await test_client.put(
            f"/api/v1/conversations/{group_conv.conversation_id}/messages/{sys_msg.message_id}/reaction",
            json={"reaction_key": "THICH"},
        )
        assert res.status_code == 400


@pytest.mark.asyncio
async def test_deleted_message_reaction_rejected_404(
    test_client: AsyncClient,
    direct_conv: Conversation,
    direct_msg: Message,
    user_a: User,
    db_session: AsyncSession,
):
    """Deleted messages cannot be reacted to -> 404."""
    direct_msg.is_deleted = True
    await db_session.commit()

    with auth_patch(user_a):
        res = await test_client.put(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{direct_msg.message_id}/reaction",
            json={"reaction_key": "THICH"},
        )
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_invalid_reaction_key_rejected_422(
    test_client: AsyncClient,
    direct_conv: Conversation,
    direct_msg: Message,
    user_a: User,
):
    """Invalid reaction key rejected by Pydantic Enum validation with 422."""
    with auth_patch(user_a):
        res = await test_client.put(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{direct_msg.message_id}/reaction",
            json={"reaction_key": "HEART_EMOJI"},
        )
        assert res.status_code == 422


@pytest.mark.asyncio
async def test_all_12_canonical_reaction_keys_accepted(
    test_client: AsyncClient,
    direct_conv: Conversation,
    direct_msg: Message,
    user_a: User,
):
    """All 12 signature reaction keys are accepted."""
    keys = [
        "THICH", "HAHA", "WOW", "CAM_ON", "CHOT_DEAL", "UY_TIN",
        "DANG_TOI", "DOI_CHUT", "QUAN_TAM", "HET_TIEN", "HOC_BAI", "KHA_NGHI"
    ]
    with auth_patch(user_a):
        for k in keys:
            res = await test_client.put(
                f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{direct_msg.message_id}/reaction",
                json={"reaction_key": k},
            )
            assert res.status_code == 200
            assert res.json()["my_reaction"] == k


# =====================================================================
# 5. SWITCH & REMOVE REACTION TESTS (Instruction 11 & Desired State)
# =====================================================================

@pytest.mark.asyncio
async def test_switch_reaction_updates_counts(
    test_client: AsyncClient,
    direct_conv: Conversation,
    direct_msg: Message,
    user_a: User,
    user_b: User,
):
    """Switching a reaction updates counts and my_reaction without creating duplicates."""
    with auth_patch(user_a):
        # A reacts THICH
        await test_client.put(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{direct_msg.message_id}/reaction",
            json={"reaction_key": "THICH"},
        )
    with auth_patch(user_b):
        # B reacts THICH
        await test_client.put(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{direct_msg.message_id}/reaction",
            json={"reaction_key": "THICH"},
        )

    # Now User A switches from THICH to HAHA
    with auth_patch(user_a):
        res = await test_client.put(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{direct_msg.message_id}/reaction",
            json={"reaction_key": "HAHA"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["my_reaction"] == "HAHA"

        counts = {r["reaction_key"]: r["count"] for r in data["reactions"]}
        assert counts.get("THICH") == 1  # only User B left
        assert counts.get("HAHA") == 1   # switched by User A


@pytest.mark.asyncio
async def test_remove_reaction_returns_200(
    test_client: AsyncClient,
    direct_conv: Conversation,
    direct_msg: Message,
    user_a: User,
):
    """Removing reaction returns 200 OK with my_reaction=None and updated list."""
    with auth_patch(user_a):
        # First add reaction
        await test_client.put(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{direct_msg.message_id}/reaction",
            json={"reaction_key": "CHOT_DEAL"},
        )

        # Then delete reaction
        res = await test_client.delete(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{direct_msg.message_id}/reaction",
        )
        assert res.status_code == 200
        data = res.json()
        assert data["message_id"] == direct_msg.message_id
        assert data["my_reaction"] is None
        assert len(data["reactions"]) == 0

        # Deleting again is idempotent, also returns 200
        res2 = await test_client.delete(
            f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{direct_msg.message_id}/reaction",
        )
        assert res2.status_code == 200
        assert res2.json()["my_reaction"] is None


# =====================================================================
# 6. ZERO SIDE EFFECTS TEST (Instruction 21)
# =====================================================================

@pytest.mark.asyncio
async def test_reactions_have_zero_side_effects(
    test_client: AsyncClient,
    direct_conv: Conversation,
    direct_msg: Message,
    user_a: User,
    db_session: AsyncSession,
):
    """Reactions must have NO side effects on messages, notifications, or conversation metadata."""
    cid = direct_conv.conversation_id
    mid = direct_msg.message_id
    # Count initial states
    msg_count_before = (await db_session.execute(select(func.count(Message.message_id)))).scalar()
    notif_count_before = (await db_session.execute(select(func.count(Notification.notification_id)))).scalar()
    conv_before = await db_session.scalar(select(Conversation).where(Conversation.conversation_id == cid))
    last_msg_at_before = conv_before.last_message_at

    with auth_patch(user_a):
        # 1. Set reaction
        await test_client.put(
            f"/api/v1/conversations/{cid}/messages/{mid}/reaction",
            json={"reaction_key": "UY_TIN"},
        )
        # 2. Switch reaction
        await test_client.put(
            f"/api/v1/conversations/{cid}/messages/{mid}/reaction",
            json={"reaction_key": "DANG_TOI"},
        )
        # 3. Remove reaction
        await test_client.delete(
            f"/api/v1/conversations/{cid}/messages/{mid}/reaction",
        )

    msg_count_after = (await db_session.execute(select(func.count(Message.message_id)))).scalar()
    notif_count_after = (await db_session.execute(select(func.count(Notification.notification_id)))).scalar()
    conv_after = await db_session.scalar(select(Conversation).where(Conversation.conversation_id == cid))

    assert msg_count_after == msg_count_before
    assert notif_count_after == notif_count_before
    assert conv_after.last_message_at == last_msg_at_before


# =====================================================================
# 7. MESSAGE HISTORY BATCHING & DTO DEFAULTS (Instruction 12 & 13)
# =====================================================================

@pytest.mark.asyncio
async def test_get_messages_batching_and_new_message_defaults(
    test_client: AsyncClient,
    group_conv: Conversation,
    group_msg: Message,
    user_a: User,
    user_b: User,
):
    """GET messages returns reactions summary and defaults for new messages."""
    # A reacts to group_msg
    with auth_patch(user_a):
        await test_client.put(
            f"/api/v1/conversations/{group_conv.conversation_id}/messages/{group_msg.message_id}/reaction",
            json={"reaction_key": "HOC_BAI"},
        )

    # Post a brand new message
    with auth_patch(user_b):
        post_res = await test_client.post(
            f"/api/v1/conversations/{group_conv.conversation_id}/messages",
            data={"content": "Tin nhắn mới không có reaction"},
        )
        assert post_res.status_code == 201
        new_msg_data = post_res.json()
        assert new_msg_data["reactions"] == []
        assert new_msg_data["my_reaction"] is None

    # Fetch messages list as user_a
    with auth_patch(user_a):
        list_res = await test_client.get(
            f"/api/v1/conversations/{group_conv.conversation_id}/messages"
        )
        assert list_res.status_code == 200
        items = list_res.json()["items"]
        assert len(items) >= 2

        # group_msg should have HOC_BAI reaction with my_reaction="HOC_BAI"
        reacted_item = next(m for m in items if m["message_id"] == group_msg.message_id)
        assert len(reacted_item["reactions"]) == 1
        assert reacted_item["reactions"][0]["reaction_key"] == "HOC_BAI"
        assert reacted_item["reactions"][0]["count"] == 1
        assert reacted_item["my_reaction"] == "HOC_BAI"

        # brand new msg should have empty reactions and my_reaction=None
        unreacted_item = next(m for m in items if m["message_id"] == new_msg_data["message_id"])
        assert unreacted_item["reactions"] == []
        assert unreacted_item["my_reaction"] is None


# =====================================================================
# 8. REALTIME FANOUT EVENT (Instruction 5 & 14)
# =====================================================================

@pytest.mark.asyncio
async def test_realtime_event_fanout_emitted(
    test_client: AsyncClient,
    direct_conv: Conversation,
    direct_msg: Message,
    user_a: User,
    user_b: User,
):
    """Reaction mutation emits MESSAGE_REACTIONS_UPDATED to all conversation participants."""
    with patch("app.modules.conversations.service.publish_user_event", new_callable=AsyncMock) as mock_ws:
        with auth_patch(user_a):
            res = await test_client.put(
                f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{direct_msg.message_id}/reaction",
                json={"reaction_key": "KHA_NGHI"},
            )
            assert res.status_code == 200

            # Verify fanout called for both participants
            called_uids = [call.args[0] for call in mock_ws.call_args_list]
            assert user_a.user_id in called_uids
            assert user_b.user_id in called_uids

            event_payload = mock_ws.call_args_list[0].args[1]
            assert event_payload["type"] == "MESSAGE_REACTIONS_UPDATED"
            assert event_payload["conversation_id"] == direct_conv.conversation_id
            assert event_payload["message_id"] == direct_msg.message_id
            assert event_payload["actor_user_id"] == user_a.user_id
            assert event_payload["actor_reaction"] == "KHA_NGHI"
            assert event_payload["reactions"][0]["reaction_key"] == "KHA_NGHI"
            assert event_payload["reactions"][0]["count"] == 1

        # Delete reaction
        mock_ws.reset_mock()
        with auth_patch(user_a):
            res = await test_client.delete(
                f"/api/v1/conversations/{direct_conv.conversation_id}/messages/{direct_msg.message_id}/reaction",
            )
            assert res.status_code == 200
            del_event = mock_ws.call_args_list[0].args[1]
            assert del_event["type"] == "MESSAGE_REACTIONS_UPDATED"
            assert del_event["actor_reaction"] is None
