from datetime import datetime, timezone
from typing import Optional


def ensure_utc_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Normalizes a datetime instance to be timezone-aware with UTC timezone.
    By project convention, naive datetimes persisted in the database represent
    UTC wall-clock time. If dt has no tzinfo, timezone.utc is attached.
    If dt is already aware, it is normalized to UTC.
    If dt is None, returns None.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
