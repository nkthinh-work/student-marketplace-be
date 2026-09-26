import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import app
from app.modules.auth.dependencies import get_current_user, get_current_active_user
from app.modules.products.router import get_optional_current_user as product_get_optional_user
from app.modules.auctions.models import Auction, AuctionBid, AuctionStatus
from app.modules.auctions.schemas import AuctionCreateRequest, PlaceBidRequest
from app.modules.auctions.service import AuctionService
from app.modules.categories.models import Category
from app.modules.favorites.models import Favorite
from app.modules.orders.models import (
    FulfillmentMethod,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from app.modules.orders.schemas import CreateOrderRequest
from app.modules.orders.service import OrderService
from app.modules.products.models import ListingType, Product, ProductStatus, ProductModerationStatus
from app.modules.reports.models import (
    ModerationAction,
    ModerationActionType,
    Report,
    ReportReason,
    ReportStatus,
    ReportTargetType,
)
from app.modules.reports.service import ReportService
from app.modules.users.models import User, UserRole, UserStatus
from tests.conftest import test_engine

TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def auth_patch(user: User):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[product_get_optional_user] = lambda: user

    class CleanCtx:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc_val, exc_tb):
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(product_get_optional_user, None)

    return CleanCtx()


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"admin_prod_1_{uuid.uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Quản Trị Viên Sản Phẩm 1",
        phone="0901000001",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def admin_user_2(db_session: AsyncSession) -> User:
    user = User(
        email=f"admin_prod_2_{uuid.uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Quản Trị Viên Sản Phẩm 2",
        phone="0901000002",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def student_seller(db_session: AsyncSession) -> User:
    user = User(
        email=f"seller_{uuid.uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Người Bán Sinh Viên",
        phone="0911000001",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def student_buyer(db_session: AsyncSession) -> User:
    user = User(
        email=f"buyer_{uuid.uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Người Mua Sinh Viên",
        phone="0912000002",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def student_reporter(db_session: AsyncSession) -> User:
    user = User(
        email=f"reporter_{uuid.uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Sinh Viên Tố Cáo",
        phone="0913000003",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> Category:
    cat = Category(
        name=f"Danh mục {uuid.uuid4().hex[:6]}",
        slug=f"danh-muc-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def sample_product(
    db_session: AsyncSession, student_seller: User, sample_category: Category
) -> Product:
    prod = Product(
        seller_id=student_seller.user_id,
        category_id=sample_category.category_id,
        title=f"Sản phẩm mẫu {uuid.uuid4().hex[:6]}",
        description="Mô tả sản phẩm cho sinh viên",
        price=Decimal("1500000"),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        moderation_status=ProductModerationStatus.CLEAR.value,
        approval_status="APPROVED",
        listing_type=ListingType.FIXED_PRICE.value,
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


@pytest_asyncio.fixture
async def open_product_report(
    db_session: AsyncSession, student_reporter: User, sample_product: Product
) -> Report:
    rep = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.PRODUCT.value,
        target_id=sample_product.product_id,
        reason=ReportReason.FAKE_ITEM.value,
        description="Sản phẩm này là hàng giả không đúng mô tả",
        status=ReportStatus.OPEN.value,
    )
    db_session.add(rep)
    await db_session.flush()
    return rep


# ==============================================================================
# 1. SECURITY & AUTH TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_enforce_product_unauthenticated_returns_401(
    test_client: AsyncClient, open_product_report: Report
):
    resp = await test_client.post(
        f"/api/v1/admin/reports/{open_product_report.report_id}/enforcement",
        json={"action": "PRODUCT_HIDE"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_enforce_product_student_forbidden_returns_403(
    test_client: AsyncClient, student_buyer: User, open_product_report: Report
):
    with auth_patch(student_buyer):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_product_report.report_id}/enforcement",
            json={"action": "PRODUCT_HIDE"},
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_enforce_action_target_mismatch(
    test_client: AsyncClient, admin_user: User, open_product_report: Report, student_reporter: User, student_seller: User, db_session: AsyncSession
):
    # Create a USER report
    user_report = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=student_seller.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add(user_report)
    await db_session.commit()

    with auth_patch(admin_user):
        # 1. PRODUCT_HIDE on USER report -> 400
        resp1 = await test_client.post(
            f"/api/v1/admin/reports/{user_report.report_id}/enforcement",
            json={"action": "PRODUCT_HIDE"},
        )
        assert resp1.status_code == 400
        assert "tin đăng" in resp1.json()["detail"].lower()

        # 2. USER_BAN on PRODUCT report -> 400
        resp2 = await test_client.post(
            f"/api/v1/admin/reports/{open_product_report.report_id}/enforcement",
            json={"action": "USER_BAN"},
        )
        assert resp2.status_code == 400
        assert "người dùng" in resp2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_product_create_and_update_forbids_moderation_status_injection(
    test_client: AsyncClient, student_seller: User, sample_category: Category, sample_product: Product
):
    with auth_patch(student_seller):
        # 1. Try create with moderation_status
        create_payload = {
            "category_id": sample_category.category_id,
            "title": "Sản phẩm hack moderation",
            "price": 100000,
            "stock": 1,
            "listing_type": "FIXED_PRICE",
            "moderation_status": "CLEAR",
        }
        resp_create = await test_client.post("/api/v1/products", json=create_payload)
        assert resp_create.status_code == 422

        # 2. Try update with moderation_status
        update_payload = {
            "title": "Cập nhật tiêu đề",
            "moderation_status": "CLEAR",
        }
        resp_update = await test_client.patch(f"/api/v1/products/{sample_product.product_id}", json=update_payload)
        assert resp_update.status_code == 422


# ==============================================================================
# 2. PRODUCT ENFORCEMENT INVARIANTS (HIDE & RESTORE)
# ==============================================================================

@pytest.mark.asyncio
async def test_product_hide_atomic_success(
    test_client: AsyncClient,
    admin_user: User,
    open_product_report: Report,
    sample_product: Product,
    db_session: AsyncSession,
):
    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_product_report.report_id}/enforcement",
            json={"action": "PRODUCT_HIDE"},
        )
        assert resp.status_code == 200
        data = resp.json()

        # In DTO
        assert data["target_type"] == "PRODUCT"
        assert data["status"] == "RESOLVED"
        assert data["workflow_state"] == "COMPLETED"
        assert data["conclusion"] == "SUPPORTED"
        assert data["handled_by"] == admin_user.user_id
        assert data["target_summary"]["moderation_status"] == "BLOCKED"
        assert "PRODUCT_RESTORE" in data["available_enforcement_actions"]
        assert "PRODUCT_HIDE" not in data["available_enforcement_actions"]

        # In DB
        await db_session.refresh(sample_product)
        assert sample_product.moderation_status == ProductModerationStatus.BLOCKED.value
        assert sample_product.status == ProductStatus.AVAILABLE.value  # Business status preserved!

        # Audit row created
        audit_res = await db_session.execute(
            select(ModerationAction).where(
                ModerationAction.report_id == open_product_report.report_id,
                ModerationAction.action_type == ModerationActionType.PRODUCT_HIDE.value,
            )
        )
        action_row = audit_res.scalar_one_or_none()
        assert action_row is not None
        assert action_row.previous_status == "CLEAR"
        assert action_row.new_status == "BLOCKED"
        assert action_row.target_type == "PRODUCT"
        assert action_row.admin_id == admin_user.user_id


@pytest.mark.asyncio
async def test_product_hide_idempotency_already_blocked_returns_400(
    test_client: AsyncClient,
    admin_user: User,
    open_product_report: Report,
    sample_product: Product,
    db_session: AsyncSession,
):
    sample_product.moderation_status = ProductModerationStatus.BLOCKED.value
    await db_session.commit()

    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_product_report.report_id}/enforcement",
            json={"action": "PRODUCT_HIDE"},
        )
        assert resp.status_code == 409
        assert "đã bị quản trị viên ẩn" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_product_restore_success(
    test_client: AsyncClient,
    admin_user: User,
    open_product_report: Report,
    sample_product: Product,
    db_session: AsyncSession,
):
    with auth_patch(admin_user):
        # Hide first via enforcement
        resp_hide = await test_client.post(
            f"/api/v1/admin/reports/{open_product_report.report_id}/enforcement",
            json={"action": "PRODUCT_HIDE"},
        )
        assert resp_hide.status_code == 200

        # Now restore
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_product_report.report_id}/enforcement",
            json={"action": "PRODUCT_RESTORE"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_summary"]["moderation_status"] == "CLEAR"
        assert "PRODUCT_RESTORE" not in data["available_enforcement_actions"]
        assert "PRODUCT_HIDE" not in data["available_enforcement_actions"]

        await db_session.refresh(sample_product)
        assert sample_product.moderation_status == ProductModerationStatus.CLEAR.value

        # Audit row
        audit_res = await db_session.execute(
            select(ModerationAction).where(
                ModerationAction.report_id == open_product_report.report_id,
                ModerationAction.action_type == ModerationActionType.PRODUCT_RESTORE.value,
            )
        )
        action_row = audit_res.scalar_one_or_none()
        assert action_row is not None
        assert action_row.previous_status == "BLOCKED"
        assert action_row.new_status == "CLEAR"


@pytest.mark.asyncio
async def test_product_restore_already_clear_returns_400(
    test_client: AsyncClient, admin_user: User, open_product_report: Report
):
    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_product_report.report_id}/enforcement",
            json={"action": "PRODUCT_RESTORE"},
        )
        assert resp.status_code == 409
        assert "không ở trạng thái bị quản trị viên ẩn" in resp.json()["detail"]


# ==============================================================================
# 3. AUCTION ATOMIC CANCELLATION INTEGRATION
# ==============================================================================

@pytest.mark.asyncio
async def test_product_hide_cancels_scheduled_auction(
    test_client: AsyncClient,
    admin_user: User,
    open_product_report: Report,
    sample_product: Product,
    db_session: AsyncSession,
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sample_product.listing_type = ListingType.AUCTION.value
    sample_product.stock = 1
    sample_product.reserved_stock = 0

    auction = Auction(
        product_id=sample_product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("10000"),
        status=AuctionStatus.SCHEDULED.value,
        starts_at=now + timedelta(hours=2),
        ends_at=now + timedelta(hours=4),
    )
    db_session.add(auction)
    await db_session.commit()

    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_product_report.report_id}/enforcement",
            json={"action": "PRODUCT_HIDE"},
        )
        assert resp.status_code == 200

        await db_session.refresh(auction)
        await db_session.refresh(sample_product)

        assert auction.status == AuctionStatus.CANCELLED.value
        assert auction.winner_id is None
        assert auction.final_price is None
        assert sample_product.moderation_status == ProductModerationStatus.BLOCKED.value
        assert sample_product.listing_type == ListingType.FIXED_PRICE.value
        assert sample_product.stock == 1
        assert sample_product.reserved_stock == 0


@pytest.mark.asyncio
async def test_product_hide_cancels_active_auction_zero_bids(
    test_client: AsyncClient,
    admin_user: User,
    open_product_report: Report,
    sample_product: Product,
    db_session: AsyncSession,
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sample_product.listing_type = ListingType.AUCTION.value
    sample_product.stock = 1
    sample_product.reserved_stock = 0

    auction = Auction(
        product_id=sample_product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("10000"),
        status=AuctionStatus.ACTIVE.value,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
    )
    db_session.add(auction)
    await db_session.commit()

    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_product_report.report_id}/enforcement",
            json={"action": "PRODUCT_HIDE"},
        )
        assert resp.status_code == 200

        await db_session.refresh(auction)
        assert auction.status == AuctionStatus.CANCELLED.value
        assert auction.winner_id is None


@pytest.mark.asyncio
async def test_product_hide_cancels_active_auction_with_existing_bids(
    test_client: AsyncClient,
    admin_user: User,
    student_buyer: User,
    open_product_report: Report,
    sample_product: Product,
    db_session: AsyncSession,
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sample_product.listing_type = ListingType.AUCTION.value
    sample_product.stock = 1
    sample_product.reserved_stock = 0

    auction = Auction(
        product_id=sample_product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("10000"),
        status=AuctionStatus.ACTIVE.value,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
    )
    db_session.add(auction)
    await db_session.flush()

    # Add 2 bids
    bid1 = AuctionBid(
        auction_id=auction.auction_id,
        bidder_id=student_buyer.user_id,
        amount=Decimal("110000"),
        created_at=now - timedelta(minutes=45),
    )
    bid2 = AuctionBid(
        auction_id=auction.auction_id,
        bidder_id=student_buyer.user_id,
        amount=Decimal("120000"),
        created_at=now - timedelta(minutes=30),
    )
    db_session.add_all([bid1, bid2])
    await db_session.commit()

    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_product_report.report_id}/enforcement",
            json={"action": "PRODUCT_HIDE"},
        )
        assert resp.status_code == 200

        await db_session.refresh(auction)
        await db_session.refresh(sample_product)

        # 1. Auction is CANCELLED
        assert auction.status == AuctionStatus.CANCELLED.value
        # 2. Winner is NOT selected
        assert auction.winner_id is None
        assert auction.final_price is None
        # 3. Existing bids are preserved intact as evidence
        bids_res = await db_session.execute(
            select(AuctionBid).where(AuctionBid.auction_id == auction.auction_id)
        )
        preserved_bids = bids_res.scalars().all()
        assert len(preserved_bids) == 2
        # 4. Product is BLOCKED and listing_type reset to FIXED_PRICE
        assert sample_product.moderation_status == ProductModerationStatus.BLOCKED.value
        assert sample_product.listing_type == ListingType.FIXED_PRICE.value
        assert sample_product.stock == 1
        assert sample_product.reserved_stock == 0


@pytest.mark.asyncio
async def test_seller_cancel_auction_still_requires_zero_bids(
    test_client: AsyncClient,
    student_seller: User,
    student_buyer: User,
    sample_product: Product,
    db_session: AsyncSession,
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sample_product.listing_type = ListingType.AUCTION.value
    auction = Auction(
        product_id=sample_product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("10000"),
        status=AuctionStatus.ACTIVE.value,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
    )
    db_session.add(auction)
    await db_session.flush()

    bid = AuctionBid(
        auction_id=auction.auction_id,
        bidder_id=student_buyer.user_id,
        amount=Decimal("110000"),
        created_at=now - timedelta(minutes=30),
    )
    db_session.add(bid)
    await db_session.commit()

    # Seller attempts cancel via public seller endpoint
    with auth_patch(student_seller):
        resp = await test_client.post(f"/api/v1/auctions/{auction.auction_id}/cancel")
        assert resp.status_code == 400
        assert "lượt đặt giá" in resp.json()["detail"] or "bid" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_product_restore_never_revives_cancelled_auction(
    test_client: AsyncClient,
    admin_user: User,
    open_product_report: Report,
    sample_product: Product,
    db_session: AsyncSession,
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sample_product.listing_type = ListingType.AUCTION.value
    auction = Auction(
        product_id=sample_product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("10000"),
        status=AuctionStatus.ACTIVE.value,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
    )
    db_session.add(auction)
    await db_session.commit()

    with auth_patch(admin_user):
        # 1. Hide
        await test_client.post(
            f"/api/v1/admin/reports/{open_product_report.report_id}/enforcement",
            json={"action": "PRODUCT_HIDE"},
        )
        await db_session.refresh(auction)
        assert auction.status == AuctionStatus.CANCELLED.value

        # 2. Restore
        await test_client.post(
            f"/api/v1/admin/reports/{open_product_report.report_id}/enforcement",
            json={"action": "PRODUCT_RESTORE"},
        )
        await db_session.refresh(auction)
        # Auction must NEVER become ACTIVE or SCHEDULED again!
        assert auction.status == AuctionStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_ended_auction_before_product_hide_preserved_but_checkout_blocked(
    test_client: AsyncClient,
    admin_user: User,
    student_buyer: User,
    open_product_report: Report,
    sample_product: Product,
    db_session: AsyncSession,
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sample_product.listing_type = ListingType.AUCTION.value
    sample_product.stock = 1
    sample_product.reserved_stock = 1

    auction = Auction(
        product_id=sample_product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("10000"),
        final_price=Decimal("150000"),
        winner_id=student_buyer.user_id,
        status=AuctionStatus.ENDED.value,
        starts_at=now - timedelta(hours=5),
        ends_at=now - timedelta(hours=1),
        winner_checkout_deadline=now + timedelta(hours=23),
    )
    db_session.add(auction)
    await db_session.commit()

    with auth_patch(admin_user):
        # Admin hides product
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_product_report.report_id}/enforcement",
            json={"action": "PRODUCT_HIDE"},
        )
        assert resp.status_code == 200

        await db_session.refresh(auction)
        # Ended auction is historical: status, winner, final_price untouched
        assert auction.status == AuctionStatus.ENDED.value
        assert auction.winner_id == student_buyer.user_id
        assert auction.final_price == Decimal("150000")

    # Winner attempts checkout on BLOCKED product
    with auth_patch(student_buyer):
        checkout_payload = {
            "payment_method": "CASH_ON_MEETUP",
            "fulfillment_method": "MEETUP",
            "meetup_place": "Cổng trường PTIT",
            "contact_name": "Người Thắng",
            "contact_phone": "0912000002",
        }
        resp_co = await test_client.post(
            f"/api/v1/auctions/{auction.auction_id}/checkout", json=checkout_payload
        )
        assert resp_co.status_code == 400
        assert "quản trị viên ẩn" in resp_co.json()["detail"]


@pytest.mark.asyncio
async def test_create_auction_blocked_product_fails(
    test_client: AsyncClient, student_seller: User, sample_product: Product, db_session: AsyncSession
):
    sample_product.moderation_status = ProductModerationStatus.BLOCKED.value
    await db_session.commit()

    payload = {
        "product_id": sample_product.product_id,
        "bid_step": 10000,
        "duration_minutes": 120,
    }
    with auth_patch(student_seller):
        resp = await test_client.post("/api/v1/auctions", json=payload)
        assert resp.status_code == 400
        assert "quản trị viên ẩn" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_place_bid_blocked_product_fails(
    test_client: AsyncClient,
    student_buyer: User,
    sample_product: Product,
    db_session: AsyncSession,
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sample_product.listing_type = ListingType.AUCTION.value
    sample_product.moderation_status = ProductModerationStatus.BLOCKED.value

    auction = Auction(
        product_id=sample_product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("10000"),
        status=AuctionStatus.ACTIVE.value,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
    )
    db_session.add(auction)
    await db_session.commit()

    with auth_patch(student_buyer):
        resp = await test_client.post(
            f"/api/v1/auctions/{auction.auction_id}/bids", json={"amount": 100000}
        )
        assert resp.status_code == 400
        assert "kiểm duyệt" in resp.json()["detail"] or "bị ẩn" in resp.json()["detail"]


# ==============================================================================
# 4. PUBLIC DISCOVERY & VISIBILITY TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_public_product_feed_and_search_excludes_blocked_product(
    test_client: AsyncClient, sample_product: Product, db_session: AsyncSession
):
    # When CLEAR
    resp_feed1 = await test_client.get("/api/v1/products")
    ids1 = [p["product_id"] for p in resp_feed1.json()["items"]]
    assert sample_product.product_id in ids1

    # Block product
    sample_product.moderation_status = ProductModerationStatus.BLOCKED.value
    await db_session.commit()

    # 1. Feed
    resp_feed2 = await test_client.get("/api/v1/products")
    ids2 = [p["product_id"] for p in resp_feed2.json()["items"]]
    assert sample_product.product_id not in ids2

    # 2. Search
    resp_search = await test_client.get(f"/api/v1/products?q={sample_product.title[:4]}")
    ids_search = [p["product_id"] for p in resp_search.json()["items"]]
    assert sample_product.product_id not in ids_search

    # 3. Category
    resp_cat = await test_client.get(f"/api/v1/products?category_id={sample_product.category_id}")
    ids_cat = [p["product_id"] for p in resp_cat.json()["items"]]
    assert sample_product.product_id not in ids_cat

    # 4. Seller filter (public profile listing)
    resp_seller = await test_client.get(f"/api/v1/products?seller_id={sample_product.seller_id}")
    ids_seller = [p["product_id"] for p in resp_seller.json()["items"]]
    assert sample_product.product_id not in ids_seller


@pytest.mark.asyncio
async def test_product_detail_public_404_vs_owner_view(
    test_client: AsyncClient,
    student_buyer: User,
    student_seller: User,
    sample_product: Product,
    db_session: AsyncSession,
):
    sample_product.moderation_status = ProductModerationStatus.BLOCKED.value
    await db_session.commit()

    # 1. Ordinary buyer -> 404
    with auth_patch(student_buyer):
        resp_buyer = await test_client.get(f"/api/v1/products/{sample_product.product_id}")
        assert resp_buyer.status_code == 404

    # 2. Unauthenticated buyer -> 404
    resp_anon = await test_client.get(f"/api/v1/products/{sample_product.product_id}")
    assert resp_anon.status_code == 404

    # 3. Owner seller -> 200, shows BLOCKED
    with auth_patch(student_seller):
        resp_owner = await test_client.get(f"/api/v1/products/{sample_product.product_id}")
        assert resp_owner.status_code == 200
        data = resp_owner.json()
        assert data["moderation_status"] == "BLOCKED"
        assert data["product_id"] == sample_product.product_id


@pytest.mark.asyncio
async def test_seller_my_products_includes_blocked_product(
    test_client: AsyncClient, student_seller: User, sample_product: Product, db_session: AsyncSession
):
    sample_product.moderation_status = ProductModerationStatus.BLOCKED.value
    await db_session.commit()

    with auth_patch(student_seller):
        resp = await test_client.get("/api/v1/products/me")
        assert resp.status_code == 200
        items = resp.json()["items"]
        found = next((p for p in items if p["product_id"] == sample_product.product_id), None)
        assert found is not None
        assert found["moderation_status"] == "BLOCKED"


@pytest.mark.asyncio
async def test_seller_mutations_preserve_blocked_status(
    test_client: AsyncClient, student_seller: User, sample_product: Product, db_session: AsyncSession
):
    sample_product.moderation_status = ProductModerationStatus.BLOCKED.value
    await db_session.commit()

    with auth_patch(student_seller):
        # Update title, price, description, status
        resp = await test_client.patch(
            f"/api/v1/products/{sample_product.product_id}",
            json={
                "title": "Tiêu đề mới của seller",
                "price": 2000000,
                "status": "HIDDEN",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["moderation_status"] == "BLOCKED"

        await db_session.refresh(sample_product)
        assert sample_product.moderation_status == ProductModerationStatus.BLOCKED.value
        assert sample_product.title == "Tiêu đề mới của seller"
        assert sample_product.status == ProductStatus.HIDDEN.value


# ==============================================================================
# 5. FAVORITES GATING TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_favorites_list_and_ids_exclude_blocked_product(
    test_client: AsyncClient,
    student_buyer: User,
    sample_product: Product,
    admin_user: User,
    open_product_report: Report,
    db_session: AsyncSession,
):
    # Buyer favorites product
    fav = Favorite(user_id=student_buyer.user_id, product_id=sample_product.product_id)
    db_session.add(fav)
    await db_session.commit()

    with auth_patch(student_buyer):
        # 1. When CLEAR -> both endpoints return it
        resp_list1 = await test_client.get("/api/v1/favorites")
        assert resp_list1.status_code == 200
        assert any(p["product_id"] == sample_product.product_id for p in resp_list1.json()["items"])

        resp_ids1 = await test_client.get("/api/v1/favorites/ids")
        assert resp_ids1.status_code == 200
        assert sample_product.product_id in resp_ids1.json()["product_ids"]

    # 2. Admin blocks product
    with auth_patch(admin_user):
        await test_client.post(
            f"/api/v1/admin/reports/{open_product_report.report_id}/enforcement",
            json={"action": "PRODUCT_HIDE"},
        )

    with auth_patch(student_buyer):
        # Excluded from favorites list
        resp_list2 = await test_client.get("/api/v1/favorites")
        assert resp_list2.status_code == 200
        assert not any(p["product_id"] == sample_product.product_id for p in resp_list2.json()["items"])

        # Excluded from favorite IDs
        resp_ids2 = await test_client.get("/api/v1/favorites/ids")
        assert resp_ids2.status_code == 200
        assert sample_product.product_id not in resp_ids2.json()["product_ids"]

    # Favorite row in DB was NOT deleted
    fav_check = await db_session.execute(
        select(Favorite).where(
            Favorite.user_id == student_buyer.user_id,
            Favorite.product_id == sample_product.product_id,
        )
    )
    assert fav_check.scalar_one_or_none() is not None

    # 3. Admin restores product
    with auth_patch(admin_user):
        await test_client.post(
            f"/api/v1/admin/reports/{open_product_report.report_id}/enforcement",
            json={"action": "PRODUCT_RESTORE"},
        )

    with auth_patch(student_buyer):
        # Appears again!
        resp_list3 = await test_client.get("/api/v1/favorites")
        assert any(p["product_id"] == sample_product.product_id for p in resp_list3.json()["items"])
        resp_ids3 = await test_client.get("/api/v1/favorites/ids")
        assert sample_product.product_id in resp_ids3.json()["product_ids"]


# ==============================================================================
# 6. DIRECT COMMERCE GATING TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_direct_order_creation_blocked_product_fails(
    test_client: AsyncClient,
    student_buyer: User,
    sample_product: Product,
    db_session: AsyncSession,
):
    sample_product.moderation_status = ProductModerationStatus.BLOCKED.value
    await db_session.commit()

    order_payload = {
        "product_id": sample_product.product_id,
        "quantity": 1,
        "payment_method": "CASH_ON_MEETUP",
        "fulfillment_method": "MEETUP",
        "meetup_place": "Cổng trường PTIT",
        "contact_name": "Sinh Viên Mua",
        "contact_phone": "0912000002",
    }
    with auth_patch(student_buyer):
        resp = await test_client.post("/api/v1/orders", json=order_payload)
        assert resp.status_code == 404
        assert "không tồn tại hoặc không khả dụng" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_existing_order_created_before_hide_remains_valid(
    test_client: AsyncClient,
    admin_user: User,
    student_buyer: User,
    sample_product: Product,
    open_product_report: Report,
    db_session: AsyncSession,
):
    # Pre-existing Order
    order = Order(
        order_code="ORD-LEGACY-001",
        buyer_id=student_buyer.user_id,
        seller_id=sample_product.seller_id,
        total_amount=Decimal("1500000"),
        payment_method=PaymentMethod.CASH_ON_MEETUP.value,
        payment_status=PaymentStatus.UNPAID.value,
        fulfillment_method=FulfillmentMethod.MEETUP.value,
        contact_name="Sinh Viên Mua",
        contact_phone="0912000002",
        status=OrderStatus.PENDING.value,
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.order_id,
        product_id=sample_product.product_id,
        product_title=sample_product.title,
        price_at_purchase=Decimal("1500000"),
        quantity=1,
    )
    db_session.add(item)
    await db_session.commit()

    # Admin hides product
    with auth_patch(admin_user):
        resp = await test_client.post(
            f"/api/v1/admin/reports/{open_product_report.report_id}/enforcement",
            json={"action": "PRODUCT_HIDE"},
        )
        assert resp.status_code == 200

    # Verify Order is completely untouched
    await db_session.refresh(order)
    assert order.status == OrderStatus.PENDING.value
    assert order.payment_status == PaymentStatus.UNPAID.value
    assert order.total_amount == Decimal("1500000")


# ==============================================================================
# 7. ADMIN REPORT QUEUE STATE FILTER TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_queue_state_filter(
    test_client: AsyncClient,
    admin_user: User,
    student_reporter: User,
    sample_product: Product,
    db_session: AsyncSession,
):
    # Create 4 reports with different statuses
    r_open = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.PRODUCT.value,
        target_id=sample_product.product_id,
        reason=ReportReason.OTHER.value,
        status=ReportStatus.OPEN.value,
    )
    r_reviewing = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.PRODUCT.value,
        target_id=sample_product.product_id,
        reason=ReportReason.OTHER.value,
        status=ReportStatus.REVIEWING.value,
    )
    r_resolved = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.PRODUCT.value,
        target_id=sample_product.product_id,
        reason=ReportReason.OTHER.value,
        status=ReportStatus.RESOLVED.value,
    )
    r_rejected = Report(
        reporter_id=student_reporter.user_id,
        target_type=ReportTargetType.PRODUCT.value,
        target_id=sample_product.product_id,
        reason=ReportReason.OTHER.value,
        status=ReportStatus.REJECTED.value,
    )
    db_session.add_all([r_open, r_reviewing, r_resolved, r_rejected])
    await db_session.commit()

    with auth_patch(admin_user):
        # 1. NEEDS_ACTION filter
        resp_needs = await test_client.get("/api/v1/admin/reports?queue_state=NEEDS_ACTION")
        assert resp_needs.status_code == 200
        items_needs = resp_needs.json()["items"]
        for it in items_needs:
            assert it["status"] in ["OPEN", "REVIEWING"]
            assert it["workflow_state"] != "NEEDS_ACTION"  # Invariant: single report never has workflow_state = NEEDS_ACTION!

        # 2. COMPLETED filter
        resp_comp = await test_client.get("/api/v1/admin/reports?queue_state=COMPLETED")
        assert resp_comp.status_code == 200
        items_comp = resp_comp.json()["items"]
        for it in items_comp:
            assert it["status"] in ["RESOLVED", "REJECTED"]
            assert it["workflow_state"] == "COMPLETED"


# ==============================================================================
# 8. CONCURRENCY & RACE CONDITIONS
# ==============================================================================

@pytest.mark.asyncio
async def test_concurrency_two_admins_product_hide():
    """
    Test that concurrent PRODUCT_HIDE calls from separate DB connections
    properly lock (Report FOR UPDATE -> Product FOR UPDATE -> Auction FOR UPDATE).
    Exactly one succeeds and commits; the other receives 400 (already BLOCKED) or 409.
    """
    rand = uuid.uuid4().hex[:6]
    async with TestSessionLocal() as session_setup:
        admin1 = User(
            email=f"admin_c1_{rand}@ptit.edu.vn",
            full_name="Admin C1",
            role=UserRole.ADMIN.value,
            status=UserStatus.ACTIVE,
        )
        admin2 = User(
            email=f"admin_c2_{rand}@ptit.edu.vn",
            full_name="Admin C2",
            role=UserRole.ADMIN.value,
            status=UserStatus.ACTIVE,
        )
        seller = User(
            email=f"seller_c_{rand}@ptit.edu.vn",
            full_name="Seller C",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
        )
        cat = Category(name=f"Cat {rand}", slug=f"cat-{rand}")
        session_setup.add_all([admin1, admin2, seller, cat])
        await session_setup.flush()

        prod = Product(
            seller_id=seller.user_id,
            category_id=cat.category_id,
            title=f"Sản phẩm concurrency {rand}",
            description="Mô tả",
            price=Decimal("100000"),
            stock=1,
            reserved_stock=0,
            status=ProductStatus.AVAILABLE.value,
            moderation_status=ProductModerationStatus.CLEAR.value,
            approval_status="APPROVED",
            listing_type=ListingType.FIXED_PRICE.value,
            is_deleted=False,
        )
        session_setup.add(prod)
        await session_setup.flush()

        rep = Report(
            reporter_id=seller.user_id,
            target_type=ReportTargetType.PRODUCT.value,
            target_id=prod.product_id,
            reason=ReportReason.FAKE_ITEM.value,
            status=ReportStatus.OPEN.value,
        )
        session_setup.add(rep)
        await session_setup.commit()

        report_id = rep.report_id
        product_id = prod.product_id
        admin1_id = admin1.user_id
        admin2_id = admin2.user_id
        seller_id = seller.user_id
        category_id = cat.category_id

    try:
        async with TestSessionLocal() as session1, TestSessionLocal() as session2:
            admin1_obj = await session1.get(User, admin1_id)
            admin2_obj = await session2.get(User, admin2_id)

            svc1 = ReportService(session1)
            svc2 = ReportService(session2)

            results = await asyncio.gather(
                svc1.enforce_product_action(admin1_obj, report_id, ModerationActionType.PRODUCT_HIDE),
                svc2.enforce_product_action(admin2_obj, report_id, ModerationActionType.PRODUCT_HIDE),
                return_exceptions=True,
            )

            successes = [r for r in results if not isinstance(r, Exception)]
            exceptions = [r for r in results if isinstance(r, Exception)]

            # Exactly 1 succeeds, 1 fails safely
            assert len(successes) == 1
            assert len(exceptions) == 1
            assert isinstance(exceptions[0], HTTPException)
            assert exceptions[0].status_code in (400, 409)
    finally:
        async with TestSessionLocal() as s:
            await s.execute(text("DELETE FROM moderation_actions WHERE report_id = :rid"), {"rid": report_id})
            await s.execute(text("DELETE FROM reports WHERE report_id = :rid"), {"rid": report_id})
            await s.execute(text("DELETE FROM products WHERE product_id = :pid"), {"pid": product_id})
            await s.execute(text("DELETE FROM users WHERE user_id IN (:u1, :u2, :u3)"), {"u1": admin1_id, "u2": admin2_id, "u3": seller_id})
            await s.execute(text("DELETE FROM categories WHERE category_id = :cid"), {"cid": category_id})
            await s.commit()


@pytest.mark.asyncio
async def test_race_bid_vs_product_hide():
    """
    Race: Bid vs Admin PRODUCT_HIDE.
    The system must never allow: Product BLOCKED + a bid committed afterward
    to an auction that should be CANCELLED.
    """
    rand = uuid.uuid4().hex[:6]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with TestSessionLocal() as session_setup:
        admin = User(
            email=f"admin_bid_{rand}@ptit.edu.vn",
            full_name="Admin Bid Race",
            role=UserRole.ADMIN.value,
            status=UserStatus.ACTIVE,
        )
        seller = User(
            email=f"seller_bid_{rand}@ptit.edu.vn",
            full_name="Seller Bid Race",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
        )
        bidder = User(
            email=f"bidder_bid_{rand}@ptit.edu.vn",
            full_name="Bidder Race",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
        )
        cat = Category(name=f"Cat {rand}", slug=f"cat-{rand}")
        session_setup.add_all([admin, seller, bidder, cat])
        await session_setup.flush()

        prod = Product(
            seller_id=seller.user_id,
            category_id=cat.category_id,
            title=f"SP Đấu giá Race {rand}",
            description="Mô tả",
            price=Decimal("100000"),
            stock=1,
            reserved_stock=1,
            status=ProductStatus.AVAILABLE.value,
            moderation_status=ProductModerationStatus.CLEAR.value,
            approval_status="APPROVED",
            listing_type=ListingType.AUCTION.value,
            is_deleted=False,
        )
        session_setup.add(prod)
        await session_setup.flush()

        auction = Auction(
            product_id=prod.product_id,
            starting_price=Decimal("100000"),
            bid_step=Decimal("10000"),
            status=AuctionStatus.ACTIVE.value,
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
        )
        session_setup.add(auction)
        await session_setup.flush()

        rep = Report(
            reporter_id=bidder.user_id,
            target_type=ReportTargetType.PRODUCT.value,
            target_id=prod.product_id,
            reason=ReportReason.FAKE_ITEM.value,
            status=ReportStatus.OPEN.value,
        )
        session_setup.add(rep)
        await session_setup.commit()

        report_id = rep.report_id
        product_id = prod.product_id
        auction_id = auction.auction_id
        admin_id = admin.user_id
        bidder_id = bidder.user_id
        seller_id = seller.user_id
        category_id = cat.category_id

    try:
        async with TestSessionLocal() as session1, TestSessionLocal() as session2:
            admin_obj = await session1.get(User, admin_id)
            bidder_obj = await session2.get(User, bidder_id)

            report_svc = ReportService(session1)
            auction_svc = AuctionService(session2)

            results = await asyncio.gather(
                report_svc.enforce_product_action(admin_obj, report_id, ModerationActionType.PRODUCT_HIDE),
                auction_svc.place_bid(bidder_obj, auction_id, PlaceBidRequest(amount=Decimal("110000"))),
                return_exceptions=True,
            )

        async with TestSessionLocal() as check_session:
            p = await check_session.get(Product, product_id)
            auc = await check_session.get(Auction, auction_id)

            # Product must be BLOCKED
            assert p.moderation_status == ProductModerationStatus.BLOCKED.value
            # Auction must be CANCELLED
            assert auc.status == AuctionStatus.CANCELLED.value
            assert auc.winner_id is None

            bids_res = await check_session.execute(
                select(AuctionBid).where(AuctionBid.auction_id == auction_id)
            )
            bids = bids_res.scalars().all()
            if not isinstance(results[1], Exception):
                # Bid committed first; preserved in history
                assert len(bids) == 1
                assert bids[0].amount == Decimal("110000")
            else:
                # Enforcement committed first; bid rejected
                assert isinstance(results[1], HTTPException)
                assert results[1].status_code == 400
                assert len(bids) == 0
    finally:
        async with TestSessionLocal() as s:
            await s.execute(text("DELETE FROM auction_bids WHERE auction_id = :aid"), {"aid": auction_id})
            await s.execute(text("DELETE FROM auctions WHERE auction_id = :aid"), {"aid": auction_id})
            await s.execute(text("DELETE FROM moderation_actions WHERE report_id = :rid"), {"rid": report_id})
            await s.execute(text("DELETE FROM reports WHERE report_id = :rid"), {"rid": report_id})
            await s.execute(text("DELETE FROM products WHERE product_id = :pid"), {"pid": product_id})
            await s.execute(text("DELETE FROM users WHERE user_id IN (:u1, :u2, :u3)"), {"u1": admin_id, "u2": bidder_id, "u3": seller_id})
            await s.execute(text("DELETE FROM categories WHERE category_id = :cid"), {"cid": category_id})
            await s.commit()


@pytest.mark.asyncio
async def test_race_direct_order_vs_product_hide():
    """
    Race: Direct order creation vs Admin PRODUCT_HIDE.
    The system must never allow an Order to be created against a BLOCKED product.
    """
    rand = uuid.uuid4().hex[:6]
    async with TestSessionLocal() as session_setup:
        admin = User(
            email=f"admin_ord_{rand}@ptit.edu.vn",
            full_name="Admin Order Race",
            role=UserRole.ADMIN.value,
            status=UserStatus.ACTIVE,
        )
        seller = User(
            email=f"seller_ord_{rand}@ptit.edu.vn",
            full_name="Seller Order Race",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
        )
        buyer = User(
            email=f"buyer_ord_{rand}@ptit.edu.vn",
            full_name="Buyer Order Race",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
        )
        cat = Category(name=f"Cat {rand}", slug=f"cat-{rand}")
        session_setup.add_all([admin, seller, buyer, cat])
        await session_setup.flush()

        prod = Product(
            seller_id=seller.user_id,
            category_id=cat.category_id,
            title=f"SP Direct Order Race {rand}",
            description="Mô tả",
            price=Decimal("200000"),
            stock=1,
            reserved_stock=0,
            status=ProductStatus.AVAILABLE.value,
            moderation_status=ProductModerationStatus.CLEAR.value,
            approval_status="APPROVED",
            listing_type=ListingType.FIXED_PRICE.value,
            is_deleted=False,
        )
        session_setup.add(prod)
        await session_setup.flush()

        rep = Report(
            reporter_id=buyer.user_id,
            target_type=ReportTargetType.PRODUCT.value,
            target_id=prod.product_id,
            reason=ReportReason.FAKE_ITEM.value,
            status=ReportStatus.OPEN.value,
        )
        session_setup.add(rep)
        await session_setup.commit()

        report_id = rep.report_id
        product_id = prod.product_id
        admin_id = admin.user_id
        buyer_id = buyer.user_id
        seller_id = seller.user_id
        category_id = cat.category_id

    created_order_id = None
    try:
        async with TestSessionLocal() as session1, TestSessionLocal() as session2:
            admin_obj = await session1.get(User, admin_id)
            buyer_obj = await session2.get(User, buyer_id)

            report_svc = ReportService(session1)
            order_svc = OrderService(session2)

            order_payload = CreateOrderRequest(
                product_id=product_id,
                quantity=1,
                payment_method=PaymentMethod.CASH_ON_MEETUP,
                fulfillment_method=FulfillmentMethod.MEETUP,
                meetup_place="Cổng trường",
                contact_name="Người Mua",
                contact_phone="0912345678",
            )

            results = await asyncio.gather(
                report_svc.enforce_product_action(admin_obj, report_id, ModerationActionType.PRODUCT_HIDE),
                order_svc.create_direct_order(buyer_obj, order_payload),
                return_exceptions=True,
            )

        async with TestSessionLocal() as check_session:
            p = await check_session.get(Product, product_id)
            assert p.moderation_status == ProductModerationStatus.BLOCKED.value

            if not isinstance(results[1], Exception):
                # Order established first: survives Product Hide
                order_obj = results[1]
                created_order_id = order_obj.order_id
                assert order_obj.status == OrderStatus.PENDING.value
                assert p.reserved_stock == 1
            else:
                # Hide established first: order rejected with 404
                assert isinstance(results[1], HTTPException)
                assert results[1].status_code == 404
                assert p.reserved_stock == 0
    finally:
        async with TestSessionLocal() as s:
            if created_order_id:
                await s.execute(text("DELETE FROM order_items WHERE order_id = :oid"), {"oid": created_order_id})
                await s.execute(text("DELETE FROM orders WHERE order_id = :oid"), {"oid": created_order_id})
            await s.execute(text("DELETE FROM moderation_actions WHERE report_id = :rid"), {"rid": report_id})
            await s.execute(text("DELETE FROM reports WHERE report_id = :rid"), {"rid": report_id})
            await s.execute(text("DELETE FROM products WHERE product_id = :pid"), {"pid": product_id})
            await s.execute(text("DELETE FROM users WHERE user_id IN (:u1, :u2, :u3)"), {"u1": admin_id, "u2": buyer_id, "u3": seller_id})
            await s.execute(text("DELETE FROM categories WHERE category_id = :cid"), {"cid": category_id})
            await s.commit()


@pytest.mark.asyncio
async def test_race_create_auction_vs_product_hide():
    """
    Race: enable_auction vs Admin PRODUCT_HIDE.
    Final state must not become: Product BLOCKED + new ACTIVE auction.
    """
    rand = uuid.uuid4().hex[:6]
    async with TestSessionLocal() as session_setup:
        admin = User(
            email=f"admin_auc_{rand}@ptit.edu.vn",
            full_name="Admin Auc Race",
            role=UserRole.ADMIN.value,
            status=UserStatus.ACTIVE,
        )
        seller = User(
            email=f"seller_auc_{rand}@ptit.edu.vn",
            full_name="Seller Auc Race",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
        )
        cat = Category(name=f"Cat {rand}", slug=f"cat-{rand}")
        session_setup.add_all([admin, seller, cat])
        await session_setup.flush()

        prod = Product(
            seller_id=seller.user_id,
            category_id=cat.category_id,
            title=f"SP Create Auc Race {rand}",
            description="Mô tả",
            price=Decimal("150000"),
            stock=1,
            reserved_stock=0,
            status=ProductStatus.AVAILABLE.value,
            moderation_status=ProductModerationStatus.CLEAR.value,
            approval_status="APPROVED",
            listing_type=ListingType.FIXED_PRICE.value,
            is_deleted=False,
        )
        session_setup.add(prod)
        await session_setup.flush()

        rep = Report(
            reporter_id=seller.user_id,
            target_type=ReportTargetType.PRODUCT.value,
            target_id=prod.product_id,
            reason=ReportReason.OTHER.value,
            status=ReportStatus.OPEN.value,
        )
        session_setup.add(rep)
        await session_setup.commit()

        report_id = rep.report_id
        product_id = prod.product_id
        admin_id = admin.user_id
        seller_id = seller.user_id
        category_id = cat.category_id

    try:
        async with TestSessionLocal() as session1, TestSessionLocal() as session2:
            admin_obj = await session1.get(User, admin_id)
            seller_obj = await session2.get(User, seller_id)

            report_svc = ReportService(session1)
            auction_svc = AuctionService(session2)

            auction_payload = AuctionCreateRequest(
                product_id=product_id,
                bid_step=Decimal("10000"),
                duration_minutes=60,
            )

            results = await asyncio.gather(
                report_svc.enforce_product_action(admin_obj, report_id, ModerationActionType.PRODUCT_HIDE),
                auction_svc.enable_auction(seller_obj, auction_payload),
                return_exceptions=True,
            )

        async with TestSessionLocal() as check_session:
            p = await check_session.get(Product, product_id)
            assert p.moderation_status == ProductModerationStatus.BLOCKED.value

            # Verify no ACTIVE or SCHEDULED auction exists for this blocked product
            auc_res = await check_session.execute(
                select(Auction).where(Auction.product_id == product_id)
            )
            auctions = auc_res.scalars().all()
            for auc in auctions:
                assert auc.status == AuctionStatus.CANCELLED.value
    finally:
        async with TestSessionLocal() as s:
            await s.execute(text("DELETE FROM auctions WHERE product_id = :pid"), {"pid": product_id})
            await s.execute(text("DELETE FROM moderation_actions WHERE report_id = :rid"), {"rid": report_id})
            await s.execute(text("DELETE FROM reports WHERE report_id = :rid"), {"rid": report_id})
            await s.execute(text("DELETE FROM products WHERE product_id = :pid"), {"pid": product_id})
            await s.execute(text("DELETE FROM users WHERE user_id IN (:u1, :u2)"), {"u1": admin_id, "u2": seller_id})
            await s.execute(text("DELETE FROM categories WHERE category_id = :cid"), {"cid": category_id})
            await s.commit()
