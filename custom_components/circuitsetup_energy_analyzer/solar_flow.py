from __future__ import annotations

from dataclasses import dataclass

EXPORT_TOLERANCE_W = 100.0
SOLAR_SURPLUS_THRESHOLD_W = 500.0
HIGH_SOLAR_SURPLUS_THRESHOLD_W = 1500.0


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
    solar_surplus_w: float
    load_shift_available_w: float
    solar_surplus_threshold_w: float
    high_solar_surplus_threshold_w: float
    generation_circuit_count: int
    status: str
    solar_surplus_status: str
    features: dict[str, float]


def calculate_solar_flow(
    *,
    mains: SolarFlowInput | None,
    generation: list[SolarFlowInput],
    export_tolerance_w: float = EXPORT_TOLERANCE_W,
    solar_surplus_threshold_w: float = SOLAR_SURPLUS_THRESHOLD_W,
    high_solar_surplus_threshold_w: float = HIGH_SOLAR_SURPLUS_THRESHOLD_W,
) -> SolarFlowResult:
    """Calculate diagnostic solar flow from signed mains and generation power."""
    if mains is None or mains.real_power_w is None:
        return _result(
            status="missing_mains",
            solar_surplus_status="missing_mains",
            solar_surplus_threshold_w=solar_surplus_threshold_w,
            high_solar_surplus_threshold_w=high_solar_surplus_threshold_w,
        )

    generation_inputs = [item for item in generation if item.real_power_w is not None]
    if not generation_inputs:
        return _result(
            mains_net_power_w=float(mains.real_power_w),
            status="missing_generation",
            solar_surplus_status="missing_generation",
            solar_surplus_threshold_w=solar_surplus_threshold_w,
            high_solar_surplus_threshold_w=high_solar_surplus_threshold_w,
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

    surplus_threshold = _round_w(max(float(solar_surplus_threshold_w), 0.0))
    high_surplus_threshold = _round_w(
        max(float(high_solar_surplus_threshold_w), surplus_threshold)
    )
    solar_surplus = 0.0 if inconsistent_export else grid_export
    if inconsistent_export:
        solar_surplus_status = "inconsistent_export"
    elif solar_generation <= 0.0:
        solar_surplus_status = "no_generation"
    elif solar_surplus >= high_surplus_threshold:
        solar_surplus_status = "high_surplus"
    elif solar_surplus >= surplus_threshold:
        solar_surplus_status = "surplus_available"
    else:
        solar_surplus_status = "no_surplus"
    load_shift_available = (
        solar_surplus
        if solar_surplus_status in {"surplus_available", "high_surplus"}
        else 0.0
    )

    return _result(
        mains_net_power_w=mains_net_power,
        solar_generation_w=solar_generation,
        grid_import_w=grid_import,
        grid_export_w=grid_export,
        site_consumption_w=site_consumption,
        solar_used_on_site_w=solar_used_on_site,
        self_consumption_percent=self_consumption,
        solar_powered_percent=solar_powered,
        solar_surplus_w=solar_surplus,
        load_shift_available_w=load_shift_available,
        solar_surplus_threshold_w=surplus_threshold,
        high_solar_surplus_threshold_w=high_surplus_threshold,
        generation_circuit_count=len(generation_inputs),
        status=status,
        solar_surplus_status=solar_surplus_status,
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
    solar_surplus_w: float = 0.0,
    load_shift_available_w: float = 0.0,
    solar_surplus_threshold_w: float = SOLAR_SURPLUS_THRESHOLD_W,
    high_solar_surplus_threshold_w: float = HIGH_SOLAR_SURPLUS_THRESHOLD_W,
    generation_circuit_count: int = 0,
    status: str,
    solar_surplus_status: str | None = None,
) -> SolarFlowResult:
    mains_net_power_w = _round_w(mains_net_power_w)
    solar_generation_w = _round_w(solar_generation_w)
    grid_import_w = _round_w(grid_import_w)
    grid_export_w = _round_w(grid_export_w)
    site_consumption_w = _round_w(site_consumption_w)
    solar_used_on_site_w = _round_w(solar_used_on_site_w)
    solar_surplus_w = _round_w(solar_surplus_w)
    load_shift_available_w = _round_w(load_shift_available_w)
    solar_surplus_threshold_w = _round_w(solar_surplus_threshold_w)
    high_solar_surplus_threshold_w = _round_w(high_solar_surplus_threshold_w)
    return SolarFlowResult(
        mains_net_power_w=mains_net_power_w,
        solar_generation_w=solar_generation_w,
        grid_import_w=grid_import_w,
        grid_export_w=grid_export_w,
        site_consumption_w=site_consumption_w,
        solar_used_on_site_w=solar_used_on_site_w,
        self_consumption_percent=round(float(self_consumption_percent), 1),
        solar_powered_percent=round(float(solar_powered_percent), 1),
        solar_surplus_w=solar_surplus_w,
        load_shift_available_w=load_shift_available_w,
        solar_surplus_threshold_w=solar_surplus_threshold_w,
        high_solar_surplus_threshold_w=high_solar_surplus_threshold_w,
        generation_circuit_count=max(int(generation_circuit_count), 0),
        status=status,
        solar_surplus_status=solar_surplus_status or status,
        features={
            "mains_net_power_w": mains_net_power_w,
            "solar_generation_w": solar_generation_w,
            "grid_import_w": grid_import_w,
            "grid_export_w": grid_export_w,
            "site_consumption_w": site_consumption_w,
            "solar_used_on_site_w": solar_used_on_site_w,
            "self_consumption_percent": round(float(self_consumption_percent), 1),
            "solar_powered_percent": round(float(solar_powered_percent), 1),
            "solar_surplus_w": solar_surplus_w,
            "load_shift_available_w": load_shift_available_w,
            "solar_surplus_threshold_w": solar_surplus_threshold_w,
            "high_solar_surplus_threshold_w": high_solar_surplus_threshold_w,
            "generation_circuit_count": float(max(int(generation_circuit_count), 0)),
        },
    )


def _round_w(value: float) -> float:
    return round(float(value), 1)
