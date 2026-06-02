from custom_components.circuitsetup_energy_analyzer.baseline import (
    build_baseline,
    score_deviation,
)


def test_build_baseline_uses_robust_statistics() -> None:
    baseline = build_baseline("cycle_duration", [100, 101, 99, 100, 102, 100, 900])

    assert baseline.median == 100.0
    assert baseline.p90 == 102.0
    assert baseline.sample_count == 7
    assert baseline.confidence > 0.4


def test_score_deviation_requires_meaningful_change() -> None:
    baseline = build_baseline(
        "steady_reactive_power", [100, 105, 95, 98, 102, 100, 103, 97]
    )

    assert score_deviation(104.0, baseline) < 1.0
    assert score_deviation(160.0, baseline) > 3.0
