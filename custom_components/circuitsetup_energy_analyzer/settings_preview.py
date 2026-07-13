from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

PREVIEW_HISTORY_DAYS = 14
PREVIEW_SAMPLE_LIMIT = 500
PREVIEW_EXAMPLE_LIMIT = 5

SUPPORTED_SETTING_KEYS = frozenset(
    {
        "daily_spike_ratio",
        "operating_on_threshold_w",
        "operating_off_threshold_w",
        "standby_threshold_w",
        "warning_ratio",
        "capacity_warning_ratio",
        "demand_limit_w",
        "leg_imbalance_warning_ratio",
        "apparent_power_tolerance_percent",
        "power_factor_tolerance",
        "nilm_confidence_threshold",
    }
)
_BELOW_THRESHOLD_SETTINGS = frozenset(
    {"operating_off_threshold_w", "nilm_confidence_threshold"}
)
_STATE_CHANGE_SETTINGS = frozenset(
    {"operating_on_threshold_w", "operating_off_threshold_w"}
)
_CONTEXT_FEATURE_BY_SETTING = {
    "daily_spike_ratio": "daily_energy_kwh",
    "demand_limit_w": "peak_demand_w",
    "standby_threshold_w": "standby_power_w",
}


@dataclass(frozen=True, slots=True)
class SettingImpactPreview:
    """Bounded dry-run comparison for one proposed setting change."""

    setting_key: str
    current_value: Any
    candidate_value: Any
    history_start: datetime
    history_end: datetime
    observations_evaluated: int
    current_alert_count: int
    candidate_alert_count: int
    current_state_change_count: int | None
    candidate_state_change_count: int | None
    examples_added: tuple[str, ...]
    examples_removed: tuple[str, ...]
    confidence: float
    limitations: tuple[str, ...]
    available: bool = True

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["history_start"] = self.history_start.isoformat()
        payload["history_end"] = self.history_end.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class _Observation:
    timestamp: datetime
    value: float
    label: str


def setting_preview_observations(
    store_data: Any,
    circuit_id: str,
    setting_key: str,
) -> list[dict[str, Any]]:
    """Extract threshold inputs from retained analyzer history without mutation."""
    observations: list[dict[str, Any]] = []
    contextual = getattr(
        store_data, "contextual_baseline_samples_by_circuit", {}
    )
    raw_samples = (
        contextual.get(circuit_id, ()) if isinstance(contextual, Mapping) else ()
    )
    expected_feature = _CONTEXT_FEATURE_BY_SETTING.get(setting_key)
    matching_samples = [
        raw
        for raw in raw_samples
        if isinstance(raw, Mapping) and raw.get("feature") == expected_feature
    ]
    daily_baseline = _median(
        value
        for raw in matching_samples
        if (value := _number_or_none(raw.get("value"))) is not None
    )
    for raw in matching_samples:
        value = _number_or_none(raw.get("value"))
        timestamp = _datetime_or_none(raw.get("timestamp"))
        if value is None or timestamp is None:
            continue
        if setting_key == "daily_spike_ratio":
            if daily_baseline is None or daily_baseline <= 0.0:
                continue
            value = max((value / daily_baseline) - 1.0, 0.0)
        observations.append(_preview_observation(timestamp, value))

    if setting_key in _STATE_CHANGE_SETTINGS:
        for event in getattr(store_data, "events", ()):
            if getattr(event, "circuit_id", None) != circuit_id:
                continue
            features = getattr(event, "features", {})
            if not isinstance(features, Mapping):
                continue
            value = _first_number(
                features,
                "raw_real_power_w",
                "startup_power_w",
                "stop_power_w",
                "real_power_w",
                "real_power",
                "power_w",
            )
            timestamp = getattr(event, "timestamp", None)
            if value is not None and isinstance(timestamp, datetime):
                observations.append(_preview_observation(timestamp, value))

    for alert in getattr(store_data, "alerts", ()):
        if getattr(alert, "circuit_id", None) != circuit_id:
            continue
        value = _alert_preview_value(alert, setting_key)
        timestamp = getattr(alert, "timestamp", None)
        if value is not None and isinstance(timestamp, datetime):
            observations.append(_preview_observation(timestamp, value))

    deduplicated = {
        (str(item["timestamp"]), float(item["value"])): item for item in observations
    }
    return sorted(
        deduplicated.values(),
        key=lambda item: _instant(datetime.fromisoformat(str(item["timestamp"]))),
    )


def build_setting_impact_preview(
    setting_key: str,
    current_value: Any,
    candidate_value: Any,
    observations: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
) -> SettingImpactPreview:
    """Compare current and candidate thresholds against retained observations."""
    window_start = now - timedelta(days=PREVIEW_HISTORY_DAYS)
    limitations = [
        "Preview uses retained analyzer history from at most 14 days.",
        "It may not exactly reproduce future behavior.",
    ]
    if setting_key not in SUPPORTED_SETTING_KEYS:
        limitations.insert(0, f"Historical preview is not supported for {setting_key}.")
        return _empty_preview(
            setting_key,
            current_value,
            candidate_value,
            window_start,
            now,
            limitations,
            available=False,
        )

    current_threshold = _number_or_none(current_value)
    candidate_threshold = _number_or_none(candidate_value)
    if current_threshold is None or candidate_threshold is None:
        limitations.insert(0, "Current and candidate values must be finite numbers.")
        return _empty_preview(
            setting_key,
            current_value,
            candidate_value,
            window_start,
            now,
            limitations,
            available=False,
        )

    retained = sorted(
        (
            observation
            for raw in observations
            if (observation := _observation_from_mapping(raw)) is not None
            and _instant(window_start)
            <= _instant(observation.timestamp)
            <= _instant(now)
        ),
        key=lambda item: _instant(item.timestamp),
    )
    if len(retained) > PREVIEW_SAMPLE_LIMIT:
        retained = retained[-PREVIEW_SAMPLE_LIMIT:]
        limitations.append("Preview is limited to the newest 500 observations.")
    if not retained:
        limitations.insert(0, "Not enough retained history is available for a preview.")
        return _empty_preview(
            setting_key,
            current_value,
            candidate_value,
            window_start,
            now,
            limitations,
        )

    current_matches = [
        _matches(setting_key, item.value, current_threshold) for item in retained
    ]
    candidate_matches = [
        _matches(setting_key, item.value, candidate_threshold) for item in retained
    ]
    added = tuple(
        item.label
        for item, current, candidate in zip(
            retained, current_matches, candidate_matches, strict=True
        )
        if candidate and not current
    )[:PREVIEW_EXAMPLE_LIMIT]
    removed = tuple(
        item.label
        for item, current, candidate in zip(
            retained, current_matches, candidate_matches, strict=True
        )
        if current and not candidate
    )[:PREVIEW_EXAMPLE_LIMIT]
    state_setting = setting_key in _STATE_CHANGE_SETTINGS
    if state_setting:
        limitations.append(
            "Operating previews approximate threshold crossings from retained "
            "transitions and do not replay dwell or hysteresis."
        )

    return SettingImpactPreview(
        setting_key=setting_key,
        current_value=current_value,
        candidate_value=candidate_value,
        history_start=retained[0].timestamp,
        history_end=retained[-1].timestamp,
        observations_evaluated=len(retained),
        current_alert_count=0 if state_setting else sum(current_matches),
        candidate_alert_count=0 if state_setting else sum(candidate_matches),
        current_state_change_count=(
            _state_change_count(current_matches) if state_setting else None
        ),
        candidate_state_change_count=(
            _state_change_count(candidate_matches) if state_setting else None
        ),
        examples_added=added,
        examples_removed=removed,
        confidence=round(min(len(retained) / 20.0, 1.0), 2),
        limitations=tuple(limitations),
    )


def _empty_preview(
    setting_key: str,
    current_value: Any,
    candidate_value: Any,
    history_start: datetime,
    history_end: datetime,
    limitations: list[str],
    *,
    available: bool = True,
) -> SettingImpactPreview:
    return SettingImpactPreview(
        setting_key=setting_key,
        current_value=current_value,
        candidate_value=candidate_value,
        history_start=history_start,
        history_end=history_end,
        observations_evaluated=0,
        current_alert_count=0,
        candidate_alert_count=0,
        current_state_change_count=None,
        candidate_state_change_count=None,
        examples_added=(),
        examples_removed=(),
        confidence=0.0,
        limitations=tuple(limitations),
        available=available,
    )


def _observation_from_mapping(raw: Mapping[str, Any]) -> _Observation | None:
    timestamp = _datetime_or_none(raw.get("timestamp"))
    value = _number_or_none(raw.get("value"))
    if timestamp is None or value is None:
        return None
    label = str(raw.get("label") or timestamp.date().isoformat())
    return _Observation(timestamp=timestamp, value=value, label=label)


def _matches(setting_key: str, value: float, threshold: float) -> bool:
    if setting_key in _BELOW_THRESHOLD_SETTINGS:
        return value < threshold
    return value > threshold


def _alert_preview_value(alert: Any, setting_key: str) -> float | None:
    feature = str(getattr(alert, "feature", ""))
    features = getattr(alert, "features", {})
    if not isinstance(features, Mapping):
        features = {}
    if setting_key == "daily_spike_ratio" and feature in {
        "daily_energy_spike",
        "daily_energy_usage_spike",
    }:
        return _number_or_none(getattr(alert, "change_ratio", None))
    if setting_key == "demand_limit_w" and feature == "demand_limit":
        return _number_or_none(getattr(alert, "observed_value", None))
    if setting_key == "standby_threshold_w" and feature in {
        "always_on_power",
        "standby_power",
    }:
        return _number_or_none(getattr(alert, "observed_value", None))
    if setting_key in {"warning_ratio", "capacity_warning_ratio"} and feature == (
        "circuit_capacity"
    ):
        percent = _number_or_none(features.get("capacity_usage_percent"))
        if percent is not None:
            return percent / 100.0
        current = _number_or_none(getattr(alert, "observed_value", None))
        breaker = _number_or_none(features.get("breaker_amps"))
        return current / breaker if current is not None and breaker else None
    if setting_key == "leg_imbalance_warning_ratio" and feature in {
        "dual_phase_leg_imbalance",
        "leg_imbalance",
    }:
        return _number_or_none(getattr(alert, "observed_value", None))
    if setting_key == "apparent_power_tolerance_percent" and feature in {
        "metric_consistency",
        "power_metric_consistency",
    }:
        value = _number_or_none(features.get("apparent_power_difference_percent"))
        return abs(value) if value is not None else None
    if setting_key == "power_factor_tolerance" and feature in {
        "metric_consistency",
        "power_metric_consistency",
    }:
        value = _number_or_none(features.get("power_factor_difference"))
        return abs(value) if value is not None else None
    if setting_key == "nilm_confidence_threshold" and feature.startswith("nilm_"):
        return _number_or_none(getattr(alert, "observed_value", None))
    return None


def _state_change_count(states: list[bool]) -> int:
    return sum(
        left != right for left, right in zip(states, states[1:], strict=False)
    )


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _number_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _preview_observation(timestamp: datetime, value: float) -> dict[str, Any]:
    return {
        "timestamp": timestamp.isoformat(),
        "value": value,
        "label": f"{timestamp.strftime('%b')} {timestamp.day}",
    }


def _first_number(values: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _number_or_none(values.get(key))
        if value is not None:
            return value
    return None


def _median(values: Iterable[float]) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _instant(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
