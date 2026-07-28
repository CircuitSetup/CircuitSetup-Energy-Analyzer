from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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
        {"date": f"2026-07-{day:02d}", "usage_kwh": 2.0, "complete": True}
        for day in range(6, 13)
    ] + [
        {"date": f"2026-06-{day:02d}", "usage_kwh": 1.0, "complete": True}
        for day in range(29, 31)
    ] + [
        {"date": f"2026-07-{day:02d}", "usage_kwh": 1.0, "complete": True}
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
            learning_by_circuit={"fridge": False},
            learning_progress_by_circuit={"fridge": {"alert_ready": True}},
            energy_usage_evidence_by_circuit={},
            solar_load_shift_evidence_by_circuit={},
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


def test_digest_direct_items_require_two_complete_eligible_weeks() -> None:
    now = datetime(2026, 7, 27, 12, tzinfo=UTC)
    start = date(2026, 7, 13)
    days = [
        {
            "date": (start + timedelta(days=offset)).isoformat(),
            "usage_kwh": 1.0,
            "complete": True,
        }
        for offset in range(13)
    ]
    coordinator = _direct_digest_coordinator(days)

    assert digest_items_for_coordinator(
        coordinator,
        now=now,
        time_zone=ZoneInfo("UTC"),
    ) == []

    coordinator.state.active_alerts_by_circuit["dryer"] = [object()]
    (unresolved,) = digest_items_for_coordinator(
        coordinator,
        now=now,
        time_zone=ZoneInfo("UTC"),
    )
    assert unresolved["status"] == "unresolved"
    assert unresolved["comparable_energy"] is False
    digest = build_weekly_digest(
        [unresolved],
        now=now,
        time_zone=ZoneInfo("UTC"),
    )
    assert [item.appliance_key for item in digest.unresolved_items] == [
        "circuit:dryer"
    ]
    assert digest.biggest_changes == ()
    assert digest.top_energy_users == ()
    coordinator.state.active_alerts_by_circuit.clear()

    days.append(
        {
            "date": date(2026, 7, 26).isoformat(),
            "usage_kwh": 1.0,
            "complete": True,
        }
    )
    assert len(
        digest_items_for_coordinator(
            coordinator,
            now=now,
            time_zone=ZoneInfo("UTC"),
        )
    ) == 1

    days[-1]["baseline_eligible"] = False
    assert digest_items_for_coordinator(
        coordinator,
        now=now,
        time_zone=ZoneInfo("UTC"),
    ) == []

    days[-1]["baseline_eligible"] = True
    coordinator.state.learning_by_circuit["dryer"] = True
    coordinator.state.active_alerts_by_circuit["dryer"] = [object()]
    assert digest_items_for_coordinator(
        coordinator,
        now=now,
        time_zone=ZoneInfo("UTC"),
    ) == []


def test_digest_honors_weather_and_water_flow_context_evidence() -> None:
    days = [
        {
            "date": (date(2026, 7, 13) + timedelta(days=offset)).isoformat(),
            "usage_kwh": 1.0,
            "complete": True,
        }
        for offset in range(14)
    ]
    coordinator = _direct_digest_coordinator(days, circuit_id="hvac", name="HVAC")
    coordinator.circuit_configs += (
        SimpleNamespace(
            circuit_id="water_heater",
            name="Water Heater",
            mode=SimpleNamespace(value="single_phase"),
        ),
    )
    coordinator.store_data.energy_usage_by_circuit["water_heater"] = {"days": days}
    coordinator.state.learning_by_circuit["water_heater"] = False
    coordinator.state.energy_usage_evidence_by_circuit = {
        "hvac": {
            "status": "context_explained",
            "baseline_context": {"season": "summer", "weather_mode": "cooling"},
        },
        "water_heater": {
            "status": "context_explained",
            "baseline_context": {"water_flow_state": "active_flow"},
        },
    }

    items = digest_items_for_coordinator(
        coordinator,
        now=datetime(2026, 7, 27, 12, tzinfo=UTC),
        time_zone=ZoneInfo("UTC"),
    )

    assert {
        item["appliance_key"]: item["expected_context"] for item in items
    } == {
        "circuit:hvac": True,
        "circuit:water_heater": True,
    }


def test_digest_reuses_idle_solar_load_shift_candidates() -> None:
    coordinator = SimpleNamespace(
        circuit_configs=(),
        state=SimpleNamespace(
            solar_load_shift_evidence_by_circuit={
                "solar": {
                    "status": "surplus_candidate",
                    "solar_load_shift_available_w": 2500.0,
                    "candidate_loads": [
                        {
                            "circuit_id": "water_heater",
                            "name": "Water Heater",
                            "current_power_w": 0.0,
                            "state": "idle",
                        }
                    ],
                }
            }
        ),
        store_data=SimpleNamespace(
            energy_usage_by_circuit={},
            nilm_appliance_assignments_by_circuit={},
            nilm_session_history_by_circuit={},
        ),
    )

    assert digest_items_for_coordinator(
        coordinator,
        now=datetime(2026, 7, 27, 12, tzinfo=UTC),
        time_zone=ZoneInfo("UTC"),
    ) == [
        {
            "appliance_key": "circuit:water_heater",
            "display_name": "Water Heater",
            "energy_kwh": 0.0,
            "normal_energy_kwh": 0.0,
            "confidence": 1.0,
            "status": "load_shift_opportunity",
        }
    ]


def _direct_digest_coordinator(
    days: list[dict[str, object]],
    *,
    circuit_id: str = "dryer",
    name: str = "Dryer",
) -> SimpleNamespace:
    return SimpleNamespace(
        circuit_configs=(
            SimpleNamespace(
                circuit_id=circuit_id,
                name=name,
                mode=SimpleNamespace(value="single_phase"),
            ),
        ),
        state=SimpleNamespace(
            active_alerts_by_circuit={},
            learning_by_circuit={circuit_id: False},
            learning_progress_by_circuit={circuit_id: {"alert_ready": True}},
            energy_usage_evidence_by_circuit={},
            solar_load_shift_evidence_by_circuit={},
        ),
        store_data=SimpleNamespace(
            energy_usage_by_circuit={circuit_id: {"days": days}},
            nilm_appliance_assignments_by_circuit={},
            nilm_session_history_by_circuit={},
        ),
    )
