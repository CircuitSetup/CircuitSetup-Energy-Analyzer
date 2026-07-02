"""Strict AnalyzerState update helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ..processors.base import FeatureResult, StateUpdate
from ..ux import friendly_feature_name


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
            self.record_recent_observation(state, observation)
        self.apply_updates(state, result.state_updates)
        notifications = [alert_feedback(alert) for alert in result.notifications]
        store_dirty = bool(result.store_dirty or result.events or stored_alerts)
        return AppliedFeatureResult(
            events=list(result.events),
            active_alerts=active_alerts,
            notifications=notifications,
            store_dirty=store_dirty,
        )

    def record_recent_observation(self, state: Any, observation: Any) -> None:
        """Record one recent observation in state, replacing matching keyed entries."""
        payload = _observation_payload(observation)
        observations = state.recent_observations_by_circuit.setdefault(
            observation.circuit_id,
            [],
        )
        observation_key = payload.get("observation_key")
        if observation_key is not None:
            for index, existing in enumerate(observations):
                if existing.get("observation_key") == observation_key:
                    observations[index] = payload
                    return
        observations.append(payload)

    def prune_recent_observations(
        self,
        state: Any,
        now: datetime,
        *,
        window_hours: float,
    ) -> None:
        """Drop recent observation payloads outside the dashboard timeline window."""
        cutoff = now - timedelta(hours=window_hours)
        retained: dict[str, list[dict[str, Any]]] = {}
        for (
            circuit_id,
            observations,
        ) in state.recent_observations_by_circuit.items():
            kept = [
                observation
                for observation in observations
                if _observation_within_cutoff(observation, cutoff)
            ]
            if kept:
                retained[circuit_id] = kept
        state.recent_observations_by_circuit = retained


def _observation_payload(observation: Any) -> dict[str, Any]:
    payload = {
        "timestamp": observation.observed_at.isoformat(),
        "circuit_id": observation.circuit_id,
        "feature": observation.feature,
        "feature_name": friendly_feature_name(observation.feature),
        "message": observation.message,
        "score": observation.score,
        "baseline_confidence": observation.baseline_confidence,
        "observed_value": observation.observed_value,
        "baseline_value": observation.baseline_value,
    }
    if getattr(observation, "observation_key", None) is not None:
        payload["observation_key"] = observation.observation_key
    return payload


def _observation_within_cutoff(
    observation: Mapping[str, Any],
    cutoff: datetime,
) -> bool:
    observed_at = _datetime_or_none(observation.get("timestamp"))
    return observed_at is not None and observed_at >= cutoff


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
