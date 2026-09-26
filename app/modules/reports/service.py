from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Any, Literal, Optional
import urllib.parse

from fastapi import HTTPException, status, UploadFile
from fastapi.responses import StreamingResponse
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.media_validation import validate_image_bytes
from app.integrations.cloudinary import (
    build_transformed_url,
    destroy_asset,
    destroy_image,
    upload_report_evidence,
)
from app.modules.auctions.models import Auction, AuctionStatus
from app.modules.auctions.repository import AuctionRepository
from app.modules.auctions.websocket import publish_auction_event
from app.modules.orders.models import Order
from app.modules.orders.repository import OrderRepository
from app.modules.orders.websocket import revoke_user_sessions
from app.modules.products.models import ListingType, Product, ProductStatus, ProductModerationStatus
from app.modules.products.repository import ProductRepository
from app.modules.reports.models import (
    AdminReportQueueState,
    ModerationAction,
    ModerationActionOption,
    ModerationActionType,
    Report,
    ReportAttachment,
    ReportConclusion,
    ReportReason,
    ReportStatus,
    ReportTargetType,
    ReportWorkflowState,
)
from app.modules.reports.repository import (
    ReportRepository,
    decode_cursor,
    encode_cursor,
)
from app.modules.reports.schemas import (
    AdminCapabilityRestrictionResponse,
    AdminEnforcementRequest,
    AdminHandlerSummary,
    AdminReportDetailResponse,
    AdminReportListResponse,
    AdminReportResponse,
    ModerationActionSummary,
    OrderTargetSummary,
    ProductTargetSummary,
    ReportCreateRequest,
    ReportEvidenceMetadata,
    ReportEvidenceUploadResponse,
    ReportedSubjectSummary,
    ReporterSummary,
    SubjectReportHistoryEnforcementAction,
    SubjectReportHistoryItem,
    SubjectReportHistoryResponse,
    UserTargetSummary,

)
from app.modules.notifications.models import NotificationType
from app.modules.notifications.schemas import NotificationResponse
from app.modules.notifications.service import (
    NotificationService,
    format_notification,
    safe_publish_user_notification,
    dispatch_notification_snapshots,
)
from app.modules.users.capability_models import (
    CapabilityType,
    UserCapabilityRestriction,
)
from app.modules.users.capability_repository import CapabilityRestrictionRepository
from app.modules.users.models import User, UserRole, UserStatus
from app.modules.users.repository import UserRepository

logger = logging.getLogger("app")

MAX_EVIDENCE_PER_REPORT = 6  # Tối đa 5 ảnh + 1 video
MAX_IMAGE_EVIDENCE_PER_REPORT = 5
MAX_VIDEO_EVIDENCE_PER_REPORT = 1
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_VIDEO_SIZE_BYTES = 30 * 1024 * 1024  # 30 MB
MAX_VIDEO_DURATION_SECONDS = 60.0

ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_VIDEO_MIME_TYPES = {"video/mp4", "video/webm", "video/quicktime"}
ALLOWED_EVIDENCE_MIME_TYPES = ALLOWED_IMAGE_MIME_TYPES | ALLOWED_VIDEO_MIME_TYPES


def validate_storage_url_safety(target_url: str) -> None:
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


def _validate_evidence_file(file_name: str, file_bytes: bytes) -> tuple[str, str]:
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


class ReportService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.report_repo = ReportRepository(db)
        self.user_repo = UserRepository(db)
        self.product_repo = ProductRepository(db)
        self.auction_repo = AuctionRepository(db)
        self.order_repo = OrderRepository(db)
        self.cap_repo = CapabilityRestrictionRepository(db)

    async def _create_reporter_terminal_notification(
        self, report: Report, is_resolved: bool
    ) -> Optional[tuple[int, NotificationResponse]]:
        try:
            notif_service = NotificationService(self.db)
            if is_resolved:
                title = "Báo cáo của bạn đã được xử lý"
                body = "Báo cáo vi phạm của bạn đã được quản trị viên xem xét và xử lý."
            else:
                title = "Báo cáo của bạn đã được xem xét"
                body = "Báo cáo vi phạm của bạn đã được quản trị viên xem xét và kết luận không có vi phạm."
            notif = await notif_service.create_notification(
                user_id=report.reporter_id,
                type=NotificationType.SYSTEM.value,
                title=title,
                body=body,
                ref_type="REPORT",
                ref_id=report.report_id,
            )
            return (report.reporter_id, format_notification(notif))
        except Exception as e:
            logger.warning("Could not dispatch reporter notification for report %s: %s", report.report_id, e)
            return None

    async def _create_capability_enforcement_notification(
        self,
        target_user_id: int,
        report_id: int,
        cap_strs: list[str],
        is_restrict: bool,
        expires_at: Optional[datetime] = None,
    ) -> Optional[tuple[int, NotificationResponse]]:
        try:
            notif_service = NotificationService(self.db)
            caps_desc = (
                "mua hàng và bán hàng"
                if len(cap_strs) > 1
                else ("mua hàng" if "BUY" in cap_strs else "bán hàng")
            )
            if is_restrict:
                title = "Quyền tài khoản của bạn đã được cập nhật"
                expiry_str = expires_at.strftime("%d/%m/%Y") if expires_at else ""
                body = f"Quyền {caps_desc} của bạn bị tạm hạn chế đến {expiry_str}."
            else:
                title = "Quyền tài khoản của bạn đã được khôi phục"
                body = f"Quyền {caps_desc} của bạn đã được khôi phục."

            notif = await notif_service.create_notification(
                user_id=target_user_id,
                type=NotificationType.SYSTEM.value,
                title=title,
                body=body,
                ref_type="ACCOUNT_ACCESS",
                ref_id=report_id,
            )
            return (target_user_id, format_notification(notif))
        except Exception as e:
            logger.warning("Could not dispatch capability notification for user %s: %s", target_user_id, e)
            return None

    async def _resolve_subject_from_report(
        self, report: Report
    ) -> tuple[Optional[User], Optional[str]]:
        """
        Derives the subject user and role_in_order from a report.
        For USER reports: target_id is the user_id, role_in_order is None.
        For ORDER reports: counterparty is resolved based on reporter_id.
        For PRODUCT reports: returns (None, None).
        """
        if report.target_type == ReportTargetType.USER.value:
            user = await self.user_repo.get_by_id(report.target_id)
            return user, None
        elif report.target_type == ReportTargetType.ORDER.value:
            order = await self.order_repo.get_order_by_id(report.target_id)
            if not order:
                return None, None
            if report.reporter_id == order.buyer_id:
                counterparty_id = order.seller_id
                role_in_order = "SELLER"
            elif report.reporter_id == order.seller_id:
                counterparty_id = order.buyer_id
                role_in_order = "BUYER"
            else:
                return None, None
            user = await self.user_repo.get_by_id(counterparty_id)
            return user, role_in_order
        return None, None

    async def create_report(
        self, current_user: User, payload: ReportCreateRequest
    ) -> Report:
        # 1. Resolve and validate target according to canonical access rules
        if payload.target_type == ReportTargetType.USER:
            # Self-report rejection
            if payload.target_id == current_user.user_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Không thể tự báo cáo chính mình.",
                )

            # Canonical Public Profile / user lookup rule
            target_user = await self.user_repo.get_by_id(payload.target_id)
            if not target_user or target_user.status != UserStatus.ACTIVE:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Không tìm thấy người dùng.",
                )

        elif payload.target_type == ReportTargetType.PRODUCT:
            # Canonical Product detail access logic
            product = await self.product_repo.get_by_id(
                payload.target_id, include_deleted=False
            )
            if not product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found.",
                )

            # Hidden visibility rule: only seller, admin, or winner with active right can view
            if product.status == ProductStatus.HIDDEN.value:
                is_authorized = False
                if (
                    current_user.user_id == product.seller_id
                    or current_user.role == "ADMIN"
                ):
                    is_authorized = True
                else:
                    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                    won_auction = await self.auction_repo.get_latest_ended_auction_with_active_winner_right(
                        product.product_id, now_utc=now_utc
                    )
                    if won_auction and won_auction.winner_id == current_user.user_id:
                        is_authorized = True

                if not is_authorized:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Product not found.",
                    )

            # Own product report rejection
            if product.seller_id == current_user.user_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Không thể báo cáo sản phẩm của chính mình.",
                )

        elif payload.target_type == ReportTargetType.ORDER:
            # Canonical Order detail access logic: only buyer and seller can access
            order = await self.order_repo.get_order_by_id(payload.target_id)
            if not order or (
                order.buyer_id != current_user.user_id
                and order.seller_id != current_user.user_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Không tìm thấy đơn hàng.",
                )

        # 2. Sequential active duplicate check (OPEN or REVIEWING)
        is_dup = await self.report_repo.has_active_report(
            reporter_id=current_user.user_id,
            target_type=payload.target_type.value,
            target_id=payload.target_id,
        )
        if is_dup:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Bạn đã gửi báo cáo cho đối tượng này và đang được xử lý.",
            )

        # 3. Create Report record
        report = Report(
            reporter_id=current_user.user_id,
            target_type=payload.target_type.value,
            target_id=payload.target_id,
            reason=payload.reason.value,
            description=payload.description,
            status=ReportStatus.OPEN.value,
            handled_by=None,
            handled_at=None,
        )

        await self.report_repo.create(report)

        # Notify active admins of new report
        notif_service = NotificationService(self.db)
        admin_snapshots = await notif_service.notify_admins(
            title="Có báo cáo vi phạm mới",
            body=f"Một báo cáo {report.target_type} mới đang chờ xử lý.",
            ref_type="ADMIN_REPORT",
            ref_id=report.report_id,
        )

        await self.db.commit()
        await self.db.refresh(report)

        # Post-commit best-effort realtime dispatch
        await dispatch_notification_snapshots(admin_snapshots)

        return report

    async def _batch_resolve_targets(
        self, reports: list[Report]
    ) -> dict[tuple[str, int], tuple[bool, Optional[Any]]]:
        """
        Batch resolves polymorphic targets for a page of reports in O(1) query count.
        Returns a dictionary mapping (target_type, target_id) -> (target_available, target_summary).
        """
        result_map: dict[tuple[str, int], tuple[bool, Optional[Any]]] = {}
        if not reports:
            return result_map

        user_ids = {
            r.target_id
            for r in reports
            if r.target_type == ReportTargetType.USER.value
        }
        product_ids = {
            r.target_id
            for r in reports
            if r.target_type == ReportTargetType.PRODUCT.value
        }
        order_ids = {
            r.target_id
            for r in reports
            if r.target_type == ReportTargetType.ORDER.value
        }

        # 1. Batch load users
        if user_ids:
            stmt = select(User).where(User.user_id.in_(user_ids))
            res = await self.db.execute(stmt)
            for u in res.scalars().all():
                summary = UserTargetSummary(
                    user_id=u.user_id,
                    full_name=u.full_name,
                    avatar_url=u.avatar_url,
                    status=u.status.value if hasattr(u.status, "value") else str(u.status),
                    role=u.role,
                )
                result_map[(ReportTargetType.USER.value, u.user_id)] = (True, summary)

        # 2. Batch load products (including soft-deleted)
        if product_ids:
            stmt = select(Product).where(Product.product_id.in_(product_ids))
            res = await self.db.execute(stmt)
            products = list(res.scalars().all())

            seller_ids = {p.seller_id for p in products if p.seller_id}
            sellers_map: dict[int, AdminHandlerSummary] = {}
            if seller_ids:
                seller_stmt = select(User).where(User.user_id.in_(seller_ids))
                seller_res = await self.db.execute(seller_stmt)
                for s in seller_res.scalars().all():
                    sellers_map[s.user_id] = AdminHandlerSummary(
                        user_id=s.user_id, full_name=s.full_name
                    )

            for p in products:
                seller_summary = sellers_map.get(p.seller_id) if p.seller_id else None
                summary = ProductTargetSummary(
                    product_id=p.product_id,
                    title=p.title,
                    seller=seller_summary,
                    status=str(p.status),
                    moderation_status=ProductModerationStatus(p.moderation_status),
                    is_deleted=bool(p.is_deleted),
                )
                result_map[(ReportTargetType.PRODUCT.value, p.product_id)] = (True, summary)

        # 3. Batch load orders
        if order_ids:
            stmt = select(Order).where(Order.order_id.in_(order_ids))
            res = await self.db.execute(stmt)
            orders = list(res.scalars().all())

            participant_ids = {o.buyer_id for o in orders if o.buyer_id} | {
                o.seller_id for o in orders if o.seller_id
            }
            participants_map: dict[int, AdminHandlerSummary] = {}
            if participant_ids:
                part_stmt = select(User).where(User.user_id.in_(participant_ids))
                part_res = await self.db.execute(part_stmt)
                for part in part_res.scalars().all():
                    participants_map[part.user_id] = AdminHandlerSummary(
                        user_id=part.user_id, full_name=part.full_name
                    )

            for o in orders:
                summary = OrderTargetSummary(
                    order_id=o.order_id,
                    order_code=o.order_code,
                    buyer=participants_map.get(o.buyer_id) if o.buyer_id else None,
                    seller=participants_map.get(o.seller_id) if o.seller_id else None,
                    status=str(o.status),
                    total_amount=int(o.total_amount) if o.total_amount is not None else None,
                )
                result_map[(ReportTargetType.ORDER.value, o.order_id)] = (True, summary)

        # Mark missing targets as target_available=False
        for r in reports:
            key = (r.target_type, r.target_id)
            if key not in result_map:
                result_map[key] = (False, None)

        return result_map

    async def _resolve_single_target(
        self, target_type: str, target_id: int
    ) -> tuple[bool, Optional[Any]]:
        if target_type == ReportTargetType.USER.value:
            user = await self.user_repo.get_by_id(target_id)
            if not user:
                return False, None
            summary = UserTargetSummary(
                user_id=user.user_id,
                full_name=user.full_name,
                avatar_url=user.avatar_url,
                status=user.status.value if hasattr(user.status, "value") else str(user.status),
                role=user.role,
            )
            return True, summary

        elif target_type == ReportTargetType.PRODUCT.value:
            product = await self.product_repo.get_by_id(target_id, include_deleted=True)
            if not product:
                return False, None
            seller = (
                await self.user_repo.get_by_id(product.seller_id)
                if product.seller_id
                else None
            )
            summary = ProductTargetSummary(
                product_id=product.product_id,
                title=product.title,
                seller=AdminHandlerSummary(user_id=seller.user_id, full_name=seller.full_name)
                if seller
                else None,
                status=str(product.status),
                moderation_status=ProductModerationStatus(product.moderation_status),
                is_deleted=bool(product.is_deleted),
            )
            return True, summary

        elif target_type == ReportTargetType.ORDER.value:
            order = await self.order_repo.get_order_by_id(target_id)
            if not order:
                return False, None
            buyer = (
                await self.user_repo.get_by_id(order.buyer_id)
                if order.buyer_id
                else None
            )
            seller = (
                await self.user_repo.get_by_id(order.seller_id)
                if order.seller_id
                else None
            )
            summary = OrderTargetSummary(
                order_id=order.order_id,
                order_code=order.order_code,
                buyer=AdminHandlerSummary(user_id=buyer.user_id, full_name=buyer.full_name)
                if buyer
                else None,
                seller=AdminHandlerSummary(user_id=seller.user_id, full_name=seller.full_name)
                if seller
                else None,
                status=str(order.status),
                total_amount=int(order.total_amount) if order.total_amount is not None else None,
            )
            return True, summary

        return False, None

    def _build_admin_report_response(
        self,
        report: Report,
        target_available: bool,
        target_summary: Optional[Any],
        evidence_count: int = 0,
    ) -> AdminReportResponse:
        reporter_summary = None
        if report.reporter:
            reporter_summary = ReporterSummary(
                user_id=report.reporter.user_id,
                full_name=report.reporter.full_name,
                avatar_url=report.reporter.avatar_url,
            )

        handler_summary = None
        if report.handler:
            handler_summary = AdminHandlerSummary(
                user_id=report.handler.user_id,
                full_name=report.handler.full_name,
            )

    @staticmethod
    def _project_workflow_and_conclusion(
        status_val: str,
    ) -> tuple[ReportWorkflowState, Optional[ReportConclusion]]:
        if status_val == ReportStatus.OPEN.value:
            return ReportWorkflowState.OPEN, None
        elif status_val == ReportStatus.REVIEWING.value:
            return ReportWorkflowState.REVIEWING, None
        elif status_val == ReportStatus.RESOLVED.value:
            return ReportWorkflowState.COMPLETED, ReportConclusion.SUPPORTED
        elif status_val == ReportStatus.REJECTED.value:
            return ReportWorkflowState.COMPLETED, ReportConclusion.INSUFFICIENT_EVIDENCE
        return ReportWorkflowState.OPEN, None

    @staticmethod
    def _compute_available_moderation_actions(
        status_val: str,
    ) -> list[ModerationActionOption]:
        if status_val == ReportStatus.OPEN.value:
            return [
                ModerationActionOption.START_REVIEW,
                ModerationActionOption.CONFIRM_SUPPORTED,
                ModerationActionOption.MARK_INSUFFICIENT_EVIDENCE,
            ]
        elif status_val == ReportStatus.REVIEWING.value:
            return [
                ModerationActionOption.CONFIRM_SUPPORTED,
                ModerationActionOption.MARK_INSUFFICIENT_EVIDENCE,
            ]
        return []

    def _build_admin_report_response(
        self,
        report: Report,
        target_available: bool,
        target_summary: Optional[Any],
        evidence_count: int = 0,
    ) -> AdminReportResponse:
        reporter_summary = None
        if report.reporter:
            reporter_summary = ReporterSummary(
                user_id=report.reporter.user_id,
                full_name=report.reporter.full_name,
                avatar_url=report.reporter.avatar_url,
            )

        handler_summary = None
        if report.handler:
            handler_summary = AdminHandlerSummary(
                user_id=report.handler.user_id,
                full_name=report.handler.full_name,
            )

        workflow_state, conclusion = self._project_workflow_and_conclusion(report.status)

        return AdminReportResponse(
            report_id=report.report_id,
            reporter_id=report.reporter_id,
            reporter=reporter_summary,
            target_type=ReportTargetType(report.target_type),
            target_id=report.target_id,
            target_available=target_available,
            target_summary=target_summary,
            reason=ReportReason(report.reason),
            description=report.description,
            status=ReportStatus(report.status),
            workflow_state=workflow_state,
            conclusion=conclusion,
            handled_by=report.handled_by,
            handler=handler_summary,
            handled_at=report.handled_at,
            created_at=report.created_at,
            evidence_count=evidence_count,
        )

    def _build_admin_report_detail_response(
        self,
        report: Report,
        target_available: bool,
        target_summary: Optional[Any],
        evidence: list[ReportAttachment],
        enforcement_actions: Optional[list[ModerationActionSummary]] = None,
        available_enforcement_actions: Optional[list[ModerationActionType]] = None,
        reported_subject: Optional[ReportedSubjectSummary] = None,
    ) -> AdminReportDetailResponse:
        base = self._build_admin_report_response(
            report=report,
            target_available=target_available,
            target_summary=target_summary,
            evidence_count=len(evidence),
        )
        available_moderation_actions = self._compute_available_moderation_actions(report.status)
        return AdminReportDetailResponse(
            **base.model_dump(),
            evidence=[ReportEvidenceMetadata.model_validate(a) for a in evidence],
            enforcement_actions=enforcement_actions or [],
            available_moderation_actions=available_moderation_actions,
            available_enforcement_actions=available_enforcement_actions or [],
            reported_subject=reported_subject,
        )

    async def _compute_available_enforcement_actions(
        self, report: Report, current_admin: User
    ) -> list[str]:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        if report.target_type in (ReportTargetType.USER.value, ReportTargetType.ORDER.value):
            subject_user, _ = await self._resolve_subject_from_report(report)
            if not subject_user:
                return []

            # Admin target protection: if target is ADMIN or is current admin, no enforcement
            if (
                subject_user.role == UserRole.ADMIN.value
                or subject_user.user_id == current_admin.user_id
            ):
                return []

            actions: list[str] = []

            # Check capability restore: if subject has active restrictions originated from this report
            active_from_this_report = await self.cap_repo.get_active_restrictions_by_source_report(
                subject_user.user_id, report.report_id, now_utc=now_utc
            )
            if active_from_this_report:
                actions.append("CAPABILITY_RESTORE")

            if subject_user.status == UserStatus.ACTIVE:
                if report.status in (ReportStatus.OPEN.value, ReportStatus.REVIEWING.value):
                    actions.append("USER_BAN")
                    active_all = await self.cap_repo.get_active_restrictions_by_user(
                        subject_user.user_id, now_utc=now_utc
                    )
                    restricted_caps = {r.capability for r in active_all}
                    if len(restricted_caps) < 2:
                        actions.append("CAPABILITY_RESTRICT")

            elif subject_user.status == UserStatus.BANNED:
                latest_action = await self.report_repo.get_latest_moderation_action_for_target(
                    ReportTargetType.USER.value,
                    subject_user.user_id,
                    action_types=[
                        ModerationActionType.USER_BAN.value,
                        ModerationActionType.USER_UNBAN.value,
                    ],
                )
                if (
                    latest_action
                    and latest_action.action_type == ModerationActionType.USER_BAN.value
                    and latest_action.report_id == report.report_id
                ):
                    actions.append("USER_UNBAN")

            return actions

        elif report.target_type == ReportTargetType.PRODUCT.value:
            product = await self.product_repo.get_by_id(report.target_id, include_deleted=True)
            if not product or product.is_deleted:
                return []

            if product.moderation_status == ProductModerationStatus.CLEAR.value:
                if report.status in (ReportStatus.OPEN.value, ReportStatus.REVIEWING.value):
                    return ["PRODUCT_HIDE"]
                return []

            if product.moderation_status == ProductModerationStatus.BLOCKED.value:
                latest_action = await self.report_repo.get_latest_moderation_action_for_target(
                    ReportTargetType.PRODUCT.value, product.product_id
                )
                if (
                    latest_action
                    and latest_action.action_type == ModerationActionType.PRODUCT_HIDE.value
                    and latest_action.report_id == report.report_id
                ):
                    return ["PRODUCT_RESTORE"]
                return []

            return []


        return []

    async def list_admin_reports(
        self,
        current_admin: User,
        limit: int = 20,
        cursor: Optional[str] = None,
        report_status: Optional[ReportStatus] = None,
        workflow: Optional[ReportWorkflowState] = None,
        conclusion: Optional[ReportConclusion] = None,
        queue_state: Optional[AdminReportQueueState] = None,
        target_type: Optional[ReportTargetType] = None,
    ) -> AdminReportListResponse:
        if queue_state is not None and (
            report_status is not None or workflow is not None or conclusion is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Không được kết hợp tham số lọc 'queue_state' với 'status', 'workflow', hoặc 'conclusion'.",
            )

        if report_status is not None and (workflow is not None or conclusion is not None):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Không được kết hợp tham số lọc 'status' truyền thống với 'workflow' hoặc 'conclusion'.",
            )

        target_statuses: Optional[list[str]] = None
        target_status_single: Optional[str] = None

        if queue_state is not None:
            if queue_state == AdminReportQueueState.NEEDS_ACTION:
                target_statuses = [ReportStatus.OPEN.value, ReportStatus.REVIEWING.value]
            elif queue_state == AdminReportQueueState.COMPLETED:
                target_statuses = [ReportStatus.RESOLVED.value, ReportStatus.REJECTED.value]
        elif report_status is not None:
            target_status_single = report_status.value
        elif conclusion is not None:
            if workflow in (ReportWorkflowState.OPEN, ReportWorkflowState.REVIEWING):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Không thể lọc kết luận ('conclusion') khi luồng xử lý ('workflow') chưa hoàn tất.",
                )
            if conclusion == ReportConclusion.SUPPORTED:
                target_status_single = ReportStatus.RESOLVED.value
            elif conclusion == ReportConclusion.INSUFFICIENT_EVIDENCE:
                target_status_single = ReportStatus.REJECTED.value
        elif workflow is not None:
            if workflow == ReportWorkflowState.OPEN:
                target_status_single = ReportStatus.OPEN.value
            elif workflow == ReportWorkflowState.REVIEWING:
                target_status_single = ReportStatus.REVIEWING.value
            elif workflow == ReportWorkflowState.COMPLETED:
                target_statuses = [ReportStatus.RESOLVED.value, ReportStatus.REJECTED.value]

        cursor_tuple = None
        if cursor:
            try:
                cursor_tuple = decode_cursor(cursor)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Invalid pagination cursor.",
                ) from e

        reports, has_more, next_cursor_tuple = (
            await self.report_repo.list_admin_reports_cursor(
                limit=limit,
                cursor=cursor_tuple,
                status=target_status_single,
                statuses=target_statuses,
                target_type=target_type.value if target_type else None,
            )
        )

        target_map = await self._batch_resolve_targets(reports)
        report_ids = [r.report_id for r in reports]
        evidence_counts = await self.report_repo.batch_count_attachments(report_ids)

        items = [
            self._build_admin_report_response(
                report=r,
                target_available=target_map[(r.target_type, r.target_id)][0],
                target_summary=target_map[(r.target_type, r.target_id)][1],
                evidence_count=evidence_counts.get(r.report_id, 0),
            )
            for r in reports
        ]

        next_cursor_str = (
            encode_cursor(next_cursor_tuple[0], next_cursor_tuple[1])
            if next_cursor_tuple
            else None
        )

        return AdminReportListResponse(
            items=items,
            next_cursor=next_cursor_str,
            has_more=has_more,
        )

    async def get_admin_report_detail(
        self, current_admin: User, report_id: int
    ) -> AdminReportDetailResponse:
        report = await self.report_repo.get_by_id(
            report_id, for_update=False, eager_load=True
        )
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Báo cáo không tồn tại.",
            )

        target_available, target_summary = await self._resolve_single_target(
            report.target_type, report.target_id
        )
        attachments = await self.report_repo.list_attachments_by_report(report_id)
        raw_actions = await self.report_repo.list_moderation_actions_by_report(report_id)
        enforcement_actions = [
            ModerationActionSummary(
                moderation_action_id=a.moderation_action_id,
                action_type=ModerationActionType(a.action_type),
                previous_status=a.previous_status,
                new_status=a.new_status,
                admin=AdminHandlerSummary(
                    user_id=a.admin.user_id,
                    full_name=a.admin.full_name,
                )
                if a.admin
                else None,
                created_at=a.created_at,
            )
            for a in raw_actions
        ]
        available_enforcements = await self._compute_available_enforcement_actions(
            report, current_admin
        )

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        reported_subject = None
        if report.target_type in (ReportTargetType.USER.value, ReportTargetType.ORDER.value):
            subject_user, role_in_order = await self._resolve_subject_from_report(report)
            if subject_user:
                active_restrictions = await self.cap_repo.get_active_restrictions_by_user(
                    subject_user.user_id, now_utc=now_utc
                )
                restricted_caps = {r.capability for r in active_restrictions}
                can_buy = (
                    subject_user.status == UserStatus.ACTIVE
                    and CapabilityType.BUY.value not in restricted_caps
                )
                can_sell = (
                    subject_user.status == UserStatus.ACTIVE
                    and CapabilityType.SELL.value not in restricted_caps
                )
                prior_report_count = await self.report_repo.count_subject_reports(
                    subject_user.user_id, exclude_report_id=report.report_id
                )
                reported_subject = ReportedSubjectSummary(
                    user_id=subject_user.user_id,
                    full_name=subject_user.full_name,
                    avatar_url=subject_user.avatar_url,
                    status=subject_user.status.value if hasattr(subject_user.status, "value") else str(subject_user.status),
                    role=subject_user.role,
                    role_in_order=role_in_order,
                    can_buy=can_buy,
                    can_sell=can_sell,
                    active_restrictions=[
                        AdminCapabilityRestrictionResponse.model_validate(r)
                        for r in active_restrictions
                    ],
                    prior_report_count=prior_report_count,
                )

        return self._build_admin_report_detail_response(
            report=report,
            target_available=target_available,
            target_summary=target_summary,
            evidence=attachments,
            enforcement_actions=enforcement_actions,
            available_enforcement_actions=available_enforcements,
            reported_subject=reported_subject,
        )

    async def get_subject_report_history(
        self,
        current_admin: User,
        subject_user_id: int,
        limit: int = 5,
        cursor: Optional[str] = None,
        exclude_report_id: Optional[int] = None,
    ) -> SubjectReportHistoryResponse:
        user = await self.user_repo.get_by_id(subject_user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Người dùng không tồn tại.",
            )

        cursor_tuple = None
        if cursor:
            try:
                cursor_tuple = decode_cursor(cursor)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Invalid pagination cursor.",
                ) from e

        reports, has_more, next_cursor_tuple = (
            await self.report_repo.list_subject_reports_cursor(
                subject_user_id=subject_user_id,
                limit=limit,
                cursor=cursor_tuple,
                exclude_report_id=exclude_report_id,
            )
        )

        total_count = await self.report_repo.count_subject_reports(
            subject_user_id=subject_user_id,
            exclude_report_id=exclude_report_id,
        )

        report_ids = [r.report_id for r in reports]
        evidence_counts = await self.report_repo.batch_count_attachments(report_ids)
        actions_map = await self.report_repo.batch_list_moderation_actions(report_ids)

        items = []
        for r in reports:
            acts = actions_map.get(r.report_id, [])
            enforcement_actions = [
                SubjectReportHistoryEnforcementAction(
                    action_type=ModerationActionType(a.action_type),
                    previous_status=a.previous_status,
                    new_status=a.new_status,
                )
                for a in acts
            ]
            items.append(
                SubjectReportHistoryItem(
                    report_id=r.report_id,
                    target_type=ReportTargetType(r.target_type),
                    reason=ReportReason(r.reason),
                    status=ReportStatus(r.status),
                    created_at=r.created_at,
                    handled_at=r.handled_at,
                    evidence_count=evidence_counts.get(r.report_id, 0),
                    enforcement_actions=enforcement_actions,
                )
            )

        next_cursor_str = (
            encode_cursor(next_cursor_tuple[0], next_cursor_tuple[1])
            if next_cursor_tuple
            else None
        )

        return SubjectReportHistoryResponse(
            user_id=subject_user_id,
            items=items,
            next_cursor=next_cursor_str,
            has_more=has_more,
            total_count=total_count,
        )


    async def update_admin_report_status(
        self, current_admin: User, report_id: int, new_status: ReportStatus
    ) -> AdminReportDetailResponse:
        report = await self.report_repo.get_by_id(
            report_id, for_update=True, eager_load=False
        )
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Báo cáo không tồn tại.",
            )

        current_status = report.status
        if current_status in (ReportStatus.RESOLVED.value, ReportStatus.REJECTED.value):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Không thể thay đổi trạng thái của báo cáo đã ở trạng thái kết thúc '{current_status}'.",
            )

        allowed_transitions = {
            ReportStatus.OPEN.value: {
                ReportStatus.REVIEWING.value,
                ReportStatus.RESOLVED.value,
                ReportStatus.REJECTED.value,
            },
            ReportStatus.REVIEWING.value: {
                ReportStatus.RESOLVED.value,
                ReportStatus.REJECTED.value,
            },
        }

        if new_status.value not in allowed_transitions.get(current_status, set()):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Chuyển trạng thái từ '{current_status}' sang '{new_status.value}' không hợp lệ.",
            )

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        report.status = new_status.value
        report.handled_by = current_admin.user_id

        reporter_snapshot = None
        if new_status == ReportStatus.REVIEWING:
            report.handled_at = None
        else:  # RESOLVED or REJECTED
            report.handled_at = now_utc
            reporter_snapshot = await self._create_reporter_terminal_notification(
                report, is_resolved=(new_status == ReportStatus.RESOLVED)
            )

        await self.db.commit()

        # Post-commit best-effort realtime dispatch
        if reporter_snapshot:
            await safe_publish_user_notification(reporter_snapshot[0], reporter_snapshot[1])

        return await self.get_admin_report_detail(current_admin, report_id)

    async def enforce_user_action(
        self,
        current_admin: User,
        report_id: int,
        action: ModerationActionType,
    ) -> AdminReportDetailResponse:
        # Step 1: Lock Report
        report = await self.report_repo.get_by_id(
            report_id, for_update=True, eager_load=False
        )
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Báo cáo không tồn tại.",
            )

        # Step 2: Validate report target_type is USER or ORDER
        if report.target_type == ReportTargetType.USER.value:
            target_user_id = report.target_id
        elif report.target_type == ReportTargetType.ORDER.value:
            order = await self.order_repo.get_order_by_id(report.target_id)
            if not order:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Đơn hàng không tồn tại.",
                )
            if report.reporter_id == order.buyer_id:
                target_user_id = order.seller_id
            elif report.reporter_id == order.seller_id:
                target_user_id = order.buyer_id
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Không thể xác định đối tượng liên quan trong đơn hàng.",
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chỉ có thể thực hiện chế tài người dùng trên báo cáo loại Người dùng hoặc Đơn hàng.",
            )

        # Step 3: Derive target_id and Lock User row
        target_user = await self.user_repo.get_by_id_for_update(target_user_id)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Người dùng bị báo cáo không tồn tại.",
            )

        # Step 4: Admin Protection
        if (
            target_user.role == UserRole.ADMIN.value
            or target_user.user_id == current_admin.user_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Không thể áp dụng chế tài lên tài khoản quản trị viên.",
            )

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        # Step 5: Branch by action
        if action == ModerationActionType.USER_BAN:
            # Allowed report states: OPEN, REVIEWING
            if report.status not in (
                ReportStatus.OPEN.value,
                ReportStatus.REVIEWING.value,
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Không thể khóa tài khoản từ báo cáo đã ở trạng thái kết thúc '{report.status}'.",
                )

            if target_user.status == UserStatus.BANNED:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Tài khoản người dùng đã bị khóa trước đó.",
                )

            if target_user.status == UserStatus.INACTIVE:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Không thể áp dụng chế tài lên tài khoản đang ngừng hoạt động.",
                )

            previous_status = (
                target_user.status.value
                if hasattr(target_user.status, "value")
                else str(target_user.status)
            )
            new_status = UserStatus.BANNED.value
            target_user.status = UserStatus.BANNED

            audit_action = ModerationAction(
                report_id=report.report_id,
                admin_id=current_admin.user_id,
                target_type=ReportTargetType.USER.value,
                target_id=target_user.user_id,
                action_type=ModerationActionType.USER_BAN.value,
                previous_status=previous_status,
                new_status=new_status,
                created_at=now_utc,
            )
            await self.report_repo.add_moderation_action(audit_action)

            report.status = ReportStatus.RESOLVED.value
            report.handled_by = current_admin.user_id
            report.handled_at = now_utc

            reporter_snapshot = await self._create_reporter_terminal_notification(
                report, is_resolved=True
            )

            # Single atomic commit
            await self.db.commit()

            # Post-commit best-effort reporter notification dispatch
            if reporter_snapshot:
                await safe_publish_user_notification(reporter_snapshot[0], reporter_snapshot[1])

            # ONLY AFTER successful commit: best-effort socket revocation
            try:
                await revoke_user_sessions(target_user.user_id)
            except Exception as e:
                logger.warning(
                    "Failed to revoke sockets for banned user %s: %s",
                    target_user.user_id,
                    e,
                )

        elif action == ModerationActionType.USER_UNBAN:
            if target_user.status != UserStatus.BANNED:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Tài khoản người dùng không ở trạng thái bị khóa.",
                )

            # Target latest effective moderation action check scoped to USER_BAN and USER_UNBAN
            latest_action = await self.report_repo.get_latest_moderation_action_for_target(
                ReportTargetType.USER.value,
                target_user.user_id,
                action_types=[
                    ModerationActionType.USER_BAN.value,
                    ModerationActionType.USER_UNBAN.value,
                ],
            )
            if (
                not latest_action
                or latest_action.action_type != ModerationActionType.USER_BAN.value
                or latest_action.report_id != report.report_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Báo cáo này không phải là nguồn tạo ra lệnh khóa tài khoản đang có hiệu lực.",
                )

            previous_status = (
                target_user.status.value
                if hasattr(target_user.status, "value")
                else str(target_user.status)
            )
            new_status = UserStatus.ACTIVE.value
            target_user.status = UserStatus.ACTIVE

            audit_action = ModerationAction(
                report_id=report.report_id,
                admin_id=current_admin.user_id,
                target_type=ReportTargetType.USER.value,
                target_id=target_user.user_id,
                action_type=ModerationActionType.USER_UNBAN.value,
                previous_status=previous_status,
                new_status=new_status,
                created_at=now_utc,
            )
            await self.report_repo.add_moderation_action(audit_action)

            # Report remains RESOLVED; do NOT overwrite handled_by/handled_at
            await self.db.commit()

        return await self.get_admin_report_detail(current_admin, report_id)

    async def enforce_product_action(
        self,
        current_admin: User,
        report_id: int,
        action: ModerationActionType,
    ) -> AdminReportDetailResponse:
        # Step 1: Lock Report FOR UPDATE
        report = await self.report_repo.get_by_id(
            report_id, for_update=True, eager_load=False
        )
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Báo cáo không tồn tại.",
            )

        # Step 2: Validate report target_type is PRODUCT
        if report.target_type != ReportTargetType.PRODUCT.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chỉ có thể thực hiện chế tài tin đăng trên báo cáo loại Tin đăng.",
            )

        # Step 3: Derive product_id and Lock Product row FOR UPDATE (including deleted)
        product = await self.product_repo.get_by_id(
            report.target_id, include_deleted=True, for_update=True
        )
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tin đăng bị báo cáo không tồn tại.",
            )

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        cancelled_auction_id = None

        if action == ModerationActionType.PRODUCT_HIDE:
            # Soft-deleted check: 409 Conflict
            if product.is_deleted:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Không thể ẩn tin đăng đã bị xóa.",
                )

            # Report terminal check
            if report.status not in (
                ReportStatus.OPEN.value,
                ReportStatus.REVIEWING.value,
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Không thể ẩn tin đăng từ báo cáo đã ở trạng thái kết thúc '{report.status}'.",
                )

            # Already blocked check
            if product.moderation_status == ProductModerationStatus.BLOCKED.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Tin đăng đã bị quản trị viên ẩn trước đó.",
                )

            # Lock any SCHEDULED or ACTIVE auction tied to this product
            active_auction = await self.auction_repo.get_active_auction_by_product_id(
                product.product_id, for_update=True
            )
            if active_auction:
                active_auction.status = AuctionStatus.CANCELLED.value
                active_auction.winner_id = None
                active_auction.final_price = None
                active_auction.winner_checkout_deadline = None
                product.listing_type = ListingType.FIXED_PRICE.value
                cancelled_auction_id = active_auction.auction_id

            # Mutate product moderation_status
            previous_status = product.moderation_status
            product.moderation_status = ProductModerationStatus.BLOCKED.value

            audit_action = ModerationAction(
                report_id=report.report_id,
                admin_id=current_admin.user_id,
                target_type=ReportTargetType.PRODUCT.value,
                target_id=product.product_id,
                action_type=ModerationActionType.PRODUCT_HIDE.value,
                previous_status=previous_status,
                new_status=ProductModerationStatus.BLOCKED.value,
                created_at=now_utc,
            )
            await self.report_repo.add_moderation_action(audit_action)

            report.status = ReportStatus.RESOLVED.value
            report.handled_by = current_admin.user_id
            report.handled_at = now_utc

            reporter_snapshot = await self._create_reporter_terminal_notification(
                report, is_resolved=True
            )

            # Single atomic commit
            await self.db.commit()

            # Post-commit best-effort reporter notification dispatch
            if reporter_snapshot:
                await safe_publish_user_notification(reporter_snapshot[0], reporter_snapshot[1])

            # Post-commit best-effort realtime auction cancellation event
            if cancelled_auction_id:
                try:
                    await publish_auction_event(
                        cancelled_auction_id,
                        {
                            "event": "AUCTION_CANCELLED",
                            "auction_id": cancelled_auction_id,
                            "server_time": now_utc.isoformat(),
                        },
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to publish AUCTION_CANCELLED event for auction %s: %s",
                        cancelled_auction_id,
                        e,
                    )

        elif action == ModerationActionType.PRODUCT_RESTORE:
            # Soft-deleted check
            if product.is_deleted:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Không thể gỡ ẩn tin đăng đã bị xóa.",
                )

            if product.moderation_status != ProductModerationStatus.BLOCKED.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Tin đăng không ở trạng thái bị quản trị viên ẩn.",
                )

            # Check latest effective action for this target across all reports
            latest_action = await self.report_repo.get_latest_moderation_action_for_target(
                ReportTargetType.PRODUCT.value, product.product_id
            )
            if (
                not latest_action
                or latest_action.action_type != ModerationActionType.PRODUCT_HIDE.value
                or latest_action.report_id != report.report_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Báo cáo này không phải là nguồn tạo ra lệnh ẩn tin đăng đang có hiệu lực.",
                )

            previous_status = product.moderation_status
            product.moderation_status = ProductModerationStatus.CLEAR.value

            audit_action = ModerationAction(
                report_id=report.report_id,
                admin_id=current_admin.user_id,
                target_type=ReportTargetType.PRODUCT.value,
                target_id=product.product_id,
                action_type=ModerationActionType.PRODUCT_RESTORE.value,
                previous_status=previous_status,
                new_status=ProductModerationStatus.CLEAR.value,
                created_at=now_utc,
            )
            await self.report_repo.add_moderation_action(audit_action)

            # Report remains RESOLVED; do NOT alter handled_by or handled_at!
            await self.db.commit()

        return await self.get_admin_report_detail(current_admin, report_id)

    async def enforce_capability_action(
        self,
        current_admin: User,
        report_id: int,
        payload: AdminEnforcementRequest,
    ) -> AdminReportDetailResponse:
        # Step 1: Lock Report FOR UPDATE
        report = await self.report_repo.get_by_id(
            report_id, for_update=True, eager_load=False
        )
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Báo cáo không tồn tại.",
            )

        # Step 2: Validate report target_type is USER or ORDER
        if report.target_type == ReportTargetType.USER.value:
            subject_user_id = report.target_id
        elif report.target_type == ReportTargetType.ORDER.value:
            order = await self.order_repo.get_order_by_id(report.target_id)
            if not order:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Đơn hàng không tồn tại.",
                )
            if report.reporter_id == order.buyer_id:
                subject_user_id = order.seller_id
            elif report.reporter_id == order.seller_id:
                subject_user_id = order.buyer_id
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Không thể xác định đối tượng liên quan trong đơn hàng.",
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chỉ có thể áp dụng chế tài quyền hạn trên báo cáo loại Người dùng hoặc Đơn hàng.",
            )

        # Step 3: Lock target User row FOR UPDATE
        target_user = await self.user_repo.get_by_id_for_update(subject_user_id)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Người dùng bị báo cáo không tồn tại.",
            )

        # Step 4: Admin Protection
        if (
            target_user.role == UserRole.ADMIN.value
            or target_user.user_id == current_admin.user_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Không thể áp dụng chế tài lên tài khoản quản trị viên.",
            )

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        if payload.action == "CAPABILITY_RESTRICT":
            # Correction 1.A: Target is USER / ACTIVE STUDENT
            if target_user.role != UserRole.STUDENT.value:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Không thể áp dụng chế tài lên tài khoản không phải sinh viên.",
                )
            if target_user.status == UserStatus.BANNED:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Tài khoản người dùng đang bị khóa, không thể giới hạn quyền.",
                )
            if target_user.status == UserStatus.INACTIVE:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Không thể áp dụng chế tài lên tài khoản đang ngừng hoạt động.",
                )

            # Report state check
            if report.status not in (
                ReportStatus.OPEN.value,
                ReportStatus.REVIEWING.value,
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Không thể áp dụng chế tài từ báo cáo đã ở trạng thái kết thúc '{report.status}'.",
                )

            # Deduplicate requested capabilities
            raw_caps = list(dict.fromkeys(payload.capabilities or []))
            cap_strs = [c.value if hasattr(c, "value") else str(c) for c in raw_caps]
            if not cap_strs:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Phải chọn ít nhất một quyền hạn để giới hạn.",
                )

            # Validate duration
            if payload.duration_days not in (1, 3, 7, 14):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Thời hạn giới hạn quyền chỉ chấp nhận 1, 3, 7 hoặc 14 ngày.",
                )

            # Duplicate / concurrency guard: query active restrictions under User lock
            existing_active = await self.cap_repo.get_active_restrictions_for_capabilities(
                target_user.user_id, cap_strs, now_utc=now_utc
            )
            if existing_active:
                conflicting = [r.capability for r in existing_active]
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Người dùng đã bị giới hạn quyền: {', '.join(conflicting)}.",
                )

            expires_at = now_utc + timedelta(days=payload.duration_days)

            # Multi-auction cancellation if SELL restricted:
            # Deterministic lock ordering: Report -> User -> Products ASC -> Auctions ASC
            cancelled_auction_ids: list[int] = []
            if "SELL" in cap_strs:
                stmt = (
                    select(Auction)
                    .join(Product, Product.product_id == Auction.product_id)
                    .where(
                        Product.seller_id == target_user.user_id,
                        Auction.status.in_([
                            AuctionStatus.SCHEDULED.value,
                            AuctionStatus.ACTIVE.value,
                        ]),
                    )
                    .order_by(Product.product_id.asc(), Auction.auction_id.asc())
                    .with_for_update()
                )
                res = await self.db.execute(stmt)
                auctions_to_cancel = list(res.scalars().all())

                for auction in auctions_to_cancel:
                    auction.status = AuctionStatus.CANCELLED.value
                    auction.winner_id = None
                    auction.final_price = None
                    auction.winner_checkout_deadline = None
                    product = await self.product_repo.get_by_id(
                        auction.product_id, for_update=True
                    )
                    if product:
                        product.listing_type = ListingType.FIXED_PRICE.value
                    cancelled_auction_ids.append(auction.auction_id)

            # Persist restriction rows & audit rows
            for cap in cap_strs:
                restriction = UserCapabilityRestriction(
                    user_id=target_user.user_id,
                    source_report_id=report.report_id,
                    imposed_by=current_admin.user_id,
                    capability=cap,
                    starts_at=now_utc,
                    expires_at=expires_at,
                    created_at=now_utc,
                )
                self.cap_repo.add(restriction)

                audit_action_type = (
                    ModerationActionType.BUY_RESTRICT.value
                    if cap == "BUY"
                    else ModerationActionType.SELL_RESTRICT.value
                )
                audit_action = ModerationAction(
                    report_id=report.report_id,
                    admin_id=current_admin.user_id,
                    target_type=ReportTargetType.USER.value,
                    target_id=target_user.user_id,
                    action_type=audit_action_type,
                    previous_status="UNRESTRICTED",
                    new_status="RESTRICTED",
                    created_at=now_utc,
                )
                await self.report_repo.add_moderation_action(audit_action)

            report.status = ReportStatus.RESOLVED.value
            report.handled_by = current_admin.user_id
            report.handled_at = now_utc

            target_snapshot = await self._create_capability_enforcement_notification(
                target_user.user_id, report.report_id, cap_strs, is_restrict=True, expires_at=expires_at
            )
            reporter_snapshot = await self._create_reporter_terminal_notification(
                report, is_resolved=True
            )

            await self.db.commit()

            # Post-commit best-effort realtime notifications
            if target_snapshot:
                await safe_publish_user_notification(target_snapshot[0], target_snapshot[1])
            if reporter_snapshot:
                await safe_publish_user_notification(reporter_snapshot[0], reporter_snapshot[1])

            # Post-commit best-effort realtime emit for cancelled auctions
            for auction_id in cancelled_auction_ids:
                try:
                    await publish_auction_event(
                        auction_id,
                        {
                            "event": "AUCTION_CANCELLED",
                            "auction_id": auction_id,
                            "server_time": now_utc.isoformat(),
                        },
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to publish AUCTION_CANCELLED event for auction %s: %s",
                        auction_id,
                        e,
                    )

        elif payload.action == "CAPABILITY_RESTORE":
            # Correction 1.D: Reversal does NOT require target user to be ACTIVE
            raw_caps = list(dict.fromkeys(payload.capabilities or []))
            cap_strs = [c.value if hasattr(c, "value") else str(c) for c in raw_caps]
            if not cap_strs:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Phải chọn ít nhất một quyền hạn để khôi phục.",
                )

            # Verify same-report active restrictions
            for cap in cap_strs:
                restr = await self.cap_repo.get_effective_by_source_report(
                    report_id=report.report_id,
                    user_id=target_user.user_id,
                    capability=cap,
                    now_utc=now_utc,
                    for_update=True,
                )
                if not restr:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Báo cáo này không có quyền hạn '{cap}' đang có hiệu lực để khôi phục.",
                    )

                restr.revoked_at = now_utc
                restr.revoked_by = current_admin.user_id

                audit_action_type = (
                    ModerationActionType.BUY_RESTORE.value
                    if cap == "BUY"
                    else ModerationActionType.SELL_RESTORE.value
                )
                audit_action = ModerationAction(
                    report_id=report.report_id,
                    admin_id=current_admin.user_id,
                    target_type=ReportTargetType.USER.value,
                    target_id=target_user.user_id,
                    action_type=audit_action_type,
                    previous_status="RESTRICTED",
                    new_status="UNRESTRICTED",
                    created_at=now_utc,
                )
                await self.report_repo.add_moderation_action(audit_action)

            target_snapshot = await self._create_capability_enforcement_notification(
                target_user.user_id, report.report_id, cap_strs, is_restrict=False
            )

            # Report remains RESOLVED; do NOT alter handled_by or handled_at
            await self.db.commit()

            # Post-commit best-effort realtime notification
            if target_snapshot:
                await safe_publish_user_notification(target_snapshot[0], target_snapshot[1])

        return await self.get_admin_report_detail(current_admin, report_id)

    async def enforce_action(
        self,
        current_admin: User,
        report_id: int,
        payload: AdminEnforcementRequest,
    ) -> AdminReportDetailResponse:
        action = payload.action
        if action in (ModerationActionType.USER_BAN.value, ModerationActionType.USER_UNBAN.value, "USER_BAN", "USER_UNBAN"):
            return await self.enforce_user_action(current_admin, report_id, action)
        elif action in (ModerationActionType.PRODUCT_HIDE.value, ModerationActionType.PRODUCT_RESTORE.value, "PRODUCT_HIDE", "PRODUCT_RESTORE"):
            return await self.enforce_product_action(current_admin, report_id, action)
        elif action in ("CAPABILITY_RESTRICT", "CAPABILITY_RESTORE"):
            return await self.enforce_capability_action(current_admin, report_id, payload)
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Hành động chế tài '{action}' không được hỗ trợ.",
            )

    async def upload_evidence(
        self,
        current_user: User,
        report_id: int,
        files: list[UploadFile],
    ) -> ReportEvidenceUploadResponse:
        # A. Pre-check: load report and authorize
        report = await self.report_repo.get_by_id(
            report_id, for_update=False, eager_load=False
        )
        if not report or report.reporter_id != current_user.user_id:
            # Correction 4: Non-owner report access must not leak report existence
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Báo cáo không tồn tại.",
            )

        # Correction 3: 409 Conflict for terminal reports
        if report.status in (ReportStatus.RESOLVED.value, ReportStatus.REJECTED.value):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Không thể thêm minh chứng cho báo cáo đã ở trạng thái kết thúc '{report.status}'.",
            )

        if not files:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Vui lòng chọn ít nhất một tệp minh chứng.",
            )

        existing_attachments = await self.report_repo.get_attachments(report_id)
        existing_images = sum(1 for a in existing_attachments if not a.mime_type.startswith("video/"))
        existing_videos = sum(1 for a in existing_attachments if a.mime_type.startswith("video/"))

        # B. Local validation phase: validate ALL files locally before ANY external upload
        validated_files: list[dict[str, Any]] = []
        new_images = 0
        new_videos = 0
        for file in files:
            file_bytes = await file.read()
            original_filename = file.filename or "evidence"
            canonical_mime, media_type = _validate_evidence_file(original_filename, file_bytes)
            if media_type == "VIDEO":
                new_videos += 1
            else:
                new_images += 1

            validated_files.append({
                "bytes": file_bytes,
                "filename": original_filename,
                "mime_type": canonical_mime,
                "media_type": media_type,
                "size_bytes": len(file_bytes),
            })

        # Check image and video capacity limits
        if existing_images + new_images > MAX_IMAGE_EVIDENCE_PER_REPORT:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT if existing_images > 0 else status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Tổng số ảnh minh chứng vượt quá giới hạn tối đa ({MAX_IMAGE_EVIDENCE_PER_REPORT} ảnh). Hiện báo cáo đã có {existing_images} ảnh.",
            )
        if existing_videos + new_videos > MAX_VIDEO_EVIDENCE_PER_REPORT:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT if existing_videos > 0 else status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Tổng số video minh chứng vượt quá giới hạn tối đa ({MAX_VIDEO_EVIDENCE_PER_REPORT} video). Hiện báo cáo đã có {existing_videos} video.",
            )

        # C. External upload phase: upload to Cloudinary while tracking every created asset
        uploaded_assets: list[tuple[str, str]] = []  # (public_id, resource_type)
        upload_records: list[dict[str, Any]] = []
        try:
            for item in validated_files:
                res_type = "video" if item["media_type"] == "VIDEO" else "image"
                res = upload_report_evidence(
                    file=item["bytes"],
                    report_id=report_id,
                    original_filename=item["filename"],
                    resource_type=res_type,
                )
                pid = res["public_id"]
                uploaded_assets.append((pid, res_type))

                # Video duration validation from trusted Cloudinary upload metadata
                if item["media_type"] == "VIDEO":
                    duration = res.get("duration")
                    if duration is not None and float(duration) > MAX_VIDEO_DURATION_SECONDS:
                        for p, rt in uploaded_assets:
                            if rt == "video":
                                destroy_asset(p, resource_type="video")
                            else:
                                destroy_image(p)
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail=f"Thời lượng video '{item['filename']}' vượt quá giới hạn tối đa ({int(MAX_VIDEO_DURATION_SECONDS)} giây). Thời lượng thực tế: {round(float(duration), 1)} giây.",
                        )

                upload_records.append({
                    "url": res.get("secure_url") or res.get("url"),
                    "storage_key": pid,
                    "mime_type": item["mime_type"],
                    "original_name": item["filename"],
                    "size_bytes": item["size_bytes"],
                })
        except HTTPException:
            raise
        except Exception as e:
            for pid, rt in uploaded_assets:
                if rt == "video":
                    destroy_asset(pid, resource_type="video")
                else:
                    destroy_image(pid)
            logger.error(f"Cloudinary upload error during evidence upload for report {report_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Lỗi khi tải tệp lên dịch vụ lưu trữ.",
            ) from e

        # D. DB transaction: lock Report row FOR UPDATE
        try:
            locked_report = await self.report_repo.get_by_id(
                report_id, for_update=True, eager_load=False
            )
            # E. Re-check under lock
            if not locked_report or locked_report.reporter_id != current_user.user_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Báo cáo không tồn tại.",
                )
            if locked_report.status in (ReportStatus.RESOLVED.value, ReportStatus.REJECTED.value):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Không thể thêm minh chứng cho báo cáo đã ở trạng thái kết thúc '{locked_report.status}'.",
                )
            locked_existing = await self.report_repo.get_attachments(report_id)
            locked_images = sum(1 for a in locked_existing if not a.mime_type.startswith("video/"))
            locked_videos = sum(1 for a in locked_existing if a.mime_type.startswith("video/"))

            if locked_images + new_images > MAX_IMAGE_EVIDENCE_PER_REPORT:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Tổng số ảnh minh chứng vượt quá giới hạn tối đa ({MAX_IMAGE_EVIDENCE_PER_REPORT} ảnh).",
                )
            if locked_videos + new_videos > MAX_VIDEO_EVIDENCE_PER_REPORT:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Tổng số video minh chứng vượt quá giới hạn tối đa ({MAX_VIDEO_EVIDENCE_PER_REPORT} video).",
                )

            # F. Persist ReportAttachment rows
            new_attachments = [
                ReportAttachment(
                    report_id=report_id,
                    url=rec["url"],
                    storage_key=rec["storage_key"],
                    mime_type=rec["mime_type"],
                    original_name=rec["original_name"],
                    size_bytes=rec["size_bytes"],
                )
                for rec in upload_records
            ]
            created = await self.report_repo.add_attachments(new_attachments)

            # G. Commit once
            await self.db.commit()
            for a in created:
                await self.db.refresh(a)

            return ReportEvidenceUploadResponse(
                report_id=report_id,
                attachments=[ReportEvidenceMetadata.model_validate(a) for a in created],
            )
        except Exception as e:
            await self.db.rollback()
            # Best-effort delete all newly uploaded Cloudinary assets
            for pid, rt in uploaded_assets:
                if rt == "video":
                    destroy_asset(pid, resource_type="video")
                else:
                    destroy_image(pid)
            if isinstance(e, HTTPException):
                raise
            logger.error(f"Failed to persist report attachments to DB for report {report_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Lỗi khi lưu thông tin tệp minh chứng.",
            ) from e

    async def stream_admin_evidence(
        self,
        current_admin: User,
        report_id: int,
        attachment_id: int,
        variant: str = "thumbnail",
        range_header: Optional[str] = None,
    ) -> StreamingResponse:
        report = await self.report_repo.get_by_id(
            report_id, for_update=False, eager_load=False
        )
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Báo cáo không tồn tại.",
            )

        attachment = await self.report_repo.get_attachment(report_id, attachment_id)
        if not attachment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tệp minh chứng không tồn tại.",
            )

        is_video = bool(attachment.mime_type and attachment.mime_type.startswith("video/"))

        if not is_video:
            # Strict variant check for images
            if variant not in ("thumbnail", "full"):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Biến thể ảnh '{variant}' không hợp lệ. Chỉ chấp nhận 'thumbnail' hoặc 'full'.",
                )
            target_url = build_transformed_url(attachment.url, width=400) if variant == "thumbnail" else attachment.url
        else:
            target_url = attachment.url

        # Full SSRF and trust model validation
        validate_storage_url_safety(target_url)

        upstream_headers: dict[str, str] = {}
        if is_video and range_header:
            range_match = re.match(r"^bytes=\d*-\d*$", range_header.strip())
            if range_match:
                upstream_headers["Range"] = range_header.strip()

        try:
            client = httpx.AsyncClient(timeout=30.0, follow_redirects=False)
            req = client.build_request("GET", target_url, headers=upstream_headers)
            upstream_resp = await client.send(req, stream=True)
            if upstream_resp.status_code >= 400:
                await upstream_resp.aclose()
                await client.aclose()
                logger.error(
                    f"Cloudinary upstream returned {upstream_resp.status_code} for evidence {attachment_id}"
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Không thể tải tệp minh chứng từ kho lưu trữ.",
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to connect to upstream storage for evidence {attachment_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Lỗi kết nối đến kho lưu trữ minh chứng.",
            ) from e

        safe_filename = attachment.original_name or f"evidence_{attachment_id}"
        encoded_name = urllib.parse.quote(safe_filename)
        content_disposition = f'inline; filename="{safe_filename}"; filename*=UTF-8\'\'{encoded_name}'

        headers = {
            "Content-Disposition": content_disposition,
            "Content-Type": attachment.mime_type or ("video/mp4" if is_video else "image/jpeg"),
            "Cache-Control": "private, no-store",
        }

        if is_video:
            headers["Accept-Ranges"] = "bytes"
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

