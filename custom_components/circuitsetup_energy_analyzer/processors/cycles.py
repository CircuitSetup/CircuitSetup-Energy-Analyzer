"""Run-cycle anomaly processor."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from ..alerting import Observation
from ..baseline import build_baseline
from ..cycles import (
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
        if not self._learning_mature(circuit_config, context.now):
            return FeatureResult(store_dirty=baseline_dirty)

        policy = self._alert_policy_for_circuit(circuit_config.circuit_id)
        evidence = select_cycle_anomaly_evidence(
            circuit_config,
            summary,
            baselines,
            min_score=policy.min_average_score,
        )
        feature_result = FeatureResult(store_dirty=baseline_dirty)
        if evidence is None:
            return feature_result

        alert = policy.observe(
            Observation(
                circuit_id=circuit_config.circuit_id,
                feature=evidence.feature,
                score=evidence.score,
                baseline_confidence=evidence.baseline_confidence,
                observed_at=context.now,
                observed_value=evidence.observed_value,
                baseline_value=evidence.baseline_value,
                message=evidence.message,
                features=evidence.features,
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
