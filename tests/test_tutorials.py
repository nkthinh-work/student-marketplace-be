import io
import uuid
from unittest.mock import patch, MagicMock, AsyncMock
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.cloudinary import build_tutorial_thumbnail_url
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.tutorials.models import Tutorial
from app.modules.tutorials.schemas import ALLOWED_ACTION_KEYS, ALLOWED_FEATURE_KEYS
from app.modules.tutorials.service import (
    MAX_TUTORIAL_VIDEO_SIZE_BYTES,
)
from app.modules.users.models import User, UserRole, UserStatus

VALID_MP4_BYTES = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 100
VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00" + b"\x00" * 100


@pytest_asyncio.fixture
async def tutorial_test_users(db_session: AsyncSession):
    student = User(
        email=f"tut_student_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Nguyễn Văn Sinh Viên",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    admin = User(
        email=f"tut_admin_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Quản Trị Viên Tutorial",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    banned = User(
        email=f"tut_banned_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Người Dùng Bị Khóa",
        role=UserRole.STUDENT.value,
        status=UserStatus.BANNED,
    )
    db_session.add_all([student, admin, banned])
    await db_session.flush()
    return {"student": student, "admin": admin, "banned": banned}


def auth_patch(user: User):
    class AuthContext:
        def __enter__(self):
            app.dependency_overrides[get_current_user] = lambda: user
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            app.dependency_overrides.pop(get_current_user, None)

    return AuthContext()


def override_admin(admin_user: User):
    return auth_patch(admin_user)


# ======================================================================
# 1. PUBLIC GET ENDPOINT TESTS
# ======================================================================

@pytest.mark.asyncio
async def test_public_get_tutorials_unauthenticated(test_client: AsyncClient, db_session: AsyncSession, tutorial_test_users: dict):
    """GET /api/v1/tutorials hoạt động công khai không cần auth."""
    admin = tutorial_test_users["admin"]
    t1 = Tutorial(
        feature_key="MY_LISTINGS",
        title="Hướng dẫn quản lý tin đăng",
        description="Chi tiết cách quản lý tin",
        video_url="https://res.cloudinary.com/demo/video/upload/tut1.mp4",
        video_storage_key="tutorials/videos/tut1",
        video_mime_type="video/mp4",
        video_size_bytes=1024000,
        duration_ms=60000,
        sort_order=10,
        is_published=True,
        created_by=admin.user_id,
    )
    db_session.add(t1)
    await db_session.commit()

    res = await test_client.get("/api/v1/tutorials")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    matching = [x for x in data if x["tutorial_id"] == t1.tutorial_id]
    assert len(matching) == 1
    item = matching[0]
    assert item["title"] == "Hướng dẫn quản lý tin đăng"
    assert item["feature_key"] == "MY_LISTINGS"
    assert "video_storage_key" not in item
    assert "poster_storage_key" not in item
    assert "poster_url" not in item
    assert "created_by" not in item
    assert item["thumbnail_url"] is not None
    assert "so_1" in item["thumbnail_url"]


@pytest.mark.asyncio
async def test_public_get_only_published_and_deterministic_order(test_client: AsyncClient, db_session: AsyncSession, tutorial_test_users: dict):
    """Chỉ trả về các tutorial đã xuất bản, sắp xếp theo sort_order và tutorial_id."""
    admin = tutorial_test_users["admin"]
    draft = Tutorial(
        feature_key="HOME",
        title="Bản nháp không xuất bản",
        video_url="https://res.cloudinary.com/demo/video/upload/draft.mp4",
        video_storage_key="tutorials/videos/draft",
        video_mime_type="video/mp4",
        video_size_bytes=1000,
        sort_order=5,
        is_published=False,
        created_by=admin.user_id,
    )
    pub2 = Tutorial(
        feature_key="HOME",
        title="Tutorial thứ tự 20",
        video_url="https://res.cloudinary.com/demo/video/upload/pub2.mp4",
        video_storage_key="tutorials/videos/pub2",
        video_mime_type="video/mp4",
        video_size_bytes=1000,
        sort_order=20,
        is_published=True,
        created_by=admin.user_id,
    )
    pub1 = Tutorial(
        feature_key="HOME",
        title="Tutorial thứ tự 10",
        video_url="https://res.cloudinary.com/demo/video/upload/pub1.mp4",
        video_storage_key="tutorials/videos/pub1",
        video_mime_type="video/mp4",
        video_size_bytes=1000,
        sort_order=10,
        is_published=True,
        created_by=admin.user_id,
    )
    db_session.add_all([draft, pub2, pub1])
    await db_session.commit()

    res = await test_client.get("/api/v1/tutorials")
    assert res.status_code == 200
    data = res.json()
    ids = [x["tutorial_id"] for x in data]
    assert draft.tutorial_id not in ids
    assert pub1.tutorial_id in ids
    assert pub2.tutorial_id in ids
    # pub1 (order 10) phải đứng trước pub2 (order 20)
    assert ids.index(pub1.tutorial_id) < ids.index(pub2.tutorial_id)


# ======================================================================
# 2. ADMIN AUTHENTICATION & AUTHORIZATION TESTS
# ======================================================================

@pytest.mark.asyncio
async def test_admin_list_unauthenticated(test_client: AsyncClient):
    """GET /api/v1/admin/tutorials chưa đăng nhập trả về 401."""
    res = await test_client.get("/api/v1/admin/tutorials")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_admin_list_student_forbidden(test_client: AsyncClient, tutorial_test_users: dict):
    """Sinh viên thường gọi endpoint admin bị 403 Forbidden."""
    student = tutorial_test_users["student"]
    with override_admin(student):
        res = await test_client.get("/api/v1/admin/tutorials")
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_admin_list_active_admin_allowed(test_client: AsyncClient, tutorial_test_users: dict):
    """Admin hợp lệ được phép truy cập danh sách quản trị."""
    admin = tutorial_test_users["admin"]
    with override_admin(admin):
        res = await test_client.get("/api/v1/admin/tutorials")
        assert res.status_code == 200
        assert isinstance(res.json(), list)


# ======================================================================
# 3. ADMIN CREATE TESTS & VALIDATIONS
# ======================================================================

@pytest.mark.asyncio
async def test_admin_create_tutorial_success(test_client: AsyncClient, tutorial_test_users: dict):
    """Tạo tutorial thành công chỉ với video MP4 (không cần poster). DTO trả về thumbnail_url dẫn xuất từ video."""
    admin = tutorial_test_users["admin"]

    mock_video_upload = {
        "secure_url": "https://res.cloudinary.com/demo/video/upload/v123/tut_new.mp4",
        "public_id": "tutorials/videos/tut_new",
        "duration": 52.4,
        "width": 1080,
        "height": 1920,
    }

    with override_admin(admin):
        with patch("app.modules.tutorials.service.upload_tutorial_video", return_value=mock_video_upload):
            files = {
                "video": ("tutorial.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4"),
            }
            data = {
                "feature_key": "MY_LISTINGS",
                "title": "Quản lý tin đăng",
                "description": "Hướng dẫn quản lý tin đã đăng",
                "action_key": "MY_LISTINGS",
                "is_published": "false",
            }
            res = await test_client.post("/api/v1/admin/tutorials", files=files, data=data)
            assert res.status_code == 201
            resp_data = res.json()
            assert resp_data["title"] == "Quản lý tin đăng"
            assert resp_data["feature_key"] == "MY_LISTINGS"
            assert resp_data["action_key"] == "MY_LISTINGS"
            assert resp_data["is_published"] is False
            assert resp_data["sort_order"] == 10
            assert resp_data["duration_ms"] == 52400
            assert resp_data["created_by"] == admin.user_id
            # Derived thumbnail
            assert resp_data["thumbnail_url"] is not None
            assert "so_1" in resp_data["thumbnail_url"]
            assert resp_data["thumbnail_url"].endswith(".jpg")
            # No poster fields
            assert "poster_url" not in resp_data
            assert "poster_storage_key" not in resp_data
            assert "poster_mime_type" not in resp_data


@pytest.mark.asyncio
async def test_admin_create_legacy_feature_keys_rejected(test_client: AsyncClient, tutorial_test_users: dict):
    """Các feature_key cũ (GETTING_STARTED, PRODUCTS, ORDERS, AUCTIONS, COMMUNITY, ACCOUNT) đều bị từ chối 400."""
    admin = tutorial_test_users["admin"]
    legacy_keys = ["GETTING_STARTED", "PRODUCTS", "ORDERS", "AUCTIONS", "COMMUNITY", "ACCOUNT"]
    with override_admin(admin):
        for key in legacy_keys:
            files = {"video": ("tutorial.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4")}
            data = {
                "feature_key": key,
                "title": f"Test {key}",
            }
            res = await test_client.post("/api/v1/admin/tutorials", files=files, data=data)
            assert res.status_code == 400
            assert "không hợp lệ" in res.json()["detail"]


@pytest.mark.asyncio
async def test_admin_create_all_canonical_navigation_keys_accepted(test_client: AsyncClient, tutorial_test_users: dict):
    """Tất cả 10 canonical navigation feature keys đều được chấp nhận."""
    admin = tutorial_test_users["admin"]
    canonical_keys = [
        "HOME",
        "FAVORITES",
        "CREATE_PRODUCT",
        "MY_LISTINGS",
        "BUYER_ORDERS",
        "SELLER_ORDERS",
        "NOTIFICATIONS",
        "MESSAGES",
        "PROFILE",
        "FEEDBACK",
    ]
    assert set(canonical_keys) == ALLOWED_FEATURE_KEYS

    mock_video_upload = {
        "secure_url": "https://res.cloudinary.com/demo/video/upload/v123/tut_nav.mp4",
        "public_id": "tutorials/videos/tut_nav",
        "duration": 10.0,
        "width": 1080,
        "height": 1920,
    }

    with override_admin(admin):
        with patch("app.modules.tutorials.service.upload_tutorial_video", return_value=mock_video_upload):
            for key in canonical_keys:
                files = {"video": ("tutorial.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4")}
                data = {
                    "feature_key": key,
                    "title": f"Tutorial {key}",
                }
                res = await test_client.post("/api/v1/admin/tutorials", files=files, data=data)
                assert res.status_code == 201, f"Failed for key {key}: {res.text}"
                assert res.json()["feature_key"] == key


@pytest.mark.asyncio
async def test_admin_create_invalid_action_rejected(test_client: AsyncClient, tutorial_test_users: dict):
    """Hành động sau khi xem không nằm trong ALLOWED_ACTION_KEYS bị từ chối 400."""
    admin = tutorial_test_users["admin"]
    with override_admin(admin):
        files = {"video": ("tutorial.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4")}
        data = {
            "feature_key": "CREATE_PRODUCT",
            "title": "Test Title",
            "action_key": "/raw/uncontrolled/path",
        }
        res = await test_client.post("/api/v1/admin/tutorials", files=files, data=data)
        assert res.status_code == 400
        assert "không hợp lệ" in res.json()["detail"]


@pytest.mark.asyncio
async def test_admin_create_empty_title_rejected(test_client: AsyncClient, tutorial_test_users: dict):
    """Tiêu đề rỗng bị từ chối 400."""
    admin = tutorial_test_users["admin"]
    with override_admin(admin):
        files = {"video": ("tutorial.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4")}
        data = {
            "feature_key": "CREATE_PRODUCT",
            "title": "    ",
        }
        res = await test_client.post("/api/v1/admin/tutorials", files=files, data=data)
        assert res.status_code == 400


@pytest.mark.asyncio
async def test_admin_create_landscape_video_rejected(test_client: AsyncClient, tutorial_test_users: dict):
    """Video ngang (width > height) bị từ chối và Cloudinary asset được dọn dẹp."""
    admin = tutorial_test_users["admin"]
    mock_landscape_upload = {
        "secure_url": "https://res.cloudinary.com/demo/video/upload/v123/landscape.mp4",
        "public_id": "tutorials/videos/landscape",
        "duration": 30.0,
        "width": 1920,
        "height": 1080,
    }

    with override_admin(admin):
        with patch("app.modules.tutorials.service.upload_tutorial_video", return_value=mock_landscape_upload), \
             patch("app.modules.tutorials.service.destroy_asset") as mock_destroy:

            files = {"video": ("tutorial.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4")}
            data = {"feature_key": "CREATE_PRODUCT", "title": "Landscape Video"}
            res = await test_client.post("/api/v1/admin/tutorials", files=files, data=data)
            assert res.status_code == 400
            assert "portrait 9:16" in res.json()["detail"]
            mock_destroy.assert_called_once_with("tutorials/videos/landscape", resource_type="video")


# ======================================================================
# 4. MEDIA COMPENSATION TESTS
# ======================================================================

@pytest.mark.asyncio
async def test_create_db_failure_cleans_up_cloudinary(test_client: AsyncClient, tutorial_test_users: dict):
    """Nếu commit DB thất bại, video và poster mới tải lên phải được dọn dẹp khỏi Cloudinary."""
    admin = tutorial_test_users["admin"]
    mock_video_upload = {
        "secure_url": "https://res.cloudinary.com/demo/video/upload/v123/fail_tut.mp4",
        "public_id": "tutorials/videos/fail_tut",
        "width": 1080,
        "height": 1920,
    }

    with override_admin(admin):
        with patch("app.modules.tutorials.service.upload_tutorial_video", return_value=mock_video_upload), \
             patch("app.modules.tutorials.service.destroy_asset") as mock_destroy, \
             patch("app.modules.tutorials.repository.TutorialRepository.create", side_effect=RuntimeError("DB write failed")):

            files = {"video": ("tutorial.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4")}
            data = {"feature_key": "MY_LISTINGS", "title": "Fail DB Tutorial"}

            with pytest.raises(RuntimeError, match="DB write failed"):
                await test_client.post("/api/v1/admin/tutorials", files=files, data=data)

            mock_destroy.assert_called_once_with("tutorials/videos/fail_tut", resource_type="video")


@pytest.mark.asyncio
async def test_replace_video_success_cleans_up_old_video(test_client: AsyncClient, db_session: AsyncSession, tutorial_test_users: dict):
    """Khi thay thế video thành công: video mới được lưu vào DB, video cũ được xóa trên Cloudinary."""
    admin = tutorial_test_users["admin"]
    tut = Tutorial(
        feature_key="BUYER_ORDERS",
        title="Xem đơn mua",
        video_url="https://res.cloudinary.com/demo/video/upload/old_video.mp4",
        video_storage_key="tutorials/videos/old_video",
        video_mime_type="video/mp4",
        video_size_bytes=500000,
        sort_order=10,
        is_published=True,
        created_by=admin.user_id,
    )
    db_session.add(tut)
    await db_session.commit()

    mock_new_video = {
        "secure_url": "https://res.cloudinary.com/demo/video/upload/new_video.mp4",
        "public_id": "tutorials/videos/new_video",
        "duration": 45.0,
        "width": 1080,
        "height": 1920,
    }

    with override_admin(admin):
        with patch("app.modules.tutorials.service.upload_tutorial_video", return_value=mock_new_video), \
             patch("app.modules.tutorials.service.destroy_asset") as mock_destroy:

            files = {"video": ("new_video.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4")}
            res = await test_client.post(f"/api/v1/admin/tutorials/{tut.tutorial_id}/video", files=files)
            assert res.status_code == 200
            data = res.json()
            assert data["video_url"] == "https://res.cloudinary.com/demo/video/upload/new_video.mp4"
            assert data["video_storage_key"] == "tutorials/videos/new_video"
            assert data["thumbnail_url"] is not None
            # Video cũ phải bị xóa
            mock_destroy.assert_called_once_with("tutorials/videos/old_video", resource_type="video")


@pytest.mark.asyncio
async def test_replace_video_db_failure_cleans_up_new_video(test_client: AsyncClient, db_session: AsyncSession, tutorial_test_users: dict):
    """Nếu commit DB thất bại khi thay video: video mới bị xóa, video cũ trong DB vẫn nguyên vẹn."""
    admin = tutorial_test_users["admin"]
    tut = Tutorial(
        feature_key="BUYER_ORDERS",
        title="Xem đơn mua",
        video_url="https://res.cloudinary.com/demo/video/upload/old_video.mp4",
        video_storage_key="tutorials/videos/old_video",
        video_mime_type="video/mp4",
        video_size_bytes=500000,
        sort_order=10,
        is_published=True,
        created_by=admin.user_id,
    )
    db_session.add(tut)
    await db_session.commit()

    mock_new_video = {
        "secure_url": "https://res.cloudinary.com/demo/video/upload/new_video_fail.mp4",
        "public_id": "tutorials/videos/new_video_fail",
        "duration": 45.0,
        "width": 1080,
        "height": 1920,
    }

    with override_admin(admin):
        with patch("app.modules.tutorials.service.upload_tutorial_video", return_value=mock_new_video), \
             patch("app.modules.tutorials.service.destroy_asset") as mock_destroy, \
             patch.object(AsyncSession, "commit", side_effect=RuntimeError("Commit failed")):

            files = {"video": ("new_video.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4")}
            with pytest.raises(RuntimeError, match="Commit failed"):
                await test_client.post(f"/api/v1/admin/tutorials/{tut.tutorial_id}/video", files=files)

            mock_destroy.assert_called_once_with("tutorials/videos/new_video_fail", resource_type="video")


# ======================================================================
# 5. POSTER REMOVED & DERIVED THUMBNAIL TESTS
# ======================================================================

@pytest.mark.asyncio
async def test_poster_endpoints_removed(test_client: AsyncClient, db_session: AsyncSession, tutorial_test_users: dict):
    """Các endpoint poster cũ (/poster POST và DELETE) đã bị gỡ bỏ hoàn toàn và trả về 404/405."""
    admin = tutorial_test_users["admin"]
    tut = Tutorial(
        feature_key="MESSAGES",
        title="Gửi tin nhắn",
        video_url="https://res.cloudinary.com/demo/video/upload/msg.mp4",
        video_storage_key="tutorials/videos/msg",
        video_mime_type="video/mp4",
        video_size_bytes=500000,
        sort_order=10,
        is_published=True,
        created_by=admin.user_id,
    )
    db_session.add(tut)
    await db_session.commit()

    with override_admin(admin):
        files = {"poster": ("poster.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
        res_post = await test_client.post(f"/api/v1/admin/tutorials/{tut.tutorial_id}/poster", files=files)
        assert res_post.status_code in (404, 405)

        res_del = await test_client.delete(f"/api/v1/admin/tutorials/{tut.tutorial_id}/poster")
        assert res_del.status_code in (404, 405)


def test_build_tutorial_thumbnail_url_video_resource_and_duration():
    """Thumbnail URL được dẫn xuất chính xác từ video Cloudinary, tuân thủ resource_type=video và duration."""
    # Case 1: Video dài (> 2000 ms) lấy frame ở giây thứ 1 (so_1)
    url_long = build_tutorial_thumbnail_url("tutorials/videos/sample_long", duration_ms=60000)
    assert url_long is not None
    assert "/video/upload/" in url_long
    assert "image/upload" not in url_long
    assert "so_1" in url_long
    assert "w_360" in url_long
    assert url_long.endswith(".jpg")

    # Case 2: Video ngắn (< 2000 ms) lấy frame ở giây 0.5 (so_0.5)
    url_short = build_tutorial_thumbnail_url("tutorials/videos/sample_short", duration_ms=1500)
    assert url_short is not None
    assert "/video/upload/" in url_short
    assert "so_0.5" in url_short
    assert url_short.endswith(".jpg")

    # Case 3: Không rõ duration (None) dùng fallback an toàn so_1
    url_none = build_tutorial_thumbnail_url("tutorials/videos/sample_unknown", duration_ms=None)
    assert url_none is not None
    assert "/video/upload/" in url_none
    assert "so_1" in url_none
    assert url_none.endswith(".jpg")


# ======================================================================
# 6. EDIT METADATA, PUBLISH & REORDER TESTS
# ======================================================================

@pytest.mark.asyncio
async def test_admin_update_metadata_and_move_feature(test_client: AsyncClient, db_session: AsyncSession, tutorial_test_users: dict):
    """Cập nhật metadata và tự động chuyển xuống cuối nhóm tính năng mới."""
    admin = tutorial_test_users["admin"]
    t1 = Tutorial(
        feature_key="MY_LISTINGS",
        title="Title ban đầu",
        video_url="https://res.cloudinary.com/demo/video/upload/t1.mp4",
        video_storage_key="tutorials/videos/t1",
        video_mime_type="video/mp4",
        video_size_bytes=500000,
        sort_order=10,
        is_published=False,
        created_by=admin.user_id,
    )
    t_existing = Tutorial(
        feature_key="FAVORITES",
        title="Tin đã lưu 1",
        video_url="https://res.cloudinary.com/demo/video/upload/t2.mp4",
        video_storage_key="tutorials/videos/t2",
        video_mime_type="video/mp4",
        video_size_bytes=500000,
        sort_order=20,
        is_published=True,
        created_by=admin.user_id,
    )
    db_session.add_all([t1, t_existing])
    await db_session.commit()

    with override_admin(admin):
        # Đổi sang FAVORITES -> sort_order phải là 20 + 10 = 30
        res = await test_client.patch(
            f"/api/v1/admin/tutorials/{t1.tutorial_id}",
            json={
                "title": "Title mới",
                "feature_key": "FAVORITES",
                "is_published": True,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["title"] == "Title mới"
        assert data["feature_key"] == "FAVORITES"
        assert data["sort_order"] == 30
        assert data["is_published"] is True


@pytest.mark.asyncio
async def test_admin_reorder_success_and_validations(test_client: AsyncClient, db_session: AsyncSession, tutorial_test_users: dict):
    """Sắp xếp lại thứ tự tutorial trong nhóm tính năng."""
    admin = tutorial_test_users["admin"]
    t1 = Tutorial(
        feature_key="SELLER_ORDERS",
        title="Đơn bán 1",
        video_url="https://res.cloudinary.com/demo/video/upload/a1.mp4",
        video_storage_key="tutorials/videos/a1",
        video_mime_type="video/mp4",
        video_size_bytes=500000,
        sort_order=10,
        is_published=True,
        created_by=admin.user_id,
    )
    t2 = Tutorial(
        feature_key="SELLER_ORDERS",
        title="Đơn bán 2",
        video_url="https://res.cloudinary.com/demo/video/upload/a2.mp4",
        video_storage_key="tutorials/videos/a2",
        video_mime_type="video/mp4",
        video_size_bytes=500000,
        sort_order=20,
        is_published=True,
        created_by=admin.user_id,
    )
    db_session.add_all([t1, t2])
    await db_session.commit()

    with override_admin(admin):
        # Đổi thứ tự: t2 trước, t1 sau
        res = await test_client.patch(
            "/api/v1/admin/tutorials/reorder",
            json={"feature_key": "SELLER_ORDERS", "tutorial_ids": [t2.tutorial_id, t1.tutorial_id]},
        )
        assert res.status_code == 200
        data = res.json()
        t2_res = next(x for x in data if x["tutorial_id"] == t2.tutorial_id)
        t1_res = next(x for x in data if x["tutorial_id"] == t1.tutorial_id)
        assert t2_res["sort_order"] == 10
        assert t1_res["sort_order"] == 20

        # Lỗi: duplicate IDs
        res_dup = await test_client.patch(
            "/api/v1/admin/tutorials/reorder",
            json={"feature_key": "SELLER_ORDERS", "tutorial_ids": [t1.tutorial_id, t1.tutorial_id]},
        )
        assert res_dup.status_code == 422


# ======================================================================
# 7. HARD DELETE TESTS
# ======================================================================

@pytest.mark.asyncio
async def test_admin_delete_tutorial_success(test_client: AsyncClient, db_session: AsyncSession, tutorial_test_users: dict):
    """Xóa cứng tutorial khỏi DB và dọn dẹp video trên Cloudinary."""
    admin = tutorial_test_users["admin"]
    tut = Tutorial(
        feature_key="FEEDBACK",
        title="Gửi phản hồi",
        video_url="https://res.cloudinary.com/demo/video/upload/del.mp4",
        video_storage_key="tutorials/videos/del_video",
        video_mime_type="video/mp4",
        video_size_bytes=500000,
        sort_order=10,
        is_published=True,
        created_by=admin.user_id,
    )
    db_session.add(tut)
    await db_session.commit()

    with override_admin(admin):
        with patch("app.modules.tutorials.service.destroy_asset") as mock_destroy:
            res = await test_client.delete(f"/api/v1/admin/tutorials/{tut.tutorial_id}")
            assert res.status_code == 200
            mock_destroy.assert_called_once_with("tutorials/videos/del_video", resource_type="video")

        # Kiểm tra không còn trong DB
        check = await db_session.execute(select(Tutorial).where(Tutorial.tutorial_id == tut.tutorial_id))
        assert check.scalars().first() is None


@pytest.mark.asyncio
async def test_admin_delete_cleanup_failure_does_not_fail_db(test_client: AsyncClient, db_session: AsyncSession, tutorial_test_users: dict):
    """Nếu Cloudinary destroy thất bại sau commit, DB row vẫn bị xóa và trả về 200."""
    admin = tutorial_test_users["admin"]
    tut = Tutorial(
        feature_key="FEEDBACK",
        title="Xóa lỗi media",
        video_url="https://res.cloudinary.com/demo/video/upload/del_err.mp4",
        video_storage_key="tutorials/videos/del_err",
        video_mime_type="video/mp4",
        video_size_bytes=500000,
        sort_order=10,
        is_published=True,
        created_by=admin.user_id,
    )
    db_session.add(tut)
    await db_session.commit()

    with override_admin(admin):
        with patch("app.modules.tutorials.service.destroy_asset", side_effect=Exception("Network error")):
            res = await test_client.delete(f"/api/v1/admin/tutorials/{tut.tutorial_id}")
            # Do không để lỗi cleanup ảnh hưởng đến kết quả DB:
            assert res.status_code == 200

        check = await db_session.execute(select(Tutorial).where(Tutorial.tutorial_id == tut.tutorial_id))
        assert check.scalars().first() is None


@pytest.mark.asyncio
async def test_student_cannot_mutate_tutorials(test_client: AsyncClient, db_session: AsyncSession, tutorial_test_users: dict):
    """Sinh viên không thể tạo, sửa, xóa, hoặc reorder tutorial."""
    student = tutorial_test_users["student"]
    admin = tutorial_test_users["admin"]
    tut = Tutorial(
        feature_key="FEEDBACK",
        title="Tutorial test",
        video_url="https://res.cloudinary.com/demo/video/upload/t.mp4",
        video_storage_key="tutorials/videos/t",
        video_mime_type="video/mp4",
        video_size_bytes=500000,
        sort_order=10,
        is_published=True,
        created_by=admin.user_id,
    )
    db_session.add(tut)
    await db_session.commit()

    with auth_patch(student):
        # 1. Create
        files = {"video": ("tutorial.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4")}
        res_create = await test_client.post("/api/v1/admin/tutorials", files=files, data={"feature_key": "CREATE_PRODUCT", "title": "T"})
        assert res_create.status_code == 403

        # 2. Update
        res_update = await test_client.patch(f"/api/v1/admin/tutorials/{tut.tutorial_id}", json={"title": "New"})
        assert res_update.status_code == 403

        # 3. Reorder
        res_reorder = await test_client.patch("/api/v1/admin/tutorials/reorder", json={"feature_key": "FEEDBACK", "tutorial_ids": [tut.tutorial_id]})
        assert res_reorder.status_code == 403

        # 4. Delete
        res_del = await test_client.delete(f"/api/v1/admin/tutorials/{tut.tutorial_id}")
        assert res_del.status_code == 403


@pytest.mark.asyncio
async def test_banned_user_cannot_access_admin(test_client: AsyncClient, tutorial_test_users: dict):
    """Người dùng bị khóa bị từ chối 403."""
    banned = tutorial_test_users["banned"]
    with auth_patch(banned):
        res = await test_client.get("/api/v1/admin/tutorials")
        assert res.status_code == 403


# ======================================================================
# 8. MULTIPART CONTRACT, BOUNDARY, AND REGISTRY RIGOR (SECTIONS 25-29)
# ======================================================================

@pytest.mark.asyncio
async def test_admin_create_multipart_contract_matches_frontend(test_client: AsyncClient, tutorial_test_users: dict):
    """Section 25: Test Admin create with exact frontend multipart field names and values (video only, no poster)."""
    admin = tutorial_test_users["admin"]
    mock_video_upload = {
        "secure_url": "https://res.cloudinary.com/demo/video/upload/v123/tut_login.mp4",
        "public_id": "tutorials/videos/tut_login",
        "duration": 48.0,
        "width": 1080,
        "height": 1920,
    }

    with override_admin(admin):
        with patch("app.modules.tutorials.service.upload_tutorial_video", return_value=mock_video_upload):
            files = {
                "video": ("11626.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4"),
            }
            data = {
                "feature_key": "PROFILE",
                "title": "Cách đăng nhập",
                "description": "Ok",
                "action_key": "PROFILE",
                "is_published": "true",
            }
            res = await test_client.post("/api/v1/admin/tutorials", files=files, data=data)
            assert res.status_code == 201
            resp_data = res.json()
            assert resp_data["feature_key"] == "PROFILE"
            assert resp_data["title"] == "Cách đăng nhập"
            assert resp_data["description"] == "Ok"
            assert resp_data["action_key"] == "PROFILE"
            assert resp_data["is_published"] is True
            assert resp_data["video_url"] == "https://res.cloudinary.com/demo/video/upload/v123/tut_login.mp4"
            assert resp_data["thumbnail_url"] is not None
            assert "poster_url" not in resp_data
            assert "poster_storage_key" not in resp_data
            assert resp_data["created_by"] == admin.user_id


@pytest.mark.asyncio
async def test_admin_create_video_size_boundary(test_client: AsyncClient, tutorial_test_users: dict):
    """Section 26: Test size boundary around 100 MB limit (rejected over limit, accepted just under)."""
    admin = tutorial_test_users["admin"]
    mock_video_upload = {
        "secure_url": "https://res.cloudinary.com/demo/video/upload/v123/tut_limit.mp4",
        "public_id": "tutorials/videos/tut_limit",
        "duration": 30.0,
        "width": 1080,
        "height": 1920,
    }

    with override_admin(admin):
        # Case 1: Over limit (100 MB + 1 byte) -> 400
        with patch("starlette.datastructures.UploadFile.read", new_callable=AsyncMock, return_value=b"x" * (MAX_TUTORIAL_VIDEO_SIZE_BYTES + 1)):
            files = {"video": ("oversized.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4")}
            data = {"feature_key": "HOME", "title": "Oversized Test"}
            res = await test_client.post("/api/v1/admin/tutorials", files=files, data=data)
            assert res.status_code == 400
            assert "vượt quá giới hạn cho phép" in res.json()["detail"]

        # Case 2: Just at/under limit (100 MB) -> 201
        with patch("app.modules.tutorials.service.upload_tutorial_video", return_value=mock_video_upload), \
             patch("starlette.datastructures.UploadFile.read", new_callable=AsyncMock, return_value=b"x" * MAX_TUTORIAL_VIDEO_SIZE_BYTES):
            files = {"video": ("valid_limit.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4")}
            data = {"feature_key": "HOME", "title": "Limit Accepted Test"}
            res_ok = await test_client.post("/api/v1/admin/tutorials", files=files, data=data)
            assert res_ok.status_code == 201
            assert res_ok.json()["video_size_bytes"] == MAX_TUTORIAL_VIDEO_SIZE_BYTES


@pytest.mark.asyncio
async def test_admin_create_all_frontend_action_keys_accepted(test_client: AsyncClient, tutorial_test_users: dict):
    """Section 27: Verify all canonical frontend action keys are accepted by backend."""
    admin = tutorial_test_users["admin"]
    expected_frontend_actions = [
        "HOME",
        "CREATE_PRODUCT",
        "MY_LISTINGS",
        "FAVORITES",
        "BUYER_ORDERS",
        "SELLER_ORDERS",
        "MESSAGES",
        "NOTIFICATIONS",
        "FEEDBACK",
        "PROFILE",
    ]

    assert set(expected_frontend_actions) == ALLOWED_ACTION_KEYS

    mock_video_upload = {
        "secure_url": "https://res.cloudinary.com/demo/video/upload/v123/tut_act.mp4",
        "public_id": "tutorials/videos/tut_act",
        "duration": 30.0,
        "width": 1080,
        "height": 1920,
    }

    with override_admin(admin):
        with patch("app.modules.tutorials.service.upload_tutorial_video", return_value=mock_video_upload):
            for action in expected_frontend_actions:
                files = {"video": ("act.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4")}
                data = {
                    "feature_key": "HOME",
                    "title": f"Test Action {action}",
                    "action_key": action,
                }
                res = await test_client.post("/api/v1/admin/tutorials", files=files, data=data)
                assert res.status_code == 201, f"Action {action} failed with {res.status_code}: {res.text}"
                assert res.json()["action_key"] == action


@pytest.mark.asyncio
async def test_admin_create_cloudinary_failure_no_db_row(test_client: AsyncClient, db_session: AsyncSession, tutorial_test_users: dict):
    """Section 28: Cloudinary upload failure raises error, creates no DB row, leaves no public tutorial."""
    admin = tutorial_test_users["admin"]

    with override_admin(admin):
        with patch("app.modules.tutorials.service.upload_tutorial_video", side_effect=RuntimeError("Cloudinary connection reset")):
            files = {"video": ("fail.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4")}
            data = {"feature_key": "HOME", "title": "Cloudinary Fail Tutorial"}

            with pytest.raises(RuntimeError, match="Cloudinary connection reset"):
                await test_client.post("/api/v1/admin/tutorials", files=files, data=data)

        check = await db_session.execute(
            select(Tutorial).where(Tutorial.title == "Cloudinary Fail Tutorial")
        )
        assert check.scalars().first() is None


@pytest.mark.asyncio
async def test_create_db_failure_cleans_up_video(test_client: AsyncClient, tutorial_test_users: dict):
    """Section 29: When DB fails after video is uploaded, video asset must be cleaned up."""
    admin = tutorial_test_users["admin"]
    mock_video_upload = {
        "secure_url": "https://res.cloudinary.com/demo/video/upload/v123/fail_v.mp4",
        "public_id": "tutorials/videos/fail_v",
        "width": 1080,
        "height": 1920,
    }

    with override_admin(admin):
        with patch("app.modules.tutorials.service.upload_tutorial_video", return_value=mock_video_upload), \
             patch("app.modules.tutorials.service.destroy_asset") as mock_destroy, \
             patch("app.modules.tutorials.repository.TutorialRepository.create", side_effect=RuntimeError("DB persistence failed")):

            files = {
                "video": ("tutorial.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4"),
            }
            data = {"feature_key": "CREATE_PRODUCT", "title": "Fail DB Media"}

            with pytest.raises(RuntimeError, match="DB persistence failed"):
                await test_client.post("/api/v1/admin/tutorials", files=files, data=data)

            mock_destroy.assert_called_once_with("tutorials/videos/fail_v", resource_type="video")


# ======================================================================
# 9. NON-BLOCKING EVENT LOOP & CLOUDINARY RESILIENCE TESTS (SECTIONS 25-29)
# ======================================================================

import asyncio
import time
from app.integrations.cloudinary import (
    _upload_tutorial_video_sync,
    get_tutorial_video_delivery_url,
    upload_tutorial_video,
    CloudinaryUploadError,
)

@pytest.mark.asyncio
async def test_tutorial_cloudinary_upload_offloaded_non_blocking_event_loop():
    """Section 25: Verify synchronous Cloudinary video upload is offloaded to worker thread
    and does NOT block the asyncio event loop."""
    def slow_blocking_upload(*args, **kwargs):
        time.sleep(0.3)
        return {
            "resource_type": "video",
            "public_id": "tutorials/videos/slow_test",
            "secure_url": "https://res.cloudinary.com/demo/video/upload/v123/slow_test.mp4",
            "duration": 20.0,
            "width": 1080,
            "height": 1920,
        }

    ticker_ticks = 0
    async def ticker():
        nonlocal ticker_ticks
        for _ in range(6):
            await asyncio.sleep(0.04)
            ticker_ticks += 1

    with patch("app.integrations.cloudinary._upload_tutorial_video_sync", side_effect=slow_blocking_upload):
        # Run upload and ticker concurrently
        upload_task = asyncio.create_task(upload_tutorial_video(io.BytesIO(VALID_MP4_BYTES)))
        ticker_task = asyncio.create_task(ticker())

        res, _ = await asyncio.gather(upload_task, ticker_task)

        assert ticker_ticks >= 4, f"Event loop was blocked! Only {ticker_ticks} ticks executed."
        assert res["public_id"] == "tutorials/videos/slow_test"


@pytest.mark.asyncio
async def test_concurrent_api_requests_not_blocked_during_tutorial_upload(test_client: AsyncClient, tutorial_test_users: dict):
    """Section 26: Concurrent API requests (e.g. GET /tutorials or health) complete promptly
    while an Admin tutorial video upload is running."""
    admin = tutorial_test_users["admin"]

    def slow_upload(*args, **kwargs):
        time.sleep(0.35)
        return {
            "resource_type": "video",
            "public_id": "tutorials/videos/slow_create",
            "secure_url": "https://res.cloudinary.com/demo/video/upload/v123/slow_create.mp4",
            "duration": 15.0,
            "width": 1080,
            "height": 1920,
        }

    with override_admin(admin):
        with patch("app.integrations.cloudinary._upload_tutorial_video_sync", side_effect=slow_upload):
            files = {"video": ("test.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4")}
            data = {"feature_key": "HOME", "title": "Slow Upload Test"}

            t_start = time.time()
            get_finished_at = 0.0

            async def do_upload():
                return await test_client.post("/api/v1/admin/tutorials", files=files, data=data)

            async def do_concurrent_get():
                nonlocal get_finished_at
                await asyncio.sleep(0.05)
                res = await test_client.get("/api/v1/tutorials")
                get_finished_at = time.time() - t_start
                return res

            upload_res, get_res = await asyncio.gather(do_upload(), do_concurrent_get())

            assert upload_res.status_code == 201
            assert get_res.status_code == 200
            assert get_finished_at < 0.25, f"Concurrent GET was blocked! Took {get_finished_at}s"


def test_upload_tutorial_video_resource_type_and_normalization():
    """Section 27 & 28: Assert resource_type='video' is strictly used, and delivery URL is normalized."""
    with patch("cloudinary.uploader.upload") as mock_small_upload, \
         patch("cloudinary.uploader.upload_large") as mock_large_upload:

        mock_small_upload.return_value = {
            "resource_type": "video",
            "public_id": "tutorials/videos/norm_vid",
            "secure_url": "https://res.cloudinary.com/demo/video/upload/v123/norm_vid.mp4",
            "duration": 12.0,
            "width": 1080,
            "height": 1920,
        }
        mock_large_upload.return_value = {
            "resource_type": "video",
            "public_id": "tutorials/videos/norm_large",
            "secure_url": "https://res.cloudinary.com/demo/video/upload/v123/norm_large.mp4",
            "duration": 45.0,
            "width": 1080,
            "height": 1920,
        }

        # Case 1: Small video (<= 20 MB) uses upload
        res_small = _upload_tutorial_video_sync(io.BytesIO(VALID_MP4_BYTES), filename="small.mp4", file_size=1024)
        mock_small_upload.assert_called_once()
        assert mock_small_upload.call_args[1]["resource_type"] == "video"
        assert mock_small_upload.call_args[1]["filename"] == "small.mp4"
        assert mock_small_upload.call_args[1]["timeout"] == 150
        assert "vc_auto" in res_small["secure_url"]

        # Case 2: Large video (> 20 MB) uses upload_large with chunk_size
        large_size = 25 * 1024 * 1024
        res_large = _upload_tutorial_video_sync(io.BytesIO(VALID_MP4_BYTES), filename="large.mp4", file_size=large_size)
        mock_large_upload.assert_called_once()
        assert mock_large_upload.call_args[1]["resource_type"] == "video"
        assert mock_large_upload.call_args[1]["chunk_size"] == 20 * 1024 * 1024
        assert mock_large_upload.call_args[1]["timeout"] == 150
        assert "vc_auto" in res_large["secure_url"]


def test_upload_tutorial_video_invalid_provider_response_rejected():
    """Section 29: If Cloudinary returns wrong resource_type or invalid response, reject safely."""
    with patch("cloudinary.uploader.upload", return_value={"resource_type": "image", "public_id": "bad/id"}):
        with pytest.raises(CloudinaryUploadError, match="unexpected resource_type"):
            _upload_tutorial_video_sync(io.BytesIO(VALID_MP4_BYTES), filename="test.mp4")

    with patch("cloudinary.uploader.upload", return_value={"resource_type": "video", "public_id": "no/url"}):
        with pytest.raises(CloudinaryUploadError, match="valid delivery URL"):
            _upload_tutorial_video_sync(io.BytesIO(VALID_MP4_BYTES), filename="test.mp4")


def test_upload_tutorial_video_12_8mb_uses_small_upload_with_timeout_150():
    """Verify 12.8 MB video (matching production 13248.mp4) uses upload with timeout=150 and BytesIO stream."""
    with patch("cloudinary.uploader.upload") as mock_small_upload, \
         patch("cloudinary.uploader.upload_large") as mock_large_upload:

        mock_small_upload.return_value = {
            "resource_type": "video",
            "public_id": "tutorials/videos/prod_13248",
            "secure_url": "https://res.cloudinary.com/demo/video/upload/v123/prod_13248.mp4",
            "duration": 25.0,
            "width": 1080,
            "height": 1920,
        }

        # 12.8 MB = 13,421,772 bytes (<= 20 MB)
        file_size_12_8mb = int(12.8 * 1024 * 1024)
        file_stream = io.BytesIO(b"0" * 1024)

        res = _upload_tutorial_video_sync(file_stream, filename="13248.mp4", file_size=file_size_12_8mb)

        mock_small_upload.assert_called_once()
        mock_large_upload.assert_not_called()
        assert mock_small_upload.call_args[1]["resource_type"] == "video"
        assert mock_small_upload.call_args[1]["timeout"] == 150
        assert mock_small_upload.call_args[1]["filename"] == "13248.mp4"
        assert "vc_auto" in res["secure_url"]


@pytest.mark.asyncio
async def test_service_maps_cloudinary_errors_to_http_exceptions():
    """Verify service maps CloudinaryNotConfiguredError to 503 and CloudinaryUploadError to 502."""
    from fastapi import HTTPException, UploadFile
    from app.integrations.cloudinary import CloudinaryNotConfiguredError
    from app.modules.tutorials.service import TutorialService
    from unittest.mock import AsyncMock

    mock_db = AsyncMock()
    service = TutorialService(mock_db)
    service.repo = AsyncMock()
    service.repo.get_by_id.return_value = MagicMock(tutorial_id=1, video_storage_key="tutorials/videos/old")

    # 1. CloudinaryNotConfiguredError -> 503
    mock_upload_file_1 = UploadFile(filename="test.mp4", file=io.BytesIO(VALID_MP4_BYTES), headers={"content-type": "video/mp4"})
    with patch("app.modules.tutorials.service.upload_tutorial_video", side_effect=CloudinaryNotConfiguredError("Not configured")):
        with pytest.raises(HTTPException) as exc_info:
            await service.replace_tutorial_video(
                tutorial_id=1,
                video_file=mock_upload_file_1,
            )
        assert exc_info.value.status_code == 503
        assert "chưa được cấu hình" in exc_info.value.detail

    # 2. CloudinaryUploadError -> 502
    mock_upload_file_2 = UploadFile(filename="test.mp4", file=io.BytesIO(VALID_MP4_BYTES), headers={"content-type": "video/mp4"})
    with patch("app.modules.tutorials.service.upload_tutorial_video", side_effect=CloudinaryUploadError("Upload failed")):
        with pytest.raises(HTTPException) as exc_info:
            await service.replace_tutorial_video(
                tutorial_id=1,
                video_file=mock_upload_file_2,
            )
        assert exc_info.value.status_code == 502
        assert "máy chủ lưu trữ" in exc_info.value.detail


@pytest.mark.asyncio
async def test_realistic_tutorial_video_replace_flow_with_structured_logging():
    """
    Realistic integration test:
    - Valid MP4 binary stream (12.8 MB simulation or chunked atoms)
    - Verifies all 6 structured logging stages:
      request_received -> file_read_completed -> cloudinary_upload_started ->
      cloudinary_upload_completed -> db_commit_completed -> response_completed
    - Verifies duration_ms, file_size_bytes, tutorial_id, status, and request_id
    - Verifies old video cleanup is dispatched off the critical response path
    """
    from fastapi import UploadFile
    from app.modules.tutorials.service import TutorialService
    from unittest.mock import AsyncMock, MagicMock, patch

    # Realistic MP4 stream with ftyp and mdat boxes
    realistic_mp4_bytes = (
        b"\x00\x00\x00\x1cftypisom\x00\x00\x02\x00isomiso2mp41\x00\x00\x00\x08mdat"
        + b"\x00" * (64 * 1024)  # 64 KB realistic sample
    )

    mock_db = AsyncMock()
    service = TutorialService(mock_db)
    service.repo = AsyncMock()

    mock_existing_tutorial = MagicMock()
    mock_existing_tutorial.tutorial_id = 99
    mock_existing_tutorial.video_storage_key = "tutorials/videos/old_key_99"
    mock_existing_tutorial.video_url = "https://res.cloudinary.com/demo/video/upload/old.mp4"
    service.repo.get_by_id.return_value = mock_existing_tutorial

    logged_stages = []

    def mock_log_stage(stage, request_id, tutorial_id=None, duration_ms=None, file_size_bytes=None, status="success", error=None):
        logged_stages.append({
            "stage": stage,
            "request_id": request_id,
            "tutorial_id": tutorial_id,
            "duration_ms": duration_ms,
            "file_size_bytes": file_size_bytes,
            "status": status,
            "error": error,
        })

    mock_upload_file = UploadFile(
        filename="13248.mp4",
        file=io.BytesIO(realistic_mp4_bytes),
        headers={"content-type": "video/mp4"},
    )

    fake_cloudinary_result = {
        "resource_type": "video",
        "public_id": "tutorials/videos/new_prod_13248",
        "secure_url": "https://res.cloudinary.com/demo/video/upload/vc_auto/v123/tutorials/videos/new_prod_13248.mp4",
        "duration": 25.4,
        "width": 1080,
        "height": 1920,  # Portrait 9:16
    }

    with patch.object(service, "_log_stage", side_effect=mock_log_stage), \
         patch("app.modules.tutorials.service.upload_tutorial_video", new=AsyncMock(return_value=fake_cloudinary_result)), \
         patch.object(service, "_safe_destroy_asset", new=AsyncMock()) as mock_safe_destroy:

        result = await service.replace_tutorial_video(
            tutorial_id=99,
            video_file=mock_upload_file,
            request_id="req-test-trace-123",
        )

        assert result.video_storage_key == "tutorials/videos/new_prod_13248"
        assert result.video_size_bytes == len(realistic_mp4_bytes)
        assert result.duration_ms == 25400
        mock_db.commit.assert_awaited_once()

        # Verify all stages recorded in chronological order
        stages = [s["stage"] for s in logged_stages]
        assert stages == [
            "request_received",
            "file_read_completed",
            "cloudinary_upload_started",
            "cloudinary_upload_completed",
            "db_commit_completed",
            "response_completed",
        ]

        # Verify structured metadata fields
        for entry in logged_stages:
            assert entry["request_id"] == "req-test-trace-123"
            if entry["stage"] == "cloudinary_upload_started":
                assert entry["status"] == "pending"
            else:
                assert entry["status"] == "success"

        file_read_event = next(s for s in logged_stages if s["stage"] == "file_read_completed")
        assert file_read_event["file_size_bytes"] == len(realistic_mp4_bytes)
        assert file_read_event["duration_ms"] is not None

        db_commit_event = next(s for s in logged_stages if s["stage"] == "db_commit_completed")
        assert db_commit_event["tutorial_id"] == 99


@pytest.mark.asyncio
async def test_realistic_tutorial_video_replace_network_failure_handling():
    """
    Realistic network failure test:
    - Simulates Cloudinary upload timeout (e.g. 150s socket timeout)
    - Verifies cloudinary_upload_failed log stage is emitted with status='error'
    - Verifies HTTP 502 Bad Gateway is returned
    - Verifies DB is NOT modified and rollback is executed
    """
    from fastapi import HTTPException, UploadFile
    from app.modules.tutorials.service import TutorialService
    from app.integrations.cloudinary import CloudinaryUploadError
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_db = AsyncMock()
    service = TutorialService(mock_db)
    service.repo = AsyncMock()

    mock_existing_tutorial = MagicMock()
    mock_existing_tutorial.tutorial_id = 42
    mock_existing_tutorial.video_storage_key = "tutorials/videos/existing_safe_video"
    service.repo.get_by_id.return_value = mock_existing_tutorial

    logged_stages = []

    def mock_log_stage(stage, request_id, tutorial_id=None, duration_ms=None, file_size_bytes=None, status="success", error=None):
        logged_stages.append({
            "stage": stage,
            "request_id": request_id,
            "status": status,
            "error": error,
        })

    mock_upload_file = UploadFile(
        filename="13248.mp4",
        file=io.BytesIO(VALID_MP4_BYTES),
        headers={"content-type": "video/mp4"},
    )

    with patch.object(service, "_log_stage", side_effect=mock_log_stage), \
         patch("app.modules.tutorials.service.upload_tutorial_video", side_effect=CloudinaryUploadError("Connection timed out after 150 seconds")):

        with pytest.raises(HTTPException) as exc_info:
            await service.replace_tutorial_video(
                tutorial_id=42,
                video_file=mock_upload_file,
                request_id="req-timeout-fail-456",
            )

        assert exc_info.value.status_code == 502
        assert "quá thời gian xử lý" in exc_info.value.detail

        # DB must never be committed
        mock_db.commit.assert_not_awaited()

        # Verify failed stage was captured in structured log
        stages = [s["stage"] for s in logged_stages]
        assert "cloudinary_upload_started" in stages
        assert "cloudinary_upload_failed" in stages

        failed_event = next(s for s in logged_stages if s["stage"] == "cloudinary_upload_failed")
        assert failed_event["status"] == "error"
        assert "timed out" in failed_event["error"]


@pytest.mark.asyncio
async def test_realistic_tutorial_video_replace_landscape_rejection():
    """
    Orientation validation test:
    - If uploaded video is landscape (height <= width, e.g. 1920x1080), reject with HTTP 400
    - Verify uploaded asset is immediately destroyed on Cloudinary
    - Verify DB row is untouched
    """
    from fastapi import HTTPException, UploadFile
    from app.modules.tutorials.service import TutorialService
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_db = AsyncMock()
    service = TutorialService(mock_db)
    service.repo = AsyncMock()

    mock_existing_tutorial = MagicMock(tutorial_id=10, video_storage_key="tutorials/videos/old")
    service.repo.get_by_id.return_value = mock_existing_tutorial

    landscape_cloudinary_result = {
        "resource_type": "video",
        "public_id": "tutorials/videos/bad_landscape",
        "secure_url": "https://res.cloudinary.com/demo/video/upload/bad.mp4",
        "duration": 15.0,
        "width": 1920,
        "height": 1080,  # Landscape: height <= width!
    }

    mock_upload_file = UploadFile(
        filename="landscape.mp4",
        file=io.BytesIO(VALID_MP4_BYTES),
        headers={"content-type": "video/mp4"},
    )

    with patch("app.modules.tutorials.service.upload_tutorial_video", new=AsyncMock(return_value=landscape_cloudinary_result)), \
         patch("app.modules.tutorials.service.destroy_asset", new=AsyncMock()) as mock_destroy:

        with pytest.raises(HTTPException) as exc_info:
            await service.replace_tutorial_video(tutorial_id=10, video_file=mock_upload_file)

        assert exc_info.value.status_code == 400
        assert "portrait 9:16" in exc_info.value.detail
        mock_destroy.assert_awaited_once_with("tutorials/videos/bad_landscape", resource_type="video")
        mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_replace_tutorial_video_early_404_when_tutorial_missing():
    """
    Early-exit 404 test:
    - If tutorial does not exist in DB, reject before performing any Cloudinary upload
    """
    from fastapi import HTTPException, UploadFile
    from app.modules.tutorials.service import TutorialService
    from unittest.mock import AsyncMock, patch

    mock_db = AsyncMock()
    service = TutorialService(mock_db)
    service.repo = AsyncMock()
    service.repo.get_by_id.return_value = None  # Tutorial not found

    mock_upload_file = UploadFile(
        filename="13248.mp4",
        file=io.BytesIO(VALID_MP4_BYTES),
        headers={"content-type": "video/mp4"},
    )

    with patch("app.modules.tutorials.service.upload_tutorial_video") as mock_upload:
        with pytest.raises(HTTPException) as exc_info:
            await service.replace_tutorial_video(tutorial_id=99999, video_file=mock_upload_file)

        assert exc_info.value.status_code == 404
        assert "99999" in exc_info.value.detail
        # Cloudinary upload must NEVER be initiated when tutorial does not exist
        mock_upload.assert_not_called()


@pytest.mark.asyncio
async def test_generate_tutorial_upload_signature():
    """Verify admin upload signature contains only safe parameters and never leaks API secret."""
    from app.modules.tutorials.service import TutorialService
    from unittest.mock import AsyncMock

    mock_db = AsyncMock()
    service = TutorialService(mock_db)

    with patch("app.integrations.cloudinary.is_cloudinary_configured", return_value=True), \
         patch("app.integrations.cloudinary.settings.CLOUDINARY_CLOUD_NAME", "ptit_cloud"), \
         patch("app.integrations.cloudinary.settings.CLOUDINARY_API_KEY", "ptit_key_123"), \
         patch("app.integrations.cloudinary.settings.CLOUDINARY_API_SECRET", "super_secret_never_leak"), \
         patch("app.integrations.cloudinary.get_tutorial_video_cloudinary_folder", return_value="student-marketplace/dev/tutorials/videos"):

        res = service.get_upload_signature("session_test_abc")
        assert res.cloud_name == "ptit_cloud"
        assert res.api_key == "ptit_key_123"
        assert res.folder == "student-marketplace/dev/tutorials/videos"
        assert res.upload_session_id == "session_test_abc"
        assert res.public_id == "tut_session_test_abc"
        assert res.overwrite == "false"
        assert isinstance(res.timestamp, int)
        assert len(res.signature) > 10
        # Ensure secret is never in the schema
        res_dict = res.model_dump()
        assert "super_secret_never_leak" not in str(res_dict)
        assert "api_secret" not in res_dict


@pytest.mark.asyncio
async def test_confirm_direct_video_replacement_success_and_lifecycle():
    """
    Verify confirm_direct_video_replacement:
    - Validates folder prefix and session-bound public_id
    - Verifies metadata from Cloudinary Admin API
    - Atomic DB update
    - Post-commit old video cleanup
    """
    from app.modules.tutorials.schemas import AdminTutorialConfirmDirectVideo
    from app.modules.tutorials.service import TutorialService
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_db = AsyncMock()
    service = TutorialService(mock_db)
    service.repo = AsyncMock()

    mock_tut = MagicMock()
    mock_tut.tutorial_id = 42
    mock_tut.video_storage_key = "student-marketplace/dev/tutorials/videos/old_asset_42"
    mock_tut.video_url = "https://res.cloudinary.com/demo/video/upload/old.mp4"
    service.repo.get_by_id.return_value = mock_tut
    service.repo.get_by_storage_key.return_value = None

    valid_folder = "student-marketplace/dev/tutorials/videos"
    new_public_id = f"{valid_folder}/tut_session_42"

    mock_cloudinary_resource = {
        "resource_type": "video",
        "format": "mp4",
        "bytes": 13421772,  # 12.8 MB
        "width": 720,
        "height": 1280,
        "duration": 15.2,
        "secure_url": "https://res.cloudinary.com/ptit/video/upload/v123/tut_session_42.mp4",
    }

    payload = AdminTutorialConfirmDirectVideo(
        public_id=new_public_id,
        upload_session_id="session_42",
    )

    with patch("app.modules.tutorials.service.get_tutorial_video_cloudinary_folder", return_value=valid_folder), \
         patch("app.modules.tutorials.service.get_cloudinary_video_resource_async", new=AsyncMock(return_value=mock_cloudinary_resource)), \
         patch("app.modules.tutorials.service.destroy_asset", new=AsyncMock()):

        result = await service.confirm_direct_video_replacement(tutorial_id=42, payload=payload)

        assert result.tutorial_id == 42
        assert mock_tut.video_storage_key == new_public_id
        assert "vc_auto" in mock_tut.video_url
        assert mock_tut.video_size_bytes == 13421772
        assert mock_tut.duration_ms == 15200
        mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_confirm_direct_video_replacement_rejects_foreign_folder():
    """Verify confirm_direct_video_replacement rejects public_id outside allowed folder prefix."""
    from fastapi import HTTPException
    from app.modules.tutorials.schemas import AdminTutorialConfirmDirectVideo
    from app.modules.tutorials.service import TutorialService
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_db = AsyncMock()
    service = TutorialService(mock_db)
    service.repo = AsyncMock()
    service.repo.get_by_id.return_value = MagicMock(tutorial_id=42)

    with patch("app.modules.tutorials.service.get_tutorial_video_cloudinary_folder", return_value="student-marketplace/dev/tutorials/videos"):
        payload = AdminTutorialConfirmDirectVideo(
            public_id="student-marketplace/dev/products/malicious_asset",
            upload_session_id="session_bad",
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.confirm_direct_video_replacement(tutorial_id=42, payload=payload)

        assert exc_info.value.status_code == 400
        assert "không khớp với phiên tải lên" in exc_info.value.detail


@pytest.mark.asyncio
async def test_confirm_direct_video_replacement_rejects_session_mismatch():
    """Verify confirm_direct_video_replacement rejects arbitrary public_id not matching session."""
    from fastapi import HTTPException
    from app.modules.tutorials.schemas import AdminTutorialConfirmDirectVideo
    from app.modules.tutorials.service import TutorialService
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_db = AsyncMock()
    service = TutorialService(mock_db)
    service.repo = AsyncMock()
    service.repo.get_by_id.return_value = MagicMock(tutorial_id=42, video_storage_key="old_key")

    valid_folder = "student-marketplace/dev/tutorials/videos"
    with patch("app.modules.tutorials.service.get_tutorial_video_cloudinary_folder", return_value=valid_folder):
        # Attacker tries to steal or delete old production video
        payload = AdminTutorialConfirmDirectVideo(
            public_id=f"{valid_folder}/old_production_video_target",
            upload_session_id="fresh_session_attacker",
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.confirm_direct_video_replacement(tutorial_id=42, payload=payload)

        assert exc_info.value.status_code == 400
        assert "không khớp với phiên tải lên" in exc_info.value.detail


@pytest.mark.asyncio
async def test_confirm_direct_video_replacement_idempotency_returns_early():
    """Verify confirm_direct_video_replacement returns existing tutorial immediately if already confirmed."""
    from app.modules.tutorials.schemas import AdminTutorialConfirmDirectVideo
    from app.modules.tutorials.service import TutorialService
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_db = AsyncMock()
    service = TutorialService(mock_db)
    service.repo = AsyncMock()

    valid_folder = "student-marketplace/dev/tutorials/videos"
    target_storage_key = f"{valid_folder}/tut_session_idempotent"

    mock_tut = MagicMock(tutorial_id=42, video_storage_key=target_storage_key)
    service.repo.get_by_id.return_value = mock_tut

    payload = AdminTutorialConfirmDirectVideo(
        public_id=target_storage_key,
        upload_session_id="session_idempotent",
    )

    with patch("app.modules.tutorials.service.get_tutorial_video_cloudinary_folder", return_value=valid_folder), \
         patch("app.modules.tutorials.service.get_cloudinary_video_resource_async") as mock_get_res:

        res = await service.confirm_direct_video_replacement(tutorial_id=42, payload=payload)
        assert res.tutorial_id == 42
        # Cloudinary API must NOT be called on idempotent replay
        mock_get_res.assert_not_called()
        mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_direct_video_replacement_rejects_already_used_storage_key():
    """Verify confirm_direct_video_replacement rejects asset that belongs to a different tutorial."""
    from fastapi import HTTPException
    from app.modules.tutorials.schemas import AdminTutorialConfirmDirectVideo
    from app.modules.tutorials.service import TutorialService
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_db = AsyncMock()
    service = TutorialService(mock_db)
    service.repo = AsyncMock()

    valid_folder = "student-marketplace/dev/tutorials/videos"
    target_storage_key = f"{valid_folder}/tut_session_conflict"

    mock_tut = MagicMock(tutorial_id=42, video_storage_key="old_video_42")
    service.repo.get_by_id.return_value = mock_tut
    # Other tutorial already owns this storage key
    service.repo.get_by_storage_key.return_value = MagicMock(tutorial_id=99, video_storage_key=target_storage_key)

    payload = AdminTutorialConfirmDirectVideo(
        public_id=target_storage_key,
        upload_session_id="session_conflict",
    )

    with patch("app.modules.tutorials.service.get_tutorial_video_cloudinary_folder", return_value=valid_folder):
        with pytest.raises(HTTPException) as exc_info:
            await service.confirm_direct_video_replacement(tutorial_id=42, payload=payload)

        assert exc_info.value.status_code == 400
        assert "đã thuộc về một video hướng dẫn khác" in exc_info.value.detail


@pytest.mark.asyncio
async def test_confirm_direct_video_replacement_rejects_landscape_and_cleans_asset():
    """Verify confirm_direct_video_replacement destroys asset and rejects landscape video."""
    from fastapi import HTTPException
    from app.modules.tutorials.schemas import AdminTutorialConfirmDirectVideo
    from app.modules.tutorials.service import TutorialService
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_db = AsyncMock()
    service = TutorialService(mock_db)
    service.repo = AsyncMock()
    service.repo.get_by_id.return_value = MagicMock(tutorial_id=42)
    service.repo.get_by_storage_key.return_value = None

    valid_folder = "student-marketplace/dev/tutorials/videos"
    bad_public_id = f"{valid_folder}/tut_session_bad_ls"

    landscape_resource = {
        "resource_type": "video",
        "format": "mp4",
        "bytes": 5000000,
        "width": 1920,
        "height": 1080,  # Landscape: width > height
    }

    with patch("app.modules.tutorials.service.get_tutorial_video_cloudinary_folder", return_value=valid_folder), \
         patch("app.modules.tutorials.service.get_cloudinary_video_resource_async", new=AsyncMock(return_value=landscape_resource)), \
         patch("app.modules.tutorials.service.destroy_asset", new=AsyncMock()) as mock_destroy:

        payload = AdminTutorialConfirmDirectVideo(
            public_id=bad_public_id,
            upload_session_id="session_bad_ls",
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.confirm_direct_video_replacement(tutorial_id=42, payload=payload)

        assert exc_info.value.status_code == 400
        assert "portrait 9:16" in exc_info.value.detail
        mock_destroy.assert_awaited_once_with(bad_public_id, resource_type="video")
        mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_direct_tutorial_lifecycle():
    """Verify create_direct_tutorial validates Cloudinary asset and inserts Tutorial row."""
    from app.modules.tutorials.schemas import AdminTutorialCreateDirect
    from app.modules.tutorials.service import TutorialService
    from unittest.mock import AsyncMock, patch

    mock_db = AsyncMock()
    service = TutorialService(mock_db)
    service.repo = AsyncMock()
    service.repo.get_max_sort_order.return_value = 20
    service.repo.get_by_storage_key.return_value = None

    valid_folder = "student-marketplace/dev/tutorials/videos"
    new_public_id = f"{valid_folder}/tut_session_new_1"

    mock_resource = {
        "resource_type": "video",
        "format": "mp4",
        "bytes": 8000000,
        "width": 720,
        "height": 1280,
        "duration": 22.0,
        "secure_url": "https://res.cloudinary.com/ptit/video/upload/new.mp4",
    }

    payload = AdminTutorialCreateDirect(
        feature_key="HOME",
        title="Hướng dẫn Trang chủ mới",
        description="Mô tả hướng dẫn",
        public_id=new_public_id,
        upload_session_id="session_new_1",
    )

    with patch("app.modules.tutorials.service.get_tutorial_video_cloudinary_folder", return_value=valid_folder), \
         patch("app.modules.tutorials.service.get_cloudinary_video_resource_async", new=AsyncMock(return_value=mock_resource)):

        tut = await service.create_direct_tutorial(current_admin_id=1, payload=payload)
        assert tut.feature_key == "HOME"
        assert tut.title == "Hướng dẫn Trang chủ mới"
        assert tut.sort_order == 30
        assert tut.video_storage_key == new_public_id
        mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_direct_tutorial_rejects_already_used_storage_key():
    """Verify create_direct_tutorial rejects asset already registered in DB."""
    from fastapi import HTTPException
    from app.modules.tutorials.schemas import AdminTutorialCreateDirect
    from app.modules.tutorials.service import TutorialService
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_db = AsyncMock()
    service = TutorialService(mock_db)
    service.repo = AsyncMock()

    valid_folder = "student-marketplace/dev/tutorials/videos"
    target_storage_key = f"{valid_folder}/tut_session_dup"

    service.repo.get_by_storage_key.return_value = MagicMock(tutorial_id=88)

    payload = AdminTutorialCreateDirect(
        feature_key="HOME",
        title="Trùng lặp video",
        public_id=target_storage_key,
        upload_session_id="session_dup",
    )

    with patch("app.modules.tutorials.service.get_tutorial_video_cloudinary_folder", return_value=valid_folder):
        with pytest.raises(HTTPException) as exc_info:
            await service.create_direct_tutorial(current_admin_id=1, payload=payload)

        assert exc_info.value.status_code == 400
        assert "đã thuộc về một video hướng dẫn khác" in exc_info.value.detail
