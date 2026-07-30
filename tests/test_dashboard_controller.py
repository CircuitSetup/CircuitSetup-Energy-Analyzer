from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_DASHBOARD_LAYOUT,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    DASHBOARD_LAYOUT_EXPERT,
    DASHBOARD_LAYOUT_STANDARD,
)
from custom_components.circuitsetup_energy_analyzer.dashboard import DASHBOARD_URL_PATH
from custom_components.circuitsetup_energy_analyzer.managers import (
    dashboard_controller,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    SensorRef,
    SensorRole,
)


class _FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object] | None]] = []

    def async_fire(
        self,
        event_type: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        self.events.append((event_type, payload))


class _FakeConfigEntries:
    def __init__(self) -> None:
        self.updated: list[tuple[object, dict[str, object]]] = []

    def async_update_entry(self, entry: object, *, options: dict[str, object]) -> None:
        self.updated.append((entry, options))


class _FakeLovelaceStorage:
    mode = "storage"

    def __init__(self, config: dict[str, object]) -> None:
        self.config = config
        self.saved: list[dict[str, object]] = []
        self.deleted = False

    async def async_save(self, config: dict[str, object]) -> None:
        self.saved.append(config)

    async def async_delete(self) -> None:
        self.deleted = True


class _FakeDashboardCollection:
    def __init__(self, stores: dict[str, _FakeLovelaceStorage]) -> None:
        self.stores = stores
        self.created: list[dict[str, object]] = []
        self.deleted: list[str] = []
        self.updated: list[tuple[str, dict[str, object]]] = []

    async def async_items(self) -> list[dict[str, object]]:
        if DASHBOARD_URL_PATH not in self.stores:
            return []
        return [{"id": DASHBOARD_URL_PATH, "url_path": DASHBOARD_URL_PATH}]

    async def async_create_item(self, data: dict[str, object]) -> dict[str, object]:
        self.created.append(data)
        item = {"id": DASHBOARD_URL_PATH, **data}
        self.stores[DASHBOARD_URL_PATH] = _FakeLovelaceStorage(item)
        return item

    async def async_update_item(
        self,
        item_id: str,
        data: dict[str, object],
    ) -> dict[str, object]:
        self.updated.append((item_id, data))
        return {"id": item_id, "url_path": DASHBOARD_URL_PATH, **data}

    async def async_delete_item(self, item_id: str) -> None:
        self.deleted.append(item_id)
        dashboard_store = self.stores.pop(DASHBOARD_URL_PATH, None)
        if dashboard_store is not None:
            await dashboard_store.async_delete()


class _FakeLovelaceResources:
    loaded = True

    def __init__(self, items: list[dict[str, object]]) -> None:
        self.items = list(items)
        self.created: list[dict[str, object]] = []

    def async_items(self) -> list[dict[str, object]]:
        return list(self.items)

    async def async_create_item(self, data: dict[str, object]) -> None:
        self.created.append(data)


class _StorageDashboardCoordinator:
    def __init__(self) -> None:
        self.entry_id = "entry-1"
        self.dashboard_layout = DASHBOARD_LAYOUT_STANDARD
        self._mains_voltage_entity_ids = frozenset(
            {"sensor.mains_l1_voltage", "sensor.mains_l2_voltage"}
        )
        self.entry_data = {
            CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.outdoor_temperature",
        }
        self.options: dict[str, object] = {}
        self._config_entry = SimpleNamespace(options={})
        self.config_entry_updates: list[dict[str, object]] = []
        self.config_entry_controller = SimpleNamespace(
            async_update_options=self._record_config_entry_update,
        )
        self.store_data = SimpleNamespace(dashboard_status=None)
        self.saved: list[object] = []
        self.dirty_count = 0
        self.store_persistence = SimpleNamespace(
            async_save_if_dirty=self._record_store_save,
            mark_dirty=self._record_store_dirty,
        )
        self.dashboard_stores: dict[str, _FakeLovelaceStorage] = {}
        self.collection = _FakeDashboardCollection(self.dashboard_stores)
        self.hass = SimpleNamespace(
            bus=_FakeBus(),
            config_entries=_FakeConfigEntries(),
            data={
                "lovelace": {
                    "dashboards": self.dashboard_stores,
                    "dashboards_collection": self.collection,
                }
            },
        )
        self.circuit_configs = (
            CircuitConfig(
                circuit_id="fridge",
                name="Kitchen Fridge",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
            ),
        )
        self.state = SimpleNamespace()
        self.last_dashboard_create_request: dict[str, object] | None = None
        self.last_dashboard_remove_request: dict[str, object] | None = None
        self.dashboard_status: dict[str, object] | None = None
        self.updated_data: list[object] = []

    async def _record_config_entry_update(self, updates: dict[str, object]) -> None:
        self.config_entry_updates.append(dict(updates))
        self.options.update(updates)

    def _now_fn(self) -> object:
        return "now"

    async def _record_store_save(self, now: object) -> None:
        self.saved.append(now)

    def _record_store_dirty(self) -> None:
        self.dirty_count += 1

    def async_set_updated_data(self, state: object) -> None:
        self.updated_data.append(state)


@pytest.mark.asyncio
async def test_dashboard_controller_refresh_does_not_create_resource() -> None:
    coordinator = _StorageDashboardCoordinator()
    resources = _FakeLovelaceResources([])
    coordinator.hass.data["lovelace"]["resources"] = resources
    controller = dashboard_controller.DashboardController(coordinator)

    refreshed = await controller.async_refresh_lovelace_resource()

    assert refreshed is True
    assert resources.created == []


@pytest.mark.asyncio
async def test_dashboard_controller_creates_dashboard_and_fires_event() -> None:
    coordinator = _StorageDashboardCoordinator()
    controller = dashboard_controller.DashboardController(coordinator)

    payload = await controller.async_create_dashboard()

    assert payload["action"] == "created"
    assert payload["layout"] == DASHBOARD_LAYOUT_STANDARD
    assert coordinator.collection.created
    assert coordinator.dashboard_stores[DASHBOARD_URL_PATH].saved
    assert coordinator.last_dashboard_create_request == payload
    assert coordinator.store_data.dashboard_status == payload
    assert coordinator.dirty_count == 1
    assert coordinator.saved == ["now"]
    assert (
        "circuitsetup_energy_analyzer_create_dashboard",
        payload,
    ) in coordinator.hass.bus.events
    assert coordinator.updated_data == [coordinator.state]
    cards = coordinator.dashboard_stores[DASHBOARD_URL_PATH].saved[-1]["views"][0][
        "sections"
    ][0]["cards"]
    assert next(card for card in cards if card.get("title") == "Line voltage")[
        "entities"
    ] == [
        {"entity": "sensor.mains_l1_voltage"},
        {"entity": "sensor.mains_l2_voltage"},
    ]


@pytest.mark.asyncio
async def test_dashboard_controller_reuses_runtime_dashboard_when_items_are_stale() -> (
    None
):
    coordinator = _StorageDashboardCoordinator()
    coordinator.dashboard_stores[DASHBOARD_URL_PATH] = _FakeLovelaceStorage(
        {
            "id": "circuitsetup_energy_analyzer",
            "url_path": DASHBOARD_URL_PATH,
            "title": "CircuitSetup Energy Analyzer",
        }
    )
    coordinator.collection.async_items = lambda: []
    controller = dashboard_controller.DashboardController(coordinator)

    payload = await controller.async_create_dashboard()

    assert payload["action"] == "updated"
    assert coordinator.collection.created == []
    assert coordinator.collection.updated == []
    assert coordinator.dashboard_stores[DASHBOARD_URL_PATH].saved


@pytest.mark.asyncio
async def test_dashboard_controller_owns_lovelace_create_and_remove() -> None:
    coordinator = _StorageDashboardCoordinator()
    controller = dashboard_controller.DashboardController(coordinator)

    created = await controller.async_create_dashboard()

    assert created["action"] == "created"
    assert coordinator.collection.created[0]["url_path"] == DASHBOARD_URL_PATH
    dashboard_store = coordinator.dashboard_stores[DASHBOARD_URL_PATH]
    assert dashboard_store.saved
    assert dashboard_store.saved[0]["views"]

    removed = await controller.async_remove_dashboard()

    assert removed["action"] == "deleted"
    assert coordinator.collection.deleted == [DASHBOARD_URL_PATH]
    assert DASHBOARD_URL_PATH not in coordinator.dashboard_stores


@pytest.mark.asyncio
async def test_dashboard_controller_removes_dashboard_and_persists_layout() -> None:
    coordinator = _StorageDashboardCoordinator()
    coordinator.dashboard_stores[DASHBOARD_URL_PATH] = _FakeLovelaceStorage(
        {"url_path": DASHBOARD_URL_PATH}
    )
    controller = dashboard_controller.DashboardController(coordinator)

    removed = await controller.async_remove_dashboard()
    await controller.async_set_dashboard_layout(DASHBOARD_LAYOUT_EXPERT)

    assert removed["action"] == "deleted"
    assert coordinator.last_dashboard_remove_request == removed
    assert coordinator.dashboard_layout == DASHBOARD_LAYOUT_EXPERT
    assert coordinator.options[CONF_DASHBOARD_LAYOUT] == DASHBOARD_LAYOUT_EXPERT
    assert coordinator.config_entry_updates == [
        {CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_EXPERT}
    ]
    assert coordinator.hass.config_entries.updated == []
