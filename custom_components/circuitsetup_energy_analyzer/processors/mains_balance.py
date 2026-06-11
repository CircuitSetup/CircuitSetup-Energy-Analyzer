"""Mains balance processor."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..balance import (
    DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W,
    BalanceInput,
    BalanceResult,
    calculate_balance,
)
from ..models import ApplianceProfile, CircuitConfig, CircuitMode, PowerFlowMode
from ..normalize import NormalizedCircuitSample
from .base import FeatureResult, ProcessingContext, StateUpdate

type MainsBalanceSettingsProvider = Callable[[str], Mapping[str, Any]]


class MainsBalanceProcessor:
    """Calculate mains minus monitored-load balance for mains NILM circuits."""

    name = "mains_balance"

    def __init__(
        self,
        *,
        settings_for_circuit: MainsBalanceSettingsProvider,
    ) -> None:
        self._settings_for_circuit = settings_for_circuit

    def process(
        self,
        samples: list[tuple[CircuitConfig, NormalizedCircuitSample]],
        context: ProcessingContext,
    ) -> FeatureResult:
        """Return state updates for every mains NILM sample in a batch."""
        del context
        mains_items = [
            (config, sample)
            for config, sample in samples
            if _is_mains_nilm(config)
        ]
        if not mains_items:
            return FeatureResult()

        mains_configs = {item[0] for item in mains_items}
        monitored = [
            BalanceInput(
                circuit_id=config.circuit_id,
                real_power_w=sample.real_power,
                generation=_is_generation(config),
            )
            for config, sample in samples
            if config not in mains_configs
        ]

        state_updates: list[StateUpdate] = []
        for config, sample in mains_items:
            settings = self._settings_for_circuit(config.circuit_id)
            result = calculate_balance(
                mains=BalanceInput(
                    circuit_id=config.circuit_id,
                    real_power_w=sample.real_power,
                ),
                monitored=monitored,
                negative_tolerance_w=_nonnegative_float_value(
                    settings.get("negative_tolerance_w"),
                    default=DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W,
                ),
            )
            state_updates.extend(
                mains_balance_state_updates(config.circuit_id, result),
            )

        return FeatureResult(state_updates=state_updates)


def mains_balance_state_updates(
    circuit_id: str,
    result: BalanceResult,
) -> list[StateUpdate]:
    """Build state updates for a mains balance calculation."""
    return [
        StateUpdate(("balance_power_w_by_circuit", circuit_id), result.balance_power_w),
        StateUpdate(
            ("monitored_power_w_by_circuit", circuit_id),
            result.monitored_power_w,
        ),
        StateUpdate(
            ("monitored_coverage_percent_by_circuit", circuit_id),
            result.monitored_coverage_percent,
        ),
        StateUpdate(("balance_status_by_circuit", circuit_id), result.status),
        StateUpdate(
            ("balance_evidence_by_circuit", circuit_id),
            {
                **result.features,
                "status": result.status,
            },
        ),
    ]


def _is_mains_nilm(config: CircuitConfig) -> bool:
    return (
        config.mode is CircuitMode.MAINS_NILM
        or config.appliance_profile is ApplianceProfile.MAINS_NILM
    )


def _is_generation(config: CircuitConfig) -> bool:
    return (
        config.power_flow is PowerFlowMode.GENERATION
        or config.appliance_profile is ApplianceProfile.SOLAR_INVERTER
    )


def _nonnegative_float_value(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0.0 else default
