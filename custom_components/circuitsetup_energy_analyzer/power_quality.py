from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import isfinite, sqrt
from types import MappingProxyType

from .baseline import score_deviation
from .models import (
    ApplianceProfile,
    BaselineStats,
    CircuitConfig,
    CircuitMode,
    CircuitSample,
)

DEFAULT_LOAD_FLOOR_W = 80.0
MIN_RELATIONSHIP_SCORE = 1.5
STABLE_REAL_POWER_SCORE = 1.2
STABLE_REAL_POWER_RATIO = 0.10

UNITLESS_FEATURE_SPREAD_FLOORS = {
    "power_factor": 0.01,
    "power_factor_deficit": 0.01,
    "reactive_to_real_ratio": 0.02,
    "apparent_to_real_ratio": 0.02,
}

MOTOR_PROFILES = frozenset(
    {
        ApplianceProfile.REFRIGERATOR,
        ApplianceProfile.FREEZER,
        ApplianceProfile.HVAC,
        ApplianceProfile.POOL_PUMP,
        ApplianceProfile.WELL_PUMP,
        ApplianceProfile.SUMP_PUMP,
        ApplianceProfile.MOTOR_LOAD,
    }
)
RESISTIVE_PROFILES = frozenset(
    {
        ApplianceProfile.WATER_HEATER,
        ApplianceProfile.OVEN,
        ApplianceProfile.DRYER,
        ApplianceProfile.RESISTIVE_LOAD,
    }
)


@dataclass(frozen=True, slots=True)
class PowerQualityFeatureScore:
    """Deviation score for one power-quality feature."""

    feature: str
    observed_value: float
    baseline_value: float
    score: float
    baseline_confidence: float
    change_ratio: float


@dataclass(frozen=True, slots=True)
class PowerQualityEvidence:
    """Selected relationship evidence for one circuit observation."""

    feature: str
    message: str
    observed_value: float
    baseline_value: float
    change_ratio: float
    score: float
    baseline_confidence: float
    features: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))


def extract_power_quality_features(
    sample: CircuitSample,
    *,
    load_floor_w: float = DEFAULT_LOAD_FLOOR_W,
) -> dict[str, float]:
    """Extract direct and derived power-quality features from a sample."""
    values: dict[str, float] = {}
    real_power = _number_or_none(getattr(sample, "real_power", None))
    reactive_power = _number_or_none(getattr(sample, "reactive_power", None))
    apparent_power = _number_or_none(getattr(sample, "apparent_power", None))
    power_factor = _number_or_none(getattr(sample, "power_factor", None))

    if real_power is not None:
        values["real_power"] = real_power
    if reactive_power is not None:
        values["reactive_power"] = reactive_power
    if apparent_power is not None:
        values["apparent_power"] = apparent_power

    loaded = real_power is not None and abs(real_power) >= load_floor_w
    if power_factor is not None and loaded and abs(power_factor) <= 1.0:
        values["power_factor"] = power_factor
        values["power_factor_deficit"] = 1.0 - abs(power_factor)

    if loaded and real_power is not None and real_power != 0.0:
        denominator = abs(real_power)
        if reactive_power is not None:
            values["reactive_to_real_ratio"] = reactive_power / denominator
        if apparent_power is not None:
            values["apparent_to_real_ratio"] = apparent_power / denominator

    if loaded and all(
        value is not None for value in (real_power, reactive_power, apparent_power)
    ):
        values["apparent_power_residual"] = apparent_power - sqrt(
            (real_power * real_power) + (reactive_power * reactive_power)
        )

    return values


def score_power_quality_features(
    features: Mapping[str, float],
    baselines: Mapping[str, BaselineStats],
    *,
    min_confidence: float = 0.6,
) -> list[PowerQualityFeatureScore]:
    """Score available power-quality features against learned baselines."""
    scores: list[PowerQualityFeatureScore] = []
    for feature, observed in features.items():
        baseline = baselines.get(feature)
        if baseline is None or baseline.confidence < min_confidence:
            continue
        scores.append(
            PowerQualityFeatureScore(
                feature=feature,
                observed_value=observed,
                baseline_value=baseline.median,
                score=_score_feature_deviation(feature, observed, baseline),
                baseline_confidence=baseline.confidence,
                change_ratio=_change_ratio(observed, baseline.median),
            )
        )
    return scores


def relationship_rms_score(scores: Sequence[PowerQualityFeatureScore]) -> float:
    """Return robust RMS score across non-real-power relationship features."""
    relationship_scores = [
        score.score
        for score in scores
        if score.feature
        not in {
            "real_power",
            "apparent_power_residual",
        }
    ]
    if not relationship_scores:
        return 0.0
    return sqrt(
        sum(score * score for score in relationship_scores) / len(relationship_scores)
    )


def select_power_quality_evidence(
    config: CircuitConfig,
    scores: Sequence[PowerQualityFeatureScore],
    *,
    min_relationship_score: float = MIN_RELATIONSHIP_SCORE,
) -> PowerQualityEvidence | None:
    """Select the strongest user-facing relationship evidence."""
    if (
        config.appliance_profile is ApplianceProfile.MIXED
        or config.mode is CircuitMode.MIXED
    ):
        return None

    by_feature = {score.feature: score for score in scores}
    real_score = by_feature.get("real_power")
    if _relationship_contributor_count(scores) < 2:
        return _real_power_fallback(by_feature)

    rms_score = relationship_rms_score(scores)
    if rms_score < min_relationship_score:
        return _real_power_fallback(by_feature)

    stable_real = _real_power_is_stable(real_score)
    evidence_features = {
        score.feature: score.score
        for score in scores
        if score.feature != "apparent_power_residual"
    }
    evidence_features["relationship_rms"] = rms_score

    reactive_score = _strongest(
        by_feature.get("reactive_to_real_ratio"),
        by_feature.get("reactive_power"),
    )
    apparent_score = _strongest(
        by_feature.get("apparent_to_real_ratio"),
        by_feature.get("apparent_power"),
    )
    pf_score = _strongest(
        by_feature.get("power_factor_deficit"),
        by_feature.get("power_factor"),
    )

    if config.appliance_profile in RESISTIVE_PROFILES:
        resistive_score = _strongest(
            by_feature.get("reactive_to_real_ratio"),
            pf_score,
        )
        if not _score_high(resistive_score, min_relationship_score) and stable_real:
            resistive_score = by_feature.get("reactive_power")
        if _score_high(resistive_score, min_relationship_score):
            return _evidence(
                "resistive_load_became_reactive",
                "Possible issue: a mostly resistive circuit shows repeated reactive "
                "power or power-factor behavior that differs from its learned "
                "baseline.",
                resistive_score,
                rms_score,
                evidence_features,
                by_feature,
            )

    if stable_real and _score_high(reactive_score, min_relationship_score):
        return _evidence(
            "reactive_shift_under_stable_real_power",
            "Possible issue: reactive power changed while real power stayed near "
            "its learned baseline across recent observations.",
            reactive_score,
            rms_score,
            evidence_features,
            by_feature,
        )

    if stable_real and _score_high(pf_score, min_relationship_score):
        return _evidence(
            "power_factor_shift_under_load",
            "Possible issue: power factor changed under a similar real-power load "
            "across recent observations.",
            pf_score,
            rms_score,
            evidence_features,
            by_feature,
        )

    if stable_real and _score_high(apparent_score, min_relationship_score):
        return _evidence(
            "apparent_power_shift",
            "Possible issue: apparent power changed while real power stayed near "
            "baseline, suggesting more non-real-power burden for similar useful power.",
            apparent_score,
            rms_score,
            evidence_features,
            by_feature,
        )

    if config.mode is CircuitMode.DUAL_PHASE and rms_score >= min_relationship_score:
        selected = _strongest(reactive_score, pf_score, apparent_score)
        return _evidence(
            "split_phase_relationship_changed",
            "Possible issue: the combined split-phase W/VAR/VA/PF relationship "
            "changed from its learned baseline across recent observations.",
            selected,
            rms_score,
            evidence_features,
            by_feature,
        )

    if (
        config.appliance_profile in MOTOR_PROFILES
        and rms_score >= min_relationship_score
    ):
        selected = _strongest(reactive_score, pf_score, apparent_score)
        return _evidence(
            "motor_relationship_changed",
            "Possible issue: motor-load W/VAR/VA/PF behavior changed from its "
            "learned baseline across recent observations.",
            selected,
            rms_score,
            evidence_features,
            by_feature,
        )

    return _real_power_fallback(by_feature)


def _evidence(
    feature: str,
    message: str,
    selected: PowerQualityFeatureScore | None,
    rms_score: float,
    features: Mapping[str, float],
    by_feature: Mapping[str, PowerQualityFeatureScore],
) -> PowerQualityEvidence | None:
    if selected is None:
        return None
    confidence_values = [
        selected.baseline_confidence,
        *(
            score.baseline_confidence
            for feature_name in features
            if feature_name != "relationship_rms"
            if (score := by_feature.get(feature_name)) is not None
        ),
    ]
    return PowerQualityEvidence(
        feature=feature,
        message=message,
        observed_value=selected.observed_value,
        baseline_value=selected.baseline_value,
        change_ratio=selected.change_ratio,
        score=max(selected.score, rms_score),
        baseline_confidence=min(confidence_values)
        if confidence_values
        else selected.baseline_confidence,
        features=features,
    )


def _real_power_fallback(
    by_feature: Mapping[str, PowerQualityFeatureScore],
) -> PowerQualityEvidence | None:
    real_score = by_feature.get("real_power")
    if real_score is None or real_score.score < MIN_RELATIONSHIP_SCORE:
        return None
    return PowerQualityEvidence(
        feature="real_power",
        message="",
        observed_value=real_score.observed_value,
        baseline_value=real_score.baseline_value,
        change_ratio=real_score.change_ratio,
        score=real_score.score,
        baseline_confidence=real_score.baseline_confidence,
        features={"real_power": real_score.score},
    )


def _real_power_is_stable(score: PowerQualityFeatureScore | None) -> bool:
    if score is None:
        return False
    return (
        score.score <= STABLE_REAL_POWER_SCORE
        or abs(score.change_ratio) <= STABLE_REAL_POWER_RATIO
    )


def _relationship_contributor_count(scores: Sequence[PowerQualityFeatureScore]) -> int:
    return sum(
        1
        for score in scores
        if score.feature
        not in {
            "real_power",
            "apparent_power_residual",
        }
    )


def _score_high(score: PowerQualityFeatureScore | None, threshold: float) -> bool:
    return score is not None and score.score >= threshold


def _strongest(
    *scores: PowerQualityFeatureScore | None,
) -> PowerQualityFeatureScore | None:
    available = [score for score in scores if score is not None]
    if not available:
        return None
    return max(available, key=lambda score: score.score)


def _change_ratio(observed: float, baseline: float) -> float:
    if baseline == 0.0:
        return 0.0
    return (observed - baseline) / baseline


def _score_feature_deviation(
    feature: str,
    observed: float,
    baseline: BaselineStats,
) -> float:
    spread_floor = UNITLESS_FEATURE_SPREAD_FLOORS.get(feature)
    if spread_floor is None:
        return score_deviation(observed, baseline)
    spread = max(baseline.mad * 1.4826, spread_floor)
    return abs(observed - baseline.median) / spread


def _number_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not isfinite(number):
        return None
    return number
