from datetime import UTC, datetime

from custom_components.circuitsetup_energy_analyzer.billing import (
    BillingCycleSettings,
    record_billing_cycle_usage,
)


def test_record_billing_cycle_usage_projects_current_cycle_budget() -> None:
    history = {
        "cycle_start": "2026-06-01",
        "cycle_end": "2026-07-01",
        "cycle_usage_kwh": 90.0,
        "last_energy_kwh": 190.0,
        "last_sample_at": "2026-06-10T00:00:00+00:00",
    }

    result = record_billing_cycle_usage(
        history,
        circuit_id="fridge",
        timestamp=datetime(2026, 6, 10, 18, 0, tzinfo=UTC),
        energy_kwh=200.0,
        settings=BillingCycleSettings(
            cycle_start_day=1,
            budget_kwh=250.0,
            budget_alert_ratio=1.0,
        ),
    )

    assert result.cycle_start == "2026-06-01"
    assert result.cycle_end == "2026-07-01"
    assert result.cycle_usage_kwh == 100.0
    assert result.elapsed_days == 10
    assert result.cycle_days == 30
    assert result.projected_cycle_kwh == 300.0
    assert result.budget_usage_percent == 40.0
    assert result.projected_budget_usage_percent == 120.0
    assert result.status == "projected_over_budget"
    assert result.budget_exceeded is not None
    assert result.budget_exceeded.features == {
        "cycle_usage_kwh": 100.0,
        "projected_cycle_kwh": 300.0,
        "budget_kwh": 250.0,
        "budget_usage_percent": 40.0,
        "projected_budget_usage_percent": 120.0,
        "budget_alert_ratio": 1.0,
        "elapsed_days": 10.0,
        "cycle_days": 30.0,
    }


def test_record_billing_cycle_usage_honors_non_first_start_day() -> None:
    result = record_billing_cycle_usage(
        {},
        circuit_id="hvac",
        timestamp=datetime(2026, 6, 3, 12, 0, tzinfo=UTC),
        energy_kwh=512.0,
        settings=BillingCycleSettings(cycle_start_day=15),
    )

    assert result.cycle_start == "2026-05-15"
    assert result.cycle_end == "2026-06-15"
    assert result.elapsed_days == 20
    assert result.cycle_days == 31
    assert result.status == "no_budget"


def test_record_billing_cycle_usage_resets_on_new_cycle() -> None:
    history = {
        "cycle_start": "2026-05-15",
        "cycle_end": "2026-06-15",
        "cycle_usage_kwh": 75.0,
        "last_energy_kwh": 500.0,
        "last_sample_at": "2026-06-14T23:00:00+00:00",
    }

    result = record_billing_cycle_usage(
        history,
        circuit_id="pool",
        timestamp=datetime(2026, 6, 15, 1, 0, tzinfo=UTC),
        energy_kwh=505.0,
        settings=BillingCycleSettings(cycle_start_day=15, budget_kwh=300.0),
    )

    assert result.cycle_start == "2026-06-15"
    assert result.cycle_end == "2026-07-15"
    assert result.cycle_usage_kwh == 0.0
    assert result.projected_cycle_kwh == 0.0
    assert history["last_energy_kwh"] == 505.0


def test_record_billing_cycle_usage_ignores_meter_reset_delta() -> None:
    history = {
        "cycle_start": "2026-06-01",
        "cycle_end": "2026-07-01",
        "cycle_usage_kwh": 42.0,
        "last_energy_kwh": 1000.0,
        "last_sample_at": "2026-06-10T12:00:00+00:00",
    }

    result = record_billing_cycle_usage(
        history,
        circuit_id="oven",
        timestamp=datetime(2026, 6, 10, 18, 0, tzinfo=UTC),
        energy_kwh=5.0,
        settings=BillingCycleSettings(cycle_start_day=1, budget_kwh=200.0),
    )

    assert result.cycle_usage_kwh == 42.0
    assert history["last_energy_kwh"] == 5.0
