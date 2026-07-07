from __future__ import annotations

from typing import Any


def _start_http_server_and_save_config_noop(*args: object, **kwargs: object) -> None:
    return None


def ensure_http_server_patch_target(http_module: Any | None = None) -> None:
    if http_module is None:
        try:
            from homeassistant.components import http as http_module
        except ImportError:
            return
    if not hasattr(http_module, "start_http_server_and_save_config"):
        http_module.start_http_server_and_save_config = (  # type: ignore[attr-defined]
            _start_http_server_and_save_config_noop
        )


ensure_http_server_patch_target()
