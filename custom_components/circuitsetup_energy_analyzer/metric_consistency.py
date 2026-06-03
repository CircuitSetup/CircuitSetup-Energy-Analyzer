from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite

DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT = 15.0
DEFAULT_POWER_FACTOR_TOLERANCE = 0.15
DEFAULT_MIN_APPARENT_POWER_VA = 80.0


@dataclass(frozen=True, slots=True)
class MetricConsistencyResult:
    """Consistency evidence for measured W, VA, V, A, and PF values."""

    status: str
    mismatch_score_percent: float = 0.0
    expected_apparent_power_va: float | None = None
    reported_apparent_power_va: float | None = None
    apparent_power_difference_percent: float | None = None
    apparent_power_tolerance_percent: float = (
        DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT
    )
    apparent_power_source: str = "missing"
    expected_power_factor: float | None = None
    reported_power_factor: float | None = None
    power_factor_difference: float | None = None
    power_factor_tolerance: float = DEFAULT_POWER_FACTOR_TOLERANCE
    minimum_apparent_power_va: float = DEFAULT_MIN_APPARENT_POWER_VA
    features: dict[str, float] = field(default_factory=dict)


def evaluate_metric_consistency(
    *,
    real_power_w: float | None,
    apparent_power_va: float | None,
    power_factor: float | None,
    voltage_v: float | None,
    current_a: float | None,
    leg_a_voltage_v: float | None = None,
    leg_a_current_a: float | None = None,
    leg_b_voltage_v: float | None = None,
    leg_b_current_a: float | None = None,
    apparent_power_tolerance_percent: float = (
        DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT
    ),
    power_factor_tolerance: float = DEFAULT_POWER_FACTOR_TOLERANCE,
    minimum_apparent_power_va: float = DEFAULT_MIN_APPARENT_POWER_VA,
) -> MetricConsistencyResult:
    """Check whether reported power metrics agree with each other."""

    apparent_power_tolerance_percent = max(
        float(apparent_power_tolerance_percent),
        0.1,
    )
    power_factor_tolerance = max(float(power_factor_tolerance), 0.001)
    minimum_apparent_power_va = max(float(minimum_apparent_power_va), 0.0)
    expected_va, apparent_power_source = _expected_apparent_power(
        voltage_v=voltage_v,
        current_a=current_a,
        leg_a_voltage_v=leg_a_voltage_v,
        leg_a_current_a=leg_a_current_a,
        leg_b_voltage_v=leg_b_voltage_v,
        leg_b_current_a=leg_b_current_a,
    )
    reported_va = _positive_number_or_none(apparent_power_va)
    reported_pf = _power_factor_or_none(power_factor)
    real_power = _number_or_none(real_power_w)

    if _is_idle(expected_va, reported_va, minimum_apparent_power_va):
        return MetricConsistencyResult(
            status="idle",
            apparent_power_tolerance_percent=apparent_power_tolerance_percent,
            apparent_power_source=apparent_power_source,
            power_factor_tolerance=power_factor_tolerance,
            minimum_apparent_power_va=minimum_apparent_power_va,
            expected_apparent_power_va=expected_va,
            reported_apparent_power_va=reported_va,
            expected_power_factor=_expected_power_factor(real_power, reported_va),
            reported_power_factor=reported_pf,
        )

    apparent_difference_percent = _difference_percent(reported_va, expected_va)
    expected_pf = _expected_power_factor(real_power, reported_va)
    pf_difference = _pf_difference(reported_pf, expected_pf)

    apparent_mismatch = (
        apparent_difference_percent is not None
        and abs(apparent_difference_percent) > apparent_power_tolerance_percent
    )
    pf_mismatch = (
        pf_difference is not None and pf_difference > power_factor_tolerance
    )
    if apparent_difference_percent is None and pf_difference is None:
        status = "missing_metrics"
    else:
        status = _status(apparent_mismatch, pf_mismatch)
    score = _mismatch_score(apparent_difference_percent, pf_difference)

    result = MetricConsistencyResult(
        status=status,
        mismatch_score_percent=score,
        expected_apparent_power_va=expected_va,
        reported_apparent_power_va=reported_va,
        apparent_power_difference_percent=apparent_difference_percent,
        apparent_power_tolerance_percent=apparent_power_tolerance_percent,
        apparent_power_source=apparent_power_source,
        expected_power_factor=expected_pf,
        reported_power_factor=reported_pf,
        power_factor_difference=pf_difference,
        power_factor_tolerance=power_factor_tolerance,
        minimum_apparent_power_va=minimum_apparent_power_va,
    )
    return MetricConsistencyResult(
        **{
            field_name: getattr(result, field_name)
            for field_name in (
                "status",
                "mismatch_score_percent",
                "expected_apparent_power_va",
                "reported_apparent_power_va",
                "apparent_power_difference_percent",
                "apparent_power_tolerance_percent",
                "apparent_power_source",
                "expected_power_factor",
                "reported_power_factor",
                "power_factor_difference",
                "power_factor_tolerance",
                "minimum_apparent_power_va",
            )
        },
        features=_features(result),
    )


def _expected_apparent_power(
    *,
    voltage_v: float | None,
    current_a: float | None,
    leg_a_voltage_v: float | None,
    leg_a_current_a: float | None,
    leg_b_voltage_v: float | None,
    leg_b_current_a: float | None,
) -> tuple[float | None, str]:
    leg_a_va = _voltage_current_va(leg_a_voltage_v, leg_a_current_a)
    leg_b_va = _voltage_current_va(leg_b_voltage_v, leg_b_current_a)
    if leg_a_va is not None and leg_b_va is not None:
        return round(leg_a_va + leg_b_va, 1), "leg_voltage_current"

    va = _voltage_current_va(voltage_v, current_a)
    if va is None:
        return None, "missing"
    return round(va, 1), "voltage_current"


def _voltage_current_va(
    voltage_v: float | None,
    current_a: float | None,
) -> float | None:
    voltage = _number_or_none(voltage_v)
    current = _number_or_none(current_a)
    if voltage is None or current is None:
        return None
    return abs(voltage * current)


def _expected_power_factor(
    real_power_w: float | None,
    apparent_power_va: float | None,
) -> float | None:
    real_power = _number_or_none(real_power_w)
    apparent_power = _positive_number_or_none(apparent_power_va)
    if real_power is None or apparent_power is None or apparent_power == 0.0:
        return None
    return round(min(abs(real_power) / apparent_power, 1.0), 3)


def _difference_percent(
    reported: float | None,
    expected: float | None,
) -> float | None:
    if reported is None or expected is None or expected == 0.0:
        return None
    return round(((reported - expected) / expected) * 100.0, 1)


def _pf_difference(
    reported: float | None,
    expected: float | None,
) -> float | None:
    if reported is None or expected is None:
        return None
    return round(abs(abs(reported) - expected), 3)


def _status(apparent_mismatch: bool, pf_mismatch: bool) -> str:
    if apparent_mismatch and pf_mismatch:
        return "metric_mismatch"
    if apparent_mismatch:
        return "apparent_power_mismatch"
    if pf_mismatch:
        return "power_factor_mismatch"
    return "consistent"


def _mismatch_score(
    apparent_difference_percent: float | None,
    pf_difference: float | None,
) -> float:
    candidates: list[float] = []
    if apparent_difference_percent is not None:
        candidates.append(abs(apparent_difference_percent))
    if pf_difference is not None:
        candidates.append(round(pf_difference * 100.0, 1))
    return max(candidates, default=0.0)


def _features(result: MetricConsistencyResult) -> dict[str, float]:
    features: dict[str, float] = {
        "mismatch_score_percent": result.mismatch_score_percent
    }
    for key, value in {
        "expected_apparent_power_va": result.expected_apparent_power_va,
        "reported_apparent_power_va": result.reported_apparent_power_va,
        "apparent_power_difference_percent": result.apparent_power_difference_percent,
        "expected_power_factor": result.expected_power_factor,
        "reported_power_factor": result.reported_power_factor,
        "power_factor_difference": result.power_factor_difference,
    }.items():
        if value is not None:
            features[key] = value
    return features


def _is_idle(
    expected_va: float | None,
    reported_va: float | None,
    minimum_apparent_power_va: float,
) -> bool:
    candidates = [
        value for value in (expected_va, reported_va) if value is not None
    ]
    return bool(candidates) and max(candidates) < minimum_apparent_power_va


def _positive_number_or_none(value: float | None) -> float | None:
    number = _number_or_none(value)
    if number is None or number < 0.0:
        return None
    return number


def _power_factor_or_none(value: float | None) -> float | None:
    number = _number_or_none(value)
    if number is None or abs(number) > 1.0:
        return None
    return abs(number)


def _number_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not isfinite(number):
        return None
    return number
