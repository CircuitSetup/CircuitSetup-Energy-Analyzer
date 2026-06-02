from custom_components.circuitsetup_energy_analyzer.discovery import (
    DiscoveredSensor,
    infer_sensor_role,
    score_circuitsetup_candidate,
)
from custom_components.circuitsetup_energy_analyzer.models import SensorRole


def test_infer_sensor_role_from_entity_id_and_friendly_name() -> None:
    cases = [
        ("sensor.energy_meter_voltage_a", "Voltage A", SensorRole.VOLTAGE),
        ("sensor.energy_meter_current_1", "Current 1", SensorRole.CURRENT),
        ("sensor.energy_meter_power_1", "Power 1", SensorRole.REAL_POWER),
        (
            "sensor.energy_meter_reactive_power_1",
            "Reactive Power 1",
            SensorRole.REACTIVE_POWER,
        ),
        (
            "sensor.energy_meter_apparent_power_1",
            "Apparent Power 1",
            SensorRole.APPARENT_POWER,
        ),
        (
            "sensor.energy_meter_power_factor_1",
            "Power Factor 1",
            SensorRole.POWER_FACTOR,
        ),
    ]

    for entity_id, friendly_name, role in cases:
        assert infer_sensor_role(entity_id, friendly_name) is role


def test_score_circuitsetup_candidate_prefers_esphome_meter_metadata() -> None:
    sensor = DiscoveredSensor(
        entity_id="sensor.circuitsetup_energy_meter_power_1",
        name="CircuitSetup Energy Meter Power 1",
        role=SensorRole.REAL_POWER,
        device_id="device-1",
        unit="W",
        device_class="power",
        integration_domain="esphome",
    )

    assert score_circuitsetup_candidate(sensor) >= 5
