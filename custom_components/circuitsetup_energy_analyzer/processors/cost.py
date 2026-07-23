"""Energy cost processor."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import Any

from ..baseline import build_baseline
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
from ..cost import (
    CostSettings,
    _float_or_none,
    _positive_float_or_none,
    record_cost_sample,
)
from ..local_time import as_ha_local, local_date
from ..models import CircuitConfig
from ..normalize import NormalizedCircuitSample
from .base import FeatureResult, ProcessingContext, StateUpdate

type CostSettingsProvider = Callable[[CircuitConfig | None, str], CostSettings]
type UtilityRateProvider = Callable[[str], float | None]


class CostProcessor:
    """Track billing-cycle cost estimates for one circuit."""

    name = "cost"

    def __init__(
        self,
        *,
        settings_for_config: CostSettingsProvider,
        utility_rate_for_circuit: UtilityRateProvider | None = None,
    ) -> None:
        self._settings_for_config = settings_for_config
        self._utility_rate_for_circuit = utility_rate_for_circuit or (
            lambda _circuit_id: None
        )

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Record cost usage and return state updates."""
        circuit_id = circuit_config.circuit_id
        settings = self._settings_for_config(circuit_config, circuit_id)
        utility_rate = self._utility_rate_for_circuit(circuit_id)
        estimate_updates = self._estimate_state_updates(
            circuit_config,
            context.state,
            settings,
            utility_rate,
        )
        if utility_rate is not None and utility_rate > 0.0:
            settings = replace(
                settings,
                default_rate_per_kwh=utility_rate,
                tou_rate_per_kwh=None,
            )
        result = record_cost_sample(
            context.store_data.cost_by_circuit.setdefault(circuit_id, {}),
            circuit_id=circuit_id,
            timestamp=context.now,
            energy_kwh=sample.energy,
            settings=settings,
            time_zone=context.time_zone,
        )
        if result is None:
            return FeatureResult()
        contextual_comparison = _contextual_cost_comparison(
            result,
            circuit_config,
            sample,
            context,
        )

        return FeatureResult(
            state_updates=[
                StateUpdate(
                    ("cost_current_rate_by_circuit", circuit_id),
                    result.current_rate_per_kwh,
                ),
                StateUpdate(("cost_today_by_circuit", circuit_id), result.cost_today),
                StateUpdate(
                    ("cost_today_status_by_circuit", circuit_id),
                    result.cost_today_status,
                ),
                StateUpdate(("cost_cycle_by_circuit", circuit_id), result.cycle_cost),
                StateUpdate(
                    ("cost_cycle_status_by_circuit", circuit_id),
                    result.cycle_cost_status,
                ),
                StateUpdate(
                    ("cost_cycle_forecast_by_circuit", circuit_id),
                    result.projected_cycle_cost,
                ),
                StateUpdate(("cost_status_by_circuit", circuit_id), result.status),
                StateUpdate(
                    ("cost_evidence_by_circuit", circuit_id),
                    cost_evidence_payload(result, contextual_comparison),
                ),
                *estimate_updates,
            ],
            store_dirty=True,
        )

    def estimate_state_updates(
        self,
        circuit_configs: Iterable[CircuitConfig],
        state: Any,
    ) -> list[StateUpdate]:
        """Refresh cost estimates without recording another energy sample."""
        return [
            update
            for config in circuit_configs
            for update in self._estimate_state_updates(
                config,
                state,
                self._settings_for_config(config, config.circuit_id),
                self._utility_rate_for_circuit(config.circuit_id),
            )
        ]

    def _estimate_state_updates(
        self,
        circuit_config: CircuitConfig,
        state: Any,
        settings: CostSettings,
        utility_rate: float | None,
    ) -> list[StateUpdate]:
        circuit_id = circuit_config.circuit_id
        estimate_rate = _estimate_rate(settings, utility_rate)
        return [
            StateUpdate(
                ("effective_electricity_rate_by_circuit", circuit_id),
                estimate_rate,
            ),
            StateUpdate(
                ("estimated_cost_today_by_circuit", circuit_id),
                _estimated_cost(
                    state.daily_energy_usage_by_circuit.get(circuit_id),
                    estimate_rate,
                ),
            ),
            StateUpdate(
                ("average_cost_per_day_by_circuit", circuit_id),
                _estimated_cost(
                    state.average_kwh_per_day_by_circuit.get(circuit_id),
                    estimate_rate,
                ),
            ),
        ]


def _estimated_cost(energy_kwh: Any, rate: float | None) -> float | None:
    value = _float_or_none(energy_kwh)
    if value is None or rate is None:
        return None
    return round(max(value, 0.0) * rate, 2)


def _estimate_rate(settings: CostSettings, utility_rate: float | None) -> float | None:
    if utility_rate is not None and utility_rate > 0.0:
        return float(utility_rate)
    return _positive_float_or_none(settings.default_rate_per_kwh)


def cost_evidence_payload(
    result: Any,
    contextual_comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the analyzer state payload for cost tracking."""
    payload = {
        "cycle_start": result.cycle_start,
        "cycle_end": result.cycle_end,
        "cycle_start_day": result.cycle_start_day,
        "current_rate_per_kwh": result.current_rate_per_kwh,
        "active_rate_name": result.active_rate_name,
        "delta_kwh": result.delta_kwh,
        "delta_cost": result.delta_cost,
        "cost_today": result.cost_today,
        "cost_today_status": result.cost_today_status,
        "cycle_cost": result.cycle_cost,
        "cycle_cost_status": result.cycle_cost_status,
        "projected_cycle_cost": result.projected_cycle_cost,
        "elapsed_days": result.elapsed_days,
        "cycle_days": result.cycle_days,
        "status": result.status,
    }
    if contextual_comparison:
        payload.update(contextual_comparison)
    return payload


def _contextual_cost_comparison(
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
        feature="cost_today",
        time_zone=context.time_zone,
        calendar_timestamp=context.now,
    )
    raw_samples = context.store_data.contextual_baseline_samples_by_circuit.get(
        circuit_config.circuit_id,
        [],
    )
    current_date = local_date(context.now, context.time_zone)
    historical = [
        item
        for item in stored_contextual_samples(
            circuit_config.circuit_id,
            raw_samples,
            cache=context.contextual_samples_cache,
        )
        if local_date(item.timestamp, context.time_zone) < current_date
    ]
    selected = select_contextual_baseline(
        circuit_id=circuit_config.circuit_id,
        feature="cost_today",
        samples=historical,
        fallback_contexts=daily_energy_fallback_contexts(context_key),
    )
    if result.cost_today is not None and context_allows_baseline_learning(context_key):
        samples = context.store_data.contextual_baseline_samples_by_circuit.setdefault(
            circuit_config.circuit_id,
            [],
        )
        upsert_contextual_sample(
            samples,
            ContextualBaselineSample(
                timestamp=context.now,
                circuit_id=circuit_config.circuit_id,
                feature="cost_today",
                value=result.cost_today,
                context=context_key,
                source="cost",
            ),
            time_zone=context.time_zone,
            cache=context.contextual_samples_cache,
        )
    if selected is None:
        return {}
    context.store_data.contextual_baselines_by_circuit.setdefault(
        circuit_config.circuit_id,
        {},
    )[contextual_stats_storage_key(selected)] = contextual_stats_to_dict(selected)
    attrs = {
        "comparison_mode": "same_time_of_day",
        "as_of": as_ha_local(context.now, context.time_zone).isoformat(),
        "contextual_expected_range": [
            round(selected.p10, 3),
            round(selected.p90, 3),
        ],
        "contextual_baseline_median_cost": round(selected.median, 3),
        "contextual_baseline_confidence": selected.confidence,
    }
    history = context.store_data.cost_by_circuit.get(circuit_config.circuit_id, {})
    raw_days = history.get("days") if isinstance(history, dict) else None
    values: list[float] = []
    if isinstance(raw_days, list):
        for item in raw_days:
            if not isinstance(item, dict) or item.get("complete") is not True:
                continue
            try:
                value = float(item["cost"])
            except (KeyError, TypeError, ValueError):
                continue
            if value >= 0.0:
                values.append(value)
    if result.cost_today is None or selected.median <= 0.0 or len(values) < 7:
        return attrs
    full_period = build_baseline("cost_today", values[-7:])
    observed_ratio = result.cost_today / selected.median
    attrs.update(
        {
            "projection_value": round(full_period.median * observed_ratio, 3),
            "projection_low": round(full_period.p10 * observed_ratio, 3),
            "projection_high": round(full_period.p90 * observed_ratio, 3),
            "projection_confidence": round(
                min(selected.confidence, full_period.confidence) * 0.66,
                3,
            ),
            "full_period_normal_low": round(full_period.p10, 3),
            "full_period_normal_high": round(full_period.p90, 3),
            "full_period_normal_median": round(full_period.median, 3),
        }
    )
    return attrs
