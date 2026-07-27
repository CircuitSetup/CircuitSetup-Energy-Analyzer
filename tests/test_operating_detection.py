from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    CircuitSample,
    EventType,
)


def _sample(
    seconds: int,
    watts: float | None,
    *,
    circuit_id: str = "washer",
    voltage: float = 120.0,
) -> CircuitSample:
    return CircuitSample(
        timestamp=datetime(2026, 6, 18, 12, 0, tzinfo=UTC) + timedelta(seconds=seconds),
        circuit_id=circuit_id,
        real_power=watts,
        current=1.0,
        voltage=voltage,
        reactive_power=0.0,
        apparent_power=abs(watts) if watts is not None else None,
        power_factor=1.0,
        frequency=60.0,
        energy=0.0,
    )


def _machine(
    *,
    on_dwell_seconds: float = 10.0,
    off_dwell_seconds: float = 20.0,
    max_sample_gap_seconds: float = 600.0,
    appliance_profile: ApplianceProfile = ApplianceProfile.REFRIGERATOR,
    circuit_mode: CircuitMode = CircuitMode.SINGLE_PHASE,
):
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingDetectionProfile,
        OperatingStateMachine,
        OperatingThresholdSource,
        ResolvedOperatingDetection,
    )

    return OperatingStateMachine(
        ResolvedOperatingDetection(
            profile=OperatingDetectionProfile(
                on_threshold_w=25.0,
                off_threshold_w=10.0,
                on_dwell_seconds=on_dwell_seconds,
                off_dwell_seconds=off_dwell_seconds,
                merge_gap_seconds=60.0,
                max_sample_gap_seconds=max_sample_gap_seconds,
            ),
            source=OperatingThresholdSource.PROFILE_DEFAULT,
            appliance_profile=appliance_profile,
            circuit_mode=circuit_mode,
        )
    )


def test_resolve_operating_detection_profiles_are_valid() -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        resolve_operating_detection,
    )

    for profile in ApplianceProfile:
        resolved = resolve_operating_detection(
            CircuitConfig(
                circuit_id=profile.value,
                name=profile.value.title(),
                appliance_profile=profile,
                mode=CircuitMode.MAINS_NILM
                if profile is ApplianceProfile.MAINS_NILM
                else CircuitMode.SINGLE_PHASE,
            )
        )
        assert resolved.profile.on_threshold_w > resolved.profile.off_threshold_w >= 0.0
        assert resolved.profile.on_dwell_seconds >= 0.0
        assert resolved.profile.off_dwell_seconds >= 0.0
        assert resolved.profile.merge_gap_seconds >= 0.0
        assert resolved.profile.max_sample_gap_seconds > 0.0


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (ApplianceProfile.DISHWASHER, (20.0, 8.0, 15.0, 90.0, 300.0, 600.0)),
        (
            ApplianceProfile.THREE_D_PRINTER,
            (35.0, 20.0, 10.0, 90.0, 180.0, 600.0),
        ),
    ],
)
def test_signature_specific_operating_defaults(
    profile: ApplianceProfile,
    expected: tuple[float, float, float, float, float, float],
) -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        resolve_operating_detection,
    )

    resolved = resolve_operating_detection(
        CircuitConfig(
            circuit_id=profile.value,
            name=profile.value,
            appliance_profile=profile,
            mode=CircuitMode.SINGLE_PHASE,
        )
    ).profile

    assert (
        resolved.on_threshold_w,
        resolved.off_threshold_w,
        resolved.on_dwell_seconds,
        resolved.off_dwell_seconds,
        resolved.merge_gap_seconds,
        resolved.max_sample_gap_seconds,
    ) == expected


def test_resolve_operating_detection_user_override_wins() -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingThresholdSource,
        resolve_operating_detection,
    )

    config = CircuitConfig(
        circuit_id="washer",
        name="Washer",
        appliance_profile=ApplianceProfile.WASHER,
        mode=CircuitMode.SINGLE_PHASE,
    )

    resolved = resolve_operating_detection(
        config,
        overrides={
            "operating_on_threshold_w": 42.0,
            "operating_off_threshold_w": 18.0,
            "operating_on_dwell_seconds": 12.0,
            "operating_off_dwell_seconds": 55.0,
            "operating_merge_gap_seconds": 90.0,
        },
    )

    assert resolved.source is OperatingThresholdSource.USER_OVERRIDE
    assert resolved.profile.on_threshold_w == 42.0
    assert resolved.profile.off_threshold_w == 18.0
    assert resolved.profile.on_dwell_seconds == 12.0
    assert resolved.profile.off_dwell_seconds == 55.0
    assert resolved.profile.merge_gap_seconds == 90.0


def test_resolve_operating_detection_rejects_invalid_override() -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        resolve_operating_detection,
    )

    config = CircuitConfig(
        circuit_id="washer",
        name="Washer",
        appliance_profile=ApplianceProfile.WASHER,
        mode=CircuitMode.SINGLE_PHASE,
    )

    with pytest.raises(ValueError):
        resolve_operating_detection(
            config,
            overrides={
                "operating_on_threshold_w": 10.0,
                "operating_off_threshold_w": 10.0,
            },
        )


def test_operating_state_machine_ignores_short_above_threshold_spike() -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingDetectionProfile,
        OperatingState,
        OperatingStateMachine,
        OperatingThresholdSource,
        ResolvedOperatingDetection,
    )

    machine = OperatingStateMachine(
        ResolvedOperatingDetection(
            profile=OperatingDetectionProfile(
                on_threshold_w=25.0,
                off_threshold_w=10.0,
                on_dwell_seconds=10.0,
                off_dwell_seconds=20.0,
                merge_gap_seconds=60.0,
                max_sample_gap_seconds=600.0,
            ),
            source=OperatingThresholdSource.PROFILE_DEFAULT,
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            circuit_mode=CircuitMode.SINGLE_PHASE,
        )
    )

    first = machine.process(_sample(0, 5.0, circuit_id="fridge"))
    second = machine.process(_sample(5, 40.0, circuit_id="fridge"))
    third = machine.process(_sample(9, 6.0, circuit_id="fridge"))

    assert first.events == ()
    assert second.events == ()
    assert third.events == ()
    assert third.snapshot.state is OperatingState.OFF
    assert third.snapshot.stable_state is OperatingState.OFF


def test_operating_state_machine_confirms_start_after_on_dwell() -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingDetectionProfile,
        OperatingState,
        OperatingStateMachine,
        OperatingThresholdSource,
        ResolvedOperatingDetection,
    )

    machine = OperatingStateMachine(
        ResolvedOperatingDetection(
            profile=OperatingDetectionProfile(
                on_threshold_w=25.0,
                off_threshold_w=10.0,
                on_dwell_seconds=10.0,
                off_dwell_seconds=20.0,
                merge_gap_seconds=60.0,
                max_sample_gap_seconds=600.0,
            ),
            source=OperatingThresholdSource.PROFILE_DEFAULT,
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            circuit_mode=CircuitMode.SINGLE_PHASE,
        )
    )

    machine.process(_sample(0, 5.0, circuit_id="fridge"))
    pending = machine.process(_sample(5, 40.0, circuit_id="fridge"))
    confirmed = machine.process(_sample(16, 42.0, circuit_id="fridge"))

    assert pending.snapshot.state is OperatingState.PENDING_ON
    assert [event.event_type for event in confirmed.events] == [EventType.START]
    assert confirmed.snapshot.state is OperatingState.RUNNING
    assert confirmed.snapshot.stable_state is OperatingState.RUNNING


def test_operating_state_machine_ignores_short_below_threshold_dip() -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingDetectionProfile,
        OperatingState,
        OperatingStateMachine,
        OperatingThresholdSource,
        ResolvedOperatingDetection,
    )

    machine = OperatingStateMachine(
        ResolvedOperatingDetection(
            profile=OperatingDetectionProfile(
                on_threshold_w=25.0,
                off_threshold_w=10.0,
                on_dwell_seconds=10.0,
                off_dwell_seconds=20.0,
                merge_gap_seconds=60.0,
                max_sample_gap_seconds=600.0,
            ),
            source=OperatingThresholdSource.PROFILE_DEFAULT,
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            circuit_mode=CircuitMode.SINGLE_PHASE,
        )
    )

    machine.process(_sample(0, 5.0, circuit_id="fridge"))
    machine.process(_sample(5, 40.0, circuit_id="fridge"))
    machine.process(_sample(16, 42.0, circuit_id="fridge"))

    pending = machine.process(_sample(20, 8.0, circuit_id="fridge"))
    recovered = machine.process(_sample(35, 35.0, circuit_id="fridge"))

    assert pending.snapshot.state is OperatingState.PENDING_OFF
    assert recovered.events == ()
    assert recovered.snapshot.state is OperatingState.RUNNING
    assert recovered.snapshot.stable_state is OperatingState.RUNNING


def test_operating_state_machine_confirms_stop_after_off_dwell() -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingDetectionProfile,
        OperatingState,
        OperatingStateMachine,
        OperatingThresholdSource,
        ResolvedOperatingDetection,
    )

    machine = OperatingStateMachine(
        ResolvedOperatingDetection(
            profile=OperatingDetectionProfile(
                on_threshold_w=25.0,
                off_threshold_w=10.0,
                on_dwell_seconds=10.0,
                off_dwell_seconds=20.0,
                merge_gap_seconds=60.0,
                max_sample_gap_seconds=600.0,
            ),
            source=OperatingThresholdSource.PROFILE_DEFAULT,
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            circuit_mode=CircuitMode.SINGLE_PHASE,
        )
    )

    machine.process(_sample(0, 5.0, circuit_id="fridge"))
    machine.process(_sample(5, 40.0, circuit_id="fridge"))
    machine.process(_sample(16, 42.0, circuit_id="fridge"))
    machine.process(_sample(20, 8.0, circuit_id="fridge"))
    confirmed = machine.process(_sample(41, 6.0, circuit_id="fridge"))

    assert [event.event_type for event in confirmed.events] == [EventType.STOP]
    assert confirmed.snapshot.state is OperatingState.OFF
    assert confirmed.snapshot.stable_state is OperatingState.OFF


def test_operating_state_machine_continued_running_preserves_state_since() -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingState,
    )

    machine = _machine()

    machine.process(_sample(0, 5.0, circuit_id="fridge"))
    machine.process(_sample(5, 40.0, circuit_id="fridge"))
    confirmed = machine.process(_sample(16, 42.0, circuit_id="fridge"))
    continued = machine.process(_sample(60, 44.0, circuit_id="fridge"))

    assert confirmed.snapshot.state is OperatingState.RUNNING
    assert continued.snapshot.state is OperatingState.RUNNING
    assert continued.snapshot.state_since == confirmed.snapshot.state_since
    assert continued.snapshot.last_sample_at == _sample(60, 44.0).timestamp


def test_operating_state_machine_continued_off_preserves_state_since() -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingState,
    )

    machine = _machine()

    first = machine.process(_sample(0, 5.0, circuit_id="fridge"))
    continued = machine.process(_sample(60, 6.0, circuit_id="fridge"))

    assert first.snapshot.state is OperatingState.OFF
    assert continued.snapshot.state is OperatingState.OFF
    assert continued.snapshot.state_since == first.snapshot.state_since
    assert continued.snapshot.last_sample_at == _sample(60, 6.0).timestamp


def test_operating_state_machine_cancelled_pending_on_preserves_off_start() -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingState,
    )

    machine = _machine()

    off = machine.process(_sample(0, 5.0, circuit_id="fridge"))
    pending = machine.process(_sample(5, 40.0, circuit_id="fridge"))
    cancelled = machine.process(_sample(9, 6.0, circuit_id="fridge"))

    assert pending.snapshot.state is OperatingState.PENDING_ON
    assert pending.snapshot.candidate_since == _sample(5, 40.0).timestamp
    assert cancelled.snapshot.state is OperatingState.OFF
    assert cancelled.snapshot.candidate_since is None
    assert cancelled.snapshot.state_since == off.snapshot.state_since


def test_operating_state_machine_cancelled_pending_off_preserves_running_start(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingState,
    )

    machine = _machine()

    machine.process(_sample(0, 5.0, circuit_id="fridge"))
    machine.process(_sample(5, 40.0, circuit_id="fridge"))
    running = machine.process(_sample(16, 42.0, circuit_id="fridge"))
    pending = machine.process(_sample(20, 8.0, circuit_id="fridge"))
    cancelled = machine.process(_sample(25, 35.0, circuit_id="fridge"))

    assert pending.snapshot.state is OperatingState.PENDING_OFF
    assert pending.snapshot.candidate_since == _sample(20, 8.0).timestamp
    assert cancelled.snapshot.state is OperatingState.RUNNING
    assert cancelled.snapshot.candidate_since is None
    assert cancelled.snapshot.state_since == running.snapshot.state_since


def test_operating_state_machine_long_gap_pending_reset_preserves_stable_since(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingState,
    )

    machine = _machine(max_sample_gap_seconds=30.0)

    off = machine.process(_sample(0, 5.0, circuit_id="fridge"))
    pending = machine.process(_sample(5, 40.0, circuit_id="fridge"))
    reset = machine.process(_sample(40, 6.0, circuit_id="fridge"))

    assert pending.snapshot.state is OperatingState.PENDING_ON
    assert reset.snapshot.state is OperatingState.OFF
    assert reset.snapshot.candidate_since is None
    assert reset.snapshot.state_since == off.snapshot.state_since


def test_operating_state_machine_unknown_start_stop_does_not_emit_orphan_stop(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingState,
    )

    machine = _machine()

    machine.process(_sample(0, 40.0, circuit_id="fridge"))
    initial_running = machine.process(_sample(12, 42.0, circuit_id="fridge"))
    pending_stop = machine.process(_sample(20, 8.0, circuit_id="fridge"))
    stopped = machine.process(_sample(41, 6.0, circuit_id="fridge"))

    assert initial_running.events == ()
    assert initial_running.snapshot.state is OperatingState.RUNNING
    assert pending_stop.snapshot.state is OperatingState.PENDING_OFF
    assert stopped.events == ()
    assert stopped.snapshot.state is OperatingState.OFF


def test_operating_state_machine_does_not_emit_false_start_on_initial_high_power(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingDetectionProfile,
        OperatingState,
        OperatingStateMachine,
        OperatingThresholdSource,
        ResolvedOperatingDetection,
    )

    machine = OperatingStateMachine(
        ResolvedOperatingDetection(
            profile=OperatingDetectionProfile(
                on_threshold_w=25.0,
                off_threshold_w=10.0,
                on_dwell_seconds=10.0,
                off_dwell_seconds=20.0,
                merge_gap_seconds=60.0,
                max_sample_gap_seconds=600.0,
            ),
            source=OperatingThresholdSource.PROFILE_DEFAULT,
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            circuit_mode=CircuitMode.SINGLE_PHASE,
        )
    )

    first = machine.process(_sample(0, 40.0, circuit_id="fridge"))
    second = machine.process(_sample(12, 42.0, circuit_id="fridge"))

    assert first.events == ()
    assert second.events == ()
    assert second.snapshot.state is OperatingState.RUNNING
    assert second.snapshot.stable_state is OperatingState.RUNNING


def test_operating_state_machine_initial_high_waits_for_on_dwell() -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingDetectionProfile,
        OperatingState,
        OperatingStateMachine,
        OperatingThresholdSource,
        ResolvedOperatingDetection,
    )

    machine = OperatingStateMachine(
        ResolvedOperatingDetection(
            profile=OperatingDetectionProfile(
                on_threshold_w=25.0,
                off_threshold_w=10.0,
                on_dwell_seconds=10.0,
                off_dwell_seconds=20.0,
                merge_gap_seconds=60.0,
                max_sample_gap_seconds=600.0,
            ),
            source=OperatingThresholdSource.PROFILE_DEFAULT,
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            circuit_mode=CircuitMode.SINGLE_PHASE,
        )
    )

    first = machine.process(_sample(0, 40.0, circuit_id="fridge"))
    second = machine.process(_sample(5, 42.0, circuit_id="fridge"))
    third = machine.process(_sample(12, 43.0, circuit_id="fridge"))

    assert first.events == ()
    assert second.events == ()
    assert second.snapshot.state is OperatingState.PENDING_ON
    assert second.snapshot.stable_state is OperatingState.UNKNOWN
    assert third.events == ()
    assert third.snapshot.state is OperatingState.RUNNING
    assert third.snapshot.stable_state is OperatingState.RUNNING


def test_operating_state_machine_confirmed_events_keep_threshold_crossing_time(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingDetectionProfile,
        OperatingStateMachine,
        OperatingThresholdSource,
        ResolvedOperatingDetection,
    )

    machine = OperatingStateMachine(
        ResolvedOperatingDetection(
            profile=OperatingDetectionProfile(
                on_threshold_w=25.0,
                off_threshold_w=10.0,
                on_dwell_seconds=10.0,
                off_dwell_seconds=45.0,
                merge_gap_seconds=60.0,
                max_sample_gap_seconds=600.0,
            ),
            source=OperatingThresholdSource.PROFILE_DEFAULT,
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            circuit_mode=CircuitMode.SINGLE_PHASE,
        )
    )

    machine.process(_sample(0, 5.0, circuit_id="fridge"))
    machine.process(_sample(30, 300.0, circuit_id="fridge"))
    start = machine.process(_sample(60, 300.0, circuit_id="fridge"))
    stop_pending = machine.process(_sample(120, 0.0, circuit_id="fridge"))
    stop = machine.process(_sample(180, 0.0, circuit_id="fridge"))

    assert stop_pending.events == ()
    assert (
        start.events[0].timestamp
        == _sample(30, 300.0, circuit_id="fridge").timestamp
    )
    assert (
        stop.events[0].timestamp
        == _sample(120, 0.0, circuit_id="fridge").timestamp
    )
    assert stop.events[0].features["run_duration_s"] == 90.0


def test_operating_state_machine_ignores_duplicate_and_out_of_order_samples() -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingDetectionProfile,
        OperatingStateMachine,
        OperatingThresholdSource,
        ResolvedOperatingDetection,
    )

    machine = OperatingStateMachine(
        ResolvedOperatingDetection(
            profile=OperatingDetectionProfile(
                on_threshold_w=25.0,
                off_threshold_w=10.0,
                on_dwell_seconds=10.0,
                off_dwell_seconds=20.0,
                merge_gap_seconds=60.0,
                max_sample_gap_seconds=600.0,
            ),
            source=OperatingThresholdSource.PROFILE_DEFAULT,
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            circuit_mode=CircuitMode.SINGLE_PHASE,
        )
    )

    machine.process(_sample(0, 5.0, circuit_id="fridge"))
    machine.process(_sample(5, 40.0, circuit_id="fridge"))

    duplicate = machine.process(_sample(5, 40.0, circuit_id="fridge"))
    out_of_order = machine.process(_sample(4, 40.0, circuit_id="fridge"))
    confirmed = machine.process(_sample(16, 42.0, circuit_id="fridge"))

    assert duplicate.events == ()
    assert out_of_order.events == ()
    assert [event.event_type for event in confirmed.events] == [EventType.START]


def test_operating_state_machine_marks_state_unavailable_after_missing_power_grace(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingDetectionProfile,
        OperatingState,
        OperatingStateMachine,
        OperatingThresholdSource,
        ResolvedOperatingDetection,
    )

    machine = OperatingStateMachine(
        ResolvedOperatingDetection(
            profile=OperatingDetectionProfile(
                on_threshold_w=25.0,
                off_threshold_w=10.0,
                on_dwell_seconds=10.0,
                off_dwell_seconds=20.0,
                merge_gap_seconds=60.0,
                max_sample_gap_seconds=30.0,
            ),
            source=OperatingThresholdSource.PROFILE_DEFAULT,
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            circuit_mode=CircuitMode.SINGLE_PHASE,
        )
    )

    machine.process(_sample(0, 5.0, circuit_id="fridge"))
    machine.process(_sample(5, 40.0, circuit_id="fridge"))
    machine.process(_sample(16, 42.0, circuit_id="fridge"))

    brief_gap = machine.process(_sample(30, None, circuit_id="fridge"))
    extended_gap = machine.process(_sample(50, None, circuit_id="fridge"))

    assert brief_gap.snapshot.state is OperatingState.RUNNING
    assert brief_gap.snapshot.stable_state is OperatingState.RUNNING
    assert extended_gap.snapshot.state is OperatingState.UNAVAILABLE
    assert extended_gap.snapshot.stable_state is OperatingState.UNAVAILABLE
    assert [event.event_type for event in extended_gap.events] == [EventType.STOP]
    assert extended_gap.events[0].timestamp == _sample(
        46,
        0.0,
        circuit_id="fridge",
    ).timestamp


def test_operating_state_machine_closes_running_cycle_when_gap_turns_unavailable(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        summarize_circuit_cycles,
    )
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingDetectionProfile,
        OperatingState,
        OperatingStateMachine,
        OperatingThresholdSource,
        ResolvedOperatingDetection,
    )

    machine = OperatingStateMachine(
        ResolvedOperatingDetection(
            profile=OperatingDetectionProfile(
                on_threshold_w=25.0,
                off_threshold_w=10.0,
                on_dwell_seconds=10.0,
                off_dwell_seconds=20.0,
                merge_gap_seconds=60.0,
                max_sample_gap_seconds=30.0,
            ),
            source=OperatingThresholdSource.PROFILE_DEFAULT,
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            circuit_mode=CircuitMode.SINGLE_PHASE,
        )
    )

    events = []
    machine.process(_sample(0, 5.0, circuit_id="fridge"))
    machine.process(_sample(5, 40.0, circuit_id="fridge"))
    start = machine.process(_sample(16, 42.0, circuit_id="fridge"))
    events.extend(start.events)
    machine.process(_sample(30, None, circuit_id="fridge"))
    unavailable = machine.process(_sample(50, None, circuit_id="fridge"))
    events.extend(unavailable.events)
    settled = machine.process(_sample(70, 5.0, circuit_id="fridge"))

    assert unavailable.snapshot.state is OperatingState.UNAVAILABLE
    assert unavailable.snapshot.stable_state is OperatingState.UNAVAILABLE
    assert [event.event_type for event in unavailable.events] == [EventType.STOP]
    assert unavailable.events[0].timestamp == _sample(
        46,
        0.0,
        circuit_id="fridge",
    ).timestamp
    assert unavailable.events[0].features["stop_power_w"] == 42.0
    assert unavailable.events[0].features["run_duration_s"] == 41.0
    assert settled.events == ()
    assert settled.snapshot.state is OperatingState.OFF
    assert settled.snapshot.stable_state is OperatingState.OFF

    summary = summarize_circuit_cycles(
        events,
        circuit_id="fridge",
        now=_sample(70, 5.0, circuit_id="fridge").timestamp,
        merge_gap_seconds=60.0,
    )

    assert summary.status == "idle"
    assert summary.completed_cycle_count == 1
    assert summary.runtime_seconds == 41.0
    assert summary.active_cycle_seconds == 0.0


def test_operating_state_machine_recovers_from_unavailable_without_false_start(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingDetectionProfile,
        OperatingState,
        OperatingStateMachine,
        OperatingThresholdSource,
        ResolvedOperatingDetection,
    )

    machine = OperatingStateMachine(
        ResolvedOperatingDetection(
            profile=OperatingDetectionProfile(
                on_threshold_w=25.0,
                off_threshold_w=10.0,
                on_dwell_seconds=10.0,
                off_dwell_seconds=20.0,
                merge_gap_seconds=60.0,
                max_sample_gap_seconds=30.0,
            ),
            source=OperatingThresholdSource.PROFILE_DEFAULT,
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            circuit_mode=CircuitMode.SINGLE_PHASE,
        )
    )

    machine.process(_sample(0, 5.0, circuit_id="fridge"))
    machine.process(_sample(5, 40.0, circuit_id="fridge"))
    machine.process(_sample(16, 42.0, circuit_id="fridge"))
    machine.process(_sample(50, None, circuit_id="fridge"))

    pending = machine.process(_sample(60, 41.0, circuit_id="fridge"))
    recovered = machine.process(_sample(72, 43.0, circuit_id="fridge"))

    assert pending.snapshot.state is OperatingState.PENDING_ON
    assert pending.snapshot.stable_state is OperatingState.UNKNOWN
    assert pending.events == ()
    assert recovered.snapshot.state is OperatingState.RUNNING
    assert recovered.snapshot.stable_state is OperatingState.RUNNING
    assert recovered.events == ()
