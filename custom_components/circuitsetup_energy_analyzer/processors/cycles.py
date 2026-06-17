"""Run-cycle anomaly processor."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from ..alerting import Observation
from ..baseline import build_baseline
from ..contextual_baseline import (
    ContextualBaselineSample,
    build_context_for_sample,
    contextual_stats_storage_key,
    contextual_stats_to_dict,
    daily_energy_fallback_contexts,
    select_contextual_baseline,
    stored_contextual_samples,
    upsert_contextual_sample,
)
from ..cycles import (
    RUN_CYCLE_DURATION_FEATURE,
    RUN_CYCLE_DUTY_CYCLE_FEATURE,
    RUN_CYCLE_START_COUNT_FEATURE,
    cycle_baseline_feature_values,
    select_cycle_anomaly_evidence,
    summarize_circuit_cycles,
)
from ..models import AlertEvidence, BaselineStats, CircuitConfig
from ..normalize import NormalizedCircuitSample
from ..storage import FeatureStoreData
from .base import FeatureResult, ProcessingContext


class _AlertPolicy(Protocol):
    """Small alert policy surface used by this processor."""

    min_average_score: float

    def observe(self, observation: Observation) -> AlertEvidence | None:
        """Fold an observation into the alert policy."""


type CycleAlertPolicyProvider = Callable[[str], _AlertPolicy]
type LearningMaturityProvider = Callable[[CircuitConfig, datetime], bool]


class RunCycleProcessor:
    """Evaluate run-cycle anomalies for one circuit."""

    name = "run_cycle"

    def __init__(
        self,
        *,
        alert_policy_for_circuit: CycleAlertPolicyProvider,
        learning_mature: LearningMaturityProvider,
    ) -> None:
        self._alert_policy_for_circuit = alert_policy_for_circuit
        self._learning_mature = learning_mature

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Return run-cycle alerts for the current retained event history."""
        summary = summarize_circuit_cycles(
            context.store_data.events,
            circuit_id=circuit_config.circuit_id,
            now=context.now,
        )
        baselines, baseline_dirty = self._cycle_baselines_for_config(
            context.store_data,
            circuit_config,
            context.now,
        )
        context_key = build_context_for_sample(
            circuit_config=circuit_config,
            sample=sample,
            state=context.state,
            store_data=context.store_data,
            now=context.now,
            feature="run_cycle",
        )
        if not self._learning_mature(circuit_config, context.now):
            contextual_dirty = _record_contextual_cycle_samples(
                store_data=context.store_data,
                circuit_id=circuit_config.circuit_id,
                summary=summary,
                context_key=context_key,
                now=context.now,
            )
            return FeatureResult(store_dirty=baseline_dirty or contextual_dirty)

        policy = self._alert_policy_for_circuit(circuit_config.circuit_id)
        evidence = select_cycle_anomaly_evidence(
            circuit_config,
            summary,
            baselines,
            min_score=policy.min_average_score,
        )
        feature_result = FeatureResult(store_dirty=baseline_dirty)
        if evidence is None:
            feature_result.store_dirty = (
                feature_result.store_dirty
                or _record_contextual_cycle_samples(
                    store_data=context.store_data,
                    circuit_id=circuit_config.circuit_id,
                    summary=summary,
                    context_key=context_key,
                    now=context.now,
                )
            )
            return feature_result
        contextual_comparison = _contextual_cycle_comparison(
            store_data=context.store_data,
            circuit_id=circuit_config.circuit_id,
            feature=evidence.feature,
            observed_value=evidence.observed_value,
            context_key=context_key,
        )
        feature_result.store_dirty = (
            feature_result.store_dirty
            or _record_contextual_cycle_samples(
                store_data=context.store_data,
                circuit_id=circuit_config.circuit_id,
                summary=summary,
                context_key=context_key,
                now=context.now,
            )
        )
        if contextual_comparison.get("comparison_basis") == "contextual":
            feature_result.store_dirty = True
        if contextual_comparison.get("status_override") == "context_explained":
            return feature_result

        alert_features = dict(evidence.features)
        alert_features.update(_contextual_alert_features(contextual_comparison))
        baseline_value = float(
            contextual_comparison.get("alert_baseline_value", evidence.baseline_value)
        )
        baseline_confidence = float(
            contextual_comparison.get(
                "alert_baseline_confidence",
                evidence.baseline_confidence,
            )
        )
        score = float(contextual_comparison.get("alert_score", evidence.score))

        alert = policy.observe(
            Observation(
                circuit_id=circuit_config.circuit_id,
                feature=evidence.feature,
                score=score,
                baseline_confidence=baseline_confidence,
                observed_at=context.now,
                observed_value=evidence.observed_value,
                baseline_value=baseline_value,
                message=evidence.message,
                features=alert_features,
            )
        )
        if alert is not None:
            feature_result.alerts.append(alert)
            feature_result.notifications.append(alert)
        return feature_result

    def _cycle_baselines_for_config(
        self,
        store_data: FeatureStoreData,
        config: CircuitConfig,
        now: datetime,
    ) -> tuple[dict[str, BaselineStats], bool]:
        baselines: dict[str, BaselineStats] = {}
        store_dirty = False
        values_by_feature = cycle_baseline_feature_values(
            store_data.events,
            circuit_id=config.circuit_id,
            now=now,
        )
        for feature, values in values_by_feature.items():
            key = _baseline_key(config.circuit_id, feature)
            baseline = store_data.baselines.get(key)
            if baseline is None and len(values) >= 9:
                baseline = build_baseline(feature, values)
                store_data.baselines[key] = baseline
                store_dirty = True
            if baseline is not None:
                baselines[feature] = baseline
        return baselines, store_dirty


def _baseline_key(circuit_id: str, feature: str) -> str:
    return f"{circuit_id}:{feature}"


def _record_contextual_cycle_samples(
    *,
    store_data: FeatureStoreData,
    circuit_id: str,
    summary: Any,
    context_key: Any,
    now: datetime,
) -> bool:
    samples = store_data.contextual_baseline_samples_by_circuit.setdefault(
        circuit_id,
        [],
    )
    before = [dict(sample) for sample in samples]
    for feature, value in _cycle_feature_values(summary).items():
        if value <= 0.0:
            continue
        upsert_contextual_sample(
            samples,
            ContextualBaselineSample(
                timestamp=now,
                circuit_id=circuit_id,
                feature=feature,
                value=value,
                context=context_key,
                source="run_cycle",
            ),
        )
    return before != samples


def _contextual_cycle_comparison(
    *,
    store_data: FeatureStoreData,
    circuit_id: str,
    feature: str,
    observed_value: float,
    context_key: Any,
) -> dict[str, Any]:
    raw_samples = store_data.contextual_baseline_samples_by_circuit.get(
        circuit_id,
        [],
    )
    selected = select_contextual_baseline(
        circuit_id=circuit_id,
        feature=feature,
        samples=stored_contextual_samples(circuit_id, raw_samples),
        fallback_contexts=daily_energy_fallback_contexts(context_key),
    )
    if selected is None:
        return {"comparison_basis": "global", "baseline_fallback_level": "global"}

    store_data.contextual_baselines_by_circuit.setdefault(circuit_id, {})[
        contextual_stats_storage_key(selected)
    ] = contextual_stats_to_dict(selected)
    attrs: dict[str, Any] = {
        "comparison_basis": "contextual",
        "baseline_context": ", ".join(selected.context.values()),
        "baseline_fallback_level": selected.fallback_level,
        "baseline_sample_count": selected.sample_count,
        "contextual_baseline_median": round(selected.median, 3),
        "contextual_baseline_p90": round(selected.p90, 3),
        "contextual_baseline_confidence": selected.confidence,
        "alert_baseline_value": selected.p90,
        "alert_baseline_confidence": selected.confidence,
        "alert_score": (
            float(observed_value) / selected.p90 if selected.p90 > 0.0 else 0.0
        ),
    }
    if observed_value <= selected.p90:
        attrs["status_override"] = "context_explained"
    return attrs


def _contextual_alert_features(contextual_comparison: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in contextual_comparison.items()
        if not key.startswith("alert_") and key != "status_override"
    }


def _cycle_feature_values(summary: Any) -> dict[str, float]:
    return {
        RUN_CYCLE_DURATION_FEATURE: float(summary.active_cycle_seconds),
        RUN_CYCLE_DUTY_CYCLE_FEATURE: float(summary.duty_cycle_percent),
        RUN_CYCLE_START_COUNT_FEATURE: float(summary.start_count),
    }
