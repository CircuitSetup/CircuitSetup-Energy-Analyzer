"""Advanced settings recommendation workflows for the coordinator."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..operating_detection import (
    OPERATING_DETECTION_OVERRIDE_FIELDS,
    OPERATING_DETECTION_SOURCE,
    OperatingThresholdSource,
)
from ..recommendation_guidance import recommendation_setting_default_value
from ..settings_advisor import RecommendationStatus


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
            coordinator._set_recommendation_setting_value(
                recommendation.circuit_id,
                str(setting_key),
                value,
            )
        if any(
            key in OPERATING_DETECTION_OVERRIDE_FIELDS
            for key in recommendation.apply_payload
        ):
            coordinator._set_recommendation_setting_value(
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

        coordinator._set_recommendation_setting_value(
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
        coordinator._set_recommendation_setting_value(
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

    async def async_deny_setting_recommendation(self, recommendation_id: str) -> None:
        """Record a denial for one pending setting recommendation."""
        await self._coordinator._async_record_setting_recommendation_decision(
            recommendation_id,
            RecommendationStatus.DENIED,
        )

    async def async_dismiss_setting_recommendation(
        self,
        recommendation_id: str,
    ) -> None:
        """Record a dismissal for one pending setting recommendation."""
        await self._coordinator._async_record_setting_recommendation_decision(
            recommendation_id,
            RecommendationStatus.DISMISSED,
        )
