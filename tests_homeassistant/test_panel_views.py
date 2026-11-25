from types import SimpleNamespace

import pytest
from homeassistant.exceptions import Unauthorized

from custom_components.circuitsetup_energy_analyzer.panel_views import (
    ApplianceDetailView,
    SetupHealthView,
)


@pytest.mark.parametrize("view_type", [ApplianceDetailView, SetupHealthView])
@pytest.mark.asyncio
async def test_mutating_panel_views_require_admin(view_type: type) -> None:
    request = {"hass_user": SimpleNamespace(is_admin=False)}

    with pytest.raises(Unauthorized):
        await view_type().post(request)


@pytest.mark.asyncio
async def test_meter_choices_follow_scoped_view_links(hass) -> None:
    import json
    from urllib.parse import parse_qsl, urlsplit

    from homeassistant.components.http import KEY_HASS
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.models import (
        ApplianceProfile,
        CircuitConfig,
        CircuitMode,
    )
    from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData

    meters = hass.data[DOMAIN] = {}
    for location in ("Kitchen", "Garage"):
        entry = MockConfigEntry(
            domain=DOMAIN, entry_id=location.lower(), title=location
        )
        entry.add_to_hass(hass)
        config = CircuitConfig(
            circuit_id="fridge",
            name=f"{location} fridge",
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            mode=CircuitMode.SINGLE_PHASE,
        )
        meters[entry.entry_id] = SimpleNamespace(
            entry_id=entry.entry_id,
            hass=hass,
            circuit_configs=(config,),
            state=AnalyzerState(),
            store_data=FeatureStoreData(),
        )

    async def get(query):
        request = SimpleNamespace(app={KEY_HASS: hass}, query=query)
        response = await ApplianceDetailView().get(request)
        return json.loads(response.body)

    choices = await get({"circuit_id": "fridge"})
    assert choices["status"] == "choose_meter"
    assert choices["actions"] == {}
    for choice in choices["meter_choices"]:
        query = dict(parse_qsl(urlsplit(choice["url"]).query))
        detail = await get(query)
        assert detail["detail"]["display_name"] == f"{choice['label']} fridge"
    assert (await get({"circuit_id": "fridge", "entry_id": "missing"}))[
        "status"
    ] == "not_found"
