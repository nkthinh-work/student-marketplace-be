import asyncio
import logging
import re
from typing import Any, Literal, Optional
import cloudinary
import cloudinary.uploader
import cloudinary.utils

from app.core.config import settings

logger = logging.getLogger("app")

CloudinaryFolderKey = Literal["products"]
SUPPORTED_CLOUDINARY_FOLDERS: set[str] = {"products"}


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


def get_cloudinary_root_folder() -> str:
    """
    Phân giải namespace thư mục gốc theo môi trường (dev vs prod):
    - production -> {root}/prod
    - development / testing / others -> {root}/dev
    Nếu cấu hình CLOUDINARY_ROOT_FOLDER đã chứa hậu tố môi trường (/dev hoặc /prod) thì giữ nguyên.
    """
    raw_root = (settings.CLOUDINARY_ROOT_FOLDER or "student-marketplace").strip("/")
    if raw_root.endswith("/dev") or raw_root.endswith("/prod"):
        return raw_root
    env = getattr(settings, "ENVIRONMENT", "development").lower()
    env_segment = "prod" if env in ("production", "prod") else "dev"
    return f"{raw_root}/{env_segment}"


def get_cloudinary_folder(folder_key: CloudinaryFolderKey = "products") -> str:
    """
    Phân giải namespace folder trên Cloudinary từ cấu hình root theo môi trường.
    products -> student-marketplace/dev/products (hoặc student-marketplace/prod/products)
    """
    if folder_key not in SUPPORTED_CLOUDINARY_FOLDERS:
        raise ValueError(
            f"Unsupported Cloudinary folder key: '{folder_key}'. Supported: {', '.join(sorted(SUPPORTED_CLOUDINARY_FOLDERS))}"
        )
    root = get_cloudinary_root_folder()
    return f"{root}/{folder_key}"


def get_product_cloudinary_folder(product_id: int) -> str:
    """
    Phân giải namespace folder trên Cloudinary cho một product cụ thể:
    student-marketplace/dev/products/product-{product_id}
    """
    base = get_cloudinary_folder("products")
    return f"{base}/product-{product_id}"


def get_order_receipt_cloudinary_folder(order_id: int) -> str:
    """
    Phân giải namespace folder trên Cloudinary cho biên nhận đơn hàng:
    student-marketplace/dev/orders/order-{order_id}
    """
    root = get_cloudinary_root_folder()
    return f"{root}/orders/order-{order_id}"


def get_conversation_attachment_cloudinary_folder(conversation_id: int) -> str:
    """
    Phân giải namespace folder trên Cloudinary cho tệp đính kèm tin nhắn:
    student-marketplace/dev/conversations/conv-{conversation_id}
    """
    root = get_cloudinary_root_folder()
    return f"{root}/conversations/conv-{conversation_id}"


def get_report_evidence_cloudinary_folder(report_id: int) -> str:
    """
    Phân giải namespace folder trên Cloudinary cho tệp ảnh minh chứng báo cáo:
    student-marketplace/dev/reports/report-{report_id}
    """
    root = get_cloudinary_root_folder()
    return f"{root}/reports/report-{report_id}"


def upload_report_evidence(
    file: Any,
    report_id: int,
    original_filename: str = "",
    resource_type: str = "image",
) -> dict[str, Any]:
    """
    Uploads an image or video evidence file to Cloudinary under the dedicated report folder.
    Uses unique_filename=True and specified resource_type ("image" or "video").
    """
    if not is_cloudinary_configured():
        raise CloudinaryNotConfiguredError(
            "Cloudinary storage service is not configured."
        )

    target_folder = get_report_evidence_cloudinary_folder(report_id)

    try:
        result = cloudinary.uploader.upload(
            file,
            folder=target_folder,
            resource_type=resource_type,
            use_filename=True,
            unique_filename=True,
        )
        return result
    except Exception as e:
        logger.error(f"Failed to upload report evidence to Cloudinary for report {report_id}: {e}")
        raise CloudinaryUploadError(f"Cloudinary report evidence upload failed: {e}") from e


def upload_order_receipt(
    file: Any,
    order_id: int,
) -> dict[str, Any]:
    """
    Uploads a payment receipt image to Cloudinary under the dedicated order folder.
    Uses public_id="payment-receipt" with overwrite=True and invalidate=True.
    """
    if not is_cloudinary_configured():
        raise CloudinaryNotConfiguredError(
            "Cloudinary storage service is not configured."
        )

    target_folder = get_order_receipt_cloudinary_folder(order_id)

    try:
        result = cloudinary.uploader.upload(
            file,
            folder=target_folder,
            public_id="payment-receipt",
            overwrite=True,
            invalidate=True,
            resource_type="image",
        )
        return result
    except Exception as e:
        logger.error(f"Failed to upload order receipt to Cloudinary for order {order_id}: {e}")
        raise CloudinaryUploadError(f"Cloudinary receipt upload failed: {e}") from e


def upload_image(
    file: Any,
    folder_key: CloudinaryFolderKey = "products",
    product_id: Optional[int] = None,
) -> dict[str, Any]:
    """
    Uploads an image file to Cloudinary under the resolved folder namespace.
    If folder_key is "products" and product_id is provided, uploads to `{root}/products/product-{product_id}`.
    Default folder resolves to `{settings.CLOUDINARY_ROOT_FOLDER}/products` ('student-marketplace/products').
    Raises CloudinaryNotConfiguredError if credentials are not configured.
    Raises CloudinaryUploadError if upload fails.
    """
    if not is_cloudinary_configured():
        raise CloudinaryNotConfiguredError(
            "Cloudinary storage service is not configured."
        )

    if folder_key == "products" and product_id is not None:
        target_folder = get_product_cloudinary_folder(product_id)
    else:
        target_folder = get_cloudinary_folder(folder_key)

    try:
        result = cloudinary.uploader.upload(
            file,
            folder=target_folder,
            resource_type="image",
        )
        return result
    except Exception as e:
        logger.error(f"Failed to upload image to Cloudinary: {e}")
        raise CloudinaryUploadError(f"Cloudinary upload failed: {e}") from e


def upload_message_attachment(
    file: Any,
    conversation_id: int,
    kind: str,
    original_filename: str,
) -> dict[str, Any]:
    """
    Uploads a message attachment (IMAGE, VIDEO, PDF) to Cloudinary.
    Maps kind to appropriate resource_type:
      - IMAGE -> 'image'
      - VIDEO -> 'video'
      - PDF -> 'raw'
    """
    if not is_cloudinary_configured():
        raise CloudinaryNotConfiguredError(
            "Cloudinary storage service is not configured."
        )

    target_folder = get_conversation_attachment_cloudinary_folder(conversation_id)

    kind_resource_map = {
        "IMAGE": "image",
        "VIDEO": "video",
        "AUDIO": "video",
        "PDF": "raw",
        "DOCUMENT": "raw",
    }
    resource_type = kind_resource_map.get(kind.upper(), "raw")

    try:
        result = cloudinary.uploader.upload(
            file,
            folder=target_folder,
            resource_type=resource_type,
            use_filename=True,
            unique_filename=True,
        )
        return result
    except Exception as e:
        logger.error(f"Failed to upload message attachment ({kind}) to Cloudinary for conv {conversation_id}: {e}")
        raise CloudinaryUploadError(f"Cloudinary attachment upload failed: {e}") from e


def destroy_asset(public_id: str, resource_type: str = "image") -> bool:
    """
    Best-effort cleanup of an uploaded Cloudinary asset using its exact resource_type.
    Returns True if deletion succeeded, False otherwise.
    """
    if not is_cloudinary_configured() or not public_id:
        return False

    try:
        result = cloudinary.uploader.destroy(public_id, resource_type=resource_type)
        if result.get("result") in ("ok", "not found"):
            return True
        logger.warning(f"Cloudinary destroy returned non-ok result: {result}")
        return False
    except Exception as e:
        logger.error(f"Error executing Cloudinary destroy for {public_id} ({resource_type}): {e}")
        return False


async def destroy_asset_async(public_id: str, resource_type: str = "image") -> bool:
    """
    Asynchronously destroys an asset on Cloudinary off the main asyncio event loop thread.
    """
    return await asyncio.to_thread(destroy_asset, public_id, resource_type=resource_type)


def destroy_image(public_id: str) -> bool:
    """Convenience alias for image assets."""
    return destroy_asset(public_id, resource_type="image")


def generate_delivery_url(
    public_id: str,
    resource_type: str = "image",
    default_url: Optional[str] = None,
) -> str:
    """
    Generates a secure signed delivery URL for an asset.
    Falls back to default_url or standard secure URL.
    """
    if not public_id:
        return default_url or ""
    if not is_cloudinary_configured():
        return default_url or ""
    try:
        url, _ = cloudinary.utils.cloudinary_url(
            public_id,
            resource_type=resource_type,
            secure=True,
            sign_url=True,
        )
        return url
    except Exception as e:
        logger.warning(f"Failed to generate signed Cloudinary URL for {public_id}: {e}")
        return default_url or ""


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


def get_hero_image_url(image_url: Optional[str]) -> Optional[str]:
    """Generates 1600px wide responsive hero image URL with f_auto,q_auto."""
    if not image_url:
        return None
    return build_transformed_url(image_url, width=1600)


def get_community_moment_cloudinary_folder() -> str:
    """
    Phân giải namespace folder trên Cloudinary cho ảnh khoảnh khắc cộng đồng:
    student-marketplace/dev/community-moments
    """
    root = get_cloudinary_root_folder()
    return f"{root}/community-moments"


def upload_community_moment_image(
    file: Any,
    user_id: int,
) -> dict[str, Any]:
    """
    Uploads a community moment photo to Cloudinary under the dedicated community folder.
    Uses unique_filename=True and resource_type="image".
    """
    if not is_cloudinary_configured():
        raise CloudinaryNotConfiguredError(
            "Cloudinary storage service is not configured."
        )

    target_folder = get_community_moment_cloudinary_folder()

    try:
        result = cloudinary.uploader.upload(
            file,
            folder=target_folder,
            resource_type="image",
            unique_filename=True,
        )
        return result
    except Exception as e:
        logger.error(f"Failed to upload community moment image to Cloudinary for user {user_id}: {e}")
        raise CloudinaryUploadError(f"Cloudinary community moment upload failed: {e}") from e


def get_feedback_cloudinary_folder() -> str:
    """
    Phân giải namespace folder trên Cloudinary cho tệp minh chứng feedback:
    student-marketplace/dev/feedback
    """
    root = get_cloudinary_root_folder()
    return f"{root}/feedback"


def upload_feedback_attachment(
    file: Any,
    resource_type: str = "image",
) -> dict[str, Any]:
    """
    Uploads an image or video feedback attachment to Cloudinary under dedicated feedback folder.
    Uses unique_filename=True and specified resource_type ("image" or "video").
    """
    if not is_cloudinary_configured():
        raise CloudinaryNotConfiguredError(
            "Cloudinary storage service is not configured."
        )

    target_folder = get_feedback_cloudinary_folder()

    try:
        result = cloudinary.uploader.upload(
            file,
            folder=target_folder,
            resource_type=resource_type,
            unique_filename=True,
        )
        return result
    except Exception as e:
        logger.error(f"Failed to upload feedback attachment to Cloudinary: {e}")
        raise CloudinaryUploadError(f"Cloudinary feedback attachment upload failed: {e}") from e


def get_tutorial_video_cloudinary_folder() -> str:
    """
    Phân giải namespace folder trên Cloudinary cho video hướng dẫn:
    student-marketplace/dev/tutorials/videos
    """
    root = get_cloudinary_root_folder()
    return f"{root}/tutorials/videos"


def build_tutorial_thumbnail_url(
    video_storage_key: str,
    duration_ms: Optional[int] = None,
) -> str:
    """
    Derives an optimized image thumbnail URL from a Cloudinary video asset.
    Chooses a frame at second 1 (or 0.5s for very short clips), formats as JPG,
    and scales to width 360 (c_limit, f_auto, q_auto).
    Does NOT store or upload a separate asset.
    """
    if not video_storage_key:
        return ""
    start_offset = "0.5" if (duration_ms and duration_ms < 2000) else "1"
    url, _ = cloudinary.utils.cloudinary_url(
        video_storage_key,
        resource_type="video",
        format="jpg",
        start_offset=start_offset,
        width=360,
        crop="limit",
        quality="auto",
        fetch_format="auto",
        secure=True,
    )
    return url


def get_tutorial_video_delivery_url(video_url: str) -> str:
    """
    Returns a web-optimized, universally playable Cloudinary video delivery URL.
    Ensures vc_auto is applied so that modern mobile uploads (e.g. HEVC/hvc1 from iPhones)
    are delivered as universally compatible H.264 (avc1) in all desktop and mobile browsers.
    Preserves existing valid video/upload structure and does NOT use image/upload.
    """
    if not video_url:
        return ""
    pattern = r"(https?://res\.cloudinary\.com/[^/]+/video/upload/)(?:[^/]+/)?(v[0-9]+/.+|\w+/.+)"
    match = re.match(pattern, video_url)
    if match and "vc_" not in video_url:
        prefix, rest = match.groups()
        return f"{prefix}vc_auto/{rest}"
    return video_url


def _upload_tutorial_video_sync(
    file: Any,
    filename: str = "tutorial.mp4",
    file_size: Optional[int] = None,
) -> dict[str, Any]:
    """
    Synchronous Cloudinary SDK invocation for tutorial video upload.
    Must be called off the event loop via upload_tutorial_video.
    Uses normal upload for files <= 20 MB, and upload_large for files > 20 MB.
    """
    if not is_cloudinary_configured():
        raise CloudinaryNotConfiguredError(
            "Cloudinary storage service is not configured."
        )

    target_folder = get_tutorial_video_cloudinary_folder()

    if hasattr(file, "seek") and callable(file.seek):
        file.seek(0)

    if file_size is None and hasattr(file, "seek") and callable(file.seek):
        try:
            file_size = cloudinary.utils.file_io_size(file)
            file.seek(0)
        except Exception:
            file_size = None

    try:
        UPLOAD_LARGE_THRESHOLD_BYTES = 20 * 1024 * 1024  # 20 MB
        if file_size is not None and file_size > UPLOAD_LARGE_THRESHOLD_BYTES:
            result = cloudinary.uploader.upload_large(
                file,
                folder=target_folder,
                resource_type="video",
                unique_filename=True,
                filename=filename,
                chunk_size=20 * 1024 * 1024,
                timeout=150,
            )
        else:
            result = cloudinary.uploader.upload(
                file,
                folder=target_folder,
                resource_type="video",
                unique_filename=True,
                filename=filename,
                timeout=150,
            )

        if not result or not isinstance(result, dict):
            raise CloudinaryUploadError("Cloudinary returned an invalid or empty response.")

        res_type = result.get("resource_type")
        if res_type != "video":
            pub_id = result.get("public_id")
            if pub_id:
                destroy_asset(pub_id, resource_type=res_type or "raw")
            raise CloudinaryUploadError(f"Cloudinary upload returned unexpected resource_type: {res_type}")

        raw_url = result.get("secure_url") or result.get("url") or ""
        if not raw_url:
            raise CloudinaryUploadError("Cloudinary upload did not return a valid delivery URL.")

        result["secure_url"] = get_tutorial_video_delivery_url(raw_url)
        return result
    except CloudinaryUploadError:
        raise
    except Exception as e:
        logger.error(f"Failed to upload tutorial video to Cloudinary: {e}")
        raise CloudinaryUploadError(f"Cloudinary tutorial video upload failed: {e}") from e


async def upload_tutorial_video(
    file: Any,
    filename: str = "tutorial.mp4",
    file_size: Optional[int] = None,
) -> dict[str, Any]:
    """
    Asynchronously uploads a tutorial MP4 video to Cloudinary off the event loop thread.
    """
    return await asyncio.to_thread(_upload_tutorial_video_sync, file, filename=filename, file_size=file_size)
