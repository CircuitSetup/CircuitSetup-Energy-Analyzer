from functools import wraps

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry, entity_registry

pytest_plugins = ("tests_homeassistant.windows_socket_shim",)


@pytest.fixture(autouse=True)
def lightweight_hass_registries(monkeypatch):
    """Use supplied registries when unit-test hass objects lack Core setup."""
    for registry_module in (device_registry, entity_registry):
        original_get = registry_module.async_get
        attribute = registry_module.__name__.rsplit(".", 1)[-1]

        @wraps(original_get)
        def async_get(hass, original_get=original_get, attribute=attribute):
            if isinstance(hass, HomeAssistant):
                return original_get(hass)
            try:
                return original_get(hass)
            except (AttributeError, KeyError, RuntimeError, TypeError) as err:
                if isinstance(err, RuntimeError) and not isinstance(
                    err.__cause__, KeyError
                ):
                    raise
                return getattr(hass, attribute, None)

        monkeypatch.setattr(registry_module, "async_get", async_get)
