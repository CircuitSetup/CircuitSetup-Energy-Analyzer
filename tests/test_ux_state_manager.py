from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.const import CONF_CIRCUITS
from custom_components.circuitsetup_energy_analyzer.coordinator import (
    EnergyAnalyzerCoordinator,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData


def test_coordinator_exposes_ux_state_manager_for_refresh() -> None:
    now = datetime(2026, 7, 2, 12, tzinfo=UTC)
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {
                            "entity_id": "sensor.fridge_power",
                            "role": "real_power",
                        },
                    ],
                }
            ],
        },
        now_fn=lambda: now,
    )

    assert coordinator.ux_state.__class__.__name__ == "UxStateManager"

    coordinator.refresh_ux_state_for_circuit("fridge", now)

    assert coordinator.state.readiness_by_circuit["fridge"]["health_status"] in {
        "ready",
        "learning",
    }


def test_hydrate_state_from_store_does_not_expire_timed_maintenance() -> None:
    now = datetime(2026, 7, 2, 12, tzinfo=UTC)
    store_data = FeatureStoreData(
        maintenance_by_circuit={
            "fridge": {
                "active": True,
                "expires_at": "2026-07-02T11:00:00+00:00",
            },
        },
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {
                            "entity_id": "sensor.fridge_power",
                            "role": "real_power",
                        },
                    ],
                }
            ],
        },
        store_data=store_data,
        now_fn=lambda: now,
    )

    maintenance = store_data.maintenance_by_circuit["fridge"]
    assert "fridge" in coordinator.paused_circuits
    assert maintenance["active"] is True
    assert "ended_at" not in maintenance
