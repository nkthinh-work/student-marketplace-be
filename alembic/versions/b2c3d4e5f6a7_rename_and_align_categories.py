"""rename and align categories

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-01 15:38:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 'Đồ điện tử' -> 'Thiết bị điện tử khác'
    op.execute(
        sa.text(
            "UPDATE categories SET name = 'Thiết bị điện tử khác', slug = 'thiet-bi-dien-tu-khac' "
            "WHERE slug IN ('do-dien-tu', 'thiet-bi-dien-tu') OR name = 'Đồ điện tử'"
        )
    )

    # 2. 'Đồ phòng trọ / KTX' -> 'Nội thất & Đồ phòng trọ'
    op.execute(
        sa.text(
            "UPDATE categories SET name = 'Nội thất & Đồ phòng trọ', slug = 'noi-that-do-phong-tro' "
            "WHERE slug IN ('do-phong-tro-ktx', 'phong-tro-ktx') OR name IN ('Đồ phòng trọ / KTX', 'Phòng trọ / KTX')"
        )
    )

    # 3. 'Xe đạp / Xe máy' -> 'Xe đạp & Xe máy'
    op.execute(
        sa.text(
            "UPDATE categories SET name = 'Xe đạp & Xe máy', slug = 'xe-dap-xe-may' "
            "WHERE slug = 'xe-dap-xe-may' OR name = 'Xe đạp / Xe máy'"
        )
    )

    # 4. 'Thời trang' -> 'Thời trang & Phụ kiện'
    op.execute(
        sa.text(
            "UPDATE categories SET name = 'Thời trang & Phụ kiện', slug = 'thoi-trang-phu-kien' "
            "WHERE slug = 'thoi-trang' OR name = 'Thời trang'"
        )
    )


def downgrade() -> None:
    # Revert in reverse order
    op.execute(
        sa.text(
            "UPDATE categories SET name = 'Thời trang', slug = 'thoi-trang' "
            "WHERE slug = 'thoi-trang-phu-kien' OR name = 'Thời trang & Phụ kiện'"
        )
    )

    op.execute(
        sa.text(
            "UPDATE categories SET name = 'Xe đạp / Xe máy', slug = 'xe-dap-xe-may' "
            "WHERE slug = 'xe-dap-xe-may' AND name = 'Xe đạp & Xe máy'"
        )
    )

    op.execute(
        sa.text(
            "UPDATE categories SET name = 'Đồ phòng trọ / KTX', slug = 'do-phong-tro-ktx' "
            "WHERE slug = 'noi-that-do-phong-tro' OR name = 'Nội thất & Đồ phòng trọ'"
        )
    )

    op.execute(
        sa.text(
            "UPDATE categories SET name = 'Đồ điện tử', slug = 'do-dien-tu' "
            "WHERE slug = 'thiet-bi-dien-tu-khac' OR name = 'Thiết bị điện tử khác'"
        )
    )
