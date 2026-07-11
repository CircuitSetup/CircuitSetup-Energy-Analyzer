"""Utility energy comparison processor."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime
from typing import Any, Protocol

from ..alerting import Observation
from ..models import AlertEvidence, CircuitConfig
from ..utility_comparison import (
    UtilityComparisonResult,
    UtilityComparisonSettings,
    compare_utility_energy,
    utility_rate_per_kwh,
)
from .base import AlertPolicy, FeatureResult, ProcessingContext, StateUpdate


class _UtilityReading(Protocol):
    """Statistics reading surface used by this processor."""

    energy_kwh: float | None
    period_start: datetime | None
    period_end: datetime | None
    data_lag_hours: float | None


type UtilitySettingsProvider = Callable[[str], UtilityComparisonSettings]
type UtilityAlertPolicyProvider = Callable[[str], AlertPolicy]
type EnergyEntityReader = Callable[[str, datetime], float | None]
type NumericEntityReader = Callable[[str], float | None]
type EnergyEntitySummer = Callable[
    [Iterable[str], datetime],
    tuple[float | None, tuple[str, ...]],
]
type StatisticsReader = Callable[
    [str, datetime, str],
    Awaitable[_UtilityReading],
]
type StatisticsEntitySummer = Callable[
    [Iterable[str], datetime, str, datetime, datetime],
    Awaitable[tuple[float | None, tuple[str, ...]]],
]
type LoadEnergyEntityProvider = Callable[[str], tuple[str, ...]]


class UtilityComparisonProcessor:
    """Compare utility-reported energy against measured circuit energy."""

    name = "utility_comparison"

    def __init__(
        self,
        *,
        settings_for_circuit: UtilitySettingsProvider,
        alert_policy_for_circuit: UtilityAlertPolicyProvider,
        energy_kwh_for_entity: EnergyEntityReader,
        energy_kwh_sum_for_entities: EnergyEntitySummer,
        statistics_kwh_for_id: StatisticsReader | None,
        statistics_kwh_sum_for_entities: StatisticsEntitySummer | None,
        load_energy_entity_ids_for_sum: LoadEnergyEntityProvider,
        numeric_value_for_entity: NumericEntityReader | None = None,
    ) -> None:
        self._settings_for_circuit = settings_for_circuit
        self._alert_policy_for_circuit = alert_policy_for_circuit
        self._energy_kwh_for_entity = energy_kwh_for_entity
        self._energy_kwh_sum_for_entities = energy_kwh_sum_for_entities
        self._statistics_kwh_for_id = statistics_kwh_for_id
        self._statistics_kwh_sum_for_entities = statistics_kwh_sum_for_entities
        self._load_energy_entity_ids_for_sum = load_energy_entity_ids_for_sum
        self._numeric_value_for_entity = numeric_value_for_entity or (
            lambda _entity_id: None
        )

    async def process(
        self,
        circuit_config: CircuitConfig,
        context: ProcessingContext,
    ) -> FeatureResult:
        """Return state updates and alerts for one utility comparison."""
        settings = self._settings_for_circuit(circuit_config.circuit_id)
        utility_source_type = utility_source_type_for_settings(settings)
        (
            utility_kwh,
            utility_period_start,
            utility_period_end,
            utility_data_lag_hours,
        ) = await self._utility_reading(settings, context.now, utility_source_type)
        (
            measured_kwh,
            measured_entity_ids,
            comparison_source,
            measured_source_type,
        ) = await self._measured_reading(
            settings,
            circuit_config.circuit_id,
            context.now,
            utility_source_type=utility_source_type,
            utility_period_start=utility_period_start,
            utility_period_end=utility_period_end,
        )

        result = compare_utility_energy(
            settings=settings,
            utility_kwh=utility_kwh,
            measured_kwh=measured_kwh,
            measured_entity_ids=measured_entity_ids,
            comparison_source=comparison_source,
            utility_source_type=utility_source_type,
            measured_source_type=measured_source_type,
            period_start=_datetime_iso_or_none(utility_period_start),
            period_end=_datetime_iso_or_none(utility_period_end),
            utility_data_lag_hours=utility_data_lag_hours,
        )
        utility_cost = self._numeric_value_for_entity(settings.utility_cost_entity)
        feature_result = FeatureResult(
            state_updates=utility_comparison_state_updates(
                circuit_config.circuit_id,
                result,
                utility_cost=utility_cost,
                utility_cost_entity=settings.utility_cost_entity,
            ),
        )
        if result.status == "mismatch":
            alert = self._mismatch_alert(circuit_config, context, result)
            if alert is not None:
                feature_result.alerts.append(alert)
                feature_result.notifications.append(alert)
        return feature_result

    async def _utility_reading(
        self,
        settings: UtilityComparisonSettings,
        now: datetime,
        utility_source_type: str,
    ) -> tuple[float | None, datetime | None, datetime | None, float | None]:
        if utility_source_type == "statistics":
            if self._statistics_kwh_for_id is None:
                return None, None, None, None
            utility_reading = await self._statistics_kwh_for_id(
                settings.utility_statistic_id,
                now,
                settings.utility_statistic_period,
            )
            return (
                utility_reading.energy_kwh,
                utility_reading.period_start,
                utility_reading.period_end,
                utility_reading.data_lag_hours,
            )
        return (
            self._energy_kwh_for_entity(settings.utility_energy_entity, now),
            None,
            None,
            None,
        )

    async def _measured_reading(
        self,
        settings: UtilityComparisonSettings,
        circuit_id: str,
        now: datetime,
        *,
        utility_source_type: str,
        utility_period_start: datetime | None,
        utility_period_end: datetime | None,
    ) -> tuple[float | None, tuple[str, ...], str, str]:
        utility_period_available = (
            utility_period_start is not None and utility_period_end is not None
        )
        if settings.measured_energy_entities:
            comparison_source = "explicit_entities"
            energy_entities = settings.measured_energy_entities
        else:
            comparison_source = "circuit_energy_sum"
            energy_entities = self._load_energy_entity_ids_for_sum(circuit_id)

        if utility_source_type == "statistics" and not utility_period_available:
            return None, energy_entities, comparison_source, "statistics"
        if utility_period_available:
            if self._statistics_kwh_sum_for_entities is None:
                return None, energy_entities, comparison_source, "statistics"
            measured_kwh, measured_entity_ids = (
                await self._statistics_kwh_sum_for_entities(
                    energy_entities,
                    now,
                    settings.utility_statistic_period,
                    utility_period_start,
                    utility_period_end,
                )
            )
            return measured_kwh, measured_entity_ids, comparison_source, "statistics"

        measured_kwh, measured_entity_ids = self._energy_kwh_sum_for_entities(
            energy_entities,
            now,
        )
        return measured_kwh, measured_entity_ids, comparison_source, "entity_state"

    def _mismatch_alert(
        self,
        config: CircuitConfig,
        context: ProcessingContext,
        result: UtilityComparisonResult,
    ) -> AlertEvidence | None:
        score = (
            result.absolute_difference_percent / result.tolerance_percent
            if result.tolerance_percent > 0.0
            else result.absolute_difference_percent
        )
        return self._alert_policy_for_circuit(config.circuit_id).observe(
            Observation(
                circuit_id=config.circuit_id,
                feature="utility_energy_mismatch",
                score=score,
                baseline_confidence=1.0,
                observed_at=context.now,
                observed_value=result.measured_kwh or 0.0,
                baseline_value=result.utility_kwh or 0.0,
                message=utility_comparison_message(config, result),
                features=result.features or {},
            )
        )


def utility_comparison_state_updates(
    circuit_id: str,
    result: UtilityComparisonResult,
    *,
    utility_cost: float | None = None,
    utility_cost_entity: str = "",
) -> list[StateUpdate]:
    """Build analyzer state updates for one utility comparison result."""
    rate_per_kwh = utility_rate_per_kwh(utility_cost, result.utility_kwh)
    return [
        StateUpdate(
            ("utility_comparison_difference_kwh_by_circuit", circuit_id),
            result.difference_kwh,
        ),
        StateUpdate(
            ("utility_comparison_difference_percent_by_circuit", circuit_id),
            result.difference_percent,
        ),
        StateUpdate(
            ("utility_comparison_status_by_circuit", circuit_id),
            result.status,
        ),
        StateUpdate(
            ("utility_comparison_evidence_by_circuit", circuit_id),
            utility_comparison_evidence_payload(
                result,
                utility_cost=utility_cost,
                rate_per_kwh=rate_per_kwh,
                utility_cost_entity=utility_cost_entity,
            ),
        ),
        StateUpdate(
            ("utility_cost_rate_by_circuit", circuit_id),
            rate_per_kwh or 0.0,
        ),
    ]


def utility_comparison_message(
    config: CircuitConfig,
    result: UtilityComparisonResult,
) -> str:
    """Build the user-facing utility comparison mismatch message."""
    return (
        f"Utility comparison mismatch: {config.name} measured "
        f"{_format_kwh(result.measured_kwh or 0.0)} kWh while "
        f"{result.utility_source_id} reports "
        f"{_format_kwh(result.utility_kwh or 0.0)} kWh. Difference is "
        f"{_format_kwh(result.difference_kwh)} kWh "
        f"({_format_percent(result.absolute_difference_percent)}%), above the "
        f"{_format_percent(result.tolerance_percent)}% tolerance. Verify both "
        "sensors cover the same billing or current-bill period before treating "
        "this as a meter, CT, or utility-data problem."
    )


def utility_comparison_evidence_payload(
    result: UtilityComparisonResult,
    *,
    utility_cost: float | None = None,
    rate_per_kwh: float | None = None,
    utility_cost_entity: str = "",
) -> dict[str, Any]:
    """Build the analyzer state payload for utility comparison."""
    payload = {
        "status": result.status,
        "utility_energy_entity": result.utility_energy_entity,
        "utility_statistic_id": result.utility_statistic_id,
        "utility_source_id": result.utility_source_id,
        "utility_source_type": result.utility_source_type,
        "utility_statistic_period": result.utility_statistic_period,
        "measured_energy_entities": list(result.measured_entity_ids),
        "comparison_source": result.comparison_source,
        "measured_source_type": result.measured_source_type,
        "period_start": result.period_start,
        "period_end": result.period_end,
        "utility_data_lag_hours": result.utility_data_lag_hours,
        "utility_kwh": result.utility_kwh,
        "measured_kwh": result.measured_kwh,
        "difference_kwh": result.difference_kwh,
        "difference_percent": result.difference_percent,
        "absolute_difference_percent": result.absolute_difference_percent,
        "tolerance_percent": result.tolerance_percent,
    }
    if utility_cost_entity:
        payload.update(
            {
                "utility_cost_entity": utility_cost_entity,
                "utility_cost": utility_cost,
                "rate_per_kwh": rate_per_kwh,
            }
        )
    return payload


def utility_source_type_for_settings(settings: UtilityComparisonSettings) -> str:
    """Select entity or statistics utility source mode from settings."""
    raw = str(settings.utility_source_type or "auto").strip().lower()
    if raw == "statistic":
        raw = "statistics"
    if raw not in {"auto", "entity", "statistics"}:
        raw = "auto"
    if raw == "auto":
        return "statistics" if settings.utility_statistic_id.strip() else "entity"
    return raw


def _datetime_iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _format_kwh(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _format_percent(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")
