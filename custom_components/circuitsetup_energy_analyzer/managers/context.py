from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from ..const import CONF_OUTDOOR_TEMPERATURE_ENTITY
from ..context_sources import configured_context_entity
from ..processors import ProcessingContext

_DEGREE_F = "\N{DEGREE SIGN}F"
_DEGREE_C = "\N{DEGREE SIGN}C"


class ProcessingContextBuilder:
    """Build processor runtime context from coordinator state."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator
        self._contextual_samples_cache: dict[
            tuple[str, tuple[int, ...]],
            Any,
        ] = {}

    def time_zone(self) -> str | None:
        value = getattr(
            getattr(self._coordinator.hass, "config", None),
            "time_zone",
            None,
        )
        return str(value) if value else None

    def build(self, now: datetime) -> ProcessingContext:
        coordinator = self._coordinator
        return ProcessingContext(
            now=now,
            hass=coordinator.hass,
            state=coordinator.state,
            store_data=coordinator.store_data,
            options=coordinator.options,
            entry_data=coordinator.entry_data,
            known_load_circuit_ids=coordinator.circuit_registry.known_load_circuit_ids,
            sensitivity=coordinator.settings_controller.default_sensitivity,
            time_zone=self.time_zone(),
            contextual_samples_cache=self._contextual_samples_cache,
        )

    def configured_context_entity(self, key: str) -> str:
        """Return a configured weather/rain/water context entity id."""
        return configured_context_entity(
            self._coordinator.entry_data,
            self._coordinator.options,
            key,
        )

    def binary_entity_active(self, entity_id: str | None) -> bool | None:
        """Return binary active state from common HA state strings."""
        if not entity_id:
            return None
        raw_state = self.raw_state_for_entity(entity_id)
        if raw_state is None:
            return None
        state = str(getattr(raw_state, "state", "")).strip().lower()
        if state in {
            "on",
            "true",
            "1",
            "wet",
            "rain",
            "raining",
            "detected",
            "hail",
            "lightning-rainy",
            "pouring",
            "rainy",
            "snowy-rainy",
        }:
            return True
        if state in {
            "off",
            "false",
            "0",
            "dry",
            "clear",
            "none",
            "clear-night",
            "cloudy",
            "exceptional",
            "fog",
            "lightning",
            "partlycloudy",
            "sunny",
            "windy",
            "windy-variant",
        }:
            return False
        return None

    def numeric_entity_value(self, entity_id: str | None) -> float | None:
        """Return a numeric HA entity state when available."""
        if not entity_id:
            return None
        raw_state = self.raw_state_for_entity(entity_id)
        if raw_state is None:
            return None
        state = str(getattr(raw_state, "state", "")).strip()
        return _float_or_none(state)

    def entity_unit_of_measurement(self, entity_id: str | None) -> str | None:
        """Return an entity unit of measurement attribute when available."""
        if not entity_id:
            return None
        raw_state = self.raw_state_for_entity(entity_id)
        if raw_state is None:
            return None
        attributes = getattr(raw_state, "attributes", {})
        if not isinstance(attributes, Mapping):
            return None
        unit = str(attributes.get("unit_of_measurement") or "").strip()
        return unit or None

    def max_flow_active_minutes(
        self,
        entity_ids: Iterable[str],
        now: datetime,
    ) -> float:
        """Return the longest active duration across flow entities."""
        durations = [
            self.flow_entity_active_minutes(entity_id, now) for entity_id in entity_ids
        ]
        return round(max(durations, default=0.0), 3)

    def flow_entity_active(self, entity_id: str | None) -> bool | None:
        """Return active state for binary or numeric flow entities."""
        active = self.binary_entity_active(entity_id)
        if active is not None:
            return active
        value = self.numeric_entity_value(entity_id)
        if value is None:
            return None
        return value > 0.0

    def flow_entity_active_minutes(self, entity_id: str, now: datetime) -> float:
        """Return how long an active flow entity has been active."""
        if self.flow_entity_active(entity_id) is not True:
            return 0.0
        raw_state = self.raw_state_for_entity(entity_id)
        changed_at = _datetime_or_none(getattr(raw_state, "last_changed", None))
        if changed_at is None:
            return 0.0
        return max(0.0, (now - changed_at).total_seconds() / 60.0)

    def recent_flow_context_minutes(
        self,
        entity_ids: Iterable[str],
        now: datetime,
        threshold_minutes: int,
    ) -> float:
        """Return recent flow context minutes for recently changed flow sensors."""
        recent_minutes = 0.0
        lookback = timedelta(minutes=max(threshold_minutes, 1) * 3)
        for entity_id in entity_ids:
            raw_state = self.raw_state_for_entity(entity_id)
            if raw_state is None:
                continue
            changed_at = _datetime_or_none(getattr(raw_state, "last_changed", None))
            if changed_at is not None and now - changed_at <= lookback:
                recent_minutes = max(recent_minutes, threshold_minutes)
        return recent_minutes

    def outdoor_temperature_entity(self) -> str:
        """Return the configured outdoor-temperature context entity id."""
        for source in (self._coordinator.options, self._coordinator.entry_data):
            entity_id = str(source.get(CONF_OUTDOOR_TEMPERATURE_ENTITY, "")).strip()
            if entity_id:
                return entity_id
        return ""

    def temperature_reading_for_entity(
        self,
        entity_id: str,
    ) -> dict[str, float | str] | None:
        """Return a normalized outdoor temperature reading."""
        raw_state = self.raw_state_for_entity(entity_id)
        if raw_state is None:
            return None
        attributes = getattr(raw_state, "attributes", {}) or {}
        if not isinstance(attributes, Mapping):
            attributes = {}
        state = str(getattr(raw_state, "state", "")).strip()
        value = _float_or_none(state)
        raw_unit = str(attributes.get("unit_of_measurement") or "").strip()
        if value is None:
            value = _float_or_none(attributes.get("temperature"))
            raw_unit = str(attributes.get("temperature_unit") or "").strip()
        if value is None:
            return None
        source_unit = self.temperature_source_unit(
            raw_unit,
        )
        temperature_f = _temperature_to_fahrenheit(value, source_unit)
        display_unit = self.temperature_display_unit(source_unit)
        display_temperature = _temperature_from_fahrenheit(
            temperature_f,
            display_unit,
        )
        return {
            "temperature_f": round(temperature_f, 3),
            "display_temperature": round(display_temperature, 3),
            "display_unit": display_unit,
            "source_unit": source_unit,
        }

    def humidity_percent_for_entity(self, entity_id: str | None) -> float | None:
        """Return an optional relative-humidity attribute."""
        value = self._numeric_entity_attribute(entity_id, "humidity")
        return value if value is not None and 0.0 <= value <= 100.0 else None

    def precipitation_reading_for_entity(
        self,
        entity_id: str | None,
    ) -> dict[str, float | str | None] | None:
        """Return precipitation from a numeric sensor or weather entity."""
        if not entity_id:
            return None
        raw_state = self.raw_state_for_entity(entity_id)
        if raw_state is None:
            return None
        attributes = getattr(raw_state, "attributes", {})
        if not isinstance(attributes, Mapping):
            attributes = {}
        value = _float_or_none(getattr(raw_state, "state", None))
        unit = str(attributes.get("unit_of_measurement") or "").strip()
        if value is None:
            value = _float_or_none(attributes.get("precipitation"))
            unit = str(attributes.get("precipitation_unit") or "").strip()
        if value is None or value < 0.0:
            return None
        return {"value": value, "unit": unit or None}

    def _numeric_entity_attribute(
        self,
        entity_id: str | None,
        key: str,
    ) -> float | None:
        if not entity_id:
            return None
        raw_state = self.raw_state_for_entity(entity_id)
        attributes = getattr(raw_state, "attributes", {})
        if not isinstance(attributes, Mapping):
            return None
        return _float_or_none(attributes.get(key))

    def temperature_source_unit(self, raw_unit: str) -> str:
        """Return normalized source temperature unit, falling back to HA unit."""
        unit = _normalized_temperature_unit(raw_unit)
        if unit:
            return unit
        return self.ha_temperature_unit()

    def temperature_display_unit(self, source_unit: str) -> str:
        """Return the display unit for a temperature source."""
        if source_unit in {_DEGREE_F, _DEGREE_C}:
            return source_unit
        return self.ha_temperature_unit()

    def ha_temperature_unit(self) -> str:
        """Return Home Assistant's configured temperature unit."""
        config = getattr(self._coordinator.hass, "config", None)
        units = getattr(config, "units", None)
        raw_unit = getattr(units, "temperature_unit", None)
        unit = _normalized_temperature_unit(str(raw_unit or ""))
        return unit or _DEGREE_F

    def raw_state_for_entity(self, entity_id: str) -> Any | None:
        """Return raw Home Assistant state object for one entity id."""
        hass_states = getattr(self._coordinator.hass, "states", None)
        get_state = getattr(hass_states, "get", None)
        if get_state is None:
            return None
        return get_state(entity_id)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _normalized_temperature_unit(unit: str) -> str:
    normalized = str(unit or "").strip().lower()
    if normalized in {"\N{DEGREE SIGN}f", "f", "fahrenheit"}:
        return _DEGREE_F
    if normalized in {"\N{DEGREE SIGN}c", "c", "celsius"}:
        return _DEGREE_C
    if normalized in {"k", "kelvin"}:
        return "K"
    return ""


def _temperature_to_fahrenheit(value: float, unit: str) -> float:
    if unit == _DEGREE_C:
        return (value * 9.0 / 5.0) + 32.0
    if unit == "K":
        return ((value - 273.15) * 9.0 / 5.0) + 32.0
    return value


def _temperature_from_fahrenheit(value: float, unit: str) -> float:
    if unit == _DEGREE_C:
        return (value - 32.0) * 5.0 / 9.0
    return value
