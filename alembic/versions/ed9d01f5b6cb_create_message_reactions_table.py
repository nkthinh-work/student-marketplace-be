"""create_message_reactions_table

Revision ID: ed9d01f5b6cb
Revises: 84ca2057bbd1
Create Date: 2026-09-15 10:38:14.448390

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ed9d01f5b6cb'
down_revision: Union[str, None] = '84ca2057bbd1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'message_reactions',
        sa.Column('reaction_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('message_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('reaction_key', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['messages.message_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('reaction_id'),
        sa.UniqueConstraint('message_id', 'user_id', name='uq_message_reactions_message_user'),
        sa.CheckConstraint(
            "reaction_key IN ('THICH', 'HAHA', 'WOW', 'CAM_ON', 'CHOT_DEAL', 'UY_TIN', 'DANG_TOI', 'DOI_CHUT', 'QUAN_TAM', 'HET_TIEN', 'HOC_BAI', 'KHA_NGHI')",
            name='chk_message_reactions_key',
        ),
    )
    op.create_index('ix_message_reactions_user_id', 'message_reactions', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_message_reactions_user_id', table_name='message_reactions')
    op.drop_table('message_reactions')
