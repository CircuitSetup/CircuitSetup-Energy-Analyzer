from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Self

from . import notifications, repairs
from .aggregation import aggregate_dual_phase
from .alerting import ConservativeAlertPolicy, Observation
from .baseline import build_baseline
from .const import (
    CONF_CIRCUITS,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_KNOWN_LOAD_CIRCUITS,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_RETENTION_MODE,
    CONF_SENSITIVITY,
    DEFAULT_RETENTION_MODE,
    DEFAULT_SENSITIVITY,
    DOMAIN,
)
from .events import CircuitEventDetector
from .models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
    RetentionMode,
    SensorRef,
    SensorRole,
)
from .nilm import (
    NilmEdge,
    NilmEdgeDetector,
    classify_signature,
    cluster_recurring_signatures,
    mask_known_loads,
    unmatched_load_percentage,
)
from .normalize import NormalizedCircuitSample, SourceState, build_circuit_sample
from .power_quality import (
    PowerQualityEvidence,
    extract_power_quality_features,
    relationship_rms_score,
    score_power_quality_features,
    select_power_quality_evidence,
)
from .profiles import get_profile_definition
from .storage import RETENTION_WINDOWS, FeatureStoreData

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
    power_quality_score_by_circuit: dict[str, float] = field(default_factory=dict)
    power_quality_evidence_by_circuit: dict[str, str] = field(default_factory=dict)
    reactive_power_drift_by_circuit: dict[str, float] = field(default_factory=dict)
    apparent_power_drift_by_circuit: dict[str, float] = field(default_factory=dict)
    power_factor_drift_by_circuit: dict[str, float] = field(default_factory=dict)
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
        store: Any | None = None,
        store_data: FeatureStoreData | None = None,
        now_fn: Any | None = None,
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN)
        self.entry_id = entry_id
        self.entry_data = entry_data or {}
        self.options = options or {}
        self._store = store
        self.store_data = store_data or FeatureStoreData()
        self.circuit_configs = _circuit_configs_from_entry_data(
            self.entry_data,
            self.options,
        )
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._entry_retention_mode = _retention_mode_from_sources(
            self.entry_data,
            self.options,
        )
        self._known_load_circuit_ids = frozenset(
            _string_list_from_sources(
                self.entry_data,
                self.options,
                CONF_KNOWN_LOAD_CIRCUITS,
            )
        )
        self._sensitivity = str(
            self.options.get(
                CONF_SENSITIVITY,
                self.entry_data.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY),
            )
        )
        self._detectors = {
            config.circuit_id: CircuitEventDetector()
            for config in self.circuit_configs
        }
        self._alert_policy = _alert_policy_for_sensitivity(self._sensitivity)
        self._baseline_values: defaultdict[str, list[float]] = defaultdict(list)
        self._notified_alert_ids: set[str] = set()
        self._active_repair_issues: set[tuple[str, str]] = set()
        self._nilm_detectors: dict[str, NilmEdgeDetector] = {}
        self._nilm_unmatched_edges: defaultdict[str, list[NilmEdge]] = defaultdict(list)
        self._nilm_total_events_by_circuit: defaultdict[str, int] = defaultdict(int)
        self._store_dirty = False
        self.paused_circuits: set[str] = set()
        self.ignored_nilm_signatures: set[tuple[str, str]] = set()
        self.last_exported_diagnostics: dict[str, Any] = {}
        self.mapping_checks_run = 0
        self.state = AnalyzerState()
        self.source_entities: tuple[str, ...] = ()
        self.started = False
        self._unsub_state_change: Any = None
        self._hydrate_state_from_store()
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
        """Handle Home Assistant source state changes."""
        await self.async_process_update()

    async def async_process_update(self: Self) -> AnalyzerState:
        """Process current HA source states through the analyzer pipeline."""
        now = self._now_fn()
        events: list[CircuitEvent] = []
        alerts: list[AlertEvidence] = []
        samples: list[tuple[CircuitConfig, NormalizedCircuitSample]] = []

        for config in self.circuit_configs:
            sample = self._sample_for_config(config, now)
            samples.append((config, sample))
            await self._sync_data_quality_repairs(config.circuit_id, sample)

            detector = self._detectors.setdefault(
                config.circuit_id,
                CircuitEventDetector(),
            )
            new_events = detector.process(sample)
            events.extend(new_events)
            if new_events:
                self.store_data.events.extend(new_events)
                self._mark_store_dirty()

            alert = self._observe_power_quality(config, sample, now)
            if alert is not None:
                alerts.append(alert)
                self.store_data.alerts.append(alert)
                self._mark_store_dirty()
                await self._notify_alert(alert)

        for config, sample in samples:
            self._process_nilm_sample(config, sample, events)

        process_events_into_state(self.state, events, alerts)
        self.async_set_updated_data(self.state)
        await self._async_save_store(now)
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
        self._mark_store_dirty()
        self.state.active_alerts_by_circuit.pop(circuit_id, None)
        self.state.anomaly_score_by_circuit[circuit_id] = 0.0
        self.state.learning_by_circuit[circuit_id] = True
        self.async_set_updated_data(self.state)
        await self._async_save_store(self._now_fn())

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
        self._mark_store_dirty()
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
        await self._async_save_store(self._now_fn())

    async def async_export_diagnostics(self: Self, circuit_id: str) -> None:
        """Store a lightweight diagnostics export snapshot for a circuit."""
        self.last_exported_diagnostics = {
            "circuit_id": circuit_id,
            "anomaly_score": self.state.anomaly_score_by_circuit.get(circuit_id, 0.0),
            "data_quality": self.state.data_quality_by_circuit.get(circuit_id),
            "learning": self.state.learning_by_circuit.get(circuit_id, True),
        }
        self.async_set_updated_data(self.state)

    async def async_run_mapping_checks(self: Self) -> None:
        """Run lightweight source mapping checks."""
        self.mapping_checks_run += 1
        for config in self.circuit_configs:
            if not config.sensors:
                self.state.data_quality_by_circuit[config.circuit_id] = (
                    "missing_required_sensor"
                )
                await self._sync_data_quality_repairs(
                    config.circuit_id,
                    "missing_required_sensor",
                )
        self.async_set_updated_data(self.state)

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
                self._mark_store_dirty()
                await self._async_save_store(self._now_fn())
                return
        signatures.append({"signature_id": signature_id, "user_label": label})
        self._mark_store_dirty()
        await self._async_save_store(self._now_fn())

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
                self._mark_store_dirty()
                await self._async_save_store(self._now_fn())
                return
        signatures.append({"signature_id": signature_id, "ignored": True})
        self._mark_store_dirty()
        await self._async_save_store(self._now_fn())

    def has_circuit(self: Self, circuit_id: str) -> bool:
        """Return whether this coordinator owns a circuit id."""
        return any(config.circuit_id == circuit_id for config in self.circuit_configs)

    def _hydrate_state_from_store(self: Self) -> None:
        for circuit_id, signatures in self.store_data.nilm_signatures.items():
            for signature in signatures:
                if signature.get("ignored") is True:
                    self.ignored_nilm_signatures.add(
                        (circuit_id, str(signature.get("signature_id", "")))
                    )
            self._refresh_nilm_state(circuit_id)

    def _sample_for_config(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> NormalizedCircuitSample:
        if config.mode is CircuitMode.MAINS_NILM:
            return self._aggregate_parallel_sample(config, now)
        if config.mode is not CircuitMode.DUAL_PHASE:
            return build_circuit_sample(
                config,
                self._source_states_for(config, now),
                now,
            )

        left_sensors = tuple(
            sensor for sensor in config.sensors if _normalized_leg(sensor.leg) == "a"
        )
        right_sensors = tuple(
            sensor for sensor in config.sensors if _normalized_leg(sensor.leg) == "b"
        )
        if not left_sensors or not right_sensors:
            return build_circuit_sample(
                config,
                self._source_states_for(config, now),
                now,
            )

        left_config = replace(
            config,
            mode=CircuitMode.SINGLE_PHASE,
            sensors=left_sensors,
        )
        right_config = replace(
            config,
            mode=CircuitMode.SINGLE_PHASE,
            sensors=right_sensors,
        )
        left_sample = build_circuit_sample(
            left_config,
            self._source_states_for(left_config, now),
            now,
        )
        right_sample = build_circuit_sample(
            right_config,
            self._source_states_for(right_config, now),
            now,
        )
        aggregated = aggregate_dual_phase(config.circuit_id, left_sample, right_sample)
        return NormalizedCircuitSample(
            timestamp=aggregated.timestamp,
            circuit_id=config.circuit_id,
            real_power=aggregated.combined_real_power,
            current=aggregated.combined_current,
            voltage=aggregated.average_voltage,
            reactive_power=aggregated.combined_reactive_power,
            apparent_power=aggregated.combined_apparent_power,
            power_factor=aggregated.average_power_factor,
            frequency=aggregated.frequency,
            energy=aggregated.energy,
            source_entity_ids=tuple(sensor.entity_id for sensor in config.sensors),
            quality_issues=aggregated.quality_issues,
        )

    def _aggregate_parallel_sample(
        self: Self,
        config: CircuitConfig,
        now: datetime,
    ) -> NormalizedCircuitSample:
        samples = [
            build_circuit_sample(
                replace(config, sensors=(sensor,)),
                self._source_states_for(replace(config, sensors=(sensor,)), now),
                now,
            )
            for sensor in config.sensors
        ]
        if not samples:
            return build_circuit_sample(config, {}, now)

        return NormalizedCircuitSample(
            timestamp=max(sample.timestamp for sample in samples),
            circuit_id=config.circuit_id,
            real_power=_sum_sample_values(samples, "real_power"),
            current=_sum_sample_values(samples, "current"),
            voltage=_average_sample_values(samples, "voltage"),
            reactive_power=_sum_sample_values(samples, "reactive_power"),
            apparent_power=_sum_sample_values(samples, "apparent_power"),
            power_factor=_average_sample_values(samples, "power_factor"),
            frequency=_average_sample_values(samples, "frequency"),
            energy=_sum_sample_values(samples, "energy"),
            source_entity_ids=tuple(sensor.entity_id for sensor in config.sensors),
            quality_issues=tuple(
                issue
                for sample in samples
                for issue in getattr(sample, "quality_issues", ())
            ),
        )

    async def _sync_data_quality_repairs(
        self: Self,
        circuit_id: str,
        sample_or_problem: NormalizedCircuitSample | str,
    ) -> None:
        desired: set[tuple[str, str]] = set()
        if isinstance(sample_or_problem, str):
            self.state.data_quality_by_circuit[circuit_id] = sample_or_problem
            desired.add((circuit_id, sample_or_problem))
        elif sample_or_problem.quality_issues:
            issue = sample_or_problem.quality_issues[0]
            problem = _data_quality_problem(issue)
            self.state.data_quality_by_circuit[circuit_id] = issue
            desired.add((circuit_id, problem))
        else:
            self.state.data_quality_by_circuit.pop(circuit_id, None)

        current = {
            issue for issue in self._active_repair_issues if issue[0] == circuit_id
        }
        for issue in current - desired:
            await repairs.async_delete_data_quality_issue(self.hass, issue[0], issue[1])
            self._active_repair_issues.discard(issue)

        for issue in desired - self._active_repair_issues:
            await repairs.async_create_data_quality_issue(self.hass, issue[0], issue[1])
            self._active_repair_issues.add(issue)

    def _process_nilm_sample(
        self: Self,
        config: CircuitConfig,
        sample: NormalizedCircuitSample,
        events: Iterable[CircuitEvent],
    ) -> None:
        if not self._nilm_enabled(config):
            return

        detector = self._nilm_detectors.setdefault(
            config.circuit_id,
            NilmEdgeDetector(min_delta_w=_nilm_min_delta_w(self._sensitivity)),
        )
        edges = detector.process(sample)
        if edges:
            known_events = self._known_load_events(config.circuit_id, events)
            mask = mask_known_loads(edges, known_events)
            self._nilm_total_events_by_circuit[config.circuit_id] += len(edges)
            self._nilm_unmatched_edges[config.circuit_id].extend(mask.unmatched_edges)

            signatures = cluster_recurring_signatures(
                self._nilm_unmatched_edges[config.circuit_id]
            )
            payloads = self._nilm_signature_payloads(config.circuit_id, signatures)
            if payloads != self.store_data.nilm_signatures.get(config.circuit_id, []):
                self.store_data.nilm_signatures[config.circuit_id] = payloads
                self._mark_store_dirty()

        self._refresh_nilm_state(config.circuit_id)

    def _known_load_events(
        self: Self,
        nilm_circuit_id: str,
        events: Iterable[CircuitEvent],
    ) -> Iterable[CircuitEvent]:
        for event in events:
            if event.circuit_id == nilm_circuit_id:
                continue
            if (
                self._known_load_circuit_ids
                and event.circuit_id not in self._known_load_circuit_ids
            ):
                continue
            yield event

    def _nilm_enabled(self: Self, config: CircuitConfig) -> bool:
        enabled = bool(
            self.options.get(
                CONF_ENABLE_EXPERIMENTAL_NILM,
                self.entry_data.get(CONF_ENABLE_EXPERIMENTAL_NILM, False),
            )
        )
        return enabled and (
            config.mode is CircuitMode.MAINS_NILM
            or config.appliance_profile is ApplianceProfile.MAINS_NILM
        )

    def _nilm_signature_payloads(
        self: Self,
        circuit_id: str,
        signatures: Iterable[Any],
    ) -> list[dict[str, Any]]:
        existing = {
            str(signature.get("signature_id")): dict(signature)
            for signature in self.store_data.nilm_signatures.get(circuit_id, [])
        }
        payloads: list[dict[str, Any]] = []
        seen: set[str] = set()
        for signature in signatures:
            current = existing.get(signature.signature_id, {})
            user_label = current.get("user_label")
            classified_signature = replace(signature, user_label=user_label)
            ignored = bool(current.get("ignored")) or (
                circuit_id,
                signature.signature_id,
            ) in self.ignored_nilm_signatures
            payload = {
                "signature_id": signature.signature_id,
                "median_delta_w": signature.median_delta_w,
                "median_delta_var": signature.median_delta_var,
                "median_delta_va": signature.median_delta_va,
                "median_delta_pf": signature.median_delta_pf,
                "occurrence_count": signature.occurrence_count,
                "confidence": signature.confidence,
                "classification": classify_signature(classified_signature),
            }
            if user_label:
                payload["user_label"] = user_label
            if ignored:
                payload["ignored"] = True
            payloads.append(payload)
            seen.add(signature.signature_id)

        for signature_id, signature in existing.items():
            if signature_id not in seen and (
                signature.get("user_label") or signature.get("ignored")
            ):
                payloads.append(signature)

        return payloads

    def _refresh_nilm_state(self: Self, circuit_id: str) -> None:
        signatures = self.store_data.nilm_signatures.get(circuit_id, [])
        active_count = sum(
            1 for signature in signatures if not signature.get("ignored")
        )
        self.state.nilm_signature_count_by_circuit[circuit_id] = active_count
        self.state.nilm_unmatched_load_percentage_by_circuit[circuit_id] = (
            unmatched_load_percentage(
                self._nilm_total_events_by_circuit[circuit_id],
                len(self._nilm_unmatched_edges[circuit_id]),
            )
        )

    def _mark_store_dirty(self: Self) -> None:
        self._store_dirty = True

    async def _async_save_store(self: Self, now: datetime) -> None:
        if self._store is None or not self._store_dirty:
            return
        self._apply_retention(now)
        self._store.data = self.store_data
        await self._store.async_save()
        self._store_dirty = False

    def _apply_retention(self: Self, now: datetime) -> None:
        retained_events = [
            event for event in self.store_data.events if self._keep_event(event, now)
        ]
        if len(retained_events) != len(self.store_data.events):
            self.store_data.events = retained_events

    def _keep_event(self: Self, event: CircuitEvent, now: datetime) -> bool:
        retention_mode = self._retention_mode_for_circuit(event.circuit_id)
        return event.timestamp >= now - RETENTION_WINDOWS[retention_mode]

    def _retention_mode_for_circuit(self: Self, circuit_id: str) -> RetentionMode:
        for config in self.circuit_configs:
            if config.circuit_id == circuit_id:
                return config.retention_mode
        return self._entry_retention_mode

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

    def _observe_power_quality(
        self: Self,
        config: CircuitConfig,
        sample: Any,
        now: datetime,
    ) -> AlertEvidence | None:
        features = extract_power_quality_features(sample)
        if not features:
            self.state.learning_by_circuit.setdefault(config.circuit_id, True)
            return None

        baselines: dict[str, Any] = {}
        learning_new_features = False
        for feature, value in features.items():
            key = _baseline_key(config.circuit_id, feature)
            baseline = self.store_data.baselines.get(key)
            if baseline is None:
                values = self._baseline_values[key]
                values.append(value)
                if len(values) >= 15:
                    baseline = build_baseline(feature, values)
                    self.store_data.baselines[key] = baseline
                    self._mark_store_dirty()
                learning_new_features = True
            if baseline is not None:
                baselines[feature] = baseline

        scores = score_power_quality_features(features, baselines)
        evidence = select_power_quality_evidence(
            config,
            scores,
            min_relationship_score=self._alert_policy.min_average_score,
        )
        self._update_power_quality_state(config.circuit_id, scores, evidence)

        mature = self._learning_mature(config, now)
        has_confident_scores = any(score.baseline_confidence >= 0.6 for score in scores)
        self.state.learning_by_circuit[config.circuit_id] = (
            learning_new_features or not mature or not has_confident_scores
        )
        if learning_new_features or not mature or not has_confident_scores:
            return None
        if evidence is None:
            return None

        return self._alert_policy.observe(
            Observation(
                circuit_id=config.circuit_id,
                feature=evidence.feature,
                score=evidence.score,
                baseline_confidence=evidence.baseline_confidence,
                observed_at=now,
                observed_value=evidence.observed_value,
                baseline_value=evidence.baseline_value,
                message=evidence.message,
                features=evidence.features,
            )
        )

    def _update_power_quality_state(
        self: Self,
        circuit_id: str,
        scores: Iterable[Any],
        evidence: PowerQualityEvidence | None,
    ) -> None:
        def _drift(primary: str, fallback: str) -> float:
            score = by_feature.get(primary, by_feature.get(fallback))
            return abs(score.change_ratio) if score is not None else 0.0

        scores = list(scores)
        by_feature = {score.feature: score for score in scores}
        self.state.power_quality_score_by_circuit[circuit_id] = relationship_rms_score(
            scores
        )
        self.state.power_quality_evidence_by_circuit[circuit_id] = (
            evidence.message if evidence is not None else ""
        )
        self.state.reactive_power_drift_by_circuit[circuit_id] = _drift(
            "reactive_power",
            "reactive_to_real_ratio",
        )
        self.state.apparent_power_drift_by_circuit[circuit_id] = _drift(
            "apparent_power",
            "apparent_to_real_ratio",
        )
        self.state.power_factor_drift_by_circuit[circuit_id] = _drift(
            "power_factor",
            "power_factor_deficit",
        )

    def _learning_mature(self: Self, config: CircuitConfig, now: datetime) -> bool:
        profile = get_profile_definition(config.appliance_profile)
        circuit_events = [
            event
            for event in self.store_data.events
            if event.circuit_id == config.circuit_id
        ]
        cycle_count = sum(
            1 for event in circuit_events if event.event_type is EventType.START
        )
        if profile.minimum_cycles > 0 and cycle_count >= profile.minimum_cycles:
            return True

        if not circuit_events:
            return False

        first_seen = min(event.timestamp for event in circuit_events)
        return now - first_seen >= timedelta(days=profile.minimum_learning_days)

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


def _sum_sample_values(
    samples: Iterable[NormalizedCircuitSample],
    attribute: str,
) -> float | None:
    values = [
        value
        for sample in samples
        if (value := getattr(sample, attribute, None)) is not None
    ]
    if not values:
        return None
    return float(sum(values))


def _average_sample_values(
    samples: Iterable[NormalizedCircuitSample],
    attribute: str,
) -> float | None:
    values = [
        value
        for sample in samples
        if (value := getattr(sample, attribute, None)) is not None
    ]
    if not values:
        return None
    return float(sum(values) / len(values))


def _normalized_leg(leg: str | None) -> str | None:
    if leg is None:
        return None
    value = leg.strip().lower()
    if value in {"a", "left", "l1", "line1", "1"}:
        return "a"
    if value in {"b", "right", "l2", "line2", "2"}:
        return "b"
    return None


def _data_quality_problem(issue: str) -> str:
    issue_text = issue.lower()
    if "stale" in issue_text:
        return "stale_source_sensor"
    return "missing_required_sensor"


def _string_list_from_sources(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None,
    key: str,
) -> list[str]:
    options = options or {}
    raw = options[key] if key in options else entry_data.get(key, [])
    if isinstance(raw, str):
        return [raw] if raw else []
    if not isinstance(raw, (list, tuple, set)):
        return []
    return [item for item in raw if isinstance(item, str) and item]


def _retention_mode_from_sources(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None,
) -> RetentionMode:
    options = options or {}
    raw = options.get(
        CONF_RETENTION_MODE,
        entry_data.get(CONF_RETENTION_MODE, DEFAULT_RETENTION_MODE),
    )
    try:
        return RetentionMode(str(raw))
    except ValueError:
        return RetentionMode.STANDARD


def _alert_policy_for_sensitivity(sensitivity: str) -> ConservativeAlertPolicy:
    if sensitivity == "high":
        return ConservativeAlertPolicy(
            min_repeated=3,
            min_total_score=2.4,
            min_average_score=1.2,
        )
    if sensitivity == "low":
        return ConservativeAlertPolicy(
            min_repeated=4,
            min_total_score=6.0,
            min_average_score=1.8,
        )
    return ConservativeAlertPolicy()


def _nilm_min_delta_w(sensitivity: str) -> float:
    if sensitivity == "high":
        return 75.0
    if sensitivity == "low":
        return 150.0
    return 100.0


def _circuit_configs_from_entry_data(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> tuple[CircuitConfig, ...]:
    configs: list[CircuitConfig] = []
    default_retention_mode = _retention_mode_from_sources(entry_data, options)
    for raw_circuit in entry_data.get(CONF_CIRCUITS, []):
        config = _circuit_config_from_raw(raw_circuit, default_retention_mode)
        if config is not None:
            configs.append(config)

    if (
        _experimental_nilm_enabled(entry_data, options)
        and not any(config.mode is CircuitMode.MAINS_NILM for config in configs)
    ):
        mains_config = _mains_nilm_config_from_sources(entry_data, options)
        if mains_config is not None:
            configs.append(mains_config)
    return tuple(configs)


def _experimental_nilm_enabled(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None,
) -> bool:
    options = options or {}
    return bool(
        options.get(
            CONF_ENABLE_EXPERIMENTAL_NILM,
            entry_data.get(CONF_ENABLE_EXPERIMENTAL_NILM, False),
        )
    )


def _mains_nilm_config_from_sources(
    entry_data: dict[str, Any],
    options: dict[str, Any] | None,
) -> CircuitConfig | None:
    mains_entities = _string_list_from_sources(
        entry_data,
        options,
        CONF_MAINS_SOURCE_ENTITIES,
    )
    if not mains_entities:
        return None

    return CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=tuple(
            SensorRef(entity_id=entity_id, role=SensorRole.REAL_POWER)
            for entity_id in mains_entities
        ),
        retention_mode=_retention_mode_from_sources(entry_data, options),
    )


def _circuit_config_from_raw(
    raw_circuit: Any,
    default_retention_mode: RetentionMode = RetentionMode.STANDARD,
) -> CircuitConfig | None:
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
            raw_circuit.get("retention_mode", default_retention_mode.value)
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
