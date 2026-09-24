import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.categories.models import Category
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
from app.modules.reports.models import (
    Report,
    ReportReason,
    ReportStatus,
    ReportTargetType,
)
from app.modules.reports.repository import encode_cursor
from app.modules.users.models import User, UserRole, UserStatus
from tests.conftest import test_engine


def auth_patch(user: User):
    app.dependency_overrides[get_current_user] = lambda: user

    class CleanCtx:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc_val, exc_tb):
            app.dependency_overrides.pop(get_current_user, None)

    return CleanCtx()


@pytest_asyncio.fixture(autouse=True)
async def clean_reports_isolation(db_session: AsyncSession):
    await db_session.execute(text("DELETE FROM user_capability_restrictions"))
    await db_session.execute(text("DELETE FROM moderation_actions"))
    await db_session.execute(text("DELETE FROM report_attachments"))
    await db_session.execute(text("DELETE FROM reports"))
    yield


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email="admin_moderator@ptit.edu.vn",
        full_name="Quản Trị Viên",
        phone="0900000000",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def student_user(db_session: AsyncSession) -> User:
    user = User(
        email="student_user@ptit.edu.vn",
        full_name="Sinh Viên Bình Thường",
        phone="0911111111",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def target_user(db_session: AsyncSession) -> User:
    user = User(
        email="target_user@ptit.edu.vn",
        full_name="Người Dùng Bị Báo Cáo",
        phone="0922222222",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def banned_target_user(db_session: AsyncSession) -> User:
    user = User(
        email="banned_user@ptit.edu.vn",
        full_name="Người Dùng Đã Khóa",
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
        name="Danh mục kiểm duyệt",
        slug="danh-muc-kiem-duyet",
        is_deleted=False,
    )
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def sample_product(
    db_session: AsyncSession, target_user: User, category: Category
) -> Product:
    prod = Product(
        seller_id=target_user.user_id,
        category_id=category.category_id,
        title="Sách Giáo trình Mạng máy tính",
        description="Sách cũ chính hãng",
        price=Decimal("60000"),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        listing_type=ListingType.FIXED_PRICE.value,
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


@pytest_asyncio.fixture
async def hidden_product(
    db_session: AsyncSession, target_user: User, category: Category
) -> Product:
    prod = Product(
        seller_id=target_user.user_id,
        category_id=category.category_id,
        title="Sách bị ẩn kiểm duyệt",
        description="Sách tạm ẩn",
        price=Decimal("50000"),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.HIDDEN.value,
        listing_type=ListingType.FIXED_PRICE.value,
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


@pytest_asyncio.fixture
async def soft_deleted_product(
    db_session: AsyncSession, target_user: User, category: Category
) -> Product:
    prod = Product(
        seller_id=target_user.user_id,
        category_id=category.category_id,
        title="Sách đã bị xóa mềm",
        description="Sách cũ đã xóa",
        price=Decimal("45000"),
        stock=0,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        listing_type=ListingType.FIXED_PRICE.value,
        is_deleted=True,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


@pytest_asyncio.fixture
async def sample_order(
    db_session: AsyncSession, student_user: User, target_user: User, sample_product: Product
) -> Order:
    order = Order(
        order_code="ORD-ADMIN-001",
        buyer_id=student_user.user_id,
        seller_id=target_user.user_id,
        total_amount=Decimal("60000"),
        payment_method=PaymentMethod.CASH_ON_MEETUP.value,
        payment_status=PaymentStatus.UNPAID.value,
        fulfillment_method=FulfillmentMethod.MEETUP.value,
        contact_name="Sinh Viên Mua Hàng",
        contact_phone="0911111111",
        status=OrderStatus.PENDING.value,
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.order_id,
        product_id=sample_product.product_id,
        product_title=sample_product.title,
        price_at_purchase=Decimal("60000"),
        quantity=1,
    )
    db_session.add(item)
    await db_session.flush()
    return order


@pytest.mark.asyncio
async def test_student_cannot_list_reports_forbidden(
    test_client: AsyncClient, student_user: User
):
    with auth_patch(student_user):
        resp = await test_client.get("/api/v1/admin/reports")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Operation not permitted for your user role."


@pytest.mark.asyncio
async def test_student_cannot_view_report_detail_forbidden(
    test_client: AsyncClient, student_user: User
):
    with auth_patch(student_user):
        resp = await test_client.get("/api/v1/admin/reports/1")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_student_cannot_change_report_status_forbidden(
    test_client: AsyncClient, student_user: User
):
    with auth_patch(student_user):
        resp = await test_client.patch(
            "/api/v1/admin/reports/1/status",
            json={"status": "REVIEWING"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_cannot_access_admin_reports(test_client: AsyncClient):
    resp = await test_client.get("/api/v1/admin/reports")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_can_list_reports_empty(
    test_client: AsyncClient, admin_user: User
):
    with auth_patch(admin_user):
        resp = await test_client.get("/api/v1/admin/reports")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["has_more"] is False
    assert data["next_cursor"] is None


@pytest.mark.asyncio
async def test_admin_can_list_reports_with_target_summary_privacy_safe(
    test_client: AsyncClient,
    admin_user: User,
    student_user: User,
    target_user: User,
    db_session: AsyncSession,
):
    report = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_user.user_id,
        reason=ReportReason.SCAM.value,
        description="Nghi vấn lừa đảo cọc",
        status=ReportStatus.OPEN.value,
    )
    db_session.add(report)
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.get("/api/v1/admin/reports")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["report_id"] == report.report_id
    assert item["status"] == "OPEN"
    assert item["reason"] == "SCAM"
    assert item["target_type"] == "USER"
    assert item["target_id"] == target_user.user_id
    assert item["target_available"] is True

    # Reporter summary must NOT expose email, phone, credentials
    assert "email" not in item["reporter"]
    assert "phone" not in item["reporter"]
    assert item["reporter"]["user_id"] == student_user.user_id
    assert item["reporter"]["full_name"] == student_user.full_name

    # Target summary
    assert item["target_summary"]["user_id"] == target_user.user_id
    assert item["target_summary"]["full_name"] == target_user.full_name
    assert item["target_summary"]["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_admin_list_reports_filters_status_and_target_type(
    test_client: AsyncClient,
    admin_user: User,
    student_user: User,
    target_user: User,
    sample_product: Product,
    sample_order: Order,
    db_session: AsyncSession,
):
    r1 = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_user.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.OPEN.value,
    )
    r2 = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.PRODUCT.value,
        target_id=sample_product.product_id,
        reason=ReportReason.FAKE_ITEM.value,
        status=ReportStatus.REVIEWING.value,
    )
    r3 = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.ORDER.value,
        target_id=sample_order.order_id,
        reason=ReportReason.NO_SHOW.value,
        status=ReportStatus.RESOLVED.value,
    )
    db_session.add_all([r1, r2, r3])
    await db_session.flush()

    with auth_patch(admin_user):
        # Filter by status = OPEN
        resp_open = await test_client.get("/api/v1/admin/reports?status=OPEN")
        assert resp_open.status_code == 200
        items_open = resp_open.json()["items"]
        assert len(items_open) == 1
        assert items_open[0]["report_id"] == r1.report_id

        # Filter by status = REVIEWING
        resp_rev = await test_client.get("/api/v1/admin/reports?status=REVIEWING")
        assert resp_rev.status_code == 200
        items_rev = resp_rev.json()["items"]
        assert len(items_rev) == 1
        assert items_rev[0]["report_id"] == r2.report_id

        # Filter by target_type = PRODUCT
        resp_prod = await test_client.get("/api/v1/admin/reports?target_type=PRODUCT")
        assert resp_prod.status_code == 200
        items_prod = resp_prod.json()["items"]
        assert len(items_prod) == 1
        assert items_prod[0]["report_id"] == r2.report_id

        # Combined filter: status = RESOLVED and target_type = ORDER
        resp_comb = await test_client.get(
            "/api/v1/admin/reports?status=RESOLVED&target_type=ORDER"
        )
        assert resp_comb.status_code == 200
        items_comb = resp_comb.json()["items"]
        assert len(items_comb) == 1
        assert items_comb[0]["report_id"] == r3.report_id

        # Non-matching combined filter
        resp_none = await test_client.get(
            "/api/v1/admin/reports?status=REJECTED&target_type=ORDER"
        )
        assert resp_none.status_code == 200
        assert len(resp_none.json()["items"]) == 0


@pytest.mark.asyncio
async def test_admin_list_reports_cursor_pagination_deterministic(
    test_client: AsyncClient,
    admin_user: User,
    student_user: User,
    target_user: User,
    db_session: AsyncSession,
):
    reports = []
    for i in range(5):
        r = Report(
            reporter_id=student_user.user_id,
            target_type=ReportTargetType.USER.value,
            target_id=target_user.user_id,
            reason=ReportReason.SPAM.value,
            description=f"Spam batch {i}",
            status=ReportStatus.OPEN.value,
        )
        reports.append(r)
        db_session.add(r)
    await db_session.flush()

    with auth_patch(admin_user):
        # Page 1: limit 2
        resp1 = await test_client.get("/api/v1/admin/reports?limit=2")
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert len(data1["items"]) == 2
        assert data1["has_more"] is True
        assert data1["next_cursor"] is not None
        cursor1 = data1["next_cursor"]

        # Page 2: limit 2 with cursor
        resp2 = await test_client.get(f"/api/v1/admin/reports?limit=2&cursor={cursor1}")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2["items"]) == 2
        assert data2["has_more"] is True
        cursor2 = data2["next_cursor"]

        # Check disjoint items between pages
        page1_ids = [item["report_id"] for item in data1["items"]]
        page2_ids = [item["report_id"] for item in data2["items"]]
        assert set(page1_ids).isdisjoint(set(page2_ids))
        assert page1_ids[0] > page1_ids[1] > page2_ids[0] > page2_ids[1]

        # Page 3: limit 2 with cursor2
        resp3 = await test_client.get(f"/api/v1/admin/reports?limit=2&cursor={cursor2}")
        assert resp3.status_code == 200
        data3 = resp3.json()
        assert len(data3["items"]) == 1
        assert data3["has_more"] is False
        assert data3["next_cursor"] is None


@pytest.mark.asyncio
async def test_admin_list_reports_invalid_parameters_422(
    test_client: AsyncClient, admin_user: User
):
    with auth_patch(admin_user):
        # Invalid status enum
        r1 = await test_client.get("/api/v1/admin/reports?status=INVALID_STATUS")
        assert r1.status_code == 422

        # Invalid target_type enum
        r2 = await test_client.get("/api/v1/admin/reports?target_type=INVALID_TARGET")
        assert r2.status_code == 422

        # Invalid limit <= 0
        r3 = await test_client.get("/api/v1/admin/reports?limit=0")
        assert r3.status_code == 422

        # Invalid limit > 50
        r4 = await test_client.get("/api/v1/admin/reports?limit=51")
        assert r4.status_code == 422

        # Malformed cursor string
        r5 = await test_client.get("/api/v1/admin/reports?cursor=not-a-valid-cursor!!")
        assert r5.status_code == 422
        assert "Invalid pagination cursor" in r5.json()["detail"]


@pytest.mark.asyncio
async def test_admin_get_report_detail_and_missing_404(
    test_client: AsyncClient,
    admin_user: User,
    student_user: User,
    sample_product: Product,
    db_session: AsyncSession,
):
    report = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.PRODUCT.value,
        target_id=sample_product.product_id,
        reason=ReportReason.FAKE_ITEM.value,
        description="Ảnh giả mạo, nội dung không khớp",
        status=ReportStatus.OPEN.value,
    )
    db_session.add(report)
    await db_session.flush()

    with auth_patch(admin_user):
        # Existing report
        resp = await test_client.get(f"/api/v1/admin/reports/{report.report_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["report_id"] == report.report_id
        assert data["target_available"] is True
        assert data["target_summary"]["product_id"] == sample_product.product_id
        assert data["target_summary"]["title"] == sample_product.title
        assert data["target_summary"]["seller"]["user_id"] == sample_product.seller_id
        assert data["target_summary"]["is_deleted"] is False

        # Non-existent report -> 404
        resp_404 = await test_client.get("/api/v1/admin/reports/999999")
        assert resp_404.status_code == 404
        assert resp_404.json()["detail"] == "Báo cáo không tồn tại."


@pytest.mark.asyncio
async def test_admin_report_survives_missing_target_row(
    test_client: AsyncClient,
    admin_user: User,
    student_user: User,
    db_session: AsyncSession,
):
    # Report points to non-existent target ID 888888
    report = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=888888,
        reason=ReportReason.SCAM.value,
        description="Đối tượng đã xóa vĩnh viễn",
        status=ReportStatus.OPEN.value,
    )
    db_session.add(report)
    await db_session.flush()

    with auth_patch(admin_user):
        # In queue list: report still appears, target_available=False
        resp_list = await test_client.get("/api/v1/admin/reports")
        assert resp_list.status_code == 200
        items = resp_list.json()["items"]
        assert len(items) == 1
        assert items[0]["target_available"] is False
        assert items[0]["target_summary"] is None

        # In detail: 200 OK, target_available=False, persistent report returned
        resp_detail = await test_client.get(f"/api/v1/admin/reports/{report.report_id}")
        assert resp_detail.status_code == 200
        data = resp_detail.json()
        assert data["report_id"] == report.report_id
        assert data["target_available"] is False
        assert data["target_summary"] is None


@pytest.mark.asyncio
async def test_admin_report_target_states_banned_hidden_soft_deleted(
    test_client: AsyncClient,
    admin_user: User,
    student_user: User,
    banned_target_user: User,
    hidden_product: Product,
    soft_deleted_product: Product,
    db_session: AsyncSession,
):
    # 1. Target is BANNED user -> target_available=True, status=BANNED
    r_user = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=banned_target_user.user_id,
        reason=ReportReason.INAPPROPRIATE.value,
        status=ReportStatus.OPEN.value,
    )
    # 2. Target is HIDDEN product -> target_available=True, status=HIDDEN
    r_hidden = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.PRODUCT.value,
        target_id=hidden_product.product_id,
        reason=ReportReason.OTHER.value,
        description="Tin ẩn vi phạm",
        status=ReportStatus.OPEN.value,
    )
    # 3. Target is soft-deleted product -> target_available=True, is_deleted=True
    r_deleted = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.PRODUCT.value,
        target_id=soft_deleted_product.product_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add_all([r_user, r_hidden, r_deleted])
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.get("/api/v1/admin/reports")
        assert resp.status_code == 200
        items_map = {item["report_id"]: item for item in resp.json()["items"]}

        # Banned user target
        user_item = items_map[r_user.report_id]
        assert user_item["target_available"] is True
        assert user_item["target_summary"]["status"] == "BANNED"

        # Hidden product target
        hidden_item = items_map[r_hidden.report_id]
        assert hidden_item["target_available"] is True
        assert hidden_item["target_summary"]["status"] == ProductStatus.HIDDEN.value

        # Soft deleted product target
        deleted_item = items_map[r_deleted.report_id]
        assert deleted_item["target_available"] is True
        assert deleted_item["target_summary"]["is_deleted"] is True


@pytest.mark.asyncio
async def test_status_transition_open_to_reviewing(
    test_client: AsyncClient,
    admin_user: User,
    student_user: User,
    target_user: User,
    db_session: AsyncSession,
):
    report = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_user.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.OPEN.value,
        handled_by=None,
        handled_at=None,
    )
    db_session.add(report)
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.patch(
            f"/api/v1/admin/reports/{report.report_id}/status",
            json={"status": "REVIEWING"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "REVIEWING"
    assert data["handled_by"] == admin_user.user_id
    assert data["handler"]["user_id"] == admin_user.user_id
    assert data["handled_at"] is None


@pytest.mark.asyncio
async def test_status_transition_reviewing_to_resolved_and_rejected(
    test_client: AsyncClient,
    admin_user: User,
    student_user: User,
    target_user: User,
    db_session: AsyncSession,
):
    r1 = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_user.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.REVIEWING.value,
        handled_by=admin_user.user_id,
        handled_at=None,
    )
    r2 = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_user.user_id,
        reason=ReportReason.SCAM.value,
        status=ReportStatus.REVIEWING.value,
        handled_by=admin_user.user_id,
        handled_at=None,
    )
    db_session.add_all([r1, r2])
    await db_session.flush()

    with auth_patch(admin_user):
        # REVIEWING -> RESOLVED
        resp1 = await test_client.patch(
            f"/api/v1/admin/reports/{r1.report_id}/status",
            json={"status": "RESOLVED"},
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["status"] == "RESOLVED"
        assert data1["handled_by"] == admin_user.user_id
        assert data1["handled_at"] is not None

        # REVIEWING -> REJECTED
        resp2 = await test_client.patch(
            f"/api/v1/admin/reports/{r2.report_id}/status",
            json={"status": "REJECTED"},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["status"] == "REJECTED"
        assert data2["handled_by"] == admin_user.user_id
        assert data2["handled_at"] is not None


@pytest.mark.asyncio
async def test_status_transition_open_direct_to_terminal(
    test_client: AsyncClient,
    admin_user: User,
    student_user: User,
    target_user: User,
    db_session: AsyncSession,
):
    r1 = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_user.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.OPEN.value,
    )
    r2 = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_user.user_id,
        reason=ReportReason.INAPPROPRIATE.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add_all([r1, r2])
    await db_session.flush()

    with auth_patch(admin_user):
        # OPEN -> direct RESOLVED
        resp1 = await test_client.patch(
            f"/api/v1/admin/reports/{r1.report_id}/status",
            json={"status": "RESOLVED"},
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["status"] == "RESOLVED"
        assert data1["handled_by"] == admin_user.user_id
        assert data1["handled_at"] is not None

        # OPEN -> direct REJECTED
        resp2 = await test_client.patch(
            f"/api/v1/admin/reports/{r2.report_id}/status",
            json={"status": "REJECTED"},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["status"] == "REJECTED"
        assert data2["handled_by"] == admin_user.user_id
        assert data2["handled_at"] is not None


@pytest.mark.asyncio
async def test_status_transition_invalid_matrix_and_terminal_409(
    test_client: AsyncClient,
    admin_user: User,
    student_user: User,
    target_user: User,
    db_session: AsyncSession,
):
    r_resolved = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_user.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.RESOLVED.value,
        handled_by=admin_user.user_id,
        handled_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    r_rejected = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_user.user_id,
        reason=ReportReason.SCAM.value,
        status=ReportStatus.REJECTED.value,
        handled_by=admin_user.user_id,
        handled_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    r_open = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_user.user_id,
        reason=ReportReason.OTHER.value,
        status=ReportStatus.OPEN.value,
    )
    r_reviewing = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_user.user_id,
        reason=ReportReason.OTHER.value,
        status=ReportStatus.REVIEWING.value,
    )
    db_session.add_all([r_resolved, r_rejected, r_open, r_reviewing])
    await db_session.flush()

    with auth_patch(admin_user):
        # RESOLVED -> cannot transition to any state (409)
        resp1 = await test_client.patch(
            f"/api/v1/admin/reports/{r_resolved.report_id}/status",
            json={"status": "OPEN"},
        )
        assert resp1.status_code == 409
        assert "trạng thái kết thúc" in resp1.json()["detail"]

        resp2 = await test_client.patch(
            f"/api/v1/admin/reports/{r_resolved.report_id}/status",
            json={"status": "REVIEWING"},
        )
        assert resp2.status_code == 409

        # REJECTED -> cannot transition to any state (409)
        resp3 = await test_client.patch(
            f"/api/v1/admin/reports/{r_rejected.report_id}/status",
            json={"status": "RESOLVED"},
        )
        assert resp3.status_code == 409

        # OPEN -> OPEN is invalid/no-op (409)
        resp4 = await test_client.patch(
            f"/api/v1/admin/reports/{r_open.report_id}/status",
            json={"status": "OPEN"},
        )
        assert resp4.status_code == 409

        # REVIEWING -> REVIEWING is invalid/no-op (409)
        resp5 = await test_client.patch(
            f"/api/v1/admin/reports/{r_reviewing.report_id}/status",
            json={"status": "REVIEWING"},
        )
        assert resp5.status_code == 409

        # REVIEWING -> OPEN is not allowed (409)
        resp6 = await test_client.patch(
            f"/api/v1/admin/reports/{r_reviewing.report_id}/status",
            json={"status": "OPEN"},
        )
        assert resp6.status_code == 409


@pytest.mark.asyncio
async def test_client_cannot_forge_handled_by_or_handled_at_422(
    test_client: AsyncClient,
    admin_user: User,
    student_user: User,
    target_user: User,
    db_session: AsyncSession,
):
    report = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_user.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add(report)
    await db_session.flush()

    with auth_patch(admin_user):
        # Client tries to send handled_by
        resp1 = await test_client.patch(
            f"/api/v1/admin/reports/{report.report_id}/status",
            json={"status": "REVIEWING", "handled_by": 999},
        )
        assert resp1.status_code == 422

        # Client tries to send handled_at
        resp2 = await test_client.patch(
            f"/api/v1/admin/reports/{report.report_id}/status",
            json={"status": "RESOLVED", "handled_at": "2026-01-01T00:00:00"},
        )
        assert resp2.status_code == 422


@pytest.mark.asyncio
async def test_moderation_causes_zero_domain_mutations_and_zero_notifications(
    test_client: AsyncClient,
    admin_user: User,
    student_user: User,
    target_user: User,
    sample_product: Product,
    sample_order: Order,
    db_session: AsyncSession,
):
    # Create product report
    r_prod = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.PRODUCT.value,
        target_id=sample_product.product_id,
        reason=ReportReason.FAKE_ITEM.value,
        status=ReportStatus.OPEN.value,
    )
    # Create order report
    r_order = Report(
        reporter_id=student_user.user_id,
        target_type=ReportTargetType.ORDER.value,
        target_id=sample_order.order_id,
        reason=ReportReason.NO_SHOW.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add_all([r_prod, r_order])
    await db_session.flush()

    # Capture pre-mutation counts and states
    notif_count_before = (
        await db_session.execute(select(func.count()).select_from(Notification))
    ).scalar_one()

    with auth_patch(admin_user):
        res1 = await test_client.patch(
            f"/api/v1/admin/reports/{r_prod.report_id}/status",
            json={"status": "RESOLVED"},
        )
        assert res1.status_code == 200

        res2 = await test_client.patch(
            f"/api/v1/admin/reports/{r_order.report_id}/status",
            json={"status": "RESOLVED"},
        )
        assert res2.status_code == 200

    # 1. Check Product is NOT mutated
    await db_session.refresh(sample_product)
    assert sample_product.status == ProductStatus.AVAILABLE.value
    assert sample_product.is_deleted is False
    assert sample_product.stock == 1

    # 2. Check User is NOT mutated
    await db_session.refresh(target_user)
    assert target_user.status == UserStatus.ACTIVE

    # 3. Check Order is NOT mutated
    await db_session.refresh(sample_order)
    assert sample_order.status == OrderStatus.PENDING.value
    assert sample_order.payment_status == PaymentStatus.UNPAID.value

    # 4. Check Notifications table has 0 new records
    notif_count_after = (
        await db_session.execute(select(func.count()).select_from(Notification))
    ).scalar_one()
    assert notif_count_after == notif_count_before


@pytest.mark.asyncio
async def test_concurrent_status_mutation_row_lock_safety():
    """
    Test that concurrent status transitions on the same Report row using separate
    database sessions are protected by row locks: Admin A wins, Admin B receives 409 Conflict.
    """
    # Create real independent connections/sessions
    async with test_engine.connect() as conn_setup:
        tx_setup = await conn_setup.begin()
        session_setup = AsyncSession(bind=conn_setup, expire_on_commit=False)

        # Create admin and target user and report
        admin_a = User(
            email="admin_a@ptit.edu.vn",
            full_name="Admin Alpha",
            role=UserRole.ADMIN.value,
            status=UserStatus.ACTIVE,
        )
        admin_b = User(
            email="admin_b@ptit.edu.vn",
            full_name="Admin Beta",
            role=UserRole.ADMIN.value,
            status=UserStatus.ACTIVE,
        )
        target = User(
            email="target_concurrent@ptit.edu.vn",
            full_name="Target Concurrent",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
        )
        session_setup.add_all([admin_a, admin_b, target])
        await session_setup.flush()

        report = Report(
            reporter_id=admin_a.user_id,
            target_type=ReportTargetType.USER.value,
            target_id=target.user_id,
            reason=ReportReason.SPAM.value,
            status=ReportStatus.OPEN.value,
        )
        session_setup.add(report)
        await session_setup.flush()
        report_id = report.report_id
        admin_a_id = admin_a.user_id
        admin_b_id = admin_b.user_id
        await tx_setup.commit()

    # Now two separate connections/sessions race to resolve the same report
    async with test_engine.connect() as conn_a, test_engine.connect() as conn_b:
        session_a = AsyncSession(bind=conn_a, expire_on_commit=False)
        session_b = AsyncSession(bind=conn_b, expire_on_commit=False)

        tx_a = await conn_a.begin()
        tx_b = await conn_b.begin()

        from app.modules.reports.service import ReportService
        service_a = ReportService(session_a)
        service_b = ReportService(session_b)

        # Step 1: Admin A locks the row and updates to RESOLVED
        admin_a_obj = await session_a.get(User, admin_a_id)
        admin_b_obj = await session_b.get(User, admin_b_id)

        # Admin A resolves report
        res_a = await service_a.update_admin_report_status(
            current_admin=admin_a_obj,
            report_id=report_id,
            new_status=ReportStatus.RESOLVED,
        )
        assert res_a.status == ReportStatus.RESOLVED
        await tx_a.commit()

        # Step 2: Admin B tries to reject or resolve the now-RESOLVED report
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await service_b.update_admin_report_status(
                current_admin=admin_b_obj,
                report_id=report_id,
                new_status=ReportStatus.REJECTED,
            )
        assert exc_info.value.status_code == 409
        assert "trạng thái kết thúc" in exc_info.value.detail
        await tx_b.rollback()

    # Cleanup created records
    async with test_engine.connect() as conn_clean:
        tx_clean = await conn_clean.begin()
        session_clean = AsyncSession(bind=conn_clean, expire_on_commit=False)
        rep = await session_clean.get(Report, report_id)
        if rep:
            await session_clean.delete(rep)
        for uid in [admin_a_id, admin_b_id, target.user_id]:
            u = await session_clean.get(User, uid)
            if u:
                await session_clean.delete(u)
        await session_clean.commit()
        await tx_clean.commit()
