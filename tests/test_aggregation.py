from datetime import UTC, datetime
from typing import get_type_hints

from custom_components.circuitsetup_energy_analyzer.aggregation import (
    AggregatedDualPhaseSample,
    aggregate_dual_phase,
)
from custom_components.circuitsetup_energy_analyzer.models import CircuitSample, LegSample


def circuit_sample(
    watts: float | None,
    voltage: float | None,
    *,
    timestamp: datetime | None = None,
    circuit_id: str = "hvac_leg",
) -> CircuitSample:
    return CircuitSample(
        timestamp=timestamp or datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id=circuit_id,
        real_power=watts,
        current=10.0,
        voltage=voltage,
        reactive_power=100.0,
        apparent_power=watts + 50.0 if watts is not None else None,
        power_factor=0.95,
        frequency=60.0,
        energy=1.5,
    )


def test_aggregate_dual_phase_sums_power_and_tracks_imbalance() -> None:
    timestamp = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    left = circuit_sample(2400.0, 121.0, timestamp=timestamp)
    right = circuit_sample(1800.0, 119.0, timestamp=timestamp)

    result = aggregate_dual_phase("hvac", left, right)

    assert result.circuit_id == "hvac"
    assert result.leg_a.real_power == 2400.0
    assert result.leg_b.real_power == 1800.0
    assert result.combined_real_power == 4200.0
    assert result.combined_reactive_power == 200.0
    assert result.combined_apparent_power == 4300.0
    assert result.combined_current == 20.0
    assert result.average_voltage == 120.0
    assert result.average_power_factor == 0.95
    assert result.frequency == 60.0
    assert result.energy == 3.0
    assert result.voltage_difference == 2.0
    assert round(result.leg_power_imbalance_ratio, 3) == 0.286
    assert result.quality_issues == ()


def test_aggregate_dual_phase_flags_one_leg_missing_power() -> None:
    left = circuit_sample(2400.0, 121.0)
    right = circuit_sample(0.0, 119.0)

    result = aggregate_dual_phase("hvac", left, right)

    assert "one_leg_low_power" in result.quality_issues


def test_aggregate_dual_phase_return_type_exposes_aggregate_fields() -> None:
    hints = get_type_hints(aggregate_dual_phase)

    assert hints["return"] is AggregatedDualPhaseSample


def test_aggregate_dual_phase_uses_newest_leg_timestamp() -> None:
    earlier = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    later = datetime(2026, 6, 2, 12, 1, tzinfo=UTC)
    left = circuit_sample(2400.0, 121.0, timestamp=earlier)
    right = circuit_sample(1800.0, 119.0, timestamp=later)

    result = aggregate_dual_phase("hvac", left, right)

    assert result.timestamp == later


def test_aggregate_dual_phase_preserves_missing_leg_power() -> None:
    left = circuit_sample(2400.0, 121.0)
    right = circuit_sample(None, 119.0)

    result = aggregate_dual_phase("hvac", left, right)

    assert result.leg_b.real_power is None
    assert result.leg_power_imbalance_ratio is None


def test_leg_sample_real_power_allows_missing_values() -> None:
    hints = get_type_hints(LegSample)

    assert hints["real_power"] == float | None
