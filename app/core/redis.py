import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
import logging
import uuid
import redis.asyncio as aioredis
from app.core.config import settings

logger = logging.getLogger("app.redis")

# Unique identifier for this process instance (used for pub/sub loopback deduplication)
INSTANCE_ID = str(uuid.uuid4())

redis_client: aioredis.Redis | None = None
_last_connect_attempt: float = 0.0
_RECONNECT_COOLDOWN_SECONDS: float = 5.0
_init_lock: asyncio.Lock | None = None


def _get_init_lock() -> asyncio.Lock:
    global _init_lock
    try:
        current_loop = asyncio.get_running_loop()
        if _init_lock is not None:
            lock_loop = getattr(_init_lock, "_loop", None)
            if lock_loop is not None and (lock_loop.is_closed() or lock_loop != current_loop):
                _init_lock = None
    except Exception:
        pass
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    return _init_lock


def get_redis_client() -> aioredis.Redis | None:
    """
    Returns the current Redis client instance, or None if not connected.
    """
    return redis_client


async def _connect_redis_locked() -> aioredis.Redis | None:
    """
    Internal connection routine. Must be called while holding _init_lock.
    """
    global redis_client, _last_connect_attempt
    _last_connect_attempt = datetime.now(timezone.utc).timestamp()

    # Close existing client if any, skipping aclose if its event loop is already closed
    if redis_client is not None:
        try:
            pool = getattr(redis_client, "connection_pool", None)
            is_closed_loop = False
            if pool is not None:
                for conn in getattr(pool, "_available_connections", []):
                    writer = getattr(conn, "_writer", None)
                    if writer:
                        loop = getattr(getattr(writer, "_transport", None), "_loop", None)
                        if loop and loop.is_closed():
                            is_closed_loop = True
                            break
            if not is_closed_loop:
                if hasattr(redis_client, "aclose"):
                    await redis_client.aclose()
                else:
                    await redis_client.close()
        except Exception:
            pass
        redis_client = None

    candidate: aioredis.Redis | None = None
    try:
        if settings.REDIS_URL:
            candidate = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
            )
        else:
            candidate = aioredis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                password=settings.REDIS_PASSWORD or None,
                decode_responses=True,
            )

        # Test connection with timeout
        await asyncio.wait_for(candidate.ping(), timeout=2.0)
        redis_client = candidate
        logger.info(
            "Redis connection established (host=%s, port=%s, db=%s)",
            settings.REDIS_HOST,
            settings.REDIS_PORT,
            settings.REDIS_DB,
        )
        return redis_client
    except Exception as e:
        logger.warning(
            "Redis unavailable (%s). Realtime fan-out running in degraded in-memory mode.",
            e,
        )
        if candidate is not None:
            try:
                if hasattr(candidate, "aclose"):
                    await candidate.aclose()
                else:
                    await candidate.close()
            except Exception:
                pass
        redis_client = None
        return None


async def init_redis() -> aioredis.Redis | None:
    """
    Initializes Redis client and validates connectivity with a ping.
    If ping fails, cleans up the client/pool and sets redis_client = None.
    Does not raise exceptions; returns active Redis client or None.
    """
    async with _get_init_lock():
        return await _connect_redis_locked()


async def get_or_reconnect_redis() -> aioredis.Redis | None:
    """
    Async single-flight: returns existing redis_client if active, or attempts
    reconnection once across concurrent callers if cooldown period has passed.
    Detects if client's underlying event loop has changed or closed.
    """
    global redis_client, _last_connect_attempt
    if redis_client is not None:
        try:
            current_loop = asyncio.get_running_loop()
            pool = getattr(redis_client, "connection_pool", None)
            if pool is not None:
                all_conns = list(getattr(pool, "_available_connections", [])) + list(getattr(pool, "_in_use_connections", set()))
                for conn in all_conns:
                    writer = getattr(conn, "_writer", None)
                    if writer:
                        loop = getattr(getattr(writer, "_transport", None), "_loop", None)
                        if loop and (loop.is_closed() or loop != current_loop):
                            redis_client = None
                            _last_connect_attempt = 0.0
                            break
        except Exception:
            pass

    if redis_client is not None:
        return redis_client

    now = datetime.now(timezone.utc).timestamp()
    if now - _last_connect_attempt < _RECONNECT_COOLDOWN_SECONDS:
        return None

    async with _get_init_lock():
        # Double-check inside lock
        if redis_client is not None:
            return redis_client
        now = datetime.now(timezone.utc).timestamp()
        if now - _last_connect_attempt < _RECONNECT_COOLDOWN_SECONDS:
            return None
        return await _connect_redis_locked()


async def close_redis() -> None:
    """
    Gracefully closes the Redis client and connection pool.
    """
    global redis_client
    async with _init_lock:
        if redis_client is not None:
            try:
                if hasattr(redis_client, "aclose"):
                    await redis_client.aclose()
                else:
                    await redis_client.close()
            except Exception as e:
                logger.error("Error closing Redis client: %s", e)
            finally:
                redis_client = None
                logger.info("Redis client closed.")


async def get_redis() -> AsyncGenerator[aioredis.Redis | None, None]:
    """
    FastAPI dependency for Redis.
    """
    if redis_client is None:
        await get_or_reconnect_redis()
    yield redis_client
