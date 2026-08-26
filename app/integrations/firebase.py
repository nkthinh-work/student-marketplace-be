import logging
from typing import Any
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

    if settings.FIREBASE_CREDENTIALS_PATH:
        try:
            cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin SDK successfully initialized.")
        except Exception as e:
            logger.error(f"Error initializing Firebase Admin SDK: {e}")
    else:
        logger.warning(
            "FIREBASE_CREDENTIALS_PATH not set. Firebase integration will not be available in live mode."
        )


def verify_firebase_token(token: str) -> dict[str, Any]:
    """
    Verify a Firebase ID Token using Firebase Admin SDK.
    Returns the decoded token dictionary.
    Raises FirebaseNotInitializedError if Firebase SDK is not initialized.
    Raises FirebaseVerificationError if token is invalid or expired.
    """
    if not firebase_admin._apps:
        # Khởi tạo muộn nếu có cấu hình credentials
        if settings.FIREBASE_CREDENTIALS_PATH:
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