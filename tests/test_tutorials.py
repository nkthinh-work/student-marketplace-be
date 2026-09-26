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
        assert "vc_auto" in res_small["secure_url"]

        # Case 2: Large video (> 20 MB) uses upload_large with chunk_size
        large_size = 25 * 1024 * 1024
        res_large = _upload_tutorial_video_sync(io.BytesIO(VALID_MP4_BYTES), filename="large.mp4", file_size=large_size)
        mock_large_upload.assert_called_once()
        assert mock_large_upload.call_args[1]["resource_type"] == "video"
        assert mock_large_upload.call_args[1]["chunk_size"] == 20 * 1024 * 1024
        assert "vc_auto" in res_large["secure_url"]


def test_upload_tutorial_video_invalid_provider_response_rejected():
    """Section 29: If Cloudinary returns wrong resource_type or invalid response, reject safely."""
    with patch("cloudinary.uploader.upload", return_value={"resource_type": "image", "public_id": "bad/id"}):
        with pytest.raises(CloudinaryUploadError, match="unexpected resource_type"):
            _upload_tutorial_video_sync(io.BytesIO(VALID_MP4_BYTES), filename="test.mp4")

    with patch("cloudinary.uploader.upload", return_value={"resource_type": "video", "public_id": "no/url"}):
        with pytest.raises(CloudinaryUploadError, match="valid delivery URL"):
            _upload_tutorial_video_sync(io.BytesIO(VALID_MP4_BYTES), filename="test.mp4")


