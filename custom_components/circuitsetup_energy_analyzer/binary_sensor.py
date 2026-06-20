from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from .const import (
    CONF_ADVANCED_SETTINGS,
    CONF_LINKED_FLOW_SENSOR_ENTITIES,
    CONF_WATER_FLOW_SENSOR_ENTITIES,
    DOMAIN,
)
from .entity import (
    CircuitAnalyzerEntity,
    EntityCategory,
    EntityTier,
    circuit_info_from_config,
    circuits_for_entities,
    device_identifiers_for_entities,
    entity_detail_level_for_coordinator,
    entity_enabled_default_for_tier,
    prune_stale_device_registry_entries,
    prune_stale_entity_registry_entries,
    sync_entity_registry_categories,
)
from .entity_catalog import (
    compact_creation_rule_for_entity,
    legacy_compatibility_keys_for_setup,
    selected_entity_groups_for_coordinator,
    should_create_entity,
)
from .models import ApplianceProfile, SensorRole
from .operating_detection import (
    PROFILE_RUNNING_ON_THRESHOLDS_W,
    operating_state_is_running,
)

try:
    from homeassistant.components.binary_sensor import BinarySensorEntity
except ModuleNotFoundError:

    class BinarySensorEntity:
        """Fallback binary sensor base for tests without Home Assistant."""


_RUNNING_BINARY_SENSOR_PROFILES = frozenset(
    {
        ApplianceProfile.REFRIGERATOR,
        ApplianceProfile.FREEZER,
        ApplianceProfile.HVAC,
        ApplianceProfile.HVAC_COMPRESSOR,
        ApplianceProfile.HVAC_BLOWER,
        ApplianceProfile.ELECTRIC_HEAT,
        ApplianceProfile.WATER_HEATER,
        ApplianceProfile.OVEN,
        ApplianceProfile.MICROWAVE,
        ApplianceProfile.WASHER,
        ApplianceProfile.DRYER,
        ApplianceProfile.POOL_PUMP,
        ApplianceProfile.WATER_PUMP,
        ApplianceProfile.WELL_PUMP,
        ApplianceProfile.SUMP_PUMP,
        ApplianceProfile.EV_CHARGER,
        ApplianceProfile.MOTOR_LOAD,
        ApplianceProfile.RESISTIVE_LOAD,
    }
)

APPLIANCE_RUNNING_POWER_THRESHOLDS_W = {
    profile: PROFILE_RUNNING_ON_THRESHOLDS_W[profile]
    for profile in _RUNNING_BINARY_SENSOR_PROFILES
}

LAUNDRY_RUNNING_POWER_THRESHOLDS_W = {
    ApplianceProfile.WASHER: APPLIANCE_RUNNING_POWER_THRESHOLDS_W[
        ApplianceProfile.WASHER
    ],
    ApplianceProfile.DRYER: APPLIANCE_RUNNING_POWER_THRESHOLDS_W[
        ApplianceProfile.DRYER
    ],
}


def is_learning(
    state: Any,
    circuit_id: str,
    appliance_profile: ApplianceProfile | None = None,
) -> bool:
    """Return whether a circuit is still in its learning period."""
    return bool(getattr(state, "learning_by_circuit", {}).get(circuit_id, True))


def has_data_quality_problem(
    state: Any,
    circuit_id: str,
    appliance_profile: ApplianceProfile | None = None,
) -> bool:
    """Return true when a circuit has a non-empty data quality issue."""
    issue = getattr(state, "data_quality_by_circuit", {}).get(circuit_id, "")
    return bool(issue)


def is_maintenance_active(
    state: Any,
    circuit_id: str,
    appliance_profile: ApplianceProfile | None = None,
) -> bool:
    """Return whether a circuit is currently marked as in maintenance."""
    maintenance = getattr(state, "maintenance_by_circuit", {}).get(circuit_id, {})
    if not isinstance(maintenance, dict):
        return False
    return maintenance.get("active") is True


def is_appliance_running(
    state: Any,
    circuit_id: str,
    appliance_profile: ApplianceProfile | str | None = None,
) -> bool:
    """Return whether an appliance appears active from cycle status or watts."""
    profile = _appliance_profile(appliance_profile)
    threshold = APPLIANCE_RUNNING_POWER_THRESHOLDS_W.get(profile)
    if threshold is None:
        return False

    operating_snapshots = getattr(state, "operating_state_snapshot_by_circuit", {})
    if isinstance(operating_snapshots, dict):
        snapshot = operating_snapshots.get(circuit_id)
        if isinstance(snapshot, Mapping):
            running = operating_state_is_running(snapshot)
            if running is not None:
                return running
            return False

    cycle_status_by_circuit = getattr(state, "run_cycle_status_by_circuit", {})
    if isinstance(cycle_status_by_circuit, dict):
        cycle_status = str(cycle_status_by_circuit.get(circuit_id, "")).lower()
        if cycle_status == "running":
            return True
        if cycle_status == "idle":
            return False

    power_by_circuit = getattr(state, "latest_real_power_w_by_circuit", {})
    if not isinstance(power_by_circuit, dict):
        return False
    power_w = power_by_circuit.get(circuit_id)
    if power_w is None:
        return False
    try:
        return float(power_w) >= threshold
    except (TypeError, ValueError):
        return False


def is_laundry_appliance_running(
    state: Any,
    circuit_id: str,
    appliance_profile: ApplianceProfile | str | None = None,
) -> bool:
    """Return whether a washer or dryer appears active from latest watts."""
    return is_appliance_running(state, circuit_id, appliance_profile)


def has_water_flow_mismatch(
    state: Any,
    circuit_id: str,
    appliance_profile: ApplianceProfile | str | None = None,
) -> bool:
    """Return whether water-flow evidence currently indicates a possible issue."""
    evidence = getattr(state, "water_flow_context_by_circuit", {}).get(circuit_id, {})
    if not isinstance(evidence, dict):
        return False
    return evidence.get("status") in {
        "possible_flow_without_load",
        "possible_load_without_flow",
        "possible_sensor_problem",
    }


@dataclass(frozen=True, slots=True)
class DiagnosticBinarySensorDescription:
    """Description for one diagnostic binary sensor entity."""

    key: str
    name_suffix: str
    value_fn: Callable[[Any, str, ApplianceProfile | None], bool]
    device_class: str | None = None
    entity_category: Any | None = EntityCategory.DIAGNOSTIC
    entity_registry_enabled_default: bool = True
    entity_registry_visible_default: bool = True
    entity_tier: EntityTier = EntityTier.DIAGNOSTIC
    entity_picture: str | None = None
    force_update: bool = False
    has_entity_name: bool = False
    icon: str | None = None
    name: str | None = None
    translation_key: str | None = None
    translation_placeholders: dict[str, str] | None = None
    unit_of_measurement: str | None = None


BINARY_SENSOR_ICONS = {
    "learning": "mdi:school-outline",
    "data_quality_problem": "mdi:database-alert-outline",
    "maintenance": "mdi:wrench-clock",
    "running": "mdi:power-cycle",
    "water_flow_mismatch": "mdi:pipe-leak",
}


BINARY_SENSOR_DESCRIPTIONS: tuple[DiagnosticBinarySensorDescription, ...] = (
    DiagnosticBinarySensorDescription(
        key="learning",
        name_suffix="Learning",
        value_fn=is_learning,
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
    ),
    DiagnosticBinarySensorDescription(
        key="data_quality_problem",
        name_suffix="Data Quality Problem",
        value_fn=has_data_quality_problem,
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
    ),
    DiagnosticBinarySensorDescription(
        key="maintenance",
        name_suffix="Maintenance",
        value_fn=is_maintenance_active,
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
    ),
    DiagnosticBinarySensorDescription(
        key="running",
        name_suffix="Running",
        value_fn=is_appliance_running,
        device_class="running",
        entity_category=None,
        entity_tier=EntityTier.SUMMARY,
    ),
    DiagnosticBinarySensorDescription(
        key="water_flow_mismatch",
        name_suffix="Water Flow Mismatch",
        value_fn=has_water_flow_mismatch,
        device_class="problem",
        entity_category=None,
        entity_tier=EntityTier.FEATURE,
    ),
)


def _with_binary_entity_defaults(
    description: DiagnosticBinarySensorDescription,
) -> DiagnosticBinarySensorDescription:
    tier = description.entity_tier
    return replace(
        description,
        entity_category=(
            None if tier is not EntityTier.DIAGNOSTIC else description.entity_category
        ),
        entity_registry_enabled_default=entity_enabled_default_for_tier(tier),
    )


BINARY_SENSOR_DESCRIPTIONS = tuple(
    _with_binary_entity_defaults(description)
    for description in BINARY_SENSOR_DESCRIPTIONS
)
BINARY_SENSOR_ENTITY_TIER_BY_KEY: dict[str, EntityTier] = {
    description.key: description.entity_tier
    for description in BINARY_SENSOR_DESCRIPTIONS
}


class CircuitAnalyzerBinarySensor(CircuitAnalyzerEntity, BinarySensorEntity):
    """Binary sensor exposing one diagnostic flag for an analyzed circuit."""

    def __init__(
        self,
        coordinator: Any,
        *,
        entry_id: str,
        circuit: Any,
        description: DiagnosticBinarySensorDescription,
    ) -> None:
        super().__init__(
            coordinator,
            entry_id=entry_id,
            circuit=circuit,
            key=description.key,
            name_suffix=description.name_suffix,
        )
        self.entity_description = description
        self._appliance_profile = _appliance_profile(
            getattr(circuit, "appliance_profile", None)
        )
        self._attr_device_class = description.device_class
        self._attr_entity_category = description.entity_category
        self._attr_entity_registry_enabled_default = (
            entity_enabled_default_for_tier(
                description.entity_tier,
                entity_detail_level_for_coordinator(coordinator),
            )
        )
        self._attr_entity_registry_visible_default = (
            description.entity_registry_visible_default
        )
        self._attr_icon = description.icon or BINARY_SENSOR_ICONS.get(description.key)

    @property
    def icon(self) -> str | None:
        """Return the purpose-specific icon for fallback tests."""
        return self._attr_icon

    @property
    def available(self) -> bool:
        """Report when the Running state is temporarily unavailable."""
        if self.entity_description.key != "running":
            return True
        state = self.coordinator_state
        if state is None:
            return True
        snapshots = getattr(state, "operating_state_snapshot_by_circuit", {})
        if not isinstance(snapshots, Mapping):
            return True
        snapshot = snapshots.get(self.circuit_id)
        if not isinstance(snapshot, Mapping):
            return True
        return operating_state_is_running(snapshot) is not None

    @property
    def is_on(self) -> bool:
        """Return the latest diagnostic flag."""
        if self.coordinator_state is None:
            return self.entity_description.value_fn(
                None,
                self.circuit_id,
                self._appliance_profile,
            )
        return self.entity_description.value_fn(
            self.coordinator_state,
            self.circuit_id,
            self._appliance_profile,
        )


def _compact_binary_sensor_descriptions_for_setup(
    descriptions: tuple[DiagnosticBinarySensorDescription, ...],
    circuit: Any,
    coordinator: Any,
    *,
    hass: Any,
    entry_id: str,
) -> tuple[DiagnosticBinarySensorDescription, ...]:
    compatibility_keys = legacy_compatibility_keys_for_setup(
        hass,
        entry_id=entry_id,
        coordinator=coordinator,
    )
    selected_groups = selected_entity_groups_for_coordinator(coordinator)
    detail_level = entity_detail_level_for_coordinator(coordinator)
    compact_descriptions: list[DiagnosticBinarySensorDescription] = []
    for description in descriptions:
        rule = compact_creation_rule_for_entity("binary_sensor", description.key)
        if not should_create_entity(
            rule=rule,
            circuit=circuit,
            coordinator=coordinator,
            detail_level=detail_level,
            selected_groups=selected_groups,
            legacy_compatibility_keys=compatibility_keys,
        ):
            continue
        compact_descriptions.append(description)
    return tuple(compact_descriptions)


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up diagnostic binary sensor entities for configured circuits."""
    entry_id = getattr(entry, "entry_id", "default")
    coordinator = hass.data[DOMAIN][entry_id]
    entities: list[CircuitAnalyzerBinarySensor] = []

    for raw_circuit in circuits_for_entities(entry, coordinator):
        circuit = circuit_info_from_config(raw_circuit)
        if circuit is None:
            continue
        descriptions = tuple(
            description
            for description in BINARY_SENSOR_DESCRIPTIONS
            if binary_sensor_description_applies(description, circuit, coordinator)
        )
        descriptions = _compact_binary_sensor_descriptions_for_setup(
            descriptions,
            raw_circuit,
            coordinator,
            hass=hass,
            entry_id=entry_id,
        )
        entities.extend(
            CircuitAnalyzerBinarySensor(
                coordinator,
                entry_id=entry_id,
                circuit=circuit,
                description=description,
            )
            for description in descriptions
        )

    prune_stale_entity_registry_entries(
        hass,
        entry_id=entry_id,
        entity_domain="binary_sensor",
        desired_unique_ids={entity.unique_id for entity in entities},
    )
    prune_stale_device_registry_entries(
        hass,
        entry_id=entry_id,
        desired_identifiers=device_identifiers_for_entities(entities),
    )
    async_add_entities(entities)
    sync_entity_registry_categories(
        hass,
        entry_id=entry_id,
        entity_domain="binary_sensor",
        entity_category_by_unique_id_suffix={
            description.key: description.entity_category
            for description in BINARY_SENSOR_DESCRIPTIONS
        },
    )


def binary_sensor_description_applies(
    description: DiagnosticBinarySensorDescription,
    circuit: Any,
    coordinator: Any | None = None,
) -> bool:
    """Return whether a binary sensor is useful for this circuit."""
    if description.key == "water_flow_mismatch":
        return (
            _appliance_profile(getattr(circuit, "appliance_profile", None))
            in {
                ApplianceProfile.WATER_PUMP,
                ApplianceProfile.WELL_PUMP,
                ApplianceProfile.WATER_HEATER,
                ApplianceProfile.WASHER,
            }
            and _has_water_flow_source(coordinator, circuit)
        )
    if description.key != "running":
        return True
    return (
        _appliance_profile(getattr(circuit, "appliance_profile", None))
        in APPLIANCE_RUNNING_POWER_THRESHOLDS_W
        and _has_real_power_sensor(circuit)
    )


def _has_real_power_sensor(circuit: Any) -> bool:
    """Return true when the configured circuit has active-power data."""
    return any(
        _sensor_role(sensor) is SensorRole.REAL_POWER
        for sensor in getattr(circuit, "sensors", ()) or ()
    )


def _sensor_role(sensor: Any) -> SensorRole | None:
    """Return a normalized sensor role from dict or dataclass sensor refs."""
    if isinstance(sensor, dict):
        role = sensor.get("role")
    else:
        role = getattr(sensor, "role", None)
    if isinstance(role, SensorRole):
        return role
    if role is None:
        return None
    try:
        return SensorRole(str(role))
    except ValueError:
        return None


def _has_water_flow_source(coordinator: Any | None, circuit: Any | None = None) -> bool:
    """Return true when a water-flow input is configured for the integration."""
    if coordinator is None:
        return False
    for field_name in ("options", "entry_data"):
        container = getattr(coordinator, field_name, {})
        value = container.get(CONF_WATER_FLOW_SENSOR_ENTITIES) if isinstance(
            container,
            dict,
        ) else None
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, (list, tuple, set)) and any(
            bool(str(item).strip()) for item in value
        ):
            return True
    return circuit is not None and _has_linked_water_flow_source(coordinator, circuit)


def _has_linked_water_flow_source(coordinator: Any, circuit: Any) -> bool:
    """Return true when this circuit has a linked flow sensor override."""
    settings = _advanced_settings_for_circuit(coordinator, circuit)
    value = settings.get(CONF_LINKED_FLOW_SENSOR_ENTITIES)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return any(bool(str(item).strip()) for item in value)
    return False


def _advanced_settings_for_circuit(coordinator: Any, circuit: Any) -> Mapping[str, Any]:
    for field_name in ("options", "entry_data"):
        container = getattr(coordinator, field_name, {})
        settings_by_circuit = (
            container.get(CONF_ADVANCED_SETTINGS)
            if isinstance(container, Mapping)
            else None
        )
        if not isinstance(settings_by_circuit, Mapping):
            continue
        settings = settings_by_circuit.get(_circuit_id(circuit), {})
        if isinstance(settings, Mapping):
            return settings
    return {}


def _circuit_id(circuit: Any) -> str:
    if isinstance(circuit, Mapping):
        return str(circuit.get("circuit_id") or circuit.get("id") or "")
    return str(getattr(circuit, "circuit_id", "") or "")


def _appliance_profile(value: Any) -> ApplianceProfile | None:
    """Return a normalized appliance profile value."""
    if isinstance(value, ApplianceProfile):
        return value
    if value is None:
        return None
    try:
        return ApplianceProfile(str(value))
    except ValueError:
        return None
