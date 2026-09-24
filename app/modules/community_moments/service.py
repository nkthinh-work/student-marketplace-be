import logging
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.media_validation import validate_image_bytes
from app.integrations.cloudinary import (
    destroy_image,
    get_detail_image_url,
    get_hero_image_url,
    get_thumbnail_url,
    upload_community_moment_image,
)
from app.modules.community_moments.models import (
    CommunityMoment,
    CommunityMomentStatus,
)
from app.modules.community_moments.repository import (
    CommunityMomentRepository,
    acquire_community_hero_lock,
    decode_cursor,
    encode_cursor,
)
from app.modules.community_moments.schemas import (
    AdminCommunityMomentCursorPage,
    AdminCommunityMomentItem,
    AdminCommunityMomentReviewer,
    AdminCommunityMomentUploader,
    CommunityMomentActionResponse,
    CommunityMomentSubmissionResponse,
    PublicCommunityMomentItem,
    PublicHeroResponse,
)
from app.modules.users.models import User, UserStatus

logger = logging.getLogger("app")


def validate_community_note(raw_note: Optional[str]) -> str:
    if raw_note is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Lời nhắn là bắt buộc.",
        )
    # Normalize Unicode NFC
    normalized = unicodedata.normalize("NFC", raw_note)
    # Check for newline/CR characters
    if "\n" in normalized or "\r" in normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Lời nhắn chỉ được chứa một dòng duy nhất, không chứa ký tự xuống dòng.",
        )
    # Check for other multiline/paragraph control characters
    for ch in normalized:
        if ch in ("\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Lời nhắn chỉ được chứa một dòng duy nhất.",
            )
    trimmed = normalized.strip()
    if not trimmed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Lời nhắn không được để trống.",
        )
    if len(trimmed) > 80:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Lời nhắn không được vượt quá 80 ký tự.",
        )
    return trimmed


class CommunityMomentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CommunityMomentRepository(db)

    async def submit_moment(
        self,
        uploader: User,
        file: UploadFile,
        note: str,
    ) -> CommunityMomentSubmissionResponse:
        # 1. Authorize: Only ACTIVE users may submit
        if uploader.status != UserStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tài khoản của bạn không ở trạng thái hoạt động.",
            )

        # 2. Validate note before reading file/performing external upload
        validated_note = validate_community_note(note)

        # 3. Anti-spam pre-check: At most one PENDING moment per user
        existing_pending = await self.repo.get_pending_by_user(uploader.user_id)
        if existing_pending:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "COMMUNITY_MOMENT_PENDING",
                    "message": "Bạn đã có một ảnh đang chờ duyệt.",
                },
            )

        # 4. Read and validate media bytes
        file_bytes = await file.read()
        canonical_mime = validate_image_bytes(
            file_name=file.filename or "community_moment",
            file_bytes=file_bytes,
        )

        # 5. Upload to Cloudinary
        try:
            upload_result = upload_community_moment_image(
                file=file_bytes,
                user_id=uploader.user_id,
            )
        except Exception as e:
            logger.error(
                "Cloudinary upload failed for user %s: %s", uploader.user_id, e
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Dịch vụ lưu trữ ảnh tạm thời không khả dụng.",
            ) from e

        image_url = upload_result.get("secure_url") or upload_result.get("url")
        storage_key = upload_result.get("public_id")

        # 6. Insert into Database with partial unique concurrency protection & compensation
        new_moment = CommunityMoment(
            uploader_id=uploader.user_id,
            image_url=image_url,
            storage_key=storage_key,
            mime_type=canonical_mime,
            size_bytes=len(file_bytes),
            note=validated_note,
            status=CommunityMomentStatus.PENDING.value,
        )

        try:
            created = await self.repo.create(new_moment)
            await self.db.commit()
            await self.db.refresh(created)
            return CommunityMomentSubmissionResponse(
                moment_id=created.moment_id,
                status=created.status,
                created_at=created.created_at,
            )
        except IntegrityError as e:
            await self.db.rollback()
            if storage_key:
                destroy_image(storage_key)

            orig = getattr(e, "orig", None)
            constraint_name = getattr(orig, "constraint_name", None) or ""
            err_str = str(e)
            if (
                "uq_community_moments_user_pending" in constraint_name
                or "uq_community_moments_user_pending" in err_str
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "COMMUNITY_MOMENT_PENDING",
                        "message": "Bạn đã có một ảnh đang chờ duyệt.",
                    },
                )

            logger.error("DB IntegrityError on community moment insert: %s", e)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Lỗi ràng buộc dữ liệu khi lưu ảnh.",
            ) from e
        except Exception as e:
            await self.db.rollback()
            if storage_key:
                destroy_image(storage_key)
            logger.error("Unexpected error on community moment insert: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Không thể lưu ảnh khoảnh khắc. Vui lòng thử lại.",
            ) from e

    async def get_public_hero_moments(self) -> PublicHeroResponse:
        moments = await self.repo.get_latest_approved(limit=5)
        items = [
            PublicCommunityMomentItem(
                moment_id=m.moment_id,
                image_url=get_hero_image_url(m.image_url) or m.image_url,
                note=m.note,
                approved_at=m.reviewed_at,
            )
            for m in moments
        ]
        return PublicHeroResponse(items=items)

    async def list_admin_moments(
        self,
        status: Optional[str] = "PENDING",
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> AdminCommunityMomentCursorPage:
        cursor_tuple = None
        if cursor:
            try:
                cursor_tuple = decode_cursor(cursor)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid pagination cursor.",
                )

        items, has_more, next_cursor_tuple = (
            await self.repo.list_admin_moments_cursor(
                status=status,
                cursor=cursor_tuple,
                limit=limit,
            )
        )

        dto_items = [
            AdminCommunityMomentItem(
                moment_id=m.moment_id,
                image_url=m.image_url,
                thumbnail_url=get_thumbnail_url(m.image_url),
                detail_image_url=get_detail_image_url(m.image_url),
                note=m.note,
                status=m.status,
                created_at=m.created_at,
                reviewed_at=m.reviewed_at,
                uploader=AdminCommunityMomentUploader(
                    user_id=m.uploader.user_id,
                    full_name=m.uploader.full_name,
                    avatar_url=m.uploader.avatar_url,
                ),
                reviewer=(
                    AdminCommunityMomentReviewer(
                        user_id=m.reviewer.user_id,
                        full_name=m.reviewer.full_name,
                    )
                    if m.reviewer
                    else None
                ),
            )
            for m in items
        ]

        next_cursor_str = (
            encode_cursor(next_cursor_tuple[0], next_cursor_tuple[1])
            if next_cursor_tuple
            else None
        )

        return AdminCommunityMomentCursorPage(
            items=dto_items,
            next_cursor=next_cursor_str,
            has_more=has_more,
        )

    async def get_admin_moment_detail(
        self,
        moment_id: int,
    ) -> AdminCommunityMomentItem:
        moment = await self.repo.get_by_id(moment_id, eager_load=True)
        if not moment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Khoảnh khắc cộng đồng không tồn tại.",
            )

        return AdminCommunityMomentItem(
            moment_id=moment.moment_id,
            image_url=moment.image_url,
            thumbnail_url=get_thumbnail_url(moment.image_url),
            detail_image_url=get_detail_image_url(moment.image_url),
            note=moment.note,
            status=moment.status,
            created_at=moment.created_at,
            reviewed_at=moment.reviewed_at,
            uploader=AdminCommunityMomentUploader(
                user_id=moment.uploader.user_id,
                full_name=moment.uploader.full_name,
                avatar_url=moment.uploader.avatar_url,
            ),
            reviewer=(
                AdminCommunityMomentReviewer(
                    user_id=moment.reviewer.user_id,
                    full_name=moment.reviewer.full_name,
                )
                if moment.reviewer
                else None
            ),
        )

    async def approve_moment(
        self,
        current_admin: User,
        moment_id: int,
    ) -> AdminCommunityMomentItem:
        # Serialize global Hero mutations through PostgreSQL advisory transaction lock
        await acquire_community_hero_lock(self.db)

        moment = await self.repo.get_by_id(
            moment_id, for_update=True, eager_load=True
        )
        if not moment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Khoảnh khắc cộng đồng không tồn tại.",
            )

        if moment.status != CommunityMomentStatus.PENDING.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Khoảnh khắc này đã được xử lý trước đó và không còn ở trạng thái chờ duyệt.",
            )

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        moment.status = CommunityMomentStatus.APPROVED.value
        moment.reviewed_by = current_admin.user_id
        moment.reviewed_at = now_utc

        await self.db.flush()

        # Prune oldest approved moments beyond 5 globally
        all_approved = await self.repo.get_all_approved(for_update=True)
        pruned_assets: list[tuple[int, str]] = []
        if len(all_approved) > 5:
            excess = all_approved[5:]
            for ex in excess:
                pruned_assets.append((ex.moment_id, ex.storage_key))
                await self.repo.delete(ex)

        await self.db.commit()
        await self.db.refresh(moment)

        # Post-commit best-effort Cloudinary cleanup for pruned excess moments
        for ex_id, ex_key in pruned_assets:
            try:
                destroy_image(ex_key)
            except Exception as e:
                logger.error(
                    "Failed to destroy pruned Cloudinary asset %s for moment %s: %s",
                    ex_key,
                    ex_id,
                    e,
                )

        return await self.get_admin_moment_detail(moment.moment_id)

    async def reject_moment(
        self,
        current_admin: User,
        moment_id: int,
    ) -> CommunityMomentActionResponse:
        moment = await self.repo.get_by_id(
            moment_id, for_update=True, eager_load=True
        )
        if not moment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Khoảnh khắc cộng đồng không tồn tại.",
            )

        if moment.status != CommunityMomentStatus.PENDING.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Khoảnh khắc này đã được xử lý trước đó và không còn ở trạng thái chờ duyệt.",
            )

        storage_key = moment.storage_key

        # Hard delete from DB
        await self.repo.delete(moment)
        await self.db.commit()

        # Post-commit best-effort Cloudinary cleanup
        try:
            destroy_image(storage_key)
        except Exception as e:
            logger.error(
                "Failed to destroy rejected Cloudinary asset %s for moment %s: %s",
                storage_key,
                moment_id,
                e,
            )

        return CommunityMomentActionResponse(
            moment_id=moment_id,
            status="REJECTED",
            message="Đã từ chối và xóa khoảnh khắc vĩnh viễn.",
        )

    async def delete_admin_moment(
        self,
        current_admin: User,
        moment_id: int,
    ) -> CommunityMomentActionResponse:
        # Serialize global Hero mutations through PostgreSQL advisory transaction lock
        await acquire_community_hero_lock(self.db)

        moment = await self.repo.get_by_id(
            moment_id, for_update=True, eager_load=True
        )
        if not moment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Khoảnh khắc cộng đồng không tồn tại.",
            )

        if moment.status != CommunityMomentStatus.APPROVED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Chỉ có thể xóa ảnh đang ở trạng thái đã duyệt trên Hero.",
            )

        storage_key = moment.storage_key

        # Hard delete from DB
        await self.repo.delete(moment)
        await self.db.commit()

        # Post-commit best-effort Cloudinary cleanup
        try:
            destroy_image(storage_key)
        except Exception as e:
            logger.error(
                "Failed to destroy removed Hero Cloudinary asset %s for moment %s: %s",
                storage_key,
                moment_id,
                e,
            )

        return CommunityMomentActionResponse(
            moment_id=moment_id,
            status="DELETED",
            message="Đã xóa khoảnh khắc khỏi Hero vĩnh viễn.",
        )
