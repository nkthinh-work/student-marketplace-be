from collections.abc import AsyncGenerator
import redis.asyncio as aioredis
from app.core.config import settings

redis_client: aioredis.Redis | None = None

async def init_redis() -> None:
    global redis_client
    redis_client = aioredis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        password=settings.REDIS_PASSWORD or None,
        decode_responses=True,
    )

async def close_redis() -> None:
    global redis_client
    if redis_client is not None:
        if hasattr(redis_client, "aclose"):
            await redis_client.aclose()
        else:
            await redis_client.close()
        redis_client = None

async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    if redis_client is None:
        await init_redis()
    yield redis_client