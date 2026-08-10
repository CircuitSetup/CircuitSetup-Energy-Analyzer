"""Reference-state interval extraction behavior."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.circuitsetup_energy_analyzer.nilm_interval_evidence import (
    NilmReferenceExtractionSettings,
    ReferenceActivityState,
    extract_reference_intervals,
    normalize_reference_samples,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)
SETTINGS = NilmReferenceExtractionSettings(
    on_threshold=10,
    off_threshold=5,
    on_dwell_seconds=20,
    off_dwell_seconds=20,
    minimum_interval_seconds=10,
    merge_gap_seconds=15,
    maximum_unknown_gap_seconds=15,
    maximum_power_gap_seconds=None,
)


def rows(*values: tuple[int, object]):
    return [(BASE + timedelta(seconds=second), value) for second, value in values]


def test_normalization_is_deterministic_and_malformed_values_are_unknown() -> None:
    samples = normalize_reference_samples(
        rows((20, "on"), (0, "bad"), (20, "off"), (10, float("nan")))
    )
    assert [(sample.timestamp, sample.state) for sample in samples] == [
        (BASE, ReferenceActivityState.UNKNOWN),
        (BASE + timedelta(seconds=10), ReferenceActivityState.UNKNOWN),
        (BASE + timedelta(seconds=20), ReferenceActivityState.INACTIVE),
    ]


def test_numeric_hysteresis_and_elapsed_dwell_backdate_start_and_stop() -> None:
    result = extract_reference_intervals(
        rows((0, 0), (10, 11), (20, 8), (30, 11), (50, 11), (60, 8), (70, 4), (90, 4)),
        start=BASE,
        end=BASE + timedelta(seconds=100),
        settings=SETTINGS,
    )
    assert len(result.intervals) == 1
    interval = result.intervals[0]
    assert interval.start == BASE + timedelta(seconds=26.666667)
    assert interval.end == BASE + timedelta(seconds=67.5)


def test_numeric_crossings_interpolate_and_report_bounded_uncertainty() -> None:
    settings = replace(SETTINGS, on_dwell_seconds=0, off_dwell_seconds=0)
    result = extract_reference_intervals(
        rows((0, 0), (10, 20), (15, 20), (25, 0), (35, 0)),
        start=BASE,
        end=BASE + timedelta(seconds=40),
        settings=settings,
    )
    interval = result.intervals[0]
    assert interval.start == BASE + timedelta(seconds=5)
    assert interval.end == BASE + timedelta(seconds=22.5)
    assert interval.start_boundary_uncertainty_seconds == 5
    assert interval.end_boundary_uncertainty_seconds == 5


def test_unknown_gap_bridges_only_when_bounded_and_reduces_confidence() -> None:
    bridged = extract_reference_intervals(
        rows(
            (0, "on"), (20, "on"), (30, "unknown"), (40, "on"), (60, "off"), (80, "off")
        ),
        start=BASE,
        end=BASE + timedelta(seconds=90),
        settings=replace(SETTINGS, merge_gap_seconds=30),
    )
    split = extract_reference_intervals(
        rows(
            (0, "on"),
            (20, "on"),
            (30, "unknown"),
            (60, "on"),
            (80, "on"),
            (90, "off"),
            (110, "off"),
        ),
        start=BASE,
        end=BASE + timedelta(seconds=120),
        settings=SETTINGS,
    )
    assert len(bridged.intervals) == 1
    assert bridged.intervals[0].unknown_duration_seconds == 10
    assert bridged.intervals[0].evidence_confidence < 1
    assert len(split.intervals) == 2


def test_request_edges_are_censored_and_short_inactive_gap_merges() -> None:
    result = extract_reference_intervals(
        rows(
            (0, "on"),
            (20, "on"),
            (30, "off"),
            (50, "off"),
            (60, "on"),
            (80, "on"),
        ),
        start=BASE,
        end=BASE + timedelta(seconds=90),
        settings=replace(SETTINGS, merge_gap_seconds=30),
    )
    assert len(result.intervals) == 1
    interval = result.intervals[0]
    assert interval.left_censored is True
    assert interval.right_censored is True
    assert interval.merged_gap_count == 1


def test_long_inactive_and_short_duration_are_not_silently_kept() -> None:
    result = extract_reference_intervals(
        rows((0, "on"), (20, "on"), (30, "off"), (60, "off"), (80, "on"), (100, "on")),
        start=BASE,
        end=BASE + timedelta(seconds=110),
        settings=SETTINGS,
    )
    assert len(result.intervals) == 2
    assert result.diagnostics.discarded_minimum_duration == 0


def test_binary_dwell_unknown_start_and_minimum_duration_diagnostics() -> None:
    binary = extract_reference_intervals(
        rows(
            (0, "off"),
            (10, "on"),
            (20, "off"),
            (30, "on"),
            (50, "on"),
            (60, "off"),
            (80, "off"),
        ),
        start=BASE,
        end=BASE + timedelta(seconds=90),
        settings=SETTINGS,
    )
    unknown = extract_reference_intervals(
        rows((0, "unknown"), (20, "unknown")),
        start=BASE,
        end=BASE + timedelta(seconds=30),
        settings=SETTINGS,
    )
    discarded = extract_reference_intervals(
        rows((0, "on"), (20, "on"), (30, "off"), (50, "off")),
        start=BASE,
        end=BASE + timedelta(seconds=60),
        settings=replace(SETTINGS, minimum_interval_seconds=40),
    )
    assert [(item.start, item.end) for item in binary.intervals] == [
        (BASE + timedelta(seconds=30), BASE + timedelta(seconds=60))
    ]
    assert unknown.intervals == ()
    assert discarded.intervals == ()
    assert discarded.diagnostics.discarded_minimum_duration == 1


@pytest.mark.parametrize(
    "changes",
    (
        {"on_threshold": -1, "off_threshold": -1},
        {"off_threshold": -1},
        {"on_dwell_seconds": 86_401},
        {"maximum_unknown_gap_seconds": 86_401},
    ),
)
def test_settings_reject_negative_thresholds_and_unbounded_durations(changes) -> None:
    with pytest.raises(ValueError):
        replace(SETTINGS, **changes)


def test_diagnostics_report_candidate_imported_and_low_coverage_counts() -> None:
    result = extract_reference_intervals(
        rows(
            (0, "on"),
            (20, "on"),
            (30, "unknown"),
            (40, "on"),
            (60, "off"),
            (80, "off"),
        ),
        start=BASE,
        end=BASE + timedelta(seconds=90),
        settings=SETTINGS,
    )
    assert result.diagnostics.candidate_interval_count == 1
    assert result.diagnostics.imported_interval_count == 1
    assert result.diagnostics.discarded_short_interval_count == 0
    assert result.diagnostics.bridged_unknown_gap_count == 1
    assert result.diagnostics.merged_short_gap_count == 0
    assert result.diagnostics.low_coverage_interval_count == 1


def test_binary_state_persists_between_rows_and_prestart_is_censored() -> None:
    persisted = extract_reference_intervals(
        rows((10, "on"), (40, "off")),
        start=BASE,
        end=BASE + timedelta(seconds=50),
        settings=SETTINGS,
    )
    prestart = extract_reference_intervals(
        rows((-10, "on"), (30, "on")),
        start=BASE,
        end=BASE + timedelta(seconds=40),
        settings=SETTINGS,
    )
    assert [(item.start, item.end) for item in persisted.intervals] == [
        (BASE + timedelta(seconds=10), BASE + timedelta(seconds=50))
    ]
    assert prestart.intervals[0].left_censored is True


def test_unknown_resets_pending_dwell_and_unknown_splits_never_merge() -> None:
    pending = extract_reference_intervals(
        rows((0, "off"), (10, "on"), (20, "unknown"), (30, "on"), (40, "on")),
        start=BASE,
        end=BASE + timedelta(seconds=49),
        settings=SETTINGS,
    )
    split = extract_reference_intervals(
        rows(
            (0, "on"), (20, "on"), (30, "unknown"), (60, "on"), (80, "on"), (100, "off")
        ),
        start=BASE,
        end=BASE + timedelta(seconds=110),
        settings=replace(SETTINGS, merge_gap_seconds=100),
    )
    assert pending.intervals == ()
    assert len(split.intervals) == 2


def test_request_end_confirms_persisted_binary_on_and_off_candidates() -> None:
    on_pending = extract_reference_intervals(
        rows((0, "off"), (10, "on")),
        start=BASE,
        end=BASE + timedelta(seconds=50),
        settings=SETTINGS,
    )
    off_pending = extract_reference_intervals(
        rows((0, "on"), (20, "on"), (30, "off")),
        start=BASE,
        end=BASE + timedelta(seconds=60),
        settings=SETTINGS,
    )
    assert [
        (item.start, item.end, item.right_censored) for item in on_pending.intervals
    ] == [(BASE + timedelta(seconds=10), BASE + timedelta(seconds=50), True)]
    assert [
        (item.start, item.end, item.right_censored) for item in off_pending.intervals
    ] == [(BASE, BASE + timedelta(seconds=30), False)]


def test_on_confirmation_hands_current_off_to_its_own_dwell() -> None:
    short = extract_reference_intervals(
        rows((10, "on"), (40, "off")),
        start=BASE,
        end=BASE + timedelta(seconds=50),
        settings=SETTINGS,
    )
    held = extract_reference_intervals(
        rows((10, "on"), (40, "off")),
        start=BASE,
        end=BASE + timedelta(seconds=60),
        settings=SETTINGS,
    )
    assert short.intervals[0].right_censored is True
    assert held.intervals[0].end == BASE + timedelta(seconds=40)
    assert held.intervals[0].right_censored is False


def test_resume_after_long_unknown_is_left_uncertain() -> None:
    result = extract_reference_intervals(
        rows((0, "on"), (20, "on"), (30, "unknown"), (60, "on"), (80, "on")),
        start=BASE,
        end=BASE + timedelta(seconds=100),
        settings=SETTINGS,
    )
    resumed = result.intervals[-1]
    assert resumed.left_censored is True
    assert "left_uncertain_after_unknown_gap" in resumed.quality_flags
    assert resumed.evidence_confidence < 0.85


def test_horizon_confirmed_resume_after_long_unknown_is_left_uncertain() -> None:
    result = extract_reference_intervals(
        rows((0, "on"), (20, "on"), (30, "unknown"), (60, "on")),
        start=BASE,
        end=BASE + timedelta(seconds=80),
        settings=SETTINGS,
    )
    resumed = result.intervals[-1]
    assert resumed.left_censored is True
    assert "left_uncertain_after_unknown_gap" in resumed.quality_flags
    assert resumed.evidence_confidence < 0.85
