"""Strict AnalyzerState update helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ..activity_timeline import build_recent_activity_timeline, timeline_payload
from ..processors.base import FeatureResult, StateUpdate
from ..ux import alert_evidence_detail, friendly_feature_name

_CIRCUIT_MODE_LABELS = {
    "single_phase": "Single Phase",
    "dual_phase": "Dual Phase",
    "mixed": "Mixed",
    "mains_nilm": "Mains NILM",
}
_POWER_FLOW_LABELS = {
    "load": "Load",
    "generation": "Generation / Solar Export",
    "mains_net": "Mains Net / Import-Export",
}


@dataclass(frozen=True, slots=True)
class AppliedFeatureResult:
    """Coordinator side effects still needed after reducing a FeatureResult."""

    events: list[Any]
    active_alerts: list[Any]
    notifications: list[Any]
    store_dirty: bool


def _bump_hvac_association_revision(state: Any, circuit_id: str) -> None:
    revisions = state.hvac_association_revision_by_circuit
    revisions[circuit_id] = revisions.get(circuit_id, 0) + 1


def clear_hvac_efficiency(state: Any, circuit_id: str) -> None:
    """Clear retained HVAC efficiency and notify existing entity consumers."""
    if circuit_id not in state.hvac_efficiency_by_circuit:
        return
    state.hvac_efficiency_by_circuit.pop(circuit_id)
    _bump_hvac_association_revision(state, circuit_id)


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
    changed_hvac_association = (
        root == "hvac_efficiency_by_circuit"
        and target.get(final_segment) != value
    )
    target[final_segment] = value
    if changed_hvac_association:
        _bump_hvac_association_revision(state, final_segment)


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
        preserved_alerts = [
            alert_feedback(alert) for alert in result.preserved_alerts
        ]
        active_alerts = [
            alert
            for alert in (*stored_alerts, *preserved_alerts)
            if alert.feedback_status != "expected"
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

    def refresh_config_metadata_state(self, state: Any, config: Any) -> None:
        """Expose configured circuit classification metadata as state."""
        state.circuit_mode_by_circuit[config.circuit_id] = _friendly_circuit_mode(
            config.mode
        )
        state.power_flow_by_circuit[config.circuit_id] = _friendly_power_flow(
            config.power_flow
        )

    def refresh_latest_real_power_state(
        self,
        state: Any,
        config: Any,
        sample: Any,
    ) -> None:
        """Store the latest normalized watts for lightweight state entities."""
        power_w = getattr(sample, "real_power", None)
        if power_w is None:
            state.latest_real_power_w_by_circuit.pop(config.circuit_id, None)
            return
        state.latest_real_power_w_by_circuit[config.circuit_id] = float(power_w)

    def reset_learning_state(self, state: Any, circuit_id: str) -> None:
        """Reset volatile state when a circuit baseline is relearned."""
        state.active_alerts_by_circuit.pop(circuit_id, None)
        state.anomaly_score_by_circuit[circuit_id] = 0.0
        state.learning_by_circuit[circuit_id] = True
        self.clear_power_quality_state(state, circuit_id)
        state.appliance_health_status_by_circuit.pop(circuit_id, None)
        state.appliance_health_evidence_by_circuit.pop(circuit_id, None)
        hvac_prefix = f"{circuit_id}|"
        state.hvac_current_episode_by_stream = {
            key: value
            for key, value in state.hvac_current_episode_by_stream.items()
            if not key.startswith(hvac_prefix)
        }
        state.hvac_correlation_active_by_pair = {
            key: value
            for key, value in state.hvac_correlation_active_by_pair.items()
            if not key.startswith(hvac_prefix)
        }
        clear_hvac_efficiency(state, circuit_id)
        state.hvac_thermostat_setup_issues_by_circuit.pop(circuit_id, None)

    def refresh_alert_evidence_state(
        self,
        state: Any,
        circuit_id: str,
        alert: Any | None,
        *,
        config: Any | None,
    ) -> None:
        """Refresh the compact alert evidence payload for one circuit."""
        if alert is None:
            state.alert_evidence_by_circuit.pop(circuit_id, None)
            return
        state.alert_evidence_by_circuit[circuit_id] = alert_evidence_detail(
            alert,
            config=config,
        )

    def refresh_recent_activity_state(
        self,
        state: Any,
        store_data: Any,
        circuit_id: str,
        now: datetime,
        *,
        events: Iterable[Any] | None = None,
        alerts: Iterable[Any] | None = None,
    ) -> None:
        """Refresh the compact recent-activity state for one circuit."""
        timeline = build_recent_activity_timeline(
            circuit_id=circuit_id,
            events=store_data.events if events is None else events,
            alerts=store_data.alerts if alerts is None else alerts,
            observations=state.recent_observations_by_circuit.get(circuit_id, []),
            now=now,
        )
        state.recent_activity_by_circuit[circuit_id] = timeline.latest_title
        state.recent_activity_count_by_circuit[circuit_id] = timeline.total_count
        state.recent_activity_timeline_by_circuit[circuit_id] = timeline_payload(
            timeline
        )

    def hydrate_context_state_from_store(self, state: Any, store_data: Any) -> None:
        """Hydrate volatile context state from persisted store snapshots."""
        state.weather_context_by_circuit = {
            circuit_id: dict(evidence)
            for circuit_id, evidence in store_data.weather_context_by_circuit.items()
        }
        state.rain_pump_context_by_circuit = {
            circuit_id: dict(evidence)
            for circuit_id, evidence in (
                store_data.rain_pump_context_by_circuit.items()
            )
        }
        state.water_flow_context_by_circuit = {
            circuit_id: dict(evidence)
            for circuit_id, evidence in (
                store_data.water_flow_context_by_circuit.items()
            )
        }
        state.water_context_history_by_circuit = {
            circuit_id: [dict(sample) for sample in samples]
            for circuit_id, samples in (
                store_data.water_context_history_by_circuit.items()
            )
        }

    def clear_power_quality_state(self, state: Any, circuit_id: str) -> bool:
        """Clear power-quality state owned by processor outputs."""
        return _pop_circuit_state(
            state,
            circuit_id,
            (
                "power_quality_score_by_circuit",
                "power_quality_evidence_by_circuit",
                "reactive_power_drift_by_circuit",
                "apparent_power_drift_by_circuit",
                "power_factor_drift_by_circuit",
            ),
        )

    def clear_standby_state(self, state: Any, circuit_id: str) -> bool:
        """Clear standby state owned by processor outputs."""
        return _pop_circuit_state(
            state,
            circuit_id,
            (
                "always_on_power_w_by_circuit",
                "standby_threshold_w_by_circuit",
                "standby_status_by_circuit",
                "always_on_limit_usage_by_circuit",
                "standby_evidence_by_circuit",
            ),
        )

    def clear_weather_context_state(
        self,
        state: Any,
        store_data: Any,
        circuit_id: str,
    ) -> bool:
        """Clear volatile and persisted weather context for one circuit."""
        removed_state = _pop_circuit_state(
            state,
            circuit_id,
            ("weather_context_by_circuit",),
        )
        removed_store = _pop_circuit_state(
            store_data,
            circuit_id,
            (
                "weather_context_by_circuit",
                "weather_context_history_by_circuit",
            ),
        )
        return removed_state or removed_store

    def clear_rain_pump_context_state(
        self,
        state: Any,
        store_data: Any,
        circuit_id: str,
    ) -> bool:
        """Clear volatile and persisted rain/pump context for one circuit."""
        return self._clear_state_and_store_group(
            state,
            store_data,
            circuit_id,
            "rain_pump_context_by_circuit",
        )

    def clear_water_flow_context_state(
        self,
        state: Any,
        store_data: Any,
        circuit_id: str,
    ) -> bool:
        """Clear volatile and persisted water-flow context for one circuit."""
        return self._clear_state_and_store_group(
            state,
            store_data,
            circuit_id,
            "water_flow_context_by_circuit",
        )

    def clear_water_context_history(
        self,
        state: Any,
        store_data: Any,
        circuit_id: str,
    ) -> bool:
        """Clear volatile and persisted water-context history for one circuit."""
        return self._clear_state_and_store_group(
            state,
            store_data,
            circuit_id,
            "water_context_history_by_circuit",
        )

    def _clear_state_and_store_group(
        self,
        state: Any,
        store_data: Any,
        circuit_id: str,
        root: str,
    ) -> bool:
        removed_state = _pop_circuit_state(state, circuit_id, (root,))
        removed_store = _pop_circuit_state(store_data, circuit_id, (root,))
        return removed_state or removed_store


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


def _pop_circuit_state(
    owner: Any,
    circuit_id: str,
    roots: tuple[str, ...],
) -> bool:
    removed = False
    for root in roots:
        mapping = getattr(owner, root)
        if mapping.pop(circuit_id, None) is not None:
            removed = True
    return removed


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _friendly_circuit_mode(mode: Any) -> str:
    return _CIRCUIT_MODE_LABELS.get(_enum_value(mode), "Unknown")


def _friendly_power_flow(power_flow: Any) -> str:
    return _POWER_FLOW_LABELS.get(_enum_value(power_flow), "Unknown")
