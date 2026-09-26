import asyncio
from decimal import Decimal
import io
from unittest.mock import patch
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.categories.models import Category
from app.modules.orders.models import FulfillmentMethod, Order, OrderStatus, PaymentMethod, PaymentStatus
from app.modules.products.models import ListingType, Product, ProductStatus
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
async def sample_cat(db_session: AsyncSession) -> Category:
    cat = Category(name="Giao dịch điều khoản", slug="giao-dich-dieu-khoan")
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def seller_with_bank(db_session: AsyncSession) -> User:
    user = User(
        email="seller_bank@ptit.edu.vn",
        full_name="Le Van Seller",
        phone="0911223344",
        status=UserStatus.ACTIVE,
        role=UserRole.STUDENT.value,
        bank_bin="970422",
        bank_account_number="0123456789",
        bank_account_name="LE VAN SELLER",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def seller_no_bank(db_session: AsyncSession) -> User:
    user = User(
        email="seller_nobank@ptit.edu.vn",
        full_name="Pham No Bank",
        phone="0922334455",
        status=UserStatus.ACTIVE,
        role=UserRole.STUDENT.value,
        bank_bin=None,
        bank_account_number=None,
        bank_account_name=None,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def buyer_user(db_session: AsyncSession) -> User:
    user = User(
        email="buyer_terms@ptit.edu.vn",
        full_name="Hoang Thi Buyer",
        phone="0933445566",
        status=UserStatus.ACTIVE,
        role=UserRole.STUDENT.value,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def unrelated_user(db_session: AsyncSession) -> User:
    user = User(
        email="unrelated@ptit.edu.vn",
        full_name="Unrelated User",
        phone="0944556677",
        status=UserStatus.ACTIVE,
        role=UserRole.STUDENT.value,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def paid_product(
    db_session: AsyncSession, seller_with_bank: User, sample_cat: Category
) -> Product:
    prod = Product(
        seller_id=seller_with_bank.user_id,
        category_id=sample_cat.category_id,
        title="Laptop ThinkPad T480s",
        description="Core i7 16GB RAM",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal("8500000"),
        stock=3,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


@pytest_asyncio.fixture
async def free_product(
    db_session: AsyncSession, seller_no_bank: User, sample_cat: Category
) -> Product:
    prod = Product(
        seller_id=seller_no_bank.user_id,
        category_id=sample_cat.category_id,
        title="Bộ đề ôn thi PTIT",
        description="Tài liệu tặng kèm",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal("0"),
        stock=5,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


# =====================================================================
# 1. BUYER CHECKOUT TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_paid_meetup_cash_succeeds(
    test_client: AsyncClient, buyer_user: User, paid_product: Product
):
    with auth_patch(buyer_user):
        res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường PTIT Hà Đông",
                "contact_name": "Buyer 1",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert res.status_code == 201
    data = res.json()
    assert data["fulfillment_method"] == "MEETUP"
    assert data["payment_method"] == "CASH_ON_MEETUP"
    assert data["status"] == "PENDING"
    assert data["payment_status"] == "UNPAID"


@pytest.mark.asyncio
async def test_paid_meetup_bank_transfer_succeeds(
    test_client: AsyncClient, buyer_user: User, paid_product: Product
):
    with auth_patch(buyer_user):
        res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Sảnh A2",
                "contact_name": "Buyer 1",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert res.status_code == 201
    data = res.json()
    assert data["fulfillment_method"] == "MEETUP"
    assert data["payment_method"] == "BANK_TRANSFER"


@pytest.mark.asyncio
async def test_paid_shipping_cash_succeeds(
    test_client: AsyncClient, buyer_user: User, paid_product: Product
):
    with auth_patch(buyer_user):
        res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "SHIPPING",
                "shipping_address": "KTX B2 Phòng 304, PTIT",
                "contact_name": "Buyer 1",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert res.status_code == 201
    data = res.json()
    assert data["fulfillment_method"] == "SHIPPING"
    assert data["payment_method"] == "CASH_ON_MEETUP"


@pytest.mark.asyncio
async def test_paid_shipping_bank_transfer_succeeds(
    test_client: AsyncClient, buyer_user: User, paid_product: Product
):
    with auth_patch(buyer_user):
        res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "SHIPPING",
                "shipping_address": "KTX B2 Phòng 304, PTIT",
                "contact_name": "Buyer 1",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert res.status_code == 201
    data = res.json()
    assert data["fulfillment_method"] == "SHIPPING"
    assert data["payment_method"] == "BANK_TRANSFER"


@pytest.mark.asyncio
async def test_paid_order_rejects_other_payment_method(
    test_client: AsyncClient, buyer_user: User, paid_product: Product
):
    with auth_patch(buyer_user):
        res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "OTHER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Sảnh A2",
                "contact_name": "Buyer 1",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_free_order_ignores_payment_method_semantics(
    test_client: AsyncClient, buyer_user: User, free_product: Product
):
    with auth_patch(buyer_user):
        res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": free_product.product_id,
                "quantity": 1,
                "fulfillment_method": "SHIPPING",
                "shipping_address": "Phòng 101 KTX",
                "contact_name": "Buyer Free",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert res.status_code == 201
    data = res.json()
    assert data["payment_method"] == "OTHER"
    assert data["payment_status"] == "PAID"
    assert Decimal(str(data["total_amount"])) == Decimal("0")


# =====================================================================
# 2. SELLER EDIT AUTH & EDITABLE STATES
# =====================================================================

@pytest.mark.asyncio
async def test_seller_can_edit_pending_order_terms(
    test_client: AsyncClient, buyer_user: User, seller_with_bank: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    order_id = create_res.json()["order_id"]

    # Seller edits terms
    with auth_patch(seller_with_bank):
        edit_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={
                "fulfillment_method": "SHIPPING",
                "shipping_address": "Nhà riêng số 123 đường ABC, Hà Đông",
                "payment_method": "BANK_TRANSFER",
                "payment_note": "Chuyển tiền xong shop ship ngay trong ngày",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert edit_res.status_code == 200
    data = edit_res.json()
    assert data["fulfillment_method"] == "SHIPPING"
    assert data["shipping_address"] == "Nhà riêng số 123 đường ABC, Hà Đông"
    assert data["meetup_place"] is None
    assert data["payment_method"] == "BANK_TRANSFER"
    assert data["payment_note"] == "Chuyển tiền xong shop ship ngay trong ngày"


@pytest.mark.asyncio
async def test_seller_can_edit_confirmed_unpaid_order_terms(
    test_client: AsyncClient, buyer_user: User, seller_with_bank: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    order_id = create_res.json()["order_id"]

    with auth_patch(seller_with_bank):
        confirm_res = await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            json={},
            headers={"Authorization": "Bearer mock"},
        )
        assert confirm_res.status_code == 200

        # Seller edits terms when CONFIRMED + UNPAID
        edit_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={
                "meetup_place": "Căn tin Tầng 1 Tòa A2",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert edit_res.status_code == 200
    assert edit_res.json()["meetup_place"] == "Căn tin Tầng 1 Tòa A2"


@pytest.mark.asyncio
async def test_buyer_cannot_call_seller_edit_terms(
    test_client: AsyncClient, buyer_user: User, seller_with_bank: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
        order_id = create_res.json()["order_id"]

        # Buyer attempts to call seller-only endpoint -> 404 (non-enumeration)
        edit_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={"meetup_place": "New Place"},
            headers={"Authorization": "Bearer mock"},
        )
    assert edit_res.status_code == 404


@pytest.mark.asyncio
async def test_unrelated_user_cannot_edit_terms(
    test_client: AsyncClient, buyer_user: User, unrelated_user: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    order_id = create_res.json()["order_id"]

    with auth_patch(unrelated_user):
        edit_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={"meetup_place": "Hacked Place"},
            headers={"Authorization": "Bearer mock"},
        )
    assert edit_res.status_code == 404


@pytest.mark.asyncio
async def test_delivering_order_cannot_edit_terms(
    test_client: AsyncClient, buyer_user: User, seller_with_bank: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "SHIPPING",
                "shipping_address": "KTX PTIT",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    order_id = create_res.json()["order_id"]

    with auth_patch(seller_with_bank):
        await test_client.post(f"/api/v1/orders/{order_id}/confirm", json={}, headers={"Authorization": "Bearer mock"})
        # Enters DELIVERING
        await test_client.post(f"/api/v1/orders/{order_id}/deliver", headers={"Authorization": "Bearer mock"})

        # Attempt to edit transaction terms while DELIVERING -> rejected
        edit_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={"shipping_address": "Changed Address"},
            headers={"Authorization": "Bearer mock"},
        )
    assert edit_res.status_code == 400


@pytest.mark.asyncio
async def test_completed_or_cancelled_order_cannot_edit_terms(
    test_client: AsyncClient, buyer_user: User, seller_with_bank: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    order_id = create_res.json()["order_id"]

    # Cancel order
    with auth_patch(buyer_user):
        await test_client.post(
            f"/api/v1/orders/{order_id}/cancel",
            json={"cancel_reason": "Cancel"},
            headers={"Authorization": "Bearer mock"},
        )

    # Attempt to edit -> rejected
    with auth_patch(seller_with_bank):
        edit_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={"meetup_place": "New Place"},
            headers={"Authorization": "Bearer mock"},
        )
    assert edit_res.status_code == 400


# =====================================================================
# 3. FULFILLMENT & LOCATION CLEANUP TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_meetup_to_shipping_clears_meetup_fields(
    test_client: AsyncClient, buyer_user: User, seller_with_bank: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Sảnh A1",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    order_id = create_res.json()["order_id"]

    with auth_patch(seller_with_bank):
        edit_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={
                "fulfillment_method": "SHIPPING",
                "shipping_address": "Số 45 Lê Duẩn, Hoàn Kiếm",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert edit_res.status_code == 200
    data = edit_res.json()
    assert data["fulfillment_method"] == "SHIPPING"
    assert data["shipping_address"] == "Số 45 Lê Duẩn, Hoàn Kiếm"
    assert data["meetup_place"] is None
    assert data["meetup_time"] is None


@pytest.mark.asyncio
async def test_shipping_to_meetup_clears_shipping_address(
    test_client: AsyncClient, buyer_user: User, seller_with_bank: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "SHIPPING",
                "shipping_address": "KTX PTIT",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    order_id = create_res.json()["order_id"]

    with auth_patch(seller_with_bank):
        edit_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cửa hàng tiện lợi 7-Eleven đối diện trường",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert edit_res.status_code == 200
    data = edit_res.json()
    assert data["fulfillment_method"] == "MEETUP"
    assert data["meetup_place"] == "Cửa hàng tiện lợi 7-Eleven đối diện trường"
    assert data["shipping_address"] is None


@pytest.mark.asyncio
async def test_switching_fulfillment_without_required_location_rejected(
    test_client: AsyncClient, buyer_user: User, seller_with_bank: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Sảnh A1",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    order_id = create_res.json()["order_id"]

    # Switch to SHIPPING without shipping_address -> 400
    with auth_patch(seller_with_bank):
        edit_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={
                "fulfillment_method": "SHIPPING",
                "shipping_address": "   ",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert edit_res.status_code in (400, 422)


# =====================================================================
# 4. PAYMENT & BANK SNAPSHOT TRANSITION TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_cash_to_bank_transfer_unpaid_snapshots_bank_on_confirmed(
    test_client: AsyncClient, buyer_user: User, seller_with_bank: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    order_id = create_res.json()["order_id"]

    # Seller confirms order as CASH
    with auth_patch(seller_with_bank):
        confirm_res = await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            json={},
            headers={"Authorization": "Bearer mock"},
        )
        assert confirm_res.status_code == 200
        assert confirm_res.json()["payment_bank"] is None

        # Seller switches CASH -> BANK_TRANSFER while CONFIRMED + UNPAID
        edit_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={"payment_method": "BANK_TRANSFER"},
            headers={"Authorization": "Bearer mock"},
        )
    assert edit_res.status_code == 200
    data = edit_res.json()
    assert data["payment_method"] == "BANK_TRANSFER"
    assert data["payment_bank"] is not None
    assert data["payment_bank"]["bank_bin"] == "970422"
    assert data["payment_bank"]["account_number"] == "0123456789"
    assert "970422" in data["payment_bank"]["qr_url"]

    # Buyer immediately sees VietQR
    with auth_patch(buyer_user):
        buyer_view = await test_client.get(
            f"/api/v1/orders/{order_id}",
            headers={"Authorization": "Bearer mock"},
        )
    assert buyer_view.json()["payment_bank"] is not None


@pytest.mark.asyncio
async def test_cash_to_bank_transfer_rejected_if_seller_has_no_bank(
    test_client: AsyncClient, buyer_user: User, seller_no_bank: User, sample_cat: Category, db_session: AsyncSession
):
    prod = Product(
        seller_id=seller_no_bank.user_id,
        category_id=sample_cat.category_id,
        title="Phone case",
        description="Case",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal("50000"),
        stock=1,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()

    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": prod.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    order_id = create_res.json()["order_id"]

    # Seller attempts to switch to BANK_TRANSFER without bank profile -> 400
    with auth_patch(seller_no_bank):
        edit_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={"payment_method": "BANK_TRANSFER"},
            headers={"Authorization": "Bearer mock"},
        )
    assert edit_res.status_code == 400
    assert "tài khoản nhận tiền" in edit_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_bank_transfer_to_cash_clears_bank_snapshot(
    test_client: AsyncClient, buyer_user: User, seller_with_bank: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    order_id = create_res.json()["order_id"]

    # Seller confirms
    with auth_patch(seller_with_bank):
        await test_client.post(f"/api/v1/orders/{order_id}/confirm", json={}, headers={"Authorization": "Bearer mock"})

        # Seller switches BANK_TRANSFER -> CASH_ON_MEETUP while UNPAID
        edit_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={"payment_method": "CASH_ON_MEETUP"},
            headers={"Authorization": "Bearer mock"},
        )
    assert edit_res.status_code == 200
    data = edit_res.json()
    assert data["payment_method"] == "CASH_ON_MEETUP"
    assert data["payment_bank"] is None

    # Buyer view: QR is gone
    with auth_patch(buyer_user):
        buyer_view = await test_client.get(
            f"/api/v1/orders/{order_id}",
            headers={"Authorization": "Bearer mock"},
        )
    assert buyer_view.json()["payment_bank"] is None


@pytest.mark.asyncio
async def test_payment_method_change_blocked_when_verifying(
    test_client: AsyncClient, buyer_user: User, seller_with_bank: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    order_id = create_res.json()["order_id"]

    with auth_patch(seller_with_bank):
        await test_client.post(f"/api/v1/orders/{order_id}/confirm", json={}, headers={"Authorization": "Bearer mock"})

    # Buyer uploads receipt -> status becomes VERIFYING
    fake_img = io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    with auth_patch(buyer_user):
        with patch(
            "app.modules.orders.service.upload_order_receipt",
            return_value={"secure_url": "https://cloudinary.com/receipt.jpg"},
        ):
            receipt_res = await test_client.post(
                f"/api/v1/orders/{order_id}/receipt",
                files={"file": ("receipt.jpg", fake_img, "image/jpeg")},
                headers={"Authorization": "Bearer mock"},
            )
        assert receipt_res.status_code == 200
        assert receipt_res.json()["payment_status"] == "VERIFYING"

    # Seller attempts to change payment method while VERIFYING -> BLOCKED (400)
    with auth_patch(seller_with_bank):
        edit_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={"payment_method": "CASH_ON_MEETUP"},
            headers={"Authorization": "Bearer mock"},
        )
    assert edit_res.status_code == 400


@pytest.mark.asyncio
async def test_payment_method_change_blocked_when_paid(
    test_client: AsyncClient, buyer_user: User, seller_with_bank: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    order_id = create_res.json()["order_id"]

    with auth_patch(seller_with_bank):
        await test_client.post(f"/api/v1/orders/{order_id}/confirm", json={}, headers={"Authorization": "Bearer mock"})
        await test_client.post(f"/api/v1/orders/{order_id}/confirm-payment", headers={"Authorization": "Bearer mock"})

        # Seller attempts to change payment method after PAID -> BLOCKED (400)
        edit_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={"payment_method": "BANK_TRANSFER"},
            headers={"Authorization": "Bearer mock"},
        )
    assert edit_res.status_code == 400


@pytest.mark.asyncio
async def test_changing_fulfillment_does_not_mutate_existing_bank_snapshot(
    test_client: AsyncClient, buyer_user: User, seller_with_bank: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    order_id = create_res.json()["order_id"]

    with auth_patch(seller_with_bank):
        confirm_res = await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            json={},
            headers={"Authorization": "Bearer mock"},
        )
        assert confirm_res.json()["payment_bank"]["account_number"] == "0123456789"

        # Change seller profile bank to VCB
        await test_client.put(
            "/api/v1/users/me/bank-account",
            json={
                "bank_bin": "970436",
                "account_number": "9999888877",
                "account_name": "LE VAN SELLER VCB",
            },
            headers={"Authorization": "Bearer mock"},
        )

        # Seller changes only fulfillment MEETUP -> SHIPPING on the existing order
        edit_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={
                "fulfillment_method": "SHIPPING",
                "shipping_address": "Số 10 Tràng Tiền",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert edit_res.status_code == 200
    # Snapshot on order remains MB (0123456789)
    assert edit_res.json()["payment_bank"]["account_number"] == "0123456789"
    assert edit_res.json()["payment_bank"]["bank_bin"] == "970422"


# =====================================================================
# 5. SHIPPING CASH FLOW & DELIVERY GUARDS
# =====================================================================

@pytest.mark.asyncio
async def test_shipping_cash_full_flow(
    test_client: AsyncClient, buyer_user: User, seller_with_bank: User, paid_product: Product
):
    # 1. Buyer creates SHIPPING + CASH
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "SHIPPING",
                "shipping_address": "KTX PTIT Phòng 202",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    order_id = create_res.json()["order_id"]

    # 2. Seller confirms
    with auth_patch(seller_with_bank):
        await test_client.post(f"/api/v1/orders/{order_id}/confirm", json={}, headers={"Authorization": "Bearer mock"})

        # 3. Seller moves to DELIVERING while UNPAID (allowed for SHIPPING + CASH!)
        deliv_res = await test_client.post(
            f"/api/v1/orders/{order_id}/deliver",
            headers={"Authorization": "Bearer mock"},
        )
    assert deliv_res.status_code == 200
    assert deliv_res.json()["status"] == "DELIVERING"
    assert deliv_res.json()["payment_status"] == "UNPAID"

    # 4. Attempt to complete while UNPAID -> rejected (400)
    with auth_patch(buyer_user):
        complete_fail = await test_client.post(
            f"/api/v1/orders/{order_id}/complete",
            headers={"Authorization": "Bearer mock"},
        )
    assert complete_fail.status_code == 400

    # 5. Seller receives cash and confirms payment -> PAID
    with auth_patch(seller_with_bank):
        pay_res = await test_client.post(
            f"/api/v1/orders/{order_id}/confirm-payment",
            headers={"Authorization": "Bearer mock"},
        )
    assert pay_res.status_code == 200
    assert pay_res.json()["payment_status"] == "PAID"

    # 6. Now order completes successfully
    with auth_patch(buyer_user):
        complete_ok = await test_client.post(
            f"/api/v1/orders/{order_id}/complete",
            headers={"Authorization": "Bearer mock"},
        )
    assert complete_ok.status_code == 200
    assert complete_ok.json()["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_shipping_bank_transfer_cannot_deliver_before_paid(
    test_client: AsyncClient, buyer_user: User, seller_with_bank: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "SHIPPING",
                "shipping_address": "KTX PTIT",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    order_id = create_res.json()["order_id"]

    with auth_patch(seller_with_bank):
        await test_client.post(f"/api/v1/orders/{order_id}/confirm", json={}, headers={"Authorization": "Bearer mock"})

        # Attempt to deliver while UNPAID for BANK_TRANSFER -> 400
        deliv_fail = await test_client.post(
            f"/api/v1/orders/{order_id}/deliver",
            headers={"Authorization": "Bearer mock"},
        )
    assert deliv_fail.status_code == 400

    # Buyer uploads receipt
    fake_img = io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    with auth_patch(buyer_user):
        with patch(
            "app.modules.orders.service.upload_order_receipt",
            return_value={"secure_url": "https://cloudinary.com/receipt.jpg"},
        ):
            await test_client.post(
                f"/api/v1/orders/{order_id}/receipt",
                files={"file": ("receipt.jpg", fake_img, "image/jpeg")},
                headers={"Authorization": "Bearer mock"},
            )

    # Seller confirms payment -> PAID
    with auth_patch(seller_with_bank):
        await test_client.post(f"/api/v1/orders/{order_id}/confirm-payment", headers={"Authorization": "Bearer mock"})

        # Now deliver succeeds
        deliv_ok = await test_client.post(
            f"/api/v1/orders/{order_id}/deliver",
            headers={"Authorization": "Bearer mock"},
        )
    assert deliv_ok.status_code == 200
    assert deliv_ok.json()["status"] == "DELIVERING"


# =====================================================================
# 6. FREE ORDER TRANSACTION TERMS
# =====================================================================

@pytest.mark.asyncio
async def test_free_order_seller_switch_fulfillment(
    test_client: AsyncClient, buyer_user: User, seller_no_bank: User, free_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": free_product.product_id,
                "quantity": 1,
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường",
                "contact_name": "Buyer",
                "contact_phone": "0933445566",
            },
            headers={"Authorization": "Bearer mock"},
        )
    order_id = create_res.json()["order_id"]

    # Seller switches free order to SHIPPING
    with auth_patch(seller_no_bank):
        edit_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={
                "fulfillment_method": "SHIPPING",
                "shipping_address": "Tòa A3 PTIT",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert edit_res.status_code == 200
    data = edit_res.json()
    assert data["fulfillment_method"] == "SHIPPING"
    assert data["shipping_address"] == "Tòa A3 PTIT"
    assert data["payment_method"] == "OTHER"
    assert data["payment_status"] == "PAID"


# =====================================================================
# 7. OPTIONAL EXPECTED TIME LIFECYCLE (MEETUP & SHIPPING)
# =====================================================================

@pytest.mark.asyncio
async def test_seller_shipping_expected_at_lifecycle(
    test_client: AsyncClient, buyer_user: User, seller_with_bank: User, paid_product: Product, unrelated_user: User
):
    # 1. Buyer creates order with SHIPPING
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "fulfillment_method": "SHIPPING",
                "payment_method": "CASH_ON_MEETUP",
                "shipping_address": "KTX PTIT Ha Dong",
                "contact_name": "Buyer B",
                "contact_phone": "0912345678",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert create_res.status_code == 201
    order_id = create_res.json()["order_id"]
    assert create_res.json()["shipping_expected_at"] is None

    # 2. Seller adds shipping expected time
    with auth_patch(seller_with_bank):
        edit_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={
                "shipping_expected_at": "2026-08-30T18:30:00",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert edit_res.status_code == 200
    data = edit_res.json()
    assert "2026-08-30" in data["shipping_expected_at"]
    assert data["status"] == "PENDING"  # Time does NOT mutate Order status

    # 3. Buyer reads order detail -> sees shipping_expected_at
    with auth_patch(buyer_user):
        detail_res = await test_client.get(
            f"/api/v1/orders/{order_id}",
            headers={"Authorization": "Bearer mock"},
        )
    assert detail_res.status_code == 200
    assert "2026-08-30" in detail_res.json()["shipping_expected_at"]

    # 4. Stranger cannot read order detail
    with auth_patch(unrelated_user):
        stranger_res = await test_client.get(
            f"/api/v1/orders/{order_id}",
            headers={"Authorization": "Bearer mock"},
        )
    assert stranger_res.status_code == 404

    # 5. Seller clears shipping expected time
    with auth_patch(seller_with_bank):
        clear_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={
                "shipping_expected_at": None,
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert clear_res.status_code == 200
    assert clear_res.json()["shipping_expected_at"] is None


@pytest.mark.asyncio
async def test_switching_fulfillment_cleans_up_stale_expected_times(
    test_client: AsyncClient, buyer_user: User, seller_with_bank: User, paid_product: Product
):
    # 1. Create MEETUP order with meetup_time
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "fulfillment_method": "MEETUP",
                "payment_method": "CASH_ON_MEETUP",
                "meetup_place": "Căn tin A2",
                "meetup_time": "2026-08-30T12:35:00",
                "contact_name": "Buyer B",
                "contact_phone": "0912345678",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert create_res.status_code == 201
    order_id = create_res.json()["order_id"]
    assert "2026-08-30" in create_res.json()["meetup_time"]

    # 2. Seller switches to SHIPPING with shipping_expected_at
    with auth_patch(seller_with_bank):
        switch_res = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={
                "fulfillment_method": "SHIPPING",
                "shipping_address": "Phong 301 KTX",
                "shipping_expected_at": "2026-08-30T19:00:00",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert switch_res.status_code == 200
    data = switch_res.json()
    assert data["fulfillment_method"] == "SHIPPING"
    assert data["shipping_address"] == "Phong 301 KTX"
    assert "2026-08-30" in data["shipping_expected_at"]
    # Meetup fields must be cleared
    assert data["meetup_place"] is None
    assert data["meetup_time"] is None

    # 3. Seller switches back to MEETUP with meetup_time
    with auth_patch(seller_with_bank):
        switch_back = await test_client.patch(
            f"/api/v1/orders/{order_id}/transaction-terms",
            json={
                "fulfillment_method": "MEETUP",
                "meetup_place": "Sảnh A1 PTIT",
                "meetup_time": "2026-08-31T09:00:00",
            },
            headers={"Authorization": "Bearer mock"},
        )
    assert switch_back.status_code == 200
    data2 = switch_back.json()
    assert data2["fulfillment_method"] == "MEETUP"
    assert data2["meetup_place"] == "Sảnh A1 PTIT"
    assert "2026-08-31" in data2["meetup_time"]
    # Shipping fields must be cleared
    assert data2["shipping_address"] is None
    assert data2["shipping_expected_at"] is None

