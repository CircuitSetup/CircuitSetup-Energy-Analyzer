from datetime import UTC, datetime, timedelta, timezone

import pytest

from custom_components.circuitsetup_energy_analyzer.aggregation import (
    aggregate_dual_phase,
)
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


@pytest.mark.parametrize("unit", ("kW", "KW", "Kw"))
def test_build_circuit_sample_converts_kw_to_watts(unit: str) -> None:
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
            unit,
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


def test_build_circuit_sample_normalizes_scaled_measurements() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    sensors = (
        SensorRef("sensor.power", SensorRole.REAL_POWER),
        SensorRef("sensor.current", SensorRole.CURRENT),
        SensorRef("sensor.voltage", SensorRole.VOLTAGE),
        SensorRef("sensor.apparent", SensorRole.APPARENT_POWER),
        SensorRef("sensor.reactive", SensorRole.REACTIVE_POWER),
    )
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        mode=CircuitMode.MAINS_NILM,
        appliance_profile=ApplianceProfile.MAINS_NILM,
        sensors=sensors,
    )
    states = {
        sensor.entity_id: SourceState(sensor.entity_id, state, unit, now)
        for sensor, state, unit in zip(
            sensors,
            ("0.001", "500", "0.24", "2", "3"),
            ("MW", "mA", "kV", "kVA", "kVAR"),
            strict=True,
        )
    }

    sample = build_circuit_sample(config, states, now)

    assert sample.real_power == 1000.0
    assert sample.current == 0.5
    assert sample.voltage == 240.0
    assert sample.apparent_power == 2000.0
    assert sample.reactive_power == 3000.0


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


def test_build_circuit_sample_treats_stale_numeric_power_as_unavailable() -> None:
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
            "180",
            "W",
            now - timedelta(minutes=30),
        )
    }

    sample = build_circuit_sample(config, states, now)

    assert sample.real_power_w is None
    assert sample.raw_real_power_w is None
    assert sample.power_flow_direction is None
    assert "sensor.fridge_power stale" in sample.quality_issues


def test_build_circuit_sample_suppresses_stale_current_only_while_inactive() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="dryer",
        name="Dryer",
        mode=CircuitMode.SINGLE_PHASE,
        appliance_profile=ApplianceProfile.DRYER,
        sensors=(
            SensorRef("sensor.dryer_power", SensorRole.REAL_POWER),
            SensorRef("sensor.dryer_current", SensorRole.CURRENT),
            SensorRef("sensor.dryer_voltage", SensorRole.VOLTAGE),
        ),
    )
    states = {
        "sensor.dryer_power": SourceState(
            "sensor.dryer_power",
            "10",
            "W",
            now,
        ),
        "sensor.dryer_current": SourceState(
            "sensor.dryer_current",
            "0.001",
            "A",
            now - timedelta(minutes=30),
        ),
        "sensor.dryer_voltage": SourceState(
            "sensor.dryer_voltage",
            "240",
            "V",
            now - timedelta(minutes=30),
        ),
    }

    inactive = build_circuit_sample(
        config,
        states,
        now,
        inactive_power_threshold_w=10.0,
    )
    states["sensor.dryer_power"] = SourceState(
        "sensor.dryer_power",
        "11",
        "W",
        now,
    )
    active = build_circuit_sample(
        config,
        states,
        now,
        inactive_power_threshold_w=10.0,
    )

    assert inactive.current is None
    assert "sensor.dryer_current stale" not in inactive.quality_issues
    assert "sensor.dryer_voltage stale" in inactive.quality_issues
    assert "sensor.dryer_current stale" in active.quality_issues


@pytest.mark.parametrize(
    ("role", "raw_state", "attribute"),
    (
        (SensorRole.REAL_POWER, "nan", "real_power_w"),
        (SensorRole.REAL_POWER, "+inf", "real_power_w"),
        (SensorRole.CURRENT, "-inf", "current"),
        (SensorRole.ENERGY, "nan", "energy"),
        (SensorRole.VOLTAGE, "inf", "voltage"),
        (SensorRole.POWER_FACTOR, "nan", "power_factor"),
    ),
)
def test_build_circuit_sample_rejects_non_finite_values(
    role: SensorRole,
    raw_state: str,
    attribute: str,
) -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    entity_id = f"sensor.fridge_{role.value}"
    config = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        mode=CircuitMode.SINGLE_PHASE,
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        sensors=(SensorRef(entity_id, role),),
    )
    states = {
        entity_id: SourceState(
            entity_id,
            raw_state,
            "W",
            now,
        )
    }

    sample = build_circuit_sample(config, states, now)

    assert getattr(sample, attribute) is None
    assert f"{entity_id} non_finite" in sample.quality_issues
    if role is SensorRole.REAL_POWER:
        assert sample.raw_real_power_w is None
        assert sample.power_flow_direction is None


def test_dual_phase_aggregate_rejects_non_finite_leg_value() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    left_config = CircuitConfig(
        circuit_id="hvac_left",
        name="HVAC Left",
        mode=CircuitMode.SINGLE_PHASE,
        appliance_profile=ApplianceProfile.HVAC,
        sensors=(SensorRef("sensor.hvac_left_power", SensorRole.REAL_POWER),),
    )
    right_config = CircuitConfig(
        circuit_id="hvac_right",
        name="HVAC Right",
        mode=CircuitMode.SINGLE_PHASE,
        appliance_profile=ApplianceProfile.HVAC,
        sensors=(SensorRef("sensor.hvac_right_power", SensorRole.REAL_POWER),),
    )
    left = build_circuit_sample(
        left_config,
        {
            "sensor.hvac_left_power": SourceState(
                "sensor.hvac_left_power",
                "nan",
                "W",
                now,
            )
        },
        now,
    )
    right = build_circuit_sample(
        right_config,
        {
            "sensor.hvac_right_power": SourceState(
                "sensor.hvac_right_power",
                "2400",
                "W",
                now,
            )
        },
        now,
    )

    result = aggregate_dual_phase("hvac", left, right)

    assert left.real_power_w is None
    assert result.leg_a.real_power is None
    assert result.leg_b.real_power == 2400.0
    assert result.combined_real_power is None
    assert "sensor.hvac_left_power non_finite" in result.quality_issues


def test_build_circuit_sample_rejects_large_future_timestamp() -> None:
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
            "180",
            "W",
            now + timedelta(minutes=5),
        )
    }

    sample = build_circuit_sample(config, states, now)

    assert sample.real_power_w is None
    assert sample.raw_real_power_w is None
    assert "sensor.fridge_power future_timestamp" in sample.quality_issues


def test_build_circuit_sample_rejects_naive_source_timestamp() -> None:
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
            "180",
            "W",
            datetime(2026, 6, 2, 12, 0),
        )
    }

    sample = build_circuit_sample(config, states, now)

    assert sample.real_power_w is None
    assert sample.raw_real_power_w is None
    assert "sensor.fridge_power naive_timestamp" in sample.quality_issues


def test_build_circuit_sample_accepts_non_utc_aware_timestamp() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    eastern = timezone(timedelta(hours=-4))
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
            "180",
            "W",
            datetime(2026, 6, 2, 8, 0, tzinfo=eastern),
        )
    }

    sample = build_circuit_sample(config, states, now)

    assert sample.real_power_w == 180.0
    assert sample.quality_issues == ()


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


@pytest.mark.parametrize(
    ("power_w", "has_issue"),
    ((-4.99, False), (-5.0, True)),
)
def test_negative_load_power_repair_starts_at_five_watts(
    power_w: float,
    has_issue: bool,
) -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        mode=CircuitMode.SINGLE_PHASE,
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
    )
    sample = build_circuit_sample(
        config,
        {
            "sensor.fridge_power": SourceState(
                "sensor.fridge_power",
                str(power_w),
                "W",
                now,
            )
        },
        now,
    )

    assert ("negative_real_power_load" in " ".join(sample.quality_issues)) is has_issue


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
