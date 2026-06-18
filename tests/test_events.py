from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer.events import CircuitEventDetector
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    CircuitSample,
    EventType,
    PowerFlowMode,
    SensorRef,
    SensorRole,
)
from custom_components.circuitsetup_energy_analyzer.normalize import (
    SourceState,
    build_circuit_sample,
)


def sample(
    seconds: int,
    watts: float,
    voltage: float = 120.0,
    *,
    circuit_id: str = "fridge",
) -> CircuitSample:
    return CircuitSample(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC) + timedelta(seconds=seconds),
        circuit_id=circuit_id,
        real_power=watts,
        current=1.0,
        voltage=voltage,
        reactive_power=0.0,
        apparent_power=watts,
        power_factor=1.0,
        frequency=60.0,
        energy=0.0,
    )


def test_event_detector_emits_start_and_stop() -> None:
    detector = CircuitEventDetector(on_threshold_w=80.0, off_threshold_w=30.0)

    events = []
    events.extend(detector.process(sample(0, 5.0)))
    events.extend(detector.process(sample(10, 210.0)))
    events.extend(detector.process(sample(20, 210.0)))
    events.extend(detector.process(sample(40, 8.0)))
    events.extend(detector.process(sample(70, 8.0)))

    assert [event.event_type for event in events] == [EventType.START, EventType.STOP]
    assert events[0].features["startup_power_w"] == 210.0
    assert events[1].features["stop_power_w"] == 210.0
    assert events[0].timestamp == sample(10, 210.0).timestamp
    assert events[1].timestamp == sample(40, 8.0).timestamp
    assert events[1].features["run_duration_s"] == 30.0


def test_event_detector_emits_voltage_sag_under_load() -> None:
    detector = CircuitEventDetector(on_threshold_w=80.0, voltage_sag_ratio=0.08)

    events = []
    events.extend(detector.process(sample(0, 5.0, 120.0)))
    events.extend(detector.process(sample(10, 500.0, 109.0)))
    events.extend(detector.process(sample(20, 500.0, 109.0)))

    assert [event.event_type for event in events] == [
        EventType.START,
        EventType.VOLTAGE_SAG,
    ]


def test_event_detector_treats_generation_export_as_start() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="solar",
        name="Solar inverter",
        appliance_profile=ApplianceProfile.SOLAR_INVERTER,
        mode=CircuitMode.SINGLE_PHASE,
        power_flow=PowerFlowMode.GENERATION,
        sensors=(SensorRef("sensor.solar_power", SensorRole.REAL_POWER),),
    )
    exported = build_circuit_sample(
        config,
        {
            "sensor.solar_power": SourceState(
                "sensor.solar_power",
                "-3200",
                "W",
                now,
            )
        },
        now,
    )
    idle = build_circuit_sample(
        config,
        {
            "sensor.solar_power": SourceState(
                "sensor.solar_power",
                "0",
                "W",
                now - timedelta(seconds=20),
            )
        },
        now - timedelta(seconds=20),
    )
    later = build_circuit_sample(
        config,
        {
            "sensor.solar_power": SourceState(
                "sensor.solar_power",
                "-3200",
                "W",
                now + timedelta(seconds=20),
            )
        },
        now + timedelta(seconds=20),
    )
    detector = CircuitEventDetector(on_threshold_w=80.0)

    events = []
    events.extend(detector.process(idle))
    events.extend(detector.process(exported))
    events.extend(detector.process(later))

    assert [event.event_type for event in events] == [EventType.START]
    assert events[0].features["startup_power_w"] == 3200.0
    assert events[0].features["raw_real_power_w"] == -3200.0
    assert events[0].features["power_flow_direction"] == "export"
