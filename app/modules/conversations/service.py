import io
import hashlib
import json
import logging
import secrets
import urllib.parse
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID
from fastapi import HTTPException, UploadFile, status

from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.datetime import ensure_utc_aware
from app.core.realtime.presence import get_users_presence
from app.core.redis import get_redis_client, get_or_reconnect_redis
from app.integrations.cloudinary import (
    destroy_asset,
    destroy_asset_async,
    generate_delivery_url,
    upload_message_attachment,
)
from app.core.rate_limiter import check_chat_video_upload_quota
from app.workers.media_cleanup import sanitize_external_error
from app.modules.conversations.models import (
    Conversation,
    ConversationInvite,
    ConversationMember,
    Message,
    MessageAttachment,
)
from app.modules.conversations.repository import (
    ConversationRepository,
    _map_kind_to_resource_type,
    build_reply_summary,
)
from app.modules.conversations.schemas import (
    AttachmentDownloadTicketResponse,
    ConversationDetailResponse,
    ConversationInviteResponse,
    ConversationListResponse,
    ConversationMemberResponse,
    GroupCreateRequest,
    GroupMemberNicknameUpdateRequest,
    GroupUpdateRequest,
    InviteCandidateListResponse,
    MessageAttachmentResponse,
    MessageListResponse,
    MessageMentionResponse,
    MessageReactionSetRequest,
    MessageReactionSummaryResponse,
    MessageResponse,
    OfficialSupportGroupResponse,
    OwnedGroupSummaryResponse,
    ParticipantSummary,
    PendingApprovalActionRequest,
    PendingApprovalItem,
    PendingApprovalListResponse,
    PresenceBatchResponse,
    ProductContextSummary,
    SharedAttachmentListResponse,
    SharedAttachmentSummaryResponse,
    UserSearchResponse,
)
from app.modules.notifications.models import Notification, NotificationType
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.schemas import NotificationResponse
from app.modules.orders.websocket import publish_user_event
from app.modules.products.models import Product, ProductStatus
from app.modules.users.models import User, UserStatus

logger = logging.getLogger("app.conversations.service")


async def safe_publish_user_notification(user_id: int, notif_dto: NotificationResponse) -> None:
    """Best-effort post-commit realtime notification dispatch isolated per recipient."""
    try:
        await publish_user_event(
            user_id,
            {
                "type": "NOTIFICATION_CREATED",
                "notification": notif_dto.model_dump(mode="json"),
            },
        )
    except Exception as err:
        logger.warning(f"Failed to publish NOTIFICATION_CREATED to user {user_id}: {err}")

MAX_ATTACHMENTS_PER_MESSAGE = 4
MAX_TOTAL_ATTACHMENTS_SIZE = 60 * 1024 * 1024  # 60 MB total payload
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024        # 10 MB
MAX_PDF_SIZE_BYTES = 20 * 1024 * 1024          # 20 MB
MAX_DOCUMENT_SIZE_BYTES = 20 * 1024 * 1024     # 20 MB
MAX_AUDIO_SIZE_BYTES = 15 * 1024 * 1024        # 15 MB
MAX_VIDEO_SIZE_BYTES = 50 * 1024 * 1024        # 50 MB
MAX_VOICE_DURATION_SECONDS = 300.0             # 5 minutes


@dataclass
class DownloadAttachmentMetadata:
    attachment_id: int
    original_name: str
    mime_type: str
    size_bytes: int
    kind: str
    target_url: str


def validate_storage_url_safety(target_url: str) -> None:
    """
    Guarantees target_url is an HTTPS Cloudinary URL belonging to the trusted delivery CDN,
    preventing any Server-Side Request Forgery (SSRF) exploitation.
    """
    if not target_url:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Đường dẫn tệp không tồn tại.",
        )
    parsed = urllib.parse.urlparse(target_url)
    if parsed.scheme.lower() != "https":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Giao thức lưu trữ không an toàn.",
        )
    hostname = (parsed.hostname or "").lower()
    allowed_domains = {"res.cloudinary.com"}
    if not any(hostname == d or hostname.endswith("." + d) for d in allowed_domains):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Nguồn lưu trữ tệp không được tin cậy.",
        )


def _is_valid_office_open_xml(file_bytes: bytes) -> bool:
    """Verifies that the ZIP archive contains [Content_Types].xml (genuine Office Open XML)."""
    if not file_bytes.startswith(b"PK\x03\x04"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            namelist = zf.namelist()
            return "[Content_Types].xml" in namelist
    except Exception:
        return False


def _validate_file_content_signature(header: bytes, filename: str, full_bytes: bytes) -> Tuple[str, str]:
    """
    Validates the magic bytes / signature of the file.
    Returns (kind, canonical_mime).
    Rejects executables, scripts, raw archives, or unknown formats.
    """
    if len(header) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tệp tin rỗng hoặc bị lỗi.",
        )

    lower_name = (filename or "").lower()

    # Reject common dangerous executables and scripts explicitly
    if header.startswith(b"MZ") or header.startswith(b"\x7fELF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Executable files are not permitted.",
        )

    # 1. JPEG
    if header.startswith(b"\xff\xd8\xff"):
        return "IMAGE", "image/jpeg"

    # 2. PNG
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "IMAGE", "image/png"

    # 3. WEBP
    if header.startswith(b"RIFF") and len(header) >= 12 and header[8:12] == b"WEBP":
        return "IMAGE", "image/webp"

    # 4. GIF
    if header.startswith(b"GIF87a") or header.startswith(b"GIF89a"):
        return "IMAGE", "image/gif"

    # 5. PDF
    if header.startswith(b"%PDF-"):
        return "PDF", "application/pdf"

    # 6. Audio MP3
    if header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0):
        return "AUDIO", "audio/mpeg"

    # 7. Audio OGG / Opus
    if header.startswith(b"OggS"):
        return "AUDIO", "audio/ogg"

    # 8. Audio WAV
    if header.startswith(b"RIFF") and len(header) >= 12 and header[8:12] == b"WAVE":
        return "AUDIO", "audio/wav"

    # 9. Matroska / WebM (Video or Audio)
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        if lower_name.endswith((".weba", ".ogg", ".opus")) or "audio" in lower_name or "voice" in lower_name:
            return "AUDIO", "audio/webm"
        return "VIDEO", "video/webm"

    # 10. MP4 / M4A
    if len(header) >= 12 and b"ftyp" in header[:16]:
        if b"ftypM4A" in header[:16] or lower_name.endswith((".m4a", ".aac")):
            return "AUDIO", "audio/mp4"
        return "VIDEO", "video/mp4"

    # 11. Office Open XML (.docx, .xlsx, .pptx)
    if header.startswith(b"PK\x03\x04"):
        if _is_valid_office_open_xml(full_bytes):
            if lower_name.endswith(".docx"):
                return "DOCUMENT", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            elif lower_name.endswith(".xlsx"):
                return "DOCUMENT", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            elif lower_name.endswith(".pptx"):
                return "DOCUMENT", "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            return "DOCUMENT", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tệp nén zip hoặc tệp Office giả mạo không được hỗ trợ.",
            )

    # 12. Plain Text (.txt)
    if lower_name.endswith(".txt"):
        if b"\x00" not in header:
            try:
                full_bytes[:1024].decode("utf-8")
                return "DOCUMENT", "text/plain"
            except UnicodeDecodeError:
                pass

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Định dạng tệp không được hỗ trợ. Chỉ nhận ảnh, video, ghi âm, PDF, TXT, DOCX, XLSX, PPTX.",
    )


class ConversationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ConversationRepository(db)

    async def create_or_open_conversation(
        self, current_user: User, product_id: int
    ) -> ConversationDetailResponse:
        """
        Opens or idempotently creates the canonical 1-to-1 Direct conversation for a product.
        """
        prod_stmt = (
            select(Product)
            .options(selectinload(Product.images))
            .where(Product.product_id == product_id, Product.is_deleted.is_(False))
        )
        product = await self.db.scalar(prod_stmt)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sản phẩm không tồn tại.",
            )

        if product.seller_id == current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot start conversation with yourself",
            )

        if product.status == ProductStatus.HIDDEN:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found",
            )

        conv = await self.repo.get_or_create_direct_conversation(
            current_user.user_id, product.seller_id
        )

        other_user = await self.db.get(User, product.seller_id)
        part_summary = ParticipantSummary(
            user_id=product.seller_id,
            public_id=other_user.public_id if other_user else None,
            full_name=other_user.full_name if other_user else "Người bán",
            avatar_url=other_user.avatar_url if other_user else None,
        )

        thumb = next((img.image_url for img in product.images if img.is_thumbnail), None)
        if not thumb and product.images:
            thumb = product.images[0].image_url

        prod_ctx = ProductContextSummary(
            product_id=product.product_id,
            title=product.title,
            price=product.price,
            status=product.status.value if hasattr(product.status, "value") else str(product.status),
            thumbnail_url=thumb,
            listing_type=product.listing_type.value if hasattr(product.listing_type, "value") else str(product.listing_type),
        )

        return ConversationDetailResponse(
            conversation_id=conv.conversation_id,
            type="DIRECT",
            other_participant=part_summary,
            product_context=prod_ctx,
            created_at=conv.created_at,
        )

    async def create_or_open_conversation_from_order(
        self, current_user: User, order_id: int
    ) -> ConversationDetailResponse:
        """
        Opens or creates the canonical Direct conversation between buyer and seller of an order.
        """
        conv = await self.repo.get_or_create_conversation_from_order(
            order_id=order_id, current_user_id=current_user.user_id
        )
        if not conv:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy đơn hàng hoặc bạn không có quyền truy cập.",
            )

        # Get other participant
        other_uid = conv.user_two_id if conv.user_one_id == current_user.user_id else conv.user_one_id
        other_user = await self.db.get(User, other_uid)
        part_summary = ParticipantSummary(
            user_id=other_uid,
            public_id=other_user.public_id if other_user else None,
            full_name=other_user.full_name if other_user else "Người dùng",
            avatar_url=other_user.avatar_url if other_user else None,
        )

        return ConversationDetailResponse(
            conversation_id=conv.conversation_id,
            type="DIRECT",
            other_participant=part_summary,
            created_at=conv.created_at,
        )

    async def create_or_open_direct_conversation(
        self,
        current_user: User,
        recipient_public_id: UUID,
    ) -> ConversationDetailResponse:
        """
        Opens or idempotently creates the canonical 1-to-1 Direct conversation
        with a recipient using client-facing recipient_public_id (UUID v4).
        """
        from app.modules.users.repository import UserRepository
        recipient = await UserRepository(self.db).get_by_public_id(recipient_public_id)

        if not recipient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Người dùng không tồn tại.",
            )

        if recipient.user_id == current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể tự nhắn tin cho chính mình.",
            )

        if recipient.status != UserStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tài khoản người dùng hiện không hoạt động.",
            )

        conv = await self.repo.get_or_create_direct_conversation(
            current_user.user_id, recipient.user_id
        )

        part_summary = ParticipantSummary(
            user_id=recipient.user_id,
            public_id=recipient.public_id,
            full_name=recipient.full_name,
            avatar_url=recipient.avatar_url,
        )


        return ConversationDetailResponse(
            conversation_id=conv.conversation_id,
            type="DIRECT",
            other_participant=part_summary,
            created_at=conv.created_at,
        )

    async def get_conversation(

        self, current_user: User, conversation_id: int
    ) -> ConversationDetailResponse:
        """
        Retrieves conversation detail with participant or group metadata.
        """
        conv, member = await self.repo.get_conversation_with_member(
            conversation_id, current_user.user_id
        )
        if not conv or not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )

        part_summary = None
        if conv.type == "DIRECT":
            other_uid = (
                conv.user_two_id
                if conv.user_one_id == current_user.user_id
                else conv.user_one_id
            )
            other_u = await self.db.get(User, other_uid)
            part_summary = ParticipantSummary(
                user_id=other_uid,
                public_id=other_u.public_id if other_u else None,
                full_name=other_u.full_name if other_u else "Người dùng",
                avatar_url=other_u.avatar_url if other_u else None,
            )

        # Count active members for GROUP
        member_count = None
        if conv.type == "GROUP":
            c_q = select(func.count(ConversationMember.user_id)).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.left_at.is_(None),
            )
            member_count = (await self.db.scalar(c_q)) or 0

        return ConversationDetailResponse(
            conversation_id=conv.conversation_id,
            type=conv.type,
            title=conv.title if conv.type != "DIRECT" else (part_summary.full_name if part_summary else None),
            description=conv.description,
            avatar_url=conv.avatar_url,
            other_participant=part_summary,
            member_count=member_count,
            my_role=member.role if member else None,
            is_joined=member is not None,
            created_at=conv.created_at,
            requires_approval=bool(conv.requires_approval) if conv.type == "GROUP" else False,
        )


    async def list_conversations(
        self,
        current_user: User,
        conv_type: Optional[str] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> ConversationListResponse:
        """Returns bounded paginated list of conversations for current user."""
        try:
            items, next_cursor, has_more, owned_group_count = await self.repo.list_user_conversations(
                current_user.user_id, conv_type=conv_type, limit=limit, cursor=cursor
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            )
        return ConversationListResponse(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            owned_group_count=owned_group_count,
        )

    async def get_owned_group_count(self, current_user: User) -> OwnedGroupSummaryResponse:
        """Returns truthful server-derived count of groups owned by current user."""
        count = await self.repo.get_user_owned_group_count(current_user.user_id)
        return OwnedGroupSummaryResponse(owned_group_count=count)

    async def get_messages(
        self,
        current_user: User,
        conversation_id: int,
        limit: int = 30,
        cursor: Optional[str] = None,
    ) -> MessageListResponse:
        """Returns bounded paginated messages for conversation."""
        conv, member = await self.repo.get_conversation_with_member(
            conversation_id, current_user.user_id
        )
        if not conv or not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )

        joined_at_filter = member.joined_at if (conv.type == "GROUP" and member) else None

        try:
            items, next_cursor, has_more = await self.repo.get_messages(
                conversation_id,
                limit=limit,
                cursor=cursor,
                current_user_id=current_user.user_id,
                joined_at_filter=joined_at_filter,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            )
        return MessageListResponse(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def send_message(
        self,
        current_user: User,
        conversation_id: int,
        content: Optional[str] = None,
        product_id: Optional[int] = None,
        files: Optional[List[UploadFile]] = None,
        voice_duration_ms: Optional[int] = None,
        mentions_data: Optional[List[dict]] = None,
        reply_to_message_id: Optional[int] = None,
    ) -> MessageResponse:
        """Validates content and attachments, uploads files safely, persists message, and emits realtime events."""
        conv, member = await self.repo.get_conversation_with_member(
            conversation_id, current_user.user_id
        )
        if not conv or not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )

        cleaned_content = content.strip() if content else None
        if cleaned_content == "":
            cleaned_content = None

        if cleaned_content and len(cleaned_content) > 2000:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Message content cannot exceed 2000 characters",
            )

        active_files = [f for f in (files or []) if f.filename]
        if len(active_files) > MAX_ATTACHMENTS_PER_MESSAGE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot attach more than {MAX_ATTACHMENTS_PER_MESSAGE} files per message.",
            )

        # Reject empty message
        if not cleaned_content and len(active_files) == 0 and product_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Message must contain text content or at least one attachment.",
            )

        # Early validation for voice_duration_ms
        if voice_duration_ms is not None:
            try:
                v_ms = int(voice_duration_ms)
                if v_ms > MAX_VOICE_DURATION_SECONDS * 1000:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Tin nhắn thoại vượt quá thời lượng tối đa 5 phút.",
                    )
            except (ValueError, TypeError):
                pass

        # Validate product_id: DIRECT only, must belong to one of the 2 participants
        if product_id is not None:
            if conv.type != "DIRECT":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Không thể gửi thẻ sản phẩm vào nhóm trò chuyện.",
                )

            prod_stmt = select(Product).where(
                Product.product_id == product_id,
                Product.is_deleted.is_(False),
            )
            product = await self.db.scalar(prod_stmt)
            if not product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Referenced product not found",
                )
            if product.seller_id not in (conv.user_one_id, conv.user_two_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Product does not belong to conversation participants",
                )

        # Validate reply_to_message_id: privacy-safe existence and scope check
        replied_msg = None
        if reply_to_message_id is not None:
            target_msg = await self.repo.get_message_by_id(reply_to_message_id)
            if not target_msg or target_msg.conversation_id != conversation_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Tin nhắn được trả lời không tồn tại hoặc không thể truy cập.",
                )
            if target_msg.type == "SYSTEM":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Không thể trả lời tin nhắn hệ thống.",
                )
            if target_msg.is_deleted:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Không thể trả lời tin nhắn đã bị xóa.",
                )
            replied_msg = target_msg

        # Read and validate files sequentially with memory limit
        validated_files_data = []
        total_attachments_size = 0

        for file in active_files:
            chunks = []
            total_read = 0
            chunk_size = 64 * 1024  # 64 KB

            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                total_read += len(chunk)
                if total_read > MAX_VIDEO_SIZE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Tệp {file.filename} vượt quá dung lượng tối đa cho phép.",
                    )
                chunks.append(chunk)

            file_bytes = b"".join(chunks)
            if len(file_bytes) == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Tệp {file.filename} rỗng.",
                )

            total_attachments_size += len(file_bytes)
            if total_attachments_size > MAX_TOTAL_ATTACHMENTS_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Tổng dung lượng các tệp đính kèm vượt quá giới hạn 60MB.",
                )

            # Detect and validate signature
            kind, mime_type = _validate_file_content_signature(
                file_bytes[:32], file.filename or "", file_bytes
            )

            # Enforce kind-specific size limits
            if kind == "IMAGE" and len(file_bytes) > MAX_IMAGE_SIZE_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Ảnh {file.filename} vượt quá giới hạn 10MB.",
                )
            elif (kind in ("PDF", "DOCUMENT")) and len(file_bytes) > MAX_DOCUMENT_SIZE_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Tài liệu {file.filename} vượt quá giới hạn 20MB.",
                )
            elif kind == "AUDIO" and len(file_bytes) > MAX_AUDIO_SIZE_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Tệp âm thanh {file.filename} vượt quá giới hạn 15MB.",
                )
            elif kind == "VIDEO" and len(file_bytes) > MAX_VIDEO_SIZE_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Video {file.filename} vượt quá giới hạn 50MB.",
                )

            validated_files_data.append((file, kind, mime_type, file_bytes))

        # Enforce video anti-spam rules before any Cloudinary upload
        video_count = sum(1 for _, kind, _, _ in validated_files_data if kind == "VIDEO")
        if video_count > settings.CHAT_MAX_VIDEOS_PER_MESSAGE:
            raise HTTPException(
                status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", status.HTTP_422_UNPROCESSABLE_ENTITY),
                detail=f"Mỗi tin nhắn chỉ được đính kèm tối đa {settings.CHAT_MAX_VIDEOS_PER_MESSAGE} video.",
            )

        if video_count > 0 and settings.RATE_LIMIT_ENABLED:
            allowed, retry_after = await check_chat_video_upload_quota(current_user.user_id)
            if not allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Bạn đã tải lên quá nhiều video trong thời gian ngắn. Vui lòng thử lại sau.",
                    headers={"Retry-After": str(retry_after)},
                )

        # Upload files sequentially and track for orphan cleanup
        uploaded_assets: List[Tuple[str, str]] = []
        attachments_data = []

        notif_snapshots: List[Tuple[int, NotificationResponse]] = []

        try:
            for file, kind, mime_type, file_bytes in validated_files_data:
                upload_res = upload_message_attachment(
                    file=file_bytes,
                    conversation_id=conversation_id,
                    kind=kind,
                    original_filename=file.filename or f"attachment_{kind.lower()}",
                )
                pub_id = upload_res.get("public_id")
                sec_url = upload_res.get("secure_url") or upload_res.get("url")
                res_type = _map_kind_to_resource_type(kind)
                uploaded_assets.append((pub_id, res_type))

                # Single recorded voice note check
                is_single_voice_note = (len(active_files) == 1 and kind == "AUDIO")

                # 1. Authoritative verification from provider (Cloudinary)
                duration_val = upload_res.get("duration")
                verified_duration_ms: Optional[int] = None
                if duration_val is not None:
                    try:
                        d_float = float(duration_val)
                        if d_float > MAX_VOICE_DURATION_SECONDS:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Tin nhắn thoại vượt quá thời lượng tối đa 5 phút.",
                            )
                        if d_float > 0:
                            verified_duration_ms = int(d_float * 1000)
                    except ValueError:
                        pass

                # 2. Client voice_duration_ms validation (only for single recorded voice note)
                if is_single_voice_note and voice_duration_ms is not None:
                    try:
                        v_ms = int(voice_duration_ms)
                        if v_ms > MAX_VOICE_DURATION_SECONDS * 1000:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Tin nhắn thoại vượt quá thời lượng tối đa 5 phút.",
                            )
                        if verified_duration_ms is None and v_ms > 0:
                            verified_duration_ms = v_ms
                    except (ValueError, TypeError):
                        pass

                attachments_data.append({
                    "kind": kind,
                    "url": sec_url,
                    "storage_key": pub_id,
                    "mime_type": mime_type,
                    "original_name": file.filename or f"attachment_{kind.lower()}",
                    "size_bytes": len(file_bytes),
                    "duration_ms": verified_duration_ms if kind == "AUDIO" else None,
                })

            try:
                msg = await self.repo.create_message(
                    conversation_id=conversation_id,
                    sender_id=current_user.user_id,
                    content=cleaned_content,
                    product_id=product_id,
                    attachments_data=attachments_data,
                    mentions_data=mentions_data,
                    reply_to_message_id=reply_to_message_id,
                )

                # Create/coalesce durable NEW_MESSAGE notifications in same transaction
                notifications_to_publish: List[Tuple[int, Notification]] = []

                if conv.type == "DIRECT":
                    recipient_id = conv.user_two_id if conv.user_one_id == current_user.user_id else conv.user_one_id
                    if recipient_id and recipient_id != current_user.user_id:
                        sender_name = current_user.full_name.strip() if (current_user.full_name and current_user.full_name.strip()) else "Một người dùng"
                        title = "Tin nhắn mới"
                        body = f"{sender_name} đã gửi tin nhắn cho bạn."

                        # Concurrency-safe advisory lock per (recipient_id, conversation_id)
                        await self.db.execute(
                            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                            {"lock_key": f"notif_chat:{recipient_id}:{conversation_id}"},
                        )

                        # Find existing unread chat notification for this conversation
                        stmt_existing = (
                            select(Notification)
                            .where(
                                Notification.user_id == recipient_id,
                                Notification.type == NotificationType.NEW_MESSAGE.value,
                                Notification.ref_type == "CONVERSATION",
                                Notification.ref_id == conversation_id,
                                Notification.is_read.is_(False),
                            )
                            .order_by(desc(Notification.notification_id))
                            .limit(1)
                            .with_for_update()
                        )
                        existing_notif = await self.db.scalar(stmt_existing)
                        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

                        if existing_notif:
                            existing_notif.title = title
                            existing_notif.body = body
                            existing_notif.created_at = now_utc
                            notifications_to_publish.append((recipient_id, existing_notif))
                        else:
                            new_notif = Notification(
                                user_id=recipient_id,
                                type=NotificationType.NEW_MESSAGE.value,
                                title=title,
                                body=body,
                                ref_type="CONVERSATION",
                                ref_id=conversation_id,
                                is_read=False,
                                created_at=now_utc,
                            )
                            self.db.add(new_notif)
                            notifications_to_publish.append((recipient_id, new_notif))

                elif conv.type == "GROUP" and msg.mentions:
                    # Derived canonically from persisted msg.mentions, excluding sender
                    valid_recipient_uids = list(dict.fromkeys(
                        m.mentioned_user_id
                        for m in msg.mentions
                        if m.mentioned_user_id != current_user.user_id
                    ))

                    group_title = conv.title.strip() if (conv.title and conv.title.strip()) else "một nhóm"
                    sender_name = current_user.full_name.strip() if (current_user.full_name and current_user.full_name.strip()) else "Một thành viên"
                    title = "Bạn được nhắc đến trong nhóm"
                    body = f"{sender_name} đã nhắc đến bạn trong {group_title}."
                    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

                    for target_uid in valid_recipient_uids:
                        await self.db.execute(
                            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                            {"lock_key": f"notif_chat:{target_uid}:{conversation_id}"},
                        )

                        stmt_existing = (
                            select(Notification)
                            .where(
                                Notification.user_id == target_uid,
                                Notification.type == NotificationType.NEW_MESSAGE.value,
                                Notification.ref_type == "CONVERSATION",
                                Notification.ref_id == conversation_id,
                                Notification.is_read.is_(False),
                            )
                            .order_by(desc(Notification.notification_id))
                            .limit(1)
                            .with_for_update()
                        )
                        existing_notif = await self.db.scalar(stmt_existing)

                        if existing_notif:
                            existing_notif.title = title
                            existing_notif.body = body
                            existing_notif.created_at = now_utc
                            notifications_to_publish.append((target_uid, existing_notif))
                        else:
                            new_notif = Notification(
                                user_id=target_uid,
                                type=NotificationType.NEW_MESSAGE.value,
                                title=title,
                                body=body,
                                ref_type="CONVERSATION",
                                ref_id=conversation_id,
                                is_read=False,
                                created_at=now_utc,
                            )
                            self.db.add(new_notif)
                            notifications_to_publish.append((target_uid, new_notif))

                if notifications_to_publish:
                    await self.db.flush()

                # Build immutable plain DTO snapshots before commit to prevent post-commit async ORM lazy-loading
                notif_snapshots = [
                    (uid, NotificationResponse.model_validate(n))
                    for uid, n in notifications_to_publish
                ]

                # Single atomic transaction commit for message, message_mentions, and mention notifications
                await self.db.commit()
            except ValueError as ve:
                err_msg = str(ve)
                if "NOT_ACTIVE_MEMBER" in err_msg:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Một số người dùng được gắn thẻ không còn là thành viên hoạt động trong nhóm.",
                    )
                if "NOT_ALLOWED_FOR_CONVERSATION_TYPE" in err_msg:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Tính năng gắn thẻ chỉ khả dụng trong nhóm và cộng đồng.",
                    )
                if "MENTION" in err_msg or "OFFSETS" in err_msg:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Vị trí gắn thẻ không khớp với nội dung tin nhắn.",
                    )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=err_msg,
                )
        except Exception as e:
            try:
                await self.db.rollback()
            except Exception as rb_err:
                logger.warning(f"Failed to rollback transaction in send_message: {rb_err}")
            # Cleanup any uploaded files on failure
            for pub_id, res_type in uploaded_assets:
                try:
                    destroy_asset(pub_id, resource_type=res_type)
                except Exception as cleanup_err:
                    logger.error(f"Failed to cleanup orphan asset {pub_id}: {cleanup_err}")
            if isinstance(e, HTTPException):
                raise e
            logger.error(f"Failed to process message creation: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to process message",
            ) from e

        # 1. Post-commit: safe attempt MESSAGE_CREATED to all active conversation members
        try:
            members_stmt = select(ConversationMember.user_id).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.left_at.is_(None),
            )
            active_member_uids = (await self.db.scalars(members_stmt)).all()
            event_data = {
                "type": "MESSAGE_CREATED",
                "conversation_id": conversation_id,
                "message_id": msg.message_id,
                "sender_id": current_user.user_id,
            }
            for uid in active_member_uids:
                try:
                    await publish_user_event(uid, event_data)
                except Exception as ws_err:
                    logger.warning(f"Failed to publish MESSAGE_CREATED to user {uid}: {ws_err}")
        except Exception as ws_err:
            logger.warning(f"Failed to publish MESSAGE_CREATED realtime event: {ws_err}")

        # 2. Post-commit: independently safe attempt NOTIFICATION_CREATED to each mentioned recipient
        for target_uid, notif_dto in notif_snapshots:
            await safe_publish_user_notification(target_uid, notif_dto)

        att_responses = [
            MessageAttachmentResponse(
                attachment_id=att.attachment_id,
                kind=att.kind,
                url=generate_delivery_url(
                    public_id=att.storage_key,
                    resource_type=_map_kind_to_resource_type(att.kind),
                    default_url=att.url,
                ),
                mime_type=att.mime_type,
                original_name=att.original_name,
                size_bytes=att.size_bytes,
                duration_ms=att.duration_ms,
            )
            for att in (msg.attachments or [])
        ]

        prod_ctx = None
        if msg.product:
            thumb = next((img.image_url for img in msg.product.images if img.is_thumbnail), None)
            if not thumb and msg.product.images:
                thumb = msg.product.images[0].image_url
            prod_ctx = ProductContextSummary(
                product_id=msg.product.product_id,
                title=msg.product.title,
                price=msg.product.price,
                status=msg.product.status.value if hasattr(msg.product.status, "value") else str(msg.product.status),
                thumbnail_url=thumb,
                listing_type=msg.product.listing_type.value if hasattr(msg.product.listing_type, "value") else str(msg.product.listing_type),
            )

        mentions_resp = [
            MessageMentionResponse(
                user_id=men.mentioned_user_id,
                display_name=men.mentioned_user.full_name if men.mentioned_user else men.display_text.lstrip("@"),
                display_text=men.display_text,
                start_offset=men.start_offset,
                end_offset=men.end_offset,
            )
            for men in (msg.mentions or [])
        ]

        return MessageResponse(
            message_id=msg.message_id,
            conversation_id=msg.conversation_id,
            sender_id=msg.sender_id,
            sender_public_id=current_user.public_id,
            sender_name=current_user.full_name,
            sender_avatar=current_user.avatar_url,
            type=msg.type,
            content=msg.content,
            product_id=msg.product_id,
            product=prod_ctx,
            sent_at=msg.sent_at,
            is_mine=True,
            is_deleted=False,
            attachments=att_responses,
            mentions=mentions_resp,
            reply_to=build_reply_summary(replied_msg) if replied_msg else None,
        )

    async def recall_message(
        self,
        current_user: User,
        conversation_id: int,
        message_id: int,
    ) -> MessageResponse:
        """
        Recalls a sender's own message from a conversation:
        1. Validates caller is active member of conversation.
        2. Validates message belongs to conversation, caller is sender, and type != SYSTEM.
        3. Idempotent: If already deleted, returns tombstone response immediately.
        4. Transactional DB commit: Enqueues media_cleanup_jobs and sets message.is_deleted = True, content = None.
        5. Post-commit: Immediate Cloudinary delete attempt; if success, removes cleanup job, otherwise worker retries.
        6. Post-commit: Emits MESSAGE_DELETED event via /ws/me to all active conversation members.
        7. Returns sanitized MessageResponse tombstone.
        """
        if current_user.status != UserStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tài khoản của bạn không ở trạng thái hoạt động.",
            )

        # 1. Authorization & access check
        conv, member = await self.repo.get_conversation_with_member(
            conversation_id, current_user.user_id
        )
        if not conv or not member or member.left_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tin nhắn không tồn tại hoặc bạn không có quyền truy cập.",
            )

        # 2. Lock & load target message
        msg = await self.repo.get_message_for_recall(conversation_id, message_id)
        if not msg or msg.conversation_id != conversation_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tin nhắn không tồn tại hoặc bạn không có quyền truy cập.",
            )

        # Non-sender cannot recall
        if msg.sender_id != current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chỉ người gửi mới có thể thu hồi tin nhắn.",
            )

        # System messages cannot be recalled
        if msg.type == "SYSTEM":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot recall system messages.",
            )

        # Idempotent return if already deleted
        if msg.is_deleted:
            return MessageResponse(
                message_id=msg.message_id,
                conversation_id=msg.conversation_id,
                sender_id=msg.sender_id,
                sender_public_id=current_user.public_id,
                sender_name=current_user.full_name,
                sender_avatar=current_user.avatar_url,
                type=msg.type,
                content=None,
                product_id=None,
                product=None,
                sent_at=msg.sent_at,
                is_mine=True,
                is_deleted=True,
                attachments=[],
                mentions=[],
                reactions=[],
                my_reaction=None,
                reply_to=build_reply_summary(msg.reply_to) if msg.reply_to_message_id else None,
            )

        # 3. Collect media cleanup jobs for any attachments
        cleanup_jobs: List[Tuple[str, str]] = []
        if msg.attachments:
            for att in msg.attachments:
                if att.storage_key:
                    res_type = _map_kind_to_resource_type(att.kind)
                    cleanup_jobs.append((att.storage_key, res_type))

        # 4. Atomic DB transaction: mark deleted + insert durable cleanup jobs + commit
        await self.repo.recall_message_in_db(msg, cleanup_jobs)

        # 5. Immediate post-commit Cloudinary destroy attempt off the event loop
        for storage_key, resource_type in cleanup_jobs:
            try:
                destroyed = await destroy_asset_async(storage_key, resource_type=resource_type)
                if destroyed:
                    await self.repo.delete_media_cleanup_job(storage_key, resource_type)
            except Exception as cleanup_err:
                logger.warning(
                    "Immediate Cloudinary destroy failed for %s (%s): %s. Will retry via worker.",
                    storage_key,
                    resource_type,
                    sanitize_external_error(cleanup_err),
                )

        # 6. Realtime invalidation signal to all active members
        try:
            members_stmt = select(ConversationMember.user_id).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.left_at.is_(None),
            )
            active_member_uids = (await self.db.scalars(members_stmt)).all()
            event_data = {
                "type": "MESSAGE_DELETED",
                "conversation_id": conversation_id,
                "message_id": message_id,
            }
            for uid in active_member_uids:
                try:
                    await publish_user_event(uid, event_data)
                except Exception as ws_err:
                    logger.warning(f"Failed to publish MESSAGE_DELETED to user {uid}: {ws_err}")
        except Exception as ws_err:
            logger.warning(f"Failed to publish MESSAGE_DELETED realtime event: {ws_err}")

        # 7. Sanitized tombstone response
        return MessageResponse(
            message_id=msg.message_id,
            conversation_id=msg.conversation_id,
            sender_id=msg.sender_id,
            sender_public_id=current_user.public_id,
            sender_name=current_user.full_name,
            sender_avatar=current_user.avatar_url,
            type=msg.type,
            content=None,
            product_id=None,
            product=None,
            sent_at=msg.sent_at,
            is_mine=True,
            is_deleted=True,
            attachments=[],
            mentions=[],
            reactions=[],
            my_reaction=None,
            reply_to=build_reply_summary(msg.reply_to) if msg.reply_to_message_id else None,
        )

    async def mark_as_read(
        self, current_user: User, conversation_id: int
    ) -> dict:
        """Advances reader's last_read_message_id in conversation."""
        conv, member = await self.repo.get_conversation_with_member(
            conversation_id, current_user.user_id
        )
        if not conv or not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cuộc trò chuyện không tồn tại.",
            )
        count = await self.repo.mark_as_read(conversation_id, current_user.user_id)
        return {"success": True, "read_count": count}

    # =========================================================================
    # Group Management Methods
    # =========================================================================

    async def create_group(
        self, current_user: User, payload: GroupCreateRequest
    ) -> ConversationDetailResponse:
        """Creates a new group conversation and emits group creation system message."""
        try:
            conv = await self.repo.create_group_conversation(
                owner_id=current_user.user_id,
                title=payload.title,
                description=payload.description,
                initial_invitee_ids=payload.initial_invitee_ids,
            )
        except ValueError as e:
            if "USER_GROUPS_CAP_EXCEEDED" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Bạn đã tạo tối đa 10 nhóm trò chuyện.",
                )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        # Insert SYSTEM message for group creation
        sys_msg = await self.repo.create_system_message(
            conversation_id=conv.conversation_id,
            sender_id=current_user.user_id,
            content=f"{current_user.full_name} đã tạo nhóm.",
        )
        await self.db.commit()

        # Realtime dispatch to creator
        try:
            await publish_user_event(
                current_user.user_id,
                {
                    "type": "MESSAGE_CREATED",
                    "conversation_id": conv.conversation_id,
                    "message_id": sys_msg.message_id,
                    "sender_id": current_user.user_id,
                },
            )
        except Exception as ws_err:
            logger.warning(f"Failed to publish MESSAGE_CREATED on group creation: {ws_err}")

        return ConversationDetailResponse(
            conversation_id=conv.conversation_id,
            type="GROUP",
            title=conv.title,
            description=conv.description,
            member_count=1,
            my_role="OWNER",
            is_joined=True,
            created_at=conv.created_at,
            requires_approval=bool(conv.requires_approval),
        )

    async def invite_members_to_group(
        self, current_user: User, conversation_id: int, invitee_ids: List[int]
    ) -> List[ConversationInviteResponse]:
        """Invites users to a group with atomic durable notification creation."""
        try:
            invites = await self.repo.create_invites(
                conversation_id=conversation_id,
                inviter_id=current_user.user_id,
                invitee_ids=invitee_ids,
            )

            # If all invitees were filtered (duplicate or already members), return empty without error
            if not invites:
                return []

            # Resolve group title for canonical notification and response
            conv_title = await self.db.scalar(
                select(Conversation.title).where(Conversation.conversation_id == conversation_id)
            )
            group_title = (conv_title or "Nhóm trò chuyện").strip()
            inviter_display = (current_user.full_name or "Người dùng").strip()

            # Create one durable SYSTEM notification for each actually created new invite
            notif_repo = NotificationRepository(self.db)
            created_notifications: List[Notification] = []
            for inv in invites:
                notif = await notif_repo.create(
                    user_id=inv.invitee_id,
                    type=NotificationType.SYSTEM.value,
                    title="Bạn có lời mời tham gia nhóm",
                    body=f"{inviter_display} đã mời bạn tham gia {group_title}.",
                    ref_type="GROUP_INVITE",
                    ref_id=inv.invite_id,
                )
                created_notifications.append(notif)

            if created_notifications:
                await self.db.flush()

            # Capture plain immutable snapshots before commit to prevent post-commit async ORM lazy-loading
            notif_snapshots = [
                (n.user_id, NotificationResponse.model_validate(n))
                for n in created_notifications
            ]
            invite_snapshots = [
                (inv.invite_id, inv.invitee_id)
                for inv in invites
            ]

            response_items = [
                ConversationInviteResponse(
                    invite_id=inv.invite_id,
                    conversation_id=inv.conversation_id,
                    conversation_title=group_title,
                    inviter_id=current_user.user_id,
                    inviter_name=current_user.full_name,
                    inviter_avatar=current_user.avatar_url,
                    status=inv.status,
                    created_at=inv.created_at,
                )
                for inv in invites
            ]

            # Service owns the single atomic transaction commit
            await self.db.commit()
        except PermissionError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chỉ chủ nhóm hoặc quản trị viên mới có quyền mời thành viên.",
            )
        except ValueError as e:
            if "GROUP_CAP_EXCEEDED" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Nhóm đã đạt giới hạn tối đa 50 thành viên.",
                )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        # Post-commit: isolated best-effort realtime events
        # 1. GROUP_INVITE_CREATED to each invitee
        for inv_id, invitee_id in invite_snapshots:
            try:
                await publish_user_event(
                    invitee_id,
                    {
                        "type": "GROUP_INVITE_CREATED",
                        "invite_id": inv_id,
                        "conversation_id": conversation_id,
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to publish GROUP_INVITE_CREATED to user {invitee_id}: {e}")

        # 2. NOTIFICATION_CREATED to each invitee (isolated per recipient)
        for target_uid, notif_dto in notif_snapshots:
            await safe_publish_user_notification(target_uid, notif_dto)

        return response_items

    async def list_user_invites(self, current_user: User) -> List[ConversationInviteResponse]:
        """Lists pending group invites for current user."""
        return await self.repo.list_user_invites(current_user.user_id)

    async def respond_to_invite(
        self, current_user: User, invite_id: int, action: str
    ) -> dict:
        """
        Accepts or declines a group invite.
        If requires_approval is ON and inviter is not OWNER: transitions to PENDING_APPROVAL.
        If requires_approval is OFF or inviter is OWNER: direct joins the group.
        """
        stmt = (
            select(ConversationInvite)
            .where(
                ConversationInvite.invite_id == invite_id,
                ConversationInvite.invitee_id == current_user.user_id,
            )
        )
        invite = await self.db.scalar(stmt)
        if not invite:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lời mời không tồn tại hoặc đã được xử lý.",
            )

        if invite.status != "PENDING":
            return {"success": True, "status": invite.status}

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        if action == "DECLINE":
            invite.status = "DECLINED"
            invite.responded_at = now
            await self.db.commit()
            return {"success": True, "status": "DECLINED"}

        # Action == ACCEPT
        conv = await self.repo.get_group_for_update(invite.conversation_id)
        if not conv or conv.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Nhóm trò chuyện không tồn tại hoặc đã bị giải tán.",
            )

        # Capacity check
        active_count = await self.repo.count_active_members(conv.conversation_id)
        if active_count >= 50:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nhóm đã đạt giới hạn tối đa 50 thành viên.",
            )

        # Check inviter role
        inviter_mem = await self.db.scalar(
            select(ConversationMember).where(
                ConversationMember.conversation_id == conv.conversation_id,
                ConversationMember.user_id == invite.inviter_id,
                ConversationMember.left_at.is_(None),
            )
        )
        is_trusted = (inviter_mem is not None and inviter_mem.role == "OWNER")

        if not conv.requires_approval or is_trusted:
            # Direct join
            invite.status = "ACCEPTED"
            invite.responded_at = now

            latest_msg_id = await self.repo.get_latest_message_id(conv.conversation_id)
            await self.repo.upsert_active_member(
                conversation_id=conv.conversation_id,
                user_id=current_user.user_id,
                role="MEMBER",
                latest_msg_id=latest_msg_id,
            )

            sys_msg = await self.repo.create_system_message(
                conversation_id=conv.conversation_id,
                sender_id=current_user.user_id,
                content=f"{current_user.full_name} đã tham gia nhóm.",
            )
            await self.db.commit()

            # Realtime to active members
            active_uids = (
                await self.db.scalars(
                    select(ConversationMember.user_id).where(
                        ConversationMember.conversation_id == conv.conversation_id,
                        ConversationMember.left_at.is_(None),
                    )
                )
            ).all()

            for uid in active_uids:
                await publish_user_event(
                    uid,
                    {
                        "type": "MESSAGE_CREATED",
                        "conversation_id": conv.conversation_id,
                        "message_id": sys_msg.message_id,
                        "sender_id": current_user.user_id,
                    },
                )
                await publish_user_event(
                    uid,
                    {
                        "type": "GROUP_MEMBERSHIP_CHANGED",
                        "conversation_id": conv.conversation_id,
                        "action": "MEMBER_JOINED",
                    },
                )

            return {"success": True, "status": "ACCEPTED"}
        else:
            # Transition to PENDING_APPROVAL
            invite.status = "PENDING_APPROVAL"
            invite.responded_at = now
            await self.db.commit()

            # Realtime to OWNER ONLY
            owner = await self.repo.get_active_owner(conv.conversation_id)
            if owner:
                try:
                    await publish_user_event(
                        owner.user_id,
                        {
                            "type": "GROUP_APPROVAL_REQUESTED",
                            "conversation_id": conv.conversation_id,
                            "invite_id": invite.invite_id,
                            "invitee_id": current_user.user_id,
                            "invitee_name": current_user.full_name,
                        },
                    )
                except Exception as ws_err:
                    logger.warning(f"Failed to publish GROUP_APPROVAL_REQUESTED: {ws_err}")

            return {"success": True, "status": "PENDING_APPROVAL"}

    async def list_group_members(
        self, current_user: User, conversation_id: int
    ) -> List[ConversationMemberResponse]:
        """Lists all active members in a group."""
        try:
            return await self.repo.list_group_members(conversation_id, current_user.user_id)
        except PermissionError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn phải là thành viên nhóm để xem danh sách thành viên.",
            )

    async def update_member_role(
        self, current_user: User, conversation_id: int, target_user_id: int, new_role: str
    ) -> dict:
        """Promotes or demotes a member's role (OWNER only)."""
        op_role = await self.db.scalar(
            select(ConversationMember.role).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == current_user.user_id,
                ConversationMember.left_at.is_(None),
            )
        )
        if op_role != "OWNER":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chỉ chủ nhóm mới có quyền thay đổi vai trò thành viên.",
            )

        if current_user.user_id == target_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể thay đổi vai trò của chính mình.",
            )

        target_mem = await self.repo.get_member_for_update(conversation_id, target_user_id)
        if not target_mem or target_mem.left_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Thành viên không tồn tại trong nhóm.",
            )

        old_role = target_mem.role
        if old_role == new_role:
            return {"success": True}

        target_user = await self.db.get(User, target_user_id)
        target_name = target_user.full_name if target_user else "Thành viên"

        target_mem.role = new_role

        if new_role == "ADMIN":
            sys_text = f"{current_user.full_name} đã bổ nhiệm {target_name} làm phó nhóm."
        else:
            sys_text = f"{current_user.full_name} đã gỡ quyền phó nhóm của {target_name}."

        sys_msg = await self.repo.create_system_message(
            conversation_id=conversation_id,
            sender_id=current_user.user_id,
            content=sys_text,
        )
        await self.db.commit()

        # Realtime dispatch
        active_uids = (
            await self.db.scalars(
                select(ConversationMember.user_id).where(
                    ConversationMember.conversation_id == conversation_id,
                    ConversationMember.left_at.is_(None),
                )
            )
        ).all()

        for uid in active_uids:
            await publish_user_event(
                uid,
                {
                    "type": "MESSAGE_CREATED",
                    "conversation_id": conversation_id,
                    "message_id": sys_msg.message_id,
                    "sender_id": current_user.user_id,
                },
            )
            await publish_user_event(
                uid,
                {
                    "type": "GROUP_MEMBERSHIP_CHANGED",
                    "conversation_id": conversation_id,
                    "action": "ROLE_UPDATED",
                },
            )

        return {"success": True}

    async def update_own_nickname(
        self,
        current_user: User,
        conversation_id: int,
        payload: GroupMemberNicknameUpdateRequest,
    ) -> ConversationMemberResponse:
        """
        Updates or clears the current authenticated user's nickname in a group.
        Self-scoped only: no user_id parameter allowed.
        """
        conv = await self.repo.get_conversation_by_id(conversation_id)
        if not conv or conv.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Nhóm không tồn tại hoặc đã bị giải tán.",
            )
        if conv.type != "GROUP":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tính năng biệt danh chỉ áp dụng cho nhóm trò chuyện.",
            )

        member = await self.repo.get_member_for_update(conversation_id, current_user.user_id)
        if not member or member.left_at is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không phải là thành viên hoạt động của nhóm này.",
            )

        # Validation & Normalization
        new_nickname: Optional[str] = None
        if payload.nickname is not None:
            trimmed = payload.nickname.strip()
            if trimmed:
                if len(trimmed) > 40:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Biệt danh không được vượt quá 40 ký tự.",
                    )
                # Reject newline, carriage return, tab, and C0/C1 control characters
                for char in trimmed:
                    code = ord(char)
                    if char in ('\n', '\r', '\t') or code < 32 or (127 <= code <= 159):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Biệt danh không được chứa ký tự điều khiển hoặc xuống dòng.",
                        )
                new_nickname = trimmed

        member.nickname = new_nickname
        await self.db.commit()
        await self.db.refresh(member)

        # Broadcast realtime best-effort (PostgreSQL is source of truth, failure does not rollback)
        try:
            active_uids = (
                await self.db.scalars(
                    select(ConversationMember.user_id).where(
                        ConversationMember.conversation_id == conversation_id,
                        ConversationMember.left_at.is_(None),
                    )
                )
            ).all()

            for uid in active_uids:
                try:
                    await publish_user_event(
                        uid,
                        {
                            "type": "GROUP_MEMBERSHIP_CHANGED",
                            "conversation_id": conversation_id,
                            "action": "NICKNAME_UPDATED",
                            "member_user_id": current_user.user_id,
                        },
                    )
                except Exception as ind_err:
                    logger.warning(
                        f"Failed to publish nickname update event to user {uid}: {ind_err}"
                    )
        except Exception as ws_err:
            logger.warning(
                f"Failed to query active members for nickname update event: {ws_err}"
            )

        # Return updated ConversationMemberResponse
        return ConversationMemberResponse(
            user_id=current_user.user_id,
            public_id=current_user.public_id,
            full_name=current_user.full_name,
            avatar_url=current_user.avatar_url,
            role=member.role,
            joined_at=member.joined_at,
            is_online=True,
            nickname=member.nickname,
        )


    async def transfer_ownership(
        self, current_user: User, conversation_id: int, new_owner_id: int
    ) -> dict:
        """Transfers group ownership to another active member (OWNER only)."""
        current_owner = await self.repo.get_member_for_update(conversation_id, current_user.user_id)
        if not current_owner or current_owner.left_at is not None or current_owner.role != "OWNER":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chỉ chủ nhóm mới có quyền chuyển nhượng quyền sở hữu.",
            )

        if current_user.user_id == new_owner_id:
            return {"success": True}

        target_mem = await self.repo.get_member_for_update(conversation_id, new_owner_id)
        if not target_mem or target_mem.left_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Thành viên được chuyển giao quyền không tồn tại trong nhóm.",
            )

        target_user = await self.db.get(User, new_owner_id)
        target_name = target_user.full_name if target_user else "Thành viên"

        # Verified behavior: old OWNER becomes MEMBER
        current_owner.role = "MEMBER"
        target_mem.role = "OWNER"

        sys_msg = await self.repo.create_system_message(
            conversation_id=conversation_id,
            sender_id=current_user.user_id,
            content=f"{current_user.full_name} đã chuyển quyền trưởng nhóm cho {target_name}.",
        )
        await self.db.commit()

        # Realtime dispatch to all active members
        active_uids = (
            await self.db.scalars(
                select(ConversationMember.user_id).where(
                    ConversationMember.conversation_id == conversation_id,
                    ConversationMember.left_at.is_(None),
                )
            )
        ).all()

        for uid in active_uids:
            await publish_user_event(
                uid,
                {
                    "type": "MESSAGE_CREATED",
                    "conversation_id": conversation_id,
                    "message_id": sys_msg.message_id,
                    "sender_id": current_user.user_id,
                },
            )
            await publish_user_event(
                uid,
                {
                    "type": "GROUP_MEMBERSHIP_CHANGED",
                    "conversation_id": conversation_id,
                    "action": "OWNER_TRANSFERRED",
                },
            )

        return {"success": True}

    async def remove_member(
        self, current_user: User, conversation_id: int, target_user_id: int
    ) -> dict:
        """Removes a member from the group (OWNER can remove anyone; ADMIN can remove MEMBER only)."""
        op_role = await self.db.scalar(
            select(ConversationMember.role).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == current_user.user_id,
                ConversationMember.left_at.is_(None),
            )
        )
        if op_role not in ("OWNER", "ADMIN"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền xóa thành viên này.",
            )

        if current_user.user_id == target_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể tự xóa chính mình, hãy sử dụng tính năng rời nhóm.",
            )

        target_mem = await self.repo.get_member_for_update(conversation_id, target_user_id)
        if not target_mem or target_mem.left_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Thành viên không tồn tại trong nhóm.",
            )

        if op_role == "ADMIN" and target_mem.role in ("OWNER", "ADMIN"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Phó nhóm không thể xóa trưởng nhóm hoặc phó nhóm khác.",
            )

        target_user = await self.db.get(User, target_user_id)
        target_name = target_user.full_name if target_user else "Thành viên"

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        target_mem.left_at = now

        sys_msg = await self.repo.create_system_message(
            conversation_id=conversation_id,
            sender_id=current_user.user_id,
            content=f"{current_user.full_name} đã xóa {target_name} khỏi nhóm.",
        )
        await self.db.commit()

        # Realtime dispatch (best effort delivery after DB commit)
        try:
            remaining_uids = (
                await self.db.scalars(
                    select(ConversationMember.user_id).where(
                        ConversationMember.conversation_id == conversation_id,
                        ConversationMember.left_at.is_(None),
                    )
                )
            ).all()

            for uid in remaining_uids:
                await publish_user_event(
                    uid,
                    {
                        "type": "MESSAGE_CREATED",
                        "conversation_id": conversation_id,
                        "message_id": sys_msg.message_id,
                        "sender_id": current_user.user_id,
                    },
                )
                await publish_user_event(
                    uid,
                    {
                        "type": "GROUP_MEMBERSHIP_CHANGED",
                        "conversation_id": conversation_id,
                        "action": "MEMBER_REMOVED",
                    },
                )

            # Target user receives direct revocation event (no MESSAGE_CREATED!)
            await publish_user_event(
                target_user_id,
                {
                    "type": "GROUP_MEMBERSHIP_CHANGED",
                    "conversation_id": conversation_id,
                    "action": "REMOVED",
                },
            )
        except Exception as ws_err:
            logger.warning(
                f"Failed to publish group member removal realtime events: {ws_err}"
            )

        return {"success": True}

    async def leave_group(self, current_user: User, conversation_id: int) -> dict:
        """Leaves a group conversation."""
        mem = await self.repo.get_member_for_update(conversation_id, current_user.user_id)
        if not mem or mem.left_at is not None:
            return {"success": True}

        if mem.role == "OWNER":
            other_active_count = await self.db.scalar(
                select(func.count(ConversationMember.user_id)).where(
                    ConversationMember.conversation_id == conversation_id,
                    ConversationMember.left_at.is_(None),
                    ConversationMember.user_id != current_user.user_id,
                )
            )
            if other_active_count and other_active_count > 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Chủ nhóm phải chuyển quyền sở hữu cho thành viên khác trước khi rời nhóm.",
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Bạn là thành viên duy nhất, vui lòng sử dụng tính năng giải tán nhóm.",
                )

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        mem.left_at = now

        sys_msg = await self.repo.create_system_message(
            conversation_id=conversation_id,
            sender_id=current_user.user_id,
            content=f"{current_user.full_name} đã rời khỏi nhóm.",
        )
        await self.db.commit()

        # Realtime dispatch (best effort delivery after DB commit)
        try:
            remaining_uids = (
                await self.db.scalars(
                    select(ConversationMember.user_id).where(
                        ConversationMember.conversation_id == conversation_id,
                        ConversationMember.left_at.is_(None),
                    )
                )
            ).all()

            for uid in remaining_uids:
                await publish_user_event(
                    uid,
                    {
                        "type": "MESSAGE_CREATED",
                        "conversation_id": conversation_id,
                        "message_id": sys_msg.message_id,
                        "sender_id": current_user.user_id,
                    },
                )
                await publish_user_event(
                    uid,
                    {
                        "type": "GROUP_MEMBERSHIP_CHANGED",
                        "conversation_id": conversation_id,
                        "action": "MEMBER_LEFT",
                    },
                )

            # Event for user who left
            await publish_user_event(
                current_user.user_id,
                {
                    "type": "GROUP_MEMBERSHIP_CHANGED",
                    "conversation_id": conversation_id,
                    "action": "LEFT",
                },
            )
        except Exception as ws_err:
            logger.warning(
                f"Failed to publish group member leave realtime events: {ws_err}"
            )

        return {"success": True}

    async def update_group_metadata(
        self, current_user: User, conversation_id: int, payload: GroupUpdateRequest
    ) -> ConversationDetailResponse:
        """Updates group title, description, and/or requires_approval setting."""
        op_role = await self.db.scalar(
            select(ConversationMember.role).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == current_user.user_id,
                ConversationMember.left_at.is_(None),
            )
        )
        if not op_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không phải thành viên của nhóm.",
            )

        if payload.requires_approval is not None and op_role != "OWNER":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chỉ trưởng nhóm mới có quyền thay đổi cài đặt phê duyệt thành viên.",
            )

        if (payload.title is not None or payload.description is not None) and op_role not in ("OWNER", "ADMIN"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chỉ chủ nhóm hoặc quản trị viên mới có quyền cập nhật thông tin nhóm.",
            )

        conv = await self.repo.get_group_for_update(conversation_id)
        if not conv or conv.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Nhóm trò chuyện không tồn tại.",
            )
        if conv.type != "GROUP":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chỉ có thể cập nhật nhóm trò chuyện.",
            )

        sys_msgs = []

        # requires_approval toggle
        if payload.requires_approval is not None and conv.requires_approval != payload.requires_approval:
            conv.requires_approval = payload.requires_approval
            if payload.requires_approval:
                txt = f"{current_user.full_name} đã bật tính năng phê duyệt thành viên mới."
            else:
                txt = f"{current_user.full_name} đã tắt tính năng phê duyệt thành viên mới."
            sys_msgs.append(await self.repo.create_system_message(conversation_id, current_user.user_id, txt))

        # Title change
        if payload.title is not None:
            new_title = payload.title.strip()
            if conv.title != new_title:
                conv.title = new_title
                sys_msgs.append(
                    await self.repo.create_system_message(
                        conversation_id, current_user.user_id, f'{current_user.full_name} đã đổi tên nhóm thành "{conv.title}".'
                    )
                )

        # Description change
        if payload.description is not None:
            new_desc = payload.description.strip() if payload.description else None
            if conv.description != new_desc:
                conv.description = new_desc
                sys_msgs.append(
                    await self.repo.create_system_message(
                        conversation_id, current_user.user_id, f"{current_user.full_name} đã cập nhật mô tả nhóm."
                    )
                )

        await self.db.commit()

        # Realtime dispatch
        if sys_msgs:
            active_uids = (
                await self.db.scalars(
                    select(ConversationMember.user_id).where(
                        ConversationMember.conversation_id == conversation_id,
                        ConversationMember.left_at.is_(None),
                    )
                )
            ).all()

            for m in sys_msgs:
                for uid in active_uids:
                    await publish_user_event(
                        uid,
                        {
                            "type": "MESSAGE_CREATED",
                            "conversation_id": conversation_id,
                            "message_id": m.message_id,
                            "sender_id": current_user.user_id,
                        },
                    )

        member_count = await self.repo.count_active_members(conversation_id)

        return ConversationDetailResponse(
            conversation_id=conv.conversation_id,
            type=conv.type,
            title=conv.title,
            description=conv.description,
            avatar_url=conv.avatar_url,
            member_count=member_count,
            my_role=op_role,
            is_joined=True,
            created_at=conv.created_at,
            requires_approval=bool(conv.requires_approval),
        )

    async def list_pending_approvals(
        self, current_user: User, conversation_id: int
    ) -> PendingApprovalListResponse:
        """Lists pending join requests for a group (OWNER only)."""
        op_role = await self.db.scalar(
            select(ConversationMember.role).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == current_user.user_id,
                ConversationMember.left_at.is_(None),
            )
        )
        if op_role != "OWNER":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chỉ trưởng nhóm mới có quyền xem danh sách chờ phê duyệt.",
            )

        invites = await self.repo.list_pending_approvals(conversation_id)

        items = [
            PendingApprovalItem(
                invite_id=inv.invite_id,
                conversation_id=inv.conversation_id,
                invitee_id=inv.invitee_id,
                invitee_name=inv.invitee.full_name if inv.invitee else "Người dùng",
                invitee_avatar=inv.invitee.avatar_url if inv.invitee else None,
                inviter_id=inv.inviter_id,
                inviter_name=inv.inviter.full_name if inv.inviter else "Người dùng",
                inviter_avatar=inv.inviter.avatar_url if inv.inviter else None,
                created_at=inv.created_at,
                responded_at=inv.responded_at,
            )
            for inv in invites
        ]

        return PendingApprovalListResponse(items=items)

    async def process_pending_approval(
        self, current_user: User, conversation_id: int, invite_id: int, action: str
    ) -> dict:
        """Processes (APPROVE or REJECT) a pending join request (OWNER only)."""
        op_role = await self.db.scalar(
            select(ConversationMember.role).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == current_user.user_id,
                ConversationMember.left_at.is_(None),
            )
        )
        if op_role != "OWNER":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chỉ trưởng nhóm mới có quyền phê duyệt thành viên.",
            )

        invite = await self.repo.get_invite_for_update(invite_id)
        if not invite or invite.conversation_id != conversation_id or invite.status != "PENDING_APPROVAL":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Yêu cầu phê duyệt không tồn tại hoặc đã được xử lý.",
            )

        if action == "REJECT":
            invite.status = "DECLINED"
            await self.db.commit()

            # Realtime to target invitee only (Guardrail 3)
            try:
                await publish_user_event(
                    invite.invitee_id,
                    {
                        "type": "GROUP_INVITE_UPDATED",
                        "invite_id": invite.invite_id,
                        "conversation_id": conversation_id,
                        "status": "DECLINED",
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to publish GROUP_INVITE_UPDATED: {e}")

            return {"success": True, "status": "DECLINED"}

        # Action == APPROVE
        conv = await self.repo.get_group_for_update(conversation_id)
        if not conv or conv.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Nhóm trò chuyện không tồn tại hoặc đã bị giải tán.",
            )

        active_count = await self.repo.count_active_members(conversation_id)
        if active_count >= 50:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nhóm đã đạt giới hạn tối đa 50 thành viên.",
            )

        # Requirement L: Stale pending target already active member
        existing_active = await self.db.scalar(
            select(ConversationMember).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == invite.invitee_id,
                ConversationMember.left_at.is_(None),
            )
        )
        if existing_active:
            invite.status = "ACCEPTED"
            await self.db.commit()
            try:
                await publish_user_event(
                    invite.invitee_id,
                    {
                        "type": "GROUP_INVITE_UPDATED",
                        "invite_id": invite.invite_id,
                        "conversation_id": conversation_id,
                        "status": "ACCEPTED",
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to publish GROUP_INVITE_UPDATED: {e}")
            return {"success": True, "status": "ACCEPTED", "already_active": True}

        # Normal approve
        invite.status = "ACCEPTED"
        latest_msg_id = await self.repo.get_latest_message_id(conversation_id)
        await self.repo.upsert_active_member(
            conversation_id=conversation_id,
            user_id=invite.invitee_id,
            role="MEMBER",
            latest_msg_id=latest_msg_id,
        )

        invitee_name = invite.invitee.full_name if invite.invitee else "Thành viên"
        sys_msg = await self.repo.create_system_message(
            conversation_id=conversation_id,
            sender_id=current_user.user_id,
            content=f"{current_user.full_name} đã phê duyệt {invitee_name} vào nhóm.",
        )
        await self.db.commit()

        # Realtime dispatch
        active_uids = (
            await self.db.scalars(
                select(ConversationMember.user_id).where(
                    ConversationMember.conversation_id == conversation_id,
                    ConversationMember.left_at.is_(None),
                )
            )
        ).all()

        for uid in active_uids:
            await publish_user_event(
                uid,
                {
                    "type": "MESSAGE_CREATED",
                    "conversation_id": conversation_id,
                    "message_id": sys_msg.message_id,
                    "sender_id": current_user.user_id,
                },
            )
            await publish_user_event(
                uid,
                {
                    "type": "GROUP_MEMBERSHIP_CHANGED",
                    "conversation_id": conversation_id,
                    "action": "MEMBER_JOINED",
                },
            )

        try:
            await publish_user_event(
                invite.invitee_id,
                {
                    "type": "GROUP_INVITE_UPDATED",
                    "invite_id": invite.invite_id,
                    "conversation_id": conversation_id,
                    "status": "ACCEPTED",
                },
            )
        except Exception as e:
            logger.warning(f"Failed to publish GROUP_INVITE_UPDATED: {e}")

        return {"success": True, "status": "ACCEPTED"}

    # =========================================================================
    # Official Support Group Methods
    # =========================================================================

    async def get_official_support_group(
        self, current_user: User
    ) -> OfficialSupportGroupResponse:
        """
        Resolves the configured official support GROUP and returns its metadata for the special entry.
        Read-only, never mutates membership.
        """
        support_id = settings.OFFICIAL_SUPPORT_GROUP_ID
        if not support_id or support_id <= 0:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Nhóm hỗ trợ chính thức chưa được cấu hình.",
            )

        conv = await self.repo.get_conversation_by_id(support_id)
        if not conv or conv.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Nhóm hỗ trợ chính thức không tồn tại.",
            )

        if conv.type != "GROUP":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Nhóm hỗ trợ chính thức có loại không hợp lệ.",
            )

        member = await self.repo.get_active_group_member(conv.conversation_id, current_user.user_id)
        is_member = member is not None

        last_preview = conv.description
        last_dt = conv.last_message_at
        unread = 0

        stmt_last_msg = (
            select(Message.content, Message.sent_at)
            .where(
                Message.conversation_id == conv.conversation_id,
                Message.is_deleted.is_(False),
            )
            .order_by(Message.sent_at.desc(), Message.message_id.desc())
            .limit(1)
        )
        last_msg_row = (await self.db.execute(stmt_last_msg)).first()
        if last_msg_row:
            last_preview = last_msg_row[0]
            last_dt = last_msg_row[1]

        if is_member and member:
            if member.last_read_message_id:
                stmt_unread = select(func.count(Message.message_id)).where(
                    Message.conversation_id == conv.conversation_id,
                    Message.message_id > member.last_read_message_id,
                    Message.sender_id != current_user.user_id,
                    Message.is_deleted.is_(False),
                )
                unread = (await self.db.scalar(stmt_unread)) or 0
            elif conv.last_message_at:
                stmt_unread = select(func.count(Message.message_id)).where(
                    Message.conversation_id == conv.conversation_id,
                    Message.sender_id != current_user.user_id,
                    Message.is_deleted.is_(False),
                )
                unread = (await self.db.scalar(stmt_unread)) or 0

        return OfficialSupportGroupResponse(
            conversation_id=conv.conversation_id,
            title=conv.title or "Cộng đồng Chợ PTITers",
            description=conv.description,
            is_member=is_member,
            last_message_preview=last_preview,
            last_message_at=last_dt,
            unread_count=unread,
        )

    async def join_official_support_group(self, current_user: User) -> dict:
        """
        Resolves the configured official support GROUP and joins current user idempotently.
        """
        support_id = settings.OFFICIAL_SUPPORT_GROUP_ID
        if not support_id or support_id <= 0:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Nhóm hỗ trợ chính thức chưa được cấu hình.",
            )

        conv = await self.repo.get_conversation_by_id(support_id)
        if not conv or conv.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Nhóm hỗ trợ chính thức không tồn tại.",
            )

        if conv.type != "GROUP":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nhóm hỗ trợ chính thức có loại không hợp lệ.",
            )

        await self.repo.join_support_group(conv.conversation_id, current_user.user_id)
        return {"conversation_id": conv.conversation_id}

    # =========================================================================
    # User Search
    # =========================================================================

    async def search_users(
        self,
        current_user: User,
        query: str,
        limit: int = 20,
        conversation_id: Optional[int] = None,
    ) -> List[UserSearchResponse]:
        """Searches users for group invitations."""
        return await self.repo.search_users(
            query=query,
            limit=limit,
            exclude_user_id=current_user.user_id,
            exclude_conversation_id=conversation_id,
        )

    # =========================================================================
    # Phase 7C: Shared Media, Attachments, Presence, and Group Deletion
    # =========================================================================

    async def delete_group(
        self, current_user: User, conversation_id: int
    ) -> dict:
        """Soft-deletes a regular group conversation (OWNER only)."""
        try:
            await self.repo.delete_group_conversation(conversation_id, current_user.user_id)
        except PermissionError as pe:
            if "CANNOT_DELETE_OFFICIAL_SUPPORT_GROUP" in str(pe):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Không thể xóa nhóm hỗ trợ chính thức.",
                )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chỉ trưởng nhóm mới có quyền xóa nhóm này.",
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Nhóm không tồn tại hoặc đã bị xóa.",
            )
        return {"success": True, "message": "Nhóm đã được xóa thành công."}

    async def get_shared_attachments(
        self,
        current_user: User,
        conversation_id: int,
        category: str,
        limit: int = 30,
        cursor: Optional[str] = None,
    ) -> SharedAttachmentListResponse:
        """Fetches cursor-paginated shared attachments for active members."""
        conv, member = await self.repo.get_conversation_with_member(
            conversation_id, current_user.user_id
        )
        if not conv or not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cuộc trò chuyện không tồn tại hoặc bạn không có quyền truy cập.",
            )

        joined_at_filter = member.joined_at if (conv.type == "GROUP" and member) else None
        try:
            items, next_cursor, has_more = await self.repo.get_shared_attachments(
                conversation_id=conversation_id,
                category=category,
                limit=limit,
                cursor=cursor,
                joined_at_filter=joined_at_filter,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        return SharedAttachmentListResponse(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def get_shared_attachments_summary(
        self,
        current_user: User,
        conversation_id: int,
    ) -> SharedAttachmentSummaryResponse:
        """Counts shared media, audio, and documents in conversation."""
        conv, member = await self.repo.get_conversation_with_member(
            conversation_id, current_user.user_id
        )
        if not conv or not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cuộc trò chuyện không tồn tại hoặc bạn không có quyền truy cập.",
            )

        joined_at_filter = member.joined_at if (conv.type == "GROUP" and member) else None
        summary = await self.repo.get_shared_attachments_summary(
            conversation_id=conversation_id,
            joined_at_filter=joined_at_filter,
        )
        return SharedAttachmentSummaryResponse(**summary)

    async def get_conversation_presence(
        self,
        current_user: User,
        conversation_id: int,
    ) -> PresenceBatchResponse:
        """Batch queries presence for active members of this conversation."""
        conv, member = await self.repo.get_conversation_with_member(
            conversation_id, current_user.user_id
        )
        if not conv or not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cuộc trò chuyện không tồn tại hoặc bạn không có quyền truy cập.",
            )

        stmt = select(ConversationMember.user_id).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.left_at.is_(None),
        )
        member_ids = list((await self.repo.db.scalars(stmt)).all())
        avail, online_ids = await get_users_presence(member_ids)
        return PresenceBatchResponse(
            presence_available=avail,
            online_user_ids=sorted(list(online_ids)),
        )

    async def get_invite_candidates(
        self,
        current_user: User,
        conversation_id: int,
        query: Optional[str] = None,
        limit: int = 20,
    ) -> InviteCandidateListResponse:
        """
        Lists eligible invite candidates from caller's previous Direct interactions.
        """
        try:
            items = await self.repo.get_invite_candidates(
                group_id=conversation_id,
                inviter_id=current_user.user_id,
                query=query,
                limit=limit,
            )
            return InviteCandidateListResponse(items=items)
        except PermissionError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn phải là thành viên nhóm để xem danh sách gợi ý mời.",
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    async def create_download_ticket(
        self,
        current_user: User,
        conversation_id: int,
        attachment_id: int,
    ) -> AttachmentDownloadTicketResponse:
        """
        Creates a short-lived (60s), single-use opaque download ticket stored in Redis.
        Caller must be an active member of the conversation.
        """
        conv, member = await self.repo.get_conversation_with_member(
            conversation_id, current_user.user_id
        )
        if not conv or not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cuộc trò chuyện không tồn tại hoặc bạn không có quyền truy cập.",
            )

        att = await self.repo.get_attachment_by_id_and_conversation(
            conversation_id, attachment_id
        )
        if not att:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tệp đính kèm không tồn tại.",
            )

        if (
            conv.type == "GROUP"
            and member
            and ensure_utc_aware(att.created_at) < ensure_utc_aware(member.joined_at)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tệp đính kèm không tồn tại hoặc bạn không có quyền truy cập.",
            )

        rc = get_redis_client()
        if rc is None:
            rc = await get_or_reconnect_redis()
        if rc is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Dịch vụ tải xuống tạm thời không khả dụng. Vui lòng thử lại sau.",
            )

        ticket = secrets.token_urlsafe(32)
        ticket_hash = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
        redis_key = f"download_ticket:{ticket_hash}"
        payload = json.dumps({
            "user_id": current_user.user_id,
            "conversation_id": conversation_id,
            "attachment_id": attachment_id,
        })
        try:
            await rc.set(redis_key, payload, ex=60)
        except Exception as e:
            logger.error(f"Failed to store download ticket in Redis: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Dịch vụ tải xuống tạm thời không khả dụng. Vui lòng thử lại sau.",
            ) from e

        return AttachmentDownloadTicketResponse(
            ticket=ticket,
            download_url=f"/api/v1/conversations/{conversation_id}/attachments/{attachment_id}/download?ticket={ticket}",
            expires_in_seconds=60,
        )

    async def consume_download_ticket(
        self,
        conversation_id: int,
        attachment_id: int,
        ticket: str,
    ) -> int:
        """
        Atomically consumes a single-use download ticket from Redis.
        Returns the bound user_id.
        """
        if not ticket or not isinstance(ticket, str):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Mã tải xuống không hợp lệ.",
            )

        rc = get_redis_client()
        if rc is None:
            rc = await get_or_reconnect_redis()
        if rc is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Dịch vụ tải xuống tạm thời không khả dụng. Vui lòng thử lại sau.",
            )

        ticket_hash = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
        redis_key = f"download_ticket:{ticket_hash}"
        try:
            raw = await rc.getdel(redis_key)
        except Exception:
            try:
                pipe = rc.pipeline()
                pipe.get(redis_key)
                pipe.delete(redis_key)
                results = await pipe.execute()
                raw = results[0]
            except Exception as e:
                logger.error(f"Failed to read/delete ticket from Redis: {e}")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Dịch vụ tải xuống tạm thời không khả dụng. Vui lòng thử lại sau.",
                ) from e

        if not raw:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Mã tải xuống không hợp lệ, đã hết hạn hoặc đã được sử dụng.",
            )

        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            data = json.loads(raw)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Mã tải xuống không hợp lệ.",
            )

        if data.get("conversation_id") != conversation_id or data.get("attachment_id") != attachment_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Mã tải xuống không khớp với tệp đính kèm này.",
            )

        user_id = data.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Mã tải xuống không hợp lệ.",
            )
        return int(user_id)

    async def authorize_and_get_attachment_metadata(
        self,
        user_id: int,
        conversation_id: int,
        attachment_id: int,
    ) -> DownloadAttachmentMetadata:
        """
        Re-verifies CURRENT membership for user_id at the moment of download,
        verifies attachment belongs to the conversation, enforces group joined_at privacy,
        validates SSRF safety, and returns trusted metadata.
        """
        conv, member = await self.repo.get_conversation_with_member(
            conversation_id, user_id
        )
        if not conv or not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cuộc trò chuyện không tồn tại hoặc bạn không có quyền truy cập.",
            )

        att = await self.repo.get_attachment_by_id_and_conversation(
            conversation_id, attachment_id
        )
        if not att:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tệp đính kèm không tồn tại.",
            )

        if (
            conv.type == "GROUP"
            and member
            and ensure_utc_aware(att.created_at) < ensure_utc_aware(member.joined_at)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tệp đính kèm không tồn tại hoặc bạn không có quyền truy cập.",
            )

        validate_storage_url_safety(att.url)

        return DownloadAttachmentMetadata(
            attachment_id=att.attachment_id,
            original_name=att.original_name,
            mime_type=att.mime_type,
            size_bytes=att.size_bytes,
            kind=att.kind,
            target_url=att.url,
        )

    async def _authorize_reaction_access(
        self,
        current_user: User,
        conversation_id: int,
        message_id: int,
    ) -> Tuple[Conversation, Message]:
        """
        Enforces canonical reaction authorization:
        - Conversation must exist.
        - DIRECT: user must be user_one_id or user_two_id (no conversation_members row required).
        - GROUP: user must be active member (left_at is None).
        - Message: must belong to conversation_id, not deleted, type != 'SYSTEM',
                   and for GROUP must not precede user's joined_at.
        All forbidden / non-existent lookups return 404 to avoid leaking existence.
        """
        conv = await self.repo.get_conversation_by_id(conversation_id)
        if not conv:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cuộc trò chuyện không tồn tại hoặc bạn không có quyền truy cập.",
            )

        joined_at_filter = None
        if conv.type == "DIRECT":
            if current_user.user_id not in (conv.user_one_id, conv.user_two_id):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Cuộc trò chuyện không tồn tại hoặc bạn không có quyền truy cập.",
                )
        elif conv.type == "GROUP":
            member = await self.repo.get_active_group_member(conversation_id, current_user.user_id)
            if not member:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Cuộc trò chuyện không tồn tại hoặc bạn không có quyền truy cập.",
                )
            joined_at_filter = member.joined_at
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Loại cuộc trò chuyện không hỗ trợ bày tỏ cảm xúc.",
            )

        msg = await self.repo.get_message_by_id_and_conversation(conversation_id, message_id)
        if not msg or msg.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tin nhắn không tồn tại.",
            )

        if (
            conv.type == "GROUP"
            and joined_at_filter
            and ensure_utc_aware(msg.sent_at) < ensure_utc_aware(joined_at_filter)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tin nhắn không tồn tại hoặc bạn không có quyền truy cập.",
            )

        if msg.type == "SYSTEM":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể bày tỏ cảm xúc cho tin nhắn hệ thống.",
            )

        return conv, msg

    async def _get_conversation_recipient_uids(self, conv: Conversation) -> List[int]:
        """Returns all eligible recipient user IDs for realtime message reaction delivery."""
        if conv.type == "DIRECT":
            return [uid for uid in (conv.user_one_id, conv.user_two_id) if uid is not None]
        elif conv.type == "GROUP":
            stmt = select(ConversationMember.user_id).where(
                ConversationMember.conversation_id == conv.conversation_id,
                ConversationMember.left_at.is_(None),
            )
            res = await self.db.scalars(stmt)
            return list(res.all())
        return []

    async def set_message_reaction(
        self,
        current_user: User,
        conversation_id: int,
        message_id: int,
        payload: MessageReactionSetRequest,
    ) -> MessageReactionSummaryResponse:
        """Sets or switches authenticated user's reaction, flushes, builds summary, commits, and emits realtime."""
        conv, msg = await self._authorize_reaction_access(current_user, conversation_id, message_id)
        reaction_key = payload.reaction_key.value

        await self.repo.set_reaction(message_id, current_user.user_id, reaction_key)
        await self.db.flush()

        # Build response before commit so post-commit query failure risk is eliminated
        summary = await self.repo.get_reaction_summary(message_id, current_user.user_id)
        # Pre-resolve recipient IDs before commit to avoid accessing expired model attributes post-commit
        recipient_uids = await self._get_conversation_recipient_uids(conv)
        await self.db.commit()

        # Post-commit best-effort realtime fanout via existing /ws/me
        try:
            event_payload = {
                "type": "MESSAGE_REACTIONS_UPDATED",
                "conversation_id": conversation_id,
                "message_id": message_id,
                "reactions": [r.model_dump() for r in summary.reactions],
                "actor_user_id": current_user.user_id,
                "actor_reaction": reaction_key,
            }
            for uid in recipient_uids:
                try:
                    await publish_user_event(uid, event_payload)
                except Exception as ws_err:
                    logger.warning(f"Failed to publish MESSAGE_REACTIONS_UPDATED to {uid}: {ws_err}")
        except Exception as fanout_err:
            logger.warning(f"Failed in realtime fanout for reaction set: {fanout_err}")

        return summary

    async def remove_message_reaction(
        self,
        current_user: User,
        conversation_id: int,
        message_id: int,
    ) -> MessageReactionSummaryResponse:
        """Idempotently removes user's reaction, flushes, builds summary, commits, and emits realtime."""
        conv, msg = await self._authorize_reaction_access(current_user, conversation_id, message_id)

        await self.repo.remove_reaction(message_id, current_user.user_id)
        await self.db.flush()

        summary = await self.repo.get_reaction_summary(message_id, current_user.user_id)
        # Pre-resolve recipient IDs before commit to avoid accessing expired model attributes post-commit
        recipient_uids = await self._get_conversation_recipient_uids(conv)
        await self.db.commit()

        # Post-commit best-effort realtime fanout via existing /ws/me
        try:
            event_payload = {
                "type": "MESSAGE_REACTIONS_UPDATED",
                "conversation_id": conversation_id,
                "message_id": message_id,
                "reactions": [r.model_dump() for r in summary.reactions],
                "actor_user_id": current_user.user_id,
                "actor_reaction": None,
            }
            for uid in recipient_uids:
                try:
                    await publish_user_event(uid, event_payload)
                except Exception as ws_err:
                    logger.warning(f"Failed to publish MESSAGE_REACTIONS_UPDATED removal to {uid}: {ws_err}")
        except Exception as fanout_err:
            logger.warning(f"Failed in realtime fanout for reaction remove: {fanout_err}")

        return summary



