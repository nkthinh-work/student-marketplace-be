from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.conversations.models import Conversation, ConversationMember, Message
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
async def owner_user(db_session: AsyncSession) -> User:
    u = User(
        email="nick_owner@ptit.edu.vn",
        full_name="Nguyễn Văn Trưởng Nhóm",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    u = User(
        email="nick_admin@ptit.edu.vn",
        full_name="Trần Thị Phó Nhóm",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def member_user_a(db_session: AsyncSession) -> User:
    u = User(
        email="nick_member_a@ptit.edu.vn",
        full_name="Nguyễn Khắc Thịnh",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def member_user_b(db_session: AsyncSession) -> User:
    u = User(
        email="nick_member_b@ptit.edu.vn",
        full_name="Nguyễn Khắc Thịnh",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def outsider_user(db_session: AsyncSession) -> User:
    u = User(
        email="nick_outsider@ptit.edu.vn",
        full_name="Người Ngoài Nhóm",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def group_conv(
    db_session: AsyncSession,
    owner_user: User,
    admin_user: User,
    member_user_a: User,
    member_user_b: User,
) -> Conversation:
    conv = Conversation(
        type="GROUP",
        title="Nhóm D24CT01",
        description="Nhóm trao đổi bài tập",
    )
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(
        conversation_id=conv.conversation_id,
        user_id=owner_user.user_id,
        role="OWNER",
    )
    m_admin = ConversationMember(
        conversation_id=conv.conversation_id,
        user_id=admin_user.user_id,
        role="ADMIN",
    )
    m_a = ConversationMember(
        conversation_id=conv.conversation_id,
        user_id=member_user_a.user_id,
        role="MEMBER",
    )
    m_b = ConversationMember(
        conversation_id=conv.conversation_id,
        user_id=member_user_b.user_id,
        role="MEMBER",
    )
    db_session.add_all([m_owner, m_admin, m_a, m_b])
    await db_session.commit()
    return conv


@pytest_asyncio.fixture
async def direct_conv(
    db_session: AsyncSession,
    owner_user: User,
    member_user_a: User,
) -> Conversation:
    conv = Conversation(
        type="DIRECT",
        user_one_id=min(owner_user.user_id, member_user_a.user_id),
        user_two_id=max(owner_user.user_id, member_user_a.user_id),
    )
    db_session.add(conv)
    await db_session.flush()

    m1 = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="MEMBER")
    m2 = ConversationMember(conversation_id=conv.conversation_id, user_id=member_user_a.user_id, role="MEMBER")
    db_session.add_all([m1, m2])
    await db_session.commit()
    return conv


@pytest.mark.asyncio
async def test_active_member_sets_own_nickname(
    test_client: AsyncClient,
    group_conv: Conversation,
    member_user_a: User,
    db_session: AsyncSession,
):
    """Active group member sets own nickname successfully."""
    with auth_patch(member_user_a):
        resp = await test_client.patch(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
            json={"nickname": "Mít"},
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["user_id"] == member_user_a.user_id
    assert data["nickname"] == "Mít"
    assert data["full_name"] == member_user_a.full_name

    # Verify persisted in database
    mem = await db_session.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == group_conv.conversation_id,
            ConversationMember.user_id == member_user_a.user_id,
        )
    )
    assert mem is not None
    assert mem.nickname == "Mít"


@pytest.mark.asyncio
async def test_nickname_appears_in_group_members_list(
    test_client: AsyncClient,
    group_conv: Conversation,
    member_user_a: User,
    db_session: AsyncSession,
):
    """Nickname is exposed in group member response DTO."""
    mem = await db_session.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == group_conv.conversation_id,
            ConversationMember.user_id == member_user_a.user_id,
        )
    )
    mem.nickname = "Mít"
    await db_session.commit()

    with auth_patch(member_user_a):
        resp = await test_client.get(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/members"
        )
    assert resp.status_code == 200
    members = resp.json()
    target = next((m for m in members if m["user_id"] == member_user_a.user_id), None)
    assert target is not None
    assert target["nickname"] == "Mít"
    assert target["full_name"] == member_user_a.full_name


@pytest.mark.asyncio
async def test_clear_nickname_with_null(
    test_client: AsyncClient,
    group_conv: Conversation,
    member_user_a: User,
    db_session: AsyncSession,
):
    """User clears nickname by passing null -> database column becomes NULL."""
    mem = await db_session.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == group_conv.conversation_id,
            ConversationMember.user_id == member_user_a.user_id,
        )
    )
    mem.nickname = "Mít"
    await db_session.commit()

    with auth_patch(member_user_a):
        resp = await test_client.patch(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
            json={"nickname": None},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["nickname"] is None

    await db_session.refresh(mem)
    assert mem.nickname is None


@pytest.mark.asyncio
async def test_clear_nickname_with_whitespace(
    test_client: AsyncClient,
    group_conv: Conversation,
    member_user_a: User,
    db_session: AsyncSession,
):
    """Whitespace-only input normalizes to NULL."""
    mem = await db_session.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == group_conv.conversation_id,
            ConversationMember.user_id == member_user_a.user_id,
        )
    )
    mem.nickname = "Mít"
    await db_session.commit()

    with auth_patch(member_user_a):
        resp = await test_client.patch(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
            json={"nickname": "   "},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["nickname"] is None

    await db_session.refresh(mem)
    assert mem.nickname is None


@pytest.mark.asyncio
async def test_nickname_max_length_enforced(
    test_client: AsyncClient,
    group_conv: Conversation,
    member_user_a: User,
):
    """Nickname exceeding 40 characters is rejected with 400 Bad Request."""
    too_long = "a" * 41
    with auth_patch(member_user_a):
        resp = await test_client.patch(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
            json={"nickname": too_long},
        )
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_nickname_control_characters_rejected(
    test_client: AsyncClient,
    group_conv: Conversation,
    member_user_a: User,
):
    """Control characters, newlines, and tabs are rejected with 400 Bad Request."""
    for invalid in ["Mít\nAdmin", "Mít\rThịnh", "Mít\tABC", "Mít\x00Hacker"]:
        with auth_patch(member_user_a):
            resp = await test_client.patch(
                f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
                json={"nickname": invalid},
            )
        assert resp.status_code == 400, f"Expected 400 for {invalid!r}, got {resp.status_code}"


@pytest.mark.asyncio
async def test_nickname_supports_vietnamese_and_emoji(
    test_client: AsyncClient,
    group_conv: Conversation,
    member_user_a: User,
    db_session: AsyncSession,
):
    """Vietnamese diacritics and emojis are valid."""
    for valid in ["Thịnh béo", "Cá Mập", "Đại ca 😎"]:
        with auth_patch(member_user_a):
            resp = await test_client.patch(
                f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
                json={"nickname": valid},
            )
        assert resp.status_code == 200
        assert resp.json()["nickname"] == valid


@pytest.mark.asyncio
async def test_owner_cannot_edit_member_nickname(
    test_client: AsyncClient,
    group_conv: Conversation,
    owner_user: User,
    member_user_a: User,
    db_session: AsyncSession,
):
    """OWNER calling /me/nickname updates OWNER's nickname only, member's nickname is untouched."""
    # Member A sets nickname "Mít"
    mem_a = await db_session.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == group_conv.conversation_id,
            ConversationMember.user_id == member_user_a.user_id,
        )
    )
    mem_a.nickname = "Mít"
    await db_session.commit()

    # Owner calls /me/nickname with "Trưởng Nhóm Quyền Lực"
    with auth_patch(owner_user):
        resp = await test_client.patch(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
            json={"nickname": "Trưởng Nhóm Quyền Lực"},
        )
    assert resp.status_code == 200
    assert resp.json()["user_id"] == owner_user.user_id
    assert resp.json()["nickname"] == "Trưởng Nhóm Quyền Lực"

    # Member A's nickname must remain "Mít"
    await db_session.refresh(mem_a)
    assert mem_a.nickname == "Mít"


@pytest.mark.asyncio
async def test_admin_cannot_edit_member_nickname(
    test_client: AsyncClient,
    group_conv: Conversation,
    admin_user: User,
    member_user_a: User,
    db_session: AsyncSession,
):
    """ADMIN calling /me/nickname updates ADMIN's nickname only."""
    mem_a = await db_session.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == group_conv.conversation_id,
            ConversationMember.user_id == member_user_a.user_id,
        )
    )
    mem_a.nickname = "Mít"
    await db_session.commit()

    with auth_patch(admin_user):
        resp = await test_client.patch(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
            json={"nickname": "Phó Nhóm"},
        )
    assert resp.status_code == 200
    assert resp.json()["user_id"] == admin_user.user_id
    assert resp.json()["nickname"] == "Phó Nhóm"

    await db_session.refresh(mem_a)
    assert mem_a.nickname == "Mít"


@pytest.mark.asyncio
async def test_removed_member_cannot_edit_nickname(
    test_client: AsyncClient,
    group_conv: Conversation,
    member_user_a: User,
    db_session: AsyncSession,
):
    """Removed member (left_at IS NOT NULL) receives 403 Forbidden."""
    mem_a = await db_session.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == group_conv.conversation_id,
            ConversationMember.user_id == member_user_a.user_id,
        )
    )
    mem_a.left_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db_session.commit()

    with auth_patch(member_user_a):
        resp = await test_client.patch(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
            json={"nickname": "Hacker"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_outsider_cannot_edit_nickname(
    test_client: AsyncClient,
    group_conv: Conversation,
    outsider_user: User,
):
    """Outsider not belonging to group receives 403 Forbidden."""
    with auth_patch(outsider_user):
        resp = await test_client.patch(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
            json={"nickname": "Người Lạ"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_direct_conversation_rejects_nickname(
    test_client: AsyncClient,
    direct_conv: Conversation,
    member_user_a: User,
):
    """DIRECT conversation rejects group nickname endpoint with 400 Bad Request."""
    with auth_patch(member_user_a):
        resp = await test_client.patch(
            f"/api/v1/conversations/groups/{direct_conv.conversation_id}/me/nickname",
            json={"nickname": "Nickname In Direct"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_two_members_can_have_same_nickname(
    test_client: AsyncClient,
    group_conv: Conversation,
    member_user_a: User,
    member_user_b: User,
    db_session: AsyncSession,
):
    """Duplicate nicknames are allowed; no uniqueness constraint."""
    with auth_patch(member_user_a):
        resp_a = await test_client.patch(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
            json={"nickname": "Mít"},
        )
    assert resp_a.status_code == 200

    with auth_patch(member_user_b):
        resp_b = await test_client.patch(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
            json={"nickname": "Mít"},
        )
    assert resp_b.status_code == 200

    mem_a = await db_session.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == group_conv.conversation_id,
            ConversationMember.user_id == member_user_a.user_id,
        )
    )
    mem_b = await db_session.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == group_conv.conversation_id,
            ConversationMember.user_id == member_user_b.user_id,
        )
    )
    assert mem_a.nickname == "Mít"
    assert mem_b.nickname == "Mít"
    assert mem_a.user_id != mem_b.user_id


@pytest.mark.asyncio
async def test_duplicate_real_names_remain_distinct_by_user_id(
    test_client: AsyncClient,
    group_conv: Conversation,
    member_user_a: User,
    member_user_b: User,
    db_session: AsyncSession,
):
    """Two members with identical full_name ('Nguyễn Khắc Thịnh') set different nicknames."""
    assert member_user_a.full_name == member_user_b.full_name == "Nguyễn Khắc Thịnh"

    with auth_patch(member_user_a):
        resp_a = await test_client.patch(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
            json={"nickname": "Mít"},
        )
    assert resp_a.status_code == 200

    with auth_patch(member_user_b):
        resp_b = await test_client.patch(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
            json={"nickname": "Tôm"},
        )
    assert resp_b.status_code == 200

    with auth_patch(member_user_a):
        resp_list = await test_client.get(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/members"
        )
    members = resp_list.json()
    item_a = next(m for m in members if m["user_id"] == member_user_a.user_id)
    item_b = next(m for m in members if m["user_id"] == member_user_b.user_id)

    assert item_a["nickname"] == "Mít"
    assert item_b["nickname"] == "Tôm"
    assert item_a["full_name"] == item_b["full_name"] == "Nguyễn Khắc Thịnh"


@pytest.mark.asyncio
async def test_nickname_update_emits_no_system_message(
    test_client: AsyncClient,
    group_conv: Conversation,
    member_user_a: User,
    db_session: AsyncSession,
):
    """Nickname update generates zero SYSTEM messages in the chat timeline."""
    msg_count_before = await db_session.scalar(
        select(func.count(Message.message_id)).where(
            Message.conversation_id == group_conv.conversation_id
        )
    )

    with auth_patch(member_user_a):
        resp = await test_client.patch(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
            json={"nickname": "Mít"},
        )
    assert resp.status_code == 200

    msg_count_after = await db_session.scalar(
        select(func.count(Message.message_id)).where(
            Message.conversation_id == group_conv.conversation_id
        )
    )
    assert msg_count_after == msg_count_before


@pytest.mark.asyncio
async def test_nickname_update_emits_no_notification_row(
    test_client: AsyncClient,
    group_conv: Conversation,
    member_user_a: User,
    db_session: AsyncSession,
):
    """Nickname update generates zero Notification rows in database."""
    notif_count_before = await db_session.scalar(
        select(func.count(Notification.notification_id))
    )

    with auth_patch(member_user_a):
        resp = await test_client.patch(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
            json={"nickname": "Mít"},
        )
    assert resp.status_code == 200

    notif_count_after = await db_session.scalar(
        select(func.count(Notification.notification_id))
    )
    assert notif_count_after == notif_count_before


@pytest.mark.asyncio
async def test_users_full_name_is_never_mutated(
    test_client: AsyncClient,
    group_conv: Conversation,
    member_user_a: User,
    db_session: AsyncSession,
):
    """Canonical users.full_name is completely untouched by nickname change."""
    original_name = member_user_a.full_name

    with auth_patch(member_user_a):
        resp = await test_client.patch(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
            json={"nickname": "Mít"},
        )
    assert resp.status_code == 200

    await db_session.refresh(member_user_a)
    assert member_user_a.full_name == original_name


@pytest.mark.asyncio
async def test_nickname_is_isolated_per_group(
    test_client: AsyncClient,
    group_conv: Conversation,
    member_user_a: User,
    owner_user: User,
    db_session: AsyncSession,
):
    """Nickname set in Group 1 does not leak into Group 2."""
    # Create second group
    group_2 = Conversation(type="GROUP", title="Nhóm D24CT02")
    db_session.add(group_2)
    await db_session.flush()
    m1 = ConversationMember(conversation_id=group_2.conversation_id, user_id=owner_user.user_id, role="OWNER")
    m2 = ConversationMember(conversation_id=group_2.conversation_id, user_id=member_user_a.user_id, role="MEMBER")
    db_session.add_all([m1, m2])
    await db_session.commit()

    # Set nickname in Group 1
    with auth_patch(member_user_a):
        resp = await test_client.patch(
            f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
            json={"nickname": "Mít"},
        )
    assert resp.status_code == 200

    # Verify Group 2 member list shows nickname is None
    with auth_patch(member_user_a):
        resp2 = await test_client.get(
            f"/api/v1/conversations/groups/{group_2.conversation_id}/members"
        )
    assert resp2.status_code == 200
    members_g2 = resp2.json()
    item_g2 = next(m for m in members_g2 if m["user_id"] == member_user_a.user_id)
    assert item_g2["nickname"] is None
    assert item_g2["full_name"] == member_user_a.full_name


@pytest.mark.asyncio
async def test_realtime_event_dispatched_and_failure_isolated(
    test_client: AsyncClient,
    group_conv: Conversation,
    member_user_a: User,
    db_session: AsyncSession,
):
    """Realtime event GROUP_MEMBERSHIP_CHANGED (NICKNAME_UPDATED) is published. Failure does not rollback DB."""
    with patch("app.modules.conversations.service.publish_user_event", new_callable=AsyncMock) as mock_pub:
        # Simulate exception on publish to test isolation
        mock_pub.side_effect = RuntimeError("Redis connection error")

        with auth_patch(member_user_a):
            resp = await test_client.patch(
                f"/api/v1/conversations/groups/{group_conv.conversation_id}/me/nickname",
                json={"nickname": "Mít"},
            )

        assert resp.status_code == 200
        assert resp.json()["nickname"] == "Mít"
        assert mock_pub.called

        # DB must still have committed nickname
        mem = await db_session.scalar(
            select(ConversationMember).where(
                ConversationMember.conversation_id == group_conv.conversation_id,
                ConversationMember.user_id == member_user_a.user_id,
            )
        )
        assert mem.nickname == "Mít"
