from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlencode

from .models import AlertEvidence, CircuitConfig, SensorRole

DEFAULT_ALERT_EVIDENCE_PATH = "/circuitsetup-energy-analyzer/alert-evidence"
MAX_GRAPH_ENTITIES = 8

_FEATURE_ROLE_HINTS: tuple[tuple[tuple[str, ...], tuple[SensorRole, ...]], ...] = (
    (
        ("leg_imbalance", "phase", "capacity"),
        (SensorRole.REAL_POWER, SensorRole.CURRENT),
    ),
    (
        ("reactive", "var"),
        (SensorRole.REACTIVE_POWER, SensorRole.REAL_POWER, SensorRole.POWER_FACTOR),
    ),
    (
        ("power_factor", "pf"),
        (SensorRole.POWER_FACTOR, SensorRole.REAL_POWER, SensorRole.APPARENT_POWER),
    ),
    (
        ("apparent", "va"),
        (SensorRole.APPARENT_POWER, SensorRole.REAL_POWER, SensorRole.POWER_FACTOR),
    ),
    (
        ("energy", "goal", "billing", "cost", "utility"),
        (SensorRole.ENERGY, SensorRole.REAL_POWER),
    ),
    (
        ("demand", "always_on", "standby", "cycle", "activity"),
        (SensorRole.REAL_POWER, SensorRole.CURRENT),
    ),
    (
        ("voltage", "sag", "swell"),
        (SensorRole.VOLTAGE, SensorRole.REAL_POWER, SensorRole.CURRENT),
    ),
)

_DEFAULT_ROLES = (
    SensorRole.REAL_POWER,
    SensorRole.CURRENT,
    SensorRole.REACTIVE_POWER,
    SensorRole.APPARENT_POWER,
    SensorRole.POWER_FACTOR,
    SensorRole.ENERGY,
)


def alert_evidence_path(
    alert: AlertEvidence, *, dashboard_path: str = DEFAULT_ALERT_EVIDENCE_PATH
) -> str:
    """Return a relative Home Assistant path for an alert evidence view."""
    from .notifications import notification_id_for_alert

    feature = _feature_for_alert(alert)
    params = urlencode(
        {
            "alert_id": notification_id_for_alert(alert),
            "circuit_id": alert.circuit_id,
            "feature": feature,
        }
    )
    return f"{dashboard_path}?{params}"


def alert_graph_entities(
    alert: AlertEvidence,
    config: CircuitConfig | None,
    *,
    max_entities: int = MAX_GRAPH_ENTITIES,
) -> tuple[str, ...]:
    """Return configured source entities ordered by relevance to the alert feature."""
    if config is None or max_entities <= 0:
        return ()

    selected: list[str] = []
    seen: set[str] = set()
    for role in _roles_for_feature(_feature_for_alert(alert)):
        for sensor in config.sensors:
            if sensor.role != role or sensor.entity_id in seen:
                continue
            selected.append(sensor.entity_id)
            seen.add(sensor.entity_id)
            if len(selected) >= max_entities:
                return tuple(selected)

    return tuple(selected)


def alert_source_entities(config: CircuitConfig | None) -> tuple[str, ...]:
    """Return all configured source entity ids without duplicates."""
    if config is None:
        return ()

    entities: list[str] = []
    seen: set[str] = set()
    for sensor in config.sensors:
        if sensor.entity_id in seen:
            continue
        entities.append(sensor.entity_id)
        seen.add(sensor.entity_id)
    return tuple(entities)


def alert_graph_window(
    alert: AlertEvidence, *, padding: timedelta = timedelta(hours=2)
) -> tuple[datetime, datetime]:
    """Return the graph start/end datetimes around the alert evidence window."""
    start = alert.first_seen or alert.timestamp
    end = alert.last_seen or alert.timestamp
    return (start - padding, end + padding)


def _roles_for_feature(feature: str) -> tuple[SensorRole, ...]:
    normalized = feature.lower()
    for hints, roles in _FEATURE_ROLE_HINTS:
        if any(hint in normalized for hint in hints):
            return roles
    return _DEFAULT_ROLES


def _feature_for_alert(alert: AlertEvidence) -> str:
    return alert.feature or (
        alert.event_type.value if alert.event_type is not None else "alert"
    )
