from __future__ import annotations

from dataclasses import dataclass

from .models import CircuitSample, DualPhaseSample, LegSample


@dataclass(frozen=True, slots=True)
class AggregatedDualPhaseSample(DualPhaseSample):
    """Dual-phase sample with derived aggregate values."""

    combined_real_power: float | None = None
    combined_current: float | None = None
    combined_reactive_power: float | None = None
    combined_apparent_power: float | None = None
    average_voltage: float | None = None
    average_power_factor: float | None = None
    voltage_difference: float | None = None
    leg_power_imbalance_ratio: float | None = None
    quality_issues: tuple[str, ...] = ()


def aggregate_dual_phase(
    circuit_id: str,
    left: CircuitSample,
    right: CircuitSample,
) -> AggregatedDualPhaseSample:
    """Aggregate two split-phase leg samples into a dual-phase sample."""

    issues = [*_quality_issues(left), *_quality_issues(right)]
    left_watts = left.real_power
    right_watts = right.real_power

    if _has_one_low_power_leg(left_watts, right_watts):
        issues.append("one_leg_low_power")

    return AggregatedDualPhaseSample(
        timestamp=max(left.timestamp, right.timestamp),
        circuit_id=circuit_id,
        leg_a=_leg_sample("left", left),
        leg_b=_leg_sample("right", right),
        frequency=_average_optional(left.frequency, right.frequency),
        energy=_sum_optional(left.energy, right.energy),
        combined_real_power=_sum_optional(left.real_power, right.real_power),
        combined_current=_sum_optional(left.current, right.current),
        combined_reactive_power=_sum_optional(
            left.reactive_power,
            right.reactive_power,
        ),
        combined_apparent_power=_sum_optional(
            left.apparent_power,
            right.apparent_power,
        ),
        average_voltage=_average_optional(left.voltage, right.voltage),
        average_power_factor=_average_optional(left.power_factor, right.power_factor),
        voltage_difference=_difference_optional(left.voltage, right.voltage),
        leg_power_imbalance_ratio=_imbalance_ratio(left_watts, right_watts),
        quality_issues=tuple(issues),
    )


def _leg_sample(leg: str, sample: CircuitSample) -> LegSample:
    return LegSample(
        leg=leg,
        real_power=sample.real_power,
        current=sample.current,
        voltage=sample.voltage,
        reactive_power=sample.reactive_power,
        apparent_power=sample.apparent_power,
        power_factor=sample.power_factor,
    )


def _sum_optional(left: float | None, right: float | None) -> float | None:
    values = [value for value in (left, right) if value is not None]
    if not values:
        return None
    return sum(values)


def _average_optional(left: float | None, right: float | None) -> float | None:
    values = [value for value in (left, right) if value is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _difference_optional(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return abs(left - right)


def _imbalance_ratio(left_watts: float | None, right_watts: float | None) -> float | None:
    if left_watts is None or right_watts is None:
        return None

    total = abs(left_watts) + abs(right_watts)
    if total == 0:
        return 0
    return abs(left_watts - right_watts) / (total / 2)


def _has_one_low_power_leg(
    left_watts: float | None,
    right_watts: float | None,
) -> bool:
    if left_watts is None or right_watts is None:
        return False

    magnitudes = (abs(left_watts), abs(right_watts))
    return max(magnitudes) > 500 and min(magnitudes) < 50


def _quality_issues(sample: CircuitSample) -> tuple[str, ...]:
    return tuple(getattr(sample, "quality_issues", ()))
