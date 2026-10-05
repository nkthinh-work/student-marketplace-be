import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.integrations.cloudinary import destroy_asset_async
from app.modules.conversations.models import MediaCleanupJob
from app.workers.retry import SweepResult

logger = logging.getLogger("worker.media_cleanup")

MEDIA_CLEANUP_INITIAL_RETRY_SECONDS = 60
CLAIM_LEASE_SECONDS = 300  # 5 minutes claim lease to protect against concurrent workers

BACKOFF_DELAYS = [
    60,      # 1st retry: 1 min
    300,     # 2nd retry: 5 mins
    900,     # 3rd retry: 15 mins
    3600,    # 4th retry: 1 hour
    21600,   # 5th retry: 6 hours
]
MAX_BACKOFF_SECONDS = 86400  # 6th+ retry: 24 hours (capped)

SENSITIVE_PATTERNS = [
    re.compile(r'(api_key|api_secret|secret|password|token|bearer|authorization)=[^&\s]+', re.IGNORECASE),
    re.compile(r'https?://[^\s]+', re.IGNORECASE),
    re.compile(r'Bearer\s+[A-Za-z0-9\-._~+/]+=*', re.IGNORECASE),
]


def sanitize_external_error(exc: Exception | str, max_length: int = 500) -> str:
    """
    Sanitizes external error messages before persisting to database or logging:
    - Strips credentials, API secrets, tokens, signed URLs
    - Normalizes error type and brief diagnostic summary
    - Truncates to max_length characters (default 500)
    """
    if isinstance(exc, Exception):
        exc_type = type(exc).__name__
        raw_msg = str(exc)
        text = f"{exc_type}: {raw_msg}" if raw_msg else exc_type
    else:
        text = str(exc)

    for pattern in SENSITIVE_PATTERNS:
        text = pattern.sub("[REDACTED]", text)

    text = " ".join(text.split())
    if len(text) > max_length:
        text = text[:max_length - 3] + "..."
    return text


def calculate_next_retry_at(attempt_count: int, base_time: Optional[datetime] = None) -> datetime:
    """Calculates bounded exponential backoff timestamp based on attempt count."""
    if base_time is None:
        base_time = datetime.now(timezone.utc).replace(tzinfo=None)

    idx = max(0, attempt_count - 1)
    if idx < len(BACKOFF_DELAYS):
        delay = BACKOFF_DELAYS[idx]
    else:
        delay = MAX_BACKOFF_SECONDS

    return base_time + timedelta(seconds=delay)


async def run_media_cleanup_sweep(
    session_factory: async_sessionmaker[AsyncSession],
) -> SweepResult:
    """
    Executes one sweep of pending media cleanup jobs with multi-worker concurrency protection:
    1. Claims candidates with SELECT ... FOR UPDATE SKIP LOCKED.
    2. Advances next_retry_at by CLAIM_LEASE_SECONDS and commits the claim transaction immediately,
       so other worker replicas skip these rows and no DB locks are held during external work.
    3. Sequentially executes Cloudinary destroy off the event loop.
    4. On success (or asset already not found): deletes the cleanup job.
    5. On failure: increments attempt_count and applies bounded backoff with sanitized last_error.
    """
    start_time = time.monotonic()
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    # 1. Atomic batch claim with FOR UPDATE SKIP LOCKED
    candidates: list[tuple[int, str, str, int]] = []
    async with session_factory() as session:
        stmt = (
            select(MediaCleanupJob)
            .where(MediaCleanupJob.next_retry_at <= now_utc)
            .order_by(MediaCleanupJob.next_retry_at.asc(), MediaCleanupJob.cleanup_id.asc())
            .with_for_update(skip_locked=True)
            .limit(settings.WORKER_BATCH_SIZE)
        )
        jobs = list((await session.scalars(stmt)).all())
        if not jobs:
            return SweepResult(changed=0, candidates=0, no_op=0, failed=0)

        claim_expiry = now_utc + timedelta(seconds=CLAIM_LEASE_SECONDS)
        for job in jobs:
            candidates.append((job.cleanup_id, job.storage_key, job.resource_type, job.attempt_count))
            job.next_retry_at = claim_expiry
            job.updated_at = now_utc
        await session.commit()

    changed_count = 0
    failed_count = 0

    # 2. Process claimed jobs with external Cloudinary call (no DB locks held)
    for cleanup_id, storage_key, resource_type, current_attempts in candidates:
        try:
            success = await destroy_asset_async(storage_key, resource_type=resource_type)

            if success:
                async with session_factory() as tx_session:
                    await tx_session.execute(
                        delete(MediaCleanupJob).where(MediaCleanupJob.cleanup_id == cleanup_id)
                    )
                    await tx_session.commit()
                changed_count += 1
                logger.info(
                    "[media_cleanup] Successfully deleted asset %s (%s), removed job %s",
                    storage_key,
                    resource_type,
                    cleanup_id,
                )
            else:
                failed_count += 1
                new_attempts = current_attempts + 1
                next_retry = calculate_next_retry_at(new_attempts, now_utc)
                sanitized_msg = "Cloudinary destroy returned non-ok result"
                async with session_factory() as tx_session:
                    await tx_session.execute(
                        update(MediaCleanupJob)
                        .where(MediaCleanupJob.cleanup_id == cleanup_id)
                        .values(
                            attempt_count=new_attempts,
                            next_retry_at=next_retry,
                            last_error=sanitized_msg,
                            updated_at=now_utc,
                        )
                    )
                    await tx_session.commit()
                logger.warning(
                    "[media_cleanup] Asset destroy non-ok for %s, scheduled retry %s at %s",
                    storage_key,
                    new_attempts,
                    next_retry.isoformat(),
                )
        except Exception as e:
            failed_count += 1
            new_attempts = current_attempts + 1
            next_retry = calculate_next_retry_at(new_attempts, now_utc)
            sanitized_err = sanitize_external_error(e)
            try:
                async with session_factory() as tx_session:
                    await tx_session.execute(
                        update(MediaCleanupJob)
                        .where(MediaCleanupJob.cleanup_id == cleanup_id)
                        .values(
                            attempt_count=new_attempts,
                            next_retry_at=next_retry,
                            last_error=sanitized_err,
                            updated_at=now_utc,
                        )
                    )
                    await tx_session.commit()
            except Exception as db_err:
                logger.error(
                    "[media_cleanup] Failed to update cleanup job %s after error: %s",
                    cleanup_id,
                    sanitize_external_error(db_err),
                )
            logger.warning(
                "[media_cleanup] Exception during destroy for %s: %s. Scheduled retry %s at %s",
                storage_key,
                sanitized_err,
                new_attempts,
                next_retry.isoformat(),
            )

    elapsed_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        "[run_media_cleanup_sweep] completed in %.1fms: candidates=%d, changed=%d, failed=%d",
        elapsed_ms,
        len(candidates),
        changed_count,
        failed_count,
    )
    return SweepResult(
        changed=changed_count,
        candidates=len(candidates),
        no_op=0,
        failed=failed_count,
    )
