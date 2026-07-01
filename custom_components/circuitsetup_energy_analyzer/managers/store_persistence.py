from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any


class StorePersistenceManager:
    """Manage store dirty tracking and save gating for the coordinator."""

    def __init__(
        self,
        coordinator: Any,
        *,
        newest_mapping_items: Callable[[Any, int], list[dict[str, Any]]],
        mapping_time: Callable[..., datetime],
        alert_history_max_age: timedelta,
        alert_history_max_items: int,
        alert_feedback_is_expired: Callable[[Any, datetime], bool],
        alert_feedback_max_age: timedelta,
        alert_feedback_max_items: int,
        nilm_signatures_max_items: int,
        nilm_unknown_loads_max_items: int,
        nilm_session_history_max_age: timedelta,
        nilm_session_history_max_items: int,
    ) -> None:
        self._coordinator = coordinator
        self._newest_mapping_items = newest_mapping_items
        self._mapping_time = mapping_time
        self._alert_history_max_age = alert_history_max_age
        self._alert_history_max_items = alert_history_max_items
        self._alert_feedback_is_expired = alert_feedback_is_expired
        self._alert_feedback_max_age = alert_feedback_max_age
        self._alert_feedback_max_items = alert_feedback_max_items
        self._nilm_signatures_max_items = nilm_signatures_max_items
        self._nilm_unknown_loads_max_items = nilm_unknown_loads_max_items
        self._nilm_session_history_max_age = nilm_session_history_max_age
        self._nilm_session_history_max_items = nilm_session_history_max_items
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
