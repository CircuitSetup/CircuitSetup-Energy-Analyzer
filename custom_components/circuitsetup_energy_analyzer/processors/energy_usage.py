"""Daily energy usage processor."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..alerting import Observation
from ..baseline import build_baseline
from ..contextual_baseline import (
    DAILY_ENERGY_FEATURE,
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
from ..local_time import as_ha_local, local_date
from ..models import CircuitConfig
from ..normalize import NormalizedCircuitSample
from ..usage import EnergyUsageSettings, EnergyUsageSpike, record_energy_usage
from .base import AlertPolicy, FeatureResult, ProcessingContext, StateUpdate

type EnergyUsageSettingsProvider = Callable[
    [CircuitConfig | None, str],
    EnergyUsageSettings,
]
type RetentionDaysProvider = Callable[[str], int]
type UsageAlertPolicyProvider = Callable[[str], AlertPolicy]
type DemoEnergyUsageSeeder = Callable[
    [CircuitConfig, NormalizedCircuitSample, Any, EnergyUsageSettings],
    None,
]


class EnergyUsageProcessor:
    """Track daily kWh usage and produce spike alerts for one circuit."""

    name = "energy_usage"

    def __init__(
        self,
        *,
        settings_for_config: EnergyUsageSettingsProvider,
        retention_days_for_circuit: RetentionDaysProvider,
        alert_policy_for_circuit: UsageAlertPolicyProvider,
        seed_demo_history: DemoEnergyUsageSeeder | None = None,
    ) -> None:
        self._settings_for_config = settings_for_config
        self._retention_days_for_circuit = retention_days_for_circuit
        self._alert_policy_for_circuit = alert_policy_for_circuit
        self._seed_demo_history = seed_demo_history

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Record daily usage, update analyzer state, and return spike alerts."""
        circuit_id = circuit_config.circuit_id
        settings = self._settings_for_config(circuit_config, circuit_id)
        if self._seed_demo_history is not None:
            self._seed_demo_history(circuit_config, sample, context.now, settings)

        result = record_energy_usage(
            context.store_data.energy_usage_by_circuit.setdefault(circuit_id, {}),
            circuit_id=circuit_id,
            timestamp=context.now,
            energy_kwh=sample.energy,
            settings=EnergyUsageSettings(
                window_days=settings.window_days,
                daily_spike_ratio=settings.daily_spike_ratio,
            ),
            retention_days=self._retention_days_for_circuit(circuit_id),
            time_zone=context.time_zone,
        )
        if result is None:
            return FeatureResult()

        contextual_comparison = _contextual_daily_energy_comparison(
            result,
            circuit_config,
            sample,
            context,
        )
        feature_result = FeatureResult(
            state_updates=[
                StateUpdate(
                    ("daily_energy_usage_by_circuit", circuit_id),
                    result.daily_usage_kwh,
                ),
                StateUpdate(
                    ("energy_usage_share_by_circuit", circuit_id),
                    round(result.daily_usage_share * 100, 1),
                ),
                StateUpdate(
                    ("energy_usage_evidence_by_circuit", circuit_id),
                    energy_usage_evidence_payload(
                        result,
                        contextual_comparison,
                    ),
                ),
            ],
            store_dirty=True,
        )

        if result.spike is None:
            return feature_result
        if contextual_comparison.get("status_override") == "context_explained":
            return feature_result

        spike = result.spike
        alert_baseline_value = float(
            contextual_comparison.get("alert_baseline_value", spike.threshold_kwh)
        )
        score = (
            spike.daily_usage_kwh / alert_baseline_value
            if alert_baseline_value > 0.0
            else 0.0
        )
        baseline_confidence = float(
            contextual_comparison.get(
                "alert_baseline_confidence",
                min(spike.baseline_day_count / spike.window_days, 1.0),
            )
        )
        alert_features = dict(spike.features)
        alert_features.update(_contextual_alert_features(contextual_comparison))
        alert = self._alert_policy_for_circuit(circuit_id).observe(
            Observation(
                circuit_id=circuit_id,
                feature="daily_energy_usage_spike",
                score=score,
                baseline_confidence=baseline_confidence,
                observed_at=context.now,
                observed_value=spike.daily_usage_kwh,
                baseline_value=alert_baseline_value,
                message=energy_usage_spike_message(circuit_config, spike),
                features=alert_features,
            )
        )
        if alert is not None:
            feature_result.alerts.append(alert)
            feature_result.notifications.append(alert)
        return feature_result


def energy_usage_spike_message(
    config: CircuitConfig,
    spike: EnergyUsageSpike,
) -> str:
    """Build the user-facing daily usage spike message."""
    share_percent = round(spike.daily_usage_share * 100, 1)
    threshold_percent = round(spike.threshold_ratio * 100)
    return (
        f"Possible issue: {config.name} used {_format_kwh(spike.daily_usage_kwh)} "
        f"kWh today, which is {share_percent}% of its last {spike.window_days} "
        f"days of usage ({_format_kwh(spike.baseline_total_kwh)} kWh). This is "
        f"above the configured {threshold_percent}% daily usage threshold."
    )


def energy_usage_evidence_payload(
    result: Any,
    contextual_comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the analyzer state payload for daily usage tracking."""
    status = "over_threshold" if result.spike is not None else result.tracking_status
    if contextual_comparison and contextual_comparison.get("status_override"):
        status = str(contextual_comparison["status_override"])
    payload = {
        "date": result.date,
        "daily_usage_kwh": result.daily_usage_kwh,
        "baseline_total_kwh": result.baseline_total_kwh,
        "baseline_window_days": result.window_days,
        "baseline_day_count": result.baseline_day_count,
        "threshold_ratio": result.threshold_ratio,
        "threshold_kwh": result.threshold_kwh,
        "daily_usage_share_percent": round(result.daily_usage_share * 100, 1),
        "status": status,
        "raw_status": status,
        "status_label": _status_label_for_evidence(status),
        "status_explanation": _status_explanation_for_evidence(status),
        "status_reason": result.status_reason,
        "suggested_next_check": _energy_usage_next_check(status),
    }
    if contextual_comparison:
        payload.update(
            {
                key: value
                for key, value in contextual_comparison.items()
                if not key.startswith("alert_") and key != "status_override"
            }
        )
    return payload


def _contextual_daily_energy_comparison(
    result: Any,
    circuit_config: CircuitConfig,
    sample: NormalizedCircuitSample,
    context: ProcessingContext,
) -> dict[str, Any]:
    """Record and compare daily energy against contextual history."""
    circuit_id = circuit_config.circuit_id
    context_key = build_context_for_sample(
        circuit_config=circuit_config,
        sample=sample,
        state=context.state,
        store_data=context.store_data,
        now=context.now,
        feature=DAILY_ENERGY_FEATURE,
        time_zone=context.time_zone,
        calendar_timestamp=context.now,
    )
    raw_samples = context.store_data.contextual_baseline_samples_by_circuit.get(
        circuit_id,
        [],
    )
    current_local_date = local_date(context.now, context.time_zone)
    historical_samples = [
        item
        for item in stored_contextual_samples(circuit_id, raw_samples)
        if local_date(item.timestamp, context.time_zone) < current_local_date
    ]
    selected = select_contextual_baseline(
        circuit_id=circuit_id,
        feature=DAILY_ENERGY_FEATURE,
        samples=historical_samples,
        fallback_contexts=daily_energy_fallback_contexts(context_key),
    )

    if result.daily_usage_kwh > 0.0 and context_allows_baseline_learning(
        context_key
    ):
        samples = context.store_data.contextual_baseline_samples_by_circuit.setdefault(
            circuit_id,
            [],
        )
        upsert_contextual_sample(
            samples,
            ContextualBaselineSample(
                timestamp=context.now,
                circuit_id=circuit_id,
                feature=DAILY_ENERGY_FEATURE,
                value=result.daily_usage_kwh,
                context=context_key,
                source="energy_usage",
            ),
            time_zone=context.time_zone,
        )
        updated_samples = stored_contextual_samples(circuit_id, samples)
        exact = select_contextual_baseline(
            circuit_id=circuit_id,
            feature=DAILY_ENERGY_FEATURE,
            samples=updated_samples,
            fallback_contexts=[("exact_context", context_key, 7)],
        )
        if exact is not None:
            context.store_data.contextual_baselines_by_circuit.setdefault(
                circuit_id,
                {},
            )[contextual_stats_storage_key(exact)] = contextual_stats_to_dict(exact)

    if selected is None:
        return {
            "comparison_basis": "rolling",
            "baseline_fallback_level": "not_enough_data",
            "global_baseline_used": True,
        }

    attrs: dict[str, Any] = {
        "comparison_mode": "same_time_of_day",
        "as_of": as_ha_local(context.now, context.time_zone).isoformat(),
        "comparison_basis": "contextual",
        "baseline_context": ", ".join(selected.context.values()),
        "baseline_fallback_level": selected.fallback_level,
        "baseline_sample_count": selected.sample_count,
        "contextual_baseline_median_kwh": round(selected.median, 3),
        "contextual_baseline_p90_kwh": round(selected.p90, 3),
        "contextual_baseline_confidence": selected.confidence,
        "contextual_expected_range": [round(selected.p10, 3), round(selected.p90, 3)],
        "global_baseline_used": False,
        "alert_baseline_value": selected.p90,
        "alert_baseline_confidence": selected.confidence,
    }
    attrs.update(_daily_energy_projection(result, selected, context))
    if result.spike is not None and result.daily_usage_kwh <= selected.p90:
        attrs["status_override"] = "context_explained"
    return attrs


def _daily_energy_projection(
    result: Any,
    selected: Any,
    context: ProcessingContext,
) -> dict[str, Any]:
    history = context.store_data.energy_usage_by_circuit.get(result.circuit_id, {})
    raw_days = history.get("days") if isinstance(history, dict) else None
    if not isinstance(raw_days, list) or selected.median <= 0.0:
        return {}
    today = local_date(context.now, context.time_zone).isoformat()
    values = []
    for item in raw_days:
        if (
            not isinstance(item, dict)
            or item.get("complete") is not True
            or str(item.get("date")) >= today
        ):
            continue
        try:
            value = float(item["usage_kwh"])
        except (KeyError, TypeError, ValueError):
            continue
        if value >= 0.0:
            values.append(value)
    required_days = max(int(result.window_days), 1)
    if len(values) < required_days:
        return {}
    full_period = build_baseline(DAILY_ENERGY_FEATURE, values[-required_days:])
    observed_ratio = max(float(result.daily_usage_kwh), 0.0) / selected.median
    confidence = round(min(selected.confidence, full_period.confidence) * 0.66, 3)
    return {
        "projection_value": round(full_period.median * observed_ratio, 3),
        "projection_low": round(full_period.p10 * observed_ratio, 3),
        "projection_high": round(full_period.p90 * observed_ratio, 3),
        "projection_confidence": confidence,
        "full_period_normal_low": round(full_period.p10, 3),
        "full_period_normal_high": round(full_period.p90, 3),
        "full_period_normal_median": round(full_period.median, 3),
    }


def _contextual_alert_features(
    contextual_comparison: dict[str, Any],
) -> dict[str, Any]:
    features: dict[str, Any] = {}
    for key in (
        "comparison_basis",
        "baseline_context",
        "baseline_fallback_level",
    ):
        value = contextual_comparison.get(key)
        if value is not None:
            features[key] = value
    for source, target in (
        ("baseline_sample_count", "baseline_sample_count"),
        ("contextual_baseline_median_kwh", "contextual_baseline_median_kwh"),
        ("contextual_baseline_p90_kwh", "contextual_baseline_p90_kwh"),
        ("contextual_baseline_confidence", "contextual_baseline_confidence"),
    ):
        value = contextual_comparison.get(source)
        if value is not None:
            features[target] = float(value)
    return features


def _status_label_for_evidence(status: str) -> str:
    overrides = {"waiting_for_delta": "Waiting For Energy Change"}
    if status in overrides:
        return overrides[status]
    return " ".join(part.capitalize() for part in status.split("_"))


def _status_explanation_for_evidence(status: str) -> str:
    if status == "waiting_for_delta":
        return (
            "A cumulative kWh source is present, but the analyzer has not "
            "observed it increase since tracking started."
        )
    if status == "learning":
        return "The analyzer is still collecting the rolling daily kWh baseline."
    if status == "tracking":
        return "The analyzer is tracking daily usage from cumulative kWh changes."
    if status == "over_threshold":
        return "Today usage is above the configured rolling-window threshold."
    return f"{_status_label_for_evidence(status)} status reported by the analyzer."


def _energy_usage_next_check(status: str) -> str:
    if status == "waiting_for_delta":
        return (
            "Let the analyzer see the energy sensor increase, or confirm the "
            "circuit has a cumulative kWh source."
        )
    if status == "learning":
        return "Let the analyzer retain enough full days for the rolling baseline."
    if status == "tracking":
        return "No action is needed unless the usage looks wrong for the appliance."
    if status == "over_threshold":
        return "Review recent appliance runtime and confirm the mapped kWh source."
    return "Review the sensor attributes for the observed evidence."


def _format_kwh(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")
