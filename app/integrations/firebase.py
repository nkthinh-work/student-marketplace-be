import json
import logging
from typing import Any, Optional
import firebase_admin
from firebase_admin import credentials, auth
from app.core.config import settings

logger = logging.getLogger("app")


class FirebaseVerificationError(Exception):
    """Exception raised when Firebase token verification fails."""
    pass


class FirebaseNotInitializedError(Exception):
    """Exception raised when Firebase is called but not configured."""
    pass


def init_firebase() -> None:
    if firebase_admin._apps:
        return

    # Ưu tiên 1: FIREBASE_CREDENTIALS_JSON (phù hợp cho Railway / cloud environment)
    if settings.FIREBASE_CREDENTIALS_JSON and settings.FIREBASE_CREDENTIALS_JSON.strip():
        try:
            cred_data = json.loads(settings.FIREBASE_CREDENTIALS_JSON)
            if not isinstance(cred_data, dict):
                logger.error("FIREBASE_CREDENTIALS_JSON is not a valid JSON object.")
                return
            cred = credentials.Certificate(cred_data)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin SDK successfully initialized from JSON.")
            return
        except json.JSONDecodeError:
            logger.error("Failed to parse FIREBASE_CREDENTIALS_JSON: Invalid JSON syntax.")
            return
        except Exception as e:
            # Tuyệt đối không log nội dung của credential JSON hay private key
            logger.error(f"Error initializing Firebase Admin SDK from JSON: {type(e).__name__}")
            return

    # Ưu tiên 2: FIREBASE_CREDENTIALS_PATH (phù hợp cho môi trường local/file-based)
    if settings.FIREBASE_CREDENTIALS_PATH:
        try:
            cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin SDK successfully initialized from path.")
        except Exception as e:
            logger.error(f"Error initializing Firebase Admin SDK from path: {e}")
        return

    # Nếu cả hai đều không được cấu hình
    logger.warning(
        "Firebase credentials not configured (neither FIREBASE_CREDENTIALS_JSON nor FIREBASE_CREDENTIALS_PATH). "
        "Firebase integration will not be available in live mode."
    )


def verify_firebase_token(token: str) -> dict[str, Any]:
    """
    Verify a Firebase ID Token using Firebase Admin SDK.
    Returns the decoded token dictionary.
    Raises FirebaseNotInitializedError if Firebase SDK is not initialized.
    Raises FirebaseVerificationError if token is invalid or expired.
    """
    if not firebase_admin._apps:
        # Khởi tạo muộn nếu có cấu hình credentials (JSON hoặc PATH)
        if (settings.FIREBASE_CREDENTIALS_JSON and settings.FIREBASE_CREDENTIALS_JSON.strip()) or settings.FIREBASE_CREDENTIALS_PATH:
            init_firebase()
        
        if not firebase_admin._apps:
            logger.error("Firebase Admin SDK is not initialized. Cannot verify token.")
            raise FirebaseNotInitializedError("Firebase Authentication service is not initialized.")

    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except auth.ExpiredIdTokenError as e:
        logger.warning(f"Firebase token expired: {e}")
        raise FirebaseVerificationError("Firebase token has expired.") from e
    except auth.RevokedIdTokenError as e:
        logger.warning(f"Firebase token revoked: {e}")
        raise FirebaseVerificationError("Firebase token has been revoked.") from e
    except (auth.InvalidIdTokenError, ValueError) as e:
        logger.warning(f"Invalid Firebase token: {e}")
        raise FirebaseVerificationError("Invalid Firebase token.") from e
    except Exception as e:
        logger.error(f"Unexpected error during Firebase token verification: {e}")
        raise FirebaseVerificationError("Failed to verify Firebase token.") from e


def send_multicast_push(
    tokens: list[str],
    title: str,
    body: str,
    data: Optional[dict[str, str]] = None,
) -> list[str]:
    """
    Send Web Push notification to a list of FCM device registration tokens.
    Returns list of stale/invalid tokens that should be cleaned up from database.
    Best-effort execution: never raises an exception to the caller.
    """
    if not tokens:
        return []

    if not firebase_admin._apps:
        if (settings.FIREBASE_CREDENTIALS_JSON and settings.FIREBASE_CREDENTIALS_JSON.strip()) or settings.FIREBASE_CREDENTIALS_PATH:
            init_firebase()
        if not firebase_admin._apps:
            logger.warning("Firebase Admin SDK is not initialized. Skipping push notification.")
            return []

    stale_tokens: list[str] = []
    try:
        from firebase_admin import messaging

        safe_data = {str(k): str(v) for k, v in (data or {}).items() if v is not None}

        message = messaging.MulticastMessage(
            tokens=tokens,
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=safe_data,
            webpush=messaging.WebpushConfig(
                notification=messaging.WebpushNotification(
                    title=title,
                    body=body,
                    icon="/logo.svg",
                    badge="/logo.svg",
                    tag=safe_data.get("notification_id") or safe_data.get("conversation_id") or "ptit-notification",
                ),
            ),
        )

        response = messaging.send_each_for_multicast(message)

        if response.failure_count > 0:
            for idx, resp in enumerate(response.responses):
                if not resp.success and resp.exception:
                    exc = resp.exception
                    if isinstance(exc, (messaging.UnregisteredError, messaging.SenderIdMismatchError)):
                        stale_tokens.append(tokens[idx])
                    else:
                        code = getattr(exc, "code", "")
                        if "not-registered" in str(code).lower() or "invalid" in str(code).lower():
                            stale_tokens.append(tokens[idx])

        return stale_tokens
    except Exception as e:
        logger.warning(f"Error dispatching FCM multicast push: {e}")
        return []