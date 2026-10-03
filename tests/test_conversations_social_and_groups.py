import io
import zipfile
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

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
    ConversationInvite,
    ConversationMember,
    Message,
)
from app.modules.categories.models import Category
from app.modules.orders.models import Order, OrderStatus
from app.modules.products.models import ListingType, Product, ProductStatus
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
        email="owner_group@ptit.edu.vn",
        full_name="Trần Văn Trưởng Nhóm",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    u = User(
        email="admin_group@ptit.edu.vn",
        full_name="Lê Phó Nhóm",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def member_user(db_session: AsyncSession) -> User:
    u = User(
        email="member_group@ptit.edu.vn",
        full_name="Phạm Thành Viên",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def invitee_user(db_session: AsyncSession) -> User:
    u = User(
        email="invitee_group@ptit.edu.vn",
        full_name="Hoàng Khách Mời",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def category(db_session: AsyncSession) -> Category:
    cat = Category(name="Đồ dùng học tập Nhóm", slug="do-dung-hoc-tap-nhom")
    db_session.add(cat)
    await db_session.commit()
    return cat


@pytest_asyncio.fixture
async def test_order(
    db_session: AsyncSession, owner_user: User, member_user: User, category: Category
) -> Order:
    from app.modules.orders.models import FulfillmentMethod, PaymentMethod
    prod = Product(
        seller_id=owner_user.user_id,
        category_id=category.category_id,
        title="Bàn phím cơ DareU",
        price=Decimal("450000"),
        status=ProductStatus.AVAILABLE,
        approval_status="APPROVED",
    )
    db_session.add(prod)
    await db_session.flush()

    order = Order(
        order_code="ORD-TEST-9999",
        buyer_id=member_user.user_id,
        seller_id=owner_user.user_id,
        status=OrderStatus.PENDING.value,
        total_amount=Decimal("450000"),
        payment_method=PaymentMethod.CASH_ON_MEETUP.value,
        fulfillment_method=FulfillmentMethod.MEETUP.value,
        contact_name="Phạm Thành Viên",
        contact_phone="0987654321",
    )
    db_session.add(order)
    await db_session.commit()
    return order


# Sample file payloads
MP3_BYTES = b"ID3\x03\x00\x00\x00\x00\x00#" + b"\x00" * 100
WEBM_AUDIO_BYTES = b"\x1a\x45\xdf\xa3" + b"\x00" * 100
TXT_BYTES = "Đây là ghi chú môn học PTIT.".encode("utf-8")


def _create_fake_docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", b"<Types></Types>")
        zf.writestr("word/document.xml", b"<w:document></w:document>")
    return buf.getvalue()


DOCX_BYTES = _create_fake_docx()
RAW_ZIP_BYTES = b"PK\x03\x04\x14\x00\x00\x00" + b"\x00" * 100


# ============================================================================
# 1. GROUP CREATION & LIMITS
# ============================================================================


@pytest.mark.asyncio
async def test_create_group_conversation(
    test_client: AsyncClient, owner_user: User, invitee_user: User
):
    with auth_patch(owner_user):
        resp = await test_client.post(
            "/api/v1/conversations/groups",
            json={
                "title": "Nhóm ôn thi Toán Rời Rạc",
                "description": "Thảo luận bài tập và giải đề thi",
                "initial_invitee_ids": [invitee_user.user_id],
            },
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["type"] == "GROUP"
    assert data["title"] == "Nhóm ôn thi Toán Rời Rạc"
    assert data["my_role"] == "OWNER"
    assert data["is_joined"] is True

    # Check invite received by invitee
    with auth_patch(invitee_user):
        invites_resp = await test_client.get("/api/v1/conversations/invites")
        assert invites_resp.status_code == 200
        invites = invites_resp.json()
        assert len(invites) >= 1
        assert invites[0]["inviter_id"] == owner_user.user_id


@pytest.mark.asyncio
async def test_group_creator_max_10_limit(
    test_client: AsyncClient, owner_user: User, db_session: AsyncSession
):
    # Simulate owner having 10 existing groups
    for i in range(10):
        conv = Conversation(type="GROUP", title=f"Nhóm {i+1}")
        db_session.add(conv)
        await db_session.flush()
        mem = ConversationMember(
            conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER"
        )
        db_session.add(mem)
    await db_session.commit()

    with auth_patch(owner_user):
        resp = await test_client.post(
            "/api/v1/conversations/groups",
            json={"title": "Nhóm thứ 11 vượt giới hạn"},
        )
    assert resp.status_code == 400
    assert "tối đa 10 nhóm" in resp.json()["detail"]


# ============================================================================
# 2. INVITES & CAPACITY CHECKS
# ============================================================================


@pytest.mark.asyncio
async def test_invite_permissions_and_accept(
    test_client: AsyncClient,
    owner_user: User,
    admin_user: User,
    member_user: User,
    invitee_user: User,
    db_session: AsyncSession,
):
    # Create group
    conv = Conversation(type="GROUP", title="Nhóm Lập Trình Python")
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    m_admin = ConversationMember(conversation_id=conv.conversation_id, user_id=admin_user.user_id, role="ADMIN")
    m_member = ConversationMember(conversation_id=conv.conversation_id, user_id=member_user.user_id, role="MEMBER")
    db_session.add_all([m_owner, m_admin, m_member])
    await db_session.commit()

    # 1. Normal active MEMBER can invite in Phase 7C -> 200
    with auth_patch(member_user):
        resp_m = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/invites",
            json={"invitee_ids": [invitee_user.user_id]},
        )
    assert resp_m.status_code == 200
    invites = resp_m.json()
    assert len(invites) == 1
    invite_id = invites[0]["invite_id"]

    # 2. Non-member / outside user cannot invite -> 403
    outsider = User(email="outsider@ptit.edu.vn", full_name="Người ngoài", role=UserRole.STUDENT, status=UserStatus.ACTIVE)
    db_session.add(outsider)
    await db_session.commit()
    with auth_patch(outsider):
        resp_out = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/invites",
            json={"invitee_ids": [invitee_user.user_id]},
        )
    assert resp_out.status_code == 403

    # 3. Invitee accepts invite -> becomes active MEMBER
    with auth_patch(invitee_user):
        resp_acc = await test_client.post(
            f"/api/v1/conversations/invites/{invite_id}/respond",
            json={"action": "ACCEPT"},
        )
    assert resp_acc.status_code == 200
    assert resp_acc.json()["status"] == "ACCEPTED"

    # Invitee can now view group messages
    with auth_patch(invitee_user):
        msg_resp = await test_client.get(
            f"/api/v1/conversations/{conv.conversation_id}/messages"
        )
    assert msg_resp.status_code == 200


# ============================================================================
# 3. ROLES, TRANSFER OWNERSHIP, AND LEAVE
# ============================================================================


@pytest.mark.asyncio
async def test_group_member_management_and_transfer_ownership(
    test_client: AsyncClient,
    owner_user: User,
    member_user: User,
    db_session: AsyncSession,
):
    conv = Conversation(type="GROUP", title="Nhóm Quản Trị Hệ Thống")
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    m_member = ConversationMember(conversation_id=conv.conversation_id, user_id=member_user.user_id, role="MEMBER")
    db_session.add_all([m_owner, m_member])
    await db_session.commit()

    # 1. Promote member to ADMIN
    with auth_patch(owner_user):
        resp_promote = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/members/{member_user.user_id}/role",
            json={"role": "ADMIN"},
        )
    assert resp_promote.status_code == 200

    # 2. Transfer ownership
    with auth_patch(owner_user):
        resp_transfer = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/transfer-ownership",
            json={"new_owner_id": member_user.user_id},
        )
    assert resp_transfer.status_code == 200

    # 3. Original owner is now ADMIN, can leave group safely
    with auth_patch(owner_user):
        resp_leave = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/leave"
        )
    assert resp_leave.status_code == 200


# ============================================================================
# 4. GROUP JOIN HISTORY PRIVACY
# ============================================================================


@pytest.mark.asyncio
async def test_group_join_history_privacy_rule(
    test_client: AsyncClient,
    owner_user: User,
    invitee_user: User,
    db_session: AsyncSession,
):
    conv = Conversation(type="GROUP", title="Nhóm Bảo Mật Thông Tin")
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    db_session.add(m_owner)
    await db_session.commit()

    # Owner sends an old message before invitee joins
    with auth_patch(owner_user):
        await test_client.post(
            f"/api/v1/conversations/{conv.conversation_id}/messages",
            data={"content": "Tin nhắn mật trước khi người mới tham gia"},
        )

    # Invitee invited and accepts
    with auth_patch(owner_user):
        inv_res = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/invites",
            json={"invitee_ids": [invitee_user.user_id]},
        )
    invite_id = inv_res.json()[0]["invite_id"]

    with auth_patch(invitee_user):
        await test_client.post(
            f"/api/v1/conversations/invites/{invite_id}/respond",
            json={"action": "ACCEPT"},
        )

    # Owner sends a new message after invitee joined
    with auth_patch(owner_user):
        await test_client.post(
            f"/api/v1/conversations/{conv.conversation_id}/messages",
            data={"content": "Chào mừng thành viên mới!"},
        )

    # Invitee reads message history: MUST ONLY SEE the new message, NOT pre-join message
    with auth_patch(invitee_user):
        history_res = await test_client.get(
            f"/api/v1/conversations/{conv.conversation_id}/messages"
        )
    messages = history_res.json()["items"]
    # Invitee sees the new message and their join system message, but NEVER the pre-join message
    assert len(messages) == 2
    assert messages[0]["content"] == "Chào mừng thành viên mới!"
    assert messages[1]["content"] == f"{invitee_user.full_name} đã tham gia nhóm."
    assert all("Tin nhắn mật trước khi người mới tham gia" != m["content"] for m in messages)


# ============================================================================
# 5. OFFICIAL SUPPORT GROUP (CANONICAL GROUP RESOLUTION & JOIN)
# ============================================================================


@pytest.mark.asyncio
async def test_official_support_group_join_lifecycle(
    test_client: AsyncClient,
    owner_user: User,
    member_user: User,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    # 1. Unconfigured support group returns 503
    monkeypatch.setattr(settings, "OFFICIAL_SUPPORT_GROUP_ID", None)
    with auth_patch(member_user):
        resp_unconf = await test_client.post("/api/v1/conversations/official-support/join")
    assert resp_unconf.status_code == 503

    # 2. Non-existent support group returns 404
    monkeypatch.setattr(settings, "OFFICIAL_SUPPORT_GROUP_ID", 999999)
    with auth_patch(member_user):
        resp_notfound = await test_client.post("/api/v1/conversations/official-support/join")
    assert resp_notfound.status_code == 404

    # 3. Configured group with wrong type (DIRECT) returns 400
    direct_conv = Conversation(
        type="DIRECT",
        user_one_id=member_user.user_id,
        user_two_id=owner_user.user_id,
    )
    db_session.add(direct_conv)
    await db_session.commit()
    monkeypatch.setattr(settings, "OFFICIAL_SUPPORT_GROUP_ID", direct_conv.conversation_id)
    with auth_patch(member_user):
        resp_wrong = await test_client.post("/api/v1/conversations/official-support/join")
    assert resp_wrong.status_code == 400

    # 4. Valid GROUP joins successfully
    support_conv = Conversation(
        type="GROUP",
        title="Cộng đồng Chợ PTITers",
    )
    db_session.add(support_conv)
    await db_session.commit()
    monkeypatch.setattr(settings, "OFFICIAL_SUPPORT_GROUP_ID", support_conv.conversation_id)

    with auth_patch(member_user):
        resp_ok = await test_client.post("/api/v1/conversations/official-support/join")
    assert resp_ok.status_code == 200
    assert resp_ok.json()["conversation_id"] == support_conv.conversation_id

    # 5. Idempotent join: repeated join does not create duplicate members
    with auth_patch(member_user):
        resp_repeat = await test_client.post("/api/v1/conversations/official-support/join")
    assert resp_repeat.status_code == 200
    assert resp_repeat.json()["conversation_id"] == support_conv.conversation_id

    members_count = await db_session.scalar(
        select(func.count(ConversationMember.user_id)).where(
            ConversationMember.conversation_id == support_conv.conversation_id,
            ConversationMember.user_id == member_user.user_id,
        )
    )
    assert members_count == 1


# ============================================================================
# 6. CONTEXTUAL MARKETPLACE ENTRY FROM ORDER
# ============================================================================


@pytest.mark.asyncio
async def test_conversation_from_order_endpoint(
    test_client: AsyncClient,
    owner_user: User,
    member_user: User,
    invitee_user: User,
    test_order: Order,
):
    # Buyer calls from-order
    with auth_patch(member_user):
        resp_buyer = await test_client.post(
            "/api/v1/conversations/from-order",
            json={"order_id": test_order.order_id},
        )
    assert resp_buyer.status_code == 200
    conv_id = resp_buyer.json()["conversation_id"]

    # Seller calls from-order -> resolves SAME conversation_id
    with auth_patch(owner_user):
        resp_seller = await test_client.post(
            "/api/v1/conversations/from-order",
            json={"order_id": test_order.order_id},
        )
    assert resp_seller.status_code == 200
    assert resp_seller.json()["conversation_id"] == conv_id

    # Non-order participant receives 404
    with auth_patch(invitee_user):
        resp_third = await test_client.post(
            "/api/v1/conversations/from-order",
            json={"order_id": test_order.order_id},
        )
    assert resp_third.status_code == 404


# ============================================================================
# 7. AUDIO, VOICE NOTES, AND DOCUMENTS
# ============================================================================


@pytest.mark.asyncio
async def test_audio_and_document_attachments(
    test_client: AsyncClient,
    owner_user: User,
    member_user: User,
    db_session: AsyncSession,
):
    conv = Conversation(
        type="DIRECT",
        direct_pair_key=f"{min(owner_user.user_id, member_user.user_id)}:{max(owner_user.user_id, member_user.user_id)}",
        user_one_id=min(owner_user.user_id, member_user.user_id),
        user_two_id=max(owner_user.user_id, member_user.user_id),
    )
    db_session.add(conv)
    await db_session.flush()

    m1 = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="MEMBER")
    m2 = ConversationMember(conversation_id=conv.conversation_id, user_id=member_user.user_id, role="MEMBER")
    db_session.add_all([m1, m2])
    await db_session.commit()

    mock_upload = {
        "public_id": "student-marketplace/test_audio",
        "secure_url": "https://res.cloudinary.com/demo/video/upload/audio.mp3",
        "duration": 45.0,  # 45 seconds (<= 300s)
    }

    with auth_patch(owner_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value=mock_upload,
    ):
        files = [
            ("files", ("voice.mp3", MP3_BYTES, "audio/mpeg")),
            ("files", ("notes.docx", DOCX_BYTES, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
        ]
        resp = await test_client.post(
            f"/api/v1/conversations/{conv.conversation_id}/messages",
            data={"content": "Tin nhắn đính kèm ghi âm và Word"},
            files=files,
        )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["attachments"]) == 2
    kinds = [att["kind"] for att in data["attachments"]]
    assert "AUDIO" in kinds
    assert "DOCUMENT" in kinds

    # Verify canonical /attachments-summary reports exact count
    with auth_patch(owner_user):
        summary_resp = await test_client.get(
            f"/api/v1/conversations/{conv.conversation_id}/attachments/summary"
        )
    assert summary_resp.status_code == 200
    summary_data = summary_resp.json()
    assert summary_data["audio_count"] == 1
    assert summary_data["file_count"] == 1
    assert summary_data["media_count"] == 0


@pytest.mark.asyncio
async def test_reject_fake_zip_as_docx(
    test_client: AsyncClient,
    owner_user: User,
    member_user: User,
    db_session: AsyncSession,
):
    conv = Conversation(
        type="DIRECT",
        direct_pair_key=f"{min(owner_user.user_id, member_user.user_id)}:{max(owner_user.user_id, member_user.user_id)}",
        user_one_id=min(owner_user.user_id, member_user.user_id),
        user_two_id=max(owner_user.user_id, member_user.user_id),
    )
    db_session.add(conv)
    await db_session.flush()
    m1 = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="MEMBER")
    m2 = ConversationMember(conversation_id=conv.conversation_id, user_id=member_user.user_id, role="MEMBER")
    db_session.add_all([m1, m2])
    await db_session.commit()

    # Raw zip disguised as docx
    files = [
        ("files", ("malware.docx", RAW_ZIP_BYTES, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
    ]
    with auth_patch(owner_user):
        resp = await test_client.post(
            f"/api/v1/conversations/{conv.conversation_id}/messages",
            files=files,
        )
    assert resp.status_code == 400
    assert "Tệp nén zip hoặc tệp Office giả mạo không được hỗ trợ" in resp.json()["detail"]


# ============================================================================
# 8. PRODUCT PICKER DIRECT ONLY & PUBLIC USER SEARCH
# ============================================================================


@pytest.mark.asyncio
async def test_product_sharing_direct_only(
    test_client: AsyncClient,
    owner_user: User,
    category: Category,
    db_session: AsyncSession,
):
    # Create group and product
    conv = Conversation(type="GROUP", title="Nhóm Thảo Luận Mua Bán")
    db_session.add(conv)
    prod = Product(seller_id=owner_user.user_id, category_id=category.category_id, title="Tai nghe Sony", price=Decimal("1200000"), approval_status="APPROVED")
    db_session.add(prod)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    db_session.add(m_owner)
    await db_session.commit()

    # Attempting to share product card into group -> 400 Bad Request
    with auth_patch(owner_user):
        resp = await test_client.post(
            f"/api/v1/conversations/{conv.conversation_id}/messages",
            data={"product_id": prod.product_id, "content": "Thẻ sản phẩm trong nhóm"},
        )
    assert resp.status_code == 400
    assert "Không thể gửi thẻ sản phẩm vào nhóm trò chuyện" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_public_user_search(
    test_client: AsyncClient, owner_user: User, invitee_user: User
):
    with auth_patch(owner_user):
        resp = await test_client.get(
            f"/api/v1/users/search?q={invitee_user.full_name[:5]}"
        )
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) >= 1
    # Verify no private data leaked
    for item in results:
        assert "email" not in item
        assert "phone" not in item
        assert "role" not in item
        assert "bank_account" not in item
        assert "user_id" in item


# ============================================================================
# 9. GROUP LIFECYCLE SYSTEM MESSAGES & OWNER-ONLY APPROVAL SETTINGS (FINAL v3)
# ============================================================================


@pytest.mark.asyncio
async def test_admin_cannot_toggle_requires_approval(
    test_client: AsyncClient,
    owner_user: User,
    admin_user: User,
    db_session: AsyncSession,
):
    """ADMIN cannot toggle requires_approval (OWNER only)."""
    conv = Conversation(type="GROUP", title="Nhóm Kiểm Tra Quyền", requires_approval=False)
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    m_admin = ConversationMember(conversation_id=conv.conversation_id, user_id=admin_user.user_id, role="ADMIN")
    db_session.add_all([m_owner, m_admin])
    await db_session.commit()

    with auth_patch(admin_user):
        resp = await test_client.patch(
            f"/api/v1/conversations/groups/{conv.conversation_id}",
            json={"requires_approval": True},
        )
    assert resp.status_code == 403
    assert "Chỉ trưởng nhóm" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_admin_cannot_list_pending_approvals(
    test_client: AsyncClient,
    owner_user: User,
    admin_user: User,
    db_session: AsyncSession,
):
    """ADMIN cannot list pending approvals (OWNER only)."""
    conv = Conversation(type="GROUP", title="Nhóm Duyệt", requires_approval=True)
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    m_admin = ConversationMember(conversation_id=conv.conversation_id, user_id=admin_user.user_id, role="ADMIN")
    db_session.add_all([m_owner, m_admin])
    await db_session.commit()

    with auth_patch(admin_user):
        resp = await test_client.get(
            f"/api/v1/conversations/groups/{conv.conversation_id}/pending-approvals",
        )
    assert resp.status_code == 403
    assert "Chỉ trưởng nhóm" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_admin_cannot_approve_or_reject(
    test_client: AsyncClient,
    owner_user: User,
    admin_user: User,
    invitee_user: User,
    db_session: AsyncSession,
):
    """ADMIN cannot approve or reject pending approvals (OWNER only)."""
    conv = Conversation(type="GROUP", title="Nhóm Xét Duyệt", requires_approval=True)
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    m_admin = ConversationMember(conversation_id=conv.conversation_id, user_id=admin_user.user_id, role="ADMIN")
    inv = ConversationInvite(
        conversation_id=conv.conversation_id,
        inviter_id=admin_user.user_id,
        invitee_id=invitee_user.user_id,
        status="PENDING_APPROVAL",
    )
    db_session.add_all([m_owner, m_admin, inv])
    await db_session.commit()

    # ADMIN attempts APPROVE
    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/pending-approvals/{inv.invite_id}",
            json={"action": "APPROVE"},
        )
    assert resp.status_code == 403
    assert "Chỉ trưởng nhóm" in resp.json()["detail"]

    # ADMIN attempts REJECT
    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/pending-approvals/{inv.invite_id}",
            json={"action": "REJECT"},
        )
    assert resp.status_code == 403
    assert "Chỉ trưởng nhóm" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_admin_invite_requires_owner_approval_when_approval_on(
    test_client: AsyncClient,
    owner_user: User,
    admin_user: User,
    invitee_user: User,
    db_session: AsyncSession,
):
    """When requires_approval is TRUE, invite sent by ADMIN goes to PENDING_APPROVAL on accept."""
    conv = Conversation(type="GROUP", title="Nhóm Cần Duyệt", requires_approval=True)
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    m_admin = ConversationMember(conversation_id=conv.conversation_id, user_id=admin_user.user_id, role="ADMIN")
    db_session.add_all([m_owner, m_admin])
    await db_session.commit()

    # Admin invites D
    with auth_patch(admin_user):
        inv_res = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/invites",
            json={"invitee_ids": [invitee_user.user_id]},
        )
    assert inv_res.status_code == 200
    invite_id = inv_res.json()[0]["invite_id"]

    # D accepts -> transitions to PENDING_APPROVAL
    with auth_patch(invitee_user):
        resp = await test_client.post(
            f"/api/v1/conversations/invites/{invite_id}/respond",
            json={"action": "ACCEPT"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "PENDING_APPROVAL"

    # D is NOT an active member yet
    stmt_mem = select(ConversationMember).where(
        ConversationMember.conversation_id == conv.conversation_id,
        ConversationMember.user_id == invitee_user.user_id,
        ConversationMember.left_at.is_(None),
    )
    assert (await db_session.scalar(stmt_mem)) is None

    # OWNER views pending approvals
    with auth_patch(owner_user):
        list_res = await test_client.get(
            f"/api/v1/conversations/groups/{conv.conversation_id}/pending-approvals",
        )
    assert list_res.status_code == 200
    items = list_res.json()["items"]
    assert len(items) == 1
    assert items[0]["invitee_id"] == invitee_user.user_id
    assert items[0]["inviter_id"] == admin_user.user_id

    # OWNER approves D
    with auth_patch(owner_user):
        appr_res = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/pending-approvals/{invite_id}",
            json={"action": "APPROVE"},
        )
    assert appr_res.status_code == 200
    assert appr_res.json()["status"] == "ACCEPTED"

    # Now D is an active member
    stmt_mem_active = select(ConversationMember).where(
        ConversationMember.conversation_id == conv.conversation_id,
        ConversationMember.user_id == invitee_user.user_id,
        ConversationMember.left_at.is_(None),
    )
    active_d = await db_session.scalar(stmt_mem_active)
    assert active_d is not None
    assert active_d.role == "MEMBER"


@pytest.mark.asyncio
async def test_owner_trusted_invite_bypasses_approval(
    test_client: AsyncClient,
    owner_user: User,
    invitee_user: User,
    db_session: AsyncSession,
):
    """When requires_approval is TRUE, invite sent by OWNER bypasses approval on accept."""
    conv = Conversation(type="GROUP", title="Nhóm Có Duyệt Nhưng Chủ Nhóm Mời", requires_approval=True)
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    db_session.add(m_owner)
    await db_session.commit()

    # OWNER invites D
    with auth_patch(owner_user):
        inv_res = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/invites",
            json={"invitee_ids": [invitee_user.user_id]},
        )
    assert inv_res.status_code == 200
    invite_id = inv_res.json()[0]["invite_id"]

    # D accepts -> direct ACCEPTED!
    with auth_patch(invitee_user):
        resp = await test_client.post(
            f"/api/v1/conversations/invites/{invite_id}/respond",
            json={"action": "ACCEPT"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ACCEPTED"

    # D is active member
    stmt_mem = select(ConversationMember).where(
        ConversationMember.conversation_id == conv.conversation_id,
        ConversationMember.user_id == invitee_user.user_id,
        ConversationMember.left_at.is_(None),
    )
    active_d = await db_session.scalar(stmt_mem)
    assert active_d is not None
    assert active_d.role == "MEMBER"


@pytest.mark.asyncio
async def test_turning_approval_off_keeps_existing_pending_unresolved(
    test_client: AsyncClient,
    owner_user: User,
    admin_user: User,
    invitee_user: User,
    db_session: AsyncSession,
):
    """Turning approval OFF keeps existing PENDING_APPROVAL invites unresolved."""
    conv = Conversation(type="GROUP", title="Nhóm Đổi Cài Đặt Duyệt", requires_approval=True)
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    m_admin = ConversationMember(conversation_id=conv.conversation_id, user_id=admin_user.user_id, role="ADMIN")
    inv = ConversationInvite(
        conversation_id=conv.conversation_id,
        inviter_id=admin_user.user_id,
        invitee_id=invitee_user.user_id,
        status="PENDING_APPROVAL",
    )
    db_session.add_all([m_owner, m_admin, inv])
    await db_session.commit()

    # OWNER toggles approval OFF
    with auth_patch(owner_user):
        resp = await test_client.patch(
            f"/api/v1/conversations/groups/{conv.conversation_id}",
            json={"requires_approval": False},
        )
    assert resp.status_code == 200
    assert resp.json()["requires_approval"] is False

    # Existing invite must STILL be PENDING_APPROVAL
    await db_session.refresh(inv)
    assert inv.status == "PENDING_APPROVAL"

    # OWNER still can approve it
    with auth_patch(owner_user):
        appr_res = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/pending-approvals/{inv.invite_id}",
            json={"action": "APPROVE"},
        )
    assert appr_res.status_code == 200
    assert appr_res.json()["status"] == "ACCEPTED"


@pytest.mark.asyncio
async def test_stale_pending_target_already_active_does_not_duplicate_membership(
    test_client: AsyncClient,
    owner_user: User,
    admin_user: User,
    invitee_user: User,
    db_session: AsyncSession,
):
    """If target in PENDING_APPROVAL already became active, owner approving resolves invite safely without duplicating membership or creating fake system message."""
    conv = Conversation(type="GROUP", title="Nhóm Stale Approval", requires_approval=True)
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    m_admin = ConversationMember(conversation_id=conv.conversation_id, user_id=admin_user.user_id, role="ADMIN")
    # Target is already active
    m_target = ConversationMember(conversation_id=conv.conversation_id, user_id=invitee_user.user_id, role="MEMBER")
    inv = ConversationInvite(
        conversation_id=conv.conversation_id,
        inviter_id=admin_user.user_id,
        invitee_id=invitee_user.user_id,
        status="PENDING_APPROVAL",
    )
    db_session.add_all([m_owner, m_admin, m_target, inv])
    await db_session.commit()

    # Count messages before approval
    msg_count_before = await db_session.scalar(
        select(func.count(Message.message_id)).where(Message.conversation_id == conv.conversation_id)
    )

    with auth_patch(owner_user):
        appr_res = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/pending-approvals/{inv.invite_id}",
            json={"action": "APPROVE"},
        )
    assert appr_res.status_code == 200
    assert appr_res.json()["status"] == "ACCEPTED"
    assert appr_res.json().get("already_active") is True

    # No new duplicate member rows
    mem_rows = (
        await db_session.scalars(
            select(ConversationMember).where(
                ConversationMember.conversation_id == conv.conversation_id,
                ConversationMember.user_id == invitee_user.user_id,
            )
        )
    ).all()
    assert len(mem_rows) == 1

    # No fake join system message created
    msg_count_after = await db_session.scalar(
        select(func.count(Message.message_id)).where(Message.conversation_id == conv.conversation_id)
    )
    assert msg_count_after == msg_count_before


@pytest.mark.asyncio
async def test_system_does_not_increment_unread_or_bump_inbox(
    test_client: AsyncClient,
    owner_user: User,
    member_user: User,
    db_session: AsyncSession,
):
    """System messages do not increment unread_count, do not update last_message_at, and do not become inbox preview."""
    # Create group via API to emit creation system message
    with auth_patch(owner_user):
        create_res = await test_client.post(
            "/api/v1/conversations/groups",
            json={"title": "Nhóm Thử Nghiệm Inbox", "description": "Mô tả ban đầu"},
        )
    assert create_res.status_code == 201
    conv_id = create_res.json()["conversation_id"]

    # Verify last_message_at in DB is None!
    conv_db = await db_session.get(Conversation, conv_id)
    assert conv_db.last_message_at is None

    # Owner invites member
    with auth_patch(owner_user):
        inv_res = await test_client.post(
            f"/api/v1/conversations/groups/{conv_id}/invites",
            json={"invitee_ids": [member_user.user_id]},
        )
    invite_id = inv_res.json()[0]["invite_id"]

    # Member joins (direct join since approval is OFF) -> emits join SYSTEM message
    with auth_patch(member_user):
        await test_client.post(
            f"/api/v1/conversations/invites/{invite_id}/respond",
            json={"action": "ACCEPT"},
        )

    # Check member's conversation inbox list
    with auth_patch(member_user):
        inbox_res = await test_client.get("/api/v1/conversations?type=GROUP")
    assert inbox_res.status_code == 200
    inbox_items = inbox_res.json()["items"]
    group_inbox = next((c for c in inbox_items if c["conversation_id"] == conv_id), None)
    assert group_inbox is not None
    # unread_count MUST BE 0!
    assert group_inbox["unread_count"] == 0
    # last_message_preview MUST BE None! (excluded SYSTEM)
    assert group_inbox["last_message_preview"] is None
    # last_message_at MUST BE None!
    assert group_inbox["last_message_at"] is None

    # Owner renames group and toggles approval
    with auth_patch(owner_user):
        await test_client.patch(
            f"/api/v1/conversations/groups/{conv_id}",
            json={"title": "Nhóm Thử Nghiệm Đổi Tên", "requires_approval": True},
        )

    # Inbox still has unread_count == 0 and last_message_preview == None!
    with auth_patch(member_user):
        inbox_res2 = await test_client.get("/api/v1/conversations?type=GROUP")
    group_inbox2 = next((c for c in inbox_res2.json()["items"] if c["conversation_id"] == conv_id), None)
    assert group_inbox2["unread_count"] == 0
    assert group_inbox2["last_message_preview"] is None


@pytest.mark.asyncio
async def test_group_timeline_returns_system_messages(
    test_client: AsyncClient,
    owner_user: User,
    member_user: User,
    db_session: AsyncSession,
):
    """Group chat timeline returns SYSTEM messages with type='SYSTEM'."""
    with auth_patch(owner_user):
        create_res = await test_client.post(
            "/api/v1/conversations/groups",
            json={"title": "Nhóm Xem Timeline"},
        )
    conv_id = create_res.json()["conversation_id"]

    with auth_patch(owner_user):
        hist_res = await test_client.get(f"/api/v1/conversations/{conv_id}/messages")
    assert hist_res.status_code == 200
    items = hist_res.json()["items"]
    assert len(items) >= 1
    create_msg = items[-1]
    assert create_msg["type"] == "SYSTEM"
    assert "đã tạo nhóm" in create_msg["content"]


@pytest.mark.asyncio
async def test_client_cannot_forge_persisted_system_message(
    test_client: AsyncClient,
    owner_user: User,
    db_session: AsyncSession,
):
    """Client cannot forge persisted Message.type == 'SYSTEM'."""
    conv = Conversation(type="GROUP", title="Nhóm Anti Spoof")
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    db_session.add(m_owner)
    await db_session.commit()

    with auth_patch(owner_user):
        resp = await test_client.post(
            f"/api/v1/conversations/{conv.conversation_id}/messages",
            data={"content": "Tôi là tin nhắn giả mạo hệ thống", "type": "SYSTEM"},
        )
    assert resp.status_code == 201
    msg_data = resp.json()
    # Type MUST BE TEXT!
    assert msg_data["type"] == "TEXT"

    # Verify DB column is TEXT
    msg_db = await db_session.get(Message, msg_data["message_id"])
    assert msg_db.type == "TEXT"


@pytest.mark.asyncio
async def test_system_event_matrix_coverage(
    test_client: AsyncClient,
    owner_user: User,
    admin_user: User,
    member_user: User,
    db_session: AsyncSession,
):
    """Verifies SYSTEM messages for promotion, demotion, rename, description, transfer, remove, leave."""
    conv = Conversation(type="GROUP", title="Nhóm Matrix Test")
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    m_admin = ConversationMember(conversation_id=conv.conversation_id, user_id=admin_user.user_id, role="ADMIN")
    m_mem = ConversationMember(conversation_id=conv.conversation_id, user_id=member_user.user_id, role="MEMBER")
    db_session.add_all([m_owner, m_admin, m_mem])
    await db_session.commit()

    # 1. Promote member to admin
    with auth_patch(owner_user):
        resp_promote = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/members/{member_user.user_id}/role",
            json={"role": "ADMIN"},
        )
    assert resp_promote.status_code == 200

    # 2. Demote admin to member
    with auth_patch(owner_user):
        resp_demote = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/members/{member_user.user_id}/role",
            json={"role": "MEMBER"},
        )
    assert resp_demote.status_code == 200

    # 3. Rename and description update in one PATCH
    with auth_patch(owner_user):
        resp_meta = await test_client.patch(
            f"/api/v1/conversations/groups/{conv.conversation_id}",
            json={"title": "Tên Nhóm Mới Toanh", "description": "Mô tả nhóm mới"},
        )
    assert resp_meta.status_code == 200

    # 4. Remove member
    with auth_patch(owner_user):
        await test_client.delete(
            f"/api/v1/conversations/groups/{conv.conversation_id}/members/{member_user.user_id}",
        )

    # 5. Transfer ownership (owner -> admin)
    with auth_patch(owner_user):
        await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/transfer-ownership",
            json={"new_owner_id": admin_user.user_id},
        )

    # 6. Old owner (now MEMBER) leaves group
    with auth_patch(owner_user):
        await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/leave",
        )

    # Fetch messages and assert all corresponding SYSTEM messages exist
    with auth_patch(admin_user):
        hist_res = await test_client.get(f"/api/v1/conversations/{conv.conversation_id}/messages")
    assert hist_res.status_code == 200
    texts = [m["content"] for m in hist_res.json()["items"]]

    assert any("đã bổ nhiệm" in t and "làm phó nhóm" in t for t in texts)
    assert any("đã gỡ quyền phó nhóm của" in t for t in texts)
    assert any('đã đổi tên nhóm thành "Tên Nhóm Mới Toanh"' in t for t in texts)
    assert any("đã cập nhật mô tả nhóm" in t for t in texts)
    assert any("đã xóa" in t and "khỏi nhóm" in t for t in texts)
    assert any("đã chuyển quyền trưởng nhóm cho" in t for t in texts)
    assert any("đã rời khỏi nhóm" in t for t in texts)


@pytest.mark.asyncio
async def test_removed_member_cannot_fetch_group_messages(
    test_client: AsyncClient,
    owner_user: User,
    member_user: User,
    db_session: AsyncSession,
):
    """Removed member cannot fetch group messages history (403/404)."""
    conv = Conversation(type="GROUP", title="Nhóm Đã Bị Xóa")
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    m_mem = ConversationMember(conversation_id=conv.conversation_id, user_id=member_user.user_id, role="MEMBER")
    db_session.add_all([m_owner, m_mem])
    await db_session.commit()

    # Owner removes member
    with auth_patch(owner_user):
        del_res = await test_client.delete(
            f"/api/v1/conversations/groups/{conv.conversation_id}/members/{member_user.user_id}"
        )
    assert del_res.status_code == 200

    # Removed member tries to fetch message history -> 404 or 403
    with auth_patch(member_user):
        hist_res = await test_client.get(f"/api/v1/conversations/{conv.conversation_id}/messages")
    assert hist_res.status_code in (403, 404)


@pytest.mark.asyncio
async def test_owner_reject_pending_approval(
    test_client: AsyncClient,
    owner_user: User,
    admin_user: User,
    invitee_user: User,
    db_session: AsyncSession,
):
    """Owner rejecting pending approval marks invite DECLINED with no membership and no join system message."""
    conv = Conversation(type="GROUP", title="Nhóm Từ Chối", requires_approval=True)
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    inv = ConversationInvite(
        conversation_id=conv.conversation_id,
        inviter_id=admin_user.user_id,
        invitee_id=invitee_user.user_id,
        status="PENDING_APPROVAL",
    )
    db_session.add_all([m_owner, inv])
    await db_session.commit()

    with auth_patch(owner_user):
        resp = await test_client.post(
            f"/api/v1/conversations/groups/{conv.conversation_id}/pending-approvals/{inv.invite_id}",
            json={"action": "REJECT"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "DECLINED"

    await db_session.refresh(inv)
    assert inv.status == "DECLINED"

    # Invitee is NOT member
    stmt = select(ConversationMember).where(
        ConversationMember.conversation_id == conv.conversation_id,
        ConversationMember.user_id == invitee_user.user_id,
    )
    assert (await db_session.scalar(stmt)) is None


@pytest.mark.asyncio
async def test_pending_approval_api_shape(
    test_client: AsyncClient,
    owner_user: User,
    admin_user: User,
    invitee_user: User,
    db_session: AsyncSession,
):
    """Pending approval GET returns object with 'items' array matching PendingApprovalListResponse."""
    conv = Conversation(type="GROUP", title="Nhóm Shape", requires_approval=True)
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    inv = ConversationInvite(
        conversation_id=conv.conversation_id,
        inviter_id=admin_user.user_id,
        invitee_id=invitee_user.user_id,
        status="PENDING_APPROVAL",
    )
    db_session.add_all([m_owner, inv])
    await db_session.commit()

    with auth_patch(owner_user):
        resp = await test_client.get(
            f"/api/v1/conversations/groups/{conv.conversation_id}/pending-approvals"
        )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "items" in data
    assert isinstance(data["items"], list)
    assert len(data["items"]) == 1
    item = data["items"][0]
    for field in ("invite_id", "conversation_id", "invitee_id", "invitee_name", "inviter_id", "inviter_name", "created_at"):
        assert field in item


@pytest.mark.asyncio
async def test_direct_conversation_regression_free(
    test_client: AsyncClient,
    owner_user: User,
    member_user: User,
    db_session: AsyncSession,
):
    """Direct conversations remain unaffected, message type is TEXT."""
    with auth_patch(owner_user):
        conv_res = await test_client.post(
            "/api/v1/conversations/direct",
            json={"recipient_public_id": str(member_user.public_id)},
        )
    assert conv_res.status_code in (200, 201)
    conv_id = conv_res.json()["conversation_id"]

    with auth_patch(owner_user):
        msg_res = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={"content": "Tin nhắn 1-1 bình thường"},
        )
    assert msg_res.status_code == 201
    assert msg_res.json()["type"] == "TEXT"


# ============================================================================
# 10. GROUP MEMBERSHIP ACCESS REVOCATION & REALTIME LIFECYCLE (VERIFIED)
# ============================================================================


@pytest.mark.asyncio
async def test_remove_member_sets_left_at_and_emits_targeted_revocation_event(
    test_client: AsyncClient,
    owner_user: User,
    member_user: User,
    db_session: AsyncSession,
):
    """
    Removing a group member:
    1. Persists ConversationMember.left_at = now in DB.
    2. Emits targeted GROUP_MEMBERSHIP_CHANGED (action: 'REMOVED') to removed user.
    3. Emits MESSAGE_CREATED and GROUP_MEMBERSHIP_CHANGED (action: 'MEMBER_REMOVED') to remaining members.
    """
    conv = Conversation(type="GROUP", title="Nhóm Kiểm Tra Eject")
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    m_mem = ConversationMember(conversation_id=conv.conversation_id, user_id=member_user.user_id, role="MEMBER")
    db_session.add_all([m_owner, m_mem])
    await db_session.commit()

    published_events: list[tuple[int, dict]] = []

    async def fake_publish(uid: int, evt: dict):
        published_events.append((uid, evt))

    with patch("app.modules.conversations.service.publish_user_event", side_effect=fake_publish):
        with auth_patch(owner_user):
            del_res = await test_client.delete(
                f"/api/v1/conversations/groups/{conv.conversation_id}/members/{member_user.user_id}"
            )
        assert del_res.status_code == 200

    # 1. DB membership is revoked
    stmt = select(ConversationMember).where(
        ConversationMember.conversation_id == conv.conversation_id,
        ConversationMember.user_id == member_user.user_id,
    )
    db_mem = await db_session.scalar(stmt)
    assert db_mem is not None
    assert db_mem.left_at is not None

    # 2. Targeted user received GROUP_MEMBERSHIP_CHANGED action='REMOVED'
    target_events = [evt for uid, evt in published_events if uid == member_user.user_id]
    assert len(target_events) == 1
    assert target_events[0]["type"] == "GROUP_MEMBERSHIP_CHANGED"
    assert target_events[0]["conversation_id"] == conv.conversation_id
    assert target_events[0]["action"] == "REMOVED"
    # Target does not receive MESSAGE_CREATED
    assert not any(evt["type"] == "MESSAGE_CREATED" for uid, evt in published_events if uid == member_user.user_id)

    # 3. Remaining member (owner) received system message and MEMBER_REMOVED
    owner_events = [evt for uid, evt in published_events if uid == owner_user.user_id]
    assert any(evt["type"] == "MESSAGE_CREATED" for evt in owner_events)
    assert any(evt["type"] == "GROUP_MEMBERSHIP_CHANGED" and evt.get("action") == "MEMBER_REMOVED" for evt in owner_events)


@pytest.mark.asyncio
async def test_removed_member_conversation_list_self_correction(
    test_client: AsyncClient,
    owner_user: User,
    member_user: User,
    db_session: AsyncSession,
):
    """
    Once membership is revoked (left_at != NULL), GET /conversations?type=GROUP as removed member
    MUST NOT return the group. PostgreSQL remains the strict source of truth.
    """
    conv = Conversation(type="GROUP", title="Nhóm Biến Mất Khỏi Inbox")
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    m_mem = ConversationMember(conversation_id=conv.conversation_id, user_id=member_user.user_id, role="MEMBER")
    db_session.add_all([m_owner, m_mem])
    await db_session.commit()

    # Before removal: Member sees group in conversation list
    with auth_patch(member_user):
        before_res = await test_client.get("/api/v1/conversations?type=GROUP")
    assert before_res.status_code == 200
    assert any(item["conversation_id"] == conv.conversation_id for item in before_res.json()["items"])

    # Owner removes member
    with auth_patch(owner_user):
        del_res = await test_client.delete(
            f"/api/v1/conversations/groups/{conv.conversation_id}/members/{member_user.user_id}"
        )
    assert del_res.status_code == 200

    # After removal: Member's list query excludes the removed group
    with auth_patch(member_user):
        after_res = await test_client.get("/api/v1/conversations?type=GROUP")
    assert after_res.status_code == 200
    assert all(item["conversation_id"] != conv.conversation_id for item in after_res.json()["items"])


@pytest.mark.asyncio
async def test_removed_member_forbidden_endpoints(
    test_client: AsyncClient,
    owner_user: User,
    member_user: User,
    db_session: AsyncSession,
):
    """
    After membership revocation, removed member cannot access:
    - GET /conversations/{id} -> 404
    - GET /conversations/{id}/messages -> 404
    - POST /conversations/{id}/messages -> 404
    - GET /conversations/groups/{id}/members -> 403
    """
    conv = Conversation(type="GROUP", title="Nhóm Bị Chặn Hoàn Toàn")
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    m_mem = ConversationMember(conversation_id=conv.conversation_id, user_id=member_user.user_id, role="MEMBER")
    db_session.add_all([m_owner, m_mem])
    await db_session.commit()

    with auth_patch(owner_user):
        del_res = await test_client.delete(
            f"/api/v1/conversations/groups/{conv.conversation_id}/members/{member_user.user_id}"
        )
    assert del_res.status_code == 200

    with auth_patch(member_user):
        # 1. Detail endpoint
        res_detail = await test_client.get(f"/api/v1/conversations/{conv.conversation_id}")
        assert res_detail.status_code == 404

        # 2. Messages list
        res_msgs = await test_client.get(f"/api/v1/conversations/{conv.conversation_id}/messages")
        assert res_msgs.status_code == 404

        # 3. Send message
        res_send = await test_client.post(
            f"/api/v1/conversations/{conv.conversation_id}/messages",
            data={"content": "Cố tình gửi tin nhắn sau khi bị xóa"},
        )
        assert res_send.status_code == 404

        # 4. Member list
        res_members = await test_client.get(f"/api/v1/conversations/groups/{conv.conversation_id}/members")
        assert res_members.status_code == 403


@pytest.mark.asyncio
async def test_future_group_messages_do_not_fan_out_to_removed_member(
    test_client: AsyncClient,
    owner_user: User,
    member_user: User,
    db_session: AsyncSession,
):
    """
    Subsequent messages sent to the group by remaining members must only fan-out
    to active members (left_at IS NULL), NEVER to removed members.
    """
    conv = Conversation(type="GROUP", title="Nhóm Kiểm Tra Fan-out Sau Xóa")
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    m_mem = ConversationMember(conversation_id=conv.conversation_id, user_id=member_user.user_id, role="MEMBER")
    db_session.add_all([m_owner, m_mem])
    await db_session.commit()

    # Remove member
    with auth_patch(owner_user):
        del_res = await test_client.delete(
            f"/api/v1/conversations/groups/{conv.conversation_id}/members/{member_user.user_id}"
        )
    assert del_res.status_code == 200

    # Remaining owner sends a new message to group
    dispatched_uids: list[int] = []

    async def fake_publish(uid: int, evt: dict):
        dispatched_uids.append(uid)

    with patch("app.modules.conversations.service.publish_user_event", side_effect=fake_publish):
        with auth_patch(owner_user):
            msg_res = await test_client.post(
                f"/api/v1/conversations/{conv.conversation_id}/messages",
                data={"content": "Tin nhắn mới sau khi đã xóa thành viên"},
            )
        assert msg_res.status_code == 201

    # Verify removed member_user was NOT dispatched to!
    assert member_user.user_id not in dispatched_uids
    assert owner_user.user_id in dispatched_uids


@pytest.mark.asyncio
async def test_redis_failure_does_not_rollback_member_removal(
    test_client: AsyncClient,
    owner_user: User,
    member_user: User,
    db_session: AsyncSession,
):
    """
    If Redis publish fails or raises an exception during event emission,
    the PostgreSQL membership revocation transaction is already committed and remains valid.
    """
    conv = Conversation(type="GROUP", title="Nhóm Thử Nghiệm Redis Failure")
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    m_mem = ConversationMember(conversation_id=conv.conversation_id, user_id=member_user.user_id, role="MEMBER")
    db_session.add_all([m_owner, m_mem])
    await db_session.commit()

    # Simulate Redis connection failure inside publish_user_event
    async def failing_publish(*args, **kwargs):
        raise ConnectionError("Redis server connection refused")

    with patch("app.modules.conversations.service.publish_user_event", side_effect=failing_publish):
        with auth_patch(owner_user):
            del_res = await test_client.delete(
                f"/api/v1/conversations/groups/{conv.conversation_id}/members/{member_user.user_id}"
            )
        # Even if publish fails, business operation succeeds or commits
        assert del_res.status_code == 200

    # DB state must reflect left_at is set
    stmt = select(ConversationMember).where(
        ConversationMember.conversation_id == conv.conversation_id,
        ConversationMember.user_id == member_user.user_id,
    )
    db_mem = await db_session.scalar(stmt)
    assert db_mem is not None
    assert db_mem.left_at is not None


@pytest.mark.asyncio
async def test_role_update_does_not_emit_revocation_and_preserves_membership(
    test_client: AsyncClient,
    owner_user: User,
    member_user: User,
    db_session: AsyncSession,
):
    """
    Role changes (MEMBER -> ADMIN or ADMIN -> MEMBER) must NOT emit revocation events
    and must keep ConversationMember.left_at as None.
    """
    conv = Conversation(type="GROUP", title="Nhóm Kiểm Tra Đổi Role")
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=owner_user.user_id, role="OWNER")
    m_mem = ConversationMember(conversation_id=conv.conversation_id, user_id=member_user.user_id, role="MEMBER")
    db_session.add_all([m_owner, m_mem])
    await db_session.commit()

    published_events: list[tuple[int, dict]] = []

    async def fake_publish(uid: int, evt: dict):
        published_events.append((uid, evt))

    with patch("app.modules.conversations.service.publish_user_event", side_effect=fake_publish):
        with auth_patch(owner_user):
            role_res = await test_client.post(
                f"/api/v1/conversations/groups/{conv.conversation_id}/members/{member_user.user_id}/role",
                json={"role": "ADMIN"},
            )
        assert role_res.status_code == 200

    # Membership left_at is still None
    stmt = select(ConversationMember).where(
        ConversationMember.conversation_id == conv.conversation_id,
        ConversationMember.user_id == member_user.user_id,
    )
    db_mem = await db_session.scalar(stmt)
    assert db_mem is not None
    assert db_mem.left_at is None
    assert db_mem.role == "ADMIN"

    # Events emitted do NOT contain action='REMOVED' or action='LEFT'
    for uid, evt in published_events:
        assert evt.get("action") not in ("REMOVED", "LEFT")

