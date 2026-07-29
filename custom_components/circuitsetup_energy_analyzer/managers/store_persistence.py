from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from ..alert_feedback import alert_feedback_is_expired
from ..local_time import local_date
from ..settings_advisor import RecommendationStatus
from ..storage import RETENTION_WINDOWS, prune_contextual_baseline_state
from .recommendation_episodes import compact_settings_recommendation_episode_key

STORE_RETENTION_SAVE_INTERVAL = timedelta(minutes=1)
STORE_DIRTY_SAVE_INTERVAL = timedelta(seconds=30)


class StorePersistenceManager:
    """Manage store dirty tracking and save gating for the coordinator."""

    def __init__(
        self,
        coordinator: Any,
        *,
        retention_mode_for_circuit: Callable[[str], Any],
        ha_time_zone: Callable[[], str | None],
        weather_context_history_max_samples: int,
        water_context_history_max_samples: int,
        alert_history_max_age: timedelta,
        alert_history_max_items: int,
        alert_feedback_max_age: timedelta,
        alert_feedback_max_items: int,
        nilm_signatures_max_items: int,
        nilm_unknown_loads_max_items: int,
        nilm_session_history_max_age: timedelta,
        nilm_session_history_max_items: int,
        recommendation_history_max_age: timedelta,
        recommendation_history_max_items: int,
        recommendation_decisions_max_age: timedelta,
        recommendation_decisions_max_items: int,
    ) -> None:
        self._coordinator = coordinator
        self._newest_mapping_items = _newest_mapping_items
        self._mapping_time = _mapping_time
        self._retention_mode_for_circuit = retention_mode_for_circuit
        self._retention_window_for_circuit = (
            lambda circuit_id: RETENTION_WINDOWS[
                self._retention_mode_for_circuit(circuit_id)
            ]
        )
        self._ha_local_date = _ha_local_date
        self._ha_time_zone = ha_time_zone
        self._sample_timestamp_is_at_or_after = _sample_timestamp_is_at_or_after
        self._contextual_baseline_pruner = prune_contextual_baseline_state
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
        self._recommendation_pending_status = RecommendationStatus.PENDING
        self._recommendation_sort_key = _recommendation_sort_key
        self._recommendation_history_max_age = recommendation_history_max_age
        self._recommendation_history_max_items = recommendation_history_max_items
        self._recommendation_decisions_max_age = recommendation_decisions_max_age
        self._recommendation_decisions_max_items = recommendation_decisions_max_items
        self._compact_settings_recommendation_episode_key = (
            compact_settings_recommendation_episode_key
        )
        self._last_dirty_save_retention_at: datetime | None = None
        self._last_dirty_save_at: datetime | None = None
        self._dirty_generation = 0
        self._save_lock = asyncio.Lock()
        self.dirty = False

    def mark_dirty(self) -> None:
        self._dirty_generation += 1
        self.dirty = True

    def reset_baseline_for_circuit(
        self,
        circuit_id: str,
        baseline_values: dict[str, list[float]],
        now: datetime,
    ) -> None:
        """Clear learned baselines and alerts for one circuit."""
        prefix = f"{circuit_id}:"
        store_data = self._coordinator.store_data
        store_data.baselines = {
            key: value
            for key, value in store_data.baselines.items()
            if not key.startswith(prefix)
        }
        for key in list(baseline_values):
            if key.startswith(prefix):
                baseline_values.pop(key, None)
        store_data.alerts = [
            alert for alert in store_data.alerts if alert.circuit_id != circuit_id
        ]
        hvac_prefix = f"{circuit_id}|"
        store_data.hvac_response_history_by_stream = {
            key: value
            for key, value in store_data.hvac_response_history_by_stream.items()
            if not key.startswith(hvac_prefix)
        }
        store_data.hvac_correlation_history_by_circuit.pop(circuit_id, None)
        store_data.hvac_baseline_era_by_stream = {
            key: value
            for key, value in store_data.hvac_baseline_era_by_stream.items()
            if not key.startswith(hvac_prefix)
        }
        store_data.learning_started_at_by_circuit[circuit_id] = now.isoformat()
        self.mark_dirty()

    async def async_save_if_dirty(self, now: datetime, *, force: bool = True) -> None:
        async with self._save_lock:
            store = getattr(self._coordinator, "_store", None)
            if store is None or not self.dirty:
                return
            if not force and not self._dirty_save_due(now):
                return
            if self._dirty_save_retention_due(now):
                self.apply_retention(now)
                self._last_dirty_save_retention_at = now
            store.data = self._coordinator.store_data
            while self.dirty:
                generation = self._dirty_generation
                try:
                    await store.async_save()
                except RuntimeError:
                    if generation == self._dirty_generation:
                        raise
                    continue
                self._last_dirty_save_at = now
                self.dirty = generation != self._dirty_generation

    def _dirty_save_due(self, now: datetime) -> bool:
        if self._last_dirty_save_at is None:
            return True
        return now - self._last_dirty_save_at >= STORE_DIRTY_SAVE_INTERVAL

    def _dirty_save_retention_due(self, now: datetime) -> bool:
        if self._last_dirty_save_retention_at is None:
            return True
        return now - self._last_dirty_save_retention_at >= STORE_RETENTION_SAVE_INTERVAL

    def apply_retention(self, now: datetime) -> None:
        """Apply all persisted store retention rules."""
        self.prune_events(now)
        self.prune_energy_usage(now)
        self.prune_demand(now)
        self.prune_standby(now)
        self.prune_weather_context(now)
        self.prune_water_context(now)
        self.prune_contextual_baseline_state(now)
        self.prune_alert_history(now)
        self.prune_nilm_history(now)
        self.prune_alert_feedback(now)
        self.prune_recommendation_history(now)

    def prune_events(self, now: datetime) -> None:
        """Apply retention caps to stored circuit events."""
        store_data = self._coordinator.store_data
        retained_events = [
            event
            for event in store_data.events
            if event.timestamp
            >= now - self._retention_window_for_circuit(event.circuit_id)
        ]
        if len(retained_events) != len(store_data.events):
            store_data.events = retained_events

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


def _ha_local_date(value: datetime, time_zone: str | None) -> Any:
    if time_zone is None or value.tzinfo is None:
        return value.date()
    return local_date(value, time_zone)


def _datetime_floor() -> datetime:
    return datetime.min.replace(tzinfo=UTC)


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _mapping_time(item: Any, *keys: str) -> datetime:
    if not isinstance(item, Mapping):
        return _datetime_floor()
    for key in keys or ("last_seen", "timestamp", "created_at", "first_seen"):
        parsed = _datetime_or_none(item.get(key))
        if parsed is not None:
            return parsed
    return _datetime_floor()


def _newest_mapping_items(items: Any, max_items: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    mapped_items = [dict(item) for item in items if isinstance(item, Mapping)]
    return sorted(mapped_items, key=_mapping_time, reverse=True)[:max_items]


def _sample_timestamp_is_at_or_after(sample: Any, cutoff: datetime) -> bool:
    if not isinstance(sample, dict):
        return False
    sample_time = _datetime_or_none(sample.get("timestamp"))
    return sample_time is not None and sample_time >= cutoff


def _recommendation_sort_key(recommendation: Any) -> tuple[bool, datetime]:
    return (
        recommendation.status is RecommendationStatus.PENDING,
        max(recommendation.created_at, recommendation.expires_at),
    )
