from datetime import datetime, timezone
from decimal import Decimal
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.categories.models import Category
from app.modules.orders.models import FulfillmentMethod, Order, OrderItem, OrderStatus, PaymentMethod, PaymentStatus
from app.modules.products.models import ListingType, Product, ProductModerationStatus, ProductStatus
from app.modules.reports.models import Report, ReportReason, ReportStatus, ReportTargetType, ReportAttachment
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
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email="admin_history@ptit.edu.vn",
        full_name="Admin Moderator",
        phone="0901234567",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def student_a(db_session: AsyncSession) -> User:
    user = User(
        email="student_a@ptit.edu.vn",
        full_name="Nguyễn Văn A",
        phone="0911223344",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def student_b(db_session: AsyncSession) -> User:
    user = User(
        email="student_b@ptit.edu.vn",
        full_name="Trần Thị B",
        phone="0922334455",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def student_c(db_session: AsyncSession) -> User:
    user = User(
        email="student_c@ptit.edu.vn",
        full_name="Lê Văn C",
        phone="0933445566",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def order_ab(
    db_session: AsyncSession, student_a: User, student_b: User
) -> Order:
    cat = Category(name="Cat Order History", slug="cat-order-hist")
    db_session.add(cat)
    await db_session.flush()

    prod = Product(
        seller_id=student_b.user_id,
        category_id=cat.category_id,
        title="Product B",
        description="Sold by B",
        price=Decimal("500000"),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        moderation_status=ProductModerationStatus.CLEAR.value,
        listing_type=ListingType.FIXED_PRICE.value,
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()

    order = Order(
        order_code="ORD-HIST-01",
        buyer_id=student_a.user_id,
        seller_id=student_b.user_id,
        total_amount=Decimal("500000"),
        payment_method=PaymentMethod.CASH_ON_MEETUP.value,
        payment_status=PaymentStatus.UNPAID.value,
        fulfillment_method=FulfillmentMethod.MEETUP.value,
        contact_name="A",
        contact_phone="0911223344",
        status=OrderStatus.PENDING.value,
    )
    db_session.add(order)
    await db_session.flush()
    return order


@pytest.mark.asyncio
async def test_subject_report_history_authorization(
    test_client: AsyncClient,
    admin_user: User,
    student_a: User,
    student_b: User,
):
    """
    History query authorization:
    - Admin: 200
    - Student: 403
    - Unauthenticated: 401
    - Unknown user: 404
    """
    # 1. Unauthenticated
    resp = await test_client.get(f"/api/v1/admin/users/{student_a.user_id}/report-history")
    assert resp.status_code == 401

    # 2. Student
    with auth_patch(student_b):
        resp = await test_client.get(f"/api/v1/admin/users/{student_a.user_id}/report-history")
    assert resp.status_code == 403

    # 3. Unknown user
    with auth_patch(admin_user):
        resp = await test_client.get("/api/v1/admin/users/99999999/report-history")
    assert resp.status_code == 404

    # 4. Admin
    with auth_patch(admin_user):
        resp = await test_client.get(f"/api/v1/admin/users/{student_a.user_id}/report-history")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_subject_report_history_attribution(
    test_client: AsyncClient,
    admin_user: User,
    student_a: User,
    student_b: User,
    student_c: User,
    order_ab: Order,
    db_session: AsyncSession,
):
    """
    Test historical report subject derivation:
    A. Direct USER report: target_id == subject
    B. ORDER report: buyer reports seller -> in seller (B) history only
    C. PRODUCT report: product.seller == subject -> in seller (B) history
    D. Report submitted BY subject against another -> NOT in subject history!
    E. Corrupt/third-party ORDER report -> in neither party's history!
    """
    cat = Category(name="Cat Hist Prod", slug="cat-hist-prod")
    db_session.add(cat)
    await db_session.flush()

    prod_b = Product(
        seller_id=student_b.user_id,
        category_id=cat.category_id,
        title="Laptop of B",
        description="Seller is B",
        price=Decimal("1000000"),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        moderation_status=ProductModerationStatus.CLEAR.value,
        listing_type=ListingType.FIXED_PRICE.value,
        is_deleted=False,
    )
    db_session.add(prod_b)
    await db_session.flush()

    # 1. Direct USER report against B (reported by A)
    rep_user_b = Report(
        reporter_id=student_a.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=student_b.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.REJECTED.value,
    )

    # 2. ORDER report: A (buyer) reports order_ab -> counterparty is B (seller)
    rep_order_b = Report(
        reporter_id=student_a.user_id,
        target_type=ReportTargetType.ORDER.value,
        target_id=order_ab.order_id,
        reason=ReportReason.NO_SHOW.value,
        status=ReportStatus.OPEN.value,
    )

    # 3. PRODUCT report against prod_b (reported by C) -> seller is B
    rep_prod_b = Report(
        reporter_id=student_c.user_id,
        target_type=ReportTargetType.PRODUCT.value,
        target_id=prod_b.product_id,
        reason=ReportReason.FAKE_ITEM.value,
        status=ReportStatus.OPEN.value,
    )

    # 4. Report submitted BY B against C -> MUST NOT appear in B's history!
    rep_by_b_against_c = Report(
        reporter_id=student_b.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=student_c.user_id,
        reason=ReportReason.SCAM.value,
        status=ReportStatus.OPEN.value,
    )

    # 5. Corrupt ORDER report on order_ab submitted by C (neither buyer nor seller) -> should NOT appear in B or A's history
    rep_corrupt_order = Report(
        reporter_id=student_c.user_id,
        target_type=ReportTargetType.ORDER.value,
        target_id=order_ab.order_id,
        reason=ReportReason.OTHER.value,
        status=ReportStatus.OPEN.value,
    )

    db_session.add_all([rep_user_b, rep_order_b, rep_prod_b, rep_by_b_against_c, rep_corrupt_order])
    await db_session.flush()

    # Add an attachment to rep_user_b
    att = ReportAttachment(
        report_id=rep_user_b.report_id,
        url="https://res.cloudinary.com/ptit/image/upload/v1234/reports/att1.jpg",
        storage_key="reports/att1.jpg",
        original_name="evidence.jpg",
        mime_type="image/jpeg",
        size_bytes=1024,
    )
    db_session.add(att)
    await db_session.flush()

    with auth_patch(admin_user):
        resp_b = await test_client.get(f"/api/v1/admin/users/{student_b.user_id}/report-history")

    assert resp_b.status_code == 200
    data_b = resp_b.json()
    assert data_b["user_id"] == student_b.user_id
    # B should have exactly 3 reports: rep_user_b, rep_order_b, rep_prod_b
    assert data_b["total_count"] == 3
    report_ids = [item["report_id"] for item in data_b["items"]]
    assert rep_user_b.report_id in report_ids
    assert rep_order_b.report_id in report_ids
    assert rep_prod_b.report_id in report_ids
    assert rep_by_b_against_c.report_id not in report_ids
    assert rep_corrupt_order.report_id not in report_ids

    # Verify attachment count on rep_user_b
    item_user_b = next(it for it in data_b["items"] if it["report_id"] == rep_user_b.report_id)
    assert item_user_b["evidence_count"] == 1
    assert item_user_b["status"] == "REJECTED"


@pytest.mark.asyncio
async def test_subject_report_history_exclude_current_report(
    test_client: AsyncClient,
    admin_user: User,
    student_a: User,
    student_b: User,
    db_session: AsyncSession,
):
    """
    Current report being viewed must be excluded from previous report history.
    """
    rep1 = Report(
        reporter_id=student_a.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=student_b.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.REJECTED.value,
    )
    rep2 = Report(
        reporter_id=student_a.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=student_b.user_id,
        reason=ReportReason.SCAM.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add_all([rep1, rep2])
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.get(
            f"/api/v1/admin/users/{student_b.user_id}/report-history",
            params={"exclude_report_id": rep2.report_id},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] == 1
    assert data["items"][0]["report_id"] == rep1.report_id


@pytest.mark.asyncio
async def test_subject_report_history_cursor_pagination(
    test_client: AsyncClient,
    admin_user: User,
    student_a: User,
    student_b: User,
    db_session: AsyncSession,
):
    """
    Pagination keyset cursor is deterministic and pages correctly.
    """
    created_reports = []
    for i in range(5):
        rep = Report(
            reporter_id=student_a.user_id,
            target_type=ReportTargetType.USER.value,
            target_id=student_b.user_id,
            reason=ReportReason.OTHER.value,
            status=ReportStatus.OPEN.value,
        )
        db_session.add(rep)
        created_reports.append(rep)
    await db_session.flush()

    # Page 1: limit 2
    with auth_patch(admin_user):
        resp1 = await test_client.get(
            f"/api/v1/admin/users/{student_b.user_id}/report-history",
            params={"limit": 2},
        )
    assert resp1.status_code == 200
    p1 = resp1.json()
    assert len(p1["items"]) == 2
    assert p1["has_more"] is True
    cursor1 = p1["next_cursor"]
    assert cursor1 is not None

    # Page 2: limit 2 with cursor
    with auth_patch(admin_user):
        resp2 = await test_client.get(
            f"/api/v1/admin/users/{student_b.user_id}/report-history",
            params={"limit": 2, "cursor": cursor1},
        )
    assert resp2.status_code == 200
    p2 = resp2.json()
    assert len(p2["items"]) == 2
    # Ensure no overlap between pages
    ids1 = {x["report_id"] for x in p1["items"]}
    ids2 = {x["report_id"] for x in p2["items"]}
    assert ids1.isdisjoint(ids2)
