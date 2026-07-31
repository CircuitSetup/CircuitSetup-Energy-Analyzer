from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from math import isfinite
from statistics import median

from .cycles import CycleAnomalyEvidence
from .models import (
    ApplianceProfile,
    BaselineStats,
    CircuitConfig,
    CircuitMode,
    CircuitSample,
    PowerFlowMode,
)

COLD_STORAGE_SIGNATURE_FEATURE = "cold_storage_cycle_signature_change"
COLD_STORAGE_PF_PEAK_DELTA_FEATURE = "cold_storage_pf_peak_delta"
COLD_STORAGE_MEDIAN_POWER_FEATURE = "cold_storage_median_power_w"
COLD_STORAGE_MEDIAN_CURRENT_FEATURE = "cold_storage_median_current_a"
COLD_STORAGE_BASELINE_FEATURES = (
    COLD_STORAGE_PF_PEAK_DELTA_FEATURE,
    COLD_STORAGE_MEDIAN_POWER_FEATURE,
    COLD_STORAGE_MEDIAN_CURRENT_FEATURE,
)
COLD_STORAGE_WINDOW = timedelta(minutes=30)
COLD_STORAGE_MIN_WINDOW_SAMPLES = 6
COLD_STORAGE_MIN_WINDOW_COVERAGE = timedelta(minutes=20)
COLD_STORAGE_MAX_SAMPLE_GAP = timedelta(minutes=10)
COLD_STORAGE_MIN_BASELINE_WINDOWS = 96
COLD_STORAGE_MIN_BASELINE_CONFIDENCE = 0.6
COLD_STORAGE_MIN_LEARNED_PF_PEAK_DELTA = 0.10
COLD_STORAGE_MAX_PF_PEAK_DELTA_RATIO = 0.40
COLD_STORAGE_MIN_WORKLOAD_RATIO = 1.20
COLD_STORAGE_MIN_WITHIN_WINDOW_RANGE_RATIO = 0.05


@dataclass(frozen=True, slots=True)
class ColdStorageWindowSummary:
    started_at: datetime
    ended_at: datetime
    sample_count: int
    coverage_seconds: float
    max_sample_gap_seconds: float
    pf_peak_delta: float
    median_power_w: float
    median_current_a: float
    power_span_w: float
    current_span_a: float
    valid: bool


@dataclass(slots=True)
class ColdStorageWindowAccumulator:
    started_at: datetime | None = None
    samples: list[tuple[datetime, float, float, float]] = field(default_factory=list)

    def observe(
        self,
        sample: CircuitSample,
    ) -> ColdStorageWindowSummary | None:
        values = _sample_values(sample)
        if values is None:
            return None
        window_start = _window_start(sample.timestamp)
        if self.started_at is None or window_start < self.started_at:
            self.started_at = window_start
            self.samples = [(sample.timestamp, *values)]
            return None
        if window_start == self.started_at:
            self.samples.append((sample.timestamp, *values))
            return None

        previous_start = self.started_at
        previous_samples = self.samples
        self.started_at = window_start
        self.samples = [(sample.timestamp, *values)]
        summary = _summarize_window(previous_start, previous_samples)
        if window_start - previous_start != COLD_STORAGE_WINDOW:
            return replace(summary, valid=False)
        return summary


def _sample_values(
    sample: CircuitSample,
) -> tuple[float, float, float] | None:
    values = (sample.real_power, sample.current, sample.power_factor)
    if any(value is None or not isfinite(float(value)) for value in values):
        return None
    power, current, power_factor = (float(value) for value in values)
    if power < 0.0 or current < 0.0 or not 0.0 <= abs(power_factor) <= 1.0:
        return None
    return power, current, abs(power_factor)


def _window_start(timestamp: datetime) -> datetime:
    return timestamp.replace(
        minute=0 if timestamp.minute < 30 else 30,
        second=0,
        microsecond=0,
    )


def _summarize_window(
    started_at: datetime,
    samples: list[tuple[datetime, float, float, float]],
) -> ColdStorageWindowSummary:
    ordered = sorted(samples, key=lambda item: item[0])
    timestamps = [item[0] for item in ordered]
    powers = [item[1] for item in ordered]
    currents = [item[2] for item in ordered]
    power_factors = [item[3] for item in ordered]
    gaps = [
        (current - previous).total_seconds()
        for previous, current in zip(timestamps, timestamps[1:], strict=False)
    ]
    coverage = (
        (timestamps[-1] - timestamps[0]).total_seconds() if len(timestamps) > 1 else 0.0
    )
    max_gap = max(gaps, default=0.0)
    valid = (
        len(ordered) >= COLD_STORAGE_MIN_WINDOW_SAMPLES
        and coverage >= COLD_STORAGE_MIN_WINDOW_COVERAGE.total_seconds()
        and max_gap <= COLD_STORAGE_MAX_SAMPLE_GAP.total_seconds()
    )
    return ColdStorageWindowSummary(
        started_at=started_at,
        ended_at=started_at + COLD_STORAGE_WINDOW,
        sample_count=len(ordered),
        coverage_seconds=coverage,
        max_sample_gap_seconds=max_gap,
        pf_peak_delta=round(max(power_factors) - float(median(power_factors)), 4),
        median_power_w=round(float(median(powers)), 3),
        median_current_a=round(float(median(currents)), 3),
        power_span_w=round(max(powers) - min(powers), 3),
        current_span_a=round(max(currents) - min(currents), 3),
        valid=valid,
    )


def cold_storage_window_values(
    summary: ColdStorageWindowSummary,
) -> dict[str, float]:
    return {
        COLD_STORAGE_PF_PEAK_DELTA_FEATURE: summary.pf_peak_delta,
        COLD_STORAGE_MEDIAN_POWER_FEATURE: summary.median_power_w,
        COLD_STORAGE_MEDIAN_CURRENT_FEATURE: summary.median_current_a,
    }


def select_cold_storage_signature_evidence(
    config: CircuitConfig,
    summary: ColdStorageWindowSummary,
    baselines: dict[str, BaselineStats],
) -> CycleAnomalyEvidence | None:
    if (
        config.appliance_profile
        not in {ApplianceProfile.REFRIGERATOR, ApplianceProfile.FREEZER}
        or config.mode is not CircuitMode.SINGLE_PHASE
        or config.power_flow is not PowerFlowMode.LOAD
        or not summary.valid
    ):
        return None
    pf_baseline = baselines.get(COLD_STORAGE_PF_PEAK_DELTA_FEATURE)
    power_baseline = baselines.get(COLD_STORAGE_MEDIAN_POWER_FEATURE)
    current_baseline = baselines.get(COLD_STORAGE_MEDIAN_CURRENT_FEATURE)
    required = (pf_baseline, power_baseline, current_baseline)
    if any(
        baseline is None
        or baseline.sample_count < COLD_STORAGE_MIN_BASELINE_WINDOWS
        or baseline.confidence < COLD_STORAGE_MIN_BASELINE_CONFIDENCE
        for baseline in required
    ):
        return None
    assert pf_baseline is not None
    assert power_baseline is not None
    assert current_baseline is not None
    if pf_baseline.median < COLD_STORAGE_MIN_LEARNED_PF_PEAK_DELTA:
        return None

    pf_ratio = summary.pf_peak_delta / pf_baseline.median
    power_ratio = _ratio(summary.median_power_w, power_baseline.median)
    current_ratio = _ratio(summary.median_current_a, current_baseline.median)
    power_range_ratio = _ratio(summary.power_span_w, summary.median_power_w)
    current_range_ratio = _ratio(summary.current_span_a, summary.median_current_a)
    if (
        pf_ratio > COLD_STORAGE_MAX_PF_PEAK_DELTA_RATIO
        or power_ratio < COLD_STORAGE_MIN_WORKLOAD_RATIO
        or current_ratio < COLD_STORAGE_MIN_WORKLOAD_RATIO
        or power_range_ratio < COLD_STORAGE_MIN_WITHIN_WINDOW_RANGE_RATIO
        or current_range_ratio < COLD_STORAGE_MIN_WITHIN_WINDOW_RANGE_RATIO
    ):
        return None

    confidence = min(baseline.confidence for baseline in required)
    baseline_windows = min(baseline.sample_count for baseline in required)
    score = min(
        4.0,
        max((1.0 - pf_ratio) * 3.0, power_ratio, current_ratio),
    )
    return CycleAnomalyEvidence(
        feature=COLD_STORAGE_SIGNATURE_FEATURE,
        message=(
            f"Possible issue: {config.name}'s learned compressor pattern has "
            "disappeared while power and current remain elevated. Check that "
            "doors are fully closed, seals and vents are clear, and temperatures "
            "are normal. This is an inspection prompt, not a door or component "
            "diagnosis."
        ),
        observed_value=summary.pf_peak_delta,
        baseline_value=pf_baseline.median,
        score=score,
        baseline_confidence=confidence,
        features={
            "signature_ready": True,
            "signature_baseline_windows": float(baseline_windows),
            "signature_baseline_confidence": confidence,
            "window_started_at": summary.started_at.isoformat(),
            "window_minutes": COLD_STORAGE_WINDOW.total_seconds() / 60.0,
            "pf_peak_delta": summary.pf_peak_delta,
            "baseline_pf_peak_delta": pf_baseline.median,
            "median_power_w": summary.median_power_w,
            "baseline_median_power_w": power_baseline.median,
            "power_ratio": power_ratio,
            "median_current_a": summary.median_current_a,
            "baseline_median_current_a": current_baseline.median,
            "current_ratio": current_ratio,
            "power_span_w": summary.power_span_w,
            "current_span_a": summary.current_span_a,
            "score": score,
        },
    )


def _ratio(observed: float, baseline: float) -> float:
    return observed / baseline if baseline > 0.0 else 0.0
