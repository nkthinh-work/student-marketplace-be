import uuid
from datetime import datetime, timezone
from decimal import Decimal
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.categories.models import Category
from app.modules.conversations.models import Conversation
from app.modules.notifications.models import Notification
from app.modules.orders.models import (
    FulfillmentMethod,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from app.modules.products.models import ListingType, Product, ProductStatus
from app.modules.reports.models import Report, ReportReason, ReportStatus, ReportTargetType
from app.modules.users.models import User, UserRole, UserStatus


def auth_patch(user: User):
    app.dependency_overrides[get_current_user] = lambda: user

    class CleanCtx:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc_val, exc_tb):
            app.dependency_overrides.pop(get_current_user, None)

    return CleanCtx()


@pytest_asyncio.fixture
async def reporter_user(db_session: AsyncSession) -> User:
    user = User(
        email="reporter_ptit@ptit.edu.vn",
        full_name="Nguyễn Văn Báo",
        phone="0911111111",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        email="target_user_ptit@ptit.edu.vn",
        full_name="Lê Vi Phạm",
        phone="0922222222",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def banned_user(db_session: AsyncSession) -> User:
    user = User(
        email="banned_target@ptit.edu.vn",
        full_name="Bị Khoá Tài Khoản",
        phone="0933333333",
        role=UserRole.STUDENT.value,
        status=UserStatus.BANNED,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def category(db_session: AsyncSession) -> Category:
    cat = Category(
        name="Giáo trình Reports",
        slug="giao-trinh-reports",
        is_deleted=False,
    )
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def available_product(
    db_session: AsyncSession, other_user: User, category: Category
) -> Product:
    prod = Product(
        seller_id=other_user.user_id,
        category_id=category.category_id,
        title="Sách C++ nâng cao",
        description="Mô tả sách C++",
        price=Decimal("80000"),
        stock=2,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        listing_type=ListingType.FIXED_PRICE.value,
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


@pytest_asyncio.fixture
async def sample_order(
    db_session: AsyncSession,
    other_user: User,
    reporter_user: User,
    available_product: Product,
) -> Order:
    order = Order(
        order_code="ORD-REP-1001",
        buyer_id=reporter_user.user_id,
        seller_id=other_user.user_id,
        total_amount=Decimal("80000"),
        status=OrderStatus.PENDING.value,
        payment_method=PaymentMethod.CASH_ON_MEETUP.value,
        payment_status=PaymentStatus.UNPAID.value,
        fulfillment_method=FulfillmentMethod.MEETUP.value,
        contact_name="Nguyễn Văn Báo",
        contact_phone="0911111111",
    )
    db_session.add(order)
    await db_session.flush()
    return order


# ============================================================
# 1. AUTHENTICATION & SECURITY SEMANTICS (401 / 403)
# ============================================================

@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(test_client: AsyncClient):
    resp = await test_client.post(
        "/api/v1/reports",
        json={"target_type": "USER", "target_public_id": str(uuid.uuid4()), "reason": "SPAM"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_banned_user_cannot_create_report(
    test_client: AsyncClient, banned_user: User, other_user: User
):
    with auth_patch(banned_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_public_id": str(other_user.public_id),
                "reason": "SPAM",
            },
        )
        assert resp.status_code == 403


# ============================================================
# 2. STRICT 422 VALIDATION SEMANTICS
# ============================================================

@pytest.mark.asyncio
async def test_invalid_target_type_returns_422(
    test_client: AsyncClient, reporter_user: User
):
    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={"target_type": "INVALID_TARGET", "target_id": 1, "reason": "SPAM"},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_reason_returns_422(
    test_client: AsyncClient, reporter_user: User
):
    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={"target_type": "USER", "target_public_id": str(uuid.uuid4()), "reason": "UNKNOWN_REASON"},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_incompatible_reason_for_user_returns_422(
    test_client: AsyncClient, reporter_user: User, other_user: User
):
    # FAKE_ITEM is for PRODUCT, not USER
    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_public_id": str(other_user.public_id),
                "reason": "FAKE_ITEM",
            },
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_incompatible_reason_for_product_returns_422(
    test_client: AsyncClient, reporter_user: User, available_product: Product
):
    # NO_SHOW is for ORDER, not PRODUCT
    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "PRODUCT",
                "target_id": available_product.product_id,
                "reason": "NO_SHOW",
            },
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_other_without_description_returns_422(
    test_client: AsyncClient, reporter_user: User, other_user: User
):
    with auth_patch(reporter_user):
        # Missing description
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_public_id": str(other_user.public_id),
                "reason": "OTHER",
            },
        )
        assert resp.status_code == 422

        # Whitespace-only description
        resp2 = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_public_id": str(other_user.public_id),
                "reason": "OTHER",
                "description": "   \n\t  ",
            },
        )
        assert resp2.status_code == 422


@pytest.mark.asyncio
async def test_description_over_1000_chars_returns_422(
    test_client: AsyncClient, reporter_user: User, other_user: User
):
    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_public_id": str(other_user.public_id),
                "reason": "SPAM",
                "description": "a" * 1001,
            },
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_forbidden_extra_fields_returns_422(
    test_client: AsyncClient, reporter_user: User, other_user: User
):
    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_public_id": str(other_user.public_id),
                "reason": "SPAM",
                "extra_forbidden_field": "injected",
            },
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_user_report_with_numeric_target_id_returns_422(
    test_client: AsyncClient, reporter_user: User, other_user: User
):
    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_id": other_user.user_id,
                "reason": "SPAM",
            },
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_user_report_with_both_target_id_and_target_public_id_returns_422(
    test_client: AsyncClient, reporter_user: User, other_user: User
):
    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_id": other_user.user_id,
                "target_public_id": str(other_user.public_id),
                "reason": "SPAM",
            },
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_product_report_with_target_public_id_returns_422(
    test_client: AsyncClient, reporter_user: User, available_product: Product
):
    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "PRODUCT",
                "target_id": available_product.product_id,
                "target_public_id": str(uuid.uuid4()),
                "reason": "FAKE_ITEM",
            },
        )
        assert resp.status_code == 422


# ============================================================
# 3. USER TARGET SEMANTICS (400, 404, 201)
# ============================================================

@pytest.mark.asyncio
async def test_self_user_report_returns_400(
    test_client: AsyncClient, reporter_user: User
):
    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_public_id": str(reporter_user.public_id),
                "reason": "SPAM",
            },
        )
        assert resp.status_code == 400
        assert "chính mình" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_nonexistent_user_returns_404(
    test_client: AsyncClient, reporter_user: User
):
    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_public_id": str(uuid.uuid4()),
                "reason": "SPAM",
            },
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_inactive_or_banned_user_target_returns_404(
    test_client: AsyncClient,
    reporter_user: User,
    banned_user: User,
    db_session: AsyncSession,
):
    # Reuses canonical Public Profile / user lookup semantics (only ACTIVE users can be looked up)
    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_public_id": str(banned_user.public_id),
                "reason": "SPAM",
            },
        )
        assert resp.status_code == 404

        # Test INACTIVE user
        inactive_user = User(
            email="inactive_user_ptit@ptit.edu.vn",
            full_name="Nguyễn Chưa Kích Hoạt",
            phone="0944444444",
            role=UserRole.STUDENT.value,
            status=UserStatus.INACTIVE,
        )
        db_session.add(inactive_user)
        await db_session.flush()

        resp_inactive = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_public_id": str(inactive_user.public_id),
                "reason": "SPAM",
            },
        )
        assert resp_inactive.status_code == 404


@pytest.mark.asyncio
async def test_valid_user_report_success_201(
    test_client: AsyncClient, reporter_user: User, other_user: User
):
    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_public_id": str(other_user.public_id),
                "reason": "SCAM",
                "description": "Người dùng có dấu hiệu lừa đảo chuyển khoản",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["target_type"] == "USER"
        assert data["target_id"] == other_user.user_id
        assert data["reason"] == "SCAM"
        assert data["status"] == "OPEN"
        assert "reporter_id" not in data
        assert "handled_by" not in data


# ============================================================
# 4. PRODUCT TARGET SEMANTICS (400, 404, 201)
# ============================================================

@pytest.mark.asyncio
async def test_own_product_report_returns_400(
    test_client: AsyncClient,
    reporter_user: User,
    category: Category,
    db_session: AsyncSession,
):
    own_prod = Product(
        seller_id=reporter_user.user_id,
        category_id=category.category_id,
        title="Sách của chính mình",
        price=Decimal("50000"),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        listing_type=ListingType.FIXED_PRICE.value,
        is_deleted=False,
    )
    db_session.add(own_prod)
    await db_session.flush()

    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "PRODUCT",
                "target_id": own_prod.product_id,
                "reason": "FAKE_ITEM",
            },
        )
        assert resp.status_code == 400
        assert "chính mình" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_nonexistent_product_returns_404(
    test_client: AsyncClient, reporter_user: User
):
    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "PRODUCT",
                "target_id": 99999999,
                "reason": "FAKE_ITEM",
            },
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_soft_deleted_product_returns_404(
    test_client: AsyncClient,
    reporter_user: User,
    category: Category,
    other_user: User,
    db_session: AsyncSession,
):
    del_prod = Product(
        seller_id=other_user.user_id,
        category_id=category.category_id,
        title="Sách đã bị xoá",
        price=Decimal("50000"),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        listing_type=ListingType.FIXED_PRICE.value,
        is_deleted=True,
    )
    db_session.add(del_prod)
    await db_session.flush()

    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "PRODUCT",
                "target_id": del_prod.product_id,
                "reason": "FAKE_ITEM",
            },
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_hidden_product_returns_404_for_non_owner(
    test_client: AsyncClient,
    reporter_user: User,
    category: Category,
    other_user: User,
    db_session: AsyncSession,
):
    hidden_prod = Product(
        seller_id=other_user.user_id,
        category_id=category.category_id,
        title="Sách bị ẩn",
        price=Decimal("50000"),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.HIDDEN.value,
        approval_status="APPROVED",
        listing_type=ListingType.FIXED_PRICE.value,
        is_deleted=False,
    )
    db_session.add(hidden_prod)
    await db_session.flush()

    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "PRODUCT",
                "target_id": hidden_prod.product_id,
                "reason": "FAKE_ITEM",
            },
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sold_out_product_is_reportable(
    test_client: AsyncClient,
    reporter_user: User,
    category: Category,
    other_user: User,
    db_session: AsyncSession,
):
    sold_out_prod = Product(
        seller_id=other_user.user_id,
        category_id=category.category_id,
        title="Sách đã bán hết",
        price=Decimal("50000"),
        stock=0,
        reserved_stock=0,
        status=ProductStatus.SOLD_OUT.value,
        approval_status="APPROVED",
        listing_type=ListingType.FIXED_PRICE.value,
        is_deleted=False,
    )
    db_session.add(sold_out_prod)
    await db_session.flush()

    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "PRODUCT",
                "target_id": sold_out_prod.product_id,
                "reason": "FAKE_ITEM",
                "description": "Sản phẩm này là hàng nhái",
            },
        )
        assert resp.status_code == 201


@pytest.mark.asyncio
async def test_valid_product_report_success_201(
    test_client: AsyncClient, reporter_user: User, available_product: Product
):
    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "PRODUCT",
                "target_id": available_product.product_id,
                "reason": "FAKE_ITEM",
                "description": "Sách photo vi phạm bản quyền",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["target_type"] == "PRODUCT"
        assert data["target_id"] == available_product.product_id
        assert data["reason"] == "FAKE_ITEM"
        assert data["status"] == "OPEN"


# ============================================================
# 5. ORDER TARGET SEMANTICS (404, 201)
# ============================================================

@pytest.mark.asyncio
async def test_nonexistent_order_returns_404(
    test_client: AsyncClient, reporter_user: User
):
    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "ORDER",
                "target_id": 99999999,
                "reason": "NO_SHOW",
            },
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_order_outsider_returns_404(
    test_client: AsyncClient,
    sample_order: Order,
    db_session: AsyncSession,
):
    # A third user who is neither buyer nor seller
    outsider = User(
        email="outsider_ptit@ptit.edu.vn",
        full_name="Người Ngoài Cuộc",
        phone="0955555555",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(outsider)
    await db_session.flush()

    with auth_patch(outsider):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "ORDER",
                "target_id": sample_order.order_id,
                "reason": "NO_SHOW",
            },
        )
        assert resp.status_code == 404
        assert "Không tìm thấy đơn hàng" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_order_buyer_and_seller_can_report(
    test_client: AsyncClient,
    sample_order: Order,
    reporter_user: User,
    other_user: User,
):
    # Reporter is buyer -> can report
    with auth_patch(reporter_user):
        resp_buyer = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "ORDER",
                "target_id": sample_order.order_id,
                "reason": "NO_SHOW",
                "description": "Người bán không tới điểm hẹn ký túc xá",
            },
        )
        assert resp_buyer.status_code == 201

    # Other user is seller -> can also report the same order
    with auth_patch(other_user):
        resp_seller = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "ORDER",
                "target_id": sample_order.order_id,
                "reason": "SCAM",
                "description": "Người mua không thanh toán tiền mặt",
            },
        )
        assert resp_seller.status_code == 201


# ============================================================
# 6. ACTIVE DUPLICATE REPORT CHECK (409)
# ============================================================

@pytest.mark.asyncio
async def test_duplicate_active_report_returns_409(
    test_client: AsyncClient, reporter_user: User, other_user: User
):
    with auth_patch(reporter_user):
        # First report -> 201
        resp1 = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_public_id": str(other_user.public_id),
                "reason": "SPAM",
            },
        )
        assert resp1.status_code == 201

        # Second report while first is OPEN -> 409
        resp2 = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_public_id": str(other_user.public_id),
                "reason": "INAPPROPRIATE",
            },
        )
        assert resp2.status_code == 409
        assert "đang được xử lý" in resp2.json()["detail"]


@pytest.mark.asyncio
async def test_can_report_again_after_resolved_or_rejected(
    test_client: AsyncClient,
    reporter_user: User,
    other_user: User,
    db_session: AsyncSession,
):
    # Pre-existing report that has been RESOLVED
    old_report = Report(
        reporter_id=reporter_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=other_user.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.RESOLVED.value,
    )
    db_session.add(old_report)
    await db_session.flush()

    with auth_patch(reporter_user):
        # Should be allowed to report again
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_public_id": str(other_user.public_id),
                "reason": "SCAM",
            },
        )
        assert resp.status_code == 201


# ============================================================
# 7. RESPONSE PRIVACY & DATABASE INTEGRITY
# ============================================================

@pytest.mark.asyncio
async def test_response_privacy_and_db_persistence(
    test_client: AsyncClient,
    reporter_user: User,
    available_product: Product,
    db_session: AsyncSession,
):
    with auth_patch(reporter_user):
        resp = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "PRODUCT",
                "target_id": available_product.product_id,
                "reason": "OTHER",
                "description": "Nội dung mô tả có thông tin cá nhân của người khác",
            },
        )
        assert resp.status_code == 201
        data = resp.json()

        # Check that internal moderation fields are NOT leaked in response
        assert "reporter_id" not in data
        assert "handled_by" not in data
        assert "handled_at" not in data

        report_id = data["report_id"]
        # Verify in database that reporter_id was correctly saved
        stmt = select(Report).where(Report.report_id == report_id)
        res = await db_session.execute(stmt)
        db_report = res.scalar_one_or_none()
        assert db_report is not None
        assert db_report.reporter_id == reporter_user.user_id
        assert db_report.status == ReportStatus.OPEN.value
        assert db_report.handled_by is None
        assert db_report.handled_at is None


# ============================================================
# 8. STRICT NO-SIDE-EFFECTS GUARANTEE (Correction 14)
# ============================================================

@pytest.mark.asyncio
async def test_report_creation_has_no_side_effects(
    test_client: AsyncClient,
    reporter_user: User,
    other_user: User,
    available_product: Product,
    sample_order: Order,
    db_session: AsyncSession,
):
    # Snapshot baseline counts and values
    initial_user_status = other_user.status
    initial_product_status = available_product.status
    initial_product_stock = available_product.stock
    initial_product_reserved = available_product.reserved_stock
    initial_product_deleted = available_product.is_deleted
    initial_order_status = sample_order.status
    initial_order_payment_status = sample_order.payment_status

    initial_notif_count = await db_session.scalar(select(func.count(Notification.notification_id))) or 0

    with auth_patch(reporter_user):
        # Report user
        await test_client.post(
            "/api/v1/reports",
            json={"target_type": "USER", "target_public_id": str(other_user.public_id), "reason": "SPAM"},
        )
        # Report product
        await test_client.post(
            "/api/v1/reports",
            json={"target_type": "PRODUCT", "target_id": available_product.product_id, "reason": "FAKE_ITEM"},
        )
        # Report order
        await test_client.post(
            "/api/v1/reports",
            json={"target_type": "ORDER", "target_id": sample_order.order_id, "reason": "NO_SHOW"},
        )

    # Re-fetch entities from DB
    await db_session.refresh(other_user)
    await db_session.refresh(available_product)
    await db_session.refresh(sample_order)

    # 1. Target user status unchanged
    assert other_user.status == initial_user_status

    # 2. Target product domain state unchanged
    assert available_product.status == initial_product_status
    assert available_product.stock == initial_product_stock
    assert available_product.reserved_stock == initial_product_reserved
    assert available_product.is_deleted == initial_product_deleted

    # 3. Target order domain state unchanged
    assert sample_order.status == initial_order_status
    assert sample_order.payment_status == initial_order_payment_status

    # 4. Reporter and target users receive zero notifications on report creation (only active admins are notified)
    user_notifs = await db_session.execute(
        select(Notification).where(
            Notification.user_id.in_([reporter_user.user_id, other_user.user_id])
        )
    )
    assert len(user_notifs.scalars().all()) == 0
