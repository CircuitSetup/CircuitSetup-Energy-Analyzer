from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.circuitsetup_energy_analyzer.const import CONF_ADVANCED_SETTINGS
from custom_components.circuitsetup_energy_analyzer.managers import (
    settings_controller,
)
from custom_components.circuitsetup_energy_analyzer.settings_advisor import (
    RecommendationStatus,
    SettingRecommendation,
)


def _recommendation(**overrides: Any) -> SettingRecommendation:
    values = {
        "recommendation_id": "fridge:daily_spike_ratio:v1",
        "unique_key": "fridge:daily_spike_ratio",
        "circuit_id": "fridge",
        "circuit_name": "Kitchen Fridge",
        "setting_key": "daily_spike_ratio",
        "setting_label": "Daily Spike Ratio",
        "current_value": 0.25,
        "suggested_value": 0.35,
        "unit": "ratio",
        "feature": "energy_usage_spikes",
        "group": "Energy Usage",
        "confidence": 0.82,
        "reason": "Observed daily variation.",
        "evidence": {"observed_days": 14},
        "apply_payload": {"daily_spike_ratio": 0.35},
        "status": RecommendationStatus.PENDING,
        "created_at": datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        "expires_at": datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return SettingRecommendation(**values)


class _SettingsCoordinator:
    def __init__(self, recommendation: SettingRecommendation) -> None:
        self.state = SimpleNamespace()
        self.entry_data = {
            CONF_ADVANCED_SETTINGS: {
                "fridge": {
                    "preset": "quiet",
                    "daily_spike_ratio": 0.2,
                    "option_only": "from_entry",
                }
            }
        }
        self.store_data = SimpleNamespace(
            settings_recommendations={
                recommendation.recommendation_id: recommendation
            },
            settings_recommendation_decisions={},
            sensitivity_by_circuit={},
            energy_usage_settings_by_circuit={
                "fridge": {"daily_spike_ratio": 0.25}
            },
            energy_goal_settings_by_circuit={},
            activity_alert_settings_by_circuit={},
            billing_settings_by_circuit={},
            cost_settings_by_circuit={},
            demand_settings_by_circuit={},
            capacity_settings_by_circuit={},
            utility_comparison_settings_by_circuit={},
            standby_settings_by_circuit={},
            leg_imbalance_settings_by_circuit={},
            metric_consistency_settings_by_circuit={},
            balance_settings_by_circuit={},
            solar_flow_settings_by_circuit={},
            operating_detection_settings_by_circuit={},
        )
        self.options = {
            CONF_ADVANCED_SETTINGS: {"fridge": {"daily_spike_ratio": 0.25}}
        }
        self.now = datetime(2026, 6, 30, 12, 5, tzinfo=UTC)
        self.persist_count = 0
        self.dirty_count = 0
        self.refreshed_recommendations: list[datetime] = []
        self.refreshed_circuits: list[tuple[str, datetime]] = []
        self.updated: list[object] = []
        self.saved: list[datetime] = []
        self.notified = 0
        self.rebuild_calls: list[tuple[datetime, str | None]] = []
        self.goal_context = SimpleNamespace(name="goal_context")
        self.goal_result = SimpleNamespace(name="goal_result")
        self.energy_goal_refreshes: list[
            tuple[str, SimpleNamespace, SimpleNamespace]
        ] = []
        self.context_calls: list[datetime] = []
        self.applied_feature_results: list[SimpleNamespace] = []
        self._energy_goal_processor = SimpleNamespace(
            refresh_state=self._refresh_energy_goal_state
        )

    def _now_fn(self) -> datetime:
        return self.now

    async def _async_persist_config_entry_options(self) -> None:
        self.persist_count += 1

    def _mark_store_dirty(self) -> None:
        self.dirty_count += 1

    def _refresh_settings_recommendation_state(self, now: datetime) -> None:
        self.refreshed_recommendations.append(now)

    def _refresh_ux_state_for_circuit(self, circuit_id: str, now: datetime) -> None:
        self.refreshed_circuits.append((circuit_id, now))

    def async_set_updated_data(self, state: object) -> None:
        self.updated.append(state)

    async def _async_save_store(self, now: datetime) -> None:
        self.saved.append(now)

    async def _notify_settings_recommendations_if_needed(self) -> None:
        self.notified += 1

    def _rebuild_setting_recommendations(
        self,
        now: datetime,
        *,
        circuit_id: str | None = None,
    ) -> bool:
        self.rebuild_calls.append((now, circuit_id))
        return True

    def _config_for_circuit(self, circuit_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            circuit_id=circuit_id,
            energy_usage_window_days=7,
            daily_energy_spike_ratio=0.25,
            daily_energy_goal_kwh=None,
            energy_goal_alert_ratio=1.0,
            billing_cycle_start_day=1,
            billing_cycle_budget_kwh=None,
            billing_cycle_budget_alert_ratio=1.0,
            billing_cycle_min_elapsed_days=3,
            cost_cycle_start_day=1,
            default_rate_per_kwh=None,
            tou_rate_per_kwh=None,
            tou_start="",
            tou_end="",
            tou_weekdays=(),
            tou_name="Peak",
            demand_window_minutes=15,
            demand_limit_w=None,
            standby_window_hours=12,
            standby_threshold_w=5.0,
            always_on_alert_w=None,
            standby_min_samples=24,
        )

    def _build_processing_context(self, now: datetime) -> SimpleNamespace:
        self.context_calls.append(now)
        return self.goal_context

    def _refresh_energy_goal_state(
        self,
        circuit_id: str,
        config: SimpleNamespace,
        context: SimpleNamespace,
    ) -> SimpleNamespace:
        self.energy_goal_refreshes.append((circuit_id, config, context))
        return self.goal_result

    async def _apply_feature_result(self, result: SimpleNamespace) -> None:
        self.applied_feature_results.append(result)


@pytest.mark.asyncio
async def test_settings_controller_applies_undoes_and_resets_recommendation() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_apply_setting_recommendation(
        recommendation.recommendation_id,
    )
    applied = coordinator.store_data.settings_recommendations[
        recommendation.recommendation_id
    ]
    undo_result = await controller.async_undo_setting_recommendation(
        recommendation.recommendation_id,
    )
    reset_result = await controller.async_reset_setting_recommendation(
        recommendation.recommendation_id,
    )

    assert applied.status is RecommendationStatus.APPLIED
    assert undo_result is True
    assert reset_result is True
    assert coordinator.options[CONF_ADVANCED_SETTINGS]["fridge"] == {
        "daily_spike_ratio": 0.25
    }
    assert coordinator.store_data.energy_usage_settings_by_circuit["fridge"] == {
        "daily_spike_ratio": 0.25
    }
    assert coordinator.persist_count == 3
    assert coordinator.dirty_count == 3
    assert coordinator.updated == [
        coordinator.state,
        coordinator.state,
        coordinator.state,
    ]


@pytest.mark.asyncio
async def test_settings_controller_recalculates_and_records_decisions() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_recalculate_setting_recommendations("fridge")
    await controller.async_dismiss_setting_recommendation(
        recommendation.recommendation_id,
    )

    assert coordinator.rebuild_calls == [(coordinator.now, "fridge")]
    assert coordinator.dirty_count == 2
    assert coordinator.saved == [coordinator.now, coordinator.now]
    assert coordinator.notified == 1
    assert (
        coordinator.store_data.settings_recommendations[
            recommendation.recommendation_id
        ].status
        is RecommendationStatus.DISMISSED
    )
    decision = coordinator.store_data.settings_recommendation_decisions[
        recommendation.unique_key
    ]
    assert decision.status is RecommendationStatus.DISMISSED
    assert decision.denied_value == recommendation.suggested_value
    assert coordinator.refreshed_recommendations[-1] == coordinator.now


def test_settings_controller_writes_recommendation_setting_values() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    controller.set_recommendation_setting_value(
        "fridge",
        "daily_spike_ratio",
        0.35,
    )
    controller.set_recommendation_setting_value(
        "fridge",
        "daily_spike_ratio",
        None,
    )

    assert coordinator.options[CONF_ADVANCED_SETTINGS] == {}
    assert coordinator.store_data.energy_usage_settings_by_circuit == {}


def test_settings_controller_replaces_advanced_settings() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    controller.replace_advanced_settings(
        "fridge",
        {
            "preset": "sensitive",
            "daily_spike_ratio": 0.4,
            "min_samples": 12,
            "leg_imbalance_warning_ratio": 0.35,
            "leg_imbalance_min_total_power_w": 700.0,
            "balance_negative_tolerance_w": 250.0,
            "solar_export_tolerance_w": 120.0,
        },
    )

    assert coordinator.store_data.sensitivity_by_circuit["fridge"] == "sensitive"
    assert coordinator.store_data.energy_usage_settings_by_circuit["fridge"] == {
        "daily_spike_ratio": 0.4
    }
    assert coordinator.store_data.standby_settings_by_circuit["fridge"] == {
        "min_samples": 12
    }
    assert coordinator.store_data.leg_imbalance_settings_by_circuit["fridge"] == {
        "warning_ratio": 0.35,
        "minimum_total_power_w": 700.0,
    }
    assert coordinator.store_data.balance_settings_by_circuit["fridge"] == {
        "negative_tolerance_w": 250.0
    }
    assert coordinator.store_data.solar_flow_settings_by_circuit["fridge"] == {
        "export_tolerance_w": 120.0
    }


def test_settings_controller_clears_advanced_setting_aliases() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)
    coordinator.store_data.standby_settings_by_circuit["fridge"] = {
        "min_samples": 12
    }
    coordinator.store_data.leg_imbalance_settings_by_circuit["fridge"] = {
        "warning_ratio": 0.35,
        "minimum_total_power_w": 700.0,
    }
    coordinator.store_data.balance_settings_by_circuit["fridge"] = {
        "negative_tolerance_w": 250.0
    }
    coordinator.store_data.solar_flow_settings_by_circuit["fridge"] = {
        "export_tolerance_w": 120.0
    }

    controller.clear_advanced_setting_value("fridge", "standby_min_samples")
    controller.clear_advanced_setting_value("fridge", "leg_imbalance_warning_ratio")
    controller.clear_advanced_setting_value(
        "fridge",
        "leg_imbalance_min_total_power_w",
    )
    controller.clear_advanced_setting_value("fridge", "balance_negative_tolerance_w")
    controller.clear_advanced_setting_value("fridge", "solar_export_tolerance_w")

    assert "fridge" not in coordinator.store_data.standby_settings_by_circuit
    assert "fridge" not in coordinator.store_data.leg_imbalance_settings_by_circuit
    assert "fridge" not in coordinator.store_data.balance_settings_by_circuit
    assert "fridge" not in coordinator.store_data.solar_flow_settings_by_circuit


@pytest.mark.asyncio
async def test_settings_controller_async_replaces_advanced_settings() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_replace_advanced_settings(
        "fridge",
        {"daily_spike_ratio": 0.4},
    )

    assert coordinator.options[CONF_ADVANCED_SETTINGS]["fridge"] == {
        "daily_spike_ratio": 0.4
    }
    assert coordinator.store_data.energy_usage_settings_by_circuit["fridge"] == {
        "daily_spike_ratio": 0.4
    }
    assert coordinator.dirty_count == 1
    assert coordinator.refreshed_circuits == [("fridge", coordinator.now)]
    assert coordinator.updated == [coordinator.state]
    assert coordinator.saved == [coordinator.now]


def test_settings_controller_reads_advanced_settings_for_circuit() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)
    coordinator.store_data.standby_settings_by_circuit["fridge"] = {
        "min_samples": 12
    }
    coordinator.store_data.leg_imbalance_settings_by_circuit["fridge"] = {
        "warning_ratio": 0.35,
        "minimum_total_power_w": 700.0,
    }
    coordinator.store_data.balance_settings_by_circuit["fridge"] = {
        "negative_tolerance_w": 250.0
    }
    coordinator.store_data.solar_flow_settings_by_circuit["fridge"] = {
        "export_tolerance_w": 120.0,
        "solar_surplus_threshold_w": 500.0,
    }

    settings = controller.advanced_settings_for_circuit("fridge")

    assert settings["preset"] == "quiet"
    assert settings["option_only"] == "from_entry"
    assert settings["daily_spike_ratio"] == 0.25
    assert settings["min_samples"] == 12
    assert settings["leg_imbalance_warning_ratio"] == 0.35
    assert settings["leg_imbalance_min_total_power_w"] == 700.0
    assert settings["balance_negative_tolerance_w"] == 250.0
    assert settings["solar_export_tolerance_w"] == 120.0
    assert settings["solar_surplus_threshold_w"] == 500.0


@pytest.mark.asyncio
async def test_settings_controller_sets_threshold_settings() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_set_leg_imbalance_settings("hvac", 0.4, 800.0)
    await controller.async_set_metric_consistency_settings("hvac", 12.0, 0.08, 120.0)
    await controller.async_set_mains_balance_settings("mains", 250.0)
    await controller.async_set_solar_flow_settings(
        "mains",
        100.0,
        500.0,
        1200.0,
        350.0,
    )

    assert coordinator.store_data.leg_imbalance_settings_by_circuit["hvac"] == {
        "warning_ratio": 0.4,
        "minimum_total_power_w": 800.0,
    }
    assert coordinator.store_data.metric_consistency_settings_by_circuit["hvac"] == {
        "apparent_power_tolerance_percent": 12.0,
        "power_factor_tolerance": 0.08,
        "minimum_apparent_power_va": 120.0,
    }
    assert coordinator.store_data.balance_settings_by_circuit["mains"] == {
        "negative_tolerance_w": 250.0
    }
    assert coordinator.store_data.solar_flow_settings_by_circuit["mains"] == {
        "export_tolerance_w": 100.0,
        "solar_surplus_threshold_w": 500.0,
        "high_solar_surplus_threshold_w": 1200.0,
        "flexible_load_running_threshold_w": 350.0,
    }
    assert coordinator.dirty_count == 4
    assert coordinator.refreshed_circuits == [
        ("hvac", coordinator.now),
        ("hvac", coordinator.now),
        ("mains", coordinator.now),
        ("mains", coordinator.now),
    ]
    assert coordinator.updated == [coordinator.state] * 4
    assert coordinator.saved == [coordinator.now] * 4


@pytest.mark.asyncio
async def test_settings_controller_sets_usage_and_load_settings() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_set_energy_usage_settings("fridge", 14, 0.2)
    await controller.async_set_demand_settings("fridge", 30, 4500.0)
    await controller.async_set_capacity_settings("fridge", 20.0, 0.8)
    await controller.async_set_standby_settings("fridge", 24, 8.0, 25.0)

    assert coordinator.store_data.energy_usage_settings_by_circuit["fridge"] == {
        "window_days": 14,
        "daily_spike_ratio": 0.2,
    }
    assert coordinator.store_data.demand_settings_by_circuit["fridge"] == {
        "window_minutes": 30,
        "demand_limit_w": 4500.0,
    }
    assert coordinator.store_data.capacity_settings_by_circuit["fridge"] == {
        "warning_ratio": 0.8,
        "breaker_amps": 20.0,
    }
    assert coordinator.store_data.standby_settings_by_circuit["fridge"] == {
        "window_hours": 24,
        "standby_threshold_w": 8.0,
        "always_on_alert_w": 25.0,
    }
    assert coordinator.dirty_count == 4
    assert coordinator.refreshed_circuits == [("fridge", coordinator.now)] * 4
    assert coordinator.updated == [coordinator.state] * 4
    assert coordinator.saved == [coordinator.now] * 4


@pytest.mark.asyncio
async def test_settings_controller_sets_billing_cost_and_utility_settings() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_set_billing_cycle_settings("fridge", 15, 300.0, 0.9)
    await controller.async_set_cost_settings(
        "fridge",
        1,
        0.20,
        0.30,
        "17:00",
        "21:00",
        "0,1,2,3,4",
        "Peak",
    )
    await controller.async_set_utility_comparison_settings(
        "mains",
        utility_energy_entity="sensor.opower_current_bill_usage",
        utility_statistic_id="opower:utility_elec_consumption",
        utility_source_type="auto",
        utility_statistic_period="day",
        measured_energy_entities=["sensor.panel_import_energy"],
        tolerance_percent=8.5,
    )

    assert coordinator.store_data.billing_settings_by_circuit["fridge"] == {
        "cycle_start_day": 15,
        "budget_kwh": 300.0,
        "budget_alert_ratio": 0.9,
    }
    assert coordinator.store_data.cost_settings_by_circuit["fridge"] == {
        "cycle_start_day": 1,
        "default_rate_per_kwh": 0.20,
        "tou_rate_per_kwh": 0.30,
        "tou_start": "17:00",
        "tou_end": "21:00",
        "tou_weekdays": "0,1,2,3,4",
        "tou_name": "Peak",
    }
    assert coordinator.store_data.utility_comparison_settings_by_circuit["mains"] == {
        "utility_energy_entity": "sensor.opower_current_bill_usage",
        "utility_statistic_id": "opower:utility_elec_consumption",
        "utility_source_type": "auto",
        "utility_statistic_period": "day",
        "measured_energy_entities": ["sensor.panel_import_energy"],
        "tolerance_percent": 8.5,
    }
    assert coordinator.dirty_count == 3
    assert coordinator.refreshed_circuits == [
        ("fridge", coordinator.now),
        ("fridge", coordinator.now),
        ("mains", coordinator.now),
    ]
    assert coordinator.updated == [coordinator.state] * 3
    assert coordinator.saved == [coordinator.now] * 3


@pytest.mark.asyncio
async def test_settings_controller_sets_goal_and_activity_settings() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_set_energy_goal_settings("fridge", 12.0, 1.0)
    await controller.async_set_activity_alert_settings("fridge", 45.0, 120.0)

    assert coordinator.store_data.energy_goal_settings_by_circuit["fridge"] == {
        "daily_goal_kwh": 12.0,
        "goal_alert_ratio": 1.0,
    }
    assert coordinator.store_data.activity_alert_settings_by_circuit["fridge"] == {
        "max_active_minutes": 45.0,
        "max_idle_minutes": 120.0,
    }
    assert coordinator.context_calls == [coordinator.now]
    assert coordinator.applied_feature_results == [coordinator.goal_result]
    assert len(coordinator.energy_goal_refreshes) == 1
    circuit_id, config, context = coordinator.energy_goal_refreshes[0]
    assert circuit_id == "fridge"
    assert config.circuit_id == "fridge"
    assert context is coordinator.goal_context
    assert coordinator.dirty_count == 2
    assert coordinator.refreshed_circuits == [("fridge", coordinator.now)] * 2
    assert coordinator.updated == [coordinator.state] * 2
    assert coordinator.saved == [coordinator.now] * 2


@pytest.mark.asyncio
async def test_settings_controller_sets_circuit_sensitivity() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)

    await controller.async_set_circuit_sensitivity("fridge", "high")

    assert coordinator.store_data.sensitivity_by_circuit["fridge"] == "sensitive"
    assert coordinator.dirty_count == 1
    assert coordinator.refreshed_circuits == [("fridge", coordinator.now)]
    assert coordinator.updated == [coordinator.state]
    assert coordinator.saved == [coordinator.now]


def test_settings_controller_reads_runtime_setting_defaults() -> None:
    recommendation = _recommendation()
    coordinator = _SettingsCoordinator(recommendation)
    controller = settings_controller.SettingsController(coordinator)
    config = SimpleNamespace(
        energy_usage_window_days=7,
        daily_energy_spike_ratio=0.25,
        daily_energy_goal_kwh=2.5,
        energy_goal_alert_ratio=0.9,
        billing_cycle_start_day=15,
        billing_cycle_budget_kwh=90.0,
        billing_cycle_budget_alert_ratio=0.85,
        billing_cycle_min_elapsed_days=5,
        cost_cycle_start_day=10,
        default_rate_per_kwh=0.18,
        tou_rate_per_kwh=0.35,
        tou_start="16:00",
        tou_end="20:00",
        tou_weekdays=(0, 1, 2, 3, 4),
        tou_name="Peak",
        demand_window_minutes=30,
        demand_limit_w=1200.0,
        standby_window_hours=72,
        standby_threshold_w=6.0,
        always_on_alert_w=12.0,
        standby_min_samples=36,
    )
    coordinator.store_data.activity_alert_settings_by_circuit["fridge"] = {
        "max_active_minutes": "45"
    }
    coordinator.store_data.energy_usage_settings_by_circuit["fridge"] = {
        "window_days": "14",
        "daily_spike_ratio": "0.35",
    }
    coordinator.store_data.billing_settings_by_circuit["fridge"] = {
        "budget_kwh": "95.0"
    }
    coordinator.store_data.cost_settings_by_circuit["fridge"] = {
        "tou_weekdays": "1,3,5",
        "tou_name": "Critical Peak",
    }
    coordinator.store_data.demand_settings_by_circuit["fridge"] = {
        "demand_limit_w": "1500"
    }
    coordinator.store_data.capacity_settings_by_circuit["fridge"] = {
        "breaker_amps": "20",
        "warning_ratio": "0.75",
    }
    coordinator.store_data.standby_settings_by_circuit["fridge"] = {
        "always_on_alert_w": "15"
    }
    coordinator.store_data.utility_comparison_settings_by_circuit["fridge"] = {
        "utility_energy_entity": "sensor.utility_energy",
        "measured_energy_entities": "sensor.panel_energy,sensor.solar_energy",
        "utility_statistic_period": "hour",
        "tolerance_percent": "8.5",
    }

    assert (
        controller.activity_alert_settings_for_config(
            config,
            "fridge",
        ).max_active_minutes
        == 45.0
    )
    assert (
        controller.activity_alert_settings_for_config(config, "fridge").max_idle_minutes
        is None
    )
    energy_usage = controller.energy_usage_settings_for_config(config, "fridge")
    assert energy_usage.window_days == 14
    assert energy_usage.daily_spike_ratio == 0.35
    energy_goal = controller.energy_goal_settings_for_config(config, "fridge")
    assert energy_goal.daily_goal_kwh == 2.5
    assert energy_goal.goal_alert_ratio == 0.9
    billing = controller.billing_cycle_settings_for_config(config, "fridge")
    assert billing.cycle_start_day == 15
    assert billing.budget_kwh == 95.0
    assert billing.budget_alert_ratio == 0.85
    assert billing.min_elapsed_days == 5
    cost = controller.cost_settings_for_config(config, "fridge")
    assert cost.cycle_start_day == 10
    assert cost.default_rate_per_kwh == 0.18
    assert cost.tou_rate_per_kwh == 0.35
    assert cost.tou_weekdays == (1, 3, 5)
    assert cost.tou_name == "Critical Peak"
    demand = controller.demand_settings_for_config(config, "fridge")
    assert demand.window_minutes == 30
    assert demand.demand_limit_w == 1500.0
    capacity = controller.capacity_settings_for_config("fridge")
    assert capacity.breaker_amps == 20.0
    assert capacity.warning_ratio == 0.75
    standby = controller.standby_settings_for_config(config, "fridge")
    assert standby.window_hours == 72
    assert standby.standby_threshold_w == 6.0
    assert standby.always_on_alert_w == 15.0
    assert standby.min_samples == 36
    utility = controller.utility_comparison_settings_for_circuit("fridge")
    assert utility.utility_energy_entity == "sensor.utility_energy"
    assert utility.utility_statistic_period == "hour"
    assert utility.measured_energy_entities == (
        "sensor.panel_energy",
        "sensor.solar_energy",
    )
    assert utility.tolerance_percent == 8.5
