"""
Unit tests for PostgreSQL Backup & Restore Tool (scripts/db_backup.py).
Kiểm thử an toàn tham số, xác thực băm, phòng chống tấn công SQL injection và quy tắc bảo mật.
"""

import hashlib
import json
import pathlib
import pytest

from scripts.db_backup import (
    assert_manifest_clean_of_secrets,
    compute_sha256,
    validate_target_dbname,
)


def test_validate_target_dbname_valid():
    """Tên database hợp lệ chỉ chứa chữ cái, số, gạch dưới và không trùng source DB."""
    source_db = "student_marketplace"
    valid_names = [
        "student_marketplace_restore_20260924_120000",
        "restore_drill_db",
        "test_isolated_db_123",
        "_backup_target",
    ]
    for name in valid_names:
        validate_target_dbname(name, source_db)


def test_validate_target_dbname_invalid_characters():
    """Tên database chứa ký tự đặc biệt, khoảng trắng, gạch ngang hoặc mã SQL phải bị từ chối."""
    source_db = "student_marketplace"
    invalid_names = [
        "student-marketplace-restore",  # Gạch ngang
        "restore db",  # Khoảng trắng
        "db; DROP TABLE users;",  # SQL injection
        "db' OR '1'='1",  # Nháy đơn
        'db"test',  # Nháy kép
        "123_invalid_start",  # Bắt đầu bằng số
        "",  # Rỗng
        "a" * 64,  # Quá 63 ký tự giới hạn của PostgreSQL identifier
    ]
    for name in invalid_names:
        with pytest.raises(ValueError, match="Tên target database không hợp lệ"):
            validate_target_dbname(name, source_db)


def test_validate_target_dbname_hard_refusal_for_source_db():
    """Cơ chế chặn cứng: Target database trùng với active source DB phải ném lỗi từ chối an toàn."""
    source_db = "student_marketplace"
    with pytest.raises(ValueError, match="TỪ CHỐI AN TOÀN"):
        validate_target_dbname("student_marketplace", source_db)

    # Thử nghiệm không phân biệt hoa thường
    with pytest.raises(ValueError, match="TỪ CHỐI AN TOÀN"):
        validate_target_dbname("STUDENT_MARKETPLACE", source_db)

    with pytest.raises(ValueError, match="TỪ CHỐI AN TOÀN"):
        validate_target_dbname("  student_marketplace  ", source_db)


def test_assert_manifest_clean_of_secrets():
    """Manifest chỉ chứa metadata, cấm tuyệt đối password, secret, token hay connection string."""
    clean_manifest = {
        "manifest_version": 1,
        "database_name": "student_marketplace",
        "postgres_version": "PostgreSQL 15.19",
        "alembic_revision": "c2f84937f5d2",
        "application_table_count": 29,
        "physical_table_count": 30,
        "dump_size_bytes": 136184,
        "sha256": "abcdef1234567890",
        "compose_service": "postgres",
    }
    assert_manifest_clean_of_secrets(clean_manifest)

    # Thử chèn các trường nhạy cảm
    sensitive_keys = [
        "password",
        "postgres_password",
        "client_secret",
        "firebase_token",
        "aws_secret_access_key",
        "user_credentials",
        "database_url",
    ]
    for k in sensitive_keys:
        bad_manifest = dict(clean_manifest)
        bad_manifest[k] = "secret_val"
        with pytest.raises(ValueError, match="BẢO MẬT: Manifest chứa trường nhạy cảm"):
            assert_manifest_clean_of_secrets(bad_manifest)


def test_compute_sha256(tmp_path: pathlib.Path):
    """Tính toán mã băm SHA-256 chính xác trên từng khối dữ liệu."""
    test_file = tmp_path / "sample.dump"
    content = b"PTITers Student Marketplace PostgreSQL Backup Test Content"
    test_file.write_bytes(content)

    expected_hash = hashlib.sha256(content).hexdigest()
    actual_hash = compute_sha256(test_file)
    assert actual_hash == expected_hash


def test_get_compose_cmd_with_compose_file():
    """Kiểm tra get_compose_cmd gắn thêm -f <compose_file> khi được cung cấp."""
    from unittest.mock import MagicMock, patch
    from scripts.db_backup import get_compose_cmd

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        cmd_default = get_compose_cmd()
        assert len(cmd_default) >= 1
        assert "compose" in cmd_default[-1] or "docker-compose" in cmd_default[0]

        cmd_custom = get_compose_cmd("docker-compose.prod.yml")
        assert "-f" in cmd_custom
        assert "docker-compose.prod.yml" in cmd_custom
        # Thứ tự: [docker, compose, -f, docker-compose.prod.yml]
        idx_f = cmd_custom.index("-f")
        assert cmd_custom[idx_f + 1] == "docker-compose.prod.yml"


def test_docker_compose_backward_compatibility():
    """Chế độ Docker Compose mặc định vẫn bảo toàn tương thích 100%."""
    from unittest.mock import MagicMock, patch
    from scripts.db_backup import query_postgres, verify_archive_toc

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="test_output\n", stderr="")
        res = query_postgres(
            "SELECT 1;",
            dbname="student_marketplace",
            user="postgres",
            service="postgres",
            direct=False,
        )
        assert res == "test_output"
        cmd = mock_run.call_args[0][0]
        # Phải là lệnh docker compose exec
        assert "exec" in cmd
        assert "-T" in cmd
        assert "postgres" in cmd
        assert "psql" in cmd


def test_direct_connection_command_construction():
    """Chế độ direct kết nối native qua psql/pg_dump/pg_restore với cờ host, port, user."""
    from unittest.mock import MagicMock, patch
    from scripts.db_backup import query_postgres

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="42\n", stderr="")
        res = query_postgres(
            "SELECT 42;",
            dbname="railway",
            user="postgres",
            direct=True,
            host="127.0.0.1",
            port=15432,
            password="test_password",
        )
        assert res == "42"
        cmd = mock_run.call_args[0][0]
        env = mock_run.call_args[1].get("env", {})

        # Kiểm tra danh sách tham số CLI psql
        assert cmd[0] == "psql"
        assert "-h" in cmd and cmd[cmd.index("-h") + 1] == "127.0.0.1"
        assert "-p" in cmd and cmd[cmd.index("-p") + 1] == "15432"
        assert "-U" in cmd and cmd[cmd.index("-U") + 1] == "postgres"
        assert "-d" in cmd and cmd[cmd.index("-d") + 1] == "railway"


def test_credentials_never_appear_in_command_arguments():
    """Mật khẩu tuyệt đối không nằm trong danh sách đối số command CLI hay manifest."""
    from unittest.mock import MagicMock, patch
    from scripts.db_backup import query_postgres

    secret_pw = "SuperSecretP@ssw0rd123!"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        query_postgres(
            "SELECT 1;",
            dbname="railway",
            user="postgres",
            direct=True,
            host="127.0.0.1",
            port=15432,
            password=secret_pw,
        )
        cmd = mock_run.call_args[0][0]
        env = mock_run.call_args[1].get("env", {})

        # Mật khẩu KHÔNG ĐƯỢC xuất hiện trong cmd
        for arg in cmd:
            assert secret_pw not in arg
        # Mật khẩu được truyền an toàn qua biến môi trường PGPASSWORD của tiến trình
        assert env.get("PGPASSWORD") == secret_pw


def test_version_gate_parse_server_major():
    """Trích xuất chính xác major version từ server banner và version_num."""
    from scripts.db_backup import parse_server_major

    # PostgreSQL 16
    assert parse_server_major("16.2 (Debian 16.2-1.pgdg120+1)", "160002") == 16
    assert parse_server_major("16.0", "160000") == 16

    # PostgreSQL 15
    assert parse_server_major("15.19", "150019") == 15
    assert parse_server_major("PostgreSQL 15.6 on x86_64", "") == 15

    # Trường hợp không có số
    with pytest.raises(ValueError, match="Không thể xác định phiên bản major"):
        parse_server_major("invalid_version_string", "")


def test_version_gate_compatibility_rules():
    """
    Quy tắc tương thích:
    - pg_dump cũ hơn server -> Hard failure (RuntimeError)
    - pg_dump khớp major -> Allowed
    - pg_dump mới hơn server -> Allowed with warning
    """
    from scripts.db_backup import check_pg_dump_compatibility

    # Khớp phiên bản -> Thành công
    check_pg_dump_compatibility(server_major=16, dump_major=16)
    check_pg_dump_compatibility(server_major=15, dump_major=15)

    # pg_dump mới hơn server -> Cho phép kèm cảnh báo
    check_pg_dump_compatibility(server_major=15, dump_major=16)

    # pg_dump cũ hơn server -> TỪ CHỐI CỨNG
    with pytest.raises(RuntimeError, match="TỪ CHỐI AN TOÀN - KHÔNG TƯƠNG THÍCH PHIÊN BẢN"):
        check_pg_dump_compatibility(server_major=16, dump_major=15)

    with pytest.raises(RuntimeError, match="TỪ CHỐI AN TOÀN - KHÔNG TƯƠNG THÍCH PHIÊN BẢN"):
        check_pg_dump_compatibility(server_major=17, dump_major=16)


def test_atomic_cleanup_on_pg_dump_failure(tmp_path: pathlib.Path):
    """Khi pg_dump gặp sự cố, tệp .dump.part phải bị xóa ngay lập tức và không tạo tệp .dump."""
    import argparse
    from unittest.mock import MagicMock, patch
    from scripts.db_backup import cmd_backup

    fake_args = argparse.Namespace(
        output_dir=str(tmp_path),
        service="postgres",
        compose_file=None,
        include_row_counts=False,
        direct=False,
        host=None,
    )

    with patch("scripts.db_backup.collect_database_metadata") as mock_meta, \
         patch("scripts.db_backup.parse_server_major", return_value=15), \
         patch("scripts.db_backup.get_pg_dump_major", return_value=15), \
         patch("scripts.db_backup.get_compose_cmd", return_value=["docker", "compose"]), \
         patch("subprocess.Popen") as mock_popen:

        mock_meta.return_value = {
            "postgres_version": "PostgreSQL 15.19",
            "server_version": "15.19",
            "server_version_num": "150019",
            "database_name": "test_db",
            "alembic_revision": "rev123",
            "application_table_count": 10,
            "physical_table_count": 11,
            "table_names": ["users"],
            "row_counts": {},
        }

        # Giả lập pg_dump thất bại (exit code 1)
        proc_mock = MagicMock()
        proc_mock.communicate.return_value = (b"", b"Connection refused by server")
        proc_mock.returncode = 1
        mock_popen.return_value = proc_mock

        with pytest.raises(RuntimeError, match="Lệnh pg_dump thất bại"):
            cmd_backup(fake_args)

        # Kiểm tra không có tệp .dump hay .part nào bị để lại
        dump_files = list(tmp_path.glob("*.dump*"))
        assert len(dump_files) == 0, f"Các tệp tạm chưa được thu dọn: {dump_files}"


def test_restore_drill_dynamic_expectations_and_source_isolation(tmp_path: pathlib.Path):
    """
    Restore drill đọc các mốc kỳ vọng hoàn toàn ĐỘNG từ manifest (không hardcode 32 hay rev cũ).
    Đặc biệt: Tuyệt đối KHÔNG gửi truy vấn vào source database trong suốt quá trình drill.
    """
    import argparse
    from unittest.mock import MagicMock, patch
    from scripts.db_backup import cmd_restore_drill

    # Tạo tệp dump giả và manifest giả
    dump_file = tmp_path / "test_backup.dump"
    dump_file.write_bytes(b"PGDMP_DUMMY_CONTENT")
    manifest_file = tmp_path / "test_backup.dump.manifest.json"

    manifest_data = {
        "manifest_version": 1,
        "database_name": "prod_railway_db",
        "postgres_version": "PostgreSQL 16.2",
        "alembic_revision": "dynamic_rev_999",
        "application_table_count": 45,
        "physical_table_count": 46,
        "dump_size_bytes": len(b"PGDMP_DUMMY_CONTENT"),
        "sha256": hashlib.sha256(b"PGDMP_DUMMY_CONTENT").hexdigest(),
        "table_names": [f"tbl_{i}" for i in range(45)],
        "row_counts": {f"tbl_{i}": 100 for i in range(45)},
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    args = argparse.Namespace(
        dump_file=str(dump_file),
        target_db="isolated_test_drill_db",
        keep_target=False,
        strict_row_counts=True,
        service="postgres",
        compose_file=None,
        direct=False,
        host=None,
    )

    with patch("scripts.db_backup.cmd_verify", return_value=0), \
         patch("scripts.db_backup.get_container_env", return_value="postgres"), \
         patch("subprocess.run") as mock_run, \
         patch("scripts.db_backup.collect_database_metadata") as mock_collect:

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # Giả lập target DB được khôi phục khớp hoàn hảo các giá trị động từ manifest
        mock_collect.return_value = {
            "postgres_version": "PostgreSQL 16.2",
            "server_version": "16.2",
            "server_version_num": "160002",
            "database_name": "isolated_test_drill_db",
            "alembic_revision": "dynamic_rev_999",
            "application_table_count": 45,
            "physical_table_count": 46,
            "table_names": [f"tbl_{i}" for i in range(45)],
            "row_counts": {f"tbl_{i}": 100 for i in range(45)},
        }

        ret = cmd_restore_drill(args)
        assert ret == 0

        # Kiểm tra collect_database_metadata CHỈ được gọi cho target_db, KHÔNG BAO GIỜ gọi cho prod_railway_db
        called_dbs = [call[0][1] for call in mock_collect.call_args_list]
        assert "prod_railway_db" not in called_dbs
        assert "isolated_test_drill_db" in called_dbs


def test_row_counts_informational_vs_strict(tmp_path: pathlib.Path):
    """
    Kiểm thử hành vi snapshot số dòng:
    - Khi có lệch số dòng: chế độ mặc định (informational) chỉ cảnh báo và PASS.
    - Chế độ --strict-row-counts sẽ raise ValueError để bảo vệ kiểm thử dev.
    """
    import argparse
    from unittest.mock import MagicMock, patch
    from scripts.db_backup import cmd_restore_drill

    dump_file = tmp_path / "test_snapshot.dump"
    dump_file.write_bytes(b"PGDMP_DUMMY")
    manifest_file = tmp_path / "test_snapshot.dump.manifest.json"

    manifest_data = {
        "manifest_version": 1,
        "database_name": "live_source_db",
        "postgres_version": "PostgreSQL 16.2",
        "alembic_revision": "rev_stable",
        "application_table_count": 2,
        "physical_table_count": 3,
        "dump_size_bytes": len(b"PGDMP_DUMMY"),
        "sha256": hashlib.sha256(b"PGDMP_DUMMY").hexdigest(),
        "table_names": ["users", "orders"],
        "row_counts": {"users": 100, "orders": 50},
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    # Giả lập target DB có 102 users do concurrent insert trước khi dump cắt transaction
    mismatched_target_meta = {
        "postgres_version": "PostgreSQL 16.2",
        "server_version": "16.2",
        "server_version_num": "160002",
        "database_name": "isolated_drill_db",
        "alembic_revision": "rev_stable",
        "application_table_count": 2,
        "physical_table_count": 3,
        "table_names": ["users", "orders"],
        "row_counts": {"users": 102, "orders": 50},
    }

    # Case 1: Mặc định (Informational) -> PASS không raise lỗi
    args_info = argparse.Namespace(
        dump_file=str(dump_file),
        target_db="isolated_drill_db",
        keep_target=False,
        strict_row_counts=False,
        service="postgres",
        compose_file=None,
        direct=False,
        host=None,
    )

    with patch("scripts.db_backup.cmd_verify", return_value=0), \
         patch("scripts.db_backup.get_container_env", return_value="postgres"), \
         patch("subprocess.run", return_value=MagicMock(returncode=0)), \
         patch("scripts.db_backup.collect_database_metadata", return_value=mismatched_target_meta):

        ret = cmd_restore_drill(args_info)
        assert ret == 0

    # Case 2: Strict row counts -> FAIL (raise ValueError)
    args_strict = argparse.Namespace(
        dump_file=str(dump_file),
        target_db="isolated_drill_db",
        keep_target=False,
        strict_row_counts=True,
        service="postgres",
        compose_file=None,
        direct=False,
        host=None,
    )

    with patch("scripts.db_backup.cmd_verify", return_value=0), \
         patch("scripts.db_backup.get_container_env", return_value="postgres"), \
         patch("subprocess.run", return_value=MagicMock(returncode=0)), \
         patch("scripts.db_backup.collect_database_metadata", return_value=mismatched_target_meta):

        with pytest.raises(ValueError, match=r"\[LỖI STRICT ROW COUNTS\]"):
            cmd_restore_drill(args_strict)


def test_manifest_evidence_fields_preserved(tmp_path: pathlib.Path):
    """Bảo đảm manifest lưu giữ đầy đủ 100% các trường chứng cứ pháp lý kỹ thuật cần thiết."""
    import argparse
    from unittest.mock import MagicMock, patch
    from scripts.db_backup import cmd_backup

    args = argparse.Namespace(
        output_dir=str(tmp_path),
        service="postgres",
        compose_file=None,
        include_row_counts=True,
        direct=True,
        host="127.0.0.1",
        port=15432,
        user="test_operator",
        dbname="railway",
    )

    with patch("scripts.db_backup.collect_database_metadata") as mock_meta, \
         patch("scripts.db_backup.parse_server_major", return_value=16), \
         patch("scripts.db_backup.get_pg_dump_major", return_value=16), \
         patch("scripts.db_backup.verify_archive_toc", return_value=(True, 350, "")), \
         patch("subprocess.Popen") as mock_popen:

        mock_meta.return_value = {
            "postgres_version": "PostgreSQL 16.2 on x86_64",
            "server_version": "16.2",
            "server_version_num": "160002",
            "database_name": "railway",
            "alembic_revision": "f1a2b3c4d5e6",
            "application_table_count": 32,
            "physical_table_count": 33,
            "table_names": ["users", "products"],
            "row_counts": {"users": 10, "products": 20},
        }

        proc_mock = MagicMock()
        proc_mock.communicate.return_value = (b"", b"")
        proc_mock.returncode = 0
        mock_popen.return_value = proc_mock

        ret = cmd_backup(args)
        assert ret == 0

        manifests = list(tmp_path.glob("*.manifest.json"))
        assert len(manifests) == 1
        with open(manifests[0], "r", encoding="utf-8") as fm:
            data = json.load(fm)

        # Kiểm tra đầy đủ các trường evidence
        assert data["manifest_version"] == 1
        assert "created_at_utc" in data
        assert data["backup_format"] == "postgres-custom"
        assert data["database_name"] == "railway"
        assert data["postgres_version"] == "PostgreSQL 16.2 on x86_64"
        assert data["server_version"] == "16.2"
        assert data["server_version_num"] == "160002"
        assert data["alembic_revision"] == "f1a2b3c4d5e6"
        assert data["application_table_count"] == 32
        assert data["physical_table_count"] == 33
        assert "dump_size_bytes" in data
        assert "sha256" in data
        assert data["archive_toc_items"] == 350
        assert data["table_names"] == ["users", "products"]
        assert data["row_counts"] == {"users": 10, "products": 20}
        assert data["row_counts_mode"] == "informational"
        assert data["connection_mode"] == "direct"
        assert data["host"] == "127.0.0.1"
        assert data["port"] == 15432
