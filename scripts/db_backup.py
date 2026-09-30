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
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5432
IDENTIFIER_REGEX = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{1,62}$")
SENSITIVE_KEY_PATTERNS = [
    re.compile(r"pass(word)?", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"database_url", re.IGNORECASE),
]


def parse_server_major(version_str: str, version_num_str: str | None = None) -> int:
    """Trích xuất số phiên bản major của PostgreSQL server."""
    if version_num_str and version_num_str.strip().isdigit():
        num = int(version_num_str.strip())
        if num >= 100000:
            return num // 10000
    cleaned = version_str.strip()
    m = re.search(r"(?:PostgreSQL\s+)?(\d+)", cleaned, re.IGNORECASE)
    if m:
        return int(m.group(1))
    raise ValueError(f"Không thể xác định phiên bản major từ server version: '{version_str}'")


def get_pg_dump_major(
    direct: bool = False,
    service: str = DEFAULT_SERVICE,
    compose_file: str | None = None,
) -> int:
    """Lấy số phiên bản major của công cụ pg_dump."""
    if direct:
        try:
            res = subprocess.run(["pg_dump", "--version"], capture_output=True, text=True, check=False)
        except FileNotFoundError:
            raise RuntimeError(
                "Không tìm thấy công cụ 'pg_dump' trên hệ thống. "
                "Vui lòng cài đặt PostgreSQL client tools (phiên bản tương thích với server)."
            )
    else:
        compose_cmd = get_compose_cmd(compose_file)
        cmd = [*compose_cmd, "exec", "-T", service, "pg_dump", "--version"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)

    if res.returncode != 0:
        err = res.stderr.strip() or res.stdout.strip()
        raise RuntimeError(f"Lỗi kiểm tra phiên bản pg_dump: {err}")

    stdout = res.stdout.strip()
    m = re.search(r"\(PostgreSQL\)\s+(\d+)", stdout)
    if not m:
        m = re.search(r"pg_dump\s+.*?(\d+)", stdout)
    if not m:
        raise ValueError(f"Không thể phân tích phiên bản từ pg_dump output: '{stdout}'")
    return int(m.group(1))


def check_pg_dump_compatibility(server_major: int, dump_major: int) -> None:
    """
    Kiểm tra tương thích phiên bản giữa pg_dump và PostgreSQL server.
    Nguyên tắc vàng: pg_dump major >= server major.
    """
    if dump_major < server_major:
        raise RuntimeError(
            f"TỪ CHỐI AN TOÀN - KHÔNG TƯƠNG THÍCH PHIÊN BẢN: "
            f"pg_dump (v{dump_major}) cũ hơn PostgreSQL server (v{server_major}). "
            f"Theo nguyên tắc PostgreSQL, pg_dump phải có phiên bản lớn hơn hoặc bằng server để tránh mất mát dữ liệu hoặc lỗi cấu trúc!"
        )
    elif dump_major > server_major:
        print(
            f"[!] CẢNH BÁO PHIÊN BẢN: pg_dump (v{dump_major}) mới hơn server (v{server_major}). "
            f"Bản dump tương thích ngược nhưng khuyến nghị sử dụng cùng phiên bản major khi có thể."
        )
    else:
        print(f"[+] Phiên bản pg_dump (v{dump_major}) khớp chính xác với server (v{server_major}).")


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
    direct: bool = False,
    host: str | None = None,
    port: int | None = None,
    password: str | None = None,
) -> str:
    """Thực thi câu truy vấn SQL đơn qua psql (Docker Compose hoặc Direct connection)."""
    if direct:
        target_host = host or os.environ.get("PGHOST", DEFAULT_HOST)
        target_port = str(port or os.environ.get("PGPORT", str(DEFAULT_PORT)))
        target_user = user or os.environ.get("PGUSER", DEFAULT_USER)
        target_db = dbname or os.environ.get("PGDATABASE", DEFAULT_DBNAME)
        cmd = [
            "psql",
            "-h",
            target_host,
            "-p",
            target_port,
            "-U",
            target_user,
            "-d",
            target_db,
            "-t",
            "-A",
            "-c",
            sql,
        ]
        env = os.environ.copy()
        pg_pwd = password or os.environ.get("PGPASSWORD")
        if pg_pwd:
            env["PGPASSWORD"] = pg_pwd
        try:
            res = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            raise RuntimeError(
                "Không tìm thấy công cụ 'psql' trên hệ thống. "
                "Vui lòng cài đặt PostgreSQL client tools."
            )
    else:
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
    direct: bool = False,
) -> tuple[bool, int, str]:
    """Kiểm tra tính toàn vẹn của tệp archive dump bằng pg_restore --list."""
    if direct:
        cmd = ["pg_restore", "-l"]
        try:
            with open(dump_path, "rb") as f:
                proc = subprocess.run(cmd, stdin=f, capture_output=True, check=False)
        except FileNotFoundError:
            return False, 0, "Không tìm thấy công cụ 'pg_restore' trên hệ thống."
        except Exception as e:
            return False, 0, str(e)
    else:
        compose_cmd = get_compose_cmd(compose_file)
        cmd = [*compose_cmd, "exec", "-T", service, "pg_restore", "-l"]
        try:
            with open(dump_path, "rb") as f:
                proc = subprocess.run(cmd, stdin=f, capture_output=True, check=False)
        except Exception as e:
            return False, 0, str(e)

    if proc.returncode != 0:
        err_msg = proc.stderr.decode("utf-8", errors="ignore").strip()
        return False, 0, err_msg
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    return True, len(lines), ""


def collect_database_metadata(
    service: str,
    dbname: str,
    user: str,
    include_row_counts: bool = False,
    compose_file: str | None = None,
    direct: bool = False,
    host: str | None = None,
    port: int | None = None,
    password: str | None = None,
) -> dict:
    """Thu thập siêu dữ liệu trạng thái của cơ sở dữ liệu nguồn."""
    kw = {
        "service": service,
        "compose_file": compose_file,
        "direct": direct,
        "host": host,
        "port": port,
        "password": password,
    }

    pg_version = query_postgres("SELECT version();", dbname, user, **kw)
    server_version_str = query_postgres("SHOW server_version;", dbname, user, **kw)
    try:
        server_version_num_str = query_postgres("SHOW server_version_num;", dbname, user, **kw)
    except Exception:
        server_version_num_str = ""

    current_db = query_postgres("SELECT current_database();", dbname, user, **kw)
    alembic_rev = query_postgres(
        "SELECT version_num FROM alembic_version LIMIT 1;",
        dbname,
        user,
        **kw,
    )

    app_table_count_str = query_postgres(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name != 'alembic_version';",
        dbname,
        user,
        **kw,
    )
    app_table_count = int(app_table_count_str)

    physical_table_count_str = query_postgres(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';",
        dbname,
        user,
        **kw,
    )
    physical_table_count = int(physical_table_count_str)

    tables_output = query_postgres(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name != 'alembic_version' "
        "ORDER BY table_name;",
        dbname,
        user,
        **kw,
    )
    table_names = [t.strip() for t in tables_output.splitlines() if t.strip()]

    row_counts = {}
    if include_row_counts:
        for tbl in table_names:
            cnt_str = query_postgres(
                f'SELECT count(*) FROM "{tbl}";',
                dbname,
                user,
                **kw,
            )
            row_counts[tbl] = int(cnt_str)

    return {
        "postgres_version": pg_version,
        "server_version": server_version_str,
        "server_version_num": server_version_num_str,
        "database_name": current_db,
        "alembic_revision": alembic_rev,
        "application_table_count": app_table_count,
        "physical_table_count": physical_table_count,
        "table_names": table_names,
        "row_counts": row_counts,
    }


def assert_manifest_clean_of_secrets(manifest_data: dict) -> None:
    """Đảm bảo không có bất kỳ trường bí mật nào trong manifest metadata."""
    for key, value in manifest_data.items():
        for pat in SENSITIVE_KEY_PATTERNS:
            if pat.search(key):
                raise ValueError(f"BẢO MẬT: Manifest chứa trường nhạy cảm không được phép: '{key}'")
        if isinstance(value, str):
            for pat in SENSITIVE_KEY_PATTERNS:
                if pat.search(value) and ("password" in value.lower() or "secret" in value.lower()):
                    raise ValueError(f"BẢO MẬT: Manifest chứa giá trị nhạy cảm trong trường '{key}'")


def cmd_backup(args: argparse.Namespace) -> int:
    """Tạo bản sao lưu logical dump PostgreSQL và manifest nguyên tử."""
    is_direct = getattr(args, "direct", False) or bool(getattr(args, "host", None))
    service = args.service or DEFAULT_SERVICE
    compose_file = getattr(args, "compose_file", None)
    output_dir = pathlib.Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if is_direct:
        source_host = getattr(args, "host", None) or os.environ.get("PGHOST", DEFAULT_HOST)
        source_port = getattr(args, "port", None) or (int(os.environ.get("PGPORT")) if os.environ.get("PGPORT") else DEFAULT_PORT)
        source_user = getattr(args, "user", None) or os.environ.get("PGUSER", DEFAULT_USER)
        source_db = getattr(args, "dbname", None) or os.environ.get("PGDATABASE", DEFAULT_DBNAME)
        source_password = os.environ.get("PGPASSWORD")
        print(f"[*] Chế độ: Direct connection ({source_host}:{source_port})")
    else:
        source_host = None
        source_port = None
        source_password = None
        source_user = get_container_env(service, "POSTGRES_USER", DEFAULT_USER, compose_file=compose_file)
        source_db = get_container_env(service, "POSTGRES_DB", DEFAULT_DBNAME, compose_file=compose_file)
        print(f"[*] Chế độ: Docker Compose (service '{service}')")
        if compose_file:
            print(f"[*] Tệp Compose: {compose_file}")

    print(f"[*] Bắt đầu sao lưu database '{source_db}'...")
    print(f"[*] Thư mục đầu ra: {output_dir}")

    # Thu thập siêu dữ liệu trước khi dump
    meta = collect_database_metadata(
        service,
        source_db,
        source_user,
        include_row_counts=args.include_row_counts,
        compose_file=compose_file,
        direct=is_direct,
        host=source_host,
        port=source_port,
        password=source_password,
    )

    # Version Gate: Kiểm tra tương thích phiên bản công cụ pg_dump với PostgreSQL server
    server_major = parse_server_major(
        meta.get("server_version") or meta["postgres_version"],
        meta.get("server_version_num"),
    )
    dump_major = get_pg_dump_major(
        direct=is_direct,
        service=service,
        compose_file=compose_file,
    )
    check_pg_dump_compatibility(server_major, dump_major)

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    timestamp_str = now_utc.strftime("%Y%m%dT%H%M%SZ")
    base_name = f"{source_db}_{timestamp_str}"

    dump_path = output_dir / f"{base_name}.dump"
    part_path = output_dir / f"{base_name}.dump.part"
    manifest_path = output_dir / f"{base_name}.dump.manifest.json"

    if is_direct:
        dump_cmd = [
            "pg_dump",
            "-h",
            source_host,
            "-p",
            str(source_port),
            "-U",
            source_user,
            "-d",
            source_db,
            "--format=custom",
            "--no-owner",
            "--no-acl",
        ]
        dump_env = os.environ.copy()
        if source_password:
            dump_env["PGPASSWORD"] = source_password
    else:
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
        dump_env = None

    t_start = time.time()
    try:
        with open(part_path, "wb") as f_part:
            proc = subprocess.Popen(
                dump_cmd,
                stdout=f_part,
                stderr=subprocess.PIPE,
                env=dump_env,
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
    is_valid, toc_items, err_msg = verify_archive_toc(
        dump_path,
        service=service,
        compose_file=compose_file,
        direct=is_direct,
    )
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
        "server_version": meta.get("server_version", ""),
        "server_version_num": meta.get("server_version_num", ""),
        "alembic_revision": meta["alembic_revision"],
        "application_table_count": meta["application_table_count"],
        "physical_table_count": meta["physical_table_count"],
        "dump_size_bytes": dump_size,
        "sha256": sha256_hash,
        "archive_toc_items": toc_items,
        "table_names": meta["table_names"],
        "connection_mode": "direct" if is_direct else "compose",
    }
    if is_direct:
        manifest_data["host"] = source_host
        manifest_data["port"] = source_port
    else:
        manifest_data["compose_service"] = service

    if args.include_row_counts:
        manifest_data["row_counts"] = meta["row_counts"]
        manifest_data["row_counts_mode"] = "informational"

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
    is_direct = getattr(args, "direct", False)
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
    direct_to_try = is_direct or manifest.get("connection_mode") == "direct"
    is_valid, toc_items, err_msg = verify_archive_toc(
        dump_path,
        service=service,
        compose_file=compose_file,
        direct=direct_to_try,
    )
    # Tự động fallback sang Docker container nếu direct thất bại do thiếu local tool
    if not is_valid and direct_to_try and "Không tìm thấy công cụ" in err_msg:
        is_valid, toc_items, err_msg = verify_archive_toc(
            dump_path,
            service=service,
            compose_file=compose_file,
            direct=False,
        )

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
    is_direct = getattr(args, "direct", False) or bool(getattr(args, "host", None))
    service = args.service or DEFAULT_SERVICE
    compose_file = getattr(args, "compose_file", None)
    dump_path = pathlib.Path(args.dump_file).resolve()

    # Bước 1: Xác thực bản sao lưu trước khi diễn tập
    print("[1/6] Xác thực bản sao lưu trước khi khôi phục...")
    verify_args = argparse.Namespace(
        dump_file=str(dump_path),
        service=service,
        compose_file=compose_file,
        direct=is_direct,
    )
    if cmd_verify(verify_args) != 0:
        print("[!] Không thể tiến hành diễn tập vì bản sao lưu không vượt qua bước kiểm tra!", file=sys.stderr)
        return 1

    manifest_path = dump_path.with_name(f"{dump_path.name}.manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as fm:
        manifest = json.load(fm)

    # Đọc thông tin kiểm chứng trực tiếp từ manifest (TUYỆT ĐỐI KHÔNG truy vấn source DB)
    source_db = manifest.get("database_name", DEFAULT_DBNAME)
    expected_alembic = manifest.get("alembic_revision")
    expected_app_tables = manifest.get("application_table_count")
    expected_tables = manifest.get("table_names", [])
    expected_row_counts = manifest.get("row_counts", {})

    if is_direct:
        target_host = getattr(args, "host", None) or os.environ.get("PGHOST", DEFAULT_HOST)
        target_port = getattr(args, "port", None) or (int(os.environ.get("PGPORT")) if os.environ.get("PGPORT") else DEFAULT_PORT)
        target_user = getattr(args, "user", None) or os.environ.get("PGUSER", DEFAULT_USER)
        target_password = os.environ.get("PGPASSWORD")
        print(f"[*] Target kết nối trực tiếp: {target_host}:{target_port} (user: {target_user})")
    else:
        target_host = None
        target_port = None
        target_password = None
        target_user = get_container_env(service, "POSTGRES_USER", DEFAULT_USER, compose_file=compose_file)
        print(f"[*] Target Docker Compose service: '{service}'")

    # Bước 2: Thiết lập tên database đích cô lập và kiểm tra an toàn
    timestamp_suffix = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    if args.target_db:
        target_db = args.target_db.strip()
    else:
        target_db = f"{source_db}_restore_{timestamp_suffix}"

    validate_target_dbname(target_db, source_db)
    print(f"[2/6] Cơ sở dữ liệu nguồn (từ manifest): '{source_db}', Cơ sở dữ liệu đích cô lập: '{target_db}'")

    # Bước 3: Tạo database đích cô lập
    print(f"[3/6] Tạo database đích cô lập '{target_db}'...")
    create_sql = f"CREATE DATABASE {target_db};"
    if is_direct:
        create_cmd = [
            "psql",
            "-h",
            target_host,
            "-p",
            str(target_port),
            "-U",
            target_user,
            "-d",
            "postgres",
            "-c",
            create_sql,
        ]
        env_create = os.environ.copy()
        if target_password:
            env_create["PGPASSWORD"] = target_password
        create_res = subprocess.run(create_cmd, env=env_create, capture_output=True, text=True, check=False)
    else:
        compose_cmd = get_compose_cmd(compose_file)
        create_res = subprocess.run(
            [
                *compose_cmd,
                "exec",
                "-T",
                service,
                "psql",
                "-U",
                target_user,
                "-d",
                "postgres",
                "-c",
                create_sql,
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
        if is_direct:
            restore_cmd = [
                "pg_restore",
                "-h",
                target_host,
                "-p",
                str(target_port),
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
                "-U",
                target_user,
                "-d",
                target_db,
            ]
            restore_env = os.environ.copy()
            if target_password:
                restore_env["PGPASSWORD"] = target_password
        else:
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
                target_user,
                "-d",
                target_db,
            ]
            restore_env = None

        t_start = time.time()
        with open(dump_path, "rb") as f_in:
            proc_restore = subprocess.run(
                restore_cmd,
                stdin=f_in,
                capture_output=True,
                check=False,
                env=restore_env,
            )
        t_restore = time.time() - t_start

        if proc_restore.returncode != 0:
            err = proc_restore.stderr.decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"Lệnh pg_restore thất bại (exit {proc_restore.returncode}): {err}")

        print(f"[+] Khôi phục thành công vào '{target_db}' trong {t_restore:.2f} giây.")

        # Bước 5: Kiểm tra và đối sánh toàn vẹn dữ liệu từ target database
        print("[5/6] Đối sánh siêu dữ liệu giữa manifest và target database đã khôi phục...")
        target_meta = collect_database_metadata(
            service,
            target_db,
            target_user,
            include_row_counts=bool(expected_row_counts),
            compose_file=compose_file,
            direct=is_direct,
            host=target_host,
            port=target_port,
            password=target_password,
        )

        # Kiểm tra Alembic revision (HARD GATE)
        if target_meta["alembic_revision"] != expected_alembic:
            raise ValueError(
                f"Lệch Alembic revision! Manifest: {expected_alembic}, "
                f"Target DB: {target_meta['alembic_revision']}"
            )
        print(f"[+] Alembic revision khớp hoàn hảo: {target_meta['alembic_revision']}")

        # Kiểm tra số lượng bảng nghiệp vụ (HARD GATE)
        if target_meta["application_table_count"] != expected_app_tables:
            raise ValueError(
                f"Lệch số lượng bảng nghiệp vụ! Manifest: {expected_app_tables}, "
                f"Target DB: {target_meta['application_table_count']}"
            )
        print(f"[+] Số lượng bảng nghiệp vụ khớp: {target_meta['application_table_count']} bảng")

        # Kiểm tra danh sách bảng (HARD GATE)
        missing_tables = set(expected_tables) - set(target_meta["table_names"])
        if missing_tables:
            raise ValueError(f"Thiếu bảng trong target DB: {missing_tables}")

        # Đối sánh số dòng (row counts)
        if expected_row_counts:
            row_count_mismatches = []
            for tbl in expected_tables:
                src_cnt = expected_row_counts.get(tbl, 0)
                tgt_cnt = target_meta["row_counts"].get(tbl, 0)
                if src_cnt != tgt_cnt:
                    row_count_mismatches.append(f"{tbl}: manifest={src_cnt}, restored={tgt_cnt}")

            strict_row_counts = getattr(args, "strict_row_counts", False)
            if row_count_mismatches:
                msg = f"Phát hiện chênh lệch số dòng trên các bảng: {', '.join(row_count_mismatches)}"
                if strict_row_counts:
                    raise ValueError(f"[LỖI STRICT ROW COUNTS] {msg}")
                else:
                    print(
                        f"[!] CẢNH BÁO THÔNG TIN (ROW COUNTS): {msg}. "
                        "Trên cơ sở dữ liệu có ghi đồng thời (concurrent writes), row counts manifest có thể lệch với snapshot dump. "
                        "Các cổng kiểm tra cứng (schema, tables, Alembic head, TOC) đã đạt 100%."
                    )
            else:
                print(f"[+] Đối sánh số dòng toàn bộ {len(expected_tables)} bảng nghiệp vụ: Khớp 100%.")

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
                    drop_sql = f"DROP DATABASE {target_db} WITH (FORCE);"
                    if is_direct:
                        drop_cmd = [
                            "psql",
                            "-h",
                            target_host,
                            "-p",
                            str(target_port),
                            "-U",
                            target_user,
                            "-d",
                            "postgres",
                            "-c",
                            drop_sql,
                        ]
                        env_drop = os.environ.copy()
                        if target_password:
                            env_drop["PGPASSWORD"] = target_password
                        drop_res = subprocess.run(drop_cmd, env=env_drop, capture_output=True, text=True, check=False)
                    else:
                        drop_res = subprocess.run(
                            [
                                *compose_cmd,
                                "exec",
                                "-T",
                                service,
                                "psql",
                                "-U",
                                target_user,
                                "-d",
                                "postgres",
                                "-c",
                                drop_sql,
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
        description="Công cụ quản trị sao lưu & khôi phục PostgreSQL cho Chợ PTITers (Phase 9C-B / Phase B Readiness)"
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
        "--include-row-counts",
        action="store_true",
        help="Lưu số lượng dòng chi tiết vào manifest (informational snapshot)",
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
        "--direct",
        action="store_true",
        help="Kích hoạt chế độ kết nối trực tiếp (native tools psql/pg_dump qua PGHOST/PGPORT)",
    )
    p_backup.add_argument(
        "--host",
        default=None,
        help="Host của PostgreSQL (mặc định: PGHOST hoặc 127.0.0.1)",
    )
    p_backup.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port của PostgreSQL (mặc định: PGPORT hoặc 5432)",
    )
    p_backup.add_argument(
        "--user",
        "-U",
        default=None,
        help="User của PostgreSQL (mặc định: PGUSER hoặc postgres)",
    )
    p_backup.add_argument(
        "--dbname",
        "-d",
        default=None,
        help="Tên Database (mặc định: PGDATABASE hoặc student_marketplace)",
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
    p_verify.add_argument(
        "--direct",
        action="store_true",
        help="Sử dụng pg_restore cục bộ thay vì qua Docker container",
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
        "--keep-target",
        action="store_true",
        help="Không xóa database đích sau khi diễn tập thành công (dành cho điều tra thủ công)",
    )
    p_restore.add_argument(
        "--strict-row-counts",
        action="store_true",
        help="Bắt buộc khớp 100%% row counts (dành cho kiểm thử tĩnh/dev)",
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
        "--direct",
        action="store_true",
        help="Kết nối trực tiếp tới PostgreSQL target qua host/port thay vì Docker Compose",
    )
    p_restore.add_argument(
        "--host",
        default=None,
        help="Host của PostgreSQL target (mặc định: PGHOST hoặc 127.0.0.1)",
    )
    p_restore.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port của PostgreSQL target (mặc định: PGPORT hoặc 5432)",
    )
    p_restore.add_argument(
        "--user",
        "-U",
        default=None,
        help="User của PostgreSQL target (mặc định: PGUSER hoặc postgres)",
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
