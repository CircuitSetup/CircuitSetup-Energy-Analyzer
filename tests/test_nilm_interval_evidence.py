"""Pure manual NILM interval-evidence behavior."""

from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer.nilm_interval_evidence import (
    NilmEvidenceThresholds,
    NilmPowerSample,
    aggregate_power_samples,
    context_window_seconds,
    derive_manual_interval_evidence,
    normalize_power_samples,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def sample(seconds: int, watts: float) -> NilmPowerSample:
    return NilmPowerSample(BASE + timedelta(seconds=seconds), watts, "sensor.mains")


def test_boundary_deltas_are_not_replaced_by_larger_interior_transition() -> None:
    """Changing extraction to select the largest in-range step must fail this test."""
    evidence = derive_manual_interval_evidence(
        [
            sample(-60, 200),
            sample(-30, 200),
            sample(0, 700),
            sample(30, 700),
            sample(45, 700),
            sample(60, 1600),
            sample(90, 1600),
            sample(120, 700),
            sample(150, 700),
            sample(180, 200),
            sample(210, 200),
        ],
        start=BASE,
        end=BASE + timedelta(seconds=180),
    )

    assert evidence.start_transition_w == 500
    assert evidence.stop_transition_w == -500
    assert "interior_transition_present" in evidence.quality_flags


def test_stale_split_phase_leg_produces_a_gap_instead_of_a_false_sum() -> None:
    points = aggregate_power_samples(
        [
            NilmPowerSample(BASE, 100, "sensor.leg_a"),
            NilmPowerSample(BASE + timedelta(seconds=30), 150, "sensor.leg_a"),
            NilmPowerSample(BASE, 100, "sensor.leg_b"),
        ],
        source_entity_ids=("sensor.leg_a", "sensor.leg_b"),
    )

    assert points[-1].power_w is None
    assert "stale_source" in points[-1].quality_flags


def test_start_and_stop_eligibility_are_independent() -> None:
    start_only = derive_manual_interval_evidence(
        [sample(-20, 200), sample(0, 700), sample(30, 700)],
        start=BASE,
        end=BASE + timedelta(seconds=120),
    )
    stop_only = derive_manual_interval_evidence(
        [sample(0, 700), sample(100, 700), sample(120, 200), sample(130, 200)],
        start=BASE,
        end=BASE + timedelta(seconds=120),
    )

    assert start_only.start_transition_eligible is True
    assert start_only.stop_transition_eligible is False
    assert stop_only.start_transition_eligible is False
    assert stop_only.stop_transition_eligible is True


def test_baseline_adjusted_energy_uses_net_plateau_not_household_power() -> None:
    evidence = derive_manual_interval_evidence(
        [
            sample(-20, 200),
            sample(0, 700),
            sample(30, 700),
            sample(60, 700),
            sample(90, 700),
            sample(120, 700),
            sample(130, 200),
        ],
        start=BASE,
        end=BASE + timedelta(seconds=120),
    )

    assert evidence.net_plateau_power_w == 500
    assert evidence.measured_energy_kwh == 500 * 120 / 3_600_000
    assert evidence.average_power_w == 500


def test_missing_span_yields_partial_energy_and_reduced_coverage() -> None:
    evidence = derive_manual_interval_evidence(
        [
            sample(-20, 200),
            sample(0, 700),
            sample(30, 700),
            NilmPowerSample(
                BASE + timedelta(seconds=60), None, "sensor.mains", "unavailable"
            ),
            sample(90, 700),
            sample(120, 700),
            sample(130, 200),
        ],
        start=BASE,
        end=BASE + timedelta(seconds=120),
    )

    assert evidence.measured_energy_kwh is None
    assert evidence.partial_energy_kwh == 500 * 60 / 3_600_000
    assert evidence.power_coverage == 0.5
    assert evidence.longest_power_gap_seconds == 60


def test_sparse_valid_endpoints_do_not_count_as_complete_energy_coverage() -> None:
    """Removing the cadence-bound gap check would falsely mark this span complete."""
    evidence = derive_manual_interval_evidence(
        [
            sample(-30, 200),
            sample(0, 700),
            sample(300, 700),
            sample(330, 200),
        ],
        start=BASE,
        end=BASE + timedelta(seconds=300),
    )

    assert evidence.measured_energy_kwh is None
    assert evidence.partial_energy_kwh is None
    assert evidence.power_coverage == 0.0
    assert evidence.longest_power_gap_seconds == 300
    assert "incomplete_power_coverage" in evidence.quality_flags


def test_units_and_duplicate_timestamps_normalize_deterministically() -> None:
    normalized = normalize_power_samples(
        [
            NilmPowerSample(BASE + timedelta(seconds=60), 1, "sensor.mains", unit="kW"),
            NilmPowerSample(BASE, 900, "sensor.mains"),
            NilmPowerSample(BASE + timedelta(seconds=60), 1200, "sensor.mains"),
        ]
    )

    assert [item.timestamp for item in normalized] == [
        BASE,
        BASE + timedelta(seconds=60),
    ]
    assert [item.value_w for item in normalized] == [900, 1200]


def test_short_interval_context_windows_are_bounded_without_overlap() -> None:
    start = BASE
    end = BASE + timedelta(seconds=20)

    assert context_window_seconds(start, end) == 5


def test_transition_direction_must_match_the_selected_boundary() -> None:
    reversed_edges = derive_manual_interval_evidence(
        [
            sample(-20, 700),
            sample(0, 200),
            sample(30, 200),
            sample(100, 200),
            sample(130, 700),
        ],
        start=BASE,
        end=BASE + timedelta(seconds=120),
    )

    assert reversed_edges.start_transition_eligible is False
    assert reversed_edges.stop_transition_eligible is False


def test_selection_after_start_does_not_fabricate_a_start_transition() -> None:
    evidence = derive_manual_interval_evidence(
        [sample(-20, 700), sample(0, 700), sample(30, 700)],
        start=BASE,
        end=BASE + timedelta(seconds=120),
    )

    assert evidence.start_transition_w == 0
    assert evidence.start_transition_eligible is False


def test_selection_before_stop_does_not_fabricate_a_stop_transition() -> None:
    evidence = derive_manual_interval_evidence(
        [sample(0, 700), sample(100, 700), sample(130, 700)],
        start=BASE,
        end=BASE + timedelta(seconds=120),
    )

    assert evidence.stop_transition_w == 0
    assert evidence.stop_transition_eligible is False


def test_synchronous_legs_sum_their_independent_boundary_deltas() -> None:
    evidence = derive_manual_interval_evidence(
        [
            NilmPowerSample(BASE - timedelta(seconds=20), 100, "sensor.a"),
            NilmPowerSample(BASE, 350, "sensor.a"),
            NilmPowerSample(BASE + timedelta(seconds=30), 350, "sensor.a"),
            NilmPowerSample(BASE + timedelta(seconds=100), 350, "sensor.a"),
            NilmPowerSample(BASE + timedelta(seconds=130), 100, "sensor.a"),
            NilmPowerSample(BASE - timedelta(seconds=20), 100, "sensor.b"),
            NilmPowerSample(BASE, 350, "sensor.b"),
            NilmPowerSample(BASE + timedelta(seconds=30), 350, "sensor.b"),
            NilmPowerSample(BASE + timedelta(seconds=100), 350, "sensor.b"),
            NilmPowerSample(BASE + timedelta(seconds=130), 100, "sensor.b"),
        ],
        start=BASE,
        end=BASE + timedelta(seconds=120),
        source_entity_ids=("sensor.a", "sensor.b"),
    )

    assert evidence.start_transition_w == 500
    assert evidence.stop_transition_w == -500


def test_boundary_source_skew_is_accepted_below_limit_and_rejected_above() -> None:
    accepted = derive_manual_interval_evidence(
        [
            NilmPowerSample(BASE - timedelta(seconds=20), 100, "sensor.a"),
            NilmPowerSample(BASE, 350, "sensor.a"),
            NilmPowerSample(BASE - timedelta(seconds=10), 100, "sensor.b"),
            NilmPowerSample(BASE + timedelta(seconds=5), 350, "sensor.b"),
        ],
        start=BASE,
        end=BASE + timedelta(seconds=120),
        source_entity_ids=("sensor.a", "sensor.b"),
    )
    rejected = derive_manual_interval_evidence(
        [
            NilmPowerSample(BASE - timedelta(seconds=20), 100, "sensor.a"),
            NilmPowerSample(BASE, 350, "sensor.a"),
            NilmPowerSample(BASE - timedelta(seconds=20), 100, "sensor.b"),
            NilmPowerSample(BASE + timedelta(seconds=16), 350, "sensor.b"),
        ],
        start=BASE,
        end=BASE + timedelta(seconds=120),
        source_entity_ids=("sensor.a", "sensor.b"),
    )

    assert accepted.start_transition_eligible is True
    assert rejected.start_transition_eligible is False


def test_unavailable_leg_at_boundary_makes_that_transition_ineligible() -> None:
    evidence = derive_manual_interval_evidence(
        [
            NilmPowerSample(BASE - timedelta(seconds=20), 100, "sensor.a"),
            NilmPowerSample(BASE, 350, "sensor.a"),
            NilmPowerSample(BASE - timedelta(seconds=20), 100, "sensor.b"),
            NilmPowerSample(BASE, None, "sensor.b", "unavailable"),
        ],
        start=BASE,
        end=BASE + timedelta(seconds=120),
        source_entity_ids=("sensor.a", "sensor.b"),
    )

    assert evidence.start_transition_eligible is False


def test_drifting_baseline_is_interpolated_from_plateau_and_energy() -> None:
    evidence = derive_manual_interval_evidence(
        [
            sample(-20, 200),
            sample(0, 700),
            sample(30, 725),
            sample(60, 750),
            sample(90, 775),
            sample(120, 800),
            sample(130, 300),
        ],
        start=BASE,
        end=BASE + timedelta(seconds=120),
    )

    assert evidence.net_plateau_power_w == 500
    assert evidence.average_power_w == 500


def test_negative_net_power_blocks_complete_energy() -> None:
    evidence = derive_manual_interval_evidence(
        [
            sample(-20, 200),
            sample(0, 100),
            sample(30, 100),
            sample(60, 100),
            sample(130, 200),
        ],
        start=BASE,
        end=BASE + timedelta(seconds=120),
    )

    assert "material_negative_net_power" in evidence.quality_flags
    assert evidence.energy_complete is False


def test_transition_threshold_is_inclusive_at_the_materiality_boundary() -> None:
    below = derive_manual_interval_evidence(
        [sample(-20, 200), sample(0, 249), sample(30, 249)],
        start=BASE,
        end=BASE + timedelta(seconds=120),
    )
    at = derive_manual_interval_evidence(
        [sample(-20, 200), sample(0, 250), sample(30, 250)],
        start=BASE,
        end=BASE + timedelta(seconds=120),
    )

    assert below.start_transition_eligible is False
    assert at.start_transition_eligible is True


def test_context_size_grows_for_slower_observed_cadence_without_overlap() -> None:
    start = BASE
    end = BASE + timedelta(seconds=200)

    assert context_window_seconds(start, end, observed_cadence_seconds=20) == 40


def test_neither_boundary_can_be_eligible_while_interval_remains_reviewable() -> None:
    evidence = derive_manual_interval_evidence(
        [sample(0, 700), sample(30, 700), sample(60, 700), sample(90, 700)],
        start=BASE,
        end=BASE + timedelta(seconds=120),
    )

    assert evidence.start_transition_eligible is False
    assert evidence.stop_transition_eligible is False
    assert evidence.source_coverage == 1.0


def test_interior_residual_diagnostics_exclude_boundary_steps() -> None:
    evidence = derive_manual_interval_evidence(
        [
            sample(-30, 200),
            sample(0, 700),
            sample(30, 700),
            sample(45, 700),
            sample(60, 1600),
            sample(90, 700),
            sample(150, 700),
            sample(190, 200),
        ],
        start=BASE,
        end=BASE + timedelta(seconds=180),
    )

    assert evidence.interior_transition_count == 2
    assert evidence.largest_interior_transition_w == 900


def test_longest_gap_includes_uncovered_interval_edges() -> None:
    evidence = derive_manual_interval_evidence(
        [sample(-20, 200), sample(30, 700), sample(90, 700), sample(130, 200)],
        start=BASE,
        end=BASE + timedelta(seconds=120),
    )

    assert evidence.longest_power_gap_seconds == 30


def test_transition_crossing_out_of_early_window_does_not_count_as_interior() -> None:
    evidence = derive_manual_interval_evidence(
        [
            sample(-30, 200),
            sample(0, 700),
            sample(30, 700),
            sample(60, 1600),
            sample(90, 1600),
            sample(150, 700),
            sample(190, 200),
        ],
        start=BASE,
        end=BASE + timedelta(seconds=180),
    )

    assert evidence.interior_transition_count == 0


def test_edge_gaps_begin_at_selection_edge_not_first_unavailable_sample() -> None:
    leading = derive_manual_interval_evidence(
        [
            sample(-20, 200),
            NilmPowerSample(
                BASE + timedelta(seconds=10), None, "sensor.mains", "unavailable"
            ),
            sample(30, 700),
            sample(60, 700),
            sample(90, 700),
            sample(120, 700),
            sample(130, 200),
        ],
        start=BASE,
        end=BASE + timedelta(seconds=120),
    )
    trailing = derive_manual_interval_evidence(
        [
            sample(-20, 200),
            sample(0, 700),
            sample(60, 700),
            NilmPowerSample(
                BASE + timedelta(seconds=110), None, "sensor.mains", "unavailable"
            ),
            sample(130, 200),
        ],
        start=BASE,
        end=BASE + timedelta(seconds=120),
    )

    assert leading.longest_power_gap_seconds == 30
    assert trailing.longest_power_gap_seconds == 60


def test_boundary_coverage_threshold_is_inclusive() -> None:
    def evidence(invalid_count: int):
        return derive_manual_interval_evidence(
            [sample(-20, 200), sample(0, 700), sample(5, 700), sample(10, 700)]
            + [
                NilmPowerSample(
                    BASE + timedelta(seconds=15 + index),
                    None,
                    "sensor.mains",
                    "unavailable",
                )
                for index in range(invalid_count)
            ],
            start=BASE,
            end=BASE + timedelta(seconds=120),
        )

    assert evidence(0).start_transition_eligible is True
    assert evidence(1).start_transition_eligible is True
    assert evidence(2).start_transition_eligible is False


def test_boundary_spread_threshold_is_inclusive() -> None:
    def eligible(second_value: int) -> bool:
        return derive_manual_interval_evidence(
            [sample(-20, 200), sample(0, 700), sample(10, second_value)],
            start=BASE, end=BASE + timedelta(seconds=120),
        ).start_transition_eligible

    assert eligible(799) is True
    assert eligible(800) is True
    assert eligible(801) is False


def test_boundary_gap_threshold_is_inclusive() -> None:
    settings = NilmEvidenceThresholds(maximum_context_seconds=120)

    def eligible(pre_seconds: int) -> bool:
        return derive_manual_interval_evidence(
            [sample(pre_seconds, 200), sample(0, 700), sample(30, 700)],
            start=BASE, end=BASE + timedelta(seconds=600), thresholds=settings,
        ).start_transition_eligible

    assert eligible(-59) is True
    assert eligible(-60) is True
    assert eligible(-61) is False
