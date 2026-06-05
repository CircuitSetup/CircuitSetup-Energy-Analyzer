from __future__ import annotations

from dataclasses import dataclass

DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W = 100.0


@dataclass(frozen=True, slots=True)
class BalanceInput:
    """Power input used to calculate unmonitored balance."""

    circuit_id: str
    real_power_w: float | None
    generation: bool = False


@dataclass(frozen=True, slots=True)
class BalanceResult:
    """Calculated mains-minus-monitored balance."""

    mains_power_w: float
    monitored_power_w: float
    balance_power_w: float
    monitored_coverage_percent: float
    monitored_circuit_count: int
    status: str
    features: dict[str, float]


def calculate_balance(
    *,
    mains: BalanceInput | None,
    monitored: list[BalanceInput],
    negative_tolerance_w: float = DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W,
) -> BalanceResult:
    """Calculate unmonitored balance from mains and monitored circuit power."""
    if mains is None or mains.real_power_w is None:
        return _result(0.0, 0.0, 0, "missing_mains")

    monitored_loads = [
        item
        for item in monitored
        if not item.generation and item.real_power_w is not None
    ]
    mains_power = max(float(mains.real_power_w), 0.0)
    monitored_power = sum(
        max(float(item.real_power_w), 0.0) for item in monitored_loads
    )

    if not monitored_loads:
        return _result(mains_power, 0.0, 0, "no_monitored_circuits")

    balance_power = round(mains_power - monitored_power, 1)
    if balance_power < -abs(float(negative_tolerance_w)):
        status = "negative_balance"
    else:
        status = "tracking"
    return _result(mains_power, monitored_power, len(monitored_loads), status)


def _result(
    mains_power_w: float,
    monitored_power_w: float,
    monitored_circuit_count: int,
    status: str,
) -> BalanceResult:
    mains_power_w = round(float(mains_power_w), 1)
    monitored_power_w = round(float(monitored_power_w), 1)
    balance_power_w = round(mains_power_w - monitored_power_w, 1)
    coverage = (
        round((monitored_power_w / mains_power_w) * 100, 1)
        if mains_power_w > 0.0
        else 0.0
    )
    return BalanceResult(
        mains_power_w=mains_power_w,
        monitored_power_w=monitored_power_w,
        balance_power_w=balance_power_w,
        monitored_coverage_percent=coverage,
        monitored_circuit_count=monitored_circuit_count,
        status=status,
        features={
            "mains_power_w": mains_power_w,
            "monitored_power_w": monitored_power_w,
            "balance_power_w": balance_power_w,
            "monitored_coverage_percent": coverage,
            "monitored_circuit_count": float(monitored_circuit_count),
        },
    )
