from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Self

from .const import STORAGE_KEY, STORAGE_VERSION
from .models import (
    AlertEvidence,
    BaselineStats,
    CircuitEvent,
    EventType,
    RetentionMode,
    Severity,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.storage import Store
else:
    HomeAssistant = Any
    Store = Any


RETENTION_WINDOWS: dict[RetentionMode, timedelta] = {
    RetentionMode.LIGHTWEIGHT: timedelta(days=14),
    RetentionMode.STANDARD: timedelta(days=45),
    RetentionMode.DIAGNOSTIC: timedelta(days=180),
}


@dataclass(slots=True)
class FeatureStoreData:
    """In-memory feature store payload."""

    events: list[CircuitEvent] = field(default_factory=list)
    baselines: dict[str, BaselineStats] = field(default_factory=dict)
    alerts: list[AlertEvidence] = field(default_factory=list)
    nilm_signatures: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    sensitivity_by_circuit: dict[str, str] = field(default_factory=dict)
    maintenance_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
    alert_feedback: dict[str, dict[str, Any]] = field(default_factory=dict)
    energy_usage_settings_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    energy_usage_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
    demand_settings_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    demand_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
    standby_settings_by_circuit: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    standby_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)


def event_to_dict(event: CircuitEvent) -> dict[str, Any]:
    """Serialize a circuit event for JSON storage."""
    return {
        "timestamp": event.timestamp.isoformat(),
        "circuit_id": event.circuit_id,
        "event_type": event.event_type.value,
        "severity": event.severity.value,
        "features": _features_to_dict(event.features),
    }


def event_from_dict(raw: dict[str, Any]) -> CircuitEvent:
    """Deserialize a circuit event from JSON storage."""
    return CircuitEvent(
        timestamp=datetime.fromisoformat(raw["timestamp"]),
        circuit_id=str(raw["circuit_id"]),
        event_type=EventType(raw["event_type"]),
        severity=Severity(raw.get("severity", Severity.INFO.value)),
        features=_features_to_dict(raw.get("features", {})),
    )


def baseline_to_dict(baseline: BaselineStats) -> dict[str, Any]:
    """Serialize baseline statistics for JSON storage."""
    return {
        "feature": baseline.feature,
        "sample_count": baseline.sample_count,
        "median": baseline.median,
        "mad": baseline.mad,
        "p10": baseline.p10,
        "p90": baseline.p90,
        "confidence": baseline.confidence,
    }


def baseline_from_dict(raw: dict[str, Any]) -> BaselineStats:
    """Deserialize baseline statistics from JSON storage."""
    return BaselineStats(
        feature=str(raw["feature"]),
        sample_count=int(raw["sample_count"]),
        median=float(raw["median"]),
        mad=float(raw["mad"]),
        p10=float(raw["p10"]),
        p90=float(raw["p90"]),
        confidence=float(raw["confidence"]),
    )


def alert_to_dict(alert: AlertEvidence) -> dict[str, Any]:
    """Serialize alert evidence for JSON storage."""
    return {
        "timestamp": alert.timestamp.isoformat(),
        "circuit_id": alert.circuit_id,
        "severity": alert.severity.value,
        "message": alert.message,
        "event_type": alert.event_type.value if alert.event_type else None,
        "features": _features_to_dict(alert.features),
        "feature": alert.feature,
        "observed_value": alert.observed_value,
        "baseline_value": alert.baseline_value,
        "change_ratio": alert.change_ratio,
        "repeated_count": alert.repeated_count,
        "first_seen": alert.first_seen.isoformat() if alert.first_seen else None,
        "last_seen": alert.last_seen.isoformat() if alert.last_seen else None,
    }


def alert_from_dict(raw: dict[str, Any]) -> AlertEvidence:
    """Deserialize alert evidence from JSON storage."""
    event_type = raw.get("event_type")
    first_seen = raw.get("first_seen")
    last_seen = raw.get("last_seen")
    return AlertEvidence(
        timestamp=datetime.fromisoformat(raw["timestamp"]),
        circuit_id=str(raw["circuit_id"]),
        severity=Severity(raw["severity"]),
        message=str(raw["message"]),
        event_type=EventType(event_type) if event_type else None,
        features=_features_to_dict(raw.get("features", {})),
        feature=str(raw.get("feature", "")),
        observed_value=float(raw.get("observed_value", 0.0)),
        baseline_value=float(raw.get("baseline_value", 0.0)),
        change_ratio=float(raw.get("change_ratio", 0.0)),
        repeated_count=int(raw.get("repeated_count", 1)),
        first_seen=datetime.fromisoformat(first_seen) if first_seen else None,
        last_seen=datetime.fromisoformat(last_seen) if last_seen else None,
    )


def feature_store_data_to_dict(data: FeatureStoreData) -> dict[str, Any]:
    """Serialize the full feature store payload for Home Assistant storage."""
    return {
        "events": [event_to_dict(event) for event in data.events],
        "baselines": {
            key: baseline_to_dict(baseline)
            for key, baseline in data.baselines.items()
        },
        "alerts": [alert_to_dict(alert) for alert in data.alerts],
        "nilm_signatures": {
            str(circuit_id): [dict(signature) for signature in signatures]
            for circuit_id, signatures in data.nilm_signatures.items()
        },
        "sensitivity_by_circuit": {
            str(circuit_id): str(sensitivity)
            for circuit_id, sensitivity in data.sensitivity_by_circuit.items()
        },
        "maintenance_by_circuit": _dict_of_dicts(data.maintenance_by_circuit),
        "alert_feedback": _dict_of_dicts(data.alert_feedback),
        "energy_usage_settings_by_circuit": _dict_of_dicts(
            data.energy_usage_settings_by_circuit
        ),
        "energy_usage_by_circuit": _dict_of_dicts(data.energy_usage_by_circuit),
        "demand_settings_by_circuit": _dict_of_dicts(data.demand_settings_by_circuit),
        "demand_by_circuit": _dict_of_dicts(data.demand_by_circuit),
        "standby_settings_by_circuit": _dict_of_dicts(
            data.standby_settings_by_circuit
        ),
        "standby_by_circuit": _dict_of_dicts(data.standby_by_circuit),
    }


def feature_store_data_from_dict(raw: dict[str, Any] | None) -> FeatureStoreData:
    """Deserialize the full feature store payload from Home Assistant storage."""
    if raw is None:
        return FeatureStoreData()

    return FeatureStoreData(
        events=[event_from_dict(event) for event in raw.get("events", [])],
        baselines={
            str(key): baseline_from_dict(baseline)
            for key, baseline in raw.get("baselines", {}).items()
        },
        alerts=[alert_from_dict(alert) for alert in raw.get("alerts", [])],
        nilm_signatures={
            str(circuit_id): [dict(signature) for signature in signatures]
            for circuit_id, signatures in raw.get("nilm_signatures", {}).items()
        },
        sensitivity_by_circuit={
            str(circuit_id): str(sensitivity)
            for circuit_id, sensitivity in raw.get(
                "sensitivity_by_circuit",
                {},
            ).items()
        },
        maintenance_by_circuit=_dict_of_dicts(
            raw.get("maintenance_by_circuit", {}),
        ),
        alert_feedback=_dict_of_dicts(raw.get("alert_feedback", {})),
        energy_usage_settings_by_circuit=_dict_of_dicts(
            raw.get("energy_usage_settings_by_circuit", {}),
        ),
        energy_usage_by_circuit=_dict_of_dicts(
            raw.get("energy_usage_by_circuit", {}),
        ),
        demand_settings_by_circuit=_dict_of_dicts(
            raw.get("demand_settings_by_circuit", {}),
        ),
        demand_by_circuit=_dict_of_dicts(raw.get("demand_by_circuit", {})),
        standby_settings_by_circuit=_dict_of_dicts(
            raw.get("standby_settings_by_circuit", {}),
        ),
        standby_by_circuit=_dict_of_dicts(raw.get("standby_by_circuit", {})),
    )


def prune_events(
    data: FeatureStoreData,
    retention_mode: RetentionMode,
    now: datetime,
) -> FeatureStoreData:
    """Return a new payload with events pruned according to retention mode."""
    cutoff = now - RETENTION_WINDOWS[retention_mode]
    return FeatureStoreData(
        events=[event for event in data.events if event.timestamp >= cutoff],
        baselines=data.baselines,
        alerts=data.alerts,
        nilm_signatures=data.nilm_signatures,
        sensitivity_by_circuit=data.sensitivity_by_circuit,
        maintenance_by_circuit=data.maintenance_by_circuit,
        alert_feedback=data.alert_feedback,
        energy_usage_settings_by_circuit=data.energy_usage_settings_by_circuit,
        energy_usage_by_circuit=data.energy_usage_by_circuit,
        demand_settings_by_circuit=data.demand_settings_by_circuit,
        demand_by_circuit=data.demand_by_circuit,
        standby_settings_by_circuit=data.standby_settings_by_circuit,
        standby_by_circuit=data.standby_by_circuit,
    )


class FeatureStore:
    """Home Assistant Store wrapper for analyzer feature data."""

    def __init__(self: Self, hass: HomeAssistant, entry_id: str) -> None:
        from homeassistant.helpers.storage import Store as HAStore

        self._store: Store[dict[str, Any]] = HAStore(
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY}.{entry_id}",
        )
        self.data = FeatureStoreData()

    async def async_load(self: Self) -> FeatureStoreData:
        """Load stored data and return the in-memory payload."""
        self.data = feature_store_data_from_dict(await self._store.async_load())
        return self.data

    async def async_save(self: Self) -> None:
        """Persist the current in-memory payload."""
        await self._store.async_save(feature_store_data_to_dict(self.data))

    async def async_prune_and_save(
        self: Self,
        retention_mode: RetentionMode,
        now: datetime,
    ) -> FeatureStoreData:
        """Prune retained events and persist the updated payload."""
        self.data = prune_events(self.data, retention_mode, now)
        await self.async_save()
        return self.data


def _features_to_dict(features: Any) -> dict[str, float]:
    return {str(key): float(value) for key, value in dict(features).items()}


def _dict_of_dicts(values: Any) -> dict[str, dict[str, Any]]:
    return {str(key): dict(value) for key, value in dict(values).items()}
