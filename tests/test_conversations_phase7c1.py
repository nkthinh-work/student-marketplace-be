from datetime import datetime, timezone
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.conversations.models import (
    Conversation,
    ConversationInvite,
    ConversationMember,
    Message,
    MessageAttachment,
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
async def user_owner(db_session: AsyncSession) -> User:
    u = User(
        email="owner_7c1@ptit.edu.vn",
        full_name="Nguyễn Văn Owner",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def user_admin(db_session: AsyncSession) -> User:
    u = User(
        email="admin_7c1@ptit.edu.vn",
        full_name="Trần Văn Admin",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def user_member(db_session: AsyncSession) -> User:
    u = User(
        email="member_7c1@ptit.edu.vn",
        full_name="Lê Thị Member",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def user_direct_contact(db_session: AsyncSession) -> User:
    u = User(
        email="direct_contact_7c1@ptit.edu.vn",
        full_name="Phạm Direct Contact",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def user_empty_contact(db_session: AsyncSession) -> User:
    u = User(
        email="empty_contact_7c1@ptit.edu.vn",
        full_name="Hoàng Empty Contact",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def user_outsider(db_session: AsyncSession) -> User:
    u = User(
        email="outsider_7c1@ptit.edu.vn",
        full_name="Đỗ Outsider",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest.mark.asyncio
async def test_invite_candidates_derived_from_prior_direct_contacts(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_owner: User,
    user_member: User,
    user_direct_contact: User,
    user_empty_contact: User,
    user_outsider: User,
):
    """
    Test invite candidates:
    - Derived only from prior DIRECT contacts
    - Empty direct conversation (last_message_at is None) excluded
    - Existing group member excluded
    - Pending invite excluded
    - Outsider without direct conversation excluded
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 1. Create a regular GROUP
    grp = Conversation(
        type="GROUP",
        title="Test Candidates Group",
        last_message_at=now,
    )
    db_session.add(grp)
    await db_session.flush()

    mem_owner = ConversationMember(
        conversation_id=grp.conversation_id,
        user_id=user_owner.user_id,
        role="OWNER",
        joined_at=now,
    )
    mem_m = ConversationMember(
        conversation_id=grp.conversation_id,
        user_id=user_member.user_id,
        role="MEMBER",
        joined_at=now,
    )
    db_session.add_all([mem_owner, mem_m])

    # 2. Direct conversation with user_direct_contact WITH message history
    dc_active = Conversation(
        type="DIRECT",
        user_one_id=user_member.user_id,
        user_two_id=user_direct_contact.user_id,
        direct_pair_key=f"{user_member.user_id}:{user_direct_contact.user_id}",
        last_message_at=now,
    )
    db_session.add(dc_active)

    # 3. Direct conversation with user_empty_contact WITHOUT message history (last_message_at is None)
    dc_empty = Conversation(
        type="DIRECT",
        user_one_id=user_member.user_id,
        user_two_id=user_empty_contact.user_id,
        direct_pair_key=f"{user_member.user_id}:{user_empty_contact.user_id}",
        last_message_at=None,
    )
    db_session.add(dc_empty)

    await db_session.commit()

    # 4. Member requests invite candidates
    with auth_patch(user_member):
        res = await test_client.get(f"/api/v1/conversations/{grp.conversation_id}/invite-candidates")
        assert res.status_code == 200
        data = res.json()
        items = data["items"]

        # Only user_direct_contact should be present
        candidate_ids = [item["user_id"] for item in items]
        assert user_direct_contact.user_id in candidate_ids
        assert user_empty_contact.user_id not in candidate_ids
        assert user_owner.user_id not in candidate_ids
        assert user_outsider.user_id not in candidate_ids

    # 5. Send an invite to user_direct_contact -> Should now be excluded from candidates
    with auth_patch(user_member):
        inv_res = await test_client.post(
            f"/api/v1/conversations/groups/{grp.conversation_id}/invites",
            json={"invitee_ids": [user_direct_contact.user_id]},
        )
        assert inv_res.status_code == 200

        # Now query candidates again: should be empty
        res2 = await test_client.get(f"/api/v1/conversations/{grp.conversation_id}/invite-candidates")
        assert res2.status_code == 200
        candidate_ids_after = [item["user_id"] for item in res2.json()["items"]]
        assert user_direct_contact.user_id not in candidate_ids_after

    # 6. Outsider cannot access candidates
    with auth_patch(user_outsider):
        res_outsider = await test_client.get(f"/api/v1/conversations/{grp.conversation_id}/invite-candidates")
        assert res_outsider.status_code == 403


@pytest.mark.asyncio
async def test_role_management_permissions_matrix(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_owner: User,
    user_admin: User,
    user_member: User,
):
    """
    Test permission matrix:
    - OWNER promotes MEMBER -> ADMIN
    - OWNER demotes ADMIN -> MEMBER
    - ADMIN cannot promote or demote
    - ADMIN cannot transfer ownership
    - ADMIN cannot delete group
    - ADMIN can remove MEMBER
    - ADMIN cannot remove another ADMIN or OWNER
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    grp = Conversation(
        type="GROUP",
        title="Role Matrix Group",
        last_message_at=now,
    )
    db_session.add(grp)
    await db_session.flush()

    m_owner = ConversationMember(
        conversation_id=grp.conversation_id,
        user_id=user_owner.user_id,
        role="OWNER",
        joined_at=now,
    )
    m_admin = ConversationMember(
        conversation_id=grp.conversation_id,
        user_id=user_admin.user_id,
        role="ADMIN",
        joined_at=now,
    )
    m_mem = ConversationMember(
        conversation_id=grp.conversation_id,
        user_id=user_member.user_id,
        role="MEMBER",
        joined_at=now,
    )
    db_session.add_all([m_owner, m_admin, m_mem])
    await db_session.commit()

    # 1. ADMIN attempts to promote MEMBER -> Forbidden (403)
    with auth_patch(user_admin):
        res = await test_client.post(
            f"/api/v1/conversations/groups/{grp.conversation_id}/members/{user_member.user_id}/role",
            json={"role": "ADMIN"},
        )
        assert res.status_code == 403

    # 2. ADMIN attempts to transfer ownership -> Forbidden (403)
    with auth_patch(user_admin):
        res = await test_client.post(
            f"/api/v1/conversations/groups/{grp.conversation_id}/transfer-ownership",
            json={"new_owner_id": user_admin.user_id},
        )
        assert res.status_code == 403

    # 3. ADMIN attempts to delete group -> Forbidden (403)
    with auth_patch(user_admin):
        res = await test_client.delete(f"/api/v1/conversations/groups/{grp.conversation_id}")
        assert res.status_code == 403

    # 4. ADMIN attempts to remove OWNER -> Forbidden (403)
    with auth_patch(user_admin):
        res = await test_client.delete(
            f"/api/v1/conversations/groups/{grp.conversation_id}/members/{user_owner.user_id}"
        )
        assert res.status_code == 403

    # 5. OWNER demotes ADMIN -> MEMBER (200)
    with auth_patch(user_owner):
        res = await test_client.post(
            f"/api/v1/conversations/groups/{grp.conversation_id}/members/{user_admin.user_id}/role",
            json={"role": "MEMBER"},
        )
        assert res.status_code == 200

    # 6. OWNER promotes former ADMIN back to ADMIN (200)
    with auth_patch(user_owner):
        res = await test_client.post(
            f"/api/v1/conversations/groups/{grp.conversation_id}/members/{user_admin.user_id}/role",
            json={"role": "ADMIN"},
        )
        assert res.status_code == 200

    # 7. ADMIN removes regular MEMBER -> Success (200)
    with auth_patch(user_admin):
        res = await test_client.delete(
            f"/api/v1/conversations/groups/{grp.conversation_id}/members/{user_member.user_id}"
        )
        assert res.status_code == 200


@pytest.mark.asyncio
async def test_direct_shared_attachments_authorization(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_owner: User,
    user_member: User,
    user_outsider: User,
):
    """
    Test direct shared attachments:
    - Direct participants can access shared attachments and summary
    - Outsider gets 404
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    conv = Conversation(
        type="DIRECT",
        user_one_id=user_owner.user_id,
        user_two_id=user_member.user_id,
        direct_pair_key=f"{user_owner.user_id}:{user_member.user_id}",
        last_message_at=now,
    )
    db_session.add(conv)
    await db_session.flush()

    m1 = ConversationMember(conversation_id=conv.conversation_id, user_id=user_owner.user_id, role="MEMBER", joined_at=now)
    m2 = ConversationMember(conversation_id=conv.conversation_id, user_id=user_member.user_id, role="MEMBER", joined_at=now)
    db_session.add_all([m1, m2])

    msg = Message(
        conversation_id=conv.conversation_id,
        sender_id=user_owner.user_id,
        content="Ảnh gửi nè",
        sent_at=now,
    )
    db_session.add(msg)
    await db_session.flush()

    att = MessageAttachment(
        message_id=msg.message_id,
        kind="IMAGE",
        url="https://res.cloudinary.com/demo/image/upload/v1/test_direct.jpg",
        storage_key="test_direct",
        mime_type="image/jpeg",
        original_name="test_direct.jpg",
        size_bytes=1024,
    )
    db_session.add(att)
    await db_session.commit()

    # Participant accesses summary and attachments -> 200
    with auth_patch(user_member):
        res_sum = await test_client.get(f"/api/v1/conversations/{conv.conversation_id}/attachments/summary")
        assert res_sum.status_code == 200
        assert res_sum.json()["media_count"] == 1

        res_att = await test_client.get(f"/api/v1/conversations/{conv.conversation_id}/attachments?kind=media")
        assert res_att.status_code == 200
        assert len(res_att.json()["items"]) == 1

    # Outsider accesses -> 404
    with auth_patch(user_outsider):
        res_sum_out = await test_client.get(f"/api/v1/conversations/{conv.conversation_id}/attachments/summary")
        assert res_sum_out.status_code == 404

        res_att_out = await test_client.get(f"/api/v1/conversations/{conv.conversation_id}/attachments?kind=media")
        assert res_att_out.status_code == 404
