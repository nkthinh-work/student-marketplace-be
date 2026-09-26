from decimal import Decimal
from unittest.mock import patch
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.categories.models import Category
from app.modules.products.models import Product, ProductImage
from app.modules.users.models import User, UserStatus, UserRole, UserAuthIdentity


@pytest_asyncio.fixture
async def detail_data(db_session: AsyncSession):
    seller = User(
        email="seller_detail@ptit.edu.vn",
        full_name="Seller Detail",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
        default_meetup_area="Sảnh A1 PTIT",
    )
    other = User(
        email="other_detail@ptit.edu.vn",
        full_name="Other Buyer",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add_all([seller, other])
    await db_session.flush()

    db_session.add_all([
        UserAuthIdentity(user_id=seller.user_id, provider="FIREBASE", provider_uid="fb_seller_detail"),
        UserAuthIdentity(user_id=other.user_id, provider="FIREBASE", provider_uid="fb_other_detail"),
    ])
    await db_session.flush()

    category = Category(name="Đồ Công Nghệ", slug="do-cn", is_deleted=False)
    db_session.add(category)
    await db_session.flush()

    # Available product with 2 images
    p_avail = Product(
        seller_id=seller.user_id,
        category_id=category.category_id,
        title="iPad Air 4 64GB Wifi",
        description="Máy màu xám, đầy đủ hộp và sạc zin",
        listing_type="FIXED_PRICE",
        price=8500000,
        stock=1,
        reserved_stock=0,
        status="AVAILABLE",
        approval_status="APPROVED",
        is_deleted=False,
    )
    # Hidden product
    p_hidden = Product(
        seller_id=seller.user_id,
        category_id=category.category_id,
        title="Apple Pencil 2 ẩn",
        description="Bút cảm ứng cho iPad",
        listing_type="FIXED_PRICE",
        price=1800000,
        stock=1,
        reserved_stock=0,
        status="HIDDEN",
        approval_status="APPROVED",
        is_deleted=False,
    )
    # Soft-deleted product
    p_deleted = Product(
        seller_id=seller.user_id,
        category_id=category.category_id,
        title="Bao da iPad cũ đã xóa",
        description="Đã vứt",
        listing_type="FIXED_PRICE",
        price=50000,
        stock=1,
        reserved_stock=0,
        status="AVAILABLE",
        approval_status="APPROVED",
        is_deleted=True,
    )
    db_session.add_all([p_avail, p_hidden, p_deleted])
    await db_session.flush()

    img1 = ProductImage(
        product_id=p_avail.product_id,
        image_url="https://res.cloudinary.com/demo/image/upload/v1234/ipad1.jpg",
        sort_order=0,
        is_thumbnail=True,
    )
    img2 = ProductImage(
        product_id=p_avail.product_id,
        image_url="https://res.cloudinary.com/demo/image/upload/v1234/ipad2.jpg",
        sort_order=1,
        is_thumbnail=False,
    )
    db_session.add_all([img1, img2])
    await db_session.flush()

    return {
        "seller": seller,
        "other": other,
        "p_avail": p_avail,
        "p_hidden": p_hidden,
        "p_deleted": p_deleted,
    }


@pytest.mark.asyncio
async def test_get_product_detail_public_available(test_client: AsyncClient, detail_data: dict):
    p_avail = detail_data["p_avail"]

    res = await test_client.get(f"/api/v1/products/{p_avail.product_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "iPad Air 4 64GB Wifi"
    assert data["available_stock"] == 1
    assert "reserved_stock" not in data
    assert "item_condition" not in data
    assert len(data["images"]) == 2
    assert "f_auto,q_auto,w_800" in data["images"][0]["detail_url"]
    assert data["seller"]["default_meetup_area"] == "Sảnh A1 PTIT"


@pytest.mark.asyncio
async def test_get_product_detail_soft_deleted_404(test_client: AsyncClient, detail_data: dict):
    p_deleted = detail_data["p_deleted"]

    res = await test_client.get(f"/api/v1/products/{p_deleted.product_id}")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_get_product_detail_hidden_public_404(test_client: AsyncClient, detail_data: dict):
    p_hidden = detail_data["p_hidden"]

    res = await test_client.get(f"/api/v1/products/{p_hidden.product_id}")
    assert res.status_code == 404

    other = detail_data["other"]
    with patch(
        "app.modules.products.router.verify_firebase_token",
        return_value={
            "uid": "fb_other_detail",
            "email": other.email,
            "name": other.full_name,
        },
    ):
        res_other = await test_client.get(
            f"/api/v1/products/{p_hidden.product_id}",
            headers={"Authorization": "Bearer other_token"},
        )
        assert res_other.status_code == 404


@pytest.mark.asyncio
async def test_get_product_detail_hidden_owner_200(test_client: AsyncClient, detail_data: dict):
    p_hidden = detail_data["p_hidden"]
    seller = detail_data["seller"]

    with patch(
        "app.modules.products.router.verify_firebase_token",
        return_value={
            "uid": "fb_seller_detail",
            "email": seller.email,
            "name": seller.full_name,
        },
    ):
        res = await test_client.get(
            f"/api/v1/products/{p_hidden.product_id}",
            headers={"Authorization": "Bearer seller_token"},
        )
        assert res.status_code == 200
        assert res.json()["title"] == "Apple Pencil 2 ẩn"
        assert res.json()["status"] == "HIDDEN"
        assert "item_condition" not in res.json()
