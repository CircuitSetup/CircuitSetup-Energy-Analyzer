from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Self

from .models import AlertEvidence, CircuitConfig, Severity
from .ux import friendly_feature_name


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
    features: Mapping[str, float] = field(default_factory=dict)

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
    ) -> None:
        self.min_repeated = min_repeated
        self.min_total_score = min_total_score
        self.min_average_score = min_average_score
        self.min_baseline_confidence = min_baseline_confidence
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
    parts = [alert.circuit_id, _alert_feature(alert)]
    if alert.event_type is not None:
        parts.append(f"event={alert.event_type.value}")
    if config is not None:
        source_roles = sorted({sensor.role.value for sensor in config.sensors})
        if source_roles:
            parts.append(f"sources={'+'.join(source_roles)}")
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
            f"ratio={_ratio_bucket(alert.change_ratio)}",
        )
    )
    if (temperature := _temperature_context_bucket(alert.features)) is not None:
        parts.append(f"temp={temperature}")
    return "|".join(parts)


def _alert_feature(alert: AlertEvidence) -> str:
    if alert.feature:
        return alert.feature
    if alert.event_type is not None:
        return alert.event_type.value
    return "alert"


def _value_bucket(value: float) -> str:
    step = 0.5
    bucket_start = _floor_to_step(float(value), step)
    bucket_end = bucket_start + step
    return f"{bucket_start:.1f}-{bucket_end:.1f}"


def _ratio_bucket(change_ratio: float) -> str:
    percent = abs(float(change_ratio) * 100.0)
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


def _floor_to_step(value: float, step: float) -> float:
    return (value // step) * step
