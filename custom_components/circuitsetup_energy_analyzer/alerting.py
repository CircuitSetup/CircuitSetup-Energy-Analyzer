from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any, Self

from .models import AlertEvidence, CircuitConfig, Severity
from .ux import friendly_feature_name

ALERT_FINGERPRINT_SCHEMA_VERSION = "alert:v2"


@dataclass(frozen=True, slots=True)
class Observation:
    """Single scored baseline deviation observation."""

    circuit_id: str
    feature: str
    score: float
    baseline_confidence: float
    observed_at: datetime
    observed_value: float = 0.0
    baseline_value: float = 0.0
    message: str = ""
    observation_key: str | None = None
    features: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))


class ConservativeAlertPolicy:
    """Require confident, repeated observations before producing alert evidence."""

    def __init__(
        self: Self,
        min_repeated: int = 3,
        min_total_score: float = 3.0,
        min_average_score: float = 1.5,
        min_baseline_confidence: float = 0.6,
        max_observation_age: timedelta = timedelta(days=7),
        max_episode_gap: timedelta = timedelta(days=2),
    ) -> None:
        self.min_repeated = min_repeated
        self.min_total_score = min_total_score
        self.min_average_score = min_average_score
        self.min_baseline_confidence = min_baseline_confidence
        self.max_observation_age = max_observation_age
        self.max_episode_gap = max_episode_gap
        self._observations: defaultdict[tuple[str, str], deque[Observation]] = (
            defaultdict(deque)
        )

    def observe(
        self: Self,
        observation: Observation,
        *,
        min_repeated: int | None = None,
    ) -> AlertEvidence | None:
        if observation.baseline_confidence < self.min_baseline_confidence:
            return None

        required_min_repeated = max(
            self.min_repeated,
            int(min_repeated) if min_repeated is not None else self.min_repeated,
        )
        key = (observation.circuit_id, observation.feature)
        observations = self._observations[key]
        self._prune_observation_episode(observations, observation.observed_at)
        if observation.observation_key is not None:
            for index, existing in enumerate(observations):
                if existing.observation_key == observation.observation_key:
                    observations[index] = observation
                    return None
        observations.append(observation)
        while len(observations) > required_min_repeated:
            observations.popleft()

        if len(observations) < required_min_repeated:
            return None

        total_score = sum(item.score for item in observations)
        average_score = total_score / len(observations)

        if (
            total_score < self.min_total_score
            or average_score < self.min_average_score
        ):
            return None

        first = observations[0]
        last = observations[-1]
        change_ratio = self._change_ratio(last.observed_value, last.baseline_value)
        feature_words = friendly_feature_name(observation.feature)
        message = last.message or (
            f"Possible issue: {feature_words} shows evidence of a "
            f"learned-baseline change across {len(observations)} recent "
            "observations."
        )
        features = dict(last.features) if last.features else {last.feature: last.score}

        return AlertEvidence(
            timestamp=last.observed_at,
            circuit_id=last.circuit_id,
            severity=Severity.WARNING,
            message=message,
            feature=last.feature,
            observed_value=last.observed_value,
            baseline_value=last.baseline_value,
            change_ratio=change_ratio,
            repeated_count=len(observations),
            first_seen=first.observed_at,
            last_seen=last.observed_at,
            features=features,
        )

    @staticmethod
    def _change_ratio(observed_value: float, baseline_value: float) -> float:
        if baseline_value == 0.0:
            return 0.0

        return (observed_value - baseline_value) / baseline_value

    def _prune_observation_episode(
        self: Self,
        observations: deque[Observation],
        observed_at: datetime,
    ) -> None:
        if observations and observed_at - observations[-1].observed_at > (
            self.max_episode_gap
        ):
            observations.clear()
            return

        oldest_allowed = observed_at - self.max_observation_age
        while observations and observations[0].observed_at < oldest_allowed:
            observations.popleft()


def alert_feedback_fingerprint_for_observation(
    observation: Observation,
    *,
    config: CircuitConfig | None = None,
) -> str:
    """Return the alert feedback key an observation would produce if promoted."""
    return alert_feedback_fingerprint(
        AlertEvidence(
            timestamp=observation.observed_at,
            circuit_id=observation.circuit_id,
            severity=Severity.WARNING,
            message=observation.message,
            feature=observation.feature,
            observed_value=observation.observed_value,
            baseline_value=observation.baseline_value,
            change_ratio=ConservativeAlertPolicy._change_ratio(
                observation.observed_value,
                observation.baseline_value,
            ),
            features=observation.features,
        ),
        config=config,
    )


def alert_feedback_fingerprint(
    alert: AlertEvidence,
    *,
    config: CircuitConfig | None = None,
) -> str:
    """Return a stable key for matching repeated versions of alert evidence."""
    parts = [ALERT_FINGERPRINT_SCHEMA_VERSION, alert.circuit_id, _alert_feature(alert)]
    if alert.event_type is not None:
        parts.append(f"event={alert.event_type.value}")
    if config is not None:
        source_roles = sorted({sensor.role.value for sensor in config.sensors})
        if source_roles:
            parts.append(f"sources={'+'.join(source_roles)}")
        source_mapping = _source_mapping_bucket(config)
        if source_mapping:
            parts.append(f"source_map={source_mapping}")
        parts.extend(
            (
                f"profile={config.appliance_profile.value}",
                f"mode={config.mode.value}",
                f"power_flow={config.power_flow.value}",
            )
        )
    parts.extend(
        (
            f"observed={_value_bucket(alert.observed_value)}",
            f"baseline={_value_bucket(alert.baseline_value)}",
            "direction="
            f"{_change_direction(alert.observed_value, alert.baseline_value)}",
            f"ratio={_ratio_bucket(alert)}",
        )
    )
    if (temperature := _temperature_context_bucket(alert.features)) is not None:
        parts.append(f"temp={temperature}")
    if (baseline_context := _baseline_context_bucket(alert.features)) is not None:
        parts.append(f"context={baseline_context}")
    return "|".join(parts)


def _alert_feature(alert: AlertEvidence) -> str:
    if alert.feature:
        return alert.feature
    if alert.event_type is not None:
        return alert.event_type.value
    return "alert"


def _source_mapping_bucket(config: CircuitConfig) -> str:
    mapped_sources = sorted(
        f"{sensor.role.value}:{sensor.entity_id}"
        for sensor in config.sensors
        if sensor.entity_id
    )
    return "+".join(mapped_sources)


def _value_bucket(value: float) -> str:
    if float(value) == 0.0:
        return "zero"
    step = 0.5
    bucket_start = _floor_to_step(float(value), step)
    bucket_end = bucket_start + step
    return f"{bucket_start:.1f}-{bucket_end:.1f}"


def _change_direction(observed_value: float, baseline_value: float) -> str:
    if observed_value > baseline_value:
        return "increase"
    if observed_value < baseline_value:
        return "decrease"
    return "no_change"


def _ratio_bucket(alert: AlertEvidence) -> str:
    if alert.baseline_value == 0.0:
        direction = _change_direction(alert.observed_value, alert.baseline_value)
        return f"zero_baseline_{direction}"
    percent = abs(float(alert.change_ratio) * 100.0)
    for bucket_start, bucket_end in (
        (0, 10),
        (10, 25),
        (25, 50),
        (50, 75),
        (75, 100),
        (100, 150),
        (150, 200),
    ):
        if percent < bucket_end:
            return f"{bucket_start}-{bucket_end}pct"
    return "200pct-plus"


def _temperature_context_bucket(features: Mapping[str, object]) -> str | None:
    for key in (
        "outdoor_temperature_f",
        "current_outdoor_temperature_f",
        "temperature_f",
        "outdoor_temperature",
        "current_outdoor_temperature",
    ):
        value = features.get(key)
        if isinstance(value, int | float):
            bucket_start = int(_floor_to_step(float(value), 5.0))
            return f"{bucket_start}-{bucket_start + 5}f"
    return None


def _baseline_context_bucket(features: Mapping[str, object]) -> str | None:
    if str(features.get("comparison_basis", "")).strip().lower() != "contextual":
        return None
    baseline_context = str(features.get("baseline_context", "")).strip()
    if not baseline_context:
        return None
    fallback_level = str(features.get("baseline_fallback_level", "")).strip()
    parts = ["contextual"]
    if fallback_level:
        parts.append(fallback_level)
    parts.append(baseline_context)
    return "+".join(parts)


def _floor_to_step(value: float, step: float) -> float:
    return (value // step) * step
