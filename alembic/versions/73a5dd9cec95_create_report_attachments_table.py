"""create_report_attachments_table

Revision ID: 73a5dd9cec95
Revises: dee714fefa43
Create Date: 2026-09-17 10:35:11.750129

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '73a5dd9cec95'
down_revision: Union[str, None] = 'dee714fefa43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'report_attachments',
        sa.Column('attachment_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('report_id', sa.BigInteger(), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('storage_key', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('original_name', sa.String(length=255), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['report_id'], ['reports.report_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('attachment_id'),
    )
    op.create_index(
        'ix_report_attachments_report_id',
        'report_attachments',
        ['report_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_report_attachments_report_id', table_name='report_attachments')
    op.drop_table('report_attachments')
