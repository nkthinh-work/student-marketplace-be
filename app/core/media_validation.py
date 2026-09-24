from typing import Tuple
from fastapi import HTTPException, status

MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
ALLOWED_COMMUNITY_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}


MAX_VIDEO_SIZE_BYTES = 30 * 1024 * 1024  # 30MB
MAX_VIDEO_DURATION_SECONDS = 60.0


def validate_image_bytes(file_name: str, file_bytes: bytes, max_size: int = MAX_IMAGE_SIZE_BYTES) -> str:
    """
    Validates image file bytes against supported formats: JPEG, PNG, WebP.
    Inspects magic bytes / signatures, rejects executables and files exceeding max_size.
    Returns the canonical MIME type ('image/jpeg', 'image/png', 'image/webp').
    Raises HTTPException(422) if invalid.
    """
    if len(file_bytes) < 4:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Tệp '{file_name}' rỗng hoặc bị hỏng.",
        )
    if file_bytes.startswith(b"MZ") or file_bytes.startswith(b"\x7fELF"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Tệp '{file_name}' là tệp thực thi, không được phép tải lên.",
        )

    # 1. JPEG
    if file_bytes.startswith(b"\xff\xd8\xff"):
        if len(file_bytes) > max_size:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Tệp '{file_name}' vượt quá dung lượng tối đa cho phép (10MB).",
            )
        return "image/jpeg"

    # 2. PNG
    if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(file_bytes) > max_size:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Tệp '{file_name}' vượt quá dung lượng tối đa cho phép (10MB).",
            )
        return "image/png"

    # 3. WEBP: RIFF + length (4 bytes) + WEBP
    if file_bytes.startswith(b"RIFF") and len(file_bytes) >= 12 and file_bytes[8:12] == b"WEBP":
        if len(file_bytes) > max_size:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Tệp '{file_name}' vượt quá dung lượng tối đa cho phép (10MB).",
            )
        return "image/webp"

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=f"Định dạng tệp '{file_name}' không được hỗ trợ. Chỉ chấp nhận ảnh (JPEG, PNG, WebP).",
    )


def validate_media_evidence_bytes(file_name: str, file_bytes: bytes) -> tuple[str, str]:
    """
    Validates evidence file bytes against supported image and video formats.
    Returns (canonical_mime_type, media_type) where media_type is 'IMAGE' or 'VIDEO'.
    """
    if len(file_bytes) < 4:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Tệp '{file_name}' rỗng hoặc bị hỏng.",
        )
    if file_bytes.startswith(b"MZ") or file_bytes.startswith(b"\x7fELF"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Tệp '{file_name}' là tệp thực thi, không được phép tải lên.",
        )

    # 1. Check images
    if (
        file_bytes.startswith(b"\xff\xd8\xff")
        or file_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        or (file_bytes.startswith(b"RIFF") and len(file_bytes) >= 12 and file_bytes[8:12] == b"WEBP")
    ):
        canonical_mime = validate_image_bytes(file_name, file_bytes, max_size=MAX_IMAGE_SIZE_BYTES)
        return canonical_mime, "IMAGE"

    # 2. Check videos
    # WebM: EBML header \x1a\x45\xdf\xa3
    if file_bytes.startswith(b"\x1a\x45\xdf\xa3"):
        if len(file_bytes) > MAX_VIDEO_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Tệp '{file_name}' vượt quá dung lượng tối đa cho phép đối với video (30MB).",
            )
        return "video/webm", "VIDEO"

    # MP4 / QuickTime (MOV): ISOBMFF box check
    if len(file_bytes) >= 8 and file_bytes[4:8] in (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip"):
        if len(file_bytes) > MAX_VIDEO_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Tệp '{file_name}' vượt quá dung lượng tối đa cho phép đối với video (30MB).",
            )
        # Check if QuickTime specific brand or extension
        is_quicktime = False
        if len(file_bytes) >= 12 and file_bytes[4:8] == b"ftyp" and file_bytes[8:12] in (b"qt  ", b"mqt "):
            is_quicktime = True
        elif file_name.lower().endswith((".mov", ".qt")):
            is_quicktime = True

        if is_quicktime:
            return "video/quicktime", "VIDEO"
        return "video/mp4", "VIDEO"

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=f"Định dạng tệp '{file_name}' không được hỗ trợ. Chỉ chấp nhận ảnh (JPEG, PNG, WebP) hoặc video (MP4, WebM, MOV).",
    )

