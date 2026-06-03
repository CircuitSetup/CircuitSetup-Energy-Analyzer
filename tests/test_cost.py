from datetime import UTC, datetime

from custom_components.circuitsetup_energy_analyzer.cost import (
    CostSettings,
    record_cost_sample,
)


def test_record_cost_sample_tracks_flat_rate_cycle_cost_and_forecast() -> None:
    history = {
        "cycle_start": "2026-06-01",
        "cycle_end": "2026-07-01",
        "cycle_cost": 18.0,
        "last_energy_kwh": 190.0,
        "last_sample_at": "2026-06-10T00:00:00+00:00",
    }

    result = record_cost_sample(
        history,
        circuit_id="fridge",
        timestamp=datetime(2026, 6, 10, 18, 0, tzinfo=UTC),
        energy_kwh=200.0,
        settings=CostSettings(default_rate_per_kwh=0.20),
    )

    assert result.cycle_start == "2026-06-01"
    assert result.cycle_end == "2026-07-01"
    assert result.current_rate_per_kwh == 0.20
    assert result.active_rate_name == "Default"
    assert result.delta_kwh == 10.0
    assert result.delta_cost == 2.0
    assert result.cycle_cost == 20.0
    assert result.projected_cycle_cost == 60.0
    assert result.status == "tracking"


def test_record_cost_sample_applies_tou_peak_weekday_rate() -> None:
    history = {
        "cycle_start": "2026-06-01",
        "cycle_end": "2026-07-01",
        "cycle_cost": 5.0,
        "last_energy_kwh": 100.0,
        "last_sample_at": "2026-06-08T16:30:00+00:00",
    }

    result = record_cost_sample(
        history,
        circuit_id="hvac",
        timestamp=datetime(2026, 6, 8, 18, 0, tzinfo=UTC),
        energy_kwh=104.0,
        settings=CostSettings(
            default_rate_per_kwh=0.10,
            tou_rate_per_kwh=0.30,
            tou_start="17:00",
            tou_end="21:00",
            tou_weekdays=(0, 1, 2, 3, 4),
            tou_name="Peak",
        ),
    )

    assert result.active_rate_name == "Peak"
    assert result.current_rate_per_kwh == 0.30
    assert result.delta_cost == 1.2
    assert result.cycle_cost == 6.2
    assert result.status == "tou_peak"


def test_record_cost_sample_handles_overnight_tou_period() -> None:
    result = record_cost_sample(
        {"last_energy_kwh": 10.0, "last_sample_at": "2026-06-08T21:00:00+00:00"},
        circuit_id="pool",
        timestamp=datetime(2026, 6, 8, 23, 30, tzinfo=UTC),
        energy_kwh=12.0,
        settings=CostSettings(
            default_rate_per_kwh=0.16,
            tou_rate_per_kwh=0.08,
            tou_start="22:00",
            tou_end="06:00",
            tou_name="Super Off Peak",
        ),
    )

    assert result.active_rate_name == "Super Off Peak"
    assert result.current_rate_per_kwh == 0.08
    assert result.status == "tou_peak"


def test_record_cost_sample_resets_on_new_cycle() -> None:
    history = {
        "cycle_start": "2026-05-15",
        "cycle_end": "2026-06-15",
        "cycle_cost": 31.0,
        "last_energy_kwh": 500.0,
        "last_sample_at": "2026-06-14T23:00:00+00:00",
    }

    result = record_cost_sample(
        history,
        circuit_id="dryer",
        timestamp=datetime(2026, 6, 15, 1, 0, tzinfo=UTC),
        energy_kwh=505.0,
        settings=CostSettings(cycle_start_day=15, default_rate_per_kwh=0.22),
    )

    assert result.cycle_start == "2026-06-15"
    assert result.cycle_end == "2026-07-15"
    assert result.cycle_cost == 0.0
    assert result.projected_cycle_cost == 0.0
    assert history["last_energy_kwh"] == 505.0


def test_record_cost_sample_ignores_meter_reset_delta() -> None:
    history = {
        "cycle_start": "2026-06-01",
        "cycle_end": "2026-07-01",
        "cycle_cost": 12.0,
        "last_energy_kwh": 1000.0,
        "last_sample_at": "2026-06-10T12:00:00+00:00",
    }

    result = record_cost_sample(
        history,
        circuit_id="oven",
        timestamp=datetime(2026, 6, 10, 18, 0, tzinfo=UTC),
        energy_kwh=5.0,
        settings=CostSettings(default_rate_per_kwh=0.20),
    )

    assert result.delta_kwh == 0.0
    assert result.cycle_cost == 12.0
    assert history["last_energy_kwh"] == 5.0
