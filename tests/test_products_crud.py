from decimal import Decimal
from unittest.mock import patch
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.categories.models import Category
from app.modules.products.models import Product, ListingType, ProductStatus
from app.modules.users.models import User, UserStatus, UserRole, UserAuthIdentity


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> Category:
    cat = Category(name="Sách Giáo Trình", slug="sach-giao-trinh", is_deleted=False)
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def seller_user(db_session: AsyncSession) -> User:
    user = User(
        email="seller1@ptit.edu.vn",
        full_name="Seller One",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="firebase_seller_1",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        email="other@ptit.edu.vn",
        full_name="Other User",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="firebase_other",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_create_product_success(
    test_client: AsyncClient,
    seller_user: User,
    sample_category: Category,
):
    with patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": "firebase_seller_1",
            "email": seller_user.email,
            "name": seller_user.full_name,
        },
    ):
        payload = {
            "category_id": sample_category.category_id,
            "title": "Giáo trình Giải tích 1 PTIT",
            "description": "Sách còn mới 95%, không rách bìa",
            "listing_type": "FIXED_PRICE",
            "price": 50000,
            "stock": 1,
        }
        response = await test_client.post(
            "/api/v1/products",
            json=payload,
            headers={"Authorization": "Bearer valid_seller_token"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Giáo trình Giải tích 1 PTIT"
        assert Decimal(str(data["price"])) == Decimal(50000)
        assert data["available_stock"] == 1
        assert data["status"] == "AVAILABLE"
        assert data["seller"]["public_id"] == str(seller_user.public_id)
        assert data["category"]["category_id"] == sample_category.category_id
        assert "item_condition" not in data


@pytest.mark.asyncio
async def test_create_product_with_item_condition_rejected(
    test_client: AsyncClient,
    seller_user: User,
    sample_category: Category,
):
    """Regression test: client sending item_condition must be rejected with 422."""
    with patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": "firebase_seller_1",
            "email": seller_user.email,
            "name": seller_user.full_name,
        },
    ):
        payload = {
            "category_id": sample_category.category_id,
            "title": "Test product with condition",
            "item_condition": "USED_GOOD",
            "listing_type": "FIXED_PRICE",
            "price": 50000,
            "stock": 1,
        }
        response = await test_client.post(
            "/api/v1/products",
            json=payload,
            headers={"Authorization": "Bearer valid_seller_token"},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_product_unauthenticated(
    test_client: AsyncClient,
    sample_category: Category,
):
    payload = {
        "category_id": sample_category.category_id,
        "title": "Test product",
        "listing_type": "FIXED_PRICE",
        "price": 10000,
        "stock": 1,
    }
    response = await test_client.post("/api/v1/products", json=payload)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_product_banned_user(
    test_client: AsyncClient,
    db_session: AsyncSession,
    sample_category: Category,
):
    banned_user = User(
        email="banned@ptit.edu.vn",
        full_name="Banned User",
        role=UserRole.STUDENT.value,
        status=UserStatus.BANNED,
    )
    db_session.add(banned_user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=banned_user.user_id,
        provider="FIREBASE",
        provider_uid="firebase_banned",
    )
    db_session.add(identity)
    await db_session.flush()

    with patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": "firebase_banned",
            "email": banned_user.email,
            "name": banned_user.full_name,
        },
    ):
        payload = {
            "category_id": sample_category.category_id,
            "title": "Banned test",
            "listing_type": "FIXED_PRICE",
            "price": 10000,
            "stock": 1,
        }
        response = await test_client.post(
            "/api/v1/products",
            json=payload,
            headers={"Authorization": "Bearer banned_token"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_product_invalid_category(
    test_client: AsyncClient,
    seller_user: User,
):
    with patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": "firebase_seller_1",
            "email": seller_user.email,
            "name": seller_user.full_name,
        },
    ):
        payload = {
            "category_id": 999999,
            "title": "Invalid category test",
            "listing_type": "FIXED_PRICE",
            "price": 10000,
            "stock": 1,
        }
        response = await test_client.post(
            "/api/v1/products",
            json=payload,
            headers={"Authorization": "Bearer valid_seller_token"},
        )
        assert response.status_code == 404
        assert "Category not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_product_protected_fields_rejected(
    test_client: AsyncClient,
    seller_user: User,
    sample_category: Category,
):
    with patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": "firebase_seller_1",
            "email": seller_user.email,
            "name": seller_user.full_name,
        },
    ):
        payload = {
            "category_id": sample_category.category_id,
            "title": "Injection test",
            "listing_type": "FIXED_PRICE",
            "price": 10000,
            "stock": 1,
            "seller_id": 999,
        }
        response = await test_client.post(
            "/api/v1/products",
            json=payload,
            headers={"Authorization": "Bearer valid_seller_token"},
        )
        assert response.status_code == 422

        for forbidden_key in ["reserved_stock", "view_count", "is_deleted", "status"]:
            bad_payload = {
                "category_id": sample_category.category_id,
                "title": "Injection test",
                "listing_type": "FIXED_PRICE",
                "price": 10000,
                "stock": 1,
                forbidden_key: 123 if forbidden_key != "is_deleted" else True,
            }
            res = await test_client.post(
                "/api/v1/products",
                json=bad_payload,
                headers={"Authorization": "Bearer valid_seller_token"},
            )
            assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_product_negative_price_stock_rejected(
    test_client: AsyncClient,
    seller_user: User,
    sample_category: Category,
):
    with patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": "firebase_seller_1",
            "email": seller_user.email,
            "name": seller_user.full_name,
        },
    ):
        res_price = await test_client.post(
            "/api/v1/products",
            json={
                "category_id": sample_category.category_id,
                "title": "Neg price",
                "price": -100,
                "stock": 1,
            },
            headers={"Authorization": "Bearer valid_seller_token"},
        )
        assert res_price.status_code == 422

        res_stock = await test_client.post(
            "/api/v1/products",
            json={
                "category_id": sample_category.category_id,
                "title": "Neg stock",
                "price": 100,
                "stock": -1,
            },
            headers={"Authorization": "Bearer valid_seller_token"},
        )
        assert res_stock.status_code == 422


@pytest.mark.asyncio
async def test_update_product_owner_success(
    test_client: AsyncClient,
    seller_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Bàn phím cơ cũ",
        listing_type="FIXED_PRICE",
        price=300000,
        stock=1,
        status="AVAILABLE",
    )
    db_session.add(prod)
    await db_session.flush()

    with patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": "firebase_seller_1",
            "email": seller_user.email,
            "name": seller_user.full_name,
        },
    ):
        payload = {
            "title": "Bàn phím cơ DareU (Đã cập nhật)",
            "price": 250000,
            "status": "HIDDEN",
        }
        res = await test_client.patch(
            f"/api/v1/products/{prod.product_id}",
            json=payload,
            headers={"Authorization": "Bearer valid_seller_token"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["title"] == "Bàn phím cơ DareU (Đã cập nhật)"
        assert Decimal(str(data["price"])) == Decimal(250000)
        assert data["status"] == "HIDDEN"
        assert "item_condition" not in data


@pytest.mark.asyncio
async def test_update_product_with_item_condition_rejected(
    test_client: AsyncClient,
    seller_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    """Regression test: client sending item_condition in PATCH must be rejected with 422."""
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Bàn phím cơ cũ",
        listing_type="FIXED_PRICE",
        price=300000,
        stock=1,
        status="AVAILABLE",
    )
    db_session.add(prod)
    await db_session.flush()

    with patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": "firebase_seller_1",
            "email": seller_user.email,
            "name": seller_user.full_name,
        },
    ):
        payload = {
            "item_condition": "USED_FAIR",
        }
        res = await test_client.patch(
            f"/api/v1/products/{prod.product_id}",
            json=payload,
            headers={"Authorization": "Bearer valid_seller_token"},
        )
        assert res.status_code == 422


@pytest.mark.asyncio
async def test_update_product_set_sold_out_rejected(
    test_client: AsyncClient,
    seller_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Màn hình 24 inch",
        listing_type="FIXED_PRICE",
        price=1500000,
        stock=1,
        status="AVAILABLE",
    )
    db_session.add(prod)
    await db_session.flush()

    with patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": "firebase_seller_1",
            "email": seller_user.email,
            "name": seller_user.full_name,
        },
    ):
        payload = {"status": "SOLD_OUT"}
        res = await test_client.patch(
            f"/api/v1/products/{prod.product_id}",
            json=payload,
            headers={"Authorization": "Bearer valid_seller_token"},
        )
        assert res.status_code == 422


@pytest.mark.asyncio
async def test_update_product_non_owner_forbidden(
    test_client: AsyncClient,
    seller_user: User,
    other_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Tai nghe Sony",
        price=500000,
        stock=1,
    )
    db_session.add(prod)
    await db_session.flush()

    with patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": "firebase_other",
            "email": other_user.email,
            "name": other_user.full_name,
        },
    ):
        payload = {"price": 1000}
        res = await test_client.patch(
            f"/api/v1/products/{prod.product_id}",
            json=payload,
            headers={"Authorization": "Bearer other_token"},
        )
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_update_product_protected_fields_rejected(
    test_client: AsyncClient,
    seller_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Laptop Dell",
        price=5000000,
        stock=1,
    )
    db_session.add(prod)
    await db_session.flush()

    with patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": "firebase_seller_1",
            "email": seller_user.email,
            "name": seller_user.full_name,
        },
    ):
        res = await test_client.patch(
            f"/api/v1/products/{prod.product_id}",
            json={"seller_id": 999, "reserved_stock": 5},
            headers={"Authorization": "Bearer valid_seller_token"},
        )
        assert res.status_code == 422


@pytest.mark.asyncio
async def test_soft_delete_product_owner_success(
    test_client: AsyncClient,
    seller_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Chuột Logitech",
        price=200000,
        stock=1,
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()

    with patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": "firebase_seller_1",
            "email": seller_user.email,
            "name": seller_user.full_name,
        },
    ):
        res = await test_client.delete(
            f"/api/v1/products/{prod.product_id}",
            headers={"Authorization": "Bearer valid_seller_token"},
        )
        assert res.status_code == 204

        get_res = await test_client.get(f"/api/v1/products/{prod.product_id}")
        assert get_res.status_code == 404


@pytest.mark.asyncio
async def test_soft_delete_product_non_owner_forbidden(
    test_client: AsyncClient,
    seller_user: User,
    other_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Chuột Razer",
        price=200000,
        stock=1,
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()

    with patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": "firebase_other",
            "email": other_user.email,
            "name": other_user.full_name,
        },
    ):
        res = await test_client.delete(
            f"/api/v1/products/{prod.product_id}",
            headers={"Authorization": "Bearer other_token"},
        )
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_product_price_boundary_validation(
    test_client: AsyncClient,
    seller_user: User,
    sample_category: Category,
):
    with patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": "firebase_seller_1",
            "email": seller_user.email,
            "name": seller_user.full_name,
        },
    ):
        # 1. Price = 0 is valid
        res_zero = await test_client.post(
            "/api/v1/products",
            headers={"Authorization": "Bearer token"},
            json={
                "category_id": sample_category.category_id,
                "title": "Sách tặng 0 đồng",
                "price": 0,
                "stock": 1,
            },
        )
        assert res_zero.status_code == 201
        prod_id = res_zero.json()["product_id"]

        # 2. Price = 50,000,000 is valid
        res_max = await test_client.post(
            "/api/v1/products",
            headers={"Authorization": "Bearer token"},
            json={
                "category_id": sample_category.category_id,
                "title": "Laptop cao cấp",
                "price": 50000000,
                "stock": 1,
            },
        )
        assert res_max.status_code == 201

        # 3. Price = 50,000,001 is invalid (upper bound violation)
        res_over = await test_client.post(
            "/api/v1/products",
            headers={"Authorization": "Bearer token"},
            json={
                "category_id": sample_category.category_id,
                "title": "Vượt trần giá",
                "price": 50000001,
                "stock": 1,
            },
        )
        assert res_over.status_code == 422

        # 4. Price negative is invalid
        res_neg = await test_client.post(
            "/api/v1/products",
            headers={"Authorization": "Bearer token"},
            json={
                "category_id": sample_category.category_id,
                "title": "Giá âm",
                "price": -1000,
                "stock": 1,
            },
        )
        assert res_neg.status_code == 422

        # 5. Price decimal is invalid
        res_dec = await test_client.post(
            "/api/v1/products",
            headers={"Authorization": "Bearer token"},
            json={
                "category_id": sample_category.category_id,
                "title": "Giá thập phân",
                "price": 100.5,
                "stock": 1,
            },
        )
        assert res_dec.status_code == 422

        # 6. Update to 50_000_001 is invalid
        res_up_over = await test_client.patch(
            f"/api/v1/products/{prod_id}",
            headers={"Authorization": "Bearer token"},
            json={"price": 50000001},
        )
        assert res_up_over.status_code == 422

        # 7. Update to decimal is invalid
        res_up_dec = await test_client.patch(
            f"/api/v1/products/{prod_id}",
            headers={"Authorization": "Bearer token"},
            json={"price": 15000.75},
        )
        assert res_up_dec.status_code == 422

        # 8. Update to valid 50,000,000 succeeds
        res_up_valid = await test_client.patch(
            f"/api/v1/products/{prod_id}",
            headers={"Authorization": "Bearer token"},
            json={"price": 50000000},
        )
        assert res_up_valid.status_code == 200
        assert Decimal(str(res_up_valid.json()["price"])) == Decimal("50000000")
