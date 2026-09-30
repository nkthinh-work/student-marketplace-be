"""
Production Security Hardening Test Suite:
Rate Limiting, Anti-Scraping, Abuse Prevention, and User Enumeration Defense.

Covers all 13 governance requirements:
1. Request below quota succeeds.
2. Boundary request succeeds correctly.
3. Request above quota returns 429.
4. Retry-After behavior is correct.
5. Quota becomes available again after window reset.
6. Two anonymous client identities do not share quota.
7. Two authenticated users do not share quota.
8. Repeated requests by one authenticated user consume that user's quota.
9. Existing auth semantics remain (anonymous /users/search -> 401, public profile remains public).
10. show_phone_publicly behavior remains intact.
11. Redis error behavior matches fail-open failure policy.
12. Health check endpoint behavior remains suitable for Railway health checks.
13. Anti-spoofing: Direct Railway origin callers cannot bypass rate limiting by spoofing CF-Connecting-IP.
"""

import asyncio
from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import redis.asyncio as aioredis

from app.main import app
from app.core.config import settings
from app.core.database import get_db
from app.core.redis import get_redis, get_redis_client, get_or_reconnect_redis
from app.core.rate_limiter import (
    IPRateLimiter,
    UserRateLimiter,
    check_rate_limit,
    rate_limit_user_profile,
    rate_limit_user_search,
)
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.users.models import User, UserRole, UserStatus
from starlette.requests import Request
from app.core.client_ip import extract_client_ip


@pytest_asyncio.fixture(autouse=True)
async def cleanup_redis_rate_limit_keys():
    """Cleans up rate limit test keys before and after each test."""
    client = await get_or_reconnect_redis()
    if client is not None:
        try:
            keys = await client.keys("rl:*")
            if keys:
                await client.delete(*keys)
        except Exception:
            pass
    yield
    if client is not None:
        try:
            keys = await client.keys("rl:*")
            if keys:
                await client.delete(*keys)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_check_rate_limit_below_and_boundary_and_exceeded():
    """
    Requirements 1, 2, 3, 4:
    - Below quota succeeds.
    - Boundary request succeeds.
    - Above quota returns allowed=False with Retry-After > 0.
    """
    client = await get_or_reconnect_redis()
    assert client is not None, "Redis client must be available locally for testing"

    key = "rl:test_core:ip:10.99.1.1"
    await client.delete(key)

    limit = 3
    window = 60

    # Request 1 (below quota)
    allowed, count, ttl = await check_rate_limit(client, key, limit, window)
    assert allowed is True
    assert count == 1
    assert 0 < ttl <= window

    # Request 2 (below quota)
    allowed, count, ttl = await check_rate_limit(client, key, limit, window)
    assert allowed is True
    assert count == 2

    # Request 3 (boundary)
    allowed, count, ttl = await check_rate_limit(client, key, limit, window)
    assert allowed is True
    assert count == 3

    # Request 4 (exceeded -> blocked)
    allowed, count, ttl = await check_rate_limit(client, key, limit, window)
    assert allowed is False
    assert count == 3  # Did not increment beyond limit
    assert 0 < ttl <= window

    await client.delete(key)


@pytest.mark.asyncio
async def test_rate_limit_window_reset():
    """
    Requirement 5:
    Quota becomes available again after window expiration.
    """
    client = await get_or_reconnect_redis()
    key = "rl:test_reset:ip:10.99.1.2"
    await client.delete(key)

    limit = 1
    window = 1  # 1 second window for deterministic testing

    # Request 1: allowed
    allowed, count, _ = await check_rate_limit(client, key, limit, window)
    assert allowed is True

    # Request 2: blocked
    allowed, count, _ = await check_rate_limit(client, key, limit, window)
    assert allowed is False

    # Wait for 1s window expiration
    await asyncio.sleep(1.1)

    # Request 3: allowed again after reset
    allowed, count, _ = await check_rate_limit(client, key, limit, window)
    assert allowed is True
    assert count == 1

    await client.delete(key)


@pytest.mark.asyncio
async def test_two_anonymous_clients_independent_quotas():
    """
    Requirement 6:
    Two anonymous client IPs do NOT share a quota.
    """
    client = await get_or_reconnect_redis()
    key_a = "rl:test_anon:ip:203.0.113.10"
    key_b = "rl:test_anon:ip:203.0.113.20"
    await client.delete(key_a, key_b)

    limit = 2
    window = 60

    # Client A consumes full quota
    await check_rate_limit(client, key_a, limit, window)
    await check_rate_limit(client, key_a, limit, window)
    allowed_a, _, _ = await check_rate_limit(client, key_a, limit, window)
    assert allowed_a is False, "Client A should be rate limited"

    # Client B still has full quota
    allowed_b1, count_b1, _ = await check_rate_limit(client, key_b, limit, window)
    assert allowed_b1 is True
    assert count_b1 == 1

    allowed_b2, count_b2, _ = await check_rate_limit(client, key_b, limit, window)
    assert allowed_b2 is True
    assert count_b2 == 2

    await client.delete(key_a, key_b)


@pytest.mark.asyncio
async def test_two_authenticated_users_independent_quotas():
    """
    Requirement 7:
    Two authenticated users do NOT share an authenticated quota even if from same NAT.
    """
    client = await get_or_reconnect_redis()
    user_key_1 = "rl:test_auth:u:101"
    user_key_2 = "rl:test_auth:u:102"
    await client.delete(user_key_1, user_key_2)

    limit = 2
    window = 60

    # User 1 consumes quota
    await check_rate_limit(client, user_key_1, limit, window)
    await check_rate_limit(client, user_key_1, limit, window)
    allowed_u1, _, _ = await check_rate_limit(client, user_key_1, limit, window)
    assert allowed_u1 is False, "User 1 should be rate limited"

    # User 2 still has quota available
    allowed_u2, count_u2, _ = await check_rate_limit(client, user_key_2, limit, window)
    assert allowed_u2 is True
    assert count_u2 == 1

    await client.delete(user_key_1, user_key_2)


@pytest.mark.asyncio
async def test_authenticated_user_repeated_requests_consume_quota(db_session):
    """
    Requirement 8:
    Repeated requests by one authenticated user consume that user's quota.
    """
    client = await get_or_reconnect_redis()
    test_user_id = 9999
    key = f"rl:user_search:u:{test_user_id}"
    await client.delete(key)

    mock_user = User(
        user_id=test_user_id,
        email="quota_test@ptit.edu.vn",
        full_name="Quota Test User",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )

    app.dependency_overrides[get_current_active_user] = lambda: mock_user
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            # Override limit to 3 for fast boundary testing
            with patch.object(settings, "RATE_LIMIT_USER_SEARCH_LIMIT", 3):
                # Request 1: 200
                res1 = await ac.get("/api/v1/users/search?q=test")
                assert res1.status_code == 200

                # Request 2: 200
                res2 = await ac.get("/api/v1/users/search?q=test")
                assert res2.status_code == 200

                # Request 3: 200 (boundary)
                res3 = await ac.get("/api/v1/users/search?q=test")
                assert res3.status_code == 200

                # Request 4: 429 Too Many Requests
                res4 = await ac.get("/api/v1/users/search?q=test")
                assert res4.status_code == 429
                assert "Retry-After" in res4.headers
                assert int(res4.headers["Retry-After"]) > 0
                assert res4.json() == {"detail": "Too many requests. Please try again later."}
    finally:
        app.dependency_overrides.clear()
        await client.delete(key)


@pytest.mark.asyncio
async def test_existing_auth_semantics_anonymous_search_returns_401():
    """
    Requirement 9a:
    Anonymous call to /api/v1/users/search returns 401 Unauthorized.
    Rate limiting does not interfere with 401 authentication rejection.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        res = await ac.get("/api/v1/users/search?q=anonymous")
        assert res.status_code == 401
        assert "detail" in res.json()


@pytest.mark.asyncio
async def test_public_user_profile_remains_public_and_throttled(db_session):
    """
    Requirement 9b, 1, 2, 3:
    Public profile /api/v1/users/{user_id} remains public (accessible without auth),
    but is protected by IP rate limiting against rapid scraping.
    """
    client = await get_or_reconnect_redis()
    test_ip = "192.0.2.100"
    key = f"rl:user_profile:ip:{test_ip}"
    await client.delete(key)

    app.dependency_overrides[get_db] = lambda: db_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            headers = {"x-forwarded-for": f"1.1.1.1, {test_ip}"}

            with patch.object(settings, "RATE_LIMIT_USER_PROFILE_LIMIT", 2):
                # Request 1: succeeds (404 or 200 depending on ID, not 429)
                r1 = await ac.get("/api/v1/users/999999", headers=headers)
                assert r1.status_code != 429

                # Request 2: succeeds (boundary)
                r2 = await ac.get("/api/v1/users/999999", headers=headers)
                assert r2.status_code != 429

                # Request 3: 429 Too Many Requests
                r3 = await ac.get("/api/v1/users/999999", headers=headers)
                assert r3.status_code == 429
                assert "Retry-After" in r3.headers
                assert r3.json() == {"detail": "Too many requests. Please try again later."}
    finally:
        app.dependency_overrides.clear()
        await client.delete(key)


@pytest.mark.asyncio
async def test_show_phone_publicly_privacy_preserved(db_session):
    """
    Requirement 10:
    Verifies that show_phone_publicly privacy logic remains intact:
    - show_phone_publicly = False -> phone is null in public response.
    """
    from app.modules.users.repository import UserRepository
    from app.modules.users.service import UserService

    user = User(
        email="phone_privacy_test@ptit.edu.vn",
        full_name="Phone Privacy Test",
        phone="0912345678",
        show_phone_publicly=False,
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()

    service = UserService(db_session)
    profile = await service.get_public_profile(user.user_id)

    assert profile.phone is None, "Phone must remain null when show_phone_publicly is False"
    assert "email" not in profile.model_dump(), "Email must not be in public profile"


@pytest.mark.asyncio
async def test_redis_failure_fail_open_policy():
    """
    Requirement 11:
    When Redis is unavailable or raises an exception, the rate limiter fails open
    gracefully without crashing the application.
    """
    with patch("app.core.rate_limiter.get_redis_client", return_value=None):
        with patch("app.core.rate_limiter.get_or_reconnect_redis", return_value=None):
            allowed, count, retry_after = await check_rate_limit(None, "rl:test:key", 5, 60)
            assert allowed is True
            assert count == 0
            assert retry_after == 0

    failing_redis = AsyncMock()
    failing_redis.eval = AsyncMock(side_effect=aioredis.ConnectionError("Redis connection lost"))
    allowed, count, retry_after = await check_rate_limit(failing_redis, "rl:test:key", 5, 60)
    assert allowed is True
    assert count == 0
    assert retry_after == 0


@pytest.mark.asyncio
async def test_health_check_endpoint_never_blocked(db_session):
    """
    Requirement 12:
    The /health check endpoint is exempt from rate limiting for Railway health check stability.
    """
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            for _ in range(10):
                res = await ac.get("/health")
                assert res.status_code == 200
                assert res.json()["status"] in ("healthy", "unhealthy")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_direct_origin_cannot_bypass_via_spoofed_cf_header(db_session):
    """
    Requirement 13 (Anti-Spoofing):
    An attacker calling the Railway origin directly cannot bypass rate limiting by
    sending random CF-Connecting-IP headers.
    Because connecting peer IP is not Cloudflare, CF-Connecting-IP is discarded and
    the real connecting peer IP is used as the limiter key.
    """
    client = await get_or_reconnect_redis()
    attacker_peer_ip = "198.51.100.77"
    key = f"rl:user_profile:ip:{attacker_peer_ip}"
    await client.delete(key)

    app.dependency_overrides[get_db] = lambda: db_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            with patch.object(settings, "RATE_LIMIT_USER_PROFILE_LIMIT", 2):
                # Request 1: Attacker sends spoofed CF-Connecting-IP: 1.1.1.1 and arbitrary XFF
                headers_1 = {
                    "x-real-ip": attacker_peer_ip,
                    "x-forwarded-for": "104.16.1.1, 5.5.5.5",
                    "cf-connecting-ip": "1.1.1.1",
                }
                r1 = await ac.get("/api/v1/users/999999", headers=headers_1)
                assert r1.status_code != 429

                # Request 2: Attacker sends different spoofed CF-Connecting-IP: 2.2.2.2
                headers_2 = {
                    "x-real-ip": attacker_peer_ip,
                    "x-forwarded-for": "172.64.0.1, 9.9.9.9",
                    "cf-connecting-ip": "2.2.2.2",
                }
                r2 = await ac.get("/api/v1/users/999999", headers=headers_2)
                assert r2.status_code != 429

                # Request 3: Attacker sends third spoofed CF-Connecting-IP: 3.3.3.3
                headers_3 = {
                    "x-real-ip": attacker_peer_ip,
                    "x-forwarded-for": "1.2.3.4",
                    "cf-connecting-ip": "3.3.3.3",
                }
                r3 = await ac.get("/api/v1/users/999999", headers=headers_3)

                # MUST BE BLOCKED (429) despite changing CF-Connecting-IP and sending arbitrary XFF!
                assert r3.status_code == 429, (
                    "Attacker bypassed rate limiter by spoofing CF-Connecting-IP!"
                )
                assert r3.json() == {"detail": "Too many requests. Please try again later."}
    finally:
        app.dependency_overrides.clear()
        await client.delete(key)


def make_mock_request(
    headers: dict[str, str],
    client_host: str = "127.0.0.1",
    client_port: int = 12345,
) -> Request:
    """Helper to construct a Starlette Request with specific headers and client address."""
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in headers.items()
    ]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/users/1",
        "headers": raw_headers,
        "client": (client_host, client_port) if client_host else None,
    }
    return Request(scope)


def test_client_ip_cloudflare_x_real_ip_with_valid_cf_connecting_ip():
    """
    Required Case 1: Cloudflare X-Real-IP + valid CF-Connecting-IP -> returns visitor IP.
    Railway identifies remote peer as Cloudflare (e.g. 173.245.48.50).
    CF-Connecting-IP is authenticated and returned as the visitor IP.
    """
    req = make_mock_request({
        "x-real-ip": "173.245.48.50",
        "cf-connecting-ip": "203.0.113.195",
    })
    assert extract_client_ip(req) == "203.0.113.195"


def test_client_ip_non_cloudflare_x_real_ip_with_forged_cf_connecting_ip():
    """
    Required Case 2: Non-Cloudflare X-Real-IP + forged CF-Connecting-IP -> returns X-Real-IP.
    Railway identifies peer as non-Cloudflare (e.g. 198.51.100.22).
    CF-Connecting-IP is discarded regardless of value; X-Real-IP is used as quota identity.
    """
    req = make_mock_request({
        "x-real-ip": "198.51.100.22",
        "cf-connecting-ip": "1.1.1.1",
    })
    assert extract_client_ip(req) == "198.51.100.22"


def test_client_ip_direct_origin_with_arbitrary_x_forwarded_for():
    """
    Required Case 3: Direct origin + arbitrary X-Forwarded-For -> cannot bypass quota identity.
    Caller provides forged X-Forwarded-For (even containing Cloudflare IPs) and forged CF-Connecting-IP.
    Because Railway-observed X-Real-IP is NOT Cloudflare, caller identity is bound to X-Real-IP.
    """
    req = make_mock_request({
        "x-real-ip": "198.51.100.77",
        "x-forwarded-for": "104.16.1.1, 172.64.0.1, 8.8.8.8",
        "cf-connecting-ip": "1.1.1.1",
    })
    assert extract_client_ip(req) == "198.51.100.77"


def test_client_ip_missing_x_real_ip_with_forged_cf_connecting_ip():
    """
    Required Case 4: Missing X-Real-IP + forged CF-Connecting-IP -> CF header ignored.
    Without a verified Cloudflare peer in X-Real-IP, CF-Connecting-IP MUST NOT be trusted.
    Falls back to request.client.host.
    """
    req = make_mock_request(
        {"cf-connecting-ip": "8.8.8.8"},
        client_host="192.0.2.1",
    )
    assert extract_client_ip(req) == "192.0.2.1"


def test_client_ip_malformed_x_real_ip():
    """
    Required Case 5: Malformed X-Real-IP -> safe fallback.
    Headers with invalid/garbage text in X-Real-IP must not crash and must not trust CF-Connecting-IP.
    """
    req = make_mock_request(
        {
            "x-real-ip": "not-an-ip-address",
            "cf-connecting-ip": "8.8.8.8",
        },
        client_host="192.0.2.99",
    )
    assert extract_client_ip(req) == "192.0.2.99"


def test_client_ip_ipv4_cloudflare():
    """
    Required Case 6: IPv4 Cloudflare peer + visitor IP.
    Validates official Cloudflare IPv4 CIDRs (e.g. 172.64.1.1 in 172.64.0.0/13).
    """
    req = make_mock_request({
        "x-real-ip": "172.64.1.1",
        "cf-connecting-ip": "203.0.113.10",
    })
    assert extract_client_ip(req) == "203.0.113.10"


def test_client_ip_ipv6_cloudflare():
    """
    Required Case 7: IPv6 Cloudflare peer.
    Validates official Cloudflare IPv6 CIDRs (e.g. 2400:cb00::1 and 2606:4700::1)
    with both IPv6 and IPv4 visitor addresses.
    """
    # 7A. IPv6 Cloudflare peer + IPv6 visitor
    req_ipv6 = make_mock_request({
        "x-real-ip": "2400:cb00:100::1",
        "cf-connecting-ip": "2001:db8:85a3::8a2e:370:7334",
    })
    assert extract_client_ip(req_ipv6) == "2001:db8:85a3::8a2e:370:7334"

    # 7B. IPv6 Cloudflare peer + IPv4 visitor
    req_ipv4_visitor = make_mock_request({
        "x-real-ip": "2606:4700:50::1",
        "cf-connecting-ip": "203.0.113.44",
    })
    assert extract_client_ip(req_ipv4_visitor) == "203.0.113.44"


def test_client_ip_missing_proxy_headers():
    """
    Missing proxy headers (local dev / test environments).
    Must fall back to request.client.host without collapsing distinct test clients.
    """
    # Local loopback
    req_local = make_mock_request({}, client_host="127.0.0.1")
    assert extract_client_ip(req_local) == "127.0.0.1"

    # Test client
    req_testclient = make_mock_request({}, client_host="testclient")
    assert extract_client_ip(req_testclient) == "testclient"

    # Unknown client when client is None
    req_none = make_mock_request({}, client_host="")
    assert extract_client_ip(req_none) == "unknown"


@pytest.mark.asyncio
async def test_emergency_flood_ceiling_allows_campus_nat_volume(db_session):
    """
    Blocker 2: Global Campus NAT Quota Hardening
    Validates that the emergency flood ceiling is generous (3,000 req/60s) so that
    multiple students on a shared campus Wi-Fi NAT gateway can perform requests without
    being throttled by an overly restrictive global IP ceiling.
    """
    client = await get_or_reconnect_redis()
    campus_ip = "203.0.113.150"
    emergency_key = f"rl:emergency_flood:ip:{campus_ip}"
    await client.delete(emergency_key)

    app.dependency_overrides[get_db] = lambda: db_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            # Simulate 10 requests from the same campus NAT IP to a static/health/meta endpoint
            headers = {"x-real-ip": campus_ip}
            for _ in range(10):
                r = await ac.get("/api/v1/categories", headers=headers)
                assert r.status_code == 200

            # Verify that emergency flood counter reflects the requests but does not block
            count = await client.get(emergency_key)
            assert count is not None
            assert int(count) == 10
            assert int(count) < settings.RATE_LIMIT_GLOBAL_IP_LIMIT
    finally:
        app.dependency_overrides.clear()
        await client.delete(emergency_key)


