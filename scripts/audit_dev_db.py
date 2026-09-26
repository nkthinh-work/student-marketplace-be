"""
DEVELOPMENT DATABASE AUDIT SCRIPT (READ-ONLY) — Student Marketplace C2C

Performs a comprehensive read-only audit of the current database state.
Reports table counts for all 32 application tables (+ alembic_version)
and provides detailed breakdowns of development/test data distribution.

Usage:
    python scripts/audit_dev_db.py
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
logger = logging.getLogger("audit_db")

# All 32 Application Tables in canonical order
APPLICATION_TABLES = [
    "users",
    "user_auth_identities",
    "categories",
    "products",
    "product_images",
    "orders",
    "order_items",
    "order_status_history",
    "conversations",
    "messages",
    "message_attachments",
    "reviews",
    "favorites",
    "auctions",
    "auction_bids",
    "notifications",
    "reports",
    "daily_needs",
    "daily_journal_checkins",
    "report_attachments",
    "moderation_actions",
    "user_capability_restrictions",
    "community_moments",
    "site_feedback",
    "site_feedback_attachments",
    "conversation_members",
    "conversation_invites",
    "message_mentions",
    "message_reactions",
    "support_contributions",
    "support_claims",
    "tutorials",
]


async def run_audit(session: AsyncSession) -> None:
    print("=" * 70)
    print("      STUDENT MARKETPLACE — DATABASE AUDIT REPORT (READ-ONLY)")
    print("=" * 70)

    # 1. Check Alembic Version
    res = await session.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
    alembic_row = res.fetchone()
    current_head = alembic_row[0] if alembic_row else "NONE"
    print(f"\nAlembic Current Head Revision: {current_head}")

    # 2. Table row counts
    print("\n--- Application Table Row Counts (32 Application Tables) ---")
    total_rows = 0
    table_counts = {}

    for table in APPLICATION_TABLES:
        try:
            count_res = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = count_res.scalar() or 0
            table_counts[table] = count
            total_rows += count
            print(f"  • {table:<32}: {count:>8} rows")
        except Exception as e:
            print(f"  • {table:<32}: ERROR ({e})")

    print("-" * 52)
    print(f"  Total Persistent Rows Across 32 Tables: {total_rows:>8} rows")

    # 3. Categorized Breakdown
    print("\n--- Detailed Entity Breakdown ---")

    # Users
    u_res = await session.execute(
        text("SELECT role, status, COUNT(*) FROM users GROUP BY role, status ORDER BY role, status")
    )
    print("  [Users]:")
    for r in u_res.fetchall():
        print(f"    - Role: {r[0]:<10} Status: {r[1]:<10} Count: {r[2]}")

    # Products
    p_res = await session.execute(
        text("SELECT status, approval_status, moderation_status, COUNT(*) FROM products GROUP BY status, approval_status, moderation_status ORDER BY status, approval_status")
    )
    print("  [Products]:")
    for r in p_res.fetchall():
        print(f"    - Status: {r[0]:<10} Approval: {r[1]:<10} Moderation: {r[2]:<10} Count: {r[3]}")

    # Orders
    o_res = await session.execute(
        text("SELECT status, payment_status, COUNT(*) FROM orders GROUP BY status, payment_status ORDER BY status")
    )
    print("  [Orders]:")
    for r in o_res.fetchall():
        print(f"    - Status: {r[0]:<12} Payment: {r[1]:<12} Count: {r[2]}")

    # Auctions
    a_res = await session.execute(
        text("SELECT status, COUNT(*) FROM auctions GROUP BY status ORDER BY status")
    )
    print("  [Auctions]:")
    for r in a_res.fetchall():
        print(f"    - Status: {r[0]:<12} Count: {r[1]}")

    # Conversations
    c_res = await session.execute(
        text("SELECT type, COUNT(*) FROM conversations GROUP BY type ORDER BY type")
    )
    print("  [Conversations]:")
    for r in c_res.fetchall():
        print(f"    - Type: {r[0]:<12} Count: {r[1]}")

    # Tutorials
    t_res = await session.execute(
        text("SELECT is_published, COUNT(*) FROM tutorials GROUP BY is_published")
    )
    print("  [Tutorials]:")
    for r in t_res.fetchall():
        print(f"    - Published: {r[0]!s:<10} Count: {r[1]}")

    print("\n" + "=" * 70)
    print("  AUDIT COMPLETE: Database read successfully. ZERO modifications made.")
    print("=" * 70)


async def async_main() -> int:
    try:
        async with SessionLocal() as session:
            await run_audit(session)
        return 0
    except Exception as e:
        logger.error(f"Audit failed: {e}", exc_info=True)
        return 1
    finally:
        await engine.dispose()


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
