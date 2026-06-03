from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FLEXIBLE_LOAD_RUNNING_THRESHOLD_W = 100.0
VALID_SOLAR_FLOW_STATUSES = frozenset(
    {
        "no_surplus",
        "surplus_available",
        "high_surplus",
    }
)


@dataclass(frozen=True, slots=True)
class FlexibleLoadInput:
    """Load circuit that may be useful for solar load shifting."""

    circuit_id: str
    name: str
    appliance_profile: str
    real_power_w: float | None


@dataclass(frozen=True, slots=True)
class SolarLoadShiftResult:
    """Read-only solar load-shift evidence for flexible household loads."""

    status: str
    active_flexible_load_power_w: float
    solar_load_shift_available_w: float
    grid_import_w: float
    solar_coverage_percent: float
    active_flexible_load_count: int
    idle_flexible_load_count: int
    candidate_loads: list[dict[str, Any]]
    features: dict[str, Any]


def evaluate_solar_load_shift(
    *,
    solar_load_shift_available_w: float,
    solar_surplus_status: str,
    grid_import_w: float,
    flexible_loads: list[FlexibleLoadInput],
    running_threshold_w: float = FLEXIBLE_LOAD_RUNNING_THRESHOLD_W,
) -> SolarLoadShiftResult:
    """Estimate whether flexible loads are solar-covered or ready to shift."""
    threshold = max(float(running_threshold_w), 0.0)
    candidate_loads = [
        _candidate_payload(load, threshold) for load in flexible_loads
    ]
    active_loads = [
        candidate for candidate in candidate_loads if candidate["state"] == "active"
    ]
    idle_loads = [
        candidate for candidate in candidate_loads if candidate["state"] == "idle"
    ]
    unavailable_loads = [
        candidate
        for candidate in candidate_loads
        if candidate["state"] == "unavailable"
    ]
    active_power = _round_w(
        sum(float(candidate["current_power_w"]) for candidate in active_loads)
    )
    load_shift_available = _round_w(max(float(solar_load_shift_available_w), 0.0))
    grid_import = _round_w(max(float(grid_import_w), 0.0))
    has_valid_solar_flow = solar_surplus_status in VALID_SOLAR_FLOW_STATUSES
    solar_coverage = (
        _solar_coverage_percent(active_power, grid_import)
        if has_valid_solar_flow
        else 0.0
    )

    if not candidate_loads:
        status = "no_flexible_loads"
    elif not has_valid_solar_flow:
        status = "solar_flow_unavailable"
    elif unavailable_loads and not active_loads and not idle_loads:
        status = "insufficient_flexible_load_data"
    elif active_power > 0.0 and solar_coverage >= 95.0:
        status = "active_solar_supported"
    elif active_power > 0.0:
        status = "active_grid_supported"
    elif (
        idle_loads
        and load_shift_available > 0.0
        and solar_surplus_status in {"surplus_available", "high_surplus"}
    ):
        status = "surplus_candidate"
    else:
        status = "waiting_for_surplus"

    features = {
        "status": status,
        "solar_surplus_status": solar_surplus_status,
        "active_flexible_load_power_w": active_power,
        "solar_load_shift_available_w": load_shift_available,
        "grid_import_w": grid_import,
        "solar_coverage_percent": solar_coverage,
        "active_flexible_load_count": len(active_loads),
        "idle_flexible_load_count": len(idle_loads),
        "unavailable_flexible_load_count": len(unavailable_loads),
        "candidate_loads": candidate_loads,
    }
    return SolarLoadShiftResult(
        status=status,
        active_flexible_load_power_w=active_power,
        solar_load_shift_available_w=load_shift_available,
        grid_import_w=grid_import,
        solar_coverage_percent=solar_coverage,
        active_flexible_load_count=len(active_loads),
        idle_flexible_load_count=len(idle_loads),
        candidate_loads=candidate_loads,
        features=features,
    )


def _candidate_payload(
    load: FlexibleLoadInput,
    running_threshold_w: float,
) -> dict[str, Any]:
    if load.real_power_w is None:
        return {
            "circuit_id": load.circuit_id,
            "name": load.name,
            "appliance_profile": str(load.appliance_profile),
            "current_power_w": None,
            "state": "unavailable",
        }

    power = _round_w(max(float(load.real_power_w or 0.0), 0.0))
    return {
        "circuit_id": load.circuit_id,
        "name": load.name,
        "appliance_profile": str(load.appliance_profile),
        "current_power_w": power,
        "state": "active" if power >= running_threshold_w else "idle",
    }


def _solar_coverage_percent(active_power_w: float, grid_import_w: float) -> float:
    if active_power_w <= 0.0:
        return 0.0
    solar_supported = max(active_power_w - grid_import_w, 0.0)
    return round((solar_supported / active_power_w) * 100.0, 1)


def _round_w(value: float) -> float:
    return round(float(value), 1)
