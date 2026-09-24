from datetime import datetime
from typing import Optional, Sequence
from sqlalchemy import BinaryExpression, or_, select, exists
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.capability_models import (
    CapabilityType,
    UserCapabilityRestriction,
)


class CapabilityRestrictionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_active_restrictions_by_user(
        self, user_id: int, now_utc: datetime
    ) -> list[UserCapabilityRestriction]:
        """Fetch all currently active (effective) capability restrictions for a user."""
        stmt = (
            select(UserCapabilityRestriction)
            .where(
                UserCapabilityRestriction.user_id == user_id,
                UserCapabilityRestriction.revoked_at.is_(None),
                UserCapabilityRestriction.starts_at <= now_utc,
                or_(
                    UserCapabilityRestriction.expires_at.is_(None),
                    UserCapabilityRestriction.expires_at > now_utc,
                ),
            )
            .order_by(UserCapabilityRestriction.starts_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_active_restrictions_for_capabilities(
        self, user_id: int, capabilities: Sequence[str], now_utc: datetime
    ) -> list[UserCapabilityRestriction]:
        """Fetch active restrictions for specific capabilities for a user."""
        stmt = (
            select(UserCapabilityRestriction)
            .where(
                UserCapabilityRestriction.user_id == user_id,
                UserCapabilityRestriction.capability.in_(capabilities),
                UserCapabilityRestriction.revoked_at.is_(None),
                UserCapabilityRestriction.starts_at <= now_utc,
                or_(
                    UserCapabilityRestriction.expires_at.is_(None),
                    UserCapabilityRestriction.expires_at > now_utc,
                ),
            )
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_effective_by_source_report(
        self, report_id: int, user_id: int, capability: str, now_utc: datetime, for_update: bool = False
    ) -> Optional[UserCapabilityRestriction]:
        """Fetch an active restriction originating from a specific report that is still effective."""
        stmt = (
            select(UserCapabilityRestriction)
            .where(
                UserCapabilityRestriction.source_report_id == report_id,
                UserCapabilityRestriction.user_id == user_id,
                UserCapabilityRestriction.capability == capability,
                UserCapabilityRestriction.revoked_at.is_(None),
                UserCapabilityRestriction.starts_at <= now_utc,
                or_(
                    UserCapabilityRestriction.expires_at.is_(None),
                    UserCapabilityRestriction.expires_at > now_utc,
                ),
            )
            .limit(1)
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_restrictions_by_source_report(
        self, user_id: int, report_id: int, now_utc: datetime
    ) -> list[UserCapabilityRestriction]:
        """Fetch all currently active restrictions originating from a specific report."""
        stmt = (
            select(UserCapabilityRestriction)
            .where(
                UserCapabilityRestriction.user_id == user_id,
                UserCapabilityRestriction.source_report_id == report_id,
                UserCapabilityRestriction.revoked_at.is_(None),
                UserCapabilityRestriction.starts_at <= now_utc,
                or_(
                    UserCapabilityRestriction.expires_at.is_(None),
                    UserCapabilityRestriction.expires_at > now_utc,
                ),
            )
            .order_by(UserCapabilityRestriction.starts_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    def add(self, restriction: UserCapabilityRestriction) -> None:
        self.db.add(restriction)

    @staticmethod
    def build_sell_unrestricted_filter(
        seller_id_col, now_utc: datetime
    ) -> BinaryExpression:
        """
        Shared SQL visibility predicate returning ~exists(...) subquery.
        Excludes products whose seller has a currently effective SELL restriction.
        """
        return ~exists(
            select(1)
            .select_from(UserCapabilityRestriction)
            .where(
                UserCapabilityRestriction.user_id == seller_id_col,
                UserCapabilityRestriction.capability == CapabilityType.SELL.value,
                UserCapabilityRestriction.starts_at <= now_utc,
                or_(
                    UserCapabilityRestriction.expires_at.is_(None),
                    UserCapabilityRestriction.expires_at > now_utc,
                ),
                UserCapabilityRestriction.revoked_at.is_(None),
            )
        )
