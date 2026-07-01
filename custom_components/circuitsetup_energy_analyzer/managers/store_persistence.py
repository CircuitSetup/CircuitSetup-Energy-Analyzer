from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

ContextualBaselinePruner = Callable[
    [dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], Any, datetime],
    tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]],
]


class StorePersistenceManager:
    """Manage store dirty tracking and save gating for the coordinator."""

    def __init__(
        self,
        coordinator: Any,
        *,
        newest_mapping_items: Callable[[Any, int], list[dict[str, Any]]],
        mapping_time: Callable[..., datetime],
        retention_mode_for_circuit: Callable[[str], Any],
        retention_window_for_circuit: Callable[[str], timedelta],
        ha_local_date: Callable[[datetime, str | None], Any],
        ha_time_zone: Callable[[], str | None],
        sample_timestamp_is_at_or_after: Callable[[Any, datetime], bool],
        contextual_baseline_pruner: ContextualBaselinePruner,
        weather_context_history_max_samples: int,
        water_context_history_max_samples: int,
        alert_history_max_age: timedelta,
        alert_history_max_items: int,
        alert_feedback_is_expired: Callable[[Any, datetime], bool],
        alert_feedback_max_age: timedelta,
        alert_feedback_max_items: int,
        nilm_signatures_max_items: int,
        nilm_unknown_loads_max_items: int,
        nilm_session_history_max_age: timedelta,
        nilm_session_history_max_items: int,
        recommendation_pending_status: Any,
        recommendation_sort_key: Callable[[Any], Any],
        recommendation_history_max_age: timedelta,
        recommendation_history_max_items: int,
        recommendation_decisions_max_age: timedelta,
        recommendation_decisions_max_items: int,
        compact_settings_recommendation_episode_key: Callable[
            [tuple[tuple[str, ...], ...]],
            tuple[tuple[str, ...], ...],
        ],
    ) -> None:
        self._coordinator = coordinator
        self._newest_mapping_items = newest_mapping_items
        self._mapping_time = mapping_time
        self._retention_mode_for_circuit = retention_mode_for_circuit
        self._retention_window_for_circuit = retention_window_for_circuit
        self._ha_local_date = ha_local_date
        self._ha_time_zone = ha_time_zone
        self._sample_timestamp_is_at_or_after = sample_timestamp_is_at_or_after
        self._contextual_baseline_pruner = contextual_baseline_pruner
        self._weather_context_history_max_samples = weather_context_history_max_samples
        self._water_context_history_max_samples = water_context_history_max_samples
        self._alert_history_max_age = alert_history_max_age
        self._alert_history_max_items = alert_history_max_items
        self._alert_feedback_is_expired = alert_feedback_is_expired
        self._alert_feedback_max_age = alert_feedback_max_age
        self._alert_feedback_max_items = alert_feedback_max_items
        self._nilm_signatures_max_items = nilm_signatures_max_items
        self._nilm_unknown_loads_max_items = nilm_unknown_loads_max_items
        self._nilm_session_history_max_age = nilm_session_history_max_age
        self._nilm_session_history_max_items = nilm_session_history_max_items
        self._recommendation_pending_status = recommendation_pending_status
        self._recommendation_sort_key = recommendation_sort_key
        self._recommendation_history_max_age = recommendation_history_max_age
        self._recommendation_history_max_items = recommendation_history_max_items
        self._recommendation_decisions_max_age = recommendation_decisions_max_age
        self._recommendation_decisions_max_items = recommendation_decisions_max_items
        self._compact_settings_recommendation_episode_key = (
            compact_settings_recommendation_episode_key
        )
        self.dirty = False

    def mark_dirty(self) -> None:
        self.dirty = True

    async def async_save_if_dirty(self, now: datetime) -> None:
        store = getattr(self._coordinator, "_store", None)
        if store is None or not self.dirty:
            return
        self._coordinator._apply_retention(now)
        store.data = self._coordinator.store_data
        await store.async_save()
        self.dirty = False

    def prune_energy_usage(self, now: datetime) -> None:
        """Apply retention caps to stored daily energy rows."""
        store_data = self._coordinator.store_data
        for circuit_id, history in store_data.energy_usage_by_circuit.items():
            cutoff = (
                self._ha_local_date(now, self._ha_time_zone())
                - self._retention_window_for_circuit(circuit_id)
            ).isoformat()
            days = history.get("days", [])
            if not isinstance(days, list):
                continue
            history["days"] = [
                day
                for day in days
                if isinstance(day, dict) and str(day.get("date", "")) >= cutoff
            ]

    def prune_demand(self, now: datetime) -> None:
        """Apply retention caps to stored demand histories."""
        store_data = self._coordinator.store_data
        for circuit_id, history in store_data.demand_by_circuit.items():
            retention_window = self._retention_window_for_circuit(circuit_id)
            cutoff_datetime = now - retention_window
            cutoff = (
                self._ha_local_date(now, self._ha_time_zone()) - retention_window
            ).isoformat()
            capacity_samples = history.get("capacity_current_samples")
            if isinstance(capacity_samples, list):
                history["capacity_current_samples"] = [
                    sample
                    for sample in capacity_samples
                    if self._sample_timestamp_is_at_or_after(sample, cutoff_datetime)
                ]
            daily_peaks = history.get("daily_peaks", [])
            if isinstance(daily_peaks, list):
                history["daily_peaks"] = [
                    peak
                    for peak in daily_peaks
                    if isinstance(peak, dict)
                    and str(peak.get("date", "")) >= cutoff
                ]

    def prune_standby(self, now: datetime) -> None:
        """Apply retention caps to stored standby samples."""
        store_data = self._coordinator.store_data
        for circuit_id, history in store_data.standby_by_circuit.items():
            cutoff = now - self._retention_window_for_circuit(circuit_id)
            samples = history.get("samples", [])
            if isinstance(samples, list):
                history["samples"] = [
                    sample
                    for sample in samples
                    if self._sample_timestamp_is_at_or_after(sample, cutoff)
                ]

    def prune_weather_context(self, now: datetime) -> None:
        """Apply retention caps to stored weather context histories."""
        store_data = self._coordinator.store_data
        for circuit_id, history in (
            store_data.weather_context_history_by_circuit.items()
        ):
            cutoff = now - self._retention_window_for_circuit(circuit_id)
            store_data.weather_context_history_by_circuit[circuit_id] = [
                sample
                for sample in history
                if self._sample_timestamp_is_at_or_after(sample, cutoff)
            ][-self._weather_context_history_max_samples :]

    def prune_water_context(self, now: datetime) -> None:
        """Apply retention caps to stored water context histories."""
        store_data = self._coordinator.store_data
        for circuit_id, history in store_data.water_context_history_by_circuit.items():
            cutoff = now - self._retention_window_for_circuit(circuit_id)
            store_data.water_context_history_by_circuit[circuit_id] = [
                sample
                for sample in history
                if self._sample_timestamp_is_at_or_after(sample, cutoff)
            ][-self._water_context_history_max_samples :]

    def prune_contextual_baseline_state(self, now: datetime) -> None:
        """Apply retention caps to contextual baseline samples and stats."""
        store_data = self._coordinator.store_data
        pruned_samples: dict[str, list[dict[str, Any]]] = {}
        pruned_stats: dict[str, dict[str, Any]] = {}
        circuit_ids = set(store_data.contextual_baseline_samples_by_circuit) | set(
            store_data.contextual_baselines_by_circuit
        )
        for circuit_id in circuit_ids:
            samples = store_data.contextual_baseline_samples_by_circuit.get(
                circuit_id,
                [],
            )
            stats = store_data.contextual_baselines_by_circuit.get(
                circuit_id,
                {},
            )
            samples_by_circuit, stats_by_circuit = (
                self._contextual_baseline_pruner(
                    {circuit_id: samples},
                    {circuit_id: stats},
                    self._retention_mode_for_circuit(circuit_id),
                    now,
                )
            )
            if samples_by_circuit.get(circuit_id):
                pruned_samples[circuit_id] = samples_by_circuit[circuit_id]
            if stats_by_circuit.get(circuit_id):
                pruned_stats[circuit_id] = stats_by_circuit[circuit_id]
        store_data.contextual_baseline_samples_by_circuit = pruned_samples
        store_data.contextual_baselines_by_circuit = pruned_stats

    def prune_alert_history(self, now: datetime) -> None:
        """Apply retention caps to stored alert history."""
        store_data = self._coordinator.store_data
        cutoff = now - self._alert_history_max_age
        store_data.alerts = sorted(
            (alert for alert in store_data.alerts if alert.timestamp >= cutoff),
            key=lambda alert: alert.timestamp,
            reverse=True,
        )[: self._alert_history_max_items]

    def prune_nilm_history(self, now: datetime) -> None:
        """Apply retention caps to NILM store histories."""
        store_data = self._coordinator.store_data
        for circuit_id, signatures in store_data.nilm_signatures.items():
            store_data.nilm_signatures[circuit_id] = self._newest_mapping_items(
                signatures,
                self._nilm_signatures_max_items,
            )
        for inventory in store_data.nilm_unknown_loads_by_circuit.values():
            unknown_loads = inventory.get("unknown_loads")
            if isinstance(unknown_loads, list):
                inventory["unknown_loads"] = self._newest_mapping_items(
                    unknown_loads,
                    self._nilm_unknown_loads_max_items,
                )
        cutoff = now - self._nilm_session_history_max_age
        for circuit_id, sessions in list(
            store_data.nilm_session_history_by_circuit.items()
        ):
            retained = [
                dict(session)
                for session in sessions
                if isinstance(session, Mapping)
                and self._mapping_time(
                    session,
                    "end",
                    "start",
                    "updated_at",
                    "created_at",
                    "timestamp",
                )
                >= cutoff
            ]
            store_data.nilm_session_history_by_circuit[circuit_id] = sorted(
                retained,
                key=lambda session: self._mapping_time(
                    session,
                    "end",
                    "start",
                    "updated_at",
                    "created_at",
                    "timestamp",
                ),
                reverse=True,
            )[: self._nilm_session_history_max_items]

    def prune_alert_feedback(self, now: datetime) -> None:
        """Apply retention caps to alert feedback state."""
        store_data = self._coordinator.store_data
        cutoff = now - self._alert_feedback_max_age
        retained = {
            key: value
            for key, value in store_data.alert_feedback.items()
            if not self._alert_feedback_is_expired(value, now)
            and self._mapping_time(value, "created_at", "timestamp") >= cutoff
        }
        store_data.alert_feedback = dict(
            sorted(
                retained.items(),
                key=lambda item: self._mapping_time(
                    item[1],
                    "created_at",
                    "timestamp",
                ),
                reverse=True,
            )[: self._alert_feedback_max_items]
        )

    def prune_recommendation_history(self, now: datetime) -> None:
        """Apply retention caps to settings recommendation histories."""
        store_data = self._coordinator.store_data
        cutoff = now - self._recommendation_history_max_age
        recommendations = {
            recommendation_id: recommendation
            for recommendation_id, recommendation in (
                store_data.settings_recommendations.items()
            )
            if recommendation.status is self._recommendation_pending_status
            or recommendation.created_at >= cutoff
        }
        store_data.settings_recommendations = dict(
            sorted(
                recommendations.items(),
                key=lambda item: self._recommendation_sort_key(item[1]),
                reverse=True,
            )[: self._recommendation_history_max_items]
        )

        decision_cutoff = now - self._recommendation_decisions_max_age
        decisions = {
            unique_key: decision
            for unique_key, decision in (
                store_data.settings_recommendation_decisions.items()
            )
            if decision.decided_at >= decision_cutoff
        }
        store_data.settings_recommendation_decisions = dict(
            sorted(
                decisions.items(),
                key=lambda item: item[1].decided_at,
                reverse=True,
            )[: self._recommendation_decisions_max_items]
        )
        store_data.settings_recommendation_notification_episode_key = (
            self._compact_settings_recommendation_episode_key(
                store_data.settings_recommendation_notification_episode_key
            )
        )
