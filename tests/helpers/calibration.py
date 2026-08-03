from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from types import SimpleNamespace
from typing import Any

import yaml

from custom_components.circuitsetup_energy_analyzer.alerting import (
    ConservativeAlertPolicy,
)
from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.managers.state_reducer import (
    apply_state_update as _apply_state_update,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
    PowerFlowMode,
    RetentionMode,
    SensorRef,
    SensorRole,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.normalize import (
    SourceState,
    build_circuit_sample,
)
from custom_components.circuitsetup_energy_analyzer.processors.base import (
    FeatureResult,
    ProcessingContext,
)
from custom_components.circuitsetup_energy_analyzer.processors.cycles import (
    RunCycleProcessor,
)
from custom_components.circuitsetup_energy_analyzer.processors.energy_usage import (
    EnergyUsageProcessor,
)
from custom_components.circuitsetup_energy_analyzer.processors.events import (
    CircuitEventProcessor,
)
from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
    NilmSampleProcessor,
)
from custom_components.circuitsetup_energy_analyzer.profiles import nilm_source_kind
from custom_components.circuitsetup_energy_analyzer.state import (
    process_events_into_state,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData
from custom_components.circuitsetup_energy_analyzer.usage import EnergyUsageSettings

CALIBRATION_CONFIDENCE_BINS = (
    "0.0-0.2",
    "0.2-0.4",
    "0.4-0.6",
    "0.6-0.8",
    "0.8-1.0",
)

_ROLE_BY_SOURCE_KEY = {
    "power": SensorRole.REAL_POWER,
    "real_power": SensorRole.REAL_POWER,
    "energy": SensorRole.ENERGY,
    "current": SensorRole.CURRENT,
    "voltage": SensorRole.VOLTAGE,
    "power_factor": SensorRole.POWER_FACTOR,
    "apparent_power": SensorRole.APPARENT_POWER,
    "reactive_power": SensorRole.REACTIVE_POWER,
    "frequency": SensorRole.FREQUENCY,
}
_SEVERITY_ORDER = {
    Severity.INFO: 0,
    Severity.WARNING: 1,
    Severity.ERROR: 2,
}


class CalibrationFixtureError(ValueError):
    """Raised when a calibration fixture is invalid."""


@dataclass(frozen=True, slots=True)
class CalibrationSample:
    timestamp: datetime
    t: int
    states: dict[str, Any]
    completes_prior_energy_days: bool = False


@dataclass(frozen=True, slots=True)
class ExpectedEvent:
    circuit_id: str
    event_type: EventType
    around_t: int
    tolerance_seconds: int


@dataclass(frozen=True, slots=True)
class ExpectedAlert:
    circuit_id: str
    feature: str
    earliest_t: int
    latest_t: int
    severity: Severity | None = None
    min_repeated_count: int = 1
    min_confidence: float | None = None


@dataclass(frozen=True, slots=True)
class ExpectedNoAlert:
    circuit_id: str
    feature: str
    start_t: int
    end_t: int


@dataclass(frozen=True, slots=True)
class CalibrationLabels:
    expected_events: tuple[ExpectedEvent, ...] = ()
    expected_alerts: tuple[ExpectedAlert, ...] = ()
    expected_no_alerts: tuple[ExpectedNoAlert, ...] = ()
    abnormal_condition_start_t: int | None = None
    component_truth: dict[str, ComponentTruth] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExpectedComponentSession:
    start_t: int
    end_t: int
    tolerance_seconds: int = 0


@dataclass(frozen=True, slots=True)
class ComponentTruth:
    edges: tuple[ExpectedEvent, ...] = ()
    sessions: tuple[ExpectedComponentSession, ...] = ()
    energy_kwh: float | None = None
    corroborating_helper_circuit_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class CalibrationExpectations:
    max_false_positive_alerts: int | None = None
    min_true_positive_alerts: int | None = None
    max_false_negative_alerts: int | None = None
    max_detection_latency_seconds: float | None = None
    expected_precision_at_least: float | None = None
    expected_recall_at_least: float | None = None


@dataclass(frozen=True, slots=True)
class CalibrationFixture:
    schema_version: int
    id: str
    description: str
    scenario_type: str
    start_time: datetime
    circuits: tuple[CircuitConfig, ...]
    samples: tuple[CalibrationSample, ...]
    labels: CalibrationLabels
    expectations: CalibrationExpectations
    path: Path
    source_kind: str | None = None
    assignments_by_circuit: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )
    entry_id: str | None = None
    entries: tuple[CalibrationFixture, ...] = ()
    min_delta_w: float = 100.0


@dataclass(slots=True)
class ReplayResult:
    events: list[CircuitEvent]
    alerts: list[AlertEvidence]
    state_snapshots: list[dict[str, Any]]
    setup_issues: list[dict[str, Any]]
    nilm_signatures: list[dict[str, Any]]
    final_state: AnalyzerState
    store_data: FeatureStoreData
    metrics: CalibrationMetrics | None = None


@dataclass(slots=True)
class CalibrationMetrics:
    fixture_id: str
    true_positive_alerts: int
    false_positive_alerts: int
    false_negative_alerts: int
    true_negative_windows: int
    precision: float | None
    recall: float | None
    f1: float | None
    detection_latency_seconds: float | None
    event_match_count: int
    event_miss_count: int
    confidence_bins: dict[str, dict[str, float]]
    brier_score: float | None
    expected_calibration_error: float | None
    source_kind: str | None = None
    component_metrics: dict[str, ComponentReplayMetrics] = field(default_factory=dict)
    residual_energy_kwh: float = 0.0
    false_helper_association_rate: float | None = None
    ambiguous_event_rate: float = 0.0
    conservation_violations: int = 0
    expectation_failures: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ComponentReplayMetrics:
    edge_precision: float | None
    edge_recall: float | None
    session_precision: float | None
    session_recall: float | None
    session_f1: float | None
    median_start_error_seconds: float | None
    median_stop_error_seconds: float | None
    energy_absolute_error_kwh: float | None
    energy_percentage_error: float | None


def load_calibration_fixture(path: Path) -> CalibrationFixture:
    raw = _load_yaml_mapping(path)
    if raw.get("scenarios"):
        msg = f"{path}: use load_calibration_scenarios for a scenario fixture"
        raise CalibrationFixtureError(msg)
    return _parse_fixture(raw, path)


def load_calibration_scenarios(path: Path) -> tuple[CalibrationFixture, ...]:
    """Expand optional scenario blocks while preserving legacy fixtures."""
    raw = _load_yaml_mapping(path)
    scenarios = _optional_list(raw, "scenarios")
    if not scenarios:
        return (_parse_fixture(raw, path),)
    _validate_block_ids(scenarios, "id", "scenario")
    parsed = tuple(
        _parse_fixture(
            {**raw, **dict(scenario), "id": f"{raw['id']}.{scenario['id']}"},
            path,
        )
        for scenario in scenarios
        if isinstance(scenario, Mapping)
    )
    return tuple(
        entry for fixture in parsed for entry in (fixture.entries or (fixture,))
    )


def _parse_fixture(raw: Mapping[str, Any], path: Path) -> CalibrationFixture:
    schema_version = int(raw.get("schema_version", 0))
    if schema_version != 1:
        msg = f"{path}: expected schema_version 1"
        raise CalibrationFixtureError(msg)

    start_time = _parse_datetime(str(raw["start_time"]))
    circuits = tuple(_parse_circuit(item) for item in _optional_list(raw, "circuits"))
    entries_raw = _optional_list(raw, "entries")
    _validate_block_ids(entries_raw, "entry_id", "entry")
    if not circuits and not entries_raw:
        msg = f"{path}: at least one circuit is required"
        raise CalibrationFixtureError(msg)

    samples = [
        _parse_sample(item, start_time) for item in _optional_list(raw, "samples")
    ]
    for segment in _optional_list(raw, "segments"):
        samples.extend(_expand_segment(segment, start_time, circuits))
    samples.sort(key=lambda sample: sample.timestamp)
    if not samples and not entries_raw:
        msg = f"{path}: at least one sample or segment is required"
        raise CalibrationFixtureError(msg)

    labels = _parse_labels(_required_mapping(raw, "labels"))
    expectations = _parse_expectations(
        _required_mapping(raw, "calibration_expectations")
    )
    fixture_id = str(raw["id"])
    entries = tuple(
        _parse_fixture(
            {
                **raw,
                **dict(entry),
                "id": f"{fixture_id}.{entry['entry_id']}",
                "entries": [],
                "scenarios": [],
                "labels": dict(entry.get("labels") or {}),
                "calibration_expectations": dict(
                    entry.get("calibration_expectations") or {}
                ),
            },
            path,
        )
        for entry in entries_raw
        if isinstance(entry, Mapping)
    )
    assignments = _optional_mapping(raw, "assignments")
    return CalibrationFixture(
        schema_version=schema_version,
        id=fixture_id,
        description=str(raw["description"]),
        scenario_type=str(raw["scenario_type"]),
        start_time=start_time,
        circuits=circuits,
        samples=tuple(samples),
        labels=labels,
        expectations=expectations,
        path=path,
        source_kind=(str(raw["source_kind"]) if raw.get("source_kind") else None),
        assignments_by_circuit={
            str(circuit_id): [
                dict(item) for item in values if isinstance(item, Mapping)
            ]
            for circuit_id, values in assignments.items()
            if isinstance(values, list)
        },
        entry_id=(str(raw["entry_id"]) if raw.get("entry_id") else None),
        entries=entries,
        min_delta_w=float(raw.get("min_delta_w", 100.0)),
    )


def replay_fixture_processors(fixture: CalibrationFixture) -> ReplayResult:
    state = AnalyzerState()
    store_data = FeatureStoreData(
        nilm_appliance_assignments_by_circuit={
            circuit_id: [dict(item) for item in assignments]
            for circuit_id, assignments in fixture.assignments_by_circuit.items()
        }
    )
    event_processor = CircuitEventProcessor()
    nilm_processor = NilmSampleProcessor(
        nilm_enabled=lambda config: nilm_source_kind(config) is not None,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _circuit_id: fixture.min_delta_w,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda circuit_id, event_list: (
            event
            for event in event_list
            if event.circuit_id != circuit_id
            and next(
                (
                    nilm_source_kind(config).value
                    for config in fixture.circuits
                    if config.circuit_id == circuit_id
                    and nilm_source_kind(config) is not None
                ),
                None,
            )
            == "mains"
        ),
        helper_candidate_events=lambda circuit_id, event_list: (
            event for event in event_list if event.circuit_id != circuit_id
        ),
        observe_topology=lambda _config, _match, _context: [],
    )
    alert_policies: dict[str, ConservativeAlertPolicy] = {}
    cycle_alert_policies: dict[str, ConservativeAlertPolicy] = {}
    run_cycle_processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda circuit_id: cycle_alert_policies.setdefault(
            circuit_id,
            ConservativeAlertPolicy(
                min_repeated=3,
                min_total_score=4.5,
                min_average_score=1.5,
                min_baseline_confidence=0.6,
            ),
        ),
        learning_mature=lambda _config, _now: False,
    )
    energy_usage_processor = EnergyUsageProcessor(
        settings_for_config=lambda config, _circuit_id: EnergyUsageSettings(
            window_days=config.energy_usage_window_days if config else 7,
            daily_spike_ratio=(config.daily_energy_spike_ratio if config else 0.25),
        ),
        retention_days_for_circuit=lambda _circuit_id: 45,
        alert_policy_for_circuit=lambda circuit_id: alert_policies.setdefault(
            circuit_id,
            ConservativeAlertPolicy(
                min_repeated=3,
                min_total_score=3.0,
                min_average_score=1.0,
                min_baseline_confidence=0.8,
            ),
        ),
    )
    hass = SimpleNamespace(data={DOMAIN: {}})
    events: list[CircuitEvent] = []
    alerts: list[AlertEvidence] = []
    setup_issues: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []

    for calibration_sample in fixture.samples:
        context = ProcessingContext(
            now=calibration_sample.timestamp,
            hass=hass,
            state=state,
            store_data=store_data,
            options={},
            entry_data={},
            known_load_circuit_ids=frozenset(
                config.circuit_id for config in fixture.circuits
            ),
            sensitivity="balanced",
        )
        for circuit_config in fixture.circuits:
            if not any(
                sensor.entity_id in calibration_sample.states
                for sensor in circuit_config.sensors
            ):
                continue
            source_states = _source_states_for_sample(
                circuit_config,
                calibration_sample,
            )
            normalized_sample = build_circuit_sample(
                circuit_config,
                source_states,
                calibration_sample.timestamp,
            )
            if normalized_sample.real_power is None:
                state.latest_real_power_w_by_circuit.pop(
                    circuit_config.circuit_id, None
                )
            else:
                state.latest_real_power_w_by_circuit[circuit_config.circuit_id] = (
                    normalized_sample.real_power
                )
            setup_issues.extend(
                {
                    "timestamp": calibration_sample.timestamp.isoformat(),
                    "circuit_id": circuit_config.circuit_id,
                    "issue": issue,
                }
                for issue in normalized_sample.quality_issues
            )

            if calibration_sample.completes_prior_energy_days:
                _mark_prior_energy_days_complete(
                    store_data,
                    circuit_config.circuit_id,
                    calibration_sample.timestamp,
                )

            results = [
                event_processor.process(
                    normalized_sample,
                    circuit_config,
                    context,
                ),
                run_cycle_processor.process(
                    normalized_sample,
                    circuit_config,
                    context,
                ),
                energy_usage_processor.process(
                    normalized_sample,
                    circuit_config,
                    context,
                ),
            ]
            active_alerts: list[AlertEvidence] = []
            if nilm_source_kind(circuit_config) is not None:
                results.append(
                    nilm_processor.process(
                        normalized_sample,
                        circuit_config,
                        context,
                        events=tuple(events),
                    )
                )
            for result in results:
                new_events, new_alerts = _apply_feature_result(
                    result,
                    state,
                    store_data,
                )
                events.extend(new_events)
                alerts.extend(result.alerts)
                active_alerts.extend(new_alerts)
            process_events_into_state(
                state,
                (),
                active_alerts,
                evaluated_circuit_ids=(circuit_config.circuit_id,),
            )
        snapshots.append(_snapshot_state(state))

    result = ReplayResult(
        events=events,
        alerts=alerts,
        state_snapshots=snapshots,
        setup_issues=setup_issues,
        nilm_signatures=[
            signature
            for signatures in store_data.nilm_signatures.values()
            for signature in signatures
        ],
        final_state=state,
        store_data=store_data,
    )
    result.metrics = evaluate_replay_result(fixture, result)
    return result


def evaluate_replay_result(
    fixture: CalibrationFixture,
    result: ReplayResult,
) -> CalibrationMetrics:
    matched_alert_indexes: set[int] = set()
    matched_alert_offsets: list[float] = []
    for expected in fixture.labels.expected_alerts:
        for index, alert in enumerate(result.alerts):
            if index in matched_alert_indexes:
                continue
            if _alert_matches(fixture, expected, alert):
                matched_alert_indexes.add(index)
                matched_alert_offsets.append(_offset_seconds(fixture, alert.timestamp))
                break

    true_positive_alerts = len(matched_alert_indexes)
    false_positive_alerts = len(result.alerts) - true_positive_alerts
    false_negative_alerts = len(fixture.labels.expected_alerts) - true_positive_alerts
    true_negative_windows = sum(
        1
        for window in fixture.labels.expected_no_alerts
        if not any(
            _alert_in_no_alert_window(fixture, alert, window) for alert in result.alerts
        )
    )
    precision = _ratio_or_none(
        true_positive_alerts,
        true_positive_alerts + false_positive_alerts,
    )
    recall = _ratio_or_none(
        true_positive_alerts,
        true_positive_alerts + false_negative_alerts,
    )
    f1 = (
        None
        if precision is None or recall is None or precision + recall == 0.0
        else round(2 * precision * recall / (precision + recall), 3)
    )
    latency = _detection_latency(fixture, matched_alert_offsets)
    event_match_count, event_miss_count = _event_match_counts(fixture, result.events)
    confidence_bins, brier, ece = _confidence_calibration(
        result.alerts,
        matched_alert_indexes,
    )
    reconciliation = _combined_reconciliation(result)
    return CalibrationMetrics(
        fixture_id=fixture.id,
        true_positive_alerts=true_positive_alerts,
        false_positive_alerts=false_positive_alerts,
        false_negative_alerts=false_negative_alerts,
        true_negative_windows=true_negative_windows,
        precision=precision,
        recall=recall,
        f1=f1,
        detection_latency_seconds=latency,
        event_match_count=event_match_count,
        event_miss_count=event_miss_count,
        confidence_bins=confidence_bins,
        brier_score=brier,
        expected_calibration_error=ece,
        source_kind=fixture.source_kind,
        component_metrics=_component_metrics(fixture, result),
        residual_energy_kwh=float(reconciliation.get("residual_energy_kwh", 0.0)),
        false_helper_association_rate=_false_helper_association_rate(
            fixture, result
        ),
        ambiguous_event_rate=_ratio_or_none(
            int(reconciliation.get("ambiguous_event_count", 0)),
            int(reconciliation.get("total_event_count", 0)),
        )
        or 0.0,
        conservation_violations=int(reconciliation.get("conservation_violations", 0)),
    )


def fixture_expectation_failures(
    fixture: CalibrationFixture,
    metrics: CalibrationMetrics,
) -> tuple[str, ...]:
    failures: list[str] = []
    expectations = fixture.expectations
    if (
        expectations.max_false_positive_alerts is not None
        and metrics.false_positive_alerts > expectations.max_false_positive_alerts
    ):
        failures.append(
            "false positives "
            f"{metrics.false_positive_alerts} > "
            f"{expectations.max_false_positive_alerts}"
        )
    if (
        expectations.min_true_positive_alerts is not None
        and metrics.true_positive_alerts < expectations.min_true_positive_alerts
    ):
        failures.append(
            "true positives "
            f"{metrics.true_positive_alerts} < "
            f"{expectations.min_true_positive_alerts}"
        )
    if (
        expectations.max_false_negative_alerts is not None
        and metrics.false_negative_alerts > expectations.max_false_negative_alerts
    ):
        failures.append(
            "false negatives "
            f"{metrics.false_negative_alerts} > "
            f"{expectations.max_false_negative_alerts}"
        )
    if (
        expectations.max_detection_latency_seconds is not None
        and metrics.detection_latency_seconds is not None
        and metrics.detection_latency_seconds
        > expectations.max_detection_latency_seconds
    ):
        failures.append(
            "detection latency "
            f"{metrics.detection_latency_seconds} > "
            f"{expectations.max_detection_latency_seconds}"
        )
    if (
        expectations.max_detection_latency_seconds is not None
        and metrics.detection_latency_seconds is None
        and metrics.true_positive_alerts > 0
    ):
        failures.append("detection latency was not available")
    if not _meets_floor(metrics.precision, expectations.expected_precision_at_least):
        failures.append(
            f"precision {metrics.precision} < "
            f"{expectations.expected_precision_at_least}"
        )
    if not _meets_floor(metrics.recall, expectations.expected_recall_at_least):
        failures.append(
            f"recall {metrics.recall} < {expectations.expected_recall_at_least}"
        )
    if metrics.event_miss_count:
        failures.append(f"missed expected events: {metrics.event_miss_count}")
    return tuple(failures)


def assert_fixture_expectations(
    fixture: CalibrationFixture,
    result: ReplayResult,
) -> CalibrationMetrics:
    metrics = evaluate_replay_result(fixture, result)
    failures = fixture_expectation_failures(fixture, metrics)
    metrics.expectation_failures = failures
    if failures:
        joined = "\n- ".join(failures)
        msg = f"{fixture.id} calibration failed:\n- {joined}"
        raise AssertionError(msg)
    return metrics


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    if not isinstance(raw, Mapping):
        msg = f"{path}: fixture must be a mapping"
        raise CalibrationFixtureError(msg)
    return dict(raw)


def _parse_circuit(raw: Any) -> CircuitConfig:
    if not isinstance(raw, Mapping):
        msg = "circuit entries must be mappings"
        raise CalibrationFixtureError(msg)
    sources = raw.get("sources", {})
    if not isinstance(sources, Mapping):
        msg = "circuit sources must be a mapping"
        raise CalibrationFixtureError(msg)
    sensors = tuple(
        SensorRef(
            entity_id=str(entity_id),
            role=role,
            unit=_unit_for_role(role),
        )
        for key, entity_id in sources.items()
        if (role := _ROLE_BY_SOURCE_KEY.get(str(key))) is not None
    )
    return CircuitConfig(
        circuit_id=str(raw["circuit_id"]),
        name=str(raw["name"]),
        appliance_profile=ApplianceProfile(str(raw["appliance_profile"])),
        mode=CircuitMode(str(raw["circuit_mode"])),
        sensors=sensors,
        retention_mode=RetentionMode(str(raw.get("retention_mode", "standard"))),
        power_flow=PowerFlowMode(str(raw.get("power_flow", "load"))),
        energy_usage_window_days=int(raw.get("energy_usage_window_days", 7)),
        daily_energy_spike_ratio=float(raw.get("daily_energy_spike_ratio", 0.25)),
    )


def _parse_sample(raw: Any, start_time: datetime) -> CalibrationSample:
    if not isinstance(raw, Mapping):
        msg = "sample entries must be mappings"
        raise CalibrationFixtureError(msg)
    t = int(raw["t"])
    states = raw.get("states", {})
    if not isinstance(states, Mapping):
        msg = "sample states must be a mapping"
        raise CalibrationFixtureError(msg)
    return CalibrationSample(
        timestamp=start_time + timedelta(seconds=t),
        t=t,
        states={str(key): value for key, value in states.items()},
    )


def _expand_segment(
    raw: Any,
    start_time: datetime,
    circuits: tuple[CircuitConfig, ...],
) -> list[CalibrationSample]:
    if not isinstance(raw, Mapping):
        msg = "segment entries must be mappings"
        raise CalibrationFixtureError(msg)
    pattern = str(raw.get("pattern", ""))
    if pattern == "cold_storage_signature":
        return _expand_cold_storage_signature_segment(raw, start_time, circuits)
    if pattern != "daily_energy_deltas":
        msg = f"unsupported calibration segment pattern: {pattern}"
        raise CalibrationFixtureError(msg)

    circuit = _segment_circuit(raw, circuits)
    sources = {sensor.role: sensor.entity_id for sensor in circuit.sensors}
    start_t = int(raw["start_t"])
    interval = int(raw["interval_seconds"])
    energy = float(raw["energy_start_kwh"])
    samples: list[CalibrationSample] = []
    for index, usage in enumerate(_required_list(raw, "daily_usage_kwh")):
        energy = round(energy + float(usage), 3)
        t = start_t + index * interval
        states: dict[str, Any] = {}
        _set_role_state(states, sources, SensorRole.REAL_POWER, raw, "power_w", index)
        _set_role_state(states, sources, SensorRole.CURRENT, raw, "current_a", index)
        _set_role_state(states, sources, SensorRole.VOLTAGE, raw, "voltage_v", index)
        if energy_entity := sources.get(SensorRole.ENERGY):
            states[energy_entity] = energy
        samples.append(
            CalibrationSample(
                timestamp=start_time + timedelta(seconds=t),
                t=t,
                states=states,
                completes_prior_energy_days=True,
            )
        )
    return samples


def _expand_cold_storage_signature_segment(
    raw: Mapping[str, Any],
    start_time: datetime,
    circuits: tuple[CircuitConfig, ...],
) -> list[CalibrationSample]:
    circuit = _segment_circuit(raw, circuits)
    sources = {sensor.role: sensor.entity_id for sensor in circuit.sensors}
    start_t = int(raw["start_t"])
    duration = int(raw["duration_seconds"])
    sample_interval = int(raw["sample_interval_seconds"])
    excursion_interval = int(raw["excursion_interval_seconds"])
    samples: list[CalibrationSample] = []
    for offset in range(0, duration, sample_interval):
        excursion = offset % excursion_interval == 0
        states: dict[str, Any] = {}
        values = {
            SensorRole.REAL_POWER: float(
                raw["excursion_power_w"] if excursion else raw["base_power_w"]
            ),
            SensorRole.CURRENT: float(
                raw["excursion_current_a"] if excursion else raw["base_current_a"]
            ),
            SensorRole.POWER_FACTOR: float(
                raw["excursion_power_factor"] if excursion else raw["base_power_factor"]
            ),
        }
        for role, value in values.items():
            entity_id = sources.get(role)
            if entity_id is None:
                raise CalibrationFixtureError(
                    f"{circuit.circuit_id} cold_storage_signature requires {role.value}"
                )
            states[entity_id] = value
        t = start_t + offset
        samples.append(
            CalibrationSample(
                timestamp=start_time + timedelta(seconds=t),
                t=t,
                states=states,
            )
        )
    return samples


def _mark_prior_energy_days_complete(
    store_data: FeatureStoreData,
    circuit_id: str,
    timestamp: datetime,
) -> None:
    history = store_data.energy_usage_by_circuit.get(circuit_id, {})
    days = history.get("days")
    if not isinstance(days, list):
        return
    today = timestamp.date().isoformat()
    for day in days:
        if isinstance(day, dict) and str(day.get("date", "")) < today:
            day["complete"] = True


def _parse_labels(raw: Mapping[str, Any]) -> CalibrationLabels:
    return CalibrationLabels(
        expected_events=tuple(
            ExpectedEvent(
                circuit_id=str(item["circuit_id"]),
                event_type=EventType(str(item["event_type"])),
                around_t=int(item["around_t"]),
                tolerance_seconds=int(item.get("tolerance_seconds", 0)),
            )
            for item in _optional_list(raw, "expected_events")
        ),
        expected_alerts=tuple(
            ExpectedAlert(
                circuit_id=str(item["circuit_id"]),
                feature=str(item.get("feature", "*")),
                earliest_t=int(item["earliest_t"]),
                latest_t=int(item["latest_t"]),
                severity=(
                    Severity(str(item["severity"])) if item.get("severity") else None
                ),
                min_repeated_count=int(item.get("min_repeated_count", 1)),
                min_confidence=_optional_float(item.get("min_confidence")),
            )
            for item in _optional_list(raw, "expected_alerts")
        ),
        expected_no_alerts=tuple(
            ExpectedNoAlert(
                circuit_id=str(item["circuit_id"]),
                feature=str(item.get("feature", "*")),
                start_t=int(item["start_t"]),
                end_t=int(item["end_t"]),
            )
            for item in _optional_list(raw, "expected_no_alerts")
        ),
        abnormal_condition_start_t=(
            int(raw["abnormal_condition_start_t"])
            if raw.get("abnormal_condition_start_t") is not None
            else None
        ),
        component_truth={
            str(component_id): ComponentTruth(
                edges=tuple(
                    ExpectedEvent(
                        circuit_id=str(component_id),
                        event_type=EventType(str(item["event_type"])),
                        around_t=int(item["around_t"]),
                        tolerance_seconds=int(item.get("tolerance_seconds", 0)),
                    )
                    for item in _optional_list(value, "edges")
                ),
                sessions=tuple(
                    ExpectedComponentSession(
                        start_t=int(item["start_t"]),
                        end_t=int(item["end_t"]),
                        tolerance_seconds=int(item.get("tolerance_seconds", 0)),
                    )
                    for item in _optional_list(value, "sessions")
                ),
                energy_kwh=_optional_float(value.get("energy_kwh")),
                corroborating_helper_circuit_ids=frozenset(
                    str(item)
                    for item in _optional_list(
                        value, "corroborating_helper_circuit_ids"
                    )
                ),
            )
            for component_id, value in _optional_mapping(raw, "component_truth").items()
            if isinstance(value, Mapping)
        },
    )


def _parse_expectations(raw: Mapping[str, Any]) -> CalibrationExpectations:
    return CalibrationExpectations(
        max_false_positive_alerts=_optional_int(raw.get("max_false_positive_alerts")),
        min_true_positive_alerts=_optional_int(raw.get("min_true_positive_alerts")),
        max_false_negative_alerts=_optional_int(raw.get("max_false_negative_alerts")),
        max_detection_latency_seconds=_optional_float(
            raw.get("max_detection_latency_seconds")
        ),
        expected_precision_at_least=_optional_float(
            raw.get("expected_precision_at_least")
        ),
        expected_recall_at_least=_optional_float(raw.get("expected_recall_at_least")),
    )


def _source_states_for_sample(
    circuit_config: CircuitConfig,
    sample: CalibrationSample,
) -> dict[str, SourceState]:
    states: dict[str, SourceState] = {}
    for sensor in circuit_config.sensors:
        if sensor.entity_id not in sample.states:
            continue
        raw_state = sample.states[sensor.entity_id]
        state_value, last_updated = _fixture_source_state(raw_state, sample.timestamp)
        states[sensor.entity_id] = SourceState(
            entity_id=sensor.entity_id,
            state=str(state_value),
            unit=sensor.unit or _unit_for_role(sensor.role),
            last_updated=last_updated,
        )
    return states


def _fixture_source_state(
    raw_state: Any,
    sample_timestamp: datetime,
) -> tuple[Any, datetime]:
    if not isinstance(raw_state, Mapping):
        return raw_state, sample_timestamp
    state_value = raw_state.get("state", raw_state.get("value", ""))
    offset = raw_state.get("last_updated_offset_seconds")
    if offset is None:
        return state_value, sample_timestamp
    return state_value, sample_timestamp + timedelta(seconds=float(offset))


def _apply_feature_result(
    result: FeatureResult,
    state: AnalyzerState,
    store_data: FeatureStoreData,
) -> tuple[list[CircuitEvent], list[AlertEvidence]]:
    if result.events:
        store_data.events.extend(result.events)
    if result.alerts:
        store_data.alerts.extend(result.alerts)
    for update in result.state_updates:
        _apply_state_update(state, update.path, update.value)
    active_alerts = [
        alert
        for alert in (*result.alerts, *result.preserved_alerts)
        if alert.feedback_status != "expected"
    ]
    return list(result.events), active_alerts


def _snapshot_state(state: AnalyzerState) -> dict[str, Any]:
    return {
        "daily_energy_usage_by_circuit": dict(state.daily_energy_usage_by_circuit),
        "energy_usage_evidence_by_circuit": dict(
            state.energy_usage_evidence_by_circuit
        ),
        "nilm_component_runtime_by_circuit": {
            circuit_id: {
                assignment_id: dict(component)
                for assignment_id, component in runtime.items()
            }
            for circuit_id, runtime in state.nilm_component_runtime_by_circuit.items()
        },
        "nilm_reconciliation_by_circuit": {
            circuit_id: dict(reconciliation)
            for circuit_id, reconciliation in (
                state.nilm_reconciliation_by_circuit.items()
            )
        },
    }


def _alert_matches(
    fixture: CalibrationFixture,
    expected: ExpectedAlert,
    alert: AlertEvidence,
) -> bool:
    offset = _offset_seconds(fixture, alert.timestamp)
    return (
        alert.circuit_id == expected.circuit_id
        and _feature_matches(expected.feature, alert.feature)
        and expected.earliest_t <= offset <= expected.latest_t
        and alert.repeated_count >= expected.min_repeated_count
        and _severity_matches(alert.severity, expected.severity)
        and _confidence_matches(alert, expected.min_confidence)
    )


def _alert_in_no_alert_window(
    fixture: CalibrationFixture,
    alert: AlertEvidence,
    window: ExpectedNoAlert,
) -> bool:
    offset = _offset_seconds(fixture, alert.timestamp)
    return (
        alert.circuit_id == window.circuit_id
        and _feature_matches(window.feature, alert.feature)
        and window.start_t <= offset <= window.end_t
    )


def _event_match_counts(
    fixture: CalibrationFixture,
    events: list[CircuitEvent],
) -> tuple[int, int]:
    matches = 0
    misses = 0
    used_indexes: set[int] = set()
    for expected in fixture.labels.expected_events:
        for index, event in enumerate(events):
            if index in used_indexes:
                continue
            offset = _offset_seconds(fixture, event.timestamp)
            if (
                event.circuit_id == expected.circuit_id
                and event.event_type is expected.event_type
                and abs(offset - expected.around_t) <= expected.tolerance_seconds
            ):
                used_indexes.add(index)
                matches += 1
                break
        else:
            misses += 1
    return matches, misses


def _component_metrics(
    fixture: CalibrationFixture, result: ReplayResult
) -> dict[str, ComponentReplayMetrics]:
    sessions = [
        item
        for history in result.store_data.nilm_session_history_by_circuit.values()
        for item in history
        if isinstance(item, Mapping)
    ]
    metrics: dict[str, ComponentReplayMetrics] = {}
    for component_id, truth in fixture.labels.component_truth.items():
        predicted = [
            item
            for item in sessions
            if str(item.get("assignment_id") or item.get("appliance_id") or "")
            == component_id
            and item.get("start")
            and item.get("end")
        ]
        matched: list[tuple[ExpectedComponentSession, Mapping[str, Any]]] = []
        unused = list(predicted)
        for expected in truth.sessions:
            for actual in unused:
                start_error = abs(
                    (
                        _parse_datetime(str(actual["start"])) - fixture.start_time
                    ).total_seconds()
                    - expected.start_t
                )
                stop_error = abs(
                    (
                        _parse_datetime(str(actual["end"])) - fixture.start_time
                    ).total_seconds()
                    - expected.end_t
                )
                if max(start_error, stop_error) <= expected.tolerance_seconds:
                    matched.append((expected, actual))
                    unused.remove(actual)
                    break
        session_precision = _ratio_or_none(len(matched), len(predicted))
        session_recall = _ratio_or_none(len(matched), len(truth.sessions))
        start_errors = [
            abs(
                (
                    _parse_datetime(str(actual["start"])) - fixture.start_time
                ).total_seconds()
                - expected.start_t
            )
            for expected, actual in matched
        ]
        stop_errors = [
            abs(
                (
                    _parse_datetime(str(actual["end"])) - fixture.start_time
                ).total_seconds()
                - expected.end_t
            )
            for expected, actual in matched
        ]
        predicted_edges = [
            (event_type, _parse_datetime(str(actual[key])))
            for actual in predicted
            for event_type, key in (
                (EventType.START, "start"),
                (EventType.STOP, "end"),
            )
        ]
        unmatched_edges = list(predicted_edges)
        matched_edges = 0
        for expected in truth.edges:
            for actual in unmatched_edges:
                if actual[0] is expected.event_type and abs(
                    (actual[1] - fixture.start_time).total_seconds()
                    - expected.around_t
                ) <= expected.tolerance_seconds:
                    matched_edges += 1
                    unmatched_edges.remove(actual)
                    break
        actual_energy = sum(float(item.get("energy_kwh", 0.0)) for item in predicted)
        absolute_error = (
            abs(actual_energy - truth.energy_kwh)
            if truth.energy_kwh is not None
            else None
        )
        metrics[component_id] = ComponentReplayMetrics(
            edge_precision=_ratio_or_none(matched_edges, len(predicted_edges)),
            edge_recall=_ratio_or_none(matched_edges, len(truth.edges)),
            session_precision=session_precision,
            session_recall=session_recall,
            session_f1=_f1(session_precision, session_recall),
            median_start_error_seconds=median(start_errors) if start_errors else None,
            median_stop_error_seconds=median(stop_errors) if stop_errors else None,
            energy_absolute_error_kwh=round(absolute_error, 6)
            if absolute_error is not None
            else None,
            energy_percentage_error=round(absolute_error / truth.energy_kwh * 100, 3)
            if absolute_error is not None and truth.energy_kwh
            else None,
        )
    return metrics


def _combined_reconciliation(result: ReplayResult) -> dict[str, Any]:
    items = list(result.final_state.nilm_reconciliation_by_circuit.values())
    return {
        key: sum(float(item.get(key, 0)) for item in items)
        for key in (
            "residual_energy_kwh",
            "ambiguous_event_count",
            "total_event_count",
            "conservation_violations",
        )
    }


def _false_helper_association_rate(
    fixture: CalibrationFixture, result: ReplayResult
) -> float | None:
    records: list[bool] = []
    unused_truth = {
        component_id: list(truth.sessions)
        for component_id, truth in fixture.labels.component_truth.items()
    }
    for sessions in result.store_data.nilm_session_history_by_circuit.values():
        for session in sessions:
            component_id = str(
                session.get("assignment_id") or session.get("appliance_id") or ""
            )
            truth = fixture.labels.component_truth.get(component_id)
            matching_truth = next((
                expected
                for expected in unused_truth.get(component_id, ())
                if max(
                    abs(
                        (_parse_datetime(str(session["start"])) - fixture.start_time)
                        .total_seconds()
                        - expected.start_t
                    ),
                    abs(
                        (_parse_datetime(str(session["end"])) - fixture.start_time)
                        .total_seconds()
                        - expected.end_t
                    ),
                )
                <= expected.tolerance_seconds
            ), None)
            session_matches = matching_truth is not None
            if matching_truth is not None:
                unused_truth[component_id].remove(matching_truth)
            for evidence in session.get("helper_evidence", ()):
                if evidence.get("relationship") != "corroborates":
                    continue
                records.append(
                    session_matches
                    and str(evidence.get("helper_circuit_id") or "")
                    in truth.corroborating_helper_circuit_ids
                )
    return _ratio_or_none(records.count(False), len(records))


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return round(2 * precision * recall / (precision + recall), 3)


def _confidence_calibration(
    alerts: list[AlertEvidence],
    matched_alert_indexes: set[int],
) -> tuple[dict[str, dict[str, float]], float | None, float | None]:
    bins = {
        label: {
            "alert_count": 0.0,
            "true_positive_count": 0.0,
            "false_positive_count": 0.0,
            "observed_accuracy": 0.0,
            "average_score": 0.0,
        }
        for label in CALIBRATION_CONFIDENCE_BINS
    }
    scored: list[tuple[float, float]] = []
    for index, alert in enumerate(alerts):
        score = _calibration_score(alert)
        outcome = 1.0 if index in matched_alert_indexes else 0.0
        scored.append((score, outcome))
        label = _bin_label(score)
        bucket = bins[label]
        bucket["alert_count"] += 1.0
        bucket["true_positive_count"] += outcome
        bucket["false_positive_count"] += 1.0 - outcome
        bucket["average_score"] += score

    for bucket in bins.values():
        count = bucket["alert_count"]
        if count > 0.0:
            bucket["average_score"] = round(bucket["average_score"] / count, 3)
            bucket["observed_accuracy"] = round(
                bucket["true_positive_count"] / count,
                3,
            )

    if not scored:
        return bins, None, None

    brier = round(
        sum((score - outcome) ** 2 for score, outcome in scored) / len(scored),
        3,
    )
    ece = 0.0
    for bucket in bins.values():
        count = bucket["alert_count"]
        if count == 0.0:
            continue
        ece += (count / len(scored)) * abs(
            bucket["average_score"] - bucket["observed_accuracy"]
        )
    return bins, brier, round(ece, 3)


def _calibration_score(alert: AlertEvidence) -> float:
    repeated_score = min(max(alert.repeated_count, 0) / 3.0, 1.0)
    ratio_score = 0.0
    if alert.baseline_value > 0.0:
        ratio_score = min(
            max(alert.observed_value / alert.baseline_value, 0.0) / 2.0,
            1.0,
        )
    threshold_ratio = _float_from_features(alert.features, "threshold_ratio")
    daily_usage_share = _float_from_features(alert.features, "daily_usage_share")
    if threshold_ratio and daily_usage_share is not None:
        ratio_score = max(
            ratio_score,
            min(max(daily_usage_share / threshold_ratio, 0.0) / 2.0, 1.0),
        )
    baseline_confidence = _baseline_confidence(alert)
    score = 0.35 * repeated_score + 0.35 * ratio_score + 0.30 * baseline_confidence
    return round(min(max(score, 0.0), 1.0), 3)


def _baseline_confidence(alert: AlertEvidence) -> float:
    contextual = _float_from_features(alert.features, "contextual_baseline_confidence")
    if contextual is not None:
        return min(max(contextual, 0.0), 1.0)
    sample_count = _float_from_features(alert.features, "baseline_day_count")
    window = _float_from_features(alert.features, "baseline_window_days")
    if sample_count is not None and window and window > 0.0:
        return min(max(sample_count / window, 0.0), 1.0)
    return 1.0 if alert.repeated_count >= 3 else 0.0


def _detection_latency(
    fixture: CalibrationFixture,
    matched_alert_offsets: list[float],
) -> float | None:
    if fixture.labels.abnormal_condition_start_t is None or not matched_alert_offsets:
        return None
    return min(matched_alert_offsets) - fixture.labels.abnormal_condition_start_t


def _offset_seconds(fixture: CalibrationFixture, timestamp: datetime) -> float:
    return (timestamp - fixture.start_time).total_seconds()


def _feature_matches(expected: str, actual: str) -> bool:
    return expected == "*" or expected == actual


def _severity_matches(actual: Severity, expected: Severity | None) -> bool:
    if expected is None:
        return True
    return _SEVERITY_ORDER[actual] >= _SEVERITY_ORDER[expected]


def _confidence_matches(alert: AlertEvidence, minimum: float | None) -> bool:
    return minimum is None or _calibration_score(alert) >= minimum


def _ratio_or_none(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 3)


def _meets_floor(value: float | None, floor: float | None) -> bool:
    if floor is None:
        return True
    return value is not None and value >= floor


def _bin_label(score: float) -> str:
    if score < 0.2:
        return "0.0-0.2"
    if score < 0.4:
        return "0.2-0.4"
    if score < 0.6:
        return "0.4-0.6"
    if score < 0.8:
        return "0.6-0.8"
    return "0.8-1.0"


def _float_from_features(features: Mapping[str, Any], key: str) -> float | None:
    try:
        value = features.get(key)
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _set_role_state(
    states: dict[str, Any],
    sources: Mapping[SensorRole, str],
    role: SensorRole,
    raw: Mapping[str, Any],
    key: str,
    index: int,
) -> None:
    entity_id = sources.get(role)
    if entity_id is None or key not in raw:
        return
    states[entity_id] = _indexed_value(raw[key], index)


def _indexed_value(raw: Any, index: int) -> Any:
    if isinstance(raw, list):
        return raw[index]
    return raw


def _segment_circuit(
    raw: Mapping[str, Any],
    circuits: tuple[CircuitConfig, ...],
) -> CircuitConfig:
    circuit_id = raw.get("circuit_id")
    if circuit_id is None:
        return circuits[0]
    for circuit in circuits:
        if circuit.circuit_id == circuit_id:
            return circuit
    msg = f"segment references unknown circuit_id: {circuit_id}"
    raise CalibrationFixtureError(msg)


def _required_mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    if not isinstance(value, Mapping):
        msg = f"{key} must be a mapping"
        raise CalibrationFixtureError(msg)
    return value


def _required_list(raw: Mapping[str, Any], key: str) -> list[Any]:
    value = raw.get(key)
    if not isinstance(value, list):
        msg = f"{key} must be a list"
        raise CalibrationFixtureError(msg)
    return value


def _optional_list(raw: Mapping[str, Any], key: str) -> list[Any]:
    value = raw.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        msg = f"{key} must be a list"
        raise CalibrationFixtureError(msg)
    return value


def _optional_mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key, {})
    if not isinstance(value, Mapping):
        msg = f"{key} must be a mapping"
        raise CalibrationFixtureError(msg)
    return value


def _validate_block_ids(items: list[Any], key: str, label: str) -> None:
    ids = [
        str(item.get(key) or "").strip()
        for item in items
        if isinstance(item, Mapping)
    ]
    invalid = len(ids) != len(items) or any(not item for item in ids)
    if invalid or len(set(ids)) != len(ids):
        msg = f"{label} IDs must be nonempty and unique"
        raise CalibrationFixtureError(msg)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        msg = "fixture start_time must include a timezone"
        raise CalibrationFixtureError(msg)
    return parsed


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _unit_for_role(role: SensorRole) -> str | None:
    return {
        SensorRole.REAL_POWER: "W",
        SensorRole.REACTIVE_POWER: "var",
        SensorRole.APPARENT_POWER: "VA",
        SensorRole.ENERGY: "kWh",
        SensorRole.CURRENT: "A",
        SensorRole.VOLTAGE: "V",
        SensorRole.POWER_FACTOR: None,
        SensorRole.FREQUENCY: "Hz",
    }[role]
