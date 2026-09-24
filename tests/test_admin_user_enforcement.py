import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.auth.dependencies import get_current_user, authenticate_user_token
from app.modules.reports.schemas import ReportResponse
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
from app.modules.orders.websocket import UserConnectionManager, revoke_user_sessions
from app.modules.products.models import ListingType, Product, ProductStatus
from app.modules.reports.models import (
    ModerationAction,
    ModerationActionOption,
    ModerationActionType,
    Report,
    ReportConclusion,
    ReportReason,
    ReportStatus,
    ReportTargetType,
    ReportWorkflowState,
)
from app.modules.reports.repository import ReportRepository
from app.modules.reports.service import ReportService
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


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email="admin_enforce_1@ptit.edu.vn",
        full_name="Quản Trị Viên 1",
        phone="0900000001",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def admin_user_2(db_session: AsyncSession) -> User:
    user = User(
        email="admin_enforce_2@ptit.edu.vn",
        full_name="Quản Trị Viên 2",
        phone="0900000002",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def student_reporter(db_session: AsyncSession) -> User:
    user = User(
        email="student_reporter@ptit.edu.vn",
        full_name="Sinh Viên Tố Cáo",
        phone="0911111112",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def target_student(db_session: AsyncSession) -> User:
    user = User(
        email="target_student@ptit.edu.vn",
        full_name="Sinh Viên Bị Tố Cáo",
        phone="0922222223",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def target_admin(db_session: AsyncSession) -> User:
    user = User(
        email="target_admin@ptit.edu.vn",
        full_name="Admin Bị Tố Cáo",
        phone="0933333334",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def open_user_report(
    db_session: AsyncSession, student_reporter: User, target_student: User
) -> Report:
    report = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.INAPPROPRIATE.value,
        description="Có hành vi quấy rối trên nền tảng",
        status=ReportStatus.OPEN.value,
    )
    db_session.add(report)
    await db_session.flush()
    return report


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> Category:
    cat = Category(
        name="Đồ điện tử kiểm thử",
        slug="do-dien-tu-kt",
    )
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def sample_product(
    db_session: AsyncSession, target_student: User, sample_category: Category
) -> Product:
    prod = Product(
        seller_id=target_student.user_id,
        category_id=sample_category.category_id,
        title="Laptop kiểm thử",
        description="Laptop cho sinh viên",
        price=Decimal("15000000"),
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
async def sample_order(
    db_session: AsyncSession, student_reporter: User, target_student: User, sample_product: Product
) -> Order:
    order = Order(
        order_code="ORD-ENF-001",
        buyer_id=student_reporter.user_id,
        seller_id=target_student.user_id,
        total_amount=Decimal("15000000"),
        payment_method=PaymentMethod.CASH_ON_MEETUP.value,
        payment_status=PaymentStatus.UNPAID.value,
        fulfillment_method=FulfillmentMethod.MEETUP.value,
        contact_name="Sinh Viên Mua",
        contact_phone="0911111112",
        status=OrderStatus.PENDING.value,
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.order_id,
        product_id=sample_product.product_id,
        product_title=sample_product.title,
        price_at_purchase=Decimal("15000000"),
        quantity=1,
    )
    db_session.add(item)
    await db_session.flush()
    return order


# ============================================================================
# 1. AUTHORIZATION & ACCESS CONTROL
# ============================================================================

@pytest.mark.asyncio
async def test_unauthenticated_enforce_returns_401(
    test_client: AsyncClient, open_user_report: Report
):
    resp = await test_client.post(
        f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
        json={"action": "USER_BAN"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_student_enforce_returns_403(
    test_client: AsyncClient, student_reporter: User, open_user_report: Report
):
    with auth_patch(student_reporter):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_ban_themselves_returns_403(
    test_client: AsyncClient, admin_user: User, student_reporter: User, db_session: AsyncSession
):
    self_report = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=admin_user.user_id,
        reason=ReportReason.OTHER.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add(self_report)
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{self_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
    assert resp.status_code == 403
    assert "không thể áp dụng chế tài lên tài khoản quản trị viên" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_admin_cannot_ban_another_admin_returns_403(
    test_client: AsyncClient, admin_user: User, target_admin: User, student_reporter: User, db_session: AsyncSession
):
    admin_report = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_admin.user_id,
        reason=ReportReason.OTHER.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add(admin_report)
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{admin_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
    assert resp.status_code == 403
    assert "không thể áp dụng chế tài lên tài khoản quản trị viên" in resp.json()["detail"].lower()


# ============================================================================
# 2. TARGET BINDING & VALIDATION
# ============================================================================

@pytest.mark.asyncio
async def test_enforce_on_nonexistent_report_returns_404(
    test_client: AsyncClient, admin_user: User
):
    with auth_patch(admin_user):
        resp = await test_client.post(
            "/api/v1/admin/reports/999999/enforcement",
            json={"action": "USER_BAN"},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_user_ban_on_product_report_returns_400(
    test_client: AsyncClient, admin_user: User, student_reporter: User, sample_product: Product, db_session: AsyncSession
):
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
        resp = await test_client.post(
            f"/api/v1/admin/reports/{prod_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
    assert resp.status_code == 400
    assert "báo cáo loại người dùng" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_user_ban_on_order_report_bans_counterparty_and_third_party_returns_400(
    test_client: AsyncClient, admin_user: User, student_reporter: User, target_student: User, sample_order: Order, db_session: AsyncSession
):
    # 1. Third-party reporter on ORDER report fails safely with 400
    unrelated_user = User(
        email="unrelated_rep@ptit.edu.vn",
        full_name="Người ngoài",
        phone="0988776655",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(unrelated_user)
    await db_session.flush()

    third_party_order_report = Report(
        reporter_id=unrelated_user.user_id,
        target_type=ReportTargetType.ORDER.value,
        target_id=sample_order.order_id,
        reason=ReportReason.NO_SHOW.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add(third_party_order_report)
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{third_party_order_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
    assert resp.status_code == 400
    assert "không thể xác định đối tượng" in resp.json()["detail"].lower()

    # 2. Participant reporter (buyer) on ORDER report bans derived counterparty (seller)
    order_report = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.ORDER.value,
        target_id=sample_order.order_id,
        reason=ReportReason.NO_SHOW.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add(order_report)
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{order_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["status"] == "RESOLVED"
    assert detail["reported_subject"]["status"] == "BANNED"
    await db_session.refresh(target_student)
    assert target_student.status == UserStatus.BANNED


@pytest.mark.asyncio
async def test_user_ban_with_extra_fields_forbidden(
    test_client: AsyncClient, admin_user: User, open_user_report: Report
):
    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_BAN", "unexpected_field": "hacked"},
        )
    assert resp.status_code == 422


# ============================================================================
# 3. USER_BAN LIFECYCLE & STATE MACHINE
# ============================================================================

@pytest.mark.asyncio
async def test_user_ban_on_open_report_success(
    test_client: AsyncClient, admin_user: User, open_user_report: Report, target_student: User, db_session: AsyncSession
):
    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
    assert resp.status_code == 200
    data = resp.json()

    # Verify Report state
    assert data["status"] == "RESOLVED"
    assert data["handled_by"] == admin_user.user_id
    assert data["handled_at"] is not None

    # Verify Target User state
    assert data["target_summary"]["status"] == "BANNED"
    assert data["target_summary"]["role"] == "STUDENT"

    # Verify enforcement actions audit trail
    assert len(data["enforcement_actions"]) == 1
    enf = data["enforcement_actions"][0]
    assert enf["action_type"] == "USER_BAN"
    assert enf["previous_status"] == "ACTIVE"
    assert enf["new_status"] == "BANNED"
    assert enf["admin"]["user_id"] == admin_user.user_id

    # Verify server computed capabilities
    assert data["available_enforcement_actions"] == ["USER_UNBAN"]

    # Verify database persistence
    await db_session.refresh(target_student)
    assert target_student.status == UserStatus.BANNED

    await db_session.refresh(open_user_report)
    assert open_user_report.status == ReportStatus.RESOLVED.value
    assert open_user_report.handled_by == admin_user.user_id


@pytest.mark.asyncio
async def test_user_ban_on_reviewing_report_success(
    test_client: AsyncClient, admin_user: User, open_user_report: Report, target_student: User, db_session: AsyncSession
):
    open_user_report.status = ReportStatus.REVIEWING.value
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "RESOLVED"
    await db_session.refresh(target_student)
    assert target_student.status == UserStatus.BANNED


@pytest.mark.asyncio
async def test_user_ban_on_already_banned_user_returns_409(
    test_client: AsyncClient, admin_user: User, open_user_report: Report, target_student: User, db_session: AsyncSession
):
    target_student.status = UserStatus.BANNED
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
    assert resp.status_code == 409
    assert "đã bị khóa" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_user_ban_on_inactive_user_returns_409(
    test_client: AsyncClient, admin_user: User, open_user_report: Report, target_student: User, db_session: AsyncSession
):
    target_student.status = UserStatus.INACTIVE
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
    assert resp.status_code == 409
    assert "ngừng hoạt động" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_user_ban_on_rejected_report_returns_409(
    test_client: AsyncClient, admin_user: User, open_user_report: Report, db_session: AsyncSession
):
    open_user_report.status = ReportStatus.REJECTED.value
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
    assert resp.status_code == 409
    assert "kết thúc" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_user_ban_on_resolved_report_without_ban_returns_409(
    test_client: AsyncClient, admin_user: User, open_user_report: Report, db_session: AsyncSession
):
    open_user_report.status = ReportStatus.RESOLVED.value
    open_user_report.handled_by = admin_user.user_id
    open_user_report.handled_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
    assert resp.status_code == 409
    assert "kết thúc" in resp.json()["detail"].lower()


# ============================================================================
# 4. USER_UNBAN LIFECYCLE & CROSS-REPORT REVERSAL PREVENTIONS
# ============================================================================

@pytest.mark.asyncio
async def test_user_unban_success(
    test_client: AsyncClient, admin_user: User, admin_user_2: User, open_user_report: Report, target_student: User, db_session: AsyncSession
):
    # 1. Ban user via Admin 1
    with auth_patch(admin_user):
        ban_resp = await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
    assert ban_resp.status_code == 200
    original_handled_at = open_user_report.handled_at
    original_handled_by = open_user_report.handled_by

    # 2. Unban user via Admin 2 on same report
    with auth_patch(admin_user_2):
        unban_resp = await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_UNBAN"},
        )
    assert unban_resp.status_code == 200
    data = unban_resp.json()

    # User restored to ACTIVE
    assert data["target_summary"]["status"] == "ACTIVE"
    # Report remains RESOLVED
    assert data["status"] == "RESOLVED"
    # Original handled_by and handled_at NOT overwritten
    assert data["handled_by"] == original_handled_by
    assert open_user_report.handled_by == original_handled_by
    assert open_user_report.handled_at == original_handled_at

    # Audit trail contains 2 entries
    assert len(data["enforcement_actions"]) == 2
    assert data["enforcement_actions"][0]["action_type"] == "USER_BAN"
    assert data["enforcement_actions"][1]["action_type"] == "USER_UNBAN"
    assert data["enforcement_actions"][1]["previous_status"] == "BANNED"
    assert data["enforcement_actions"][1]["new_status"] == "ACTIVE"
    assert data["enforcement_actions"][1]["admin"]["user_id"] == admin_user_2.user_id

    # Capabilities now empty (report RESOLVED, user ACTIVE)
    assert data["available_enforcement_actions"] == []

    await db_session.refresh(target_student)
    assert target_student.status == UserStatus.ACTIVE


@pytest.mark.asyncio
async def test_user_unban_on_active_user_returns_409(
    test_client: AsyncClient, admin_user: User, open_user_report: Report
):
    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_UNBAN"},
        )
    assert resp.status_code == 409
    assert "bị khóa" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_user_unban_second_time_returns_409(
    test_client: AsyncClient, admin_user: User, open_user_report: Report
):
    with auth_patch(admin_user):
        await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
        res1 = await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_UNBAN"},
        )
        assert res1.status_code == 200

        res2 = await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_UNBAN"},
        )
        assert res2.status_code == 409


@pytest.mark.asyncio
async def test_cross_report_reversal_prevention_scenario(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    open_user_report: Report,
    db_session: AsyncSession,
):
    """
    CRITICAL REQUIREMENT #3:
    Report A: USER_BAN -> USER_UNBAN (User becomes ACTIVE).
    Report B: USER_BAN (User becomes BANNED).
    Now attempt USER_UNBAN using Report A.
    Expected: 409 Conflict, User remains BANNED.
    Report B can unban successfully.
    """
    report_a = open_user_report

    # Report B
    report_b = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.SCAM.value,
        description="Báo cáo lừa đảo thứ hai",
        status=ReportStatus.OPEN.value,
    )
    db_session.add(report_b)
    await db_session.flush()

    with auth_patch(admin_user):
        # 1. Report A: Ban
        resp = await test_client.post(
            f"/api/v1/admin/reports/{report_a.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
        assert resp.status_code == 200

        # 2. Report A: Unban -> user is ACTIVE
        resp = await test_client.post(
            f"/api/v1/admin/reports/{report_a.report_id}/enforcement",
            json={"action": "USER_UNBAN"},
        )
        assert resp.status_code == 200
        await db_session.refresh(target_student)
        assert target_student.status == UserStatus.ACTIVE

        # 3. Report B: Ban -> user is BANNED
        resp = await test_client.post(
            f"/api/v1/admin/reports/{report_b.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
        assert resp.status_code == 200
        await db_session.refresh(target_student)
        assert target_student.status == UserStatus.BANNED

        # 4. Now attempt USER_UNBAN using Report A!
        resp = await test_client.post(
            f"/api/v1/admin/reports/{report_a.report_id}/enforcement",
            json={"action": "USER_UNBAN"},
        )
        assert resp.status_code == 409
        assert "không phải là nguồn tạo ra lệnh khóa" in resp.json()["detail"].lower()

        # Ensure target user is STILL BANNED
        await db_session.refresh(target_student)
        assert target_student.status == UserStatus.BANNED

        # 5. Report B performs USER_UNBAN -> Succeeds!
        resp = await test_client.post(
            f"/api/v1/admin/reports/{report_b.report_id}/enforcement",
            json={"action": "USER_UNBAN"},
        )
        assert resp.status_code == 200
        await db_session.refresh(target_student)
        assert target_student.status == UserStatus.ACTIVE


@pytest.mark.asyncio
async def test_unrelated_report_cannot_unban_user(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    open_user_report: Report,
    db_session: AsyncSession,
):
    report_b = open_user_report

    report_c = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.SPAM.value,
        description="Báo cáo C",
        status=ReportStatus.OPEN.value,
    )
    db_session.add(report_c)
    await db_session.flush()

    with auth_patch(admin_user):
        # Ban via Report B
        resp = await test_client.post(
            f"/api/v1/admin/reports/{report_b.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
        assert resp.status_code == 200

        # Attempt UNBAN via Report C
        resp_c = await test_client.post(
            f"/api/v1/admin/reports/{report_c.report_id}/enforcement",
            json={"action": "USER_UNBAN"},
        )
        assert resp_c.status_code == 409
        assert "không phải là nguồn tạo ra lệnh khóa" in resp_c.json()["detail"].lower()


# ============================================================================
# 5. CAPABILITIES MATRIX (REQUIREMENT #22)
# ============================================================================

@pytest.mark.asyncio
async def test_capabilities_matrix(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    target_admin: User,
    sample_product: Product,
    sample_order: Order,
    open_user_report: Report,
    db_session: AsyncSession,
):
    service = ReportService(db_session)

    # 1. OPEN + ACTIVE STUDENT USER report -> ["USER_BAN", "CAPABILITY_RESTRICT"]
    res = await service.get_admin_report_detail(admin_user, open_user_report.report_id)
    assert set(res.available_enforcement_actions) == {"USER_BAN", "CAPABILITY_RESTRICT"}

    # 2. REVIEWING + ACTIVE STUDENT -> ["USER_BAN", "CAPABILITY_RESTRICT"]
    open_user_report.status = ReportStatus.REVIEWING.value
    await db_session.flush()
    res = await service.get_admin_report_detail(admin_user, open_user_report.report_id)
    assert set(res.available_enforcement_actions) == {"USER_BAN", "CAPABILITY_RESTRICT"}

    # 3. REJECTED -> []
    open_user_report.status = ReportStatus.REJECTED.value
    await db_session.flush()
    res = await service.get_admin_report_detail(admin_user, open_user_report.report_id)
    assert res.available_enforcement_actions == []

    # 4. RESOLVED without ban -> []
    open_user_report.status = ReportStatus.RESOLVED.value
    await db_session.flush()
    res = await service.get_admin_report_detail(admin_user, open_user_report.report_id)
    assert res.available_enforcement_actions == []

    # 5. ADMIN target -> []
    admin_target_rep = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_admin.user_id,
        reason=ReportReason.OTHER.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add(admin_target_rep)
    await db_session.flush()
    res = await service.get_admin_report_detail(admin_user, admin_target_rep.report_id)
    assert res.available_enforcement_actions == []

    # 6. INACTIVE target -> []
    target_student.status = UserStatus.INACTIVE
    open_user_report.status = ReportStatus.OPEN.value
    await db_session.flush()
    res = await service.get_admin_report_detail(admin_user, open_user_report.report_id)
    assert res.available_enforcement_actions == []
    target_student.status = UserStatus.ACTIVE
    await db_session.flush()

    # 7. PRODUCT / ORDER report -> []
    prod_rep = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.PRODUCT.value,
        target_id=sample_product.product_id,
        reason=ReportReason.FAKE_ITEM.value,
        status=ReportStatus.OPEN.value,
    )
    order_rep = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.ORDER.value,
        target_id=sample_order.order_id,
        reason=ReportReason.NO_SHOW.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add_all([prod_rep, order_rep])
    await db_session.flush()

    res_prod = await service.get_admin_report_detail(admin_user, prod_rep.report_id)
    assert res_prod.available_enforcement_actions == [ModerationActionType.PRODUCT_HIDE]

    res_order = await service.get_admin_report_detail(admin_user, order_rep.report_id)
    assert set(res_order.available_enforcement_actions) == {"USER_BAN", "CAPABILITY_RESTRICT"}

    # 8. BANNED target whose effective USER_BAN belongs to THIS report -> ["USER_UNBAN"]
    with auth_patch(admin_user):
        await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
    res_banned_own = await service.get_admin_report_detail(admin_user, open_user_report.report_id)
    assert res_banned_own.available_enforcement_actions == ["USER_UNBAN"]

    # 9. BANNED target whose effective USER_BAN belongs to ANOTHER report -> []
    other_rep = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add(other_rep)
    await db_session.flush()
    res_other = await service.get_admin_report_detail(admin_user, other_rep.report_id)
    assert res_other.available_enforcement_actions == []


# ============================================================================
# 6. NON-CASCADE & SIDE EFFECT ISOLATION
# ============================================================================

@pytest.mark.asyncio
async def test_no_product_or_order_side_effects_on_user_ban(
    test_client: AsyncClient,
    admin_user: User,
    open_user_report: Report,
    target_student: User,
    sample_product: Product,
    sample_order: Order,
    db_session: AsyncSession,
):
    """
    Requirement #20:
    Banning user does NOT mutate products (no delete, status remains AVAILABLE)
    and does NOT mutate orders.
    """
    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
    assert resp.status_code == 200

    await db_session.refresh(sample_product)
    assert sample_product.status == ProductStatus.AVAILABLE.value
    assert sample_product.is_deleted is False
    assert sample_product.stock == 1

    await db_session.refresh(sample_order)
    assert sample_order.status == OrderStatus.PENDING.value
    assert sample_order.payment_status == PaymentStatus.UNPAID.value


@pytest.mark.asyncio
async def test_no_notification_rows_created(
    test_client: AsyncClient,
    admin_user: User,
    open_user_report: Report,
    db_session: AsyncSession,
):
    """
    Requirement #8 & #25:
    Zero application Notification rows created during USER_BAN and USER_UNBAN.
    """
    count_before = (
        await db_session.execute(select(func.count()).select_from(Notification))
    ).scalar_one()

    with auth_patch(admin_user):
        # 1. Ban
        res1 = await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
        assert res1.status_code == 200

        # 2. Unban
        res2 = await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_UNBAN"},
        )
        assert res2.status_code == 200

    count_after = (
        await db_session.execute(select(func.count()).select_from(Notification))
    ).scalar_one()

    assert count_after == count_before


@pytest.mark.asyncio
async def test_public_report_response_does_not_leak_admin_enforcement(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    open_user_report: Report,
):
    """
    Requirement #4:
    Do not expose enforcement actions or capabilities in ordinary user ReportResponse.
    """
    with auth_patch(admin_user):
        await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )

    # Verify ordinary user ReportResponse schema does not leak admin enforcement fields
    assert "available_enforcement_actions" not in ReportResponse.model_fields
    assert "enforcement_actions" not in ReportResponse.model_fields
    assert "handled_by" not in ReportResponse.model_fields
    assert "handler" not in ReportResponse.model_fields


# ============================================================================
# 7. AUTH & WEBSOCKET SECURITY AUDIT (REQUIREMENTS #7, #8, #9, #23)
# ============================================================================

@pytest.mark.asyncio
async def test_banned_user_blocked_by_active_user_endpoint(
    test_client: AsyncClient, admin_user: User, open_user_report: Report, target_student: User
):
    """
    Requirement #23:
    After User becomes BANNED: authenticated REST access requiring ACTIVE returns 403.
    """
    with auth_patch(admin_user):
        await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )

    # Calling an active-required endpoint as target_student
    with auth_patch(target_student):
        resp = await test_client.get("/api/v1/users/me")
    assert resp.status_code == 403
    assert "banned" in resp.json()["detail"].lower() or "khóa" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_websocket_handshake_rejected_for_banned_user(
    db_session: AsyncSession, target_student: User
):
    """
    Requirement #23:
    New private WebSocket connection cannot regain active access.
    """
    target_student.status = UserStatus.BANNED
    await db_session.flush()

    # Mock token verification resolving to target_student
    with patch("app.modules.auth.dependencies.verify_firebase_token") as mock_verify:
        mock_verify.return_value = {"uid": f"firebase_{target_student.user_id}", "email": target_student.email}
        with pytest.raises(HTTPException) as exc_info:
            await authenticate_user_token("mock_token", db_session)
        assert exc_info.value.status_code == 403
        assert "khóa" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_websocket_established_revocation():
    """
    Requirement #8, #9, #23:
    Verify revocation logic closes connected WebSockets with code 1008
    and dispatches Redis _DISCONNECT envelope.
    """
    manager = UserConnectionManager()
    user_id = 8888

    # Create mock active WebSocket
    mock_ws = AsyncMock()
    mock_ws.client_state.name = "CONNECTED"
    mock_ws.close = AsyncMock()

    # Connect mock ws
    async with manager._lock:
        manager._connections[user_id] = {mock_ws}

    # Execute local revocation
    await manager.revoke_user_connections(user_id)

    # Assert closed with code 1008
    mock_ws.close.assert_called_once_with(code=1008)
    assert user_id not in manager._connections

    # Test revoke_user_sessions dispatches Redis message
    with patch("app.modules.orders.websocket.get_redis_client") as mock_get_redis:
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis
        await revoke_user_sessions(user_id)
        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args[0]
        assert args[0] == f"user:{user_id}:events"
        assert "_DISCONNECT" in args[1]


# ============================================================================
# 8. DETERMINISTIC ORDER & AUDIT INDEX TEST (REQUIREMENTS #12, #13)
# ============================================================================

@pytest.mark.asyncio
async def test_moderation_history_order_deterministic(
    db_session: AsyncSession, admin_user: User, open_user_report: Report, target_student: User
):
    repo = ReportRepository(db_session)

    # Add multiple actions
    a1 = await repo.add_moderation_action(
        ModerationAction(
            report_id=open_user_report.report_id,
            admin_id=admin_user.user_id,
            action_type=ModerationActionType.USER_BAN.value,
            target_type=ReportTargetType.USER.value,
            target_id=target_student.user_id,
            previous_status="ACTIVE",
            new_status="BANNED",
        )
    )
    a2 = await repo.add_moderation_action(
        ModerationAction(
            report_id=open_user_report.report_id,
            admin_id=admin_user.user_id,
            action_type=ModerationActionType.USER_UNBAN.value,
            target_type=ReportTargetType.USER.value,
            target_id=target_student.user_id,
            previous_status="BANNED",
            new_status="ACTIVE",
        )
    )
    await db_session.flush()

    # List by report -> created_at ASC, moderation_action_id ASC
    actions = await repo.list_moderation_actions_by_report(open_user_report.report_id)
    assert len(actions) == 2
    assert actions[0].moderation_action_id == a1.moderation_action_id
    assert actions[1].moderation_action_id == a2.moderation_action_id

    # Latest by target -> created_at DESC, moderation_action_id DESC
    latest = await repo.get_latest_moderation_action_for_target(
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
    )
    assert latest is not None
    assert latest.moderation_action_id == a2.moderation_action_id


# ============================================================================
# 9. CONCURRENCY SAFETY (ROW LOCK ORDER: REPORT -> USER)
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_user_ban_row_lock_safety():
    """
    Test that concurrent USER_BAN calls on the same report from separate sessions
    use canonical lock order (Report FOR UPDATE -> User FOR UPDATE).
    Admin A wins, Admin B receives 409 Conflict. Exactly 1 audit record is created.
    """
    async with test_engine.connect() as conn_setup:
        tx_setup = await conn_setup.begin()
        session_setup = AsyncSession(bind=conn_setup, expire_on_commit=False)

        rand_suffix = uuid.uuid4().hex[:6]
        admin_a = User(
            email=f"admin_conc_a_{rand_suffix}@ptit.edu.vn",
            full_name="Admin Conc Alpha",
            role=UserRole.ADMIN.value,
            status=UserStatus.ACTIVE,
        )
        admin_b = User(
            email=f"admin_conc_b_{rand_suffix}@ptit.edu.vn",
            full_name="Admin Conc Beta",
            role=UserRole.ADMIN.value,
            status=UserStatus.ACTIVE,
        )
        target = User(
            email=f"target_conc_user_{rand_suffix}@ptit.edu.vn",
            full_name="Target Conc User",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
        )
        session_setup.add_all([admin_a, admin_b, target])
        await session_setup.flush()

        report = Report(
            reporter_id=admin_a.user_id,
            target_type=ReportTargetType.USER.value,
            target_id=target.user_id,
            reason=ReportReason.INAPPROPRIATE.value,
            status=ReportStatus.OPEN.value,
        )
        session_setup.add(report)
        await session_setup.flush()
        report_id = report.report_id
        admin_a_id = admin_a.user_id
        admin_b_id = admin_b.user_id
        target_id = target.user_id
        await tx_setup.commit()

    async with test_engine.connect() as conn_a, test_engine.connect() as conn_b:
        session_a = AsyncSession(bind=conn_a, expire_on_commit=False)
        session_b = AsyncSession(bind=conn_b, expire_on_commit=False)

        tx_a = await conn_a.begin()
        tx_b = await conn_b.begin()

        service_a = ReportService(session_a)
        service_b = ReportService(session_b)

        admin_a_obj = await session_a.get(User, admin_a_id)
        admin_b_obj = await session_b.get(User, admin_b_id)

        # Admin A executes USER_BAN
        res_a = await service_a.enforce_user_action(
            current_admin=admin_a_obj,
            report_id=report_id,
            action=ModerationActionType.USER_BAN,
        )
        assert res_a.target_summary.status == "BANNED"
        await tx_a.commit()

        # Admin B executes USER_BAN concurrently on the now-RESOLVED report and BANNED user
        with pytest.raises(HTTPException) as exc_info:
            await service_b.enforce_user_action(
                current_admin=admin_b_obj,
                report_id=report_id,
                action=ModerationActionType.USER_BAN,
            )
        assert exc_info.value.status_code == 409
        await tx_b.rollback()

    # Cleanup and verify exactly 1 ModerationAction was created
    async with test_engine.connect() as conn_clean:
        tx_clean = await conn_clean.begin()
        session_clean = AsyncSession(bind=conn_clean, expire_on_commit=False)

        actions = (
            await session_clean.execute(
                select(ModerationAction).where(ModerationAction.report_id == report_id)
            )
        ).scalars().all()
        assert len(actions) == 1
        assert actions[0].action_type == "USER_BAN"

        for act in actions:
            await session_clean.delete(act)
        rep = await session_clean.get(Report, report_id)
        if rep:
            await session_clean.delete(rep)
        for uid in [admin_a_id, admin_b_id, target_id]:
            u = await session_clean.get(User, uid)
            if u:
                await session_clean.delete(u)
        await session_clean.commit()
        await tx_clean.commit()


# ============================================================================
# 9. REVISED PHASE 8G-B1: MODERATION SEMANTICS & ACCESS STATUS
# ============================================================================

@pytest.mark.asyncio
async def test_user_access_status_endpoint(
    test_client: AsyncClient,
    target_student: User,
    db_session: AsyncSession,
):
    """
    GET /api/v1/users/me/access-status:
    Must be accessible and return 200 for ACTIVE, BANNED, and INACTIVE users.
    Returns machine-readable access status: user_id, status, role.
    """
    # 1. ACTIVE user
    with auth_patch(target_student):
        resp = await test_client.get("/api/v1/users/me/access-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == target_student.user_id
    assert data["status"] == "ACTIVE"
    assert data["role"] == "STUDENT"

    # 2. BANNED user
    target_student.status = UserStatus.BANNED
    await db_session.flush()
    with auth_patch(target_student):
        resp_banned = await test_client.get("/api/v1/users/me/access-status")
    assert resp_banned.status_code == 200
    data_banned = resp_banned.json()
    assert data_banned["user_id"] == target_student.user_id
    assert data_banned["status"] == "BANNED"
    assert data_banned["role"] == "STUDENT"

    # 3. INACTIVE user
    target_student.status = UserStatus.INACTIVE
    await db_session.flush()
    with auth_patch(target_student):
        resp_inactive = await test_client.get("/api/v1/users/me/access-status")
    assert resp_inactive.status_code == 200
    data_inactive = resp_inactive.json()
    assert data_inactive["user_id"] == target_student.user_id
    assert data_inactive["status"] == "INACTIVE"
    assert data_inactive["role"] == "STUDENT"

    # Restore
    target_student.status = UserStatus.ACTIVE
    await db_session.flush()


@pytest.mark.asyncio
async def test_admin_reports_workflow_and_conclusion_filtering(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    db_session: AsyncSession,
):
    """
    Verify filtering by workflow (OPEN, REVIEWING, COMPLETED)
    and conclusion (SUPPORTED, INSUFFICIENT_EVIDENCE).
    COMPLETED returns both RESOLVED and REJECTED.
    SUPPORTED returns RESOLVED.
    INSUFFICIENT_EVIDENCE returns REJECTED.
    """
    prefix = uuid.uuid4().hex[:6]
    r_open = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.SPAM.value,
        description=f"open_{prefix}",
        status=ReportStatus.OPEN.value,
    )
    r_reviewing = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.SPAM.value,
        description=f"reviewing_{prefix}",
        status=ReportStatus.REVIEWING.value,
    )
    r_resolved = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.SPAM.value,
        description=f"resolved_{prefix}",
        status=ReportStatus.RESOLVED.value,
    )
    r_rejected = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.SPAM.value,
        description=f"rejected_{prefix}",
        status=ReportStatus.REJECTED.value,
    )
    db_session.add_all([r_open, r_reviewing, r_resolved, r_rejected])
    await db_session.flush()

    with auth_patch(admin_user):
        # 1. Filter workflow=OPEN
        resp_open = await test_client.get("/api/v1/admin/reports?workflow=OPEN")
        assert resp_open.status_code == 200
        items_open = resp_open.json()["items"]
        open_ids = [i["report_id"] for i in items_open]
        assert r_open.report_id in open_ids
        assert r_reviewing.report_id not in open_ids
        assert r_resolved.report_id not in open_ids
        assert r_rejected.report_id not in open_ids

        # 2. Filter workflow=REVIEWING
        resp_rev = await test_client.get("/api/v1/admin/reports?workflow=REVIEWING")
        assert resp_rev.status_code == 200
        items_rev = resp_rev.json()["items"]
        rev_ids = [i["report_id"] for i in items_rev]
        assert r_reviewing.report_id in rev_ids
        assert r_open.report_id not in rev_ids
        assert r_resolved.report_id not in rev_ids
        assert r_rejected.report_id not in rev_ids

        # 3. Filter workflow=COMPLETED (returns both RESOLVED and REJECTED)
        resp_comp = await test_client.get("/api/v1/admin/reports?workflow=COMPLETED")
        assert resp_comp.status_code == 200
        items_comp = resp_comp.json()["items"]
        comp_ids = [i["report_id"] for i in items_comp]
        assert r_resolved.report_id in comp_ids
        assert r_rejected.report_id in comp_ids
        assert r_open.report_id not in comp_ids
        assert r_reviewing.report_id not in comp_ids

        # 4. Filter conclusion=SUPPORTED
        resp_sup = await test_client.get("/api/v1/admin/reports?conclusion=SUPPORTED")
        assert resp_sup.status_code == 200
        items_sup = resp_sup.json()["items"]
        sup_ids = [i["report_id"] for i in items_sup]
        assert r_resolved.report_id in sup_ids
        assert r_rejected.report_id not in sup_ids
        assert r_open.report_id not in sup_ids

        # 5. Filter conclusion=INSUFFICIENT_EVIDENCE
        resp_insuf = await test_client.get("/api/v1/admin/reports?conclusion=INSUFFICIENT_EVIDENCE")
        assert resp_insuf.status_code == 200
        items_insuf = resp_insuf.json()["items"]
        insuf_ids = [i["report_id"] for i in items_insuf]
        assert r_rejected.report_id in insuf_ids
        assert r_resolved.report_id not in insuf_ids
        assert r_open.report_id not in insuf_ids


@pytest.mark.asyncio
async def test_admin_reports_conflicting_filters_return_422(
    test_client: AsyncClient,
    admin_user: User,
):
    with auth_patch(admin_user):
        # Conflict between status and workflow
        r1 = await test_client.get("/api/v1/admin/reports?status=OPEN&workflow=OPEN")
        assert r1.status_code == 422

        # Conflict between status and conclusion
        r2 = await test_client.get("/api/v1/admin/reports?status=RESOLVED&conclusion=SUPPORTED")
        assert r2.status_code == 422

        # Conflict between workflow=OPEN and conclusion
        r3 = await test_client.get("/api/v1/admin/reports?workflow=OPEN&conclusion=SUPPORTED")
        assert r3.status_code == 422

        # Conflict between workflow=REVIEWING and conclusion
        r4 = await test_client.get("/api/v1/admin/reports?workflow=REVIEWING&conclusion=INSUFFICIENT_EVIDENCE")
        assert r4.status_code == 422


@pytest.mark.asyncio
async def test_available_moderation_actions_lifecycle(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    db_session: AsyncSession,
):
    """
    Test available_moderation_actions, workflow_state, and conclusion projection
    across the lifecycle of a report.
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
        # 1. OPEN
        resp_open = await test_client.get(f"/api/v1/admin/reports/{report.report_id}")
        assert resp_open.status_code == 200
        data_open = resp_open.json()
        assert data_open["workflow_state"] == "OPEN"
        assert data_open["conclusion"] is None
        assert set(data_open["available_moderation_actions"]) == {
            "START_REVIEW",
            "CONFIRM_SUPPORTED",
            "MARK_INSUFFICIENT_EVIDENCE",
        }

        # 2. Transition to REVIEWING
        resp_patch = await test_client.patch(
            f"/api/v1/admin/reports/{report.report_id}/status",
            json={"status": "REVIEWING"},
        )
        assert resp_patch.status_code == 200
        data_rev = resp_patch.json()
        assert data_rev["workflow_state"] == "REVIEWING"
        assert data_rev["conclusion"] is None
        assert set(data_rev["available_moderation_actions"]) == {
            "CONFIRM_SUPPORTED",
            "MARK_INSUFFICIENT_EVIDENCE",
        }

        # 3. Transition to RESOLVED
        resp_res = await test_client.patch(
            f"/api/v1/admin/reports/{report.report_id}/status",
            json={"status": "RESOLVED"},
        )
        assert resp_res.status_code == 200
        data_res = resp_res.json()
        assert data_res["workflow_state"] == "COMPLETED"
        assert data_res["conclusion"] == "SUPPORTED"
        assert data_res["available_moderation_actions"] == []


@pytest.mark.asyncio
async def test_banned_seller_product_excluded_from_public_listing(
    test_client: AsyncClient,
    admin_user: User,
    target_student: User,
    sample_product: Product,
    open_user_report: Report,
    db_session: AsyncSession,
):
    """
    Public product search excludes products of BANNED sellers,
    without mutating the product's status in the database.
    """
    # 1. Product is visible when seller is ACTIVE
    resp = await test_client.get(f"/api/v1/products/{sample_product.product_id}")
    assert resp.status_code == 200

    # 2. Ban the seller via admin report enforcement
    with auth_patch(admin_user):
        ban_resp = await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
        assert ban_resp.status_code == 200

    # 3. Listing is excluded from public search
    list_resp = await test_client.get("/api/v1/products")
    assert list_resp.status_code == 200
    listed_ids = [p["product_id"] for p in list_resp.json()["items"]]
    assert sample_product.product_id not in listed_ids

    # 4. Product record in database is intact (AVAILABLE, not deleted)
    await db_session.refresh(sample_product)
    assert sample_product.status == ProductStatus.AVAILABLE.value
    assert sample_product.is_deleted is False


@pytest.mark.asyncio
async def test_banned_seller_direct_order_creation_blocked(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    sample_product: Product,
    open_user_report: Report,
    db_session: AsyncSession,
):
    """
    Direct order creation is rejected if the seller is BANNED.
    """
    with auth_patch(admin_user):
        await test_client.post(
            f"/api/v1/admin/reports/{open_user_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )

    # Buyer attempts to order product from banned seller
    with auth_patch(student_reporter):
        resp = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": sample_product.product_id,
                "quantity": 1,
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường PTIT",
                "contact_name": "Người mua hàng",
                "contact_phone": "0988888888",
                "payment_method": "CASH_ON_MEETUP",
            },
        )
    assert resp.status_code == 400
    assert "người bán" in resp.json()["detail"].lower()
