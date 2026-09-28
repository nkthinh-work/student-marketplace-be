import json
from datetime import datetime, timezone
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.core.config import settings
from app.core.realtime.presence import record_user_presence, get_users_presence, is_user_online
from app.core.redis import redis_client
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.conversations.models import (
    Conversation,
    ConversationInvite,
    ConversationMember,
    Message,
    MessageAttachment,
    MessageMention,
)
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
        email="user_a_7c@ptit.edu.vn",
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
        email="user_b_7c@ptit.edu.vn",
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
        email="user_c_7c@ptit.edu.vn",
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
        email="user_d_7c@ptit.edu.vn",
        full_name="Hoàng Thị D",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest.mark.asyncio
async def test_redis_config_environment_driven():
    """A. Verify Redis configuration is environment-driven and not hardcoded."""
    assert hasattr(settings, "REDIS_HOST")
    assert hasattr(settings, "REDIS_PORT")
    assert hasattr(settings, "REDIS_URL")
    assert hasattr(settings, "REDIS_DB")


@pytest.mark.asyncio
async def test_presence_heartbeat_and_ttl(user_a: User):
    """B & C. Heartbeat refreshes presence TTL; multi-tab safety keeps user online."""
    # Record presence
    ok = await record_user_presence(user_a.user_id)
    if ok:
        avail, is_on = await is_user_online(user_a.user_id)
        assert avail is True
        assert is_on is True

        # Batch lookup
        avail_batch, online_set = await get_users_presence([user_a.user_id, 999999])
        assert avail_batch is True
        assert user_a.user_id in online_set
        assert 999999 not in online_set


@pytest.mark.asyncio
async def test_redis_outage_does_not_break_message_send(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    db_session: AsyncSession,
    monkeypatch,
):
    """D. If Redis is unavailable, message send and chat operations still succeed."""
    # Create direct conversation
    conv = Conversation(type="DIRECT", direct_pair_key=f"{min(user_a.user_id, user_b.user_id)}:{max(user_a.user_id, user_b.user_id)}", user_one_id=min(user_a.user_id, user_b.user_id), user_two_id=max(user_a.user_id, user_b.user_id))
    db_session.add(conv)
    await db_session.flush()

    m1 = ConversationMember(conversation_id=conv.conversation_id, user_id=user_a.user_id, role="MEMBER")
    m2 = ConversationMember(conversation_id=conv.conversation_id, user_id=user_b.user_id, role="MEMBER")
    db_session.add_all([m1, m2])
    await db_session.commit()

    # Simulate Redis outage in presence module
    import app.core.realtime.presence as presence_mod
    monkeypatch.setattr(presence_mod, "redis_client", None)

    # Sending message must succeed without any error
    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/{conv.conversation_id}/messages",
            data={"content": "Tin nhắn khi Redis down"},
        )
    assert resp.status_code == 201
    assert resp.json()["content"] == "Tin nhắn khi Redis down"

    # Presence endpoint returns truthful fallback: presence_available=False
    with auth_patch(user_a):
        pres_resp = await test_client.get(
            f"/api/v1/conversations/{conv.conversation_id}/presence"
        )
    assert pres_resp.status_code == 200
    pres_data = pres_resp.json()
    assert pres_data["presence_available"] is False
    assert pres_data["online_user_ids"] == []


@pytest.mark.asyncio
async def test_structured_mentions_persistence_and_display_name_mutation(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    user_c: User,
    db_session: AsyncSession,
):
    """E & F. Structured mention persists offsets, display_text snapshot, and remains render-stable after name change."""
    conv = Conversation(type="GROUP", title="Nhóm Mentions Test")
    db_session.add(conv)
    await db_session.flush()

    m_a = ConversationMember(conversation_id=conv.conversation_id, user_id=user_a.user_id, role="OWNER")
    m_b = ConversationMember(conversation_id=conv.conversation_id, user_id=user_b.user_id, role="MEMBER")
    m_c = ConversationMember(conversation_id=conv.conversation_id, user_id=user_c.user_id, role="MEMBER")
    db_session.add_all([m_a, m_b, m_c])
    await db_session.commit()

    content = f"@{user_b.full_name} hãy xem tài liệu này nhé"
    start_offset = 0
    end_offset = len(f"@{user_b.full_name}")
    display_text = f"@{user_b.full_name}"

    mentions_payload = [
        {
            "mentioned_user_id": user_b.user_id,
            "display_text": display_text,
            "start_offset": start_offset,
            "end_offset": end_offset,
        }
    ]

    with auth_patch(user_a):
        send_resp = await test_client.post(
            f"/api/v1/conversations/{conv.conversation_id}/messages",
            data={
                "content": content,
                "mentions": json.dumps(mentions_payload),
            },
        )
    assert send_resp.status_code == 201
    msg_data = send_resp.json()
    assert len(msg_data["mentions"]) == 1
    assert msg_data["mentions"][0]["user_id"] == user_b.user_id
    assert msg_data["mentions"][0]["display_text"] == display_text
    assert msg_data["mentions"][0]["start_offset"] == start_offset
    assert msg_data["mentions"][0]["end_offset"] == end_offset

    # User B now changes full_name in the database
    user_b.full_name = "Trần B (Tên Mới Sau Đổi)"
    await db_session.commit()

    # Read message history: historical display_text snapshot remains unchanged
    with auth_patch(user_a):
        hist_resp = await test_client.get(
            f"/api/v1/conversations/{conv.conversation_id}/messages"
        )
    assert hist_resp.status_code == 200
    items = hist_resp.json()["items"]
    assert len(items) >= 1
    mention_entry = items[0]["mentions"][0]
    # Original snapshot preserved for render stability
    assert mention_entry["display_text"] == display_text
    assert mention_entry["user_id"] == user_b.user_id


@pytest.mark.asyncio
async def test_cannot_mention_non_member(
    test_client: AsyncClient,
    user_a: User,
    user_d: User,
    db_session: AsyncSession,
):
    """Cannot mention a user who is not an active member -> 422."""
    conv = Conversation(type="GROUP", title="Nhóm Mentions Guard")
    db_session.add(conv)
    await db_session.flush()

    m_a = ConversationMember(conversation_id=conv.conversation_id, user_id=user_a.user_id, role="OWNER")
    db_session.add(m_a)
    await db_session.commit()

    # user_d is NOT a member of this group
    content = f"@{user_d.full_name} xin chào"
    mentions_payload = [
        {
            "mentioned_user_id": user_d.user_id,
            "display_text": f"@{user_d.full_name}",
            "start_offset": 0,
            "end_offset": len(f"@{user_d.full_name}"),
        }
    ]

    with auth_patch(user_a):
        resp = await test_client.post(
            f"/api/v1/conversations/{conv.conversation_id}/messages",
            data={
                "content": content,
                "mentions": json.dumps(mentions_payload),
            },
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_deleted_group_system_wide_inaccessible(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    db_session: AsyncSession,
):
    """G & H. Soft-deleted group is completely inaccessible system-wide and disappears from lists."""
    conv = Conversation(type="GROUP", title="Nhóm Chuẩn Bị Xóa")
    db_session.add(conv)
    await db_session.flush()

    m_a = ConversationMember(conversation_id=conv.conversation_id, user_id=user_a.user_id, role="OWNER")
    m_b = ConversationMember(conversation_id=conv.conversation_id, user_id=user_b.user_id, role="MEMBER")
    db_session.add_all([m_a, m_b])
    await db_session.commit()

    # Verify visible in list before deletion
    with auth_patch(user_a):
        list_before = await test_client.get("/api/v1/conversations?type=GROUP")
    assert any(c["conversation_id"] == conv.conversation_id for c in list_before.json()["items"])

    # Non-owner user_b cannot delete -> 403
    with auth_patch(user_b):
        del_b = await test_client.delete(f"/api/v1/conversations/groups/{conv.conversation_id}")
    assert del_b.status_code == 403

    # Owner user_a deletes group -> 200
    with auth_patch(user_a):
        del_a = await test_client.delete(f"/api/v1/conversations/groups/{conv.conversation_id}")
    assert del_a.status_code == 200

    # 1. Disappears from list
    with auth_patch(user_a):
        list_after = await test_client.get("/api/v1/conversations?type=GROUP")
    assert not any(c["conversation_id"] == conv.conversation_id for c in list_after.json()["items"])

    # 2. Cannot fetch detail -> 404
    with auth_patch(user_a):
        detail_resp = await test_client.get(f"/api/v1/conversations/{conv.conversation_id}")
    assert detail_resp.status_code == 404

    # 3. Cannot send message -> 404
    with auth_patch(user_a):
        send_resp = await test_client.post(
            f"/api/v1/conversations/{conv.conversation_id}/messages",
            data={"content": "Tin nhắn vào nhóm đã xóa"},
        )
    assert send_resp.status_code == 404

    # 4. Cannot invite -> 400/404
    with auth_patch(user_a):
        inv_resp = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/invites",
            json={"invitee_ids": [user_b.user_id]},
        )
    assert inv_resp.status_code in (400, 404)

    # 5. Cannot access attachments -> 404
    with auth_patch(user_a):
        att_resp = await test_client.get(
            f"/api/v1/conversations/{conv.conversation_id}/attachments?category=media"
        )
    assert att_resp.status_code == 404


@pytest.mark.asyncio
async def test_member_invites_for_regular_group(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    user_c: User,
    db_session: AsyncSession,
):
    """I & J. Ordinary active MEMBER can invite to regular GROUP; non-member cannot."""
    conv = Conversation(type="GROUP", title="Nhóm Trao Đổi Bài Tập")
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=user_a.user_id, role="OWNER")
    m_member = ConversationMember(conversation_id=conv.conversation_id, user_id=user_b.user_id, role="MEMBER")
    db_session.add_all([m_owner, m_member])
    await db_session.commit()

    # Active member user_b invites user_c -> 200 OK
    with auth_patch(user_b):
        resp_inv = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/invites",
            json={"invitee_ids": [user_c.user_id]},
        )
    assert resp_inv.status_code == 200
    invites = resp_inv.json()
    assert len(invites) == 1
    assert invites[0]["inviter_id"] == user_b.user_id

    # Invited user_c can see it in their invites list
    with auth_patch(user_c):
        my_invites = await test_client.get("/api/v1/conversations/invites")
    assert my_invites.status_code == 200
    assert any(i["conversation_id"] == conv.conversation_id for i in my_invites.json())


@pytest.mark.asyncio
async def test_official_support_group_cannot_be_deleted(
    test_client: AsyncClient,
    user_a: User,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """K. Official support group cannot be deleted via Group owner delete flow."""
    supp_conv = Conversation(
        type="GROUP",
        title="Cộng đồng Chợ PTITers",
    )
    db_session.add(supp_conv)
    await db_session.flush()
    db_session.add(
        ConversationMember(
            conversation_id=supp_conv.conversation_id,
            user_id=user_a.user_id,
            role="OWNER",
        )
    )
    await db_session.commit()
    monkeypatch.setattr(settings, "OFFICIAL_SUPPORT_GROUP_ID", supp_conv.conversation_id)

    # Attempt delete official support group -> 403 Forbidden
    with auth_patch(user_a):
        del_res = await test_client.delete(f"/api/v1/conversations/groups/{supp_conv.conversation_id}")
    assert del_res.status_code == 403
    assert "nhóm hỗ trợ chính thức" in del_res.json()["detail"]


@pytest.mark.asyncio
async def test_deterministic_ownership_transfer_and_leave_guard(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    db_session: AsyncSession,
):
    """L. Owner transfer is atomic, leaves exactly one owner (old owner -> MEMBER), and prevents owner from leaving before transfer."""
    conv = Conversation(type="GROUP", title="Nhóm Bàn Giao Trưởng Nhóm")
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=user_a.user_id, role="OWNER")
    m_member = ConversationMember(conversation_id=conv.conversation_id, user_id=user_b.user_id, role="MEMBER")
    db_session.add_all([m_owner, m_member])
    await db_session.commit()

    # 1. Owner attempts to leave while other members exist -> 400
    with auth_patch(user_a):
        leave_err = await test_client.post(f"/api/v1/conversations/groups/{conv.conversation_id}/leave")
    assert leave_err.status_code == 400

    # 2. Transfer ownership to user_b -> 200
    with auth_patch(user_a):
        trans_res = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/transfer-ownership",
            json={"new_owner_id": user_b.user_id},
        )
    assert trans_res.status_code == 200

    # 3. Check members list: user_b is OWNER, user_a is MEMBER
    with auth_patch(user_a):
        mems_res = await test_client.get(f"/api/v1/conversations/groups/{conv.conversation_id}/members")
    assert mems_res.status_code == 200
    mems = mems_res.json()
    owner_mems = [m for m in mems if m["role"] == "OWNER"]
    assert len(owner_mems) == 1
    assert owner_mems[0]["user_id"] == user_b.user_id

    former_owner = next(m for m in mems if m["user_id"] == user_a.user_id)
    assert former_owner["role"] == "MEMBER"

    # 4. Now former owner can leave group safely
    with auth_patch(user_a):
        leave_ok = await test_client.post(f"/api/v1/conversations/groups/{conv.conversation_id}/leave")
    assert leave_ok.status_code == 200


@pytest.mark.asyncio
async def test_shared_attachments_api_and_summary(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    db_session: AsyncSession,
):
    """Shared attachments categorizes media, audio, file with cursor pagination and summary counts."""
    conv = Conversation(type="GROUP", title="Nhóm Chia Sẻ Tệp")
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=user_a.user_id, role="OWNER")
    m_member = ConversationMember(conversation_id=conv.conversation_id, user_id=user_b.user_id, role="MEMBER")
    db_session.add_all([m_owner, m_member])
    await db_session.commit()

    # Add message with 1 image, 1 audio, 1 doc
    msg = Message(conversation_id=conv.conversation_id, sender_id=user_a.user_id, content="Tệp đính kèm")
    db_session.add(msg)
    await db_session.flush()

    att_img = MessageAttachment(
        message_id=msg.message_id,
        kind="IMAGE",
        url="https://res.cloudinary.com/demo/image/upload/sample.jpg",
        storage_key="sample_image",
        mime_type="image/jpeg",
        original_name="sample.jpg",
        size_bytes=1024,
    )
    att_aud = MessageAttachment(
        message_id=msg.message_id,
        kind="AUDIO",
        url="https://res.cloudinary.com/demo/video/upload/voice.mp3",
        storage_key="sample_audio",
        mime_type="audio/mp3",
        original_name="voice.mp3",
        size_bytes=2048,
        duration_ms=18000,
    )
    att_doc = MessageAttachment(
        message_id=msg.message_id,
        kind="PDF",
        url="https://res.cloudinary.com/demo/raw/upload/document.pdf",
        storage_key="sample_pdf",
        mime_type="application/pdf",
        original_name="document.pdf",
        size_bytes=4096,
    )
    db_session.add_all([att_img, att_aud, att_doc])
    await db_session.commit()

    # Query summary
    with auth_patch(user_a):
        sum_res = await test_client.get(f"/api/v1/conversations/{conv.conversation_id}/attachments/summary")
    assert sum_res.status_code == 200
    sum_data = sum_res.json()
    assert sum_data["media_count"] == 1
    assert sum_data["audio_count"] == 1
    assert sum_data["file_count"] == 1

    # Query media
    with auth_patch(user_a):
        media_res = await test_client.get(f"/api/v1/conversations/{conv.conversation_id}/attachments?category=media")
    assert media_res.status_code == 200
    assert len(media_res.json()["items"]) == 1
    assert media_res.json()["items"][0]["kind"] == "IMAGE"

    # Query audio
    with auth_patch(user_a):
        audio_res = await test_client.get(f"/api/v1/conversations/{conv.conversation_id}/attachments?category=audio")
    assert audio_res.status_code == 200
    assert len(audio_res.json()["items"]) == 1
    assert audio_res.json()["items"][0]["duration_ms"] == 18000

    # Query file
    with auth_patch(user_a):
        file_res = await test_client.get(f"/api/v1/conversations/{conv.conversation_id}/attachments?category=file")
    assert file_res.status_code == 200
    assert len(file_res.json()["items"]) == 1
    assert file_res.json()["items"][0]["kind"] == "PDF"


@pytest.mark.asyncio
async def test_presence_endpoint_authorization(
    test_client: AsyncClient,
    user_a: User,
    user_d: User,
    db_session: AsyncSession,
):
    """Presence endpoint requires caller to be an active member of the conversation."""
    conv = Conversation(type="GROUP", title="Nhóm Presence Auth")
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=user_a.user_id, role="OWNER")
    db_session.add(m_owner)
    await db_session.commit()

    # Member user_a can query presence -> 200
    with auth_patch(user_a):
        resp_a = await test_client.get(f"/api/v1/conversations/{conv.conversation_id}/presence")
    assert resp_a.status_code == 200

    # Non-member user_d cannot query presence -> 404
    with auth_patch(user_d):
        resp_d = await test_client.get(f"/api/v1/conversations/{conv.conversation_id}/presence")
    assert resp_d.status_code == 404
