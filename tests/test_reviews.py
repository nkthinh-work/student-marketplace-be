from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.core.config import settings
from app.core.redis import get_or_reconnect_redis
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.categories.models import Category
from app.modules.orders.models import (
    FulfillmentMethod,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from app.modules.products.models import ListingType, Product, ProductStatus
from app.modules.reviews.models import Review
from app.modules.users.models import User, UserRole, UserStatus


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
async def seller_user(db_session: AsyncSession) -> User:
    user = User(
        email="seller_ptit_rev@ptit.edu.vn",
        full_name="Nguyễn Khắc Thịnh",
        phone="0352866196",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def buyer_user(db_session: AsyncSession) -> User:
    user = User(
        email="buyer_ptit_rev@ptit.edu.vn",
        full_name="Trần Minh Anh",
        phone="0987654321",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def buyer_user_2(db_session: AsyncSession) -> User:
    user = User(
        email="buyer2_ptit_rev@ptit.edu.vn",
        full_name="Lê Hoàng Nam",
        phone="0911223344",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def unrelated_user(db_session: AsyncSession) -> User:
    user = User(
        email="unrelated_ptit_rev@ptit.edu.vn",
        full_name="Phạm Gia Huy",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def test_category(db_session: AsyncSession) -> Category:
    cat = Category(name="Giáo trình & Sách", slug="giao-trinh-sach-test-rev")
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def test_product(
    db_session: AsyncSession, seller_user: User, test_category: Category
) -> Product:
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=test_category.category_id,
        title="Giáo trình Cấu trúc dữ liệu",
        description="Sách đẹp 99%",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal("50000"),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        view_count=0,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


@pytest_asyncio.fixture
async def completed_order(
    db_session: AsyncSession, seller_user: User, buyer_user: User, test_product: Product
) -> Order:
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    order = Order(
        order_code="REV-COMPL-001",
        buyer_id=buyer_user.user_id,
        seller_id=seller_user.user_id,
        status=OrderStatus.COMPLETED.value,
        total_amount=Decimal("50000"),
        payment_method=PaymentMethod.CASH_ON_MEETUP.value,
        payment_status=PaymentStatus.PAID.value,
        paid_confirmed_at=now_naive,
        fulfillment_method=FulfillmentMethod.MEETUP.value,
        meetup_place="Cổng trường PTIT",
        contact_name="Trần Minh Anh",
        contact_phone="0987654321",
        completed_at=now_naive,
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.order_id,
        product_id=test_product.product_id,
        product_title=test_product.title,
        price_at_purchase=test_product.price,
        quantity=1,
    )
    db_session.add(item)
    await db_session.flush()
    return order


@pytest_asyncio.fixture
async def completed_order_2(
    db_session: AsyncSession, seller_user: User, buyer_user_2: User, test_product: Product
) -> Order:
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    order = Order(
        order_code="REV-COMPL-002",
        buyer_id=buyer_user_2.user_id,
        seller_id=seller_user.user_id,
        status=OrderStatus.COMPLETED.value,
        total_amount=Decimal("50000"),
        payment_method=PaymentMethod.CASH_ON_MEETUP.value,
        payment_status=PaymentStatus.PAID.value,
        paid_confirmed_at=now_naive,
        fulfillment_method=FulfillmentMethod.MEETUP.value,
        meetup_place="Căn tin A2 PTIT",
        contact_name="Lê Hoàng Nam",
        contact_phone="0911223344",
        completed_at=now_naive,
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.order_id,
        product_id=test_product.product_id,
        product_title=test_product.title,
        price_at_purchase=test_product.price,
        quantity=1,
    )
    db_session.add(item)
    await db_session.flush()
    return order


@pytest.mark.asyncio
async def test_create_review_success_on_completed_order(
    test_client: AsyncClient, buyer_user: User, completed_order: Order
):
    with auth_patch(buyer_user):
        resp = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={
                "rating": 5,
                "comment": "Người bán thân thiện, giao dịch nhanh chóng!",
            },
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["order_id"] == completed_order.order_id
    assert data["rating"] == 5
    assert data["comment"] == "Người bán thân thiện, giao dịch nhanh chóng!"
    assert data["reviewer_id"] == buyer_user.user_id
    assert data["reviewer_name"] == buyer_user.full_name


@pytest.mark.asyncio
async def test_create_review_ratings_validation(
    test_client: AsyncClient, buyer_user: User, completed_order: Order
):
    # Rating 0 -> rejected 422
    with auth_patch(buyer_user):
        r0 = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 0},
        )
    assert r0.status_code == 422

    # Rating 6 -> rejected 422
    with auth_patch(buyer_user):
        r6 = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 6},
        )
    assert r6.status_code == 422

    # Missing rating -> rejected 422
    with auth_patch(buyer_user):
        rmiss = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"comment": "Không có sao"},
        )
    assert rmiss.status_code == 422


@pytest.mark.asyncio
async def test_create_review_comment_normalization_and_length(
    test_client: AsyncClient, buyer_user: User, completed_order: Order
):
    # Whitespace-only comment normalized to None
    with auth_patch(buyer_user):
        resp = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 4, "comment": "   \n  \t  "},
        )
    assert resp.status_code == 201
    assert resp.json()["comment"] is None

    # Comment > 1000 characters -> 422
    with auth_patch(buyer_user):
        resp_long = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 4, "comment": "a" * 1001},
        )
    assert resp_long.status_code == 422


@pytest.mark.asyncio
async def test_create_review_eligibility_status_guards(
    test_client: AsyncClient, db_session: AsyncSession, buyer_user: User, completed_order: Order
):
    # Non-COMPLETED order rejects review with 400
    for st in [OrderStatus.PENDING, OrderStatus.CONFIRMED, OrderStatus.DELIVERING, OrderStatus.CANCELLED]:
        completed_order.status = st.value
        await db_session.flush()

        with auth_patch(buyer_user):
            resp = await test_client.post(
                f"/api/v1/orders/{completed_order.order_id}/review",
                json={"rating": 5},
            )
        assert resp.status_code == 400
        assert "Chỉ có thể đánh giá sau khi đơn hàng hoàn tất" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_review_authorization_guards(
    test_client: AsyncClient,
    seller_user: User,
    unrelated_user: User,
    completed_order: Order,
):
    # Unauthenticated -> 401
    r_unauth = await test_client.post(
        f"/api/v1/orders/{completed_order.order_id}/review",
        json={"rating": 5},
    )
    assert r_unauth.status_code == 401

    # Unrelated user -> 404
    with auth_patch(unrelated_user):
        r_unrel = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5},
        )
    assert r_unrel.status_code == 404

    # Seller attempts to review -> 403
    with auth_patch(seller_user):
        r_seller = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5},
        )
    assert r_seller.status_code == 403
    assert "Chỉ người mua mới có thể đánh giá người bán" in r_seller.json()["detail"]


@pytest.mark.asyncio
async def test_create_review_duplicate_prevention(
    test_client: AsyncClient, buyer_user: User, completed_order: Order
):
    with auth_patch(buyer_user):
        r1 = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5, "comment": "Đánh giá lần 1"},
        )
        assert r1.status_code == 201

        # Second attempt -> 409 Conflict
        r2 = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 4, "comment": "Đánh giá lần 2"},
        )
        assert r2.status_code == 409
        assert "Bạn đã đánh giá đơn hàng này" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_patch_review_semantics(
    test_client: AsyncClient, buyer_user: User, completed_order: Order
):
    # 1. Create initial review
    with auth_patch(buyer_user):
        await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5, "comment": "Ban đầu rất tốt"},
        )

    # 2. PATCH {} -> 422 rejected
    with auth_patch(buyer_user):
        r_empty = await test_client.patch(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={},
        )
    assert r_empty.status_code == 422

    # 3. PATCH {"rating": null} -> 422 rejected
    with auth_patch(buyer_user):
        r_null_rating = await test_client.patch(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": None},
        )
    assert r_null_rating.status_code == 422

    # 4. PATCH {"rating": 4} -> preserves existing comment
    with auth_patch(buyer_user):
        r_rating = await test_client.patch(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 4},
        )
    assert r_rating.status_code == 200
    assert r_rating.json()["rating"] == 4
    assert r_rating.json()["comment"] == "Ban đầu rất tốt"

    # 5. PATCH {"comment": "Cập nhật lại"} -> preserves existing rating 4
    with auth_patch(buyer_user):
        r_comment = await test_client.patch(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"comment": "Cập nhật lại"},
        )
    assert r_comment.status_code == 200
    assert r_comment.json()["rating"] == 4
    assert r_comment.json()["comment"] == "Cập nhật lại"

    # 6. PATCH {"comment": null} -> clears comment
    with auth_patch(buyer_user):
        r_clear = await test_client.patch(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"comment": None},
        )
    assert r_clear.status_code == 200
    assert r_clear.json()["rating"] == 4
    assert r_clear.json()["comment"] is None


@pytest.mark.asyncio
async def test_patch_review_authorization(
    test_client: AsyncClient,
    seller_user: User,
    unrelated_user: User,
    buyer_user: User,
    completed_order: Order,
):
    # Create review by buyer
    with auth_patch(buyer_user):
        await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5},
        )

    # Seller attempts to edit -> 404
    with auth_patch(seller_user):
        r_seller = await test_client.patch(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 3},
        )
    assert r_seller.status_code == 404

    # Unrelated user attempts to edit -> 404
    with auth_patch(unrelated_user):
        r_unrel = await test_client.patch(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 3},
        )
    assert r_unrel.status_code == 404


@pytest.mark.asyncio
async def test_get_order_review_semantics(
    test_client: AsyncClient,
    seller_user: User,
    buyer_user: User,
    unrelated_user: User,
    completed_order: Order,
):
    # Before review created: buyer gets 200 with null body
    with auth_patch(buyer_user):
        r_buyer_pre = await test_client.get(f"/api/v1/orders/{completed_order.order_id}/review")
    assert r_buyer_pre.status_code == 200
    assert r_buyer_pre.json() is None

    # Before review created: seller gets 200 with null body
    with auth_patch(seller_user):
        r_seller_pre = await test_client.get(f"/api/v1/orders/{completed_order.order_id}/review")
    assert r_seller_pre.status_code == 200
    assert r_seller_pre.json() is None

    # Unrelated user gets 404
    with auth_patch(unrelated_user):
        r_unrel = await test_client.get(f"/api/v1/orders/{completed_order.order_id}/review")
    assert r_unrel.status_code == 404

    # Buyer creates review
    with auth_patch(buyer_user):
        await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5, "comment": "Hàng đẹp lắm"},
        )

    # After review: buyer gets review
    with auth_patch(buyer_user):
        r_buyer_post = await test_client.get(f"/api/v1/orders/{completed_order.order_id}/review")
    assert r_buyer_post.status_code == 200
    assert r_buyer_post.json()["rating"] == 5
    assert r_buyer_post.json()["comment"] == "Hàng đẹp lắm"

    # After review: seller gets review
    with auth_patch(seller_user):
        r_seller_post = await test_client.get(f"/api/v1/orders/{completed_order.order_id}/review")
    assert r_seller_post.status_code == 200
    assert r_seller_post.json()["rating"] == 5


@pytest.mark.asyncio
async def test_public_seller_reviews_keyset_and_privacy(
    test_client: AsyncClient,
    seller_user: User,
    buyer_user: User,
    buyer_user_2: User,
    completed_order: Order,
    completed_order_2: Order,
):
    # Buyer 1 reviews (5 stars)
    with auth_patch(buyer_user):
        await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5, "comment": "Giao dịch nhanh"},
        )

    # Buyer 2 reviews (4 stars)
    with auth_patch(buyer_user_2):
        await test_client.post(
            f"/api/v1/orders/{completed_order_2.order_id}/review",
            json={"rating": 4, "comment": "Rất ổn"},
        )

    # Public fetch (page limit=1)
    resp = await test_client.get(f"/api/v1/users/{seller_user.public_id}/reviews?limit=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["has_more"] is True
    assert data["next_cursor"] is not None

    # Privacy checks on public review item
    item1 = data["items"][0]
    assert item1["rating"] == 4
    assert item1["verified_transaction"] is True
    assert "reviewer_display" not in item1
    assert "reviewer_name" not in item1
    assert "buyer_name" not in item1
    assert "order_id" not in item1
    assert "order_code" not in item1
    assert "reviewer_id" not in item1
    assert "buyer_id" not in item1
    assert "product_id" not in item1
    assert "product_title" not in item1
    assert "phone" not in item1
    assert "email" not in item1
    assert "address" not in item1

    # Fetch next page using cursor
    resp2 = await test_client.get(
        f"/api/v1/users/{seller_user.public_id}/reviews?limit=1&cursor={data['next_cursor']}"
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["items"]) == 1
    assert data2["items"][0]["rating"] == 5
    assert data2["items"][0]["verified_transaction"] is True
    assert "reviewer_display" not in data2["items"][0]
    assert data2["has_more"] is False


@pytest.mark.asyncio
async def test_public_profile_rating_aggregation(
    test_client: AsyncClient,
    seller_user: User,
    buyer_user: User,
    buyer_user_2: User,
    completed_order: Order,
    completed_order_2: Order,
):
    # 0 reviews -> rating_average is None, review_count is 0
    resp_init = await test_client.get(f"/api/v1/users/{seller_user.public_id}")
    assert resp_init.status_code == 200
    assert resp_init.json()["rating_average"] is None
    assert resp_init.json()["review_count"] == 0

    # 1 review (5 stars) -> 5.0, 1
    with auth_patch(buyer_user):
        await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5},
        )
    resp_1 = await test_client.get(f"/api/v1/users/{seller_user.public_id}")
    assert resp_1.status_code == 200
    assert resp_1.json()["rating_average"] == 5.0
    assert resp_1.json()["review_count"] == 1

    # 2nd review (4 stars) -> 4.5, 2
    with auth_patch(buyer_user_2):
        await test_client.post(
            f"/api/v1/orders/{completed_order_2.order_id}/review",
            json={"rating": 4},
        )
    resp_2 = await test_client.get(f"/api/v1/users/{seller_user.public_id}")
    assert resp_2.status_code == 200
    assert resp_2.json()["rating_average"] == 4.5
    assert resp_2.json()["review_count"] == 2


@pytest.mark.asyncio
async def test_product_detail_seller_reputation(
    test_client: AsyncClient,
    seller_user: User,
    buyer_user: User,
    test_product: Product,
    completed_order: Order,
):
    with auth_patch(buyer_user):
        await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5},
        )

    resp = await test_client.get(f"/api/v1/products/{test_product.product_id}")
    assert resp.status_code == 200
    seller_data = resp.json()["seller"]
    assert seller_data["rating_average"] == 5.0
    assert seller_data["review_count"] == 1


@pytest.mark.asyncio
async def test_sold_products_contextual_review_enrichment_and_privacy(
    test_client: AsyncClient,
    seller_user: User,
    buyer_user: User,
    buyer_user_2: User,
    completed_order: Order,
    completed_order_2: Order,
):
    # 1. Before reviews are posted: sold products has review_count = 0, rating_average = None, recent_reviews = []
    res_pre = await test_client.get(f"/api/v1/users/{seller_user.public_id}/sold-products")
    assert res_pre.status_code == 200
    data_pre = res_pre.json()
    assert len(data_pre["items"]) == 1
    sold_item_pre = data_pre["items"][0]
    assert sold_item_pre["total_sold_quantity"] == 2
    assert sold_item_pre["review_count"] == 0
    assert sold_item_pre["rating_average"] is None
    assert sold_item_pre["recent_reviews"] == []

    # 2. Buyer 1 posts a 5-star review
    with auth_patch(buyer_user):
        await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5, "comment": "Giao dịch nhanh, sách rất mới"},
        )

    res_1 = await test_client.get(f"/api/v1/users/{seller_user.public_id}/sold-products")
    assert res_1.status_code == 200
    sold_item_1 = res_1.json()["items"][0]
    assert sold_item_1["review_count"] == 1
    assert sold_item_1["rating_average"] == 5.0
    assert len(sold_item_1["recent_reviews"]) == 1
    r1 = sold_item_1["recent_reviews"][0]
    assert r1["rating"] == 5
    assert r1["comment"] == "Giao dịch nhanh, sách rất mới"
    assert r1["verified_transaction"] is True
    # Privacy verification on sold-history review item
    assert "reviewer_display" not in r1
    assert "reviewer_id" not in r1
    assert "buyer_id" not in r1
    assert "order_id" not in r1
    assert "order_code" not in r1
    assert "phone" not in r1
    assert "email" not in r1
    assert "address" not in r1

    # 3. Buyer 2 posts a 3-star review
    with auth_patch(buyer_user_2):
        await test_client.post(
            f"/api/v1/orders/{completed_order_2.order_id}/review",
            json={"rating": 3, "comment": "Giao dịch ổn"},
        )

    res_2 = await test_client.get(f"/api/v1/users/{seller_user.public_id}/sold-products")
    assert res_2.status_code == 200
    sold_item_2 = res_2.json()["items"][0]
    assert sold_item_2["review_count"] == 2
    assert sold_item_2["rating_average"] == 4.0
    assert len(sold_item_2["recent_reviews"]) == 2
    # Bounded list contains recent reviews (latest first)
    assert sold_item_2["recent_reviews"][0]["rating"] == 3
    assert sold_item_2["recent_reviews"][1]["rating"] == 5


@pytest.mark.asyncio
async def test_get_public_seller_reviews_contract_and_rate_limiting(
    db_session: AsyncSession,
    seller_user: User,
    buyer_user: User,
    completed_order: Order,
):
    """
    Finding-01:
    - GET /api/v1/users/{user_id}/reviews remains public (no auth required)
    - Response matches PublicSellerReviewsCursorPage contract
    - Rate limit matches Class C user profile policy (below quota -> 200, above quota -> 429)
    - Retry-After header returned on 429
    - No internal role or sensitive data leaked in public reviews
    """
    from app.core.database import get_db

    app.dependency_overrides[get_db] = lambda: db_session

    from app.core.redis import init_redis

    client = await init_redis()
    test_ip = "198.51.100.42"
    key = f"rl:user_profile:ip:{test_ip}"
    if client is not None:
        await client.delete(key)

    headers = {"x-real-ip": test_ip}

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            # 1. Post a review first (authenticated buyer)
            with auth_patch(buyer_user):
                await ac.post(
                    f"/api/v1/orders/{completed_order.order_id}/review",
                    json={"rating": 5, "comment": "Người bán uy tín, giao dịch nhanh!"},
                )

            with patch.object(settings, "RATE_LIMIT_USER_PROFILE_LIMIT", 2):
                # Request 1: Below quota -> 200 OK (unauthenticated public access)
                res1 = await ac.get(
                    f"/api/v1/users/{seller_user.public_id}/reviews",
                    headers=headers,
                )
                assert res1.status_code == 200
                data1 = res1.json()
                assert "items" in data1
                assert "next_cursor" in data1
                assert "has_more" in data1
                assert len(data1["items"]) == 1
                review_item = data1["items"][0]
                assert review_item["rating"] == 5
                assert review_item["comment"] == "Người bán uy tín, giao dịch nhanh!"
                assert review_item["verified_transaction"] is True
                # Strict Privacy: PublicSellerReviewItem does not expose reviewer identity or internal metadata
                assert "reviewer_name" not in review_item
                assert "reviewer_id" not in review_item
                assert "email" not in review_item
                assert "phone" not in review_item
                assert "role" not in review_item

                # Request 2: Boundary -> 200 OK
                res2 = await ac.get(
                    f"/api/v1/users/{seller_user.public_id}/reviews",
                    headers=headers,
                )
                assert res2.status_code == 200

                # Request 3: Exceeded -> 429 Too Many Requests
                res3 = await ac.get(
                    f"/api/v1/users/{seller_user.public_id}/reviews",
                    headers=headers,
                )
                assert res3.status_code == 429
                assert "Retry-After" in res3.headers
                assert res3.json() == {"detail": "Too many requests. Please try again later."}
    finally:
        app.dependency_overrides.clear()
        if client is not None:
            await client.delete(key)
