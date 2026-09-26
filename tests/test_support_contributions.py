import uuid
from datetime import datetime, timezone, timedelta
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.auth.dependencies import get_current_active_user, require_admin
from app.modules.feedback.models import SupportContribution
from app.modules.users.models import User, UserRole, UserStatus


@pytest_asyncio.fixture
async def support_test_users(db_session: AsyncSession):
    student1 = User(
        email=f"supporter1_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Nguyễn Văn Sinh Viên Một",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    student2 = User(
        email=f"supporter2_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Trần Thị Sinh Viên Hai",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    student3 = User(
        email=f"supporter3_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Lê Văn Sinh Viên Ba",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    banned_student = User(
        email=f"supporter_banned_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Sinh Viên Bị Khóa",
        role=UserRole.STUDENT.value,
        status=UserStatus.BANNED,
    )
    admin = User(
        email=f"support_admin_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Quản Trị Viên Hỗ Trợ",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add_all([student1, student2, student3, banned_student, admin])
    await db_session.flush()
    return {
        "student1": student1,
        "student2": student2,
        "student3": student3,
        "banned": banned_student,
        "admin": admin,
    }


def override_user(user: User):
    class OverrideContext:
        def __enter__(self):
            app.dependency_overrides[get_current_active_user] = lambda: user
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            app.dependency_overrides.pop(get_current_active_user, None)

    return OverrideContext()


def override_admin(admin: User):
    class OverrideAdminContext:
        def __enter__(self):
            app.dependency_overrides[require_admin] = lambda: admin
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            app.dependency_overrides.pop(require_admin, None)

    return OverrideAdminContext()


# ======================================================================
# 1. ADMIN AUTHORIZATION & CREATE TESTS
# ======================================================================

@pytest.mark.asyncio
async def test_admin_create_support_contribution_unauthenticated(test_client: AsyncClient, support_test_users: dict):
    student = support_test_users["student1"]
    res = await test_client.post(
        "/api/v1/admin/support-contributions",
        json={
            "supporter_id": student.user_id,
            "amount_vnd": 100000,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "is_public": False,
        },
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_student_cannot_create_support_contribution(test_client: AsyncClient, support_test_users: dict):
    student = support_test_users["student1"]
    with override_user(student):
        res = await test_client.post(
            "/api/v1/admin/support-contributions",
            json={
                "supporter_id": student.user_id,
                "amount_vnd": 100000,
                "received_at": datetime.now(timezone.utc).isoformat(),
                "is_public": False,
            },
        )
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_admin_create_support_contribution_success(test_client: AsyncClient, support_test_users: dict):
    student = support_test_users["student1"]
    admin = support_test_users["admin"]
    received_time = datetime.now(timezone.utc)

    with override_admin(admin):
        res = await test_client.post(
            "/api/v1/admin/support-contributions",
            json={
                "supporter_id": student.user_id,
                "amount_vnd": 250000,
                "received_at": received_time.isoformat(),
                "is_public": False,
                "transaction_ref": " FT240924123456 ",
                "admin_note": "Ủng hộ server Chợ PTITers",
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert data["contribution_id"] > 0
        assert data["supporter"]["user_id"] == student.user_id
        assert data["supporter"]["full_name"] == student.full_name
        assert data["amount_vnd"] == 250000
        assert data["is_public"] is False
        assert data["transaction_ref"] == "FT240924123456"  # Trimmed
        assert data["admin_note"] == "Ủng hộ server Chợ PTITers"
        # Server trích xuất recorded_by từ admin hiện tại
        assert data["recorded_by"]["user_id"] == admin.user_id
        assert data["recorded_by"]["full_name"] == admin.full_name


@pytest.mark.asyncio
async def test_admin_create_invalid_amount_rejected(test_client: AsyncClient, support_test_users: dict):
    student = support_test_users["student1"]
    admin = support_test_users["admin"]

    with override_admin(admin):
        # Amount = 0
        res0 = await test_client.post(
            "/api/v1/admin/support-contributions",
            json={
                "supporter_id": student.user_id,
                "amount_vnd": 0,
                "received_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        assert res0.status_code == 422

        # Negative amount
        res_neg = await test_client.post(
            "/api/v1/admin/support-contributions",
            json={
                "supporter_id": student.user_id,
                "amount_vnd": -50000,
                "received_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        assert res_neg.status_code == 422


@pytest.mark.asyncio
async def test_admin_create_unknown_supporter_rejected(test_client: AsyncClient, support_test_users: dict):
    admin = support_test_users["admin"]

    with override_admin(admin):
        res = await test_client.post(
            "/api/v1/admin/support-contributions",
            json={
                "supporter_id": 999999999,
                "amount_vnd": 100000,
                "received_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        assert res.status_code == 404
        assert "Không tìm thấy người dùng ủng hộ" in res.json()["detail"]


# ======================================================================
# 2. ADMIN LIST, VISIBILITY, DELETE TESTS
# ======================================================================

@pytest.mark.asyncio
async def test_admin_list_support_contributions_and_keyset(test_client: AsyncClient, support_test_users: dict):
    student1 = support_test_users["student1"]
    admin = support_test_users["admin"]

    with override_admin(admin):
        # Create 3 records
        now = datetime.now(timezone.utc)
        for i in range(3):
            await test_client.post(
                "/api/v1/admin/support-contributions",
                json={
                    "supporter_id": student1.user_id,
                    "amount_vnd": (i + 1) * 50000,
                    "received_at": (now - timedelta(hours=i)).isoformat(),
                    "is_public": False,
                },
            )

        # List with limit=2
        res = await test_client.get("/api/v1/admin/support-contributions?limit=2")
        assert res.status_code == 200
        data = res.json()
        assert len(data["items"]) == 2
        assert data["has_more"] is True
        assert data["next_cursor"] is not None

        # Fetch next page
        next_res = await test_client.get(f"/api/v1/admin/support-contributions?limit=2&cursor={data['next_cursor']}")
        assert next_res.status_code == 200
        next_data = next_res.json()
        assert len(next_data["items"]) >= 1


@pytest.mark.asyncio
async def test_admin_toggle_visibility(test_client: AsyncClient, support_test_users: dict):
    student = support_test_users["student1"]
    admin = support_test_users["admin"]

    with override_admin(admin):
        create_res = await test_client.post(
            "/api/v1/admin/support-contributions",
            json={
                "supporter_id": student.user_id,
                "amount_vnd": 150000,
                "received_at": datetime.now(timezone.utc).isoformat(),
                "is_public": False,
            },
        )
        cid = create_res.json()["contribution_id"]
        assert create_res.json()["is_public"] is False

        # Switch to public
        patch_res = await test_client.patch(
            f"/api/v1/admin/support-contributions/{cid}/visibility",
            json={"is_public": True},
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["is_public"] is True

        # Switch back to private
        patch_res2 = await test_client.patch(
            f"/api/v1/admin/support-contributions/{cid}/visibility",
            json={"is_public": False},
        )
        assert patch_res2.status_code == 200
        assert patch_res2.json()["is_public"] is False


@pytest.mark.asyncio
async def test_admin_delete_support_contribution(test_client: AsyncClient, support_test_users: dict):
    student = support_test_users["student1"]
    admin = support_test_users["admin"]

    with override_admin(admin):
        create_res = await test_client.post(
            "/api/v1/admin/support-contributions",
            json={
                "supporter_id": student.user_id,
                "amount_vnd": 80000,
                "received_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        cid = create_res.json()["contribution_id"]

        # Delete record
        del_res = await test_client.delete(f"/api/v1/admin/support-contributions/{cid}")
        assert del_res.status_code == 204

        # Delete again -> 404
        del_again = await test_client.delete(f"/api/v1/admin/support-contributions/{cid}")
        assert del_again.status_code == 404


# ======================================================================
# 3. PUBLIC LEADERBOARD TESTS (AGGREGATION, ORDERING, PRIVACY)
# ======================================================================

@pytest.mark.asyncio
async def test_public_leaderboard_auth_free_and_empty(test_client: AsyncClient, db_session: AsyncSession):
    # Ensure all existing public contributions are cleared or checked
    res = await test_client.get("/api/v1/feedback/support/leaderboard")
    assert res.status_code == 200
    assert "items" in res.json()
    assert isinstance(res.json()["items"], list)


@pytest.mark.asyncio
async def test_public_leaderboard_privacy_and_aggregation(test_client: AsyncClient, support_test_users: dict):
    student1 = support_test_users["student1"]
    student2 = support_test_users["student2"]
    student3 = support_test_users["student3"]
    banned = support_test_users["banned"]
    admin = support_test_users["admin"]

    t0 = datetime.now(timezone.utc) - timedelta(days=2)
    t1 = datetime.now(timezone.utc) - timedelta(days=1)
    t2 = datetime.now(timezone.utc)

    with override_admin(admin):
        # student1: 100k public, 500k private -> public total MUST be 100k
        await test_client.post(
            "/api/v1/admin/support-contributions",
            json={
                "supporter_id": student1.user_id,
                "amount_vnd": 100000,
                "received_at": t0.isoformat(),
                "is_public": True,
                "transaction_ref": "TX100K",
                "admin_note": "Secret Note 1",
            },
        )
        await test_client.post(
            "/api/v1/admin/support-contributions",
            json={
                "supporter_id": student1.user_id,
                "amount_vnd": 500000,
                "received_at": t1.isoformat(),
                "is_public": False,  # PRIVATE
                "transaction_ref": "TX500K_PRIVATE",
                "admin_note": "Secret Private 500k",
            },
        )

        # student2: 2 public contributions: 120k + 80k = 200k
        await test_client.post(
            "/api/v1/admin/support-contributions",
            json={
                "supporter_id": student2.user_id,
                "amount_vnd": 120000,
                "received_at": t1.isoformat(),
                "is_public": True,
            },
        )
        await test_client.post(
            "/api/v1/admin/support-contributions",
            json={
                "supporter_id": student2.user_id,
                "amount_vnd": 80000,
                "received_at": t2.isoformat(),
                "is_public": True,
            },
        )

        # student3: ONLY private contribution (300k) -> MUST NOT appear on leaderboard
        await test_client.post(
            "/api/v1/admin/support-contributions",
            json={
                "supporter_id": student3.user_id,
                "amount_vnd": 300000,
                "received_at": t2.isoformat(),
                "is_public": False,
            },
        )

        # banned: 1,000,000k public -> BANNED user must not appear
        await test_client.post(
            "/api/v1/admin/support-contributions",
            json={
                "supporter_id": banned.user_id,
                "amount_vnd": 1000000,
                "received_at": t2.isoformat(),
                "is_public": True,
            },
        )

    # Public request (no auth)
    res = await test_client.get("/api/v1/feedback/support/leaderboard")
    assert res.status_code == 200
    items = res.json()["items"]

    # Filter to our test students
    test_uids = {student1.user_id, student2.user_id, student3.user_id, banned.user_id}
    matched = [it for it in items if it["supporter"]["user_id"] in test_uids]

    # student3 and banned MUST NOT be present
    matched_uids = [it["supporter"]["user_id"] for it in matched]
    assert student3.user_id not in matched_uids
    assert banned.user_id not in matched_uids

    # student2 (200k) should rank higher than student1 (100k)
    s2_row = next(it for it in matched if it["supporter"]["user_id"] == student2.user_id)
    s1_row = next(it for it in matched if it["supporter"]["user_id"] == student1.user_id)

    assert s2_row["total_amount_vnd"] == 200000
    assert s2_row["contribution_count"] == 2

    assert s1_row["total_amount_vnd"] == 100000  # NOT 600k! Private 500k is excluded!
    assert s1_row["contribution_count"] == 1

    # Check rank order
    assert s2_row["rank"] < s1_row["rank"]

    # Verify no private leaks in response items
    for item in items:
        assert "transaction_ref" not in item
        assert "admin_note" not in item
        assert "recorded_by" not in item
        supporter = item["supporter"]
        assert "email" not in supporter
        assert "phone" not in supporter
        assert "bank" not in supporter
        assert "status" not in supporter
        assert supporter["profile_path"] == f"/users/{supporter['user_id']}"


@pytest.mark.asyncio
async def test_public_leaderboard_max_10_limit(test_client: AsyncClient, db_session: AsyncSession):
    # Ensure limit does not exceed 10
    res = await test_client.get("/api/v1/feedback/support/leaderboard")
    assert res.status_code == 200
    assert len(res.json()["items"]) <= 10


@pytest.mark.asyncio
async def test_public_leaderboard_tie_breaking_deterministic(test_client: AsyncClient, support_test_users: dict):
    student1 = support_test_users["student1"]
    student2 = support_test_users["student2"]
    admin = support_test_users["admin"]

    # Both students get exactly 500,000 VND
    # student1 gets earlier timestamp, student2 gets later timestamp
    earlier_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    later_time = datetime(2026, 1, 2, 10, 0, 0, tzinfo=timezone.utc)

    with override_admin(admin):
        # student2: 500k at later_time
        await test_client.post(
            "/api/v1/admin/support-contributions",
            json={
                "supporter_id": student2.user_id,
                "amount_vnd": 500000,
                "received_at": later_time.isoformat(),
                "is_public": True,
            },
        )
        # student1: 500k at earlier_time
        await test_client.post(
            "/api/v1/admin/support-contributions",
            json={
                "supporter_id": student1.user_id,
                "amount_vnd": 500000,
                "received_at": earlier_time.isoformat(),
                "is_public": True,
            },
        )

    res = await test_client.get("/api/v1/feedback/support/leaderboard")
    assert res.status_code == 200
    items = res.json()["items"]

    s1_row = next(it for it in items if it["supporter"]["user_id"] == student1.user_id)
    s2_row = next(it for it in items if it["supporter"]["user_id"] == student2.user_id)

    assert s1_row["total_amount_vnd"] == s2_row["total_amount_vnd"]
    # student1 has earlier last_supported_at, so student1 ranks higher (smaller rank number)
    assert s1_row["rank"] < s2_row["rank"]


# ======================================================================
# 5. ADMIN SUPPORTER SEARCH TESTS FOR MANUAL ENTRY
# ======================================================================

@pytest.mark.asyncio
async def test_admin_search_supporters_by_name_and_id(
    test_client: AsyncClient, support_test_users: dict
):
    student = support_test_users["student1"]
    admin = support_test_users["admin"]

    with override_admin(admin):
        # 1. Search by name
        res1 = await test_client.get(
            "/api/v1/admin/support-contributions/search-supporters",
            params={"query": student.full_name[:5]},
        )
        assert res1.status_code == 200
        items = res1.json()
        assert any(u["user_id"] == student.user_id for u in items)
        first = next(u for u in items if u["user_id"] == student.user_id)
        assert first["full_name"] == student.full_name
        assert first["profile_path"] == f"/users/{student.user_id}"
        # Never expose sensitive fields
        assert "email" not in first
        assert "phone" not in first
        assert "bank_account" not in first

        # 2. Search by numeric user_id
        res2 = await test_client.get(
            "/api/v1/admin/support-contributions/search-supporters",
            params={"query": str(student.user_id)},
        )
        assert res2.status_code == 200
        assert any(u["user_id"] == student.user_id for u in res2.json())


@pytest.mark.asyncio
async def test_admin_search_supporters_bounded_limit(
    test_client: AsyncClient, support_test_users: dict
):
    admin = support_test_users["admin"]

    with override_admin(admin):
        res = await test_client.get(
            "/api/v1/admin/support-contributions/search-supporters",
            params={"query": "a", "limit": 2},
        )
        assert res.status_code == 200
        assert len(res.json()) <= 2


@pytest.mark.asyncio
async def test_admin_search_supporters_unknown_returns_empty(
    test_client: AsyncClient, support_test_users: dict
):
    admin = support_test_users["admin"]

    with override_admin(admin):
        res = await test_client.get(
            "/api/v1/admin/support-contributions/search-supporters",
            params={"query": "NonExistentUserZZZZZ999"},
        )
        assert res.status_code == 200
        assert res.json() == []


@pytest.mark.asyncio
async def test_admin_search_supporters_auth_required(
    test_client: AsyncClient, support_test_users: dict
):
    student = support_test_users["student1"]

    # Unauthenticated -> 401
    res = await test_client.get(
        "/api/v1/admin/support-contributions/search-supporters",
        params={"query": str(student.user_id)},
    )
    assert res.status_code == 401

    # Student -> 403
    with override_user(student):
        res = await test_client.get(
            "/api/v1/admin/support-contributions/search-supporters",
            params={"query": str(student.user_id)},
        )
        assert res.status_code == 403


