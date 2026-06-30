from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .. import notifications
from ..models import AlertEvidence


class NotificationController:
    """Coordinate persistent notifications and duplicate suppression."""

    def __init__(
        self,
        coordinator: Any,
        *,
        compact_settings_recommendation_episode_key: Callable[
            [tuple[tuple[str, ...], ...]],
            tuple[tuple[str, ...], ...],
        ],
        material_evidence_key: Callable[
            [str, dict[str, Any]],
            tuple[tuple[str, Any], ...],
        ],
    ) -> None:
        self._coordinator = coordinator
        self._compact_settings_recommendation_episode_key = (
            compact_settings_recommendation_episode_key
        )
        self._material_evidence_key = material_evidence_key
        self.notified_alert_ids: set[str] = set()
        self.settings_recommendation_notification_episode_key = (
            self._stored_settings_recommendation_episode_key()
        )
        store_data = self._coordinator.store_data
        store_data.settings_recommendation_notification_episode_key = (
            self.settings_recommendation_notification_episode_key
        )

    async def async_notify_alert(self, alert: AlertEvidence) -> None:
        """Create one persistent alert notification when it is not suppressed."""
        if alert.circuit_id in self._coordinator.paused_circuits:
            return
        if self._coordinator._has_suppressed_alert_feedback(alert):
            return
        alert_id = notifications.notification_id_for_alert(alert)
        if alert_id in self.notified_alert_ids:
            return
        self.notified_alert_ids.add(alert_id)
        await notifications.async_create_alert_notification(
            self._coordinator.hass,
            alert,
            config=self._coordinator._config_for_circuit(alert.circuit_id),
        )

    async def async_notify_settings_recommendations_if_needed(self) -> None:
        """Notify once for each material set of pending setting recommendations."""
        total_pending = sum(
            self._coordinator.state.settings_recommendation_count_by_circuit.values(),
        )
        if total_pending <= 0:
            self.set_settings_recommendation_notification_episode_key(())
            return

        episode_key = self.settings_recommendation_episode_key()
        if episode_key == self.settings_recommendation_notification_episode_key:
            return

        self.set_settings_recommendation_notification_episode_key(episode_key)
        await notifications.async_create_settings_recommendation_notification(
            self._coordinator.hass,
            self._coordinator.entry_id,
            total_pending=total_pending,
        )
        self._coordinator._mark_store_dirty()
        await self._coordinator._async_save_store(self._coordinator._now_fn())

    def settings_recommendation_episode_key(
        self,
    ) -> tuple[tuple[str, ...], ...]:
        """Return the duplicate-suppression key for pending recommendations."""
        parts: list[tuple[str, ...]] = []
        for recommendation in self._coordinator._pending_settings_recommendations(
            self._coordinator._now_fn()
        ):
            evidence_key = repr(
                self._material_evidence_key(
                    recommendation.feature,
                    recommendation.evidence,
                ),
            )
            parts.append(
                (
                    str(recommendation.recommendation_id),
                    str(recommendation.circuit_id),
                    str(recommendation.setting_key),
                    repr(recommendation.current_value),
                    repr(recommendation.suggested_value),
                    repr(sorted(dict(recommendation.apply_payload).items())),
                    str(recommendation.reason),
                    evidence_key,
                )
            )
        return self._compact_settings_recommendation_episode_key(tuple(sorted(parts)))

    def set_settings_recommendation_notification_episode_key(
        self,
        episode_key: tuple[tuple[str, ...], ...],
    ) -> None:
        """Persist the latest settings recommendation notification episode key."""
        if episode_key == self.settings_recommendation_notification_episode_key:
            return
        self.settings_recommendation_notification_episode_key = episode_key
        store_data = self._coordinator.store_data
        store_data.settings_recommendation_notification_episode_key = episode_key
        self._coordinator._mark_store_dirty()

    def _stored_settings_recommendation_episode_key(
        self,
    ) -> tuple[tuple[str, ...], ...]:
        store_data = self._coordinator.store_data
        return self._compact_settings_recommendation_episode_key(
            tuple(
                tuple(str(item) for item in part)
                for part in (
                    store_data.settings_recommendation_notification_episode_key
                )
            )
        )
