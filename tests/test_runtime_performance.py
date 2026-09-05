"""Distinguish HA loop stalls from slow executor work."""

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.coordinator import (
    EnergyAnalyzerCoordinator,
)
from custom_components.circuitsetup_energy_analyzer.managers import processing_pipeline


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_executor_queue_and_execution_are_measured_separately(
    monkeypatch: pytest.MonkeyPatch, fail: bool
) -> None:
    coordinator = EnergyAnalyzerCoordinator(SimpleNamespace())
    timestamps = iter((10.0, 11.0, 13.0))
    monkeypatch.setattr(processing_pipeline, "monotonic", lambda: next(timestamps))
    owner = threading.get_ident()
    record = coordinator._record_runtime_performance

    def record_on_loop(*args, **kwargs):
        assert threading.get_ident() == owner
        record(*args, **kwargs)

    def work(value):
        assert threading.get_ident() != owner
        if fail:
            raise ValueError("worker failed")
        return value

    coordinator._record_runtime_performance = record_on_loop
    if fail:
        with pytest.raises(ValueError, match="worker failed"):
            await coordinator.pipeline.async_run(work, 42, operation="test")
    else:
        assert await coordinator.pipeline.async_run(work, 42, operation="test") == 42

    performance = coordinator.runtime_performance_snapshot()
    assert performance["executor_queue"]["test"] == {
        "count": 1,
        "last_ms": 1000.0,
        "max_ms": 1000.0,
    }
    assert performance["executor_execution"]["test"] == {
        "count": 1,
        "last_ms": 2000.0,
        "max_ms": 2000.0,
    }


@pytest.mark.asyncio
async def test_loop_lag_detects_stall_and_monitor_stops_on_unload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    coordinator = EnergyAnalyzerCoordinator(SimpleNamespace())
    manager = coordinator.source_updates
    await manager.async_start(())
    try:
        # The loop's timer must become overdue while this thread is blocked.
        time.sleep(0.25)  # noqa: ASYNC251 - deliberately stall the loop under test
        await asyncio.sleep(0.02)
        lag = coordinator.runtime_performance_snapshot()["event_loop_lag"]
        assert lag["count"] >= 1
        assert lag["max_ms"] >= 100.0
        assert any("event loop lag" in record.message for record in caplog.records)
    finally:
        await manager.async_stop()

    stopped = coordinator.runtime_performance_snapshot()["event_loop_lag"]
    await asyncio.sleep(0.15)
    assert coordinator.runtime_performance_snapshot()["event_loop_lag"] == stopped


def test_worker_timings_do_not_emit_loop_stall_warnings(
    caplog: pytest.LogCaptureFixture,
) -> None:
    coordinator = EnergyAnalyzerCoordinator(SimpleNamespace())
    coordinator._record_runtime_performance("executor_queue:nilm_snapshot", 2.0)
    coordinator._record_runtime_performance("executor_execution:nilm_snapshot", 3.0)
    assert not [record for record in caplog.records if record.levelname == "WARNING"]
    assert coordinator.runtime_performance_snapshot()["event_loop_lag"]["count"] == 0


@pytest.mark.asyncio
async def test_analysis_exposes_synchronous_phases_and_nilm_snapshot_cost() -> None:
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda _entity_id: None), data={}),
        entry_data={
            "circuits": [
                {
                    "circuit_id": "mains",
                    "name": "Mains",
                    "mode": "mains_nilm",
                    "appliance_profile": "mains_nilm",
                    "nilm_detection_enabled": True,
                    "sensors": [],
                }
            ]
        },
    )

    async def save():
        return None

    coordinator._store = SimpleNamespace(async_save=save)
    coordinator.store_persistence.mark_dirty()
    await coordinator.async_process_update()
    performance = coordinator.runtime_performance_snapshot()
    # UX is refreshed once during hydration and once during analysis.
    assert performance["synchronous"]["ux_state"]["count"] == 2
    for operation in ("settings_recommendations", "retention"):
        assert performance["synchronous"][operation]["count"] == 1
    for operation in ("nilm_snapshot", "nilm_process"):
        assert performance["executor_execution"][operation]["count"] == 1

    await coordinator.async_recalculate_setting_recommendations()
    assert coordinator.runtime_performance_snapshot()["synchronous"][
        "settings_recommendations"
    ]["count"] == 2

    ux_count = coordinator.runtime_performance_snapshot()["synchronous"]["ux_state"][
        "count"
    ]
    now = coordinator.current_time()
    coordinator.refresh_ux_state_for_circuit("mains", now)
    coordinator.refresh_all_ux_state(now)
    coordinator.ux_state.refresh_all(now, refresh_nilm=False)
    assert coordinator.runtime_performance_snapshot()["synchronous"]["ux_state"][
        "count"
    ] == ux_count + 3
