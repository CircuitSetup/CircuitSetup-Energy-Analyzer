"""Strict AnalyzerState update helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterable, MutableMapping
from dataclasses import dataclass
from typing import Any

from ..processors.base import FeatureResult, StateUpdate


@dataclass(frozen=True, slots=True)
class AppliedFeatureResult:
    """Coordinator side effects still needed after reducing a FeatureResult."""

    events: list[Any]
    active_alerts: list[Any]
    notifications: list[Any]
    store_dirty: bool


def apply_state_update(state: Any, path: tuple[str, ...], value: Any) -> None:
    """Apply a processor-requested update to AnalyzerState."""
    if not path:
        msg = "State update path must not be empty"
        raise ValueError(msg)
    if len(path) < 2:
        msg = "State update path must include a root and destination key"
        raise ValueError(msg)

    root = path[0]
    if root not in getattr(type(state), "__dataclass_fields__", {}):
        msg = f"State update path has unknown root: {root}"
        raise ValueError(msg)

    target = getattr(state, root)
    if not isinstance(target, MutableMapping):
        msg = f"State update root is not a mapping: {root}"
        raise TypeError(msg)

    target_segment = root
    for segment in path[1:-1]:
        if not isinstance(target, MutableMapping):
            msg = f"State update target is not a mapping at: {target_segment}"
            raise TypeError(msg)
        if segment not in target:
            msg = f"State update cannot create intermediate key: {segment}"
            raise ValueError(msg)
        target = target[segment]
        target_segment = segment

    if not isinstance(target, MutableMapping):
        msg = f"State update target is not a mapping at: {target_segment}"
        raise TypeError(msg)
    final_segment = path[-1]
    target[final_segment] = value


class StateReducer:
    """Apply validated state update paths."""

    def apply_update(self, state: Any, path: tuple[str, ...], value: Any) -> None:
        """Apply one validated state update path."""
        apply_state_update(state, path, value)

    def apply_updates(self, state: Any, updates: Iterable[StateUpdate]) -> None:
        """Apply a batch of validated state update paths."""
        for update in updates:
            self.apply_update(state, update.path, update.value)

    def apply_feature_result(
        self,
        state: Any,
        store_data: Any,
        result: FeatureResult,
        *,
        alert_feedback: Callable[[Any], Any],
        record_observation: Callable[[Any], None],
    ) -> AppliedFeatureResult:
        """Apply processor output to analyzer state and persistent store."""
        stored_alerts = [alert_feedback(alert) for alert in result.alerts]
        active_alerts = [
            alert for alert in stored_alerts if alert.feedback_status != "expected"
        ]
        if result.events:
            store_data.events.extend(result.events)
        if stored_alerts:
            store_data.alerts.extend(stored_alerts)
        for observation in result.observations:
            record_observation(observation)
        self.apply_updates(state, result.state_updates)
        notifications = [alert_feedback(alert) for alert in result.notifications]
        store_dirty = bool(result.store_dirty or result.events or stored_alerts)
        return AppliedFeatureResult(
            events=list(result.events),
            active_alerts=active_alerts,
            notifications=notifications,
            store_dirty=store_dirty,
        )
