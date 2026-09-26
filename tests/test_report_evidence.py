import asyncio
from datetime import datetime, timezone
import io
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.categories.models import Category
from app.modules.orders.models import (
    FulfillmentMethod,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from app.modules.products.models import ListingType, Product, ProductStatus
from app.modules.reports.models import (
    ModerationAction,
    Report,
    ReportAttachment,
    ReportReason,
    ReportStatus,
    ReportTargetType,
)
from app.modules.reports.schemas import ReportEvidenceMetadata
from app.modules.users.models import User, UserRole, UserStatus
from tests.conftest import test_engine


def auth_patch(user: User):
    app.dependency_overrides[get_current_user] = lambda: user

    class CleanCtx:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc_val, exc_tb):
            app.dependency_overrides.pop(get_current_user, None)

    return CleanCtx()


# Valid magic-byte image fixtures
VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00" + b"\x00" * 100
VALID_PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01" + b"\x00" * 100
VALID_WEBP_BYTES = b"RIFF\x24\x00\x00\x00WEBPVP8 \x18\x00\x00\x00" + b"\x00" * 100
SPOOFED_EXE_BYTES = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 100

# Valid magic-byte video fixtures
VALID_MP4_BYTES = b"\x00\x00\x00\x1cftypisom\x00\x00\x02\x00isomiso2mp41" + b"\x00" * 100
VALID_WEBM_BYTES = b"\x1a\x45\xdf\xa3\x01\x00\x00\x1f\x42\x86\x81\x01\x42\xf7\x81\x01" + b"\x00" * 100
VALID_MOV_BYTES = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  " + b"\x00" * 100


@pytest_asyncio.fixture(autouse=True)
async def cleanup_reports_before_test(db_session: AsyncSession):
    await db_session.execute(delete(ModerationAction))
    await db_session.execute(delete(Report))
    await db_session.flush()


@pytest_asyncio.fixture
async def reporter_user(db_session: AsyncSession) -> User:
    user = User(
        email="reporter_ev@ptit.edu.vn",
        full_name="Người Báo Cáo",
        phone="0911111111",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        email="other_ev@ptit.edu.vn",
        full_name="Người Dùng Khác",
        phone="0922222222",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email="admin_ev@ptit.edu.vn",
        full_name="Quản Trị Viên",
        phone="0933333333",
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def sample_report(
    db_session: AsyncSession, reporter_user: User, other_user: User
) -> Report:
    report = Report(
        reporter_id=reporter_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=other_user.user_id,
        reason=ReportReason.SCAM.value,
        description="Có dấu hiệu gian lận chuyển khoản",
        status=ReportStatus.OPEN.value,
    )
    db_session.add(report)
    await db_session.flush()
    return report


# ============================================================
# 1. REPORTER UPLOAD EVIDENCE TESTS
# ============================================================


@pytest.mark.asyncio
async def test_reporter_can_upload_valid_image_evidence_to_own_report(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
):
    mock_upload = {
        "secure_url": "https://res.cloudinary.com/demo/image/upload/v12345/evidence_1.jpg",
        "public_id": "student-marketplace/reports/report-1/evidence_1",
    }

    with auth_patch(reporter_user):
        with patch("app.modules.reports.service.upload_report_evidence", return_value=mock_upload) as mock_fn:
            files = [
                ("files", ("receipt.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")),
                ("files", ("chat.png", io.BytesIO(VALID_PNG_BYTES), "image/png")),
            ]
            resp = await test_client.post(
                f"/api/v1/reports/{sample_report.report_id}/evidence",
                files=files,
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["report_id"] == sample_report.report_id
            assert len(data["attachments"]) == 2
            assert mock_fn.call_count == 2

            # Check privacy: no raw URL or storage_key in DTO
            for att in data["attachments"]:
                assert "storage_key" not in att
                assert "url" not in att
                assert att["attachment_id"] > 0
                assert att["original_name"] in ("receipt.jpg", "chat.png")
                assert att["mime_type"] in ("image/jpeg", "image/png")


@pytest.mark.asyncio
async def test_other_user_cannot_upload_evidence_returns_404(
    test_client: AsyncClient,
    other_user: User,
    sample_report: Report,
):
    # Non-owner report access must return 404 (never 403, non-leaking)
    with auth_patch(other_user):
        files = [("files", ("test.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))]
        resp = await test_client.post(
            f"/api/v1/reports/{sample_report.report_id}/evidence",
            files=files,
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Báo cáo không tồn tại."


@pytest.mark.asyncio
async def test_missing_report_returns_canonical_404(
    test_client: AsyncClient,
    reporter_user: User,
):
    with auth_patch(reporter_user):
        files = [("files", ("test.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))]
        resp = await test_client.post(
            "/api/v1/reports/999999/evidence",
            files=files,
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Báo cáo không tồn tại."


@pytest.mark.asyncio
async def test_empty_files_rejected_422(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
):
    with auth_patch(reporter_user):
        resp = await test_client.post(
            f"/api/v1/reports/{sample_report.report_id}/evidence",
            files=[],
        )
        # FastAPI or service returns 422 for missing required files
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_max_evidence_per_report_enforced_strictly(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
):
    # Uploading 6 files at once -> rejected 422
    with auth_patch(reporter_user):
        files = [
            ("files", (f"img_{i}.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))
            for i in range(6)
        ]
        resp = await test_client.post(
            f"/api/v1/reports/{sample_report.report_id}/evidence",
            files=files,
        )
        assert resp.status_code in (409, 422)
        assert "vượt quá giới hạn tối đa" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_existing_count_plus_new_files_exceeding_max_rejected(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
    db_session: AsyncSession,
):
    # Add 4 existing attachments
    for i in range(4):
        att = ReportAttachment(
            report_id=sample_report.report_id,
            url=f"https://res.cloudinary.com/demo/image/upload/img_{i}.jpg",
            storage_key=f"reports/report-{sample_report.report_id}/img_{i}",
            mime_type="image/jpeg",
            original_name=f"old_{i}.jpg",
            size_bytes=1024,
        )
        db_session.add(att)
    await db_session.flush()

    # User attempts to upload 2 more (4 + 2 = 6 > 5) -> must be rejected 409
    with auth_patch(reporter_user):
        files = [
            ("files", ("new1.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")),
            ("files", ("new2.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")),
        ]
        resp = await test_client.post(
            f"/api/v1/reports/{sample_report.report_id}/evidence",
            files=files,
        )
        assert resp.status_code == 409
        assert "vượt quá giới hạn tối đa" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_oversized_image_rejected_422(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
):
    oversized_bytes = VALID_JPEG_BYTES + b"\x00" * (10 * 1024 * 1024 + 1)
    with auth_patch(reporter_user):
        files = [("files", ("big.jpg", io.BytesIO(oversized_bytes), "image/jpeg"))]
        resp = await test_client.post(
            f"/api/v1/reports/{sample_report.report_id}/evidence",
            files=files,
        )
        assert resp.status_code == 422
        assert "vượt quá dung lượng" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_spoofed_executable_rejected_422(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
):
    # .exe disguised as .jpg
    with auth_patch(reporter_user):
        files = [("files", ("trojan.jpg", io.BytesIO(SPOOFED_EXE_BYTES), "image/jpeg"))]
        resp = await test_client.post(
            f"/api/v1/reports/{sample_report.report_id}/evidence",
            files=files,
        )
        assert resp.status_code == 422
        assert "thực thi" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_unsupported_non_image_rejected_422(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
):
    # Plain text file disguised as .jpg
    with auth_patch(reporter_user):
        files = [("files", ("doc.jpg", io.BytesIO(b"Hello world text file"), "image/jpeg"))]
        resp = await test_client.post(
            f"/api/v1/reports/{sample_report.report_id}/evidence",
            files=files,
        )
        assert resp.status_code == 422
        assert "không được hỗ trợ" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_terminal_resolved_report_rejects_evidence_409(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
    db_session: AsyncSession,
):
    sample_report.status = ReportStatus.RESOLVED.value
    await db_session.flush()

    with auth_patch(reporter_user):
        files = [("files", ("test.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))]
        resp = await test_client.post(
            f"/api/v1/reports/{sample_report.report_id}/evidence",
            files=files,
        )
        assert resp.status_code == 409
        assert "trạng thái kết thúc" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_terminal_rejected_report_rejects_evidence_409(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
    db_session: AsyncSession,
):
    sample_report.status = ReportStatus.REJECTED.value
    await db_session.flush()

    with auth_patch(reporter_user):
        files = [("files", ("test.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))]
        resp = await test_client.post(
            f"/api/v1/reports/{sample_report.report_id}/evidence",
            files=files,
        )
        assert resp.status_code == 409
        assert "trạng thái kết thúc" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_reviewing_report_allows_evidence_upload(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
    db_session: AsyncSession,
):
    sample_report.status = ReportStatus.REVIEWING.value
    await db_session.flush()

    mock_upload = {
        "secure_url": "https://res.cloudinary.com/demo/image/upload/v12345/evidence_rev.jpg",
        "public_id": "student-marketplace/reports/report-1/evidence_rev",
    }

    with auth_patch(reporter_user):
        with patch("app.modules.reports.service.upload_report_evidence", return_value=mock_upload):
            files = [("files", ("test.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))]
            resp = await test_client.post(
                f"/api/v1/reports/{sample_report.report_id}/evidence",
                files=files,
            )
            assert resp.status_code == 201


@pytest.mark.asyncio
async def test_multifile_local_validation_failure_attempts_zero_cloudinary_uploads(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
):
    # File 1 is valid, File 2 is an executable
    with auth_patch(reporter_user):
        with patch("app.modules.reports.service.upload_report_evidence") as mock_upload:
            files = [
                ("files", ("valid.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")),
                ("files", ("virus.jpg", io.BytesIO(SPOOFED_EXE_BYTES), "image/jpeg")),
            ]
            resp = await test_client.post(
                f"/api/v1/reports/{sample_report.report_id}/evidence",
                files=files,
            )
            assert resp.status_code == 422
            # Zero external uploads attempted
            mock_upload.assert_not_called()


@pytest.mark.asyncio
async def test_cloudinary_partial_failure_cleans_up_previous_uploads(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
):
    mock_upload_1 = {
        "secure_url": "https://res.cloudinary.com/demo/image/upload/v1/ok.jpg",
        "public_id": "reports/report-1/ok_pid",
    }

    # Upload 1 succeeds, Upload 2 raises exception
    with auth_patch(reporter_user):
        with patch(
            "app.modules.reports.service.upload_report_evidence",
            side_effect=[mock_upload_1, Exception("Cloudinary connection dropped")],
        ):
            with patch("app.modules.reports.service.destroy_image") as mock_destroy:
                files = [
                    ("files", ("img1.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")),
                    ("files", ("img2.jpg", io.BytesIO(VALID_PNG_BYTES), "image/png")),
                ]
                resp = await test_client.post(
                    f"/api/v1/reports/{sample_report.report_id}/evidence",
                    files=files,
                )
                assert resp.status_code == 503
                # Destroy was called for ok_pid
                mock_destroy.assert_called_once_with("reports/report-1/ok_pid")


@pytest.mark.asyncio
async def test_db_failure_after_cloudinary_triggers_compensation_cleanup(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
):
    mock_upload = {
        "secure_url": "https://res.cloudinary.com/demo/image/upload/v1/comp.jpg",
        "public_id": "reports/report-1/comp_pid",
    }

    with auth_patch(reporter_user):
        with patch("app.modules.reports.service.upload_report_evidence", return_value=mock_upload):
            with patch("app.modules.reports.service.ReportRepository.add_attachments", side_effect=Exception("DB failure")):
                with patch("app.modules.reports.service.destroy_image") as mock_destroy:
                    files = [("files", ("comp.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))]
                    resp = await test_client.post(
                        f"/api/v1/reports/{sample_report.report_id}/evidence",
                        files=files,
                    )
                    assert resp.status_code == 500
                    mock_destroy.assert_called_once_with("reports/report-1/comp_pid")


# ============================================================
# 2. EVIDENCE ON ALL THREE REPORT TARGETS
# ============================================================


@pytest.mark.asyncio
async def test_evidence_on_product_and_order_reports(
    test_client: AsyncClient,
    reporter_user: User,
    other_user: User,
    db_session: AsyncSession,
):
    cat = Category(name="Đồ học tập", slug="do-hoc-tap", is_deleted=False)
    db_session.add(cat)
    await db_session.flush()

    prod = Product(
        seller_id=other_user.user_id,
        category_id=cat.category_id,
        title="Máy tính Casio fx-580VN X",
        price=500000,
        stock=1,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        listing_type=ListingType.FIXED_PRICE.value,
    )
    db_session.add(prod)
    await db_session.flush()

    order = Order(
        buyer_id=reporter_user.user_id,
        seller_id=other_user.user_id,
        order_code="ORD-EV-001",
        total_amount=500000,
        fulfillment_method=FulfillmentMethod.MEETUP.value,
        payment_method=PaymentMethod.CASH_ON_MEETUP.value,
        contact_name="Người Mua",
        contact_phone="0911111111",
        status=OrderStatus.CONFIRMED.value,
    )
    db_session.add(order)
    await db_session.flush()

    rep_prod = Report(
        reporter_id=reporter_user.user_id,
        target_type=ReportTargetType.PRODUCT.value,
        target_id=prod.product_id,
        reason=ReportReason.FAKE_ITEM.value,
        status=ReportStatus.OPEN.value,
    )
    rep_order = Report(
        reporter_id=reporter_user.user_id,
        target_type=ReportTargetType.ORDER.value,
        target_id=order.order_id,
        reason=ReportReason.NO_SHOW.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add_all([rep_prod, rep_order])
    await db_session.flush()

    mock_upload = {
        "secure_url": "https://res.cloudinary.com/demo/image/upload/v1/sample.jpg",
        "public_id": "reports/report-1/sample",
    }

    with auth_patch(reporter_user):
        with patch("app.modules.reports.service.upload_report_evidence", return_value=mock_upload):
            # 1. Upload to Product report
            res_p = await test_client.post(
                f"/api/v1/reports/{rep_prod.report_id}/evidence",
                files=[("files", ("fake_calc.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))],
            )
            assert res_p.status_code == 201

            # 2. Upload to Order report
            res_o = await test_client.post(
                f"/api/v1/reports/{rep_order.report_id}/evidence",
                files=[("files", ("noshow_proof.png", io.BytesIO(VALID_PNG_BYTES), "image/png"))],
            )
            assert res_o.status_code == 201


# ============================================================
# 3. ADMIN QUEUE AND DETAIL EVIDENCE TESTS
# ============================================================


@pytest.mark.asyncio
async def test_admin_queue_list_returns_evidence_count_without_evidence_array(
    test_client: AsyncClient,
    admin_user: User,
    sample_report: Report,
    db_session: AsyncSession,
):
    # Attach 2 evidence records
    for i in range(2):
        att = ReportAttachment(
            report_id=sample_report.report_id,
            url=f"https://res.cloudinary.com/demo/evidence_{i}.jpg",
            storage_key=f"reports/report-{sample_report.report_id}/evidence_{i}",
            mime_type="image/jpeg",
            original_name=f"evidence_{i}.jpg",
            size_bytes=2048,
        )
        db_session.add(att)
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.get("/api/v1/admin/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        # Count is present
        assert item["evidence_count"] == 2
        # Evidence array is NOT present in list DTO
        assert "evidence" not in item


@pytest.mark.asyncio
async def test_admin_detail_returns_evidence_metadata_without_storage_url(
    test_client: AsyncClient,
    admin_user: User,
    sample_report: Report,
    db_session: AsyncSession,
):
    att = ReportAttachment(
        report_id=sample_report.report_id,
        url="https://res.cloudinary.com/demo/raw_secret_url.jpg",
        storage_key="secret_key_12345",
        mime_type="image/jpeg",
        original_name="bang_chung.jpg",
        size_bytes=5000,
    )
    db_session.add(att)
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.get(f"/api/v1/admin/reports/{sample_report.report_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["evidence_count"] == 1
        assert len(data["evidence"]) == 1
        ev = data["evidence"][0]
        assert ev["attachment_id"] == att.attachment_id
        assert ev["original_name"] == "bang_chung.jpg"
        assert ev["mime_type"] == "image/jpeg"
        assert ev["size_bytes"] == 5000
        # Check no sensitive keys leaked
        assert "storage_key" not in ev
        assert "url" not in ev


@pytest.mark.asyncio
async def test_student_cannot_access_admin_evidence_delivery_403(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
    db_session: AsyncSession,
):
    att = ReportAttachment(
        report_id=sample_report.report_id,
        url="https://res.cloudinary.com/demo/img.jpg",
        storage_key="key",
        mime_type="image/jpeg",
        original_name="img.jpg",
        size_bytes=1000,
    )
    db_session.add(att)
    await db_session.flush()

    with auth_patch(reporter_user):
        resp = await test_client.get(
            f"/api/v1/admin/reports/{sample_report.report_id}/evidence/{att.attachment_id}"
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_evidence_streaming_success(
    test_client: AsyncClient,
    admin_user: User,
    sample_report: Report,
    db_session: AsyncSession,
):
    att = ReportAttachment(
        report_id=sample_report.report_id,
        url="https://res.cloudinary.com/demo/image/upload/sample.jpg",
        storage_key="reports/sample",
        mime_type="image/jpeg",
        original_name="evidence_screenshot.jpg",
        size_bytes=len(VALID_JPEG_BYTES),
    )
    db_session.add(att)
    await db_session.flush()

    fake_stream_chunks = [VALID_JPEG_BYTES[:20], VALID_JPEG_BYTES[20:]]

    async def fake_aiter_bytes(chunk_size=65536):
        for chunk in fake_stream_chunks:
            yield chunk

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-length": str(len(VALID_JPEG_BYTES))}
    mock_resp.aiter_bytes = fake_aiter_bytes
    mock_resp.aclose = AsyncMock()

    mock_client = AsyncMock()
    mock_client.build_request = MagicMock(return_value=MagicMock())
    mock_client.send = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    with auth_patch(admin_user):
        with patch("httpx.AsyncClient", return_value=mock_client):
            # 1. Test thumbnail variant
            resp_thumb = await test_client.get(
                f"/api/v1/admin/reports/{sample_report.report_id}/evidence/{att.attachment_id}?variant=thumbnail"
            )
            assert resp_thumb.status_code == 200
            assert resp_thumb.headers["content-type"] == "image/jpeg"
            assert "evidence_screenshot.jpg" in resp_thumb.headers["content-disposition"]
            assert resp_thumb.content == VALID_JPEG_BYTES

            # 2. Test full variant
            resp_full = await test_client.get(
                f"/api/v1/admin/reports/{sample_report.report_id}/evidence/{att.attachment_id}?variant=full"
            )
            assert resp_full.status_code == 200
            assert resp_full.content == VALID_JPEG_BYTES


@pytest.mark.asyncio
async def test_admin_evidence_invalid_variant_rejected_422(
    test_client: AsyncClient,
    admin_user: User,
    sample_report: Report,
    db_session: AsyncSession,
):
    att = ReportAttachment(
        report_id=sample_report.report_id,
        url="https://res.cloudinary.com/demo/image/upload/sample.jpg",
        storage_key="sample",
        mime_type="image/jpeg",
        original_name="test.jpg",
        size_bytes=1000,
    )
    db_session.add(att)
    await db_session.flush()

    with auth_patch(admin_user):
        resp = await test_client.get(
            f"/api/v1/admin/reports/{sample_report.report_id}/evidence/{att.attachment_id}?variant=arbitrary_exploit"
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_attachment_from_wrong_report_returns_404(
    test_client: AsyncClient,
    admin_user: User,
    reporter_user: User,
    other_user: User,
    db_session: AsyncSession,
):
    r1 = Report(
        reporter_id=reporter_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=other_user.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.OPEN.value,
    )
    r2 = Report(
        reporter_id=reporter_user.user_id,
        target_type=ReportTargetType.USER.value,
        target_id=other_user.user_id,
        reason=ReportReason.SPAM.value,
        status=ReportStatus.OPEN.value,
    )
    db_session.add_all([r1, r2])
    await db_session.flush()

    att_r1 = ReportAttachment(
        report_id=r1.report_id,
        url="https://res.cloudinary.com/demo/img1.jpg",
        storage_key="key1",
        mime_type="image/jpeg",
        original_name="img1.jpg",
        size_bytes=1000,
    )
    db_session.add(att_r1)
    await db_session.flush()

    with auth_patch(admin_user):
        # Querying att_r1 through report r2 must return 404
        resp = await test_client.get(
            f"/api/v1/admin/reports/{r2.report_id}/evidence/{att_r1.attachment_id}"
        )
        assert resp.status_code == 404


# ============================================================
# 4. CONCURRENCY & RACE CONDITIONS (Corrections 18.A, 18.B)
# ============================================================


@pytest.mark.asyncio
async def test_concurrent_evidence_upload_respects_max_limit():
    """
    Test 18.A: Existing 4 evidence + two concurrent requests attempting 1 and 1
    Total must never exceed 5; one succeeds, the other gets 409.
    """
    uid_suffix = uuid.uuid4().hex[:8]
    async with test_engine.connect() as conn_setup:
        tx_setup = await conn_setup.begin()
        session_setup = AsyncSession(bind=conn_setup, expire_on_commit=False)

        reporter = User(
            email=f"conc_reporter_{uid_suffix}@ptit.edu.vn",
            full_name="Concurrent Reporter",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
        )
        session_setup.add(reporter)
        await session_setup.flush()

        report = Report(
            reporter_id=reporter.user_id,
            target_type=ReportTargetType.USER.value,
            target_id=reporter.user_id + 999,
            reason=ReportReason.SPAM.value,
            status=ReportStatus.OPEN.value,
        )
        session_setup.add(report)
        await session_setup.flush()

        # Seed 4 attachments
        for i in range(4):
            att = ReportAttachment(
                report_id=report.report_id,
                url=f"https://res.cloudinary.com/demo/old_{i}.jpg",
                storage_key=f"reports/old_{i}",
                mime_type="image/jpeg",
                original_name=f"old_{i}.jpg",
                size_bytes=1000,
            )
            session_setup.add(att)
        await session_setup.flush()
        report_id = report.report_id
        reporter_id = reporter.user_id
        await tx_setup.commit()

    try:
        # Now run two concurrent uploads via independent DB sessions
        async with AsyncSession(test_engine, expire_on_commit=False) as session_1, \
                   AsyncSession(test_engine, expire_on_commit=False) as session_2:

            reporter_1 = await session_1.get(User, reporter_id)
            reporter_2 = await session_2.get(User, reporter_id)

            from app.modules.reports.service import ReportService
            service_1 = ReportService(session_1)
            service_2 = ReportService(session_2)

            file_mock_1 = MagicMock()
            file_mock_1.filename = "race1.jpg"
            file_mock_1.read = AsyncMock(return_value=VALID_JPEG_BYTES)

            file_mock_2 = MagicMock()
            file_mock_2.filename = "race2.jpg"
            file_mock_2.read = AsyncMock(return_value=VALID_PNG_BYTES)

            mock_upload_res = {
                "secure_url": "https://res.cloudinary.com/demo/race.jpg",
                "public_id": "reports/race_pid",
            }

            with patch("app.modules.reports.service.upload_report_evidence", return_value=mock_upload_res):
                with patch("app.modules.reports.service.destroy_image"):
                    # Run upload 1
                    res1 = await service_1.upload_evidence(reporter_1, report_id, [file_mock_1])
                    assert len(res1.attachments) == 1

                    # Upload 2 tries while existing is now 5 -> must raise 409
                    from fastapi import HTTPException
                    with pytest.raises(HTTPException) as exc_info:
                        await service_2.upload_evidence(reporter_2, report_id, [file_mock_2])
                    assert exc_info.value.status_code == 409
                    assert "vượt quá giới hạn tối đa" in exc_info.value.detail

        # Verify final count in DB is exactly 5
        async with AsyncSession(test_engine) as session_check:
            count = (
                await session_check.execute(
                    select(func.count(ReportAttachment.attachment_id)).where(ReportAttachment.report_id == report_id)
                )
            ).scalar_one()
            assert count == 5
    finally:
        # Cleanup
        async with AsyncSession(test_engine) as session_clean:
            await session_clean.execute(delete(Report).where(Report.report_id == report_id))
            await session_clean.execute(delete(User).where(User.user_id == reporter_id))
            await session_clean.commit()


@pytest.mark.asyncio
async def test_evidence_upload_race_with_admin_resolution():
    """
    Test 18.B: Evidence upload starts while report is OPEN, but Admin resolves report
    before DB persistence. Locked re-check rejects persistence and compensation cleanup runs.
    """
    uid_suffix = uuid.uuid4().hex[:8]
    async with test_engine.connect() as conn_setup:
        tx_setup = await conn_setup.begin()
        session_setup = AsyncSession(bind=conn_setup, expire_on_commit=False)

        reporter = User(
            email=f"race_rep_{uid_suffix}@ptit.edu.vn",
            full_name="Race Admin Rep",
            role=UserRole.STUDENT.value,
            status=UserStatus.ACTIVE,
        )
        admin = User(
            email=f"race_adm_{uid_suffix}@ptit.edu.vn",
            full_name="Race Admin User",
            role=UserRole.ADMIN.value,
            status=UserStatus.ACTIVE,
        )
        session_setup.add_all([reporter, admin])
        await session_setup.flush()

        report = Report(
            reporter_id=reporter.user_id,
            target_type=ReportTargetType.USER.value,
            target_id=reporter.user_id + 888,
            reason=ReportReason.SPAM.value,
            status=ReportStatus.OPEN.value,
        )
        session_setup.add(report)
        await session_setup.flush()
        report_id = report.report_id
        reporter_id = reporter.user_id
        admin_id = admin.user_id
        await tx_setup.commit()

    try:
        async with AsyncSession(test_engine, expire_on_commit=False) as session_reporter:
            from app.modules.reports.service import ReportService
            service_reporter = ReportService(session_reporter)
            reporter_obj = await session_reporter.get(User, reporter_id)

            file_mock = MagicMock()
            file_mock.filename = "late_proof.jpg"
            file_mock.read = AsyncMock(return_value=VALID_JPEG_BYTES)

            mock_upload_res = {
                "secure_url": "https://res.cloudinary.com/demo/late.jpg",
                "public_id": "reports/late_pid",
            }

            def mock_upload_during_race(*args, **kwargs):
                # While upload is running externally, admin resolves the report in a separate transaction
                import threading

                def run_in_thread():
                    async def do_update():
                        async with AsyncSession(test_engine) as s:
                            await s.execute(
                                text("UPDATE reports SET status = :st, handled_by = :adm WHERE report_id = :r_id"),
                                {"st": ReportStatus.RESOLVED.value, "adm": admin_id, "r_id": report_id},
                            )
                            await s.commit()
                    asyncio.run(do_update())

                t = threading.Thread(target=run_in_thread)
                t.start()
                t.join()
                return mock_upload_res

            with patch("app.modules.reports.service.upload_report_evidence", side_effect=mock_upload_during_race):
                with patch("app.modules.reports.service.destroy_image") as mock_destroy:
                    from fastapi import HTTPException
                    with pytest.raises(HTTPException) as exc_info:
                        await service_reporter.upload_evidence(reporter_obj, report_id, [file_mock])
                    assert exc_info.value.status_code == 409
                    assert "trạng thái kết thúc" in exc_info.value.detail
                    # Compensation cleanup destroyed the asset
                    mock_destroy.assert_called_once_with("reports/late_pid")
    finally:
        # Cleanup
        async with AsyncSession(test_engine) as session_clean:
            await session_clean.execute(delete(Report).where(Report.report_id == report_id))
            await session_clean.execute(delete(User).where(User.user_id.in_([reporter_id, admin_id])))
            await session_clean.commit()


# ============================================================
# 5. VIDEO EVIDENCE TESTS (Part G)
# ============================================================

@pytest.mark.asyncio
async def test_accepts_one_valid_mp4_video_evidence(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
):
    mock_upload = {
        "secure_url": "https://res.cloudinary.com/demo/video/upload/sample.mp4",
        "public_id": "reports/video_mp4_pid",
        "duration": 25.5,
    }
    with auth_patch(reporter_user):
        with patch("app.modules.reports.service.upload_report_evidence", return_value=mock_upload) as mock_up:
            files = [("files", ("evidence.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4"))]
            resp = await test_client.post(
                f"/api/v1/reports/{sample_report.report_id}/evidence",
                files=files,
            )
            assert resp.status_code == 201
            data = resp.json()
            assert len(data["attachments"]) == 1
            att = data["attachments"][0]
            assert att["mime_type"] == "video/mp4"
            assert att["media_type"] == "VIDEO"
            # Verified resource_type="video" was requested
            assert mock_up.call_args.kwargs["resource_type"] == "video"


@pytest.mark.asyncio
async def test_accepts_valid_webm_and_mov_videos(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
):
    mock_upload = {
        "secure_url": "https://res.cloudinary.com/demo/video/upload/sample.webm",
        "public_id": "reports/video_webm_pid",
        "duration": 42.0,
    }
    with auth_patch(reporter_user):
        with patch("app.modules.reports.service.upload_report_evidence", return_value=mock_upload):
            files = [("files", ("clip.webm", io.BytesIO(VALID_WEBM_BYTES), "video/webm"))]
            resp = await test_client.post(
                f"/api/v1/reports/{sample_report.report_id}/evidence",
                files=files,
            )
            assert resp.status_code == 201
            assert resp.json()["attachments"][0]["mime_type"] == "video/webm"
            assert resp.json()["attachments"][0]["media_type"] == "VIDEO"


@pytest.mark.asyncio
async def test_rejects_second_video_in_same_or_later_request(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
):
    mock_upload = {
        "secure_url": "https://res.cloudinary.com/demo/video/upload/v1.mp4",
        "public_id": "reports/v1_pid",
        "duration": 15.0,
    }
    with auth_patch(reporter_user):
        # 1. Rejecting 2 videos in same request
        files_two = [
            ("files", ("v1.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4")),
            ("files", ("v2.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4")),
        ]
        resp_two = await test_client.post(
            f"/api/v1/reports/{sample_report.report_id}/evidence",
            files=files_two,
        )
        assert resp_two.status_code == 422
        assert "1 video" in resp_two.json()["detail"].lower()

        # 2. Upload 1 valid video first
        with patch("app.modules.reports.service.upload_report_evidence", return_value=mock_upload):
            files_one = [("files", ("v1.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4"))]
            resp_one = await test_client.post(
                f"/api/v1/reports/{sample_report.report_id}/evidence",
                files=files_one,
            )
            assert resp_one.status_code == 201

        # 3. Attempting to add a 2nd video to existing report -> 409 Conflict
        files_second = [("files", ("v2.mov", io.BytesIO(VALID_MOV_BYTES), "video/quicktime"))]
        resp_second = await test_client.post(
            f"/api/v1/reports/{sample_report.report_id}/evidence",
            files=files_second,
        )
        assert resp_second.status_code == 409
        assert "1 video" in resp_second.json()["detail"].lower()


@pytest.mark.asyncio
async def test_rejects_oversized_video_30mb(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
):
    oversized_video = VALID_MP4_BYTES + b"\x00" * (30 * 1024 * 1024 + 1)
    with auth_patch(reporter_user):
        files = [("files", ("huge.mp4", io.BytesIO(oversized_video), "video/mp4"))]
        resp = await test_client.post(
            f"/api/v1/reports/{sample_report.report_id}/evidence",
            files=files,
        )
        assert resp.status_code == 422
        assert "vượt quá dung lượng" in resp.json()["detail"]
        assert "30mb" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_rejects_video_exceeding_60s_and_compensates(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
):
    mock_upload = {
        "secure_url": "https://res.cloudinary.com/demo/video/upload/long.mp4",
        "public_id": "reports/long_video_pid",
        "duration": 61.2,  # > 60s
    }
    with auth_patch(reporter_user):
        with patch("app.modules.reports.service.upload_report_evidence", return_value=mock_upload):
            with patch("app.modules.reports.service.destroy_asset") as mock_destroy:
                files = [("files", ("long.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4"))]
                resp = await test_client.post(
                    f"/api/v1/reports/{sample_report.report_id}/evidence",
                    files=files,
                )
                assert resp.status_code == 422
                assert "thời lượng video" in resp.json()["detail"].lower()
                assert "60 giây" in resp.json()["detail"]
                # Must compensate/destroy asset with resource_type="video"
                mock_destroy.assert_called_once_with("reports/long_video_pid", resource_type="video")


@pytest.mark.asyncio
async def test_five_images_plus_one_video_permitted(
    test_client: AsyncClient,
    reporter_user: User,
    sample_report: Report,
):
    mock_img_upload = {
        "secure_url": "https://res.cloudinary.com/demo/img.jpg",
        "public_id": "reports/img_pid",
    }
    mock_vid_upload = {
        "secure_url": "https://res.cloudinary.com/demo/vid.mp4",
        "public_id": "reports/vid_pid",
        "duration": 18.0,
    }

    def mock_upload_side_effect(*args, **kwargs):
        if kwargs.get("resource_type") == "video":
            return mock_vid_upload
        return mock_img_upload

    with auth_patch(reporter_user):
        with patch("app.modules.reports.service.upload_report_evidence", side_effect=mock_upload_side_effect):
            # 5 images + 1 video in single batch
            files = [
                ("files", (f"img_{i}.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))
                for i in range(5)
            ] + [
                ("files", ("proof.mp4", io.BytesIO(VALID_MP4_BYTES), "video/mp4"))
            ]
            resp = await test_client.post(
                f"/api/v1/reports/{sample_report.report_id}/evidence",
                files=files,
            )
            assert resp.status_code == 201
            assert len(resp.json()["attachments"]) == 6

            # 6th image rejected
            resp_extra_img = await test_client.post(
                f"/api/v1/reports/{sample_report.report_id}/evidence",
                files=[("files", ("img_extra.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg"))],
            )
            assert resp_extra_img.status_code == 409
            assert "ảnh minh chứng vượt quá giới hạn" in resp_extra_img.json()["detail"].lower()


@pytest.mark.asyncio
async def test_admin_video_evidence_streaming_and_range(
    test_client: AsyncClient,
    admin_user: User,
    reporter_user: User,
    sample_report: Report,
    db_session: AsyncSession,
):
    att = ReportAttachment(
        report_id=sample_report.report_id,
        url="https://res.cloudinary.com/demo/video/upload/evidence_stream.mp4",
        storage_key="reports/video_stream_pid",
        mime_type="video/mp4",
        original_name="screen_recording.mp4",
        size_bytes=len(VALID_MP4_BYTES),
    )
    db_session.add(att)
    await db_session.flush()

    mock_resp = AsyncMock()
    mock_resp.status_code = 206
    mock_resp.headers = {
        "content-range": f"bytes 0-49/{len(VALID_MP4_BYTES)}",
        "content-length": "50",
    }
    fake_chunk = [VALID_MP4_BYTES[:50]]

    async def fake_stream():
        for c in fake_chunk:
            yield c

    mock_resp.aiter_bytes = lambda chunk_size=65536: fake_stream()
    mock_resp.aclose = AsyncMock()

    mock_client = AsyncMock()
    mock_client.build_request = MagicMock(return_value=MagicMock())
    mock_client.send = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    # 1. Admin access with Range header
    with auth_patch(admin_user):
        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = await test_client.get(
                f"/api/v1/admin/reports/{sample_report.report_id}/evidence/{att.attachment_id}",
                headers={"Range": "bytes=0-49"},
            )
            assert resp.status_code == 206
            assert resp.headers["content-type"] == "video/mp4"
            assert resp.headers["accept-ranges"] == "bytes"
            assert resp.headers["content-range"] == f"bytes 0-49/{len(VALID_MP4_BYTES)}"
            assert resp.headers["content-length"] == "50"
            assert resp.content == VALID_MP4_BYTES[:50]

    # 2. Non-admin (regular reporter) forbidden
    with auth_patch(reporter_user):
        resp_forbid = await test_client.get(
            f"/api/v1/admin/reports/{sample_report.report_id}/evidence/{att.attachment_id}",
            headers={"Range": "bytes=0-49"},
        )
        assert resp_forbid.status_code == 403

    # 3. Unauthenticated request without token rejected with 401
    resp_unauth = await test_client.get(
        f"/api/v1/admin/reports/{sample_report.report_id}/evidence/{att.attachment_id}",
        headers={"Range": "bytes=0-49"},
    )
    assert resp_unauth.status_code == 401

