from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .baseline import build_baseline
from .contextual_baseline import (
    season_for_datetime,
)
from .contextual_baseline import (
    temperature_bin as contextual_temperature_bin,
)

MIN_WEATHER_CONTEXT_SAMPLES = 3


@dataclass(frozen=True, slots=True)
class WeatherContextSample:
    """Observed HVAC activity for a comparable outdoor temperature period."""

    temperature: float
    runtime_minutes: float
    duty_cycle_percent: float
    timestamp: datetime | None = None
    energy_kwh: float | None = None
    start_count: int | None = None


def evaluate_weather_context(
    *,
    outdoor_temperature: float | None,
    current_runtime_minutes: float,
    current_duty_cycle_percent: float,
    history: Iterable[WeatherContextSample],
    mode: str = "cooling",
    display_temperature: float | None = None,
    display_temperature_unit: str = "°F",
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Return weather context for current HVAC activity."""

    if outdoor_temperature is None:
        return {
            "status": "no_temperature_source",
            "explanation": "No outdoor temperature source is configured.",
        }

    temperature = float(outdoor_temperature)
    user_temperature = (
        round(float(display_temperature), 3)
        if display_temperature is not None
        else round(temperature, 3)
    )
    user_unit = _temperature_unit(display_temperature_unit)
    weather_mode = _weather_mode(mode)
    comparable = _select_weather_baseline(
        temperature=temperature,
        mode=weather_mode,
        history=list(history),
        observed_at=observed_at,
    )
    if comparable is None:
        return {
            "status": "learning",
            "current_outdoor_temperature": user_temperature,
            "temperature_unit": user_unit,
            "temperature_f": round(temperature, 3),
            "temperature_bin": temperature_bin(temperature),
            "mode": weather_mode,
            "baseline_fallback_level": "not_enough_data",
            "explanation": (
                "Learning HVAC activity for similar outdoor temperatures."
            ),
        }

    comparable_samples = comparable["samples"]
    runtime_values = sorted(
        float(sample.runtime_minutes) for sample in comparable_samples
    )
    duty_values = sorted(
        float(sample.duty_cycle_percent) for sample in comparable_samples
    )
    runtime_baseline = build_baseline(
        "runtime_minutes",
        [sample.runtime_minutes for sample in comparable_samples],
    )
    duty_baseline = build_baseline(
        "duty_cycle_percent",
        [sample.duty_cycle_percent for sample in comparable_samples],
    )
    runtime_range = [runtime_values[0], runtime_values[-1]]
    duty_range = [duty_values[0], duty_values[-1]]
    observed_runtime = round(float(current_runtime_minutes), 3)
    observed_duty = round(float(current_duty_cycle_percent), 3)
    above_range = observed_runtime > (runtime_baseline.p90 * 1.25)
    status = (
        "above_weather_adjusted_range" if above_range else "weather_correlated"
    )

    return {
        "status": status,
        "current_outdoor_temperature": user_temperature,
        "temperature_unit": user_unit,
        "temperature_f": round(temperature, 3),
        "temperature_bin": temperature_bin(temperature),
        "mode": weather_mode,
        "observed_runtime_minutes": observed_runtime,
        "expected_runtime_range_minutes": runtime_range,
        "expected_runtime_median_minutes": round(runtime_baseline.median, 3),
        "expected_runtime_p90_minutes": round(runtime_baseline.p90, 3),
        "observed_duty_cycle_percent": observed_duty,
        "expected_duty_cycle_range_percent": duty_range,
        "expected_duty_cycle_median_percent": round(duty_baseline.median, 3),
        "expected_duty_cycle_p90_percent": round(duty_baseline.p90, 3),
        "baseline_context": comparable["baseline_context"],
        "baseline_fallback_level": comparable["fallback_level"],
        "baseline_sample_count": len(comparable_samples),
        "baseline_confidence": _baseline_confidence(
            len(comparable_samples),
            str(comparable["fallback_level"]),
        ),
        "contextual_status": status,
        "explanation": _explanation(
            status,
            user_temperature,
            user_unit,
            runtime_range,
        ),
    }


def _select_weather_baseline(
    *,
    temperature: float,
    mode: str,
    history: list[WeatherContextSample],
    observed_at: datetime | None,
) -> dict[str, Any] | None:
    current_temperature_bin = contextual_temperature_bin(temperature)
    current_season = season_for_datetime(observed_at) if observed_at else None
    fallback_groups: list[tuple[str, str, list[WeatherContextSample]]] = []
    if current_season is not None:
        fallback_groups.append(
            (
                "exact_context",
                f"{mode}, {current_temperature_bin}, {current_season}",
                [
                    sample
                    for sample in history
                    if _similar_temperature(sample, temperature)
                    and _sample_season(sample) == current_season
                ],
            )
        )
    fallback_groups.append(
        (
            "temperature_context",
            f"{mode}, {current_temperature_bin}",
            [
                sample
                for sample in history
                if _similar_temperature(sample, temperature)
            ],
        )
    )
    if current_season is not None:
        fallback_groups.append(
            (
                "seasonal_context",
                f"{mode}, {current_season}",
                [
                    sample
                    for sample in history
                    if _sample_season(sample) == current_season
                ],
            )
        )
    fallback_groups.append(("global_circuit", mode, list(history)))

    for fallback_level, baseline_context, samples in fallback_groups:
        if len(samples) >= MIN_WEATHER_CONTEXT_SAMPLES:
            return {
                "fallback_level": fallback_level,
                "baseline_context": baseline_context,
                "samples": samples,
            }
    return None


def _similar_temperature(sample: WeatherContextSample, temperature: float) -> bool:
    return abs(sample.temperature - temperature) <= 3.0


def _sample_season(sample: WeatherContextSample) -> str | None:
    return season_for_datetime(sample.timestamp) if sample.timestamp else None


def _baseline_confidence(sample_count: int, fallback_level: str) -> float:
    specificity_weight = {
        "exact_context": 1.0,
        "temperature_context": 0.85,
        "seasonal_context": 0.75,
        "global_circuit": 0.65,
    }.get(fallback_level, 0.65)
    sample_confidence = min(1.0, sample_count / MIN_WEATHER_CONTEXT_SAMPLES)
    return round(sample_confidence * specificity_weight, 3)


def temperature_bin(temperature: float) -> str:
    """Return a friendly temperature bin."""

    if temperature >= 88.0:
        return "hot"
    if temperature >= 75.0:
        return "warm"
    if temperature >= 55.0:
        return "mild"
    return "cool"


def _weather_mode(mode: str) -> str:
    normalized = str(mode or "cooling").strip().lower()
    return normalized if normalized in {"cooling", "heating"} else "cooling"


def _explanation(
    status: str,
    temperature: float,
    unit: str,
    runtime_range: list[float],
) -> str:
    formatted_temperature = _format_temperature(temperature, unit)
    if status == "weather_correlated":
        return (
            "HVAC activity is consistent with learned activity for about "
            f"{formatted_temperature} outdoor conditions."
        )
    return (
        "HVAC activity is above the learned range for about "
        f"{formatted_temperature}. "
        f"Similar-temperature runtime is usually {runtime_range[0]:.1f} to "
        f"{runtime_range[1]:.1f} minutes."
    )


def _temperature_unit(unit: str) -> str:
    normalized = str(unit or "°F").strip()
    lowered = normalized.lower()
    if lowered in {"c", "celsius", "°c"}:
        return "°C"
    if lowered in {"f", "fahrenheit", "°f"}:
        return "°F"
    return normalized or "°F"


def _format_temperature(temperature: float, unit: str) -> str:
    rounded = round(float(temperature), 1)
    if rounded.is_integer():
        return f"{rounded:.0f} {unit}"
    return f"{rounded:.1f} {unit}"
