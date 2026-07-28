from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

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
from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
from custom_components.circuitsetup_energy_analyzer.cost import CostSettings
from custom_components.circuitsetup_energy_analyzer.demand import DemandSettings
from custom_components.circuitsetup_energy_analyzer.goals import EnergyGoalSettings
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


class _CaptureObservationOnlyPolicy:
    min_average_score = 1.5

    def __init__(self) -> None:
        self.observations: list[Observation] = []

    def observe(self, observation: Observation) -> None:
        self.observations.append(observation)


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
        activity_alert_processor=_Processor(),
        billing_cycle_processor=_Processor(),
        cost_processor=_Processor(),
        demand_processor=_Processor(),
        capacity_processor=_Processor(),
        leg_imbalance_processor=_Processor(),
        metric_consistency_processor=_Processor(),
        standby_processor=_Processor(),
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


def test_demand_processor_suppresses_context_explained_monthly_peak() -> None:
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
            peak_rank_count=3,
            peak_warning_ratio=0.9,
        ),
        alert_policy_for_circuit=lambda _circuit_id: policy,
        retention_days_for_circuit=lambda _circuit_id: 45,
    )

    result = processor.process(_sample(0, 3700.0), config, context)

    assert result.store_dirty is True
    assert result.alerts == []
    assert policy.observations == []
    updates = {update.path: update.value for update in result.state_updates}
    evidence = updates[("demand_evidence_by_circuit", "ev")]
    assert evidence["status"] == "context_explained"
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
        state="42",
        unit="A",
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
            "assignment_id": "masking",
            "signature_fingerprints": ["masking-signature"],
            "conversion_state": "direct_meter",
            "keep_assignment_for_masking": True,
        },
    ]

    assert _nilm_session_specs([], assignments) == [
        ("masking-signature", "masking")
    ]


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
            timestamp=now + timedelta(seconds=index * 30),
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
        for index, watts in enumerate((100, 420, 110, 430, 115, 425), start=1)
    ]

    assert any(result.store_dirty for result in results)
    assert isinstance(processor.detectors["mains"], NilmEdgeDetector)
    assert processor.total_events_by_circuit["mains"] == 5
    assert len(processor.unmatched_edges_by_circuit["mains"]) == 5
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


def test_nilm_sample_processor_matches_buffered_edge_after_delayed_known_event(
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

    processor.process(sample(0, 100.0), config, context, events=())
    processor.process(sample(1, 420.0), config, context, events=())
    result = processor.process(
        sample(2, 420.0),
        config,
        context,
        events=(
            CircuitEvent(
                timestamp=now + timedelta(seconds=30),
                circuit_id="fridge",
                event_type=EventType.START,
                features={"startup_power_w": 320.0},
            ),
        ),
    )

    assert len(observed_matches) == 1
    assert observed_matches[0].known_circuit_id == "fridge"
    assert observed_matches[0].edge.timestamp == now + timedelta(seconds=30)
    assert processor.total_events_by_circuit["mains"] == 1
    assert processor.unmatched_edges_by_circuit["mains"] == []
    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("nilm_unmatched_load_percentage_by_circuit", "mains")] == 0.0


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
        appliance_profile=ApplianceProfile.MIXED,
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
        appliance_profile=ApplianceProfile.MIXED,
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


def test_power_quality_processor_updates_state_and_returns_alert() -> None:
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
