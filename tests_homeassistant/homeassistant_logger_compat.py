from __future__ import annotations

from typing import Any


def ensure_logger_patch_target(logger_module: Any | None = None) -> None:
    """Expose HA's relocated logger cleanup for the pinned pytest plugin."""
    if logger_module is None:
        from homeassistant.components import logger as logger_module
    if hasattr(logger_module, "_clear_logger_overwrites"):
        return
    try:
        from homeassistant.components.logger.helpers import _clear_logger_overwrites
    except ImportError:
        return

    logger_module._clear_logger_overwrites = _clear_logger_overwrites


ensure_logger_patch_target()
