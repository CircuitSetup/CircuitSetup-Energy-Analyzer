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
    assert extended_gap.events == ()


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
