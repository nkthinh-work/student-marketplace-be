import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.categories.models import Category
from app.modules.conversations.models import Conversation, ConversationMember
from app.modules.notifications.models import Notification, NotificationType
from app.modules.orders.models import Order, OrderItem, OrderStatus
from app.modules.products.models import ListingType, Product, ProductApprovalStatus, ProductModerationStatus, ProductStatus
from app.modules.reports.models import Report, ReportReason, ReportStatus, ReportTargetType
from app.modules.users.models import User, UserRole, UserStatus
from app.main import app


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
async def user_a(db_session: AsyncSession) -> User:
    user = User(
        email="user_a_bola@ptit.edu.vn",
        full_name="Nguyễn Văn A BOLA",
        phone="0352866333",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    user = User(
        email="user_b_bola@ptit.edu.vn",
        full_name="Trần Thị B BOLA",
        phone="0352866444",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def user_c(db_session: AsyncSession) -> User:
    user = User(
        email="user_c_bola@ptit.edu.vn",
        full_name="Lê Văn C ThirdParty",
        phone="0352866555",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


# =====================================================================
# 1. ORDERS BOLA / IDOR TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_order_detail_bola_rejection(
    test_client: AsyncClient, user_a: User, user_b: User, user_c: User, db_session: AsyncSession
):
    cat = Category(name="Đồ dùng BOLA", slug="do-dung-bola")
    db_session.add(cat)
    await db_session.flush()

    prod = Product(
        seller_id=user_a.user_id,
        category_id=cat.category_id,
        title="Máy tính Casio fx-580",
        listing_type=ListingType.FIXED_PRICE.value,
        price=350000,
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status=ProductApprovalStatus.APPROVED.value,
        moderation_status=ProductModerationStatus.CLEAR.value,
    )
    db_session.add(prod)
    await db_session.flush()

    order = Order(
        order_code="ORD-BOLA-01",
        buyer_id=user_b.user_id,
        seller_id=user_a.user_id,
        contact_name="Trần Thị B",
        contact_phone="0352866444",
        status=OrderStatus.PENDING.value,
        total_amount=350000,
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.order_id,
        product_id=prod.product_id,
        product_title=prod.title,
        quantity=1,
        price_at_purchase=350000,
    )
    db_session.add(item)
    await db_session.commit()

    # User A (seller) can view
    with auth_patch(user_a):
        res_a = await test_client.get(f"/api/v1/orders/{order.order_id}", headers={"Authorization": "Bearer mock"})
        assert res_a.status_code == 200

    # User B (buyer) can view
    with auth_patch(user_b):
        res_b = await test_client.get(f"/api/v1/orders/{order.order_id}", headers={"Authorization": "Bearer mock"})
        assert res_b.status_code == 200

    # User C (unrelated third party) gets 404 (existence hiding)
    with auth_patch(user_c):
        res_c = await test_client.get(f"/api/v1/orders/{order.order_id}", headers={"Authorization": "Bearer mock"})
        assert res_c.status_code == 404

    # User C cannot confirm order
    with auth_patch(user_c):
        res_confirm = await test_client.post(
            f"/api/v1/orders/{order.order_id}/confirm",
            json={"payment_note": "Sneaky confirm"},
            headers={"Authorization": "Bearer mock"},
        )
        assert res_confirm.status_code == 404

    # User C cannot cancel order
    with auth_patch(user_c):
        res_cancel = await test_client.post(
            f"/api/v1/orders/{order.order_id}/cancel",
            json={"cancel_reason": "Attacker trying to cancel"},
            headers={"Authorization": "Bearer mock"},
        )
        assert res_cancel.status_code in (403, 404)


# =====================================================================
# 2. CONVERSATIONS & MESSAGES BOLA / IDOR TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_conversation_and_messages_bola_rejection(
    test_client: AsyncClient, user_a: User, user_b: User, user_c: User, db_session: AsyncSession
):
    # Direct conversation between User A and User B
    conv = Conversation(
        type="DIRECT",
        user_one_id=user_a.user_id,
        user_two_id=user_b.user_id,
    )
    db_session.add(conv)
    await db_session.flush()

    m1 = ConversationMember(conversation_id=conv.conversation_id, user_id=user_a.user_id, role="MEMBER")
    m2 = ConversationMember(conversation_id=conv.conversation_id, user_id=user_b.user_id, role="MEMBER")
    db_session.add_all([m1, m2])
    await db_session.commit()

    # User A can view conversation detail
    with auth_patch(user_a):
        res_a = await test_client.get(
            f"/api/v1/conversations/{conv.conversation_id}", headers={"Authorization": "Bearer mock"}
        )
        assert res_a.status_code == 200

    # User C cannot view conversation detail -> 404
    with auth_patch(user_c):
        res_c = await test_client.get(
            f"/api/v1/conversations/{conv.conversation_id}", headers={"Authorization": "Bearer mock"}
        )
        assert res_c.status_code == 404

    # User C cannot read messages -> 404
    with auth_patch(user_c):
        res_msgs = await test_client.get(
            f"/api/v1/conversations/{conv.conversation_id}/messages", headers={"Authorization": "Bearer mock"}
        )
        assert res_msgs.status_code == 404

    # User C cannot send message -> 404
    with auth_patch(user_c):
        res_send = await test_client.post(
            f"/api/v1/conversations/{conv.conversation_id}/messages",
            data={"content": "Malicious intrusion message"},
            headers={"Authorization": "Bearer mock"},
        )
        assert res_send.status_code == 404


# =====================================================================
# 3. NOTIFICATIONS BOLA / IDOR TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_notifications_bola_rejection(
    test_client: AsyncClient, user_a: User, user_b: User, db_session: AsyncSession
):
    # Create notification for User A
    notif = Notification(
        user_id=user_a.user_id,
        type=NotificationType.SYSTEM.value,
        title="Tin nhắn riêng tư của User A",
        body="Nội dung bảo mật",
        is_read=False,
    )
    db_session.add(notif)
    await db_session.commit()

    # User B cannot mark User A's notification as read -> 404
    with auth_patch(user_b):
        res_read = await test_client.patch(
            f"/api/v1/notifications/{notif.notification_id}/read",
            headers={"Authorization": "Bearer mock"},
        )
        assert res_read.status_code == 404

    # User B cannot delete User A's notification -> 404
    with auth_patch(user_b):
        res_del = await test_client.delete(
            f"/api/v1/notifications/{notif.notification_id}",
            headers={"Authorization": "Bearer mock"},
        )
        assert res_del.status_code == 404

    # User A can mark as read -> 204
    with auth_patch(user_a):
        res_a_read = await test_client.patch(
            f"/api/v1/notifications/{notif.notification_id}/read",
            headers={"Authorization": "Bearer mock"},
        )
        assert res_a_read.status_code == 204


# =====================================================================
# 4. ADMIN & MODERATION IDOR TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_admin_reports_and_moderation_unauthorized_rejection(
    test_client: AsyncClient, user_a: User, user_b: User, db_session: AsyncSession
):
    report = Report(
        reporter_id=user_a.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=user_b.user_id,
        reason=ReportReason.SPAM.value,
        description="Spam link",
        status=ReportStatus.OPEN.value,
    )
    db_session.add(report)
    await db_session.commit()

    # User A (student role) cannot access admin queue -> 403
    with auth_patch(user_a):
        res_queue = await test_client.get(
            "/api/v1/admin/reports", headers={"Authorization": "Bearer mock"}
        )
        assert res_queue.status_code == 403

    # User A cannot execute moderation actions -> 403
    with auth_patch(user_a):
        res_enforce = await test_client.post(
            f"/api/v1/admin/reports/{report.report_id}/enforcement",
            json={"action": "USER_BAN"},
            headers={"Authorization": "Bearer mock"},
        )
        assert res_enforce.status_code == 403


# =====================================================================
# 5. PRODUCT MUTATION IDOR TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_product_mutation_unauthorized_rejection(
    test_client: AsyncClient, user_a: User, user_b: User, db_session: AsyncSession
):
    cat = Category(name="Sản phẩm IDOR", slug="san-pham-idor")
    db_session.add(cat)
    await db_session.flush()

    prod = Product(
        seller_id=user_a.user_id,
        category_id=cat.category_id,
        title="Sản phẩm của User A",
        listing_type=ListingType.FIXED_PRICE.value,
        price=50000,
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status=ProductApprovalStatus.APPROVED.value,
        moderation_status=ProductModerationStatus.CLEAR.value,
    )
    db_session.add(prod)
    await db_session.commit()

    # User B cannot update User A's product -> 403 or 404
    with auth_patch(user_b):
        res_update = await test_client.patch(
            f"/api/v1/products/{prod.product_id}",
            json={
                "title": "Bị thay đổi bởi Hacker",
            },
            headers={"Authorization": "Bearer mock"},
        )
        assert res_update.status_code in (403, 404)

    # User B cannot delete User A's product -> 403 or 404
    with auth_patch(user_b):
        res_delete = await test_client.delete(
            f"/api/v1/products/{prod.product_id}",
            headers={"Authorization": "Bearer mock"},
        )
        assert res_delete.status_code in (403, 404)
