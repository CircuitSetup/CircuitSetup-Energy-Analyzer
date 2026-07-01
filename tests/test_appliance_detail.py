from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
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
            SensorRef(f"sensor.{circuit_id}_energy", SensorRole.ENERGY),
        ),
    )


def _direct_state() -> AnalyzerState:
    state = AnalyzerState()
    state.health_summary_by_circuit["fridge"] = "Ready"
    state.data_quality_checklist_by_circuit["fridge"] = {
        "required_sensors_present": True,
        "numeric_states_valid": True,
        "source_data_fresh": True,
    }
    state.latest_real_power_w_by_circuit["fridge"] = 128.4
    state.run_cycle_status_by_circuit["fridge"] = "running"
    state.run_cycle_count_by_circuit["fridge"] = 14
    state.run_cycle_runtime_seconds_by_circuit["fridge"] = 7200.0
    state.daily_energy_usage_by_circuit["fridge"] = 1.82
    state.energy_usage_evidence_by_circuit["fridge"] = {"status": "normal"}
    state.metric_consistency_status_by_circuit["fridge"] = "consistent"
    state.leg_imbalance_status_by_circuit["fridge"] = "balanced"
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
    return SimpleNamespace(
        circuit_configs=(mains,),
        state=AnalyzerState(),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mains": [assignment]},
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


def test_existing_summary_fields_feed_appliance_story() -> None:
    state = _direct_state()

    assert activity_summary_value(state, "fridge") == "Running"
    assert activity_summary_attributes(state, "fridge") == {
        "run_cycle_status": "running",
        "standby_status": "learning",
        "run_cycle_count": 14,
        "run_cycle_runtime_seconds": 7200.0,
        "duty_cycle_percent": 0.0,
        "summary_explanation": "The appliance is currently active.",
    }
    assert energy_summary_value(state, "fridge") == "Normal"
    assert energy_summary_attributes(state, "fridge")[
        "daily_energy_usage_kwh"
    ] == 1.82
    assert electrical_health_attributes(state, "fridge")[
        "what_to_check_first"
    ] == "No electrical check is needed right now."
    assert health_summary_attributes(state, "fridge")["next_step"] == (
        "No action needed"
    )


def test_direct_appliance_detail_payload_uses_existing_summary_state() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    payload = appliance_detail_payload([_direct_coordinator()], circuit_id="fridge")

    assert payload["status"] == "ok"
    detail = payload["detail"]
    assert detail["circuit_id"] == "fridge"
    assert detail["display_name"] == "Kitchen Fridge"
    assert detail["appliance_profile"] == "refrigerator"
    assert detail["source_type"] == "direct_meter"
    assert detail["confidence"] is None
    assert detail["activity_state"] == "Running"
    assert detail["health_state"] == "Ready"
    assert detail["electrical_state"] == "Normal"
    assert detail["energy_state"] == "Normal"
    assert detail["current_power_w"] == 128.4
    assert detail["daily_energy_kwh"] == 1.82
    assert detail["runtime_today_seconds"] == 7200.0
    assert detail["run_count_today"] == 14
    assert detail["cost_today"] is None
    assert detail["next_step"] == "Review alert evidence"
    assert detail["what_to_check_first"] == [
        "No electrical check is needed right now."
    ]
    assert detail["evidence_path"] == (
        "/circuitsetup-energy-analyzer-evidence?circuit_id=fridge"
    )
    assert detail["active_alerts"][0]["feature"] == "daily_energy"
    assert payload["actions"]["open_evidence"]["path"] == detail["evidence_path"]
    assert payload["actions"]["relearn_baseline"]["data"] == {"circuit_id": "fridge"}


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


def test_nilm_appliance_detail_payload_marks_estimated_source() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_detail_payload,
    )

    payload = appliance_detail_payload(
        [_nilm_coordinator()],
        assignment_id="assignment-dishwasher",
    )

    assert payload["status"] == "ok"
    detail = payload["detail"]
    assert detail["circuit_id"] == "mains"
    assert detail["display_name"] == "Dishwasher"
    assert detail["appliance_profile"] == "dishwasher"
    assert detail["source_type"] == "nilm_estimate"
    assert detail["confidence"] == 0.72
    assert detail["model_status"] == "needs_validation"
    assert detail["activity_state"] == "Idle"
    assert detail["health_state"] == "Needs validation"
    assert detail["electrical_state"] == "Estimated by NILM"
    assert detail["energy_state"] == "Estimated"
    assert detail["current_power_w"] == 0.0
    assert detail["daily_energy_kwh"] == 0.818
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
    assert review_query == {
        "circuit_id": ["mains"],
        "assignment_id": ["assignment-dishwasher"],
        "nilm_workspace": ["1"],
    }
    assert payload["actions"]["review_nilm_assignment"] == {
        "type": "navigate",
        "path": review_path,
        "data": {
            "circuit_id": "mains",
            "assignment_id": "assignment-dishwasher",
        },
    }
    assert payload["actions"]["open_evidence"]["path"] == detail["evidence_path"]


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


def test_appliance_detail_view_registers_with_panel_views() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        APPLIANCE_DETAIL_API_PATH,
        _register_view,
    )

    registered = []
    hass = SimpleNamespace(
        http=SimpleNamespace(register_view=lambda view: registered.append(view)),
    )

    _register_view(hass)

    assert APPLIANCE_DETAIL_API_PATH in {view.url for view in registered}
    assert {view.name for view in registered} >= {
        f"api:{DOMAIN}:alert_evidence",
        f"api:{DOMAIN}:nilm_workspace",
        f"api:{DOMAIN}:appliance_detail",
    }
