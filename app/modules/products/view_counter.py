"""
Redis Product View Counter Domain Module (Phase 9B)
- Exact atomic integer counter
- 24h viewer deduplication
- High-frequency Redis layer
- Periodic idempotent projection to PostgreSQL
- Safe under multi-worker and concurrent requests
"""

import logging
import time
from typing import Optional
from uuid import UUID
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.redis import get_redis_client
from app.modules.products.repository import ProductRepository
from app.workers.retry import SweepResult

logger = logging.getLogger("app.products.view_counter")

# Redis Key Namespaces
REDIS_KEY_PREFIX = "product:views"
DIRTY_SET_KEY = f"{REDIS_KEY_PREFIX}:dirty"
GLOBAL_SEQUENCE_KEY = f"{REDIS_KEY_PREFIX}:sequence"


def get_product_view_count_key(product_id: int) -> str:
    return f"{REDIS_KEY_PREFIX}:count:{product_id}"


def get_product_view_dedupe_key(product_id: int, viewer_token: str) -> str:
    return f"{REDIS_KEY_PREFIX}:seen:{product_id}:{viewer_token}"


def build_viewer_token(
    user_id: Optional[int], anonymous_id: Optional[UUID]
) -> Optional[str]:
    """
    Constructs a privacy-safe viewer token for deduplication.
    Authenticated user takes precedence over anonymous browser UUID.
    Never includes raw IP, email, or sensitive identifiers.
    """
    if user_id is not None:
        return f"u:{user_id}"
    if anonymous_id is not None:
        return f"a:{str(anonymous_id)}"
    return None


# Atomic registration script: checks DB floor, checks dedupe, increments counter and sequence, tags dirty.
REGISTER_VIEW_LUA = """
local counter_key = KEYS[1]
local dedupe_key = KEYS[2]
local dirty_key = KEYS[3]
local seq_key = KEYS[4]

local product_id = ARGV[1]
local db_view_count = tonumber(ARGV[2]) or 0
local dedupe_ttl = tonumber(ARGV[3]) or 86400

-- 1. Ensure Redis counter exists and is at least db_view_count
local current_count = redis.call('GET', counter_key)
if not current_count then
    current_count = db_view_count
    redis.call('SET', counter_key, current_count)
else
    current_count = tonumber(current_count) or 0
    if current_count < db_view_count then
        current_count = db_view_count
        redis.call('SET', counter_key, current_count)
    end
end

-- 2. Check if dedupe key already exists (already seen within dedupe window)
local seen = redis.call('EXISTS', dedupe_key)
if seen == 1 then
    -- Duplicate: do not increment, return current_count, counted = 0
    return {current_count, 0}
end

-- 3. First view from this viewer: mark as seen with TTL
redis.call('SET', dedupe_key, '1', 'EX', dedupe_ttl)

-- 4. Increment absolute counter
local new_count = redis.call('INCR', counter_key)

-- 5. Increment global dirty sequence & update dirty sorted set
local new_seq = redis.call('INCR', seq_key)
redis.call('ZADD', dirty_key, new_seq, product_id)

-- 6. Return new_count, counted = 1
return {new_count, 1}
"""

READ_EFFECTIVE_COUNT_LUA = """
local counter_key = KEYS[1]
local db_view_count = tonumber(ARGV[1]) or 0

local current_count = redis.call('GET', counter_key)
if not current_count then
    return db_view_count
end
current_count = tonumber(current_count) or 0
if current_count < db_view_count then
    return db_view_count
end
return current_count
"""

CONDITIONAL_ACK_LUA = """
local dirty_key = KEYS[1]
local product_id = ARGV[1]
local expected_version = tonumber(ARGV[2])

local current_version = redis.call('ZSCORE', dirty_key, product_id)
if current_version and tonumber(current_version) == expected_version then
    redis.call('ZREM', dirty_key, product_id)
    return 1
else
    return 0
end
"""


async def register_view_in_redis(
    redis: aioredis.Redis,
    product_id: int,
    viewer_token: str,
    db_view_count: int,
    dedupe_ttl: int = 86400,
) -> tuple[int, bool]:
    """
    Atomically registers a product view in Redis using Lua script.
    Returns (effective_view_count, was_counted).
    """
    keys = [
        get_product_view_count_key(product_id),
        get_product_view_dedupe_key(product_id, viewer_token),
        DIRTY_SET_KEY,
        GLOBAL_SEQUENCE_KEY,
    ]
    args = [
        str(product_id),
        str(db_view_count),
        str(dedupe_ttl),
    ]
    res = await redis.eval(REGISTER_VIEW_LUA, len(keys), *keys, *args)
    if not isinstance(res, (list, tuple)) or len(res) < 2:
        raise ValueError(f"Malformed Redis view registration response: {res}")
    return int(res[0]), bool(res[1])


async def get_effective_view_count_from_redis(
    redis: aioredis.Redis,
    product_id: int,
    db_view_count: int,
) -> int:
    """
    Reads the effective view count from Redis floored by authoritative db_view_count.
    Never modifies counter or state.
    """
    keys = [get_product_view_count_key(product_id)]
    args = [str(db_view_count)]
    res = await redis.eval(READ_EFFECTIVE_COUNT_LUA, len(keys), *keys, *args)
    return int(res)


async def get_effective_view_counts_batch(
    redis: Optional[aioredis.Redis],
    db_counts: dict[int, int],
) -> dict[int, int]:
    """
    Given a mapping of {product_id: db_view_count}, returns {product_id: effective_view_count}.
    - If db_counts is empty: return {} without calling Redis (zero MGET).
    - If redis client is unavailable / None: return a copy of db_counts.
    - For non-empty db_counts: executes exactly ONE batched MGET across all keys.
    - Defensively parses each Redis value:
      * Missing (None) or malformed individual Redis counter falls back to that product's DB floor.
      * Redis counter lower than DB floor falls back to DB floor (DB floor wins).
      * Minimum effective display value is 0.
    - On Redis infrastructure failure: fails open to all DB counts.
    """
    if not db_counts:
        return {}

    fallback = {pid: max(count or 0, 0) for pid, count in db_counts.items()}
    if redis is None:
        return fallback

    keys = [get_product_view_count_key(pid) for pid in db_counts.keys()]
    try:
        raw_values = await redis.mget(*keys)
    except Exception as e:
        logger.warning(
            "[get_effective_view_counts_batch] Redis MGET failed (%s): %s; failing open to DB counts",
            type(e).__name__,
            e,
        )
        return fallback

    result: dict[int, int] = {}
    for (pid, db_floor), raw in zip(db_counts.items(), raw_values):
        floor_val = max(db_floor or 0, 0)
        if raw is None:
            result[pid] = floor_val
        else:
            try:
                c = int(raw)
                result[pid] = max(c, floor_val)
            except (ValueError, TypeError):
                result[pid] = floor_val

    return result


async def get_dirty_product_views(
    redis: aioredis.Redis,
    limit: int = 200,
) -> list[tuple[int, int, int]]:
    """
    Retrieves up to `limit` dirty products that need synchronization to PostgreSQL.
    Returns list of tuples: (product_id, dirty_version, redis_count).
    """
    # 1. Fetch products from sorted set with their score (dirty sequence version)
    raw_dirty = await redis.zrange(DIRTY_SET_KEY, 0, limit - 1, withscores=True)
    if not raw_dirty:
        return []

    product_ids: list[int] = []
    versions: list[int] = []
    for item in raw_dirty:
        pid = int(item[0])
        ver = int(item[1])
        product_ids.append(pid)
        versions.append(ver)

    # 2. Batch fetch counter values
    counter_keys = [get_product_view_count_key(pid) for pid in product_ids]
    raw_counts = await redis.mget(*counter_keys)

    result: list[tuple[int, int, int]] = []
    for pid, ver, c_val in zip(product_ids, versions, raw_counts):
        count = int(c_val) if c_val is not None else 0
        result.append((pid, ver, count))

    return result


async def acknowledge_dirty_product_view(
    redis: aioredis.Redis,
    product_id: int,
    expected_version: int,
) -> bool:
    """
    Conditionally removes product from dirty sorted set only if its version
    still matches expected_version (i.e. no newer view was registered in the meantime).
    """
    keys = [DIRTY_SET_KEY]
    args = [str(product_id), str(expected_version)]
    res = await redis.eval(CONDITIONAL_ACK_LUA, len(keys), *keys, *args)
    return bool(res == 1)


async def run_product_views_flush(
    session_factory: async_sessionmaker[AsyncSession],
    batch_size: Optional[int] = None,
) -> SweepResult:
    """
    Periodic worker sweep to project dirty Redis product view totals to PostgreSQL.
    1. Reads bounded batch of dirty products from Redis.
    2. Updates PostgreSQL view_count floor monotonically inside a transaction.
    3. Commits the database transaction.
    4. Conditionally ACKs each product in Redis based on version score.
    Returns a SweepResult.
    """
    start_time = time.monotonic()
    limit = batch_size or settings.PRODUCT_VIEW_FLUSH_BATCH_SIZE

    redis = get_redis_client()
    if redis is None:
        return SweepResult(changed=0, candidates=0, no_op=0, failed=0)

    try:
        dirty_items = await get_dirty_product_views(redis, limit=limit)
    except Exception as e:
        logger.warning(
            "[run_product_views_flush] Redis failure reading dirty items (%s): %s",
            type(e).__name__,
            e,
        )
        return SweepResult(changed=0, candidates=0, no_op=0, failed=0)

    if not dirty_items:
        return SweepResult(changed=0, candidates=0, no_op=0, failed=0)

    changed_count = 0
    noop_count = 0
    failed_count = 0
    successfully_committed: list[tuple[int, int]] = []

    try:
        async with session_factory() as session:
            repo = ProductRepository(session)
            for pid, ver, redis_count in dirty_items:
                rows = await repo.update_view_count_floor(pid, redis_count)
                if rows > 0:
                    changed_count += 1
                else:
                    noop_count += 1
                successfully_committed.append((pid, ver))
            await session.commit()
    except Exception as e:
        failed_count = len(dirty_items)
        logger.error(
            "[run_product_views_flush] DB transaction failed during view projection (%s): %s",
            type(e).__name__,
            e,
        )
        # On DB failure, do NOT acknowledge any dirty items in Redis
        return SweepResult(
            changed=0,
            candidates=len(dirty_items),
            no_op=0,
            failed=failed_count,
        )

    # After DB commit succeeds, perform conditional version-safe ACK in Redis
    for pid, ver in successfully_committed:
        try:
            await acknowledge_dirty_product_view(redis, pid, ver)
        except Exception as e:
            logger.warning(
                "[run_product_views_flush] Failed to ACK product %s in Redis (%s): %s",
                pid,
                type(e).__name__,
                e,
            )

    elapsed_ms = (time.monotonic() - start_time) * 1000
    logger.info(
        f"[run_product_views_flush] completed in {elapsed_ms:.1f}ms: "
        f"candidates={len(dirty_items)}, changed={changed_count}, no_op={noop_count}, failed={failed_count}"
    )
    return SweepResult(
        changed=changed_count,
        candidates=len(dirty_items),
        no_op=noop_count,
        failed=failed_count,
    )

