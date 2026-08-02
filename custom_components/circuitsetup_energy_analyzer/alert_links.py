from __future__ import annotations

import math
from datetime import datetime, timedelta
from urllib.parse import urlencode

from .models import AlertEvidence, CircuitConfig, SensorRole

DEFAULT_ALERT_EVIDENCE_PATH = "/circuitsetup-energy-analyzer-evidence"
DEFAULT_ALERT_EVIDENCE_DASHBOARD_PATH = (
    "/circuitsetup-energy-analyzer/alert-evidence"
)
MAX_GRAPH_ENTITIES = 8

_FEATURE_ROLE_HINTS: tuple[tuple[tuple[str, ...], tuple[SensorRole, ...]], ...] = (
    (
        ("efficiency_degradation",),
        (SensorRole.ENERGY, SensorRole.REAL_POWER),
    ),
    (
        ("repeated_short_cycle",),
        (SensorRole.REAL_POWER,),
    ),
    (
        ("relationship",),
        (
            SensorRole.REACTIVE_POWER,
            SensorRole.REAL_POWER,
            SensorRole.POWER_FACTOR,
            SensorRole.APPARENT_POWER,
        ),
    ),
    (
        ("leg_imbalance", "phase", "capacity"),
        (SensorRole.REAL_POWER, SensorRole.CURRENT, SensorRole.PEAK_CURRENT),
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
        ("solar", "mains_balance"),
        (SensorRole.REAL_POWER,),
    ),
    (("demand",), (SensorRole.REAL_POWER,)),
    (
        (
            "always_on",
            "standby",
            "cycle",
            "activity",
            "schedule",
            "running",
            "runtime",
        ),
        (SensorRole.REAL_POWER, SensorRole.CURRENT),
    ),
    (("frequency",), (SensorRole.FREQUENCY,)),
    (("real_power",), (SensorRole.REAL_POWER,)),
    (("current",), (SensorRole.CURRENT,)),
    (("nilm",), (SensorRole.REAL_POWER,)),
    (
        ("rain_pump", "water_flow", "pump", "flow"),
        (SensorRole.REAL_POWER, SensorRole.CURRENT, SensorRole.ENERGY),
    ),
    (
        ("voltage", "sag", "swell"),
        (SensorRole.VOLTAGE, SensorRole.REAL_POWER, SensorRole.CURRENT),
    ),
)


def alert_evidence_path(
    alert: AlertEvidence, *, dashboard_path: str = DEFAULT_ALERT_EVIDENCE_PATH
) -> str:
    """Return a relative Home Assistant path for an alert evidence view."""
    from .notifications import notification_id_for_alert

    feature = _feature_for_alert(alert)
    assignment_id = str(alert.features.get("assignment_id") or "").strip()
    mains_circuit_id = str(
        alert.features.get("mains_circuit_id") or alert.circuit_id
    ).strip()
    values = {
        "circuit_id": mains_circuit_id,
        "alert_id": notification_id_for_alert(alert),
        "feature": feature,
    }
    if assignment_id:
        values.update(
            {
                "assignment_id": assignment_id,
                "nilm_workspace": "1",
                "appliance_detail": "1",
            }
        )
    params = urlencode(values)
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

    roles = _roles_for_feature(_feature_for_alert(alert))
    if not roles and alert.value_metric:
        roles = _roles_for_feature(alert.value_metric)

    selected: list[str] = []
    seen: set[str] = set()
    for role in roles:
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


def alert_graph_window(alert: AlertEvidence) -> tuple[datetime, datetime]:
    """Return the alert evidence interval with enough surrounding context."""
    raw_start = alert.first_seen or alert.timestamp
    raw_end = alert.last_seen or alert.timestamp
    start = min(raw_start, raw_end)
    end = max(raw_start, raw_end)

    if "demand" in _feature_for_alert(alert).lower():
        try:
            demand_window_minutes = float(
                alert.features.get("demand_window_minutes", 0.0)
            )
        except (TypeError, ValueError):
            demand_window_minutes = 0.0
        if math.isfinite(demand_window_minutes) and 0.0 < demand_window_minutes <= 240:
            try:
                start = min(
                    start,
                    alert.timestamp - timedelta(minutes=demand_window_minutes),
                )
            except OverflowError:
                pass

    if start == end:
        point_padding = timedelta(minutes=15)
        return (start - point_padding, end + point_padding)

    context_padding = timedelta(minutes=10)
    return (start - context_padding, end + context_padding)


def _roles_for_feature(feature: str) -> tuple[SensorRole, ...]:
    normalized = feature.lower()
    for hints, roles in _FEATURE_ROLE_HINTS:
        if any(hint in normalized for hint in hints):
            return roles
    return ()


def _feature_for_alert(alert: AlertEvidence) -> str:
    return alert.feature or (
        alert.event_type.value if alert.event_type is not None else "alert"
    )
