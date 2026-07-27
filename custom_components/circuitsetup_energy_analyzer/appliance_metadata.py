from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .models import ApplianceProfile


@dataclass(frozen=True, slots=True)
class ApplianceMetadata:
    """User-facing metadata for one appliance profile."""

    icon: str | None
    area_candidates: tuple[str, ...]


APPLIANCE_METADATA: dict[ApplianceProfile, ApplianceMetadata] = {
    ApplianceProfile.REFRIGERATOR: ApplianceMetadata(
        icon="mdi:fridge-outline",
        area_candidates=("Kitchen", "Garage", "Basement"),
    ),
    ApplianceProfile.FREEZER: ApplianceMetadata(
        icon="mdi:fridge-outline",
        area_candidates=("Basement", "Garage", "Kitchen", "Utility Room"),
    ),
    ApplianceProfile.HVAC: ApplianceMetadata(
        icon="mdi:hvac",
        area_candidates=(
            "HVAC",
            "Basement",
            "Utility Room",
            "Mechanical Room",
            "Attic",
            "Garage",
        ),
    ),
    ApplianceProfile.HVAC_COMPRESSOR: ApplianceMetadata(
        icon="mdi:fan",
        area_candidates=("Outside", "HVAC", "Exterior", "Side Yard", "Backyard"),
    ),
    ApplianceProfile.HVAC_BLOWER: ApplianceMetadata(
        icon="mdi:fan",
        area_candidates=(
            "HVAC",
            "Basement",
            "Utility Room",
            "Attic",
            "Mechanical Room",
        ),
    ),
    ApplianceProfile.ELECTRIC_HEAT: ApplianceMetadata(
        icon="mdi:radiator",
        area_candidates=("HVAC", "Basement", "Utility Room", "Mechanical Room"),
    ),
    ApplianceProfile.WATER_HEATER: ApplianceMetadata(
        icon="mdi:water-boiler",
        area_candidates=("Utility Room", "Basement", "Mechanical Room", "Garage"),
    ),
    ApplianceProfile.OVEN: ApplianceMetadata(
        icon="mdi:stove",
        area_candidates=("Kitchen",),
    ),
    ApplianceProfile.MICROWAVE: ApplianceMetadata(
        icon="mdi:microwave",
        area_candidates=("Kitchen",),
    ),
    ApplianceProfile.DISHWASHER: ApplianceMetadata(
        icon="mdi:dishwasher",
        area_candidates=("Kitchen",),
    ),
    ApplianceProfile.THREE_D_PRINTER: ApplianceMetadata(
        icon="mdi:printer-3d",
        area_candidates=("Workshop", "Office", "Craft Room", "Garage"),
    ),
    ApplianceProfile.WASHER: ApplianceMetadata(
        icon="mdi:washing-machine",
        area_candidates=("Laundry", "Laundry Room", "Basement", "Utility Room"),
    ),
    ApplianceProfile.DRYER: ApplianceMetadata(
        icon="mdi:tumble-dryer",
        area_candidates=("Laundry", "Laundry Room", "Basement", "Utility Room"),
    ),
    ApplianceProfile.POOL_PUMP: ApplianceMetadata(
        icon="mdi:pump",
        area_candidates=("Pool", "Pool Equipment", "Outside", "Backyard"),
    ),
    ApplianceProfile.WATER_PUMP: ApplianceMetadata(
        icon="mdi:pump",
        area_candidates=("Utility Room", "Basement", "Mechanical Room"),
    ),
    ApplianceProfile.WELL_PUMP: ApplianceMetadata(
        icon="mdi:pump",
        area_candidates=("Utility Room", "Outside", "Basement", "Mechanical Room"),
    ),
    ApplianceProfile.SUMP_PUMP: ApplianceMetadata(
        icon="mdi:pump",
        area_candidates=("Basement", "Utility Room", "Crawlspace", "Mechanical Room"),
    ),
    ApplianceProfile.EV_CHARGER: ApplianceMetadata(
        icon="mdi:ev-station",
        area_candidates=("Garage", "Driveway", "Carport", "Outside"),
    ),
    ApplianceProfile.SOLAR_INVERTER: ApplianceMetadata(
        icon="mdi:solar-power-variant",
        area_candidates=("Electrical", "Utility Room", "Garage", "Basement"),
    ),
    ApplianceProfile.MAINS_NILM: ApplianceMetadata(
        icon="mdi:transmission-tower",
        area_candidates=(
            "Electrical",
            "Basement",
            "Utility Room",
            "Mechanical Room",
            "Garage",
        ),
    ),
    ApplianceProfile.MOTOR_LOAD: ApplianceMetadata(
        icon="mdi:engine-outline",
        area_candidates=("Utility Room", "Garage", "Basement"),
    ),
    ApplianceProfile.RESISTIVE_LOAD: ApplianceMetadata(
        icon="mdi:heat-wave",
        area_candidates=("Utility Room", "Kitchen", "Garage", "Basement"),
    ),
}


def appliance_metadata_for_profile(value: Any) -> ApplianceMetadata | None:
    """Return metadata for an appliance profile-like value."""
    profile = _coerce_appliance_profile(value)
    if profile is None:
        return None
    return APPLIANCE_METADATA.get(profile)


def appliance_icon_for_profile(value: Any) -> str | None:
    """Return the preferred Material Design Icon for an appliance profile."""
    metadata = appliance_metadata_for_profile(value)
    return metadata.icon if metadata is not None else None


def suggested_area_for_profile(
    value: Any,
    existing_area_names: Iterable[str] | None = None,
) -> str | None:
    """Return the best Home Assistant Area suggestion for an appliance profile."""
    metadata = appliance_metadata_for_profile(value)
    if metadata is None or not metadata.area_candidates:
        return None

    existing = [name for name in existing_area_names or () if str(name).strip()]
    normalized_existing = {_normalize_area_name(name): name for name in existing}
    for candidate in metadata.area_candidates:
        normalized_candidate = _normalize_area_name(candidate)
        if normalized_candidate in normalized_existing:
            return normalized_existing[normalized_candidate]

    for candidate in metadata.area_candidates:
        normalized_candidate = _normalize_area_name(candidate)
        for normalized_name, original_name in normalized_existing.items():
            if (
                normalized_candidate in normalized_name
                or normalized_name in normalized_candidate
            ):
                return original_name

    return metadata.area_candidates[0]


def existing_area_names_for_hass(hass: Any) -> tuple[str, ...]:
    """Return Home Assistant Area names when the registry is available."""
    if hass is None:
        return ()
    try:
        from homeassistant.helpers import area_registry as ar
    except ImportError:
        return ()

    try:
        registry = ar.async_get(hass)
    except (AttributeError, TypeError):
        registry = getattr(hass, "area_registry", None)
    if registry is None:
        return ()
    areas = getattr(registry, "areas", {})
    values = areas.values() if hasattr(areas, "values") else areas
    names: list[str] = []
    for area in values:
        name = getattr(area, "name", None)
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return tuple(names)


def _coerce_appliance_profile(value: Any) -> ApplianceProfile | None:
    if isinstance(value, ApplianceProfile):
        return value
    try:
        return ApplianceProfile(str(value))
    except (TypeError, ValueError):
        return None


def _normalize_area_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())
