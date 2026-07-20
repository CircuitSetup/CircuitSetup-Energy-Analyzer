from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.managers.store_persistence import (
    StorePersistenceManager,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    CircuitEvent,
    EventType,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.storage import (
    BaselineStats,
    FeatureStoreData,
)


def test_store_persistence_resets_circuit_baselines_and_alerts() -> None:
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        baselines={
            "fridge:real_power": BaselineStats(
                "real_power",
                4,
                120.0,
                10.0,
                100.0,
                140.0,
                0.8,
            ),
            "washer:real_power": BaselineStats(
                "real_power",
                4,
                400.0,
                25.0,
                350.0,
                450.0,
                0.8,
            ),
        },
        alerts=[
            AlertEvidence(
                timestamp=now,
                circuit_id="fridge",
                severity=Severity.WARNING,
                message="Fridge alert.",
                feature="energy_usage",
            ),
            AlertEvidence(
                timestamp=now,
                circuit_id="washer",
                severity=Severity.WARNING,
                message="Washer alert.",
                feature="energy_usage",
            ),
        ],
        events=[
            CircuitEvent(now, "fridge", EventType.START),
            CircuitEvent(now, "washer", EventType.START),
        ],
    )
    baseline_values = defaultdict(list)
    baseline_values["fridge:real_power"].append(120.0)
    baseline_values["washer:real_power"].append(400.0)
    manager = object.__new__(StorePersistenceManager)
    manager._coordinator = SimpleNamespace(store_data=store_data)
    manager.dirty = False

    manager.reset_baseline_for_circuit("fridge", baseline_values, now)

    assert store_data.baselines == {
        "washer:real_power": BaselineStats(
            "real_power",
            4,
            400.0,
            25.0,
            350.0,
            450.0,
            0.8,
        )
    }
    assert [alert.circuit_id for alert in store_data.alerts] == ["washer"]
    assert [event.circuit_id for event in store_data.events] == ["fridge", "washer"]
    assert store_data.learning_started_at_by_circuit == {
        "fridge": "2026-06-30T12:00:00+00:00"
    }
    assert dict(baseline_values) == {"washer:real_power": [400.0]}
    assert manager.dirty is True


def test_store_persistence_manager_owns_retention_helper_behavior() -> None:
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        nilm_signatures={
            "mains": [
                {"signature_id": "old", "last_seen": "2026-06-01T12:00:00+00:00"},
                {"signature_id": "new", "last_seen": "2026-06-30T12:00:00+00:00"},
            ],
        },
        nilm_session_history_by_circuit={
            "mains": [
                {"session_id": "stale", "end": "2026-05-01T12:00:00+00:00"},
                {"session_id": "fresh", "end": "2026-06-30T12:00:00+00:00"},
            ],
        },
    )
    coordinator = SimpleNamespace(store_data=store_data)
    manager = StorePersistenceManager(
        coordinator,
        retention_mode_for_circuit=lambda circuit_id: object(),
        ha_time_zone=lambda: "UTC",
        weather_context_history_max_samples=10,
        water_context_history_max_samples=10,
        alert_history_max_age=timedelta(days=180),
        alert_history_max_items=100,
        alert_feedback_max_age=timedelta(days=365),
        alert_feedback_max_items=100,
        nilm_signatures_max_items=1,
        nilm_unknown_loads_max_items=1,
        nilm_session_history_max_age=timedelta(days=45),
        nilm_session_history_max_items=10,
        recommendation_history_max_age=timedelta(days=180),
        recommendation_history_max_items=100,
        recommendation_decisions_max_age=timedelta(days=180),
        recommendation_decisions_max_items=100,
    )

    manager.prune_nilm_history(now)

    assert store_data.nilm_signatures["mains"] == [
        {"signature_id": "new", "last_seen": "2026-06-30T12:00:00+00:00"},
    ]
    assert store_data.nilm_session_history_by_circuit["mains"] == [
        {"session_id": "fresh", "end": "2026-06-30T12:00:00+00:00"},
    ]
