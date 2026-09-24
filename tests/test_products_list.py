from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auctions.models import Auction, AuctionStatus
from app.modules.categories.models import Category
from app.modules.products.models import Product, ProductImage
from app.modules.users.models import User, UserStatus, UserRole, UserAuthIdentity


@pytest_asyncio.fixture
async def seed_data(db_session: AsyncSession):
    # Sellers
    seller1 = User(
        email="seller_list1@ptit.edu.vn",
        full_name="Seller List 1",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    seller2 = User(
        email="seller_list2@ptit.edu.vn",
        full_name="Seller List 2",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add_all([seller1, seller2])
    await db_session.flush()

    db_session.add_all([
        UserAuthIdentity(user_id=seller1.user_id, provider="FIREBASE", provider_uid="fb_seller_list1"),
        UserAuthIdentity(user_id=seller2.user_id, provider="FIREBASE", provider_uid="fb_seller_list2"),
    ])
    await db_session.flush()

    # Categories
    cat_books = Category(name="Sách Giáo Trình", slug="sach-gt", is_deleted=False)
    cat_tech = Category(name="Thiết Bị Điện Tử", slug="tb-dien-tu", is_deleted=False)
    db_session.add_all([cat_books, cat_tech])
    await db_session.flush()

    # Products for Seller 1
    # 1. Available Book
    p1 = Product(
        seller_id=seller1.user_id,
        category_id=cat_books.category_id,
        title="Sách Lập trình C++ căn bản",
        description="Sách học kỳ 1 của khoa CNTT PTIT",
        listing_type="FIXED_PRICE",
        price=45000,
        stock=2,
        reserved_stock=1,
        status="AVAILABLE",
        is_deleted=False,
    )
    # 2. Available Tech
    p2 = Product(
        seller_id=seller1.user_id,
        category_id=cat_tech.category_id,
        title="Chuột máy tính không dây Logitech M331",
        description="Chuột silent click màu đen pin dùng 1 năm",
        listing_type="FIXED_PRICE",
        price=200000,
        stock=1,
        reserved_stock=0,
        status="AVAILABLE",
        is_deleted=False,
    )
    # 3. Hidden Product
    p3 = Product(
        seller_id=seller1.user_id,
        category_id=cat_tech.category_id,
        title="Bàn phím cơ DareU ẩn",
        description="Đang giữ hàng cho bạn cùng phòng",
        listing_type="FIXED_PRICE",
        price=350000,
        stock=1,
        reserved_stock=0,
        status="HIDDEN",
        is_deleted=False,
    )
    # 4. Soft-deleted Product
    p4 = Product(
        seller_id=seller1.user_id,
        category_id=cat_books.category_id,
        title="Sách cũ đã xóa",
        description="Không bán nữa",
        listing_type="FIXED_PRICE",
        price=10000,
        stock=1,
        reserved_stock=0,
        status="AVAILABLE",
        is_deleted=True,
    )
    # 5. Product for Seller 2 (Auction)
    p5 = Product(
        seller_id=seller2.user_id,
        category_id=cat_tech.category_id,
        title="Máy tính Casio fx 580 VNX đấu giá",
        description="Máy tính cầm tay dùng cho thi trắc nghiệm Toán",
        listing_type="AUCTION",
        price=300000,
        stock=1,
        reserved_stock=0,
        status="AVAILABLE",
        is_deleted=False,
    )

    db_session.add_all([p1, p2, p3, p4, p5])
    await db_session.flush()

    auc5 = Auction(
        product_id=p5.product_id,
        starting_price=p5.price,
        bid_step=Decimal("10000"),
        starts_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ends_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1),
        status=AuctionStatus.ACTIVE.value,
    )
    db_session.add(auc5)
    await db_session.flush()

    # Images
    img1 = ProductImage(
        product_id=p1.product_id,
        image_url="https://res.cloudinary.com/demo/image/upload/v1234/book1.jpg",
        sort_order=0,
        is_thumbnail=True,
    )
    img2 = ProductImage(
        product_id=p2.product_id,
        image_url="https://res.cloudinary.com/demo/image/upload/v1234/mouse.jpg",
        sort_order=0,
        is_thumbnail=True,
    )
    db_session.add_all([img1, img2])
    await db_session.flush()

    return {
        "seller1": seller1,
        "seller2": seller2,
        "cat_books": cat_books,
        "cat_tech": cat_tech,
        "products": [p1, p2, p3, p4, p5],
    }


@pytest.mark.asyncio
async def test_public_list_available_only(test_client: AsyncClient, seed_data: dict):
    res = await test_client.get("/api/v1/products")
    assert res.status_code == 200
    data = res.json()
    items = data["items"]

    titles = [item["title"] for item in items]
    assert "Sách Lập trình C++ căn bản" in titles
    assert "Chuột máy tính không dây Logitech M331" in titles
    assert "Máy tính Casio fx 580 VNX đấu giá" in titles

    assert "Bàn phím cơ DareU ẩn" not in titles
    assert "Sách cũ đã xóa" not in titles

    # DTO public không expose reserved_stock
    p1_data = next(item for item in items if item["title"] == "Sách Lập trình C++ căn bản")
    assert p1_data["available_stock"] == 1
    assert "reserved_stock" not in p1_data
    assert "item_condition" not in p1_data
    assert "f_auto,q_auto,w_200" in p1_data["thumbnail_url"]
    assert "view_count" in p1_data
    assert isinstance(p1_data["view_count"], int)


@pytest.mark.asyncio
async def test_filter_category_listing_type(test_client: AsyncClient, seed_data: dict):
    cat_books = seed_data["cat_books"]
    cat_tech = seed_data["cat_tech"]

    res_cat = await test_client.get(f"/api/v1/products?category_id={cat_books.category_id}")
    assert res_cat.status_code == 200
    items_cat = res_cat.json()["items"]
    assert len(items_cat) == 1
    assert items_cat[0]["title"] == "Sách Lập trình C++ căn bản"

    res_type = await test_client.get(f"/api/v1/products?category_id={cat_tech.category_id}&listing_type=AUCTION")
    assert res_type.status_code == 200
    items_type = res_type.json()["items"]
    assert len(items_type) == 1
    assert items_type[0]["title"] == "Máy tính Casio fx 580 VNX đấu giá"


@pytest.mark.asyncio
async def test_filter_price_range(test_client: AsyncClient, seed_data: dict):
    cat_tech = seed_data["cat_tech"]
    res = await test_client.get(f"/api/v1/products?category_id={cat_tech.category_id}&min_price=50000&max_price=250000")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Chuột máy tính không dây Logitech M331"

    res_inv = await test_client.get("/api/v1/products?min_price=500000&max_price=100000")
    assert res_inv.status_code == 422


@pytest.mark.asyncio
async def test_invalid_cursor_and_limit_rejected(test_client: AsyncClient, seed_data: dict):
    res_cur = await test_client.get("/api/v1/products?cursor=not-valid-base64!@#")
    assert res_cur.status_code == 422

    res_lim1 = await test_client.get("/api/v1/products?limit=100")
    assert res_lim1.status_code == 422

    res_lim2 = await test_client.get("/api/v1/products?limit=0")
    assert res_lim2.status_code == 422


@pytest.mark.asyncio
async def test_keyset_cursor_pagination(test_client: AsyncClient, seed_data: dict, db_session: AsyncSession):
    cat = Category(name="Cat Pagination", slug=f"cat-page-{seed_data['seller1'].user_id}", is_deleted=False)
    db_session.add(cat)
    await db_session.flush()

    for i in range(3):
        p = Product(
            seller_id=seed_data["seller1"].user_id,
            category_id=cat.category_id,
            title=f"Paginated Item {i+1}",
            price=10000 * (i + 1),
            stock=1,
            status="AVAILABLE",
            is_deleted=False,
        )
        db_session.add(p)
    await db_session.flush()

    res_p1 = await test_client.get(f"/api/v1/products?category_id={cat.category_id}&limit=2")
    assert res_p1.status_code == 200
    data_p1 = res_p1.json()
    assert len(data_p1["items"]) == 2
    assert data_p1["has_more"] is True
    assert data_p1["next_cursor"] is not None

    cursor = data_p1["next_cursor"]
    res_p2 = await test_client.get(f"/api/v1/products?category_id={cat.category_id}&limit=2&cursor={cursor}")
    assert res_p2.status_code == 200
    data_p2 = res_p2.json()
    assert len(data_p2["items"]) == 1
    assert data_p2["has_more"] is False
    assert data_p2["next_cursor"] is None

    p1_ids = {item["product_id"] for item in data_p1["items"]}
    p2_ids = {item["product_id"] for item in data_p2["items"]}
    assert p1_ids.isdisjoint(p2_ids)


@pytest.mark.asyncio
async def test_postgresql_fulltext_search(test_client: AsyncClient, seed_data: dict):
    res1 = await test_client.get("/api/v1/products?q=Logitech")
    assert res1.status_code == 200
    items1 = res1.json()["items"]
    assert len(items1) == 1
    assert items1[0]["title"] == "Chuột máy tính không dây Logitech M331"

    res2 = await test_client.get("/api/v1/products?q=Casio")
    assert res2.status_code == 200
    items2 = res2.json()["items"]
    assert len(items2) == 1
    assert items2[0]["title"] == "Máy tính Casio fx 580 VNX đấu giá"


@pytest.mark.asyncio
async def test_seller_my_products_list(test_client: AsyncClient, seed_data: dict):
    seller1 = seed_data["seller1"]

    with patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": "fb_seller_list1",
            "email": seller1.email,
            "name": seller1.full_name,
        },
    ):
        res = await test_client.get(
            "/api/v1/products/me",
            headers={"Authorization": "Bearer seller1_token"},
        )
        assert res.status_code == 200
        items = res.json()["items"]
        titles = [i["title"] for i in items]
        assert "Sách Lập trình C++ căn bản" in titles
        assert "Chuột máy tính không dây Logitech M331" in titles
        assert "Bàn phím cơ DareU ẩn" in titles
        assert "Sách cũ đã xóa" not in titles
        assert "Máy tính Casio fx 580 VNX đấu giá" not in titles

        p1_item = next(i for i in items if i["title"] == "Sách Lập trình C++ căn bản")
        assert p1_item["stock"] == 2
        assert p1_item["reserved_stock"] == 1
        assert p1_item["available_stock"] == 1
        assert "item_condition" not in p1_item

        res_hidden = await test_client.get(
            "/api/v1/products/me?status=HIDDEN",
            headers={"Authorization": "Bearer seller1_token"},
        )
        assert res_hidden.status_code == 200
        hidden_items = res_hidden.json()["items"]
        assert len(hidden_items) == 1
        assert hidden_items[0]["title"] == "Bàn phím cơ DareU ẩn"
