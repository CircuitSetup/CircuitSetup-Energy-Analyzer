"""Manual NILM hot-path benchmark.

Run with ``python scripts/benchmark_nilm_performance.py``.

This is deliberately outside ``tests/`` so normal pytest discovery never runs it.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from time import perf_counter_ns
from types import SimpleNamespace
from typing import Any

from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    SensorRef,
    SensorRole,
)
from custom_components.circuitsetup_energy_analyzer.nilm import (
    NilmEdge,
    NilmResidualPowerPoint,
    pair_nilm_sessions_for_signatures,
)
from custom_components.circuitsetup_energy_analyzer.normalize import (
    NormalizedCircuitSample,
)
from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
    MAX_NILM_WORKSPACE_COLLECTION_LIMIT,
    nilm_workspace_collection_payload,
    nilm_workspace_item_payload,
    nilm_workspace_payload,
)
from custom_components.circuitsetup_energy_analyzer.processors.base import (
    ProcessingContext,
)
from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
    NilmSampleProcessor,
)
from custom_components.circuitsetup_energy_analyzer.state import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.storage import (
    FeatureStoreData,
    feature_store_data_to_dict,
)

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)
SESSION_COUNTS = (0, 100, 500, 1_000, 2_000)
TRACE_COUNTS = (0, 1_024, 4_096)
REPEATS = 5


def _timed(operation: Callable[[], Any]) -> dict[str, float]:
    samples = []
    for _ in range(REPEATS):
        started = perf_counter_ns()
        operation()
        samples.append((perf_counter_ns() - started) / 1_000_000)
    return {"median_ms": round(median(samples), 3), "min_ms": round(min(samples), 3)}


def _serialized_feature_store_bytes(store: FeatureStoreData) -> int:
    """Return a stable serialized-size measurement for the full feature store."""

    return len(json.dumps(feature_store_data_to_dict(store), sort_keys=True).encode())


def _mains_config() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )


def _steady_sample(timestamp: datetime = BASE_TIME) -> NormalizedCircuitSample:
    return NormalizedCircuitSample(
        timestamp=timestamp,
        circuit_id="mains",
        real_power=150.0,
        current=None,
        voltage=None,
        reactive_power=None,
        apparent_power=None,
        power_factor=None,
        frequency=60.0,
        energy=None,
    )


def _point(index: int) -> NilmResidualPowerPoint:
    return NilmResidualPowerPoint(
        timestamp=BASE_TIME + timedelta(seconds=index),
        mains_power_w=150.0,
        explained_known_power_w=0.0,
        residual_power_w=150.0,
        contributing_known_circuit_ids=(),
        stale_known_circuit_ids=(),
        unavailable_known_circuit_ids=(),
        missing_known_circuit_ids=(),
        expected_known_circuit_count=0,
        fresh_known_circuit_count=0,
        known_source_coverage=1.0,
        subtraction_complete=True,
        quality_flags=(),
    )


def _processor() -> NilmSampleProcessor:
    return NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        min_delta_w_for_circuit=lambda _circuit_id: 100.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda *_args: (),
        observe_topology=lambda *_args: [],
    )


def _steady_sample_measurement(session_count: int) -> dict[str, object]:
    """Warm a processor, then measure samples with no changed NILM evidence."""

    store = FeatureStoreData(
        nilm_session_history_by_circuit={
            "mains": [_session(index) for index in range(session_count)]
        }
    )
    context = ProcessingContext(
        now=BASE_TIME,
        hass=SimpleNamespace(data={}),
        state=AnalyzerState(),
        store_data=store,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
        time_zone="UTC",
    )
    processor = _processor()
    config = _mains_config()
    sample = _steady_sample()
    processor.process(sample, config, context, events=())
    before = _serialized_feature_store_bytes(store)
    dirty_results: list[bool] = []

    def run_steady_sample() -> None:
        dirty_results.append(
            processor.process(sample, config, context, events=()).store_dirty
        )

    timing = _timed(run_steady_sample)
    after = _serialized_feature_store_bytes(store)
    return {
        "steady_sample": timing,
        "dirty_save_frequency": sum(dirty_results) / REPEATS,
        "serialized_feature_store_bytes": after,
        "serialized_store_unchanged": before == after,
    }


def _session(index: int) -> dict[str, object]:
    start = BASE_TIME + timedelta(minutes=index)
    return {
        "session_id": f"session-{index}",
        "signature_fingerprint": "sig-1",
        "on_edge_id": f"on-{index}",
        "off_edge_id": f"off-{index}",
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=5)).isoformat(),
    }


def _coordinator(session_count: int) -> SimpleNamespace:
    config = _mains_config()
    store = FeatureStoreData(
        nilm_session_history_by_circuit={
            "mains": [_session(i) for i in range(session_count)]
        }
    )
    return SimpleNamespace(
        entry_id="benchmark",
        store_data=store,
        circuit_configs=(config,),
        options={},
        entry_data={},
        state=SimpleNamespace(
            nilm_unknown_loads_by_circuit={
                "mains": {"unknown_loads": [{"signature_id": "sig-1"}]}
            },
            learning_by_circuit={"mains": False},
        ),
    )


def _panel_coordinator(session_count: int) -> SimpleNamespace:
    """Populate every lazy workspace source with representative retained rows."""

    coordinator = _coordinator(session_count)
    sessions: list[dict[str, object]] = []
    signatures: list[dict[str, object]] = []
    assignments: list[dict[str, object]] = []
    label_intervals: list[dict[str, object]] = []
    attributions: list[dict[str, object]] = []
    # Signatures and assignments have no 2,000-row retention contract.  Use a
    # full maximum page for them while retaining 2,000 sessions, labels, and
    # attribution rows; assigning every retained session a distinct source
    # would instead manufacture an unrelated cross-product benchmark.
    reference_item_count = min(
        MAX_NILM_WORKSPACE_COLLECTION_LIMIT,
        max(session_count, 1),
    )
    for index in range(reference_item_count):
        signature_id = f"sig-{index}"
        assignment_id = f"assignment-{index}"
        signatures.append(
            {
                "signature_id": signature_id,
                "feedback_fingerprint": signature_id,
                "direction": "on",
                "median_delta_w": 150.0,
                "occurrence_count": 3,
                "confidence": 0.9,
            }
        )
        assignments.append(
            {
                "assignment_id": assignment_id,
                "mains_circuit_id": "mains",
                "display_name": f"Load {index}",
                "lifecycle_state": "assigned",
                "signature_fingerprints": [signature_id],
            }
        )
    for index in range(session_count):
        start = BASE_TIME + timedelta(minutes=index)
        signature_id = f"sig-{index % reference_item_count}"
        assignment_id = f"assignment-{index % reference_item_count}"
        ambiguous = index % 2 == 0
        sessions.append(
            {
                "session_id": f"session-{index}",
                "mains_circuit_id": "mains",
                "signature_fingerprint": signature_id,
                "assignment_id": assignment_id,
                "on_edge_id": f"on-{index}",
                "off_edge_id": f"off-{index}",
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=5)).isoformat(),
                "ambiguous": ambiguous,
                "ambiguity_candidates": (
                    [
                        {
                            "candidate_id": "signature-a",
                            "candidate_kind": "signature",
                            "signature_fingerprint": "sig-a",
                            "total_score": 0.92,
                            "score_margin_from_best": 0.0,
                            "reason_code": "signature_candidate_conflict",
                        },
                        {
                            "candidate_id": "signature-b",
                            "candidate_kind": "signature",
                            "signature_fingerprint": "sig-b",
                            "total_score": 0.9,
                            "score_margin_from_best": 0.02,
                            "reason_code": "signature_candidate_conflict",
                        },
                    ]
                    if ambiguous
                    else []
                ),
            }
        )
        label_intervals.append(
            {
                "interval_id": f"interval-{index}",
                "assignment_id": assignment_id,
                "label": f"Load {index}",
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=5)).isoformat(),
            }
        )
        attributions.append(
            {
                "attribution_id": f"attribution-{index}",
                "timestamp": start.isoformat(),
                "aggregate_edge_id": f"edge-{index}",
                "aggregate_delta_w": 150.0,
                "explained_delta_w": 120.0,
                "residual_delta_w": 30.0,
                "known_circuit_ids": (),
                "selection_method": "global_assignment",
                "compound": False,
                "ambiguity_status": "matched",
                "rejected_candidate_summaries": [],
                "provenance_version": 1,
            }
        )
    coordinator.store_data.nilm_session_history_by_circuit = {"mains": sessions}
    coordinator.store_data.nilm_signatures = {"mains": signatures}
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": assignments
    }
    coordinator.store_data.nilm_label_intervals_by_circuit = {
        "mains": label_intervals
    }
    coordinator.store_data.nilm_known_load_attributions_by_circuit = {
        "mains": attributions
    }
    coordinator.state.nilm_unknown_loads_by_circuit = {
        "mains": {"unknown_loads": [{"signature_id": "sig-0"}]}
    }
    return coordinator


def _append_trace(points: list[NilmResidualPowerPoint]) -> None:
    processor = _processor()
    for point in points:
        processor._append_residual_trace_point("mains", point)


def _candidate_edges(on_edge_count: int) -> list[NilmEdge]:
    """Build one or up to 64 valid on/off candidate pairs."""

    return [
        *(
            NilmEdge(
                BASE_TIME + timedelta(minutes=index),
                150.0,
                0.0,
                150.0,
                0.0,
                "on",
            )
            for index in range(on_edge_count)
        ),
        *(
            NilmEdge(
                BASE_TIME + timedelta(minutes=10 + index),
                -150.0,
                0.0,
                150.0,
                0.0,
                "off",
            )
            for index in range(on_edge_count)
        ),
    ]


def _session_refresh_measurement(
    points: list[NilmResidualPowerPoint],
    *,
    on_edge_count: int,
) -> dict[str, object]:
    """Measure a warm session refresh against a retained residual trace."""

    processor = _processor()
    for point in points:
        processor._append_residual_trace_point("mains", point)
    processor.unmatched_edges_by_circuit["mains"] = _candidate_edges(on_edge_count)
    store = FeatureStoreData(
        nilm_signatures={
            "mains": [
                {"signature_fingerprint": "sig-1", "median_delta_w": 150.0}
            ]
        }
    )
    processor.refresh_session_history("mains", store)
    return {
        "on_edge_count": on_edge_count,
        "candidate_pair_upper_bound": on_edge_count * on_edge_count,
        "refresh": _timed(
            lambda: processor.refresh_session_history("mains", store)
        ),
    }


def run_benchmarks() -> dict[str, object]:
    """Measure configured hot paths and return JSON-serializable results."""
    results: dict[str, object] = {
        "python": sys.version,
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
        },
        "repeats": REPEATS,
        "retention_limits": {
            "session_history": max(SESSION_COUNTS),
            "residual_trace": max(TRACE_COUNTS),
        },
        "session_counts": {},
        "trace_counts": {},
        "session_refresh": {},
        "panel_routes": {},
    }
    specs = [{"signature_fingerprint": "sig-1", "median_delta_w": 150.0}]
    edges = [
        NilmEdge(BASE_TIME, 150.0, 0.0, 150.0, 0.0, "on"),
        NilmEdge(BASE_TIME + timedelta(minutes=5), -150.0, 0.0, 150.0, 0.0, "off"),
    ]
    for count in SESSION_COUNTS:
        results["session_counts"][str(count)] = _steady_sample_measurement(count)
    for count in TRACE_COUNTS:
        points = [_point(index) for index in range(count)]
        results["trace_counts"][str(count)] = {
            "candidate_pairing": _timed(
                lambda points=points: pair_nilm_sessions_for_signatures(
                    edges,
                    mains_circuit_id="mains",
                    signature_specs=specs,
                    power_trace=points,
                )
            ),
            "monotonic_append": _timed(lambda points=points: _append_trace(points)),
            "out_of_order_append": _timed(
                lambda points=points: _append_trace(list(reversed(points)))
            ),
        }
    refresh_trace = [_point(index) for index in range(max(TRACE_COUNTS))]
    results["session_refresh"] = {
        "one_candidate_pair_4096_trace": _session_refresh_measurement(
            refresh_trace,
            on_edge_count=1,
        ),
        "candidate_pair_budget_4096_trace": _session_refresh_measurement(
            refresh_trace,
            on_edge_count=8,
        ),
    }

    coordinator = _panel_coordinator(max(SESSION_COUNTS))
    routes = {
        "main": lambda: nilm_workspace_payload(
            [coordinator], circuit_id="mains", entry_id="benchmark"
        ),
        "item_session": lambda: nilm_workspace_item_payload(
            [coordinator],
            kind="session",
            item_id="session-1",
            circuit_id="mains",
            entry_id="benchmark",
        ),
    }
    for collection in (
        "sessions",
        "label_intervals",
        "assignments",
        "signatures",
        "known_load_attributions",
    ):
        routes[f"collection_{collection}_max_limit"] = (
            lambda collection=collection: nilm_workspace_collection_payload(
                [coordinator],
                collection=collection,
                circuit_id="mains",
                entry_id="benchmark",
                limit=50,
            )
        )
    routes["ambiguity_occurrences_max_limit"] = (
        lambda: nilm_workspace_collection_payload(
            [coordinator],
            collection="ambiguous_sessions",
            circuit_id="mains",
            entry_id="benchmark",
            view="occurrences",
            limit=50,
        )
    )
    routes["ambiguity_groups_max_limit"] = lambda: nilm_workspace_collection_payload(
        [coordinator],
        collection="ambiguous_sessions",
        circuit_id="mains",
        entry_id="benchmark",
        view="groups",
        limit=50,
    )
    for kind, item_id in (
        ("ambiguous_session", "session-0"),
        ("label_interval", "interval-1"),
        ("assignment", "assignment-1"),
        ("signature", "sig-1"),
        ("known_load_attribution", "attribution-1"),
    ):
        routes[f"item_{kind}"] = (
            lambda kind=kind, item_id=item_id: nilm_workspace_item_payload(
                [coordinator],
                kind=kind,
                item_id=item_id,
                circuit_id="mains",
                entry_id="benchmark",
            )
        )
    for name, route in routes.items():
        payload = route()
        results["panel_routes"][name] = {
            **_timed(route),
            "serialized_bytes": len(json.dumps(payload, sort_keys=True).encode()),
            "status": payload.get("status"),
            "returned_count": payload.get("returned_count"),
        }
    return results


def main(argv: Sequence[str] | None = None) -> int:
    """Run the opt-in benchmark and optionally persist its JSON result."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="write the JSON result to this path as well as stdout",
    )
    args = parser.parse_args(argv)
    rendered = json.dumps(run_benchmarks(), indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
