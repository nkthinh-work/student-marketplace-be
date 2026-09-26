"""create_support_contributions_table

Revision ID: 7c1e506f367d
Revises: c2f84937f5d2
Create Date: 2026-09-24 18:01:48.154258

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c1e506f367d'
down_revision: Union[str, None] = 'c2f84937f5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'support_contributions',
        sa.Column('contribution_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('supporter_id', sa.BigInteger(), nullable=False),
        sa.Column('amount_vnd', sa.BigInteger(), nullable=False),
        sa.Column('is_public', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recorded_by', sa.BigInteger(), nullable=False),
        sa.Column('transaction_ref', sa.String(length=100), nullable=True),
        sa.Column('admin_note', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.CheckConstraint('amount_vnd > 0', name='chk_support_contributions_amount_positive'),
        sa.ForeignKeyConstraint(['supporter_id'], ['users.user_id'], ondelete='RESTRICT', name='fk_support_contributions_supporter_id'),
        sa.ForeignKeyConstraint(['recorded_by'], ['users.user_id'], ondelete='RESTRICT', name='fk_support_contributions_recorded_by'),
        sa.PrimaryKeyConstraint('contribution_id', name='pk_support_contributions'),
    )
    op.create_index(
        'ix_support_contributions_received_desc',
        'support_contributions',
        [sa.text('received_at DESC'), sa.text('contribution_id DESC')],
    )
    op.create_index(
        'ix_support_contributions_public_supporter',
        'support_contributions',
        ['is_public', 'supporter_id'],
    )
    op.create_index(
        'ix_support_contributions_supporter_id',
        'support_contributions',
        ['supporter_id'],
    )
    op.create_index(
        'ix_support_contributions_recorded_by',
        'support_contributions',
        ['recorded_by'],
    )


def downgrade() -> None:
    op.drop_index('ix_support_contributions_recorded_by', table_name='support_contributions')
    op.drop_index('ix_support_contributions_supporter_id', table_name='support_contributions')
    op.drop_index('ix_support_contributions_public_supporter', table_name='support_contributions')
    op.drop_index('ix_support_contributions_received_desc', table_name='support_contributions')
    op.drop_table('support_contributions')

