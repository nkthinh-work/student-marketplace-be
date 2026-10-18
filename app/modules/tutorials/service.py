import asyncio
import io
import json
import logging
import time
from typing import Optional, Sequence

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.cloudinary import (
    CloudinaryNotConfiguredError,
    CloudinaryUploadError,
    destroy_asset_async as destroy_asset,
    generate_tutorial_upload_signature,
    get_cloudinary_video_resource_async,
    get_tutorial_video_cloudinary_folder,
    get_tutorial_video_delivery_url,
    upload_tutorial_video,
)
from app.modules.tutorials.models import Tutorial
from app.modules.tutorials.repository import TutorialRepository
from app.modules.tutorials.schemas import (
    ALLOWED_ACTION_KEYS,
    ALLOWED_FEATURE_KEYS,
    AdminTutorialConfirmDirectVideo,
    AdminTutorialCreateDirect,
    AdminTutorialReorderRequest,
    AdminTutorialUpdate,
    TutorialUploadSignatureResponse,
)

logger = logging.getLogger("app")

MAX_TUTORIAL_VIDEO_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB
ALLOWED_VIDEO_MIMES = {"video/mp4"}


class TutorialService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TutorialRepository(db)

    @staticmethod
    def _log_stage(
        stage: str,
        request_id: str,
        tutorial_id: Optional[int] = None,
        duration_ms: Optional[int] = None,
        file_size_bytes: Optional[int] = None,
        status: str = "success",
        error: Optional[str] = None,
    ) -> None:
        """Structured JSON logging for tutorial video upload lifecycle stages."""
        payload = {
            "event": "tutorial_upload",
            "stage": stage,
            "request_id": request_id,
            "tutorial_id": tutorial_id,
            "file_size_bytes": file_size_bytes,
            "duration_ms": duration_ms,
            "status": status,
        }
        if error:
            payload["error"] = error
        logger.info(f"[TUTORIAL_UPLOAD] {json.dumps(payload)}")

    @staticmethod
    async def _safe_destroy_asset(storage_key: str, resource_type: str = "video") -> None:
        """Asynchronously cleans up an asset in the background without blocking HTTP responses."""
        try:
            await asyncio.wait_for(destroy_asset(storage_key, resource_type=resource_type), timeout=15.0)
        except Exception as e:
            logger.warning(f"Background cleanup of old tutorial asset {storage_key} failed: {e}")

    async def get_public_tutorials(self) -> Sequence[Tutorial]:
        """Lấy danh sách các tutorial đã xuất bản phục vụ hiển thị công khai."""
        return await self.repo.get_published_tutorials()

    async def get_admin_tutorials(
        self, feature_key: Optional[str] = None
    ) -> Sequence[Tutorial]:
        """Lấy danh sách tất cả tutorial (kể cả bản nháp) cho quản trị viên."""
        return await self.repo.get_all_tutorials(feature_key=feature_key)

    async def get_admin_tutorial_detail(self, tutorial_id: int) -> Tutorial:
        """Lấy chi tiết một tutorial cho quản trị viên."""
        tutorial = await self.repo.get_by_id(tutorial_id)
        if not tutorial:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy Tutorial với ID {tutorial_id}",
            )
        return tutorial

    async def create_tutorial(
        self,
        current_admin_id: int,
        feature_key: str,
        title: str,
        description: Optional[str],
        action_key: Optional[str],
        is_published: bool,
        video_file: UploadFile,
        request_id: str = "unknown",
    ) -> Tutorial:
        """Tạo tutorial mới với upload video MP4 9:16."""
        start_time = time.monotonic()
        self._log_stage(
            stage="request_received",
            request_id=request_id,
            status="success",
        )

        # 1. Validate metadata
        feature_key = feature_key.strip()
        if feature_key not in ALLOWED_FEATURE_KEYS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tính năng '{feature_key}' không hợp lệ. Cho phép: {', '.join(sorted(ALLOWED_FEATURE_KEYS))}",
            )

        title = title.strip()
        if not title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tiêu đề Tutorial không được để trống",
            )
        if len(title) > 120:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tiêu đề Tutorial không được vượt quá 120 ký tự",
            )

        if description:
            description = description.strip()
            if len(description) > 500:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Mô tả không được vượt quá 500 ký tự",
                )
            if not description:
                description = None

        if action_key:
            action_key = action_key.strip()
            if action_key not in ALLOWED_ACTION_KEYS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Hành động '{action_key}' không hợp lệ. Cho phép: {', '.join(sorted(ALLOWED_ACTION_KEYS))}",
                )
            if not action_key:
                action_key = None

        # 2. Validate video file
        video_content_type = (video_file.content_type or "").lower()
        if video_content_type not in ALLOWED_VIDEO_MIMES and not (video_file.filename or "").lower().endswith(".mp4"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Định dạng video không được hỗ trợ. Chỉ chấp nhận tệp video MP4 (video/mp4).",
            )

        read_start = time.monotonic()
        video_bytes = await video_file.read()
        read_duration_ms = int((time.monotonic() - read_start) * 1000)

        if len(video_bytes) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tệp video không được rỗng.",
            )
        if len(video_bytes) > MAX_TUTORIAL_VIDEO_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Dung lượng video vượt quá giới hạn cho phép ({MAX_TUTORIAL_VIDEO_SIZE_BYTES // (1024 * 1024)} MB).",
            )

        self._log_stage(
            stage="file_read_completed",
            request_id=request_id,
            file_size_bytes=len(video_bytes),
            duration_ms=read_duration_ms,
            status="success",
        )

        # 3. Upload media to Cloudinary (non-blocking)
        self._log_stage(
            stage="cloudinary_upload_started",
            request_id=request_id,
            file_size_bytes=len(video_bytes),
            status="pending",
        )
        upload_start = time.monotonic()
        try:
            video_upload_res = await upload_tutorial_video(
                io.BytesIO(video_bytes),
                filename=video_file.filename or "tutorial.mp4",
                file_size=len(video_bytes),
            )
            upload_duration_ms = int((time.monotonic() - upload_start) * 1000)
            self._log_stage(
                stage="cloudinary_upload_completed",
                request_id=request_id,
                file_size_bytes=len(video_bytes),
                duration_ms=upload_duration_ms,
                status="success",
            )
        except CloudinaryNotConfiguredError as e:
            upload_duration_ms = int((time.monotonic() - upload_start) * 1000)
            self._log_stage(
                stage="cloudinary_upload_failed",
                request_id=request_id,
                file_size_bytes=len(video_bytes),
                duration_ms=upload_duration_ms,
                status="error",
                error=str(e),
            )
            logger.error(f"Cloudinary not configured: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Dịch vụ lưu trữ video Cloudinary chưa được cấu hình.",
            ) from e
        except CloudinaryUploadError as e:
            upload_duration_ms = int((time.monotonic() - upload_start) * 1000)
            self._log_stage(
                stage="cloudinary_upload_failed",
                request_id=request_id,
                file_size_bytes=len(video_bytes),
                duration_ms=upload_duration_ms,
                status="error",
                error=str(e),
            )
            logger.error(f"Cloudinary video upload failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Tải video lên máy chủ lưu trữ thất bại hoặc quá thời gian xử lý. Vui lòng thử lại.",
            ) from e

        video_url = video_upload_res.get("secure_url") or video_upload_res.get("url") or ""
        video_storage_key = video_upload_res.get("public_id") or ""
        duration_sec = video_upload_res.get("duration")
        duration_ms = int(float(duration_sec) * 1000) if duration_sec is not None else None

        # Check aspect ratio if metadata returned
        v_width = video_upload_res.get("width")
        v_height = video_upload_res.get("height")
        if v_width and v_height and v_height <= v_width:
            await destroy_asset(video_storage_key, resource_type="video")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Video phải có định dạng dọc (portrait 9:16). Vui lòng không tải lên video ngang hoặc vuông.",
            )

        # 4. DB transaction with compensation
        commit_start = time.monotonic()
        try:
            max_order = await self.repo.get_max_sort_order(feature_key)
            new_order = max_order + 10

            tutorial = Tutorial(
                feature_key=feature_key,
                title=title,
                description=description,
                video_url=video_url,
                video_storage_key=video_storage_key,
                video_mime_type="video/mp4",
                video_size_bytes=len(video_bytes),
                duration_ms=duration_ms,
                action_key=action_key,
                sort_order=new_order,
                is_published=is_published,
                created_by=current_admin_id,
            )
            await self.repo.create(tutorial)
            await self.db.commit()
            await self.db.refresh(tutorial)
            commit_duration_ms = int((time.monotonic() - commit_start) * 1000)
            self._log_stage(
                stage="db_commit_completed",
                request_id=request_id,
                tutorial_id=tutorial.tutorial_id,
                file_size_bytes=len(video_bytes),
                duration_ms=commit_duration_ms,
                status="success",
            )
        except Exception as e:
            commit_duration_ms = int((time.monotonic() - commit_start) * 1000)
            self._log_stage(
                stage="db_commit_failed",
                request_id=request_id,
                file_size_bytes=len(video_bytes),
                duration_ms=commit_duration_ms,
                status="error",
                error=str(e),
            )
            await self.db.rollback()
            logger.error(f"Failed to persist tutorial in DB, cleaning up Cloudinary video: {e}")
            await destroy_asset(video_storage_key, resource_type="video")
            raise e

        total_duration_ms = int((time.monotonic() - start_time) * 1000)
        self._log_stage(
            stage="response_completed",
            request_id=request_id,
            tutorial_id=tutorial.tutorial_id,
            file_size_bytes=len(video_bytes),
            duration_ms=total_duration_ms,
            status="success",
        )
        return tutorial

    async def update_tutorial_metadata(
        self, tutorial_id: int, payload: AdminTutorialUpdate
    ) -> Tutorial:
        """Cập nhật metadata của Tutorial. Nếu đổi feature_key thì tự động chuyển xuống cuối nhóm mới."""
        tutorial = await self.repo.get_by_id(tutorial_id, for_update=True)
        if not tutorial:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy Tutorial với ID {tutorial_id}",
            )

        if payload.feature_key is not None and payload.feature_key != tutorial.feature_key:
            max_order = await self.repo.get_max_sort_order(payload.feature_key)
            tutorial.feature_key = payload.feature_key
            tutorial.sort_order = max_order + 10

        if payload.title is not None:
            tutorial.title = payload.title

        if payload.description is not None:
            tutorial.description = payload.description if payload.description else None

        if payload.action_key is not None:
            tutorial.action_key = payload.action_key if payload.action_key else None

        if payload.is_published is not None:
            tutorial.is_published = payload.is_published

        await self.db.commit()
        await self.db.refresh(tutorial)
        return tutorial

    async def replace_tutorial_video(
        self,
        tutorial_id: int,
        video_file: UploadFile,
        request_id: str = "unknown",
    ) -> Tutorial:
        """Thay thế video của Tutorial một cách an toàn."""
        start_time = time.monotonic()
        self._log_stage(
            stage="request_received",
            request_id=request_id,
            tutorial_id=tutorial_id,
            status="success",
        )

        # 0. Early check existence before expensive media read/upload
        tutorial_exists = await self.repo.get_by_id(tutorial_id)
        if not tutorial_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy Tutorial với ID {tutorial_id}",
            )

        # 1. Validate video format & headers
        video_content_type = (video_file.content_type or "").lower()
        if video_content_type not in ALLOWED_VIDEO_MIMES and not (video_file.filename or "").lower().endswith(".mp4"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Định dạng video không được hỗ trợ. Chỉ chấp nhận tệp video MP4 (video/mp4).",
            )

        read_start = time.monotonic()
        video_bytes = await video_file.read()
        read_duration_ms = int((time.monotonic() - read_start) * 1000)

        if len(video_bytes) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tệp video không được rỗng.",
            )
        if len(video_bytes) > MAX_TUTORIAL_VIDEO_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Dung lượng video vượt quá giới hạn ({MAX_TUTORIAL_VIDEO_SIZE_BYTES // (1024 * 1024)} MB).",
            )

        self._log_stage(
            stage="file_read_completed",
            request_id=request_id,
            tutorial_id=tutorial_id,
            file_size_bytes=len(video_bytes),
            duration_ms=read_duration_ms,
            status="success",
        )

        # 2. Upload NEW video to Cloudinary (non-blocking)
        self._log_stage(
            stage="cloudinary_upload_started",
            request_id=request_id,
            tutorial_id=tutorial_id,
            file_size_bytes=len(video_bytes),
            status="pending",
        )
        upload_start = time.monotonic()
        try:
            new_upload_res = await upload_tutorial_video(
                io.BytesIO(video_bytes),
                filename=video_file.filename or "tutorial.mp4",
                file_size=len(video_bytes),
            )
            upload_duration_ms = int((time.monotonic() - upload_start) * 1000)
            self._log_stage(
                stage="cloudinary_upload_completed",
                request_id=request_id,
                tutorial_id=tutorial_id,
                file_size_bytes=len(video_bytes),
                duration_ms=upload_duration_ms,
                status="success",
            )
        except CloudinaryNotConfiguredError as e:
            upload_duration_ms = int((time.monotonic() - upload_start) * 1000)
            self._log_stage(
                stage="cloudinary_upload_failed",
                request_id=request_id,
                tutorial_id=tutorial_id,
                file_size_bytes=len(video_bytes),
                duration_ms=upload_duration_ms,
                status="error",
                error=str(e),
            )
            logger.error(f"Cloudinary not configured: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Dịch vụ lưu trữ video Cloudinary chưa được cấu hình.",
            ) from e
        except CloudinaryUploadError as e:
            upload_duration_ms = int((time.monotonic() - upload_start) * 1000)
            self._log_stage(
                stage="cloudinary_upload_failed",
                request_id=request_id,
                tutorial_id=tutorial_id,
                file_size_bytes=len(video_bytes),
                duration_ms=upload_duration_ms,
                status="error",
                error=str(e),
            )
            logger.error(f"Cloudinary video upload failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Tải video lên máy chủ lưu trữ thất bại hoặc quá thời gian xử lý. Vui lòng thử lại.",
            ) from e

        new_video_url = new_upload_res.get("secure_url") or new_upload_res.get("url") or ""
        new_video_storage_key = new_upload_res.get("public_id") or ""
        new_duration_sec = new_upload_res.get("duration")
        new_duration_ms = int(float(new_duration_sec) * 1000) if new_duration_sec is not None else None

        v_width = new_upload_res.get("width")
        v_height = new_upload_res.get("height")
        if v_width and v_height and v_height <= v_width:
            await destroy_asset(new_video_storage_key, resource_type="video")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Video phải có định dạng dọc (portrait 9:16). Vui lòng không tải lên video ngang hoặc vuông.",
            )

        # 3. Lock DB row & commit
        commit_start = time.monotonic()
        tutorial = await self.repo.get_by_id(tutorial_id, for_update=True)
        if not tutorial:
            await destroy_asset(new_video_storage_key, resource_type="video")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy Tutorial với ID {tutorial_id}",
            )

        old_video_storage_key = tutorial.video_storage_key

        try:
            tutorial.video_url = new_video_url
            tutorial.video_storage_key = new_video_storage_key
            tutorial.video_mime_type = "video/mp4"
            tutorial.video_size_bytes = len(video_bytes)
            tutorial.duration_ms = new_duration_ms

            await self.db.commit()
            await self.db.refresh(tutorial)
            commit_duration_ms = int((time.monotonic() - commit_start) * 1000)
            self._log_stage(
                stage="db_commit_completed",
                request_id=request_id,
                tutorial_id=tutorial_id,
                file_size_bytes=len(video_bytes),
                duration_ms=commit_duration_ms,
                status="success",
            )
        except Exception as e:
            commit_duration_ms = int((time.monotonic() - commit_start) * 1000)
            self._log_stage(
                stage="db_commit_failed",
                request_id=request_id,
                tutorial_id=tutorial_id,
                file_size_bytes=len(video_bytes),
                duration_ms=commit_duration_ms,
                status="error",
                error=str(e),
            )
            await self.db.rollback()
            logger.error(f"Failed to update tutorial video in DB, cleaning up new video: {e}")
            await destroy_asset(new_video_storage_key, resource_type="video")
            raise e

        # 4. Post-commit cleanup of old video off critical HTTP path
        if old_video_storage_key and old_video_storage_key != new_video_storage_key:
            asyncio.create_task(
                self._safe_destroy_asset(old_video_storage_key, resource_type="video")
            )

        total_duration_ms = int((time.monotonic() - start_time) * 1000)
        self._log_stage(
            stage="response_completed",
            request_id=request_id,
            tutorial_id=tutorial_id,
            file_size_bytes=len(video_bytes),
            duration_ms=total_duration_ms,
            status="success",
        )
        return tutorial

    async def reorder_tutorials(
        self, payload: AdminTutorialReorderRequest
    ) -> Sequence[Tutorial]:
        """Sắp xếp lại thứ tự các Tutorial trong một nhóm tính năng."""
        tutorials = await self.repo.get_by_ids(payload.tutorial_ids, for_update=True)
        if len(tutorials) != len(payload.tutorial_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Một hoặc nhiều ID Tutorial không tồn tại trong hệ thống.",
            )

        tutorial_map = {t.tutorial_id: t for t in tutorials}
        for tid in payload.tutorial_ids:
            t = tutorial_map[tid]
            if t.feature_key != payload.feature_key:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Tutorial ID {tid} không thuộc tính năng '{payload.feature_key}'.",
                )

        # Reassign sort_order
        for index, tid in enumerate(payload.tutorial_ids):
            tutorial_map[tid].sort_order = (index + 1) * 10

        await self.db.commit()
        return await self.repo.get_all_tutorials(feature_key=payload.feature_key)

    async def delete_tutorial(self, tutorial_id: int) -> dict[str, str]:
        """Xóa vĩnh viễn Tutorial khỏi DB và dọn dẹp video trên Cloudinary."""
        tutorial = await self.repo.get_by_id(tutorial_id, for_update=True)
        if not tutorial:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy Tutorial với ID {tutorial_id}",
            )

        video_storage_key = tutorial.video_storage_key

        await self.repo.delete(tutorial)
        await self.db.commit()

        # Best-effort cleanup after commit
        if video_storage_key:
            try:
                await destroy_asset(video_storage_key, resource_type="video")
            except Exception as e:
                logger.warning(f"Failed to cleanup video {video_storage_key}: {e}")

        return {"message": "Đã xóa Tutorial thành công"}

    def get_upload_signature(self, upload_session_id: str) -> TutorialUploadSignatureResponse:
        """Cấp chữ ký an toàn cho Admin tải trực tiếp video lên Cloudinary (Signed Direct Upload)."""
        sig_data = generate_tutorial_upload_signature(upload_session_id)
        return TutorialUploadSignatureResponse(**sig_data)

    async def confirm_direct_video_replacement(
        self,
        tutorial_id: int,
        payload: AdminTutorialConfirmDirectVideo,
        request_id: str = "unknown",
    ) -> Tutorial:
        """
        Xác thực và thay thế video tutorial từ kết quả tải trực tiếp lên Cloudinary.
        1. Kiểm tra existence của tutorial.
        2. Thẩm định namespace folder của public_id.
        3. Kiểm chứng metadata từ Cloudinary Admin API (resource_type, mp4, <=100MB, dọc 9:16).
        4. Atomic DB update & commit. Giữ video cũ nếu thất bại.
        5. Xóa video cũ sau khi commit thành công.
        """
        start_time = time.monotonic()
        self._log_stage(
            stage="direct_confirm_received",
            request_id=request_id,
            tutorial_id=tutorial_id,
            status="success",
        )

        # 0. Early check existence
        tutorial = await self.repo.get_by_id(tutorial_id)
        if not tutorial:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy Tutorial với ID {tutorial_id}",
            )

        # 1. Thẩm định public_id nằm trong đúng namespace folder và khớp phiên tải lên
        expected_folder = get_tutorial_video_cloudinary_folder()
        clean_public_id = payload.public_id.strip()
        expected_public_id = f"{expected_folder}/tut_{payload.upload_session_id.strip()}"
        if clean_public_id != expected_public_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Public ID video không khớp với phiên tải lên (upload session) hợp lệ.",
            )

        # Idempotency check: nếu tutorial đã trỏ đúng storage key này thì trả về ngay
        if tutorial.video_storage_key == clean_public_id:
            return tutorial

        # Đảm bảo không thể xác nhận video asset đã thuộc về tutorial khác
        existing_with_key = await self.repo.get_by_storage_key(clean_public_id)
        if existing_with_key and existing_with_key.tutorial_id != tutorial_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tệp video này đã thuộc về một video hướng dẫn khác.",
            )

        # 2. Server-side authoritative verification from Cloudinary
        verify_start = time.monotonic()
        try:
            resource = await get_cloudinary_video_resource_async(clean_public_id)
            verify_duration_ms = int((time.monotonic() - verify_start) * 1000)
            self._log_stage(
                stage="direct_verification_completed",
                request_id=request_id,
                tutorial_id=tutorial_id,
                file_size_bytes=resource.get("bytes"),
                duration_ms=verify_duration_ms,
                status="success",
            )
        except Exception as e:
            verify_duration_ms = int((time.monotonic() - verify_start) * 1000)
            self._log_stage(
                stage="direct_verification_failed",
                request_id=request_id,
                tutorial_id=tutorial_id,
                duration_ms=verify_duration_ms,
                status="error",
                error=str(e),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể xác thực tệp video trên Cloudinary. Vui lòng tải lại video.",
            ) from e

        # Validate resource_type
        if resource.get("resource_type") != "video":
            await destroy_asset(clean_public_id, resource_type=resource.get("resource_type") or "raw")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tài nguyên trên Cloudinary không phải video hợp lệ.",
            )

        # Validate format
        fmt = (resource.get("format") or "").lower()
        if fmt not in ("mp4", "m4v"):
            await destroy_asset(clean_public_id, resource_type="video")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Định dạng video không được hỗ trợ. Chỉ chấp nhận tệp video MP4 (video/mp4).",
            )

        # Validate file size
        file_size_bytes = resource.get("bytes") or payload.video_size_bytes or 0
        if file_size_bytes <= 0:
            await destroy_asset(clean_public_id, resource_type="video")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tệp video không được rỗng.",
            )
        if file_size_bytes > MAX_TUTORIAL_VIDEO_SIZE_BYTES:
            await destroy_asset(clean_public_id, resource_type="video")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Dung lượng video vượt quá giới hạn ({MAX_TUTORIAL_VIDEO_SIZE_BYTES // (1024 * 1024)} MB).",
            )

        # Validate aspect ratio
        v_width = resource.get("width")
        v_height = resource.get("height")
        if v_width and v_height and v_height <= v_width:
            await destroy_asset(clean_public_id, resource_type="video")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Video phải có định dạng dọc (portrait 9:16). Vui lòng không tải lên video ngang hoặc vuông.",
            )

        # 3. Lock DB row & update atomically
        commit_start = time.monotonic()
        tutorial = await self.repo.get_by_id(tutorial_id, for_update=True)
        if not tutorial:
            await destroy_asset(clean_public_id, resource_type="video")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy Tutorial với ID {tutorial_id}",
            )

        # Idempotency check: if tutorial already points to this storage key
        if tutorial.video_storage_key == clean_public_id:
            return tutorial

        old_video_storage_key = tutorial.video_storage_key

        raw_url = resource.get("secure_url") or resource.get("url") or payload.secure_url or ""
        delivery_url = get_tutorial_video_delivery_url(raw_url)
        duration_sec = resource.get("duration")
        duration_ms = int(float(duration_sec) * 1000) if duration_sec is not None else payload.duration_ms

        try:
            tutorial.video_url = delivery_url
            tutorial.video_storage_key = clean_public_id
            tutorial.video_mime_type = "video/mp4"
            tutorial.video_size_bytes = file_size_bytes
            tutorial.duration_ms = duration_ms

            await self.db.commit()
            await self.db.refresh(tutorial)
            commit_duration_ms = int((time.monotonic() - commit_start) * 1000)
            self._log_stage(
                stage="db_commit_completed",
                request_id=request_id,
                tutorial_id=tutorial_id,
                file_size_bytes=file_size_bytes,
                duration_ms=commit_duration_ms,
                status="success",
            )
        except Exception as e:
            commit_duration_ms = int((time.monotonic() - commit_start) * 1000)
            self._log_stage(
                stage="db_commit_failed",
                request_id=request_id,
                tutorial_id=tutorial_id,
                file_size_bytes=file_size_bytes,
                duration_ms=commit_duration_ms,
                status="error",
                error=str(e),
            )
            await self.db.rollback()
            logger.error(f"Failed to update tutorial video in DB, cleaning up new video: {e}")
            await destroy_asset(clean_public_id, resource_type="video")
            raise e

        # 4. Post-commit cleanup of old video off critical path
        if old_video_storage_key and old_video_storage_key != clean_public_id:
            asyncio.create_task(
                self._safe_destroy_asset(old_video_storage_key, resource_type="video")
            )

        total_duration_ms = int((time.monotonic() - start_time) * 1000)
        self._log_stage(
            stage="response_completed",
            request_id=request_id,
            tutorial_id=tutorial_id,
            file_size_bytes=file_size_bytes,
            duration_ms=total_duration_ms,
            status="success",
        )
        return tutorial

    async def create_direct_tutorial(
        self,
        current_admin_id: int,
        payload: AdminTutorialCreateDirect,
        request_id: str = "unknown",
    ) -> Tutorial:
        """
        Tạo tutorial mới từ video đã tải trực tiếp lên Cloudinary.
        """
        start_time = time.monotonic()
        self._log_stage(
            stage="direct_create_received",
            request_id=request_id,
            status="success",
        )

        expected_folder = get_tutorial_video_cloudinary_folder()
        clean_public_id = payload.public_id.strip()
        expected_public_id = f"{expected_folder}/tut_{payload.upload_session_id.strip()}"
        if clean_public_id != expected_public_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Public ID video không khớp với phiên tải lên (upload session) hợp lệ.",
            )

        existing_with_key = await self.repo.get_by_storage_key(clean_public_id)
        if existing_with_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tệp video này đã thuộc về một video hướng dẫn khác.",
            )

        # Server-side authoritative verification
        verify_start = time.monotonic()
        try:
            resource = await get_cloudinary_video_resource_async(clean_public_id)
            verify_duration_ms = int((time.monotonic() - verify_start) * 1000)
            self._log_stage(
                stage="direct_verification_completed",
                request_id=request_id,
                file_size_bytes=resource.get("bytes"),
                duration_ms=verify_duration_ms,
                status="success",
            )
        except Exception as e:
            verify_duration_ms = int((time.monotonic() - verify_start) * 1000)
            self._log_stage(
                stage="direct_verification_failed",
                request_id=request_id,
                duration_ms=verify_duration_ms,
                status="error",
                error=str(e),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể xác thực tệp video trên Cloudinary. Vui lòng tải lại video.",
            ) from e

        if resource.get("resource_type") != "video":
            await destroy_asset(clean_public_id, resource_type=resource.get("resource_type") or "raw")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tài nguyên trên Cloudinary không phải video hợp lệ.",
            )

        fmt = (resource.get("format") or "").lower()
        if fmt not in ("mp4", "m4v"):
            await destroy_asset(clean_public_id, resource_type="video")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Định dạng video không được hỗ trợ. Chỉ chấp nhận tệp video MP4 (video/mp4).",
            )

        file_size_bytes = resource.get("bytes") or payload.video_size_bytes or 0
        if file_size_bytes <= 0:
            await destroy_asset(clean_public_id, resource_type="video")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tệp video không được rỗng.",
            )
        if file_size_bytes > MAX_TUTORIAL_VIDEO_SIZE_BYTES:
            await destroy_asset(clean_public_id, resource_type="video")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Dung lượng video vượt quá giới hạn ({MAX_TUTORIAL_VIDEO_SIZE_BYTES // (1024 * 1024)} MB).",
            )

        v_width = resource.get("width")
        v_height = resource.get("height")
        if v_width and v_height and v_height <= v_width:
            await destroy_asset(clean_public_id, resource_type="video")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Video phải có định dạng dọc (portrait 9:16). Vui lòng không tải lên video ngang hoặc vuông.",
            )

        raw_url = resource.get("secure_url") or resource.get("url") or payload.secure_url or ""
        delivery_url = get_tutorial_video_delivery_url(raw_url)
        duration_sec = resource.get("duration")
        duration_ms = int(float(duration_sec) * 1000) if duration_sec is not None else payload.duration_ms

        commit_start = time.monotonic()
        try:
            max_order = await self.repo.get_max_sort_order(payload.feature_key)
            new_order = max_order + 10

            tutorial = Tutorial(
                feature_key=payload.feature_key,
                title=payload.title,
                description=payload.description,
                video_url=delivery_url,
                video_storage_key=clean_public_id,
                video_mime_type="video/mp4",
                video_size_bytes=file_size_bytes,
                duration_ms=duration_ms,
                action_key=payload.action_key,
                sort_order=new_order,
                is_published=payload.is_published,
                created_by=current_admin_id,
            )
            await self.repo.create(tutorial)
            await self.db.commit()
            await self.db.refresh(tutorial)
            commit_duration_ms = int((time.monotonic() - commit_start) * 1000)
            self._log_stage(
                stage="db_commit_completed",
                request_id=request_id,
                tutorial_id=tutorial.tutorial_id,
                file_size_bytes=file_size_bytes,
                duration_ms=commit_duration_ms,
                status="success",
            )
        except Exception as e:
            commit_duration_ms = int((time.monotonic() - commit_start) * 1000)
            self._log_stage(
                stage="db_commit_failed",
                request_id=request_id,
                file_size_bytes=file_size_bytes,
                duration_ms=commit_duration_ms,
                status="error",
                error=str(e),
            )
            await self.db.rollback()
            logger.error(f"Failed to persist direct tutorial in DB, cleaning up Cloudinary video: {e}")
            await destroy_asset(clean_public_id, resource_type="video")
            raise e

        total_duration_ms = int((time.monotonic() - start_time) * 1000)
        self._log_stage(
            stage="response_completed",
            request_id=request_id,
            tutorial_id=tutorial.tutorial_id,
            file_size_bytes=file_size_bytes,
            duration_ms=total_duration_ms,
            status="success",
        )
        return tutorial
