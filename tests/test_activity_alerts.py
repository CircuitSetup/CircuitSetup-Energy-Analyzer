from __future__ import annotations

from datetime import UTC, datetime

from custom_components.circuitsetup_energy_analyzer.cycles import CircuitCycleSummary


def test_activity_alert_flags_active_run_over_configured_duration() -> None:
    from custom_components.circuitsetup_energy_analyzer.activity_alerts import (
        ActivityAlertSettings,
        evaluate_activity_alert,
    )

    summary = CircuitCycleSummary(
        circuit_id="fridge",
        date="2026-06-16",
        status="running",
        start_count=1,
        completed_cycle_count=0,
        runtime_seconds=2700.0,
        average_cycle_seconds=0.0,
        active_cycle_seconds=2700.0,
        duty_cycle_percent=7.5,
        day_elapsed_seconds=36000.0,
        last_start=datetime(2026, 6, 16, 11, 15, tzinfo=UTC),
    )

    evidence = evaluate_activity_alert(
        circuit_id="fridge",
        circuit_name="Kitchen Fridge",
        summary=summary,
        settings=ActivityAlertSettings(max_active_minutes=30.0),
    )

    assert evidence is not None
    assert evidence.feature == "activity_left_on"
    assert evidence.observed_value == 45.0
    assert evidence.baseline_value == 30.0
    assert "Kitchen Fridge has been active for 45 minutes" in evidence.message
    assert evidence.features == {
        "active_minutes": 45.0,
        "max_active_minutes": 30.0,
        "active_cycle_seconds": 2700.0,
        "last_start": "2026-06-16T11:15:00+00:00",
    }


def test_activity_alert_ignores_unconfigured_or_idle_circuits() -> None:
    from custom_components.circuitsetup_energy_analyzer.activity_alerts import (
        ActivityAlertSettings,
        evaluate_activity_alert,
    )

    idle_summary = CircuitCycleSummary(
        circuit_id="fridge",
        date="2026-06-16",
        status="idle",
        start_count=1,
        completed_cycle_count=1,
        runtime_seconds=1200.0,
        average_cycle_seconds=1200.0,
        active_cycle_seconds=0.0,
        duty_cycle_percent=3.3,
        day_elapsed_seconds=36000.0,
    )

    assert (
        evaluate_activity_alert(
            circuit_id="fridge",
            circuit_name="Kitchen Fridge",
            summary=idle_summary,
            settings=ActivityAlertSettings(max_active_minutes=30.0),
        )
        is None
    )
    assert (
        evaluate_activity_alert(
            circuit_id="fridge",
            circuit_name="Kitchen Fridge",
            summary=idle_summary,
            settings=ActivityAlertSettings(),
        )
        is None
    )
