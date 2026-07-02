from __future__ import annotations

from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_KNOWN_LOAD_CIRCUITS,
)
from custom_components.circuitsetup_energy_analyzer.managers import circuit_registry


def test_circuit_registry_returns_config_by_circuit_id() -> None:
    fridge = SimpleNamespace(circuit_id="fridge")
    hvac = SimpleNamespace(circuit_id="hvac")
    registry = circuit_registry.CircuitRegistry(
        SimpleNamespace(circuit_configs=(fridge, hvac))
    )

    assert registry.config_for_circuit("hvac") is hvac
    assert registry.config_for_circuit("missing") is None


def test_circuit_registry_exposes_known_load_ids_from_options() -> None:
    registry = circuit_registry.CircuitRegistry(
        SimpleNamespace(
            circuit_configs=(),
            entry_data={CONF_KNOWN_LOAD_CIRCUITS: ["entry_load"]},
            options={CONF_KNOWN_LOAD_CIRCUITS: ["fridge", "hvac"]},
        )
    )

    assert registry.known_load_circuit_ids == frozenset({"fridge", "hvac"})
