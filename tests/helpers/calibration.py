from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import isfinite
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
    StateReducer,
)
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
from custom_components.circuitsetup_energy_analyzer.nilm import (
    NilmResidualPowerPoint,
    NilmResidualTraceMetadata,
    normalize_nilm_assignment_model,
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
_REPLAY_RUNTIME_EVIDENCE_MAX_ITEMS = 12
_REPLAY_RUNTIME_TEXT_MAX_CHARS = 256
_REPLAY_RUNTIME_TIMESTAMP_MAX_CHARS = 64

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
    restart_before_sample: bool = False


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
class ReplaySplit:
    training_end_t: int
    evaluation_start_t: int


@dataclass(frozen=True, slots=True)
class ExpectedStateSegment:
    start_t: int
    end_t: int
    state_id: str


@dataclass(frozen=True, slots=True)
class CalibrationLabels:
    expected_events: tuple[ExpectedEvent, ...] = ()
    expected_alerts: tuple[ExpectedAlert, ...] = ()
    expected_no_alerts: tuple[ExpectedNoAlert, ...] = ()
    abnormal_condition_start_t: int | None = None
    component_truth: dict[str, ComponentTruth] = field(default_factory=dict)
    replay_split: ReplaySplit | None = None


@dataclass(frozen=True, slots=True)
class ExpectedComponentSession:
    start_t: int
    end_t: int
    tolerance_seconds: int = 0


@dataclass(frozen=True, slots=True)
class ComponentTruth:
    edges: tuple[ExpectedEvent, ...] = ()
    sessions: tuple[ExpectedComponentSession, ...] = ()
    state_segments: tuple[ExpectedStateSegment, ...] = ()
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
    min_component_session_f1: float | None = None
    min_component_edge_f1: float | None = None
    min_component_state_accuracy: float | None = None
    max_residual_energy_kwh: float | None = None
    max_false_assignment_rate: float | None = None
    max_conservation_violations: int | None = None
    max_nilm_brier_score: float | None = None
    max_nilm_expected_calibration_error: float | None = None
    require_replay_split: bool = False
    require_frozen_pre_split_models: bool = False
    require_duration_decision_benefit: bool = False


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
    initial_runtime_by_circuit: dict[str, dict[str, dict[str, Any]]] = field(
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
    residual_trace_points_by_circuit: dict[
        str, tuple[NilmResidualPowerPoint, ...]
    ] = field(default_factory=dict)
    residual_trace_metadata_by_circuit: dict[
        str, NilmResidualTraceMetadata
    ] = field(default_factory=dict)
    processing_work_units: int = 0
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
    false_assignment_rate: float | None = None
    nilm_confidence_bins: dict[str, dict[str, float]] = field(default_factory=dict)
    nilm_brier_score: float | None = None
    nilm_expected_calibration_error: float | None = None
    residual_plateau_mae_w: float | None = None
    session_energy_mae_kwh: float | None = None
    stale_subtraction_incidents: int = 0
    measured_session_count: int = 0
    partial_session_count: int = 0
    fallback_session_count: int = 0
    unavailable_session_count: int = 0
    measured_session_percentage: float | None = None
    partial_session_percentage: float | None = None
    fallback_session_percentage: float | None = None
    unavailable_session_percentage: float | None = None
    replay_processing_work_units: int = 0
    decision_impacts: ReplayDecisionImpacts = field(
        default_factory=lambda: ReplayDecisionImpacts()
    )
    replay_split: ReplaySplit | None = None
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
    median_duration_error_seconds: float | None
    interval_iou: float | None
    state_accuracy: float | None
    observed_active_state_count: int
    energy_absolute_error_kwh: float | None
    energy_percentage_error: float | None


@dataclass(frozen=True, slots=True)
class ReplayDecisionImpact:
    changed_count: int = 0
    changed_correct_count: int = 0
    changed_incorrect_count: int = 0
    changed_neutral_count: int = 0
    changed_unscored_count: int = 0


@dataclass(frozen=True, slots=True)
class ReplayDecisionImpacts:
    duration: ReplayDecisionImpact = field(default_factory=ReplayDecisionImpact)
    validation: ReplayDecisionImpact = field(default_factory=ReplayDecisionImpact)


@dataclass(frozen=True, slots=True)
class ReplayGateResult:
    passed: bool
    violations: tuple[str, ...]


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

    source_kind = None
    if raw.get("source_kind") and circuits:
        production_kinds = {
            kind.value
            for circuit in circuits
            if (kind := nilm_source_kind(circuit)) is not None
        }
        if (
            len(production_kinds) != 1
            or str(raw["source_kind"]) not in production_kinds
        ):
            msg = (
                f"{path}: declared source_kind {raw['source_kind']!r} does not "
                f"match one unambiguous production source kind: "
                f"{sorted(production_kinds)}"
            )
            raise CalibrationFixtureError(msg)
        source_kind = production_kinds.pop()

    labels = _parse_labels(_required_mapping(raw, "labels"))
    if labels.replay_split and any(
        sample.t < labels.replay_split.evaluation_start_t for sample in samples
    ):
        msg = (
            f"{path}: evaluation samples must begin at or after "
            "replay_split.evaluation_start_t"
        )
        raise CalibrationFixtureError(msg)
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
    initial_runtime = _optional_mapping(raw, "initial_nilm_runtime_by_circuit")
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
        source_kind=source_kind,
        assignments_by_circuit={
            str(circuit_id): [
                dict(item) for item in values if isinstance(item, Mapping)
            ]
            for circuit_id, values in assignments.items()
            if isinstance(values, list)
        },
        initial_runtime_by_circuit={
            str(circuit_id): {
                str(assignment_id): dict(runtime)
                for assignment_id, runtime in runtimes.items()
                if isinstance(runtime, Mapping)
            }
            for circuit_id, runtimes in initial_runtime.items()
            if isinstance(runtimes, Mapping)
        },
        entry_id=(str(raw["entry_id"]) if raw.get("entry_id") else None),
        entries=entries,
        min_delta_w=float(raw.get("min_delta_w", 100.0)),
    )


def replay_fixture_processors(fixture: CalibrationFixture) -> ReplayResult:
    state = AnalyzerState()
    state.nilm_component_runtime_by_circuit = {
        circuit_id: {
            assignment_id: dict(runtime) for assignment_id, runtime in runtimes.items()
        }
        for circuit_id, runtimes in fixture.initial_runtime_by_circuit.items()
    }
    store_data = FeatureStoreData(
        nilm_appliance_assignments_by_circuit={
            circuit_id: [dict(item) for item in assignments]
            for circuit_id, assignments in fixture.assignments_by_circuit.items()
        }
    )

    def build_processors() -> tuple[
        CircuitEventProcessor,
        NilmSampleProcessor,
        RunCycleProcessor,
        EnergyUsageProcessor,
    ]:
        alert_policies: dict[str, ConservativeAlertPolicy] = {}
        cycle_alert_policies: dict[str, ConservativeAlertPolicy] = {}
        return (
            CircuitEventProcessor(),
            NilmSampleProcessor(
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
            ),
            RunCycleProcessor(
                alert_policy_for_circuit=lambda circuit_id: (
                    cycle_alert_policies.setdefault(
                        circuit_id,
                        ConservativeAlertPolicy(
                            min_repeated=3,
                            min_total_score=4.5,
                            min_average_score=1.5,
                            min_baseline_confidence=0.6,
                        ),
                    )
                ),
                learning_mature=lambda _config, _now: False,
            ),
            EnergyUsageProcessor(
                settings_for_config=lambda config, _circuit_id: EnergyUsageSettings(
                    window_days=config.energy_usage_window_days if config else 7,
                    daily_spike_ratio=(
                        config.daily_energy_spike_ratio if config else 0.25
                    ),
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
            ),
        )

    (
        event_processor,
        nilm_processor,
        run_cycle_processor,
        energy_usage_processor,
    ) = build_processors()
    hass = SimpleNamespace(data={DOMAIN: {}})
    state_reducer = StateReducer()
    events: list[CircuitEvent] = []
    alerts: list[AlertEvidence] = []
    setup_issues: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    processing_work_units = 0
    residual_trace_metadata_by_circuit: dict[
        str, NilmResidualTraceMetadata
    ] = {}
    source_values_by_entity: dict[str, tuple[Any, datetime]] = {}

    for calibration_sample in fixture.samples:
        if calibration_sample.restart_before_sample:
            _merge_replay_residual_trace_diagnostics(
                residual_trace_metadata_by_circuit,
                nilm_processor,
            )
            state = AnalyzerState()
            state_reducer = StateReducer()
            (
                event_processor,
                nilm_processor,
                run_cycle_processor,
                energy_usage_processor,
            ) = build_processors()
        changed_entities = _update_replay_source_values(
            source_values_by_entity,
            calibration_sample,
        )
        processing_circuit_ids = _replay_processing_circuit_ids(
            fixture,
            changed_entities,
        )
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
        normalized_samples: list[tuple[CircuitConfig, Any]] = []
        for circuit_config in fixture.circuits:
            normalized_sample = build_circuit_sample(
                circuit_config,
                _source_states_from_replay_values(
                    circuit_config,
                    source_values_by_entity,
                ),
                calibration_sample.timestamp,
            )
            state_reducer.refresh_latest_real_power_state(
                state,
                circuit_config,
                normalized_sample,
            )
            if circuit_config.circuit_id in processing_circuit_ids:
                setup_issues.extend(
                    {
                        "timestamp": calibration_sample.timestamp.isoformat(),
                        "circuit_id": circuit_config.circuit_id,
                        "issue": issue,
                    }
                    for issue in normalized_sample.quality_issues
                )
            normalized_samples.append((circuit_config, normalized_sample))

        for circuit_config, normalized_sample in normalized_samples:
            if circuit_config.circuit_id not in processing_circuit_ids:
                continue
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
            processing_work_units += len(results)
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
        snapshots.append(_snapshot_state(state, nilm_processor, store_data))

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
        residual_trace_points_by_circuit={
            circuit_id: tuple(trace)
            for circuit_id, trace in (
                nilm_processor._residual_power_trace_by_circuit.items()  # noqa: SLF001
            )
        },
        residual_trace_metadata_by_circuit=_merged_replay_residual_trace_metadata(
            residual_trace_metadata_by_circuit,
            nilm_processor,
        ),
        processing_work_units=processing_work_units,
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
    component_metrics = _component_metrics(fixture, result)
    residual_trace_metrics = _residual_trace_replay_metrics(
        result,
        component_metrics,
    )
    nilm_confidence_bins, nilm_brier, nilm_ece = _nilm_confidence_calibration(
        fixture,
        result,
    )
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
        component_metrics=component_metrics,
        residual_energy_kwh=float(reconciliation.get("residual_energy_kwh", 0.0)),
        false_helper_association_rate=_false_helper_association_rate(fixture, result),
        ambiguous_event_rate=_ratio_or_none(
            int(reconciliation.get("ambiguous_event_count", 0)),
            int(reconciliation.get("total_event_count", 0)),
        )
        or 0.0,
        conservation_violations=int(reconciliation.get("conservation_violations", 0)),
        false_assignment_rate=_false_assignment_rate(fixture, result),
        nilm_confidence_bins=nilm_confidence_bins,
        nilm_brier_score=nilm_brier,
        nilm_expected_calibration_error=nilm_ece,
        **residual_trace_metrics,
        decision_impacts=_decision_impacts(fixture, result),
        replay_split=fixture.labels.replay_split,
    )


def _residual_trace_replay_metrics(
    result: ReplayResult,
    component_metrics: Mapping[str, ComponentReplayMetrics],
) -> dict[str, int | float | None]:
    """Summarize session and bounded in-memory trace evidence for a replay."""
    sessions = _completed_nilm_sessions(result)
    sources = [
        str(session.get("energy_source") or "unavailable") for session in sessions
    ]
    plateau_errors = [
        abs(float(session["plateau_power_w"]) - abs(float(session["on_delta_w"])))
        for session in sessions
        if isinstance(session.get("plateau_power_w"), (int, float))
        and isinstance(session.get("on_delta_w"), (int, float))
    ]
    energy_errors = [
        component.energy_absolute_error_kwh
        for component in component_metrics.values()
        if component.energy_absolute_error_kwh is not None
    ]
    stale_incidents = sum(
        metadata.stale_subtraction_prevented_count
        for metadata in result.residual_trace_metadata_by_circuit.values()
    )
    total_sessions = len(sources)
    source_percentages = {
        source: (
            round(100.0 * sources.count(source) / total_sessions, 3)
            if total_sessions
            else None
        )
        for source in (
            "residual_trace_measured",
            "residual_trace_partial",
            "transition_fallback",
            "unavailable",
        )
    }
    return {
        "residual_plateau_mae_w": (
            round(sum(plateau_errors) / len(plateau_errors), 6)
            if plateau_errors
            else None
        ),
        "session_energy_mae_kwh": (
            round(sum(energy_errors) / len(energy_errors), 6)
            if energy_errors
            else None
        ),
        "stale_subtraction_incidents": stale_incidents,
        "measured_session_count": sources.count("residual_trace_measured"),
        "partial_session_count": sources.count("residual_trace_partial"),
        "fallback_session_count": sources.count("transition_fallback"),
        "unavailable_session_count": sources.count("unavailable"),
        "measured_session_percentage": source_percentages[
            "residual_trace_measured"
        ],
        "partial_session_percentage": source_percentages[
            "residual_trace_partial"
        ],
        "fallback_session_percentage": source_percentages["transition_fallback"],
        "unavailable_session_percentage": source_percentages["unavailable"],
        "replay_processing_work_units": result.processing_work_units,
    }


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
    if expectations.min_component_session_f1 is not None:
        if not metrics.component_metrics:
            failures.append("component replay metrics were not available")
        for component_id, component in metrics.component_metrics.items():
            if not _meets_floor(
                component.session_f1,
                expectations.min_component_session_f1,
            ):
                failures.append(
                    f"{component_id} session F1 {component.session_f1} < "
                    f"{expectations.min_component_session_f1}"
                )
    if expectations.min_component_edge_f1 is not None:
        for component_id, truth in fixture.labels.component_truth.items():
            if not truth.edges:
                continue
            component = metrics.component_metrics.get(component_id)
            if component is None:
                failures.append(f"{component_id} edge F1 was not available")
                continue
            edge_f1 = _f1(component.edge_precision, component.edge_recall)
            if edge_f1 is None:
                failures.append(f"{component_id} edge F1 was not available")
            elif not _meets_floor(edge_f1, expectations.min_component_edge_f1):
                failures.append(
                    f"{component_id} edge F1 {edge_f1} < "
                    f"{expectations.min_component_edge_f1}"
                )
    if expectations.min_component_state_accuracy is not None:
        for component_id, truth in fixture.labels.component_truth.items():
            if not truth.state_segments:
                continue
            component = metrics.component_metrics.get(component_id)
            if component is None or component.state_accuracy is None:
                failures.append(f"{component_id} state accuracy was not available")
            elif not _meets_floor(
                component.state_accuracy, expectations.min_component_state_accuracy
            ):
                failures.append(
                    f"{component_id} state accuracy {component.state_accuracy} < "
                    f"{expectations.min_component_state_accuracy}"
                )
    if (
        expectations.max_residual_energy_kwh is not None
        and metrics.residual_energy_kwh > expectations.max_residual_energy_kwh
    ):
        failures.append(
            f"residual energy {metrics.residual_energy_kwh} > "
            f"{expectations.max_residual_energy_kwh}"
        )
    if (
        expectations.max_false_assignment_rate is not None
        and (
            metrics.false_assignment_rate is None
            or metrics.false_assignment_rate > expectations.max_false_assignment_rate
        )
    ):
        failures.append(
            f"false assignment rate {metrics.false_assignment_rate} > "
            f"{expectations.max_false_assignment_rate}"
        )
    if (
        expectations.max_conservation_violations is not None
        and metrics.conservation_violations > expectations.max_conservation_violations
    ):
        failures.append(
            f"conservation violations {metrics.conservation_violations} > "
            f"{expectations.max_conservation_violations}"
        )
    if expectations.require_replay_split and not _valid_replay_split(
        metrics.replay_split
    ):
        failures.append("replay split provenance is required")
    if (
        expectations.require_frozen_pre_split_models
        and not _has_frozen_pre_split_models(fixture)
    ):
        failures.append("frozen pre-split NILM model provenance is required")
    if expectations.max_nilm_brier_score is not None and (
        metrics.nilm_brier_score is None
        or metrics.nilm_brier_score > expectations.max_nilm_brier_score
    ):
        failures.append(
            f"NILM Brier score {metrics.nilm_brier_score} > "
            f"{expectations.max_nilm_brier_score}"
        )
    if expectations.max_nilm_expected_calibration_error is not None and (
        metrics.nilm_expected_calibration_error is None
        or metrics.nilm_expected_calibration_error
        > expectations.max_nilm_expected_calibration_error
    ):
        failures.append(
            "NILM expected calibration error "
            f"{metrics.nilm_expected_calibration_error} > "
            f"{expectations.max_nilm_expected_calibration_error}"
        )
    if expectations.require_duration_decision_benefit:
        impact = metrics.decision_impacts.duration
        if (
            impact.changed_count == 0
            or impact.changed_correct_count <= impact.changed_incorrect_count
        ):
            failures.append("duration score decisions did not demonstrate net benefit")
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
        restart_before_sample=raw.get("restart") is True,
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
    replay_split_raw = raw.get("replay_split")
    replay_split = None
    if replay_split_raw is not None:
        if not isinstance(replay_split_raw, Mapping):
            msg = "replay_split must be a mapping"
            raise CalibrationFixtureError(msg)
        replay_split = ReplaySplit(
            training_end_t=int(replay_split_raw["training_end_t"]),
            evaluation_start_t=int(replay_split_raw["evaluation_start_t"]),
        )
        if replay_split.training_end_t >= replay_split.evaluation_start_t:
            msg = "replay_split.training_end_t must precede evaluation_start_t"
            raise CalibrationFixtureError(msg)
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
            str(component_id): _parse_component_truth(str(component_id), value)
            for component_id, value in _optional_mapping(raw, "component_truth").items()
            if isinstance(value, Mapping)
        },
        replay_split=replay_split,
    )


def _parse_component_truth(component_id: str, raw: Mapping[str, Any]) -> ComponentTruth:
    state_segments = tuple(
        ExpectedStateSegment(
            start_t=int(item["start_t"]),
            end_t=int(item["end_t"]),
            state_id=str(item["state_id"]),
        )
        for item in _optional_list(raw, "state_segments")
    )
    if any(segment.end_t <= segment.start_t for segment in state_segments):
        msg = f"{component_id} state_segments must have positive durations"
        raise CalibrationFixtureError(msg)
    if any(
        later.start_t < earlier.end_t
        for earlier, later in zip(state_segments, state_segments[1:], strict=False)
    ):
        msg = f"{component_id} state_segments must not overlap"
        raise CalibrationFixtureError(msg)
    return ComponentTruth(
        edges=tuple(
            ExpectedEvent(
                circuit_id=component_id,
                event_type=EventType(str(item["event_type"])),
                around_t=int(item["around_t"]),
                tolerance_seconds=int(item.get("tolerance_seconds", 0)),
            )
            for item in _optional_list(raw, "edges")
        ),
        sessions=tuple(
            ExpectedComponentSession(
                start_t=int(item["start_t"]),
                end_t=int(item["end_t"]),
                tolerance_seconds=int(item.get("tolerance_seconds", 0)),
            )
            for item in _optional_list(raw, "sessions")
        ),
        state_segments=state_segments,
        energy_kwh=_optional_float(raw.get("energy_kwh")),
        corroborating_helper_circuit_ids=frozenset(
            str(item)
            for item in _optional_list(raw, "corroborating_helper_circuit_ids")
        ),
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
        min_component_session_f1=_optional_float(
            raw.get("min_component_session_f1")
        ),
        min_component_edge_f1=_optional_float(raw.get("min_component_edge_f1")),
        min_component_state_accuracy=_optional_float(
            raw.get("min_component_state_accuracy")
        ),
        max_residual_energy_kwh=_optional_float(raw.get("max_residual_energy_kwh")),
        max_false_assignment_rate=_optional_float(
            raw.get("max_false_assignment_rate")
        ),
        max_conservation_violations=_optional_int(
            raw.get("max_conservation_violations")
        ),
        max_nilm_brier_score=_optional_float(raw.get("max_nilm_brier_score")),
        max_nilm_expected_calibration_error=_optional_float(
            raw.get("max_nilm_expected_calibration_error")
        ),
        require_replay_split=raw.get("require_replay_split") is True,
        require_frozen_pre_split_models=(
            raw.get("require_frozen_pre_split_models") is True
        ),
        require_duration_decision_benefit=(
            raw.get("require_duration_decision_benefit") is True
        ),
    )


def _merge_replay_residual_trace_diagnostics(
    metadata_by_circuit: dict[str, NilmResidualTraceMetadata],
    nilm_processor: NilmSampleProcessor,
) -> None:
    """Accumulate bounded processor-lifetime trace diagnostics across restarts."""
    metadata_by_circuit.update(
        _merged_replay_residual_trace_metadata(metadata_by_circuit, nilm_processor)
    )


def _merged_replay_residual_trace_metadata(
    prior: Mapping[str, NilmResidualTraceMetadata],
    nilm_processor: NilmSampleProcessor,
) -> dict[str, NilmResidualTraceMetadata]:
    """Combine restart-separated bounded counters without inventing trace history."""
    merged = dict(prior)
    for (
        circuit_id,
        metadata,
    ) in nilm_processor._residual_trace_metadata_by_circuit.items():  # noqa: SLF001
        previous = merged.get(circuit_id)
        if previous is None:
            merged[circuit_id] = metadata
            continue
        merged[circuit_id] = NilmResidualTraceMetadata(
            configured_horizon_seconds=metadata.configured_horizon_seconds,
            point_cap=metadata.point_cap,
            point_cap_truncated=metadata.point_cap_truncated,
            oldest_point_at=metadata.oldest_point_at,
            newest_point_at=metadata.newest_point_at,
            stale_subtraction_prevented_count=min(
                previous.stale_subtraction_prevented_count
                + metadata.stale_subtraction_prevented_count,
                1_000_000,
            ),
            partial_residual_point_count=min(
                previous.partial_residual_point_count
                + metadata.partial_residual_point_count,
                1_000_000,
            ),
            negative_residual_point_count=min(
                previous.negative_residual_point_count
                + metadata.negative_residual_point_count,
                1_000_000,
            ),
            trace_point_cap_truncation_count=min(
                previous.trace_point_cap_truncation_count
                + metadata.trace_point_cap_truncation_count,
                1_000_000,
            ),
        )
    return merged


def _update_replay_source_values(
    source_values_by_entity: dict[str, tuple[Any, datetime]],
    sample: CalibrationSample,
) -> frozenset[str]:
    """Apply fixture source updates while retaining HA's current source states."""
    changed_entities: set[str] = set()
    for entity_id, raw_state in sample.states.items():
        state_value, last_updated = _fixture_source_state(raw_state, sample.timestamp)
        source_values_by_entity[entity_id] = (state_value, last_updated)
        if not (
            isinstance(raw_state, Mapping)
            and raw_state.get("last_updated_offset_seconds") is not None
        ):
            changed_entities.add(entity_id)
    return frozenset(changed_entities)


def _replay_processing_circuit_ids(
    fixture: CalibrationFixture,
    changed_entities: frozenset[str],
) -> frozenset[str]:
    """Mirror coordinator source-update selection for calibration replays."""
    all_circuit_ids = frozenset(
        circuit_config.circuit_id for circuit_config in fixture.circuits
    )
    if not changed_entities:
        return all_circuit_ids

    known_source_entity_ids = {
        sensor.entity_id
        for circuit_config in fixture.circuits
        for sensor in circuit_config.sensors
    }
    mains_voltage_entity_ids = {
        sensor.entity_id
        for circuit_config in fixture.circuits
        if nilm_source_kind(circuit_config) is not None
        for sensor in circuit_config.sensors
        if sensor.role is SensorRole.VOLTAGE
    }
    if (
        changed_entities & mains_voltage_entity_ids
        or not changed_entities.issubset(known_source_entity_ids)
    ):
        return all_circuit_ids

    selected_circuit_ids = {
        circuit_config.circuit_id
        for circuit_config in fixture.circuits
        if any(
            sensor.entity_id in changed_entities
            for sensor in circuit_config.sensors
        )
    }
    if not selected_circuit_ids:
        return all_circuit_ids

    if any(
        nilm_source_kind(circuit_config) is None
        for circuit_config in fixture.circuits
        if circuit_config.circuit_id in selected_circuit_ids
    ):
        selected_circuit_ids.update(
            circuit_config.circuit_id
            for circuit_config in fixture.circuits
            if nilm_source_kind(circuit_config) is not None
        )
    return frozenset(selected_circuit_ids)


def _source_states_from_replay_values(
    circuit_config: CircuitConfig,
    source_values_by_entity: Mapping[str, tuple[Any, datetime]],
) -> dict[str, SourceState]:
    states: dict[str, SourceState] = {}
    for sensor in circuit_config.sensors:
        source_value = source_values_by_entity.get(sensor.entity_id)
        if source_value is None:
            continue
        state_value, last_updated = source_value
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


def _snapshot_state(
    state: AnalyzerState,
    nilm_processor: NilmSampleProcessor,
    store_data: FeatureStoreData,
) -> dict[str, Any]:
    return {
        "state_id": id(state),
        "nilm_processor_id": id(nilm_processor),
        "store_id": id(store_data),
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
        (circuit_id, item)
        for circuit_id, history in (
            result.store_data.nilm_session_history_by_circuit.items()
        )
        for item in history
        if isinstance(item, Mapping)
    ]
    metrics: dict[str, ComponentReplayMetrics] = {}
    for component_id, truth in fixture.labels.component_truth.items():
        predicted_items = [
            (circuit_id, item)
            for circuit_id, item in sessions
            if str(item.get("assignment_id") or item.get("appliance_id") or "")
            == component_id
            and item.get("start")
            and item.get("end")
        ]
        predicted = [item for _circuit_id, item in predicted_items]
        matched = [
            (expected, actual)
            for expected, actual in _optimal_session_pairs(
                truth.sessions,
                predicted,
                lambda expected, actual: float(
                    _session_matches_truth(fixture, expected, actual)
                ),
            )
            if expected is not None and actual is not None
        ]
        session_precision = _ratio_or_none(len(matched), len(predicted))
        session_recall = _ratio_or_none(len(matched), len(truth.sessions))
        evaluation_pairs = _session_evaluation_pairs(
            fixture, truth.sessions, predicted
        )
        start_errors = [
            abs(
                (
                    _parse_datetime(str(actual["start"])) - fixture.start_time
                ).total_seconds()
                - expected.start_t
            )
            for expected, actual in evaluation_pairs
            if expected is not None and actual is not None
        ]
        stop_errors = [
            abs(
                (
                    _parse_datetime(str(actual["end"])) - fixture.start_time
                ).total_seconds()
                - expected.end_t
            )
            for expected, actual in evaluation_pairs
            if expected is not None and actual is not None
        ]
        duration_errors = [
            abs(
                (
                    _parse_datetime(str(actual["end"]))
                    - _parse_datetime(str(actual["start"]))
                ).total_seconds()
                - (expected.end_t - expected.start_t)
            )
            for expected, actual in evaluation_pairs
            if expected is not None and actual is not None
        ]
        interval_ious = [
            0.0
            if expected is None or actual is None
            else _session_interval_iou(fixture, expected, actual)
            for expected, actual in evaluation_pairs
        ]
        predicted_state_segments = [
            segment
            for circuit_id, actual in predicted_items
            for state_path, _predictions, _helper_evidence in (
                _replay_session_runtime_evidence(
                    result,
                    circuit_id,
                    component_id,
                    actual,
                ),
            )
            for segment in _predicted_state_segments(fixture, actual, state_path)
        ]
        state_accuracy = _state_accuracy(
            truth.state_segments,
            predicted_state_segments,
        )
        observed_active_state_count = len(
            {
                state_id
                for state_id, _start, _end in predicted_state_segments
                if state_id != "off"
            }
        )
        predicted_starts = {
            _parse_datetime(str(actual["start"])) for actual in predicted
        }
        predicted_starts.update(
            _parse_datetime(str(runtime["session_start"]))
            for snapshot in result.state_snapshots
            for circuit_runtime in snapshot.get(
                "nilm_component_runtime_by_circuit", {}
            ).values()
            for assignment_id, runtime in circuit_runtime.items()
            if assignment_id == component_id and runtime.get("session_start")
        )
        predicted_edges = [
            *((EventType.START, start) for start in predicted_starts),
            *(
                (EventType.STOP, _parse_datetime(str(actual["end"])))
                for actual in predicted
            ),
        ]
        unmatched_edges = list(predicted_edges)
        matched_edges = 0
        for expected in truth.edges:
            for actual in unmatched_edges:
                if (
                    actual[0] is expected.event_type
                    and abs(
                        (actual[1] - fixture.start_time).total_seconds()
                        - expected.around_t
                    )
                    <= expected.tolerance_seconds
                ):
                    matched_edges += 1
                    unmatched_edges.remove(actual)
                    break
        actual_energy = sum(
            float(
                item.get(
                    "estimated_energy_kwh",
                    item.get("energy_kwh", 0.0),
                )
                or 0.0
            )
            for item in predicted
        )
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
            median_duration_error_seconds=(
                median(duration_errors) if duration_errors else None
            ),
            interval_iou=(
                round(sum(interval_ious) / len(interval_ious), 3)
                if interval_ious
                else None
            ),
            state_accuracy=state_accuracy,
            observed_active_state_count=observed_active_state_count,
            energy_absolute_error_kwh=round(absolute_error, 6)
            if absolute_error is not None
            else None,
            energy_percentage_error=round(absolute_error / truth.energy_kwh * 100, 3)
            if absolute_error is not None and truth.energy_kwh
            else None,
        )
    return metrics


def evaluate_nilm_replay_gate(
    baseline: CalibrationMetrics,
    candidate: CalibrationMetrics,
    *,
    multistate_component_ids: tuple[str, ...] = (),
    variable_envelope_component_ids: tuple[str, ...] = (),
    required_score_channels: tuple[str, ...] = (),
) -> ReplayGateResult:
    """Apply the deterministic no-regression gate to chronological NILM replay."""
    violations: list[str] = []
    if candidate.expectation_failures:
        violations.append("candidate has deterministic expectation failures")
    if candidate.event_miss_count > baseline.event_miss_count:
        violations.append("candidate missed more deterministic events")
    if not _not_increased(
        candidate.false_assignment_rate,
        baseline.false_assignment_rate,
    ):
        violations.append("false assignment rate increased")
    if candidate.conservation_violations > baseline.conservation_violations:
        violations.append("conservation violations increased")
    if not _not_increased(
        candidate.residual_energy_kwh,
        baseline.residual_energy_kwh,
    ):
        violations.append("residual energy increased")

    for component_id, baseline_component in baseline.component_metrics.items():
        candidate_component = candidate.component_metrics.get(component_id)
        if candidate_component is None:
            violations.append(f"missing component replay metric: {component_id}")
            continue
        for field_name in ("session_f1", "interval_iou"):
            if not _not_worse(
                getattr(candidate_component, field_name),
                getattr(baseline_component, field_name),
            ):
                violations.append(f"{component_id} {field_name} regressed")
        if not _not_increased(
            candidate_component.energy_absolute_error_kwh,
            baseline_component.energy_absolute_error_kwh,
        ):
            violations.append(f"{component_id} energy error increased")

    for channel, impact in (
        ("duration", candidate.decision_impacts.duration),
        ("validation", candidate.decision_impacts.validation),
    ):
        if impact.changed_incorrect_count > impact.changed_correct_count:
            violations.append(f"{channel} changed decisions have net harm")
        if impact.changed_unscored_count:
            violations.append(f"{channel} changed decisions were not truth-scored")
        if channel in required_score_channels and (
            not impact.changed_count
            or impact.changed_correct_count <= impact.changed_incorrect_count
        ):
            violations.append(f"{channel} did not demonstrate net benefit")

    for component_id in multistate_component_ids:
        baseline_component = baseline.component_metrics.get(component_id)
        candidate_component = candidate.component_metrics.get(component_id)
        if candidate_component is None or candidate_component.state_accuracy is None:
            violations.append(f"missing multistate accuracy: {component_id}")
            continue
        if baseline_component is None or not _improved(
            candidate_component.state_accuracy,
            baseline_component.state_accuracy,
        ):
            violations.append(f"{component_id} state accuracy did not improve")
        if baseline_component is None or not _improved(
            candidate_component.session_f1,
            baseline_component.session_f1,
        ):
            violations.append(f"{component_id} session F1 did not improve")

    for component_id in variable_envelope_component_ids:
        component = candidate.component_metrics.get(component_id)
        if component is None or component.observed_active_state_count != 1:
            violations.append(f"{component_id} variable envelope was oversegmented")

    if not _valid_replay_split(baseline.replay_split) or not _valid_replay_split(
        candidate.replay_split
    ):
        violations.append("replay split provenance is required")
    elif baseline.replay_split != candidate.replay_split:
        violations.append("baseline and candidate replay splits differ")

    return ReplayGateResult(passed=not violations, violations=tuple(violations))


def _not_worse(candidate: float | None, baseline: float | None) -> bool:
    if baseline is None:
        return True
    return candidate is not None and candidate >= baseline


def _not_increased(candidate: float | None, baseline: float | None) -> bool:
    if baseline is None:
        return candidate is None
    return candidate is not None and candidate <= baseline


def _improved(candidate: float | None, baseline: float | None) -> bool:
    return (
        candidate is not None
        and candidate > (baseline if baseline is not None else 0.0)
    )


def _valid_replay_split(split: ReplaySplit | None) -> bool:
    return split is not None and split.training_end_t < split.evaluation_start_t


def _has_frozen_pre_split_models(fixture: CalibrationFixture) -> bool:
    """Require explicit, non-empty model snapshots from before evaluation."""
    split = fixture.labels.replay_split
    assignments = [
        assignment
        for items in fixture.assignments_by_circuit.values()
        for assignment in items
    ]
    if not _valid_replay_split(split) or not assignments:
        return False
    return all(
        isinstance(provenance := assignment.get("model_provenance"), Mapping)
        and provenance.get("frozen") is True
        and (_optional_int(provenance.get("training_end_t")) is not None)
        and _optional_int(provenance.get("training_end_t"))
        <= split.training_end_t
        and (_optional_int(provenance.get("training_example_count")) or 0) > 0
        for assignment in assignments
    )


def _interval_iou(
    expected_start: float,
    expected_end: float,
    actual_start: float,
    actual_end: float,
) -> float:
    overlap = max(
        0.0, min(expected_end, actual_end) - max(expected_start, actual_start)
    )
    union = max(expected_end, actual_end) - min(expected_start, actual_start)
    return overlap / union if union else 0.0


def _session_interval_iou(
    fixture: CalibrationFixture,
    expected: ExpectedComponentSession,
    actual: Mapping[str, Any],
) -> float:
    return _interval_iou(
        expected.start_t,
        expected.end_t,
        (_parse_datetime(str(actual["start"])) - fixture.start_time).total_seconds(),
        (_parse_datetime(str(actual["end"])) - fixture.start_time).total_seconds(),
    )


def _session_evaluation_pairs(
    fixture: CalibrationFixture,
    expected_sessions: tuple[ExpectedComponentSession, ...],
    predicted_sessions: list[Mapping[str, Any]],
) -> list[tuple[ExpectedComponentSession | None, Mapping[str, Any] | None]]:
    return _optimal_session_pairs(
        expected_sessions,
        predicted_sessions,
        lambda expected, actual: _session_interval_iou(fixture, expected, actual),
    )


def _optimal_session_pairs(
    expected_sessions: tuple[ExpectedComponentSession, ...],
    predicted_sessions: list[Mapping[str, Any]],
    score: Any,
) -> list[tuple[ExpectedComponentSession | None, Mapping[str, Any] | None]]:
    """Return a deterministic maximum-total-score one-to-one session pairing."""
    size = max(len(expected_sessions), len(predicted_sessions))
    if not size:
        return []
    weights = [
        [
            (
                float(score(expected, actual))
                if expected_index < len(expected_sessions)
                and actual_index < len(predicted_sessions)
                else 0.0
            )
            for actual_index, actual in enumerate(
                list(predicted_sessions) + [None] * (size - len(predicted_sessions))
            )
        ]
        for expected_index, expected in enumerate(
            list(expected_sessions) + [None] * (size - len(expected_sessions))
        )
    ]
    selected = _maximum_weight_assignment(weights)
    used_actual_indexes: set[int] = set()
    pairs: list[tuple[ExpectedComponentSession | None, Mapping[str, Any] | None]] = []
    for expected_index, expected in enumerate(expected_sessions):
        actual_index = selected[expected_index]
        actual = (
            predicted_sessions[actual_index]
            if actual_index < len(predicted_sessions)
            and weights[expected_index][actual_index] > 0.0
            else None
        )
        if actual is not None:
            used_actual_indexes.add(actual_index)
        pairs.append((expected, actual))
    pairs.extend(
        (None, actual)
        for index, actual in enumerate(predicted_sessions)
        if index not in used_actual_indexes
    )
    return pairs


def _maximum_weight_assignment(weights: list[list[float]]) -> list[int]:
    """Solve a square maximum-weight assignment with stable tie ordering."""
    size = len(weights)
    if not size:
        return []
    maximum = max(max(row) for row in weights)
    costs = [[maximum - weight for weight in row] for row in weights]
    u = [0.0] * (size + 1)
    v = [0.0] * (size + 1)
    p = [0] * (size + 1)
    way = [0] * (size + 1)
    for row in range(1, size + 1):
        p[0] = row
        column = 0
        min_cost = [float("inf")] * (size + 1)
        used = [False] * (size + 1)
        while True:
            used[column] = True
            assigned_row = p[column]
            delta = float("inf")
            next_column = 0
            for candidate_column in range(1, size + 1):
                if used[candidate_column]:
                    continue
                reduced_cost = (
                    costs[assigned_row - 1][candidate_column - 1]
                    - u[assigned_row]
                    - v[candidate_column]
                )
                if reduced_cost < min_cost[candidate_column]:
                    min_cost[candidate_column] = reduced_cost
                    way[candidate_column] = column
                if min_cost[candidate_column] < delta:
                    delta = min_cost[candidate_column]
                    next_column = candidate_column
            for candidate_column in range(size + 1):
                if used[candidate_column]:
                    u[p[candidate_column]] += delta
                    v[candidate_column] -= delta
                else:
                    min_cost[candidate_column] -= delta
            column = next_column
            if p[column] == 0:
                break
        while True:
            previous_column = way[column]
            p[column] = p[previous_column]
            column = previous_column
            if column == 0:
                break
    assignment = [0] * size
    for column in range(1, size + 1):
        assignment[p[column] - 1] = column - 1
    return assignment


def _predicted_state_segments(
    fixture: CalibrationFixture,
    session: Mapping[str, Any],
    state_path: tuple[Mapping[str, Any], ...],
) -> list[tuple[str, float, float]]:
    path = sorted(
        (
            item
            for item in state_path
            if isinstance(item, Mapping)
            and item.get("state_id")
            and item.get("started_at")
        ),
        key=lambda item: str(item["started_at"]),
    )
    if not path or not session.get("start") or not session.get("end"):
        return []
    session_start = (
        _parse_datetime(str(session["start"])) - fixture.start_time
    ).total_seconds()
    session_end = (
        _parse_datetime(str(session["end"])) - fixture.start_time
    ).total_seconds()
    segments: list[tuple[str, float, float]] = []
    for index, item in enumerate(path):
        started_at = (
            _parse_datetime(str(item["started_at"])) - fixture.start_time
        ).total_seconds()
        ended_at = (
            (
                _parse_datetime(str(path[index + 1]["started_at"])) - fixture.start_time
            ).total_seconds()
            if index + 1 < len(path)
            else session_end
        )
        if ended_at > max(started_at, session_start):
            segments.append(
                (
                    str(item["state_id"]),
                    max(started_at, session_start),
                    min(ended_at, session_end),
                )
            )
    return segments


def _state_accuracy(
    expected: tuple[ExpectedStateSegment, ...],
    predicted: list[tuple[str, float, float]],
) -> float | None:
    if not expected:
        return None
    expected_duration = sum(segment.end_t - segment.start_t for segment in expected)
    if expected_duration <= 0:
        return None
    correct_duration = sum(
        _merged_overlap_duration(
            expected_segment.start_t,
            expected_segment.end_t,
            [
                (predicted_start, predicted_end)
                for state_id, predicted_start, predicted_end in predicted
                if state_id == expected_segment.state_id
            ],
        )
        for expected_segment in expected
    )
    return round(correct_duration / expected_duration, 3)


def _merged_overlap_duration(
    expected_start: float,
    expected_end: float,
    intervals: list[tuple[float, float]],
) -> float:
    overlapping = sorted(
        (
            (max(expected_start, start), min(expected_end, end))
            for start, end in intervals
            if end > expected_start and start < expected_end
        ),
    )
    merged: list[tuple[float, float]] = []
    for start, end in overlapping:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return sum(end - start for start, end in merged)


def _completed_nilm_sessions(result: ReplayResult) -> list[Mapping[str, Any]]:
    return [
        session
        for _circuit_id, session in _completed_nilm_session_items(result)
    ]


def _completed_nilm_session_items(
    result: ReplayResult,
) -> list[tuple[str, Mapping[str, Any]]]:
    return [
        (circuit_id, session)
        for circuit_id, history in (
            result.store_data.nilm_session_history_by_circuit.items()
        )
        for session in history
        if isinstance(session, Mapping) and session.get("start") and session.get("end")
    ]


def _session_matches_truth(
    fixture: CalibrationFixture,
    expected: ExpectedComponentSession,
    actual: Mapping[str, Any],
) -> bool:
    start_error = abs(
        (_parse_datetime(str(actual["start"])) - fixture.start_time).total_seconds()
        - expected.start_t
    )
    stop_error = abs(
        (_parse_datetime(str(actual["end"])) - fixture.start_time).total_seconds()
        - expected.end_t
    )
    return max(start_error, stop_error) <= expected.tolerance_seconds


def _false_assignment_rate(
    fixture: CalibrationFixture, result: ReplayResult
) -> float | None:
    records: list[bool] = []
    unused_truth = {
        component_id: list(truth.sessions)
        for component_id, truth in fixture.labels.component_truth.items()
    }
    for session in _completed_nilm_sessions(result):
        component_id = str(
            session.get("assignment_id") or session.get("appliance_id") or ""
        )
        expected = next(
            (
                item
                for item in unused_truth.get(component_id, ())
                if _session_matches_truth(fixture, item, session)
            ),
            None,
        )
        records.append(expected is None)
        if expected is not None:
            unused_truth[component_id].remove(expected)
    return _ratio_or_none(records.count(True), len(records))


def _prediction_matches_truth(
    fixture: CalibrationFixture,
    component_id: str,
    prediction: Mapping[str, Any],
) -> bool | None:
    truth = fixture.labels.component_truth.get(component_id)
    timestamp = prediction.get("prediction_timestamp")
    if truth is None or not timestamp:
        return None
    offset = (_parse_datetime(str(timestamp)) - fixture.start_time).total_seconds()
    kind = str(prediction.get("transition_kind") or "").lower()
    if kind in {"start", "on"}:
        return any(
            edge.event_type is EventType.START
            and abs(offset - edge.around_t) <= edge.tolerance_seconds
            for edge in truth.edges
        )
    if kind in {"stop", "off"}:
        return any(
            edge.event_type is EventType.STOP
            and abs(offset - edge.around_t) <= edge.tolerance_seconds
            for edge in truth.edges
        )
    state_id = str(prediction.get("state_id") or "")
    return any(
        segment.state_id == state_id and segment.start_t <= offset < segment.end_t
        for segment in truth.state_segments
    )


def _nilm_confidence_calibration(
    fixture: CalibrationFixture, result: ReplayResult
) -> tuple[dict[str, dict[str, float]], float | None, float | None]:
    bins = {
        label: {
            "prediction_count": 0.0,
            "correct_count": 0.0,
            "incorrect_count": 0.0,
            "observed_accuracy": 0.0,
            "average_score": 0.0,
        }
        for label in CALIBRATION_CONFIDENCE_BINS
    }
    scored: list[tuple[float, float]] = []
    for circuit_id, session in _completed_nilm_session_items(result):
        component_id = str(
            session.get("assignment_id") or session.get("appliance_id") or ""
        )
        _state_path, predictions, _helper_evidence = (
            _replay_session_runtime_evidence(
                result,
                circuit_id,
                component_id,
                session,
            )
        )
        for prediction in predictions:
            outcome = _prediction_matches_truth(fixture, component_id, prediction)
            score = _optional_float(prediction.get("candidate_score"))
            if outcome is None or score is None:
                continue
            bounded_score = max(0.0, min(score, 1.0))
            outcome_value = float(outcome)
            scored.append((bounded_score, outcome_value))
            bucket = bins[_bin_label(bounded_score)]
            bucket["prediction_count"] += 1.0
            bucket["correct_count"] += outcome_value
            bucket["incorrect_count"] += 1.0 - outcome_value
            bucket["average_score"] += bounded_score
    for bucket in bins.values():
        count = bucket["prediction_count"]
        if count:
            bucket["average_score"] = round(bucket["average_score"] / count, 3)
            bucket["observed_accuracy"] = round(bucket["correct_count"] / count, 3)
    if not scored:
        return bins, None, None
    brier = round(
        sum((score - outcome) ** 2 for score, outcome in scored) / len(scored),
        3,
    )
    ece = sum(
        (bucket["prediction_count"] / len(scored))
        * abs(bucket["average_score"] - bucket["observed_accuracy"])
        for bucket in bins.values()
        if bucket["prediction_count"]
    )
    return bins, brier, round(ece, 3)


def _decision_impacts(
    fixture: CalibrationFixture, result: ReplayResult
) -> ReplayDecisionImpacts:
    decisions_by_channel: dict[str, list[tuple[str, Mapping[str, Any]]]] = {
        "duration": [],
        "validation": [],
    }
    for circuit_id, decision in _replay_score_decisions(result):
        for channel in decisions_by_channel:
            if f"{channel}_counterfactual_prototype_ids" in decision:
                decisions_by_channel[channel].append((circuit_id, decision))

    def impact_for(channel: str) -> ReplayDecisionImpact:
        correct = incorrect = neutral = unscored = 0
        for circuit_id, decision in decisions_by_channel[channel]:
            accepted_outcomes = _decision_outcomes(
                fixture,
                circuit_id,
                tuple(
                    str(prototype_id)
                    for prototype_id in _optional_list(
                        decision, "accepted_prototype_ids"
                    )
                ),
                str(decision["timestamp"]),
            )
            counterfactual_outcomes = _decision_outcomes(
                fixture,
                circuit_id,
                tuple(
                    str(prototype_id)
                    for prototype_id in _optional_list(
                        decision, f"{channel}_counterfactual_prototype_ids"
                    )
                ),
                str(decision["timestamp"]),
            )
            if (
                accepted_outcomes is None
                or counterfactual_outcomes is None
                or any(
                    outcome is None
                    for outcome in (*accepted_outcomes, *counterfactual_outcomes)
                )
            ):
                unscored += 1
                continue
            accepted_correct = _decision_is_correct(
                accepted_outcomes, counterfactual_outcomes
            )
            counterfactual_correct = _decision_is_correct(
                counterfactual_outcomes, accepted_outcomes
            )
            if accepted_correct and not counterfactual_correct:
                correct += 1
            elif not accepted_correct and counterfactual_correct:
                incorrect += 1
            else:
                neutral += 1
        return ReplayDecisionImpact(
            changed_count=len(decisions_by_channel[channel]),
            changed_correct_count=correct,
            changed_incorrect_count=incorrect,
            changed_neutral_count=neutral,
            changed_unscored_count=unscored,
        )

    return ReplayDecisionImpacts(
        duration=impact_for("duration"),
        validation=impact_for("validation"),
    )


def _replay_score_decisions(
    result: ReplayResult,
) -> list[tuple[str, Mapping[str, Any]]]:
    """Recover every bounded runtime decision from chronological snapshots."""
    decisions: dict[tuple[str, str, int], tuple[str, Mapping[str, Any]]] = {}

    def collect(
        scope: str, reconciliations: Mapping[str, Any]
    ) -> None:
        for raw_circuit_id, reconciliation in reconciliations.items():
            if not isinstance(reconciliation, Mapping):
                continue
            circuit_id = str(raw_circuit_id)
            for decision in _optional_list(reconciliation, "score_decisions"):
                if not isinstance(decision, Mapping) or not decision.get("timestamp"):
                    continue
                sequence = max(_optional_int(decision.get("sequence")) or 0, 0)
                if sequence:
                    decisions[(scope, circuit_id, sequence)] = (
                        circuit_id,
                        dict(decision),
                    )

    for snapshot in result.state_snapshots:
        if not isinstance(snapshot, Mapping):
            continue
        reconciliations = snapshot.get("nilm_reconciliation_by_circuit")
        if isinstance(reconciliations, Mapping):
            collect(str(snapshot.get("state_id") or "snapshot"), reconciliations)
    collect(
        str(id(result.final_state)),
        result.final_state.nilm_reconciliation_by_circuit,
    )
    return list(decisions.values())


def _decision_outcomes(
    fixture: CalibrationFixture,
    circuit_id: str,
    prototype_ids: tuple[str, ...],
    timestamp: str,
) -> list[bool | None] | None:
    if not prototype_ids:
        return []
    prototypes = _fixture_prototypes_by_id(fixture, circuit_id)
    outcomes: list[bool | None] = []
    for prototype_id in prototype_ids:
        candidate = prototypes.get(prototype_id)
        if candidate is None:
            return None
        component_id, prototype = candidate
        outcomes.append(
            _prediction_matches_truth(
                fixture,
                component_id,
                {
                    "prediction_timestamp": timestamp,
                    "transition_kind": prototype["kind"],
                    "state_id": prototype["to_state_id"],
                },
            )
        )
    return outcomes


def _decision_is_correct(
    outcomes: list[bool | None], alternate_outcomes: list[bool | None]
) -> bool:
    """Treat rejection as correct only when the alternate outcome is false."""
    return all(outcomes) if outcomes else not any(alternate_outcomes)


def _fixture_prototypes_by_id(
    fixture: CalibrationFixture, circuit_id: str
) -> dict[str, tuple[str, Mapping[str, Any]]]:
    prototypes: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for assignment in fixture.assignments_by_circuit.get(circuit_id, ()):
        assignment_id = str(assignment.get("assignment_id") or "")
        model = normalize_nilm_assignment_model(assignment)
        for prototype in model.get("transition_prototypes", ()):
            if isinstance(prototype, Mapping) and prototype.get("id"):
                prototypes[str(prototype["id"])] = (assignment_id, prototype)
    return prototypes


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
    for circuit_id, sessions in (
        result.store_data.nilm_session_history_by_circuit.items()
    ):
        for session in sessions:
            component_id = str(
                session.get("assignment_id") or session.get("appliance_id") or ""
            )
            truth = fixture.labels.component_truth.get(component_id)
            matching_truth = next(
                (
                    expected
                    for expected in unused_truth.get(component_id, ())
                    if max(
                        abs(
                            (
                                _parse_datetime(str(session["start"]))
                                - fixture.start_time
                            ).total_seconds()
                            - expected.start_t
                        ),
                        abs(
                            (
                                _parse_datetime(str(session["end"]))
                                - fixture.start_time
                            ).total_seconds()
                            - expected.end_t
                        ),
                    )
                    <= expected.tolerance_seconds
                ),
                None,
            )
            session_matches = matching_truth is not None
            if matching_truth is not None:
                unused_truth[component_id].remove(matching_truth)
            for evidence in _session_helper_evidence(
                result,
                circuit_id,
                component_id,
                session,
            ):
                if evidence.get("relationship") != "corroborates":
                    continue
                records.append(
                    session_matches
                    and str(evidence.get("helper_circuit_id") or "")
                    in truth.corroborating_helper_circuit_ids
                )
    return _ratio_or_none(records.count(False), len(records))


def _session_helper_evidence(
    result: ReplayResult,
    circuit_id: str,
    component_id: str,
    session: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    """Return fixed scalar replay evidence without persisting nested history."""

    _state_path, _predictions, helper_evidence = _replay_session_runtime_evidence(
        result,
        circuit_id,
        component_id,
        session,
    )
    return helper_evidence


def _replay_session_runtime_evidence(
    result: ReplayResult,
    circuit_id: str,
    component_id: str,
    session: Mapping[str, Any],
) -> tuple[
    tuple[Mapping[str, Any], ...],
    tuple[Mapping[str, Any], ...],
    tuple[Mapping[str, Any], ...],
]:
    """Project matching replay runtime evidence into fixed, bounded scalars.

    This is test-only calibration provenance. Production history deliberately
    excludes nested runtime payloads, so the replay reader examines only the
    last active snapshot for the matching session and projects at most twelve
    known scalar items from each runtime list.
    """

    state_path_from_session = "state_path" in session
    predictions_from_session = "accepted_predictions" in session
    helper_evidence_from_session = "helper_evidence" in session
    state_path = (
        _replay_state_path(session.get("state_path"))
        if state_path_from_session
        else None
    )
    predictions = (
        _replay_predictions(session.get("accepted_predictions"))
        if predictions_from_session
        else None
    )
    helper_evidence = (
        _replay_helper_evidence(session.get("helper_evidence"))
        if helper_evidence_from_session
        else None
    )
    session_start = _replay_timestamp(session.get("start"))
    session_end = _replay_timestamp(session.get("end"))
    terminal_prediction: Mapping[str, Any] | None = None
    if session_start is None:
        return state_path or (), predictions or (), helper_evidence or ()

    for snapshot in result.state_snapshots:
        runtimes = snapshot.get("nilm_component_runtime_by_circuit")
        if not isinstance(runtimes, Mapping):
            continue
        circuit_runtime = runtimes.get(circuit_id)
        if not isinstance(circuit_runtime, Mapping):
            continue
        runtime = circuit_runtime.get(component_id)
        if not isinstance(runtime, Mapping):
            continue
        if _replay_timestamp(runtime.get("session_start")) == session_start:
            if not state_path_from_session:
                state_path = _replay_state_path(runtime.get("state_path"))
            if not predictions_from_session:
                predictions = _replay_predictions(runtime.get("accepted_predictions"))
            if not helper_evidence_from_session:
                helper_evidence = _replay_helper_evidence(
                    runtime.get("helper_evidence")
                )
        if not predictions_from_session and session_end is not None:
            candidate = _replay_predictions((runtime.get("last_prediction"),))
            if (
                candidate
                and candidate[0].get("prediction_timestamp") == session_end
            ):
                terminal_prediction = candidate[0]
    base_predictions = predictions or ()
    if terminal_prediction is not None and not any(
        item.get("prediction_timestamp")
        == terminal_prediction.get("prediction_timestamp")
        for item in base_predictions
    ):
        predictions = tuple(
            [*base_predictions, terminal_prediction][
                -_REPLAY_RUNTIME_EVIDENCE_MAX_ITEMS:
            ]
        )
    return state_path or (), predictions or (), helper_evidence or ()


def _replay_state_path(value: Any) -> tuple[Mapping[str, Any], ...]:
    """Retain only the bounded scalar state fields used by calibration."""

    if not isinstance(value, (list, tuple)):
        return ()
    projected: list[Mapping[str, Any]] = []
    for item in value[-_REPLAY_RUNTIME_EVIDENCE_MAX_ITEMS:]:
        if not isinstance(item, Mapping):
            continue
        state_id = _replay_text(item.get("state_id"))
        started_at = _replay_timestamp(item.get("started_at"))
        if state_id is not None and started_at is not None:
            projected.append({"state_id": state_id, "started_at": started_at})
    return tuple(projected)


def _replay_predictions(value: Any) -> tuple[Mapping[str, Any], ...]:
    """Retain only the bounded scalar prediction fields used by calibration."""

    if not isinstance(value, (list, tuple)):
        return ()
    projected: list[Mapping[str, Any]] = []
    for item in value[-_REPLAY_RUNTIME_EVIDENCE_MAX_ITEMS:]:
        if not isinstance(item, Mapping):
            continue
        timestamp = _replay_timestamp(item.get("prediction_timestamp"))
        score = _replay_number(item.get("candidate_score"))
        if timestamp is None or score is None:
            continue
        prediction: dict[str, Any] = {
            "prediction_timestamp": timestamp,
            "candidate_score": score,
        }
        for key in ("transition_kind", "state_id"):
            if (text := _replay_text(item.get(key))) is not None:
                prediction[key] = text
        projected.append(prediction)
    return tuple(projected)


def _replay_helper_evidence(value: Any) -> tuple[Mapping[str, Any], ...]:
    """Retain only fixed scalar helper fields used by calibration."""

    if not isinstance(value, (list, tuple)):
        return ()
    projected: list[Mapping[str, Any]] = []
    for item in value[-_REPLAY_RUNTIME_EVIDENCE_MAX_ITEMS:]:
        if not isinstance(item, Mapping):
            continue
        relationship = _replay_text(item.get("relationship"))
        helper_id = _replay_text(item.get("helper_circuit_id"))
        if relationship is not None and helper_id is not None:
            projected.append(
                {
                    "relationship": relationship,
                    "helper_circuit_id": helper_id,
                }
            )
    return tuple(projected)


def _replay_timestamp(value: Any) -> str | None:
    text = _replay_text(value, maximum=_REPLAY_RUNTIME_TIMESTAMP_MAX_CHARS)
    if text is None:
        return None
    try:
        return _parse_datetime(text).isoformat()
    except (TypeError, ValueError):
        return None


def _replay_text(
    value: Any,
    *,
    maximum: int = _REPLAY_RUNTIME_TEXT_MAX_CHARS,
) -> str | None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        return None
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        return None
    if len(encoded) > maximum:
        return None
    return value


def _replay_number(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    normalized = float(value)
    return normalized if isfinite(normalized) else None


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
        str(item.get(key) or "").strip() for item in items if isinstance(item, Mapping)
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
