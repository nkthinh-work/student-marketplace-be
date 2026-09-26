"""add_product_pre_publication_approval

Revision ID: 4414f46b5404
Revises: dc949589783d
Create Date: 2026-09-26 03:38:13.447218

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4414f46b5404'
down_revision: Union[str, None] = 'dc949589783d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Thêm các cột phục vụ duyệt tin vào bảng products
    op.add_column('products', sa.Column('approval_status', sa.String(length=12), nullable=True))
    op.add_column('products', sa.Column('submitted_for_review_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('products', sa.Column('reviewed_by', sa.BigInteger(), nullable=True))
    op.add_column('products', sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('products', sa.Column('review_note', sa.String(length=500), nullable=True))

    # 2. Di chuyển toàn bộ sản phẩm hiện hữu sang APPROVED để bảo toàn dữ liệu lịch sử
    op.execute(sa.text("UPDATE products SET approval_status = 'APPROVED' WHERE approval_status IS NULL;"))

    # 3. Ràng buộc NOT NULL và đặt giá trị mặc định cho bản ghi mới là DRAFT
    op.alter_column('products', 'approval_status', nullable=False, server_default='DRAFT')

    # 4. Thêm check constraint cho approval_status
    op.create_check_constraint(
        'chk_products_approval_status',
        'products',
        "approval_status IN ('DRAFT', 'PENDING', 'APPROVED', 'REJECTED')"
    )

    # 5. Thêm khóa ngoại cho reviewed_by trỏ tới users.user_id
    op.create_foreign_key(
        'fk_products_reviewed_by_users',
        'products',
        'users',
        ['reviewed_by'],
        ['user_id'],
        ondelete='SET NULL'
    )

    # 6. Tạo partial index tối ưu hàng đợi duyệt tin Admin
    op.create_index(
        'ix_products_approval_queue',
        'products',
        ['submitted_for_review_at', 'product_id'],
        postgresql_where=sa.text("approval_status = 'PENDING' AND is_deleted = FALSE")
    )

    # 7. Mở rộng notifications.ref_type lên VARCHAR(32) để hỗ trợ ADMIN_PRODUCT_APPROVAL
    op.alter_column(
        'notifications',
        'ref_type',
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        existing_nullable=True
    )


def downgrade() -> None:
    # 1. Khôi phục notifications.ref_type về VARCHAR(20)
    op.alter_column(
        'notifications',
        'ref_type',
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        existing_nullable=True
    )

    # 2. Xóa partial index hàng đợi duyệt tin
    op.drop_index('ix_products_approval_queue', table_name='products')

    # 3. Xóa khóa ngoại và check constraint
    op.drop_constraint('fk_products_reviewed_by_users', 'products', type_='foreignkey')
    op.drop_constraint('chk_products_approval_status', 'products', type_='check')

    # 4. Xóa các cột duyệt tin khỏi bảng products
    op.drop_column('products', 'review_note')
    op.drop_column('products', 'reviewed_at')
    op.drop_column('products', 'reviewed_by')
    op.drop_column('products', 'submitted_for_review_at')
    op.drop_column('products', 'approval_status')
