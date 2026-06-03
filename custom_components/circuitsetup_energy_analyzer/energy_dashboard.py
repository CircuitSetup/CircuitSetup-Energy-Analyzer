from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .models import CircuitConfig, SensorRole
from .normalize import SourceState

_ENERGY_UNITS = {"kwh", "wh", "mwh"}
_POWER_UNITS = {"w", "kw"}
_ENERGY_STATE_CLASSES = {"total", "total_increasing"}


@dataclass(frozen=True, slots=True)
class EnergyDashboardReadiness:
    """Circuit source readiness for Home Assistant's Energy Dashboard."""

    circuit_id: str
    status: str
    ready_energy_entities: tuple[str, ...] = ()
    ready_power_entities: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    guidance: str = ""


def evaluate_energy_dashboard_readiness(
    config: CircuitConfig,
    source_states: Mapping[str, SourceState],
) -> EnergyDashboardReadiness:
    """Evaluate whether source entities can be handed to HA Energy Dashboard."""
    energy_entities: list[str] = []
    power_entities: list[str] = []
    issues: list[str] = []

    for sensor in config.sensors:
        if sensor.role not in {SensorRole.ENERGY, SensorRole.REAL_POWER}:
            continue
        source = source_states.get(sensor.entity_id)
        if source is None:
            issues.append(f"{sensor.entity_id} missing")
            continue
        if sensor.role is SensorRole.ENERGY:
            if _energy_ready(source, issues):
                energy_entities.append(sensor.entity_id)
        elif _power_ready(source, issues):
            power_entities.append(sensor.entity_id)

    if energy_entities:
        return EnergyDashboardReadiness(
            circuit_id=config.circuit_id,
            status="ready",
            ready_energy_entities=tuple(energy_entities),
            ready_power_entities=tuple(power_entities),
            issues=tuple(issues),
            guidance=(
                "Add the ready energy entity to Home Assistant's Energy Dashboard "
                "as an individual device."
            ),
        )

    if power_entities and not issues:
        return EnergyDashboardReadiness(
            circuit_id=config.circuit_id,
            status="power_ready",
            ready_power_entities=tuple(power_entities),
            guidance=(
                "Use the ready power input with Home Assistant's Energy Dashboard "
                "or create an energy sensor with the Integration helper."
            ),
        )

    if issues:
        return EnergyDashboardReadiness(
            circuit_id=config.circuit_id,
            status="needs_metadata",
            ready_power_entities=tuple(power_entities),
            issues=tuple(issues),
            guidance=(
                "Fix source sensor metadata before adding the circuit to Home "
                "Assistant's Energy Dashboard."
            ),
        )

    return EnergyDashboardReadiness(
        circuit_id=config.circuit_id,
        status="needs_energy_source",
        guidance=(
            "Add a circuit energy sensor to Home Assistant's Energy Dashboard, "
            "or expose a power sensor that Home Assistant can integrate."
        ),
    )


def readiness_payload(result: EnergyDashboardReadiness) -> dict[str, object]:
    """Return a JSON-safe evidence payload for diagnostics attributes."""
    return {
        "status": result.status,
        "ready_energy_entities": list(result.ready_energy_entities),
        "ready_power_entities": list(result.ready_power_entities),
        "issues": list(result.issues),
        "guidance": result.guidance,
    }


def _energy_ready(source: SourceState, issues: list[str]) -> bool:
    ready = True
    unit = _normalized(source.unit)
    if unit not in _ENERGY_UNITS:
        issues.append(f"{source.entity_id} unit is not kWh, Wh, or MWh")
        ready = False
    if _normalized(source.device_class) != "energy":
        issues.append(f"{source.entity_id} missing device_class energy")
        ready = False
    if _normalized(source.state_class) not in _ENERGY_STATE_CLASSES:
        issues.append(
            f"{source.entity_id} missing state_class total or total_increasing"
        )
        ready = False
    return ready


def _power_ready(source: SourceState, issues: list[str]) -> bool:
    ready = True
    unit = _normalized(source.unit)
    if unit not in _POWER_UNITS:
        issues.append(f"{source.entity_id} unit is not W or kW")
        ready = False
    if _normalized(source.device_class) != "power":
        issues.append(f"{source.entity_id} missing device_class power")
        ready = False
    if _normalized(source.state_class) != "measurement":
        issues.append(f"{source.entity_id} missing state_class measurement")
        ready = False
    return ready


def _normalized(value: str | None) -> str:
    return "" if value is None else value.strip().lower()
