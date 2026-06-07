from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class WeatherContextSample:
    """Observed HVAC activity for a comparable outdoor temperature period."""

    temperature: float
    runtime_minutes: float
    duty_cycle_percent: float
    energy_kwh: float | None = None
    start_count: int | None = None


def evaluate_weather_context(
    *,
    outdoor_temperature: float | None,
    current_runtime_minutes: float,
    current_duty_cycle_percent: float,
    history: Iterable[WeatherContextSample],
    mode: str = "cooling",
) -> dict[str, Any]:
    """Return weather context for current HVAC activity."""

    if outdoor_temperature is None:
        return {
            "status": "no_temperature_source",
            "explanation": "No outdoor temperature source is configured.",
        }

    temperature = float(outdoor_temperature)
    comparable = [
        sample for sample in history if abs(sample.temperature - temperature) <= 3.0
    ]
    if len(comparable) < 3:
        return {
            "status": "learning",
            "current_outdoor_temperature": temperature,
            "temperature_bin": temperature_bin(temperature),
            "mode": _weather_mode(mode),
            "explanation": (
                "Learning HVAC activity for similar outdoor temperatures."
            ),
        }

    runtime_values = sorted(float(sample.runtime_minutes) for sample in comparable)
    duty_values = sorted(float(sample.duty_cycle_percent) for sample in comparable)
    runtime_range = [runtime_values[0], runtime_values[-1]]
    duty_range = [duty_values[0], duty_values[-1]]
    observed_runtime = round(float(current_runtime_minutes), 3)
    observed_duty = round(float(current_duty_cycle_percent), 3)
    above_range = observed_runtime > (runtime_range[1] * 1.25)
    status = (
        "above_weather_adjusted_range" if above_range else "weather_correlated"
    )

    return {
        "status": status,
        "current_outdoor_temperature": temperature,
        "temperature_bin": temperature_bin(temperature),
        "mode": _weather_mode(mode),
        "observed_runtime_minutes": observed_runtime,
        "expected_runtime_range_minutes": runtime_range,
        "observed_duty_cycle_percent": observed_duty,
        "expected_duty_cycle_range_percent": duty_range,
        "explanation": _explanation(status, temperature, runtime_range),
    }


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
    runtime_range: list[float],
) -> str:
    if status == "weather_correlated":
        return (
            "HVAC activity is consistent with learned activity for about "
            f"{temperature:.0f} F outdoor conditions."
        )
    return (
        f"HVAC activity is above the learned range for about {temperature:.0f} F. "
        f"Similar-temperature runtime is usually {runtime_range[0]:.1f} to "
        f"{runtime_range[1]:.1f} minutes."
    )
