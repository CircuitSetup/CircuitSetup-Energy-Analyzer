"""Demand tracking processor."""

from __future__ import annotations

from collections.abc import Callable, Mapping
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
from ..demand import (
    DemandLimitEvidence,
    DemandPeakEvidence,
    DemandSettings,
    record_demand_sample,
)
from ..local_time import as_ha_local, local_date
from ..models import AlertEvidence, CircuitConfig, PowerFlowMode
from ..normalize import NormalizedCircuitSample
from .base import AlertPolicy, FeatureResult, ProcessingContext, StateUpdate

DEMAND_PEAK_FEATURE = "peak_demand_w"


type DemandSettingsProvider = Callable[[CircuitConfig | None, str], DemandSettings]
type DemandAlertPolicyProvider = Callable[[str], AlertPolicy]
type RetentionDaysProvider = Callable[[str], int]


class DemandProcessor:
    """Track rolling demand and demand alerts for one circuit."""

    name = "demand"

    def __init__(
        self,
        *,
        settings_for_config: DemandSettingsProvider,
        alert_policy_for_circuit: DemandAlertPolicyProvider,
        retention_days_for_circuit: RetentionDaysProvider,
    ) -> None:
        self._settings_for_config = settings_for_config
        self._alert_policy_for_circuit = alert_policy_for_circuit
        self._retention_days_for_circuit = retention_days_for_circuit
        self._transient_samples_by_circuit: dict[str, list[dict[str, Any]]] = {}

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Record demand state and return configured demand alerts."""
        circuit_id = circuit_config.circuit_id
        result = record_demand_sample(
            context.store_data.demand_by_circuit.setdefault(circuit_id, {}),
            circuit_id=circuit_id,
            timestamp=context.now,
            real_power_w=_demand_power_w(sample),
            settings=self._settings_for_config(circuit_config, circuit_id),
            retention_days=self._retention_days_for_circuit(circuit_id),
            time_zone=context.time_zone,
            baseline_eligible=not (
                isinstance(
                    maintenance := context.store_data.maintenance_by_circuit.get(
                        circuit_id,
                    ),
                    Mapping,
                )
                and maintenance.get("active") is True
            ),
            transient_samples=self._transient_samples_by_circuit.setdefault(
                circuit_id,
                [],
            ),
        )
        if result is None:
            return FeatureResult()

        contextual_comparison = _contextual_demand_comparison(
            result,
            circuit_config,
            sample,
            context,
        )
        feature_result = FeatureResult(
            state_updates=[
                StateUpdate(
                    ("current_demand_w_by_circuit", circuit_id),
                    result.current_demand_w,
                ),
                StateUpdate(
                    ("peak_demand_w_by_circuit", circuit_id),
                    result.peak_demand_w,
                ),
                StateUpdate(
                    ("demand_limit_usage_by_circuit", circuit_id),
                    result.demand_limit_usage,
                ),
                StateUpdate(
                    ("demand_peak_rank_by_circuit", circuit_id),
                    result.monthly_peak_rank,
                ),
                StateUpdate(
                    ("demand_peak_status_by_circuit", circuit_id),
                    result.monthly_peak_status,
                ),
                StateUpdate(
                    ("demand_evidence_by_circuit", circuit_id),
                    demand_evidence_payload(result, contextual_comparison),
                ),
            ],
            store_dirty=result.monthly_peak_recorded
            or bool(contextual_comparison.get("sample_recorded")),
        )

        alert = None
        if result.limit_exceeded is not None:
            alert = self._demand_limit_alert(
                circuit_config,
                context,
                result.limit_exceeded,
                contextual_comparison,
            )
        elif (
            result.monthly_peak_warning is not None
            and contextual_comparison.get("status_override") != "context_explained"
        ):
            alert = self._demand_monthly_peak_alert(
                circuit_config,
                context,
                result.monthly_peak_warning,
                contextual_comparison,
            )
        if alert is not None:
            feature_result.alerts.append(alert)
            feature_result.notifications.append(alert)
        return feature_result

    def _demand_limit_alert(
        self,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
        evidence: DemandLimitEvidence,
        contextual_comparison: dict[str, Any],
    ) -> AlertEvidence | None:
        score = (
            evidence.current_demand_w / evidence.demand_limit_w
            if evidence.demand_limit_w > 0.0
            else 0.0
        )
        return self._alert_policy_for_circuit(circuit_config.circuit_id).observe(
            Observation(
                circuit_id=circuit_config.circuit_id,
                feature="demand_limit",
                score=score,
                baseline_confidence=1.0,
                observed_at=context.now,
                observed_value=evidence.current_demand_w,
                baseline_value=evidence.demand_limit_w,
                message=demand_limit_message(circuit_config, evidence),
                features={
                    **evidence.features,
                    **_contextual_alert_features(contextual_comparison),
                },
            )
        )

    def _demand_monthly_peak_alert(
        self,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
        evidence: DemandPeakEvidence,
        contextual_comparison: dict[str, Any],
    ) -> AlertEvidence | None:
        baseline_value = float(
            contextual_comparison.get(
                "alert_baseline_value",
                evidence.monthly_peak_cutoff_w,
            )
        )
        score = max(
            1.0,
            (
                float(evidence.current_demand_w) / baseline_value
                if baseline_value > 0.0
                else evidence.monthly_peak_usage_percent / 100.0
            ),
        )
        return self._alert_policy_for_circuit(circuit_config.circuit_id).observe(
            Observation(
                circuit_id=circuit_config.circuit_id,
                feature="demand_monthly_peak",
                score=score,
                baseline_confidence=1.0,
                observed_at=context.now,
                observed_value=evidence.current_demand_w,
                baseline_value=baseline_value,
                message=demand_monthly_peak_message(circuit_config, evidence),
                features={
                    **evidence.features,
                    **_contextual_alert_features(contextual_comparison),
                },
            )
        )


def demand_limit_message(
    config: CircuitConfig,
    evidence: DemandLimitEvidence,
) -> str:
    """Build the user-facing demand-limit alert message."""
    return (
        f"Possible issue: {config.name} demand averaged "
        f"{_format_w(evidence.current_demand_w)} W over "
        f"{evidence.window_minutes} minutes, above the configured "
        f"{_format_w(evidence.demand_limit_w)} W limit."
    )


def demand_monthly_peak_message(
    config: CircuitConfig,
    evidence: DemandPeakEvidence,
) -> str:
    """Build the user-facing monthly peak demand alert message."""
    return (
        f"Possible issue: {config.name} demand averaged "
        f"{_format_w(evidence.current_demand_w)} W over "
        f"{evidence.window_minutes} minutes, "
        f"{_monthly_peak_comparison_phrase(evidence)}"
    )


def _monthly_peak_comparison_phrase(evidence: DemandPeakEvidence) -> str:
    cutoff = f"{_format_w(evidence.monthly_peak_cutoff_w)} W"
    if evidence.current_demand_w >= evidence.monthly_peak_cutoff_w:
        return (
            f"matching this month's #{evidence.peak_rank_count} "
            f"demand window cutoff of {cutoff}."
        )
    return (
        f"within {_format_percent(evidence.monthly_peak_usage_percent)}% "
        f"of this month's #{evidence.peak_rank_count} demand window "
        f"cutoff of {cutoff}."
    )


def demand_evidence_payload(
    result: Any,
    contextual_comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the analyzer state payload for rolling demand tracking."""
    status = (
        "over_limit"
        if result.limit_exceeded is not None
        else ("tracking" if result.demand_limit_w is not None else "unconfigured")
    )
    if contextual_comparison and contextual_comparison.get("status_override"):
        status = str(contextual_comparison["status_override"])
    return _with_contextual_evidence(
        {
            "date": result.date,
            "current_demand_w": result.current_demand_w,
            "peak_demand_w": result.peak_demand_w,
            "demand_window_minutes": result.window_minutes,
            "demand_limit_w": result.demand_limit_w,
            "demand_limit_usage_percent": result.demand_limit_usage,
            "status": status,
            "monthly_peak_rank": result.monthly_peak_rank,
            "monthly_peak_status": result.monthly_peak_status,
            "monthly_peak_cutoff_w": result.monthly_peak_cutoff_w,
            "monthly_peak_usage_percent": result.monthly_peak_usage_percent,
            "monthly_peak_rank_count": result.monthly_peak_rank_count,
            "monthly_peak_warning_ratio": result.monthly_peak_warning_ratio,
        },
        contextual_comparison,
    )


def _contextual_demand_comparison(
    result: Any,
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
        feature=DEMAND_PEAK_FEATURE,
        time_zone=context.time_zone,
        calendar_timestamp=context.now,
    )
    raw_samples = context.store_data.contextual_baseline_samples_by_circuit.get(
        circuit_config.circuit_id,
        [],
    )
    current_local_date = local_date(context.now, context.time_zone)
    historical_samples = [
        item
        for item in stored_contextual_samples(
            circuit_config.circuit_id,
            raw_samples,
            cache=context.contextual_samples_cache,
        )
        if local_date(item.timestamp, context.time_zone) < current_local_date
    ]
    selected = select_contextual_baseline(
        circuit_id=circuit_config.circuit_id,
        feature=DEMAND_PEAK_FEATURE,
        samples=historical_samples,
        fallback_contexts=daily_energy_fallback_contexts(context_key),
    )

    sample_recorded = False
    if (
        result.window_baseline_eligible
        and result.peak_demand_w > 0.0
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
                feature=DEMAND_PEAK_FEATURE,
                value=result.peak_demand_w,
                context=context_key,
                source="demand",
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
            feature=DEMAND_PEAK_FEATURE,
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

    attrs: dict[str, Any] = {
        "comparison_mode": "same_time_of_day",
        "as_of": as_ha_local(context.now, context.time_zone).isoformat(),
        "comparison_basis": "contextual",
        "baseline_context": ", ".join(selected.context.values()),
        "baseline_fallback_level": selected.fallback_level,
        "baseline_sample_count": selected.sample_count,
        "contextual_baseline_median_w": round(selected.median, 1),
        "contextual_baseline_p90_w": round(selected.p90, 1),
        "contextual_baseline_confidence": selected.confidence,
        "contextual_expected_range_w": [round(selected.p10, 1), round(selected.p90, 1)],
        "alert_baseline_value": selected.p90,
        "sample_recorded": sample_recorded,
    }
    if (
        result.monthly_peak_warning is not None
        and result.current_demand_w <= selected.p90
    ):
        attrs["status_override"] = "context_explained"
    return attrs


def _with_contextual_evidence(
    payload: dict[str, Any],
    contextual_comparison: dict[str, Any] | None,
) -> dict[str, Any]:
    if contextual_comparison:
        payload.update(
            {
                key: value
                for key, value in contextual_comparison.items()
                if not key.startswith("alert_")
                and key not in {"sample_recorded", "status_override"}
            }
        )
    return payload


def _contextual_alert_features(contextual_comparison: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in contextual_comparison.items()
        if not key.startswith("alert_")
        and key not in {"sample_recorded", "status_override"}
    }


def _demand_power_w(sample: NormalizedCircuitSample) -> float | None:
    power = getattr(sample, "real_power", None)
    if power is None:
        return None
    power_flow = getattr(sample, "power_flow", PowerFlowMode.LOAD)
    if power_flow is PowerFlowMode.GENERATION:
        return None
    return max(float(power), 0.0)


def _format_percent(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _format_w(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")
