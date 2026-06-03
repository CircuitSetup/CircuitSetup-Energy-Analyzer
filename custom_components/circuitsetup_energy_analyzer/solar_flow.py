from __future__ import annotations

from dataclasses import dataclass

EXPORT_TOLERANCE_W = 100.0


@dataclass(frozen=True, slots=True)
class SolarFlowInput:
    """Power input used to calculate instantaneous solar flow."""

    circuit_id: str
    real_power_w: float | None


@dataclass(frozen=True, slots=True)
class SolarFlowResult:
    """Instantaneous solar generation, import, export, and site-use evidence."""

    mains_net_power_w: float
    solar_generation_w: float
    grid_import_w: float
    grid_export_w: float
    site_consumption_w: float
    solar_used_on_site_w: float
    self_consumption_percent: float
    solar_powered_percent: float
    generation_circuit_count: int
    status: str
    features: dict[str, float]


def calculate_solar_flow(
    *,
    mains: SolarFlowInput | None,
    generation: list[SolarFlowInput],
    export_tolerance_w: float = EXPORT_TOLERANCE_W,
) -> SolarFlowResult:
    """Calculate diagnostic solar flow from signed mains and generation power."""
    if mains is None or mains.real_power_w is None:
        return _result(status="missing_mains")

    generation_inputs = [item for item in generation if item.real_power_w is not None]
    if not generation_inputs:
        return _result(
            mains_net_power_w=float(mains.real_power_w),
            status="missing_generation",
        )

    mains_net_power = _round_w(float(mains.real_power_w))
    solar_generation = _round_w(
        sum(max(float(item.real_power_w or 0.0), 0.0) for item in generation_inputs)
    )
    grid_import = _round_w(max(mains_net_power, 0.0))
    grid_export = _round_w(max(-mains_net_power, 0.0))
    raw_site_consumption = solar_generation + mains_net_power

    inconsistent_export = grid_export > solar_generation + abs(export_tolerance_w)
    site_consumption = _round_w(max(raw_site_consumption, 0.0))
    solar_used_on_site = _round_w(
        min(solar_generation, max(site_consumption - grid_import, 0.0))
    )
    self_consumption = (
        round((solar_used_on_site / solar_generation) * 100, 1)
        if solar_generation > 0.0
        else 0.0
    )
    solar_powered = (
        round((solar_used_on_site / site_consumption) * 100, 1)
        if site_consumption > 0.0
        else 0.0
    )

    if inconsistent_export:
        status = "inconsistent_export"
    elif solar_generation <= 0.0:
        status = "no_generation"
    elif grid_export > 0.0:
        status = "exporting"
    elif grid_import > 0.0:
        status = "importing"
    else:
        status = "self_powered"

    return _result(
        mains_net_power_w=mains_net_power,
        solar_generation_w=solar_generation,
        grid_import_w=grid_import,
        grid_export_w=grid_export,
        site_consumption_w=site_consumption,
        solar_used_on_site_w=solar_used_on_site,
        self_consumption_percent=self_consumption,
        solar_powered_percent=solar_powered,
        generation_circuit_count=len(generation_inputs),
        status=status,
    )


def _result(
    *,
    mains_net_power_w: float = 0.0,
    solar_generation_w: float = 0.0,
    grid_import_w: float = 0.0,
    grid_export_w: float = 0.0,
    site_consumption_w: float = 0.0,
    solar_used_on_site_w: float = 0.0,
    self_consumption_percent: float = 0.0,
    solar_powered_percent: float = 0.0,
    generation_circuit_count: int = 0,
    status: str,
) -> SolarFlowResult:
    mains_net_power_w = _round_w(mains_net_power_w)
    solar_generation_w = _round_w(solar_generation_w)
    grid_import_w = _round_w(grid_import_w)
    grid_export_w = _round_w(grid_export_w)
    site_consumption_w = _round_w(site_consumption_w)
    solar_used_on_site_w = _round_w(solar_used_on_site_w)
    return SolarFlowResult(
        mains_net_power_w=mains_net_power_w,
        solar_generation_w=solar_generation_w,
        grid_import_w=grid_import_w,
        grid_export_w=grid_export_w,
        site_consumption_w=site_consumption_w,
        solar_used_on_site_w=solar_used_on_site_w,
        self_consumption_percent=round(float(self_consumption_percent), 1),
        solar_powered_percent=round(float(solar_powered_percent), 1),
        generation_circuit_count=max(int(generation_circuit_count), 0),
        status=status,
        features={
            "mains_net_power_w": mains_net_power_w,
            "solar_generation_w": solar_generation_w,
            "grid_import_w": grid_import_w,
            "grid_export_w": grid_export_w,
            "site_consumption_w": site_consumption_w,
            "solar_used_on_site_w": solar_used_on_site_w,
            "self_consumption_percent": round(float(self_consumption_percent), 1),
            "solar_powered_percent": round(float(solar_powered_percent), 1),
            "generation_circuit_count": float(max(int(generation_circuit_count), 0)),
        },
    )


def _round_w(value: float) -> float:
    return round(float(value), 1)
