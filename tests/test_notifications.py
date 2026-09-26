from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.categories.models import Category
from app.modules.notifications.models import Notification, NotificationType
from app.modules.notifications.repository import NotificationRepository
from app.modules.orders.models import Order
from app.modules.products.models import ListingType, Product, ProductStatus
from app.modules.users.models import User, UserAuthIdentity, UserRole, UserStatus


@pytest_asyncio.fixture
async def user_a(db_session: AsyncSession) -> User:
    user = User(
        email=f"user_a_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="User A",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid=f"uid_user_a_{user.user_id}",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    user = User(
        email=f"user_b_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="User B",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid=f"uid_user_b_{user.user_id}",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> Category:
    cat = Category(
        name=f"Category {uuid4().hex[:6]}",
        slug=f"cat-{uuid4().hex[:6]}",
        is_deleted=False,
    )
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def fixed_product(
    db_session: AsyncSession, user_a: User, sample_category: Category
) -> Product:
    prod = Product(
        seller_id=user_a.user_id,
        category_id=sample_category.category_id,
        title="Sách Giáo Trình Mạng Máy Tính",
        description="Mô tả sách mạng máy tính",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal("50000"),
        stock=5,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


def auth_patch(user: User):
    return patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        return_value={
            "uid": f"uid_user_{'a' if 'user_a' in user.email else 'b'}_{user.user_id}",
            "email": user.email,
            "name": user.full_name,
        },
    )


# 1. User lists only own notifications
@pytest.mark.asyncio
async def test_list_notifications_user_isolation(
    test_client: AsyncClient, user_a: User, user_b: User, db_session: AsyncSession
):
    repo = NotificationRepository(db_session)
    n_a = await repo.create(
        user_id=user_a.user_id,
        type=NotificationType.NEW_ORDER.value,
        title="Đơn cho A",
        body="Nội dung cho A",
    )
    n_b = await repo.create(
        user_id=user_b.user_id,
        type=NotificationType.NEW_MESSAGE.value,
        title="Đơn cho B",
        body="Nội dung cho B",
    )
    await db_session.flush()

    with auth_patch(user_a):
        res = await test_client.get(
            "/api/v1/notifications",
            headers={"Authorization": "Bearer token"},
        )
    assert res.status_code == 200
    data = res.json()
    ids = [item["notification_id"] for item in data["items"]]
    assert n_a.notification_id in ids
    assert n_b.notification_id not in ids


# 2. Ordering: created_at DESC, notification_id DESC
@pytest.mark.asyncio
async def test_list_notifications_ordering(
    test_client: AsyncClient, user_a: User, db_session: AsyncSession
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    n1 = Notification(
        user_id=user_a.user_id,
        type=NotificationType.SYSTEM.value,
        title="First",
        created_at=now - timedelta(minutes=10),
    )
    n2 = Notification(
        user_id=user_a.user_id,
        type=NotificationType.SYSTEM.value,
        title="Second",
        created_at=now - timedelta(minutes=5),
    )
    n3 = Notification(
        user_id=user_a.user_id,
        type=NotificationType.SYSTEM.value,
        title="Third",
        created_at=now,
    )
    db_session.add_all([n1, n2, n3])
    await db_session.flush()

    with auth_patch(user_a):
        res = await test_client.get(
            "/api/v1/notifications",
            headers={"Authorization": "Bearer token"},
        )
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) >= 3
    assert items[0]["notification_id"] == n3.notification_id
    assert items[1]["notification_id"] == n2.notification_id
    assert items[2]["notification_id"] == n1.notification_id


# 3. Keyset cursor pagination stability
@pytest.mark.asyncio
async def test_keyset_cursor_pagination(
    test_client: AsyncClient, user_a: User, db_session: AsyncSession
):
    repo = NotificationRepository(db_session)
    for i in range(5):
        await repo.create(
            user_id=user_a.user_id,
            type=NotificationType.SYSTEM.value,
            title=f"Notif {i}",
        )
    await db_session.flush()

    with auth_patch(user_a):
        # Fetch page 1 with limit 2
        res1 = await test_client.get(
            "/api/v1/notifications?limit=2",
            headers={"Authorization": "Bearer token"},
        )
        assert res1.status_code == 200
        data1 = res1.json()
        assert len(data1["items"]) == 2
        assert data1["has_more"] is True
        assert data1["next_cursor"] is not None

        # Fetch page 2
        cursor = data1["next_cursor"]
        res2 = await test_client.get(
            f"/api/v1/notifications?limit=2&cursor={cursor}",
            headers={"Authorization": "Bearer token"},
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert len(data2["items"]) == 2

        # Verify no item overlap between pages
        page1_ids = {item["notification_id"] for item in data1["items"]}
        page2_ids = {item["notification_id"] for item in data2["items"]}
        assert page1_ids.isdisjoint(page2_ids)


# 4. unread_only filter & unread-count
@pytest.mark.asyncio
async def test_unread_only_and_unread_count(
    test_client: AsyncClient, user_a: User, db_session: AsyncSession
):
    repo = NotificationRepository(db_session)
    n1 = await repo.create(
        user_id=user_a.user_id,
        type=NotificationType.SYSTEM.value,
        title="Unread 1",
    )
    n2 = await repo.create(
        user_id=user_a.user_id,
        type=NotificationType.SYSTEM.value,
        title="Unread 2",
    )
    n3 = await repo.create(
        user_id=user_a.user_id,
        type=NotificationType.SYSTEM.value,
        title="Read 1",
    )
    n3.is_read = True
    await db_session.flush()

    with auth_patch(user_a):
        # Check unread count
        count_res = await test_client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": "Bearer token"},
        )
        assert count_res.status_code == 200
        assert count_res.json()["count"] == 2

        # Check unread_only filter
        list_res = await test_client.get(
            "/api/v1/notifications?unread_only=true",
            headers={"Authorization": "Bearer token"},
        )
        assert list_res.status_code == 200
        items = list_res.json()["items"]
        assert all(not item["is_read"] for item in items)
        retrieved_ids = [item["notification_id"] for item in items]
        assert n1.notification_id in retrieved_ids
        assert n2.notification_id in retrieved_ids
        assert n3.notification_id not in retrieved_ids


# 5. Mark single notification read (204, idempotent)
@pytest.mark.asyncio
async def test_mark_single_read_idempotent(
    test_client: AsyncClient, user_a: User, db_session: AsyncSession
):
    repo = NotificationRepository(db_session)
    n = await repo.create(
        user_id=user_a.user_id,
        type=NotificationType.NEW_ORDER.value,
        title="Single read",
    )
    await db_session.flush()

    with auth_patch(user_a):
        # First call -> 204
        res1 = await test_client.patch(
            f"/api/v1/notifications/{n.notification_id}/read",
            headers={"Authorization": "Bearer token"},
        )
        assert res1.status_code == 204

        # Verify in DB
        await db_session.refresh(n)
        assert n.is_read is True

        # Second call (idempotent) -> 204
        res2 = await test_client.patch(
            f"/api/v1/notifications/{n.notification_id}/read",
            headers={"Authorization": "Bearer token"},
        )
        assert res2.status_code == 204


# 6. Non-leaking 404 for stranger's notification or nonexistent
@pytest.mark.asyncio
async def test_mark_read_stranger_or_nonexistent_404(
    test_client: AsyncClient, user_a: User, user_b: User, db_session: AsyncSession
):
    repo = NotificationRepository(db_session)
    n_b = await repo.create(
        user_id=user_b.user_id,
        type=NotificationType.SYSTEM.value,
        title="Notification of B",
    )
    await db_session.flush()

    with auth_patch(user_a):
        # User A tries to mark B's notification -> 404
        res_stranger = await test_client.patch(
            f"/api/v1/notifications/{n_b.notification_id}/read",
            headers={"Authorization": "Bearer token"},
        )
        assert res_stranger.status_code == 404
        assert res_stranger.json()["detail"] == "Không tìm thấy thông báo."

        # Nonexistent notification -> 404
        res_nonexistent = await test_client.patch(
            "/api/v1/notifications/9999999/read",
            headers={"Authorization": "Bearer token"},
        )
        assert res_nonexistent.status_code == 404


# 7. Static route /read-all does NOT collide with /{id}/read & marks all read
@pytest.mark.asyncio
async def test_mark_all_read_static_route(
    test_client: AsyncClient, user_a: User, user_b: User, db_session: AsyncSession
):
    repo = NotificationRepository(db_session)
    n_a1 = await repo.create(
        user_id=user_a.user_id,
        type=NotificationType.SYSTEM.value,
        title="A unread 1",
    )
    n_a2 = await repo.create(
        user_id=user_a.user_id,
        type=NotificationType.SYSTEM.value,
        title="A unread 2",
    )
    n_b = await repo.create(
        user_id=user_b.user_id,
        type=NotificationType.SYSTEM.value,
        title="B unread",
    )
    await db_session.flush()

    with auth_patch(user_a):
        res = await test_client.patch(
            "/api/v1/notifications/read-all",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 204

        # Check user A unread count is now 0
        count_res = await test_client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": "Bearer token"},
        )
        assert count_res.json()["count"] == 0

    # User B's notification remains unread
    await db_session.refresh(n_b)
    assert n_b.is_read is False


# 8. NEW_ORDER creation creates notification for seller and publishes realtime
@pytest.mark.asyncio
async def test_order_creation_creates_seller_notification(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    fixed_product: Product,
    db_session: AsyncSession,
):
    # user_a is seller, user_b is buyer
    with auth_patch(user_b), patch(
        "app.modules.orders.service.publish_user_event", new_callable=AsyncMock
    ) as mock_publish:
        res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": fixed_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường PTIT Hà Đông",
                "contact_name": "Nguyen Van B",
                "contact_phone": "0987654321",
                "buyer_note": "Giao giờ trưa",
            },
        )
        assert res.status_code == 201
        order_data = res.json()
        order_id = order_data["order_id"]
        order_code = order_data["order_code"]

        # 1. Verify notification created in DB for SELLER (user_a)
        stmt = select(Notification).where(
            Notification.user_id == user_a.user_id,
            Notification.ref_id == order_id,
        )
        result = await db_session.execute(stmt)
        notification = result.scalar_one_or_none()
        assert notification is not None
        assert notification.type == NotificationType.NEW_ORDER.value
        assert notification.ref_type == "ORDER"
        assert notification.ref_id == order_id
        assert notification.title == "Bạn có đơn hàng mới"
        assert f"Đơn {order_code} vừa được tạo." == notification.body
        assert notification.is_read is False

        # 2. Verify BUYER (user_b) has NO notification
        buyer_stmt = select(Notification).where(
            Notification.user_id == user_b.user_id,
            Notification.ref_id == order_id,
        )
        buyer_result = await db_session.execute(buyer_stmt)
        assert buyer_result.scalar_one_or_none() is None

        # 3. Verify realtime event published to seller
        mock_publish.assert_awaited()
        # Find the NOTIFICATION_CREATED call
        event_calls = [
            call for call in mock_publish.call_args_list
            if len(call[0]) >= 2 and isinstance(call[0][1], dict) and call[0][1].get("type") == "NOTIFICATION_CREATED"
        ]
        assert len(event_calls) == 1
        target_user_id = event_calls[0][0][0]
        event_payload = event_calls[0][0][1]
        assert target_user_id == user_a.user_id
        assert event_payload["notification"]["notification_id"] == notification.notification_id
        assert event_payload["notification"]["type"] == "NEW_ORDER"


# 9. Realtime failure does not roll back order or notification
@pytest.mark.asyncio
async def test_order_creation_realtime_failure_does_not_break_order(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    fixed_product: Product,
    db_session: AsyncSession,
):
    with auth_patch(user_b), patch(
        "app.modules.orders.service.publish_user_event",
        side_effect=Exception("Redis connection refused"),
    ):
        res = await test_client.post(
            "/api/v1/orders",
            headers={"Authorization": "Bearer token"},
            json={
                "product_id": fixed_product.product_id,
                "quantity": 1,
                "payment_method": "CASH_ON_MEETUP",
                "fulfillment_method": "MEETUP",
                "meetup_place": "Cổng trường PTIT Hà Đông",
                "contact_name": "Nguyen Van B",
                "contact_phone": "0987654321",
            },
        )
        # Order should succeed despite realtime error
        assert res.status_code == 201
        order_id = res.json()["order_id"]

        # Notification still persisted
        stmt = select(Notification).where(
            Notification.user_id == user_a.user_id,
            Notification.ref_id == order_id,
        )
        result = await db_session.execute(stmt)
        assert result.scalar_one_or_none() is not None


# 10. Delete own read Notification -> 204, row gone
@pytest.mark.asyncio
async def test_delete_own_read_notification(
    test_client: AsyncClient,
    user_a: User,
    db_session: AsyncSession,
):
    notif = Notification(
        user_id=user_a.user_id,
        type="SYSTEM",
        title="Test Read Notif",
        body="Body",
        is_read=True,
    )
    db_session.add(notif)
    await db_session.commit()
    await db_session.refresh(notif)

    with auth_patch(user_a):
        res = await test_client.delete(
            f"/api/v1/notifications/{notif.notification_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 204

    # Verify row is hard deleted from DB
    stmt = select(Notification).where(Notification.notification_id == notif.notification_id)
    result = await db_session.execute(stmt)
    assert result.scalar_one_or_none() is None


# 11. Delete own unread Notification -> 204, unread-count decreases canonically
@pytest.mark.asyncio
async def test_delete_own_unread_notification_decrements_count(
    test_client: AsyncClient,
    user_a: User,
    db_session: AsyncSession,
):
    notif = Notification(
        user_id=user_a.user_id,
        type="SYSTEM",
        title="Test Unread Notif",
        body="Body",
        is_read=False,
    )
    db_session.add(notif)
    await db_session.commit()
    await db_session.refresh(notif)

    with auth_patch(user_a):
        count_res_before = await test_client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": "Bearer token"},
        )
        before_count = count_res_before.json()["count"]
        assert before_count >= 1

        del_res = await test_client.delete(
            f"/api/v1/notifications/{notif.notification_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert del_res.status_code == 204

        count_res_after = await test_client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": "Bearer token"},
        )
        after_count = count_res_after.json()["count"]
        assert after_count == before_count - 1


# 12. Delete other user's Notification -> 404 privacy-safe, row remains
@pytest.mark.asyncio
async def test_delete_other_user_notification_returns_404(
    test_client: AsyncClient,
    user_a: User,
    user_b: User,
    db_session: AsyncSession,
):
    notif = Notification(
        user_id=user_a.user_id,
        type="SYSTEM",
        title="User A's Notif",
        body="Body",
        is_read=False,
    )
    db_session.add(notif)
    await db_session.commit()
    await db_session.refresh(notif)

    # User B tries to delete User A's notification
    with auth_patch(user_b):
        res = await test_client.delete(
            f"/api/v1/notifications/{notif.notification_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 404

    # Verify row still exists for User A
    stmt = select(Notification).where(Notification.notification_id == notif.notification_id)
    result = await db_session.execute(stmt)
    assert result.scalar_one_or_none() is not None


# 13. Delete nonexistent notification -> 404
@pytest.mark.asyncio
async def test_delete_nonexistent_notification_returns_404(
    test_client: AsyncClient,
    user_a: User,
):
    with auth_patch(user_a):
        res = await test_client.delete(
            "/api/v1/notifications/999999999",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 404


# 14. Delete Admin actionable notification -> underlying referenced object remains unchanged
@pytest.mark.asyncio
async def test_delete_admin_actionable_notification_preserves_underlying_object(
    test_client: AsyncClient,
    user_a: User,
    fixed_product: Product,
    db_session: AsyncSession,
):
    # Create an admin notification referencing a product
    admin_notif = Notification(
        user_id=user_a.user_id,
        type="SYSTEM",
        title="Có tin đăng mới chờ duyệt",
        body="Chi tiết",
        ref_type="ADMIN_PRODUCT_APPROVAL",
        ref_id=fixed_product.product_id,
        is_read=False,
    )
    db_session.add(admin_notif)
    await db_session.commit()
    await db_session.refresh(admin_notif)

    with auth_patch(user_a):
        res = await test_client.delete(
            f"/api/v1/notifications/{admin_notif.notification_id}",
            headers={"Authorization": "Bearer token"},
        )
        assert res.status_code == 204

    # Notification row is gone
    stmt_notif = select(Notification).where(Notification.notification_id == admin_notif.notification_id)
    assert (await db_session.execute(stmt_notif)).scalar_one_or_none() is None

    # Underlying product remains intact and untouched
    stmt_prod = select(Product).where(Product.product_id == fixed_product.product_id)
    prod = (await db_session.execute(stmt_prod)).scalar_one_or_none()
    assert prod is not None
    assert prod.title == fixed_product.title
    assert prod.is_deleted is False
