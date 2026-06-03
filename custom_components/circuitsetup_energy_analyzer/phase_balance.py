from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_LEG_IMBALANCE_WARNING_RATIO = 0.5
DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W = 500.0


@dataclass(frozen=True, slots=True)
class LegImbalanceResult:
    """Dual-phase leg balance evidence calculated from per-leg power."""

    status: str
    imbalance_ratio: float = 0.0
    imbalance_percent: float = 0.0
    threshold_ratio: float = DEFAULT_LEG_IMBALANCE_WARNING_RATIO
    threshold_percent: float = DEFAULT_LEG_IMBALANCE_WARNING_RATIO * 100
    minimum_total_power_w: float = DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W
    left_real_power_w: float | None = None
    right_real_power_w: float | None = None
    left_current_a: float | None = None
    right_current_a: float | None = None
    left_voltage_v: float | None = None
    right_voltage_v: float | None = None
    voltage_difference_v: float | None = None
    dominant_leg: str = "unknown"
    features: dict[str, float] = field(default_factory=dict)


def evaluate_dual_phase_leg_imbalance(
    *,
    left_real_power_w: float | None,
    right_real_power_w: float | None,
    left_current_a: float | None = None,
    right_current_a: float | None = None,
    left_voltage_v: float | None = None,
    right_voltage_v: float | None = None,
    threshold_ratio: float = DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
    minimum_total_power_w: float = DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
) -> LegImbalanceResult:
    """Compare split-phase leg real power and classify the balance state."""

    threshold_ratio = max(float(threshold_ratio), 0.01)
    minimum_total_power_w = max(float(minimum_total_power_w), 0.0)
    threshold_percent = round(threshold_ratio * 100.0, 1)
    voltage_difference_v = _voltage_difference(left_voltage_v, right_voltage_v)

    if left_real_power_w is None or right_real_power_w is None:
        return LegImbalanceResult(
            status="missing_leg_power",
            threshold_ratio=threshold_ratio,
            threshold_percent=threshold_percent,
            minimum_total_power_w=minimum_total_power_w,
            left_real_power_w=left_real_power_w,
            right_real_power_w=right_real_power_w,
            left_current_a=left_current_a,
            right_current_a=right_current_a,
            left_voltage_v=left_voltage_v,
            right_voltage_v=right_voltage_v,
            voltage_difference_v=voltage_difference_v,
        )

    left_magnitude = abs(float(left_real_power_w))
    right_magnitude = abs(float(right_real_power_w))
    total_power = left_magnitude + right_magnitude
    if total_power < minimum_total_power_w:
        return LegImbalanceResult(
            status="idle",
            threshold_ratio=threshold_ratio,
            threshold_percent=threshold_percent,
            minimum_total_power_w=minimum_total_power_w,
            left_real_power_w=left_real_power_w,
            right_real_power_w=right_real_power_w,
            left_current_a=left_current_a,
            right_current_a=right_current_a,
            left_voltage_v=left_voltage_v,
            right_voltage_v=right_voltage_v,
            voltage_difference_v=voltage_difference_v,
        )

    imbalance_ratio = round(
        abs(left_magnitude - right_magnitude) / (total_power / 2.0),
        3,
    )
    imbalance_percent = round(imbalance_ratio * 100.0, 1)
    dominant_leg = _dominant_leg(left_magnitude, right_magnitude)
    status = "imbalanced" if imbalance_ratio >= threshold_ratio else "tracking"
    features = {
        "leg_imbalance_ratio": imbalance_ratio,
        "leg_imbalance_percent": imbalance_percent,
        "left_real_power_w": float(left_real_power_w),
        "right_real_power_w": float(right_real_power_w),
        "threshold_ratio": threshold_ratio,
        "threshold_percent": threshold_percent,
    }

    return LegImbalanceResult(
        status=status,
        imbalance_ratio=imbalance_ratio,
        imbalance_percent=imbalance_percent,
        threshold_ratio=threshold_ratio,
        threshold_percent=threshold_percent,
        minimum_total_power_w=minimum_total_power_w,
        left_real_power_w=float(left_real_power_w),
        right_real_power_w=float(right_real_power_w),
        left_current_a=_optional_float(left_current_a),
        right_current_a=_optional_float(right_current_a),
        left_voltage_v=_optional_float(left_voltage_v),
        right_voltage_v=_optional_float(right_voltage_v),
        voltage_difference_v=voltage_difference_v,
        dominant_leg=dominant_leg,
        features=features,
    )


def _dominant_leg(left_magnitude: float, right_magnitude: float) -> str:
    if left_magnitude > right_magnitude:
        return "a"
    if right_magnitude > left_magnitude:
        return "b"
    return "even"


def _voltage_difference(
    left_voltage_v: float | None,
    right_voltage_v: float | None,
) -> float | None:
    if left_voltage_v is None or right_voltage_v is None:
        return None
    return round(abs(float(left_voltage_v) - float(right_voltage_v)), 3)


def _optional_float(value: float | None) -> float | None:
    if value is None:
        return None
    return float(value)
