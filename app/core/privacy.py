from typing import Optional


def anonymize_name(full_name: Optional[str], default: str = "Người dùng") -> str:
    """
    Shortens a Vietnamese full name for privacy-safe public social display.
    Examples:
      - "Nguyễn Khắc Thịnh" -> "Nguyễn K. T."
      - "Trần Minh Anh" -> "Trần M. A."
      - "Lê Hoàng Nam" -> "Lê H. N."
      - "Thịnh" -> "Thịnh"
      - "Minh Anh" -> "Minh A."
    """
    if not full_name:
        return default
    parts = full_name.strip().split()
    if not parts:
        return default
    if len(parts) == 1:
        return parts[0]
    first = parts[0]
    initials = " ".join(f"{p[0].upper()}." for p in parts[1:] if p)
    return f"{first} {initials}".strip()
