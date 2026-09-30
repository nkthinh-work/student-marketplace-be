"""
Tests for Finding-04: OpenAPI and Swagger UI Production Exposure.

Requirements:
- In development/test environments, OpenAPI documentation (/docs, /redoc, /openapi.json)
  must remain available.
- In production environment (ENVIRONMENT == "production"), /docs, /redoc, and /openapi.json
  must be disabled (return 404).
- Application normal API routes (e.g. /, /health) must remain available in all environments.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from app.core.config import settings
from app.main import app, create_app


@pytest.mark.asyncio
async def test_openapi_available_in_development_or_test():
    """
    In non-production environments (development, test):
    /docs, /redoc, and /openapi.json must be accessible with HTTP 200.
    """
    assert settings.ENVIRONMENT.lower() != "production"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        # 1. /docs Swagger UI
        res_docs = await ac.get("/docs")
        assert res_docs.status_code == 200

        # 2. /redoc ReDoc UI
        res_redoc = await ac.get("/redoc")
        assert res_redoc.status_code == 200

        # 3. /openapi.json OpenAPI Schema
        res_openapi = await ac.get("/openapi.json")
        assert res_openapi.status_code == 200
        schema = res_openapi.json()
        assert "openapi" in schema
        assert "paths" in schema


@pytest.mark.asyncio
async def test_openapi_disabled_in_production(monkeypatch):
    """
    When ENVIRONMENT == 'production':
    - /docs -> 404 Not Found
    - /redoc -> 404 Not Found
    - /openapi.json -> 404 Not Found
    - Normal API routes (e.g., /, /health) must remain available.
    """
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    prod_app = create_app()

    # Verify FastAPI configuration attributes directly
    assert prod_app.docs_url is None
    assert prod_app.redoc_url is None
    assert prod_app.openapi_url is None

    async with AsyncClient(
        transport=ASGITransport(app=prod_app),
        base_url="http://test",
    ) as ac:
        # 1. Swagger UI must return 404
        res_docs = await ac.get("/docs")
        assert res_docs.status_code == 404

        # 2. ReDoc UI must return 404
        res_redoc = await ac.get("/redoc")
        assert res_redoc.status_code == 404

        # 3. OpenAPI schema JSON must return 404
        res_openapi = await ac.get("/openapi.json")
        assert res_openapi.status_code == 404

        # 4. Root endpoint must remain functional
        res_root = await ac.get("/")
        assert res_root.status_code == 200
        assert res_root.json() == {"message": "Welcome to Student Marketplace C2C API"}
