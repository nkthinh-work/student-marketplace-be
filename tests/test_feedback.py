import asyncio
import io
from unittest.mock import patch, MagicMock, AsyncMock
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.main import app
from app.modules.auth.dependencies import get_current_active_user, require_admin, get_admin_for_evidence
from app.modules.feedback.models import SiteFeedback, SiteFeedbackAttachment
from app.modules.users.models import User, UserAuthIdentity, UserRole, UserStatus

# Valid media signatures
VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00" + b"\x00" * 100
VALID_PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4" + b"\x00" * 100
VALID_WEBP_BYTES = b"RIFF" + (100).to_bytes(4, "little") + b"WEBPVP8 " + b"\x00" * 80
VALID_MP4_BYTES = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 100
VALID_WEBM_BYTES = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81\x01" + b"\x00" * 100


@pytest_asyncio.fixture
async def feedback_test_users(db_session: AsyncSession):
    student1 = User(
        email=f"fb_student1_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Nguyễn Khắc Thịnh",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    student2 = User(
        email=f"fb_student2_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Trần Thị Sinh Viên",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    banned = User(
        email=f"fb_banned_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Người Dùng Bị Khóa",
        role=UserRole.STUDENT.value,
        status=UserStatus.BANNED,
    )
    admin = User(
        email=f"fb_admin_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Quản Trị Viên",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    creator = User(
        email=f"fb_creator_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Nguyễn Khắc Thịnh - Admin1",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(creator)
    await db_session.flush()

    creator_uid = f"fb_creator_uid_{uuid.uuid4().hex[:8]}"
    creator_ident = UserAuthIdentity(
        user_id=creator.user_id,
        provider="FIREBASE",
        provider_uid=creator_uid,
    )
    db_session.add(creator_ident)

    db_session.add_all([student1, student2, banned, admin])
    await db_session.flush()
    return {
        "student1": student1,
        "student2": student2,
        "banned": banned,
        "admin": admin,
        "creator": creator,
        "creator_uid": creator_uid,
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
            app.dependency_overrides[get_admin_for_evidence] = lambda: admin
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            app.dependency_overrides.pop(require_admin, None)
            app.dependency_overrides.pop(get_admin_for_evidence, None)

    return OverrideAdminContext()


# ======================================================================
# 1. CREATE & VALIDATION TESTS
# ======================================================================

@pytest.mark.asyncio
async def test_feedback_submit_unauthenticated(test_client: AsyncClient):
    res = await test_client.post(
        "/api/v1/feedback",
        data={"content": "Lỗi khi bấm thanh toán."},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_feedback_submit_banned_user(test_client: AsyncClient, feedback_test_users: dict):
    banned = feedback_test_users["banned"]
    with override_user(banned):
        res = await test_client.post(
            "/api/v1/feedback",
            data={"content": "Lỗi khi bấm thanh toán."},
        )
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_feedback_submit_text_only_success(test_client: AsyncClient, feedback_test_users: dict):
    student1 = feedback_test_users["student1"]
    with override_user(student1):
        res = await test_client.post(
            "/api/v1/feedback",
            data={"content": "Không thể bấm đặt giá khi bàn phím đang mở."},
        )
        assert res.status_code == 201
        data = res.json()
        assert data["content"] == "Không thể bấm đặt giá khi bàn phím đang mở."
        assert data["feedback_id"] > 0
        assert data["attachments"] == []

    # Immediately visible publicly
    pub_res = await test_client.get("/api/v1/feedback")
    assert pub_res.status_code == 200
    pub_data = pub_res.json()
    assert any(item["feedback_id"] == data["feedback_id"] for item in pub_data["items"])


@pytest.mark.asyncio
async def test_feedback_content_length_validation(test_client: AsyncClient, feedback_test_users: dict):
    student1 = feedback_test_users["student1"]
    with override_user(student1):
        # Too short (< 5)
        res1 = await test_client.post("/api/v1/feedback", data={"content": "abc"})
        assert res1.status_code in (400, 422)

        # Whitespace only (< 5)
        res2 = await test_client.post("/api/v1/feedback", data={"content": "   abcd   "})
        assert res2.status_code in (400, 422)

        # Too long (> 500)
        res3 = await test_client.post("/api/v1/feedback", data={"content": "A" * 501})
        assert res3.status_code in (400, 422)


@pytest.mark.asyncio
async def test_feedback_with_valid_attachments(test_client: AsyncClient, feedback_test_users: dict):
    student1 = feedback_test_users["student1"]

    with patch("app.modules.feedback.service.upload_feedback_attachment") as mock_upload:
        mock_upload.side_effect = [
            {"public_id": "img1", "secure_url": "https://res.cloudinary.com/demo/image/upload/img1.jpg"},
            {"public_id": "img2", "secure_url": "https://res.cloudinary.com/demo/image/upload/img2.png"},
            {"public_id": "vid1", "secure_url": "https://res.cloudinary.com/demo/video/upload/vid1.mp4", "duration": 25.5},
        ]

        files = [
            ("images", ("test1.jpg", VALID_JPEG_BYTES, "image/jpeg")),
            ("images", ("test2.png", VALID_PNG_BYTES, "image/png")),
            ("video", ("test_video.mp4", VALID_MP4_BYTES, "video/mp4")),
        ]

        with override_user(student1):
            res = await test_client.post(
                "/api/v1/feedback",
                data={"content": "Nút gửi tin nhắn bị che khuất trên màn hình nhỏ."},
                files=files,
            )
            assert res.status_code == 201
            data = res.json()
            assert len(data["attachments"]) == 3
            kinds = [a["kind"] for a in data["attachments"]]
            assert kinds == ["IMAGE", "IMAGE", "VIDEO"]
            assert data["attachments"][2]["duration_ms"] == 25500


@pytest.mark.asyncio
async def test_feedback_attachment_quantity_limits(test_client: AsyncClient, feedback_test_users: dict):
    student1 = feedback_test_users["student1"]
    with override_user(student1):
        # 4 images (exceeds max 3)
        files = [
            ("images", (f"img_{i}.jpg", VALID_JPEG_BYTES, "image/jpeg"))
            for i in range(4)
        ]
        res = await test_client.post(
            "/api/v1/feedback",
            data={"content": "Báo cáo lỗi giao diện nhiều ảnh."},
            files=files,
        )
        assert res.status_code == 422
        assert "3" in res.json()["detail"]


@pytest.mark.asyncio
async def test_feedback_invalid_magic_bytes(test_client: AsyncClient, feedback_test_users: dict):
    student1 = feedback_test_users["student1"]
    with override_user(student1):
        # An executable or fake text masquerading as image
        fake_files = [
            ("images", ("malicious.jpg", b"MZ\x90\x00\x03\x00\x00\x00fakeexe", "image/jpeg")),
        ]
        res = await test_client.post(
            "/api/v1/feedback",
            data={"content": "Thử upload file thực thi độc hại."},
            files=fake_files,
        )
        assert res.status_code == 422


@pytest.mark.asyncio
async def test_feedback_video_duration_exceeded(test_client: AsyncClient, feedback_test_users: dict):
    student1 = feedback_test_users["student1"]
    with patch("app.modules.feedback.service.upload_feedback_attachment") as mock_upload, \
         patch("app.modules.feedback.service.destroy_asset") as mock_destroy:
        mock_upload.return_value = {
            "public_id": "vid_long",
            "secure_url": "https://res.cloudinary.com/demo/video/upload/vid_long.mp4",
            "duration": 65.0,  # > 60s
        }

        with override_user(student1):
            res = await test_client.post(
                "/api/v1/feedback",
                data={"content": "Video ghi lại quá trình thao tác."},
                files=[("video", ("video.mp4", VALID_MP4_BYTES, "video/mp4"))],
            )
            assert res.status_code == 422
            assert "60" in res.json()["detail"]
            # Verify compensation destroyed uploaded asset
            mock_destroy.assert_called_once_with("vid_long", resource_type="video")


# ======================================================================
# 2. MULTIPLE FEEDBACKS PER USER (NO UNIQUE CONSTRAINT)
# ======================================================================

@pytest.mark.asyncio
async def test_multiple_feedbacks_per_user(test_client: AsyncClient, feedback_test_users: dict):
    student1 = feedback_test_users["student1"]
    with override_user(student1):
        res1 = await test_client.post(
            "/api/v1/feedback",
            data={"content": "Góp ý lần 1: Giao diện tìm kiếm cần cải thiện."},
        )
        assert res1.status_code == 201
        fb1_id = res1.json()["feedback_id"]

        res2 = await test_client.post(
            "/api/v1/feedback",
            data={"content": "Góp ý lần 2: Không thấy thông báo đẩy."},
        )
        assert res2.status_code == 201
        fb2_id = res2.json()["feedback_id"]

        assert fb1_id != fb2_id

        # Check user's feedbacks list
        my_res = await test_client.get("/api/v1/feedback/me")
        assert my_res.status_code == 200
        my_items = my_res.json()["items"]
        my_ids = [item["feedback_id"] for item in my_items]
        assert fb1_id in my_ids
        assert fb2_id in my_ids


# ======================================================================
# 3. PUBLIC FEED & PRIVACY TESTS
# ======================================================================

@pytest.mark.asyncio
async def test_public_feed_anonymity_and_isolation(test_client: AsyncClient, feedback_test_users: dict):
    student1 = feedback_test_users["student1"]
    with override_user(student1):
        res = await test_client.post(
            "/api/v1/feedback",
            data={"content": "Kiểm tra tính ẩn danh của phản hồi công khai."},
        )
        assert res.status_code == 201
        fb_id = res.json()["feedback_id"]

    # Public user fetches feed
    pub_res = await test_client.get("/api/v1/feedback")
    assert pub_res.status_code == 200
    items = pub_res.json()["items"]
    target = next((item for item in items if item["feedback_id"] == fb_id), None)
    assert target is not None

    # Verify ONLY feedback_id, content, created_at exist
    expected_keys = {"feedback_id", "content", "created_at"}
    assert set(target.keys()) == expected_keys
    assert "user_id" not in target
    assert "full_name" not in target
    assert "avatar_url" not in target
    assert "attachments" not in target
    assert "rating" not in target
    assert "status" not in target


# ======================================================================
# 4. HARD DELETE TESTS (USER & ADMIN)
# ======================================================================

@pytest.mark.asyncio
async def test_user_delete_own_feedback(test_client: AsyncClient, feedback_test_users: dict):
    student1 = feedback_test_users["student1"]
    student2 = feedback_test_users["student2"]

    with patch("app.modules.feedback.service.upload_feedback_attachment") as mock_upload, \
         patch("app.modules.feedback.service.destroy_asset") as mock_destroy:
        mock_upload.return_value = {
            "public_id": "img_to_delete",
            "secure_url": "https://res.cloudinary.com/demo/image/upload/img_to_delete.jpg",
        }

        with override_user(student1):
            create_res = await test_client.post(
                "/api/v1/feedback",
                data={"content": "Phản hồi sắp bị xóa bởi chính tác giả."},
                files=[("images", ("test.jpg", VALID_JPEG_BYTES, "image/jpeg"))],
            )
            assert create_res.status_code == 201
            fb_id = create_res.json()["feedback_id"]

        # Other user tries to delete -> 404
        with override_user(student2):
            del_other = await test_client.delete(f"/api/v1/feedback/{fb_id}")
            assert del_other.status_code == 404

        # Owner deletes -> 204
        with override_user(student1):
            del_res = await test_client.delete(f"/api/v1/feedback/{fb_id}")
            assert del_res.status_code == 204
            mock_destroy.assert_called_with("img_to_delete", resource_type="image")

        # Now public feed does not have it
        pub_res = await test_client.get("/api/v1/feedback")
        assert not any(item["feedback_id"] == fb_id for item in pub_res.json()["items"])


@pytest.mark.asyncio
async def test_admin_inspect_and_delete(test_client: AsyncClient, feedback_test_users: dict):
    student1 = feedback_test_users["student1"]
    admin = feedback_test_users["admin"]

    with patch("app.modules.feedback.service.upload_feedback_attachment") as mock_upload, \
         patch("app.modules.feedback.service.destroy_asset") as mock_destroy:
        mock_upload.return_value = {
            "public_id": "admin_test_img",
            "secure_url": "https://res.cloudinary.com/demo/image/upload/admin_test_img.jpg",
        }

        with override_user(student1):
            create_res = await test_client.post(
                "/api/v1/feedback",
                data={"content": "Admin kiểm tra phản hồi này."},
                files=[("images", ("test.jpg", VALID_JPEG_BYTES, "image/jpeg"))],
            )
            assert create_res.status_code == 201
            fb_id = create_res.json()["feedback_id"]

        # Student cannot call admin endpoints
        with override_user(student1):
            assert (await test_client.get("/api/v1/admin/feedback")).status_code == 403
            assert (await test_client.get(f"/api/v1/admin/feedback/{fb_id}")).status_code == 403
            assert (await test_client.delete(f"/api/v1/admin/feedback/{fb_id}")).status_code == 403

        # Admin lists feedbacks
        with override_admin(admin):
            admin_list_res = await test_client.get("/api/v1/admin/feedback")
            assert admin_list_res.status_code == 200
            admin_items = admin_list_res.json()["items"]
            item = next(i for i in admin_items if i["feedback_id"] == fb_id)
            assert item["sender"]["user_id"] == student1.user_id
            assert item["sender"]["full_name"] == student1.full_name
            assert item["image_count"] == 1
            assert item["video_count"] == 0

            # Admin gets detail
            detail_res = await test_client.get(f"/api/v1/admin/feedback/{fb_id}")
            assert detail_res.status_code == 200
            detail = detail_res.json()
            assert len(detail["attachments"]) == 1
            assert "evidence" in detail["attachments"][0]["stream_url"]

            # Admin deletes
            admin_del_res = await test_client.delete(f"/api/v1/admin/feedback/{fb_id}")
            assert admin_del_res.status_code == 204
            mock_destroy.assert_called_with("admin_test_img", resource_type="image")


@pytest.mark.asyncio
async def test_admin_feedback_evidence_streaming(test_client: AsyncClient, feedback_test_users: dict):
    student1 = feedback_test_users["student1"]
    admin = feedback_test_users["admin"]

    with patch("app.modules.feedback.service.upload_feedback_attachment") as mock_upload:
        mock_upload.return_value = {
            "public_id": "stream_test_img",
            "secure_url": "https://res.cloudinary.com/demo/image/upload/stream_test_img.jpg",
        }

        with override_user(student1):
            create_res = await test_client.post(
                "/api/v1/feedback",
                data={"content": "Minh chứng cần được stream an toàn cho Admin."},
                files=[("images", ("test.jpg", VALID_JPEG_BYTES, "image/jpeg"))],
            )
            assert create_res.status_code == 201
            fb_id = create_res.json()["feedback_id"]

    with override_admin(admin):
        detail_res = await test_client.get(f"/api/v1/admin/feedback/{fb_id}")
        att_id = detail_res.json()["attachments"][0]["attachment_id"]

    # 1. Unauthenticated -> 401
    unauth_res = await test_client.get(f"/api/v1/admin/feedback/{fb_id}/evidence/{att_id}")
    assert unauth_res.status_code == 401

    # 2. Non-admin -> 403
    with override_user(student1):
        forbid_res = await test_client.get(f"/api/v1/admin/feedback/{fb_id}/evidence/{att_id}")
        assert forbid_res.status_code == 403

    # Mock httpx response for upstream Cloudinary streaming
    async def fake_stream():
        yield VALID_JPEG_BYTES

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "image/jpeg", "content-length": str(len(VALID_JPEG_BYTES))}
    mock_resp.aiter_bytes = lambda chunk_size=65536: fake_stream()
    mock_resp.aclose = AsyncMock()

    mock_client = AsyncMock()
    mock_client.build_request = MagicMock(return_value=MagicMock())
    mock_client.send = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    # 3. Admin streaming via Bearer auth
    with override_admin(admin):
        with patch("httpx.AsyncClient", return_value=mock_client):
            stream_res = await test_client.get(f"/api/v1/admin/feedback/{fb_id}/evidence/{att_id}")
            assert stream_res.status_code == 200
            assert stream_res.headers["content-type"] == "image/jpeg"

    # 4. Admin streaming via ?token= query param
    with patch("app.modules.auth.dependencies.authenticate_user_token", return_value=admin):
        with patch("httpx.AsyncClient", return_value=mock_client):
            token_res = await test_client.get(f"/api/v1/admin/feedback/{fb_id}/evidence/{att_id}?token=valid_admin_token")
            assert token_res.status_code == 200
            assert token_res.headers["content-type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_concurrent_delete_safety(test_client: AsyncClient, feedback_test_users: dict):
    student1 = feedback_test_users["student1"]
    admin = feedback_test_users["admin"]

    with override_user(student1):
        res = await test_client.post(
            "/api/v1/feedback",
            data={"content": "Thử nghiệm xóa đồng thời."},
        )
        fb_id = res.json()["feedback_id"]

    # Delete 1: user deletes
    with override_user(student1):
        r1 = await test_client.delete(f"/api/v1/feedback/{fb_id}")
        assert r1.status_code == 204

    # Delete 2: admin deletes already-deleted
    with override_admin(admin):
        r2 = await test_client.delete(f"/api/v1/admin/feedback/{fb_id}")
        assert r2.status_code == 404


# ======================================================================
# 5. CREATOR & SUPPORT PROFILE TESTS
# ======================================================================

@pytest.mark.asyncio
async def test_support_info_endpoint_resolved_by_provider_uid(
    test_client: AsyncClient, feedback_test_users: dict, monkeypatch
):
    creator = feedback_test_users["creator"]
    creator_uid = feedback_test_users["creator_uid"]
    monkeypatch.setattr(settings, "COMMUNITY_CREATOR_PROVIDER_UID", creator_uid)
    monkeypatch.setattr(settings, "COMMUNITY_CREATOR_EMAIL", None)

    res = await test_client.get("/api/v1/feedback/support")
    assert res.status_code == 200
    data = res.json()
    assert data["fixed_qr_url"] == "/support/nguyen-khac-thinh-vietqr.png"
    assert data["support_message"] == "Quan trọng là tấm lòng 💛"
    assert data["creator"] is not None
    assert data["creator"]["user_id"] == creator.user_id
    assert data["creator"]["full_name"] == creator.full_name
    assert data["creator"]["title"] == "Người phát triển Chợ PTITers"
    assert data["profile_path"] == f"/users/{creator.user_id}"
    # Never expose email or provider_uid
    assert "email" not in str(data)
    assert creator_uid not in str(data)


@pytest.mark.asyncio
async def test_support_info_endpoint_resolved_by_email_fallback(
    test_client: AsyncClient, feedback_test_users: dict, monkeypatch
):
    creator = feedback_test_users["creator"]
    monkeypatch.setattr(settings, "COMMUNITY_CREATOR_PROVIDER_UID", None)
    monkeypatch.setattr(settings, "COMMUNITY_CREATOR_EMAIL", creator.email)

    res = await test_client.get("/api/v1/feedback/support")
    assert res.status_code == 200
    data = res.json()
    assert data["creator"] is not None
    assert data["creator"]["user_id"] == creator.user_id
    assert data["profile_path"] == f"/users/{creator.user_id}"


@pytest.mark.asyncio
async def test_support_info_endpoint_unconfigured_produces_safe_controlled_response(
    test_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "COMMUNITY_CREATOR_PROVIDER_UID", None)
    monkeypatch.setattr(settings, "COMMUNITY_CREATOR_EMAIL", None)

    res = await test_client.get("/api/v1/feedback/support")
    assert res.status_code == 200
    data = res.json()
    assert data["fixed_qr_url"] == "/support/nguyen-khac-thinh-vietqr.png"
    assert data["support_message"] == "Quan trọng là tấm lòng 💛"
    assert data["creator"] is None
    assert data["profile_path"] is None


@pytest.mark.asyncio
async def test_support_info_endpoint_unresolvable_uid_produces_safe_controlled_response(
    test_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "COMMUNITY_CREATOR_PROVIDER_UID", "non_existent_firebase_uid_99999")
    monkeypatch.setattr(settings, "COMMUNITY_CREATOR_EMAIL", None)

    res = await test_client.get("/api/v1/feedback/support")
    assert res.status_code == 200
    data = res.json()
    assert data["creator"] is None
    assert data["profile_path"] is None
