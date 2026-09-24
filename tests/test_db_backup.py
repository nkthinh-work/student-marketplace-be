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
    from scripts.db_backup import get_compose_cmd

    cmd_default = get_compose_cmd()
    assert len(cmd_default) >= 1
    assert "compose" in cmd_default[-1] or "docker-compose" in cmd_default[0]

    cmd_custom = get_compose_cmd("docker-compose.prod.yml")
    assert "-f" in cmd_custom
    assert "docker-compose.prod.yml" in cmd_custom
    # Thứ tự: [docker, compose, -f, docker-compose.prod.yml]
    idx_f = cmd_custom.index("-f")
    assert cmd_custom[idx_f + 1] == "docker-compose.prod.yml"
