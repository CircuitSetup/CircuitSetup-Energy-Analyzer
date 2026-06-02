from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    SensorRef,
    SensorRole,
)
from custom_components.circuitsetup_energy_analyzer.normalize import (
    SourceState,
    build_circuit_sample,
)


def test_build_circuit_sample_converts_kw_to_watts() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        mode=CircuitMode.SINGLE_PHASE,
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        sensors=(
            SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),
            SensorRef("sensor.fridge_current", SensorRole.CURRENT),
        ),
    )
    states = {
        "sensor.fridge_power": SourceState(
            "sensor.fridge_power",
            "0.18",
            "kW",
            now,
        ),
        "sensor.fridge_current": SourceState(
            "sensor.fridge_current",
            "1.7",
            "A",
            now,
        ),
    }

    sample = build_circuit_sample(config, states, now)

    assert sample.real_power_w == 180.0
    assert sample.current == 1.7
    assert sample.quality_issues == ()


def test_build_circuit_sample_marks_stale_and_unavailable_values() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        mode=CircuitMode.SINGLE_PHASE,
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
    )
    states = {
        "sensor.fridge_power": SourceState(
            "sensor.fridge_power",
            "unavailable",
            "W",
            now - timedelta(minutes=30),
        )
    }

    sample = build_circuit_sample(config, states, now)

    assert sample.real_power_w is None
    assert "sensor.fridge_power unavailable" in sample.quality_issues
    assert "sensor.fridge_power stale" in sample.quality_issues
