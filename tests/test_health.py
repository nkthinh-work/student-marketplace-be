import pytest
from unittest.mock import AsyncMock
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.database import get_db
from app.core.redis import get_redis

@pytest.mark.asyncio
async def test_health_check_healthy(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "up"
    assert data["redis"] == "up"
    assert data["service"] == "up"

@pytest.mark.asyncio
async def test_health_check_db_down(mock_redis_conn):
    failing_db = AsyncMock()
    failing_db.execute = AsyncMock(side_effect=Exception("DB Connection Error"))
    
    app.dependency_overrides[get_db] = lambda: failing_db
    app.dependency_overrides[get_redis] = lambda: mock_redis_conn
    
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        response = await ac.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["database"] == "down"
        assert data["redis"] == "up"
        assert data["service"] == "up"
        
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_health_check_redis_down(mock_db_session):
    failing_redis = AsyncMock()
    failing_redis.ping = AsyncMock(side_effect=Exception("Redis Connection Error"))
    
    app.dependency_overrides[get_db] = lambda: mock_db_session
    app.dependency_overrides[get_redis] = lambda: failing_redis
    
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        response = await ac.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "up"
        assert data["redis"] == "down"
        assert data["service"] == "up"
        
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_health_check_both_db_and_redis_down():
    failing_db = AsyncMock()
    failing_db.execute = AsyncMock(side_effect=Exception("DB Connection Error"))
    failing_redis = AsyncMock()
    failing_redis.ping = AsyncMock(side_effect=Exception("Redis Connection Error"))

    app.dependency_overrides[get_db] = lambda: failing_db
    app.dependency_overrides[get_redis] = lambda: failing_redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        response = await ac.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["database"] == "down"
        assert data["redis"] == "down"
        assert data["service"] == "up"

    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_root(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to Student Marketplace C2C API"}


@pytest.mark.asyncio
async def test_health_check_db_timeout(mock_redis_conn):
    """Xác nhận khi truy vấn CSDL bị timeout, endpoint trả về HTTP 503, status unhealthy và database down."""
    failing_db = AsyncMock()
    failing_db.execute = AsyncMock(side_effect=TimeoutError("Postgres query timed out"))

    app.dependency_overrides[get_db] = lambda: failing_db
    app.dependency_overrides[get_redis] = lambda: mock_redis_conn

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        response = await ac.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["database"] == "down"
        assert data["redis"] == "up"
        assert data["service"] == "up"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_check_never_leaks_secrets_in_payload(mock_redis_conn):
    """Payload /health tuyệt đối không rò rỉ chi tiết ngoại lệ hoặc mật khẩu kết nối."""
    failing_db = AsyncMock()
    failing_db.execute = AsyncMock(
        side_effect=Exception("FATAL: password authentication failed with PGPASSWORD=SuperSecretPass123!")
    )

    app.dependency_overrides[get_db] = lambda: failing_db
    app.dependency_overrides[get_redis] = lambda: mock_redis_conn

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        response = await ac.get("/health")
        assert response.status_code == 503
        text = response.text
        assert "SuperSecretPass123!" not in text
        assert "password" not in text
        data = response.json()
        assert set(data.keys()) == {"status", "database", "redis", "service"}
        assert data["status"] == "unhealthy"
        assert data["database"] == "down"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_production_unhandled_exception_does_not_expose_details():
    """Lỗi 5xx nội bộ không để lộ stack trace hay secret ra client."""
    from app.main import create_app
    test_app = create_app()

    @test_app.get("/api/v1/test-unhandled-crash")
    async def crash():
        raise RuntimeError("CRITICAL_INTERNAL_DB_CRASH_SECRET_KEY_999")

    async with AsyncClient(
        transport=ASGITransport(app=test_app, raise_app_exceptions=False),
        base_url="http://test"
    ) as ac:
        response = await ac.get("/api/v1/test-unhandled-crash")
        assert response.status_code == 500
        assert "CRITICAL_INTERNAL_DB_CRASH_SECRET_KEY_999" not in response.text
        assert "Traceback" not in response.text

