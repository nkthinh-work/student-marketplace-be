#!/usr/bin/env python3
"""
PostgreSQL Remote Backup Storage & Retention Tool.
Dành riêng cho nền tảng Chợ PTITers (student-marketplace).
Quản lý tải bản sao lưu nguyên tử lên Cloudflare R2 (S3-compatible) và chính sách lưu giữ (retention).
"""

import argparse
import datetime
import os
import pathlib
import re
import sys
import time
from dataclasses import dataclass

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None
    Config = None
    ClientError = Exception

# Đảm bảo console Windows hỗ trợ xuất ký tự UTF-8 an toàn
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

DEFAULT_PREFIX = "backups/"
DEFAULT_REGION = "auto"
TIMESTAMP_REGEX = re.compile(r"_(\d{8}T\d{6}Z)$")
SENSITIVE_PATTERNS = [
    re.compile(r"pass(word)?", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"database_url", re.IGNORECASE),
]


@dataclass(frozen=True)
class RemoteBackupSet:
    """Đại diện cho một cặp bản sao lưu hoàn chỉnh trên bộ lưu trữ đám mây."""
    base_name: str
    dump_key: str
    manifest_key: str
    timestamp_utc: datetime.datetime
    dump_size_bytes: int
    manifest_size_bytes: int


def sanitize_message(msg: str) -> str:
    """Xóa bỏ các chuỗi nhạy cảm có khả năng xuất hiện trong thông điệp lỗi."""
    cleaned = msg
    for env_var in ("PGPASSWORD", "R2_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY", "R2_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"):
        val = os.environ.get(env_var)
        if val and len(val) > 4:
            cleaned = cleaned.replace(val, "[REDACTED]")
    return cleaned


def get_r2_config() -> dict[str, str]:
    """Đọc cấu hình Cloudflare R2 / S3 từ biến môi trường mà không in ra console."""
    bucket_name = os.environ.get("R2_BUCKET_NAME") or os.environ.get("S3_BUCKET_NAME")
    endpoint_url = os.environ.get("R2_ENDPOINT_URL") or os.environ.get("S3_ENDPOINT_URL")
    access_key_id = os.environ.get("R2_ACCESS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY_ID")
    secret_access_key = os.environ.get("R2_SECRET_ACCESS_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY")
    region_name = os.environ.get("R2_REGION") or os.environ.get("AWS_DEFAULT_REGION") or DEFAULT_REGION
    prefix = os.environ.get("R2_PREFIX", DEFAULT_PREFIX)

    if not prefix.endswith("/"):
        prefix += "/"

    missing = []
    if not bucket_name:
        missing.append("R2_BUCKET_NAME / S3_BUCKET_NAME")
    if not endpoint_url:
        missing.append("R2_ENDPOINT_URL / S3_ENDPOINT_URL")
    if not access_key_id:
        missing.append("R2_ACCESS_KEY_ID / AWS_ACCESS_KEY_ID")
    if not secret_access_key:
        missing.append("R2_SECRET_ACCESS_KEY / AWS_SECRET_ACCESS_KEY")

    if missing:
        raise ValueError(f"Thiếu các biến môi trường cấu hình R2/S3 bắt buộc: {', '.join(missing)}")

    return {
        "bucket_name": bucket_name,
        "endpoint_url": endpoint_url,
        "access_key_id": access_key_id,
        "secret_access_key": secret_access_key,
        "region_name": region_name,
        "prefix": prefix,
    }


def create_s3_client(conf: dict[str, str]):
    """Khởi tạo boto3 S3 client với cấu hình an toàn."""
    if boto3 is None:
        raise RuntimeError("Thư viện 'boto3' chưa được cài đặt. Vui lòng cài đặt boto3.")

    client_config = Config(
        signature_version="s3v4",
        retries={"max_attempts": 3, "mode": "standard"},
    )
    return boto3.client(
        "s3",
        endpoint_url=conf["endpoint_url"],
        aws_access_key_id=conf["access_key_id"],
        aws_secret_access_key=conf["secret_access_key"],
        region_name=conf["region_name"],
        config=client_config,
    )


def parse_timestamp_from_base_name(base_name: str) -> datetime.datetime | None:
    """Phân tích thời gian UTC từ tên tệp cơ sở (ví dụ: railway_20261001T200000Z)."""
    m = TIMESTAMP_REGEX.search(base_name)
    if not m:
        return None
    ts_str = m.group(1)
    try:
        dt = datetime.datetime.strptime(ts_str, "%Y%m%dT%H%M%SZ")
        return dt.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def list_remote_backup_sets(s3_client, bucket_name: str, prefix: str = DEFAULT_PREFIX) -> list[RemoteBackupSet]:
    """
    Liệt kê toàn bộ các cặp bản sao lưu hoàn chỉnh trên bucket.
    Xử lý an toàn các tệp mồ côi (orphans) hoặc tệp không đúng cấu trúc.
    """
    paginator = s3_client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)

    dumps: dict[str, tuple[str, int]] = {}
    manifests: dict[str, tuple[str, int]] = {}

    for page in pages:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            size = obj["Size"]

            if key.endswith(".dump.manifest.json"):
                stem = key.removesuffix(".dump.manifest.json")
                base_name = stem[len(prefix):] if stem.startswith(prefix) else stem
                manifests[base_name] = (key, size)
            elif key.endswith(".dump"):
                stem = key.removesuffix(".dump")
                base_name = stem[len(prefix):] if stem.startswith(prefix) else stem
                dumps[base_name] = (key, size)
            else:
                # Bỏ qua an toàn tệp lạ / không đúng quy ước
                continue

    valid_sets: list[RemoteBackupSet] = []
    all_bases = set(dumps.keys()) | set(manifests.keys())

    for base in all_bases:
        has_dump = base in dumps
        has_manifest = base in manifests

        if not (has_dump and has_manifest):
            # Tệp mồ côi (chỉ có 1 trong 2): bỏ qua an toàn
            continue

        ts = parse_timestamp_from_base_name(base)
        if ts is None:
            # Tên tệp không chứa timestamp hợp lệ: bỏ qua
            continue

        dump_key, dump_size = dumps[base]
        manifest_key, manifest_size = manifests[base]

        valid_sets.append(
            RemoteBackupSet(
                base_name=base,
                dump_key=dump_key,
                manifest_key=manifest_key,
                timestamp_utc=ts,
                dump_size_bytes=dump_size,
                manifest_size_bytes=manifest_size,
            )
        )

    valid_sets.sort(key=lambda s: s.timestamp_utc)
    return valid_sets


def upload_backup_set(
    s3_client,
    bucket_name: str,
    dump_path: pathlib.Path,
    manifest_path: pathlib.Path,
    prefix: str = DEFAULT_PREFIX,
) -> RemoteBackupSet:
    """
    Tải cặp bản sao lưu hoàn chỉnh lên Cloudflare R2 STANDARD storage.
    Bắt buộc cả 2 tệp phải tải thành công và kiểm chứng kích thước sau khi tải.
    """
    if not dump_path.exists() or dump_path.stat().st_size == 0:
        raise ValueError(f"Tệp dump không hợp lệ hoặc rỗng: {dump_path}")
    if not manifest_path.exists() or manifest_path.stat().st_size == 0:
        raise ValueError(f"Tệp manifest không hợp lệ hoặc rỗng: {manifest_path}")

    dump_size_local = dump_path.stat().st_size
    manifest_size_local = manifest_path.stat().st_size

    dump_key = f"{prefix}{dump_path.name}"
    manifest_key = f"{prefix}{manifest_path.name}"
    base_name = dump_path.stem

    ts = parse_timestamp_from_base_name(base_name)
    if ts is None:
        ts = datetime.datetime.now(datetime.timezone.utc)

    # Bước 1: Tải tệp .dump với StorageClass STANDARD
    print(f"[*] Đang tải {dump_path.name} ({dump_size_local:,} bytes) lên R2...")
    t0 = time.time()
    try:
        s3_client.upload_file(
            Filename=str(dump_path),
            Bucket=bucket_name,
            Key=dump_key,
            ExtraArgs={"StorageClass": "STANDARD"},
        )
    except Exception as e:
        raise RuntimeError(f"Tải tệp dump thất bại: {sanitize_message(str(e))}") from e
    t_dump = time.time() - t0
    print(f"[+] Đã tải dump hoàn tất ({t_dump:.2f}s).")

    # Bước 2: Tải tệp .dump.manifest.json với StorageClass STANDARD
    print(f"[*] Đang tải {manifest_path.name} ({manifest_size_local:,} bytes) lên R2...")
    t1 = time.time()
    try:
        s3_client.upload_file(
            Filename=str(manifest_path),
            Bucket=bucket_name,
            Key=manifest_key,
            ExtraArgs={"StorageClass": "STANDARD"},
        )
    except Exception as e:
        raise RuntimeError(f"Tải tệp manifest thất bại: {sanitize_message(str(e))}") from e
    t_manifest = time.time() - t1
    print(f"[+] Đã tải manifest hoàn tất ({t_manifest:.2f}s).")

    # Bước 3: Xác thực từ xa (Remote Confirmation & Size Match)
    print("[*] Đang xác thực đối tượng trên bộ lưu trữ từ xa...")
    try:
        head_dump = s3_client.head_object(Bucket=bucket_name, Key=dump_key)
        remote_dump_size = head_dump["ContentLength"]
    except Exception as e:
        raise RuntimeError(f"Kiểm chứng remote dump thất bại ({dump_key}): {sanitize_message(str(e))}") from e

    if remote_dump_size != dump_size_local:
        raise RuntimeError(
            f"Kích thước remote dump lệch với local! Remote: {remote_dump_size}, Local: {dump_size_local}"
        )

    try:
        head_manifest = s3_client.head_object(Bucket=bucket_name, Key=manifest_key)
        remote_manifest_size = head_manifest["ContentLength"]
    except Exception as e:
        raise RuntimeError(f"Kiểm chứng remote manifest thất bại ({manifest_key}): {sanitize_message(str(e))}") from e

    if remote_manifest_size != manifest_size_local:
        raise RuntimeError(
            f"Kích thước remote manifest lệch với local! Remote: {remote_manifest_size}, Local: {manifest_size_local}"
        )

    print(f"[+] Xác thực từ xa thành công 100%: Cặp bản sao lưu '{base_name}' an toàn trên R2.")
    return RemoteBackupSet(
        base_name=base_name,
        dump_key=dump_key,
        manifest_key=manifest_key,
        timestamp_utc=ts,
        dump_size_bytes=remote_dump_size,
        manifest_size_bytes=remote_manifest_size,
    )


def select_backup_sets_for_retention(
    backup_sets: list[RemoteBackupSet],
    newest_verified: RemoteBackupSet | None = None,
    now_utc: datetime.datetime | None = None,
) -> list[RemoteBackupSet]:
    """
    Thuật toán lựa chọn bản sao lưu cần xóa theo chính sách lưu giữ (Retention Policy):
    - Cổng an toàn 1: Tuyệt đối không xóa nếu không có bản sao lưu mới được xác thực trong phiên chạy.
    - Cổng an toàn 2: Tổng số cặp bản sao lưu <= 1 -> Tuyệt đối không xóa bất kỳ bản nào.
    - Cổng an toàn 3: Bản sao lưu mới nhất (newest verified pair) TUYỆT ĐỐI KHÔNG BAO GIỜ bị xóa.
    - Cửa sổ ngày (Daily Window): Giữ lại toàn bộ bản sao lưu trong vòng 14 ngày gần nhất.
    - Cửa sổ tuần (Weekly Window): Giữ lại 1 bản/tuần cho 4 tuần kế tiếp (từ 14 đến 42 ngày).
    - Toàn bộ bản sao lưu cũ hơn nằm ngoài 2 cửa sổ trên được đưa vào danh sách thu dọn.
    """
    if newest_verified is None:
        # Không có bản sao lưu mới được xác nhận: Không kích hoạt retention
        return []

    if len(backup_sets) <= 1:
        # 1 hoặc 0 cặp bản sao lưu: Không kích hoạt retention
        return []

    now = now_utc or datetime.datetime.now(datetime.timezone.utc)
    newest_pair = max(backup_sets, key=lambda s: s.timestamp_utc)

    # Đảm bảo newest_verified khớp với newest_pair
    if newest_verified.base_name != newest_pair.base_name and newest_verified.timestamp_utc < newest_pair.timestamp_utc:
        # newest_pair có thể mới hơn nữa nếu có tệp đồng thời, vẫn bảo vệ newest_pair
        pass

    daily_cutoff = now - datetime.timedelta(days=14)
    weekly_cutoff = now - datetime.timedelta(days=42)

    kept_sets: set[str] = set()

    # Invariant: Bản sao lưu mới nhất LUÔN ĐƯỢC GIỮ
    kept_sets.add(newest_pair.base_name)
    if newest_verified:
        kept_sets.add(newest_verified.base_name)

    # 1. Giữ toàn bộ bản trong vòng 14 ngày
    for s in backup_sets:
        if s.timestamp_utc >= daily_cutoff:
            kept_sets.add(s.base_name)

    # 2. Giữ tối đa 4 bản tuần cho khoảng thời gian 14 - 42 ngày (nhóm theo tuần lịch ISO)
    weekly_candidates = [
        s for s in backup_sets
        if weekly_cutoff <= s.timestamp_utc < daily_cutoff
    ]
    # Nhóm theo tuần: (year, iso_week)
    weeks: dict[tuple[int, int], RemoteBackupSet] = {}
    for s in weekly_candidates:
        week_key = (s.timestamp_utc.isocalendar().year, s.timestamp_utc.isocalendar().week)
        # Ưu tiên bản mới nhất trong tuần đó
        if week_key not in weeks or s.timestamp_utc > weeks[week_key].timestamp_utc:
            weeks[week_key] = s

    for s in weeks.values():
        kept_sets.add(s.base_name)

    to_delete: list[RemoteBackupSet] = []
    for s in backup_sets:
        if s.base_name not in kept_sets:
            to_delete.append(s)

    # Cổng an toàn bảo vệ: Newest tuyệt đối không nằm trong to_delete
    for s in to_delete:
        if s.base_name == newest_pair.base_name:
            raise RuntimeError("VI PHẠM BẢO MẬT CỐT LÕI: Bản sao lưu mới nhất bị chọn để xóa!")

    # Cổng an toàn bảo vệ: Không bao giờ xóa toàn bộ
    if len(backup_sets) - len(to_delete) < 1:
        return []

    return to_delete


def apply_retention(s3_client, bucket_name: str, to_delete: list[RemoteBackupSet]) -> int:
    """Xóa các cặp bản sao lưu hết hạn hoàn chỉnh (cả dump và manifest)."""
    if not to_delete:
        print("[+] Retention: Không có cặp bản sao lưu nào hết hạn cần thu dọn.")
        return 0

    print(f"[*] Retention: Bắt đầu thu dọn {len(to_delete)} cặp bản sao lưu hết hạn...")
    deleted_count = 0
    for s in to_delete:
        print(f"    [-] Xóa bản hết hạn: {s.base_name} ({s.dump_size_bytes:,} bytes)")
        try:
            s3_client.delete_object(Bucket=bucket_name, Key=s.dump_key)
            s3_client.delete_object(Bucket=bucket_name, Key=s.manifest_key)
            deleted_count += 1
        except Exception as e:
            print(f"[!] Cảnh báo: Lỗi xóa cặp '{s.base_name}': {sanitize_message(str(e))}", file=sys.stderr)

    print(f"[+] Retention hoàn tất: Đã xóa thành công {deleted_count}/{len(to_delete)} cặp bản sao lưu.")
    return deleted_count


def cmd_upload_pair(args: argparse.Namespace) -> int:
    """Subcommand: Tải cặp dump + manifest chỉ định lên R2."""
    dump_path = pathlib.Path(args.dump_file).resolve()
    manifest_path = pathlib.Path(args.manifest_file).resolve() if args.manifest_file else dump_path.with_name(f"{dump_path.name}.manifest.json")

    conf = get_r2_config()
    s3_client = create_s3_client(conf)

    newest_pair = upload_backup_set(
        s3_client,
        bucket_name=conf["bucket_name"],
        dump_path=dump_path,
        manifest_path=manifest_path,
        prefix=conf["prefix"],
    )

    if args.apply_retention:
        all_sets = list_remote_backup_sets(s3_client, conf["bucket_name"], conf["prefix"])
        to_delete = select_backup_sets_for_retention(all_sets, newest_verified=newest_pair)
        apply_retention(s3_client, conf["bucket_name"], to_delete)

    return 0


def cmd_list_pairs(args: argparse.Namespace) -> int:
    """Subcommand: Liệt kê các cặp bản sao lưu từ xa."""
    conf = get_r2_config()
    s3_client = create_s3_client(conf)
    all_sets = list_remote_backup_sets(s3_client, conf["bucket_name"], conf["prefix"])

    print(f"[+] Danh sách bản sao lưu trên R2 ({conf['bucket_name']}, prefix='{conf['prefix']}'):")
    print(f"    Tổng số cặp hợp lệ: {len(all_sets)}")
    for i, s in enumerate(all_sets, start=1):
        ts_str = s.timestamp_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"    {i}. {s.base_name} | {ts_str} | Dump: {s.dump_size_bytes:,} bytes")
    return 0


def cmd_prune_pairs(args: argparse.Namespace) -> int:
    """Subcommand: Chỉ áp dụng thu dọn retention nếu có newest-verified chỉ định."""
    conf = get_r2_config()
    s3_client = create_s3_client(conf)
    all_sets = list_remote_backup_sets(s3_client, conf["bucket_name"], conf["prefix"])

    if not all_sets:
        print("[!] Không có bản sao lưu nào trên R2.")
        return 0

    newest = all_sets[-1]
    to_delete = select_backup_sets_for_retention(all_sets, newest_verified=newest)
    apply_retention(s3_client, conf["bucket_name"], to_delete)
    return 0


def cmd_run_pipeline(args: argparse.Namespace) -> int:
    """
    Subcommand: Chạy toàn bộ chu trình tự động (Autonomous Cron Pipeline):
    1. Tạo bản sao lưu cục bộ qua scripts.db_backup (--direct)
    2. Xác thực bản sao lưu qua scripts.db_backup verify
    3. Tải cặp .dump + .manifest.json lên Cloudflare R2 STANDARD
    4. Kiểm chứng remote existence & size
    5. Áp dụng chính sách lưu giữ (Retention: 14 ngày + 4 tuần)
    """
    from scripts.db_backup import cmd_backup, cmd_verify

    output_dir = pathlib.Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("[PHASE C] KHỞI ĐỘNG CHU TRÌNH SAO LƯU & LƯU TRỮ TỰ ĐỘNG")
    print(f"Thời gian: {datetime.datetime.now(datetime.timezone.utc).isoformat()} UTC")
    print("=" * 60)

    # Bước 1: Tạo backup
    print("\n[BƯỚC 1/5] Thực thi sao lưu database cục bộ (--direct)...")
    backup_args = argparse.Namespace(
        output_dir=str(output_dir),
        service="postgres",
        compose_file=None,
        direct=True,
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=int(os.environ.get("PGPORT", "5432")),
        user=os.environ.get("PGUSER", "postgres"),
        dbname=os.environ.get("PGDATABASE", "railway"),
        include_row_counts=True,
    )

    t_start = time.time()
    rc = cmd_backup(backup_args)
    if rc != 0:
        raise RuntimeError("Bước sao lưu database cục bộ thất bại! Hủy bỏ chu trình.")

    # Tìm tệp vừa tạo mới nhất trong output_dir
    dumps = sorted(output_dir.glob("*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not dumps:
        raise RuntimeError("Không tìm thấy tệp .dump sau khi sao lưu!")
    latest_dump = dumps[0]
    latest_manifest = latest_dump.with_name(f"{latest_dump.name}.manifest.json")

    # Bước 2: Xác thực archive TOC & Checksum
    print("\n[BƯỚC 2/5] Xác thực tính toàn vẹn của tệp sao lưu...")
    verify_args = argparse.Namespace(
        dump_file=str(latest_dump),
        service="postgres",
        compose_file=None,
        direct=True,
    )
    rc_verify = cmd_verify(verify_args)
    if rc_verify != 0:
        raise RuntimeError("Bản sao lưu không vượt qua bước kiểm chứng toàn vẹn! Hủy bỏ tải lên.")

    # Bước 3: Tải lên Cloudflare R2
    print("\n[BƯỚC 3/5] Tải cặp bản sao lưu lên Cloudflare R2 STANDARD...")
    conf = get_r2_config()
    s3_client = create_s3_client(conf)

    newest_pair = upload_backup_set(
        s3_client=s3_client,
        bucket_name=conf["bucket_name"],
        dump_path=latest_dump,
        manifest_path=latest_manifest,
        prefix=conf["prefix"],
    )

    # Bước 4: Kiểm tra danh sách remote
    print("\n[BƯỚC 4/5] Đồng bộ danh mục bản sao lưu từ xa...")
    all_sets = list_remote_backup_sets(s3_client, conf["bucket_name"], conf["prefix"])
    print(f"[+] Hiện có {len(all_sets)} cặp bản sao lưu hoàn chỉnh trên R2.")

    # Bước 5: Áp dụng chính sách lưu giữ (Retention)
    print("\n[BƯỚC 5/5] Áp dụng chính sách lưu giữ (Retention Policy)...")
    to_delete = select_backup_sets_for_retention(all_sets, newest_verified=newest_pair)
    apply_retention(s3_client, conf["bucket_name"], to_delete)

    # Dọn dẹp tệp dump cục bộ tạm thời (để giải phóng đĩa container)
    if args.cleanup_local:
        print("\n[*] Dọn dẹp tệp cục bộ tạm thời sau khi lưu trữ từ xa an toàn...")
        if latest_dump.exists():
            latest_dump.unlink()
        if latest_manifest.exists():
            latest_manifest.unlink()
        print("[+] Đã dọn dẹp bộ nhớ đệm cục bộ.")

    t_total = time.time() - t_start
    print("\n" + "=" * 60)
    print(f"[OK] CHU TRÌNH SAO LƯU TỰ ĐỘNG HOÀN TẤT THÀNH CÔNG (Tổng thời gian: {t_total:.2f}s)")
    print(f"     Bản sao lưu: {newest_pair.base_name}")
    print(f"     Kích thước dump: {newest_pair.dump_size_bytes:,} bytes")
    print(f"     Bucket: {conf['bucket_name']}")
    print("=" * 60)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Công cụ quản lý lưu trữ từ xa & retention bản sao lưu PostgreSQL Chợ PTITers (Phase C)"
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # upload-pair
    p_up = subparsers.add_parser("upload-pair", help="Tải một cặp dump + manifest lên R2")
    p_up.add_argument("dump_file", help="Đường dẫn tới tệp .dump")
    p_up.add_argument("--manifest-file", default=None, help="Đường dẫn tới tệp manifest (mặc định: tự sinh)")
    p_up.add_argument("--apply-retention", action="store_true", help="Áp dụng retention sau khi tải thành công")

    # list-pairs
    subparsers.add_parser("list-pairs", help="Liệt kê danh sách các cặp bản sao lưu trên R2")

    # prune-pairs
    subparsers.add_parser("prune-pairs", help="Áp dụng retention trên các bản sao lưu hiện có")

    # run-pipeline
    p_pipe = subparsers.add_parser("run-pipeline", help="Chạy toàn bộ chu trình backup -> verify -> upload -> retention")
    p_pipe.add_argument("--output-dir", default="backups", help="Thư mục xuất dump cục bộ tạm thời")
    p_pipe.add_argument("--cleanup-local", action="store_true", help="Xóa tệp dump cục bộ sau khi tải lên thành công")

    args = parser.parse_args()

    try:
        if args.subcommand == "upload-pair":
            return cmd_upload_pair(args)
        elif args.subcommand == "list-pairs":
            return cmd_list_pairs(args)
        elif args.subcommand == "prune-pairs":
            return cmd_prune_pairs(args)
        elif args.subcommand == "run-pipeline":
            return cmd_run_pipeline(args)
        else:
            parser.print_help()
            return 1
    except Exception as e:
        safe_err = sanitize_message(str(e))
        print(f"[!] LỖI THỰC THI (REMOTE BACKUP): {safe_err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
