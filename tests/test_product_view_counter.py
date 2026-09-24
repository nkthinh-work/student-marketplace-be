import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch
import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.redis import init_redis, close_redis, get_redis_client
import app.core.redis as redis_core
from app.modules.categories.models import Category
from app.modules.products.models import Product, ProductStatus, ProductModerationStatus
from app.modules.products.view_counter import (
    register_view_in_redis,
    get_effective_view_count_from_redis,
    get_effective_view_counts_batch,
    get_dirty_product_views,
    acknowledge_dirty_product_view,
    run_product_views_flush,
    get_product_view_count_key,
    get_product_view_dedupe_key,
    DIRTY_SET_KEY,
    GLOBAL_SEQUENCE_KEY,
)
from app.modules.users.models import User, UserStatus, UserRole, UserAuthIdentity
from app.modules.users.capability_models import UserCapabilityRestriction, CapabilityType


@pytest_asyncio.fixture
async def view_data(db_session: AsyncSession):
    # 1. Seller
    seller = User(
        email="seller_vc@ptit.edu.vn",
        full_name="Seller VC",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    # 2. Student A (Viewer 1)
    student_a = User(
        email="student_a_vc@ptit.edu.vn",
        full_name="Student A",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    # 3. Student B (Viewer 2)
    student_b = User(
        email="student_b_vc@ptit.edu.vn",
        full_name="Student B",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    # 4. Admin
    admin_user = User(
        email="admin_vc@ptit.edu.vn",
        full_name="Admin VC",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add_all([seller, student_a, student_b, admin_user])
    await db_session.flush()

    db_session.add_all([
        UserAuthIdentity(user_id=seller.user_id, provider="FIREBASE", provider_uid="fb_seller_vc"),
        UserAuthIdentity(user_id=student_a.user_id, provider="FIREBASE", provider_uid="fb_student_a_vc"),
        UserAuthIdentity(user_id=student_b.user_id, provider="FIREBASE", provider_uid="fb_student_b_vc"),
        UserAuthIdentity(user_id=admin_user.user_id, provider="FIREBASE", provider_uid="fb_admin_vc"),
    ])
    await db_session.flush()

    category = Category(name="Sách Giáo Trình VC", slug="sach-gt-vc", is_deleted=False)
    db_session.add(category)
    await db_session.flush()

    # Normal public available product
    product = Product(
        seller_id=seller.user_id,
        category_id=category.category_id,
        title="Giáo trình Cấu trúc dữ liệu & Giải thuật",
        description="Sách dùng cho sinh viên năm 2",
        listing_type="FIXED_PRICE",
        price=50000,
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        moderation_status=ProductModerationStatus.CLEAR.value,
        view_count=10,
        is_deleted=False,
    )
    # Hidden product
    p_hidden = Product(
        seller_id=seller.user_id,
        category_id=category.category_id,
        title="Sản phẩm ẩn",
        listing_type="FIXED_PRICE",
        price=10000,
        stock=1,
        status=ProductStatus.HIDDEN.value,
        moderation_status=ProductModerationStatus.CLEAR.value,
        view_count=0,
        is_deleted=False,
    )
    # Blocked product
    p_blocked = Product(
        seller_id=seller.user_id,
        category_id=category.category_id,
        title="Sản phẩm vi phạm",
        listing_type="FIXED_PRICE",
        price=10000,
        stock=1,
        status=ProductStatus.AVAILABLE.value,
        moderation_status=ProductModerationStatus.BLOCKED.value,
        view_count=0,
        is_deleted=False,
    )
    # Soft-deleted product
    p_deleted = Product(
        seller_id=seller.user_id,
        category_id=category.category_id,
        title="Sản phẩm đã xóa",
        listing_type="FIXED_PRICE",
        price=10000,
        stock=1,
        status=ProductStatus.AVAILABLE.value,
        moderation_status=ProductModerationStatus.CLEAR.value,
        view_count=0,
        is_deleted=True,
    )
    db_session.add_all([product, p_hidden, p_blocked, p_deleted])
    await db_session.flush()

    return {
        "seller": seller,
        "student_a": student_a,
        "student_b": student_b,
        "admin": admin_user,
        "category": category,
        "product": product,
        "p_hidden": p_hidden,
        "p_blocked": p_blocked,
        "p_deleted": p_deleted,
    }


@pytest_asyncio.fixture(autouse=True)
async def clean_redis():
    """Ensure Redis is connected and clean before and after each test."""
    client = await init_redis()
    if client is not None:
        try:
            async for k in client.scan_iter("product:views:*"):
                await client.delete(k)
        except Exception:
            pass
    yield client
    if client is not None:
        try:
            async for k in client.scan_iter("product:views:*"):
                await client.delete(k)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 1. Focused View Semantics & Deduplication Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_view_and_24h_deduplication(test_client: AsyncClient, view_data, db_session: AsyncSession):
    """
    Requirements 62 & 63:
    Student A views Product owned by Student B.
    DB count: 10. No Redis count initially.
    First view: counted = True, view_count = 11.
    Duplicate within 24h: counted = False, view_count = 11.
    DB remains 10 until worker flush.
    """
    prod = view_data["product"]
    student_a = view_data["student_a"]

    with patch("app.modules.products.router.verify_firebase_token", return_value={"uid": "fb_student_a_vc"}):
        # 1. First View
        res1 = await test_client.post(
            f"/api/v1/products/{prod.product_id}/view",
            headers={"Authorization": "Bearer mock_token_a"},
        )
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["counted"] is True
        assert data1["view_count"] == 11

        # Confirm DB still has initial durable count (10)
        await db_session.refresh(prod)
        assert prod.view_count == 10

        # 2. Duplicate View (same user within 24h)
        res2 = await test_client.post(
            f"/api/v1/products/{prod.product_id}/view",
            headers={"Authorization": "Bearer mock_token_a"},
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["counted"] is False
        assert data2["view_count"] == 11


@pytest.mark.asyncio
async def test_dedupe_expiry_allows_new_count(test_client: AsyncClient, view_data, clean_redis):
    """
    Requirement 64:
    After dedupe TTL expires, the same logical viewer counts again (+1).
    """
    prod = view_data["product"]
    student_a = view_data["student_a"]

    with patch("app.modules.products.router.verify_firebase_token", return_value={"uid": "fb_student_a_vc"}):
        res1 = await test_client.post(
            f"/api/v1/products/{prod.product_id}/view",
            headers={"Authorization": "Bearer mock_token_a"},
        )
        assert res1.json()["view_count"] == 11
        assert res1.json()["counted"] is True

        # Manually expire/delete the dedupe key in Redis to simulate TTL expiry
        if clean_redis:
            dedupe_key = get_product_view_dedupe_key(prod.product_id, f"u:{student_a.user_id}")
            await clean_redis.delete(dedupe_key)

        res2 = await test_client.post(
            f"/api/v1/products/{prod.product_id}/view",
            headers={"Authorization": "Bearer mock_token_a"},
        )
        assert res2.json()["view_count"] == 12
        assert res2.json()["counted"] is True


@pytest.mark.asyncio
async def test_different_viewers_increment_independently(test_client: AsyncClient, view_data):
    """
    Requirement 65:
    Student A (+1), Student B (+1), Anonymous UUID X (+1) -> Aggregate increases by 3.
    """
    prod = view_data["product"]
    anon_id = str(uuid.uuid4())

    # 1. Student A
    with patch("app.modules.products.router.verify_firebase_token", return_value={"uid": "fb_student_a_vc"}):
        r1 = await test_client.post(
            f"/api/v1/products/{prod.product_id}/view",
            headers={"Authorization": "Bearer token_a"},
        )
        assert r1.json()["view_count"] == 11
        assert r1.json()["counted"] is True

    # 2. Student B
    with patch("app.modules.products.router.verify_firebase_token", return_value={"uid": "fb_student_b_vc"}):
        r2 = await test_client.post(
            f"/api/v1/products/{prod.product_id}/view",
            headers={"Authorization": "Bearer token_b"},
        )
        assert r2.json()["view_count"] == 12
        assert r2.json()["counted"] is True

    # 3. Anonymous Viewer
    r3 = await test_client.post(
        f"/api/v1/products/{prod.product_id}/view",
        json={"anonymous_viewer_id": anon_id},
    )
    assert r3.json()["view_count"] == 13
    assert r3.json()["counted"] is True


@pytest.mark.asyncio
async def test_seller_self_view_excluded(test_client: AsyncClient, view_data):
    """
    Requirement 66:
    Product seller registers view -> counted = False, view_count unchanged.
    """
    prod = view_data["product"]

    with patch("app.modules.products.router.verify_firebase_token", return_value={"uid": "fb_seller_vc"}):
        res = await test_client.post(
            f"/api/v1/products/{prod.product_id}/view",
            headers={"Authorization": "Bearer seller_token"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["counted"] is False
        assert data["view_count"] == 10


@pytest.mark.asyncio
async def test_admin_view_excluded(test_client: AsyncClient, view_data):
    """
    Requirement 67:
    Admin registers product view -> counted = False, view_count unchanged.
    """
    prod = view_data["product"]

    with patch("app.modules.products.router.verify_firebase_token", return_value={"uid": "fb_admin_vc"}):
        res = await test_client.post(
            f"/api/v1/products/{prod.product_id}/view",
            headers={"Authorization": "Bearer admin_token"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["counted"] is False
        assert data["view_count"] == 10


@pytest.mark.asyncio
async def test_anonymous_viewer_deduplication(test_client: AsyncClient, view_data):
    """
    Requirement 68:
    UUID X: first = true, duplicate = false.
    UUID Y: first = true.
    """
    prod = view_data["product"]
    uuid_x = str(uuid.uuid4())
    uuid_y = str(uuid.uuid4())

    # UUID X first view
    r1 = await test_client.post(
        f"/api/v1/products/{prod.product_id}/view",
        json={"anonymous_viewer_id": uuid_x},
    )
    assert r1.json()["counted"] is True
    assert r1.json()["view_count"] == 11

    # UUID X duplicate view
    r2 = await test_client.post(
        f"/api/v1/products/{prod.product_id}/view",
        json={"anonymous_viewer_id": uuid_x},
    )
    assert r2.json()["counted"] is False
    assert r2.json()["view_count"] == 11

    # UUID Y first view
    r3 = await test_client.post(
        f"/api/v1/products/{prod.product_id}/view",
        json={"anonymous_viewer_id": uuid_y},
    )
    assert r3.json()["counted"] is True
    assert r3.json()["view_count"] == 12


@pytest.mark.asyncio
async def test_invalid_anonymous_id_validation(test_client: AsyncClient, view_data):
    """
    Requirement 69:
    Missing anonymous_id with no auth -> counted = False, returns current count.
    Invalid UUID format -> 422 Unprocessable Entity.
    """
    prod = view_data["product"]

    # 1. No auth and empty body -> counted = False
    r_empty = await test_client.post(
        f"/api/v1/products/{prod.product_id}/view",
        json={},
    )
    assert r_empty.status_code == 200
    assert r_empty.json()["counted"] is False
    assert r_empty.json()["view_count"] == 10

    # 2. Invalid UUID format -> 422
    r_invalid = await test_client.post(
        f"/api/v1/products/{prod.product_id}/view",
        json={"anonymous_viewer_id": "not-a-valid-uuid"},
    )
    assert r_invalid.status_code == 422


# ---------------------------------------------------------------------------
# 2. Concurrency & Atomicity Tests (Real Redis Lua)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_same_viewer_increments_once(view_data, clean_redis):
    """
    Requirement 70:
    10 concurrent view registrations from the SAME viewer for the SAME product.
    Authoritative Lua atomicity ensures exactly ONE increment.
    """
    if not clean_redis:
        pytest.skip("Local Redis not available")

    prod = view_data["product"]
    viewer_token = "u:8888"

    # Clean test keys
    await clean_redis.delete(
        get_product_view_count_key(prod.product_id),
        get_product_view_dedupe_key(prod.product_id, viewer_token),
    )

    # Launch 10 concurrent registrations
    tasks = [
        register_view_in_redis(
            redis=clean_redis,
            product_id=prod.product_id,
            viewer_token=viewer_token,
            db_view_count=10,
            dedupe_ttl=60,
        )
        for _ in range(10)
    ]
    results = await asyncio.gather(*tasks)

    counted_true = [res for res in results if res[1] is True]
    counted_false = [res for res in results if res[1] is False]

    assert len(counted_true) == 1, "Exactly ONE request must be accepted"
    assert len(counted_false) == 9, "All 9 duplicates must be rejected"
    assert counted_true[0][0] == 11
    for cf in counted_false:
        assert cf[0] == 11


@pytest.mark.asyncio
async def test_concurrent_different_viewers(view_data, clean_redis):
    """
    Requirement 71:
    10 concurrent unique viewers register for the same product.
    All 10 must increment without race condition losses.
    """
    if not clean_redis:
        pytest.skip("Local Redis not available")

    prod = view_data["product"]
    p_key = get_product_view_count_key(prod.product_id)
    await clean_redis.delete(p_key)

    tasks = [
        register_view_in_redis(
            redis=clean_redis,
            product_id=prod.product_id,
            viewer_token=f"u:test_{i}",
            db_view_count=10,
            dedupe_ttl=60,
        )
        for i in range(10)
    ]
    results = await asyncio.gather(*tasks)

    for res in results:
        assert res[1] is True, "Every unique viewer must be counted"

    # Final Redis count must be exactly 10 + 10 = 20
    final_count = int(await clean_redis.get(p_key))
    assert final_count == 20


# ---------------------------------------------------------------------------
# 3. DB Floor & Effective Count Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_redis_db_floor(view_data, clean_redis):
    """
    Requirement 72:
    DB = 100, Redis = 90.
    New view arrives -> Redis count becomes max(90, 100) + 1 = 101 (never 91).
    """
    if not clean_redis:
        pytest.skip("Local Redis not available")

    pid = 77777
    p_key = get_product_view_count_key(pid)
    await clean_redis.set(p_key, 90)

    count, counted = await register_view_in_redis(
        redis=clean_redis,
        product_id=pid,
        viewer_token="u:floor_user",
        db_view_count=100,
        dedupe_ttl=60,
    )
    assert counted is True
    assert count == 101
    assert int(await clean_redis.get(p_key)) == 101


@pytest.mark.asyncio
async def test_redis_above_db_duplicate(view_data, clean_redis):
    """
    Requirement 73:
    DB = 100, Redis = 120. Duplicate viewer -> response is 120 (not lowered to 100).
    """
    if not clean_redis:
        pytest.skip("Local Redis not available")

    pid = 66666
    p_key = get_product_view_count_key(pid)
    d_key = get_product_view_dedupe_key(pid, "u:dup_user")
    await clean_redis.set(p_key, 120)
    await clean_redis.set(d_key, "1", ex=60)

    count, counted = await register_view_in_redis(
        redis=clean_redis,
        product_id=pid,
        viewer_token="u:dup_user",
        db_view_count=100,
        dedupe_ttl=60,
    )
    assert counted is False
    assert count == 120


# ---------------------------------------------------------------------------
# 4. Worker Flush & Idempotency Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_worker_flush_normal(view_data, clean_redis, db_session: AsyncSession):
    """
    Requirement 74:
    DB = 10, Redis receives view -> 11, dirty set has entry.
    Worker flush executes -> DB is updated to 11, dirty entry removed.
    """
    if not clean_redis:
        pytest.skip("Local Redis not available")

    prod = view_data["product"]
    # Register view in Redis
    await register_view_in_redis(
        redis=clean_redis,
        product_id=prod.product_id,
        viewer_token="u:worker_test",
        db_view_count=prod.view_count,
    )

    # Confirm dirty set has product
    dirty = await get_dirty_product_views(clean_redis)
    assert any(d[0] == prod.product_id for d in dirty)

    # Execute flush using session factory wrapping current test session
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def bound_session_factory():
        yield db_session

    result = await run_product_views_flush(bound_session_factory)
    assert result.changed >= 1

    # Verify DB updated
    await db_session.refresh(prod)
    assert prod.view_count == 11

    # Verify dirty entry was ACKed and removed
    dirty_after = await get_dirty_product_views(clean_redis)
    assert not any(d[0] == prod.product_id for d in dirty_after)


@pytest.mark.asyncio
async def test_worker_idempotent_replay(view_data, clean_redis, db_session: AsyncSession):
    """
    Requirement 75:
    Replaying flush with same value writes GREATEST(view_count, count).
    Count stays 11 (no double increment).
    """
    if not clean_redis:
        pytest.skip("Local Redis not available")

    prod = view_data["product"]
    prod.view_count = 11
    await db_session.flush()

    # Seed Redis count = 11 and re-add to dirty set
    await clean_redis.set(get_product_view_count_key(prod.product_id), 11)
    await clean_redis.zadd(DIRTY_SET_KEY, {str(prod.product_id): 10})

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def bound_session_factory():
        yield db_session

    res = await run_product_views_flush(bound_session_factory)

    await db_session.refresh(prod)
    assert prod.view_count == 11, "Must remain 11, no double count"


@pytest.mark.asyncio
async def test_new_view_during_flush_retains_dirty(view_data, clean_redis):
    """
    Requirement 77:
    Worker reads count 120, version 50.
    Before ACK, new view arrives -> version 51.
    Worker ACKs with version 50 -> ACK refuses removal -> item remains dirty!
    """
    if not clean_redis:
        pytest.skip("Local Redis not available")

    pid = 55555
    # Simulate dirty at version 50
    await clean_redis.zadd(DIRTY_SET_KEY, {str(pid): 50})

    # A new view arrives, bumping version to 51
    await clean_redis.zadd(DIRTY_SET_KEY, {str(pid): 51})

    # Worker attempts conditional ACK with the older version 50
    acked = await acknowledge_dirty_product_view(clean_redis, pid, expected_version=50)
    assert acked is False, "Must NOT ACK if newer view modified the version"

    # Product must still be in dirty set
    score = await clean_redis.zscore(DIRTY_SET_KEY, str(pid))
    assert score == 51


@pytest.mark.asyncio
async def test_worker_flush_preserves_updated_at(view_data, clean_redis, db_session: AsyncSession):
    """
    Requirement 58 & 59:
    Worker projection of view_count must NOT change products.updated_at.
    """
    if not clean_redis:
        pytest.skip("Local Redis not available")

    prod = view_data["product"]
    orig_updated_at = prod.updated_at

    await clean_redis.set(get_product_view_count_key(prod.product_id), 15)
    await clean_redis.zadd(DIRTY_SET_KEY, {str(prod.product_id): 1})

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def bound_session_factory():
        yield db_session

    await run_product_views_flush(bound_session_factory)

    await db_session.refresh(prod)
    assert prod.view_count == 15
    assert prod.updated_at == orig_updated_at, "updated_at must remain completely identical"


# ---------------------------------------------------------------------------
# 5. Fail-Open & Privacy Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_redis_outage_fail_open(test_client: AsyncClient, view_data):
    """
    Requirement 79:
    If Redis is unavailable:
    - GET product detail works (returns DB count).
    - POST view returns HTTP 200 with DB count and counted=False (does not fail).
    """
    prod = view_data["product"]

    with patch("app.modules.products.service.get_redis_client", return_value=None):
        # 1. GET detail
        get_res = await test_client.get(f"/api/v1/products/{prod.product_id}")
        assert get_res.status_code == 200
        assert get_res.json()["view_count"] == 10

        # 2. POST view
        post_res = await test_client.post(
            f"/api/v1/products/{prod.product_id}/view",
            json={"anonymous_viewer_id": str(uuid.uuid4())},
        )
        assert post_res.status_code == 200
        assert post_res.json()["counted"] is False
        assert post_res.json()["view_count"] == 10


@pytest.mark.asyncio
async def test_product_visibility_privacy(test_client: AsyncClient, view_data):
    """
    Requirement 81:
    Hidden, Blocked, and Deleted products return 404 for unauthorized callers.
    Zero existence leak.
    """
    p_hidden = view_data["p_hidden"]
    p_blocked = view_data["p_blocked"]
    p_deleted = view_data["p_deleted"]
    anon_id = str(uuid.uuid4())

    # Hidden product: anonymous caller gets 404
    r_hidden = await test_client.post(
        f"/api/v1/products/{p_hidden.product_id}/view",
        json={"anonymous_viewer_id": anon_id},
    )
    assert r_hidden.status_code == 404

    # Blocked product: anonymous caller gets 404
    r_blocked = await test_client.post(
        f"/api/v1/products/{p_blocked.product_id}/view",
        json={"anonymous_viewer_id": anon_id},
    )
    assert r_blocked.status_code == 404

    # Deleted product: anonymous caller gets 404
    r_deleted = await test_client.post(
        f"/api/v1/products/{p_deleted.product_id}/view",
        json={"anonymous_viewer_id": anon_id},
    )
    assert r_deleted.status_code == 404


@pytest.mark.asyncio
async def test_worker_redis_failure():
    """
    Requirement 80:
    When Redis fails during worker sweep, run_product_views_flush returns
    SweepResult without crashing the worker or throwing uncaught exceptions.
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def dummy_factory():
        yield None

    with patch("app.modules.products.view_counter.get_redis_client", return_value=None):
        result = await run_product_views_flush(dummy_factory)
        assert result.changed == 0
        assert result.failed == 0


@pytest.mark.asyncio
async def test_multi_worker_concurrent_flush(view_data, clean_redis, db_session: AsyncSession):
    """
    Requirement 78:
    Multiple workers concurrently flush the same dirty product.
    Absolute monotonic GREATEST SQL prevents duplicate/lost increments and causes zero exceptions.
    """
    if not clean_redis:
        pytest.skip("Local Redis not available")

    prod = view_data["product"]
    await clean_redis.set(get_product_view_count_key(prod.product_id), 25)
    await clean_redis.zadd(DIRTY_SET_KEY, {str(prod.product_id): 100})

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def bound_session_factory():
        yield db_session

    res1, res2 = await asyncio.gather(
        run_product_views_flush(bound_session_factory),
        run_product_views_flush(bound_session_factory),
    )

    await db_session.refresh(prod)
    assert prod.view_count == 25


# =====================================================================
# Phase 9B Corrections & Edge Case Tests
# =====================================================================

@pytest.mark.asyncio
async def test_batch_redis_helper_empty_list():
    """
    Correction 3:
    When db_counts is empty: returns {} and makes ZERO Redis MGET calls.
    """
    from unittest.mock import AsyncMock, MagicMock
    mock_redis = MagicMock()
    mock_redis.mget = AsyncMock()

    res = await get_effective_view_counts_batch(mock_redis, {})
    assert res == {}
    assert mock_redis.mget.call_count == 0


@pytest.mark.asyncio
async def test_batch_redis_helper_redis_unavailable():
    """
    Correction 3:
    When Redis client is None / unavailable: returns a copy of DB counts.
    """
    db_counts = {101: 15, 102: 42}
    res = await get_effective_view_counts_batch(None, db_counts)
    assert res == {101: 15, 102: 42}
    assert res is not db_counts  # must be a copy


@pytest.mark.asyncio
async def test_batch_redis_helper_single_mget_non_empty():
    """
    Correction 3:
    For a non-empty list of N items: executes exactly ONE batched MGET call.
    """
    from unittest.mock import AsyncMock, MagicMock
    mock_redis = MagicMock()
    mock_redis.mget = AsyncMock(return_value=[b"25", b"42", b"100"])

    db_counts = {10: 5, 20: 30, 30: 80}
    res = await get_effective_view_counts_batch(mock_redis, db_counts)

    assert mock_redis.mget.call_count == 1
    mock_redis.mget.assert_called_once_with(
        "product:views:count:10",
        "product:views:count:20",
        "product:views:count:30",
    )
    assert res == {10: 25, 20: 42, 30: 100}


@pytest.mark.asyncio
async def test_batch_redis_helper_infrastructure_failure_fails_open():
    """
    Correction 3:
    On Redis infrastructure failure: fails open and returns copy of DB counts.
    """
    from unittest.mock import AsyncMock, MagicMock
    mock_redis = MagicMock()
    mock_redis.mget = AsyncMock(side_effect=ConnectionError("Redis cluster unreachable"))

    db_counts = {1: 10, 2: 20}
    res = await get_effective_view_counts_batch(mock_redis, db_counts)
    assert res == {1: 10, 2: 20}


@pytest.mark.asyncio
async def test_batch_redis_helper_defensive_parsing_and_stale_floor():
    """
    Correction 3:
    Defensively parses each Redis value:
    - Missing individual counter (None) -> falls back to DB floor
    - Malformed counter (non-integer) -> falls back to DB floor
    - Stale Redis counter below DB -> DB floor wins
    - Redis count above DB -> Redis count wins
    """
    from unittest.mock import AsyncMock, MagicMock
    mock_redis = MagicMock()
    # 5 items:
    # 1: None (missing in Redis) -> DB floor 10
    # 2: b"corrupted" (malformed) -> DB floor 20
    # 3: b"4" (stale, below DB 12) -> DB floor 12 wins
    # 4: b"55" (valid higher) -> 55 wins
    # 5: b"-1" (negative) -> DB floor 0 wins
    mock_redis.mget = AsyncMock(return_value=[None, b"corrupted", b"4", b"55", b"-1"])

    db_counts = {1: 10, 2: 20, 3: 12, 4: 15, 5: 0}
    res = await get_effective_view_counts_batch(mock_redis, db_counts)

    assert res[1] == 10
    assert res[2] == 20
    assert res[3] == 12
    assert res[4] == 55
    assert res[5] == 0


@pytest.mark.asyncio
async def test_seller_manage_listings_serializes_explicit_view_count(
    test_client: AsyncClient,
    view_data: dict,
    clean_redis,
    db_session: AsyncSession,
):
    """
    Correction 1 & 4:
    GET /api/v1/products/me explicitly serializes view_count for each SellerProductResponse
    and reflects effective batch Redis view counts.
    """
    seller = view_data["seller"]
    prod = view_data["product"]

    # Set higher view count in Redis
    if clean_redis:
        await clean_redis.set(get_product_view_count_key(prod.product_id), 99)

    headers = {"Authorization": "Bearer fb_seller_vc"}
    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value={"uid": "fb_seller_vc", "email": seller.email}):
        res = await test_client.get("/api/v1/products/me", headers=headers)

    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert len(data["items"]) >= 1

    item = next(i for i in data["items"] if i["product_id"] == prod.product_id)
    assert "view_count" in item
    assert isinstance(item["view_count"], int)
    if clean_redis:
        assert item["view_count"] == 99
    else:
        assert item["view_count"] == prod.view_count


@pytest.mark.asyncio
async def test_public_listings_serializes_explicit_view_count(
    test_client: AsyncClient,
    view_data: dict,
    clean_redis,
):
    """
    Correction 4 & 5:
    GET /api/v1/products serializes required view_count in ProductSummaryResponse
    using batch Redis counts.
    """
    prod = view_data["product"]
    if clean_redis:
        await clean_redis.set(get_product_view_count_key(prod.product_id), 88)

    res = await test_client.get("/api/v1/products")
    assert res.status_code == 200
    data = res.json()
    items = data["items"]
    assert len(items) >= 1

    item = next(i for i in items if i["product_id"] == prod.product_id)
    assert "view_count" in item
    assert isinstance(item["view_count"], int)
    if clean_redis:
        assert item["view_count"] == 88
    else:
        assert item["view_count"] == prod.view_count
