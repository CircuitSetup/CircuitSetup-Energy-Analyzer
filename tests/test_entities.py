from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_ADVANCED_SETTINGS,
    CONF_CIRCUITS,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_RAIN_PUMP_CORRELATION_ENABLED,
    CONF_UTILITY_COMPARISON_SETTINGS,
    CONF_WATER_FLOW_CORRELATION_ENABLED,
    CONF_WATER_FLOW_SENSOR_ENTITIES,
    DOMAIN,
)
from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
    SensorRef,
    SensorRole,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData

DOMAIN_PATH = Path(__file__).parents[1] / "custom_components" / DOMAIN


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


def test_apply_entity_profile_to_registry_changes_only_integration_owned_rows(
    monkeypatch,
) -> None:
    import sys
    from types import ModuleType

    from custom_components.circuitsetup_energy_analyzer import entity
    from custom_components.circuitsetup_energy_analyzer.entity import EntityTier

    class FakeDisabler:
        INTEGRATION = "integration"
        USER = "user"

    class FakeRegistry:
        def __init__(self) -> None:
            self.entities = {
                "sensor.fridge_activity_summary": SimpleNamespace(
                    entity_id="sensor.fridge_activity_summary",
                    unique_id="entry-1_fridge_activity_summary",
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    disabled_by=None,
                ),
                "sensor.fridge_energy_goal_status": SimpleNamespace(
                    entity_id="sensor.fridge_energy_goal_status",
                    unique_id="entry-1_fridge_energy_goal_status",
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    disabled_by=None,
                ),
                "sensor.fridge_power_quality_evidence": SimpleNamespace(
                    entity_id="sensor.fridge_power_quality_evidence",
                    unique_id="entry-1_fridge_power_quality_evidence",
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    disabled_by="integration",
                ),
                "sensor.fridge_alert_evidence": SimpleNamespace(
                    entity_id="sensor.fridge_alert_evidence",
                    unique_id="entry-1_fridge_alert_evidence",
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    disabled_by="user",
                ),
            }
            self.updated: list[tuple[str, object]] = []

        def async_update_entity(self, entity_id, **kwargs) -> None:
            self.updated.append((entity_id, kwargs.get("disabled_by")))
            self.entities[entity_id].disabled_by = kwargs.get("disabled_by")

    fake_registry = FakeRegistry()
    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    entity_registry_module = ModuleType("homeassistant.helpers.entity_registry")
    entity_registry_module.RegistryEntryDisabler = FakeDisabler
    entity_registry_module.async_get = lambda hass: hass.entity_registry
    helpers_module.entity_registry = entity_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry_module,
    )

    simple_plan = entity.apply_entity_profile_to_registry(
        SimpleNamespace(entity_registry=fake_registry),
        entry_id="entry-1",
        entity_domain="sensor",
        tier_by_unique_id_suffix={
            "activity_summary": EntityTier.SUMMARY,
            "energy_goal_status": EntityTier.FEATURE,
            "power_quality_evidence": EntityTier.DIAGNOSTIC,
            "alert_evidence": EntityTier.DIAGNOSTIC,
        },
        detail_level="simple",
    )

    assert simple_plan["will_disable"] == 1
    assert fake_registry.updated == [
        ("sensor.fridge_energy_goal_status", "integration")
    ]

    expert_plan = entity.apply_entity_profile_to_registry(
        SimpleNamespace(entity_registry=fake_registry),
        entry_id="entry-1",
        entity_domain="sensor",
        tier_by_unique_id_suffix={
            "activity_summary": EntityTier.SUMMARY,
            "energy_goal_status": EntityTier.FEATURE,
            "power_quality_evidence": EntityTier.DIAGNOSTIC,
            "alert_evidence": EntityTier.DIAGNOSTIC,
        },
        detail_level="expert",
    )

    assert expert_plan["will_enable"] == 2
    assert expert_plan["left_user_disabled"] == 1
    assert fake_registry.updated[-2:] == [
        ("sensor.fridge_energy_goal_status", None),
        ("sensor.fridge_power_quality_evidence", None),
    ]


def test_enable_summary_registry_entries_repairs_newly_promoted_entities(
    monkeypatch,
) -> None:
    import sys
    from types import ModuleType

    from custom_components.circuitsetup_energy_analyzer import entity
    from custom_components.circuitsetup_energy_analyzer.entity import EntityTier

    class FakeRegistry:
        def __init__(self) -> None:
            self.entities = {
                "sensor.mains_nilm_nilm_unknown_loads": SimpleNamespace(
                    entity_id="sensor.mains_nilm_nilm_unknown_loads",
                    unique_id="entry-1_mains_nilm_unknown_loads",
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    disabled_by="integration",
                ),
                "sensor.mains_nilm_nilm_discovered_signatures": SimpleNamespace(
                    entity_id="sensor.mains_nilm_nilm_discovered_signatures",
                    unique_id="entry-1_mains_nilm_signature_count",
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    disabled_by="integration",
                ),
                "sensor.mains_nilm_power_quality_evidence": SimpleNamespace(
                    entity_id="sensor.mains_nilm_power_quality_evidence",
                    unique_id="entry-1_mains_power_quality_evidence",
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    disabled_by="integration",
                ),
                "sensor.mains_nilm_activity_summary": SimpleNamespace(
                    entity_id="sensor.mains_nilm_activity_summary",
                    unique_id="entry-1_mains_activity_summary",
                    config_entry_id="entry-1",
                    platform=DOMAIN,
                    disabled_by="user",
                ),
            }
            self.updated: list[tuple[str, object]] = []

        def async_update_entity(self, entity_id, **kwargs) -> None:
            self.updated.append((entity_id, kwargs.get("disabled_by")))
            self.entities[entity_id].disabled_by = kwargs.get("disabled_by")

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

    plan = entity.enable_summary_registry_entries(
        SimpleNamespace(entity_registry=FakeRegistry()),
        entry_id="entry-1",
        entity_domain="sensor",
        tier_by_unique_id_suffix={
            "activity_summary": EntityTier.SUMMARY,
            "nilm_signature_count": EntityTier.SUMMARY,
            "nilm_unknown_loads": EntityTier.SUMMARY,
            "power_quality_evidence": EntityTier.DIAGNOSTIC,
        },
    )

    assert plan == {
        "enabled": 2,
        "left_user_disabled": 1,
        "unchanged": 0,
        "ignored": 1,
        "actions": [
            {
                "action": "enable",
                "entity_id": "sensor.mains_nilm_nilm_unknown_loads",
                "suffix": "nilm_unknown_loads",
            },
            {
                "action": "enable",
                "entity_id": "sensor.mains_nilm_nilm_discovered_signatures",
                "suffix": "nilm_signature_count",
            },
            {
                "action": "ignore",
                "entity_id": "sensor.mains_nilm_power_quality_evidence",
                "suffix": "power_quality_evidence",
            },
            {
                "action": "left_user_disabled",
                "entity_id": "sensor.mains_nilm_activity_summary",
                "suffix": "activity_summary",
            },
        ],
    }


def test_prune_stale_device_registry_entries_detaches_config_entry(monkeypatch) -> (
    None
):
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
        alert_evidence_value,
        always_on_limit_usage_value,
        always_on_power_value,
        anomaly_score_value,
        apparent_power_drift_value,
        balance_power_value,
        balance_status_value,
        billing_cycle_budget_usage_value,
        billing_cycle_forecast_value,
        billing_cycle_status_value,
        billing_cycle_usage_value,
        capacity_status_value,
        capacity_usage_value,
        circuit_mode_value,
        cost_current_rate_value,
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
        electrical_health_value,
        energy_dashboard_status_value,
        energy_goal_status_value,
        energy_goal_usage_value,
        energy_summary_value,
        energy_usage_share_value,
        energy_usage_status_value,
        health_summary_value,
        last_event_value,
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
        recent_activity_count_value,
        recent_activity_value,
        run_cycle_count_value,
        run_cycle_duty_cycle_value,
        run_cycle_runtime_value,
        run_cycle_status_value,
        sensitivity_value,
        settings_suggestions_attributes,
        settings_suggestions_value,
        setup_health_attributes,
        setup_health_value,
        solar_flexible_load_coverage_value,
        solar_flexible_load_power_value,
        solar_flow_status_value,
        solar_generation_power_value,
        solar_grid_export_power_value,
        solar_grid_import_power_value,
        solar_load_shift_power_value,
        solar_load_shift_status_value,
        solar_powered_value,
        solar_self_consumption_value,
        solar_site_consumption_power_value,
        solar_surplus_power_value,
        solar_surplus_status_value,
        standby_status_value,
        standby_threshold_value,
        utility_comparison_difference_value,
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
                    }
                ],
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
    assert last_event_value(state, "fridge") == "start"
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
        "unknown_loads": [
            {
                "signature_id": "sig-motor",
                "likely_type": "motor",
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
    assert alert_evidence_value(state, "fridge") == "Reactive Power"
    assert recent_activity_value(state, "fridge") == "Possible issue: Cycle Duration"
    assert recent_activity_count_value(state, "fridge") == 2
    assert sensitivity_value(state, "fridge") == "Quiet"
    assert circuit_mode_value(state, "fridge") == "Dual Phase"
    assert power_flow_value(state, "fridge") == "Generation / Solar Export"
    assert activity_summary_value(state, "fridge") == "Idle"
    assert electrical_health_value(state, "fridge") == "Possible Imbalance"
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
    assert (
        metric_consistency_status_value(state, "fridge")
        == "apparent_power_mismatch"
    )
    assert balance_power_value(state, "fridge") == 2300.0
    assert monitored_power_value(state, "fridge") == 2700.0
    assert monitored_coverage_value(state, "fridge") == 54.0
    assert balance_status_value(state, "fridge") == "tracking"
    assert solar_generation_power_value(state, "fridge") == 2000.0
    assert solar_site_consumption_power_value(state, "fridge") == 1500.0
    assert solar_grid_import_power_value(state, "fridge") == 0.0
    assert solar_grid_export_power_value(state, "fridge") == 500.0
    assert solar_self_consumption_value(state, "fridge") == 75.0
    assert solar_powered_value(state, "fridge") == 100.0
    assert solar_flow_status_value(state, "fridge") == "exporting"
    assert solar_surplus_power_value(state, "fridge") == 500.0
    assert solar_load_shift_power_value(state, "fridge") == 500.0
    assert solar_flexible_load_power_value(state, "fridge") == 800.0
    assert solar_flexible_load_coverage_value(state, "fridge") == 100.0
    assert solar_surplus_status_value(state, "fridge") == "surplus_available"
    assert solar_load_shift_status_value(state, "fridge") == "active_solar_supported"
    assert utility_comparison_difference_value(state, "fridge") == 12.5
    assert utility_comparison_status_value(state, "fridge") == "mismatch"
    assert billing_cycle_usage_value(state, "fridge") == 100.0
    assert billing_cycle_forecast_value(state, "fridge") == 300.0
    assert billing_cycle_budget_usage_value(state, "fridge") == 40.0
    assert billing_cycle_status_value(state, "fridge") == "projected_over_budget"
    assert cost_current_rate_value(state, "fridge") == 0.3
    assert cost_cycle_value(state, "fridge") == 6.2
    assert cost_cycle_forecast_value(state, "fridge") == 18.6
    assert cost_status_value(state, "fridge") == "tou_peak"
    assert always_on_power_value(state, "fridge") == 45.0
    assert standby_threshold_value(state, "fridge") == 8.0
    assert standby_status_value(state, "fridge") == "standby"
    assert always_on_limit_usage_value(state, "fridge") == 180.0
    assert settings_suggestions_value(state, "fridge") == 2
    assert settings_suggestions_attributes(state, "fridge") == {
        "pending_count": 2,
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
    assert last_event_value(state, "unknown") is None
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
    assert health_summary_value(state, "unknown") == "Ready"
    assert readiness_value(state, "unknown") == "ready"
    assert learning_progress_value(state, "unknown") == 0.0
    assert data_quality_checklist_value(state, "unknown") == "problem"
    assert energy_dashboard_status_value(state, "unknown") == "needs_energy_source"
    assert alert_evidence_value(state, "unknown") == ""
    assert recent_activity_value(state, "unknown") == "No recent activity"
    assert recent_activity_count_value(state, "unknown") == 0
    assert sensitivity_value(state, "unknown") == "Balanced"
    assert activity_summary_value(state, "unknown") == "No Activity"
    assert electrical_health_value(state, "unknown") == "Needs Metrics"
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
    assert solar_site_consumption_power_value(state, "unknown") == 0.0
    assert solar_grid_import_power_value(state, "unknown") == 0.0
    assert solar_grid_export_power_value(state, "unknown") == 0.0
    assert solar_self_consumption_value(state, "unknown") == 0.0
    assert solar_powered_value(state, "unknown") == 0.0
    assert solar_flow_status_value(state, "unknown") == "missing_mains"
    assert solar_surplus_power_value(state, "unknown") == 0.0
    assert solar_load_shift_power_value(state, "unknown") == 0.0
    assert solar_flexible_load_power_value(state, "unknown") == 0.0
    assert solar_flexible_load_coverage_value(state, "unknown") == 0.0
    assert solar_surplus_status_value(state, "unknown") == "missing_mains"
    assert solar_load_shift_status_value(state, "unknown") == "not_applicable"
    assert utility_comparison_difference_value(state, "unknown") == 0.0
    assert utility_comparison_status_value(state, "unknown") == "unconfigured"
    assert billing_cycle_usage_value(state, "unknown") == 0.0
    assert billing_cycle_forecast_value(state, "unknown") == 0.0
    assert billing_cycle_budget_usage_value(state, "unknown") == 0.0
    assert billing_cycle_status_value(state, "unknown") == "no_budget"
    assert cost_current_rate_value(state, "unknown") == 0.0
    assert cost_cycle_value(state, "unknown") == 0.0
    assert cost_cycle_forecast_value(state, "unknown") == 0.0
    assert cost_status_value(state, "unknown") == "unconfigured"
    assert always_on_power_value(state, "unknown") == 0.0
    assert standby_threshold_value(state, "unknown") == 0.0
    assert standby_status_value(state, "unknown") == "learning"
    assert always_on_limit_usage_value(state, "unknown") == 0.0
    assert settings_suggestions_value(state, "unknown") == 0
    assert settings_suggestions_attributes(state, "unknown") == {
        "pending_count": 0,
        "shown_count": 0,
        "has_more": False,
        "recommendations": [],
    }

    setup_coordinator = SimpleNamespace(
        data=AnalyzerState(
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
    )
    assert setup_health_value(setup_coordinator) == "Add cumulative kWh source"
    setup_attrs = setup_health_attributes(setup_coordinator)
    assert setup_attrs["blocking_issue_count"] == 1
    assert setup_attrs["issue_count"] == 1
    assert setup_attrs["warning_count"] == 0
    assert setup_attrs["ready"] is False
    assert setup_attrs["next_step"] == (
        "Add a cumulative kWh sensor to Kitchen Fridge"
    )
    assert setup_attrs["recommended_action"] == (
        "Add a cumulative kWh sensor to Kitchen Fridge"
    )
    assert setup_attrs["affected_circuit"] == "fridge"
    assert setup_attrs["affected_circuits"] == ["fridge"]
    assert setup_attrs["missing_energy_sources"] == ["fridge"]
    assert setup_attrs["learning_circuits"] == []
    assert setup_attrs["stale_sources"] == []
    assert setup_attrs["negative_power_loads"] == []
    assert setup_attrs["issues"][0]["reason"] == (
        "Daily Energy Usage needs a cumulative energy source."
    )
    assert setup_attrs["issues"][0]["circuit_id"] == "fridge"
    assert setup_attrs["issues"][0]["issue"] == "missing_energy_source"
    assert setup_attrs["issues"][0]["fix"] == (
        "Add a cumulative kWh sensor to Kitchen Fridge"
    )

    ready_coordinator = SimpleNamespace(data=AnalyzerState(), circuit_configs=())
    assert setup_health_value(ready_coordinator) == "Review circuit assignments"
    assert setup_health_attributes(ready_coordinator)["blocking_issue_count"] == 1


def test_summary_sensors_answer_primary_user_questions() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        activity_summary_attributes,
        activity_summary_value,
        electrical_health_attributes,
        electrical_health_value,
        energy_summary_attributes,
        energy_summary_value,
        health_summary_attributes,
        health_summary_value,
    )

    state = AnalyzerState(
        health_summary_by_circuit={"washer": "Possible issue"},
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
    assert health_attrs["status_label"] == "Possible issue"
    assert health_attrs["active_alert_count"] == 2
    assert health_attrs["next_step"] == "Review source sensor data"
    assert health_attrs["learning_progress"] == 0.0

    assert activity_summary_value(state, "washer") == "Running"
    assert activity_summary_attributes(state, "washer") == {
        "run_cycle_status": "running",
        "standby_status": "on",
        "run_cycle_count": 2,
        "run_cycle_runtime_seconds": 1800.0,
        "duty_cycle_percent": 0.0,
        "summary_explanation": "The appliance is currently active.",
    }

    assert electrical_health_value(state, "washer") == "Possible Metric Mismatch"
    electrical_attrs = electrical_health_attributes(state, "washer")
    assert electrical_attrs["metric_consistency_status"] == "metric_mismatch"
    assert electrical_attrs["metric_consistency_score"] == 28.5
    assert electrical_attrs["status_explanation"] == (
        "Reported electrical measurements do not agree with each other."
    )
    assert electrical_attrs["power_quality_evidence"] == (
        "Possible issue: apparent power changed"
    )

    assert energy_summary_value(state, "washer") == "High Usage"
    energy_attrs = energy_summary_attributes(state, "washer")
    assert energy_attrs["energy_usage_status"] == "over_threshold"
    assert energy_attrs["billing_cycle_status"] == "projected_over_budget"
    assert energy_attrs["daily_energy_usage_kwh"] == 13.1
    assert energy_attrs["summary_explanation"] == (
        "Energy use is above a configured threshold or budget."
    )

    power_quality_only_state = AnalyzerState(
        metric_consistency_status_by_circuit={"pump": "missing_metrics"},
        power_quality_evidence_by_circuit={
            "pump": "Possible issue: reactive power changed from baseline"
        },
        power_quality_score_by_circuit={"pump": 0.35},
    )

    assert electrical_health_value(power_quality_only_state, "pump") == (
        "Possible Power Quality Change"
    )
    assert electrical_health_attributes(power_quality_only_state, "pump")[
        "status_explanation"
    ] == "Power-quality evidence has changed from the learned baseline."

    score_only_state = AnalyzerState(
        metric_consistency_status_by_circuit={"mixed": "missing_metrics"},
        power_quality_score_by_circuit={"mixed": 0.35},
    )

    assert electrical_health_value(score_only_state, "mixed") == "Needs Metrics"

    power_only_state = AnalyzerState()
    assert energy_summary_value(power_only_state, "pump") == "Needs Energy Data"
    assert energy_summary_attributes(power_only_state, "pump")[
        "summary_explanation"
    ] == "No cumulative kWh evidence is available for this circuit."


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

    negative_power = coordinator_for(
        fridge,
        AnalyzerState(
            data_quality_checklist_by_circuit={
                "fridge": {
                    "quality_issues": [
                        "sensor.fridge_power negative_real_power_load"
                    ],
                    "required_sensors_present": True,
                }
            }
        ),
    )
    assert setup_health_value(negative_power) == "Check CT direction"

    assert setup_health_value(coordinator_for(hvac)) == "Configure breaker amps"

    weather_context = coordinator_for(
        hvac,
        store_data=FeatureStoreData(
            capacity_settings_by_circuit={"hvac": {"breaker_amps": 40.0}},
        ),
    )
    assert setup_health_value(weather_context) == "Add outdoor temperature source"

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


def test_setup_health_reports_fixable_context_and_utility_setup_gaps() -> None:
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

    assert setup_health_value(coordinator) == "Add rain source"
    assert attrs["missing_rain_sources"] == ["sump_pump"]
    assert attrs["missing_water_flow_sources"] == ["washer"]
    assert attrs["utility_comparison_setup_issues"] == ["mains"]
    assert [issue["issue"] for issue in attrs["issues"]] == [
        "missing_rain_context_source",
        "missing_water_flow_source",
        "utility_comparison_source_mismatch",
    ]


def test_binary_sensor_helpers_return_diagnostic_values_and_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        has_data_quality_problem,
        is_appliance_running,
        is_laundry_appliance_running,
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
    assert (
        is_laundry_appliance_running(state, "washer", ApplianceProfile.WASHER)
        is False
    )

    state.latest_real_power_w_by_circuit["washer"] = 19.9
    state.latest_real_power_w_by_circuit["dryer"] = 99.9
    assert (
        is_laundry_appliance_running(state, "washer", ApplianceProfile.WASHER)
        is False
    )
    assert is_laundry_appliance_running(state, "dryer", ApplianceProfile.DRYER) is False

    state.latest_real_power_w_by_circuit["washer"] = 20.0
    state.latest_real_power_w_by_circuit["dryer"] = 100.0
    state.latest_real_power_w_by_circuit["refrigerator"] = 40.0
    state.latest_real_power_w_by_circuit["microwave"] = 650.0
    state.latest_real_power_w_by_circuit["mixed"] = 1200.0
    assert (
        is_laundry_appliance_running(state, "washer", ApplianceProfile.WASHER)
        is True
    )
    assert is_laundry_appliance_running(state, "dryer", ApplianceProfile.DRYER) is True
    assert (
        is_appliance_running(state, "refrigerator", ApplianceProfile.REFRIGERATOR)
        is True
    )
    assert is_appliance_running(state, "microwave", ApplianceProfile.MICROWAVE) is True
    assert is_appliance_running(state, "mixed", ApplianceProfile.MIXED) is False

    state.run_cycle_status_by_circuit["refrigerator"] = "running"
    state.run_cycle_status_by_circuit["oven"] = "idle"
    state.latest_real_power_w_by_circuit["refrigerator"] = 0.0
    state.latest_real_power_w_by_circuit["oven"] = 2000.0
    assert is_appliance_running(state, "refrigerator", ApplianceProfile.REFRIGERATOR)
    assert is_appliance_running(state, "oven", ApplianceProfile.OVEN) is False


def test_demo_source_values_are_intentionally_triggerable() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        APPLIANCE_RUNNING_POWER_THRESHOLDS_W,
    )
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

    reported_va = (
        (_demo_source_value("hvac_l1", SensorRole.APPARENT_POWER) or 0.0)
        + (_demo_source_value("hvac_l2", SensorRole.APPARENT_POWER) or 0.0)
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

    assert (
        (_demo_source_value("washer", SensorRole.REAL_POWER) or 0.0)
        > APPLIANCE_RUNNING_POWER_THRESHOLDS_W[ApplianceProfile.WASHER]
    )
    assert (
        (_demo_source_value("dryer_l1", SensorRole.REAL_POWER) or 0.0)
        + (_demo_source_value("dryer_l2", SensorRole.REAL_POWER) or 0.0)
        > APPLIANCE_RUNNING_POWER_THRESHOLDS_W[ApplianceProfile.DRYER]
    )


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
        "electrical_health",
        "energy_summary",
        "daily_energy_usage",
        "nilm_signature_count",
        "nilm_unknown_loads",
        "weather_context",
        "outdoor_temperature",
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
        "electrical_health",
        "energy_summary",
        "nilm_signature_count",
        "nilm_unknown_loads",
        "settings_suggestions",
        "daily_energy_usage",
        "weather_context",
        "outdoor_temperature",
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
        "balance_power",
        "monitored_power",
        "monitored_coverage",
        "solar_generation_power",
        "solar_site_consumption_power",
        "solar_grid_import_power",
        "solar_grid_export_power",
        "solar_self_consumption",
        "solar_powered",
        "solar_flow_status",
        "solar_surplus_power",
        "solar_load_shift_power",
        "solar_flexible_load_power",
        "solar_flexible_load_coverage",
        "solar_load_shift_status",
        "solar_surplus_status",
        "utility_comparison_difference",
        "utility_comparison_status",
        "billing_cycle_usage",
        "billing_cycle_forecast",
        "billing_cycle_budget_usage",
        "billing_cycle_status",
        "cost_current_rate",
        "cost_cycle",
        "cost_cycle_forecast",
        "cost_status",
        "always_on_power",
        "standby_threshold",
        "standby_status",
        "always_on_limit_usage",
    }

    assert normal_entity_keys <= set(descriptions)
    assert descriptions["settings_suggestions"].name_suffix == "Settings Suggestions"
    assert descriptions["settings_suggestions"].entity_registry_enabled_default is False
    assert descriptions["settings_suggestions"].entity_registry_visible_default is False
    assert descriptions["health_summary"].entity_tier is EntityTier.SUMMARY
    assert descriptions["daily_energy_usage"].entity_tier is EntityTier.SUMMARY
    assert descriptions["nilm_signature_count"].entity_tier is EntityTier.SUMMARY
    assert descriptions["nilm_unknown_loads"].entity_tier is EntityTier.SUMMARY
    assert descriptions["energy_goal_status"].entity_tier is EntityTier.FEATURE
    assert descriptions["power_quality_score"].entity_tier is EntityTier.DIAGNOSTIC
    assert descriptions["power_quality_score"].entity_registry_enabled_default is False
    assert descriptions["metric_consistency_status"].entity_tier is (
        EntityTier.DIAGNOSTIC
    )
    assert (
        descriptions["metric_consistency_status"].entity_registry_enabled_default
        is False
    )
    for diagnostic_status_key in {
        "run_cycle_status",
        "demand_status",
        "capacity_status",
        "leg_imbalance_status",
        "balance_status",
    }:
        assert descriptions[diagnostic_status_key].entity_tier is (
            EntityTier.DIAGNOSTIC
        )
        assert (
            descriptions[diagnostic_status_key].entity_registry_enabled_default
            is False
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
        description=descriptions["power_quality_evidence"],
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
        description=descriptions["power_quality_evidence"],
    )
    expert_diagnostic_entity = CircuitAnalyzerSensor(
        expert_coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["power_quality_evidence"],
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
        "learning_progress": "mdi:school-outline",
        "circuit_mode": "mdi:transmission-tower",
        "power_flow": "mdi:swap-horizontal",
        "settings_suggestions": "mdi:tune-variant",
        "power_quality_score": "mdi:sine-wave",
        "reactive_power_drift": "mdi:flash-triangle-outline",
        "power_factor_drift": "mdi:cosine-wave",
        "daily_energy_usage": "mdi:counter",
        "current_demand": "mdi:gauge",
        "metric_consistency_status": "mdi:clipboard-check-outline",
        "standby_status": "mdi:power-sleep",
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
        weather_context_value(SimpleNamespace(), "missing")
        == "No Temperature Source"
    )
    assert weather_context_attributes(state, "missing") == {}


def test_outdoor_temperature_sensor_exposes_graphable_display_temperature() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        CircuitAnalyzerSensor,
        outdoor_temperature_attributes,
        outdoor_temperature_value,
    )

    state = SimpleNamespace(
        weather_context_by_circuit={
            "hvac": {
                "status": "weather_correlated",
                "temperature_f": 77.0,
                "current_outdoor_temperature": 25.0,
                "temperature_unit": "°C",
            }
        }
    )

    assert outdoor_temperature_value(state, "hvac") == 25.0
    assert outdoor_temperature_attributes(state, "hvac") == {
        "temperature_f": 77.0,
        "temperature_unit": "°C",
    }

    description = {
        description.key: description for description in SENSOR_DESCRIPTIONS
    }["outdoor_temperature"]
    entity = CircuitAnalyzerSensor(
        SimpleNamespace(data=state),
        entry_id="entry-1",
        circuit=SimpleNamespace(
            circuit_id="hvac",
            name="HVAC",
            appliance_profile="hvac",
        ),
        description=description,
    )

    assert entity.native_value == 25.0
    assert entity.native_unit_of_measurement == "°C"


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


def test_outdoor_temperature_sensor_metadata_is_graphable_and_visible() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        CircuitAnalyzerSensor,
    )

    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    description = descriptions["outdoor_temperature"]
    coordinator = SimpleNamespace(data=AnalyzerState())
    circuit = SimpleNamespace(circuit_id="hvac", name="HVAC", appliance_profile="hvac")

    entity = CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=description,
    )

    assert description.name_suffix == "Outdoor Temperature"
    assert description.entity_category is None
    assert description.entity_registry_visible_default is True
    assert entity.icon == "mdi:thermometer"
    assert entity._attr_entity_category is None


def test_weather_context_sensor_only_applies_to_hvac_with_temperature_source() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        sensor_description_applies,
    )

    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    weather_description = descriptions["weather_context"]
    outdoor_temperature_description = descriptions["outdoor_temperature"]
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
            outdoor_temperature_description,
            circuit,
            coordinator_with_options,
        )
        assert sensor_description_applies(
            weather_description,
            circuit,
            coordinator_with_entry_data,
        )
        assert sensor_description_applies(
            outdoor_temperature_description,
            circuit,
            coordinator_with_entry_data,
        )
        assert not sensor_description_applies(
            weather_description,
            circuit,
            coordinator_without_temperature,
        )
        assert not sensor_description_applies(
            outdoor_temperature_description,
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
    assert not sensor_description_applies(
        outdoor_temperature_description,
        SimpleNamespace(
            circuit_id="fridge",
            name="Fridge",
            appliance_profile=ApplianceProfile.REFRIGERATOR,
        ),
        coordinator_with_options,
    )


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


def test_settings_suggestions_sensor_has_translation_entry() -> None:
    strings = json.loads(
        (DOMAIN_PATH / "strings.json").read_text(encoding="utf-8"),
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
    assert (
        feature_module.nilm_unknown_loads_attributes
        is nilm_unknown_loads_attributes
    )


def test_status_sensor_entities_explain_machine_status_values() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        CircuitAnalyzerSensor,
    )

    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    state = AnalyzerState(
        metric_consistency_status_by_circuit={"pool": "missing_metrics"},
        metric_consistency_evidence_by_circuit={
            "pool": {
                "status": "missing_metrics",
                "missing_roles": ["voltage", "current", "apparent_power"],
            }
        },
        leg_imbalance_status_by_circuit={"pool": "not_dual_phase"},
        solar_flow_status_by_circuit={"pool": "inconsistent_export"},
    )
    coordinator = SimpleNamespace(data=state)
    circuit = SimpleNamespace(
        circuit_id="pool",
        name="Pool Pump",
        appliance_profile="pool_pump",
    )

    metric_status = CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["metric_consistency_status"],
    )
    assert metric_status.native_value == "Missing Metrics"
    assert metric_status.extra_state_attributes == {
        "status": "missing_metrics",
        "missing_roles": ["voltage", "current", "apparent_power"],
        "raw_status": "missing_metrics",
        "status_label": "Missing Metrics",
        "status_explanation": (
            "This check needs more matching voltage, current, real power, "
            "apparent power, or power factor sensors."
        ),
    }

    leg_status = CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["leg_imbalance_status"],
    )
    assert leg_status.native_value == "Not Dual Phase"
    assert leg_status.extra_state_attributes == {
        "raw_status": "not_dual_phase",
        "status_label": "Not Dual Phase",
        "status_explanation": "This check only applies to dual-phase circuits.",
    }

    solar_status = CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["solar_flow_status"],
    )
    assert solar_status.native_value == "Inconsistent Export"
    assert solar_status.extra_state_attributes["raw_status"] == "inconsistent_export"
    assert "CT orientation" in solar_status.extra_state_attributes[
        "status_explanation"
    ]


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
    assert (
        descriptions["data_quality_problem"].entity_registry_visible_default is False
    )
    assert (
        descriptions["data_quality_problem"].entity_registry_enabled_default is False
    )
    assert descriptions["data_quality_problem"].entity_tier is EntityTier.DIAGNOSTIC
    assert descriptions["maintenance"].entity_registry_visible_default is False
    assert descriptions["maintenance"].entity_registry_enabled_default is False
    assert descriptions["maintenance"].entity_tier is EntityTier.DIAGNOSTIC
    assert descriptions["running"].entity_registry_visible_default is True
    assert descriptions["running"].entity_registry_enabled_default is True
    assert descriptions["running"].entity_tier is EntityTier.SUMMARY
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
        "maintenance": "mdi:wrench-clock",
        "running": "mdi:power-cycle",
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


def test_sensor_extra_attributes_return_runtime_diagnostics() -> None:
    from custom_components.circuitsetup_energy_analyzer.safety import (
        ELECTRICAL_SAFETY_NOTICE,
    )
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        CircuitAnalyzerSensor,
    )

    readiness = {
        "health_status": "possible_issue",
        "health_summary": "Possible issue",
    }
    progress = {
        "learned_feature_count": 5,
        "pending_feature_samples": {"reactive_power": 3},
    }
    checklist = {"quality_issues": [], "required_sensors_present": True}
    energy_dashboard = {
        "status": "ready",
        "ready_energy_entities": ["sensor.fridge_energy"],
    }
    evidence = {"feature": "reactive_power", "change_ratio": 0.42}
    recent_activity = {
        "status": "activity",
        "total_count": 2,
        "items": [{"title": "Possible issue: Cycle Duration"}],
    }
    energy_evidence = {
        "status": "tracking",
        "daily_usage_kwh": 8.2,
        "baseline_total_kwh": 50.0,
    }
    energy_goal_evidence = {
        "status": "over_goal",
        "daily_usage_kwh": 13.2,
        "daily_goal_kwh": 12.0,
    }
    run_cycle_evidence = {
        "status": "idle",
        "start_count": 4,
        "runtime_seconds": 3600.0,
    }
    demand_evidence = {
        "status": "over_limit",
        "current_demand_w": 2400.0,
        "demand_limit_w": 2000.0,
    }
    capacity_evidence = {
        "status": "over_limit",
        "capacity_usage_percent": 85.0,
        "breaker_amps": 40.0,
    }
    demand_evidence_with_notice = {
        **demand_evidence,
        "safety_notice": ELECTRICAL_SAFETY_NOTICE,
    }
    capacity_evidence_with_notice = {
        **capacity_evidence,
        "safety_notice": ELECTRICAL_SAFETY_NOTICE,
    }
    leg_imbalance_evidence = {
        "status": "imbalanced",
        "leg_imbalance_percent": 66.7,
        "left_real_power_w": 2400.0,
        "right_real_power_w": 1200.0,
    }
    metric_consistency_evidence = {
        "status": "apparent_power_mismatch",
        "mismatch_score_percent": 50.0,
        "expected_apparent_power_va": 1200.0,
        "reported_apparent_power_va": 600.0,
    }
    balance_evidence = {
        "status": "tracking",
        "balance_power_w": 2300.0,
        "monitored_coverage_percent": 54.0,
    }
    solar_flow_evidence = {
        "status": "exporting",
        "solar_surplus_status": "surplus_available",
        "solar_generation_w": 2000.0,
        "site_consumption_w": 1500.0,
        "solar_surplus_w": 500.0,
        "load_shift_available_w": 500.0,
    }
    solar_load_shift_evidence = {
        "status": "active_solar_supported",
        "active_flexible_load_power_w": 800.0,
        "solar_coverage_percent": 100.0,
        "candidate_loads": [{"circuit_id": "pool", "state": "active"}],
    }
    utility_comparison_evidence = {
        "status": "mismatch",
        "utility_kwh": 120.0,
        "measured_kwh": 135.0,
    }
    nilm_topology_evidence = {
        "status": "topology_mismatch",
        "observed_split_phase_type": "balanced_240v",
        "configured_mode": "single_phase",
    }
    billing_cycle_evidence = {
        "status": "projected_over_budget",
        "cycle_usage_kwh": 100.0,
        "projected_cycle_kwh": 300.0,
    }
    cost_evidence = {
        "status": "tou_peak",
        "active_rate_name": "Peak",
        "current_rate_per_kwh": 0.3,
    }
    standby_evidence = {
        "status": "standby",
        "always_on_power_w": 45.0,
        "standby_threshold_w": 8.0,
    }
    state = AnalyzerState(
        readiness_by_circuit={"fridge": readiness},
        learning_progress_by_circuit={"fridge": progress},
        data_quality_checklist_by_circuit={"fridge": checklist},
        energy_dashboard_evidence_by_circuit={"fridge": energy_dashboard},
        alert_evidence_by_circuit={"fridge": evidence},
        recent_activity_timeline_by_circuit={"fridge": recent_activity},
        sensitivity_by_circuit={"fridge": "quiet"},
        energy_usage_evidence_by_circuit={"fridge": energy_evidence},
        energy_goal_evidence_by_circuit={"fridge": energy_goal_evidence},
        run_cycle_evidence_by_circuit={"fridge": run_cycle_evidence},
        demand_evidence_by_circuit={"fridge": demand_evidence},
        capacity_evidence_by_circuit={"fridge": capacity_evidence},
        leg_imbalance_evidence_by_circuit={"fridge": leg_imbalance_evidence},
        metric_consistency_evidence_by_circuit={
            "fridge": metric_consistency_evidence
        },
        balance_evidence_by_circuit={"fridge": balance_evidence},
        solar_flow_evidence_by_circuit={"fridge": solar_flow_evidence},
        solar_load_shift_evidence_by_circuit={
            "fridge": solar_load_shift_evidence
        },
        utility_comparison_evidence_by_circuit={
            "fridge": utility_comparison_evidence
        },
        nilm_topology_evidence_by_circuit={
            "fridge": nilm_topology_evidence
        },
        billing_cycle_evidence_by_circuit={"fridge": billing_cycle_evidence},
        cost_evidence_by_circuit={"fridge": cost_evidence},
        standby_evidence_by_circuit={"fridge": standby_evidence},
    )
    coordinator = SimpleNamespace(data=state)
    circuit = SimpleNamespace(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile="refrigerator",
    )
    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}

    def assert_status_attributes(
        sensor_key: str,
        evidence_mapping: dict[str, object],
    ) -> None:
        attributes = CircuitAnalyzerSensor(
            coordinator,
            entry_id="entry-1",
            circuit=circuit,
            description=descriptions[sensor_key],
        ).extra_state_attributes

        assert attributes is not None
        for key, value in evidence_mapping.items():
            assert attributes[key] == value
        assert attributes["raw_status"] == evidence_mapping["status"]
        assert attributes["status_label"] != evidence_mapping["status"]
        assert attributes["status_explanation"]

    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["readiness"],
    ).extra_state_attributes == readiness
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["learning_progress"],
    ).extra_state_attributes == progress
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["data_quality_checklist"],
    ).extra_state_attributes == checklist
    assert_status_attributes("energy_dashboard_status", energy_dashboard)
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["alert_evidence"],
    ).extra_state_attributes == evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["recent_activity"],
    ).extra_state_attributes == recent_activity
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["recent_activity_count"],
    ).extra_state_attributes == recent_activity
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["sensitivity"],
    ).extra_state_attributes == {"preset": "Quiet"}
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["daily_energy_usage"],
    ).extra_state_attributes == energy_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["energy_usage_share"],
    ).extra_state_attributes == energy_evidence
    assert_status_attributes("energy_usage_status", energy_evidence)
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["energy_goal_usage"],
    ).extra_state_attributes == energy_goal_evidence
    assert_status_attributes("energy_goal_status", energy_goal_evidence)
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["run_cycle_count"],
    ).extra_state_attributes == run_cycle_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["run_cycle_runtime"],
    ).extra_state_attributes == run_cycle_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["run_cycle_duty_cycle"],
    ).extra_state_attributes == run_cycle_evidence
    assert_status_attributes("run_cycle_status", run_cycle_evidence)
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["current_demand"],
    ).extra_state_attributes == demand_evidence_with_notice
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["peak_demand"],
    ).extra_state_attributes == demand_evidence_with_notice
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["demand_limit_usage"],
    ).extra_state_attributes == demand_evidence_with_notice
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["demand_peak_rank"],
    ).extra_state_attributes == demand_evidence_with_notice
    assert_status_attributes("demand_peak_status", demand_evidence_with_notice)
    assert_status_attributes("demand_status", demand_evidence_with_notice)
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["capacity_usage"],
    ).extra_state_attributes == capacity_evidence_with_notice
    assert_status_attributes("capacity_status", capacity_evidence_with_notice)
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["leg_imbalance"],
    ).extra_state_attributes == leg_imbalance_evidence
    assert_status_attributes("leg_imbalance_status", leg_imbalance_evidence)
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["metric_consistency_score"],
    ).extra_state_attributes == metric_consistency_evidence
    assert_status_attributes("metric_consistency_status", metric_consistency_evidence)
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["balance_power"],
    ).extra_state_attributes == balance_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["monitored_power"],
    ).extra_state_attributes == balance_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["monitored_coverage"],
    ).extra_state_attributes == balance_evidence
    assert_status_attributes("balance_status", balance_evidence)
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["solar_generation_power"],
    ).extra_state_attributes == solar_flow_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["solar_site_consumption_power"],
    ).extra_state_attributes == solar_flow_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["solar_grid_import_power"],
    ).extra_state_attributes == solar_flow_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["solar_grid_export_power"],
    ).extra_state_attributes == solar_flow_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["solar_self_consumption"],
    ).extra_state_attributes == solar_flow_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["solar_powered"],
    ).extra_state_attributes == solar_flow_evidence
    assert_status_attributes("solar_flow_status", solar_flow_evidence)
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["solar_surplus_power"],
    ).extra_state_attributes == solar_flow_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["solar_load_shift_power"],
    ).extra_state_attributes == solar_flow_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["solar_flexible_load_power"],
    ).extra_state_attributes == solar_load_shift_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["solar_flexible_load_coverage"],
    ).extra_state_attributes == solar_load_shift_evidence
    assert_status_attributes("solar_load_shift_status", solar_load_shift_evidence)
    assert_status_attributes("solar_surplus_status", solar_flow_evidence)
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["utility_comparison_difference"],
    ).extra_state_attributes == utility_comparison_evidence
    assert_status_attributes("utility_comparison_status", utility_comparison_evidence)
    assert_status_attributes("nilm_topology_status", nilm_topology_evidence)
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["billing_cycle_usage"],
    ).extra_state_attributes == billing_cycle_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["billing_cycle_forecast"],
    ).extra_state_attributes == billing_cycle_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["billing_cycle_budget_usage"],
    ).extra_state_attributes == billing_cycle_evidence
    assert_status_attributes("billing_cycle_status", billing_cycle_evidence)
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["cost_current_rate"],
    ).extra_state_attributes == cost_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["cost_cycle"],
    ).extra_state_attributes == cost_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["cost_cycle_forecast"],
    ).extra_state_attributes == cost_evidence
    assert_status_attributes("cost_status", cost_evidence)
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["always_on_power"],
    ).extra_state_attributes == standby_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["standby_threshold"],
    ).extra_state_attributes == standby_evidence
    assert_status_attributes("standby_status", standby_evidence)
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["always_on_limit_usage"],
    ).extra_state_attributes == standby_evidence


@pytest.mark.asyncio
async def test_sensor_setup_entry_adds_diagnostic_entities_without_ha() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.fridge_energy", SensorRole.ENERGY),),
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
        "entry-1_fridge_anomaly_score",
        "entry-1_fridge_last_event",
        "entry-1_fridge_health_summary",
        "entry-1_fridge_activity_summary",
        "entry-1_fridge_electrical_health",
        "entry-1_fridge_energy_summary",
        "entry-1_fridge_readiness",
        "entry-1_fridge_learning_progress",
        "entry-1_fridge_data_quality_checklist",
        "entry-1_fridge_energy_dashboard_status",
        "entry-1_fridge_alert_evidence",
        "entry-1_fridge_recent_activity",
        "entry-1_fridge_recent_activity_count",
        "entry-1_fridge_sensitivity",
        "entry-1_fridge_settings_suggestions",
        "entry-1_fridge_circuit_mode",
        "entry-1_fridge_power_flow",
        "entry-1_fridge_daily_energy_usage",
        "entry-1_fridge_energy_usage_share",
        "entry-1_fridge_energy_usage_status",
    ]
    setup_health = added_entities[0]
    assert setup_health.name == "CircuitSetup Energy Analyzer Setup Health"
    assert setup_health.suggested_object_id == (
        "circuitsetup_energy_analyzer_setup_health"
    )
    assert setup_health.native_value == "Add cumulative kWh source"
    assert setup_health.extra_state_attributes["blocking_issue_count"] == 1
    assert setup_health.extra_state_attributes["next_step"] == (
        "Add a cumulative kWh sensor to Kitchen Fridge"
    )
    assert not hasattr(setup_health, "device_info")
    assert added_entities[1].device_info["identifiers"] == {
        (DOMAIN, "entry-1_fridge")
    }
    assert not isinstance(added_entities[1].state, AnalyzerState)
    assert added_entities[1].coordinator_state is coordinator.data


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
    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        circuit_configs=(circuit,),
        store_data=FeatureStoreData(
            capacity_settings_by_circuit={"hvac": {"breaker_amps": 40.0}},
        ),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert {
        "entry-1_hvac_power_quality_score",
        "entry-1_hvac_reactive_power_drift",
        "entry-1_hvac_apparent_power_drift",
        "entry-1_hvac_power_factor_drift",
        "entry-1_hvac_run_cycle_count",
        "entry-1_hvac_current_demand",
        "entry-1_hvac_capacity_usage",
        "entry-1_hvac_leg_imbalance",
        "entry-1_hvac_metric_consistency_score",
    } <= unique_ids
    assert not {
        "entry-1_hvac_nilm_signature_count",
        "entry-1_hvac_balance_power",
        "entry-1_hvac_solar_generation_power",
        "entry-1_hvac_utility_comparison_difference",
        "entry-1_hvac_billing_cycle_usage",
        "entry-1_hvac_cost_cycle",
    } & unique_ids


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
    coordinator = SimpleNamespace(
        data=AnalyzerState(),
        circuit_configs=(circuit,),
        store_data=FeatureStoreData(
            capacity_settings_by_circuit={
                "car_charger": {"breaker_amps": 40.0, "warning_ratio": 0.8}
            },
        ),
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
        "entry-1_car_charger_leg_imbalance_status",
        "entry-1_car_charger_metric_consistency_score",
        "entry-1_car_charger_metric_consistency_status",
        "entry-1_car_charger_daily_energy_usage",
        "entry-1_car_charger_power_factor_drift",
    } <= unique_ids
    assert not {
        "entry-1_car_charger_run_cycle_count",
        "entry-1_car_charger_run_cycle_status",
        "entry-1_car_charger_standby_status",
        "entry-1_car_charger_nilm_signature_count",
        "entry-1_car_charger_balance_power",
    } & unique_ids


@pytest.mark.asyncio
async def test_sensor_setup_entry_adds_single_phase_metric_consistency() -> (
    None
):
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
    coordinator = SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,))
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert {
        "entry-1_pool_pump_metric_consistency_score",
        "entry-1_pool_pump_metric_consistency_status",
    } <= unique_ids
    assert not {
        "entry-1_pool_pump_leg_imbalance",
        "entry-1_pool_pump_leg_imbalance_status",
    } & unique_ids


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
    coordinator = SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,))
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    unique_ids = {entity.unique_id for entity in added_entities}
    assert {
        "entry-1_mains_nilm_signature_count",
        "entry-1_mains_balance_power",
    } <= unique_ids
    assert not {
        "entry-1_mains_leg_imbalance",
        "entry-1_mains_leg_imbalance_status",
    } & unique_ids


@pytest.mark.asyncio
async def test_sensor_setup_entry_materializes_selected_demo_source_entities() -> (
    None
):
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
    coordinator = SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,))
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
    assert by_entity_id[
        "sensor.cs_energy_analyzer_demo_pool_pump_active_power"
    ].device_class == "power"
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
    assert by_entity_id[
        "sensor.cs_energy_analyzer_demo_mains_l1_voltage"
    ].icon == "mdi:sine-wave"
    assert (
        by_entity_id["sensor.cs_energy_analyzer_demo_mains_l1_voltage"].native_value
        == 119.6
    )
    assert "sensor.cs_energy_analyzer_demo_pool_pump_voltage" not in by_entity_id
    assert getattr(
        by_entity_id["sensor.cs_energy_analyzer_demo_mains_l1_voltage"],
        "device_info",
        None,
    ) is None


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
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_washer_active_power"
        ].native_value
        == 420.0
    )
    assert (
        by_entity_id["sensor.cs_energy_analyzer_demo_washer_current"].native_value
        == 4.2
    )
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_washer_power_factor"
        ].native_value
        == 0.83
    )
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_washer_reactive_power"
        ].native_value
        == 280.0
    )
    assert by_entity_id[
        "sensor.cs_energy_analyzer_demo_dryer_l1_energy"
    ].native_value == 63.7
    assert by_entity_id[
        "sensor.cs_energy_analyzer_demo_dryer_l2_energy"
    ].native_value == 63.1
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
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_dryer_l1_current"
        ].native_value
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
    coordinator = SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,))
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
    coordinator = SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,))
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
async def test_sensor_setup_entry_adds_mains_nilm_entities_only() -> None:
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
    coordinator = SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,))
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
    } <= unique_ids
    assert not {
        "entry-1_mains_run_cycle_count",
        "entry-1_mains_daily_energy_usage",
        "entry-1_mains_standby_status",
        "entry-1_mains_billing_cycle_usage",
        "entry-1_mains_cost_cycle",
    } & unique_ids


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
    coordinator = SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,))
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
async def test_binary_sensor_setup_entry_adds_diagnostic_entities_without_ha() -> None:
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

    assert [entity.name for entity in added_entities] == [
        "Well Pump Learning",
        "Well Pump Data Quality Problem",
        "Well Pump Maintenance",
    ]
    assert [entity.unique_id for entity in added_entities] == [
        "entry-1_well_pump_learning",
        "entry-1_well_pump_data_quality_problem",
        "entry-1_well_pump_maintenance",
    ]


@pytest.mark.asyncio
async def test_binary_sensor_setup_entry_adds_appliance_running_entities() -> None:
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

    running_entities = {
        entity.circuit_id: entity
        for entity in added_entities
        if entity.entity_description.key == "running"
    }
    assert set(running_entities) == {"washer", "dryer", "refrigerator", "microwave"}
    assert running_entities["washer"].name == "Washer Running"
    assert running_entities["dryer"].name == "Dryer Running"
    assert running_entities["refrigerator"].name == "Refrigerator Running"
    assert running_entities["microwave"].name == "Microwave Running"
    assert running_entities["washer"].is_on is True
    assert running_entities["dryer"].is_on is False
    assert running_entities["refrigerator"].is_on is True
    assert running_entities["microwave"].is_on is True
    assert {entity.unique_id for entity in running_entities.values()} == {
        "entry-1_washer_running",
        "entry-1_dryer_running",
        "entry-1_refrigerator_running",
        "entry-1_microwave_running",
    }


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

    assert [entity.circuit_id for entity in added_entities] == [
        "mains",
        "mains",
        "mains",
    ]


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
            options={CONF_WATER_FLOW_SENSOR_ENTITIES: ["sensor.water_flow_rate"]},
            entry_data={},
        ),
    )

    assert "entry-1_washer_water_flow_mismatch" not in without_flow
    assert "entry-1_washer_water_flow_mismatch" in with_flow
