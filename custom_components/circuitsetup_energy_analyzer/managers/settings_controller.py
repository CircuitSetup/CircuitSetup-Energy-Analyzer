"""Advanced settings workflows for the coordinator."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import replace
from typing import Any

from ..const import CONF_ADVANCED_SETTINGS
from ..operating_detection import (
    OPERATING_DETECTION_OVERRIDE_FIELDS,
    OPERATING_DETECTION_SOURCE,
    OperatingThresholdSource,
)
from ..recommendation_guidance import recommendation_setting_default_value
from ..settings_advisor import (
    RecommendationDecision,
    RecommendationStatus,
    recommendation_evidence_fingerprint,
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
