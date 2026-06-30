"""Dashboard orchestration extracted from the coordinator facade."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..const import CONF_DASHBOARD_LAYOUT, DOMAIN
from ..dashboard import (
    DASHBOARD_TITLE,
    DASHBOARD_URL_PATH,
    dashboard_storage_payload,
    normalize_dashboard_layout,
)


class DashboardController:
    """Own recommended-dashboard create, remove, and layout workflows."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    async def async_create_dashboard(self) -> dict[str, Any]:
        """Create or update the recommended Home Assistant dashboard."""
        coordinator = self._coordinator
        layout = normalize_dashboard_layout(coordinator.dashboard_layout)
        dashboard_payload = dashboard_storage_payload(
            coordinator.circuit_configs,
            layout,
            hass=coordinator.hass,
            entry_id=coordinator.entry_id,
            outdoor_temperature_entity=coordinator._outdoor_temperature_entity(),
        )
        action, reason = await coordinator._async_create_or_update_lovelace_dashboard(
            dashboard_payload,
        )
        payload = {
            "entry_id": coordinator.entry_id,
            "dashboard_path": f"/{DASHBOARD_URL_PATH}",
            "title": DASHBOARD_TITLE,
            "layout": layout,
            "action": action,
        }
        if reason is not None:
            payload["reason"] = reason
        coordinator.last_dashboard_create_request = payload
        coordinator.dashboard_status = dict(payload)
        store_data = getattr(coordinator, "store_data", None)
        if store_data is not None:
            store_data.dashboard_status = dict(payload)
            mark_store_dirty = getattr(coordinator, "_mark_store_dirty", None)
            save_store = getattr(coordinator, "_async_save_store", None)
            now_fn = getattr(coordinator, "_now_fn", None)
            if callable(mark_store_dirty) and callable(save_store) and callable(now_fn):
                mark_store_dirty()
                await save_store(now_fn())
        self._fire_event(f"{DOMAIN}_create_dashboard", payload)
        coordinator.async_set_updated_data(coordinator.state)
        return payload

    async def async_remove_dashboard(self) -> dict[str, Any]:
        """Remove the recommended Home Assistant dashboard."""
        coordinator = self._coordinator
        action, reason = await coordinator._async_remove_lovelace_dashboard()
        payload = {
            "entry_id": coordinator.entry_id,
            "dashboard_path": f"/{DASHBOARD_URL_PATH}",
            "title": DASHBOARD_TITLE,
            "action": action,
        }
        if reason is not None:
            payload["reason"] = reason
        coordinator.last_dashboard_remove_request = payload
        self._fire_event(f"{DOMAIN}_remove_dashboard", payload)
        coordinator.async_set_updated_data(coordinator.state)
        return payload

    async def async_set_dashboard_layout(self, layout: str) -> None:
        """Persist the selected recommended-dashboard layout."""
        coordinator = self._coordinator
        normalized = normalize_dashboard_layout(layout)
        coordinator.dashboard_layout = normalized
        coordinator.options[CONF_DASHBOARD_LAYOUT] = normalized
        entry = coordinator._config_entry
        if entry is not None:
            options = dict(getattr(entry, "options", {}) or {})
            options[CONF_DASHBOARD_LAYOUT] = normalized
            update_entry = getattr(
                getattr(coordinator.hass, "config_entries", None),
                "async_update_entry",
                None,
            )
            if callable(update_entry):
                update_entry(entry, options=options)
        coordinator.async_set_updated_data(coordinator.state)

    def _fire_event(self, event_type: str, payload: Mapping[str, Any]) -> None:
        bus = getattr(self._coordinator.hass, "bus", None)
        fire = getattr(bus, "async_fire", None)
        if fire is not None:
            fire(event_type, dict(payload))
