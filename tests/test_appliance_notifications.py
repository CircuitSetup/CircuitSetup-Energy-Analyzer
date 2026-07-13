from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from custom_components.circuitsetup_energy_analyzer.appliance_notifications import (
    ApplianceNotificationPreferences,
    alert_notification_category,
    decide_notification_delivery,
    preferences_from_dict,
)

LOCAL = ZoneInfo("America/New_York")


def test_legacy_preferences_use_safe_defaults_and_category_choices() -> None:
    preferences = preferences_from_dict({}, appliance_key="circuit:fridge")

    assert preferences == ApplianceNotificationPreferences(
        appliance_key="circuit:fridge"
    )
    assert preferences.finished_running is False
    assert preferences.electrical_issue is True
    assert preferences.data_quality_issue is True
    assert preferences.delivery_mode == "immediate"

    now = datetime(2026, 7, 13, 12, 0, tzinfo=LOCAL)
    assert decide_notification_delivery(
        preferences,
        category="finished_running",
        now=now,
        source_type="direct_meter",
    ).action == "suppress"
    assert decide_notification_delivery(
        preferences,
        category="electrical_issue",
        now=now,
        source_type="direct_meter",
    ).action == "send"


@pytest.mark.parametrize(
    ("mode", "action"),
    [
        ("daily_summary", "queue_daily"),
        ("weekly_digest", "queue_weekly"),
        ("disabled", "suppress"),
    ],
)
def test_delivery_modes(mode: str, action: str) -> None:
    decision = decide_notification_delivery(
        ApplianceNotificationPreferences(
            appliance_key="circuit:dryer",
            delivery_mode=mode,
        ),
        category="unusual_runtime",
        now=datetime(2026, 7, 13, 12, 0, tzinfo=LOCAL),
        source_type="direct_meter",
    )

    assert decision.action == action


def test_cross_midnight_quiet_hours_defer_and_cooldown_suppresses() -> None:
    preferences = ApplianceNotificationPreferences(
        appliance_key="circuit:dryer",
        quiet_hours_start=time(22, 0),
        quiet_hours_end=time(7, 0),
        cooldown_minutes=60,
    )
    now = datetime(2026, 7, 13, 23, 30, tzinfo=LOCAL)

    quiet = decide_notification_delivery(
        preferences,
        category="unusual_runtime",
        now=now,
        source_type="direct_meter",
    )
    cooldown = decide_notification_delivery(
        preferences,
        category="unusual_runtime",
        now=datetime(2026, 7, 14, 12, 0, tzinfo=LOCAL),
        source_type="direct_meter",
        last_sent_at=datetime(2026, 7, 14, 11, 30, tzinfo=LOCAL),
    )

    assert quiet.action == "defer"
    assert quiet.defer_until == datetime(2026, 7, 14, 7, 0, tzinfo=LOCAL)
    assert cooldown.action == "suppress"
    assert cooldown.reason == "cooldown"


def test_minimum_confidence_applies_only_to_nilm() -> None:
    preferences = ApplianceNotificationPreferences(appliance_key="circuit:dryer")
    now = datetime(2026, 7, 13, 12, 0, tzinfo=LOCAL)

    nilm = decide_notification_delivery(
        preferences,
        category="unusual_runtime",
        now=now,
        source_type="nilm_estimate",
        confidence=0.5,
    )
    direct = decide_notification_delivery(
        preferences,
        category="unusual_runtime",
        now=now,
        source_type="direct_meter",
        confidence=0.5,
    )

    assert nilm.action == "suppress"
    assert nilm.reason == "below_minimum_confidence"
    assert direct.action == "send"


def test_nilm_alert_categories_remain_independent() -> None:
    assert alert_notification_category("nilm_appliance_finished") == (
        "finished_running"
    )
    assert alert_notification_category("nilm_unusual_runtime") == "unusual_runtime"
    assert alert_notification_category("nilm_high_daily_energy") == (
        "high_daily_energy"
    )
    assert alert_notification_category("nilm_low_confidence_change") == (
        "nilm_review_needed"
    )
