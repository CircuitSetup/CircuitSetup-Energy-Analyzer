from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import MappingProxyType, SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.activity_alerts import (
    ActivityAlertSettings,
)
from custom_components.circuitsetup_energy_analyzer.alerting import Observation
from custom_components.circuitsetup_energy_analyzer.balance import (
    DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W,
)
from custom_components.circuitsetup_energy_analyzer.billing import BillingCycleSettings
from custom_components.circuitsetup_energy_analyzer.capacity import CapacitySettings
from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_ADVANCED_SETTINGS,
    CONF_BLOWER_REPRESENTS_GAS_HEAT,
    CONF_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT,
    CONF_LINKED_THERMOSTAT_ENTITIES,
    CONF_THERMOSTAT_ENTITIES,
    CONF_THERMOSTAT_TEMPERATURE_SENSOR_ENTITIES,
    CONF_THERMOSTAT_TEMPERATURE_SENSOR_MAP,
    DEFAULT_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT,
    DOMAIN,
)
from custom_components.circuitsetup_energy_analyzer.cost import CostSettings
from custom_components.circuitsetup_energy_analyzer.demand import DemandSettings
from custom_components.circuitsetup_energy_analyzer.goals import EnergyGoalSettings
from custom_components.circuitsetup_energy_analyzer.hvac_efficiency import (
    HvacResponseEpisode,
    ThermostatObservation,
    episode_to_dict,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    ApplianceProfile,
    BaselineStats,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    CircuitSample,
    EventType,
    PowerFlowMode,
    SensorRef,
    SensorRole,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.normalize import (
    NormalizedCircuitSample,
)
from custom_components.circuitsetup_energy_analyzer.phase_balance import (
    DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
    DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
)
from custom_components.circuitsetup_energy_analyzer.standby import StandbySettings
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData
from custom_components.circuitsetup_energy_analyzer.usage import (
    EnergyUsageSettings,
    record_energy_usage,
)
from custom_components.circuitsetup_energy_analyzer.utility_comparison import (
    UtilityComparisonSettings,
)


def _sample(seconds: int, watts: float) -> CircuitSample:
    return CircuitSample(
        timestamp=datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
        + timedelta(seconds=seconds),
        circuit_id="fridge",
        real_power=watts,
        current=1.0,
        voltage=120.0,
        reactive_power=0.0,
        apparent_power=abs(watts),
        power_factor=1.0,
        frequency=60.0,
        energy=0.0,
    )


def _energy_sample(energy_kwh: float) -> CircuitSample:
    return CircuitSample(
        timestamp=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
        circuit_id="fridge",
        real_power=180.0,
        current=1.5,
        voltage=120.0,
        reactive_power=20.0,
        apparent_power=181.1,
        power_factor=0.99,
        frequency=60.0,
        energy=energy_kwh,
    )


def _hvac_context(
    *,
    configs: tuple[CircuitConfig, ...],
    observation: ThermostatObservation,
    advanced_settings: dict[str, dict[str, object]],
    running_circuit_ids: set[str],
) -> object:
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    state = SimpleNamespace(
        operating_state_snapshot_by_circuit={
            config.circuit_id: {
                "state": (
                    "running"
                    if config.circuit_id in running_circuit_ids
                    else "off"
                ),
                "stable_state": (
                    "running" if config.circuit_id in running_circuit_ids else "off"
                ),
            }
            for config in configs
        },
        hvac_current_episode_by_stream={},
        hvac_correlation_active_by_pair={},
        hvac_efficiency_by_circuit={},
        weather_context_by_circuit={
            config.circuit_id: {
                "temperature_f": 92.0,
                "temperature_bin": "very_hot",
                "mode": "cooling",
            }
            for config in configs
        },
    )
    observations = {
        f"{config.circuit_id}|{observation.thermostat_entity_id}": observation
        for config in configs
    }
    return ProcessingContext(
        now=datetime(2026, 7, 29, 12, tzinfo=UTC),
        hass=SimpleNamespace(),
        state=state,
        store_data=FeatureStoreData(),
        options={CONF_ADVANCED_SETTINGS: advanced_settings},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="balanced",
        time_zone="UTC",
        thermostat_observations=MappingProxyType(observations),
    )


def _hvac_config(circuit_id: str, profile: ApplianceProfile) -> CircuitConfig:
    return CircuitConfig(
        circuit_id=circuit_id,
        name=circuit_id.replace("_", " ").title(),
        appliance_profile=profile,
        mode=(
            CircuitMode.SINGLE_PHASE
            if profile is ApplianceProfile.HVAC_BLOWER
            else CircuitMode.DUAL_PHASE
        ),
    )


def _state_update_values(result: object, root: str) -> dict[str, object]:
    return {
        update.path[-1]: update.value
        for update in result.state_updates
        if update.path[0] == root
    }


def test_hvac_efficiency_attributes_cooling_to_driver_not_blower() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    ac = _hvac_config("ac", ApplianceProfile.HVAC_COMPRESSOR)
    blower = _hvac_config("blower", ApplianceProfile.HVAC_BLOWER)
    configs = (ac, blower)
    linked = {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
    context = _hvac_context(
        configs=configs,
        observation=ThermostatObservation(
            thermostat_entity_id=thermostat,
            temperature_entity_id=None,
            actual_temperature_f=78.0,
            target_temperature_f=72.0,
            mode="cool",
            action="cooling",
            available_capabilities=(
                "current_temperature",
                "temperature",
                "hvac_action",
            ),
        ),
        advanced_settings={"ac": linked, "blower": linked},
        running_circuit_ids={"ac", "blower"},
    )

    result = HvacEfficiencyProcessor().process(
        [(config, SimpleNamespace()) for config in configs],
        context,
    )
    episodes = _state_update_values(
        result,
        "hvac_current_episode_by_stream",
    )

    assert episodes["ac|climate.downstairs|cooling"][
        "participant_signature"
    ] == ["ac"]
    assert episodes["ac|climate.downstairs|cooling"][
        "supporting_blower_ids"
    ] == ["blower"]
    assert episodes["ac|climate.downstairs|cooling"]["attribution"] == "direct"
    assert not any(key.startswith("blower|") for key in episodes)


def test_hvac_efficiency_attributes_assisted_and_gas_heat() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    observation = ThermostatObservation(
        thermostat_entity_id=thermostat,
        temperature_entity_id=None,
        actual_temperature_f=65.0,
        target_temperature_f=70.0,
        mode="heat",
        action="heating",
        available_capabilities=(
            "current_temperature",
            "temperature",
            "hvac_action",
        ),
    )
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    electric_heat = _hvac_config(
        "electric_heat",
        ApplianceProfile.ELECTRIC_HEAT,
    )
    linked = {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
    assisted_context = _hvac_context(
        configs=(heat_pump, electric_heat),
        observation=observation,
        advanced_settings={
            "heat_pump": linked,
            "electric_heat": linked,
        },
        running_circuit_ids={"heat_pump", "electric_heat"},
    )

    assisted = HvacEfficiencyProcessor().process(
        [
            (heat_pump, SimpleNamespace()),
            (electric_heat, SimpleNamespace()),
        ],
        assisted_context,
    )
    assisted_episodes = _state_update_values(
        assisted,
        "hvac_current_episode_by_stream",
    )
    for circuit_id in ("heat_pump", "electric_heat"):
        episode = assisted_episodes[
            f"{circuit_id}|climate.downstairs|heating"
        ]
        assert episode["participant_signature"] == [
            "electric_heat",
            "heat_pump",
        ]
        assert episode["attribution"] == "assisted_system"

    blower = _hvac_config("blower", ApplianceProfile.HVAC_BLOWER)
    gas_context = _hvac_context(
        configs=(blower,),
        observation=observation,
        advanced_settings={
            "blower": {
                CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat],
                CONF_BLOWER_REPRESENTS_GAS_HEAT: True,
            }
        },
        running_circuit_ids={"blower"},
    )
    gas = HvacEfficiencyProcessor().process(
        [(blower, SimpleNamespace())],
        gas_context,
    )
    gas_episode = _state_update_values(
        gas,
        "hvac_current_episode_by_stream",
    )["blower|climate.downstairs|heating"]
    assert gas_episode["participant_signature"] == ["blower"]
    assert gas_episode["attribution"] == "gas_furnace_proxy"


def test_hvac_efficiency_tracks_multiple_thermostats_with_weather_context() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    mini_split = _hvac_config("mini_split", ApplianceProfile.MINI_SPLIT)
    downstairs = ThermostatObservation(
        "climate.downstairs",
        None,
        78.0,
        72.0,
        "cool",
        "cooling",
        ("current_temperature", "temperature", "hvac_action"),
    )
    upstairs = ThermostatObservation(
        "climate.upstairs",
        None,
        65.0,
        70.0,
        "heat",
        "heating",
        ("current_temperature", "temperature", "hvac_action"),
    )
    context = _hvac_context(
        configs=(mini_split,),
        observation=downstairs,
        advanced_settings={
            "mini_split": {
                CONF_LINKED_THERMOSTAT_ENTITIES: [
                    downstairs.thermostat_entity_id,
                    upstairs.thermostat_entity_id,
                ]
            }
        },
        running_circuit_ids={"mini_split"},
    )
    context = replace(
        context,
        thermostat_observations=MappingProxyType(
            {
                f"mini_split|{downstairs.thermostat_entity_id}": downstairs,
                f"mini_split|{upstairs.thermostat_entity_id}": upstairs,
            }
        ),
    )

    result = HvacEfficiencyProcessor().process(
        [(mini_split, SimpleNamespace())],
        context,
    )
    episodes = _state_update_values(result, "hvac_current_episode_by_stream")

    assert set(episodes) == {
        "mini_split|climate.downstairs|cooling",
        "mini_split|climate.upstairs|heating",
    }
    assert {episode["mode"] for episode in episodes.values()} == {
        "cooling",
        "heating",
    }
    for episode in episodes.values():
        assert episode["outdoor_temperature_f"] == 92.0
        assert episode["temperature_bin"] == "very_hot"
        assert episode["weather_mode"] == "cooling"
        assert episode["season"] == "summer"


def test_hvac_efficiency_caps_completed_history() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    linked = {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
    starting = ThermostatObservation(
        thermostat,
        "sensor.downstairs_temperature",
        78.0,
        72.0,
        "cool",
        "cooling",
        (
            "current_temperature",
            "temperature",
            "temperature_override",
            "hvac_action",
        ),
    )
    context = _hvac_context(
        configs=(heat_pump,),
        observation=starting,
        advanced_settings={"heat_pump": linked},
        running_circuit_ids={"heat_pump"},
    )
    processor = HvacEfficiencyProcessor()
    first = processor.process([(heat_pump, SimpleNamespace())], context)
    stream_id = "heat_pump|climate.downstairs|cooling"
    context.state.hvac_current_episode_by_stream[stream_id] = (
        _state_update_values(first, "hvac_current_episode_by_stream")[stream_id]
    )
    context.store_data.hvac_response_history_by_stream[stream_id] = [
        {"marker": index} for index in range(256)
    ]
    completed = replace(
        starting,
        actual_temperature_f=72.4,
    )
    context = replace(
        context,
        now=context.now + timedelta(minutes=12),
        thermostat_observations=MappingProxyType(
            {f"heat_pump|{thermostat}": completed}
        ),
    )

    result = processor.process([(heat_pump, SimpleNamespace())], context)
    history = context.store_data.hvac_response_history_by_stream[stream_id]

    assert result.store_dirty is True
    assert len(history) == 1
    assert history[-1]["complete"] is True
    assert history[-1]["temperature_entity_id"] == (
        "sensor.downstairs_temperature"
    )


def test_hvac_efficiency_stores_completed_subdegree_thermostat_call() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.upstairs"
    compressor = _hvac_config("ac2", ApplianceProfile.HVAC_COMPRESSOR)
    linked = {
        CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat],
        CONF_THERMOSTAT_TEMPERATURE_SENSOR_MAP: {
            thermostat: "sensor.upstairs_temperature"
        },
    }
    calling = ThermostatObservation(
        thermostat,
        "sensor.upstairs_temperature",
        75.8,
        75.2,
        "cool",
        "cooling",
        (
            "current_temperature",
            "temperature",
            "temperature_override",
            "hvac_action",
        ),
    )
    context = _hvac_context(
        configs=(compressor,),
        observation=calling,
        advanced_settings={"ac2": linked},
        running_circuit_ids={"ac2"},
    )
    processor = HvacEfficiencyProcessor()

    started = processor.process([(compressor, SimpleNamespace())], context)
    stream_id = f"ac2|{thermostat}|cooling"
    current_episode = _state_update_values(
        started,
        "hvac_current_episode_by_stream",
    )[stream_id]
    assert current_episode["episode_kind"] == "thermostat_call"
    context.state.hvac_current_episode_by_stream[stream_id] = current_episode
    recoveries = _hvac_response_history(
        stream_id,
        appliance_profile="hvac_compressor",
    )
    for recovery in recoveries:
        recovery["temperature_entity_id"] = "sensor.upstairs_temperature"
    context.store_data.hvac_response_history_by_stream[stream_id] = [
        *recoveries,
        *[
            {"marker": f"call-{index}", "episode_kind": "thermostat_call"}
            for index in range(256)
        ],
    ]

    context = replace(
        context,
        now=context.now + timedelta(minutes=20),
        thermostat_observations=MappingProxyType(
            {
                f"ac2|{thermostat}": replace(
                    calling,
                    actual_temperature_f=75.3,
                    action="idle",
                )
            }
        ),
    )
    context.state.operating_state_snapshot_by_circuit["ac2"] = {
        "state": "off",
        "stable_state": "off",
    }

    result = processor.process([(compressor, SimpleNamespace())], context)
    stored = context.store_data.hvac_response_history_by_stream[stream_id]
    payload = _state_update_values(
        result,
        "hvac_efficiency_by_circuit",
    )["ac2"]

    assert result.store_dirty is True
    assert len(stored) == 56
    assert stored[0]["episode_kind"] == "core_day"
    assert stored[-1]["complete"] is True
    assert stored[-1]["episode_kind"] == "thermostat_call"
    assert payload["streams"][stream_id]["status"] == "ready"


def test_hvac_efficiency_retains_excluded_call_as_same_day_marker() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    starting = ThermostatObservation(
        thermostat,
        None,
        78.0,
        72.0,
        "cool",
        "cooling",
        ("current_temperature", "temperature", "hvac_action"),
    )
    context = _hvac_context(
        configs=(heat_pump,),
        observation=starting,
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids={"heat_pump"},
    )
    processor = HvacEfficiencyProcessor()
    started = processor.process([(heat_pump, SimpleNamespace())], context)
    stream_id = f"heat_pump|{thermostat}|cooling"
    context.state.hvac_current_episode_by_stream[stream_id] = (
        _state_update_values(started, "hvac_current_episode_by_stream")[stream_id]
    )
    context = replace(
        context,
        now=context.now + timedelta(minutes=5),
        thermostat_observations=MappingProxyType(
            {
                f"heat_pump|{thermostat}": replace(
                    starting,
                    target_temperature_f=70.0,
                )
            }
        ),
    )

    processor.process([(heat_pump, SimpleNamespace())], context)
    marker = context.store_data.hvac_response_history_by_stream[stream_id][0]

    assert marker["complete"] is False
    assert marker["excluded_from_baseline"] is True


def test_hvac_instant_marker_deduplication_is_scoped_to_baseline_era() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            None,
            75.25,
            75.2,
            "cool",
            "cooling",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids={"heat_pump"},
    )
    stream_id = f"heat_pump|{thermostat}|cooling"
    processor = HvacEfficiencyProcessor()

    processor.process([(heat_pump, SimpleNamespace())], context)
    context.store_data.hvac_baseline_era_by_stream[stream_id] = "era-2"
    processor.process([(heat_pump, SimpleNamespace())], context)

    history = context.store_data.hvac_response_history_by_stream[stream_id]
    assert [raw["baseline_era"] for raw in history] == ["initial", "era-2"]


def test_hvac_instant_marker_deduplication_is_scoped_to_response_context() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    auxiliary = _hvac_config("auxiliary", ApplianceProfile.HVAC_COMPRESSOR)
    configs = (heat_pump, auxiliary)
    linked = {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
    context = _hvac_context(
        configs=configs,
        observation=ThermostatObservation(
            thermostat,
            None,
            75.25,
            75.2,
            "cool",
            "cooling",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={"heat_pump": linked, "auxiliary": linked},
        running_circuit_ids={"heat_pump"},
    )
    stream_id = f"heat_pump|{thermostat}|cooling"
    processor = HvacEfficiencyProcessor()

    processor.process([(config, SimpleNamespace()) for config in configs], context)
    context.state.operating_state_snapshot_by_circuit["auxiliary"] = {
        "state": "running",
        "stable_state": "running",
    }
    processor.process([(config, SimpleNamespace()) for config in configs], context)

    history = context.store_data.hvac_response_history_by_stream[stream_id]
    assert [raw["participant_signature"] for raw in history] == [
        ["heat_pump"],
        ["auxiliary", "heat_pump"],
    ]


@pytest.mark.parametrize(
    ("profile", "expected_modes"),
    [
        (ApplianceProfile.HVAC_COMPRESSOR, {"cooling"}),
        (ApplianceProfile.HEAT_PUMP, {"cooling", "heating"}),
    ],
)
@pytest.mark.parametrize(
    "actual_temperature_f",
    [None, 72.0],
    ids=["missing-actual", "exact-setpoint"],
)
def test_hvac_unresolved_auto_call_retains_excluded_date_marker(
    profile: ApplianceProfile,
    expected_modes: set[str],
    actual_temperature_f: float | None,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    driver = _hvac_config("driver", profile)
    blower = _hvac_config("blower", ApplianceProfile.HVAC_BLOWER)
    configs = (driver, blower)
    linked = {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
    context = _hvac_context(
        configs=configs,
        observation=ThermostatObservation(
            thermostat,
            None,
            actual_temperature_f,
            72.0,
            "heat_cool",
            None,
            ("current_temperature", "temperature"),
        ),
        advanced_settings={"driver": linked, "blower": linked},
        running_circuit_ids={"driver", "blower"},
    )

    result = HvacEfficiencyProcessor().process(
        [(config, SimpleNamespace()) for config in configs],
        context,
    )

    assert result.store_dirty is True
    history = context.store_data.hvac_response_history_by_stream
    assert {stream_id.rsplit("|", 1)[-1] for stream_id in history} == expected_modes
    for marker in (raw_history[0] for raw_history in history.values()):
        assert marker["complete"] is False
        assert marker["excluded_from_baseline"] is True
        assert marker["participant_signature"] == ["driver"]
        assert marker["supporting_blower_ids"] == ["blower"]


def test_hvac_efficiency_persists_orphaned_call_as_same_day_marker() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    calling = ThermostatObservation(
        thermostat,
        None,
        78.0,
        72.0,
        "cool",
        "cooling",
        ("current_temperature", "temperature", "hvac_action"),
    )
    context = _hvac_context(
        configs=(heat_pump,),
        observation=calling,
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids={"heat_pump"},
    )
    processor = HvacEfficiencyProcessor()
    started = processor.process([(heat_pump, SimpleNamespace())], context)
    stream_id = f"heat_pump|{thermostat}|cooling"
    context.state.hvac_current_episode_by_stream[stream_id] = (
        _state_update_values(started, "hvac_current_episode_by_stream")[stream_id]
    )
    context = replace(
        context,
        now=context.now + timedelta(minutes=5),
        thermostat_observations=MappingProxyType({}),
    )

    result = processor.process([(heat_pump, SimpleNamespace())], context)
    marker = context.store_data.hvac_response_history_by_stream[stream_id][0]

    assert result.store_dirty is True
    assert marker["ended_at"] == context.now.isoformat()
    assert marker["complete"] is False
    assert marker["excluded_from_baseline"] is True


def test_hvac_efficiency_finalizes_call_when_action_changes_direction() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    linked = {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
    cooling = ThermostatObservation(
        thermostat,
        "sensor.downstairs_temperature",
        75.8,
        75.2,
        "heat_cool",
        "cooling",
        ("current_temperature", "temperature", "hvac_action"),
    )
    context = _hvac_context(
        configs=(heat_pump,),
        observation=cooling,
        advanced_settings={"heat_pump": linked},
        running_circuit_ids={"heat_pump"},
    )
    processor = HvacEfficiencyProcessor()
    started = processor.process([(heat_pump, SimpleNamespace())], context)
    stream_id = f"heat_pump|{thermostat}|cooling"
    context.state.hvac_current_episode_by_stream[stream_id] = (
        _state_update_values(started, "hvac_current_episode_by_stream")[
            stream_id
        ]
    )
    context = replace(
        context,
        now=context.now + timedelta(minutes=20),
        thermostat_observations=MappingProxyType(
            {
                f"heat_pump|{thermostat}": replace(
                    cooling,
                    actual_temperature_f=75.3,
                    target_temperature_f=76.0,
                    action="heating",
                )
            }
        ),
    )

    result = processor.process([(heat_pump, SimpleNamespace())], context)
    completed = context.store_data.hvac_response_history_by_stream[stream_id][
        -1
    ]

    assert result.store_dirty is True
    assert completed["complete"] is True
    assert completed["mode"] == "cooling"
    assert completed["episode_kind"] == "thermostat_call"


@pytest.mark.parametrize(
    "profile",
    [ApplianceProfile.HEAT_PUMP, ApplianceProfile.HVAC_BLOWER],
)
def test_hvac_efficiency_completes_auto_episode_when_idle_in_deadband(
    profile: ApplianceProfile,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    circuit_id = (
        "blower"
        if profile is ApplianceProfile.HVAC_BLOWER
        else "heat_pump"
    )
    appliance = _hvac_config(circuit_id, profile)
    response_mode = (
        "heating"
        if profile is ApplianceProfile.HVAC_BLOWER
        else "cooling"
    )
    linked = {
        CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat],
        **(
            {CONF_BLOWER_REPRESENTS_GAS_HEAT: True}
            if profile is ApplianceProfile.HVAC_BLOWER
            else {}
        ),
    }
    starting = ThermostatObservation(
        thermostat,
        None,
        65.0 if response_mode == "heating" else 78.0,
        70.0 if response_mode == "heating" else 72.0,
        "heat_cool",
        response_mode,
        ("current_temperature", "temperature", "hvac_action"),
    )
    context = _hvac_context(
        configs=(appliance,),
        observation=starting,
        advanced_settings={circuit_id: linked},
        running_circuit_ids={circuit_id},
    )
    processor = HvacEfficiencyProcessor()
    started = processor.process([(appliance, SimpleNamespace())], context)
    stream_id = f"{circuit_id}|{thermostat}|{response_mode}"
    current_episode = dict(
        _state_update_values(started, "hvac_current_episode_by_stream")[
            stream_id
        ]
    )
    current_episode["active_minutes"] = 20.0
    context.state.hvac_current_episode_by_stream[stream_id] = current_episode
    completed = replace(
        starting,
        actual_temperature_f=(
            70.2 if response_mode == "heating" else 71.8
        ),
        target_temperature_f=None,
        action="idle",
    )
    context = replace(
        context,
        now=context.now + timedelta(minutes=30),
        thermostat_observations=MappingProxyType(
            {f"{circuit_id}|{thermostat}": completed}
        ),
    )
    context.state.operating_state_snapshot_by_circuit[circuit_id] = {
        "state": "off",
        "stable_state": "off",
    }

    result = processor.process([(appliance, SimpleNamespace())], context)

    assert stream_id in context.store_data.hvac_response_history_by_stream, (
        result.state_updates
    )
    assert context.store_data.hvac_response_history_by_stream[stream_id][0][
        "complete"
    ] is True
    assert _state_update_values(
        result,
        "hvac_current_episode_by_stream",
    )[stream_id] == {}


def test_hvac_correlation_history_learns_before_thermostat_link() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    temperature = "sensor.downstairs_temperature"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    calling = ThermostatObservation(
        thermostat,
        None,
        None,
        72.0,
        "cool",
        "cooling",
        ("temperature", "hvac_action"),
    )
    candidate = replace(
        calling,
        temperature_entity_id=temperature,
        actual_temperature_f=77.0,
        available_capabilities=(
            "temperature",
            "temperature_override",
            "hvac_action",
        ),
    )
    context = _hvac_context(
        configs=(heat_pump,),
        observation=calling,
        advanced_settings={"heat_pump": {}},
        running_circuit_ids={"heat_pump"},
    )
    context = replace(
        context,
        entry_data={
            CONF_THERMOSTAT_ENTITIES: [thermostat],
            CONF_THERMOSTAT_TEMPERATURE_SENSOR_ENTITIES: [temperature],
        },
        thermostat_observations=MappingProxyType(
            {
                thermostat: calling,
                f"candidate|{thermostat}|{temperature}": candidate,
            }
        ),
    )
    context.store_data.hvac_correlation_history_by_circuit["heat_pump"] = [
        {"marker": index} for index in range(256)
    ]
    processor = HvacEfficiencyProcessor()
    pair_id = f"heat_pump|{thermostat}"

    started = processor.process([(heat_pump, SimpleNamespace())], context)
    context.state.hvac_correlation_active_by_pair[pair_id] = (
        _state_update_values(started, "hvac_correlation_active_by_pair")[
            pair_id
        ]
    )
    context = replace(
        context,
        now=context.now + timedelta(minutes=18),
        thermostat_observations=MappingProxyType(
            {
                thermostat: calling,
                f"candidate|{thermostat}|{temperature}": replace(
                    candidate,
                    actual_temperature_f=74.0,
                ),
            }
        ),
    )
    active = processor.process([(heat_pump, SimpleNamespace())], context)
    context.state.hvac_correlation_active_by_pair[pair_id] = (
        _state_update_values(active, "hvac_correlation_active_by_pair")[
            pair_id
        ]
    )
    context = replace(
        context,
        now=context.now + timedelta(minutes=2),
        thermostat_observations=MappingProxyType(
            {
                thermostat: replace(calling, action="idle"),
                f"candidate|{thermostat}|{temperature}": replace(
                    candidate,
                    actual_temperature_f=72.5,
                    action="idle",
                ),
            }
        ),
    )
    context.state.operating_state_snapshot_by_circuit["heat_pump"] = {
        "state": "off",
        "stable_state": "off",
    }

    completed = processor.process([(heat_pump, SimpleNamespace())], context)
    calls = context.store_data.hvac_correlation_history_by_circuit["heat_pump"]
    call = calls[-1]

    response_markers = context.store_data.hvac_response_history_by_stream[
        f"heat_pump|{thermostat}|cooling"
    ]
    assert len(response_markers) == 1
    assert response_markers[0]["complete"] is False
    assert response_markers[0]["excluded_from_baseline"] is True
    assert completed.store_dirty is True
    assert len(calls) == 256
    assert calls[0]["marker"] == 1
    assert call["thermostat_entity_id"] == thermostat
    assert call["mode"] == call["driver_mode"] == "cooling"
    assert call["overlap_ratio"] == pytest.approx(1.0)
    assert call["temperature_entity_id"] == temperature
    assert call["candidate_moved_toward_target"] is True
    assert call["climate_has_current_temperature"] is False


def test_hvac_correlation_history_identifies_unlinked_gas_blower() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    blower = _hvac_config("blower", ApplianceProfile.HVAC_BLOWER)
    calling = ThermostatObservation(
        thermostat,
        None,
        65.0,
        70.0,
        "heat",
        "heating",
        ("current_temperature", "temperature", "hvac_action"),
    )
    context = _hvac_context(
        configs=(blower,),
        observation=calling,
        advanced_settings={"blower": {}},
        running_circuit_ids={"blower"},
    )
    context = replace(
        context,
        entry_data={CONF_THERMOSTAT_ENTITIES: [thermostat]},
        thermostat_observations=MappingProxyType({thermostat: calling}),
    )
    processor = HvacEfficiencyProcessor()
    pair_id = f"blower|{thermostat}"

    started = processor.process([(blower, SimpleNamespace())], context)
    context.state.hvac_correlation_active_by_pair[pair_id] = (
        _state_update_values(started, "hvac_correlation_active_by_pair")[
            pair_id
        ]
    )
    context = replace(context, now=context.now + timedelta(minutes=18))
    active = processor.process([(blower, SimpleNamespace())], context)
    context.state.hvac_correlation_active_by_pair[pair_id] = (
        _state_update_values(active, "hvac_correlation_active_by_pair")[
            pair_id
        ]
    )
    context = replace(
        context,
        now=context.now + timedelta(minutes=2),
        thermostat_observations=MappingProxyType(
            {thermostat: replace(calling, action="idle")}
        ),
    )
    context.state.operating_state_snapshot_by_circuit["blower"] = {
        "state": "off",
        "stable_state": "off",
    }

    processor.process([(blower, SimpleNamespace())], context)
    call = context.store_data.hvac_correlation_history_by_circuit["blower"][0]

    assert call["mode"] == call["driver_mode"] == "heating"
    assert call["overlap_ratio"] == pytest.approx(1.0)
    assert call["electrical_driver_present"] is False


def test_hvac_correlation_overlap_uses_prior_running_state() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    calling = ThermostatObservation(
        thermostat,
        None,
        78.0,
        72.0,
        "cool",
        "cooling",
        ("current_temperature", "temperature", "hvac_action"),
    )
    context = _hvac_context(
        configs=(heat_pump,),
        observation=calling,
        advanced_settings={"heat_pump": {}},
        running_circuit_ids=set(),
    )
    context = replace(
        context,
        entry_data={CONF_THERMOSTAT_ENTITIES: [thermostat]},
        thermostat_observations=MappingProxyType({thermostat: calling}),
    )
    processor = HvacEfficiencyProcessor()
    pair_id = f"heat_pump|{thermostat}"

    started = processor.process([(heat_pump, SimpleNamespace())], context)
    context.state.hvac_correlation_active_by_pair[pair_id] = (
        _state_update_values(started, "hvac_correlation_active_by_pair")[
            pair_id
        ]
    )
    context = replace(context, now=context.now + timedelta(minutes=5))
    context.state.operating_state_snapshot_by_circuit["heat_pump"] = {
        "state": "running",
        "stable_state": "running",
    }
    turned_on = processor.process([(heat_pump, SimpleNamespace())], context)
    context.state.hvac_correlation_active_by_pair[pair_id] = (
        _state_update_values(turned_on, "hvac_correlation_active_by_pair")[
            pair_id
        ]
    )
    context = replace(context, now=context.now + timedelta(minutes=20))
    active = processor.process([(heat_pump, SimpleNamespace())], context)
    context.state.hvac_correlation_active_by_pair[pair_id] = (
        _state_update_values(active, "hvac_correlation_active_by_pair")[
            pair_id
        ]
    )
    context = replace(
        context,
        now=context.now + timedelta(minutes=10),
        thermostat_observations=MappingProxyType(
            {thermostat: replace(calling, action="idle")}
        ),
    )
    context.state.operating_state_snapshot_by_circuit["heat_pump"] = {
        "state": "off",
        "stable_state": "off",
    }

    processor.process([(heat_pump, SimpleNamespace())], context)
    call = context.store_data.hvac_correlation_history_by_circuit["heat_pump"][
        0
    ]

    assert call["overlap_ratio"] == pytest.approx(30.0 / 35.0)


def test_hvac_efficiency_main_loop_uses_only_bounded_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket
    import urllib.request

    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("blocking I/O is forbidden in the HVAC processor")

    thermostat_ids = tuple(f"climate.zone_{index}" for index in range(32))
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    starting = {
        thermostat_id: ThermostatObservation(
            thermostat_id,
            None,
            78.0,
            72.0,
            "cool",
            "cooling",
            ("current_temperature", "temperature", "hvac_action"),
        )
        for thermostat_id in thermostat_ids
    }
    context = _hvac_context(
        configs=(heat_pump,),
        observation=next(iter(starting.values())),
        advanced_settings={
            "heat_pump": {
                CONF_LINKED_THERMOSTAT_ENTITIES: list(thermostat_ids)
            }
        },
        running_circuit_ids={"heat_pump"},
    )
    context = replace(
        context,
        hass=SimpleNamespace(
            states=SimpleNamespace(get=forbidden),
            async_add_executor_job=forbidden,
        ),
        thermostat_observations=MappingProxyType(
            {
                f"heat_pump|{thermostat_id}": observation
                for thermostat_id, observation in starting.items()
            }
        ),
    )
    processor = HvacEfficiencyProcessor()
    started = processor.process([(heat_pump, SimpleNamespace())], context)
    for update in started.state_updates:
        if update.path[0] == "hvac_current_episode_by_stream":
            context.state.hvac_current_episode_by_stream[update.path[-1]] = (
                update.value
            )
    for thermostat_id in thermostat_ids:
        stream_id = f"heat_pump|{thermostat_id}|cooling"
        context.store_data.hvac_response_history_by_stream[stream_id] = [
            {"marker": index} for index in range(256)
        ]

    completed = {
        f"heat_pump|{thermostat_id}": replace(
            observation,
            actual_temperature_f=72.4,
        )
        for thermostat_id, observation in starting.items()
    }
    context = replace(
        context,
        now=context.now + timedelta(minutes=12),
        thermostat_observations=MappingProxyType(completed),
    )
    with monkeypatch.context() as guards:
        guards.setattr("builtins.open", forbidden)
        guards.setattr(asyncio, "to_thread", forbidden)
        guards.setattr(socket, "create_connection", forbidden)
        guards.setattr(urllib.request, "urlopen", forbidden)
        result = processor.process([(heat_pump, SimpleNamespace())], context)

    histories = context.store_data.hvac_response_history_by_stream
    assert result.store_dirty is True
    assert len(histories) == len(thermostat_ids)
    assert max(len(history) for history in histories.values()) == 1
    assert all(
        history[-1]["thermostat_entity_id"] == thermostat_id
        for thermostat_id, history in (
            (
                stream_id.split("|")[1],
                stream_history,
            )
            for stream_id, stream_history in histories.items()
        )
    )


def test_hvac_efficiency_defaults_a_malformed_persisted_threshold() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat_id = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat_id,
            None,
            78.0,
            72.0,
            "cool",
            "cooling",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "heat_pump": {
                CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat_id],
                CONF_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT: "invalid",
            }
        },
        running_circuit_ids={"heat_pump"},
    )

    result = HvacEfficiencyProcessor().process(
        [(heat_pump, SimpleNamespace())],
        context,
    )
    payload = _state_update_values(
        result,
        "hvac_efficiency_by_circuit",
    )["heat_pump"]

    assert payload["threshold_pct"] == (
        DEFAULT_HVAC_EFFICIENCY_CHANGE_THRESHOLD_PCT
    )


def _hvac_response_history(
    stream_id: str,
    *,
    reference_rate: float = 10.0,
    recent_rate: float = 12.5,
    count: int = 55,
    appliance_profile: str = "heat_pump",
) -> list[dict[str, object]]:
    circuit_id, thermostat_id, mode = stream_id.split("|")
    history: list[dict[str, object]] = []
    for index in range(count):
        outdoor_temperature = 75.0 + 5.0 * (index % 5)
        baseline_runtime = 40.0 + 2.0 * (outdoor_temperature - 75.0)
        runtime_minutes = (
            baseline_runtime
            if index < 50
            else baseline_runtime * recent_rate / reference_rate
        )
        started = datetime(2026, 6, 1, 12, tzinfo=UTC) + timedelta(days=index)
        target = 72.0 if mode == "cooling" else 70.0
        start = 77.0 if mode == "cooling" else 65.0
        history.append(
            episode_to_dict(
                HvacResponseEpisode(
                    stream_id=stream_id,
                    circuit_id=circuit_id,
                    thermostat_entity_id=thermostat_id,
                    mode=mode,
                    started_at=started,
                    ended_at=started
                    + timedelta(minutes=runtime_minutes),
                    start_temperature_f=start,
                    target_temperature_f=target,
                    latest_temperature_f=target,
                    elapsed_minutes=runtime_minutes,
                    active_minutes=runtime_minutes,
                    outdoor_temperature_f=outdoor_temperature,
                    season="summer",
                    weather_mode=mode,
                    temperature_bin="very_hot",
                    gap_bin="4-6F",
                    participant_signature=(circuit_id,),
                    supporting_blower_ids=(),
                    complete=True,
                    appliance_profile=appliance_profile,
                    outdoor_temperature_minutes=runtime_minutes,
                )
            )
        )
    return history


def _set_hvac_history_multiplier(
    history: list[dict[str, object]],
    indexes: range,
    multiplier: float,
) -> None:
    for raw in history[indexes.start : indexes.stop]:
        outdoor = float(raw["outdoor_temperature_f"])
        runtime = (40.0 + 2.0 * (outdoor - 75.0)) * multiplier
        started = datetime.fromisoformat(str(raw["started_at"]))
        raw.update(
            elapsed_minutes=runtime,
            active_minutes=runtime,
            outdoor_temperature_minutes=runtime,
            ended_at=(started + timedelta(minutes=runtime)).isoformat(),
        )


@pytest.mark.parametrize("handoff_complete", [True, False])
def test_hvac_response_change_emits_mature_slower_alert(
    handoff_complete: bool,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            None,
            72.0,
            72.0,
            "cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids=set(),
    )
    stream_id = f"heat_pump|{thermostat}|cooling"
    context.store_data.hvac_response_history_by_stream[stream_id] = (
        _hvac_response_history(stream_id, recent_rate=12.5)
    )
    policy = ConservativeAlertPolicy(
        min_repeated=1,
        min_total_score=1.0,
        min_average_score=1.0,
        min_baseline_confidence=0.0,
    )

    processor = HvacEfficiencyProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy
    )
    result = processor.process([(heat_pump, SimpleNamespace())], context)

    assert [alert.feature for alert in result.alerts] == ["hvac_response_slower"]
    assert result.notifications == result.alerts
    assert result.alerts[0].severity is Severity.WARNING
    assert result.alerts[0].features["health_feature"] == (
        "hvac_thermostat_efficiency"
    )
    assert result.alerts[0].features["reference_core_day_count"] == 50
    assert result.alerts[0].features["recent_core_day_count"] == 5
    assert result.alerts[0].features["baseline_context"] == (
        "cooling, climate.downstairs, weather-normalized over 50 core days"
    )
    assert result.alerts[0].features["thermostat_entity_id"] == thermostat
    assert result.alerts[0].features["outdoor_temperature_f"] == 85.0
    evidence = _state_update_values(result, "hvac_efficiency_by_circuit")[
        "heat_pump"
    ]
    assert evidence["finding"] == "slower"
    assert evidence["score"] == pytest.approx(80.0)
    assert result.repairs == []
    context.state.active_alerts_by_circuit = {"heat_pump": result.alerts}
    duplicate = processor.process([(heat_pump, SimpleNamespace())], context)
    assert duplicate.alerts == duplicate.notifications == []
    assert duplicate.preserved_alerts == result.alerts

    changed_context = _hvac_response_history(stream_id, count=56)[-1]
    changed_context["participant_signature"] = ["heat_pump", "auxiliary"]
    changed_started = datetime.fromisoformat(str(changed_context["started_at"]))
    changed_context.update(
        ended_at=(changed_started + timedelta(minutes=10)).isoformat(),
        elapsed_minutes=10.0,
        active_minutes=10.0,
        outdoor_temperature_minutes=10.0,
        complete=handoff_complete,
        excluded_from_baseline=not handoff_complete,
    )
    context.store_data.hvac_response_history_by_stream[stream_id].append(
        changed_context
    )
    handoff = processor.process([(heat_pump, SimpleNamespace())], context)

    assert _state_update_values(
        handoff,
        "hvac_efficiency_by_circuit",
    )["heat_pump"]["streams"][stream_id]["status"] == "no_data"
    assert handoff.preserved_alerts == []


def test_hvac_incomplete_temperature_handoff_retires_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    old_temperature = "sensor.downstairs_temperature"
    replacement_temperature = "sensor.replacement_downstairs_temperature"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    linked = {
        CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat],
        CONF_THERMOSTAT_TEMPERATURE_SENSOR_MAP: {
            thermostat: old_temperature,
        },
    }
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            old_temperature,
            72.0,
            72.0,
            "cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={"heat_pump": linked},
        running_circuit_ids=set(),
    )
    stream_id = f"heat_pump|{thermostat}|cooling"
    history = _hvac_response_history(stream_id, recent_rate=12.5)
    for raw in history:
        raw["temperature_entity_id"] = old_temperature
    context.store_data.hvac_response_history_by_stream[stream_id] = history
    context.store_data.hvac_response_history_by_stream[
        "other|climate.upstairs|cooling"
    ] = []
    processor = HvacEfficiencyProcessor(
        alert_policy_for_circuit=lambda _circuit_id: ConservativeAlertPolicy(
            min_repeated=1,
            min_total_score=1.0,
            min_average_score=1.0,
            min_baseline_confidence=0.0,
        )
    )
    initial = processor.process([(heat_pump, SimpleNamespace())], context)
    assert initial.alerts
    context.state.active_alerts_by_circuit = {"heat_pump": initial.alerts}
    context = replace(
        context,
        options={
            CONF_ADVANCED_SETTINGS: {
                "heat_pump": {
                    **linked,
                    CONF_THERMOSTAT_TEMPERATURE_SENSOR_MAP: {
                        thermostat: replacement_temperature,
                    },
                }
            }
        },
    )
    configuration_handoff = processor.process(
        [(heat_pump, SimpleNamespace())], context
    )
    assert _state_update_values(
        configuration_handoff,
        "hvac_efficiency_by_circuit",
    )["heat_pump"]["streams"][stream_id]["status"] == "no_data"
    assert configuration_handoff.preserved_alerts == []

    context.state.active_alerts_by_circuit = {"heat_pump": initial.alerts}
    replacement = _hvac_response_history(stream_id, count=56)[-1]
    replacement_started = datetime.fromisoformat(str(replacement["started_at"]))
    replacement.update(
        temperature_entity_id=replacement_temperature,
        ended_at=(replacement_started + timedelta(minutes=10)).isoformat(),
        elapsed_minutes=10.0,
        active_minutes=10.0,
        outdoor_temperature_minutes=10.0,
        complete=False,
        excluded_from_baseline=True,
    )
    context.store_data.hvac_response_history_by_stream[stream_id].append(replacement)

    handoff = processor.process([(heat_pump, SimpleNamespace())], context)

    assert _state_update_values(
        handoff,
        "hvac_efficiency_by_circuit",
    )["heat_pump"]["streams"][stream_id]["status"] == "no_data"
    assert handoff.preserved_alerts == []


def test_hvac_profile_handoff_retires_alert_while_idle() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    linked = {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            None,
            72.0,
            72.0,
            "cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={"heat_pump": linked},
        running_circuit_ids=set(),
    )
    stream_id = f"heat_pump|{thermostat}|cooling"
    context.store_data.hvac_response_history_by_stream[stream_id] = (
        _hvac_response_history(stream_id, recent_rate=12.5)
    )
    processor = HvacEfficiencyProcessor(
        alert_policy_for_circuit=lambda _circuit_id: ConservativeAlertPolicy(
            min_repeated=1,
            min_total_score=1.0,
            min_average_score=1.0,
            min_baseline_confidence=0.0,
        )
    )
    initial = processor.process([(heat_pump, SimpleNamespace())], context)
    assert initial.alerts
    context.state.active_alerts_by_circuit = {"heat_pump": initial.alerts}
    compressor = replace(
        heat_pump,
        appliance_profile=ApplianceProfile.HVAC_COMPRESSOR,
    )

    handoff = processor.process([(compressor, SimpleNamespace())], context)

    assert _state_update_values(
        handoff,
        "hvac_efficiency_by_circuit",
    )["heat_pump"]["streams"][stream_id]["status"] == "no_data"
    assert handoff.preserved_alerts == []


def test_hvac_efficiency_matures_with_lightweight_retention() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            None,
            72.0,
            72.0,
            "cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids=set(),
    )
    stream_id = f"heat_pump|{thermostat}|cooling"
    context.store_data.hvac_response_history_by_stream[stream_id] = (
        _hvac_response_history(stream_id, count=17)
    )

    result = HvacEfficiencyProcessor(
        retention_days_for_circuit=lambda _circuit_id: 18
    ).process([(heat_pump, SimpleNamespace())], context)
    stream = _state_update_values(result, "hvac_efficiency_by_circuit")[
        "heat_pump"
    ]["streams"][stream_id]

    assert stream["status"] == "ready"
    assert stream["required_reference_count"] == 12
    assert stream["required_recent_count"] == 5


def test_hvac_faster_response_is_informational_only() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            None,
            72.0,
            72.0,
            "cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids=set(),
    )
    stream_id = f"heat_pump|{thermostat}|cooling"
    context.store_data.hvac_response_history_by_stream[stream_id] = (
        _hvac_response_history(stream_id, recent_rate=7.5)
    )
    result = HvacEfficiencyProcessor(
        alert_policy_for_circuit=lambda _circuit_id: ConservativeAlertPolicy(
            min_repeated=1,
            min_total_score=1.5,
            min_average_score=1.5,
            min_baseline_confidence=0.0,
        )
    ).process([(heat_pump, SimpleNamespace())], context)

    evidence = _state_update_values(result, "hvac_efficiency_by_circuit")[
        "heat_pump"
    ]
    assert evidence["finding"] == "faster"
    assert result.observations == result.alerts == result.notifications == []


def test_hvac_excludes_days_with_both_heating_and_cooling() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            None,
            72.0,
            72.0,
            "heat_cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids=set(),
    )
    cooling_stream = f"heat_pump|{thermostat}|cooling"
    heating_stream = f"heat_pump|{thermostat}|heating"
    context.store_data.hvac_response_history_by_stream[cooling_stream] = (
        _hvac_response_history(cooling_stream, recent_rate=12.5)
    )
    context.store_data.hvac_response_history_by_stream[heating_stream] = (
        _hvac_response_history(heating_stream)[-5:]
    )

    result = HvacEfficiencyProcessor().process(
        [(heat_pump, SimpleNamespace())],
        context,
    )
    evidence = _state_update_values(result, "hvac_efficiency_by_circuit")[
        "heat_pump"
    ]

    assert evidence["streams"][cooling_stream]["status"] == "provisional"
    assert evidence["finding"] is None
    assert result.notifications == []


def test_hvac_mixed_mode_dates_stay_excluded_after_one_mode_relearns() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            None,
            72.0,
            72.0,
            "heat_cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids=set(),
    )
    cooling_stream = f"heat_pump|{thermostat}|cooling"
    heating_stream = f"heat_pump|{thermostat}|heating"
    context.store_data.hvac_response_history_by_stream[cooling_stream] = (
        _hvac_response_history(cooling_stream)
    )
    context.store_data.hvac_response_history_by_stream[heating_stream] = (
        _hvac_response_history(heating_stream, count=1)
    )
    context.store_data.hvac_baseline_era_by_stream[heating_stream] = "era-2"

    result = HvacEfficiencyProcessor().process(
        [(heat_pump, SimpleNamespace())],
        context,
    )
    evidence = _state_update_values(result, "hvac_efficiency_by_circuit")[
        "heat_pump"
    ]

    assert evidence["streams"][cooling_stream]["status"] == "provisional"
    assert evidence["streams"][cooling_stream]["recent_count"] == 4
    assert context.store_data.hvac_response_history_by_stream[heating_stream] == []


def test_hvac_incomplete_opposing_call_excludes_mixed_mode_day() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            None,
            72.0,
            72.0,
            "heat_cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids=set(),
    )
    cooling_stream = f"heat_pump|{thermostat}|cooling"
    heating_stream = f"heat_pump|{thermostat}|heating"
    context.store_data.hvac_response_history_by_stream[cooling_stream] = (
        _hvac_response_history(cooling_stream)
    )
    incomplete_heating = _hvac_response_history(heating_stream, count=1)[0]
    incomplete_heating.update(complete=False, excluded_from_baseline=True)
    context.store_data.hvac_response_history_by_stream[heating_stream] = [
        incomplete_heating
    ]

    result = HvacEfficiencyProcessor().process(
        [(heat_pump, SimpleNamespace())],
        context,
    )
    cooling = _state_update_values(result, "hvac_efficiency_by_circuit")[
        "heat_pump"
    ]["streams"][cooling_stream]

    assert cooling["status"] == "provisional"
    assert cooling["recent_count"] == 4
    assert context.store_data.hvac_response_history_by_stream[heating_stream] == []


def test_hvac_linked_circuits_share_mixed_mode_dates() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    compressor = _hvac_config("compressor", ApplianceProfile.HVAC_COMPRESSOR)
    electric_heat = _hvac_config("electric_heat", ApplianceProfile.ELECTRIC_HEAT)
    linked = {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
    context = _hvac_context(
        configs=(compressor, electric_heat),
        observation=ThermostatObservation(
            thermostat,
            None,
            72.0,
            72.0,
            "heat_cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={"compressor": linked, "electric_heat": linked},
        running_circuit_ids=set(),
    )
    cooling_stream = f"compressor|{thermostat}|cooling"
    heating_stream = f"electric_heat|{thermostat}|heating"
    context.store_data.hvac_response_history_by_stream[cooling_stream] = (
        _hvac_response_history(
            cooling_stream,
            appliance_profile="hvac_compressor",
        )
    )
    context.store_data.hvac_response_history_by_stream[heating_stream] = (
        _hvac_response_history(
            heating_stream,
            count=1,
            appliance_profile="electric_heat",
        )
    )

    result = HvacEfficiencyProcessor().process(
        [(compressor, SimpleNamespace()), (electric_heat, SimpleNamespace())],
        context,
    )
    cooling = _state_update_values(result, "hvac_efficiency_by_circuit")[
        "compressor"
    ]["streams"][cooling_stream]

    assert cooling["status"] == "provisional"
    assert cooling["recent_count"] == 4
    assert context.store_data.hvac_response_history_by_stream[heating_stream] == []


def test_hvac_active_cross_midnight_call_disqualifies_closed_date() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    observation = ThermostatObservation(
        thermostat,
        None,
        76.0,
        72.0,
        "cool",
        "cooling",
        ("current_temperature", "temperature", "hvac_action"),
    )
    context = _hvac_context(
        configs=(heat_pump,),
        observation=observation,
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids={"heat_pump"},
    )
    context = replace(
        context,
        now=datetime(2026, 7, 29, 0, 10, tzinfo=UTC),
    )
    stream_id = f"heat_pump|{thermostat}|cooling"
    base = _hvac_response_history(stream_id, count=1)[0]
    calls = []
    for hour in (14, 16, 18, 20):
        started = datetime(2026, 7, 28, hour, tzinfo=UTC)
        calls.append(
            {
                **base,
                "started_at": started.isoformat(),
                "ended_at": (started + timedelta(minutes=10)).isoformat(),
                "elapsed_minutes": 10.0,
                "active_minutes": 10.0,
                "outdoor_temperature_minutes": 10.0,
            }
        )
    active = {
        **base,
        "started_at": datetime(2026, 7, 28, 23, 30, tzinfo=UTC).isoformat(),
        "ended_at": None,
        "elapsed_minutes": 40.0,
        "active_minutes": 40.0,
        "outdoor_temperature_minutes": 40.0,
        "complete": False,
        "excluded_from_baseline": False,
    }
    context.store_data.hvac_response_history_by_stream[stream_id] = calls
    context.state.hvac_current_episode_by_stream[stream_id] = active

    HvacEfficiencyProcessor().process([(heat_pump, SimpleNamespace())], context)

    assert context.store_data.hvac_response_history_by_stream[stream_id] == []


def test_hvac_nonselected_complete_weather_call_preserves_selected_context_day(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            None,
            72.0,
            72.0,
            "cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids=set(),
    )
    stream_id = f"heat_pump|{thermostat}|cooling"
    base = _hvac_response_history(stream_id, count=1)[0]
    calls = []
    for hour in (0, 2, 4, 6):
        started = datetime.fromisoformat(str(base["started_at"])) + timedelta(
            hours=hour
        )
        calls.append(
            {
                **base,
                "started_at": started.isoformat(),
                "ended_at": (started + timedelta(minutes=10)).isoformat(),
                "elapsed_minutes": 10.0,
                "active_minutes": 10.0,
                "outdoor_temperature_minutes": 10.0,
                "participant_signature": ["heat_pump", "selected"],
            }
        )
    excluded = {
        **calls[-1],
        "started_at": (
            datetime.fromisoformat(str(base["started_at"])) + timedelta(hours=8)
        ).isoformat(),
        "ended_at": (
            datetime.fromisoformat(str(base["started_at"]))
            + timedelta(hours=8, minutes=10)
        ).isoformat(),
        "complete": False,
        "excluded_from_baseline": True,
        "participant_signature": ["heat_pump", "alternate"],
    }
    context.store_data.hvac_response_history_by_stream[stream_id] = [
        *calls,
        excluded,
    ]

    HvacEfficiencyProcessor().process([(heat_pump, SimpleNamespace())], context)

    compacted = context.store_data.hvac_response_history_by_stream[stream_id]

    assert len(compacted) == 1
    assert compacted[0]["episode_kind"] == "core_day"
    assert compacted[0]["active_minutes"] == 40.0


def test_hvac_mixed_mode_markers_survive_until_local_day_closes() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            None,
            72.0,
            72.0,
            "heat_cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids=set(),
    )
    cooling_stream = f"heat_pump|{thermostat}|cooling"
    heating_stream = f"heat_pump|{thermostat}|heating"
    cooling = _hvac_response_history(cooling_stream, count=1)[0]
    heating = _hvac_response_history(heating_stream, count=1)[0]
    cooling_started = context.now - timedelta(hours=13)
    cooling.update(
        started_at=cooling_started.isoformat(),
        ended_at=(cooling_started + timedelta(hours=2)).isoformat(),
    )
    heating_started = context.now - timedelta(hours=2)
    heating.update(
        started_at=heating_started.isoformat(),
        ended_at=(heating_started + timedelta(minutes=40)).isoformat(),
    )
    context.store_data.hvac_response_history_by_stream.update(
        {cooling_stream: [cooling], heating_stream: [heating]}
    )
    processor = HvacEfficiencyProcessor()

    processor.process([(heat_pump, SimpleNamespace())], context)

    assert len(context.store_data.hvac_response_history_by_stream[cooling_stream]) == 1
    assert len(context.store_data.hvac_response_history_by_stream[heating_stream]) == 1

    context.store_data.hvac_baseline_era_by_stream[cooling_stream] = "era-2"
    later_cooling = {**cooling}
    later_started = context.now + timedelta(hours=1)
    later_cooling.update(
        baseline_era="era-2",
        started_at=later_started.isoformat(),
        ended_at=(later_started + timedelta(minutes=40)).isoformat(),
    )
    context.store_data.hvac_response_history_by_stream[cooling_stream].append(
        later_cooling
    )
    processor.process([(heat_pump, SimpleNamespace())], context)

    assert len(context.store_data.hvac_response_history_by_stream[cooling_stream]) == 2
    context = replace(context, now=context.now + timedelta(days=1))
    processor.process([(heat_pump, SimpleNamespace())], context)

    assert context.store_data.hvac_response_history_by_stream[cooling_stream] == []
    assert context.store_data.hvac_response_history_by_stream[heating_stream] == []


def test_hvac_compaction_discards_obsolete_baseline_eras() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            None,
            72.0,
            72.0,
            "cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids=set(),
    )
    stream_id = f"heat_pump|{thermostat}|cooling"
    history = _hvac_response_history(stream_id)
    obsolete = []
    for raw in history:
        started = datetime.fromisoformat(str(raw["started_at"])) - timedelta(days=90)
        ended = datetime.fromisoformat(str(raw["ended_at"])) - timedelta(days=90)
        obsolete.append(
            {
                **raw,
                "baseline_era": "initial",
                "started_at": started.isoformat(),
                "ended_at": ended.isoformat(),
            }
        )
    context.store_data.hvac_response_history_by_stream[stream_id] = [
        *obsolete,
        *[{**raw, "baseline_era": "era-2"} for raw in history],
    ]
    context.store_data.hvac_baseline_era_by_stream[stream_id] = "era-2"

    HvacEfficiencyProcessor().process([(heat_pump, SimpleNamespace())], context)
    retained = context.store_data.hvac_response_history_by_stream[stream_id]

    assert len(retained) == 55
    assert {raw["baseline_era"] for raw in retained} == {"era-2"}


@pytest.mark.parametrize("prior_complete", [False, True])
def test_hvac_prior_era_same_mode_call_disqualifies_core_day(
    prior_complete: bool,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            None,
            72.0,
            72.0,
            "cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids=set(),
    )
    stream_id = f"heat_pump|{thermostat}|cooling"
    base = _hvac_response_history(stream_id, count=1)[0]
    calls = []
    for hour in (14, 16, 18, 20):
        started = context.now - timedelta(days=1) + timedelta(hours=hour - 12)
        calls.append(
            {
                **base,
                "baseline_era": "era-2",
                "started_at": started.isoformat(),
                "ended_at": (started + timedelta(minutes=10)).isoformat(),
                "elapsed_minutes": 10.0,
                "active_minutes": 10.0,
                "outdoor_temperature_minutes": 10.0,
            }
        )
    prior_era = {
        **calls[0],
        "baseline_era": "initial",
        "started_at": (context.now - timedelta(days=1, hours=1)).isoformat(),
        "ended_at": (context.now - timedelta(days=1, minutes=50)).isoformat(),
        "complete": prior_complete,
        "excluded_from_baseline": not prior_complete,
    }
    context.store_data.hvac_response_history_by_stream[stream_id] = [
        prior_era,
        *calls,
    ]
    context.store_data.hvac_baseline_era_by_stream[stream_id] = "era-2"

    HvacEfficiencyProcessor().process([(heat_pump, SimpleNamespace())], context)

    assert context.store_data.hvac_response_history_by_stream[stream_id] == []


def test_hvac_alert_recovers_after_three_normal_core_days() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            None,
            72.0,
            72.0,
            "cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids=set(),
    )
    stream_id = f"heat_pump|{thermostat}|cooling"
    history = _hvac_response_history(stream_id, recent_rate=12.5)
    context.store_data.hvac_response_history_by_stream[stream_id] = history
    policy = ConservativeAlertPolicy(
        min_repeated=1,
        min_total_score=1.0,
        min_average_score=1.0,
        min_baseline_confidence=0.0,
    )
    processor = HvacEfficiencyProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy
    )
    initial = processor.process([(heat_pump, SimpleNamespace())], context)
    context.state.active_alerts_by_circuit = {"heat_pump": initial.alerts}

    history = context.store_data.hvac_response_history_by_stream[stream_id]
    _set_hvac_history_multiplier(history, range(53, 55), 1.0)
    two_normal = processor.process([(heat_pump, SimpleNamespace())], context)
    history = context.store_data.hvac_response_history_by_stream[stream_id]
    _set_hvac_history_multiplier(history, range(52, 55), 1.0)
    three_normal = processor.process([(heat_pump, SimpleNamespace())], context)

    assert two_normal.preserved_alerts == initial.alerts
    assert three_normal.preserved_alerts == []
    assert three_normal.notifications == []


def test_hvac_efficiency_ignores_history_for_unlinked_thermostat() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    linked = "climate.upstairs"
    retired = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            linked,
            None,
            72.0,
            72.0,
            "cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [linked]}
        },
        running_circuit_ids=set(),
    )
    retired_stream = f"heat_pump|{retired}|cooling"
    context.store_data.hvac_response_history_by_stream[retired_stream] = (
        _hvac_response_history(retired_stream, recent_rate=15.0)
    )
    policy = ConservativeAlertPolicy(
        min_repeated=1,
        min_total_score=1.5,
        min_average_score=1.5,
        min_baseline_confidence=0.0,
    )

    result = HvacEfficiencyProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy
    ).process([(heat_pump, SimpleNamespace())], context)
    payload = _state_update_values(
        result,
        "hvac_efficiency_by_circuit",
    )["heat_pump"]

    assert payload["streams"] == {}
    assert payload["score"] is None
    assert result.alerts == result.notifications == []
    assert retired_stream in context.store_data.hvac_response_history_by_stream


def test_hvac_efficiency_ignores_history_from_previous_appliance_profile() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            None,
            72.0,
            72.0,
            "cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids=set(),
    )
    stream_id = f"heat_pump|{thermostat}|cooling"
    context.store_data.hvac_response_history_by_stream[stream_id] = (
        _hvac_response_history(
            stream_id,
            recent_rate=15.0,
            appliance_profile="hvac_compressor",
        )
    )

    result = HvacEfficiencyProcessor(
        alert_policy_for_circuit=lambda _circuit_id: ConservativeAlertPolicy(
            min_repeated=1,
            min_total_score=1.5,
            min_average_score=1.5,
            min_baseline_confidence=0.0,
        )
    ).process([(heat_pump, SimpleNamespace())], context)
    payload = _state_update_values(
        result,
        "hvac_efficiency_by_circuit",
    )["heat_pump"]

    assert payload["streams"][stream_id]["status"] == "no_data"
    assert payload["score"] is None
    assert result.alerts == result.notifications == []
    assert len(context.store_data.hvac_response_history_by_stream[stream_id]) == 55


def test_hvac_new_equipment_context_replaces_mature_context() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            None,
            72.0,
            72.0,
            "cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids=set(),
    )
    stream_id = f"heat_pump|{thermostat}|cooling"
    history = _hvac_response_history(stream_id)
    for raw in history:
        raw["participant_signature"] = ["heat_pump", "old"]
    context.store_data.hvac_response_history_by_stream[stream_id] = history
    processor = HvacEfficiencyProcessor()

    processor.process([(heat_pump, SimpleNamespace())], context)

    first_new = _hvac_response_history(stream_id, count=56)[-1]
    first_new["participant_signature"] = ["heat_pump", "new"]
    context.store_data.hvac_response_history_by_stream[stream_id].append(first_new)
    processor.process([(heat_pump, SimpleNamespace())], context)

    retained = context.store_data.hvac_response_history_by_stream[stream_id]
    assert len(retained) == 1
    assert retained[0]["participant_signature"] == ["heat_pump", "new"]

    second_new = _hvac_response_history(stream_id, count=57)[-1]
    second_new["participant_signature"] = ["heat_pump", "new"]
    retained.append(second_new)
    processor.process([(heat_pump, SimpleNamespace())], context)

    assert len(context.store_data.hvac_response_history_by_stream[stream_id]) == 2

    context = replace(context, now=context.now + timedelta(days=5))
    alternating_old = _hvac_response_history(stream_id, count=58)[-1]
    alternating_old["participant_signature"] = ["heat_pump", "old"]
    context.store_data.hvac_response_history_by_stream[stream_id].append(
        alternating_old
    )
    processor.process([(heat_pump, SimpleNamespace())], context)
    alternating_new = _hvac_response_history(stream_id, count=59)[-1]
    alternating_new["participant_signature"] = ["heat_pump", "new"]
    context.store_data.hvac_response_history_by_stream[stream_id].append(
        alternating_new
    )
    processor.process([(heat_pump, SimpleNamespace())], context)

    assert len(context.store_data.hvac_response_history_by_stream[stream_id]) == 3

    for count in (60, 61, 62):
        returning = _hvac_response_history(stream_id, count=count)[-1]
        returning["participant_signature"] = ["heat_pump", "old"]
        context.store_data.hvac_response_history_by_stream[stream_id].append(
            returning
        )
        processor.process([(heat_pump, SimpleNamespace())], context)
        if count < 62:
            candidate = dict(
                context.store_data.hvac_response_context_by_stream[stream_id]
            )
            processor.process([(heat_pump, SimpleNamespace())], context)
            assert (
                context.store_data.hvac_response_context_by_stream[stream_id]
                == candidate
            )

    retained = context.store_data.hvac_response_history_by_stream[stream_id]
    assert len(retained) == 1
    assert retained[0]["participant_signature"] == ["heat_pump", "old"]


def test_hvac_efficiency_uses_only_the_current_temperature_source() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    old_temperature = "sensor.old_downstairs_temperature"
    current_temperature = "sensor.downstairs_temperature"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            current_temperature,
            72.0,
            72.0,
            "cool",
            "idle",
            ("temperature_override", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "heat_pump": {
                CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat],
                CONF_THERMOSTAT_TEMPERATURE_SENSOR_MAP: {
                    thermostat: current_temperature
                },
            }
        },
        running_circuit_ids=set(),
    )
    stream_id = f"heat_pump|{thermostat}|cooling"
    history = _hvac_response_history(stream_id, recent_rate=15.0)
    for raw in history[:9]:
        raw["temperature_entity_id"] = old_temperature
    for raw in history[9:]:
        raw["temperature_entity_id"] = current_temperature
    context.store_data.hvac_response_history_by_stream[stream_id] = history

    result = HvacEfficiencyProcessor(
        alert_policy_for_circuit=lambda _circuit_id: ConservativeAlertPolicy(
            min_repeated=1,
            min_total_score=1.5,
            min_average_score=1.5,
            min_baseline_confidence=0.0,
        )
    ).process([(heat_pump, SimpleNamespace())], context)
    payload = _state_update_values(
        result,
        "hvac_efficiency_by_circuit",
    )["heat_pump"]

    assert payload["streams"][stream_id]["status"] == "provisional"
    assert payload["finding"] is None
    assert result.alerts == result.notifications == []
    assert len(context.store_data.hvac_response_history_by_stream[stream_id]) == 46


def test_hvac_response_requires_maturity_and_never_scores_cooling_blower() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    blower = _hvac_config("blower", ApplianceProfile.HVAC_BLOWER)
    context = _hvac_context(
        configs=(blower,),
        observation=ThermostatObservation(
            thermostat,
            None,
            72.0,
            72.0,
            "cool",
            "idle",
            ("current_temperature", "temperature", "hvac_action"),
        ),
        advanced_settings={
            "blower": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids=set(),
    )
    stream_id = f"blower|{thermostat}|cooling"
    policy = ConservativeAlertPolicy(
        min_repeated=1,
        min_total_score=1.5,
        min_average_score=1.5,
        min_baseline_confidence=0.0,
    )
    processor = HvacEfficiencyProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy
    )
    context.store_data.hvac_response_history_by_stream[stream_id] = (
        _hvac_response_history(stream_id, count=11)
    )

    immature = processor.process([(blower, SimpleNamespace())], context)
    context.store_data.hvac_response_history_by_stream[stream_id] = (
        _hvac_response_history(stream_id)
    )
    mature = processor.process([(blower, SimpleNamespace())], context)

    assert immature.alerts == immature.notifications == []
    assert mature.alerts == mature.notifications == []


def test_hvac_response_evaluation_uses_only_current_baseline_era() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    thermostat = "climate.downstairs"
    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            thermostat,
            None,
            72.0,
            72.0,
            "cool",
            "idle",
            ("current_temperature", "temperature"),
        ),
        advanced_settings={
            "heat_pump": {CONF_LINKED_THERMOSTAT_ENTITIES: [thermostat]}
        },
        running_circuit_ids=set(),
    )
    stream_id = f"heat_pump|{thermostat}|cooling"
    context.store_data.hvac_response_history_by_stream[stream_id] = (
        _hvac_response_history(stream_id)
    )
    context.store_data.hvac_baseline_era_by_stream[stream_id] = "era-2"
    processor = HvacEfficiencyProcessor(
        alert_policy_for_circuit=lambda _circuit_id: ConservativeAlertPolicy(
            min_repeated=1,
            min_total_score=1.5,
            min_average_score=1.5,
            min_baseline_confidence=0.0,
        )
    )

    result = processor.process([(heat_pump, SimpleNamespace())], context)
    evidence = _state_update_values(result, "hvac_efficiency_by_circuit")[
        "heat_pump"
    ]

    assert result.alerts == result.notifications == []
    assert evidence["finding"] is None
    assert evidence["streams"][stream_id]["status"] == "no_data"


@pytest.mark.parametrize(
    ("observation", "reason_fragment"),
    [
        (
            ThermostatObservation(
                "climate.downstairs",
                None,
                None,
                None,
                None,
                None,
                (),
            ),
            "unavailable",
        ),
        (
            ThermostatObservation(
                "climate.downstairs",
                None,
                72.0,
                None,
                "cool",
                "idle",
                ("current_temperature",),
            ),
            "setpoint",
        ),
        (
            ThermostatObservation(
                "climate.downstairs",
                None,
                None,
                72.0,
                "cool",
                "idle",
                ("temperature",),
            ),
            "current temperature",
        ),
        (
            ThermostatObservation(
                "climate.downstairs",
                "sensor.downstairs_temperature",
                72.0,
                72.0,
                "cool",
                "idle",
                ("current_temperature", "temperature"),
            ),
            "override",
        ),
    ],
)
def test_hvac_selected_unusable_thermostat_reports_setup_issue(
    observation: ThermostatObservation,
    reason_fragment: str,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    heat_pump = replace(
        _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP),
        name="Downstairs Heat Pump",
    )
    context = _hvac_context(
        configs=(heat_pump,),
        observation=observation,
        advanced_settings={
            "heat_pump": {
                CONF_LINKED_THERMOSTAT_ENTITIES: [
                    observation.thermostat_entity_id
                ]
            }
        },
        running_circuit_ids=set(),
    )

    result = HvacEfficiencyProcessor().process(
        [(heat_pump, SimpleNamespace())],
        context,
    )
    issues = _state_update_values(
        result,
        "hvac_thermostat_setup_issues_by_circuit",
    )["heat_pump"]

    assert issues[0]["issue_kind"] == "missing_required_sensor"
    assert issues[0]["circuit_name"] == "Downstairs Heat Pump"
    assert "Downstairs Heat Pump" in issues[0]["reason"]
    assert reason_fragment in issues[0]["reason"].lower()


@pytest.mark.parametrize(
    "observation",
    [
        ThermostatObservation(
            "climate.downstairs",
            None,
            72.0,
            None,
            "heat_cool",
            None,
            ("current_temperature", "target_temp_low", "target_temp_high"),
        ),
        ThermostatObservation(
            "climate.downstairs",
            None,
            72.0,
            None,
            "off",
            None,
            ("current_temperature", "temperature"),
        ),
    ],
)
def test_hvac_idle_thermostat_with_setpoint_capability_has_no_setup_issue(
    observation: ThermostatObservation,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    heat_pump = _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP)
    context = _hvac_context(
        configs=(heat_pump,),
        observation=observation,
        advanced_settings={
            "heat_pump": {
                CONF_LINKED_THERMOSTAT_ENTITIES: [
                    observation.thermostat_entity_id
                ]
            }
        },
        running_circuit_ids=set(),
    )

    result = HvacEfficiencyProcessor().process(
        [(heat_pump, SimpleNamespace())],
        context,
    )

    assert _state_update_values(
        result,
        "hvac_thermostat_setup_issues_by_circuit",
    )["heat_pump"] == []


def test_hvac_multiple_thermostats_require_explicit_circuit_mapping() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        HvacEfficiencyProcessor,
    )

    heat_pump = replace(
        _hvac_config("heat_pump", ApplianceProfile.HEAT_PUMP),
        name="Downstairs Heat Pump",
    )
    context = _hvac_context(
        configs=(heat_pump,),
        observation=ThermostatObservation(
            "climate.downstairs",
            None,
            72.0,
            72.0,
            "cool",
            "idle",
            ("current_temperature", "temperature"),
        ),
        advanced_settings={"heat_pump": {}},
        running_circuit_ids=set(),
    )
    context = replace(
        context,
        entry_data={
            CONF_THERMOSTAT_ENTITIES: [
                "climate.downstairs",
                "climate.upstairs",
            ]
        },
    )

    result = HvacEfficiencyProcessor().process(
        [(heat_pump, SimpleNamespace())],
        context,
    )
    issue = _state_update_values(
        result,
        "hvac_thermostat_setup_issues_by_circuit",
    )["heat_pump"][0]

    assert issue["issue_kind"] == "missing_required_sensor"
    assert issue["circuit_name"] == "Downstairs Heat Pump"
    assert "choose a thermostat" in issue["reason"].lower()


class _CaptureAlertPolicy:
    min_average_score = 1.5

    def __init__(self) -> None:
        self.observations: list[Observation] = []

    def observe(self, observation: Observation) -> AlertEvidence:
        self.observations.append(observation)
        return AlertEvidence(
            timestamp=observation.observed_at,
            circuit_id=observation.circuit_id,
            severity=Severity.WARNING,
            message=observation.message,
            feature=observation.feature,
            features=observation.features,
            observed_value=observation.observed_value,
            baseline_value=observation.baseline_value,
        )

    def reset_episode(self, circuit_id: str, feature: str) -> None:
        del circuit_id, feature


class _CaptureObservationOnlyPolicy:
    min_average_score = 1.5

    def __init__(self) -> None:
        self.observations: list[Observation] = []

    def observe(self, observation: Observation) -> None:
        self.observations.append(observation)

    def reset_episode(self, circuit_id: str, feature: str) -> None:
        del circuit_id, feature


def _cold_storage_sample(
    timestamp: datetime,
    *,
    pulse: bool,
    abnormal: bool,
) -> NormalizedCircuitSample:
    return NormalizedCircuitSample(
        timestamp=timestamp,
        circuit_id="fridge",
        real_power=(
            (125.0 if pulse else 150.0)
            if abnormal
            else (160.0 if pulse else 100.0)
        ),
        current=(1.45 if pulse else 1.8) if abnormal else (1.9 if pulse else 1.2),
        power_factor=0.60 if abnormal else (0.86 if pulse else 0.60),
    )


def _cold_storage_baselines() -> dict[str, BaselineStats]:
    return {
        "fridge:cold_storage_pf_peak_delta": BaselineStats(
            "cold_storage_pf_peak_delta", 96, 0.26, 0.01, 0.24, 0.27, 1.0
        ),
        "fridge:cold_storage_median_power_w": BaselineStats(
            "cold_storage_median_power_w", 96, 100.0, 3.0, 95.0, 105.0, 1.0
        ),
        "fridge:cold_storage_median_current_a": BaselineStats(
            "cold_storage_median_current_a", 96, 1.2, 0.04, 1.1, 1.3, 1.0
        ),
    }


def test_feature_result_defaults_are_independent() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        FeatureResult,
        StateUpdate,
    )

    first = FeatureResult()
    second = FeatureResult()

    first.events.append(
        CircuitEvent(
            timestamp=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
            circuit_id="fridge",
            event_type=EventType.START,
        )
    )
    first.state_updates.append(
        StateUpdate(
            path=("health_summary_by_circuit", "fridge"),
            value="Running",
        )
    )
    first.observations.append(
        Observation(
            circuit_id="fridge",
            feature="cycle_duration",
            score=1.7,
            baseline_confidence=0.8,
            observed_at=datetime(2026, 6, 11, 12, 1, tzinfo=UTC),
        )
    )

    assert len(first.events) == 1
    assert len(first.observations) == 1
    assert len(first.state_updates) == 1
    assert second.events == []
    assert second.observations == []
    assert second.state_updates == []


def test_processing_context_keeps_runtime_dependencies() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    hass = SimpleNamespace(data={DOMAIN: {}})
    state = AnalyzerState()
    store_data = FeatureStoreData()

    context = ProcessingContext(
        now=now,
        hass=hass,
        state=state,
        store_data=store_data,
        options={"sensitivity": "standard"},
        entry_data={"source_entities": ["sensor.fridge_power"]},
        known_load_circuit_ids=frozenset({"fridge"}),
        sensitivity="standard",
    )

    assert context.now is now
    assert context.hass is hass
    assert context.state is state
    assert context.store_data is store_data
    assert context.known_load_circuit_ids == frozenset({"fridge"})


@pytest.mark.asyncio
async def test_processing_pipeline_uses_injected_processors() -> None:
    from custom_components.circuitsetup_energy_analyzer.managers import (
        processing_pipeline,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import power_quality
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        FeatureResult,
    )

    calls: list[str] = []
    cleared_power_quality: list[str] = []
    cleared_standby: list[str] = []

    class _Processor:
        def __init__(self, name: str, result: FeatureResult | None = None) -> None:
            self.name = name
            self.result = result or FeatureResult()

        def process(self, *args: object, **kwargs: object) -> FeatureResult:
            del args, kwargs
            calls.append(self.name)
            asyncio.get_running_loop().call_soon(
                calls.append,
                f"tick:{self.name}",
            )
            return self.result

    class _Coordinator:
        async def async_apply_feature_result(
            self,
            result: FeatureResult,
        ) -> tuple[list[CircuitEvent], list[AlertEvidence]]:
            return result.events, result.alerts

    coordinator = _Coordinator()
    pipeline = processing_pipeline.ProcessingPipeline(coordinator)
    pipeline.configure_processors(
        event_processor=_Processor("event"),
        power_quality_processor=_Processor(
            "power_quality",
            power_quality.PowerQualityResult(clear_power_quality_state="fridge"),
        ),
        energy_usage_processor=_Processor("usage"),
        energy_goal_processor=_Processor("goal"),
        run_cycle_processor=_Processor("cycle"),
        appliance_health_processor=_Processor("appliance_health"),
        activity_alert_processor=_Processor("activity"),
        billing_cycle_processor=_Processor("billing"),
        cost_processor=_Processor("cost"),
        demand_processor=_Processor("demand"),
        capacity_processor=_Processor("capacity"),
        leg_imbalance_processor=_Processor("leg_imbalance"),
        metric_consistency_processor=_Processor("metric_consistency"),
        standby_processor=_Processor("standby"),
        mains_balance_processor=_Processor("mains_balance"),
        solar_flow_processor=_Processor("solar_flow"),
        utility_comparison_processor=_Processor("utility_comparison"),
        clear_power_quality_state=cleared_power_quality.append,
        clear_standby_state=cleared_standby.append,
        sync_setup_health_repairs=lambda circuit_id: None,
    )

    await pipeline.async_process_circuit(
        CircuitConfig(
            circuit_id="fridge",
            name="Fridge",
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            mode=CircuitMode.SINGLE_PHASE,
            power_flow=PowerFlowMode.LOAD,
        ),
        NormalizedCircuitSample(
            timestamp=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
            circuit_id="fridge",
            real_power=180.0,
        ),
        SimpleNamespace(store_data=FeatureStoreData()),
    )

    processor_names = [
        "event",
        "power_quality",
        "usage",
        "goal",
        "cycle",
        "appliance_health",
        "activity",
        "billing",
        "cost",
        "demand",
        "capacity",
        "leg_imbalance",
        "metric_consistency",
        "standby",
    ]
    assert calls == [
        entry
        for name in processor_names
        for entry in (name, f"tick:{name}")
    ]
    assert cleared_power_quality == ["fridge"]
    assert cleared_standby == []


@pytest.mark.asyncio
async def test_processing_pipeline_applies_cross_circuit_feature_results() -> None:
    from custom_components.circuitsetup_energy_analyzer.managers import (
        processing_pipeline,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        FeatureResult,
        StateUpdate,
    )

    applied: list[FeatureResult] = []
    balance_result = FeatureResult(
        state_updates=[
            StateUpdate(
                ("health_summary_by_circuit", "mains"),
                "Balanced",
            )
        ]
    )
    solar_result = FeatureResult(
        state_updates=[
            StateUpdate(
                ("solar_flow_status_by_circuit", "mains"),
                "surplus",
            )
        ],
        store_dirty=True,
    )
    hvac_result = FeatureResult(
        state_updates=[
            StateUpdate(
                ("hvac_efficiency_by_circuit", "heat_pump"),
                {"status": "tracking"},
            )
        ]
    )

    class _Processor:
        def __init__(self, result: FeatureResult | None = None) -> None:
            self.result = result or FeatureResult()

        def process(self, *args: object, **kwargs: object) -> FeatureResult:
            del args, kwargs
            return self.result

    class _AsyncProcessor(_Processor):
        async def process(self, *args: object, **kwargs: object) -> FeatureResult:
            return super().process(*args, **kwargs)

    async def sync_setup_health_repairs(circuit_id: str) -> None:
        del circuit_id

    class _Coordinator:
        state = SimpleNamespace()
        store_data = SimpleNamespace(
            utility_comparison_settings_by_circuit={"mains": {}}
        )
        circuit_registry = SimpleNamespace(
            config_for_circuit=lambda circuit_id: object()
        )
        state_reducer = SimpleNamespace(apply_updates=lambda state, updates: None)

        def __init__(self) -> None:
            self.cost_estimate_refreshes = 0

        def refresh_cost_estimates(self) -> None:
            self.cost_estimate_refreshes += 1

        async def async_apply_feature_result(
            self,
            result: FeatureResult,
        ) -> tuple[list[CircuitEvent], list[AlertEvidence]]:
            applied.append(result)
            return result.events, result.alerts

    coordinator = _Coordinator()
    pipeline = processing_pipeline.ProcessingPipeline(coordinator)
    pipeline.configure_processors(
        event_processor=_Processor(),
        power_quality_processor=_Processor(),
        energy_usage_processor=_Processor(),
        energy_goal_processor=_Processor(),
        run_cycle_processor=_Processor(),
        appliance_health_processor=_Processor(),
        activity_alert_processor=_Processor(),
        billing_cycle_processor=_Processor(),
        cost_processor=_Processor(),
        demand_processor=_Processor(),
        capacity_processor=_Processor(),
        leg_imbalance_processor=_Processor(),
        metric_consistency_processor=_Processor(),
        standby_processor=_Processor(),
        hvac_efficiency_processor=_Processor(hvac_result),
        mains_balance_processor=_Processor(balance_result),
        solar_flow_processor=_Processor(solar_result),
        utility_comparison_processor=_AsyncProcessor(
            FeatureResult(
                state_updates=[
                    StateUpdate(("utility_cost_rate_by_circuit", "mains"), 0.25)
                ]
            )
        ),
        clear_power_quality_state=lambda circuit_id: None,
        clear_standby_state=lambda circuit_id: None,
        sync_setup_health_repairs=sync_setup_health_repairs,
    )

    alerts = await pipeline.async_process_cross_circuit([], SimpleNamespace())

    assert alerts == []
    assert applied == [
        hvac_result,
        balance_result,
        solar_result,
        pipeline._utility_comparison_processor.result,
    ]
    assert coordinator.cost_estimate_refreshes == 1
    assert any(result.store_dirty for result in applied)


@pytest.mark.asyncio
async def test_coordinator_applies_feature_result() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        FeatureResult,
        StateUpdate,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    event = CircuitEvent(
        timestamp=now,
        circuit_id="fridge",
        event_type=EventType.START,
    )
    alert = AlertEvidence(
        timestamp=now,
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue detected.",
        feature="processor_test",
    )
    notifications: list[AlertEvidence] = []
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={DOMAIN: {}}),
        entry_data={},
        store_data=FeatureStoreData(),
        now_fn=lambda: now,
    )
    coordinator.state.learning_by_circuit["fridge"] = False

    async def fake_notify(alert_to_notify: AlertEvidence) -> None:
        notifications.append(alert_to_notify)

    coordinator._notify_alert = fake_notify

    applied_events, applied_alerts = await coordinator.async_apply_feature_result(
        FeatureResult(
            events=[event],
            alerts=[alert],
            notifications=[alert],
            state_updates=[
                StateUpdate(
                    path=("health_summary_by_circuit", "fridge"),
                    value="Running",
                )
            ],
            store_dirty=True,
        )
    )

    assert applied_events == [event]
    assert applied_alerts == [alert]
    assert coordinator.store_data.events == [event]
    assert coordinator.store_data.alerts == [alert]
    assert coordinator.state.health_summary_by_circuit["fridge"] == "Running"
    assert notifications == [alert]
    assert coordinator._store_dirty is True


@pytest.mark.asyncio
async def test_coordinator_state_update_without_store_data_change_stays_clean() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        FeatureResult,
        StateUpdate,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={DOMAIN: {}}),
        entry_data={},
        store_data=FeatureStoreData(),
    )

    await coordinator.async_apply_feature_result(
        FeatureResult(
            state_updates=[
                StateUpdate(
                    path=("health_summary_by_circuit", "fridge"),
                    value="Running",
                )
            ],
        )
    )

    assert coordinator.state.health_summary_by_circuit["fridge"] == "Running"
    assert coordinator._store_dirty is False


@pytest.mark.asyncio
async def test_coordinator_applies_observation_lane_without_creating_alert_history(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        FeatureResult,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    observation = Observation(
        circuit_id="fridge",
        feature="cycle_duration",
        score=1.8,
        baseline_confidence=0.9,
        observed_at=now,
        observed_value=45.0,
        baseline_value=30.0,
        message="Fridge ran longer than usual.",
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={DOMAIN: {}}),
        entry_data={},
        store_data=FeatureStoreData(),
        now_fn=lambda: now,
    )

    applied_events, applied_alerts = await coordinator.async_apply_feature_result(
        FeatureResult(observations=[observation]),
    )

    assert applied_events == []
    assert applied_alerts == []
    assert coordinator.store_data.alerts == []
    assert coordinator._store_dirty is False
    assert coordinator.state.recent_observations_by_circuit["fridge"] == [
        {
            "timestamp": now.isoformat(),
            "circuit_id": "fridge",
            "feature": "cycle_duration",
            "feature_name": "Cycle Duration",
            "message": "Fridge ran longer than usual.",
            "score": 1.8,
            "baseline_confidence": 0.9,
            "observed_value": 45.0,
            "baseline_value": 30.0,
        }
    ]


@pytest.mark.parametrize(
    ("maintenance_active", "baseline_eligible"),
    [(False, True), (True, False)],
)
def test_event_processor_returns_events_after_dwell(
    maintenance_active: bool,
    baseline_eligible: bool,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.events import (
        CircuitEventProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(
            maintenance_by_circuit=(
                {"fridge": {"active": True}} if maintenance_active else {}
            )
        ),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    processor = CircuitEventProcessor()

    first = processor.process(_sample(0, 5.0), config, context)
    second = processor.process(_sample(10, 210.0), config, context)
    third = processor.process(_sample(21, 210.0), config, context)

    assert first.events == []
    assert second.events == []
    assert [event.event_type for event in third.events] == [EventType.START]
    assert third.events[0].features["baseline_eligible"] is baseline_eligible
    assert third.store_dirty is True


def test_event_processor_excludes_run_overlapping_completed_maintenance() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.events import (
        CircuitEventProcessor,
    )

    context = ProcessingContext(
        now=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    processor = CircuitEventProcessor()

    processor.process(_sample(0, 5.0), config, context)
    processor.process(_sample(10, 210.0), config, context)
    started = processor.process(_sample(21, 210.0), config, context)
    assert started.events[0].features["baseline_eligible"] is True

    context.store_data.maintenance_by_circuit["fridge"] = {
        "active": False,
        "started_at": _sample(25, 210.0).timestamp.isoformat(),
        "ended_at": _sample(35, 210.0).timestamp.isoformat(),
    }
    processor.process(_sample(40, 5.0), config, context)
    stopped = processor.process(_sample(90, 5.0), config, context)

    assert [event.event_type for event in stopped.events] == [EventType.STOP]
    assert stopped.events[0].features["baseline_eligible"] is False


def test_event_processor_uses_profile_thresholds_and_dwell() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.events import (
        CircuitEventProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    processor = CircuitEventProcessor()
    washer = CircuitConfig(
        circuit_id="washer",
        name="Washer",
        appliance_profile=ApplianceProfile.WASHER,
        mode=CircuitMode.SINGLE_PHASE,
    )
    microwave = CircuitConfig(
        circuit_id="microwave",
        name="Microwave",
        appliance_profile=ApplianceProfile.MICROWAVE,
        mode=CircuitMode.SINGLE_PHASE,
    )

    washer_first = processor.process(_sample(0, 5.0), washer, context)
    washer_pending = processor.process(_sample(5, 35.0), washer, context)
    washer_confirmed = processor.process(_sample(21, 35.0), washer, context)
    microwave_first = processor.process(_sample(0, 5.0), microwave, context)
    microwave_second = processor.process(_sample(5, 35.0), microwave, context)
    microwave_third = processor.process(_sample(21, 35.0), microwave, context)

    assert washer_first.events == []
    assert washer_pending.events == []
    assert [event.event_type for event in washer_confirmed.events] == [EventType.START]
    assert microwave_first.events == []
    assert microwave_second.events == []
    assert microwave_third.events == []


def test_event_processor_returns_operating_state_updates() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.events import (
        CircuitEventProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="washer",
        name="Washer",
        appliance_profile=ApplianceProfile.WASHER,
        mode=CircuitMode.SINGLE_PHASE,
    )
    processor = CircuitEventProcessor()

    first = processor.process(_sample(0, 5.0), config, context)
    second = processor.process(_sample(5, 35.0), config, context)
    third = processor.process(_sample(21, 35.0), config, context)

    first_updates = {update.path: update.value for update in first.state_updates}
    second_updates = {update.path: update.value for update in second.state_updates}
    third_updates = {update.path: update.value for update in third.state_updates}

    assert first_updates[("operating_state_by_circuit", "washer")] == "off"
    assert (
        first_updates[("operating_state_snapshot_by_circuit", "washer")]["state"]
        == "off"
    )
    assert second_updates[("operating_state_by_circuit", "washer")] == "pending_on"
    assert third_updates[("operating_state_by_circuit", "washer")] == "running"
    assert third_updates[("operating_state_snapshot_by_circuit", "washer")][
        "stable_state"
    ] == "running"


def test_event_processor_preserves_threshold_source_from_overrides() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.events import (
        CircuitEventProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(
            operating_detection_settings_by_circuit={
                "washer": {
                    "operating_on_threshold_w": 42.0,
                    "operating_off_threshold_w": 18.0,
                }
            }
        ),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="washer",
        name="Washer",
        appliance_profile=ApplianceProfile.WASHER,
        mode=CircuitMode.SINGLE_PHASE,
    )
    processor = CircuitEventProcessor()

    result = processor.process(_sample(0, 5.0), config, context)
    updates = {update.path: update.value for update in result.state_updates}

    assert updates[("operating_state_snapshot_by_circuit", "washer")][
        "threshold_source"
    ] == "user_override"


def test_event_processor_preserves_threshold_source_from_applied_recommendation() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.events import (
        CircuitEventProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(
            operating_detection_settings_by_circuit={
                "washer": {
                    "operating_on_threshold_w": 42.0,
                    "operating_off_threshold_w": 18.0,
                    "operating_detection_source": "learned_recommendation",
                }
            }
        ),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="washer",
        name="Washer",
        appliance_profile=ApplianceProfile.WASHER,
        mode=CircuitMode.SINGLE_PHASE,
    )
    processor = CircuitEventProcessor()

    result = processor.process(_sample(0, 5.0), config, context)
    updates = {update.path: update.value for update in result.state_updates}

    assert updates[("operating_state_snapshot_by_circuit", "washer")][
        "threshold_source"
    ] == "learned_recommendation"


def test_energy_usage_processor_updates_state_and_returns_spike_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.energy_usage import (
        EnergyUsageProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    state = AnalyzerState()
    store_data = FeatureStoreData(
        energy_usage_by_circuit={
            "fridge": {
                "last_energy_kwh": 100.0,
                "last_sample_at": (now - timedelta(days=1)).isoformat(),
                "days": [
                    {
                        "date": (now.date() - timedelta(days=offset)).isoformat(),
                        "usage_kwh": 10.0,
                        "complete": True,
                    }
                    for offset in range(1, 6)
                ],
            }
        }
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=state,
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = EnergyUsageProcessor(
        settings_for_config=lambda _config, _circuit_id: EnergyUsageSettings(
            window_days=5,
            daily_spike_ratio=0.25,
        ),
        retention_days_for_circuit=lambda _circuit_id: 45,
        alert_policy_for_circuit=lambda _circuit_id: policy,
    )

    result = processor.process(_energy_sample(112.9), config, context)

    assert result.store_dirty is True
    assert result.events == []
    assert len(result.state_updates) == 4
    assert len(result.alerts) == 1
    assert result.notifications == result.alerts
    assert policy.observations[0].feature == "daily_energy_usage_spike"
    assert policy.observations[0].observed_value == 12.9
    assert policy.observations[0].baseline_value == 12.5
    assert "Kitchen Fridge used 12.9 kWh today" in result.alerts[0].message

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("daily_energy_usage_by_circuit", "fridge")] == 12.9
    assert updates[("average_kwh_per_day_by_circuit", "fridge")] == 10.0
    assert updates[("energy_usage_share_by_circuit", "fridge")] == 25.8
    evidence = updates[("energy_usage_evidence_by_circuit", "fridge")]
    assert evidence["status"] == "over_threshold"
    assert evidence["daily_usage_share_percent"] == 25.8
    assert store_data.energy_usage_by_circuit["fridge"]["last_energy_kwh"] == 112.9


def test_energy_usage_processor_excludes_delta_spanning_completed_maintenance() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.energy_usage import (
        EnergyUsageProcessor,
    )

    now = datetime(2026, 7, 28, 0, 5, tzinfo=UTC)
    previous_day = now - timedelta(days=1)
    store_data = FeatureStoreData(
        energy_usage_by_circuit={
            "water_heater": {
                "last_energy_kwh": 100.0,
                "last_sample_at": previous_day.replace(hour=23, minute=50).isoformat(),
                "coverage_date": previous_day.date().isoformat(),
                "coverage_first_sample_at": previous_day.replace(
                    hour=0,
                    minute=5,
                ).isoformat(),
                "coverage_last_sample_at": previous_day.replace(
                    hour=23,
                    minute=50,
                ).isoformat(),
                "days": [
                    {
                        "date": previous_day.date().isoformat(),
                        "usage_kwh": 8.0,
                    }
                ],
            }
        },
        maintenance_by_circuit={
            "water_heater": {
                "active": False,
                "started_at": previous_day.replace(hour=23, minute=55).isoformat(),
                "ended_at": now.replace(minute=2).isoformat(),
            }
        },
        contextual_baseline_samples_by_circuit={
            "water_heater": [
                {
                    "timestamp": previous_day.replace(hour=23, minute=50).isoformat(),
                    "feature": "daily_energy_kwh",
                    "value": 8.0,
                    "context": {"season": "summer"},
                    "source": "energy_usage",
                },
                {
                    "timestamp": now.isoformat(),
                    "feature": "cost_today",
                    "value": 1.0,
                    "context": {"season": "summer"},
                    "source": "cost",
                },
            ]
        },
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
        time_zone="UTC",
    )
    config = CircuitConfig(
        circuit_id="water_heater",
        name="Water Heater",
        appliance_profile=ApplianceProfile.WATER_HEATER,
        mode=CircuitMode.SINGLE_PHASE,
    )
    processor = EnergyUsageProcessor(
        settings_for_config=lambda _config, _circuit_id: EnergyUsageSettings(),
        retention_days_for_circuit=lambda _circuit_id: 45,
        alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
    )

    result = processor.process(_energy_sample(101.0), config, context)

    assert store_data.energy_usage_by_circuit["water_heater"]["days"] == [
        {
            "date": "2026-07-27",
            "usage_kwh": 8.0,
            "complete": True,
            "baseline_eligible": False,
        },
        {
            "date": "2026-07-28",
            "usage_kwh": 1.0,
            "baseline_eligible": False,
        },
    ]
    evidence = {
        update.path: update.value for update in result.state_updates
    }[("energy_usage_evidence_by_circuit", "water_heater")]
    assert evidence["baseline_day_count"] == 0
    assert store_data.contextual_baseline_samples_by_circuit == {}

    processor.process(
        _energy_sample(102.0),
        config,
        replace(context, now=now + timedelta(minutes=30)),
    )

    assert store_data.contextual_baseline_samples_by_circuit == {}


def _energy_usage_projection_evidence(
    days: list[dict[str, object]],
) -> dict[str, object]:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.energy_usage import (
        EnergyUsageProcessor,
    )

    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    context_key = {
        "appliance_profile": "refrigerator",
        "circuit_mode": "single_phase",
        "season": "summer",
        "time_of_day": "morning",
    }
    store_data = FeatureStoreData(
        energy_usage_by_circuit={
            "fridge": {
                "last_energy_kwh": 100.0,
                "last_sample_at": (now - timedelta(days=1)).isoformat(),
                "days": days,
            }
        },
        contextual_baseline_samples_by_circuit={
            "fridge": [
                {
                    "timestamp": (now - timedelta(days=offset)).isoformat(),
                    "feature": "daily_energy_kwh",
                    "value": 5.0,
                    "context": stored_context,
                    "source": "energy_usage",
                }
                for stored_context in (
                    context_key,
                    {**context_key, "day_progress": "30-40%"},
                )
                for offset in range(1, 8)
            ]
        },
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
        time_zone="America/New_York",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    processor = EnergyUsageProcessor(
        settings_for_config=lambda _config, _circuit_id: EnergyUsageSettings(
            window_days=5,
        ),
        retention_days_for_circuit=lambda _circuit_id: 45,
        alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
    )

    result = processor.process(_energy_sample(105.0), config, context)
    updates = {update.path: update.value for update in result.state_updates}
    return updates[("energy_usage_evidence_by_circuit", "fridge")]


def test_energy_usage_projection_rejects_incomplete_days() -> None:
    evidence = _energy_usage_projection_evidence(
        [
            {"date": f"2026-07-{day:02d}", "usage_kwh": usage}
            for day, usage in zip(range(8, 13), range(8, 13), strict=True)
        ]
    )

    assert "projection_value" not in evidence


def test_energy_usage_projection_uses_only_adequate_complete_days() -> None:
    evidence = _energy_usage_projection_evidence(
        [
            {
                "date": f"2026-07-{day:02d}",
                "usage_kwh": usage,
                "complete": True,
            }
            for day, usage in zip(range(6, 11), range(8, 13), strict=True)
        ]
        + [
            {"date": "2026-07-11", "usage_kwh": 100.0, "complete": False},
            {"date": "2026-07-12", "usage_kwh": 100.0, "complete": False},
        ]
    )

    assert evidence["projection_value"] == 10.0
    assert evidence["projection_low"] == 8.0
    assert evidence["projection_high"] == 12.0
    assert evidence["full_period_normal_low"] == 8.0
    assert evidence["full_period_normal_high"] == 12.0
    assert evidence["projection_confidence"] < evidence[
        "contextual_baseline_confidence"
    ]


def test_energy_usage_projection_accepts_days_completed_by_live_tracking() -> None:
    history: dict[str, object] = {}
    settings = EnergyUsageSettings(window_days=5)
    energy = 100.0
    start = datetime(2026, 7, 7, 0, 5, tzinfo=UTC)
    record_energy_usage(
        history,
        circuit_id="fridge",
        timestamp=start,
        energy_kwh=energy,
        settings=settings,
        time_zone="UTC",
    )
    for offset, usage in enumerate(range(8, 13)):
        day_start = start + timedelta(days=offset)
        energy += usage
        record_energy_usage(
            history,
            circuit_id="fridge",
            timestamp=day_start.replace(hour=23, minute=55),
            energy_kwh=energy,
            settings=settings,
            time_zone="UTC",
        )
        record_energy_usage(
            history,
            circuit_id="fridge",
            timestamp=day_start + timedelta(days=1),
            energy_kwh=energy,
            settings=settings,
            time_zone="UTC",
        )

    complete_days = [
        day
        for day in history["days"]
        if isinstance(day, dict) and day.get("complete") is True
    ]
    assert len(complete_days) == 5
    evidence = _energy_usage_projection_evidence(complete_days)
    assert evidence["projection_value"] == 10.0


def test_cycle_same_time_evidence_produces_runtime_and_count_projections() -> None:
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        RUN_CYCLE_RUNTIME_TODAY_FEATURE,
        RUN_CYCLE_START_COUNT_FEATURE,
    )
    from custom_components.circuitsetup_energy_analyzer.managers.ux_state import (
        _same_time_cycle_evidence,
    )

    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    context_key = {
        "appliance_profile": "refrigerator",
        "circuit_mode": "single_phase",
        "day_progress": "50-60%",
        "season": "summer",
        "time_of_day": "afternoon",
    }
    samples = [
        {
            "timestamp": (now - timedelta(days=offset)).isoformat(),
            "feature": feature,
            "value": value,
            "context": context_key,
            "source": "run_cycle",
        }
        for feature, value in (
            (RUN_CYCLE_RUNTIME_TODAY_FEATURE, 3600.0),
            (RUN_CYCLE_START_COUNT_FEATURE, 4.0),
        )
        for offset in range(1, 8)
    ]
    store_data = FeatureStoreData(
        baselines={
            f"fridge:{RUN_CYCLE_RUNTIME_TODAY_FEATURE}": BaselineStats(
                feature=RUN_CYCLE_RUNTIME_TODAY_FEATURE,
                sample_count=14,
                median=7200.0,
                mad=600.0,
                p10=6000.0,
                p90=8400.0,
                confidence=0.9,
            ),
            f"fridge:{RUN_CYCLE_START_COUNT_FEATURE}": BaselineStats(
                feature=RUN_CYCLE_START_COUNT_FEATURE,
                sample_count=14,
                median=8.0,
                mad=1.0,
                p10=6.0,
                p90=10.0,
                confidence=0.9,
            ),
        },
        contextual_baseline_samples_by_circuit={"fridge": samples},
    )

    evidence = _same_time_cycle_evidence(
        config=CircuitConfig(
            circuit_id="fridge",
            name="Kitchen Fridge",
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            mode=CircuitMode.SINGLE_PHASE,
        ),
        sample=None,
        state=SimpleNamespace(),
        store_data=store_data,
        summary=SimpleNamespace(runtime_seconds=3600.0, start_count=4),
        now=now,
        time_zone="UTC",
    )

    assert evidence["runtime_today_contextual_expected_range_seconds"] == [
        3600.0,
        3600.0,
    ]
    assert evidence["runtime_today_projection_value"] == 7200.0
    assert evidence["run_count_projection_value"] == 8.0
    assert evidence["runtime_today_projection_confidence"] < evidence[
        "runtime_today_contextual_baseline_confidence"
    ]


def test_energy_usage_processor_suppresses_spike_when_context_explains_usage() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.energy_usage import (
        EnergyUsageProcessor,
    )

    now = datetime(2026, 6, 17, 15, 0, tzinfo=UTC)
    context_key = {
        "appliance_profile": "hvac",
        "circuit_mode": "dual_phase",
        "day_progress": "60-70%",
        "season": "summer",
        "temperature_bin": "very_hot",
        "time_of_day": "afternoon",
        "weather_mode": "cooling",
    }
    store_data = FeatureStoreData(
        energy_usage_by_circuit={
            "hvac": {
                "last_energy_kwh": 100.0,
                "last_sample_at": (now - timedelta(days=1)).isoformat(),
                "days": [
                    {
                        "date": (now.date() - timedelta(days=offset)).isoformat(),
                        "usage_kwh": 10.0,
                        "complete": True,
                    }
                    for offset in range(1, 6)
                ],
            }
        },
        contextual_baseline_samples_by_circuit={
            "hvac": [
                {
                    "timestamp": (now - timedelta(days=offset)).isoformat(),
                    "feature": "daily_energy_kwh",
                    "value": value,
                    "context": context_key,
                    "source": "energy_usage",
                }
                for offset, value in enumerate(
                    [13.1, 13.6, 14.0, 14.4, 14.7, 15.0, 15.2],
                    start=1,
                )
            ]
        },
    )
    state = AnalyzerState(
        weather_context_by_circuit={
            "hvac": {
                "temperature_f": 94.0,
                "mode": "cooling",
            }
        }
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=state,
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = EnergyUsageProcessor(
        settings_for_config=lambda _config, _circuit_id: EnergyUsageSettings(
            window_days=5,
            daily_spike_ratio=0.25,
        ),
        retention_days_for_circuit=lambda _circuit_id: 45,
        alert_policy_for_circuit=lambda _circuit_id: policy,
    )

    result = processor.process(_energy_sample(114.0), config, context)

    assert result.alerts == []
    assert policy.observations == []
    updates = {update.path: update.value for update in result.state_updates}
    evidence = updates[("energy_usage_evidence_by_circuit", "hvac")]
    assert evidence["status"] == "context_explained"
    assert evidence["comparison_basis"] == "contextual"
    assert evidence["baseline_fallback_level"] == "exact_context"
    assert evidence["baseline_sample_count"] == 7
    assert evidence["contextual_baseline_median_kwh"] == 14.4
    assert evidence["contextual_baseline_p90_kwh"] == 15.0
    assert store_data.energy_usage_by_circuit["hvac"]["days"][-1][
        "expected_context"
    ] is True
    assert "daily_energy_kwh" in (
        store_data.contextual_baseline_samples_by_circuit["hvac"][-1]["feature"]
    )


def test_energy_usage_processor_keeps_rolling_alert_when_context_is_sparse() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.energy_usage import (
        EnergyUsageProcessor,
    )

    now = datetime(2026, 6, 17, 15, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        energy_usage_by_circuit={
            "hvac": {
                "last_energy_kwh": 100.0,
                "last_sample_at": (now - timedelta(days=1)).isoformat(),
                "days": [
                    {
                        "date": (now.date() - timedelta(days=offset)).isoformat(),
                        "usage_kwh": 10.0,
                        "complete": True,
                    }
                    for offset in range(1, 6)
                ],
            }
        },
        contextual_baseline_samples_by_circuit={
            "hvac": [
                {
                    "timestamp": (now - timedelta(days=offset)).isoformat(),
                    "feature": "daily_energy_kwh",
                    "value": 14.0,
                    "context": {
                        "season": "summer",
                        "temperature_bin": "very_hot",
                        "weather_mode": "cooling",
                    },
                    "source": "energy_usage",
                }
                for offset in range(1, 4)
            ]
        },
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(
            weather_context_by_circuit={
                "hvac": {
                    "temperature_f": 94.0,
                    "mode": "cooling",
                }
            }
        ),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = EnergyUsageProcessor(
        settings_for_config=lambda _config, _circuit_id: EnergyUsageSettings(
            window_days=5,
            daily_spike_ratio=0.25,
        ),
        retention_days_for_circuit=lambda _circuit_id: 45,
        alert_policy_for_circuit=lambda _circuit_id: policy,
    )

    result = processor.process(_energy_sample(114.0), config, context)

    assert len(result.alerts) == 1
    assert policy.observations[0].baseline_value == 12.5
    updates = {update.path: update.value for update in result.state_updates}
    evidence = updates[("energy_usage_evidence_by_circuit", "hvac")]
    assert evidence["status"] == "over_threshold"
    assert evidence["comparison_basis"] == "rolling"
    assert evidence["baseline_fallback_level"] == "not_enough_data"


def test_energy_usage_context_uses_local_progress_across_dst_fallback() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.energy_usage import (
        EnergyUsageProcessor,
    )

    now = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    sample_time = datetime(2026, 10, 30, 15, 30, tzinfo=UTC)
    store_data = FeatureStoreData(
        energy_usage_by_circuit={
            "ev": {
                "last_energy_kwh": 100.0,
                "last_sample_at": (now - timedelta(days=1)).isoformat(),
            }
        }
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
        time_zone="America/New_York",
    )
    config = CircuitConfig(
        circuit_id="ev",
        name="EV Charger",
        appliance_profile=ApplianceProfile.EV_CHARGER,
        mode=CircuitMode.DUAL_PHASE,
    )
    processor = EnergyUsageProcessor(
        settings_for_config=lambda _config, _circuit_id: EnergyUsageSettings(),
        retention_days_for_circuit=lambda _circuit_id: 45,
        alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
    )
    sample = CircuitSample(
        timestamp=sample_time,
        circuit_id="ev",
        real_power=180.0,
        current=1.5,
        voltage=120.0,
        energy=104.0,
    )

    processor.process(sample, config, context)

    stored = store_data.contextual_baseline_samples_by_circuit["ev"][0]
    assert stored["timestamp"] == now.isoformat()
    assert stored["context"]["time_of_day"] == "night"
    assert stored["context"]["day_progress"] == "0-10%"


def test_energy_usage_processor_skips_contextual_learning_during_maintenance() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.energy_usage import (
        EnergyUsageProcessor,
    )

    now = datetime(2026, 6, 1, 3, 30, tzinfo=UTC)
    store_data = FeatureStoreData(
        energy_usage_by_circuit={
            "ev": {
                "last_energy_kwh": 100.0,
                "last_sample_at": (now - timedelta(days=1)).isoformat(),
            }
        },
        maintenance_by_circuit={"ev": {"active": True}},
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
        time_zone="America/New_York",
    )
    config = CircuitConfig(
        circuit_id="ev",
        name="EV Charger",
        appliance_profile=ApplianceProfile.EV_CHARGER,
        mode=CircuitMode.DUAL_PHASE,
    )
    processor = EnergyUsageProcessor(
        settings_for_config=lambda _config, _circuit_id: EnergyUsageSettings(),
        retention_days_for_circuit=lambda _circuit_id: 45,
        alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
    )
    sample = CircuitSample(
        timestamp=now,
        circuit_id="ev",
        real_power=180.0,
        current=1.5,
        voltage=120.0,
        energy=104.0,
    )

    processor.process(sample, config, context)

    assert store_data.contextual_baseline_samples_by_circuit == {}
    assert store_data.energy_usage_by_circuit["ev"]["days"] == [
        {
            "date": "2026-05-31",
            "usage_kwh": 4.0,
            "baseline_eligible": False,
        }
    ]


def test_energy_usage_alert_features_include_contextual_baseline_details() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.energy_usage import (
        EnergyUsageProcessor,
    )

    now = datetime(2026, 6, 17, 15, 0, tzinfo=UTC)
    context_key = {
        "appliance_profile": "hvac",
        "circuit_mode": "dual_phase",
        "day_progress": "60-70%",
        "season": "summer",
        "temperature_bin": "very_hot",
        "time_of_day": "afternoon",
        "weather_mode": "cooling",
    }
    store_data = FeatureStoreData(
        energy_usage_by_circuit={
            "hvac": {
                "last_energy_kwh": 100.0,
                "last_sample_at": (now - timedelta(days=1)).isoformat(),
                "days": [
                    {
                        "date": (now.date() - timedelta(days=offset)).isoformat(),
                        "usage_kwh": 10.0,
                        "complete": True,
                    }
                    for offset in range(1, 6)
                ],
            }
        },
        contextual_baseline_samples_by_circuit={
            "hvac": [
                {
                    "timestamp": (now - timedelta(days=offset)).isoformat(),
                    "feature": "daily_energy_kwh",
                    "value": value,
                    "context": context_key,
                    "source": "energy_usage",
                }
                for offset, value in enumerate(
                    [10.8, 11.0, 11.4, 11.8, 12.0, 12.2, 12.5],
                    start=1,
                )
            ]
        },
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(
            weather_context_by_circuit={
                "hvac": {
                    "temperature_f": 94.0,
                    "mode": "cooling",
                }
            }
        ),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = EnergyUsageProcessor(
        settings_for_config=lambda _config, _circuit_id: EnergyUsageSettings(
            window_days=5,
            daily_spike_ratio=0.25,
        ),
        retention_days_for_circuit=lambda _circuit_id: 45,
        alert_policy_for_circuit=lambda _circuit_id: policy,
    )

    result = processor.process(_energy_sample(114.0), config, context)

    assert len(result.alerts) == 1
    assert policy.observations[0].features["comparison_basis"] == "contextual"
    assert policy.observations[0].features["baseline_context"] == (
        "hvac, dual_phase, 60-70%, summer, very_hot, afternoon, cooling"
    )
    assert policy.observations[0].features["baseline_fallback_level"] == (
        "exact_context"
    )
    assert policy.observations[0].features["contextual_baseline_confidence"] == 1.0
    assert result.alerts[0].features["baseline_context"] == (
        "hvac, dual_phase, 60-70%, summer, very_hot, afternoon, cooling"
    )


def test_energy_goal_processor_updates_state_and_returns_goal_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.energy_goal import (
        EnergyGoalProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    state = AnalyzerState(
        daily_energy_usage_by_circuit={"fridge": 20.5},
        energy_usage_evidence_by_circuit={
            "fridge": {
                "date": now.date().isoformat(),
                "daily_usage_kwh": 20.5,
            }
        },
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=state,
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = EnergyGoalProcessor(
        settings_for_config=lambda _config, _circuit_id: EnergyGoalSettings(
            daily_goal_kwh=20.0,
            goal_alert_ratio=0.9,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
    )

    result = processor.process(_energy_sample(120.5), config, context)

    assert result.store_dirty is False
    assert len(result.state_updates) == 3
    assert len(result.alerts) == 1
    assert result.notifications == result.alerts
    assert policy.observations[0].feature == "daily_energy_goal"
    assert policy.observations[0].observed_value == 20.5
    assert policy.observations[0].baseline_value == 20.0
    assert "Kitchen Fridge used 20.5 kWh today" in result.alerts[0].message

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("energy_goal_usage_by_circuit", "fridge")] == 102.5
    assert updates[("energy_goal_status_by_circuit", "fridge")] == "over_goal"
    evidence = updates[("energy_goal_evidence_by_circuit", "fridge")]
    assert evidence == {
        "date": "2026-06-11",
        "daily_usage_kwh": 20.5,
        "daily_goal_kwh": 20.0,
        "goal_usage_percent": 102.5,
        "alert_threshold_kwh": 18.0,
        "goal_alert_ratio": 0.9,
        "status": "over_goal",
    }


def test_energy_goal_processor_uses_ha_local_usage_date() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.energy_goal import (
        EnergyGoalProcessor,
    )

    now = datetime(2026, 6, 18, 2, 0, tzinfo=UTC)
    state = AnalyzerState(
        daily_energy_usage_by_circuit={"fridge": 20.5},
        energy_usage_evidence_by_circuit={
            "fridge": {
                "date": "2026-06-17",
                "daily_usage_kwh": 20.5,
            }
        },
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=state,
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
        time_zone="America/New_York",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = EnergyGoalProcessor(
        settings_for_config=lambda _config, _circuit_id: EnergyGoalSettings(
            daily_goal_kwh=20.0,
            goal_alert_ratio=0.9,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
    )

    result = processor.process(_energy_sample(120.5), config, context)

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("energy_goal_status_by_circuit", "fridge")] == "over_goal"
    assert result.alerts


def test_cold_storage_signature_alerts_after_three_windows_during_shared_learning(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cycles import (
        RunCycleProcessor,
    )

    start = datetime(2026, 7, 29, 20, 30, tzinfo=UTC)
    state = AnalyzerState(learning_by_circuit={"fridge": True})
    store_data = FeatureStoreData(baselines=_cold_storage_baselines())
    policy = ConservativeAlertPolicy()
    processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
        learning_mature=lambda _config, _now: False,
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Basement Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    alerts = []
    for minute in range(0, 91, 5):
        now = start + timedelta(minutes=minute)
        context = ProcessingContext(
            now=now,
            hass=SimpleNamespace(data={DOMAIN: {}}),
            state=state,
            store_data=store_data,
            options={},
            entry_data={},
            known_load_circuit_ids=frozenset(),
            sensitivity="standard",
        )
        pulse = minute % 20 == 0
        result = processor.process(
            _cold_storage_sample(now, pulse=pulse, abnormal=True),
            config,
            context,
        )
        alerts.extend(result.alerts)
        if result.alerts:
            state.active_alerts_by_circuit["fridge"] = list(result.alerts)

    assert len(alerts) == 1
    assert alerts[0].feature == "cold_storage_cycle_signature_change"
    assert alerts[0].first_seen == start + timedelta(minutes=30)
    assert alerts[0].last_seen == start + timedelta(minutes=90)


def test_cold_storage_signature_preserves_then_recovers_after_two_normal_windows(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cycles import (
        RunCycleProcessor,
    )

    start = datetime(2026, 7, 29, 20, 30, tzinfo=UTC)
    state = AnalyzerState(learning_by_circuit={"fridge": True})
    store_data = FeatureStoreData(baselines=_cold_storage_baselines())
    policy = ConservativeAlertPolicy()
    processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
        learning_mature=lambda _config, _now: False,
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Basement Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )

    def run(minute: int, *, abnormal: bool):
        now = start + timedelta(minutes=minute)
        result = processor.process(
            _cold_storage_sample(
                now,
                pulse=minute % 20 == 0,
                abnormal=abnormal,
            ),
            config,
            ProcessingContext(
                now=now,
                hass=SimpleNamespace(data={DOMAIN: {}}),
                state=state,
                store_data=store_data,
                options={},
                entry_data={},
                known_load_circuit_ids=frozenset(),
                sensitivity="standard",
            ),
        )
        if result.alerts:
            state.active_alerts_by_circuit["fridge"] = list(result.alerts)
        return result

    for minute in range(0, 91, 5):
        alert_result = run(minute, abnormal=True)
    active_alert = alert_result.alerts[0]

    for minute in range(95, 121, 5):
        first_recovery = run(minute, abnormal=False)
    assert first_recovery.preserved_alerts == [active_alert]

    for minute in range(125, 151, 5):
        second_recovery = run(minute, abnormal=False)
    assert second_recovery.preserved_alerts == []
    state.active_alerts_by_circuit.pop("fridge")

    for minute in range(155, 181, 5):
        one_later_anomaly = run(minute, abnormal=True)
    assert one_later_anomaly.alerts == []


def test_cold_storage_invalid_window_restarts_recovery_streak() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cycles import (
        RunCycleProcessor,
    )

    start = datetime(2026, 7, 29, 20, 30, tzinfo=UTC)
    state = AnalyzerState(learning_by_circuit={"fridge": True})
    policy = ConservativeAlertPolicy()
    processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
        learning_mature=lambda _config, _now: False,
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Basement Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    store_data = FeatureStoreData(baselines=_cold_storage_baselines())

    def run(minute: int, *, abnormal: bool):
        now = start + timedelta(minutes=minute)
        result = processor.process(
            _cold_storage_sample(
                now,
                pulse=minute % 20 == 0,
                abnormal=abnormal,
            ),
            config,
            ProcessingContext(
                now=now,
                hass=SimpleNamespace(data={DOMAIN: {}}),
                state=state,
                store_data=store_data,
                options={},
                entry_data={},
                known_load_circuit_ids=frozenset(),
                sensitivity="standard",
            ),
        )
        if result.alerts:
            state.active_alerts_by_circuit["fridge"] = list(result.alerts)
        return result

    for minute in range(0, 91, 5):
        alert_result = run(minute, abnormal=True)
    active_alert = alert_result.alerts[0]

    for minute in range(95, 121, 5):
        first_normal = run(minute, abnormal=False)
    assert first_normal.preserved_alerts == [active_alert]

    run(145, abnormal=False)
    invalid = run(150, abnormal=False)
    assert invalid.preserved_alerts == [active_alert]

    for minute in range(155, 181, 5):
        normal_after_invalid = run(minute, abnormal=False)
    assert normal_after_invalid.preserved_alerts == [active_alert]


def test_cold_storage_active_alert_still_records_each_anomalous_window() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cycles import (
        RunCycleProcessor,
    )

    start = datetime(2026, 7, 29, 20, 30, tzinfo=UTC)
    state = AnalyzerState(learning_by_circuit={"fridge": True})
    policy = ConservativeAlertPolicy()
    processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
        learning_mature=lambda _config, _now: False,
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Basement Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    store_data = FeatureStoreData(baselines=_cold_storage_baselines())

    def run(minute: int):
        now = start + timedelta(minutes=minute)
        result = processor.process(
            _cold_storage_sample(
                now,
                pulse=minute % 20 == 0,
                abnormal=True,
            ),
            config,
            ProcessingContext(
                now=now,
                hass=SimpleNamespace(data={DOMAIN: {}}),
                state=state,
                store_data=store_data,
                options={},
                entry_data={},
                known_load_circuit_ids=frozenset(),
                sensitivity="standard",
            ),
        )
        if result.alerts:
            state.active_alerts_by_circuit["fridge"] = list(result.alerts)
        return result

    for minute in range(0, 91, 5):
        alert_result = run(minute)
    active_alert = alert_result.alerts[0]

    for minute in range(95, 121, 5):
        ongoing_anomaly = run(minute)

    assert len(ongoing_anomaly.observations) == 1
    assert ongoing_anomaly.observations[0].observed_at == start + timedelta(
        minutes=120
    )
    assert ongoing_anomaly.alerts == []
    assert ongoing_anomaly.preserved_alerts == [active_alert]


def test_cold_storage_signature_missing_metrics_do_not_clear_active_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cycles import (
        RunCycleProcessor,
    )

    now = datetime(2026, 7, 29, 22, 5, tzinfo=UTC)
    active_alert = AlertEvidence(
        timestamp=now,
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Compressor signature changed.",
        feature="cold_storage_cycle_signature_change",
        features={
            "signature_ready": True,
            "signature_baseline_windows": 96.0,
            "signature_baseline_confidence": 1.0,
        },
    )
    state = AnalyzerState(
        active_alerts_by_circuit={"fridge": [active_alert]},
        learning_by_circuit={"fridge": True},
    )
    store_data = FeatureStoreData(baselines=_cold_storage_baselines())
    processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda _circuit_id: ConservativeAlertPolicy(),
        learning_mature=lambda _config, _now: False,
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Basement Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )

    result = processor.process(
        replace(
            _cold_storage_sample(now, pulse=False, abnormal=True),
            power_factor=None,
        ),
        config,
        ProcessingContext(
            now=now,
            hass=SimpleNamespace(data={DOMAIN: {}}),
            state=state,
            store_data=store_data,
            options={},
            entry_data={},
            known_load_circuit_ids=frozenset(),
            sensitivity="standard",
        ),
    )

    assert result.alerts == []
    assert result.preserved_alerts == [active_alert]


def test_cold_storage_signature_persists_96_window_baseline_across_restart() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cycles import (
        RunCycleProcessor,
    )

    start = datetime(2026, 7, 1, tzinfo=UTC)
    state = AnalyzerState(learning_by_circuit={"fridge": True})
    store_data = FeatureStoreData()
    policy = ConservativeAlertPolicy()
    config = CircuitConfig(
        circuit_id="fridge",
        name="Basement Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )

    def feed(
        processor: RunCycleProcessor,
        first_minute: int,
        last_minute: int,
        *,
        abnormal: bool,
    ) -> None:
        for minute in range(first_minute, last_minute + 1, 5):
            now = start + timedelta(minutes=minute)
            processor.process(
                _cold_storage_sample(
                    now,
                    pulse=minute % 20 == 0,
                    abnormal=abnormal,
                ),
                config,
                ProcessingContext(
                    now=now,
                    hass=SimpleNamespace(data={DOMAIN: {}}),
                    state=state,
                    store_data=store_data,
                    options={},
                    entry_data={},
                    known_load_circuit_ids=frozenset(),
                    sensitivity="standard",
                ),
            )

    first_processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
        learning_mature=lambda _config, _now: False,
    )
    feed(first_processor, 0, 48 * 30, abnormal=False)

    restarted_processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
        learning_mature=lambda _config, _now: False,
    )
    feed(restarted_processor, 48 * 30, 96 * 30, abnormal=False)

    assert store_data.baselines["fridge:cold_storage_pf_peak_delta"].sample_count == 96
    assert store_data.baselines["fridge:cold_storage_pf_peak_delta"].median == 0.26
    assert store_data.baselines["fridge:cold_storage_median_power_w"].median == 100.0
    assert store_data.baselines["fridge:cold_storage_median_current_a"].median == 1.2
    assert not any(
        row.get("source") == "cold_storage_signature"
        for row in store_data.contextual_baseline_samples_by_circuit.get("fridge", [])
    )
    learned_baselines = dict(store_data.baselines)

    anomaly_processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
        learning_mature=lambda _config, _now: False,
    )
    feed(anomaly_processor, 96 * 30, 97 * 30, abnormal=True)

    assert store_data.baselines == learned_baselines


def test_run_cycle_processor_builds_baseline_and_returns_long_cycle_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        RUN_CYCLE_DURATION_FEATURE,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cycles import (
        RunCycleProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    events: list[CircuitEvent] = []
    for offset in range(1, 10):
        started_at = now - timedelta(days=offset, hours=1)
        events.extend(
            [
                CircuitEvent(
                    timestamp=started_at,
                    circuit_id="fridge",
                    event_type=EventType.START,
                ),
                CircuitEvent(
                    timestamp=started_at + timedelta(minutes=20),
                    circuit_id="fridge",
                    event_type=EventType.STOP,
                ),
            ]
        )
    events.append(
        CircuitEvent(
            timestamp=now - timedelta(hours=1),
            circuit_id="fridge",
            event_type=EventType.START,
        )
    )
    store_data = FeatureStoreData(events=events)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
        learning_mature=lambda _config, _now: True,
    )

    result = processor.process(_energy_sample(120.5), config, context)

    assert result.store_dirty is True
    assert len(result.alerts) == 1
    assert result.notifications == result.alerts
    assert policy.observations[0].feature == RUN_CYCLE_DURATION_FEATURE
    assert policy.observations[0].observed_value == 3600.0
    assert policy.observations[0].baseline_value == 1200.0
    assert "Kitchen Fridge has been running for 1 h" in result.alerts[0].message

    baseline = store_data.baselines["fridge:run_cycle_duration_s"]
    assert baseline.feature == RUN_CYCLE_DURATION_FEATURE
    assert baseline.median == 1200.0


def test_run_cycle_processor_context_uses_rollup_timestamp() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cycles import (
        RunCycleProcessor,
    )

    now = datetime(2026, 6, 1, 3, 30, tzinfo=UTC)
    sample_time = datetime(2026, 5, 30, 15, 30, tzinfo=UTC)
    events = [
        CircuitEvent(
            timestamp=now - timedelta(hours=1),
            circuit_id="fridge",
            event_type=EventType.START,
        ),
        CircuitEvent(
            timestamp=now - timedelta(minutes=30),
            circuit_id="fridge",
            event_type=EventType.STOP,
        ),
    ]
    store_data = FeatureStoreData(events=events)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
        time_zone="America/New_York",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
        learning_mature=lambda _config, _now: False,
    )
    sample = CircuitSample(
        timestamp=sample_time,
        circuit_id="fridge",
        real_power=180.0,
        current=1.5,
        voltage=120.0,
    )

    processor.process(sample, config, context)

    stored = store_data.contextual_baseline_samples_by_circuit["fridge"][0]
    assert stored["timestamp"] == now.isoformat()
    assert stored["context"]["time_of_day"] == "evening"


def test_run_cycle_processor_skips_contextual_learning_for_flagged_day() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cycles import (
        RunCycleProcessor,
    )

    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        events=[
            CircuitEvent(
                timestamp=now - timedelta(hours=2),
                circuit_id="water_heater",
                event_type=EventType.START,
            ),
            CircuitEvent(
                timestamp=now - timedelta(hours=1),
                circuit_id="water_heater",
                event_type=EventType.STOP,
                features={"baseline_eligible": False},
            ),
        ],
        contextual_baseline_samples_by_circuit={
            "water_heater": [
                {
                    "timestamp": now.isoformat(),
                    "feature": "runtime_today_seconds",
                    "value": 1800.0,
                    "context": {
                        "appliance_profile": "water_heater",
                        "circuit_mode": "single_phase",
                        "season": "summer",
                        "water_flow_state": "active_flow",
                    },
                    "source": "run_cycle",
                }
            ]
        },
        baselines={
            "water_heater:run_cycle_duration_s": BaselineStats(
                "run_cycle_duration_s",
                9,
                1800.0,
                60.0,
                1700.0,
                1900.0,
                1.0,
            )
        },
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="water_heater",
        name="Water Heater",
        appliance_profile=ApplianceProfile.WATER_HEATER,
        mode=CircuitMode.SINGLE_PHASE,
    )
    processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
        learning_mature=lambda _config, _now: False,
    )

    processor.process(_energy_sample(106.0), config, context)

    assert store_data.contextual_baseline_samples_by_circuit == {}
    assert "water_heater:run_cycle_duration_s" not in store_data.baselines


def test_run_cycle_processor_suppresses_alert_when_context_explains_runtime() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        RUN_CYCLE_DURATION_FEATURE,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cycles import (
        RunCycleProcessor,
    )

    now = datetime(2026, 6, 17, 15, 0, tzinfo=UTC)
    events: list[CircuitEvent] = []
    for offset in range(1, 10):
        started_at = now - timedelta(days=offset, hours=1)
        events.extend(
            [
                CircuitEvent(
                    timestamp=started_at,
                    circuit_id="hvac",
                    event_type=EventType.START,
                ),
                CircuitEvent(
                    timestamp=started_at + timedelta(minutes=20),
                    circuit_id="hvac",
                    event_type=EventType.STOP,
                ),
            ]
        )
    events.append(
        CircuitEvent(
            timestamp=now - timedelta(hours=1),
            circuit_id="hvac",
            event_type=EventType.START,
        )
    )
    context_key = {
        "appliance_profile": "hvac",
        "circuit_mode": "dual_phase",
        "day_progress": "60-70%",
        "season": "summer",
        "temperature_bin": "very_hot",
        "time_of_day": "afternoon",
        "weather_mode": "cooling",
    }
    store_data = FeatureStoreData(
        events=events,
        contextual_baseline_samples_by_circuit={
            "hvac": [
                {
                    "timestamp": (now - timedelta(days=offset)).isoformat(),
                    "feature": RUN_CYCLE_DURATION_FEATURE,
                    "value": value,
                    "context": context_key,
                    "source": "run_cycle",
                }
                for offset, value in enumerate(
                    [3300.0, 3400.0, 3500.0, 3600.0, 3650.0, 3700.0, 3800.0],
                    start=1,
                )
            ]
        },
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(
            weather_context_by_circuit={
                "hvac": {
                    "temperature_f": 94.0,
                    "mode": "cooling",
                }
            }
        ),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
        learning_mature=lambda _config, _now: True,
    )

    result = processor.process(_energy_sample(120.5), config, context)

    assert result.alerts == []
    assert policy.observations == []


def test_run_cycle_alert_features_include_contextual_baseline_details() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        RUN_CYCLE_DURATION_FEATURE,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cycles import (
        RunCycleProcessor,
    )

    now = datetime(2026, 6, 17, 15, 0, tzinfo=UTC)
    events: list[CircuitEvent] = []
    for offset in range(1, 10):
        started_at = now - timedelta(days=offset, hours=1)
        events.extend(
            [
                CircuitEvent(
                    timestamp=started_at,
                    circuit_id="hvac",
                    event_type=EventType.START,
                ),
                CircuitEvent(
                    timestamp=started_at + timedelta(minutes=20),
                    circuit_id="hvac",
                    event_type=EventType.STOP,
                ),
            ]
        )
    events.append(
        CircuitEvent(
            timestamp=now - timedelta(hours=1),
            circuit_id="hvac",
            event_type=EventType.START,
        )
    )
    context_key = {
        "appliance_profile": "hvac",
        "circuit_mode": "dual_phase",
        "day_progress": "60-70%",
        "season": "summer",
        "temperature_bin": "very_hot",
        "time_of_day": "afternoon",
        "weather_mode": "cooling",
    }
    store_data = FeatureStoreData(
        events=events,
        contextual_baseline_samples_by_circuit={
            "hvac": [
                {
                    "timestamp": (now - timedelta(days=offset)).isoformat(),
                    "feature": RUN_CYCLE_DURATION_FEATURE,
                    "value": value,
                    "context": context_key,
                    "source": "run_cycle",
                }
                for offset, value in enumerate(
                    [1200.0, 1250.0, 1300.0, 1350.0, 1400.0, 1450.0, 1500.0],
                    start=1,
                )
            ]
        },
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(
            weather_context_by_circuit={
                "hvac": {
                    "temperature_f": 94.0,
                    "mode": "cooling",
                }
            }
        ),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
        learning_mature=lambda _config, _now: True,
    )

    result = processor.process(_energy_sample(120.5), config, context)

    assert len(result.alerts) == 1
    assert policy.observations[0].baseline_value == 1450.0
    assert policy.observations[0].features["comparison_basis"] == "contextual"
    assert policy.observations[0].features["baseline_fallback_level"] == (
        "exact_context"
    )
    assert policy.observations[0].features["baseline_context"] == (
        "hvac, dual_phase, 60-70%, summer, very_hot, afternoon, cooling"
    )
    assert policy.observations[0].features["contextual_baseline_p90"] == 1450.0
    assert result.alerts[0].features["comparison_basis"] == "contextual"


def test_activity_alert_processor_returns_left_on_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.activity import (
        ActivityAlertProcessor,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        events=[
            CircuitEvent(
                timestamp=now - timedelta(minutes=45),
                circuit_id="dryer",
                event_type=EventType.START,
            )
        ]
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="dryer",
        name="Dryer",
        appliance_profile=ApplianceProfile.DRYER,
        mode=CircuitMode.SINGLE_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = ActivityAlertProcessor(
        settings_for_config=lambda _config, _circuit_id: ActivityAlertSettings(
            max_active_minutes=30.0,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
    )

    result = processor.process(_energy_sample(1.0), config, context)

    assert result.store_dirty is False
    assert len(result.alerts) == 1
    assert result.notifications == result.alerts
    assert policy.observations[0].feature == "activity_left_on"
    assert policy.observations[0].observed_value == 45.0
    assert policy.observations[0].baseline_value == 30.0
    assert "Dryer has been active for 45 minutes" in result.alerts[0].message


def test_activity_alert_processor_skips_left_on_for_mains_nilm_config() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.activity import (
        ActivityAlertProcessor,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        events=[
            CircuitEvent(
                timestamp=now - timedelta(minutes=45),
                circuit_id="main_panel",
                event_type=EventType.START,
            )
        ]
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="main_panel",
        name="Main Panel",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    policy = _CaptureAlertPolicy()
    processor = ActivityAlertProcessor(
        settings_for_config=lambda _config, _circuit_id: ActivityAlertSettings(
            max_active_minutes=30.0,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
    )

    result = processor.process(_energy_sample(1.0), config, context)

    assert result.observations == []
    assert result.alerts == []
    assert result.notifications == []
    assert policy.observations == []


@pytest.mark.parametrize(
    ("profile", "mode"),
    (
        (ApplianceProfile.WASHER, CircuitMode.MIXED),
        (ApplianceProfile.MIXED, CircuitMode.SINGLE_PHASE),
    ),
)
def test_activity_alert_processor_skips_idle_alerts_for_mixed_circuits(
    profile: ApplianceProfile, mode: CircuitMode
) -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.activity import (
        ActivityAlertProcessor,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=now - timedelta(minutes=45),
                    circuit_id="washer",
                    event_type=EventType.STOP,
                )
            ]
        ),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="washer",
        name="Washer",
        appliance_profile=profile,
        mode=mode,
    )
    policy = _CaptureAlertPolicy()
    processor = ActivityAlertProcessor(
        settings_for_config=lambda _config, _circuit_id: ActivityAlertSettings(
            max_idle_minutes=30.0,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
    )

    result = processor.process(_energy_sample(1.0), config, context)

    assert result.observations == []
    assert result.alerts == []
    assert result.notifications == []
    assert policy.observations == []


@pytest.mark.parametrize(
    ("profile", "mode"),
    (
        (ApplianceProfile.WASHER, CircuitMode.MIXED),
        (ApplianceProfile.MIXED, CircuitMode.SINGLE_PHASE),
    ),
)
def test_event_processor_skips_mixed_circuits(
    profile: ApplianceProfile, mode: CircuitMode
) -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.events import (
        CircuitEventProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="washer",
        name="Washer",
        appliance_profile=profile,
        mode=mode,
    )

    processor = CircuitEventProcessor()
    results = [
        processor.process(_sample(seconds, power), config, context)
        for seconds, power in ((0, 5.0), (10, 100.0), (21, 100.0))
    ]

    assert all(result.events == [] for result in results)
    assert all(result.state_updates == [] for result in results)
    assert processor.detectors == {}


@pytest.mark.parametrize(
    ("profile", "mode"),
    (
        (ApplianceProfile.SOLAR_INVERTER, CircuitMode.SINGLE_PHASE),
        (ApplianceProfile.MAINS_NILM, CircuitMode.MAINS_NILM),
    ),
)
def test_event_processor_retains_generic_events_for_non_mixed_circuits(
    profile: ApplianceProfile, mode: CircuitMode
) -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.events import (
        CircuitEventProcessor,
    )

    context = ProcessingContext(
        now=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="source",
        name="Source",
        appliance_profile=profile,
        mode=mode,
    )
    processor = CircuitEventProcessor()

    processor.process(_sample(0, 5.0), config, context)
    processor.process(_sample(10, 100.0), config, context)
    result = processor.process(_sample(30, 100.0), config, context)

    assert [event.event_type for event in result.events] == [EventType.START]
    assert "source" in processor.detectors


def test_run_cycle_processor_returns_observation_without_alert_when_policy_is_not_ready(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        RUN_CYCLE_DURATION_FEATURE,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cycles import (
        RunCycleProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    events = []
    for index in range(10):
        start = now - timedelta(days=10 - index, hours=1)
        stop = start + timedelta(minutes=20)
        events.extend(
            [
                CircuitEvent(
                    timestamp=start,
                    circuit_id="fridge",
                    event_type=EventType.START,
                ),
                CircuitEvent(
                    timestamp=stop,
                    circuit_id="fridge",
                    event_type=EventType.STOP,
                ),
            ]
        )
    events.append(
        CircuitEvent(
            timestamp=now - timedelta(hours=1),
            circuit_id="fridge",
            event_type=EventType.START,
        )
    )
    store_data = FeatureStoreData(events=events)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    policy = _CaptureObservationOnlyPolicy()
    processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
        learning_mature=lambda _config, _now: True,
    )

    result = processor.process(_energy_sample(120.5), config, context)

    assert len(result.observations) == 1
    assert result.alerts == []
    assert result.notifications == []
    assert result.observations[0].feature == RUN_CYCLE_DURATION_FEATURE
    assert policy.observations[0] == result.observations[0]


def test_run_cycle_processor_skips_unavailable_operating_state(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        RUN_CYCLE_DURATION_FEATURE,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cycles import (
        RunCycleProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    events = []
    for index in range(10):
        start = now - timedelta(days=10 - index, hours=1)
        stop = start + timedelta(minutes=20)
        events.extend(
            [
                CircuitEvent(
                    timestamp=start,
                    circuit_id="fridge",
                    event_type=EventType.START,
                ),
                CircuitEvent(
                    timestamp=stop,
                    circuit_id="fridge",
                    event_type=EventType.STOP,
                ),
            ]
        )
    events.append(
        CircuitEvent(
            timestamp=now - timedelta(hours=1),
            circuit_id="fridge",
            event_type=EventType.START,
        )
    )
    state = AnalyzerState(
        operating_state_snapshot_by_circuit={
            "fridge": {
                "state": "unavailable",
                "stable_state": "unavailable",
            }
        }
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=state,
        store_data=FeatureStoreData(events=events),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
        learning_mature=lambda _config, _now: True,
    )

    result = processor.process(_energy_sample(120.5), config, context)

    assert result.observations == []
    assert result.alerts == []
    assert result.notifications == []
    assert RUN_CYCLE_DURATION_FEATURE not in {
        observation.feature for observation in policy.observations
    }


def test_run_cycle_processor_does_not_promote_one_cycle_across_polls() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.cycles import (
        RUN_CYCLE_DURATION_FEATURE,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cycles import (
        RunCycleProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    events = []
    for index in range(10):
        start = now - timedelta(days=10 - index, hours=1)
        stop = start + timedelta(minutes=20)
        events.extend(
            [
                CircuitEvent(
                    timestamp=start,
                    circuit_id="fridge",
                    event_type=EventType.START,
                ),
                CircuitEvent(
                    timestamp=stop,
                    circuit_id="fridge",
                    event_type=EventType.STOP,
                ),
            ]
        )
    events.append(
        CircuitEvent(
            timestamp=now - timedelta(hours=1),
            circuit_id="fridge",
            event_type=EventType.START,
        )
    )
    store_data = FeatureStoreData(events=events)
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    policy = ConservativeAlertPolicy()
    processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
        learning_mature=lambda _config, _now: True,
    )

    results = []
    for offset in range(3):
        context = ProcessingContext(
            now=now + timedelta(minutes=offset),
            hass=SimpleNamespace(data={DOMAIN: {}}),
            state=AnalyzerState(),
            store_data=store_data,
            options={},
            entry_data={},
            known_load_circuit_ids=frozenset(),
            sensitivity="standard",
        )
        results.append(processor.process(_energy_sample(120.5), config, context))

    assert [len(result.observations) for result in results] == [1, 1, 1]
    assert [result.observations[0].feature for result in results] == [
        RUN_CYCLE_DURATION_FEATURE,
        RUN_CYCLE_DURATION_FEATURE,
        RUN_CYCLE_DURATION_FEATURE,
    ]
    assert [result.alerts for result in results] == [[], [], []]
    assert [result.notifications for result in results] == [[], [], []]


def test_activity_alert_processor_returns_observation_without_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.activity import (
        ActivityAlertProcessor,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        events=[
            CircuitEvent(
                timestamp=now - timedelta(minutes=45),
                circuit_id="dryer",
                event_type=EventType.START,
            )
        ]
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="dryer",
        name="Dryer",
        appliance_profile=ApplianceProfile.DRYER,
        mode=CircuitMode.SINGLE_PHASE,
    )
    policy = _CaptureObservationOnlyPolicy()
    processor = ActivityAlertProcessor(
        settings_for_config=lambda _config, _circuit_id: ActivityAlertSettings(
            max_active_minutes=30.0,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
    )

    result = processor.process(_energy_sample(1.0), config, context)

    assert len(result.observations) == 1
    assert result.alerts == []
    assert result.notifications == []
    assert result.observations[0].feature == "activity_left_on"
    assert result.observations[0].observation_key is not None
    assert policy.observations[0].feature == result.observations[0].feature
    assert (
        policy.observations[0].observed_value
        == result.observations[0].observed_value
    )
    assert (
        policy.observations[0].baseline_value
        == result.observations[0].baseline_value
    )
    assert policy.observations[0].message == result.observations[0].message
    assert policy.observations[0].features == result.observations[0].features
    assert policy.observations[0].observation_key is None


def test_activity_alert_processor_promotes_one_session_across_repeated_polls() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.activity import (
        ActivityAlertProcessor,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        events=[
            CircuitEvent(
                timestamp=now - timedelta(minutes=45),
                circuit_id="dryer",
                event_type=EventType.START,
            )
        ]
    )
    config = CircuitConfig(
        circuit_id="dryer",
        name="Dryer",
        appliance_profile=ApplianceProfile.DRYER,
        mode=CircuitMode.SINGLE_PHASE,
    )
    policy = ConservativeAlertPolicy()
    processor = ActivityAlertProcessor(
        settings_for_config=lambda _config, _circuit_id: ActivityAlertSettings(
            max_active_minutes=30.0,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
    )

    results = []
    for offset in range(3):
        context = ProcessingContext(
            now=now + timedelta(minutes=offset),
            hass=SimpleNamespace(data={DOMAIN: {}}),
            state=AnalyzerState(),
            store_data=store_data,
            options={},
            entry_data={},
            known_load_circuit_ids=frozenset(),
            sensitivity="standard",
        )
        results.append(processor.process(_energy_sample(1.0), config, context))

    assert [len(result.observations) for result in results] == [1, 1, 1]
    assert [result.observations[0].feature for result in results] == [
        "activity_left_on",
        "activity_left_on",
        "activity_left_on",
    ]
    assert [result.observations[0].observation_key for result in results] == [
        results[0].observations[0].observation_key,
        results[0].observations[0].observation_key,
        results[0].observations[0].observation_key,
    ]
    assert [len(result.alerts) for result in results] == [0, 0, 1]
    assert results[2].notifications == results[2].alerts
    assert results[2].alerts[0].feature == "activity_left_on"
    assert results[2].alerts[0].repeated_count == 3


def test_activity_alert_processor_skips_unavailable_operating_state(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.activity import (
        ActivityAlertProcessor,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        events=[
            CircuitEvent(
                timestamp=now - timedelta(minutes=45),
                circuit_id="dryer",
                event_type=EventType.START,
            )
        ]
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(
            operating_state_snapshot_by_circuit={
                "dryer": {
                    "state": "unavailable",
                    "stable_state": "unavailable",
                }
            }
        ),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="dryer",
        name="Dryer",
        appliance_profile=ApplianceProfile.DRYER,
        mode=CircuitMode.SINGLE_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = ActivityAlertProcessor(
        settings_for_config=lambda _config, _circuit_id: ActivityAlertSettings(
            max_active_minutes=30.0,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
    )

    result = processor.process(_energy_sample(1.0), config, context)

    assert result.observations == []
    assert result.alerts == []
    assert result.notifications == []
    assert policy.observations == []


def test_billing_cycle_processor_updates_state_and_returns_budget_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.billing import (
        BillingCycleProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        billing_by_circuit={
            "fridge": {
                "cycle_start": "2026-06-01",
                "cycle_usage_kwh": 0.0,
                "last_energy_kwh": 100.0,
                "last_sample_at": "2026-06-10T12:00:00+00:00",
            }
        }
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = BillingCycleProcessor(
        settings_for_config=lambda _config, _circuit_id: BillingCycleSettings(
            cycle_start_day=1,
            budget_kwh=20.0,
            budget_alert_ratio=1.0,
            min_elapsed_days=3,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
    )

    result = processor.process(_energy_sample(110.0), config, context)

    assert result.store_dirty is True
    assert len(result.state_updates) == 5
    assert len(result.alerts) == 1
    assert result.notifications == result.alerts
    assert policy.observations[0].feature == "billing_cycle_budget"
    assert policy.observations[0].observed_value == 27.273
    assert policy.observations[0].baseline_value == 20.0
    assert "Kitchen Fridge is projected to use 27.273 kWh" in result.alerts[0].message

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("billing_cycle_usage_kwh_by_circuit", "fridge")] == 10.0
    assert updates[("billing_cycle_forecast_kwh_by_circuit", "fridge")] == 27.273
    assert updates[("billing_cycle_budget_usage_by_circuit", "fridge")] == 50.0
    assert updates[("billing_cycle_status_by_circuit", "fridge")] == (
        "projected_over_budget"
    )
    evidence = updates[("billing_cycle_evidence_by_circuit", "fridge")]
    assert evidence["cycle_start"] == "2026-06-01"
    assert evidence["cycle_end"] == "2026-07-01"
    assert evidence["cycle_usage_kwh"] == 10.0
    assert evidence["projected_cycle_kwh"] == 27.273
    assert evidence["projected_budget_usage_percent"] == 136.4
    assert evidence["status"] == "projected_over_budget"
    assert store_data.billing_by_circuit["fridge"]["last_energy_kwh"] == 110.0


def test_cost_processor_updates_state_from_flat_rate_delta() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cost import (
        CostProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        cost_by_circuit={
            "fridge": {
                "cycle_start": "2026-06-01",
                "cycle_cost": 0.0,
                "last_energy_kwh": 100.0,
                "last_sample_at": "2026-06-10T12:00:00+00:00",
            }
        }
    )
    state = AnalyzerState()
    state.daily_energy_usage_by_circuit["fridge"] = 2.4
    state.average_kwh_per_day_by_circuit["fridge"] = 1.5
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=state,
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    processor = CostProcessor(
        settings_for_config=lambda _config, _circuit_id: CostSettings(
            cycle_start_day=1,
            default_rate_per_kwh=0.20,
        ),
    )

    result = processor.process(_energy_sample(115.0), config, context)

    assert result.store_dirty is True
    assert result.alerts == []
    assert result.notifications == []
    assert len(result.state_updates) == 11

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("estimated_cost_today_by_circuit", "fridge")] == 0.48
    assert updates[("average_cost_per_day_by_circuit", "fridge")] == 0.3
    assert updates[("effective_electricity_rate_by_circuit", "fridge")] == 0.2
    assert updates[("cost_current_rate_by_circuit", "fridge")] == 0.2
    assert updates[("cost_today_by_circuit", "fridge")] is None
    assert updates[("cost_today_status_by_circuit", "fridge")] == "unavailable"
    assert updates[("cost_cycle_by_circuit", "fridge")] == 3.0
    assert updates[("cost_cycle_status_by_circuit", "fridge")] == "actual"
    assert updates[("cost_cycle_forecast_by_circuit", "fridge")] == 8.18
    assert updates[("cost_status_by_circuit", "fridge")] == "tracking"
    evidence = updates[("cost_evidence_by_circuit", "fridge")]
    assert evidence["cycle_start"] == "2026-06-01"
    assert evidence["cycle_end"] == "2026-07-01"
    assert evidence["delta_kwh"] == 15.0
    assert evidence["delta_cost"] == 3.0
    assert evidence["cycle_cost"] == 3.0
    assert evidence["projected_cycle_cost"] == 8.18
    assert evidence["status"] == "tracking"
    assert store_data.cost_by_circuit["fridge"]["last_energy_kwh"] == 115.0

    no_rate_result = CostProcessor(
        settings_for_config=lambda _config, _circuit_id: CostSettings(
            cycle_start_day=1,
        ),
    ).process(_energy_sample(115.0), config, context)
    no_rate_updates = {
        update.path: update.value for update in no_rate_result.state_updates
    }
    assert no_rate_updates[("estimated_cost_today_by_circuit", "fridge")] is None
    assert no_rate_updates[("average_cost_per_day_by_circuit", "fridge")] is None

    store_data.cost_by_circuit["fridge"]["days"] = [
        {
            "date": f"2026-06-{day:02d}",
            "cost": day / 10,
            "complete": True,
        }
        for day in range(1, 9)
    ]
    tou_result = CostProcessor(
        settings_for_config=lambda _config, _circuit_id: CostSettings(
            default_rate_per_kwh=0.20,
            tou_rate_per_kwh=0.35,
        ),
    ).process(_energy_sample(115.0), config, context)
    tou_updates = {update.path: update.value for update in tou_result.state_updates}
    assert tou_updates[("effective_electricity_rate_by_circuit", "fridge")] is None
    assert tou_updates[("estimated_cost_today_by_circuit", "fridge")] is None
    assert tou_updates[("average_cost_per_day_by_circuit", "fridge")] == 0.5


def test_cost_processor_refreshes_estimates_when_the_utility_rate_changes() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.managers.state_reducer import (
        StateReducer,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cost import (
        CostProcessor,
    )

    state = AnalyzerState()
    state.daily_energy_usage_by_circuit["fridge"] = 2.4
    state.average_kwh_per_day_by_circuit["fridge"] = 1.5
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    processor = CostProcessor(
        settings_for_config=lambda _config, _circuit_id: CostSettings(
            default_rate_per_kwh=0.2,
        ),
        utility_rate_for_circuit=(
            lambda _circuit_id: state.utility_cost_rate_by_circuit.get("mains")
        ),
    )

    state.utility_cost_rate_by_circuit["mains"] = 0.25
    StateReducer().apply_updates(
        state,
        processor.estimate_state_updates((config,), state),
    )

    assert state.effective_electricity_rate_by_circuit["fridge"] == 0.25
    assert state.estimated_cost_today_by_circuit["fridge"] == 0.6
    assert state.average_cost_per_day_by_circuit["fridge"] == 0.38

    state.utility_cost_rate_by_circuit.clear()
    StateReducer().apply_updates(
        state,
        processor.estimate_state_updates((config,), state),
    )

    assert state.effective_electricity_rate_by_circuit["fridge"] == 0.2
    assert state.estimated_cost_today_by_circuit["fridge"] == 0.48
    assert state.average_cost_per_day_by_circuit["fridge"] == 0.3

    no_fallback = CostProcessor(
        settings_for_config=lambda _config, _circuit_id: CostSettings(),
    )
    StateReducer().apply_updates(
        state,
        no_fallback.estimate_state_updates((config,), state),
    )

    assert state.effective_electricity_rate_by_circuit["fridge"] is None
    assert state.estimated_cost_today_by_circuit["fridge"] is None
    assert state.average_cost_per_day_by_circuit["fridge"] is None


def test_cost_processor_produces_same_time_comparison_evidence() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cost import (
        CostProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context_key = {
        "appliance_profile": "refrigerator",
        "circuit_mode": "single_phase",
        "day_progress": "50-60%",
        "season": "summer",
        "time_of_day": "afternoon",
    }
    store_data = FeatureStoreData(
        cost_by_circuit={
            "fridge": {
                "cycle_start": "2026-06-01",
                "cycle_cost": 5.0,
                "last_energy_kwh": 100.0,
                "last_sample_at": "2026-06-11T11:00:00+00:00",
                "days": [
                    {
                        "date": f"2026-06-{day:02d}",
                        "cost": value,
                        "complete": True,
                    }
                    for day, value in zip(
                        range(4, 11),
                        (0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4),
                        strict=True,
                    )
                ],
            }
        },
        contextual_baseline_samples_by_circuit={
            "fridge": [
                {
                    "timestamp": (now - timedelta(days=offset)).isoformat(),
                    "feature": "cost_today",
                    "value": value,
                    "context": context_key,
                    "source": "cost",
                }
                for offset, value in enumerate(
                    (0.31, 0.32, 0.33, 0.34, 0.35, 0.36, 0.37),
                    start=1,
                )
            ]
        },
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
        time_zone="UTC",
    )
    processor = CostProcessor(
        settings_for_config=lambda _config, _circuit_id: CostSettings(
            default_rate_per_kwh=0.20,
        )
    )

    result = processor.process(
        _energy_sample(102.0),
        CircuitConfig(
            circuit_id="fridge",
            name="Kitchen Fridge",
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            mode=CircuitMode.SINGLE_PHASE,
        ),
        context,
    )
    updates = {update.path: update.value for update in result.state_updates}
    evidence = updates[("cost_evidence_by_circuit", "fridge")]

    assert evidence["comparison_mode"] == "same_time_of_day"
    assert evidence["contextual_expected_range"] == [0.32, 0.36]
    assert evidence["contextual_baseline_median_cost"] == 0.34
    assert evidence["projection_value"] == 1.294
    assert evidence["full_period_normal_low"] == 0.9
    assert evidence["full_period_normal_high"] == 1.3
    assert evidence["projection_confidence"] < evidence[
        "contextual_baseline_confidence"
    ]


def test_cost_processor_prefers_the_derived_utility_rate() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.cost import (
        CostProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    processor = CostProcessor(
        settings_for_config=lambda _config, _circuit_id: CostSettings(
            default_rate_per_kwh=0.20,
            tou_rate_per_kwh=0.42,
        ),
        utility_rate_for_circuit=lambda _circuit_id: 0.31,
    )

    result = processor.process(_energy_sample(115.0), config, context)

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("cost_current_rate_by_circuit", "fridge")] == 0.31
    assert updates[("effective_electricity_rate_by_circuit", "fridge")] == 0.31


def test_demand_processor_updates_state_and_returns_limit_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.demand import (
        DemandProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="ev",
        name="EV Charger",
        appliance_profile=ApplianceProfile.EV_CHARGER,
        mode=CircuitMode.DUAL_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = DemandProcessor(
        settings_for_config=lambda _config, _circuit_id: DemandSettings(
            window_minutes=15,
            demand_limit_w=2000.0,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
        retention_days_for_circuit=lambda _circuit_id: 45,
    )

    result = processor.process(_sample(0, 2500.0), config, context)

    assert result.store_dirty is True
    assert len(result.state_updates) == 6
    assert len(result.alerts) == 1
    assert result.notifications == result.alerts
    assert policy.observations[0].feature == "demand_limit"
    assert policy.observations[0].observed_value == 2500.0
    assert policy.observations[0].baseline_value == 2000.0
    assert "EV Charger demand averaged 2500 W" in result.alerts[0].message

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("current_demand_w_by_circuit", "ev")] == 2500.0
    assert updates[("peak_demand_w_by_circuit", "ev")] == 2500.0
    assert updates[("demand_limit_usage_by_circuit", "ev")] == 125.0
    assert updates[("demand_peak_rank_by_circuit", "ev")] == 1
    assert updates[("demand_peak_status_by_circuit", "ev")] == "monthly_peak"
    evidence = updates[("demand_evidence_by_circuit", "ev")]
    assert evidence["status"] == "over_limit"
    assert evidence["current_demand_w"] == 2500.0
    assert evidence["demand_limit_w"] == 2000.0
    assert evidence["demand_limit_usage_percent"] == 125.0
    assert context.store_data.demand_by_circuit["ev"]["monthly_peak_windows"] == [
        {
            "timestamp": now.isoformat(),
            "demand_w": 2500.0,
            "window_minutes": 15,
        }
    ]


def test_demand_processor_keeps_maintenance_readings_out_of_history() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.demand import (
        DemandProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    history = {
        "daily_peaks": [{"date": "2026-06-10", "peak_demand_w": 1200.0}],
        "monthly_peak_windows": [
            {
                "timestamp": (now - timedelta(days=1)).isoformat(),
                "demand_w": 1200.0,
                "window_minutes": 15,
            }
        ],
    }
    store_data = FeatureStoreData(
        demand_by_circuit={"ev": history},
        maintenance_by_circuit={"ev": {"active": True}},
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="ev",
        name="EV Charger",
        appliance_profile=ApplianceProfile.EV_CHARGER,
        mode=CircuitMode.DUAL_PHASE,
    )
    processor = DemandProcessor(
        settings_for_config=lambda _config, _circuit_id: DemandSettings(
            window_minutes=15,
        ),
        alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
        retention_days_for_circuit=lambda _circuit_id: 45,
    )

    result = processor.process(_sample(0, 5000.0), config, context)

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("current_demand_w_by_circuit", "ev")] == 5000.0
    assert "samples" not in history
    assert history["daily_peaks"] == [
        {"date": "2026-06-10", "peak_demand_w": 1200.0}
    ]
    assert history["monthly_peak_windows"] == [
        {
            "timestamp": (now - timedelta(days=1)).isoformat(),
            "demand_w": 1200.0,
            "window_minutes": 15,
        }
    ]
    assert "ev" not in store_data.contextual_baseline_samples_by_circuit
    assert result.store_dirty is False


def test_demand_processor_excludes_windows_overlapping_maintenance() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.demand import (
        DemandProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData()
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="ev",
        name="EV Charger",
        appliance_profile=ApplianceProfile.EV_CHARGER,
        mode=CircuitMode.DUAL_PHASE,
    )
    processor = DemandProcessor(
        settings_for_config=lambda _config, _circuit_id: DemandSettings(
            window_minutes=15,
        ),
        alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
        retention_days_for_circuit=lambda _circuit_id: 45,
    )

    processor.process(_sample(0, 1000.0), config, context)
    history = store_data.demand_by_circuit["ev"]
    samples_before = list(history["samples"])
    daily_peaks_before = list(history["daily_peaks"])
    monthly_windows_before = list(history["monthly_peak_windows"])
    contextual_before = list(
        store_data.contextual_baseline_samples_by_circuit["ev"]
    )

    store_data.maintenance_by_circuit["ev"] = {"active": True}
    processor.process(
        _sample(300, 5000.0),
        config,
        replace(context, now=now + timedelta(minutes=5)),
    )
    processor.process(
        _sample(600, 5000.0),
        config,
        replace(context, now=now + timedelta(minutes=10)),
    )
    store_data.maintenance_by_circuit["ev"] = {"active": False}
    result = processor.process(
        _sample(900, 1000.0),
        config,
        replace(context, now=now + timedelta(minutes=15)),
    )

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("current_demand_w_by_circuit", "ev")] == 3666.7
    assert history["samples"] == samples_before
    assert history["daily_peaks"] == daily_peaks_before
    assert history["monthly_peak_windows"] == monthly_windows_before
    assert (
        store_data.contextual_baseline_samples_by_circuit["ev"]
        == contextual_before
    )
    assert result.store_dirty is False


def test_demand_processor_restart_preserves_maintenance_window_exclusion() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.demand import (
        DemandProcessor,
    )

    now = datetime(2026, 6, 11, 12, 12, tzinfo=UTC)
    history = {
        "samples": [
            {
                "timestamp": (now - timedelta(minutes=12)).isoformat(),
                "real_power_w": 1000.0,
            }
        ],
        "daily_peaks": [{"date": "2026-06-10", "peak_demand_w": 1200.0}],
        "monthly_peak_windows": [
            {
                "timestamp": (now - timedelta(days=1)).isoformat(),
                "demand_w": 1200.0,
                "window_minutes": 15,
            }
        ],
    }
    store_data = FeatureStoreData(
        demand_by_circuit={"ev": history},
        maintenance_by_circuit={
            "ev": {
                "active": False,
                "started_at": (now - timedelta(minutes=7)).isoformat(),
                "ended_at": (now - timedelta(minutes=2)).isoformat(),
            }
        },
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="ev",
        name="EV Charger",
        appliance_profile=ApplianceProfile.EV_CHARGER,
        mode=CircuitMode.DUAL_PHASE,
    )
    processor = DemandProcessor(
        settings_for_config=lambda _config, _circuit_id: DemandSettings(
            window_minutes=15,
        ),
        alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
        retention_days_for_circuit=lambda _circuit_id: 45,
    )
    samples_before = list(history["samples"])
    daily_peaks_before = list(history["daily_peaks"])
    monthly_windows_before = list(history["monthly_peak_windows"])

    result = processor.process(_sample(720, 5000.0), config, context)

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("current_demand_w_by_circuit", "ev")] == 1000.0
    assert history["samples"] == samples_before
    assert history["daily_peaks"] == daily_peaks_before
    assert history["monthly_peak_windows"] == monthly_windows_before
    assert "ev" not in store_data.contextual_baseline_samples_by_circuit
    assert result.store_dirty is False


@pytest.mark.parametrize(
    ("demand_limit_w", "expected_status", "expected_alert_features"),
    (
        (None, "context_explained", ()),
        (3000.0, "over_limit", ("demand_limit",)),
    ),
)
def test_demand_processor_suppresses_negligible_contextual_excess(
    demand_limit_w: float | None,
    expected_status: str,
    expected_alert_features: tuple[str, ...],
) -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.demand import (
        DemandProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context_key = {
        "appliance_profile": "ev_charger",
        "circuit_mode": "dual_phase",
        "day_progress": "50-60%",
        "season": "summer",
        "day_type": "weekday",
        "time_of_day": "afternoon",
    }
    store_data = FeatureStoreData(
        demand_by_circuit={
            "ev": {
                "monthly_peak_windows": [
                    {
                        "timestamp": (now - timedelta(days=offset + 1)).isoformat(),
                        "demand_w": demand_w,
                        "window_minutes": 15,
                    }
                    for offset, demand_w in enumerate((5000.0, 4500.0, 4000.0))
                ]
            }
        },
        contextual_baseline_samples_by_circuit={
            "ev": [
                {
                    "timestamp": (now - timedelta(days=offset + 2)).isoformat(),
                    "feature": "peak_demand_w",
                    "value": value,
                    "context": context_key,
                    "source": "demand",
                }
                for offset, value in enumerate(
                    (3300.0, 3400.0, 3500.0, 3600.0, 3700.0, 3800.0, 3900.0)
                )
            ]
        },
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="ev",
        name="EV Charger",
        appliance_profile=ApplianceProfile.EV_CHARGER,
        mode=CircuitMode.DUAL_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = DemandProcessor(
        settings_for_config=lambda _config, _circuit_id: DemandSettings(
            window_minutes=15,
            demand_limit_w=demand_limit_w,
            peak_rank_count=3,
            peak_warning_ratio=0.9,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
        retention_days_for_circuit=lambda _circuit_id: 45,
    )

    result = processor.process(_sample(0, 3800.1), config, context)

    assert result.store_dirty is True
    assert tuple(alert.feature for alert in result.alerts) == expected_alert_features
    assert tuple(observation.feature for observation in policy.observations) == (
        expected_alert_features
    )
    updates = {update.path: update.value for update in result.state_updates}
    evidence = updates[("demand_evidence_by_circuit", "ev")]
    assert evidence["status"] == expected_status
    assert evidence["comparison_basis"] == "contextual"
    assert evidence["baseline_fallback_level"] == "exact_context"
    assert evidence["baseline_sample_count"] == 7
    assert evidence["contextual_baseline_p90_w"] == 3800.0
    assert (
        store_data.contextual_baseline_samples_by_circuit["ev"][-1]["feature"]
        == "peak_demand_w"
    )


def test_demand_monthly_peak_message_names_cutoff_not_baseline_change() -> None:
    from custom_components.circuitsetup_energy_analyzer.demand import (
        DemandPeakEvidence,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.demand import (
        demand_monthly_peak_message,
    )

    config = CircuitConfig(
        circuit_id="water_heater",
        name="Water Heater",
        appliance_profile=ApplianceProfile.WATER_HEATER,
        mode=CircuitMode.SINGLE_PHASE,
    )
    evidence = DemandPeakEvidence(
        circuit_id="water_heater",
        date="2026-06-19",
        current_demand_w=4100.0,
        monthly_peak_rank=3,
        monthly_peak_cutoff_w=4100.0,
        monthly_peak_usage_percent=100.0,
        peak_rank_count=3,
        peak_warning_ratio=0.9,
        window_minutes=15,
        features={},
    )

    message = demand_monthly_peak_message(config, evidence)

    assert message == (
        "Possible issue: Water Heater demand averaged 4100 W over 15 minutes, "
        "matching this month's #3 demand window cutoff of 4100 W."
    )
    assert "Baseline" not in message
    assert "Observed" not in message


def test_demand_processor_context_uses_rollup_timestamp() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.demand import (
        DemandProcessor,
    )

    now = datetime(2026, 6, 1, 3, 30, tzinfo=UTC)
    sample_time = datetime(2026, 5, 30, 15, 30, tzinfo=UTC)
    store_data = FeatureStoreData()
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
        time_zone="America/New_York",
    )
    config = CircuitConfig(
        circuit_id="ev",
        name="EV Charger",
        appliance_profile=ApplianceProfile.EV_CHARGER,
        mode=CircuitMode.DUAL_PHASE,
    )
    processor = DemandProcessor(
        settings_for_config=lambda _config, _circuit_id: DemandSettings(),
        alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
        retention_days_for_circuit=lambda _circuit_id: 45,
    )
    sample = CircuitSample(
        timestamp=sample_time,
        circuit_id="ev",
        real_power=2500.0,
        current=20.8,
        voltage=120.0,
    )

    processor.process(sample, config, context)

    stored = store_data.contextual_baseline_samples_by_circuit["ev"][0]
    assert stored["timestamp"] == now.isoformat()
    assert stored["context"]["time_of_day"] == "evening"


def test_capacity_processor_records_current_and_returns_capacity_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.capacity import (
        CapacityProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="ev",
        name="EV Charger",
        appliance_profile=ApplianceProfile.EV_CHARGER,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.ev_current", SensorRole.CURRENT),),
    )
    sample = CircuitSample(
        timestamp=now,
        circuit_id="ev",
        real_power=6720.0,
        current=28.0,
        voltage=240.0,
        reactive_power=0.0,
        apparent_power=6720.0,
        power_factor=1.0,
        frequency=60.0,
        energy=0.0,
    )
    policy = _CaptureAlertPolicy()
    processor = CapacityProcessor(
        settings_for_config=lambda _circuit_id: CapacitySettings(
            breaker_amps=30.0,
            warning_ratio=0.8,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
        retention_days_for_circuit=lambda _circuit_id: 45,
        source_states_for=lambda _config, _now: {},
    )

    result = processor.process(sample, config, context)

    assert result.store_dirty is True
    assert len(result.state_updates) == 3
    assert len(result.alerts) == 1
    assert result.notifications == result.alerts
    assert policy.observations[0].feature == "circuit_capacity"
    assert policy.observations[0].observed_value == 28.0
    assert policy.observations[0].baseline_value == 24.0
    assert "EV Charger current is 28 A" in result.alerts[0].message

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("capacity_usage_by_circuit", "ev")] == 93.3
    assert updates[("capacity_status_by_circuit", "ev")] == "over_limit"
    assert updates[("capacity_evidence_by_circuit", "ev")] == {
        "status": "over_limit",
        "current_amps": 28.0,
        "breaker_amps": 30.0,
        "warning_threshold_amps": 24.0,
        "capacity_usage_percent": 93.3,
        "warning_ratio": 0.8,
        "current_source": "current_sensor",
    }
    assert (
        context.store_data.demand_by_circuit["ev"]["capacity_current_sample_format"]
        == "5m-max-v1"
    )
    assert context.store_data.demand_by_circuit["ev"]["capacity_current_samples"] == [
        {
            "timestamp": now.isoformat(),
            "current_amps": 28.0,
        }
    ]


def test_capacity_processor_prefers_peak_current_for_spike_alerts() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.normalize import SourceState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.capacity import (
        CapacityProcessor,
    )

    now = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="ev",
        name="EV Charger",
        appliance_profile=ApplianceProfile.EV_CHARGER,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(
            SensorRef("sensor.ev_current", SensorRole.CURRENT),
            SensorRef("sensor.ev_peak_a", SensorRole.PEAK_CURRENT),
        ),
    )
    peak_state = SourceState(
        entity_id="sensor.ev_peak_a",
        state="42000",
        unit="mA",
        last_updated=now,
    )
    policy = _CaptureAlertPolicy()
    processor = CapacityProcessor(
        settings_for_config=lambda _circuit_id: CapacitySettings(
            breaker_amps=40.0,
            warning_ratio=0.8,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
        retention_days_for_circuit=lambda _circuit_id: 45,
        source_states_for=lambda _config, _now: {
            peak_state.entity_id: peak_state,
        },
    )
    sample = NormalizedCircuitSample(
        timestamp=now,
        circuit_id="ev",
        real_power=2880.0,
        current=12.0,
        voltage=240.0,
    )

    result = processor.process(sample, config, context)

    assert policy.observations[0].observed_value == 42.0
    assert result.state_updates[0].value == 105.0
    assert result.alerts[0].feature == "circuit_capacity"


def test_capacity_history_discards_unsupported_sample_format() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import capacity

    now = datetime(2026, 7, 19, 12, 4, 50, tzinfo=UTC)
    histories = {
        "ev": {
            "capacity_current_samples": [
                {
                    "timestamp": (now - timedelta(days=46)).isoformat(),
                    "current_amps": 30.0,
                },
                {"timestamp": "2026-07-19T12:00:10+00:00", "current_amps": 10.0},
                {"timestamp": "2026-07-19T12:03:00+00:00", "current_amps": 18.0},
                {"timestamp": "2026-07-19T12:03:30+00:00", "current_amps": 15.0},
                {"timestamp": "invalid", "current_amps": 99.0},
            ]
        }
    }

    assert capacity._record_capacity_current_sample(
        histories,
        circuit_id="ev",
        timestamp=now,
        current_amps=16.0,
        retention_days=45,
    )
    assert histories["ev"]["capacity_current_sample_format"] == "5m-max-v1"
    assert histories["ev"]["capacity_current_samples"] == [
        {
            "timestamp": "2026-07-19T12:04:50+00:00",
            "current_amps": 16.0,
        }
    ]

    assert capacity._record_capacity_current_sample(
        histories,
        circuit_id="ev",
        timestamp=datetime(2026, 7, 19, 12, 5, tzinfo=UTC),
        current_amps=20.0,
        retention_days=45,
    )
    assert histories["ev"]["capacity_current_samples"] == [
        {
            "timestamp": "2026-07-19T12:04:50+00:00",
            "current_amps": 16.0,
        },
        {"timestamp": "2026-07-19T12:05:00+00:00", "current_amps": 20.0},
    ]


def test_capacity_processor_without_current_does_not_create_storage_history() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.capacity import (
        CapacityProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = CapacityProcessor(
        settings_for_config=lambda _circuit_id: CapacitySettings(
            breaker_amps=15.0,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
        retention_days_for_circuit=lambda _circuit_id: 45,
        source_states_for=lambda _config, _now: {},
    )
    sample = CircuitSample(
        timestamp=now,
        circuit_id="fridge",
        real_power=None,
        current=None,
        voltage=120.0,
        reactive_power=None,
        apparent_power=None,
        power_factor=None,
        frequency=60.0,
        energy=0.0,
    )

    result = processor.process(sample, config, context)

    assert result.store_dirty is False
    assert result.alerts == []
    assert context.store_data.demand_by_circuit == {}

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("capacity_status_by_circuit", "fridge")] == "missing_current"


def test_capacity_processor_uses_dual_phase_leg_currents_and_prunes_history() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.normalize import SourceState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.capacity import (
        CapacityProcessor,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        demand_by_circuit={
            "hvac": {
                "capacity_current_sample_format": "5m-max-v1",
                "capacity_current_samples": [
                    {
                        "timestamp": (now - timedelta(days=46)).isoformat(),
                        "current_amps": 19.0,
                    },
                    {
                        "timestamp": (now - timedelta(days=2)).isoformat(),
                        "current_amps": 20.0,
                    },
                ]
            }
        }
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="hvac",
        name="HVAC Compressor",
        appliance_profile=ApplianceProfile.HVAC_COMPRESSOR,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(
            SensorRef("sensor.hvac_l1_current", SensorRole.CURRENT, leg="a"),
            SensorRef("sensor.hvac_l2_current", SensorRole.CURRENT, leg="b"),
        ),
    )
    policy = _CaptureAlertPolicy()
    processor = CapacityProcessor(
        settings_for_config=lambda _circuit_id: CapacitySettings(
            breaker_amps=40.0,
            warning_ratio=0.8,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
        retention_days_for_circuit=lambda _circuit_id: 45,
        source_states_for=lambda _config, _now: {
            "sensor.hvac_l1_current": SourceState(
                entity_id="sensor.hvac_l1_current",
                state="31",
                unit="A",
                last_updated=now,
            ),
            "sensor.hvac_l2_current": SourceState(
                entity_id="sensor.hvac_l2_current",
                state="34",
                unit="A",
                last_updated=now,
            ),
        },
    )
    sample = CircuitSample(
        timestamp=now,
        circuit_id="hvac",
        real_power=7200.0,
        current=66.0,
        voltage=120.0,
        reactive_power=0.0,
        apparent_power=7200.0,
        power_factor=1.0,
        frequency=60.0,
        energy=0.0,
    )

    result = processor.process(sample, config, context)

    assert result.store_dirty is True
    updates = {update.path: update.value for update in result.state_updates}
    evidence = updates[("capacity_evidence_by_circuit", "hvac")]
    assert evidence["current_amps"] == 34.0
    assert evidence["capacity_usage_percent"] == 85.0
    assert (
        store_data.demand_by_circuit["hvac"]["capacity_current_sample_format"]
        == "5m-max-v1"
    )
    assert store_data.demand_by_circuit["hvac"]["capacity_current_samples"] == [
        {
            "timestamp": (now - timedelta(days=2)).isoformat(),
            "current_amps": 20.0,
        },
        {
            "timestamp": now.isoformat(),
            "current_amps": 34.0,
        },
    ]


def test_leg_imbalance_processor_updates_state_and_returns_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC_COMPRESSOR,
        mode=CircuitMode.DUAL_PHASE,
    )
    sample = NormalizedCircuitSample(
        timestamp=now,
        circuit_id="hvac",
        real_power=3600.0,
        current=30.0,
        voltage=240.0,
        reactive_power=0.0,
        apparent_power=3600.0,
        power_factor=1.0,
        frequency=60.0,
        energy=0.0,
        leg_a_real_power=2400.0,
        leg_b_real_power=1200.0,
        leg_a_current=20.0,
        leg_b_current=10.0,
        leg_a_voltage=121.0,
        leg_b_voltage=119.0,
    )
    policy = _CaptureAlertPolicy()
    processor = processors.LegImbalanceProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
    )

    result = processor.process(sample, config, context)

    assert result.store_dirty is False
    assert len(result.state_updates) == 3
    assert len(result.alerts) == 1
    assert result.notifications == result.alerts
    assert policy.observations[0].feature == "dual_phase_leg_imbalance"
    assert policy.observations[0].observed_value == 0.667
    assert policy.observations[0].baseline_value == DEFAULT_LEG_IMBALANCE_WARNING_RATIO
    assert "Possible issue: HVAC split-phase legs are imbalanced" in (
        result.alerts[0].message
    )

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("leg_imbalance_percent_by_circuit", "hvac")] == 66.7
    assert updates[("leg_imbalance_status_by_circuit", "hvac")] == "imbalanced"
    assert updates[("leg_imbalance_evidence_by_circuit", "hvac")] == {
        "status": "imbalanced",
        "leg_imbalance_ratio": 0.667,
        "leg_imbalance_percent": 66.7,
        "threshold_ratio": DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
        "threshold_percent": 50.0,
        "minimum_total_power_w": DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
        "left_real_power_w": 2400.0,
        "right_real_power_w": 1200.0,
        "left_current_a": 20.0,
        "right_current_a": 10.0,
        "left_voltage_v": 121.0,
        "right_voltage_v": 119.0,
        "voltage_difference_v": 2.0,
        "dominant_leg": "a",
    }


def test_mains_balance_processor_updates_state_for_mains_circuit() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        balance_settings_by_circuit={
            "mains": {"negative_tolerance_w": DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W},
        },
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )

    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        power_flow=PowerFlowMode.MAINS_NET,
    )
    hvac = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
    )
    fridge = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    solar = CircuitConfig(
        circuit_id="solar",
        name="Solar",
        appliance_profile=ApplianceProfile.SOLAR_INVERTER,
        mode=CircuitMode.SINGLE_PHASE,
        power_flow=PowerFlowMode.GENERATION,
    )

    def sample(circuit_id: str, watts: float) -> NormalizedCircuitSample:
        return NormalizedCircuitSample(
            timestamp=now,
            circuit_id=circuit_id,
            real_power=watts,
            current=None,
            voltage=None,
            reactive_power=None,
            apparent_power=None,
            power_factor=None,
            frequency=60.0,
            energy=None,
        )

    processor = processors.MainsBalanceProcessor(
        settings_for_circuit=lambda circuit_id: (
            store_data.balance_settings_by_circuit.get(circuit_id, {})
        ),
    )

    result = processor.process(
        [
            (mains, sample("mains", 5000.0)),
            (hvac, sample("hvac", 2400.0)),
            (fridge, sample("fridge", 300.0)),
            (solar, sample("solar", -1800.0)),
        ],
        context,
    )

    assert result.alerts == []
    assert result.notifications == []
    assert result.store_dirty is False
    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("balance_power_w_by_circuit", "mains")] == 2300.0
    assert updates[("monitored_power_w_by_circuit", "mains")] == 2700.0
    assert updates[("monitored_coverage_percent_by_circuit", "mains")] == 54.0
    assert updates[("balance_status_by_circuit", "mains")] == "tracking"
    assert updates[("balance_evidence_by_circuit", "mains")] == {
        "mains_power_w": 5000.0,
        "monitored_power_w": 2700.0,
        "balance_power_w": 2300.0,
        "monitored_coverage_percent": 54.0,
        "monitored_circuit_count": 2.0,
        "status": "tracking",
    }


def test_solar_flow_processor_updates_flow_and_load_shift_state() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData()
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )

    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        power_flow=PowerFlowMode.MAINS_NET,
    )
    solar = CircuitConfig(
        circuit_id="solar",
        name="Solar",
        appliance_profile=ApplianceProfile.SOLAR_INVERTER,
        mode=CircuitMode.SINGLE_PHASE,
        power_flow=PowerFlowMode.GENERATION,
    )
    pool_pump = CircuitConfig(
        circuit_id="pool",
        name="Pool Pump",
        appliance_profile=ApplianceProfile.POOL_PUMP,
        mode=CircuitMode.SINGLE_PHASE,
    )
    water_heater = CircuitConfig(
        circuit_id="water_heater",
        name="Water Heater",
        appliance_profile=ApplianceProfile.WATER_HEATER,
        mode=CircuitMode.DUAL_PHASE,
    )

    def sample(circuit_id: str, watts: float) -> NormalizedCircuitSample:
        return NormalizedCircuitSample(
            timestamp=now,
            circuit_id=circuit_id,
            real_power=watts,
            current=None,
            voltage=None,
            reactive_power=None,
            apparent_power=None,
            power_factor=None,
            frequency=60.0,
            energy=None,
        )

    processor = processors.SolarFlowProcessor(
        settings_for_circuit=lambda circuit_id: (
            store_data.solar_flow_settings_by_circuit.get(circuit_id, {})
        ),
    )

    result = processor.process(
        [
            (mains, sample("mains", -500.0)),
            (solar, sample("solar", 2000.0)),
            (pool_pump, sample("pool", 800.0)),
            (water_heater, sample("water_heater", 0.0)),
        ],
        context,
    )

    assert result.alerts == []
    assert result.notifications == []
    assert result.store_dirty is True
    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("solar_generation_w_by_circuit", "mains")] == 2000.0
    assert updates[("solar_grid_import_w_by_circuit", "mains")] == 0.0
    assert updates[("solar_grid_export_w_by_circuit", "mains")] == 500.0
    assert updates[("solar_self_consumption_percent_by_circuit", "mains")] == 75.0
    assert updates[("solar_powered_percent_by_circuit", "mains")] == 100.0
    assert updates[("solar_surplus_w_by_circuit", "mains")] == 500.0
    assert updates[("solar_load_shift_w_by_circuit", "mains")] == 500.0
    assert updates[("solar_flexible_load_power_w_by_circuit", "mains")] == 800.0
    assert updates[
        ("solar_flexible_load_coverage_percent_by_circuit", "mains")
    ] == 100.0
    assert updates[("solar_flow_status_by_circuit", "mains")] == "exporting"
    assert updates[("solar_surplus_status_by_circuit", "mains")] == (
        "surplus_available"
    )
    assert updates[("solar_load_shift_status_by_circuit", "mains")] == (
        "active_solar_supported"
    )
    assert updates[("solar_flow_evidence_by_circuit", "mains")] == {
        "mains_net_power_w": -500.0,
        "solar_generation_w": 2000.0,
        "grid_import_w": 0.0,
        "grid_export_w": 500.0,
        "site_consumption_w": 1500.0,
        "solar_used_on_site_w": 1500.0,
        "self_consumption_percent": 75.0,
        "solar_powered_percent": 100.0,
        "solar_surplus_w": 500.0,
        "load_shift_available_w": 500.0,
        "solar_surplus_threshold_w": 500.0,
        "high_solar_surplus_threshold_w": 1500.0,
        "generation_circuit_count": 1.0,
        "status": "exporting",
        "solar_surplus_status": "surplus_available",
    }
    assert updates[("solar_load_shift_evidence_by_circuit", "mains")][
        "candidate_loads"
    ] == [
        {
            "circuit_id": "pool",
            "name": "Pool Pump",
            "appliance_profile": "pool_pump",
            "current_power_w": 800.0,
            "state": "active",
        },
        {
            "circuit_id": "water_heater",
            "name": "Water Heater",
            "appliance_profile": "water_heater",
            "current_power_w": 0.0,
            "state": "idle",
        },
    ]


def test_solar_flow_processor_ignores_mixed_flexible_loads() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        power_flow=PowerFlowMode.MAINS_NET,
    )
    solar = CircuitConfig(
        circuit_id="solar",
        name="Solar",
        appliance_profile=ApplianceProfile.SOLAR_INVERTER,
        mode=CircuitMode.SINGLE_PHASE,
        power_flow=PowerFlowMode.GENERATION,
    )
    mixed_pool = CircuitConfig(
        circuit_id="pool",
        name="Pool Pump",
        appliance_profile=ApplianceProfile.POOL_PUMP,
        mode=CircuitMode.MIXED,
    )

    def sample(circuit_id: str, watts: float) -> NormalizedCircuitSample:
        return NormalizedCircuitSample(
            timestamp=now,
            circuit_id=circuit_id,
            real_power=watts,
            current=None,
            voltage=None,
            reactive_power=None,
            apparent_power=None,
            power_factor=None,
            frequency=60.0,
            energy=None,
        )

    result = processors.SolarFlowProcessor(
        settings_for_circuit=lambda _circuit_id: {}
    ).process(
        [
            (mains, sample("mains", -500.0)),
            (solar, sample("solar", 2000.0)),
            (mixed_pool, sample("pool", 800.0)),
        ],
        context,
    )

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("solar_flexible_load_power_w_by_circuit", "mains")] == 0.0
    assert (
        updates[("solar_load_shift_status_by_circuit", "mains")]
        == "no_flexible_loads"
    )
    assert updates[("solar_load_shift_evidence_by_circuit", "mains")][
        "candidate_loads"
    ] == []


def test_solar_flow_processor_ignores_batches_without_mains() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    solar = CircuitConfig(
        circuit_id="solar",
        name="Solar",
        appliance_profile=ApplianceProfile.SOLAR_INVERTER,
        mode=CircuitMode.SINGLE_PHASE,
        power_flow=PowerFlowMode.GENERATION,
    )
    sample = NormalizedCircuitSample(
        timestamp=now,
        circuit_id="solar",
        real_power=1800.0,
        current=None,
        voltage=None,
        reactive_power=None,
        apparent_power=None,
        power_factor=None,
        frequency=60.0,
        energy=None,
    )
    processor = processors.SolarFlowProcessor(
        settings_for_circuit=lambda _circuit_id: {},
    )

    result = processor.process([(solar, sample)], context)

    assert result.state_updates == []
    assert result.alerts == []
    assert result.notifications == []


def test_solar_flow_processor_adds_contextual_surplus_evidence() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 17, 15, 0, tzinfo=UTC)
    context_key = {
        "appliance_profile": "mains_nilm",
        "circuit_mode": "mains_nilm",
        "power_flow_mode": "mains_net",
        "season": "summer",
        "solar_flow_state": "exporting",
        "time_of_day": "afternoon",
    }
    store_data = FeatureStoreData(
        contextual_baseline_samples_by_circuit={
            "mains": [
                {
                    "timestamp": (now - timedelta(days=offset)).isoformat(),
                    "feature": "solar_surplus_power_w",
                    "value": value,
                    "context": context_key,
                    "source": "solar_flow",
                }
                for offset, value in enumerate(
                    [420.0, 450.0, 500.0, 520.0, 540.0, 560.0, 580.0],
                    start=1,
                )
            ]
        }
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        power_flow=PowerFlowMode.MAINS_NET,
    )
    solar = CircuitConfig(
        circuit_id="solar",
        name="Solar",
        appliance_profile=ApplianceProfile.SOLAR_INVERTER,
        mode=CircuitMode.SINGLE_PHASE,
        power_flow=PowerFlowMode.GENERATION,
    )

    def sample(circuit_id: str, watts: float) -> NormalizedCircuitSample:
        return NormalizedCircuitSample(
            timestamp=now,
            circuit_id=circuit_id,
            real_power=watts,
            current=None,
            voltage=None,
            reactive_power=None,
            apparent_power=None,
            power_factor=None,
            frequency=60.0,
            energy=None,
        )

    processor = processors.SolarFlowProcessor(
        settings_for_circuit=lambda _circuit_id: {},
    )

    result = processor.process(
        [(mains, sample("mains", -500.0)), (solar, sample("solar", 2000.0))],
        context,
    )

    assert result.store_dirty is True
    updates = {update.path: update.value for update in result.state_updates}
    evidence = updates[("solar_flow_evidence_by_circuit", "mains")]
    assert evidence["comparison_basis"] == "contextual"
    assert evidence["baseline_context"] == (
        "mains_nilm, mains_nilm, mains_net, summer, exporting, afternoon"
    )
    assert evidence["baseline_fallback_level"] == "exact_context"
    assert evidence["baseline_sample_count"] == 7
    assert evidence["contextual_baseline_median_w"] == 520.0
    assert evidence["contextual_baseline_p90_w"] == 560.0
    assert evidence["contextual_baseline_confidence"] == 1.0
    assert (
        store_data.contextual_baseline_samples_by_circuit["mains"][-1]["feature"]
        == "solar_surplus_power_w"
    )


@pytest.mark.parametrize(
    "maintenance",
    [
        {"active": True},
        {
            "active": False,
            "started_at": "2026-06-17T13:00:00+00:00",
            "ended_at": "2026-06-17T14:00:00+00:00",
        },
    ],
)
def test_solar_flow_processor_skips_contextual_learning_during_maintenance(
    maintenance: dict[str, object],
) -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 17, 15, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        maintenance_by_circuit={"mains": maintenance},
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        power_flow=PowerFlowMode.MAINS_NET,
    )
    solar = CircuitConfig(
        circuit_id="solar",
        name="Solar",
        appliance_profile=ApplianceProfile.SOLAR_INVERTER,
        mode=CircuitMode.SINGLE_PHASE,
        power_flow=PowerFlowMode.GENERATION,
    )

    def sample(circuit_id: str, watts: float) -> NormalizedCircuitSample:
        return NormalizedCircuitSample(
            timestamp=now,
            circuit_id=circuit_id,
            real_power=watts,
            current=None,
            voltage=None,
            reactive_power=None,
            apparent_power=None,
            power_factor=None,
            frequency=60.0,
            energy=None,
        )

    processor = processors.SolarFlowProcessor(
        settings_for_circuit=lambda _circuit_id: {},
    )

    result = processor.process(
        [(mains, sample("mains", -500.0)), (solar, sample("solar", 2000.0))],
        context,
    )

    assert result.store_dirty is False
    assert store_data.contextual_baseline_samples_by_circuit == {}


def test_solar_flow_processor_respects_selection_and_settings_overrides() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        solar_flow_settings_by_circuit={
            "mains": {
                "solar_surplus_threshold_w": 700.0,
                "high_solar_surplus_threshold_w": 900.0,
                "flexible_load_running_threshold_w": 900.0,
            },
        },
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )

    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.SINGLE_PHASE,
        power_flow=PowerFlowMode.MAINS_NET,
    )
    solar_by_profile = CircuitConfig(
        circuit_id="solar",
        name="Solar",
        appliance_profile=ApplianceProfile.SOLAR_INVERTER,
        mode=CircuitMode.SINGLE_PHASE,
        power_flow=PowerFlowMode.LOAD,
    )
    pool_pump = CircuitConfig(
        circuit_id="pool",
        name="Pool Pump",
        appliance_profile=ApplianceProfile.POOL_PUMP,
        mode=CircuitMode.SINGLE_PHASE,
    )
    microwave = CircuitConfig(
        circuit_id="microwave",
        name="Microwave",
        appliance_profile=ApplianceProfile.MICROWAVE,
        mode=CircuitMode.SINGLE_PHASE,
    )

    def sample(circuit_id: str, watts: float) -> NormalizedCircuitSample:
        return NormalizedCircuitSample(
            timestamp=now,
            circuit_id=circuit_id,
            real_power=watts,
            current=None,
            voltage=None,
            reactive_power=None,
            apparent_power=None,
            power_factor=None,
            frequency=60.0,
            energy=None,
        )

    processor = processors.SolarFlowProcessor(
        settings_for_circuit=lambda circuit_id: (
            store_data.solar_flow_settings_by_circuit.get(circuit_id, {})
        ),
    )

    result = processor.process(
        [
            (mains, sample("mains", -800.0)),
            (solar_by_profile, sample("solar", 1600.0)),
            (pool_pump, sample("pool", 800.0)),
            (microwave, sample("microwave", 1000.0)),
        ],
        context,
    )

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("solar_generation_w_by_circuit", "mains")] == 1600.0
    assert updates[("solar_grid_export_w_by_circuit", "mains")] == 800.0
    assert updates[("solar_surplus_w_by_circuit", "mains")] == 800.0
    assert updates[("solar_surplus_status_by_circuit", "mains")] == (
        "surplus_available"
    )
    assert updates[("solar_load_shift_w_by_circuit", "mains")] == 800.0
    assert updates[("solar_flexible_load_power_w_by_circuit", "mains")] == 0.0
    assert updates[("solar_load_shift_status_by_circuit", "mains")] == (
        "surplus_candidate"
    )

    flow_evidence = updates[("solar_flow_evidence_by_circuit", "mains")]
    assert flow_evidence["solar_surplus_threshold_w"] == 700.0
    assert flow_evidence["high_solar_surplus_threshold_w"] == 900.0
    assert flow_evidence["generation_circuit_count"] == 1.0

    load_shift_evidence = updates[("solar_load_shift_evidence_by_circuit", "mains")]
    assert load_shift_evidence["candidate_loads"] == [
        {
            "circuit_id": "pool",
            "name": "Pool Pump",
            "appliance_profile": "pool_pump",
            "current_power_w": 800.0,
            "state": "idle",
        },
    ]


def test_nilm_topology_processor_updates_state_and_returns_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.nilm import (
        KnownLoadMatch,
        NilmEdge,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    fridge = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(
            SensorRef(
                entity_id="sensor.fridge_power",
                role=SensorRole.REAL_POWER,
                leg="a",
            ),
        ),
    )
    match = KnownLoadMatch(
        edge=NilmEdge(
            timestamp=now,
            delta_w=620.1234,
            delta_var=30.0,
            delta_va=621.0,
            delta_pf=0.02,
            direction="on",
            leg_a_delta_w=310.0,
            leg_b_delta_w=310.0,
            leg_balance_ratio=0.0,
            dominant_leg="balanced",
            split_phase_type="balanced_240v",
        ),
        known_circuit_id="fridge",
        confidence=0.92,
        known_power_w=618.5555,
        power_source="startup_power_w",
        explained_delta_w=618.5555,
        residual_delta_w=1.5679,
        residual_edge=NilmEdge(
            timestamp=now,
            delta_w=1.5679,
            direction="on",
            origin="known_load_residual",
            parent_edge_id="mains:edge",
            explained_known_circuit_ids=("fridge",),
        ),
        selection_method="global_assignment",
        time_offset_seconds=2.5,
        magnitude_score=0.92,
        time_score=0.83,
        topology_score=0.4,
    )
    policy = _CaptureAlertPolicy()
    processor = processors.NilmTopologyProcessor(
        known_config_for_circuit=lambda circuit_id: (
            fridge if circuit_id == "fridge" else None
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
    )

    result = processor.process(mains, match, context)

    assert len(result.state_updates) == 2
    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("nilm_topology_status_by_circuit", "fridge")] == (
        "topology_mismatch"
    )
    evidence = updates[("nilm_topology_evidence_by_circuit", "fridge")]
    assert evidence == {
        "status": "topology_mismatch",
        "matched_mains_circuit_id": "mains",
        "event_type": "start",
        "configured_mode": "single_phase",
        "configured_leg": "a",
        "expected_split_phase_types": ["single_leg_a", "single_leg_b"],
        "expected_dominant_legs": ["a"],
        "observed_split_phase_type": "balanced_240v",
        "observed_dominant_leg": "balanced",
        "observed_leg": None,
        "suggested_leg": None,
        "observed_leg_a_delta_w": 310.0,
        "observed_leg_b_delta_w": 310.0,
        "observed_leg_balance_ratio": 0.0,
        "matched_delta_w": 620.123,
        "known_event_power_w": 618.556,
        "match_confidence": 0.92,
        "source_aggregate_delta_w": 620.123,
        "explained_delta_w": 618.556,
        "residual_delta_w": 1.568,
        "residual_emitted": True,
        "residual_edge_id": (
            "on|2026-06-11T12:00:00+00:00|w=1.568|var=unknown|unknown|unknown"
            "|origin=known_load_residual|parent=mains:edge|explained=fridge"
        ),
        "match_time_offset_seconds": 2.5,
        "synchronized_time_offset_seconds": 2.5,
        "magnitude_score": 0.92,
        "time_score": 0.83,
        "topology_score": 0.4,
        "selection_method": "global_assignment",
        "known_power_source": "startup_power_w",
    }
    assert result.store_dirty is False
    assert len(result.alerts) == 1
    assert result.notifications == result.alerts
    assert policy.observations[0].feature == "nilm_topology_mismatch"
    assert policy.observations[0].features == {
        "match_confidence": 0.92,
        "matched_delta_w": 620.123,
        "known_event_power_w": 618.556,
        "observed_leg_balance_ratio": 0.0,
    }
    assert "configured as single phase" in result.alerts[0].message
    assert "balanced_240v" in result.alerts[0].message


@pytest.mark.parametrize(
    ("confidence", "expects_alert"),
    [
        (0.49, False),
        (0.4999, False),
        (0.5, True),
        (float("nan"), False),
        (float("inf"), False),
    ],
)
def test_nilm_topology_rejection_requires_minimum_confidence_for_alerts(
    confidence: float,
    expects_alert: bool,
) -> None:
    """Bypassing the confidence gate would alert on weak rejections."""
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.nilm import (
        KnownLoadMatch,
        NilmEdge,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    fridge = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    match = KnownLoadMatch(
        edge=NilmEdge(
            timestamp=now,
            delta_w=300.0,
            direction="on",
            split_phase_type="balanced_240v",
            dominant_leg="balanced",
        ),
        known_circuit_id="fridge",
        confidence=confidence,
        selection_method="topology_rejected",
        topology_status="topology_mismatch",
    )

    policy = _CaptureAlertPolicy()
    processor = processors.NilmTopologyProcessor(
        known_config_for_circuit=lambda _id: fridge,
        alert_policy_for_circuit=lambda _id: policy,
    )
    result = processor.process(mains, match, context)
    evidence = {update.path: update.value for update in result.state_updates}[
        ("nilm_topology_evidence_by_circuit", "fridge")
    ]

    assert evidence["status"] == "topology_mismatch"
    assert evidence["attribution_rejected"] is True
    assert "low_confidence_match" not in str(evidence)
    if confidence == 0.4999:
        assert evidence["match_confidence"] == 0.5
    assert len(policy.observations) == int(expects_alert)
    assert len(result.alerts) == int(expects_alert)
    assert result.notifications == result.alerts


def test_nilm_topology_processor_uses_attached_status_and_provenance() -> None:
    """Re-evaluating a supplied status would diverge diagnostics from matching."""
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.nilm import (
        KnownLoadMatch,
        NilmEdge,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    known = CircuitConfig(
        circuit_id="load",
        name="Load",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.DUAL_PHASE,
    )
    edge = NilmEdge(
        timestamp=now,
        delta_w=500.0,
        direction="on",
        split_phase_type="single_leg_a",
        dominant_leg="a",
    )
    match = KnownLoadMatch(
        edge=edge,
        known_circuit_id="load",
        confidence=0.8,
        event_type=EventType.POWER_TRANSITION,
        known_power_w=500.0,
        selection_method="topology_rejected",
        selection_status="rejected_topology",
        topology_status="leg_mismatch",
        known_power_source="transition_delta_w",
        known_transition_delta_w=500.0,
        known_transition_spread_w=11.0,
        power_match_confidence=0.9,
        time_distance_seconds=1.5,
        time_offset_seconds=-1.5,
        transition_timing_uncertainty_s=0.25,
    )

    result = processors.NilmTopologyProcessor(
        known_config_for_circuit=lambda _id: known,
        alert_policy_for_circuit=lambda _id: _CaptureAlertPolicy(),
    ).process(mains, match, context)
    evidence = {update.path: update.value for update in result.state_updates}[
        ("nilm_topology_evidence_by_circuit", "load")
    ]

    assert evidence["status"] == "leg_mismatch"
    assert evidence["event_type"] == "power_transition"
    assert evidence["selection_status"] == "rejected_topology"
    assert evidence["known_selected_power_source"] == "transition_delta_w"
    assert evidence["known_transition_delta_w"] == 500.0
    assert evidence["known_transition_spread_w"] == 11.0
    assert evidence["pre_topology_power_match_confidence"] == 0.9
    assert evidence["synchronized_time_distance_seconds"] == 1.5
    assert evidence["synchronized_time_offset_seconds"] == -1.5
    assert evidence["transition_timing_uncertainty_s"] == 0.25
    assert match.edge == edge
    assert match.selection_status == "rejected_topology"


def test_nilm_edge_storage_round_trips_residual_provenance_and_legacy_defaults(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _nilm_edge_to_storage,
        _nilm_edges_from_storage,
    )

    timestamp = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    residual = NilmEdge(
        timestamp=timestamp,
        delta_w=180.0,
        direction="on",
        origin="known_load_residual",
        parent_edge_id="mains:2026-06-11T12:00:00+00:00:500",
        explained_known_circuit_ids=("fridge",),
        transition_kind="ramp",
        dominant_leg=None,
    )

    payload = _nilm_edge_to_storage(residual)

    assert payload is not None
    assert payload["origin"] == "known_load_residual"
    assert payload["parent_edge_id"] == residual.parent_edge_id
    assert payload["explained_known_circuit_ids"] == ["fridge"]
    assert payload["transition_kind"] == "ramp"
    assert payload["dominant_leg"] is None
    assert _nilm_edges_from_storage([payload], max_items=10) == [residual]

    legacy = dict(payload)
    legacy.pop("origin")
    legacy.pop("parent_edge_id")
    legacy.pop("explained_known_circuit_ids")
    legacy.pop("transition_kind")
    restored_legacy = _nilm_edges_from_storage([legacy], max_items=10)

    assert restored_legacy[0].origin == "aggregate"
    assert restored_legacy[0].parent_edge_id is None
    assert restored_legacy[0].explained_known_circuit_ids == ()
    assert restored_legacy[0].transition_kind == "step"


def test_water_context_alert_processor_returns_flow_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    state = AnalyzerState()
    state.water_flow_context_by_circuit["washer"] = {
        "status": "possible_flow_without_load",
        "friendly_summary": "Water flow has been active for 14 minutes.",
        "mismatch_minutes": 14.0,
        "flow_active_minutes": 14.0,
        "flow_mismatch_threshold_minutes": 5,
        "confidence": 0.84,
        "baseline_context": "active_flow",
        "baseline_fallback_level": "water_flow_context",
        "baseline_sample_count": 12,
        "contextual_baseline_confidence": 0.84,
        "contextual_status": "possible_flow_without_load",
    }
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=state,
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="washer",
        name="Washer",
        appliance_profile=ApplianceProfile.WASHER,
        mode=CircuitMode.SINGLE_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = processors.WaterContextAlertProcessor(
        alert_policy_for_circuit=lambda circuit_id, feature: policy,
    )

    result = processor.process(config, context)

    assert result.state_updates == []
    assert result.store_dirty is False
    assert len(result.alerts) == 1
    assert result.notifications == result.alerts
    assert result.alerts[0].feature == "water_flow_correlation"
    assert result.alerts[0].message == (
        "Possible issue: Washer water context changed. "
        "Water flow has been active for 14 minutes."
    )
    assert policy.observations[0].observed_value == 14.0
    assert policy.observations[0].baseline_value == 5.0
    assert policy.observations[0].baseline_confidence == 0.84
    assert policy.observations[0].features == {
        "mismatch_minutes": 14.0,
        "flow_active_minutes": 14.0,
        "confidence": 0.84,
        "baseline_context": "active_flow",
        "baseline_fallback_level": "water_flow_context",
        "baseline_sample_count": 12.0,
        "contextual_baseline_confidence": 0.84,
        "contextual_status": "possible_flow_without_load",
    }


def test_nilm_session_specs_skip_retired_direct_meter_assignment() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _nilm_session_specs,
    )

    assignments = [
        {
            "assignment_id": "retired",
            "signature_fingerprints": ["retired-signature"],
            "lifecycle_state": "retired",
        },
        {
            "assignment_id": "converted",
            "signature_fingerprints": ["converted-signature"],
            "conversion_state": "direct_meter",
            "keep_assignment_for_masking": False,
        },
        {
            "assignment_id": "ignored",
            "signature_fingerprints": ["ignored-signature"],
            "lifecycle_state": "ignored",
        },
        {
            "assignment_id": "expected",
            "signature_fingerprints": ["expected-signature"],
            "lifecycle_state": "expected",
        },
        {
            "assignment_id": "masking",
            "signature_fingerprints": ["masking-signature"],
            "conversion_state": "direct_meter",
            "keep_assignment_for_masking": True,
        },
    ]

    assert _nilm_session_specs(
        [
            {"signature_id": "ignored-signature"},
            {"signature_id": "expected-signature"},
        ],
        assignments,
    ) == [
        ("expected-signature", "expected"),
        ("masking-signature", "masking")
    ]


def test_nilm_session_specs_do_not_let_placeholder_or_off_edges_own_sessions() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _nilm_session_specs,
    )

    assert _nilm_session_specs(
        [
            {"signature_id": "on-pump", "direction": "on"},
            {"signature_id": "off-pump", "direction": "off"},
        ],
        [
            {
                "assignment_id": "broken",
                "signature_fingerprints": ["unassigned", "off-pump"],
            }
        ],
    ) == [("on-pump", None)]


def test_placeholder_assignment_does_not_starve_three_recurring_load_groups() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import (
        NilmEdge,
        cluster_recurring_signatures,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _recover_unassigned_session_edges,
        _runtime_assignment_model,
    )

    assignment = {
        "assignment_id": "broken",
        "signature_fingerprints": ["unassigned"],
        "power_states_w": [0.0, 80.0],
        "transition_prototypes": [
            {
                "direction": "on",
                "from_state_w": 0.0,
                "to_state_w": 80.0,
                "delta_w": 80.0,
                "spread_w": 2.0,
                "sample_count": 3,
            }
        ],
    }
    start = datetime(2026, 8, 4, tzinfo=UTC)
    sessions = [
        {
            "signature_fingerprint": "unassigned",
            "start": (start + timedelta(minutes=index)).isoformat(),
            "on_delta_w": watts,
            "on_delta_var": reactive,
        }
        for index, (watts, reactive) in enumerate(
            [(80.0, 18.0), (82.0, 19.0), (84.0, 20.0),
             (185.0, 65.0), (190.0, 68.0), (195.0, 70.0),
             (315.0, 115.0), (320.0, 120.0), (325.0, 125.0)]
        )
    ]
    edges = _recover_unassigned_session_edges(sessions, since=start)
    hidden_edges = _recover_unassigned_session_edges(
        [{**sessions[0], "assignment_id": "hidden"}],
        since=start,
        excluded_assignment_ids={"hidden"},
    )

    assert _runtime_assignment_model(assignment).transition_prototypes == ()
    assert all(isinstance(edge, NilmEdge) for edge in edges)
    assert {edge.origin for edge in edges} == {"recovered_session"}
    assert hidden_edges == []
    assert [
        round(signature.median_delta_w)
        for signature in cluster_recurring_signatures(edges)
    ] == [82, 190, 320]


def test_nilm_session_history_assigns_overlapping_signatures_once() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _nilm_session_history_payloads,
    )

    start = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    sessions = _nilm_session_history_payloads(
        "mains",
        [
            NilmEdge(start, 150.0, 0.0, 150.0, 0.0, "on"),
            NilmEdge(
                start + timedelta(minutes=5),
                -150.0,
                0.0,
                -150.0,
                0.0,
                "off",
            ),
        ],
        [
            {"signature_id": "120-w", "typical_watts": 120.0},
            {"signature_id": "187-w", "typical_watts": 187.0},
        ],
        [],
    )

    assert len(sessions) == 1
    assert sessions[0]["signature_fingerprint"] == "120-w"


def test_nilm_session_history_persists_residual_trace_measurements() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _nilm_session_history_payloads,
    )

    start = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    sessions = _nilm_session_history_payloads(
        "mains",
        [
            NilmEdge(start, 100.0, direction="on"),
            NilmEdge(start + timedelta(minutes=10), -100.0, direction="off"),
        ],
        [{"signature_id": "pump", "typical_watts": 100.0}],
        [],
        power_trace=[
            (start - timedelta(seconds=30), 0.0),
            (start, 0.0),
            (start + timedelta(minutes=1), 120.0),
            (start + timedelta(minutes=5), 120.0),
            (start + timedelta(minutes=9), 120.0),
            (start + timedelta(minutes=10), 0.0),
        ],
    )

    assert sessions[0]["plateau_power_w"] == 120.0
    assert sessions[0]["measured_energy_kwh"] == pytest.approx(0.018)
    assert sessions[0]["power_coverage"] == 1.0


def test_nilm_completed_session_retains_separate_transition_deltas() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _nilm_session_history_payloads,
    )

    start = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    sessions = _nilm_session_history_payloads(
        "mixed",
        [
            NilmEdge(start, 83.0, 0.0, 83.0, 0.0, "on"),
            NilmEdge(start + timedelta(minutes=5), -79.0, 0.0, -79.0, 0.0, "off"),
        ],
        [{"signature_id": "pump", "typical_watts": 81.0}],
        [{"assignment_id": "pump", "signature_fingerprints": ["pump"]}],
    )

    assert sessions[0]["on_delta_w"] == 83.0
    assert sessions[0]["off_delta_w"] == -79.0


def test_reviewed_fingerprint_drift_requests_review_without_relearning() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _record_assignment_model_drift,
    )

    assignment = {
        "model_revision": 4,
        "transition_prototypes": [{
            "direction": "on", "delta_w": 83.0, "spread_w": 2.0,
            "sample_count": 4,
        }],
    }
    prototypes = list(assignment["transition_prototypes"])
    start = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)

    for index in range(3):
        _record_assignment_model_drift(assignment, "pump", [
            NilmEdge(start + timedelta(minutes=index), 140.0, 0.0, 140.0, 0.0, "on")
        ])

    assert assignment["model_status"] == "needs_review"
    assert assignment["model_revision"] == 4
    assert assignment["transition_prototypes"] == prototypes


def test_assignment_drift_is_scoped_per_persisted_fingerprint() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _record_assignment_model_drift,
    )

    assignment = {"transition_prototypes": [{
        "direction": "on", "delta_w": 80.0, "spread_w": 2.0,
    }]}
    start = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    for index, fingerprint in enumerate(("one", "two", "three")):
        _record_assignment_model_drift(assignment, fingerprint, [
            NilmEdge(start + timedelta(minutes=index), 140.0, 0.0, 140.0, 0.0, "on")
        ])
    assert assignment.get("model_status") is None

    restored = dict(assignment)
    for index in range(2):
        _record_assignment_model_drift(
            restored,
            "one",
            [NilmEdge(
                start + timedelta(minutes=10 + index),
                140.0, 0.0, 140.0, 0.0, "on",
            )],
        )
    assert restored["model_status"] == "needs_review"


def test_assignment_drift_retains_all_reviewed_fingerprints_across_restart() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _record_assignment_model_drift,
    )

    fingerprints = [f"signature-{index}" for index in range(5)]
    assignment = {
        "signature_fingerprints": fingerprints,
        "transition_prototypes": [{
            "direction": "on", "delta_w": 80.0, "spread_w": 2.0,
        }],
    }
    start = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    for index, fingerprint in enumerate(fingerprints):
        _record_assignment_model_drift(assignment, fingerprint, [
            NilmEdge(start + timedelta(minutes=index), 140.0, 0.0, 140.0, 0.0, "on")
        ])

    restored = dict(assignment)
    for index in range(2):
        _record_assignment_model_drift(restored, fingerprints[0], [
            NilmEdge(
                start + timedelta(minutes=10 + index),
                140.0, 0.0, 140.0, 0.0, "on",
            )
        ])

    assert restored["model_status"] == "needs_review"


def test_legacy_assignment_v2_alias_retains_model_drift() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _ensure_nilm_assignment_fingerprint,
        _record_assignment_model_drift,
    )

    assignment = {
        "signature_fingerprints": ["legacy-pump"],
        "transition_prototypes": [{
            "direction": "on", "delta_w": 80.0, "spread_w": 2.0,
        }],
    }
    assert _ensure_nilm_assignment_fingerprint(assignment, "revision=2|pump")
    start = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    for index in range(3):
        _record_assignment_model_drift(assignment, "revision=2|pump", [
            NilmEdge(start + timedelta(minutes=index), 140.0, 0.0, 140.0, 0.0, "on")
        ])

    assert assignment["model_status"] == "needs_review"
    assert "revision=2|pump" in assignment["model_drift_edges_by_fingerprint"]


def test_nilm_session_history_closes_open_session_when_pair_becomes_ambiguous() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _merge_nilm_session_history,
        _nilm_session_history_payloads,
    )

    start = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    on_edge = NilmEdge(start, 125.0, 0.0, 125.0, 0.0, "on")
    existing = _nilm_session_history_payloads(
        "mains",
        [on_edge],
        [{"signature_id": "120-w", "typical_watts": 120.0}],
        [],
    )
    updates = _nilm_session_history_payloads(
        "mains",
        [
            on_edge,
            NilmEdge(
                start + timedelta(minutes=5),
                -125.0,
                0.0,
                -125.0,
                0.0,
                "off",
            ),
        ],
        [
            {"signature_id": "120-w", "typical_watts": 120.0},
            {"signature_id": "130-w", "typical_watts": 130.0},
        ],
        [],
    )

    merged = _merge_nilm_session_history(existing, updates)

    assert len(merged) == 1
    assert merged[0]["end"] == "2026-07-31T12:05:00+00:00"
    assert merged[0]["ambiguous"] is True
    assert merged[0]["assignment_id"] is None


def test_nilm_history_invalidates_open_owner_when_ambiguous() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _merge_nilm_session_history,
        _nilm_session_history_payloads,
    )

    on_edge = NilmEdge(
        datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
        125.0,
        0.0,
        125.0,
        0.0,
        "on",
    )
    existing = _nilm_session_history_payloads(
        "mains",
        [on_edge],
        [{"signature_id": "120-w", "typical_watts": 125.0}],
        [{"assignment_id": "load-a", "signature_fingerprints": ["120-w"]}],
    )
    updates = _nilm_session_history_payloads(
        "mains",
        [on_edge],
        [
            {"signature_id": "120-w", "typical_watts": 125.0},
            {"signature_id": "130-w", "typical_watts": 125.0},
        ],
        [
            {"assignment_id": "load-a", "signature_fingerprints": ["120-w"]},
            {"assignment_id": "load-b", "signature_fingerprints": ["130-w"]},
        ],
    )

    merged = _merge_nilm_session_history(existing, updates)

    assert len(merged) == 1
    assert merged[0]["end"] is None
    assert merged[0]["ambiguous"] is True
    assert merged[0]["assignment_id"] is None


def test_nilm_session_history_closes_open_session_across_owner_fingerprints() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _merge_nilm_session_history,
    )

    merged = _merge_nilm_session_history(
        [
            {
                "session_id": "open",
                "signature_fingerprint": "off-500",
                "assignment_id": "dryer",
                "on_edge_id": "on-1",
                "off_edge_id": None,
            }
        ],
        [
            {
                "session_id": "closed",
                "signature_fingerprint": "on-500",
                "assignment_id": "dryer",
                "on_edge_id": "on-1",
                "off_edge_id": "off-1",
            }
        ],
    )

    assert [session["session_id"] for session in merged] == ["closed"]


def test_nilm_session_history_preserves_close_across_open_fingerprints() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _merge_nilm_session_history,
    )

    assignment = {
        "assignment_id": "dryer",
        "rejected_session_ids": ["open-old"],
    }
    preserved_close = {
        "session_id": "closed",
        "off_edge_id": "off-1",
        "end": "2026-07-31T12:05:00+00:00",
        "duration_seconds": 300.0,
    }
    merged = _merge_nilm_session_history(
        [
            {
                "session_id": "open-old",
                "signature_fingerprint": "signature-old",
                "assignment_id": "dryer",
                "on_edge_id": "on-1",
                "off_edge_id": None,
                "_duration_bound_close": preserved_close,
            }
        ],
        [
            {
                "session_id": "open-new",
                "signature_fingerprint": "signature-new",
                "assignment_id": "dryer",
                "on_edge_id": "on-1",
                "off_edge_id": None,
            }
        ],
        assignments=[assignment],
    )

    assert merged[0]["_duration_bound_close"] == preserved_close
    assert assignment["rejected_session_ids"] == ["open-new"]


@pytest.mark.parametrize("existing_off_edge_id", ["off-1", "off-old"])
def test_nilm_session_history_replaces_stale_closed_edge_pair(
    existing_off_edge_id: str,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _merge_nilm_session_history,
    )

    merged = _merge_nilm_session_history(
        [
            {
                "session_id": "stale",
                "signature_fingerprint": "signature-a",
                "assignment_id": "appliance-a",
                "on_edge_id": "on-1",
                "off_edge_id": existing_off_edge_id,
            }
        ],
        [
            {
                "session_id": "current",
                "signature_fingerprint": "signature-b",
                "assignment_id": None,
                "on_edge_id": "on-1",
                "off_edge_id": "off-1",
                "ambiguous": True,
            }
        ],
    )

    assert [session["session_id"] for session in merged] == ["current"]


def test_nilm_session_history_replaces_stale_close_with_reopened_session() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _merge_nilm_session_history,
    )

    merged = _merge_nilm_session_history(
        [
            {
                "session_id": "closed",
                "signature_fingerprint": "dryer",
                "assignment_id": "dryer",
                "on_edge_id": "on-1",
                "off_edge_id": "off-1",
            }
        ],
        [
            {
                "session_id": "reopened",
                "signature_fingerprint": "dryer",
                "assignment_id": "dryer",
                "on_edge_id": "on-1",
                "off_edge_id": None,
            }
        ],
    )

    assert [session["session_id"] for session in merged] == ["reopened"]


def test_nilm_sample_processor_updates_signatures_and_unknown_inventory() -> None:
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdgeDetector
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData()
    state = AnalyzerState()
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=state,
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    topology_alerts: list[AlertEvidence] = []
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _circuit_id: 100.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _circuit_id, _events: (),
        observe_topology=lambda _config, _match, _context: topology_alerts,
    )

    def sample(index: int, watts: float) -> NormalizedCircuitSample:
        return NormalizedCircuitSample(
            timestamp=now + timedelta(seconds=index * 10),
            circuit_id="mains",
            real_power=watts,
            current=None,
            voltage=None,
            reactive_power=10.0 if watts < 200 else 150.0,
            apparent_power=abs(watts),
            power_factor=0.8,
            frequency=60.0,
            energy=None,
        )

    results = [
        processor.process(
            sample(index, watts),
            config,
            context,
            events=(),
        )
        for index, watts in enumerate(
            (
                100,
                1_000,
                100,
                420,
                410,
                110,
                120,
                430,
                420,
                115,
                120,
                425,
                415,
            ),
            start=1,
        )
    ]

    assert any(result.store_dirty for result in results)
    assert isinstance(processor.detectors["mains"], NilmEdgeDetector)
    assert processor.total_events_by_circuit["mains"] == 5
    assert len(processor.unmatched_edges_by_circuit["mains"]) == 5
    assert [
        payload["delta_w"]
        for payload in store_data.nilm_unmatched_edges_by_circuit["mains"]
    ] == [edge.delta_w for edge in processor.unmatched_edges_by_circuit["mains"]]
    assert topology_alerts == []
    assert len(store_data.nilm_signatures["mains"]) == 1

    signature = store_data.nilm_signatures["mains"][0]
    assert signature["signature_id"].startswith("on-")
    assert signature["occurrence_count"] == 3
    assert signature["classification"].startswith("possible")
    updates = {update.path: update.value for update in results[-1].state_updates}
    assert updates[("nilm_signature_count_by_circuit", "mains")] == 1
    assert updates[("nilm_unmatched_load_percentage_by_circuit", "mains")] == 100.0
    assert updates[("nilm_review_by_circuit", "mains")][0]["signature_id"] == (
        signature["signature_id"]
    )
    inventory = updates[("nilm_unknown_loads_by_circuit", "mains")]
    assert inventory["unknown_load_count"] == 1
    assert inventory["unknown_loads"][0]["signature_id"] == signature["signature_id"]
    assert "estimated_energy_today_kwh" in inventory["unknown_loads"][0]


def test_nilm_processor_builds_inventory_after_refreshing_current_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections import defaultdict
    from copy import deepcopy

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData()
    store_data.nilm_unmatched_edges_by_circuit["mains"] = [
        {
            "timestamp": (now + timedelta(minutes=minutes)).isoformat(),
            "delta_w": watts,
            "delta_var": 100.0 if watts > 0 else -100.0,
            "delta_va": 510.0,
            "delta_pf": 0.0,
            "direction": direction,
            "dominant_leg": "a",
            "split_phase_type": "single_leg_a",
        }
        for minutes, watts, direction in (
            (0, 500.0, "on"),
            (10, -500.0, "off"),
            (20, 500.0, "on"),
            (40, -500.0, "off"),
            (50, 500.0, "on"),
            (80, -500.0, "off"),
        )
    ]
    store_data.nilm_unknown_loads_by_circuit["mains"] = {
        "circuit_id": "mains",
        "unknown_loads": [
            {"signature_id": "on-legacy", "review_state": "assigned"},
            {"signature_id": "off-legacy", "review_state": "new"},
        ],
    }
    context = ProcessingContext(
        now=now + timedelta(minutes=90),
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _circuit_id: 100.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _circuit_id, _events: (),
        observe_topology=lambda _config, _match, _context: [],
    )
    sample = NormalizedCircuitSample(
        timestamp=context.now,
        circuit_id="mains",
        real_power=100.0,
        current=None,
        voltage=None,
        reactive_power=None,
        apparent_power=None,
        power_factor=None,
        frequency=60.0,
        energy=None,
    )

    result = processor.process(sample, config, context, events=())

    inventory = store_data.nilm_unknown_loads_by_circuit["mains"]
    assert result.store_dirty
    assert inventory["schema_version"] == 4
    assert inventory["unknown_load_count"] == 1
    assert inventory["unknown_loads"][0]["matched_on_edge_count"] == 3
    assert inventory["unknown_loads"][0]["matched_off_edge_count"] == 3
    assert inventory["unknown_loads"][0]["runtime_today_minutes"] == 60.0

    snapshot = deepcopy(inventory)
    def unexpected_rebuild(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("stable NILM samples must not rebuild derived history")

    monkeypatch.setattr(processor, "refresh_session_history", unexpected_rebuild)
    monkeypatch.setattr(
        "custom_components.circuitsetup_energy_analyzer.processors.nilm_sample"
        ".cluster_recurring_signatures",
        unexpected_rebuild,
    )
    monkeypatch.setattr(
        "custom_components.circuitsetup_energy_analyzer.processors.nilm_sample"
        ".build_unknown_load_inventory",
        unexpected_rebuild,
    )
    monkeypatch.setattr(
        "custom_components.circuitsetup_energy_analyzer.processors.nilm_sample"
        ".migrate_unknown_load_inventory",
        unexpected_rebuild,
    )
    later_sample = replace(sample, timestamp=sample.timestamp + timedelta(minutes=5))
    second_result = processor.process(later_sample, config, context, events=())
    current_inventory = {
        update.path: update.value for update in second_result.state_updates
    }[("nilm_unknown_loads_by_circuit", "mains")]

    assert not second_result.store_dirty
    assert store_data.nilm_unknown_loads_by_circuit["mains"] == snapshot
    assert current_inventory == snapshot


def test_nilm_processor_does_not_recluster_an_empty_signature_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retained edge set with no signature is still stable evidence."""
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData()
    store_data.nilm_unmatched_edges_by_circuit["mains"] = [
        {
            "timestamp": now.isoformat(),
            "delta_w": 500.0,
            "direction": "on",
        }
    ]
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _circuit_id: 100.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _circuit_id, _events: (),
        observe_topology=lambda _config, _match, _context: [],
    )
    sample = NormalizedCircuitSample(
        timestamp=now,
        circuit_id="mains",
        real_power=100.0,
        current=None,
        voltage=None,
        reactive_power=None,
        apparent_power=None,
        power_factor=None,
        frequency=60.0,
        energy=None,
    )

    processor.process(sample, config, context, events=())
    assert store_data.nilm_signatures.get("mains", []) == []

    def unexpected_recluster(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("steady empty NILM evidence must not be reclustered")

    monkeypatch.setattr(
        "custom_components.circuitsetup_energy_analyzer.processors.nilm_sample"
        ".cluster_recurring_signatures",
        unexpected_recluster,
    )
    processor.process(
        replace(sample, timestamp=sample.timestamp + timedelta(minutes=5)),
        config,
        context,
        events=(),
    )


def test_nilm_inventory_cache_tracks_open_sessions_and_window_boundaries() -> None:
    """Keep dynamic inventory fields fresh without rebuilding stable history."""
    from custom_components.circuitsetup_energy_analyzer import processors

    now = datetime(2026, 6, 11, 23, 55, tzinfo=UTC)
    store_data = FeatureStoreData()
    store_data.nilm_session_history_by_circuit["mains"] = [
        {
            "session_id": "open",
            "start": (now - timedelta(minutes=30)).isoformat(),
            "end": None,
            "signature_fingerprint": "open-signature",
        }
    ]
    first_open_context = processors.NilmSampleProcessor._inventory_context(
        "mains",
        store_data,
        existing_inventory={"active_unknown_load_count": 1},
        now=now,
        time_zone="UTC",
    )
    later_open_context = processors.NilmSampleProcessor._inventory_context(
        "mains",
        store_data,
        existing_inventory={"active_unknown_load_count": 1},
        now=now + timedelta(minutes=5),
        time_zone="UTC",
    )
    assert first_open_context != later_open_context

    store_data.nilm_session_history_by_circuit["mains"] = [
        {
            "session_id": "closed",
            "start": (now - timedelta(hours=2)).isoformat(),
            "end": (now - timedelta(hours=1)).isoformat(),
            "signature_fingerprint": "closed-signature",
        }
    ]
    before_midnight = processors.NilmSampleProcessor._inventory_context(
        "mains",
        store_data,
        existing_inventory={"active_unknown_load_count": 0},
        now=now,
        time_zone="UTC",
    )
    after_midnight = processors.NilmSampleProcessor._inventory_context(
        "mains",
        store_data,
        existing_inventory={"active_unknown_load_count": 0},
        now=now + timedelta(minutes=10),
        time_zone="UTC",
    )
    assert before_midnight != after_midnight


def test_nilm_processor_records_actual_session_retention_coverage() -> None:
    """Configured capacity alone is not evidence that history was truncated."""
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.unknown_loads import (
        NilmSessionHistoryCoverage,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        nilm_session_history_by_circuit={
            "mains": [
                {
                    "session_id": f"retained-{day}",
                    "signature_fingerprint": "load-a",
                    "start": (now - timedelta(days=31 - day)).isoformat(),
                    "end": (now - timedelta(days=31 - day, minutes=-5)).isoformat(),
                }
                for day in range(31)
            ]
        }
    )
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _circuit_id: 100.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _circuit_id, _events: (),
        observe_topology=lambda _config, _match, _context: [],
        session_history_max_items=2_000,
    )

    processor.refresh_session_history("mains", store_data)
    assert processor._session_history_coverage_by_circuit["mains"] == (
        NilmSessionHistoryCoverage(
            configured_max_items=2_000,
            source_count_before_retention=31,
            retained_count=31,
            was_truncated=False,
            dropped_count=0,
            oldest_retained_at=now - timedelta(days=31),
            newest_retained_at=now - timedelta(days=1, minutes=-5),
        )
    )


def test_nilm_processor_coverage_is_component_and_window_specific() -> None:
    """Processor-captured coverage never spreads a bad session to other loads."""
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmSignature
    from custom_components.circuitsetup_energy_analyzer.unknown_loads import (
        build_unknown_load_inventory,
        migrate_unknown_load_inventory,
    )

    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    signatures = [
        NilmSignature("on-a", 500.0, 100.0, occurrence_count=3),
        NilmSignature("on-b", 700.0, 100.0, occurrence_count=3),
    ]

    def run(rows: list[dict[str, object]], cap: int = 2_000) -> dict[str, object]:
        store = FeatureStoreData(nilm_session_history_by_circuit={"mains": rows})
        processor = processors.NilmSampleProcessor(
            nilm_enabled=lambda _: True, seed_demo_nilm_state=lambda *_: None,
            min_delta_w_for_circuit=lambda _: 100.0, detectors={},
            total_events_by_circuit=defaultdict(int),
            unmatched_edges_by_circuit=defaultdict(list), ignored_signatures=set(),
            known_load_events=lambda *_: (), observe_topology=lambda *_: [],
            session_history_max_items=cap,
        )
        processor.refresh_session_history("mains", store)
        return build_unknown_load_inventory(
            circuit_id="mains", signatures=signatures, edges=(),
            sessions=store.nilm_session_history_by_circuit["mains"], now=now,
            session_history_coverage=processor._session_history_coverage_by_circuit["mains"],
        )

    def row(name: str, owner: str, age: int, **extra: object) -> dict[str, object]:
        start = now - timedelta(days=age, hours=1)
        return {"session_id": name, "signature_id": owner,
                "signature_fingerprint": owner, "start": start.isoformat(),
                "end": (start + timedelta(minutes=30)).isoformat(), **extra}

    def by_signature(value: dict[str, object]) -> dict[str, dict[str, object]]:
        return {str(item["on_signature_id"]): item for item in value["unknown_loads"]}  # type: ignore[index]

    complete = by_signature(
        run([row("a-old", "on-a", 31), row("b-old", "on-b", 31)])
    )
    assert complete["on-a"]["estimate_status_by_window"]["30_days"] == "complete"  # type: ignore[index]
    truncated = by_signature(run([row(f"a-{i}", "on-a", i + 1) for i in range(5)], 2))
    assert (
        truncated["on-a"]["estimate_status_by_window"]["30_days"]
        == "partial_history"
    )  # type: ignore[index]
    assert truncated["on-a"]["estimate_status_by_window"]["today"] == "complete"  # type: ignore[index]
    isolated = by_signature(run([
        row("a-old", "on-a", 31), row("b-old", "on-b", 31),
        {
            "session_id": "bad-a", "signature_id": "on-a",
            "signature_fingerprint": "on-a", "start": "bad", "end": "bad",
        },
        {
            "session_id": "unowned", "signature_fingerprint": "x",
            "start": (now - timedelta(days=31)).isoformat(),
            "end": (now - timedelta(days=30)).isoformat(),
        },
    ]))
    assert isolated["on-a"]["estimate_status"] == "partial_history"
    assert isolated["on-b"]["estimate_status"] == "complete"
    ambiguous = by_signature(run([
        row("a-old", "on-a", 31), row("b-old", "on-b", 31),
        row("both", "on-a", 1, on_signature_id="on-b"),
    ]))
    assert ambiguous["on-a"]["estimate_status"] == "ambiguous"
    assert ambiguous["on-b"]["estimate_status"] == "ambiguous"
    started = by_signature(
        run([row("a-old", "on-a", 31), row("b-new", "on-b", 5)])
    )
    assert started["on-a"]["estimate_status_by_window"]["30_days"] == "complete"  # type: ignore[index]
    assert (
        started["on-b"]["estimate_status_by_window"]["30_days"]
        == "partial_history"
    )  # type: ignore[index]
    legacy = migrate_unknown_load_inventory(
        circuit_id="mains", signature_payloads=[],
        existing_state={
            "schema_version": 3, "unknown_loads": [{"signature_id": "on-a"}]
        },
    )
    assert legacy["estimate_status"] == "legacy_unverified"


def test_nilm_processor_retains_persisted_truncation_coverage_after_restart() -> None:
    """A restarted processor must not recast a capped store as complete history."""
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.unknown_loads import (
        NilmSessionHistoryCoverage,
    )

    store = FeatureStoreData(
        nilm_session_history_by_circuit={"mains": []},
        nilm_unknown_loads_by_circuit={
            "mains": {
                "session_history_coverage": {
                    "configured_max_items": 2,
                    "source_count_before_retention": 5,
                    "retained_count": 2,
                    "was_truncated": True,
                    "dropped_count": 3,
                    "oldest_retained_at": "2026-08-08T00:00:00+00:00",
                    "newest_retained_at": "2026-08-10T00:00:00+00:00",
                }
            }
        },
    )
    for day in (8, 10):
        store.nilm_session_history_by_circuit["mains"].append(
            {
                "session_id": f"run-{day}",
                "signature_fingerprint": "on-a",
                "start": f"2026-08-{day:02d}T00:00:00+00:00",
                "end": f"2026-08-{day:02d}T00:30:00+00:00",
            }
        )
    restarted = processors.NilmSampleProcessor(
        nilm_enabled=lambda _: True, seed_demo_nilm_state=lambda *_: None,
        min_delta_w_for_circuit=lambda _: 100.0, detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list), ignored_signatures=set(),
        known_load_events=lambda *_: (), observe_topology=lambda *_: [],
        session_history_max_items=2,
    )

    context = ProcessingContext(
        now=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        hass=SimpleNamespace(data={DOMAIN: {}}), state=AnalyzerState(),
        store_data=store, options={}, entry_data={}, known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="mains", name="Mains", appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    restarted.process(
        NormalizedCircuitSample(
            timestamp=context.now, circuit_id="mains", real_power=0.0,
            current=None, voltage=None, reactive_power=None, apparent_power=None,
            power_factor=None, frequency=None, energy=None,
        ),
        config, context, events=(),
    )

    assert restarted._session_history_coverage_by_circuit["mains"] == (
        NilmSessionHistoryCoverage(
            configured_max_items=2,
            source_count_before_retention=5,
            retained_count=2,
            was_truncated=True,
            dropped_count=3,
            oldest_retained_at=datetime(2026, 8, 8, tzinfo=UTC),
            newest_retained_at=datetime(2026, 8, 10, tzinfo=UTC),
        )
    )


def test_nilm_sample_processor_caps_runtime_unmatched_edges() -> None:
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _circuit_id: 100.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _circuit_id, _events: (),
        observe_topology=lambda _config, _match, _context: [],
        unmatched_edges_max_items=3,
    )

    def sample(index: int, watts: float) -> NormalizedCircuitSample:
        return NormalizedCircuitSample(
            timestamp=now + timedelta(seconds=index * 30),
            circuit_id="mains",
            real_power=watts,
            current=None,
            voltage=None,
            reactive_power=None,
            apparent_power=None,
            power_factor=None,
            frequency=60.0,
            energy=None,
        )

    for index, watts in enumerate((100, 260, 100, 260, 100, 260), start=1):
        processor.process(sample(index, watts), config, context, events=())

    retained_edges = processor.unmatched_edges_by_circuit["mains"]
    assert len(retained_edges) == 3
    assert [edge.timestamp for edge in retained_edges] == [
        now + timedelta(seconds=index * 30) for index in (4, 5, 6)
    ]


def test_nilm_processor_restores_raw_edges_before_legacy_sessions() -> (
    None
):
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    raw_edge = NilmEdge(
        timestamp=now - timedelta(seconds=30),
        delta_w=250.0,
        delta_var=110.0,
        delta_va=275.0,
        delta_pf=-0.08,
        direction="on",
        leg_a_delta_w=245.0,
        leg_b_delta_w=5.0,
        leg_balance_ratio=0.02,
        dominant_leg="a",
        split_phase_type="single_leg_a",
    )
    store_data = FeatureStoreData(
        nilm_unmatched_edges_by_circuit={
            "mains": [
                {
                    "timestamp": raw_edge.timestamp.isoformat(),
                    "delta_w": raw_edge.delta_w,
                    "delta_var": raw_edge.delta_var,
                    "delta_va": raw_edge.delta_va,
                    "delta_pf": raw_edge.delta_pf,
                    "direction": raw_edge.direction,
                    "leg_a_delta_w": raw_edge.leg_a_delta_w,
                    "leg_b_delta_w": raw_edge.leg_b_delta_w,
                    "leg_balance_ratio": raw_edge.leg_balance_ratio,
                    "dominant_leg": raw_edge.dominant_leg,
                    "split_phase_type": raw_edge.split_phase_type,
                }
            ]
        },
        nilm_session_history_by_circuit={
            "mains": [
                {
                    "signature_fingerprint": "unassigned",
                    "start": raw_edge.timestamp.isoformat(),
                    "on_delta_w": raw_edge.delta_w,
                }
            ]
        },
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _circuit_id: 100.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _circuit_id, _events: (),
        observe_topology=lambda _config, _match, _context: [],
    )
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )

    processor.process(
        NormalizedCircuitSample(
            timestamp=now,
            circuit_id="mains",
            real_power=100.0,
            current=None,
            voltage=None,
            reactive_power=None,
            apparent_power=None,
            power_factor=None,
            frequency=60.0,
            energy=None,
        ),
        config,
        context,
        events=(),
    )

    assert processor.unmatched_edges_by_circuit["mains"] == [raw_edge]


def test_nilm_session_history_replaces_open_session_when_off_edge_arrives() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _merge_nilm_session_history,
    )

    open_session = {
        "session_id": "open-session",
        "signature_fingerprint": "signature-dishwasher",
        "on_edge_id": "edge-on",
        "off_edge_id": None,
        "start": "2026-06-11T12:00:00+00:00",
        "end": None,
    }
    closed_update = {
        "session_id": "closed-session",
        "signature_fingerprint": "signature-dishwasher",
        "on_edge_id": "edge-on",
        "off_edge_id": "edge-off",
        "start": "2026-06-11T12:00:00+00:00",
        "end": "2026-06-11T12:45:00+00:00",
    }

    merged = _merge_nilm_session_history([open_session], [closed_update])

    assert [session["session_id"] for session in merged] == ["closed-session"]
    assert merged[0]["off_edge_id"] == "edge-off"


def test_nilm_runtime_reconciles_overlapping_components_and_conserves_power() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignments = [
        {
            "assignment_id": assignment_id,
            "lifecycle_state": "validated",
            "power_states_w": [0.0, watts],
            "transition_prototypes": [
                {"direction": "on", "from_state_w": 0.0, "to_state_w": watts,
                 "delta_w": watts, "spread_w": 2.0, "sample_count": 3},
                {"direction": "off", "from_state_w": watts, "to_state_w": 0.0,
                 "delta_w": -watts, "spread_w": 2.0, "sample_count": 3},
            ],
            "model_confidence": 0.9,
        }
        for assignment_id, watts in (("blower", 100.0), ("pump", 80.0))
    ]
    runtime = {
        assignment_id: {
            "status": "off", "state_power_w": 0.0, "estimated_power_w": 0.0,
            "session_id": None, "session_start": None, "confidence": 0.9,
            "consistent": True, "last_observed": now.isoformat(),
            "energy_kwh": 0.0,
        }
        for assignment_id in ("blower", "pump")
    }
    edges = [
        NilmEdge(now + timedelta(seconds=10), 180.0, 0.0, 180.0, 0.0, "on"),
        NilmEdge(now + timedelta(seconds=20), -100.0, 0.0, -100.0, 0.0, "off"),
    ]

    runtime, first, completed, accepted = reconcile_component_runtime(
        source_power_w=200.0, timestamp=now + timedelta(seconds=10),
        assignments=assignments, runtime=runtime, edges=edges[:1],
        standby_w=0.0, noise_spread_w=2.0,
    )
    assert accepted == edges[:1]
    assert {key: item["status"] for key, item in runtime.items()} == {
        "blower": "on", "pump": "on"
    }
    assert completed == []
    assert first["residual_w"] == pytest.approx(0.0)
    assert first["source_power_w"] == pytest.approx(
        first["standby_w"]
        + sum(item["estimated_power_w"] for item in runtime.values())
        + first["residual_w"]
    )

    runtime, second, completed, accepted = reconcile_component_runtime(
        source_power_w=80.0, timestamp=now + timedelta(seconds=20),
        assignments=assignments, runtime=runtime, edges=edges[1:],
        standby_w=0.0, noise_spread_w=2.0, previous_reconciliation=first,
    )
    assert accepted == edges[1:]
    assert runtime["blower"]["status"] == "off"
    assert runtime["pump"]["status"] == "on"
    assert completed[0]["assignment_id"] == "blower"
    assert completed[0]["on_delta_w"] == 100.0
    assert completed[0]["off_delta_w"] == -100.0
    assert completed[0]["energy_kwh"] == pytest.approx(
        (200.0 * 100.0 / 180.0) * 10 / 3_600_000
    )
    assert second["allocated_power_w"] == 80.0


def test_nilm_runtime_attributes_pump_blower_and_combined_states() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _initial_component_runtime,
        reconcile_component_runtime,
    )

    start = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignments = (
        _reconciliation_assignment("pump", 84.0),
        _reconciliation_assignment("blower", 319.0),
    )
    runtime = _initial_component_runtime(assignments, {}, start)
    for payload in runtime.values():
        payload.update({
            "status": "off", "state_power_w": 0.0, "estimated_power_w": 0.0,
        })

    runtime, reconciliation, _, _ = reconcile_component_runtime(
        source_power_w=84.0,
        timestamp=start,
        assignments=assignments,
        runtime=runtime,
        edges=(NilmEdge(start, 84.0, 18.0, 86.0, 0.0, "on"),),
        standby_w=0.0,
        noise_spread_w=2.0,
    )
    assert runtime["pump"]["status"] == "on"
    assert runtime["blower"]["status"] == "off"

    runtime, reconciliation, _, _ = reconcile_component_runtime(
        source_power_w=379.0,
        timestamp=start + timedelta(seconds=60),
        assignments=assignments,
        runtime=runtime,
        edges=(NilmEdge(
            start + timedelta(seconds=60), 319.0, 120.0, 341.0, 0.0, "on"
        ),),
        standby_w=0.0,
        noise_spread_w=2.0,
        previous_reconciliation=reconciliation,
    )
    assert {item["status"] for item in runtime.values()} == {"on"}
    assert sum(item["estimated_power_w"] for item in runtime.values()) == pytest.approx(
        379.0
    )
    assert reconciliation["residual_w"] == pytest.approx(0.0)

    runtime, reconciliation, pump_sessions, _ = reconcile_component_runtime(
        source_power_w=319.0,
        timestamp=start + timedelta(seconds=120),
        assignments=assignments,
        runtime=runtime,
        edges=(NilmEdge(
            start + timedelta(seconds=120), -84.0, -18.0, -86.0, 0.0, "off"
        ),),
        standby_w=0.0,
        noise_spread_w=2.0,
        previous_reconciliation=reconciliation,
    )
    assert runtime["pump"]["status"] == "off"
    assert runtime["blower"]["status"] == "on"
    assert runtime["blower"]["estimated_power_w"] == pytest.approx(319.0)
    assert pump_sessions[0]["assignment_id"] == "pump"
    assert pump_sessions[0]["on_delta_var"] == 18.0
    assert pump_sessions[0]["off_delta_var"] == -18.0

    runtime, reconciliation, blower_sessions, _ = reconcile_component_runtime(
        source_power_w=0.0,
        timestamp=start + timedelta(seconds=180),
        assignments=assignments,
        runtime=runtime,
        edges=(NilmEdge(
            start + timedelta(seconds=180), -319.0, -120.0, -341.0, 0.0, "off"
        ),),
        standby_w=0.0,
        noise_spread_w=2.0,
        previous_reconciliation=reconciliation,
    )
    assert {item["status"] for item in runtime.values()} == {"off"}
    assert blower_sessions[0]["assignment_id"] == "blower"
    assert blower_sessions[0]["on_delta_var"] == 120.0
    assert blower_sessions[0]["off_delta_var"] == -120.0
    attributed = sum(
        item["energy_kwh"] for item in (*pump_sessions, *blower_sessions)
    )
    assert attributed == pytest.approx(reconciliation["component_energy_kwh"])
    assert attributed <= reconciliation["source_energy_kwh"]


@pytest.mark.parametrize(
    "previous",
    [
        "truthy but not a mapping",
        {"last_observed": "2026-06-11T12:00:00+00:00"},
        {
            "source_power_w": float("inf"),
            "last_observed": "2026-06-11T12:00:00+00:00",
        },
        {"source_power_w": 80.0, "last_observed": "not-a-timestamp"},
    ],
)
def test_nilm_pending_reconciliation_rejects_invalid_previous_truth(
    previous: object,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _pending_reconciliation_source,
    )

    assert _pending_reconciliation_source(
        previous, datetime(2026, 6, 11, 12, 1, tzinfo=UTC)
    ) is None


def test_nilm_pending_reconciliation_accepts_finite_timestamped_source() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _pending_reconciliation_source,
    )

    assert _pending_reconciliation_source(
        {
            "source_power_w": 80.0,
            "last_observed": "2026-06-11T12:00:00+00:00",
        },
        datetime(2026, 6, 11, 12, 1, tzinfo=UTC),
    ) == pytest.approx(80.0)


def test_nilm_pending_reconciliation_rejects_future_previous_truth() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _pending_reconciliation_source,
    )

    assert _pending_reconciliation_source(
        {
            "source_power_w": 80.0,
            "last_observed": "2026-06-11T12:00:10+00:00",
        },
        datetime(2026, 6, 11, 12, 0, 5, tzinfo=UTC),
    ) is None


@pytest.mark.parametrize(
    "previous",
    [
        "truthy but not a mapping",
        {"last_observed": "2026-06-11T12:00:00+00:00"},
        {
            "source_power_w": float("nan"),
            "last_observed": "2026-06-11T12:00:00+00:00",
        },
        {"source_power_w": 80.0, "last_observed": "invalid"},
        {
            "source_power_w": 80.0,
            "last_observed": "2026-06-11T12:00:10+00:00",
        },
    ],
)
def test_nilm_pending_edge_defers_when_previous_truth_is_invalid(
    previous: object,
) -> None:
    from collections import defaultdict
    from types import SimpleNamespace

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.models import (
        ApplianceProfile,
        CircuitConfig,
        CircuitMode,
    )
    from custom_components.circuitsetup_energy_analyzer.normalize import (
        NormalizedCircuitSample,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData

    class PendingDetector:
        min_delta_w = 20.0
        has_pending_transition = True
        noise_spread_w = 0.0

        def process(self, _sample: object) -> list[object]:
            return []

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    state = AnalyzerState()
    state.nilm_reconciliation_by_circuit["mixed"] = previous  # type: ignore[assignment]
    state.nilm_component_runtime_by_circuit["mixed"] = {
        "pump": {"status": "on", "estimated_power_w": 80.0}
    }
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _id: 20.0,
        detectors={"mixed": PendingDetector()},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _id, _events: (),
        observe_topology=lambda _config, _match, _context: [],
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=state,
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [_reconciliation_assignment("pump", 80.0)]
            }
        ),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="balanced",
    )

    result = processor.process(
        NormalizedCircuitSample(
            timestamp=now,
            circuit_id="mixed",
            real_power=0.0,
            current=None,
            voltage=None,
            reactive_power=None,
            apparent_power=None,
            power_factor=None,
            frequency=None,
            energy=None,
        ),
        CircuitConfig("mixed", "Mixed", ApplianceProfile.MIXED, CircuitMode.MIXED),
        context,
        events=(),
    )

    updated_paths = {update.path for update in result.state_updates}
    assert ("nilm_component_runtime_by_circuit", "mixed") not in updated_paths
    assert ("nilm_reconciliation_by_circuit", "mixed") not in updated_paths
    assert state.nilm_reconciliation_by_circuit["mixed"] is previous


def test_nilm_future_pending_truth_defers_then_confirms_without_double_energy() -> None:
    from collections import defaultdict
    from types import SimpleNamespace

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.managers.state_reducer import (
        apply_state_update,
    )
    from custom_components.circuitsetup_energy_analyzer.models import (
        ApplianceProfile,
        CircuitConfig,
        CircuitMode,
    )
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.normalize import (
        NormalizedCircuitSample,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData

    start = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)

    class ConfirmingDetector:
        min_delta_w = 20.0
        noise_spread_w = 0.0
        calls = 0

        @property
        def has_pending_transition(self) -> bool:
            return self.calls == 1

        def process(self, _sample: object) -> list[NilmEdge]:
            self.calls += 1
            return (
                [NilmEdge(start, 80.0, 0.0, 80.0, 0.0, "on")]
                if self.calls == 2
                else []
            )

    state = AnalyzerState()
    future_previous = {
        "source_power_w": 0.0,
        "last_observed": (start + timedelta(seconds=5)).isoformat(),
        "energy_allocation_allowed": True,
    }
    state.nilm_reconciliation_by_circuit["mixed"] = future_previous
    state.nilm_component_runtime_by_circuit["mixed"] = {
        "pump": {
            "status": "off",
            "state_power_w": 0.0,
            "estimated_power_w": 0.0,
            "consistent": True,
            "last_observed": start.isoformat(),
            "energy_kwh": 0.0,
        }
    }
    store = FeatureStoreData(
        nilm_appliance_assignments_by_circuit={
            "mixed": [_reconciliation_assignment("pump", 80.0)]
        }
    )
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _id: 20.0,
        detectors={"mixed": ConfirmingDetector()},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _id, _events: (),
        observe_topology=lambda _config, _match, _context: [],
    )
    config = CircuitConfig("mixed", "Mixed", ApplianceProfile.MIXED, CircuitMode.MIXED)

    def process(offset: int) -> None:
        now = start + timedelta(seconds=offset)
        result = processor.process(
            NormalizedCircuitSample(
                timestamp=now,
                circuit_id="mixed",
                real_power=80.0,
                current=None,
                voltage=None,
                reactive_power=None,
                apparent_power=None,
                power_factor=None,
                frequency=None,
                energy=None,
            ),
            config,
            ProcessingContext(
                now=now,
                hass=SimpleNamespace(data={DOMAIN: {}}),
                state=state,
                store_data=store,
                options={},
                entry_data={},
                known_load_circuit_ids=frozenset(),
                sensitivity="balanced",
            ),
            events=(),
        )
        for update in result.state_updates:
            apply_state_update(state, update.path, update.value)

    process(0)
    assert state.nilm_reconciliation_by_circuit["mixed"] is future_previous
    process(10)
    pump = state.nilm_component_runtime_by_circuit["mixed"]["pump"]
    assert pump["status"] == "on"
    assert pump["session_start"] == start.isoformat()
    assert state.nilm_reconciliation_by_circuit["mixed"]["last_observed"] == (
        start + timedelta(seconds=10)
    ).isoformat()
    assert state.nilm_reconciliation_by_circuit["mixed"][
        "component_energy_kwh"
    ] == pytest.approx(80.0 * 10 / 3_600_000)
    process(20)
    reconciliation = state.nilm_reconciliation_by_circuit["mixed"]
    assert reconciliation["last_observed"] == (
        start + timedelta(seconds=20)
    ).isoformat()
    assert reconciliation["component_energy_kwh"] == pytest.approx(
        80.0 * 20 / 3_600_000
    )


def test_nilm_runtime_suspends_overallocation_without_fake_close() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    runtime = {"pump": {
        "status": "on", "state_power_w": 80.0, "estimated_power_w": 80.0,
        "session_id": "open", "session_start": now.isoformat(),
        "confidence": 0.9, "consistent": True,
        "last_observed": now.isoformat(), "energy_kwh": 0.0,
    }}

    runtime, reconciliation, completed, accepted = reconcile_component_runtime(
        source_power_w=10.0, timestamp=now + timedelta(seconds=10),
        assignments=[], runtime=runtime, edges=(), standby_w=0.0,
        noise_spread_w=0.0,
    )

    assert accepted == completed == []
    assert runtime["pump"]["status"] == "uncertain"
    assert runtime["pump"]["session_id"] == "open"
    assert reconciliation["conflict"] == "over_allocation"
    assert reconciliation["energy_allocation_allowed"] is False
    assert reconciliation["review_item"]["type"] == "model_conflict"


def test_nilm_sample_processor_preserves_delayed_overallocation_conflict() -> None:
    from collections import defaultdict
    from types import SimpleNamespace

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.managers.state_reducer import (
        apply_state_update,
    )
    from custom_components.circuitsetup_energy_analyzer.models import (
        ApplianceProfile,
        CircuitConfig,
        CircuitMode,
    )
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.normalize import (
        NormalizedCircuitSample,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData

    start = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)

    class DelayedDetector:
        min_delta_w = 20.0
        noise_spread_w = 0.0
        calls = 0

        @property
        def has_pending_transition(self) -> bool:
            return self.calls == 1

        def process(self, _sample: object) -> list[NilmEdge]:
            self.calls += 1
            return (
                [NilmEdge(start + timedelta(seconds=10), -40.0, 0.0, -40.0, 0.0, "off")]
                if self.calls == 2
                else []
            )

    state = AnalyzerState()
    state.nilm_component_runtime_by_circuit["mixed"] = {
        "pump": {
            "status": "on",
            "state_power_w": 80.0,
            "estimated_power_w": 80.0,
            "session_id": "open",
            "session_start": start.isoformat(),
            "confidence": 0.9,
            "consistent": True,
            "last_observed": start.isoformat(),
            "energy_kwh": 0.001,
        }
    }
    state.nilm_reconciliation_by_circuit["mixed"] = {
        "source_power_w": 80.0,
        "source_energy_kwh": 0.001,
        "component_energy_kwh": 0.001,
        "last_observed": start.isoformat(),
        "energy_allocation_allowed": True,
    }
    store = FeatureStoreData(
        nilm_appliance_assignments_by_circuit={
            "mixed": [_reconciliation_assignment("pump", 80.0)]
        }
    )
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _id: 20.0,
        detectors={"mixed": DelayedDetector()},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _id, _events: (),
        observe_topology=lambda _config, _match, _context: [],
    )
    config = CircuitConfig("mixed", "Mixed", ApplianceProfile.MIXED, CircuitMode.MIXED)

    energy_before_rejection = 0.0
    for offset in (10, 20):
        now = start + timedelta(seconds=offset)
        result = processor.process(
            NormalizedCircuitSample(
                timestamp=now,
                circuit_id="mixed",
                real_power=40.0,
                current=None,
                voltage=None,
                reactive_power=None,
                apparent_power=None,
                power_factor=None,
                frequency=None,
                energy=None,
            ),
            config,
            ProcessingContext(
                now=now,
                hass=SimpleNamespace(data={DOMAIN: {}}),
                state=state,
                store_data=store,
                options={},
                entry_data={},
                known_load_circuit_ids=frozenset(),
                sensitivity="balanced",
            ),
            events=(),
        )
        for update in result.state_updates:
            apply_state_update(state, update.path, update.value)
        if offset == 10:
            energy_before_rejection = state.nilm_reconciliation_by_circuit["mixed"][
                "component_energy_kwh"
            ]

    reconciliation = state.nilm_reconciliation_by_circuit["mixed"]
    assert reconciliation["conflict"] == "over_allocation"
    assert reconciliation["energy_allocation_allowed"] is False
    assert reconciliation["total_event_count"] == 1
    assert reconciliation["ambiguous_event_count"] == 0
    assert reconciliation["conservation_violations"] == 1
    assert reconciliation["component_energy_kwh"] == pytest.approx(
        energy_before_rejection
    )
    assert state.nilm_component_runtime_by_circuit["mixed"]["pump"]["status"] == (
        "uncertain"
    )
    assert processor.unmatched_edges_by_circuit["mixed"]


@pytest.mark.parametrize(
    ("candidate_watts", "expected_ambiguous"),
    [
        ((80.0, 80.0), 1),
        ((200.0,), 0),
    ],
)
def test_nilm_reconciliation_counts_only_equal_candidates_as_ambiguous(
    candidate_watts: tuple[float, ...], expected_ambiguous: int
) -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignments = [
        _reconciliation_assignment(f"load-{index}", watts)
        for index, watts in enumerate(candidate_watts)
    ]
    runtime = {
        str(assignment["assignment_id"]): {
            "status": "off",
            "state_power_w": 0.0,
            "estimated_power_w": 0.0,
            "consistent": True,
            "last_observed": now.isoformat(),
        }
        for assignment in assignments
    }

    _, reconciliation, _, accepted = reconcile_component_runtime(
        source_power_w=80.0,
        timestamp=now,
        assignments=assignments,
        runtime=runtime,
        edges=(NilmEdge(now, 80.0, 0.0, 80.0, 0.0, "on"),),
        standby_w=0.0,
        noise_spread_w=0.0,
    )

    assert accepted == []
    assert reconciliation["total_event_count"] == 1
    assert reconciliation["ambiguous_event_count"] == expected_ambiguous


def test_nilm_runtime_duration_breaks_equal_stop_tie_from_session_age() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    started_at = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    observed_at = started_at + timedelta(seconds=100)

    def assignment(assignment_id: str, p10: float, p90: float) -> dict[str, object]:
        return {
            **_reconciliation_assignment(assignment_id, 100.0),
            "run_profile": {"duration_s": {
                "effective_support": 5.0,
                "distinct_days": 3,
                "median_seconds": (p10 + p90) / 2,
                "p10_seconds": p10,
                "p90_seconds": p90,
            }},
            "transition_prototypes": [{
                "id": f"{assignment_id}-stop",
                "kind": "stop",
                "direction": "off",
                "from_state_id": "running",
                "to_state_id": "off",
                "from_state_w": 100.0,
                "to_state_w": 0.0,
                "delta_w": -100.0,
                "spread_w": 2.0,
                "sample_count": 3,
            }],
        }

    assignments = (
        assignment("on-time", 90.0, 110.0),
        assignment("too-long", 10.0, 20.0),
    )
    runtime = {
        assignment_id: {
            "status": "on",
            "state_power_w": 100.0,
            "estimated_power_w": 100.0,
            "session_id": f"{assignment_id}-session",
            "session_start": started_at.isoformat(),
            "consistent": True,
            "energy_kwh": 0.0,
        }
        for assignment_id in ("on-time", "too-long")
    }
    edge = NilmEdge(observed_at, -100.0, 0.0, -100.0, 0.0, "off")

    runtime, reconciliation, completed, accepted = reconcile_component_runtime(
        source_power_w=100.0,
        timestamp=observed_at,
        assignments=assignments,
        runtime=runtime,
        edges=(edge,),
        standby_w=0.0,
        noise_spread_w=0.0,
    )

    assert accepted == [edge]
    assert runtime["on-time"]["status"] == "off"
    assert runtime["too-long"]["status"] == "on"
    assert completed[0]["assignment_id"] == "on-time"
    assert reconciliation["ambiguous_event_count"] == 0
    assert reconciliation["duration_channel_available_count"] == 1
    assert reconciliation["duration_rank_impact_count"] == 1
    assert completed[0]["accepted_predictions"][-1].get(
        "duration_changed_winner"
    ) is True
    assert completed[0]["accepted_predictions"][-1].get(
        "duration_counterfactual_prototype_ids"
    ) == []
    assert reconciliation["score_decisions"] == [{
        "sequence": 1,
        "timestamp": observed_at.isoformat(),
        "accepted_prototype_ids": ["on-time:stop:running->off"],
        "duration_counterfactual_prototype_ids": [],
    }]


def test_nilm_runtime_records_duration_counterfactual_after_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A channel-caused rejection remains available to replay scoring."""
    from custom_components.circuitsetup_energy_analyzer.nilm import (
        NilmEdge,
        NilmReconciliationResult,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        nilm_sample,
    )

    started_at = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    observed_at = started_at + timedelta(seconds=100)
    assignment = {
        **_reconciliation_assignment("on-time", 100.0),
        "run_profile": {"duration_s": {
            "effective_support": 5.0,
            "distinct_days": 3,
            "median_seconds": 100.0,
            "p10_seconds": 90.0,
            "p90_seconds": 110.0,
        }},
        "transition_prototypes": [{
            "id": "on-time-stop",
            "kind": "stop",
            "direction": "off",
            "from_state_id": "running",
            "to_state_id": "off",
            "from_state_w": 100.0,
            "to_state_w": 0.0,
            "delta_w": -100.0,
            "spread_w": 2.0,
            "sample_count": 3,
        }],
    }

    def reconcile_with_duration_rejection(
        edge: NilmEdge,
        _models: object,
        _current: object,
        _helper_scores: object,
        duration_scores: object,
        _validation_scores: object,
        **_kwargs: object,
    ) -> NilmReconciliationResult:
        accepted = not bool(duration_scores)
        return NilmReconciliationResult(
            accepted=accepted,
            transitions=(),
            residual_w=0.0,
            tolerance_w=25.0,
            compound=False,
            consistent=True,
            energy_allocation_allowed=accepted,
            reason="accepted" if accepted else "low_confidence",
            accepted_prototype_ids=("on-time-stop",) if accepted else (),
        )

    monkeypatch.setattr(
        nilm_sample,
        "reconcile_nilm_edge",
        reconcile_with_duration_rejection,
    )
    runtime, reconciliation, completed, accepted = (
        nilm_sample.reconcile_component_runtime(
            source_power_w=100.0,
            timestamp=observed_at,
            assignments=(assignment,),
            runtime={
                "on-time": {
                    "status": "on",
                    "state_power_w": 100.0,
                    "estimated_power_w": 100.0,
                    "session_id": "on-time-session",
                    "session_start": started_at.isoformat(),
                    "consistent": True,
                    "energy_kwh": 0.0,
                }
            },
            edges=(NilmEdge(observed_at, -100.0, 0.0, -100.0, 0.0, "off"),),
            standby_w=0.0,
            noise_spread_w=0.0,
        )
    )

    assert accepted == []
    assert completed == []
    assert runtime["on-time"]["status"] == "on"
    assert reconciliation["score_decisions"] == [{
        "sequence": 1,
        "timestamp": observed_at.isoformat(),
        "accepted_prototype_ids": [],
        "duration_counterfactual_prototype_ids": ["on-time-stop"],
    }]


def test_nilm_runtime_duration_keeps_assignment_local_prototype_scores() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    started_at = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    observed_at = started_at + timedelta(seconds=100)

    def assignment(assignment_id: str, p10: float, p90: float) -> dict[str, object]:
        return {
            **_reconciliation_assignment(assignment_id, 100.0),
            "run_profile": {"duration_s": {
                "effective_support": 5.0,
                "distinct_days": 3,
                "median_seconds": (p10 + p90) / 2,
                "p10_seconds": p10,
                "p90_seconds": p90,
            }},
        }

    assignments = (
        assignment("on-time", 90.0, 110.0),
        assignment("too-long", 10.0, 20.0),
    )
    runtime = {
        assignment_id: {
            "status": "on",
            "state_power_w": 100.0,
            "estimated_power_w": 100.0,
            "session_id": f"{assignment_id}-session",
            "session_start": started_at.isoformat(),
            "consistent": True,
            "energy_kwh": 0.0,
        }
        for assignment_id in ("on-time", "too-long")
    }
    edge = NilmEdge(observed_at, -100.0, 0.0, -100.0, 0.0, "off")

    runtime, _, completed, accepted = reconcile_component_runtime(
        source_power_w=100.0,
        timestamp=observed_at,
        assignments=assignments,
        runtime=runtime,
        edges=(edge,),
        standby_w=0.0,
        noise_spread_w=0.0,
    )

    assert accepted == [edge]
    assert runtime["on-time"]["status"] == "off"
    assert runtime["too-long"]["status"] == "on"
    assert completed[0]["assignment_id"] == "on-time"


def test_nilm_runtime_validation_breaks_equal_tie_for_current_revision() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)

    def assignment(assignment_id: str, outcome: str) -> dict[str, object]:
        return {
            **_reconciliation_assignment(assignment_id, 100.0),
            "model_revision": 7,
            "model_fingerprint": f"{assignment_id}-model-seven",
            "validation_schema_version": 2,
            "validation_method": "one_to_one_iou",
            "validation_outcomes": [
                {
                    "outcome_id": f"{assignment_id}-{index}",
                    "source": "ground_truth",
                    "outcome": outcome,
                    "timestamp": (now - timedelta(days=index % 3)).isoformat(),
                    "model_revision": 7,
                    "model_fingerprint": f"{assignment_id}-model-seven",
                }
                for index in range(200)
            ],
            "transition_prototypes": [{
                "id": f"{assignment_id}-start",
                "kind": "start",
                "direction": "on",
                "from_state_id": "off",
                "to_state_id": "running",
                "from_state_w": 0.0,
                "to_state_w": 100.0,
                "delta_w": 100.0,
                "spread_w": 2.0,
                "sample_count": 3,
            }],
        }

    assignments = (
        assignment("reliable", "correct"),
        assignment("unreliable", "wrong"),
    )
    runtime = {
        assignment_id: {
            "status": "off",
            "state_power_w": 0.0,
            "estimated_power_w": 0.0,
            "consistent": True,
            "energy_kwh": 0.0,
        }
        for assignment_id in ("reliable", "unreliable")
    }
    edge = NilmEdge(now, 100.0, 0.0, 100.0, 0.0, "on")

    runtime, reconciliation, _, accepted = reconcile_component_runtime(
        source_power_w=100.0,
        timestamp=now,
        assignments=assignments,
        runtime=runtime,
        edges=(edge,),
        standby_w=0.0,
        noise_spread_w=0.0,
    )

    assert accepted == [edge]
    assert runtime["reliable"]["status"] == "on"
    assert runtime["unreliable"]["status"] == "off"
    assert reconciliation["ambiguous_event_count"] == 0
    assert reconciliation["validation_channel_available_count"] == 1
    assert reconciliation["validation_rank_impact_count"] == 1
    assert runtime["reliable"]["accepted_predictions"][-1].get(
        "validation_changed_winner"
    ) is True
    assert runtime["reliable"]["accepted_predictions"][-1].get(
        "validation_counterfactual_prototype_ids"
    ) == []


def test_nilm_runtime_uses_revision_matched_explicit_feedback_scores() -> None:
    """Dropping persisted feedback from runtime profile construction must fail."""
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)

    def assignment(
        assignment_id: str,
        outcome: str,
        helper_id: str,
        helper_confidence: float,
    ) -> dict[str, object]:
        return {
            **_reconciliation_assignment(assignment_id, 100.0),
            "model_revision": 7,
            "model_fingerprint": f"{assignment_id}-model-seven",
            "validation_outcomes": [
                {
                    "outcome_id": f"{assignment_id}-{index}",
                    "source": "explicit_feedback",
                    "outcome": outcome,
                    "timestamp": (now - timedelta(days=index % 3)).isoformat(),
                    "model_revision": 7,
                    "model_fingerprint": f"{assignment_id}-model-seven",
                }
                for index in range(5)
            ],
            "helper_links": [{
                "helper_circuit_id": helper_id,
                "relationship": "corroborates",
                "status": "confirmed",
                "confidence": helper_confidence,
                "start_lag_seconds": 0.0,
                "start_lag_mad_seconds": 0.0,
            }],
        }

    assignments = (
        assignment("reliable", "correct", "helper-reliable", 0.7),
        assignment("unreliable", "wrong", "helper-unreliable", 0.3),
    )
    runtime = {
        assignment_id: {
            "status": "off",
            "state_power_w": 0.0,
            "estimated_power_w": 0.0,
            "consistent": True,
            "energy_kwh": 0.0,
        }
        for assignment_id in ("reliable", "unreliable")
    }
    helper_events = (
        CircuitEvent(now, "helper-reliable", EventType.START, features={}),
        CircuitEvent(now, "helper-unreliable", EventType.START, features={}),
    )
    edge = NilmEdge(now, 100.0, 0.0, 100.0, 0.0, "on")

    runtime, reconciliation, _, accepted = reconcile_component_runtime(
        source_power_w=100.0,
        timestamp=now,
        assignments=assignments,
        runtime=runtime,
        edges=(edge,),
        standby_w=0.0,
        noise_spread_w=0.0,
        helper_events=helper_events,
        available_helper_ids={"helper-reliable", "helper-unreliable"},
    )

    assert accepted == [edge]
    assert runtime["reliable"]["status"] == "on"
    assert runtime["unreliable"]["status"] == "off"
    assert reconciliation["validation_channel_available_count"] == 1
    assert reconciliation["validation_rank_impact_count"] == 1


def test_nilm_runtime_diagnostics_ignore_unrelated_validation_scores() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    candidate = _reconciliation_assignment("candidate", 100.0)
    unrelated = {
        **_reconciliation_assignment("unrelated", 300.0),
        "model_revision": 7,
        "validation_schema_version": 2,
        "validation_method": "one_to_one_iou",
        "validation_outcomes": [
            {
                "outcome_id": f"unrelated-{index}",
                "source": "ground_truth",
                "outcome": "correct",
                "timestamp": (now - timedelta(days=index % 3)).isoformat(),
                "model_revision": 7,
            }
            for index in range(5)
        ],
    }
    runtime = {
        assignment_id: {
            "status": "off", "state_power_w": 0.0,
            "estimated_power_w": 0.0, "consistent": True,
        }
        for assignment_id in ("candidate", "unrelated")
    }

    _, reconciliation, _, _ = reconcile_component_runtime(
        source_power_w=100.0, timestamp=now,
        assignments=(candidate, unrelated), runtime=runtime,
        edges=(NilmEdge(now, 100.0, 0.0, 100.0, 0.0, "on"),),
        standby_w=0.0, noise_spread_w=0.0,
    )

    assert reconciliation["validation_channel_available_count"] == 0
    assert reconciliation["evidence_unavailable_reason_counts"] == {
        "insufficient_validation_support": 1,
        "duration_unsupported_transition": 1,
    }


def test_nilm_runtime_ambiguity_ignores_unrelated_helper_score() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignments = (
        _reconciliation_assignment("first", 100.0),
        _reconciliation_assignment("second", 100.0),
        {
            **_reconciliation_assignment("unrelated", 300.0),
            "helper_links": [{
                "helper_circuit_id": "helper",
                "relationship": "corroborates",
                "status": "confirmed",
                "confidence": 1.0,
                "start_lag_seconds": 0.0,
                "start_lag_mad_seconds": 0.0,
            }],
        },
    )
    runtime = {
        assignment_id: {
            "status": "off", "state_power_w": 0.0,
            "estimated_power_w": 0.0, "consistent": True,
        }
        for assignment_id in ("first", "second", "unrelated")
    }

    _, reconciliation, _, accepted = reconcile_component_runtime(
        source_power_w=100.0, timestamp=now, assignments=assignments,
        runtime=runtime,
        edges=(NilmEdge(now, 100.0, 0.0, 100.0, 0.0, "on"),),
        standby_w=0.0, noise_spread_w=0.0,
        helper_events=(CircuitEvent(now, "helper", EventType.START, features={}),),
        available_helper_ids={"helper"},
    )

    assert accepted == []
    assert reconciliation["ambiguous_with_secondary_evidence_count"] == 0
    assert reconciliation["ambiguous_without_secondary_evidence_count"] == 1


@pytest.mark.parametrize(
    ("validation_fields", "expected_reason"),
    [
        ({"validation_method": "overlap"}, "legacy_validation_method"),
        (
            {
                "model_revision": 7,
                "validation_schema_version": 2,
                "validation_method": "one_to_one_iou",
                "validation_outcomes": [{
                    "outcome_id": "sparse", "source": "ground_truth",
                    "outcome": "correct", "timestamp": "2026-06-11T12:00:00+00:00",
                    "model_revision": 7,
                }],
            },
            "insufficient_validation_support",
        ),
        (
            {
                "model_revision": 7,
                "validation_schema_version": 2,
                "validation_method": "one_to_one_iou",
                "validation_outcomes": [
                    {
                        "outcome_id": f"mismatch-{index}",
                        "source": "ground_truth", "outcome": "correct",
                        "timestamp": f"2026-06-{11 + index % 3:02d}T12:00:00+00:00",
                        "model_revision": 6,
                    }
                    for index in range(5)
                ],
            },
            "validation_revision_mismatch",
        ),
        (
            {
                "model_fingerprint": "current-model",
                "validation_schema_version": 2,
                "validation_method": "one_to_one_iou",
                "validation_outcomes": [{
                    "outcome_id": "fingerprint-mismatch",
                    "source": "ground_truth", "outcome": "correct",
                    "timestamp": "2026-06-11T12:00:00+00:00",
                    "model_fingerprint": "old-model",
                }],
            },
            "validation_revision_mismatch",
        ),
    ],
)
def test_nilm_runtime_diagnostics_distinguish_validation_unavailability(
    validation_fields: dict[str, object], expected_reason: str
) -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignment = {
        **_reconciliation_assignment("load", 100.0),
        **validation_fields,
    }
    _, reconciliation, _, _ = reconcile_component_runtime(
        source_power_w=100.0, timestamp=now, assignments=(assignment,),
        runtime={"load": {
            "status": "off", "state_power_w": 0.0,
            "estimated_power_w": 0.0, "consistent": True,
        }},
        edges=(NilmEdge(now, 100.0, 0.0, 100.0, 0.0, "on"),),
        standby_w=0.0, noise_spread_w=0.0,
    )

    assert reconciliation["evidence_unavailable_reason_counts"][expected_reason] == 1


def test_nilm_runtime_persists_bounded_prediction_provenance_on_completion() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    started_at = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    stopped_at = started_at + timedelta(minutes=5)
    assignment = {
        **_reconciliation_assignment("dryer", 100.0),
        "model_schema_version": 2,
        "model_revision": 7,
        "model_fingerprint": "dryer-model-seven",
        "transition_prototypes": [
            {
                "id": "dryer-start-v7",
                "kind": "start",
                "direction": "on",
                "from_state_id": "off",
                "to_state_id": "running",
                "from_state_w": 0.0,
                "to_state_w": 100.0,
                "delta_w": 100.0,
                "spread_w": 2.0,
                "sample_count": 3,
            },
            {
                "id": "dryer-stop-v7",
                "kind": "stop",
                "direction": "off",
                "from_state_id": "running",
                "to_state_id": "off",
                "from_state_w": 100.0,
                "to_state_w": 0.0,
                "delta_w": -100.0,
                "spread_w": 2.0,
                "sample_count": 3,
            },
        ],
    }
    runtime = {
        "dryer": {
            "status": "off",
            "state_power_w": 0.0,
            "estimated_power_w": 0.0,
            "consistent": True,
            "energy_kwh": 0.0,
        }
    }

    runtime, first, _, _ = reconcile_component_runtime(
        source_power_w=100.0,
        timestamp=started_at,
        assignments=(assignment,),
        runtime=runtime,
        edges=(NilmEdge(started_at, 100.0, 0.0, 100.0, 0.0, "on"),),
        standby_w=0.0,
        noise_spread_w=0.0,
    )

    assert runtime["dryer"]["current_state_id"] == "running"
    assert runtime["dryer"]["state_since"] == started_at.isoformat()
    assert runtime["dryer"]["start_prediction"]["prototype_id"] == (
        "dryer:start:off->running"
    )
    assert runtime["dryer"]["accepted_predictions"][0] == {
        "prediction_timestamp": started_at.isoformat(),
        "model_schema_version": 2,
        "model_revision": 7,
        "model_fingerprint": "dryer-model-seven",
        "prototype_id": "dryer:start:off->running",
        "transition_kind": "start",
        "candidate_score": 1.0,
        "winner_margin": None,
        "channel_breakdown": {
            "electrical": 1.0,
            "helper": None,
            "duration": None,
            "validation": None,
        },
        "unavailable_channels": ["helper", "duration", "validation"],
        "state_id": "running",
        "state_power_w": 100.0,
    }

    runtime, _, completed, _ = reconcile_component_runtime(
        source_power_w=0.0,
        timestamp=stopped_at,
        assignments=(assignment,),
        runtime=runtime,
        edges=(NilmEdge(stopped_at, -100.0, 0.0, -100.0, 0.0, "off"),),
        standby_w=0.0,
        noise_spread_w=0.0,
        previous_reconciliation=first,
    )

    session = completed[0]
    assert session["start_prototype_id"] == "dryer:start:off->running"
    assert session["stop_prototype_id"] == "dryer:stop:running->off"
    assert session["start_model_revision"] == session["stop_model_revision"] == 7
    assert [item["state_id"] for item in session["state_path"]] == ["running"]
    assert [item["prototype_id"] for item in session["accepted_predictions"]] == [
        "dryer:start:off->running",
        "dryer:stop:running->off",
    ]
    assert runtime["dryer"]["last_stop"] == stopped_at.isoformat()
    assert runtime["dryer"]["state_path"] == []
    assert runtime["dryer"]["accepted_predictions"] == []


def test_nilm_runtime_stop_then_start_keeps_each_session_provenance() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    old_start = datetime(2026, 6, 11, 11, 0, tzinfo=UTC)
    stop_at = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    restart_at = stop_at + timedelta(seconds=10)
    assignment = {
        **_reconciliation_assignment("dryer", 100.0),
        "model_revision": 7,
        "model_fingerprint": "dryer-model-seven",
        "transition_prototypes": [
            {
                "id": "dryer-start-v7", "kind": "start", "direction": "on",
                "from_state_id": "off", "to_state_id": "running",
                "from_state_w": 0.0, "to_state_w": 100.0,
                "delta_w": 100.0, "spread_w": 2.0, "sample_count": 3,
            },
            {
                "id": "dryer-stop-v7", "kind": "stop", "direction": "off",
                "from_state_id": "running", "to_state_id": "off",
                "from_state_w": 100.0, "to_state_w": 0.0,
                "delta_w": -100.0, "spread_w": 2.0, "sample_count": 3,
            },
        ],
    }
    old_prediction = {
        "prediction_timestamp": old_start.isoformat(),
        "model_schema_version": 2,
        "model_revision": 6,
        "model_fingerprint": "dryer-model-six",
        "prototype_id": "dryer-start-v6",
        "transition_kind": "start",
        "candidate_score": 0.9,
        "winner_margin": None,
        "channel_breakdown": {},
        "unavailable_channels": [],
        "state_id": "running",
        "state_power_w": 100.0,
    }
    runtime = {
        "dryer": {
            "status": "on", "state_power_w": 100.0,
            "estimated_power_w": 100.0, "session_id": "old-session",
            "session_start": old_start.isoformat(), "energy_kwh": 0.01,
            "consistent": True, "start_prediction": old_prediction,
            "accepted_predictions": [old_prediction],
            "state_path": [{"state_id": "running"}],
        }
    }

    runtime, _, completed, accepted = reconcile_component_runtime(
        source_power_w=100.0,
        timestamp=restart_at,
        assignments=(assignment,),
        runtime=runtime,
        edges=(
            NilmEdge(stop_at, -100.0, 0.0, -100.0, 0.0, "off"),
            NilmEdge(restart_at, 100.0, 0.0, 100.0, 0.0, "on"),
        ),
        standby_w=0.0,
        noise_spread_w=0.0,
    )

    assert len(accepted) == 2
    assert completed[0]["session_id"] == "old-session"
    assert completed[0]["start"] == old_start.isoformat()
    assert completed[0]["start_prototype_id"] == "dryer-start-v6"
    assert completed[0]["stop_prototype_id"] == "dryer:stop:running->off"
    assert runtime["dryer"]["status"] == "on"
    assert runtime["dryer"]["session_start"] == restart_at.isoformat()
    assert runtime["dryer"]["start_prediction"]["prototype_id"] == (
        "dryer:start:off->running"
    )


def test_nilm_runtime_keeps_one_session_through_active_state_changes() -> None:
    """A state-down transition must not close a multi-state NILM session."""
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    started_at = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    raised_at = started_at + timedelta(minutes=1)
    lowered_at = raised_at + timedelta(minutes=1)
    stopped_at = lowered_at + timedelta(minutes=1)
    assignment = {
        "assignment_id": "dryer",
        "lifecycle_state": "validated",
        "model_confidence": 0.9,
        "power_states_w": [0.0, 100.0, 200.0],
        "states": [
            {"id": "off", "kind": "off", "power_w": 0.0, "spread_w": 0.0},
            {"id": "active_1", "kind": "active", "power_w": 100.0, "spread_w": 2.0},
            {"id": "active_2", "kind": "active", "power_w": 200.0, "spread_w": 2.0},
        ],
        "transition_prototypes": [
            {"id": "dryer-start", "kind": "start", "direction": "on",
             "from_state_id": "off", "to_state_id": "active_1",
             "from_state_w": 0.0, "to_state_w": 100.0,
             "delta_w": 100.0, "spread_w": 2.0, "sample_count": 4},
            {"id": "dryer-up", "kind": "state_up", "direction": "on",
             "from_state_id": "active_1", "to_state_id": "active_2",
             "from_state_w": 100.0, "to_state_w": 200.0,
             "delta_w": 100.0, "spread_w": 2.0, "sample_count": 4},
            {"id": "dryer-down", "kind": "state_down", "direction": "off",
             "from_state_id": "active_2", "to_state_id": "active_1",
             "from_state_w": 200.0, "to_state_w": 100.0,
             "delta_w": -100.0, "spread_w": 2.0, "sample_count": 4},
            {"id": "dryer-stop", "kind": "stop", "direction": "off",
             "from_state_id": "active_1", "to_state_id": "off",
             "from_state_w": 100.0, "to_state_w": 0.0,
             "delta_w": -100.0, "spread_w": 2.0, "sample_count": 4},
        ],
    }
    runtime: dict[str, dict[str, object]] = {
        "dryer": {
            "status": "off", "state_power_w": 0.0,
            "estimated_power_w": 0.0, "consistent": True,
        }
    }
    previous = None
    completed: list[dict[str, object]] = []
    for timestamp, source_power_w, delta_w, direction in (
        (started_at, 100.0, 100.0, "on"),
        (raised_at, 200.0, 100.0, "on"),
        (lowered_at, 100.0, -100.0, "off"),
        (stopped_at, 0.0, -100.0, "off"),
    ):
        runtime, previous, completed, accepted = reconcile_component_runtime(
            source_power_w=source_power_w,
            timestamp=timestamp,
            assignments=(assignment,),
            runtime=runtime,
            edges=(NilmEdge(timestamp, delta_w, 0.0, delta_w, 0.0, direction),),
            standby_w=0.0,
            noise_spread_w=0.0,
            previous_reconciliation=previous,
        )
        assert accepted

    assert len(completed) == 1
    session = completed[0]
    assert session["on_delta_w"] == 100.0
    assert session["off_delta_w"] == -100.0
    assert [item["state_id"] for item in session["state_path"]] == [
        "active_1", "active_2", "active_1",
    ]
    assert [item["started_at"] for item in session["state_path"]] == [
        started_at.isoformat(), raised_at.isoformat(), lowered_at.isoformat(),
    ]
    assert [item["power_w"] for item in session["state_path"]] == [
        100.0, 200.0, 100.0,
    ]
    assert session["state_dwell_seconds"] == {
        "active_1": 120.0,
        "active_2": 60.0,
    }
    assert session["time_weighted_mean_power_w"] == pytest.approx(133.333)
    assert session["time_weighted_median_power_w"] == 100.0


def test_nilm_runtime_rejects_transition_from_a_different_active_state_id() -> None:
    """Equal state power alone cannot authorize an incompatible state transition."""
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignment = {
        "assignment_id": "load",
        "lifecycle_state": "validated",
        "model_confidence": 0.9,
        "power_states_w": [0.0, 100.0],
        "states": [
            {"id": "off", "kind": "off", "power_w": 0.0, "spread_w": 0.0},
            {"id": "active_1", "kind": "active", "power_w": 100.0, "spread_w": 1.0},
            {"id": "active_2", "kind": "active", "power_w": 100.0, "spread_w": 1.0},
        ],
        "transition_prototypes": [
            {"id": "load-stop-active-2", "kind": "stop", "direction": "off",
             "from_state_id": "active_2", "to_state_id": "off",
             "from_state_w": 100.0, "to_state_w": 0.0,
             "delta_w": -100.0, "spread_w": 2.0, "sample_count": 4},
        ],
    }
    runtime, _, completed, accepted = reconcile_component_runtime(
        source_power_w=0.0,
        timestamp=now,
        assignments=(assignment,),
        runtime={
            "load": {
                "status": "on", "state_power_w": 100.0,
                "current_state_id": "active_1", "estimated_power_w": 100.0,
                "session_id": "load|open", "session_start": now.isoformat(),
                "consistent": True,
            }
        },
        edges=(NilmEdge(now, -100.0, 0.0, -100.0, 0.0, "off"),),
        standby_w=0.0,
        noise_spread_w=0.0,
    )

    assert accepted == []
    assert completed == []


def test_nilm_runtime_retired_assignment_can_only_return_to_off() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignment = {
        "assignment_id": "load",
        "lifecycle_state": "retired",
        "model_confidence": 0.9,
        "power_states_w": [0.0, 100.0, 200.0],
        "states": [
            {"id": "off", "kind": "off", "power_w": 0.0, "spread_w": 0.0},
            {"id": "active_1", "kind": "active", "power_w": 100.0, "spread_w": 1.0},
            {"id": "active_2", "kind": "active", "power_w": 200.0, "spread_w": 1.0},
        ],
        "transition_prototypes": [
            {"id": "load-state-down", "kind": "state_down", "direction": "off",
             "from_state_id": "active_2", "to_state_id": "active_1",
             "from_state_w": 200.0, "to_state_w": 100.0,
             "delta_w": -100.0, "spread_w": 2.0, "sample_count": 4},
            {"id": "load-stop", "kind": "stop", "direction": "off",
             "from_state_id": "active_2", "to_state_id": "off",
             "from_state_w": 200.0, "to_state_w": 0.0,
             "delta_w": -200.0, "spread_w": 2.0, "sample_count": 4},
        ],
    }
    runtime, _, completed, accepted = reconcile_component_runtime(
        source_power_w=200.0,
        timestamp=now,
        assignments=(assignment,),
        runtime={
            "load": {
                "status": "on", "state_power_w": 200.0,
                "current_state_id": "active_2", "estimated_power_w": 200.0,
                "session_id": "load|open", "session_start": now.isoformat(),
                "consistent": True,
            }
        },
        edges=(NilmEdge(now, -100.0, 0.0, -100.0, 0.0, "off"),),
        standby_w=0.0,
        noise_spread_w=0.0,
    )

    assert accepted == []
    assert completed == []
    assert runtime["load"]["current_state_id"] == "active_2"

    _, _, completed, accepted = reconcile_component_runtime(
        source_power_w=0.0,
        timestamp=now + timedelta(minutes=1),
        assignments=(assignment,),
        runtime=runtime,
        edges=(
            NilmEdge(
                now + timedelta(minutes=1), -200.0, 0.0, -200.0, 0.0, "off"
            ),
        ),
        standby_w=0.0,
        noise_spread_w=0.0,
    )

    assert len(accepted) == 1
    assert len(completed) == 1


def test_nilm_runtime_bootstraps_reviewable_active_state_path_from_observed_edge() -> (
    None
):
    """A reviewed session can seed real active transitions before a prototype exists."""
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    started_at = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignment = {
        "assignment_id": "dryer",
        "lifecycle_state": "validated",
        "model_confidence": 0.9,
        "power_states_w": [0.0, 100.0, 200.0],
        "states": [
            {"id": "off", "kind": "off", "power_w": 0.0, "spread_w": 0.0},
            {"id": "active_1", "kind": "active", "power_w": 100.0, "spread_w": 2.0},
            {"id": "active_2", "kind": "active", "power_w": 200.0, "spread_w": 2.0},
        ],
        "transition_prototypes": [
            {"kind": "start", "direction": "on", "from_state_id": "off",
             "to_state_id": "active_1", "from_state_w": 0.0,
             "to_state_w": 100.0, "delta_w": 100.0, "spread_w": 2.0,
             "sample_count": 4},
            {"kind": "stop", "direction": "off", "from_state_id": "active_2",
             "to_state_id": "off", "from_state_w": 200.0,
             "to_state_w": 0.0, "delta_w": -200.0, "spread_w": 2.0,
             "sample_count": 4},
        ],
    }
    runtime: dict[str, dict[str, object]] = {
        "dryer": {"status": "off", "state_power_w": 0.0,
                  "estimated_power_w": 0.0, "consistent": True}
    }

    runtime, previous, _, accepted = reconcile_component_runtime(
        source_power_w=100.0,
        timestamp=started_at,
        assignments=(assignment,),
        runtime=runtime,
        edges=(NilmEdge(started_at, 100.0, 0.0, 100.0, 0.0, "on"),),
        standby_w=0.0,
        noise_spread_w=0.0,
    )
    assert accepted

    raised_at = started_at + timedelta(minutes=1)
    runtime, previous, _, accepted = reconcile_component_runtime(
        source_power_w=200.0,
        timestamp=raised_at,
        assignments=(assignment,),
        runtime=runtime,
        edges=(NilmEdge(raised_at, 100.0, 0.0, 100.0, 0.0, "on"),),
        standby_w=0.0,
        noise_spread_w=0.0,
        previous_reconciliation=previous,
    )
    assert accepted == []
    assert runtime["dryer"]["current_state_id"] == "active_2"

    stopped_at = started_at + timedelta(minutes=2)
    _, _, completed, accepted = reconcile_component_runtime(
        source_power_w=0.0,
        timestamp=stopped_at,
        assignments=(assignment,),
        runtime=runtime,
        edges=(NilmEdge(stopped_at, -200.0, 0.0, -200.0, 0.0, "off"),),
        standby_w=0.0,
        noise_spread_w=0.0,
        previous_reconciliation=previous,
    )

    assert accepted
    assert [item["state_id"] for item in completed[0]["state_path"]] == [
        "active_1", "active_2"
    ]


def test_nilm_runtime_keeps_full_dwell_summary_when_state_path_is_bounded() -> None:
    """Path compaction must not discard earlier state dwell from a long session."""
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    started_at = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignment = {
        "assignment_id": "dryer",
        "lifecycle_state": "validated",
        "model_confidence": 0.9,
        "power_states_w": [0.0, 100.0, 200.0],
        "states": [
            {"id": "off", "kind": "off", "power_w": 0.0, "spread_w": 0.0},
            {"id": "active_1", "kind": "active", "power_w": 100.0, "spread_w": 2.0},
            {"id": "active_2", "kind": "active", "power_w": 200.0, "spread_w": 2.0},
        ],
        "transition_prototypes": [
            {"kind": "start", "direction": "on", "from_state_id": "off",
             "to_state_id": "active_1", "from_state_w": 0.0,
             "to_state_w": 100.0, "delta_w": 100.0, "spread_w": 2.0,
             "sample_count": 4},
            {"kind": "state_up", "direction": "on", "from_state_id": "active_1",
             "to_state_id": "active_2", "from_state_w": 100.0,
             "to_state_w": 200.0, "delta_w": 100.0, "spread_w": 2.0,
             "sample_count": 4},
            {"kind": "state_down", "direction": "off", "from_state_id": "active_2",
             "to_state_id": "active_1", "from_state_w": 200.0,
             "to_state_w": 100.0, "delta_w": -100.0, "spread_w": 2.0,
             "sample_count": 4},
            {"kind": "stop", "direction": "off", "from_state_id": "active_2",
             "to_state_id": "off", "from_state_w": 200.0,
             "to_state_w": 0.0, "delta_w": -200.0, "spread_w": 2.0,
             "sample_count": 4},
        ],
    }
    runtime: dict[str, dict[str, object]] = {
        "dryer": {"status": "off", "state_power_w": 0.0,
                  "estimated_power_w": 0.0, "consistent": True}
    }
    previous = None
    for minute in range(14):
        timestamp = started_at + timedelta(minutes=minute)
        if minute == 0:
            delta_w, source_power_w, direction = 100.0, 100.0, "on"
        elif minute % 2:
            delta_w, source_power_w, direction = 100.0, 200.0, "on"
        else:
            delta_w, source_power_w, direction = -100.0, 100.0, "off"
        runtime, previous, _, accepted = reconcile_component_runtime(
            source_power_w=source_power_w,
            timestamp=timestamp,
            assignments=(assignment,),
            runtime=runtime,
            edges=(NilmEdge(timestamp, delta_w, 0.0, delta_w, 0.0, direction),),
            standby_w=0.0,
            noise_spread_w=0.0,
            previous_reconciliation=previous,
        )
        assert accepted

    stopped_at = started_at + timedelta(minutes=14)
    runtime, _, completed, accepted = reconcile_component_runtime(
        source_power_w=0.0,
        timestamp=stopped_at,
        assignments=(assignment,),
        runtime=runtime,
        edges=(NilmEdge(stopped_at, -200.0, 0.0, -200.0, 0.0, "off"),),
        standby_w=0.0,
        noise_spread_w=0.0,
        previous_reconciliation=previous,
    )

    assert accepted
    assert len(completed) == 1
    assert len(completed[0]["state_path"]) == 12
    assert completed[0]["state_dwell_seconds"] == {
        "active_1": 420.0,
        "active_2": 420.0,
    }
    assert completed[0]["time_weighted_mean_power_w"] == 150.0


def test_nilm_source_unavailable_preserves_metrics_and_counts_input_edge() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    _, reconciliation, _, _ = reconcile_component_runtime(
        source_power_w=None,
        timestamp=now,
        assignments=(),
        runtime={},
        edges=(NilmEdge(now, 80.0, 0.0, 80.0, 0.0, "on"),),
        standby_w=0.0,
        noise_spread_w=0.0,
        previous_reconciliation={
            "source_energy_kwh": 0.02,
            "component_energy_kwh": 0.01,
            "residual_energy_kwh": 0.01,
            "total_event_count": 2,
            "ambiguous_event_count": 1,
            "conservation_violations": 1,
        },
    )

    assert reconciliation["source_energy_kwh"] == 0.02
    assert reconciliation["component_energy_kwh"] == 0.01
    assert reconciliation["residual_energy_kwh"] == 0.01
    assert reconciliation["total_event_count"] == 3
    assert reconciliation["ambiguous_event_count"] == 1
    assert reconciliation["conservation_violations"] == 1


def test_nilm_reconciliation_ignores_malformed_prior_counters() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    _, reconciliation, _, _ = reconcile_component_runtime(
        source_power_w=0.0,
        timestamp=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
        assignments=(),
        runtime={},
        edges=(),
        standby_w=0.0,
        noise_spread_w=0.0,
        previous_reconciliation={
            "total_event_count": "bad",
            "ambiguous_event_count": {},
            "conservation_violations": float("nan"),
        },
    )

    assert reconciliation["total_event_count"] == 0
    assert reconciliation["ambiguous_event_count"] == 0
    assert reconciliation["conservation_violations"] == 0


def test_nilm_runtime_keeps_helper_conflict_unknown() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignments = [
        {
            "assignment_id": assignment_id,
            "lifecycle_state": "validated",
            "power_states_w": [0.0, 100.0],
            "transition_prototypes": [{
                "direction": "on", "from_state_w": 0.0, "to_state_w": 100.0,
                "delta_w": 100.0, "spread_w": 2.0, "sample_count": 3,
            }],
            "model_confidence": 0.9,
                "helper_links": [{
                    "helper_circuit_id": "helper", "relationship": "corroborates",
                    "status": "confirmed", "confidence": 0.9,
                    "start_lag_seconds": 0.0,
                    "start_lag_mad_seconds": 0.0,
                }],
        }
        for assignment_id in ("first", "second")
    ]
    runtime = {
        key: {"status": "off", "state_power_w": 0.0,
              "estimated_power_w": 0.0, "consistent": True,
              "last_observed": now.isoformat()}
        for key in ("first", "second")
    }
    edge = NilmEdge(now, 100.0, 0.0, 100.0, 0.0, "on")
    helper_event = CircuitEvent(now, "helper", EventType.START, features={})

    runtime, reconciliation, completed, accepted = reconcile_component_runtime(
        source_power_w=100.0, timestamp=now, assignments=assignments,
        runtime=runtime, edges=(edge,), standby_w=0.0, noise_spread_w=0.0,
        helper_events=(helper_event,),
        available_helper_ids={"helper"},
    )

    assert accepted == completed == []
    assert all(item["status"] == "off" for item in runtime.values())
    assert reconciliation["conflict"] == "helper_conflict"


def test_nilm_helper_conflict_ignores_illegal_assignment_state() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignments = [
        {
            **_reconciliation_assignment(assignment_id, 100.0),
            "helper_links": [{
                "helper_circuit_id": "helper", "relationship": "corroborates",
                "status": "confirmed", "confidence": 0.9,
                "start_lag_seconds": 0.0, "start_lag_mad_seconds": 0.0,
            }],
        }
        for assignment_id in ("first", "second")
    ]
    runtime = {
        "first": {"status": "off", "state_power_w": 0.0,
                  "estimated_power_w": 0.0, "consistent": True},
        "second": {"status": "on", "state_power_w": 100.0,
                   "estimated_power_w": 100.0, "consistent": True},
    }
    edge = NilmEdge(now, 100.0, 0.0, 100.0, 0.0, "on")

    runtime, reconciliation, _, accepted = reconcile_component_runtime(
        source_power_w=200.0, timestamp=now, assignments=assignments,
        runtime=runtime, edges=(edge,), standby_w=0.0, noise_spread_w=0.0,
        helper_events=(CircuitEvent(
            now, "helper", EventType.START, features={}
        ),),
        available_helper_ids={"helper"},
    )

    assert accepted == [edge]
    assert reconciliation["conflict"] is None
    assert all(item["status"] == "on" for item in runtime.values())


def test_nilm_helper_conflict_ignores_nonmatching_shared_link() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    first = {
        **_reconciliation_assignment("first", 100.0),
        "helper_links": [{
            "helper_circuit_id": "shared", "relationship": "corroborates",
            "status": "confirmed", "confidence": 0.9,
            "start_lag_seconds": 0.0, "start_lag_mad_seconds": 0.0,
        }],
    }
    second = {
        **_reconciliation_assignment("second", 200.0),
        "helper_links": [
            {
                "helper_circuit_id": "shared", "relationship": "corroborates",
                "status": "confirmed", "confidence": 0.1,
                "start_lag_seconds": 600.0, "start_lag_mad_seconds": 0.0,
            },
            {
                "helper_circuit_id": "independent",
                "relationship": "corroborates", "status": "confirmed",
                "confidence": 1.0, "start_lag_seconds": 0.0,
                "start_lag_mad_seconds": 0.0,
            },
        ],
    }
    runtime = {
        assignment_id: {"status": "off", "state_power_w": 0.0,
                        "estimated_power_w": 0.0, "consistent": True}
        for assignment_id in ("first", "second")
    }
    edge = NilmEdge(now, 100.0, 0.0, 100.0, 0.0, "on")

    runtime, reconciliation, _, accepted = reconcile_component_runtime(
        source_power_w=100.0, timestamp=now, assignments=(first, second),
        runtime=runtime, edges=(edge,), standby_w=0.0, noise_spread_w=0.0,
        helper_events=(
            CircuitEvent(now, "shared", EventType.START, features={}),
            CircuitEvent(now, "independent", EventType.START, features={}),
        ),
        available_helper_ids={"shared", "independent"},
    )

    assert accepted == [edge]
    assert reconciliation["conflict"] is None
    assert runtime["first"]["status"] == "on"
    assert runtime["second"]["status"] == "off"


def _reconciliation_assignment(
    assignment_id: str, watts: float
) -> dict[str, object]:
    return {
        "assignment_id": assignment_id,
        "lifecycle_state": "validated",
        "power_states_w": [0.0, watts],
        "transition_prototypes": [
            {"direction": "on", "from_state_w": 0.0, "to_state_w": watts,
             "delta_w": watts, "spread_w": 2.0, "sample_count": 3},
            {"direction": "off", "from_state_w": watts, "to_state_w": 0.0,
             "delta_w": -watts, "spread_w": 2.0, "sample_count": 3},
        ],
        "model_confidence": 0.9,
    }


@pytest.mark.parametrize(
    "assignment",
    [
        {**_reconciliation_assignment("load", 80.0), "lifecycle_state": "retired"},
        {**_reconciliation_assignment("load", 80.0), "power_states_w": []},
        {**_reconciliation_assignment("load", 80.0), "model_confidence": 0.2},
    ],
)
def test_nilm_restart_excludes_ineligible_models(
    assignment: dict[str, object],
) -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _initial_component_runtime,
        _restore_unique_component_state,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    runtime = _initial_component_runtime((assignment,), {}, now)

    _restore_unique_component_state(80.0, 0.0, 0.0, (assignment,), runtime, now)

    assert runtime["load"]["status"] == "unknown"


def test_nilm_restart_restores_user_assigned_model() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _initial_component_runtime,
        _restore_unique_component_state,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignment = {
        **_reconciliation_assignment("load", 80.0),
        "lifecycle_state": "assigned",
    }
    runtime = _initial_component_runtime((assignment,), {}, now)

    _restore_unique_component_state(80.0, 0.0, 0.0, (assignment,), runtime, now)

    assert runtime["load"]["status"] == "on"
    assert runtime["load"]["current_state_id"] == "running"
    assert runtime["load"]["current_state_power_w"] == 80.0
    assert runtime["load"]["state_since"] == now.isoformat()


def test_nilm_restart_restores_the_unique_supported_active_state() -> None:
    """Hydration must retain the matching multi-state ID, not collapse to running."""
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _initial_component_runtime,
        _restore_unique_component_state,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignment = {
        "assignment_id": "load",
        "lifecycle_state": "assigned",
        "model_confidence": 0.9,
        "power_states_w": [0.0, 80.0, 160.0],
        "states": [
            {"id": "off", "kind": "off", "power_w": 0.0, "spread_w": 0.0},
            {"id": "active_1", "kind": "active", "power_w": 80.0, "spread_w": 1.0},
            {"id": "active_2", "kind": "active", "power_w": 160.0, "spread_w": 1.0},
        ],
        "transition_prototypes": [
            {"direction": "on", "kind": "start", "from_state_id": "off",
             "to_state_id": "active_2", "from_state_w": 0.0,
             "to_state_w": 160.0, "delta_w": 160.0, "spread_w": 2.0,
             "sample_count": 4},
            {"direction": "off", "kind": "stop", "from_state_id": "active_2",
             "to_state_id": "off", "from_state_w": 160.0,
             "to_state_w": 0.0, "delta_w": -160.0, "spread_w": 2.0,
             "sample_count": 4},
        ],
    }
    runtime = _initial_component_runtime((assignment,), {}, now)

    _restore_unique_component_state(160.0, 0.0, 0.0, (assignment,), runtime, now)

    assert runtime["load"]["status"] == "on"
    assert runtime["load"]["current_state_id"] == "active_2"
    assert runtime["load"]["current_state_power_w"] == 160.0


def test_nilm_restart_restores_multiple_assigned_signature_models() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _initial_component_runtime,
        _restore_unique_component_state,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignments = [
        {
            "assignment_id": assignment_id,
            "lifecycle_state": "assigned",
            "signature_fingerprints": [fingerprint],
        }
        for assignment_id, fingerprint in (
            ("pump", "pump-fingerprint"),
            ("blower", "blower-fingerprint"),
        )
    ]
    signatures = [
        {
            "feedback_fingerprint": fingerprint,
            "median_delta_w": watts,
            "median_delta_var": reactive,
            "occurrence_count": 4,
            "confidence": 0.8,
        }
        for fingerprint, watts, reactive in (
            ("pump-fingerprint", 84.0, 27.0),
            ("blower-fingerprint", 319.0, 120.0),
        )
    ]
    runtime = _initial_component_runtime(assignments, {}, now)

    _restore_unique_component_state(
        403.0, 0.0, 0.0, assignments, runtime, now, signatures
    )

    assert {item["status"] for item in runtime.values()} == {"on"}


def test_confirmed_legacy_off_signature_drives_component_runtime() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _runtime_assignment_model,
    )

    fingerprint = (
        "direction=off|watts=0-100|var=0-100|va=0-100|pf=0.10-0.15|"
        "split=unknown|leg=unknown|balance=unknown"
    )
    model = _runtime_assignment_model(
        {
            "assignment_id": "pump",
            "lifecycle_state": "assigned",
            "confidence": 0.85,
            "signature_fingerprints": [fingerprint, "unassigned"],
            "confirmed_session_ids": ["confirmed-session"],
        },
        [
            {
                "feedback_fingerprint": fingerprint,
                "direction": "off",
                "median_delta_w": -82.0,
                "median_delta_var": 4.0,
                "occurrence_count": 3,
                "confidence": 0.6,
            }
        ],
    )

    assert model.power_states_w == (0.0, 82.0)
    assert [
        (item.direction, item.delta_w, item.delta_var)
        for item in model.transition_prototypes
    ] == [
        ("on", 82.0, -4.0),
        ("off", -82.0, 4.0),
    ]
    assert model.model_confidence == 0.85


def test_provisional_signature_model_remains_binary_with_multiple_signatures() -> None:
    """Unreviewed signatures cannot invent separate durable active states."""
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _runtime_assignment_model,
    )

    model = _runtime_assignment_model(
        {
            "assignment_id": "pump",
            "lifecycle_state": "assigned",
            "signature_fingerprints": ["signature-low", "signature-high"],
        },
        [
            {
                "feedback_fingerprint": "signature-low",
                "median_delta_w": 80.0,
                "occurrence_count": 3,
                "confidence": 0.70,
            },
            {
                "feedback_fingerprint": "signature-high",
                "median_delta_w": 160.0,
                "occurrence_count": 4,
                "confidence": 0.80,
            },
        ],
    )

    assert model.power_states_w == (0.0, 160.0)
    assert [
        (item.from_state_w, item.to_state_w)
        for item in model.transition_prototypes
    ] == [
        (0.0, 160.0),
        (160.0, 0.0),
    ]


def test_assigned_on_signature_replaces_legacy_off_fallback() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _runtime_assignment_model,
    )

    off_fingerprint = "direction=off|watts=0-100"
    on_fingerprint = "direction=on|watts=0-100"
    model = _runtime_assignment_model(
        {
            "assignment_id": "pump",
            "lifecycle_state": "assigned",
            "signature_fingerprints": [off_fingerprint, on_fingerprint],
            "confirmed_session_ids": ["confirmed-session"],
        },
        [
            {
                "feedback_fingerprint": off_fingerprint,
                "median_delta_w": -82.0,
                "occurrence_count": 3,
                "confidence": 0.85,
            },
            {
                "feedback_fingerprint": on_fingerprint,
                "median_delta_w": 78.0,
                "occurrence_count": 3,
                "confidence": 0.8,
            },
        ],
    )

    assert model.power_states_w == (0.0, 78.0)
    assert len(model.transition_prototypes) == 2


def test_confirmed_placeholder_sessions_identify_one_legacy_owner() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _confirmed_placeholder_owner,
    )

    start = datetime(2026, 8, 4, tzinfo=UTC)
    edges = [
        NilmEdge(
            timestamp=start + timedelta(minutes=index),
            delta_w=watts,
            delta_var=reactive,
            direction="on",
        )
        for index, (watts, reactive) in enumerate(
            [(80.0, -4.0), (82.0, -3.5), (84.0, -4.5)]
        )
    ]
    sessions = [
        {
            "session_id": f"session-{index}",
            "signature_fingerprint": "unassigned",
            "start": edge.timestamp.isoformat(),
        }
        for index, edge in enumerate(edges)
    ]
    signature = {
        "feedback_fingerprint": "direction=on|watts=0-100|var=0-100",
        "median_delta_w": 82.0,
        "median_delta_var": -4.0,
        "occurrence_count": 3,
    }
    owner = {
        "assignment_id": "pump",
        "lifecycle_state": "assigned",
        "signature_fingerprints": ["direction=off|watts=0-100", "unassigned"],
        "confirmed_session_ids": ["session-0", "session-1"],
    }

    assert _confirmed_placeholder_owner(signature, edges, [owner], sessions) is owner
    assert _confirmed_placeholder_owner(
        signature,
        edges,
        [
            owner,
            {
                **owner,
                "assignment_id": "other",
            },
        ],
        sessions,
    ) is None


def test_signature_payload_rebinds_confirmed_placeholder_owner() -> None:
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.nilm import (
        NilmEdge,
        NilmSignature,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 8, 4, 12, 5, tzinfo=UTC)
    edges = [
        NilmEdge(
            timestamp=now - timedelta(minutes=5 - index),
            delta_w=watts,
            delta_var=reactive,
            direction="on",
        )
        for index, (watts, reactive) in enumerate(
            [(80.0, -4.0), (82.0, -3.5), (84.0, -4.5)]
        )
    ]
    owner = {
        "assignment_id": "pump",
        "lifecycle_state": "assigned",
        "signature_fingerprints": ["direction=off|watts=0-100", "unassigned"],
        "confirmed_session_ids": ["session-0", "session-1"],
    }
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": [owner]},
            nilm_session_history_by_circuit={
                "mixed": [
                    {
                        "session_id": f"session-{index}",
                        "signature_fingerprint": "unassigned",
                        "assignment_id": "pump",
                        "start": edge.timestamp.isoformat(),
                    }
                    for index, edge in enumerate(edges)
                ]
            },
        ),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _id: 20.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _id, _events: (),
        observe_topology=lambda _config, _match, _context: [],
    )
    processor.unmatched_edges_by_circuit["mixed"] = edges

    payload = processor._nilm_signature_payloads(
        "mixed",
        [
            NilmSignature(
                signature_id="on-1",
                median_delta_w=82.0,
                median_delta_var=-4.0,
                occurrence_count=3,
                confidence=0.8,
            )
        ],
        context,
    )[0]

    assert payload["review_state"] == "assigned"
    assert payload["assignment_id"] == "pump"
    assert "unassigned" not in owner["signature_fingerprints"]
    assert payload["feedback_fingerprint"] in owner["signature_fingerprints"]


def test_nilm_signature_payload_migrates_unique_v1_metadata() -> None:
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.nilm import (
        NilmSignature,
        nilm_signature_fingerprint_v1,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    signature = NilmSignature("on-2", 500.0, 100.0, occurrence_count=3)
    context = ProcessingContext(
        now=datetime(2026, 8, 4, 12, 5, tzinfo=UTC),
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "pool-pump",
                        "signature_fingerprints": [
                            nilm_signature_fingerprint_v1(signature)
                        ],
                    }
                ]
            },
            nilm_signatures={
                "mains": [
                    {
                        "signature_id": "on-1",
                        "feedback_fingerprint": nilm_signature_fingerprint_v1(
                            signature
                        ),
                        "median_delta_w": 500.0,
                        "median_delta_var": 100.0,
                        "user_label": "Pool pump",
                        "ignored": True,
                    }
                ]
            }
        ),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _id: 20.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _id, _events: (),
        observe_topology=lambda _config, _match, _context: [],
    )

    payloads = processor._nilm_signature_payloads("mains", [signature], context)

    assert len(payloads) == 1
    assert payloads[0]["signature_id"] == "on-2"
    assert payloads[0]["user_label"] == "Pool pump"
    assert payloads[0]["ignored"] is True
    assert payloads[0]["fingerprint_revision"] == 2
    assert payloads[0]["legacy_feedback_fingerprint"] == (
        nilm_signature_fingerprint_v1(signature)
    )
    assert payloads[0]["feedback_fingerprint"] in (
        context.store_data.nilm_appliance_assignments_by_circuit["mains"][0][
            "signature_fingerprints"
        ]
    )


def test_nilm_signature_payload_retains_ambiguous_legacy_split_for_review() -> None:
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.nilm import (
        NilmSignature,
        nilm_signature_fingerprint_v1,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    children = [
        NilmSignature("on-1", 500.0, 100.0, occurrence_count=3),
        NilmSignature("on-2", 500.0, 150.0, occurrence_count=3),
    ]
    legacy = nilm_signature_fingerprint_v1(children[0])
    assert legacy == nilm_signature_fingerprint_v1(children[1])
    context = ProcessingContext(
        now=datetime(2026, 8, 4, 12, 5, tzinfo=UTC),
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mains": [
                    {
                        "signature_id": "on-old",
                        "feedback_fingerprint": legacy,
                        "median_delta_w": 500.0,
                        "median_delta_var": 125.0,
                        "user_label": "Do not duplicate me",
                        "ignored": True,
                    }
                ]
            }
        ),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _id: 20.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _id, _events: (),
        observe_topology=lambda _config, _match, _context: [],
    )

    payloads = processor._nilm_signature_payloads("mains", children, context)
    by_id = {payload["signature_id"]: payload for payload in payloads}

    assert "user_label" not in by_id["on-1"]
    assert "ignored" not in by_id["on-2"]
    assert by_id["on-1"]["migration_status"] == "ambiguous_split"
    assert by_id["on-2"]["review_state"] == "needs_review"
    retained = by_id["on-old"]
    assert retained["user_label"] == "Do not duplicate me"
    assert retained["ignored"] is True
    assert retained["migration_status"] == "ambiguous_split"
    assert retained["review_state"] == "needs_review"
    assert len(retained["split_into_fingerprints"]) == 2


def test_nilm_signature_payload_enriches_confidence_from_validation_precision() -> None:
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.nilm import (
        NilmSignature,
        nilm_signature_fingerprint,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    signature = NilmSignature(
        "on-1",
        500.0,
        occurrence_count=3,
        unique_day_count=3,
        on_off_support=0.8,
        intrinsic_confidence=0.5,
        confidence=0.5,
    )
    fingerprint = nilm_signature_fingerprint(signature)
    context = ProcessingContext(
        now=datetime(2026, 8, 4, 12, 5, tzinfo=UTC),
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mains": [
                    {
                        "assignment_id": "pool-pump",
                        "signature_fingerprints": [fingerprint],
                        "validation_evaluable_session_count": 3,
                        "validation_precision": 0.9,
                    }
                ]
            }
        ),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _id: 20.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _id, _events: (),
        observe_topology=lambda _config, _match, _context: [],
    )

    payload = processor._nilm_signature_payloads("mains", [signature], context)[0]

    assert payload["validated_precision"] == 0.9
    assert payload["confidence"] == 0.54
    assert payload["confidence_kind"] == "evidence"


def test_assigned_signature_drives_w_var_component_runtime() -> None:
    from collections import defaultdict
    from types import SimpleNamespace

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.managers.state_reducer import (
        apply_state_update,
    )
    from custom_components.circuitsetup_energy_analyzer.models import (
        ApplianceProfile,
        CircuitConfig,
        CircuitMode,
    )
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.normalize import (
        NormalizedCircuitSample,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )
    from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)

    class Detector:
        min_delta_w = 20.0
        has_pending_transition = False
        noise_spread_w = 0.0

        def process(self, _sample: object) -> list[NilmEdge]:
            return [NilmEdge(now, 84.0, 27.0, 88.0, 0.0, "on")]

    assignment = {
        "assignment_id": "pump",
        "lifecycle_state": "assigned",
        "signature_fingerprints": ["pump-fingerprint"],
    }
    store = FeatureStoreData(
        nilm_appliance_assignments_by_circuit={"mixed": [assignment]},
        nilm_signatures={"mixed": [{
            "signature_id": "on-1",
            "feedback_fingerprint": "pump-fingerprint",
            "median_delta_w": 84.0,
            "median_delta_var": 27.0,
            "occurrence_count": 4,
            "confidence": 0.8,
        }]},
    )
    state = AnalyzerState()
    state.nilm_component_runtime_by_circuit["mixed"] = {
        "pump": {
            "status": "off",
            "state_power_w": 0.0,
            "estimated_power_w": 0.0,
            "consistent": True,
            "last_observed": now.isoformat(),
            "energy_kwh": 0.0,
        }
    }
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _id: 20.0,
        detectors={"mixed": Detector()},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _id, _events: (),
        observe_topology=lambda _config, _match, _context: [],
    )
    sample = NormalizedCircuitSample(
        timestamp=now,
        circuit_id="mixed",
        real_power=84.0,
        current=None,
        voltage=None,
        reactive_power=27.0,
        apparent_power=88.0,
        power_factor=None,
        frequency=None,
        energy=None,
    )
    result = processor.process(
        sample,
        CircuitConfig("mixed", "Mixed", ApplianceProfile.MIXED, CircuitMode.MIXED),
        ProcessingContext(
            now=now,
            hass=SimpleNamespace(data={DOMAIN: {}}),
            state=state,
            store_data=store,
            options={},
            entry_data={},
            known_load_circuit_ids=frozenset(),
            sensitivity="balanced",
        ),
        events=(),
    )
    for update in result.state_updates:
        apply_state_update(state, update.path, update.value)

    runtime = state.nilm_component_runtime_by_circuit["mixed"]["pump"]
    assert runtime["status"] == "on"
    assert runtime["on_delta_w"] == 84.0
    assert runtime["on_delta_var"] == 27.0


def test_nilm_restart_restores_only_one_unique_bounded_fit() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _initial_component_runtime,
        _restore_unique_component_state,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    one = _reconciliation_assignment("one", 80.0)
    one["lifecycle_state"] = "validated"
    runtime = _initial_component_runtime((one,), {}, now)
    _restore_unique_component_state(100.0, 20.0, 0.0, (one,), runtime, now)
    assert runtime["one"]["status"] == "on"
    assert runtime["one"]["session_id"] == f"one|{now.isoformat()}"
    assert runtime["one"]["session_start"] == now.isoformat()

    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.nilm_virtual import (
        nilm_virtual_appliance_states,
    )

    state = AnalyzerState()
    state.nilm_component_runtime_by_circuit["mains"] = runtime
    state.nilm_reconciliation_by_circuit["mains"] = {
        "consistent": True, "conflict": None,
    }
    virtual_assignment = {**one, "mains_circuit_id": "mains"}
    coordinator = SimpleNamespace(
        data=state, circuit_configs=(),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mains": [virtual_assignment]}
        ),
    )
    assert nilm_virtual_appliance_states(coordinator)[0].is_running is True

    equal = [
        {**_reconciliation_assignment(key, 80.0), "lifecycle_state": "validated"}
        for key in ("one", "two")
    ]
    runtime = _initial_component_runtime(equal, {}, now)
    _restore_unique_component_state(80.0, 0.0, 0.0, equal, runtime, now)
    assert {item["status"] for item in runtime.values()} == {"unknown"}

    compound = [
        {**_reconciliation_assignment("one", 80.0), "lifecycle_state": "validated"},
        {**_reconciliation_assignment("two", 100.0), "lifecycle_state": "validated"},
    ]
    runtime = _initial_component_runtime(compound, {}, now)
    _restore_unique_component_state(180.0, 0.0, 0.0, compound, runtime, now)
    assert {item["status"] for item in runtime.values()} == {"on"}
    assert all(item["session_start"] == now.isoformat() for item in runtime.values())

    runtime = _initial_component_runtime((one,), {}, now)
    _restore_unique_component_state(20.0, 20.0, 0.0, (one,), runtime, now)
    assert runtime["one"]["status"] == "off"
    assert runtime["one"]["session_id"] is None
    assert runtime["one"]["session_start"] is None


def test_nilm_restart_restores_unique_state_with_three_active_components() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _initial_component_runtime,
        _restore_unique_component_state,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignments = [
        _reconciliation_assignment(name, watts)
        for name, watts in (("pump", 84.0), ("blower", 319.0), ("heater", 500.0))
    ]
    runtime = _initial_component_runtime(assignments, {}, now)

    _restore_unique_component_state(
        903.0, 0.0, 0.0, assignments, runtime, now
    )

    assert {item["status"] for item in runtime.values()} == {"on"}
    assert sum(item["estimated_power_w"] for item in runtime.values()) == 903.0


def test_nilm_restart_state_search_uses_twenty_most_recent_models() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _initial_component_runtime,
        _restore_unique_component_state,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignments = [
        {
            **_reconciliation_assignment(f"old-{index:02d}", 1_000.0 + index),
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        for index in range(20)
    ]
    assignments.append({
        **_reconciliation_assignment("recent", 80.0),
        "updated_at": now.isoformat(),
    })
    runtime = _initial_component_runtime(assignments, {}, now)

    _restore_unique_component_state(80.0, 0.0, 0.0, assignments, runtime, now)

    assert runtime["recent"]["status"] == "on"
    assert sum(item["status"] == "unknown" for item in runtime.values()) == 1


def test_runtime_assignment_model_discards_malformed_values() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _runtime_assignment_model,
    )

    model = _runtime_assignment_model({
        "assignment_id": "bad",
        "lifecycle_state": "validated",
        "power_states_w": ["bad", float("nan")],
        "transition_prototypes": [
            {"direction": "on", "from_state_w": "bad", "to_state_w": 80.0,
             "delta_w": float("inf"), "spread_w": {}, "sample_count": "bad"},
        ],
        "model_confidence": float("nan"),
    })

    assert model.power_states_w == ()
    assert model.transition_prototypes == ()
    assert model.model_confidence == 0.0


def test_runtime_assignment_model_preserves_prediction_identity() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _runtime_assignment_model,
    )

    model = _runtime_assignment_model({
        **_reconciliation_assignment("dryer", 100.0),
        "model_schema_version": 2,
        "model_revision": 7,
        "model_fingerprint": "dryer-model-seven",
        "transition_prototypes": [{
            "id": "dryer-start-v7",
            "kind": "start",
            "direction": "on",
            "from_state_id": "off",
            "to_state_id": "running",
            "from_state_w": 0.0,
            "to_state_w": 100.0,
            "delta_w": 100.0,
            "spread_w": 2.0,
            "sample_count": 3,
        }],
    })

    prototype = model.transition_prototypes[0]
    assert (
        prototype.prototype_id,
        prototype.transition_kind,
        prototype.from_state_id,
        prototype.to_state_id,
    ) == ("dryer:start:off->running", "start", "off", "running")
    assert prototype.prototype_aliases == ("dryer-start-v7",)
    assert (
        model.model_schema_version,
        model.model_revision,
        model.model_fingerprint,
    ) == (2, 7, "dryer-model-seven")


def test_confirmed_helper_scores_use_relationship_availability_and_learned_lag(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _confirmed_helper_scores,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    edge = NilmEdge(now, 100.0, 0.0, 100.0, 0.0, "on")
    assignments = [{
        "assignment_id": "load",
        "helper_links": [
            {"helper_circuit_id": "corroborating", "relationship": "corroborates",
             "status": "confirmed", "confidence": 0.8,
             "start_lag_seconds": 60.0, "start_lag_mad_seconds": 5.0},
            {"helper_circuit_id": "direct", "relationship": "direct_component",
             "status": "confirmed", "confidence": 1.0,
             "start_lag_seconds": 0.0, "start_lag_mad_seconds": 0.0},
        ],
    }]
    in_window = CircuitEvent(
        now + timedelta(seconds=170), "corroborating", EventType.START, features={}
    )

    assert _confirmed_helper_scores(
        assignments, (in_window,), edge, {"corroborating", "direct"}
    ) == {"load": 0.8}
    assert _confirmed_helper_scores(
        assignments, (), edge, {"corroborating"}
    ) == {"load": 0.0}
    assert _confirmed_helper_scores(assignments, (), edge, set()) == {}


def test_direct_component_uses_prior_power_and_closes_once() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _initial_component_runtime,
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignment = {
        **_reconciliation_assignment("pump", 60.0),
        "lifecycle_state": "validated",
        "helper_links": [{
            "helper_circuit_id": "meter", "relationship": "direct_component",
            "status": "confirmed", "confidence": 0.95,
        }],
    }
    runtime = _initial_component_runtime((assignment,), {}, now)
    runtime, first, completed, _ = reconcile_component_runtime(
        source_power_w=100.0, timestamp=now, assignments=(assignment,),
        runtime=runtime, edges=(), standby_w=0.0, noise_spread_w=0.0,
        direct_helper_powers={"meter": 60.0},
    )
    assert runtime["pump"]["status"] == "on"
    assert first["allocated_power_w"] == 60.0
    assert first["residual_w"] == 40.0
    assert completed == []

    suspended, unavailable, fake_close, _ = reconcile_component_runtime(
        source_power_w=None, timestamp=now + timedelta(seconds=5),
        assignments=(assignment,), runtime=runtime, edges=(), standby_w=0.0,
        noise_spread_w=0.0, previous_reconciliation=first,
        direct_helper_powers={"meter": 0.0},
    )
    assert suspended["pump"]["status"] == "uncertain"
    assert unavailable["conflict"] == "source_unavailable"
    assert fake_close == []

    runtime, second, completed, _ = reconcile_component_runtime(
        source_power_w=20.0, timestamp=now + timedelta(seconds=10),
        assignments=(assignment,), runtime=suspended, edges=(), standby_w=0.0,
        noise_spread_w=0.0, previous_reconciliation=unavailable,
        direct_helper_powers={"meter": 0.0},
    )
    assert runtime["pump"]["status"] == "off"
    assert completed[0]["on_delta_w"] == 60.0
    assert completed[0]["off_delta_w"] == -60.0
    assert completed[0]["energy_kwh"] == 0.0
    assert completed[0]["helper_evidence"][0]["relationship"] == "direct_component"
    assert runtime["pump"]["session_id"] is None
    assert runtime["pump"]["session_start"] is None

    runtime, _, repeated, _ = reconcile_component_runtime(
        source_power_w=20.0, timestamp=now + timedelta(seconds=10),
        assignments=(assignment,), runtime=runtime, edges=(), standby_w=0.0,
        noise_spread_w=0.0, previous_reconciliation=second,
        direct_helper_powers={"meter": 0.0},
    )
    assert repeated == []


def test_direct_component_clears_stale_nilm_prediction_provenance() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignment = {
        **_reconciliation_assignment("pump", 60.0),
        "helper_links": [{
            "helper_circuit_id": "meter", "relationship": "direct_component",
            "status": "confirmed", "confidence": 0.95,
        }],
    }
    stale = {
        "prototype_id": "stale-start",
        "model_revision": 4,
        "prediction_timestamp": (now - timedelta(hours=1)).isoformat(),
    }
    runtime = {
        "pump": {
            "status": "off", "state_power_w": 0.0, "estimated_power_w": 0.0,
            "session_id": None, "session_start": None, "energy_kwh": 0.0,
            "start_prediction": stale, "last_prediction": stale,
            "accepted_predictions": [stale],
            "state_path": [{"prototype_id": "stale-start"}],
        }
    }

    runtime, first, _, _ = reconcile_component_runtime(
        source_power_w=60.0, timestamp=now, assignments=(assignment,),
        runtime=runtime, edges=(), standby_w=0.0, noise_spread_w=0.0,
        direct_helper_powers={"meter": 60.0},
    )
    assert runtime["pump"]["start_prediction"] is None
    assert runtime["pump"]["last_prediction"] is None
    assert runtime["pump"]["accepted_predictions"] == []
    assert runtime["pump"]["state_path"] == []

    runtime, _, completed, _ = reconcile_component_runtime(
        source_power_w=0.0, timestamp=now + timedelta(minutes=5),
        assignments=(assignment,), runtime=runtime, edges=(), standby_w=0.0,
        noise_spread_w=0.0, previous_reconciliation=first,
        direct_helper_powers={"meter": 0.0},
    )

    assert completed[0]["start_prototype_id"] is None
    assert completed[0]["stop_prototype_id"] is None
    assert completed[0]["accepted_predictions"] == []
    assert completed[0]["state_path"] == []


def test_direct_component_takeover_clears_open_nilm_session_provenance() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignment = {
        **_reconciliation_assignment("pump", 60.0),
        "helper_links": [{
            "helper_circuit_id": "meter", "relationship": "direct_component",
            "status": "confirmed", "confidence": 0.95,
        }],
    }
    stale = {
        "prototype_id": "nilm-start",
        "model_revision": 4,
        "prediction_timestamp": (now - timedelta(hours=1)).isoformat(),
    }
    runtime = {
        "pump": {
            "status": "on", "state_power_w": 60.0, "estimated_power_w": 60.0,
            "session_id": "legacy-nilm-session",
            "session_start": (now - timedelta(hours=1)).isoformat(),
            "energy_kwh": 0.01, "start_prediction": stale,
            "last_prediction": stale, "accepted_predictions": [stale],
            "state_path": [{"prototype_id": "nilm-start"}],
        }
    }

    runtime, first, _, _ = reconcile_component_runtime(
        source_power_w=60.0, timestamp=now, assignments=(assignment,),
        runtime=runtime, edges=(), standby_w=0.0, noise_spread_w=0.0,
        direct_helper_powers={"meter": 60.0},
    )

    assert runtime["pump"]["session_id"] == "legacy-nilm-session"
    assert runtime["pump"]["session_source"] == "direct_helper"
    assert runtime["pump"]["start_prediction"] is None
    assert runtime["pump"]["last_prediction"] is None
    assert runtime["pump"]["accepted_predictions"] == []
    assert runtime["pump"]["state_path"] == []

    _, _, completed, _ = reconcile_component_runtime(
        source_power_w=0.0, timestamp=now + timedelta(minutes=5),
        assignments=(assignment,), runtime=runtime, edges=(), standby_w=0.0,
        noise_spread_w=0.0, previous_reconciliation=first,
        direct_helper_powers={"meter": 0.0},
    )

    assert completed[0]["session_id"] == "legacy-nilm-session"
    assert completed[0]["start_prototype_id"] is None
    assert completed[0]["stop_prototype_id"] is None
    assert completed[0]["accepted_predictions"] == []


def test_completed_session_records_only_matched_corroborating_helper() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _initial_component_runtime,
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignment = {
        **_reconciliation_assignment("load", 100.0),
        "helper_links": [{
            "helper_circuit_id": "helper", "relationship": "corroborates",
            "status": "confirmed", "confidence": 1.0,
            "start_lag_seconds": 0.0, "start_lag_mad_seconds": 1.0,
            "stop_lag_seconds": 0.0, "stop_lag_mad_seconds": 1.0,
        }, {
            "helper_circuit_id": "unmatched", "relationship": "corroborates",
            "status": "confirmed", "confidence": 1.0,
            "start_lag_seconds": 0.0, "start_lag_mad_seconds": 1.0,
            "stop_lag_seconds": 0.0, "stop_lag_mad_seconds": 1.0,
        }],
    }
    runtime = _initial_component_runtime((assignment,), {}, now)
    runtime["load"].update({
        "status": "off", "state_power_w": 0.0, "estimated_power_w": 0.0
    })
    runtime, reconciliation, _, _ = reconcile_component_runtime(
        source_power_w=100.0, timestamp=now, assignments=(assignment,),
        runtime=runtime, edges=(NilmEdge(now, 100, 0, 0, 0, "on"),),
        standby_w=0.0, noise_spread_w=0.0,
        helper_events=(CircuitEvent(now, "helper", EventType.START, features={}),),
        available_helper_ids={"helper"},
    )
    assert runtime["load"]["status"] == "on"
    runtime, _, completed, _ = reconcile_component_runtime(
        source_power_w=100.0, timestamp=now + timedelta(seconds=60),
        assignments=(assignment,), runtime=runtime,
        edges=(NilmEdge(now + timedelta(seconds=60), -100, 0, 0, 0, "off"),),
        standby_w=0.0, noise_spread_w=0.0,
        previous_reconciliation=reconciliation,
        helper_events=(CircuitEvent(
            now + timedelta(seconds=60), "helper", EventType.STOP, features={}
        ),),
        available_helper_ids={"helper"},
    )

    assert completed[0]["helper_evidence"] == [assignment["helper_links"][0]]


def test_energy_interval_is_atomic_and_capped_to_source() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    runtime = {
        key: {"status": "on", "state_power_w": 100.0,
              "estimated_power_w": 100.0, "session_id": key,
              "session_start": now.isoformat(), "confidence": 0.9,
              "consistent": True, "last_observed": now.isoformat(),
              "energy_kwh": 0.0}
        for key in ("one", "two")
    }
    previous = {
        "source_power_w": 100.0, "tolerance_w": 25.0,
        "consistent": True, "energy_allocation_allowed": True,
    }

    runtime, reconciliation, _, _ = reconcile_component_runtime(
        source_power_w=200.0, timestamp=now + timedelta(seconds=10),
        assignments=(), runtime=runtime, edges=(), standby_w=0.0,
        noise_spread_w=0.0, previous_reconciliation=previous,
    )

    assert sum(item["energy_kwh"] for item in runtime.values()) == 0.0
    assert reconciliation["conflict"] == "energy_over_allocation"
    assert reconciliation["residual_energy_kwh"] == 0.0


def test_energy_interval_uses_reconciliation_time_when_all_components_are_off() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    runtime = {"load": {
        "status": "off", "state_power_w": 0.0, "estimated_power_w": 0.0,
        "session_id": None, "session_start": None, "consistent": True,
        "last_observed": now.isoformat(), "energy_kwh": 0.0,
    }}
    previous = {
        "source_power_w": 120.0, "standby_w": 20.0, "tolerance_w": 25.0,
        "last_observed": now.isoformat(), "source_energy_kwh": 0.0,
        "component_energy_kwh": 0.0, "standby_energy_kwh": 0.0,
        "consistent": True, "energy_allocation_allowed": True,
    }

    runtime, reconciliation, _, _ = reconcile_component_runtime(
        source_power_w=120.0, timestamp=now + timedelta(seconds=37),
        assignments=(), runtime=runtime, edges=(), standby_w=20.0,
        noise_spread_w=0.0, previous_reconciliation=previous,
    )

    assert runtime["load"]["energy_kwh"] == 0.0
    assert reconciliation["source_energy_kwh"] == pytest.approx(120 * 37 / 3_600_000)
    assert reconciliation["standby_energy_kwh"] == pytest.approx(20 * 37 / 3_600_000)
    assert reconciliation["residual_energy_kwh"] == pytest.approx(100 * 37 / 3_600_000)


def test_energy_rollback_keeps_the_transition_edge_unknown() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        reconcile_component_runtime,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assignment = _reconciliation_assignment("pump", 100.0)
    runtime = {
        "pump": {
            "status": "off", "state_power_w": 0.0, "estimated_power_w": 0.0,
            "session_id": None, "session_start": None, "confidence": 0.9,
            "consistent": True, "last_observed": now.isoformat(),
            "energy_kwh": 0.0,
        }
    }
    edge = NilmEdge(
        now + timedelta(seconds=10), 100.0, 0.0, 100.0, 0.0, "on"
    )
    previous = {
        "source_power_w": 100.0, "source_energy_kwh": 0.0,
        "component_energy_kwh": 1.0, "standby_w": 0.0,
        "consistent": True, "energy_allocation_allowed": True,
    }

    runtime, reconciliation, completed, accepted = reconcile_component_runtime(
        source_power_w=100.0,
        timestamp=now + timedelta(seconds=10),
        assignments=(assignment,),
        runtime=runtime,
        edges=(edge,),
        standby_w=0.0,
        noise_spread_w=0.0,
        previous_reconciliation=previous,
    )

    assert accepted == completed == []
    assert runtime["pump"]["status"] == "uncertain"
    assert reconciliation["conflict"] == "energy_over_allocation"


def test_processor_keeps_only_rejected_reconciliation_edges_unknown() -> None:
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    edge = NilmEdge(now, 100.0, 0.0, 100.0, 0.0, "on")

    class Detector:
        min_delta_w = 20.0
        has_pending_transition = False
        noise_spread_w = 0.0

        def process(self, _sample: object) -> list[NilmEdge]:
            return [edge]

    def run(assignments: list[dict[str, object]]) -> int:
        state = AnalyzerState()
        state.nilm_component_runtime_by_circuit["mixed"] = {
            str(item["assignment_id"]): {
                "status": "off", "state_power_w": 0.0,
                "estimated_power_w": 0.0, "consistent": True,
                "last_observed": now.isoformat(),
            }
            for item in assignments
        }
        context = ProcessingContext(
            now=now, hass=SimpleNamespace(data={DOMAIN: {}}), state=state,
            store_data=FeatureStoreData(
                nilm_appliance_assignments_by_circuit={"mixed": assignments}
            ),
            options={}, entry_data={}, known_load_circuit_ids=frozenset(),
            sensitivity="standard",
        )
        processor = processors.NilmSampleProcessor(
            nilm_enabled=lambda _config: True,
            seed_demo_nilm_state=lambda _config, _now: None,
            min_delta_w_for_circuit=lambda _id: 20.0,
            detectors={"mixed": Detector()},
            total_events_by_circuit=defaultdict(int),
            unmatched_edges_by_circuit=defaultdict(list),
            ignored_signatures=set(), known_load_events=lambda _id, _events: (),
            observe_topology=lambda _config, _match, _context: [],
        )
        config = CircuitConfig(
            "mixed", "Mixed", ApplianceProfile.MIXED, CircuitMode.MIXED
        )
        sample = NormalizedCircuitSample(
            timestamp=now, circuit_id="mixed", real_power=100.0,
            current=None, voltage=None, reactive_power=None,
            apparent_power=None, power_factor=None, frequency=60.0,
            energy=None,
        )
        processor.process(
            sample, config, context, events=()
        )
        return len(processor.unmatched_edges_by_circuit["mixed"])

    accepted = [_reconciliation_assignment("only", 100.0)]
    ambiguous = [
        _reconciliation_assignment("first", 100.0),
        _reconciliation_assignment("second", 100.0),
    ]

    assert run(accepted) == 0
    assert run(ambiguous) == 1


@pytest.mark.parametrize(
    ("event_sample", "noisy_confirmation", "older_unmatched"),
    [(1, False, False), (2, False, False), (1, True, False), (1, False, True)],
)
def test_nilm_sample_processor_matches_confirmed_edge_to_known_event(
    event_sample: int,
    noisy_confirmation: bool,
    older_unmatched: bool,
) -> None:
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.models import (
        CircuitEvent,
        EventType,
    )
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData()
    state = AnalyzerState()
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=state,
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset({"fridge"}),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    observed_matches = []
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _circuit_id: 100.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _circuit_id, events: events,
        observe_topology=lambda _config, match, _context: observed_matches.append(match)
        or [],
    )
    if older_unmatched:
        processor.unmatched_edges_by_circuit["mains"] = [
            NilmEdge(now, 320.0, 0.0, 320.0, 0.0, "on")
        ]

    def sample(index: int, watts: float) -> NormalizedCircuitSample:
        return NormalizedCircuitSample(
            timestamp=now + timedelta(seconds=index * 5),
            circuit_id="mains",
            real_power=watts,
            current=None,
            voltage=None,
            reactive_power=None,
            apparent_power=None,
            power_factor=None,
            frequency=60.0,
            energy=None,
        )

    processor.process(sample(0, 100.0), config, context, events=())
    known_event = CircuitEvent(
        timestamp=now + timedelta(seconds=5),
        circuit_id="fridge",
        event_type=EventType.START,
        features={"startup_power_w": 390.0 if noisy_confirmation else 320.0},
    )
    processor.process(
        sample(1, 420.0),
        config,
        context,
        events=(known_event,) if event_sample == 1 else (),
    )
    result = processor.process(
        sample(2, 490.0 if noisy_confirmation else 420.0),
        config,
        context,
        events=(known_event,) if event_sample == 2 else (),
    )
    if noisy_confirmation:
        result = processor.process(sample(3, 490.0), config, context, events=())

    assert len(observed_matches) == 1
    assert observed_matches[0].known_circuit_id == "fridge"
    assert observed_matches[0].edge.timestamp == now + timedelta(
        seconds=10 if noisy_confirmation else 5
    )
    assert processor.total_events_by_circuit["mains"] == 1
    assert [
        edge.timestamp for edge in processor.unmatched_edges_by_circuit["mains"]
    ] == ([now] if older_unmatched else [])
    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("nilm_unmatched_load_percentage_by_circuit", "mains")] == (
        100.0 if older_unmatched else 0.0
    )


@pytest.mark.parametrize(
    ("observed_power_w", "known_power_w", "min_delta_w", "expected_residual_w"),
    [
        (600.0, 400.0, 100.0, 100.0),
        (575.0, 400.0, 50.0, 75.0),
        (850.0, 600.0, 250.0, None),
    ],
)
def test_nilm_sample_processor_reconciles_only_known_load_residual(
    monkeypatch: pytest.MonkeyPatch,
    observed_power_w: float,
    known_power_w: float,
    min_delta_w: float,
    expected_residual_w: float | None,
) -> None:
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import nilm_sample
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mains": [_reconciliation_assignment("unknown", 100.0)]
            }
        ),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset({"fridge"}),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    observed_matches = []
    reconciled_edges = []

    def reconcile(*, runtime: object, edges: object, **_kwargs: object) -> tuple[
        object, dict[str, object], list[object], list[object]
    ]:
        reconciled_edges.extend(edges)
        return runtime, {"consistent": True}, [], list(edges)

    monkeypatch.setattr(nilm_sample, "reconcile_component_runtime", reconcile)
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _circuit_id: min_delta_w,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _circuit_id, events: events,
        observe_topology=lambda _config, match, _context: (
            observed_matches.append(match) or []
        ),
    )

    def sample(seconds: int, watts: float) -> NormalizedCircuitSample:
        return NormalizedCircuitSample(
            timestamp=now + timedelta(seconds=seconds),
            circuit_id="mains",
            real_power=watts,
            current=None,
            voltage=None,
            reactive_power=None,
            apparent_power=None,
            power_factor=None,
            frequency=60.0,
            energy=None,
        )

    known_event = CircuitEvent(
        timestamp=now + timedelta(seconds=5),
        circuit_id="fridge",
        event_type=EventType.START,
        features={"startup_power_w": known_power_w},
    )
    processor.process(sample(0, 100.0), config, context, events=())
    processor.process(
        sample(5, observed_power_w), config, context, events=(known_event,)
    )
    processor.process(sample(10, observed_power_w), config, context, events=())

    assert len(observed_matches) == 1
    assert observed_matches[0].edge.delta_w == observed_power_w - 100.0
    if expected_residual_w is None:
        assert observed_matches[0].residual_edge is None
        assert reconciled_edges == []
    else:
        assert observed_matches[0].residual_edge is not None
        assert observed_matches[0].residual_edge.delta_w == expected_residual_w
        assert reconciled_edges == [observed_matches[0].residual_edge]
    assert processor.unmatched_edges_by_circuit["mains"] == []


def test_nilm_sample_processor_keeps_equal_fresh_edge_when_persisted_edge_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.nilm import (
        KnownLoadMatch,
        NilmEdge,
        NilmMaskResult,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        nilm_sample,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    persisted = NilmEdge(timestamp=now, delta_w=400.0, direction="on")
    fresh = NilmEdge(timestamp=now, delta_w=400.0, direction="on")

    class Detector:
        min_delta_w = 100.0
        noise_spread_w = 0.0
        has_pending_transition = False

        def process(self, _sample: object) -> list[NilmEdge]:
            return [fresh]

    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset({"fridge"}),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    unmatched = defaultdict(list, {"mains": [persisted]})
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda *_args: None,
        min_delta_w_for_circuit=lambda _id: 100.0,
        detectors={"mains": Detector()},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=unmatched,
        ignored_signatures=set(),
        known_load_events=lambda _id, events: events,
        observe_topology=lambda *_args: [],
    )
    candidate_counts = []

    def attribute(candidates, *_args, **_kwargs):
        candidate_counts.append(len(candidates))
        return NilmMaskResult(
            (KnownLoadMatch(persisted, "fridge", 1.0),),
            (fresh,),
        )

    monkeypatch.setattr(nilm_sample, "attribute_known_loads", attribute)
    sample = NormalizedCircuitSample(
        timestamp=now,
        circuit_id="mains",
        real_power=500.0,
        current=None,
        voltage=None,
        reactive_power=None,
        apparent_power=None,
        power_factor=None,
        frequency=60.0,
        energy=None,
    )
    event = CircuitEvent(
        timestamp=now,
        circuit_id="fridge",
        event_type=EventType.START,
        features={"startup_power_w": 400.0},
    )

    processor.process(sample, config, context, events=(event,))

    assert candidate_counts == [2]
    assert len(processor.unmatched_edges_by_circuit["mains"]) == 1
    assert processor.unmatched_edges_by_circuit["mains"][0] is fresh


def test_nilm_sample_processor_keeps_mixed_known_load_edges_unmatched() -> None:
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.managers import (
        nilm_controller,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset({"fridge"}),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="mixed",
        name="Mixed",
        appliance_profile=ApplianceProfile.MOTOR_LOAD,
        mode=CircuitMode.MIXED,
    )
    controller = nilm_controller.NilmController(
        SimpleNamespace(
            options={"enable_experimental_nilm": True},
            entry_data={},
            circuit_registry=SimpleNamespace(
                config_for_circuit=lambda _circuit_id: config,
                known_load_circuit_ids=frozenset({"fridge"}),
            ),
        ),
        label_interval_max_items=1,
        assignment_max_items=1,
    )
    observed_matches = []
    processor = processors.NilmSampleProcessor(
        nilm_enabled=controller.enabled_for_config,
        seed_demo_nilm_state=controller.seed_demo_state,
        min_delta_w_for_circuit=lambda _circuit_id: 100.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=controller.known_load_events,
        observe_topology=lambda _config, match, _context: observed_matches.append(match)
        or [],
    )

    def sample(seconds: int, watts: float) -> NormalizedCircuitSample:
        return NormalizedCircuitSample(
            timestamp=now + timedelta(seconds=seconds),
            circuit_id="mixed",
            real_power=watts,
            current=None,
            voltage=None,
            reactive_power=None,
            apparent_power=None,
            power_factor=None,
            frequency=60.0,
            energy=None,
        )

    known_event = CircuitEvent(
        timestamp=now + timedelta(seconds=5),
        circuit_id="fridge",
        event_type=EventType.START,
        features={"startup_power_w": 320.0},
    )
    processor.process(sample(0, 100.0), config, context, events=())
    processor.process(sample(5, 420.0), config, context, events=(known_event,))
    result = processor.process(sample(10, 420.0), config, context, events=())

    assert observed_matches == []
    assert result.alerts == []
    assert processor.total_events_by_circuit["mixed"] == 1
    assert len(processor.unmatched_edges_by_circuit["mixed"]) == 1
    assert not any(
        update.path[0].startswith("nilm_topology") for update in result.state_updates
    )


def test_nilm_sample_processor_collects_helper_candidate_statistics() -> None:
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.nilm import (
        NilmEdge,
        cluster_recurring_signatures,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    edges = [
        NilmEdge(
            now + timedelta(minutes=index),
            300.0 if index % 2 == 0 else -300.0,
            0.0,
            300.0,
            0.0,
            "on" if index % 2 == 0 else "off",
        )
        for index in range(6)
    ]
    events = [
        CircuitEvent(
            edge.timestamp,
            "hvac-2",
            EventType.START if edge.direction == "on" else EventType.STOP,
            features={},
        )
        for edge in edges
    ]
    context = ProcessingContext(
        now=now + timedelta(minutes=6),
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _id: 100.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _id, _events: (),
        helper_candidate_events=lambda _id, values: values,
        observe_topology=lambda _config, _match, _context: [],
    )
    processor.unmatched_edges_by_circuit["ac-2"] = edges
    processor._helper_events_by_source["ac-2"] = events

    payload = processor._nilm_signature_payloads(
        "ac-2", cluster_recurring_signatures(edges), context
    )[0]

    candidate = payload["helper_candidates"][0]
    assert candidate["helper_circuit_id"] == "hvac-2"
    assert candidate["matched_on_count"] == candidate["matched_off_count"] == 3
    context.store_data.nilm_signatures["ac-2"] = [payload]

    config = CircuitConfig(
        circuit_id="ac-2",
        name="AC 2",
        appliance_profile=ApplianceProfile.HVAC_BLOWER,
        mode=CircuitMode.MIXED,
    )
    sample = NormalizedCircuitSample(
        timestamp=now + timedelta(days=1),
        circuit_id="ac-2",
        real_power=100.0,
        current=None,
        voltage=None,
        reactive_power=None,
        apparent_power=None,
        power_factor=None,
        frequency=60.0,
        energy=None,
    )
    processor.process(sample, config, context, events=events)
    processor.process(sample, config, context, events=events)

    assert len(processor._helper_events_by_source["ac-2"]) == 6
    retained_candidate = context.store_data.nilm_signatures["ac-2"][0][
        "helper_candidates"
    ][0]
    assert retained_candidate["matched_on_count"] == 3
    assert retained_candidate["matched_off_count"] == 3

    processor._helper_events_by_source["ac-2"] = [
        CircuitEvent(
            now + timedelta(seconds=index),
            "hvac-2",
            EventType.START,
            features={},
        )
        for index in range(520)
    ]
    processor.process(sample, config, context, events=())

    retained = processor._helper_events_by_source["ac-2"]
    assert len(retained) == 512
    assert retained[0].timestamp == now + timedelta(seconds=8)


def test_nilm_helper_candidates_ignore_edges_before_observation_window() -> None:
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.nilm import (
        NilmEdge,
        cluster_recurring_signatures,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 20, tzinfo=UTC)
    old_edges = [
        NilmEdge(
            now - timedelta(minutes=20 - index),
            300.0 if index % 2 == 0 else -300.0,
            0.0,
            300.0,
            0.0,
            "on" if index % 2 == 0 else "off",
        )
        for index in range(6)
    ]
    recent_edges = [
        NilmEdge(
            now - timedelta(minutes=5 - index),
            300.0 if index % 2 == 0 else -300.0,
            0.0,
            300.0,
            0.0,
            "on" if index % 2 == 0 else "off",
        )
        for index in range(6)
    ]
    events = [
        CircuitEvent(
            edge.timestamp,
            "hvac-2",
            EventType.START if edge.direction == "on" else EventType.STOP,
            features={},
        )
        for edge in recent_edges
    ]
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    processor = processors.NilmSampleProcessor(
        nilm_enabled=lambda _config: True,
        seed_demo_nilm_state=lambda _config, _now: None,
        min_delta_w_for_circuit=lambda _id: 100.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=lambda _id, _events: (),
        helper_candidate_events=lambda _id, values: values,
        observe_topology=lambda _config, _match, _context: [],
    )
    edges = [*old_edges, *recent_edges]
    processor.unmatched_edges_by_circuit["ac-2"] = edges
    processor._helper_events_by_source["ac-2"] = events

    payload = processor._nilm_signature_payloads(
        "ac-2", cluster_recurring_signatures(edges), context
    )[0]

    candidate = payload["helper_candidates"][0]
    assert candidate["source_event_count"] == 6
    assert candidate["source_coverage"] == 1.0
    assert candidate["suggested"] is True


def test_confirmed_helper_link_refresh_preserves_relationship() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _refresh_confirmed_helper_links,
    )

    link = {
        "helper_circuit_id": "hvac-2",
        "relationship": "tracks_runtime",
        "status": "confirmed",
        "matched_on_count": 4,
        "matched_off_count": 5,
        "confidence": 0.9,
    }
    assignments = [{"signature_fingerprints": ["fingerprint"], "helper_links": [link]}]
    low_confidence = {
        "helper_circuit_id": "hvac-2",
        "matched_on_count": 6,
        "matched_off_count": 8,
        "confidence": 0.7,
        "start_lag_seconds": 8.0,
        "stop_lag_seconds": 12.0,
    }

    _refresh_confirmed_helper_links(assignments, "fingerprint", [low_confidence])

    assert link["relationship"] == "tracks_runtime"
    assert link["status"] == "confirmed"
    assert link["confidence"] == 0.7
    assert link["confirmed_matched_on_count"] == 4
    assert link["confirmed_matched_off_count"] == 5

    low_confidence["matched_on_count"] = 7
    _refresh_confirmed_helper_links(assignments, "fingerprint", [low_confidence])

    assert link["status"] == "degraded"


def test_confirmed_helper_link_refresh_normalizes_malformed_metrics() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _refresh_confirmed_helper_links,
    )

    link = {
        "helper_circuit_id": "hvac-2",
        "relationship": "tracks_runtime",
        "status": "confirmed",
        "matched_on_count": "invalid",
        "matched_off_count": {},
        "confirmed_matched_on_count": 10**10_000,
        "confirmed_matched_off_count": -4,
        "confidence": "NaN",
    }
    assignments = [{"signature_fingerprints": ["fingerprint"], "helper_links": [link]}]
    candidate = {
        "helper_circuit_id": "hvac-2",
        "matched_on_count": "7",
        "matched_off_count": 8.5,
        "confidence": float("nan"),
    }

    _refresh_confirmed_helper_links(assignments, "fingerprint", [candidate])

    assert link["matched_on_count"] == 7
    assert link["matched_off_count"] == 8
    assert link["confirmed_matched_on_count"] == 0
    assert link["confirmed_matched_off_count"] == 0
    assert link["confidence"] == 0.0


def test_confirmed_helper_link_unavailability_does_not_degrade() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors.nilm_sample import (
        _refresh_confirmed_helper_links,
    )

    link = {
        "helper_circuit_id": "hvac-2",
        "relationship": "tracks_runtime",
        "status": "confirmed",
        "matched_on_count": 3,
        "matched_off_count": 3,
        "confidence": 0.9,
    }
    assignments = [{"signature_fingerprints": ["fingerprint"], "helper_links": [link]}]

    _refresh_confirmed_helper_links(assignments, "fingerprint", [])

    assert link["status"] == "confirmed"
    assert "confirmed_matched_on_count" not in link


@pytest.mark.parametrize(
    ("profile", "mode", "expected_events"),
    [
        (ApplianceProfile.MAINS_NILM, CircuitMode.MAINS_NILM, 1),
        (ApplianceProfile.MIXED, CircuitMode.SINGLE_PHASE, 1),
        (ApplianceProfile.HVAC_BLOWER, CircuitMode.MIXED, 1),
        (ApplianceProfile.HVAC_BLOWER, CircuitMode.SINGLE_PHASE, 0),
    ],
)
def test_nilm_sample_processor_processes_only_configured_source_kinds(
    profile: ApplianceProfile,
    mode: CircuitMode,
    expected_events: int,
) -> None:
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.managers import (
        nilm_controller,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="source",
        name="Source",
        appliance_profile=profile,
        mode=mode,
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    controller = nilm_controller.NilmController(
        SimpleNamespace(
            options={"enable_experimental_nilm": True},
            entry_data={},
            circuit_registry=SimpleNamespace(
                known_load_circuit_ids=frozenset(),
                config_for_circuit=lambda _circuit_id: config,
            ),
        ),
        label_interval_max_items=1,
        assignment_max_items=1,
    )
    processor = processors.NilmSampleProcessor(
        nilm_enabled=controller.enabled_for_config,
        seed_demo_nilm_state=controller.seed_demo_state,
        min_delta_w_for_circuit=lambda _circuit_id: 100.0,
        detectors={},
        total_events_by_circuit=defaultdict(int),
        unmatched_edges_by_circuit=defaultdict(list),
        ignored_signatures=set(),
        known_load_events=controller.known_load_events,
        observe_topology=lambda _config, _match, _context: [],
    )

    for seconds, watts in ((0, 100.0), (5, 420.0), (10, 420.0)):
        processor.process(
            NormalizedCircuitSample(
                timestamp=now + timedelta(seconds=seconds),
                circuit_id="source",
                real_power=watts,
                current=None,
                voltage=None,
                reactive_power=None,
                apparent_power=None,
                power_factor=None,
                frequency=60.0,
                energy=None,
            ),
            config,
            context,
            events=(),
        )

    assert processor.total_events_by_circuit["source"] == expected_events


def test_leg_imbalance_processor_marks_single_phase_not_dual_phase() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    processor = processors.LegImbalanceProcessor(
        alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
    )

    result = processor.process(_energy_sample(1.0), config, context)

    assert result.alerts == []
    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("leg_imbalance_percent_by_circuit", "fridge")] == 0.0
    assert updates[("leg_imbalance_status_by_circuit", "fridge")] == "not_dual_phase"
    assert updates[("leg_imbalance_evidence_by_circuit", "fridge")]["status"] == (
        "not_dual_phase"
    )


def test_leg_imbalance_processor_uses_store_settings_override() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(
            leg_imbalance_settings_by_circuit={
                "hvac": {
                    "warning_ratio": 0.75,
                    "minimum_total_power_w": 4000.0,
                }
            }
        ),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC_COMPRESSOR,
        mode=CircuitMode.DUAL_PHASE,
    )
    sample = NormalizedCircuitSample(
        timestamp=now,
        circuit_id="hvac",
        real_power=3600.0,
        current=30.0,
        voltage=240.0,
        reactive_power=0.0,
        apparent_power=3600.0,
        power_factor=1.0,
        frequency=60.0,
        energy=0.0,
        leg_a_real_power=2400.0,
        leg_b_real_power=1200.0,
    )
    processor = processors.LegImbalanceProcessor(
        alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
    )

    result = processor.process(sample, config, context)

    assert result.alerts == []
    updates = {update.path: update.value for update in result.state_updates}
    evidence = updates[("leg_imbalance_evidence_by_circuit", "hvac")]
    assert evidence["status"] == "idle"
    assert evidence["threshold_ratio"] == 0.75
    assert evidence["threshold_percent"] == 75.0
    assert evidence["minimum_total_power_w"] == 4000.0


def test_metric_consistency_processor_updates_state_from_store_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(
            metric_consistency_settings_by_circuit={
                "pump": {
                    "apparent_power_tolerance_percent": 10.0,
                    "power_factor_tolerance": 0.1,
                    "minimum_apparent_power_va": 50.0,
                }
            }
        ),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="pump",
        name="Pool Pump",
        appliance_profile=ApplianceProfile.WATER_PUMP,
        mode=CircuitMode.SINGLE_PHASE,
    )
    sample = CircuitSample(
        timestamp=now,
        circuit_id="pump",
        real_power=480.0,
        current=10.0,
        voltage=120.0,
        reactive_power=0.0,
        apparent_power=600.0,
        power_factor=0.8,
        frequency=60.0,
        energy=0.0,
    )
    processor = processors.MetricConsistencyProcessor()

    result = processor.process(sample, config, context)

    assert result.store_dirty is False
    assert result.alerts == []
    assert result.notifications == []
    assert len(result.state_updates) == 3

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("metric_consistency_score_by_circuit", "pump")] == 50.0
    assert updates[("metric_consistency_status_by_circuit", "pump")] == (
        "apparent_power_mismatch"
    )
    assert updates[("metric_consistency_evidence_by_circuit", "pump")] == {
        "status": "apparent_power_mismatch",
        "mismatch_score_percent": 50.0,
        "expected_apparent_power_va": 1200.0,
        "reported_apparent_power_va": 600.0,
        "apparent_power_difference_percent": -50.0,
        "apparent_power_tolerance_percent": 10.0,
        "apparent_power_source": "voltage_current",
        "expected_power_factor": 0.8,
        "reported_power_factor": 0.8,
        "power_factor_difference": 0.0,
        "power_factor_tolerance": 0.1,
    }


def test_standby_processor_updates_state_and_returns_always_on_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        standby_by_circuit={
            "office": {
                "standby_sample_format": "1m-min-v1",
                "samples": [
                    {
                        "timestamp": (now - timedelta(hours=offset + 1)).isoformat(),
                        "real_power_w": 45.0,
                    }
                    for offset in range(6)
                ]
            }
        }
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="office",
        name="Office",
        appliance_profile=ApplianceProfile.MOTOR_LOAD,
        mode=CircuitMode.SINGLE_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = processors.StandbyProcessor(
        settings_for_config=lambda _config, _circuit_id: StandbySettings(
            standby_threshold_w=8.0,
            always_on_alert_w=25.0,
            min_samples=6,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
        seed_demo_history=lambda _config, _sample, _context, _settings: None,
    )

    result = processor.process(_sample(0, 46.0), config, context)

    assert result.store_dirty is True
    assert len(result.state_updates) == 5
    assert len(result.alerts) == 1
    assert result.notifications == result.alerts
    assert policy.observations[0].feature == "always_on_power"
    assert policy.observations[0].observed_value == 45.0
    assert policy.observations[0].baseline_value == 25.0
    assert "Office Always On is 45 W" in result.alerts[0].message

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("always_on_power_w_by_circuit", "office")] == 45.0
    assert updates[("standby_threshold_w_by_circuit", "office")] == 8.0
    assert updates[("standby_status_by_circuit", "office")] == "on"
    assert updates[("always_on_limit_usage_by_circuit", "office")] == 180.0
    assert updates[("standby_evidence_by_circuit", "office")] == {
        "always_on_power_w": 45.0,
        "current_power_w": 46.0,
        "standby_threshold_w": 8.0,
        "sample_count": 7,
        "window_hours": 48,
        "always_on_alert_w": 25.0,
        "always_on_limit_usage_percent": 180.0,
        "status": "on",
    }


def test_standby_processor_alert_features_include_contextual_baseline_details() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context_key = {
        "appliance_profile": "water_heater",
        "circuit_mode": "single_phase",
        "season": "summer",
        "day_type": "weekday",
        "time_of_day": "afternoon",
        "water_flow_state": "active_flow",
    }
    store_data = FeatureStoreData(
        standby_by_circuit={
            "water_heater": {
                "standby_sample_format": "1m-min-v1",
                "samples": [
                    {
                        "timestamp": (now - timedelta(hours=offset + 1)).isoformat(),
                        "real_power_w": 45.0,
                    }
                    for offset in range(6)
                ]
            }
        },
        contextual_baseline_samples_by_circuit={
            "water_heater": [
                {
                    "timestamp": (now - timedelta(days=offset + 2)).isoformat(),
                    "feature": "standby_power_w",
                    "value": value,
                    "context": context_key,
                    "source": "standby",
                }
                for offset, value in enumerate(
                    (41.0, 42.0, 43.0, 44.0, 45.0, 46.0, 47.0)
                )
            ]
        },
    )
    state = AnalyzerState()
    state.water_flow_context_by_circuit["water_heater"] = {
        "flow_sensor_active": True,
        "flow_active_minutes": 12.0,
    }
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=state,
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="water_heater",
        name="Water Heater",
        appliance_profile=ApplianceProfile.WATER_HEATER,
        mode=CircuitMode.SINGLE_PHASE,
    )
    policy = _CaptureAlertPolicy()
    processor = processors.StandbyProcessor(
        settings_for_config=lambda _config, _circuit_id: StandbySettings(
            standby_threshold_w=8.0,
            always_on_alert_w=25.0,
            min_samples=6,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
        seed_demo_history=lambda _config, _sample, _context, _settings: None,
    )

    result = processor.process(_sample(0, 46.0), config, context)

    assert len(result.alerts) == 1
    assert policy.observations[0].feature == "always_on_power"
    assert policy.observations[0].baseline_value == 25.0
    assert policy.observations[0].features["comparison_basis"] == "contextual"
    assert policy.observations[0].features["baseline_fallback_level"] == (
        "exact_context"
    )
    assert policy.observations[0].features["baseline_sample_count"] == 7
    assert policy.observations[0].features["contextual_baseline_p90_w"] == 46.0

    updates = {update.path: update.value for update in result.state_updates}
    evidence = updates[("standby_evidence_by_circuit", "water_heater")]
    assert evidence["comparison_basis"] == "contextual"
    assert evidence["contextual_baseline_median_w"] == 44.0
    assert (
        store_data.contextual_baseline_samples_by_circuit["water_heater"][-1][
            "feature"
        ]
        == "standby_power_w"
    )


def test_standby_processor_learning_path_uses_demo_seeder_without_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(
            standby_by_circuit={
                "office": {
                    "standby_sample_format": "1m-min-v1",
                    "samples": [
                        {
                            "timestamp": (now - timedelta(seconds=30)).isoformat(),
                            "real_power_w": 5.0,
                        },
                        {
                            "timestamp": (now - timedelta(seconds=10)).isoformat(),
                            "real_power_w": 3.0,
                        },
                    ]
                }
            }
        ),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="office",
        name="Office",
        appliance_profile=ApplianceProfile.MOTOR_LOAD,
        mode=CircuitMode.SINGLE_PHASE,
    )
    seeded: list[str] = []

    def seed_demo_history(
        seeded_config: CircuitConfig,
        _sample: CircuitSample,
        seeded_context: ProcessingContext,
        settings: StandbySettings,
    ) -> None:
        seeded.append(seeded_config.circuit_id)
        assert seeded_context is context
        assert settings.min_samples == 4

    processor = processors.StandbyProcessor(
        settings_for_config=lambda _config, _circuit_id: StandbySettings(
            min_samples=4,
        ),
        alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
        seed_demo_history=seed_demo_history,
    )

    result = processor.process(_sample(0, 4.0), config, context)

    assert seeded == ["office"]
    assert result.store_dirty is True
    assert result.alerts == []
    assert context.store_data.standby_by_circuit["office"] == {
            "standby_sample_format": "1m-min-v1",
            "samples": [
                {
                    "timestamp": (now - timedelta(seconds=30)).isoformat(),
                    "real_power_w": 5.0,
                },
                {
                    "timestamp": (now - timedelta(seconds=10)).isoformat(),
                    "real_power_w": 3.0,
                },
            {"timestamp": now.isoformat(), "real_power_w": 4.0},
        ],
    }
    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("always_on_power_w_by_circuit", "office")] == 0.0
    assert updates[("standby_status_by_circuit", "office")] == "learning"
    assert updates[("standby_evidence_by_circuit", "office")] == {
        "always_on_power_w": 0.0,
        "current_power_w": 4.0,
        "standby_threshold_w": 8.0,
        "sample_count": 3,
        "window_hours": 48,
        "always_on_alert_w": None,
        "always_on_limit_usage_percent": 0.0,
        "status": "learning",
    }


def test_power_quality_processor_updates_generation_state_and_returns_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        baselines={
            "fridge:real_power": BaselineStats(
                feature="real_power",
                sample_count=20,
                median=120.0,
                mad=5.0,
                p10=110.0,
                p90=130.0,
                confidence=1.0,
            ),
            "fridge:reactive_power": BaselineStats(
                feature="reactive_power",
                sample_count=20,
                median=20.0,
                mad=2.0,
                p10=16.0,
                p90=24.0,
                confidence=1.0,
            ),
            "fridge:apparent_power": BaselineStats(
                feature="apparent_power",
                sample_count=20,
                median=122.0,
                mad=5.0,
                p10=112.0,
                p90=132.0,
                confidence=1.0,
            ),
            "fridge:power_factor": BaselineStats(
                feature="power_factor",
                sample_count=20,
                median=0.98,
                mad=0.02,
                p10=0.94,
                p90=1.0,
                confidence=1.0,
            ),
            "fridge:reactive_to_real_ratio": BaselineStats(
                feature="reactive_to_real_ratio",
                sample_count=20,
                median=0.16,
                mad=0.02,
                p10=0.12,
                p90=0.2,
                confidence=1.0,
            ),
            "fridge:apparent_to_real_ratio": BaselineStats(
                feature="apparent_to_real_ratio",
                sample_count=20,
                median=1.02,
                mad=0.02,
                p10=0.98,
                p90=1.06,
                confidence=1.0,
            ),
            "fridge:power_factor_deficit": BaselineStats(
                feature="power_factor_deficit",
                sample_count=20,
                median=0.02,
                mad=0.01,
                p10=0.0,
                p90=0.04,
                confidence=1.0,
            ),
            "fridge:apparent_power_residual": BaselineStats(
                feature="apparent_power_residual",
                sample_count=20,
                median=0.03,
                mad=0.01,
                p10=0.0,
                p90=0.06,
                confidence=1.0,
            ),
        }
    )
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=store_data,
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        power_flow=PowerFlowMode.GENERATION,
    )
    sample = CircuitSample(
        timestamp=now,
        circuit_id="fridge",
        real_power=120.0,
        current=1.0,
        voltage=120.0,
        reactive_power=80.0,
        apparent_power=145.0,
        power_factor=0.83,
        frequency=60.0,
        energy=0.0,
    )
    policy = _CaptureAlertPolicy()
    processor = processors.PowerQualityProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
        learning_mature=lambda _config, _now: True,
        seed_demo_event_history=lambda _config, _now: None,
        seed_demo_power_quality_baselines=lambda _config, _features: None,
    )

    result = processor.process(sample, config, context)

    assert result.clear_power_quality_state is None
    assert result.store_dirty is False
    assert len(result.state_updates) == 6
    assert len(result.alerts) == 1
    assert result.notifications == result.alerts
    assert policy.observations[0].circuit_id == "fridge"
    assert policy.observations[0].baseline_confidence == 1.0

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("learning_by_circuit", "fridge")] is False
    assert updates[("power_quality_score_by_circuit", "fridge")] > 0.0
    assert updates[("power_quality_evidence_by_circuit", "fridge")]
    assert updates[("reactive_power_drift_by_circuit", "fridge")] > 0.0
    assert updates[("apparent_power_drift_by_circuit", "fridge")] > 0.0
    assert updates[("power_factor_drift_by_circuit", "fridge")] > 0.0


@pytest.mark.parametrize(
    ("profile", "mode"),
    [
        (ApplianceProfile.REFRIGERATOR, CircuitMode.MIXED),
        (ApplianceProfile.MIXED, CircuitMode.SINGLE_PHASE),
    ],
)
def test_power_quality_processor_marks_mixed_circuit_aggregate_ready(
    profile: ApplianceProfile,
    mode: CircuitMode,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    policy = _CaptureAlertPolicy()
    context = ProcessingContext(
        now=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    processor = processors.PowerQualityProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
        learning_mature=lambda _config, _now: True,
        seed_demo_event_history=lambda _config, _now: None,
        seed_demo_power_quality_baselines=lambda _config, _features: None,
    )

    result = processor.process(
        _sample(0, 120.0),
        CircuitConfig(
            circuit_id="fridge",
            name="Kitchen Fridge",
            appliance_profile=profile,
            mode=mode,
        ),
        context,
    )

    assert result.clear_power_quality_state == "fridge"
    assert [(update.path, update.value) for update in result.state_updates] == [
        (("learning_by_circuit", "fridge"), False)
    ]
    assert result.alerts == []
    assert policy.observations == []
    assert context.store_data.baselines == {}


def test_power_quality_processor_requests_clear_when_features_missing() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    sample = CircuitSample(
        timestamp=now,
        circuit_id="fridge",
        real_power=None,
        current=None,
        voltage=None,
        reactive_power=None,
        apparent_power=None,
        power_factor=None,
        frequency=60.0,
        energy=0.0,
    )
    processor = processors.PowerQualityProcessor(
        alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
        learning_mature=lambda _config, _now: True,
        seed_demo_event_history=lambda _config, _now: None,
        seed_demo_power_quality_baselines=lambda _config, _features: None,
    )

    result = processor.process(sample, config, context)

    assert result.clear_power_quality_state == "fridge"
    assert result.alerts == []
    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("learning_by_circuit", "fridge")] is True


def test_power_quality_processor_does_not_learn_during_maintenance() -> None:
    from collections import defaultdict

    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    baseline_values: defaultdict[str, list[float]] = defaultdict(list)
    seeded_events: list[str] = []
    seeded: list[dict[str, float]] = []
    policy = _CaptureAlertPolicy()
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(
            maintenance_by_circuit={"fridge": {"active": True}}
        ),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    sample = CircuitSample(
        timestamp=now,
        circuit_id="fridge",
        real_power=120.0,
        current=1.0,
        voltage=120.0,
        reactive_power=80.0,
        apparent_power=145.0,
        power_factor=0.83,
        frequency=60.0,
        energy=0.0,
    )
    processor = processors.PowerQualityProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
        learning_mature=lambda _config, _now: True,
        seed_demo_event_history=lambda config, _now: seeded_events.append(
            config.circuit_id
        ),
        seed_demo_power_quality_baselines=lambda _config, features: seeded.append(
            dict(features)
        ),
        baseline_values=baseline_values,
    )

    result = processor.process(sample, config, context)

    assert baseline_values == {}
    assert seeded_events == []
    assert seeded == []
    assert policy.observations == []
    assert result.alerts == []
    assert result.store_dirty is False


@pytest.mark.asyncio
async def test_utility_comparison_processor_updates_state_and_returns_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer import processors
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        AnalyzerState,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    context = ProcessingContext(
        now=now,
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset(),
        sensitivity="standard",
    )
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    policy = _CaptureAlertPolicy()
    processor = processors.UtilityComparisonProcessor(
        settings_for_circuit=lambda _circuit_id: UtilityComparisonSettings(
            utility_energy_entity="sensor.opower_current_bill_usage",
            utility_cost_entity="sensor.opower_current_bill_cost",
            measured_energy_entities=("sensor.panel_import_energy",),
            tolerance_percent=10.0,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
        energy_kwh_for_entity=lambda entity_id, _now: {
            "sensor.opower_current_bill_usage": 120.0,
        }.get(entity_id),
        energy_kwh_sum_for_entities=lambda entity_ids, _now: (
            135.0,
            tuple(entity_ids),
        ),
        statistics_kwh_for_id=None,
        statistics_kwh_sum_for_entities=None,
        load_energy_entity_ids_for_sum=lambda _circuit_id: (),
        numeric_value_for_entity=lambda entity_id: {
            "sensor.opower_current_bill_cost": 30.0,
        }.get(entity_id),
    )

    result = await processor.process(config, context)

    assert result.store_dirty is False
    assert len(result.state_updates) == 5
    assert len(result.alerts) == 1
    assert result.notifications == result.alerts
    assert policy.observations[0].feature == "utility_energy_mismatch"
    assert policy.observations[0].observed_value == 135.0
    assert policy.observations[0].baseline_value == 120.0
    assert "Mains measured 135 kWh" in result.alerts[0].message

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("utility_comparison_difference_kwh_by_circuit", "mains")] == 15.0
    assert updates[("utility_comparison_difference_percent_by_circuit", "mains")] == (
        12.5
    )
    assert updates[("utility_comparison_status_by_circuit", "mains")] == "mismatch"
    assert updates[("utility_comparison_evidence_by_circuit", "mains")] == {
        "status": "mismatch",
        "utility_energy_entity": "sensor.opower_current_bill_usage",
        "utility_cost_entity": "sensor.opower_current_bill_cost",
        "utility_statistic_id": "",
        "utility_source_id": "sensor.opower_current_bill_usage",
        "utility_source_type": "entity",
        "utility_statistic_period": "day",
        "measured_energy_entities": ["sensor.panel_import_energy"],
        "comparison_source": "explicit_entities",
        "measured_source_type": "entity_state",
        "period_start": None,
        "period_end": None,
        "utility_data_lag_hours": None,
        "utility_kwh": 120.0,
        "utility_cost": 30.0,
        "rate_per_kwh": 0.25,
        "measured_kwh": 135.0,
        "difference_kwh": 15.0,
        "difference_percent": 12.5,
        "absolute_difference_percent": 12.5,
        "tolerance_percent": 10.0,
    }
    assert updates[("utility_cost_rate_by_circuit", "mains")] == 0.25


def test_utility_rate_uses_matching_entity_usage_not_comparison_statistic(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        utility_comparison as utility_processor,
    )
    from custom_components.circuitsetup_energy_analyzer.utility_comparison import (
        compare_utility_energy,
    )

    settings = UtilityComparisonSettings(
        utility_energy_entity="sensor.opower_current_bill_usage",
        utility_cost_entity="sensor.opower_current_bill_cost",
        utility_statistic_id="opower:daily_usage",
        utility_source_type="statistics",
    )
    result = compare_utility_energy(
        settings=settings,
        utility_kwh=10.0,
        measured_kwh=10.0,
        measured_entity_ids=("sensor.panel_import_energy",),
        comparison_source="explicit_entities",
        utility_source_type="statistics",
    )

    updates = utility_processor.utility_comparison_state_updates(
        "mains",
        result,
        utility_cost=30.0,
        utility_cost_entity=settings.utility_cost_entity,
        utility_rate_kwh=120.0,
    )
    values = {update.path: update.value for update in updates}

    assert values[("utility_cost_rate_by_circuit", "mains")] == 0.25


def test_utility_comparison_does_not_overwrite_a_valid_rate_with_zero_cost() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        utility_comparison as utility_processor,
    )
    from custom_components.circuitsetup_energy_analyzer.utility_comparison import (
        compare_utility_energy,
    )

    result = compare_utility_energy(
        settings=UtilityComparisonSettings(),
        utility_kwh=10.0,
        measured_kwh=10.0,
        measured_entity_ids=("sensor.panel_import_energy",),
        comparison_source="explicit_entities",
    )

    updates = utility_processor.utility_comparison_state_updates(
        "mains",
        result,
        utility_cost=0.0,
        utility_rate_kwh=120.0,
    )

    assert ("utility_cost_rate_by_circuit", "mains") not in {
        update.path for update in updates
    }


def _appliance_health_history(
    day_count: int,
) -> tuple[list[dict[str, object]], list[CircuitEvent]]:
    days: list[dict[str, object]] = []
    events: list[CircuitEvent] = []
    for day in range(1, day_count + 1):
        day_start = datetime(2026, 7, day, 0, 0, tzinfo=UTC)
        days.append(
            {
                "date": day_start.date().isoformat(),
                "usage_kwh": 2.0 if day <= 14 else 3.0,
                "complete": True,
                "baseline_eligible": True,
            }
        )
        for cycle in range(4):
            started_at = day_start + timedelta(hours=cycle * 4 + 1)
            events.extend(
                (
                    CircuitEvent(
                        started_at,
                        "fridge",
                        EventType.START,
                        features={"baseline_eligible": True},
                    ),
                    CircuitEvent(
                        started_at + timedelta(minutes=30),
                        "fridge",
                        EventType.STOP,
                        features={"baseline_eligible": True},
                    ),
                )
            )
    return days, events


def _appliance_health_context(
    *,
    days: list[dict[str, object]],
    events: list[CircuitEvent],
    learning: bool,
) -> object:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        ProcessingContext,
    )

    state = AnalyzerState()
    state.learning_by_circuit["fridge"] = learning
    return ProcessingContext(
        now=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        hass=SimpleNamespace(data={DOMAIN: {}}),
        state=state,
        store_data=FeatureStoreData(
            events=events,
            energy_usage_by_circuit={"fridge": {"days": days}},
        ),
        options={},
        entry_data={},
        known_load_circuit_ids=frozenset({"fridge"}),
        sensitivity="standard",
        time_zone="UTC",
    )


def test_appliance_health_processor_stays_learning_with_shared_learning() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        ApplianceHealthProcessor,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        StateUpdate,
    )

    days, events = _appliance_health_history(17)
    context = _appliance_health_context(days=days, events=events, learning=True)
    processor = ApplianceHealthProcessor(
        alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
        merge_gap_seconds_for_config=lambda _config: 60.0,
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )

    result = processor.process(_energy_sample(120.5), config, context)

    assert result.state_updates == [
        StateUpdate(("appliance_health_status_by_circuit", "fridge"), "learning"),
        StateUpdate(
            ("appliance_health_evidence_by_circuit", "fridge"),
            {"status": "learning", "reason": "shared_learning_active"},
        ),
    ]
    assert result.alerts == []
    assert result.notifications == []


def test_appliance_health_relearn_ignores_prior_evidence() -> None:
    from custom_components.circuitsetup_energy_analyzer.processors import (
        ApplianceHealthProcessor,
    )

    days, events = _appliance_health_history(19)
    context = _appliance_health_context(days=days, events=events, learning=False)
    context.store_data.learning_started_at_by_circuit["fridge"] = (
        "2026-07-18T00:00:00+00:00"
    )
    processor = ApplianceHealthProcessor(
        alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
        merge_gap_seconds_for_config=lambda _config: 60.0,
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )

    result = processor.process(_energy_sample(120.5), config, context)

    assert result.state_updates[0].value == "learning"
    assert result.state_updates[1].value["reason"] == "insufficient_history"
    assert result.observations == []
    assert result.alerts == []
    assert result.notifications == []


def test_appliance_health_feedback_fingerprint_includes_comparison_context() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        alert_feedback_fingerprint,
    )
    from custom_components.circuitsetup_energy_analyzer.appliance_health import (
        ApplianceHealthFinding,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        appliance_health as appliance_health_processor,
    )

    def fingerprint(context: dict[str, str]) -> tuple[dict[str, object], str]:
        finding = ApplianceHealthFinding(
            feature="efficiency_degradation",
            metric="energy_per_runtime_hour",
            reference_median=1.0,
            recent_median=1.5,
            change_ratio=0.5,
            reference_count=14,
            recent_count=3,
            confidence=1.0,
            last_evidence_at="2026-07-17",
            context=context,
        )
        features = appliance_health_processor._finding_features(finding)
        alert = AlertEvidence(
            timestamp=datetime(2026, 7, 20, tzinfo=UTC),
            circuit_id="appliance",
            severity=Severity.WARNING,
            message="Possible issue",
            feature=finding.feature,
            value_metric=finding.metric,
            observed_value=finding.recent_median,
            baseline_value=finding.reference_median,
            change_ratio=finding.change_ratio,
            features=features,
        )
        return features, alert_feedback_fingerprint(alert)

    summer_features, summer = fingerprint(
        {
            "season": "summer",
            "weather_mode": "cooling",
            "temperature_bin": "hot",
        }
    )
    _, winter = fingerprint(
        {
            "season": "winter",
            "weather_mode": "heating",
            "temperature_bin": "cold",
        }
    )
    _, active_flow = fingerprint({"water_flow_state": "active_flow"})
    _, no_flow = fingerprint({"water_flow_state": "no_flow"})

    assert summer_features["comparison_basis"] == "contextual"
    assert summer_features["baseline_fallback_level"] == "exact_context"
    assert len({summer, winter, active_flow, no_flow}) == 4


def test_appliance_health_processor_requires_distinct_completed_dates() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        ApplianceHealthProcessor,
    )

    days, events = _appliance_health_history(19)
    context = _appliance_health_context(
        days=days[:17],
        events=events,
        learning=False,
    )
    policy = ConservativeAlertPolicy()
    processor = ApplianceHealthProcessor(
        alert_policy_for_circuit=lambda _circuit_id: policy,
        merge_gap_seconds_for_config=lambda _config: 60.0,
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )

    first = processor.process(_energy_sample(120.5), config, context)
    context.store_data.energy_usage_by_circuit["fridge"]["days"] = days[:18]
    second = processor.process(_energy_sample(120.5), config, context)
    context.store_data.energy_usage_by_circuit["fridge"]["days"] = days
    third = processor.process(_energy_sample(120.5), config, context)

    assert first.alerts == []
    assert second.alerts == []
    assert len(third.alerts) == 1
    alert = third.alerts[0]
    assert alert.feature == "efficiency_degradation"
    assert alert.value_metric == "energy_per_runtime_hour"
    assert alert.features["notification_type"] == "appliance_health_issue"
    assert alert.features["reference_day_count"] == 14
    assert alert.features["recent_day_count"] == 3
    assert third.notifications == third.alerts

    context.state.active_alerts_by_circuit["fridge"] = third.alerts
    unchanged = processor.process(_energy_sample(120.5), config, context)

    assert unchanged.alerts == []
    assert unchanged.preserved_alerts == third.alerts
    assert unchanged.notifications == []


def test_appliance_health_processor_deduplicates_same_completed_date() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        ApplianceHealthProcessor,
    )

    days, events = _appliance_health_history(17)
    context = _appliance_health_context(days=days, events=events, learning=False)
    processor = ApplianceHealthProcessor(
        alert_policy_for_circuit=lambda _circuit_id: ConservativeAlertPolicy(),
        merge_gap_seconds_for_config=lambda _config: 60.0,
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )

    results = [
        processor.process(_energy_sample(120.5), config, context) for _ in range(3)
    ]

    assert all(result.alerts == [] for result in results)
    assert {
        result.observations[0].observation_key
        for result in results
        if result.observations
    } == {"efficiency_degradation:2026-07-17"}


def test_appliance_health_observation_key_ignores_noncontributing_days() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        ApplianceHealthProcessor,
    )

    days, events = _appliance_health_history(17)
    idle_days = [
        {
            "date": f"2026-07-{day:02d}",
            "usage_kwh": 0.0,
            "complete": True,
            "baseline_eligible": True,
        }
        for day in (18, 19)
    ]
    context = _appliance_health_context(days=days, events=events, learning=False)
    processor = ApplianceHealthProcessor(
        alert_policy_for_circuit=lambda _circuit_id: ConservativeAlertPolicy(),
        merge_gap_seconds_for_config=lambda _config: 60.0,
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )

    first = processor.process(_energy_sample(120.5), config, context)
    context.store_data.energy_usage_by_circuit["fridge"]["days"] = days + idle_days[:1]
    second = processor.process(_energy_sample(120.5), config, context)
    context.store_data.energy_usage_by_circuit["fridge"]["days"] = days + idle_days
    third = processor.process(_energy_sample(120.5), config, context)

    observation_keys = [
        result.observations[0].observation_key
        for result in (first, second, third)
    ]
    assert observation_keys == [
        "efficiency_degradation:2026-07-17",
        "efficiency_degradation:2026-07-17",
        "efficiency_degradation:2026-07-17",
    ]
    assert first.alerts == second.alerts == third.alerts == []


def test_repeated_short_cycles_use_already_repeated_policy() -> None:
    from custom_components.circuitsetup_energy_analyzer.alerting import (
        ConservativeAlertPolicy,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        ApplianceHealthProcessor,
    )

    events: list[CircuitEvent] = []
    for day in range(1, 13):
        started_at = datetime(2026, 7, day, 10, 0, tzinfo=UTC)
        duration = timedelta(minutes=12 if day <= 9 else 2)
        events.extend(
            (
                CircuitEvent(started_at, "fridge", EventType.START),
                CircuitEvent(started_at + duration, "fridge", EventType.STOP),
            )
        )
    context = _appliance_health_context(days=[], events=events, learning=False)
    short_cycle_policy = ConservativeAlertPolicy(
        min_repeated=1,
        min_total_score=1.5,
        min_average_score=1.5,
    )
    processor = ApplianceHealthProcessor(
        alert_policy_for_circuit=lambda _circuit_id: ConservativeAlertPolicy(),
        short_cycle_alert_policy_for_circuit=lambda _circuit_id: short_cycle_policy,
        merge_gap_seconds_for_config=lambda _config: 60.0,
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )

    result = processor.process(_energy_sample(120.5), config, context)

    assert [alert.feature for alert in result.alerts] == ["repeated_short_cycle"]
    assert result.alerts[0].repeated_count == 3
    assert result.alerts[0].features["reference_session_count"] == 9
    assert result.alerts[0].features["recent_session_count"] == 3

    context.state.active_alerts_by_circuit["fridge"] = result.alerts
    unchanged = processor.process(_energy_sample(120.5), config, context)

    assert unchanged.alerts == []
    assert unchanged.preserved_alerts == result.alerts
    assert unchanged.notifications == []


@pytest.mark.asyncio
async def test_pipeline_applies_learning_transition_before_appliance_health() -> None:
    from custom_components.circuitsetup_energy_analyzer.managers import (
        processing_pipeline,
    )
    from custom_components.circuitsetup_energy_analyzer.managers.state_reducer import (
        StateReducer,
    )
    from custom_components.circuitsetup_energy_analyzer.processors import (
        ApplianceHealthProcessor,
        power_quality,
    )
    from custom_components.circuitsetup_energy_analyzer.processors.base import (
        FeatureResult,
        StateUpdate,
    )

    days, events = _appliance_health_history(17)
    context = _appliance_health_context(days=days, events=events, learning=True)
    state_reducer = StateReducer()

    class _Coordinator:
        async def async_apply_feature_result(
            self,
            result: FeatureResult,
        ) -> tuple[list[CircuitEvent], list[AlertEvidence]]:
            applied = state_reducer.apply_feature_result(
                context.state,
                context.store_data,
                result,
                alert_feedback=lambda alert: alert,
            )
            return applied.events, applied.active_alerts

    class _NoopProcessor:
        def __init__(self, result: FeatureResult | None = None) -> None:
            self.result = result or FeatureResult()

        def process(self, *args: object, **kwargs: object) -> FeatureResult:
            del args, kwargs
            return self.result

    pipeline = processing_pipeline.ProcessingPipeline(_Coordinator())
    pipeline.configure_processors(
        event_processor=_NoopProcessor(),
        power_quality_processor=_NoopProcessor(power_quality.PowerQualityResult()),
        energy_usage_processor=_NoopProcessor(
            FeatureResult(
                state_updates=[
                    StateUpdate(("learning_by_circuit", "fridge"), False)
                ]
            )
        ),
        energy_goal_processor=_NoopProcessor(),
        run_cycle_processor=_NoopProcessor(),
        appliance_health_processor=ApplianceHealthProcessor(
            alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
            merge_gap_seconds_for_config=lambda _config: 60.0,
        ),
        activity_alert_processor=_NoopProcessor(),
        billing_cycle_processor=_NoopProcessor(),
        cost_processor=_NoopProcessor(),
        demand_processor=_NoopProcessor(),
        capacity_processor=_NoopProcessor(),
        leg_imbalance_processor=_NoopProcessor(),
        metric_consistency_processor=_NoopProcessor(),
        standby_processor=_NoopProcessor(),
        mains_balance_processor=_NoopProcessor(),
        solar_flow_processor=_NoopProcessor(),
        utility_comparison_processor=_NoopProcessor(),
        clear_power_quality_state=lambda circuit_id: None,
        clear_standby_state=lambda circuit_id: None,
        sync_setup_health_repairs=lambda circuit_id: None,
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )

    _, alerts = await pipeline.async_process_circuit(
        config,
        NormalizedCircuitSample(
            timestamp=context.now,
            circuit_id="fridge",
            real_power=180.0,
        ),
        context,
    )

    assert context.state.learning_by_circuit["fridge"] is False
    assert context.state.appliance_health_status_by_circuit["fridge"] == (
        "possible_degradation"
    )
    assert [alert.feature for alert in alerts] == ["efficiency_degradation"]
