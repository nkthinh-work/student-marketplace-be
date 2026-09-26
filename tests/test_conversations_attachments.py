from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.categories.models import Category
from app.modules.conversations.models import Conversation, ConversationMember, Message
from app.modules.products.models import ListingType, Product, ProductStatus
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
async def seller_user(db_session: AsyncSession) -> User:
    user = User(
        email="seller_att@ptit.edu.vn",
        full_name="Nguyễn Văn Bán",
        phone="0351234567",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def buyer_user(db_session: AsyncSession) -> User:
    user = User(
        email="buyer_att@ptit.edu.vn",
        full_name="Trần Văn Mua",
        phone="0987654321",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def third_user(db_session: AsyncSession) -> User:
    user = User(
        email="third_att@ptit.edu.vn",
        full_name="Lê Người Ngoài",
        phone="0911223344",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def category(db_session: AsyncSession) -> Category:
    cat = Category(
        name="Giáo trình & Sách",
        slug="giao-trinh-sach-att",
    )
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def product(db_session: AsyncSession, seller_user: User, category: Category) -> Product:
    prod = Product(
        seller_id=seller_user.user_id,
        category_id=category.category_id,
        title="Giáo trình Giải tích 1 PTIT",
        description="Sách mới 99%",
        price=Decimal("45000.00"),
        status=ProductStatus.AVAILABLE,
        approval_status="APPROVED",
        listing_type=ListingType.FIXED_PRICE,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


@pytest_asyncio.fixture
async def active_conversation(
    db_session: AsyncSession, seller_user: User, buyer_user: User
) -> Conversation:
    from app.modules.conversations.models import ConversationMember
    u1 = min(seller_user.user_id, buyer_user.user_id)
    u2 = max(seller_user.user_id, buyer_user.user_id)
    conv = Conversation(
        type="DIRECT",
        direct_pair_key=f"{u1}:{u2}",
        user_one_id=u1,
        user_two_id=u2,
    )
    db_session.add(conv)
    await db_session.flush()
    m1 = ConversationMember(conversation_id=conv.conversation_id, user_id=u1, role="MEMBER")
    m2 = ConversationMember(conversation_id=conv.conversation_id, user_id=u2, role="MEMBER")
    db_session.add_all([m1, m2])
    await db_session.flush()
    return conv


# Sample valid headers
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00" + b"\x00" * 100
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 100
PDF_BYTES = b"%PDF-1.4\n%header\n" + b"\x00" * 100
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00" + b"\x00" * 100
EXE_DISGUISED_BYTES = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 100


@pytest.mark.asyncio
async def test_send_text_only_message(
    test_client: AsyncClient, buyer_user: User, active_conversation: Conversation
):
    with auth_patch(buyer_user):
        response = await test_client.post(
            f"/api/v1/conversations/{active_conversation.conversation_id}/messages",
            data={"content": "Xin chào, sách còn không ạ?"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["content"] == "Xin chào, sách còn không ạ?"
    assert data["attachments"] == []
    assert data["is_mine"] is True


@pytest.mark.asyncio
async def test_send_image_only_message(
    test_client: AsyncClient, buyer_user: User, active_conversation: Conversation
):
    mock_upload = {
        "public_id": "student-marketplace/conversations/conv-1/sample_jpg",
        "secure_url": "https://res.cloudinary.com/demo/image/upload/sample.jpg",
    }
    with auth_patch(buyer_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value=mock_upload,
    ), patch(
        "app.modules.conversations.service.generate_delivery_url",
        return_value="https://res.cloudinary.com/demo/image/upload/sample.jpg",
    ) as mock_gen_url:
        files = [
            ("files", ("anh_san_pham.jpg", JPEG_BYTES, "image/jpeg")),
        ]
        response = await test_client.post(
            f"/api/v1/conversations/{active_conversation.conversation_id}/messages",
            files=files,
        )

    assert response.status_code == 201
    data = response.json()
    assert data["content"] is None
    assert len(data["attachments"]) == 1
    att = data["attachments"][0]
    assert att["kind"] == "IMAGE"
    assert att["mime_type"] == "image/jpeg"
    assert att["original_name"] == "anh_san_pham.jpg"
    assert att["url"] == "https://res.cloudinary.com/demo/image/upload/sample.jpg"
    mock_gen_url.assert_called_once_with(
        public_id="student-marketplace/conversations/conv-1/sample_jpg",
        resource_type="image",
        default_url="https://res.cloudinary.com/demo/image/upload/sample.jpg",
    )


@pytest.mark.asyncio
async def test_send_pdf_only_message(
    test_client: AsyncClient, seller_user: User, active_conversation: Conversation
):
    mock_upload = {
        "public_id": "student-marketplace/conversations/conv-1/tai_lieu_pdf",
        "secure_url": "https://res.cloudinary.com/demo/raw/upload/tailieu.pdf",
    }
    with auth_patch(seller_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value=mock_upload,
    ):
        files = [
            ("files", ("De_thi_giai_tich.pdf", PDF_BYTES, "application/pdf")),
        ]
        response = await test_client.post(
            f"/api/v1/conversations/{active_conversation.conversation_id}/messages",
            files=files,
        )

    assert response.status_code == 201
    data = response.json()
    assert data["content"] is None
    assert len(data["attachments"]) == 1
    att = data["attachments"][0]
    assert att["kind"] == "PDF"
    assert att["mime_type"] == "application/pdf"
    assert att["original_name"] == "De_thi_giai_tich.pdf"


@pytest.mark.asyncio
async def test_send_video_only_message(
    test_client: AsyncClient, seller_user: User, active_conversation: Conversation
):
    mock_upload = {
        "public_id": "student-marketplace/conversations/conv-1/video_review",
        "secure_url": "https://res.cloudinary.com/demo/video/upload/review.mp4",
    }
    with auth_patch(seller_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value=mock_upload,
    ):
        files = [
            ("files", ("video_sach.mp4", MP4_BYTES, "video/mp4")),
        ]
        response = await test_client.post(
            f"/api/v1/conversations/{active_conversation.conversation_id}/messages",
            files=files,
        )

    assert response.status_code == 201
    data = response.json()
    assert data["content"] is None
    assert len(data["attachments"]) == 1
    att = data["attachments"][0]
    assert att["kind"] == "VIDEO"
    assert att["mime_type"] == "video/mp4"
    assert att["original_name"] == "video_sach.mp4"


@pytest.mark.asyncio
async def test_send_text_and_multiple_attachments(
    test_client: AsyncClient, buyer_user: User, active_conversation: Conversation
):
    mock_upload = {
        "public_id": "student-marketplace/conversations/conv-1/test_asset",
        "secure_url": "https://res.cloudinary.com/demo/image/upload/asset.jpg",
    }
    with auth_patch(buyer_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value=mock_upload,
    ):
        files = [
            ("files", ("img1.jpg", JPEG_BYTES, "image/jpeg")),
            ("files", ("img2.png", PNG_BYTES, "image/png")),
            ("files", ("doc.pdf", PDF_BYTES, "application/pdf")),
        ]
        data = {"content": "Đây là ảnh và tài liệu em chụp"}
        response = await test_client.post(
            f"/api/v1/conversations/{active_conversation.conversation_id}/messages",
            data=data,
            files=files,
        )

    assert response.status_code == 201
    res_data = response.json()
    assert res_data["content"] == "Đây là ảnh và tài liệu em chụp"
    assert len(res_data["attachments"]) == 3
    kinds = [a["kind"] for a in res_data["attachments"]]
    assert kinds == ["IMAGE", "IMAGE", "PDF"]


@pytest.mark.asyncio
async def test_reject_more_than_four_attachments(
    test_client: AsyncClient, buyer_user: User, active_conversation: Conversation
):
    files = [
        ("files", ("img1.jpg", JPEG_BYTES, "image/jpeg")),
        ("files", ("img2.jpg", JPEG_BYTES, "image/jpeg")),
        ("files", ("img3.jpg", JPEG_BYTES, "image/jpeg")),
        ("files", ("img4.jpg", JPEG_BYTES, "image/jpeg")),
        ("files", ("img5.jpg", JPEG_BYTES, "image/jpeg")),
    ]
    with auth_patch(buyer_user):
        response = await test_client.post(
            f"/api/v1/conversations/{active_conversation.conversation_id}/messages",
            files=files,
        )
    assert response.status_code == 400
    assert "Cannot attach more than 4 files" in response.json()["detail"]


@pytest.mark.asyncio
async def test_reject_unsupported_mime_or_disguised_executable(
    test_client: AsyncClient, buyer_user: User, active_conversation: Conversation
):
    # Executable disguised as JPG
    files = [
        ("files", ("virus.jpg", EXE_DISGUISED_BYTES, "image/jpeg")),
    ]
    with auth_patch(buyer_user):
        response = await test_client.post(
            f"/api/v1/conversations/{active_conversation.conversation_id}/messages",
            files=files,
        )
    assert response.status_code == 400
    assert "Executable files are not permitted" in response.json()["detail"]


@pytest.mark.asyncio
async def test_reject_empty_text_and_zero_attachments(
    test_client: AsyncClient, buyer_user: User, active_conversation: Conversation
):
    with auth_patch(buyer_user):
        response = await test_client.post(
            f"/api/v1/conversations/{active_conversation.conversation_id}/messages",
            data={"content": "    "},
        )
    assert response.status_code == 422
    assert "Message must contain text content or at least one attachment" in response.json()["detail"]


@pytest.mark.asyncio
async def test_reject_third_party_non_participant(
    test_client: AsyncClient, third_user: User, active_conversation: Conversation
):
    with auth_patch(third_user):
        response = await test_client.post(
            f"/api/v1/conversations/{active_conversation.conversation_id}/messages",
            data={"content": "Tin nhắn từ người ngoài"},
        )
    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation not found"


@pytest.mark.asyncio
async def test_get_messages_includes_attachments_metadata(
    test_client: AsyncClient, buyer_user: User, active_conversation: Conversation
):
    mock_upload = {
        "public_id": "student-marketplace/conversations/conv-1/img1",
        "secure_url": "https://res.cloudinary.com/demo/image/upload/img1.jpg",
    }
    with auth_patch(buyer_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value=mock_upload,
    ):
        files = [
            ("files", ("test.jpg", JPEG_BYTES, "image/jpeg")),
        ]
        await test_client.post(
            f"/api/v1/conversations/{active_conversation.conversation_id}/messages",
            data={"content": "Check attachment history"},
            files=files,
        )

    # Query message history
    with auth_patch(buyer_user):
        history_res = await test_client.get(
            f"/api/v1/conversations/{active_conversation.conversation_id}/messages"
        )
    assert history_res.status_code == 200
    history_data = history_res.json()
    assert len(history_data["items"]) >= 1
    latest_msg = history_data["items"][0]
    assert latest_msg["content"] == "Check attachment history"
    assert len(latest_msg["attachments"]) == 1
    assert latest_msg["attachments"][0]["original_name"] == "test.jpg"
    assert latest_msg["attachments"][0]["kind"] == "IMAGE"


@pytest.mark.asyncio
async def test_orphan_cleanup_on_db_or_upload_failure(
    test_client: AsyncClient, buyer_user: User, active_conversation: Conversation
):
    mock_upload = {
        "public_id": "student-marketplace/conversations/conv-1/orphan_test",
        "secure_url": "https://res.cloudinary.com/demo/image/upload/orphan.jpg",
    }
    cleanup_mock = MagicMock(return_value=True)

    with auth_patch(buyer_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value=mock_upload,
    ), patch(
        "app.modules.conversations.service.destroy_asset",
        cleanup_mock,
    ), patch(
        "app.modules.conversations.repository.ConversationRepository.create_message",
        side_effect=Exception("Simulated DB error during commit"),
    ):
        files = [
            ("files", ("test.jpg", JPEG_BYTES, "image/jpeg")),
        ]
        response = await test_client.post(
            f"/api/v1/conversations/{active_conversation.conversation_id}/messages",
            files=files,
        )

    assert response.status_code == 500
    # Verify destroy_asset was called to cleanup the orphan asset
    cleanup_mock.assert_called_once_with(
        "student-marketplace/conversations/conv-1/orphan_test",
        resource_type="image",
    )


WEBM_VOICE_BYTES = b"\x1a\x45\xdf\xa3" + b"\x00" * 100


@pytest.mark.asyncio
async def test_send_voice_note_persists_duration(
    test_client: AsyncClient, buyer_user: User, active_conversation: Conversation
):
    mock_upload = {
        "public_id": "student-marketplace/conversations/conv-1/voice_note_1",
        "secure_url": "https://res.cloudinary.com/demo/video/upload/voice.webm",
        "duration": 6.85,
    }
    with auth_patch(buyer_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value=mock_upload,
    ):
        files = [
            ("files", ("voice_note.webm", WEBM_VOICE_BYTES, "audio/webm")),
        ]
        response = await test_client.post(
            f"/api/v1/conversations/{active_conversation.conversation_id}/messages",
            data={"voice_duration_ms": 7000},
            files=files,
        )

    assert response.status_code == 201
    data = response.json()
    assert len(data["attachments"]) == 1
    att = data["attachments"][0]
    assert att["kind"] == "AUDIO"
    # Provider duration 6.85s -> 6850ms
    assert att["duration_ms"] == 6850

    # Verify duration_ms is returned in messages history
    with auth_patch(buyer_user):
        history_res = await test_client.get(
            f"/api/v1/conversations/{active_conversation.conversation_id}/messages"
        )
    assert history_res.status_code == 200
    history_data = history_res.json()
    assert history_data["items"][0]["attachments"][0]["duration_ms"] == 6850


@pytest.mark.asyncio
async def test_reject_voice_note_exceeding_five_minutes(
    test_client: AsyncClient, buyer_user: User, active_conversation: Conversation
):
    files = [
        ("files", ("voice_note.webm", WEBM_VOICE_BYTES, "audio/webm")),
    ]
    with auth_patch(buyer_user):
        response = await test_client.post(
            f"/api/v1/conversations/{active_conversation.conversation_id}/messages",
            data={"voice_duration_ms": 305000},
            files=files,
        )
    assert response.status_code == 400
    assert "vượt quá thời lượng tối đa 5 phút" in response.json()["detail"]


@pytest.mark.asyncio
async def test_owned_group_count_endpoint(
    test_client: AsyncClient, seller_user: User
):
    with auth_patch(seller_user):
        res = await test_client.get("/api/v1/conversations/owned-group-count")
    assert res.status_code == 200
    assert res.json()["owned_group_count"] == 0

    # Create a group
    with auth_patch(seller_user):
        create_res = await test_client.post(
            "/api/v1/conversations/groups",
            json={"title": "Nhóm Nghiên Cứu AI PTIT"},
        )
    assert create_res.status_code == 201

    # Check owned_group_count again -> 1
    with auth_patch(seller_user):
        res2 = await test_client.get("/api/v1/conversations/owned-group-count")
    assert res2.status_code == 200
    assert res2.json()["owned_group_count"] == 1


@pytest.mark.asyncio
async def test_shared_attachments_summary_lifecycle(
    test_client: AsyncClient,
    buyer_user: User,
    active_conversation: Conversation,
):
    conv_id = active_conversation.conversation_id

    # 1. Initial count: 0 across all categories
    with auth_patch(buyer_user):
        res0 = await test_client.get(f"/api/v1/conversations/{conv_id}/attachments/summary")
    assert res0.status_code == 200
    assert res0.json() == {"media_count": 0, "audio_count": 0, "file_count": 0}

    # 2. Send IMAGE: media_count becomes 1
    with auth_patch(buyer_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value={"public_id": "test_img", "secure_url": "https://res.cloudinary.com/test_img.jpg"},
    ):
        r_img = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            files=[("files", ("test.jpg", JPEG_BYTES, "image/jpeg"))],
        )
    assert r_img.status_code == 201

    with auth_patch(buyer_user):
        res1 = await test_client.get(f"/api/v1/conversations/{conv_id}/attachments/summary")
    assert res1.status_code == 200
    assert res1.json() == {"media_count": 1, "audio_count": 0, "file_count": 0}

    # 3. Send VIDEO: media_count becomes 2
    with auth_patch(buyer_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value={"public_id": "test_vid", "secure_url": "https://res.cloudinary.com/test_vid.mp4", "duration": 15.0},
    ):
        r_vid = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            files=[("files", ("test.mp4", MP4_BYTES, "video/mp4"))],
        )
    assert r_vid.status_code == 201

    with auth_patch(buyer_user):
        res2 = await test_client.get(f"/api/v1/conversations/{conv_id}/attachments/summary")
    assert res2.status_code == 200
    assert res2.json() == {"media_count": 2, "audio_count": 0, "file_count": 0}

    # 4. Send AUDIO: audio_count becomes 1
    with auth_patch(buyer_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value={"public_id": "test_audio", "secure_url": "https://res.cloudinary.com/test_audio.webm", "duration": 8.0},
    ):
        r_aud = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={"voice_duration_ms": 8000},
            files=[("files", ("voice.webm", WEBM_VOICE_BYTES, "audio/webm"))],
        )
    assert r_aud.status_code == 201

    with auth_patch(buyer_user):
        res3 = await test_client.get(f"/api/v1/conversations/{conv_id}/attachments/summary")
    assert res3.status_code == 200
    assert res3.json() == {"media_count": 2, "audio_count": 1, "file_count": 0}

    # 5. Send PDF: file_count becomes 1
    with auth_patch(buyer_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value={"public_id": "test_doc", "secure_url": "https://res.cloudinary.com/test_doc.pdf"},
    ):
        r_pdf = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            files=[("files", ("document.pdf", PDF_BYTES, "application/pdf"))],
        )
    assert r_pdf.status_code == 201

    with auth_patch(buyer_user):
        res4 = await test_client.get(f"/api/v1/conversations/{conv_id}/attachments/summary")
    assert res4.status_code == 200
    assert res4.json() == {"media_count": 2, "audio_count": 1, "file_count": 1}

    # 6. Send TEXT-ONLY message: counts remain identical
    with auth_patch(buyer_user):
        r_txt = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            data={"content": "Tin nhắn văn bản thuần túy"},
        )
    assert r_txt.status_code == 201

    with auth_patch(buyer_user):
        res5 = await test_client.get(f"/api/v1/conversations/{conv_id}/attachments/summary")
    assert res5.status_code == 200
    assert res5.json() == {"media_count": 2, "audio_count": 1, "file_count": 1}


class MockUpstreamResponse:
    def __init__(self, content: bytes = b"%PDF-1.4 mock content", status_code: int = 200, headers: dict = None):
        self.content = content
        self.status_code = status_code
        self.headers = headers if headers is not None else {"content-length": str(len(content))}

    async def aiter_bytes(self, chunk_size=65536):
        yield self.content

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_format_content_disposition_sanitization_and_vietnamese():
    from app.modules.conversations.router import format_content_disposition

    # Standard ASCII
    cd1 = format_content_disposition("PTIT Code Helper - An Vu.pdf", "application/pdf")
    assert 'filename="PTIT Code Helper - An Vu.pdf"' in cd1
    assert "filename*=UTF-8''PTIT%20Code%20Helper%20-%20An%20Vu.pdf" in cd1

    # Vietnamese Unicode
    cd2 = format_content_disposition("Báo cáo thực tập cuối kỳ 2026.pdf", "application/pdf")
    assert "filename*=UTF-8''" in cd2
    assert "2026.pdf" in cd2
    # Verify RFC 5987 percent-decoded value preserves exact original
    import urllib.parse
    encoded_part = cd2.split("filename*=UTF-8''")[1]
    assert urllib.parse.unquote(encoded_part) == "Báo cáo thực tập cuối kỳ 2026.pdf"

    # CR/LF injection and path traversal attempt
    cd3 = format_content_disposition("../../etc/passwd\r\nInjected: hack.pdf", "application/pdf")
    assert "\r" not in cd3
    assert "\n" not in cd3
    assert ".." not in cd3
    assert "/" not in cd3


@pytest.mark.asyncio
async def test_active_member_can_request_ticket_and_download(
    test_client: AsyncClient,
    buyer_user: User,
    active_conversation: Conversation,
):
    conv_id = active_conversation.conversation_id

    # Send a document attachment
    with auth_patch(buyer_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value={
            "public_id": "doc_123",
            "secure_url": "https://res.cloudinary.com/evbzqq5l/raw/upload/v123/doc_123",
        },
    ):
        r_msg = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            files=[("files", ("test_report.pdf", PDF_BYTES, "application/pdf"))],
        )
    assert r_msg.status_code == 201
    att_id = r_msg.json()["attachments"][0]["attachment_id"]

    # 1. Request single-use download ticket (Authenticated via Bearer)
    with auth_patch(buyer_user):
        r_ticket = await test_client.post(
            f"/api/v1/conversations/{conv_id}/attachments/{att_id}/download-ticket"
        )
    assert r_ticket.status_code == 200
    data = r_ticket.json()
    ticket = data["ticket"]
    download_url = data["download_url"]
    assert ticket
    assert f"/api/v1/conversations/{conv_id}/attachments/{att_id}/download?ticket={ticket}" in download_url
    # Critical security check: No Firebase token in download URL or ticket
    assert "firebase" not in ticket.lower()
    assert "firebase" not in download_url.lower()

    # 2. Native browser download via ticket (Unauthenticated navigation with ticket query)
    mock_resp = MockUpstreamResponse(b"%PDF-1.4 streamed payload")
    mock_client = MagicMock()
    mock_client.aclose = AsyncMock()
    with patch(
        "app.modules.conversations.router.fetch_upstream_asset",
        return_value=(mock_client, mock_resp),
    ):
        r_dl = await test_client.get(
            f"/api/v1/conversations/{conv_id}/attachments/{att_id}/download?ticket={ticket}"
        )
    assert r_dl.status_code == 200
    assert r_dl.content == b"%PDF-1.4 streamed payload"
    assert "attachment" in r_dl.headers["content-disposition"]
    assert "test_report.pdf" in r_dl.headers["content-disposition"]
    assert r_dl.headers["content-type"] == "application/pdf"
    assert r_dl.headers["cache-control"] == "private, no-store"

    # 3. Single-use invariant: Consumed ticket cannot be reused
    r_dl2 = await test_client.get(
        f"/api/v1/conversations/{conv_id}/attachments/{att_id}/download?ticket={ticket}"
    )
    assert r_dl2.status_code == 401


@pytest.mark.asyncio
async def test_direct_bearer_download_supported(
    test_client: AsyncClient,
    buyer_user: User,
    active_conversation: Conversation,
):
    conv_id = active_conversation.conversation_id

    with auth_patch(buyer_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value={
            "public_id": "doc_direct",
            "secure_url": "https://res.cloudinary.com/evbzqq5l/raw/upload/v123/doc_direct",
        },
    ):
        r_msg = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            files=[("files", ("direct.pdf", PDF_BYTES, "application/pdf"))],
        )
    att_id = r_msg.json()["attachments"][0]["attachment_id"]

    mock_resp = MockUpstreamResponse(b"%PDF-1.4 direct bearer download")
    mock_client = MagicMock()
    mock_client.aclose = AsyncMock()
    with auth_patch(buyer_user), patch(
        "app.modules.conversations.router.fetch_upstream_asset",
        return_value=(mock_client, mock_resp),
    ):
        r_dl = await test_client.get(
            f"/api/v1/conversations/{conv_id}/attachments/{att_id}/download",
            headers={"Authorization": "Bearer direct_test_token"},
        )
    assert r_dl.status_code == 200
    assert r_dl.content == b"%PDF-1.4 direct bearer download"


@pytest.mark.asyncio
async def test_ticket_revocation_race(
    test_client: AsyncClient,
    buyer_user: User,
    seller_user: User,
    db_session: AsyncSession,
):
    # Create a group conversation with seller_user as leader and buyer_user as member
    conv = Conversation(type="GROUP", title="Test Group For Revocation")
    db_session.add(conv)
    await db_session.flush()

    m_owner = ConversationMember(conversation_id=conv.conversation_id, user_id=seller_user.user_id, role="OWNER")
    m_member = ConversationMember(conversation_id=conv.conversation_id, user_id=buyer_user.user_id, role="MEMBER")
    db_session.add_all([m_owner, m_member])
    await db_session.commit()
    conv_id = conv.conversation_id

    # Leader posts an attachment
    with auth_patch(seller_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value={
            "public_id": "group_doc",
            "secure_url": "https://res.cloudinary.com/evbzqq5l/raw/upload/v123/group_doc",
        },
    ):
        r_msg = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            files=[("files", ("secret.pdf", PDF_BYTES, "application/pdf"))],
        )
    assert r_msg.status_code == 201
    att_id = r_msg.json()["attachments"][0]["attachment_id"]

    # Active member requests a download ticket BEFORE revocation
    with auth_patch(buyer_user):
        r_ticket = await test_client.post(
            f"/api/v1/conversations/{conv_id}/attachments/{att_id}/download-ticket"
        )
    assert r_ticket.status_code == 200
    ticket = r_ticket.json()["ticket"]

    # Leader removes member from the group
    with auth_patch(seller_user):
        r_remove = await test_client.delete(
            f"/api/v1/conversations/groups/{conv_id}/members/{buyer_user.user_id}"
        )
    assert r_remove.status_code == 200

    # Removed member tries to consume previously issued ticket AFTER removal
    # Real-time authorization re-check must DENY the download!
    mock_resp = MockUpstreamResponse(b"should never be reached")
    mock_client = MagicMock()
    mock_client.aclose = AsyncMock()
    with patch(
        "app.modules.conversations.router.fetch_upstream_asset",
        return_value=(mock_client, mock_resp),
    ):
        r_dl = await test_client.get(
            f"/api/v1/conversations/{conv_id}/attachments/{att_id}/download?ticket={ticket}"
        )
    assert r_dl.status_code == 404
    assert "không có quyền truy cập" in r_dl.json()["detail"]


@pytest.mark.asyncio
async def test_redis_unavailable_fails_gracefully(
    test_client: AsyncClient,
    buyer_user: User,
    active_conversation: Conversation,
):
    conv_id = active_conversation.conversation_id

    with auth_patch(buyer_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value={
            "public_id": "doc_redis_test",
            "secure_url": "https://res.cloudinary.com/evbzqq5l/raw/upload/v123/doc_redis_test",
        },
    ):
        r_msg = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            files=[("files", ("doc.pdf", PDF_BYTES, "application/pdf"))],
        )
    att_id = r_msg.json()["attachments"][0]["attachment_id"]

    # Mock Redis client to be None (simulating Redis outage)
    with auth_patch(buyer_user), patch(
        "app.modules.conversations.service.get_redis_client", return_value=None
    ), patch(
        "app.modules.conversations.service.get_or_reconnect_redis", return_value=None
    ):
        r_ticket = await test_client.post(
            f"/api/v1/conversations/{conv_id}/attachments/{att_id}/download-ticket"
        )
    # Must fail with 503 Service Unavailable and NOT issue an in-memory ticket
    assert r_ticket.status_code == 503
    assert "tạm thời không khả dụng" in r_ticket.json()["detail"]


@pytest.mark.asyncio
async def test_untrusted_upstream_target_ssrf_rejected(
    test_client: AsyncClient,
    buyer_user: User,
    active_conversation: Conversation,
):
    conv_id = active_conversation.conversation_id

    # Pretend an attachment in DB has an untrusted external URL
    with auth_patch(buyer_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value={
            "public_id": "evil_doc",
            "secure_url": "https://attacker.evil.com/leak",
        },
    ):
        r_msg = await test_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            files=[("files", ("evil.pdf", PDF_BYTES, "application/pdf"))],
        )
    att_id = r_msg.json()["attachments"][0]["attachment_id"]

    # Requesting download ticket succeeds
    with auth_patch(buyer_user):
        r_ticket = await test_client.post(
            f"/api/v1/conversations/{conv_id}/attachments/{att_id}/download-ticket"
        )
    assert r_ticket.status_code == 200
    ticket = r_ticket.json()["ticket"]

    # Downloading fails with 502 Bad Gateway due to SSRF protection!
    with patch("app.modules.conversations.router.fetch_upstream_asset") as mock_fetch:
        r_dl = await test_client.get(
            f"/api/v1/conversations/{conv_id}/attachments/{att_id}/download?ticket={ticket}"
        )
        # Verify no outbound HTTP call was made to the evil host!
        mock_fetch.assert_not_called()

    assert r_dl.status_code == 502
    assert "không được tin cậy" in r_dl.json()["detail"]


@pytest.mark.asyncio
async def test_cross_conversation_download_rejected(
    test_client: AsyncClient,
    buyer_user: User,
    db_session: AsyncSession,
):
    # Create two separate conversations
    conv_1 = Conversation(type="GROUP", title="Group 1")
    conv_2 = Conversation(type="GROUP", title="Group 2")
    db_session.add_all([conv_1, conv_2])
    await db_session.flush()

    m1 = ConversationMember(conversation_id=conv_1.conversation_id, user_id=buyer_user.user_id, role="MEMBER")
    m2 = ConversationMember(conversation_id=conv_2.conversation_id, user_id=buyer_user.user_id, role="MEMBER")
    db_session.add_all([m1, m2])
    await db_session.commit()

    # Post attachment to Group 1
    with auth_patch(buyer_user), patch(
        "app.modules.conversations.service.upload_message_attachment",
        return_value={
            "public_id": "g1_doc",
            "secure_url": "https://res.cloudinary.com/evbzqq5l/raw/upload/v123/g1_doc",
        },
    ):
        r_msg = await test_client.post(
            f"/api/v1/conversations/{conv_1.conversation_id}/messages",
            files=[("files", ("g1.pdf", PDF_BYTES, "application/pdf"))],
        )
    att_1 = r_msg.json()["attachments"][0]["attachment_id"]

    # Attempt to request ticket for Group 1 attachment via Group 2
    with auth_patch(buyer_user):
        r_ticket = await test_client.post(
            f"/api/v1/conversations/{conv_2.conversation_id}/attachments/{att_1}/download-ticket"
        )
    assert r_ticket.status_code == 404

