from __future__ import annotations

from custom_components.circuitsetup_energy_analyzer.weather_context import (
    WeatherContextSample,
    evaluate_weather_context,
)


def test_weather_context_marks_hot_weather_hvac_activity_correlated() -> None:
    result = evaluate_weather_context(
        outdoor_temperature=91.0,
        current_runtime_minutes=180.0,
        current_duty_cycle_percent=45.0,
        history=[
            WeatherContextSample(
                temperature=90.0,
                runtime_minutes=170.0,
                duty_cycle_percent=44.0,
            ),
            WeatherContextSample(
                temperature=92.0,
                runtime_minutes=190.0,
                duty_cycle_percent=48.0,
            ),
            WeatherContextSample(
                temperature=89.0,
                runtime_minutes=160.0,
                duty_cycle_percent=42.0,
            ),
        ],
        mode="cooling",
    )

    assert result["status"] == "weather_correlated"
    assert result["temperature_bin"] == "hot"
    assert result["expected_runtime_range_minutes"] == [160.0, 190.0]
    assert "consistent" in result["explanation"].lower()


def test_weather_context_flags_activity_above_adjusted_range() -> None:
    result = evaluate_weather_context(
        outdoor_temperature=72.0,
        current_runtime_minutes=430.0,
        current_duty_cycle_percent=80.0,
        history=[
            WeatherContextSample(
                temperature=71.0,
                runtime_minutes=120.0,
                duty_cycle_percent=20.0,
            ),
            WeatherContextSample(
                temperature=73.0,
                runtime_minutes=160.0,
                duty_cycle_percent=25.0,
            ),
            WeatherContextSample(
                temperature=72.0,
                runtime_minutes=140.0,
                duty_cycle_percent=22.0,
            ),
        ],
        mode="cooling",
    )

    assert result["status"] == "above_weather_adjusted_range"
    assert result["temperature_bin"] == "mild"
    assert result["expected_runtime_range_minutes"] == [120.0, 160.0]
    assert "above the learned range" in result["explanation"]


def test_weather_context_learns_until_similar_temperature_history_exists() -> None:
    result = evaluate_weather_context(
        outdoor_temperature=81.0,
        current_runtime_minutes=95.0,
        current_duty_cycle_percent=24.0,
        history=[
            WeatherContextSample(
                temperature=65.0,
                runtime_minutes=40.0,
                duty_cycle_percent=10.0,
            )
        ],
        mode="cooling",
    )

    assert result["status"] == "learning"
    assert result["temperature_bin"] == "warm"
    assert "learning" in result["explanation"].lower()


def test_weather_context_reports_missing_temperature_source() -> None:
    result = evaluate_weather_context(
        outdoor_temperature=None,
        current_runtime_minutes=95.0,
        current_duty_cycle_percent=24.0,
        history=[],
        mode="cooling",
    )

    assert result["status"] == "no_temperature_source"
