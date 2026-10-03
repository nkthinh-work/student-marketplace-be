from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.categories.models import Category
from app.modules.conversations.models import Conversation, Message
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
async def seller_user(db_session: AsyncSession) -> User:
    user = User(
        email="seller_chat@ptit.edu.vn",
        full_name="Nguyễn Văn Bán",
        phone="0351234567",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def buyer_user(db_session: AsyncSession) -> User:
    user = User(
        email="buyer_chat@ptit.edu.vn",
        full_name="Trần Văn Mua",
        phone="0987654321",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def third_user(db_session: AsyncSession) -> User:
    user = User(
        email="third_chat@ptit.edu.vn",
        full_name="Lê Người Ngoài",
        phone="0911223344",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def category(db_session: AsyncSession) -> Category:
    cat = Category(
        name="Giáo trình & Sách",
        slug="giao-trinh-sach-chat",
    )
    db_session.add(cat)
    await db_session.flush()
    return cat



@pytest_asyncio.fixture
async def product_one(
    db_session: AsyncSession, seller_user: User, category: Category
) -> Product:
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=category.category_id,
        title="Giáo trình Cấu trúc dữ liệu PTIT",
        description="Sách còn mới 95%, không rách",
        price=Decimal("45000"),
        status=ProductStatus.AVAILABLE,
        approval_status="APPROVED",
        listing_type=ListingType.FIXED_PRICE,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


@pytest_asyncio.fixture
async def product_two(
    db_session: AsyncSession, seller_user: User, category: Category
) -> Product:
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=category.category_id,
        title="Máy tính Casio fx-580VN X",
        description="Máy tính dùng tốt môn Toán rời rạc",
        price=Decimal("350000"),
        status=ProductStatus.AVAILABLE,
        approval_status="APPROVED",
        listing_type=ListingType.FIXED_PRICE,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


@pytest_asyncio.fixture
async def third_party_product(
    db_session: AsyncSession, third_user: User, category: Category
) -> Product:
    prod = Product(
        seller_id=third_user.user_id,
        category_id=category.category_id,
        title="Chuột không dây Logitech",
        description="Chuột chính hãng",
        price=Decimal("150000"),
        status=ProductStatus.AVAILABLE,
        approval_status="APPROVED",
        listing_type=ListingType.FIXED_PRICE,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


# ============================================================================
# 1. CONVERSATION IDENTITY & RACE SAFETY TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_create_or_open_conversation(
    test_client: AsyncClient,
    buyer_user: User,
    seller_user: User,
    product_one: Product,
):
    with auth_patch(buyer_user):
        resp = await test_client.post(
            "/api/v1/conversations",
            json={"product_id": product_one.product_id},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "conversation_id" in data
    assert data["other_participant"]["user_id"] == seller_user.user_id
    assert data["other_participant"]["full_name"] == "Nguyễn Văn Bán"
    assert data["product_context"]["product_id"] == product_one.product_id
    assert data["product_context"]["title"] == "Giáo trình Cấu trúc dữ liệu PTIT"


@pytest.mark.asyncio
async def test_open_conversation_idempotency_and_same_user_different_product(
    test_client: AsyncClient,
    buyer_user: User,
    seller_user: User,
    product_one: Product,
    product_two: Product,
):
    # 1. Open with product_one
    with auth_patch(buyer_user):
        resp1 = await test_client.post(
            "/api/v1/conversations",
            json={"product_id": product_one.product_id},
        )
    assert resp1.status_code == 200
    conv_id_1 = resp1.json()["conversation_id"]

    # 2. Repeated open with product_one -> returns same conversation_id
    with auth_patch(buyer_user):
        resp2 = await test_client.post(
            "/api/v1/conversations",
            json={"product_id": product_one.product_id},
        )
    assert resp2.status_code == 200
    assert resp2.json()["conversation_id"] == conv_id_1

    # 3. Open with product_two (same seller) -> returns SAME 1-to-1 conversation_id
    with auth_patch(buyer_user):
        resp3 = await test_client.post(
            "/api/v1/conversations",
            json={"product_id": product_two.product_id},
        )
    assert resp3.status_code == 200
    assert resp3.json()["conversation_id"] == conv_id_1
    assert resp3.json()["product_context"]["product_id"] == product_two.product_id


@pytest.mark.asyncio
async def test_self_chat_forbidden(
    test_client: AsyncClient,
    seller_user: User,
    product_one: Product,
):
    with auth_patch(seller_user):
        resp = await test_client.post(
            "/api/v1/conversations",
            json={"product_id": product_one.product_id},
        )
    assert resp.status_code == 400
    assert "Cannot start conversation with yourself" in resp.json()["detail"]


# ============================================================================
# 2. EMPTY CONVERSATION INBOX FILTERING TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_empty_conversation_not_in_inbox_until_first_message(
    test_client: AsyncClient,
    buyer_user: User,
    seller_user: User,
    product_one: Product,
):
    # 1. Open conversation without sending message
    with auth_patch(buyer_user):
        resp_create = await test_client.post(
            "/api/v1/conversations",
            json={"product_id": product_one.product_id},
        )
    conv_id = resp_create.json()["conversation_id"]

    # 2. Check inbox for buyer and seller -> empty
    with auth_patch(buyer_user):
        resp_inbox_buyer = await test_client.get("/api/v1/conversations")
    assert resp_inbox_buyer.status_code == 200
    assert len(resp_inbox_buyer.json()["items"]) == 0

    with auth_patch(seller_user):
        resp_inbox_seller = await test_client.get("/api/v1/conversations")
    assert resp_inbox_seller.status_code == 200
    assert len(resp_inbox_seller.json()["items"]) == 0

    # 3. Send first message
    with auth_patch(buyer_user):
        resp_msg = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={
                "content": "Chào bạn, sách này còn không ạ?",
                "product_id": product_one.product_id,
            },
        )
    assert resp_msg.status_code == 201

    # 4. Now conversation appears in inbox
    with auth_patch(buyer_user):
        resp_inbox_buyer2 = await test_client.get("/api/v1/conversations")
    assert len(resp_inbox_buyer2.json()["items"]) == 1
    item = resp_inbox_buyer2.json()["items"][0]
    assert item["conversation_id"] == conv_id
    assert item["last_message_preview"] == "Chào bạn, sách này còn không ạ?"
    assert item["unread_count"] == 0  # Buyer sent it

    with auth_patch(seller_user):
        resp_inbox_seller2 = await test_client.get("/api/v1/conversations")
    assert len(resp_inbox_seller2.json()["items"]) == 1
    seller_item = resp_inbox_seller2.json()["items"][0]
    assert seller_item["unread_count"] == 1  # Unread for seller


# ============================================================================
# 3. PRODUCT OWNERSHIP VALIDATION ON MESSAGE SEND
# ============================================================================


@pytest.mark.asyncio
async def test_third_party_product_cannot_be_attached_to_message(
    test_client: AsyncClient,
    buyer_user: User,
    seller_user: User,
    product_one: Product,
    third_party_product: Product,
):
    with auth_patch(buyer_user):
        resp_conv = await test_client.post(
            "/api/v1/conversations",
            json={"product_id": product_one.product_id},
        )
    conv_id = resp_conv.json()["conversation_id"]

    # Attempt to attach third party's product into buyer-seller conversation
    with auth_patch(buyer_user):
        resp_msg = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={
                "content": "Đây là sản phẩm của ai đó",
                "product_id": third_party_product.product_id,
            },
        )
    assert resp_msg.status_code == 400
    assert "Product does not belong to conversation participants" in resp_msg.json()["detail"]


# ============================================================================
# 4. PRIVACY SAFEGUARDS & AUTHORIZATION BOUNDARIES
# ============================================================================


@pytest.mark.asyncio
async def test_non_participant_receives_404_on_all_endpoints(
    test_client: AsyncClient,
    buyer_user: User,
    seller_user: User,
    third_user: User,
    product_one: Product,
):
    with auth_patch(buyer_user):
        resp_conv = await test_client.post(
            "/api/v1/conversations",
            json={"product_id": product_one.product_id},
        )
    conv_id = resp_conv.json()["conversation_id"]

    # Third user tries to GET conversation
    with auth_patch(third_user):
        resp_get = await test_client.get(f"/api/v1/conversations/{conv_id}")
        assert resp_get.status_code == 404

        resp_msgs = await test_client.get(f"/api/v1/conversations/{conv_id}/messages")
        assert resp_msgs.status_code == 404

        resp_send = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"content": "Hacker msg"},
        )
        assert resp_send.status_code == 404

        resp_read = await test_client.post(f"/api/v1/conversations/{conv_id}/read")
        assert resp_read.status_code == 404


@pytest.mark.asyncio
async def test_privacy_no_private_fields_leaked(
    test_client: AsyncClient,
    buyer_user: User,
    seller_user: User,
    product_one: Product,
):
    with auth_patch(buyer_user):
        resp_conv = await test_client.post(
            "/api/v1/conversations",
            json={"product_id": product_one.product_id},
        )
    data = resp_conv.json()
    part = data["other_participant"]

    # Verify zero private fields
    assert "email" not in part
    assert "phone" not in part
    assert "bank_account_number" not in part
    assert "bank_code" not in part
    assert "role" not in part
    assert "status" not in part
    assert "provider_uid" not in part


# ============================================================================
# 5. MARK AS READ & UNREAD STATE INVARIANTS
# ============================================================================


@pytest.mark.asyncio
async def test_mark_as_read_only_marks_other_user_messages(
    test_client: AsyncClient,
    buyer_user: User,
    seller_user: User,
    product_one: Product,
):
    with auth_patch(buyer_user):
        resp_conv = await test_client.post(
            "/api/v1/conversations",
            json={"product_id": product_one.product_id},
        )
        conv_id = resp_conv.json()["conversation_id"]
        # Buyer sends 2 messages
        await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"content": "Tin nhắn 1"},
        )
        await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"content": "Tin nhắn 2"},
        )

    # Seller checks inbox -> unread_count is 2
    with auth_patch(seller_user):
        resp_inbox = await test_client.get("/api/v1/conversations")
        assert resp_inbox.json()["items"][0]["unread_count"] == 2

        # Seller marks as read
        resp_read = await test_client.post(f"/api/v1/conversations/{conv_id}/read")
        assert resp_read.status_code == 200
        assert resp_read.json()["read_count"] == 2

        # Seller checks inbox again -> unread_count is 0
        resp_inbox_after = await test_client.get("/api/v1/conversations")
        assert resp_inbox_after.json()["items"][0]["unread_count"] == 0

    # Buyer marks as read -> read_count is 0 (does not mark own messages)
    with auth_patch(buyer_user):
        resp_read_buyer = await test_client.post(f"/api/v1/conversations/{conv_id}/read")
        assert resp_read_buyer.status_code == 200
        assert resp_read_buyer.json()["read_count"] == 0


# ============================================================================
# 6. DETERMINISTIC KEYSET PAGINATION & CURSOR VALIDATION
# ============================================================================


@pytest.mark.asyncio
async def test_message_keyset_pagination_and_malformed_cursor(
    test_client: AsyncClient,
    buyer_user: User,
    seller_user: User,
    product_one: Product,
):
    with auth_patch(buyer_user):
        resp_conv = await test_client.post(
            "/api/v1/conversations",
            json={"product_id": product_one.product_id},
        )
        conv_id = resp_conv.json()["conversation_id"]

        # Send 5 messages
        for i in range(5):
            await test_client.post(
                f"/api/v1/conversations/{conv_id}/messages",
                json={"content": f"Message {i+1}"},
            )

        # Page 1 (limit=2)
        resp_p1 = await test_client.get(
            f"/api/v1/conversations/{conv_id}/messages?limit=2"
        )
        data_p1 = resp_p1.json()
        assert len(data_p1["items"]) == 2
        assert data_p1["has_more"] is True
        assert data_p1["next_cursor"] is not None
        p1_ids = [m["message_id"] for m in data_p1["items"]]

        # Page 2 (limit=2)
        resp_p2 = await test_client.get(
            f"/api/v1/conversations/{conv_id}/messages?limit=2&cursor={data_p1['next_cursor']}"
        )
        data_p2 = resp_p2.json()
        assert len(data_p2["items"]) == 2
        p2_ids = [m["message_id"] for m in data_p2["items"]]

        # Verify no duplicate or skipped items across pages
        assert set(p1_ids).isdisjoint(set(p2_ids))

        # Test malformed cursor returns 422, NOT 500
        resp_bad = await test_client.get(
            f"/api/v1/conversations/{conv_id}/messages?cursor=invalid_base64_json!!!"
        )
        assert resp_bad.status_code == 422


# ============================================================================
# 7. REALTIME TARGETING TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_message_send_emits_realtime_only_to_participants(
    test_client: AsyncClient,
    buyer_user: User,
    seller_user: User,
    third_user: User,
    product_one: Product,
):
    with patch(
        "app.modules.conversations.service.publish_user_event",
        new_callable=AsyncMock,
    ) as mock_publish:
        with auth_patch(buyer_user):
            resp_conv = await test_client.post(
                "/api/v1/conversations",
                json={"product_id": product_one.product_id},
            )
            conv_id = resp_conv.json()["conversation_id"]

            await test_client.post(
                f"/api/v1/conversations/{conv_id}/messages",
                json={"content": "Realtime test message"},
            )

        # Verify publish_user_event was called for seller and buyer, NOT third_user
        called_user_ids = [call.args[0] for call in mock_publish.call_args_list]
        assert seller_user.user_id in called_user_ids
        assert buyer_user.user_id in called_user_ids
        assert third_user.user_id not in called_user_ids


# ============================================================================
# 8. DIRECT CONVERSATION PERSON-TO-PERSON TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_create_or_open_direct_conversation_canonical_reuse(
    test_client: AsyncClient,
    buyer_user: User,
    seller_user: User,
    product_one: Product,
):
    with auth_patch(buyer_user):
        # 1. Open direct conversation from Public Profile (no product)
        resp_direct = await test_client.post(
            "/api/v1/conversations/direct",
            json={"recipient_public_id": str(seller_user.public_id)},
        )
        assert resp_direct.status_code == 200
        data_direct = resp_direct.json()
        assert data_direct["type"] == "DIRECT"
        assert data_direct["other_participant"]["user_id"] == seller_user.user_id
        assert data_direct.get("product_context") is None
        conv_id = data_direct["conversation_id"]

        # 2. Repeated call by buyer returns exact same conversation_id
        resp_direct_repeat = await test_client.post(
            "/api/v1/conversations/direct",
            json={"recipient_public_id": str(seller_user.public_id)},
        )
        assert resp_direct_repeat.status_code == 200
        assert resp_direct_repeat.json()["conversation_id"] == conv_id

    # 3. Seller calling direct endpoint with buyer returns the same conversation_id
    with auth_patch(seller_user):
        resp_seller_direct = await test_client.post(
            "/api/v1/conversations/direct",
            json={"recipient_public_id": str(buyer_user.public_id)},
        )
        assert resp_seller_direct.status_code == 200
        assert resp_seller_direct.json()["conversation_id"] == conv_id

    # 4. Opening from product also shares the canonical conversation_id
    with auth_patch(buyer_user):
        resp_prod = await test_client.post(
            "/api/v1/conversations",
            json={"product_id": product_one.product_id},
        )
        assert resp_prod.status_code == 200
        assert resp_prod.json()["conversation_id"] == conv_id


@pytest.mark.asyncio
async def test_direct_conversation_validations(
    test_client: AsyncClient,
    buyer_user: User,
):
    with auth_patch(buyer_user):
        # Reject self-chat
        resp_self = await test_client.post(
            "/api/v1/conversations/direct",
            json={"recipient_public_id": str(buyer_user.public_id)},
        )
        assert resp_self.status_code == 400
        assert "Không thể tự nhắn tin cho chính mình" in resp_self.json()["detail"]

        # Reject nonexistent user
        resp_not_found = await test_client.post(
            "/api/v1/conversations/direct",
            json={"recipient_public_id": "00000000-0000-0000-0000-000000000999"},
        )
        assert resp_not_found.status_code == 404


@pytest.mark.asyncio
async def test_reply_cross_conversation_privacy_indistinguishable(
    test_client: AsyncClient,
    db_session: AsyncSession,
    buyer_user: User,
    seller_user: User,
    product_one: Product,
):
    """
    Proves that replying to a nonexistent message_id and replying to an existing
    message_id from another private conversation return the EXACT SAME 404 response.
    No existence leakage.
    """
    # 1. Create Conv A (buyer & seller) and send message A1
    with auth_patch(buyer_user):
        resp_conv_a = await test_client.post(
            "/api/v1/conversations/direct",
            json={"recipient_public_id": str(seller_user.public_id)},
        )
        conv_a_id = resp_conv_a.json()["conversation_id"]

        resp_msg_a = await test_client.post(
            f"/api/v1/conversations/{conv_a_id}/messages",
            data={"content": "Tin nhắn trong Conv A"},
        )
        assert resp_msg_a.status_code == 201

    # 2. Create Conv B (other two users) and send private message B1
    user_c = User(email="user_c@ptit.edu.vn", full_name="User C", role=UserRole.STUDENT.value, status=UserStatus.ACTIVE)
    user_d = User(email="user_d@ptit.edu.vn", full_name="User D", role=UserRole.STUDENT.value, status=UserStatus.ACTIVE)
    db_session.add_all([user_c, user_d])
    await db_session.flush()

    with auth_patch(user_c):
        resp_conv_b = await test_client.post(
            "/api/v1/conversations/direct",
            json={"recipient_public_id": str(user_d.public_id)},
        )
        conv_b_id = resp_conv_b.json()["conversation_id"]

        resp_msg_b = await test_client.post(
            f"/api/v1/conversations/{conv_b_id}/messages",
            data={"content": "Tin nhắn bí mật trong Conv B"},
        )
        assert resp_msg_b.status_code == 201
        msg_b_id = resp_msg_b.json()["message_id"]

    # 3. Buyer in Conv A replies to nonexistent message ID
    with auth_patch(buyer_user):
        resp_nonexistent = await test_client.post(
            f"/api/v1/conversations/{conv_a_id}/messages",
            data={"content": "Trả lời tin không tồn tại", "reply_to_message_id": 99999999},
        )

        # 4. Buyer in Conv A replies to Conv B message ID
        resp_cross_conv = await test_client.post(
            f"/api/v1/conversations/{conv_a_id}/messages",
            data={"content": "Trả lời tin Conv B", "reply_to_message_id": msg_b_id},
        )

    # Privacy-safe contract: Both must return 404 with identical detail
    assert resp_nonexistent.status_code == 404
    assert resp_cross_conv.status_code == 404
    assert resp_nonexistent.json() == resp_cross_conv.json()
    assert resp_nonexistent.json()["detail"] == "Tin nhắn được trả lời không tồn tại hoặc không thể truy cập."


@pytest.mark.asyncio
async def test_reply_to_deleted_or_system_message_rejected(
    test_client: AsyncClient,
    db_session: AsyncSession,
    buyer_user: User,
    seller_user: User,
):
    with auth_patch(buyer_user):
        resp_conv = await test_client.post(
            "/api/v1/conversations/direct",
            json={"recipient_public_id": str(seller_user.public_id)},
        )
        conv_id = resp_conv.json()["conversation_id"]

        # Send normal message
        resp_msg = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={"content": "Tin nhắn sắp bị xóa"},
        )
        msg_id = resp_msg.json()["message_id"]

    # Mark message as deleted in DB
    msg_orm = await db_session.get(Message, msg_id)
    msg_orm.is_deleted = True
    await db_session.commit()

    # Attempt to reply to already-deleted message -> 400
    with auth_patch(seller_user):
        resp_reply_deleted = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={"content": "Thử trả lời tin đã xóa", "reply_to_message_id": msg_id},
        )
        assert resp_reply_deleted.status_code == 400
        assert "Không thể trả lời tin nhắn đã bị xóa" in resp_reply_deleted.json()["detail"]

    # Create SYSTEM message in the same conversation
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sys_msg = Message(
        conversation_id=conv_id,
        sender_id=seller_user.user_id,
        type="SYSTEM",
        content="Hệ thống thông báo",
        sent_at=now,
    )
    db_session.add(sys_msg)
    await db_session.commit()

    # Attempt to reply to SYSTEM message -> 400
    with auth_patch(buyer_user):
        resp_reply_sys = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={"content": "Thử trả lời tin hệ thống", "reply_to_message_id": sys_msg.message_id},
        )
        assert resp_reply_sys.status_code == 400
        assert "Không thể trả lời tin nhắn hệ thống" in resp_reply_sys.json()["detail"]


@pytest.mark.asyncio
async def test_reply_original_later_deleted_renders_tombstone(
    test_client: AsyncClient,
    db_session: AsyncSession,
    buyer_user: User,
    seller_user: User,
):
    """
    Message B replies to Message A. Later A becomes deleted.
    B's reply_to must render safe tombstone 'Tin nhắn không còn khả dụng', not original text.
    """
    with auth_patch(buyer_user):
        resp_conv = await test_client.post(
            "/api/v1/conversations/direct",
            json={"recipient_public_id": str(seller_user.public_id)},
        )
        conv_id = resp_conv.json()["conversation_id"]

        resp_a = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={"content": "Nội dung gốc tuyệt mật"},
        )
        msg_a_id = resp_a.json()["message_id"]

    # Seller replies to Message A
    with auth_patch(seller_user):
        resp_b = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={"content": "Tôi trả lời tin của bạn", "reply_to_message_id": msg_a_id},
        )
        assert resp_b.status_code == 201
        data_b = resp_b.json()
        assert data_b["reply_to"] is not None
        assert data_b["reply_to"]["preview"] == "Nội dung gốc tuyệt mật"

    # Now original message A becomes deleted
    msg_a_orm = await db_session.get(Message, msg_a_id)
    msg_a_orm.is_deleted = True
    await db_session.commit()

    # Query message history: Message B's reply preview must be tombstone
    with auth_patch(seller_user):
        resp_history = await test_client.get(f"/api/v1/conversations/{conv_id}/messages")
        assert resp_history.status_code == 200
        messages = resp_history.json()["items"]
        b_fetched = next(m for m in messages if m["message_id"] == data_b["message_id"])
        assert b_fetched["reply_to"] is not None
        assert b_fetched["reply_to"]["preview"] == "Tin nhắn không còn khả dụng"
        assert "tuyệt mật" not in b_fetched["reply_to"]["preview"]

