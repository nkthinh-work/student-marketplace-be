import json
import logging
from unittest.mock import patch, MagicMock
import pytest
import firebase_admin
from firebase_admin import credentials

from app.core.config import settings
from app.integrations.firebase import (
    init_firebase,
    verify_firebase_token,
    FirebaseNotInitializedError,
    FirebaseVerificationError,
)


@pytest.fixture(autouse=True)
def reset_firebase_state():
    """Ensure clean firebase_admin._apps and restored settings for each test."""
    original_apps = dict(firebase_admin._apps)
    original_path = settings.FIREBASE_CREDENTIALS_PATH
    original_json = settings.FIREBASE_CREDENTIALS_JSON
    firebase_admin._apps.clear()
    yield
    firebase_admin._apps.clear()
    firebase_admin._apps.update(original_apps)
    settings.FIREBASE_CREDENTIALS_PATH = original_path
    settings.FIREBASE_CREDENTIALS_JSON = original_json


def test_firebase_init_with_json_credentials():
    """Test A: Valid JSON credentials configured -> parsed to dict and passed to Certificate."""
    sample_cred = {
        "type": "service_account",
        "project_id": "test-project-123",
        "private_key_id": "key123",
        "client_email": "test@test-project-123.iam.gserviceaccount.com",
    }
    settings.FIREBASE_CREDENTIALS_JSON = json.dumps(sample_cred)
    settings.FIREBASE_CREDENTIALS_PATH = None

    mock_cert_instance = MagicMock()
    with patch("firebase_admin.credentials.Certificate", return_value=mock_cert_instance) as mock_cert:
        with patch("firebase_admin.initialize_app") as mock_init:
            init_firebase()

            mock_cert.assert_called_once()
            called_arg = mock_cert.call_args[0][0]
            assert isinstance(called_arg, dict)
            assert called_arg == sample_cred
            mock_init.assert_called_once_with(mock_cert_instance)


def test_firebase_json_takes_precedence_over_path():
    """Test B: When both JSON and PATH exist, JSON credentials take precedence."""
    sample_cred = {"type": "service_account", "project_id": "json-precedence-project"}
    settings.FIREBASE_CREDENTIALS_JSON = json.dumps(sample_cred)
    settings.FIREBASE_CREDENTIALS_PATH = "/dummy/filesystem/path.json"

    mock_cert_instance = MagicMock()
    with patch("firebase_admin.credentials.Certificate", return_value=mock_cert_instance) as mock_cert:
        with patch("firebase_admin.initialize_app") as mock_init:
            init_firebase()

            mock_cert.assert_called_once()
            called_arg = mock_cert.call_args[0][0]
            # Must be the dict from JSON, not the file path string
            assert isinstance(called_arg, dict)
            assert called_arg == sample_cred
            mock_init.assert_called_once_with(mock_cert_instance)


def test_firebase_init_with_path_only():
    """Test C: PATH-only configuration preserves backward compatibility."""
    settings.FIREBASE_CREDENTIALS_JSON = None
    settings.FIREBASE_CREDENTIALS_PATH = "/app/secrets/firebase-service-account.json"

    mock_cert_instance = MagicMock()
    with patch("firebase_admin.credentials.Certificate", return_value=mock_cert_instance) as mock_cert:
        with patch("firebase_admin.initialize_app") as mock_init:
            init_firebase()

            mock_cert.assert_called_once_with("/app/secrets/firebase-service-account.json")
            mock_init.assert_called_once_with(mock_cert_instance)


def test_firebase_neither_configured_graceful_degradation(caplog):
    """Test D: Neither JSON nor PATH configured -> no crash, logs warning, Firebase remains unavailable."""
    settings.FIREBASE_CREDENTIALS_JSON = None
    settings.FIREBASE_CREDENTIALS_PATH = None

    with caplog.at_level(logging.WARNING):
        init_firebase()

    assert not firebase_admin._apps
    assert "Firebase credentials not configured" in caplog.text

    # verify_firebase_token should fail with FirebaseNotInitializedError
    with pytest.raises(FirebaseNotInitializedError) as exc_info:
        verify_firebase_token("dummy-token")
    assert "Firebase Authentication service is not initialized" in str(exc_info.value)


@pytest.mark.parametrize(
    "malformed_value,expected_error_log",
    [
        (
            '{"type": "service_account", "private_key": "-----BEGIN SENSITIVE SECRET-----", invalid_json',
            "Failed to parse FIREBASE_CREDENTIALS_JSON: Invalid JSON syntax.",
        ),
        (
            '["not", "a", "json", "object"]',
            "FIREBASE_CREDENTIALS_JSON is not a valid JSON object.",
        ),
    ],
)
def test_firebase_malformed_json_handling_and_no_leak(malformed_value, expected_error_log, caplog):
    """Test E: Malformed JSON -> no crash, no secret leaked into logs, Firebase remains unavailable."""
    settings.FIREBASE_CREDENTIALS_JSON = malformed_value
    settings.FIREBASE_CREDENTIALS_PATH = None

    with caplog.at_level(logging.DEBUG):
        init_firebase()

    # Application did not crash and no app was initialized
    assert not firebase_admin._apps
    # Verify expected safe log message
    assert expected_error_log in caplog.text
    # Verify NO sensitive secret string leaked into any log message
    assert "SENSITIVE SECRET" not in caplog.text
    assert malformed_value not in caplog.text


def test_firebase_lazy_initialization_with_json_only():
    """Test F: verify_firebase_token performs lazy initialization when only FIREBASE_CREDENTIALS_JSON is set."""
    sample_cred = {"type": "service_account", "project_id": "lazy-project"}
    settings.FIREBASE_CREDENTIALS_JSON = json.dumps(sample_cred)
    settings.FIREBASE_CREDENTIALS_PATH = None

    assert not firebase_admin._apps

    fake_app = MagicMock()
    with patch("firebase_admin.credentials.Certificate") as mock_cert:
        with patch("firebase_admin.initialize_app") as mock_init:
            def side_effect_init(cred):
                firebase_admin._apps["[DEFAULT]"] = fake_app
                return fake_app

            mock_init.side_effect = side_effect_init

            with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "user_lazy_123", "email": "lazy@ptit.edu.vn"}):
                decoded = verify_firebase_token("valid-bearer-token")
                assert decoded["uid"] == "user_lazy_123"
                assert decoded["email"] == "lazy@ptit.edu.vn"

                mock_cert.assert_called_once_with(sample_cred)
                mock_init.assert_called_once()
