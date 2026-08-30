import asyncio
from datetime import datetime, timezone
import logging
import signal
import sys
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.modules.orders.repository import OrderRepository
from app.modules.orders.service import OrderService
from app.modules.auctions.service import (
    run_auction_scheduled_sweep,
    run_auction_close_sweep,
    run_winner_timeout_sweep,
)

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("worker")

_should_stop = False


def _signal_handler(sig, frame):
    global _should_stop
    logger.info(f"Received shutdown signal ({sig}), initiating graceful shutdown...")
    _should_stop = True


async def run_auto_cancel_sweep(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """
    Executes one sweep of expired PENDING orders:
    1. Fetches candidate order IDs in a read session.
    2. Cancels each eligible order in an isolated transaction.
    Returns the number of orders successfully cancelled.
    """
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    async with session_factory() as read_session:
        repo = OrderRepository(read_session)
        candidate_ids = await repo.get_expired_pending_order_ids(now_utc=now_utc, limit=50)

    if not candidate_ids:
        return 0

    cancelled_count = 0
    for order_id in candidate_ids:
        try:
            async with session_factory() as tx_session:
                service = OrderService(tx_session)
                cancelled = await service.auto_cancel_single_order(order_id)
                if cancelled:
                    cancelled_count += 1
                    logger.info(f"Auto-cancelled expired order ID {order_id}")
        except Exception as e:
            logger.error(f"Error auto-cancelling order ID {order_id}: {e}", exc_info=True)

    return cancelled_count


async def start_worker_loop():
    logger.info(
        f"Starting unified worker loop (poll interval: {settings.WORKER_POLL_INTERVAL_SECONDS}s, order timeout: {settings.ORDER_CONFIRM_TIMEOUT_HOURS}h, auction checkout deadline: {settings.AUCTION_WINNER_CHECKOUT_HOURS}h)..."
    )

    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    except Exception:
        # Signal handling might not be supported on non-main threads or some Windows setups
        pass

    while not _should_stop:
        # 1. Orders auto-cancel sweep
        try:
            cancelled_count = await run_auto_cancel_sweep(SessionLocal)
            if cancelled_count > 0:
                logger.info(f"Orders sweep finished: cancelled {cancelled_count} expired orders.")
        except Exception as e:
            logger.error(f"Unexpected error during orders auto-cancel sweep: {e}", exc_info=True)

        # 2. Auctions scheduled sweep (activate or directly end if expired)
        try:
            sched_count = await run_auction_scheduled_sweep(SessionLocal)
            if sched_count > 0:
                logger.info(f"Auctions sweep finished: processed {sched_count} scheduled auctions.")
        except Exception as e:
            logger.error(f"Unexpected error during auctions scheduled sweep: {e}", exc_info=True)

        # 3. Auctions close sweep (close ended auctions and reserve winner stock)
        try:
            closed_count = await run_auction_close_sweep(SessionLocal)
            if closed_count > 0:
                logger.info(f"Auctions sweep finished: closed {closed_count} ended auctions.")
        except Exception as e:
            logger.error(f"Unexpected error during auctions close sweep: {e}", exc_info=True)

        # 4. Auction winner timeout sweep (release unpurchased reservation)
        try:
            released_count = await run_winner_timeout_sweep(SessionLocal)
            if released_count > 0:
                logger.info(f"Auctions sweep finished: released {released_count} expired winner reservations.")
        except Exception as e:
            logger.error(f"Unexpected error during auction winner timeout sweep: {e}", exc_info=True)

        for _ in range(settings.WORKER_POLL_INTERVAL_SECONDS):
            if _should_stop:
                break
            await asyncio.sleep(1)

    logger.info("Worker loop exiting cleanly.")
    await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(start_worker_loop())
    except KeyboardInterrupt:
        logger.info("Worker stopped by KeyboardInterrupt.")
