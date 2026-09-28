import io
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.banks import get_bank_by_bin
from app.main import app
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.conversations.models import (
    Conversation,
    ConversationMember,
    Message,
)
from app.modules.orders.service import generate_vietqr_url
from app.modules.users.models import User, UserRole, UserStatus


def auth_patch(user: User):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_active_user] = lambda: user

    class CleanCtx:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc_val, exc_tb):
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_current_active_user, None)

    return CleanCtx()


@pytest_asyncio.fixture
async def user_a(db_session: AsyncSession) -> User:
    u = User(
        email="user_a_hardening@ptit.edu.vn",
        full_name="Nguyễn Văn A",
        phone="0912345678",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    u = User(
        email="user_b_hardening@ptit.edu.vn",
        full_name="Trần Thị B",
        phone="0987654321",
        role=UserRole.STUDENT,
        status=UserStatus.ACTIVE,
    )
    db_session.add(u)
    await db_session.commit()
    return u


# =========================================================================
# 1. Phone Validation Tests
# =========================================================================

@pytest.mark.asyncio
async def test_phone_validation_valid_formats(test_client: AsyncClient, user_a: User):
    """Test valid Vietnamese mobile numbers with +84, 84, separators are normalized to 0XXXXXXXXX."""
    valid_test_cases = [
        ("0912345678", "0912345678"),
        ("+84912345678", "0912345678"),
        ("84912345678", "0912345678"),
        ("0912 345 678", "0912345678"),
        ("0912-345-678", "0912345678"),
        ("0912.345.678", "0912345678"),
        ("+84 912 345 678", "0912345678"),
        ("0321234567", "0321234567"),
        ("0561234567", "0561234567"),
        ("0771234567", "0771234567"),
        ("0881234567", "0881234567"),
    ]

    with auth_patch(user_a):
        for raw_phone, expected_stored in valid_test_cases:
            resp = await test_client.patch(
                "/api/v1/users/me",
                json={"phone": raw_phone},
            )
            assert resp.status_code == 200, f"Failed for phone {raw_phone}: {resp.text}"
            data = resp.json()
            assert data["phone"] == expected_stored


@pytest.mark.asyncio
async def test_phone_validation_invalid_formats(test_client: AsyncClient, user_a: User):
    """Test malformed, wrong prefix, all zeros, letters, or foreign numbers are rejected with 422."""
    invalid_phones = [
        "abcdefghij",
        "09123",
        "091234567890",
        "0000000000",
        "1234567890",
        "0243123456",  # Landline Hà Nội
        "0123456789",  # Obsolete 11-digit prefix
        "!@#$%^&*()",
        "+14155552671",  # US phone
    ]

    with auth_patch(user_a):
        for raw_phone in invalid_phones:
            resp = await test_client.patch(
                "/api/v1/users/me",
                json={"phone": raw_phone},
            )
            assert resp.status_code == 422, f"Phone '{raw_phone}' should have returned 422, got {resp.status_code}"


@pytest.mark.asyncio
async def test_phone_optional_on_profile_patch(test_client: AsyncClient, user_a: User):
    """Test phone is optional: null or omitted does not trigger validation error."""
    with auth_patch(user_a):
        # Omitted
        resp = await test_client.patch(
            "/api/v1/users/me",
            json={"bio": "Updated bio without phone"},
        )
        assert resp.status_code == 200

        # Explicitly null
        resp = await test_client.patch(
            "/api/v1/users/me",
            json={"phone": None},
        )
        assert resp.status_code == 200
        assert resp.json()["phone"] is None


# =========================================================================
# 2. Bank Account Validation Tests
# =========================================================================

@pytest.mark.asyncio
async def test_bank_account_valid_numeric_preserves_leading_zero(
    test_client: AsyncClient, user_a: User, db_session: AsyncSession
):
    """Valid digits-only bank account number preserves leading zeros."""
    with auth_patch(user_a):
        resp = await test_client.put(
            "/api/v1/users/me/bank-account",
            json={
                "bank_bin": "970422",  # MBBank
                "account_number": "0011001234567",
                "account_name": "NGUYEN VAN A",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["account_number"] == "0011001234567"
        assert data["account_number"].startswith("00")


@pytest.mark.asyncio
async def test_bank_account_invalid_account_number(test_client: AsyncClient, user_a: User):
    """Malformed account numbers (alphabetic, spaces, symbols, too short/long) return 422."""
    invalid_acc_numbers = [
        "Vshbsbsbbsbsbd",
        "ABC123",
        "1234 5678",
        "123-456",
        "123",  # < 4 digits
        "1" * 31,  # > 30 digits
        "0123456789@",
        "12.345.678",
    ]

    with auth_patch(user_a):
        for acc in invalid_acc_numbers:
            resp = await test_client.put(
                "/api/v1/users/me/bank-account",
                json={
                    "bank_bin": "970422",
                    "account_number": acc,
                    "account_name": "NGUYEN VAN A",
                },
            )
            assert resp.status_code == 422, f"Account number '{acc}' should return 422, got {resp.status_code}"


@pytest.mark.asyncio
async def test_bank_account_unsupported_bank(test_client: AsyncClient, user_a: User):
    """Unsupported bank BIN or bank code must return 422."""
    with auth_patch(user_a):
        resp = await test_client.put(
            "/api/v1/users/me/bank-account",
            json={
                "bank_bin": "999999",  # Unsupported
                "account_number": "0123456789",
                "account_name": "NGUYEN VAN A",
            },
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_bank_account_name_validation(test_client: AsyncClient, user_a: User):
    """Account name must contain letters, no control chars, proper length."""
    with auth_patch(user_a):
        # Invalid cases
        invalid_names = [
            "12345678",  # digits only
            "---...---",  # punctuation only
            "A\x00B",  # control character
            "X",  # < 2 chars
            "A" * 101,  # > 100 chars
        ]
        for name in invalid_names:
            resp = await test_client.put(
                "/api/v1/users/me/bank-account",
                json={
                    "bank_bin": "970422",
                    "account_number": "0123456789",
                    "account_name": name,
                },
            )
            assert resp.status_code == 422, f"Account name '{name}' should return 422, got {resp.status_code}"

        # Valid cases
        valid_resp = await test_client.put(
            "/api/v1/users/me/bank-account",
            json={
                "bank_bin": "970422",
                "account_number": "0123456789",
                "account_name": "  Trần   Thị   B  ",
            },
        )
        assert valid_resp.status_code == 200
        # Collapses internal spaces
        assert valid_resp.json()["account_name"] == "Trần Thị B"


@pytest.mark.asyncio
async def test_vietqr_compatibility_regression(test_client: AsyncClient, user_a: User):
    """Valid saved profile bank account flows cleanly into generate_vietqr_url."""
    with auth_patch(user_a):
        save_resp = await test_client.put(
            "/api/v1/users/me/bank-account",
            json={
                "bank_bin": "970422",  # MBBank
                "account_number": "0352866196",
                "account_name": "NGUYEN KHAC THINH",
            },
        )
        assert save_resp.status_code == 200
        bank_data = save_resp.json()

    # Verify VietQR URL generation with the stored values
    qr_url = generate_vietqr_url(
        bank_bin=bank_data["bank_bin"],
        account_number=bank_data["account_number"],
        amount=150000,
        order_code="ORD-12345",
        account_name=bank_data["account_name"],
    )
    assert qr_url.startswith("https://img.vietqr.io/image/970422-0352866196-compact2.png")
    assert "amount=150000" in qr_url
    assert "addInfo=ORD-12345" in qr_url
    assert "accountName=NGUYEN+KHAC+THINH" in qr_url or "accountName=NGUYEN%20KHAC%20THINH" in qr_url


# =========================================================================
# 3. Dedicated Official Support Metadata & Join Tests
# =========================================================================

@pytest.mark.asyncio
async def test_get_official_support_metadata(
    test_client: AsyncClient, user_a: User, user_b: User, db_session: AsyncSession
):
    """
    GET /api/v1/conversations/official-support:
    - configured official group -> 200
    - correct conversation_id
    - correct title/description
    - member -> is_member true
    - non-member -> is_member false
    - GET does NOT create membership (read-only)
    - missing config -> 503
    - wrong type -> 503
    - deleted group -> 503
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 1. Valid official group
    official_group = Conversation(
        type="GROUP",
        title="Cộng đồng Chợ PTITers",
        description="Mọi người cần giao lưu, hỏi đáp hay hỗ trợ thì nhắn ở đây nhé",
        created_at=now,
    )
    db_session.add(official_group)
    await db_session.flush()

    # user_a is member
    db_session.add(
        ConversationMember(
            conversation_id=official_group.conversation_id,
            user_id=user_a.user_id,
            role="MEMBER",
        )
    )
    await db_session.commit()

    with patch.object(settings, "OFFICIAL_SUPPORT_GROUP_ID", official_group.conversation_id):
        # Case A: user_a is member -> is_member is True
        with auth_patch(user_a):
            resp_member = await test_client.get("/api/v1/conversations/official-support")
            assert resp_member.status_code == 200
            data_m = resp_member.json()
            assert data_m["conversation_id"] == official_group.conversation_id
            assert data_m["title"] == "Cộng đồng Chợ PTITers"
            assert data_m["description"] == "Mọi người cần giao lưu, hỏi đáp hay hỗ trợ thì nhắn ở đây nhé"
            assert data_m["is_member"] is True

        # Case B: user_b is non-member -> is_member is False
        with auth_patch(user_b):
            resp_non_member = await test_client.get("/api/v1/conversations/official-support")
            assert resp_non_member.status_code == 200
            data_nm = resp_non_member.json()
            assert data_nm["conversation_id"] == official_group.conversation_id
            assert data_nm["is_member"] is False

            # Verify GET does NOT create membership for user_b
            mem_b = await db_session.scalar(
                select(ConversationMember).where(
                    ConversationMember.conversation_id == official_group.conversation_id,
                    ConversationMember.user_id == user_b.user_id,
                )
            )
            assert mem_b is None, "GET /official-support must be strictly read-only and NOT mutate membership"

    # Case C: Missing config -> 503
    with patch.object(settings, "OFFICIAL_SUPPORT_GROUP_ID", None):
        with auth_patch(user_a):
            resp_unconf = await test_client.get("/api/v1/conversations/official-support")
            assert resp_unconf.status_code == 503

    # Case D: Non-existent group -> 503
    with patch.object(settings, "OFFICIAL_SUPPORT_GROUP_ID", 999999):
        with auth_patch(user_a):
            resp_notfound = await test_client.get("/api/v1/conversations/official-support")
            assert resp_notfound.status_code == 503

    # Case E: Wrong type (DIRECT) -> 503
    direct_conv = Conversation(
        type="DIRECT",
        user_one_id=user_a.user_id,
        user_two_id=user_b.user_id,
    )
    db_session.add(direct_conv)
    await db_session.commit()

    with patch.object(settings, "OFFICIAL_SUPPORT_GROUP_ID", direct_conv.conversation_id):
        with auth_patch(user_a):
            resp_wrong_type = await test_client.get("/api/v1/conversations/official-support")
            assert resp_wrong_type.status_code == 503

    # Case F: Deleted group -> 503
    deleted_group = Conversation(
        type="GROUP",
        title="Deleted Group",
        deleted_at=now,
    )
    db_session.add(deleted_group)
    await db_session.commit()

    with patch.object(settings, "OFFICIAL_SUPPORT_GROUP_ID", deleted_group.conversation_id):
        with auth_patch(user_a):
            resp_deleted = await test_client.get("/api/v1/conversations/official-support")
            assert resp_deleted.status_code == 503


@pytest.mark.asyncio
async def test_post_official_support_join_idempotent_and_rejoin(
    test_client: AsyncClient, user_a: User, user_b: User, db_session: AsyncSession
):
    """
    POST /api/v1/conversations/official-support/join:
    - non-member -> creates membership
    - member -> idempotent
    - left member -> restores active membership
    - returns official conversation_id
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    support_group = Conversation(
        type="GROUP",
        title="Cộng đồng Chợ PTITers",
        description="Nhóm chính thức",
    )
    db_session.add(support_group)
    await db_session.commit()

    with patch.object(settings, "OFFICIAL_SUPPORT_GROUP_ID", support_group.conversation_id):
        # 1. Non-member joins -> creates membership
        with auth_patch(user_a):
            r1 = await test_client.post("/api/v1/conversations/official-support/join")
            assert r1.status_code == 200
            assert r1.json()["conversation_id"] == support_group.conversation_id

            mem_1 = await db_session.scalar(
                select(ConversationMember).where(
                    ConversationMember.conversation_id == support_group.conversation_id,
                    ConversationMember.user_id == user_a.user_id,
                    ConversationMember.left_at.is_(None),
                )
            )
            assert mem_1 is not None

            # 2. Member calls join again -> idempotent, returns same conversation_id
            r2 = await test_client.post("/api/v1/conversations/official-support/join")
            assert r2.status_code == 200
            assert r2.json()["conversation_id"] == support_group.conversation_id

            members = (await db_session.scalars(
                select(ConversationMember).where(
                    ConversationMember.conversation_id == support_group.conversation_id,
                    ConversationMember.user_id == user_a.user_id,
                )
            )).all()
            assert len(members) == 1, "Join must be idempotent with no duplicate membership rows"

        # 3. Left member -> restores active membership
        # Simulate user_b was a member who left
        mem_b = ConversationMember(
            conversation_id=support_group.conversation_id,
            user_id=user_b.user_id,
            role="MEMBER",
            left_at=now - timedelta(days=2),
        )
        db_session.add(mem_b)
        await db_session.commit()

        with auth_patch(user_b):
            r_rejoin = await test_client.post("/api/v1/conversations/official-support/join")
            assert r_rejoin.status_code == 200
            assert r_rejoin.json()["conversation_id"] == support_group.conversation_id

            await db_session.refresh(mem_b)
            assert mem_b.left_at is None, "Rejoining official support restores active membership"


# =========================================================================
# 4. Canonical Group Pagination & Absence of Generic is_official_support
# =========================================================================

@pytest.mark.asyncio
async def test_generic_group_list_no_official_flag_and_normal_pagination(
    test_client: AsyncClient, user_a: User, db_session: AsyncSession
):
    """
    - Generic group list DTO no longer includes is_official_support
    - Generic conversation detail DTO no longer includes is_official_support
    - Normal keyset pagination and ordering preserved without official-specific sort hacks
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Create 4 ordinary groups with ordered recency
    groups = []
    for i in range(4):
        g = Conversation(
            type="GROUP",
            title=f"Nhóm Test {i + 1}",
            created_at=now - timedelta(hours=i * 2 + 1),
            last_message_at=now - timedelta(hours=i * 2 + 1),
        )
        db_session.add(g)
        groups.append(g)
    await db_session.flush()

    for g in groups:
        db_session.add(
            ConversationMember(
                conversation_id=g.conversation_id,
                user_id=user_a.user_id,
                role="MEMBER",
            )
        )
    await db_session.commit()

    with auth_patch(user_a):
        # Page 1: limit 2
        p1_resp = await test_client.get("/api/v1/conversations?type=GROUP&limit=2")
        assert p1_resp.status_code == 200
        p1_data = p1_resp.json()
        p1_items = p1_data["items"]
        assert len(p1_items) == 2

        # Verify no is_official_support field on DTO
        assert "is_official_support" not in p1_items[0]
        assert "is_official_support" not in p1_items[1]

        # Verify canonical recency order: group 0 is newest, then group 1
        assert p1_items[0]["conversation_id"] == groups[0].conversation_id
        assert p1_items[1]["conversation_id"] == groups[1].conversation_id

        # Verify detail endpoint does NOT have is_official_support
        detail_resp = await test_client.get(f"/api/v1/conversations/{groups[0].conversation_id}")
        assert detail_resp.status_code == 200
        assert "is_official_support" not in detail_resp.json()

        # Page 2: keyset cursor
        cursor = p1_data["next_cursor"]
        assert cursor is not None

        p2_resp = await test_client.get(f"/api/v1/conversations?type=GROUP&limit=2&cursor={cursor}")
        assert p2_resp.status_code == 200
        p2_data = p2_resp.json()
        p2_items = p2_data["items"]
        assert len(p2_items) == 2

        assert p2_items[0]["conversation_id"] == groups[2].conversation_id
        assert p2_items[1]["conversation_id"] == groups[3].conversation_id

        # Total distinct IDs
        all_ids = [item["conversation_id"] for item in p1_items] + [item["conversation_id"] for item in p2_items]
        assert all_ids == [g.conversation_id for g in groups]
        assert len(all_ids) == len(set(all_ids)), "Keyset pagination must have zero duplicates or skips"
