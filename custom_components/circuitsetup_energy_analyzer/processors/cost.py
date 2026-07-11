"""Energy cost processor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from ..cost import CostSettings, record_cost_sample
from ..models import CircuitConfig
from ..normalize import NormalizedCircuitSample
from .base import FeatureResult, ProcessingContext, StateUpdate

type CostSettingsProvider = Callable[[CircuitConfig | None, str], CostSettings]
type UtilityRateProvider = Callable[[str], float | None]


class CostProcessor:
    """Track billing-cycle cost estimates for one circuit."""

    name = "cost"

    def __init__(
        self,
        *,
        settings_for_config: CostSettingsProvider,
        utility_rate_for_circuit: UtilityRateProvider | None = None,
    ) -> None:
        self._settings_for_config = settings_for_config
        self._utility_rate_for_circuit = utility_rate_for_circuit or (
            lambda _circuit_id: None
        )

    def process(
        self,
        sample: NormalizedCircuitSample,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Record cost usage and return state updates."""
        circuit_id = circuit_config.circuit_id
        settings = self._settings_for_config(circuit_config, circuit_id)
        utility_rate = self._utility_rate_for_circuit(circuit_id)
        if utility_rate is not None and utility_rate > 0.0:
            settings = replace(
                settings,
                default_rate_per_kwh=utility_rate,
                tou_rate_per_kwh=None,
            )
        result = record_cost_sample(
            context.store_data.cost_by_circuit.setdefault(circuit_id, {}),
            circuit_id=circuit_id,
            timestamp=context.now,
            energy_kwh=sample.energy,
            settings=settings,
        )
        if result is None:
            return FeatureResult()

        return FeatureResult(
            state_updates=[
                StateUpdate(
                    ("cost_current_rate_by_circuit", circuit_id),
                    result.current_rate_per_kwh,
                ),
                StateUpdate(("cost_cycle_by_circuit", circuit_id), result.cycle_cost),
                StateUpdate(
                    ("cost_cycle_forecast_by_circuit", circuit_id),
                    result.projected_cycle_cost,
                ),
                StateUpdate(("cost_status_by_circuit", circuit_id), result.status),
                StateUpdate(
                    ("cost_evidence_by_circuit", circuit_id),
                    cost_evidence_payload(result),
                ),
            ],
            store_dirty=True,
        )


def cost_evidence_payload(result: Any) -> dict[str, Any]:
    """Build the analyzer state payload for cost tracking."""
    return {
        "cycle_start": result.cycle_start,
        "cycle_end": result.cycle_end,
        "cycle_start_day": result.cycle_start_day,
        "current_rate_per_kwh": result.current_rate_per_kwh,
        "active_rate_name": result.active_rate_name,
        "delta_kwh": result.delta_kwh,
        "delta_cost": result.delta_cost,
        "cycle_cost": result.cycle_cost,
        "projected_cycle_cost": result.projected_cycle_cost,
        "elapsed_days": result.elapsed_days,
        "cycle_days": result.cycle_days,
        "status": result.status,
    }
