from __future__ import annotations

from enum import StrEnum

try:
    from homeassistant.const import Platform
except ModuleNotFoundError:

    class Platform(StrEnum):
        """Fallback platform enum for unit tests without Home Assistant installed."""

        SENSOR = "sensor"
        BINARY_SENSOR = "binary_sensor"
        BUTTON = "button"
        SELECT = "select"
        NUMBER = "number"
        SWITCH = "switch"
        TEXT = "text"
        TIME = "time"


DOMAIN = "circuitsetup_energy_analyzer"
DATA_RELOAD_COUNT = "_reload_count"

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.TEXT,
    Platform.TIME,
]

CONF_CIRCUITS = "circuits"
CONF_CIRCUIT_ASSIGNMENTS = "circuit_assignments"
CONF_ADVANCED_SETTINGS = "advanced_settings"
CONF_DASHBOARD_LAYOUT = "dashboard_layout"
CONF_DEMO_SOURCE_BUNDLE_ENABLED = "demo_source_bundle_enabled"
CONF_ENABLE_EXPERIMENTAL_NILM = "enable_experimental_nilm"
CONF_ENTITY_DETAIL_LEVEL = "entity_detail_level"
CONF_ENTITY_MODEL_VERSION = "entity_model_version"
CONF_EXTRA_SOURCE_ENTITIES = "extra_source_entities"
CONF_KNOWN_LOAD_CIRCUITS = "known_load_circuits"
CONF_LEGACY_ENTITY_COMPATIBILITY_KEYS = "legacy_entity_compatibility_keys"
CONF_MAINS_SOURCE_ENTITIES = "mains_source_entities"
CONF_OUTDOOR_TEMPERATURE_ENTITY = "outdoor_temperature_entity"
CONF_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT = "rain_activity_delta_threshold_pct"
CONF_RAIN_INTENSITY_ENTITY = "rain_intensity_entity"
CONF_RAIN_PUMP_CORRELATION_ENABLED = "rain_pump_correlation_enabled"
CONF_RAIN_RESPONSE_WINDOW_MINUTES = "rain_response_window_minutes"
CONF_RAIN_SENSOR_ENTITY = "rain_sensor_entity"
CONF_RETENTION_MODE = "retention_mode"
CONF_SELECTED_ENTITY_GROUPS = "selected_entity_groups"
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
DASHBOARD_LAYOUT_SIMPLE = "simple"
DASHBOARD_LAYOUT_STANDARD = "standard"
DASHBOARD_LAYOUT_EXPERT = "expert"
DASHBOARD_LAYOUTS = (
    DASHBOARD_LAYOUT_SIMPLE,
    DASHBOARD_LAYOUT_STANDARD,
    DASHBOARD_LAYOUT_EXPERT,
)
DEFAULT_DASHBOARD_LAYOUT = DASHBOARD_LAYOUT_SIMPLE
ENTITY_DETAIL_SIMPLE = "simple"
ENTITY_DETAIL_STANDARD = "standard"
ENTITY_DETAIL_EXPERT = "expert"
DEFAULT_ENTITY_DETAIL_LEVEL = ENTITY_DETAIL_SIMPLE
ENTITY_MODEL_LEGACY = 1
ENTITY_MODEL_COMPACT = 2
DEFAULT_FLOW_MISMATCH_THRESHOLD_MINUTES = 5
DEFAULT_RAIN_ACTIVITY_DELTA_THRESHOLD_PCT = 25.0
DEFAULT_RAIN_PUMP_CORRELATION_ENABLED = True
DEFAULT_RAIN_RESPONSE_WINDOW_MINUTES = 120
DEFAULT_SENSITIVITY = "balanced"
DEFAULT_RETENTION_MODE = "standard"
DEFAULT_WATER_FLOW_CORRELATION_ENABLED = True

STORAGE_KEY = f"{DOMAIN}.store"
STORAGE_VERSION = 8

MIN_LEARNING_DAYS = 7
