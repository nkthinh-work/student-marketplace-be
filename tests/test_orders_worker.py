from uuid import uuid4
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.categories.models import Category
from app.modules.orders.models import FulfillmentMethod, Order, OrderItem, OrderStatus, PaymentMethod, PaymentStatus
from app.modules.orders.service import OrderService
from app.modules.products.models import ListingType, Product, ProductStatus
from app.modules.users.models import User, UserAuthIdentity, UserRole, UserStatus
from app.workers.order_auto_cancel import run_auto_cancel_sweep


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> Category:
    cat = Category(name="Đồ Gia Dụng", slug=f"do-gia-dung-{uuid4().hex[:6]}", is_deleted=False)
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def seller(db_session: AsyncSession) -> User:
    user = User(
        email="seller_worker@ptit.edu.vn",
        full_name="Seller Worker",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_seller_worker",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def buyer(db_session: AsyncSession) -> User:
    user = User(
        email="buyer_worker@ptit.edu.vn",
        full_name="Buyer Worker",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_buyer_worker",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def sample_product(
    db_session: AsyncSession, seller: User, sample_category: Category
) -> Product:
    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Quạt điện mini",
        description="Quạt để bàn",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal(80000),
        stock=5,
        reserved_stock=2,
        status=ProductStatus.AVAILABLE.value,
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


# 1. Auto-cancel expired pending order releases reserved_stock
@pytest.mark.asyncio
async def test_auto_cancel_expired_order_success(
    db_session: AsyncSession,
    buyer: User,
    seller: User,
    sample_product: Product,
):
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    expired_time = now_utc - timedelta(hours=1)

    order = Order(
        order_code="ORD-EXPIRED-001",
        buyer_id=buyer.user_id,
        seller_id=seller.user_id,
        status=OrderStatus.PENDING.value,
        payment_method=PaymentMethod.CASH_ON_MEETUP.value,
        payment_status=PaymentStatus.UNPAID,
        fulfillment_method=FulfillmentMethod.MEETUP.value,
        contact_name="Buyer",
        contact_phone="0987654321",
        total_amount=Decimal(160000),
        auto_cancel_at=expired_time,
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.order_id,
        product_id=sample_product.product_id,
        product_title=sample_product.title,
        quantity=2,
        price_at_purchase=Decimal(80000),
    )
    db_session.add(item)
    await db_session.flush()

    service = OrderService(db_session)
    cancelled = await service.auto_cancel_single_order(order.order_id)
    assert cancelled is True

    await db_session.refresh(order)
    assert order.status == OrderStatus.CANCELLED.value
    assert order.cancelled_by == "SYSTEM"
    assert "Hết hạn" in order.cancel_reason

    await db_session.refresh(sample_product)
    assert sample_product.reserved_stock == 0


# 2. Future auto_cancel_at is NOT cancelled
@pytest.mark.asyncio
async def test_unexpired_order_not_cancelled(
    db_session: AsyncSession,
    buyer: User,
    seller: User,
    sample_product: Product,
):
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    future_time = now_utc + timedelta(hours=24)

    order = Order(
        order_code="ORD-ACTIVE-002",
        buyer_id=buyer.user_id,
        seller_id=seller.user_id,
        status=OrderStatus.PENDING.value,
        payment_method=PaymentMethod.CASH_ON_MEETUP.value,
        payment_status=PaymentStatus.UNPAID,
        fulfillment_method=FulfillmentMethod.MEETUP.value,
        contact_name="Buyer",
        contact_phone="0987654321",
        total_amount=Decimal(160000),
        auto_cancel_at=future_time,
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.order_id,
        product_id=sample_product.product_id,
        product_title=sample_product.title,
        quantity=2,
        price_at_purchase=Decimal(80000),
    )
    db_session.add(item)
    await db_session.flush()

    service = OrderService(db_session)
    cancelled = await service.auto_cancel_single_order(order.order_id)
    assert cancelled is False

    await db_session.refresh(order)
    assert order.status == OrderStatus.PENDING.value
    await db_session.refresh(sample_product)
    assert sample_product.reserved_stock == 2
