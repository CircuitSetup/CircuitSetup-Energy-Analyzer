from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.managers.store_persistence import (
    StorePersistenceManager,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
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
    )
    baseline_values = defaultdict(list)
    baseline_values["fridge:real_power"].append(120.0)
    baseline_values["washer:real_power"].append(400.0)
    manager = object.__new__(StorePersistenceManager)
    manager._coordinator = SimpleNamespace(store_data=store_data)
    manager.dirty = False

    manager.reset_baseline_for_circuit("fridge", baseline_values)

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
    assert dict(baseline_values) == {"washer:real_power": [400.0]}
    assert manager.dirty is True
