from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_ADVANCED_SETTINGS,
    CONF_CIRCUITS,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_ENTITY_DETAIL_LEVEL,
    CONF_LINKED_FLOW_SENSOR_ENTITIES,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_RAIN_PUMP_CORRELATION_ENABLED,
    CONF_SELECTED_ENTITY_GROUPS,
    CONF_SOURCE_ENTITIES,
    CONF_UTILITY_COMPARISON_SETTINGS,
    CONF_WATER_FLOW_CORRELATION_ENABLED,
    CONF_WATER_FLOW_SENSOR_ENTITIES,
    DOMAIN,
    ENTITY_DETAIL_EXPERT,
    ENTITY_DETAIL_STANDARD,
)
from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
    PowerFlowMode,
    SensorRef,
    SensorRole,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData

DOMAIN_PATH = Path(__file__).parents[1] / "custom_components" / DOMAIN


def _use_expert_entity_detail(coordinator: SimpleNamespace) -> SimpleNamespace:
    return _use_entity_detail(coordinator, ENTITY_DETAIL_EXPERT)


def _use_entity_detail(
    coordinator: SimpleNamespace,
    detail_level: str,
    selected_groups: tuple[str, ...] = (),
) -> SimpleNamespace:
    options = dict(getattr(coordinator, "options", {}) or {})
    options[CONF_ENTITY_DETAIL_LEVEL] = detail_level
    if selected_groups:
        options[CONF_SELECTED_ENTITY_GROUPS] = list(selected_groups)
    coordinator.options = options
    return coordinator


@pytest.mark.asyncio
async def test_async_call_or_raise_awaits_action_and_reports_missing_method() -> None:
    from custom_components.circuitsetup_energy_analyzer.entity import (
        HomeAssistantError,
        async_call_or_raise,
    )

    calls: list[str] = []

    async def action(value: str) -> None:
        calls.append(value)

    await async_call_or_raise(SimpleNamespace(action=action), "action", "Run", "ok")

    assert calls == ["ok"]
    with pytest.raises(HomeAssistantError, match="analyzer action is unavailable"):
        await async_call_or_raise(SimpleNamespace(), "missing", "Run")


def test_stale_device_registry_device_ids_returns_removed_circuit_devices() -> None:
    from custom_components.circuitsetup_energy_analyzer.entity import (
        stale_device_registry_device_ids,
    )

    entries = [
        SimpleNamespace(
            id="old-circuit",
            config_entries={"entry-1"},
            identifiers={(DOMAIN, "entry-1_old_circuit")},
        ),
        SimpleNamespace(
            id="current-circuit",
            config_entries={"entry-1"},
            identifiers={(DOMAIN, "entry-1_current_circuit")},
        ),
        SimpleNamespace(
            id="other-entry",
            config_entries={"entry-2"},
            identifiers={(DOMAIN, "entry-1_old_circuit")},
        ),
        SimpleNamespace(
            id="other-domain",
            config_entries={"entry-1"},
            identifiers={("other_domain", "entry-1_old_circuit")},
        ),
    ]

    assert stale_device_registry_device_ids(
        entries,
        entry_id="entry-1",
        desired_identifiers={(DOMAIN, "entry-1_current_circuit")},
    ) == ["old-circuit"]


def test_circuit_device_info_uses_only_device_registry_fields() -> None:
    from custom_components.circuitsetup_energy_analyzer.entity import (
        CircuitAnalyzerEntity,
        CircuitInfo,
    )

    entity = CircuitAnalyzerEntity(
        SimpleNamespace(data=AnalyzerState()),
        entry_id="entry-1",
        circuit=CircuitInfo(
            circuit_id="fridge",
            name="Fridge",
            appliance_profile=ApplianceProfile.REFRIGERATOR.value,
        ),
        key="health_summary",
        name_suffix="Health Summary",
    )

    assert entity.device_info == {
        "identifiers": {(DOMAIN, "entry-1_fridge")},
        "name": "Fridge",
        "manufacturer": "CircuitSetup",
        "suggested_area": "Kitchen",
    }
    assert "icon" not in entity.device_info


def test_circuit_device_info_matches_ranked_existing_area_names(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import entity as entity_module
    from custom_components.circuitsetup_energy_analyzer.entity import (
        CircuitAnalyzerEntity,
        CircuitInfo,
    )

    monkeypatch.setattr(
        entity_module,
        "existing_area_names_for_hass",
        lambda hass: ("Basement", "Garage"),
    )
    analyzer_entity = CircuitAnalyzerEntity(
        SimpleNamespace(data=AnalyzerState(), hass=object()),
        entry_id="entry-1",
        circuit=CircuitInfo(
            circuit_id="mains",
            name="Mains",
            appliance_profile=ApplianceProfile.MAINS_NILM.value,
        ),
        key="activity_summary",
        name_suffix="Activity Summary",
    )

    assert analyzer_entity.device_info["suggested_area"] == "Basement"


def test_prune_stale_device_registry_entries_detaches_config_entry(monkeypatch) -> None:
    import sys
    from types import ModuleType

    from custom_components.circuitsetup_energy_analyzer import entity

    class FakeRegistry:
        def __init__(self) -> None:
            self.devices = {
                "old-circuit": SimpleNamespace(
                    id="old-circuit",
                    config_entries={"entry-1"},
                    identifiers={(DOMAIN, "entry-1_old_circuit")},
                ),
                "current-circuit": SimpleNamespace(
                    id="current-circuit",
                    config_entries={"entry-1"},
                    identifiers={(DOMAIN, "entry-1_current_circuit")},
                ),
            }
            self.updated: list[tuple[str, str]] = []

        def async_update_device(self, device_id, **kwargs) -> None:
            self.updated.append((device_id, kwargs["remove_config_entry_id"]))

    fake_registry = FakeRegistry()
    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    device_registry_module = ModuleType("homeassistant.helpers.device_registry")
    device_registry_module.async_get = lambda hass: hass.device_registry
    helpers_module.device_registry = device_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.device_registry",
        device_registry_module,
    )

    entity.prune_stale_device_registry_entries(
        SimpleNamespace(device_registry=fake_registry),
        entry_id="entry-1",
        desired_identifiers={(DOMAIN, "entry-1_current_circuit")},
    )

    assert fake_registry.updated == [("old-circuit", "entry-1")]


def test_hide_entity_registry_entries_marks_existing_detail_entities_hidden(
    monkeypatch,
) -> None:
    import sys
    from types import ModuleType

    from custom_components.circuitsetup_energy_analyzer import entity

    class FakeHider:
        INTEGRATION = "integration"

    class FakeRegistry:
        def __init__(self) -> None:
            self.entities = {
                "sensor.fridge_last_event": SimpleNamespace(
                    entity_id="sensor.fridge_last_event",
                    unique_id="entry-1_fridge_last_event",
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    hidden_by=None,
                ),
                "sensor.fridge_activity_summary": SimpleNamespace(
                    entity_id="sensor.fridge_activity_summary",
                    unique_id="entry-1_fridge_activity_summary",
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    hidden_by=None,
                ),
                "sensor.fridge_metric_consistency_status": SimpleNamespace(
                    entity_id="sensor.fridge_metric_consistency_status",
                    unique_id="entry-1_fridge_metric_consistency_status",
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    hidden_by="user",
                ),
                "sensor.other_last_event": SimpleNamespace(
                    entity_id="sensor.other_last_event",
                    unique_id="entry-2_fridge_last_event",
                    config_entry_id="entry-2",
                    platform=DOMAIN,
                    hidden_by=None,
                ),
            }
            self.updated: list[tuple[str, str]] = []

        def async_update_entity(self, entity_id, **kwargs) -> None:
            self.updated.append((entity_id, kwargs["hidden_by"]))

    fake_registry = FakeRegistry()
    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    entity_registry_module = ModuleType("homeassistant.helpers.entity_registry")
    entity_registry_module.RegistryEntryHider = FakeHider
    entity_registry_module.async_get = lambda hass: hass.entity_registry
    helpers_module.entity_registry = entity_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry_module,
    )

    entity.hide_entity_registry_entries(
        SimpleNamespace(entity_registry=fake_registry),
        entry_id="entry-1",
        entity_domain="sensor",
        hidden_unique_id_suffixes={"last_event", "metric_consistency_status"},
    )

    assert fake_registry.updated == [
        ("sensor.fridge_last_event", "integration"),
    ]


class _VisibilitySetupFakeHider:
    INTEGRATION = "integration"
    USER = "user"


class _VisibilitySetupFakeEntityRegistry:
    def __init__(self) -> None:
        self.entities: dict[str, SimpleNamespace] = {}
        self.updated: list[tuple[str, object]] = []
        self.disabled_updates: list[tuple[str, object]] = []

    def async_remove(self, entity_id: str) -> None:
        self.entities.pop(entity_id, None)

    def async_update_entity(self, entity_id: str, **kwargs) -> None:
        entry = self.entities[entity_id]
        if "hidden_by" in kwargs:
            entry.hidden_by = kwargs["hidden_by"]
            self.updated.append((entity_id, kwargs["hidden_by"]))
        if "disabled_by" in kwargs:
            entry.disabled_by = kwargs["disabled_by"]
            self.disabled_updates.append((entity_id, kwargs["disabled_by"]))
        if "entity_category" in kwargs:
            entry.entity_category = kwargs["entity_category"]


def _install_visibility_setup_registries(monkeypatch, fake_registry) -> None:
    import sys
    from types import ModuleType

    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    entity_registry_module = ModuleType("homeassistant.helpers.entity_registry")
    device_registry_module = ModuleType("homeassistant.helpers.device_registry")
    entity_registry_module.RegistryEntryHider = _VisibilitySetupFakeHider
    entity_registry_module.async_get = lambda hass: hass.entity_registry
    device_registry_module.async_get = lambda hass: SimpleNamespace(devices={})
    helpers_module.entity_registry = entity_registry_module
    helpers_module.device_registry = device_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.device_registry",
        device_registry_module,
    )


def _register_default_hidden_entities(
    fake_registry: _VisibilitySetupFakeEntityRegistry,
    entities,
    *,
    domain: str,
    entry_id: str,
) -> None:
    for entity in entities:
        if getattr(entity, "_attr_entity_registry_visible_default", True) is not False:
            continue
        unique_id = entity.unique_id
        object_id = unique_id.removeprefix(f"{entry_id}_")
        entity_id = f"{domain}.{object_id}"
        fake_registry.entities[entity_id] = SimpleNamespace(
            entity_id=entity_id,
            unique_id=unique_id,
            config_entry_id=entry_id,
            platform=DOMAIN,
            hidden_by="integration",
            entity_category=getattr(entity, "_attr_entity_category", None),
        )


@pytest.mark.asyncio
async def test_sensor_setup_does_not_unhide_registry_entries_after_registration(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import sensor

    fake_registry = _VisibilitySetupFakeEntityRegistry()
    _install_visibility_setup_registries(monkeypatch, fake_registry)
    circuit = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
    )
    coordinator = _use_expert_entity_detail(
        SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,))
    )
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        entity_registry=fake_registry,
    )
    entry = SimpleNamespace(entry_id="entry-1", data={})

    def async_add_entities(entities) -> None:
        _register_default_hidden_entities(
            fake_registry,
            entities,
            domain="sensor",
            entry_id="entry-1",
        )

    await sensor.async_setup_entry(hass, entry, async_add_entities)

    hidden_entries = [
        entry
        for entry in fake_registry.entities.values()
        if entry.hidden_by == "integration"
    ]
    assert {entry.entity_id for entry in hidden_entries} == {
        "sensor.fridge_always_on_power",
    }
    assert fake_registry.updated == []


@pytest.mark.asyncio
async def test_binary_sensor_setup_does_not_unhide_registry_entries_after_registration(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import binary_sensor

    fake_registry = _VisibilitySetupFakeEntityRegistry()
    _install_visibility_setup_registries(monkeypatch, fake_registry)
    circuit = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
    )
    coordinator = _use_expert_entity_detail(
        SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,))
    )
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        entity_registry=fake_registry,
    )
    entry = SimpleNamespace(entry_id="entry-1", data={})

    def async_add_entities(entities) -> None:
        _register_default_hidden_entities(
            fake_registry,
            entities,
            domain="binary_sensor",
            entry_id="entry-1",
        )

    await binary_sensor.async_setup_entry(hass, entry, async_add_entities)

    hidden_entries = [
        entry
        for entry in fake_registry.entities.values()
        if entry.hidden_by == "integration"
    ]
    assert hidden_entries == []
    assert fake_registry.updated == []


def test_sync_entity_registry_categories_updates_existing_sensor_categories(
    monkeypatch,
) -> None:
    import sys
    from types import ModuleType

    from custom_components.circuitsetup_energy_analyzer import entity
    from custom_components.circuitsetup_energy_analyzer.entity import EntityCategory

    class FakeRegistry:
        def __init__(self) -> None:
            self.entities = {
                "sensor.fridge_health_summary": SimpleNamespace(
                    entity_id="sensor.fridge_health_summary",
                    unique_id="entry-1_fridge_health_summary",
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    entity_category=EntityCategory.DIAGNOSTIC,
                ),
                "sensor.fridge_power_quality_evidence": SimpleNamespace(
                    entity_id="sensor.fridge_power_quality_evidence",
                    unique_id="entry-1_fridge_power_quality_evidence",
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    entity_category=EntityCategory.DIAGNOSTIC,
                ),
                "sensor.other_health_summary": SimpleNamespace(
                    entity_id="sensor.other_health_summary",
                    unique_id="entry-2_fridge_health_summary",
                    config_entry_id="entry-2",
                    platform=DOMAIN,
                    entity_category=EntityCategory.DIAGNOSTIC,
                ),
            }
            self.updated: list[tuple[str, object]] = []

        def async_update_entity(self, entity_id, **kwargs) -> None:
            self.updated.append((entity_id, kwargs["entity_category"]))

    fake_registry = FakeRegistry()
    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    entity_registry_module = ModuleType("homeassistant.helpers.entity_registry")
    entity_registry_module.async_get = lambda hass: hass.entity_registry
    helpers_module.entity_registry = entity_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry_module,
    )

    entity.sync_entity_registry_categories(
        SimpleNamespace(entity_registry=fake_registry),
        entry_id="entry-1",
        entity_domain="sensor",
        entity_category_by_unique_id_suffix={
            "health_summary": None,
            "power_quality_evidence": EntityCategory.DIAGNOSTIC,
        },
    )

    assert fake_registry.updated == [("sensor.fridge_health_summary", None)]


def test_sensor_helpers_return_diagnostic_values_and_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        activity_summary_value,
        always_on_limit_usage_value,
        always_on_power_value,
        anomaly_score_value,
        apparent_power_drift_value,
        balance_power_value,
        balance_status_value,
        billing_cycle_forecast_value,
        billing_cycle_status_value,
        billing_cycle_usage_value,
        capacity_status_value,
        capacity_usage_value,
        circuit_mode_value,
        cost_cycle_forecast_value,
        cost_cycle_value,
        cost_status_value,
        current_demand_value,
        daily_energy_usage_value,
        data_quality_checklist_value,
        demand_limit_usage_value,
        demand_peak_rank_value,
        demand_peak_status_value,
        demand_status_value,
        energy_dashboard_status_value,
        energy_goal_status_value,
        energy_goal_usage_value,
        energy_summary_value,
        energy_usage_share_value,
        energy_usage_status_value,
        health_summary_value,
        learning_progress_value,
        leg_imbalance_status_value,
        leg_imbalance_value,
        metric_consistency_score_value,
        metric_consistency_status_value,
        monitored_coverage_value,
        monitored_power_value,
        nilm_signature_count_value,
        nilm_topology_status_value,
        nilm_unknown_loads_attributes,
        nilm_unknown_loads_value,
        nilm_unmatched_load_percentage_value,
        peak_demand_value,
        power_factor_drift_value,
        power_flow_value,
        power_quality_evidence_value,
        power_quality_score_value,
        reactive_power_drift_value,
        readiness_value,
        recent_activity_value,
        run_cycle_count_value,
        run_cycle_duty_cycle_value,
        run_cycle_runtime_value,
        run_cycle_status_value,
        sensitivity_value,
        settings_suggestions_attributes,
        settings_suggestions_value,
        solar_flow_status_value,
        solar_generation_power_value,
        solar_surplus_power_value,
        solar_surplus_status_value,
        standby_status_value,
        utility_comparison_status_value,
    )

    event = CircuitEvent(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="fridge",
        event_type=EventType.START,
        severity=Severity.INFO,
        features={"startup_power_w": 512.0},
    )
    state = AnalyzerState(
        last_event_by_circuit={"fridge": event},
        anomaly_score_by_circuit={"fridge": 0.42},
        power_quality_score_by_circuit={"fridge": 3.25},
        power_quality_evidence_by_circuit={
            "fridge": "Possible issue: reactive power changed"
        },
        reactive_power_drift_by_circuit={"fridge": 0.38},
        apparent_power_drift_by_circuit={"fridge": 0.12},
        power_factor_drift_by_circuit={"fridge": 0.07},
        nilm_signature_count_by_circuit={"fridge": 3},
        nilm_unmatched_load_percentage_by_circuit={"fridge": 17.5},
        nilm_topology_status_by_circuit={"fridge": "topology_mismatch"},
        nilm_unknown_loads_by_circuit={
            "fridge": {
                "unknown_load_count": 2,
                "active_unknown_load_count": 1,
                "unknown_loads": [
                    {
                        "signature_id": "sig-motor",
                        "likely_type": "motor",
                        "typical_watts": 725.0,
                        "confidence": 0.81,
                        "first_seen": "2026-06-12T12:00:00+00:00",
                        "raw_samples": [1, 2, 3],
                    }
                ],
                "debug_history": [{"sample": index} for index in range(20)],
            }
        },
        nilm_topology_evidence_by_circuit={
            "fridge": {
                "status": "topology_mismatch",
                "observed_split_phase_type": "balanced_240v",
            }
        },
        health_status_by_circuit={"fridge": "possible_issue"},
        health_summary_by_circuit={"fridge": "Possible issue"},
        readiness_by_circuit={
            "fridge": {
                "health_status": "possible_issue",
                "health_summary": "Possible issue",
            }
        },
        learning_progress_by_circuit={
            "fridge": {
                "learned_feature_count": 5,
                "pending_feature_samples": {"reactive_power": 3},
                "alert_ready": False,
            },
            "ready": {
                "learned_feature_count": 1,
                "pending_feature_samples": {},
                "alert_ready": True,
            },
        },
        data_quality_checklist_by_circuit={
            "fridge": {
                "quality_issues": [],
                "required_sensors_present": True,
            },
            "well_pump": {
                "quality_issues": ["missing_required_sensor"],
                "required_sensors_present": False,
            },
        },
        energy_dashboard_status_by_circuit={"fridge": "ready"},
        energy_dashboard_evidence_by_circuit={
            "fridge": {"status": "ready", "ready_energy_entities": []}
        },
        alert_evidence_by_circuit={"fridge": {"feature": "reactive_power"}},
        recent_activity_by_circuit={"fridge": "Possible issue: Cycle Duration"},
        recent_activity_count_by_circuit={"fridge": 2},
        recent_activity_timeline_by_circuit={
            "fridge": {
                "status": "activity",
                "items": [
                    {
                        "title": "Possible issue: Cycle Duration",
                        "feature_name": "Cycle Duration",
                    }
                ],
            }
        },
        sensitivity_by_circuit={"fridge": "quiet"},
        circuit_mode_by_circuit={"fridge": "Dual Phase"},
        power_flow_by_circuit={"fridge": "Generation / Solar Export"},
        daily_energy_usage_by_circuit={"fridge": 12.9},
        energy_usage_share_by_circuit={"fridge": 25.8},
        energy_usage_evidence_by_circuit={
            "fridge": {"status": "over_threshold", "threshold_kwh": 12.5}
        },
        energy_goal_usage_by_circuit={"fridge": 110.0},
        energy_goal_status_by_circuit={"fridge": "over_goal"},
        energy_goal_evidence_by_circuit={
            "fridge": {"status": "over_goal", "daily_goal_kwh": 12.0}
        },
        run_cycle_count_by_circuit={"fridge": 4},
        run_cycle_runtime_seconds_by_circuit={"fridge": 3600.0},
        run_cycle_duty_cycle_by_circuit={"fridge": 12.5},
        run_cycle_status_by_circuit={"fridge": "idle"},
        run_cycle_evidence_by_circuit={"fridge": {"status": "idle"}},
        current_demand_w_by_circuit={"fridge": 2400.0},
        peak_demand_w_by_circuit={"fridge": 3200.0},
        demand_limit_usage_by_circuit={"fridge": 80.0},
        demand_peak_rank_by_circuit={"fridge": 2},
        demand_peak_status_by_circuit={"fridge": "monthly_peak"},
        demand_evidence_by_circuit={
            "fridge": {
                "status": "tracking",
                "demand_limit_w": 4000.0,
                "monthly_peak_status": "monthly_peak",
            }
        },
        capacity_usage_by_circuit={"fridge": 85.0},
        capacity_status_by_circuit={"fridge": "over_limit"},
        capacity_evidence_by_circuit={
            "fridge": {"status": "over_limit", "breaker_amps": 40.0}
        },
        leg_imbalance_percent_by_circuit={"fridge": 66.7},
        leg_imbalance_status_by_circuit={"fridge": "imbalanced"},
        leg_imbalance_evidence_by_circuit={
            "fridge": {
                "status": "imbalanced",
                "left_real_power_w": 2400.0,
                "right_real_power_w": 1200.0,
            }
        },
        metric_consistency_score_by_circuit={"fridge": 50.0},
        metric_consistency_status_by_circuit={"fridge": "apparent_power_mismatch"},
        metric_consistency_evidence_by_circuit={
            "fridge": {
                "status": "apparent_power_mismatch",
                "expected_apparent_power_va": 1200.0,
                "reported_apparent_power_va": 600.0,
            }
        },
        balance_power_w_by_circuit={"fridge": 2300.0},
        monitored_power_w_by_circuit={"fridge": 2700.0},
        monitored_coverage_percent_by_circuit={"fridge": 54.0},
        balance_status_by_circuit={"fridge": "tracking"},
        balance_evidence_by_circuit={
            "fridge": {"status": "tracking", "balance_power_w": 2300.0}
        },
        solar_generation_w_by_circuit={"fridge": 2000.0},
        solar_site_consumption_w_by_circuit={"fridge": 1500.0},
        solar_grid_import_w_by_circuit={"fridge": 0.0},
        solar_grid_export_w_by_circuit={"fridge": 500.0},
        solar_self_consumption_percent_by_circuit={"fridge": 75.0},
        solar_powered_percent_by_circuit={"fridge": 100.0},
        solar_surplus_w_by_circuit={"fridge": 500.0},
        solar_load_shift_w_by_circuit={"fridge": 500.0},
        solar_flexible_load_power_w_by_circuit={"fridge": 800.0},
        solar_flexible_load_coverage_percent_by_circuit={"fridge": 100.0},
        solar_flow_status_by_circuit={"fridge": "exporting"},
        solar_surplus_status_by_circuit={"fridge": "surplus_available"},
        solar_load_shift_status_by_circuit={"fridge": "active_solar_supported"},
        solar_flow_evidence_by_circuit={
            "fridge": {
                "status": "exporting",
                "solar_surplus_status": "surplus_available",
                "solar_generation_w": 2000.0,
                "site_consumption_w": 1500.0,
                "solar_surplus_w": 500.0,
                "load_shift_available_w": 500.0,
            }
        },
        utility_comparison_difference_kwh_by_circuit={"fridge": 15.0},
        utility_comparison_difference_percent_by_circuit={"fridge": 12.5},
        utility_comparison_status_by_circuit={"fridge": "mismatch"},
        utility_comparison_evidence_by_circuit={
            "fridge": {
                "status": "mismatch",
                "utility_kwh": 120.0,
                "measured_kwh": 135.0,
            }
        },
        billing_cycle_usage_kwh_by_circuit={"fridge": 100.0},
        billing_cycle_forecast_kwh_by_circuit={"fridge": 300.0},
        billing_cycle_budget_usage_by_circuit={"fridge": 40.0},
        billing_cycle_status_by_circuit={"fridge": "projected_over_budget"},
        billing_cycle_evidence_by_circuit={
            "fridge": {
                "status": "projected_over_budget",
                "projected_cycle_kwh": 300.0,
            }
        },
        cost_current_rate_by_circuit={"fridge": 0.3},
        cost_cycle_by_circuit={"fridge": 6.2},
        cost_cycle_forecast_by_circuit={"fridge": 18.6},
        cost_status_by_circuit={"fridge": "tou_peak"},
        cost_evidence_by_circuit={
            "fridge": {"status": "tou_peak", "active_rate_name": "Peak"}
        },
        always_on_power_w_by_circuit={"fridge": 45.0},
        standby_threshold_w_by_circuit={"fridge": 8.0},
        standby_status_by_circuit={"fridge": "standby"},
        always_on_limit_usage_by_circuit={"fridge": 180.0},
        standby_evidence_by_circuit={
            "fridge": {"status": "standby", "always_on_power_w": 45.0}
        },
        learning_by_circuit={"fridge": False},
        settings_recommendation_count_by_circuit={"fridge": 2},
        settings_recommendations_by_circuit={
            "fridge": [
                {
                    "recommendation_id": "fridge:daily_spike_ratio:v1",
                    "setting_key": "daily_spike_ratio",
                    "suggested_value": 1.8,
                },
                {
                    "recommendation_id": "fridge:standby_threshold:v1",
                    "setting_key": "standby_threshold_w",
                    "suggested_value": 9.0,
                },
            ]
        },
    )

    assert anomaly_score_value(state, "fridge") == 0.42
    assert power_quality_score_value(state, "fridge") == 3.25
    assert (
        power_quality_evidence_value(state, "fridge")
        == "Possible issue: reactive power changed"
    )
    assert reactive_power_drift_value(state, "fridge") == 0.38
    assert apparent_power_drift_value(state, "fridge") == 0.12
    assert power_factor_drift_value(state, "fridge") == 0.07
    assert nilm_signature_count_value(state, "fridge") == 3
    assert nilm_unmatched_load_percentage_value(state, "fridge") == 17.5
    assert nilm_topology_status_value(state, "fridge") == "topology_mismatch"
    assert nilm_unknown_loads_value(state, "fridge") == 2
    assert nilm_unknown_loads_attributes(state, "fridge") == {
        "unknown_load_count": 2,
        "active_unknown_load_count": 1,
        "shown_count": 1,
        "has_more": False,
        "unknown_loads": [
            {
                "signature_id": "sig-motor",
                "likely_type": "motor",
                "typical_watts": 725.0,
                "confidence": 0.81,
                "first_seen": "2026-06-12T12:00:00+00:00",
            }
        ],
    }
    assert health_summary_value(state, "fridge") == "Possible issue"
    assert readiness_value(state, "fridge") == "possible_issue"
    assert learning_progress_value(state, "fridge") == 62.5
    assert learning_progress_value(state, "ready") == 100.0
    assert data_quality_checklist_value(state, "fridge") == "ok"
    assert data_quality_checklist_value(state, "well_pump") == "problem"
    assert energy_dashboard_status_value(state, "fridge") == "ready"
    assert recent_activity_value(state, "fridge") == "Possible issue: Cycle Duration"
    assert sensitivity_value(state, "fridge") == "Quiet"
    assert circuit_mode_value(state, "fridge") == "Dual Phase"
    assert power_flow_value(state, "fridge") == "Generation / Solar Export"
    assert activity_summary_value(state, "fridge") == "Idle"
    assert energy_summary_value(state, "fridge") == "High Usage"
    assert daily_energy_usage_value(state, "fridge") == 12.9
    assert energy_usage_share_value(state, "fridge") == 25.8
    assert energy_usage_status_value(state, "fridge") == "over_threshold"
    assert energy_goal_usage_value(state, "fridge") == 110.0
    assert energy_goal_status_value(state, "fridge") == "over_goal"
    assert run_cycle_count_value(state, "fridge") == 4
    assert run_cycle_runtime_value(state, "fridge") == 3600.0
    assert run_cycle_duty_cycle_value(state, "fridge") == 12.5
    assert run_cycle_status_value(state, "fridge") == "idle"
    assert current_demand_value(state, "fridge") == 2400.0
    assert peak_demand_value(state, "fridge") == 3200.0
    assert demand_limit_usage_value(state, "fridge") == 80.0
    assert demand_peak_rank_value(state, "fridge") == 2
    assert demand_peak_status_value(state, "fridge") == "monthly_peak"
    assert demand_status_value(state, "fridge") == "tracking"
    assert capacity_usage_value(state, "fridge") == 85.0
    assert capacity_status_value(state, "fridge") == "over_limit"
    assert leg_imbalance_value(state, "fridge") == 66.7
    assert leg_imbalance_status_value(state, "fridge") == "imbalanced"
    assert metric_consistency_score_value(state, "fridge") == 50.0
    assert metric_consistency_status_value(state, "fridge") == "apparent_power_mismatch"
    assert balance_power_value(state, "fridge") == 2300.0
    assert monitored_power_value(state, "fridge") == 2700.0
    assert monitored_coverage_value(state, "fridge") == 54.0
    assert balance_status_value(state, "fridge") == "tracking"
    assert solar_generation_power_value(state, "fridge") == 2000.0
    assert solar_flow_status_value(state, "fridge") == "exporting"
    assert solar_surplus_power_value(state, "fridge") == 500.0
    assert solar_surplus_status_value(state, "fridge") == "surplus_available"
    assert utility_comparison_status_value(state, "fridge") == "mismatch"
    assert billing_cycle_usage_value(state, "fridge") == 100.0
    assert billing_cycle_forecast_value(state, "fridge") == 300.0
    assert billing_cycle_status_value(state, "fridge") == "projected_over_budget"
    assert cost_cycle_value(state, "fridge") == 6.2
    assert cost_cycle_forecast_value(state, "fridge") == 18.6
    assert cost_status_value(state, "fridge") == "tou_peak"
    assert always_on_power_value(state, "fridge") == 45.0
    assert standby_status_value(state, "fridge") == "standby"
    assert always_on_limit_usage_value(state, "fridge") == 180.0
    assert settings_suggestions_value(state, "fridge") == 2
    assert settings_suggestions_attributes(state, "fridge") == {
        "pending_count": 2,
        "learning": False,
        "shown_count": 2,
        "has_more": False,
        "recommendations": [
            {
                "recommendation_id": "fridge:daily_spike_ratio:v1",
                "setting_key": "daily_spike_ratio",
                "suggested_value": 1.8,
            },
            {
                "recommendation_id": "fridge:standby_threshold:v1",
                "setting_key": "standby_threshold_w",
                "suggested_value": 9.0,
            },
        ],
    }

    assert anomaly_score_value(state, "unknown") == 0.0
    assert power_quality_score_value(state, "unknown") == 0.0
    assert power_quality_evidence_value(state, "unknown") == ""
    assert reactive_power_drift_value(state, "unknown") == 0.0
    assert apparent_power_drift_value(state, "unknown") == 0.0
    assert power_factor_drift_value(state, "unknown") == 0.0
    assert nilm_signature_count_value(state, "unknown") == 0
    assert nilm_unmatched_load_percentage_value(state, "unknown") == 0.0
    assert nilm_topology_status_value(state, "unknown") == "no_match"
    assert nilm_unknown_loads_value(state, "unknown") == 0
    assert nilm_unknown_loads_attributes(state, "unknown") == {}
    assert health_summary_value(state, "unknown") == "Learning"
    assert readiness_value(state, "unknown") == "learning"
    assert learning_progress_value(state, "unknown") == 0.0
    assert data_quality_checklist_value(state, "unknown") == "problem"
    assert energy_dashboard_status_value(state, "unknown") == "needs_energy_source"
    assert recent_activity_value(state, "unknown") == "No recent activity"
    assert sensitivity_value(state, "unknown") == "Balanced"
    assert activity_summary_value(state, "unknown") == "No Activity"
    assert energy_summary_value(state, "unknown") == "Needs Energy Data"
    assert daily_energy_usage_value(state, "unknown") == 0.0
    assert energy_usage_share_value(state, "unknown") == 0.0
    assert energy_usage_status_value(state, "unknown") == "learning"
    assert energy_goal_usage_value(state, "unknown") == 0.0
    assert energy_goal_status_value(state, "unknown") == "unconfigured"
    assert run_cycle_count_value(state, "unknown") == 0
    assert run_cycle_runtime_value(state, "unknown") == 0.0
    assert run_cycle_duty_cycle_value(state, "unknown") == 0.0
    assert run_cycle_status_value(state, "unknown") == "no_activity"
    assert current_demand_value(state, "unknown") == 0.0
    assert peak_demand_value(state, "unknown") == 0.0
    assert demand_limit_usage_value(state, "unknown") == 0.0
    assert demand_peak_rank_value(state, "unknown") == 0
    assert demand_peak_status_value(state, "unknown") == "unavailable"
    assert demand_status_value(state, "unknown") == "unconfigured"
    assert capacity_usage_value(state, "unknown") == 0.0
    assert capacity_status_value(state, "unknown") == "unconfigured"
    assert leg_imbalance_value(state, "unknown") == 0.0
    assert leg_imbalance_status_value(state, "unknown") == "not_dual_phase"
    assert metric_consistency_score_value(state, "unknown") == 0.0
    assert metric_consistency_status_value(state, "unknown") == "missing_metrics"
    assert balance_power_value(state, "unknown") == 0.0
    assert monitored_power_value(state, "unknown") == 0.0
    assert monitored_coverage_value(state, "unknown") == 0.0
    assert balance_status_value(state, "unknown") == "missing_mains"
    assert solar_generation_power_value(state, "unknown") == 0.0
    assert solar_flow_status_value(state, "unknown") == "missing_mains"
    assert solar_surplus_power_value(state, "unknown") == 0.0
    assert solar_surplus_status_value(state, "unknown") == "missing_mains"
    assert utility_comparison_status_value(state, "unknown") == "unconfigured"
    assert billing_cycle_usage_value(state, "unknown") == 0.0
    assert billing_cycle_forecast_value(state, "unknown") == 0.0
    assert billing_cycle_status_value(state, "unknown") == "no_budget"
    assert cost_cycle_value(state, "unknown") == 0.0
    assert cost_cycle_forecast_value(state, "unknown") == 0.0
    assert cost_status_value(state, "unknown") == "unconfigured"
    assert always_on_power_value(state, "unknown") == 0.0
    assert standby_status_value(state, "unknown") == "learning"
    assert always_on_limit_usage_value(state, "unknown") == 0.0
    assert settings_suggestions_value(state, "unknown") == 0
    assert settings_suggestions_attributes(state, "unknown") == {
        "pending_count": 0,
        "learning": True,
        "shown_count": 0,
        "has_more": False,
        "recommendations": [],
    }


def test_nilm_unknown_load_attributes_are_bounded() -> None:
    from custom_components.circuitsetup_energy_analyzer.entities.nilm import (
        nilm_unknown_loads_attributes,
    )

    unknown_loads = [
        {
            "signature_id": f"signature-{index}",
            "display_name": f"Unknown load {index}",
            "likely_type": "motor",
            "typical_watts": 600 + index,
            "confidence": 0.5,
            "first_seen": "2026-06-12T12:00:00+00:00",
            "sample_history": [index] * 20,
        }
        for index in range(7)
    ]
    state = AnalyzerState(
        nilm_unknown_loads_by_circuit={
            "mains": {
                "unknown_load_count": len(unknown_loads),
                "active_unknown_load_count": 6,
                "unknown_loads": unknown_loads,
            }
        }
    )

    attrs = nilm_unknown_loads_attributes(state, "mains")

    assert attrs["unknown_load_count"] == 7
    assert attrs["active_unknown_load_count"] == 6
    assert attrs["shown_count"] == 5
    assert attrs["has_more"] is True
    assert [load["signature_id"] for load in attrs["unknown_loads"]] == [
        "signature-0",
        "signature-1",
        "signature-2",
        "signature-3",
        "signature-4",
    ]
    assert all("sample_history" not in load for load in attrs["unknown_loads"])


def test_recent_activity_attributes_are_bounded() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
    )

    description = next(
        item for item in SENSOR_DESCRIPTIONS if item.key == "recent_activity"
    )
    long_detail = "Retained activity detail " + ("with extra context " * 20)
    timeline_items = [
        {
            "timestamp": f"2026-06-13T12:{index:02d}:00+00:00",
            "title": f"Activity {index}",
            "detail": long_detail,
            "extra_samples": [index] * 20,
        }
        for index in range(9)
    ]
    state = AnalyzerState(
        recent_activity_timeline_by_circuit={
            "fridge": {
                "status": "activity",
                "window_hours": 24,
                "total_count": 9,
                "items": timeline_items,
            }
        }
    )

    attrs = description.attributes_fn(state, "fridge")

    assert attrs == {
        "status": "activity",
        "window_hours": 24,
        "total_count": 9,
        "shown_count": 5,
        "has_more": True,
        "items": [
            {
                "timestamp": f"2026-06-13T12:{index:02d}:00+00:00",
                "title": f"Activity {index}",
                "detail": (
                    "Retained activity detail with extra context with extra context..."
                ),
            }
            for index in range(5)
        ],
    }


def test_setup_health_treats_optional_energy_and_metric_inputs_as_ready() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
        setup_health_value,
    )

    setup_coordinator = SimpleNamespace(
        data=AnalyzerState(
            data_quality_checklist_by_circuit={
                "fridge": {
                    "sample_observed": True,
                    "required_sensors_present": True,
                    "numeric_states_valid": True,
                    "source_data_fresh": True,
                }
            },
            energy_dashboard_status_by_circuit={"fridge": "needs_energy_source"},
            energy_dashboard_evidence_by_circuit={
                "fridge": {"status": "needs_energy_source"}
            },
            metric_consistency_status_by_circuit={"fridge": "missing_metrics"},
        ),
        circuit_configs=(
            CircuitConfig(
                circuit_id="fridge",
                name="Kitchen Fridge",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
            ),
        ),
    )
    assert setup_health_value(setup_coordinator) == "Ready"
    setup_attrs = setup_health_attributes(setup_coordinator)
    assert setup_attrs["blocking_issue_count"] == 0
    assert setup_attrs["issue_count"] == 0
    assert setup_attrs["warning_count"] == 0
    assert setup_attrs["ready"] is True
    assert setup_attrs["next_step"] == "No setup action needed"
    assert setup_attrs["recommended_action"] == "No setup action needed"
    assert setup_attrs["primary_issue"] is None
    assert setup_attrs["primary_severity"] is None
    assert setup_attrs["issue_summary"] == "Ready"
    assert setup_attrs["affected_circuit"] is None
    assert setup_attrs["affected_circuits"] == []
    assert setup_attrs["missing_energy_sources"] == []
    assert setup_attrs["learning_circuits"] == []
    assert setup_attrs["stale_sources"] == []
    assert setup_attrs["negative_power_loads"] == []
    assert setup_attrs["issues"] == []
    checklist = {item["item_id"]: item for item in setup_attrs["checklist"]}
    assert checklist["cumulative_kwh_sources_found"]["status"] == "ok"

    ready_coordinator = SimpleNamespace(data=AnalyzerState(), circuit_configs=())
    assert setup_health_value(ready_coordinator) == "Review circuit assignments"
    assert setup_health_attributes(ready_coordinator)["blocking_issue_count"] == 1


def test_setup_health_ignores_leg_imbalance_for_single_phase_circuit() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
        setup_health_value,
    )

    circuit = CircuitConfig(
        circuit_id="hvac_1",
        name="HVAC 1",
        appliance_profile=ApplianceProfile.HVAC_BLOWER,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.hvac_1_power", SensorRole.REAL_POWER),),
    )
    coordinator = SimpleNamespace(
        data=AnalyzerState(
            data_quality_checklist_by_circuit={
                "hvac_1": {
                    "sample_observed": True,
                    "required_sensors_present": True,
                    "numeric_states_valid": True,
                    "source_data_fresh": True,
                }
            },
            leg_imbalance_status_by_circuit={"hvac_1": "not_dual_phase"},
        ),
        circuit_configs=(circuit,),
    )

    assert setup_health_value(coordinator) == "Ready"
    assert setup_health_attributes(coordinator)["issues"] == []


def test_setup_health_reports_missing_source_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
        setup_health_value,
    )

    coordinator = SimpleNamespace(
        data=AnalyzerState(
            data_quality_by_circuit={"garage_freezer": "missing_source_entities"},
        ),
        circuit_configs=(
            CircuitConfig(
                circuit_id="garage_freezer",
                name="Garage Freezer",
                appliance_profile=ApplianceProfile.FREEZER,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(),
            ),
        ),
    )

    assert setup_health_value(coordinator) == "Add source sensor"
    attrs = setup_health_attributes(coordinator)
    assert attrs["primary_issue"] == "missing_source_entities"
    assert attrs["next_step"] == "Add at least one source sensor to Garage Freezer"
    assert attrs["issues"][0]["reason"] == (
        "No source sensors are configured for this circuit."
    )
    assert attrs["issues"][0]["fix"] == (
        "Add at least one source sensor to Garage Freezer"
    )
    checklist = {item["item_id"]: item for item in attrs["checklist"]}
    assert checklist["source_data_found"]["title"] == "Source data needs attention"


def test_setup_health_includes_hvac_thermostat_source_issue() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
    )

    circuit = CircuitConfig(
        circuit_id="heat_pump",
        name="Downstairs Heat Pump",
        appliance_profile=ApplianceProfile.HEAT_PUMP,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.heat_pump_power", SensorRole.REAL_POWER),),
    )
    coordinator = SimpleNamespace(
        data=AnalyzerState(
            hvac_thermostat_setup_issues_by_circuit={
                "heat_pump": [
                    {
                        "issue_kind": "missing_required_sensor",
                        "circuit_id": "heat_pump",
                        "circuit_name": "Downstairs Heat Pump",
                        "reason": (
                            "Downstairs Heat Pump cannot use climate.downstairs "
                            "because no current temperature is available."
                        ),
                        "source_entities": ["climate.downstairs"],
                    }
                ]
            }
        ),
        circuit_configs=(circuit,),
    )

    issue = setup_health_attributes(coordinator)["issues"][0]

    assert issue["issue"] == "hvac_thermostat_source"
    assert issue["issue_kind"] == "missing_required_sensor"
    assert issue["circuit_name"] == "Downstairs Heat Pump"
    assert "Downstairs Heat Pump" in issue["reason"]
    assert issue["source_entities"] == ["climate.downstairs"]


@pytest.mark.parametrize(
    ("quality_issue", "numeric_states_valid"),
    [
        ("sensor.fridge_power unavailable", False),
        ("sensor.fridge_power naive_timestamp", True),
    ],
)
def test_setup_health_source_checklist_surfaces_invalid_source_issues(
    quality_issue: str,
    numeric_states_valid: bool,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
    )

    coordinator = SimpleNamespace(
        data=AnalyzerState(
            data_quality_checklist_by_circuit={
                "fridge": {
                    "sample_observed": True,
                    "required_sensors_present": True,
                    "numeric_states_valid": numeric_states_valid,
                    "source_data_fresh": True,
                    "quality_issues": [quality_issue],
                }
            }
        ),
        circuit_configs=(
            CircuitConfig(
                circuit_id="fridge",
                name="Kitchen Fridge",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
            ),
        ),
    )

    checklist = {
        item["item_id"]: item
        for item in setup_health_attributes(coordinator)["checklist"]
    }

    assert checklist["source_data_found"]["status"] == "needs_attention"
    assert checklist["source_data_found"]["affected_circuits"] == ["fridge"]


@pytest.mark.parametrize(
    ("quality_issues", "checklist_overrides", "expected_issue", "expected_entity"),
    [
        (
            [
                "sensor.badtime future_timestamp",
                "sensor.current stale",
            ],
            {"source_data_fresh": False},
            "invalid_source_timestamp",
            "sensor.badtime",
        ),
        (
            [
                "sensor.badvalue unavailable",
                "sensor.current stale",
            ],
            {"numeric_states_valid": False, "source_data_fresh": False},
            "invalid_source_sensor",
            "sensor.badvalue",
        ),
        (
            [
                "sensor.current stale",
                "sensor.missing missing",
            ],
            {"required_sensors_present": False, "source_data_fresh": False},
            "stale_source",
            "sensor.current",
        ),
    ],
)
def test_setup_health_filters_source_entities_for_selected_issue(
    quality_issues: list[str],
    checklist_overrides: dict[str, bool],
    expected_issue: str,
    expected_entity: str,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
    )

    checklist = {
        "sample_observed": True,
        "required_sensors_present": True,
        "numeric_states_valid": True,
        "source_data_fresh": True,
        "quality_issues": quality_issues,
        **checklist_overrides,
    }
    coordinator = SimpleNamespace(
        data=AnalyzerState(
            data_quality_checklist_by_circuit={"fridge": checklist}
        ),
        circuit_configs=(
            CircuitConfig(
                circuit_id="fridge",
                name="Kitchen Fridge",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=tuple(
                    SensorRef(entity_id, SensorRole.REAL_POWER)
                    for entity_id in (
                        "sensor.badtime",
                        "sensor.badvalue",
                        "sensor.current",
                        "sensor.missing",
                    )
                ),
            ),
        ),
    )

    issue = setup_health_attributes(coordinator)["issues"][0]

    assert issue["issue"] == expected_issue
    assert issue["source_entities"] == [expected_entity]


def test_setup_health_attributes_include_guided_onboarding_checklist() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
    )

    coordinator = SimpleNamespace(
        data=AnalyzerState(
            data_quality_checklist_by_circuit={
                "fridge": {
                    "sample_observed": True,
                    "required_sensors_present": True,
                    "numeric_states_valid": True,
                    "source_data_fresh": True,
                }
            },
            energy_dashboard_status_by_circuit={"fridge": "needs_energy_source"},
            energy_dashboard_evidence_by_circuit={
                "fridge": {"status": "needs_energy_source"}
            },
        ),
        circuit_configs=(
            CircuitConfig(
                circuit_id="fridge",
                name="Kitchen Fridge",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
            ),
        ),
        options={
            CONF_ENTITY_DETAIL_LEVEL: "standard",
            CONF_ENABLE_EXPERIMENTAL_NILM: False,
        },
        last_dashboard_create_request={"action": "created"},
    )

    attrs = setup_health_attributes(coordinator)
    checklist = {item["item_id"]: item for item in attrs["checklist"]}

    assert attrs["checklist_total_count"] == 10
    assert checklist["source_data_found"]["status"] == "ok"
    assert checklist["source_data_found"]["title"] == (
        "Source data is available and healthy"
    )
    assert checklist["cumulative_kwh_sources_found"]["status"] == "ok"
    assert "affected_circuits" not in checklist["cumulative_kwh_sources_found"]
    assert checklist["dashboard_created"]["status"] == "ok"
    assert checklist["nilm_enabled"]["status"] == "optional"
    assert checklist["learning_progress"]["status"] == "ok"
    assert attrs["checklist_ready_count"] == 10


def test_setup_health_waits_to_verify_configured_source_data() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
    )
    from custom_components.circuitsetup_energy_analyzer.ux import (
        data_quality_checklist,
    )

    circuit = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
    )
    coordinator = SimpleNamespace(
        data=AnalyzerState(
            data_quality_checklist_by_circuit={
                "fridge": data_quality_checklist(circuit, None)
            }
        ),
        circuit_configs=(circuit,),
    )

    checklist = {
        item["item_id"]: item
        for item in setup_health_attributes(coordinator)["checklist"]
    }

    assert checklist["source_data_found"]["status"] == "learning"
    assert checklist["source_data_found"]["title"] == (
        "Waiting to verify source data"
    )


def test_setup_health_unassigned_source_waits_for_verification() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
    )

    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        circuit_configs=(),
        options={CONF_SOURCE_ENTITIES: ["sensor.unassigned_power"]},
    )

    checklist = {
        item["item_id"]: item
        for item in setup_health_attributes(coordinator)["checklist"]
    }
    assert checklist["source_data_found"]["status"] == "learning"
    assert checklist["source_data_found"]["title"] == (
        "Waiting to verify source data"
    )
    assert checklist["source_data_found"]["fix"] == "Review circuit assignments"
    assert checklist["source_data_found"]["open_path"].startswith(
        "/config/integrations/"
    )
    assert checklist["circuit_assignments_reviewed"]["status"] == "needs_attention"


def test_setup_health_valid_ct_row_has_no_action() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
    )

    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        circuit_configs=(
            CircuitConfig(
                circuit_id="fridge",
                name="Kitchen Fridge",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
            ),
        ),
        entry_id="entry-1",
    )

    checklist = {
        item["item_id"]: item
        for item in setup_health_attributes(coordinator)["checklist"]
    }
    assert checklist["ct_direction_valid"]["status"] == "ok"
    assert "fix" not in checklist["ct_direction_valid"]
    assert "open_path" not in checklist["ct_direction_valid"]


def test_setup_health_dashboard_checklist_survives_reload_status() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
    )

    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        circuit_configs=(
            CircuitConfig(
                circuit_id="fridge",
                name="Kitchen Fridge",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(
                    SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),
                    SensorRef("sensor.fridge_energy", SensorRole.ENERGY),
                ),
            ),
        ),
        options={
            CONF_ENTITY_DETAIL_LEVEL: "standard",
            CONF_ENABLE_EXPERIMENTAL_NILM: False,
        },
        dashboard_status={"action": "created"},
        last_dashboard_create_request=None,
    )

    attrs = setup_health_attributes(coordinator)
    checklist = {item["item_id"]: item for item in attrs["checklist"]}

    assert checklist["dashboard_created"]["status"] == "ok"


def test_summary_sensors_answer_primary_user_questions() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        activity_summary_attributes,
        activity_summary_value,
        electrical_health_attributes,
        energy_summary_attributes,
        energy_summary_value,
        health_summary_attributes,
        health_summary_value,
    )

    state = AnalyzerState(
        health_summary_by_circuit={"washer": "Possible issue"},
        hvac_association_revision_by_circuit={"washer": 7},
        readiness_by_circuit={"washer": {"health_status": "possible_issue"}},
        run_cycle_status_by_circuit={"washer": "running"},
        run_cycle_count_by_circuit={"washer": 2},
        run_cycle_runtime_seconds_by_circuit={"washer": 1800.0},
        standby_status_by_circuit={"washer": "on"},
        metric_consistency_status_by_circuit={"washer": "metric_mismatch"},
        metric_consistency_score_by_circuit={"washer": 28.5},
        metric_consistency_evidence_by_circuit={
            "washer": {"status": "metric_mismatch", "largest_mismatch": 0.285}
        },
        leg_imbalance_status_by_circuit={"washer": "not_dual_phase"},
        power_quality_evidence_by_circuit={
            "washer": "Possible issue: apparent power changed"
        },
        power_quality_score_by_circuit={"washer": 0.42},
        daily_energy_usage_by_circuit={"washer": 13.1},
        energy_usage_evidence_by_circuit={
            "washer": {"status": "over_threshold", "threshold_kwh": 12.5}
        },
        energy_goal_status_by_circuit={"washer": "tracking"},
        billing_cycle_status_by_circuit={"washer": "projected_over_budget"},
        billing_cycle_evidence_by_circuit={
            "washer": {"status": "projected_over_budget", "budget_kwh": 50.0}
        },
        cost_status_by_circuit={"washer": "tracking"},
        active_alerts_by_circuit={"washer": [object(), object()]},
    )

    assert health_summary_value(state, "washer") == "Possible issue"
    health_attrs = health_summary_attributes(state, "washer")
    assert health_attrs["raw_status"] == "possible_issue"
    assert health_attrs["hvac_association_revision"] == 7
    assert health_attrs["status_label"] == "Possible issue"
    assert health_attrs["active_alert_count"] == 2
    assert health_attrs["alert_confirmed"] is True
    assert health_attrs["next_step"] == "Review source sensor data"
    assert health_attrs["learning_progress"] == 0.0
    assert health_attrs["evidence_path"] == (
        "/circuitsetup-energy-analyzer-evidence?circuit_id=washer"
    )
    assert health_attrs["electrical_summary"] == "Possible Metric Mismatch"
    assert health_attrs["metric_consistency_status"] == "metric_mismatch"
    assert health_attrs["metric_consistency_score"] == 28.5
    assert health_attrs["power_quality_evidence"] == (
        "Possible issue: apparent power changed"
    )
    assert health_attrs["what_to_check_first"]

    assert activity_summary_value(state, "washer") == "Running"
    assert activity_summary_attributes(state, "washer") == {
        "is_running": True,
        "run_cycle_status": "running",
        "standby_status": "on",
        "run_cycle_count": 2,
        "run_cycle_runtime_seconds": 1800.0,
        "duty_cycle_percent": 0.0,
        "summary_explanation": "The appliance is currently active.",
    }

    electrical_attrs = electrical_health_attributes(state, "washer")
    assert electrical_attrs["summary"] == "Possible Metric Mismatch"
    assert electrical_attrs["metric_consistency_status"] == "metric_mismatch"
    assert electrical_attrs["metric_consistency_score"] == 28.5
    assert electrical_attrs["alert_confirmed"] is True
    assert electrical_attrs["status_explanation"] == (
        "Reported electrical measurements do not agree with each other."
    )
    assert electrical_attrs["power_quality_evidence"] == (
        "Possible issue: apparent power changed"
    )
    assert electrical_attrs["evidence_path"] == (
        "/circuitsetup-energy-analyzer-evidence?circuit_id=washer"
    )

    assert energy_summary_value(state, "washer") == "High Usage"
    energy_attrs = energy_summary_attributes(state, "washer")
    assert energy_attrs["energy_usage_status"] == "over_threshold"
    assert energy_attrs["billing_cycle_status"] == "projected_over_budget"
    assert energy_attrs["daily_energy_usage_kwh"] == 13.1
    assert energy_attrs["alert_confirmed"] is True
    assert energy_attrs["summary_explanation"] == (
        "Energy use is above a configured threshold or budget."
    )
    assert energy_attrs["evidence_path"] == (
        "/circuitsetup-energy-analyzer-evidence?circuit_id=washer"
    )


def test_health_summary_attributes_explain_observation_without_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        electrical_health_attributes,
        energy_summary_attributes,
        energy_summary_value,
        health_summary_attributes,
        health_summary_value,
    )

    state = AnalyzerState(
        health_summary_by_circuit={"fridge": "Observation recorded"},
        readiness_by_circuit={"fridge": {"health_status": "observation"}},
    )

    assert health_summary_value(state, "fridge") == "Observation recorded"
    assert health_summary_attributes(state, "fridge")["status_explanation"] == (
        "A noteworthy observation was recorded, but repeated evidence is still "
        "required before an alert is raised."
    )
    assert health_summary_attributes(state, "fridge")["alert_confirmed"] is False

    power_quality_only_state = AnalyzerState(
        metric_consistency_status_by_circuit={"pump": "missing_metrics"},
        power_quality_evidence_by_circuit={
            "pump": "Possible issue: reactive power changed from baseline"
        },
        power_quality_score_by_circuit={"pump": 0.35},
    )

    assert (
        electrical_health_attributes(power_quality_only_state, "pump")["summary"]
        == "Possible Power Quality Change"
    )
    assert (
        electrical_health_attributes(power_quality_only_state, "pump")[
            "status_explanation"
        ]
        == "Power-quality evidence has changed from the learned baseline."
    )
    assert (
        electrical_health_attributes(power_quality_only_state, "pump")[
            "power_quality_alert_confirmed"
        ]
        is False
    )

    score_only_state = AnalyzerState(
        metric_consistency_status_by_circuit={"mixed": "missing_metrics"},
        power_quality_score_by_circuit={"mixed": 0.35},
    )

    assert electrical_health_attributes(score_only_state, "mixed")["summary"] == (
        "Needs Metrics"
    )

    power_only_state = AnalyzerState()
    assert energy_summary_value(power_only_state, "pump") == "Needs Energy Data"
    assert (
        energy_summary_attributes(power_only_state, "pump")["summary_explanation"]
        == "No cumulative kWh evidence is available for this circuit."
    )


def test_electrical_health_marks_confirmed_power_quality_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        electrical_health_attributes,
    )

    state = AnalyzerState(
        power_quality_evidence_by_circuit={
            "pump": "Possible issue: reactive power changed from baseline"
        },
        active_alerts_by_circuit={
            "pump": [
                AlertEvidence(
                    timestamp=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
                    circuit_id="pump",
                    severity=Severity.WARNING,
                    message="Possible issue: reactive power changed from baseline",
                    feature="reactive_shift_under_stable_real_power",
                )
            ]
        },
    )

    assert (
        electrical_health_attributes(state, "pump")["power_quality_alert_confirmed"]
        is True
    )


def test_activity_summary_prefers_operating_state_lane() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        activity_summary_attributes,
        activity_summary_value,
    )

    state = AnalyzerState(
        operating_state_snapshot_by_circuit={
            "dryer": {"state": "pending_off", "stable_state": "running"},
            "washer": {"state": "pending_on", "stable_state": "off"},
        },
        run_cycle_status_by_circuit={"dryer": "idle", "washer": "running"},
        standby_status_by_circuit={"dryer": "off", "washer": "on"},
        run_cycle_count_by_circuit={"dryer": 1, "washer": 2},
        run_cycle_runtime_seconds_by_circuit={"dryer": 1800.0, "washer": 0.0},
    )

    assert activity_summary_value(state, "dryer") == "Running"
    assert activity_summary_value(state, "washer") == "Idle"
    assert activity_summary_attributes(state, "dryer")["operating_state"] == (
        "pending_off"
    )


def test_activity_summary_reports_unavailable_operating_state() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        activity_summary_attributes,
        activity_summary_value,
    )

    state = AnalyzerState(
        operating_state_snapshot_by_circuit={
            "fridge": {"state": "unavailable", "stable_state": "unavailable"}
        },
        run_cycle_status_by_circuit={"fridge": "running"},
        standby_status_by_circuit={"fridge": "on"},
    )

    assert activity_summary_value(state, "fridge") == "Unavailable"
    assert activity_summary_attributes(state, "fridge")["summary_explanation"] == (
        "Current operating state is unavailable because source data is missing "
        "or stale."
    )


def test_setup_health_prioritizes_actionable_next_steps() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
        setup_health_value,
    )

    def coordinator_for(
        circuit: CircuitConfig,
        state: AnalyzerState | None = None,
        *,
        store_data: FeatureStoreData | None = None,
        options: dict[str, object] | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            data=state or AnalyzerState(),
            circuit_configs=(circuit,),
            store_data=store_data,
            options=options or {},
        )

    fridge = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
    )
    hvac = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(
            SensorRef("sensor.hvac_power", SensorRole.REAL_POWER),
            SensorRef("sensor.hvac_current", SensorRole.CURRENT),
        ),
    )
    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )

    stale = coordinator_for(
        fridge,
        AnalyzerState(
            data_quality_checklist_by_circuit={
                "fridge": {
                    "quality_issues": ["sensor.fridge_power stale"],
                    "required_sensors_present": True,
                    "source_data_fresh": False,
                }
            }
        ),
    )
    assert setup_health_value(stale) == "Fix stale source sensor"

    invalid_source = coordinator_for(
        fridge,
        AnalyzerState(
            data_quality_checklist_by_circuit={
                "fridge": {
                    "quality_issues": ["sensor.fridge_power non_finite"],
                    "required_sensors_present": True,
                    "source_data_fresh": True,
                    "numeric_states_valid": False,
                }
            }
        ),
    )
    assert setup_health_value(invalid_source) == (
        "Fix unavailable or invalid source data"
    )

    invalid_timestamp = coordinator_for(
        fridge,
        AnalyzerState(
            data_quality_checklist_by_circuit={
                "fridge": {
                    "quality_issues": ["sensor.fridge_power future_timestamp"],
                    "required_sensors_present": True,
                    "source_data_fresh": True,
                    "numeric_states_valid": True,
                }
            }
        ),
    )
    assert setup_health_value(invalid_timestamp) == "Fix source sensor timestamps"

    negative_power = coordinator_for(
        fridge,
        AnalyzerState(
            data_quality_checklist_by_circuit={
                "fridge": {
                    "quality_issues": ["sensor.fridge_power negative_real_power_load"],
                    "required_sensors_present": True,
                }
            }
        ),
    )
    assert setup_health_value(negative_power) == "Check CT direction"

    truncated_negative_power = coordinator_for(
        fridge,
        AnalyzerState(
            data_quality_checklist_by_circuit={
                "fridge": {
                    "quality_issues": [
                        f"sensor.optional_{index} stale" for index in range(5)
                    ],
                    "quality_issues_full": [
                        *(f"sensor.optional_{index} stale" for index in range(5)),
                        "sensor.fridge_power negative_real_power_load",
                    ],
                    "required_sensors_present": True,
                    "source_data_fresh": False,
                }
            }
        ),
    )
    assert setup_health_value(truncated_negative_power) == "Check CT direction"

    assert setup_health_value(coordinator_for(hvac)) == "Configure breaker amps"

    optional_weather_context = coordinator_for(
        hvac,
        store_data=FeatureStoreData(
            capacity_settings_by_circuit={"hvac": {"breaker_amps": 40.0}},
        ),
    )
    assert setup_health_value(optional_weather_context) == "Ready"

    missing_mains = coordinator_for(
        mains,
        AnalyzerState(balance_status_by_circuit={"mains": "missing_mains"}),
    )
    assert setup_health_value(missing_mains) == "Add mains source"
    assert setup_health_attributes(missing_mains)["recommended_action"] == (
        "Add a mains or whole-home source"
    )


def test_setup_health_learning_next_step_uses_specific_progress_reason() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
    )

    waiting_for_delta = SimpleNamespace(
        data=AnalyzerState(
            energy_usage_evidence_by_circuit={"fridge": {"status": "waiting_for_delta"}}
        ),
        circuit_configs=(
            CircuitConfig(
                circuit_id="fridge",
                name="Kitchen Fridge",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(SensorRef("sensor.fridge_energy", SensorRole.ENERGY),),
            ),
        ),
        store_data=FeatureStoreData(),
        options={},
    )
    waiting_attrs = setup_health_attributes(waiting_for_delta)
    assert waiting_attrs["next_step"] == (
        "Waiting for first positive kWh increase on Kitchen Fridge"
    )

    derived_energy = SimpleNamespace(
        data=AnalyzerState(
            energy_usage_evidence_by_circuit={
                "fridge": {
                    "status": "waiting_for_delta",
                    "energy_source": "derived_from_power",
                }
            }
        ),
        circuit_configs=(
            CircuitConfig(
                circuit_id="fridge",
                name="Kitchen Fridge",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
            ),
        ),
        store_data=FeatureStoreData(),
        options={},
    )
    derived_attrs = setup_health_attributes(derived_energy)
    assert derived_attrs["next_step"] == (
        "Waiting for another power sample on Kitchen Fridge"
    )
    assert "automatic kWh helper" in derived_attrs["reason"]

    cycle_learning = SimpleNamespace(
        data=AnalyzerState(
            learning_progress_by_circuit={
                "washer": {"cycle_count": 5, "alert_ready": False}
            }
        ),
        circuit_configs=(
            CircuitConfig(
                circuit_id="washer",
                name="Washer",
                appliance_profile=ApplianceProfile.WASHER,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(SensorRef("sensor.washer_power", SensorRole.REAL_POWER),),
            ),
        ),
        store_data=FeatureStoreData(),
        options={},
    )
    cycle_attrs = setup_health_attributes(cycle_learning)
    assert cycle_attrs["next_step"] == "Learning: 3 more run cycles needed for Washer"


def test_setup_health_stale_source_lists_source_entities_and_circuits() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
    )

    coordinator = SimpleNamespace(
        data=AnalyzerState(
            data_quality_checklist_by_circuit={
                "fridge": {
                    "quality_issues": ["sensor.fridge_power stale"],
                    "required_sensors_present": True,
                    "source_data_fresh": False,
                }
            }
        ),
        circuit_configs=(
            CircuitConfig(
                circuit_id="fridge",
                name="Kitchen Fridge",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(
                    SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),
                    SensorRef("sensor.fridge_energy", SensorRole.ENERGY),
                ),
            ),
        ),
        store_data=FeatureStoreData(),
        options={},
    )

    attrs = setup_health_attributes(coordinator)

    assert attrs["stale_sources"] == ["sensor.fridge_power"]
    assert attrs["stale_source_circuits"] == ["fridge"]
    assert attrs["issues"][0]["source_entities"] == ["sensor.fridge_power"]


def test_setup_health_attributes_are_bounded_for_recorder() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
    )

    circuits = tuple(
        CircuitConfig(
            circuit_id=f"large_stale_circuit_{index:03d}_{'circuit_' * 24}",
            name=f"Large Stale Circuit {index:03d} {'Name ' * 32}",
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            mode=CircuitMode.SINGLE_PHASE,
            sensors=(
                SensorRef(
                    f"sensor.large_stale_circuit_{index:03d}_{'source_' * 28}power",
                    SensorRole.REAL_POWER,
                ),
            ),
        )
        for index in range(80)
    )
    coordinator = SimpleNamespace(
        data=AnalyzerState(
            data_quality_checklist_by_circuit={
                circuit.circuit_id: {
                    "quality_issues": [
                        f"{circuit.sensors[0].entity_id} stale for recorder cap test"
                    ],
                    "required_sensors_present": True,
                    "source_data_fresh": False,
                }
                for circuit in circuits
            }
        ),
        circuit_configs=circuits,
        store_data=FeatureStoreData(),
        options={},
    )

    attrs = setup_health_attributes(coordinator)
    encoded = json.dumps(attrs, sort_keys=True, default=str, separators=(",", ":"))

    assert len(encoded) <= 12_000
    assert attrs["issue_count"] == 80
    assert attrs["issue_summary"].startswith("80 warnings: Fix stale source")
    assert attrs["issue_summary"].endswith("(+79 more)")
    assert len(attrs["issue_summary"]) <= 80
    assert attrs["issues"][0]["affected_circuit"].startswith(
        "large_stale_circuit_000",
    )
    assert len(attrs["issues"][0]["affected_circuit"]) <= 80
    assert attrs["issues_truncated_count"] > 0
    assert attrs["stale_sources_truncated_count"] > 0


def test_setup_health_attributes_keep_multi_issue_payload_small() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
    )

    profiles = (
        ApplianceProfile.HVAC,
        ApplianceProfile.WELL_PUMP,
        ApplianceProfile.WATER_HEATER,
        ApplianceProfile.MAINS_NILM,
    )
    circuits = tuple(
        CircuitConfig(
            circuit_id=f"multi_issue_circuit_{index:03d}_{'circuit_' * 12}",
            name=f"Multi Issue Circuit {index:03d} {'Name ' * 16}",
            appliance_profile=profiles[index % len(profiles)],
            mode=(
                CircuitMode.DUAL_PHASE
                if index % len(profiles) in {0, 2}
                else CircuitMode.SINGLE_PHASE
            ),
            sensors=(
                SensorRef(
                    f"sensor.multi_issue_circuit_{index:03d}_{'source_' * 16}power",
                    SensorRole.REAL_POWER,
                ),
                SensorRef(
                    f"sensor.multi_issue_circuit_{index:03d}_{'source_' * 16}current",
                    SensorRole.CURRENT,
                ),
            ),
        )
        for index in range(80)
    )
    utility_settings = {
        circuit.circuit_id: {
            "enabled": True,
            "utility_source_entity": f"sensor.utility_{index}",
            "measured_source_entity": f"sensor.measured_{index}",
        }
        for index, circuit in enumerate(circuits)
    }
    coordinator = SimpleNamespace(
        data=AnalyzerState(
            data_quality_checklist_by_circuit={
                circuit.circuit_id: {
                    "quality_issues": [
                        (
                            f"{circuit.sensors[0].entity_id} stale unavailable "
                            "negative_real_power_load"
                        )
                    ],
                    "required_sensors_present": True,
                    "source_data_fresh": False,
                }
                for circuit in circuits
            },
            balance_status_by_circuit={
                circuit.circuit_id: (
                    "missing_mains"
                    if circuit.appliance_profile is ApplianceProfile.MAINS_NILM
                    else "negative_balance"
                )
                for circuit in circuits
            },
            utility_comparison_status_by_circuit={
                circuit.circuit_id: "missing_utility" for circuit in circuits
            },
        ),
        circuit_configs=circuits,
        store_data=FeatureStoreData(
            utility_comparison_settings_by_circuit=utility_settings,
        ),
        options={CONF_UTILITY_COMPARISON_SETTINGS: utility_settings},
    )

    attrs = setup_health_attributes(coordinator)
    encoded = json.dumps(attrs, sort_keys=True, default=str, separators=(",", ":"))

    assert len(encoded) <= 6_000
    assert attrs["issue_count"] > 80
    assert attrs["issues_truncated_count"] > 0
    assert attrs["affected_circuits_truncated_count"] > 0
    assert attrs["negative_power_loads_truncated_count"] > 0
    assert attrs["utility_comparison_setup_issues_truncated_count"] > 0


def test_setup_health_attributes_bound_oversized_strings() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
    )

    source_entity = f"sensor.{'very_long_source_entity_name_' * 20}power"
    circuit = CircuitConfig(
        circuit_id="long_source_circuit",
        name="Long Source Circuit",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef(source_entity, SensorRole.REAL_POWER),),
    )
    coordinator = SimpleNamespace(
        data=AnalyzerState(
            data_quality_checklist_by_circuit={
                circuit.circuit_id: {
                    "quality_issues": [f"{source_entity} is stale"],
                    "required_sensors_present": True,
                    "source_data_fresh": False,
                }
            }
        ),
        circuit_configs=(circuit,),
        store_data=FeatureStoreData(),
        options={},
    )

    attrs = setup_health_attributes(coordinator)
    encoded = json.dumps(attrs, sort_keys=True, default=str, separators=(",", ":"))
    bounded_source = attrs["issues"][0]["source_entities"][0]

    assert len(encoded) <= 12_000
    assert len(bounded_source) <= 80
    assert bounded_source.endswith("...")
    assert attrs["stale_sources"] == [bounded_source]


def test_setup_health_ignores_unselected_optional_context_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
        setup_health_value,
    )

    sump_pump = CircuitConfig(
        circuit_id="sump_pump",
        name="Sump Pump",
        appliance_profile=ApplianceProfile.SUMP_PUMP,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.sump_power", SensorRole.REAL_POWER),),
    )
    washer = CircuitConfig(
        circuit_id="washer",
        name="Washer",
        appliance_profile=ApplianceProfile.WASHER,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.washer_power", SensorRole.REAL_POWER),),
    )
    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = SimpleNamespace(
        data=AnalyzerState(
            utility_comparison_status_by_circuit={"mains": "missing_measured"}
        ),
        circuit_configs=(sump_pump, washer, mains),
        entry_data={
            CONF_ADVANCED_SETTINGS: {
                "sump_pump": {CONF_RAIN_PUMP_CORRELATION_ENABLED: True},
                "washer": {CONF_WATER_FLOW_CORRELATION_ENABLED: True},
            },
            CONF_UTILITY_COMPARISON_SETTINGS: {
                "mains": {"utility_energy_entity": "sensor.utility_kwh"}
            },
        },
        store_data=FeatureStoreData(
            utility_comparison_settings_by_circuit={
                "mains": {"utility_energy_entity": "sensor.utility_kwh"}
            }
        ),
        options={},
    )

    attrs = setup_health_attributes(coordinator)

    assert setup_health_value(coordinator) == "Add measured kWh source"
    assert attrs["missing_rain_sources"] == []
    assert attrs["missing_water_flow_sources"] == []
    assert attrs["utility_comparison_setup_issues"] == ["mains"]
    assert attrs["primary_issue"] == "utility_comparison_missing_measured_source"
    assert attrs["primary_severity"] == "warning"
    assert attrs["issue_summary"] == "1 warning: Add measured kWh source for Mains"
    assert [issue["issue"] for issue in attrs["issues"]] == [
        "utility_comparison_missing_measured_source",
    ]


def test_setup_health_honors_linked_water_flow_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
    )

    washer = CircuitConfig(
        circuit_id="washer",
        name="Washer",
        appliance_profile=ApplianceProfile.WASHER,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.washer_power", SensorRole.REAL_POWER),),
    )
    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        circuit_configs=(washer,),
        entry_data={},
        options={
            CONF_ADVANCED_SETTINGS: {
                "washer": {
                    CONF_WATER_FLOW_CORRELATION_ENABLED: True,
                    CONF_LINKED_FLOW_SENSOR_ENTITIES: ["binary_sensor.washer_flow"],
                }
            }
        },
        store_data=FeatureStoreData(),
    )

    attrs = setup_health_attributes(coordinator)

    assert attrs["missing_water_flow_sources"] == []
    assert attrs["issues"] == []


@pytest.mark.parametrize(
    ("status", "expected_issue", "expected_step", "expected_reason"),
    (
        (
            "missing_utility",
            "utility_comparison_missing_utility_source",
            "Add utility comparison source for Mains",
            "Utility comparison is enabled, but utility kWh has no data.",
        ),
        (
            "missing_measured",
            "utility_comparison_missing_measured_source",
            "Add measured kWh source for Mains",
            "Utility comparison is enabled, but measured kWh has no data.",
        ),
    ),
)
def test_setup_health_reports_specific_utility_comparison_setup_gaps(
    status: str,
    expected_issue: str,
    expected_step: str,
    expected_reason: str,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
    )

    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = SimpleNamespace(
        data=AnalyzerState(utility_comparison_status_by_circuit={"mains": status}),
        circuit_configs=(mains,),
        entry_data={
            CONF_UTILITY_COMPARISON_SETTINGS: {
                "mains": {"utility_energy_entity": "sensor.utility_kwh"}
            },
        },
        store_data=FeatureStoreData(
            utility_comparison_settings_by_circuit={
                "mains": {"utility_energy_entity": "sensor.utility_kwh"}
            }
        ),
        options={},
    )

    attrs = setup_health_attributes(coordinator)

    assert attrs["next_step"] == expected_step
    assert attrs["primary_issue"] == expected_issue
    assert attrs["reason"] == expected_reason
    assert attrs["utility_comparison_setup_issues"] == ["mains"]
    assert attrs["issues"][0]["issue"] == expected_issue
    assert attrs["issues"][0]["reason"] == expected_reason


def test_setup_health_merges_utility_comparison_config_sources_per_circuit() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes,
    )

    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = SimpleNamespace(
        data=AnalyzerState(
            utility_comparison_status_by_circuit={"mains": "missing_utility"},
        ),
        circuit_configs=(mains,),
        entry_data={
            CONF_UTILITY_COMPARISON_SETTINGS: {
                "mains": {"utility_energy_entity": "sensor.utility_kwh"},
            },
        },
        options={
            CONF_UTILITY_COMPARISON_SETTINGS: {
                "garage": {"utility_energy_entity": "sensor.garage_utility_kwh"},
            },
        },
        store_data=FeatureStoreData(),
    )

    attrs = setup_health_attributes(coordinator)

    assert attrs["utility_comparison_setup_issues"] == ["mains"]
    assert attrs["issues"][0]["issue"] == ("utility_comparison_missing_utility_source")


def test_binary_sensor_helpers_return_diagnostic_values_and_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        has_data_quality_problem,
        is_learning,
        is_maintenance_active,
    )

    state = AnalyzerState(
        learning_by_circuit={"fridge": False},
        data_quality_by_circuit={
            "fridge": "",
            "well_pump": "missing current sample",
        },
        maintenance_by_circuit={"fridge": {"active": True}},
    )

    assert is_learning(state, "fridge") is False
    assert is_learning(state, "unknown") is True
    assert has_data_quality_problem(state, "fridge") is False
    assert has_data_quality_problem(state, "well_pump") is True
    assert has_data_quality_problem(state, "unknown") is False
    assert is_maintenance_active(state, "fridge") is True
    assert is_maintenance_active(state, "unknown") is False


def test_demo_source_values_are_intentionally_triggerable() -> None:
    from custom_components.circuitsetup_energy_analyzer.metric_consistency import (
        evaluate_metric_consistency,
    )
    from custom_components.circuitsetup_energy_analyzer.phase_balance import (
        evaluate_dual_phase_leg_imbalance,
    )
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        _demo_source_value,
    )

    expected_recent_energy_kwh = {
        "mains_l1": 868.4,
        "mains_l2": 852.7,
        "refrigerator": 52.6,
        "hvac_l1": 188.4,
        "hvac_l2": 171.9,
        "water_heater_l1": 84.3,
        "water_heater_l2": 84.1,
        "pool_pump": 77.6,
        "washer": 14.2,
        "dryer_l1": 63.7,
        "dryer_l2": 63.1,
        "car_charger_l1": 151.4,
        "car_charger_l2": 150.8,
    }
    assert {
        circuit_id: _demo_source_value(circuit_id, SensorRole.ENERGY)
        for circuit_id in expected_recent_energy_kwh
    } == expected_recent_energy_kwh

    hvac_l1_w = _demo_source_value("hvac_l1", SensorRole.REAL_POWER)
    hvac_l2_w = _demo_source_value("hvac_l2", SensorRole.REAL_POWER)
    imbalance = evaluate_dual_phase_leg_imbalance(
        left_real_power_w=hvac_l1_w,
        right_real_power_w=hvac_l2_w,
    )
    assert imbalance.status == "imbalanced"
    assert imbalance.imbalance_percent >= 50.0

    reported_va = (_demo_source_value("hvac_l1", SensorRole.APPARENT_POWER) or 0.0) + (
        _demo_source_value("hvac_l2", SensorRole.APPARENT_POWER) or 0.0
    )
    reported_pf = (
        (_demo_source_value("hvac_l1", SensorRole.POWER_FACTOR) or 0.0)
        + (_demo_source_value("hvac_l2", SensorRole.POWER_FACTOR) or 0.0)
    ) / 2.0
    consistency = evaluate_metric_consistency(
        real_power_w=(hvac_l1_w or 0.0) + (hvac_l2_w or 0.0),
        apparent_power_va=reported_va,
        power_factor=reported_pf,
        voltage_v=None,
        current_a=None,
        leg_a_voltage_v=_demo_source_value("mains_l1", SensorRole.VOLTAGE),
        leg_a_current_a=_demo_source_value("hvac_l1", SensorRole.CURRENT),
        leg_b_voltage_v=_demo_source_value("mains_l2", SensorRole.VOLTAGE),
        leg_b_current_a=_demo_source_value("hvac_l2", SensorRole.CURRENT),
    )
    assert consistency.status in {"apparent_power_mismatch", "metric_mismatch"}


def test_sensor_descriptions_include_home_assistant_entity_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.const import (
        ENTITY_DETAIL_SIMPLE,
    )
    from custom_components.circuitsetup_energy_analyzer.entity import EntityTier
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
    )

    required_attrs = {
        "device_class",
        "entity_category",
        "entity_registry_enabled_default",
        "entity_registry_visible_default",
        "entity_picture",
        "entity_tier",
        "force_update",
        "has_entity_name",
        "icon",
        "last_reset",
        "name",
        "native_unit_of_measurement",
        "options",
        "state_class",
        "suggested_display_precision",
        "suggested_unit_of_measurement",
        "translation_key",
        "translation_placeholders",
        "unit_of_measurement",
    }

    for description in SENSOR_DESCRIPTIONS:
        missing_attrs = sorted(
            attr for attr in required_attrs if not hasattr(description, attr)
        )
        assert missing_attrs == []
        if description.entity_tier is EntityTier.SUMMARY:
            assert description.entity_registry_enabled_default is True
        else:
            assert description.entity_registry_enabled_default is False
        assert description.last_reset is None
        assert description.options is None
        assert description.unit_of_measurement is None
    assert ENTITY_DETAIL_SIMPLE == "simple"


def test_daily_energy_and_cost_sensor_descriptions() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        CircuitAnalyzerSensor,
    )

    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    state = AnalyzerState(
        estimated_cost_today_by_circuit={"fridge": 0.48},
        cost_today_by_circuit={"fridge": 0.56},
        cost_today_status_by_circuit={"fridge": "actual"},
        average_cost_per_day_by_circuit={"fridge": 0.3},
        average_kwh_per_day_by_circuit={"fridge": 1.5},
    )
    circuit = SimpleNamespace(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile="refrigerator",
    )

    assert descriptions["daily_energy_usage"].name_suffix == "Energy Usage Today"
    assert descriptions["daily_energy_usage"].device_class == "energy"
    assert descriptions["daily_energy_usage"].state_class == "total_increasing"
    assert descriptions["cost_today"].value_fn(state, "fridge") == 0.56
    state.cost_today_status_by_circuit["fridge"] = "unavailable"
    assert descriptions["cost_today"].value_fn(state, "fridge") == 0.48
    assert descriptions["cost_today"].device_class == "monetary"
    assert descriptions["cost_today"].state_class == "total"
    assert descriptions["average_cost_per_day"].device_class == "monetary"
    assert descriptions["average_cost_per_day"].state_class is None
    assert descriptions["average_cost_per_day"].value_fn(state, "fridge") == 0.3
    assert descriptions["cost_cycle"].state_class == "total"
    assert descriptions["cost_cycle_forecast"].state_class is None
    assert descriptions["average_kwh_per_day"].value_fn(state, "fridge") == 1.5
    assert descriptions["average_kwh_per_day"].native_unit_of_measurement == "kWh"
    cost_entity = CircuitAnalyzerSensor(
        SimpleNamespace(
            data=state,
            hass=SimpleNamespace(config=SimpleNamespace(currency="EUR")),
        ),
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["cost_today"],
    )
    assert cost_entity.native_unit_of_measurement == "EUR"
    assert CircuitAnalyzerSensor(
        SimpleNamespace(data=state),
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["daily_energy_usage"],
    ).unique_id.endswith("_fridge_daily_energy_usage")


def test_sensor_descriptions_classify_dashboard_vs_advanced_detail() -> None:
    from custom_components.circuitsetup_energy_analyzer.entity import (
        EntityCategory,
        EntityTier,
    )
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        CircuitAnalyzerSensor,
    )

    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}

    visible_by_default = {
        description.key
        for description in SENSOR_DESCRIPTIONS
        if description.entity_registry_visible_default is True
    }
    assert visible_by_default == {
        "health_summary",
        "activity_summary",
        "energy_summary",
        "daily_energy_usage",
        "cost_today",
        "average_cost_per_day",
        "average_kwh_per_day",
        "nilm_signature_count",
        "nilm_unknown_loads",
        "weather_context",
        "rain_pump_correlation",
        "water_flow_correlation",
    }
    simple_enabled_by_default = {
        description.key
        for description in SENSOR_DESCRIPTIONS
        if description.entity_registry_enabled_default is True
    }
    assert simple_enabled_by_default == {
        key
        for key, description in descriptions.items()
        if description.entity_tier is EntityTier.SUMMARY
    }

    normal_entity_keys = {
        "health_summary",
        "activity_summary",
        "energy_summary",
        "nilm_signature_count",
        "nilm_unknown_loads",
        "settings_suggestions",
        "daily_energy_usage",
        "cost_today",
        "average_cost_per_day",
        "average_kwh_per_day",
        "weather_context",
        "rain_pump_correlation",
        "water_flow_correlation",
        "water_flow_mismatch_minutes",
        "energy_usage_share",
        "energy_usage_status",
        "energy_goal_usage",
        "energy_goal_status",
        "run_cycle_count",
        "run_cycle_runtime",
        "run_cycle_duty_cycle",
        "current_demand",
        "peak_demand",
        "demand_limit_usage",
        "capacity_usage",
        "leg_imbalance",
        "balance_power",
        "monitored_power",
        "monitored_coverage",
        "solar_generation_power",
        "solar_flow_status",
        "solar_surplus_power",
        "solar_surplus_status",
        "utility_comparison_status",
        "billing_cycle_usage",
        "billing_cycle_forecast",
        "cost_cycle",
        "cost_cycle_forecast",
        "always_on_power",
        "always_on_limit_usage",
    }

    assert normal_entity_keys <= set(descriptions)
    assert "electrical_health" not in descriptions
    assert "standby_status" not in descriptions
    assert descriptions["settings_suggestions"].name_suffix == "Settings Suggestions"
    assert descriptions["settings_suggestions"].entity_registry_enabled_default is False
    assert descriptions["settings_suggestions"].entity_registry_visible_default is False
    assert descriptions["health_summary"].entity_tier is EntityTier.SUMMARY
    assert descriptions["daily_energy_usage"].entity_tier is EntityTier.SUMMARY
    assert descriptions["nilm_signature_count"].entity_tier is EntityTier.SUMMARY
    assert descriptions["nilm_unknown_loads"].entity_tier is EntityTier.SUMMARY
    assert descriptions["energy_goal_status"].entity_tier is EntityTier.FEATURE
    assert descriptions["leg_imbalance"].entity_tier is EntityTier.FEATURE
    assert descriptions["power_quality_score"].entity_tier is EntityTier.DIAGNOSTIC
    assert descriptions["power_quality_score"].entity_registry_enabled_default is False
    assert descriptions["metric_consistency_score"].entity_tier is (
        EntityTier.DIAGNOSTIC
    )
    assert (
        descriptions["metric_consistency_score"].entity_registry_enabled_default
        is False
    )
    for diagnostic_status_key in {
        "demand_status",
        "capacity_status",
        "balance_status",
    }:
        assert descriptions[diagnostic_status_key].entity_tier is (
            EntityTier.DIAGNOSTIC
        )
        assert (
            descriptions[diagnostic_status_key].entity_registry_enabled_default is False
        )

    for key in descriptions:
        expected_category = (
            None if key in normal_entity_keys else EntityCategory.DIAGNOSTIC
        )
        assert descriptions[key].entity_category == expected_category

    coordinator = SimpleNamespace(data=AnalyzerState())
    circuit = SimpleNamespace(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile="refrigerator",
    )
    normal_entity = CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["health_summary"],
    )
    diagnostic_entity = CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["power_quality_score"],
    )
    assert normal_entity._attr_entity_category is None
    assert normal_entity._attr_entity_registry_enabled_default is True
    assert diagnostic_entity._attr_entity_category == EntityCategory.DIAGNOSTIC
    assert diagnostic_entity._attr_entity_registry_enabled_default is False

    standard_coordinator = SimpleNamespace(
        data=AnalyzerState(),
        options={"entity_detail_level": "standard"},
    )
    expert_coordinator = SimpleNamespace(
        data=AnalyzerState(),
        options={"entity_detail_level": "expert"},
    )
    standard_feature_entity = CircuitAnalyzerSensor(
        standard_coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["energy_goal_status"],
    )
    standard_diagnostic_entity = CircuitAnalyzerSensor(
        standard_coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["power_quality_score"],
    )
    expert_diagnostic_entity = CircuitAnalyzerSensor(
        expert_coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["power_quality_score"],
    )
    assert standard_feature_entity._attr_entity_registry_enabled_default is True
    assert standard_diagnostic_entity._attr_entity_registry_enabled_default is False
    assert expert_diagnostic_entity._attr_entity_registry_enabled_default is True


def test_sensor_entities_use_purpose_specific_icons() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        CircuitAnalyzerSensor,
    )

    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    coordinator = SimpleNamespace(data=AnalyzerState())
    circuit = SimpleNamespace(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile="refrigerator",
    )

    expected_icons = {
        "activity_summary": "mdi:fridge-outline",
        "health_summary": "mdi:heart-pulse",
        "circuit_mode": "mdi:transmission-tower",
        "power_flow": "mdi:swap-horizontal",
        "settings_suggestions": "mdi:tune-variant",
        "power_quality_score": "mdi:sine-wave",
        "reactive_power_drift": "mdi:flash-triangle-outline",
        "power_factor_drift": "mdi:cosine-wave",
        "daily_energy_usage": "mdi:counter",
        "current_demand": "mdi:gauge",
        "metric_consistency_score": "mdi:clipboard-check-outline",
    }

    for key, icon in expected_icons.items():
        entity = CircuitAnalyzerSensor(
            coordinator,
            entry_id="entry-1",
            circuit=circuit,
            description=descriptions[key],
        )
        assert entity.icon == icon
        assert entity.icon != "mdi:eye"


def test_weather_context_sensor_exposes_readable_status_and_evidence() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        weather_context_attributes,
        weather_context_value,
    )

    state = SimpleNamespace(
        weather_context_by_circuit={
            "hvac": {
                "status": "above_weather_adjusted_range",
                "temperature_f": 92.0,
                "expected_high_w": 2400.0,
            },
            "blower": {"status": "weather_correlated"},
            "custom": {"status": "needs_manual_review"},
            "plain": "learning",
        }
    )

    assert weather_context_value(state, "hvac") == "Above Weather-Adjusted Range"
    assert weather_context_attributes(state, "hvac") == {
        "status": "above_weather_adjusted_range",
        "temperature_f": 92.0,
        "expected_high_w": 2400.0,
    }
    assert weather_context_value(state, "blower") == "Weather Correlated"
    assert weather_context_value(state, "custom") == "Needs Manual Review"
    assert weather_context_value(state, "plain") == "Learning"
    assert (
        weather_context_value(SimpleNamespace(), "missing") == "No Temperature Source"
    )
    assert weather_context_attributes(state, "missing") == {}


def test_weather_context_attributes_are_bounded() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        weather_context_attributes,
    )

    long_explanation = "Weather adjusted context " + ("with detail " * 20)
    comparison_samples = [
        {
            "timestamp": f"2026-06-13T12:{index:02d}:00+00:00",
            "runtime_minutes": 20 + index,
            "duty_cycle_percent": 10 + index,
            "extra_debug": [index] * 20,
        }
        for index in range(9)
    ]
    state = SimpleNamespace(
        weather_context_by_circuit={
            "hvac": {
                "status": "above_weather_adjusted_range",
                "temperature_f": 92.0,
                "expected_high_w": 2400.0,
                "explanation": long_explanation,
                "comparison_samples": comparison_samples,
                "temperature_bins": {
                    f"bin_{index:02d}": {"sample_count": index} for index in range(8)
                },
            }
        }
    )

    attrs = weather_context_attributes(state, "hvac")

    assert attrs["status"] == "above_weather_adjusted_range"
    assert attrs["temperature_f"] == 92.0
    assert attrs["expected_high_w"] == 2400.0
    assert attrs["explanation"] == (
        "Weather adjusted context with detail with detail with detail w..."
    )
    assert attrs["comparison_samples_count"] == 9
    assert attrs["comparison_samples_shown_count"] == 5
    assert attrs["comparison_samples_has_more"] is True
    assert attrs["comparison_samples"] == [
        {
            "timestamp": f"2026-06-13T12:{index:02d}:00+00:00",
            "runtime_minutes": 20 + index,
            "duty_cycle_percent": 10 + index,
        }
        for index in range(5)
    ]
    assert attrs["temperature_bins_count"] == 8
    assert attrs["temperature_bins_shown_count"] == 5
    assert attrs["temperature_bins_has_more"] is True
    assert attrs["temperature_bins"] == {
        f"bin_{index:02d}": {"sample_count": index} for index in range(5)
    }


def test_weather_context_sensor_metadata_is_user_facing_and_visible() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        CircuitAnalyzerSensor,
    )

    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    description = descriptions["weather_context"]
    coordinator = SimpleNamespace(data=AnalyzerState())
    circuit = SimpleNamespace(circuit_id="hvac", name="HVAC", appliance_profile="hvac")

    entity = CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=description,
    )

    assert description.name_suffix == "Weather Context"
    assert description.entity_category is None
    assert description.entity_registry_visible_default is True
    assert entity.icon == "mdi:thermometer-lines"
    assert entity._attr_entity_category is None


def test_weather_context_sensor_only_applies_to_hvac_with_temperature_source() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        sensor_description_applies,
    )

    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    weather_description = descriptions["weather_context"]
    coordinator_with_options = SimpleNamespace(
        options={CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.outdoor_temperature"},
        entry_data={},
    )
    coordinator_with_entry_data = SimpleNamespace(
        options={},
        entry_data={CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.outdoor_temperature"},
    )
    coordinator_without_temperature = SimpleNamespace(options={}, entry_data={})

    for profile in (
        ApplianceProfile.HVAC,
        ApplianceProfile.HVAC_COMPRESSOR,
        ApplianceProfile.HEAT_PUMP,
        ApplianceProfile.MINI_SPLIT,
        ApplianceProfile.HVAC_BLOWER,
        ApplianceProfile.ELECTRIC_HEAT,
    ):
        circuit = SimpleNamespace(
            circuit_id=profile.value,
            name=profile.value,
            appliance_profile=profile,
        )
        assert sensor_description_applies(
            weather_description,
            circuit,
            coordinator_with_options,
        )
        assert sensor_description_applies(
            weather_description,
            circuit,
            coordinator_with_entry_data,
        )
        assert not sensor_description_applies(
            weather_description,
            circuit,
            coordinator_without_temperature,
        )

    assert not sensor_description_applies(
        weather_description,
        SimpleNamespace(
            circuit_id="fridge",
            name="Fridge",
            appliance_profile=ApplianceProfile.REFRIGERATOR,
        ),
        coordinator_with_options,
    )


def test_heat_pump_uses_cyclic_and_high_power_entity_groups() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        _CYCLIC_APPLIANCE_PROFILES,
        _HIGH_POWER_PROFILES,
    )

    assert ApplianceProfile.HEAT_PUMP in _CYCLIC_APPLIANCE_PROFILES
    assert ApplianceProfile.HEAT_PUMP in _HIGH_POWER_PROFILES


def test_settings_suggestions_sensor_applies_to_every_configured_circuit() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        sensor_description_applies,
    )

    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    coordinator = SimpleNamespace(data=AnalyzerState())
    circuit_without_sources = SimpleNamespace(
        circuit_id="spare",
        name="Spare",
        appliance_profile="mixed",
    )
    mixed_circuit = SimpleNamespace(
        circuit_id="mixed",
        name="Mixed",
        sensors=[SensorRef(entity_id="sensor.mixed_power", role=SensorRole.REAL_POWER)],
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
    )

    assert sensor_description_applies(
        descriptions["settings_suggestions"],
        circuit_without_sources,
        coordinator,
    )
    assert sensor_description_applies(
        descriptions["settings_suggestions"],
        mixed_circuit,
        coordinator,
    )


def test_specific_profile_mixed_mode_hides_direct_appliance_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        BINARY_SENSOR_DESCRIPTIONS,
        binary_sensor_description_applies,
    )
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        sensor_description_applies,
    )

    sensors = {description.key: description for description in SENSOR_DESCRIPTIONS}
    binary = {
        description.key: description for description in BINARY_SENSOR_DESCRIPTIONS
    }
    circuit = CircuitConfig(
        circuit_id="washer",
        name="Washer",
        appliance_profile=ApplianceProfile.WASHER,
        mode=CircuitMode.MIXED,
        sensors=(
            SensorRef("sensor.power", SensorRole.REAL_POWER),
            SensorRef("sensor.current", SensorRole.CURRENT),
            SensorRef("sensor.voltage", SensorRole.VOLTAGE),
            SensorRef("sensor.var", SensorRole.REACTIVE_POWER),
            SensorRef("sensor.va", SensorRole.APPARENT_POWER),
            SensorRef("sensor.pf", SensorRole.POWER_FACTOR),
        ),
    )
    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        options={CONF_WATER_FLOW_SENSOR_ENTITIES: ["binary_sensor.water"]},
        entry_data={},
        store_data=FeatureStoreData(),
    )

    for key in (
        "activity_summary",
        "run_cycle_count",
        "power_quality_score",
        "reactive_power_drift",
        "apparent_power_drift",
        "power_factor_drift",
        "always_on_power",
        "water_flow_correlation",
    ):
        assert not sensor_description_applies(sensors[key], circuit, coordinator)
    assert sensor_description_applies(
        sensors["energy_usage_status"], circuit, coordinator
    )
    assert sensor_description_applies(
        sensors["metric_consistency_score"], circuit, coordinator
    )
    assert not binary_sensor_description_applies(
        binary["water_flow_mismatch"], circuit, coordinator
    )


def test_solar_generation_exposes_power_quality_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        sensor_description_applies,
    )

    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    solar = CircuitConfig(
        circuit_id="solar",
        name="Solar Inverter",
        appliance_profile=ApplianceProfile.SOLAR_INVERTER,
        mode=CircuitMode.SINGLE_PHASE,
        power_flow=PowerFlowMode.GENERATION,
        sensors=(
            SensorRef("sensor.solar_power", SensorRole.REAL_POWER),
            SensorRef("sensor.solar_var", SensorRole.REACTIVE_POWER),
            SensorRef("sensor.solar_va", SensorRole.APPARENT_POWER),
            SensorRef("sensor.solar_pf", SensorRole.POWER_FACTOR),
        ),
    )

    coordinator = SimpleNamespace(data=AnalyzerState())
    for key in (
        "power_quality_score",
        "reactive_power_drift",
        "apparent_power_drift",
        "power_factor_drift",
    ):
        assert sensor_description_applies(descriptions[key], solar, coordinator)


def test_dishwasher_exposes_water_cycle_and_demand_behavior() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        BINARY_SENSOR_DESCRIPTIONS,
        binary_sensor_description_applies,
    )
    from custom_components.circuitsetup_energy_analyzer.entities.setup_health import (
        _setup_health_needs_capacity_settings,
    )
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        sensor_description_applies,
    )

    sensors = {description.key: description for description in SENSOR_DESCRIPTIONS}
    binary_sensors = {
        description.key: description for description in BINARY_SENSOR_DESCRIPTIONS
    }
    circuit = CircuitConfig(
        circuit_id="dishwasher",
        name="Dishwasher",
        appliance_profile=ApplianceProfile.DISHWASHER,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(
            SensorRef("sensor.dishwasher_power", SensorRole.REAL_POWER),
            SensorRef("sensor.dishwasher_current", SensorRole.CURRENT),
        ),
    )
    coordinator = SimpleNamespace(
        options={CONF_WATER_FLOW_SENSOR_ENTITIES: ["binary_sensor.water_flow"]},
        entry_data={},
        store_data=FeatureStoreData(),
    )

    assert sensor_description_applies(
        sensors["run_cycle_count"], circuit, coordinator
    )
    assert sensor_description_applies(
        sensors["current_demand"], circuit, coordinator
    )
    assert sensor_description_applies(
        sensors["water_flow_correlation"], circuit, coordinator
    )
    assert binary_sensor_description_applies(
        binary_sensors["water_flow_mismatch"], circuit, coordinator
    )
    assert _setup_health_needs_capacity_settings(coordinator, circuit)


@pytest.mark.parametrize(
    "profile",
    [ApplianceProfile.MINI_SPLIT, ApplianceProfile.HEAT_PUMP],
)
@pytest.mark.parametrize("mode", [CircuitMode.SINGLE_PHASE, CircuitMode.DUAL_PHASE])
def test_bidirectional_hvac_exposes_cycle_demand_and_capacity_behavior(
    profile: ApplianceProfile,
    mode: CircuitMode,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.entities.setup_health import (
        _setup_health_needs_capacity_settings,
    )
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        sensor_description_applies,
    )

    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    circuit_id = profile.value
    circuit = CircuitConfig(
        circuit_id=circuit_id,
        name=profile.value.replace("_", " ").title(),
        appliance_profile=profile,
        mode=mode,
        sensors=(
            SensorRef(f"sensor.{circuit_id}_power", SensorRole.REAL_POWER),
            SensorRef(f"sensor.{circuit_id}_current", SensorRole.CURRENT),
        ),
    )
    unconfigured = SimpleNamespace(
        options={},
        entry_data={},
        store_data=FeatureStoreData(),
    )
    configured = SimpleNamespace(
        options={},
        entry_data={},
        store_data=FeatureStoreData(
            capacity_settings_by_circuit={circuit_id: {"breaker_amps": 20.0}},
        ),
    )

    assert sensor_description_applies(
        descriptions["run_cycle_count"], circuit, unconfigured
    )
    assert sensor_description_applies(
        descriptions["current_demand"], circuit, unconfigured
    )
    assert sensor_description_applies(
        descriptions["capacity_usage"], circuit, configured
    )
    assert _setup_health_needs_capacity_settings(unconfigured, circuit)


def test_shared_mains_voltage_enables_appliance_voltage_calculations() -> None:
    from custom_components.circuitsetup_energy_analyzer.entities.setup_health import (
        _setup_health_needs_capacity_settings,
    )
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        sensor_description_applies,
    )

    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    coordinator = SimpleNamespace(
        _mains_voltage_entity_ids=frozenset({"sensor.panel_voltage"}),
        store_data=FeatureStoreData(
            capacity_settings_by_circuit={"heater": {"breaker_amps": 20.0}},
        ),
    )
    heater = CircuitConfig(
        circuit_id="heater",
        name="Heater",
        appliance_profile=ApplianceProfile.ELECTRIC_HEAT,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.heater_power", SensorRole.REAL_POWER),),
    )
    pump = CircuitConfig(
        circuit_id="pump",
        name="Pump",
        appliance_profile=ApplianceProfile.WATER_PUMP,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(
            SensorRef("sensor.pump_power", SensorRole.REAL_POWER),
            SensorRef("sensor.pump_current", SensorRole.CURRENT),
        ),
    )

    assert sensor_description_applies(
        descriptions["capacity_usage"], heater, coordinator
    )
    assert sensor_description_applies(
        descriptions["metric_consistency_score"], pump, coordinator
    )
    assert _setup_health_needs_capacity_settings(
        SimpleNamespace(
            _mains_voltage_entity_ids=frozenset({"sensor.panel_voltage"}),
            store_data=FeatureStoreData(),
        ),
        heater,
    )


def test_utility_comparison_sensors_merge_config_sources_per_circuit() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        sensor_description_applies,
    )

    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(
            SensorRef("sensor.mains_power", SensorRole.REAL_POWER),
            SensorRef("sensor.mains_energy", SensorRole.ENERGY),
        ),
    )
    coordinator = SimpleNamespace(
        options={
            CONF_UTILITY_COMPARISON_SETTINGS: {
                "garage": {"utility_energy_entity": "sensor.garage_utility_kwh"},
            },
        },
        entry_data={
            CONF_UTILITY_COMPARISON_SETTINGS: {
                "mains": {"utility_energy_entity": "sensor.utility_kwh"},
            },
        },
        store_data=FeatureStoreData(),
    )

    assert sensor_description_applies(
        descriptions["utility_comparison_status"],
        mains,
        coordinator,
    )


def test_settings_suggestions_sensor_has_translation_entry() -> None:
    strings = json.loads(
        (DOMAIN_PATH / "translations" / "en.json").read_text(encoding="utf-8"),
    )

    assert strings["entity"]["sensor"]["settings_suggestions"] == {
        "name": "Settings suggestions"
    }


def test_settings_suggestions_attributes_are_bounded_and_slim() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        settings_suggestions_attributes,
    )

    recommendations = [
        {
            "recommendation_id": f"fridge:setting_{index}:v1",
            "setting_key": f"setting_{index}",
            "setting_label": f"Setting {index}",
            "current_value": index,
            "suggested_value": index + 1,
            "reason": "Retained evidence suggests an adjustment.",
            "evidence": {"large": list(range(50))},
            "apply_payload": {f"setting_{index}": index + 1},
        }
        for index in range(8)
    ]
    state = AnalyzerState(
        settings_recommendation_count_by_circuit={"fridge": len(recommendations)},
        settings_recommendations_by_circuit={"fridge": recommendations},
    )

    attrs = settings_suggestions_attributes(state, "fridge")

    assert attrs["pending_count"] == 8
    assert attrs["shown_count"] == 5
    assert attrs["has_more"] is True
    assert len(attrs["recommendations"]) == 5
    assert attrs["recommendations"][0] == {
        "recommendation_id": "fridge:setting_0:v1",
        "setting_key": "setting_0",
        "setting_label": "Setting 0",
        "current_value": 0,
        "suggested_value": 1,
    }
    assert "evidence" not in attrs["recommendations"][0]
    assert "apply_payload" not in attrs["recommendations"][0]


def test_settings_suggestions_helpers_are_feature_module_exports() -> None:
    from custom_components.circuitsetup_energy_analyzer.entities import (
        settings_suggestions as feature_module,
    )
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        settings_suggestions_attributes as sensor_attributes,
    )
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        settings_suggestions_value as sensor_value,
    )

    assert feature_module.settings_suggestions_value is sensor_value
    assert feature_module.settings_suggestions_attributes is sensor_attributes


def test_setup_health_helpers_are_feature_module_exports() -> None:
    from custom_components.circuitsetup_energy_analyzer.entities import (
        setup_health as feature_module,
    )
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_attributes as sensor_attributes,
    )
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        setup_health_value as sensor_value,
    )

    assert feature_module.setup_health_value is sensor_value
    assert feature_module.setup_health_attributes is sensor_attributes


def test_energy_helpers_are_feature_module_exports() -> None:
    from custom_components.circuitsetup_energy_analyzer.entities import (
        energy as feature_module,
    )
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        daily_energy_usage_value,
        energy_goal_status_value,
        energy_goal_usage_value,
        energy_usage_share_value,
        energy_usage_status_value,
    )

    assert feature_module.daily_energy_usage_value is daily_energy_usage_value
    assert feature_module.energy_usage_share_value is energy_usage_share_value
    assert feature_module.energy_usage_status_value is energy_usage_status_value
    assert feature_module.energy_goal_usage_value is energy_goal_usage_value
    assert feature_module.energy_goal_status_value is energy_goal_status_value


def test_nilm_helpers_are_feature_module_exports() -> None:
    from custom_components.circuitsetup_energy_analyzer.entities import (
        nilm as feature_module,
    )
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        nilm_signature_count_value,
        nilm_topology_status_value,
        nilm_unknown_loads_attributes,
        nilm_unknown_loads_value,
        nilm_unmatched_load_percentage_value,
    )

    assert feature_module.nilm_signature_count_value is nilm_signature_count_value
    assert (
        feature_module.nilm_unmatched_load_percentage_value
        is nilm_unmatched_load_percentage_value
    )
    assert feature_module.nilm_topology_status_value is nilm_topology_status_value
    assert feature_module.nilm_unknown_loads_value is nilm_unknown_loads_value
    assert feature_module.nilm_unknown_loads_attributes is nilm_unknown_loads_attributes


def test_status_sensor_entities_explain_machine_status_values() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        CircuitAnalyzerSensor,
    )

    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    state = AnalyzerState(
        active_alerts_by_circuit={
            "pool": [SimpleNamespace(feature="solar_flow")],
        },
        learning_by_circuit={"pool": False},
        solar_flow_status_by_circuit={"pool": "inconsistent_export"},
    )
    coordinator = SimpleNamespace(data=state)
    circuit = SimpleNamespace(
        circuit_id="pool",
        name="Pool Pump",
        appliance_profile="pool_pump",
    )

    solar_status = CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["solar_flow_status"],
    )
    assert solar_status.native_value == "Inconsistent Export"
    assert solar_status.extra_state_attributes["alert_confirmed"] is True
    assert solar_status.extra_state_attributes["learning"] is False
    assert solar_status.extra_state_attributes["raw_status"] == "inconsistent_export"
    assert "CT orientation" in solar_status.extra_state_attributes["status_explanation"]


def test_energy_usage_sensors_explain_waiting_for_delta() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        CircuitAnalyzerSensor,
    )

    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    circuit = SimpleNamespace(circuit_id="hvac", name="HVAC", appliance_profile="hvac")
    coordinator = SimpleNamespace(
        data=AnalyzerState(
            energy_usage_evidence_by_circuit={
                "hvac": {
                    "status": "waiting_for_delta",
                    "status_label": "Waiting For Energy Change",
                    "raw_status": "waiting_for_delta",
                    "status_explanation": (
                        "A cumulative kWh source is present, but the analyzer has "
                        "not observed it increase since tracking started."
                    ),
                    "suggested_next_check": (
                        "Let the analyzer see the energy sensor increase, or "
                        "confirm the circuit has a cumulative kWh source."
                    ),
                }
            },
            daily_energy_usage_by_circuit={"hvac": 0.0},
        )
    )

    attrs = CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["daily_energy_usage"],
    ).extra_state_attributes

    assert attrs["status_label"] == "Waiting For Energy Change"
    assert attrs["raw_status"] == "waiting_for_delta"
    assert "cumulative kWh" in attrs["status_explanation"]
    assert "energy sensor increase" in attrs["suggested_next_check"]


def test_energy_summary_explains_automatic_kwh_helper_startup() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        energy_summary_attributes,
        energy_summary_value,
    )

    state = AnalyzerState(
        energy_usage_evidence_by_circuit={
            "fridge": {
                "status": "waiting_for_delta",
                "energy_source": "derived_from_power",
            }
        }
    )

    assert energy_summary_value(state, "fridge") == "Learning"
    assert (
        "automatic kWh helper"
        in energy_summary_attributes(state, "fridge")["summary_explanation"]
    )


def test_energy_learning_keeps_shared_learning_state_active() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        is_learning,
    )
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        energy_summary_attributes,
    )

    state = AnalyzerState(
        learning_by_circuit={"hvac": False},
        energy_usage_evidence_by_circuit={
            "hvac": {"status": "learning"},
        },
    )

    assert is_learning(state, "hvac") is True
    assert energy_summary_attributes(state, "hvac")["learning"] is True


def test_binary_sensor_descriptions_include_home_assistant_entity_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        BINARY_SENSOR_DESCRIPTIONS,
    )
    from custom_components.circuitsetup_energy_analyzer.entity import EntityTier

    required_attrs = {
        "device_class",
        "entity_category",
        "entity_registry_enabled_default",
        "entity_registry_visible_default",
        "entity_picture",
        "entity_tier",
        "force_update",
        "has_entity_name",
        "icon",
        "name",
        "translation_key",
        "translation_placeholders",
        "unit_of_measurement",
    }

    for description in BINARY_SENSOR_DESCRIPTIONS:
        missing_attrs = sorted(
            attr for attr in required_attrs if not hasattr(description, attr)
        )
        assert missing_attrs == []
        if description.entity_tier is EntityTier.SUMMARY:
            assert description.entity_registry_enabled_default is True
        else:
            assert description.entity_registry_enabled_default is False
        assert description.unit_of_measurement is None

    descriptions = {
        description.key: description for description in BINARY_SENSOR_DESCRIPTIONS
    }
    assert descriptions["learning"].entity_registry_visible_default is False
    assert descriptions["learning"].entity_registry_enabled_default is False
    assert descriptions["learning"].entity_tier is EntityTier.DIAGNOSTIC
    assert descriptions["data_quality_problem"].entity_registry_visible_default is False
    assert descriptions["data_quality_problem"].entity_registry_enabled_default is False
    assert descriptions["data_quality_problem"].entity_tier is EntityTier.DIAGNOSTIC
    assert descriptions["maintenance"].entity_registry_visible_default is False
    assert descriptions["maintenance"].entity_registry_enabled_default is False
    assert descriptions["maintenance"].entity_tier is EntityTier.DIAGNOSTIC
    assert "running" not in descriptions
    assert descriptions["water_flow_mismatch"].entity_tier is EntityTier.FEATURE
    assert descriptions["water_flow_mismatch"].entity_registry_enabled_default is False


def test_binary_sensor_entities_use_purpose_specific_icons() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        BINARY_SENSOR_DESCRIPTIONS,
        CircuitAnalyzerBinarySensor,
    )

    descriptions = {
        description.key: description for description in BINARY_SENSOR_DESCRIPTIONS
    }
    coordinator = SimpleNamespace(data=AnalyzerState())
    circuit = SimpleNamespace(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile="refrigerator",
    )

    expected_icons = {
        "learning": "mdi:school-outline",
        "data_quality_problem": "mdi:database-alert-outline",
        "maintenance": "mdi:bell-pause-outline",
    }

    for key, icon in expected_icons.items():
        entity = CircuitAnalyzerBinarySensor(
            coordinator,
            entry_id="entry-1",
            circuit=circuit,
            description=descriptions[key],
        )
        assert entity.icon == icon
        assert entity.icon != "mdi:eye"


@pytest.mark.asyncio
async def test_sensor_setup_entry_adds_diagnostic_entities_without_ha() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
    )
    coordinator = SimpleNamespace(
        data=AnalyzerState(
            energy_dashboard_status_by_circuit={"fridge": "needs_energy_source"},
        ),
        circuit_configs=(circuit,),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    assert [entity.unique_id for entity in added_entities] == [
        "entry-1_setup_health",
        "entry-1_electricity_rate",
        "entry-1_fridge_health_summary",
        "entry-1_fridge_activity_summary",
        "entry-1_fridge_energy_summary",
        "entry-1_fridge_daily_energy_usage",
        "entry-1_fridge_average_kwh_per_day",
    ]
    setup_health = added_entities[0]
    assert setup_health.name == "CircuitSetup Energy Analyzer Setup Health"
    assert setup_health.suggested_object_id == (
        "circuitsetup_energy_analyzer_setup_health"
    )
    assert setup_health.native_value == "Ready"
    assert setup_health.extra_state_attributes["blocking_issue_count"] == 0
    assert setup_health.extra_state_attributes["next_step"] == "No setup action needed"
    assert getattr(setup_health, "device_info", None) is None
    effective_rate = added_entities[1]
    assert effective_rate.name == "CircuitSetup Energy Analyzer Electricity Rate"
    assert effective_rate.native_value == 0.0
    assert effective_rate.device_info["identifiers"] == {(DOMAIN, "entry-1")}
    assert added_entities[2].device_info["identifiers"] == {(DOMAIN, "entry-1_fridge")}
    assert not isinstance(added_entities[2].state, AnalyzerState)
    assert added_entities[2].coordinator_state is coordinator.data


@pytest.mark.asyncio
async def test_nilm_virtual_entities_are_opt_in_and_estimated() -> None:
    from custom_components.circuitsetup_energy_analyzer import binary_sensor, sensor
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge

    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    assignment = {
        "assignment_id": "assignment-dishwasher",
        "appliance_id": "dishwasher",
        "display_name": "Dishwasher",
        "appliance_profile": "dishwasher",
        "mains_circuit_id": "mains",
        "signature_fingerprints": ["signature_1"],
        "session_ids": [],
        "label_interval_ids": [],
        "lifecycle_state": "published",
        "confidence": 0.92,
        "created_device": True,
        "publish_entities": True,
    }
    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        circuit_configs=(mains,),
        entry_data={},
        options={},
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mains": [assignment]},
        ),
        _nilm_unmatched_edges={
            "mains": [
                NilmEdge(
                    timestamp=datetime(2026, 6, 6, 8, 0, tzinfo=UTC),
                    delta_w=820.0,
                    delta_var=120.0,
                    delta_va=830.0,
                    delta_pf=-0.05,
                    direction="on",
                ),
                NilmEdge(
                    timestamp=datetime(2026, 6, 6, 9, 0, tzinfo=UTC),
                    delta_w=-815.0,
                    delta_var=-118.0,
                    delta_va=-825.0,
                    delta_pf=0.04,
                    direction="off",
                ),
            ]
        },
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    sensors = []
    binary_sensors = []

    await sensor.async_setup_entry(hass, entry, sensors.extend)
    await binary_sensor.async_setup_entry(hass, entry, binary_sensors.extend)

    sensor_by_id = {entity.unique_id: entity for entity in sensors}
    binary_by_id = {entity.unique_id: entity for entity in binary_sensors}
    assert {
        "entry-1_nilm_assignment-dishwasher_health_summary",
        "entry-1_nilm_assignment-dishwasher_activity_summary",
        "entry-1_nilm_assignment-dishwasher_energy_summary",
        "entry-1_nilm_assignment-dishwasher_estimated_power",
        "entry-1_nilm_assignment-dishwasher_estimated_daily_energy",
    } <= set(sensor_by_id)
    assert {
        unique_id
        for unique_id in sensor_by_id
        if unique_id.startswith("entry-1_nilm_assignment-dishwasher_")
    } == {
        "entry-1_nilm_assignment-dishwasher_health_summary",
        "entry-1_nilm_assignment-dishwasher_activity_summary",
        "entry-1_nilm_assignment-dishwasher_energy_summary",
        "entry-1_nilm_assignment-dishwasher_estimated_power",
        "entry-1_nilm_assignment-dishwasher_estimated_daily_energy",
    }
    assert {
        unique_id
        for unique_id in binary_by_id
        if unique_id.startswith("entry-1_nilm_assignment-dishwasher_")
    } == {"entry-1_nilm_assignment-dishwasher_estimated_running"}

    estimated_power = sensor_by_id["entry-1_nilm_assignment-dishwasher_estimated_power"]
    estimated_daily_energy = sensor_by_id[
        "entry-1_nilm_assignment-dishwasher_estimated_daily_energy"
    ]
    running = binary_by_id["entry-1_nilm_assignment-dishwasher_estimated_running"]
    assert estimated_power.native_value is None
    assert estimated_daily_energy.native_value == 0.818
    assert running.is_on is None
    assert estimated_power.extra_state_attributes == {
        "estimated": True,
        "source": "nilm",
        "source_type": "nilm_estimate",
        "appliance_key": "nilm:assignment-dishwasher",
        "assignment_id": "assignment-dishwasher",
        "appliance_id": "dishwasher",
        "appliance_profile": "dishwasher",
        "mains_circuit_id": "mains",
        "mains_source": "sensor.mains_power",
        "confidence": 0.92,
        "model_status": "published",
        "last_validation": None,
    }
    assert running.extra_state_attributes["estimated"] is True
    assert estimated_power.device_info == {
        "identifiers": {(DOMAIN, "entry-1_nilm_assignment-dishwasher")},
        "name": "Dishwasher",
            "manufacturer": "CircuitSetup",
            "model": "NILM Estimated Appliance",
            "suggested_area": "Kitchen",
            "via_device": (DOMAIN, "entry-1_mains"),
        }
    assert "icon" not in estimated_power.device_info
    assert "entry-1_dishwasher_active_power" not in sensor_by_id
    assert "entry-1_dishwasher_running" not in binary_by_id

    coordinator._nilm_unmatched_edges["mains"].append(
        NilmEdge(
            timestamp=datetime(2026, 6, 6, 10, 0, tzinfo=UTC),
            delta_w=900.0,
            delta_var=125.0,
            delta_va=910.0,
            delta_pf=-0.04,
            direction="on",
        ),
    )

    assert estimated_power.native_value is None
    assert running.is_on is None


def test_nilm_virtual_device_info_inherits_real_appliance_area_metadata() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm_virtual import (
        NilmVirtualApplianceState,
        nilm_virtual_device_info,
    )

    state = NilmVirtualApplianceState(
        appliance_id="washer",
        assignment_id="assignment-washer",
        display_name="Washer",
        is_running=False,
        estimated_power_w=0.0,
        estimated_energy_kwh_today=0.0,
        confidence=0.91,
        last_seen=None,
        active_signature_id=None,
        active_session_id=None,
        latest_session_id=None,
        model_status="published",
        mains_circuit_id="mains",
        mains_source="sensor.mains_power",
        appliance_profile="washer",
        last_validation="2026-06-06T08:00:00+00:00",
    )

    device_info = nilm_virtual_device_info("entry-1", state)

    assert device_info == {
        "identifiers": {(DOMAIN, "entry-1_nilm_assignment-washer")},
        "name": "Washer",
        "manufacturer": "CircuitSetup",
        "model": "NILM Estimated Appliance",
        "via_device": (DOMAIN, "entry-1_mains"),
        "suggested_area": "Laundry",
    }


def test_nilm_virtual_states_filter_sessions_by_assignment_signature() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.nilm_virtual import (
        nilm_virtual_appliance_states,
    )

    coordinator = SimpleNamespace(
        circuit_configs=(),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mains": [
                    {
                        "signature_id": "signature-dishwasher",
                        "median_delta_w": 820.0,
                        "split_phase_type": "single_leg",
                    },
                    {
                        "signature_id": "signature-washer",
                        "median_delta_w": 420.0,
                        "split_phase_type": "single_leg",
                    },
                ]
            },
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-dishwasher",
                        "display_name": "Dishwasher",
                        "signature_fingerprints": ["signature-dishwasher"],
                    },
                    {
                        "assignment_id": "assignment-washer",
                        "display_name": "Washer",
                        "signature_fingerprints": ["signature-washer"],
                    },
                ]
            },
        ),
        _nilm_unmatched_edges={
            "mains": [
                NilmEdge(
                    timestamp=datetime(2026, 6, 6, 8, 0, tzinfo=UTC),
                    delta_w=420.0,
                    delta_var=80.0,
                    delta_va=430.0,
                    delta_pf=-0.04,
                    direction="on",
                    split_phase_type="single_leg",
                ),
            ]
        },
    )

    states = {
        state.assignment_id: state
        for state in nilm_virtual_appliance_states(coordinator)
    }

    assert states["assignment-dishwasher"].is_running is None
    assert states["assignment-washer"].is_running is None


def test_nilm_virtual_live_values_require_consistent_component_runtime() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm_virtual import (
        nilm_virtual_appliance_states,
    )

    assignment = {
        "assignment_id": "assignment-washer",
        "display_name": "Washer",
        "mains_circuit_id": "mains",
        "lifecycle_state": "published",
        "publish_entities": True,
        "confidence": 0.9,
    }
    state = AnalyzerState()
    coordinator = SimpleNamespace(
        data=state,
        circuit_configs=(),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mains": [assignment]},
            nilm_session_history_by_circuit={
                "mains": [{
                    "assignment_id": "assignment-washer",
                    "session_id": "persisted-open",
                    "start": "2026-08-02T12:00:00+00:00",
                    "end": None,
                    "median_power_w": 500.0,
                }]
            },
        ),
    )

    restored = nilm_virtual_appliance_states(coordinator)[0]
    assert restored.is_running is None
    assert restored.estimated_power_w is None

    state.nilm_component_runtime_by_circuit["mains"] = {
        "assignment-washer": {
            "status": "on",
            "estimated_power_w": 510.0,
            "energy_kwh": 0.125,
            "consistent": True,
            "session_id": "live",
            "session_start": "2026-08-02T13:00:00+00:00",
        }
    }
    state.nilm_reconciliation_by_circuit["mains"] = {
        "consistent": True,
        "conflict": None,
    }
    live = nilm_virtual_appliance_states(coordinator)[0]
    assert live.is_running is True
    assert live.estimated_power_w == 510.0
    assert live.estimated_energy_kwh_today == 0.125

    state.nilm_reconciliation_by_circuit["mains"]["conflict"] = "over_allocation"
    conflicted = nilm_virtual_appliance_states(coordinator)[0]
    assert conflicted.is_running is None
    assert conflicted.estimated_power_w is None
    assert conflicted.model_status == "conflict"


@pytest.mark.parametrize("hidden_state", ["ignored", "expected"])
def test_nilm_virtual_states_assign_overlapping_signatures_once(
    hidden_state: str,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.nilm_virtual import (
        nilm_virtual_appliance_states,
    )

    coordinator = SimpleNamespace(
        circuit_configs=(),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mains": [
                    {"signature_id": "120-w", "typical_watts": 120.0},
                    {"signature_id": "187-w", "typical_watts": 187.0},
                    {"signature_id": "hidden-120-w", "typical_watts": 120.0},
                ]
            },
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-120",
                        "display_name": "120 W appliance",
                        "signature_fingerprints": ["120-w"],
                    },
                    {
                        "assignment_id": "assignment-187",
                        "display_name": "187 W appliance",
                        "signature_fingerprints": ["187-w"],
                    },
                    {
                        "assignment_id": "hidden-120",
                        "display_name": "Hidden 120 W appliance",
                        "signature_fingerprints": ["hidden-120-w"],
                        "lifecycle_state": hidden_state,
                    },
                ]
            },
        ),
        _nilm_unmatched_edges={
            "mains": [
                NilmEdge(
                    datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
                    140.0,
                    0.0,
                    140.0,
                    0.0,
                    "on",
                )
            ]
        },
    )

    states = nilm_virtual_appliance_states(coordinator)

    assert all(state.is_running is None for state in states)


def test_published_nilm_virtual_state_ignores_retired_assignment() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.nilm_virtual import (
        published_nilm_virtual_appliance_states,
    )

    coordinator = SimpleNamespace(
        circuit_configs=(),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mains": [
                    {"signature_id": "published-500", "typical_watts": 500.0},
                    {"signature_id": "retired-500", "typical_watts": 500.0},
                ]
            },
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "published",
                        "signature_fingerprints": ["published-500"],
                        "publish_entities": True,
                        "lifecycle_state": "published",
                    },
                    {
                        "assignment_id": "retired",
                        "signature_fingerprints": ["retired-500"],
                        "publish_entities": True,
                        "lifecycle_state": "retired",
                    },
                ]
            },
        ),
        _nilm_unmatched_edges={
            "mains": [
                NilmEdge(
                    datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
                    500.0,
                    0.0,
                    500.0,
                    0.0,
                    "on",
                )
            ]
        },
    )

    states = published_nilm_virtual_appliance_states(coordinator)

    assert len(states) == 1
    assert states[0].assignment_id == "published"
    assert states[0].is_running is None


@pytest.mark.asyncio
async def test_nilm_virtual_entities_skip_unpublished_and_retired_assignments() -> None:
    from custom_components.circuitsetup_energy_analyzer import binary_sensor, sensor

    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        circuit_configs=(mains,),
        entry_data={},
        options={},
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "assignment-unpublished",
                        "display_name": "Unpublished",
                        "mains_circuit_id": "mains",
                        "publish_entities": False,
                        "lifecycle_state": "validated",
                    },
                    {
                        "assignment_id": "assignment-retired",
                        "display_name": "Retired",
                        "mains_circuit_id": "mains",
                        "publish_entities": True,
                        "lifecycle_state": "retired",
                    },
                ]
            },
        ),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await sensor.async_setup_entry(hass, entry, added_entities.extend)
    await binary_sensor.async_setup_entry(hass, entry, added_entities.extend)

    assert not any(
        entity.unique_id.startswith("entry-1_nilm_") for entity in added_entities
    )


@pytest.mark.asyncio
async def test_nilm_virtual_publish_flags_control_entity_setup() -> None:
    from custom_components.circuitsetup_energy_analyzer import binary_sensor, sensor

    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    assignment = {
        "assignment_id": "assignment-washer",
        "display_name": "Washer",
        "mains_circuit_id": "mains",
        "publish_entities": False,
        "lifecycle_state": "validated",
    }
    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        circuit_configs=(mains,),
        entry_data={},
        options={},
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mains": [assignment]},
        ),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})

    async def nilm_unique_ids() -> set[str]:
        added_entities = []
        await sensor.async_setup_entry(hass, entry, added_entities.extend)
        await binary_sensor.async_setup_entry(hass, entry, added_entities.extend)
        return {
            entity.unique_id
            for entity in added_entities
            if entity.unique_id.startswith("entry-1_nilm_")
        }

    assert await nilm_unique_ids() == set()

    assignment["publish_entities"] = True
    assignment["lifecycle_state"] = "published"
    assert {
        "entry-1_nilm_assignment-washer_health_summary",
        "entry-1_nilm_assignment-washer_estimated_power",
        "entry-1_nilm_assignment-washer_estimated_running",
    } <= await nilm_unique_ids()

    assignment["publish_entities"] = False
    assignment["lifecycle_state"] = "validated"
    assert await nilm_unique_ids() == set()

    assignment["publish_entities"] = True
    assignment["lifecycle_state"] = "retired"
    assert await nilm_unique_ids() == set()


@pytest.mark.asyncio
async def test_sensor_setup_entry_omits_non_current_sensors() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.fridge_energy", SensorRole.ENERGY),),
    )
    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        circuit_configs=(circuit,),
        entry_data={},
        options={},
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert {
        "entry-1_fridge_health_summary",
        "entry-1_fridge_activity_summary",
        "entry-1_fridge_energy_summary",
    } <= unique_ids
    assert {
        "entry-1_fridge_sensitivity",
        "entry-1_fridge_readiness",
        "entry-1_fridge_learning_progress",
        "entry-1_fridge_data_quality_checklist",
        "entry-1_fridge_alert_evidence",
        "entry-1_fridge_last_event",
        "entry-1_fridge_recent_activity_count",
    }.isdisjoint(unique_ids)


@pytest.mark.asyncio
async def test_sensor_setup_entry_adds_high_power_entities_only() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(
            SensorRef("sensor.hvac_power_l1", SensorRole.REAL_POWER, leg="a"),
            SensorRef("sensor.hvac_power_l2", SensorRole.REAL_POWER, leg="b"),
            SensorRef("sensor.hvac_current", SensorRole.CURRENT),
            SensorRef("sensor.hvac_voltage", SensorRole.VOLTAGE),
            SensorRef("sensor.hvac_reactive", SensorRole.REACTIVE_POWER),
            SensorRef("sensor.hvac_apparent", SensorRole.APPARENT_POWER),
            SensorRef("sensor.hvac_pf", SensorRole.POWER_FACTOR),
        ),
    )
    coordinator = _use_entity_detail(
        SimpleNamespace(
            data=AnalyzerState(),
            circuit_configs=(circuit,),
            store_data=FeatureStoreData(
                capacity_settings_by_circuit={"hvac": {"breaker_amps": 40.0}},
            ),
        ),
        ENTITY_DETAIL_EXPERT,
        ("demand_capacity",),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert {
        "entry-1_hvac_activity_summary",
        "entry-1_hvac_current_demand",
        "entry-1_hvac_capacity_usage",
        "entry-1_hvac_leg_imbalance",
    } <= unique_ids
    assert (
        not {
            "entry-1_hvac_nilm_signature_count",
            "entry-1_hvac_balance_power",
            "entry-1_hvac_solar_generation_power",
            "entry-1_hvac_utility_comparison_difference",
            "entry-1_hvac_billing_cycle_usage",
            "entry-1_hvac_cost_cycle",
            "entry-1_hvac_power_quality_score",
            "entry-1_hvac_power_quality_evidence",
            "entry-1_hvac_reactive_power_drift",
            "entry-1_hvac_apparent_power_drift",
            "entry-1_hvac_power_factor_drift",
            "entry-1_hvac_metric_consistency_score",
            "entry-1_hvac_metric_consistency_status",
            "entry-1_hvac_leg_imbalance_status",
            "entry-1_hvac_run_cycle_count",
            "entry-1_hvac_run_cycle_runtime",
            "entry-1_hvac_run_cycle_duty_cycle",
            "entry-1_hvac_run_cycle_status",
        }
        & unique_ids
    )


@pytest.mark.asyncio
async def test_sensor_setup_entry_adds_selected_cycle_and_electrical_graph_groups() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.entity_catalog import (
        EntityGroup,
    )
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(
            SensorRef("sensor.hvac_power_l1", SensorRole.REAL_POWER, leg="a"),
            SensorRef("sensor.hvac_power_l2", SensorRole.REAL_POWER, leg="b"),
            SensorRef("sensor.hvac_current", SensorRole.CURRENT),
            SensorRef("sensor.hvac_voltage", SensorRole.VOLTAGE),
            SensorRef("sensor.hvac_reactive", SensorRole.REACTIVE_POWER),
            SensorRef("sensor.hvac_apparent", SensorRole.APPARENT_POWER),
            SensorRef("sensor.hvac_pf", SensorRole.POWER_FACTOR),
        ),
    )
    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        circuit_configs=(circuit,),
        options={
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_EXPERT,
            CONF_SELECTED_ENTITY_GROUPS: [
                EntityGroup.CYCLE_METRICS.value,
                EntityGroup.ELECTRICAL_SCORES.value,
                EntityGroup.POWER_QUALITY_DRIFT.value,
            ],
        },
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert {
        "entry-1_hvac_run_cycle_count",
        "entry-1_hvac_run_cycle_runtime",
        "entry-1_hvac_run_cycle_duty_cycle",
        "entry-1_hvac_power_quality_score",
        "entry-1_hvac_metric_consistency_score",
        "entry-1_hvac_reactive_power_drift",
        "entry-1_hvac_apparent_power_drift",
        "entry-1_hvac_power_factor_drift",
    } <= unique_ids
    assert {
        "entry-1_hvac_activity_summary",
        "entry-1_hvac_leg_imbalance",
    } <= unique_ids
    assert (
        not {
            "entry-1_hvac_run_cycle_status",
            "entry-1_hvac_power_quality_evidence",
            "entry-1_hvac_metric_consistency_status",
            "entry-1_hvac_leg_imbalance_status",
        }
        & unique_ids
    )


@pytest.mark.asyncio
async def test_sensor_setup_entry_condenses_billing_standby_and_weather_entities() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
        billing_cycle_budget_kwh=400.0,
        standby_threshold_w=12.0,
        sensors=(
            SensorRef("sensor.hvac_power_l1", SensorRole.REAL_POWER, leg="a"),
            SensorRef("sensor.hvac_power_l2", SensorRole.REAL_POWER, leg="b"),
            SensorRef("sensor.hvac_energy", SensorRole.ENERGY),
        ),
    )
    coordinator = _use_entity_detail(
        SimpleNamespace(
            data=AnalyzerState(),
            circuit_configs=(circuit,),
            store_data=FeatureStoreData(
                cost_settings_by_circuit={
                    "__global__": {"default_rate_per_kwh": 0.15},
                },
            ),
            options={CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.backyard_temperature"},
        ),
        ENTITY_DETAIL_STANDARD,
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert {
        "entry-1_hvac_billing_cycle_usage",
        "entry-1_hvac_cost_cycle",
        "entry-1_hvac_always_on_power",
        "entry-1_hvac_leg_imbalance",
        "entry-1_hvac_weather_context",
    } <= unique_ids
    leg_imbalance = next(
        entity
        for entity in added_entities
        if entity.unique_id == "entry-1_hvac_leg_imbalance"
    )
    assert leg_imbalance._attr_entity_registry_enabled_default is True
    assert (
        not {
            "entry-1_hvac_electrical_health",
            "entry-1_hvac_standby_status",
            "entry-1_hvac_billing_cycle_forecast",
            "entry-1_hvac_billing_cycle_budget_usage",
            "entry-1_hvac_billing_cycle_status",
            "entry-1_hvac_cost_current_rate",
            "entry-1_hvac_cost_cycle_forecast",
            "entry-1_hvac_cost_status",
            "entry-1_hvac_standby_threshold",
            "entry-1_hvac_outdoor_temperature",
        }
        & unique_ids
    )


@pytest.mark.asyncio
async def test_sensor_setup_entry_adds_selected_billing_forecast_group_only() -> None:
    from custom_components.circuitsetup_energy_analyzer.entity_catalog import (
        EntityGroup,
    )
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
        billing_cycle_budget_kwh=400.0,
        standby_threshold_w=12.0,
        sensors=(
            SensorRef("sensor.hvac_power_l1", SensorRole.REAL_POWER, leg="a"),
            SensorRef("sensor.hvac_power_l2", SensorRole.REAL_POWER, leg="b"),
            SensorRef("sensor.hvac_energy", SensorRole.ENERGY),
        ),
    )
    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        circuit_configs=(circuit,),
        store_data=FeatureStoreData(
            cost_settings_by_circuit={
                "__global__": {"default_rate_per_kwh": 0.15},
            },
        ),
        options={
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_EXPERT,
            CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.backyard_temperature",
            CONF_SELECTED_ENTITY_GROUPS: [EntityGroup.BILLING_FORECASTS.value],
        },
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert {
        "entry-1_hvac_billing_cycle_usage",
        "entry-1_hvac_cost_cycle",
        "entry-1_hvac_billing_cycle_forecast",
        "entry-1_hvac_cost_cycle_forecast",
    } <= unique_ids
    assert (
        not {
            "entry-1_hvac_billing_cycle_budget_usage",
            "entry-1_hvac_billing_cycle_status",
            "entry-1_hvac_cost_current_rate",
            "entry-1_hvac_cost_status",
            "entry-1_hvac_standby_threshold",
            "entry-1_hvac_outdoor_temperature",
        }
        & unique_ids
    )


@pytest.mark.asyncio
async def test_sensor_setup_entry_adds_car_charger_specific_diagnostics() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="car_charger",
        name="Car Charger",
        appliance_profile=ApplianceProfile.EV_CHARGER,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(
            SensorRef("sensor.car_charger_l1_power", SensorRole.REAL_POWER, leg="a"),
            SensorRef("sensor.car_charger_l2_power", SensorRole.REAL_POWER, leg="b"),
            SensorRef("sensor.car_charger_l1_current", SensorRole.CURRENT, leg="a"),
            SensorRef("sensor.car_charger_l2_current", SensorRole.CURRENT, leg="b"),
            SensorRef("sensor.mains_l1_voltage", SensorRole.VOLTAGE, leg="a"),
            SensorRef("sensor.mains_l2_voltage", SensorRole.VOLTAGE, leg="b"),
            SensorRef("sensor.car_charger_apparent", SensorRole.APPARENT_POWER),
            SensorRef("sensor.car_charger_pf", SensorRole.POWER_FACTOR),
            SensorRef("sensor.car_charger_energy", SensorRole.ENERGY),
        ),
    )
    coordinator = _use_entity_detail(
        SimpleNamespace(
            data=AnalyzerState(),
            circuit_configs=(circuit,),
            store_data=FeatureStoreData(
                capacity_settings_by_circuit={
                    "car_charger": {"breaker_amps": 40.0, "warning_ratio": 0.8}
                },
            ),
        ),
        ENTITY_DETAIL_EXPERT,
        ("demand_capacity",),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert {
        "entry-1_car_charger_current_demand",
        "entry-1_car_charger_demand_peak_status",
        "entry-1_car_charger_capacity_usage",
        "entry-1_car_charger_leg_imbalance",
        "entry-1_car_charger_daily_energy_usage",
    } <= unique_ids
    assert (
        not {
            "entry-1_car_charger_run_cycle_count",
            "entry-1_car_charger_run_cycle_status",
            "entry-1_car_charger_leg_imbalance_status",
            "entry-1_car_charger_metric_consistency_score",
            "entry-1_car_charger_metric_consistency_status",
            "entry-1_car_charger_power_factor_drift",
            "entry-1_car_charger_standby_status",
            "entry-1_car_charger_nilm_signature_count",
            "entry-1_car_charger_balance_power",
        }
        & unique_ids
    )


@pytest.mark.asyncio
async def test_sensor_setup_entry_adds_single_phase_metric_consistency() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="pool_pump",
        name="Pool Pump",
        appliance_profile=ApplianceProfile.POOL_PUMP,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(
            SensorRef("sensor.pool_power", SensorRole.REAL_POWER),
            SensorRef("sensor.pool_current", SensorRole.CURRENT),
            SensorRef("sensor.pool_voltage", SensorRole.VOLTAGE),
            SensorRef("sensor.pool_pf", SensorRole.POWER_FACTOR),
        ),
    )
    coordinator = _use_entity_detail(
        SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,)),
        ENTITY_DETAIL_EXPERT,
        ("demand_capacity",),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert {
        "entry-1_pool_pump_health_summary",
        "entry-1_pool_pump_current_demand",
    } <= unique_ids
    assert (
        not {
            "entry-1_pool_pump_metric_consistency_score",
            "entry-1_pool_pump_metric_consistency_status",
            "entry-1_pool_pump_leg_imbalance",
            "entry-1_pool_pump_leg_imbalance_status",
        }
        & unique_ids
    )


@pytest.mark.asyncio
async def test_sensor_setup_entry_does_not_create_leg_imbalance_for_mains_nilm() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(
            SensorRef("sensor.mains_l1_power", SensorRole.REAL_POWER, leg="a"),
            SensorRef("sensor.mains_l2_power", SensorRole.REAL_POWER, leg="b"),
            SensorRef("sensor.mains_l1_current", SensorRole.CURRENT, leg="a"),
            SensorRef("sensor.mains_l2_current", SensorRole.CURRENT, leg="b"),
        ),
    )
    coordinator = _use_entity_detail(
        SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,)),
        ENTITY_DETAIL_EXPERT,
        ("nilm", "mains_solar"),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert {
        "entry-1_mains_nilm_signature_count",
        "entry-1_mains_balance_power",
    } <= unique_ids
    assert (
        not {
            "entry-1_mains_leg_imbalance",
            "entry-1_mains_leg_imbalance_status",
        }
        & unique_ids
    )


@pytest.mark.asyncio
async def test_sensor_setup_entry_uses_entry_data_for_solar_flow_applicability() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    coordinator = _use_entity_detail(
        SimpleNamespace(
            data=AnalyzerState(),
            circuit_configs=(),
            entry_data={},
        ),
        ENTITY_DETAIL_EXPERT,
        ("mains_solar",),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "appliance_profile": "mains_nilm",
                    "mode": "mains_nilm",
                    "sensors": [
                        {"entity_id": "sensor.mains_power", "role": "real_power"}
                    ],
                },
                {
                    "circuit_id": "solar",
                    "name": "Solar",
                    "appliance_profile": "solar_inverter",
                    "mode": "single_phase",
                    "power_flow": "generation",
                    "sensors": [
                        {"entity_id": "sensor.solar_power", "role": "real_power"}
                    ],
                },
            ]
        },
    )
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert {
        "entry-1_mains_solar_flow_status",
        "entry-1_mains_solar_surplus_status",
    } <= unique_ids
    assert "entry-1_mains_solar_load_shift_status" not in unique_ids
    assert "entry-1_solar_solar_flow_status" not in unique_ids


@pytest.mark.asyncio
async def test_sensor_setup_entry_uses_config_for_utility_comparison_and_costs() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(
            SensorRef("sensor.mains_power", SensorRole.REAL_POWER),
            SensorRef("sensor.mains_energy", SensorRole.ENERGY),
        ),
    )
    coordinator = _use_entity_detail(
        SimpleNamespace(
            data=AnalyzerState(),
            circuit_configs=(circuit,),
            store_data=FeatureStoreData(),
            options={
                CONF_UTILITY_COMPARISON_SETTINGS: {
                    "mains": {
                        "utility_energy_entity": "sensor.utility_kwh",
                        "utility_cost_entity": "sensor.utility_cost",
                    }
                }
            },
        ),
        ENTITY_DETAIL_EXPERT,
        ("mains_solar",),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert "entry-1_mains_utility_comparison_status" in unique_ids
    assert "entry-1_mains_cost_today" in unique_ids
    assert "entry-1_mains_average_cost_per_day" in unique_ids
    assert "entry-1_mains_utility_comparison_difference" not in unique_ids


@pytest.mark.asyncio
async def test_sensor_setup_entry_materializes_selected_demo_source_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="cs_energy_analyzer_demo_pool_pump",
        name="Pool Pump",
        appliance_profile=ApplianceProfile.POOL_PUMP,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(
            SensorRef(
                "sensor.cs_energy_analyzer_demo_pool_pump_active_power",
                SensorRole.REAL_POWER,
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_pool_pump_current",
                SensorRole.CURRENT,
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_pool_pump_power_factor",
                SensorRole.POWER_FACTOR,
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_pool_pump_reactive_power",
                SensorRole.REACTIVE_POWER,
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_mains_l1_voltage",
                SensorRole.VOLTAGE,
                leg="a",
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_mains_l2_voltage",
                SensorRole.VOLTAGE,
                leg="b",
            ),
        ),
    )
    coordinator = _use_entity_detail(
        SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,)),
        ENTITY_DETAIL_EXPERT,
        ("nilm", "mains_solar", "demand_capacity"),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    source_entities = [
        entity
        for entity in added_entities
        if getattr(entity, "unique_id", "").startswith("entry-1_demo_source_")
    ]
    assert {entity.unique_id for entity in source_entities} == {
        "entry-1_demo_source_exact_cs_energy_analyzer_demo_pool_pump_active_power",
        "entry-1_demo_source_exact_cs_energy_analyzer_demo_pool_pump_current",
        "entry-1_demo_source_exact_cs_energy_analyzer_demo_pool_pump_power_factor",
        "entry-1_demo_source_exact_cs_energy_analyzer_demo_pool_pump_reactive_power",
        "entry-1_demo_source_exact_cs_energy_analyzer_demo_mains_l1_voltage",
        "entry-1_demo_source_exact_cs_energy_analyzer_demo_mains_l2_voltage",
    }
    assert {entity.entity_id for entity in source_entities} == {
        "sensor.cs_energy_analyzer_demo_pool_pump_active_power",
        "sensor.cs_energy_analyzer_demo_pool_pump_current",
        "sensor.cs_energy_analyzer_demo_pool_pump_power_factor",
        "sensor.cs_energy_analyzer_demo_pool_pump_reactive_power",
        "sensor.cs_energy_analyzer_demo_mains_l1_voltage",
        "sensor.cs_energy_analyzer_demo_mains_l2_voltage",
    }
    by_entity_id = {
        f"sensor.{entity.suggested_object_id}": entity for entity in source_entities
    }
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_pool_pump_active_power"
        ].device_class
        == "power"
    )
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_pool_pump_active_power"
        ].native_unit_of_measurement
        == "W"
    )
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_pool_pump_power_factor"
        ].native_value
        == 0.86
    )
    assert (
        by_entity_id["sensor.cs_energy_analyzer_demo_mains_l1_voltage"].icon
        == "mdi:sine-wave"
    )
    assert (
        by_entity_id["sensor.cs_energy_analyzer_demo_mains_l1_voltage"].native_value
        == 119.6
    )
    assert "sensor.cs_energy_analyzer_demo_pool_pump_voltage" not in by_entity_id
    assert (
        getattr(
            by_entity_id["sensor.cs_energy_analyzer_demo_mains_l1_voltage"],
            "device_info",
            None,
        )
        is None
    )


@pytest.mark.asyncio
async def test_sensor_setup_entry_materializes_demo_laundry_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    washer = CircuitConfig(
        circuit_id="cs_energy_analyzer_demo_washer",
        name="Washer",
        appliance_profile=ApplianceProfile.WASHER,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(
            SensorRef(
                "sensor.cs_energy_analyzer_demo_washer_energy",
                SensorRole.ENERGY,
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_washer_active_power",
                SensorRole.REAL_POWER,
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_washer_current",
                SensorRole.CURRENT,
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_washer_power_factor",
                SensorRole.POWER_FACTOR,
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_washer_reactive_power",
                SensorRole.REACTIVE_POWER,
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_washer_apparent_power",
                SensorRole.APPARENT_POWER,
            ),
        ),
    )
    dryer = CircuitConfig(
        circuit_id="cs_energy_analyzer_demo_dryer",
        name="Dryer",
        appliance_profile=ApplianceProfile.DRYER,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(
            SensorRef(
                "sensor.cs_energy_analyzer_demo_dryer_l1_energy",
                SensorRole.ENERGY,
                leg="a",
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_dryer_l2_energy",
                SensorRole.ENERGY,
                leg="b",
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_dryer_l1_active_power",
                SensorRole.REAL_POWER,
                leg="a",
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_dryer_l2_active_power",
                SensorRole.REAL_POWER,
                leg="b",
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_dryer_l1_current",
                SensorRole.CURRENT,
                leg="a",
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_dryer_l2_current",
                SensorRole.CURRENT,
                leg="b",
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_dryer_l1_power_factor",
                SensorRole.POWER_FACTOR,
                leg="a",
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_dryer_l2_power_factor",
                SensorRole.POWER_FACTOR,
                leg="b",
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_dryer_l1_reactive_power",
                SensorRole.REACTIVE_POWER,
                leg="a",
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_dryer_l2_reactive_power",
                SensorRole.REACTIVE_POWER,
                leg="b",
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_dryer_l1_apparent_power",
                SensorRole.APPARENT_POWER,
                leg="a",
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_dryer_l2_apparent_power",
                SensorRole.APPARENT_POWER,
                leg="b",
            ),
        ),
    )
    coordinator = SimpleNamespace(data=AnalyzerState(), circuit_configs=(washer, dryer))
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    source_entities = [
        entity
        for entity in added_entities
        if getattr(entity, "unique_id", "").startswith("entry-1_demo_source_")
    ]
    assert all(
        entity._attr_entity_registry_visible_default is False
        for entity in source_entities
    )
    by_entity_id = {
        f"sensor.{entity.suggested_object_id}": entity for entity in source_entities
    }

    assert set(by_entity_id) == {
        "sensor.cs_energy_analyzer_demo_washer_energy",
        "sensor.cs_energy_analyzer_demo_washer_active_power",
        "sensor.cs_energy_analyzer_demo_washer_current",
        "sensor.cs_energy_analyzer_demo_washer_power_factor",
        "sensor.cs_energy_analyzer_demo_washer_reactive_power",
        "sensor.cs_energy_analyzer_demo_washer_apparent_power",
        "sensor.cs_energy_analyzer_demo_dryer_l1_energy",
        "sensor.cs_energy_analyzer_demo_dryer_l2_energy",
        "sensor.cs_energy_analyzer_demo_dryer_l1_active_power",
        "sensor.cs_energy_analyzer_demo_dryer_l2_active_power",
        "sensor.cs_energy_analyzer_demo_dryer_l1_current",
        "sensor.cs_energy_analyzer_demo_dryer_l2_current",
        "sensor.cs_energy_analyzer_demo_dryer_l1_power_factor",
        "sensor.cs_energy_analyzer_demo_dryer_l2_power_factor",
        "sensor.cs_energy_analyzer_demo_dryer_l1_reactive_power",
        "sensor.cs_energy_analyzer_demo_dryer_l2_reactive_power",
        "sensor.cs_energy_analyzer_demo_dryer_l1_apparent_power",
        "sensor.cs_energy_analyzer_demo_dryer_l2_apparent_power",
    }
    assert (
        by_entity_id["sensor.cs_energy_analyzer_demo_washer_energy"].native_value
        == 14.2
    )
    assert (
        by_entity_id["sensor.cs_energy_analyzer_demo_washer_active_power"].native_value
        == 420.0
    )
    assert (
        by_entity_id["sensor.cs_energy_analyzer_demo_washer_current"].native_value
        == 4.2
    )
    assert (
        by_entity_id["sensor.cs_energy_analyzer_demo_washer_power_factor"].native_value
        == 0.83
    )
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_washer_reactive_power"
        ].native_value
        == 280.0
    )
    assert (
        by_entity_id["sensor.cs_energy_analyzer_demo_dryer_l1_energy"].native_value
        == 63.7
    )
    assert (
        by_entity_id["sensor.cs_energy_analyzer_demo_dryer_l2_energy"].native_value
        == 63.1
    )
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_dryer_l1_active_power"
        ].native_value
        == 2600.0
    )
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_dryer_l2_active_power"
        ].native_value
        == 2550.0
    )
    assert (
        by_entity_id["sensor.cs_energy_analyzer_demo_dryer_l1_current"].native_value
        == 21.8
    )
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_dryer_l2_power_factor"
        ].native_value
        == 0.99
    )
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_dryer_l2_reactive_power"
        ].native_value
        == 250.0
    )
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_dryer_l1_apparent_power"
        ].native_value
        == 2626.0
    )
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_dryer_l2_apparent_power"
        ].native_value
        == 2576.0
    )


@pytest.mark.asyncio
async def test_sensor_setup_entry_hides_existing_demo_source_entities(
    monkeypatch,
) -> None:
    import sys
    from types import ModuleType

    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    class FakeHider:
        INTEGRATION = "integration"

    class FakeRegistry:
        def __init__(self) -> None:
            self.entities = {
                "sensor.cs_energy_analyzer_demo_washer_active_power": SimpleNamespace(
                    entity_id="sensor.cs_energy_analyzer_demo_washer_active_power",
                    unique_id=(
                        "entry-1_demo_source_exact_"
                        "cs_energy_analyzer_demo_washer_active_power"
                    ),
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    hidden_by=None,
                    entity_category=None,
                ),
                "sensor.washer_health_summary": SimpleNamespace(
                    entity_id="sensor.washer_health_summary",
                    unique_id="entry-1_cs_energy_analyzer_demo_washer_health_summary",
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    hidden_by=None,
                    entity_category=None,
                ),
            }
            self.removed: list[str] = []
            self.updated: list[tuple[str, dict[str, object]]] = []

        def async_remove(self, entity_id) -> None:
            self.removed.append(entity_id)

        def async_update_entity(self, entity_id, **kwargs) -> None:
            self.updated.append((entity_id, kwargs))

    fake_registry = FakeRegistry()
    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    entity_registry_module = ModuleType("homeassistant.helpers.entity_registry")
    entity_registry_module.RegistryEntryHider = FakeHider
    entity_registry_module.async_get = lambda hass: hass.entity_registry
    helpers_module.entity_registry = entity_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry_module,
    )

    circuit = CircuitConfig(
        circuit_id="cs_energy_analyzer_demo_washer",
        name="Washer",
        appliance_profile=ApplianceProfile.WASHER,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(
            SensorRef(
                "sensor.cs_energy_analyzer_demo_washer_active_power",
                SensorRole.REAL_POWER,
            ),
        ),
    )
    coordinator = _use_entity_detail(
        SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,)),
        ENTITY_DETAIL_EXPERT,
        ("nilm", "mains_solar", "demand_capacity"),
    )
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        entity_registry=fake_registry,
    )
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    assert (
        "sensor.cs_energy_analyzer_demo_washer_active_power",
        {"hidden_by": "integration"},
    ) in fake_registry.updated
    assert fake_registry.removed == []


@pytest.mark.asyncio
async def test_sensor_setup_entry_keeps_demo_source_entities_hidden_for_expert(
    monkeypatch,
) -> None:
    import sys
    from types import ModuleType

    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    class FakeHider:
        INTEGRATION = "integration"

    class FakeRegistry:
        def __init__(self) -> None:
            self.entities = {
                "sensor.cs_energy_analyzer_demo_washer_active_power": SimpleNamespace(
                    entity_id="sensor.cs_energy_analyzer_demo_washer_active_power",
                    unique_id=(
                        "entry-1_demo_source_exact_"
                        "cs_energy_analyzer_demo_washer_active_power"
                    ),
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    hidden_by="integration",
                    entity_category=None,
                ),
            }
            self.removed: list[str] = []
            self.updated: list[tuple[str, dict[str, object]]] = []

        def async_remove(self, entity_id) -> None:
            self.removed.append(entity_id)

        def async_update_entity(self, entity_id, **kwargs) -> None:
            self.updated.append((entity_id, kwargs))
            self.entities[entity_id].hidden_by = kwargs.get("hidden_by")

    fake_registry = FakeRegistry()
    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    entity_registry_module = ModuleType("homeassistant.helpers.entity_registry")
    entity_registry_module.RegistryEntryHider = FakeHider
    entity_registry_module.async_get = lambda hass: hass.entity_registry
    helpers_module.entity_registry = entity_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry_module,
    )

    circuit = CircuitConfig(
        circuit_id="cs_energy_analyzer_demo_washer",
        name="Washer",
        appliance_profile=ApplianceProfile.WASHER,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(
            SensorRef(
                "sensor.cs_energy_analyzer_demo_washer_active_power",
                SensorRole.REAL_POWER,
            ),
        ),
    )
    coordinator = _use_expert_entity_detail(
        SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,))
    )
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        entity_registry=fake_registry,
    )
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    assert fake_registry.updated == []
    assert (
        fake_registry.entities[
            "sensor.cs_energy_analyzer_demo_washer_active_power"
        ].hidden_by
        == "integration"
    )


@pytest.mark.asyncio
async def test_sensor_setup_entry_materializes_demo_car_charger_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="cs_energy_analyzer_demo_car_charger",
        name="Car Charger",
        appliance_profile=ApplianceProfile.EV_CHARGER,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(
            SensorRef(
                "sensor.cs_energy_analyzer_demo_car_charger_l1_active_power",
                SensorRole.REAL_POWER,
                leg="a",
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_car_charger_l2_active_power",
                SensorRole.REAL_POWER,
                leg="b",
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_car_charger_l1_current",
                SensorRole.CURRENT,
                leg="a",
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_car_charger_l2_current",
                SensorRole.CURRENT,
                leg="b",
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_car_charger_l1_power_factor",
                SensorRole.POWER_FACTOR,
                leg="a",
            ),
            SensorRef(
                "sensor.cs_energy_analyzer_demo_car_charger_l2_reactive_power",
                SensorRole.REACTIVE_POWER,
                leg="b",
            ),
        ),
    )
    coordinator = _use_entity_detail(
        SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,)),
        ENTITY_DETAIL_EXPERT,
        ("nilm", "mains_solar", "demand_capacity"),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    source_entities = [
        entity
        for entity in added_entities
        if getattr(entity, "unique_id", "").startswith("entry-1_demo_source_")
    ]
    by_entity_id = {
        f"sensor.{entity.suggested_object_id}": entity for entity in source_entities
    }

    assert set(by_entity_id) == {
        "sensor.cs_energy_analyzer_demo_car_charger_l1_active_power",
        "sensor.cs_energy_analyzer_demo_car_charger_l2_active_power",
        "sensor.cs_energy_analyzer_demo_car_charger_l1_current",
        "sensor.cs_energy_analyzer_demo_car_charger_l2_current",
        "sensor.cs_energy_analyzer_demo_car_charger_l1_power_factor",
        "sensor.cs_energy_analyzer_demo_car_charger_l2_reactive_power",
    }
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_car_charger_l1_active_power"
        ].native_value
        == 4600.0
    )
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_car_charger_l2_active_power"
        ].native_value
        == 4550.0
    )
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_car_charger_l1_current"
        ].native_value
        == 38.5
    )
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_car_charger_l1_power_factor"
        ].native_value
        == 0.99
    )
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_car_charger_l2_reactive_power"
        ].native_value
        == 450.0
    )
    assert "sensor.cs_energy_analyzer_demo_car_charger_voltage" not in by_entity_id


@pytest.mark.asyncio
async def test_sensor_setup_entry_adds_mains_energy_without_appliance_cycles() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(
            SensorRef("sensor.mains_l1_power", SensorRole.REAL_POWER, leg="a"),
            SensorRef("sensor.mains_l2_power", SensorRole.REAL_POWER, leg="b"),
        ),
    )
    coordinator = _use_entity_detail(
        SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,)),
        ENTITY_DETAIL_EXPERT,
        ("nilm", "mains_solar", "demand_capacity"),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert {
        "entry-1_mains_nilm_signature_count",
        "entry-1_mains_nilm_unknown_loads",
        "entry-1_mains_nilm_unmatched_load_percentage",
        "entry-1_mains_nilm_topology_status",
        "entry-1_mains_balance_power",
        "entry-1_mains_current_demand",
        "entry-1_mains_daily_energy_usage",
    } <= unique_ids
    assert (
        not {
            "entry-1_mains_run_cycle_count",
            "entry-1_mains_standby_status",
            "entry-1_mains_billing_cycle_usage",
            "entry-1_mains_cost_cycle",
        }
        & unique_ids
    )


def test_stale_entity_registry_entries_identifies_only_inapplicable_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer.entity import (
        stale_entity_registry_entity_ids,
    )

    entries = [
        SimpleNamespace(
            entity_id="sensor.fridge_anomaly_score",
            unique_id="entry-1_fridge_anomaly_score",
            config_entry_id="entry-1",
            platform=DOMAIN,
        ),
        SimpleNamespace(
            entity_id="sensor.fridge_solar_generation_power",
            unique_id="entry-1_fridge_solar_generation_power",
            config_entry_id="entry-1",
            platform=DOMAIN,
        ),
        SimpleNamespace(
            entity_id="binary_sensor.fridge_learning",
            unique_id="entry-1_fridge_learning",
            config_entry_id="entry-1",
            platform=DOMAIN,
        ),
        SimpleNamespace(
            entity_id="sensor.other",
            unique_id="other_fridge_solar_generation_power",
            config_entry_id="other",
            platform=DOMAIN,
        ),
    ]

    assert stale_entity_registry_entity_ids(
        entries,
        entry_id="entry-1",
        entity_domain="sensor",
        desired_unique_ids={"entry-1_fridge_anomaly_score"},
    ) == ["sensor.fridge_solar_generation_power"]


@pytest.mark.asyncio
async def test_sensor_setup_entry_uses_runtime_synthetic_mains() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _use_entity_detail(
        SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,)),
        ENTITY_DETAIL_EXPERT,
        ("nilm", "mains_solar", "demand_capacity"),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    assert {entity.unique_id for entity in added_entities} >= {
        "entry-1_mains_health_summary",
        "entry-1_mains_nilm_signature_count",
        "entry-1_mains_balance_power",
        "entry-1_mains_current_demand",
    }


@pytest.mark.asyncio
async def test_binary_sensor_setup_omits_unselected_diagnostics_without_ha() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        async_setup_entry,
    )

    circuit = {
        "circuit_id": "well_pump",
        "name": "Well Pump",
    }
    coordinator = SimpleNamespace(data=AnalyzerState())
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={CONF_CIRCUITS: [circuit]})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    assert added_entities == []


@pytest.mark.asyncio
async def test_binary_sensor_setup_selected_expert_diagnostics_preserve_visibility(
    monkeypatch,
) -> None:
    import sys
    from types import ModuleType

    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        async_setup_entry,
    )

    class FakeHider:
        INTEGRATION = "integration"
        USER = "user"

    class FakeRegistry:
        def __init__(self) -> None:
            self.entities = {
                "binary_sensor.well_pump_learning": SimpleNamespace(
                    entity_id="binary_sensor.well_pump_learning",
                    unique_id="entry-1_well_pump_learning",
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    hidden_by="integration",
                ),
                "binary_sensor.well_pump_data_quality_problem": SimpleNamespace(
                    entity_id="binary_sensor.well_pump_data_quality_problem",
                    unique_id="entry-1_well_pump_data_quality_problem",
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    hidden_by="user",
                ),
            }
            self.updated: list[tuple[str, object]] = []
            self.removed: list[str] = []

        def async_remove(self, entity_id) -> None:
            self.removed.append(entity_id)

        def async_update_entity(self, entity_id, **kwargs) -> None:
            if "hidden_by" in kwargs:
                self.updated.append((entity_id, kwargs["hidden_by"]))
                self.entities[entity_id].hidden_by = kwargs["hidden_by"]
            if "entity_category" in kwargs:
                self.entities[entity_id].entity_category = kwargs["entity_category"]

    fake_registry = FakeRegistry()
    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    entity_registry_module = ModuleType("homeassistant.helpers.entity_registry")
    entity_registry_module.RegistryEntryHider = FakeHider
    entity_registry_module.async_get = lambda hass: hass.entity_registry
    helpers_module.entity_registry = entity_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry_module,
    )

    circuit = {
        "circuit_id": "well_pump",
        "name": "Well Pump",
    }
    coordinator = _use_expert_entity_detail(
        SimpleNamespace(
            data=AnalyzerState(),
            options={
                CONF_SELECTED_ENTITY_GROUPS: ["developer_diagnostics"],
            },
        )
    )
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        entity_registry=fake_registry,
    )
    entry = SimpleNamespace(entry_id="entry-1", data={CONF_CIRCUITS: [circuit]})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    assert {entity.unique_id for entity in added_entities} == {
        "entry-1_well_pump_learning",
        "entry-1_well_pump_data_quality_problem",
        "entry-1_well_pump_maintenance",
    }
    assert fake_registry.updated == []
    assert (
        fake_registry.entities["binary_sensor.well_pump_learning"].hidden_by
        == "integration"
    )
    assert (
        fake_registry.entities["binary_sensor.well_pump_data_quality_problem"].hidden_by
        == "user"
    )
    assert fake_registry.removed == []


@pytest.mark.asyncio
async def test_binary_sensor_setup_entry_does_not_add_redundant_running_entities() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        async_setup_entry,
    )

    washer = CircuitConfig(
        circuit_id="washer",
        name="Washer",
        appliance_profile=ApplianceProfile.WASHER,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.washer_power", SensorRole.REAL_POWER),),
    )
    dryer = CircuitConfig(
        circuit_id="dryer",
        name="Dryer",
        appliance_profile=ApplianceProfile.DRYER,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(SensorRef("sensor.dryer_power", SensorRole.REAL_POWER),),
    )
    refrigerator = CircuitConfig(
        circuit_id="refrigerator",
        name="Refrigerator",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.refrigerator_power", SensorRole.REAL_POWER),),
    )
    microwave = CircuitConfig(
        circuit_id="microwave",
        name="Microwave",
        appliance_profile=ApplianceProfile.MICROWAVE,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.microwave_power", SensorRole.REAL_POWER),),
    )
    mixed = CircuitConfig(
        circuit_id="mixed_lights",
        name="Mixed Lights",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_lights_power", SensorRole.REAL_POWER),),
    )
    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    solar = CircuitConfig(
        circuit_id="solar",
        name="Solar",
        appliance_profile=ApplianceProfile.SOLAR_INVERTER,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.solar_power", SensorRole.REAL_POWER),),
    )
    state = AnalyzerState(
        latest_real_power_w_by_circuit={
            "washer": 35.0,
            "dryer": 70.0,
            "refrigerator": 180.0,
            "microwave": 650.0,
            "mixed_lights": 1200.0,
            "mains": 2600.0,
            "solar": 1800.0,
        }
    )
    state.run_cycle_status_by_circuit["refrigerator"] = "running"
    coordinator = SimpleNamespace(
        data=state,
        circuit_configs=(washer, dryer, refrigerator, microwave, mixed, mains, solar),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    assert all(
        entity.entity_description.key != "running" for entity in added_entities
    )


@pytest.mark.asyncio
async def test_binary_sensor_setup_entry_uses_runtime_synthetic_mains() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        async_setup_entry,
    )

    circuit = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    coordinator = SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,))
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    assert added_entities == []


@pytest.mark.asyncio
async def test_binary_sensor_setup_entry_requires_water_flow_input_for_mismatch() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        async_setup_entry,
    )

    washer = CircuitConfig(
        circuit_id="washer",
        name="Washer",
        appliance_profile=ApplianceProfile.WASHER,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.washer_power", SensorRole.REAL_POWER),),
    )

    async def entity_keys_for(coordinator: SimpleNamespace) -> set[str]:
        hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
        entry = SimpleNamespace(entry_id="entry-1", data={})
        added_entities = []
        await async_setup_entry(hass, entry, added_entities.extend)
        return {entity.unique_id for entity in added_entities}

    without_flow = await entity_keys_for(
        SimpleNamespace(data=AnalyzerState(), circuit_configs=(washer,)),
    )
    with_flow = await entity_keys_for(
        SimpleNamespace(
            data=AnalyzerState(),
            circuit_configs=(washer,),
            options={
                CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_STANDARD,
                CONF_WATER_FLOW_SENSOR_ENTITIES: ["sensor.water_flow_rate"],
            },
            entry_data={},
        ),
    )
    with_linked_flow = await entity_keys_for(
        SimpleNamespace(
            data=AnalyzerState(),
            circuit_configs=(washer,),
            options={
                CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_STANDARD,
                CONF_ADVANCED_SETTINGS: {
                    "washer": {
                        CONF_LINKED_FLOW_SENSOR_ENTITIES: [
                            "binary_sensor.washer_water_flow"
                        ]
                    }
                },
            },
            entry_data={},
        ),
    )
    mixed_with_flow = await entity_keys_for(
        SimpleNamespace(
            data=AnalyzerState(),
            circuit_configs=(replace(washer, mode=CircuitMode.MIXED),),
            options={
                CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_STANDARD,
                CONF_WATER_FLOW_SENSOR_ENTITIES: ["sensor.water_flow_rate"],
            },
            entry_data={},
        ),
    )

    assert "entry-1_washer_water_flow_mismatch" not in without_flow
    assert "entry-1_washer_water_flow_mismatch" in with_flow
    assert "entry-1_washer_water_flow_mismatch" in with_linked_flow
    assert "entry-1_washer_water_flow_mismatch" not in mixed_with_flow


@pytest.mark.asyncio
async def test_binary_sensor_setup_entry_applies_to_dict_circuits() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        async_setup_entry,
    )

    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        circuit_configs=(),
        options={
            CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_STANDARD,
            CONF_WATER_FLOW_SENSOR_ENTITIES: ["binary_sensor.water_flow"],
        },
        entry_data={},
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "washer",
                    "name": "Washer",
                    "appliance_profile": "washer",
                    "mode": "single_phase",
                    "sensors": [
                        {
                            "entity_id": "sensor.washer_power",
                            "role": "real_power",
                        }
                    ],
                }
            ]
        },
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert "entry-1_washer_water_flow_mismatch" in unique_ids


@pytest.mark.asyncio
async def test_sensor_setup_entry_uses_linked_water_flow_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    washer = CircuitConfig(
        circuit_id="washer",
        name="Washer",
        appliance_profile=ApplianceProfile.WASHER,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.washer_power", SensorRole.REAL_POWER),),
    )
    coordinator = _use_entity_detail(
        SimpleNamespace(
            data=AnalyzerState(),
            circuit_configs=(washer,),
            options={
                CONF_ADVANCED_SETTINGS: {
                    "washer": {
                        CONF_LINKED_FLOW_SENSOR_ENTITIES: [
                            "binary_sensor.washer_water_flow"
                        ]
                    }
                }
            },
            entry_data={},
        ),
        ENTITY_DETAIL_EXPERT,
        ("water",),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert "entry-1_washer_water_flow_correlation" in unique_ids
    assert "entry-1_washer_water_flow_mismatch_minutes" in unique_ids


def test_health_summary_attributes_include_learning_day_progress() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        health_summary_attributes,
    )

    state = AnalyzerState(
        learning_progress_by_circuit={
            "fridge": {"baseline_age_days": 3.8, "days_required": 7}
        }
    )

    attributes = health_summary_attributes(state, "fridge")

    assert attributes["learning_days_complete"] == 3
    assert attributes["learning_days_required"] == 7


@pytest.mark.parametrize(
    ("progress_by_circuit", "expected"),
    (
        ({}, (0, 0)),
        ({"fridge": "invalid"}, (0, 0)),
        (
            {"fridge": {"baseline_age_days": "invalid", "days_required": 7}},
            (0, 0),
        ),
        ({"fridge": {"baseline_age_days": -1, "days_required": -7}}, (0, 0)),
        ({"fridge": {"baseline_age_days": 12, "days_required": 7}}, (7, 7)),
    ),
)
def test_health_summary_attributes_bound_learning_day_progress(
    progress_by_circuit: dict[str, object],
    expected: tuple[int, int],
) -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        health_summary_attributes,
    )

    attributes = health_summary_attributes(
        AnalyzerState(learning_progress_by_circuit=progress_by_circuit),
        "fridge",
    )

    assert (
        attributes["learning_days_complete"],
        attributes["learning_days_required"],
    ) == expected
