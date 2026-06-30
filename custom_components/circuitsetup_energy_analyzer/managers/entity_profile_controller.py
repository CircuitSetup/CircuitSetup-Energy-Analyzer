"""Entity profile orchestration for compact analyzer entities."""

from __future__ import annotations

from typing import Any

from ..const import CONF_ENTITY_DETAIL_LEVEL


class EntityProfileController:
    """Own entity-detail profile changes and reload requests."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    async def async_set_entity_detail_level(self, detail_level: str) -> None:
        """Persist the entity detail level and reload desired entities."""
        from ..entity import normalize_entity_detail_level

        coordinator = self._coordinator
        level = normalize_entity_detail_level(detail_level)
        coordinator.options[CONF_ENTITY_DETAIL_LEVEL] = level
        await coordinator._async_persist_config_entry_options()
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator._async_reload_config_entry()
