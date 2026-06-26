from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    EventType,
    SensorRef,
    SensorRole,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.notifications import (
    notification_id_for_alert,
)


def _alert(
    circuit_id: str = "hvac",
    feature: str = "leg_imbalance",
    *,
    timestamp: datetime | None = None,
    **overrides,
) -> AlertEvidence:
    timestamp = timestamp or datetime(2026, 6, 6, 9, 0, tzinfo=UTC)
    return AlertEvidence(
        timestamp=timestamp,
        circuit_id=circuit_id,
        severity=Severity.WARNING,
        message=f"Possible issue: {circuit_id} {feature}",
        feature=feature,
        observed_value=62.0,
        baseline_value=20.0,
        change_ratio=2.1,
        repeated_count=3,
        first_seen=timestamp - timedelta(hours=1),
        last_seen=timestamp,
        features={feature: 2.1},
        **overrides,
    )


def _config(circuit_id: str = "hvac") -> CircuitConfig:
    return CircuitConfig(
        circuit_id=circuit_id,
        name="HVAC" if circuit_id == "hvac" else circuit_id.replace("_", " ").title(),
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(
            SensorRef(f"sensor.{circuit_id}_l1_watts", SensorRole.REAL_POWER, leg="a"),
            SensorRef(f"sensor.{circuit_id}_l2_watts", SensorRole.REAL_POWER, leg="b"),
            SensorRef(f"sensor.{circuit_id}_l1_current", SensorRole.CURRENT, leg="a"),
            SensorRef(f"sensor.{circuit_id}_l2_current", SensorRole.CURRENT, leg="b"),
        ),
    )


def _coordinator(
    *alerts: AlertEvidence,
    config: CircuitConfig | None = None,
    configs: tuple[CircuitConfig, ...] | None = None,
):
    default_config = config or _config(alerts[0].circuit_id if alerts else "hvac")
    return SimpleNamespace(
        store_data=SimpleNamespace(alerts=list(alerts)),
        circuit_configs=configs or (default_config,),
        state=SimpleNamespace(alert_evidence_by_circuit={}),
    )


def test_alert_evidence_payload_matches_exact_alert_id() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert()
    payload = alert_evidence_payload(
        [_coordinator(alert)],
        alert_id=notification_id_for_alert(alert),
    )

    assert payload["status"] == "matched_alert"
    assert payload["alert"]["alert_id"] == notification_id_for_alert(alert)
    assert payload["alert"]["circuit_id"] == "hvac"
    assert payload["alert"]["feature"] == "leg_imbalance"
    assert payload["alert"]["feature_name"] == "Leg Imbalance"
    assert payload["alert"]["what_happened"].startswith("Leg Imbalance changed")
    assert "Verify both CTs" in payload["alert"]["what_to_check_first"]
    assert payload["alert"]["graph_entities"] == [
        "sensor.hvac_l1_watts",
        "sensor.hvac_l2_watts",
        "sensor.hvac_l1_current",
        "sensor.hvac_l2_current",
    ]
    assert payload["circuit"] == {
        "circuit_id": "hvac",
        "name": "HVAC",
        "appliance_profile": "hvac",
        "mode": "dual_phase",
    }
    assert payload["actions"]["acknowledge"]["service"] == "acknowledge_alert"
    assert payload["actions"]["acknowledge"]["data"] == {
        "alert_id": notification_id_for_alert(alert)
    }
    assert payload["actions"]["mark_expected"]["service"] == "mark_alert_expected"
    assert payload["actions"]["mark_unhelpful"]["service"] == "mark_alert_unhelpful"
    assert payload["actions"]["pause_alerts"] == {
        "domain": DOMAIN,
        "service": "pause_alerts",
        "data": {"circuit_id": "hvac"},
    }
    assert payload["actions"]["start_maintenance"]["data"] == {"circuit_id": "hvac"}
    assert payload["actions"]["relearn_baseline"]["data"] == {"circuit_id": "hvac"}
    assert payload["actions"]["open_advanced_circuit_settings"]["path"].startswith(
        "/config/integrations/"
    )
    assert "workspace_call_api_path" not in payload["nilm"]


def test_alert_evidence_payload_explains_expected_feedback_state() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    fingerprint = (
        "hvac|runtime_high|sources=real_power|observed=3.0-3.5|ratio=25-50pct"
    )
    alert = _alert(
        feedback_status="expected",
        feedback_effect="Notifications suppressed for this expected pattern",
        feedback_expires_at=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
        matching_feedback_fingerprint=fingerprint,
    )

    payload = alert_evidence_payload(
        [_coordinator(alert)],
        alert_id=notification_id_for_alert(alert),
    )

    assert payload["alert"]["feedback_status"] == "expected"
    assert payload["alert"]["feedback_effect"] == (
        "Notifications suppressed for this expected pattern"
    )
    assert payload["alert"]["feedback_expires_at"] == (
        "2026-09-15T12:00:00+00:00"
    )
    assert payload["alert"]["matching_feedback_fingerprint"] == fingerprint


def test_alert_evidence_payload_explains_unhelpful_adjusted_requirement() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    fingerprint = (
        "hvac|runtime_high|sources=real_power|observed=3.0-3.5|ratio=25-50pct"
    )
    alert = _alert(
        feedback_status="unhelpful",
        feedback_effect="Future matching alerts require stronger repeated evidence",
        feedback_expires_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        matching_feedback_fingerprint=fingerprint,
        adjusted_min_repeated=5,
    )

    payload = alert_evidence_payload(
        [_coordinator(alert)],
        alert_id=notification_id_for_alert(alert),
    )

    assert payload["alert"]["feedback_status"] == "unhelpful"
    assert payload["alert"]["feedback_effect"] == (
        "Future matching alerts require stronger repeated evidence"
    )
    assert payload["alert"]["adjusted_min_repeated"] == 5


def test_alert_evidence_payload_anchors_advanced_settings_to_entry_and_circuit() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert(circuit_id="car_charger", feature="demand_monthly_peak")
    coordinator = _coordinator(alert, config=_config("car_charger"))
    coordinator.entry_id = "entry-car-charger"

    payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
        circuit_id="car_charger",
        feature="demand_monthly_peak",
    )

    action = payload["actions"]["open_advanced_circuit_settings"]
    parsed = urlparse(action["path"])
    params = parse_qs(parsed.fragment)
    assert parsed.path == (
        "/config/integrations/integration/circuitsetup_energy_analyzer"
    )
    assert params["config_entry"] == ["entry-car-charger"]
    assert params["circuit_id"] == ["car_charger"]
    assert params["options_step"] == ["advanced_settings"]
    assert action["entry_id"] == "entry-car-charger"
    assert action["circuit_id"] == "car_charger"
    assert action["options_step"] == "advanced_settings"


def test_panel_navigation_dispatches_home_assistant_route_detail() -> None:
    panel_script = Path(
        "custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-panel.js"
    ).read_text(encoding="utf-8")

    assert 'new CustomEvent("location-changed"' in panel_script
    assert "detail: { replace: false }" in panel_script


def test_alert_evidence_payload_bounds_source_entity_previews() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert(circuit_id="panel", feature="metric_consistency")
    config = CircuitConfig(
        circuit_id="panel",
        name="Panel",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=tuple(
            SensorRef(f"sensor.panel_source_{index:02d}", SensorRole.REAL_POWER)
            for index in range(9)
        ),
    )
    payload = alert_evidence_payload(
        [_coordinator(alert, config=config)],
        alert_id=notification_id_for_alert(alert),
    )

    assert payload["alert"]["source_entities"] == [
        "sensor.panel_source_00",
        "sensor.panel_source_01",
        "sensor.panel_source_02",
        "sensor.panel_source_03",
        "sensor.panel_source_04",
    ]
    assert payload["alert"]["source_entities_count"] == 9
    assert payload["alert"]["source_entities_has_more"] is True
    assert payload["alert"]["source_entities_omitted_count"] == 4


def test_alert_evidence_payload_switches_to_end_maintenance_when_active() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert()
    coordinator = _coordinator(alert)
    coordinator.state.maintenance_by_circuit = {"hvac": {"active": True}}

    payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
    )

    assert "start_maintenance" not in payload["actions"]
    assert payload["actions"]["end_maintenance"] == {
        "domain": DOMAIN,
        "service": "end_maintenance",
        "data": {"circuit_id": "hvac"},
    }
    assert payload["actions"]["pause_alerts"] == {
        "domain": DOMAIN,
        "service": "pause_alerts",
        "data": {"circuit_id": "hvac"},
        "enabled": False,
        "unavailable_reason": "alerts_paused",
        "unavailable_label": "Alerts are already paused for this circuit.",
    }


def test_alert_evidence_payload_marks_pause_alerts_unavailable_without_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    coordinator = _coordinator()
    coordinator.state.alert_evidence_by_circuit = {
        "hvac": {
            "alert_id": None,
            "circuit_id": "hvac",
            "feature": "leg_imbalance",
            "feature_name": "Leg Imbalance",
            "message": "Previous issue",
        }
    }

    payload = alert_evidence_payload([coordinator], circuit_id="hvac")

    assert payload["actions"]["pause_alerts"] == {
        "domain": DOMAIN,
        "service": "pause_alerts",
        "data": {"circuit_id": "hvac"},
        "enabled": False,
        "unavailable_reason": "no_active_alert",
        "unavailable_label": "No active alert is available to pause.",
    }


def test_alert_evidence_payload_includes_setting_recommendation_actions() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert()
    coordinator = _coordinator(alert)
    coordinator.entry_id = "entry-1"
    coordinator.state.settings_recommendations_by_circuit = {
        "hvac": [
            {
                "recommendation_id": "hvac:daily_spike_ratio:v1",
                "title": "Raise daily spike threshold",
            }
        ]
    }

    payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
    )

    assert payload["setting_recommendations"][0]["recommendation_id"] == (
        "hvac:daily_spike_ratio:v1"
    )
    assert payload["setting_recommendations"][0]["title"] == (
        "Raise daily spike threshold"
    )
    assert payload["setting_recommendations"][0]["actions"]["apply"]["data"] == {
        "recommendation_id": "hvac:daily_spike_ratio:v1",
        "entry_id": "entry-1",
    }
    assert payload["actions"]["apply_setting_recommendation"] == {
        "domain": DOMAIN,
        "service": "apply_setting_recommendation",
        "data": {
            "recommendation_id": "hvac:daily_spike_ratio:v1",
            "entry_id": "entry-1",
        },
    }
    assert "deny_setting_recommendation" not in payload["actions"]
    assert payload["actions"]["dismiss_setting_recommendation"]["data"] == {
        "recommendation_id": "hvac:daily_spike_ratio:v1",
        "entry_id": "entry-1",
    }


def test_alert_evidence_payload_advertises_only_pending_recommendation_actions() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert()
    coordinator = _coordinator(alert)
    coordinator.entry_id = "entry-1"
    coordinator.state.settings_recommendations_by_circuit = {
        "hvac": [
            {
                "recommendation_id": "hvac:already_applied:v1",
                "title": "Already applied",
                "status": "applied",
            },
            {
                "recommendation_id": "hvac:pending:v1",
                "title": "Pending suggestion",
                "status": "pending",
            },
        ]
    }

    payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
    )

    assert payload["actions"]["apply_setting_recommendation"]["data"] == {
        "recommendation_id": "hvac:pending:v1",
        "entry_id": "entry-1",
    }

    coordinator.state.settings_recommendations_by_circuit = {
        "hvac": [
            {
                "recommendation_id": "hvac:already_applied:v1",
                "title": "Already applied",
                "status": "applied",
            }
        ]
    }

    payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
    )

    assert "apply_setting_recommendation" not in payload["actions"]
    assert "deny_setting_recommendation" not in payload["actions"]
    assert "dismiss_setting_recommendation" not in payload["actions"]


def test_alert_evidence_payload_includes_per_recommendation_actions() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert()
    coordinator = _coordinator(alert)
    coordinator.entry_id = "entry-1"
    coordinator.state.settings_recommendations_by_circuit = {
        "hvac": [
            {
                "recommendation_id": "hvac:daily_spike_ratio:v1",
                "title": "Raise daily spike threshold",
                "feature": "daily_spike_ratio",
            },
            {
                "recommendation_id": "hvac:standby_threshold_w:v1",
                "feature": "standby_threshold_w",
                "setting_label": "Standby threshold",
            },
        ]
    }

    payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
    )

    assert payload["setting_recommendations"][0]["actions"]["apply"]["data"] == {
        "recommendation_id": "hvac:daily_spike_ratio:v1",
        "entry_id": "entry-1",
    }
    assert "deny" not in payload["setting_recommendations"][0]["actions"]
    assert payload["setting_recommendations"][0]["actions"]["dismiss"]["service"] == (
        "dismiss_setting_recommendation"
    )
    assert payload["setting_recommendations"][0]["actions"]["undo"]["service"] == (
        "undo_setting_recommendation"
    )
    assert payload["setting_recommendations"][0]["actions"]["undo"][
        "enabled"
    ] is False
    assert payload["setting_recommendations"][0]["actions"]["reset"]["service"] == (
        "reset_setting_recommendation"
    )
    assert payload["setting_recommendations"][0]["actions"]["reset"][
        "enabled"
    ] is True
    assert payload["setting_recommendations"][0]["display_label"] == (
        "Raise daily spike threshold"
    )
    assert payload["setting_recommendations"][1]["actions"]["apply"]["data"] == {
        "recommendation_id": "hvac:standby_threshold_w:v1",
        "entry_id": "entry-1",
    }
    assert payload["setting_recommendations"][1]["display_label"] == (
        "Standby threshold"
    )


def test_alert_evidence_payload_enables_undo_for_applied_recommendations() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert()
    coordinator = _coordinator(alert)
    coordinator.entry_id = "entry-1"
    coordinator.state.settings_recommendations_by_circuit = {
        "hvac": [
            {
                "recommendation_id": "hvac:daily_spike_ratio:v1",
                "title": "Raise daily spike threshold",
                "feature": "daily_spike_ratio",
                "status": "applied",
            }
        ]
    }

    payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
    )

    actions = payload["setting_recommendations"][0]["actions"]
    assert actions["apply"]["enabled"] is False
    assert "deny" not in actions
    assert actions["dismiss"]["enabled"] is False
    assert actions["undo"]["enabled"] is True
    assert actions["undo"]["data"] == {
        "recommendation_id": "hvac:daily_spike_ratio:v1",
        "entry_id": "entry-1",
    }
    assert actions["reset"]["enabled"] is True


def test_alert_evidence_payload_guides_recommendation_preview() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert(circuit_id="ev_charger", feature="capacity_warning_ratio")
    coordinator = _coordinator(alert, config=_config("ev_charger"))
    coordinator.entry_id = "entry-1"
    coordinator.state.settings_recommendations_by_circuit = {
        "ev_charger": [
            {
                "recommendation_id": "ev_charger:warning_ratio:v1",
                "circuit_id": "ev_charger",
                "setting_key": "warning_ratio",
                "setting_label": "Capacity Warning Ratio",
                "current_value": 0.9,
                "suggested_value": 0.75,
                "reason": "Observed sustained high-current samples.",
                "evidence": {
                    "observed_samples": 8,
                    "p95_current_amps": 36.4,
                    "source_entities": ["sensor.ev_charger_current"],
                },
            }
        ]
    }

    payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
    )

    recommendation = payload["setting_recommendations"][0]
    assert recommendation["default_value"] == 0.8
    assert recommendation["expected_effect"].startswith(
        "Warn earlier when usage approaches capacity"
    )
    assert recommendation["evidence_preview"] == (
        "Observed Samples: 8; P95 Current Amps: 36.4"
    )
    assert "source_entities" not in recommendation["evidence_preview"]
    assert recommendation["evidence_path"] == (
        "/circuitsetup-energy-analyzer-evidence"
        "?circuit_id=ev_charger&recommendation_id=ev_charger%3Awarning_ratio%3Av1"
    )
    assert recommendation["actions"]["preview"] == {
        "path": recommendation["evidence_path"],
    }


def test_alert_evidence_payload_selects_requested_recommendation_preview() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert(circuit_id="ev_charger", feature="capacity_warning_ratio")
    coordinator = _coordinator(alert, config=_config("ev_charger"))
    coordinator.entry_id = "entry-1"
    recommendation_id = "ev_charger:warning_ratio:v1"
    coordinator.state.settings_recommendations_by_circuit = {
        "ev_charger": [
            {
                "recommendation_id": recommendation_id,
                "circuit_id": "ev_charger",
                "setting_key": "warning_ratio",
                "setting_label": "Capacity Warning Ratio",
                "current_value": 0.9,
                "suggested_value": 0.75,
                "reason": "Observed sustained high-current samples.",
                "evidence": {
                    "observed_samples": 8,
                    "p95_current_amps": 36.4,
                    "source_entities": ["sensor.ev_charger_current"],
                },
            }
        ]
    }

    payload = alert_evidence_payload(
        [coordinator],
        circuit_id="ev_charger",
        recommendation_id=recommendation_id,
    )

    assert payload["requested_recommendation_id"] == recommendation_id
    selected = payload["selected_recommendation"]
    assert selected["recommendation_id"] == recommendation_id
    assert selected["display_label"] == "Capacity Warning Ratio"
    assert selected["evidence_preview"] == (
        "Observed Samples: 8; P95 Current Amps: 36.4"
    )


def test_alert_evidence_payload_guides_always_on_recommendations() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert(circuit_id="washer", feature="standby_always_on")
    coordinator = _coordinator(alert, config=_config("washer"))
    coordinator.entry_id = "entry-1"
    coordinator.state.settings_recommendations_by_circuit = {
        "washer": [
            {
                "recommendation_id": "washer:always_on_alert_w:v1",
                "circuit_id": "washer",
                "setting_key": "always_on_alert_w",
                "setting_label": "Always On Alert W",
                "current_value": 0.0,
                "suggested_value": 35.0,
                "reason": "Observed elevated always-on draw.",
                "evidence": {"p95_always_on_w": 42.5},
            }
        ]
    }

    payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
    )

    recommendation = payload["setting_recommendations"][0]
    assert recommendation["default_value"] == 0.0
    assert recommendation["expected_effect"].startswith(
        "Surface unusually high Always On draw"
    )
    assert recommendation["evidence_preview"] == "P95 Always On W: 42.5"


def test_alert_evidence_payload_guides_flexible_load_recommendations() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert(circuit_id="mains", feature="solar_flow")
    coordinator = _coordinator(alert, config=_config("mains"))
    coordinator.entry_id = "entry-1"
    coordinator.state.settings_recommendations_by_circuit = {
        "mains": [
            {
                "recommendation_id": "mains:flexible_load_running_threshold_w:v1",
                "circuit_id": "mains",
                "setting_key": "flexible_load_running_threshold_w",
                "setting_label": "Flexible Load Running Threshold W",
                "current_value": 100.0,
                "suggested_value": 175.0,
                "reason": "Observed low idle draw on flexible loads.",
                "evidence": {"observed_flexible_loads": 3},
            }
        ]
    }

    payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
    )

    recommendation = payload["setting_recommendations"][0]
    assert recommendation["default_value"] == 100.0
    assert recommendation["expected_effect"].startswith(
        "Classify flexible loads as running only after"
    )
    assert recommendation["evidence_preview"] == "Observed Flexible Loads: 3"


def test_alert_evidence_payload_bounds_recommendation_evidence() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert(circuit_id="ev_charger", feature="capacity_warning_ratio")
    coordinator = _coordinator(alert, config=_config("ev_charger"))
    coordinator.state.settings_recommendations_by_circuit = {
        "ev_charger": [
            {
                "recommendation_id": "ev_charger:warning_ratio:v1",
                "circuit_id": "ev_charger",
                "setting_key": "warning_ratio",
                "evidence": {
                    "observed_samples": 8,
                    "p95_current_amps": 36.4,
                    "median_current_amps": 31.2,
                    "spike_count": 3,
                    "long_notes": "x" * 5000,
                    "source_entities": [
                        f"sensor.ev_charger_{index}" for index in range(50)
                    ],
                    "sample_history": [{"watts": index} for index in range(200)],
                    "nested_summary": {"p95": 36.4},
                },
            }
        ]
    }

    payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
    )

    recommendation = payload["setting_recommendations"][0]
    assert "evidence" not in recommendation
    assert recommendation["evidence_preview"] == (
        "Observed Samples: 8; P95 Current Amps: 36.4; "
        "Median Current Amps: 31.2; Spike Count: 3"
    )
    assert recommendation["evidence_key_count"] == 8
    assert recommendation["evidence_preview_key_count"] == 4
    assert recommendation["evidence_omitted_key_count"] == 4
    assert recommendation["evidence_has_more"] is True


def test_alert_evidence_payload_includes_nilm_guided_actions() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert(circuit_id="mains", feature="nilm_unknown_load")
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(alert, config=config)
    coordinator.state.nilm_unknown_loads_by_circuit = {
        "mains": {
            "unknown_loads": [
                {
                    "signature_id": "signature_1",
                    "display_name": "Motor-like load",
                    "likely_type": "motor",
                }
            ]
        }
    }

    payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
    )

    assert payload["nilm"]["signatures"][0]["signature_id"] == "signature_1"
    assert payload["nilm"]["signatures"][0]["display_label"] == "Motor-like load"
    assert payload["nilm"]["signatures"][0]["actions"]["label"]["service"] == (
        "label_nilm_signature"
    )
    assert payload["nilm"]["workspace_call_api_path"].endswith("circuit_id=mains")
    assert payload["nilm"]["signatures"][0]["actions"]["ignore"] == {
        "domain": DOMAIN,
        "service": "ignore_nilm_signature",
        "data": {"circuit_id": "mains", "signature_id": "signature_1"},
    }
    assert payload["nilm"]["signatures"][0]["actions"]["mark_expected"]["data"] == {
        "circuit_id": "mains",
        "signature_id": "signature_1",
    }
    assert payload["nilm"]["signatures"][0]["actions"]["merge"]["enabled"] is False
    assert (
        payload["nilm"]["signatures"][0]["actions"]["merge"]["unavailable_reason"]
        == "no_merge_target"
    )
    assert (
        payload["nilm"]["signatures"][0]["actions"]["merge"]["unavailable_label"]
        == "No other NILM signature is available to merge into yet."
    )


def test_alert_evidence_payload_includes_selectable_nilm_merge_targets() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert(circuit_id="mains", feature="nilm_unknown_load")
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(alert, config=config)
    coordinator.state.nilm_unknown_loads_by_circuit = {
        "mains": {
            "unknown_loads": [
                {
                    "signature_id": "signature_1",
                    "display_name": "Motor-like load",
                    "likely_type": "motor",
                    "typical_watts": 3800.0,
                    "confidence": 0.72,
                    "first_seen": "2026-06-10T09:00:00+00:00",
                },
                {
                    "signature_id": "signature_2",
                    "display_name": "Pool pump-like load",
                    "likely_type": "pump",
                    "typical_watts": 1100.0,
                    "confidence": 0.65,
                    "first_seen": "2026-06-09T09:00:00+00:00",
                },
            ]
        }
    }

    payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
    )

    merge_action = payload["nilm"]["signatures"][0]["actions"]["merge"]
    assert payload["nilm"]["signatures"][0]["display_label"] == (
        "Motor-like load, 3.8 kW, confidence 72%, first seen 2026-06-10"
    )
    assert merge_action["data"] == {
        "circuit_id": "mains",
        "source_signature_id": "signature_1",
    }
    assert merge_action["target_options"] == [
        {
            "value": "signature_2",
            "label": (
                "Pool pump-like load, 1.1 kW, confidence 65%, first seen 2026-06-09"
            ),
        }
    ]


def test_alert_evidence_payload_overlays_saved_nilm_review_state_on_inventory() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert(circuit_id="mains", feature="nilm_unknown_load")
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(alert, config=config)
    coordinator.state.nilm_unknown_loads_by_circuit = {
        "mains": {
            "unknown_loads": [
                {
                    "signature_id": "signature_1",
                    "display_name": "Motor-like load",
                    "likely_type": "motor",
                    "typical_watts": 3800.0,
                },
                {
                    "signature_id": "signature_2",
                    "display_name": "Pump-like load",
                    "likely_type": "pump",
                },
                {
                    "signature_id": "signature_3",
                    "display_name": "Heater-like load",
                    "likely_type": "heater",
                },
            ]
        }
    }
    coordinator.store_data.nilm_signatures = {
        "mains": [
            {
                "signature_id": "signature_1",
                "user_label": "Pool Pump",
                "review_state": "expected",
                "expected": True,
            },
            {
                "signature_id": "signature_2",
                "ignored": True,
            },
            {
                "signature_id": "signature_3",
                "review_state": "merged",
                "merged_into": "signature_1",
            },
        ]
    }

    payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
    )

    signatures = payload["nilm"]["signatures"]
    assert signatures[0]["user_label"] == "Pool Pump"
    assert signatures[0]["display_label"] == "Pool Pump, 3.8 kW"
    assert signatures[0]["review_state"] == "expected"
    assert signatures[0]["expected"] is True
    assert signatures[1]["review_state"] == "ignored"
    assert signatures[1]["ignored"] is True
    assert signatures[2]["review_state"] == "merged"
    assert signatures[2]["merged_into"] == "signature_1"


def test_alert_evidence_payload_bounds_large_nilm_payloads() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert(circuit_id="mains", feature="nilm_unknown_load")
    config = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(alert, config=config)
    coordinator.state.nilm_unknown_loads_by_circuit = {
        "mains": {
            "unknown_loads": [
                {
                    "signature_id": f"signature_{index}",
                    "display_name": f"Unknown load {index}",
                    "likely_type": "motor",
                    "typical_watts": 1000.0 + index,
                    "confidence": 0.70,
                    "sample_history": [index] * 20,
                }
                for index in range(8)
            ]
        }
    }

    payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
    )

    nilm = payload["nilm"]
    assert nilm["signature_count"] == 8
    assert nilm["signatures_has_more"] is True
    assert nilm["signatures_omitted_count"] == 3
    assert [signature["signature_id"] for signature in nilm["signatures"]] == [
        "signature_0",
        "signature_1",
        "signature_2",
        "signature_3",
        "signature_4",
    ]
    assert all("sample_history" not in signature for signature in nilm["signatures"])

    merge_action = nilm["signatures"][0]["actions"]["merge"]
    assert merge_action["target_option_count"] == 7
    assert merge_action["target_options_has_more"] is True
    assert merge_action["target_options_omitted_count"] == 2
    assert [option["value"] for option in merge_action["target_options"]] == [
        "signature_1",
        "signature_2",
        "signature_3",
        "signature_4",
        "signature_5",
    ]

    expanded_payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
        include_all_nilm=True,
    )

    expanded_nilm = expanded_payload["nilm"]
    assert expanded_nilm["signature_count"] == 8
    assert expanded_nilm["signatures_has_more"] is False
    assert expanded_nilm["signatures_omitted_count"] == 0
    assert [signature["signature_id"] for signature in expanded_nilm["signatures"]] == [
        f"signature_{index}" for index in range(8)
    ]
    assert all(
        "sample_history" not in signature for signature in expanded_nilm["signatures"]
    )

    expanded_merge_action = expanded_nilm["signatures"][0]["actions"]["merge"]
    assert expanded_merge_action["target_option_count"] == 7
    assert expanded_merge_action["target_options_has_more"] is False
    assert expanded_merge_action["target_options_omitted_count"] == 0
    assert [option["value"] for option in expanded_merge_action["target_options"]] == [
        f"signature_{index}" for index in range(1, 8)
    ]


def test_nilm_workspace_payload_is_read_only_and_bounded() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.panel import (
        nilm_workspace_payload,
    )

    mains_config = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(
            SensorRef("sensor.mains_power", SensorRole.REAL_POWER),
            SensorRef("sensor.mains_reactive_power", SensorRole.REACTIVE_POWER),
        ),
    )
    known_config = CircuitConfig(
        circuit_id="pool_pump",
        name="Pool Pump",
        appliance_profile=ApplianceProfile.POOL_PUMP,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.pool_pump_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(
        config=mains_config,
        configs=(mains_config, known_config),
    )
    coordinator._known_load_circuit_ids = frozenset({"pool_pump"})
    coordinator.state.nilm_unknown_loads_by_circuit = {
        "mains": {
            "unknown_loads": [
                {
                    "signature_id": "signature_1",
                    "display_name": "Pump-like load",
                    "typical_watts": 800.0,
                    "confidence": 0.8,
                }
            ]
        }
    }
    coordinator._nilm_unmatched_edges = {
        "mains": [
            NilmEdge(
                timestamp=datetime(2026, 6, 6, 8, 0, tzinfo=UTC),
                delta_w=820.0,
                delta_var=120.0,
                delta_va=830.0,
                delta_pf=-0.05,
                direction="on",
            ),
            NilmEdge(
                timestamp=datetime(2026, 6, 6, 9, 0, tzinfo=UTC),
                delta_w=-815.0,
                delta_var=-118.0,
                delta_va=-825.0,
                delta_pf=0.04,
                direction="off",
            ),
        ]
    }

    payload = nilm_workspace_payload([coordinator], circuit_id="mains", hours="72")

    assert payload["status"] == "ok"
    assert payload["history"]["hours"] == 24.0
    assert payload["history"]["entities"] == [
        "sensor.mains_power",
        "sensor.mains_reactive_power",
        "sensor.pool_pump_power",
    ]
    assert payload["history"]["api_path"].startswith(
        "circuitsetup_energy_analyzer/nilm_workspace_history?"
    )
    assert payload["history"]["fetch_path"].startswith(
        "/api/circuitsetup_energy_analyzer/nilm_workspace_history?"
    )
    assert "minimal_response=1" in payload["history"]["recorder_api_path"]
    assert "no_attributes=1" in payload["history"]["recorder_api_path"]
    assert payload["known_load_overlays"] == [
        {
            "circuit_id": "pool_pump",
            "name": "Pool Pump",
            "entity_ids": ["sensor.pool_pump_power"],
        }
    ]
    assert payload["signatures"][0]["signature_id"] == "signature_1"
    assert "actions" not in payload["signatures"][0]
    assert payload["edges"][0]["direction"] == "on"
    assert payload["sessions"][0]["off_edge_id"] is not None


def test_nilm_workspace_history_rows_are_capped() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        MAX_NILM_WORKSPACE_HISTORY_POINTS_PER_ENTITY,
        _bounded_history_rows,
    )

    rows = {
        "sensor.mains_power": [
            {
                "state": str(index),
                "last_changed": (
                    datetime(2026, 6, 6, tzinfo=UTC) + timedelta(seconds=index)
                ),
            }
            for index in range(MAX_NILM_WORKSPACE_HISTORY_POINTS_PER_ENTITY + 100)
        ]
    }

    bounded = _bounded_history_rows(rows)

    assert len(bounded) == 1
    assert len(bounded[0]) == MAX_NILM_WORKSPACE_HISTORY_POINTS_PER_ENTITY
    assert bounded[0][0]["entity_id"] == "sensor.mains_power"


@pytest.mark.asyncio
async def test_nilm_workspace_history_uses_recorder_executor(monkeypatch) -> None:
    from custom_components.circuitsetup_energy_analyzer import panel

    class FakeRecorder:
        def __init__(self) -> None:
            self.jobs = []

        async def async_add_executor_job(self, job):
            self.jobs.append(job)
            return job()

    recorder = FakeRecorder()

    def fake_history(hass, start, **kwargs):
        assert kwargs["entity_ids"] == ["sensor.mains_power"]
        assert kwargs["minimal_response"] is True
        assert kwargs["no_attributes"] is True
        return {
            "sensor.mains_power": [
                {
                    "entity_id": "sensor.mains_power",
                    "state": "12",
                    "last_changed": start,
                }
            ]
        }

    monkeypatch.setattr(panel, "_history_get_significant_states", lambda: fake_history)
    monkeypatch.setattr(panel, "_recorder_get_instance", lambda hass: recorder)

    rows = await panel._async_history_rows(
        SimpleNamespace(),
        "2026-06-06T08:00:00+00:00",
        "2026-06-06T09:00:00+00:00",
        ["sensor.mains_power"],
    )

    assert len(recorder.jobs) == 1
    assert rows[0][0]["state"] == "12"


def test_alert_evidence_payload_falls_back_to_latest_alert_for_circuit() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    older = _alert(timestamp=datetime(2026, 6, 6, 8, 0, tzinfo=UTC))
    latest = _alert(feature="demand_monthly_peak")

    payload = alert_evidence_payload(
        [_coordinator(older, latest)],
        alert_id="old-notification-id",
        circuit_id="hvac",
    )

    assert payload["status"] == "latest_for_circuit"
    assert payload["requested_alert_id"] == "old-notification-id"
    assert payload["alert"]["alert_id"] == notification_id_for_alert(latest)
    assert payload["alert"]["feature"] == "demand_monthly_peak"
    assert payload["alert"]["feature_name"] == "Demand Monthly Peak"


def test_alert_evidence_payload_prefers_feature_for_circuit_fallback() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    requested_feature = _alert(
        feature="leg_imbalance",
        timestamp=datetime(2026, 6, 6, 8, 0, tzinfo=UTC),
    )
    latest_other_feature = _alert(
        feature="demand_monthly_peak",
        timestamp=datetime(2026, 6, 6, 9, 0, tzinfo=UTC),
    )

    payload = alert_evidence_payload(
        [_coordinator(requested_feature, latest_other_feature)],
        alert_id="stale-notification-id",
        circuit_id="hvac",
        feature="leg_imbalance",
    )

    assert payload["status"] == "latest_for_circuit"
    assert payload["requested_feature"] == "leg_imbalance"
    assert payload["alert"]["alert_id"] == notification_id_for_alert(requested_feature)
    assert payload["alert"]["feature"] == "leg_imbalance"


def test_alert_evidence_payload_uses_event_type_for_feature_fallback() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    timestamp = datetime(2026, 6, 6, 8, 0, tzinfo=UTC)
    requested_feature = AlertEvidence(
        timestamp=timestamp,
        circuit_id="hvac",
        severity=Severity.WARNING,
        message="Possible issue: hvac leg imbalance",
        feature="",
        event_type=EventType.LEG_IMBALANCE,
        observed_value=62.0,
        baseline_value=20.0,
        change_ratio=2.1,
        repeated_count=3,
        first_seen=timestamp - timedelta(hours=1),
        last_seen=timestamp,
        features={"leg_imbalance": 2.1},
    )
    latest_other_feature = _alert(
        feature="demand_monthly_peak",
        timestamp=datetime(2026, 6, 6, 9, 0, tzinfo=UTC),
    )

    payload = alert_evidence_payload(
        [_coordinator(requested_feature, latest_other_feature)],
        alert_id="stale-notification-id",
        circuit_id="hvac",
        feature="leg_imbalance",
    )

    assert payload["status"] == "latest_for_circuit"
    assert payload["requested_feature"] == "leg_imbalance"
    assert payload["alert"]["alert_id"] == notification_id_for_alert(requested_feature)
    assert payload["alert"]["feature"] == "leg_imbalance"


@pytest.mark.asyncio
async def test_alert_evidence_view_forwards_requested_feature_for_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import panel

    requested_feature = _alert(
        feature="leg_imbalance",
        timestamp=datetime(2026, 6, 6, 8, 0, tzinfo=UTC),
    )
    latest_other_feature = _alert(
        feature="demand_monthly_peak",
        timestamp=datetime(2026, 6, 6, 9, 0, tzinfo=UTC),
    )
    coordinator = _coordinator(requested_feature, latest_other_feature)
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    request = SimpleNamespace(
        app={panel.KEY_HASS: hass},
        query={
            "alert_id": "stale-notification-id",
            "circuit_id": "hvac",
            "feature": "leg_imbalance",
        },
    )
    monkeypatch.setattr(panel.web, "json_response", lambda payload: payload)

    payload = await panel.AlertEvidenceView().get(request)

    assert payload["requested_feature"] == "leg_imbalance"
    assert payload["alert"]["alert_id"] == notification_id_for_alert(requested_feature)
    assert payload["alert"]["feature"] == "leg_imbalance"


def test_alert_evidence_payload_reports_not_found_for_unknown_context() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    payload = alert_evidence_payload(
        [_coordinator(_alert())],
        alert_id="missing-alert",
        circuit_id="water_heater",
    )

    assert payload == {
        "status": "not_found",
        "requested_alert_id": "missing-alert",
        "requested_circuit_id": "water_heater",
        "alert": None,
        "circuit": None,
        "actions": {},
        "message": ("The requested alert or circuit evidence is no longer available."),
        "next_step": (
            "Open a newer notification or review the appliance summary sensors."
        ),
    }


def test_alert_evidence_payload_keeps_known_stale_circuit_actionable() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    payload = alert_evidence_payload([_coordinator()], circuit_id="hvac")

    assert payload["status"] == "circuit_found_no_evidence"
    assert payload["requested_circuit_id"] == "hvac"
    assert payload["alert"] is None
    assert payload["circuit"] == {
        "circuit_id": "hvac",
        "name": "HVAC",
        "appliance_profile": "hvac",
        "mode": "dual_phase",
    }
    assert payload["message"] == (
        "No current alert evidence is available for this circuit."
    )
    assert payload["actions"]["relearn_baseline"]["data"] == {"circuit_id": "hvac"}
    assert payload["actions"]["start_maintenance"]["data"] == {"circuit_id": "hvac"}
    assert payload["actions"]["pause_alerts"]["enabled"] is False
    assert payload["actions"]["open_advanced_circuit_settings"]["path"].startswith(
        "/config/integrations/"
    )


def test_alert_evidence_payload_keeps_requested_circuit_after_stale_alert_id() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    coordinator = _coordinator(config=_config("car_charger"))

    payload = alert_evidence_payload(
        [coordinator],
        alert_id="old-car-charger-alert",
        circuit_id="car_charger",
        feature="demand_monthly_peak",
    )

    assert payload["status"] == "circuit_found_no_evidence"
    assert payload["requested_alert_id"] == "old-car-charger-alert"
    assert payload["requested_circuit_id"] == "car_charger"
    assert payload["requested_feature"] == "demand_monthly_peak"
    assert payload["circuit"]["circuit_id"] == "car_charger"
    assert payload["actions"]["pause_alerts"]["data"] == {
        "circuit_id": "car_charger"
    }
    assert payload["actions"]["start_maintenance"]["data"] == {
        "circuit_id": "car_charger"
    }


def test_alert_evidence_payload_checks_later_coordinators_before_stale_fallback() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert(circuit_id="hvac", feature="demand_monthly_peak")

    payload = alert_evidence_payload(
        [
            _coordinator(config=_config("hvac")),
            _coordinator(alert, config=_config("hvac")),
        ],
        circuit_id="hvac",
    )

    assert payload["status"] == "latest_for_circuit"
    assert payload["alert"]["alert_id"] == notification_id_for_alert(alert)
    assert payload["alert"]["feature"] == "demand_monthly_peak"


@pytest.mark.asyncio
async def test_panel_setup_registers_static_api_and_panel_once() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        EVIDENCE_API_PATH,
        NILM_WORKSPACE_API_PATH,
        NILM_WORKSPACE_HISTORY_API_PATH,
        PANEL_ELEMENT_NAME,
        PANEL_MODULE_VERSION,
        PANEL_URL_PATH,
        STATIC_URL_PATH,
        async_setup_panel,
        async_unload_panel,
    )

    class FakeHttp:
        def __init__(self) -> None:
            self.static_paths = []
            self.views = []

        async def async_register_static_paths(self, paths) -> None:
            self.static_paths.extend(paths)

        def register_view(self, view) -> None:
            self.views.append(view)

    class FakePanelCustom:
        def __init__(self) -> None:
            self.panels = []

        async def async_register_panel(self, hass, **kwargs) -> None:
            self.panels.append(kwargs)

    class FakeFrontend:
        def __init__(self) -> None:
            self.removed = []

        def async_remove_panel(self, hass, frontend_url_path, **kwargs) -> None:
            self.removed.append((frontend_url_path, kwargs))

    http = FakeHttp()
    panel_custom = FakePanelCustom()
    frontend = FakeFrontend()
    hass = SimpleNamespace(
        data={},
        http=http,
        components=SimpleNamespace(panel_custom=panel_custom, frontend=frontend),
    )

    assert await async_setup_panel(hass) is True
    assert await async_setup_panel(hass) is True

    assert len(http.static_paths) == 1
    assert STATIC_URL_PATH in str(http.static_paths[0])
    assert [view.url for view in http.views] == [
        EVIDENCE_API_PATH,
        NILM_WORKSPACE_API_PATH,
        NILM_WORKSPACE_HISTORY_API_PATH,
    ]
    assert len(panel_custom.panels) == 1
    assert panel_custom.panels[0]["frontend_url_path"] == PANEL_URL_PATH
    assert panel_custom.panels[0]["webcomponent_name"] == PANEL_ELEMENT_NAME
    assert panel_custom.panels[0].get("sidebar_title") is None
    assert panel_custom.panels[0].get("sidebar_icon") is None
    assert panel_custom.panels[0]["module_url"].endswith(f"?v={PANEL_MODULE_VERSION}")

    await async_unload_panel(hass)

    assert frontend.removed == [(PANEL_URL_PATH, {"warn_if_unknown": False})]
    assert DOMAIN in hass.data


@pytest.mark.asyncio
async def test_setup_entry_registers_and_unloads_panel_with_first_entry() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        async_setup_entry,
        async_unload_entry,
    )
    from custom_components.circuitsetup_energy_analyzer.panel import PANEL_URL_PATH

    class FakeConfigEntries:
        async def async_forward_entry_setups(self, entry, platforms) -> None:
            return None

        async def async_unload_platforms(self, entry, platforms) -> bool:
            return True

    class FakeHttp:
        def __init__(self) -> None:
            self.static_paths = []
            self.views = []

        async def async_register_static_paths(self, paths) -> None:
            self.static_paths.extend(paths)

        def register_view(self, view) -> None:
            self.views.append(view)

    class FakePanelCustom:
        def __init__(self) -> None:
            self.panels = []

        async def async_register_panel(self, hass, **kwargs) -> None:
            self.panels.append(kwargs)

    class FakeFrontend:
        def __init__(self) -> None:
            self.removed = []

        def async_remove_panel(self, hass, frontend_url_path, **kwargs) -> None:
            self.removed.append(frontend_url_path)

    http = FakeHttp()
    panel_custom = FakePanelCustom()
    frontend = FakeFrontend()
    hass = SimpleNamespace(
        data={},
        http=http,
        components=SimpleNamespace(panel_custom=panel_custom, frontend=frontend),
        config_entries=FakeConfigEntries(),
    )
    entry = SimpleNamespace(entry_id="entry-1", data={})

    assert await async_setup_entry(hass, entry) is True

    assert panel_custom.panels[0]["frontend_url_path"] == PANEL_URL_PATH
    assert len(http.static_paths) == 1
    assert len(http.views) == 3

    assert await async_unload_entry(hass, entry) is True

    assert frontend.removed == [PANEL_URL_PATH]


@pytest.mark.asyncio
async def test_setup_entry_registers_panel_once_until_last_entry_unloads() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        async_setup_entry,
        async_unload_entry,
    )
    from custom_components.circuitsetup_energy_analyzer.panel import PANEL_URL_PATH

    class FakeConfigEntries:
        async def async_forward_entry_setups(self, entry, platforms) -> None:
            return None

        async def async_unload_platforms(self, entry, platforms) -> bool:
            return True

    class FakeHttp:
        async def async_register_static_paths(self, paths) -> None:
            return None

        def register_view(self, view) -> None:
            return None

    class FakePanelCustom:
        def __init__(self) -> None:
            self.panels = []

        async def async_register_panel(self, hass, **kwargs) -> None:
            self.panels.append(kwargs)

    class FakeFrontend:
        def __init__(self) -> None:
            self.removed = []

        def async_remove_panel(self, hass, frontend_url_path, **kwargs) -> None:
            self.removed.append(frontend_url_path)

    panel_custom = FakePanelCustom()
    frontend = FakeFrontend()
    hass = SimpleNamespace(
        data={},
        http=FakeHttp(),
        components=SimpleNamespace(panel_custom=panel_custom, frontend=frontend),
        config_entries=FakeConfigEntries(),
    )
    first = SimpleNamespace(entry_id="entry-1", data={})
    second = SimpleNamespace(entry_id="entry-2", data={})

    assert await async_setup_entry(hass, first) is True
    assert await async_setup_entry(hass, second) is True

    assert [panel["frontend_url_path"] for panel in panel_custom.panels] == [
        PANEL_URL_PATH
    ]

    assert await async_unload_entry(hass, first) is True
    assert frontend.removed == []

    assert await async_unload_entry(hass, second) is True
    assert frontend.removed == [PANEL_URL_PATH]


@pytest.mark.asyncio
async def test_panel_setup_refreshes_existing_panel_path() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        PANEL_MODULE_VERSION,
        PANEL_URL_PATH,
        async_setup_panel,
        async_unload_panel,
    )

    class FakeHttp:
        async def async_register_static_paths(self, paths) -> None:
            return None

        def register_view(self, view) -> None:
            return None

    class FakePanelCustom:
        def __init__(self) -> None:
            self.panels = []

        async def async_register_panel(self, hass, **kwargs) -> None:
            self.panels.append(kwargs)

    class FakeFrontend:
        def __init__(self) -> None:
            self.panel_present = True
            self.removed = []

        def async_panel_exists(self, hass, frontend_url_path) -> bool:
            return self.panel_present and frontend_url_path == PANEL_URL_PATH

        def async_remove_panel(self, hass, frontend_url_path, **kwargs) -> None:
            self.removed.append(frontend_url_path)
            self.panel_present = False

    panel_custom = FakePanelCustom()
    frontend = FakeFrontend()
    hass = SimpleNamespace(
        data={},
        http=FakeHttp(),
        components=SimpleNamespace(panel_custom=panel_custom, frontend=frontend),
    )

    assert await async_setup_panel(hass) is True
    assert len(panel_custom.panels) == 1
    assert panel_custom.panels[0]["module_url"].endswith(f"?v={PANEL_MODULE_VERSION}")
    assert frontend.removed == [PANEL_URL_PATH]

    await async_unload_panel(hass)

    assert frontend.removed == [PANEL_URL_PATH, PANEL_URL_PATH]
