import pytest
from unittest.mock import patch
from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.main import app
from app.integrations.firebase import FirebaseVerificationError, FirebaseNotInitializedError
from app.modules.auth.dependencies import (
    get_current_active_user,
    require_admin,
    require_role,
)
from app.modules.users.models import User, UserAuthIdentity, UserStatus, UserRole
from app.modules.users.schemas import UserResponse

# Test router cho role authorization
admin_test_router = APIRouter(prefix="/test-admin", tags=["Test"])


@admin_test_router.get("/admin-only")
async def admin_only_endpoint(admin_user: User = Depends(require_admin)):
    return {"message": f"Hello Admin {admin_user.full_name}"}


app.include_router(admin_test_router)


@pytest.mark.asyncio
async def test_missing_authorization_header(test_client):
    response = await test_client.get("/api/v1/users/me")
    assert response.status_code == 401
    assert "Missing or invalid Authorization header" in response.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_authorization_header_format(test_client):
    response = await test_client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Basic 12345"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_or_expired_token(test_client):
    with patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        side_effect=FirebaseVerificationError("Firebase token has expired."),
    ):
        response = await test_client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer expired_token"},
        )
        assert response.status_code == 401
        assert "Firebase token has expired." in response.json()["detail"]


@pytest.mark.asyncio
async def test_unconfigured_firebase(test_client):
    with patch(
        "app.modules.auth.dependencies.verify_firebase_token",
        side_effect=FirebaseNotInitializedError("Firebase Authentication service is not initialized."),
    ):
        response = await test_client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer some_token"},
        )
        assert response.status_code == 503
        assert "unavailable" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_first_login_provisions_user_and_identity_atomically(test_client, db_session):
    mock_claims = {
        "uid": "fb_test_alice_001",
        "email": "alice@student.edu.vn",
        "name": "Alice Nguyen",
        "picture": "https://avatar.example.com/alice.jpg",
    }

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value=mock_claims):
        response = await test_client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer valid_alice_token"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["email"] == "alice@student.edu.vn"
        assert data["full_name"] == "Alice Nguyen"
        assert data["avatar_url"] == "https://avatar.example.com/alice.jpg"
        assert data["role"] == "STUDENT"
        assert data["status"] == "ACTIVE"
        assert "user_id" in data
        assert "provider_uid" not in data  # Không leak provider_uid của identity bên thứ 3

        user_id = data["user_id"]

        user_stmt = select(User).where(User.user_id == user_id)
        user_res = await db_session.execute(user_stmt)
        user_in_db = user_res.scalar_one_or_none()
        assert user_in_db is not None
        assert user_in_db.email == "alice@student.edu.vn"

        ident_stmt = select(UserAuthIdentity).where(UserAuthIdentity.user_id == user_id)
        ident_res = await db_session.execute(ident_stmt)
        ident_in_db = ident_res.scalar_one_or_none()
        assert ident_in_db is not None
        assert ident_in_db.provider == "FIREBASE"
        assert ident_in_db.provider_uid == "fb_test_alice_001"


@pytest.mark.asyncio
async def test_existing_user_resolution(test_client, db_session):
    mock_claims = {
        "uid": "fb_test_bob_002",
        "email": "bob@student.edu.vn",
        "name": "Bob Tran",
    }

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value=mock_claims):
        res1 = await test_client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer valid_bob_token"},
        )
        assert res1.status_code == 200
        user_id_1 = res1.json()["user_id"]

        res2 = await test_client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer valid_bob_token"},
        )
        assert res2.status_code == 200
        user_id_2 = res2.json()["user_id"]

        assert user_id_1 == user_id_2

        user_stmt = select(User).where(User.email == "bob@student.edu.vn")
        user_res = await db_session.execute(user_stmt)
        all_bobs = user_res.scalars().all()
        assert len(all_bobs) == 1


@pytest.mark.asyncio
async def test_client_supplied_uid_ignored(test_client):
    """
    Ensure client-supplied fake parameters in query/body/header do NOT override verified token UID.
    """
    mock_claims = {
        "uid": "fb_real_charlie_003",
        "email": "charlie@student.edu.vn",
        "name": "Charlie Le",
    }

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value=mock_claims):
        # Client cố tình giả mạo user khác qua param/header
        response = await test_client.get(
            "/api/v1/users/me?uid=fake_attacker_uid&user_id=1&role=ADMIN",
            headers={
                "Authorization": "Bearer valid_charlie_token",
                "X-User-Id": "1",
                "X-Role": "ADMIN",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "charlie@student.edu.vn"
        assert data["role"] == "STUDENT"


@pytest.mark.asyncio
async def test_user_status_banned_and_inactive(test_client, db_session):
    mock_claims = {
        "uid": "fb_test_david_004",
        "email": "david@student.edu.vn",
        "name": "David Pham",
    }

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value=mock_claims):
        res = await test_client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer token_david"},
        )
        assert res.status_code == 200
        user_id = res.json()["user_id"]

        user_stmt = select(User).where(User.user_id == user_id)
        user_res = await db_session.execute(user_stmt)
        user = user_res.scalar_one()
        user.status = UserStatus.BANNED
        await db_session.commit()

        banned_res = await test_client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer token_david"},
        )
        assert banned_res.status_code == 403
        assert "banned" in banned_res.json()["detail"].lower()

        user.status = UserStatus.INACTIVE
        await db_session.commit()

        inactive_res = await test_client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer token_david"},
        )
        assert inactive_res.status_code == 403
        assert "inactive" in inactive_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_profile_valid_fields(test_client, db_session):
    mock_claims = {
        "uid": "fb_test_eva_005",
        "email": "eva@student.edu.vn",
        "name": "Eva Vu",
    }

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value=mock_claims):
        await test_client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer token_eva"},
        )

        update_payload = {
            "full_name": "Eva Vu Updated",
            "phone": "0912345678",
            "avatar_url": "https://avatar.example.com/eva_new.jpg",
            "bio": "Sophomore at Computer Science",
            "default_meetup_area": "Hall B, Campus 1",
        }

        patch_res = await test_client.patch(
            "/api/v1/users/me",
            json=update_payload,
            headers={"Authorization": "Bearer token_eva"},
        )
        assert patch_res.status_code == 200
        data = patch_res.json()
        assert data["full_name"] == "Eva Vu Updated"
        assert data["phone"] == "0912345678"
        assert data["avatar_url"] == "https://avatar.example.com/eva_new.jpg"
        assert data["bio"] == "Sophomore at Computer Science"
        assert data["default_meetup_area"] == "Hall B, Campus 1"


@pytest.mark.asyncio
async def test_patch_profile_forbidden_and_invalid_fields(test_client, db_session):
    mock_claims = {
        "uid": "fb_test_frank_006",
        "email": "frank@student.edu.vn",
        "name": "Frank Do",
    }

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value=mock_claims):
        await test_client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer token_frank"},
        )

        patch_res = await test_client.patch(
            "/api/v1/users/me",
            json={"role": "ADMIN", "status": "ACTIVE"},
            headers={"Authorization": "Bearer token_frank"},
        )
        assert patch_res.status_code == 422

        invalid_len_res = await test_client.patch(
            "/api/v1/users/me",
            json={"phone": "1234567890123456789012345"},  # max 20
            headers={"Authorization": "Bearer token_frank"},
        )
        assert invalid_len_res.status_code == 422


@pytest.mark.asyncio
async def test_role_authorization_admin_dependency(test_client, db_session):
    mock_student = {
        "uid": "fb_test_student_007",
        "email": "student@student.edu.vn",
        "name": "Normal Student",
    }
    mock_admin = {
        "uid": "fb_test_admin_008",
        "email": "admin@student.edu.vn",
        "name": "Admin Officer",
    }

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value=mock_student):
        res = await test_client.get(
            "/test-admin/admin-only",
            headers={"Authorization": "Bearer token_student"},
        )
        assert res.status_code == 403
        assert "not permitted" in res.json()["detail"].lower()

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value=mock_admin):
        res = await test_client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer token_admin"},
        )
        user_id = res.json()["user_id"]

        user_stmt = select(User).where(User.user_id == user_id)
        user_res = await db_session.execute(user_stmt)
        user = user_res.scalar_one()
        user.role = UserRole.ADMIN.value
        await db_session.commit()

        admin_res = await test_client.get(
            "/test-admin/admin-only",
            headers={"Authorization": "Bearer token_admin"},
        )
        assert admin_res.status_code == 200
        assert "Hello Admin Admin Officer" in admin_res.json()["message"]


@pytest.mark.asyncio
async def test_first_login_without_email_or_name(test_client, db_session):
    mock_claims = {
        "uid": "fb_phone_user_009",
    }

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value=mock_claims):
        response = await test_client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer token_phone_user"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "fb_phone_user_009@firebase.user"
        assert data["full_name"] == "fb_phone_user_009"
        assert data["role"] == "STUDENT"
        assert data["status"] == "ACTIVE"
