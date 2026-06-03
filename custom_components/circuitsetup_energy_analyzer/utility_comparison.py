from __future__ import annotations

from dataclasses import dataclass

DEFAULT_UTILITY_COMPARISON_TOLERANCE_PERCENT = 10.0


@dataclass(frozen=True, slots=True)
class UtilityComparisonSettings:
    """Settings for comparing utility-reported kWh with measured kWh."""

    utility_energy_entity: str = ""
    measured_energy_entities: tuple[str, ...] = ()
    tolerance_percent: float = DEFAULT_UTILITY_COMPARISON_TOLERANCE_PERCENT


@dataclass(frozen=True, slots=True)
class UtilityComparisonResult:
    """Diagnostic comparison of utility-reported and locally measured energy."""

    status: str
    utility_energy_entity: str
    measured_entity_ids: tuple[str, ...]
    comparison_source: str
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
) -> UtilityComparisonResult:
    """Compare same-period utility kWh with same-period measured kWh."""
    tolerance_percent = max(float(settings.tolerance_percent), 0.0)
    utility_entity = settings.utility_energy_entity.strip()

    if not utility_entity:
        return _result(
            "unconfigured",
            settings=settings,
            measured_entity_ids=measured_entity_ids,
            comparison_source=comparison_source,
        )
    if utility_kwh is None:
        return _result(
            "missing_utility",
            settings=settings,
            measured_entity_ids=measured_entity_ids,
            comparison_source=comparison_source,
        )
    if measured_kwh is None:
        return _result(
            "missing_measured",
            settings=settings,
            utility_kwh=float(utility_kwh),
            measured_entity_ids=measured_entity_ids,
            comparison_source=comparison_source,
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
        features=features,
    )


def _result(
    status: str,
    *,
    settings: UtilityComparisonSettings,
    measured_entity_ids: tuple[str, ...],
    comparison_source: str,
    utility_kwh: float | None = None,
    measured_kwh: float | None = None,
    difference_kwh: float = 0.0,
    difference_percent: float = 0.0,
    absolute_difference_percent: float = 0.0,
    tolerance_percent: float | None = None,
    features: dict[str, float] | None = None,
) -> UtilityComparisonResult:
    return UtilityComparisonResult(
        status=status,
        utility_energy_entity=settings.utility_energy_entity.strip(),
        measured_entity_ids=measured_entity_ids,
        comparison_source=comparison_source,
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
