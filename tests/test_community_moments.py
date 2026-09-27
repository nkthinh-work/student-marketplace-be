import io
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import test_engine
from app.main import app
from app.modules.auth.dependencies import get_current_active_user, require_admin
from app.modules.community_moments.models import (
    CommunityMoment,
    CommunityMomentStatus,
)
from app.modules.users.models import User, UserRole, UserStatus


VALID_JPEG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
    b"\xff\xdb\x00C\x00" + b"\x08" * 64 +
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00"
    b"\xff\xd9"
)

VALID_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    b"\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
)

VALID_WEBP_BYTES = (
    b"RIFF\x1a\x00\x00\x00WEBPVP8 \x0e\x00\x00\x000\x01\x00\x9d\x01*\x01\x00\x01\x00\x00\x00"
)

SPOOFED_EXE_BYTES = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"


@pytest_asyncio.fixture
async def community_test_users(db_session: AsyncSession):
    student = User(
        email=f"moment_student_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Nguyễn Văn Sinh Viên",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    banned = User(
        email=f"moment_banned_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Tài Khoản Bị Khóa",
        role=UserRole.STUDENT.value,
        status=UserStatus.BANNED,
    )
    admin = User(
        email=f"moment_admin_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Quản Trị Viên",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add_all([student, banned, admin])
    await db_session.flush()
    return {"student": student, "banned": banned, "admin": admin}


def override_active_user(user: User):
    class OverrideContext:
        def __enter__(self):
            app.dependency_overrides[get_current_active_user] = lambda: user
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            app.dependency_overrides.pop(get_current_active_user, None)

    return OverrideContext()


def override_admin_user(admin: User):
    class OverrideAdminContext:
        def __enter__(self):
            app.dependency_overrides[require_admin] = lambda: admin
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            app.dependency_overrides.pop(require_admin, None)

    return OverrideAdminContext()


# ======================================================================
# 1. USER SUBMISSION TESTS
# ======================================================================

@pytest.mark.asyncio
async def test_submit_valid_jpeg(test_client: AsyncClient, community_test_users: dict):
    student = community_test_users["student"]
    mock_upload = {
        "secure_url": "https://res.cloudinary.com/ptit/image/upload/v123/moment1.jpg",
        "public_id": "student-marketplace/community-moments/moment1",
    }

    with override_active_user(student):
        with patch("app.modules.community_moments.service.upload_community_moment_image", return_value=mock_upload):
            files = {"file": ("moment.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
            data = {"note": "Giao lưu nhanh trước cổng A2 ✨"}
            res = await test_client.post("/api/v1/community-moments", files=files, data=data)
            assert res.status_code == 201
            resp = res.json()
            assert "moment_id" in resp
            assert resp["status"] == "PENDING"
            assert "created_at" in resp


@pytest.mark.asyncio
async def test_submit_valid_png_and_webp(test_client: AsyncClient, db_session: AsyncSession, community_test_users: dict):
    student = community_test_users["student"]

    # PNG test
    mock_upload_png = {
        "secure_url": "https://res.cloudinary.com/ptit/image/upload/v123/moment_png.png",
        "public_id": "student-marketplace/community-moments/moment_png",
    }
    with override_active_user(student):
        with patch("app.modules.community_moments.service.upload_community_moment_image", return_value=mock_upload_png):
            files = {"file": ("moment.png", io.BytesIO(VALID_PNG_BYTES), "image/png")}
            data = {"note": "Cuối cùng cũng săn được cuốn giáo trình mình cần 😆"}
            res = await test_client.post("/api/v1/community-moments", files=files, data=data)
            assert res.status_code == 201
            resp = res.json()
            assert resp["status"] == "PENDING"

    # Mark first approved so user can test WebP
    moment_row = await db_session.execute(
        select(CommunityMoment).where(CommunityMoment.moment_id == resp["moment_id"])
    )
    m = moment_row.scalar_one()
    m.status = CommunityMomentStatus.APPROVED.value
    await db_session.flush()

    # WebP test
    mock_upload_webp = {
        "secure_url": "https://res.cloudinary.com/ptit/image/upload/v123/moment_webp.webp",
        "public_id": "student-marketplace/community-moments/moment_webp",
    }
    with override_active_user(student):
        with patch("app.modules.community_moments.service.upload_community_moment_image", return_value=mock_upload_webp):
            files = {"file": ("moment.webp", io.BytesIO(VALID_WEBP_BYTES), "image/webp")}
            data = {"note": "Khoảnh khắc tuyệt vời tại hội trường"}
            res = await test_client.post("/api/v1/community-moments", files=files, data=data)
            assert res.status_code == 201


@pytest.mark.asyncio
async def test_submit_unauthenticated(test_client: AsyncClient):
    files = {"file": ("moment.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
    data = {"note": "Lời nhắn thử nghiệm"}
    res = await test_client.post("/api/v1/community-moments", files=files, data=data)
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_submit_banned_user(test_client: AsyncClient, community_test_users: dict):
    banned = community_test_users["banned"]
    with override_active_user(banned):
        files = {"file": ("moment.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
        data = {"note": "Lời nhắn bị cấm"}
        res = await test_client.post("/api/v1/community-moments", files=files, data=data)
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_submit_invalid_mime_and_magic(test_client: AsyncClient, community_test_users: dict):
    student = community_test_users["student"]
    with override_active_user(student):
        # Spoofed EXE disguised as JPG
        files = {"file": ("test.jpg", io.BytesIO(SPOOFED_EXE_BYTES), "image/jpeg")}
        data = {"note": "Lời nhắn hợp lệ"}
        res = await test_client.post("/api/v1/community-moments", files=files, data=data)
        assert res.status_code == 422

        # Plain text
        files = {"file": ("test.jpg", io.BytesIO(b"Hello world this is not an image"), "image/jpeg")}
        res = await test_client.post("/api/v1/community-moments", files=files, data=data)
        assert res.status_code == 422


@pytest.mark.asyncio
async def test_submit_oversized_image(test_client: AsyncClient, community_test_users: dict):
    student = community_test_users["student"]
    oversized = b"\xff\xd8\xff" + b"\x00" * (10 * 1024 * 1024 + 1)
    with override_active_user(student):
        files = {"file": ("large.jpg", io.BytesIO(oversized), "image/jpeg")}
        data = {"note": "Ảnh quá nặng"}
        res = await test_client.post("/api/v1/community-moments", files=files, data=data)
        assert res.status_code == 422


@pytest.mark.asyncio
async def test_submit_note_validations(test_client: AsyncClient, community_test_users: dict):
    student = community_test_users["student"]
    mock_upload = {
        "secure_url": "https://res.cloudinary.com/ptit/image/upload/v123/moment_note.jpg",
        "public_id": "student-marketplace/community-moments/moment_note",
    }

    with override_active_user(student):
        # 1. Missing note -> 422
        files = {"file": ("moment.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
        res_missing = await test_client.post("/api/v1/community-moments", files=files)
        assert res_missing.status_code == 422

        # 2. Blank note -> 422
        res_blank = await test_client.post(
            "/api/v1/community-moments", files=files, data={"note": "    "}
        )
        assert res_blank.status_code == 422

        # 3. Note > 80 chars -> 422
        long_note = "A" * 81
        res_long = await test_client.post(
            "/api/v1/community-moments", files=files, data={"note": long_note}
        )
        assert res_long.status_code == 422

        # 4. Note with newline \n or \r -> 422
        res_newline = await test_client.post(
            "/api/v1/community-moments", files=files, data={"note": "Dòng 1\nDòng 2"}
        )
        assert res_newline.status_code == 422

        res_cr = await test_client.post(
            "/api/v1/community-moments", files=files, data={"note": "Dòng 1\rDòng 2"}
        )
        assert res_cr.status_code == 422

        # 5. Note with forbidden control character -> 422
        res_ctrl = await test_client.post(
            "/api/v1/community-moments", files=files, data={"note": "Hello\x0cWorld"}
        )
        assert res_ctrl.status_code == 422

        # 6. Valid note with Vietnamese NFC and emoji -> 201
        with patch("app.modules.community_moments.service.upload_community_moment_image", return_value=mock_upload):
            res_ok = await test_client.post(
                "/api/v1/community-moments",
                files=files,
                data={"note": "Nhận giáo trình ngay trước giờ lên lớp 😆 ✨"},
            )
            assert res_ok.status_code == 201


# ======================================================================
# 2. ANTI-SPAM ONE PENDING RULE & CONCURRENCY
# ======================================================================

@pytest.mark.asyncio
async def test_one_pending_submission_limit(test_client: AsyncClient, db_session: AsyncSession, community_test_users: dict):
    student = community_test_users["student"]
    mock_upload = {
        "secure_url": "https://res.cloudinary.com/ptit/image/upload/v123/moment1.jpg",
        "public_id": "student-marketplace/community-moments/moment1",
    }

    with override_active_user(student):
        with patch("app.modules.community_moments.service.upload_community_moment_image", return_value=mock_upload):
            # 1. First upload succeeds -> PENDING
            files = {"file": ("moment1.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
            data = {"note": "Khoảnh khắc 1"}
            res = await test_client.post("/api/v1/community-moments", files=files, data=data)
            assert res.status_code == 201
            moment1_id = res.json()["moment_id"]

            # 2. Second upload while first is PENDING -> 409 Conflict
            files2 = {"file": ("moment2.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
            res2 = await test_client.post("/api/v1/community-moments", files=files2, data={"note": "Khoảnh khắc 2"})
            assert res2.status_code == 409
            detail = res2.json()["detail"]
            assert detail["code"] == "COMMUNITY_MOMENT_PENDING"

            # 3. First is rejected and hard-deleted -> user can submit again
            m1 = await db_session.get(CommunityMoment, moment1_id)
            await db_session.delete(m1)
            await db_session.flush()

            files3 = {"file": ("moment3.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
            res3 = await test_client.post("/api/v1/community-moments", files=files3, data={"note": "Khoảnh khắc 3"})
            assert res3.status_code == 201
            moment3_id = res3.json()["moment_id"]

            # 4. That one becomes APPROVED -> user can submit again
            m3 = await db_session.get(CommunityMoment, moment3_id)
            m3.status = CommunityMomentStatus.APPROVED.value
            await db_session.flush()

            files4 = {"file": ("moment4.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
            res4 = await test_client.post("/api/v1/community-moments", files=files4, data={"note": "Khoảnh khắc 4"})
            assert res4.status_code == 201


@pytest.mark.asyncio
async def test_concurrent_same_user_submissions():
    async with test_engine.connect() as setup_conn:
        setup_trans = await setup_conn.begin()
        setup_sess = AsyncSession(bind=setup_conn, expire_on_commit=False)
        test_user = User(
            email=f"concurrent_moment_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
            full_name="Concurrent Tester",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
        )
        setup_sess.add(test_user)
        await setup_sess.flush()
        user_id = test_user.user_id
        await setup_trans.commit()
        await setup_sess.close()

    try:
        async with test_engine.connect() as conn1, test_engine.connect() as conn2:
            trans1 = await conn1.begin()
            trans2 = await conn2.begin()
            sess1 = AsyncSession(bind=conn1, expire_on_commit=False)
            sess2 = AsyncSession(bind=conn2, expire_on_commit=False)

            m1 = CommunityMoment(
                uploader_id=user_id,
                image_url="https://res.cloudinary.com/demo/image1.jpg",
                storage_key="key1",
                mime_type="image/jpeg",
                size_bytes=1000,
                note="Note 1",
                status=CommunityMomentStatus.PENDING.value,
            )
            m2 = CommunityMoment(
                uploader_id=user_id,
                image_url="https://res.cloudinary.com/demo/image2.jpg",
                storage_key="key2",
                mime_type="image/jpeg",
                size_bytes=1000,
                note="Note 2",
                status=CommunityMomentStatus.PENDING.value,
            )

            sess1.add(m1)
            await sess1.flush()
            await trans1.commit()

            # Session 2 attempts to insert another PENDING row for same user
            sess2.add(m2)
            with pytest.raises(Exception) as exc_info:
                await sess2.flush()
                await trans2.commit()

            assert "uq_community_moments_user_pending" in str(exc_info.value)
            await trans2.rollback()
            await sess1.close()
            await sess2.close()
    finally:
        async with test_engine.connect() as clean_conn:
            clean_trans = await clean_conn.begin()
            clean_sess = AsyncSession(bind=clean_conn, expire_on_commit=False)
            moments = await clean_sess.execute(select(CommunityMoment).where(CommunityMoment.uploader_id == user_id))
            for m in moments.scalars().all():
                await clean_sess.delete(m)
            u = await clean_sess.get(User, user_id)
            if u:
                await clean_sess.delete(u)
            await clean_trans.commit()
            await clean_sess.close()


# ======================================================================
# 3. CLOUDINARY COMPENSATION TEST
# ======================================================================

@pytest.mark.asyncio
async def test_cloudinary_compensation_on_db_error(test_client: AsyncClient, community_test_users: dict):
    student = community_test_users["student"]
    mock_upload = {
        "secure_url": "https://res.cloudinary.com/ptit/image/upload/v123/moment_comp.jpg",
        "public_id": "student-marketplace/community-moments/moment_comp",
    }

    with override_active_user(student):
        with patch("app.modules.community_moments.service.upload_community_moment_image", return_value=mock_upload):
            with patch("app.modules.community_moments.repository.CommunityMomentRepository.create", side_effect=RuntimeError("Simulated DB crash")):
                with patch("app.modules.community_moments.service.destroy_image") as mock_destroy:
                    files = {"file": ("moment.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
                    data = {"note": "Khoảnh khắc bù trừ"}
                    res = await test_client.post("/api/v1/community-moments", files=files, data=data)
                    assert res.status_code == 500
                    mock_destroy.assert_called_once_with(mock_upload["public_id"])


# ======================================================================
# 4. ADMIN MODERATION QUEUE & ACTIONS WITH NOTE
# ======================================================================

@pytest.mark.asyncio
async def test_admin_queue_authorization(test_client: AsyncClient, community_test_users: dict):
    student = community_test_users["student"]
    admin = community_test_users["admin"]

    app.dependency_overrides[get_current_active_user] = lambda: student
    app.dependency_overrides[require_admin] = lambda: (_ for _ in ()).throw(
        pytest.importorskip("fastapi").HTTPException(status_code=403, detail="Admin role required")
    )
    res_student = await test_client.get("/api/v1/admin/community-moments")
    assert res_student.status_code == 403

    app.dependency_overrides[require_admin] = lambda: admin
    res_admin = await test_client.get("/api/v1/admin/community-moments")
    assert res_admin.status_code == 200
    assert "items" in res_admin.json()
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_approve_and_reject_workflow(test_client: AsyncClient, db_session: AsyncSession, community_test_users: dict):
    student = community_test_users["student"]
    admin = community_test_users["admin"]

    m1 = CommunityMoment(
        uploader_id=student.user_id,
        image_url="https://res.cloudinary.com/ptit/image/upload/v123/m1.jpg",
        storage_key="m1_key",
        mime_type="image/jpeg",
        size_bytes=2000,
        note="Nhận được sách ngay trước tiết học 😆",
        status=CommunityMomentStatus.PENDING.value,
    )
    db_session.add(m1)
    await db_session.flush()

    with override_admin_user(admin):
        # 1. Admin queue includes note preview
        res_list = await test_client.get("/api/v1/admin/community-moments?status=PENDING")
        assert res_list.status_code == 200
        list_items = res_list.json()["items"]
        assert any(it["moment_id"] == m1.moment_id and it["note"] == m1.note for it in list_items)

        # 2. Admin views detail with note
        res = await test_client.get(f"/api/v1/admin/community-moments/{m1.moment_id}")
        assert res.status_code == 200
        detail = res.json()
        assert detail["status"] == "PENDING"
        assert detail["note"] == "Nhận được sách ngay trước tiết học 😆"
        assert detail["uploader"]["user_id"] == student.user_id
        assert detail["reviewer"] is None

        # 3. Admin approves
        res_app = await test_client.post(f"/api/v1/admin/community-moments/{m1.moment_id}/approve")
        assert res_app.status_code == 200
        data_app = res_app.json()
        assert data_app["status"] == "APPROVED"
        assert data_app["note"] == m1.note
        assert data_app["reviewer"]["user_id"] == admin.user_id
        assert data_app["reviewed_at"] is not None

        # 4. Cannot approve or reject already APPROVED moment (terminal) -> 409
        res_app_again = await test_client.post(f"/api/v1/admin/community-moments/{m1.moment_id}/approve")
        assert res_app_again.status_code == 409

        res_rej_after_app = await test_client.post(f"/api/v1/admin/community-moments/{m1.moment_id}/reject")
        assert res_rej_after_app.status_code == 409

    # Test reject on a second pending moment
    m2 = CommunityMoment(
        uploader_id=student.user_id,
        image_url="https://res.cloudinary.com/ptit/image/upload/v123/m2.jpg",
        storage_key="m2_key",
        mime_type="image/jpeg",
        size_bytes=3000,
        note="Khoảnh khắc thứ hai",
        status=CommunityMomentStatus.PENDING.value,
    )
    db_session.add(m2)
    await db_session.flush()

    with override_admin_user(admin):
        res_rej = await test_client.post(f"/api/v1/admin/community-moments/{m2.moment_id}/reject")
        assert res_rej.status_code == 200
        assert res_rej.json()["status"] == "REJECTED"

        # Cannot reject again (already hard-deleted -> 404)
        res_rej_again = await test_client.post(f"/api/v1/admin/community-moments/{m2.moment_id}/reject")
        assert res_rej_again.status_code == 404


# ======================================================================
# 5. PUBLIC HERO CONTRACT & PRIVACY & LEGACY NULL NOTE
# ======================================================================

@pytest.mark.asyncio
async def test_public_hero_bounded_and_privacy(test_client: AsyncClient, db_session: AsyncSession, community_test_users: dict):
    student = community_test_users["student"]
    admin = community_test_users["admin"]

    await db_session.execute(delete(CommunityMoment))
    await db_session.flush()

    # 1. Initially 0 approved
    res = await test_client.get("/api/v1/community-moments/hero")
    assert res.status_code == 200
    assert res.json()["items"] == []

    # 2. Insert 5 approved moments with note + 1 legacy approved moment with note=NULL + 1 pending + 1 rejected
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for i in range(1, 6):
        m = CommunityMoment(
            uploader_id=student.user_id,
            image_url=f"https://res.cloudinary.com/ptit/image/upload/v123/hero_{i}.jpg",
            storage_key=f"hero_key_{i}",
            mime_type="image/jpeg",
            size_bytes=1000 * i,
            note=f"Khoảnh khắc {i} cùng bạn bè",
            status=CommunityMomentStatus.APPROVED.value,
            reviewed_by=admin.user_id,
            reviewed_at=datetime(2026, 9, 21, 10, i, 0),
        )
        db_session.add(m)

    # Legacy row with note=NULL
    legacy_m = CommunityMoment(
        uploader_id=student.user_id,
        image_url="https://res.cloudinary.com/ptit/image/upload/v123/hero_legacy.jpg",
        storage_key="hero_key_legacy",
        mime_type="image/jpeg",
        size_bytes=1500,
        note=None,
        status=CommunityMomentStatus.APPROVED.value,
        reviewed_by=admin.user_id,
        reviewed_at=datetime(2026, 9, 21, 10, 6, 0),
    )
    pending_m = CommunityMoment(
        uploader_id=student.user_id,
        image_url="https://res.cloudinary.com/ptit/image/upload/v123/hero_pending.jpg",
        storage_key="hero_key_pending",
        mime_type="image/jpeg",
        size_bytes=999,
        note="Pending note - never public",
        status=CommunityMomentStatus.PENDING.value,
    )
    rejected_m = CommunityMoment(
        uploader_id=student.user_id,
        image_url="https://res.cloudinary.com/ptit/image/upload/v123/hero_rejected.jpg",
        storage_key="hero_key_rejected",
        mime_type="image/jpeg",
        size_bytes=999,
        note="Rejected note - never public",
        status=CommunityMomentStatus.REJECTED.value,
        reviewed_by=admin.user_id,
        reviewed_at=now,
    )
    db_session.add_all([legacy_m, pending_m, rejected_m])
    await db_session.flush()

    # 3. Public query: exactly top 5, ordered newest reviewed_at first
    res_hero = await test_client.get("/api/v1/community-moments/hero")
    assert res_hero.status_code == 200
    hero_items = res_hero.json()["items"]

    # Must be capped at 5
    assert len(hero_items) == 5

    # Newest is legacy_m (reviewed_at 10:06), note is None, appended to the right (last index)
    assert "hero_legacy.jpg" in hero_items[-1]["image_url"]
    assert hero_items[-1]["note"] is None

    # First item is the oldest retained (Moment 2)
    assert hero_items[0]["note"] == "Khoảnh khắc 2 cùng bạn bè"

    # Pending and rejected excluded
    for item in hero_items:
        assert "hero_pending.jpg" not in item["image_url"]
        assert "hero_rejected.jpg" not in item["image_url"]
        assert "never public" not in (item["note"] or "")

        # PRIVACY AUDIT: NO uploader_id, NO storage_key, NO reviewer
        assert "uploader_id" not in item
        assert "uploader" not in item
        assert "storage_key" not in item
        assert "reviewed_by" not in item
        assert "reviewer" not in item


# ======================================================================
# 6. LIFECYCLE, PRUNING & CLOUDINARY CLEANUP TESTS (PHASE 8H-A.2)
# ======================================================================

@pytest.mark.asyncio
async def test_only_one_cloudinary_upload_on_submission(test_client: AsyncClient, community_test_users: dict):
    student = community_test_users["student"]
    mock_upload = {
        "secure_url": "https://res.cloudinary.com/ptit/image/upload/v123/moment_single.jpg",
        "public_id": "student-marketplace/community-moments/moment_single",
    }

    with override_active_user(student):
        with patch("app.modules.community_moments.service.upload_community_moment_image", return_value=mock_upload) as mock_up:
            files = {"file": ("cropped.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
            data = {"note": "Khoảnh khắc duy nhất"}
            res = await test_client.post("/api/v1/community-moments", files=files, data=data)
            assert res.status_code == 201
            # Explicit assertion: only ONE upload call occurs
            assert mock_up.call_count == 1


@pytest.mark.asyncio
async def test_reject_hard_deletes_and_calls_destroy(test_client: AsyncClient, db_session: AsyncSession, community_test_users: dict):
    student = community_test_users["student"]
    admin = community_test_users["admin"]

    m = CommunityMoment(
        uploader_id=student.user_id,
        image_url="https://res.cloudinary.com/ptit/image/upload/v123/to_reject.jpg",
        storage_key="key_to_reject",
        mime_type="image/jpeg",
        size_bytes=2000,
        note="Ảnh này sẽ bị từ chối",
        status=CommunityMomentStatus.PENDING.value,
    )
    db_session.add(m)
    await db_session.flush()
    moment_id = m.moment_id

    with override_admin_user(admin):
        with patch("app.modules.community_moments.service.destroy_image") as mock_destroy:
            res = await test_client.post(f"/api/v1/admin/community-moments/{moment_id}/reject")
            assert res.status_code == 200
            assert res.json()["status"] == "REJECTED"

            # DB row is gone
            row = await db_session.get(CommunityMoment, moment_id)
            assert row is None

            # Cloudinary cleanup called post-commit
            mock_destroy.assert_called_once_with("key_to_reject")


@pytest.mark.asyncio
async def test_sixth_approval_prunes_oldest_approved(test_client: AsyncClient, db_session: AsyncSession, community_test_users: dict):
    student = community_test_users["student"]
    admin = community_test_users["admin"]

    # Clear table
    await db_session.execute(delete(CommunityMoment))
    await db_session.flush()

    # Insert 5 approved moments
    for i in range(1, 6):
        approved_m = CommunityMoment(
            uploader_id=student.user_id,
            image_url=f"https://res.cloudinary.com/ptit/image/upload/v123/approved_{i}.jpg",
            storage_key=f"key_approved_{i}",
            mime_type="image/jpeg",
            size_bytes=1000 * i,
            note=f"Đã duyệt {i}",
            status=CommunityMomentStatus.APPROVED.value,
            reviewed_by=admin.user_id,
            reviewed_at=datetime(2026, 9, 21, 10, i, 0),
        )
        db_session.add(approved_m)

    # Insert 6th pending moment
    pending_m = CommunityMoment(
        uploader_id=student.user_id,
        image_url="https://res.cloudinary.com/ptit/image/upload/v123/pending_sixth.jpg",
        storage_key="key_pending_sixth",
        mime_type="image/jpeg",
        size_bytes=6000,
        note="Ảnh thứ 6",
        status=CommunityMomentStatus.PENDING.value,
    )
    db_session.add(pending_m)
    await db_session.flush()

    sixth_id = pending_m.moment_id

    with override_admin_user(admin):
        with patch("app.modules.community_moments.service.destroy_image") as mock_destroy:
            res = await test_client.post(f"/api/v1/admin/community-moments/{sixth_id}/approve")
            assert res.status_code == 200
            assert res.json()["status"] == "APPROVED"

            # Check DB count: must be <= 5 approved
            res_all = await db_session.execute(
                select(CommunityMoment).where(CommunityMoment.status == CommunityMomentStatus.APPROVED.value)
            )
            rows = res_all.scalars().all()
            assert len(rows) == 5

            # Oldest moment (approved_1 with reviewed_at 10:01) must be pruned
            pruned_row = await db_session.execute(
                select(CommunityMoment).where(CommunityMoment.storage_key == "key_approved_1")
            )
            assert pruned_row.scalar_one_or_none() is None

            # Cloudinary cleanup called for key_approved_1
            mock_destroy.assert_called_once_with("key_approved_1")


@pytest.mark.asyncio
async def test_admin_delete_approved_hero_moment(test_client: AsyncClient, db_session: AsyncSession, community_test_users: dict):
    student = community_test_users["student"]
    admin = community_test_users["admin"]

    m = CommunityMoment(
        uploader_id=student.user_id,
        image_url="https://res.cloudinary.com/ptit/image/upload/v123/hero_to_delete.jpg",
        storage_key="key_hero_to_delete",
        mime_type="image/jpeg",
        size_bytes=3000,
        note="Ảnh xóa khỏi hero",
        status=CommunityMomentStatus.APPROVED.value,
        reviewed_by=admin.user_id,
        reviewed_at=datetime(2026, 9, 21, 12, 0, 0),
    )
    db_session.add(m)
    await db_session.flush()
    moment_id = m.moment_id

    with override_admin_user(admin):
        with patch("app.modules.community_moments.service.destroy_image") as mock_destroy:
            res = await test_client.delete(f"/api/v1/admin/community-moments/{moment_id}")
            assert res.status_code == 200
            assert res.json()["status"] == "DELETED"

            # DB row is gone
            row = await db_session.get(CommunityMoment, moment_id)
            assert row is None

            # Cloudinary destroy called
            mock_destroy.assert_called_once_with("key_hero_to_delete")

            # Cannot delete again -> 404
            res_again = await test_client.delete(f"/api/v1/admin/community-moments/{moment_id}")
            assert res_again.status_code == 404


@pytest.mark.asyncio
async def test_cloudinary_destroy_failure_does_not_rollback_db(test_client: AsyncClient, db_session: AsyncSession, community_test_users: dict):
    student = community_test_users["student"]
    admin = community_test_users["admin"]

    m = CommunityMoment(
        uploader_id=student.user_id,
        image_url="https://res.cloudinary.com/ptit/image/upload/v123/destroy_fail.jpg",
        storage_key="key_destroy_fail",
        mime_type="image/jpeg",
        size_bytes=2500,
        note="Ảnh lỗi destroy",
        status=CommunityMomentStatus.PENDING.value,
    )
    db_session.add(m)
    await db_session.flush()
    moment_id = m.moment_id

    with override_admin_user(admin):
        with patch("app.modules.community_moments.service.destroy_image", side_effect=Exception("Simulated Cloudinary 503 error")):
            res = await test_client.post(f"/api/v1/admin/community-moments/{moment_id}/reject")
            # Operation must succeed at business layer
            assert res.status_code == 200
            assert res.json()["status"] == "REJECTED"

            # DB row remains committed and deleted (no resurrection)
            row = await db_session.get(CommunityMoment, moment_id)
            assert row is None


@pytest.mark.asyncio
async def test_concurrent_approve_and_delete_separate_sessions():
    async with test_engine.connect() as setup_conn:
        setup_trans = await setup_conn.begin()
        setup_sess = AsyncSession(bind=setup_conn, expire_on_commit=False)
        u = User(
            email=f"concurrent_lifecycle_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
            full_name="Lifecycle Tester",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
        )
        adm = User(
            email=f"concurrent_adm_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
            full_name="Lifecycle Admin",
            role=UserRole.ADMIN.value,
            status=UserStatus.ACTIVE,
        )
        setup_sess.add_all([u, adm])
        await setup_sess.flush()
        u_id = u.user_id
        adm_id = adm.user_id

        # Insert 1 pending moment and 1 approved moment
        pending = CommunityMoment(
            uploader_id=u_id,
            image_url="https://res.cloudinary.com/demo/p1.jpg",
            storage_key="p1_key",
            mime_type="image/jpeg",
            size_bytes=1000,
            note="Pending 1",
            status=CommunityMomentStatus.PENDING.value,
        )
        approved = CommunityMoment(
            uploader_id=u_id,
            image_url="https://res.cloudinary.com/demo/a1.jpg",
            storage_key="a1_key",
            mime_type="image/jpeg",
            size_bytes=1000,
            note="Approved 1",
            status=CommunityMomentStatus.APPROVED.value,
            reviewed_by=adm_id,
            reviewed_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        setup_sess.add_all([pending, approved])
        await setup_sess.flush()
        p_id = pending.moment_id
        a_id = approved.moment_id
        await setup_trans.commit()
        await setup_sess.close()

    try:
        from app.modules.community_moments.service import CommunityMomentService
        async with test_engine.connect() as conn1, test_engine.connect() as conn2:
            sess1 = AsyncSession(bind=conn1, expire_on_commit=False)
            sess2 = AsyncSession(bind=conn2, expire_on_commit=False)
            admin_user = await sess1.get(User, adm_id)

            svc1 = CommunityMomentService(sess1)
            svc2 = CommunityMomentService(sess2)

            with patch("app.modules.community_moments.service.destroy_image"):
                # Run approve on sess1 and delete on sess2
                app_res = await svc1.approve_moment(admin_user, p_id)
                del_res = await svc2.delete_admin_moment(admin_user, a_id)

                assert app_res.status == "APPROVED"
                assert del_res.status == "DELETED"

            await sess1.close()
            await sess2.close()
    finally:
        async with test_engine.connect() as clean_conn:
            clean_trans = await clean_conn.begin()
            clean_sess = AsyncSession(bind=clean_conn, expire_on_commit=False)
            moments = await clean_sess.execute(select(CommunityMoment).where(CommunityMoment.uploader_id == u_id))
            for m in moments.scalars().all():
                await clean_sess.delete(m)
            for uid in [u_id, adm_id]:
                usr = await clean_sess.get(User, uid)
                if usr:
                    await clean_sess.delete(usr)
            await clean_trans.commit()
            await clean_sess.close()


@pytest.mark.asyncio
async def test_concurrent_approve_and_reject_same_pending():
    async with test_engine.connect() as setup_conn:
        setup_trans = await setup_conn.begin()
        setup_sess = AsyncSession(bind=setup_conn, expire_on_commit=False)
        u = User(
            email=f"race_pend_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
            full_name="Race Tester",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
        )
        adm = User(
            email=f"race_adm_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
            full_name="Race Admin",
            role=UserRole.ADMIN.value,
            status=UserStatus.ACTIVE,
        )
        setup_sess.add_all([u, adm])
        await setup_sess.flush()
        u_id = u.user_id
        adm_id = adm.user_id

        target = CommunityMoment(
            uploader_id=u_id,
            image_url="https://res.cloudinary.com/demo/race_target.jpg",
            storage_key="race_target_key",
            mime_type="image/jpeg",
            size_bytes=1000,
            note="Race target",
            status=CommunityMomentStatus.PENDING.value,
        )
        setup_sess.add(target)
        await setup_sess.flush()
        target_id = target.moment_id
        await setup_trans.commit()
        await setup_sess.close()

    try:
        from app.modules.community_moments.service import CommunityMomentService
        from fastapi import HTTPException
        async with test_engine.connect() as conn1, test_engine.connect() as conn2:
            sess1 = AsyncSession(bind=conn1, expire_on_commit=False)
            sess2 = AsyncSession(bind=conn2, expire_on_commit=False)
            admin_user = await sess1.get(User, adm_id)

            svc1 = CommunityMomentService(sess1)
            svc2 = CommunityMomentService(sess2)

            with patch("app.modules.community_moments.service.destroy_image"):
                # Session 1 approves
                await svc1.approve_moment(admin_user, target_id)

                # Session 2 attempts reject on now APPROVED moment -> 409
                with pytest.raises(HTTPException) as exc_info:
                    await svc2.reject_moment(admin_user, target_id)
                assert exc_info.value.status_code == 409

            await sess1.close()
            await sess2.close()
    finally:
        async with test_engine.connect() as clean_conn:
            clean_trans = await clean_conn.begin()
            clean_sess = AsyncSession(bind=clean_conn, expire_on_commit=False)
            moments = await clean_sess.execute(select(CommunityMoment).where(CommunityMoment.uploader_id == u_id))
            for m in moments.scalars().all():
                await clean_sess.delete(m)
            for uid in [u_id, adm_id]:
                usr = await clean_sess.get(User, uid)
                if usr:
                    await clean_sess.delete(usr)
            await clean_trans.commit()
            await clean_sess.close()
