"""Run-cycle anomaly processor."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..alerting import Observation
from ..baseline import build_baseline
from ..cold_storage import (
    COLD_STORAGE_BASELINE_FEATURES,
    COLD_STORAGE_MIN_BASELINE_WINDOWS,
    COLD_STORAGE_SIGNATURE_FEATURE,
    ColdStorageWindowAccumulator,
    cold_storage_window_values,
    select_cold_storage_signature_evidence,
)
from ..contextual_baseline import (
    ContextKey,
    ContextualBaselineSample,
    build_context_for_sample,
    context_allows_baseline_learning,
    contextual_sample_from_dict,
    contextual_stats_storage_key,
    contextual_stats_to_dict,
    daily_energy_fallback_contexts,
    day_progress_bucket,
    remove_contextual_samples_for_dates,
    select_contextual_baseline,
    stored_contextual_samples,
    upsert_contextual_sample,
)
from ..cycles import (
    RUN_CYCLE_DURATION_FEATURE,
    RUN_CYCLE_DUTY_CYCLE_FEATURE,
    RUN_CYCLE_RUNTIME_TODAY_FEATURE,
    RUN_CYCLE_START_COUNT_FEATURE,
    cycle_baseline_feature_values,
    cycle_baseline_ineligible_dates,
    select_cycle_anomaly_evidence,
    summarize_circuit_cycles,
)
from ..local_time import local_date
from ..models import (
    AlertEvidence,
    ApplianceProfile,
    BaselineStats,
    CircuitConfig,
    CircuitMode,
    PowerFlowMode,
)
from ..normalize import NormalizedCircuitSample
from ..operating_detection import (
    operating_state_is_running,
    resolve_operating_detection_from_settings,
)
from ..profiles import supports_direct_appliance_analysis
from ..storage import FeatureStoreData
from .base import AlertPolicy, FeatureResult, ProcessingContext

type CycleAlertPolicyProvider = Callable[[str], AlertPolicy]
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
        self._cold_storage_windows: dict[str, ColdStorageWindowAccumulator] = {}
        self._cold_storage_recovery_windows: defaultdict[str, int] = defaultdict(int)

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Return run-cycle alerts for the current retained event history."""
        if not supports_direct_appliance_analysis(circuit_config):
            return FeatureResult()
        feature_result = self._process_cold_storage_signature(
            sample,
            circuit_config,
            context,
        )
        merge_gap_seconds = resolve_operating_detection_from_settings(
            circuit_config,
            getattr(
                context.store_data,
                "operating_detection_settings_by_circuit",
                {},
            ).get(circuit_config.circuit_id, {}),
        ).profile.merge_gap_seconds
        ineligible_dates = cycle_baseline_ineligible_dates(
            context.store_data.events,
            circuit_id=circuit_config.circuit_id,
            now=context.now,
            merge_gap_seconds=merge_gap_seconds,
            time_zone=context.time_zone,
        )
        summary = summarize_circuit_cycles(
            context.store_data.events,
            circuit_id=circuit_config.circuit_id,
            now=context.now,
            merge_gap_seconds=merge_gap_seconds,
            time_zone=context.time_zone,
        )
        baselines, baseline_dirty = self._cycle_baselines_for_config(
            context.store_data,
            circuit_config,
            context.now,
            merge_gap_seconds=merge_gap_seconds,
            time_zone=context.time_zone,
            rebuild_for_exclusions=bool(ineligible_dates),
        )
        context_key = build_context_for_sample(
            circuit_config=circuit_config,
            sample=sample,
            state=context.state,
            store_data=context.store_data,
            now=context.now,
            feature="run_cycle",
            time_zone=context.time_zone,
            calendar_timestamp=context.now,
        )
        context_key = ContextKey.from_mapping(
            {
                **context_key.as_dict(),
                "day_progress": day_progress_bucket(
                    context.now,
                    time_zone=context.time_zone,
                ),
            }
        )
        raw_contextual_samples = (
            context.store_data.contextual_baseline_samples_by_circuit.get(
                circuit_config.circuit_id,
                [],
            )
        )
        contextual_samples_removed = remove_contextual_samples_for_dates(
            raw_contextual_samples,
            circuit_id=circuit_config.circuit_id,
            dates=ineligible_dates,
            time_zone=context.time_zone,
            cache=context.contextual_samples_cache,
        )
        if contextual_samples_removed:
            if not raw_contextual_samples:
                context.store_data.contextual_baseline_samples_by_circuit.pop(
                    circuit_config.circuit_id,
                    None,
                )
            context.store_data.contextual_baselines_by_circuit.pop(
                circuit_config.circuit_id,
                None,
            )
        contextual_baseline_eligible = context_allows_baseline_learning(
            context_key
        ) and local_date(context.now, context.time_zone) not in ineligible_dates
        if not self._learning_mature(circuit_config, context.now):
            contextual_dirty = _record_contextual_cycle_samples(
                store_data=context.store_data,
                circuit_id=circuit_config.circuit_id,
                summary=summary,
                context_key=context_key,
                now=context.now,
                time_zone=context.time_zone,
                baseline_eligible=contextual_baseline_eligible,
            )
            feature_result.store_dirty = (
                feature_result.store_dirty
                or baseline_dirty
                or contextual_samples_removed
                or contextual_dirty
            )
            return feature_result
        if _operating_state_is_unavailable(context, circuit_config.circuit_id):
            feature_result.store_dirty = (
                feature_result.store_dirty
                or baseline_dirty
                or contextual_samples_removed
            )
            return feature_result

        policy = self._alert_policy_for_circuit(circuit_config.circuit_id)
        evidence = select_cycle_anomaly_evidence(
            circuit_config,
            summary,
            baselines,
            min_score=policy.min_average_score,
        )
        feature_result.store_dirty = (
            feature_result.store_dirty or baseline_dirty or contextual_samples_removed
        )
        if evidence is None:
            feature_result.store_dirty = (
                feature_result.store_dirty
                or _record_contextual_cycle_samples(
                    store_data=context.store_data,
                    circuit_id=circuit_config.circuit_id,
                    summary=summary,
                    context_key=context_key,
                    now=context.now,
                    time_zone=context.time_zone,
                    contextual_samples_cache=context.contextual_samples_cache,
                    baseline_eligible=contextual_baseline_eligible,
                )
            )
            return feature_result
        contextual_comparison = _contextual_cycle_comparison(
            store_data=context.store_data,
            circuit_id=circuit_config.circuit_id,
            feature=evidence.feature,
            observed_value=evidence.observed_value,
            context_key=context_key,
            contextual_samples_cache=context.contextual_samples_cache,
        )
        feature_result.store_dirty = (
            feature_result.store_dirty
            or _record_contextual_cycle_samples(
                store_data=context.store_data,
                circuit_id=circuit_config.circuit_id,
                summary=summary,
                context_key=context_key,
                now=context.now,
                time_zone=context.time_zone,
                contextual_samples_cache=context.contextual_samples_cache,
                baseline_eligible=contextual_baseline_eligible,
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

        observation = Observation(
            circuit_id=circuit_config.circuit_id,
            feature=evidence.feature,
            score=score,
            baseline_confidence=baseline_confidence,
            observed_at=context.now,
            observed_value=evidence.observed_value,
            baseline_value=baseline_value,
            message=evidence.message,
            observation_key=_observation_key(evidence.feature, summary),
            features=alert_features,
        )
        feature_result.observations.append(observation)
        alert = policy.observe(observation)
        if alert is not None:
            feature_result.alerts.append(alert)
            feature_result.notifications.append(alert)
        return feature_result

    def reset_cold_storage_state(self, circuit_id: str) -> None:
        """Reset runtime cold-storage state for one circuit."""
        self._cold_storage_windows.pop(circuit_id, None)
        self._cold_storage_recovery_windows.pop(circuit_id, None)

    def _process_cold_storage_signature(
        self,
        sample: NormalizedCircuitSample,
        config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        result = FeatureResult()
        if (
            config.appliance_profile
            not in {ApplianceProfile.REFRIGERATOR, ApplianceProfile.FREEZER}
            or config.mode is not CircuitMode.SINGLE_PHASE
            or config.power_flow is not PowerFlowMode.LOAD
        ):
            return result
        active_alert = _matching_active_signature_alert(
            context.state,
            config.circuit_id,
        )
        accumulator = self._cold_storage_windows.setdefault(
            config.circuit_id,
            ColdStorageWindowAccumulator(),
        )
        summary = accumulator.observe(sample)
        if summary is None:
            if active_alert is not None:
                result.preserved_alerts.append(active_alert)
            return result
        learning_started_at = _learning_started_at(
            context.store_data,
            config.circuit_id,
            context.now,
        )
        if learning_started_at is not None and summary.started_at < learning_started_at:
            if active_alert is not None:
                result.preserved_alerts.append(active_alert)
            return result
        policy = self._alert_policy_for_circuit(config.circuit_id)
        if not summary.valid:
            policy.reset_episode(config.circuit_id, COLD_STORAGE_SIGNATURE_FEATURE)
            self._cold_storage_recovery_windows[config.circuit_id] = 0
            if active_alert is not None:
                result.preserved_alerts.append(active_alert)
            return result

        baselines = {
            feature: context.store_data.baselines.get(
                _baseline_key(config.circuit_id, feature)
            )
            for feature in COLD_STORAGE_BASELINE_FEATURES
        }
        if any(baseline is None for baseline in baselines.values()):
            raw_samples = (
                context.store_data.contextual_baseline_samples_by_circuit.setdefault(
                    config.circuit_id,
                    [],
                )
            )
            window_context = ContextKey.from_mapping(
                {"cold_storage_window": summary.started_at.isoformat()}
            )
            for feature, value in cold_storage_window_values(summary).items():
                upsert_contextual_sample(
                    raw_samples,
                    ContextualBaselineSample(
                        timestamp=summary.ended_at,
                        circuit_id=config.circuit_id,
                        feature=feature,
                        value=value,
                        context=window_context,
                        source="cold_storage_signature",
                    ),
                    time_zone=context.time_zone,
                    cache=context.contextual_samples_cache,
                )
            pending = [
                item
                for item in stored_contextual_samples(
                    config.circuit_id,
                    raw_samples,
                    cache=context.contextual_samples_cache,
                )
                if item.source == "cold_storage_signature"
                and (
                    learning_started_at is None
                    or item.timestamp >= learning_started_at
                )
            ]
            values_by_feature = {
                feature: [
                    item.value for item in pending if item.feature == feature
                ][-COLD_STORAGE_MIN_BASELINE_WINDOWS:]
                for feature in COLD_STORAGE_BASELINE_FEATURES
            }
            if all(
                len(values) == COLD_STORAGE_MIN_BASELINE_WINDOWS
                for values in values_by_feature.values()
            ):
                for feature, values in values_by_feature.items():
                    context.store_data.baselines[
                        _baseline_key(config.circuit_id, feature)
                    ] = build_baseline(feature, values)
                raw_samples[:] = [
                    raw
                    for raw in raw_samples
                    if (
                        (stored := contextual_sample_from_dict(config.circuit_id, raw))
                        is None
                        or stored.source != "cold_storage_signature"
                    )
                ]
                context.contextual_samples_cache.clear()
            result.store_dirty = True
            if active_alert is not None:
                result.preserved_alerts.append(active_alert)
            return result

        evidence = select_cold_storage_signature_evidence(
            config,
            summary,
            {
                feature: baseline
                for feature, baseline in baselines.items()
                if baseline
            },
        )
        if evidence is None:
            policy.reset_episode(config.circuit_id, COLD_STORAGE_SIGNATURE_FEATURE)
            self._cold_storage_recovery_windows[config.circuit_id] += 1
            if (
                active_alert is not None
                and self._cold_storage_recovery_windows[config.circuit_id] < 2
            ):
                result.preserved_alerts.append(active_alert)
            return result

        self._cold_storage_recovery_windows[config.circuit_id] = 0
        observation = Observation(
            circuit_id=config.circuit_id,
            feature=evidence.feature,
            score=evidence.score,
            baseline_confidence=evidence.baseline_confidence,
            observed_at=summary.ended_at,
            observed_value=evidence.observed_value,
            baseline_value=evidence.baseline_value,
            value_metric="power_factor_peak_delta",
            message=evidence.message,
            observation_key=f"{evidence.feature}:{summary.started_at.isoformat()}",
            features=evidence.features,
        )
        result.observations.append(observation)
        if active_alert is not None:
            result.preserved_alerts.append(active_alert)
            return result
        alert = policy.observe(observation)
        if alert is None:
            return result
        result.alerts.append(alert)
        result.notifications.append(alert)
        return result

    def _cycle_baselines_for_config(
        self,
        store_data: FeatureStoreData,
        config: CircuitConfig,
        now: datetime,
        *,
        merge_gap_seconds: float,
        time_zone: str | None = None,
        rebuild_for_exclusions: bool = False,
    ) -> tuple[dict[str, BaselineStats], bool]:
        baselines: dict[str, BaselineStats] = {}
        store_dirty = False
        values_by_feature = cycle_baseline_feature_values(
            store_data.events,
            circuit_id=config.circuit_id,
            now=now,
            merge_gap_seconds=merge_gap_seconds,
            time_zone=time_zone,
        )
        for feature, values in values_by_feature.items():
            key = _baseline_key(config.circuit_id, feature)
            baseline = store_data.baselines.get(key)
            if rebuild_for_exclusions:
                rebuilt = build_baseline(feature, values) if len(values) >= 9 else None
                if rebuilt != baseline:
                    if rebuilt is None:
                        store_data.baselines.pop(key, None)
                    else:
                        store_data.baselines[key] = rebuilt
                    store_dirty = True
                baseline = rebuilt
            elif baseline is None and len(values) >= 9:
                baseline = build_baseline(feature, values)
                store_data.baselines[key] = baseline
                store_dirty = True
            if baseline is not None:
                baselines[feature] = baseline
        return baselines, store_dirty


def _baseline_key(circuit_id: str, feature: str) -> str:
    return f"{circuit_id}:{feature}"


def _learning_started_at(
    store_data: FeatureStoreData,
    circuit_id: str,
    now: datetime,
) -> datetime | None:
    raw = store_data.learning_started_at_by_circuit.get(circuit_id)
    if not raw:
        return None
    try:
        started_at = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=now.tzinfo)
    return started_at


def _matching_active_signature_alert(
    state: Any,
    circuit_id: str,
) -> AlertEvidence | None:
    return next(
        (
            alert
            for alert in getattr(state, "active_alerts_by_circuit", {}).get(
                circuit_id, ()
            )
            if alert.feature == COLD_STORAGE_SIGNATURE_FEATURE
        ),
        None,
    )


def _observation_key(feature: str, summary: Any) -> str:
    if feature == RUN_CYCLE_DURATION_FEATURE:
        last_start = getattr(summary, "last_start", None)
        if last_start is not None:
            return f"{feature}:{last_start.isoformat()}"
    return f"{feature}:{getattr(summary, 'date', '')}"


def _operating_state_is_unavailable(
    context: ProcessingContext,
    circuit_id: str,
) -> bool:
    snapshots = getattr(context.state, "operating_state_snapshot_by_circuit", {}) or {}
    if not isinstance(snapshots, dict):
        return False
    snapshot = snapshots.get(circuit_id)
    return snapshot is not None and operating_state_is_running(snapshot) is None


def _record_contextual_cycle_samples(
    *,
    store_data: FeatureStoreData,
    circuit_id: str,
    summary: Any,
    context_key: Any,
    now: datetime,
    time_zone: str | None = None,
    contextual_samples_cache: Any | None = None,
    baseline_eligible: bool,
) -> bool:
    if not baseline_eligible:
        return False
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
            time_zone=time_zone,
            cache=contextual_samples_cache,
        )
    return before != samples


def _contextual_cycle_comparison(
    *,
    store_data: FeatureStoreData,
    circuit_id: str,
    feature: str,
    observed_value: float,
    context_key: Any,
    contextual_samples_cache: Any,
) -> dict[str, Any]:
    raw_samples = store_data.contextual_baseline_samples_by_circuit.get(
        circuit_id,
        [],
    )
    selected = select_contextual_baseline(
        circuit_id=circuit_id,
        feature=feature,
        samples=stored_contextual_samples(
            circuit_id,
            raw_samples,
            cache=contextual_samples_cache,
        ),
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
        RUN_CYCLE_RUNTIME_TODAY_FEATURE: float(summary.runtime_seconds),
    }
