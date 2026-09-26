"""
ADMIN PROMOTION SCRIPT — Student Marketplace C2C

Safely promotes an existing registered user account to role 'ADMIN'.
Requires explicit email or user_id. Does NOT bypass Firebase authentication
or create backdoors. The target user must have already signed in at least once
via Firebase Authentication to establish their user record.

Usage:
    python scripts/promote_admin.py --email admin@example.com
    python scripts/promote_admin.py --user-id 1
"""

import argparse
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
logger = logging.getLogger("promote_admin")


async def promote_user(session: AsyncSession, email: str | None = None, user_id: int | None = None) -> int:
    if not email and not user_id:
        logger.error("Either --email or --user-id must be provided.")
        return 1

    if email:
        result = await session.execute(
            text("SELECT user_id, email, full_name, role, status FROM users WHERE LOWER(email) = LOWER(:email)"),
            {"email": email.strip()},
        )
    else:
        result = await session.execute(
            text("SELECT user_id, email, full_name, role, status FROM users WHERE user_id = :uid"),
            {"uid": user_id},
        )

    user = result.fetchone()
    if not user:
        identifier = email if email else f"ID {user_id}"
        logger.error(
            f"User '{identifier}' not found in database. "
            "The user must first sign in via Firebase Auth so an internal user record is provisioned."
        )
        return 1

    if user.status != "ACTIVE":
        logger.error(f"Cannot promote user {user.user_id} ({user.email}): Account status is '{user.status}' (must be 'ACTIVE').")
        return 1

    if user.role == "ADMIN":
        logger.info(f"User {user.user_id} ({user.email}) is already an ADMIN. No changes made.")
        return 0

    await session.execute(
        text("UPDATE users SET role = 'ADMIN', updated_at = NOW() WHERE user_id = :uid"),
        {"uid": user.user_id},
    )
    await session.commit()
    logger.info(
        f"SUCCESS: Promoted user {user.user_id} ({user.email}, '{user.full_name}') to role 'ADMIN'."
    )
    return 0


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="Promote a user account to ADMIN role.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--email", type=str, help="Email of the user to promote to ADMIN")
    group.add_argument("--user-id", type=int, help="Internal user_id to promote to ADMIN")

    args = parser.parse_args()

    try:
        async with SessionLocal() as session:
            return await promote_user(session, email=args.email, user_id=args.user_id)
    except Exception as e:
        logger.error(f"Failed to promote admin: {e}", exc_info=True)
        return 1
    finally:
        await engine.dispose()


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
