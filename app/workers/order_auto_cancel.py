import asyncio
from datetime import datetime, timezone
import logging
import signal
import sys
import time
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Ensure all SQLAlchemy ORM models are registered in the mapper registry for standalone worker process
import app.modules.users.models  # noqa: F401
import app.modules.categories.models  # noqa: F401
import app.modules.products.models  # noqa: F401
import app.modules.orders.models  # noqa: F401
import app.modules.auctions.models  # noqa: F401
import app.modules.notifications.models  # noqa: F401
import app.modules.conversations.models  # noqa: F401

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.redis import init_redis, close_redis
from app.modules.orders.repository import OrderRepository
from app.modules.orders.service import OrderService
from app.modules.auctions.service import (
    run_auction_scheduled_sweep,
    run_auction_close_sweep,
    run_winner_timeout_sweep,
)
from app.modules.products.view_counter import run_product_views_flush
from app.workers.media_cleanup import run_media_cleanup_sweep
from app.workers.retry import SweepResult, execute_with_retry, is_transient_db_error

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


async def run_auto_cancel_sweep(
    session_factory: async_sessionmaker[AsyncSession],
) -> SweepResult:
    """
    Executes one sweep of expired PENDING orders:
    1. Fetches candidate order IDs in a read session.
    2. Cancels each eligible order in an isolated transaction with bounded retry.
    Returns a SweepResult (acts as an int of changed count for backward compatibility).
    """
    start_time = time.monotonic()
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    async with session_factory() as read_session:
        repo = OrderRepository(read_session)
        candidate_ids = await repo.get_expired_pending_order_ids(
            now_utc=now_utc, limit=settings.WORKER_BATCH_SIZE
        )

    if not candidate_ids:
        return SweepResult(changed=0, candidates=0, no_op=0, failed=0)

    changed_count = 0
    noop_count = 0
    failed_count = 0

    for order_id in candidate_ids:
        try:
            async def _cancel():
                async with session_factory() as tx_session:
                    service = OrderService(tx_session)
                    return await service.auto_cancel_single_order(order_id)

            cancelled = await execute_with_retry(
                _cancel,
                max_retries=settings.WORKER_MAX_RETRIES,
                backoff_seconds=settings.WORKER_RETRY_BACKOFF_SECONDS,
                operation_name=f"order_auto_cancel:{order_id}",
            )
            if cancelled:
                changed_count += 1
                logger.info(f"Auto-cancelled expired order ID {order_id}")
            else:
                noop_count += 1
        except Exception as e:
            failed_count += 1
            logger.error(
                f"[run_auto_cancel_sweep] Error auto-cancelling order ID {order_id} ({type(e).__name__}): {e}"
            )

    elapsed_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        f"[run_auto_cancel_sweep] completed in {elapsed_ms:.1f}ms: "
        f"candidates={len(candidate_ids)}, changed={changed_count}, no_op={noop_count}, failed={failed_count}"
    )
    return SweepResult(
        changed=changed_count,
        candidates=len(candidate_ids),
        no_op=noop_count,
        failed=failed_count,
    )


async def start_worker_loop():
    logger.info(
        f"Starting unified worker loop (poll interval: {settings.WORKER_POLL_INTERVAL_SECONDS}s, "
        f"batch size: {settings.WORKER_BATCH_SIZE}, max retries: {settings.WORKER_MAX_RETRIES}, "
        f"order timeout: {settings.ORDER_CONFIRM_TIMEOUT_HOURS}h, "
        f"auction checkout deadline: {settings.AUCTION_WINNER_CHECKOUT_HOURS}h)..."
    )
    try:
        await init_redis()
    except Exception as e:
        logger.warning(
            f"Redis initialization failed on worker startup: {e}. "
            f"Realtime notifications/events may be degraded, but PostgreSQL domain transactions remain fully authoritative."
        )

    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    except Exception:
        # Signal handling might not be supported on non-main threads or some Windows setups
        pass

    _last_product_views_flush: float = 0.0

    while not _should_stop:
        # 1. Orders auto-cancel sweep
        try:
            cancelled_res = await run_auto_cancel_sweep(SessionLocal)
            if cancelled_res > 0:
                logger.info(f"Orders sweep finished: cancelled {cancelled_res.changed} expired orders.")
        except Exception as e:
            if is_transient_db_error(e):
                logger.warning(f"Database unavailable during orders sweep: {e}. Backing off 5s...")
                await asyncio.sleep(5)
            else:
                logger.error(f"Unexpected error during orders auto-cancel sweep: {e}", exc_info=True)

        # 2. Auctions scheduled sweep (activate or directly end if expired)
        try:
            sched_res = await run_auction_scheduled_sweep(SessionLocal)
            if sched_res > 0:
                logger.info(f"Auctions sweep finished: processed {sched_res.changed} scheduled auctions.")
        except Exception as e:
            if is_transient_db_error(e):
                logger.warning(f"Database unavailable during auctions scheduled sweep: {e}. Backing off 5s...")
                await asyncio.sleep(5)
            else:
                logger.error(f"Unexpected error during auctions scheduled sweep: {e}", exc_info=True)

        # 3. Auctions close sweep (close ended auctions and reserve winner stock)
        try:
            closed_res = await run_auction_close_sweep(SessionLocal)
            if closed_res > 0:
                logger.info(f"Auctions sweep finished: closed {closed_res.changed} ended auctions.")
        except Exception as e:
            if is_transient_db_error(e):
                logger.warning(f"Database unavailable during auctions close sweep: {e}. Backing off 5s...")
                await asyncio.sleep(5)
            else:
                logger.error(f"Unexpected error during auctions close sweep: {e}", exc_info=True)

        # 4. Auction winner timeout sweep (release unpurchased reservation)
        try:
            released_res = await run_winner_timeout_sweep(SessionLocal)
            if released_res > 0:
                logger.info(f"Auctions sweep finished: released {released_res.changed} expired winner reservations.")
        except Exception as e:
            if is_transient_db_error(e):
                logger.warning(f"Database unavailable during auction winner timeout sweep: {e}. Backing off 5s...")
                await asyncio.sleep(5)
            else:
                logger.error(f"Unexpected error during auction winner timeout sweep: {e}", exc_info=True)

        # 5. Product view counter periodic projection (Phase 9B)
        now_mono = time.monotonic()
        if now_mono - _last_product_views_flush >= settings.PRODUCT_VIEW_FLUSH_INTERVAL_SECONDS:
            try:
                views_res = await run_product_views_flush(SessionLocal)
                _last_product_views_flush = now_mono
                if views_res > 0:
                    logger.info(f"Product views sweep finished: projected {views_res.changed} products.")
            except Exception as e:
                logger.error(f"Unexpected error during product views flush: {e}", exc_info=True)

        # 6. Media cleanup jobs sweep (Chat Recall Media Hardening)
        try:
            cleanup_res = await run_media_cleanup_sweep(SessionLocal)
            if cleanup_res > 0:
                logger.info(f"Media cleanup sweep finished: processed {cleanup_res.changed} assets.")
        except Exception as e:
            if is_transient_db_error(e):
                logger.warning(f"Database unavailable during media cleanup sweep: {e}. Backing off 5s...")
                await asyncio.sleep(5)
            else:
                logger.error(f"Unexpected error during media cleanup sweep: {e}", exc_info=True)

        for _ in range(settings.WORKER_POLL_INTERVAL_SECONDS):
            if _should_stop:
                break
            await asyncio.sleep(1)

    logger.info("Worker loop exiting cleanly.")
    try:
        await close_redis()
    except Exception as e:
        logger.warning(f"Error closing Redis on worker shutdown: {e}")
    await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(start_worker_loop())
    except KeyboardInterrupt:
        logger.info("Worker stopped by KeyboardInterrupt.")
