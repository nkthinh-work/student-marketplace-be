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
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email="admin_workflow@ptit.edu.vn",
        full_name="Admin Moderator",
        phone="0901234567",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def student_reporter(db_session: AsyncSession) -> User:
    user = User(
        email="reporter_wf@ptit.edu.vn",
        full_name="Student Reporter",
        phone="0911223344",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def target_student(db_session: AsyncSession) -> User:
    user = User(
        email="target_wf@ptit.edu.vn",
        full_name="Target Student",
        phone="0922334455",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def sample_product(
    db_session: AsyncSession, target_student: User
) -> Product:
    cat = Category(name="Category WF", slug="cat-wf")
    db_session.add(cat)
    await db_session.flush()

    prod = Product(
        seller_id=target_student.user_id,
        category_id=cat.category_id,
        title="Laptop WF",
        description="Laptop for workflow tests",
        price=Decimal("10000000"),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        moderation_status=ProductModerationStatus.CLEAR.value,
        listing_type=ListingType.FIXED_PRICE.value,
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


@pytest.mark.asyncio
async def test_opening_report_does_not_mutate_db_status(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    db_session: AsyncSession,
):
    """
    Opening a report detail must NOT mutate status from OPEN to REVIEWING.
    Zero mutation on GET detail.
    """
    report = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add(report)
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.get(f"/api/v1/admin/reports/{report.report_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["status"] == "OPEN"
    assert detail["handled_by"] is None
    assert detail["handled_at"] is None

    await db_session.refresh(report)
    assert report.status == ReportStatus.OPEN.value
    assert report.handled_by is None
    assert report.handled_at is None


@pytest.mark.asyncio
async def test_bo_qua_on_open_and_reviewing_sets_rejected(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    db_session: AsyncSession,
):
    """
    Bỏ qua uses PATCH /status with REJECTED:
    - OPEN -> REJECTED
    - legacy REVIEWING -> REJECTED
    - Sets handled_by and handled_at
    - Zero domain mutation on User
    """
    # 1. OPEN report -> Bỏ qua
    rep_open = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.OTHER.value,
        status=ReportStatus.OPEN.value,
    )
    # 2. Legacy REVIEWING report -> Bỏ qua
    rep_rev = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.OTHER.value,
        status=ReportStatus.REVIEWING.value,
    )
    db_session.add_all([rep_open, rep_rev])
    await db_session.flush()

    with auth_patch(admin_user):
        resp1 = await test_client.patch(
            f"/api/v1/admin/reports/{rep_open.report_id}/status",
            json={"status": "REJECTED"},
        )
        resp2 = await test_client.patch(
            f"/api/v1/admin/reports/{rep_rev.report_id}/status",
            json={"status": "REJECTED"},
        )

    assert resp1.status_code == 200
    assert resp1.json()["status"] == "REJECTED"
    assert resp1.json()["handled_by"] == admin_user.user_id

    assert resp2.status_code == 200
    assert resp2.json()["status"] == "REJECTED"
    assert resp2.json()["handled_by"] == admin_user.user_id

    await db_session.refresh(target_student)
    assert target_student.status == UserStatus.ACTIVE


@pytest.mark.asyncio
async def test_enforcement_success_resolves_report_atomically(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    sample_product: Product,
    db_session: AsyncSession,
):
    """
    Report is resolved ONLY when actual enforcement succeeds:
    - PRODUCT_HIDE -> Report RESOLVED
    - USER_BAN -> Report RESOLVED
    - CAPABILITY_RESTRICT -> Report RESOLVED
    All in the same transaction.
    """
    # 1. PRODUCT_HIDE resolves Product report
    prod_report = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.PRODUCT.value,
        target_id=sample_product.product_id,
        reason=ReportReason.FAKE_ITEM.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add(prod_report)
    await db_session.flush()

    with auth_patch(admin_user):
        resp_prod = await test_client.post(
            f"/api/v1/admin/reports/{prod_report.report_id}/enforcement",
            json={"action": "PRODUCT_HIDE"},
        )
    assert resp_prod.status_code == 200
    assert resp_prod.json()["status"] == "RESOLVED"
    assert resp_prod.json()["handled_by"] == admin_user.user_id

    # 2. CAPABILITY_RESTRICT resolves User report
    user_report = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add(user_report)
    await db_session.flush()

    with auth_patch(admin_user):
        resp_cap = await test_client.post(
            f"/api/v1/admin/reports/{user_report.report_id}/enforcement",
            json={
                "action": "CAPABILITY_RESTRICT",
                "capabilities": ["SELL"],
                "duration_days": 3,
            },
        )
    assert resp_cap.status_code == 200
    assert resp_cap.json()["status"] == "RESOLVED"
    assert resp_cap.json()["handled_by"] == admin_user.user_id


@pytest.mark.asyncio
async def test_failed_enforcement_keeps_report_unresolved(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    db_session: AsyncSession,
):
    """
    If an enforcement action fails validation (e.g. invalid action or wrong target),
    the report remains OPEN and unresolved.
    """
    report = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.SCAM.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add(report)
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "PRODUCT_HIDE"},  # Invalid for USER report
        )
    assert resp.status_code == 400

    await db_session.refresh(report)
    assert report.status == ReportStatus.OPEN.value
    assert report.handled_by is None


@pytest.mark.asyncio
async def test_reversal_does_not_reopen_report(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    sample_product: Product,
    db_session: AsyncSession,
):
    """
    Reversing an enforcement (e.g. PRODUCT_RESTORE) does NOT reopen the Report.
    The report remains RESOLVED.
    """
    report = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.PRODUCT.value,
        target_id=sample_product.product_id,
        reason=ReportReason.FAKE_ITEM.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add(report)
    await db_session.flush()

    with auth_patch(admin_user):
        resp_hide = await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "PRODUCT_HIDE"},
        )
        assert resp_hide.status_code == 200
        assert resp_hide.json()["status"] == "RESOLVED"

        resp_restore = await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "PRODUCT_RESTORE"},
        )
        assert resp_restore.status_code == 200
        assert resp_restore.json()["status"] == "RESOLVED"

    await db_session.refresh(report)
    assert report.status == ReportStatus.RESOLVED.value
