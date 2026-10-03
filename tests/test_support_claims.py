import uuid
from datetime import datetime, timezone, timedelta
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.auth.dependencies import get_current_active_user, require_admin
from app.modules.feedback.models import SupportClaim, SupportContribution
from app.modules.notifications.models import Notification
from app.modules.users.models import User, UserRole, UserStatus


@pytest_asyncio.fixture
async def claims_test_users(db_session: AsyncSession):
    student1 = User(
        email=f"claim_stud1_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Nguyễn Văn Sinh Viên Một",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    student2 = User(
        email=f"claim_stud2_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Trần Thị Sinh Viên Hai",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    admin = User(
        email=f"claim_admin_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Quản Trị Viên Đối Soát",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add_all([student1, student2, admin])
    await db_session.flush()
    return {
        "student1": student1,
        "student2": student2,
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
# A. USER CLAIM CREATION
# ======================================================================

@pytest.mark.asyncio
async def test_user_create_claim_success(test_client: AsyncClient, claims_test_users, db_session: AsyncSession):
    student1 = claims_test_users["student1"]
    now_iso = datetime.now(timezone.utc).isoformat()

    with override_user(student1):
        resp = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "claimed_amount_vnd": 50000,
                "claimed_transferred_at": now_iso,
                "sender_account_name": "NGUYEN VAN A",
                "wants_public": True,
            },
        )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["claim_id"] > 0
    assert data["claimed_amount_vnd"] == 50000
    assert data["sender_account_name"] == "NGUYEN VAN A"
    assert data["wants_public"] is True
    assert data["status"] == "PENDING"
    assert "created_at" in data

    # Verify DB row
    stmt = select(SupportClaim).where(SupportClaim.claim_id == data["claim_id"])
    res = await db_session.execute(stmt)
    claim = res.scalar_one()
    assert claim.supporter_id == student1.user_id
    assert claim.status == "PENDING"
    assert claim.reviewed_by is None
    assert claim.contribution_id is None


@pytest.mark.asyncio
async def test_user_cannot_impersonate_supporter(test_client: AsyncClient, claims_test_users, db_session: AsyncSession):
    student1 = claims_test_users["student1"]
    student2 = claims_test_users["student2"]
    now_iso = datetime.now(timezone.utc).isoformat()

    # Client tries to send someone else's supporter_id or user_id in body
    with override_user(student1):
        resp = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "supporter_id": student2.user_id,
                "user_id": student2.user_id,
                "claimed_amount_vnd": 20000,
                "claimed_transferred_at": now_iso,
                "sender_account_name": "NGUYEN VAN A",
            },
        )
    assert resp.status_code == 201
    claim_id = resp.json()["claim_id"]

    stmt = select(SupportClaim).where(SupportClaim.claim_id == claim_id)
    res = await db_session.execute(stmt)
    claim = res.scalar_one()
    # Server-side auth MUST derive supporter_id from current_user, ignoring body
    assert claim.supporter_id == student1.user_id
    assert claim.supporter_id != student2.user_id


@pytest.mark.asyncio
async def test_user_create_claim_sender_account_name_required(test_client: AsyncClient, claims_test_users):
    student1 = claims_test_users["student1"]
    now_iso = datetime.now(timezone.utc).isoformat()

    with override_user(student1):
        # Missing sender_account_name -> 422
        r1 = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={"claimed_amount_vnd": 50000, "claimed_transferred_at": now_iso},
        )
        assert r1.status_code == 422

        # Empty sender_account_name -> 422
        r2 = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={"claimed_amount_vnd": 50000, "claimed_transferred_at": now_iso, "sender_account_name": ""},
        )
        assert r2.status_code == 422

        # Whitespace-only sender_account_name -> 422
        r3 = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={"claimed_amount_vnd": 50000, "claimed_transferred_at": now_iso, "sender_account_name": "   "},
        )
        assert r3.status_code == 422

        # Valid with whitespace -> 201 trimmed
        r4 = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={"claimed_amount_vnd": 50000, "claimed_transferred_at": now_iso, "sender_account_name": "  TRAN VAN B  "},
        )
        assert r4.status_code == 201
        assert r4.json()["sender_account_name"] == "TRAN VAN B"


@pytest.mark.asyncio
async def test_user_create_claim_invalid_amount(test_client: AsyncClient, claims_test_users):
    student1 = claims_test_users["student1"]
    now_iso = datetime.now(timezone.utc).isoformat()

    with override_user(student1):
        # 0 VND
        resp0 = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "claimed_amount_vnd": 0,
                "claimed_transferred_at": now_iso,
                "sender_account_name": "NGUYEN VAN A",
            },
        )
        assert resp0.status_code == 422

        # Negative VND
        resp_neg = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "claimed_amount_vnd": -50000,
                "claimed_transferred_at": now_iso,
                "sender_account_name": "NGUYEN VAN A",
            },
        )
        assert resp_neg.status_code == 422


@pytest.mark.asyncio
async def test_user_create_claim_default_wants_public_is_false(test_client: AsyncClient, claims_test_users):
    student1 = claims_test_users["student1"]
    now_iso = datetime.now(timezone.utc).isoformat()

    with override_user(student1):
        resp = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "claimed_amount_vnd": 50000,
                "claimed_transferred_at": now_iso,
                "sender_account_name": "NGUYEN VAN A",
            },
        )
    assert resp.status_code == 201
    assert resp.json()["wants_public"] is False


@pytest.mark.asyncio
async def test_unauthenticated_cannot_create_claim(test_client: AsyncClient):
    now_iso = datetime.now(timezone.utc).isoformat()
    resp = await test_client.post(
        "/api/v1/feedback/support/claims",
        json={
            "claimed_amount_vnd": 50000,
            "claimed_transferred_at": now_iso,
            "sender_account_name": "NGUYEN VAN A",
        },
    )
    assert resp.status_code == 401


# ======================================================================
# B. USER CLAIM VISIBILITY
# ======================================================================

@pytest.mark.asyncio
async def test_user_sees_own_claims_and_not_others(test_client: AsyncClient, claims_test_users):
    student1 = claims_test_users["student1"]
    student2 = claims_test_users["student2"]
    now_iso = datetime.now(timezone.utc).isoformat()

    # Student 1 creates 2 claims
    with override_user(student1):
        await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "claimed_amount_vnd": 20000,
                "claimed_transferred_at": now_iso,
                "sender_account_name": "NGUYEN VAN A",
            },
        )
        await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "claimed_amount_vnd": 50000,
                "claimed_transferred_at": now_iso,
                "sender_account_name": "NGUYEN VAN A",
            },
        )

        resp1 = await test_client.get("/api/v1/feedback/support/claims/me")
        assert resp1.status_code == 200
        items1 = resp1.json()["items"]
        assert len(items1) == 2
        assert items1[0]["claimed_amount_vnd"] == 50000

    # Student 2 should see 0 claims
    with override_user(student2):
        resp2 = await test_client.get("/api/v1/feedback/support/claims/me")
        assert resp2.status_code == 200
        items2 = resp2.json()["items"]
        assert len(items2) == 0


@pytest.mark.asyncio
async def test_unauthenticated_cannot_list_my_claims(test_client: AsyncClient):
    resp = await test_client.get("/api/v1/feedback/support/claims/me")
    assert resp.status_code == 401


# ======================================================================
# C. ADMIN PENDING QUEUE
# ======================================================================

@pytest.mark.asyncio
async def test_admin_list_pending_claims(test_client: AsyncClient, claims_test_users):
    student1 = claims_test_users["student1"]
    admin = claims_test_users["admin"]
    now_iso = datetime.now(timezone.utc).isoformat()

    with override_user(student1):
        await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "claimed_amount_vnd": 100000,
                "claimed_transferred_at": now_iso,
                "sender_account_name": "NGUYEN VAN A",
                "wants_public": True,
            },
        )

    with override_admin(admin):
        resp = await test_client.get("/api/v1/admin/support-claims?status=PENDING")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) >= 1
        claim = data["items"][0]
        assert claim["claimed_amount_vnd"] == 100000
        assert claim["supporter"]["user_id"] == student1.user_id
        assert claim["supporter"]["full_name"] == student1.full_name
        assert claim["supporter"]["profile_path"] == f"/users/{student1.user_id}"
        # Assert safe fields - no email or phone
        assert "email" not in claim["supporter"]
        assert "phone" not in claim["supporter"]


@pytest.mark.asyncio
async def test_student_forbidden_from_admin_claims(test_client: AsyncClient, claims_test_users):
    student1 = claims_test_users["student1"]

    with override_user(student1):
        # List
        resp_list = await test_client.get("/api/v1/admin/support-claims")
        assert resp_list.status_code == 403

        # Verify
        resp_verify = await test_client.post(
            "/api/v1/admin/support-claims/1/verify",
            json={"amount_vnd": 50000, "received_at": datetime.now(timezone.utc).isoformat()},
        )
        assert resp_verify.status_code == 403

        # Reject
        resp_reject = await test_client.post(
            "/api/v1/admin/support-claims/1/reject",
            json={"rejection_reason": "No"},
        )
        assert resp_reject.status_code == 403


# ======================================================================
# D. VERIFY FLOW & IDEMPOTENCY
# ======================================================================

@pytest.mark.asyncio
async def test_admin_verify_claim_success(test_client: AsyncClient, claims_test_users, db_session: AsyncSession):
    student1 = claims_test_users["student1"]
    admin = claims_test_users["admin"]
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. User submits claim for 50,000 VND
    with override_user(student1):
        c_resp = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "claimed_amount_vnd": 50000,
                "claimed_transferred_at": now_iso,
                "sender_account_name": "NGUYEN VAN A",
                "wants_public": True,
            },
        )
        claim_id = c_resp.json()["claim_id"]

    # 2. Admin verifies, but actual bank receipt is 51,000 VND!
    verify_time_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with override_admin(admin):
        v_resp = await test_client.post(
            f"/api/v1/admin/support-claims/{claim_id}/verify",
            json={
                "amount_vnd": 51000,
                "received_at": verify_time_iso,
                "transaction_ref": "FT260925123456",
                "admin_note": "Khớp sao kê VCB",
            },
        )
        assert v_resp.status_code == 200, v_resp.text
        v_data = v_resp.json()
        assert v_data["status"] == "VERIFIED"
        assert v_data["contribution_id"] is not None
        assert v_data["reviewed_by"]["user_id"] == admin.user_id

    # 3. Check authoritative ledger: exactly 1 support_contributions row created with 51,000 VND!
    stmt = select(SupportContribution).where(SupportContribution.supporter_id == student1.user_id)
    res = await db_session.execute(stmt)
    contributions = list(res.scalars().all())
    assert len(contributions) == 1
    contrib = contributions[0]
    assert contrib.amount_vnd == 51000
    assert contrib.is_public is True  # Honored claim.wants_public
    assert contrib.recorded_by == admin.user_id
    assert contrib.transaction_ref == "FT260925123456"
    assert contrib.admin_note == "Khớp sao kê VCB"

    # 4. Check durable notification was created for student
    stmt_n = select(Notification).where(
        Notification.user_id == student1.user_id,
        Notification.ref_type == "SUPPORT_CLAIM",
        Notification.ref_id == claim_id,
    )
    res_n = await db_session.execute(stmt_n)
    notif = res_n.scalar_one_or_none()
    assert notif is not None
    assert "xác nhận" in notif.title.lower()


@pytest.mark.asyncio
async def test_admin_verify_claim_idempotency_double_click(test_client: AsyncClient, claims_test_users, db_session: AsyncSession):
    student1 = claims_test_users["student1"]
    admin = claims_test_users["admin"]
    now_iso = datetime.now(timezone.utc).isoformat()

    with override_user(student1):
        c_resp = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "claimed_amount_vnd": 50000,
                "claimed_transferred_at": now_iso,
                "sender_account_name": "NGUYEN VAN A",
            },
        )
        claim_id = c_resp.json()["claim_id"]

    verify_payload = {
        "amount_vnd": 50000,
        "received_at": now_iso,
        "transaction_ref": "FT1111",
    }

    with override_admin(admin):
        # First verify -> 200 OK
        resp1 = await test_client.post(f"/api/v1/admin/support-claims/{claim_id}/verify", json=verify_payload)
        assert resp1.status_code == 200

        # Second verify -> 409 Conflict
        resp2 = await test_client.post(f"/api/v1/admin/support-claims/{claim_id}/verify", json=verify_payload)
        assert resp2.status_code == 409

    # Exactly 1 contribution exists in database
    stmt = select(SupportContribution).where(SupportContribution.transaction_ref == "FT1111")
    res = await db_session.execute(stmt)
    assert len(list(res.scalars().all())) == 1


# ======================================================================
# E. REJECT FLOW
# ======================================================================

@pytest.mark.asyncio
async def test_admin_reject_claim_success(test_client: AsyncClient, claims_test_users, db_session: AsyncSession):
    student1 = claims_test_users["student1"]
    admin = claims_test_users["admin"]
    now_iso = datetime.now(timezone.utc).isoformat()

    with override_user(student1):
        c_resp = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "claimed_amount_vnd": 50000,
                "claimed_transferred_at": now_iso,
                "sender_account_name": "NGUYEN VAN A",
            },
        )
        claim_id = c_resp.json()["claim_id"]

    with override_admin(admin):
        r_resp = await test_client.post(
            f"/api/v1/admin/support-claims/{claim_id}/reject",
            json={"rejection_reason": "Không tìm thấy giao dịch chuyển tiền."},
        )
        assert r_resp.status_code == 200
        r_data = r_resp.json()
        assert r_data["status"] == "REJECTED"
        assert r_data["contribution_id"] is None
        assert r_data["reviewed_by"]["user_id"] == admin.user_id
        assert r_data["rejection_reason"] == "Không tìm thấy giao dịch chuyển tiền."

    # NO support_contributions row created!
    stmt = select(SupportContribution).where(SupportContribution.supporter_id == student1.user_id)
    res = await db_session.execute(stmt)
    assert len(list(res.scalars().all())) == 0

    # User sees rejected status
    with override_user(student1):
        my_claims = await test_client.get("/api/v1/feedback/support/claims/me")
        assert my_claims.status_code == 200
        assert my_claims.json()["items"][0]["status"] == "REJECTED"


@pytest.mark.asyncio
async def test_cannot_verify_rejected_claim(test_client: AsyncClient, claims_test_users):
    student1 = claims_test_users["student1"]
    admin = claims_test_users["admin"]
    now_iso = datetime.now(timezone.utc).isoformat()

    with override_user(student1):
        c_resp = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "claimed_amount_vnd": 50000,
                "claimed_transferred_at": now_iso,
                "sender_account_name": "NGUYEN VAN A",
            },
        )
        claim_id = c_resp.json()["claim_id"]

    with override_admin(admin):
        # Reject first
        await test_client.post(f"/api/v1/admin/support-claims/{claim_id}/reject", json={})
        # Attempt verify -> 409
        v_resp = await test_client.post(
            f"/api/v1/admin/support-claims/{claim_id}/verify",
            json={"amount_vnd": 50000, "received_at": now_iso},
        )
        assert v_resp.status_code == 409


@pytest.mark.asyncio
async def test_cannot_reject_verified_claim(test_client: AsyncClient, claims_test_users):
    student1 = claims_test_users["student1"]
    admin = claims_test_users["admin"]
    now_iso = datetime.now(timezone.utc).isoformat()

    with override_user(student1):
        c_resp = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "claimed_amount_vnd": 50000,
                "claimed_transferred_at": now_iso,
                "sender_account_name": "NGUYEN VAN A",
            },
        )
        claim_id = c_resp.json()["claim_id"]

    with override_admin(admin):
        # Verify first
        await test_client.post(
            f"/api/v1/admin/support-claims/{claim_id}/verify",
            json={"amount_vnd": 50000, "received_at": now_iso},
        )
        # Attempt reject -> 409
        r_resp = await test_client.post(
            f"/api/v1/admin/support-claims/{claim_id}/reject",
            json={},
        )
        assert r_resp.status_code == 409


# ======================================================================
# F. LEADERBOARD REGRESSION
# ======================================================================

@pytest.mark.asyncio
async def test_leaderboard_ignores_claims_and_private_contributions(test_client: AsyncClient, claims_test_users):
    student1 = claims_test_users["student1"]
    student2 = claims_test_users["student2"]
    admin = claims_test_users["admin"]
    now_iso = datetime.now(timezone.utc).isoformat()

    # Student 1 creates claim for 100,000,000 VND (PENDING)
    with override_user(student1):
        c1 = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "claimed_amount_vnd": 100000000,
                "claimed_transferred_at": now_iso,
                "sender_account_name": "NGUYEN VAN A",
                "wants_public": True,
            },
        )
        claim1_id = c1.json()["claim_id"]

    # Student 2 creates claim for 50,000,000 VND (then REJECTED)
    with override_user(student2):
        c2 = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "claimed_amount_vnd": 50000000,
                "claimed_transferred_at": now_iso,
                "sender_account_name": "TRAN THI B",
                "wants_public": True,
            },
        )
        claim2_id = c2.json()["claim_id"]

    with override_admin(admin):
        await test_client.post(f"/api/v1/admin/support-claims/{claim2_id}/reject", json={})

    # Leaderboard MUST NOT have Student 1 or Student 2
    l_resp = await test_client.get("/api/v1/feedback/support/leaderboard")
    assert l_resp.status_code == 200
    leaderboard_users = [item["supporter"]["public_id"] for item in l_resp.json()["items"]]
    assert str(student1.public_id) not in leaderboard_users
    assert str(student2.public_id) not in leaderboard_users

    # Now verify Student 1 with wants_public = False
    # First create private claim
    with override_user(student1):
        c3 = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "claimed_amount_vnd": 200000,
                "claimed_transferred_at": now_iso,
                "sender_account_name": "NGUYEN VAN A",
                "wants_public": False,
            },
        )
        claim3_id = c3.json()["claim_id"]

    with override_admin(admin):
        await test_client.post(
            f"/api/v1/admin/support-claims/{claim3_id}/verify",
            json={"amount_vnd": 200000, "received_at": now_iso},
        )

    # Leaderboard still excludes Student 1 because is_public = False
    l_resp2 = await test_client.get("/api/v1/feedback/support/leaderboard")
    assert str(student1.public_id) not in [item["supporter"]["public_id"] for item in l_resp2.json()["items"]]


# ======================================================================
# G. MANUAL ADMIN FLOW REGRESSION
# ======================================================================

@pytest.mark.asyncio
async def test_manual_admin_flow_and_supporter_search(test_client: AsyncClient, claims_test_users):
    student1 = claims_test_users["student1"]
    admin = claims_test_users["admin"]
    now_iso = datetime.now(timezone.utc).isoformat()

    with override_admin(admin):
        # 1. Search by name
        r1 = await test_client.get(
            "/api/v1/admin/support-contributions/search-supporters",
            params={"query": "Sinh Viên Một"},
        )
        assert r1.status_code == 200
        items = r1.json()
        assert any(u["user_id"] == student1.user_id for u in items)

        # 2. Search by numeric user_id
        r2 = await test_client.get(
            "/api/v1/admin/support-contributions/search-supporters",
            params={"query": str(student1.user_id)},
        )
        assert r2.status_code == 200
        assert any(u["user_id"] == student1.user_id for u in r2.json())

        # 3. Create manual contribution
        c_resp = await test_client.post(
            "/api/v1/admin/support-contributions",
            json={
                "supporter_id": student1.user_id,
                "amount_vnd": 30000,
                "received_at": now_iso,
                "is_public": False,
                "admin_note": "Ghi nhận thủ công",
            },
        )
        assert c_resp.status_code == 201
        assert c_resp.json()["amount_vnd"] == 30000
