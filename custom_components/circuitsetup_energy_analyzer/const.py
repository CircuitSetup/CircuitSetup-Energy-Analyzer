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
CONF_RETENTION_MODE = "retention_mode"
CONF_SENSITIVITY = "sensitivity"
CONF_SOURCE_DEVICES = "source_devices"
CONF_SOURCE_ENTITIES = "source_entities"
CONF_UTILITY_COMPARISON_SETTINGS = "utility_comparison_settings"

DEFAULT_ENABLE_EXPERIMENTAL_NILM = False
DEFAULT_SENSITIVITY = "standard"
DEFAULT_RETENTION_MODE = "standard"

STORAGE_KEY = f"{DOMAIN}.store"
STORAGE_VERSION = 1

MIN_LEARNING_DAYS = 7
