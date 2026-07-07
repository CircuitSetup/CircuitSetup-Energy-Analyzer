from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from custom_components.circuitsetup_energy_analyzer.models import SensorRole


def test_demo_module_exposes_shared_source_metadata() -> None:
    from custom_components.circuitsetup_energy_analyzer import demo

    assert demo.DEMO_SOURCE_ENTITY_PREFIX == "sensor.cs_energy_analyzer_demo_"
    assert Path(demo.__file__).with_name("demo_sources.json").exists()
    assert "sensor.cs_energy_analyzer_demo_hvac_l1_active_power" in (
        demo.DEMO_SOURCE_ENTITY_IDS
    )
    assert "sensor.cs_energy_analyzer_demo_sump_pump_active_power" in (
        demo.DEMO_SOURCE_ENTITY_IDS
    )
    assert "sensor.cs_energy_analyzer_demo_oven_l2_active_power" in (
        demo.DEMO_SOURCE_ENTITY_IDS
    )
    assert "sensor.cs_energy_analyzer_demo_mains_l1_voltage" in (
        demo.DEMO_SOURCE_ENTITY_IDS
    )
    assert "sensor.cs_energy_analyzer_demo_hvac_voltage" not in (
        demo.DEMO_SOURCE_ENTITY_IDS
    )
    assert demo.DEMO_SOURCE_VALUES["washer"][SensorRole.REAL_POWER] == 420.0
    assert demo.DEMO_SOURCE_VALUES["microwave"][SensorRole.REAL_POWER] == 1250.0
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
    assert demo.demo_prior_usage("sump_pump", 3) == (0.4, 0.9, 0.3)
    assert demo.demo_today_usage("microwave", 3.2) == 0.8
    assert demo.demo_circuit_key_from_id(
        "cs_energy_analyzer_demo_water_heater"
    ) == "water_heater"


def test_demo_nilm_workspace_seed_does_not_read_json_at_runtime(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import demo

    def fail_read_text(self: Path, *args: object, **kwargs: object) -> str:
        raise AssertionError(f"unexpected runtime read: {self}")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    seed = demo.demo_nilm_workspace_seed(
        datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
    )

    assert seed["assignments"][0]["display_name"] == "Demo Pool Pump"


def test_demo_module_loads_nilm_workspace_seed_from_json() -> None:
    from custom_components.circuitsetup_energy_analyzer import demo

    seed = demo.demo_nilm_workspace_seed(datetime(2026, 6, 7, 12, 0, tzinfo=UTC))

    assert Path(demo.__file__).with_name("demo_nilm_workspace.json").exists()
    assert seed["assignments"][0]["display_name"] == "Demo Pool Pump"
    assert seed["label_intervals"][0]["start"] == "2026-06-07T09:50:00+00:00"
    assert seed["edges"][0]["timestamp"] == "2026-06-07T07:00:00+00:00"


def test_nilm_demo_scenario_is_not_embedded_in_coordinator() -> None:
    coordinator_source = (
        Path(__file__).parents[1]
        / "custom_components"
        / "circuitsetup_energy_analyzer"
        / "coordinator.py"
    ).read_text(encoding="utf-8")

    assert "demo_motor_load_l1" not in coordinator_source
