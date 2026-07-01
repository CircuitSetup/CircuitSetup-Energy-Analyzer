"""Advanced settings workflows for the coordinator."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import replace
from typing import Any

from ..balance import DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W
from ..const import CONF_ADVANCED_SETTINGS
from ..load_shift import FLEXIBLE_LOAD_RUNNING_THRESHOLD_W
from ..metric_consistency import (
    DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT,
    DEFAULT_MIN_APPARENT_POWER_VA,
    DEFAULT_POWER_FACTOR_TOLERANCE,
)
from ..operating_detection import (
    OPERATING_DETECTION_OVERRIDE_FIELDS,
    OPERATING_DETECTION_SOURCE,
    OperatingThresholdSource,
)
from ..phase_balance import (
    DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
    DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
)
from ..recommendation_guidance import recommendation_setting_default_value
from ..settings_advisor import (
    RecommendationDecision,
    RecommendationStatus,
    recommendation_evidence_fingerprint,
)
from ..solar_flow import (
    EXPORT_TOLERANCE_W,
    HIGH_SOLAR_SURPLUS_THRESHOLD_W,
    SOLAR_SURPLUS_THRESHOLD_W,
)
from ..ux import normalize_sensitivity


class SettingsController:
    """Own user-triggered advanced setting recommendation actions."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    async def async_recalculate_setting_recommendations(
        self,
        circuit_id: str | None = None,
    ) -> None:
        """Rebuild pending advanced-setting recommendations from retained data."""
        coordinator = self._coordinator
        now = coordinator._now_fn()
        if coordinator._rebuild_setting_recommendations(now, circuit_id=circuit_id):
            coordinator._mark_store_dirty()
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator._async_save_store(now)
        await coordinator._notify_settings_recommendations_if_needed()

    async def async_replace_advanced_settings(
        self,
        circuit_id: str,
        settings: Mapping[str, Any],
    ) -> None:
        """Replace store-backed advanced settings for one circuit."""
        coordinator = self._coordinator
        advanced_by_circuit = coordinator.options.setdefault(
            CONF_ADVANCED_SETTINGS,
            {},
        )
        if not isinstance(advanced_by_circuit, dict):
            advanced_by_circuit = dict(advanced_by_circuit)
            coordinator.options[CONF_ADVANCED_SETTINGS] = advanced_by_circuit
        updated_settings = dict(settings)
        advanced_by_circuit[circuit_id] = updated_settings
        self.replace_advanced_settings(circuit_id, updated_settings)
        coordinator._mark_store_dirty()
        now = coordinator._now_fn()
        coordinator._refresh_ux_state_for_circuit(circuit_id, now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator._async_save_store(now)

    async def async_set_circuit_sensitivity(
        self,
        circuit_id: str,
        preset: str,
    ) -> None:
        """Persist an alert sensitivity preset for one circuit."""
        await self._async_save_circuit_settings(
            circuit_id,
            self._coordinator.store_data.sensitivity_by_circuit,
            normalize_sensitivity(preset),
        )

    async def async_set_energy_usage_settings(
        self,
        circuit_id: str,
        window_days: Any = None,
        daily_spike_ratio: Any = None,
    ) -> None:
        """Persist daily energy usage spike settings for one circuit."""
        coordinator = self._coordinator
        config = coordinator._config_for_circuit(circuit_id)
        current = coordinator._energy_usage_settings_for_config(config, circuit_id)
        settings = {
            "window_days": _positive_int_value(
                window_days,
                default=current.window_days,
            ),
            "daily_spike_ratio": _positive_float_value(
                daily_spike_ratio,
                default=current.daily_spike_ratio,
            ),
        }
        await self._async_save_circuit_settings(
            circuit_id,
            coordinator.store_data.energy_usage_settings_by_circuit,
            settings,
        )

    async def async_set_energy_goal_settings(
        self,
        circuit_id: str,
        daily_goal_kwh: Any = None,
        goal_alert_ratio: Any = None,
    ) -> None:
        """Persist daily energy goal settings for one circuit."""
        coordinator = self._coordinator
        config = coordinator._config_for_circuit(circuit_id)
        current = coordinator._energy_goal_settings_for_config(config, circuit_id)
        settings: dict[str, Any] = {
            "goal_alert_ratio": _positive_float_value(
                goal_alert_ratio,
                default=current.goal_alert_ratio,
            ),
        }
        if daily_goal_kwh is None:
            if current.daily_goal_kwh is not None:
                settings["daily_goal_kwh"] = current.daily_goal_kwh
        else:
            goal_kwh = _optional_positive_float_value(
                daily_goal_kwh,
                default=None,
            )
            settings["daily_goal_kwh"] = goal_kwh if goal_kwh is not None else 0.0
        coordinator.store_data.energy_goal_settings_by_circuit[circuit_id] = settings
        coordinator._mark_store_dirty()
        now = coordinator._now_fn()
        goal_result = coordinator._energy_goal_processor.refresh_state(
            circuit_id,
            config,
            coordinator._build_processing_context(now),
        )
        await coordinator._apply_feature_result(goal_result)
        coordinator._refresh_ux_state_for_circuit(circuit_id, now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator._async_save_store(now)

    async def async_set_activity_alert_settings(
        self,
        circuit_id: str,
        max_active_minutes: Any = None,
        max_idle_minutes: Any = None,
    ) -> None:
        """Persist user-configured activity alert settings for one circuit."""
        coordinator = self._coordinator
        current = coordinator._activity_alert_settings_for_config(None, circuit_id)
        max_minutes = _optional_positive_float_value(
            max_active_minutes,
            default=current.max_active_minutes,
        )
        max_idle = _optional_positive_float_value(
            max_idle_minutes,
            default=current.max_idle_minutes,
        )
        settings: dict[str, Any] = {}
        if max_minutes is not None:
            settings["max_active_minutes"] = max_minutes
        if max_idle is not None:
            settings["max_idle_minutes"] = max_idle
        await self._async_save_circuit_settings(
            circuit_id,
            coordinator.store_data.activity_alert_settings_by_circuit,
            settings,
        )

    async def async_set_demand_settings(
        self,
        circuit_id: str,
        window_minutes: Any = None,
        demand_limit_w: Any = None,
    ) -> None:
        """Persist rolling demand settings for one circuit."""
        coordinator = self._coordinator
        config = coordinator._config_for_circuit(circuit_id)
        current = coordinator._demand_settings_for_config(config, circuit_id)
        settings: dict[str, Any] = {
            "window_minutes": _positive_int_value(
                window_minutes,
                default=current.window_minutes,
            ),
        }
        limit_w = _optional_positive_float_value(
            demand_limit_w,
            default=current.demand_limit_w,
        )
        if limit_w is not None:
            settings["demand_limit_w"] = limit_w
        await self._async_save_circuit_settings(
            circuit_id,
            coordinator.store_data.demand_settings_by_circuit,
            settings,
        )

    async def async_set_capacity_settings(
        self,
        circuit_id: str,
        breaker_amps: Any = None,
        warning_ratio: Any = None,
    ) -> None:
        """Persist circuit capacity settings for one circuit."""
        coordinator = self._coordinator
        current = coordinator._capacity_settings_for_config(circuit_id)
        settings: dict[str, Any] = {
            "warning_ratio": _positive_float_value(
                warning_ratio,
                default=current.warning_ratio,
            ),
        }
        capacity_amps = _optional_positive_float_value(
            breaker_amps,
            default=current.breaker_amps,
        )
        if capacity_amps is not None:
            settings["breaker_amps"] = capacity_amps
        await self._async_save_circuit_settings(
            circuit_id,
            coordinator.store_data.capacity_settings_by_circuit,
            settings,
        )

    async def async_set_standby_settings(
        self,
        circuit_id: str,
        window_hours: Any = None,
        standby_threshold_w: Any = None,
        always_on_alert_w: Any = None,
    ) -> None:
        """Persist Always On and standby settings for one circuit."""
        coordinator = self._coordinator
        config = coordinator._config_for_circuit(circuit_id)
        current = coordinator._standby_settings_for_config(config, circuit_id)
        settings: dict[str, Any] = {
            "window_hours": _positive_int_value(
                window_hours,
                default=current.window_hours,
            ),
            "standby_threshold_w": _positive_float_value(
                standby_threshold_w,
                default=current.standby_threshold_w,
            ),
        }
        alert_w = _optional_positive_float_value(
            always_on_alert_w,
            default=current.always_on_alert_w,
        )
        if alert_w is not None:
            settings["always_on_alert_w"] = alert_w
        await self._async_save_circuit_settings(
            circuit_id,
            coordinator.store_data.standby_settings_by_circuit,
            settings,
        )

    async def async_set_billing_cycle_settings(
        self,
        circuit_id: str,
        cycle_start_day: Any = None,
        budget_kwh: Any = None,
        budget_alert_ratio: Any = None,
    ) -> None:
        """Persist billing-cycle usage forecast settings for one circuit."""
        coordinator = self._coordinator
        config = coordinator._config_for_circuit(circuit_id)
        current = coordinator._billing_cycle_settings_for_config(config, circuit_id)
        settings: dict[str, Any] = {
            "cycle_start_day": _positive_int_value(
                cycle_start_day,
                default=current.cycle_start_day,
            ),
            "budget_alert_ratio": _positive_float_value(
                budget_alert_ratio,
                default=current.budget_alert_ratio,
            ),
        }
        budget = _optional_positive_float_value(
            budget_kwh,
            default=current.budget_kwh,
        )
        if budget is not None:
            settings["budget_kwh"] = budget
        await self._async_save_circuit_settings(
            circuit_id,
            coordinator.store_data.billing_settings_by_circuit,
            settings,
        )

    async def async_set_cost_settings(
        self,
        circuit_id: str,
        cycle_start_day: Any = None,
        default_rate_per_kwh: Any = None,
        tou_rate_per_kwh: Any = None,
        tou_start: Any = None,
        tou_end: Any = None,
        tou_weekdays: Any = None,
        tou_name: Any = None,
    ) -> None:
        """Persist cost and Time-of-Use settings for one circuit."""
        coordinator = self._coordinator
        config = coordinator._config_for_circuit(circuit_id)
        current = coordinator._cost_settings_for_config(config, circuit_id)
        settings: dict[str, Any] = {
            "cycle_start_day": _positive_int_value(
                cycle_start_day,
                default=current.cycle_start_day,
            ),
        }
        default_rate = _optional_positive_float_value(
            default_rate_per_kwh,
            default=current.default_rate_per_kwh,
        )
        tou_rate = _optional_positive_float_value(
            tou_rate_per_kwh,
            default=current.tou_rate_per_kwh,
        )
        if default_rate is not None:
            settings["default_rate_per_kwh"] = default_rate
        if tou_rate is not None:
            settings["tou_rate_per_kwh"] = tou_rate
        settings["tou_start"] = str(tou_start or current.tou_start or "")
        settings["tou_end"] = str(tou_end or current.tou_end or "")
        weekdays = _weekday_csv_value(
            tou_weekdays,
            default=current.tou_weekdays,
        )
        if weekdays:
            settings["tou_weekdays"] = weekdays
        settings["tou_name"] = str(tou_name or current.tou_name or "Peak")
        await self._async_save_circuit_settings(
            circuit_id,
            coordinator.store_data.cost_settings_by_circuit,
            settings,
        )

    async def async_set_utility_comparison_settings(
        self,
        circuit_id: str,
        utility_energy_entity: Any = None,
        measured_energy_entities: Any = None,
        tolerance_percent: Any = None,
        utility_statistic_id: Any = None,
        utility_source_type: Any = None,
        utility_statistic_period: Any = None,
    ) -> None:
        """Persist utility-vs-measured kWh comparison settings."""
        coordinator = self._coordinator
        current = coordinator._utility_comparison_settings_for_circuit(circuit_id)
        utility_entity = (
            current.utility_energy_entity
            if utility_energy_entity is None
            else str(utility_energy_entity).strip()
        )
        utility_statistic = (
            current.utility_statistic_id
            if utility_statistic_id is None
            else str(utility_statistic_id).strip()
        )
        source_type = (
            current.utility_source_type
            if utility_source_type is None
            else str(utility_source_type).strip()
        )
        statistic_period = (
            current.utility_statistic_period
            if utility_statistic_period is None
            else str(utility_statistic_period).strip()
        )
        measured_entities = _entity_id_tuple_value(
            measured_energy_entities,
            default=current.measured_energy_entities,
        )
        settings: dict[str, Any] = {
            "tolerance_percent": _nonnegative_float_value(
                tolerance_percent,
                default=current.tolerance_percent,
            ),
        }
        if utility_entity:
            settings["utility_energy_entity"] = utility_entity
        if utility_statistic:
            settings["utility_statistic_id"] = utility_statistic
        if source_type:
            settings["utility_source_type"] = source_type
        if statistic_period:
            settings["utility_statistic_period"] = statistic_period
        if measured_entities:
            settings["measured_energy_entities"] = list(measured_entities)
        await self._async_save_circuit_settings(
            circuit_id,
            coordinator.store_data.utility_comparison_settings_by_circuit,
            settings,
        )

    async def async_set_leg_imbalance_settings(
        self,
        circuit_id: str,
        warning_ratio: Any = None,
        minimum_total_power_w: Any = None,
    ) -> None:
        """Persist dual-phase leg imbalance thresholds for one circuit."""
        current = self._coordinator.store_data.leg_imbalance_settings_by_circuit.get(
            circuit_id,
            {},
        )
        settings = {
            "warning_ratio": _positive_float_value(
                warning_ratio,
                default=_positive_float_value(
                    current.get("warning_ratio"),
                    default=DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
                ),
            ),
            "minimum_total_power_w": _nonnegative_float_value(
                minimum_total_power_w,
                default=_nonnegative_float_value(
                    current.get("minimum_total_power_w"),
                    default=DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
                ),
            ),
        }
        await self._async_save_circuit_settings(
            circuit_id,
            self._coordinator.store_data.leg_imbalance_settings_by_circuit,
            settings,
        )

    async def async_set_metric_consistency_settings(
        self,
        circuit_id: str,
        apparent_power_tolerance_percent: Any = None,
        power_factor_tolerance: Any = None,
        minimum_apparent_power_va: Any = None,
    ) -> None:
        """Persist W/VA/PF consistency thresholds for one circuit."""
        current = (
            self._coordinator.store_data.metric_consistency_settings_by_circuit.get(
                circuit_id,
                {},
            )
        )
        settings = {
            "apparent_power_tolerance_percent": _positive_float_value(
                apparent_power_tolerance_percent,
                default=_positive_float_value(
                    current.get("apparent_power_tolerance_percent"),
                    default=DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT,
                ),
            ),
            "power_factor_tolerance": _positive_float_value(
                power_factor_tolerance,
                default=_positive_float_value(
                    current.get("power_factor_tolerance"),
                    default=DEFAULT_POWER_FACTOR_TOLERANCE,
                ),
            ),
            "minimum_apparent_power_va": _nonnegative_float_value(
                minimum_apparent_power_va,
                default=_nonnegative_float_value(
                    current.get("minimum_apparent_power_va"),
                    default=DEFAULT_MIN_APPARENT_POWER_VA,
                ),
            ),
        }
        await self._async_save_circuit_settings(
            circuit_id,
            self._coordinator.store_data.metric_consistency_settings_by_circuit,
            settings,
        )

    async def async_set_mains_balance_settings(
        self,
        circuit_id: str,
        negative_tolerance_w: Any = None,
    ) -> None:
        """Persist mains-minus-monitored balance thresholds."""
        current = self._coordinator.store_data.balance_settings_by_circuit.get(
            circuit_id,
            {},
        )
        settings = {
            "negative_tolerance_w": _nonnegative_float_value(
                negative_tolerance_w,
                default=_nonnegative_float_value(
                    current.get("negative_tolerance_w"),
                    default=DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W,
                ),
            ),
        }
        await self._async_save_circuit_settings(
            circuit_id,
            self._coordinator.store_data.balance_settings_by_circuit,
            settings,
        )

    async def async_set_solar_flow_settings(
        self,
        circuit_id: str,
        export_tolerance_w: Any = None,
        solar_surplus_threshold_w: Any = None,
        high_solar_surplus_threshold_w: Any = None,
        flexible_load_running_threshold_w: Any = None,
    ) -> None:
        """Persist solar flow and flexible-load thresholds."""
        current = self._coordinator.store_data.solar_flow_settings_by_circuit.get(
            circuit_id,
            {},
        )
        settings = {
            "export_tolerance_w": _nonnegative_float_value(
                export_tolerance_w,
                default=_nonnegative_float_value(
                    current.get("export_tolerance_w"),
                    default=EXPORT_TOLERANCE_W,
                ),
            ),
            "solar_surplus_threshold_w": _nonnegative_float_value(
                solar_surplus_threshold_w,
                default=_nonnegative_float_value(
                    current.get("solar_surplus_threshold_w"),
                    default=SOLAR_SURPLUS_THRESHOLD_W,
                ),
            ),
            "high_solar_surplus_threshold_w": _nonnegative_float_value(
                high_solar_surplus_threshold_w,
                default=_nonnegative_float_value(
                    current.get("high_solar_surplus_threshold_w"),
                    default=HIGH_SOLAR_SURPLUS_THRESHOLD_W,
                ),
            ),
            "flexible_load_running_threshold_w": _nonnegative_float_value(
                flexible_load_running_threshold_w,
                default=_nonnegative_float_value(
                    current.get("flexible_load_running_threshold_w"),
                    default=FLEXIBLE_LOAD_RUNNING_THRESHOLD_W,
                ),
            ),
        }
        await self._async_save_circuit_settings(
            circuit_id,
            self._coordinator.store_data.solar_flow_settings_by_circuit,
            settings,
        )

    async def _async_save_circuit_settings(
        self,
        circuit_id: str,
        settings_by_circuit: MutableMapping[str, Any],
        settings: Any,
    ) -> None:
        coordinator = self._coordinator
        settings_by_circuit[circuit_id] = settings
        coordinator._mark_store_dirty()
        now = coordinator._now_fn()
        coordinator._refresh_ux_state_for_circuit(circuit_id, now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator._async_save_store(now)

    async def async_apply_setting_recommendation(
        self,
        recommendation_id: str,
    ) -> None:
        """Apply one pending setting recommendation to advanced settings."""
        coordinator = self._coordinator
        recommendation = coordinator.store_data.settings_recommendations.get(
            recommendation_id,
        )
        if (
            recommendation is None
            or recommendation.status is not RecommendationStatus.PENDING
        ):
            return

        for setting_key, value in recommendation.apply_payload.items():
            self.set_recommendation_setting_value(
                recommendation.circuit_id,
                str(setting_key),
                value,
            )
        if any(
            key in OPERATING_DETECTION_OVERRIDE_FIELDS
            for key in recommendation.apply_payload
        ):
            self.set_recommendation_setting_value(
                recommendation.circuit_id,
                OPERATING_DETECTION_SOURCE,
                OperatingThresholdSource.LEARNED_RECOMMENDATION.value,
            )
        await coordinator._async_persist_config_entry_options()

        coordinator.store_data.settings_recommendations[recommendation_id] = replace(
            recommendation,
            status=RecommendationStatus.APPLIED,
        )
        coordinator._mark_store_dirty()
        now = coordinator._now_fn()
        coordinator._refresh_settings_recommendation_state(now)
        coordinator._refresh_ux_state_for_circuit(recommendation.circuit_id, now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator._async_save_store(now)

    async def async_undo_setting_recommendation(
        self,
        recommendation_id: str,
    ) -> bool:
        """Restore the value recorded before an applied recommendation."""
        coordinator = self._coordinator
        recommendation = coordinator.store_data.settings_recommendations.get(
            recommendation_id,
        )
        if (
            recommendation is None
            or recommendation.status is not RecommendationStatus.APPLIED
        ):
            return False

        self.set_recommendation_setting_value(
            recommendation.circuit_id,
            recommendation.setting_key,
            recommendation.current_value,
        )
        await coordinator._async_persist_config_entry_options()
        coordinator.store_data.settings_recommendations[recommendation_id] = replace(
            recommendation,
            status=RecommendationStatus.PENDING,
        )
        coordinator._mark_store_dirty()
        now = coordinator._now_fn()
        coordinator._refresh_settings_recommendation_state(now)
        coordinator._refresh_ux_state_for_circuit(recommendation.circuit_id, now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator._async_save_store(now)
        return True

    async def async_reset_setting_recommendation(
        self,
        recommendation_id: str,
    ) -> bool:
        """Reset a recommendation-backed setting to its built-in default."""
        coordinator = self._coordinator
        recommendation = coordinator.store_data.settings_recommendations.get(
            recommendation_id,
        )
        if recommendation is None:
            return False

        default_value = recommendation_setting_default_value(
            recommendation.setting_key,
        )
        self.set_recommendation_setting_value(
            recommendation.circuit_id,
            recommendation.setting_key,
            default_value,
        )
        await coordinator._async_persist_config_entry_options()
        coordinator.store_data.settings_recommendations[recommendation_id] = replace(
            recommendation,
            status=RecommendationStatus.STALE,
        )
        coordinator._mark_store_dirty()
        now = coordinator._now_fn()
        coordinator._refresh_settings_recommendation_state(now)
        coordinator._refresh_ux_state_for_circuit(recommendation.circuit_id, now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator._async_save_store(now)
        return True

    def set_recommendation_setting_value(
        self,
        circuit_id: str,
        setting_key: str,
        value: Any,
    ) -> None:
        """Write one recommendation-backed advanced setting value."""
        coordinator = self._coordinator
        advanced_by_circuit = coordinator.options.setdefault(
            CONF_ADVANCED_SETTINGS,
            {},
        )
        if not isinstance(advanced_by_circuit, dict):
            advanced_by_circuit = dict(advanced_by_circuit)
            coordinator.options[CONF_ADVANCED_SETTINGS] = advanced_by_circuit
        current_settings = advanced_by_circuit.get(circuit_id, {})
        updated_settings = (
            dict(current_settings) if isinstance(current_settings, Mapping) else {}
        )
        self.clear_advanced_setting_value(circuit_id, setting_key)
        if value is None:
            updated_settings.pop(setting_key, None)
        else:
            updated_settings[setting_key] = value
            self.apply_advanced_settings(circuit_id, {setting_key: value})
        if updated_settings:
            advanced_by_circuit[circuit_id] = updated_settings
        else:
            advanced_by_circuit.pop(circuit_id, None)

    def replace_advanced_settings(
        self,
        circuit_id: str,
        settings: Mapping[str, Any],
    ) -> None:
        """Replace all store-backed advanced setting groups for one circuit."""
        self.clear_advanced_settings(circuit_id)
        self.apply_advanced_settings(circuit_id, settings)

    def clear_advanced_settings(self, circuit_id: str) -> None:
        """Clear all store-backed advanced setting groups for one circuit."""
        store_data = self._coordinator.store_data
        store_data.sensitivity_by_circuit.pop(circuit_id, None)
        store_data.energy_usage_settings_by_circuit.pop(circuit_id, None)
        store_data.energy_goal_settings_by_circuit.pop(circuit_id, None)
        store_data.activity_alert_settings_by_circuit.pop(circuit_id, None)
        store_data.billing_settings_by_circuit.pop(circuit_id, None)
        store_data.cost_settings_by_circuit.pop(circuit_id, None)
        store_data.demand_settings_by_circuit.pop(circuit_id, None)
        store_data.capacity_settings_by_circuit.pop(circuit_id, None)
        store_data.standby_settings_by_circuit.pop(circuit_id, None)
        store_data.leg_imbalance_settings_by_circuit.pop(circuit_id, None)
        store_data.metric_consistency_settings_by_circuit.pop(circuit_id, None)
        store_data.balance_settings_by_circuit.pop(circuit_id, None)
        store_data.solar_flow_settings_by_circuit.pop(circuit_id, None)
        store_data.operating_detection_settings_by_circuit.pop(circuit_id, None)

    def apply_advanced_settings(
        self,
        circuit_id: str,
        settings: Mapping[str, Any],
    ) -> None:
        """Apply advanced setting values to their store-backed setting groups."""
        if not settings:
            return

        store_data = self._coordinator.store_data
        sensitivity = settings.get("preset")
        if sensitivity:
            store_data.sensitivity_by_circuit[circuit_id] = normalize_sensitivity(
                str(sensitivity)
            )

        _replace_if_present(
            store_data.energy_usage_settings_by_circuit,
            circuit_id,
            settings,
            ("window_days", "daily_spike_ratio"),
        )
        _replace_if_present(
            store_data.energy_goal_settings_by_circuit,
            circuit_id,
            settings,
            ("daily_goal_kwh", "goal_alert_ratio"),
        )
        _replace_if_present(
            store_data.activity_alert_settings_by_circuit,
            circuit_id,
            settings,
            ("max_active_minutes", "max_idle_minutes"),
        )
        _replace_if_present(
            store_data.billing_settings_by_circuit,
            circuit_id,
            settings,
            (
                "cycle_start_day",
                "budget_kwh",
                "budget_alert_ratio",
                "min_elapsed_days",
            ),
        )
        _replace_if_present(
            store_data.cost_settings_by_circuit,
            circuit_id,
            settings,
            (
                "cycle_start_day",
                "default_rate_per_kwh",
                "tou_rate_per_kwh",
                "tou_start",
                "tou_end",
                "tou_weekdays",
                "tou_name",
            ),
        )
        _replace_if_present(
            store_data.demand_settings_by_circuit,
            circuit_id,
            settings,
            ("window_minutes", "demand_limit_w"),
        )
        _replace_if_present(
            store_data.capacity_settings_by_circuit,
            circuit_id,
            settings,
            ("breaker_amps", "warning_ratio"),
        )
        _replace_if_present(
            store_data.standby_settings_by_circuit,
            circuit_id,
            settings,
            (
                "window_hours",
                "standby_threshold_w",
                "always_on_alert_w",
                "min_samples",
            ),
        )
        _replace_if_present_as(
            store_data.leg_imbalance_settings_by_circuit,
            circuit_id,
            settings,
            {
                "leg_imbalance_warning_ratio": "warning_ratio",
                "leg_imbalance_min_total_power_w": "minimum_total_power_w",
            },
        )
        _replace_if_present(
            store_data.metric_consistency_settings_by_circuit,
            circuit_id,
            settings,
            (
                "apparent_power_tolerance_percent",
                "power_factor_tolerance",
                "minimum_apparent_power_va",
            ),
        )
        _replace_if_present_as(
            store_data.balance_settings_by_circuit,
            circuit_id,
            settings,
            {"balance_negative_tolerance_w": "negative_tolerance_w"},
        )
        _replace_if_present_as(
            store_data.solar_flow_settings_by_circuit,
            circuit_id,
            settings,
            {
                "solar_export_tolerance_w": "export_tolerance_w",
                "solar_surplus_threshold_w": "solar_surplus_threshold_w",
                "high_solar_surplus_threshold_w": (
                    "high_solar_surplus_threshold_w"
                ),
                "flexible_load_running_threshold_w": (
                    "flexible_load_running_threshold_w"
                ),
            },
        )
        _replace_if_present(
            store_data.operating_detection_settings_by_circuit,
            circuit_id,
            settings,
            (*OPERATING_DETECTION_OVERRIDE_FIELDS, OPERATING_DETECTION_SOURCE),
        )

    def advanced_settings_for_circuit(self, circuit_id: str) -> dict[str, Any]:
        """Return merged advanced settings for one circuit."""
        coordinator = self._coordinator
        settings: dict[str, Any] = {}
        for source in (
            coordinator.entry_data.get(CONF_ADVANCED_SETTINGS, {}),
            coordinator.options.get(CONF_ADVANCED_SETTINGS, {}),
        ):
            if not isinstance(source, Mapping):
                continue
            raw_settings = source.get(circuit_id, {})
            if isinstance(raw_settings, Mapping):
                settings.update(dict(raw_settings))

        store_data = coordinator.store_data
        settings.update(
            store_data.energy_usage_settings_by_circuit.get(circuit_id, {}),
        )
        settings.update(
            store_data.activity_alert_settings_by_circuit.get(circuit_id, {}),
        )
        settings.update(store_data.demand_settings_by_circuit.get(circuit_id, {}))
        settings.update(store_data.capacity_settings_by_circuit.get(circuit_id, {}))
        settings.update(store_data.standby_settings_by_circuit.get(circuit_id, {}))
        settings.update(
            store_data.metric_consistency_settings_by_circuit.get(
                circuit_id,
                {},
            ),
        )

        leg_imbalance = store_data.leg_imbalance_settings_by_circuit.get(
            circuit_id,
            {},
        )
        if "warning_ratio" in leg_imbalance:
            settings["leg_imbalance_warning_ratio"] = leg_imbalance["warning_ratio"]
        if "minimum_total_power_w" in leg_imbalance:
            settings["leg_imbalance_min_total_power_w"] = leg_imbalance[
                "minimum_total_power_w"
            ]

        balance = store_data.balance_settings_by_circuit.get(circuit_id, {})
        if "negative_tolerance_w" in balance:
            settings["balance_negative_tolerance_w"] = balance[
                "negative_tolerance_w"
            ]

        solar_flow = store_data.solar_flow_settings_by_circuit.get(
            circuit_id,
            {},
        )
        if "export_tolerance_w" in solar_flow:
            settings["solar_export_tolerance_w"] = solar_flow["export_tolerance_w"]
        for key in (
            "solar_surplus_threshold_w",
            "high_solar_surplus_threshold_w",
            "flexible_load_running_threshold_w",
        ):
            if key in solar_flow:
                settings[key] = solar_flow[key]

        settings.update(
            store_data.operating_detection_settings_by_circuit.get(
                circuit_id,
                {},
            )
        )

        return settings

    def clear_advanced_setting_value(self, circuit_id: str, setting_key: str) -> None:
        """Clear one recommendation-backed value from stored setting groups."""
        store_data = self._coordinator.store_data
        if setting_key == "preset":
            store_data.sensitivity_by_circuit.pop(circuit_id, None)
            return
        _remove_setting_key(
            store_data.energy_usage_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            store_data.energy_goal_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            store_data.activity_alert_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            store_data.billing_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            store_data.cost_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            store_data.demand_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            store_data.capacity_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            store_data.standby_settings_by_circuit,
            circuit_id,
            "min_samples" if setting_key == "standby_min_samples" else setting_key,
        )
        _remove_setting_key(
            store_data.leg_imbalance_settings_by_circuit,
            circuit_id,
            {
                "leg_imbalance_warning_ratio": "warning_ratio",
                "leg_imbalance_min_total_power_w": "minimum_total_power_w",
            }.get(setting_key, setting_key),
        )
        _remove_setting_key(
            store_data.metric_consistency_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            store_data.balance_settings_by_circuit,
            circuit_id,
            {
                "balance_negative_tolerance_w": "negative_tolerance_w",
            }.get(setting_key, setting_key),
        )
        _remove_setting_key(
            store_data.solar_flow_settings_by_circuit,
            circuit_id,
            {
                "solar_export_tolerance_w": "export_tolerance_w",
            }.get(setting_key, setting_key),
        )
        _remove_setting_key(
            store_data.operating_detection_settings_by_circuit,
            circuit_id,
            setting_key,
        )

    async def async_deny_setting_recommendation(self, recommendation_id: str) -> None:
        """Record a denial for one pending setting recommendation."""
        await self.async_record_setting_recommendation_decision(
            recommendation_id,
            RecommendationStatus.DENIED,
        )

    async def async_dismiss_setting_recommendation(
        self,
        recommendation_id: str,
    ) -> None:
        """Record a dismissal for one pending setting recommendation."""
        await self.async_record_setting_recommendation_decision(
            recommendation_id,
            RecommendationStatus.DISMISSED,
        )

    async def async_record_setting_recommendation_decision(
        self,
        recommendation_id: str,
        status: RecommendationStatus,
    ) -> None:
        """Record a terminal decision for one pending setting recommendation."""
        coordinator = self._coordinator
        recommendation = coordinator.store_data.settings_recommendations.get(
            recommendation_id,
        )
        if (
            recommendation is None
            or recommendation.status is not RecommendationStatus.PENDING
        ):
            return

        now = coordinator._now_fn()
        coordinator.store_data.settings_recommendations[recommendation_id] = replace(
            recommendation,
            status=status,
        )
        coordinator.store_data.settings_recommendation_decisions[
            recommendation.unique_key
        ] = RecommendationDecision(
            unique_key=recommendation.unique_key,
            status=status,
            decided_at=now,
            denied_value=recommendation.suggested_value,
            evidence_fingerprint=recommendation_evidence_fingerprint(
                recommendation,
            ),
        )
        coordinator._mark_store_dirty()
        coordinator._refresh_settings_recommendation_state(now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator._async_save_store(now)


def _remove_setting_key(
    settings_by_circuit: MutableMapping[str, dict[str, Any]],
    circuit_id: str,
    setting_key: str,
) -> None:
    settings = settings_by_circuit.get(circuit_id)
    if not isinstance(settings, dict):
        return
    settings.pop(setting_key, None)
    if not settings:
        settings_by_circuit.pop(circuit_id, None)


def _replace_if_present(
    target: MutableMapping[str, dict[str, Any]],
    circuit_id: str,
    source: Mapping[str, Any],
    keys: tuple[str, ...],
) -> None:
    values = {key: source[key] for key in keys if key in source}
    if values:
        target[circuit_id] = values


def _replace_if_present_as(
    target: MutableMapping[str, dict[str, Any]],
    circuit_id: str,
    source: Mapping[str, Any],
    key_map: Mapping[str, str],
) -> None:
    values = {
        output_key: source[input_key]
        for input_key, output_key in key_map.items()
        if input_key in source
    }
    if values:
        target[circuit_id] = values


def _positive_int_value(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _positive_float_value(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0.0 else default


def _optional_positive_float_value(
    value: Any,
    *,
    default: float | None,
) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0.0 else default


def _entity_id_tuple_value(
    value: Any,
    *,
    default: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        raw_items: Any = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        return default
    return tuple(str(item).strip() for item in raw_items if str(item).strip())


def _weekday_tuple_value(
    value: Any,
    *,
    default: tuple[int, ...] = (),
) -> tuple[int, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        raw_items: Any = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        return default
    weekdays: list[int] = []
    for item in raw_items:
        try:
            weekday = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if 0 <= weekday <= 6 and weekday not in weekdays:
            weekdays.append(weekday)
    return tuple(weekdays) if weekdays else default


def _weekday_csv_value(value: Any, *, default: tuple[int, ...] = ()) -> str:
    return ",".join(str(day) for day in _weekday_tuple_value(value, default=default))


def _nonnegative_float_value(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0.0 else default
