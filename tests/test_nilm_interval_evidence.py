"""Pure manual NILM interval-evidence behavior."""

from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer.nilm_interval_evidence import (
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
