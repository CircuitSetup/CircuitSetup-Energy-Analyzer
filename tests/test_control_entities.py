from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_ENTITY_DETAIL_LEVEL,
    DOMAIN,
    PLATFORMS,
)
from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    SensorRef,
    SensorRole,
)


def _platform_value(platform: object) -> str:
    return str(getattr(platform, "value", platform))


def _assert_base_description_defaults(description: object) -> None:
    assert description.device_class is None
    assert description.entity_category is None
    assert description.entity_registry_enabled_default is True
    assert description.entity_registry_visible_default is True
    assert description.force_update is False
    assert description.has_entity_name is False
    assert description.translation_key is None
    assert description.translation_placeholders is None
    assert description.unit_of_measurement is None


def _disable_registry_pruning(monkeypatch: pytest.MonkeyPatch, module: object) -> None:
    monkeypatch.setattr(
        module,
        "prune_stale_entity_registry_entries",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        module,
        "prune_stale_device_registry_entries",
        lambda *args, **kwargs: None,
    )


def _circuit() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
    )


class _FakeCoordinator:
    def __init__(self) -> None:
        self.data = AnalyzerState(sensitivity_by_circuit={"fridge": "quiet"})
        self.circuit_configs = (_circuit(),)
        self.options = {CONF_ENTITY_DETAIL_LEVEL: "standard"}
        self.entry_data = {}
        self.store_data = SimpleNamespace(
            energy_goal_settings_by_circuit={
                "fridge": {"daily_goal_kwh": 4.5},
            }
        )
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def async_relearn_baseline(self, circuit_id: str) -> None:
        self.calls.append(("async_relearn_baseline", (circuit_id,)))

    async def async_start_maintenance(
        self,
        circuit_id: str,
        note: str = "",
        duration: str | None = None,
        relearn_on_end: bool = False,
    ) -> None:
        self.calls.append(
            ("async_start_maintenance", (circuit_id, note, duration, relearn_on_end))
        )

    async def async_end_maintenance(
        self,
        circuit_id: str,
        relearn: bool = False,
    ) -> None:
        self.calls.append(("async_end_maintenance", (circuit_id, relearn)))

    async def async_pause_alerts(
        self,
        circuit_id: str,
        duration: str | None = None,
    ) -> None:
        self.calls.append(("async_pause_alerts", (circuit_id, duration)))

    async def async_run_mapping_checks(self) -> None:
        self.calls.append(("async_run_mapping_checks", ()))

    async def async_recalculate_setting_recommendations(
        self,
        circuit_id: str | None = None,
    ) -> None:
        self.calls.append(
            ("async_recalculate_setting_recommendations", (circuit_id,))
        )

    async def async_create_dashboard(self) -> None:
        self.calls.append(("async_create_dashboard", ()))

    async def async_set_circuit_sensitivity(
        self,
        circuit_id: str,
        preset: str,
    ) -> None:
        self.calls.append(("async_set_circuit_sensitivity", (circuit_id, preset)))

    async def async_set_entity_detail_level(self, detail_level: str) -> None:
        self.calls.append(("async_set_entity_detail_level", (detail_level,)))

    async def async_set_energy_goal_settings(
        self,
        circuit_id: str,
        daily_goal_kwh: float,
        goal_alert_ratio: object = None,
    ) -> None:
        self.calls.append(
            ("async_set_energy_goal_settings", (circuit_id, daily_goal_kwh, None))
        )


def _hass_with(coordinator: _FakeCoordinator) -> SimpleNamespace:
    return SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})


def test_platforms_include_daily_control_entities() -> None:
    assert {_platform_value(platform) for platform in PLATFORMS} == {
        "sensor",
        "binary_sensor",
        "button",
        "select",
        "number",
    }


@pytest.mark.asyncio
async def test_button_setup_entry_adds_circuit_and_global_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        button,
    )

    _disable_registry_pruning(monkeypatch, button)
    coordinator = _FakeCoordinator()
    added_entities = []

    await button.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    by_unique_id = {entity.unique_id: entity for entity in added_entities}
    assert set(by_unique_id) == {
        "entry-1_fridge_relearn_baseline",
        "entry-1_fridge_start_maintenance",
        "entry-1_fridge_end_maintenance",
        "entry-1_fridge_pause_alerts",
        "entry-1_run_mapping_checks",
        "entry-1_recalculate_suggestions",
        "entry-1_create_dashboard",
    }
    assert by_unique_id["entry-1_fridge_relearn_baseline"].device_info == {
        "identifiers": {(DOMAIN, "entry-1_fridge")},
        "name": "Kitchen Fridge",
        "manufacturer": "CircuitSetup",
    }
    assert (
        by_unique_id["entry-1_fridge_relearn_baseline"].suggested_object_id
        == "fridge_relearn_baseline"
    )
    assert (
        by_unique_id["entry-1_run_mapping_checks"].suggested_object_id
        == "circuitsetup_energy_analyzer_run_mapping_checks"
    )
    for entity in added_entities:
        _assert_base_description_defaults(entity.entity_description)

    for unique_id in (
        "entry-1_fridge_relearn_baseline",
        "entry-1_fridge_start_maintenance",
        "entry-1_fridge_end_maintenance",
        "entry-1_fridge_pause_alerts",
        "entry-1_run_mapping_checks",
        "entry-1_recalculate_suggestions",
        "entry-1_create_dashboard",
    ):
        await by_unique_id[unique_id].async_press()

    assert coordinator.calls == [
        ("async_relearn_baseline", ("fridge",)),
        ("async_start_maintenance", ("fridge", "", None, False)),
        ("async_end_maintenance", ("fridge", False)),
        ("async_pause_alerts", ("fridge", None)),
        ("async_run_mapping_checks", ()),
        ("async_recalculate_setting_recommendations", (None,)),
        ("async_create_dashboard", ()),
    ]


@pytest.mark.asyncio
async def test_select_setup_entry_adds_sensitivity_and_detail_level_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        select,
    )

    _disable_registry_pruning(monkeypatch, select)
    coordinator = _FakeCoordinator()
    added_entities = []

    await select.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    by_unique_id = {entity.unique_id: entity for entity in added_entities}
    assert set(by_unique_id) == {
        "entry-1_fridge_alert_sensitivity",
        "entry-1_entity_detail_level",
    }

    sensitivity = by_unique_id["entry-1_fridge_alert_sensitivity"]
    assert sensitivity.name == "Kitchen Fridge Alert Sensitivity"
    assert sensitivity.suggested_object_id == "fridge_alert_sensitivity"
    assert sensitivity.options == ["quiet", "balanced", "sensitive"]
    assert sensitivity.current_option == "quiet"
    _assert_base_description_defaults(sensitivity.entity_description)
    assert sensitivity.entity_description.options is None

    detail_level = by_unique_id["entry-1_entity_detail_level"]
    assert detail_level.name == "CircuitSetup Energy Analyzer Entity Detail Level"
    assert detail_level.options == ["simple", "standard", "expert"]
    assert detail_level.current_option == "standard"

    await sensitivity.async_select_option("sensitive")
    await detail_level.async_select_option("expert")

    assert coordinator.calls == [
        ("async_set_circuit_sensitivity", ("fridge", "sensitive")),
        ("async_set_entity_detail_level", ("expert",)),
    ]


@pytest.mark.asyncio
async def test_number_setup_entry_adds_daily_energy_goal_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        number,
    )

    _disable_registry_pruning(monkeypatch, number)
    coordinator = _FakeCoordinator()
    added_entities = []

    await number.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    assert len(added_entities) == 1
    goal = added_entities[0]
    assert goal.unique_id == "entry-1_fridge_daily_energy_goal"
    assert goal.name == "Kitchen Fridge Daily Energy Goal"
    assert goal.suggested_object_id == "fridge_daily_energy_goal"
    assert goal.native_value == 4.5
    assert goal.native_min_value == 0.0
    assert goal.native_step == 0.1
    assert goal.native_unit_of_measurement == "kWh"
    _assert_base_description_defaults(goal.entity_description)
    assert goal.entity_description.mode is None

    await goal.async_set_native_value(6.25)

    assert coordinator.calls == [
        ("async_set_energy_goal_settings", ("fridge", 6.25, None))
    ]
