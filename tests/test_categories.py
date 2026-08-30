import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.categories.models import Category


@pytest.mark.asyncio
async def test_list_active_categories(test_client: AsyncClient, db_session: AsyncSession):
    uid = uuid.uuid4().hex[:6]
    slug1 = f"giao-trinh-sach-{uid}"
    slug2 = f"do-dien-tu-{uid}"
    slug3 = f"danh-muc-cu-{uid}"
    c1 = Category(name=f"Giáo trình {uid}", slug=slug1, is_deleted=False)
    c2 = Category(name=f"Đồ điện tử {uid}", slug=slug2, is_deleted=False)
    c3 = Category(name=f"Danh mục cũ {uid}", slug=slug3, is_deleted=True)
    db_session.add_all([c1, c2, c3])
    await db_session.flush()

    response = await test_client.get("/api/v1/categories")
    assert response.status_code == 200
    data = response.json()
    slugs = [item["slug"] for item in data]
    assert slug1 in slugs
    assert slug2 in slugs
    assert slug3 not in slugs


@pytest.mark.asyncio
async def test_get_category_by_id(test_client: AsyncClient, db_session: AsyncSession):
    uid = uuid.uuid4().hex[:6]
    slug1 = f"do-gia-dung-{uid}"
    slug2 = f"do-bi-xoa-{uid}"
    c1 = Category(name=f"Đồ gia dụng {uid}", slug=slug1, is_deleted=False)
    c2 = Category(name=f"Đồ bị xóa {uid}", slug=slug2, is_deleted=True)
    db_session.add_all([c1, c2])
    await db_session.flush()

    res = await test_client.get(f"/api/v1/categories/{c1.category_id}")
    assert res.status_code == 200
    assert res.json()["name"] == f"Đồ gia dụng {uid}"

    res_del = await test_client.get(f"/api/v1/categories/{c2.category_id}")
    assert res_del.status_code == 404

    res_none = await test_client.get("/api/v1/categories/999999")
    assert res_none.status_code == 404
