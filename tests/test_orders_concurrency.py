from uuid import uuid4
import asyncio
from decimal import Decimal
from unittest.mock import patch
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.main import app
from app.modules.categories.models import Category
from app.modules.orders.models import FulfillmentMethod, Order, OrderStatus, PaymentMethod, PaymentStatus
from app.modules.orders.schemas import CancelOrderRequest
from app.modules.orders.service import OrderService, StockInvariantViolationError
from app.modules.products.models import ListingType, Product, ProductStatus
from app.modules.users.models import User, UserAuthIdentity, UserRole, UserStatus


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> Category:
    cat = Category(name="Điện Thoại", slug=f"dien-thoai-{uuid4().hex[:6]}", is_deleted=False)
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def seller(db_session: AsyncSession) -> User:
    user = User(
        email="seller_conc@ptit.edu.vn",
        full_name="Seller Concurrency",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_seller_conc",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def buyer1(db_session: AsyncSession) -> User:
    user = User(
        email="buyer1@ptit.edu.vn",
        full_name="Buyer 1",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_buyer1",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def buyer2(db_session: AsyncSession) -> User:
    user = User(
        email="buyer2@ptit.edu.vn",
        full_name="Buyer 2",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_buyer2",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def limited_product(
    db_session: AsyncSession, seller: User, sample_category: Category
) -> Product:
    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="iPhone 13 cũ",
        description="Bản 128GB",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal(10000000),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


def auth_patch(user: User):
    return patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": f"uid_{user.email.split('@')[0]}",
            "email": user.email,
            "name": user.full_name,
        },
    )


# 1. Concurrent order creation on limited stock (stock=1) -> exactly 1 succeeds, 1 gets 400
@pytest.mark.asyncio
async def test_concurrent_order_creation_no_overselling(
    test_client: AsyncClient,
    buyer1: User,
    buyer2: User,
    limited_product: Product,
    db_session: AsyncSession,
):
    async def place_order(buyer_user: User):
        with auth_patch(buyer_user):
            return await test_client.post(
                "/api/v1/orders",
                headers={"Authorization": f"Bearer token_{buyer_user.user_id}"},
                json={
                    "product_id": limited_product.product_id,
                    "quantity": 1,
                    "payment_method": "CASH_ON_MEETUP",
                    "fulfillment_method": "MEETUP",
                    "meetup_place": "PTIT",
                    "contact_name": buyer_user.full_name,
                    "contact_phone": "0987654321",
                },
            )

    # In single db_session transaction, execute sequentially / simulated race
    res1 = await place_order(buyer1)
    res2 = await place_order(buyer2)

    status_codes = [res1.status_code, res2.status_code]
    assert status_codes.count(201) == 1
    assert status_codes.count(400) == 1

    await db_session.refresh(limited_product)
    assert limited_product.reserved_stock == 1
    assert limited_product.stock == 1


# 2. Stock invariant violation raises error instead of clamping with max(0)
@pytest.mark.asyncio
async def test_stock_invariant_violation_raises_error_not_clamped(
    db_session: AsyncSession,
    buyer1: User,
    seller: User,
    limited_product: Product,
):
    service = OrderService(db_session)
    order = Order(
        buyer_id=buyer1.user_id,
        seller_id=seller.user_id,
        status=OrderStatus.PENDING.value,
        payment_method=PaymentMethod.CASH_ON_MEETUP.value,
        payment_status=PaymentStatus.UNPAID,
        fulfillment_method=FulfillmentMethod.MEETUP.value,
        contact_name="Buyer",
        contact_phone="0123",
        total_amount=Decimal(10000000),
    )
    # Intentionally corrupt reserved_stock to 0 in product while order has quantity 1
    limited_product.reserved_stock = 0
    await db_session.flush()

    from app.modules.orders.models import OrderItem
    item = OrderItem(
        product_id=limited_product.product_id,
        product_title=limited_product.title,
        quantity=1,
        price_at_purchase=Decimal(10000000),
    )
    created_order = await service.order_repo.create_order(order, [item])

    with pytest.raises(StockInvariantViolationError):
        await service.cancel_order(
            created_order.order_id,
            buyer1,
            CancelOrderRequest(cancel_reason="Hủy thử nghiệm"),
        )
