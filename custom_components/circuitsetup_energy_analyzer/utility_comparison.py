from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DEFAULT_UTILITY_COMPARISON_TOLERANCE_PERCENT = 10.0
DEFAULT_UTILITY_SOURCE_TYPE = "auto"
DEFAULT_UTILITY_STATISTIC_PERIOD = "day"
VALID_UTILITY_SOURCE_TYPES = frozenset({"auto", "entity", "statistics"})
VALID_UTILITY_STATISTIC_PERIODS = frozenset({"hour", "day", "month"})


@dataclass(frozen=True, slots=True)
class UtilityComparisonSettings:
    """Settings for comparing utility-reported kWh with measured kWh."""

    utility_energy_entity: str = ""
    utility_cost_entity: str = ""
    utility_statistic_id: str = ""
    utility_source_type: str = DEFAULT_UTILITY_SOURCE_TYPE
    utility_statistic_period: str = DEFAULT_UTILITY_STATISTIC_PERIOD
    measured_energy_entities: tuple[str, ...] = ()
    tolerance_percent: float = DEFAULT_UTILITY_COMPARISON_TOLERANCE_PERCENT


@dataclass(frozen=True, slots=True)
class StatisticsEnergyReading:
    """Latest energy value from Home Assistant recorder statistics."""

    energy_kwh: float | None
    period_start: datetime | None = None
    period_end: datetime | None = None
    source_metric: str = ""
    data_lag_hours: float | None = None


@dataclass(frozen=True, slots=True)
class UtilityComparisonResult:
    """Diagnostic comparison of utility-reported and locally measured energy."""

    status: str
    utility_energy_entity: str
    utility_statistic_id: str
    utility_source_id: str
    utility_source_type: str
    utility_statistic_period: str
    measured_entity_ids: tuple[str, ...]
    comparison_source: str
    measured_source_type: str
    period_start: str | None = None
    period_end: str | None = None
    utility_data_lag_hours: float | None = None
    utility_kwh: float | None = None
    measured_kwh: float | None = None
    difference_kwh: float = 0.0
    difference_percent: float = 0.0
    absolute_difference_percent: float = 0.0
    tolerance_percent: float = DEFAULT_UTILITY_COMPARISON_TOLERANCE_PERCENT
    features: dict[str, float] | None = None


def compare_utility_energy(
    *,
    settings: UtilityComparisonSettings,
    utility_kwh: float | None,
    measured_kwh: float | None,
    measured_entity_ids: tuple[str, ...],
    comparison_source: str,
    utility_source_type: str = DEFAULT_UTILITY_SOURCE_TYPE,
    measured_source_type: str = "entity_state",
    period_start: str | None = None,
    period_end: str | None = None,
    utility_data_lag_hours: float | None = None,
) -> UtilityComparisonResult:
    """Compare same-period utility kWh with same-period measured kWh."""
    tolerance_percent = max(float(settings.tolerance_percent), 0.0)
    resolved_source_type = _resolved_utility_source_type(settings, utility_source_type)
    utility_source_id = _utility_source_id(settings, resolved_source_type)

    if not utility_source_id:
        return _result(
            "unconfigured",
            settings=settings,
            measured_entity_ids=measured_entity_ids,
            comparison_source=comparison_source,
            utility_source_type=resolved_source_type,
            measured_source_type=measured_source_type,
            period_start=period_start,
            period_end=period_end,
            utility_data_lag_hours=utility_data_lag_hours,
        )
    if utility_kwh is None:
        return _result(
            "missing_utility",
            settings=settings,
            measured_entity_ids=measured_entity_ids,
            comparison_source=comparison_source,
            utility_source_type=resolved_source_type,
            measured_source_type=measured_source_type,
            period_start=period_start,
            period_end=period_end,
            utility_data_lag_hours=utility_data_lag_hours,
        )
    if measured_kwh is None:
        return _result(
            "missing_measured",
            settings=settings,
            utility_kwh=float(utility_kwh),
            measured_entity_ids=measured_entity_ids,
            comparison_source=comparison_source,
            utility_source_type=resolved_source_type,
            measured_source_type=measured_source_type,
            period_start=period_start,
            period_end=period_end,
            utility_data_lag_hours=utility_data_lag_hours,
        )

    utility = round(float(utility_kwh), 3)
    measured = round(float(measured_kwh), 3)
    difference = round(measured - utility, 3)
    if utility > 0.0:
        difference_percent = round((difference / utility) * 100.0, 3)
    else:
        difference_percent = 0.0 if measured == 0.0 else 100.0
    absolute_difference_percent = round(abs(difference_percent), 3)
    status = (
        "mismatch"
        if absolute_difference_percent > tolerance_percent
        else "tracking"
    )
    features = {
        "utility_kwh": utility,
        "measured_kwh": measured,
        "difference_kwh": difference,
        "difference_percent": difference_percent,
        "absolute_difference_percent": absolute_difference_percent,
        "tolerance_percent": tolerance_percent,
        "measured_entity_count": float(len(measured_entity_ids)),
    }
    return _result(
        status,
        settings=settings,
        utility_kwh=utility,
        measured_kwh=measured,
        difference_kwh=difference,
        difference_percent=difference_percent,
        absolute_difference_percent=absolute_difference_percent,
        tolerance_percent=tolerance_percent,
        measured_entity_ids=measured_entity_ids,
        comparison_source=comparison_source,
        utility_source_type=resolved_source_type,
        measured_source_type=measured_source_type,
        period_start=period_start,
        period_end=period_end,
        utility_data_lag_hours=utility_data_lag_hours,
        features=features,
    )


def utility_rate_per_kwh(
    utility_cost: float | None,
    utility_kwh: float | None,
) -> float | None:
    """Return an Opower-derived rate when matching cost and usage are present."""
    if utility_cost is None or utility_kwh is None or utility_kwh <= 0.0:
        return None
    if utility_cost < 0.0:
        return None
    return round(float(utility_cost) / float(utility_kwh), 4)


def configured_electricity_rate(cost_settings_by_circuit: Any) -> float:
    """Return the persisted analyzer-wide fallback electricity rate."""
    if not isinstance(cost_settings_by_circuit, Mapping):
        return 0.0
    settings = cost_settings_by_circuit.get("__global__", {})
    if not isinstance(settings, Mapping):
        return 0.0
    return _positive_electricity_rate(settings.get("default_rate_per_kwh"))


def effective_electricity_rate(
    utility_cost_rate_by_circuit: Any,
    fallback_rate: Any = None,
) -> float:
    """Return the Opower rate when available, otherwise the fallback rate."""
    if isinstance(utility_cost_rate_by_circuit, Mapping):
        for rate in utility_cost_rate_by_circuit.values():
            value = _positive_electricity_rate(rate)
            if value > 0.0:
                return value
    return _positive_electricity_rate(fallback_rate)


def _positive_electricity_rate(value: Any) -> float:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return 0.0
    return rate if rate > 0.0 else 0.0


def select_latest_statistics_energy(
    statistic_id: str,
    statistics: dict[str, list[dict[str, float | int | None]]],
    now: datetime,
) -> StatisticsEnergyReading:
    """Select the latest usable kWh value from recorder statistics rows."""
    rows = statistics.get(statistic_id) or []
    usable: list[tuple[datetime, dict[str, float | int | None], float, str]] = []
    for row in rows:
        period_end = _timestamp_to_datetime(row.get("end") or row.get("start"))
        if period_end is None:
            continue
        value, source_metric = _statistics_energy_value(row)
        if value is None:
            continue
        usable.append((period_end, row, value, source_metric))
    if not usable:
        return StatisticsEnergyReading(energy_kwh=None)

    period_end, row, value, source_metric = max(usable, key=lambda item: item[0])
    period_start = _timestamp_to_datetime(row.get("start"))
    data_lag_hours = round(
        max((now.astimezone(UTC) - period_end).total_seconds() / 3600.0, 0.0),
        3,
    )
    return StatisticsEnergyReading(
        energy_kwh=round(value, 3),
        period_start=period_start,
        period_end=period_end,
        source_metric=source_metric,
        data_lag_hours=data_lag_hours,
    )


def select_statistics_energy_for_period(
    statistic_id: str,
    statistics: dict[str, list[dict[str, float | int | None]]],
    now: datetime,
    *,
    period_start: datetime,
    period_end: datetime,
) -> StatisticsEnergyReading:
    """Select a recorder statistics row matching an exact start/end period."""
    rows = statistics.get(statistic_id) or []
    target_start = period_start.astimezone(UTC)
    target_end = period_end.astimezone(UTC)
    for row in rows:
        row_start = _timestamp_to_datetime(row.get("start"))
        row_end = _timestamp_to_datetime(row.get("end") or row.get("start"))
        if row_start != target_start or row_end != target_end:
            continue
        value, source_metric = _statistics_energy_value(row)
        if value is None:
            continue
        data_lag_hours = round(
            max((now.astimezone(UTC) - row_end).total_seconds() / 3600.0, 0.0),
            3,
        )
        return StatisticsEnergyReading(
            energy_kwh=round(value, 3),
            period_start=row_start,
            period_end=row_end,
            source_metric=source_metric,
            data_lag_hours=data_lag_hours,
        )
    return StatisticsEnergyReading(
        energy_kwh=None,
        period_start=target_start,
        period_end=target_end,
    )


def _result(
    status: str,
    *,
    settings: UtilityComparisonSettings,
    measured_entity_ids: tuple[str, ...],
    comparison_source: str,
    utility_source_type: str = DEFAULT_UTILITY_SOURCE_TYPE,
    measured_source_type: str = "entity_state",
    period_start: str | None = None,
    period_end: str | None = None,
    utility_data_lag_hours: float | None = None,
    utility_kwh: float | None = None,
    measured_kwh: float | None = None,
    difference_kwh: float = 0.0,
    difference_percent: float = 0.0,
    absolute_difference_percent: float = 0.0,
    tolerance_percent: float | None = None,
    features: dict[str, float] | None = None,
) -> UtilityComparisonResult:
    resolved_source_type = _resolved_utility_source_type(settings, utility_source_type)
    return UtilityComparisonResult(
        status=status,
        utility_energy_entity=settings.utility_energy_entity.strip(),
        utility_statistic_id=settings.utility_statistic_id.strip(),
        utility_source_id=_utility_source_id(settings, resolved_source_type),
        utility_source_type=resolved_source_type,
        utility_statistic_period=_normalized_statistic_period(
            settings.utility_statistic_period
        ),
        measured_entity_ids=measured_entity_ids,
        comparison_source=comparison_source,
        measured_source_type=str(measured_source_type or "entity_state"),
        period_start=period_start,
        period_end=period_end,
        utility_data_lag_hours=utility_data_lag_hours,
        utility_kwh=utility_kwh,
        measured_kwh=measured_kwh,
        difference_kwh=difference_kwh,
        difference_percent=difference_percent,
        absolute_difference_percent=absolute_difference_percent,
        tolerance_percent=(
            max(float(settings.tolerance_percent), 0.0)
            if tolerance_percent is None
            else tolerance_percent
        ),
        features=features,
    )


def _statistics_energy_value(
    row: dict[str, float | int | None],
) -> tuple[float | None, str]:
    for key in ("change", "sum", "state"):
        value = row.get(key)
        if value is None:
            continue
        try:
            return float(value), key
        except (TypeError, ValueError):
            continue
    return None, ""


def _timestamp_to_datetime(value: float | int | None) -> datetime | None:
    if value is None:
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if timestamp > 10_000_000_000:
        timestamp /= 1000.0
    return datetime.fromtimestamp(timestamp, UTC)


def _resolved_utility_source_type(
    settings: UtilityComparisonSettings,
    source_type: str,
) -> str:
    normalized = _normalized_source_type(source_type)
    if normalized == "auto":
        normalized = _normalized_source_type(settings.utility_source_type)
    if normalized == "auto":
        return "statistics" if settings.utility_statistic_id.strip() else "entity"
    return normalized


def _normalized_source_type(source_type: str) -> str:
    normalized = str(source_type or DEFAULT_UTILITY_SOURCE_TYPE).strip().lower()
    if normalized == "statistic":
        normalized = "statistics"
    if normalized not in VALID_UTILITY_SOURCE_TYPES:
        return DEFAULT_UTILITY_SOURCE_TYPE
    return normalized


def _normalized_statistic_period(period: str) -> str:
    normalized = str(period or DEFAULT_UTILITY_STATISTIC_PERIOD).strip().lower()
    if normalized not in VALID_UTILITY_STATISTIC_PERIODS:
        return DEFAULT_UTILITY_STATISTIC_PERIOD
    return normalized


def _utility_source_id(
    settings: UtilityComparisonSettings,
    source_type: str,
) -> str:
    if source_type == "statistics":
        return settings.utility_statistic_id.strip()
    return settings.utility_energy_entity.strip()
