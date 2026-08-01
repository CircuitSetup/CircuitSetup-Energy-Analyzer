import asyncio

from custom_components.circuitsetup_energy_analyzer.discovery import (
    async_discover_energy_source_entities_for_devices,
    async_discover_utility_energy_entities,
    async_discover_utility_statistic_ids,
    infer_sensor_role,
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
        self.recorder_statistic_ids: list[str] = []


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


def test_infer_sensor_role_from_circuitsetup_live_sensor_names() -> None:
    cases = [
        (
            "sensor.energy_meter_2b01f8_ct1_watts",
            "CircuitSetup Energy Meter CT1 Watts",
            SensorRole.REAL_POWER,
        ),
        (
            "sensor.energy_meter_2b01f8_ct1_amps",
            "CircuitSetup Energy Meter CT1 Amps",
            SensorRole.CURRENT,
        ),
        (
            "sensor.energy_meter_2b01f8_circuitsetup_energy_meter_total_watts",
            "CircuitSetup Energy Meter Total Watts",
            SensorRole.REAL_POWER,
        ),
        (
            "sensor.energy_meter_2b01f8_circuitsetup_energy_meter_total_amps",
            "CircuitSetup Energy Meter Total Amps",
            SensorRole.CURRENT,
        ),
        (
            "sensor.energy_meter_2b01f8_circuitsetup_energy_meter_total_kwh",
            "CircuitSetup Energy Meter Total kWh",
            SensorRole.ENERGY,
        ),
    ]

    for entity_id, friendly_name, role in cases:
        assert infer_sensor_role(entity_id, friendly_name) is role


def test_async_discover_energy_sources_includes_generic_sensors() -> None:
    import custom_components.circuitsetup_energy_analyzer.discovery as discovery

    hass = FakeHass(
        [
            FakeState(
                "sensor.random_power",
                {
                    "friendly_name": "Random Power",
                    "device_class": "power",
                    "unit_of_measurement": "W",
                },
            ),
            FakeState(
                "sensor.panel_reactive_power",
                {
                    "friendly_name": "Panel Reactive Power",
                    "unit_of_measurement": "var",
                },
            ),
            FakeState(
                "sensor.living_room_temperature",
                {
                    "friendly_name": "Living Room Temperature",
                    "device_class": "temperature",
                    "unit_of_measurement": "degF",
                },
            ),
        ]
    )

    entity_ids = asyncio.run(discovery.async_discover_energy_source_entities(hass))

    assert entity_ids == [
        "sensor.panel_reactive_power",
        "sensor.random_power",
    ]


def test_async_discover_energy_sources_for_devices_expands_selected_meter() -> None:
    hass = FakeHass(
        [
            FakeState(
                "sensor.panel_ct1_watts",
                {
                    "friendly_name": "Panel CT1 Watts",
                    "device_class": "power",
                    "device_id": "meter-device",
                    "unit_of_measurement": "W",
                },
            ),
            FakeState(
                "sensor.panel_ct1_amps",
                {
                    "friendly_name": "Panel CT1 Amps",
                    "device_class": "current",
                    "device_id": "meter-device",
                    "unit_of_measurement": "A",
                },
            ),
            FakeState(
                "sensor.panel_temperature",
                {
                    "friendly_name": "Panel Temperature",
                    "device_class": "temperature",
                    "device_id": "meter-device",
                    "unit_of_measurement": "degF",
                },
            ),
            FakeState(
                "sensor.other_power",
                {
                    "friendly_name": "Other Power",
                    "device_class": "power",
                    "device_id": "other-device",
                    "unit_of_measurement": "W",
                },
            ),
        ]
    )

    entity_ids = asyncio.run(
        async_discover_energy_source_entities_for_devices(hass, ["meter-device"])
    )

    assert entity_ids == [
        "sensor.panel_ct1_amps",
        "sensor.panel_ct1_watts",
    ]


def test_async_discover_utility_energy_entities_prefers_opower_and_billing_kwh() -> (
    None
):
    hass = FakeHass(
        [
            FakeState(
                "sensor.typical_monthly_electric_usage",
                {
                    "friendly_name": "ELEC Typical monthly electric usage",
                    "device_class": "energy",
                    "unit_of_measurement": "kWh",
                },
            ),
            FakeState(
                "sensor.opower_current_bill_usage",
                {
                    "friendly_name": "Opower current bill usage",
                    "device_class": "energy",
                    "unit_of_measurement": "kWh",
                },
            ),
            FakeState(
                "sensor.kitchen_lights_energy",
                {
                    "friendly_name": "Kitchen Lights Energy",
                    "device_class": "energy",
                    "unit_of_measurement": "kWh",
                },
            ),
            FakeState(
                "sensor.typical_monthly_electric_cost",
                {
                    "friendly_name": "Typical monthly electric cost",
                    "device_class": "monetary",
                    "unit_of_measurement": "USD",
                },
            ),
        ]
    )

    assert asyncio.run(async_discover_utility_energy_entities(hass)) == [
        "sensor.opower_current_bill_usage",
        "sensor.typical_monthly_electric_usage",
    ]


def test_async_discover_utility_statistic_ids_filters_recorder_metadata() -> None:
    hass = FakeHass([])
    hass.recorder_statistic_ids = [
        "sensor.kitchen_lights_energy",
        "opower:utility_elec_consumption",
        "utility:gas_consumption",
        "sensor.typical_monthly_electric_usage",
    ]

    assert asyncio.run(async_discover_utility_statistic_ids(hass)) == [
        "opower:utility_elec_consumption",
        "sensor.typical_monthly_electric_usage",
        "utility:gas_consumption",
    ]


def test_async_discover_energy_sources_returns_empty_without_hass() -> None:
    import custom_components.circuitsetup_energy_analyzer.discovery as discovery

    assert asyncio.run(discovery.async_discover_energy_source_entities(None)) == []
