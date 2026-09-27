from datetime import datetime, timezone
import logging
from typing import Any, List, Optional
import urllib.parse

from fastapi import HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.media_validation import (
    MAX_IMAGE_SIZE_BYTES,
    MAX_VIDEO_DURATION_SECONDS,
    MAX_VIDEO_SIZE_BYTES,
    validate_media_evidence_bytes,
)
from app.integrations.cloudinary import (
    destroy_asset,
    destroy_image,
    upload_feedback_attachment,
)
from app.modules.feedback import repository
from app.modules.feedback.models import (
    SiteFeedback,
    SiteFeedbackAttachment,
    SupportContribution,
    SupportClaim,
    SupportClaimStatus,
)
from app.modules.feedback.schemas import (
    AdminFeedbackAttachmentItem,
    AdminFeedbackDetail,
    AdminFeedbackListItem,
    AdminFeedbackListPage,
    AdminFeedbackSender,
    AdminSupportContributionCreate,
    AdminSupportContributionCursorPage,
    AdminSupportContributionItem,
    AdminUserSafeIdentity,
    CreatorPublicInfo,
    FeedbackAttachmentItem,
    FeedbackCreateResponse,
    MyFeedbackCursorPage,
    MyFeedbackItem,
    PublicFeedbackCursorPage,
    PublicFeedbackItem,
    SupportResponse,
    SupporterLeaderboardItem,
    SupporterLeaderboardResponse,
    SupporterPublicIdentity,
    SupporterResolveResponse,
    sanitize_feedback_content,
    SupportClaimCreate,
    SupportClaimUserItem,
    SupportClaimUserListPage,
    AdminSupportClaimVerify,
    AdminSupportClaimReject,
    AdminSupportClaimItem,
    AdminSupportClaimCursorPage,
)
from app.modules.notifications.models import NotificationType
from app.modules.notifications.service import (
    NotificationService,
    format_notification,
    safe_publish_user_notification,
    dispatch_notification_snapshots,
)
from app.modules.users.models import User, UserAuthIdentity, UserStatus

logger = logging.getLogger("app")

MAX_FEEDBACK_IMAGES = 3
MAX_FEEDBACK_VIDEOS = 1
MAX_FEEDBACK_ATTACHMENTS = 4


def _validate_safe_media_url(url: str) -> None:
    if not url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tệp minh chứng không có liên kết hợp lệ.",
        )
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Giao thức liên kết tệp không an toàn.",
        )
    hostname = (parsed.hostname or "").lower()
    allowed_domains = {"res.cloudinary.com"}
    if not any(hostname == d or hostname.endswith("." + d) for d in allowed_domains):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Nguồn lưu trữ tệp không được tin cậy.",
        )


async def submit_feedback(
    session: AsyncSession,
    current_user: User,
    content: str,
    images: Optional[List[UploadFile]] = None,
    video: Optional[UploadFile] = None,
) -> FeedbackCreateResponse:
    if current_user.status not in (UserStatus.ACTIVE, "ACTIVE"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản của bạn không có quyền gửi phản hồi.",
        )

    # 1. Content validation
    cleaned_content = sanitize_feedback_content(content)

    # 2. File list aggregation and quantity validation
    image_files = [f for f in (images or []) if f.filename]
    video_files = [video] if (video and video.filename) else []

    if len(image_files) > MAX_FEEDBACK_IMAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Số lượng ảnh minh chứng tối đa là {MAX_FEEDBACK_IMAGES}.",
        )
    if len(video_files) > MAX_FEEDBACK_VIDEOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Số lượng video minh chứng tối đa là {MAX_FEEDBACK_VIDEOS}.",
        )
    if len(image_files) + len(video_files) > MAX_FEEDBACK_ATTACHMENTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Tổng số tệp đính kèm tối đa là {MAX_FEEDBACK_ATTACHMENTS}.",
        )

    # 3. Read and validate bytes locally before uploading
    validated_files: List[dict[str, Any]] = []
    for f in image_files:
        content_bytes = await f.read()
        canon_mime, media_type = validate_media_evidence_bytes(f.filename or "image", content_bytes)
        if media_type != "IMAGE":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Tệp '{f.filename}' không phải là ảnh hợp lệ.",
            )
        if len(content_bytes) > MAX_IMAGE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Ảnh '{f.filename}' vượt quá dung lượng tối đa (10MB).",
            )
        validated_files.append({
            "bytes": content_bytes,
            "filename": f.filename or "image",
            "mime_type": canon_mime,
            "kind": "IMAGE",
            "size_bytes": len(content_bytes),
        })

    for f in video_files:
        content_bytes = await f.read()
        canon_mime, media_type = validate_media_evidence_bytes(f.filename or "video", content_bytes)
        if media_type != "VIDEO":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Tệp '{f.filename}' không phải là video hợp lệ.",
            )
        if len(content_bytes) > MAX_VIDEO_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Video '{f.filename}' vượt quá dung lượng tối đa (30MB).",
            )
        validated_files.append({
            "bytes": content_bytes,
            "filename": f.filename or "video",
            "mime_type": canon_mime,
            "kind": "VIDEO",
            "size_bytes": len(content_bytes),
        })

    # 4. Upload to Cloudinary with compensation tracking
    uploaded_assets: List[tuple[str, str]] = []  # (public_id, resource_type)
    attachments_data: List[dict[str, Any]] = []

    try:
        for item in validated_files:
            res_type = "video" if item["kind"] == "VIDEO" else "image"
            res = upload_feedback_attachment(
                file=item["bytes"],
                resource_type=res_type,
            )
            pid = res["public_id"]
            uploaded_assets.append((pid, res_type))

            # Video duration check from trusted upload metadata
            duration_ms = None
            if item["kind"] == "VIDEO":
                duration_sec = res.get("duration")
                if duration_sec is not None:
                    if float(duration_sec) > MAX_VIDEO_DURATION_SECONDS:
                        # Compensate already uploaded
                        for p, rt in uploaded_assets:
                            destroy_asset(p, resource_type=rt)
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail=f"Thời lượng video vượt quá giới hạn tối đa ({int(MAX_VIDEO_DURATION_SECONDS)} giây).",
                        )
                    duration_ms = int(float(duration_sec) * 1000)

            attachments_data.append({
                "kind": item["kind"],
                "media_url": res.get("secure_url") or res.get("url"),
                "storage_key": pid,
                "mime_type": item["mime_type"],
                "size_bytes": item["size_bytes"],
                "duration_ms": duration_ms,
            })
    except HTTPException:
        raise
    except Exception as e:
        for pid, rt in uploaded_assets:
            destroy_asset(pid, resource_type=rt)
        logger.error(f"Cloudinary upload error during feedback creation: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lỗi khi tải tệp lên dịch vụ lưu trữ.",
        ) from e

    # 5. DB Persistence
    try:
        feedback = await repository.create_feedback(
            session=session,
            user_id=current_user.user_id,
            content=cleaned_content,
        )
        created_attachments = []
        if attachments_data:
            created_attachments = await repository.add_attachments(
                session=session,
                feedback_id=feedback.feedback_id,
                attachments_data=attachments_data,
            )

        # Notify active admins of new feedback
        notif_service = NotificationService(session)
        admin_snapshots = await notif_service.notify_admins(
            title="Có phản hồi mới",
            body="Một phản hồi mới vừa được gửi tới Chợ PTITers.",
            ref_type="ADMIN_FEEDBACK",
            ref_id=feedback.feedback_id,
        )

        await session.commit()
        await session.refresh(feedback)
    except Exception as e:
        await session.rollback()
        # Compensate uploaded assets on DB failure
        for pid, rt in uploaded_assets:
            destroy_asset(pid, resource_type=rt)
        logger.error(f"DB error during feedback creation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể lưu phản hồi vào hệ thống.",
        ) from e

    # Post-commit best-effort realtime dispatch
    await dispatch_notification_snapshots(admin_snapshots)

    return FeedbackCreateResponse(
        feedback_id=feedback.feedback_id,
        content=feedback.content,
        created_at=feedback.created_at,
        attachments=[
            FeedbackAttachmentItem(
                attachment_id=a.attachment_id,
                kind=a.kind,
                mime_type=a.mime_type,
                size_bytes=a.size_bytes,
                duration_ms=a.duration_ms,
            )
            for a in created_attachments
        ],
    )


async def list_public_feedbacks(
    session: AsyncSession,
    limit: int = 20,
    cursor: Optional[str] = None,
) -> PublicFeedbackCursorPage:
    items, next_cursor, has_more = await repository.list_public_feedbacks(
        session=session,
        limit=limit,
        cursor=cursor,
    )
    return PublicFeedbackCursorPage(
        items=[
            PublicFeedbackItem(
                feedback_id=f.feedback_id,
                content=f.content,
                created_at=f.created_at,
            )
            for f in items
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )


async def list_my_feedbacks(
    session: AsyncSession,
    current_user: User,
    limit: int = 20,
    cursor: Optional[str] = None,
) -> MyFeedbackCursorPage:
    items, next_cursor, has_more = await repository.list_user_feedbacks(
        session=session,
        user_id=current_user.user_id,
        limit=limit,
        cursor=cursor,
    )
    return MyFeedbackCursorPage(
        items=[
            MyFeedbackItem(
                feedback_id=f.feedback_id,
                content=f.content,
                created_at=f.created_at,
                attachments=[
                    FeedbackAttachmentItem(
                        attachment_id=a.attachment_id,
                        kind=a.kind,
                        mime_type=a.mime_type,
                        size_bytes=a.size_bytes,
                        duration_ms=a.duration_ms,
                    )
                    for a in f.attachments
                ],
            )
            for f in items
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )


async def delete_user_feedback(
    session: AsyncSession,
    feedback_id: int,
    current_user: User,
) -> None:
    if current_user.status not in (UserStatus.ACTIVE, "ACTIVE"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản của bạn không có quyền thực hiện thao tác này.",
        )

    feedback = await repository.get_by_id(
        session, feedback_id, eager_load=True, for_update=True
    )
    # Privacy-safe 404: if feedback doesn't exist or belongs to someone else
    if not feedback or feedback.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy phản hồi.",
        )

    # Collect storage keys for post-commit cleanup
    to_delete = [
        (a.storage_key, "video" if a.kind == "VIDEO" else "image")
        for a in feedback.attachments
    ]

    await repository.delete_feedback(session, feedback)
    await session.commit()

    # Best-effort Cloudinary cleanup AFTER successful commit
    for storage_key, resource_type in to_delete:
        try:
            destroy_asset(storage_key, resource_type=resource_type)
        except Exception as e:
            logger.error(f"Failed to cleanup Cloudinary asset {storage_key}: {e}")


async def list_admin_feedbacks(
    session: AsyncSession,
    limit: int = 20,
    cursor: Optional[str] = None,
) -> AdminFeedbackListPage:
    items, next_cursor, has_more = await repository.list_admin_feedbacks(
        session=session,
        limit=limit,
        cursor=cursor,
    )
    admin_items = []
    for f in items:
        img_count = sum(1 for a in f.attachments if a.kind == "IMAGE")
        vid_count = sum(1 for a in f.attachments if a.kind == "VIDEO")
        admin_items.append(
            AdminFeedbackListItem(
                feedback_id=f.feedback_id,
                sender=AdminFeedbackSender(
                    user_id=f.user_id,
                    full_name=f.user.full_name if f.user else f"Người dùng #{f.user_id}",
                    avatar_url=f.user.avatar_url if f.user else None,
                ),
                content=f.content,
                created_at=f.created_at,
                image_count=img_count,
                video_count=vid_count,
            )
        )
    return AdminFeedbackListPage(
        items=admin_items,
        next_cursor=next_cursor,
        has_more=has_more,
    )


async def get_admin_feedback_detail(
    session: AsyncSession,
    feedback_id: int,
) -> AdminFeedbackDetail:
    feedback = await repository.get_by_id(session, feedback_id, eager_load=True)
    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy phản hồi.",
        )

    attachments = [
        AdminFeedbackAttachmentItem(
            attachment_id=a.attachment_id,
            kind=a.kind,
            mime_type=a.mime_type,
            size_bytes=a.size_bytes,
            duration_ms=a.duration_ms,
            stream_url=f"/api/v1/admin/feedback/{feedback.feedback_id}/evidence/{a.attachment_id}",
        )
        for a in feedback.attachments
    ]

    return AdminFeedbackDetail(
        feedback_id=feedback.feedback_id,
        sender=AdminFeedbackSender(
            user_id=feedback.user_id,
            full_name=feedback.user.full_name if feedback.user else f"Người dùng #{feedback.user_id}",
            avatar_url=feedback.user.avatar_url if feedback.user else None,
        ),
        content=feedback.content,
        created_at=feedback.created_at,
        attachments=attachments,
    )


async def delete_admin_feedback(
    session: AsyncSession,
    feedback_id: int,
) -> None:
    feedback = await repository.get_by_id(
        session, feedback_id, eager_load=True, for_update=True
    )
    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy phản hồi.",
        )

    # Collect storage keys for post-commit cleanup
    to_delete = [
        (a.storage_key, "video" if a.kind == "VIDEO" else "image")
        for a in feedback.attachments
    ]

    await repository.delete_feedback(session, feedback)
    await session.commit()

    # Best-effort Cloudinary cleanup AFTER successful commit
    for storage_key, resource_type in to_delete:
        try:
            destroy_asset(storage_key, resource_type=resource_type)
        except Exception as e:
            logger.error(f"Failed to cleanup Cloudinary asset {storage_key}: {e}")


async def stream_feedback_evidence(
    session: AsyncSession,
    feedback_id: int,
    attachment_id: int,
    range_header: Optional[str] = None,
) -> StreamingResponse:
    attachment = await repository.get_attachment_by_id(session, attachment_id)
    if not attachment or attachment.feedback_id != feedback_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy tệp minh chứng.",
        )

    target_url = attachment.media_url
    _validate_safe_media_url(target_url)

    upstream_headers: dict[str, str] = {}
    if range_header:
        upstream_headers["Range"] = range_header.strip()

    client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    try:
        req = client.build_request("GET", target_url, headers=upstream_headers)
        upstream_resp = await client.send(req, stream=True)
        if upstream_resp.status_code >= 400:
            await upstream_resp.aclose()
            await client.aclose()
            logger.error(
                f"Cloudinary upstream returned {upstream_resp.status_code} for feedback attachment {attachment_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Không thể tải tệp từ máy chủ lưu trữ.",
            )
    except HTTPException:
        raise
    except Exception as e:
        await client.aclose()
        logger.error(f"Failed to connect to upstream storage for feedback attachment {attachment_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Không thể kết nối đến máy chủ lưu trữ tệp.",
        ) from e

    headers = {
        "Content-Type": attachment.mime_type or upstream_resp.headers.get("content-type", "application/octet-stream"),
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600",
    }

    if upstream_resp.status_code == 206:
        content_range = upstream_resp.headers.get("content-range")
        if content_range:
            headers["Content-Range"] = content_range

    upstream_cl = upstream_resp.headers.get("content-length")
    if upstream_cl and upstream_cl.isdigit() and int(upstream_cl) > 0:
        headers["Content-Length"] = upstream_cl

    async def body_stream():
        try:
            async for chunk in upstream_resp.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await upstream_resp.aclose()
            await client.aclose()

    return StreamingResponse(body_stream(), status_code=upstream_resp.status_code, headers=headers)


async def get_support_info(session: AsyncSession) -> SupportResponse:
    creator_user: Optional[User] = None
    provider_uid = (settings.COMMUNITY_CREATOR_PROVIDER_UID or "").strip()
    creator_email = (settings.COMMUNITY_CREATOR_EMAIL or "").strip()

    if provider_uid:
        stmt = (
            select(User)
            .join(UserAuthIdentity, User.user_id == UserAuthIdentity.user_id)
            .where(
                UserAuthIdentity.provider == "FIREBASE",
                UserAuthIdentity.provider_uid == provider_uid,
            )
        )
        res = await session.execute(stmt)
        creator_user = res.scalar_one_or_none()
        if not creator_user:
            logger.warning(
                "Configured COMMUNITY_CREATOR_PROVIDER_UID could not be resolved to any local user"
            )
    elif creator_email:
        stmt = select(User).where(func.lower(User.email) == creator_email.lower())
        res = await session.execute(stmt)
        creator_user = res.scalar_one_or_none()
        if not creator_user:
            logger.warning(
                "Configured COMMUNITY_CREATOR_EMAIL could not be resolved to any local user"
            )
    else:
        logger.warning(
            "Neither COMMUNITY_CREATOR_PROVIDER_UID nor COMMUNITY_CREATOR_EMAIL is configured"
        )

    creator_info = None
    profile_path = None
    if creator_user and creator_user.status in (UserStatus.ACTIVE, "ACTIVE"):
        creator_info = CreatorPublicInfo(
            user_id=creator_user.user_id,
            full_name=creator_user.full_name,
            avatar_url=creator_user.avatar_url,
            title="Người phát triển Chợ PTITers",
        )
        profile_path = f"/users/{creator_user.user_id}"

    return SupportResponse(
        creator=creator_info,
        profile_path=profile_path,
        fixed_qr_url="/support/nguyen-khac-thinh-vietqr.png",
        support_message="Quan trọng là tấm lòng 💛",
    )


async def search_supporters_for_admin(
    session: AsyncSession,
    query: str,
    limit: int = 10,
) -> List[SupporterResolveResponse]:
    """Tìm kiếm người dùng an toàn cho Quản trị viên phục vụ ghi nhận ủng hộ thủ công."""
    users = await repository.search_supporters_for_admin(session=session, query=query, limit=limit)
    return [
        SupporterResolveResponse(
            user_id=u.user_id,
            full_name=u.full_name,
            avatar_url=u.avatar_url,
            profile_path=f"/users/{u.user_id}",
        )
        for u in users
    ]


# ======================================================================
# SUPPORTER LEADERBOARD & ADMIN SUPPORT CONTRIBUTIONS
# ======================================================================

def _map_admin_support_contribution_item(c: SupportContribution) -> AdminSupportContributionItem:
    return AdminSupportContributionItem(
        contribution_id=c.contribution_id,
        supporter=AdminUserSafeIdentity(
            user_id=c.supporter.user_id,
            full_name=c.supporter.full_name,
            avatar_url=c.supporter.avatar_url,
        ),
        amount_vnd=c.amount_vnd,
        is_public=c.is_public,
        received_at=c.received_at,
        transaction_ref=c.transaction_ref,
        admin_note=c.admin_note,
        recorded_by=AdminUserSafeIdentity(
            user_id=c.recorder.user_id,
            full_name=c.recorder.full_name,
            avatar_url=c.recorder.avatar_url,
        ),
        created_at=c.created_at,
    )


async def get_supporter_leaderboard(session: AsyncSession) -> SupporterLeaderboardResponse:
    """Lấy danh sách Top 10 người ủng hộ công khai xếp hạng theo tổng tiền ủng hộ."""
    items = await repository.get_supporter_leaderboard(session, limit=10)
    return SupporterLeaderboardResponse(
        items=[
            SupporterLeaderboardItem(
                rank=item["rank"],
                supporter=SupporterPublicIdentity(**item["supporter"]),
                total_amount_vnd=item["total_amount_vnd"],
                contribution_count=item["contribution_count"],
                last_supported_at=item["last_supported_at"],
            )
            for item in items
        ]
    )


async def create_admin_support_contribution(
    session: AsyncSession,
    current_admin: User,
    payload: AdminSupportContributionCreate,
) -> AdminSupportContributionItem:
    """Quản trị viên ghi nhận khoản ủng hộ thực tế đã được xác minh."""
    # Xác thực người ủng hộ tồn tại
    stmt = select(User).where(User.user_id == payload.supporter_id)
    res = await session.execute(stmt)
    supporter = res.scalar_one_or_none()
    if not supporter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy người dùng ủng hộ.",
        )

    # Server trích xuất recorded_by từ current_admin đã xác thực
    contribution = await repository.create_support_contribution(
        session=session,
        supporter_id=payload.supporter_id,
        amount_vnd=payload.amount_vnd,
        received_at=payload.received_at,
        is_public=payload.is_public,
        recorded_by=current_admin.user_id,
        transaction_ref=payload.transaction_ref,
        admin_note=payload.admin_note,
    )
    await session.commit()
    return _map_admin_support_contribution_item(contribution)


async def list_admin_support_contributions(
    session: AsyncSession,
    limit: int = 20,
    cursor: Optional[str] = None,
) -> AdminSupportContributionCursorPage:
    """Quản trị viên xem sổ cái đóng góp kèm phân trang Keyset."""
    records, next_cursor, has_more = await repository.list_admin_support_contributions(
        session=session,
        limit=limit,
        cursor=cursor,
    )
    items = [_map_admin_support_contribution_item(r) for r in records]
    return AdminSupportContributionCursorPage(
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
    )


async def update_support_contribution_visibility(
    session: AsyncSession,
    contribution_id: int,
    is_public: bool,
) -> AdminSupportContributionItem:
    """Quản trị viên chuyển đổi trạng thái hiển thị công khai trên Bảng tri ân."""
    contribution = await repository.get_support_contribution_by_id(session, contribution_id)
    if not contribution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy bản ghi đóng góp.",
        )

    await repository.update_support_contribution_visibility(session, contribution, is_public)
    await session.commit()
    return _map_admin_support_contribution_item(contribution)


async def delete_admin_support_contribution(
    session: AsyncSession,
    contribution_id: int,
) -> None:
    """Quản trị viên xóa bản ghi đóng góp sai sót / nhầm lẫn."""
    contribution = await repository.get_support_contribution_by_id(session, contribution_id)
    if not contribution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy bản ghi đóng góp.",
        )

    await repository.delete_support_contribution(session, contribution)
    await session.commit()


# ======================================================================
# SUPPORT CLAIMS SERVICE (USER DECLARATION & ADMIN RECONCILIATION)
# ======================================================================

def _map_admin_support_claim_item(c: SupportClaim) -> AdminSupportClaimItem:
    reviewer = None
    if c.reviewer:
        reviewer = AdminUserSafeIdentity(
            user_id=c.reviewer.user_id,
            full_name=c.reviewer.full_name,
            avatar_url=c.reviewer.avatar_url,
        )
    elif c.reviewed_by:
        reviewer = AdminUserSafeIdentity(
            user_id=c.reviewed_by,
            full_name="Quản trị viên",
            avatar_url=None,
        )

    return AdminSupportClaimItem(
        claim_id=c.claim_id,
        supporter=SupporterResolveResponse(
            user_id=c.supporter.user_id,
            full_name=c.supporter.full_name,
            avatar_url=c.supporter.avatar_url,
            profile_path=f"/users/{c.supporter.user_id}",
        ),
        claimed_amount_vnd=c.claimed_amount_vnd,
        claimed_transferred_at=c.claimed_transferred_at,
        sender_account_name=c.sender_account_name,
        wants_public=c.wants_public,
        status=c.status,
        reviewed_by=reviewer,
        reviewed_at=c.reviewed_at,
        contribution_id=c.contribution_id,
        rejection_reason=c.rejection_reason,
        created_at=c.created_at,
    )


async def create_user_support_claim(
    session: AsyncSession,
    current_user: User,
    payload: SupportClaimCreate,
) -> SupportClaimUserItem:
    """Người dùng gửi xác nhận chuyển khoản ủng hộ (khai báo phi tài chính)."""
    claim = await repository.create_support_claim(
        session=session,
        supporter_id=current_user.user_id,
        claimed_amount_vnd=payload.claimed_amount_vnd,
        claimed_transferred_at=payload.claimed_transferred_at,
        sender_account_name=payload.sender_account_name,
        wants_public=payload.wants_public,
    )

    # Notify all active admins of new pending support claim
    notif_service = NotificationService(session)
    admin_snapshots = await notif_service.notify_admins(
        title="Có khoản ủng hộ chờ đối soát",
        body="Một yêu cầu xác nhận ủng hộ mới đang chờ đối soát.",
        ref_type="ADMIN_SUPPORT_CLAIM",
        ref_id=claim.claim_id,
    )

    await session.commit()

    # Post-commit best-effort realtime dispatch
    await dispatch_notification_snapshots(admin_snapshots)

    return SupportClaimUserItem.model_validate(claim)


async def list_my_support_claims(
    session: AsyncSession,
    current_user: User,
    limit: int = 10,
) -> SupportClaimUserListPage:
    """Lấy danh sách các yêu cầu xác nhận ủng hộ của chính người dùng hiện tại."""
    claims = await repository.list_support_claims_by_user(
        session=session,
        supporter_id=current_user.user_id,
        limit=limit,
    )
    return SupportClaimUserListPage(
        items=[SupportClaimUserItem.model_validate(c) for c in claims]
    )


async def list_admin_support_claims(
    session: AsyncSession,
    status_filter: Optional[str] = None,
    limit: int = 20,
    cursor: Optional[str] = None,
) -> AdminSupportClaimCursorPage:
    """Hàng đợi đối soát xác nhận ủng hộ dành cho Quản trị viên."""
    records, next_cursor, has_more = await repository.list_admin_support_claims(
        session=session,
        status=status_filter,
        limit=limit,
        cursor=cursor,
    )
    items = [_map_admin_support_claim_item(r) for r in records]
    return AdminSupportClaimCursorPage(
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
    )


async def verify_admin_support_claim(
    session: AsyncSession,
    claim_id: int,
    current_admin: User,
    payload: AdminSupportClaimVerify,
) -> AdminSupportClaimItem:
    """
    Quản trị viên đối soát với tài khoản ngân hàng thực tế và xác nhận khoản ủng hộ.
    Thao tác khóa dòng (SELECT FOR UPDATE) để chống trùng lặp / tranh chấp đồng thời.
    Chỉ khi xác nhận thành công mới tạo duy nhất một dòng support_contributions authoritative.
    """
    # 1. Khóa dòng claim FOR UPDATE
    claim = await repository.get_support_claim_by_id(
        session=session,
        claim_id=claim_id,
        eager_load=True,
        for_update=True,
    )
    if not claim:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy yêu cầu xác nhận ủng hộ.",
        )

    # 2. Kiểm tra tính lũy kế / Idempotency
    if claim.status == SupportClaimStatus.VERIFIED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Yêu cầu xác nhận này đã được xác thực trước đó.",
        )
    if claim.status == SupportClaimStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Yêu cầu xác nhận này đã bị từ chối trước đó.",
        )
    if claim.status != SupportClaimStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Trạng thái yêu cầu không hợp lệ để xác thực: {claim.status}",
        )

    # 3. Kiểm tra người ủng hộ vẫn tồn tại
    stmt = select(User).where(User.user_id == claim.supporter_id)
    res = await session.execute(stmt)
    supporter = res.scalar_one_or_none()
    if not supporter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy người dùng ủng hộ.",
        )

    # 4. Tạo duy nhất 1 bản ghi support_contributions có thẩm quyền tài chính
    now_utc = datetime.now(timezone.utc)
    contribution = await repository.create_support_contribution(
        session=session,
        supporter_id=claim.supporter_id,
        amount_vnd=payload.amount_vnd,
        received_at=payload.received_at,
        is_public=claim.wants_public,
        recorded_by=current_admin.user_id,
        transaction_ref=payload.transaction_ref,
        admin_note=payload.admin_note,
    )
    await session.flush()

    # 5. Cập nhật trạng thái claim
    claim.status = SupportClaimStatus.VERIFIED
    claim.reviewed_by = current_admin.user_id
    claim.reviewer = current_admin
    claim.reviewed_at = now_utc
    claim.contribution_id = contribution.contribution_id

    # 6. Gửi thông báo hệ thống bền vững cho người dùng
    supporter_snapshot = None
    try:
        notification_service = NotificationService(session)
        notif = await notification_service.create_notification(
            user_id=claim.supporter_id,
            type=NotificationType.SYSTEM.value,
            title="Khoản ủng hộ đã được xác nhận",
            body=f"Khoản ủng hộ {payload.amount_vnd:,}đ của bạn đã được xác nhận. Cảm ơn bạn đã đồng hành cùng Chợ PTITers.",
            ref_type="SUPPORT_CLAIM",
            ref_id=claim.claim_id,
        )
        supporter_snapshot = format_notification(notif)
    except Exception as e:
        logger.warning("Could not dispatch support confirmation notification: %s", e)

    # 7. Commit một lần duy nhất
    await session.commit()

    # 8. Post-commit realtime dispatch
    if supporter_snapshot:
        await safe_publish_user_notification(claim.supporter_id, supporter_snapshot)

    updated_claim = await repository.get_support_claim_by_id(
        session=session,
        claim_id=claim_id,
        eager_load=True,
        for_update=False,
    )
    assert updated_claim is not None
    return _map_admin_support_claim_item(updated_claim)


async def reject_admin_support_claim(
    session: AsyncSession,
    claim_id: int,
    current_admin: User,
    payload: AdminSupportClaimReject,
) -> AdminSupportClaimItem:
    """
    Quản trị viên từ chối yêu cầu xác nhận khi không tìm thấy giao dịch ngân hàng khớp.
    Khóa dòng FOR UPDATE và cập nhật trạng thái REJECTED. Tuyệt đối không tạo support_contributions.
    """
    claim = await repository.get_support_claim_by_id(
        session=session,
        claim_id=claim_id,
        eager_load=True,
        for_update=True,
    )
    if not claim:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy yêu cầu xác nhận ủng hộ.",
        )

    if claim.status == SupportClaimStatus.VERIFIED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Yêu cầu xác nhận này đã được xác thực trước đó, không thể từ chối.",
        )
    if claim.status == SupportClaimStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Yêu cầu xác nhận này đã bị từ chối trước đó.",
        )
    if claim.status != SupportClaimStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Trạng thái yêu cầu không hợp lệ để từ chối: {claim.status}",
        )

    now_utc = datetime.now(timezone.utc)
    claim.status = SupportClaimStatus.REJECTED
    claim.reviewed_by = current_admin.user_id
    claim.reviewer = current_admin
    claim.reviewed_at = now_utc
    claim.rejection_reason = payload.rejection_reason

    supporter_snapshot = None
    try:
        notification_service = NotificationService(session)
        body_text = "Khoản ủng hộ bạn khai báo chưa khớp với giao dịch nhận tiền thực tế. Vui lòng kiểm tra lại."
        if payload.rejection_reason and payload.rejection_reason.strip():
            body_text = f"Yêu cầu xác nhận chưa được chấp thuận: {payload.rejection_reason.strip()}"
        notif = await notification_service.create_notification(
            user_id=claim.supporter_id,
            type=NotificationType.SYSTEM.value,
            title="Chưa xác nhận được khoản ủng hộ",
            body=body_text,
            ref_type="SUPPORT_CLAIM",
            ref_id=claim.claim_id,
        )
        supporter_snapshot = format_notification(notif)
    except Exception as e:
        logger.warning("Could not dispatch support rejection notification: %s", e)

    await session.commit()

    # Post-commit realtime dispatch
    if supporter_snapshot:
        await safe_publish_user_notification(claim.supporter_id, supporter_snapshot)

    updated_claim = await repository.get_support_claim_by_id(
        session=session,
        claim_id=claim_id,
        eager_load=True,
        for_update=False,
    )
    assert updated_claim is not None
    return _map_admin_support_claim_item(updated_claim)
