from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_CIRCUITS,
    DOMAIN,
)
from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
    Severity,
)


def test_sensor_helpers_return_diagnostic_values_and_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        alert_evidence_value,
        anomaly_score_value,
        apparent_power_drift_value,
        balance_power_value,
        balance_status_value,
        current_demand_value,
        daily_energy_usage_value,
        data_quality_checklist_value,
        demand_limit_usage_value,
        demand_status_value,
        energy_usage_share_value,
        energy_usage_status_value,
        health_summary_value,
        last_event_value,
        learning_progress_value,
        monitored_coverage_value,
        monitored_power_value,
        nilm_signature_count_value,
        nilm_unmatched_load_percentage_value,
        peak_demand_value,
        power_factor_drift_value,
        power_quality_evidence_value,
        power_quality_score_value,
        reactive_power_drift_value,
        readiness_value,
        sensitivity_value,
    )

    event = CircuitEvent(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="fridge",
        event_type=EventType.START,
        severity=Severity.INFO,
        features={"startup_power_w": 512.0},
    )
    state = AnalyzerState(
        last_event_by_circuit={"fridge": event},
        anomaly_score_by_circuit={"fridge": 0.42},
        power_quality_score_by_circuit={"fridge": 3.25},
        power_quality_evidence_by_circuit={
            "fridge": "Possible issue: reactive power changed"
        },
        reactive_power_drift_by_circuit={"fridge": 0.38},
        apparent_power_drift_by_circuit={"fridge": 0.12},
        power_factor_drift_by_circuit={"fridge": 0.07},
        nilm_signature_count_by_circuit={"fridge": 3},
        nilm_unmatched_load_percentage_by_circuit={"fridge": 17.5},
        health_status_by_circuit={"fridge": "possible_issue"},
        health_summary_by_circuit={"fridge": "Possible issue"},
        readiness_by_circuit={
            "fridge": {
                "health_status": "possible_issue",
                "health_summary": "Possible issue",
            }
        },
        learning_progress_by_circuit={
            "fridge": {
                "learned_feature_count": 5,
                "pending_feature_samples": {"reactive_power": 3},
                "alert_ready": False,
            },
            "ready": {
                "learned_feature_count": 1,
                "pending_feature_samples": {},
                "alert_ready": True,
            },
        },
        data_quality_checklist_by_circuit={
            "fridge": {
                "quality_issues": [],
                "required_sensors_present": True,
            },
            "well_pump": {
                "quality_issues": ["missing_required_sensor"],
                "required_sensors_present": False,
            },
        },
        alert_evidence_by_circuit={"fridge": {"feature": "reactive_power"}},
        sensitivity_by_circuit={"fridge": "quiet"},
        daily_energy_usage_by_circuit={"fridge": 12.9},
        energy_usage_share_by_circuit={"fridge": 25.8},
        energy_usage_evidence_by_circuit={
            "fridge": {"status": "over_threshold", "threshold_kwh": 12.5}
        },
        current_demand_w_by_circuit={"fridge": 2400.0},
        peak_demand_w_by_circuit={"fridge": 3200.0},
        demand_limit_usage_by_circuit={"fridge": 80.0},
        demand_evidence_by_circuit={
            "fridge": {"status": "tracking", "demand_limit_w": 4000.0}
        },
        balance_power_w_by_circuit={"fridge": 2300.0},
        monitored_power_w_by_circuit={"fridge": 2700.0},
        monitored_coverage_percent_by_circuit={"fridge": 54.0},
        balance_status_by_circuit={"fridge": "tracking"},
        balance_evidence_by_circuit={
            "fridge": {"status": "tracking", "balance_power_w": 2300.0}
        },
    )

    assert anomaly_score_value(state, "fridge") == 0.42
    assert last_event_value(state, "fridge") == "start"
    assert power_quality_score_value(state, "fridge") == 3.25
    assert (
        power_quality_evidence_value(state, "fridge")
        == "Possible issue: reactive power changed"
    )
    assert reactive_power_drift_value(state, "fridge") == 0.38
    assert apparent_power_drift_value(state, "fridge") == 0.12
    assert power_factor_drift_value(state, "fridge") == 0.07
    assert nilm_signature_count_value(state, "fridge") == 3
    assert nilm_unmatched_load_percentage_value(state, "fridge") == 17.5
    assert health_summary_value(state, "fridge") == "Possible issue"
    assert readiness_value(state, "fridge") == "possible_issue"
    assert learning_progress_value(state, "fridge") == 62.5
    assert learning_progress_value(state, "ready") == 100.0
    assert data_quality_checklist_value(state, "fridge") == "ok"
    assert data_quality_checklist_value(state, "well_pump") == "problem"
    assert alert_evidence_value(state, "fridge") == "reactive_power"
    assert sensitivity_value(state, "fridge") == "quiet"
    assert daily_energy_usage_value(state, "fridge") == 12.9
    assert energy_usage_share_value(state, "fridge") == 25.8
    assert energy_usage_status_value(state, "fridge") == "over_threshold"
    assert current_demand_value(state, "fridge") == 2400.0
    assert peak_demand_value(state, "fridge") == 3200.0
    assert demand_limit_usage_value(state, "fridge") == 80.0
    assert demand_status_value(state, "fridge") == "tracking"
    assert balance_power_value(state, "fridge") == 2300.0
    assert monitored_power_value(state, "fridge") == 2700.0
    assert monitored_coverage_value(state, "fridge") == 54.0
    assert balance_status_value(state, "fridge") == "tracking"

    assert anomaly_score_value(state, "unknown") == 0.0
    assert last_event_value(state, "unknown") is None
    assert power_quality_score_value(state, "unknown") == 0.0
    assert power_quality_evidence_value(state, "unknown") == ""
    assert reactive_power_drift_value(state, "unknown") == 0.0
    assert apparent_power_drift_value(state, "unknown") == 0.0
    assert power_factor_drift_value(state, "unknown") == 0.0
    assert nilm_signature_count_value(state, "unknown") == 0
    assert nilm_unmatched_load_percentage_value(state, "unknown") == 0.0
    assert health_summary_value(state, "unknown") == "Ready"
    assert readiness_value(state, "unknown") == "ready"
    assert learning_progress_value(state, "unknown") == 0.0
    assert data_quality_checklist_value(state, "unknown") == "problem"
    assert alert_evidence_value(state, "unknown") == ""
    assert sensitivity_value(state, "unknown") == "balanced"
    assert daily_energy_usage_value(state, "unknown") == 0.0
    assert energy_usage_share_value(state, "unknown") == 0.0
    assert energy_usage_status_value(state, "unknown") == "learning"
    assert current_demand_value(state, "unknown") == 0.0
    assert peak_demand_value(state, "unknown") == 0.0
    assert demand_limit_usage_value(state, "unknown") == 0.0
    assert demand_status_value(state, "unknown") == "unconfigured"
    assert balance_power_value(state, "unknown") == 0.0
    assert monitored_power_value(state, "unknown") == 0.0
    assert monitored_coverage_value(state, "unknown") == 0.0
    assert balance_status_value(state, "unknown") == "missing_mains"


def test_binary_sensor_helpers_return_diagnostic_values_and_defaults() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        has_data_quality_problem,
        is_learning,
        is_maintenance_active,
    )

    state = AnalyzerState(
        learning_by_circuit={"fridge": False},
        data_quality_by_circuit={
            "fridge": "",
            "well_pump": "missing current sample",
        },
        maintenance_by_circuit={"fridge": {"active": True}},
    )

    assert is_learning(state, "fridge") is False
    assert is_learning(state, "unknown") is True
    assert has_data_quality_problem(state, "fridge") is False
    assert has_data_quality_problem(state, "well_pump") is True
    assert has_data_quality_problem(state, "unknown") is False
    assert is_maintenance_active(state, "fridge") is True
    assert is_maintenance_active(state, "unknown") is False


def test_sensor_extra_attributes_return_runtime_diagnostics() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import (
        SENSOR_DESCRIPTIONS,
        CircuitAnalyzerSensor,
    )

    readiness = {
        "health_status": "possible_issue",
        "health_summary": "Possible issue",
    }
    progress = {
        "learned_feature_count": 5,
        "pending_feature_samples": {"reactive_power": 3},
    }
    checklist = {"quality_issues": [], "required_sensors_present": True}
    evidence = {"feature": "reactive_power", "change_ratio": 0.42}
    energy_evidence = {
        "status": "tracking",
        "daily_usage_kwh": 8.2,
        "baseline_total_kwh": 50.0,
    }
    demand_evidence = {
        "status": "over_limit",
        "current_demand_w": 2400.0,
        "demand_limit_w": 2000.0,
    }
    balance_evidence = {
        "status": "tracking",
        "balance_power_w": 2300.0,
        "monitored_coverage_percent": 54.0,
    }
    state = AnalyzerState(
        readiness_by_circuit={"fridge": readiness},
        learning_progress_by_circuit={"fridge": progress},
        data_quality_checklist_by_circuit={"fridge": checklist},
        alert_evidence_by_circuit={"fridge": evidence},
        sensitivity_by_circuit={"fridge": "quiet"},
        energy_usage_evidence_by_circuit={"fridge": energy_evidence},
        demand_evidence_by_circuit={"fridge": demand_evidence},
        balance_evidence_by_circuit={"fridge": balance_evidence},
    )
    coordinator = SimpleNamespace(data=state)
    circuit = SimpleNamespace(circuit_id="fridge", name="Kitchen Fridge")
    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}

    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["readiness"],
    ).extra_state_attributes == readiness
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["learning_progress"],
    ).extra_state_attributes == progress
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["data_quality_checklist"],
    ).extra_state_attributes == checklist
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["alert_evidence"],
    ).extra_state_attributes == evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["sensitivity"],
    ).extra_state_attributes == {"preset": "quiet"}
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["daily_energy_usage"],
    ).extra_state_attributes == energy_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["energy_usage_share"],
    ).extra_state_attributes == energy_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["energy_usage_status"],
    ).extra_state_attributes == energy_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["current_demand"],
    ).extra_state_attributes == demand_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["peak_demand"],
    ).extra_state_attributes == demand_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["demand_limit_usage"],
    ).extra_state_attributes == demand_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["demand_status"],
    ).extra_state_attributes == demand_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["balance_power"],
    ).extra_state_attributes == balance_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["monitored_power"],
    ).extra_state_attributes == balance_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["monitored_coverage"],
    ).extra_state_attributes == balance_evidence
    assert CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["balance_status"],
    ).extra_state_attributes == balance_evidence


@pytest.mark.asyncio
async def test_sensor_setup_entry_adds_diagnostic_entities_without_ha() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    coordinator = SimpleNamespace(data=AnalyzerState())
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={CONF_CIRCUITS: [circuit]})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    assert [entity.name for entity in added_entities] == [
        "Kitchen Fridge Anomaly Score",
        "Kitchen Fridge Last Event",
        "Kitchen Fridge Health Summary",
        "Kitchen Fridge Readiness",
        "Kitchen Fridge Learning Progress",
        "Kitchen Fridge Data Quality Checklist",
        "Kitchen Fridge Alert Evidence",
        "Kitchen Fridge Sensitivity",
        "Kitchen Fridge Power Quality Score",
        "Kitchen Fridge Power Quality Evidence",
        "Kitchen Fridge Reactive Power Drift",
        "Kitchen Fridge Apparent Power Drift",
        "Kitchen Fridge Power Factor Drift",
        "Kitchen Fridge NILM Discovered Signatures",
        "Kitchen Fridge NILM Unmatched Load Percentage",
        "Kitchen Fridge Daily Energy Usage",
        "Kitchen Fridge Energy Usage Share",
        "Kitchen Fridge Energy Usage Status",
        "Kitchen Fridge Current Demand",
        "Kitchen Fridge Peak Demand",
        "Kitchen Fridge Demand Limit Usage",
        "Kitchen Fridge Demand Status",
        "Kitchen Fridge Balance Power",
        "Kitchen Fridge Monitored Power",
        "Kitchen Fridge Monitored Coverage",
        "Kitchen Fridge Balance Status",
    ]
    assert [entity.unique_id for entity in added_entities] == [
        "entry-1_fridge_anomaly_score",
        "entry-1_fridge_last_event",
        "entry-1_fridge_health_summary",
        "entry-1_fridge_readiness",
        "entry-1_fridge_learning_progress",
        "entry-1_fridge_data_quality_checklist",
        "entry-1_fridge_alert_evidence",
        "entry-1_fridge_sensitivity",
        "entry-1_fridge_power_quality_score",
        "entry-1_fridge_power_quality_evidence",
        "entry-1_fridge_reactive_power_drift",
        "entry-1_fridge_apparent_power_drift",
        "entry-1_fridge_power_factor_drift",
        "entry-1_fridge_nilm_signature_count",
        "entry-1_fridge_nilm_unmatched_load_percentage",
        "entry-1_fridge_daily_energy_usage",
        "entry-1_fridge_energy_usage_share",
        "entry-1_fridge_energy_usage_status",
        "entry-1_fridge_current_demand",
        "entry-1_fridge_peak_demand",
        "entry-1_fridge_demand_limit_usage",
        "entry-1_fridge_demand_status",
        "entry-1_fridge_balance_power",
        "entry-1_fridge_monitored_power",
        "entry-1_fridge_monitored_coverage",
        "entry-1_fridge_balance_status",
    ]
    assert added_entities[0].device_info["identifiers"] == {
        (DOMAIN, "entry-1_fridge")
    }
    assert not isinstance(added_entities[0].state, AnalyzerState)
    assert added_entities[0].coordinator_state is coordinator.data


@pytest.mark.asyncio
async def test_sensor_setup_entry_uses_runtime_synthetic_mains() -> None:
    from custom_components.circuitsetup_energy_analyzer.sensor import async_setup_entry

    circuit = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    coordinator = SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,))
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    assert [entity.circuit_id for entity in added_entities] == [
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
    ]


@pytest.mark.asyncio
async def test_binary_sensor_setup_entry_adds_diagnostic_entities_without_ha() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        async_setup_entry,
    )

    circuit = {
        "circuit_id": "well_pump",
        "name": "Well Pump",
    }
    coordinator = SimpleNamespace(data=AnalyzerState())
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={CONF_CIRCUITS: [circuit]})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    assert [entity.name for entity in added_entities] == [
        "Well Pump Learning",
        "Well Pump Data Quality Problem",
        "Well Pump Maintenance",
    ]
    assert [entity.unique_id for entity in added_entities] == [
        "entry-1_well_pump_learning",
        "entry-1_well_pump_data_quality_problem",
        "entry-1_well_pump_maintenance",
    ]


@pytest.mark.asyncio
async def test_binary_sensor_setup_entry_uses_runtime_synthetic_mains() -> None:
    from custom_components.circuitsetup_energy_analyzer.binary_sensor import (
        async_setup_entry,
    )

    circuit = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    coordinator = SimpleNamespace(data=AnalyzerState(), circuit_configs=(circuit,))
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    entry = SimpleNamespace(entry_id="entry-1", data={})
    added_entities = []

    await async_setup_entry(hass, entry, added_entities.extend)

    assert [entity.circuit_id for entity in added_entities] == [
        "mains",
        "mains",
        "mains",
    ]
