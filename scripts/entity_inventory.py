from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from custom_components.circuitsetup_energy_analyzer import (
    binary_sensor,
    button,
    number,
    select,
    sensor,
)
from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_ENTITY_DETAIL_LEVEL,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_RAIN_SENSOR_ENTITY,
    CONF_WATER_FLOW_SENSOR_ENTITIES,
    ENTITY_DETAIL_EXPERT,
    ENTITY_DETAIL_SIMPLE,
    ENTITY_DETAIL_STANDARD,
)
from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.entity import (
    EntityTier,
    entity_enabled_default_for_tier,
)
from custom_components.circuitsetup_energy_analyzer.entity_catalog import (
    compact_creation_rule_for_entity,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    PowerFlowMode,
    SensorRef,
    SensorRole,
)

DETAIL_LEVELS = (
    ENTITY_DETAIL_SIMPLE,
    ENTITY_DETAIL_STANDARD,
    ENTITY_DETAIL_EXPERT,
)
CONFIGURATION_VARIANTS = (
    "minimal_sources",
    "full_electrical_sources",
    "all_applicable_optional_settings",
)
REPRESENTATIVE_SCENARIO_IDS = (
    "refrigerator",
    "washer",
    "dryer_dual_phase",
    "hvac",
    "water_heater",
    "ev_charger",
    "sump_pump_with_rain",
    "water_pump_with_flow",
    "solar_inverter",
    "mains_nilm",
    "mixed_circuit",
)


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    """Representative circuit shape used by the inventory report."""

    scenario_id: str
    profile: ApplianceProfile
    mode: CircuitMode = CircuitMode.SINGLE_PHASE
    minimal_roles: tuple[SensorRole, ...] = (SensorRole.REAL_POWER,)
    full_roles: tuple[SensorRole, ...] = field(
        default_factory=lambda: FULL_ELECTRICAL_ROLES,
    )
    power_flow: PowerFlowMode = PowerFlowMode.LOAD


FULL_ELECTRICAL_ROLES = (
    SensorRole.REAL_POWER,
    SensorRole.ENERGY,
    SensorRole.CURRENT,
    SensorRole.VOLTAGE,
    SensorRole.APPARENT_POWER,
    SensorRole.POWER_FACTOR,
    SensorRole.REACTIVE_POWER,
)


def build_inventory_report() -> dict[str, Any]:
    """Build a deterministic current-entity inventory report."""
    scenarios = _scenario_definitions()
    return {
        "report": "entity-inventory-before",
        "scope": "per-circuit entities only",
        "configuration_variants": list(CONFIGURATION_VARIANTS),
        "detail_levels": list(DETAIL_LEVELS),
        "entity_descriptions": entity_description_rows(),
        "global_entities": global_entity_rows(),
        "scenarios": [
            _scenario_report(scenario, scenarios) for scenario in scenarios
        ],
    }


def entity_description_rows() -> list[dict[str, Any]]:
    """Return current entity description metadata for documentation."""
    rows: list[dict[str, Any]] = []
    rows.extend(
        _description_row(
            "sensor",
            description.key,
            description.name_suffix,
            tier=description.entity_tier,
            entity_category=description.entity_category,
            enabled_default=description.entity_registry_enabled_default,
            visible_default=description.entity_registry_visible_default,
            graphable=_is_graphable(description),
            applicability=_sensor_applicability_label(description.key),
        )
        for description in sensor.SENSOR_DESCRIPTIONS
    )
    rows.extend(
        _description_row(
            "binary_sensor",
            description.key,
            description.name_suffix,
            tier=description.entity_tier,
            entity_category=description.entity_category,
            enabled_default=description.entity_registry_enabled_default,
            visible_default=description.entity_registry_visible_default,
            graphable=False,
            applicability=_binary_sensor_applicability_label(description.key),
        )
        for description in binary_sensor.BINARY_SENSOR_DESCRIPTIONS
    )
    rows.extend(
        _description_row(
            "button",
            description.key,
            description.name_suffix,
            tier=None,
            entity_category=description.entity_category,
            enabled_default=description.entity_registry_enabled_default,
            visible_default=description.entity_registry_visible_default,
            graphable=False,
            applicability="daily control circuits",
        )
        for description in button.CIRCUIT_BUTTON_DESCRIPTIONS
    )
    rows.extend(
        _description_row(
            "select",
            description.key,
            description.name_suffix,
            tier=None,
            entity_category=description.entity_category,
            enabled_default=description.entity_registry_enabled_default,
            visible_default=description.entity_registry_visible_default,
            graphable=False,
            applicability="all configured circuits",
        )
        for description in select.CIRCUIT_SELECT_DESCRIPTIONS
    )
    rows.extend(
        _description_row(
            "number",
            description.key,
            description.name_suffix,
            tier=None,
            entity_category=description.entity_category,
            enabled_default=description.entity_registry_enabled_default,
            visible_default=description.entity_registry_visible_default,
            graphable=False,
            applicability="circuits with usable cumulative energy evidence",
        )
        for description in number.CIRCUIT_NUMBER_DESCRIPTIONS
    )
    return rows


def global_entity_rows() -> list[dict[str, Any]]:
    """Return non per-circuit entities that are outside appliance counts."""
    return [
        {
            "domain": "sensor",
            "key": sensor.SETUP_HEALTH_ENTITY_KEY,
            "name": sensor.SETUP_HEALTH_ENTITY_NAME,
            "unique_id_pattern": "{entry_id}_setup_health",
            "suggested_object_id": sensor.SETUP_HEALTH_SUGGESTED_OBJECT_ID,
            "notes": "integration-wide setup health sensor",
        },
        *(
            {
                "domain": "button",
                "key": description.key,
                "name": description.name,
                "unique_id_pattern": f"{{entry_id}}_{description.key}",
                "suggested_object_id": (
                    f"circuitsetup_energy_analyzer_{description.key}"
                ),
                "notes": "integration-wide action button",
            }
            for description in button.GLOBAL_BUTTON_DESCRIPTIONS
        ),
        {
            "domain": "select",
            "key": "entity_detail_level",
            "name": "CircuitSetup Energy Analyzer Entity Detail Level",
            "unique_id_pattern": "{entry_id}_entity_detail_level",
            "suggested_object_id": (
                "circuitsetup_energy_analyzer_entity_detail_level"
            ),
            "notes": "integration-wide detail profile control",
        },
        {
            "domain": "select",
            "key": "dashboard_layout",
            "name": "CircuitSetup Energy Analyzer Dashboard Layout",
            "unique_id_pattern": "{entry_id}_dashboard_layout",
            "suggested_object_id": "circuitsetup_energy_analyzer_dashboard_layout",
            "notes": "integration-wide recommended-dashboard layout control",
        },
    ]


def _scenario_report(
    definition: ScenarioDefinition,
    all_definitions: Iterable[ScenarioDefinition],
) -> dict[str, Any]:
    variants = {
        variant: _variant_report(definition, variant, all_definitions)
        for variant in CONFIGURATION_VARIANTS
    }
    default_variant = variants["all_applicable_optional_settings"]
    return {
        "scenario_id": definition.scenario_id,
        "appliance_profile": definition.profile.value,
        "mode": definition.mode.value,
        "variants": variants,
        "detail_levels": default_variant["detail_levels"],
    }


def _variant_report(
    definition: ScenarioDefinition,
    variant: str,
    all_definitions: Iterable[ScenarioDefinition],
) -> dict[str, Any]:
    circuit = _circuit_for_variant(definition, variant)
    configured_circuits = tuple(
        _circuit_for_variant(item, variant)
        for item in all_definitions
    )
    coordinator = _coordinator_for(circuit, configured_circuits, variant)
    rows = _entity_rows_for_circuit(circuit, coordinator, configured_circuits)
    return {
        "circuit_id": circuit.circuit_id,
        "configuration": variant,
        "source_roles": [sensor_ref.role.value for sensor_ref in circuit.sensors],
        "detail_levels": {
            detail_level: _detail_level_summary(rows, detail_level)
            for detail_level in DETAIL_LEVELS
        },
    }


def _entity_rows_for_circuit(
    circuit: CircuitConfig,
    coordinator: Any,
    configured_circuits: tuple[CircuitConfig, ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend(
        _current_entity_row(
            "sensor",
            circuit,
            description.key,
            description.name_suffix,
            tier=description.entity_tier,
            enabled_default=description.entity_registry_enabled_default,
            visible_default=description.entity_registry_visible_default,
            applies=sensor.sensor_description_applies(
                description,
                circuit,
                coordinator,
                configured_circuits,
            ),
        )
        for description in sensor.SENSOR_DESCRIPTIONS
    )
    rows.extend(
        _current_entity_row(
            "binary_sensor",
            circuit,
            description.key,
            description.name_suffix,
            tier=description.entity_tier,
            enabled_default=description.entity_registry_enabled_default,
            visible_default=description.entity_registry_visible_default,
            applies=binary_sensor.binary_sensor_description_applies(
                description,
                circuit,
                coordinator,
            ),
        )
        for description in binary_sensor.BINARY_SENSOR_DESCRIPTIONS
    )
    rows.extend(
        _current_entity_row(
            "button",
            circuit,
            description.key,
            description.name_suffix,
            tier=None,
            enabled_default=description.entity_registry_enabled_default,
            visible_default=description.entity_registry_visible_default,
            applies=button.button_description_applies(
                description,
                circuit,
                coordinator,
            ),
            control=True,
        )
        for description in button.CIRCUIT_BUTTON_DESCRIPTIONS
    )
    rows.extend(
        _current_entity_row(
            "select",
            circuit,
            description.key,
            description.name_suffix,
            tier=None,
            enabled_default=description.entity_registry_enabled_default,
            visible_default=description.entity_registry_visible_default,
            applies=select.select_description_applies(
                description,
                circuit,
                coordinator,
            ),
            control=True,
        )
        for description in select.CIRCUIT_SELECT_DESCRIPTIONS
    )
    rows.extend(
        _current_entity_row(
            "number",
            circuit,
            description.key,
            description.name_suffix,
            tier=None,
            enabled_default=description.entity_registry_enabled_default,
            visible_default=description.entity_registry_visible_default,
            applies=number.number_description_applies(
                description,
                circuit,
                coordinator,
            ),
            control=True,
        )
        for description in number.CIRCUIT_NUMBER_DESCRIPTIONS
    )
    return rows


def _detail_level_summary(
    rows: list[dict[str, Any]],
    detail_level: str,
) -> dict[str, Any]:
    created = [row for row in rows if row["created"]]
    enabled = [row for row in created if _row_enabled(row, detail_level)]
    disabled = [row for row in created if row not in enabled]
    hidden = [row for row in created if _row_hidden(row, detail_level)]
    available = [row for row in enabled if row not in hidden]
    not_created = [row for row in rows if not row["created"]]
    return {
        "created": _bucket(created),
        "enabled": _bucket(enabled),
        "disabled": _bucket(disabled),
        "hidden": _bucket(hidden),
        "available": _bucket(available),
        "not_created": _bucket(not_created),
        "summary_entities": _bucket(
            row for row in created if row["tier"] == EntityTier.SUMMARY.value
        ),
        "feature_entities": _bucket(
            row for row in created if row["tier"] == EntityTier.FEATURE.value
        ),
        "diagnostic_entities": _bucket(
            row for row in created if row["tier"] == EntityTier.DIAGNOSTIC.value
        ),
        "controls": _bucket(row for row in created if row["control"]),
    }


def _bucket(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(rows)
    counts = {
        domain: 0
        for domain in (
            "sensor",
            "binary_sensor",
            "button",
            "select",
            "number",
            "switch",
        )
    }
    for row in items:
        counts[row["domain"]] = counts.get(row["domain"], 0) + 1
    return {
        **counts,
        "total": len(items),
        "entity_ids": [row["entity_id"] for row in items],
    }


def _row_enabled(row: Mapping[str, Any], detail_level: str) -> bool:
    if row["tier"]:
        return entity_enabled_default_for_tier(EntityTier(row["tier"]), detail_level)
    return bool(row["enabled_default"])


def _row_hidden(row: Mapping[str, Any], detail_level: str) -> bool:
    if detail_level == ENTITY_DETAIL_EXPERT:
        return False
    return not bool(row["visible_default"])


def _description_row(
    domain: str,
    key: str,
    name_suffix: str,
    *,
    tier: EntityTier | None,
    entity_category: Any,
    enabled_default: bool,
    visible_default: bool,
    graphable: bool,
    applicability: str,
) -> dict[str, Any]:
    compact_rule = compact_creation_rule_for_entity(domain, key)
    replacement = compact_rule.replacement
    return {
        "domain": domain,
        "key": key,
        "name_suffix": name_suffix,
        "unique_id_suffix": key,
        "unique_id_pattern": f"{{entry_id}}_{{circuit_id}}_{key}",
        "tier": tier.value if tier else None,
        "category": _category_value(entity_category),
        "enabled_default": enabled_default,
        "visible_default": visible_default,
        "expected_update_frequency": _expected_update_frequency(domain),
        "graphable": graphable,
        "applicability": applicability,
        "current_tests": _current_tests_for(domain, key),
        "duplicated_by_or_replaced_with": replacement,
        "compact_exposure": compact_rule.exposure.value,
        "compact_group": compact_rule.group.value,
    }


def _current_entity_row(
    domain: str,
    circuit: CircuitConfig,
    key: str,
    name_suffix: str,
    *,
    tier: EntityTier | None,
    enabled_default: bool,
    visible_default: bool,
    applies: bool,
    control: bool = False,
) -> dict[str, Any]:
    return {
        "domain": domain,
        "key": key,
        "name": f"{circuit.name} {name_suffix}",
        "entity_id": f"{domain}.{circuit.circuit_id}_{key}",
        "unique_id": f"{{entry_id}}_{circuit.circuit_id}_{key}",
        "tier": tier.value if tier else None,
        "enabled_default": enabled_default,
        "visible_default": visible_default,
        "control": control,
        "created": applies,
    }


def _is_graphable(description: Any) -> bool:
    return bool(
        getattr(description, "state_class", None)
        or getattr(description, "native_unit_of_measurement", None)
    )


def _category_value(entity_category: Any) -> str | None:
    if entity_category is None:
        return None
    return str(getattr(entity_category, "value", entity_category))


def _sensor_applicability_label(key: str) -> str:
    groups = (
        ("core/diagnostic baseline", sensor._CORE_SENSOR_KEYS),
        ("energy source", sensor._ENERGY_USAGE_SENSOR_KEYS),
        ("configured energy goal", sensor._ENERGY_GOAL_SENSOR_KEYS),
        ("electrical metric roles", sensor._POWER_QUALITY_SENSOR_KEYS),
        ("mains NILM circuit", sensor._MAINS_NILM_SENSOR_KEYS),
        ("cyclic appliance with power/current", sensor._RUN_CYCLE_SENSOR_KEYS),
        ("mains/high-power demand context", sensor._DEMAND_SENSOR_KEYS),
        ("configured capacity settings", sensor._CAPACITY_SENSOR_KEYS),
        ("dual-phase circuit", sensor._SPLIT_PHASE_SENSOR_KEYS),
        ("metric consistency context", sensor._METRIC_CONSISTENCY_SENSOR_KEYS),
        ("mains balance context", sensor._BALANCE_SENSOR_KEYS),
        ("mains with solar-flow source", sensor._SOLAR_FLOW_SENSOR_KEYS),
        ("utility comparison settings", sensor._UTILITY_COMPARISON_SENSOR_KEYS),
        ("billing settings and energy source", sensor._BILLING_SENSOR_KEYS),
        ("cost settings and energy source", sensor._COST_SENSOR_KEYS),
        ("standby-capable load", sensor._STANDBY_SENSOR_KEYS),
        ("HVAC profile with temperature source", sensor._WEATHER_CONTEXT_SENSOR_KEYS),
        ("pump profile with rain source", sensor._RAIN_PUMP_CONTEXT_SENSOR_KEYS),
        ("water profile with flow source", sensor._WATER_FLOW_CONTEXT_SENSOR_KEYS),
    )
    for label, keys in groups:
        if key in keys:
            return label
    if key in {
        "reactive_power_drift",
        "apparent_power_drift",
        "power_factor_drift",
    }:
        return "matching drift metric role"
    return "not created by current applicability rules"


def _binary_sensor_applicability_label(key: str) -> str:
    if key == "running":
        return "supported appliance profile with real power"
    if key == "water_flow_mismatch":
        return "water profile with global or linked flow source"
    return "all configured circuits"


def _expected_update_frequency(domain: str) -> str:
    if domain in {"sensor", "binary_sensor"}:
        return "coordinator update"
    return "user action"


def _current_tests_for(domain: str, key: str) -> str:
    if domain == "sensor":
        if key in {
            "health_summary",
            "activity_summary",
            "electrical_health",
            "energy_summary",
        }:
            return "tests/test_entities.py summary helper and attribute tests"
        if key in {"weather_context", "outdoor_temperature"}:
            return "tests/test_entities.py weather context applicability tests"
        if key in {
            "run_cycle_count",
            "run_cycle_runtime",
            "run_cycle_duty_cycle",
            "run_cycle_status",
        }:
            return (
                "tests/test_entities.py helper tests; "
                "tests/test_processors.py cycle tests"
            )
        return "tests/test_entities.py description, helper, and applicability tests"
    if domain == "binary_sensor":
        return "tests/test_entities.py binary defaults/applicability tests"
    if domain in {"button", "select", "number"}:
        return "tests/test_control_entities.py control setup tests"
    return "tests/test_entities.py"


def _scenario_definitions() -> tuple[ScenarioDefinition, ...]:
    return (
        ScenarioDefinition("refrigerator", ApplianceProfile.REFRIGERATOR),
        ScenarioDefinition("washer", ApplianceProfile.WASHER),
        ScenarioDefinition(
            "dryer_dual_phase",
            ApplianceProfile.DRYER,
            mode=CircuitMode.DUAL_PHASE,
        ),
        ScenarioDefinition("hvac", ApplianceProfile.HVAC, mode=CircuitMode.DUAL_PHASE),
        ScenarioDefinition("water_heater", ApplianceProfile.WATER_HEATER),
        ScenarioDefinition(
            "ev_charger",
            ApplianceProfile.EV_CHARGER,
            mode=CircuitMode.DUAL_PHASE,
        ),
        ScenarioDefinition("sump_pump_with_rain", ApplianceProfile.SUMP_PUMP),
        ScenarioDefinition("water_pump_with_flow", ApplianceProfile.WATER_PUMP),
        ScenarioDefinition(
            "solar_inverter",
            ApplianceProfile.SOLAR_INVERTER,
            power_flow=PowerFlowMode.GENERATION,
            minimal_roles=(SensorRole.REAL_POWER, SensorRole.ENERGY),
            full_roles=(SensorRole.REAL_POWER, SensorRole.ENERGY),
        ),
        ScenarioDefinition(
            "mains_nilm",
            ApplianceProfile.MAINS_NILM,
            mode=CircuitMode.MAINS_NILM,
        ),
        ScenarioDefinition(
            "mixed_circuit",
            ApplianceProfile.MIXED,
            mode=CircuitMode.MIXED,
        ),
    )


def _circuit_for_variant(
    definition: ScenarioDefinition,
    variant: str,
) -> CircuitConfig:
    roles = (
        definition.minimal_roles
        if variant == "minimal_sources"
        else definition.full_roles
    )
    optional = variant == "all_applicable_optional_settings"
    return CircuitConfig(
        circuit_id=definition.scenario_id,
        name=definition.scenario_id.replace("_", " ").title(),
        appliance_profile=definition.profile,
        mode=definition.mode,
        power_flow=definition.power_flow,
        sensors=tuple(_sensor_ref(definition.scenario_id, role) for role in roles),
        daily_energy_goal_kwh=4.0 if optional and SensorRole.ENERGY in roles else None,
        billing_cycle_budget_kwh=(
            120.0 if optional and SensorRole.ENERGY in roles else None
        ),
        default_rate_per_kwh=0.2 if optional and SensorRole.ENERGY in roles else None,
        always_on_alert_w=20.0 if optional else None,
    )


def _sensor_ref(circuit_id: str, role: SensorRole) -> SensorRef:
    return SensorRef(f"sensor.{circuit_id}_{role.value}", role)


def _coordinator_for(
    circuit: CircuitConfig,
    configured_circuits: tuple[CircuitConfig, ...],
    variant: str,
) -> Any:
    circuit_id = circuit.circuit_id
    optional = variant == "all_applicable_optional_settings"
    store_data = SimpleNamespace(
        energy_goal_settings_by_circuit=(
            {circuit_id: {"daily_goal_kwh": 4.0}}
            if optional and _has_role(circuit, SensorRole.ENERGY)
            else {}
        ),
        capacity_settings_by_circuit=(
            {circuit_id: {"breaker_amps": 40}}
            if optional and _uses_capacity_settings(circuit)
            else {}
        ),
        billing_settings_by_circuit=(
            {circuit_id: {"billing_cycle_budget_kwh": 120.0}} if optional else {}
        ),
        cost_settings_by_circuit=(
            {circuit_id: {"default_rate_per_kwh": 0.2}} if optional else {}
        ),
        standby_settings_by_circuit=(
            {circuit_id: {"standby_threshold_w": 8.0}} if optional else {}
        ),
        utility_comparison_settings_by_circuit=(
            {circuit_id: {"enabled": True}}
            if optional and circuit.mode is CircuitMode.MAINS_NILM
            else {}
        ),
    )
    options = {CONF_ENTITY_DETAIL_LEVEL: ENTITY_DETAIL_SIMPLE}
    if optional:
        options.update(
            {
                CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.outdoor_temperature",
                CONF_RAIN_SENSOR_ENTITY: "binary_sensor.rain_detected",
                CONF_WATER_FLOW_SENSOR_ENTITIES: ["sensor.water_flow"],
            },
        )
    return SimpleNamespace(
        data=AnalyzerState(),
        circuit_configs=configured_circuits,
        options=options,
        entry_data={},
        store_data=store_data,
    )


def _has_role(circuit: CircuitConfig, role: SensorRole) -> bool:
    return any(sensor_ref.role is role for sensor_ref in circuit.sensors)


def _uses_capacity_settings(circuit: CircuitConfig) -> bool:
    return circuit.appliance_profile in {
        ApplianceProfile.HVAC,
        ApplianceProfile.ELECTRIC_HEAT,
        ApplianceProfile.WATER_HEATER,
        ApplianceProfile.EV_CHARGER,
        ApplianceProfile.MAINS_NILM,
    }
