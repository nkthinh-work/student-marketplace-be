"""add_support_claims_table

Revision ID: 36b9d7d15f56
Revises: 7c1e506f367d
Create Date: 2026-09-25 11:00:24.512314

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36b9d7d15f56'
down_revision: Union[str, None] = '7c1e506f367d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'support_claims',
        sa.Column('claim_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('supporter_id', sa.BigInteger(), nullable=False),
        sa.Column('claimed_amount_vnd', sa.BigInteger(), nullable=False),
        sa.Column('claimed_transferred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sender_account_name', sa.String(length=100), nullable=True),
        sa.Column('wants_public', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False),
        sa.Column('status', sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column('reviewed_by', sa.BigInteger(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('contribution_id', sa.BigInteger(), nullable=True),
        sa.Column('rejection_reason', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.CheckConstraint('claimed_amount_vnd > 0', name='chk_support_claims_claimed_amount_positive'),
        sa.CheckConstraint("status IN ('PENDING', 'VERIFIED', 'REJECTED')", name='chk_support_claims_status'),
        sa.ForeignKeyConstraint(['supporter_id'], ['users.user_id'], ondelete='RESTRICT', name='fk_support_claims_supporter_id'),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.user_id'], ondelete='SET NULL', name='fk_support_claims_reviewed_by'),
        sa.ForeignKeyConstraint(['contribution_id'], ['support_contributions.contribution_id'], ondelete='SET NULL', name='fk_support_claims_contribution_id'),
        sa.PrimaryKeyConstraint('claim_id', name='pk_support_claims'),
    )
    op.create_index(
        'ix_support_claims_status_created',
        'support_claims',
        ['status', sa.text('created_at DESC'), sa.text('claim_id DESC')],
    )
    op.create_index(
        'ix_support_claims_supporter',
        'support_claims',
        ['supporter_id', sa.text('created_at DESC'), sa.text('claim_id DESC')],
    )
    op.create_index(
        'ix_support_claims_reviewed_by',
        'support_claims',
        ['reviewed_by'],
    )
    op.create_index(
        'ix_support_claims_contribution_id',
        'support_claims',
        ['contribution_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_support_claims_contribution_id', table_name='support_claims')
    op.drop_index('ix_support_claims_reviewed_by', table_name='support_claims')
    op.drop_index('ix_support_claims_supporter', table_name='support_claims')
    op.drop_index('ix_support_claims_status_created', table_name='support_claims')
    op.drop_table('support_claims')

