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
        assert response.status_code == 200
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
        assert data["status"] == "unhealthy"
        assert data["database"] == "up"
        assert data["redis"] == "down"
        assert data["service"] == "up"
        
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_root(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to Student Marketplace C2C API"}

