from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Literal

from .notifications import POWER_QUALITY_ALERT_FEATURES

DELIVERY_MODES = frozenset(
    {"immediate", "daily_summary", "weekly_digest", "disabled"}
)
NOTIFICATION_CATEGORIES = (
    "finished_running",
    "unusual_runtime",
    "high_daily_energy",
    "electrical_issue",
    "capacity_demand_issue",
    "data_quality_issue",
    "nilm_review_needed",
    "other_issue",
)

_NOTIFICATION_CATEGORY_BY_FEATURE = {
    "always_on_power": "high_daily_energy",
    "billing_cycle_budget": "high_daily_energy",
    "daily_energy_spike": "high_daily_energy",
    "utility_energy_mismatch": "data_quality_issue",
}


@dataclass(frozen=True, slots=True)
class ApplianceNotificationPreferences:
    appliance_key: str
    finished_running: bool = False
    unusual_runtime: bool = True
    high_daily_energy: bool = True
    electrical_issue: bool = True
    capacity_demand_issue: bool = True
    data_quality_issue: bool = True
    nilm_review_needed: bool = True
    other_issue: bool = True
    delivery_mode: str = "immediate"
    minimum_confidence: float = 0.6
    cooldown_minutes: int = 60
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            category: getattr(self, category) for category in NOTIFICATION_CATEGORIES
        } | {
            "appliance_key": self.appliance_key,
            "delivery_mode": self.delivery_mode,
            "minimum_confidence": self.minimum_confidence,
            "cooldown_minutes": self.cooldown_minutes,
            "quiet_hours_start": _time_to_text(self.quiet_hours_start),
            "quiet_hours_end": _time_to_text(self.quiet_hours_end),
        }


@dataclass(frozen=True, slots=True)
class NotificationDeliveryDecision:
    action: Literal[
        "send", "suppress", "defer", "queue_daily", "queue_weekly"
    ]
    reason: str
    defer_until: datetime | None = None


def preferences_from_dict(
    raw: Mapping[str, Any] | None,
    *,
    appliance_key: str,
) -> ApplianceNotificationPreferences:
    """Parse persisted preferences with independent, safe field defaults."""
    values = raw if isinstance(raw, Mapping) else {}
    defaults = ApplianceNotificationPreferences(appliance_key=appliance_key)
    mode = str(values.get("delivery_mode") or defaults.delivery_mode)
    if mode not in DELIVERY_MODES:
        mode = defaults.delivery_mode
    confidence = _bounded_float(
        values.get("minimum_confidence"), defaults.minimum_confidence, 0.0, 1.0
    )
    cooldown = _bounded_int(
        values.get("cooldown_minutes"), defaults.cooldown_minutes, 0, 10080
    )
    return ApplianceNotificationPreferences(
        appliance_key=appliance_key,
        **{
            category: _boolean(values.get(category), getattr(defaults, category))
            for category in NOTIFICATION_CATEGORIES
        },
        delivery_mode=mode,
        minimum_confidence=confidence,
        cooldown_minutes=cooldown,
        quiet_hours_start=_time_or_none(values.get("quiet_hours_start")),
        quiet_hours_end=_time_or_none(values.get("quiet_hours_end")),
    )


def decide_notification_delivery(
    preferences: ApplianceNotificationPreferences,
    *,
    category: str,
    now: datetime,
    source_type: str,
    confidence: float | None = None,
    last_sent_at: datetime | None = None,
) -> NotificationDeliveryDecision:
    """Apply category, confidence, cooldown, quiet-hour, and mode policy."""
    if category not in NOTIFICATION_CATEGORIES or not getattr(
        preferences, category, False
    ):
        return NotificationDeliveryDecision("suppress", "category_disabled")
    if (
        source_type == "nilm_estimate"
        and confidence is not None
        and confidence < preferences.minimum_confidence
    ):
        return NotificationDeliveryDecision("suppress", "below_minimum_confidence")
    if last_sent_at is not None and now - last_sent_at < timedelta(
        minutes=preferences.cooldown_minutes
    ):
        return NotificationDeliveryDecision("suppress", "cooldown")
    quiet_end = _quiet_hours_end(preferences, now)
    if quiet_end is not None:
        return NotificationDeliveryDecision("defer", "quiet_hours", quiet_end)
    action = {
        "immediate": "send",
        "daily_summary": "queue_daily",
        "weekly_digest": "queue_weekly",
        "disabled": "suppress",
    }[preferences.delivery_mode]
    return NotificationDeliveryDecision(action, preferences.delivery_mode)


def alert_notification_category(feature: str) -> str:
    normalized = str(feature or "").lower()
    if normalized in _NOTIFICATION_CATEGORY_BY_FEATURE:
        return _NOTIFICATION_CATEGORY_BY_FEATURE[normalized]
    if normalized in POWER_QUALITY_ALERT_FEATURES:
        return "electrical_issue"
    if "finished" in normalized:
        return "finished_running"
    if any(
        token in normalized
        for token in ("daily_energy", "energy_spike", "unusual_energy")
    ):
        return "high_daily_energy"
    if "runtime" in normalized or "duration" in normalized:
        return "unusual_runtime"
    if "capacity" in normalized or "demand" in normalized:
        return "capacity_demand_issue"
    if any(
        token in normalized
        for token in ("data_quality", "stale", "missing", "metric_consistency")
    ):
        return "data_quality_issue"
    if any(
        token in normalized
        for token in ("voltage", "frequency", "power_factor", "leg_imbalance")
    ):
        return "electrical_issue"
    if normalized.startswith("nilm_"):
        return "nilm_review_needed"
    return "other_issue"


def _quiet_hours_end(
    preferences: ApplianceNotificationPreferences,
    now: datetime,
) -> datetime | None:
    start = preferences.quiet_hours_start
    end = preferences.quiet_hours_end
    if start is None or end is None or start == end:
        return None
    current = now.timetz().replace(tzinfo=None)
    crosses_midnight = start > end
    in_quiet = (
        current >= start or current < end
        if crosses_midnight
        else start <= current < end
    )
    if not in_quiet:
        return None
    end_date = now.date()
    if crosses_midnight and current >= start:
        end_date += timedelta(days=1)
    return datetime.combine(end_date, end, tzinfo=now.tzinfo)


def _time_or_none(value: Any) -> time | None:
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    if not isinstance(value, str) or not value:
        return None
    try:
        return time.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return None


def _time_to_text(value: time | None) -> str | None:
    return value.isoformat(timespec="minutes") if value is not None else None


def _boolean(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _bounded_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        return min(max(float(value), low), high)
    except (TypeError, ValueError):
        return default


def _bounded_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        return min(max(int(value), low), high)
    except (TypeError, ValueError):
        return default
