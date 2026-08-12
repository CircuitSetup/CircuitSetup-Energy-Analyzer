from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlparse

import pytest

from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
    SensorRef,
    SensorRole,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
from custom_components.circuitsetup_energy_analyzer.sensor import (
    activity_summary_attributes,
    activity_summary_value,
    electrical_health_attributes,
    energy_summary_attributes,
    energy_summary_value,
    health_summary_attributes,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData


def _config(
    circuit_id: str = "fridge",
    *,
    name: str = "Kitchen Fridge",
    profile: ApplianceProfile = ApplianceProfile.REFRIGERATOR,
    mode: CircuitMode = CircuitMode.SINGLE_PHASE,
) -> CircuitConfig:
    return CircuitConfig(
        circuit_id=circuit_id,
        name=name,
        appliance_profile=profile,
        mode=mode,
        sensors=(
            SensorRef(f"sensor.{circuit_id}_power", SensorRole.REAL_POWER),
            SensorRef(f"sensor.{circuit_id}_current", SensorRole.CURRENT),
            SensorRef(f"sensor.{circuit_id}_apparent_power", SensorRole.APPARENT_POWER),
            SensorRef(f"sensor.{circuit_id}_reactive_power", SensorRole.REACTIVE_POWER),
            SensorRef(f"sensor.{circuit_id}_power_factor", SensorRole.POWER_FACTOR),
            SensorRef(f"sensor.{circuit_id}_energy", SensorRole.ENERGY),
        ),
    )


def _direct_state() -> AnalyzerState:
    state = AnalyzerState()
    state.learning_by_circuit["fridge"] = False
    state.health_summary_by_circuit["fridge"] = "Ready"
    state.data_quality_checklist_by_circuit["fridge"] = {
        "required_sensors_present": True,
        "numeric_states_valid": True,
        "source_data_fresh": True,
        "metric_roles_present": ["energy", "real_power"],
        "missing_required_metric_roles": [],
    }
    state.learning_progress_by_circuit["fridge"] = {
        "alert_ready": True,
        "baseline_age_days": 14,
        "cycle_count": 18,
        "learned_feature_count": 3,
        "pending_feature_samples": 0,
    }
    state.latest_real_power_w_by_circuit["fridge"] = 128.4
    state.run_cycle_status_by_circuit["fridge"] = "running"
    state.run_cycle_count_by_circuit["fridge"] = 14
    state.run_cycle_runtime_seconds_by_circuit["fridge"] = 7200.0
    state.daily_energy_usage_by_circuit["fridge"] = 1.82
    state.cost_current_rate_by_circuit["fridge"] = 0.25
    state.energy_usage_evidence_by_circuit["fridge"] = {"status": "normal"}
    state.metric_consistency_status_by_circuit["fridge"] = "consistent"
    state.leg_imbalance_status_by_circuit["fridge"] = "balanced"
    state.appliance_health_status_by_circuit["fridge"] = "watch"
    state.appliance_health_evidence_by_circuit["fridge"] = {
        "status": "watch",
        "feature": "efficiency_degradation",
        "recent_median": 0.52,
        "reference_median": 0.4,
    }
    return state


def _direct_coordinator() -> SimpleNamespace:
    state = _direct_state()
    state.active_alerts_by_circuit["fridge"] = [
        AlertEvidence(
            timestamp=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
            circuit_id="fridge",
            severity=Severity.WARNING,
            message="Kitchen Fridge is using more energy than usual.",
            feature="daily_energy",
            observed_value=1.82,
            baseline_value=1.2,
            change_ratio=0.52,
            repeated_count=2,
        )
    ]
    return SimpleNamespace(
        circuit_configs=(_config(),),
        state=state,
        store_data=FeatureStoreData(),
        entry_id="entry-1",
    )


def _nilm_coordinator() -> SimpleNamespace:
    mains = _config(
        "mains",
        name="Mains NILM",
        profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
    )
    assignment = {
        "assignment_id": "assignment-dishwasher",
        "appliance_id": "dishwasher",
        "display_name": "Dishwasher",
        "appliance_profile": "dishwasher",
        "mains_circuit_id": "mains",
        "signature_fingerprints": ["signature_1"],
        "session_ids": [],
        "label_interval_ids": [],
        "lifecycle_state": "needs_validation",
        "confidence": 0.72,
        "created_device": True,
        "publish_entities": True,
    }
    state = AnalyzerState()
    state.cost_current_rate_by_circuit["mains"] = 0.2
    return SimpleNamespace(
        circuit_configs=(mains,),
        state=state,
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mains": [assignment]},
            nilm_signatures={"mains": [{
                "signature_id": "signature_1",
                "direction": "on",
                "median_delta_w": 820.0,
            }]},
        ),
        _nilm_unmatched_edges={
            "mains": [
                NilmEdge(
                    timestamp=datetime(2026, 6, 30, 8, 0, tzinfo=UTC),
                    delta_w=820.0,
                    delta_var=0.0,
                    delta_va=820.0,
                    delta_pf=0.0,
                    direction="on",
                ),
                NilmEdge(
                    timestamp=datetime(2026, 6, 30, 9, 0, tzinfo=UTC),
                    delta_w=-815.0,
                    delta_var=0.0,
                    delta_va=-815.0,
                    delta_pf=0.0,
                    direction="off",
                ),
            ]
        },
        entry_id="entry-1",
    )


def test_nilm_assignment_without_signature_metadata_has_no_derived_usage() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm_virtual import (
        nilm_virtual_appliance_states,
    )

    coordinator = _nilm_coordinator()
    coordinator.store_data.nilm_signatures = {}

    state = nilm_virtual_appliance_states(coordinator)[0]

    assert state.estimated_energy_kwh_today == 0.0
    assert state.latest_session_id is None


def test_nilm_assignment_combines_stored_and_newly_derived_sessions() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm_virtual import (
        nilm_virtual_appliance_states,
    )

    coordinator = _nilm_coordinator()
    coordinator.store_data.nilm_session_history_by_circuit = {
        "mains": [{
            "session_id": "stored-session",
            "assignment_id": "assignment-dishwasher",
            "signature_fingerprint": "signature_1",
            "start": "2026-06-29T08:00:00+00:00",
            "end": "2026-06-29T08:30:00+00:00",
            "duration_seconds": 1800.0,
            "median_power_w": 820.0,
            "estimated_energy_kwh": 0.41,
            "confidence": 0.91,
        }]
    }

    sessions = nilm_virtual_appliance_states(coordinator)[0].sessions

    assert len(sessions) == 2
    assert {session["start"] for session in sessions} == {
        "2026-06-29T08:00:00+00:00",
        "2026-06-30T08:00:00+00:00",
    }


def test_nilm_virtual_state_excludes_assigned_stop_boundary_ambiguity() -> None:
    """Ambiguous completed evidence cannot become an appliance alert."""
    from custom_components.circuitsetup_energy_analyzer.nilm_virtual import (
        nilm_virtual_appliance_alerts,
        published_nilm_virtual_appliance_states,
    )

    coordinator = _nilm_coordinator()
    assignment = coordinator.store_data.nilm_appliance_assignments_by_circuit[
        "mains"
    ][0]
    assignment.update({"lifecycle_state": "published", "confidence": 0.91})
    coordinator._nilm_unmatched_edges = {"mains": []}
    coordinator.store_data.nilm_session_history_by_circuit = {
        "mains": [{
            **_nilm_session(
                "ambiguous-stop-boundary",
                start=datetime(2026, 6, 30, 8, 0, tzinfo=UTC),
                end=datetime(2026, 6, 30, 8, 30, tzinfo=UTC),
                duration_seconds=1800.0,
                energy_kwh=0.41,
            ),
            "ambiguous": True,
            "ambiguity_candidates": [{
                "candidate_id": "stop-boundary-early",
                "candidate_kind": "stop_boundary",
                "edge_id": "off-early",
                "reason_code": "stop_boundary_conflict",
            }],
        }]
    }

    state = published_nilm_virtual_appliance_states(coordinator)[0]

    assert state.sessions == ()
    assert state.latest_session_id is None
    assert state.estimated_energy_kwh_today == 0.0
    assert nilm_virtual_appliance_alerts(
        coordinator,
        now=datetime(2026, 6, 30, 10, 0, tzinfo=UTC),
    ) == ()


def _nilm_session(
    session_id: str,
    *,
    start: datetime,
    end: datetime | None,
    duration_seconds: float | None,
    assignment_id: str = "assignment-dishwasher",
    energy_kwh: float = 0.2,
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "assignment_id": assignment_id,
        "signature_fingerprint": "signature_1",
        "start": start.isoformat(),
        "end": end.isoformat() if end else None,
        "duration_seconds": duration_seconds,
        "median_power_w": 820.0,
        "estimated_energy_kwh": energy_kwh,
        "confidence": 0.91,
    }


def test_existing_summary_fields_feed_appliance_story() -> None:
    state = _direct_state()

    assert activity_summary_value(state, "fridge") == "Running"
    assert activity_summary_attributes(state, "fridge") == {
        "is_running": True,
        "run_cycle_status": "running",
        "standby_status": "learning",
        "run_cycle_count": 14,
        "run_cycle_runtime_seconds": 7200.0,
        "duty_cycle_percent": 0.0,
        "summary_explanation": "The appliance is currently active.",
    }
    assert energy_summary_value(state, "fridge") == "Normal"
    assert energy_summary_attributes(state, "fridge")["daily_energy_usage_kwh"] == 1.82
    assert (
        electrical_health_attributes(state, "fridge")["what_to_check_first"]
        == "No electrical check is needed right now."
    )
    assert health_summary_attributes(state, "fridge")["next_step"] == (
        "No action needed"
    )
    assert health_summary_attributes(state, "fridge")["appliance_health_status"] == (
        "watch"
    )
    assert health_summary_attributes(state, "fridge")["appliance_health_evidence"] == {
        "status": "watch",
        "feature": "efficiency_degradation",
        "recent_median": 0.52,
        "reference_median": 0.4,
    }


def test_direct_appliance_detail_payload_uses_existing_summary_state() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    payload = appliance_detail_payload([_direct_coordinator()], circuit_id="fridge")

    assert payload["status"] == "ok"
    assert payload["history"]["default_hours"] == 24
    detail = payload["detail"]
    assert detail["circuit_id"] == "fridge"
    assert detail["display_name"] == "Kitchen Fridge"
    assert detail["appliance_profile"] == "refrigerator"
    assert detail["source_type"] == "direct_meter"
    assert detail["confidence"] is None
    assert detail["activity_state"] == "Running"
    assert detail["health_state"] == "Ready"
    assert "electrical_state" not in detail
    assert detail["energy_state"] == "Normal"
    assert detail["current_power_w"] == 128.4
    assert detail["daily_energy_kwh"] == 1.82
    assert detail["runtime_today_seconds"] == 7200.0
    assert detail["run_count_today"] == 14
    assert detail["cost_today"] is None
    assert detail["source_quality"] == {
        "status": "fresh",
        "label": "Fresh",
        "available_source_count": 2,
        "configured_source_count": 6,
        "stale_source_count": 0,
        "missing_required_roles": [],
    }
    assert detail["learning_readiness"]["status"] == "ready"
    assert detail["learning_readiness"]["label"] == "Ready"
    assert detail["learning_readiness"]["days_complete"] == 7
    assert detail["learning_readiness"]["days_required"] == 7
    assert detail["next_step"] == "Review alert evidence"
    assert detail["what_to_check_first"] == ["No electrical check is needed right now."]
    assert detail["evidence_path"] == (
        "/circuitsetup-energy-analyzer-evidence?circuit_id=fridge"
    )
    assert detail["appliance_health"] == {
        "status": "watch",
        "feature": "efficiency_degradation",
        "recent_median": 0.52,
        "reference_median": 0.4,
    }
    assert "hvac_efficiency" not in detail
    assert "water_flow_context" not in detail
    assert detail["active_alerts"][0]["feature"] == "daily_energy"
    assert payload["actions"]["open_evidence"]["path"] == detail["evidence_path"]
    assert payload["actions"]["relearn_baseline"]["data"] == {"circuit_id": "fridge"}


def test_sump_pump_detail_exposes_history_driver_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _direct_coordinator()
    coordinator.circuit_configs = (
        _config(
            "sump",
            name="Basement Sump Pump",
            profile=ApplianceProfile.SUMP_PUMP,
        ),
        _config(
            "compressor",
            name="Air Conditioner",
            profile=ApplianceProfile.HVAC_COMPRESSOR,
        ),
        _config(
            "blower",
            name="Air Handler",
            profile=ApplianceProfile.HVAC_BLOWER,
        ),
        _config("fridge"),
    )
    coordinator.state.rain_pump_context_by_circuit["sump"] = {
        "rain_sensor_entity": "binary_sensor.rain",
        "rain_intensity_entity": "sensor.rain_rate",
        "outdoor_humidity_source_entity": "weather.home",
        "rain_response_window_minutes": 120,
        "hvac_compressor_circuits": ["compressor"],
    }
    coordinator.hass = SimpleNamespace(
        entity_registry=SimpleNamespace(
            entities={
                "sensor.renamed_sump_activity": SimpleNamespace(
                    entity_id="sensor.renamed_sump_activity",
                    unique_id="entry-1_sump_activity_summary",
                ),
                "sensor.renamed_compressor_activity": SimpleNamespace(
                    entity_id="sensor.renamed_compressor_activity",
                    unique_id="entry-1_compressor_activity_summary",
                ),
                "sensor.renamed_blower_activity": SimpleNamespace(
                    entity_id="sensor.renamed_blower_activity",
                    unique_id="entry-1_blower_activity_summary",
                ),
            }
        )
    )

    payload = appliance_detail_payload([coordinator], circuit_id="sump")

    assert payload["history"]["default_hours"] == 720
    assert payload["detail"]["sump_driver_context"] == {
        "default_hours": 720,
        "period_hours": [24, 168, 720],
        "rain_response_window_minutes": 120,
        "pump_activity_entity_id": "sensor.renamed_sump_activity",
        "compressor_activity_entity_ids": ["sensor.renamed_compressor_activity"],
        "blower_activity_entity_ids": ["sensor.renamed_blower_activity"],
        "rain_intensity_entity_id": "sensor.rain_rate",
        "rain_entity_id": "binary_sensor.rain",
        "humidity_entity_id": "weather.home",
    }
    assert (
        "sump_driver_context"
        not in appliance_detail_payload(
            [coordinator],
            circuit_id="fridge",
        )["detail"]
    )

    nilm_coordinator = _nilm_coordinator()
    nilm_coordinator.store_data.nilm_appliance_assignments_by_circuit["mains"][0][
        "appliance_profile"
    ] = "sump_pump"
    nilm_payload = appliance_detail_payload(
        [nilm_coordinator],
        assignment_id="assignment-dishwasher",
    )
    assert nilm_payload["history"]["default_hours"] == 720
    nilm_detail = nilm_payload["detail"]
    assert nilm_detail["source_type"] == "nilm_estimate"
    assert "sump_driver_context" not in nilm_detail


def test_water_flow_context_detail_projects_retained_evidence() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _direct_coordinator()
    coordinator.circuit_configs = (
        _config(
            "washer",
            name="Laundry Washer",
            profile=ApplianceProfile.WASHER,
        ),
    )
    coordinator.state.water_flow_context_by_circuit["washer"] = {
        "status": "possible_flow_without_load",
        "friendly_summary": "Water flow has no mapped running appliance.",
        "confidence": 0.75,
        "flow_sensor_active": True,
        "flow_active_minutes": 18.5,
        "appliance_runtime_minutes": 12.0,
        "mapped_appliance_count": 1,
        "mapped_appliance_runtime_minutes": 0.0,
        "recent_related_runtime_minutes": 0.0,
        "recent_flow_explains_activity": False,
        "mismatch_minutes": 6.5,
        "flow_mismatch_threshold_minutes": 10,
        "comparable_window_count": 4,
        "flow_sensor_entities": [
            "sensor.house_flow",
            "binary_sensor.washer_flow",
            "sensor.house_flow",
        ],
    }

    detail = appliance_detail_payload(
        [coordinator],
        circuit_id="washer",
    )["detail"]

    assert detail["water_flow_context"] == {
        "status": "possible_flow_without_load",
        "friendly_summary": "Water flow has no mapped running appliance.",
        "confidence": 0.75,
        "flow_sensor_active": True,
        "flow_active_minutes": 18.5,
        "appliance_runtime_minutes": 12.0,
        "mapped_appliance_count": 1,
        "mapped_appliance_runtime_minutes": 0.0,
        "recent_related_runtime_minutes": 0.0,
        "recent_flow_explains_activity": False,
        "mismatch_minutes": 6.5,
        "flow_mismatch_threshold_minutes": 10,
        "flow_sensors": [
            {
                "entity_id": "binary_sensor.washer_flow",
                "name": "Washer Flow",
            },
            {
                "entity_id": "sensor.house_flow",
                "name": "House Flow",
            },
        ],
        "learning": {
            "comparable_window_count": 4,
            "required_comparable_windows": 10,
        },
    }


def test_water_flow_context_detail_omits_missing_metrics_and_keeps_zero_values() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _direct_coordinator()
    coordinator.circuit_configs = (
        _config(
            "washer",
            name="Laundry Washer",
            profile=ApplianceProfile.WASHER,
        ),
    )
    coordinator.state.water_flow_context_by_circuit["washer"] = {
        "status": "learning",
        "confidence": 0.0,
        "flow_sensor_active": False,
        "flow_active_minutes": 0.0,
        "mapped_appliance_count": 0,
        "mapped_appliance_runtime_minutes": 0.0,
        "recent_flow_explains_activity": False,
    }

    context = appliance_detail_payload(
        [coordinator],
        circuit_id="washer",
    )["detail"]["water_flow_context"]

    assert context == {
        "status": "learning",
        "confidence": 0.0,
        "flow_sensor_active": False,
        "flow_active_minutes": 0.0,
        "mapped_appliance_count": 0,
        "mapped_appliance_runtime_minutes": 0.0,
        "recent_flow_explains_activity": False,
        "flow_sensors": [],
        "learning": {
            "comparable_window_count": 0,
            "required_comparable_windows": 10,
        },
    }


def test_hvac_appliance_detail_exposes_retained_thermostat_efficiency() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _direct_coordinator()
    coordinator.circuit_configs = (
        _config(
            "heat_pump",
            name="Downstairs Heat Pump",
            profile=ApplianceProfile.HEAT_PUMP,
            mode=CircuitMode.DUAL_PHASE,
        ),
    )
    coordinator.state.hvac_efficiency_by_circuit["heat_pump"] = {
        "status": "ready",
        "score": 80.0,
        "finding": "slower",
        "threshold_pct": 25.0,
        "current_streams": {},
        "streams": {
            "heat_pump|climate.downstairs|cooling": {
                "status": "ready",
                "score": 80.0,
                "change_ratio": 0.25,
                "baseline_runtime_minutes": 50.0,
                "recent_runtime_minutes": 62.5,
                "reference_count": 50,
                "recent_count": 5,
                "finding": "slower",
                "context": {
                    "thermostat_entity_id": "climate.downstairs",
                    "mode": "cooling",
                    "temperature_bin": "very_hot",
                    "season": "summer",
                    "weather_mode": "cooling",
                    "gap_bin": "4-6F",
                    "participant_signature": ["heat_pump"],
                    "supporting_blower_ids": ["blower"],
                    "outdoor_temperature_f": 95.0,
                },
            },
            "heat_pump|climate.upstairs|heating": {
                "status": "learning",
                "score": None,
                "change_ratio": None,
                "baseline_runtime_minutes": None,
                "recent_runtime_minutes": None,
                "reference_count": 6,
                "recent_count": 0,
                "finding": None,
                "context": {
                    "thermostat_entity_id": "climate.upstairs",
                    "mode": "heating",
                    "temperature_bin": "cold",
                    "season": "winter",
                    "weather_mode": "heating",
                    "gap_bin": "2-4F",
                    "participant_signature": ["heat_pump", "electric_heat"],
                    "supporting_blower_ids": [],
                    "outdoor_temperature_f": 28.0,
                },
            },
        },
    }

    detail = appliance_detail_payload(
        [coordinator],
        circuit_id="heat_pump",
    )["detail"]

    assert detail["hvac_efficiency"] == {
        "status": "ready",
        "summary_score": 80.0,
        "trend": "slower",
        "threshold_pct": 25.0,
        "heating": [
            {
                "thermostat_entity_id": "climate.upstairs",
                "thermostat_name": "Upstairs",
                "status": "learning",
                "score": None,
                "trend": None,
                "change_percent": None,
                "baseline_runtime_minutes": None,
                "recent_runtime_minutes": None,
                "reference_count": 6,
                "recent_count": 0,
                "outdoor_temperature_f": 28.0,
                "season": "winter",
                "weather_mode": "heating",
                "temperature_bin": "cold",
                "gap_bin": "2-4F",
                "participant_signature": ["electric_heat", "heat_pump"],
                "supporting_blower_ids": [],
                "attribution": "assisted_system",
            }
        ],
        "cooling": [
            {
                "thermostat_entity_id": "climate.downstairs",
                "thermostat_name": "Downstairs",
                "status": "ready",
                "score": 80.0,
                "trend": "slower",
                "change_percent": 25.0,
                "baseline_runtime_minutes": 50.0,
                "recent_runtime_minutes": 62.5,
                "reference_count": 50,
                "recent_count": 5,
                "outdoor_temperature_f": 95.0,
                "season": "summer",
                "weather_mode": "cooling",
                "temperature_bin": "very_hot",
                "gap_bin": "4-6F",
                "participant_signature": ["heat_pump"],
                "supporting_blower_ids": ["blower"],
                "attribution": "direct",
            }
        ],
        "learning": {
            "reference_count": 50,
            "recent_count": 5,
            "required_reference": 50,
            "required_recent": 5,
        },
    }


def test_hvac_blower_detail_labels_heating_as_gas_furnace_proxy() -> None:
    from custom_components.circuitsetup_energy_analyzer.appliance_detail import (
        appliance_detail_for_circuit,
    )

    coordinator = _direct_coordinator()
    coordinator.circuit_configs = (
        _config(
            "blower",
            name="Furnace Blower",
            profile=ApplianceProfile.HVAC_BLOWER,
        ),
    )
    coordinator.state.hvac_efficiency_by_circuit["blower"] = {
        "status": "learning",
        "threshold_pct": 25.0,
        "streams": {
            "blower|climate.downstairs|heating": {
                "status": "learning",
                "reference_count": 4,
                "recent_count": 0,
                "context": {
                    "thermostat_entity_id": "climate.downstairs",
                    "mode": "heating",
                    "participant_signature": ["blower"],
                },
            }
        },
    }

    detail = appliance_detail_for_circuit(coordinator, "blower")

    assert detail is not None
    assert detail.hvac_efficiency is not None
    assert detail.hvac_efficiency["heating"][0]["attribution"] == ("gas_furnace_proxy")
    assert detail.hvac_efficiency["cooling"] == []


def test_appliance_detail_payload_includes_completed_daily_totals() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _direct_coordinator()
    coordinator.state.estimated_cost_today_by_circuit["fridge"] = 0.48
    coordinator.state.average_cost_per_day_by_circuit["fridge"] = 0.3
    coordinator.state.average_kwh_per_day_by_circuit["fridge"] = 1.5
    coordinator.state.effective_electricity_rate_by_circuit["fridge"] = 0.2
    coordinator.current_time = lambda: datetime(2026, 7, 22, 12, tzinfo=UTC)
    coordinator.context_builder = SimpleNamespace(
        time_zone=lambda: "America/New_York",
    )
    coordinator.store_data.energy_usage_by_circuit["fridge"] = {
        "days": [
            {
                "date": f"2026-06-{day:02d}",
                "usage_kwh": 2.0,
                "complete": True,
            }
            for day in range(17, 31)
        ]
        + [
            {
                "date": f"2026-07-{day:02d}",
                "usage_kwh": 2.0,
                "complete": True,
            }
            for day in range(1, 22)
        ]
        + [
            {"date": "2026-07-22", "usage_kwh": 1.0, "complete": True},
            {"date": "2026-07-23", "usage_kwh": 1.0, "complete": True},
            {"date": "not-a-date", "usage_kwh": 1.0, "complete": True},
        ],
    }

    payload = appliance_detail_payload([coordinator], circuit_id="fridge")

    assert payload["detail"]["cost_today"] == 0.48
    assert payload["detail"]["cost_today_status"] == "estimated"
    assert payload["detail"]["average_cost_per_day"] == 0.3
    assert payload["detail"]["average_kwh_per_day"] == 1.5
    assert len(payload["daily_totals"]) == 30
    assert payload["daily_totals"][0]["date"] == "2026-06-22"
    assert payload["daily_totals"][-1] == {
        "date": "2026-07-21",
        "energy_kwh": 2.0,
        "cost": 0.4,
        "cost_source": "estimated",
    }
    assert all(item["date"] < "2026-07-22" for item in payload["daily_totals"])


def test_appliance_daily_totals_follow_refreshed_effective_rate() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _direct_coordinator()
    coordinator.current_time = lambda: datetime(2026, 7, 22, 12, tzinfo=UTC)
    coordinator.store_data.energy_usage_by_circuit["fridge"] = {
        "days": [{"date": "2026-07-21", "usage_kwh": 2.0, "complete": True}]
    }
    coordinator.store_data.cost_by_circuit["fridge"] = {
        "days": [{"date": "2026-07-21", "cost": 0.62, "complete": True}]
    }
    coordinator.state.effective_electricity_rate_by_circuit["fridge"] = 0.25
    coordinator.state.estimated_cost_today_by_circuit["fridge"] = 0.6
    coordinator.state.cost_today_by_circuit["fridge"] = 0.72
    coordinator.state.cost_today_status_by_circuit["fridge"] = "actual"
    coordinator.state.average_cost_per_day_by_circuit["fridge"] = 0.38

    payload = appliance_detail_payload([coordinator], circuit_id="fridge")

    assert payload["detail"]["cost_today"] == 0.72
    assert payload["detail"]["cost_today_status"] == "recorded"
    assert payload["detail"]["average_cost_per_day"] == 0.38
    assert payload["daily_totals"] == [
        {
            "date": "2026-07-21",
            "energy_kwh": 2.0,
            "cost": 0.62,
            "cost_source": "recorded",
        }
    ]

    coordinator.state.effective_electricity_rate_by_circuit["fridge"] = None
    coordinator.state.estimated_cost_today_by_circuit["fridge"] = None
    coordinator.state.cost_today_status_by_circuit["fridge"] = "unavailable"
    coordinator.state.average_cost_per_day_by_circuit["fridge"] = None

    payload = appliance_detail_payload([coordinator], circuit_id="fridge")

    assert payload["detail"]["cost_today"] is None
    assert payload["detail"]["cost_today_status"] == "unavailable"
    assert payload["detail"]["average_cost_per_day"] is None
    assert payload["daily_totals"][0]["cost"] == 0.62


def test_appliance_detail_payload_includes_energy_change_explanation() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _direct_coordinator()
    coordinator.state.energy_usage_evidence_by_circuit["fridge"].update(
        {
            "contextual_expected_range": [1.0, 1.4],
            "contextual_baseline_median_kwh": 1.2,
            "contextual_baseline_confidence": 0.9,
        }
    )
    coordinator.state.run_cycle_evidence_by_circuit["fridge"] = {
        "runtime_today_contextual_expected_range_seconds": [5400.0, 6600.0],
        "runtime_today_contextual_baseline_median_seconds": 6000.0,
        "runtime_today_contextual_baseline_confidence": 0.9,
        "run_count_contextual_expected_range": [10.0, 14.0],
        "run_count_contextual_baseline_median": 12.0,
        "run_count_contextual_baseline_confidence": 0.9,
    }

    payload = appliance_detail_payload([coordinator], circuit_id="fridge")

    explanation = payload["detail"]["energy_change_explanation"]
    assert explanation["appliance_key"] == "circuit:fridge"
    assert explanation["current_energy_kwh"] == pytest.approx(1.82)
    assert explanation["normal_energy_kwh"] == pytest.approx(1.2)
    assert explanation["total_change_percent"] == pytest.approx(51.6666667)
    assert explanation["confidence"] == pytest.approx(0.9)
    assert explanation["explanation"].startswith("Energy today is 52% above normal")


def test_appliance_detail_payload_scopes_duplicate_circuit_to_entry() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    upstairs = _direct_coordinator()
    upstairs.circuit_configs = (_config(name="Upstairs Fridge"),)
    downstairs = _direct_coordinator()
    downstairs.entry_id = "entry-2"
    downstairs.circuit_configs = (_config(name="Downstairs Fridge"),)

    payload = appliance_detail_payload(
        [upstairs, downstairs],
        circuit_id="fridge",
        entry_id="entry-2",
    )

    assert payload["status"] == "ok"
    assert payload["requested_entry_id"] == "entry-2"
    assert payload["detail"]["display_name"] == "Downstairs Fridge"


def test_direct_appliance_detail_hides_alert_actions_without_an_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _direct_coordinator()
    coordinator.state.active_alerts_by_circuit["fridge"] = []

    payload = appliance_detail_payload([coordinator], circuit_id="fridge")

    assert "open_evidence" not in payload["actions"]
    assert "mark_expected" not in payload["actions"]
    assert "mark_unhelpful" not in payload["actions"]
    assert "relearn_baseline" in payload["actions"]


def test_direct_appliance_detail_does_not_reprice_daily_energy() -> None:
    from custom_components.circuitsetup_energy_analyzer.appliance_detail import (
        appliance_detail_for_circuit,
    )

    coordinator = _direct_coordinator()
    coordinator.state.utility_cost_rate_by_circuit["mains"] = 0.30

    detail = appliance_detail_for_circuit(coordinator, "fridge")

    assert detail is not None
    assert detail.cost_today is None


def test_direct_appliance_detail_preserves_explicitly_unavailable_cost() -> None:
    from custom_components.circuitsetup_energy_analyzer.appliance_detail import (
        appliance_detail_for_circuit,
    )

    coordinator = _direct_coordinator()
    coordinator.state.cost_evidence_by_circuit["fridge"] = {
        "cost_today_status": "unavailable"
    }

    detail = appliance_detail_for_circuit(coordinator, "fridge")

    assert detail is not None
    assert detail.cost_today is None


def test_direct_appliance_detail_does_not_estimate_with_missing_tariff() -> None:
    from custom_components.circuitsetup_energy_analyzer.appliance_detail import (
        appliance_detail_for_circuit,
    )

    coordinator = _direct_coordinator()
    coordinator.state.cost_current_rate_by_circuit["fridge"] = 0.0

    detail = appliance_detail_for_circuit(coordinator, "fridge")

    assert detail is not None
    assert detail.cost_today is None


def test_direct_appliance_detail_hides_missing_metric_prompt_when_metrics_exist() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.appliance_detail import (
        appliance_detail_for_circuit,
    )

    coordinator = _direct_coordinator()
    coordinator.state.metric_consistency_status_by_circuit["fridge"] = "missing_metrics"
    coordinator.state.data_quality_checklist_by_circuit["fridge"].update(
        {
            "optional_sensors_present": True,
            "metric_roles_present": [
                "apparent_power",
                "current",
                "energy",
                "power_factor",
                "real_power",
                "voltage",
            ],
        }
    )

    detail = appliance_detail_for_circuit(coordinator, "fridge")

    assert detail is not None
    assert detail.what_to_check_first == ()


def test_direct_detail_keeps_missing_metric_prompt_for_incomplete_metrics() -> None:
    from custom_components.circuitsetup_energy_analyzer.appliance_detail import (
        appliance_detail_for_circuit,
    )

    coordinator = _direct_coordinator()
    coordinator.state.metric_consistency_status_by_circuit["fridge"] = "missing_metrics"
    coordinator.state.data_quality_checklist_by_circuit["fridge"].update(
        {
            "optional_sensors_present": True,
            "metric_roles_present": ["energy", "real_power", "voltage"],
        }
    )

    detail = appliance_detail_for_circuit(coordinator, "fridge")

    assert detail is not None
    assert detail.what_to_check_first == (
        "Add matching electrical metrics such as watts, amps, voltage, VA, or PF.",
    )


def test_direct_appliance_detail_payload_includes_recent_timeline() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _direct_coordinator()
    coordinator.state.recent_activity_timeline_by_circuit["fridge"] = {
        "status": "activity",
        "window_hours": 24,
        "total_count": 1,
        "event_count": 1,
        "alert_count": 0,
        "observation_count": 0,
        "latest_title": "Start",
        "latest_timestamp": "2026-06-30T12:00:00+00:00",
        "items": [
            {
                "timestamp": "2026-06-30T12:00:00+00:00",
                "kind": "event",
                "title": "Start",
                "detail": "Observed start event.",
                "severity": "info",
            }
        ],
    }

    payload = appliance_detail_payload([coordinator], circuit_id="fridge")

    timeline = payload["detail"]["recent_timeline"]
    assert timeline["status"] == "activity"
    assert timeline["latest_title"] == "Start"
    assert timeline["items"][0]["detail"] == "Observed start event."


def test_direct_appliance_detail_includes_normalized_session_timeline() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _direct_coordinator()
    coordinator.current_time = lambda: datetime(2026, 6, 30, 13, 0, tzinfo=UTC)
    coordinator.store_data.events = [
        CircuitEvent(
            timestamp=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
            circuit_id="fridge",
            event_type=EventType.START,
        ),
        CircuitEvent(
            timestamp=datetime(2026, 6, 30, 12, 10, tzinfo=UTC),
            circuit_id="fridge",
            event_type=EventType.STOP,
        ),
    ]

    timeline = appliance_detail_payload(
        [coordinator],
        circuit_id="fridge",
    )["detail"]["session_timeline"]

    assert len(timeline) == 1
    assert timeline[0]["source_type"] == "direct_meter"
    assert timeline[0]["duration_seconds"] == 600.0


def test_direct_appliance_detail_payload_exposes_all_source_history() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    payload = appliance_detail_payload([_direct_coordinator()], circuit_id="fridge")

    assert payload["history"]["entity_series"] == [
        {"entity_id": "sensor.fridge_power", "unit": "W"},
        {"entity_id": "sensor.fridge_current", "unit": "A"},
        {"entity_id": "sensor.fridge_power_factor", "unit": "PF"},
        {"entity_id": "sensor.fridge_energy", "unit": "kWh"},
    ]
    assert "sensor.fridge_apparent_power" not in payload["history"]["entities"]
    assert "sensor.fridge_reactive_power" not in payload["history"]["entities"]


def test_direct_appliance_detail_omits_va_and_var_with_misclassified_roles() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _direct_coordinator()
    coordinator.circuit_configs = (
        CircuitConfig(
            circuit_id="fridge",
            name="Kitchen Fridge",
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            mode=CircuitMode.SINGLE_PHASE,
            sensors=(
                SensorRef("sensor.fridge_watts", SensorRole.REAL_POWER),
                SensorRef("sensor.var_speed_pump_power", SensorRole.REAL_POWER),
                SensorRef("sensor.kva_speed_pump_power", SensorRole.REAL_POWER),
                SensorRef("sensor.fridge_va", SensorRole.REAL_POWER),
                SensorRef("sensor.fridge_var", SensorRole.REAL_POWER),
                SensorRef("sensor.fridge_kva", SensorRole.REAL_POWER),
                SensorRef("sensor.fridge_mva", SensorRole.REAL_POWER),
                SensorRef("sensor.fridge_kvar", SensorRole.REAL_POWER),
                SensorRef("sensor.fridge_mvar", SensorRole.REAL_POWER),
                SensorRef(
                    "sensor.legacy_apparent_meter",
                    SensorRole.REAL_POWER,
                    unit="kVA",
                ),
            ),
        ),
    )

    history = appliance_detail_payload(
        [coordinator],
        circuit_id="fridge",
    )["history"]

    assert history["entities"] == [
        "sensor.fridge_watts",
        "sensor.var_speed_pump_power",
        "sensor.kva_speed_pump_power",
    ]


def test_mains_nilm_appliance_detail_expectations_keep_mains_source() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    state = AnalyzerState()
    state.health_summary_by_circuit["mains"] = "Ready"
    coordinator = SimpleNamespace(
        circuit_configs=(
            _config(
                "mains",
                name="Whole Home",
                profile=ApplianceProfile.MAINS_NILM,
                mode=CircuitMode.MAINS_NILM,
            ),
        ),
        state=state,
        store_data=FeatureStoreData(),
        entry_id="entry-1",
    )

    payload = appliance_detail_payload([coordinator], circuit_id="mains")

    assert payload["status"] == "ok"
    detail = payload["detail"]
    assert detail["source_type"] == "mains"
    assert detail["expectations"][0]["source_type"] == "mains"


def test_mixed_appliance_detail_expectations_keep_mixed_source() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    state = AnalyzerState()
    state.health_summary_by_circuit["garage"] = "Ready"
    coordinator = SimpleNamespace(
        circuit_configs=(
            _config(
                "garage",
                name="Garage Mixed Loads",
                profile=ApplianceProfile.MIXED,
                mode=CircuitMode.MIXED,
            ),
        ),
        state=state,
        store_data=FeatureStoreData(),
        entry_id="entry-1",
    )

    payload = appliance_detail_payload([coordinator], circuit_id="garage")

    assert payload["status"] == "ok"
    detail = payload["detail"]
    assert detail["source_type"] == "mixed"
    assert detail["expectations"][0]["source_type"] == "mixed"


def test_specific_profile_mixed_detail_explains_shared_measurement() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _direct_coordinator()
    coordinator.circuit_configs = (
        _config(profile=ApplianceProfile.REFRIGERATOR, mode=CircuitMode.MIXED),
    )

    detail = appliance_detail_payload([coordinator], circuit_id="fridge")["detail"]
    expectation = detail["expectations"][0]

    assert expectation["source_type"] == "mixed"
    assert "whole shared circuit" in expectation["observed"]
    assert "Reviewed Experimental NILM" in expectation["expected"]
    assert "appliance-specific evidence" in expectation["expected"]


@pytest.mark.parametrize(
    ("profile", "mode"),
    (
        (ApplianceProfile.REFRIGERATOR, CircuitMode.MIXED),
        (ApplianceProfile.MIXED, CircuitMode.SINGLE_PHASE),
    ),
)
def test_mixed_detail_omits_direct_run_comparisons(
    profile: ApplianceProfile, mode: CircuitMode
) -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _direct_coordinator()
    coordinator.circuit_configs = (_config(profile=profile, mode=mode),)

    comparisons = appliance_detail_payload([coordinator], circuit_id="fridge")[
        "detail"
    ]["today_vs_normal"]

    metric_ids = {comparison["metric_id"] for comparison in comparisons}

    assert "daily_energy_kwh" in metric_ids
    assert metric_ids.isdisjoint(
        {"runtime_today_seconds", "run_count_today", "current_power_w"}
    )


def test_nilm_appliance_detail_payload_marks_estimated_source() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _nilm_coordinator()
    coordinator.hass = SimpleNamespace(
        states=SimpleNamespace(
            async_all=lambda _domain: [
                SimpleNamespace(
                    entity_id="sensor.dishwasher_estimated_power",
                    attributes={
                        "assignment_id": "assignment-dishwasher",
                        "unit_of_measurement": "W",
                    },
                ),
                SimpleNamespace(
                    entity_id="sensor.dishwasher_estimated_daily_energy",
                    attributes={
                        "assignment_id": "assignment-dishwasher",
                        "unit_of_measurement": "kWh",
                    },
                ),
            ]
        )
    )

    payload = appliance_detail_payload(
        [coordinator],
        assignment_id="assignment-dishwasher",
    )

    assert payload["status"] == "ok"
    detail = payload["detail"]
    assert detail["appliance_key"] == "nilm:assignment-dishwasher"
    assert detail["appliance_id"] == "dishwasher"
    assert detail["assignment_id"] == "assignment-dishwasher"
    assert detail["mains_circuit_id"] == "mains"

    assert detail["mains_source"] == "sensor.mains_power"
    assert detail["circuit_id"] == "mains"
    assert detail["display_name"] == "Dishwasher"
    assert detail["appliance_profile"] == "dishwasher"
    assert detail["source_type"] == "nilm_estimate"
    assert detail["source_quality"]["label"] == "Estimated from aggregate circuit"
    assert "aggregate circuit power" in detail["expectations"][0]["why_it_matters"]
    assert payload["daily_totals"] == []
    assert detail["confidence"] == 0.72
    assert detail["model_status"] == "needs_validation"
    assert detail["activity_state"] == "Idle"
    assert detail["health_state"] == "Needs validation"
    assert "electrical_state" not in detail
    assert detail["energy_state"] == "Estimated"
    assert detail["current_power_w"] is None
    assert detail["daily_energy_kwh"] == 0.818
    assert detail["cost_today"] is None
    assert detail["next_step"] == "Review NILM assignment"
    assert detail["what_to_check_first"] == [
        "Validate this estimated appliance before relying on alerts."
    ]
    evidence_query = parse_qs(urlparse(detail["evidence_path"]).query)
    assert evidence_query == {
        "circuit_id": ["mains"],
        "assignment_id": ["assignment-dishwasher"],
        "nilm_workspace": ["1"],
        "appliance_detail": ["1"],
    }
    review_path = payload["actions"]["review_nilm_assignment"]["path"]
    review_query = parse_qs(urlparse(review_path).query)
    assert review_query["circuit_id"] == ["mains"]
    assert review_query["assignment_id"] == ["assignment-dishwasher"]
    assert review_query["nilm_workspace"] == ["1"]
    assert review_query["session_id"]
    assert payload["actions"]["review_nilm_assignment"] == {
        "type": "navigate",
        "path": review_path,
        "data": {
            "circuit_id": "mains",
            "assignment_id": "assignment-dishwasher",
            "session_id": review_query["session_id"][0],
        },
    }
    assert "open_evidence" not in payload["actions"]
    assert {"mark_correct", "mark_wrong", "adjust_interval"} <= set(payload["actions"])
    assert payload["actions"]["mark_correct"]["service"] == "validate_nilm_session"
    assert payload["actions"]["mark_wrong"]["service"] == "reject_nilm_session"
    assert payload["history"]["entities"] == [
        "sensor.dishwasher_estimated_power",
    ]


def test_off_only_nilm_assignment_does_not_create_energy_or_history() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _nilm_coordinator()
    assignment = coordinator.store_data.nilm_appliance_assignments_by_circuit["mains"][
        0
    ]
    assignment["signature_fingerprints"] = [
        "direction=off|watts=0-100|var=0-100|va=0-100|pf=0.10-0.15|"
        "split=unknown|leg=unknown|balance=unknown",
        "unassigned",
    ]
    coordinator.store_data.nilm_signatures = {
        "mains": [
            {
                "feedback_fingerprint": assignment["signature_fingerprints"][0],
                "direction": "off",
                "median_delta_w": -82.0,
            }
        ]
    }
    coordinator.store_data.nilm_session_history_by_circuit = {
        "mains": [
            {
                **_nilm_session(
                    "invalid-off-session",
                    start=datetime(2026, 6, 30, 8, 0, tzinfo=UTC),
                    end=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
                    duration_seconds=14400.0,
                    energy_kwh=0.328,
                ),
                "signature_fingerprint": assignment["signature_fingerprints"][0],
            },
            {
                **_nilm_session(
                    "invalid-unassigned-session",
                    start=datetime(2026, 6, 30, 13, 0, tzinfo=UTC),
                    end=datetime(2026, 6, 30, 14, 0, tzinfo=UTC),
                    duration_seconds=3600.0,
                    energy_kwh=0.31,
                ),
                "signature_fingerprint": "unassigned",
            },
            {
                **_nilm_session(
                    "invalid-legacy-session",
                    start=datetime(2026, 6, 30, 15, 0, tzinfo=UTC),
                    end=datetime(2026, 6, 30, 16, 0, tzinfo=UTC),
                    duration_seconds=3600.0,
                    energy_kwh=0.5,
                ),
                "assignment_id": "assignment-dishwasher",
            },
        ]
    }
    coordinator.hass = SimpleNamespace(
        states=SimpleNamespace(
            async_all=lambda _domain: [
                SimpleNamespace(
                    entity_id="sensor.dishwasher_estimated_daily_energy",
                    attributes={
                        "assignment_id": "assignment-dishwasher",
                        "unit_of_measurement": "kWh",
                    },
                ),
            ]
        )
    )

    payload = appliance_detail_payload(
        [coordinator],
        assignment_id="assignment-dishwasher",
    )

    assert payload["detail"]["daily_energy_kwh"] == 0.0
    assert payload["detail"]["active_alerts"] == []
    assert payload["history"]["entities"] == []
    assert "embedded_series" not in payload["history"]


def test_explicitly_linked_legacy_off_session_is_retained() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm_virtual import (
        _merged_assignment_session_payloads,
    )

    coordinator = _nilm_coordinator()
    assignment = coordinator.store_data.nilm_appliance_assignments_by_circuit["mains"][
        0
    ]
    fingerprint = (
        "direction=off|watts=0-100|var=0-100|va=0-100|pf=0.10-0.15|"
        "split=unknown|leg=unknown|balance=unknown"
    )
    assignment["signature_fingerprints"] = [fingerprint, "unassigned"]
    assignment["session_ids"] = [
        "legacy-complete",
        "legacy-open",
        "legacy-rejected",
    ]
    assignment["confirmed_session_ids"] = ["legacy-complete", "legacy-open"]
    assignment["rejected_session_ids"] = ["legacy-rejected"]
    coordinator.store_data.nilm_session_history_by_circuit = {
        "mains": [
            {
                **_nilm_session(
                    "legacy-complete",
                    start=datetime(2026, 6, 30, 8, 0, tzinfo=UTC),
                    end=datetime(2026, 6, 30, 8, 5, tzinfo=UTC),
                    duration_seconds=300.0,
                    energy_kwh=0.008,
                ),
                "signature_fingerprint": fingerprint,
                "assignment_id": assignment["assignment_id"],
            },
            {
                **_nilm_session(
                    "legacy-open",
                    start=datetime(2026, 6, 30, 8, 30, tzinfo=UTC),
                    end=None,
                    duration_seconds=None,
                    energy_kwh=0.0,
                ),
                "signature_fingerprint": fingerprint,
                "assignment_id": assignment["assignment_id"],
            },
            {
                **_nilm_session(
                    "legacy-rejected",
                    start=datetime(2026, 6, 30, 8, 45, tzinfo=UTC),
                    end=datetime(2026, 6, 30, 12, 45, tzinfo=UTC),
                    duration_seconds=14400.0,
                    energy_kwh=0.4,
                ),
                "signature_fingerprint": fingerprint,
                "assignment_id": assignment["assignment_id"],
            },
            {
                **_nilm_session(
                    "unlinked",
                    start=datetime(2026, 6, 30, 9, 0, tzinfo=UTC),
                    end=datetime(2026, 6, 30, 9, 5, tzinfo=UTC),
                    duration_seconds=300.0,
                    energy_kwh=0.008,
                ),
                "signature_fingerprint": fingerprint,
                "assignment_id": assignment["assignment_id"],
            },
        ]
    }

    sessions = _merged_assignment_session_payloads(
        coordinator,
        "mains",
        assignment,
        (),
    )

    assert [session["session_id"] for session in sessions] == [
        "legacy-complete",
        "legacy-rejected",
    ]


def test_nilm_appliance_alert_actions_use_alert_feedback_contract() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _nilm_coordinator()
    coordinator.state.active_alerts_by_circuit["mains"] = [
        AlertEvidence(
            timestamp=datetime(2026, 6, 30, 9, 0, tzinfo=UTC),
            circuit_id="mains",
            severity=Severity.WARNING,
            message="Dishwasher appears finished.",
            feature="nilm_appliance_finished",
            features={"assignment_id": "assignment-dishwasher"},
        )
    ]

    payload = appliance_detail_payload(
        [coordinator],
        assignment_id="assignment-dishwasher",
    )
    actions = payload["actions"]
    alert_id = payload["detail"]["active_alerts"][0]["alert_id"]

    assert (
        actions["open_evidence"]["path"]
        == (payload["detail"]["active_alerts"][0]["evidence_path"])
    )
    for key, service in (
        ("mark_correct", "mark_nilm_appliance_correct"),
        ("mark_wrong", "mark_nilm_appliance_wrong"),
        ("mark_expected", "mark_alert_expected"),
        ("mark_unhelpful", "mark_alert_unhelpful"),
    ):
        assert actions[key]["service"] == service
        assert actions[key]["data"] == {"alert_id": alert_id}


def test_nilm_appliance_detail_derives_only_assignment_session_history() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _nilm_coordinator()
    coordinator.current_time = lambda: datetime(2026, 6, 30, 10, 10, tzinfo=UTC)
    coordinator.state.recent_activity_timeline_by_circuit["mains"] = {
        "status": "activity",
        "items": [{"session_id": "mains-timeline-must-not-leak"}],
    }
    coordinator.store_data.nilm_session_history_by_circuit = {
        "mains": [
            _nilm_session(
                "session-dishwasher-complete",
                start=datetime(2026, 6, 30, 8, 0, tzinfo=UTC),
                end=datetime(2026, 6, 30, 8, 30, tzinfo=UTC),
                duration_seconds=1800.0,
            ),
            _nilm_session(
                "session-other-appliance",
                assignment_id="assignment-other",
                start=datetime(2026, 6, 30, 9, 0, tzinfo=UTC),
                end=datetime(2026, 6, 30, 9, 15, tzinfo=UTC),
                duration_seconds=900.0,
            ),
            _nilm_session(
                "session-dishwasher-open",
                start=datetime(2026, 6, 30, 10, 0, tzinfo=UTC),
                end=None,
                duration_seconds=None,
                energy_kwh=0.0,
            ),
        ]
    }

    payload = appliance_detail_payload(
        [coordinator],
        assignment_id="assignment-dishwasher",
    )
    detail = payload["detail"]

    assert detail["runtime_today_seconds"] == 1800.0
    assert detail["run_count_today"] == 1
    assert detail["current_session_duration_seconds"] is None
    assert detail["current_session"] is None
    assert detail["last_matched_session"] == {
        "session_id": "session-dishwasher-complete",
        "signature_fingerprint": "signature_1",
        "start": "2026-06-30T08:00:00+00:00",
        "end": "2026-06-30T08:30:00+00:00",
        "duration_seconds": 1800.0,
        "estimated_energy_kwh": 0.2,
        "confidence": 0.91,
        "validation_result": None,
    }
    timeline_ids = {item["session_id"] for item in detail["recent_timeline"]["items"]}
    assert timeline_ids == {"session-dishwasher-complete"}
    assert {item["session_id"] for item in detail["session_timeline"]} == timeline_ids
    assert {item["source_type"] for item in detail["session_timeline"]} == {
        "nilm_estimate"
    }
    embedded_rows = payload["history"]["embedded_series"][0]
    assert not any("09:00:00" in row["last_changed"] for row in embedded_rows)
    adjust_query = parse_qs(
        urlparse(payload["actions"]["adjust_interval"]["path"]).query
    )
    assert adjust_query["session_id"] == ["session-dishwasher-complete"]


def test_direct_meter_conversion_preserves_nilm_identity_in_appliance_detail() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _nilm_coordinator()
    direct = _config(
        "dishwasher_direct",
        name="Dishwasher Meter",
        profile=ApplianceProfile.WASHER,
    )
    coordinator.circuit_configs = (*coordinator.circuit_configs, direct)
    assignment = coordinator.store_data.nilm_appliance_assignments_by_circuit["mains"][
        0
    ]
    assignment.update(
        {
            "appliance_key": "nilm:assignment-dishwasher",
            "conversion_state": "direct_meter",
            "direct_circuit_id": "dishwasher_direct",
            "keep_assignment_for_masking": True,
            "publish_entities": False,
        }
    )

    detail = appliance_detail_payload(
        [coordinator],
        circuit_id="dishwasher_direct",
    )["detail"]

    assert detail["source_type"] == "direct_meter"
    assert detail["display_name"] == "Dishwasher"
    assert detail["appliance_key"] == "nilm:assignment-dishwasher"
    assert detail["assignment_id"] == "assignment-dishwasher"
    assert detail["mains_circuit_id"] == "mains"

    assignment_detail = appliance_detail_payload(
        [coordinator],
        assignment_id="assignment-dishwasher",
    )["detail"]
    assert assignment_detail == detail


@pytest.mark.parametrize("lifecycle_state", ["ignored", "retired"])
def test_hidden_direct_meter_conversion_releases_configured_circuit_identity(
    lifecycle_state: str,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _nilm_coordinator()
    ac2 = _config("ac2", name="AC 2", profile=ApplianceProfile.HVAC)
    coordinator.circuit_configs = (*coordinator.circuit_configs, ac2)
    assignment = coordinator.store_data.nilm_appliance_assignments_by_circuit["mains"][
        0
    ]
    assignment.update(
        {
            "display_name": "Condensate Pump 2",
            "conversion_state": "direct_meter",
            "direct_circuit_id": "ac2",
            "lifecycle_state": lifecycle_state,
        }
    )

    detail = appliance_detail_payload([coordinator], circuit_id="ac2")["detail"]

    assert detail["display_name"] == "AC 2"
    assert detail["appliance_key"] == "circuit:ac2"
    assert detail["assignment_id"] is None


def test_appliance_detail_payload_includes_notification_preferences() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _direct_coordinator()
    coordinator.store_data.appliance_notification_preferences = {
        "circuit:fridge": {
            "finished_running": True,
            "delivery_mode": "daily_summary",
        }
    }

    payload = appliance_detail_payload([coordinator], circuit_id="fridge")

    preferences = payload["notification_preferences"]
    assert preferences["appliance_key"] == "circuit:fridge"
    assert preferences["finished_running"] is True
    assert preferences["electrical_issue"] is True
    assert preferences["delivery_mode"] == "daily_summary"


def test_appliance_detail_payload_includes_expected_schedule_context() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _direct_coordinator()
    coordinator.store_data.appliance_schedule_settings = {
        "circuit:fridge": {
            "enabled": True,
            "schedule_entity_id": "schedule.fridge",
            "minimum_duration_minutes": 20,
        }
    }
    coordinator.state.expected_schedule_by_appliance["circuit:fridge"] = {
        "status": "running_in_expected_window",
        "message": "Running during the expected schedule.",
    }
    coordinator.hass = SimpleNamespace(
        states=SimpleNamespace(
            async_all=lambda: [
                SimpleNamespace(
                    entity_id="schedule.fridge",
                    name="Fridge Schedule",
                ),
                SimpleNamespace(entity_id="sensor.power", name="Power"),
            ]
        )
    )

    payload = appliance_detail_payload([coordinator], circuit_id="fridge")

    schedule = payload["expected_schedule"]
    assert schedule["settings"]["schedule_entity_id"] == "schedule.fridge"
    assert schedule["context"]["status"] == "running_in_expected_window"
    assert schedule["schedule_entities"] == [
        {"entity_id": "schedule.fridge", "name": "Fridge Schedule"}
    ]


@pytest.mark.asyncio
async def test_expected_schedule_save_uses_backend_appliance_identity() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        async_set_appliance_expected_schedule,
    )

    coordinator = _direct_coordinator()
    coordinator.current_time = lambda: datetime(2026, 7, 13, 12, tzinfo=UTC)
    coordinator.store_persistence = SimpleNamespace(
        mark_dirty=Mock(),
        async_save_if_dirty=AsyncMock(),
    )

    result = await async_set_appliance_expected_schedule(
        [coordinator],
        circuit_id="fridge",
        assignment_id=None,
        values={
            "enabled": True,
            "windows": [
                {
                    "start": "08:00",
                    "end": "10:00",
                    "weekdays": [0, 1, 2, 3, 4],
                }
            ],
            "minimum_duration_minutes": 30,
        },
    )

    assert result["status"] == "saved"
    assert result["expected_schedule_settings"]["appliance_key"] == ("circuit:fridge")
    assert (
        coordinator.store_data.appliance_schedule_settings["circuit:fridge"]["windows"][
            0
        ]["start"]
        == "08:00"
    )
    assert coordinator.store_data.appliance_schedule_evidence == {}


def test_nilm_today_vs_normal_requires_validated_multi_day_history() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _nilm_coordinator()
    assignment = coordinator.store_data.nilm_appliance_assignments_by_circuit["mains"][
        0
    ]
    sessions = [
        _nilm_session(
            f"session-confirmed-{day}",
            start=datetime(2026, 6, day, 8, 0, tzinfo=UTC),
            end=datetime(2026, 6, day, 8, 30, tzinfo=UTC),
            duration_seconds=1800.0,
            energy_kwh=0.41,
        )
        for day in (27, 28, 29, 30)
    ]
    assignment.update(
        {
            "lifecycle_state": "validated",
            "confidence": 0.92,
            "session_ids": [item["session_id"] for item in sessions],
            "confirmed_session_ids": [item["session_id"] for item in sessions],
            "false_positive_rate": 0.0,
        }
    )
    coordinator.store_data.nilm_session_history_by_circuit = {"mains": sessions}
    validated = appliance_detail_payload(
        [coordinator],
        assignment_id="assignment-dishwasher",
    )["detail"]

    assert {item["metric_id"] for item in validated["today_vs_normal"]} >= {
        "daily_energy_kwh",
        "runtime_today_seconds",
        "run_count_today",
    }
    assert {item["comparison_mode"] for item in validated["today_vs_normal"]} == {
        "same_time_of_day"
    }

    assignment["lifecycle_state"] = "needs_validation"
    unvalidated = appliance_detail_payload(
        [coordinator],
        assignment_id="assignment-dishwasher",
    )["detail"]
    assert unvalidated["today_vs_normal"] == []

    assignment["lifecycle_state"] = "validated"
    assignment["confirmed_session_ids"] = [sessions[-1]["session_id"]]
    insufficient_history = appliance_detail_payload(
        [coordinator],
        assignment_id="assignment-dishwasher",
    )["detail"]
    assert insufficient_history["today_vs_normal"] == []
    assert insufficient_history["health_state"] == "Needs validation"
    assert insufficient_history["learning_readiness"] == {
        "status": "needs_validation",
        "label": "Not enough confirmed history",
    }
    assert insufficient_history["next_step"] == "Confirm more NILM sessions"

    assignment["confirmed_session_ids"] = [item["session_id"] for item in sessions]
    assignment["false_positive_rate"] = 1.0
    poor_validation = appliance_detail_payload(
        [coordinator],
        assignment_id="assignment-dishwasher",
    )["detail"]
    assert poor_validation["today_vs_normal"] == []


def test_rejected_nilm_session_is_reviewable_but_not_last_attributed_match() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _nilm_coordinator()
    assignment = coordinator.store_data.nilm_appliance_assignments_by_circuit["mains"][
        0
    ]
    assignment.update(
        {
            "session_ids": ["session-confirmed", "session-rejected"],
            "rejected_session_ids": ["session-rejected"],
        }
    )
    coordinator.store_data.nilm_session_history_by_circuit = {
        "mains": [
            _nilm_session(
                "session-confirmed",
                start=datetime(2026, 6, 30, 8, 0, tzinfo=UTC),
                end=datetime(2026, 6, 30, 8, 30, tzinfo=UTC),
                duration_seconds=1800.0,
            ),
            _nilm_session(
                "session-rejected",
                start=datetime(2026, 6, 30, 9, 0, tzinfo=UTC),
                end=datetime(2026, 6, 30, 9, 30, tzinfo=UTC),
                duration_seconds=1800.0,
            ),
        ]
    }

    detail = appliance_detail_payload(
        [coordinator],
        assignment_id="assignment-dishwasher",
    )["detail"]

    assert detail["last_matched_session"]["session_id"] == "session-confirmed"
    timeline = {item["session_id"]: item for item in detail["recent_timeline"]["items"]}
    assert timeline["session-rejected"]["validation_result"] == "rejected"


def test_unpublished_nilm_appliance_uses_retained_session_history() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _nilm_coordinator()
    assignment = coordinator.store_data.nilm_appliance_assignments_by_circuit["mains"][
        0
    ]
    assignment["publish_entities"] = False
    coordinator.store_data.nilm_session_history_by_circuit = {
        "mains": [
            {
                "session_id": "session-dishwasher",
                "assignment_id": "assignment-dishwasher",
                "start": "2026-07-11T12:00:00+00:00",
                "end": "2026-07-11T12:30:00+00:00",
                "median_power_w": 820.0,
            }
        ]
    }

    payload = appliance_detail_payload(
        [coordinator],
        assignment_id="assignment-dishwasher",
    )

    embedded = payload["history"]["embedded_series"]
    assert len(embedded) == 1
    assert {row["state"] for row in embedded[0]} == {"0", "820"}
    assert embedded[0][0]["entity_id"] == "sensor.dishwasher_estimated_power"


def test_appliance_detail_reports_stale_assignment_before_circuit_fallback() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    payload = appliance_detail_payload(
        [_nilm_coordinator()],
        circuit_id="mains",
        assignment_id="missing-assignment",
    )

    assert payload["status"] == "not_found"
    assert payload["requested_circuit_id"] == "mains"
    assert payload["requested_assignment_id"] == "missing-assignment"
    assert payload["detail"] is None
    assert payload["actions"] == {}
    assert payload["message"] == (
        "The requested NILM appliance assignment is no longer available."
    )
    assert payload["next_step"] == (
        "Open the NILM workspace to review current appliance assignments."
    )


@pytest.mark.parametrize(
    ("profile", "mode"),
    [
        (ApplianceProfile.MAINS_NILM, CircuitMode.MAINS_NILM),
        (ApplianceProfile.MIXED, CircuitMode.MIXED),
        (ApplianceProfile.HVAC, CircuitMode.MIXED),
    ],
)
def test_appliance_detail_offers_load_separation_for_each_source(
    profile: ApplianceProfile, mode: CircuitMode
) -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    config = _config("source", profile=profile, mode=mode)
    coordinator = SimpleNamespace(
        circuit_configs=(config,),
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
        entry_id="entry-1",
    )

    payload = appliance_detail_payload([coordinator], circuit_id="source")

    assert payload["actions"]["open_load_separation"] == {
        "type": "navigate",
        "label": "Open Load Separation",
        "path": (
            "/circuitsetup-energy-analyzer-evidence?"
            "nilm_workspace=1&entry_id=entry-1&circuit_id=source"
        ),
    }


def test_appliance_detail_omits_load_separation_for_dedicated_circuit() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    payload = appliance_detail_payload([_direct_coordinator()], circuit_id="fridge")

    assert "open_load_separation" not in payload["actions"]


def test_appliance_detail_payload_reports_missing_ids_friendly() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    payload = appliance_detail_payload([_direct_coordinator()], circuit_id="missing")

    assert payload == {
        "status": "not_found",
        "requested_circuit_id": "missing",
        "requested_assignment_id": None,
        "detail": None,
        "actions": {},
        "message": "No appliance detail is available for the requested appliance.",
        "next_step": (
            "Open the generated dashboard or review the appliance summary sensors."
        ),
    }


def test_nilm_appliance_detail_includes_assignment_alerts() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    coordinator = _nilm_coordinator()
    coordinator.state.active_alerts_by_circuit["mains"] = [
        AlertEvidence(
            timestamp=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
            circuit_id="mains",
            severity=Severity.WARNING,
            message="Dishwasher estimate needs review.",
            feature="nilm_assignment",
            features={"assignment_id": "assignment-dishwasher"},
        ),
        AlertEvidence(
            timestamp=datetime(2026, 6, 30, 12, 5, tzinfo=UTC),
            circuit_id="mains",
            severity=Severity.WARNING,
            message="Other estimate needs review.",
            feature="nilm_assignment",
            features={"assignment_id": "assignment-other"},
        ),
    ]

    payload = appliance_detail_payload(
        [coordinator],
        assignment_id="assignment-dishwasher",
    )

    active_alerts = payload["detail"]["active_alerts"]
    assert len(active_alerts) == 1
    alert = active_alerts[0]
    assert alert["alert_id"].startswith(
        "circuitsetup_energy_analyzer_alert_mains_nilm_assignment_"
    )
    assert alert["feature"] == "nilm_assignment"
    assert alert["severity"] == "warning"
    assert alert["message"] == "Dishwasher estimate needs review."
    assert alert["evidence_path"].startswith(
        "/circuitsetup-energy-analyzer-evidence?circuit_id=mains&alert_id="
    )
    assert alert["observed_value"] == 0.0
    assert alert["baseline_value"] == 0.0
    assert alert["change_ratio"] == 0.0
    assert alert["repeated_count"] == 1


def test_appliance_views_register_with_panel_views() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import _register_view
    from custom_components.circuitsetup_energy_analyzer.panel_contracts import (
        APPLIANCE_DETAIL_API_PATH,
        APPLIANCE_INSIGHTS_API_PATH,
    )

    registered = []
    hass = SimpleNamespace(
        http=SimpleNamespace(register_view=lambda view: registered.append(view)),
    )

    _register_view(hass)

    views_by_url = {view.url: view for view in registered}
    assert APPLIANCE_DETAIL_API_PATH in views_by_url
    assert APPLIANCE_INSIGHTS_API_PATH in views_by_url
    assert views_by_url[APPLIANCE_INSIGHTS_API_PATH].requires_auth is True
    assert {view.name for view in registered} >= {
        f"api:{DOMAIN}:alert_evidence",
        f"api:{DOMAIN}:nilm_workspace",
        f"api:{DOMAIN}:appliance_detail",
        f"api:{DOMAIN}:appliance_insights",
    }
