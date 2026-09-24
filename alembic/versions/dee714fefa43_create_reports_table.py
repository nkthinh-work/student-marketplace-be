"""create_reports_table

Revision ID: dee714fefa43
Revises: ed9d01f5b6cb
Create Date: 2026-09-15 20:28:42.602907

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dee714fefa43'
down_revision: Union[str, None] = 'ed9d01f5b6cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'reports',
        sa.Column('report_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('reporter_id', sa.BigInteger(), nullable=False),
        sa.Column('target_type', sa.String(length=10), nullable=False),
        sa.Column('target_id', sa.BigInteger(), nullable=False),
        sa.Column('reason', sa.String(length=20), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=10), server_default='OPEN', nullable=False),
        sa.Column('handled_by', sa.BigInteger(), nullable=True),
        sa.Column('handled_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "target_type IN ('USER', 'PRODUCT', 'ORDER')",
            name='ck_reports_target_type'
        ),
        sa.CheckConstraint(
            "reason IN ('SCAM', 'FAKE_ITEM', 'SPAM', 'INAPPROPRIATE', 'NO_SHOW', 'OTHER')",
            name='ck_reports_reason'
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'REVIEWING', 'RESOLVED', 'REJECTED')",
            name='ck_reports_status'
        ),
        sa.ForeignKeyConstraint(['reporter_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['handled_by'], ['users.user_id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('report_id')
    )


def downgrade() -> None:
    op.drop_table('reports')
