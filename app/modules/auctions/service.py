from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
import time
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select

from app.core.config import settings
from app.modules.auctions.models import Auction, AuctionBid, AuctionStatus
from app.modules.auctions.repository import (
    AuctionRepository,
    decode_bid_cursor,
    encode_bid_cursor,
)
from app.modules.auctions.schemas import (
    AuctionBidCursorPage,
    AuctionBidResponse,
    AuctionCreateRequest,
    AuctionDetailResponse,
    PlaceBidRequest,
    WinnerCheckoutRequest,
    WonAuctionItemResponse,
    anonymize_name,
)
from app.modules.auctions.websocket import publish_auction_event
from app.modules.notifications.models import NotificationType
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.schemas import NotificationResponse
from app.modules.orders.models import Order
from app.modules.orders.service import OrderService
from app.modules.orders.websocket import publish_user_event
from app.modules.products.models import ListingType, Product, ProductStatus, ProductModerationStatus
from app.modules.users.capability_service import CapabilityService
from app.modules.users.models import User, UserStatus
from app.workers.retry import SweepResult, execute_with_retry

logger = logging.getLogger("app.auctions")


async def safe_publish_user_notification(
    user_id: int, notification: NotificationResponse, context_msg: str
) -> None:
    try:
        await publish_user_event(
            user_id,
            {
                "type": "NOTIFICATION_CREATED",
                "notification": notification.model_dump(mode="json"),
            },
        )
    except Exception as e:
        logger.warning(
            f"Failed to publish notification realtime to user {user_id} ({context_msg}): {e}"
        )


def normalize_to_utc_naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert an offset-aware or offset-naive datetime to a UTC offset-naive datetime."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


async def format_auction_detail(
    auction: Auction,
    repo: AuctionRepository,
    current_user: Optional[User] = None,
    now_utc: Optional[datetime] = None,
) -> AuctionDetailResponse:
    if now_utc is None:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    bid_count = await repo.count_bids(auction.auction_id)
    highest_bid_row = await repo.get_highest_bid(auction.auction_id)

    if highest_bid_row:
        current_price = highest_bid_row.amount
        highest_bid = highest_bid_row.amount
        minimum_next_bid = highest_bid_row.amount + auction.bid_step
        is_highest = (
            current_user is not None
            and highest_bid_row.bidder_id == current_user.user_id
        )
        highest_bidder_display = (
            anonymize_name(highest_bid_row.bidder.full_name)
            if highest_bid_row.bidder
            else None
        )
    else:
        current_price = auction.starting_price
        highest_bid = None
        minimum_next_bid = max(auction.starting_price, Decimal(1))
        is_highest = False
        highest_bidder_display = None

    has_winner = auction.status == AuctionStatus.ENDED.value and auction.winner_id is not None
    is_winner = (
        has_winner
        and current_user is not None
        and auction.winner_id == current_user.user_id
    )

    winner_checkout_state = "NOT_APPLICABLE"
    winner_order_id = None

    if auction.status == AuctionStatus.ENDED.value:
        if auction.winner_id is None:
            winner_checkout_state = "NO_BIDS"
        else:
            order = await repo.get_order_by_auction_id(auction.auction_id)
            if order:
                winner_checkout_state = "ORDER_CREATED"
                winner_order_id = order.order_id
            elif auction.winner_checkout_deadline and now_utc > auction.winner_checkout_deadline:
                winner_checkout_state = "EXPIRED"
            else:
                winner_checkout_state = "WAITING"

    return AuctionDetailResponse(
        auction_id=auction.auction_id,
        product_id=auction.product_id,
        status=auction.status,
        starting_price=auction.starting_price,
        bid_step=auction.bid_step,
        current_price=current_price,
        highest_bid=highest_bid,
        bid_count=bid_count,
        minimum_next_bid=minimum_next_bid,
        starts_at=auction.starts_at,
        ends_at=auction.ends_at,
        has_winner=has_winner,
        final_price=auction.final_price,
        winner_checkout_deadline=auction.winner_checkout_deadline,
        is_current_user_winner=is_winner,
        is_current_user_highest_bidder=is_highest,
        highest_bidder_display=highest_bidder_display,
        server_time=now_utc,
        winner_checkout_state=winner_checkout_state,
        winner_order_id=winner_order_id,
    )


class AuctionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.auction_repo = AuctionRepository(db)

    async def enable_auction(
        self, seller: User, payload: AuctionCreateRequest
    ) -> AuctionDetailResponse:
        if seller.status != UserStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tài khoản của bạn không được phép tạo phiên đấu giá.",
            )

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        if not await CapabilityService(self.db).can_user_sell(seller.user_id, now_utc=now_utc):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "SELL_RESTRICTED",
                    "message": "Tài khoản của bạn đang bị giới hạn quyền bán hàng.",
                },
            )

        # 1. Lock Product FOR UPDATE
        stmt = (
            select(Product)
            .where(
                Product.product_id == payload.product_id,
                Product.is_deleted.is_(False),
            )
            .with_for_update()
        )
        res = await self.db.execute(stmt)
        product = res.scalar_one_or_none()

        if not product or product.seller_id != seller.user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sản phẩm không tồn tại hoặc bạn không có quyền sở hữu.",
            )

        if product.status != ProductStatus.AVAILABLE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chỉ có thể bật đấu giá cho sản phẩm đang ở trạng thái AVAILABLE.",
            )

        if product.moderation_status == ProductModerationStatus.BLOCKED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể tạo đấu giá cho sản phẩm đang bị quản trị viên ẩn.",
            )

        if product.stock != 1 or product.reserved_stock != 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sản phẩm đấu giá phải có đúng 1 tồn kho khả dụng và chưa bị giữ hàng.",
            )

        if payload.bid_step <= Decimal(0):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bước giá phải lớn hơn 0.",
            )

        # Immediate start using duration_minutes (preferred MVP architecture)
        if payload.duration_minutes is not None:
            if payload.duration_minutes <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Thời lượng đấu giá phải lớn hơn 0 phút.",
                )
            starts_at = now_utc
            ends_at = now_utc + timedelta(minutes=payload.duration_minutes)
            auction_status = AuctionStatus.ACTIVE.value
        else:
            # Fallback for manual/legacy starts_at & ends_at
            starts_at = normalize_to_utc_naive(payload.starts_at)
            ends_at = normalize_to_utc_naive(payload.ends_at)

            if starts_at is None:
                starts_at = now_utc
            else:
                if starts_at < now_utc:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Thời gian bắt đầu không được ở trong quá khứ.",
                    )

            if ends_at is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cần cung cấp duration_minutes hoặc ends_at.",
                )

            if ends_at <= starts_at:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Thời gian kết thúc phải diễn ra sau thời gian bắt đầu.",
                )

            auction_status = (
                AuctionStatus.ACTIVE.value
                if starts_at <= now_utc
                else AuctionStatus.SCHEDULED.value
            )

        # Check existing active/scheduled auction
        existing_active = await self.auction_repo.get_active_auction_by_product_id(product.product_id)
        if existing_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sản phẩm đã có một phiên đấu giá đang hoạt động hoặc được lên lịch.",
            )

        auction = Auction(
            product_id=product.product_id,
            starting_price=product.price,
            bid_step=payload.bid_step,
            starts_at=starts_at,
            ends_at=ends_at,
            status=auction_status,
        )

        created_auction = await self.auction_repo.create_auction(auction)
        product.listing_type = ListingType.AUCTION.value

        await self.db.commit()

        if auction_status == AuctionStatus.ACTIVE.value:
            await publish_auction_event(
                created_auction.auction_id,
                {
                    "event": "AUCTION_STARTED",
                    "auction_id": created_auction.auction_id,
                    "current_price": str(created_auction.starting_price),
                    "bid_count": 0,
                    "server_time": now_utc.isoformat(),
                },
            )

        return await format_auction_detail(created_auction, self.auction_repo, seller, now_utc)

    async def cancel_auction(self, seller: User, auction_id: int) -> AuctionDetailResponse:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        # 1. Lock Auction FOR UPDATE
        auction = await self.auction_repo.get_auction_by_id(auction_id, for_update=True)
        if not auction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy phiên đấu giá.",
            )

        # 2. Lock Product FOR UPDATE
        stmt_prod = select(Product).where(Product.product_id == auction.product_id).with_for_update()
        res_prod = await self.db.execute(stmt_prod)
        product = res_prod.scalar_one_or_none()

        if not product or (product.seller_id != seller.user_id and seller.role != "ADMIN"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền hủy phiên đấu giá này.",
            )

        if auction.status not in (AuctionStatus.SCHEDULED.value, AuctionStatus.ACTIVE.value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chỉ có thể hủy phiên đấu giá đang được lên lịch hoặc đang hoạt động.",
            )

        bid_count = await self.auction_repo.count_bids(auction.auction_id)
        if bid_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể hủy phiên đấu giá đã có lượt đặt giá.",
            )

        auction.status = AuctionStatus.CANCELLED.value
        product.listing_type = ListingType.FIXED_PRICE.value

        await self.db.commit()

        await publish_auction_event(
            auction.auction_id,
            {
                "event": "AUCTION_CANCELLED",
                "auction_id": auction.auction_id,
                "server_time": now_utc.isoformat(),
            },
        )

        return await format_auction_detail(auction, self.auction_repo, seller, now_utc)

    async def place_bid(
        self, bidder: User, auction_id: int, payload: PlaceBidRequest
    ) -> AuctionBidResponse:
        if bidder.status != UserStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tài khoản của bạn không được phép đặt giá.",
            )

        if payload.amount <= Decimal(0):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Giá đặt phải lớn hơn 0.",
            )

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        if not await CapabilityService(self.db).can_user_buy(bidder.user_id, now_utc=now_utc):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "BUY_RESTRICTED",
                    "message": "Tài khoản của bạn đang bị giới hạn quyền mua hàng.",
                },
            )

        # 1. Lock Auction FOR UPDATE
        auction = await self.auction_repo.get_auction_by_id(auction_id, for_update=True)
        if not auction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy phiên đấu giá.",
            )

        # Catch-up SCHEDULED to ACTIVE
        if (
            auction.status == AuctionStatus.SCHEDULED.value
            and auction.starts_at <= now_utc < auction.ends_at
        ):
            auction.status = AuctionStatus.ACTIVE.value

        if auction.status != AuctionStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phiên đấu giá chưa bắt đầu hoặc đã kết thúc.",
            )

        # Fresh product moderation check to close race with concurrent PRODUCT_HIDE
        stmt_p = select(Product.moderation_status, Product.is_deleted).where(Product.product_id == auction.product_id)
        res_p = await self.db.execute(stmt_p)
        prod_row = res_p.one_or_none()
        if not prod_row or prod_row.is_deleted or prod_row.moderation_status == ProductModerationStatus.BLOCKED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sản phẩm đấu giá đã bị ẩn hoặc không còn khả dụng.",
            )

        if now_utc >= auction.ends_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phiên đấu giá đã hết thời gian đặt giá.",
            )

        if auction.product.seller_id == bidder.user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Người bán không được tự đặt giá sản phẩm của chính mình.",
            )

        seller = await self.db.get(User, auction.product.seller_id)
        if not seller or seller.status != UserStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Người bán hiện đang bị khóa tài khoản hoặc không hoạt động.",
            )

        # 1. Capture previous highest bid and bidder BEFORE inserting the new bid
        previous_highest_bid = await self.auction_repo.get_highest_bid(auction.auction_id)
        previous_highest_bidder_id = (
            previous_highest_bid.bidder_id if previous_highest_bid else None
        )

        if previous_highest_bid:
            min_required = previous_highest_bid.amount + auction.bid_step
        else:
            # First bid rule: amount > 0 and amount >= starting_price
            min_required = max(auction.starting_price, Decimal(1))

        if payload.amount < min_required:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Giá đặt phải tối thiểu là {int(min_required):,} đ.",
            )

        # 2. Insert new bid
        bid = AuctionBid(
            auction_id=auction.auction_id,
            bidder_id=bidder.user_id,
            amount=payload.amount,
            created_at=now_utc,
        )
        created_bid = await self.auction_repo.create_bid(bid)
        bid_count = await self.auction_repo.count_bids(auction.auction_id)

        # 3. Pre-resolve plain data for notifications before commit (avoid lazy-load post-commit)
        seller_id = auction.product.seller_id
        product_title = auction.product.title
        auction_id_val = auction.auction_id
        bid_amount_formatted = f"{int(created_bid.amount):,} đ"
        bidder_display_name = bidder.full_name

        notification_repo = NotificationRepository(self.db)

        # Seller notification: AUCTION_BID
        n_seller = await notification_repo.create(
            user_id=seller_id,
            type=NotificationType.AUCTION_BID.value,
            title="Có lượt đấu giá mới",
            body=f"{bidder_display_name} vừa đặt giá {bid_amount_formatted} cho {product_title}.",
            ref_type="AUCTION",
            ref_id=auction_id_val,
        )

        # Displaced bidder notification: AUCTION_OUTBID (only if previous bidder existed and != current bidder)
        n_outbid = None
        if previous_highest_bidder_id is not None and previous_highest_bidder_id != bidder.user_id:
            n_outbid = await notification_repo.create(
                user_id=previous_highest_bidder_id,
                type=NotificationType.AUCTION_OUTBID.value,
                title="Bạn đã bị vượt giá",
                body=f"Mức giá cao nhất mới của {product_title} là {bid_amount_formatted}.",
                ref_type="AUCTION",
                ref_id=auction_id_val,
            )

        # 4. Flush and construct immutable DTO snapshots BEFORE commit
        await self.db.flush()
        seller_snapshot = NotificationResponse.model_validate(n_seller)
        outbid_snapshot = NotificationResponse.model_validate(n_outbid) if n_outbid else None

        # 5. Commit transaction
        await self.db.commit()

        # 6. Independent best-effort post-commit realtime delivery
        try:
            await publish_auction_event(
                auction_id_val,
                {
                    "event": "BID_PLACED",
                    "auction_id": auction_id_val,
                    "current_price": str(created_bid.amount),
                    "highest_bid": str(created_bid.amount),
                    "bid_count": bid_count,
                    "minimum_next_bid": str(created_bid.amount + auction.bid_step),
                    "server_time": now_utc.isoformat(),
                },
            )
        except Exception as e:
            logger.warning(f"Failed to publish BID_PLACED event for auction {auction_id_val}: {e}")

        await safe_publish_user_notification(seller_id, seller_snapshot, f"bid on auction {auction_id_val}")
        if outbid_snapshot and previous_highest_bidder_id:
            await safe_publish_user_notification(
                previous_highest_bidder_id, outbid_snapshot, f"outbid on auction {auction_id_val}"
            )

        return AuctionBidResponse(
            bid_id=created_bid.bid_id,
            auction_id=created_bid.auction_id,
            bidder_display=anonymize_name(bidder.full_name),
            amount=created_bid.amount,
            created_at=created_bid.created_at,
            is_current_user=True,
        )

    async def close_single_auction_if_expired(
        self, auction_id: int, now_utc: Optional[datetime] = None
    ) -> Optional[Auction]:
        """
        Idempotently closes a single expired ACTIVE auction within this session.
        Ensures strict row-locking order:
        1. Lock Auction FOR UPDATE
        2. If active and ends_at <= now:
           - Fetch highest bid (amount DESC, created_at ASC, bid_id ASC LIMIT 1)
           - If no bids: status = ENDED, winner_id = None, final_price = None, winner_checkout_deadline = None
           - If winning bid:
             Lock Product FOR UPDATE
             Verify product invariant (stock == 1, reserved_stock == 0)
             status = ENDED, winner_id = highest_bid.bidder_id, final_price = highest_bid.amount,
             winner_checkout_deadline = now_utc + timedelta(hours=settings.AUCTION_WINNER_CHECKOUT_HOURS)
             product.reserved_stock = 1
        3. Flush session
        4. Best-effort publish AUCTION_ENDED event
        Returns the updated Auction instance.
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        auction = await self.auction_repo.get_auction_by_id(auction_id, for_update=True)
        if not auction:
            return None

        has_transitioned = False
        notification_repo = NotificationRepository(self.db)

        # If scheduled and starts_at <= now, activate or directly end if expired
        if auction.status == AuctionStatus.SCHEDULED.value:
            if auction.ends_at <= now_utc:
                seller_id = auction.product.seller_id
                product_title = auction.product.title
                auction_id_val = auction.auction_id

                auction.status = AuctionStatus.ENDED.value
                auction.winner_id = None
                auction.final_price = None
                auction.winner_checkout_deadline = None
                has_transitioned = True

                n_seller = await notification_repo.create(
                    user_id=seller_id,
                    type=NotificationType.AUCTION_ENDED.value,
                    title="Đấu giá đã kết thúc",
                    body=f"Phiên đấu giá {product_title} đã kết thúc mà chưa có người thắng.",
                    ref_type="AUCTION",
                    ref_id=auction_id_val,
                )
                await self.db.flush()
                seller_snapshot = NotificationResponse.model_validate(n_seller)

                await self.db.commit()

                await safe_publish_user_notification(
                    seller_id, seller_snapshot, f"expired scheduled auction {auction_id_val}"
                )
                setattr(auction, "_transitioned", has_transitioned)
                return auction
            elif auction.starts_at <= now_utc:
                auction.status = AuctionStatus.ACTIVE.value
                has_transitioned = True
                await self.db.commit()

        if auction.status == AuctionStatus.ACTIVE.value and auction.ends_at <= now_utc:
            seller_id = auction.product.seller_id
            product_title = auction.product.title
            auction_id_val = auction.auction_id

            highest_bid = await self.auction_repo.get_highest_bid(auction.auction_id)

            if not highest_bid:
                auction.status = AuctionStatus.ENDED.value
                auction.winner_id = None
                auction.final_price = None
                auction.winner_checkout_deadline = None
                has_transitioned = True

                n_seller = await notification_repo.create(
                    user_id=seller_id,
                    type=NotificationType.AUCTION_ENDED.value,
                    title="Đấu giá đã kết thúc",
                    body=f"Phiên đấu giá {product_title} đã kết thúc mà chưa có người thắng.",
                    ref_type="AUCTION",
                    ref_id=auction_id_val,
                )
                await self.db.flush()
                seller_snapshot = NotificationResponse.model_validate(n_seller)

                await self.db.commit()

                # Best-effort publish
                try:
                    await publish_auction_event(
                        auction_id_val,
                        {
                            "event": "AUCTION_ENDED",
                            "auction_id": auction_id_val,
                            "status": "ENDED",
                            "final_price": None,
                            "has_winner": False,
                            "server_time": now_utc.isoformat(),
                        },
                    )
                except Exception as e:
                    logger.warning(f"Failed to publish AUCTION_ENDED event for auction {auction_id_val}: {e}")

                await safe_publish_user_notification(
                    seller_id, seller_snapshot, f"ended no-bid auction {auction_id_val}"
                )

                logger.info(f"Closed auction ID {auction_id_val} with no bids.")
            else:
                # Lock Product FOR UPDATE
                stmt_prod = select(Product).where(Product.product_id == auction.product_id).with_for_update()
                res_prod = await self.db.execute(stmt_prod)
                product = res_prod.scalar_one_or_none()

                if product and product.stock == 1 and product.reserved_stock == 0:
                    deadline = now_utc + timedelta(hours=settings.AUCTION_WINNER_CHECKOUT_HOURS)
                    auction.status = AuctionStatus.ENDED.value
                    auction.winner_id = highest_bid.bidder_id
                    auction.final_price = highest_bid.amount
                    auction.winner_checkout_deadline = deadline

                    # Reserve stock for winner
                    product.reserved_stock = 1
                    has_transitioned = True

                    final_price_formatted = f"{int(highest_bid.amount):,} đ"
                    winner_id = highest_bid.bidder_id

                    # Create seller notification: AUCTION_ENDED
                    n_seller = await notification_repo.create(
                        user_id=seller_id,
                        type=NotificationType.AUCTION_ENDED.value,
                        title="Đấu giá đã kết thúc",
                        body=f"{product_title} đã kết thúc với giá {final_price_formatted}.",
                        ref_type="AUCTION",
                        ref_id=auction_id_val,
                    )

                    # Create winner notification: AUCTION_WON
                    n_winner = await notification_repo.create(
                        user_id=winner_id,
                        type=NotificationType.AUCTION_WON.value,
                        title="Bạn đã thắng đấu giá",
                        body=f"Bạn đã thắng {product_title} với giá {final_price_formatted}.",
                        ref_type="AUCTION",
                        ref_id=auction_id_val,
                    )

                    await self.db.flush()
                    seller_snapshot = NotificationResponse.model_validate(n_seller)
                    winner_snapshot = NotificationResponse.model_validate(n_winner)

                    await self.db.commit()

                    # Independent post-commit realtime delivery
                    try:
                        await publish_auction_event(
                            auction_id_val,
                            {
                                "event": "AUCTION_ENDED",
                                "auction_id": auction_id_val,
                                "status": "ENDED",
                                "final_price": str(highest_bid.amount),
                                "has_winner": True,
                                "server_time": now_utc.isoformat(),
                            },
                        )
                    except Exception as e:
                        logger.warning(f"Failed to publish AUCTION_ENDED event for auction {auction_id_val}: {e}")

                    await safe_publish_user_notification(
                        seller_id, seller_snapshot, f"ended auction seller {auction_id_val}"
                    )
                    await safe_publish_user_notification(
                        winner_id, winner_snapshot, f"ended auction winner {auction_id_val}"
                    )

                    logger.info(f"Closed auction ID {auction_id_val} with winner {highest_bid.bidder_id}, price {highest_bid.amount}.")
                elif product and product.stock == 1 and product.reserved_stock == 1 and auction.winner_id == highest_bid.bidder_id:
                    # Already reserved
                    auction.status = AuctionStatus.ENDED.value
                    await self.db.commit()
                else:
                    logger.error(f"Cannot reserve stock for auction winner on auction {auction_id_val} (stock invariant violation).")

        setattr(auction, "_transitioned", has_transitioned)
        return auction

    async def activate_or_end_single_scheduled_auction(
        self, auction_id: int, now_utc: Optional[datetime] = None
    ) -> bool:
        """
        Activates a SCHEDULED auction whose starts_at <= NOW(),
        or directly ends it if ends_at <= NOW() without bids.
        Returns True if a state transition occurred (CHANGED), False if NO_OP.
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        auction = await self.auction_repo.get_auction_by_id(auction_id, for_update=True)
        if not auction or auction.status != AuctionStatus.SCHEDULED.value:
            return False

        if auction.ends_at <= now_utc:
            seller_id = auction.product.seller_id
            product_title = auction.product.title
            auction_id_val = auction.auction_id

            auction.status = AuctionStatus.ENDED.value
            auction.winner_id = None
            auction.final_price = None
            auction.winner_checkout_deadline = None

            notification_repo = NotificationRepository(self.db)
            n_seller = await notification_repo.create(
                user_id=seller_id,
                type=NotificationType.AUCTION_ENDED.value,
                title="Đấu giá đã kết thúc",
                body=f"Phiên đấu giá {product_title} đã kết thúc mà chưa có người thắng.",
                ref_type="AUCTION",
                ref_id=auction_id_val,
            )
            await self.db.flush()
            seller_snapshot = NotificationResponse.model_validate(n_seller)
            await self.db.commit()

            await safe_publish_user_notification(
                seller_id, seller_snapshot, f"sweep expired scheduled auction {auction_id_val}"
            )
            logger.info(f"Directly ended expired scheduled auction ID {auction_id_val}")
            return True

        elif auction.starts_at <= now_utc:
            auction.status = AuctionStatus.ACTIVE.value
            await self.db.commit()
            try:
                await publish_auction_event(
                    auction.auction_id,
                    {
                        "event": "AUCTION_STARTED",
                        "auction_id": auction.auction_id,
                        "current_price": str(auction.starting_price),
                        "bid_count": 0,
                        "server_time": now_utc.isoformat(),
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to publish AUCTION_STARTED event for auction {auction.auction_id}: {e}")

            logger.info(f"Activated scheduled auction ID {auction_id}")
            return True

        return False

    async def close_single_auction_sweep(
        self, auction_id: int, now_utc: Optional[datetime] = None
    ) -> bool:
        """
        Processes an expired active auction for the worker sweep.
        Returns True if a state transition occurred (CHANGED), False if NO_OP.
        """
        auction = await self.close_single_auction_if_expired(auction_id, now_utc=now_utc)
        return bool(auction and getattr(auction, "_transitioned", False))

    async def timeout_single_winner_checkout(
        self, auction_id: int, now_utc: Optional[datetime] = None
    ) -> bool:
        """
        Releases expired winner reservation idempotently inside an isolated transaction:
        1. Lock Auction FOR UPDATE.
        2. Revalidate auction is ENDED and winner_checkout_deadline <= now_utc.
        3. Revalidate no order exists for this auction.
        4. Lock Product FOR UPDATE.
        5. If product.reserved_stock > 0: set reserved_stock = 0, commit, return True (CHANGED).
        6. If conditions not met or already released: return False (NO_OP).
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        auction = await self.auction_repo.get_auction_by_id(auction_id, for_update=True)
        if (
            not auction
            or auction.status != AuctionStatus.ENDED.value
            or not auction.winner_checkout_deadline
            or auction.winner_checkout_deadline > now_utc
        ):
            return False

        has_order = await self.auction_repo.has_order_for_auction(auction.auction_id)
        if has_order:
            return False

        stmt_prod = select(Product).where(Product.product_id == auction.product_id).with_for_update()
        res_prod = await self.db.execute(stmt_prod)
        product = res_prod.scalar_one_or_none()

        if not product or product.reserved_stock < 1:
            return False

        product.reserved_stock = 0
        await self.db.commit()
        logger.info(
            f"Released expired winner reservation on product {product.product_id} from auction {auction_id}."
        )
        return True

    async def get_auction_detail(
        self, auction_id: int, current_user: Optional[User] = None
    ) -> AuctionDetailResponse:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        auction = await self.close_single_auction_if_expired(auction_id, now_utc)
        if not auction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy phiên đấu giá.",
            )
        return await format_auction_detail(auction, self.auction_repo, current_user, now_utc=now_utc)

    async def get_auction_by_product(
        self, product_id: int, current_user: Optional[User] = None
    ) -> AuctionDetailResponse:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        auction = await self.auction_repo.get_active_or_latest_by_product_id(product_id)
        if not auction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy phiên đấu giá nào cho sản phẩm này.",
            )
        # Finalize on the fly if active and expired
        if auction.status == AuctionStatus.ACTIVE.value and auction.ends_at <= now_utc:
            updated_auction = await self.close_single_auction_if_expired(auction.auction_id, now_utc)
            if updated_auction:
                auction = updated_auction

        return await format_auction_detail(auction, self.auction_repo, current_user, now_utc=now_utc)

    async def list_bids(
        self,
        auction_id: int,
        cursor: Optional[str] = None,
        limit: int = 20,
        current_user: Optional[User] = None,
    ) -> AuctionBidCursorPage:
        limit = max(1, min(limit, 50))
        cursor_data = decode_bid_cursor(cursor) if cursor else None
        bids = await self.auction_repo.list_bids_keyset(auction_id, cursor=cursor_data, limit=limit)

        has_more = len(bids) > limit
        if has_more:
            bids = bids[:limit]

        next_cursor = None
        if has_more and bids:
            last_bid = bids[-1]
            next_cursor = encode_bid_cursor(last_bid.amount, last_bid.created_at, last_bid.bid_id)

        # Determine highest bid_id for leading bidder badge
        highest_bid_row = await self.auction_repo.get_highest_bid(auction_id)
        highest_bid_id = highest_bid_row.bid_id if highest_bid_row else None

        items = [
            AuctionBidResponse(
                bid_id=b.bid_id,
                auction_id=b.auction_id,
                bidder_display=anonymize_name(b.bidder.full_name if b.bidder else None),
                bidder_avatar_url=b.bidder.avatar_url if b.bidder else None,
                amount=b.amount,
                created_at=b.created_at,
                is_current_user=(
                    current_user is not None and b.bidder_id == current_user.user_id
                ),
                is_highest=(highest_bid_id is not None and b.bid_id == highest_bid_id),
            )
            for b in bids
        ]

        return AuctionBidCursorPage(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def get_my_won_auctions(self, current_user: User) -> list[WonAuctionItemResponse]:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        # 1. On-demand sweep of any expired active auctions to ensure recent ends are finalized
        candidate_ids = await self.auction_repo.get_active_auctions_to_close(now_utc=now_utc, limit=50)
        for cand_id in candidate_ids:
            try:
                await self.close_single_auction_if_expired(cand_id, now_utc)
            except Exception as e:
                logger.warning(f"Error finalizing candidate auction {cand_id}: {e}")

        # 2. Query won auctions pending checkout
        won_auctions = await self.auction_repo.get_won_auctions_pending_checkout(
            user_id=current_user.user_id, now_utc=now_utc
        )

        items: list[WonAuctionItemResponse] = []
        for auc in won_auctions:
            if not auc.product or getattr(auc.product, "is_deleted", False):
                logger.warning(
                    f"Excluding inconsistent won auction {auc.auction_id}: product {auc.product_id} is deleted or missing"
                )
                continue

            thumbnail_url = None
            if hasattr(auc.product, "images") and auc.product.images:
                thumb = next((img for img in auc.product.images if img.is_thumbnail), auc.product.images[0])
                thumbnail_url = thumb.image_url if thumb else None

            items.append(
                WonAuctionItemResponse(
                    auction_id=auc.auction_id,
                    product_id=auc.product_id,
                    product_title=auc.product.title,
                    product_image_url=thumbnail_url,
                    final_price=auc.final_price or Decimal(0),
                    winner_checkout_deadline=auc.winner_checkout_deadline or now_utc,
                    server_time=now_utc,
                )
            )

        return items

    async def winner_checkout(
        self, winner: User, auction_id: int, payload: WinnerCheckoutRequest
    ) -> Order:
        if winner.status != UserStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tài khoản của bạn không được phép mua hàng.",
            )

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        if not await CapabilityService(self.db).can_user_buy(winner.user_id, now_utc=now_utc):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "BUY_RESTRICTED",
                    "message": "Tài khoản của bạn đang bị giới hạn quyền mua hàng.",
                },
            )

        # 1. Close single auction if expired, obtaining authoritative row lock and status
        auction = await self.close_single_auction_if_expired(auction_id, now_utc)
        if not auction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy phiên đấu giá.",
            )

        # 2. Lock Auction FOR UPDATE in current transaction to ensure strict freshness
        auction = await self.auction_repo.get_auction_by_id(auction_id, for_update=True)
        if not auction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy phiên đấu giá.",
            )

        if auction.status != AuctionStatus.ENDED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phiên đấu giá chưa kết thúc.",
            )

        if not auction.winner_id or auction.winner_id != winner.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không phải người thắng phiên đấu giá này.",
            )

        if not auction.final_price or auction.final_price <= Decimal(0):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Giá chốt phiên đấu giá không hợp lệ.",
            )

        if not auction.winner_checkout_deadline or now_utc > auction.winner_checkout_deadline:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Đã hết thời hạn hoàn tất đặt mua cho phiên đấu giá này.",
            )

        # 2. Lock Product FOR UPDATE
        stmt_prod = select(Product).where(Product.product_id == auction.product_id).with_for_update()
        res_prod = await self.db.execute(stmt_prod)
        product = res_prod.scalar_one_or_none()

        if not product or product.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sản phẩm không tồn tại.",
            )

        if product.moderation_status == ProductModerationStatus.BLOCKED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sản phẩm đã bị quản trị viên ẩn hoặc không còn khả dụng.",
            )

        # Check single-order-per-auction guarantee
        existing_order_stmt = select(Order).where(Order.auction_id == auction.auction_id).limit(1)
        res_order = await self.db.execute(existing_order_stmt)
        existing_order = res_order.scalar_one_or_none()
        if existing_order:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Quyền mua từ phiên đấu giá này đã được sử dụng.",
            )

        if product.reserved_stock < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Lỗi dữ liệu tồn kho: quyền giữ hàng của người thắng không khả dụng.",
            )

        # Delegate directly to OrderService for order creation with transferred reservation
        order_service = OrderService(self.db)
        created_order = await order_service.create_auction_winner_order(
            winner=winner,
            auction=auction,
            product=product,
            payload=payload,
            now_utc=now_utc,
        )

        await self.db.commit()

        try:
            from app.modules.orders.websocket import (
                publish_auction_winner_checked_out,
                publish_order_created,
                publish_user_event,
            )
            await publish_auction_winner_checked_out(
                seller_id=product.seller_id,
                auction_id=auction.auction_id,
                order_id=created_order.order_id,
            )
            await publish_order_created(
                seller_id=product.seller_id,
                order_id=created_order.order_id,
            )
            if hasattr(created_order, "_notification_snapshot"):
                await publish_user_event(
                    product.seller_id,
                    {
                        "type": "NOTIFICATION_CREATED",
                        "notification": created_order._notification_snapshot.model_dump(mode="json"),
                    },
                )
        except Exception as e:
            logger.error(f"Failed to publish winner checkout event: {e}")

        return await order_service.get_order_detail(created_order.order_id, winner)

    async def convert_product_to_fixed_price(self, seller: User, product_id: int) -> None:
        # Lock Product FOR UPDATE
        stmt = (
            select(Product)
            .where(
                Product.product_id == product_id,
                Product.is_deleted.is_(False),
            )
            .with_for_update()
        )
        res = await self.db.execute(stmt)
        product = res.scalar_one_or_none()

        if not product or (product.seller_id != seller.user_id and seller.role != "ADMIN"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sản phẩm không tồn tại hoặc bạn không có quyền sở hữu.",
            )

        # Revalidate auction state without lock
        active_auction = await self.auction_repo.get_active_auction_by_product_id(product.product_id)
        if active_auction:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể chuyển sang bán giá cố định khi đang có phiên đấu giá hoạt động.",
            )

        if product.reserved_stock > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể chuyển hình thức bán khi sản phẩm đang có giao dịch giữ hàng.",
            )

        product.listing_type = ListingType.FIXED_PRICE.value
        await self.db.commit()


# ==============================================================================
# WORKER PERIODIC SWEEPS
# ==============================================================================

async def run_auction_scheduled_sweep(
    session_factory: async_sessionmaker[AsyncSession],
) -> SweepResult:
    """Activates SCHEDULED auctions whose starts_at <= NOW(), or finalizes them if already expired."""
    start_time = time.monotonic()
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    async with session_factory() as read_session:
        repo = AuctionRepository(read_session)
        candidate_ids = await repo.get_scheduled_auctions_to_sweep(
            now_utc=now_utc, limit=settings.WORKER_BATCH_SIZE
        )

    if not candidate_ids:
        return SweepResult(changed=0, candidates=0, no_op=0, failed=0)

    changed_count = 0
    noop_count = 0
    failed_count = 0

    for auction_id in candidate_ids:
        try:
            async def _activate():
                async with session_factory() as tx_session:
                    service = AuctionService(tx_session)
                    return await service.activate_or_end_single_scheduled_auction(
                        auction_id, now_utc=now_utc
                    )

            changed = await execute_with_retry(
                _activate,
                max_retries=settings.WORKER_MAX_RETRIES,
                backoff_seconds=settings.WORKER_RETRY_BACKOFF_SECONDS,
                operation_name=f"auction_scheduled_sweep:{auction_id}",
            )
            if changed:
                changed_count += 1
            else:
                noop_count += 1
        except Exception as e:
            failed_count += 1
            logger.error(
                f"[run_auction_scheduled_sweep] Error processing auction {auction_id} ({type(e).__name__}): {e}"
            )

    elapsed_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        f"[run_auction_scheduled_sweep] completed in {elapsed_ms:.1f}ms: "
        f"candidates={len(candidate_ids)}, changed={changed_count}, no_op={noop_count}, failed={failed_count}"
    )
    return SweepResult(
        changed=changed_count,
        candidates=len(candidate_ids),
        no_op=noop_count,
        failed=failed_count,
    )


async def run_auction_close_sweep(
    session_factory: async_sessionmaker[AsyncSession],
) -> SweepResult:
    """Closes ACTIVE auctions whose ends_at <= NOW(), determines winner and reserves inventory."""
    start_time = time.monotonic()
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    async with session_factory() as read_session:
        repo = AuctionRepository(read_session)
        candidate_ids = await repo.get_active_auctions_to_close(
            now_utc=now_utc, limit=settings.WORKER_BATCH_SIZE
        )

    if not candidate_ids:
        return SweepResult(changed=0, candidates=0, no_op=0, failed=0)

    changed_count = 0
    noop_count = 0
    failed_count = 0

    for auction_id in candidate_ids:
        try:
            async def _close():
                async with session_factory() as tx_session:
                    service = AuctionService(tx_session)
                    return await service.close_single_auction_sweep(
                        auction_id, now_utc=now_utc
                    )

            changed = await execute_with_retry(
                _close,
                max_retries=settings.WORKER_MAX_RETRIES,
                backoff_seconds=settings.WORKER_RETRY_BACKOFF_SECONDS,
                operation_name=f"auction_close_sweep:{auction_id}",
            )
            if changed:
                changed_count += 1
            else:
                noop_count += 1
        except Exception as e:
            failed_count += 1
            logger.error(
                f"[run_auction_close_sweep] Error closing auction {auction_id} ({type(e).__name__}): {e}"
            )

    elapsed_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        f"[run_auction_close_sweep] completed in {elapsed_ms:.1f}ms: "
        f"candidates={len(candidate_ids)}, changed={changed_count}, no_op={noop_count}, failed={failed_count}"
    )
    return SweepResult(
        changed=changed_count,
        candidates=len(candidate_ids),
        no_op=noop_count,
        failed=failed_count,
    )


async def run_winner_timeout_sweep(
    session_factory: async_sessionmaker[AsyncSession],
) -> SweepResult:
    """Releases expired winner stock reservations if no order was created."""
    start_time = time.monotonic()
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    async with session_factory() as read_session:
        repo = AuctionRepository(read_session)
        candidate_ids = await repo.get_expired_winner_auctions(
            now_utc=now_utc, limit=settings.WORKER_BATCH_SIZE
        )

    if not candidate_ids:
        return SweepResult(changed=0, candidates=0, no_op=0, failed=0)

    changed_count = 0
    noop_count = 0
    failed_count = 0

    for auction_id in candidate_ids:
        try:
            async def _timeout():
                async with session_factory() as tx_session:
                    service = AuctionService(tx_session)
                    return await service.timeout_single_winner_checkout(
                        auction_id, now_utc=now_utc
                    )

            changed = await execute_with_retry(
                _timeout,
                max_retries=settings.WORKER_MAX_RETRIES,
                backoff_seconds=settings.WORKER_RETRY_BACKOFF_SECONDS,
                operation_name=f"winner_timeout_sweep:{auction_id}",
            )
            if changed:
                changed_count += 1
            else:
                noop_count += 1
        except Exception as e:
            failed_count += 1
            logger.error(
                f"[run_winner_timeout_sweep] Error timing out auction {auction_id} ({type(e).__name__}): {e}"
            )

    elapsed_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        f"[run_winner_timeout_sweep] completed in {elapsed_ms:.1f}ms: "
        f"candidates={len(candidate_ids)}, changed={changed_count}, no_op={noop_count}, failed={failed_count}"
    )
    return SweepResult(
        changed=changed_count,
        candidates=len(candidate_ids),
        no_op=noop_count,
        failed=failed_count,
    )
