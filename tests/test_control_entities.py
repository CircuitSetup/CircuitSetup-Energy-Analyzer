from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_ADVANCED_SETTINGS,
    CONF_ENTITY_DETAIL_LEVEL,
    CONF_LEGACY_ENTITY_COMPATIBILITY_KEYS,
    CONF_SELECTED_ENTITY_GROUPS,
    DASHBOARD_LAYOUT_EXPERT,
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
        sensors=(
            SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),
            SensorRef("sensor.fridge_energy", SensorRole.ENERGY),
        ),
    )


def _power_only_circuit() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="garage_freezer",
        name="Garage Freezer",
        appliance_profile=ApplianceProfile.FREEZER,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.garage_freezer_power", SensorRole.REAL_POWER),),
    )


def _misclassified_energy_circuit() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="air_handler",
        name="Air Handler",
        appliance_profile=ApplianceProfile.HVAC_BLOWER,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(
            SensorRef("sensor.air_handler_power", SensorRole.REAL_POWER),
            SensorRef("sensor.air_handler_instant", SensorRole.ENERGY, unit="W"),
        ),
    )


def _dict_energy_circuit() -> dict[str, object]:
    return {
        "circuit_id": "dishwasher",
        "name": "Dishwasher",
        "appliance_profile": "washer",
        "mode": "single_phase",
        "sensors": [
            {"entity_id": "sensor.dishwasher_power", "role": "real_power"},
            {"entity_id": "sensor.dishwasher_energy", "role": "energy"},
        ],
    }


def _mains_circuit() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(
            SensorRef("sensor.mains_power", SensorRole.REAL_POWER),
            SensorRef("sensor.mains_energy", SensorRole.ENERGY),
        ),
    )


class _FakeCoordinator:
    def __init__(
        self,
        *,
        circuits: tuple[CircuitConfig, ...] | None = None,
        state: AnalyzerState | None = None,
    ) -> None:
        self.data = state or AnalyzerState(sensitivity_by_circuit={"fridge": "quiet"})
        self.circuit_configs = circuits or (_circuit(),)
        self.options = {CONF_ENTITY_DETAIL_LEVEL: "standard"}
        self.entry_data = {}
        self.last_dashboard_create_request: dict[str, object] | None = None
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
        self.calls.append(("async_recalculate_setting_recommendations", (circuit_id,)))

    async def async_create_dashboard(self) -> None:
        self.calls.append(("async_create_dashboard", ()))

    async def async_remove_dashboard(self) -> None:
        self.calls.append(("async_remove_dashboard", ()))

    async def async_set_dashboard_layout(self, layout: str) -> None:
        self.calls.append(("async_set_dashboard_layout", (layout,)))

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
        "switch",
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
        "entry-1_run_mapping_checks",
        "entry-1_recalculate_suggestions",
    }
    assert by_unique_id["entry-1_fridge_relearn_baseline"].device_info == {
        "identifiers": {(DOMAIN, "entry-1_fridge")},
        "name": "Kitchen Fridge",
        "manufacturer": "CircuitSetup",
        "suggested_area": "Kitchen",
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
        "entry-1_run_mapping_checks",
        "entry-1_recalculate_suggestions",
    ):
        await by_unique_id[unique_id].async_press()

    assert coordinator.calls == [
        ("async_relearn_baseline", ("fridge",)),
        ("async_run_mapping_checks", ()),
        ("async_recalculate_setting_recommendations", (None,)),
    ]


@pytest.mark.asyncio
async def test_button_setup_skips_inapplicable_controls_and_keeps_single_globals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import button

    _disable_registry_pruning(monkeypatch, button)
    coordinator = _FakeCoordinator(circuits=(_circuit(), _mains_circuit()))
    added_entities = []

    await button.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    unique_ids = {entity.unique_id for entity in added_entities}

    assert "entry-1_fridge_pause_alerts" not in unique_ids
    assert "entry-1_mains_pause_alerts" not in unique_ids
    assert "entry-1_mains_relearn_baseline" not in unique_ids
    assert {
        "entry-1_run_mapping_checks",
        "entry-1_recalculate_suggestions",
    } <= unique_ids
    assert not any(
        entity.unique_id.endswith(("create_dashboard", "remove_dashboard"))
        for entity in added_entities
    )


@pytest.mark.asyncio
async def test_unavailable_global_buttons_explain_missing_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import button

    _disable_registry_pruning(monkeypatch, button)
    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        circuit_configs=(),
        options={},
        entry_data={},
        store_data=SimpleNamespace(),
    )
    added_entities = []

    await button.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    by_unique_id = {entity.unique_id: entity for entity in added_entities}
    run_mapping = by_unique_id["entry-1_run_mapping_checks"]

    assert run_mapping.available is False
    assert run_mapping.extra_state_attributes == {
        "availability_reason": "action_unavailable",
        "availability_label": "The analyzer action is unavailable.",
        "next_step": "Reload the integration or check the system log.",
    }


@pytest.mark.asyncio
async def test_legacy_maintenance_buttons_follow_compatibility_keys_and_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import button

    _disable_registry_pruning(monkeypatch, button)
    state = AnalyzerState(
        maintenance_by_circuit={"fridge": {"active": True}},
        sensitivity_by_circuit={"fridge": "quiet"},
    )
    coordinator = _FakeCoordinator(state=state)
    coordinator.options[CONF_LEGACY_ENTITY_COMPATIBILITY_KEYS] = [
        "button:start_maintenance",
        "button:end_maintenance",
    ]
    added_entities = []

    await button.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    by_unique_id = {entity.unique_id: entity for entity in added_entities}

    assert by_unique_id["entry-1_fridge_start_maintenance"].available is False
    assert by_unique_id["entry-1_fridge_end_maintenance"].available is True


@pytest.mark.asyncio
async def test_existing_legacy_maintenance_button_registry_row_preserves_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import button

    _disable_registry_pruning(monkeypatch, button)
    coordinator = _FakeCoordinator()
    hass = _hass_with(coordinator)
    hass.entity_registry = SimpleNamespace(
        entities={
            "button.kitchen_fridge_start": SimpleNamespace(
                entity_id="button.kitchen_fridge_start",
                config_entry_id="entry-1",
                platform=DOMAIN,
                unique_id="entry-1_fridge_start_maintenance",
            )
        }
    )
    added_entities = []

    await button.async_setup_entry(
        hass,
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    by_unique_id = {entity.unique_id: entity for entity in added_entities}
    assert "entry-1_fridge_start_maintenance" in by_unique_id
    assert "entry-1_fridge_end_maintenance" not in by_unique_id


@pytest.mark.asyncio
async def test_pause_alerts_button_requires_active_unpaused_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import button

    _disable_registry_pruning(monkeypatch, button)
    coordinator = _FakeCoordinator()
    coordinator.options[CONF_ENTITY_DETAIL_LEVEL] = "expert"
    coordinator.options[CONF_SELECTED_ENTITY_GROUPS] = ["developer_diagnostics"]
    added_entities = []

    await button.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    by_unique_id = {entity.unique_id: entity for entity in added_entities}
    pause_alerts = by_unique_id["entry-1_fridge_pause_alerts"]

    assert pause_alerts.available is False
    assert pause_alerts.extra_state_attributes == {
        "availability_reason": "no_active_alert",
        "availability_label": "No active alert is available to pause.",
        "next_step": "Review the circuit summary or evidence panel for current alerts.",
    }

    with pytest.raises(button.HomeAssistantError, match="no active alert"):
        await pause_alerts.async_press()

    coordinator.data.active_alerts_by_circuit["fridge"] = [object()]

    assert pause_alerts.available is True
    assert pause_alerts.extra_state_attributes is None

    coordinator.data.maintenance_by_circuit["fridge"] = {"active": True}

    assert pause_alerts.available is False
    assert pause_alerts.extra_state_attributes == {
        "availability_reason": "alerts_paused",
        "availability_label": "Alerts are already paused for this circuit.",
        "next_step": "End maintenance or wait for the alert pause to expire.",
    }


@pytest.mark.asyncio
async def test_unavailable_maintenance_button_press_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import button

    _disable_registry_pruning(monkeypatch, button)
    coordinator = _FakeCoordinator()
    coordinator.options[CONF_LEGACY_ENTITY_COMPATIBILITY_KEYS] = [
        "button:start_maintenance",
        "button:end_maintenance",
    ]
    added_entities = []

    await button.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    by_unique_id = {entity.unique_id: entity for entity in added_entities}
    end_maintenance = by_unique_id["entry-1_fridge_end_maintenance"]

    assert end_maintenance.available is False
    assert end_maintenance.extra_state_attributes == {
        "availability_reason": "maintenance_inactive",
        "availability_label": "Maintenance is not active for this circuit.",
        "next_step": "Use Start Maintenance before ending maintenance.",
    }

    with pytest.raises(button.HomeAssistantError, match="maintenance inactive"):
        await end_maintenance.async_press()

    assert coordinator.calls == []


@pytest.mark.asyncio
async def test_switch_setup_entry_adds_maintenance_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import switch

    _disable_registry_pruning(monkeypatch, switch)
    state = AnalyzerState(
        maintenance_by_circuit={
            "fridge": {
                "active": True,
                "started_at": "2026-06-19T08:00:00-04:00",
                "expires_at": "2026-06-19T10:00:00-04:00",
                "note": "Cleaned coils",
                "relearn_on_end": True,
                "ended_at": "not exposed",
                "duration": "not exposed",
            }
        },
        sensitivity_by_circuit={"fridge": "quiet"},
    )
    coordinator = _FakeCoordinator(state=state)
    added_entities = []

    await switch.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    assert len(added_entities) == 1
    maintenance = added_entities[0]
    assert maintenance.unique_id == "entry-1_fridge_maintenance"
    assert maintenance.name is None
    assert maintenance.suggested_object_id == "fridge_maintenance"
    assert maintenance.icon == "mdi:wrench-clock"
    assert maintenance.entity_description.has_entity_name is True
    assert maintenance.entity_description.translation_key == "maintenance"
    assert maintenance._attr_has_entity_name is True
    assert maintenance._attr_translation_key == "maintenance"
    assert maintenance.is_on is True
    assert maintenance.extra_state_attributes == {
        "started_at": "2026-06-19T08:00:00-04:00",
        "expires_at": "2026-06-19T10:00:00-04:00",
        "note": "Cleaned coils",
        "relearn_on_end": True,
    }
    assert maintenance.entity_description.entity_category is None
    assert maintenance.entity_description.entity_registry_enabled_default is True
    assert maintenance.entity_description.entity_registry_visible_default is True


@pytest.mark.asyncio
async def test_switch_setup_entry_filters_controls_through_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import switch

    _disable_registry_pruning(monkeypatch, switch)
    monkeypatch.setattr(switch, "should_create_entity", lambda **_kwargs: False)
    coordinator = _FakeCoordinator()
    added_entities = []

    await switch.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    assert added_entities == []


@pytest.mark.asyncio
async def test_maintenance_switch_turns_on_and_off_idempotently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import switch

    _disable_registry_pruning(monkeypatch, switch)
    coordinator = _FakeCoordinator()
    added_entities = []

    await switch.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    maintenance = added_entities[0]

    assert maintenance.is_on is False
    await maintenance.async_turn_off()
    assert coordinator.calls == []

    await maintenance.async_turn_on()
    assert coordinator.calls == [
        ("async_start_maintenance", ("fridge", "", None, False)),
    ]

    coordinator.data.maintenance_by_circuit["fridge"] = {"active": True}
    await maintenance.async_turn_on()
    assert coordinator.calls == [
        ("async_start_maintenance", ("fridge", "", None, False)),
    ]

    await maintenance.async_turn_off()
    assert coordinator.calls == [
        ("async_start_maintenance", ("fridge", "", None, False)),
        ("async_end_maintenance", ("fridge", False)),
    ]

    coordinator.data.maintenance_by_circuit["fridge"] = {"active": False}
    await maintenance.async_turn_off()
    assert coordinator.calls == [
        ("async_start_maintenance", ("fridge", "", None, False)),
        ("async_end_maintenance", ("fridge", False)),
    ]


@pytest.mark.asyncio
async def test_maintenance_switch_skips_inapplicable_daily_control_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import switch

    _disable_registry_pruning(monkeypatch, switch)
    coordinator = _FakeCoordinator(circuits=(_circuit(), _mains_circuit()))
    added_entities = []

    await switch.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    assert {entity.unique_id for entity in added_entities} == {
        "entry-1_fridge_maintenance",
    }


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
        "entry-1_dashboard_layout",
        "entry-1_entity_detail_level",
    }

    sensitivity = by_unique_id["entry-1_fridge_alert_sensitivity"]
    assert sensitivity.name == "Kitchen Fridge Alert Sensitivity"
    assert sensitivity.suggested_object_id == "fridge_alert_sensitivity"
    assert sensitivity.options == ["Quiet", "Balanced", "Sensitive"]
    assert sensitivity.current_option == "Quiet"
    _assert_base_description_defaults(sensitivity.entity_description)
    assert sensitivity.entity_description.options is None

    detail_level = by_unique_id["entry-1_entity_detail_level"]
    assert detail_level.name == "CircuitSetup Energy Analyzer Entity Detail Level"
    assert detail_level.options == ["simple", "standard", "expert"]
    assert detail_level.current_option == "standard"

    dashboard_layout = by_unique_id["entry-1_dashboard_layout"]
    assert dashboard_layout.name == "CircuitSetup Energy Analyzer Dashboard Layout"
    assert dashboard_layout.options == ["Simple", "Standard", "Expert"]
    assert dashboard_layout.current_option == "Simple"

    await sensitivity.async_select_option("Sensitive")
    await detail_level.async_select_option("expert")
    await dashboard_layout.async_select_option("Expert")

    assert coordinator.calls == [
        ("async_set_circuit_sensitivity", ("fridge", "sensitive")),
        ("async_set_entity_detail_level", ("expert",)),
        ("async_set_dashboard_layout", (DASHBOARD_LAYOUT_EXPERT,)),
    ]


@pytest.mark.asyncio
async def test_select_setup_entry_filters_circuit_controls_through_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import select

    _disable_registry_pruning(monkeypatch, select)
    monkeypatch.setattr(select, "should_create_entity", lambda **_kwargs: False)
    coordinator = _FakeCoordinator()
    added_entities = []

    await select.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    assert {entity.unique_id for entity in added_entities} == {
        "entry-1_dashboard_layout",
        "entry-1_entity_detail_level",
    }


@pytest.mark.asyncio
async def test_select_setup_keeps_mains_sensitivity_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import select

    _disable_registry_pruning(monkeypatch, select)
    coordinator = _FakeCoordinator(circuits=(_circuit(), _mains_circuit()))
    added_entities = []

    await select.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    unique_ids = [entity.unique_id for entity in added_entities]

    assert "entry-1_fridge_alert_sensitivity" in unique_ids
    assert "entry-1_mains_alert_sensitivity" in unique_ids
    assert unique_ids.count("entry-1_entity_detail_level") == 1
    assert unique_ids.count("entry-1_dashboard_layout") == 1


@pytest.mark.asyncio
async def test_select_controls_reject_invalid_options_without_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import select

    _disable_registry_pruning(monkeypatch, select)
    coordinator = _FakeCoordinator()
    added_entities = []

    await select.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    by_unique_id = {entity.unique_id: entity for entity in added_entities}

    with pytest.raises(select.HomeAssistantError, match="alert sensitivity"):
        await by_unique_id["entry-1_fridge_alert_sensitivity"].async_select_option(
            "Noisy"
        )
    with pytest.raises(select.HomeAssistantError, match="entity detail level"):
        await by_unique_id["entry-1_entity_detail_level"].async_select_option(
            "advanced"
        )
    with pytest.raises(select.HomeAssistantError, match="dashboard layout"):
        await by_unique_id["entry-1_dashboard_layout"].async_select_option("Huge")

    assert coordinator.calls == []


@pytest.mark.asyncio
async def test_unavailable_selects_explain_missing_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import select

    _disable_registry_pruning(monkeypatch, select)
    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        circuit_configs=(_circuit(),),
        options={},
        entry_data={},
        store_data=SimpleNamespace(),
    )
    added_entities = []

    await select.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    by_unique_id = {entity.unique_id: entity for entity in added_entities}

    for unique_id in (
        "entry-1_fridge_alert_sensitivity",
        "entry-1_entity_detail_level",
        "entry-1_dashboard_layout",
    ):
        entity = by_unique_id[unique_id]
        assert entity.available is False
        assert entity.extra_state_attributes == {
            "availability_reason": "action_unavailable",
            "availability_label": "The analyzer action is unavailable.",
            "next_step": "Reload the integration or check the system log.",
        }

    with pytest.raises(select.HomeAssistantError, match="analyzer action"):
        await by_unique_id["entry-1_entity_detail_level"].async_select_option(
            "expert"
        )


@pytest.mark.asyncio
async def test_circuit_select_preserves_coordinator_update_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import select

    _disable_registry_pruning(monkeypatch, select)
    coordinator = _FakeCoordinator()
    coordinator.last_update_success = False
    added_entities = []

    await select.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    by_unique_id = {entity.unique_id: entity for entity in added_entities}
    entity = by_unique_id["entry-1_fridge_alert_sensitivity"]

    assert entity.available is False
    assert entity.extra_state_attributes is None


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


@pytest.mark.asyncio
async def test_number_setup_entry_filters_controls_through_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import number

    _disable_registry_pruning(monkeypatch, number)
    monkeypatch.setattr(number, "should_create_entity", lambda **_kwargs: False)
    coordinator = _FakeCoordinator()
    added_entities = []

    await number.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    assert added_entities == []


@pytest.mark.asyncio
async def test_number_setup_skips_daily_energy_goal_without_energy_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import number

    _disable_registry_pruning(monkeypatch, number)
    coordinator = _FakeCoordinator(circuits=(_power_only_circuit(),))
    coordinator.store_data = SimpleNamespace(energy_goal_settings_by_circuit={})
    added_entities = []

    await number.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    assert added_entities == []


@pytest.mark.asyncio
async def test_number_setup_skips_daily_energy_goal_for_non_cumulative_energy_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import number

    _disable_registry_pruning(monkeypatch, number)
    coordinator = _FakeCoordinator(circuits=(_misclassified_energy_circuit(),))
    coordinator.store_data = SimpleNamespace(energy_goal_settings_by_circuit={})
    added_entities = []

    await number.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    assert added_entities == []


@pytest.mark.asyncio
async def test_number_setup_skips_stale_daily_goal_without_energy_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import number

    _disable_registry_pruning(monkeypatch, number)
    coordinator = _FakeCoordinator(circuits=(_power_only_circuit(),))
    coordinator.options = {
        CONF_ADVANCED_SETTINGS: {
            "garage_freezer": {"daily_goal_kwh": 3.25},
        }
    }
    coordinator.store_data = SimpleNamespace(
        energy_goal_settings_by_circuit={
            "garage_freezer": {"daily_goal_kwh": 3.25},
        }
    )
    added_entities = []

    await number.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    assert added_entities == []


@pytest.mark.asyncio
async def test_number_setup_keeps_circuit_device_when_stale_goal_is_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import number

    coordinator = _FakeCoordinator(circuits=(_power_only_circuit(),))
    coordinator.store_data = SimpleNamespace(
        energy_goal_settings_by_circuit={
            "garage_freezer": {"daily_goal_kwh": 3.25},
        }
    )
    desired_identifiers: set[tuple[str, str]] = set()
    monkeypatch.setattr(
        number,
        "prune_stale_entity_registry_entries",
        lambda *args, **kwargs: None,
    )

    def _capture_device_prune(*args: object, **kwargs: object) -> None:
        desired_identifiers.update(kwargs["desired_identifiers"])

    monkeypatch.setattr(
        number,
        "prune_stale_device_registry_entries",
        _capture_device_prune,
    )
    added_entities = []

    await number.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    assert added_entities == []
    assert desired_identifiers == {(DOMAIN, "entry-1_garage_freezer")}


@pytest.mark.asyncio
async def test_number_setup_keeps_goal_when_runtime_energy_evidence_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import number

    _disable_registry_pruning(monkeypatch, number)
    coordinator = _FakeCoordinator(circuits=(_power_only_circuit(),))
    coordinator.data.daily_energy_usage_by_circuit["garage_freezer"] = 1.2
    coordinator.store_data = SimpleNamespace(energy_goal_settings_by_circuit={})
    added_entities = []

    await number.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    assert [entity.unique_id for entity in added_entities] == [
        "entry-1_garage_freezer_daily_energy_goal"
    ]


@pytest.mark.asyncio
async def test_control_entities_apply_to_dict_circuits_from_entry_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import button, number, switch

    _disable_registry_pruning(monkeypatch, button)
    _disable_registry_pruning(monkeypatch, number)
    _disable_registry_pruning(monkeypatch, switch)
    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        options={CONF_ADVANCED_SETTINGS: {"dishwasher": {"daily_goal_kwh": 3.25}}},
        entry_data={},
        store_data=SimpleNamespace(energy_goal_settings_by_circuit={}),
        circuit_configs=(),
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={"circuits": [_dict_energy_circuit()]},
    )
    button_entities = []
    number_entities = []
    switch_entities = []

    await button.async_setup_entry(
        _hass_with(coordinator), entry, button_entities.extend
    )
    await number.async_setup_entry(
        _hass_with(coordinator), entry, number_entities.extend
    )
    await switch.async_setup_entry(
        _hass_with(coordinator), entry, switch_entities.extend
    )

    assert {entity.unique_id for entity in button_entities} >= {
        "entry-1_dishwasher_relearn_baseline",
    }
    assert [entity.unique_id for entity in number_entities] == [
        "entry-1_dishwasher_daily_energy_goal"
    ]
    assert [entity.unique_id for entity in switch_entities] == [
        "entry-1_dishwasher_maintenance"
    ]
    assert number_entities[0].native_value == 3.25


@pytest.mark.asyncio
async def test_button_press_raises_clear_error_when_coordinator_method_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import button

    _disable_registry_pruning(monkeypatch, button)
    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        circuit_configs=(_circuit(),),
        hass=None,
    )
    added_entities = []

    await button.async_setup_entry(
        _hass_with(coordinator),
        SimpleNamespace(entry_id="entry-1", data={}),
        added_entities.extend,
    )

    relearn = next(
        entity
        for entity in added_entities
        if entity.unique_id == "entry-1_fridge_relearn_baseline"
    )

    with pytest.raises(button.HomeAssistantError, match="relearn baseline"):
        await relearn.async_press()
