from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    PowerFlowMode,
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


def test_build_circuit_sample_preserves_energy_reading() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        mode=CircuitMode.SINGLE_PHASE,
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        sensors=(SensorRef("sensor.fridge_energy", SensorRole.ENERGY),),
    )
    states = {
        "sensor.fridge_energy": SourceState(
            "sensor.fridge_energy",
            "12.5",
            "kWh",
            now,
        )
    }

    sample = build_circuit_sample(config, states, now)

    assert sample.energy == 12.5


def test_build_circuit_sample_converts_wh_energy_to_kwh() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        mode=CircuitMode.SINGLE_PHASE,
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        sensors=(SensorRef("sensor.fridge_energy", SensorRole.ENERGY),),
    )
    states = {
        "sensor.fridge_energy": SourceState(
            "sensor.fridge_energy",
            "12500",
            "Wh",
            now,
        )
    }

    sample = build_circuit_sample(config, states, now)

    assert sample.energy == 12.5


def test_build_circuit_sample_flags_negative_load_power() -> None:
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
            "-180",
            "W",
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

    assert sample.raw_real_power_w == -180.0
    assert sample.real_power_w is None
    assert sample.current == 1.7
    assert sample.power_flow_direction == "unexpected_export"
    assert "sensor.fridge_power negative_real_power_load" in sample.quality_issues


def test_build_circuit_sample_analyzes_generation_export_power() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="solar",
        name="Solar inverter",
        mode=CircuitMode.SINGLE_PHASE,
        appliance_profile=ApplianceProfile.SOLAR_INVERTER,
        power_flow=PowerFlowMode.GENERATION,
        sensors=(SensorRef("sensor.solar_power", SensorRole.REAL_POWER),),
    )
    states = {
        "sensor.solar_power": SourceState(
            "sensor.solar_power",
            "-3.2",
            "kW",
            now,
        )
    }

    sample = build_circuit_sample(config, states, now)

    assert sample.raw_real_power_w == -3200.0
    assert sample.real_power_w == 3200.0
    assert sample.power_flow_direction == "export"
    assert sample.quality_issues == ()


def test_build_circuit_sample_preserves_mains_net_signed_power() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        mode=CircuitMode.MAINS_NILM,
        appliance_profile=ApplianceProfile.MAINS_NILM,
        power_flow=PowerFlowMode.MAINS_NET,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    states = {
        "sensor.mains_power": SourceState(
            "sensor.mains_power",
            "-900",
            "W",
            now,
        )
    }

    sample = build_circuit_sample(config, states, now)

    assert sample.raw_real_power_w == -900.0
    assert sample.real_power_w == -900.0
    assert sample.power_flow_direction == "export"
    assert sample.quality_issues == ()
