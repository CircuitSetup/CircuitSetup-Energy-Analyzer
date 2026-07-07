from __future__ import annotations

from types import SimpleNamespace


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
