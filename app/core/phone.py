"""
Canonical Vietnamese Mobile Phone Validation and Normalization.
Marketplace C2C Sinh viên - Vietnam-only scope.
"""
import re
from typing import Optional

# Canonical VN mobile prefix families: 03, 05, 07, 08, 09 (10 digits total)
VN_MOBILE_REGEX = re.compile(r"^0[35789]\d{8}$")

# Allowed input characters: digits, spaces, '.', '-', and optional leading '+'
ALLOWED_PHONE_CHARS = re.compile(r"^\+?[0-9\s.-]+$")


def normalize_vietnam_phone(phone: Optional[str]) -> Optional[str]:
    """
    Normalizes and validates a Vietnamese mobile phone number.
    Returns normalized 10-digit format '0XXXXXXXXX' if valid.
    Raises ValueError if invalid.
    If phone is None or empty/whitespace, returns None.
    """
    if phone is None:
        return None
    raw = phone.strip()
    if not raw:
        return None

    if not ALLOWED_PHONE_CHARS.match(raw):
        raise ValueError(
            "Số điện thoại không hợp lệ. Vui lòng nhập số di động Việt Nam 10 chữ số."
        )

    # Strip visual separators (spaces, dots, hyphens)
    cleaned = re.sub(r"[\s.-]", "", raw)

    if cleaned.startswith("+84"):
        cleaned = "0" + cleaned[3:]
    elif cleaned.startswith("84") and len(cleaned) == 11:
        cleaned = "0" + cleaned[2:]

    if not VN_MOBILE_REGEX.match(cleaned):
        raise ValueError(
            "Số điện thoại không hợp lệ. Vui lòng nhập số di động Việt Nam 10 chữ số."
        )

    return cleaned
