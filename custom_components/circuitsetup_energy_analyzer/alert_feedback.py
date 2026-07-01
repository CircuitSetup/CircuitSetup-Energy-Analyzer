"""Shared alert feedback parsing helpers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any


def alert_feedback_status(feedback: Mapping[str, Any]) -> str | None:
    """Return the normalized feedback status/action."""
    status = feedback.get("status") or feedback.get("action")
    if not isinstance(status, str):
        return None
    normalized = status.strip().lower()
    return normalized or None


def alert_feedback_is_expired(
    feedback: Mapping[str, Any],
    now: datetime,
) -> bool:
    """Return true when a feedback mapping has expired."""
    expires_at = mapping_datetime(feedback.get("expires_at"))
    if expires_at is None:
        return False
    return expires_at <= _datetime_with_matching_timezone(now, expires_at)


def mapping_datetime(value: Any) -> datetime | None:
    """Parse datetimes stored in feedback mappings."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _datetime_with_matching_timezone(now: datetime, target: datetime) -> datetime:
    if target.tzinfo is None and now.tzinfo is not None:
        return now.replace(tzinfo=None)
    if target.tzinfo is not None and now.tzinfo is None:
        return now.replace(tzinfo=target.tzinfo)
    return now
