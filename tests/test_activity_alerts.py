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


def test_activity_alert_skips_active_duration_when_suppressed() -> None:
    from custom_components.circuitsetup_energy_analyzer.activity_alerts import (
        ActivityAlertSettings,
        evaluate_activity_alert,
    )

    summary = CircuitCycleSummary(
        circuit_id="main_panel",
        date="2026-06-16",
        status="running",
        start_count=1,
        completed_cycle_count=0,
        runtime_seconds=38520.0,
        average_cycle_seconds=0.0,
        active_cycle_seconds=38520.0,
        duty_cycle_percent=100.0,
        day_elapsed_seconds=38520.0,
        last_start=datetime(2026, 6, 16, 0, 0, tzinfo=UTC),
    )

    assert (
        evaluate_activity_alert(
            circuit_id="main_panel",
            circuit_name="Main Panel",
            summary=summary,
            settings=ActivityAlertSettings(max_active_minutes=66.0),
            suppress_active_duration_alert=True,
        )
        is None
    )


def test_activity_alert_flags_idle_period_over_configured_duration() -> None:
    from custom_components.circuitsetup_energy_analyzer.activity_alerts import (
        ActivityAlertSettings,
        evaluate_activity_alert,
    )

    summary = CircuitCycleSummary(
        circuit_id="fridge",
        date="2026-06-16",
        status="idle",
        start_count=1,
        completed_cycle_count=1,
        runtime_seconds=1200.0,
        average_cycle_seconds=1200.0,
        active_cycle_seconds=0.0,
        duty_cycle_percent=3.3,
        day_elapsed_seconds=21600.0,
        last_start=datetime(2026, 6, 16, 1, 0, tzinfo=UTC),
        last_stop=datetime(2026, 6, 16, 2, 0, tzinfo=UTC),
    )

    evidence = evaluate_activity_alert(
        circuit_id="fridge",
        circuit_name="Kitchen Fridge",
        summary=summary,
        settings=ActivityAlertSettings(max_idle_minutes=90.0),
    )

    assert evidence is not None
    assert evidence.feature == "activity_inactive_too_long"
    assert evidence.observed_value == 240.0
    assert evidence.baseline_value == 90.0
    assert "Kitchen Fridge has shown no activity for 4 hours" in evidence.message
    assert evidence.features == {
        "idle_minutes": 240.0,
        "max_idle_minutes": 90.0,
        "idle_seconds": 14400.0,
        "last_start": "2026-06-16T01:00:00+00:00",
        "last_stop": "2026-06-16T02:00:00+00:00",
        "status": "idle",
    }


def test_activity_alert_idle_period_uses_summary_day_start() -> None:
    from custom_components.circuitsetup_energy_analyzer.activity_alerts import (
        ActivityAlertSettings,
        evaluate_activity_alert,
    )

    summary = CircuitCycleSummary(
        circuit_id="fridge",
        date="2026-05-31",
        status="idle",
        start_count=1,
        completed_cycle_count=1,
        runtime_seconds=1800.0,
        average_cycle_seconds=1800.0,
        active_cycle_seconds=0.0,
        duty_cycle_percent=2.1,
        day_elapsed_seconds=84600.0,
        day_start=datetime(2026, 5, 31, 4, 0, tzinfo=UTC),
        last_start=datetime(2026, 5, 31, 23, 30, tzinfo=UTC),
        last_stop=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
    )

    evidence = evaluate_activity_alert(
        circuit_id="fridge",
        circuit_name="Kitchen Fridge",
        summary=summary,
        settings=ActivityAlertSettings(max_idle_minutes=180.0),
    )

    assert evidence is not None
    assert evidence.observed_value == 210.0
    assert evidence.features["idle_seconds"] == 12600.0


def test_activity_alert_can_flag_no_activity_since_day_start() -> None:
    from custom_components.circuitsetup_energy_analyzer.activity_alerts import (
        ActivityAlertSettings,
        evaluate_activity_alert,
    )

    summary = CircuitCycleSummary(
        circuit_id="sump",
        date="2026-06-16",
        status="no_activity",
        start_count=0,
        completed_cycle_count=0,
        runtime_seconds=0.0,
        average_cycle_seconds=0.0,
        active_cycle_seconds=0.0,
        duty_cycle_percent=0.0,
        day_elapsed_seconds=10800.0,
    )

    evidence = evaluate_activity_alert(
        circuit_id="sump",
        circuit_name="Sump Pump",
        summary=summary,
        settings=ActivityAlertSettings(max_idle_minutes=120.0),
    )

    assert evidence is not None
    assert evidence.feature == "activity_inactive_too_long"
    assert evidence.observed_value == 180.0
    assert evidence.features["status"] == "no_activity"


def test_activity_alert_ignores_unconfigured_idle_or_running_circuits() -> None:
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
            settings=ActivityAlertSettings(max_idle_minutes=300.0),
        )
        is None
    )

    running_summary = CircuitCycleSummary(
        circuit_id="fridge",
        date="2026-06-16",
        status="running",
        start_count=1,
        completed_cycle_count=0,
        runtime_seconds=900.0,
        average_cycle_seconds=0.0,
        active_cycle_seconds=900.0,
        duty_cycle_percent=2.5,
        day_elapsed_seconds=36000.0,
    )
    assert (
        evaluate_activity_alert(
            circuit_id="fridge",
            circuit_name="Kitchen Fridge",
            summary=running_summary,
            settings=ActivityAlertSettings(max_idle_minutes=30.0),
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
