from __future__ import annotations

from statistics import median

from .models import BaselineStats


def _percentile(values: list[float], percentile: float) -> float:
    index = round((len(values) - 1) * percentile)
    return float(values[index])


def build_baseline(feature: str, values: list[float]) -> BaselineStats:
    """Build robust baseline stats for one feature."""
    if not values:
        raise ValueError("baseline requires at least one value")

    sorted_values = sorted(values)
    baseline_median = float(median(sorted_values))
    deviations = [abs(value - baseline_median) for value in sorted_values]

    return BaselineStats(
        feature=feature,
        sample_count=len(sorted_values),
        median=baseline_median,
        mad=float(median(deviations)),
        p10=_percentile(sorted_values, 0.10),
        p90=_percentile(sorted_values, 0.90),
        confidence=min(1.0, len(sorted_values) / 15.0),
    )


def score_deviation(observed: float, baseline: BaselineStats) -> float:
    """Return robust absolute deviation score from baseline."""
    spread = max(baseline.mad * 1.4826, abs(baseline.median) * 0.05, 1.0)
    return abs(observed - baseline.median) / spread
