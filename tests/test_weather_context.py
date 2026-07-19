from __future__ import annotations

from datetime import UTC, datetime

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
                timestamp=datetime(2026, 6, 1, tzinfo=UTC),
                temperature=90.0,
                runtime_minutes=170.0,
                duty_cycle_percent=44.0,
            ),
            WeatherContextSample(
                timestamp=datetime(2026, 6, 2, tzinfo=UTC),
                temperature=92.0,
                runtime_minutes=190.0,
                duty_cycle_percent=48.0,
            ),
            WeatherContextSample(
                timestamp=datetime(2026, 6, 3, tzinfo=UTC),
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
                timestamp=datetime(2026, 6, 1, tzinfo=UTC),
                temperature=71.0,
                runtime_minutes=120.0,
                duty_cycle_percent=20.0,
            ),
            WeatherContextSample(
                timestamp=datetime(2026, 6, 2, tzinfo=UTC),
                temperature=73.0,
                runtime_minutes=160.0,
                duty_cycle_percent=25.0,
            ),
            WeatherContextSample(
                timestamp=datetime(2026, 6, 3, tzinfo=UTC),
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




def test_weather_context_requires_distinct_local_dates_for_baseline() -> None:
    result = evaluate_weather_context(
        outdoor_temperature=94.0,
        current_runtime_minutes=101.0,
        current_duty_cycle_percent=50.0,
        history=[
            WeatherContextSample(
                timestamp=timestamp,
                temperature=temperature,
                runtime_minutes=runtime,
                duty_cycle_percent=duty,
            )
            for timestamp, temperature, runtime, duty in (
                (
                    datetime(2026, 6, 1, 4, 30, tzinfo=UTC),
                    93.0,
                    95.0,
                    46.0,
                ),
                (
                    datetime(2026, 6, 2, 3, 30, tzinfo=UTC),
                    95.0,
                    100.0,
                    50.0,
                ),
                (
                    datetime(2026, 6, 3, 3, 30, tzinfo=UTC),
                    92.0,
                    110.0,
                    54.0,
                ),
            )
        ],
        mode="cooling",
        observed_at=datetime(2026, 6, 17, 15, tzinfo=UTC),
        time_zone="America/New_York",
    )

    assert result["status"] == "learning"
    assert result["baseline_fallback_level"] == "not_enough_data"
    assert "baseline_confidence" not in result


def test_weather_context_reports_missing_temperature_source() -> None:
    result = evaluate_weather_context(
        outdoor_temperature=None,
        current_runtime_minutes=95.0,
        current_duty_cycle_percent=24.0,
        history=[],
        mode="cooling",
    )

    assert result["status"] == "no_temperature_source"


def test_weather_context_uses_exact_temperature_season_baseline() -> None:
    result = evaluate_weather_context(
        outdoor_temperature=94.0,
        current_runtime_minutes=101.0,
        current_duty_cycle_percent=50.0,
        history=[
            WeatherContextSample(
                timestamp=datetime(2026, 6, day, tzinfo=UTC),
                temperature=temperature,
                runtime_minutes=runtime,
                duty_cycle_percent=duty,
            )
            for day, temperature, runtime, duty in (
                (1, 93.0, 95.0, 46.0),
                (2, 95.0, 100.0, 50.0),
                (3, 92.0, 110.0, 54.0),
                (4, 80.0, 60.0, 30.0),
            )
        ],
        mode="cooling",
        observed_at=datetime(2026, 6, 17, 15, tzinfo=UTC),
    )

    assert result["status"] == "weather_correlated"
    assert result["baseline_context"] == "cooling, very_hot, summer"
    assert result["baseline_fallback_level"] == "exact_context"
    assert result["baseline_sample_count"] == 3
    assert result["baseline_confidence"] == 1.0
    assert result["expected_runtime_median_minutes"] == 100.0
    assert result["expected_runtime_p90_minutes"] == 110.0
    assert result["contextual_status"] == "weather_correlated"


def test_weather_context_season_uses_ha_local_timezone() -> None:
    result = evaluate_weather_context(
        outdoor_temperature=94.0,
        current_runtime_minutes=101.0,
        current_duty_cycle_percent=50.0,
        history=[
            WeatherContextSample(
                timestamp=timestamp,
                temperature=temperature,
                runtime_minutes=runtime,
                duty_cycle_percent=duty,
            )
            for timestamp, temperature, runtime, duty in (
                (
                    datetime(2026, 5, 29, 18, tzinfo=UTC),
                    93.0,
                    95.0,
                    46.0,
                ),
                (
                    datetime(2026, 5, 30, 18, tzinfo=UTC),
                    95.0,
                    100.0,
                    50.0,
                ),
                (
                    datetime(2026, 6, 1, 1, tzinfo=UTC),
                    92.0,
                    110.0,
                    54.0,
                ),
            )
        ],
        mode="cooling",
        observed_at=datetime(2026, 6, 1, 3, 30, tzinfo=UTC),
        time_zone="America/New_York",
    )

    assert result["baseline_context"] == "cooling, very_hot, spring"
    assert result["baseline_fallback_level"] == "exact_context"
    assert result["baseline_sample_count"] == 3


def test_weather_context_falls_back_to_temperature_context_without_season() -> None:
    result = evaluate_weather_context(
        outdoor_temperature=94.0,
        current_runtime_minutes=101.0,
        current_duty_cycle_percent=50.0,
        history=[
            WeatherContextSample(
                timestamp=datetime(2026, month, day, tzinfo=UTC),
                temperature=temperature,
                runtime_minutes=runtime,
                duty_cycle_percent=duty,
            )
            for month, day, temperature, runtime, duty in (
                (5, 28, 93.0, 95.0, 46.0),
                (5, 29, 95.0, 100.0, 50.0),
                (9, 3, 92.0, 110.0, 54.0),
            )
        ],
        mode="cooling",
        observed_at=datetime(2026, 6, 17, 15, tzinfo=UTC),
    )

    assert result["status"] == "weather_correlated"
    assert result["baseline_context"] == "cooling, very_hot"
    assert result["baseline_fallback_level"] == "temperature_context"
    assert result["baseline_sample_count"] == 3


def test_weather_context_mild_day_can_be_above_contextual_range() -> None:
    result = evaluate_weather_context(
        outdoor_temperature=62.0,
        current_runtime_minutes=220.0,
        current_duty_cycle_percent=75.0,
        history=[
            WeatherContextSample(
                timestamp=datetime(2026, 6, day, tzinfo=UTC),
                temperature=temperature,
                runtime_minutes=runtime,
                duty_cycle_percent=duty,
            )
            for day, temperature, runtime, duty in (
                (1, 61.0, 40.0, 12.0),
                (2, 63.0, 45.0, 14.0),
                (3, 62.0, 50.0, 16.0),
            )
        ],
        mode="cooling",
        observed_at=datetime(2026, 6, 17, 15, tzinfo=UTC),
    )

    assert result["status"] == "above_weather_adjusted_range"
    assert result["baseline_context"] == "cooling, mild, summer"
    assert result["baseline_fallback_level"] == "exact_context"
    assert result["observed_runtime_minutes"] == 220.0
    assert result["expected_runtime_p90_minutes"] == 50.0
