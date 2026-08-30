import logging
from contextlib import asynccontextmanager
from typing import Any
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.database import get_db, engine
from app.core.redis import init_redis, close_redis, get_redis
from app.core.logging import setup_logging
from app.integrations.firebase import init_firebase
from app.integrations.cloudinary import init_cloudinary
from app.modules.users.router import router as users_router
from app.modules.categories.router import router as categories_router
from app.modules.products.router import router as products_router
from app.modules.favorites.router import router as favorites_router
from app.modules.orders.router import router as orders_router
from app.modules.orders.websocket import ws_router as orders_ws_router
from app.modules.auctions.router import router as auctions_router, ws_router as auctions_ws_router

logger = logging.getLogger("app")

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Starting up backend application...")
    await init_redis()
    init_firebase()
    init_cloudinary()
    yield
    logger.info("Shutting down backend application...")
    await close_redis()
    await engine.dispose()

app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users_router, prefix=settings.API_V1_STR)
app.include_router(categories_router, prefix=settings.API_V1_STR)
app.include_router(products_router, prefix=settings.API_V1_STR)
app.include_router(favorites_router, prefix=settings.API_V1_STR)
app.include_router(orders_router, prefix=settings.API_V1_STR)
app.include_router(orders_ws_router)
app.include_router(auctions_router, prefix=settings.API_V1_STR)
app.include_router(auctions_ws_router)

@app.get("/health")
async def health_check(
    db: AsyncSession = Depends(get_db),
    redis_conn: aioredis.Redis = Depends(get_redis)
) -> dict[str, Any]:
    db_status = "down"
    try:
        await db.execute(text("SELECT 1"))
        db_status = "up"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")

    redis_status = "down"
    try:
        if await redis_conn.ping():
            redis_status = "up"
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")

    overall_status = "healthy" if db_status == "up" and redis_status == "up" else "unhealthy"
    
    return {
        "status": overall_status,
        "database": db_status,
        "redis": redis_status,
        "service": "up"
    }

@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Welcome to Student Marketplace C2C API"}
