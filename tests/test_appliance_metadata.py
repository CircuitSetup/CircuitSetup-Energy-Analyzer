from __future__ import annotations

from custom_components.circuitsetup_energy_analyzer.appliance_metadata import (
    appliance_icon_for_profile,
    suggested_area_for_profile,
)
from custom_components.circuitsetup_energy_analyzer.models import ApplianceProfile


def test_ranked_area_matching_prefers_existing_area_aliases() -> None:
    """Existing Home Assistant areas should win over creating a new first choice."""
    assert (
        suggested_area_for_profile(
            ApplianceProfile.MAINS_NILM,
            existing_area_names=["Basement", "Garage"],
        )
        == "Basement"
    )
    assert (
        suggested_area_for_profile(
            ApplianceProfile.HVAC,
            existing_area_names=["Basement", "HVAC"],
        )
        == "HVAC"
    )
    assert (
        suggested_area_for_profile(
            ApplianceProfile.HVAC,
            existing_area_names=["Basement", "Utility Room"],
        )
        == "Basement"
    )


def test_area_suggestion_uses_default_when_no_existing_area_matches() -> None:
    """Unknown or absent HA areas should fall back to the profile's best default."""
    assert suggested_area_for_profile(ApplianceProfile.WASHER, []) == "Laundry"
    assert suggested_area_for_profile(ApplianceProfile.REFRIGERATOR, []) == "Kitchen"
    assert suggested_area_for_profile(ApplianceProfile.DISHWASHER, []) == "Kitchen"
    assert (
        suggested_area_for_profile(ApplianceProfile.THREE_D_PRINTER, [])
        == "Workshop"
    )
    assert suggested_area_for_profile(ApplianceProfile.MIXED, []) is None


def test_appliance_icons_are_profile_specific() -> None:
    """Appliance icons should make appliance entities visually distinct."""
    assert appliance_icon_for_profile(ApplianceProfile.WASHER) == "mdi:washing-machine"
    assert appliance_icon_for_profile(ApplianceProfile.DRYER) == "mdi:tumble-dryer"
    assert appliance_icon_for_profile(ApplianceProfile.EV_CHARGER) == "mdi:ev-station"
    assert appliance_icon_for_profile(ApplianceProfile.DISHWASHER) == "mdi:dishwasher"
    assert (
        appliance_icon_for_profile(ApplianceProfile.THREE_D_PRINTER)
        == "mdi:printer-3d"
    )
    assert appliance_icon_for_profile(ApplianceProfile.MIXED) is None
