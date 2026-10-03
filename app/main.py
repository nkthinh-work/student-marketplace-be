import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any
from fastapi import FastAPI, Depends, Response, status
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
from app.modules.reviews.router import router as reviews_router
from app.modules.conversations.router import router as conversations_router
from app.modules.daily_needs.router import router as daily_needs_router
from app.modules.notifications.router import router as notifications_router
from app.modules.reports.admin_router import (
    router as admin_reports_router,
    admin_users_router,
)
from app.modules.reports.router import router as reports_router
from app.modules.community_moments.router import router as community_moments_router
from app.modules.community_moments.admin_router import (
    router as admin_community_moments_router,
)
from app.modules.feedback.router import router as feedback_router
from app.modules.feedback.admin_router import router as admin_feedback_router
from app.modules.feedback.admin_support_router import router as admin_support_router
from app.modules.feedback.admin_support_claims_router import router as admin_support_claims_router
from app.modules.tutorials.router import router as tutorials_router
from app.modules.tutorials.admin_router import router as admin_tutorials_router
from app.modules.products.admin_router import router as admin_product_approvals_router



from app.core.rate_limiter import RateLimitMiddleware

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

def create_app() -> FastAPI:
    is_production = settings.ENVIRONMENT.lower() == "production"

    application = FastAPI(
        title=settings.PROJECT_NAME,
        lifespan=lifespan,
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )

    # Outermost middleware is CORSMiddleware; RateLimitMiddleware sits inside CORS
    application.add_middleware(RateLimitMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(users_router, prefix=settings.API_V1_STR)
    application.include_router(categories_router, prefix=settings.API_V1_STR)
    application.include_router(products_router, prefix=settings.API_V1_STR)
    application.include_router(favorites_router, prefix=settings.API_V1_STR)
    application.include_router(orders_router, prefix=settings.API_V1_STR)
    application.include_router(orders_ws_router)
    application.include_router(auctions_router, prefix=settings.API_V1_STR)
    application.include_router(auctions_ws_router)
    application.include_router(reviews_router, prefix=settings.API_V1_STR)
    application.include_router(conversations_router, prefix=settings.API_V1_STR)
    application.include_router(daily_needs_router, prefix=settings.API_V1_STR)
    application.include_router(notifications_router, prefix=settings.API_V1_STR)
    application.include_router(reports_router, prefix=settings.API_V1_STR)
    application.include_router(admin_reports_router, prefix=settings.API_V1_STR)
    application.include_router(admin_users_router, prefix=settings.API_V1_STR)
    application.include_router(community_moments_router, prefix=settings.API_V1_STR)
    application.include_router(admin_community_moments_router, prefix=settings.API_V1_STR)
    application.include_router(feedback_router, prefix=settings.API_V1_STR)
    application.include_router(admin_feedback_router, prefix=settings.API_V1_STR)
    application.include_router(admin_support_router, prefix=settings.API_V1_STR)
    application.include_router(admin_support_claims_router, prefix=settings.API_V1_STR)
    application.include_router(tutorials_router, prefix=settings.API_V1_STR)
    application.include_router(admin_tutorials_router, prefix=settings.API_V1_STR)
    application.include_router(admin_product_approvals_router, prefix=settings.API_V1_STR)

    @application.get("/health")
    async def health_check(
        response: Response,
        db: AsyncSession = Depends(get_db),
        redis_conn: aioredis.Redis = Depends(get_redis)
    ) -> dict[str, Any]:
        db_status = "down"
        try:
            await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=2.0)
            db_status = "up"
        except Exception as e:
            logger.error(f"Database health check failed: {e}")

        redis_status = "down"
        try:
            if redis_conn is not None:
                if await asyncio.wait_for(redis_conn.ping(), timeout=1.0):
                    redis_status = "up"
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")

        if db_status == "up":
            overall_status = "healthy" if redis_status == "up" else "degraded"
            response.status_code = status.HTTP_200_OK
        else:
            overall_status = "unhealthy"
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        return {
            "status": overall_status,
            "database": db_status,
            "redis": redis_status,
            "service": "up"
        }

    @application.get("/")
    async def root() -> dict[str, str]:
        return {"message": "Welcome to Student Marketplace C2C API"}

    return application


app = create_app()
