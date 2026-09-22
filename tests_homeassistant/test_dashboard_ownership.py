"""Protect dashboards created outside this integration."""

from typing import Any

import pytest
from homeassistant.helpers.storage import Store
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
from custom_components.circuitsetup_energy_analyzer.dashboard import DASHBOARD_URL_PATH
from tests_homeassistant.test_lifecycle_gate import _point_custom_components_at_worktree


@pytest.mark.usefixtures("enable_custom_integrations", "socket_enabled")
@pytest.mark.asyncio
async def test_user_dashboard_at_reserved_path_is_preserved(
    hass: Any, monkeypatch: pytest.MonkeyPatch, unused_tcp_port: int
) -> None:
    _point_custom_components_at_worktree(monkeypatch)
    assert await async_setup_component(
        hass, "http", {"http": {"server_port": unused_tcp_port}}
    )
    assert await async_setup_component(hass, "frontend", {})
    collection = hass.data["lovelace"]["dashboards_collection"]
    assert not [
        item
        for item in collection.async_items()
        if item["url_path"] == DASHBOARD_URL_PATH
    ]

    user_item = await collection.async_create_item(
        {
            "url_path": DASHBOARD_URL_PATH,
            "mode": "storage",
            "title": "My personal dashboard",
            "show_in_sidebar": True,
        }
    )
    await collection.store._async_callback_delayed_write()
    assert any(
        row["title"] == "My personal dashboard"
        for row in (await Store(hass, 1, "lovelace_dashboards").async_load())["items"]
        if row["id"] == user_item["id"]
    )
    dashboard = hass.data["lovelace"]["dashboards"][DASHBOARD_URL_PATH]
    original_views = [
        {"title": "Personal", "cards": [{"type": "markdown", "content": "Keep me"}]}
    ]
    await dashboard.async_save({"views": original_views})
    assert (await dashboard.async_load(False))["views"] == original_views
    dashboard_storage_key = f"lovelace.{user_item['id']}"
    assert (await Store(hass, 1, dashboard_storage_key).async_load())["config"][
        "views"
    ] == original_views

    hass.states.async_set(
        "sensor.fridge_power",
        "84",
        {"unit_of_measurement": "W", "device_class": "power"},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="audit-dashboard-collision",
        title="Audit Collision",
        data={
            "source_entities": ["sensor.fridge_power"],
            "circuits": [
                {
                    "circuit_id": "fridge",
                    "name": "Kitchen Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"}
                    ],
                }
            ],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][entry.entry_id]

    created = await coordinator.async_create_dashboard()
    updated_item = next(
        item for item in collection.async_items() if item["id"] == user_item["id"]
    )
    retained = await hass.data["lovelace"]["dashboards"][DASHBOARD_URL_PATH].async_load(
        False
    )
    assert created["action"] == "unavailable"
    assert created["reason"] == "dashboard_not_owned"
    assert updated_item["title"] == "My personal dashboard"
    assert retained["views"] == original_views
    assert (await Store(hass, 1, dashboard_storage_key).async_load())["config"][
        "views"
    ] == original_views
    await collection.store._async_callback_delayed_write()
    saved_collection = await Store(hass, 1, "lovelace_dashboards").async_load()
    assert any(
        row["title"] == "My personal dashboard"
        for row in saved_collection["items"]
        if row["id"] == user_item["id"]
    )

    removed = await coordinator.async_remove_dashboard()
    assert removed["action"] == "unavailable"
    assert removed["reason"] == "dashboard_not_owned"
    assert [
        item
        for item in collection.async_items()
        if item["url_path"] == DASHBOARD_URL_PATH
    ]
    assert DASHBOARD_URL_PATH in hass.data["lovelace"]["dashboards"]
    assert (await Store(hass, 1, dashboard_storage_key).async_load())["config"][
        "views"
    ] == original_views
    await collection.store._async_callback_delayed_write()
    assert any(
        row["title"] == "My personal dashboard"
        for row in (await Store(hass, 1, "lovelace_dashboards").async_load())["items"]
        if row["id"] == user_item["id"]
    )
