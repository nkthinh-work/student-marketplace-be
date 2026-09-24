import logging
from typing import List, Set, Tuple
from app.core.redis import get_redis_client, get_or_reconnect_redis

logger = logging.getLogger("app.realtime.presence")

PRESENCE_KEY_PREFIX = "presence:user:"
PRESENCE_TTL_SECONDS = 90  # 90-120 seconds bounded TTL


class _RedisPresenceProxy:
    """Dynamically proxies to active Redis client while allowing monkeypatching."""
    def __getattr__(self, name):
        rc = get_redis_client()
        if rc is None:
            raise AttributeError(f"'NoneType' object has no attribute '{name}'")
        return getattr(rc, name)

    def __bool__(self):
        return get_redis_client() is not None


# Expose redis_client proxy for backward compatibility with tests
redis_client = _RedisPresenceProxy()


async def record_user_presence(user_id: int) -> bool:
    """
    Refreshes presence heartbeat in Redis with bounded TTL.
    Gracefully returns False if Redis is unavailable without throwing.
    """
    if not redis_client:
        return False
    try:
        key = f"{PRESENCE_KEY_PREFIX}{user_id}"
        await redis_client.set(key, "1", ex=PRESENCE_TTL_SECONDS)
        return True
    except Exception as e:
        logger.debug(f"Redis presence record failed for user {user_id}: {e}")
        return False


async def get_users_presence(user_ids: List[int]) -> Tuple[bool, Set[int]]:
    """
    Batch queries presence for multiple user IDs in a single Redis MGET.
    Returns:
        (presence_available: bool, online_user_ids: Set[int])
    If Redis is down or unavailable, returns (False, empty set).
    """
    if not user_ids:
        return True, set()

    if not redis_client:
        return False, set()

    try:
        keys = [f"{PRESENCE_KEY_PREFIX}{uid}" for uid in user_ids]
        values = await redis_client.mget(keys)
        online_ids = {
            uid for uid, val in zip(user_ids, values) if val is not None
        }
        return True, online_ids
    except Exception as e:
        logger.warning(f"Redis batch presence lookup failed: {e}")
        return False, set()


async def is_user_online(user_id: int) -> Tuple[bool, bool]:
    """
    Checks whether a specific user is currently active.
    Returns (presence_available: bool, is_online: bool).
    """
    avail, online_set = await get_users_presence([user_id])
    return avail, user_id in online_set
