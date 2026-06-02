from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Self

from . import notifications
from .alerting import ConservativeAlertPolicy, Observation
from .baseline import build_baseline, score_deviation
from .const import CONF_CIRCUITS, DOMAIN
from .events import CircuitEventDetector
from .models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    RetentionMode,
    SensorRef,
    SensorRole,
)
from .normalize import SourceState, build_circuit_sample
from .storage import FeatureStoreData

_LOGGER = logging.getLogger(__name__)

try:
    from homeassistant.helpers.event import async_track_state_change_event
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
except ModuleNotFoundError:
    async_track_state_change_event = None

    class DataUpdateCoordinator:
        """Small fallback so helper tests can import without Home Assistant."""

        def __init__(
            self,
            hass: Any,
            logger: logging.Logger | None = None,
            *,
            name: str | None = None,
            **_: Any,
        ) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.data: Any = None

        def async_set_updated_data(self, data: Any) -> None:
            self.data = data


@dataclass(slots=True)
class AnalyzerState:
    """Runtime state exposed by the energy analyzer coordinator."""

    last_event_by_circuit: dict[str, CircuitEvent] = field(default_factory=dict)
    active_alerts_by_circuit: dict[str, list[AlertEvidence]] = field(
        default_factory=dict
    )
    anomaly_score_by_circuit: dict[str, float] = field(default_factory=dict)
    learning_by_circuit: dict[str, bool] = field(default_factory=dict)
    data_quality_by_circuit: dict[str, str] = field(default_factory=dict)
    nilm_signature_count_by_circuit: dict[str, int] = field(default_factory=dict)
    nilm_unmatched_load_percentage_by_circuit: dict[str, float] = field(
        default_factory=dict
    )


def process_events_into_state(
    state: AnalyzerState,
    events: Iterable[CircuitEvent],
    alerts: Iterable[AlertEvidence],
) -> AnalyzerState:
    """Fold newly detected events and alerts into analyzer runtime state."""
    for event in events:
        previous = state.last_event_by_circuit.get(event.circuit_id)
        if previous is None or event.timestamp >= previous.timestamp:
            state.last_event_by_circuit[event.circuit_id] = event

    alerts_by_circuit: defaultdict[str, list[AlertEvidence]] = defaultdict(list)
    for alert in alerts:
        alerts_by_circuit[alert.circuit_id].append(alert)

    state.active_alerts_by_circuit = dict(alerts_by_circuit)
    state.anomaly_score_by_circuit = {
        circuit_id: max(_alert_anomaly_score(alert) for alert in circuit_alerts)
        for circuit_id, circuit_alerts in alerts_by_circuit.items()
    }

    for circuit_id in state.last_event_by_circuit:
        state.anomaly_score_by_circuit.setdefault(circuit_id, 0.0)

    return state


def _alert_anomaly_score(alert: AlertEvidence) -> float:
    if alert.change_ratio != 0.0:
        return abs(alert.change_ratio)

    if alert.baseline_value != 0.0:
        return abs((alert.observed_value - alert.baseline_value) / alert.baseline_value)

    return abs(alert.observed_value)


class EnergyAnalyzerCoordinator(DataUpdateCoordinator):
    """Runtime coordinator for source sensor updates and analyzer state."""

    def __init__(
        self: Self,
        hass: Any,
        *,
        entry_id: str = "default",
        entry_data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        store_data: FeatureStoreData | None = None,
        now_fn: Any | None = None,
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN)
        self.entry_id = entry_id
        self.entry_data = entry_data or {}
        self.options = options or {}
        self.store_data = store_data or FeatureStoreData()
        self.circuit_configs = _circuit_configs_from_entry_data(self.entry_data)
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._detectors = {
            config.circuit_id: CircuitEventDetector()
            for config in self.circuit_configs
        }
        self._alert_policy = ConservativeAlertPolicy()
        self._baseline_values: defaultdict[str, list[float]] = defaultdict(list)
        self._notified_alert_ids: set[str] = set()
        self.paused_circuits: set[str] = set()
        self.ignored_nilm_signatures: set[tuple[str, str]] = set()
        self.last_exported_diagnostics: dict[str, Any] = {}
        self.mapping_checks_run = 0
        self.state = AnalyzerState()
        self.source_entities: tuple[str, ...] = ()
        self.started = False
        self._unsub_state_change: Any = None
        self.async_set_updated_data(self.state)

    async def async_start(self: Self, source_entities: Iterable[str]) -> None:
        """Start listening to configured source entity state changes."""
        if self._unsub_state_change is not None:
            self._unsub_state_change()
            self._unsub_state_change = None

        self.source_entities = tuple(source_entities)
        self.started = True

        if async_track_state_change_event is None or not self.source_entities:
            return

        self._unsub_state_change = async_track_state_change_event(
            self.hass,
            list(self.source_entities),
            self._async_handle_source_state_change,
        )

    async def async_stop(self: Self) -> None:
        """Stop listening to source entity state changes."""
        if self._unsub_state_change is not None:
            self._unsub_state_change()
            self._unsub_state_change = None
        self.started = False

    async def _async_handle_source_state_change(self: Self, event: Any) -> None:
        """Handle Home Assistant source state changes.

        The analysis pipeline is intentionally staged behind this callback; Task 11
        establishes the runtime coordinator surface that later tasks can feed.
        """
        await self.async_process_update()

    async def async_process_update(self: Self) -> AnalyzerState:
        """Process current HA source states through the analyzer pipeline."""
        now = self._now_fn()
        events: list[CircuitEvent] = []
        alerts: list[AlertEvidence] = []

        for config in self.circuit_configs:
            sample = build_circuit_sample(
                config,
                self._source_states_for(config, now),
                now,
            )
            if sample.quality_issues:
                self.state.data_quality_by_circuit[config.circuit_id] = (
                    sample.quality_issues[0]
                )
            else:
                self.state.data_quality_by_circuit.pop(config.circuit_id, None)

            detector = self._detectors.setdefault(
                config.circuit_id,
                CircuitEventDetector(),
            )
            events.extend(detector.process(sample))

            alert = self._observe_real_power(config, sample, now)
            if alert is not None:
                alerts.append(alert)
                self.store_data.alerts.append(alert)
                await self._notify_alert(alert)

        process_events_into_state(self.state, events, alerts)
        self.async_set_updated_data(self.state)
        return self.state

    async def async_relearn_baseline(self: Self, circuit_id: str) -> None:
        """Clear learned baselines and alert state for one circuit."""
        prefix = f"{circuit_id}:"
        self.store_data.baselines = {
            key: value
            for key, value in self.store_data.baselines.items()
            if not key.startswith(prefix)
        }
        for key in list(self._baseline_values):
            if key.startswith(prefix):
                self._baseline_values.pop(key, None)
        self.store_data.alerts = [
            alert for alert in self.store_data.alerts if alert.circuit_id != circuit_id
        ]
        self.state.active_alerts_by_circuit.pop(circuit_id, None)
        self.state.anomaly_score_by_circuit[circuit_id] = 0.0
        self.state.learning_by_circuit[circuit_id] = True
        self.async_set_updated_data(self.state)

    async def async_pause_alerts(
        self: Self,
        circuit_id: str,
        duration: str | None = None,
    ) -> None:
        """Pause alert notifications for a circuit."""
        self.paused_circuits.add(circuit_id)

    async def async_acknowledge_alert(self: Self, alert_id: str) -> None:
        """Acknowledge an active alert evidence item."""
        self.store_data.alerts = [
            alert
            for alert in self.store_data.alerts
            if notifications.notification_id_for_alert(alert) != alert_id
        ]
        self.state.active_alerts_by_circuit = {
            circuit_id: [
                alert
                for alert in alerts
                if notifications.notification_id_for_alert(alert) != alert_id
            ]
            for circuit_id, alerts in self.state.active_alerts_by_circuit.items()
        }
        self.state.active_alerts_by_circuit = {
            circuit_id: alerts
            for circuit_id, alerts in self.state.active_alerts_by_circuit.items()
            if alerts
        }
        self.state.anomaly_score_by_circuit = {
            circuit_id: (
                max(_alert_anomaly_score(alert) for alert in alerts)
                if alerts
                else 0.0
            )
            for circuit_id, alerts in self.state.active_alerts_by_circuit.items()
        }
        self.async_set_updated_data(self.state)

    async def async_export_diagnostics(self: Self, circuit_id: str) -> None:
        """Store a lightweight diagnostics export snapshot for a circuit."""
        self.last_exported_diagnostics = {
            "circuit_id": circuit_id,
            "anomaly_score": self.state.anomaly_score_by_circuit.get(circuit_id, 0.0),
            "data_quality": self.state.data_quality_by_circuit.get(circuit_id),
            "learning": self.state.learning_by_circuit.get(circuit_id, True),
        }

    async def async_run_mapping_checks(self: Self) -> None:
        """Run lightweight source mapping checks."""
        self.mapping_checks_run += 1
        for config in self.circuit_configs:
            if not config.sensors:
                self.state.data_quality_by_circuit[config.circuit_id] = (
                    "missing_required_sensor"
                )

    async def async_label_nilm_signature(
        self: Self,
        circuit_id: str,
        signature_id: str,
        label: str,
    ) -> None:
        """Persist a user-confirmed label for a NILM signature."""
        signatures = self.store_data.nilm_signatures.setdefault(circuit_id, [])
        for signature in signatures:
            if signature.get("signature_id") == signature_id:
                signature["user_label"] = label
                return
        signatures.append({"signature_id": signature_id, "user_label": label})

    async def async_ignore_nilm_signature(
        self: Self,
        circuit_id: str,
        signature_id: str,
    ) -> None:
        """Persist an ignored NILM signature marker."""
        self.ignored_nilm_signatures.add((circuit_id, signature_id))
        signatures = self.store_data.nilm_signatures.setdefault(circuit_id, [])
        for signature in signatures:
            if signature.get("signature_id") == signature_id:
                signature["ignored"] = True
                return
        signatures.append({"signature_id": signature_id, "ignored": True})

    def has_circuit(self: Self, circuit_id: str) -> bool:
        """Return whether this coordinator owns a circuit id."""
        return any(config.circuit_id == circuit_id for config in self.circuit_configs)

    def _source_states_for(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> dict[str, SourceState]:
        states: dict[str, SourceState] = {}
        hass_states = getattr(self.hass, "states", None)
        get_state = getattr(hass_states, "get", None)
        if get_state is None:
            return states

        for sensor in config.sensors:
            raw_state = get_state(sensor.entity_id)
            if raw_state is None:
                continue
            attributes = getattr(raw_state, "attributes", {}) or {}
            states[sensor.entity_id] = SourceState(
                entity_id=sensor.entity_id,
                state=str(getattr(raw_state, "state", "")),
                unit=attributes.get("unit_of_measurement") or sensor.unit,
                last_updated=getattr(raw_state, "last_updated", now) or now,
            )
        return states

    def _observe_real_power(
        self: Self,
        config: CircuitConfig,
        sample: Any,
        now: datetime,
    ) -> AlertEvidence | None:
        if sample.real_power is None:
            self.state.learning_by_circuit.setdefault(config.circuit_id, True)
            return None

        key = _baseline_key(config.circuit_id, "real_power")
        baseline = self.store_data.baselines.get(key)
        if baseline is None:
            values = self._baseline_values[key]
            values.append(sample.real_power)
            if len(values) >= 15:
                baseline = build_baseline("real_power", values)
                self.store_data.baselines[key] = baseline
            self.state.learning_by_circuit[config.circuit_id] = True
            return None

        self.state.learning_by_circuit[config.circuit_id] = baseline.confidence < 0.6
        if baseline.confidence < 0.6:
            return None

        score = score_deviation(sample.real_power, baseline)
        return self._alert_policy.observe(
            Observation(
                circuit_id=config.circuit_id,
                feature="real_power",
                score=score,
                baseline_confidence=baseline.confidence,
                observed_at=now,
                observed_value=sample.real_power,
                baseline_value=baseline.median,
            )
        )

    async def _notify_alert(self: Self, alert: AlertEvidence) -> None:
        if alert.circuit_id in self.paused_circuits:
            return
        alert_id = notifications.notification_id_for_alert(alert)
        if alert_id in self._notified_alert_ids:
            return
        self._notified_alert_ids.add(alert_id)
        await notifications.async_create_alert_notification(self.hass, alert)


def _baseline_key(circuit_id: str, feature: str) -> str:
    return f"{circuit_id}:{feature}"


def _circuit_configs_from_entry_data(
    entry_data: dict[str, Any],
) -> tuple[CircuitConfig, ...]:
    configs: list[CircuitConfig] = []
    for raw_circuit in entry_data.get(CONF_CIRCUITS, []):
        config = _circuit_config_from_raw(raw_circuit)
        if config is not None:
            configs.append(config)
    return tuple(configs)


def _circuit_config_from_raw(raw_circuit: Any) -> CircuitConfig | None:
    if isinstance(raw_circuit, CircuitConfig):
        return raw_circuit
    if not isinstance(raw_circuit, dict):
        return None

    circuit_id = raw_circuit.get("circuit_id") or raw_circuit.get("id")
    if not circuit_id:
        return None

    try:
        appliance_profile = ApplianceProfile(
            raw_circuit.get("appliance_profile", ApplianceProfile.MIXED.value)
        )
        mode = CircuitMode(raw_circuit.get("mode", CircuitMode.MIXED.value))
        retention_mode = RetentionMode(
            raw_circuit.get("retention_mode", RetentionMode.STANDARD.value)
        )
    except ValueError:
        return None

    return CircuitConfig(
        circuit_id=str(circuit_id),
        name=str(raw_circuit.get("name") or circuit_id),
        appliance_profile=appliance_profile,
        mode=mode,
        sensors=_sensor_refs_from_raw(raw_circuit),
        retention_mode=retention_mode,
    )


def _sensor_refs_from_raw(raw_circuit: dict[str, Any]) -> tuple[SensorRef, ...]:
    raw_sensors = raw_circuit.get("sensors")
    if raw_sensors is None:
        raw_sensors = raw_circuit.get("source_entities", [])

    refs: list[SensorRef] = []
    for raw_sensor in raw_sensors:
        ref = _sensor_ref_from_raw(raw_sensor)
        if ref is not None:
            refs.append(ref)
    return tuple(refs)


def _sensor_ref_from_raw(raw_sensor: Any) -> SensorRef | None:
    if isinstance(raw_sensor, SensorRef):
        return raw_sensor
    if isinstance(raw_sensor, str):
        return SensorRef(entity_id=raw_sensor, role=SensorRole.REAL_POWER)
    if not isinstance(raw_sensor, dict):
        return None

    entity_id = raw_sensor.get("entity_id")
    if not entity_id:
        return None
    try:
        role = SensorRole(raw_sensor.get("role", SensorRole.REAL_POWER.value))
    except ValueError:
        return None
    return SensorRef(
        entity_id=str(entity_id),
        role=role,
        leg=raw_sensor.get("leg"),
        unit=raw_sensor.get("unit"),
    )
