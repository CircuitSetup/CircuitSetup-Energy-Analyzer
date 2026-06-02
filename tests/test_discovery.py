import asyncio

from custom_components.circuitsetup_energy_analyzer.discovery import (
    DiscoveredSensor,
    async_discover_sensors,
    infer_sensor_role,
    score_circuitsetup_candidate,
)
from custom_components.circuitsetup_energy_analyzer.models import SensorRole


class FakeState:
    def __init__(self, entity_id: str, attributes: dict[str, str]) -> None:
        self.entity_id = entity_id
        self.attributes = attributes


class FakeStates:
    def __init__(self, states: list[FakeState]) -> None:
        self._states = {state.entity_id: state for state in states}

    def async_entity_ids(self, domain: str) -> list[str]:
        prefix = f"{domain}."
        return [
            entity_id
            for entity_id in reversed(self._states)
            if entity_id.startswith(prefix)
        ]

    def get(self, entity_id: str) -> FakeState | None:
        return self._states.get(entity_id)


class FakeHass:
    def __init__(self, states: list[FakeState]) -> None:
        self.states = FakeStates(states)


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


def test_async_discover_sensors_returns_candidates_sorted_by_entity_id() -> None:
    hass = FakeHass(
        [
            FakeState(
                "sensor.circuitsetup_energy_meter_power_2",
                {
                    "friendly_name": "CircuitSetup Energy Meter Power 2",
                    "device_class": "power",
                    "integration_domain": "esphome",
                    "unit_of_measurement": "W",
                },
            ),
            FakeState(
                "sensor.circuitsetup_energy_meter_power_1",
                {
                    "friendly_name": "CircuitSetup Energy Meter Power 1",
                    "device_class": "power",
                    "integration_domain": "esphome",
                    "unit_of_measurement": "W",
                },
            ),
        ]
    )

    sensors = asyncio.run(async_discover_sensors(hass))

    assert [sensor.entity_id for sensor in sensors] == [
        "sensor.circuitsetup_energy_meter_power_1",
        "sensor.circuitsetup_energy_meter_power_2",
    ]


def test_async_discover_sensors_filters_low_score_generic_sensors() -> None:
    hass = FakeHass(
        [
            FakeState(
                "sensor.circuitsetup_energy_meter_power_1",
                {
                    "friendly_name": "CircuitSetup Energy Meter Power 1",
                    "device_class": "power",
                    "integration_domain": "esphome",
                    "unit_of_measurement": "W",
                },
            ),
            FakeState(
                "sensor.random_power",
                {
                    "friendly_name": "Random Power",
                    "device_class": "power",
                    "unit_of_measurement": "W",
                },
            ),
        ]
    )

    sensors = asyncio.run(async_discover_sensors(hass))

    assert [sensor.entity_id for sensor in sensors] == [
        "sensor.circuitsetup_energy_meter_power_1",
    ]
    assert score_circuitsetup_candidate(sensors[0]) >= 3
    assert sensors[0].integration_domain == "esphome"


def test_async_discover_sensors_returns_empty_list_without_hass() -> None:
    assert asyncio.run(async_discover_sensors(None)) == []
