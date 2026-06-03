from __future__ import annotations

import json
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
    )
    ha_selector = None

from .const import (
    CONF_CIRCUITS,
    CONF_ENABLE_EXPERIMENTAL_NILM,
    CONF_KNOWN_LOAD_CIRCUITS,
    CONF_MAINS_SOURCE_ENTITIES,
    CONF_RETENTION_MODE,
    CONF_SENSITIVITY,
    CONF_SOURCE_ENTITIES,
    DEFAULT_ENABLE_EXPERIMENTAL_NILM,
    DEFAULT_RETENTION_MODE,
    DEFAULT_SENSITIVITY,
    DOMAIN,
)
from .discovery import async_discover_sensors
from .mapping import DualPhaseSuggestion, suggest_dual_phase_pairs
from .models import ApplianceProfile, CircuitMode, RetentionMode

TITLE = "CircuitSetup Energy Analyzer"
ERROR_NO_SOURCE_ENTITIES = "no_source_entities"
ERROR_INVALID_SOURCE_ENTITIES = "invalid_source_entities"
_VALID_CIRCUIT_MODES = {mode.value for mode in CircuitMode}
_VALID_APPLIANCE_PROFILES = {profile.value for profile in ApplianceProfile}
_VALID_RETENTION_MODES = {mode.value for mode in RetentionMode}
_SENSITIVITY_OPTIONS = ("standard", "high", "low")


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
            "No dual-phase mapping suggestions were found; manual definition is "
            "needed for circuit channels."
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

    circuits = _validate_circuits(user_input.get(CONF_CIRCUITS, []))
    retention_mode = _validate_retention_mode(user_input)

    return {
        CONF_SOURCE_ENTITIES: source_entities,
        CONF_CIRCUITS: circuits,
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
        CONF_KNOWN_LOAD_CIRCUITS: _strict_string_list(
            user_input.get(CONF_KNOWN_LOAD_CIRCUITS, []),
            invalid_error_key="invalid_known_load_circuits",
        ),
        CONF_SENSITIVITY: str(user_input.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY)),
        CONF_RETENTION_MODE: retention_mode,
    }


def validate_options_input(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize options flow data without requiring Home Assistant."""
    return {
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
        CONF_KNOWN_LOAD_CIRCUITS: _strict_string_list(
            user_input.get(CONF_KNOWN_LOAD_CIRCUITS, []),
            invalid_error_key="invalid_known_load_circuits",
        ),
        CONF_SENSITIVITY: str(user_input.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY)),
        CONF_RETENTION_MODE: _validate_retention_mode(user_input),
    }


def _validate_circuits(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        try:
            value = json.loads(value)
        except json.JSONDecodeError as err:
            raise SetupValidationError("invalid_circuits") from err
    if not isinstance(value, list):
        raise SetupValidationError("invalid_circuits")

    circuits: list[Any] = []
    for circuit in value:
        if not isinstance(circuit, Mapping):
            raise SetupValidationError("invalid_circuits")
        mode = circuit.get("mode")
        if mode is not None and str(mode) not in _VALID_CIRCUIT_MODES:
            raise SetupValidationError("invalid_circuit_mode")
        profile = circuit.get("appliance_profile")
        if profile is not None and str(profile) not in _VALID_APPLIANCE_PROFILES:
            raise SetupValidationError("invalid_appliance_profile")
        circuits.append(circuit)
    return circuits


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


def _entity_list_selector() -> Any:
    return _selector(
        {
            "entity": {
                "multiple": True,
                "filter": [{"domain": "sensor"}],
            }
        },
        str,
    )


def _multiline_text_selector() -> Any:
    return _selector({"text": {"multiline": True}}, str)


def _select_selector(options: Iterable[str]) -> Any:
    return _selector({"select": {"options": list(options)}}, vol.In(tuple(options)))


def _list_text_default(value: Any) -> str:
    return "\n".join(
        _strict_string_list(value, invalid_error_key="invalid_list_default")
    )


DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SOURCE_ENTITIES): _entity_list_selector(),
        vol.Optional(CONF_CIRCUITS, default=""): _multiline_text_selector(),
        vol.Optional(
            CONF_ENABLE_EXPERIMENTAL_NILM,
            default=DEFAULT_ENABLE_EXPERIMENTAL_NILM,
        ): bool,
        vol.Optional(CONF_MAINS_SOURCE_ENTITIES, default=[]): _entity_list_selector(),
        vol.Optional(CONF_KNOWN_LOAD_CIRCUITS, default=""): _multiline_text_selector(),
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
            data_schema=DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "mapping_suggestions": await _async_format_mapping_suggestions(
                    getattr(self, "hass", None)
                )
            },
        )


class CircuitSetupEnergyAnalyzerOptionsFlow(config_entries.OptionsFlow):
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
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(self._config_entry),
            errors=errors or {},
            description_placeholders={
                "mapping_suggestions": await _async_format_mapping_suggestions(
                    getattr(self, "hass", None)
                )
            },
        )


def _options_schema(config_entry: config_entries.ConfigEntry) -> Any:
    options = getattr(config_entry, "options", {}) or {}
    data = getattr(config_entry, "data", {}) or {}
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
                CONF_MAINS_SOURCE_ENTITIES,
                default=options.get(
                    CONF_MAINS_SOURCE_ENTITIES,
                    data.get(CONF_MAINS_SOURCE_ENTITIES, []),
                ),
            ): _entity_list_selector(),
            vol.Optional(
                CONF_KNOWN_LOAD_CIRCUITS,
                default=_list_text_default(
                    options.get(
                        CONF_KNOWN_LOAD_CIRCUITS,
                        data.get(CONF_KNOWN_LOAD_CIRCUITS, []),
                    )
                ),
            ): _multiline_text_selector(),
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
