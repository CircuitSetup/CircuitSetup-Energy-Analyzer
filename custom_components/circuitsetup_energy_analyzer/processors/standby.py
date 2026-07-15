"""Always On and standby tracking processor."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..alerting import Observation
from ..contextual_baseline import (
    ContextualBaselineSample,
    build_context_for_sample,
    context_allows_baseline_learning,
    contextual_stats_storage_key,
    contextual_stats_to_dict,
    daily_energy_fallback_contexts,
    select_contextual_baseline,
    stored_contextual_samples,
    upsert_contextual_sample,
)
from ..models import (
    AlertEvidence,
    CircuitConfig,
    PowerFlowMode,
)
from ..normalize import NormalizedCircuitSample
from ..standby import (
    StandbyLimitEvidence,
    StandbyResult,
    StandbySettings,
    record_standby_sample,
)
from .base import AlertPolicy, FeatureResult, ProcessingContext, StateUpdate

STANDBY_POWER_FEATURE = "standby_power_w"


type StandbySettingsProvider = Callable[[CircuitConfig | None, str], StandbySettings]
type StandbyAlertPolicyProvider = Callable[[str], AlertPolicy]
type DemoStandbySeeder = Callable[
    [CircuitConfig, NormalizedCircuitSample, ProcessingContext, StandbySettings],
    None,
]


class StandbyProcessor:
    """Track Always On / standby state and configured Always On alerts."""

    name = "standby"

    def __init__(
        self,
        *,
        settings_for_config: StandbySettingsProvider,
        alert_policy_for_circuit: StandbyAlertPolicyProvider,
        seed_demo_history: DemoStandbySeeder | None = None,
    ) -> None:
        self._settings_for_config = settings_for_config
        self._alert_policy_for_circuit = alert_policy_for_circuit
        self._seed_demo_history = seed_demo_history

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Record standby state and return configured Always On alerts."""
        power_w = _standby_power_w(sample)
        settings = self._settings_for_config(circuit_config, circuit_config.circuit_id)
        if self._seed_demo_history is not None:
            self._seed_demo_history(circuit_config, sample, context, settings)
        result = record_standby_sample(
            context.store_data.standby_by_circuit.setdefault(
                circuit_config.circuit_id,
                {},
            ),
            circuit_id=circuit_config.circuit_id,
            timestamp=context.now,
            real_power_w=power_w,
            settings=settings,
        )
        if result is None:
            return FeatureResult()

        contextual_comparison = _contextual_standby_comparison(
            result,
            circuit_config,
            sample,
            context,
        )
        feature_result = FeatureResult(
            state_updates=[
                StateUpdate(
                    ("always_on_power_w_by_circuit", circuit_config.circuit_id),
                    result.always_on_power_w,
                ),
                StateUpdate(
                    ("standby_threshold_w_by_circuit", circuit_config.circuit_id),
                    result.standby_threshold_w,
                ),
                StateUpdate(
                    ("standby_status_by_circuit", circuit_config.circuit_id),
                    result.status,
                ),
                StateUpdate(
                    ("always_on_limit_usage_by_circuit", circuit_config.circuit_id),
                    result.always_on_limit_usage,
                ),
                StateUpdate(
                    ("standby_evidence_by_circuit", circuit_config.circuit_id),
                    standby_evidence_payload(result, contextual_comparison),
                ),
            ],
            store_dirty=result.limit_exceeded is not None
            or bool(contextual_comparison.get("sample_recorded")),
        )
        if result.limit_exceeded is not None:
            alert = self._standby_limit_alert(
                circuit_config,
                context,
                result.limit_exceeded,
                contextual_comparison,
            )
            if alert is not None:
                feature_result.alerts.append(alert)
                feature_result.notifications.append(alert)
        return feature_result

    def _standby_limit_alert(
        self,
        config: CircuitConfig,
        context: ProcessingContext,
        evidence: StandbyLimitEvidence,
        contextual_comparison: dict[str, Any],
    ) -> AlertEvidence | None:
        score = (
            evidence.always_on_power_w / evidence.always_on_alert_w
            if evidence.always_on_alert_w > 0.0
            else 0.0
        )
        return self._alert_policy_for_circuit(config.circuit_id).observe(
            Observation(
                circuit_id=config.circuit_id,
                feature="always_on_power",
                score=score,
                baseline_confidence=1.0,
                observed_at=context.now,
                observed_value=evidence.always_on_power_w,
                baseline_value=evidence.always_on_alert_w,
                message=standby_limit_message(config, evidence),
                features={
                    **evidence.features,
                    **_contextual_alert_features(contextual_comparison),
                },
            )
        )


def standby_limit_message(
    config: CircuitConfig,
    evidence: StandbyLimitEvidence,
) -> str:
    """Build the user-facing Always On alert message."""
    return (
        f"Possible issue: {config.name} Always On is "
        f"{_format_w(evidence.always_on_power_w)} W over the last "
        f"{evidence.window_hours} hours, above the configured "
        f"{_format_w(evidence.always_on_alert_w)} W limit."
    )


def standby_evidence_payload(
    result: StandbyResult,
    contextual_comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the analyzer state payload for standby tracking."""
    payload = {
        "always_on_power_w": result.always_on_power_w,
        "current_power_w": result.current_power_w,
        "standby_threshold_w": result.standby_threshold_w,
        "sample_count": result.sample_count,
        "window_hours": result.window_hours,
        "always_on_alert_w": result.always_on_alert_w,
        "always_on_limit_usage_percent": result.always_on_limit_usage,
        "status": result.status,
    }
    if contextual_comparison:
        payload.update(
            {
                key: value
                for key, value in contextual_comparison.items()
                if not key.startswith("alert_") and key != "sample_recorded"
            }
        )
    return payload


def _contextual_standby_comparison(
    result: StandbyResult,
    circuit_config: CircuitConfig,
    sample: NormalizedCircuitSample,
    context: ProcessingContext,
) -> dict[str, Any]:
    context_key = build_context_for_sample(
        circuit_config=circuit_config,
        sample=sample,
        state=context.state,
        store_data=context.store_data,
        now=context.now,
        feature=STANDBY_POWER_FEATURE,
        time_zone=context.time_zone,
        calendar_timestamp=context.now,
    )
    raw_samples = context.store_data.contextual_baseline_samples_by_circuit.get(
        circuit_config.circuit_id,
        [],
    )
    selected = select_contextual_baseline(
        circuit_id=circuit_config.circuit_id,
        feature=STANDBY_POWER_FEATURE,
        samples=stored_contextual_samples(
            circuit_config.circuit_id,
            raw_samples,
            cache=context.contextual_samples_cache,
        ),
        fallback_contexts=daily_energy_fallback_contexts(context_key),
    )

    sample_recorded = False
    if (
        result.always_on_power_w > 0.0
        and result.status != "learning"
        and context_allows_baseline_learning(context_key)
    ):
        samples = context.store_data.contextual_baseline_samples_by_circuit.setdefault(
            circuit_config.circuit_id,
            [],
        )
        before = [dict(item) for item in samples]
        upsert_contextual_sample(
            samples,
            ContextualBaselineSample(
                timestamp=context.now,
                circuit_id=circuit_config.circuit_id,
                feature=STANDBY_POWER_FEATURE,
                value=result.always_on_power_w,
                context=context_key,
                source="standby",
            ),
            time_zone=context.time_zone,
            cache=context.contextual_samples_cache,
        )
        sample_recorded = before != samples
        updated_samples = stored_contextual_samples(
            circuit_config.circuit_id,
            samples,
            cache=context.contextual_samples_cache,
        )
        exact = select_contextual_baseline(
            circuit_id=circuit_config.circuit_id,
            feature=STANDBY_POWER_FEATURE,
            samples=updated_samples,
            fallback_contexts=[("exact_context", context_key, 7)],
        )
        if exact is not None:
            context.store_data.contextual_baselines_by_circuit.setdefault(
                circuit_config.circuit_id,
                {},
            )[contextual_stats_storage_key(exact)] = contextual_stats_to_dict(exact)

    if selected is None:
        return {"sample_recorded": sample_recorded}

    return {
        "comparison_basis": "contextual",
        "baseline_context": ", ".join(selected.context.values()),
        "baseline_fallback_level": selected.fallback_level,
        "baseline_sample_count": selected.sample_count,
        "contextual_baseline_median_w": round(selected.median, 1),
        "contextual_baseline_p90_w": round(selected.p90, 1),
        "contextual_baseline_confidence": selected.confidence,
        "contextual_expected_range_w": [round(selected.p10, 1), round(selected.p90, 1)],
        "sample_recorded": sample_recorded,
    }


def _contextual_alert_features(contextual_comparison: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in contextual_comparison.items()
        if not key.startswith("alert_") and key != "sample_recorded"
    }


def _standby_power_w(sample: NormalizedCircuitSample) -> float | None:
    power = getattr(sample, "real_power", None)
    if power is None:
        return None
    power_flow = getattr(sample, "power_flow", PowerFlowMode.LOAD)
    if power_flow is PowerFlowMode.GENERATION:
        return None
    return max(float(power), 0.0)


def _format_w(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")
