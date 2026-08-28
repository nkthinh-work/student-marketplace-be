import io
from unittest.mock import patch, MagicMock
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.cloudinary import CloudinaryNotConfiguredError
from app.modules.categories.models import Category
from app.modules.products.models import Product, ProductImage
from app.modules.users.models import User, UserStatus, UserRole, UserAuthIdentity


@pytest_asyncio.fixture
async def image_test_data(db_session: AsyncSession):
    seller = User(
        email="seller_img@ptit.edu.vn",
        full_name="Seller Image",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    other = User(
        email="other_img@ptit.edu.vn",
        full_name="Other User",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add_all([seller, other])
    await db_session.flush()

    db_session.add_all([
        UserAuthIdentity(user_id=seller.user_id, provider="FIREBASE", provider_uid="fb_seller_img"),
        UserAuthIdentity(user_id=other.user_id, provider="FIREBASE", provider_uid="fb_other_img"),
    ])
    await db_session.flush()

    category = Category(name="Đồ Gia Dụng", slug="do-gd", is_deleted=False)
    db_session.add(category)
    await db_session.flush()

    # Product 1 for seller
    p1 = Product(
        seller_id=seller.user_id,
        category_id=category.category_id,
        title="Ấm đun nước siêu tốc",
        price=120000,
        stock=1,
    )
    # Product 2 for other user
    p2 = Product(
        seller_id=other.user_id,
        category_id=category.category_id,
        title="Quạt mini để bàn",
        price=80000,
        stock=1,
    )
    db_session.add_all([p1, p2])
    await db_session.flush()

    return {
        "seller": seller,
        "other": other,
        "p1": p1,
        "p2": p2,
    }


@pytest.mark.asyncio
async def test_upload_image_success(test_client: AsyncClient, image_test_data: dict):
    seller = image_test_data["seller"]
    p1 = image_test_data["p1"]

    mock_upload_result = {
        "secure_url": "https://res.cloudinary.com/demo/image/upload/v12345/prod_img_1.jpg",
        "public_id": "student_marketplace/products/prod_img_1",
    }

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value={"uid": "fb_seller_img", "email": seller.email, "name": seller.full_name}):
        with patch("app.modules.products.service.upload_image", return_value=mock_upload_result):
            file_content = b"fake-jpeg-binary-data"
            files = {"file": ("test.jpg", io.BytesIO(file_content), "image/jpeg")}

            res = await test_client.post(
                f"/api/v1/products/{p1.product_id}/images/upload",
                files=files,
                headers={"Authorization": "Bearer seller_token"},
            )
            assert res.status_code == 201
            data = res.json()
            assert data["image_url"] == mock_upload_result["secure_url"]
            assert "f_auto,q_auto,w_800" in data["detail_url"]
            assert data["is_thumbnail"] is True
            assert data["sort_order"] == 0


@pytest.mark.asyncio
async def test_upload_image_non_owner_forbidden(test_client: AsyncClient, image_test_data: dict):
    other = image_test_data["other"]
    p1 = image_test_data["p1"]

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value={"uid": "fb_other_img", "email": other.email, "name": other.full_name}):
        file_content = b"fake-jpeg-binary-data"
        files = {"file": ("test.jpg", io.BytesIO(file_content), "image/jpeg")}

        res = await test_client.post(
            f"/api/v1/products/{p1.product_id}/images/upload",
            files=files,
            headers={"Authorization": "Bearer other_token"},
        )
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_upload_image_invalid_mime_rejected(test_client: AsyncClient, image_test_data: dict):
    seller = image_test_data["seller"]
    p1 = image_test_data["p1"]

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value={"uid": "fb_seller_img", "email": seller.email, "name": seller.full_name}):
        file_content = b"fake text"
        files = {"file": ("test.txt", io.BytesIO(file_content), "text/plain")}

        res = await test_client.post(
            f"/api/v1/products/{p1.product_id}/images/upload",
            files=files,
            headers={"Authorization": "Bearer seller_token"},
        )
        assert res.status_code == 400
        assert "Invalid image type" in res.json()["detail"]


@pytest.mark.asyncio
async def test_upload_image_cloudinary_not_configured_503(test_client: AsyncClient, image_test_data: dict):
    seller = image_test_data["seller"]
    p1 = image_test_data["p1"]

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value={"uid": "fb_seller_img", "email": seller.email, "name": seller.full_name}):
        with patch("app.modules.products.service.upload_image", side_effect=CloudinaryNotConfiguredError("Not configured")):
            files = {"file": ("test.jpg", io.BytesIO(b"img"), "image/jpeg")}

            res = await test_client.post(
                f"/api/v1/products/{p1.product_id}/images/upload",
                files=files,
                headers={"Authorization": "Bearer seller_token"},
            )
            assert res.status_code == 503
            assert "not configured" in res.json()["detail"]


@pytest.mark.asyncio
async def test_upload_image_db_failure_triggers_cleanup(test_client: AsyncClient, image_test_data: dict):
    seller = image_test_data["seller"]
    p1 = image_test_data["p1"]

    mock_upload_result = {
        "secure_url": "https://res.cloudinary.com/demo/image/upload/v12345/prod_img_cleanup.jpg",
        "public_id": "student-marketplace/products/prod_img_cleanup_unique",
    }

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value={"uid": "fb_seller_img", "email": seller.email, "name": seller.full_name}):
        with patch("app.modules.products.service.upload_image", return_value=mock_upload_result):
            with patch("app.modules.products.service.ProductImageRepository.create", side_effect=Exception("DB connection dropped")):
                with patch("app.modules.products.service.destroy_image") as mock_destroy:
                    files = {"file": ("test.jpg", io.BytesIO(b"img"), "image/jpeg")}

                    res = await test_client.post(
                        f"/api/v1/products/{p1.product_id}/images/upload",
                        files=files,
                        headers={"Authorization": "Bearer seller_token"},
                    )
                    assert res.status_code == 500
                    # Kiểm tra hàm destroy_image được gọi đúng với public_id trả về từ Cloudinary
                    mock_destroy.assert_called_once_with("student-marketplace/products/prod_img_cleanup_unique")


@pytest.mark.asyncio
async def test_set_thumbnail_success(test_client: AsyncClient, image_test_data: dict, db_session: AsyncSession):
    seller = image_test_data["seller"]
    p1 = image_test_data["p1"]

    img1 = ProductImage(product_id=p1.product_id, image_url="https://res.cloudinary.com/demo/img1.jpg", sort_order=0, is_thumbnail=True)
    img2 = ProductImage(product_id=p1.product_id, image_url="https://res.cloudinary.com/demo/img2.jpg", sort_order=1, is_thumbnail=False)
    db_session.add_all([img1, img2])
    await db_session.flush()

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value={"uid": "fb_seller_img", "email": seller.email, "name": seller.full_name}):
        res = await test_client.patch(
            f"/api/v1/products/{p1.product_id}/images/{img2.image_id}/thumbnail",
            headers={"Authorization": "Bearer seller_token"},
        )
        assert res.status_code == 200

        await db_session.refresh(img1)
        await db_session.refresh(img2)
        assert img2.is_thumbnail is True
        assert img1.is_thumbnail is False


@pytest.mark.asyncio
async def test_set_thumbnail_cross_product_404(test_client: AsyncClient, image_test_data: dict, db_session: AsyncSession):
    seller = image_test_data["seller"]
    p1 = image_test_data["p1"]
    p2 = image_test_data["p2"]

    img_p2 = ProductImage(product_id=p2.product_id, image_url="https://res.cloudinary.com/demo/img_p2.jpg", sort_order=0, is_thumbnail=True)
    db_session.add(img_p2)
    await db_session.flush()

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value={"uid": "fb_seller_img", "email": seller.email, "name": seller.full_name}):
        res = await test_client.patch(
            f"/api/v1/products/{p1.product_id}/images/{img_p2.image_id}/thumbnail",
            headers={"Authorization": "Bearer seller_token"},
        )
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_delete_thumbnail_auto_promotes_next(test_client: AsyncClient, image_test_data: dict, db_session: AsyncSession):
    seller = image_test_data["seller"]
    p1 = image_test_data["p1"]

    img1 = ProductImage(product_id=p1.product_id, image_url="https://res.cloudinary.com/demo/img1.jpg", sort_order=0, is_thumbnail=True)
    img2 = ProductImage(product_id=p1.product_id, image_url="https://res.cloudinary.com/demo/img2.jpg", sort_order=1, is_thumbnail=False)
    db_session.add_all([img1, img2])
    await db_session.flush()

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value={"uid": "fb_seller_img", "email": seller.email, "name": seller.full_name}):
        res = await test_client.delete(
            f"/api/v1/products/{p1.product_id}/images/{img1.image_id}",
            headers={"Authorization": "Bearer seller_token"},
        )
        assert res.status_code == 204

        await db_session.refresh(img2)
        assert img2.is_thumbnail is True


@pytest.mark.asyncio
async def test_delete_image_cross_product_404(test_client: AsyncClient, image_test_data: dict, db_session: AsyncSession):
    seller = image_test_data["seller"]
    p1 = image_test_data["p1"]
    p2 = image_test_data["p2"]

    img_p2 = ProductImage(product_id=p2.product_id, image_url="https://res.cloudinary.com/demo/img_p2.jpg", sort_order=0, is_thumbnail=True)
    db_session.add(img_p2)
    await db_session.flush()

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value={"uid": "fb_seller_img", "email": seller.email, "name": seller.full_name}):
        res = await test_client.delete(
            f"/api/v1/products/{p1.product_id}/images/{img_p2.image_id}",
            headers={"Authorization": "Bearer seller_token"},
        )
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_reorder_images_success(test_client: AsyncClient, image_test_data: dict, db_session: AsyncSession):
    seller = image_test_data["seller"]
    p1 = image_test_data["p1"]

    img1 = ProductImage(product_id=p1.product_id, image_url="https://res.cloudinary.com/demo/img1.jpg", sort_order=0, is_thumbnail=True)
    img2 = ProductImage(product_id=p1.product_id, image_url="https://res.cloudinary.com/demo/img2.jpg", sort_order=1, is_thumbnail=False)
    db_session.add_all([img1, img2])
    await db_session.flush()

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value={"uid": "fb_seller_img", "email": seller.email, "name": seller.full_name}):
        payload = {
            "images": [
                {"image_id": img1.image_id, "sort_order": 5},
                {"image_id": img2.image_id, "sort_order": 2},
            ]
        }
        res = await test_client.put(
            f"/api/v1/products/{p1.product_id}/images/reorder",
            json=payload,
            headers={"Authorization": "Bearer seller_token"},
        )
        assert res.status_code == 200

        await db_session.refresh(img1)
        await db_session.refresh(img2)
        assert img1.sort_order == 5
        assert img2.sort_order == 2


@pytest.mark.asyncio
async def test_reorder_images_cross_product_404(test_client: AsyncClient, image_test_data: dict, db_session: AsyncSession):
    seller = image_test_data["seller"]
    p1 = image_test_data["p1"]
    p2 = image_test_data["p2"]

    img1 = ProductImage(product_id=p1.product_id, image_url="https://res.cloudinary.com/demo/img1.jpg", sort_order=0, is_thumbnail=True)
    img_p2 = ProductImage(product_id=p2.product_id, image_url="https://res.cloudinary.com/demo/img_p2.jpg", sort_order=0, is_thumbnail=True)
    db_session.add_all([img1, img_p2])
    await db_session.flush()

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value={"uid": "fb_seller_img", "email": seller.email, "name": seller.full_name}):
        payload = {
            "images": [
                {"image_id": img1.image_id, "sort_order": 1},
                {"image_id": img_p2.image_id, "sort_order": 2},
            ]
        }
        res = await test_client.put(
            f"/api/v1/products/{p1.product_id}/images/reorder",
            json=payload,
            headers={"Authorization": "Bearer seller_token"},
        )
        assert res.status_code == 404
