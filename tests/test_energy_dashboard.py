from datetime import UTC, datetime

from custom_components.circuitsetup_energy_analyzer.energy_dashboard import (
    evaluate_energy_dashboard_readiness,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    SensorRef,
    SensorRole,
)
from custom_components.circuitsetup_energy_analyzer.normalize import SourceState


def test_energy_dashboard_readiness_accepts_energy_sensor_metadata() -> None:
    config = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.fridge_energy", SensorRole.ENERGY),),
    )

    result = evaluate_energy_dashboard_readiness(
        config,
        {
            "sensor.fridge_energy": SourceState(
                "sensor.fridge_energy",
                "42",
                "kWh",
                datetime(2026, 6, 3, 12, 0, tzinfo=UTC),
                device_class="energy",
                state_class="total_increasing",
            )
        },
    )

    assert result.status == "ready"
    assert result.ready_energy_entities == ("sensor.fridge_energy",)
    assert result.ready_power_entities == ()
    assert result.issues == ()


def test_energy_dashboard_readiness_accepts_power_sensor_handoff() -> None:
    config = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(SensorRef("sensor.hvac_power", SensorRole.REAL_POWER),),
    )

    result = evaluate_energy_dashboard_readiness(
        config,
        {
            "sensor.hvac_power": SourceState(
                "sensor.hvac_power",
                "4200",
                "W",
                datetime(2026, 6, 3, 12, 0, tzinfo=UTC),
                device_class="power",
                state_class="measurement",
            )
        },
    )

    assert result.status == "power_ready"
    assert result.ready_energy_entities == ()
    assert result.ready_power_entities == ("sensor.hvac_power",)
    assert "power input" in result.guidance.lower()


def test_energy_dashboard_readiness_reports_metadata_problems() -> None:
    config = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.fridge_energy", SensorRole.ENERGY),),
    )

    result = evaluate_energy_dashboard_readiness(
        config,
        {
            "sensor.fridge_energy": SourceState(
                "sensor.fridge_energy",
                "42",
                "kWh",
                datetime(2026, 6, 3, 12, 0, tzinfo=UTC),
                device_class=None,
                state_class=None,
            )
        },
    )

    assert result.status == "needs_metadata"
    assert result.ready_energy_entities == ()
    assert result.issues == (
        "sensor.fridge_energy missing device_class energy",
        "sensor.fridge_energy missing state_class total or total_increasing",
    )


def test_energy_dashboard_readiness_reports_missing_source() -> None:
    config = CircuitConfig(
        circuit_id="lights",
        name="Lights",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(),
    )

    result = evaluate_energy_dashboard_readiness(config, {})

    assert result.status == "needs_energy_source"
    assert result.guidance == (
        "Add a circuit energy sensor to Home Assistant's Energy Dashboard, "
        "or expose a power sensor that Home Assistant can integrate."
    )
