from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_ADVANCED_SETTINGS,
    CONF_CIRCUITS,
)
from custom_components.circuitsetup_energy_analyzer.coordinator import (
    EnergyAnalyzerCoordinator,
)
from custom_components.circuitsetup_energy_analyzer.mains_power_quality import (
    MainsPowerQualityDetector,
    MainsPowerQualitySettings,
    mains_power_quality_settings_from_mapping,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
    SensorRef,
    SensorRole,
)
from custom_components.circuitsetup_energy_analyzer.normalize import (
    NormalizedCircuitSample,
)
from custom_components.circuitsetup_energy_analyzer.processors import (
    MainsPowerQualityProcessor,
)
from custom_components.circuitsetup_energy_analyzer.processors.base import (
    ProcessingContext,
)
from custom_components.circuitsetup_energy_analyzer.profiles import (
    get_profile_definition,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData

_BASE_TIME = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def _mains_config() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )


def _mains_config_with_voltage_sensor() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_voltage", SensorRole.VOLTAGE),),
    )


def _mains_config_with_frequency_sensor() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_frequency", SensorRole.FREQUENCY),),
    )


def _mains_config_with_leg_voltage_sensors() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(
            SensorRef("sensor.mains_l1_voltage", SensorRole.VOLTAGE, leg="a"),
            SensorRef("sensor.mains_l2_voltage", SensorRole.VOLTAGE, leg="b"),
        ),
    )


def _mains_config_with_alias_leg_voltage_sensors() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(
            SensorRef("sensor.mains_l1_voltage", SensorRole.VOLTAGE, leg="line1"),
            SensorRef("sensor.mains_l2_voltage", SensorRole.VOLTAGE, leg="line2"),
        ),
    )


def _mains_config_with_power_quality_sensors() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(
            SensorRef("sensor.mains_voltage", SensorRole.VOLTAGE),
            SensorRef("sensor.mains_frequency", SensorRole.FREQUENCY),
        ),
    )


def _appliance_config() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="dryer",
        name="Dryer",
        appliance_profile=ApplianceProfile.DRYER,
        mode=CircuitMode.DUAL_PHASE,
    )


def _sample(
    minute: int,
    *,
    circuit_id: str = "mains",
    voltage: float | None = 120.0,
    leg_a_voltage: float | None = None,
    leg_b_voltage: float | None = None,
    frequency: float = 60.0,
    quality_issues: tuple[str, ...] = (),
) -> NormalizedCircuitSample:
    return NormalizedCircuitSample(
        timestamp=_BASE_TIME + timedelta(minutes=minute),
        circuit_id=circuit_id,
        real_power=2000.0,
        current=16.0,
        voltage=voltage,
        frequency=frequency,
        leg_a_voltage=leg_a_voltage,
        leg_b_voltage=leg_b_voltage,
        quality_issues=quality_issues,
    )


def _context(
    minute: int,
    *,
    mature: bool,
    options: dict[str, object] | None = None,
    entry_data: dict[str, object] | None = None,
    store_data: FeatureStoreData | None = None,
) -> ProcessingContext:
    return ProcessingContext(
        now=_BASE_TIME + timedelta(minutes=minute),
        hass=SimpleNamespace(),
        state=SimpleNamespace(),
        store_data=store_data or FeatureStoreData(),
        options=options or {},
        entry_data=entry_data or {},
        known_load_circuit_ids=frozenset(),
        sensitivity="balanced",
        time_zone="UTC",
    )


def _prime_detector(
    detector: MainsPowerQualityDetector,
    count: int,
    *,
    voltage: float = 120.0,
    frequency: float = 60.0,
) -> None:
    for minute in range(count):
        result = detector.process(_sample(minute, voltage=voltage, frequency=frequency))
        assert result.events == ()


def test_mains_detector_tracks_preliminary_voltage_sag_without_emitting() -> None:
    detector = MainsPowerQualityDetector(
        MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
        )
    )
    _prime_detector(detector, 3)

    first = detector.process(_sample(3, voltage=109.0))
    second = detector.process(_sample(4, voltage=109.0))

    assert first.events == ()
    assert second.events == ()
    assert len(second.active_events) == 1
    event = second.active_events[0]
    assert event.event_type is EventType.VOLTAGE_SAG
    assert event.features["source"] == "mains_power_quality"
    assert event.features["channel"] == "voltage"
    assert event.features["voltage"] == 109.0
    assert event.features["nominal_voltage"] == 120.0
    assert event.features["sag_ratio"] > 0.08
    assert event.features["notification_eligible"] is False


def test_mains_detector_honors_single_sample_event_threshold() -> None:
    detector = MainsPowerQualityDetector(
        MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=3,
            min_event_samples=1,
            min_baseline_confidence=0.0,
        )
    )
    _prime_detector(detector, 3)

    result = detector.process(_sample(3, voltage=109.0))

    assert len(result.events) == 1
    assert result.events[0].event_type is EventType.VOLTAGE_SAG
    assert result.events[0].features["sample_count"] == 1
    assert result.events[0].features["notification_eligible"] is True


def test_mains_detector_emits_mature_voltage_swell_notification() -> None:
    detector = MainsPowerQualityDetector(
        MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
        )
    )
    _prime_detector(detector, 5)

    detector.process(_sample(5, voltage=132.0))
    result = detector.process(_sample(6, voltage=132.0))

    assert len(result.events) == 1
    event = result.events[0]
    assert event.event_type is EventType.VOLTAGE_SWELL
    assert event.features["channel"] == "voltage"
    assert event.features["swell_ratio"] == 0.1
    assert event.features["notification_eligible"] is True


def test_mains_detector_emits_frequency_drop_and_spike_events() -> None:
    drop_detector = MainsPowerQualityDetector(
        MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
        )
    )
    _prime_detector(drop_detector, 5)

    drop_detector.process(_sample(5, frequency=59.3))
    drop = drop_detector.process(_sample(6, frequency=59.3)).events[0]

    spike_detector = MainsPowerQualityDetector(
        MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
        )
    )
    _prime_detector(spike_detector, 5)

    spike_detector.process(_sample(5, frequency=60.7))
    spike = spike_detector.process(_sample(6, frequency=60.7)).events[0]

    assert drop.event_type is EventType.FREQUENCY_DROP
    assert drop.features["frequency_delta_hz"] == -0.7
    assert drop.features["notification_eligible"] is True
    assert spike.event_type is EventType.FREQUENCY_SPIKE
    assert spike.features["frequency_delta_hz"] == 0.7
    assert spike.features["notification_eligible"] is True


def test_mains_detector_emits_leg_voltage_imbalance_event() -> None:
    detector = MainsPowerQualityDetector(
        MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
            voltage_imbalance_ratio=0.03,
        )
    )
    for minute in range(5):
        result = detector.process(
            _sample(
                minute,
                voltage=None,
                leg_a_voltage=120.0,
                leg_b_voltage=120.0,
            )
        )
        assert result.events == ()

    first = detector.process(
        _sample(5, voltage=None, leg_a_voltage=117.0, leg_b_voltage=123.0)
    )
    second = detector.process(
        _sample(6, voltage=None, leg_a_voltage=117.0, leg_b_voltage=123.0)
    )

    assert first.events == ()
    assert len(second.events) == 1
    event = second.events[0]
    assert event.event_type is EventType.VOLTAGE_IMBALANCE
    assert event.features["channel"] == "leg_voltage_imbalance"
    assert event.features["metric"] == "voltage_imbalance"
    assert event.features["leg_a_voltage"] == 117.0
    assert event.features["leg_b_voltage"] == 123.0
    assert event.features["voltage_difference"] == 6.0
    assert event.features["voltage_imbalance_ratio"] == 0.05
    assert event.features["voltage_imbalance_threshold_ratio"] == 0.03
    assert event.features["notification_eligible"] is True


def test_mains_detector_keeps_healthy_leg_with_other_leg_quality_issue() -> None:
    detector = MainsPowerQualityDetector(
        MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
        )
    )
    for minute in range(5):
        result = detector.process(
            _sample(
                minute,
                voltage=None,
                leg_a_voltage=120.0,
                leg_b_voltage=120.0,
            )
        )
        assert result.events == ()

    detector.process(
        _sample(
            5,
            voltage=None,
            leg_a_voltage=109.0,
            leg_b_voltage=None,
            quality_issues=("sensor.mains_l2_voltage stale",),
        )
    )
    result = detector.process(
        _sample(
            6,
            voltage=None,
            leg_a_voltage=109.0,
            leg_b_voltage=None,
            quality_issues=("sensor.mains_l2_voltage stale",),
        )
    )

    assert len(result.events) == 1
    assert result.events[0].features["channel"] == "leg_a_voltage"


def test_mains_detector_keeps_healthy_leg_with_broad_voltage_quality_issue() -> None:
    detector = MainsPowerQualityDetector(
        MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
        )
    )
    for minute in range(5):
        result = detector.process(
            _sample(
                minute,
                voltage=None,
                leg_a_voltage=120.0,
                leg_b_voltage=120.0,
            )
        )
        assert result.events == ()

    detector.process(
        _sample(
            5,
            voltage=None,
            leg_a_voltage=109.0,
            leg_b_voltage=None,
            quality_issues=("sensor.panel_voltage stale",),
        )
    )
    result = detector.process(
        _sample(
            6,
            voltage=None,
            leg_a_voltage=109.0,
            leg_b_voltage=None,
            quality_issues=("sensor.panel_voltage stale",),
        )
    )

    assert len(result.events) == 1
    assert result.events[0].features["channel"] == "leg_a_voltage"


def test_mains_settings_parser_ignores_invalid_values() -> None:
    settings = mains_power_quality_settings_from_mapping(
        {
            "mains_voltage_sag_ratio": "not-a-number",
            "mains_voltage_swell_ratio": "0.09",
            "mains_frequency_drop_hz": "0.7",
            "mains_frequency_spike_hz": "0.8",
            "mains_voltage_imbalance_ratio": "0.04",
            "mains_notifications_enabled": "false",
        }
    )

    assert settings.voltage_sag_ratio == 0.08
    assert settings.voltage_swell_ratio == 0.09
    assert settings.frequency_drop_hz == 0.7
    assert settings.frequency_spike_hz == 0.8
    assert settings.voltage_imbalance_ratio == 0.04
    assert settings.notifications_enabled is False


def test_mains_processor_reads_entry_data_settings_with_option_override() -> None:
    processor = MainsPowerQualityProcessor(
        learning_mature=lambda _config, _now: True,
    )
    config = _mains_config_with_voltage_sensor()
    entry_data = {
        CONF_ADVANCED_SETTINGS: {
            "mains": {
                "preliminary_baseline_samples": 2,
                "min_baseline_samples": 3,
                "min_event_samples": 2,
                "min_baseline_confidence": 0.0,
            }
        }
    }
    options = {
        CONF_ADVANCED_SETTINGS: {
            "mains": {
                "min_event_samples": 3,
            }
        }
    }
    for minute in range(3):
        processor.process(
            _sample(minute),
            config,
            _context(
                minute,
                mature=True,
                entry_data=entry_data,
                options=options,
            ),
        )

    processor.process(
        _sample(3, voltage=109.0),
        config,
        _context(3, mature=True, entry_data=entry_data, options=options),
    )
    second_excursion = processor.process(
        _sample(4, voltage=109.0),
        config,
        _context(4, mature=True, entry_data=entry_data, options=options),
    )
    third_excursion = processor.process(
        _sample(5, voltage=109.0),
        config,
        _context(5, mature=True, entry_data=entry_data, options=options),
    )

    assert second_excursion.alerts == []
    assert len(third_excursion.alerts) == 1


def test_mains_processor_notifies_after_learning_maturity() -> None:
    processor = MainsPowerQualityProcessor(
        learning_mature=lambda _config, _now: True,
        settings_for_config=lambda _config, _context: MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
        ),
    )
    config = _mains_config_with_voltage_sensor()
    for minute in range(5):
        result = processor.process(
            _sample(minute),
            config,
            _context(minute, mature=True),
        )
        assert result.events == []
        assert result.notifications == []

    processor.process(_sample(5, voltage=109.0), config, _context(5, mature=True))
    result = processor.process(
        _sample(6, voltage=109.0),
        config,
        _context(6, mature=True),
    )

    assert len(result.events) == 1
    assert len(result.alerts) == 1
    assert result.notifications == result.alerts
    alert = result.alerts[0]
    assert alert.event_type is EventType.VOLTAGE_SAG
    assert alert.feature == "voltage_sag"
    assert alert.value_metric == "voltage"
    assert alert.observed_value == 109.0
    assert alert.baseline_value == 120.0
    assert "voltage sag" in alert.message.lower()


def test_mains_processor_notifies_for_leg_voltage_imbalance_after_learning() -> None:
    processor = MainsPowerQualityProcessor(
        learning_mature=lambda _config, _now: True,
        settings_for_config=lambda _config, _context: MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
            voltage_imbalance_ratio=0.03,
        ),
    )
    config = _mains_config_with_leg_voltage_sensors()
    for minute in range(5):
        processor.process(
            _sample(
                minute,
                voltage=None,
                leg_a_voltage=120.0,
                leg_b_voltage=120.0,
            ),
            config,
            _context(minute, mature=True),
        )

    processor.process(
        _sample(5, voltage=None, leg_a_voltage=117.0, leg_b_voltage=123.0),
        config,
        _context(5, mature=True),
    )
    result = processor.process(
        _sample(6, voltage=None, leg_a_voltage=117.0, leg_b_voltage=123.0),
        config,
        _context(6, mature=True),
    )

    assert len(result.alerts) == 1
    assert result.notifications == result.alerts
    alert = result.alerts[0]
    assert alert.event_type is EventType.VOLTAGE_IMBALANCE
    assert alert.feature == "voltage_imbalance"
    assert alert.value_metric == "voltage_imbalance"
    assert alert.observed_value == 0.05
    assert alert.baseline_value == 0.03
    assert alert.features["notification_key"] == "leg_voltage_imbalance"
    assert "voltage imbalance" in alert.message.lower()
    assert "117.0 V" in alert.message
    assert "123.0 V" in alert.message


def test_mains_processor_accepts_alias_leg_names_for_voltage_imbalance() -> None:
    processor = MainsPowerQualityProcessor(
        learning_mature=lambda _config, _now: True,
        settings_for_config=lambda _config, _context: MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
            voltage_imbalance_ratio=0.03,
        ),
    )
    config = _mains_config_with_alias_leg_voltage_sensors()
    for minute in range(5):
        processor.process(
            _sample(
                minute,
                voltage=None,
                leg_a_voltage=120.0,
                leg_b_voltage=120.0,
            ),
            config,
            _context(minute, mature=True),
        )

    processor.process(
        _sample(5, voltage=None, leg_a_voltage=117.0, leg_b_voltage=123.0),
        config,
        _context(5, mature=True),
    )
    result = processor.process(
        _sample(6, voltage=None, leg_a_voltage=117.0, leg_b_voltage=123.0),
        config,
        _context(6, mature=True),
    )

    assert len(result.alerts) == 1
    assert result.alerts[0].event_type is EventType.VOLTAGE_IMBALANCE


def test_mains_processor_skips_voltage_imbalance_without_two_voltage_sensors() -> None:
    processor = MainsPowerQualityProcessor(
        learning_mature=lambda _config, _now: True,
        settings_for_config=lambda _config, _context: MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
            voltage_imbalance_ratio=0.03,
        ),
    )
    config = _mains_config_with_voltage_sensor()
    for minute in range(5):
        processor.process(
            _sample(
                minute,
                voltage=None,
                leg_a_voltage=120.0,
                leg_b_voltage=120.0,
            ),
            config,
            _context(minute, mature=True),
        )

    processor.process(
        _sample(5, voltage=None, leg_a_voltage=117.0, leg_b_voltage=123.0),
        config,
        _context(5, mature=True),
    )
    result = processor.process(
        _sample(6, voltage=None, leg_a_voltage=117.0, leg_b_voltage=123.0),
        config,
        _context(6, mature=True),
    )

    assert result.events == []
    assert result.alerts == []
    assert result.notifications == []


def test_mains_processor_clears_voltage_imbalance_when_voltage_sensors_removed(
) -> None:
    processor = MainsPowerQualityProcessor(
        learning_mature=lambda _config, _now: True,
        settings_for_config=lambda _config, _context: MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
            voltage_imbalance_ratio=0.03,
        ),
    )
    two_leg_config = _mains_config_with_leg_voltage_sensors()
    for minute in range(5):
        processor.process(
            _sample(
                minute,
                voltage=None,
                leg_a_voltage=120.0,
                leg_b_voltage=120.0,
            ),
            two_leg_config,
            _context(minute, mature=True),
        )

    processor.process(
        _sample(5, voltage=None, leg_a_voltage=117.0, leg_b_voltage=123.0),
        two_leg_config,
        _context(5, mature=True),
    )
    active = processor.process(
        _sample(6, voltage=None, leg_a_voltage=117.0, leg_b_voltage=123.0),
        two_leg_config,
        _context(6, mature=True),
    )
    assert len(active.alerts) == 1

    one_leg_config = _mains_config()
    result = processor.process(
        _sample(7, voltage=None, leg_a_voltage=117.0, leg_b_voltage=123.0),
        one_leg_config,
        _context(7, mature=True),
    )

    assert result.events == []
    assert result.alerts == []
    assert result.preserved_alerts == []
    assert result.notifications == []


def test_mains_processor_reads_store_backed_voltage_imbalance_setting() -> None:
    processor = MainsPowerQualityProcessor(
        learning_mature=lambda _config, _now: True,
    )
    config = _mains_config_with_leg_voltage_sensors()
    store_data = FeatureStoreData(
        mains_power_quality_settings_by_circuit={
            "mains": {"voltage_imbalance_ratio": 0.10}
        }
    )
    for minute in range(5):
        processor.process(
            _sample(
                minute,
                voltage=None,
                leg_a_voltage=120.0,
                leg_b_voltage=120.0,
            ),
            config,
            _context(minute, mature=True, store_data=store_data),
        )

    processor.process(
        _sample(5, voltage=None, leg_a_voltage=117.0, leg_b_voltage=123.0),
        config,
        _context(5, mature=True, store_data=store_data),
    )
    result = processor.process(
        _sample(6, voltage=None, leg_a_voltage=117.0, leg_b_voltage=123.0),
        config,
        _context(6, mature=True, store_data=store_data),
    )

    assert result.events == []
    assert result.alerts == []
    assert result.notifications == []


def test_mains_processor_skips_events_until_detector_baseline_is_mature() -> None:
    processor = MainsPowerQualityProcessor(
        learning_mature=lambda _config, _now: True,
        settings_for_config=lambda _config, _context: MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=10,
            min_event_samples=2,
            min_baseline_confidence=0.0,
        ),
    )
    store_data = FeatureStoreData()
    config = _mains_config_with_voltage_sensor()
    for minute in range(3):
        processor.process(
            _sample(minute, voltage=120.0),
            config,
            _context(minute, mature=True, store_data=store_data),
        )

    processor.process(
        _sample(3, voltage=109.0),
        config,
        _context(3, mature=True, store_data=store_data),
    )
    result = processor.process(
        _sample(4, voltage=109.0),
        config,
        _context(4, mature=True, store_data=store_data),
    )

    assert result.events == []
    assert result.alerts == []
    assert result.notifications == []
    assert store_data.events == []


def test_mains_processor_skips_voltage_imbalance_until_baseline_is_mature() -> None:
    processor = MainsPowerQualityProcessor(
        learning_mature=lambda _config, _now: True,
        settings_for_config=lambda _config, _context: MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=10,
            min_event_samples=2,
            min_baseline_confidence=0.0,
            voltage_imbalance_ratio=0.03,
        ),
    )
    store_data = FeatureStoreData()
    config = _mains_config_with_leg_voltage_sensors()
    for minute in range(3):
        processor.process(
            _sample(
                minute,
                voltage=None,
                leg_a_voltage=120.0,
                leg_b_voltage=120.0,
            ),
            config,
            _context(minute, mature=True, store_data=store_data),
        )

    processor.process(
        _sample(3, voltage=None, leg_a_voltage=117.0, leg_b_voltage=123.0),
        config,
        _context(3, mature=True, store_data=store_data),
    )
    result = processor.process(
        _sample(4, voltage=None, leg_a_voltage=117.0, leg_b_voltage=123.0),
        config,
        _context(4, mature=True, store_data=store_data),
    )

    assert result.events == []
    assert result.alerts == []
    assert result.notifications == []
    assert store_data.events == []


def test_mains_processor_skips_voltage_and_frequency_without_configured_sensors(
) -> None:
    processor = MainsPowerQualityProcessor(
        learning_mature=lambda _config, _now: True,
        settings_for_config=lambda _config, _context: MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
        ),
    )
    config = _mains_config()
    for minute in range(5):
        processor.process(
            _sample(minute, voltage=120.0, frequency=60.0),
            config,
            _context(minute, mature=True),
        )

    processor.process(
        _sample(5, voltage=109.0, frequency=59.3),
        config,
        _context(5, mature=True),
    )
    result = processor.process(
        _sample(6, voltage=109.0, frequency=59.3),
        config,
        _context(6, mature=True),
    )

    assert result.events == []
    assert result.alerts == []
    assert result.preserved_alerts == []
    assert result.notifications == []


def test_mains_processor_clears_voltage_and_frequency_alerts_when_sensors_removed(
) -> None:
    processor = MainsPowerQualityProcessor(
        learning_mature=lambda _config, _now: True,
        settings_for_config=lambda _config, _context: MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
        ),
    )
    configured = _mains_config_with_power_quality_sensors()
    for minute in range(5):
        processor.process(
            _sample(minute, voltage=120.0, frequency=60.0),
            configured,
            _context(minute, mature=True),
        )

    processor.process(
        _sample(5, voltage=109.0, frequency=59.3),
        configured,
        _context(5, mature=True),
    )
    active = processor.process(
        _sample(6, voltage=109.0, frequency=59.3),
        configured,
        _context(6, mature=True),
    )
    assert {alert.event_type for alert in active.alerts} == {
        EventType.VOLTAGE_SAG,
        EventType.FREQUENCY_DROP,
    }

    result = processor.process(
        _sample(7, voltage=109.0, frequency=59.3),
        _mains_config(),
        _context(7, mature=True),
    )

    assert result.events == []
    assert result.alerts == []
    assert result.preserved_alerts == []
    assert result.notifications == []


def test_mains_processor_preserves_alert_until_recovery() -> None:
    processor = MainsPowerQualityProcessor(
        learning_mature=lambda _config, _now: True,
        settings_for_config=lambda _config, _context: MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            recovery_samples=2,
            min_baseline_confidence=0.0,
        ),
    )
    config = _mains_config_with_voltage_sensor()
    for minute in range(5):
        processor.process(_sample(minute), config, _context(minute, mature=True))

    processor.process(_sample(5, voltage=109.0), config, _context(5, mature=True))
    emitted = processor.process(
        _sample(6, voltage=109.0),
        config,
        _context(6, mature=True),
    )
    ongoing = processor.process(
        _sample(7, voltage=109.0),
        config,
        _context(7, mature=True),
    )
    first_recovery = processor.process(
        _sample(8, voltage=120.0),
        config,
        _context(8, mature=True),
    )
    recovered = processor.process(
        _sample(9, voltage=120.0),
        config,
        _context(9, mature=True),
    )

    assert len(emitted.alerts) == 1
    assert ongoing.alerts == []
    assert len(ongoing.preserved_alerts) == 1
    assert ongoing.preserved_alerts[0].event_type is EventType.VOLTAGE_SAG
    assert len(first_recovery.preserved_alerts) == 1
    assert recovered.preserved_alerts == []


def test_mains_processor_preserves_active_alert_across_missing_sample() -> None:
    processor = MainsPowerQualityProcessor(
        learning_mature=lambda _config, _now: True,
        settings_for_config=lambda _config, _context: MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            recovery_samples=2,
            min_baseline_confidence=0.0,
        ),
    )
    config = _mains_config_with_voltage_sensor()
    for minute in range(5):
        processor.process(_sample(minute), config, _context(minute, mature=True))

    processor.process(_sample(5, voltage=109.0), config, _context(5, mature=True))
    emitted = processor.process(
        _sample(6, voltage=109.0),
        config,
        _context(6, mature=True),
    )
    missing = processor.process(
        _sample(
            7,
            voltage=None,
            quality_issues=("sensor.mains_voltage stale",),
        ),
        config,
        _context(7, mature=True),
    )
    first_recovery = processor.process(
        _sample(8, voltage=120.0),
        config,
        _context(8, mature=True),
    )
    recovered = processor.process(
        _sample(9, voltage=120.0),
        config,
        _context(9, mature=True),
    )

    assert len(emitted.alerts) == 1
    assert missing.alerts == []
    assert len(missing.preserved_alerts) == 1
    assert missing.preserved_alerts[0].event_type is EventType.VOLTAGE_SAG
    assert len(first_recovery.preserved_alerts) == 1
    assert recovered.preserved_alerts == []


def test_mains_processor_uses_channel_specific_notification_keys() -> None:
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        notification_id_for_alert,
    )

    processor = MainsPowerQualityProcessor(
        learning_mature=lambda _config, _now: True,
        settings_for_config=lambda _config, _context: MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
        ),
    )
    config = _mains_config_with_leg_voltage_sensors()
    for minute in range(5):
        processor.process(
            _sample(
                minute,
                voltage=120.0,
                leg_a_voltage=120.0,
                leg_b_voltage=120.0,
            ),
            config,
            _context(minute, mature=True),
        )

    processor.process(
        _sample(5, voltage=109.0, leg_a_voltage=109.0, leg_b_voltage=109.0),
        config,
        _context(5, mature=True),
    )
    result = processor.process(
        _sample(6, voltage=109.0, leg_a_voltage=109.0, leg_b_voltage=109.0),
        config,
        _context(6, mature=True),
    )

    assert len(result.alerts) == 2
    assert {
        alert.features["notification_key"] for alert in result.alerts
    } == {
        "leg_a_voltage",
        "leg_b_voltage",
    }
    assert "voltage" not in {
        alert.features["notification_key"] for alert in result.alerts
    }
    assert len({notification_id_for_alert(alert) for alert in result.alerts}) == 2


def test_mains_processor_suppresses_notifications_while_learning() -> None:
    processor = MainsPowerQualityProcessor(
        learning_mature=lambda _config, _now: False,
        settings_for_config=lambda _config, _context: MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
        ),
    )
    config = _mains_config_with_frequency_sensor()
    for minute in range(5):
        processor.process(_sample(minute), config, _context(minute, mature=False))

    processor.process(_sample(5, frequency=59.3), config, _context(5, mature=False))
    result = processor.process(
        _sample(6, frequency=59.3),
        config,
        _context(6, mature=False),
    )

    assert result.events == []
    assert result.alerts == []
    assert result.notifications == []


def test_mains_processor_emits_event_when_learning_matures_during_excursion() -> None:
    processor = MainsPowerQualityProcessor(
        learning_mature=lambda _config, now: now >= _BASE_TIME + timedelta(minutes=7),
        settings_for_config=lambda _config, _context: MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
        ),
    )
    config = _mains_config_with_frequency_sensor()
    for minute in range(5):
        processor.process(_sample(minute), config, _context(minute, mature=False))

    processor.process(_sample(5, frequency=59.3), config, _context(5, mature=False))
    immature = processor.process(
        _sample(6, frequency=59.3),
        config,
        _context(6, mature=False),
    )
    mature = processor.process(
        _sample(7, frequency=59.3),
        config,
        _context(7, mature=True),
    )

    assert immature.events == []
    assert immature.alerts == []
    assert len(mature.events) == 1
    assert mature.events[0].event_type is EventType.FREQUENCY_DROP
    assert len(mature.alerts) == 1
    assert mature.notifications == mature.alerts


def test_coordinator_mains_quality_emits_after_learning_age_without_cycles() -> None:
    store_data = FeatureStoreData(
        learning_started_at_by_circuit={
            "mains": (_BASE_TIME - timedelta(days=8)).isoformat(),
        },
        mains_power_quality_settings_by_circuit={
            "mains": {
                "preliminary_baseline_samples": 3,
                "min_baseline_samples": 5,
                "min_event_samples": 2,
                "min_baseline_confidence": 0.0,
            },
        },
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [
                        {
                            "entity_id": "sensor.mains_frequency",
                            "role": "frequency",
                        }
                    ],
                }
            ],
        },
        store_data=store_data,
        now_fn=lambda: _BASE_TIME,
    )
    config = coordinator.circuit_configs[0]

    for minute in range(5):
        coordinator._mains_power_quality_processor.process(
            _sample(minute),
            config,
            _context(minute, mature=True, store_data=store_data),
        )

    coordinator._mains_power_quality_processor.process(
        _sample(5, frequency=59.3),
        config,
        _context(5, mature=True, store_data=store_data),
    )
    result = coordinator._mains_power_quality_processor.process(
        _sample(6, frequency=59.3),
        config,
        _context(6, mature=True, store_data=store_data),
    )

    assert coordinator.processor_runtime.learning_events_since_restart(
        config,
        _BASE_TIME + timedelta(minutes=6),
    ) == []
    assert len(result.events) == 1
    assert result.events[0].event_type is EventType.FREQUENCY_DROP
    assert len(result.alerts) == 1
    assert result.notifications == result.alerts


def test_coordinator_mains_quality_blocks_start_cycle_maturity_shortcut() -> None:
    minimum_cycles = get_profile_definition(ApplianceProfile.MAINS_NILM).minimum_cycles
    store_data = FeatureStoreData(
        events=[
            CircuitEvent(
                timestamp=_BASE_TIME - timedelta(minutes=index),
                circuit_id="mains",
                event_type=EventType.START,
            )
            for index in range(minimum_cycles)
        ],
        learning_started_at_by_circuit={
            "mains": (_BASE_TIME - timedelta(days=1)).isoformat(),
        },
        mains_power_quality_settings_by_circuit={
            "mains": {
                "preliminary_baseline_samples": 3,
                "min_baseline_samples": 5,
                "min_event_samples": 2,
                "min_baseline_confidence": 0.0,
            },
        },
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "sensors": [
                        {
                            "entity_id": "sensor.mains_frequency",
                            "role": "frequency",
                        }
                    ],
                }
            ],
        },
        store_data=store_data,
        now_fn=lambda: _BASE_TIME,
    )
    config = coordinator.circuit_configs[0]

    assert coordinator.processor_runtime.learning_mature(config, _BASE_TIME)
    assert not coordinator.processor_runtime.mains_power_quality_learning_mature(
        config,
        _BASE_TIME,
    )

    for minute in range(5):
        coordinator._mains_power_quality_processor.process(
            _sample(minute),
            config,
            _context(minute, mature=True, store_data=store_data),
        )

    coordinator._mains_power_quality_processor.process(
        _sample(5, frequency=59.3),
        config,
        _context(5, mature=True, store_data=store_data),
    )
    result = coordinator._mains_power_quality_processor.process(
        _sample(6, frequency=59.3),
        config,
        _context(6, mature=True, store_data=store_data),
    )

    assert result.events == []
    assert result.alerts == []
    assert result.notifications == []


def test_mains_power_quality_processor_ignores_direct_appliances() -> None:
    processor = MainsPowerQualityProcessor(
        learning_mature=lambda _config, _now: True,
        settings_for_config=lambda _config, _context: MainsPowerQualitySettings(
            preliminary_baseline_samples=3,
            min_baseline_samples=5,
            min_event_samples=2,
            min_baseline_confidence=0.0,
        ),
    )
    config = _appliance_config()

    for minute in range(7):
        result = processor.process(
            _sample(minute, circuit_id="dryer", voltage=109.0),
            config,
            _context(minute, mature=True),
        )

    assert result.events == []
    assert result.alerts == []
