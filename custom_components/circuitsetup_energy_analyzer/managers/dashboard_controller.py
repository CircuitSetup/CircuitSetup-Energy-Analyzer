"""Dashboard orchestration extracted from the coordinator facade."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from inspect import isawaitable
from typing import Any

from ..const import CONF_DASHBOARD_LAYOUT, DOMAIN
from ..dashboard import (
    DASHBOARD_TITLE,
    DASHBOARD_URL_PATH,
    NILM_DASHBOARD_GRAPHS_CARD,
    dashboard_graph_module_resource,
    dashboard_includes_nilm_graph_card,
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
        action, reason = await self.async_create_or_update_lovelace_dashboard(
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
        action, reason = await self.async_remove_lovelace_dashboard()
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

    async def async_create_or_update_lovelace_dashboard(
        self,
        payload: Mapping[str, Any],
    ) -> tuple[str, str | None]:
        """Create or update the backing Lovelace dashboard storage item."""
        lovelace_data = _lovelace_data_from_hass(self._coordinator.hass)
        collection = _lovelace_dashboard_item_value(
            lovelace_data,
            "dashboards_collection",
        )
        if collection is None and _lovelace_dashboards(lovelace_data) is not None:
            collection = await _async_load_lovelace_dashboards_collection(
                self._coordinator.hass,
                lovelace_data,
            )
        if collection is None:
            return "unavailable", "lovelace_dashboard_collection_unavailable"

        items_method = getattr(collection, "async_items", None)
        create_method = getattr(collection, "async_create_item", None)
        update_method = getattr(collection, "async_update_item", None)
        if not callable(items_method) or not callable(create_method):
            return "unavailable", "lovelace_dashboard_collection_unavailable"

        items = await _async_lovelace_method_result(items_method())
        dashboard_config = _lovelace_dashboard_config(payload)
        storage_payload = _lovelace_dashboard_storage_payload(payload)
        existing = next(
            (
                item
                for item in items
                if _lovelace_dashboard_matches(item, payload)
            ),
            None,
        )
        if existing is not None:
            if not callable(update_method):
                return "unavailable", "dashboard_update_unavailable"
            item_id = _lovelace_dashboard_item_id(existing, payload)
            allowed_update_keys = {
                "icon",
                "require_admin",
                "show_in_sidebar",
                "title",
            }
            update_payload = {
                key: value
                for key, value in storage_payload.items()
                if key in allowed_update_keys
            }
            updated_item = await _async_lovelace_method_result(
                update_method(item_id, update_payload)
            )
            item = {
                **_lovelace_dashboard_item_mapping(existing),
                **(dict(updated_item) if isinstance(updated_item, Mapping) else {}),
                **update_payload,
            }
            if not await _async_save_lovelace_dashboard_config(
                self._coordinator.hass,
                lovelace_data,
                item,
                dashboard_config,
                update=True,
            ):
                return "unavailable", "dashboard_config_save_unavailable"
            return "updated", None

        created_item = await _async_lovelace_method_result(
            create_method(dict(storage_payload))
        )
        item = created_item if isinstance(created_item, Mapping) else storage_payload
        if not await _async_save_lovelace_dashboard_config(
            self._coordinator.hass,
            lovelace_data,
            item,
            dashboard_config,
            update=False,
        ):
            return "unavailable", "dashboard_config_save_unavailable"
        return "created", None

    async def async_remove_lovelace_dashboard(self) -> tuple[str, str | None]:
        """Remove the backing Lovelace dashboard storage item."""
        lovelace_data = _lovelace_data_from_hass(self._coordinator.hass)
        collection = _lovelace_dashboard_item_value(
            lovelace_data,
            "dashboards_collection",
        )
        if collection is None and _lovelace_dashboards(lovelace_data) is not None:
            collection = await _async_load_lovelace_dashboards_collection(
                self._coordinator.hass,
                lovelace_data,
            )

        payload = {"url_path": DASHBOARD_URL_PATH}
        if collection is not None:
            items_method = getattr(collection, "async_items", None)
            delete_method = getattr(collection, "async_delete_item", None)
            if not callable(items_method) or not callable(delete_method):
                return "unavailable", "lovelace_dashboard_delete_unavailable"

            items = await _async_lovelace_method_result(items_method())
            existing = next(
                (
                    item
                    for item in items
                    if _lovelace_dashboard_matches(item, payload)
                ),
                None,
            )
            if existing is None:
                if await _async_delete_lovelace_dashboard_config(
                    self._coordinator.hass,
                    lovelace_data,
                    DASHBOARD_URL_PATH,
                ):
                    return "deleted", None
                return "missing", None

            item_id = _lovelace_dashboard_item_id(existing, payload)
            if not item_id:
                return "unavailable", "lovelace_dashboard_delete_unavailable"
            await _async_lovelace_method_result(delete_method(item_id))
            await _async_delete_lovelace_dashboard_config(
                self._coordinator.hass,
                lovelace_data,
                DASHBOARD_URL_PATH,
            )
            return "deleted", None

        if await _async_delete_lovelace_dashboard_config(
            self._coordinator.hass,
            lovelace_data,
            DASHBOARD_URL_PATH,
        ):
            return "deleted", None
        return "missing", None


def _lovelace_dashboard_matches(item: Any, payload: Mapping[str, Any]) -> bool:
    target = _normalize_lovelace_path(payload.get("url_path"))
    if not target:
        return False
    return any(
        _normalize_lovelace_path(_lovelace_dashboard_item_value(item, key)) == target
        for key in ("url_path", "id")
    )


def _lovelace_data_from_hass(hass: Any) -> Any:
    hass_data = getattr(hass, "data", {})
    if isinstance(hass_data, Mapping):
        return hass_data.get("lovelace", {})
    return getattr(hass_data, "lovelace", {})


async def _async_load_lovelace_dashboards_collection(
    hass: Any,
    lovelace_data: Any,
) -> Any | None:
    del lovelace_data
    try:
        from homeassistant.components.lovelace import dashboard as lovelace_dashboard
    except ImportError:
        return None

    collection = lovelace_dashboard.DashboardsCollection(hass)
    async_load = getattr(collection, "async_load", None)
    if callable(async_load):
        await _async_lovelace_method_result(async_load())
    return collection


def _lovelace_dashboards(lovelace_data: Any) -> MutableMapping[Any, Any] | None:
    dashboards = _lovelace_dashboard_item_value(lovelace_data, "dashboards")
    return dashboards if isinstance(dashboards, MutableMapping) else None


def _lovelace_dashboard_storage_payload(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "config"}


def _lovelace_dashboard_config(payload: Mapping[str, Any]) -> dict[str, Any]:
    config = payload.get("config")
    return dict(config) if isinstance(config, Mapping) else {}


async def _async_save_lovelace_dashboard_config(
    hass: Any,
    lovelace_data: Any,
    item: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    update: bool,
) -> bool:
    dashboards = _lovelace_dashboards(lovelace_data)
    if dashboards is None:
        return False

    url_path = _normalize_lovelace_path(
        _lovelace_dashboard_item_value(item, "url_path")
    )
    if not url_path:
        return False

    dashboard_store = dashboards.get(url_path)
    if dashboard_store is None:
        dashboard_store = _new_lovelace_storage(hass, item)
        if dashboard_store is None:
            return False
        dashboards[url_path] = dashboard_store

    if hasattr(dashboard_store, "config"):
        dashboard_store.config = dict(item)

    save = getattr(dashboard_store, "async_save", None)
    if not callable(save):
        return False
    save_config = dict(config)
    if not await _async_ensure_lovelace_dashboard_graph_resource(
        lovelace_data,
        save_config,
    ):
        save_config = _lovelace_config_without_card_type(
            save_config,
            NILM_DASHBOARD_GRAPHS_CARD,
        )
    await _async_lovelace_method_result(save(save_config))
    _register_lovelace_dashboard_panel(hass, item, update=update)
    return True


async def _async_ensure_lovelace_dashboard_graph_resource(
    lovelace_data: Any,
    config: Mapping[str, Any],
) -> bool:
    if not dashboard_includes_nilm_graph_card(config):
        return True

    resources = _lovelace_dashboard_item_value(lovelace_data, "resources")
    if resources is None:
        return False

    async_load = getattr(resources, "async_load", None)
    if callable(async_load) and not getattr(resources, "loaded", True):
        await _async_lovelace_method_result(async_load())
        if hasattr(resources, "loaded"):
            resources.loaded = True

    items_method = getattr(resources, "async_items", None)
    if not callable(items_method):
        return False

    resource = dashboard_graph_module_resource()
    items = await _async_lovelace_method_result(items_method())
    existing = next(
        (
            item
            for item in items
            if _lovelace_resource_matches_static_url(item, resource)
        ),
        None,
    )
    resource_payload = _lovelace_resource_update_payload(resource)
    if existing is None:
        create_method = getattr(resources, "async_create_item", None)
        if not callable(create_method):
            return False
        await _async_lovelace_method_result(create_method(resource_payload))
        return True

    if _lovelace_resource_has_current_values(existing, resource):
        return True

    update_method = getattr(resources, "async_update_item", None)
    item_id = _lovelace_dashboard_item_value(existing, "id")
    if callable(update_method) and item_id:
        await _async_lovelace_method_result(
            update_method(str(item_id), resource_payload)
        )
        return True
    return False


def _lovelace_config_without_card_type(
    config: Mapping[str, Any],
    card_type: str,
) -> dict[str, Any]:
    remove = object()

    def clean(value: Any) -> Any:
        if isinstance(value, Mapping):
            if value.get("type") == card_type:
                return remove
            cleaned: dict[str, Any] = {}
            for key, nested in value.items():
                cleaned_value = clean(nested)
                if cleaned_value is not remove:
                    cleaned[key] = cleaned_value
            return cleaned
        if isinstance(value, list):
            return [
                cleaned_value
                for item in value
                if (cleaned_value := clean(item)) is not remove
            ]
        return value

    cleaned_config = clean(config)
    return cleaned_config if isinstance(cleaned_config, dict) else dict(config)


def _lovelace_resource_update_payload(
    resource: Mapping[str, str],
) -> dict[str, str]:
    return {
        "res_type": resource["type"],
        "url": resource["url"],
    }


def _lovelace_resource_matches_static_url(
    item: Any,
    resource: Mapping[str, str],
) -> bool:
    return _lovelace_resource_static_url(
        _lovelace_dashboard_item_value(item, "url")
    ) == _lovelace_resource_static_url(resource.get("url"))


def _lovelace_resource_has_current_values(
    item: Any,
    resource: Mapping[str, str],
) -> bool:
    item_type = (
        _lovelace_dashboard_item_value(item, "type")
        or _lovelace_dashboard_item_value(item, "res_type")
    )
    return (
        str(item_type or "") == resource["type"]
        and str(_lovelace_dashboard_item_value(item, "url") or "") == resource["url"]
    )


def _lovelace_resource_static_url(value: Any) -> str:
    return str(value or "").strip().split("?", 1)[0]


async def _async_delete_lovelace_dashboard_config(
    hass: Any,
    lovelace_data: Any,
    url_path: str,
) -> bool:
    dashboards = _lovelace_dashboards(lovelace_data)
    if dashboards is None:
        return False

    dashboard_store = dashboards.get(url_path)
    if dashboard_store is None:
        return False

    dashboard_mode = getattr(dashboard_store, "mode", None)
    if callable(dashboard_mode):
        dashboard_mode = dashboard_mode()
    if str(dashboard_mode or "").strip().lower() != "storage":
        return False

    dashboard_store = dashboards.pop(url_path, None)
    if dashboard_store is None:
        return False

    try:
        from homeassistant.components import frontend
    except ImportError:
        frontend = None

    remove_panel = getattr(frontend, "async_remove_panel", None)
    if callable(remove_panel):
        remove_panel(hass, url_path)

    delete = getattr(dashboard_store, "async_delete", None)
    if callable(delete):
        await _async_lovelace_method_result(delete())
    return True


async def _async_lovelace_method_result(result: Any) -> Any:
    if isawaitable(result):
        return await result
    return result


def _new_lovelace_storage(hass: Any, item: Mapping[str, Any]) -> Any | None:
    try:
        from homeassistant.components.lovelace import dashboard as lovelace_dashboard
    except ImportError:
        return None
    return lovelace_dashboard.LovelaceStorage(hass, dict(item))


def _register_lovelace_dashboard_panel(
    hass: Any,
    item: Mapping[str, Any],
    *,
    update: bool,
) -> None:
    try:
        from homeassistant.components import frontend
        from homeassistant.components.lovelace.const import (
            CONF_ICON,
            CONF_REQUIRE_ADMIN,
            CONF_SHOW_IN_SIDEBAR,
            CONF_TITLE,
            CONF_URL_PATH,
            DEFAULT_ICON,
            MODE_STORAGE,
        )
        from homeassistant.components.lovelace.const import (
            DOMAIN as LOVELACE_DOMAIN,
        )
    except ImportError:
        return

    try:
        panel_kwargs = {
            "frontend_url_path": item.get(CONF_URL_PATH),
            "require_admin": item[CONF_REQUIRE_ADMIN],
            "show_in_sidebar": item[CONF_SHOW_IN_SIDEBAR],
            "sidebar_title": item[CONF_TITLE],
            "sidebar_icon": item.get(CONF_ICON, DEFAULT_ICON),
            "config": {"mode": MODE_STORAGE},
            "update": update,
        }
        try:
            frontend.async_register_built_in_panel(
                hass,
                LOVELACE_DOMAIN,
                **panel_kwargs,
            )
        except TypeError as err:
            if "show_in_sidebar" not in str(err):
                raise
            panel_kwargs.pop("show_in_sidebar", None)
            frontend.async_register_built_in_panel(
                hass,
                LOVELACE_DOMAIN,
                **panel_kwargs,
            )
    except (AttributeError, KeyError, ValueError):
        return


def _lovelace_dashboard_item_id(
    item: Any,
    payload: Mapping[str, Any],
) -> str:
    return str(
        _lovelace_dashboard_item_value(item, "id")
        or _lovelace_dashboard_item_value(item, "url_path")
        or payload.get("url_path")
        or ""
    )


def _lovelace_dashboard_item_mapping(item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping):
        return dict(item)
    return {
        key: value
        for key in ("id", "url_path", "mode", "title", "icon", "show_in_sidebar")
        if (value := getattr(item, key, None)) is not None
    }


def _lovelace_dashboard_item_value(item: Any, key: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(key)
    return getattr(item, key, None)


def _normalize_lovelace_path(value: Any) -> str:
    return str(value or "").strip().removeprefix("/")
