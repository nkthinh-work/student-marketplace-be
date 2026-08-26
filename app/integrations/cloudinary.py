import logging
import re
from typing import Any, Optional
import cloudinary
import cloudinary.uploader
import cloudinary.utils

from app.core.config import settings

logger = logging.getLogger("app")


class CloudinaryNotConfiguredError(Exception):
    pass


class CloudinaryUploadError(Exception):
    pass


def is_cloudinary_configured() -> bool:
    return bool(
        settings.CLOUDINARY_CLOUD_NAME
        and settings.CLOUDINARY_API_KEY
        and settings.CLOUDINARY_API_SECRET
    )


def init_cloudinary() -> None:
    if is_cloudinary_configured():
        try:
            cloudinary.config(
                cloud_name=settings.CLOUDINARY_CLOUD_NAME,
                api_key=settings.CLOUDINARY_API_KEY,
                api_secret=settings.CLOUDINARY_API_SECRET,
                secure=True,
            )
            logger.info("Cloudinary SDK successfully configured.")
        except Exception as e:
            logger.error(f"Error configuring Cloudinary: {e}")
    else:
        logger.warning(
            "Cloudinary credentials missing. Cloudinary upload will return 503."
        )


def upload_image(
    file: Any,
    folder: str = "products",
) -> dict[str, Any]:
    """
    Uploads an image file to Cloudinary.
    Raises CloudinaryNotConfiguredError if credentials are not configured.
    Raises CloudinaryUploadError if upload fails.
    """
    if not is_cloudinary_configured():
        raise CloudinaryNotConfiguredError(
            "Cloudinary storage service is not configured."
        )

    try:
        result = cloudinary.uploader.upload(
            file,
            folder=f"student_marketplace/{folder}",
            resource_type="image",
        )
        return result
    except Exception as e:
        logger.error(f"Failed to upload image to Cloudinary: {e}")
        raise CloudinaryUploadError(f"Cloudinary upload failed: {e}") from e


def destroy_image(public_id: str) -> bool:
    """
    Best-effort cleanup of an uploaded Cloudinary asset.
    Returns True if deletion succeeded, False otherwise.
    """
    if not is_cloudinary_configured() or not public_id:
        return False

    try:
        result = cloudinary.uploader.destroy(public_id, resource_type="image")
        if result.get("result") in ("ok", "not found"):
            return True
        logger.warning(f"Cloudinary destroy returned non-ok result: {result}")
        return False
    except Exception as e:
        logger.error(f"Error executing Cloudinary destroy for {public_id}: {e}")
        return False


def build_transformed_url(
    original_url: str,
    width: int,
    format: str = "auto",
    quality: str = "auto",
) -> str:
    """
    Constructs a responsive, optimized image URL from a Cloudinary image URL.
    Applies f_auto,q_auto,w_<width>.
    If the URL is not a standard Cloudinary URL (e.g. mock in tests), returns the original URL.
    """
    if not original_url:
        return ""

    transform_str = f"f_{format},q_{quality},w_{width}"

    # Pattern URL chuẩn của Cloudinary image
    cloudinary_pattern = r"(https?://res\.cloudinary\.com/[^/]+/image/upload/)(?:[^/]+/)?(.*)"
    match = re.match(cloudinary_pattern, original_url)
    if match:
        prefix, rest = match.groups()
        return f"{prefix}{transform_str}/{rest}"

    return original_url


def get_thumbnail_url(image_url: Optional[str]) -> Optional[str]:
    """Generates 200px wide responsive thumbnail URL with f_auto,q_auto."""
    if not image_url:
        return None
    return build_transformed_url(image_url, width=200)


def get_detail_image_url(image_url: Optional[str]) -> Optional[str]:
    """Generates 800px wide responsive detail image URL with f_auto,q_auto."""
    if not image_url:
        return None
    return build_transformed_url(image_url, width=800)
