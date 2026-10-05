import uuid
from datetime import datetime, timezone
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.categories.models import Category
from app.modules.conversations.models import Conversation, ConversationMember
from app.modules.daily_needs.models import DailyNeed
from app.modules.daily_needs.repository import get_vietnam_today
from app.modules.orders.models import Order, OrderItem, OrderStatus
from app.modules.products.models import ListingType, Product, ProductApprovalStatus, ProductModerationStatus, ProductStatus
from app.modules.products.repository import ProductRepository
from app.modules.reports.models import Report, ReportReason, ReportTargetType
from app.modules.reviews.models import Review
from app.modules.users.models import User, UserRole, UserStatus
from app.modules.users.repository import UserRepository
from app.main import app


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
    user = User(
        email="user_a_pubtest@ptit.edu.vn",
        full_name="Nguyễn Văn A Public",
        phone="0352866111",
        avatar_url="https://lh3.googleusercontent.com/a/pub_user_a",
        bio="Học CNTT PTIT",
        delivery_area="Hà Đông, Thanh Xuân",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
        bank_bin="970422",
        bank_account_number="111222333",
        bank_account_name="NGUYEN VAN A",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    user = User(
        email="user_b_pubtest@ptit.edu.vn",
        full_name="Trần Thị B Public",
        phone="0352866222",
        avatar_url="https://lh3.googleusercontent.com/a/pub_user_b",
        bio="Học DTVT PTIT",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def banned_user_fixture(db_session: AsyncSession) -> User:
    user = User(
        email="banned_pubtest@ptit.edu.vn",
        full_name="Bị Khóa Public",
        role=UserRole.STUDENT.value,
        status=UserStatus.BANNED,
    )
    db_session.add(user)
    await db_session.flush()
    return user


# =====================================================================
# 1. UUID V4 GENERATION AND UNIQUENESS
# =====================================================================

@pytest.mark.asyncio
async def test_user_provisioning_assigns_valid_uuid_v4(user_a: User, user_b: User):
    assert user_a.public_id is not None
    assert user_b.public_id is not None
    assert isinstance(user_a.public_id, uuid.UUID)
    assert isinstance(user_b.public_id, uuid.UUID)
    # Check UUID version 4
    assert user_a.public_id.version == 4
    assert user_b.public_id.version == 4
    # Must be distinct
    assert user_a.public_id != user_b.public_id


# =====================================================================
# 2. PUBLIC PROFILE LOOKUP BY PUBLIC_ID & SECURITY EXCLUSIONS
# =====================================================================

@pytest.mark.asyncio
async def test_public_profile_lookup_by_public_id(test_client: AsyncClient, user_a: User):
    res = await test_client.get(f"/api/v1/users/{user_a.public_id}")
    assert res.status_code == 200
    data = res.json()

    # public_id present
    assert data["public_id"] == str(user_a.public_id)
    assert data["full_name"] == user_a.full_name
    assert data["avatar_url"] == user_a.avatar_url
    assert data["bio"] == user_a.bio
    assert data["delivery_area"] == user_a.delivery_area

    # MUST NOT leak internal numeric user_id or sensitive fields
    assert "user_id" not in data
    assert "email" not in data
    assert data.get("phone") is None  # phone hidden by default
    assert "bank_bin" not in data
    assert "bank_account_number" not in data
    assert "bank_account_name" not in data
    assert "role" not in data


@pytest.mark.asyncio
async def test_public_profile_random_uuid_returns_404(test_client: AsyncClient):
    random_uuid = uuid.uuid4()
    res = await test_client.get(f"/api/v1/users/{random_uuid}")
    assert res.status_code == 404
    assert res.json()["detail"] == "Không tìm thấy người dùng."


@pytest.mark.asyncio
async def test_public_profile_invalid_uuid_returns_422(test_client: AsyncClient):
    # Numeric ID or arbitrary string must return 422 Unprocessable Content (FastAPI path type validation)
    res = await test_client.get("/api/v1/users/12345")
    assert res.status_code == 422

    res_str = await test_client.get("/api/v1/users/not-a-uuid")
    assert res_str.status_code == 422


@pytest.mark.asyncio
async def test_public_profile_banned_user_returns_404(test_client: AsyncClient, banned_user_fixture: User):
    res = await test_client.get(f"/api/v1/users/{banned_user_fixture.public_id}")
    assert res.status_code == 404


# =====================================================================
# 3. PUBLIC_ID IMMUTABILITY DURING PROFILE UPDATES
# =====================================================================

@pytest.mark.asyncio
async def test_profile_update_cannot_change_public_id(test_client: AsyncClient, user_a: User, db_session: AsyncSession):
    original_public_id = user_a.public_id
    fake_new_uuid = str(uuid.uuid4())

    with auth_patch(user_a):
        res = await test_client.patch(
            "/api/v1/users/me",
            json={
                "full_name": "Nguyễn Văn A Đã Đổi Tên",
                "public_id": fake_new_uuid,
            },
            headers={"Authorization": "Bearer mock"},
        )

    # FastAPI extra="forbid" in UserUpdateRequest rejects unexpected public_id with 422
    assert res.status_code == 422

    # Verify in DB that public_id remained completely unchanged
    await db_session.refresh(user_a)
    assert user_a.public_id == original_public_id


# =====================================================================
# 4. STATIC ROUTES COLLISION PREVENTION (/me, /search, /banks)
# =====================================================================

@pytest.mark.asyncio
async def test_static_routes_not_shadowed(test_client: AsyncClient, user_a: User):
    with auth_patch(user_a):
        # /users/me
        res_me = await test_client.get("/api/v1/users/me", headers={"Authorization": "Bearer mock"})
        assert res_me.status_code == 200
        assert res_me.json()["email"] == user_a.email
        assert res_me.json()["public_id"] == str(user_a.public_id)

        # /users/banks
        res_banks = await test_client.get("/api/v1/users/banks")
        assert res_banks.status_code == 200
        assert isinstance(res_banks.json(), list)

        # /users/search
        res_search = await test_client.get("/api/v1/users/search?q=Public", headers={"Authorization": "Bearer mock"})
        assert res_search.status_code == 200


# =====================================================================
# 5. PUBLIC NESTED DTO PROJECTIONS (PRODUCTS, REVIEWS, SOLD-PRODUCTS, DAILY-NEEDS)
# =====================================================================

@pytest.mark.asyncio
async def test_product_seller_projection_uses_public_id(
    test_client: AsyncClient, user_a: User, db_session: AsyncSession
):
    cat = Category(name="Sách giáo trình", slug="sach-gt")
    db_session.add(cat)
    await db_session.flush()

    prod = Product(
        seller_id=user_a.user_id,
        category_id=cat.category_id,
        title="Sách Hệ điều hành",
        description="Mới 98%",
        listing_type=ListingType.FIXED_PRICE.value,
        price=45000,
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status=ProductApprovalStatus.APPROVED.value,
        moderation_status=ProductModerationStatus.CLEAR.value,
    )
    db_session.add(prod)
    await db_session.commit()

    # 1. Product detail
    res_det = await test_client.get(f"/api/v1/products/{prod.product_id}")
    assert res_det.status_code == 200
    seller = res_det.json()["seller"]
    assert seller["public_id"] == str(user_a.public_id)
    assert "user_id" not in seller

    # 2. Product list
    res_list = await test_client.get(f"/api/v1/products?seller_public_id={user_a.public_id}")
    assert res_list.status_code == 200
    items = res_list.json()["items"]
    assert len(items) >= 1
    assert items[0]["seller"]["public_id"] == str(user_a.public_id)
    assert "user_id" not in items[0]["seller"]


@pytest.mark.asyncio
async def test_public_user_reviews_and_sold_products_endpoints(
    test_client: AsyncClient, user_a: User, user_b: User, db_session: AsyncSession
):
    cat = Category(name="Đồ điện tử", slug="do-dien-tu")
    db_session.add(cat)
    await db_session.flush()

    prod = Product(
        seller_id=user_a.user_id,
        category_id=cat.category_id,
        title="Chuột Logitech M331",
        description="Dùng tốt",
        listing_type=ListingType.FIXED_PRICE.value,
        price=120000,
        stock=0,
        reserved_stock=0,
        status=ProductStatus.SOLD_OUT.value,
        approval_status=ProductApprovalStatus.APPROVED.value,
        moderation_status=ProductModerationStatus.CLEAR.value,
    )
    db_session.add(prod)
    await db_session.flush()

    order = Order(
        order_code="ORD-PUBTEST-01",
        buyer_id=user_b.user_id,
        seller_id=user_a.user_id,
        contact_name="Trần Thị B",
        contact_phone="0352866222",
        status=OrderStatus.COMPLETED.value,
        total_amount=120000,
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.order_id,
        product_id=prod.product_id,
        product_title=prod.title,
        quantity=1,
        price_at_purchase=120000,
    )
    db_session.add(item)
    await db_session.flush()

    rev = Review(
        order_id=order.order_id,
        reviewer_id=user_b.user_id,
        reviewee_id=user_a.user_id,
        rating=5,
        comment="Giao dịch nhanh chóng uy tín",
    )
    db_session.add(rev)
    await db_session.commit()

    # GET /users/{public_id}/reviews
    res_rev = await test_client.get(f"/api/v1/users/{user_a.public_id}/reviews")
    assert res_rev.status_code == 200
    rev_data = res_rev.json()
    assert len(rev_data["items"]) >= 1
    assert rev_data["items"][0]["rating"] == 5

    # GET /users/{public_id}/sold-products
    res_sold = await test_client.get(f"/api/v1/users/{user_a.public_id}/sold-products")
    assert res_sold.status_code == 200
    sold_data = res_sold.json()
    assert len(sold_data["items"]) >= 1
    assert sold_data["items"][0]["product_title"] == "Chuột Logitech M331"


@pytest.mark.asyncio
async def test_public_daily_needs_today_endpoint(
    test_client: AsyncClient, user_a: User, db_session: AsyncSession
):
    note = DailyNeed(
        user_id=user_a.user_id,
        note_date=get_vietnam_today(),
        content="Tìm mua giáo trình XSTK",
    )
    db_session.add(note)
    await db_session.commit()

    res = await test_client.get(f"/api/v1/daily-needs/users/{user_a.public_id}/today")
    assert res.status_code == 200
    note_data = res.json()
    assert note_data["content"] == "Tìm mua giáo trình XSTK"
    assert note_data["author"]["public_id"] == str(user_a.public_id)
    assert "user_id" not in note_data["author"]


# =====================================================================
# 6. DIRECT CONVERSATION INITIATION USING RECIPIENT_PUBLIC_ID
# =====================================================================

@pytest.mark.asyncio
async def test_create_direct_conversation_with_recipient_public_id(
    test_client: AsyncClient, user_a: User, user_b: User, db_session: AsyncSession
):
    with auth_patch(user_a):
        res = await test_client.post(
            "/api/v1/conversations/direct",
            json={"recipient_public_id": str(user_b.public_id)},
            headers={"Authorization": "Bearer mock"},
        )
    assert res.status_code in (200, 201)
    data = res.json()
    assert data["type"] == "DIRECT"

    # Test C: Verify resolved internal user_id participants in database
    conv_id = data["conversation_id"]
    part_res = await db_session.execute(
        select(ConversationMember.user_id).where(ConversationMember.conversation_id == conv_id)
    )
    participant_user_ids = set(part_res.scalars().all())
    assert participant_user_ids == {user_a.user_id, user_b.user_id}


@pytest.mark.asyncio
async def test_direct_conversation_rejects_numeric_recipient(
    test_client: AsyncClient, user_a: User, user_b: User
):
    # Test D: Direct conversation does NOT accept numeric recipient targeting
    with auth_patch(user_a):
        # 1. recipient_id (numeric) forbidden
        res1 = await test_client.post(
            "/api/v1/conversations/direct",
            json={"recipient_id": user_b.user_id},
            headers={"Authorization": "Bearer mock"},
        )
        assert res1.status_code == 422

        # 2. recipient_user_id (numeric) forbidden
        res2 = await test_client.post(
            "/api/v1/conversations/direct",
            json={"recipient_user_id": user_b.user_id},
            headers={"Authorization": "Bearer mock"},
        )
        assert res2.status_code == 422

        # 3. recipient_public_id as integer forbidden
        res3 = await test_client.post(
            "/api/v1/conversations/direct",
            json={"recipient_public_id": user_b.user_id},
            headers={"Authorization": "Bearer mock"},
        )
        assert res3.status_code == 422


# =====================================================================
# 7. REGRESSION TESTS: UUID VS INTEGER OPERATOR MISMATCH (Tests A & B)
# =====================================================================

@pytest.mark.asyncio
async def test_regression_uuid_query_executes_without_operator_mismatch(
    test_client: AsyncClient, user_a: User, db_session: AsyncSession
):
    # Test A: valid UUID public profile query executes against real local PostgreSQL without operator mismatch
    user_repo = UserRepository(db_session)

    # 1. Valid UUID
    user_found = await user_repo.get_by_public_id(user_a.public_id)
    assert user_found is not None
    assert user_found.user_id == user_a.user_id

    # 2. String representation of valid UUID
    user_found_str = await user_repo.get_by_public_id(str(user_a.public_id))
    assert user_found_str is not None
    assert user_found_str.user_id == user_a.user_id

    # 3. Defensive handling: numeric / integer input must return None without operator does not exist: uuid = integer
    user_by_int = await user_repo.get_by_public_id(user_a.user_id)  # type: ignore
    assert user_by_int is None

    # 4. Defensive handling: arbitrary non-UUID string
    user_by_str = await user_repo.get_by_public_id("not-a-valid-uuid")  # type: ignore
    assert user_by_str is None


@pytest.mark.asyncio
async def test_seller_public_id_filter_uses_uuid_binding(
    test_client: AsyncClient, user_a: User, db_session: AsyncSession
):
    # Test B: seller_public_id filter uses UUID binding, not INTEGER binding
    prod_repo = ProductRepository(db_session)

    # 1. Filter by valid UUID
    products_uuid, has_more_uuid, _ = await prod_repo.list_public(seller_public_id=user_a.public_id)
    assert isinstance(products_uuid, list)

    # 2. Filter by str UUID
    products_str, has_more_str, _ = await prod_repo.list_public(seller_public_id=str(user_a.public_id))  # type: ignore
    assert isinstance(products_str, list)
    assert len(products_uuid) == len(products_str)

    # 3. Filter by integer must NOT raise PostgreSQL "operator does not exist: uuid = integer"
    products_int, has_more_int, _ = await prod_repo.list_public(seller_public_id=user_a.user_id)  # type: ignore
    assert products_int == []

    # 4. Filter by invalid string
    products_bad, has_more_bad, _ = await prod_repo.list_public(seller_public_id="invalid-uuid")  # type: ignore
    assert products_bad == []


# =====================================================================
# 8. REPORTS CONTRACT TESTS (Tests E & F)
# =====================================================================

@pytest.mark.asyncio
async def test_reports_target_type_contracts(
    test_client: AsyncClient, user_a: User, user_b: User, db_session: AsyncSession
):
    # Setup a sample product and order
    cat = Category(name=f"Đồ gia dụng {uuid.uuid4().hex[:6]}", slug=f"do-gia-dung-{uuid.uuid4().hex[:6]}")
    db_session.add(cat)
    await db_session.flush()

    prod = Product(
        seller_id=user_b.user_id,
        category_id=cat.category_id,
        title="Bàn học gấp",
        description="Còn dùng tốt",
        listing_type=ListingType.FIXED_PRICE.value,
        price=80000,
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status=ProductApprovalStatus.APPROVED.value,
        moderation_status=ProductModerationStatus.CLEAR.value,
    )
    db_session.add(prod)
    await db_session.flush()

    order = Order(
        order_code=f"ORD-REPTEST-{uuid.uuid4().hex[:6]}",
        buyer_id=user_a.user_id,
        seller_id=user_b.user_id,
        contact_name="Nguyễn Văn A",
        contact_phone="0352866111",
        status=OrderStatus.COMPLETED.value,
        total_amount=80000,
    )
    db_session.add(order)
    await db_session.commit()

    with auth_patch(user_a):
        # Test E: USER report requires target_public_id, rejects numeric target_id
        res_user_numeric = await test_client.post(
            "/api/v1/reports",
            json={"target_type": "USER", "target_id": user_b.user_id, "reason": "SPAM"},
        )
        assert res_user_numeric.status_code == 422

        res_user_valid = await test_client.post(
            "/api/v1/reports",
            json={"target_type": "USER", "target_public_id": str(user_b.public_id), "reason": "SPAM"},
        )
        assert res_user_valid.status_code == 201
        report_id = res_user_valid.json()["report_id"]

        # Verify internal DB integrity: resolved target_id is internal user_id
        rep_stmt = select(Report).where(Report.report_id == report_id)
        rep = (await db_session.execute(rep_stmt)).scalar_one()
        assert rep.target_id == user_b.user_id

        # Test F: PRODUCT / ORDER reports still use target_id, reject target_public_id
        res_prod_uuid = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "PRODUCT",
                "target_id": prod.product_id,
                "target_public_id": str(uuid.uuid4()),
                "reason": "FAKE_ITEM",
            },
        )
        assert res_prod_uuid.status_code == 422

        res_prod_valid = await test_client.post(
            "/api/v1/reports",
            json={"target_type": "PRODUCT", "target_id": prod.product_id, "reason": "FAKE_ITEM"},
        )
        assert res_prod_valid.status_code == 201

        res_order_uuid = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "ORDER",
                "target_id": order.order_id,
                "target_public_id": str(uuid.uuid4()),
                "reason": "NO_SHOW",
            },
        )
        assert res_order_uuid.status_code == 422

        res_order_valid = await test_client.post(
            "/api/v1/reports",
            json={"target_type": "ORDER", "target_id": order.order_id, "reason": "NO_SHOW"},
        )
        assert res_order_valid.status_code == 201


# =====================================================================
# 9. DATABASE UNIQUE STRUCTURE SANITY (Test I)
# =====================================================================

# =====================================================================
# 9. DATABASE UNIQUE STRUCTURE SANITY (Test I)
# =====================================================================

@pytest.mark.asyncio
async def test_no_duplicate_public_id_database_structures(db_session: AsyncSession):
    # Test I: Exactly one unique constraint and one unique index on users.public_id
    index_res = await db_session.execute(text("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'users' AND indexdef LIKE '%public_id%';
    """))
    indexes = index_res.fetchall()
    assert len(indexes) == 1
    assert indexes[0][0] == "ux_users_public_id"

    constraint_res = await db_session.execute(text("""
        SELECT conname, contype
        FROM pg_constraint
        WHERE conrelid = 'users'::regclass AND conname LIKE '%public_id%';
    """))
    constraints = constraint_res.fetchall()
    assert len(constraints) == 1
    assert constraints[0][0] == "ux_users_public_id"
    assert constraints[0][1] in ("u", b"u")


# =====================================================================
# 10. CHAT PARTICIPANT & GROUP MEMBER PUBLIC_ID EXPOSURE
# =====================================================================

@pytest.mark.asyncio
async def test_conversation_participants_and_members_expose_public_id(
    test_client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
):
    """
    Verifies that all conversation detail, list, direct creation, and group member
    endpoints expose user.public_id (UUID v4) for safe public profile navigation,
    NOT numeric user_id or stringified user_id.
    """
    # 1. POST /api/v1/conversations/direct with recipient_public_id
    with auth_patch(user_a):
        res_create = await test_client.post(
            "/api/v1/conversations/direct",
            json={"recipient_public_id": str(user_b.public_id)},
        )
        assert res_create.status_code == 200
        create_data = res_create.json()
        assert create_data["other_participant"] is not None
        assert create_data["other_participant"]["user_id"] == user_b.user_id
        assert create_data["other_participant"]["public_id"] == str(user_b.public_id)
        assert create_data["other_participant"]["public_id"] != str(user_b.user_id)
        conv_id = create_data["conversation_id"]

    # 2. GET /api/v1/conversations/{conv_id}
    with auth_patch(user_a):
        res_detail = await test_client.get(f"/api/v1/conversations/{conv_id}")
        assert res_detail.status_code == 200
        detail_data = res_detail.json()
        assert detail_data["other_participant"]["public_id"] == str(user_b.public_id)
        assert detail_data["other_participant"]["user_id"] == user_b.user_id

    # 3. Messages expose sender_public_id
    with auth_patch(user_a):
        res_msg = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={"content": "Xin chào từ user A"},
        )
        assert res_msg.status_code == 201
        msg_data = res_msg.json()
        assert msg_data["sender_public_id"] == str(user_a.public_id)
        assert msg_data["sender_id"] == user_a.user_id

        res_msgs = await test_client.get(f"/api/v1/conversations/{conv_id}/messages")
        assert res_msgs.status_code == 200
        msgs_list = res_msgs.json()["items"]
        assert len(msgs_list) >= 1
        assert msgs_list[0]["sender_public_id"] == str(user_a.public_id)

    # 4. GET /api/v1/conversations (list - requires last_message_at for DIRECT)
    with auth_patch(user_a):
        res_list = await test_client.get("/api/v1/conversations")
        assert res_list.status_code == 200
        list_data = res_list.json()
        item = next(c for c in list_data["items"] if c["conversation_id"] == conv_id)
        assert item["other_participant"]["public_id"] == str(user_b.public_id)
        assert item["other_participant"]["user_id"] == user_b.user_id

    # 5. Group creation and member list
    with auth_patch(user_a):
        res_group = await test_client.post(
            "/api/v1/conversations/groups",
            json={"title": "Nhóm học tập PTIT", "initial_invitee_ids": [user_b.user_id]},
        )
        assert res_group.status_code == 201
        group_id = res_group.json()["conversation_id"]

        res_members = await test_client.get(f"/api/v1/conversations/groups/{group_id}/members")
        assert res_members.status_code == 200
        members = res_members.json()
        owner_member = next(m for m in members if m["user_id"] == user_a.user_id)
        assert owner_member["public_id"] == str(user_a.public_id)
        assert owner_member["public_id"] != str(user_a.user_id)

