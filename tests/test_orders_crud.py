from uuid import uuid4
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.categories.models import Category
from app.modules.orders.models import (
    FulfillmentMethod,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from app.modules.orders.repository import OrderRepository
from app.modules.products.models import ListingType, Product, ProductStatus, ProductApprovalStatus
from app.modules.users.models import User, UserAuthIdentity, UserRole, UserStatus


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> Category:
    cat = Category(name="Sách Giáo Trình", slug=f"sach-giao-trinh-{uuid4().hex[:6]}", is_deleted=False)
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def seller(db_session: AsyncSession) -> User:
    user = User(
        email="seller@ptit.edu.vn",
        full_name="Seller User",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_seller",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def buyer(db_session: AsyncSession) -> User:
    user = User(
        email="buyer@ptit.edu.vn",
        full_name="Buyer User",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_buyer",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def stranger(db_session: AsyncSession) -> User:
    user = User(
        email="stranger@ptit.edu.vn",
        full_name="Stranger User",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_stranger",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def fixed_product(
    db_session: AsyncSession, seller: User, sample_category: Category
) -> Product:
    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Giáo trình Cấu trúc dữ liệu",
        description="Sách học thuật toán PTIT",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal(60000),
        stock=5,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status=ProductApprovalStatus.APPROVED.value,
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


@pytest_asyncio.fixture
async def free_product(
    db_session: AsyncSession, seller: User, sample_category: Category
) -> Product:
    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Tài liệu ôn thi miễn phí",
        description="Tài liệu tặng kèm",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal(0),
        stock=3,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status=ProductApprovalStatus.APPROVED.value,
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


@pytest_asyncio.fixture
async def auction_product(
    db_session: AsyncSession, seller: User, sample_category: Category
) -> Product:
    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Bàn phím cơ đấu giá",
        description="Đấu giá bàn phím",
        listing_type=ListingType.AUCTION.value,
        price=Decimal(200000),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status=ProductApprovalStatus.APPROVED.value,
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


# 1. Create order valid fixed price -> 201 Created, snapshot saved, reserved_stock incremented
@pytest.mark.asyncio
async def test_create_order_valid_fixed_price(
    test_client: AsyncClient, buyer: User, fixed_product: Product, db_session: AsyncSession
):
    with auth_patch(buyer):
        res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": fixed_product.product_id,
                "quantity": 2,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường PTIT Hà Đông",
                "contact_name": "Nguyen Van Buyer",
                "contact_phone": "0987654321",
                "buyer_note": "Gặp vào giờ trưa",
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert data["status"] == "PENDING"
        assert data["payment_status"] == "UNPAID"
        assert Decimal(str(data["total_amount"])) == Decimal(120000)
        assert data["order_code"].startswith("ORD-")
        assert len(data["items"]) == 1
        assert data["items"][0]["quantity"] == 2
        assert data["items"][0]["product_title"] == "Giáo trình Cấu trúc dữ liệu"

        # Verify DB product reserved_stock was incremented
        await db_session.refresh(fixed_product)
        assert fixed_product.reserved_stock == 2
        assert fixed_product.stock == 5


# 2. Create order quantity exceeds available -> 400 Bad Request
@pytest.mark.asyncio
async def test_create_order_quantity_exceeds_available(
    test_client: AsyncClient, buyer: User, fixed_product: Product
):
    with auth_patch(buyer):
        res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": fixed_product.product_id,
                "quantity": 10,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "PTIT",
                "contact_name": "Nguyen Van Buyer",
                "contact_phone": "0987654321",
            },
        )
        assert res.status_code == 400
        assert "tồn kho khả dụng không đủ" in res.json()["detail"]


# 3. Create order buy own product -> 400 Bad Request
@pytest.mark.asyncio
async def test_create_order_buy_own_product(
    test_client: AsyncClient, seller: User, fixed_product: Product
):
    with auth_patch(seller):
        res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": fixed_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "PTIT",
                "contact_name": "Seller Buyer",
                "contact_phone": "0987654321",
            },
        )
        assert res.status_code == 400
        assert "Không thể mua sản phẩm của chính mình" in res.json()["detail"]


# 4. Create order auction direct buy -> 400 Bad Request
@pytest.mark.asyncio
async def test_create_order_auction_direct_buy_rejected(
    test_client: AsyncClient, buyer: User, auction_product: Product
):
    with auth_patch(buyer):
        res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": auction_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "PTIT",
                "contact_name": "Nguyen Van Buyer",
                "contact_phone": "0987654321",
            },
        )
        assert res.status_code == 400
        assert "đấu giá" in res.json()["detail"]


# 5. Create order cash on meetup + shipping -> 201 Created (Cash supported with shipping)
@pytest.mark.asyncio
async def test_create_order_cash_on_meetup_shipping_succeeds(
    test_client: AsyncClient, buyer: User, fixed_product: Product
):
    with auth_patch(buyer):
        res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": fixed_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "SHIPPING",
                "shipping_address": "So 1 Trieu Khuc, Ha Noi",
                "contact_name": "Nguyen Van Buyer",
                "contact_phone": "0987654321",
            },
        )
        assert res.status_code == 201
        assert res.json()["fulfillment_method"] == "SHIPPING"
        assert res.json()["payment_method"] == "CASH_ON_MEETUP"


# 6. Price zero order auto PAID with paid_confirmed_at
@pytest.mark.asyncio
async def test_create_order_price_zero_auto_paid(
    test_client: AsyncClient, buyer: User, free_product: Product
):
    with auth_patch(buyer):
        res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": free_product.product_id,
                "quantity": 1,
                "payment_method": "OTHER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Sanh A2 PTIT",
                "contact_name": "Free Hunter",
                "contact_phone": "0987654321",
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert Decimal(str(data["total_amount"])) == Decimal(0)
        assert data["payment_status"] == "PAID"
        assert data["paid_confirmed_at"] is not None


# 7. Free PENDING order can cancel
@pytest.mark.asyncio
async def test_free_pending_order_can_cancel(
    test_client: AsyncClient, buyer: User, free_product: Product, db_session: AsyncSession
):
    with auth_patch(buyer):
        create_res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": free_product.product_id,
                "quantity": 1,
                "payment_method": "OTHER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "PTIT",
                "contact_name": "Free Hunter",
                "contact_phone": "0987654321",
            },
        )
        order_id = create_res.json()["order_id"]

        cancel_res = await test_client.post(
            f"/api/v1/orders/{order_id}/cancel",
            headers={"Authorization": "Bearer token"},
            json={"cancel_reason": "Không cần nữa"},
        )
        assert cancel_res.status_code == 200
        assert cancel_res.json()["status"] == "CANCELLED"
        assert cancel_res.json()["cancelled_by"] == "BUYER"

        await db_session.refresh(free_product)
        assert free_product.reserved_stock == 0


# 8. Free CONFIRMED order can cancel
@pytest.mark.asyncio
async def test_free_confirmed_order_can_cancel(
    test_client: AsyncClient, buyer: User, seller: User, free_product: Product, db_session: AsyncSession
):
    with auth_patch(buyer):
        create_res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": free_product.product_id,
                "quantity": 1,
                "payment_method": "OTHER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "PTIT",
                "contact_name": "Free Hunter",
                "contact_phone": "0987654321",
            },
        )
        order_id = create_res.json()["order_id"]

    # Seller confirms free order
    with auth_patch(seller):
        confirm_res = await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            headers={"Authorization": "Bearer token"},
            json={},
        )
        assert confirm_res.status_code == 200
        assert confirm_res.json()["status"] == "CONFIRMED"

    # Buyer cancels free confirmed order -> Allowed
    with auth_patch(buyer):
        cancel_res = await test_client.post(
            f"/api/v1/orders/{order_id}/cancel",
            headers={"Authorization": "Bearer token"},
            json={"cancel_reason": "Bận không đến lấy được"},
        )
        assert cancel_res.status_code == 200
        assert cancel_res.json()["status"] == "CANCELLED"

        await db_session.refresh(free_product)
        assert free_product.reserved_stock == 0


# 9. Free DELIVERING order cannot cancel
@pytest.mark.asyncio
async def test_free_delivering_order_cannot_cancel(
    test_client: AsyncClient, buyer: User, seller: User, free_product: Product
):
    with auth_patch(buyer):
        create_res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": free_product.product_id,
                "quantity": 1,
                "payment_method": "OTHER",
                "fulfillment_method": "SHIPPING",
                "shipping_address": "Ky tuc xa PTIT",
                "contact_name": "Free Hunter",
                "contact_phone": "0987654321",
            },
        )
        order_id = create_res.json()["order_id"]

    # Seller confirms and marks delivering
    with auth_patch(seller):
        await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            headers={"Authorization": "Bearer token"},
            json={},
        )
        deliver_res = await test_client.post(
            f"/api/v1/orders/{order_id}/deliver",
            headers={"Authorization": "Bearer token"},
        )
        assert deliver_res.status_code == 200
        assert deliver_res.json()["status"] == "DELIVERING"

    # Try cancel while delivering -> 400
    with auth_patch(buyer):
        cancel_res = await test_client.post(
            f"/api/v1/orders/{order_id}/cancel",
            headers={"Authorization": "Bearer token"},
            json={"cancel_reason": "Muon huy"},
        )
        assert cancel_res.status_code == 400
        assert "đang trong quá trình giao hàng" in cancel_res.json()["detail"]


# 10. List buying and selling orders with cursor pagination
@pytest.mark.asyncio
async def test_list_buying_and_selling_orders(
    test_client: AsyncClient, buyer: User, seller: User, fixed_product: Product
):
    with auth_patch(buyer):
        # Create 2 orders
        for _ in range(2):
            await test_client.post(
                "/api/v1/orders",
                headers={"Authorization": "Bearer token"},
                json={
                    "product_id": fixed_product.product_id,
                    "quantity": 1,
                    "payment_method": "CASH_ON_MEETUP",
                    "fulfillment_method": "MEETUP",
                    "meetup_place": "PTIT",
                    "contact_name": "Nguyen Van Buyer",
                    "contact_phone": "0987654321",
                },
            )

        # Buyer list
        res_buy = await test_client.get(
            "/api/v1/orders/me/buying?limit=1",
            headers={"Authorization": "Bearer token"},
        )
        assert res_buy.status_code == 200
        data_buy = res_buy.json()
        assert len(data_buy["items"]) == 1
        assert data_buy["has_more"] is True
        assert data_buy["next_cursor"] is not None

    # Seller list
    with auth_patch(seller):
        res_sell = await test_client.get(
            "/api/v1/orders/me/selling?limit=10",
            headers={"Authorization": "Bearer token"},
        )
        assert res_sell.status_code == 200
        data_sell = res_sell.json()
        assert len(data_sell["items"]) == 2


# 11. Unrelated user gets 404 on order detail
@pytest.mark.asyncio
async def test_unrelated_user_gets_404(
    test_client: AsyncClient, buyer: User, stranger: User, fixed_product: Product
):
    with auth_patch(buyer):
        create_res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": fixed_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "PTIT",
                "contact_name": "Nguyen Van Buyer",
                "contact_phone": "0987654321",
            },
        )
        order_id = create_res.json()["order_id"]

    with auth_patch(stranger):
        res = await test_client.get(
            f"/api/v1/orders/{order_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 404


# 12. Order code collision retry with SAVEPOINT
@pytest.mark.asyncio
async def test_order_code_collision_retry_with_savepoint(
    db_session: AsyncSession, buyer: User, seller: User, fixed_product: Product
):
    repo = OrderRepository(db_session)
    order1 = Order(
        buyer_id=buyer.user_id,
        seller_id=seller.user_id,
        status="PENDING",
        payment_method="CASH_ON_MEETUP",
        payment_status=PaymentStatus.UNPAID,
        fulfillment_method="MEETUP",
        contact_name="Buyer",
        contact_phone="0123",
        total_amount=Decimal(60000),
    )
    item1 = OrderItem(
        product_id=fixed_product.product_id,
        product_title=fixed_product.title,
        quantity=1,
        price_at_purchase=Decimal(60000),
    )
    created1 = await repo.create_order(order1, [item1])
    fixed_code = created1.order_code

    # Simulate collision on next create
    order2 = Order(
        buyer_id=buyer.user_id,
        seller_id=seller.user_id,
        status="PENDING",
        payment_method="CASH_ON_MEETUP",
        payment_status=PaymentStatus.UNPAID,
        fulfillment_method="MEETUP",
        contact_name="Buyer 2",
        contact_phone="0123",
        total_amount=Decimal(60000),
    )
    item2 = OrderItem(
        product_id=fixed_product.product_id,
        product_title=fixed_product.title,
        quantity=1,
        price_at_purchase=Decimal(60000),
    )

    codes_yielded = iter([fixed_code, "ORD-999999-UNIQUE1"])
    with patch.object(OrderRepository, "generate_order_code", side_effect=lambda: next(codes_yielded)):
        created2 = await repo.create_order(order2, [item2])
        assert created2.order_code == "ORD-999999-UNIQUE1"
