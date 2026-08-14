"""Processor wrapper for mains voltage and frequency excursions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..const import CONF_ADVANCED_SETTINGS
from ..mains_power_quality import (
    MainsPowerQualityDetector,
    MainsPowerQualitySettings,
    mains_power_quality_settings_from_mapping,
)
from ..managers.source_samples import entity_id_leg_hint, normalized_leg
from ..models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
    SensorRole,
    Severity,
)
from ..normalize import NormalizedCircuitSample
from .base import FeatureResult, ProcessingContext

type LearningMaturePredicate = Callable[[CircuitConfig, datetime], bool]
type MainsPowerQualitySettingsProvider = Callable[
    [CircuitConfig, ProcessingContext],
    MainsPowerQualitySettings,
]


@dataclass(slots=True)
class _DetectorSlot:
    settings: MainsPowerQualitySettings
    detector: MainsPowerQualityDetector


class MainsPowerQualityProcessor:
    """Detect and alert on mains voltage/frequency quality events."""

    name = "mains_power_quality"

    def __init__(
        self,
        *,
        learning_mature: LearningMaturePredicate,
        settings_for_config: MainsPowerQualitySettingsProvider | None = None,
        detectors: MutableMapping[str, _DetectorSlot] | None = None,
    ) -> None:
        self._learning_mature = learning_mature
        self._settings_for_config = (
            settings_for_config or _settings_from_context_options
        )
        self._detectors = detectors if detectors is not None else {}
        self._last_alert_at: dict[tuple[str, str, EventType], datetime] = {}
        self._active_alerts: dict[tuple[str, str, EventType], AlertEvidence] = {}

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Return mains power-quality events and matured notification alerts."""
        if not _is_mains_config(circuit_config):
            return FeatureResult()

        settings = self._settings_for_config(circuit_config, context)
        detector = self._detector_for(circuit_config.circuit_id, settings)
        allowed_voltage_channels = _voltage_channels_for_config(circuit_config)
        learning_mature = self._learning_mature(circuit_config, context.now)
        detection = detector.process(
            sample,
            allowed_voltage_channels=allowed_voltage_channels,
            detect_frequency=_has_sensor_role(circuit_config, SensorRole.FREQUENCY),
            detect_leg_voltage_imbalance=_has_two_leg_voltage_sensors(circuit_config),
            emit_events=learning_mature,
        )
        if not learning_mature:
            return FeatureResult()

        if not detection.events:
            result = FeatureResult()
        else:
            result = FeatureResult(
                events=list(detection.events),
                store_dirty=True,
            )

        active_keys = {_alert_key(event) for event in detection.active_events}
        for key in list(self._active_alerts):
            if key[0] == circuit_config.circuit_id and key not in active_keys:
                self._active_alerts.pop(key, None)

        for event in detection.active_events:
            if not event.features.get("notification_eligible"):
                continue
            alert = _alert_for_event(circuit_config, event)
            key = _alert_key(event)
            if key in self._active_alerts:
                self._active_alerts[key] = alert
                result.preserved_alerts.append(alert)
                continue

            self._active_alerts[key] = alert
            if self._notification_cooldown_allows(event, settings):
                result.alerts.append(alert)
                result.notifications.append(alert)
            else:
                result.preserved_alerts.append(alert)
        return result

    def _detector_for(
        self,
        circuit_id: str,
        settings: MainsPowerQualitySettings,
    ) -> MainsPowerQualityDetector:
        slot = self._detectors.get(circuit_id)
        if slot is None or slot.settings != settings:
            slot = _DetectorSlot(
                settings=settings,
                detector=MainsPowerQualityDetector(settings),
            )
            self._detectors[circuit_id] = slot
        return slot.detector

    def _notification_cooldown_allows(
        self,
        event: CircuitEvent,
        settings: MainsPowerQualitySettings,
    ) -> bool:
        channel = str(event.features.get("channel") or "")
        key = (event.circuit_id, channel, event.event_type)
        previous = self._last_alert_at.get(key)
        if previous is not None:
            elapsed = (event.timestamp - previous).total_seconds()
            if elapsed < settings.cooldown_seconds:
                return False
        self._last_alert_at[key] = event.timestamp
        return True


def _alert_for_event(
    circuit_config: CircuitConfig,
    event: CircuitEvent,
) -> AlertEvidence:
    value_metric = str(event.features.get("metric") or "")
    observed = _float_feature(event, "observed_value")
    baseline = _float_feature(event, "baseline_value")
    change_ratio = _float_feature(event, "deviation_ratio")
    channel = str(event.features.get("channel") or value_metric)
    first_seen = _datetime_feature(event, "first_seen") or event.timestamp
    last_seen = _datetime_feature(event, "last_seen") or event.timestamp
    message = _message_for_event(circuit_config, event, channel, observed, baseline)
    features = dict(event.features)
    features["notification_key"] = channel
    return AlertEvidence(
        timestamp=event.timestamp,
        circuit_id=event.circuit_id,
        severity=Severity.WARNING,
        message=message,
        event_type=event.event_type,
        feature=event.event_type.value,
        value_metric=value_metric,
        observed_value=observed,
        baseline_value=baseline,
        change_ratio=change_ratio,
        repeated_count=int(event.features.get("sample_count") or 1),
        first_seen=first_seen,
        last_seen=last_seen,
        features=features,
    )


def _alert_key(event: CircuitEvent) -> tuple[str, str, EventType]:
    return (
        event.circuit_id,
        str(event.features.get("channel") or ""),
        event.event_type,
    )


def _message_for_event(
    circuit_config: CircuitConfig,
    event: CircuitEvent,
    channel: str,
    observed: float,
    baseline: float,
) -> str:
    name = circuit_config.name or circuit_config.circuit_id
    channel_label = channel.replace("_", " ")
    if event.event_type is EventType.VOLTAGE_SAG:
        return (
            f"{name} voltage sag detected on {channel_label}: "
            f"{observed:.1f} V versus {baseline:.1f} V baseline."
        )
    if event.event_type is EventType.VOLTAGE_SWELL:
        return (
            f"{name} voltage swell detected on {channel_label}: "
            f"{observed:.1f} V versus {baseline:.1f} V baseline."
        )
    if event.event_type is EventType.VOLTAGE_IMBALANCE:
        leg_a_voltage = _float_feature(event, "leg_a_voltage")
        leg_b_voltage = _float_feature(event, "leg_b_voltage")
        return (
            f"{name} voltage imbalance detected: "
            f"leg A is {leg_a_voltage:.1f} V and leg B is {leg_b_voltage:.1f} V "
            f"({observed * 100.0:.1f}% difference), above the configured "
            f"{baseline * 100.0:.1f}% threshold."
        )
    if event.event_type is EventType.FREQUENCY_DROP:
        return (
            f"{name} frequency drop detected: "
            f"{observed:.2f} Hz versus {baseline:.2f} Hz baseline."
        )
    return (
        f"{name} frequency spike detected: "
        f"{observed:.2f} Hz versus {baseline:.2f} Hz baseline."
    )


def _settings_from_context_options(
    circuit_config: CircuitConfig,
    context: ProcessingContext,
) -> MainsPowerQualitySettings:
    raw_settings: dict[str, Any] = {}
    raw_settings.update(
        _per_circuit_advanced_settings(context.entry_data, circuit_config.circuit_id)
    )
    raw_settings.update(
        _per_circuit_advanced_settings(context.options, circuit_config.circuit_id)
    )
    raw_settings.update(_store_backed_settings(context, circuit_config.circuit_id))
    return mains_power_quality_settings_from_mapping(raw_settings)


def _per_circuit_advanced_settings(
    source: Mapping[str, Any],
    circuit_id: str,
) -> Mapping[str, Any]:
    advanced = source.get(CONF_ADVANCED_SETTINGS, {})
    if not isinstance(advanced, Mapping):
        return {}
    raw_settings = advanced.get(circuit_id, {})
    if not isinstance(raw_settings, Mapping):
        return {}
    return raw_settings


def _is_mains_config(config: CircuitConfig) -> bool:
    return (
        config.mode is CircuitMode.MAINS_NILM
        or config.appliance_profile is ApplianceProfile.MAINS_NILM
    )


def _has_two_leg_voltage_sensors(config: CircuitConfig) -> bool:
    channels = _voltage_channels_for_config(config)
    return {"leg_a_voltage", "leg_b_voltage"}.issubset(channels)


def _has_sensor_role(config: CircuitConfig, role: SensorRole) -> bool:
    return any(sensor.role is role for sensor in config.sensors)


def _voltage_channels_for_config(config: CircuitConfig) -> frozenset[str]:
    channels: set[str] = set()
    for sensor in config.sensors:
        if sensor.role is not SensorRole.VOLTAGE:
            continue
        leg = normalized_leg(sensor.leg) or entity_id_leg_hint(sensor.entity_id)
        if leg == "a":
            channels.add("leg_a_voltage")
        elif leg == "b":
            channels.add("leg_b_voltage")
        else:
            channels.add("voltage")
    return frozenset(channels)


def _store_backed_settings(
    context: ProcessingContext,
    circuit_id: str,
) -> Mapping[str, Any]:
    settings_by_circuit = getattr(
        context.store_data,
        "mains_power_quality_settings_by_circuit",
        {},
    )
    if not isinstance(settings_by_circuit, Mapping):
        return {}
    raw_settings = settings_by_circuit.get(circuit_id, {})
    if not isinstance(raw_settings, Mapping):
        return {}
    return raw_settings


def _float_feature(event: CircuitEvent, key: str) -> float:
    try:
        return float(event.features.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _datetime_feature(event: CircuitEvent, key: str) -> datetime | None:
    value = event.features.get(key)
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
