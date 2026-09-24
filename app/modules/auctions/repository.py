import base64
from datetime import datetime
from decimal import Decimal
import json
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.auctions.models import Auction, AuctionBid, AuctionStatus
from app.modules.orders.models import Order
from app.modules.products.models import Product


def encode_bid_cursor(amount: Decimal, created_at: datetime, bid_id: int) -> str:
    data = {
        "amount": str(amount),
        "created_at": created_at.isoformat(),
        "bid_id": bid_id,
    }
    raw = json.dumps(data)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def decode_bid_cursor(cursor: str) -> tuple[Decimal, datetime, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        data = json.loads(raw)
        return (
            Decimal(data["amount"]),
            datetime.fromisoformat(data["created_at"]),
            int(data["bid_id"]),
        )
    except Exception as e:
        raise ValueError("Invalid cursor format") from e


class AuctionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_auction(self, auction: Auction) -> Auction:
        self.db.add(auction)
        await self.db.flush()
        return auction

    async def get_auction_by_id(
        self, auction_id: int, for_update: bool = False
    ) -> Optional[Auction]:
        stmt = (
            select(Auction)
            .where(Auction.auction_id == auction_id)
            .options(
                selectinload(Auction.product),
                selectinload(Auction.winner),
            )
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_auction_by_product_id(
        self, product_id: int, for_update: bool = False
    ) -> Optional[Auction]:
        stmt = (
            select(Auction)
            .where(
                Auction.product_id == product_id,
                Auction.status.in_([AuctionStatus.SCHEDULED.value, AuctionStatus.ACTIVE.value]),
            )
            .options(
                selectinload(Auction.product),
                selectinload(Auction.winner),
            )
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_or_latest_by_product_id(
        self, product_id: int
    ) -> Optional[Auction]:
        # 1. Prefer SCHEDULED or ACTIVE auction
        stmt_active = (
            select(Auction)
            .where(
                Auction.product_id == product_id,
                Auction.status.in_([AuctionStatus.SCHEDULED.value, AuctionStatus.ACTIVE.value]),
            )
            .options(
                selectinload(Auction.product),
                selectinload(Auction.winner),
            )
            .order_by(Auction.auction_id.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt_active)
        active_auction = result.scalar_one_or_none()
        if active_auction:
            return active_auction

        # 2. Fallback to latest historical auction
        stmt_latest = (
            select(Auction)
            .where(Auction.product_id == product_id)
            .options(
                selectinload(Auction.product),
                selectinload(Auction.winner),
            )
            .order_by(Auction.created_at.desc(), Auction.auction_id.desc())
            .limit(1)
        )
        result_latest = await self.db.execute(stmt_latest)
        return result_latest.scalar_one_or_none()

    async def get_active_or_latest_by_product_ids(
        self, product_ids: list[int]
    ) -> dict[int, Auction]:
        if not product_ids:
            return {}

        result_map: dict[int, Auction] = {}

        stmt_active = (
            select(Auction)
            .where(
                Auction.product_id.in_(product_ids),
                Auction.status.in_([AuctionStatus.SCHEDULED.value, AuctionStatus.ACTIVE.value]),
            )
            .options(
                selectinload(Auction.product),
                selectinload(Auction.winner),
                selectinload(Auction.bids),
            )
            .order_by(Auction.auction_id.desc())
        )
        res_active = await self.db.execute(stmt_active)
        for a in res_active.scalars().all():
            if a.product_id not in result_map:
                result_map[a.product_id] = a

        remaining_pids = [pid for pid in product_ids if pid not in result_map]
        if remaining_pids:
            stmt_latest = (
                select(Auction)
                .where(Auction.product_id.in_(remaining_pids))
                .options(
                    selectinload(Auction.product),
                    selectinload(Auction.winner),
                    selectinload(Auction.bids),
                )
                .order_by(Auction.created_at.desc(), Auction.auction_id.desc())
            )
            res_latest = await self.db.execute(stmt_latest)
            for a in res_latest.scalars().all():
                if a.product_id not in result_map:
                    result_map[a.product_id] = a

        return result_map

    async def count_bids(self, auction_id: int) -> int:
        stmt = select(func.count()).select_from(AuctionBid).where(AuctionBid.auction_id == auction_id)
        result = await self.db.execute(stmt)
        return result.scalar_one() or 0

    async def get_highest_bid(self, auction_id: int) -> Optional[AuctionBid]:
        stmt = (
            select(AuctionBid)
            .where(AuctionBid.auction_id == auction_id)
            .options(selectinload(AuctionBid.bidder))
            .order_by(
                AuctionBid.amount.desc(),
                AuctionBid.created_at.asc(),
                AuctionBid.bid_id.asc(),
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_bid(self, bid: AuctionBid) -> AuctionBid:
        self.db.add(bid)
        await self.db.flush()
        return bid

    async def list_bids_keyset(
        self,
        auction_id: int,
        cursor: Optional[tuple[Decimal, datetime, int]] = None,
        limit: int = 20,
    ) -> list[AuctionBid]:
        stmt = (
            select(AuctionBid)
            .where(AuctionBid.auction_id == auction_id)
            .options(selectinload(AuctionBid.bidder))
        )
        if cursor:
            c_amount, c_created_at, c_bid_id = cursor
            # Keyset pagination on (amount DESC, created_at ASC, bid_id ASC)
            stmt = stmt.where(
                (AuctionBid.amount < c_amount)
                | (
                    (AuctionBid.amount == c_amount)
                    & (
                        (AuctionBid.created_at > c_created_at)
                        | (
                            (AuctionBid.created_at == c_created_at)
                            & (AuctionBid.bid_id > c_bid_id)
                        )
                    )
                )
            )

        stmt = stmt.order_by(
            AuctionBid.amount.desc(),
            AuctionBid.created_at.asc(),
            AuctionBid.bid_id.asc(),
        ).limit(limit + 1)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_scheduled_auctions_to_sweep(
        self, now_utc: datetime, limit: int = 50
    ) -> list[int]:
        stmt = (
            select(Auction.auction_id)
            .where(
                Auction.status == AuctionStatus.SCHEDULED.value,
                Auction.starts_at <= now_utc,
            )
            .order_by(Auction.starts_at.asc(), Auction.auction_id.asc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_active_auctions_to_close(
        self, now_utc: datetime, limit: int = 50
    ) -> list[int]:
        stmt = (
            select(Auction.auction_id)
            .where(
                Auction.status == AuctionStatus.ACTIVE.value,
                Auction.ends_at <= now_utc,
            )
            .order_by(Auction.ends_at.asc(), Auction.auction_id.asc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_expired_winner_auctions(
        self, now_utc: datetime, limit: int = 50
    ) -> list[int]:
        stmt = (
            select(Auction.auction_id)
            .join(Product, Product.product_id == Auction.product_id)
            .where(
                Auction.status == AuctionStatus.ENDED.value,
                Auction.winner_id.is_not(None),
                Auction.winner_checkout_deadline.is_not(None),
                Auction.winner_checkout_deadline <= now_utc,
                Product.reserved_stock > 0,
                ~select(Order.order_id)
                .where(Order.auction_id == Auction.auction_id)
                .exists(),
            )
            .order_by(Auction.winner_checkout_deadline.asc(), Auction.auction_id.asc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def has_order_for_auction(self, auction_id: int) -> bool:
        stmt = (
            select(Order.order_id)
            .where(
                Order.auction_id == auction_id,
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_order_by_auction_id(self, auction_id: int) -> Optional[Order]:
        stmt = (
            select(Order)
            .where(
                Order.auction_id == auction_id,
            )
            .order_by(Order.order_id.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_won_auctions_pending_checkout(
        self, user_id: int, now_utc: datetime
    ) -> list[Auction]:
        stmt = (
            select(Auction)
            .join(Auction.product)
            .where(
                Auction.status == AuctionStatus.ENDED.value,
                Auction.winner_id == user_id,
                Auction.final_price.is_not(None),
                Auction.winner_checkout_deadline.is_not(None),
                Auction.winner_checkout_deadline >= now_utc,
                Product.is_deleted.is_(False),
                ~select(Order.order_id)
                .where(Order.auction_id == Auction.auction_id)
                .exists(),
            )
            .options(
                selectinload(Auction.product).selectinload(Product.images),
            )
            .order_by(Auction.winner_checkout_deadline.asc(), Auction.auction_id.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_ended_auction_with_active_winner_right(
        self, product_id: int, now_utc: datetime, for_update: bool = False
    ) -> Optional[Auction]:
        stmt = (
            select(Auction)
            .where(
                Auction.product_id == product_id,
                Auction.status == AuctionStatus.ENDED.value,
                Auction.winner_id.is_not(None),
                Auction.final_price.is_not(None),
                Auction.winner_checkout_deadline.is_not(None),
                Auction.winner_checkout_deadline >= now_utc,
                ~select(Order.order_id)
                .where(Order.auction_id == Auction.auction_id)
                .exists(),
            )
            .order_by(Auction.auction_id.desc())
            .limit(1)
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
