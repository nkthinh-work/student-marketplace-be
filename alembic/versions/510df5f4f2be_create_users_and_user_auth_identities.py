"""create_users_and_user_auth_identities

Revision ID: 510df5f4f2be
Revises: 
Create Date: 2026-08-25 09:50:58.774924

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '510df5f4f2be'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum type safely using DO block
    op.execute(sa.text("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_status') THEN
                CREATE TYPE user_status AS ENUM ('ACTIVE', 'BANNED', 'INACTIVE');
            END IF;
        END $$;
    """))

    user_status_enum = postgresql.ENUM('ACTIVE', 'BANNED', 'INACTIVE', name='user_status', create_type=False)

    # Create users table
    op.create_table(
        'users',
        sa.Column('user_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('email', sa.String(length=150), nullable=False),
        sa.Column('full_name', sa.String(length=100), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('avatar_url', sa.String(length=500), nullable=True),
        sa.Column('bio', sa.String(length=500), nullable=True),
        sa.Column('default_meetup_area', sa.String(length=255), nullable=True),
        sa.Column('role', sa.String(length=10), server_default='STUDENT', nullable=False),
        sa.Column('status', user_status_enum, server_default='ACTIVE', nullable=False),
        sa.Column('last_active_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("role IN ('STUDENT', 'ADMIN')", name='chk_users_role'),
        sa.PrimaryKeyConstraint('user_id', name='pk_users'),
        sa.UniqueConstraint('email', name='ux_users_email'),
    )

    # Create user_auth_identities table
    op.create_table(
        'user_auth_identities',
        sa.Column('user_auth_identity_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('provider', sa.String(length=30), server_default='FIREBASE', nullable=False),
        sa.Column('provider_uid', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("provider IN ('FIREBASE')", name='chk_user_auth_identities_provider'),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], name='fk_user_auth_identities_users', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_auth_identity_id', name='pk_user_auth_identities'),
        sa.UniqueConstraint('provider', 'provider_uid', name='ux_user_auth_identities_provider_uid'),
        sa.UniqueConstraint('user_id', name='ux_user_auth_identities_user_id'),
    )


def downgrade() -> None:
    op.drop_table('user_auth_identities')
    op.drop_table('users')
    op.execute(sa.text("DROP TYPE IF EXISTS user_status"))
