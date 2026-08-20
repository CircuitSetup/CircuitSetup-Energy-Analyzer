"""Power quality baseline and alert processor."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ..alerting import Observation
from ..baseline import build_baseline
from ..models import ApplianceProfile, CircuitConfig, CircuitMode
from ..normalize import NormalizedCircuitSample
from ..power_quality import (
    PowerQualityEvidence,
    extract_power_quality_features,
    relationship_rms_score,
    score_power_quality_features,
    select_power_quality_evidence,
)
from ..profiles import supports_power_quality_analysis
from .base import AlertPolicy, FeatureResult, ProcessingContext, StateUpdate

type PowerQualityAlertPolicyProvider = Callable[[str], AlertPolicy]
type LearningMaturePredicate = Callable[[CircuitConfig, Any], bool]


@dataclass(slots=True)
class PowerQualityResult(FeatureResult):
    """Processor result with optional request to clear power quality state."""

    clear_power_quality_state: str | None = None


class PowerQualityProcessor:
    """Track power quality baselines, runtime evidence, and alerts."""

    name = "power_quality"

    def __init__(
        self,
        *,
        alert_policy_for_circuit: PowerQualityAlertPolicyProvider,
        learning_mature: LearningMaturePredicate,
        baseline_values: defaultdict[str, list[float]] | None = None,
    ) -> None:
        self._alert_policy_for_circuit = alert_policy_for_circuit
        self._learning_mature = learning_mature
        self._baseline_values = (
            baseline_values if baseline_values is not None else defaultdict(list)
        )

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> PowerQualityResult:
        """Record power quality state and return repeated anomaly alerts."""
        circuit_id = circuit_config.circuit_id
        if not supports_power_quality_analysis(circuit_config):
            return PowerQualityResult(
                state_updates=(
                    [StateUpdate(("learning_by_circuit", circuit_id), False)]
                    if (
                        circuit_config.mode is CircuitMode.MIXED
                        or circuit_config.appliance_profile is ApplianceProfile.MIXED
                    )
                    else []
                ),
                clear_power_quality_state=circuit_id,
            )
        policy = self._alert_policy_for_circuit(circuit_id)
        features = extract_power_quality_features(sample)
        if not features:
            return PowerQualityResult(
                state_updates=[
                    StateUpdate(("learning_by_circuit", circuit_id), True),
                ],
                clear_power_quality_state=circuit_id,
            )

        maintenance = context.store_data.maintenance_by_circuit.get(circuit_id, {})
        maintenance_active = (
            isinstance(maintenance, Mapping) and maintenance.get("active") is True
        )
        baselines: dict[str, Any] = {}
        learning_new_features = False
        store_dirty = False
        for feature, value in features.items():
            key = _baseline_key(circuit_id, feature)
            baseline = context.store_data.baselines.get(key)
            if baseline is None:
                if maintenance_active:
                    learning_new_features = True
                    continue
                values = self._baseline_values[key]
                values.append(value)
                if len(values) >= 15:
                    baseline = build_baseline(feature, values)
                    context.store_data.baselines[key] = baseline
                    store_dirty = True
                learning_new_features = True
            if baseline is not None:
                baselines[feature] = baseline

        scores = score_power_quality_features(features, baselines)
        evidence = select_power_quality_evidence(
            circuit_config,
            scores,
            min_relationship_score=policy.min_average_score,
        )

        mature = self._learning_mature(circuit_config, context.now)
        has_confident_scores = any(score.baseline_confidence >= 0.6 for score in scores)
        learning = learning_new_features or not mature or not has_confident_scores
        feature_result = PowerQualityResult(
            state_updates=[
                StateUpdate(("learning_by_circuit", circuit_id), learning),
                *power_quality_state_updates(circuit_id, scores, evidence),
            ],
            store_dirty=store_dirty,
        )
        if (
            maintenance_active
            or not mature
            or not has_confident_scores
            or evidence is None
        ):
            return feature_result

        alert = policy.observe(
            Observation(
                circuit_id=circuit_id,
                feature=evidence.feature,
                score=evidence.score,
                baseline_confidence=evidence.baseline_confidence,
                observed_at=context.now,
                observed_value=evidence.observed_value,
                baseline_value=evidence.baseline_value,
                value_metric=evidence.metric,
                message=evidence.message,
                features=evidence.features,
            )
        )
        if alert is not None:
            feature_result.alerts.append(alert)
            feature_result.notifications.append(alert)
        return feature_result


def power_quality_state_updates(
    circuit_id: str,
    scores: Iterable[Any],
    evidence: PowerQualityEvidence | None,
) -> list[StateUpdate]:
    """Build analyzer state updates for power quality scores and drifts."""

    def drift(primary: str, fallback: str) -> float:
        candidates = [
            score
            for feature in (primary, fallback)
            if (score := by_feature.get(feature)) is not None
        ]
        if not candidates:
            return 0.0
        score = max(
            candidates,
            key=lambda candidate: (
                abs(candidate.change_ratio),
                candidate.score,
            ),
        )
        return abs(score.change_ratio)

    scores = list(scores)
    by_feature = {score.feature: score for score in scores}
    return [
        StateUpdate(
            ("power_quality_score_by_circuit", circuit_id),
            relationship_rms_score(scores),
        ),
        StateUpdate(
            ("power_quality_evidence_by_circuit", circuit_id),
            evidence.message if evidence is not None else "",
        ),
        StateUpdate(
            ("reactive_power_drift_by_circuit", circuit_id),
            drift("reactive_power", "reactive_to_real_ratio"),
        ),
        StateUpdate(
            ("apparent_power_drift_by_circuit", circuit_id),
            drift("apparent_power", "apparent_to_real_ratio"),
        ),
        StateUpdate(
            ("power_factor_drift_by_circuit", circuit_id),
            drift("power_factor", "power_factor_deficit"),
        ),
    ]


def _baseline_key(circuit_id: str, feature: str) -> str:
    return f"{circuit_id}:{feature}"
