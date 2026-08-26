import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.categories.models import Category


@pytest.mark.asyncio
async def test_list_active_categories(test_client: AsyncClient, db_session: AsyncSession):
    c1 = Category(name="Giáo trình & Sách", slug="giao-trinh-sach", is_deleted=False)
    c2 = Category(name="Đồ điện tử", slug="do-dien-tu", is_deleted=False)
    c3 = Category(name="Danh mục cũ", slug="danh-muc-cu", is_deleted=True)
    db_session.add_all([c1, c2, c3])
    await db_session.flush()

    response = await test_client.get("/api/v1/categories")
    assert response.status_code == 200
    data = response.json()
    slugs = [item["slug"] for item in data]
    assert "giao-trinh-sach" in slugs
    assert "do-dien-tu" in slugs
    assert "danh-muc-cu" not in slugs


@pytest.mark.asyncio
async def test_get_category_by_id(test_client: AsyncClient, db_session: AsyncSession):
    c1 = Category(name="Đồ gia dụng", slug="do-gia-dung", is_deleted=False)
    c2 = Category(name="Đồ bị xóa", slug="do-bi-xoa", is_deleted=True)
    db_session.add_all([c1, c2])
    await db_session.flush()

    res = await test_client.get(f"/api/v1/categories/{c1.category_id}")
    assert res.status_code == 200
    assert res.json()["name"] == "Đồ gia dụng"

    res_del = await test_client.get(f"/api/v1/categories/{c2.category_id}")
    assert res_del.status_code == 404

    res_none = await test_client.get("/api/v1/categories/999999")
    assert res_none.status_code == 404
