"""
Unit tests for Remote PostgreSQL Backup & Cloudflare R2 Retention Tool (scripts/db_backup_remote.py).
Bao phủ các ca kiểm thử: upload cặp tệp nguyên tử, xác thực kích thước, xử lý tệp mồ côi,
quy tắc retention 14 ngày + 4 tuần, bảo vệ bản sao lưu mới nhất, và an toàn credential.
Toàn bộ kiểm thử sử dụng mocks/fakes, tuyệt đối không kết nối dịch vụ ngoài.
"""

import datetime
import pathlib
from unittest.mock import MagicMock, patch

import pytest

from scripts.db_backup_remote import (
    RemoteBackupSet,
    apply_retention,
    get_r2_config,
    list_remote_backup_sets,
    parse_timestamp_from_base_name,
    sanitize_message,
    select_backup_sets_for_retention,
    upload_backup_set,
)


def test_sanitize_message_redacts_credentials(monkeypatch):
    """Đảm bảo các bí mật như PGPASSWORD, R2_SECRET_ACCESS_KEY bị che giấu khỏi thông điệp log."""
    monkeypatch.setenv("PGPASSWORD", "UltraSecretDbPassword999!")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "r2_super_secret_token_abc123")

    raw_msg = (
        "Lỗi kết nối: password 'UltraSecretDbPassword999!' không hợp lệ "
        "khi xác thực token 'r2_super_secret_token_abc123'"
    )
    cleaned = sanitize_message(raw_msg)
    assert "UltraSecretDbPassword999!" not in cleaned
    assert "r2_super_secret_token_abc123" not in cleaned
    assert "[REDACTED]" in cleaned


def test_get_r2_config_success(monkeypatch):
    """Cấu hình R2 được đọc chính xác từ biến môi trường."""
    monkeypatch.setenv("R2_BUCKET_NAME", "choptiters-backups")
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://account123.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key_id_456")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret_key_789")
    monkeypatch.setenv("R2_PREFIX", "custom-backups")

    conf = get_r2_config()
    assert conf["bucket_name"] == "choptiters-backups"
    assert conf["endpoint_url"] == "https://account123.r2.cloudflarestorage.com"
    assert conf["access_key_id"] == "key_id_456"
    assert conf["secret_access_key"] == "secret_key_789"
    assert conf["prefix"] == "custom-backups/"


def test_get_r2_config_missing_vars_raises_value_error(monkeypatch):
    """Thiếu bất kỳ biến môi trường cấu hình R2 bắt buộc nào phải ném ValueError rõ ràng."""
    monkeypatch.delenv("R2_BUCKET_NAME", raising=False)
    monkeypatch.delenv("S3_BUCKET_NAME", raising=False)
    monkeypatch.delenv("R2_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)

    with pytest.raises(ValueError, match="Thiếu các biến môi trường cấu hình R2/S3 bắt buộc"):
        get_r2_config()


def test_upload_backup_set_complete_success(tmp_path: pathlib.Path):
    """Tải thành công cả dump và manifest lên R2 STANDARD storage và xác thực kích thước."""
    dump_file = tmp_path / "railway_20261001T200000Z.dump"
    dump_file.write_bytes(b"DUMP_CONTENT_BYTES_12345")
    manifest_file = tmp_path / "railway_20261001T200000Z.dump.manifest.json"
    manifest_file.write_text('{"manifest_version": 1}', encoding="utf-8")

    mock_s3 = MagicMock()
    # Giả lập head_object trả về kích thước khớp 100%
    mock_s3.head_object.side_effect = [
        {"ContentLength": len(b"DUMP_CONTENT_BYTES_12345")},
        {"ContentLength": len('{"manifest_version": 1}'.encode("utf-8"))},
    ]

    remote_set = upload_backup_set(
        s3_client=mock_s3,
        bucket_name="test-bucket",
        dump_path=dump_file,
        manifest_path=manifest_file,
        prefix="backups/",
    )

    assert remote_set.base_name == "railway_20261001T200000Z"
    assert remote_set.dump_key == "backups/railway_20261001T200000Z.dump"
    assert remote_set.manifest_key == "backups/railway_20261001T200000Z.dump.manifest.json"
    assert remote_set.dump_size_bytes == len(b"DUMP_CONTENT_BYTES_12345")

    # Kiểm tra upload_file được gọi đúng với StorageClass: STANDARD
    assert mock_s3.upload_file.call_count == 2
    dump_call_kwargs = mock_s3.upload_file.call_args_list[0].kwargs
    assert dump_call_kwargs.get("ExtraArgs") == {"StorageClass": "STANDARD"}
    manifest_call_kwargs = mock_s3.upload_file.call_args_list[1].kwargs
    assert manifest_call_kwargs.get("ExtraArgs") == {"StorageClass": "STANDARD"}


def test_upload_backup_set_dump_failure(tmp_path: pathlib.Path):
    """Nếu tải dump thất bại, tiến trình ném lỗi và không tải manifest."""
    dump_file = tmp_path / "railway_20261001T200000Z.dump"
    dump_file.write_bytes(b"DUMP_CONTENT")
    manifest_file = tmp_path / "railway_20261001T200000Z.dump.manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")

    mock_s3 = MagicMock()
    mock_s3.upload_file.side_effect = RuntimeError("S3 Network Connection Timeout")

    with pytest.raises(RuntimeError, match="Tải tệp dump thất bại"):
        upload_backup_set(
            s3_client=mock_s3,
            bucket_name="test-bucket",
            dump_path=dump_file,
            manifest_path=manifest_file,
            prefix="backups/",
        )

    # Manifest không được tải nếu dump thất bại
    assert mock_s3.upload_file.call_count == 1


def test_upload_backup_set_manifest_failure(tmp_path: pathlib.Path):
    """Nếu dump tải thành công nhưng manifest thất bại, toàn bộ quá trình bị đánh dấu thất bại."""
    dump_file = tmp_path / "railway_20261001T200000Z.dump"
    dump_file.write_bytes(b"DUMP_CONTENT")
    manifest_file = tmp_path / "railway_20261001T200000Z.dump.manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")

    mock_s3 = MagicMock()
    # Call 1 (dump) thành công, Call 2 (manifest) thất bại
    mock_s3.upload_file.side_effect = [None, RuntimeError("Access Denied on manifest")]

    with pytest.raises(RuntimeError, match="Tải tệp manifest thất bại"):
        upload_backup_set(
            s3_client=mock_s3,
            bucket_name="test-bucket",
            dump_path=dump_file,
            manifest_path=manifest_file,
            prefix="backups/",
        )


def test_upload_backup_set_remote_size_mismatch_failure(tmp_path: pathlib.Path):
    """Nếu head_object phát hiện kích thước remote lệch local, ném RuntimeError."""
    dump_file = tmp_path / "railway_20261001T200000Z.dump"
    dump_file.write_bytes(b"1234567890")
    manifest_file = tmp_path / "railway_20261001T200000Z.dump.manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")

    mock_s3 = MagicMock()
    # Trả về kích thước remote 5 bytes trong khi local là 10 bytes
    mock_s3.head_object.return_value = {"ContentLength": 5}

    with pytest.raises(RuntimeError, match="Kích thước remote dump lệch với local"):
        upload_backup_set(
            s3_client=mock_s3,
            bucket_name="test-bucket",
            dump_path=dump_file,
            manifest_path=manifest_file,
            prefix="backups/",
        )


def test_list_remote_backup_sets_handles_orphans_and_malformed():
    """Chỉ công nhận các cặp có đủ cả .dump và .dump.manifest.json; tệp mồ côi và dị vật bị bỏ qua."""
    mock_s3 = MagicMock()
    paginator_mock = MagicMock()
    mock_s3.get_paginator.return_value = paginator_mock

    # Giả lập danh sách đối tượng trong bucket:
    # 1. Cặp hợp lệ A: railway_20261001T200000Z
    # 2. Cặp hợp lệ B: railway_20261002T200000Z
    # 3. Tệp mồ côi: orphan_no_manifest_20261003T200000Z.dump
    # 4. Tệp mồ côi: orphan_no_dump_20261004T200000Z.dump.manifest.json
    # 5. Dị vật / malformed: random_notes.txt, logs/app.log
    paginator_mock.paginate.return_value = [
        {
            "Contents": [
                {"Key": "backups/railway_20261001T200000Z.dump", "Size": 1000},
                {"Key": "backups/railway_20261001T200000Z.dump.manifest.json", "Size": 200},
                {"Key": "backups/railway_20261002T200000Z.dump", "Size": 1050},
                {"Key": "backups/railway_20261002T200000Z.dump.manifest.json", "Size": 210},
                {"Key": "backups/orphan_20261003T200000Z.dump", "Size": 500},
                {"Key": "backups/orphan_20261004T200000Z.dump.manifest.json", "Size": 100},
                {"Key": "backups/random_notes.txt", "Size": 50},
                {"Key": "backups/bad_timestamp.dump", "Size": 200},
                {"Key": "backups/bad_timestamp.dump.manifest.json", "Size": 50},
            ]
        }
    ]

    valid_sets = list_remote_backup_sets(mock_s3, bucket_name="test-bucket", prefix="backups/")
    assert len(valid_sets) == 2
    assert valid_sets[0].base_name == "railway_20261001T200000Z"
    assert valid_sets[1].base_name == "railway_20261002T200000Z"


def test_retention_skipped_if_no_newly_verified_backup():
    """Nếu không có bản sao lưu mới được xác nhận trong phiên chạy (newest_verified=None) -> Không xóa gì."""
    dt_now = datetime.datetime(2026, 10, 15, 20, 0, 0, tzinfo=datetime.timezone.utc)
    set1 = RemoteBackupSet("b1", "b1.dump", "b1.manifest", dt_now - datetime.timedelta(days=30), 100, 10)
    set2 = RemoteBackupSet("b2", "b2.dump", "b2.manifest", dt_now - datetime.timedelta(days=20), 100, 10)

    to_delete = select_backup_sets_for_retention([set1, set2], newest_verified=None, now_utc=dt_now)
    assert to_delete == []


def test_retention_skipped_if_single_or_zero_backup():
    """Nếu chỉ có <= 1 cặp bản sao lưu trong hệ thống -> Tuyệt đối không xóa."""
    dt_now = datetime.datetime(2026, 10, 15, 20, 0, 0, tzinfo=datetime.timezone.utc)
    set1 = RemoteBackupSet("b1", "b1.dump", "b1.manifest", dt_now - datetime.timedelta(days=30), 100, 10)

    # 1 backup duy nhất
    to_delete = select_backup_sets_for_retention([set1], newest_verified=set1, now_utc=dt_now)
    assert to_delete == []

    # 0 backup
    to_delete_empty = select_backup_sets_for_retention([], newest_verified=None, now_utc=dt_now)
    assert to_delete_empty == []


def test_retention_newest_verified_never_deleted():
    """Bản sao lưu mới nhất (newest verified pair) TUYỆT ĐỐI KHÔNG BAO GIỜ bị đưa vào danh sách xóa."""
    dt_now = datetime.datetime(2026, 10, 15, 20, 0, 0, tzinfo=datetime.timezone.utc)
    # Giả lập tình huống bất thường: cả 2 bản đều rất cũ, nhưng bản mới hơn vẫn là newest
    set1 = RemoteBackupSet("old_1", "old_1.dump", "old_1.manifest", dt_now - datetime.timedelta(days=100), 100, 10)
    set2 = RemoteBackupSet("old_2_newest", "old_2.dump", "old_2.manifest", dt_now - datetime.timedelta(days=50), 100, 10)

    to_delete = select_backup_sets_for_retention([set1, set2], newest_verified=set2, now_utc=dt_now)

    # old_2_newest KHÔNG ĐƯỢC PHÉP bị xóa
    deleted_names = [s.base_name for s in to_delete]
    assert "old_2_newest" not in deleted_names
    assert "old_1" in deleted_names


def test_retention_14_daily_and_4_weekly_behavior():
    """
    Kiểm thử hành vi lưu giữ toàn diện:
    - 14 ngày gần nhất: Giữ 100% bản hàng ngày (14 bản).
    - 4 tuần tiếp theo (14 - 42 ngày): Giữ 1 bản/tuần (tối đa 4 bản tuần).
    - Bản cũ hơn 42 ngày: Bị xóa toàn bộ.
    """
    dt_now = datetime.datetime(2026, 10, 30, 20, 0, 0, tzinfo=datetime.timezone.utc)
    all_sets = []

    # Tạo 14 bản sao lưu hàng ngày (từ ngày 0 đến 13)
    for day in range(14):
        ts = dt_now - datetime.timedelta(days=day)
        name = f"daily_day_{day}_{ts.strftime('%Y%m%dT%H%M%SZ')}"
        all_sets.append(RemoteBackupSet(name, f"{name}.dump", f"{name}.manifest", ts, 100, 10))

    # Tạo các bản trong khoảng 14 - 42 ngày (4 tuần):
    # Tuần 42 (15 và 17 ngày trước): 2 bản trong cùng tuần -> Giữ bản mới hơn (15 ngày), xóa bản cũ hơn (17 ngày)
    ts_w1_old = dt_now - datetime.timedelta(days=17)
    ts_w1_new = dt_now - datetime.timedelta(days=15)
    name_w1_old = f"w1_old_{ts_w1_old.strftime('%Y%m%dT%H%M%SZ')}"
    name_w1_new = f"w1_new_{ts_w1_new.strftime('%Y%m%dT%H%M%SZ')}"
    all_sets.append(RemoteBackupSet(name_w1_old, f"{name_w1_old}.dump", f"{name_w1_old}.manifest", ts_w1_old, 100, 10))
    all_sets.append(RemoteBackupSet(name_w1_new, f"{name_w1_new}.dump", f"{name_w1_new}.manifest", ts_w1_new, 100, 10))

    # Tuần 41 (23 ngày trước): 1 bản
    ts_w2 = dt_now - datetime.timedelta(days=23)
    name_w2 = f"w2_{ts_w2.strftime('%Y%m%dT%H%M%SZ')}"
    all_sets.append(RemoteBackupSet(name_w2, f"{name_w2}.dump", f"{name_w2}.manifest", ts_w2, 100, 10))

    # Tuần 40 (30 ngày trước): 1 bản
    ts_w3 = dt_now - datetime.timedelta(days=30)
    name_w3 = f"w3_{ts_w3.strftime('%Y%m%dT%H%M%SZ')}"
    all_sets.append(RemoteBackupSet(name_w3, f"{name_w3}.dump", f"{name_w3}.manifest", ts_w3, 100, 10))

    # Tuần 39 (37 ngày trước): 1 bản
    ts_w4 = dt_now - datetime.timedelta(days=37)
    name_w4 = f"w4_{ts_w4.strftime('%Y%m%dT%H%M%SZ')}"
    all_sets.append(RemoteBackupSet(name_w4, f"{name_w4}.dump", f"{name_w4}.manifest", ts_w4, 100, 10))

    # Bản quá cũ (> 42 ngày, ví dụ 50 ngày và 60 ngày): Bắt buộc bị xóa
    ts_old1 = dt_now - datetime.timedelta(days=50)
    name_old1 = f"old1_{ts_old1.strftime('%Y%m%dT%H%M%SZ')}"
    all_sets.append(RemoteBackupSet(name_old1, f"{name_old1}.dump", f"{name_old1}.manifest", ts_old1, 100, 10))

    ts_old2 = dt_now - datetime.timedelta(days=60)
    name_old2 = f"old2_{ts_old2.strftime('%Y%m%dT%H%M%SZ')}"
    all_sets.append(RemoteBackupSet(name_old2, f"{name_old2}.dump", f"{name_old2}.manifest", ts_old2, 100, 10))

    newest_pair = all_sets[0]  # day 0
    to_delete = select_backup_sets_for_retention(all_sets, newest_verified=newest_pair, now_utc=dt_now)
    del_names = {s.base_name for s in to_delete}

    # Kiểm tra: 14 bản daily KHÔNG bản nào bị xóa
    for day in range(14):
        assert f"daily_day_{day}" not in "".join(del_names)

    # Kiểm tra: Trong tuần 42, bản cũ hơn (w1_old) bị xóa, bản mới hơn (w1_new) được giữ
    assert name_w1_old in del_names
    assert name_w1_new not in del_names

    # Kiểm tra: W2, W3, W4 được giữ lại
    assert name_w2 not in del_names
    assert name_w3 not in del_names
    assert name_w4 not in del_names

    # Kiểm tra: Các bản > 42 ngày bị xóa
    assert name_old1 in del_names
    assert name_old2 in del_names


def test_apply_retention_deletes_both_dump_and_manifest():
    """apply_retention gọi delete_object cho CẢ tệp dump và manifest tương ứng."""
    mock_s3 = MagicMock()
    dt_now = datetime.datetime.now(datetime.timezone.utc)
    set_to_del = RemoteBackupSet(
        base_name="expired_backup",
        dump_key="backups/expired_backup.dump",
        manifest_key="backups/expired_backup.dump.manifest.json",
        timestamp_utc=dt_now,
        dump_size_bytes=5000,
        manifest_size_bytes=200,
    )

    deleted_count = apply_retention(mock_s3, bucket_name="test-bucket", to_delete=[set_to_del])
    assert deleted_count == 1
    assert mock_s3.delete_object.call_count == 2
    mock_s3.delete_object.assert_any_call(Bucket="test-bucket", Key="backups/expired_backup.dump")
    mock_s3.delete_object.assert_any_call(Bucket="test-bucket", Key="backups/expired_backup.dump.manifest.json")


def test_pipeline_fail_closed_skips_retention_on_upload_error(tmp_path: pathlib.Path, monkeypatch):
    """Khi upload gặp sự cố, chu trình pipeline bị hủy (raise lỗi), retention hoàn toàn KHÔNG ĐƯỢC CHẠY."""
    import argparse
    from scripts.db_backup_remote import cmd_run_pipeline

    monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://fake.r2.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")

    # Tạo tệp dump giả trong tmp_path
    dump_file = tmp_path / "railway_20261001T200000Z.dump"
    dump_file.write_bytes(b"DUMP")
    manifest_file = tmp_path / "railway_20261001T200000Z.dump.manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")

    args = argparse.Namespace(
        output_dir=str(tmp_path),
        cleanup_local=False,
    )

    with patch("scripts.db_backup.cmd_backup", return_value=0), \
         patch("scripts.db_backup.cmd_verify", return_value=0), \
         patch("scripts.db_backup_remote.create_s3_client") as mock_client_factory, \
         patch("scripts.db_backup_remote.apply_retention") as mock_retention:

        mock_s3 = MagicMock()
        mock_client_factory.return_value = mock_s3
        # Giả lập upload_file thất bại
        mock_s3.upload_file.side_effect = RuntimeError("R2 Network Dropped")

        with pytest.raises(RuntimeError, match="Tải tệp dump thất bại"):
            cmd_run_pipeline(args)

        # Retention KHÔNG BAO GIỜ ĐƯỢC GỌI
        assert mock_retention.call_count == 0


def test_pipeline_success_end_to_end_mocked(tmp_path: pathlib.Path, monkeypatch):
    """Khi backup, verify và upload thành công, retention được áp dụng và dọn dẹp an toàn."""
    import argparse
    from scripts.db_backup_remote import cmd_run_pipeline

    monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://fake.r2.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")

    dump_file = tmp_path / "railway_20261001T200000Z.dump"
    dump_file.write_bytes(b"DUMP_CONTENT_OK")
    manifest_file = tmp_path / "railway_20261001T200000Z.dump.manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")

    args = argparse.Namespace(
        output_dir=str(tmp_path),
        cleanup_local=True,
    )

    with patch("scripts.db_backup.cmd_backup", return_value=0), \
         patch("scripts.db_backup.cmd_verify", return_value=0), \
         patch("scripts.db_backup_remote.create_s3_client") as mock_client_factory, \
         patch("scripts.db_backup_remote.apply_retention", return_value=0) as mock_retention:

        mock_s3 = MagicMock()
        mock_client_factory.return_value = mock_s3
        mock_s3.head_object.side_effect = [
            {"ContentLength": len(b"DUMP_CONTENT_OK")},
            {"ContentLength": len(b"{}")},
        ]
        paginator_mock = MagicMock()
        paginator_mock.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "backups/railway_20261001T200000Z.dump", "Size": len(b"DUMP_CONTENT_OK")},
                    {"Key": "backups/railway_20261001T200000Z.dump.manifest.json", "Size": len(b"{}")},
                ]
            }
        ]
        mock_s3.get_paginator.return_value = paginator_mock

        rc = cmd_run_pipeline(args)
        assert rc == 0
        assert mock_retention.call_count == 1
        # cleanup_local=True đã xóa dump và manifest tạm
        assert not dump_file.exists()
        assert not manifest_file.exists()


def test_main_run_pipeline_success_exit_code_0(monkeypatch):
    """Hàm main() trả về 0 khi pipeline chạy thành công."""
    from scripts.db_backup_remote import main

    monkeypatch.setattr("sys.argv", ["db_backup_remote.py", "run-pipeline"])
    with patch("scripts.db_backup_remote.cmd_run_pipeline", return_value=0):
        rc = main()
        assert rc == 0


def test_main_failure_returns_exit_code_1_with_error_marker(capsys, monkeypatch):
    """Hàm main() trả về 1 khi gặp lỗi và in ra marker lỗi chuẩn hóa."""
    from scripts.db_backup_remote import main

    monkeypatch.setattr("sys.argv", ["db_backup_remote.py", "run-pipeline"])
    with patch("scripts.db_backup_remote.cmd_run_pipeline", side_effect=RuntimeError("Database dump failed")):
        rc = main()
        assert rc == 1
        captured = capsys.readouterr()
        assert "[!] LỖI THỰC THI (REMOTE BACKUP):" in captured.err
        assert "Database dump failed" in captured.err

