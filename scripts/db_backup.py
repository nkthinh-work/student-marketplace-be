#!/usr/bin/env python3
"""
PostgreSQL Backup & Restore Operations Tool.
Dành riêng cho nền tảng Chợ PTITers (student-marketplace).
Sử dụng chuẩn thư viện Python tiêu chuẩn (Standard Library Only).
"""

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time

# Đảm bảo console Windows hỗ trợ xuất ký tự tiếng Việt an toàn
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

MANIFEST_VERSION = 1
DEFAULT_SERVICE = "postgres"
DEFAULT_DBNAME = "student_marketplace"
DEFAULT_USER = "postgres"
IDENTIFIER_REGEX = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{1,62}$")
SENSITIVE_KEY_PATTERNS = [
    re.compile(r"pass(word)?", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"database_url", re.IGNORECASE),
]


def get_compose_cmd(compose_file: str | None = None) -> list[str]:
    """Xác định lệnh Docker Compose khả dụng trên hệ thống, kèm tệp cấu hình nếu được chỉ định."""
    base_cmd: list[str] = []
    try:
        res = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            base_cmd = ["docker", "compose"]
    except FileNotFoundError:
        pass

    if not base_cmd:
        try:
            res = subprocess.run(
                ["docker-compose", "version"],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0:
                base_cmd = ["docker-compose"]
        except FileNotFoundError:
            pass

    if not base_cmd:
        raise RuntimeError("Không tìm thấy lệnh 'docker compose' hoặc 'docker-compose' trên hệ thống.")

    if compose_file:
        return [*base_cmd, "-f", compose_file]
    return base_cmd


def get_container_env(service: str, var_name: str, default_val: str, compose_file: str | None = None) -> str:
    """Đọc biến môi trường bên trong container dịch vụ."""
    compose_cmd = get_compose_cmd(compose_file)
    cmd = [*compose_cmd, "exec", "-T", service, "printenv", var_name]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return default_val


def query_postgres(
    sql: str,
    dbname: str,
    user: str,
    service: str = DEFAULT_SERVICE,
    compose_file: str | None = None,
) -> str:
    """Thực thi câu truy vấn SQL đơn qua psql bên trong container PostgreSQL."""
    compose_cmd = get_compose_cmd(compose_file)
    cmd = [
        *compose_cmd,
        "exec",
        "-T",
        service,
        "psql",
        "-t",
        "-A",
        "-U",
        user,
        "-d",
        dbname,
        "-c",
        sql,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        err = res.stderr.strip() or res.stdout.strip()
        raise RuntimeError(f"Lỗi truy vấn PostgreSQL ({sql[:60]}...): {err}")
    return res.stdout.strip()


def validate_target_dbname(target_db: str, source_db: str) -> None:
    """Kiểm tra tính an toàn của định danh database và ngăn chặn ghi đè source DB."""
    cleaned_target = target_db.strip() if target_db else ""
    if not cleaned_target or not IDENTIFIER_REGEX.match(cleaned_target):
        raise ValueError(
            f"Tên target database không hợp lệ: '{target_db}'. "
            "Chỉ chấp nhận chữ cái, số, dấu gạch dưới (2-63 ký tự), bắt đầu bằng chữ cái hoặc gạch dưới."
        )

    # Chặn cứng việc chỉ định target trùng với source database đang hoạt động
    if cleaned_target.lower() == source_db.strip().lower():
        raise ValueError(
            f"TỪ CHỐI AN TOÀN: Target database '{target_db}' trùng khớp với active database '{source_db}'. "
            "Quy trình tuyệt đối không cho phép khôi phục đè trực tiếp lên cơ sở dữ liệu đang vận hành!"
        )


def compute_sha256(filepath: pathlib.Path) -> str:
    """Tính toán mã băm SHA-256 của tệp theo từng khối 64KB."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_archive_toc(
    dump_path: pathlib.Path,
    service: str = DEFAULT_SERVICE,
    compose_file: str | None = None,
) -> tuple[bool, int, str]:
    """Kiểm tra tính toàn vẹn của tệp archive dump bằng pg_restore --list."""
    compose_cmd = get_compose_cmd(compose_file)
    cmd = [*compose_cmd, "exec", "-T", service, "pg_restore", "-l"]
    try:
        with open(dump_path, "rb") as f:
            proc = subprocess.run(cmd, stdin=f, capture_output=True, check=False)
        if proc.returncode != 0:
            err_msg = proc.stderr.decode("utf-8", errors="ignore").strip()
            return False, 0, err_msg
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        return True, len(lines), ""
    except Exception as e:
        return False, 0, str(e)


def collect_database_metadata(
    service: str,
    dbname: str,
    user: str,
    include_row_counts: bool = False,
    compose_file: str | None = None,
) -> dict:
    """Thu thập siêu dữ liệu trạng thái của cơ sở dữ liệu nguồn."""
    pg_version = query_postgres("SELECT version();", dbname, user, service, compose_file=compose_file)
    current_db = query_postgres("SELECT current_database();", dbname, user, service, compose_file=compose_file)

    alembic_rev = query_postgres(
        "SELECT version_num FROM alembic_version LIMIT 1;",
        dbname,
        user,
        service,
        compose_file=compose_file,
    )

    app_table_count_str = query_postgres(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name != 'alembic_version';",
        dbname,
        user,
        service,
        compose_file=compose_file,
    )
    app_table_count = int(app_table_count_str)

    physical_table_count_str = query_postgres(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';",
        dbname,
        user,
        service,
        compose_file=compose_file,
    )
    physical_table_count = int(physical_table_count_str)

    tables_output = query_postgres(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name != 'alembic_version' "
        "ORDER BY table_name;",
        dbname,
        user,
        service,
        compose_file=compose_file,
    )
    table_names = [t.strip() for t in tables_output.splitlines() if t.strip()]

    row_counts = {}
    if include_row_counts:
        for tbl in table_names:
            cnt_str = query_postgres(
                f'SELECT count(*) FROM "{tbl}";',
                dbname,
                user,
                service,
                compose_file=compose_file,
            )
            row_counts[tbl] = int(cnt_str)

    return {
        "postgres_version": pg_version,
        "database_name": current_db,
        "alembic_revision": alembic_rev,
        "application_table_count": app_table_count,
        "physical_table_count": physical_table_count,
        "table_names": table_names,
        "row_counts": row_counts,
    }


def assert_manifest_clean_of_secrets(manifest_data: dict) -> None:
    """Đảm bảo không có bất kỳ trường bí mật nào trong manifest metadata."""
    for key in manifest_data.keys():
        for pat in SENSITIVE_KEY_PATTERNS:
            if pat.search(key):
                raise ValueError(f"BẢO MẬT: Manifest chứa trường nhạy cảm không được phép: '{key}'")


def cmd_backup(args: argparse.Namespace) -> int:
    """Tạo bản sao lưu logical dump PostgreSQL và manifest nguyên tử."""
    service = args.service or DEFAULT_SERVICE
    compose_file = getattr(args, "compose_file", None)
    output_dir = pathlib.Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    source_user = get_container_env(service, "POSTGRES_USER", DEFAULT_USER, compose_file=compose_file)
    source_db = get_container_env(service, "POSTGRES_DB", DEFAULT_DBNAME, compose_file=compose_file)

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    timestamp_str = now_utc.strftime("%Y%m%dT%H%M%SZ")
    base_name = f"{source_db}_{timestamp_str}"

    dump_path = output_dir / f"{base_name}.dump"
    part_path = output_dir / f"{base_name}.dump.part"
    manifest_path = output_dir / f"{base_name}.dump.manifest.json"

    print(f"[*] Bắt đầu sao lưu database '{source_db}' từ service '{service}'...")
    if compose_file:
        print(f"[*] Tệp Compose: {compose_file}")
    print(f"[*] Thư mục đầu ra: {output_dir}")

    # Thu thập siêu dữ liệu trước khi dump
    meta = collect_database_metadata(
        service,
        source_db,
        source_user,
        include_row_counts=args.include_row_counts,
        compose_file=compose_file,
    )

    compose_cmd = get_compose_cmd(compose_file)
    dump_cmd = [
        *compose_cmd,
        "exec",
        "-T",
        service,
        "pg_dump",
        "-U",
        source_user,
        "-d",
        source_db,
        "--format=custom",
        "--no-owner",
        "--no-acl",
    ]

    t_start = time.time()
    try:
        with open(part_path, "wb") as f_part:
            proc = subprocess.Popen(
                dump_cmd,
                stdout=f_part,
                stderr=subprocess.PIPE,
            )
            _, stderr = proc.communicate()

        if proc.returncode != 0:
            if part_path.exists():
                part_path.unlink()
            err_text = stderr.decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"Lệnh pg_dump thất bại (exit {proc.returncode}): {err_text}")

        # Đổi tên nguyên tử từ .part sang .dump
        part_path.rename(dump_path)
    except (Exception, KeyboardInterrupt) as e:
        if part_path.exists():
            part_path.unlink()
        raise e

    t_elapsed = time.time() - t_start
    dump_size = dump_path.stat().st_size

    print(f"[+] Dump hoàn tất: {dump_path.name} ({dump_size} bytes, thời gian: {t_elapsed:.2f}s)")

    # Kiểm tra ngay tính toàn vẹn của archive
    print("[*] Xác thực khả năng đọc của archive qua pg_restore --list...")
    is_valid, toc_items, err_msg = verify_archive_toc(dump_path, service=service, compose_file=compose_file)
    if not is_valid:
        if dump_path.exists():
            dump_path.unlink()
        raise RuntimeError(f"Xác thực archive thất bại: {err_msg}")

    print(f"[+] Archive hợp lệ, TOC chứa {toc_items} thành phần.")

    # Tính toán SHA-256
    print("[*] Tính toán mã băm SHA-256...")
    sha256_hash = compute_sha256(dump_path)

    # Khởi tạo manifest
    manifest_data = {
        "manifest_version": MANIFEST_VERSION,
        "created_at_utc": now_utc.isoformat(),
        "backup_format": "postgres-custom",
        "database_name": meta["database_name"],
        "postgres_version": meta["postgres_version"],
        "alembic_revision": meta["alembic_revision"],
        "application_table_count": meta["application_table_count"],
        "physical_table_count": meta["physical_table_count"],
        "dump_size_bytes": dump_size,
        "sha256": sha256_hash,
        "compose_service": service,
        "archive_toc_items": toc_items,
        "table_names": meta["table_names"],
    }
    if args.include_row_counts:
        manifest_data["row_counts"] = meta["row_counts"]

    # Đảm bảo không chứa thông tin nhạy cảm
    assert_manifest_clean_of_secrets(manifest_data)

    # Ghi manifest nguyên tử
    part_manifest = manifest_path.with_suffix(".json.part")
    with open(part_manifest, "w", encoding="utf-8") as fm:
        json.dump(manifest_data, fm, indent=2, ensure_ascii=False)
    part_manifest.rename(manifest_path)

    print(f"[+] Manifest đã lưu: {manifest_path.name}")
    print(f"[OK] SAO LƯU THÀNH CÔNG!")
    print(f"     File: {dump_path.name}")
    print(f"     Kích thước: {dump_size:,} bytes")
    print(f"     Alembic: {meta['alembic_revision']}")
    print(f"     Bảng nghiệp vụ: {meta['application_table_count']}")
    print(f"     SHA-256: {sha256_hash}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Xác thực tính toàn vẹn, checksum và cấu trúc TOC của bản sao lưu."""
    service = args.service or DEFAULT_SERVICE
    compose_file = getattr(args, "compose_file", None)
    dump_path = pathlib.Path(args.dump_file).resolve()
    if not dump_path.exists():
        print(f"[!] Lỗi: Tệp dump không tồn tại: {dump_path}", file=sys.stderr)
        return 1

    manifest_path = dump_path.with_name(f"{dump_path.name}.manifest.json")
    if not manifest_path.exists():
        print(f"[!] Lỗi: Tệp manifest tương ứng không tồn tại: {manifest_path}", file=sys.stderr)
        return 1

    file_size = dump_path.stat().st_size
    if file_size == 0:
        print("[!] Lỗi: Tệp dump rỗng (0 bytes)!", file=sys.stderr)
        return 1

    with open(manifest_path, "r", encoding="utf-8") as fm:
        manifest = json.load(fm)

    # Kiểm tra an toàn secret trong manifest
    assert_manifest_clean_of_secrets(manifest)

    # So khớp SHA-256
    print(f"[*] Kiểm tra mã băm SHA-256 cho {dump_path.name}...")
    actual_hash = compute_sha256(dump_path)
    expected_hash = manifest.get("sha256", "")
    if actual_hash != expected_hash:
        print(f"[!] Lỗi lệch Checksum! Dự kiến: {expected_hash}, Thực tế: {actual_hash}", file=sys.stderr)
        return 1
    print(f"[+] SHA-256 khớp hoàn hảo: {actual_hash}")

    # So khớp kích thước
    if file_size != manifest.get("dump_size_bytes"):
        print(
            f"[!] Lỗi kích thước dump! Manifest: {manifest.get('dump_size_bytes')}, Thực tế: {file_size}",
            file=sys.stderr,
        )
        return 1

    # Kiểm tra cấu trúc archive TOC
    print("[*] Kiểm tra tính đọc được của archive qua pg_restore --list...")
    is_valid, toc_items, err_msg = verify_archive_toc(dump_path, service=service, compose_file=compose_file)
    if not is_valid:
        print(f"[!] Archive hỏng hoặc không tương thích: {err_msg}", file=sys.stderr)
        return 1
    print(f"[+] Archive hợp lệ, {toc_items} thành phần.")

    print(f"[OK] XÁC THỰC BẢN SAO LƯU THÀNH CÔNG:")
    print(f"     Database: {manifest.get('database_name')}")
    print(f"     Alembic Head: {manifest.get('alembic_revision')}")
    print(f"     Bảng nghiệp vụ: {manifest.get('application_table_count')}")
    print(f"     Thời gian tạo: {manifest.get('created_at_utc')}")
    return 0


def cmd_restore_drill(args: argparse.Namespace) -> int:
    """Thực hiện diễn tập khôi phục bản sao lưu vào một database cô lập tạm thời."""
    service = args.service or DEFAULT_SERVICE
    compose_file = getattr(args, "compose_file", None)
    dump_path = pathlib.Path(args.dump_file).resolve()

    # Bước 1: Xác thực bản sao lưu trước khi diễn tập
    print("[1/6] Xác thực bản sao lưu trước khi khôi phục...")
    verify_args = argparse.Namespace(dump_file=str(dump_path), service=service, compose_file=compose_file)
    if cmd_verify(verify_args) != 0:
        print("[!] Không thể tiến hành diễn tập vì bản sao lưu không vượt qua bước kiểm tra!", file=sys.stderr)
        return 1

    manifest_path = dump_path.with_name(f"{dump_path.name}.manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as fm:
        manifest = json.load(fm)

    source_user = get_container_env(service, "POSTGRES_USER", DEFAULT_USER, compose_file=compose_file)
    source_db = get_container_env(service, "POSTGRES_DB", DEFAULT_DBNAME, compose_file=compose_file)

    # Bước 2: Thiết lập tên database đích cô lập và kiểm tra an toàn
    if args.target_db:
        target_db = args.target_db.strip()
    else:
        timestamp_suffix = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
        target_db = f"{source_db}_restore_{timestamp_suffix}"

    validate_target_dbname(target_db, source_db)
    print(f"[2/6] Cơ sở dữ liệu nguồn: '{source_db}', Cơ sở dữ liệu đích cô lập: '{target_db}'")

    # Thu thập snapshot của source DB trước drill
    source_meta = collect_database_metadata(
        service,
        source_db,
        source_user,
        include_row_counts=True,
        compose_file=compose_file,
    )

    compose_cmd = get_compose_cmd(compose_file)

    # Bước 3: Tạo database đích cô lập
    print(f"[3/6] Tạo database đích cô lập '{target_db}'...")
    create_res = subprocess.run(
        [
            *compose_cmd,
            "exec",
            "-T",
            service,
            "psql",
            "-U",
            source_user,
            "-d",
            "postgres",
            "-c",
            f"CREATE DATABASE {target_db};",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if create_res.returncode != 0:
        err = create_res.stderr.strip() or create_res.stdout.strip()
        raise RuntimeError(f"Không thể tạo database đích '{target_db}': {err}")

    target_created = True
    try:
        # Bước 4: Khôi phục dữ liệu từ dump vào database đích qua stdin stream
        print(f"[4/6] Khôi phục dữ liệu từ '{dump_path.name}' vào '{target_db}'...")
        restore_cmd = [
            *compose_cmd,
            "exec",
            "-T",
            service,
            "pg_restore",
            "--exit-on-error",
            "--no-owner",
            "--no-acl",
            "-U",
            source_user,
            "-d",
            target_db,
        ]

        t_start = time.time()
        with open(dump_path, "rb") as f_in:
            proc_restore = subprocess.run(
                restore_cmd,
                stdin=f_in,
                capture_output=True,
                check=False,
            )
        t_restore = time.time() - t_start

        if proc_restore.returncode != 0:
            err = proc_restore.stderr.decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"Lệnh pg_restore thất bại (exit {proc_restore.returncode}): {err}")

        print(f"[+] Khôi phục thành công vào '{target_db}' trong {t_restore:.2f} giây.")

        # Bước 5: Kiểm tra và đối sánh toàn vẹn dữ liệu
        print("[5/6] Đối sánh siêu dữ liệu giữa database nguồn và đích khôi phục...")
        target_meta = collect_database_metadata(
            service,
            target_db,
            source_user,
            include_row_counts=True,
            compose_file=compose_file,
        )

        # Kiểm tra Alembic revision
        if target_meta["alembic_revision"] != manifest["alembic_revision"]:
            raise ValueError(
                f"Lệch Alembic revision! Manifest: {manifest['alembic_revision']}, "
                f"Target DB: {target_meta['alembic_revision']}"
            )
        print(f"[+] Alembic revision khớp hoàn hảo: {target_meta['alembic_revision']}")

        # Kiểm tra số lượng bảng nghiệp vụ
        if target_meta["application_table_count"] != manifest["application_table_count"]:
            raise ValueError(
                f"Lệch số lượng bảng nghiệp vụ! Manifest: {manifest['application_table_count']}, "
                f"Target DB: {target_meta['application_table_count']}"
            )
        print(f"[+] Số lượng bảng nghiệp vụ khớp: {target_meta['application_table_count']} bảng")

        # Kiểm tra danh sách bảng
        missing_tables = set(manifest.get("table_names", [])) - set(target_meta["table_names"])
        if missing_tables:
            raise ValueError(f"Thiếu bảng trong target DB: {missing_tables}")

        # Đối sánh số dòng (row counts)
        row_count_mismatches = []
        for tbl in source_meta["table_names"]:
            src_cnt = source_meta["row_counts"].get(tbl, 0)
            tgt_cnt = target_meta["row_counts"].get(tbl, 0)
            if src_cnt != tgt_cnt:
                row_count_mismatches.append(f"{tbl}: source={src_cnt}, restored={tgt_cnt}")

        if row_count_mismatches:
            raise ValueError(f"Lệch số lượng dòng trên các bảng: {', '.join(row_count_mismatches)}")
        print(f"[+] Đối sánh số dòng toàn bộ {len(source_meta['table_names'])} bảng nghiệp vụ: Khớp 100%.")

        # Kiểm tra database nguồn không hề bị chạm tới
        post_source_meta = collect_database_metadata(
            service,
            source_db,
            source_user,
            compose_file=compose_file,
        )
        if post_source_meta["alembic_revision"] != source_meta["alembic_revision"]:
            raise RuntimeError("CẢNH BÁO: Database nguồn đã bị biến đổi trong quá trình diễn tập!")
        print(f"[+] Database nguồn '{source_db}' hoàn toàn nguyên vẹn và không bị tác động.")

    finally:
        # Bước 6: Dọn dẹp database đích tạm thời
        if target_created:
            if args.keep_target:
                print(f"[*] Cờ --keep-target được chỉ định: Giữ lại database '{target_db}' để kiểm tra thủ công.")
            else:
                print(f"[6/6] Dọn dẹp database đích cô lập '{target_db}'...")
                # Xác thực an toàn kép trước khi drop
                if target_db.strip().lower() == source_db.strip().lower():
                    print(f"[!] TỪ CHỐI DROP: Database đích trùng tên với source DB!", file=sys.stderr)
                else:
                    drop_res = subprocess.run(
                        [
                            *compose_cmd,
                            "exec",
                            "-T",
                            service,
                            "psql",
                            "-U",
                            source_user,
                            "-d",
                            "postgres",
                            "-c",
                            f"DROP DATABASE {target_db} WITH (FORCE);",
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if drop_res.returncode == 0:
                        print(f"[+] Đã xóa database tạm thời '{target_db}' an toàn.")
                    else:
                        print(f"[!] Cảnh báo: Không thể xóa tự động database tạm: {drop_res.stderr.strip()}")

    print("[OK] DIỄN TẬP KHÔI PHỤC (RESTORE DRILL) THÀNH CÔNG 100%!")
    print(f"     Thời gian khôi phục: {t_restore:.2f}s")
    print(f"     Alembic Head: {target_meta['alembic_revision']}")
    print(f"     Bảng nghiệp vụ: {target_meta['application_table_count']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Công cụ quản trị sao lưu & khôi phục PostgreSQL cho Chợ PTITers (Phase 9C-B)"
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Subcommand: backup
    p_backup = subparsers.add_parser("backup", help="Tạo bản sao lưu logical dump và manifest")
    p_backup.add_argument(
        "--output-dir",
        default="backups",
        help="Thư mục lưu trữ bản sao lưu (mặc định: backups/)",
    )
    p_backup.add_argument(
        "--service",
        default=DEFAULT_SERVICE,
        help="Tên Compose service của PostgreSQL (mặc định: postgres)",
    )
    p_backup.add_argument(
        "--compose-file",
        "-f",
        default=None,
        help="Tệp Docker Compose chỉ định (ví dụ: docker-compose.prod.yml)",
    )
    p_backup.add_argument(
        "--include-row-counts",
        action="store_true",
        help="Lưu số lượng dòng chi tiết vào manifest (dành cho kiểm toán dữ liệu nhỏ)",
    )

    # Subcommand: verify
    p_verify = subparsers.add_parser("verify", help="Xác thực tính toàn vẹn và checksum của bản sao lưu")
    p_verify.add_argument("dump_file", help="Đường dẫn tới tệp .dump cần kiểm tra")
    p_verify.add_argument(
        "--service",
        default=DEFAULT_SERVICE,
        help="Tên Compose service của PostgreSQL (mặc định: postgres)",
    )
    p_verify.add_argument(
        "--compose-file",
        "-f",
        default=None,
        help="Tệp Docker Compose chỉ định (ví dụ: docker-compose.prod.yml)",
    )

    # Subcommand: restore-drill
    p_restore = subparsers.add_parser(
        "restore-drill",
        help="Diễn tập khôi phục vào một database cô lập tạm thời để chứng minh tính sử dụng được",
    )
    p_restore.add_argument("dump_file", help="Đường dẫn tới tệp .dump cần khôi phục")
    p_restore.add_argument(
        "--target-db",
        default=None,
        help="Tên database đích cô lập (mặc định: tự động sinh kèm timestamp)",
    )
    p_restore.add_argument(
        "--service",
        default=DEFAULT_SERVICE,
        help="Tên Compose service của PostgreSQL (mặc định: postgres)",
    )
    p_restore.add_argument(
        "--compose-file",
        "-f",
        default=None,
        help="Tệp Docker Compose chỉ định (ví dụ: docker-compose.prod.yml)",
    )
    p_restore.add_argument(
        "--keep-target",
        action="store_true",
        help="Không xóa database đích sau khi diễn tập thành công (dành cho điều tra thủ công)",
    )

    args = parser.parse_args()

    try:
        if args.subcommand == "backup":
            return cmd_backup(args)
        elif args.subcommand == "verify":
            return cmd_verify(args)
        elif args.subcommand == "restore-drill":
            return cmd_restore_drill(args)
        else:
            parser.print_help()
            return 1
    except Exception as e:
        print(f"[!] LỖI THỰC THI: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
