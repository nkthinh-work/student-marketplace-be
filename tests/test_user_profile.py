from datetime import datetime, timezone, timedelta
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.auctions.models import Auction, AuctionStatus
from app.modules.categories.models import Category
from app.modules.products.models import (
    ListingType,
    Product,
    ProductApprovalStatus,
    ProductModerationStatus,
    ProductStatus,
)
from app.modules.reports.models import Report, ReportReason, ReportStatus, ReportTargetType
from app.modules.users.capability_models import CapabilityType, UserCapabilityRestriction
from app.modules.users.models import User, UserRole, UserStatus
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
async def sample_user(db_session: AsyncSession) -> User:
    user = User(
        email="test_student@ptit.edu.vn",
        full_name="Nguyễn Khắc Thịnh",
        phone="0352866196",
        avatar_url="https://lh3.googleusercontent.com/a/test_avatar",
        bio="Sinh viên D20 PTIT",
        delivery_area="Hà Đông, Thanh Xuân, Cầu Giấy",
        default_meetup_area="Legacy Căn tin A2",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
        bank_bin="970422",
        bank_account_number="0123456789",
        bank_account_name="NGUYEN KHAC THINH",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        email="other_student@ptit.edu.vn",
        full_name="Trần Văn Buyer",
        phone="0987654321",
        avatar_url=None,
        bio=None,
        delivery_area=None,
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def banned_user(db_session: AsyncSession) -> User:
    user = User(
        email="banned_student@ptit.edu.vn",
        full_name="Lê Bị Khóa",
        role=UserRole.STUDENT.value,
        status=UserStatus.BANNED,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def sample_product(db_session: AsyncSession, sample_user: User) -> Product:
    cat = Category(name="Giáo trình", slug="giao-trinh")
    db_session.add(cat)
    await db_session.flush()

    prod = Product(
        seller_id=sample_user.user_id,
        category_id=cat.category_id,
        title="Giáo trình Giải tích 1",
        description="Sách còn mới 95%",
        listing_type=ListingType.FIXED_PRICE,
        price=50000,
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE,
        approval_status="APPROVED",
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


# =====================================================================
# 1. PROFILE UPDATE & DELIVERY AREA
# =====================================================================

@pytest.mark.asyncio
async def test_user_update_delivery_area_success(test_client: AsyncClient, sample_user: User):
    with auth_patch(sample_user):
        res = await test_client.patch(
            "/api/v1/users/me",
            json={
                "delivery_area": "Toàn quận Hà Đông, KTX PTIT",
                "bio": "Học ngành CNTT",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["delivery_area"] == "Toàn quận Hà Đông, KTX PTIT"
    assert data["bio"] == "Học ngành CNTT"
    assert data["full_name"] == sample_user.full_name


# =====================================================================
# 2. PUBLIC USER PROFILE
# =====================================================================

@pytest.mark.asyncio
async def test_get_public_user_profile_success(test_client: AsyncClient, sample_user: User):
    # Unauthenticated client can read public profile
    res = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == sample_user.user_id
    assert data["full_name"] == "Nguyễn Khắc Thịnh"
    assert data["avatar_url"] == "https://lh3.googleusercontent.com/a/test_avatar"
    assert data["bio"] == "Sinh viên D20 PTIT"
    assert data["delivery_area"] == "Hà Đông, Thanh Xuân, Cầu Giấy"
    assert data["role"] == "STUDENT"

    # Strict Privacy: Must NOT expose sensitive/private fields
    assert "email" not in data
    assert data["phone"] is None  # Phone is None unless show_phone_publicly is True
    assert "bank_bin" not in data
    assert "bank_account_number" not in data
    assert "bank_account_name" not in data
    assert "default_meetup_area" not in data


@pytest.mark.asyncio
async def test_get_public_user_profile_banned_or_inactive_404(test_client: AsyncClient, banned_user: User):
    res = await test_client.get(f"/api/v1/users/{banned_user.user_id}")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_get_public_user_profile_nonexistent_404(test_client: AsyncClient):
    res = await test_client.get("/api/v1/users/999999")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_public_profile_active_listing_count_invariants(
    test_client: AsyncClient,
    sample_user: User,
    other_user: User,
    db_session: AsyncSession,
):
    """
    Tests Bug #2 canonical public selling count invariants:
    - PENDING + AVAILABLE => active_listing_count == 0 (absent from public product listing)
    - APPROVED + AVAILABLE + CLEAR => active_listing_count == 1
    - REJECTED => 0
    - DRAFT => 0
    - HIDDEN => 0
    - BLOCKED => 0
    - is_deleted == True => 0
    - Active SELL capability restriction => 0 (revoked restriction restores count)
    - AUCTION listing requires active auction to count publicly
    - Private /api/v1/products/me maintains private seller management semantics
    """
    cat = Category(name="Giáo trình IT", slug="giao-trinh-it")
    db_session.add(cat)
    await db_session.flush()

    # 1. Product created: PENDING + AVAILABLE
    prod = Product(
        seller_id=sample_user.user_id,
        category_id=cat.category_id,
        title="Sách Cấu trúc dữ liệu",
        description="Còn mới 99%",
        listing_type=ListingType.FIXED_PRICE.value,
        price=60000,
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status=ProductApprovalStatus.PENDING.value,
        moderation_status=ProductModerationStatus.CLEAR.value,
    )
    db_session.add(prod)
    await db_session.commit()

    # Public profile must show active_listing_count == 0
    res = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert res.status_code == 200
    assert res.json()["active_listing_count"] == 0

    # Public products query for seller must return 0 items
    pub_res = await test_client.get(f"/api/v1/products?seller_id={sample_user.user_id}")
    assert pub_res.status_code == 200
    assert len(pub_res.json()["items"]) == 0

    # Private seller management /products/me must still return the pending product
    with auth_patch(sample_user):
        priv_res = await test_client.get("/api/v1/products/me")
        assert priv_res.status_code == 200
        assert len(priv_res.json()["items"]) == 1

    # 2. Product APPROVED: count becomes 1
    prod.approval_status = ProductApprovalStatus.APPROVED.value
    await db_session.commit()

    res = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert res.status_code == 200
    assert res.json()["active_listing_count"] == 1

    pub_res = await test_client.get(f"/api/v1/products?seller_id={sample_user.user_id}")
    assert pub_res.status_code == 200
    assert len(pub_res.json()["items"]) == 1

    # 3. Product REJECTED: count becomes 0
    prod.approval_status = ProductApprovalStatus.REJECTED.value
    await db_session.commit()
    res = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert res.json()["active_listing_count"] == 0

    # 4. Product DRAFT: count becomes 0
    prod.approval_status = ProductApprovalStatus.DRAFT.value
    await db_session.commit()
    res = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert res.json()["active_listing_count"] == 0

    # 5. Product HIDDEN: count becomes 0
    prod.approval_status = ProductApprovalStatus.APPROVED.value
    prod.status = ProductStatus.HIDDEN.value
    await db_session.commit()
    res = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert res.json()["active_listing_count"] == 0

    # 6. Product BLOCKED by moderation: count becomes 0
    prod.status = ProductStatus.AVAILABLE.value
    prod.moderation_status = ProductModerationStatus.BLOCKED.value
    await db_session.commit()
    res = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert res.json()["active_listing_count"] == 0

    # Also SOLD_OUT: count becomes 0
    prod.moderation_status = ProductModerationStatus.CLEAR.value
    prod.status = ProductStatus.SOLD_OUT.value
    await db_session.commit()
    res = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert res.json()["active_listing_count"] == 0


    # 7. Product is_deleted == True: count becomes 0
    prod.status = ProductStatus.AVAILABLE.value
    prod.is_deleted = True
    await db_session.commit()
    res = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert res.json()["active_listing_count"] == 0

    # Restore product to fully eligible state (count is 1)
    prod.is_deleted = False
    prod.status = ProductStatus.AVAILABLE.value
    prod.approval_status = ProductApprovalStatus.APPROVED.value
    prod.moderation_status = ProductModerationStatus.CLEAR.value
    await db_session.commit()
    res = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert res.json()["active_listing_count"] == 1

    # 8. Active SELL capability restriction => count becomes 0
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    report = Report(
        reporter_id=other_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=sample_user.user_id,
        reason=ReportReason.SCAM.value,
        status=ReportStatus.RESOLVED.value,
    )
    db_session.add(report)
    await db_session.flush()

    sell_restr = UserCapabilityRestriction(
        user_id=sample_user.user_id,
        source_report_id=report.report_id,
        imposed_by=other_user.user_id,
        capability=CapabilityType.SELL.value,
        starts_at=now_utc - timedelta(hours=1),
        expires_at=None,
    )
    db_session.add(sell_restr)
    await db_session.commit()

    res = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert res.json()["active_listing_count"] == 0

    # Revoking restriction restores count to 1
    sell_restr.revoked_at = now_utc
    await db_session.commit()

    res = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert res.json()["active_listing_count"] == 1

    # 9. Auction product: requires active auction to count publicly
    auction_prod = Product(
        seller_id=sample_user.user_id,
        category_id=cat.category_id,
        title="Laptop cũ đấu giá",
        description="Đấu giá gây quỹ",
        listing_type=ListingType.AUCTION.value,
        price=100000,
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status=ProductApprovalStatus.APPROVED.value,
        moderation_status=ProductModerationStatus.CLEAR.value,
    )
    db_session.add(auction_prod)
    await db_session.commit()

    # Without active auction, auction product does not increment count
    res = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert res.json()["active_listing_count"] == 1

    # With active auction, count becomes 2
    act_auction = Auction(
        product_id=auction_prod.product_id,
        starting_price=100000,
        bid_step=10000,
        starts_at=now_utc.replace(tzinfo=None) - timedelta(hours=1),
        ends_at=now_utc.replace(tzinfo=None) + timedelta(hours=24),
        status=AuctionStatus.ACTIVE.value,
    )
    db_session.add(act_auction)
    await db_session.commit()

    res = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert res.json()["active_listing_count"] == 2



# =====================================================================
# 3. SELLER PRODUCT DETAIL EXPOSES DELIVERY AREA
# =====================================================================

@pytest.mark.asyncio
async def test_product_detail_seller_delivery_area(test_client: AsyncClient, sample_product: Product):
    res = await test_client.get(f"/api/v1/products/{sample_product.product_id}")
    assert res.status_code == 200
    data = res.json()
    seller = data["seller"]
    assert seller["delivery_area"] == "Hà Đông, Thanh Xuân, Cầu Giấy"


# =====================================================================
# 4. ORDER CREATION DOES NOT USE PROFILE DELIVERY AREA OR DEFAULT MEETUP
# =====================================================================

@pytest.mark.asyncio
async def test_order_creation_requires_explicit_meetup_place(
    test_client: AsyncClient, other_user: User, sample_product: Product
):
    # MEETUP without meetup_place -> 400
    with auth_patch(other_user):
        res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": sample_product.product_id,
                "quantity": 1,
                "fulfillment_method": "MEETUP",
                "payment_method": "CASH_ON_MEETUP",
                "contact_name": "Buyer Name",
                "contact_phone": "0987654321",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert res.status_code in (400, 422)
    res_text = res.text
    assert "Vui lòng nhập địa điểm hẹn gặp" in res_text


@pytest.mark.asyncio
async def test_order_creation_explicit_meetup_and_shipping(
    test_client: AsyncClient, other_user: User, sample_product: Product
):
    # Explicit meetup_place creates order successfully
    with auth_patch(other_user):
        res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": sample_product.product_id,
                "quantity": 1,
                "fulfillment_method": "MEETUP",
                "payment_method": "CASH_ON_MEETUP",
                "meetup_place": "Cổng phụ đường Nguyễn Trãi",
                "contact_name": "Buyer Name",
                "contact_phone": "0987654321",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert res.status_code == 201
    order_data = res.json()
    assert order_data["meetup_place"] == "Cổng phụ đường Nguyễn Trãi"
    # Verify delivery_area was NOT copied into meetup_place
    assert order_data["meetup_place"] != other_user.delivery_area


# =====================================================================
# 5. SOCIAL LINKS VALIDATION & PHONE PUBLICITY
# =====================================================================

@pytest.mark.asyncio
async def test_user_update_social_links_success(test_client: AsyncClient, sample_user: User):
    with auth_patch(sample_user):
        res = await test_client.patch(
            "/api/v1/users/me",
            json={
                "social_links": [
                    {"platform": "FACEBOOK", "url": "https://facebook.com/thinh123"},
                    {"platform": "INSTAGRAM", "url": "https://instagram.com/thinh.ptit"},
                    {"platform": "ZALO", "url": "https://zalo.me/0352866196"},
                ],
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert res.status_code == 200
    data = res.json()
    assert len(data["social_links"]) == 3
    assert data["social_links"][0]["platform"] == "FACEBOOK"
    assert data["social_links"][0]["url"] == "https://facebook.com/thinh123"

    # Verify public profile exposes social links
    pub_res = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert pub_res.status_code == 200
    pub_data = pub_res.json()
    assert len(pub_data["social_links"]) == 3


@pytest.mark.asyncio
async def test_user_update_social_links_domain_mismatch_rejected(
    test_client: AsyncClient, sample_user: User
):
    with auth_patch(sample_user):
        res = await test_client.patch(
            "/api/v1/users/me",
            json={
                "social_links": [
                    {"platform": "FACEBOOK", "url": "https://docs.google.com/document/d/12345"},
                ],
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert res.status_code == 422
    assert "Liên kết không thuộc Facebook" in res.text


@pytest.mark.asyncio
async def test_phone_publicity_toggle(test_client: AsyncClient, sample_user: User):
    # 1. By default, phone is hidden on public profile
    res1 = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert res1.status_code == 200
    assert res1.json()["phone"] is None

    # 2. Enable show_phone_publicly
    with auth_patch(sample_user):
        update_res = await test_client.patch(
            "/api/v1/users/me",
            json={"show_phone_publicly": True},
            headers={"Authorization": "Bearer mock"},
        )
    assert update_res.status_code == 200
    assert update_res.json()["show_phone_publicly"] is True

    # 3. Now public profile exposes phone
    res2 = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert res2.status_code == 200
    assert res2.json()["phone"] == "0352866196"

    # 4. Disable show_phone_publicly
    with auth_patch(sample_user):
        update_res2 = await test_client.patch(
            "/api/v1/users/me",
            json={"show_phone_publicly": False},
            headers={"Authorization": "Bearer mock"},
        )
    assert update_res2.status_code == 200

    # 5. Public profile hides phone again
    res3 = await test_client.get(f"/api/v1/users/{sample_user.user_id}")
    assert res3.status_code == 200
    assert res3.json()["phone"] is None


# =====================================================================
# 6. PUBLIC PRODUCTS FILTER BY SELLER & SOLD PRODUCTS SUMMARY
# =====================================================================

@pytest.mark.asyncio
async def test_products_filter_by_seller_id(
    test_client: AsyncClient, sample_user: User, other_user: User, sample_product: Product
):
    # Filter by sample_user -> returns sample_product
    res = await test_client.get(f"/api/v1/products?seller_id={sample_user.user_id}")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["product_id"] == sample_product.product_id

    # Filter by other_user -> returns empty
    res2 = await test_client.get(f"/api/v1/products?seller_id={other_user.user_id}")
    assert res2.status_code == 200
    assert len(res2.json()["items"]) == 0


@pytest.mark.asyncio
async def test_user_sold_products_endpoint_privacy(
    test_client: AsyncClient, sample_user: User
):
    res = await test_client.get(f"/api/v1/users/{sample_user.user_id}/sold-products")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total_count" in data
    assert isinstance(data["items"], list)

