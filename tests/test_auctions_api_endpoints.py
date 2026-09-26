from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auctions.models import Auction, AuctionBid, AuctionStatus
from app.modules.categories.models import Category
from app.modules.orders.models import FulfillmentMethod, PaymentMethod
from app.modules.products.models import ListingType, Product, ProductStatus
from app.modules.users.models import User, UserAuthIdentity, UserRole, UserStatus


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> Category:
    cat = Category(name="Thiết Bị Âm Thanh", slug=f"am-thanh-{uuid4().hex[:6]}", is_deleted=False)
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def seller(db_session: AsyncSession) -> User:
    user = User(
        email=f"seller_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Nguyễn Văn Bán",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_seller_api",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def buyer(db_session: AsyncSession) -> User:
    user = User(
        email=f"buyer_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Trần Thị Mua",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_buyer_api",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def product(db_session: AsyncSession, seller: User, sample_category: Category) -> Product:
    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Tai nghe Sony WH-1000XM4",
        description="Tai nghe chống ồn đỉnh cao",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal("3500000"),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        view_count=0,
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


@pytest.mark.asyncio
async def test_api_auction_lifecycle(
    test_client: AsyncClient, db_session: AsyncSession, seller: User, buyer: User, product: Product
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 1. Seller enables auction via POST /api/v1/auctions
    with patch("app.modules.auth.dependencies.verify_firebase_token") as mock_fb:
        mock_fb.return_value = {"uid": "uid_seller_api", "email": seller.email, "name": seller.full_name}
        resp = await test_client.post(
            "/api/v1/auctions",
            headers={"Authorization": "Bearer fake-token"},
            json={
                "product_id": product.product_id,
                "bid_step": 50000,
                "ends_at": (now + timedelta(hours=2)).isoformat(),
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        auction_id = data["auction_id"]
        assert Decimal(str(data["starting_price"])) == Decimal("3500000")
        assert Decimal(str(data["current_price"])) == Decimal("3500000")
        assert Decimal(str(data["minimum_next_bid"])) == Decimal("3500000")
        assert data["bid_count"] == 0
        assert data["has_winner"] is False

    # 2. Public gets auction by product via GET /api/v1/auctions/by-product/{product_id}
    resp = await test_client.get(f"/api/v1/auctions/by-product/{product.product_id}")
    assert resp.status_code == 200
    by_prod_data = resp.json()
    assert by_prod_data["auction_id"] == auction_id

    # 3. Buyer places a bid via POST /api/v1/auctions/{auction_id}/bids
    with patch("app.modules.auth.dependencies.verify_firebase_token") as mock_fb:
        mock_fb.return_value = {"uid": "uid_buyer_api", "email": buyer.email, "name": buyer.full_name}
        resp = await test_client.post(
            f"/api/v1/auctions/{auction_id}/bids",
            headers={"Authorization": "Bearer fake-token"},
            json={"amount": 3500000},
        )
        assert resp.status_code == 201
        bid_data = resp.json()
        assert Decimal(str(bid_data["amount"])) == Decimal("3500000")
        assert bid_data["bidder_display"] == "Trần T. M."
        assert "bidder_id" not in bid_data

    # 4. Public gets bid history via GET /api/v1/auctions/{auction_id}/bids
    resp = await test_client.get(f"/api/v1/auctions/{auction_id}/bids")
    assert resp.status_code == 200
    bids_data = resp.json()
    assert len(bids_data["items"]) == 1
    assert Decimal(str(bids_data["items"][0]["amount"])) == Decimal("3500000")
    assert "bidder_id" not in bids_data["items"][0]

    # 5. Seller cancellation fails because bid exists
    with patch("app.modules.auth.dependencies.verify_firebase_token") as mock_fb:
        mock_fb.return_value = {"uid": "uid_seller_api", "email": seller.email, "name": seller.full_name}
        resp = await test_client.post(
            f"/api/v1/auctions/{auction_id}/cancel",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_my_won_auctions_endpoint_and_privacy(
    test_client: AsyncClient,
    db_session: AsyncSession,
    seller: User,
    buyer: User,
    product: Product,
):
    from app.modules.auctions.models import Auction, AuctionBid, AuctionStatus
    from app.modules.orders.models import Order, OrderStatus, FulfillmentMethod, PaymentMethod, PaymentStatus
    from app.modules.products.models import ProductImage

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Add product image
    img = ProductImage(
        product_id=product.product_id,
        image_url="https://res.cloudinary.com/ptit/image/upload/sample.jpg",
        sort_order=0,
        is_thumbnail=True,
    )
    db_session.add(img)

    # 1. Auction 1: ENDED, won by buyer, deadline in future, no Order
    auc1 = Auction(
        product_id=product.product_id,
        starting_price=Decimal("1000000"),
        bid_step=Decimal("50000"),
        starts_at=now - timedelta(hours=3),
        ends_at=now - timedelta(hours=1),
        status=AuctionStatus.ENDED.value,
        winner_id=buyer.user_id,
        final_price=Decimal("1200000"),
        winner_checkout_deadline=now + timedelta(hours=20),
    )
    db_session.add(auc1)
    await db_session.flush()

    # 2. Winner queries GET /api/v1/auctions/me/won
    with patch("app.modules.auth.dependencies.verify_firebase_token") as mock_fb:
        mock_fb.return_value = {"uid": "uid_buyer_api", "email": buyer.email, "name": buyer.full_name}
        resp = await test_client.get(
            "/api/v1/auctions/me/won",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["auction_id"] == auc1.auction_id
        assert items[0]["product_id"] == product.product_id
        assert items[0]["product_title"] == product.title
        assert items[0]["product_image_url"] == "https://res.cloudinary.com/ptit/image/upload/sample.jpg"
        assert Decimal(str(items[0]["final_price"])) == Decimal("1200000")
        assert "winner_id" not in items[0]
        assert "seller_id" not in items[0]

    # 3. Seller queries GET /api/v1/auctions/me/won -> gets empty list (not won by seller)
    with patch("app.modules.auth.dependencies.verify_firebase_token") as mock_fb:
        mock_fb.return_value = {"uid": "uid_seller_api", "email": seller.email, "name": seller.full_name}
        resp = await test_client.get(
            "/api/v1/auctions/me/won",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    # 4. Unauthenticated user gets 401
    resp_unauth = await test_client.get("/api/v1/auctions/me/won")
    assert resp_unauth.status_code == 401

    # 5. When Order is created for auc1, it disappears from /me/won
    order = Order(
        order_code="ORD_WON_TEST",
        auction_id=auc1.auction_id,
        buyer_id=buyer.user_id,
        seller_id=seller.user_id,
        status=OrderStatus.PENDING.value,
        total_amount=Decimal("1200000"),
        fulfillment_method=FulfillmentMethod.MEETUP.value,
        payment_method=PaymentMethod.CASH_ON_MEETUP.value,
        payment_status=PaymentStatus.UNPAID.value,
        contact_name="Buyer Test",
        contact_phone="0912345678",
    )
    db_session.add(order)
    await db_session.flush()

    with patch("app.modules.auth.dependencies.verify_firebase_token") as mock_fb:
        mock_fb.return_value = {"uid": "uid_buyer_api", "email": buyer.email, "name": buyer.full_name}
        resp = await test_client.get(
            "/api/v1/auctions/me/won",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert resp.status_code == 200
        assert resp.json() == []
