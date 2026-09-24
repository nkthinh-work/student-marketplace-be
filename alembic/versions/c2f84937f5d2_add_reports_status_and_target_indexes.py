"""add_reports_status_and_target_indexes

Revision ID: c2f84937f5d2
Revises: eeb83ca4d13e
Create Date: 2026-09-24 09:17:34.565224

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2f84937f5d2'
down_revision: Union[str, None] = 'eeb83ca4d13e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_reports_status_created_desc',
        'reports',
        ['status', sa.text('created_at DESC'), sa.text('report_id DESC')],
    )
    op.create_index(
        'ix_reports_reporter_target',
        'reports',
        ['reporter_id', 'target_type', 'target_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_reports_reporter_target', table_name='reports')
    op.drop_index('ix_reports_status_created_desc', table_name='reports')

