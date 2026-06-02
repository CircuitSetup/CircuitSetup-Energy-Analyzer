from custom_components.circuitsetup_energy_analyzer.discovery import DiscoveredSensor
from custom_components.circuitsetup_energy_analyzer.mapping import (
    ChannelGroup,
    suggest_dual_phase_pairs,
)
from custom_components.circuitsetup_energy_analyzer.models import SensorRole


def discovered_sensor(
    entity_id: str,
    name: str,
    role: SensorRole | None = SensorRole.REAL_POWER,
    device_id: str | None = "panel",
    unit: str | None = "W",
    device_class: str | None = "power",
    integration_domain: str | None = "esphome",
) -> DiscoveredSensor:
    return DiscoveredSensor(
        entity_id=entity_id,
        name=name,
        role=role,
        device_id=device_id,
        unit=unit,
        device_class=device_class,
        integration_domain=integration_domain,
    )


def test_dual_phase_suggestions_pair_neighboring_channels() -> None:
    candidates = [
        discovered_sensor("sensor.panel_ch1_power", "HVAC L1 Power"),
        discovered_sensor("sensor.panel_ch2_power", "HVAC L2 Power"),
        discovered_sensor("sensor.panel_ch3_power", "Fridge Power"),
    ]

    suggestions = suggest_dual_phase_pairs(candidates)

    assert suggestions[0].left.entity_id == "sensor.panel_ch1_power"
    assert suggestions[0].right.entity_id == "sensor.panel_ch2_power"
    assert suggestions[0].confidence >= 0.6
    assert "neighboring channels" in suggestions[0].reasons


def test_dual_phase_suggestions_do_not_pair_different_meter_prefixes() -> None:
    candidates = [
        discovered_sensor(
            "sensor.circuitsetup_energy_meter_558f54_ct1_watts",
            "CircuitSetup Energy Meter 558f54 CT1 Watts",
            device_id=None,
        ),
        discovered_sensor(
            "sensor.energy_meter_2af0e8_ct2_watts",
            "CircuitSetup Energy Meter 24x 2af0e8 CT2 Watts",
            device_id=None,
        ),
    ]

    assert suggest_dual_phase_pairs(candidates) == []


def test_channel_group_rejects_missing_real_power() -> None:
    group = ChannelGroup(
        group_id="fridge",
        sensors=(
            discovered_sensor(
                "sensor.panel_ch3_voltage",
                "Fridge Voltage",
                role=SensorRole.VOLTAGE,
                unit="V",
                device_class="voltage",
            ),
        ),
    )

    assert group.has_role(SensorRole.REAL_POWER) is False
