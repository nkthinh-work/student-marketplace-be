from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.categories.models import Category
from app.modules.orders.models import FulfillmentMethod, Order, OrderItem, OrderStatus, PaymentMethod, PaymentStatus
from app.modules.products.models import ListingType, Product, ProductModerationStatus, ProductStatus
from app.modules.reports.models import Report, ReportReason, ReportStatus, ReportTargetType, ModerationAction, ModerationActionType
from app.modules.reports.schemas import AdminEnforcementRequest
from app.modules.users.models import User, UserRole, UserStatus
from app.modules.users.capability_models import UserCapabilityRestriction, CapabilityType
from app.modules.users.capability_service import CapabilityService
from app.modules.auctions.models import Auction, AuctionStatus, AuctionBid
from app.modules.favorites.models import Favorite


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
        email="admin_caps@ptit.edu.vn",
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
        email="reporter_caps@ptit.edu.vn",
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
        email="target_caps@ptit.edu.vn",
        full_name="Target Student",
        phone="0922334455",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> Category:
    cat = Category(name="Category Caps", slug="cat-caps")
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
        title="Laptop Caps",
        description="Laptop for caps test",
        price=Decimal("12000000"),
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
async def test_capability_duration_validation(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    db_session: AsyncSession,
):
    """
    Test duration validation:
    - 1, 3, 7, 14 allowed
    - Omitted duration -> 422
    - null duration -> 422
    - Invalid duration (0, 2, 5, 15, 30, 90, 365, -1, garbage) -> 422
    - CAPABILITY_RESTORE with duration -> 422
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
        # 1. Omitted duration_days -> 422
        r_omit = await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTRICT", "capabilities": ["BUY"]},
        )
        assert r_omit.status_code == 422

        # 2. null duration_days -> 422
        r_null = await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTRICT", "capabilities": ["BUY"], "duration_days": None},
        )
        assert r_null.status_code == 422

        # 3. Invalid durations (0, 2, 5, 15, 30, 90, 365, -1, garbage) -> 422
        for bad_val in (0, 2, 5, 15, 30, 90, 365, -1, "garbage"):
            r_invalid = await test_client.post(
                f"/api/v1/admin/reports/{report.report_id}/enforcement",
                json={"action": "CAPABILITY_RESTRICT", "capabilities": ["BUY"], "duration_days": bad_val},
            )
            assert r_invalid.status_code == 422, f"Expected 422 for duration {bad_val}, got {r_invalid.status_code}"

        # 4. Valid duration: 1, 3, 7, 14 (test 1, 3, 14, and execute 7)
        # Verify schema accepts 1, 3, 14
        for valid_val in (1, 3, 14):
            req = AdminEnforcementRequest.model_validate({
                "action": "CAPABILITY_RESTRICT",
                "capabilities": ["BUY"],
                "duration_days": valid_val,
            })
            assert req.duration_days == valid_val

        # Execute 7 on report
        r_valid = await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTRICT", "capabilities": ["BUY"], "duration_days": 7},
        )
        assert r_valid.status_code == 200
        assert r_valid.json()["status"] == "RESOLVED"

        # 5. CAPABILITY_RESTORE providing duration_days -> 422
        r_restore_invalid = await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTORE", "capabilities": ["BUY"], "duration_days": 7},
        )
        assert r_restore_invalid.status_code == 422


@pytest.mark.asyncio
async def test_capability_restrict_duplicate_conflict_409(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    db_session: AsyncSession,
):
    """
    If any requested capability already has an active restriction: 409 conflict, zero mutation.
    """
    report1 = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.OPEN.value,
    )
    report2 = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.SCAM.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add_all([report1, report2])
    await db_session.flush()

    with auth_patch(admin_user):
        r1 = await test_client.post(
            f"/api/v1/admin/reports/{report1.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTRICT", "capabilities": ["BUY"], "duration_days": 3},
        )
        assert r1.status_code == 200

        # Attempt to restrict BUY again on report2 -> 409
        r2 = await test_client.post(
            f"/api/v1/admin/reports/{report2.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTRICT", "capabilities": ["BUY"], "duration_days": 3},
        )
        assert r2.status_code == 409


@pytest.mark.asyncio
async def test_capability_restore_same_report_safety(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    db_session: AsyncSession,
):
    """
    Only the report that created the active restriction can restore it.
    """
    report1 = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.OPEN.value,
    )
    report2 = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.SCAM.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add_all([report1, report2])
    await db_session.flush()

    with auth_patch(admin_user):
        r1 = await test_client.post(
            f"/api/v1/admin/reports/{report1.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTRICT", "capabilities": ["SELL"], "duration_days": 3},
        )
        assert r1.status_code == 200

        # Report 2 tries to restore SELL -> 409 (not creator)
        r2_restore = await test_client.post(
            f"/api/v1/admin/reports/{report2.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTORE", "capabilities": ["SELL"]},
        )
        assert r2_restore.status_code == 409

        # Report 1 restores SELL -> 200
        r1_restore = await test_client.post(
            f"/api/v1/admin/reports/{report1.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTORE", "capabilities": ["SELL"]},
        )
        assert r1_restore.status_code == 200


@pytest.mark.asyncio
async def test_buy_restricted_blocks_direct_order_creation(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    sample_product: Product,
    db_session: AsyncSession,
):
    """
    A BUY-restricted user cannot create a direct order -> returns 403 with BUY_RESTRICTED error code.
    """
    report = Report(
        reporter_id=target_student.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=student_reporter.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add(report)
    await db_session.flush()

    # Restrict BUY on student_reporter
    with auth_patch(admin_user):
        resp_res = await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTRICT", "capabilities": ["BUY"], "duration_days": 3},
        )
        assert resp_res.status_code == 200

    # student_reporter attempts to place direct order
    with auth_patch(student_reporter):
        resp_ord = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": sample_product.product_id,
                "quantity": 1,
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường PTIT",
                "contact_name": "Người mua",
                "contact_phone": "0911223344",
                "payment_method": "CASH_ON_MEETUP",
            },
        )
    assert resp_ord.status_code == 403
    ord_detail = resp_ord.json().get("detail")
    assert (isinstance(ord_detail, dict) and ord_detail.get("code") == "BUY_RESTRICTED") or "BUY_RESTRICTED" in str(ord_detail)


@pytest.mark.asyncio
async def test_sell_restricted_blocks_product_creation_and_hides_public_products(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    sample_category: Category,
    sample_product: Product,
    db_session: AsyncSession,
):
    """
    A SELL-restricted user:
    - Cannot create new products (403 SELL_RESTRICTED)
    - Existing products are dynamically excluded from public feed
    - Direct purchase attempts against seller return privacy-safe 404
    - Owner can still view products via /products/me
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

    # Restrict SELL on target_student
    with auth_patch(admin_user):
        resp_res = await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTRICT", "capabilities": ["SELL"], "duration_days": 3},
        )
        assert resp_res.status_code == 200

    # 1. target_student cannot create new product
    with auth_patch(target_student):
        resp_create = await test_client.post(
            "/api/v1/products",
            json={
                "title": "New Phone",
                "description": "Selling phone",
                "category_id": sample_category.category_id,
                "price": 5000000,
                "stock": 1,
            },
        )
    assert resp_create.status_code == 403
    create_detail = resp_create.json().get("detail")
    assert (isinstance(create_detail, dict) and create_detail.get("code") == "SELL_RESTRICTED") or "SELL_RESTRICTED" in str(create_detail)

    # 2. Public feed excludes target_student's product
    with auth_patch(student_reporter):
        resp_feed = await test_client.get("/api/v1/products")
        assert resp_feed.status_code == 200
        feed_ids = [p["product_id"] for p in resp_feed.json().get("items", [])]
        assert sample_product.product_id not in feed_ids

    # 3. Direct purchase against SELL-restricted seller returns 404 Not Found
    with auth_patch(student_reporter):
        resp_buy = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": sample_product.product_id,
                "quantity": 1,
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường PTIT",
                "contact_name": "Người mua",
                "contact_phone": "0911223344",
                "payment_method": "CASH_ON_MEETUP",
            },
        )
    assert resp_buy.status_code == 404

    # 4. Owner still sees own product in /products/me
    with auth_patch(target_student):
        resp_me = await test_client.get("/api/v1/products/me")
        assert resp_me.status_code == 200
        my_ids = [p["product_id"] for p in resp_me.json().get("items", [])]
        assert sample_product.product_id in my_ids


@pytest.mark.asyncio
async def test_user_me_access_status_contains_capabilities(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    db_session: AsyncSession,
):
    """
    GET /api/v1/users/me/access-status exposes can_buy, can_sell, and active_restrictions
    without leaking internal report/moderator IDs.
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
        await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTRICT", "capabilities": ["BUY"], "duration_days": 3},
        )

    with auth_patch(target_student):
        resp = await test_client.get("/api/v1/users/me/access-status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["can_buy"] is False
    assert data["can_sell"] is True
    assert len(data["active_restrictions"]) == 1
    assert data["active_restrictions"][0]["capability"] == "BUY"
    assert "source_report_id" not in data["active_restrictions"][0]
    assert "imposed_by" not in data["active_restrictions"][0]


@pytest.mark.asyncio
async def test_banned_or_inactive_user_capability_restriction_returns_409(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    db_session: AsyncSession,
):
    """
    Cannot apply capability restrictions over already BANNED or INACTIVE accounts -> 409 Conflict.
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

    # 1. BANNED target
    target_student.status = UserStatus.BANNED
    await db_session.flush()

    with auth_patch(admin_user):
        r_ban = await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTRICT", "capabilities": ["BUY"], "duration_days": 3},
        )
    assert r_ban.status_code == 409

    # 2. INACTIVE target
    target_student.status = UserStatus.INACTIVE
    await db_session.flush()

    with auth_patch(admin_user):
        r_inactive = await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTRICT", "capabilities": ["BUY"], "duration_days": 3},
        )
    assert r_inactive.status_code == 409


@pytest.mark.asyncio
async def test_admin_user_capability_restriction_forbidden_403(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    db_session: AsyncSession,
):
    """
    Cannot apply capability restrictions over an ADMIN account -> 403 Forbidden.
    """
    admin_target = User(
        email="other_admin@ptit.edu.vn",
        full_name="Other Admin",
        phone="0999888777",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(admin_target)
    await db_session.flush()

    report = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=admin_target.user_id,
        reason=ReportReason.OTHER.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add(report)
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTRICT", "capabilities": ["BUY"], "duration_days": 3},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_buy_and_sell_combined_restriction_atomic_audit_rows(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    db_session: AsyncSession,
):
    """
    BUY + SELL combined writes two restriction rows and two audit rows atomically:
    - BUY_RESTRICT: UNRESTRICTED -> RESTRICTED
    - SELL_RESTRICT: UNRESTRICTED -> RESTRICTED
    - duration_days: 14
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
            json={"action": "CAPABILITY_RESTRICT", "capabilities": ["BUY", "SELL"], "duration_days": 14},
        )
    assert resp.status_code == 200

    # Query moderation actions created for this report
    stmt = select(ModerationAction).where(ModerationAction.report_id == report.report_id).order_by(ModerationAction.action_type.asc())
    actions = (await db_session.execute(stmt)).scalars().all()
    assert len(actions) == 2
    action_types = {a.action_type for a in actions}
    assert action_types == {"BUY_RESTRICT", "SELL_RESTRICT"}
    for a in actions:
        assert a.previous_status == "UNRESTRICTED"
        assert a.new_status == "RESTRICTED"


@pytest.mark.asyncio
async def test_sell_restriction_cancels_active_and_scheduled_auctions(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    """
    Imposing SELL restriction:
    - Cancels SCHEDULED auctions -> CANCELLED
    - Cancels ACTIVE auctions -> CANCELLED
    - Preserves bids
    - Resets Product listing_type to FIXED_PRICE
    """
    # 1. Product with ACTIVE auction
    prod_active = Product(
        seller_id=target_student.user_id,
        category_id=sample_category.category_id,
        title="Auction Active Prod",
        description="Desc",
        price=Decimal("1000000"),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        moderation_status=ProductModerationStatus.CLEAR.value,
        listing_type=ListingType.AUCTION.value,
        is_deleted=False,
    )
    # 2. Product with SCHEDULED auction
    prod_sched = Product(
        seller_id=target_student.user_id,
        category_id=sample_category.category_id,
        title="Auction Sched Prod",
        description="Desc",
        price=Decimal("2000000"),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        moderation_status=ProductModerationStatus.CLEAR.value,
        listing_type=ListingType.AUCTION.value,
        is_deleted=False,
    )
    db_session.add_all([prod_active, prod_sched])
    await db_session.flush()

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    auc_active = Auction(
        product_id=prod_active.product_id,
        starting_price=Decimal("1000000"),
        bid_step=Decimal("50000"),
        starts_at=now_utc - timedelta(hours=1),
        ends_at=now_utc + timedelta(hours=1),
        status=AuctionStatus.ACTIVE.value,
    )
    auc_sched = Auction(
        product_id=prod_sched.product_id,
        starting_price=Decimal("2000000"),
        bid_step=Decimal("100000"),
        starts_at=now_utc + timedelta(hours=2),
        ends_at=now_utc + timedelta(hours=4),
        status=AuctionStatus.SCHEDULED.value,
    )
    db_session.add_all([auc_active, auc_sched])
    await db_session.flush()

    # Add bid on active auction to verify bids preserved
    bid = AuctionBid(
        auction_id=auc_active.auction_id,
        bidder_id=student_reporter.user_id,
        amount=Decimal("1100000"),
        created_at=now_utc - timedelta(minutes=30),
    )
    db_session.add(bid)
    await db_session.flush()

    report = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.SCAM.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add(report)
    await db_session.flush()

    # Admin restricts SELL on target_student
    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTRICT", "capabilities": ["SELL"], "duration_days": 7},
        )
    assert resp.status_code == 200

    await db_session.refresh(auc_active)
    await db_session.refresh(auc_sched)
    await db_session.refresh(prod_active)
    await db_session.refresh(prod_sched)

    assert auc_active.status == AuctionStatus.CANCELLED.value
    assert auc_sched.status == AuctionStatus.CANCELLED.value
    assert prod_active.listing_type == ListingType.FIXED_PRICE.value
    assert prod_sched.listing_type == ListingType.FIXED_PRICE.value

    # Verify bid is still intact in DB
    await db_session.refresh(bid)
    assert bid.bid_id is not None


@pytest.mark.asyncio
async def test_favorites_exclude_sell_restricted_seller_product(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    sample_product: Product,
    db_session: AsyncSession,
):
    """
    Favorites exclusion:
    - User favorites product of seller
    - When seller is SELL restricted, product is excluded from /favorites and /favorites/ids
    - Favorite row remains intact in DB
    - When restriction is restored, product reappears in /favorites!
    """
    # 1. Favorite product
    fav = Favorite(user_id=student_reporter.user_id, product_id=sample_product.product_id)
    db_session.add(fav)
    await db_session.flush()

    with auth_patch(student_reporter):
        r_fav1 = await test_client.get("/api/v1/favorites")
        assert r_fav1.status_code == 200
        ids1 = [p["product_id"] for p in r_fav1.json().get("items", [])]
        assert sample_product.product_id in ids1

    # 2. Impose SELL restriction
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
        r_rest = await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTRICT", "capabilities": ["SELL"], "duration_days": 3},
        )
        assert r_rest.status_code == 200

    # 3. Product excluded from favorites
    with auth_patch(student_reporter):
        r_fav2 = await test_client.get("/api/v1/favorites")
        assert r_fav2.status_code == 200
        ids2 = [p["product_id"] for p in r_fav2.json().get("items", [])]
        assert sample_product.product_id not in ids2

    # 4. Restore SELL restriction
    with auth_patch(admin_user):
        r_restore = await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTORE", "capabilities": ["SELL"]},
        )
        assert r_restore.status_code == 200

    # 5. Product automatically reappears
    with auth_patch(student_reporter):
        r_fav3 = await test_client.get("/api/v1/favorites")
        assert r_fav3.status_code == 200
        ids3 = [p["product_id"] for p in r_fav3.json().get("items", [])]
        assert sample_product.product_id in ids3


@pytest.mark.asyncio
async def test_restriction_expiry_exact_server_time(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    db_session: AsyncSession,
):
    """
    Controlled server time expiry verification:
    durations: 1, 3, 7, 14 days.
    - expires_at = starts_at + timedelta(days=d)
    - at exact expiry / 1s before: still restricted
    - at exact expiry / 1s after: automatically unrestricted
    """
    cap_service = CapabilityService(db_session)

    for days in (1, 3, 7, 14):
        student = User(
            email=f"target_dur_{days}@ptit.edu.vn",
            full_name=f"Target Student {days}",
            phone=f"091100000{days}",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
        )
        db_session.add(student)
        await db_session.flush()

        report = Report(
            reporter_id=student_reporter.user_id,
            target_type=ReportTargetType.USER.value,
            target_id=student.user_id,
            reason=ReportReason.SPAM.value,
            status=ReportStatus.OPEN.value,
        )
        db_session.add(report)
        await db_session.flush()

        with auth_patch(admin_user):
            resp = await test_client.post(
                f"/api/v1/admin/reports/{report.report_id}/enforcement",
                json={"action": "CAPABILITY_RESTRICT", "capabilities": ["BUY"], "duration_days": days},
            )
            assert resp.status_code == 200

        # Query the restriction row
        stmt = select(UserCapabilityRestriction).where(
            UserCapabilityRestriction.user_id == student.user_id,
            UserCapabilityRestriction.capability == "BUY",
        )
        res = await db_session.execute(stmt)
        restriction = res.scalar_one()

        # Verify starts_at and expires_at relationship
        assert restriction.expires_at is not None
        expected_expiry = restriction.starts_at + timedelta(days=days)
        assert abs((restriction.expires_at - expected_expiry).total_seconds()) < 2

        # 1s before expiry: still restricted
        assert await cap_service.can_user_buy(student, restriction.expires_at - timedelta(seconds=1)) is False

        # 1s after expiry: no longer restricted
        assert await cap_service.can_user_buy(student, restriction.expires_at + timedelta(seconds=1)) is True


@pytest.mark.asyncio
async def test_legacy_null_expires_at_compatibility(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    target_student: User,
    db_session: AsyncSession,
):
    """
    Test backward compatibility with legacy rows where expires_at IS NULL:
    - Existing row remains readable and effective indefinitely
    - Admin can restore it using standard CAPABILITY_RESTORE
    - After restore, capability is restored
    """
    cap_service = CapabilityService(db_session)
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    report = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=target_student.user_id,
        reason=ReportReason.SCAM.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add(report)
    await db_session.flush()

    # Manually insert legacy restriction with expires_at = None
    legacy_restr = UserCapabilityRestriction(
        user_id=target_student.user_id,
        source_report_id=report.report_id,
        imposed_by=admin_user.user_id,
        capability=CapabilityType.BUY.value,
        starts_at=now_utc - timedelta(days=10),
        expires_at=None,
    )
    db_session.add(legacy_restr)
    await db_session.flush()

    # Verify target cannot buy at current time and far future
    assert await cap_service.can_user_buy(target_student, now_utc) is False
    assert await cap_service.can_user_buy(target_student, now_utc + timedelta(days=365)) is False

    # Verify detail API reads it
    with auth_patch(admin_user):
        r_det = await test_client.get(f"/api/v1/admin/reports/{report.report_id}")
        assert r_det.status_code == 200
        subj = r_det.json().get("reported_subject")
        assert subj is not None
        assert subj["can_buy"] is False
        assert len(subj["active_restrictions"]) == 1
        assert subj["active_restrictions"][0]["expires_at"] is None

        # Admin restores capability
        r_restore = await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "CAPABILITY_RESTORE", "capabilities": ["BUY"]},
        )
        assert r_restore.status_code == 200

    # User can now buy
    assert await cap_service.can_user_buy(target_student, now_utc) is True

