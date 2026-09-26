from decimal import Decimal
from unittest.mock import patch
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.categories.models import Category
from app.modules.products.models import Product, ListingType, ProductStatus
from app.modules.users.models import User, UserStatus, UserRole, UserAuthIdentity
from app.modules.favorites.models import Favorite


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> Category:
    cat = Category(name="Giáo Trình", slug="giao-trinh", is_deleted=False)
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def user_a(db_session: AsyncSession) -> User:
    user = User(
        email="usera@ptit.edu.vn",
        full_name="User A",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_usera",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    user = User(
        email="userb@ptit.edu.vn",
        full_name="User B",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_userb",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def banned_user(db_session: AsyncSession) -> User:
    user = User(
        email="banned@ptit.edu.vn",
        full_name="Banned User",
        role=UserRole.STUDENT.value,
        status=UserStatus.BANNED,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_banned",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def inactive_user(db_session: AsyncSession) -> User:
    user = User(
        email="inactive@ptit.edu.vn",
        full_name="Inactive User",
        role=UserRole.STUDENT.value,
        status=UserStatus.INACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="uid_inactive",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def available_product(
    db_session: AsyncSession, user_a: User, sample_category: Category
) -> Product:
    prod = Product(
        seller_id=user_a.user_id,
        category_id=sample_category.category_id,
        title="Sách Giải tích 1",
        description="Sách mới 99%",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal(50000),
        stock=7,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


def auth_patch(user: User):
    uid_map = {
        "usera@ptit.edu.vn": "uid_usera",
        "userb@ptit.edu.vn": "uid_userb",
        "banned@ptit.edu.vn": "uid_banned",
        "inactive@ptit.edu.vn": "uid_inactive",
    }
    return patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": uid_map.get(user.email, f"uid_{user.email}"),
            "email": user.email,
            "name": user.full_name,
        },
    )


# 1. AVAILABLE product favorite -> 204
@pytest.mark.asyncio
async def test_favorite_available_product_success(
    test_client: AsyncClient, user_b: User, available_product: Product
):
    with auth_patch(user_b):
        res = await test_client.post(
            f"/api/v1/favorites/{available_product.product_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 204


# 2. Duplicate favorite -> 204 (idempotent)
@pytest.mark.asyncio
async def test_duplicate_favorite_idempotent(
    test_client: AsyncClient, user_b: User, available_product: Product
):
    with auth_patch(user_b):
        res1 = await test_client.post(
            f"/api/v1/favorites/{available_product.product_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert res1.status_code == 204

        res2 = await test_client.post(
            f"/api/v1/favorites/{available_product.product_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert res2.status_code == 204


# 3. Missing auth -> 401
@pytest.mark.asyncio
async def test_favorite_missing_auth(
    test_client: AsyncClient, available_product: Product
):
    res = await test_client.post(f"/api/v1/favorites/{available_product.product_id}")
    assert res.status_code == 401


# 4. BANNED/INACTIVE user -> 403
@pytest.mark.asyncio
async def test_favorite_banned_inactive_user(
    test_client: AsyncClient,
    banned_user: User,
    inactive_user: User,
    available_product: Product,
):
    with auth_patch(banned_user):
        res = await test_client.post(
            f"/api/v1/favorites/{available_product.product_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 403

    with auth_patch(inactive_user):
        res = await test_client.post(
            f"/api/v1/favorites/{available_product.product_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 403


# 5. Nonexistent product -> 404
@pytest.mark.asyncio
async def test_favorite_nonexistent_product(
    test_client: AsyncClient, user_b: User
):
    with auth_patch(user_b):
        res = await test_client.post(
            "/api/v1/favorites/999999",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 404


# 6. HIDDEN product -> 404
@pytest.mark.asyncio
async def test_favorite_hidden_product(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=user_a.user_id,
        category_id=sample_category.category_id,
        title="Sách ẩn",
        price=Decimal(20000),
        status=ProductStatus.HIDDEN.value,
        approval_status="APPROVED",
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()

    with auth_patch(user_b):
        res = await test_client.post(
            f"/api/v1/favorites/{prod.product_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 404


# 7. SOLD_OUT product -> 404
@pytest.mark.asyncio
async def test_favorite_sold_out_product(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=user_a.user_id,
        category_id=sample_category.category_id,
        title="Sách hết hàng",
        price=Decimal(20000),
        stock=0,
        status=ProductStatus.SOLD_OUT.value,
        approval_status="APPROVED",
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()

    with auth_patch(user_b):
        res = await test_client.post(
            f"/api/v1/favorites/{prod.product_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 404


# 8. Soft-deleted product -> 404
@pytest.mark.asyncio
async def test_favorite_soft_deleted_product(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=user_a.user_id,
        category_id=sample_category.category_id,
        title="Sách đã xóa mềm",
        price=Decimal(20000),
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        is_deleted=True,
    )
    db_session.add(prod)
    await db_session.flush()

    with auth_patch(user_b):
        res = await test_client.post(
            f"/api/v1/favorites/{prod.product_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 404


# 9. Seller can favorite own product -> 204
@pytest.mark.asyncio
async def test_seller_can_favorite_own_product(
    test_client: AsyncClient, user_a: User, available_product: Product
):
    with auth_patch(user_a):
        res = await test_client.post(
            f"/api/v1/favorites/{available_product.product_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 204


# 10. Unfavorite existing -> 204
@pytest.mark.asyncio
async def test_unfavorite_existing(
    test_client: AsyncClient, user_b: User, available_product: Product
):
    with auth_patch(user_b):
        # Favorite first
        await test_client.post(
            f"/api/v1/favorites/{available_product.product_id}",
            headers={"Authorization": "Bearer token"},
        )
        # Then unfavorite
        res = await test_client.delete(
            f"/api/v1/favorites/{available_product.product_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 204


# 11. Unfavorite non-existing -> 204 (idempotent)
@pytest.mark.asyncio
async def test_unfavorite_non_existing_idempotent(
    test_client: AsyncClient, user_b: User, available_product: Product
):
    with auth_patch(user_b):
        res = await test_client.delete(
            f"/api/v1/favorites/{available_product.product_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 204


# 12. Unfavorite still works even if product becomes unavailable later
@pytest.mark.asyncio
async def test_unfavorite_when_product_becomes_unavailable(
    test_client: AsyncClient,
    user_b: User,
    available_product: Product,
    db_session: AsyncSession,
):
    with auth_patch(user_b):
        # Favorite when available
        await test_client.post(
            f"/api/v1/favorites/{available_product.product_id}",
            headers={"Authorization": "Bearer token"},
        )

        # Product later changes to HIDDEN and is_deleted=True
        available_product.status = ProductStatus.HIDDEN.value
        available_product.is_deleted = True
        await db_session.flush()

        # Unfavorite must still succeed with 204
        res = await test_client.delete(
            f"/api/v1/favorites/{available_product.product_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 204


# 13. User A cannot affect User B's favorite
@pytest.mark.asyncio
async def test_user_a_cannot_affect_user_b_favorite(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    available_product: Product,
):
    with auth_patch(user_a):
        await test_client.post(
            f"/api/v1/favorites/{available_product.product_id}",
            headers={"Authorization": "Bearer token"},
        )

    with auth_patch(user_b):
        await test_client.post(
            f"/api/v1/favorites/{available_product.product_id}",
            headers={"Authorization": "Bearer token"},
        )
        # User B unfavorites
        await test_client.delete(
            f"/api/v1/favorites/{available_product.product_id}",
            headers={"Authorization": "Bearer token"},
        )

    # User A's favorite must still exist
    with auth_patch(user_a):
        res = await test_client.get(
            "/api/v1/favorites",
            headers={"Authorization": "Bearer token"},
        )
        data = res.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["product_id"] == available_product.product_id


# 14. GET favorites only returns current user's records
@pytest.mark.asyncio
async def test_get_favorites_user_isolation(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    available_product: Product,
):
    with auth_patch(user_a):
        await test_client.post(
            f"/api/v1/favorites/{available_product.product_id}",
            headers={"Authorization": "Bearer token"},
        )

    with auth_patch(user_b):
        res = await test_client.get(
            "/api/v1/favorites",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 200
        assert len(res.json()["items"]) == 0


# 15. GET favorites excludes HIDDEN
# 16. GET favorites excludes SOLD_OUT
# 17. GET favorites excludes soft-deleted
@pytest.mark.asyncio
async def test_get_favorites_excludes_unavailable(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    # Create 4 products: 1 normal, 1 will be hidden, 1 will be sold out, 1 will be deleted
    p1 = Product(
        seller_id=user_a.user_id,
        category_id=sample_category.category_id,
        title="P1 Available",
        price=Decimal(10000),
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        is_deleted=False,
    )
    p2 = Product(
        seller_id=user_a.user_id,
        category_id=sample_category.category_id,
        title="P2 Hidden",
        price=Decimal(20000),
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        is_deleted=False,
    )
    p3 = Product(
        seller_id=user_a.user_id,
        category_id=sample_category.category_id,
        title="P3 Sold Out",
        price=Decimal(30000),
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        is_deleted=False,
    )
    p4 = Product(
        seller_id=user_a.user_id,
        category_id=sample_category.category_id,
        title="P4 Deleted",
        price=Decimal(40000),
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        is_deleted=False,
    )
    db_session.add_all([p1, p2, p3, p4])
    await db_session.flush()

    with auth_patch(user_b):
        # Favorite all 4
        for p in [p1, p2, p3, p4]:
            await test_client.post(
                f"/api/v1/favorites/{p.product_id}",
                headers={"Authorization": "Bearer token"},
            )

        # Now change statuses
        p2.status = ProductStatus.HIDDEN.value
        p3.status = ProductStatus.SOLD_OUT.value
        p4.is_deleted = True
        await db_session.flush()

        res = await test_client.get(
            "/api/v1/favorites",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) == 1
        assert items[0]["product_id"] == p1.product_id


# 18. GET favorites IDs follows exact same visibility policy
@pytest.mark.asyncio
async def test_get_favorite_ids_visibility_policy(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    p1 = Product(
        seller_id=user_a.user_id,
        category_id=sample_category.category_id,
        title="P1 Available",
        price=Decimal(10000),
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        is_deleted=False,
    )
    p2 = Product(
        seller_id=user_a.user_id,
        category_id=sample_category.category_id,
        title="P2 Sold Out",
        price=Decimal(20000),
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        is_deleted=False,
    )
    db_session.add_all([p1, p2])
    await db_session.flush()

    with auth_patch(user_b):
        await test_client.post(
            f"/api/v1/favorites/{p1.product_id}",
            headers={"Authorization": "Bearer token"},
        )
        await test_client.post(
            f"/api/v1/favorites/{p2.product_id}",
            headers={"Authorization": "Bearer token"},
        )

        # P2 becomes sold out
        p2.status = ProductStatus.SOLD_OUT.value
        await db_session.flush()

        res = await test_client.get(
            "/api/v1/favorites/ids",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["product_ids"] == [p1.product_id]


# 19. /favorites/ids static route does not collide with product_id route
@pytest.mark.asyncio
async def test_favorites_ids_route_collision_safety(
    test_client: AsyncClient, user_b: User
):
    with auth_patch(user_b):
        res = await test_client.get(
            "/api/v1/favorites/ids",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 200
        assert "product_ids" in res.json()


# 20. Pagination cursor remains stable
@pytest.mark.asyncio
async def test_favorites_pagination(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    # Create 3 products
    products = []
    for i in range(3):
        p = Product(
            seller_id=user_a.user_id,
            category_id=sample_category.category_id,
            title=f"Book {i+1}",
            price=Decimal(10000 * (i + 1)),
            status=ProductStatus.AVAILABLE.value,
            approval_status="APPROVED",
            is_deleted=False,
        )
        db_session.add(p)
        products.append(p)
    await db_session.flush()

    with auth_patch(user_b):
        for p in products:
            await test_client.post(
                f"/api/v1/favorites/{p.product_id}",
                headers={"Authorization": "Bearer token"},
            )

        # Fetch page 1 with limit=2
        res1 = await test_client.get(
            "/api/v1/favorites?limit=2",
            headers={"Authorization": "Bearer token"},
        )
        assert res1.status_code == 200
        data1 = res1.json()
        assert len(data1["items"]) == 2
        assert data1["has_more"] is True
        assert data1["next_cursor"] is not None

        # Fetch page 2 with cursor
        res2 = await test_client.get(
            f"/api/v1/favorites?limit=2&cursor={data1['next_cursor']}",
            headers={"Authorization": "Bearer token"},
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert len(data2["items"]) == 1
        assert data2["has_more"] is False

        # IDs between pages must be distinct
        ids1 = {it["product_id"] for it in data1["items"]}
        ids2 = {it["product_id"] for it in data2["items"]}
        assert ids1.isdisjoint(ids2)


# 21. Partial purchase / stock reduction (7 -> 3) keeps favorite
@pytest.mark.asyncio
async def test_stock_reduction_keeps_favorite(
    test_client: AsyncClient,
    user_b: User,
    available_product: Product,
    db_session: AsyncSession,
):
    with auth_patch(user_b):
        await test_client.post(
            f"/api/v1/favorites/{available_product.product_id}",
            headers={"Authorization": "Bearer token"},
        )

        # Simulate stock reduction (e.g. from 7 to 3)
        available_product.stock = 3
        await db_session.flush()

        # Favorite must still be visible and available_stock=3
        res = await test_client.get(
            "/api/v1/favorites",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) == 1
        assert items[0]["product_id"] == available_product.product_id
        assert items[0]["available_stock"] == 3
        assert "view_count" in items[0]
        assert isinstance(items[0]["view_count"], int)


@pytest.mark.asyncio
async def test_favorites_serializes_view_count(
    test_client: AsyncClient,
    user_b: User,
    available_product: Product,
):
    """Proves GET /api/v1/favorites explicitly serializes view_count for FavoriteProductResponse."""
    with auth_patch(user_b):
        await test_client.post(
            f"/api/v1/favorites/{available_product.product_id}",
            headers={"Authorization": "Bearer token"},
        )

        res = await test_client.get(
            "/api/v1/favorites",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) == 1
        assert items[0]["view_count"] == available_product.view_count
        assert isinstance(items[0]["view_count"], int)
