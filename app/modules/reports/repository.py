import base64
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.reports.models import (
    ModerationAction,
    Report,
    ReportAttachment,
    ReportStatus,
)


def encode_cursor(created_at: datetime, report_id: int) -> str:
    """Encodes created_at (ISO format) and report_id into an opaque Base64 string."""
    payload = f"{created_at.isoformat()}|{report_id}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")


def decode_cursor(cursor_str: str) -> tuple[datetime, int]:
    """
    Decodes an opaque Base64 cursor string into (created_at, report_id).
    Raises ValueError if malformed.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor_str.encode("utf-8")).decode("utf-8")
        parts = raw.split("|")
        if len(parts) != 2:
            raise ValueError("Invalid cursor format")
        created_at = datetime.fromisoformat(parts[0])
        report_id = int(parts[1])
        return created_at, report_id
    except Exception as e:
        raise ValueError("Invalid cursor") from e


class ReportRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, report: Report) -> Report:
        self.db.add(report)
        await self.db.flush()
        return report

    async def has_active_report(
        self, reporter_id: int, target_type: str, target_id: int
    ) -> bool:
        stmt = (
            select(Report.report_id)
            .where(
                Report.reporter_id == reporter_id,
                Report.target_type == target_type,
                Report.target_id == target_id,
                Report.status.in_([ReportStatus.OPEN.value, ReportStatus.REVIEWING.value]),
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_by_id(
        self, report_id: int, for_update: bool = False, eager_load: bool = True
    ) -> Optional[Report]:
        stmt = select(Report).where(Report.report_id == report_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        elif eager_load:
            stmt = stmt.options(
                selectinload(Report.reporter),
                selectinload(Report.handler),
            )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_admin_reports_cursor(
        self,
        limit: int = 20,
        cursor: Optional[tuple[datetime, int]] = None,
        status: Optional[str] = None,
        statuses: Optional[list[str]] = None,
        target_type: Optional[str] = None,
    ) -> tuple[list[Report], bool, Optional[tuple[datetime, int]]]:
        stmt = select(Report).options(
            selectinload(Report.reporter),
            selectinload(Report.handler),
        )

        if statuses:
            stmt = stmt.where(Report.status.in_(statuses))
        elif status:
            stmt = stmt.where(Report.status == status)

        if target_type:
            stmt = stmt.where(Report.target_type == target_type)

        if cursor is not None:
            cursor_dt, cursor_id = cursor
            stmt = stmt.where(
                or_(
                    Report.created_at < cursor_dt,
                    and_(
                        Report.created_at == cursor_dt,
                        Report.report_id < cursor_id,
                    ),
                )
            )

        stmt = stmt.order_by(
            Report.created_at.desc(),
            Report.report_id.desc(),
        ).limit(limit + 1)

        result = await self.db.execute(stmt)
        items = list(result.scalars().all())

        has_more = len(items) > limit
        if has_more:
            items = items[:limit]
            next_cursor = (items[-1].created_at, items[-1].report_id)
        else:
            next_cursor = None

        return items, has_more, next_cursor

    async def add_attachments(
        self, attachments: list[ReportAttachment]
    ) -> list[ReportAttachment]:
        self.db.add_all(attachments)
        await self.db.flush()
        return attachments

    async def list_attachments_by_report(
        self, report_id: int
    ) -> list[ReportAttachment]:
        stmt = (
            select(ReportAttachment)
            .where(ReportAttachment.report_id == report_id)
            .order_by(ReportAttachment.attachment_id.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    get_attachments = list_attachments_by_report

    async def get_attachment(
        self, report_id: int, attachment_id: int
    ) -> Optional[ReportAttachment]:
        stmt = select(ReportAttachment).where(
            ReportAttachment.report_id == report_id,
            ReportAttachment.attachment_id == attachment_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def count_attachments(self, report_id: int) -> int:
        stmt = (
            select(func.count(ReportAttachment.attachment_id))
            .where(ReportAttachment.report_id == report_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one() or 0

    async def batch_count_attachments(
        self, report_ids: list[int]
    ) -> dict[int, int]:
        if not report_ids:
            return {}
        stmt = (
            select(
                ReportAttachment.report_id,
                func.count(ReportAttachment.attachment_id),
            )
            .where(ReportAttachment.report_id.in_(report_ids))
            .group_by(ReportAttachment.report_id)
        )
        result = await self.db.execute(stmt)
        return dict(result.all())

    async def add_moderation_action(
        self, action: ModerationAction
    ) -> ModerationAction:
        self.db.add(action)
        await self.db.flush()
        return action

    async def list_moderation_actions_by_report(
        self, report_id: int
    ) -> list[ModerationAction]:
        stmt = (
            select(ModerationAction)
            .options(selectinload(ModerationAction.admin))
            .where(ModerationAction.report_id == report_id)
            .order_by(
                ModerationAction.created_at.asc(),
                ModerationAction.moderation_action_id.asc(),
            )
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_moderation_action_for_target(
        self,
        target_type: str,
        target_id: int,
        action_types: Optional[list[str]] = None,
    ) -> Optional[ModerationAction]:
        conditions = [
            ModerationAction.target_type == target_type,
            ModerationAction.target_id == target_id,
        ]
        if action_types:
            conditions.append(ModerationAction.action_type.in_(action_types))

        stmt = (
            select(ModerationAction)
            .options(selectinload(ModerationAction.admin))
            .where(*conditions)
            .order_by(
                ModerationAction.created_at.desc(),
                ModerationAction.moderation_action_id.desc(),
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def count_subject_reports(
        self, subject_user_id: int, exclude_report_id: Optional[int] = None
    ) -> int:
        from app.modules.orders.models import Order
        from app.modules.products.models import Product
        from app.modules.reports.models import ReportTargetType

        conditions = [
            Report.reporter_id != subject_user_id,
            or_(
                and_(
                    Report.target_type == ReportTargetType.USER.value,
                    Report.target_id == subject_user_id,
                ),
                and_(
                    Report.target_type == ReportTargetType.PRODUCT.value,
                    Product.seller_id == subject_user_id,
                ),
                and_(
                    Report.target_type == ReportTargetType.ORDER.value,
                    or_(
                        and_(
                            Order.buyer_id == Report.reporter_id,
                            Order.seller_id == subject_user_id,
                        ),
                        and_(
                            Order.seller_id == Report.reporter_id,
                            Order.buyer_id == subject_user_id,
                        ),
                    ),
                ),
            ),
        ]
        if exclude_report_id is not None:
            conditions.append(Report.report_id != exclude_report_id)

        count_stmt = (
            select(func.count(Report.report_id))
            .select_from(Report)
            .outerjoin(
                Product,
                and_(
                    Report.target_type == ReportTargetType.PRODUCT.value,
                    Report.target_id == Product.product_id,
                ),
            )
            .outerjoin(
                Order,
                and_(
                    Report.target_type == ReportTargetType.ORDER.value,
                    Report.target_id == Order.order_id,
                ),
            )
            .where(*conditions)
        )
        result = await self.db.execute(count_stmt)
        return result.scalar_one() or 0

    async def list_subject_reports_cursor(
        self,
        subject_user_id: int,
        limit: int = 5,
        cursor: Optional[tuple[datetime, int]] = None,
        exclude_report_id: Optional[int] = None,
    ) -> tuple[list[Report], bool, Optional[tuple[datetime, int]]]:
        from app.modules.orders.models import Order
        from app.modules.products.models import Product
        from app.modules.reports.models import ReportTargetType

        conditions = [
            Report.reporter_id != subject_user_id,
            or_(
                and_(
                    Report.target_type == ReportTargetType.USER.value,
                    Report.target_id == subject_user_id,
                ),
                and_(
                    Report.target_type == ReportTargetType.PRODUCT.value,
                    Product.seller_id == subject_user_id,
                ),
                and_(
                    Report.target_type == ReportTargetType.ORDER.value,
                    or_(
                        and_(
                            Order.buyer_id == Report.reporter_id,
                            Order.seller_id == subject_user_id,
                        ),
                        and_(
                            Order.seller_id == Report.reporter_id,
                            Order.buyer_id == subject_user_id,
                        ),
                    ),
                ),
            ),
        ]
        if exclude_report_id is not None:
            conditions.append(Report.report_id != exclude_report_id)

        stmt = (
            select(Report)
            .outerjoin(
                Product,
                and_(
                    Report.target_type == ReportTargetType.PRODUCT.value,
                    Report.target_id == Product.product_id,
                ),
            )
            .outerjoin(
                Order,
                and_(
                    Report.target_type == ReportTargetType.ORDER.value,
                    Report.target_id == Order.order_id,
                ),
            )
            .where(*conditions)
        )

        if cursor is not None:
            cursor_dt, cursor_id = cursor
            stmt = stmt.where(
                or_(
                    Report.created_at < cursor_dt,
                    and_(
                        Report.created_at == cursor_dt,
                        Report.report_id < cursor_id,
                    ),
                )
            )

        stmt = stmt.order_by(
            Report.created_at.desc(),
            Report.report_id.desc(),
        ).limit(limit + 1)

        result = await self.db.execute(stmt)
        items = list(result.scalars().all())

        has_more = len(items) > limit
        if has_more:
            items = items[:limit]
            next_cursor = (items[-1].created_at, items[-1].report_id)
        else:
            next_cursor = None

        return items, has_more, next_cursor

    async def batch_list_moderation_actions(
        self, report_ids: list[int]
    ) -> dict[int, list[ModerationAction]]:
        if not report_ids:
            return {}
        stmt = (
            select(ModerationAction)
            .options(selectinload(ModerationAction.admin))
            .where(ModerationAction.report_id.in_(report_ids))
            .order_by(
                ModerationAction.created_at.asc(),
                ModerationAction.moderation_action_id.asc(),
            )
        )
        result = await self.db.execute(stmt)
        actions = list(result.scalars().all())
        mapping: dict[int, list[ModerationAction]] = {rid: [] for rid in report_ids}
        for act in actions:
            mapping[act.report_id].append(act)
        return mapping


