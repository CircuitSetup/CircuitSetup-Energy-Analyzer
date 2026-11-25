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


@pytest.mark.asyncio
async def test_attention_view_only_returns_loaded_scope(hass):
    import json

    from homeassistant.components.http import KEY_HASS
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
    from custom_components.circuitsetup_energy_analyzer.panel_views import (
        ApplianceInsightsView,
    )
    from tests.test_appliance_detail import _direct_coordinator

    meter = _direct_coordinator()
    hass.data[DOMAIN] = {meter.entry_id: meter}
    assert ApplianceInsightsView.requires_auth

    async def read(**query):
        response = await ApplianceInsightsView().get(
            SimpleNamespace(app={KEY_HASS: hass}, query={"view": "attention", **query})
        )
        return json.loads(response.body)

    entry = MockConfigEntry(
        domain=DOMAIN, entry_id=meter.entry_id, title="Kitchen meter"
    )
    entry.add_to_hass(hass)
    meter.hass = hass
    area = ar.async_get(hass).async_create("Kitchen")
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_fridge")},
    )
    devices.async_update_device(device.id, area_id=area.id)
    result = await read()
    assert result["total_affected"] == 1
    assert result["items"][0]["area"] == "Kitchen"
    assert (await read(offset="100"))["items"] == []
    assert (await read(entry_id="unloaded"))["status"] == "not_found"
    assert (await read(entry_id=""))["items"] == []
    for index in range(100):
        other = _direct_coordinator()
        other.entry_id = f"other-{index:03d}"
        hass.data[DOMAIN][other.entry_id] = other
    result = await read()
    assert result["total_affected"] == result["matching_count"] == 101
    page = await read(offset=str(result["next_offset"]))
    assert len(page["items"]) == 1 and page["next_offset"] is None
    assert (await read(entry_id=meter.entry_id))["coverage"]["direct_monitored"] == 1
