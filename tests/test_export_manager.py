from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import CONF_CIRCUITS
from custom_components.circuitsetup_energy_analyzer.coordinator import (
    EnergyAnalyzerCoordinator,
)


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
