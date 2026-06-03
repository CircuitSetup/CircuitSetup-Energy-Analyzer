from __future__ import annotations

from dataclasses import dataclass

DEFAULT_CAPACITY_WARNING_RATIO = 0.8


@dataclass(frozen=True, slots=True)
class CapacitySettings:
    """User settings for circuit capacity diagnostics."""

    breaker_amps: float | None = None
    warning_ratio: float = DEFAULT_CAPACITY_WARNING_RATIO


@dataclass(frozen=True, slots=True)
class CapacityResult:
    """Calculated circuit capacity usage evidence."""

    circuit_id: str
    status: str
    current_amps: float = 0.0
    breaker_amps: float = 0.0
    warning_threshold_amps: float = 0.0
    capacity_usage_percent: float = 0.0
    warning_ratio: float = DEFAULT_CAPACITY_WARNING_RATIO
    current_source: str = ""
    features: dict[str, float] | None = None


def evaluate_circuit_capacity(
    *,
    circuit_id: str,
    current_amps: float | None,
    real_power_w: float | None,
    voltage_v: float | None,
    settings: CapacitySettings,
) -> CapacityResult:
    """Evaluate current draw against a configured circuit capacity."""
    breaker_amps = _positive_float_or_none(settings.breaker_amps)
    warning_ratio = _warning_ratio(settings.warning_ratio)
    current, source = _current_for_capacity(
        current_amps=current_amps,
        real_power_w=real_power_w,
        voltage_v=voltage_v,
    )

    if breaker_amps is None:
        return CapacityResult(
            circuit_id=circuit_id,
            status="unconfigured",
            current_amps=round(current or 0.0, 2),
            warning_ratio=warning_ratio,
            current_source=source,
        )
    if current is None:
        return CapacityResult(
            circuit_id=circuit_id,
            status="missing_current",
            breaker_amps=round(breaker_amps, 2),
            warning_ratio=warning_ratio,
        )

    current = round(abs(float(current)), 2)
    breaker_amps = round(breaker_amps, 2)
    threshold = round(breaker_amps * warning_ratio, 2)
    usage = round((current / breaker_amps) * 100.0, 1)
    status = "over_limit" if current > threshold else "tracking"
    features = {
        "current_amps": current,
        "breaker_amps": breaker_amps,
        "warning_threshold_amps": threshold,
        "capacity_usage_percent": usage,
        "warning_ratio": warning_ratio,
    }
    return CapacityResult(
        circuit_id=circuit_id,
        status=status,
        current_amps=current,
        breaker_amps=breaker_amps,
        warning_threshold_amps=threshold,
        capacity_usage_percent=usage,
        warning_ratio=warning_ratio,
        current_source=source,
        features=features,
    )


def _current_for_capacity(
    *,
    current_amps: float | None,
    real_power_w: float | None,
    voltage_v: float | None,
) -> tuple[float | None, str]:
    current = _positive_float_or_none(current_amps)
    if current is not None:
        return current, "current_sensor"

    power = _positive_float_or_none(real_power_w)
    voltage = _positive_float_or_none(voltage_v)
    if power is not None and voltage is not None:
        return power / voltage, "estimated_from_power_voltage"
    return None, ""


def _warning_ratio(value: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return DEFAULT_CAPACITY_WARNING_RATIO
    if parsed <= 0.0:
        return DEFAULT_CAPACITY_WARNING_RATIO
    return min(parsed, 1.0)


def _positive_float_or_none(value: float | None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0.0 else None
