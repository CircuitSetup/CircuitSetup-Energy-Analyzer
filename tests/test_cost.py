from datetime import UTC, datetime

import pytest

from custom_components.circuitsetup_energy_analyzer.cost import (
    CostSettings,
    record_cost_sample,
)
from custom_components.circuitsetup_energy_analyzer.processors.cost import (
    cost_evidence_payload,
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
        "last_sample_at": "2026-06-08T17:30:00+00:00",
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


def test_record_cost_sample_accepts_time_picker_seconds_for_tou() -> None:
    result = record_cost_sample(
        {"last_energy_kwh": 100.0, "last_sample_at": "2026-06-08T17:30:00+00:00"},
        circuit_id="hvac",
        timestamp=datetime(2026, 6, 8, 18, 0, tzinfo=UTC),
        energy_kwh=104.0,
        settings=CostSettings(
            default_rate_per_kwh=0.10,
            tou_rate_per_kwh=0.30,
            tou_start="17:00:00",
            tou_end="21:00:00",
            tou_weekdays=(0, 1, 2, 3, 4),
            tou_name="Peak",
        ),
    )

    assert result.active_rate_name == "Peak"
    assert result.current_rate_per_kwh == 0.30
    assert result.status == "tou_peak"


def test_record_cost_sample_handles_overnight_tou_period() -> None:
    result = record_cost_sample(
        {"last_energy_kwh": 10.0, "last_sample_at": "2026-06-08T22:30:00+00:00"},
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
    assert result.delta_kwh == 5.0
    assert result.cost_today_status == "unavailable"
    assert result.cycle_cost_status == "unavailable"
    assert history["last_energy_kwh"] == 505.0


def test_record_cost_sample_initializes_partial_periods_as_unavailable() -> None:
    result = record_cost_sample(
        {},
        circuit_id="fridge",
        timestamp=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
        energy_kwh=505.0,
        settings=CostSettings(default_rate_per_kwh=0.22),
    )

    assert result.cost_today is None
    assert result.cost_today_status == "unavailable"
    assert result.cycle_cost_status == "unavailable"


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


def test_record_cost_sample_accumulates_daily_cost_at_actual_tou_rates() -> None:
    history = {
        "last_energy_kwh": 100.0,
        "last_sample_at": "2026-06-08T16:00:00+00:00",
    }
    settings = CostSettings(
        default_rate_per_kwh=0.10,
        tou_rate_per_kwh=0.30,
        tou_start="17:00",
        tou_end="21:00",
    )

    off_peak = record_cost_sample(
        history,
        circuit_id="hvac",
        timestamp=datetime(2026, 6, 8, 16, 30, tzinfo=UTC),
        energy_kwh=102.0,
        settings=settings,
        time_zone="UTC",
    )
    record_cost_sample(
        history,
        circuit_id="hvac",
        timestamp=datetime(2026, 6, 8, 17, 0, tzinfo=UTC),
        energy_kwh=102.0,
        settings=settings,
        time_zone="UTC",
    )
    peak = record_cost_sample(
        history,
        circuit_id="hvac",
        timestamp=datetime(2026, 6, 8, 17, 30, tzinfo=UTC),
        energy_kwh=103.0,
        settings=settings,
        time_zone="UTC",
    )

    assert off_peak.cost_today == 0.20
    assert peak.cost_today == 0.50
    assert peak.cost_today_status == "actual"
    evidence = cost_evidence_payload(peak)
    assert evidence["cost_today"] == 0.50
    assert evidence["cost_today_status"] == "actual"


def test_record_cost_sample_resets_daily_cost_on_ha_local_day() -> None:
    history = {
        "last_energy_kwh": 100.0,
        "last_sample_at": "2026-06-09T03:40:00+00:00",
    }
    settings = CostSettings(default_rate_per_kwh=0.10)

    before_midnight = record_cost_sample(
        history,
        circuit_id="fridge",
        timestamp=datetime(2026, 6, 9, 3, 50, tzinfo=UTC),
        energy_kwh=102.0,
        settings=settings,
        time_zone="America/New_York",
    )
    at_midnight = record_cost_sample(
        history,
        circuit_id="fridge",
        timestamp=datetime(2026, 6, 9, 4, 0, tzinfo=UTC),
        energy_kwh=102.0,
        settings=settings,
        time_zone="America/New_York",
    )
    after_midnight = record_cost_sample(
        history,
        circuit_id="fridge",
        timestamp=datetime(2026, 6, 9, 4, 10, tzinfo=UTC),
        energy_kwh=103.0,
        settings=settings,
        time_zone="America/New_York",
    )

    assert before_midnight.cost_today == 0.20
    assert at_midnight.cost_today == 0.0
    assert after_midnight.cost_today == 0.10


def test_record_cost_sample_marks_tariff_boundary_gap_unavailable() -> None:
    history = {
        "last_energy_kwh": 100.0,
        "last_sample_at": "2026-06-08T16:00:00+00:00",
    }
    settings = CostSettings(
        default_rate_per_kwh=0.10,
        tou_rate_per_kwh=0.30,
        tou_start="17:00",
        tou_end="21:00",
    )
    record_cost_sample(
        history,
        circuit_id="hvac",
        timestamp=datetime(2026, 6, 8, 16, 30, tzinfo=UTC),
        energy_kwh=102.0,
        settings=settings,
        time_zone="UTC",
    )

    result = record_cost_sample(
        history,
        circuit_id="hvac",
        timestamp=datetime(2026, 6, 8, 17, 30, tzinfo=UTC),
        energy_kwh=103.0,
        settings=settings,
        time_zone="UTC",
    )

    assert result.delta_kwh == 1.0
    assert result.delta_cost == 0.0
    assert result.cost_today is None
    assert result.cost_today_status == "unavailable"


def test_record_cost_sample_detects_hidden_tariff_period_in_gap() -> None:
    result = record_cost_sample(
        {
            "last_energy_kwh": 100.0,
            "last_sample_at": "2026-06-08T16:00:00+00:00",
        },
        circuit_id="hvac",
        timestamp=datetime(2026, 6, 8, 22, 0, tzinfo=UTC),
        energy_kwh=104.0,
        settings=CostSettings(
            default_rate_per_kwh=0.10,
            tou_rate_per_kwh=0.30,
            tou_start="17:00",
            tou_end="21:00",
        ),
        time_zone="UTC",
    )

    assert result.delta_cost == 0.0
    assert result.cost_today_status == "unavailable"


@pytest.mark.parametrize(
    ("last_sample_at", "gap_sample_at", "later_sample_at", "time_zone"),
    [
        (
            "2026-06-09T03:50:00+00:00",
            datetime(2026, 6, 9, 4, 10, tzinfo=UTC),
            datetime(2026, 6, 9, 4, 20, tzinfo=UTC),
            "America/New_York",
        ),
        (
            "2026-06-08T16:50:00+00:00",
            datetime(2026, 6, 8, 17, 10, tzinfo=UTC),
            datetime(2026, 6, 8, 17, 20, tzinfo=UTC),
            "UTC",
        ),
    ],
    ids=("local-midnight", "tariff-boundary"),
)
def test_boundary_gap_keeps_daily_and_cycle_cost_incomplete_for_rest_of_day(
    last_sample_at: str,
    gap_sample_at: datetime,
    later_sample_at: datetime,
    time_zone: str,
) -> None:
    history = {"last_energy_kwh": 100.0, "last_sample_at": last_sample_at}
    settings = CostSettings(
        default_rate_per_kwh=0.10,
        tou_rate_per_kwh=0.30,
        tou_start="17:00",
        tou_end="21:00",
    )
    record_cost_sample(
        history,
        circuit_id="hvac",
        timestamp=gap_sample_at,
        energy_kwh=101.0,
        settings=settings,
        time_zone=time_zone,
    )

    result = record_cost_sample(
        history,
        circuit_id="hvac",
        timestamp=later_sample_at,
        energy_kwh=102.0,
        settings=settings,
        time_zone=time_zone,
    )
    evidence = cost_evidence_payload(result)

    assert (
        result.cost_today_status,
        result.cost_today,
        evidence.get("cycle_cost_status"),
    ) == ("unavailable", None, "unavailable")


def test_record_cost_sample_retains_only_cleanly_bracketed_complete_day() -> None:
    history: dict[str, object] = {}
    settings = CostSettings(default_rate_per_kwh=0.20)
    energy = 100.0

    for timestamp, sample_energy in (
        (datetime(2026, 7, 7, 0, 5, tzinfo=UTC), energy),
        (datetime(2026, 7, 7, 23, 55, tzinfo=UTC), energy + 1.0),
        (datetime(2026, 7, 8, 0, 5, tzinfo=UTC), energy + 1.0),
        (datetime(2026, 7, 8, 12, 0, tzinfo=UTC), energy + 11.0),
        (datetime(2026, 7, 8, 23, 55, tzinfo=UTC), energy + 11.0),
        (datetime(2026, 7, 9, 0, 5, tzinfo=UTC), energy + 11.0),
    ):
        record_cost_sample(
            history,
            circuit_id="fridge",
            timestamp=timestamp,
            energy_kwh=sample_energy,
            settings=settings,
            time_zone="UTC",
        )

    assert history["days"] == [
        {"date": "2026-07-08", "cost": 2.0, "complete": True}
    ]


def test_unconfigured_rate_stays_unavailable_across_local_midnight() -> None:
    history: dict[str, object] = {}
    settings = CostSettings(default_rate_per_kwh=None)
    record_cost_sample(
        history,
        circuit_id="fridge",
        timestamp=datetime(2026, 7, 7, 23, 55, tzinfo=UTC),
        energy_kwh=100.0,
        settings=settings,
        time_zone="UTC",
    )
    result = record_cost_sample(
        history,
        circuit_id="fridge",
        timestamp=datetime(2026, 7, 8, 0, 5, tzinfo=UTC),
        energy_kwh=101.0,
        settings=settings,
        time_zone="UTC",
    )

    assert result.status == "unconfigured"
    assert result.cost_today is None
    assert result.cost_today_status == "unavailable"
    assert result.cycle_cost_status == "unavailable"
