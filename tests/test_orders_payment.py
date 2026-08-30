from uuid import uuid4
from decimal import Decimal
from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.categories.models import Category
from app.modules.favorites.models import Favorite
from app.modules.orders.models import FulfillmentMethod, Order, OrderStatus, PaymentMethod, PaymentStatus
from app.modules.products.models import ListingType, Product, ProductStatus
from app.modules.users.models import User, UserAuthIdentity, UserRole, UserStatus


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> Category:
    cat = Category(name="Đồ Điện Tử", slug=f"do-dien-tu-{uuid4().hex[:6]}", is_deleted=False)
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def seller(db_session: AsyncSession) -> User:
    user = User(
        email="seller_pay@ptit.edu.vn",
        full_name="Seller Pay",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
        bank_bin="970422",
        bank_account_number="0123456789",
        bank_account_name="SELLER PAY",
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_seller_pay",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def buyer(db_session: AsyncSession) -> User:
    user = User(
        email="buyer_pay@ptit.edu.vn",
        full_name="Buyer Pay",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_buyer_pay",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def single_stock_product(
    db_session: AsyncSession, seller: User, sample_category: Category
) -> Product:
    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Chuột không dây Logitech",
        description="Mới nguyên hộp",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal(150000),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
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


# 1. POST /orders/{id}/receipt rejected while PENDING
@pytest.mark.asyncio
async def test_upload_receipt_while_order_pending_rejected(
    test_client: AsyncClient, buyer: User, single_stock_product: Product
):
    with auth_patch(buyer):
        create_res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": single_stock_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "PTIT",
                "contact_name": "Buyer",
                "contact_phone": "0987654321",
            },
        )
        order_id = create_res.json()["order_id"]

        with patch(
            "app.modules.orders.service.upload_order_receipt",
            return_value={"secure_url": "https://cloudinary.com/receipt.jpg"},
        ):
            res = await test_client.post(
                f"/api/v1/orders/{order_id}/receipt",
                headers={"Authorization": "Bearer token"},
                files={"file": ("receipt.jpg", b"fake_image_bytes", "image/jpeg")},
            )
            assert res.status_code == 400
            assert "phải được người bán xác nhận trước" in res.json()["detail"]


# 2. Seller confirms BANK_TRANSFER requires payment_note, then buyer uploads receipt -> VERIFYING
@pytest.mark.asyncio
async def test_bank_transfer_flow_and_payment_note(
    test_client: AsyncClient, buyer: User, seller: User, single_stock_product: Product
):
    # Buyer creates BANK_TRANSFER order
    with auth_patch(buyer):
        create_res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": single_stock_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "PTIT",
                "contact_name": "Buyer",
                "contact_phone": "0987654321",
            },
        )
        order_id = create_res.json()["order_id"]

    # Seller confirms with optional payment_note -> 200
    with auth_patch(seller):
        success_confirm = await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            headers={"Authorization": "Bearer token"},
            json={"payment_note": "MB Bank STK: 123456789 CTK: NGUYEN VAN A"},
        )
        assert success_confirm.status_code == 200
        assert success_confirm.json()["status"] == "CONFIRMED"
        assert success_confirm.json()["payment_note"] == "MB Bank STK: 123456789 CTK: NGUYEN VAN A"
        assert success_confirm.json()["payment_bank"] is not None
        assert success_confirm.json()["payment_bank"]["bank_bin"] == "970422"

    # Buyer sees payment_note, payment_bank, and uploads receipt -> VERIFYING
    with auth_patch(buyer):
        detail_res = await test_client.get(
            f"/api/v1/orders/{order_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert detail_res.json()["payment_note"] == "MB Bank STK: 123456789 CTK: NGUYEN VAN A"
        assert detail_res.json()["payment_bank"] is not None

        with patch(
            "app.modules.orders.service.upload_order_receipt",
            return_value={"secure_url": "https://cloudinary.com/receipt1.jpg"},
        ):
            receipt_res = await test_client.post(
                f"/api/v1/orders/{order_id}/receipt",
                headers={"Authorization": "Bearer token"},
                files={"file": ("receipt.png", b"fake_png_bytes", "image/png")},
            )
            assert receipt_res.status_code == 200
            assert receipt_res.json()["payment_status"] == "VERIFYING"
            assert receipt_res.json()["payment_receipt_url"] == "https://cloudinary.com/receipt1.jpg"

    # Seller confirms payment -> PAID
    with auth_patch(seller):
        pay_res = await test_client.post(
            f"/api/v1/orders/{order_id}/confirm-payment",
            headers={"Authorization": "Bearer token"},
        )
        assert pay_res.status_code == 200
        assert pay_res.json()["payment_status"] == "PAID"
        assert pay_res.json()["paid_confirmed_at"] is not None

    # Buyer attempts receipt replacement AFTER PAID -> 400 Rejected
    with auth_patch(buyer):
        with patch(
            "app.modules.orders.service.upload_order_receipt",
            return_value={"secure_url": "https://cloudinary.com/receipt2.jpg"},
        ):
            replace_res = await test_client.post(
                f"/api/v1/orders/{order_id}/receipt",
                headers={"Authorization": "Bearer token"},
                files={"file": ("receipt2.png", b"fake_png_bytes2", "image/png")},
            )
            assert replace_res.status_code == 400
            assert "Không thể thay đổi biên nhận" in replace_res.json()["detail"]


# 3. BANK_TRANSFER cannot confirm payment while UNPAID
@pytest.mark.asyncio
async def test_bank_transfer_cannot_confirm_payment_while_unpaid(
    test_client: AsyncClient, buyer: User, seller: User, single_stock_product: Product
):
    with auth_patch(buyer):
        create_res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": single_stock_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "PTIT",
                "contact_name": "Buyer",
                "contact_phone": "0987654321",
            },
        )
        order_id = create_res.json()["order_id"]

    with auth_patch(seller):
        await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            headers={"Authorization": "Bearer token"},
            json={"payment_note": "MB Bank 123456"},
        )

        # Seller attempts to confirm payment before receipt uploaded -> 400
        pay_res = await test_client.post(
            f"/api/v1/orders/{order_id}/confirm-payment",
            headers={"Authorization": "Bearer token"},
        )
        assert pay_res.status_code == 400
        assert "chưa tải lên biên nhận" in pay_res.json()["detail"]


# 4. CASH_ON_MEETUP cannot confirm-payment while PENDING, succeeds in CONFIRMED
@pytest.mark.asyncio
async def test_cash_confirm_payment_rules(
    test_client: AsyncClient, buyer: User, seller: User, single_stock_product: Product
):
    with auth_patch(buyer):
        create_res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": single_stock_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "PTIT",
                "contact_name": "Buyer",
                "contact_phone": "0987654321",
            },
        )
        order_id = create_res.json()["order_id"]

    with auth_patch(seller):
        # Confirm payment on PENDING order -> 400
        pending_pay = await test_client.post(
            f"/api/v1/orders/{order_id}/confirm-payment",
            headers={"Authorization": "Bearer token"},
        )
        assert pending_pay.status_code == 400

        # Confirm order -> CONFIRMED
        await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            headers={"Authorization": "Bearer token"},
            json={},
        )

        # Confirm payment on CONFIRMED order -> 200 PAID
        confirmed_pay = await test_client.post(
            f"/api/v1/orders/{order_id}/confirm-payment",
            headers={"Authorization": "Bearer token"},
        )
        assert confirmed_pay.status_code == 200
        assert confirmed_pay.json()["payment_status"] == "PAID"


# 5. MEETUP cannot transition to DELIVERING (400)
@pytest.mark.asyncio
async def test_meetup_cannot_transition_to_delivering(
    test_client: AsyncClient, buyer: User, seller: User, single_stock_product: Product
):
    with auth_patch(buyer):
        create_res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": single_stock_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "PTIT",
                "contact_name": "Buyer",
                "contact_phone": "0987654321",
            },
        )
        order_id = create_res.json()["order_id"]

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
        assert deliver_res.status_code == 400
        assert "không sử dụng trạng thái đang giao hàng" in deliver_res.json()["detail"]


# 6. SHIPPING cannot transition to DELIVERING while UNPAID or VERIFYING
@pytest.mark.asyncio
async def test_shipping_delivering_payment_guard(
    test_client: AsyncClient, buyer: User, seller: User, single_stock_product: Product
):
    with auth_patch(buyer):
        create_res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": single_stock_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "SHIPPING",
                "shipping_address": "Ha Dong, Ha Noi",
                "contact_name": "Buyer",
                "contact_phone": "0987654321",
            },
        )
        order_id = create_res.json()["order_id"]

    with auth_patch(seller):
        await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            headers={"Authorization": "Bearer token"},
            json={"payment_note": "MB Bank 123"},
        )

        # Deliver while UNPAID -> 400
        deliver_unpaid = await test_client.post(
            f"/api/v1/orders/{order_id}/deliver",
            headers={"Authorization": "Bearer token"},
        )
        assert deliver_unpaid.status_code == 400
        assert "phải thanh toán trước khi giao" in deliver_unpaid.json()["detail"]

    # Buyer uploads receipt -> VERIFYING
    with auth_patch(buyer):
        with patch(
            "app.modules.orders.service.upload_order_receipt",
            return_value={"secure_url": "https://cloudinary.com/receipt.jpg"},
        ):
            await test_client.post(
                f"/api/v1/orders/{order_id}/receipt",
                headers={"Authorization": "Bearer token"},
                files={"file": ("receipt.jpg", b"fake", "image/jpeg")},
            )

    # Deliver while VERIFYING -> 400
    with auth_patch(seller):
        deliver_verifying = await test_client.post(
            f"/api/v1/orders/{order_id}/deliver",
            headers={"Authorization": "Bearer token"},
        )
        assert deliver_verifying.status_code == 400
        assert "phải thanh toán trước khi giao" in deliver_verifying.json()["detail"]

        # Seller confirms payment -> PAID
        await test_client.post(
            f"/api/v1/orders/{order_id}/confirm-payment",
            headers={"Authorization": "Bearer token"},
        )

        # Deliver while PAID -> 200 DELIVERING
        deliver_paid = await test_client.post(
            f"/api/v1/orders/{order_id}/deliver",
            headers={"Authorization": "Bearer token"},
        )
        assert deliver_paid.status_code == 200
        assert deliver_paid.json()["status"] == "DELIVERING"


# 7. Complete order reduces stock and removes favorites if stock=0
@pytest.mark.asyncio
async def test_complete_order_finalizes_stock_and_cleans_favorites(
    test_client: AsyncClient,
    buyer: User,
    seller: User,
    single_stock_product: Product,
    db_session: AsyncSession,
):
    # Buyer adds product to favorites first
    fav = Favorite(user_id=buyer.user_id, product_id=single_stock_product.product_id)
    db_session.add(fav)
    await db_session.flush()

    with auth_patch(buyer):
        create_res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": single_stock_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "PTIT",
                "contact_name": "Buyer",
                "contact_phone": "0987654321",
            },
        )
        order_id = create_res.json()["order_id"]

    with auth_patch(seller):
        await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            headers={"Authorization": "Bearer token"},
            json={},
        )
        # Try complete before payment -> 400
        fail_complete = await test_client.post(
            f"/api/v1/orders/{order_id}/complete",
            headers={"Authorization": "Bearer token"},
        )
        assert fail_complete.status_code == 400
        assert "hoàn tất thanh toán" in fail_complete.json()["detail"]

        # Confirm cash payment
        await test_client.post(
            f"/api/v1/orders/{order_id}/confirm-payment",
            headers={"Authorization": "Bearer token"},
        )

        # Complete order
        complete_res = await test_client.post(
            f"/api/v1/orders/{order_id}/complete",
            headers={"Authorization": "Bearer token"},
        )
        assert complete_res.status_code == 200
        assert complete_res.json()["status"] == "COMPLETED"

    # Verify product stock = 0, status = SOLD_OUT, and favorite is deleted
    await db_session.refresh(single_stock_product)
    assert single_stock_product.stock == 0
    assert single_stock_product.reserved_stock == 0
    assert single_stock_product.status == ProductStatus.SOLD_OUT.value

    fav_res = await db_session.execute(
        select(Favorite).where(Favorite.product_id == single_stock_product.product_id)
    )
    assert fav_res.scalar_one_or_none() is None
