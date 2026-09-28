import json
import logging
import mimetypes
import os
import re
import urllib.parse
from typing import List, Optional
import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.integrations.firebase import verify_firebase_token, FirebaseVerificationError
from app.modules.auth.dependencies import get_current_active_user, get_current_user, security
from app.modules.auth.service import AuthService
from app.modules.conversations.schemas import (
    AttachmentDownloadTicketResponse,
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationFromOrderRequest,
    ConversationInviteResponse,
    ConversationListResponse,
    ConversationMemberResponse,
    DirectConversationCreateRequest,
    GroupCreateRequest,
    GroupInviteCreateRequest,
    GroupInviteRespondRequest,
    GroupMemberNicknameUpdateRequest,
    GroupMemberRoleUpdateRequest,
    GroupTransferOwnershipRequest,
    GroupUpdateRequest,
    InviteCandidateListResponse,
    MessageListResponse,
    MessageReactionSetRequest,
    MessageReactionSummaryResponse,
    MessageResponse,
    OfficialSupportGroupJoinResponse,
    OwnedGroupSummaryResponse,
    PendingApprovalActionRequest,
    PendingApprovalListResponse,
    PresenceBatchResponse,
    SharedAttachmentListResponse,
    SharedAttachmentSummaryResponse,
)
from app.modules.conversations.service import ConversationService
from app.modules.users.models import User

logger = logging.getLogger("app.conversations.router")


def format_content_disposition(original_name: str, mime_type: Optional[str] = None) -> str:
    """
    Safely sanitizes and formats Content-Disposition header conforming to RFC 5987 / RFC 6266.
    - Strips CR, LF, null, and control characters (< 32, 127).
    - Removes path separators and prevents path traversal (e.g. '../').
    - Preserves valid file extension; infers from canonical mime_type if missing.
    - Builds safe ASCII fallback filename="..." (using [A-Za-z0-9._- ]).
    - Builds RFC 5987 UTF-8 percent-encoded filename*=UTF-8''... for Vietnamese Unicode.
    """
    sanitized = "".join(
        ch for ch in (original_name or "")
        if ord(ch) >= 32 and ord(ch) != 127 and ch not in "\r\n\t\x00"
    )
    sanitized = sanitized.replace("\\", "/")
    basename = os.path.basename(sanitized).strip(". ")
    if not basename:
        basename = "attachment"

    name_part, ext = os.path.splitext(basename)
    if not ext and mime_type:
        guessed_ext = mimetypes.guess_extension(mime_type)
        if guessed_ext:
            basename = f"{name_part}{guessed_ext}"
            ext = guessed_ext

    # Safe ASCII fallback: only [A-Za-z0-9._- ]
    ascii_clean = "".join(
        c if (c.isalnum() and ord(c) < 128) or c in " ._-" else "_"
        for c in basename
    )
    ascii_clean = re.sub(r"_+", "_", ascii_clean).strip(" _")
    if not ascii_clean or ascii_clean == ext.lstrip("."):
        ascii_fallback = f"download{ext}"
    else:
        ascii_fallback = ascii_clean
        if ext and not ascii_fallback.lower().endswith(ext.lower()):
            ascii_fallback = f"{ascii_fallback}{ext}"

    utf8_encoded = urllib.parse.quote(basename, encoding="utf-8")
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{utf8_encoded}'


router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post(
    "",
    response_model=ConversationDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Khởi tạo hoặc mở cuộc trò chuyện 1-1 từ sản phẩm",
)
async def open_or_create_conversation(
    payload: ConversationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.create_or_open_conversation(current_user, payload.product_id)


@router.post(
    "/direct",
    response_model=ConversationDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Khởi tạo hoặc mở cuộc trò chuyện 1-1 trực tiếp với người dùng",
)
async def open_or_create_direct_conversation(
    payload: DirectConversationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.create_or_open_direct_conversation(
        current_user, payload.recipient_user_id
    )


@router.post(
    "/from-order",
    response_model=ConversationDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Khởi tạo hoặc mở cuộc trò chuyện 1-1 từ đơn hàng",
)
async def open_or_create_conversation_from_order(
    payload: ConversationFromOrderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.create_or_open_conversation_from_order(current_user, payload.order_id)



@router.post(
    "/groups",
    response_model=ConversationDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo nhóm trò chuyện mới",
)
async def create_group_conversation(
    payload: GroupCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.create_group(current_user, payload)


@router.get(
    "/invites",
    response_model=List[ConversationInviteResponse],
    status_code=status.HTTP_200_OK,
    summary="Danh sách lời mời vào nhóm đang chờ",
)
async def list_group_invites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.list_user_invites(current_user)


@router.post(
    "/invites/{invite_id}/respond",
    status_code=status.HTTP_200_OK,
    summary="Phản hồi lời mời nhóm (Chấp nhận / Từ chối)",
)
async def respond_to_group_invite(
    invite_id: int,
    payload: GroupInviteRespondRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.respond_to_invite(current_user, invite_id, payload.action)


@router.post(
    "/official-support/join",
    response_model=OfficialSupportGroupJoinResponse,
    status_code=status.HTTP_200_OK,
    summary="Tham gia hoặc mở nhóm Hỗ trợ / Cộng đồng chính thức",
)
async def join_official_support_group(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.join_official_support_group(current_user)



@router.get(
    "",
    response_model=ConversationListResponse,
    status_code=status.HTTP_200_OK,
    summary="Danh sách cuộc trò chuyện của người dùng",
)
async def list_conversations(
    type: Optional[str] = Query(None, description="Lọc theo loại: DIRECT | GROUP"),
    limit: int = Query(20, ge=1, le=50, description="Số lượng tối đa mỗi trang"),
    cursor: Optional[str] = Query(None, description="Keyset pagination cursor"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.list_conversations(
        current_user, conv_type=type, limit=limit, cursor=cursor
    )


@router.get(
    "/owned-group-count",
    response_model=OwnedGroupSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Lấy số lượng nhóm do người dùng hiện tại sở hữu",
)
async def get_owned_group_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.get_owned_group_count(current_user)


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Lấy thông tin chi tiết cuộc trò chuyện",
)
async def get_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.get_conversation(current_user, conversation_id)


@router.patch(
    "/groups/{conversation_id}",
    response_model=ConversationDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Cập nhật thông tin nhóm (Tên, mô tả)",
)
async def update_group_metadata(
    conversation_id: int,
    payload: GroupUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.update_group_metadata(current_user, conversation_id, payload)


@router.post(
    "/groups/{conversation_id}/invites",
    response_model=List[ConversationInviteResponse],
    status_code=status.HTTP_200_OK,
    summary="Mời thành viên vào nhóm",
)
async def invite_members_to_group(
    conversation_id: int,
    payload: GroupInviteCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.invite_members_to_group(
        current_user, conversation_id, payload.invitee_ids
    )


@router.get(
    "/groups/{conversation_id}/pending-approvals",
    response_model=PendingApprovalListResponse,
    status_code=status.HTTP_200_OK,
    summary="Danh sách thành viên chờ phê duyệt vào nhóm (Chỉ trưởng nhóm)",
)
async def list_group_pending_approvals(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.list_pending_approvals(current_user, conversation_id)


@router.post(
    "/groups/{conversation_id}/pending-approvals/{invite_id}",
    status_code=status.HTTP_200_OK,
    summary="Phê duyệt hoặc từ chối yêu cầu vào nhóm (Chỉ trưởng nhóm)",
)
async def process_group_pending_approval(
    conversation_id: int,
    invite_id: int,
    payload: PendingApprovalActionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.process_pending_approval(
        current_user, conversation_id, invite_id, payload.action
    )


@router.get(
    "/{conversation_id}/invite-candidates",
    response_model=InviteCandidateListResponse,
    status_code=status.HTTP_200_OK,
    summary="Danh sách bạn bè từng trò chuyện trực tiếp để mời vào nhóm",
)
@router.get(
    "/groups/{conversation_id}/invite-candidates",
    response_model=InviteCandidateListResponse,
    status_code=status.HTTP_200_OK,
    summary="Danh sách bạn bè từng trò chuyện trực tiếp để mời vào nhóm (alias)",
)
async def get_invite_candidates(
    conversation_id: int,
    q: Optional[str] = Query(None, description="Tìm kiếm theo tên bạn bè"),
    limit: int = Query(20, ge=1, le=50, description="Số lượng gợi ý tối đa"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.get_invite_candidates(
        current_user, conversation_id, query=q, limit=limit
    )



@router.get(
    "/groups/{conversation_id}/members",
    response_model=List[ConversationMemberResponse],
    status_code=status.HTTP_200_OK,
    summary="Danh sách thành viên nhóm",
)
async def list_group_members(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.list_group_members(current_user, conversation_id)


@router.post(
    "/groups/{conversation_id}/members/{user_id}/role",
    status_code=status.HTTP_200_OK,
    summary="Cập nhật vai trò thành viên (ADMIN / MEMBER)",
)
async def update_group_member_role(
    conversation_id: int,
    user_id: int,
    payload: GroupMemberRoleUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.update_member_role(
        current_user, conversation_id, user_id, payload.role
    )


@router.patch(
    "/groups/{conversation_id}/me/nickname",
    response_model=ConversationMemberResponse,
    status_code=status.HTTP_200_OK,
    summary="Tự đặt hoặc xóa biệt danh của bản thân trong nhóm",
)
async def update_group_member_nickname(
    conversation_id: int,
    payload: GroupMemberNicknameUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.update_own_nickname(current_user, conversation_id, payload)


@router.post(
    "/groups/{conversation_id}/transfer-ownership",
    status_code=status.HTTP_200_OK,
    summary="Chuyển nhượng quyền chủ nhóm",
)
async def transfer_group_ownership(
    conversation_id: int,
    payload: GroupTransferOwnershipRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.transfer_ownership(
        current_user, conversation_id, payload.new_owner_id
    )


@router.delete(
    "/groups/{conversation_id}/members/{user_id}",
    status_code=status.HTTP_200_OK,
    summary="Xóa thành viên khỏi nhóm",
)
async def remove_group_member(
    conversation_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.remove_member(current_user, conversation_id, user_id)


@router.post(
    "/groups/{conversation_id}/leave",
    status_code=status.HTTP_200_OK,
    summary="Rời khỏi nhóm",
)
async def leave_group(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.leave_group(current_user, conversation_id)


@router.delete(
    "/groups/{conversation_id}",
    status_code=status.HTTP_200_OK,
    summary="Xóa nhóm trò chuyện (Chỉ Trưởng nhóm)",
)
async def delete_group(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.delete_group(current_user, conversation_id)


@router.get(
    "/{conversation_id}/attachments",
    response_model=SharedAttachmentListResponse,
    status_code=status.HTTP_200_OK,
    summary="Lấy danh sách tệp đính kèm đã chia sẻ (media, audio, file)",
)
async def get_shared_attachments(
    conversation_id: int,
    category: Optional[str] = Query(None, description="Loại tệp: media | audio | file"),
    kind: Optional[str] = Query(None, description="Alias cho category"),
    limit: int = Query(30, ge=1, le=100, description="Số lượng tối đa mỗi trang"),
    cursor: Optional[str] = Query(None, description="Keyset cursor"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    selected_category = category or kind or "media"
    return await service.get_shared_attachments(
        current_user, conversation_id, category=selected_category, limit=limit, cursor=cursor
    )


@router.get(
    "/{conversation_id}/attachments/summary",
    response_model=SharedAttachmentSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Lấy tổng số lượng tệp đã chia sẻ theo từng danh mục",
)
async def get_shared_attachments_summary(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.get_shared_attachments_summary(current_user, conversation_id)


@router.post(
    "/{conversation_id}/attachments/{attachment_id}/download-ticket",
    response_model=AttachmentDownloadTicketResponse,
    status_code=status.HTTP_200_OK,
    summary="Tạo mã tải xuống dùng 1 lần (60s) cho trình duyệt",
)
async def create_attachment_download_ticket(
    conversation_id: int,
    attachment_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.create_download_ticket(current_user, conversation_id, attachment_id)


async def fetch_upstream_asset(target_url: str) -> tuple[httpx.AsyncClient, httpx.Response]:
    client = httpx.AsyncClient(timeout=120.0, follow_redirects=False)
    req = client.build_request("GET", target_url)
    upstream_resp = await client.send(req, stream=True)
    return client, upstream_resp


async def get_current_user_optional(
    request: Request,
    auth_header: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    Route-specific optional bearer auth for the download endpoint.
    Preserves global auth invariants and supports test dependency overrides.
    """
    if not auth_header or not auth_header.credentials:
        return None
    override = request.app.dependency_overrides.get(get_current_user)
    if override:
        return override()
    try:
        payload = verify_firebase_token(auth_header.credentials)
    except FirebaseVerificationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    auth_service = AuthService(db)
    return await auth_service.get_or_create_user_from_token_payload(payload)


@router.get(
    "/{conversation_id}/attachments/{attachment_id}/download",
    summary="Tải tệp đính kèm với luồng dữ liệu an toàn và tên tệp gốc",
)
async def download_attachment(
    conversation_id: int,
    attachment_id: int,
    ticket: Optional[str] = Query(None, description="Mã tải xuống dùng 1 lần"),
    direct_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    if ticket:
        user_id = await service.consume_download_ticket(conversation_id, attachment_id, ticket)
        meta = await service.authorize_and_get_attachment_metadata(user_id, conversation_id, attachment_id)
    elif direct_user:
        meta = await service.authorize_and_get_attachment_metadata(direct_user.user_id, conversation_id, attachment_id)
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Yêu cầu xác thực qua ticket hoặc Authorization Bearer header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        client, upstream_resp = await fetch_upstream_asset(meta.target_url)
        if upstream_resp.status_code >= 400:
            await upstream_resp.aclose()
            await client.aclose()
            logger.error(
                f"Cloudinary upstream returned {upstream_resp.status_code} for attachment {attachment_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Không thể tải tệp từ kho lưu trữ.",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to connect to upstream storage for attachment {attachment_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Lỗi kết nối đến kho lưu trữ tệp.",
        ) from e

    content_disposition = format_content_disposition(meta.original_name, meta.mime_type)
    headers = {
        "Content-Disposition": content_disposition,
        "Content-Type": meta.mime_type or "application/octet-stream",
        "Cache-Control": "private, no-store",
    }

    upstream_cl = upstream_resp.headers.get("content-length")
    if upstream_cl and upstream_cl.isdigit() and int(upstream_cl) > 0:
        headers["Content-Length"] = upstream_cl

    async def body_stream():
        try:
            async for chunk in upstream_resp.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await upstream_resp.aclose()
            await client.aclose()

    return StreamingResponse(body_stream(), headers=headers)


@router.get(
    "/{conversation_id}/presence",
    response_model=PresenceBatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Lấy trạng thái trực tuyến của các thành viên trong cuộc trò chuyện",
)
async def get_conversation_presence(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.get_conversation_presence(current_user, conversation_id)


@router.get(
    "/{conversation_id}/messages",
    response_model=MessageListResponse,
    status_code=status.HTTP_200_OK,
    summary="Lấy lịch sử tin nhắn trong cuộc trò chuyện",
)
async def get_messages(
    conversation_id: int,
    limit: int = Query(30, ge=1, le=100, description="Số lượng tin nhắn tối đa"),
    cursor: Optional[str] = Query(None, description="Keyset pagination cursor"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.get_messages(
        current_user, conversation_id, limit=limit, cursor=cursor
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Gửi tin nhắn hoặc tệp đính kèm trong cuộc trò chuyện",
)
async def send_message(
    conversation_id: int,
    request: Request,
    content: Optional[str] = Form(None),
    product_id: Optional[int] = Form(None),
    voice_duration_ms: Optional[int] = Form(None),
    mentions: Optional[str] = Form(None),
    reply_to_message_id: Optional[int] = Form(None),
    files: List[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    content_type = request.headers.get("content-type", "")
    final_content = content
    final_product_id = product_id
    final_voice_duration_ms = voice_duration_ms
    final_reply_to_message_id = reply_to_message_id
    final_files = files
    final_mentions: List[dict] = []

    if mentions:
        try:
            parsed_m = json.loads(mentions)
            if isinstance(parsed_m, list):
                final_mentions = parsed_m
        except Exception:
            pass

    # Fallback support for application/json payloads
    if "application/json" in content_type:
        try:
            body = await request.json()
            final_content = body.get("content")
            final_product_id = body.get("product_id")
            final_voice_duration_ms = body.get("voice_duration_ms")
            final_reply_to_message_id = body.get("reply_to_message_id")
            final_files = []
            if body.get("mentions") and isinstance(body.get("mentions"), list):
                final_mentions = body.get("mentions")
        except Exception:
            pass

    service = ConversationService(db)
    return await service.send_message(
        current_user=current_user,
        conversation_id=conversation_id,
        content=final_content,
        product_id=final_product_id,
        files=final_files,
        voice_duration_ms=final_voice_duration_ms,
        mentions_data=final_mentions,
        reply_to_message_id=final_reply_to_message_id,
    )


@router.post(
    "/{conversation_id}/read",
    status_code=status.HTTP_200_OK,
    summary="Đánh dấu tin nhắn đã đọc trong cuộc trò chuyện",
)
async def mark_messages_read(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.mark_as_read(current_user, conversation_id)


@router.put(
    "/{conversation_id}/messages/{message_id}/reaction",
    response_model=MessageReactionSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Thêm hoặc thay đổi cảm xúc cho tin nhắn",
)
async def set_message_reaction(
    conversation_id: int,
    message_id: int,
    payload: MessageReactionSetRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.set_message_reaction(
        current_user=current_user,
        conversation_id=conversation_id,
        message_id=message_id,
        payload=payload,
    )


@router.delete(
    "/{conversation_id}/messages/{message_id}/reaction",
    response_model=MessageReactionSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Gỡ bỏ cảm xúc khỏi tin nhắn",
)
async def remove_message_reaction(
    conversation_id: int,
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    return await service.remove_message_reaction(
        current_user=current_user,
        conversation_id=conversation_id,
        message_id=message_id,
    )
