from unittest.mock import patch, MagicMock
import pytest

from app.core.config import settings
from app.integrations.cloudinary import (
    get_cloudinary_root_folder,
    get_cloudinary_folder,
    get_product_cloudinary_folder,
    get_order_receipt_cloudinary_folder,
    get_conversation_attachment_cloudinary_folder,
    get_report_evidence_cloudinary_folder,
    get_community_moment_cloudinary_folder,
    get_feedback_cloudinary_folder,
    get_tutorial_video_cloudinary_folder,
    upload_image,
    destroy_image,
    is_cloudinary_configured,
    CloudinaryNotConfiguredError,
    CloudinaryUploadError,
    get_thumbnail_url,
    get_detail_image_url,
    build_transformed_url,
)


def test_get_cloudinary_folder_products():
    """Verify base folder resolution for products in default development environment."""
    folder = get_cloudinary_folder("products")
    assert folder == "student-marketplace/dev/products"


def test_get_product_cloudinary_folder_458():
    """Verify product-scoped folder resolution for product_id=458."""
    folder = get_product_cloudinary_folder(458)
    assert folder == "student-marketplace/dev/products/product-458"


def test_get_product_cloudinary_folder_1():
    """Verify product-scoped folder resolution for product_id=1."""
    folder = get_product_cloudinary_folder(1)
    assert folder == "student-marketplace/dev/products/product-1"


def test_get_product_cloudinary_folder_different_ids():
    """Verify different product IDs resolve to distinct isolated folders."""
    folder_458 = get_product_cloudinary_folder(458)
    folder_459 = get_product_cloudinary_folder(459)
    assert folder_458 != folder_459
    assert folder_458 == "student-marketplace/dev/products/product-458"
    assert folder_459 == "student-marketplace/dev/products/product-459"


def test_get_cloudinary_folder_invalid_key_raises():
    """Verify invalid folder keys raise ValueError."""
    with pytest.raises(ValueError, match="Unsupported Cloudinary folder key"):
        get_cloudinary_folder("invalid_folder_key")  # type: ignore[arg-type]


def test_get_cloudinary_folder_normalizes_slashes():
    """Verify root folder with slashes is properly normalized."""
    with patch.object(settings, "CLOUDINARY_ROOT_FOLDER", "/custom-root/"):
        assert get_cloudinary_folder("products") == "custom-root/dev/products"
        assert get_product_cloudinary_folder(458) == "custom-root/dev/products/product-458"


def test_cloudinary_environment_separation():
    """Verify dev and prod namespaces are strictly separated across all folder builders."""
    with patch.object(settings, "ENVIRONMENT", "development"):
        assert get_cloudinary_root_folder() == "student-marketplace/dev"
        assert get_cloudinary_folder("products") == "student-marketplace/dev/products"
        assert get_order_receipt_cloudinary_folder(10) == "student-marketplace/dev/orders/order-10"
        assert get_conversation_attachment_cloudinary_folder(20) == "student-marketplace/dev/conversations/conv-20"
        assert get_report_evidence_cloudinary_folder(30) == "student-marketplace/dev/reports/report-30"
        assert get_community_moment_cloudinary_folder() == "student-marketplace/dev/community-moments"
        assert get_feedback_cloudinary_folder() == "student-marketplace/dev/feedback"
        assert get_tutorial_video_cloudinary_folder() == "student-marketplace/dev/tutorials/videos"

    with patch.object(settings, "ENVIRONMENT", "production"):
        assert get_cloudinary_root_folder() == "student-marketplace/prod"
        assert get_cloudinary_folder("products") == "student-marketplace/prod/products"
        assert get_order_receipt_cloudinary_folder(10) == "student-marketplace/prod/orders/order-10"
        assert get_conversation_attachment_cloudinary_folder(20) == "student-marketplace/prod/conversations/conv-20"
        assert get_report_evidence_cloudinary_folder(30) == "student-marketplace/prod/reports/report-30"
        assert get_community_moment_cloudinary_folder() == "student-marketplace/prod/community-moments"
        assert get_feedback_cloudinary_folder() == "student-marketplace/prod/feedback"
        assert get_tutorial_video_cloudinary_folder() == "student-marketplace/prod/tutorials/videos"


def test_is_cloudinary_configured():
    """Verify configuration check logic."""
    with patch.object(settings, "CLOUDINARY_CLOUD_NAME", "my_cloud"), \
         patch.object(settings, "CLOUDINARY_API_KEY", "my_key"), \
         patch.object(settings, "CLOUDINARY_API_SECRET", "my_secret"):
        assert is_cloudinary_configured() is True

    with patch.object(settings, "CLOUDINARY_CLOUD_NAME", None):
        assert is_cloudinary_configured() is False


def test_upload_image_missing_credentials_raises():
    """Verify upload fails predictably if credentials missing."""
    with patch.object(settings, "CLOUDINARY_CLOUD_NAME", None):
        with pytest.raises(CloudinaryNotConfiguredError, match="not configured"):
            upload_image(b"fake_image_bytes", folder_key="products", product_id=458)


def test_upload_image_passes_correct_product_scoped_folder():
    """Verify upload_image forwards folder='student-marketplace/dev/products/product-458' to SDK."""
    with patch.object(settings, "CLOUDINARY_CLOUD_NAME", "test_cloud"), \
         patch.object(settings, "CLOUDINARY_API_KEY", "test_key"), \
         patch.object(settings, "CLOUDINARY_API_SECRET", "test_secret"):
        with patch("cloudinary.uploader.upload") as mock_upload:
            mock_upload.return_value = {
                "secure_url": "https://res.cloudinary.com/test_cloud/image/upload/v1/prod.jpg",
                "public_id": "student-marketplace/dev/products/product-458/prod_123",
            }
            result = upload_image(b"image_bytes", folder_key="products", product_id=458)

            mock_upload.assert_called_once_with(
                b"image_bytes",
                folder="student-marketplace/dev/products/product-458",
                resource_type="image",
            )
            assert result["public_id"] == "student-marketplace/dev/products/product-458/prod_123"
            assert result["secure_url"] == "https://res.cloudinary.com/test_cloud/image/upload/v1/prod.jpg"


def test_upload_image_without_product_id_falls_back_to_base():
    """Verify upload_image forwards folder='student-marketplace/dev/products' when product_id is None."""
    with patch.object(settings, "CLOUDINARY_CLOUD_NAME", "test_cloud"), \
         patch.object(settings, "CLOUDINARY_API_KEY", "test_key"), \
         patch.object(settings, "CLOUDINARY_API_SECRET", "test_secret"):
        with patch("cloudinary.uploader.upload") as mock_upload:
            mock_upload.return_value = {
                "secure_url": "https://res.cloudinary.com/test_cloud/image/upload/v1/prod.jpg",
                "public_id": "student-marketplace/dev/products/prod_123",
            }
            result = upload_image(b"image_bytes", folder_key="products")

            mock_upload.assert_called_once_with(
                b"image_bytes",
                folder="student-marketplace/dev/products",
                resource_type="image",
            )
            assert result["public_id"] == "student-marketplace/dev/products/prod_123"




def test_upload_image_handles_sdk_error():
    """Verify upload_image wraps SDK errors in CloudinaryUploadError."""
    with patch.object(settings, "CLOUDINARY_CLOUD_NAME", "test_cloud"), \
         patch.object(settings, "CLOUDINARY_API_KEY", "test_key"), \
         patch.object(settings, "CLOUDINARY_API_SECRET", "test_secret"):
        with patch("cloudinary.uploader.upload", side_effect=Exception("Connection timeout")):
            with pytest.raises(CloudinaryUploadError, match="Cloudinary upload failed"):
                upload_image(b"image_bytes", folder_key="products", product_id=458)


def test_destroy_image():
    """Verify destroy_image passes exact public_id to destroy method."""
    with patch.object(settings, "CLOUDINARY_CLOUD_NAME", "test_cloud"), \
         patch.object(settings, "CLOUDINARY_API_KEY", "test_key"), \
         patch.object(settings, "CLOUDINARY_API_SECRET", "test_secret"):
        with patch("cloudinary.uploader.destroy") as mock_destroy:
            mock_destroy.return_value = {"result": "ok"}
            success = destroy_image("student-marketplace/products/product-458/prod_123")
            assert success is True
            mock_destroy.assert_called_once_with(
                "student-marketplace/products/product-458/prod_123",
                resource_type="image",
            )


def test_destroy_image_missing_credentials():
    """Verify destroy_image returns False when credentials missing or public_id empty."""
    with patch.object(settings, "CLOUDINARY_CLOUD_NAME", None):
        assert destroy_image("some_id") is False
    assert destroy_image("") is False


def test_transformations():
    """Verify responsive image transformation URL generation."""
    raw_url = "https://res.cloudinary.com/test_cloud/image/upload/v12345/student-marketplace/products/product-458/prod.jpg"
    thumb = get_thumbnail_url(raw_url)
    assert thumb == "https://res.cloudinary.com/test_cloud/image/upload/f_auto,q_auto,w_200/student-marketplace/products/product-458/prod.jpg"

    detail = get_detail_image_url(raw_url)
    assert detail == "https://res.cloudinary.com/test_cloud/image/upload/f_auto,q_auto,w_800/student-marketplace/products/product-458/prod.jpg"

    assert get_thumbnail_url(None) is None
    assert get_detail_image_url(None) is None
