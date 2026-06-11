from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.activity_alerts import (
    ActivityAlertSettings,
)
from custom_components.circuitsetup_energy_analyzer.alerting import Observation
from custom_components.circuitsetup_energy_analyzer.billing import BillingCycleSettings
from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
from custom_components.circuitsetup_energy_analyzer.cost import CostSettings
from custom_components.circuitsetup_energy_analyzer.demand import DemandSettings
from custom_components.circuitsetup_energy_analyzer.goals import EnergyGoalSettings
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    CircuitSample,
    EventType,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData
from custom_components.circuitsetup_energy_analyzer.usage import EnergyUsageSettings


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
