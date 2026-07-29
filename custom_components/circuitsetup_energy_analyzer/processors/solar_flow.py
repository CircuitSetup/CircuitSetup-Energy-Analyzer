"""Solar flow and load-shift processor."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..contextual_baseline import (
    ContextKey,
    ContextualBaselineSample,
    context_allows_baseline_learning,
    contextual_stats_storage_key,
    contextual_stats_to_dict,
    daily_energy_fallback_contexts,
    maintenance_context_state,
    season_for_datetime,
    select_contextual_baseline,
    solar_flow_state,
    stored_contextual_samples,
    time_of_day_bucket,
    upsert_contextual_sample,
)
from ..load_shift import (
    FLEXIBLE_LOAD_RUNNING_THRESHOLD_W,
    FlexibleLoadInput,
    SolarLoadShiftResult,
    evaluate_solar_load_shift,
)
from ..models import ApplianceProfile, CircuitConfig, CircuitMode, PowerFlowMode
from ..normalize import NormalizedCircuitSample
from ..solar_flow import (
    EXPORT_TOLERANCE_W,
    HIGH_SOLAR_SURPLUS_THRESHOLD_W,
    SOLAR_SURPLUS_THRESHOLD_W,
    SolarFlowInput,
    SolarFlowResult,
    calculate_solar_flow,
)
from .base import FeatureResult, ProcessingContext, StateUpdate

FLEXIBLE_SOLAR_LOAD_PROFILES = frozenset(
    {
        ApplianceProfile.EV_CHARGER,
        ApplianceProfile.HVAC,
        ApplianceProfile.HVAC_COMPRESSOR,
        ApplianceProfile.MINI_SPLIT,
        ApplianceProfile.POOL_PUMP,
        ApplianceProfile.WATER_HEATER,
    },
)

type SolarFlowSettingsProvider = Callable[[str], Mapping[str, Any]]

SOLAR_SURPLUS_CONTEXT_FEATURE = "solar_surplus_power_w"


class SolarFlowProcessor:
    """Calculate solar generation, grid flow, surplus, and load-shift state."""

    name = "solar_flow"

    def __init__(
        self,
        *,
        settings_for_circuit: SolarFlowSettingsProvider,
    ) -> None:
        self._settings_for_circuit = settings_for_circuit

    def process(
        self,
        samples: list[tuple[CircuitConfig, NormalizedCircuitSample]],
        context: ProcessingContext,
    ) -> FeatureResult:
        """Return state updates for every mains NILM sample in a batch."""
        mains_items = [
            (config, sample)
            for config, sample in samples
            if _is_mains_nilm(config)
        ]
        if not mains_items:
            return FeatureResult()

        generation = [
            SolarFlowInput(
                circuit_id=config.circuit_id,
                real_power_w=sample.real_power,
            )
            for config, sample in samples
            if _is_generation(config)
        ]
        flexible_loads = [
            FlexibleLoadInput(
                circuit_id=config.circuit_id,
                name=config.name,
                appliance_profile=config.appliance_profile.value,
                real_power_w=sample.real_power,
            )
            for config, sample in samples
            if _is_flexible_solar_load(config)
        ]

        state_updates: list[StateUpdate] = []
        store_dirty = False
        for config, sample in mains_items:
            settings = self._settings_for_circuit(config.circuit_id)
            solar_flow = calculate_solar_flow(
                mains=SolarFlowInput(
                    circuit_id=config.circuit_id,
                    real_power_w=sample.real_power,
                ),
                generation=generation,
                export_tolerance_w=_nonnegative_float_value(
                    settings.get("export_tolerance_w"),
                    default=EXPORT_TOLERANCE_W,
                ),
                solar_surplus_threshold_w=_nonnegative_float_value(
                    settings.get("solar_surplus_threshold_w"),
                    default=SOLAR_SURPLUS_THRESHOLD_W,
                ),
                high_solar_surplus_threshold_w=_nonnegative_float_value(
                    settings.get("high_solar_surplus_threshold_w"),
                    default=HIGH_SOLAR_SURPLUS_THRESHOLD_W,
                ),
            )
            load_shift = evaluate_solar_load_shift(
                solar_load_shift_available_w=solar_flow.load_shift_available_w,
                solar_surplus_status=solar_flow.solar_surplus_status,
                grid_import_w=solar_flow.grid_import_w,
                flexible_loads=flexible_loads,
                running_threshold_w=_nonnegative_float_value(
                    settings.get("flexible_load_running_threshold_w"),
                    default=FLEXIBLE_LOAD_RUNNING_THRESHOLD_W,
                ),
            )
            contextual_evidence, contextual_dirty = _solar_contextual_evidence(
                config=config,
                result=solar_flow,
                context=context,
            )
            store_dirty = store_dirty or contextual_dirty
            state_updates.extend(
                solar_flow_state_updates(
                    config.circuit_id,
                    solar_flow,
                    load_shift,
                    contextual_evidence,
                ),
            )

        return FeatureResult(state_updates=state_updates, store_dirty=store_dirty)


def solar_flow_state_updates(
    circuit_id: str,
    result: SolarFlowResult,
    load_shift: SolarLoadShiftResult,
    contextual_evidence: Mapping[str, Any] | None = None,
) -> list[StateUpdate]:
    """Build state updates for a solar flow calculation."""
    return [
        StateUpdate(
            ("solar_generation_w_by_circuit", circuit_id),
            result.solar_generation_w,
        ),
        StateUpdate(
            ("solar_site_consumption_w_by_circuit", circuit_id),
            result.site_consumption_w,
        ),
        StateUpdate(
            ("solar_grid_import_w_by_circuit", circuit_id),
            result.grid_import_w,
        ),
        StateUpdate(
            ("solar_grid_export_w_by_circuit", circuit_id),
            result.grid_export_w,
        ),
        StateUpdate(
            ("solar_self_consumption_percent_by_circuit", circuit_id),
            result.self_consumption_percent,
        ),
        StateUpdate(
            ("solar_powered_percent_by_circuit", circuit_id),
            result.solar_powered_percent,
        ),
        StateUpdate(("solar_surplus_w_by_circuit", circuit_id), result.solar_surplus_w),
        StateUpdate(
            ("solar_load_shift_w_by_circuit", circuit_id),
            result.load_shift_available_w,
        ),
        StateUpdate(
            ("solar_flexible_load_power_w_by_circuit", circuit_id),
            load_shift.active_flexible_load_power_w,
        ),
        StateUpdate(
            ("solar_flexible_load_coverage_percent_by_circuit", circuit_id),
            load_shift.solar_coverage_percent,
        ),
        StateUpdate(("solar_flow_status_by_circuit", circuit_id), result.status),
        StateUpdate(
            ("solar_surplus_status_by_circuit", circuit_id),
            result.solar_surplus_status,
        ),
        StateUpdate(
            ("solar_load_shift_status_by_circuit", circuit_id),
            load_shift.status,
        ),
        StateUpdate(
            ("solar_flow_evidence_by_circuit", circuit_id),
            {
                **result.features,
                "status": result.status,
                "solar_surplus_status": result.solar_surplus_status,
                **dict(contextual_evidence or {}),
            },
        ),
        StateUpdate(
            ("solar_load_shift_evidence_by_circuit", circuit_id),
            load_shift.features,
        ),
    ]


def _solar_contextual_evidence(
    *,
    config: CircuitConfig,
    result: SolarFlowResult,
    context: ProcessingContext,
) -> tuple[dict[str, Any], bool]:
    context_key = _solar_context_key(config, result, context)
    raw_samples = context.store_data.contextual_baseline_samples_by_circuit.get(
        config.circuit_id,
        [],
    )
    selected = select_contextual_baseline(
        circuit_id=config.circuit_id,
        feature=SOLAR_SURPLUS_CONTEXT_FEATURE,
        samples=stored_contextual_samples(
            config.circuit_id,
            raw_samples,
            cache=context.contextual_samples_cache,
        ),
        fallback_contexts=daily_energy_fallback_contexts(context_key),
    )
    evidence: dict[str, Any] = {}
    store_dirty = False
    if selected is not None:
        evidence = {
            "comparison_basis": "contextual",
            "baseline_context": ", ".join(selected.context.values()),
            "baseline_fallback_level": selected.fallback_level,
            "baseline_sample_count": selected.sample_count,
            "contextual_baseline_median_w": round(selected.median, 3),
            "contextual_baseline_p90_w": round(selected.p90, 3),
            "contextual_baseline_confidence": selected.confidence,
        }
        context.store_data.contextual_baselines_by_circuit.setdefault(
            config.circuit_id,
            {},
        )[contextual_stats_storage_key(selected)] = contextual_stats_to_dict(selected)
        store_dirty = True

    if context_allows_baseline_learning(context_key):
        samples = context.store_data.contextual_baseline_samples_by_circuit.setdefault(
            config.circuit_id,
            [],
        )
        before = [dict(sample) for sample in samples]
        for feature, value in _solar_context_values(result).items():
            upsert_contextual_sample(
                samples,
                ContextualBaselineSample(
                    timestamp=context.now,
                    circuit_id=config.circuit_id,
                    feature=feature,
                    value=value,
                    context=context_key,
                    source="solar_flow",
                ),
                time_zone=context.time_zone,
                cache=context.contextual_samples_cache,
            )
        return evidence, store_dirty or before != samples
    return evidence, store_dirty


def _solar_context_key(
    config: CircuitConfig,
    result: SolarFlowResult,
    context: ProcessingContext,
) -> ContextKey:
    values = {
        "appliance_profile": config.appliance_profile.value,
        "circuit_mode": config.mode.value,
        "power_flow_mode": config.power_flow.value,
        "season": season_for_datetime(context.now, time_zone=context.time_zone),
        "solar_flow_state": solar_flow_state(
            result.status,
            result.solar_surplus_status,
        ),
        "time_of_day": time_of_day_bucket(context.now, time_zone=context.time_zone),
    }
    maintenance_state = maintenance_context_state(
        context.store_data,
        circuit_id=config.circuit_id,
        timestamp=context.now,
        time_zone=context.time_zone,
    )
    if maintenance_state is not None:
        values["maintenance_state"] = maintenance_state
    return ContextKey.from_mapping(values)


def _solar_context_values(result: SolarFlowResult) -> dict[str, float]:
    return {
        "solar_generation_power_w": result.solar_generation_w,
        "grid_import_power_w": result.grid_import_w,
        "grid_export_power_w": result.grid_export_w,
        "site_consumption_power_w": result.site_consumption_w,
        SOLAR_SURPLUS_CONTEXT_FEATURE: result.solar_surplus_w,
    }


def _is_mains_nilm(config: CircuitConfig) -> bool:
    return (
        config.mode is CircuitMode.MAINS_NILM
        or config.appliance_profile is ApplianceProfile.MAINS_NILM
    )


def _is_generation(config: CircuitConfig) -> bool:
    return (
        config.power_flow is PowerFlowMode.GENERATION
        or config.appliance_profile is ApplianceProfile.SOLAR_INVERTER
    )


def _is_flexible_solar_load(config: CircuitConfig) -> bool:
    return (
        config.power_flow is PowerFlowMode.LOAD
        and config.mode is not CircuitMode.MAINS_NILM
        and config.appliance_profile in FLEXIBLE_SOLAR_LOAD_PROFILES
    )


def _nonnegative_float_value(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0.0 else default
