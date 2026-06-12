from __future__ import annotations

from custom_components.circuitsetup_energy_analyzer.models import SensorRole


def test_demo_module_exposes_shared_source_metadata() -> None:
    from custom_components.circuitsetup_energy_analyzer import demo

    assert demo.DEMO_SOURCE_ENTITY_PREFIX == "sensor.cs_energy_analyzer_demo_"
    assert "sensor.cs_energy_analyzer_demo_hvac_l1_active_power" in (
        demo.DEMO_SOURCE_ENTITY_IDS
    )
    assert "sensor.cs_energy_analyzer_demo_mains_l1_voltage" in (
        demo.DEMO_SOURCE_ENTITY_IDS
    )
    assert "sensor.cs_energy_analyzer_demo_hvac_voltage" not in (
        demo.DEMO_SOURCE_ENTITY_IDS
    )
    assert demo.DEMO_SOURCE_VALUES["washer"][SensorRole.REAL_POWER] == 420.0
    assert demo.DEMO_SOURCE_ROLE_METADATA[SensorRole.REAL_POWER] == {
        "device_class": "power",
        "state_class": "measurement",
        "unit": "W",
        "icon": "mdi:flash",
    }


def test_demo_module_exposes_shared_history_seed_templates() -> None:
    from custom_components.circuitsetup_energy_analyzer import demo

    assert demo.DEMO_HISTORY_SEED_VERSION == 1
    assert demo.demo_prior_usage("hvac", 9) == (
        24.0,
        28.5,
        31.2,
        27.8,
        33.1,
        29.4,
        30.6,
        24.0,
        28.5,
    )
    assert demo.demo_today_usage("car_charger", 151.4) == 26.0
    assert demo.demo_circuit_key_from_id(
        "cs_energy_analyzer_demo_water_heater"
    ) == "water_heater"
