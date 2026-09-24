from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.main import app
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.categories.models import Category
from app.modules.notifications.models import Notification, NotificationType
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
from app.modules.users.models import User, UserAuthIdentity, UserRole, UserStatus


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
        email=f"seller_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Nguyễn Văn Bán",
        phone="0352866196",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid=f"uid_seller_{user.user_id}",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def buyer_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"buyer_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Trần Minh Mua",
        phone="0987654321",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid=f"uid_buyer_{user.user_id}",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def unrelated_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"unrelated_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Phạm Gia Huy",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def test_category(db_session: AsyncSession) -> Category:
    cat = Category(name=f"Sách {uuid4().hex[:4]}", slug=f"sach-{uuid4().hex[:6]}")
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
        title="Giáo trình Mạng máy tính",
        description="Sách học kỳ 1",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal("65000"),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
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
        order_code=f"ORD-REV-{uuid4().hex[:6].upper()}",
        buyer_id=buyer_user.user_id,
        seller_id=seller_user.user_id,
        status=OrderStatus.COMPLETED.value,
        total_amount=Decimal("65000"),
        payment_method=PaymentMethod.CASH_ON_MEETUP.value,
        payment_status=PaymentStatus.PAID.value,
        paid_confirmed_at=now_naive,
        fulfillment_method=FulfillmentMethod.MEETUP.value,
        meetup_place="Cổng trường PTIT",
        contact_name="Trần Minh Mua",
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
    await db_session.commit()
    return order


# ============================================================================
# 1. CORE FUNCTIONAL & NOTIFICATION PERSISTENCE TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_create_review_creates_single_new_review_notification(
    test_client: AsyncClient,
    db_session: AsyncSession,
    buyer_user: User,
    seller_user: User,
    completed_order: Order,
):
    """
    Valid COMPLETED order review:
    - Review persists.
    - Seller/reviewee gets exactly one NEW_REVIEW notification.
    - Review.reviewee_id == Notification.user_id.
    """
    with auth_patch(buyer_user):
        resp = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={
                "rating": 5,
                "comment": "Giao dịch rất tốt, sản phẩm chuẩn như mô tả.",
            },
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["rating"] == 5
    assert data["comment"] == "Giao dịch rất tốt, sản phẩm chuẩn như mô tả."
    assert data["order_id"] == completed_order.order_id
    assert data["reviewer_id"] == buyer_user.user_id
    assert data["reviewee_id"] == seller_user.user_id

    # Verify Review row in DB
    rev_res = await db_session.execute(
        select(Review).where(Review.order_id == completed_order.order_id)
    )
    persisted_review = rev_res.scalar_one_or_none()
    assert persisted_review is not None
    assert persisted_review.rating == 5
    assert persisted_review.reviewee_id == seller_user.user_id

    # Verify exactly 1 notification for seller
    notif_res = await db_session.execute(
        select(Notification).where(
            Notification.ref_type == "ORDER",
            Notification.ref_id == completed_order.order_id,
        )
    )
    notifs = notif_res.scalars().all()
    assert len(notifs) == 1
    notif = notifs[0]

    assert notif.type == NotificationType.NEW_REVIEW.value
    assert notif.user_id == seller_user.user_id
    assert notif.user_id == persisted_review.reviewee_id
    assert notif.is_read is False


@pytest.mark.asyncio
async def test_notification_attributes_and_exact_privacy_copy(
    test_client: AsyncClient,
    db_session: AsyncSession,
    buyer_user: User,
    seller_user: User,
    completed_order: Order,
):
    """
    Verify notification attributes:
    - type == NEW_REVIEW
    - ref_type == ORDER
    - ref_id == order_id
    - user_id == review.reviewee_id
    - is_read == False
    - exact title and body format using canonical persisted rating
    - review comment is NOT leaked in notification body
    - sensitive buyer attributes (phone, email, etc.) are NOT in notification body
    """
    with auth_patch(buyer_user):
        resp = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={
                "rating": 4,
                "comment": "Rất hài lòng nhưng ship hơi chậm một chút.",
            },
        )
    assert resp.status_code == 201

    notif_res = await db_session.execute(
        select(Notification).where(Notification.user_id == seller_user.user_id)
    )
    notif = notif_res.scalar_one()

    # Exact attributes
    assert notif.type == "NEW_REVIEW"
    assert notif.ref_type == "ORDER"
    assert notif.ref_id == completed_order.order_id
    assert notif.user_id == seller_user.user_id
    assert notif.is_read is False
    assert notif.title == "Bạn có đánh giá mới"
    assert notif.body == f"Đơn {completed_order.order_code} vừa nhận được đánh giá 4 sao."

    # Privacy invariants: comment and buyer details are NOT in notification body
    assert "Rất hài lòng" not in notif.body
    assert "ship hơi chậm" not in notif.body
    assert buyer_user.email not in notif.body
    assert buyer_user.phone not in notif.body
    assert buyer_user.full_name not in notif.body


@pytest.mark.asyncio
async def test_reviewer_buyer_receives_zero_self_notification(
    test_client: AsyncClient,
    db_session: AsyncSession,
    buyer_user: User,
    completed_order: Order,
):
    """Buyer does NOT receive any self-action notification."""
    with auth_patch(buyer_user):
        resp = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5, "comment": "Tốt"},
        )
    assert resp.status_code == 201

    buyer_notifs = await db_session.execute(
        select(Notification).where(Notification.user_id == buyer_user.user_id)
    )
    assert len(buyer_notifs.scalars().all()) == 0


# ============================================================================
# 2. ELIGIBILITY, AUTHORIZATION & INVALID ATTEMPTS (0 NOTIFICATIONS)
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_status",
    [OrderStatus.PENDING.value, OrderStatus.CONFIRMED.value, OrderStatus.DELIVERING.value],
)
async def test_order_not_completed_creates_zero_notifications(
    test_client: AsyncClient,
    db_session: AsyncSession,
    buyer_user: User,
    completed_order: Order,
    invalid_status: str,
):
    """Review rejected when order is not COMPLETED -> 0 notifications."""
    completed_order.status = invalid_status
    await db_session.commit()

    with auth_patch(buyer_user):
        resp = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5, "comment": "Quá sớm để đánh giá"},
        )
    assert resp.status_code == 400
    assert "Chỉ có thể đánh giá sau khi đơn hàng hoàn tất" in resp.json()["detail"]

    # Invariant: 0 review, 0 notification
    rev_cnt = await db_session.scalar(
        select(func.count(Review.review_id)).where(Review.order_id == completed_order.order_id)
    )
    assert rev_cnt == 0

    notif_cnt = await db_session.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.ref_type == "ORDER", Notification.ref_id == completed_order.order_id
        )
    )
    assert notif_cnt == 0


@pytest.mark.asyncio
async def test_seller_forbidden_review_creates_zero_notifications(
    test_client: AsyncClient,
    db_session: AsyncSession,
    seller_user: User,
    completed_order: Order,
):
    """Seller attempting to review own transaction -> 403 Forbidden, 0 notifications."""
    with auth_patch(seller_user):
        resp = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5, "comment": "Tự khen mình"},
        )
    assert resp.status_code == 403
    assert "Chỉ người mua mới có thể đánh giá người bán" in resp.json()["detail"]

    notif_cnt = await db_session.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.ref_type == "ORDER", Notification.ref_id == completed_order.order_id
        )
    )
    assert notif_cnt == 0


@pytest.mark.asyncio
async def test_outsider_forbidden_creates_zero_notifications(
    test_client: AsyncClient,
    db_session: AsyncSession,
    unrelated_user: User,
    completed_order: Order,
):
    """Unrelated user attempting to review -> 404 Not Found, 0 notifications."""
    with auth_patch(unrelated_user):
        resp = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5, "comment": "Người lạ vào đánh giá"},
        )
    assert resp.status_code == 404

    notif_cnt = await db_session.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.ref_type == "ORDER", Notification.ref_id == completed_order.order_id
        )
    )
    assert notif_cnt == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_rating", [0, 6, -1, 10])
async def test_invalid_rating_creates_zero_notifications(
    test_client: AsyncClient,
    db_session: AsyncSession,
    buyer_user: User,
    completed_order: Order,
    bad_rating: int,
):
    """Invalid rating schema validation rejection -> 422 Unprocessable, 0 notifications."""
    with auth_patch(buyer_user):
        resp = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": bad_rating, "comment": "Rating không hợp lệ"},
        )
    assert resp.status_code == 422

    notif_cnt = await db_session.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.ref_type == "ORDER", Notification.ref_id == completed_order.order_id
        )
    )
    assert notif_cnt == 0


# ============================================================================
# 3. DUPLICATE & PATCH TESTS (NO RE-NOTIFICATION)
# ============================================================================

@pytest.mark.asyncio
async def test_duplicate_post_review_creates_zero_extra_notification(
    test_client: AsyncClient,
    db_session: AsyncSession,
    buyer_user: User,
    seller_user: User,
    completed_order: Order,
):
    """
    First POST: Review created, 1 notification.
    Second POST: 409 Conflict error.
    Notification count in DB remains exactly 1.
    """
    with auth_patch(buyer_user):
        resp1 = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5, "comment": "Lần 1"},
        )
    assert resp1.status_code == 201

    notif_cnt1 = await db_session.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.user_id == seller_user.user_id
        )
    )
    assert notif_cnt1 == 1

    # Second POST
    with auth_patch(buyer_user):
        resp2 = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5, "comment": "Lần 2 trùng lặp"},
        )
    assert resp2.status_code == 409
    assert "Bạn đã đánh giá đơn hàng này" in resp2.json()["detail"]

    # Invariant: notification count remains 1
    notif_cnt2 = await db_session.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.user_id == seller_user.user_id
        )
    )
    assert notif_cnt2 == 1


@pytest.mark.asyncio
async def test_patch_review_creates_zero_new_notification(
    test_client: AsyncClient,
    db_session: AsyncSession,
    buyer_user: User,
    seller_user: User,
    completed_order: Order,
):
    """
    PATCH rating, comment, or both must NOT create any new notification.
    """
    # 1. Initial create
    with auth_patch(buyer_user):
        resp_create = await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5, "comment": "Ban đầu 5 sao"},
        )
    assert resp_create.status_code == 201

    notif_cnt_initial = await db_session.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.user_id == seller_user.user_id
        )
    )
    assert notif_cnt_initial == 1

    # 2. PATCH rating only: 5 -> 4
    with auth_patch(buyer_user):
        resp_patch_rating = await test_client.patch(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 4},
        )
    assert resp_patch_rating.status_code == 200
    assert resp_patch_rating.json()["rating"] == 4

    notif_cnt_after_rating = await db_session.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.user_id == seller_user.user_id
        )
    )
    assert notif_cnt_after_rating == 1

    # 3. PATCH comment only
    with auth_patch(buyer_user):
        resp_patch_comment = await test_client.patch(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"comment": "Chỉnh sửa nhận xét chi tiết hơn"},
        )
    assert resp_patch_comment.status_code == 200
    assert resp_patch_comment.json()["comment"] == "Chỉnh sửa nhận xét chi tiết hơn"

    notif_cnt_after_comment = await db_session.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.user_id == seller_user.user_id
        )
    )
    assert notif_cnt_after_comment == 1

    # 4. PATCH both rating and comment
    with auth_patch(buyer_user):
        resp_patch_both = await test_client.patch(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5, "comment": "Quay lại 5 sao"},
        )
    assert resp_patch_both.status_code == 200

    notif_cnt_after_both = await db_session.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.user_id == seller_user.user_id
        )
    )
    assert notif_cnt_after_both == 1


@pytest.mark.asyncio
async def test_get_order_review_creates_zero_notifications(
    test_client: AsyncClient,
    db_session: AsyncSession,
    buyer_user: User,
    seller_user: User,
    completed_order: Order,
):
    """GET review must NOT create any notification."""
    with auth_patch(buyer_user):
        await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5, "comment": "Đã đánh giá"},
        )

    # Seller reads review
    with auth_patch(seller_user):
        resp_get = await test_client.get(
            f"/api/v1/orders/{completed_order.order_id}/review"
        )
    assert resp_get.status_code == 200

    notif_cnt = await db_session.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.user_id == seller_user.user_id
        )
    )
    assert notif_cnt == 1


# ============================================================================
# 4. ATOMICITY & RACE CONDITIONS
# ============================================================================

@pytest.mark.asyncio
async def test_transaction_atomicity_on_pre_commit_failure(
    test_client: AsyncClient,
    db_session: AsyncSession,
    buyer_user: User,
    completed_order: Order,
):
    """
    Force commit failure:
    - 0 Review rows persisted.
    - 0 Notification rows persisted.
    """
    order_id = completed_order.order_id
    with patch.object(AsyncSession, "commit", side_effect=Exception("Simulated Pre-Commit Crash")):
        with auth_patch(buyer_user):
            with pytest.raises(Exception, match="Simulated Pre-Commit Crash"):
                await test_client.post(
                    f"/api/v1/orders/{order_id}/review",
                    json={"rating": 5, "comment": "Thử nghiệm atomicity"},
                )

    rev_cnt = await db_session.scalar(
        select(func.count(Review.review_id)).where(Review.order_id == order_id)
    )
    assert rev_cnt == 0

    notif_cnt = await db_session.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.ref_type == "ORDER", Notification.ref_id == order_id
        )
    )
    assert notif_cnt == 0


@pytest.mark.asyncio
async def test_concurrency_duplicate_conflict_rollback(
    test_client: AsyncClient,
    db_session: AsyncSession,
    buyer_user: User,
    completed_order: Order,
):
    """
    Simulate unique constraint violation at commit time (ux_reviews_order_reviewer).
    - Verified that IntegrityError is caught and rolls back.
    - Maps specifically to 409 Conflict.
    - No orphan notification.
    """
    order_id = completed_order.order_id
    simulated_integrity_err = IntegrityError(
        statement="INSERT INTO reviews ...",
        params={},
        orig=Exception("duplicate key value violates unique constraint 'ux_reviews_order_reviewer'"),
    )

    with patch.object(AsyncSession, "commit", side_effect=simulated_integrity_err):
        with auth_patch(buyer_user):
            resp = await test_client.post(
                f"/api/v1/orders/{order_id}/review",
                json={"rating": 5, "comment": "Race condition simulation"},
            )
        assert resp.status_code == 409
        assert "Bạn đã đánh giá đơn hàng này" in resp.json()["detail"]

    # Verify 0 orphan notifications committed
    notif_cnt = await db_session.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.ref_type == "ORDER", Notification.ref_id == order_id
        )
    )
    assert notif_cnt == 0


@pytest.mark.asyncio
async def test_unexpected_integrity_error_not_converted_to_409(
    test_client: AsyncClient,
    buyer_user: User,
    completed_order: Order,
):
    """
    An IntegrityError that is NOT ux_reviews_order_reviewer must NOT be converted to 409.
    It should be re-raised, preserving normal error handling.
    """
    order_id = completed_order.order_id
    simulated_foreign_key_err = IntegrityError(
        statement="INSERT INTO ...",
        params={},
        orig=Exception("violates foreign key constraint 'fk_unexpected_table'"),
    )

    with patch.object(AsyncSession, "commit", side_effect=simulated_foreign_key_err):
        with auth_patch(buyer_user):
            with pytest.raises(IntegrityError):
                await test_client.post(
                    f"/api/v1/orders/{order_id}/review",
                    json={"rating": 5, "comment": "Unexpected error simulation"},
                )


# ============================================================================
# 5. REALTIME TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_realtime_event_dispatched_post_commit_to_seller(
    test_client: AsyncClient,
    buyer_user: User,
    seller_user: User,
    completed_order: Order,
):
    """
    NOTIFICATION_CREATED only dispatched post-commit with correct user_id and payload.
    Verifies that AsyncSession.commit completes BEFORE publish_user_event is called.
    """
    order_id = completed_order.order_id
    order_code = completed_order.order_code
    seller_id = seller_user.user_id

    call_sequence = []
    original_commit = AsyncSession.commit

    async def tracking_commit(self, *args, **kwargs):
        call_sequence.append("commit")
        return await original_commit(self, *args, **kwargs)

    async def tracking_publish(user_id, event_data):
        call_sequence.append("publish")

    with patch.object(AsyncSession, "commit", side_effect=tracking_commit, autospec=True):
        with patch("app.modules.reviews.service.publish_user_event", side_effect=tracking_publish) as mock_pub:
            with auth_patch(buyer_user):
                resp = await test_client.post(
                    f"/api/v1/orders/{order_id}/review",
                    json={"rating": 5, "comment": "Realtime test"},
                )
            assert resp.status_code == 201

            # Exact order verification: commit happens strictly before realtime publish
            assert call_sequence == ["commit", "publish"]
            assert mock_pub.call_count == 1
            target_uid, event_payload = mock_pub.call_args[0]
            assert target_uid == seller_id
            assert event_payload["type"] == "NOTIFICATION_CREATED"
            notif_dict = event_payload["notification"]
            assert notif_dict["type"] == "NEW_REVIEW"
            assert notif_dict["ref_type"] == "ORDER"
            assert notif_dict["ref_id"] == order_id
            assert notif_dict["title"] == "Bạn có đánh giá mới"
            assert notif_dict["body"] == f"Đơn {order_code} vừa nhận được đánh giá 5 sao."


@pytest.mark.asyncio
async def test_realtime_failure_does_not_rollback_review_or_notification(
    test_client: AsyncClient,
    db_session: AsyncSession,
    buyer_user: User,
    seller_user: User,
    completed_order: Order,
):
    """
    If Redis/WebSocket publication fails, Review and Notification remain committed,
    and the HTTP 201 response succeeds.
    """
    with patch(
        "app.modules.reviews.service.publish_user_event",
        side_effect=Exception("Redis connection refused"),
    ):
        with auth_patch(buyer_user):
            resp = await test_client.post(
                f"/api/v1/orders/{completed_order.order_id}/review",
                json={"rating": 5, "comment": "Giao dịch thành công dù Redis lỗi"},
            )
        # HTTP response is still successful
        assert resp.status_code == 201

    # Both Review and Notification exist in DB
    rev_cnt = await db_session.scalar(
        select(func.count(Review.review_id)).where(Review.order_id == completed_order.order_id)
    )
    assert rev_cnt == 1

    notif_cnt = await db_session.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.user_id == seller_user.user_id
        )
    )
    assert notif_cnt == 1


@pytest.mark.asyncio
async def test_zero_realtime_on_patch_or_duplicate_or_invalid(
    test_client: AsyncClient,
    buyer_user: User,
    completed_order: Order,
):
    """Zero realtime events on PATCH, duplicate POST, or invalid review."""
    # 1. Create first valid review
    with auth_patch(buyer_user):
        await test_client.post(
            f"/api/v1/orders/{completed_order.order_id}/review",
            json={"rating": 5, "comment": "Review ban đầu"},
        )

    # 2. Monitor publish_user_event during subsequent actions
    with patch("app.modules.reviews.service.publish_user_event", new_callable=AsyncMock) as mock_pub:
        # Action A: PATCH review
        with auth_patch(buyer_user):
            resp_patch = await test_client.patch(
                f"/api/v1/orders/{completed_order.order_id}/review",
                json={"rating": 4},
            )
        assert resp_patch.status_code == 200
        assert mock_pub.call_count == 0

        # Action B: Duplicate POST
        with auth_patch(buyer_user):
            resp_dup = await test_client.post(
                f"/api/v1/orders/{completed_order.order_id}/review",
                json={"rating": 5},
            )
        assert resp_dup.status_code == 409
        assert mock_pub.call_count == 0

        # Action C: Invalid rating POST
        with auth_patch(buyer_user):
            resp_invalid = await test_client.post(
                f"/api/v1/orders/{completed_order.order_id}/review",
                json={"rating": 10},
            )
        assert resp_invalid.status_code == 422
        assert mock_pub.call_count == 0


@pytest.mark.asyncio
async def test_commit_failure_dispatches_zero_realtime_events(
    test_client: AsyncClient,
    buyer_user: User,
    completed_order: Order,
):
    """If DB commit fails, publish_user_event is NOT called."""
    order_id = completed_order.order_id
    with patch.object(AsyncSession, "commit", side_effect=Exception("Database crash on commit")):
        with patch("app.modules.reviews.service.publish_user_event", new_callable=AsyncMock) as mock_pub:
            with auth_patch(buyer_user):
                with pytest.raises(Exception, match="Database crash on commit"):
                    await test_client.post(
                        f"/api/v1/orders/{order_id}/review",
                        json={"rating": 5, "comment": "Commit crash test"},
                    )
            assert mock_pub.call_count == 0
