from decimal import Decimal
from uuid import uuid4
import urllib.parse
from unittest.mock import patch
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.banks import SUPPORTED_BANKS, get_bank_by_bin
from app.modules.categories.models import Category
from app.modules.orders.models import Order, OrderStatus, PaymentMethod, PaymentStatus
from app.modules.products.models import Product, ProductStatus, ListingType
from app.modules.users.models import User, UserAuthIdentity, UserStatus, UserRole


def auth_patch(user: User):
    return patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": f"uid_{user.email.split('@')[0]}",
            "email": user.email,
            "name": user.full_name,
        },
    )


@pytest_asyncio.fixture
async def sample_cat(db_session: AsyncSession) -> Category:
    cat = Category(
        name="Danh mục Test",
        slug=f"danh-muc-test-{uuid4().hex[:6]}",
        is_deleted=False,
    )
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def seller_user(db_session: AsyncSession) -> User:
    user = User(
        email="seller_bank@ptit.edu.vn",
        full_name="Nguyen Van Seller",
        phone="0911223344",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
        bank_bin="970422",  # MBBank
        bank_account_number="0123456789",
        bank_account_name="NGUYEN VAN SELLER",
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_seller_bank",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def seller_no_bank(db_session: AsyncSession) -> User:
    user = User(
        email="seller_nobank@ptit.edu.vn",
        full_name="Seller No Bank",
        phone="0911223355",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_seller_nobank",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def buyer_user(db_session: AsyncSession) -> User:
    user = User(
        email="buyer_bank@ptit.edu.vn",
        full_name="Tran Thi Buyer",
        phone="0988776655",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_buyer_bank",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def unrelated_user(db_session: AsyncSession) -> User:
    user = User(
        email="unrelated_bank@ptit.edu.vn",
        full_name="Le Van Other",
        phone="0977665544",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_unrelated_bank",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def paid_product(db_session: AsyncSession, seller_user: User, sample_cat: Category) -> Product:
    product = Product(
        seller_id=seller_user.user_id,
        category_id=sample_cat.category_id,
        title="Giao trinh Lap trinh Web",
        description="Sach con moi 99%",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal("50000"),
        stock=5,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        is_deleted=False,
    )
    db_session.add(product)
    await db_session.flush()
    return product


@pytest_asyncio.fixture
async def free_product(db_session: AsyncSession, seller_user: User, sample_cat: Category) -> Product:
    product = Product(
        seller_id=seller_user.user_id,
        category_id=sample_cat.category_id,
        title="Tai lieu on thi Mien phi",
        description="Tang cac ban sinh vien",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal("0"),
        stock=5,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        is_deleted=False,
    )
    db_session.add(product)
    await db_session.flush()
    return product


# =====================================================================
# 1. BANK PROFILE CRUD & VALIDATION TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_get_bank_account_unconfigured_returns_null(
    test_client: AsyncClient, buyer_user: User
):
    with auth_patch(buyer_user):
        response = await test_client.get(
            "/api/v1/users/me/bank-account",
            headers={"Authorization": "Bearer mock_token"},
        )
    assert response.status_code == 200
    assert response.json() is None


@pytest.mark.asyncio
async def test_update_bank_account_success(
    test_client: AsyncClient, buyer_user: User
):
    payload = {
        "bank_bin": "970422",  # MB
        "account_number": "0987654321",
        "account_name": "TRAN THI BUYER",
    }
    with auth_patch(buyer_user):
        response = await test_client.put(
            "/api/v1/users/me/bank-account",
            json=payload,
            headers={"Authorization": "Bearer mock_token"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["bank_bin"] == "970422"
    assert data["bank_code"] == "MB"
    assert data["bank_short_name"] == "MBBank"
    assert data["account_number"] == "0987654321"
    assert data["account_name"] == "TRAN THI BUYER"


@pytest.mark.asyncio
async def test_update_bank_account_with_code_resolves_to_canonical_bin(
    test_client: AsyncClient, buyer_user: User
):
    payload = {
        "bank_bin": "VCB",  # Code alias
        "account_number": "1234567890",
        "account_name": "TRAN THI BUYER",
    }
    with auth_patch(buyer_user):
        response = await test_client.put(
            "/api/v1/users/me/bank-account",
            json=payload,
            headers={"Authorization": "Bearer mock_token"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["bank_bin"] == "970436"  # Canonical BIN for VCB
    assert data["bank_code"] == "VCB"
    assert data["account_number"] == "1234567890"


@pytest.mark.asyncio
async def test_get_bank_account_configured_returns_details(
    test_client: AsyncClient, seller_user: User
):
    with auth_patch(seller_user):
        response = await test_client.get(
            "/api/v1/users/me/bank-account",
            headers={"Authorization": "Bearer mock_token"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data is not None
    assert data["bank_bin"] == "970422"
    assert data["bank_code"] == "MB"
    assert data["account_number"] == "0123456789"
    assert data["account_name"] == "NGUYEN VAN SELLER"


@pytest.mark.asyncio
async def test_delete_bank_account_success(
    test_client: AsyncClient, seller_user: User
):
    with auth_patch(seller_user):
        response = await test_client.delete(
            "/api/v1/users/me/bank-account",
            headers={"Authorization": "Bearer mock_token"},
        )
        assert response.status_code == 204

        # Subsequent GET returns null
        get_res = await test_client.get(
            "/api/v1/users/me/bank-account",
            headers={"Authorization": "Bearer mock_token"},
        )
        assert get_res.status_code == 200
        assert get_res.json() is None


@pytest.mark.asyncio
async def test_bank_account_unauthenticated_rejected(test_client: AsyncClient):
    response = await test_client.get("/api/v1/users/me/bank-account")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_bank_account_banned_user_rejected(
    test_client: AsyncClient, db_session: AsyncSession
):
    banned_user = User(
        email="banned_user@ptit.edu.vn",
        full_name="Banned User",
        status=UserStatus.BANNED,
        role=UserRole.STUDENT.value,
    )
    db_session.add(banned_user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=banned_user.user_id,
        provider="FIREBASE",
        provider_uid="uid_banned_user",
    )
    db_session.add(identity)
    await db_session.flush()

    with auth_patch(banned_user):
        response = await test_client.get(
            "/api/v1/users/me/bank-account",
            headers={"Authorization": "Bearer mock_token"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_bank_account_invalid_bank_code_rejected(
    test_client: AsyncClient, buyer_user: User
):
    payload = {
        "bank_bin": "UNKNOWN_BANK_999",
        "account_number": "0123456789",
        "account_name": "TRAN THI BUYER",
    }
    with auth_patch(buyer_user):
        response = await test_client.put(
            "/api/v1/users/me/bank-account",
            json=payload,
            headers={"Authorization": "Bearer mock_token"},
        )
    assert response.status_code in (400, 422)


@pytest.mark.asyncio
async def test_bank_account_invalid_account_number_rejected(
    test_client: AsyncClient, buyer_user: User
):
    payload = {
        "bank_bin": "970422",
        "account_number": "012 345-6789!",
        "account_name": "TRAN THI BUYER",
    }
    with auth_patch(buyer_user):
        response = await test_client.put(
            "/api/v1/users/me/bank-account",
            json=payload,
            headers={"Authorization": "Bearer mock_token"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_bank_account_not_exposed_in_user_profile_dto(
    test_client: AsyncClient, seller_user: User
):
    with auth_patch(seller_user):
        response = await test_client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer mock_token"},
        )
    assert response.status_code == 200
    data = response.json()
    assert "bank_bin" not in data
    assert "bank_account_number" not in data
    assert "bank_account_name" not in data


@pytest.mark.asyncio
async def test_supported_banks_list_endpoint(test_client: AsyncClient):
    response = await test_client.get("/api/v1/users/banks")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 30
    mb = next((b for b in data if b["bin"] == "970422"), None)
    assert mb is not None
    assert mb["code"] == "MB"
    assert mb["short_name"] == "MBBank"


# =====================================================================
# 2. ORDER BANK SNAPSHOT & SELLER CONFIRMATION TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_confirm_bank_transfer_order_snapshots_seller_bank(
    test_client: AsyncClient, buyer_user: User, seller_user: User, paid_product: Product
):
    order_payload = {
        "product_id": paid_product.product_id,
        "quantity": 1,
        "payment_method": "BANK_TRANSFER",
        "fulfillment_method": "MEETUP",
        "meetup_place": "Cong truong PTIT",
        "contact_name": "Tran Thi Buyer",
        "contact_phone": "0988776655",
    }
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json=order_payload,
            headers={"Authorization": "Bearer mock_token"},
        )
    assert create_res.status_code == 201
    order_id = create_res.json()["order_id"]

    # Pending order should NOT have payment_bank exposed yet
    assert create_res.json()["payment_bank"] is None

    # Seller confirms order
    with auth_patch(seller_user):
        confirm_res = await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            json={"payment_note": "Chuyen dung cu phap nhe"},
            headers={"Authorization": "Bearer mock_token"},
        )
    assert confirm_res.status_code == 200
    detail = confirm_res.json()
    assert detail["status"] == "CONFIRMED"
    assert detail["payment_bank"] is not None
    assert detail["payment_bank"]["bank_bin"] == "970422"
    assert detail["payment_bank"]["account_number"] == "0123456789"
    assert detail["payment_bank"]["account_name"] == "NGUYEN VAN SELLER"
    assert detail["payment_bank"]["qr_url"] is not None
    assert "https://img.vietqr.io/image/970422-0123456789-compact2.png" in detail["payment_bank"]["qr_url"]


@pytest.mark.asyncio
async def test_seller_without_bank_account_cannot_confirm_paid_bank_transfer(
    test_client: AsyncClient, db_session: AsyncSession, buyer_user: User, seller_no_bank: User, sample_cat: Category
):
    prod = Product(
        seller_id=seller_no_bank.user_id,
        category_id=sample_cat.category_id,
        title="Laptop cu",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal("100000"),
        stock=1,
        status=ProductStatus.AVAILABLE.value,
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
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "San A",
                "contact_name": "Buyer",
                "contact_phone": "0988776655",
            },
            headers={"Authorization": "Bearer mock_token"},
        )
    assert create_res.status_code == 201
    order_id = create_res.json()["order_id"]

    # Seller attempts to confirm -> rejected with 400
    with auth_patch(seller_no_bank):
        confirm_res = await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            json={},
            headers={"Authorization": "Bearer mock_token"},
        )
    assert confirm_res.status_code == 400
    assert "tài khoản nhận tiền" in confirm_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_changing_seller_profile_bank_does_not_affect_existing_order_snapshot(
    test_client: AsyncClient, buyer_user: User, seller_user: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res1 = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "San A",
                "contact_name": "Buyer",
                "contact_phone": "0988776655",
            },
            headers={"Authorization": "Bearer mock_token"},
        )
    order_id1 = create_res1.json()["order_id"]

    with auth_patch(seller_user):
        await test_client.post(
            f"/api/v1/orders/{order_id1}/confirm",
            json={},
            headers={"Authorization": "Bearer mock_token"},
        )

        # Seller changes Profile bank account to Techcombank (970407)
        update_bank_res = await test_client.put(
            "/api/v1/users/me/bank-account",
            json={
                "bank_bin": "970407",  # TCB
                "account_number": "888899990000",
                "account_name": "NGUYEN VAN SELLER TCB",
            },
            headers={"Authorization": "Bearer mock_token"},
        )
        assert update_bank_res.status_code == 200

    # Order 1 must STILL have MBBank snapshot (970422)
    with auth_patch(buyer_user):
        order1_detail = await test_client.get(
            f"/api/v1/orders/{order_id1}",
            headers={"Authorization": "Bearer mock_token"},
        )
    assert order1_detail.status_code == 200
    bank1 = order1_detail.json()["payment_bank"]
    assert bank1["bank_bin"] == "970422"
    assert bank1["account_number"] == "0123456789"
    assert bank1["account_name"] == "NGUYEN VAN SELLER"
    assert "970422" in bank1["qr_url"]

    # Subsequent Order 2 confirmed afterwards receives new TCB snapshot (970407)
    with auth_patch(buyer_user):
        create_res2 = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "San A",
                "contact_name": "Buyer",
                "contact_phone": "0988776655",
            },
            headers={"Authorization": "Bearer mock_token"},
        )
    order_id2 = create_res2.json()["order_id"]

    with auth_patch(seller_user):
        confirm2 = await test_client.post(
            f"/api/v1/orders/{order_id2}/confirm",
            json={},
            headers={"Authorization": "Bearer mock_token"},
        )
    bank2 = confirm2.json()["payment_bank"]
    assert bank2["bank_bin"] == "970407"
    assert bank2["account_number"] == "888899990000"
    assert bank2["account_name"] == "NGUYEN VAN SELLER TCB"
    assert "970407" in bank2["qr_url"]


@pytest.mark.asyncio
async def test_deleting_bank_profile_preserves_confirmed_order_snapshot(
    test_client: AsyncClient, buyer_user: User, seller_user: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "San A",
                "contact_name": "Buyer",
                "contact_phone": "0988776655",
            },
            headers={"Authorization": "Bearer mock_token"},
        )
    order_id = create_res.json()["order_id"]

    with auth_patch(seller_user):
        await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            json={},
            headers={"Authorization": "Bearer mock_token"},
        )
        del_res = await test_client.delete(
            "/api/v1/users/me/bank-account",
            headers={"Authorization": "Bearer mock_token"},
        )
        assert del_res.status_code == 204

    # Confirmed order snapshot remains intact
    with auth_patch(buyer_user):
        order_detail = await test_client.get(
            f"/api/v1/orders/{order_id}",
            headers={"Authorization": "Bearer mock_token"},
        )
    bank = order_detail.json()["payment_bank"]
    assert bank is not None
    assert bank["bank_bin"] == "970422"
    assert bank["account_number"] == "0123456789"


# =====================================================================
# 3. FREE ORDER BEHAVIOR TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_free_order_creation_without_payment_method(
    test_client: AsyncClient, buyer_user: User, free_product: Product
):
    payload = {
        "product_id": free_product.product_id,
        "quantity": 1,
        # payment_method is omitted
        "fulfillment_method": "MEETUP",
        "meetup_place": "San Canteen",
        "contact_name": "Tran Thi Buyer",
        "contact_phone": "0988776655",
    }
    with auth_patch(buyer_user):
        response = await test_client.post(
            "/api/v1/orders",
            json=payload,
            headers={"Authorization": "Bearer mock_token"},
        )
    assert response.status_code == 201
    data = response.json()
    assert Decimal(str(data["total_amount"])) == Decimal("0")
    assert data["payment_status"] == "PAID"
    assert data["paid_confirmed_at"] is not None
    assert data["payment_bank"] is None
    assert data["payment_method"] == "OTHER"  # internal sentinel


@pytest.mark.asyncio
async def test_free_order_shipping_flow(
    test_client: AsyncClient, buyer_user: User, free_product: Product
):
    payload = {
        "product_id": free_product.product_id,
        "quantity": 1,
        "fulfillment_method": "SHIPPING",
        "shipping_address": "Phong 302 KTX PTIT",
        "contact_name": "Tran Thi Buyer",
        "contact_phone": "0988776655",
    }
    with auth_patch(buyer_user):
        response = await test_client.post(
            "/api/v1/orders",
            json=payload,
            headers={"Authorization": "Bearer mock_token"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["fulfillment_method"] == "SHIPPING"
    assert data["payment_status"] == "PAID"


@pytest.mark.asyncio
async def test_free_order_requires_no_bank_account_on_seller_confirm(
    test_client: AsyncClient, db_session: AsyncSession, buyer_user: User, seller_no_bank: User, sample_cat: Category
):
    free_prod = Product(
        seller_id=seller_no_bank.user_id,
        category_id=sample_cat.category_id,
        title="Giao trinh cu tang mien phi",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal("0"),
        stock=1,
        status=ProductStatus.AVAILABLE.value,
        is_deleted=False,
    )
    db_session.add(free_prod)
    await db_session.flush()

    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": free_prod.product_id,
                "quantity": 1,
                "fulfillment_method": "MEETUP",
                "meetup_place": "Canteen",
                "contact_name": "Buyer",
                "contact_phone": "0988776655",
            },
            headers={"Authorization": "Bearer mock_token"},
        )
    assert create_res.status_code == 201
    order_id = create_res.json()["order_id"]

    # Seller with NO bank account can confirm free order successfully
    with auth_patch(seller_no_bank):
        confirm_res = await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            json={},
            headers={"Authorization": "Bearer mock_token"},
        )
    assert confirm_res.status_code == 200
    assert confirm_res.json()["status"] == "CONFIRMED"
    assert confirm_res.json()["payment_bank"] is None


@pytest.mark.asyncio
async def test_free_order_cannot_upload_receipt(
    test_client: AsyncClient, buyer_user: User, seller_user: User, free_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": free_product.product_id,
                "quantity": 1,
                "fulfillment_method": "MEETUP",
                "meetup_place": "Canteen",
                "contact_name": "Buyer",
                "contact_phone": "0988776655",
            },
            headers={"Authorization": "Bearer mock_token"},
        )
    order_id = create_res.json()["order_id"]

    with auth_patch(seller_user):
        await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            json={},
            headers={"Authorization": "Bearer mock_token"},
        )

    # Attempt to upload receipt on free order
    files = {"file": ("receipt.jpg", b"fake_image_bytes", "image/jpeg")}
    with auth_patch(buyer_user):
        receipt_res = await test_client.post(
            f"/api/v1/orders/{order_id}/receipt",
            files=files,
            headers={"Authorization": "Bearer mock_token"},
        )
    assert receipt_res.status_code == 400


# =====================================================================
# 4. PAID ORDER RULES & PAYMENT METHODS TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_paid_order_requires_payment_method(
    test_client: AsyncClient, buyer_user: User, paid_product: Product
):
    payload = {
        "product_id": paid_product.product_id,
        "quantity": 1,
        # omitted payment_method for paid product
        "fulfillment_method": "MEETUP",
        "meetup_place": "Canteen",
        "contact_name": "Buyer",
        "contact_phone": "0988776655",
    }
    with auth_patch(buyer_user):
        response = await test_client.post(
            "/api/v1/orders",
            json=payload,
            headers={"Authorization": "Bearer mock_token"},
        )
    assert response.status_code == 400
    assert "phương thức thanh toán" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_paid_meetup_supports_cash_and_bank_transfer(
    test_client: AsyncClient, buyer_user: User, paid_product: Product
):
    with auth_patch(buyer_user):
        # CASH_ON_MEETUP
        res_cash = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Canteen",
                "contact_name": "Buyer",
                "contact_phone": "0988776655",
            },
            headers={"Authorization": "Bearer mock_token"},
        )
        assert res_cash.status_code == 201

        # BANK_TRANSFER
        res_bank = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Canteen",
                "contact_name": "Buyer",
                "contact_phone": "0988776655",
            },
            headers={"Authorization": "Bearer mock_token"},
        )
        assert res_bank.status_code == 201


@pytest.mark.asyncio
async def test_paid_order_rejects_other_payment_method(
    test_client: AsyncClient, buyer_user: User, paid_product: Product
):
    with auth_patch(buyer_user):
        response = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "OTHER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Canteen",
                "contact_name": "Buyer",
                "contact_phone": "0988776655",
            },
            headers={"Authorization": "Bearer mock_token"},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_paid_shipping_cash_success(
    test_client: AsyncClient, buyer_user: User, paid_product: Product
):
    with auth_patch(buyer_user):
        response = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "SHIPPING",
                "shipping_address": "KTX PTIT",
                "contact_name": "Buyer",
                "contact_phone": "0988776655",
            },
            headers={"Authorization": "Bearer mock_token"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["fulfillment_method"] == "SHIPPING"
    assert data["payment_method"] == "CASH_ON_MEETUP"


@pytest.mark.asyncio
async def test_paid_shipping_bank_transfer_success(
    test_client: AsyncClient, buyer_user: User, paid_product: Product
):
    with auth_patch(buyer_user):
        response = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "SHIPPING",
                "shipping_address": "KTX PTIT",
                "contact_name": "Buyer",
                "contact_phone": "0988776655",
            },
            headers={"Authorization": "Bearer mock_token"},
        )
    assert response.status_code == 201
    assert response.json()["fulfillment_method"] == "SHIPPING"
    assert response.json()["payment_method"] == "BANK_TRANSFER"


# =====================================================================
# 5. VIETQR GENERATION & PRIVACY TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_vietqr_url_and_special_character_encoding(
    test_client: AsyncClient, buyer_user: User, seller_user: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 2,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "San Canteen",
                "contact_name": "Buyer",
                "contact_phone": "0988776655",
            },
            headers={"Authorization": "Bearer mock_token"},
        )
    order_id = create_res.json()["order_id"]
    order_code = create_res.json()["order_code"]

    with auth_patch(seller_user):
        confirm_res = await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            json={},
            headers={"Authorization": "Bearer mock_token"},
        )
    assert confirm_res.status_code == 200
    qr_url = confirm_res.json()["payment_bank"]["qr_url"]

    # Assert URL structure
    assert qr_url.startswith("https://img.vietqr.io/image/970422-0123456789-compact2.png?")
    parsed_url = urllib.parse.urlparse(qr_url)
    query_params = urllib.parse.parse_qs(parsed_url.query)

    assert query_params["amount"] == ["100000"]  # 50000 * 2
    assert query_params["addInfo"] == [order_code]
    assert query_params["accountName"] == ["NGUYEN VAN SELLER"]


@pytest.mark.asyncio
async def test_bank_snapshot_not_accessible_by_unrelated_user(
    test_client: AsyncClient, buyer_user: User, seller_user: User, unrelated_user: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "San Canteen",
                "contact_name": "Buyer",
                "contact_phone": "0988776655",
            },
            headers={"Authorization": "Bearer mock_token"},
        )
    order_id = create_res.json()["order_id"]

    with auth_patch(seller_user):
        await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            json={},
            headers={"Authorization": "Bearer mock_token"},
        )

    # Unrelated user gets 404
    with auth_patch(unrelated_user):
        unrelated_res = await test_client.get(
            f"/api/v1/orders/{order_id}",
            headers={"Authorization": "Bearer mock_token"},
        )
    assert unrelated_res.status_code == 404


@pytest.mark.asyncio
async def test_order_list_dto_does_not_expose_bank_snapshot(
    test_client: AsyncClient, buyer_user: User, seller_user: User, paid_product: Product
):
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "San Canteen",
                "contact_name": "Buyer",
                "contact_phone": "0988776655",
            },
            headers={"Authorization": "Bearer mock_token"},
        )
    order_id = create_res.json()["order_id"]

    with auth_patch(seller_user):
        await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            json={},
            headers={"Authorization": "Bearer mock_token"},
        )

    # Buying orders list
    with auth_patch(buyer_user):
        buying_res = await test_client.get(
            "/api/v1/orders/me/buying",
            headers={"Authorization": "Bearer mock_token"},
        )
    assert buying_res.status_code == 200
    for item in buying_res.json()["items"]:
        assert "payment_bank" not in item
        assert "payment_bank_bin" not in item
        assert "payment_bank_account_number" not in item

    # Selling orders list
    with auth_patch(seller_user):
        selling_res = await test_client.get(
            "/api/v1/orders/me/selling",
            headers={"Authorization": "Bearer mock_token"},
        )
    assert selling_res.status_code == 200
    for item in selling_res.json()["items"]:
        assert "payment_bank" not in item
        assert "payment_bank_bin" not in item
        assert "payment_bank_account_number" not in item


@pytest.mark.asyncio
async def test_changing_product_price_after_order_does_not_alter_order_total_or_qr(
    test_client: AsyncClient, db_session: AsyncSession, buyer_user: User, seller_user: User, paid_product: Product
):
    # 1. Buyer creates order when product price is 50,000đ
    with auth_patch(buyer_user):
        create_res = await test_client.post(
            "/api/v1/orders",
            json={
                "product_id": paid_product.product_id,
                "quantity": 1,
                "payment_method": "BANK_TRANSFER",
                "fulfillment_method": "MEETUP",
                "meetup_place": "San Canteen",
                "contact_name": "Buyer",
                "contact_phone": "0988776655",
            },
            headers={"Authorization": "Bearer mock_token"},
        )
    order_id = create_res.json()["order_id"]
    order_code = create_res.json()["order_code"]

    with auth_patch(seller_user):
        await test_client.post(
            f"/api/v1/orders/{order_id}/confirm",
            json={},
            headers={"Authorization": "Bearer mock_token"},
        )

    # 2. Seller changes product price in database to 150,000đ
    paid_product.price = Decimal("150000")
    await db_session.flush()

    # 3. Order detail still has total_amount = 50000 and QR amount = 50000
    with auth_patch(buyer_user):
        order_detail = await test_client.get(
            f"/api/v1/orders/{order_id}",
            headers={"Authorization": "Bearer mock_token"},
        )
    assert order_detail.status_code == 200
    detail = order_detail.json()
    assert Decimal(str(detail["total_amount"])) == Decimal("50000")
    qr_url = detail["payment_bank"]["qr_url"]
    parsed_url = urllib.parse.urlparse(qr_url)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    assert query_params["amount"] == ["50000"]
    assert query_params["addInfo"] == [order_code]


@pytest.mark.asyncio
async def test_bank_account_is_not_marked_verified(
    test_client: AsyncClient, seller_user: User
):
    with auth_patch(seller_user):
        response = await test_client.get(
            "/api/v1/users/me/bank-account",
            headers={"Authorization": "Bearer mock_token"},
        )
    assert response.status_code == 200
    data = response.json()
    assert "is_verified" not in data
    assert "verified" not in data
    assert "verified_at" not in data

