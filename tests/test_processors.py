from __future__ import annotations

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
from custom_components.circuitsetup_energy_analyzer.usage import EnergyUsageSettings
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

    assert len(first.events) == 1
    assert len(first.state_updates) == 1
    assert second.events == []
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

    async def fake_notify(alert_to_notify: AlertEvidence) -> None:
        notifications.append(alert_to_notify)

    coordinator._notify_alert = fake_notify

    applied_events, applied_alerts = await coordinator._apply_feature_result(
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

    await coordinator._apply_feature_result(
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


def test_event_processor_returns_events() -> None:
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
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    processor = CircuitEventProcessor()

    first = processor.process(_sample(0, 5.0), config, context)
    second = processor.process(_sample(10, 210.0), config, context)

    assert first.events == []
    assert [event.event_type for event in second.events] == [EventType.START]
    assert second.store_dirty is True


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
    assert len(result.state_updates) == 3
    assert len(result.alerts) == 1
    assert result.notifications == result.alerts
    assert policy.observations[0].feature == "daily_energy_usage_spike"
    assert policy.observations[0].observed_value == 12.9
    assert policy.observations[0].baseline_value == 12.5
    assert "Kitchen Fridge used 12.9 kWh today" in result.alerts[0].message

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("daily_energy_usage_by_circuit", "fridge")] == 12.9
    assert updates[("energy_usage_share_by_circuit", "fridge")] == 25.8
    evidence = updates[("energy_usage_evidence_by_circuit", "fridge")]
    assert evidence["status"] == "over_threshold"
    assert evidence["daily_usage_share_percent"] == 25.8
    assert store_data.energy_usage_by_circuit["fridge"]["last_energy_kwh"] == 112.9


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
    assert len(result.state_updates) == 5

    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("cost_current_rate_by_circuit", "fridge")] == 0.2
    assert updates[("cost_cycle_by_circuit", "fridge")] == 3.0
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
    assert context.store_data.demand_by_circuit["ev"]["capacity_current_samples"] == [
        {
            "timestamp": now.isoformat(),
            "current_amps": 28.0,
        }
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
    assert result.store_dirty is False
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
    }


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
        store_data=FeatureStoreData(),
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
        assert settings.min_samples == 3

    processor = processors.StandbyProcessor(
        settings_for_config=lambda _config, _circuit_id: StandbySettings(
            min_samples=3,
        ),
        alert_policy_for_circuit=lambda _circuit_id: _CaptureAlertPolicy(),
        seed_demo_history=seed_demo_history,
    )

    result = processor.process(_sample(0, 4.0), config, context)

    assert seeded == ["office"]
    assert result.store_dirty is False
    assert result.alerts == []
    updates = {update.path: update.value for update in result.state_updates}
    assert updates[("always_on_power_w_by_circuit", "office")] == 0.0
    assert updates[("standby_status_by_circuit", "office")] == "learning"
    assert updates[("standby_evidence_by_circuit", "office")] == {
        "always_on_power_w": 0.0,
        "current_power_w": 4.0,
        "standby_threshold_w": 8.0,
        "sample_count": 1,
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
    )

    result = await processor.process(config, context)

    assert result.store_dirty is False
    assert len(result.state_updates) == 4
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
        "measured_kwh": 135.0,
        "difference_kwh": 15.0,
        "difference_percent": 12.5,
        "absolute_difference_percent": 12.5,
        "tolerance_percent": 10.0,
    }
