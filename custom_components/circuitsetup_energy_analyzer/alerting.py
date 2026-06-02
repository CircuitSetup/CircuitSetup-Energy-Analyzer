from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Self

from .models import AlertEvidence, Severity


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
            defaultdict(lambda: deque(maxlen=self.min_repeated))
        )

    def observe(self: Self, observation: Observation) -> AlertEvidence | None:
        if observation.baseline_confidence < self.min_baseline_confidence:
            return None

        key = (observation.circuit_id, observation.feature)
        observations = self._observations[key]
        observations.append(observation)

        if len(observations) < self.min_repeated:
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
        feature_words = observation.feature.replace("_", " ")
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
