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
# 3. Official Support Group Identity & Presentation Tests
# =========================================================================

@pytest.mark.asyncio
async def test_official_support_identity_and_dto(
    test_client: AsyncClient, user_a: User, db_session: AsyncSession
):
    """Configured OFFICIAL_SUPPORT_GROUP_ID is marked is_official_support=True; ordinary groups are False."""
    # Create two groups: one with configured official ID, one ordinary
    official_group = Conversation(
        type="GROUP",
        title="Cộng đồng Chợ PTITers",
    )
    db_session.add(official_group)
    await db_session.flush()

    ordinary_group = Conversation(
        type="GROUP",
        title="Nhóm Học Tập PTIT",
    )
    db_session.add(ordinary_group)
    await db_session.flush()

    # Another group with same title as official group, but not configured ID
    impostor_group = Conversation(
        type="GROUP",
        title="Cộng đồng Chợ PTITers",
    )
    db_session.add(impostor_group)
    await db_session.flush()

    # Add user_a as member to all 3
    for conv in [official_group, ordinary_group, impostor_group]:
        m = ConversationMember(
            conversation_id=conv.conversation_id,
            user_id=user_a.user_id,
            role="MEMBER",
        )
        db_session.add(m)
    await db_session.commit()

    # Test with official support ID configured
    with patch.object(settings, "OFFICIAL_SUPPORT_GROUP_ID", official_group.conversation_id):
        with auth_patch(user_a):
            # List
            list_resp = await test_client.get("/api/v1/conversations?type=GROUP")
            assert list_resp.status_code == 200
            items = list_resp.json()["items"]

            item_map = {item["conversation_id"]: item for item in items}
            assert item_map[official_group.conversation_id]["is_official_support"] is True
            assert item_map[ordinary_group.conversation_id]["is_official_support"] is False
            # Crucial: Title matching does NOT make impostor official
            assert item_map[impostor_group.conversation_id]["is_official_support"] is False

            # Detail
            detail_official = await test_client.get(f"/api/v1/conversations/{official_group.conversation_id}")
            assert detail_official.status_code == 200
            assert detail_official.json()["is_official_support"] is True

            detail_ordinary = await test_client.get(f"/api/v1/conversations/{ordinary_group.conversation_id}")
            assert detail_ordinary.status_code == 200
            assert detail_ordinary.json()["is_official_support"] is False


@pytest.mark.asyncio
async def test_official_support_missing_config_fails_gracefully(
    test_client: AsyncClient, user_a: User, db_session: AsyncSession
):
    """When OFFICIAL_SUPPORT_GROUP_ID is None, groups continue to work and is_official_support is False."""
    group = Conversation(
        type="GROUP",
        title="Nhóm Thử Nghiệm",
    )
    db_session.add(group)
    await db_session.flush()
    m = ConversationMember(
        conversation_id=group.conversation_id,
        user_id=user_a.user_id,
        role="MEMBER",
    )
    db_session.add(m)
    await db_session.commit()

    with patch.object(settings, "OFFICIAL_SUPPORT_GROUP_ID", None):
        with auth_patch(user_a):
            list_resp = await test_client.get("/api/v1/conversations?type=GROUP")
            assert list_resp.status_code == 200
            items = list_resp.json()["items"]
            assert len(items) >= 1
            assert all(item["is_official_support"] is False for item in items)


@pytest.mark.asyncio
async def test_official_support_join_idempotent_and_chat(
    test_client: AsyncClient, user_a: User, db_session: AsyncSession
):
    """POST /official-support/join is idempotent and group supports normal messaging."""
    support_group = Conversation(
        type="GROUP",
        title="Cộng đồng Chợ PTITers",
    )
    db_session.add(support_group)
    await db_session.commit()

    with patch.object(settings, "OFFICIAL_SUPPORT_GROUP_ID", support_group.conversation_id):
        with auth_patch(user_a):
            # Join call 1
            r1 = await test_client.post("/api/v1/conversations/official-support/join")
            assert r1.status_code == 200
            data1 = r1.json()
            assert data1["conversation_id"] == support_group.conversation_id

            # Join call 2 (idempotent)
            r2 = await test_client.post("/api/v1/conversations/official-support/join")
            assert r2.status_code == 200
            data2 = r2.json()
            assert data2["conversation_id"] == support_group.conversation_id

            # Normal message sending works
            msg_resp = await test_client.post(
                f"/api/v1/conversations/{support_group.conversation_id}/messages",
                json={"content": "Chào cộng đồng PTITers!"},
            )
            assert msg_resp.status_code == 201


# =========================================================================
# 4. Group List Keyset Pagination and Official Group Pinning Tests
# =========================================================================

@pytest.mark.asyncio
async def test_group_pinning_and_pagination_no_duplicates(
    test_client: AsyncClient, user_a: User, db_session: AsyncSession
):
    """Test that official group is pinned first on page 1, and never duplicated on page 2+."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Create official group with an older timestamp
    official_group = Conversation(
        type="GROUP",
        title="Cộng đồng Chợ PTITers",
        created_at=now - timedelta(days=10),
        last_message_at=now - timedelta(days=5),
    )
    db_session.add(official_group)
    await db_session.flush()

    # Create 3 ordinary groups with newer timestamps
    ord_groups = []
    for i in range(3):
        g = Conversation(
            type="GROUP",
            title=f"Ordinary Group {i + 1}",
            created_at=now - timedelta(hours=i + 1),
            last_message_at=now - timedelta(hours=i + 1),
        )
        db_session.add(g)
        ord_groups.append(g)
    await db_session.flush()

    # Add user_a to all
    for g in [official_group] + ord_groups:
        db_session.add(
            ConversationMember(
                conversation_id=g.conversation_id,
                user_id=user_a.user_id,
                role="MEMBER",
            )
        )
    await db_session.commit()

    with patch.object(settings, "OFFICIAL_SUPPORT_GROUP_ID", official_group.conversation_id):
        with auth_patch(user_a):
            # Page 1 with limit=2
            p1_resp = await test_client.get("/api/v1/conversations?type=GROUP&limit=2")
            assert p1_resp.status_code == 200
            p1_data = p1_resp.json()
            p1_items = p1_data["items"]
            assert len(p1_items) == 2

            # First item on Page 1 must be the official support group!
            assert p1_items[0]["conversation_id"] == official_group.conversation_id
            assert p1_items[0]["is_official_support"] is True

            # Second item is the most recent ordinary group (Ordinary Group 1)
            assert p1_items[1]["conversation_id"] == ord_groups[0].conversation_id
            assert p1_items[1]["is_official_support"] is False

            # Page 2 using cursor
            cursor = p1_data["next_cursor"]
            assert cursor is not None

            p2_resp = await test_client.get(f"/api/v1/conversations?type=GROUP&limit=2&cursor={cursor}")
            assert p2_resp.status_code == 200
            p2_data = p2_resp.json()
            p2_items = p2_data["items"]

            # Must contain Ordinary Group 2 and Ordinary Group 3
            p2_ids = [item["conversation_id"] for item in p2_items]
            assert ord_groups[1].conversation_id in p2_ids
            assert ord_groups[2].conversation_id in p2_ids

            # CRITICAL: Official group must NOT be duplicated on Page 2!
            assert official_group.conversation_id not in p2_ids

            # Verify no duplicates across all pages
            all_received_ids = [item["conversation_id"] for item in p1_items] + p2_ids
            assert len(all_received_ids) == len(set(all_received_ids)), "Found duplicate conversation across pages!"
