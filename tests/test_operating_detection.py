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
    on_threshold_w: float = 25.0,
    off_threshold_w: float = 10.0,
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
                on_threshold_w=on_threshold_w,
                off_threshold_w=off_threshold_w,
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


def test_mixed_mode_uses_generic_thresholds_without_losing_metadata() -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        resolve_operating_detection,
    )

    resolved = resolve_operating_detection(
        CircuitConfig(
            circuit_id="fridge",
            name="Fridge",
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            mode=CircuitMode.MIXED,
        )
    )

    assert resolved.profile.on_threshold_w == 80.0
    assert resolved.profile.off_threshold_w == 30.0
    assert resolved.appliance_profile is ApplianceProfile.REFRIGERATOR
    assert resolved.circuit_mode is CircuitMode.MIXED


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (ApplianceProfile.DISHWASHER, (20.0, 8.0, 15.0, 90.0, 300.0, 600.0)),
        (
            ApplianceProfile.THREE_D_PRINTER,
            (35.0, 20.0, 10.0, 90.0, 180.0, 600.0),
        ),
        (
            ApplianceProfile.MINI_SPLIT,
            (100.0, 40.0, 30.0, 180.0, 300.0, 600.0),
        ),
        (
            ApplianceProfile.HEAT_PUMP,
            (500.0, 200.0, 10.0, 60.0, 120.0, 600.0),
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
        OPERATING_IDLE_SAMPLE_COUNT,
        OPERATING_RUNNING_SAMPLE_COUNT,
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

    machine.process(_sample(0, 4.0, circuit_id="fridge"))
    machine.process(_sample(1, 4.0, circuit_id="fridge"))
    machine.process(_sample(2, 5.0, circuit_id="fridge"))
    machine.process(_sample(3, 6.0, circuit_id="fridge"))
    machine.process(_sample(4, 40.0, circuit_id="fridge"))
    machine.process(_sample(16, 42.0, circuit_id="fridge"))
    machine.process(_sample(17, 80.0, circuit_id="fridge"))
    machine.process(_sample(18, 90.0, circuit_id="fridge"))
    machine.process(_sample(19, 100.0, circuit_id="fridge"))

    pending = machine.process(_sample(20, 8.0, circuit_id="fridge"))
    recovered = machine.process(_sample(35, 35.0, circuit_id="fridge"))
    machine.process(_sample(36, 80.0, circuit_id="fridge"))
    machine.process(_sample(37, 90.0, circuit_id="fridge"))
    machine.process(_sample(38, 100.0, circuit_id="fridge"))
    machine.process(_sample(39, 8.0, circuit_id="fridge"))
    stopped = machine.process(_sample(60, 7.0, circuit_id="fridge"))

    assert pending.snapshot.state is OperatingState.PENDING_OFF
    assert recovered.events == ()
    assert recovered.snapshot.state is OperatingState.RUNNING
    assert recovered.snapshot.stable_state is OperatingState.RUNNING
    assert stopped.events[0].features[OPERATING_IDLE_SAMPLE_COUNT] == 3
    assert stopped.events[0].features[OPERATING_RUNNING_SAMPLE_COUNT] == 6


@pytest.mark.parametrize(
    ("before_w", "after_w", "expected_delta_w"),
    ((500.0, 900.0, 400.0), (900.0, 500.0, -400.0)),
)
def test_running_power_step_emits_confirmed_transition_evidence(
    before_w: float,
    after_w: float,
    expected_delta_w: float,
) -> None:
    machine = _machine()
    events = []
    for seconds, watts in (
        (0, 5.0),
        (5, before_w),
        (15, before_w),
        (20, before_w),
        (25, before_w),
        (30, after_w),
        (35, after_w),
        (40, after_w),
    ):
        events.extend(
            machine.process(_sample(seconds, watts, circuit_id="fridge")).events
        )

    transitions = [
        event for event in events if event.event_type is EventType.POWER_TRANSITION
    ]
    assert len(transitions) == 1
    transition = transitions[0]
    assert transition.timestamp == _sample(30, after_w, circuit_id="fridge").timestamp
    assert transition.features["transition_delta_w"] == expected_delta_w
    assert transition.features["pre_power_median_w"] == before_w
    assert transition.features["post_power_median_w"] == after_w
    assert transition.features["pre_power_spread_w"] == 0.0
    assert transition.features["post_power_spread_w"] == 0.0
    assert transition.features["transition_kind"] == "step"
    assert transition.features["lifecycle_state_before"] == "running"
    assert transition.features["lifecycle_state_after"] == "running"
    assert transition.features["transition_evidence_version"] == 1
    assert transition.features["transition_quality"] == "measured"


def test_running_power_steps_do_not_duplicate_lifecycle_events_or_cycles() -> None:
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        summarize_circuit_cycles,
    )

    machine = _machine()
    events = []
    for seconds, watts in (
        (0, 5.0),
        (5, 500.0),
        (15, 500.0),
        (20, 500.0),
        (25, 500.0),
        (30, 900.0),
        (35, 900.0),
        (40, 900.0),
        (50, 5.0),
        (70, 5.0),
    ):
        events.extend(
            machine.process(_sample(seconds, watts, circuit_id="fridge")).events
        )

    assert [event.event_type for event in events] == [
        EventType.START,
        EventType.POWER_TRANSITION,
        EventType.STOP,
    ]
    summary = summarize_circuit_cycles(
        events,
        circuit_id="fridge",
        now=_sample(70, 5.0, circuit_id="fridge").timestamp,
        merge_gap_seconds=60.0,
    )
    assert summary.completed_cycle_count == 1


def test_running_power_step_ignores_short_spikes_and_unsettled_ramps() -> None:
    machine = _machine()
    events = []
    for seconds, watts in (
        (0, 5.0),
        (5, 500.0),
        (15, 500.0),
        (20, 500.0),
        (25, 500.0),
        (30, 900.0),
        (35, 500.0),
        (40, 550.0),
        (45, 600.0),
        (50, 650.0),
        (55, 700.0),
        (60, 750.0),
        (65, 800.0),
    ):
        events.extend(
            machine.process(_sample(seconds, watts, circuit_id="fridge")).events
        )

    assert EventType.POWER_TRANSITION not in [event.event_type for event in events]


def test_running_power_step_cooldown_prevents_duplicate_plateau_events() -> None:
    machine = _machine()
    events = []
    for seconds, watts in (
        (0, 5.0),
        (5, 500.0),
        (15, 500.0),
        (20, 500.0),
        (25, 500.0),
        (30, 900.0),
        (35, 900.0),
        (40, 900.0),
        (45, 900.0),
        (50, 900.0),
        (55, 900.0),
        (60, 900.0),
    ):
        events.extend(
            machine.process(_sample(seconds, watts, circuit_id="fridge")).events
        )

    assert [event.event_type for event in events].count(EventType.POWER_TRANSITION) == 1


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


def test_completed_stop_records_stable_cycle_power_boundaries() -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OPERATING_IDLE_SAMPLE_COUNT,
        OPERATING_IDLE_UPPER_W,
        OPERATING_RUNNING_LOWER_W,
        OPERATING_RUNNING_SAMPLE_COUNT,
    )

    machine = _machine()
    machine.process(_sample(0, 4.0))
    machine.process(_sample(1, 4.0))
    machine.process(_sample(2, 5.0))
    machine.process(_sample(3, 6.0))
    machine.process(_sample(4, 50.0))
    machine.process(_sample(15, 55.0))
    machine.process(_sample(16, 80.0))
    machine.process(_sample(17, 90.0))
    machine.process(_sample(18, 100.0))
    machine.process(_sample(19, 8.0))
    stopped = machine.process(_sample(40, 7.0))

    stop = stopped.events[0]
    assert stop.event_type is EventType.STOP
    assert stop.features[OPERATING_IDLE_UPPER_W] == 6.0
    assert stop.features[OPERATING_RUNNING_LOWER_W] == 80.0
    assert stop.features[OPERATING_IDLE_SAMPLE_COUNT] == 3
    assert stop.features[OPERATING_RUNNING_SAMPLE_COUNT] == 3


def test_completed_cycles_keep_independent_power_boundaries() -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OPERATING_IDLE_SAMPLE_COUNT,
        OPERATING_IDLE_UPPER_W,
        OPERATING_RUNNING_LOWER_W,
        OPERATING_RUNNING_SAMPLE_COUNT,
    )

    machine = _machine()
    for seconds in range(4):
        machine.process(_sample(seconds, 20.0))
    machine.process(_sample(4, 50.0))
    machine.process(_sample(15, 55.0))
    for seconds, watts in ((16, 80.0), (17, 90.0), (18, 100.0)):
        machine.process(_sample(seconds, watts))
    machine.process(_sample(19, 8.0))
    first_stop = machine.process(_sample(40, 7.0)).events[0]

    for seconds in range(41, 44):
        machine.process(_sample(seconds, 2.0))
    machine.process(_sample(44, 50.0))
    machine.process(_sample(55, 55.0))
    for seconds, watts in ((56, 40.0), (57, 50.0), (58, 60.0)):
        machine.process(_sample(seconds, watts))
    machine.process(_sample(59, 8.0))
    second_stop = machine.process(_sample(80, 7.0)).events[0]

    assert first_stop.features[OPERATING_IDLE_UPPER_W] == 20.0
    assert first_stop.features[OPERATING_IDLE_SAMPLE_COUNT] == 3
    assert second_stop.features[OPERATING_IDLE_UPPER_W] == 2.0
    assert second_stop.features[OPERATING_RUNNING_LOWER_W] == 40.0
    assert second_stop.features[OPERATING_IDLE_SAMPLE_COUNT] == 3
    assert second_stop.features[OPERATING_RUNNING_SAMPLE_COUNT] == 3


def test_unavailable_stop_omits_learned_cycle_boundaries() -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OPERATING_IDLE_UPPER_W,
        OPERATING_RUNNING_LOWER_W,
    )

    machine = _machine(max_sample_gap_seconds=30.0)
    machine.process(_sample(0, 4.0))
    machine.process(_sample(1, 5.0))
    machine.process(_sample(2, 6.0))
    machine.process(_sample(3, 7.0))
    machine.process(_sample(5, 40.0))
    machine.process(_sample(16, 42.0))
    machine.process(_sample(17, 80.0))
    machine.process(_sample(18, 90.0))
    machine.process(_sample(19, 100.0))
    machine.process(_sample(30, None))
    unavailable = machine.process(_sample(50, None))

    stop = unavailable.events[0]
    assert stop.event_type is EventType.STOP
    assert OPERATING_IDLE_UPPER_W not in stop.features
    assert OPERATING_RUNNING_LOWER_W not in stop.features


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
        OPERATING_IDLE_SAMPLE_COUNT,
        OPERATING_RUNNING_SAMPLE_COUNT,
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

    machine.process(_sample(0, 4.0, circuit_id="fridge"))
    machine.process(_sample(1, 4.0, circuit_id="fridge"))
    machine.process(_sample(2, 5.0, circuit_id="fridge"))
    machine.process(_sample(3, 6.0, circuit_id="fridge"))
    duplicate_off = machine.process(_sample(3, 6.0, circuit_id="fridge"))
    out_of_order_off = machine.process(_sample(2, 5.0, circuit_id="fridge"))
    machine.process(_sample(4, 40.0, circuit_id="fridge"))
    confirmed = machine.process(_sample(16, 42.0, circuit_id="fridge"))
    machine.process(_sample(17, 80.0, circuit_id="fridge"))
    duplicate_running = machine.process(_sample(17, 80.0, circuit_id="fridge"))
    out_of_order_running = machine.process(_sample(16, 42.0, circuit_id="fridge"))
    machine.process(_sample(18, 90.0, circuit_id="fridge"))
    machine.process(_sample(19, 100.0, circuit_id="fridge"))
    machine.process(_sample(20, 8.0, circuit_id="fridge"))
    stopped = machine.process(_sample(41, 7.0, circuit_id="fridge"))

    assert duplicate_off.events == ()
    assert out_of_order_off.events == ()
    assert duplicate_running.events == ()
    assert out_of_order_running.events == ()
    assert [event.event_type for event in confirmed.events] == [EventType.START]
    assert stopped.events[0].features[OPERATING_IDLE_SAMPLE_COUNT] == 3
    assert stopped.events[0].features[OPERATING_RUNNING_SAMPLE_COUNT] == 3


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


def test_confirmed_start_includes_synchronized_transition_evidence() -> None:
    import json

    machine = _machine()
    machine.process(_sample(0, 20.0, circuit_id="fridge"))
    machine.process(_sample(5, 120.0, circuit_id="fridge"))
    start = machine.process(_sample(15, 120.0, circuit_id="fridge")).events[0]

    assert start.timestamp == _sample(5, 120.0, circuit_id="fridge").timestamp
    assert start.features["startup_power_w"] == 120.0
    assert start.features["pre_power_median_w"] == 20.0
    assert start.features["post_power_median_w"] == 120.0
    assert start.features["transition_delta_w"] == 100.0
    assert start.features["pre_power_spread_w"] == 0.0
    assert start.features["post_power_spread_w"] == 0.0
    assert start.features["transition_spread_w"] == 0.0
    assert start.features["pre_sample_count"] == 1
    assert start.features["post_sample_count"] == 2
    assert start.features["transition_evidence_version"] == 1
    assert start.features["transition_quality"] == "measured"
    assert start.features["transition_timestamp"] == "2026-06-18T12:00:05+00:00"
    assert start.features["transition_window_start"] == "2026-06-18T12:00:00+00:00"
    assert start.features["transition_window_end"] == "2026-06-18T12:00:05+00:00"
    assert start.features["transition_timing_uncertainty_s"] == 5.0
    json.dumps(dict(start.features), allow_nan=False)


def test_confirmed_start_uses_post_plateau_median_not_confirmation_power() -> None:
    machine = _machine()
    machine.process(_sample(0, 20.0, circuit_id="fridge"))
    machine.process(_sample(5, 145.0, circuit_id="fridge"))
    machine.process(_sample(10, 122.0, circuit_id="fridge"))
    start = machine.process(_sample(15, 118.0, circuit_id="fridge")).events[0]

    assert start.features["startup_power_w"] == 118.0
    assert start.features["post_plateau_power_w"] == 122.0
    assert start.features["post_power_median_w"] == 122.0
    assert start.features["transition_delta_w"] == 102.0


def test_transition_features_use_plateau_medians_and_adjacent_boundaries() -> None:
    machine = _machine()
    machine.process(_sample(0, 20.0, circuit_id="fridge"))
    machine.process(_sample(5, 22.0, circuit_id="fridge"))
    machine.process(_sample(10, 18.0, circuit_id="fridge"))
    machine.process(_sample(15, 145.0, circuit_id="fridge"))
    machine.process(_sample(20, 118.0, circuit_id="fridge"))
    start = machine.process(_sample(25, 122.0, circuit_id="fridge")).events[0]

    assert start.features["pre_power_median_w"] == 20.0
    assert start.features["post_power_median_w"] == 122.0
    assert start.features["transition_delta_w"] == 102.0
    assert start.features["transition_window_start"] == "2026-06-18T12:00:10+00:00"
    assert start.features["transition_window_end"] == "2026-06-18T12:00:15+00:00"
    assert start.features["transition_timing_uncertainty_s"] == 5.0
    assert start.features["pre_sample_count"] == 3
    assert start.features["post_sample_count"] == 3
    assert start.features["transition_pre_sample_count"] == 3
    assert start.features["transition_post_sample_count"] == 3


def test_confirmed_stop_includes_signed_transition_evidence() -> None:
    machine = _machine(on_threshold_w=30.0, off_threshold_w=25.0)
    machine.process(_sample(0, 20.0, circuit_id="fridge"))
    machine.process(_sample(5, 120.0, circuit_id="fridge"))
    machine.process(_sample(15, 120.0, circuit_id="fridge"))
    machine.process(_sample(16, 120.0, circuit_id="fridge"))
    machine.process(_sample(20, 20.0, circuit_id="fridge"))
    machine.process(_sample(30, 15.0, circuit_id="fridge"))
    stop = machine.process(_sample(40, 25.0, circuit_id="fridge")).events[0]

    assert stop.timestamp == _sample(20, 20.0, circuit_id="fridge").timestamp
    assert stop.features["stop_power_w"] == 120.0
    assert stop.features["pre_power_median_w"] == 120.0
    assert stop.features["post_power_median_w"] == 20.0
    assert stop.features["post_plateau_power_w"] == 20.0
    assert stop.features["transition_delta_w"] == -100.0
    assert stop.features["transition_quality"] == "measured"


def test_cancelled_pending_transitions_do_not_leak_transition_evidence() -> None:
    machine = _machine()
    machine.process(_sample(0, 20.0, circuit_id="fridge"))
    machine.process(_sample(5, 120.0, circuit_id="fridge"))
    machine.process(_sample(8, 20.0, circuit_id="fridge"))
    machine.process(_sample(20, 130.0, circuit_id="fridge"))
    start = machine.process(_sample(30, 130.0, circuit_id="fridge")).events[0]

    assert start.features["post_power_median_w"] == 130.0
    assert start.features["post_sample_count"] == 2

    machine.process(_sample(31, 125.0, circuit_id="fridge"))
    machine.process(_sample(35, 10.0, circuit_id="fridge"))
    machine.process(_sample(40, 125.0, circuit_id="fridge"))
    machine.process(_sample(45, 125.0, circuit_id="fridge"))
    machine.process(_sample(50, 10.0, circuit_id="fridge"))
    stop = machine.process(
        _sample(70, 10.0, circuit_id="fridge")
    ).events[0]

    assert stop.features["pre_power_median_w"] == 125.0
    assert stop.features["post_power_median_w"] == 10.0
    assert stop.features["post_sample_count"] == 2


def test_invalid_gap_and_timestamp_samples_cannot_contaminate_transition_evidence(
) -> None:
    machine = _machine(max_sample_gap_seconds=30.0)
    machine.process(_sample(0, 20.0, circuit_id="fridge"))
    machine.process(_sample(5, 120.0, circuit_id="fridge"))
    machine.process(_sample(5, 999.0, circuit_id="fridge"))
    machine.process(_sample(4, 999.0, circuit_id="fridge"))
    machine.process(_sample(15, None, circuit_id="fridge"))
    machine.process(_sample(50, 20.0, circuit_id="fridge"))
    machine.process(_sample(60, 130.0, circuit_id="fridge"))
    start = machine.process(_sample(70, 130.0, circuit_id="fridge")).events[0]

    assert start.features["pre_power_median_w"] == 20.0
    assert start.features["post_power_median_w"] == 130.0
    assert start.features["transition_delta_w"] == 110.0


def test_unavailable_stop_is_legacy_fallback_without_fabricated_delta() -> None:
    machine = _machine(max_sample_gap_seconds=30.0)
    machine.process(_sample(0, 20.0, circuit_id="fridge"))
    machine.process(_sample(5, 120.0, circuit_id="fridge"))
    machine.process(_sample(15, 120.0, circuit_id="fridge"))
    machine.process(_sample(20, None, circuit_id="fridge"))
    stop = machine.process(_sample(50, None, circuit_id="fridge")).events[0]

    assert stop.features["stop_power_w"] == 120.0
    assert stop.features["transition_quality"] == "legacy_fallback"
    assert "transition_delta_w" not in stop.features
    assert "post_plateau_power_w" not in stop.features


def test_unavailable_stop_after_pending_off_drops_measured_transition_evidence(
) -> None:
    machine = _machine(
        on_threshold_w=30.0,
        off_threshold_w=25.0,
        max_sample_gap_seconds=30.0,
    )
    machine.process(_sample(0, 20.0, circuit_id="fridge"))
    machine.process(_sample(5, 120.0, circuit_id="fridge"))
    machine.process(_sample(15, 120.0, circuit_id="fridge"))
    machine.process(_sample(16, 120.0, circuit_id="fridge"))
    machine.process(_sample(20, 20.0, circuit_id="fridge"))
    stop = machine.process(_sample(51, None, circuit_id="fridge")).events[0]

    assert stop.features["stop_power_w"] == 120.0
    assert stop.features["transition_quality"] == "legacy_fallback"
    assert "transition_delta_w" not in stop.features
    assert "post_plateau_power_w" not in stop.features


def test_transition_crossing_prunes_pre_context_older_than_sixty_seconds() -> None:
    machine = _machine(max_sample_gap_seconds=600.0)
    machine.process(_sample(0, 20.0, circuit_id="fridge"))
    machine.process(_sample(61, 120.0, circuit_id="fridge"))
    start = machine.process(_sample(71, 120.0, circuit_id="fridge")).events[0]

    assert start.features["pre_sample_count"] == 0
    assert start.features["post_sample_count"] == 2
    assert start.features["transition_quality"] == "partial"
    assert "transition_delta_w" not in start.features


def test_pending_transition_post_samples_remain_bounded_and_age_pruned() -> None:
    machine = _machine(on_dwell_seconds=100.0)
    machine.process(_sample(0, 20.0, circuit_id="fridge"))
    for seconds in range(1, 100, 5):
        machine.process(_sample(seconds, 120.0, circuit_id="fridge"))
    start = machine.process(_sample(101, 120.0, circuit_id="fridge")).events[0]

    assert start.features["post_sample_count"] == 12
    assert start.features["post_power_median_w"] == 120.0
    assert start.features["transition_window_end"] == "2026-06-18T12:00:46+00:00"


def test_pending_transition_post_window_excludes_samples_older_than_sixty_seconds(
) -> None:
    machine = _machine(on_dwell_seconds=100.0)
    machine.process(_sample(0, 20.0, circuit_id="fridge"))
    for seconds, watts in (
        (1, 100.0),
        (21, 110.0),
        (41, 120.0),
        (61, 130.0),
        (81, 140.0),
    ):
        machine.process(_sample(seconds, watts, circuit_id="fridge"))
    start = machine.process(_sample(101, 150.0, circuit_id="fridge")).events[0]

    assert start.features["post_sample_count"] == 4
    assert start.features["post_power_median_w"] == 135.0


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
