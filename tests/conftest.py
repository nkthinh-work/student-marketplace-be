import pytest
import pytest_asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

import cloudinary
from app.main import app
from app.core.config import settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.integrations.cloudinary import init_cloudinary

# Khởi tạo cấu hình Cloudinary cho test suite (mô phỏng lifespan khi chạy tests không qua ASGI server)
if not cloudinary.config().cloud_name:
    if settings.CLOUDINARY_CLOUD_NAME:
        init_cloudinary()
    else:
        cloudinary.config(cloud_name="test", secure=True)

# Dùng NullPool để tránh lỗi tái sử dụng connection giữa các event loop trên Windows
test_engine = create_async_engine(
    settings.database_url_async,
    poolclass=NullPool,
)


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=AsyncMock())
    return session


@pytest.fixture
def mock_redis_conn():
    conn = AsyncMock()
    conn.ping = AsyncMock(return_value=True)
    return conn


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Database session for integration tests using savepoints
    so changes are rolled back after each test.
    """
    async with test_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        yield session
        await session.close()
        await transaction.rollback()


@pytest_asyncio.fixture
async def test_client(db_session, mock_redis_conn) -> AsyncGenerator[AsyncClient, None]:
    """
    Test client wired with transactional test database session.
    """
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_redis] = lambda: mock_redis_conn

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(mock_db_session, mock_redis_conn) -> AsyncGenerator[AsyncClient, None]:
    """
    Standard test client for unit tests with mocked db session.
    """
    app.dependency_overrides[get_db] = lambda: mock_db_session
    app.dependency_overrides[get_redis] = lambda: mock_redis_conn

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
