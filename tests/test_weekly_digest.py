from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from custom_components.circuitsetup_energy_analyzer.weekly_digest import (
    build_weekly_digest,
    digest_idempotence_key,
    digest_items_for_coordinator,
)


def _items() -> list[dict[str, object]]:
    return [
        {
            "appliance_key": "circuit:ev",
            "display_name": "EV Charger",
            "energy_kwh": 20.0,
            "normal_energy_kwh": 10.0,
            "confidence": 0.95,
            "expected_context": True,
        },
        {
            "appliance_key": "circuit:fridge",
            "display_name": "Refrigerator",
            "energy_kwh": 1.6,
            "normal_energy_kwh": 1.0,
            "confidence": 0.9,
            "status": "unresolved",
        },
        {
            "appliance_key": "circuit:old-setup",
            "display_name": "Old Setup Issue",
            "energy_kwh": 0.0,
            "normal_energy_kwh": 0.0,
            "status": "resolved",
        },
        {
            "appliance_key": "nilm:dishwasher",
            "display_name": "Dishwasher",
            "energy_kwh": 1.1,
            "normal_energy_kwh": 1.0,
            "status": "nilm_review_needed",
            "confidence": 0.72,
        },
    ]


def test_digest_ranks_change_and_omits_expected_or_resolved_noise() -> None:
    digest = build_weekly_digest(
        _items(),
        now=datetime(2026, 7, 13, 12, 0, tzinfo=UTC),
        time_zone=ZoneInfo("America/New_York"),
    )

    assert digest.week_start == date(2026, 7, 6)
    assert digest.week_end == date(2026, 7, 12)
    assert digest_idempotence_key(digest) == digest_idempotence_key(
        build_weekly_digest(
            _items(),
            now=datetime(2026, 7, 14, 3, 30, tzinfo=UTC),
            time_zone=ZoneInfo("America/New_York"),
        )
    )

    assert digest.biggest_changes[0].appliance_key == "circuit:fridge"
    assert "circuit:ev" not in {item.appliance_key for item in digest.biggest_changes}
    assert digest.top_energy_users[0].appliance_key == "circuit:ev"
    assert "circuit:old-setup" not in {
        item.appliance_key for item in digest.unresolved_items
    }
    assert [item.appliance_key for item in digest.nilm_review_items] == [
        "nilm:dishwasher"
    ]


def test_digest_uses_local_week_and_has_a_stable_idempotence_key() -> None:
    digest = build_weekly_digest(
        _items(),
        now=datetime(2026, 7, 13, 3, 30, tzinfo=UTC),
        time_zone=ZoneInfo("America/New_York"),
    )

    assert digest.week_start == date(2026, 6, 29)
    assert digest.week_end == date(2026, 7, 5)
    assert digest_idempotence_key(digest) == digest_idempotence_key(
        build_weekly_digest(
            _items(),
            now=datetime(2026, 7, 12, 12, 0, tzinfo=UTC),
            time_zone=ZoneInfo("America/New_York"),
        )
    )


def test_digest_items_sum_completed_week_and_compare_prior_week() -> None:
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    days = [
        {"date": f"2026-07-{day:02d}", "usage_kwh": 2.0}
        for day in range(6, 13)
    ] + [
        {"date": f"2026-06-{day:02d}", "usage_kwh": 1.0}
        for day in range(29, 31)
    ] + [
        {"date": f"2026-07-{day:02d}", "usage_kwh": 1.0}
        for day in range(1, 6)
    ]
    coordinator = SimpleNamespace(
        circuit_configs=(
            SimpleNamespace(
                circuit_id="fridge",
                name="Fridge",
                mode=SimpleNamespace(value="single_phase"),
            ),
        ),
        state=SimpleNamespace(
            active_alerts_by_circuit={},
            daily_energy_usage_by_circuit={"fridge": 99.0},
            learning_progress_by_circuit={"fridge": {"alert_ready": True}},
        ),
        store_data=SimpleNamespace(
            energy_usage_by_circuit={"fridge": {"days": days}},
            nilm_appliance_assignments_by_circuit={},
            nilm_session_history_by_circuit={},
        ),
    )

    (item,) = digest_items_for_coordinator(
        coordinator,
        now=now,
        time_zone=ZoneInfo("America/New_York"),
    )

    assert item["energy_kwh"] == 14.0
    assert item["normal_energy_kwh"] == 7.0
