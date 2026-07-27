from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contextual_baseline import (
    RainContext,
    rain_context,
    water_flow_state,
)

SUPPORTED_RAIN_PUMP_PROFILES = {"sump_pump", "water_pump", "well_pump"}
SUPPORTED_FLOW_PROFILES = {
    "water_pump",
    "well_pump",
    "water_heater",
    "washer",
    "dishwasher",
}
RAIN_THRESHOLD_PCT = 25.0
MIN_COMPARABLE_WINDOWS = 10


@dataclass(frozen=True, slots=True)
class RainPumpCorrelationInput:
    circuit_id: str
    appliance_profile: str
    pump_runtime_minutes: float
    dry_baseline_minutes: float | None
    comparable_window_count: int
    rain_active: bool | None
    rain_intensity_per_hour: float | None
    compressor_runtime_minutes: float
    compressor_duty_cycle_percent: float
    rain_intensity_unit: str | None = "mm/h"
    sensitivity_delta_threshold_pct: float = RAIN_THRESHOLD_PCT


@dataclass(frozen=True, slots=True)
class FlowCorrelationInput:
    circuit_id: str
    appliance_profile: str
    flow_active_minutes: float
    appliance_runtime_minutes: float
    recent_related_runtime_minutes: float
    mapped_appliance_count: int
    threshold_minutes: float
    expects_water_flow: bool
    comparable_window_count: int
    mapped_appliance_runtime_minutes: float = 0.0
    flow_source_configured: bool = True


def evaluate_rain_pump_correlation(inputs: RainPumpCorrelationInput) -> dict[str, Any]:
    profile = _normalize_profile(inputs.appliance_profile)
    pump_runtime = _round_minutes(inputs.pump_runtime_minutes)
    dry_baseline = (
        None
        if inputs.dry_baseline_minutes is None
        else _round_minutes(inputs.dry_baseline_minutes)
    )
    comparable_window_count = max(int(inputs.comparable_window_count), 0)
    if profile not in SUPPORTED_RAIN_PUMP_PROFILES:
        return _rain_result(
            inputs,
            status="unconfigured",
            dry_baseline_minutes=dry_baseline,
            comparable_window_count=comparable_window_count,
        )

    if comparable_window_count < MIN_COMPARABLE_WINDOWS or dry_baseline is None:
        return _rain_result(
            inputs,
            status="learning",
            dry_baseline_minutes=dry_baseline,
            comparable_window_count=comparable_window_count,
        )

    rain_info = rain_context(
        inputs.rain_active,
        inputs.rain_intensity_per_hour,
        unit=inputs.rain_intensity_unit,
    )
    rain_adjustment = 0.0
    contributing_factors: list[str] = [f"baseline:{dry_baseline:.1f}"]
    if rain_info.state in {"raining", "heavy_rain"}:
        rain_adjustment = dry_baseline * 2.0
        if rain_info.intensity_mm_per_hour is not None:
            rain_adjustment += rain_info.intensity_mm_per_hour * 10.0
            contributing_factors.append("rain_intensity")
        contributing_factors.append("rain")

    compressor_adjustment = 0.0
    compressor_runtime = _round_minutes(inputs.compressor_runtime_minutes)
    compressor_duty_cycle = max(float(inputs.compressor_duty_cycle_percent), 0.0)
    if compressor_runtime > 0.0 and compressor_duty_cycle > 0.0:
        compressor_adjustment = min(
            compressor_runtime * (compressor_duty_cycle / 100.0) * 0.5,
            dry_baseline * 1.5,
        )
        contributing_factors.append("compressor")

    expected_runtime = _round_minutes(
        dry_baseline + rain_adjustment + compressor_adjustment
    )
    threshold_ratio = max(float(inputs.sensitivity_delta_threshold_pct), 0.0) / 100.0
    actual_minus_expected = _round_minutes(pump_runtime - expected_runtime)

    if pump_runtime > expected_runtime * (1.0 + threshold_ratio):
        status = "possible_excess_pump_activity"
    elif rain_adjustment > 0.0 and compressor_adjustment > 0.0:
        status = "weather_explained"
    elif rain_adjustment > 0.0:
        status = "rain_explained"
    elif compressor_adjustment > 0.0:
        status = "compressor_explained"
    elif pump_runtime < dry_baseline * (1.0 - threshold_ratio):
        status = "possible_missing_pump_activity"
    else:
        status = "normal"

    confidence = _rain_confidence(
        comparable_window_count=comparable_window_count,
        status=status,
        rain_active=inputs.rain_active is True,
        compressor_adjustment=compressor_adjustment,
    )
    return _rain_result(
        inputs,
        status=status,
        dry_baseline_minutes=dry_baseline,
        comparable_window_count=comparable_window_count,
        pump_runtime_minutes=pump_runtime,
        expected_runtime_minutes=expected_runtime,
        rain_adjustment_minutes=_round_minutes(rain_adjustment),
        compressor_adjustment_minutes=_round_minutes(compressor_adjustment),
        actual_minus_expected_minutes=actual_minus_expected,
        contributing_factors=contributing_factors,
        confidence=confidence,
    )


def evaluate_flow_correlation(inputs: FlowCorrelationInput) -> dict[str, Any]:
    profile = _normalize_profile(inputs.appliance_profile)
    flow_active = _round_minutes(inputs.flow_active_minutes)
    appliance_runtime = _round_minutes(inputs.appliance_runtime_minutes)
    recent_related_runtime = _round_minutes(inputs.recent_related_runtime_minutes)
    threshold_minutes = _round_minutes(inputs.threshold_minutes)
    comparable_window_count = max(int(inputs.comparable_window_count), 0)
    mapped_appliance_count = max(int(inputs.mapped_appliance_count), 0)
    mapped_appliance_runtime = _round_minutes(
        inputs.mapped_appliance_runtime_minutes
    )

    if not inputs.flow_source_configured:
        return _flow_result(
            inputs,
            status="unconfigured",
            flow_active_minutes=flow_active,
            appliance_runtime_minutes=appliance_runtime,
            recent_related_runtime_minutes=recent_related_runtime,
            mismatch_minutes=0.0,
            mapped_appliance_count=mapped_appliance_count,
            mapped_appliance_runtime_minutes=mapped_appliance_runtime,
            recent_flow_explains_activity=False,
            friendly_summary="No water-flow sensor is configured for this appliance.",
            confidence=0.3,
        )

    if profile not in SUPPORTED_FLOW_PROFILES or not inputs.expects_water_flow:
        return _flow_result(
            inputs,
            status="unconfigured",
            flow_active_minutes=flow_active,
            appliance_runtime_minutes=appliance_runtime,
            recent_related_runtime_minutes=recent_related_runtime,
            mismatch_minutes=_round_minutes(
                max(
                    flow_active
                    - (
                        max(appliance_runtime, mapped_appliance_runtime)
                        + recent_related_runtime
                    ),
                    0.0,
                )
            ),
            mapped_appliance_count=mapped_appliance_count,
            mapped_appliance_runtime_minutes=mapped_appliance_runtime,
            recent_flow_explains_activity=False,
            friendly_summary=_generic_flow_summary(flow_active, profile),
            confidence=0.3,
        )

    if comparable_window_count < MIN_COMPARABLE_WINDOWS:
        return _flow_result(
            inputs,
            status="learning",
            flow_active_minutes=flow_active,
            appliance_runtime_minutes=appliance_runtime,
            recent_related_runtime_minutes=recent_related_runtime,
            mismatch_minutes=_round_minutes(
                max(
                    flow_active
                    - (
                        max(appliance_runtime, mapped_appliance_runtime)
                        + recent_related_runtime
                    ),
                    0.0,
                )
            ),
            mapped_appliance_count=mapped_appliance_count,
            mapped_appliance_runtime_minutes=mapped_appliance_runtime,
            recent_flow_explains_activity=False,
            friendly_summary=_generic_flow_summary(flow_active, profile),
            confidence=0.35,
        )

    recent_flow_explains_activity = _recent_flow_explains_activity(
        profile=profile,
        appliance_runtime_minutes=appliance_runtime,
        recent_related_runtime_minutes=recent_related_runtime,
        threshold_minutes=threshold_minutes,
    )
    mismatch_minutes = _round_minutes(
        max(
            flow_active
            - (
                max(appliance_runtime, mapped_appliance_runtime)
                + recent_related_runtime
            ),
            0.0,
        )
    )
    load_without_flow_minutes = _round_minutes(
        max(appliance_runtime - (flow_active + recent_related_runtime), 0.0)
    )
    status = "normal"

    if (
        flow_active >= threshold_minutes
        and mapped_appliance_runtime <= 0.0
    ):
        status = "possible_flow_without_load"
    elif (
        appliance_runtime >= threshold_minutes
        and flow_active <= 0.0
        and recent_related_runtime <= 0.0
        and mapped_appliance_count <= 0
    ) or (
        appliance_runtime >= threshold_minutes
        and flow_active <= 0.0
        and not recent_flow_explains_activity
        and recent_related_runtime > 0.0
    ):
        status = "possible_sensor_problem"
        mismatch_minutes = load_without_flow_minutes
    elif (
        appliance_runtime >= threshold_minutes
        and flow_active <= 0.0
        and not recent_flow_explains_activity
    ):
        status = "possible_load_without_flow"
        mismatch_minutes = load_without_flow_minutes
    elif (
        flow_active >= threshold_minutes
        and appliance_runtime > 0.0
        and recent_flow_explains_activity
    ):
        status = "normal"

    friendly_summary = _flow_summary(
        status=status,
        flow_active_minutes=flow_active,
        mapped_appliance_count=mapped_appliance_count,
    )
    confidence = _flow_confidence(
        comparable_window_count=comparable_window_count,
        recent_flow_explains_activity=recent_flow_explains_activity,
        mapped_appliance_count=mapped_appliance_count,
        status=status,
    )
    return _flow_result(
        inputs,
        status=status,
        flow_active_minutes=flow_active,
        appliance_runtime_minutes=appliance_runtime,
        recent_related_runtime_minutes=recent_related_runtime,
        mismatch_minutes=mismatch_minutes,
        mapped_appliance_count=mapped_appliance_count,
        mapped_appliance_runtime_minutes=mapped_appliance_runtime,
        recent_flow_explains_activity=recent_flow_explains_activity,
        friendly_summary=friendly_summary,
        confidence=confidence,
    )


def _rain_result(
    inputs: RainPumpCorrelationInput,
    *,
    status: str,
    dry_baseline_minutes: float | None,
    comparable_window_count: int,
    pump_runtime_minutes: float | None = None,
    expected_runtime_minutes: float = 0.0,
    rain_adjustment_minutes: float = 0.0,
    compressor_adjustment_minutes: float = 0.0,
    actual_minus_expected_minutes: float = 0.0,
    contributing_factors: list[str] | None = None,
    confidence: float = 0.0,
) -> dict[str, Any]:
    pump_runtime_minutes = _round_minutes(
        inputs.pump_runtime_minutes
        if pump_runtime_minutes is None
        else pump_runtime_minutes
    )
    result = {
        "status": status,
        "circuit_id": inputs.circuit_id,
        "appliance_profile": _normalize_profile(inputs.appliance_profile),
        "pump_runtime_minutes": pump_runtime_minutes,
        "dry_baseline_minutes": dry_baseline_minutes,
        "comparable_window_count": comparable_window_count,
        "expected_runtime_minutes": _round_minutes(expected_runtime_minutes),
        "rain_adjustment_minutes": _round_minutes(rain_adjustment_minutes),
        "compressor_adjustment_minutes": _round_minutes(compressor_adjustment_minutes),
        "actual_minus_expected_minutes": _round_minutes(actual_minus_expected_minutes),
        "contributing_factors": contributing_factors or ["baseline"],
        "confidence": round(float(confidence), 2),
    }
    result.update(_rain_context_attributes(inputs, result))
    result["friendly_summary"] = _rain_summary(result)
    return result


def _flow_result(
    inputs: FlowCorrelationInput,
    *,
    status: str,
    flow_active_minutes: float,
    appliance_runtime_minutes: float,
    recent_related_runtime_minutes: float,
    mismatch_minutes: float,
    mapped_appliance_count: int,
    mapped_appliance_runtime_minutes: float,
    recent_flow_explains_activity: bool,
    friendly_summary: str,
    confidence: float,
) -> dict[str, Any]:
    result = {
        "status": status,
        "circuit_id": inputs.circuit_id,
        "appliance_profile": _normalize_profile(inputs.appliance_profile),
        "flow_active_minutes": _round_minutes(flow_active_minutes),
        "appliance_runtime_minutes": _round_minutes(appliance_runtime_minutes),
        "recent_related_runtime_minutes": _round_minutes(
            recent_related_runtime_minutes
        ),
        "mismatch_minutes": _round_minutes(mismatch_minutes),
        "comparable_window_count": inputs.comparable_window_count,
        "mapped_appliance_count": mapped_appliance_count,
        "mapped_appliance_runtime_minutes": _round_minutes(
            mapped_appliance_runtime_minutes
        ),
        "recent_flow_explains_activity": bool(recent_flow_explains_activity),
        "friendly_summary": friendly_summary,
        "confidence": round(float(confidence), 2),
    }
    result.update(_flow_context_attributes(inputs, result))
    return result


def _rain_context_attributes(
    inputs: RainPumpCorrelationInput,
    result: dict[str, Any],
) -> dict[str, Any]:
    rain_info = _rain_context_for_input(inputs)
    state = rain_info.state
    intensity = rain_info.intensity_bin
    context_parts = [state]
    if state in {"ambiguous", "raining", "heavy_rain"} and intensity not in {
        "unknown",
        "none",
    }:
        context_parts.append(intensity)
    if state in {"raining", "heavy_rain"}:
        fallback_level = "rain_adjusted_context"
    elif state == "ambiguous":
        fallback_level = "ambiguous_rain_context"
    elif state == "unknown":
        fallback_level = "unknown_rain_context"
    else:
        fallback_level = "dry_context"
    expected_runtime = _round_minutes(result.get("expected_runtime_minutes", 0.0))
    return {
        "baseline_context": ", ".join(context_parts),
        "baseline_fallback_level": fallback_level,
        "baseline_sample_count": int(result.get("comparable_window_count", 0)),
        "contextual_status": str(result.get("status", "")),
        "contextual_baseline_confidence": result.get("confidence", 0.0),
        "dry_baseline_minutes": result.get("dry_baseline_minutes"),
        "rain_adjusted_baseline_minutes": expected_runtime,
        "rain_context_issues": list(rain_info.issues),
        "rain_intensity_bin": intensity,
        "rain_intensity_mm_per_hour": rain_info.intensity_mm_per_hour,
        "rain_state": state,
    }


def _rain_context_for_input(inputs: RainPumpCorrelationInput) -> RainContext:
    return rain_context(
        inputs.rain_active,
        inputs.rain_intensity_per_hour,
        unit=inputs.rain_intensity_unit,
    )


def _flow_context_attributes(
    inputs: FlowCorrelationInput,
    result: dict[str, Any],
) -> dict[str, Any]:
    flow_active = _round_minutes(result.get("flow_active_minutes", 0.0))
    recent_related = _round_minutes(inputs.recent_related_runtime_minutes)
    flow_context = (
        water_flow_state(True, flow_active)
        if flow_active > 0.0
        else "recent_flow"
        if recent_related > 0.0
        else water_flow_state(False, 0.0)
    )
    return {
        "baseline_context": flow_context,
        "baseline_fallback_level": "water_flow_context",
        "baseline_sample_count": int(result.get("comparable_window_count", 0)),
        "contextual_status": str(result.get("status", "")),
        "contextual_baseline_confidence": result.get("confidence", 0.0),
    }


def _rain_confidence(
    *,
    comparable_window_count: int,
    status: str,
    rain_active: bool,
    compressor_adjustment: float,
) -> float:
    if status == "learning":
        return 0.35
    confidence = 0.6 + min(comparable_window_count, 20) / 100.0
    if rain_active:
        confidence += 0.1
    if compressor_adjustment > 0.0:
        confidence += 0.05
    return min(confidence, 0.95)


def _flow_confidence(
    *,
    comparable_window_count: int,
    recent_flow_explains_activity: bool,
    mapped_appliance_count: int,
    status: str,
) -> float:
    if status == "learning":
        return 0.35
    confidence = 0.58 + min(comparable_window_count, 20) / 120.0
    if recent_flow_explains_activity:
        confidence += 0.1
    if mapped_appliance_count > 0:
        confidence += 0.05
    return min(confidence, 0.92)


def _rain_summary(result: dict[str, Any]) -> str:
    status = result["status"]
    if status == "learning":
        return "Learning rain and pump correlations from comparable windows."
    if status == "possible_excess_pump_activity":
        return (
            "Pump runtime is above the weather-adjusted expectation by "
            f"{_format_minutes(result['actual_minus_expected_minutes'])} minutes."
        )
    if status == "rain_explained":
        return "Rain appears to explain the elevated pump runtime."
    if status == "weather_explained":
        return "Rain and compressor activity explain the higher pump runtime."
    if status == "compressor_explained":
        return "Compressor activity explains the elevated pump runtime."
    if status == "possible_missing_pump_activity":
        return "Expected pump runtime is not showing up in the observed window."
    return "Pump runtime is within the learned range."


def _flow_summary(
    *,
    status: str,
    flow_active_minutes: float,
    mapped_appliance_count: int,
) -> str:
    if status == "possible_flow_without_load":
        return (
            "Water flow has been active for "
            f"{_format_minutes(flow_active_minutes)} minutes "
            "with no mapped water appliance activity."
        )
    if status == "possible_load_without_flow":
        return "Mapped water appliance activity is present without matching flow."
    if status == "possible_sensor_problem":
        return (
            "Flow and appliance activity do not agree, which suggests a sensor "
            "problem."
        )
    if status == "learning":
        return "Learning water flow correlations from comparable windows."
    if mapped_appliance_count <= 0:
        return "No mapped water appliances are available for comparison."
    return "Water flow and appliance activity are aligned."


def _generic_flow_summary(flow_active_minutes: float, profile: str) -> str:
    if flow_active_minutes > 0.0:
        return (
            "Water flow has been active for "
            f"{_format_minutes(flow_active_minutes)} minutes "
            f"for {profile}."
        )
    return f"No mapped water appliance activity is available for {profile}."


def _recent_flow_explains_activity(
    *,
    profile: str,
    appliance_runtime_minutes: float,
    recent_related_runtime_minutes: float,
    threshold_minutes: float,
) -> bool:
    if recent_related_runtime_minutes <= 0.0:
        return False
    if profile == "water_heater":
        return True
    if appliance_runtime_minutes <= 0.0:
        return False
    return recent_related_runtime_minutes >= min(
        appliance_runtime_minutes * 0.25,
        max(threshold_minutes, 1.0),
    )


def _normalize_profile(profile: str) -> str:
    return str(profile or "").strip().lower()


def _round_minutes(value: float) -> float:
    return round(float(value), 1)


def _format_minutes(value: float) -> str:
    rounded = _round_minutes(value)
    if rounded.is_integer():
        return f"{rounded:.0f}"
    return f"{rounded:.1f}"
