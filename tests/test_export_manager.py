from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import CONF_CIRCUITS
from custom_components.circuitsetup_energy_analyzer.coordinator import (
    EnergyAnalyzerCoordinator,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData


@pytest.mark.asyncio
async def test_coordinator_exposes_export_manager_for_diagnostics() -> None:
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [],
                }
            ],
        },
    )
    coordinator.state.anomaly_score_by_circuit["fridge"] = 2.5

    assert coordinator.export_manager.__class__.__name__ == "ExportManager"

    await coordinator.async_export_diagnostics("fridge")

    assert coordinator.last_exported_diagnostics["circuit_id"] == "fridge"
    assert coordinator.last_exported_diagnostics["anomaly_score"] == 2.5


@pytest.mark.asyncio
async def test_history_export_prunes_expired_rows_after_quiet_restore() -> None:
    now = datetime(2026, 9, 22, 12, tzinfo=UTC)
    old_day = (now - timedelta(days=90)).date().isoformat()
    recent_day = (now - timedelta(days=5)).date().isoformat()
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda _entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [],
                }
            ]
        },
        store_data=FeatureStoreData(
            energy_usage_by_circuit={
                "fridge": {
                    "days": [
                        {"date": old_day, "usage_kwh": 10.0},
                        {"date": recent_day, "usage_kwh": 5.0},
                    ]
                }
            }
        ),
        now_fn=lambda: now,
    )

    await coordinator.async_export_history_csv("fridge")

    assert old_day not in coordinator.last_exported_history_csv
    assert recent_day in coordinator.last_exported_history_csv
