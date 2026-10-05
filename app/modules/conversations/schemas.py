from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_serializer


from app.core.datetime import ensure_utc_aware

ConversationType = Literal["DIRECT", "GROUP"]
MemberRole = Literal["OWNER", "ADMIN", "MEMBER"]
InviteStatus = Literal["PENDING", "PENDING_APPROVAL", "ACCEPTED", "DECLINED", "CANCELLED"]
MessageType = Literal["TEXT", "IMAGE", "FILE", "PRODUCT_CARD", "ORDER_CARD", "SYSTEM"]


class ReactionKey(str, Enum):
    THICH = "THICH"
    HAHA = "HAHA"
    WOW = "WOW"
    CAM_ON = "CAM_ON"
    CHOT_DEAL = "CHOT_DEAL"
    UY_TIN = "UY_TIN"
    DANG_TOI = "DANG_TOI"
    DOI_CHUT = "DOI_CHUT"
    QUAN_TAM = "QUAN_TAM"
    HET_TIEN = "HET_TIEN"
    HOC_BAI = "HOC_BAI"
    KHA_NGHI = "KHA_NGHI"


class ConversationCreateRequest(BaseModel):
    """
    Payload to initiate/open a marketplace conversation anchored to a product.
    """
    product_id: int = Field(..., gt=0, description="Product ID being discussed")


class DirectConversationCreateRequest(BaseModel):
    """
    Payload to initiate/open the canonical 1-to-1 Direct conversation directly with a recipient.
    Strictly accepts recipient_public_id (UUID v4) for client-facing identity.
    """
    model_config = ConfigDict(extra="forbid")

    recipient_public_id: UUID = Field(..., description="Recipient Public UUID (UUID v4)")



class ConversationFromOrderRequest(BaseModel):
    """
    Payload to initiate/open the canonical Direct conversation between buyer and seller of an order.
    """
    order_id: int = Field(..., gt=0, description="Order ID")



class GroupCreateRequest(BaseModel):
    """
    Payload to create a new user-owned Group chat.
    """
    title: str = Field(..., min_length=3, max_length=80, description="Group title")
    description: Optional[str] = Field(None, max_length=300, description="Optional group description")
    initial_invitee_ids: List[int] = Field(default_factory=list, description="List of user IDs to invite initially")


class GroupUpdateRequest(BaseModel):
    """
    Payload to update group metadata (title, description, requires_approval).
    """
    title: Optional[str] = Field(None, min_length=3, max_length=80)
    description: Optional[str] = Field(None, max_length=300)
    requires_approval: Optional[bool] = Field(None, description="Toggle whether new members require owner approval")


class GroupInviteCreateRequest(BaseModel):
    """
    Payload to invite one or more users to an existing group.
    """
    invitee_ids: List[int] = Field(..., min_length=1, description="List of user IDs to invite")


class GroupInviteRespondRequest(BaseModel):
    """
    Payload to accept or decline a pending group invite.
    """
    action: Literal["ACCEPT", "DECLINE"] = Field(..., description="Response action")


class GroupTransferOwnershipRequest(BaseModel):
    """
    Payload to transfer group ownership to another active member.
    """
    new_owner_id: int = Field(..., gt=0, description="New owner user ID")


class GroupMemberRoleUpdateRequest(BaseModel):
    """
    Payload to promote a member to ADMIN or demote to MEMBER.
    """
    role: Literal["ADMIN", "MEMBER"] = Field(..., description="Target role")


class GroupMemberNicknameUpdateRequest(BaseModel):
    """
    Payload to update authenticated member's nickname in a group.
    """
    nickname: Optional[str] = Field(None, max_length=40, description="Group nickname (null or empty string to clear)")


class ParticipantSummary(BaseModel):
    """
    Safe public profile summary for chat participants.
    Excludes private fields (email, phone, role, status, bank details, etc.)
    """
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    public_id: UUID
    full_name: str
    avatar_url: Optional[str] = None


class UserSearchResponse(BaseModel):
    """
    Safe public projection for user search in group invites.
    """
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    public_id: UUID
    full_name: str
    avatar_url: Optional[str] = None


class ConversationMemberResponse(BaseModel):
    """
    Summary of a member in a conversation.
    """
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    public_id: UUID
    full_name: str
    avatar_url: Optional[str] = None
    role: str
    joined_at: datetime
    is_online: Optional[bool] = None
    nickname: Optional[str] = None


class ConversationInviteResponse(BaseModel):
    """
    Public representation of a group chat invitation.
    """
    model_config = ConfigDict(from_attributes=True)

    invite_id: int
    conversation_id: int
    conversation_title: str
    inviter_id: int
    inviter_name: str
    inviter_avatar: Optional[str] = None
    status: str
    created_at: datetime


class ProductContextSummary(BaseModel):
    """
    Compact snapshot of the product context inside chat.
    """
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    title: str
    price: Decimal
    status: str
    thumbnail_url: Optional[str] = None
    listing_type: str = "FIXED_PRICE"


class MessageAttachmentResponse(BaseModel):
    """
    Public metadata for a message attachment.
    Excludes private storage keys / credentials.
    """
    model_config = ConfigDict(from_attributes=True)

    attachment_id: int
    kind: str  # 'IMAGE' | 'VIDEO' | 'PDF' | 'AUDIO' | 'DOCUMENT'
    url: str
    mime_type: str
    original_name: str
    size_bytes: int
    duration_ms: Optional[int] = None


class MessageMentionCreate(BaseModel):
    """
    Payload schema for a structured mention submitted during message creation.
    """
    mentioned_user_id: int = Field(..., gt=0)
    display_text: str = Field(..., min_length=1, max_length=100)
    start_offset: int = Field(..., ge=0)
    end_offset: int = Field(..., ge=0)


class MessageMentionResponse(BaseModel):
    """
    Safe public projection for a structured mention in a message.
    """
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    display_name: str
    display_text: str
    start_offset: int
    end_offset: int


class MessageCreateRequest(BaseModel):
    """
    Payload for sending a new message in a conversation.
    """
    content: Optional[str] = Field(None, max_length=2000, description="Message text content")
    product_id: Optional[int] = Field(None, gt=0, description="Optional product context anchor")
    mentions: List[MessageMentionCreate] = Field(default_factory=list, description="Structured user mentions")
    reply_to_message_id: Optional[int] = Field(None, gt=0, description="Optional parent message ID to reply to")


class ReactionAggregateResponse(BaseModel):
    """
    Aggregate count for a specific reaction on a message.
    """
    model_config = ConfigDict(from_attributes=True)

    reaction_key: ReactionKey
    count: int


class MessageReactionSetRequest(BaseModel):
    """
    Payload for setting or switching authenticated user's reaction on a message.
    """
    reaction_key: ReactionKey


class MessageReactionSummaryResponse(BaseModel):
    """
    Public response summarizing reactions on a message for the current user.
    """
    model_config = ConfigDict(from_attributes=True)

    message_id: int
    reactions: List[ReactionAggregateResponse] = Field(default_factory=list)
    my_reaction: Optional[ReactionKey] = None


class ReplyMessageSummary(BaseModel):
    """
    Compact one-level projection of a replied message to avoid recursive trees.
    """
    model_config = ConfigDict(from_attributes=True)

    message_id: int
    sender_id: int
    sender_name: Optional[str] = None
    type: MessageType = "TEXT"
    preview: str


class MessageResponse(BaseModel):
    """
    Public message representation for chat thread.
    """
    model_config = ConfigDict(from_attributes=True)

    message_id: int
    conversation_id: int
    sender_id: int
    sender_public_id: Optional[UUID] = None
    sender_name: Optional[str] = None
    sender_avatar: Optional[str] = None
    type: MessageType = "TEXT"
    content: Optional[str] = None
    product_id: Optional[int] = None
    product: Optional[ProductContextSummary] = None
    sent_at: datetime
    is_mine: bool = False
    is_deleted: bool = False
    attachments: List[MessageAttachmentResponse] = Field(default_factory=list)
    mentions: List[MessageMentionResponse] = Field(default_factory=list)
    reactions: List[ReactionAggregateResponse] = Field(default_factory=list)
    my_reaction: Optional[ReactionKey] = None
    reply_to: Optional[ReplyMessageSummary] = None

    @field_serializer("sent_at", when_used="json")
    def serialize_sent_at(self, dt: datetime) -> str:
        aware = ensure_utc_aware(dt)
        return aware.isoformat().replace("+00:00", "Z")


class ConversationSummaryResponse(BaseModel):
    """
    Inbox row item representing a conversation (Direct or Group).
    """
    model_config = ConfigDict(from_attributes=True)

    conversation_id: int
    type: str = "DIRECT"  # 'DIRECT' | 'GROUP'
    title: Optional[str] = None
    avatar_url: Optional[str] = None
    other_participant: Optional[ParticipantSummary] = None
    member_count: Optional[int] = None
    my_role: Optional[str] = None
    is_joined: Optional[bool] = None
    product_context: Optional[ProductContextSummary] = None
    last_message_preview: Optional[str] = None
    last_message_at: Optional[datetime] = None
    unread_count: int = 0
    created_at: datetime

    @field_serializer("last_message_at", when_used="json")
    def serialize_last_message_at(self, dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        aware = ensure_utc_aware(dt)
        return aware.isoformat().replace("+00:00", "Z")


class ConversationListResponse(BaseModel):
    """
    Bounded paginated list of user's active conversations.
    """
    items: List[ConversationSummaryResponse] = Field(default_factory=list)
    next_cursor: Optional[str] = None
    has_more: bool = False
    owned_group_count: int = 0


class OwnedGroupSummaryResponse(BaseModel):
    """
    Truthful server-derived summary for user's owned group count.
    """
    owned_group_count: int


class ConversationDetailResponse(BaseModel):
    """
    Conversation header metadata for active chat thread.
    """
    model_config = ConfigDict(from_attributes=True)

    conversation_id: int
    type: str = "DIRECT"
    title: Optional[str] = None
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    other_participant: Optional[ParticipantSummary] = None
    member_count: Optional[int] = None
    my_role: Optional[str] = None
    is_joined: Optional[bool] = None
    product_context: Optional[ProductContextSummary] = None
    created_at: datetime
    requires_approval: bool = False


class OfficialSupportGroupResponse(BaseModel):
    """
    Dedicated DTO for rendering the system-level official support entry.
    """
    model_config = ConfigDict(from_attributes=True)

    conversation_id: int
    title: str
    description: Optional[str] = None
    is_member: bool
    last_message_preview: Optional[str] = None
    last_message_at: Optional[datetime] = None
    unread_count: int = 0

    @field_serializer("last_message_at", when_used="json")
    def serialize_last_message_at(self, dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        aware = ensure_utc_aware(dt)
        return aware.isoformat().replace("+00:00", "Z")



class PendingApprovalItem(BaseModel):
    """
    Projection for an invite pending owner approval.
    """
    model_config = ConfigDict(from_attributes=True)

    invite_id: int
    conversation_id: int
    invitee_id: int
    invitee_name: str
    invitee_avatar: Optional[str] = None
    inviter_id: int
    inviter_name: str
    inviter_avatar: Optional[str] = None
    created_at: datetime
    responded_at: Optional[datetime] = None


class PendingApprovalListResponse(BaseModel):
    """
    Wrapper response for pending approval list.
    """
    items: List[PendingApprovalItem] = Field(default_factory=list)


class PendingApprovalActionRequest(BaseModel):
    """
    Payload for approving or rejecting a pending join request.
    """
    action: Literal["APPROVE", "REJECT"] = Field(..., description="Action to perform on pending invite")


class MessageListResponse(BaseModel):
    """
    Paginated message history for a conversation.
    """
    items: List[MessageResponse] = Field(default_factory=list)
    next_cursor: Optional[str] = None
    has_more: bool = False


class SharedAttachmentItemResponse(BaseModel):
    """
    Item projection for shared media, audio, or document file in a conversation.
    """
    model_config = ConfigDict(from_attributes=True)

    attachment_id: int
    message_id: int
    kind: str  # 'IMAGE' | 'VIDEO' | 'PDF' | 'AUDIO' | 'DOCUMENT'
    url: str
    mime_type: str
    original_name: str
    size_bytes: int
    duration_ms: Optional[int] = None
    created_at: datetime
    sender_id: int
    sender_name: Optional[str] = None
    sender_avatar: Optional[str] = None


class SharedAttachmentListResponse(BaseModel):
    """
    Cursor-paginated list of shared attachments in a conversation.
    """
    items: List[SharedAttachmentItemResponse] = Field(default_factory=list)
    next_cursor: Optional[str] = None
    has_more: bool = False


class SharedAttachmentSummaryResponse(BaseModel):
    """
    Summary counts for media, audio, and documents in a conversation.
    """
    media_count: int = 0
    audio_count: int = 0
    file_count: int = 0


class PresenceBatchResponse(BaseModel):
    """
    Truthful presence status indicating availability of presence infrastructure
    and set of online user IDs.
    """
    presence_available: bool
    online_user_ids: List[int] = Field(default_factory=list)


class InviteCandidateItem(BaseModel):
    """
    Candidate user from prior Direct interactions eligible for Group invitation.
    """
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    full_name: str
    avatar_url: Optional[str] = None
    last_interaction_at: Optional[datetime] = None


class InviteCandidateListResponse(BaseModel):
    """
    List of eligible invite candidates for a group.
    """
    items: List[InviteCandidateItem] = Field(default_factory=list)


class AttachmentDownloadTicketResponse(BaseModel):
    """
    Opaque, short-lived download ticket for native browser navigation.
    Contains no Firebase credentials or tokens.
    """
    ticket: str
    download_url: str
    expires_in_seconds: int = 60


class OfficialSupportGroupJoinResponse(BaseModel):
    """
    Response returned when resolving/joining the configured official support group.
    """
    conversation_id: int
