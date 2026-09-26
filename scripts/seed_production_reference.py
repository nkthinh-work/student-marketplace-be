"""
PRODUCTION REFERENCE SEED SCRIPT — Student Marketplace C2C

Idempotent bootstrap of required system reference data for production database.
DO NOT SEED FAKE DATA (users, products, orders, auctions, messages, etc.).
Safe to execute repeatedly.

Usage:
    python scripts/seed_production_reference.py
"""

import asyncio
import sys
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Add project root to path
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal, engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed")

# 10 Canonical Product Categories
CANONICAL_CATEGORIES = [
    {"name": "Giáo trình & Sách", "slug": "giao-trinh-sach"},
    {"name": "Thiết bị điện tử khác", "slug": "thiet-bi-dien-tu-khac"},
    {"name": "Máy tính & Phụ kiện", "slug": "may-tinh-phu-kien"},
    {"name": "Điện thoại & Phụ kiện", "slug": "dien-thoai-phu-kien"},
    {"name": "Nội thất & Đồ phòng trọ", "slug": "noi-that-do-phong-tro"},
    {"name": "Xe đạp & Xe máy", "slug": "xe-dap-xe-may"},
    {"name": "Thời trang & Phụ kiện", "slug": "thoi-trang-phu-kien"},
    {"name": "Đồ gia dụng", "slug": "do-gia-dung"},
    {"name": "Thể thao & Giải trí", "slug": "the-thao-giai-tri"},
    {"name": "Khác", "slug": "khac"},
]


async def seed_categories(session: AsyncSession) -> tuple[int, int]:
    """
    Idempotently seeds canonical categories using slug as candidate key.
    Returns (inserted_count, existing_count).
    """
    inserted = 0
    existing = 0

    for cat in CANONICAL_CATEGORIES:
        result = await session.execute(
            text("SELECT category_id, name, is_deleted FROM categories WHERE slug = :slug"),
            {"slug": cat["slug"]},
        )
        row = result.fetchone()

        if row:
            existing += 1
            if row.is_deleted or row.name != cat["name"]:
                await session.execute(
                    text("UPDATE categories SET name = :name, is_deleted = FALSE WHERE category_id = :cid"),
                    {"name": cat["name"], "cid": row.category_id},
                )
                logger.info(f"Updated category: {cat['slug']} -> {cat['name']}")
        else:
            await session.execute(
                text("INSERT INTO categories (name, slug, is_deleted) VALUES (:name, :slug, FALSE)"),
                {"name": cat["name"], "slug": cat["slug"]},
            )
            inserted += 1
            logger.info(f"Inserted new canonical category: {cat['name']} ({cat['slug']})")

    await session.commit()
    return inserted, existing


async def async_main() -> int:
    logger.info("Starting production reference data seed...")
    try:
        async with SessionLocal() as session:
            inserted, existing = await seed_categories(session)
            logger.info(
                f"Categories seeded successfully: {inserted} inserted, {existing} already present."
            )

        logger.info("Production reference data seed completed successfully (0 errors).")
        return 0
    except Exception as e:
        logger.error(f"Production seed failed: {e}", exc_info=True)
        return 1
    finally:
        await engine.dispose()


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
