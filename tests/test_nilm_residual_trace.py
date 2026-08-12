"""Production-path regression coverage for residual-trace freshness evidence."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.managers.state_reducer import (
    StateReducer,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    SensorRole,
)
from custom_components.circuitsetup_energy_analyzer.nilm import (
    NilmEdge,
    NilmResidualPowerPoint,
    NilmResidualTraceMetadata,
    _nilm_normalized_power_trace,
    pair_nilm_sessions_for_signatures,
)
from custom_components.circuitsetup_energy_analyzer.normalize import (
    NormalizedCircuitSample,
)
from custom_components.circuitsetup_energy_analyzer.processors.base import (
    ProcessingContext,
)
from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
    NilmSampleProcessor,
)
from custom_components.circuitsetup_energy_analyzer.state import (
    AnalyzerState,
    LatestCircuitPowerObservation,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData
from tests.helpers.calibration import (
    load_calibration_scenarios,
    replay_fixture_processors,
)

BASE_TIME = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def _mains_config() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )


def _mixed_config() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="mixed",
        name="Mixed",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
    )


def _processor(**kwargs: object) -> NilmSampleProcessor:
    return NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _circuit_id: 100.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _circuit_id, _events: (),
        observe_topology=lambda _config, _match, _context: [],
        **kwargs,
    )


def _context(state: AnalyzerState) -> ProcessingContext:
    return ProcessingContext(
        now=BASE_TIME,
        hass=SimpleNamespace(data={}),
        state=state,
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset({"mains", "direct_a", "direct_b"}),
        sensitivity="balanced",
        time_zone="UTC",
    )


def _sample(
    timestamp: datetime,
    power_w: float,
    *,
    source_updated_at: datetime | None = None,
) -> NormalizedCircuitSample:
    return NormalizedCircuitSample(
        timestamp=timestamp,
        circuit_id="mains",
        real_power=power_w,
        source_updated_at_by_role=(
            (SensorRole.REAL_POWER, source_updated_at or timestamp),
        ),
    )


def _point(
    timestamp: datetime,
    power_w: float,
    *,
    complete: bool = True,
    coverage: float = 1.0,
) -> NilmResidualPowerPoint:
    return NilmResidualPowerPoint(
        timestamp=timestamp,
        mains_power_w=power_w,
        explained_known_power_w=0.0,
        residual_power_w=power_w,
        contributing_known_circuit_ids=(),
        stale_known_circuit_ids=(),
        unavailable_known_circuit_ids=(),
        missing_known_circuit_ids=(),
        expected_known_circuit_count=0,
        fresh_known_circuit_count=0,
        known_source_coverage=coverage,
        subtraction_complete=complete,
        quality_flags=() if complete else ("partial_known_source_coverage",),
    )


def test_state_reducer_tracks_structured_latest_power_observation() -> None:
    state = AnalyzerState()
    reducer = StateReducer()
    config = SimpleNamespace(circuit_id="direct_a")

    reducer.refresh_latest_real_power_state(
        state,
        config,
        NormalizedCircuitSample(
            timestamp=BASE_TIME,
            circuit_id="direct_a",
            real_power=1_000.0,
            source_updated_at_by_role=((SensorRole.REAL_POWER, BASE_TIME),),
        ),
    )
    reducer.refresh_latest_real_power_state(
        state,
        config,
        NormalizedCircuitSample(
            timestamp=BASE_TIME + timedelta(seconds=30),
            circuit_id="direct_a",
            real_power=1_000.0,
            source_updated_at_by_role=(
                (SensorRole.REAL_POWER, BASE_TIME + timedelta(seconds=30)),
            ),
        ),
    )

    observation = state.latest_real_power_observation_by_circuit["direct_a"]
    assert state.latest_real_power_w_by_circuit == {"direct_a": 1_000.0}
    assert observation.available is True
    assert observation.power_w == 1_000.0
    assert observation.source_updated_at == BASE_TIME + timedelta(seconds=30)
    assert observation.expected_cadence_s == pytest.approx(30.0)

    reducer.refresh_latest_real_power_state(
        state,
        config,
        NormalizedCircuitSample(
            timestamp=BASE_TIME + timedelta(seconds=31),
            circuit_id="direct_a",
            real_power=None,
            quality_issues=("sensor.direct unavailable",),
        ),
    )

    unavailable = state.latest_real_power_observation_by_circuit["direct_a"]
    assert state.latest_real_power_w_by_circuit == {}
    assert unavailable.available is False
    assert unavailable.power_w is None
    assert "sensor.direct unavailable" in unavailable.quality_flags


def test_nilm_processor_never_subtracts_unavailable_legacy_power() -> None:
    state = AnalyzerState(
        latest_real_power_w_by_circuit={"direct_a": 1_000.0},
        latest_real_power_observation_by_circuit={
            "direct_a": LatestCircuitPowerObservation(
                power_w=None,
                observed_at=BASE_TIME,
                source_updated_at=None,
                available=False,
                expected_cadence_s=30.0,
                quality_flags=("sensor.direct unavailable",),
            )
        },
    )
    processor = _processor()

    processor.process(
        _sample(BASE_TIME, 2_000.0),
        _mains_config(),
        _context(state),
        events=(),
    )

    point = processor._residual_power_trace_by_circuit["mains"][-1]  # noqa: SLF001
    assert point.residual_power_w == 2_000.0
    assert point.explained_known_power_w == 0.0
    assert point.unavailable_known_circuit_ids == ("direct_a",)
    assert point.missing_known_circuit_ids == ("direct_b",)
    assert point.subtraction_complete is False


def test_monotonic_residual_trace_append_never_uses_slow_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Appending newer points must not reconstruct the retained trace."""
    processor = _processor()

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("monotonic trace append rebuilt the full trace")

    monkeypatch.setattr(processor, "_rebuild_residual_trace", fail_if_called)

    processor._append_residual_trace_point("mains", _point(BASE_TIME, 100.0))
    processor._append_residual_trace_point(
        "mains", _point(BASE_TIME + timedelta(seconds=1), 101.0)
    )


def test_residual_trace_is_collected_only_for_mains_nilm() -> None:
    processor = _processor()

    processor.process(
        _sample(BASE_TIME, 500.0),
        _mixed_config(),
        _context(AnalyzerState()),
        events=(),
    )

    assert "mixed" not in processor._residual_power_trace_by_circuit  # noqa: SLF001


def test_residual_trace_uses_each_source_cadence_and_rejects_future_readings() -> None:
    state = AnalyzerState(
        latest_real_power_observation_by_circuit={
            "direct_a": LatestCircuitPowerObservation(
                power_w=400.0,
                observed_at=BASE_TIME,
                source_updated_at=BASE_TIME,
                available=True,
                expected_cadence_s=30.0,
            ),
            "direct_b": LatestCircuitPowerObservation(
                power_w=250.0,
                observed_at=BASE_TIME,
                source_updated_at=BASE_TIME,
                available=True,
                expected_cadence_s=5.0,
            ),
        }
    )
    context = _context(state)
    sample = _sample(BASE_TIME + timedelta(seconds=11), 2_000.0)
    processor = _processor()

    processor.process(sample, _mains_config(), context, events=())
    point = processor._residual_power_trace_by_circuit["mains"][-1]  # noqa: SLF001

    assert point.explained_known_power_w == 400.0
    assert point.contributing_known_circuit_ids == ("direct_a",)
    assert point.stale_known_circuit_ids == ("direct_b",)

    state.latest_real_power_observation_by_circuit["direct_b"] = (
        LatestCircuitPowerObservation(
            power_w=250.0,
            observed_at=BASE_TIME + timedelta(seconds=12),
            source_updated_at=BASE_TIME + timedelta(seconds=12),
            available=True,
            expected_cadence_s=5.0,
        )
    )
    future_processor = _processor()
    future_processor.process(sample, _mains_config(), context, events=())
    future_point = future_processor._residual_power_trace_by_circuit["mains"][-1]  # noqa: SLF001

    assert future_point.explained_known_power_w == 400.0
    assert future_point.stale_known_circuit_ids == ("direct_b",)
    assert "future_known_observation" in future_point.quality_flags


def test_residual_trace_never_uses_direct_power_newer_than_mains_source() -> None:
    state = AnalyzerState(
        latest_real_power_observation_by_circuit={
            "direct_a": LatestCircuitPowerObservation(
                power_w=400.0,
                observed_at=BASE_TIME + timedelta(seconds=10),
                source_updated_at=BASE_TIME + timedelta(seconds=10),
                available=True,
                expected_cadence_s=10.0,
            ),
        }
    )
    processor = _processor()

    processor.process(
        _sample(
            BASE_TIME + timedelta(seconds=10),
            2_000.0,
            source_updated_at=BASE_TIME,
        ),
        _mains_config(),
        _context(state),
        events=(),
    )

    point = processor._residual_power_trace_by_circuit["mains"][-1]  # noqa: SLF001
    assert point.timestamp == BASE_TIME
    assert point.explained_known_power_w == 0.0
    assert point.stale_known_circuit_ids == ("direct_a",)
    assert "future_known_observation" in point.quality_flags


def test_processor_trace_retention_is_time_first_then_cap_with_disclosure() -> None:
    state = AnalyzerState()
    processor = _processor(
        residual_power_trace_horizon=timedelta(hours=1),
        residual_power_trace_max_items=2,
    )
    context = _context(state)
    config = _mains_config()

    for offset in (0, 10, 20):
        processor.process(
            _sample(BASE_TIME + timedelta(seconds=offset), 100.0 + offset),
            config,
            context,
            events=(),
        )

    trace = processor._residual_power_trace_by_circuit["mains"]  # noqa: SLF001
    metadata = processor._residual_trace_metadata_by_circuit["mains"]  # noqa: SLF001
    assert [point.timestamp for point in trace] == [
        BASE_TIME + timedelta(seconds=10),
        BASE_TIME + timedelta(seconds=20),
    ]
    assert metadata.point_cap_truncated is True
    assert metadata.trace_point_cap_truncation_count == 1
    assert metadata.oldest_point_at == BASE_TIME + timedelta(seconds=10)

    processor.process(
        _sample(BASE_TIME + timedelta(hours=2), 100.0),
        config,
        context,
        events=(),
    )
    trace = processor._residual_power_trace_by_circuit["mains"]  # noqa: SLF001
    metadata = processor._residual_trace_metadata_by_circuit["mains"]  # noqa: SLF001
    assert [point.timestamp for point in trace] == [BASE_TIME + timedelta(hours=2)]
    assert metadata.oldest_point_at == BASE_TIME + timedelta(hours=2)
    assert metadata.point_cap_truncated is False
    assert metadata.trace_point_cap_truncation_count == 1


def test_session_trace_quality_exposes_partial_and_measured_energy_sources() -> None:
    edges = [
        NilmEdge(BASE_TIME, 100.0, direction="on"),
        NilmEdge(BASE_TIME + timedelta(minutes=10), -100.0, direction="off"),
    ]
    complete_trace = [
        _point(BASE_TIME - timedelta(seconds=30), 0.0),
        _point(BASE_TIME, 0.0),
        _point(BASE_TIME + timedelta(minutes=1), 120.0),
        _point(BASE_TIME + timedelta(minutes=5), 120.0),
        _point(BASE_TIME + timedelta(minutes=9), 120.0),
        _point(BASE_TIME + timedelta(minutes=10), 0.0),
    ]
    complete = pair_nilm_sessions_for_signatures(
        edges,
        mains_circuit_id="mains",
        signature_specs=[{"signature_fingerprint": "pump", "typical_watts": 100.0}],
        power_trace=complete_trace,
    )[0]

    assert complete.energy_source == "residual_trace_measured"
    assert complete.measured_energy_kwh == pytest.approx(0.018)
    assert complete.partial_energy_kwh is None
    assert complete.longest_trace_gap_seconds == pytest.approx(240.0)
    assert complete.known_source_coverage_min == 1.0

    partial = pair_nilm_sessions_for_signatures(
        edges,
        mains_circuit_id="mains",
        signature_specs=[{"signature_fingerprint": "pump", "typical_watts": 100.0}],
        power_trace=complete_trace[1:],
        trace_metadata=NilmResidualTraceMetadata(
            configured_horizon_seconds=43_560.0,
            point_cap=4_096,
            point_cap_truncated=True,
            oldest_point_at=BASE_TIME,
            newest_point_at=BASE_TIME + timedelta(minutes=10),
            trace_point_cap_truncation_count=1,
        ),
    )[0]

    assert partial.energy_source == "residual_trace_partial"
    assert partial.measured_energy_kwh is None
    assert partial.partial_energy_kwh == pytest.approx(0.018)
    assert partial.pre_context_coverage is False
    assert partial.trace_point_cap_truncated is True
    assert partial.estimated_energy_kwh == pytest.approx(0.017)


def test_session_trace_recovers_after_cap_truncation_when_full_window_remains() -> None:
    """A historic cap eviction must not taint a newer fully covered session."""
    edges = [
        NilmEdge(BASE_TIME, 100.0, direction="on"),
        NilmEdge(BASE_TIME + timedelta(minutes=10), -100.0, direction="off"),
    ]
    trace = [
        _point(BASE_TIME - timedelta(seconds=30), 0.0),
        _point(BASE_TIME, 0.0),
        _point(BASE_TIME + timedelta(minutes=1), 120.0),
        _point(BASE_TIME + timedelta(minutes=5), 120.0),
        _point(BASE_TIME + timedelta(minutes=9), 120.0),
        _point(BASE_TIME + timedelta(minutes=10), 0.0),
    ]

    session = pair_nilm_sessions_for_signatures(
        edges,
        mains_circuit_id="mains",
        signature_specs=[{"signature_fingerprint": "pump", "typical_watts": 100.0}],
        power_trace=trace,
        trace_metadata=NilmResidualTraceMetadata(
            configured_horizon_seconds=43_560.0,
            point_cap=4_096,
            point_cap_truncated=True,
            oldest_point_at=BASE_TIME - timedelta(seconds=30),
            newest_point_at=BASE_TIME + timedelta(minutes=10),
            trace_point_cap_truncation_count=9,
        ),
    )[0]

    assert session.energy_source == "residual_trace_measured"
    assert session.measured_energy_kwh == pytest.approx(0.018)
    assert session.trace_point_cap_truncated is False
    assert session.trace_point_cap_truncation_count == 0


def test_session_trace_provenance_excludes_later_unrelated_points() -> None:
    """Historical session payloads stay stable as the runtime trace advances."""
    edges = [
        NilmEdge(BASE_TIME, 100.0, direction="on"),
        NilmEdge(BASE_TIME + timedelta(minutes=10), -100.0, direction="off"),
    ]
    session_trace = [
        _point(BASE_TIME - timedelta(seconds=30), 0.0),
        _point(BASE_TIME, 0.0),
        _point(BASE_TIME + timedelta(minutes=1), 120.0),
        _point(BASE_TIME + timedelta(minutes=5), 120.0),
        _point(BASE_TIME + timedelta(minutes=9), 120.0),
        _point(BASE_TIME + timedelta(minutes=10), 0.0),
    ]
    base_session = pair_nilm_sessions_for_signatures(
        edges,
        mains_circuit_id="mains",
        signature_specs=[{"signature_fingerprint": "pump", "typical_watts": 100.0}],
        power_trace=session_trace,
    )[0]
    later_session = pair_nilm_sessions_for_signatures(
        edges,
        mains_circuit_id="mains",
        signature_specs=[{"signature_fingerprint": "pump", "typical_watts": 100.0}],
        power_trace=[
            *session_trace,
            _point(BASE_TIME + timedelta(minutes=20), 0.0),
        ],
    )[0]

    assert base_session.trace_started_at == later_session.trace_started_at
    assert base_session.trace_ended_at == later_session.trace_ended_at
    assert later_session.trace_ended_at == BASE_TIME + timedelta(minutes=10)


def test_session_trace_does_not_measure_from_partial_baseline_context() -> None:
    edges = [
        NilmEdge(BASE_TIME, 100.0, direction="on"),
        NilmEdge(BASE_TIME + timedelta(minutes=10), -100.0, direction="off"),
    ]
    trace = [
        _point(
            BASE_TIME - timedelta(seconds=30),
            0.0,
            complete=False,
            coverage=0.0,
        ),
        _point(BASE_TIME, 0.0),
        _point(BASE_TIME + timedelta(minutes=1), 120.0),
        _point(BASE_TIME + timedelta(minutes=5), 120.0),
        _point(BASE_TIME + timedelta(minutes=9), 120.0),
        _point(BASE_TIME + timedelta(minutes=10), 0.0),
    ]

    session = pair_nilm_sessions_for_signatures(
        edges,
        mains_circuit_id="mains",
        signature_specs=[{"signature_fingerprint": "pump", "typical_watts": 100.0}],
        power_trace=trace,
    )[0]

    assert session.energy_source != "residual_trace_measured"
    assert session.measured_energy_kwh is None


def test_session_trace_long_outage_cannot_certify_its_own_coverage() -> None:
    edges = [
        NilmEdge(BASE_TIME, 100.0, direction="on"),
        NilmEdge(BASE_TIME + timedelta(minutes=10), -100.0, direction="off"),
    ]
    trace = [
        _point(BASE_TIME - timedelta(seconds=30), 0.0),
        _point(BASE_TIME + timedelta(seconds=1), 120.0),
        _point(BASE_TIME + timedelta(seconds=599), 120.0),
        _point(BASE_TIME + timedelta(minutes=10), 0.0),
    ]

    session = pair_nilm_sessions_for_signatures(
        edges,
        mains_circuit_id="mains",
        signature_specs=[{"signature_fingerprint": "pump", "typical_watts": 100.0}],
        power_trace=trace,
    )[0]

    assert session.longest_trace_gap_seconds == pytest.approx(598.0)
    assert session.power_coverage is not None and session.power_coverage < 0.1
    assert session.energy_source == "residual_trace_partial"
    assert session.measured_energy_kwh is None


def test_typed_trace_normalization_keeps_signed_negative_residuals() -> None:
    negative = _point(BASE_TIME, -125.0)

    assert _nilm_normalized_power_trace([negative]) == (negative,)


def test_residual_trace_freshness_replay_fixture_exercises_quality_metrics() -> None:
    fixture_path = (
        Path(__file__).parent
        / "fixtures"
        / "calibration"
        / "nilm_residual_trace_freshness.yaml"
    )
    results = {
        fixture.id.rsplit(".", 1)[-1]: replay_fixture_processors(fixture)
        for fixture in load_calibration_scenarios(fixture_path)
    }

    assert set(results) == {
        "mains_1s_direct_10s",
        "mains_10s_direct_1s",
        "delayed_direct_updates",
        "unavailable_stale_nonzero",
        "unequal_direct_cadences",
        "direct_source_recovery",
        "long_session_beyond_retained_context",
        "restart_mid_session",
        "negative_residual_misalignment",
        "complete_aligned_trace_baseline",
    }

    slow_direct = results["mains_1s_direct_10s"]
    slow_point = slow_direct.residual_trace_points_by_circuit["mains"][-1]
    assert slow_point.stale_known_circuit_ids == ("direct_a",)
    assert slow_point.explained_known_power_w == 0.0
    assert slow_direct.metrics is not None
    assert slow_direct.metrics.stale_subtraction_incidents == 1

    fast_direct = results["mains_10s_direct_1s"]
    fast_trace = fast_direct.residual_trace_points_by_circuit["mains"]
    assert [point.timestamp for point in fast_trace] == [
        fast_direct.final_state.latest_real_power_observation_by_circuit[
            "mains"
        ].observed_at
        - timedelta(seconds=20),
        fast_direct.final_state.latest_real_power_observation_by_circuit[
            "mains"
        ].observed_at
        - timedelta(seconds=10),
        fast_direct.final_state.latest_real_power_observation_by_circuit[
            "mains"
        ].observed_at,
    ]
    assert fast_trace[1].stale_known_circuit_ids == ("direct_a",)
    assert fast_trace[1].explained_known_power_w == 0.0

    unavailable = results["unavailable_stale_nonzero"]
    unavailable_point = unavailable.residual_trace_points_by_circuit["mains"][-1]
    assert unavailable_point.unavailable_known_circuit_ids == ("direct_a",)
    assert unavailable_point.missing_known_circuit_ids == ()
    assert unavailable_point.explained_known_power_w == 0.0

    unequal = results["unequal_direct_cadences"]
    unequal_point = unequal.residual_trace_points_by_circuit["mains"][-1]
    assert unequal_point.contributing_known_circuit_ids == ("direct_a",)
    assert unequal_point.stale_known_circuit_ids == ("direct_b",)

    recovery = results["direct_source_recovery"]
    recovery_point = recovery.residual_trace_points_by_circuit["mains"][-1]
    assert recovery_point.subtraction_complete is True
    assert recovery_point.residual_power_w == pytest.approx(120.0)

    long_session = results["long_session_beyond_retained_context"]
    long_trace = long_session.residual_trace_points_by_circuit["mains"]
    assert len(long_trace) == 2
    assert (long_trace[1].timestamp - long_trace[0].timestamp) == timedelta(
        seconds=10
    )

    restart = results["restart_mid_session"]
    restart_trace = restart.residual_trace_points_by_circuit["mains"]
    latest_mains = restart.final_state.latest_real_power_observation_by_circuit[
        "mains"
    ]
    assert restart_trace[0].timestamp == latest_mains.observed_at - timedelta(
        seconds=10
    )

    negative = results["negative_residual_misalignment"]
    negative_point = negative.residual_trace_points_by_circuit["mains"][-1]
    assert negative_point.residual_power_w == -500.0
    assert "negative_residual" in negative_point.quality_flags

    complete = results["complete_aligned_trace_baseline"]
    assert all(
        point.subtraction_complete
        for point in complete.residual_trace_points_by_circuit["mains"]
    )
    assert complete.metrics is not None
    assert complete.metrics.stale_subtraction_incidents == 0
    assert complete.metrics.residual_plateau_mae_w == 0.0
    assert complete.metrics.measured_session_percentage == 100.0
    assert complete.metrics.replay_processing_work_units > 0
