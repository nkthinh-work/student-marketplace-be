import base64
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, case, delete, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload, selectinload

from app.core.config import settings
from app.core.realtime.presence import get_users_presence
from app.integrations.cloudinary import generate_delivery_url
from app.modules.notifications.models import Notification, NotificationType
from app.modules.conversations.models import (
    Conversation,
    ConversationInvite,
    ConversationMember,
    MediaCleanupJob,
    Message,
    MessageAttachment,
    MessageMention,
    MessageReaction,
)
from app.modules.conversations.schemas import (
    ConversationInviteResponse,
    ConversationMemberResponse,
    ConversationSummaryResponse,
    InviteCandidateItem,
    MessageAttachmentResponse,
    MessageMentionResponse,
    MessageReactionSummaryResponse,
    MessageResponse,
    ParticipantSummary,
    ProductContextSummary,
    ReactionAggregateResponse,
    ReactionKey,
    ReplyMessageSummary,
    SharedAttachmentItemResponse,
    UserSearchResponse,
)
from app.modules.orders.models import Order
from app.modules.products.models import Product, ProductImage
from app.modules.users.models import User, UserStatus


def encode_cursor(data: dict) -> str:
    """Encodes a dictionary cursor into a URL-safe Base64 string."""
    json_bytes = json.dumps(data, default=str).encode("utf-8")
    return base64.urlsafe_b64encode(json_bytes).decode("utf-8")


def decode_cursor(cursor_str: str) -> dict:
    """Decodes a URL-safe Base64 string into a cursor dictionary."""
    try:
        json_bytes = base64.urlsafe_b64decode(cursor_str.encode("utf-8"))
        return json.loads(json_bytes.decode("utf-8"))
    except Exception as e:
        raise ValueError("Invalid cursor format") from e


def _map_kind_to_resource_type(kind: str) -> str:
    k = kind.upper()
    if k == "IMAGE":
        return "image"
    if k in ("VIDEO", "AUDIO"):
        return "video"
    return "raw"


def _format_message_preview(msg: Message) -> Optional[str]:
    if msg.content:
        return msg.content
    if msg.attachments:
        first_att = msg.attachments[0]
        if first_att.kind == "IMAGE":
            return "[Hình ảnh]"
        elif first_att.kind == "VIDEO":
            return "[Video]"
        elif first_att.kind == "AUDIO":
            return "[Tin nhắn thoại]"
        elif first_att.kind == "PDF":
            return "[Tệp PDF]"
        elif first_att.kind == "DOCUMENT":
            return "[Tài liệu]"
        return "[Tệp đính kèm]"
    if msg.product_id:
        return "[Sản phẩm]"
    return None


def build_reply_summary(target: Optional[Message]) -> Optional[ReplyMessageSummary]:
    """
    Builds a safe, compact one-level ReplyMessageSummary.
    Never loads child relationships recursively.
    """
    if not target:
        return None
    if getattr(target, "is_deleted", False):
        preview = "Tin nhắn không còn khả dụng"
    else:
        msg_type = getattr(target, "type", "TEXT") or "TEXT"
        if msg_type == "IMAGE":
            preview = "Hình ảnh"
        elif msg_type == "FILE":
            preview = "Tệp đính kèm"
        elif msg_type == "AUDIO":
            preview = "Tin nhắn thoại"
        elif msg_type == "VIDEO":
            preview = "Video"
        elif msg_type == "PRODUCT_CARD":
            preview = "Sản phẩm"
        elif msg_type == "ORDER_CARD":
            preview = "Đơn hàng"
        else:
            raw_text = (getattr(target, "content", None) or "").strip()
            normalized = re.sub(r"\s+", " ", raw_text)
            if len(normalized) > 120:
                normalized = normalized[:120].rstrip() + "..."
            preview = normalized or "Tin nhắn"

    sender = getattr(target, "sender", None)
    sender_name = sender.full_name if sender else None

    return ReplyMessageSummary(
        message_id=target.message_id,
        sender_id=target.sender_id,
        sender_name=sender_name,
        type=getattr(target, "type", "TEXT") or "TEXT",
        preview=preview,
    )


class ConversationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_direct_conversation(
        self, user_a_id: int, user_b_id: int
    ) -> Conversation:
        """
        Race-safe retrieval or insertion of the canonical 1-to-1 conversation
        between user_a and user_b using direct_pair_key.
        """
        u1 = min(user_a_id, user_b_id)
        u2 = max(user_a_id, user_b_id)
        pair_key = f"{u1}:{u2}"
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # 1. Attempt race-safe INSERT ON CONFLICT (direct_pair_key) DO NOTHING
        stmt_insert = (
            insert(Conversation)
            .values(
                type="DIRECT",
                direct_pair_key=pair_key,
                user_one_id=u1,
                user_two_id=u2,
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=["direct_pair_key"])
            .returning(Conversation.conversation_id)
        )
        result = await self.db.execute(stmt_insert)
        new_id = result.scalar_one_or_none()

        if new_id is not None:
            # Insert the 2 members
            stmt_members = insert(ConversationMember).values(
                [
                    {"conversation_id": new_id, "user_id": u1, "role": "MEMBER", "joined_at": now},
                    {"conversation_id": new_id, "user_id": u2, "role": "MEMBER", "joined_at": now},
                ]
            )
            await self.db.execute(stmt_members)
            await self.db.commit()
            return await self.get_conversation_by_id(new_id)

        # 2. Existing conversation: query and ensure both are active members
        stmt_select = select(Conversation).where(
            Conversation.direct_pair_key == pair_key
        )
        conv = await self.db.scalar(stmt_select)
        if conv:
            # Guarantee both members are active
            stmt_m1 = (
                insert(ConversationMember)
                .values(conversation_id=conv.conversation_id, user_id=u1, role="MEMBER", joined_at=now)
                .on_conflict_do_nothing(index_elements=["conversation_id", "user_id"])
            )
            stmt_m2 = (
                insert(ConversationMember)
                .values(conversation_id=conv.conversation_id, user_id=u2, role="MEMBER", joined_at=now)
                .on_conflict_do_nothing(index_elements=["conversation_id", "user_id"])
            )
            await self.db.execute(stmt_m1)
            await self.db.execute(stmt_m2)
            await self.db.commit()

        return conv

    async def get_or_create_conversation_from_order(
        self, order_id: int, current_user_id: int
    ) -> Optional[Conversation]:
        """
        Resolves the other participant from an Order and returns the canonical Direct conversation.
        """
        stmt_order = select(Order).where(Order.order_id == order_id)
        order = await self.db.scalar(stmt_order)
        if not order:
            return None
        if current_user_id not in (order.buyer_id, order.seller_id):
            return None

        other_user_id = order.seller_id if current_user_id == order.buyer_id else order.buyer_id
        return await self.get_or_create_direct_conversation(current_user_id, other_user_id)

    async def create_group_conversation(
        self,
        owner_id: int,
        title: str,
        description: Optional[str] = None,
        initial_invitee_ids: Optional[List[int]] = None,
    ) -> Conversation:
        """
        Creates a new user-owned Group chat, enforcing MAX_GROUPS_OWNED_PER_USER = 10.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # Check user's currently owned active groups count
        count_stmt = (
            select(func.count(ConversationMember.conversation_id))
            .join(Conversation, Conversation.conversation_id == ConversationMember.conversation_id)
            .where(
                ConversationMember.user_id == owner_id,
                ConversationMember.role == "OWNER",
                Conversation.type == "GROUP",
                ConversationMember.left_at.is_(None),
            )
        )
        owned_count = (await self.db.scalar(count_stmt)) or 0
        if owned_count >= 10:
            raise ValueError("USER_GROUPS_CAP_EXCEEDED")

        conv = Conversation(
            type="GROUP",
            title=title.strip(),
            description=description.strip() if description else None,
            created_at=now,
        )
        self.db.add(conv)
        await self.db.flush()

        # Add owner member
        owner_member = ConversationMember(
            conversation_id=conv.conversation_id,
            user_id=owner_id,
            role="OWNER",
            joined_at=now,
        )
        self.db.add(owner_member)
        await self.db.flush()

        # Send initial invitations (up to 49 unique invitees)
        if initial_invitee_ids:
            unique_invitees = [uid for uid in set(initial_invitee_ids) if uid != owner_id][:49]
            for invitee_id in unique_invitees:
                invite = ConversationInvite(
                    conversation_id=conv.conversation_id,
                    inviter_id=owner_id,
                    invitee_id=invitee_id,
                    status="PENDING",
                    created_at=now,
                )
                self.db.add(invite)

        await self.db.commit()
        return conv

    async def join_support_group(
        self, conversation_id: int, user_id: int
    ) -> ConversationMember:
        """
        Joins or rejoins the official support group idempotently.
        Initializes last_read_message_id to current latest message so old messages are not unread.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        latest_msg_stmt = (
            select(func.max(Message.message_id))
            .where(Message.conversation_id == conversation_id, Message.is_deleted.is_(False))
        )
        latest_msg_id = await self.db.scalar(latest_msg_stmt)

        stmt_mem = select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
        )
        mem = await self.db.scalar(stmt_mem)
        if mem:
            if mem.left_at is not None:
                mem.left_at = None
                mem.joined_at = now
                mem.last_read_message_id = latest_msg_id
        else:
            mem = ConversationMember(
                conversation_id=conversation_id,
                user_id=user_id,
                role="MEMBER",
                joined_at=now,
                last_read_message_id=latest_msg_id,
            )
            self.db.add(mem)

        await self.db.commit()
        return mem

    async def get_conversation_by_id(
        self, conversation_id: int
    ) -> Optional[Conversation]:
        """Fetch active conversation by ID."""
        stmt = select(Conversation).where(
            Conversation.conversation_id == conversation_id,
            Conversation.deleted_at.is_(None),
        )
        return await self.db.scalar(stmt)

    async def get_conversation_with_member(
        self, conversation_id: int, user_id: int
    ) -> Tuple[Optional[Conversation], Optional[ConversationMember]]:
        """
        Fetches conversation and active membership for user_id.
        Returns (None, None) if user is not an active member.
        """
        conv = await self.get_conversation_by_id(conversation_id)
        if not conv:
            return None, None

        stmt_mem = select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
            ConversationMember.left_at.is_(None),
        )
        member = await self.db.scalar(stmt_mem)
        if not member:
            return None, None

        return conv, member

    async def list_user_conversations(
        self,
        user_id: int,
        conv_type: Optional[str] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> Tuple[List[ConversationSummaryResponse], Optional[str], bool, int]:
        """
        Fetches bounded page of active conversations using keyset cursor pagination with ZERO N+1 queries.
        """
        # Base query: user is active member
        stmt = (
            select(Conversation, ConversationMember)
            .join(
                ConversationMember,
                and_(
                    ConversationMember.conversation_id == Conversation.conversation_id,
                    ConversationMember.user_id == user_id,
                    ConversationMember.left_at.is_(None),
                ),
            )
            .where(
                Conversation.deleted_at.is_(None),
                or_(
                    Conversation.last_message_at.is_not(None),
                    Conversation.type == "GROUP",
                ),
            )
        )
        if conv_type:
            stmt = stmt.where(Conversation.type == conv_type)

        # Apply Keyset Cursor: (COALESCE(last_message_at, created_at), conversation_id)
        if cursor:
            cursor_data = decode_cursor(cursor)
            cursor_dt = datetime.fromisoformat(cursor_data["last_message_at"])
            cursor_id = int(cursor_data["conversation_id"])
            stmt = stmt.where(
                tuple_(
                    func.coalesce(Conversation.last_message_at, Conversation.created_at),
                    Conversation.conversation_id,
                )
                < (cursor_dt, cursor_id)
            )

        stmt = stmt.order_by(
            func.coalesce(Conversation.last_message_at, Conversation.created_at).desc(),
            Conversation.conversation_id.desc(),
        ).limit(limit + 1)

        rows = (await self.db.execute(stmt)).all()
        has_more = len(rows) > limit
        page_rows = rows[:limit]

        if not page_rows:
            owned_group_count = await self.get_user_owned_group_count(user_id)
            return [], None, False, owned_group_count

        conv_items = [r[0] for r in page_rows]
        member_items = {r[0].conversation_id: r[1] for r in page_rows}
        conv_ids = [c.conversation_id for c in conv_items]

        last_item = conv_items[-1]
        last_dt = last_item.last_message_at or last_item.created_at
        next_cursor = (
            encode_cursor(
                {
                    "last_message_at": last_dt.isoformat(),
                    "conversation_id": last_item.conversation_id,
                }
            )
            if has_more
            else None
        )

        # BATCH QUERY 1: Other participants for DIRECT conversations
        direct_conv_ids = [c.conversation_id for c in conv_items if c.type == "DIRECT"]
        direct_other_users_map = {}
        if direct_conv_ids:
            direct_members_stmt = (
                select(ConversationMember)
                .options(selectinload(ConversationMember.user))
                .where(
                    ConversationMember.conversation_id.in_(direct_conv_ids),
                    ConversationMember.user_id != user_id,
                )
            )
            direct_members = (await self.db.scalars(direct_members_stmt)).all()
            for dm in direct_members:
                direct_other_users_map[dm.conversation_id] = dm.user

        # BATCH QUERY 2: Member counts for GROUP
        group_conv_ids = [c.conversation_id for c in conv_items if c.type == "GROUP"]
        member_counts_map = {}
        if group_conv_ids:
            count_stmt = (
                select(ConversationMember.conversation_id, func.count(ConversationMember.user_id))
                .where(
                    ConversationMember.conversation_id.in_(group_conv_ids),
                    ConversationMember.left_at.is_(None),
                )
                .group_by(ConversationMember.conversation_id)
            )
            member_counts_map = dict((await self.db.execute(count_stmt)).all())

        # BATCH QUERY 3: Latest message per conversation with attachments eager loaded (EXCLUDE SYSTEM)
        latest_msg_stmt = (
            select(Message)
            .options(selectinload(Message.attachments))
            .distinct(Message.conversation_id)
            .where(
                Message.conversation_id.in_(conv_ids),
                Message.is_deleted.is_(False),
                Message.type != "SYSTEM",
            )
            .order_by(
                Message.conversation_id,
                Message.sent_at.desc(),
                Message.message_id.desc(),
            )
        )
        latest_msgs = (await self.db.scalars(latest_msg_stmt)).all()
        latest_msg_map = {m.conversation_id: m for m in latest_msgs}

        # BATCH QUERY 4: Unread message counts per conversation using member's last_read_message_id (EXCLUDE SYSTEM)
        unread_map = {}
        for conv in conv_items:
            m_info = member_items.get(conv.conversation_id)
            last_read_id = m_info.last_read_message_id if m_info else 0
            joined_at = m_info.joined_at if m_info else conv.created_at

            unread_q = (
                select(func.count(Message.message_id))
                .where(
                    Message.conversation_id == conv.conversation_id,
                    Message.sender_id != user_id,
                    Message.is_deleted.is_(False),
                    Message.type != "SYSTEM",
                    Message.message_id > (last_read_id or 0),
                    (Message.sent_at >= joined_at if conv.type == "GROUP" else True),
                )
            )
            count_val = (await self.db.scalar(unread_q)) or 0
            unread_map[conv.conversation_id] = count_val

        # BATCH QUERY 5: Contextual products
        product_ids = [
            m.product_id for m in latest_msgs if m.product_id is not None
        ]
        products_map = {}
        if product_ids:
            prod_stmt = (
                select(Product)
                .options(selectinload(Product.images))
                .where(Product.product_id.in_(product_ids), Product.is_deleted.is_(False))
            )
            products_map = {p.product_id: p for p in (await self.db.scalars(prod_stmt)).all()}

        # Construct summaries
        summaries: List[ConversationSummaryResponse] = []
        for conv in conv_items:
            m_info = member_items.get(conv.conversation_id)
            other_u = direct_other_users_map.get(conv.conversation_id)

            part_summary = None
            if conv.type == "DIRECT":
                part_summary = ParticipantSummary(
                    user_id=other_u.user_id if other_u else 0,
                    full_name=other_u.full_name if other_u else "Người dùng",
                    avatar_url=other_u.avatar_url if other_u else None,
                )

            latest_m = latest_msg_map.get(conv.conversation_id)
            prod_ctx = None
            if latest_m and latest_m.product_id and latest_m.product_id in products_map:
                prod = products_map[latest_m.product_id]
                thumb = next((img.image_url for img in prod.images if img.is_thumbnail), None)
                if not thumb and prod.images:
                    thumb = prod.images[0].image_url
                prod_ctx = ProductContextSummary(
                    product_id=prod.product_id,
                    title=prod.title,
                    price=prod.price,
                    status=prod.status.value if hasattr(prod.status, "value") else str(prod.status),
                    thumbnail_url=thumb,
                    listing_type=prod.listing_type.value if hasattr(prod.listing_type, "value") else str(prod.listing_type),
                )

            summaries.append(
                ConversationSummaryResponse(
                    conversation_id=conv.conversation_id,
                    type=conv.type,
                    title=conv.title if conv.type != "DIRECT" else (other_u.full_name if other_u else "Người dùng"),
                    avatar_url=conv.avatar_url if conv.type != "DIRECT" else (other_u.avatar_url if other_u else None),
                    other_participant=part_summary,
                    member_count=member_counts_map.get(conv.conversation_id, 2 if conv.type == "DIRECT" else 1),
                    my_role=m_info.role if m_info else "MEMBER",
                    is_joined=m_info is not None,
                    product_context=prod_ctx,
                    last_message_preview=_format_message_preview(latest_m) if latest_m else None,
                    last_message_at=conv.last_message_at,
                    unread_count=unread_map.get(conv.conversation_id, 0),
                    created_at=conv.created_at,
                )
            )

        owned_group_count = await self.get_user_owned_group_count(user_id)
        return summaries, next_cursor, has_more, owned_group_count

    async def get_user_owned_group_count(self, user_id: int) -> int:
        """Counts active GROUP conversations owned by user_id."""
        stmt = (
            select(func.count(ConversationMember.conversation_id))
            .join(Conversation, Conversation.conversation_id == ConversationMember.conversation_id)
            .where(
                ConversationMember.user_id == user_id,
                ConversationMember.role == "OWNER",
                ConversationMember.left_at.is_(None),
                Conversation.type == "GROUP",
                Conversation.deleted_at.is_(None),
            )
        )
        return (await self.db.scalar(stmt)) or 0

    async def get_messages(
        self,
        conversation_id: int,
        limit: int = 30,
        cursor: Optional[str] = None,
        current_user_id: Optional[int] = None,
        joined_at_filter: Optional[datetime] = None,
    ) -> Tuple[List[MessageResponse], Optional[str], bool]:
        """
        Fetches bounded page of messages for a conversation ordered newest first.
        Respects joined_at_filter for private groups.
        """
        stmt = (
            select(Message)
            .options(
                selectinload(Message.attachments),
                selectinload(Message.sender),
                selectinload(Message.product).selectinload(Product.images),
                selectinload(Message.mentions).selectinload(MessageMention.mentioned_user),
                selectinload(Message.reply_to).selectinload(Message.sender),
            )
            .where(
                Message.conversation_id == conversation_id,
            )
        )

        if joined_at_filter:
            stmt = stmt.where(Message.sent_at >= joined_at_filter)

        # Keyset condition: (sent_at, message_id) < (cursor_dt, cursor_id)
        if cursor:
            cursor_data = decode_cursor(cursor)
            cursor_dt = datetime.fromisoformat(cursor_data["sent_at"])
            cursor_id = int(cursor_data["message_id"])
            stmt = stmt.where(
                tuple_(Message.sent_at, Message.message_id) < (cursor_dt, cursor_id)
            )

        stmt = stmt.order_by(
            Message.sent_at.desc(),
            Message.message_id.desc(),
        ).limit(limit + 1)

        msg_rows = list((await self.db.scalars(stmt)).all())

        has_more = len(msg_rows) > limit
        items = msg_rows[:limit]

        next_cursor = None
        if has_more and items:
            last_item = items[-1]
            next_cursor = encode_cursor(
                {
                    "sent_at": last_item.sent_at.isoformat(),
                    "message_id": last_item.message_id,
                }
            )

        responses = []
        msg_ids = [m.message_id for m in items]
        reactions_map, my_reactions_map = await self.batch_get_reaction_summaries(
            msg_ids, current_user_id
        )

        for m in items:
            if m.is_deleted:
                responses.append(
                    MessageResponse(
                        message_id=m.message_id,
                        conversation_id=m.conversation_id,
                        sender_id=m.sender_id,
                        sender_name=m.sender.full_name if m.sender else None,
                        sender_avatar=m.sender.avatar_url if m.sender else None,
                        type=m.type,
                        content=None,
                        product_id=None,
                        product=None,
                        sent_at=m.sent_at,
                        is_mine=(current_user_id is not None and m.sender_id == current_user_id),
                        is_deleted=True,
                        attachments=[],
                        mentions=[],
                        reactions=[],
                        my_reaction=None,
                        reply_to=build_reply_summary(m.reply_to) if m.reply_to_message_id else None,
                    )
                )
                continue

            att_responses = [
                MessageAttachmentResponse(
                    attachment_id=att.attachment_id,
                    kind=att.kind,
                    url=generate_delivery_url(
                        public_id=att.storage_key,
                        resource_type=_map_kind_to_resource_type(att.kind),
                        default_url=att.url,
                    ),
                    mime_type=att.mime_type,
                    original_name=att.original_name,
                    size_bytes=att.size_bytes,
                    duration_ms=att.duration_ms,
                )
                for att in (m.attachments or [])
            ]

            prod_ctx = None
            if m.product:
                thumb = next((img.image_url for img in m.product.images if img.is_thumbnail), None)
                if not thumb and m.product.images:
                    thumb = m.product.images[0].image_url
                prod_ctx = ProductContextSummary(
                    product_id=m.product.product_id,
                    title=m.product.title,
                    price=m.product.price,
                    status=m.product.status.value if hasattr(m.product.status, "value") else str(m.product.status),
                    thumbnail_url=thumb,
                    listing_type=m.product.listing_type.value if hasattr(m.product.listing_type, "value") else str(m.product.listing_type),
                )

            mentions_resp = [
                MessageMentionResponse(
                    user_id=men.mentioned_user_id,
                    display_name=men.mentioned_user.full_name if men.mentioned_user else men.display_text.lstrip("@"),
                    display_text=men.display_text,
                    start_offset=men.start_offset,
                    end_offset=men.end_offset,
                )
                for men in (m.mentions or [])
            ]

            responses.append(
                MessageResponse(
                    message_id=m.message_id,
                    conversation_id=m.conversation_id,
                    sender_id=m.sender_id,
                    sender_name=m.sender.full_name if m.sender else None,
                    sender_avatar=m.sender.avatar_url if m.sender else None,
                    type=m.type,
                    content=m.content,
                    product_id=m.product_id,
                    product=prod_ctx,
                    sent_at=m.sent_at,
                    is_mine=(current_user_id is not None and m.sender_id == current_user_id),
                    is_deleted=False,
                    attachments=att_responses,
                    mentions=mentions_resp,
                    reactions=reactions_map.get(m.message_id, []),
                    my_reaction=my_reactions_map.get(m.message_id, None),
                    reply_to=build_reply_summary(m.reply_to) if m.reply_to_message_id else None,
                )
            )

        return responses, next_cursor, has_more

    async def get_message_by_id(self, message_id: int) -> Optional[Message]:
        """Loads a single message by ID with sender eagerly loaded."""
        stmt = (
            select(Message)
            .options(
                selectinload(Message.sender),
            )
            .where(Message.message_id == message_id)
        )
        return await self.db.scalar(stmt)

    async def create_message(
        self,
        conversation_id: int,
        sender_id: int,
        content: Optional[str] = None,
        product_id: Optional[int] = None,
        attachments_data: Optional[List[dict]] = None,
        mentions_data: Optional[List[dict]] = None,
        reply_to_message_id: Optional[int] = None,
    ) -> Message:
        """
        Persists a message with optional attachments and structured mentions atomically,
        updates last_message_at, and advances sender's last_read_message_id.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        msg = Message(
            conversation_id=conversation_id,
            sender_id=sender_id,
            content=content,
            product_id=product_id,
            type="TEXT",
            sent_at=now,
            reply_to_message_id=reply_to_message_id,
        )
        self.db.add(msg)
        await self.db.flush()

        if attachments_data:
            for att_data in attachments_data:
                att = MessageAttachment(
                    message_id=msg.message_id,
                    kind=att_data["kind"],
                    url=att_data["url"],
                    storage_key=att_data["storage_key"],
                    mime_type=att_data["mime_type"],
                    original_name=att_data["original_name"],
                    size_bytes=att_data["size_bytes"],
                    duration_ms=att_data.get("duration_ms"),
                    created_at=now,
                )
                self.db.add(att)
            await self.db.flush()

        if mentions_data:
            # Check conversation type: only GROUP allows mentions
            stmt_conv_type = select(Conversation.type).where(Conversation.conversation_id == conversation_id)
            ctype = await self.db.scalar(stmt_conv_type)
            if ctype != "GROUP":
                raise ValueError("MENTIONS_NOT_ALLOWED_FOR_CONVERSATION_TYPE")

            # Validate that every mentioned user is an active member
            mentioned_uids = {m["mentioned_user_id"] for m in mentions_data}
            active_mems_stmt = select(ConversationMember.user_id).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id.in_(mentioned_uids),
                ConversationMember.left_at.is_(None),
            )
            active_mem_ids = set((await self.db.scalars(active_mems_stmt)).all())

            # Deduplicate by mentioned_user_id to maintain clean 1-relation-per-user-per-message
            seen_uids = set()
            for m_data in mentions_data:
                target_uid = m_data["mentioned_user_id"]
                if target_uid not in active_mem_ids:
                    raise ValueError(f"USER_{target_uid}_NOT_ACTIVE_MEMBER")

                if target_uid in seen_uids:
                    continue
                seen_uids.add(target_uid)

                start = m_data["start_offset"]
                end = m_data["end_offset"]
                disp = m_data["display_text"]

                if not content or start < 0 or end > len(content) or start >= end:
                    raise ValueError("INVALID_MENTION_OFFSETS")

                if content[start:end] != disp:
                    raise ValueError("MENTION_TEXT_MISMATCH")

                mention_entity = MessageMention(
                    message_id=msg.message_id,
                    mentioned_user_id=target_uid,
                    display_text=disp,
                    start_offset=start,
                    end_offset=end,
                    created_at=now,
                )
                self.db.add(mention_entity)
            await self.db.flush()

        # Update parent conversation last_message_at
        stmt_conv = (
            update(Conversation)
            .where(Conversation.conversation_id == conversation_id)
            .values(last_message_at=now)
        )
        await self.db.execute(stmt_conv)

        # Update sender's last_read_message_id in conversation_members
        stmt_read = (
            update(ConversationMember)
            .where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == sender_id,
            )
            .values(last_read_message_id=msg.message_id)
        )
        await self.db.execute(stmt_read)

        await self.db.flush()

        # Refresh message with attachments, sender, product, mentions, and reply_to loaded
        stmt_refresh = (
            select(Message)
            .options(
                selectinload(Message.attachments),
                selectinload(Message.sender),
                selectinload(Message.product).selectinload(Product.images),
                selectinload(Message.mentions).selectinload(MessageMention.mentioned_user),
                selectinload(Message.reply_to).selectinload(Message.sender),
            )
            .where(Message.message_id == msg.message_id)
        )
        refreshed_msg = await self.db.scalar(stmt_refresh)
        return refreshed_msg or msg

    async def mark_as_read(self, conversation_id: int, reader_id: int) -> int:
        """
        Advances reader's last_read_message_id to the latest message in this conversation.
        Returns the count of unread messages marked as read.
        """
        latest_msg_stmt = (
            select(func.max(Message.message_id))
            .where(
                Message.conversation_id == conversation_id,
                Message.is_deleted.is_(False),
            )
        )
        max_id = await self.db.scalar(latest_msg_stmt)
        if not max_id:
            return 0

        stmt_mem = select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == reader_id,
            ConversationMember.left_at.is_(None),
        )
        mem = await self.db.scalar(stmt_mem)
        if not mem:
            return 0

        prev_read_id = mem.last_read_message_id or 0
        unread_q = (
            select(func.count(Message.message_id))
            .where(
                Message.conversation_id == conversation_id,
                Message.sender_id != reader_id,
                Message.message_id > prev_read_id,
                Message.message_id <= max_id,
                Message.is_deleted.is_(False),
            )
        )
        unread_count = (await self.db.scalar(unread_q)) or 0

        mem.last_read_message_id = max_id

        # Mark matching unread chat Bell notification as read
        stmt_notif = (
            update(Notification)
            .where(
                Notification.user_id == reader_id,
                Notification.type == NotificationType.NEW_MESSAGE.value,
                Notification.ref_type == "CONVERSATION",
                Notification.ref_id == conversation_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True)
        )
        await self.db.execute(stmt_notif)

        await self.db.commit()
        return unread_count

    async def create_invites(
        self, conversation_id: int, inviter_id: int, invitee_ids: List[int]
    ) -> List[ConversationInvite]:
        """
        Invites users to a group chat, enforcing MAX_ACTIVE_MEMBERS_PER_GROUP = 50.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # Lock conversation row to prevent race conditions during member capacity check
        stmt_lock = (
            select(Conversation)
            .where(Conversation.conversation_id == conversation_id)
            .with_for_update(of=Conversation)
        )
        conv = await self.db.scalar(stmt_lock)
        if not conv or conv.deleted_at is not None or conv.type != "GROUP":
            raise ValueError("INVALID_CONVERSATION")

        # Check inviter role: Any active member of GROUP can invite
        stmt_role = select(ConversationMember.role).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == inviter_id,
            ConversationMember.left_at.is_(None),
        )
        role = await self.db.scalar(stmt_role)
        if not role or role not in ("OWNER", "ADMIN", "MEMBER"):
            raise PermissionError("ONLY_ACTIVE_MEMBERS_CAN_INVITE")

        # Current active members count
        active_count_stmt = select(func.count(ConversationMember.user_id)).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.left_at.is_(None),
        )
        active_count = (await self.db.scalar(active_count_stmt)) or 0

        # Existing active members and pending invites
        existing_members_stmt = select(ConversationMember.user_id).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.left_at.is_(None),
        )
        active_uids = set((await self.db.scalars(existing_members_stmt)).all())

        pending_stmt = select(ConversationInvite.invitee_id).where(
            ConversationInvite.conversation_id == conversation_id,
            ConversationInvite.status == "PENDING",
        )
        pending_uids = set((await self.db.scalars(pending_stmt)).all())

        valid_invitee_ids = [
            uid for uid in set(invitee_ids)
            if uid not in active_uids and uid not in pending_uids and uid != inviter_id
        ]

        if active_count + len(valid_invitee_ids) > 50:
            raise ValueError("GROUP_CAP_EXCEEDED")

        invites = []
        for uid in valid_invitee_ids:
            inv = ConversationInvite(
                conversation_id=conversation_id,
                inviter_id=inviter_id,
                invitee_id=uid,
                status="PENDING",
                created_at=now,
            )
            self.db.add(inv)
            invites.append(inv)

        if invites:
            await self.db.flush()
        return invites

    async def list_user_invites(self, user_id: int) -> List[ConversationInviteResponse]:
        """
        Lists pending group invites for user_id.
        """
        stmt = (
            select(ConversationInvite)
            .options(
                selectinload(ConversationInvite.conversation),
                selectinload(ConversationInvite.inviter),
            )
            .where(
                ConversationInvite.invitee_id == user_id,
                ConversationInvite.status == "PENDING",
            )
            .order_by(ConversationInvite.created_at.desc())
        )
        invites = (await self.db.scalars(stmt)).all()

        return [
            ConversationInviteResponse(
                invite_id=inv.invite_id,
                conversation_id=inv.conversation_id,
                conversation_title=inv.conversation.title or "Nhóm trò chuyện",
                inviter_id=inv.inviter_id,
                inviter_name=inv.inviter.full_name if inv.inviter else "Người dùng",
                inviter_avatar=inv.inviter.avatar_url if inv.inviter else None,
                status=inv.status,
                created_at=inv.created_at,
            )
            for inv in invites
        ]

    async def respond_invite(
        self, invite_id: int, user_id: int, action: str
    ) -> Tuple[ConversationInvite, Optional[Conversation]]:
        """
        Accepts or declines a pending group invite.
        On accept, reactivates or creates ConversationMember row and enforces 50 member cap.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        stmt = select(ConversationInvite).where(
            ConversationInvite.invite_id == invite_id,
            ConversationInvite.invitee_id == user_id,
        )
        invite = await self.db.scalar(stmt)
        if not invite:
            raise ValueError("INVITE_NOT_FOUND")
        if invite.status != "PENDING":
            # Idempotent response
            conv = await self.get_conversation_by_id(invite.conversation_id)
            return invite, conv

        if action == "DECLINE":
            invite.status = "DECLINED"
            invite.responded_at = now
            await self.db.commit()
            return invite, None

        # ACCEPT
        stmt_lock = (
            select(Conversation)
            .where(Conversation.conversation_id == invite.conversation_id)
            .with_for_update(of=Conversation)
        )
        conv = await self.db.scalar(stmt_lock)
        if not conv:
            raise ValueError("CONVERSATION_NOT_FOUND")

        # Capacity check
        active_count_stmt = select(func.count(ConversationMember.user_id)).where(
            ConversationMember.conversation_id == conv.conversation_id,
            ConversationMember.left_at.is_(None),
        )
        active_count = (await self.db.scalar(active_count_stmt)) or 0
        if active_count >= 50:
            raise ValueError("GROUP_CAP_EXCEEDED")

        invite.status = "ACCEPTED"
        invite.responded_at = now

        # Get latest message ID
        latest_msg_stmt = (
            select(func.max(Message.message_id))
            .where(Message.conversation_id == conv.conversation_id, Message.is_deleted.is_(False))
        )
        latest_msg_id = await self.db.scalar(latest_msg_stmt)

        # Upsert member row
        stmt_mem = select(ConversationMember).where(
            ConversationMember.conversation_id == conv.conversation_id,
            ConversationMember.user_id == user_id,
        )
        mem = await self.db.scalar(stmt_mem)
        if mem:
            mem.left_at = None
            mem.joined_at = now
            mem.role = "MEMBER"
            mem.last_read_message_id = latest_msg_id
        else:
            mem = ConversationMember(
                conversation_id=conv.conversation_id,
                user_id=user_id,
                role="MEMBER",
                joined_at=now,
                last_read_message_id=latest_msg_id,
            )
            self.db.add(mem)

        await self.db.commit()
        return invite, conv

    async def cancel_invite(self, invite_id: int, operator_id: int) -> bool:
        """
        Cancels a pending invite by inviter or group admin/owner.
        """
        stmt = select(ConversationInvite).where(ConversationInvite.invite_id == invite_id)
        inv = await self.db.scalar(stmt)
        if not inv or inv.status != "PENDING":
            return False

        # Verify permission
        if inv.inviter_id != operator_id:
            stmt_role = select(ConversationMember.role).where(
                ConversationMember.conversation_id == inv.conversation_id,
                ConversationMember.user_id == operator_id,
                ConversationMember.left_at.is_(None),
            )
            role = await self.db.scalar(stmt_role)
            if role not in ("OWNER", "ADMIN"):
                raise PermissionError("PERMISSION_DENIED")

        inv.status = "CANCELLED"
        inv.responded_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.db.commit()
        return True

    async def list_group_members(
        self, conversation_id: int, user_id: int
    ) -> List[ConversationMemberResponse]:
        """
        Lists all active members in a group with presence status.
        """
        conv = await self.get_conversation_by_id(conversation_id)
        if not conv or conv.deleted_at is not None:
            raise ValueError("CONVERSATION_NOT_FOUND")

        # Verify user is active member
        stmt_check = select(ConversationMember.role).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
            ConversationMember.left_at.is_(None),
        )
        my_role = await self.db.scalar(stmt_check)
        if not my_role:
            raise PermissionError("NOT_AN_ACTIVE_MEMBER")

        stmt = (
            select(ConversationMember)
            .options(selectinload(ConversationMember.user))
            .where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.left_at.is_(None),
            )
            .order_by(
                case(
                    (ConversationMember.role == "OWNER", 1),
                    (ConversationMember.role == "ADMIN", 2),
                    else_=3,
                ),
                ConversationMember.joined_at.asc(),
            )
        )
        members = (await self.db.scalars(stmt)).all()

        uids = [m.user_id for m in members]
        avail, online_ids = await get_users_presence(uids)

        return [
            ConversationMemberResponse(
                user_id=m.user_id,
                full_name=m.user.full_name if m.user else "Người dùng",
                avatar_url=m.user.avatar_url if m.user else None,
                role=m.role,
                joined_at=m.joined_at,
                is_online=m.user_id in online_ids if avail else None,
                nickname=m.nickname,
            )
            for m in members
        ]

    async def update_member_role(
        self, conversation_id: int, operator_id: int, target_user_id: int, new_role: str
    ) -> bool:
        """
        Promotes a member to ADMIN or demotes to MEMBER (OWNER only).
        """
        stmt_owner = select(ConversationMember.role).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == operator_id,
            ConversationMember.left_at.is_(None),
        )
        my_role = await self.db.scalar(stmt_owner)
        if my_role != "OWNER":
            raise PermissionError("ONLY_OWNER_CAN_MANAGE_ROLES")

        if operator_id == target_user_id:
            raise ValueError("CANNOT_MODIFY_OWN_ROLE")

        stmt_target = select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == target_user_id,
            ConversationMember.left_at.is_(None),
        )
        target = await self.db.scalar(stmt_target)
        if not target:
            raise ValueError("MEMBER_NOT_FOUND")

        target.role = new_role
        await self.db.commit()
        return True

    async def transfer_ownership(
        self, conversation_id: int, current_owner_id: int, new_owner_id: int
    ) -> bool:
        """
        Atomically transfers group ownership (OWNER -> ADMIN/MEMBER, target -> OWNER).
        """
        stmt_owner = select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == current_owner_id,
            ConversationMember.left_at.is_(None),
        )
        current_owner = await self.db.scalar(stmt_owner)
        if not current_owner or current_owner.role != "OWNER":
            raise PermissionError("ONLY_OWNER_CAN_TRANSFER")

        if current_owner_id == new_owner_id:
            return True

        stmt_target = select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == new_owner_id,
            ConversationMember.left_at.is_(None),
        )
        target = await self.db.scalar(stmt_target)
        if not target:
            raise ValueError("TARGET_NOT_ACTIVE_MEMBER")

        current_owner.role = "MEMBER"
        target.role = "OWNER"
        await self.db.commit()
        return True

    async def remove_member(
        self, conversation_id: int, operator_id: int, target_user_id: int
    ) -> bool:
        """
        Removes a member from the group.
        OWNER can remove anyone except self. ADMIN can remove normal MEMBERs only.
        """
        stmt_op = select(ConversationMember.role).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == operator_id,
            ConversationMember.left_at.is_(None),
        )
        op_role = await self.db.scalar(stmt_op)
        if op_role not in ("OWNER", "ADMIN"):
            raise PermissionError("PERMISSION_DENIED")

        if operator_id == target_user_id:
            raise ValueError("USE_LEAVE_GROUP_INSTEAD")

        stmt_target = select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == target_user_id,
            ConversationMember.left_at.is_(None),
        )
        target = await self.db.scalar(stmt_target)
        if not target:
            raise ValueError("MEMBER_NOT_FOUND")

        if op_role == "ADMIN" and target.role in ("OWNER", "ADMIN"):
            raise PermissionError("ADMIN_CANNOT_REMOVE_ADMIN_OR_OWNER")

        target.left_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.db.commit()
        return True

    async def leave_group(self, conversation_id: int, user_id: int) -> bool:
        """
        Leaves a group chat. OWNER must transfer ownership before leaving if other active members exist.
        """
        stmt = select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
            ConversationMember.left_at.is_(None),
        )
        mem = await self.db.scalar(stmt)
        if not mem:
            return False
        if mem.role == "OWNER":
            # Check if other active members exist
            count_stmt = select(func.count(ConversationMember.user_id)).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.left_at.is_(None),
                ConversationMember.user_id != user_id,
            )
            other_active_count = (await self.db.scalar(count_stmt)) or 0
            if other_active_count > 0:
                raise ValueError("OWNER_CANNOT_LEAVE_BEFORE_TRANSFER")
            else:
                raise ValueError("OWNER_ONLY_MEMBER_MUST_DELETE_GROUP")

        mem.left_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.db.commit()
        return True

    async def update_group_metadata(
        self,
        conversation_id: int,
        operator_id: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Conversation:
        """
        Updates group title and/or description (OWNER/ADMIN only).
        """
        stmt_op = select(ConversationMember.role).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == operator_id,
            ConversationMember.left_at.is_(None),
        )
        op_role = await self.db.scalar(stmt_op)
        if op_role not in ("OWNER", "ADMIN"):
            raise PermissionError("PERMISSION_DENIED")

        conv = await self.get_conversation_by_id(conversation_id)
        if not conv or conv.type != "GROUP":
            raise ValueError("INVALID_CONVERSATION")

        if title is not None:
            conv.title = title.strip()
        if description is not None:
            conv.description = description.strip() if description else None

        await self.db.commit()
        return conv

    async def search_users(
        self,
        query: str,
        limit: int = 20,
        exclude_user_id: Optional[int] = None,
        exclude_conversation_id: Optional[int] = None,
    ) -> List[UserSearchResponse]:
        """
        Safe public user search by full_name or user_id.
        Excludes private fields (email, phone, bank, etc.)
        """
        trimmed = query.strip()
        if len(trimmed) < 2:
            return []

        stmt = (
            select(User)
            .where(
                User.status == UserStatus.ACTIVE,
                User.full_name.ilike(f"%{trimmed}%"),
            )
        )

        if exclude_user_id:
            stmt = stmt.where(User.user_id != exclude_user_id)

        if exclude_conversation_id:
            active_mems = select(ConversationMember.user_id).where(
                ConversationMember.conversation_id == exclude_conversation_id,
                ConversationMember.left_at.is_(None),
            )
            stmt = stmt.where(User.user_id.not_in(active_mems))

        stmt = stmt.limit(min(limit, 20))
        users = (await self.db.scalars(stmt)).all()

        return [
            UserSearchResponse(
                user_id=u.user_id,
                full_name=u.full_name,
                avatar_url=u.avatar_url,
            )
            for u in users
        ]

    async def delete_group_conversation(
        self, conversation_id: int, operator_id: int
    ) -> bool:
        """
        Soft-deletes a regular GROUP conversation (OWNER only).
        Sets conversation.deleted_at = now and sets all active members' left_at = now.
        Preserves all historical messages and attachments in database.
        Official support group cannot be deleted.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        stmt_conv = select(Conversation).where(
            Conversation.conversation_id == conversation_id,
            Conversation.deleted_at.is_(None),
        ).with_for_update(of=Conversation)
        conv = await self.db.scalar(stmt_conv)
        if not conv:
            raise ValueError("CONVERSATION_NOT_FOUND")

        if settings.OFFICIAL_SUPPORT_GROUP_ID and conv.conversation_id == settings.OFFICIAL_SUPPORT_GROUP_ID:
            raise PermissionError("CANNOT_DELETE_OFFICIAL_SUPPORT_GROUP")

        if conv.type != "GROUP":
            raise ValueError("ONLY_GROUP_CAN_BE_DELETED")

        stmt_role = select(ConversationMember.role).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == operator_id,
            ConversationMember.left_at.is_(None),
        )
        role = await self.db.scalar(stmt_role)
        if role != "OWNER":
            raise PermissionError("ONLY_OWNER_CAN_DELETE_GROUP")

        conv.deleted_at = now

        # Soft deactivate all active members
        stmt_deact_members = (
            update(ConversationMember)
            .where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.left_at.is_(None),
            )
            .values(left_at=now)
        )
        await self.db.execute(stmt_deact_members)
        await self.db.commit()
        return True

    async def get_shared_attachments(
        self,
        conversation_id: int,
        category: str,
        limit: int = 30,
        cursor: Optional[str] = None,
        joined_at_filter: Optional[datetime] = None,
    ) -> Tuple[List[SharedAttachmentItemResponse], Optional[str], bool]:
        """
        Fetches cursor-paginated shared attachments for a conversation.
        category: 'media' (IMAGE, VIDEO), 'audio' (AUDIO), 'file' (PDF, DOCUMENT).
        Respects joined_at_filter for GROUP conversations.
        """
        stmt = (
            select(MessageAttachment)
            .join(Message, Message.message_id == MessageAttachment.message_id)
            .options(
                selectinload(MessageAttachment.message).selectinload(Message.sender)
            )
            .where(
                Message.conversation_id == conversation_id,
                Message.is_deleted.is_(False),
            )
        )

        cat_upper = category.lower()
        if cat_upper == "media":
            stmt = stmt.where(MessageAttachment.kind.in_(["IMAGE", "VIDEO"]))
        elif cat_upper == "audio":
            stmt = stmt.where(MessageAttachment.kind == "AUDIO")
        elif cat_upper == "file":
            stmt = stmt.where(MessageAttachment.kind.in_(["PDF", "DOCUMENT"]))
        else:
            raise ValueError("INVALID_ATTACHMENT_CATEGORY")

        if joined_at_filter:
            stmt = stmt.where(Message.sent_at >= joined_at_filter)

        if cursor:
            cursor_data = decode_cursor(cursor)
            cursor_dt = datetime.fromisoformat(cursor_data["created_at"])
            cursor_id = int(cursor_data["attachment_id"])
            stmt = stmt.where(
                tuple_(MessageAttachment.created_at, MessageAttachment.attachment_id)
                < (cursor_dt, cursor_id)
            )

        stmt = stmt.order_by(
            MessageAttachment.created_at.desc(),
            MessageAttachment.attachment_id.desc(),
        ).limit(limit + 1)

        att_rows = list((await self.db.scalars(stmt)).all())
        has_more = len(att_rows) > limit
        items = att_rows[:limit]

        next_cursor = None
        if has_more and items:
            last_item = items[-1]
            next_cursor = encode_cursor(
                {
                    "created_at": last_item.created_at.isoformat(),
                    "attachment_id": last_item.attachment_id,
                }
            )

        responses = [
            SharedAttachmentItemResponse(
                attachment_id=att.attachment_id,
                message_id=att.message_id,
                kind=att.kind,
                url=generate_delivery_url(
                    public_id=att.storage_key,
                    resource_type=_map_kind_to_resource_type(att.kind),
                    default_url=att.url,
                ),
                mime_type=att.mime_type,
                original_name=att.original_name,
                size_bytes=att.size_bytes,
                duration_ms=att.duration_ms,
                created_at=att.created_at,
                sender_id=att.message.sender_id if att.message else 0,
                sender_name=att.message.sender.full_name if (att.message and att.message.sender) else None,
                sender_avatar=att.message.sender.avatar_url if (att.message and att.message.sender) else None,
            )
            for att in items
        ]
        return responses, next_cursor, has_more

    async def get_shared_attachments_summary(
        self,
        conversation_id: int,
        joined_at_filter: Optional[datetime] = None,
    ) -> dict:
        """
        Counts shared attachments by category in a single aggregated query.
        """
        stmt = (
            select(
                func.count(
                    case((MessageAttachment.kind.in_(["IMAGE", "VIDEO"]), MessageAttachment.attachment_id))
                ).label("media_count"),
                func.count(
                    case((MessageAttachment.kind == "AUDIO", MessageAttachment.attachment_id))
                ).label("audio_count"),
                func.count(
                    case((MessageAttachment.kind.in_(["PDF", "DOCUMENT"]), MessageAttachment.attachment_id))
                ).label("file_count"),
            )
            .join(Message, Message.message_id == MessageAttachment.message_id)
            .where(
                Message.conversation_id == conversation_id,
                Message.is_deleted.is_(False),
            )
        )
        if joined_at_filter:
            stmt = stmt.where(Message.sent_at >= joined_at_filter)

        row = (await self.db.execute(stmt)).one()
        return {
            "media_count": row.media_count or 0,
            "audio_count": row.audio_count or 0,
            "file_count": row.file_count or 0,
        }

    async def get_invite_candidates(
        self,
        group_id: int,
        inviter_id: int,
        query: Optional[str] = None,
        limit: int = 20,
    ) -> List[InviteCandidateItem]:
        """
        Retrieves eligible invite candidates for group_id based on inviter_id's prior DIRECT contacts.
        Rules:
        - Caller must be an active member of group_id.
        - Target conversation must be GROUP.
        - Candidate must have a canonical DIRECT conversation with inviter_id.
        - That DIRECT conversation must have exchanged messages (last_message_at IS NOT NULL).
        - Exclude candidate == inviter_id.
        - Exclude candidates who are already active members of target group.
        - Exclude candidates who already have a PENDING invite to target group.
        - Exclude inactive/banned users.
        - Ordered by recent direct interaction (Conversation.last_message_at DESC).
        """
        conv, member = await self.get_conversation_with_member(group_id, inviter_id)
        if not conv or not member:
            raise PermissionError("NOT_ACTIVE_MEMBER")
        if conv.type != "GROUP":
            raise ValueError("INVITES_ONLY_FOR_GROUPS")

        other_user_expr = case(
            (Conversation.user_one_id == inviter_id, Conversation.user_two_id),
            else_=Conversation.user_one_id,
        )

        active_members_subq = select(ConversationMember.user_id).where(
            ConversationMember.conversation_id == group_id,
            ConversationMember.left_at.is_(None),
        )

        pending_invites_subq = select(ConversationInvite.invitee_id).where(
            ConversationInvite.conversation_id == group_id,
            ConversationInvite.status == "PENDING",
        )

        stmt = (
            select(
                User.user_id,
                User.full_name,
                User.avatar_url,
                Conversation.last_message_at,
            )
            .join(
                Conversation,
                and_(
                    Conversation.type == "DIRECT",
                    Conversation.deleted_at.is_(None),
                    Conversation.last_message_at.isnot(None),
                    or_(
                        Conversation.user_one_id == inviter_id,
                        Conversation.user_two_id == inviter_id,
                    ),
                    other_user_expr == User.user_id,
                ),
            )
            .where(
                User.user_id != inviter_id,
                User.status == UserStatus.ACTIVE,
                User.user_id.notin_(active_members_subq),
                User.user_id.notin_(pending_invites_subq),
            )
        )

        if query and query.strip():
            stmt = stmt.where(User.full_name.ilike(f"%{query.strip()}%"))

        stmt = stmt.order_by(Conversation.last_message_at.desc()).limit(limit)

        rows = (await self.db.execute(stmt)).all()
        return [
            InviteCandidateItem(
                user_id=row.user_id,
                full_name=row.full_name,
                avatar_url=row.avatar_url,
                last_interaction_at=row.last_message_at,
            )
            for row in rows
        ]

    async def get_group_for_update(self, conversation_id: int) -> Optional[Conversation]:
        """Locks and returns conversation row for atomic group update."""
        stmt = (
            select(Conversation)
            .where(
                Conversation.conversation_id == conversation_id,
                Conversation.deleted_at.is_(None),
            )
            .with_for_update(of=Conversation)
        )
        return await self.db.scalar(stmt)

    async def get_member_for_update(self, conversation_id: int, user_id: int) -> Optional[ConversationMember]:
        """Locks and returns conversation_member row."""
        stmt = (
            select(ConversationMember)
            .where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == user_id,
            )
            .with_for_update(of=ConversationMember)
        )
        return await self.db.scalar(stmt)

    async def get_active_owner(self, conversation_id: int) -> Optional[ConversationMember]:
        """Returns the active OWNER member of a conversation."""
        stmt = select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.role == "OWNER",
            ConversationMember.left_at.is_(None),
        )
        return await self.db.scalar(stmt)

    async def get_invite_for_update(self, invite_id: int) -> Optional[ConversationInvite]:
        """Locks and returns conversation_invite row with inviter and invitee eager-loaded."""
        stmt = (
            select(ConversationInvite)
            .options(
                selectinload(ConversationInvite.inviter),
                selectinload(ConversationInvite.invitee),
            )
            .where(ConversationInvite.invite_id == invite_id)
            .with_for_update(of=ConversationInvite)
        )
        return await self.db.scalar(stmt)

    async def count_active_members(self, conversation_id: int) -> int:
        """Counts active members in a conversation."""
        stmt = select(func.count(ConversationMember.user_id)).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.left_at.is_(None),
        )
        return (await self.db.scalar(stmt)) or 0

    async def get_latest_message_id(self, conversation_id: int) -> Optional[int]:
        """Returns max message_id in conversation."""
        stmt = select(func.max(Message.message_id)).where(
            Message.conversation_id == conversation_id,
            Message.is_deleted.is_(False),
        )
        return await self.db.scalar(stmt)

    async def upsert_active_member(
        self,
        conversation_id: int,
        user_id: int,
        role: str = "MEMBER",
        latest_msg_id: Optional[int] = None,
    ) -> ConversationMember:
        """Upserts an active member row (creates or reactivates)."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        stmt_mem = select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
        )
        mem = await self.db.scalar(stmt_mem)
        if mem:
            mem.left_at = None
            mem.joined_at = now
            mem.role = role
            if latest_msg_id is not None:
                mem.last_read_message_id = latest_msg_id
        else:
            mem = ConversationMember(
                conversation_id=conversation_id,
                user_id=user_id,
                role=role,
                joined_at=now,
                last_read_message_id=latest_msg_id,
            )
            self.db.add(mem)
        await self.db.flush()
        return mem

    async def create_system_message(
        self,
        conversation_id: int,
        sender_id: int,
        content: str,
    ) -> Message:
        """
        Creates and persists a lifecycle SYSTEM message.
        CRITICAL: Never touches conversation.last_message_at or unread pointers.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        msg = Message(
            conversation_id=conversation_id,
            sender_id=sender_id,
            type="SYSTEM",
            content=content,
            sent_at=now,
            is_deleted=False,
        )
        self.db.add(msg)
        await self.db.flush()
        return msg

    async def list_pending_approvals(self, conversation_id: int) -> List[ConversationInvite]:
        """
        Fetches all PENDING_APPROVAL invites for a conversation with eager loaded users.
        Avoids N+1 query.
        """
        stmt = (
            select(ConversationInvite)
            .options(
                selectinload(ConversationInvite.invitee),
                selectinload(ConversationInvite.inviter),
            )
            .where(
                ConversationInvite.conversation_id == conversation_id,
                ConversationInvite.status == "PENDING_APPROVAL",
            )
            .order_by(ConversationInvite.created_at.asc())
        )
        return (await self.db.scalars(stmt)).all()

    async def get_attachment_by_id_and_conversation(
        self,
        conversation_id: int,
        attachment_id: int,
    ) -> Optional[MessageAttachment]:
        """
        Fetches an attachment by ID ensuring it belongs to the given conversation
        and its parent message is not soft-deleted.
        """
        stmt = (
            select(MessageAttachment)
            .join(Message, Message.message_id == MessageAttachment.message_id)
            .where(
                Message.conversation_id == conversation_id,
                MessageAttachment.attachment_id == attachment_id,
                Message.is_deleted.is_(False),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_message_by_id_and_conversation(
        self,
        conversation_id: int,
        message_id: int,
    ) -> Optional[Message]:
        """
        Fetches a message by ID ensuring it belongs to the given conversation
        and is not soft-deleted.
        """
        stmt = select(Message).where(
            Message.conversation_id == conversation_id,
            Message.message_id == message_id,
            Message.is_deleted.is_(False),
        )
        return await self.db.scalar(stmt)

    async def get_message_for_recall(
        self,
        conversation_id: int,
        message_id: int,
    ) -> Optional[Message]:
        """
        Loads a message by ID and conversation with row lock FOR UPDATE and attachments loaded.
        Does NOT filter is_deleted so caller can handle idempotency.
        """
        stmt = (
            select(Message)
            .options(
                lazyload(Message.product),
                selectinload(Message.attachments),
                selectinload(Message.sender),
            )
            .where(
                Message.conversation_id == conversation_id,
                Message.message_id == message_id,
            )
            .with_for_update(of=Message)
        )
        return await self.db.scalar(stmt)

    async def recall_message_in_db(
        self,
        message: Message,
        cleanup_jobs: List[Tuple[str, str]],
    ) -> None:
        """
        Durable transactional message recall:
        1. Inserts pending media cleanup jobs for any attachments (with ON CONFLICT DO NOTHING).
        2. Sets message.is_deleted = True and message.content = None.
        3. Commits the transaction.
        """
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        initial_retry_at = now_utc + timedelta(seconds=60)
        for storage_key, resource_type in cleanup_jobs:
            stmt = (
                insert(MediaCleanupJob)
                .values(
                    storage_key=storage_key,
                    resource_type=resource_type,
                    attempt_count=0,
                    next_retry_at=initial_retry_at,
                    created_at=now_utc,
                    updated_at=now_utc,
                )
                .on_conflict_do_nothing(
                    constraint="uq_media_cleanup_jobs_key_type"
                )
            )
            await self.db.execute(stmt)

        message.is_deleted = True
        message.content = None
        await self.db.commit()

    async def delete_media_cleanup_job(
        self,
        storage_key: str,
        resource_type: str,
    ) -> None:
        """Removes a completed media cleanup job upon immediate post-commit delete success."""
        stmt = delete(MediaCleanupJob).where(
            MediaCleanupJob.storage_key == storage_key,
            MediaCleanupJob.resource_type == resource_type,
        )
        await self.db.execute(stmt)
        await self.db.commit()

    async def get_active_group_member(
        self, conversation_id: int, user_id: int
    ) -> Optional[ConversationMember]:
        """Fetches active member row for a group (left_at IS NULL)."""
        stmt = select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
            ConversationMember.left_at.is_(None),
        )
        return await self.db.scalar(stmt)

    async def set_reaction(
        self, message_id: int, user_id: int, reaction_key: str
    ) -> None:
        """
        Sets or switches authenticated user's reaction on a message atomically.
        Uses PostgreSQL ON CONFLICT (message_id, user_id) DO UPDATE.
        """
        stmt = (
            insert(MessageReaction)
            .values(
                message_id=message_id,
                user_id=user_id,
                reaction_key=reaction_key,
            )
            .on_conflict_do_update(
                constraint="uq_message_reactions_message_user",
                set_={"reaction_key": reaction_key},
            )
        )
        await self.db.execute(stmt)

    async def remove_reaction(self, message_id: int, user_id: int) -> bool:
        """
        Removes authenticated user's reaction on a message if present.
        Returns True if a row was deleted, False otherwise. Idempotent.
        """
        stmt = delete(MessageReaction).where(
            MessageReaction.message_id == message_id,
            MessageReaction.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        return (result.rowcount or 0) > 0

    async def batch_get_reaction_summaries(
        self, message_ids: List[int], current_user_id: Optional[int] = None
    ) -> Tuple[Dict[int, List[ReactionAggregateResponse]], Dict[int, ReactionKey]]:
        """
        Batch fetches reaction aggregates and current user's reaction for a list of message IDs.
        Guarantees O(1) bounded database round-trips for the entire message page (No N+1).
        """
        if not message_ids:
            return {}, {}

        # 1. Bounded batch aggregate counts
        agg_stmt = (
            select(
                MessageReaction.message_id,
                MessageReaction.reaction_key,
                func.count(MessageReaction.reaction_id).label("cnt"),
            )
            .where(MessageReaction.message_id.in_(message_ids))
            .group_by(MessageReaction.message_id, MessageReaction.reaction_key)
            .order_by(
                MessageReaction.message_id,
                func.count(MessageReaction.reaction_id).desc(),
                MessageReaction.reaction_key.asc(),
            )
        )
        agg_rows = (await self.db.execute(agg_stmt)).all()

        reactions_map: Dict[int, List[ReactionAggregateResponse]] = {}
        for mid, rkey, cnt in agg_rows:
            if mid not in reactions_map:
                reactions_map[mid] = []
            reactions_map[mid].append(
                ReactionAggregateResponse(
                    reaction_key=ReactionKey(rkey),
                    count=cnt,
                )
            )

        # 2. Bounded batch my_reaction query
        my_reactions_map: Dict[int, ReactionKey] = {}
        if current_user_id:
            my_stmt = select(
                MessageReaction.message_id, MessageReaction.reaction_key
            ).where(
                MessageReaction.message_id.in_(message_ids),
                MessageReaction.user_id == current_user_id,
            )
            my_rows = (await self.db.execute(my_stmt)).all()
            for mid, rkey in my_rows:
                my_reactions_map[mid] = ReactionKey(rkey)

        return reactions_map, my_reactions_map

    async def get_reaction_summary(
        self, message_id: int, current_user_id: Optional[int] = None
    ) -> MessageReactionSummaryResponse:
        """
        Retrieves aggregate counts and current user's reaction for a single message.
        """
        reactions_map, my_reactions_map = await self.batch_get_reaction_summaries(
            [message_id], current_user_id
        )
        return MessageReactionSummaryResponse(
            message_id=message_id,
            reactions=reactions_map.get(message_id, []),
            my_reaction=my_reactions_map.get(message_id, None),
        )



