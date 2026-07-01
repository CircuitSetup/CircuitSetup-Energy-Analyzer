from __future__ import annotations

from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.managers import circuit_registry


def test_circuit_registry_returns_config_by_circuit_id() -> None:
    fridge = SimpleNamespace(circuit_id="fridge")
    hvac = SimpleNamespace(circuit_id="hvac")
    registry = circuit_registry.CircuitRegistry(
        SimpleNamespace(circuit_configs=(fridge, hvac))
    )

    assert registry.config_for_circuit("hvac") is hvac
    assert registry.config_for_circuit("missing") is None
