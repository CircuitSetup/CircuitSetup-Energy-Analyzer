"""Manual NILM hot-path benchmark.

Run with ``python scripts/benchmark_nilm_performance.py``.

This is deliberately outside ``tests/`` so normal pytest discovery never runs it.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
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
from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
    nilm_workspace_collection_payload,
    nilm_workspace_item_payload,
    nilm_workspace_payload,
)
from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
    NilmSampleProcessor,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData

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
        seed_demo_nilm_state=lambda *_args: None,
        min_delta_w_for_circuit=lambda _circuit_id: 100.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda *_args: (),
        observe_topology=lambda *_args: [],
    )


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
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
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


def _append_trace(points: list[NilmResidualPowerPoint]) -> None:
    processor = _processor()
    for point in points:
        processor._append_residual_trace_point("mains", point)


def run_benchmarks() -> dict[str, object]:
    """Measure configured hot paths and return JSON-serializable results."""
    results: dict[str, object] = {
        "python": sys.version,
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
        },
        "session_counts": {},
        "trace_counts": {},
        "panel_routes": {},
    }
    specs = [{"signature_fingerprint": "sig-1", "median_delta_w": 150.0}]
    edges = [
        NilmEdge(BASE_TIME, 150.0, 0.0, 150.0, 0.0, "on"),
        NilmEdge(BASE_TIME + timedelta(minutes=5), -150.0, 0.0, 150.0, 0.0, "off"),
    ]
    for count in SESSION_COUNTS:
        store = FeatureStoreData(
            nilm_session_history_by_circuit={
                "mains": [_session(i) for i in range(count)]
            }
        )
        processor = _processor()
        dirty = sum(
            bool(processor.refresh_session_history("mains", store))
            for _ in range(REPEATS)
        )
        results["session_counts"][str(count)] = {
            "refresh": _timed(
                lambda processor=processor, store=store: (
                    processor.refresh_session_history("mains", store)
                )
            ),
            "dirty_save_frequency": dirty / REPEATS,
        }
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
    coordinator = _coordinator(max(SESSION_COUNTS))
    routes = {
        "main": lambda: nilm_workspace_payload(
            [coordinator], circuit_id="mains", entry_id="benchmark"
        ),
        "collection_max_limit": lambda: nilm_workspace_collection_payload(
            [coordinator],
            collection="sessions",
            circuit_id="mains",
            entry_id="benchmark",
            limit=50,
        ),
        "item_signature": lambda: nilm_workspace_item_payload(
            [coordinator],
            kind="signature",
            item_id="sig-1",
            circuit_id="mains",
            entry_id="benchmark",
        ),
        "item_session": lambda: nilm_workspace_item_payload(
            [coordinator],
            kind="session",
            item_id="session-0",
            circuit_id="mains",
            entry_id="benchmark",
        ),
    }
    for name, route in routes.items():
        payload = route()
        results["panel_routes"][name] = {
            **_timed(route),
            "serialized_bytes": len(json.dumps(payload, sort_keys=True).encode()),
        }
    return results


if __name__ == "__main__":
    print(json.dumps(run_benchmarks(), indent=2, sort_keys=True))  # noqa: T201
