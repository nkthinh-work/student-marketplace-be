from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class Conversation(Base):
    """
    Conversations supporting DIRECT (1-to-1) and GROUP.
    Authorization is derived from conversation_members.
    """
    __tablename__ = "conversations"

    conversation_id = Column(
        BigInteger,
        Identity(always=False, start=1),
        primary_key=True,
    )
    type = Column(
        String(12),
        server_default="DIRECT",
        nullable=False,
    )
    title = Column(
        String(80),
        nullable=True,
    )
    description = Column(
        String(300),
        nullable=True,
    )
    avatar_url = Column(
        Text,
        nullable=True,
    )
    direct_pair_key = Column(
        String(64),
        nullable=True,
    )
    user_one_id = Column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=True,
    )
    user_two_id = Column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=True,
    )
    last_message_at = Column(
        DateTime,
        nullable=True,
    )
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )
    deleted_at = Column(
        DateTime,
        nullable=True,
        index=True,
    )
    requires_approval = Column(
        Boolean,
        server_default=text("false"),
        nullable=False,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    # Relationships
    members = relationship(
        "ConversationMember",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )
    invites = relationship(
        "ConversationInvite",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )
    user_one = relationship("User", foreign_keys=[user_one_id], lazy="joined")
    user_two = relationship("User", foreign_keys=[user_two_id], lazy="joined")
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="desc(Message.sent_at), desc(Message.message_id)",
    )

    __table_args__ = (
        CheckConstraint(
            "type IN ('DIRECT', 'GROUP')",
            name="chk_conversations_type",
        ),
        UniqueConstraint(
            "direct_pair_key",
            name="uq_conversations_direct_pair_key",
        ),
        Index(
            "ix_conversations_user_one_last_msg",
            "user_one_id",
            text("last_message_at DESC"),
            text("conversation_id DESC"),
        ),
        Index(
            "ix_conversations_user_two_last_msg",
            "user_two_id",
            text("last_message_at DESC"),
            text("conversation_id DESC"),
        ),
    )


class ConversationMember(Base):
    """
    Relational membership entity for participants in conversations.
    Supports roles: OWNER, ADMIN, MEMBER.
    Tracks read pointer (last_read_message_id) and join/leave state.
    """
    __tablename__ = "conversation_members"

    conversation_id = Column(
        BigInteger,
        ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    role = Column(
        String(10),
        server_default="MEMBER",
        nullable=False,
    )
    joined_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )
    left_at = Column(
        DateTime,
        nullable=True,
    )
    last_read_message_id = Column(
        BigInteger,
        ForeignKey("messages.message_id", ondelete="SET NULL"),
        nullable=True,
    )
    nickname = Column(
        String(40),
        nullable=True,
    )

    # Relationships
    conversation = relationship("Conversation", back_populates="members")
    user = relationship("User", foreign_keys=[user_id], lazy="joined")
    last_read_message = relationship("Message", foreign_keys=[last_read_message_id], lazy="select")

    __table_args__ = (
        CheckConstraint(
            "role IN ('OWNER', 'ADMIN', 'MEMBER')",
            name="chk_conversation_members_role",
        ),
        Index(
            "ix_conversation_members_user_active",
            "user_id",
            "left_at",
        ),
        Index(
            "ix_conversation_members_conversation_id",
            "conversation_id",
        ),
    )


class ConversationInvite(Base):
    """
    Relational invite entity for inviting users to private GROUP conversations.
    """
    __tablename__ = "conversation_invites"

    invite_id = Column(
        BigInteger,
        Identity(always=False, start=1),
        primary_key=True,
    )
    conversation_id = Column(
        BigInteger,
        ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
    )
    inviter_id = Column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    invitee_id = Column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(
        String(20),
        server_default="PENDING",
        nullable=False,
    )
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )
    responded_at = Column(
        DateTime,
        nullable=True,
    )

    # Relationships
    conversation = relationship("Conversation", back_populates="invites")
    inviter = relationship("User", foreign_keys=[inviter_id], lazy="joined")
    invitee = relationship("User", foreign_keys=[invitee_id], lazy="joined")

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'PENDING_APPROVAL', 'ACCEPTED', 'DECLINED', 'CANCELLED')",
            name="chk_conversation_invites_status",
        ),
        Index(
            "ux_conversation_invites_pending",
            "conversation_id",
            "invitee_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'PENDING_APPROVAL')"),
        ),
        Index(
            "ix_conversation_invites_invitee_status",
            "invitee_id",
            "status",
        ),
    )


class Message(Base):
    """
    Individual text, media, or contextual message in a conversation.
    """
    __tablename__ = "messages"

    message_id = Column(
        BigInteger,
        Identity(always=False, start=1),
        primary_key=True,
    )
    conversation_id = Column(
        BigInteger,
        ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
    )
    sender_id = Column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    type = Column(
        String(12),
        server_default="TEXT",
        nullable=False,
    )
    content = Column(
        Text,
        nullable=True,
    )
    product_id = Column(
        BigInteger,
        ForeignKey("products.product_id", ondelete="SET NULL"),
        nullable=True,
    )
    order_id = Column(
        BigInteger,
        ForeignKey("orders.order_id", ondelete="SET NULL"),
        nullable=True,
    )
    is_deleted = Column(
        Boolean,
        server_default=text("false"),
        nullable=False,
    )
    sent_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )
    read_at = Column(
        DateTime,
        nullable=True,
    )
    reply_to_message_id = Column(
        BigInteger,
        ForeignKey("messages.message_id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
    sender = relationship("User", foreign_keys=[sender_id], lazy="joined")
    product = relationship("Product", foreign_keys=[product_id], lazy="joined")
    reply_to = relationship(
        "Message",
        remote_side=[message_id],
        foreign_keys=[reply_to_message_id],
    )
    attachments = relationship(
        "MessageAttachment",
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="MessageAttachment.attachment_id.asc()",
    )
    mentions = relationship(
        "MessageMention",
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="MessageMention.start_offset.asc()",
    )
    reactions = relationship(
        "MessageReaction",
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="MessageReaction.reaction_id.asc()",
    )

    __table_args__ = (
        CheckConstraint(
            "type IN ('TEXT', 'IMAGE', 'FILE', 'PRODUCT_CARD', 'ORDER_CARD', 'SYSTEM')",
            name="chk_messages_type_valid",
        ),
        Index(
            "ix_messages_conversation_sent_desc",
            "conversation_id",
            text("sent_at DESC"),
            text("message_id DESC"),
        ),
        Index(
            "ix_messages_conversation_sender_read",
            "conversation_id",
            "sender_id",
            "read_at",
        ),
    )


class MessageAttachment(Base):
    """
    Relational attachment metadata for files (IMAGE, VIDEO, PDF, AUDIO, DOCUMENT) attached to messages.
    """
    __tablename__ = "message_attachments"

    attachment_id = Column(
        BigInteger,
        Identity(always=False, start=1),
        primary_key=True,
    )
    message_id = Column(
        BigInteger,
        ForeignKey("messages.message_id", ondelete="CASCADE"),
        nullable=False,
    )
    kind = Column(
        String(10),
        nullable=False,
    )
    url = Column(
        Text,
        nullable=False,
    )
    storage_key = Column(
        String(255),
        nullable=False,
    )
    mime_type = Column(
        String(100),
        nullable=False,
    )
    original_name = Column(
        String(255),
        nullable=False,
    )
    size_bytes = Column(
        BigInteger,
        nullable=False,
    )
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )
    duration_ms = Column(
        BigInteger,
        nullable=True,
    )

    # Relationship
    message = relationship("Message", back_populates="attachments")

    __table_args__ = (
        CheckConstraint(
            "kind IN ('IMAGE', 'VIDEO', 'PDF', 'AUDIO', 'DOCUMENT')",
            name="chk_message_attachments_kind",
        ),
        Index(
            "ix_message_attachments_message_id",
            "message_id",
        ),
    )


class MessageMention(Base):
    """
    Relational mention entity recording structured @mentions in messages.
    Persists stable snapshot of display text and offsets so rendering is deterministic
    even if user display names change in the future.
    """
    __tablename__ = "message_mentions"

    mention_id = Column(
        BigInteger,
        Identity(always=False, start=1),
        primary_key=True,
    )
    message_id = Column(
        BigInteger,
        ForeignKey("messages.message_id", ondelete="CASCADE"),
        nullable=False,
    )
    mentioned_user_id = Column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    display_text = Column(
        String(100),
        nullable=False,
    )
    start_offset = Column(
        Integer,
        nullable=False,
    )
    end_offset = Column(
        Integer,
        nullable=False,
    )
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    message = relationship("Message", back_populates="mentions")
    mentioned_user = relationship("User", foreign_keys=[mentioned_user_id], lazy="joined")

    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "mentioned_user_id",
            name="uq_message_mentions_msg_user",
        ),
        Index(
            "ix_message_mentions_user_id",
            "mentioned_user_id",
        ),
        Index(
            "ix_message_mentions_message_id",
            "message_id",
        ),
    )


class MessageReaction(Base):
    """
    Relational reaction entity recording a single active reaction per (message_id, user_id).
    """
    __tablename__ = "message_reactions"

    reaction_id = Column(
        BigInteger,
        Identity(always=False, start=1),
        primary_key=True,
    )
    message_id = Column(
        BigInteger,
        ForeignKey("messages.message_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    reaction_key = Column(
        String(20),
        nullable=False,
    )
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    message = relationship("Message", back_populates="reactions")
    user = relationship("User", foreign_keys=[user_id], lazy="joined")

    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "user_id",
            name="uq_message_reactions_message_user",
        ),
        CheckConstraint(
            "reaction_key IN ('THICH', 'HAHA', 'WOW', 'CAM_ON', 'CHOT_DEAL', 'UY_TIN', 'DANG_TOI', 'DOI_CHUT', 'QUAN_TAM', 'HET_TIEN', 'HOC_BAI', 'KHA_NGHI')",
            name="chk_message_reactions_key",
        ),
        Index(
            "ix_message_reactions_user_id",
            "user_id",
        ),
    )

