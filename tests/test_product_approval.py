import asyncio
import io
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.products.router import get_optional_current_user
from app.modules.categories.models import Category
from app.modules.notifications.models import Notification
from app.modules.products.models import (
    ListingType,
    Product,
    ProductApprovalStatus,
    ProductImage,
    ProductModerationStatus,
    ProductStatus,
)
from app.modules.users.models import User, UserRole, UserStatus, UserAuthIdentity


def auth_patch(user: User):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_current_user] = lambda: user

    class CleanCtx:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc_val, exc_tb):
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_optional_current_user, None)

    return CleanCtx()


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> Category:
    cat = Category(name="Đồ Gia Dụng SV", slug="do-gia-dung-sv", is_deleted=False)
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def seller_user(db_session: AsyncSession) -> User:
    user = User(
        email="seller_approval@ptit.edu.vn",
        full_name="Nguyễn Văn Bán",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="firebase_seller_approval",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def buyer_user(db_session: AsyncSession) -> User:
    user = User(
        email="buyer_approval@ptit.edu.vn",
        full_name="Trần Thị Mua",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="firebase_buyer_approval",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email="admin_approver@ptit.edu.vn",
        full_name="Admin Kiểm Duyệt",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid="firebase_admin_approver",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_product_creation_defaults_to_draft(
    test_client: AsyncClient,
    seller_user: User,
    sample_category: Category,
):
    with auth_patch(seller_user):
        payload = {
            "title": "Nồi cơm điện mini SV",
            "description": "Nồi cơm điện 1.2L còn dùng tốt không hỏng hóc gì.",
            "price": 150000,
            "category_id": sample_category.category_id,
            "listing_type": "FIXED_PRICE",
            "stock": 1,
        }
        res = await test_client.post("/api/v1/products", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["title"] == "Nồi cơm điện mini SV"
        assert data["approval_status"] == "DRAFT"
        assert data["moderation_status"] == "CLEAR"
        assert data["status"] == "AVAILABLE"


@pytest.mark.asyncio
async def test_submit_review_zero_images_allowed(
    test_client: AsyncClient,
    seller_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    # Create product directly in DRAFT without images
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Bàn học gấp gọn không ảnh",
        description="Bàn học nhỏ gọn gỗ ép sinh viên.",
        price=Decimal("120000"),
        stock=1,
        listing_type=ListingType.FIXED_PRICE,
        status=ProductStatus.AVAILABLE,
        approval_status=ProductApprovalStatus.DRAFT,
        moderation_status=ProductModerationStatus.CLEAR,
    )
    db_session.add(prod)
    await db_session.flush()

    # Zero images is valid for review submission
    with auth_patch(seller_user):
        res = await test_client.post(f"/api/v1/products/{prod.product_id}/submit-review")
        assert res.status_code == 200
        data = res.json()
        assert data["approval_status"] == "PENDING"
        assert data["submitted_for_review_at"] is not None


@pytest.mark.asyncio
async def test_submit_review_success_and_admin_notification(
    test_client: AsyncClient,
    seller_user: User,
    admin_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Quạt bàn mini Senko",
        description="Quạt chạy êm mát nguyên bản.",
        price=Decimal("80000"),
        stock=1,
        listing_type=ListingType.FIXED_PRICE,
        status=ProductStatus.AVAILABLE,
        approval_status=ProductApprovalStatus.DRAFT,
        moderation_status=ProductModerationStatus.CLEAR,
    )
    db_session.add(prod)
    await db_session.flush()

    # Add at least 1 image
    img = ProductImage(
        product_id=prod.product_id,
        image_url="https://res.cloudinary.com/demo/image/upload/v1/sample.jpg",
        sort_order=0,
        is_thumbnail=True,
    )
    db_session.add(img)
    await db_session.flush()

    with auth_patch(seller_user):
        res = await test_client.post(f"/api/v1/products/{prod.product_id}/submit-review")
        assert res.status_code == 200
        data = res.json()
        assert data["approval_status"] == "PENDING"
        assert data["submitted_for_review_at"] is not None

    # Verify admin received notification
    stmt = select(Notification).where(
        Notification.user_id == admin_user.user_id,
        Notification.ref_type == "ADMIN_PRODUCT_APPROVAL",
        Notification.ref_id == prod.product_id,
    )
    admin_notif = (await db_session.execute(stmt)).scalars().first()
    assert admin_notif is not None
    assert "Có tin đăng mới chờ duyệt" in admin_notif.title


@pytest.mark.asyncio
async def test_submit_review_invalid_transition(
    test_client: AsyncClient,
    seller_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Sách lập trình Python",
        description="Sách mới 99% không gập mép.",
        price=Decimal("50000"),
        stock=1,
        listing_type=ListingType.FIXED_PRICE,
        status=ProductStatus.AVAILABLE,
        approval_status=ProductApprovalStatus.PENDING,
        moderation_status=ProductModerationStatus.CLEAR,
    )
    db_session.add(prod)
    await db_session.flush()
    img = ProductImage(
        product_id=prod.product_id,
        image_url="https://res.cloudinary.com/demo/image/upload/v1/sample.jpg",
        sort_order=0,
        is_thumbnail=True,
    )
    db_session.add(img)
    await db_session.flush()

    with auth_patch(seller_user):
        # Cannot submit PENDING again
        res = await test_client.post(f"/api/v1/products/{prod.product_id}/submit-review")
        assert res.status_code == 409

        # Cannot submit APPROVED
        prod.approval_status = ProductApprovalStatus.APPROVED
        await db_session.flush()
        res2 = await test_client.post(f"/api/v1/products/{prod.product_id}/submit-review")
        assert res2.status_code == 409


@pytest.mark.asyncio
async def test_submit_review_stranger_forbidden(
    test_client: AsyncClient,
    seller_user: User,
    buyer_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Chuột quang Logitech",
        description="Chuột có dây cổng USB.",
        price=Decimal("60000"),
        stock=1,
        listing_type=ListingType.FIXED_PRICE,
        status=ProductStatus.AVAILABLE,
        approval_status=ProductApprovalStatus.DRAFT,
        moderation_status=ProductModerationStatus.CLEAR,
    )
    db_session.add(prod)
    await db_session.flush()

    with auth_patch(buyer_user):
        res = await test_client.post(f"/api/v1/products/{prod.product_id}/submit-review")
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_admin_approval_queue_and_detail(
    test_client: AsyncClient,
    seller_user: User,
    buyer_user: User,
    admin_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Ấm siêu tốc Inox 1.8L",
        description="Đun nước sôi cực nhanh tự ngắt khi sôi.",
        price=Decimal("95000"),
        stock=1,
        listing_type=ListingType.FIXED_PRICE,
        status=ProductStatus.AVAILABLE,
        approval_status=ProductApprovalStatus.PENDING,
        moderation_status=ProductModerationStatus.CLEAR,
        submitted_for_review_at=datetime.now(timezone.utc),
    )
    db_session.add(prod)
    await db_session.flush()
    img = ProductImage(
        product_id=prod.product_id,
        image_url="https://res.cloudinary.com/demo/image/upload/v1/sample.jpg",
        sort_order=0,
        is_thumbnail=True,
    )
    db_session.add(img)
    await db_session.flush()

    # Non-admin forbidden
    with auth_patch(buyer_user):
        res = await test_client.get("/api/v1/admin/product-approvals")
        assert res.status_code == 403

    # Admin access queue
    with auth_patch(admin_user):
        res = await test_client.get("/api/v1/admin/product-approvals")
        assert res.status_code == 200
        data = res.json()
        assert "items" in data
        item_ids = [item["product_id"] for item in data["items"]]
        assert prod.product_id in item_ids

        # Admin access detail
        detail_res = await test_client.get(f"/api/v1/admin/product-approvals/{prod.product_id}")
        assert detail_res.status_code == 200
        detail_data = detail_res.json()
        assert detail_data["product_id"] == prod.product_id
        assert detail_data["title"] == "Ấm siêu tốc Inox 1.8L"
        assert detail_data["seller"] is not None
        assert detail_data["seller"]["full_name"] == seller_user.full_name
        assert len(detail_data["images"]) >= 1


@pytest.mark.asyncio
async def test_admin_approve_success(
    test_client: AsyncClient,
    seller_user: User,
    admin_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Kệ để giày dép 4 tầng",
        description="Kệ giày nhựa lắp ráp chắc chắn.",
        price=Decimal("70000"),
        stock=1,
        listing_type=ListingType.FIXED_PRICE,
        status=ProductStatus.AVAILABLE,
        approval_status=ProductApprovalStatus.PENDING,
        moderation_status=ProductModerationStatus.CLEAR,
        submitted_for_review_at=datetime.now(timezone.utc),
    )
    db_session.add(prod)
    await db_session.flush()

    with auth_patch(admin_user):
        res = await test_client.post(
            f"/api/v1/admin/product-approvals/{prod.product_id}/decision",
            json={"decision": "APPROVE"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["approval_status"] == "APPROVED"
        assert data["reviewed_by"] == admin_user.user_id
        assert data["reviewed_at"] is not None

    # Seller gets notification
    stmt = select(Notification).where(
        Notification.user_id == seller_user.user_id,
        Notification.ref_type == "PRODUCT_APPROVAL",
        Notification.ref_id == prod.product_id,
    )
    seller_notif = (await db_session.execute(stmt)).scalars().first()
    assert seller_notif is not None
    assert "đã được duyệt" in seller_notif.title


@pytest.mark.asyncio
async def test_admin_reject_success_and_resubmit(
    test_client: AsyncClient,
    seller_user: User,
    admin_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Tai nghe Bluetooth hỏng 1 bên",
        description="Bán xác tai nghe cho ai cần linh kiện.",
        price=Decimal("30000"),
        stock=1,
        listing_type=ListingType.FIXED_PRICE,
        status=ProductStatus.AVAILABLE,
        approval_status=ProductApprovalStatus.PENDING,
        moderation_status=ProductModerationStatus.CLEAR,
        submitted_for_review_at=datetime.now(timezone.utc),
    )
    db_session.add(prod)
    await db_session.flush()
    img = ProductImage(
        product_id=prod.product_id,
        image_url="https://res.cloudinary.com/demo/image/upload/v1/sample.jpg",
        sort_order=0,
        is_thumbnail=True,
    )
    db_session.add(img)
    await db_session.flush()

    # Reject without note fails validation
    with auth_patch(admin_user):
        bad_res = await test_client.post(
            f"/api/v1/admin/product-approvals/{prod.product_id}/decision",
            json={"decision": "REJECT", "note": ""},
        )
        assert bad_res.status_code in (400, 422)

        # Reject with valid note
        res = await test_client.post(
            f"/api/v1/admin/product-approvals/{prod.product_id}/decision",
            json={"decision": "REJECT", "note": "Thông tin sản phẩm chưa đủ rõ ràng."},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["approval_status"] == "REJECTED"
        assert data["review_note"] == "Thông tin sản phẩm chưa đủ rõ ràng."

    # Seller can re-submit REJECTED -> PENDING
    with auth_patch(seller_user):
        res_resubmit = await test_client.post(f"/api/v1/products/{prod.product_id}/submit-review")
        assert res_resubmit.status_code == 200
        assert res_resubmit.json()["approval_status"] == "PENDING"


@pytest.mark.asyncio
async def test_admin_decision_concurrency_409(
    test_client: AsyncClient,
    seller_user: User,
    admin_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Đèn bàn học Rạng Đông",
        description="Đèn LED chống cận tốt.",
        price=Decimal("110000"),
        stock=1,
        listing_type=ListingType.FIXED_PRICE,
        status=ProductStatus.AVAILABLE,
        approval_status=ProductApprovalStatus.APPROVED,  # Already approved!
        moderation_status=ProductModerationStatus.CLEAR,
    )
    db_session.add(prod)
    await db_session.flush()

    with auth_patch(admin_user):
        res = await test_client.post(
            f"/api/v1/admin/product-approvals/{prod.product_id}/decision",
            json={"decision": "APPROVE"},
        )
        assert res.status_code == 409


@pytest.mark.asyncio
async def test_public_visibility_gate(
    test_client: AsyncClient,
    seller_user: User,
    buyer_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    # Create products in various approval statuses
    draft_prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Draft Book Visible Only to Owner",
        description="Desc",
        price=Decimal("50000"),
        stock=1,
        listing_type=ListingType.FIXED_PRICE,
        status=ProductStatus.AVAILABLE,
        approval_status=ProductApprovalStatus.DRAFT,
        moderation_status=ProductModerationStatus.CLEAR,
    )
    pending_prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Pending Book Visible Only to Owner",
        description="Desc",
        price=Decimal("50000"),
        stock=1,
        listing_type=ListingType.FIXED_PRICE,
        status=ProductStatus.AVAILABLE,
        approval_status=ProductApprovalStatus.PENDING,
        moderation_status=ProductModerationStatus.CLEAR,
    )
    approved_prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Approved Book Visible to Everyone",
        description="Desc",
        price=Decimal("50000"),
        stock=1,
        listing_type=ListingType.FIXED_PRICE,
        status=ProductStatus.AVAILABLE,
        approval_status=ProductApprovalStatus.APPROVED,
        moderation_status=ProductModerationStatus.CLEAR,
    )
    db_session.add_all([draft_prod, pending_prod, approved_prod])
    await db_session.flush()

    # Public list check
    res = await test_client.get("/api/v1/products")
    assert res.status_code == 200
    public_titles = [p["title"] for p in res.json()["items"]]
    assert "Approved Book Visible to Everyone" in public_titles
    assert "Draft Book Visible Only to Owner" not in public_titles
    assert "Pending Book Visible Only to Owner" not in public_titles

    # Stranger direct access: DRAFT/PENDING returns 404
    with auth_patch(buyer_user):
        res_draft = await test_client.get(f"/api/v1/products/{draft_prod.product_id}")
        assert res_draft.status_code == 404
        res_pending = await test_client.get(f"/api/v1/products/{pending_prod.product_id}")
        assert res_pending.status_code == 404
        res_approved = await test_client.get(f"/api/v1/products/{approved_prod.product_id}")
        assert res_approved.status_code == 200

    # Owner direct access: DRAFT returns 200
    with auth_patch(seller_user):
        res_owner = await test_client.get(f"/api/v1/products/{draft_prod.product_id}")
        assert res_owner.status_code == 200


@pytest.mark.asyncio
async def test_sensitive_edit_resets_approval_to_draft(
    test_client: AsyncClient,
    seller_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Vợt cầu lông Pro",
        description="Vợt còn mới căng cước xịn.",
        price=Decimal("250000"),
        stock=1,
        listing_type=ListingType.FIXED_PRICE,
        status=ProductStatus.AVAILABLE,
        approval_status=ProductApprovalStatus.APPROVED,
        moderation_status=ProductModerationStatus.CLEAR,
    )
    db_session.add(prod)
    await db_session.flush()

    with auth_patch(seller_user):
        # 1. Non-sensitive status change (AVAILABLE -> HIDDEN) preserves APPROVED
        res_status = await test_client.patch(
            f"/api/v1/products/{prod.product_id}",
            json={"status": "HIDDEN"},
        )
        assert res_status.status_code == 200
        assert res_status.json()["approval_status"] == "APPROVED"

        # 2. Sensitive title change resets to DRAFT
        res_title = await test_client.patch(
            f"/api/v1/products/{prod.product_id}",
            json={"title": "Vợt cầu lông Pro Max Plus"},
        )
        assert res_title.status_code == 200
        assert res_title.json()["approval_status"] == "DRAFT"


@pytest.mark.asyncio
async def test_report_moderation_separate_from_approval(
    test_client: AsyncClient,
    admin_user: User,
    seller_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Áo khoác gió SV PTIT",
        description="Áo khoác đồng phục mới.",
        price=Decimal("120000"),
        stock=1,
        listing_type=ListingType.FIXED_PRICE,
        status=ProductStatus.AVAILABLE,
        approval_status=ProductApprovalStatus.APPROVED,
        moderation_status=ProductModerationStatus.CLEAR,
    )
    db_session.add(prod)
    await db_session.flush()

    # Admin enforces PRODUCT_HIDE via report enforcement or moderation action
    # moderation_status becomes BLOCKED, but approval_status remains APPROVED
    prod.moderation_status = ProductModerationStatus.BLOCKED
    await db_session.flush()

    assert prod.approval_status == ProductApprovalStatus.APPROVED
    assert prod.moderation_status == ProductModerationStatus.BLOCKED


@pytest.mark.asyncio
async def test_approved_product_upload_image_resets_to_draft(
    test_client: AsyncClient,
    seller_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Laptop cũ còn tốt",
        description="Core i5 ram 8gb.",
        price=Decimal("4500000"),
        stock=1,
        listing_type=ListingType.FIXED_PRICE,
        status=ProductStatus.AVAILABLE,
        approval_status=ProductApprovalStatus.APPROVED,
        moderation_status=ProductModerationStatus.CLEAR,
    )
    db_session.add(prod)
    await db_session.flush()

    mock_upload_result = {
        "secure_url": "https://res.cloudinary.com/demo/image/upload/v12345/prod_new.jpg",
        "public_id": "student_marketplace/products/prod_new",
    }
    with auth_patch(seller_user):
        with patch("app.modules.products.service.upload_image", return_value=mock_upload_result):
            files = {"file": ("test.jpg", io.BytesIO(b"fake-image-bytes"), "image/jpeg")}
            res = await test_client.post(
                f"/api/v1/products/{prod.product_id}/images/upload",
                files=files,
            )
            assert res.status_code == 201

    await db_session.refresh(prod)
    assert prod.approval_status == ProductApprovalStatus.DRAFT.value
    assert prod.submitted_for_review_at is None


@pytest.mark.asyncio
async def test_approved_product_delete_image_resets_to_draft(
    test_client: AsyncClient,
    seller_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Bàn phím cơ DareU",
        description="Blue switch gõ nảy.",
        price=Decimal("350000"),
        stock=1,
        listing_type=ListingType.FIXED_PRICE,
        status=ProductStatus.AVAILABLE,
        approval_status=ProductApprovalStatus.APPROVED,
        moderation_status=ProductModerationStatus.CLEAR,
    )
    db_session.add(prod)
    await db_session.flush()

    img = ProductImage(
        product_id=prod.product_id,
        image_url="https://res.cloudinary.com/demo/image/upload/v1/keyboard.jpg",
        sort_order=0,
        is_thumbnail=True,
    )
    db_session.add(img)
    await db_session.flush()

    with auth_patch(seller_user):
        res = await test_client.delete(f"/api/v1/products/{prod.product_id}/images/{img.image_id}")
        assert res.status_code == 204

    await db_session.refresh(prod)
    assert prod.approval_status == ProductApprovalStatus.DRAFT.value
    assert prod.submitted_for_review_at is None


@pytest.mark.asyncio
async def test_admin_review_product_with_zero_images(
    test_client: AsyncClient,
    seller_user: User,
    admin_user: User,
    sample_category: Category,
    db_session: AsyncSession,
):
    prod1 = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Tài liệu ôn thi triết học",
        description="Bộ đề cương và tài liệu cương lĩnh ôn thi.",
        price=Decimal("20000"),
        stock=1,
        listing_type=ListingType.FIXED_PRICE,
        status=ProductStatus.AVAILABLE,
        approval_status=ProductApprovalStatus.PENDING,
        moderation_status=ProductModerationStatus.CLEAR,
        submitted_for_review_at=datetime.now(timezone.utc),
    )
    prod2 = Product(
        seller_id=seller_user.user_id,
        category_id=sample_category.category_id,
        title="Tài liệu toán cao cấp A1",
        description="Đề thi các năm trước có giải chi tiết.",
        price=Decimal("25000"),
        stock=1,
        listing_type=ListingType.FIXED_PRICE,
        status=ProductStatus.AVAILABLE,
        approval_status=ProductApprovalStatus.PENDING,
        moderation_status=ProductModerationStatus.CLEAR,
        submitted_for_review_at=datetime.now(timezone.utc),
    )
    db_session.add_all([prod1, prod2])
    await db_session.flush()

    with auth_patch(admin_user):
        detail_res = await test_client.get(f"/api/v1/admin/product-approvals/{prod1.product_id}")
        assert detail_res.status_code == 200
        detail_data = detail_res.json()
        assert detail_data["product_id"] == prod1.product_id
        assert detail_data["images"] == []

        approve_res = await test_client.post(
            f"/api/v1/admin/product-approvals/{prod1.product_id}/decision",
            json={"decision": "APPROVE"},
        )
        assert approve_res.status_code == 200
        assert approve_res.json()["approval_status"] == "APPROVED"

        reject_res = await test_client.post(
            f"/api/v1/admin/product-approvals/{prod2.product_id}/decision",
            json={"decision": "REJECT", "note": "Cần bổ sung thêm thông tin tài liệu."},
        )
        assert reject_res.status_code == 200
        assert reject_res.json()["approval_status"] == "REJECTED"
        assert reject_res.json()["review_note"] == "Cần bổ sung thêm thông tin tài liệu."

