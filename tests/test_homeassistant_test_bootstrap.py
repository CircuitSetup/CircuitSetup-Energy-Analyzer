from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace


def test_http_compat_adds_removed_patch_target() -> None:
    from tests_homeassistant.homeassistant_http_compat import (
        ensure_http_server_patch_target,
    )

    module = SimpleNamespace()

    ensure_http_server_patch_target(module)

    assert callable(module.start_http_server_and_save_config)


def test_http_compat_preserves_existing_patch_target() -> None:
    from tests_homeassistant.homeassistant_http_compat import (
        ensure_http_server_patch_target,
    )

    def existing() -> None:
        return None

    module = SimpleNamespace(start_http_server_and_save_config=existing)

    ensure_http_server_patch_target(module)

    assert module.start_http_server_and_save_config is existing


def test_logger_compat_uses_relocated_cleanup(monkeypatch) -> None:
    from tests_homeassistant.homeassistant_logger_compat import (
        ensure_logger_patch_target,
    )

    def clear_logger_overwrites(hass) -> None:
        hass.overrides.clear()

    helpers = ModuleType("homeassistant.components.logger.helpers")
    helpers._clear_logger_overwrites = clear_logger_overwrites
    monkeypatch.setitem(sys.modules, helpers.__name__, helpers)
    module = SimpleNamespace()
    hass = SimpleNamespace(overrides={"test.component": "DEBUG"})

    ensure_logger_patch_target(module)
    module._clear_logger_overwrites(hass)

    assert hass.overrides == {}


def test_logger_compat_preserves_existing_cleanup() -> None:
    from tests_homeassistant.homeassistant_logger_compat import (
        ensure_logger_patch_target,
    )

    def existing() -> None:
        return None

    module = SimpleNamespace(_clear_logger_overwrites=existing)

    ensure_logger_patch_target(module)

    assert module._clear_logger_overwrites is existing


def test_logger_compat_leaves_older_ha_without_cleanup(monkeypatch) -> None:
    from tests_homeassistant.homeassistant_logger_compat import (
        ensure_logger_patch_target,
    )

    helpers = ModuleType("homeassistant.components.logger.helpers")
    monkeypatch.setitem(sys.modules, helpers.__name__, helpers)
    module = SimpleNamespace()

    ensure_logger_patch_target(module)

    assert not hasattr(module, "_clear_logger_overwrites")
