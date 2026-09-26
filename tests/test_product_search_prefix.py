import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.modules.categories.models import Category
from app.modules.products.models import Product
from app.modules.users.models import User, UserStatus, UserRole, UserAuthIdentity


@pytest_asyncio.fixture
async def search_seed_data(db_session: AsyncSession):
    # Create seller
    seller = User(
        email="seller_search_prefix@ptit.edu.vn",
        full_name="Seller Search Prefix",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(seller)
    await db_session.flush()

    db_session.add(
        UserAuthIdentity(
            user_id=seller.user_id,
            provider="FIREBASE",
            provider_uid=f"fb_seller_search_{seller.user_id}",
        )
    )
    await db_session.flush()

    # Create Categories
    cat_books = Category(name="Sách Giáo Trình PTIT", slug=f"sach-gt-search-{seller.user_id}", is_deleted=False)
    cat_tech = Category(name="Thiết Bị Điện Tử", slug=f"tb-dien-tu-search-{seller.user_id}", is_deleted=False)
    db_session.add_all([cat_books, cat_tech])
    await db_session.flush()

    # Seed products
    # A: title = "Giáo trình Giải tích 1", description = "Sách PTIT"
    p_a = Product(
        seller_id=seller.user_id,
        category_id=cat_books.category_id,
        title="Giáo trình Giải tích 1",
        description="Sách PTIT toán cao cấp",
        listing_type="FIXED_PRICE",
        price=45000,
        stock=1,
        status="AVAILABLE",
        approval_status="APPROVED",
        is_deleted=False,
    )

    # B: title = "Giáo trình Mạng Máy Tính D21", description = "Tài liệu học tập"
    p_b = Product(
        seller_id=seller.user_id,
        category_id=cat_books.category_id,
        title="Giáo trình Mạng Máy Tính D21",
        description="Tài liệu học tập kỳ 5",
        listing_type="FIXED_PRICE",
        price=60000,
        stock=1,
        status="AVAILABLE",
        approval_status="APPROVED",
        is_deleted=False,
    )

    # C: title = "Laptop gaming", description = "Máy tính"
    p_c = Product(
        seller_id=seller.user_id,
        category_id=cat_tech.category_id,
        title="Laptop gaming",
        description="Máy tính cấu hình cao",
        listing_type="FIXED_PRICE",
        price=15000000,
        stock=1,
        status="AVAILABLE",
        approval_status="APPROVED",
        is_deleted=False,
    )

    # D: HIDDEN product with matching prefix
    p_hidden = Product(
        seller_id=seller.user_id,
        category_id=cat_books.category_id,
        title="Giáo trình Cấu trúc dữ liệu ẩn",
        description="Sách ẩn không bán",
        listing_type="FIXED_PRICE",
        price=50000,
        stock=1,
        status="HIDDEN",
        approval_status="APPROVED",
        is_deleted=False,
    )

    # E: Soft-deleted product with matching prefix
    p_deleted = Product(
        seller_id=seller.user_id,
        category_id=cat_books.category_id,
        title="Giáo trình Triết học Mác đã xóa",
        description="Đã xóa khỏi hệ thống",
        listing_type="FIXED_PRICE",
        price=30000,
        stock=1,
        status="AVAILABLE",
        approval_status="APPROVED",
        is_deleted=True,
    )

    db_session.add_all([p_a, p_b, p_c, p_hidden, p_deleted])
    await db_session.flush()

    return {
        "seller": seller,
        "cat_books": cat_books,
        "cat_tech": cat_tech,
        "p_a": p_a,
        "p_b": p_b,
        "p_c": p_c,
        "p_hidden": p_hidden,
        "p_deleted": p_deleted,
    }


@pytest.mark.asyncio
async def test_prefix_search_gi_matches_giao_products(test_client: AsyncClient, search_seed_data: dict):
    """1. q=gi -> returns products whose lexeme starts with gi (A and B)."""
    res = await test_client.get("/api/v1/products?q=gi")
    assert res.status_code == 200
    titles = [p["title"] for p in res.json()["items"]]
    assert "Giáo trình Giải tích 1" in titles
    assert "Giáo trình Mạng Máy Tính D21" in titles
    assert "Laptop gaming" not in titles


@pytest.mark.asyncio
async def test_prefix_search_gia_matches_giao_products(test_client: AsyncClient, search_seed_data: dict):
    """2. q=giá -> returns A and B."""
    res = await test_client.get("/api/v1/products?q=giá")
    assert res.status_code == 200
    titles = [p["title"] for p in res.json()["items"]]
    assert "Giáo trình Giải tích 1" in titles
    assert "Giáo trình Mạng Máy Tính D21" in titles
    assert "Laptop gaming" not in titles


@pytest.mark.asyncio
async def test_prefix_search_giao_matches_giao_products(test_client: AsyncClient, search_seed_data: dict):
    """3. q=giáo -> returns A and B."""
    res = await test_client.get("/api/v1/products?q=giáo")
    assert res.status_code == 200
    titles = [p["title"] for p in res.json()["items"]]
    assert "Giáo trình Giải tích 1" in titles
    assert "Giáo trình Mạng Máy Tính D21" in titles
    assert "Laptop gaming" not in titles


@pytest.mark.asyncio
async def test_multi_token_prefix_giao_tr(test_client: AsyncClient, search_seed_data: dict):
    """4. q="giáo tr" -> returns titles containing "giáo trình"."""
    res = await test_client.get("/api/v1/products?q=giáo tr")
    assert res.status_code == 200
    titles = [p["title"] for p in res.json()["items"]]
    assert "Giáo trình Giải tích 1" in titles
    assert "Giáo trình Mạng Máy Tính D21" in titles
    assert "Laptop gaming" not in titles


@pytest.mark.asyncio
async def test_multi_token_prefix_giai_t(test_client: AsyncClient, search_seed_data: dict):
    """5. q="giải t" -> returns A ("Giáo trình Giải tích 1")."""
    res = await test_client.get("/api/v1/products?q=giải t")
    assert res.status_code == 200
    titles = [p["title"] for p in res.json()["items"]]
    assert "Giáo trình Giải tích 1" in titles
    assert "Giáo trình Mạng Máy Tính D21" not in titles
    assert "Laptop gaming" not in titles


@pytest.mark.asyncio
async def test_unmatched_prefix_returns_empty(test_client: AsyncClient, search_seed_data: dict):
    """6. q=zzzzzz -> empty result."""
    res = await test_client.get("/api/v1/products?q=zzzzzz")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 0


@pytest.mark.asyncio
async def test_whitespace_only_query_preserves_normal_listing(test_client: AsyncClient, search_seed_data: dict):
    """7. whitespace-only query -> normal semantics, no 500."""
    res = await test_client.get("/api/v1/products?q=   ")
    assert res.status_code == 200
    items = res.json()["items"]
    # Normal listing returns public available products
    titles = [p["title"] for p in items]
    assert "Giáo trình Giải tích 1" in titles
    assert "Laptop gaming" in titles


@pytest.mark.asyncio
async def test_special_characters_no_500_and_safe_semantics(test_client: AsyncClient, search_seed_data: dict):
    """8. Special tsquery characters -> no syntax error, no 500, safe behavior."""
    special_queries = [
        ":",
        "&",
        "|",
        "!",
        "()",
        "---",
        "+++",
        "c++",
        "gi:",
        "gi &",
        "gi|",
        "(gi",
        '"gi"',
        "\\",
        "'",
        "''",
        ":*",
    ]
    for q in special_queries:
        res = await test_client.get(f"/api/v1/products?q={q}")
        assert res.status_code == 200, f"Query '{q}' returned status {res.status_code}: {res.text}"
        data = res.json()
        assert "items" in data

    # gi: has usable lexeme "gi", so it should match "giáo"
    res_gi_colon = await test_client.get("/api/v1/products?q=gi:")
    assert res_gi_colon.status_code == 200
    titles = [p["title"] for p in res_gi_colon.json()["items"]]
    assert "Giáo trình Giải tích 1" in titles


@pytest.mark.asyncio
async def test_hidden_and_deleted_products_not_exposed(test_client: AsyncClient, search_seed_data: dict):
    """9 & 10. HIDDEN and soft-deleted products matching prefix are never exposed."""
    res = await test_client.get("/api/v1/products?q=giáo")
    assert res.status_code == 200
    titles = [p["title"] for p in res.json()["items"]]
    assert "Giáo trình Cấu trúc dữ liệu ẩn" not in titles
    assert "Giáo trình Triết học Mác đã xóa" not in titles


@pytest.mark.asyncio
async def test_category_filter_intersection_with_prefix(test_client: AsyncClient, search_seed_data: dict):
    """11. Category/price filters intersect correctly with prefix search."""
    cat_books = search_seed_data["cat_books"]
    cat_tech = search_seed_data["cat_tech"]

    # Search 'gi' with books category
    res_books = await test_client.get(f"/api/v1/products?q=gi&category_id={cat_books.category_id}")
    assert res_books.status_code == 200
    titles_books = [p["title"] for p in res_books.json()["items"]]
    assert "Giáo trình Giải tích 1" in titles_books
    assert "Laptop gaming" not in titles_books

    # Search 'gi' with tech category (no 'gi' books in tech category)
    res_tech = await test_client.get(f"/api/v1/products?q=gi&category_id={cat_tech.category_id}")
    assert res_tech.status_code == 200
    titles_tech = [p["title"] for p in res_tech.json()["items"]]
    assert "Giáo trình Giải tích 1" not in titles_tech


@pytest.mark.asyncio
async def test_cursor_pagination_with_prefix(test_client: AsyncClient, search_seed_data: dict):
    """12. Cursor pagination with prefix search is stable without duplicates."""
    res_p1 = await test_client.get("/api/v1/products?q=giáo&limit=1")
    assert res_p1.status_code == 200
    data_p1 = res_p1.json()
    assert len(data_p1["items"]) == 1
    assert data_p1["has_more"] is True
    cursor = data_p1["next_cursor"]
    assert cursor is not None

    res_p2 = await test_client.get(f"/api/v1/products?q=giáo&limit=1&cursor={cursor}")
    assert res_p2.status_code == 200
    data_p2 = res_p2.json()
    assert len(data_p2["items"]) == 1

    item1_id = data_p1["items"][0]["product_id"]
    item2_id = data_p2["items"][0]["product_id"]
    assert item1_id != item2_id


@pytest.mark.asyncio
async def test_nfd_decomposed_vietnamese_input_normalized_to_nfc(test_client: AsyncClient, search_seed_data: dict):
    """Decomposed NFD input 'gia\\u0301o' must normalize to NFC 'giáo' and match."""
    decomposed_giao = "gia\u0301o"
    res = await test_client.get(f"/api/v1/products?q={decomposed_giao}")
    assert res.status_code == 200
    titles = [p["title"] for p in res.json()["items"]]
    assert "Giáo trình Giải tích 1" in titles
    assert "Giáo trình Mạng Máy Tính D21" in titles


@pytest.mark.asyncio
async def test_one_character_query_safe(test_client: AsyncClient, search_seed_data: dict):
    """Single-character query like q=g does not fail with 500."""
    res = await test_client.get("/api/v1/products?q=g")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data


@pytest.mark.asyncio
async def test_actual_postgresql_prefix_tsquery_expression(db_session: AsyncSession):
    """Assert actual PostgreSQL behavior for tsquery transformation."""
    res = await db_session.execute(text("""
        SELECT 
            plainto_tsquery('simple', 'gi')::text as q1,
            to_tsquery('simple', plainto_tsquery('simple', 'gi')::text || ':*')::text as q1_prefix,
            plainto_tsquery('simple', 'giáo tr')::text as q2,
            to_tsquery('simple', plainto_tsquery('simple', 'giáo tr')::text || ':*')::text as q2_prefix,
            plainto_tsquery('simple', 'giải t')::text as q3,
            to_tsquery('simple', plainto_tsquery('simple', 'giải t')::text || ':*')::text as q3_prefix
    """))
    row = res.mappings().one()
    assert row["q1_prefix"] == "'gi':*"
    assert row["q2_prefix"] == "'giáo' & 'tr':*"
    assert row["q3_prefix"] == "'giải' & 't':*"
