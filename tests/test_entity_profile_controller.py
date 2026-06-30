from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_ENTITY_DETAIL_LEVEL,
    ENTITY_DETAIL_EXPERT,
)
from custom_components.circuitsetup_energy_analyzer.managers import (
    entity_profile_controller,
)


class _EntityProfileCoordinator:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}
        self.state = SimpleNamespace()
        self.persisted = 0
        self.reloaded = 0
        self.updated: list[object] = []

    async def _async_persist_config_entry_options(self) -> None:
        self.persisted += 1

    def async_set_updated_data(self, state: object) -> None:
        self.updated.append(state)

    async def _async_reload_config_entry(self) -> None:
        self.reloaded += 1


@pytest.mark.asyncio
async def test_entity_profile_controller_sets_detail_level_and_reloads() -> None:
    coordinator = _EntityProfileCoordinator()
    controller = entity_profile_controller.EntityProfileController(coordinator)

    await controller.async_set_entity_detail_level(ENTITY_DETAIL_EXPERT)

    assert coordinator.options[CONF_ENTITY_DETAIL_LEVEL] == ENTITY_DETAIL_EXPERT
    assert coordinator.persisted == 1
    assert coordinator.updated == [coordinator.state]
    assert coordinator.reloaded == 1
