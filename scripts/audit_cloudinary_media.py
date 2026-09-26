"""
CLOUDINARY MEDIA AUDIT & CLEANUP TOOL (DRY-RUN DEFAULT) — Student Marketplace C2C

Compares Cloudinary assets against all media tables in PostgreSQL.
Classifies assets into:
  - REFERENCED (active in DB under dev/prod namespace)
  - LEGACY REFERENCED (active in DB under legacy namespace)
  - ORPHAN CANDIDATE (in student-marketplace namespace but unreferenced in DB)
  - UNKNOWN (unrecognized namespace, never touched)

Handles resource_types: image, video, raw.
SAFETY GUARD: Defaults to DRY-RUN. ZERO assets deleted unless BOTH --execute AND --confirm are passed.

Usage:
    # Safe Dry Run (default):
    python scripts/audit_cloudinary_media.py

    # Targeted resource type dry run:
    python scripts/audit_cloudinary_media.py --resource-type video

    # Explicit Execution (REQUIRES BOTH FLAGS):
    # python scripts/audit_cloudinary_media.py --execute --confirm
"""

import argparse
import asyncio
import re
import sys
import logging
from typing import Any
import cloudinary
import cloudinary.api
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Add project root to path
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.integrations.cloudinary import is_cloudinary_configured, init_cloudinary

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("audit_cloudinary")


def extract_public_id_from_url(url: str | None) -> str | None:
    """
    Extracts Cloudinary public_id (storage_key) from a standard Cloudinary delivery URL.
    Supports /image/upload/, /video/upload/, /raw/upload/ with optional version/transform prefixes.
    """
    if not url or not isinstance(url, str):
        return None

    # URL match pattern for Cloudinary assets
    pattern = r"res\.cloudinary\.com/[^/]+/(?:image|video|raw)/upload/(?:[^/]+/)*(?:v\d+/)?(.+)$"
    match = re.search(pattern, url)
    if match:
        full_path = match.group(1)
        # Strip extension if present (e.g. .jpg, .png, .mp4, .pdf)
        # Note: raw files may keep their extension in public_id
        clean_id = re.sub(r"\.[a-zA-Z0-9]+$", "", full_path)
        return clean_id
    return None


async def collect_db_referenced_keys(session: AsyncSession) -> dict[str, set[str]]:
    """
    Scans all 8 media tables in PostgreSQL and extracts referenced storage keys / public_ids.
    Returns mapping: table_name -> set of referenced keys/public_ids.
    """
    db_references: dict[str, set[str]] = {
        "product_images": set(),
        "message_attachments": set(),
        "report_attachments": set(),
        "community_moments": set(),
        "site_feedback_attachments": set(),
        "tutorials": set(),
        "orders": set(),
        "users": set(),
    }

    # 1. product_images (image_url)
    res = await session.execute(text("SELECT image_url FROM product_images WHERE image_url IS NOT NULL"))
    for row in res.fetchall():
        url = row[0]
        pub_id = extract_public_id_from_url(url)
        if pub_id:
            db_references["product_images"].add(pub_id)
        if url:
            db_references["product_images"].add(url)

    # 2. message_attachments (storage_key, url)
    res = await session.execute(
        text("SELECT storage_key, url FROM message_attachments WHERE storage_key IS NOT NULL OR url IS NOT NULL")
    )
    for row in res.fetchall():
        s_key, f_url = row[0], row[1]
        if s_key:
            db_references["message_attachments"].add(s_key)
        if f_url:
            db_references["message_attachments"].add(f_url)
            pub_id = extract_public_id_from_url(f_url)
            if pub_id:
                db_references["message_attachments"].add(pub_id)

    # 3. report_attachments (storage_key, url)
    res = await session.execute(
        text("SELECT storage_key, url FROM report_attachments WHERE storage_key IS NOT NULL OR url IS NOT NULL")
    )
    for row in res.fetchall():
        s_key, url = row[0], row[1]
        if s_key:
            db_references["report_attachments"].add(s_key)
        if url:
            db_references["report_attachments"].add(url)
            pub_id = extract_public_id_from_url(url)
            if pub_id:
                db_references["report_attachments"].add(pub_id)

    # 4. community_moments (storage_key, image_url)
    res = await session.execute(
        text("SELECT storage_key, image_url FROM community_moments WHERE storage_key IS NOT NULL OR image_url IS NOT NULL")
    )
    for row in res.fetchall():
        s_key, url = row[0], row[1]
        if s_key:
            db_references["community_moments"].add(s_key)
        if url:
            db_references["community_moments"].add(url)
            pub_id = extract_public_id_from_url(url)
            if pub_id:
                db_references["community_moments"].add(pub_id)

    # 5. site_feedback_attachments (storage_key, media_url)
    res = await session.execute(
        text("SELECT storage_key, media_url FROM site_feedback_attachments WHERE storage_key IS NOT NULL OR media_url IS NOT NULL")
    )
    for row in res.fetchall():
        s_key, url = row[0], row[1]
        if s_key:
            db_references["site_feedback_attachments"].add(s_key)
        if url:
            db_references["site_feedback_attachments"].add(url)
            pub_id = extract_public_id_from_url(url)
            if pub_id:
                db_references["site_feedback_attachments"].add(pub_id)

    # 6. tutorials (video_storage_key, video_url)
    res = await session.execute(
        text("SELECT video_storage_key, video_url FROM tutorials WHERE video_storage_key IS NOT NULL OR video_url IS NOT NULL")
    )
    for row in res.fetchall():
        v_key, v_url = row[0], row[1]
        if v_key:
            db_references["tutorials"].add(v_key)
        if v_url:
            db_references["tutorials"].add(v_url)
            pub_id = extract_public_id_from_url(v_url)
            if pub_id:
                db_references["tutorials"].add(pub_id)

    # 7. orders (payment_receipt_url)
    res = await session.execute(text("SELECT payment_receipt_url FROM orders WHERE payment_receipt_url IS NOT NULL"))
    for row in res.fetchall():
        url = row[0]
        if url:
            db_references["orders"].add(url)
            pub_id = extract_public_id_from_url(url)
            if pub_id:
                db_references["orders"].add(pub_id)

    # 8. users (avatar_url)
    res = await session.execute(text("SELECT avatar_url FROM users WHERE avatar_url IS NOT NULL"))
    for row in res.fetchall():
        url = row[0]
        if url and "res.cloudinary.com" in url:
            db_references["users"].add(url)
            pub_id = extract_public_id_from_url(url)
            if pub_id:
                db_references["users"].add(pub_id)

    return db_references


def fetch_cloudinary_assets(resource_type: str, prefix: str = "student-marketplace") -> list[dict[str, Any]]:
    """
    Fetches Cloudinary assets under the given prefix and resource_type using Admin API pagination.
    """
    assets: list[dict[str, Any]] = []
    next_cursor = None

    while True:
        try:
            params = {
                "resource_type": resource_type,
                "type": "upload",
                "prefix": prefix,
                "max_results": 500,
            }
            if next_cursor:
                params["next_cursor"] = next_cursor

            res = cloudinary.api.resources(**params)
            resources = res.get("resources", [])
            assets.extend(resources)

            next_cursor = res.get("next_cursor")
            if not next_cursor:
                break
        except Exception as e:
            logger.warning(f"Error fetching {resource_type} assets with prefix '{prefix}': {e}")
            break

    return assets


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="Audit and clean Cloudinary media assets safely.")
    parser.add_argument(
        "--resource-type",
        choices=["all", "image", "video", "raw"],
        default="all",
        help="Target resource types to inspect (default: all)",
    )
    parser.add_argument(
        "--prefix",
        default="student-marketplace",
        help="Target folder prefix namespace (default: student-marketplace)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="DESTRUCTIVE FLAG: execute deletion of orphan candidates (MUST be paired with --confirm)",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="DESTRUCTIVE CONFIRMATION: confirms deletion of orphan candidates",
    )

    args = parser.parse_args()

    is_dry_run = not (args.execute and args.confirm)

    print("=" * 70)
    print("      STUDENT MARKETPLACE — CLOUDINARY MEDIA AUDIT REPORT")
    print(f"      Mode: {'DRY RUN (NO CHANGES)' if is_dry_run else 'LIVE DESTRUCTION (--execute --confirm)'}")
    print(f"      Target Namespace: {args.prefix}")
    print(f"      Resource Type: {args.resource_type}")
    print("=" * 70)

    if not is_cloudinary_configured():
        logger.error("Cloudinary credentials are not configured in settings. Cannot audit.")
        return 1

    init_cloudinary()

    # Step 1: Collect all database references
    logger.info("Scanning PostgreSQL for all referenced media keys across 8 tables...")
    async with SessionLocal() as session:
        db_references = await collect_db_referenced_keys(session)

    all_db_keys: set[str] = set()
    for tbl, keys in db_references.items():
        all_db_keys.update(keys)
        logger.info(f"  • {tbl:<26}: {len(keys):>4} referenced keys/URLs")

    # Step 2: Fetch Cloudinary assets
    resource_types = ["image", "video", "raw"] if args.resource_type == "all" else [args.resource_type]
    all_cloudinary_assets: list[dict[str, Any]] = []

    for r_type in resource_types:
        logger.info(f"Querying Cloudinary for '{r_type}' assets under prefix '{args.prefix}'...")
        r_assets = fetch_cloudinary_assets(resource_type=r_type, prefix=args.prefix)
        logger.info(f"  Found {len(r_assets)} '{r_type}' assets.")
        all_cloudinary_assets.extend(r_assets)

    # Step 3: Classify assets
    referenced_assets: list[dict[str, Any]] = []
    legacy_referenced_assets: list[dict[str, Any]] = []
    orphan_candidates: list[dict[str, Any]] = []
    unknown_assets: list[dict[str, Any]] = []

    for asset in all_cloudinary_assets:
        pub_id = asset.get("public_id", "")
        secure_url = asset.get("secure_url", "")
        url = asset.get("url", "")

        # Check if asset matches recognized namespace
        if not pub_id.startswith(args.prefix):
            unknown_assets.append(asset)
            continue

        # Check if matches any DB key
        is_ref = (
            pub_id in all_db_keys
            or secure_url in all_db_keys
            or url in all_db_keys
            or any(pub_id in k or (k in pub_id and len(k) > 10) for k in all_db_keys)
        )

        if is_ref:
            if pub_id.startswith(f"{args.prefix}/dev/") or pub_id.startswith(f"{args.prefix}/prod/"):
                referenced_assets.append(asset)
            else:
                legacy_referenced_assets.append(asset)
        else:
            orphan_candidates.append(asset)

    # Step 4: Output summary
    print("\n--- Media Classification Summary ---")
    print(f"  Total Cloudinary Assets Scanned : {len(all_cloudinary_assets):>5}")
    print(f"  • REFERENCED (Active Dev/Prod)   : {len(referenced_assets):>5}")
    print(f"  • LEGACY REFERENCED (Pre-Phase 9): {len(legacy_referenced_assets):>5}")
    print(f"  • ORPHAN CANDIDATES (Unreferenced): {len(orphan_candidates):>5}")
    print(f"  • UNKNOWN (Untouched)            : {len(unknown_assets):>5}")

    if orphan_candidates:
        print("\n--- Orphan Candidate Samples (Top 10) ---")
        for o in orphan_candidates[:10]:
            print(f"  [ORPHAN] {o.get('resource_type')}/{o.get('public_id')}")

    deleted_count = 0
    if not is_dry_run:
        print("\n[CAUTION] EXECUTING DELETION OF ORPHAN CANDIDATES...")
        for o in orphan_candidates:
            pid = o.get("public_id")
            rtype = o.get("resource_type", "image")
            try:
                cloudinary.uploader.destroy(pid, resource_type=rtype)
                deleted_count += 1
                logger.info(f"Deleted orphan: {rtype}/{pid}")
            except Exception as e:
                logger.error(f"Failed to delete {pid}: {e}")
        print(f"  Successfully deleted {deleted_count} orphan assets.")
    else:
        print("\n[DRY RUN ONLY] ZERO assets deleted.")
        print("To safely execute deletion in the future after manual review, run:")
        print("  python scripts/audit_cloudinary_media.py --execute --confirm")

    print("\n" + "=" * 70)
    print(f"  AUDIT COMPLETE: Scanned {len(all_cloudinary_assets)} assets. Deleted: {deleted_count} assets.")
    print("=" * 70)
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
