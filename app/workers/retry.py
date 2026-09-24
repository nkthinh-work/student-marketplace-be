import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional, TypeVar

from sqlalchemy.exc import DBAPIError, OperationalError

try:
    import asyncpg
except ImportError:
    asyncpg = None

logger = logging.getLogger("worker.retry")

T = TypeVar("T")

TRANSIENT_SQLSTATES = {
    "40001",  # serialization_failure
    "40P01",  # deadlock_detected
    "57P01",  # admin_shutdown
    "57P02",  # crash_shutdown
    "57P03",  # cannot_connect_now
    "08000",  # connection_exception
    "08003",  # connection_does_not_exist
    "08006",  # connection_failure
}


def is_transient_db_error(exc: BaseException) -> bool:
    """
    Determines if an exception is a transient database failure suitable for retry.
    Never treats IntegrityError, DataError, or domain logic errors as transient.
    """
    if getattr(exc, "is_transient", False) is True:
        return True

    sqlstate = getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)
    if sqlstate in TRANSIENT_SQLSTATES:
        return True

    if isinstance(exc, OperationalError):
        return True

    if isinstance(exc, DBAPIError):
        orig = getattr(exc, "orig", None)
        orig_sqlstate = getattr(orig, "sqlstate", None) or getattr(exc, "pgcode", None)
        if orig_sqlstate in TRANSIENT_SQLSTATES:
            return True
        if orig and asyncpg:
            asyncpg_exceptions = getattr(asyncpg, "exceptions", asyncpg)
            target_types = tuple(
                cls
                for name in (
                    "DeadlockDetectedError",
                    "SerializationError",
                    "CannotConnectNowError",
                    "ConnectionDoesNotExistError",
                    "InterfaceError",
                )
                if (cls := getattr(asyncpg_exceptions, name, getattr(asyncpg, name, None))) is not None
            )
            if target_types and isinstance(orig, target_types):
                return True

    if asyncpg:
        asyncpg_exceptions = getattr(asyncpg, "exceptions", asyncpg)
        target_types = tuple(
            cls
            for name in (
                "DeadlockDetectedError",
                "SerializationError",
                "CannotConnectNowError",
                "ConnectionDoesNotExistError",
                "InterfaceError",
            )
            if (cls := getattr(asyncpg_exceptions, name, getattr(asyncpg, name, None))) is not None
        )
        if target_types and isinstance(exc, target_types):
            return True

    return False


async def execute_with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 3,
    backoff_seconds: float = 0.5,
    operation_name: str = "worker_operation",
) -> T:
    """
    Executes an async operation with bounded retry only for transient DB failures.
    Non-transient errors (like domain logic or integrity errors) fail immediately.
    Guarantees no DB session is held during backoff sleep.
    """
    attempt = 0
    while True:
        try:
            return await operation()
        except asyncio.CancelledError:
            # Re-raise CancelledError immediately for graceful shutdown
            raise
        except Exception as e:
            attempt += 1
            if attempt > max_retries or not is_transient_db_error(e):
                logger.error(
                    f"[{operation_name}] Failed (attempt {attempt}/{max_retries + 1}, non-retryable or max retries exceeded): {e}",
                    exc_info=not is_transient_db_error(e),
                )
                raise

            delay = backoff_seconds * (2 ** (attempt - 1))
            logger.warning(
                f"[{operation_name}] Transient DB error on attempt {attempt}/{max_retries + 1}: {e}. Retrying in {delay:.2f}s..."
            )
            if delay > 0:
                await asyncio.sleep(delay)


class SweepResult(int):
    """
    Integer subclass containing rich metrics for worker sweep cycles.
    Maintains backward compatibility where int(result) or result > 0 is expected.
    """
    candidates: int
    changed: int
    no_op: int
    failed: int

    def __new__(cls, changed: int = 0, candidates: int = 0, no_op: int = 0, failed: int = 0):
        instance = super().__new__(cls, changed)
        instance.candidates = candidates
        instance.changed = changed
        instance.no_op = no_op
        instance.failed = failed
        return instance

    def __repr__(self) -> str:
        return (
            f"SweepResult(changed={self.changed}, candidates={self.candidates}, "
            f"no_op={self.no_op}, failed={self.failed})"
        )
