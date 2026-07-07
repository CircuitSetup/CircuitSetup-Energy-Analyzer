from __future__ import annotations

pytest_plugins = (
    "tests_homeassistant.homeassistant_http_compat",
    "pytest_homeassistant_custom_component",
    "tests_homeassistant.windows_socket_shim",
)
