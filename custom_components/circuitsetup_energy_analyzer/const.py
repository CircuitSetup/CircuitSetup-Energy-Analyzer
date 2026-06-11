from __future__ import annotations

from enum import StrEnum

try:
    from homeassistant.const import Platform
except ModuleNotFoundError:

    class Platform(StrEnum):
        """Fallback platform enum for unit tests without Home Assistant installed."""

        SENSOR = "sensor"
        BINARY_SENSOR = "binary_sensor"


DOMAIN = "circuitsetup_energy_analyzer"

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

CONF_CIRCUITS = "circuits"
CONF_CIRCUIT_ASSIGNMENTS = "circuit_assignments"
CONF_ADVANCED_SETTINGS = "advanced_settings"
CONF_ENABLE_EXPERIMENTAL_NILM = "enable_experimental_nilm"
CONF_EXTRA_SOURCE_ENTITIES = "extra_source_entities"
CONF_KNOWN_LOAD_CIRCUITS = "known_load_circuits"
CONF_MAINS_SOURCE_ENTITIES = "mains_source_entities"
CONF_OUTDOOR_TEMPERATURE_ENTITY = "outdoor_temperature_entity"
CONF_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT = "rain_activity_delta_threshold_pct"
CONF_RAIN_INTENSITY_ENTITY = "rain_intensity_entity"
CONF_RAIN_PUMP_CORRELATION_ENABLED = "rain_pump_correlation_enabled"
CONF_RAIN_RESPONSE_WINDOW_MINUTES = "rain_response_window_minutes"
CONF_RAIN_SENSOR_ENTITY = "rain_sensor_entity"
CONF_RETENTION_MODE = "retention_mode"
CONF_SENSITIVITY = "sensitivity"
CONF_SOURCE_DEVICES = "source_devices"
CONF_SOURCE_ENTITIES = "source_entities"
CONF_UTILITY_COMPARISON_SETTINGS = "utility_comparison_settings"
CONF_WATER_FLOW_CORRELATION_ENABLED = "water_flow_correlation_enabled"
CONF_WATER_FLOW_SENSOR_ENTITIES = "water_flow_sensor_entities"
CONF_FLOW_MISMATCH_THRESHOLD_MINUTES = "flow_mismatch_threshold_minutes"
CONF_LINKED_FLOW_SENSOR_ENTITIES = "linked_flow_sensor_entities"
CONF_EXPECTS_WATER_FLOW = "expects_water_flow"

DEFAULT_ENABLE_EXPERIMENTAL_NILM = False
DEFAULT_FLOW_MISMATCH_THRESHOLD_MINUTES = 5
DEFAULT_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT = 25.0
DEFAULT_RAIN_PUMP_CORRELATION_ENABLED = True
DEFAULT_RAIN_RESPONSE_WINDOW_MINUTES = 120
DEFAULT_SENSITIVITY = "standard"
DEFAULT_RETENTION_MODE = "standard"
DEFAULT_WATER_FLOW_CORRELATION_ENABLED = True

STORAGE_KEY = f"{DOMAIN}.store"
STORAGE_VERSION = 1

MIN_LEARNING_DAYS = 7
