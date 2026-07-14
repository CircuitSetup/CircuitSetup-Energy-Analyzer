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
