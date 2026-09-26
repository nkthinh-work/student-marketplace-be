import io
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.auth.dependencies import (
    get_current_active_user,
    get_current_user,
    require_admin,
)
from app.modules.community_moments.models import CommunityMoment
from app.modules.feedback.models import SiteFeedback, SupportClaim
from app.modules.notifications.models import Notification
from app.modules.reports.models import Report, ReportReason, ReportTargetType
from app.modules.users.models import User, UserRole, UserStatus

VALID_JPEG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
    b"\xff\xdb\x00C\x00" + b"\x08" * 64 +
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00"
    b"\xff\xd9"
)


def auth_override(user: User):
    class CleanCtx:
        def __enter__(self):
            app.dependency_overrides[get_current_user] = lambda: user
            app.dependency_overrides[get_current_active_user] = lambda: user
            if user.role == UserRole.ADMIN.value:
                app.dependency_overrides[require_admin] = lambda: user
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(require_admin, None)

    return CleanCtx()


@pytest_asyncio.fixture
async def setup_notification_actors(db_session: AsyncSession):
    # Active Admin 1
    admin1 = User(
        email=f"admin1_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Quản Trị Viên Một",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    # Active Admin 2
    admin2 = User(
        email=f"admin2_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Quản Trị Viên Hai",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    # Inactive Admin (must not receive admin notifications)
    admin_inactive = User(
        email=f"admin_inact_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Quản Trị Nghỉ Việc",
        role=UserRole.ADMIN.value,
        status=UserStatus.INACTIVE,
    )
    # Student 1 (reporter / submitter)
    student1 = User(
        email=f"stud1_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Sinh Viên Thường 1",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    # Student 2 (reported subject / counterparty)
    student2 = User(
        email=f"stud2_{uuid.uuid4().hex[:8]}@ptit.edu.vn",
        full_name="Sinh Viên Thường 2",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )

    db_session.add_all([admin1, admin2, admin_inactive, student1, student2])
    await db_session.commit()
    await db_session.refresh(admin1)
    await db_session.refresh(admin2)
    await db_session.refresh(admin_inactive)
    await db_session.refresh(student1)
    await db_session.refresh(student2)

    return {
        "admin1": admin1,
        "admin2": admin2,
        "admin_inactive": admin_inactive,
        "student1": student1,
        "student2": student2,
    }


@pytest.mark.asyncio
async def test_admin_notifications_fanout_all_events(
    test_client: AsyncClient,
    setup_notification_actors: dict,
    db_session: AsyncSession,
):
    admin1 = setup_notification_actors["admin1"]
    admin2 = setup_notification_actors["admin2"]
    admin_inactive = setup_notification_actors["admin_inactive"]
    student1 = setup_notification_actors["student1"]
    student2 = setup_notification_actors["student2"]

    # -------------------------------------------------------------
    # 1. Event 1: New Report created by student1 against student2
    # -------------------------------------------------------------
    with auth_override(student1):
        report_res = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_id": student2.user_id,
                "reason": "SCAM",
                "description": "Gian lận bán hàng lừa đảo",
            },
        )
        assert report_res.status_code == 201
        report_id = report_res.json()["report_id"]

    # Verify notifications created for both active admins
    stmt = select(Notification).where(
        Notification.ref_type == "ADMIN_REPORT",
        Notification.ref_id == report_id,
    )
    res = await db_session.execute(stmt)
    report_notifs = list(res.scalars().all())
    recipient_ids = {n.user_id for n in report_notifs}
    assert admin1.user_id in recipient_ids
    assert admin2.user_id in recipient_ids
    assert admin_inactive.user_id not in recipient_ids
    assert student1.user_id not in recipient_ids
    assert student2.user_id not in recipient_ids

    assert len([n for n in report_notifs if n.user_id == admin1.user_id]) == 1
    assert len([n for n in report_notifs if n.user_id == admin2.user_id]) == 1

    admin1_notif = [n for n in report_notifs if n.user_id == admin1.user_id][0]
    assert admin1_notif.type == "SYSTEM"
    assert admin1_notif.title == "Có báo cáo vi phạm mới"
    assert "Gian lận bán hàng lừa đảo" not in admin1_notif.body  # Privacy: no raw description
    assert student1.email not in admin1_notif.body  # Privacy: no email

    # -------------------------------------------------------------
    # 2. Event 2: New Community Moment uploaded by student1
    # -------------------------------------------------------------
    mock_upload = {
        "secure_url": "https://res.cloudinary.com/ptit/image/upload/v123/moment1.jpg",
        "public_id": "student-marketplace/community-moments/moment1",
    }
    with auth_override(student1):
        with patch(
            "app.modules.community_moments.service.upload_community_moment_image",
            return_value=mock_upload,
        ):
            files = {"file": ("moment.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
            data = {"note": "Khoảnh khắc sân khấu A2"}
            moment_res = await test_client.post(
                "/api/v1/community-moments", files=files, data=data
            )
            assert moment_res.status_code == 201
            moment_id = moment_res.json()["moment_id"]

    stmt = select(Notification).where(
        Notification.ref_type == "ADMIN_COMMUNITY",
        Notification.ref_id == moment_id,
    )
    res = await db_session.execute(stmt)
    moment_notifs = list(res.scalars().all())
    recipient_ids = {n.user_id for n in moment_notifs}
    assert admin1.user_id in recipient_ids
    assert admin2.user_id in recipient_ids
    assert admin_inactive.user_id not in recipient_ids
    assert student1.user_id not in recipient_ids

    assert len([n for n in moment_notifs if n.user_id == admin1.user_id]) == 1
    assert len([n for n in moment_notifs if n.user_id == admin2.user_id]) == 1

    admin1_m = [n for n in moment_notifs if n.user_id == admin1.user_id][0]
    assert admin1_m.type == "SYSTEM"
    assert admin1_m.title == "Có ảnh cộng đồng mới chờ duyệt"
    assert "student-marketplace" not in admin1_m.body  # No cloudinary key leak

    # -------------------------------------------------------------
    # 3. Event 3: New Site Feedback submitted by student1
    # -------------------------------------------------------------
    with auth_override(student1):
        fb_res = await test_client.post(
            "/api/v1/feedback",
            data={
                "content": "Mong muốn có chế độ dark mode khi dùng ban đêm.",
            },
        )
        assert fb_res.status_code == 201
        feedback_id = fb_res.json()["feedback_id"]

    stmt = select(Notification).where(
        Notification.ref_type == "ADMIN_FEEDBACK",
        Notification.ref_id == feedback_id,
    )
    res = await db_session.execute(stmt)
    fb_notifs = list(res.scalars().all())
    recipient_ids = {n.user_id for n in fb_notifs}
    assert admin1.user_id in recipient_ids
    assert admin2.user_id in recipient_ids
    assert admin_inactive.user_id not in recipient_ids
    assert student1.user_id not in recipient_ids

    assert len([n for n in fb_notifs if n.user_id == admin1.user_id]) == 1
    assert len([n for n in fb_notifs if n.user_id == admin2.user_id]) == 1

    admin1_fb = [n for n in fb_notifs if n.user_id == admin1.user_id][0]
    assert admin1_fb.type == "SYSTEM"
    assert admin1_fb.title == "Có phản hồi mới"

    # -------------------------------------------------------------
    # 4. Event 4: New Support Claim submitted by student1
    # -------------------------------------------------------------
    with auth_override(student1):
        claim_res = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "claimed_transferred_at": datetime.now(timezone.utc).isoformat(),
                "claimed_amount_vnd": 50000,
                "sender_account_name": "NGUYEN VAN SINH VIEN 1",
                "wants_public": True,
            },
        )
        assert claim_res.status_code == 201
        claim_id = claim_res.json()["claim_id"]

    stmt = select(Notification).where(
        Notification.ref_type == "ADMIN_SUPPORT_CLAIM",
        Notification.ref_id == claim_id,
    )
    res = await db_session.execute(stmt)
    claim_notifs = list(res.scalars().all())
    recipient_ids = {n.user_id for n in claim_notifs}
    assert admin1.user_id in recipient_ids
    assert admin2.user_id in recipient_ids
    assert admin_inactive.user_id not in recipient_ids
    assert student1.user_id not in recipient_ids

    assert len([n for n in claim_notifs if n.user_id == admin1.user_id]) == 1
    assert len([n for n in claim_notifs if n.user_id == admin2.user_id]) == 1

    admin1_cl = [n for n in claim_notifs if n.user_id == admin1.user_id][0]
    assert admin1_cl.type == "SYSTEM"
    assert admin1_cl.title == "Có khoản ủng hộ chờ đối soát"


@pytest.mark.asyncio
async def test_community_moment_user_outcomes(
    test_client: AsyncClient,
    setup_notification_actors: dict,
    db_session: AsyncSession,
):
    admin1 = setup_notification_actors["admin1"]
    student1 = setup_notification_actors["student1"]

    # 1. Approve Moment
    mock_upload = {
        "secure_url": "https://res.cloudinary.com/ptit/image/upload/v123/moment_appr.jpg",
        "public_id": "student-marketplace/community-moments/moment_appr",
    }
    with auth_override(student1):
        with patch(
            "app.modules.community_moments.service.upload_community_moment_image",
            return_value=mock_upload,
        ):
            files = {"file": ("moment.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
            data = {"note": "Khoảnh khắc được duyệt"}
            res = await test_client.post(
                "/api/v1/community-moments", files=files, data=data
            )
            assert res.status_code == 201
            appr_moment_id = res.json()["moment_id"]

    # Admin approves
    with auth_override(admin1):
        appr_res = await test_client.post(
            f"/api/v1/admin/community-moments/{appr_moment_id}/approve"
        )
        assert appr_res.status_code == 200

    # Verify uploader received APPROVED notification
    stmt = select(Notification).where(
        Notification.user_id == student1.user_id,
        Notification.ref_type == "COMMUNITY_MOMENT",
        Notification.ref_id == appr_moment_id,
    )
    res = await db_session.execute(stmt)
    uploader_notif = res.scalar_one_or_none()
    assert uploader_notif is not None
    assert uploader_notif.type == "SYSTEM"
    assert "đã được duyệt" in uploader_notif.title

    # Admin receives NO self-notification for approval
    stmt_admin = select(Notification).where(
        Notification.user_id == admin1.user_id,
        Notification.ref_type == "COMMUNITY_MOMENT",
        Notification.ref_id == appr_moment_id,
    )
    res_admin = await db_session.execute(stmt_admin)
    assert res_admin.scalar_one_or_none() is None

    # 2. Reject Moment (Hard delete + user notification)
    with auth_override(student1):
        with patch(
            "app.modules.community_moments.service.upload_community_moment_image",
            return_value=mock_upload,
        ):
            files = {"file": ("moment.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
            data = {"note": "Khoảnh khắc bị từ chối"}
            res = await test_client.post(
                "/api/v1/community-moments", files=files, data=data
            )
            assert res.status_code == 201
            rej_moment_id = res.json()["moment_id"]

    # Admin rejects
    with auth_override(admin1):
        with patch("app.modules.community_moments.service.destroy_image"):
            rej_res = await test_client.post(
                f"/api/v1/admin/community-moments/{rej_moment_id}/reject"
            )
            assert rej_res.status_code == 200

    # Verify moment is deleted from DB
    stmt_mom = select(CommunityMoment).where(
        CommunityMoment.moment_id == rej_moment_id
    )
    res_mom = await db_session.execute(stmt_mom)
    assert res_mom.scalar_one_or_none() is None

    # Verify uploader received REJECTED notification
    stmt_rej = select(Notification).where(
        Notification.user_id == student1.user_id,
        Notification.ref_type == "COMMUNITY_REJECTED",
        Notification.ref_id == rej_moment_id,
    )
    res_rej = await db_session.execute(stmt_rej)
    rej_notif = res_rej.scalar_one_or_none()
    assert rej_notif is not None
    assert rej_notif.type == "SYSTEM"
    assert "chưa được duyệt" in rej_notif.title


@pytest.mark.asyncio
async def test_report_terminal_user_outcomes(
    test_client: AsyncClient,
    setup_notification_actors: dict,
    db_session: AsyncSession,
):
    admin1 = setup_notification_actors["admin1"]
    student1 = setup_notification_actors["student1"]
    student2 = setup_notification_actors["student2"]

    # Student 1 reports Student 2
    with auth_override(student1):
        res = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_id": student2.user_id,
                "reason": "SPAM",
                "description": "Quấy rối nhắn tin spam",
            },
        )
        assert res.status_code == 201
        report_id = res.json()["report_id"]

    # 1. OPEN -> REVIEWING: MUST CREATE 0 REPORTER NOTIFICATIONS
    with auth_override(admin1):
        rev_res = await test_client.patch(
            f"/api/v1/admin/reports/{report_id}/status",
            json={"status": "REVIEWING"},
        )
        assert rev_res.status_code == 200

    stmt_rep = select(Notification).where(
        Notification.user_id == student1.user_id,
        Notification.ref_type == "REPORT",
        Notification.ref_id == report_id,
    )
    res_rep = await db_session.execute(stmt_rep)
    assert len(res_rep.scalars().all()) == 0

    # 2. REVIEWING -> RESOLVED: MUST CREATE EXACTLY 1 REPORTER NOTIFICATION
    with auth_override(admin1):
        res_resp = await test_client.patch(
            f"/api/v1/admin/reports/{report_id}/status",
            json={"status": "RESOLVED"},
        )
        assert res_resp.status_code == 200

    res_rep = await db_session.execute(stmt_rep)
    resolved_notifs = list(res_rep.scalars().all())
    assert len(resolved_notifs) == 1
    r_notif = resolved_notifs[0]
    assert r_notif.type == "SYSTEM"
    assert "đã được xử lý" in r_notif.title
    assert admin1.full_name not in r_notif.body  # No admin identity leak
    assert admin1.email not in r_notif.body

    # Reported subject (student2) must NOT receive reporter-outcome notification
    stmt_subj = select(Notification).where(
        Notification.user_id == student2.user_id,
        Notification.ref_type == "REPORT",
        Notification.ref_id == report_id,
    )
    res_subj = await db_session.execute(stmt_subj)
    assert len(res_subj.scalars().all()) == 0

    # 3. Another report: OPEN -> REJECTED: MUST CREATE EXACTLY 1 REPORTER NOTIFICATION
    with auth_override(student1):
        res2 = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_id": student2.user_id,
                "reason": "OTHER",
                "description": "Báo cáo lý do khác",
            },
        )
        assert res2.status_code == 201
        report2_id = res2.json()["report_id"]

    with auth_override(admin1):
        rej_res = await test_client.patch(
            f"/api/v1/admin/reports/{report2_id}/status",
            json={"status": "REJECTED"},
        )
        assert rej_res.status_code == 200

    stmt_rep2 = select(Notification).where(
        Notification.user_id == student1.user_id,
        Notification.ref_type == "REPORT",
        Notification.ref_id == report2_id,
    )
    res_rep2 = await db_session.execute(stmt_rep2)
    rejected_notifs = list(res_rep2.scalars().all())
    assert len(rejected_notifs) == 1
    rej_notif = rejected_notifs[0]
    assert rej_notif.type == "SYSTEM"
    assert "đã được xem xét" in rej_notif.title


@pytest.mark.asyncio
async def test_capability_restriction_and_restore_notifications(
    test_client: AsyncClient,
    setup_notification_actors: dict,
    db_session: AsyncSession,
):
    admin1 = setup_notification_actors["admin1"]
    student1 = setup_notification_actors["student1"]
    student2 = setup_notification_actors["student2"]

    # Student 1 reports Student 2
    with auth_override(student1):
        res = await test_client.post(
            "/api/v1/reports",
            json={
                "target_type": "USER",
                "target_id": student2.user_id,
                "reason": "SCAM",
                "description": "Gian lận bán hàng",
            },
        )
        assert res.status_code == 201
        report_id = res.json()["report_id"]

    # Admin restricts SELL capability for 7 days
    with auth_override(admin1):
        enforce_res = await test_client.post(
            f"/api/v1/admin/reports/{report_id}/enforcement",
            json={
                "action": "CAPABILITY_RESTRICT",
                "capabilities": ["SELL"],
                "duration_days": 7,
            },
        )
        assert enforce_res.status_code == 200

    # 1. Target student2 receives 1 consolidated notification
    stmt_target = select(Notification).where(
        Notification.user_id == student2.user_id,
        Notification.ref_type == "ACCOUNT_ACCESS",
        Notification.ref_id == report_id,
    )
    res_target = await db_session.execute(stmt_target)
    target_notifs = list(res_target.scalars().all())
    assert len(target_notifs) == 1
    t_notif = target_notifs[0]
    assert t_notif.type == "SYSTEM"
    assert "Quyền tài khoản của bạn đã được cập nhật" in t_notif.title
    assert "bán hàng" in t_notif.body
    assert student1.full_name not in t_notif.body  # Reporter identity not leaked
    assert "Gian lận bán hàng" not in t_notif.body  # Report evidence/description not leaked

    # Reporter receives 1 RESOLVED notification
    stmt_rep = select(Notification).where(
        Notification.user_id == student1.user_id,
        Notification.ref_type == "REPORT",
        Notification.ref_id == report_id,
    )
    res_rep = await db_session.execute(stmt_rep)
    assert len(res_rep.scalars().all()) == 1

    # 2. Admin restores capability
    with auth_override(admin1):
        restore_res = await test_client.post(
            f"/api/v1/admin/reports/{report_id}/enforcement",
            json={
                "action": "CAPABILITY_RESTORE",
                "capabilities": ["SELL"],
            },
        )
        assert restore_res.status_code == 200

    # Target student2 receives restoration notification
    stmt_restore = select(Notification).where(
        Notification.user_id == student2.user_id,
        Notification.ref_type == "ACCOUNT_ACCESS",
        Notification.ref_id == report_id,
    )
    res_restore = await db_session.execute(stmt_restore)
    all_target_notifs = list(res_restore.scalars().all())
    assert len(all_target_notifs) == 2  # 1 restrict + 1 restore
    restore_notif = [n for n in all_target_notifs if "khôi phục" in n.title][0]
    assert restore_notif.type == "SYSTEM"
    assert "bán hàng" in restore_notif.body


@pytest.mark.asyncio
async def test_support_claim_outcomes(
    test_client: AsyncClient,
    setup_notification_actors: dict,
    db_session: AsyncSession,
):
    admin1 = setup_notification_actors["admin1"]
    student1 = setup_notification_actors["student1"]

    # Student 1 creates claim for 50,000 VND
    with auth_override(student1):
        claim_res = await test_client.post(
            "/api/v1/feedback/support/claims",
            json={
                "claimed_transferred_at": datetime.now(timezone.utc).isoformat(),
                "claimed_amount_vnd": 50000,
                "sender_account_name": "NGUYEN VAN SINH VIEN 1",
                "wants_public": True,
            },
        )
        assert claim_res.status_code == 201
        claim_id = claim_res.json()["claim_id"]

    # Admin verifies claim with authoritative amount 75,000 VND
    with auth_override(admin1):
        ver_res = await test_client.post(
            f"/api/v1/admin/support-claims/{claim_id}/verify",
            json={
                "amount_vnd": 75000,
                "received_at": datetime.now(timezone.utc).isoformat(),
                "transaction_ref": "FT99998888",
                "admin_note": "Khớp giao dịch ngân hàng",
            },
        )
        assert ver_res.status_code == 200

    # Verify student receives 1 persistent notification with verified authoritative amount
    stmt = select(Notification).where(
        Notification.user_id == student1.user_id,
        Notification.ref_type == "SUPPORT_CLAIM",
        Notification.ref_id == claim_id,
    )
    res = await db_session.execute(stmt)
    notif = res.scalar_one_or_none()
    assert notif is not None
    assert notif.type == "SYSTEM"
    assert "đã được xác nhận" in notif.title
    assert "75,000" in notif.body  # Authoritative verified amount!
    assert "FT99998888" not in notif.body  # Privacy: transaction ref not leaked in bell body
    assert "Khớp giao dịch" not in notif.body  # Privacy: internal note not leaked


@pytest.mark.asyncio
async def test_realtime_failure_isolation(
    test_client: AsyncClient,
    setup_notification_actors: dict,
    db_session: AsyncSession,
):
    student1 = setup_notification_actors["student1"]
    student2 = setup_notification_actors["student2"]

    # Mock Redis publication failure
    with patch(
        "app.modules.orders.websocket.publish_user_event",
        side_effect=ConnectionError("Redis down!"),
    ):
        with auth_override(student1):
            report_res = await test_client.post(
                "/api/v1/reports",
                json={
                    "target_type": "USER",
                    "target_id": student2.user_id,
                    "reason": "SPAM",
                    "description": "Gửi tin nhắn spam",
                },
            )
            # Business operation succeeds despite Redis failure!
            assert report_res.status_code == 201
            report_id = report_res.json()["report_id"]

    # Verify Report exists in DB
    stmt_rep = select(Report).where(Report.report_id == report_id)
    res_rep = await db_session.execute(stmt_rep)
    assert res_rep.scalar_one_or_none() is not None

    # Verify persistent Admin notifications still created in DB
    stmt_notif = select(Notification).where(
        Notification.ref_type == "ADMIN_REPORT",
        Notification.ref_id == report_id,
    )
    res_notif = await db_session.execute(stmt_notif)
    notifs = list(res_notif.scalars().all())
    recipient_ids = {n.user_id for n in notifs}
    assert setup_notification_actors["admin1"].user_id in recipient_ids
    assert setup_notification_actors["admin2"].user_id in recipient_ids
    assert setup_notification_actors["admin_inactive"].user_id not in recipient_ids
    assert student1.user_id not in recipient_ids
    assert len([n for n in notifs if n.user_id == setup_notification_actors["admin1"].user_id]) == 1
