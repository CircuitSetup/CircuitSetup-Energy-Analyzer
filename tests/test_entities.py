from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_CIRCUITS,
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


def test_sensor_helpers_return_diagnostic_values_and_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
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
        energy_dashboard_status_value,
        energy_goal_status_value,
        energy_goal_usage_value,
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
        nilm_unmatched_load_percentage_value,
        peak_demand_value,
        power_flow_value,
        power_factor_drift_value,
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
        recent_activity_by_circuit={"fridge": "Possible issue: cycle duration"},
        recent_activity_count_by_circuit={"fridge": 2},
        recent_activity_timeline_by_circuit={
            "fridge": {
                "status": "activity",
                "items": [{"title": "Possible issue: cycle duration"}],
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
    assert health_summary_value(state, "fridge") == "Possible issue"
    assert readiness_value(state, "fridge") == "possible_issue"
    assert learning_progress_value(state, "fridge") == 62.5
    assert learning_progress_value(state, "ready") == 100.0
    assert data_quality_checklist_value(state, "fridge") == "ok"
    assert data_quality_checklist_value(state, "well_pump") == "problem"
    assert energy_dashboard_status_value(state, "fridge") == "ready"
    assert alert_evidence_value(state, "fridge") == "reactive_power"
    assert recent_activity_value(state, "fridge") == "Possible issue: cycle duration"
    assert recent_activity_count_value(state, "fridge") == 2
    assert sensitivity_value(state, "fridge") == "quiet"
    assert circuit_mode_value(state, "fridge") == "Dual Phase"
    assert power_flow_value(state, "fridge") == "Generation / Solar Export"
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
    assert health_summary_value(state, "unknown") == "Ready"
    assert readiness_value(state, "unknown") == "ready"
    assert learning_progress_value(state, "unknown") == 0.0
    assert data_quality_checklist_value(state, "unknown") == "problem"
    assert energy_dashboard_status_value(state, "unknown") == "needs_energy_source"
    assert alert_evidence_value(state, "unknown") == ""
    assert recent_activity_value(state, "unknown") == "No recent activity"
    assert recent_activity_count_value(state, "unknown") == 0
    assert sensitivity_value(state, "unknown") == "balanced"
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


def test_binary_sensor_helpers_return_diagnostic_values_and_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        has_data_quality_problem,
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
    assert (
        is_laundry_appliance_running(state, "washer", ApplianceProfile.WASHER)
        is True
    )
    assert is_laundry_appliance_running(state, "dryer", ApplianceProfile.DRYER) is True
    assert (
        is_laundry_appliance_running(state, "washer", ApplianceProfile.REFRIGERATOR)
        is False
    )


def test_sensor_descriptions_include_home_assistant_entity_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
    )

    required_attrs = {
        "device_class",
        "entity_category",
        "entity_registry_enabled_default",
        "entity_registry_visible_default",
        "entity_picture",
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
        assert description.entity_registry_enabled_default is True
        assert description.last_reset is None
        assert description.options is None
        assert description.unit_of_measurement is None


def test_sensor_entities_use_purpose_specific_icons() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        CircuitAnalyzerSensor,
    )

    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    coordinator = SimpleNamespace(data=AnalyzerState())
    circuit = SimpleNamespace(circuit_id="fridge", name="Kitchen Fridge")

    expected_icons = {
        "health_summary": "mdi:heart-pulse",
        "learning_progress": "mdi:school-outline",
        "circuit_mode": "mdi:transmission-tower",
        "power_flow": "mdi:swap-horizontal",
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


def test_binary_sensor_descriptions_include_home_assistant_entity_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        BINARY_SENSOR_DESCRIPTIONS,
    )

    required_attrs = {
        "device_class",
        "entity_category",
        "entity_registry_enabled_default",
        "entity_registry_visible_default",
        "entity_picture",
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
        assert description.entity_registry_enabled_default is True
        assert description.unit_of_measurement is None


def test_binary_sensor_entities_use_purpose_specific_icons() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        BINARY_SENSOR_DESCRIPTIONS,
        CircuitAnalyzerBinarySensor,
    )

    descriptions = {
        description.key: description for description in BINARY_SENSOR_DESCRIPTIONS
    }
    coordinator = SimpleNamespace(data=AnalyzerState())
    circuit = SimpleNamespace(circuit_id="fridge", name="Kitchen Fridge")

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
        "items": [{"title": "Possible issue: cycle duration"}],
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
    circuit = SimpleNamespace(circuit_id="fridge", name="Kitchen Fridge")
    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}

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
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["energy_dashboard_status"],
    ).extra_state_attributes == energy_dashboard
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
    ).extra_state_attributes == {"preset": "quiet"}
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
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["energy_usage_status"],
    ).extra_state_attributes == energy_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["energy_goal_usage"],
    ).extra_state_attributes == energy_goal_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["energy_goal_status"],
    ).extra_state_attributes == energy_goal_evidence
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
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["run_cycle_status"],
    ).extra_state_attributes == run_cycle_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["current_demand"],
    ).extra_state_attributes == demand_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["peak_demand"],
    ).extra_state_attributes == demand_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["demand_limit_usage"],
    ).extra_state_attributes == demand_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["demand_peak_rank"],
    ).extra_state_attributes == demand_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["demand_peak_status"],
    ).extra_state_attributes == demand_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["demand_status"],
    ).extra_state_attributes == demand_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["capacity_usage"],
    ).extra_state_attributes == capacity_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["capacity_status"],
    ).extra_state_attributes == capacity_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["leg_imbalance"],
    ).extra_state_attributes == leg_imbalance_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["leg_imbalance_status"],
    ).extra_state_attributes == leg_imbalance_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["metric_consistency_score"],
    ).extra_state_attributes == metric_consistency_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["metric_consistency_status"],
    ).extra_state_attributes == metric_consistency_evidence
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
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["balance_status"],
    ).extra_state_attributes == balance_evidence
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
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["solar_flow_status"],
    ).extra_state_attributes == solar_flow_evidence
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
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["solar_load_shift_status"],
    ).extra_state_attributes == solar_load_shift_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["solar_surplus_status"],
    ).extra_state_attributes == solar_flow_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["utility_comparison_difference"],
    ).extra_state_attributes == utility_comparison_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["utility_comparison_status"],
    ).extra_state_attributes == utility_comparison_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["nilm_topology_status"],
    ).extra_state_attributes == nilm_topology_evidence
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
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["billing_cycle_status"],
    ).extra_state_attributes == billing_cycle_evidence
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
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["cost_status"],
    ).extra_state_attributes == cost_evidence
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
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["standby_status"],
    ).extra_state_attributes == standby_evidence
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
    coordinator = SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,))
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    assert [entity.unique_id for entity in added_entities] == [
        "entry-1_fridge_anomaly_score",
        "entry-1_fridge_last_event",
        "entry-1_fridge_health_summary",
        "entry-1_fridge_readiness",
        "entry-1_fridge_learning_progress",
        "entry-1_fridge_data_quality_checklist",
        "entry-1_fridge_energy_dashboard_status",
        "entry-1_fridge_alert_evidence",
        "entry-1_fridge_recent_activity",
        "entry-1_fridge_recent_activity_count",
        "entry-1_fridge_sensitivity",
        "entry-1_fridge_circuit_mode",
        "entry-1_fridge_power_flow",
        "entry-1_fridge_daily_energy_usage",
        "entry-1_fridge_energy_usage_share",
        "entry-1_fridge_energy_usage_status",
    ]
    assert added_entities[0].device_info["identifiers"] == {
        (DOMAIN, "entry-1_fridge")
    }
    assert not isinstance(added_entities[0].state, AnalyzerState)
    assert added_entities[0].coordinator_state is coordinator.data


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
        == 3600.0
    )
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_car_charger_l2_active_power"
        ].native_value
        == 3580.0
    )
    assert (
        by_entity_id[
            "sensor.cs_energy_analyzer_demo_car_charger_l1_current"
        ].native_value
        == 30.1
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
        == 320.0
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
async def test_binary_sensor_setup_entry_adds_laundry_running_entities() -> None:
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
    state = AnalyzerState(
        latest_real_power_w_by_circuit={
            "washer": 35.0,
            "dryer": 70.0,
            "refrigerator": 180.0,
        }
    )
    coordinator = SimpleNamespace(
        data=state,
        circuit_configs=(washer, dryer, refrigerator),
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
    assert set(running_entities) == {"washer", "dryer"}
    assert running_entities["washer"].name == "Washer Running"
    assert running_entities["dryer"].name == "Dryer Running"
    assert running_entities["washer"].is_on is True
    assert running_entities["dryer"].is_on is False
    assert {entity.unique_id for entity in running_entities.values()} == {
        "entry-1_washer_running",
        "entry-1_dryer_running",
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
