from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from types import SimpleNamespace
from typing import Any

try:
    import voluptuous as vol
except ModuleNotFoundError:

    class _Schema:
        def __init__(self, schema: Mapping[Any, Any]) -> None:
            self.schema = schema

        def __call__(self, value: Any) -> Any:
            return value

    class _Marker:
        def __init__(self, key: str, default: Any = None) -> None:
            self.key = key
            self.default = default

        def __hash__(self) -> int:
            return hash((self.key, self.default))

        def __eq__(self, other: object) -> bool:
            return (
                isinstance(other, _Marker)
                and self.key == other.key
                and self.default == other.default
            )

    class _VoluptuousFallback:
        Schema = _Schema

        @staticmethod
        def Required(key: str, default: Any = None) -> _Marker:
            return _Marker(key, default)

        @staticmethod
        def Optional(key: str, default: Any = None) -> _Marker:
            return _Marker(key, default)

    vol = _VoluptuousFallback()

try:
    from homeassistant import config_entries
    from homeassistant.core import callback
    from homeassistant.helpers.selector import selector as ha_selector
except ModuleNotFoundError:

    def callback(func: Any) -> Any:
        return func

    class _ConfigFlow:
        def __init_subclass__(cls, **kwargs: Any) -> None:
            super().__init_subclass__()

        def async_create_entry(
            self,
            *,
            title: str,
            data: dict[str, Any],
        ) -> dict[str, Any]:
            return {"type": "create_entry", "title": title, "data": data}

        def async_show_form(
            self,
            *,
            step_id: str,
            data_schema: Any,
            errors: dict[str, str] | None = None,
            description_placeholders: dict[str, str] | None = None,
        ) -> dict[str, Any]:
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
                "description_placeholders": description_placeholders or {},
            }

    class _OptionsFlow(_ConfigFlow):
        pass

    config_entries = SimpleNamespace(
        ConfigEntry=Any,
        ConfigFlow=_ConfigFlow,
        ConfigFlowResult=dict[str, Any],
        OptionsFlow=_OptionsFlow,
        OptionsFlowWithReload=_OptionsFlow,
    )
    ha_selector = None

from .const import (
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_RETENTION_MODE,
    CONF_SENSITIVITY,
    CONF_SOURCE_ENTITIES,
    DEFAULT_ENABLE_EXPERIMENTAL_NILM,
    DEFAULT_RETENTION_MODE,
    DEFAULT_SENSITIVITY,
    DOMAIN,
)
from .discovery import (
    ENERGY_SOURCE_DEVICE_CLASSES,
    async_discover_energy_source_entities,
    async_discover_sensors,
)
from .mapping import DualPhaseSuggestion, suggest_dual_phase_pairs
from .models import RetentionMode

TITLE = "CircuitSetup Energy Analyzer"
ERROR_NO_SOURCE_ENTITIES = "no_source_entities"
ERROR_INVALID_SOURCE_ENTITIES = "invalid_source_entities"
_VALID_RETENTION_MODES = {mode.value for mode in RetentionMode}
_SENSITIVITY_OPTIONS = ("standard", "high", "low")
_OPTIONS_FLOW_BASE = getattr(
    config_entries,
    "OptionsFlowWithReload",
    config_entries.OptionsFlow,
)


class SetupValidationError(ValueError):
    """Setup validation error with a Home Assistant translation key."""

    def __init__(self, error_key: str) -> None:
        super().__init__(error_key)
        self.error_key = error_key


def format_mapping_suggestions(suggestions: Iterable[DualPhaseSuggestion]) -> str:
    """Format auto-suggested dual-phase mappings for user confirmation."""
    suggestion_list = list(suggestions)
    if not suggestion_list:
        return (
            "No dual-phase mapping suggestions were found yet. Continue with "
            "source sensors; the analyzer can still learn from selected inputs."
        )

    lines = [
        "Suggested dual-phase channel pairs are listed below. Review each pair, "
        "then confirm or manually override the mapping before saving. You can "
        "accept, edit, mark as mixed, or exclude each suggested circuit. "
        "Confidence may use naming, phase pairing, correlated changes, "
        "required metric availability, and optional metric availability."
    ]
    for suggestion in suggestion_list:
        reasons = ", ".join(suggestion.reasons) if suggestion.reasons else "no reasons"
        lines.append(
            f"- {suggestion.left.name} ({suggestion.left.entity_id}) + "
            f"{suggestion.right.name} ({suggestion.right.entity_id}): "
            f"{suggestion.confidence:.0%} confidence; reasons: {reasons}."
        )
    return "\n".join(lines)


def validate_setup_input(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize setup data without requiring Home Assistant."""
    source_entities = _strict_string_list(
        user_input.get(CONF_SOURCE_ENTITIES),
        invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
    )
    if not source_entities:
        raise SetupValidationError(ERROR_NO_SOURCE_ENTITIES)

    retention_mode = _validate_retention_mode(user_input)

    return {
        CONF_SOURCE_ENTITIES: source_entities,
        CONF_ENABLE_EXPERIMENTAL_NILM: bool(
            user_input.get(
                CONF_ENABLE_EXPERIMENTAL_NILM,
                DEFAULT_ENABLE_EXPERIMENTAL_NILM,
            )
        ),
        CONF_MAINS_SOURCE_ENTITIES: _strict_string_list(
            user_input.get(CONF_MAINS_SOURCE_ENTITIES, []),
            invalid_error_key="invalid_mains_source_entities",
        ),
        CONF_SENSITIVITY: str(user_input.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY)),
        CONF_RETENTION_MODE: retention_mode,
    }


def validate_options_input(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize options flow data without requiring Home Assistant."""
    validated = {
        CONF_ENABLE_EXPERIMENTAL_NILM: bool(
            user_input.get(
                CONF_ENABLE_EXPERIMENTAL_NILM,
                DEFAULT_ENABLE_EXPERIMENTAL_NILM,
            )
        ),
        CONF_MAINS_SOURCE_ENTITIES: _strict_string_list(
            user_input.get(CONF_MAINS_SOURCE_ENTITIES, []),
            invalid_error_key="invalid_mains_source_entities",
        ),
        CONF_SENSITIVITY: str(user_input.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY)),
        CONF_RETENTION_MODE: _validate_retention_mode(user_input),
    }
    if CONF_SOURCE_ENTITIES in user_input:
        source_entities = _strict_string_list(
            user_input.get(CONF_SOURCE_ENTITIES),
            invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
        )
        if not source_entities:
            raise SetupValidationError(ERROR_NO_SOURCE_ENTITIES)
        validated[CONF_SOURCE_ENTITIES] = source_entities
    return validated


def _strict_string_list(value: Any, *, invalid_error_key: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items: list[str] = []
        for raw_item in re.split(r"[\n,]+", value):
            item = raw_item.strip()
            if item:
                items.append(item)
        return items
    if isinstance(value, Mapping) or not isinstance(value, (list, tuple, set)):
        raise SetupValidationError(invalid_error_key)

    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise SetupValidationError(invalid_error_key)
        if item:
            items.append(item)
    return items


def _validate_retention_mode(user_input: Mapping[str, Any]) -> str:
    retention_mode = str(user_input.get(CONF_RETENTION_MODE, DEFAULT_RETENTION_MODE))
    if retention_mode not in _VALID_RETENTION_MODES:
        raise SetupValidationError("invalid_retention_mode")
    return retention_mode


def _selector(config: dict[str, Any], fallback: Any) -> Any:
    if ha_selector is None:
        return fallback
    return ha_selector(config)


def _energy_entity_selector_config(
    include_entities: Iterable[str] | None = None,
) -> dict[str, Any]:
    entity_ids = list(dict.fromkeys(include_entities or ()))
    config: dict[str, Any] = {
        "entity": {
            "multiple": True,
            "filter": [
                {
                    "domain": "sensor",
                    "device_class": sorted(ENERGY_SOURCE_DEVICE_CLASSES),
                }
            ],
        }
    }
    if entity_ids:
        config["entity"]["include_entities"] = entity_ids

    return config


def _energy_entity_list_selector(
    include_entities: Iterable[str] | None = None,
) -> Any:
    return _selector(_energy_entity_selector_config(include_entities), str)


def _select_selector(options: Iterable[str]) -> Any:
    return _selector({"select": {"options": list(options)}}, vol.In(tuple(options)))


def _setup_schema(source_entity_ids: Iterable[str] | None = None) -> Any:
    del source_entity_ids
    return vol.Schema(
        {
            vol.Required(CONF_SOURCE_ENTITIES): _energy_entity_list_selector(),
            vol.Optional(
                CONF_ENABLE_EXPERIMENTAL_NILM,
                default=DEFAULT_ENABLE_EXPERIMENTAL_NILM,
            ): bool,
            vol.Optional(
                CONF_MAINS_SOURCE_ENTITIES,
                default=[],
            ): _energy_entity_list_selector(),
            vol.Optional(
                CONF_SENSITIVITY,
                default=DEFAULT_SENSITIVITY,
            ): _select_selector(_SENSITIVITY_OPTIONS),
            vol.Optional(
                CONF_RETENTION_MODE,
                default=DEFAULT_RETENTION_MODE,
            ): _select_selector(sorted(_VALID_RETENTION_MODES)),
        }
    )


DATA_SCHEMA = _setup_schema()


class CircuitSetupEnergyAnalyzerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for CircuitSetup Energy Analyzer."""

    VERSION = 1
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> CircuitSetupEnergyAnalyzerOptionsFlow:
        """Create the options flow."""
        return CircuitSetupEnergyAnalyzerOptionsFlow(config_entry)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle user setup."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                validated = validate_setup_input(user_input)
            except SetupValidationError as err:
                errors["base"] = err.error_key
            else:
                return self.async_create_entry(title=TITLE, data=validated)

        return self.async_show_form(
            step_id="user",
            data_schema=_setup_schema(
                await _async_discover_energy_source_entities(
                    getattr(self, "hass", None),
                )
            ),
            errors=errors,
        )


class CircuitSetupEnergyAnalyzerOptionsFlow(_OPTIONS_FLOW_BASE):
    """Options flow for CircuitSetup Energy Analyzer."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            try:
                validated = validate_options_input(user_input)
            except SetupValidationError as err:
                return await self._async_show_options_form({"base": err.error_key})
            return self.async_create_entry(title="", data=validated)

        return await self._async_show_options_form()

    async def _async_show_options_form(
        self,
        errors: dict[str, str] | None = None,
    ) -> config_entries.ConfigFlowResult:
        source_entity_ids = await _async_discover_energy_source_entities(
            getattr(self, "hass", None),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(self._config_entry, source_entity_ids),
            errors=errors or {},
        )


def _options_schema(
    config_entry: config_entries.ConfigEntry,
    source_entity_ids: Iterable[str] | None = None,
) -> Any:
    options = getattr(config_entry, "options", {}) or {}
    data = getattr(config_entry, "data", {}) or {}
    source_entities = options.get(
        CONF_SOURCE_ENTITIES,
        data.get(CONF_SOURCE_ENTITIES, []),
    )
    mains_source_entities = options.get(
        CONF_MAINS_SOURCE_ENTITIES,
        data.get(CONF_MAINS_SOURCE_ENTITIES, []),
    )
    selectable_source_entities = [
        *list(source_entity_ids or ()),
        *_strict_string_list(
            source_entities,
            invalid_error_key=ERROR_INVALID_SOURCE_ENTITIES,
        ),
        *_strict_string_list(
            mains_source_entities,
            invalid_error_key="invalid_mains_source_entities",
        ),
    ]
    return vol.Schema(
        {
            vol.Optional(
                CONF_ENABLE_EXPERIMENTAL_NILM,
                default=options.get(
                    CONF_ENABLE_EXPERIMENTAL_NILM,
                    data.get(
                        CONF_ENABLE_EXPERIMENTAL_NILM,
                        DEFAULT_ENABLE_EXPERIMENTAL_NILM,
                    ),
                ),
            ): bool,
            vol.Optional(
                CONF_SOURCE_ENTITIES,
                default=source_entities,
            ): _energy_entity_list_selector(selectable_source_entities),
            vol.Optional(
                CONF_MAINS_SOURCE_ENTITIES,
                default=mains_source_entities,
            ): _energy_entity_list_selector(selectable_source_entities),
            vol.Optional(
                CONF_SENSITIVITY,
                default=options.get(
                    CONF_SENSITIVITY,
                    data.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY),
                ),
            ): _select_selector(_SENSITIVITY_OPTIONS),
            vol.Optional(
                CONF_RETENTION_MODE,
                default=options.get(
                    CONF_RETENTION_MODE,
                    data.get(CONF_RETENTION_MODE, DEFAULT_RETENTION_MODE),
                ),
            ): _select_selector(sorted(_VALID_RETENTION_MODES)),
        }
    )


async def _async_format_mapping_suggestions(hass: Any) -> str:
    if hass is None:
        return format_mapping_suggestions([])
    try:
        discovered = await async_discover_sensors(hass)
    except Exception:
        discovered = []
    return format_mapping_suggestions(suggest_dual_phase_pairs(discovered))


async def _async_discover_energy_source_entities(hass: Any) -> list[str]:
    if hass is None:
        return []
    try:
        return await async_discover_energy_source_entities(hass)
    except Exception:
        return []
