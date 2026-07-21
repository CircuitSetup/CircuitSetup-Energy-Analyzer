from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    DATA_RELOAD_COUNT,
    DOMAIN,
)
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
        "service": "start_maintenance",
        "label": "Pause Alerts",
        "data": {"circuit_id": "hvac"},
    }
    assert "start_maintenance" not in payload["actions"]
    assert "end_maintenance" not in payload["actions"]
    assert payload["actions"]["relearn_baseline"]["data"] == {"circuit_id": "hvac"}
    detail_action = payload["actions"]["open_appliance_detail"]
    assert detail_action["type"] == "navigate"
    assert parse_qs(urlparse(detail_action["path"]).query) == {
        "circuit_id": ["hvac"],
        "appliance_detail": ["1"],
    }
    assert payload["actions"]["open_advanced_circuit_settings"]["path"].startswith(
        "/config/integrations/"
    )
    assert "workspace_call_api_path" not in payload["nilm"]


def test_alert_evidence_payload_explains_expected_feedback_state() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    fingerprint = "hvac|runtime_high|sources=real_power|observed=3.0-3.5|ratio=25-50pct"
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
    assert payload["alert"]["feedback_expires_at"] == ("2026-09-15T12:00:00+00:00")
    assert payload["alert"]["matching_feedback_fingerprint"] == fingerprint


def test_alert_evidence_payload_explains_unhelpful_adjusted_requirement() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    fingerprint = "hvac|runtime_high|sources=real_power|observed=3.0-3.5|ratio=25-50pct"
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
    assert action["path"] == (
        "/config/integrations/integration/circuitsetup_energy_analyzer"
    )
    assert action["entry_id"] == "entry-car-charger"
    assert action["circuit_id"] == "car_charger"
    assert action["options_step"] == "advanced_settings"


def test_panel_navigation_dispatches_home_assistant_route_detail() -> None:
    panel_script = Path(
        "custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-panel-main.js"
    ).read_text(encoding="utf-8")

    assert 'new CustomEvent("location-changed"' in panel_script
    assert "detail: { replace: false }" in panel_script
    assert 'startsWith("/config/")' in panel_script
    assert "window.location.assign(path)" in panel_script


def test_panel_action_refresh_does_not_rewrite_browser_route() -> None:
    panel_script = Path(
        "custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-panel-main.js"
    ).read_text(encoding="utf-8")

    body = panel_script.split("  _actionRefreshRouteKey(actionKey) {", 1)[1].split(
        "\n  _nilmActionMessage",
        1,
    )[0]
    assert "history.replaceState" not in body
    assert "routeUrl.searchParams.set(EXPAND_NILM_QUERY_PARAM" not in body
    assert "protectedEvidencePanelTarget" not in panel_script


def test_panel_nilm_assignment_save_reloads_after_service_calls() -> None:
    panel_script = Path(
        "custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-nilm-workspace.js"
    ).read_text(encoding="utf-8")

    body = panel_script.split(
        "  async _saveNilmAssignmentChanges(index) {",
        1,
    )[1].split("\n  _routeRequestsNilmWorkspace", 1)[0]
    context_line = "const actionContext = this._nilmWorkspaceActionContext();"
    assert body.index(context_line) < body.index("await this._hass.callService")
    assert body.index("await this._hass.callService") < body.index(
        "await this._refreshNilmWorkspaceData"
    )
    assert "if (!actionContext.isCurrent())" in body
    assert "if (!actionContext.isRouteCurrent())" in body
    assert "this._busyAction === busyKey" in body
    assert "merge.data.target_assignment_id" not in body
    assert "this._selectRefreshedNilmAssignment" in body
    assert "this._storeActionMessageForReload" not in body
    assert "window.location.assign" not in body
    assert "await this._loadEvidence" not in body


def test_panel_nilm_item_actions_refresh_sessions_without_browser_reload() -> None:
    panel_script = Path(
        "custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-nilm-workspace.js"
    ).read_text(encoding="utf-8")

    body = panel_script.split(
        "  async _callNilmWorkspaceItemAction(collectionKey, index, actionKey) {",
        1,
    )[1].split("\n  async _saveNilmAssignmentChanges", 1)[0]
    context_line = "const actionContext = this._nilmWorkspaceActionContext();"
    assert body.index(context_line) < body.index("await this._hass.callService")
    assert body.index("await this._hass.callService") < body.index(
        "await this._refreshNilmWorkspaceData"
    )
    assert "if (!actionContext.isCurrent())" in body
    assert "if (!actionContext.isRouteCurrent())" in body
    assert "this._busyAction === busyKey" in body
    assert "this._selectRefreshedNilmAssignment(item, data)" in body
    assert "this._storeActionMessageForReload" not in body
    assert "window.location.assign" not in body
    assert "await this._loadEvidence" not in body


def test_panel_custom_component_falls_back_when_proxy_lacks_register_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        _panel_custom_component,
    )

    components_module = ModuleType("homeassistant.components")
    panel_custom_module = ModuleType("homeassistant.components.panel_custom")
    panel_custom_module.async_register_panel = object()
    components_module.panel_custom = panel_custom_module
    monkeypatch.setitem(sys.modules, "homeassistant.components", components_module)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.panel_custom",
        panel_custom_module,
    )
    hass = SimpleNamespace(components=SimpleNamespace(panel_custom=SimpleNamespace()))

    assert _panel_custom_component(hass) is panel_custom_module


def test_frontend_component_prefers_import_without_hass_components_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        _frontend_component,
    )

    frontend_module = ModuleType("homeassistant.components.frontend")
    frontend_module.async_remove_panel = lambda *args, **kwargs: None
    components_module = ModuleType("homeassistant.components")
    components_module.frontend = frontend_module
    monkeypatch.setitem(sys.modules, "homeassistant.components", components_module)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.frontend",
        frontend_module,
    )

    class Components:
        @property
        def frontend(self) -> None:
            raise AssertionError("deprecated hass.components.frontend access")

    assert (
        _frontend_component(SimpleNamespace(components=Components())) is frontend_module
    )


@pytest.mark.asyncio
async def test_panel_registers_via_frontend_when_panel_custom_helper_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import panel
    from custom_components.circuitsetup_energy_analyzer.panel import (
        PANEL_ELEMENT_NAME,
        PANEL_MODULE_VERSION,
        PANEL_URL_PATH,
        STATIC_URL_PATH,
        alert_evidence_panel_text,
    )

    class FakeFrontend:
        def __init__(self) -> None:
            self.panels = []

        def async_register_built_in_panel(self, hass, **kwargs) -> None:
            self.panels.append(kwargs)

    frontend = FakeFrontend()
    monkeypatch.setattr(
        panel,
        "_panel_custom_component",
        lambda hass: SimpleNamespace(),
    )
    monkeypatch.setattr(panel, "_frontend_component", lambda hass: frontend)

    assert await panel._async_register_panel(SimpleNamespace()) is True

    assert frontend.panels == [
        {
            "component_name": "custom",
            "sidebar_title": None,
            "sidebar_icon": None,
            "frontend_url_path": PANEL_URL_PATH,
            "config": {
                "api_path": "/api/circuitsetup_energy_analyzer/alert_evidence",
                "domain": "circuitsetup_energy_analyzer",
                "text": alert_evidence_panel_text(),
                "_panel_custom": {
                    "name": PANEL_ELEMENT_NAME,
                    "embed_iframe": False,
                    "trust_external": False,
                    "module_url": (
                        f"{STATIC_URL_PATH}/energy-analyzer-panel.js"
                        f"?v={PANEL_MODULE_VERSION}"
                    ),
                },
            },
            "require_admin": False,
            "config_panel_domain": None,
        }
    ]


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


def test_alert_evidence_payload_switches_to_resume_alerts_when_paused() -> None:
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
    assert "end_maintenance" not in payload["actions"]
    assert payload["actions"]["pause_alerts"] == {
        "domain": DOMAIN,
        "service": "end_maintenance",
        "label": "Resume Alerts",
        "data": {"circuit_id": "hvac"},
    }


def test_alert_evidence_payload_allows_pause_alerts_without_current_alert() -> None:
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
        "service": "start_maintenance",
        "label": "Pause Alerts",
        "data": {"circuit_id": "hvac"},
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
    assert payload["setting_recommendations"][0]["actions"]["undo"]["enabled"] is False
    assert payload["setting_recommendations"][0]["actions"]["reset"]["service"] == (
        "reset_setting_recommendation"
    )
    assert payload["setting_recommendations"][0]["actions"]["reset"]["enabled"] is True
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
    assert recommendation["what_this_controls"].startswith(
        "Controls how close load can get to configured circuit capacity"
    )
    assert recommendation["expected_effect"].startswith(
        "Warn earlier when usage approaches capacity"
    )
    assert recommendation["setting_explanation"] == {
        "what_this_controls": recommendation["what_this_controls"],
        "current_value": 0.9,
        "default_value": 0.8,
        "suggested_value": 0.75,
        "why_suggestion_exists": "Observed sustained high-current samples.",
        "expected_effect": recommendation["expected_effect"],
        "reset_to_default": True,
    }
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


def test_recommendation_payload_includes_historical_setting_impact() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    alert = _alert(circuit_id="ev", timestamp=now)
    coordinator = _coordinator(alert, config=_config("ev"))
    coordinator.current_time = lambda: now
    coordinator.store_data.contextual_baseline_samples_by_circuit = {
        "ev": [
            {
                "timestamp": (now - timedelta(days=2)).isoformat(),
                "feature": "peak_demand_w",
                "value": 1800.0,
            },
            {
                "timestamp": (now - timedelta(days=1)).isoformat(),
                "feature": "peak_demand_w",
                "value": 2400.0,
            },
        ]
    }
    coordinator.state.settings_recommendations_by_circuit = {
        "ev": [
            {
                "recommendation_id": "ev:demand_limit_w:v1",
                "circuit_id": "ev",
                "setting_key": "demand_limit_w",
                "current_value": 2000.0,
                "suggested_value": 2500.0,
            }
        ]
    }

    payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
    )

    impact = payload["setting_recommendations"][0]["impact_preview"]
    assert impact["observations_evaluated"] == 2
    assert impact["current_alert_count"] == 1
    assert impact["candidate_alert_count"] == 0
    assert impact["history_start"].startswith("2026-07-11")


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
                "circuit_name": "EV Charger",
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
    assert selected["display_label"] == "EV Charger Capacity Warning Ratio"
    assert selected["evidence_preview"] == (
        "Observed Samples: 8; P95 Current Amps: 36.4"
    )


def test_recommendation_header_leads_with_appliance_and_names_power() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        _recommendation_display_label,
    )

    assert (
        _recommendation_display_label(
            {
                "circuit_id": "hvac",
                "circuit_name": "HVAC",
                "setting_key": "standby_threshold_w",
                "setting_label": "Standby Threshold W",
            }
        )
        == "HVAC Standby Power Threshold"
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
    assert recommendation["display_label"] == "Washer Always On Power Alert"
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
    assert recommendation["display_label"] == (
        "Mains Flexible Load Running Power Threshold"
    )
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


def test_alert_evidence_payload_links_explicit_nilm_duplicate() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert(circuit_id="mains", feature="nilm_unknown_load")
    regular_mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
    )
    nilm_mains = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(
        alert,
        config=regular_mains,
        configs=(regular_mains, nilm_mains),
    )
    coordinator.state.nilm_unknown_loads_by_circuit = {
        "mains": {"unknown_loads": [{"signature_id": "signature_1"}]}
    }

    payload = alert_evidence_payload(
        [coordinator],
        alert_id=notification_id_for_alert(alert),
    )

    assert payload["nilm"]["workspace_call_api_path"].endswith("circuit_id=mains")


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


def test_alert_evidence_payload_overlays_saved_nilm_review_state_on_inventory() -> None:
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


def test_nilm_workspace_payload_includes_label_interval_actions_and_is_bounded() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
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
        sensors=(
            SensorRef("sensor.pool_pump_power", SensorRole.REAL_POWER),
            SensorRef("sensor.pool_pump_power_leg_2", SensorRole.REAL_POWER),
        ),
    )
    solar_config = CircuitConfig(
        circuit_id="solar",
        name="Solar Inverter",
        appliance_profile=ApplianceProfile.SOLAR_INVERTER,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.solar_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(
        config=mains_config,
        configs=(mains_config, known_config, solar_config),
    )
    coordinator.store_data.nilm_label_intervals_by_circuit = {
        "mains": [
            {
                "interval_id": "label-1",
                "mains_circuit_id": "mains",
                "appliance_id": "dishwasher",
                "label": "Dishwasher",
                "start": "2026-06-06T08:10:00+00:00",
                "end": "2026-06-06T08:40:00+00:00",
                "source": "manual",
                "confidence": 1.0,
                "mains_entity_id": "sensor.mains_power",
                "created_at": "2026-06-06T09:00:00+00:00",
                "updated_at": "2026-06-06T09:00:00+00:00",
            }
        ]
    }
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {
                "assignment_id": "assignment-dishwasher",
                "appliance_id": "dishwasher",
                "display_name": "Dishwasher",
                "appliance_profile": "dishwasher",
                "mains_circuit_id": "mains",
                "signature_fingerprints": ["signature_1"],
                "session_ids": ["session_1"],
                "label_interval_ids": ["label-1"],
                "lifecycle_state": "assigned",
                "confidence": 0.9,
                "created_at": "2026-06-06T09:00:00+00:00",
                "updated_at": "2026-06-06T09:00:00+00:00",
                "created_device": False,
                "publish_entities": False,
            }
        ]
    }
    coordinator.circuit_registry = SimpleNamespace(
        known_load_circuit_ids=frozenset({"pool_pump"})
    )
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
        "sensor.pool_pump_power_leg_2",
        "sensor.solar_power",
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
            "entity_ids": ["sensor.pool_pump_power", "sensor.pool_pump_power_leg_2"],
        }
    ]
    assert payload["solar_overlays"] == [
        {
            "circuit_id": "solar",
            "name": "Solar Inverter",
            "entity_ids": ["sensor.solar_power"],
        }
    ]
    assert payload["signatures"][0]["signature_id"] == "signature_1"
    assert payload["signatures"][0]["actions"]["label"]["service"] == (
        "label_nilm_signature"
    )
    assert payload["signatures"][0]["actions"]["ignore"]["service"] == (
        "ignore_nilm_signature"
    )
    assert payload["signatures"][0]["actions"]["assign"] == {
        "domain": DOMAIN,
        "service": "assign_signature_to_appliance",
        "data": {"circuit_id": "mains", "signature_id": "signature_1"},
        "requires": ["label"],
        "assignment_options": [
            {"value": "assignment-dishwasher", "label": "Dishwasher"}
        ],
    }
    assert payload["label_intervals"][0]["label"] == "Dishwasher"
    assert payload["label_intervals"][0]["actions"]["delete"] == {
        "domain": DOMAIN,
        "service": "delete_nilm_label_interval",
        "data": {"circuit_id": "mains", "interval_id": "label-1"},
    }
    assert payload["label_intervals"][0]["actions"]["assign"] == {
        "domain": DOMAIN,
        "service": "assign_interval_to_appliance",
        "data": {"circuit_id": "mains", "interval_id": "label-1"},
        "requires": ["label"],
        "assignment_options": [
            {"value": "assignment-dishwasher", "label": "Dishwasher"}
        ],
    }
    assert payload["assignments"][0]["display_name"] == "Dishwasher"
    assert payload["assignments"][0]["lifecycle_state"] == "assigned"
    assignment_detail_query = parse_qs(
        urlparse(payload["assignments"][0]["appliance_detail_path"]).query
    )
    assert assignment_detail_query == {
        "assignment_id": ["assignment-dishwasher"],
        "appliance_detail": ["1"],
    }
    assert payload["assignments"][0]["actions"]["rename"] == {
        "domain": DOMAIN,
        "service": "rename_nilm_appliance",
        "data": {"circuit_id": "mains", "assignment_id": "assignment-dishwasher"},
        "requires": ["label"],
    }
    change_profile = payload["assignments"][0]["actions"]["change_profile"]
    assert change_profile == {
        "domain": DOMAIN,
        "service": "change_nilm_appliance_profile",
        "data": {"circuit_id": "mains", "assignment_id": "assignment-dishwasher"},
        "requires": ["appliance_profile"],
        "profile_options": change_profile["profile_options"],
    }
    assert {"value": "dishwasher", "label": "Dishwasher"} in change_profile[
        "profile_options"
    ]
    assert {"value": "mixed", "label": "Mixed"} in change_profile["profile_options"]
    assert payload["assignments"][0]["actions"]["convert_to_direct_meter"] == {
        "domain": DOMAIN,
        "service": "convert_nilm_appliance_to_direct_meter",
        "data": {"circuit_id": "mains", "assignment_id": "assignment-dishwasher"},
        "requires": ["direct_circuit_id"],
        "target_options": [{"value": "pool_pump", "label": "Pool Pump"}],
    }
    assert payload["assignments"][0]["actions"]["publish"] == {
        "domain": DOMAIN,
        "service": "publish_nilm_appliance_assignment",
        "data": {"circuit_id": "mains", "assignment_id": "assignment-dishwasher"},
    }
    assert "unpublish" not in payload["assignments"][0]["actions"]
    assert payload["assignments"][0]["actions"]["retire"] == {
        "domain": DOMAIN,
        "service": "retire_nilm_appliance_assignment",
        "data": {"circuit_id": "mains", "assignment_id": "assignment-dishwasher"},
    }
    assert payload["virtual_appliance_count"] == 1
    assert payload["virtual_appliances"][0]["assignment_id"] == (
        "assignment-dishwasher"
    )
    assert payload["virtual_appliances"][0]["display_name"] == "Dishwasher"
    assert payload["virtual_appliances"][0]["is_running"] is False
    assert payload["virtual_appliances"][0]["estimated_power_w"] == 0.0
    assert (
        payload["virtual_appliances"][0]["estimated_energy_kwh_today"]
        == (payload["sessions"][0]["estimated_energy_kwh"])
    )
    assert payload["virtual_appliances"][0]["confidence"] == 0.9
    assert payload["virtual_appliances"][0]["model_status"] == "assigned"
    assert payload["virtual_appliances"][0]["active_session_id"] is None
    label_action = payload["actions"]["label_interval"]
    assert label_action["domain"] == DOMAIN
    assert label_action["service"] == "label_nilm_interval"
    assert label_action["data"] == {
        "circuit_id": "mains",
        "mains_entity_id": "sensor.mains_power",
    }
    assert label_action["requires"] == [
        "start",
        "end",
        "label",
        "appliance_profile",
    ]
    assert {"value": "washer", "label": "Washer"} in label_action["profile_options"]
    assert "sensor_label_interval" not in payload["actions"]
    assert payload["edges"][0]["direction"] == "on"
    assert payload["sessions"][0]["display_label"] == "Dishwasher"
    assert payload["sessions"][0]["actions"]["assign"] == {
        "domain": DOMAIN,
        "service": "assign_session_to_appliance",
        "data": {
            "circuit_id": "mains",
            "session_id": payload["sessions"][0]["session_id"],
            "signature_fingerprint": payload["sessions"][0]["signature_fingerprint"],
        },
        "requires": ["label"],
        "assignment_options": [
            {"value": "assignment-dishwasher", "label": "Dishwasher"}
        ],
    }
    assert payload["sessions"][0]["actions"]["validate"] == {
        "domain": DOMAIN,
        "service": "validate_nilm_session",
        "data": {
            "circuit_id": "mains",
            "session_id": payload["sessions"][0]["session_id"],
            "assignment_id": "assignment-dishwasher",
        },
    }
    assert payload["sessions"][0]["actions"]["reject"] == {
        "domain": DOMAIN,
        "service": "reject_nilm_session",
        "data": {
            "circuit_id": "mains",
            "session_id": payload["sessions"][0]["session_id"],
            "assignment_id": "assignment-dishwasher",
        },
    }
    assert payload["sessions"][0]["off_edge_id"] is not None


def test_nilm_workspace_payload_groups_lanes_and_estimated_source_language() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    mains_config = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=mains_config, configs=(mains_config,))
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {
                "assignment_id": "assignment-assigned",
                "display_name": "Dishwasher",
                "signature_fingerprints": ["fingerprint-assigned"],
                "lifecycle_state": "assigned",
                "confidence": 0.86,
                "publish_entities": False,
            },
            {
                "assignment_id": "assignment-zero-confidence",
                "display_name": "Unknown Appliance",
                "signature_fingerprints": ["sig-zero"],
                "lifecycle_state": "assigned",
                "confidence": 0.0,
                "publish_entities": False,
            },
            {
                "assignment_id": "assignment-validation",
                "display_name": "Dryer",
                "lifecycle_state": "needs_validation",
                "confidence": 0.61,
                "publish_entities": True,
            },
            {
                "assignment_id": "assignment-ready",
                "display_name": "Washer",
                "lifecycle_state": "validated",
                "confidence": 0.91,
                "publish_entities": False,
            },
            {
                "assignment_id": "assignment-published",
                "display_name": "Pool Pump",
                "lifecycle_state": "published",
                "confidence": 0.94,
                "publish_entities": True,
            },
            {
                "assignment_id": "assignment-ignored",
                "display_name": "Expected Load",
                "lifecycle_state": "ignored",
                "confidence": 0.5,
                "publish_entities": False,
            },
        ]
    }
    coordinator.state.nilm_unknown_loads_by_circuit = {
        "mains": {
            "unknown_loads": [
                {
                    "signature_id": "sig-assigned",
                    "fingerprint": "fingerprint-assigned",
                    "display_name": "Dishwasher-like load",
                    "typical_watts": 510.0,
                },
                {
                    "signature_id": "sig-new",
                    "display_name": "Pump-like load",
                    "typical_watts": 720.0,
                    "typical_duration_seconds": 1500.0,
                    "seen_count": 4,
                    "confidence": 0.72,
                    "voltage_class": "120v",
                    "dominant_leg": "a",
                },
                {
                    "signature_id": "sig-ignored",
                    "display_name": "Expected background load",
                    "typical_watts": 110.0,
                    "ignored": True,
                },
            ]
        }
    }
    coordinator._nilm_unmatched_edges = {}

    payload = nilm_workspace_payload([coordinator], circuit_id="mains")

    assert payload["lanes"]["needs_review"]["signature_ids"] == ["sig-new"]
    assert payload["lanes"]["assigned"]["assignment_ids"] == ["assignment-assigned"]
    assert payload["lanes"]["needs_review"]["assignment_ids"] == [
        "assignment-zero-confidence",
        "assignment-ready",
    ]
    assert payload["lanes"]["published"]["assignment_ids"] == [
        "assignment-validation",
        "assignment-published",
    ]
    assert payload["lanes"]["ignored_expected"]["assignment_ids"] == [
        "assignment-ignored"
    ]
    assert payload["lanes"]["ignored_expected"]["signature_ids"] == ["sig-ignored"]
    assert payload["lane_counts"]["needs_review"] == 3
    signature = next(
        item for item in payload["signatures"] if item["signature_id"] == "sig-new"
    )
    assert signature["source_type"] == "nilm_estimate"
    assert signature["source_label"] == "Estimated by NILM"
    assert signature["typical_power_w"] == 720.0
    assert signature["typical_duration_seconds"] == 1500.0
    assert signature["seen_count"] == 4
    assert "similar NILM on/off edges" in signature["why_grouped"]
    assert payload["selection_guidance"] == {
        "snap_to_edges": True,
        "show_likely_paired_off_edge": True,
        "preview_interval_kwh": True,
        "show_known_load_overlap": True,
    }
    virtual = payload["virtual_appliances"][0]
    assert virtual["source_type"] == "nilm_estimate"
    assert virtual["source_label"] == "Estimated by NILM"
    virtual_detail_query = parse_qs(urlparse(virtual["appliance_detail_path"]).query)
    assert virtual_detail_query == {
        "assignment_id": ["assignment-assigned"],
        "appliance_detail": ["1"],
    }
    assert virtual["appliance_detail_api_path"].endswith(
        "assignment_id=assignment-assigned"
    )


def test_nilm_workspace_hides_retired_and_reviews_unassigned_intervals() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        _nilm_workspace_lanes,
        _nilm_workspace_session_specs,
    )

    signatures = [
        {"signature_id": "sig-retired", "review_state": "assigned"},
        {"signature_id": "sig-new", "review_state": "new"},
        {"signature_id": "sig-ignored", "review_state": "ignored"},
    ]
    assignments = [
        {
            "assignment_id": "assignment-retired",
            "signature_fingerprints": ["sig-retired"],
            "label_interval_ids": ["interval-retired"],
            "lifecycle_state": "retired",
        }
    ]
    intervals = [
        {"interval_id": "interval-retired", "label": "Dishwasher"},
        {"interval_id": "interval-new", "label": "Dryer"},
    ]

    assert _nilm_workspace_session_specs(signatures, assignments) == [("sig-new", None)]
    lanes = _nilm_workspace_lanes(signatures, assignments, intervals)
    assert set(lanes) == {
        "needs_review",
        "assigned",
        "published",
        "ignored_expected",
    }
    assert lanes["needs_review"]["signature_ids"] == ["sig-new"]
    assert lanes["needs_review"]["interval_ids"] == ["interval-new"]
    assert lanes["ignored_expected"]["assignment_ids"] == ["assignment-retired"]


def test_nilm_workspace_visibility_ignores_empty_hidden_identifiers() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        _nilm_workspace_visible_sessions,
    )

    sessions = [{"session_id": "session-unassigned"}]

    assert (
        _nilm_workspace_visible_sessions(
            sessions,
            [{"ignored": True}],
            [{"lifecycle_state": "retired"}],
        )
        == sessions
    )


def test_nilm_workspace_keeps_merged_signature_sessions_on_visible_assignment() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        _nilm_workspace_visible_sessions,
    )

    session = {
        "session_id": "session-merged",
        "assignment_id": "assignment-dishwasher",
        "signature_fingerprint": "merged-fingerprint",
    }

    assert _nilm_workspace_visible_sessions(
        [session],
        [
            {
                "review_state": "merged",
                "feedback_fingerprint": "merged-fingerprint",
            }
        ],
        [
            {
                "assignment_id": "assignment-dishwasher",
                "lifecycle_state": "assigned",
                "signature_fingerprints": ["merged-fingerprint"],
            }
        ],
    ) == [session]


def _nilm_workspace_coordinator(
    *,
    entry_id: str,
    name: str,
    entity_id: str,
) -> SimpleNamespace:
    config = CircuitConfig(
        circuit_id="mains",
        name=name,
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef(entity_id, SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=config, configs=(config,))
    coordinator.entry_id = entry_id
    return coordinator


def test_nilm_workspace_payload_uses_requested_entry_for_duplicate_circuit_id() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    first = _nilm_workspace_coordinator(
        entry_id="entry-1",
        name="First Mains",
        entity_id="sensor.first_mains_power",
    )
    second = _nilm_workspace_coordinator(
        entry_id="entry-2",
        name="Second Mains",
        entity_id="sensor.second_mains_power",
    )

    payload = nilm_workspace_payload(
        [first, second],
        circuit_id="mains",
        entry_id="entry-2",
    )

    assert payload["circuit"]["name"] == "Second Mains"
    assert payload["history"]["entities"] == ["sensor.second_mains_power"]


@pytest.mark.asyncio
async def test_nilm_workspace_view_forwards_requested_entry_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import panel

    first = _nilm_workspace_coordinator(
        entry_id="entry-1",
        name="First Mains",
        entity_id="sensor.first_mains_power",
    )
    second = _nilm_workspace_coordinator(
        entry_id="entry-2",
        name="Second Mains",
        entity_id="sensor.second_mains_power",
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": first, "entry-2": second}})
    request = SimpleNamespace(
        app={panel.KEY_HASS: hass},
        query={"circuit_id": "mains", "entry_id": "entry-2"},
    )
    monkeypatch.setattr(panel.web, "json_response", lambda payload: payload)

    payload = await panel.NilmWorkspaceView().get(request)

    assert payload["circuit"]["name"] == "Second Mains"


@pytest.mark.asyncio
async def test_nilm_workspace_history_view_forwards_requested_entry_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import panel

    first = _nilm_workspace_coordinator(
        entry_id="entry-1",
        name="First Mains",
        entity_id="sensor.first_mains_power",
    )
    second = _nilm_workspace_coordinator(
        entry_id="entry-2",
        name="Second Mains",
        entity_id="sensor.second_mains_power",
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": first, "entry-2": second}})
    request = SimpleNamespace(
        app={panel.KEY_HASS: hass},
        query={"circuit_id": "mains", "entry_id": "entry-2"},
    )

    async def history_rows(_hass, _start, _end, entity_ids):
        return [[{"entity_id": entity_id}] for entity_id in entity_ids]

    monkeypatch.setattr(panel, "_async_history_rows", history_rows)
    monkeypatch.setattr(panel.web, "json_response", lambda payload: payload)

    payload = await panel.NilmWorkspaceHistoryView().get(request)

    assert payload == [[{"entity_id": "sensor.second_mains_power"}]]


def test_nilm_workspace_payload_skips_non_nilm_mains_duplicate() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    regular_mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
    )
    nilm_mains = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )

    payload = nilm_workspace_payload(
        [_coordinator(config=regular_mains, configs=(regular_mains, nilm_mains))],
        circuit_id="mains",
    )

    assert payload["status"] == "ok"
    assert payload["circuit"]["name"] == "Mains NILM"


def test_nilm_workspace_payload_accepts_mixed_mains_with_sensors() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    mains_config = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )

    payload = nilm_workspace_payload(
        [_coordinator(config=mains_config, configs=(mains_config,))],
        circuit_id="mains",
    )

    assert payload["status"] == "ok"
    assert payload["history"]["entities"] == ["sensor.mains_power"]


def test_nilm_workspace_payload_prefers_explicit_nilm_over_sensor_fallback() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    sensor_backed_mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    nilm_mains = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.nilm_power", SensorRole.REAL_POWER),),
    )

    payload = nilm_workspace_payload(
        [
            _coordinator(
                config=sensor_backed_mains,
                configs=(sensor_backed_mains, nilm_mains),
            )
        ],
        circuit_id="mains",
    )

    assert payload["status"] == "ok"
    assert payload["circuit"]["name"] == "Mains NILM"
    assert payload["history"]["entities"] == ["sensor.nilm_power"]


def test_nilm_workspace_payload_accepts_runtime_config_shape() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    mains_config = SimpleNamespace(
        circuit_id="mains",
        name="Mains",
        appliance_profile="mixed",
        mode="mixed",
        sensors=(SimpleNamespace(entity_id="sensor.mains_power"),),
    )

    payload = nilm_workspace_payload(
        [_coordinator(config=mains_config, configs=(mains_config,))],
        circuit_id="mains",
    )

    assert payload["status"] == "ok"
    assert payload["history"]["entities"] == ["sensor.mains_power"]


def test_nilm_workspace_payload_adds_assignment_merge_targets() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    config = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=config)
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {
                "assignment_id": "assignment-source",
                "appliance_id": "dishwasher_old",
                "display_name": "Dishwasher old",
                "mains_circuit_id": "mains",
                "signature_fingerprints": ["source-fingerprint"],
                "session_ids": [],
                "label_interval_ids": [],
                "lifecycle_state": "assigned",
                "confidence": 0.7,
            },
            {
                "assignment_id": "assignment-target",
                "appliance_id": "dishwasher",
                "display_name": "Dishwasher",
                "mains_circuit_id": "mains",
                "signature_fingerprints": ["target-fingerprint"],
                "session_ids": [],
                "label_interval_ids": [],
                "lifecycle_state": "assigned",
                "confidence": 0.9,
            },
        ]
    }

    payload = nilm_workspace_payload([coordinator], circuit_id="mains")

    assert payload["assignments"][0]["actions"]["merge"] == {
        "domain": DOMAIN,
        "service": "merge_nilm_assignments",
        "data": {
            "circuit_id": "mains",
            "source_assignment_id": "assignment-source",
        },
        "requires": ["target_assignment_id"],
        "target_options": [
            {"value": "assignment-target", "label": "Dishwasher"},
        ],
    }
    assert "validate_history" not in payload["assignments"][0]["actions"]


def test_nilm_workspace_payload_marks_open_virtual_appliance_running() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    mains_config = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=mains_config, configs=(mains_config,))
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {
                "assignment_id": "assignment-dishwasher",
                "appliance_id": "dishwasher",
                "display_name": "Dishwasher",
                "mains_circuit_id": "mains",
                "signature_fingerprints": ["signature_1"],
                "session_ids": [],
                "label_interval_ids": [],
                "lifecycle_state": "learning",
                "confidence": 0.8,
            }
        ]
    }
    coordinator.state.nilm_unknown_loads_by_circuit = {
        "mains": {"unknown_loads": [{"signature_id": "signature_1", "confidence": 0.7}]}
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
            )
        ]
    }

    payload = nilm_workspace_payload([coordinator], circuit_id="mains")

    virtual = payload["virtual_appliances"][0]
    assert virtual["is_running"] is True
    assert virtual["estimated_power_w"] == 820.0
    assert virtual["estimated_energy_kwh_today"] == 0.0
    assert virtual["active_session_id"] == payload["sessions"][0]["session_id"]
    assert virtual["last_seen"] == "2026-06-06T08:00:00+00:00"
    assert virtual["model_status"] == "learning"


def test_nilm_workspace_payload_validates_sensor_labels_against_predictions() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    mains_config = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=mains_config, configs=(mains_config,))
    coordinator.store_data.nilm_label_intervals_by_circuit = {
        "mains": [
            {
                "interval_id": "label-dishwasher",
                "mains_circuit_id": "mains",
                "appliance_id": "dishwasher",
                "label": "Dishwasher",
                "start": "2026-06-06T08:10:00+00:00",
                "end": "2026-06-06T08:40:00+00:00",
                "source": "sensor",
                "confidence": 0.95,
                "mains_entity_id": "sensor.mains_power",
                "ground_truth_entity_id": "sensor.dishwasher_power",
            },
            {
                "interval_id": "label-dryer",
                "mains_circuit_id": "mains",
                "appliance_id": "dryer",
                "label": "Dryer",
                "start": "2026-06-06T10:00:00+00:00",
                "end": "2026-06-06T10:30:00+00:00",
                "source": "sensor",
                "confidence": 0.95,
                "mains_entity_id": "sensor.mains_power",
                "ground_truth_entity_id": "sensor.dryer_power",
            },
            {
                "interval_id": "label-dishwasher-duplicate",
                "mains_circuit_id": "mains",
                "appliance_id": "dishwasher",
                "label": "Dishwasher",
                "start": "2026-06-06T08:15:00+00:00",
                "end": "2026-06-06T08:35:00+00:00",
                "source": "sensor",
                "confidence": 0.95,
                "mains_entity_id": "sensor.mains_power",
                "ground_truth_entity_id": "sensor.dishwasher_power_2",
            },
        ]
    }
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {
                "assignment_id": "assignment-dishwasher",
                "appliance_id": "dishwasher",
                "display_name": "Dishwasher",
                "mains_circuit_id": "mains",
                "signature_fingerprints": ["signature_1"],
                "label_interval_ids": ["label-dishwasher"],
                "lifecycle_state": "assigned",
                "confidence": 0.9,
            }
        ]
    }
    coordinator._nilm_unmatched_edges = {
        "mains": [
            NilmEdge(
                timestamp=datetime(2026, 6, 6, 8, 12, tzinfo=UTC),
                delta_w=820.0,
                delta_var=120.0,
                delta_va=830.0,
                delta_pf=-0.05,
                direction="on",
            ),
            NilmEdge(
                timestamp=datetime(2026, 6, 6, 8, 37, tzinfo=UTC),
                delta_w=-815.0,
                delta_var=-118.0,
                delta_va=-825.0,
                delta_pf=0.04,
                direction="off",
            ),
        ]
    }

    payload = nilm_workspace_payload([coordinator], circuit_id="mains")

    assert payload["assignments"][0]["actions"]["validate_history"] == {
        "domain": DOMAIN,
        "service": "validate_nilm_assignment_history",
        "data": {
            "circuit_id": "mains",
            "assignment_id": "assignment-dishwasher",
        },
    }
    validation = payload["validation"]
    assert validation["metrics"] == {
        "ground_truth_interval_count": 3,
        "prediction_count": 1,
        "matched_ground_truth_count": 1,
        "matched_prediction_count": 1,
        "missed_ground_truth_count": 2,
        "precision": 1.0,
        "recall": 0.333,
    }
    assert validation["prediction_preview"][0] == {
        "interval_id": "label-dishwasher",
        "label": "Dishwasher",
        "ground_truth_entity_id": "sensor.dishwasher_power",
        "source": "sensor",
        "prediction_status": "matched",
        "matched_assignment_id": "assignment-dishwasher",
        "matched_session_id": payload["sessions"][0]["session_id"],
        "overlap_seconds": 1500.0,
        "prediction_confidence": payload["sessions"][0]["confidence"],
    }
    assert validation["prediction_preview"][1] == {
        "interval_id": "label-dryer",
        "label": "Dryer",
        "ground_truth_entity_id": "sensor.dryer_power",
        "source": "sensor",
        "prediction_status": "missed",
        "matched_assignment_id": None,
        "matched_session_id": None,
        "overlap_seconds": 0.0,
        "prediction_confidence": None,
    }
    assert validation["prediction_preview"][2] == {
        "interval_id": "label-dishwasher-duplicate",
        "label": "Dishwasher",
        "ground_truth_entity_id": "sensor.dishwasher_power_2",
        "source": "sensor",
        "prediction_status": "missed",
        "matched_assignment_id": None,
        "matched_session_id": None,
        "overlap_seconds": 0.0,
        "prediction_confidence": None,
    }


def test_nilm_workspace_validation_uses_uncapped_data() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        MAX_NILM_WORKSPACE_LABEL_INTERVALS,
        MAX_NILM_WORKSPACE_SESSIONS,
        nilm_workspace_payload,
    )

    mains_config = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=mains_config, configs=(mains_config,))
    coordinator.store_data.nilm_label_intervals_by_circuit = {
        "mains": [
            {
                "interval_id": f"label-{index}",
                "mains_circuit_id": "mains",
                "appliance_id": f"load-{index}",
                "label": f"Load {index}",
                "start": "2026-06-06T08:00:00+00:00",
                "end": "2026-06-06T08:10:00+00:00",
                "source": "sensor",
                "ground_truth_entity_id": f"sensor.load_{index}",
            }
            for index in range(MAX_NILM_WORKSPACE_LABEL_INTERVALS + 1)
        ]
    }
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {
                "assignment_id": "assignment-dishwasher",
                "appliance_id": "dishwasher",
                "display_name": "Dishwasher",
                "mains_circuit_id": "mains",
                "signature_fingerprints": ["signature_1"],
                "lifecycle_state": "assigned",
                "confidence": 0.9,
            },
        ]
    }
    coordinator.state.nilm_unknown_loads_by_circuit = {
        "mains": {"unknown_loads": [{"signature_id": "signature_1"}]}
    }
    start_at = datetime(2026, 6, 6, 8, 0, tzinfo=UTC)
    coordinator._nilm_unmatched_edges = {
        "mains": [
            edge
            for index in range(MAX_NILM_WORKSPACE_SESSIONS + 1)
            for edge in (
                NilmEdge(
                    timestamp=start_at + timedelta(hours=index * 13),
                    delta_w=820.0,
                    delta_var=120.0,
                    delta_va=830.0,
                    delta_pf=-0.05,
                    direction="on",
                ),
                NilmEdge(
                    timestamp=start_at + timedelta(hours=index * 13, minutes=5),
                    delta_w=-815.0,
                    delta_var=-118.0,
                    delta_va=-825.0,
                    delta_pf=0.04,
                    direction="off",
                ),
            )
        ]
    }

    payload = nilm_workspace_payload([coordinator], circuit_id="mains")

    assert len(payload["label_intervals"]) == MAX_NILM_WORKSPACE_LABEL_INTERVALS
    assert len(payload["sessions"]) == MAX_NILM_WORKSPACE_SESSIONS
    assert payload["validation"]["metrics"]["ground_truth_interval_count"] == (
        MAX_NILM_WORKSPACE_LABEL_INTERVALS + 1
    )
    assert payload["validation"]["metrics"]["prediction_count"] == (
        MAX_NILM_WORKSPACE_SESSIONS + 1
    )


def test_nilm_workspace_payload_filters_sessions_by_assignment_signature() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    mains_config = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=mains_config, configs=(mains_config,))
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {
                "assignment_id": "assignment-dishwasher",
                "appliance_id": "dishwasher",
                "display_name": "Dishwasher",
                "mains_circuit_id": "mains",
                "signature_fingerprints": ["signature_1"],
                "session_ids": [],
                "label_interval_ids": [],
                "lifecycle_state": "learning",
                "confidence": 0.8,
            },
            {
                "assignment_id": "assignment-dryer",
                "appliance_id": "dryer",
                "display_name": "Dryer",
                "mains_circuit_id": "mains",
                "signature_fingerprints": ["signature_2"],
                "session_ids": [],
                "label_interval_ids": [],
                "lifecycle_state": "learning",
                "confidence": 0.7,
            },
        ]
    }
    coordinator.state.nilm_unknown_loads_by_circuit = {
        "mains": {
            "unknown_loads": [
                {
                    "signature_id": "signature_1",
                    "typical_watts": 820.0,
                    "confidence": 0.8,
                },
                {
                    "signature_id": "signature_2",
                    "typical_watts": 420.0,
                    "confidence": 0.7,
                },
            ]
        }
    }
    coordinator._nilm_unmatched_edges = {
        "mains": [
            NilmEdge(
                timestamp=datetime(2026, 6, 6, 8, 0, tzinfo=UTC),
                delta_w=420.0,
                delta_var=20.0,
                delta_va=421.0,
                delta_pf=-0.01,
                direction="on",
            )
        ]
    }

    payload = nilm_workspace_payload([coordinator], circuit_id="mains")

    appliances = {
        appliance["assignment_id"]: appliance
        for appliance in payload["virtual_appliances"]
    }
    assert appliances["assignment-dishwasher"]["is_running"] is False
    assert appliances["assignment-dishwasher"]["estimated_power_w"] == 0.0
    assert appliances["assignment-dryer"]["is_running"] is True
    assert appliances["assignment-dryer"]["estimated_power_w"] == 420.0


def test_nilm_workspace_payload_filters_sessions_by_feedback_fingerprint() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    mains_config = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=mains_config, configs=(mains_config,))
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {
                "assignment_id": "assignment-dishwasher",
                "appliance_id": "dishwasher",
                "display_name": "Dishwasher",
                "mains_circuit_id": "mains",
                "signature_fingerprints": ["stable-dishwasher-fingerprint"],
                "session_ids": [],
                "label_interval_ids": [],
                "lifecycle_state": "learning",
                "confidence": 0.8,
            }
        ]
    }
    coordinator.state.nilm_unknown_loads_by_circuit = {
        "mains": {
            "unknown_loads": [
                {
                    "signature_id": "signature_cluster_1",
                    "feedback_fingerprint": "stable-dishwasher-fingerprint",
                    "typical_watts": 820.0,
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
                delta_var=20.0,
                delta_va=821.0,
                delta_pf=-0.01,
                direction="on",
            ),
            NilmEdge(
                timestamp=datetime(2026, 6, 6, 8, 30, tzinfo=UTC),
                delta_w=-815.0,
                delta_var=-20.0,
                delta_va=-816.0,
                delta_pf=0.01,
                direction="off",
            ),
            NilmEdge(
                timestamp=datetime(2026, 6, 6, 9, 0, tzinfo=UTC),
                delta_w=420.0,
                delta_var=15.0,
                delta_va=421.0,
                delta_pf=-0.01,
                direction="on",
            ),
        ]
    }

    payload = nilm_workspace_payload([coordinator], circuit_id="mains")

    assert payload["session_count"] == 1
    assert payload["sessions"][0]["assignment_id"] == "assignment-dishwasher"
    assert payload["sessions"][0]["signature_fingerprint"] == (
        "stable-dishwasher-fingerprint"
    )


def test_nilm_workspace_payload_restores_persisted_session_history() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    mains_config = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=mains_config, configs=(mains_config,))
    coordinator.store_data.nilm_session_history_by_circuit = {
        "mains": [
            {
                "session_id": "session-dishwasher",
                "mains_circuit_id": "mains",
                "signature_fingerprint": "signature_1",
                "on_edge_id": "edge-on",
                "off_edge_id": "edge-off",
                "start": "2026-06-06T08:00:00+00:00",
                "end": "2026-06-06T08:45:00+00:00",
                "duration_seconds": 2700.0,
                "median_power_w": 820.0,
                "estimated_energy_kwh": 0.615,
                "confidence": 0.9,
                "overlap_count": 0,
                "ambiguous": False,
                "alternate_match_count": 0,
                "known_load_masked": False,
                "known_load_confidence": None,
                "assignment_id": "assignment-dishwasher",
            }
        ]
    }

    payload = nilm_workspace_payload([coordinator], circuit_id="mains")

    assert payload["session_count"] == 1
    assert payload["sessions"][0]["session_id"] == "session-dishwasher"
    assert payload["sessions"][0]["assignment_id"] == "assignment-dishwasher"


def test_nilm_workspace_payload_hides_review_actions_for_reviewed_sessions() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    mains_config = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=mains_config, configs=(mains_config,))
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {
                "assignment_id": "assignment-dishwasher",
                "appliance_id": "dishwasher",
                "display_name": "Dishwasher",
                "mains_circuit_id": "mains",
                "confirmed_session_ids": ["session-confirmed", "session-merged"],
                "rejected_session_ids": ["session-rejected"],
            }
        ]
    }
    coordinator.store_data.nilm_session_history_by_circuit = {
        "mains": [
            {
                "session_id": "session-confirmed",
                "mains_circuit_id": "mains",
                "signature_fingerprint": "signature_1",
                "start": "2026-06-06T08:00:00+00:00",
                "end": "2026-06-06T08:45:00+00:00",
                "assignment_id": "assignment-dishwasher",
            },
            {
                "session_id": "session-merged",
                "mains_circuit_id": "mains",
                "signature_fingerprint": "signature_1",
                "start": "2026-06-06T09:00:00+00:00",
                "end": "2026-06-06T09:45:00+00:00",
                "assignment_id": "assignment-before-merge",
            },
            {
                "session_id": "session-pending",
                "mains_circuit_id": "mains",
                "signature_fingerprint": "signature_1",
                "start": "2026-06-06T10:00:00+00:00",
                "end": "2026-06-06T10:45:00+00:00",
                "assignment_id": "assignment-dishwasher",
            },
        ]
    }

    payload = nilm_workspace_payload([coordinator], circuit_id="mains")

    sessions = {session["session_id"]: session for session in payload["sessions"]}
    assert "validate" not in sessions["session-confirmed"]["actions"]
    assert "reject" not in sessions["session-confirmed"]["actions"]
    assert "validate" not in sessions["session-merged"]["actions"]
    assert "reject" not in sessions["session-merged"]["actions"]
    assert "validate" in sessions["session-pending"]["actions"]
    assert "reject" in sessions["session-pending"]["actions"]


def test_nilm_workspace_virtual_appliance_uses_assignment_session_ids() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    mains_config = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=mains_config, configs=(mains_config,))
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {
                "assignment_id": "assignment-dishwasher",
                "appliance_id": "dishwasher",
                "display_name": "Dishwasher",
                "mains_circuit_id": "mains",
                "signature_fingerprints": ["signature_1"],
                "session_ids": ["session-dishwasher"],
                "label_interval_ids": [],
                "lifecycle_state": "assigned",
                "confidence": 0.8,
            }
        ]
    }
    coordinator.store_data.nilm_session_history_by_circuit = {
        "mains": [
            {
                "session_id": "session-dishwasher",
                "mains_circuit_id": "mains",
                "signature_fingerprint": "signature_1",
                "start": "2026-06-06T08:00:00+00:00",
                "end": "2026-06-06T08:45:00+00:00",
                "duration_seconds": 2700.0,
                "median_power_w": 820.0,
                "estimated_energy_kwh": 0.615,
                "confidence": 0.9,
            }
        ]
    }

    payload = nilm_workspace_payload([coordinator], circuit_id="mains")

    virtual = payload["virtual_appliances"][0]
    assert virtual["assignment_id"] == "assignment-dishwasher"
    assert virtual["estimated_energy_kwh_today"] == 0.615
    assert virtual["last_seen"] == "2026-06-06T08:45:00+00:00"


def test_nilm_workspace_payload_pairs_only_recent_bounded_edges() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        MAX_NILM_WORKSPACE_EDGES,
        MAX_NILM_WORKSPACE_SESSIONS,
        nilm_workspace_payload,
    )

    mains_config = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=mains_config, configs=(mains_config,))
    old_edges = []
    for index in range(MAX_NILM_WORKSPACE_SESSIONS + 1):
        start = index * 120
        old_edges.extend(
            [
                NilmEdge(
                    timestamp=datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
                    + timedelta(seconds=start),
                    delta_w=800.0,
                    delta_var=0.0,
                    delta_va=800.0,
                    delta_pf=0.0,
                    direction="on",
                ),
                NilmEdge(
                    timestamp=datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
                    + timedelta(seconds=start + 60),
                    delta_w=-800.0,
                    delta_var=0.0,
                    delta_va=-800.0,
                    delta_pf=0.0,
                    direction="off",
                ),
            ]
        )
    recent_start = datetime(2026, 6, 6, 8, 0, tzinfo=UTC)
    coordinator._nilm_unmatched_edges = {
        "mains": [
            *old_edges,
            NilmEdge(
                timestamp=recent_start,
                delta_w=900.0,
                delta_var=0.0,
                delta_va=900.0,
                delta_pf=0.0,
                direction="on",
            ),
            NilmEdge(
                timestamp=recent_start + timedelta(minutes=30),
                delta_w=-900.0,
                delta_var=0.0,
                delta_va=-900.0,
                delta_pf=0.0,
                direction="off",
            ),
        ]
    }

    payload = nilm_workspace_payload([coordinator], circuit_id="mains")

    assert payload["edge_count"] == len(old_edges) + 2
    assert len(payload["edges"]) == MAX_NILM_WORKSPACE_EDGES
    assert (
        payload["edges"][-1]["timestamp"]
        == (recent_start + timedelta(minutes=30)).isoformat()
    )
    assert (
        payload["sessions"][-1]["end"]
        == (recent_start + timedelta(minutes=30)).isoformat()
    )


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


@pytest.mark.asyncio
async def test_nilm_workspace_history_handles_missing_recorder_or_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import panel

    monkeypatch.setattr(panel, "_history_get_significant_states", lambda: None)

    rows = await panel._async_history_rows(
        SimpleNamespace(),
        "2026-06-06T08:00:00+00:00",
        "2026-06-06T09:00:00+00:00",
        ["sensor.mains_power"],
    )

    assert rows == []

    monkeypatch.setattr(panel, "_history_get_significant_states", lambda: object())
    monkeypatch.setattr(panel, "_recorder_get_instance", lambda hass: None)

    rows = await panel._async_history_rows(
        SimpleNamespace(),
        "2026-06-06T08:00:00+00:00",
        "2026-06-06T09:00:00+00:00",
        ["sensor.mains_power"],
    )

    assert rows == []


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
        alert_evidence_panel_text,
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
        "text": alert_evidence_panel_text(),
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
    assert payload["actions"]["pause_alerts"] == {
        "domain": DOMAIN,
        "service": "start_maintenance",
        "label": "Pause Alerts",
        "data": {"circuit_id": "hvac"},
    }
    assert "start_maintenance" not in payload["actions"]
    assert "end_maintenance" not in payload["actions"]
    assert payload["actions"]["open_advanced_circuit_settings"]["path"].startswith(
        "/config/integrations/"
    )


def test_alert_evidence_payload_exposes_panel_text() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    payload = alert_evidence_payload([_coordinator()], circuit_id="hvac")

    assert payload["text"]["evidence"]["fallbacks"]["current_circuit_heading"] == (
        "No current alert evidence"
    )


def test_suggested_settings_payload_lists_pending_recommendations_for_entry() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    coordinator = _coordinator()
    coordinator.entry_id = "entry-1"
    coordinator.state.settings_recommendations_by_circuit = {
        "hvac": [
            {
                "recommendation_id": "hvac:daily_spike_ratio:v1",
                "title": "Raise daily spike threshold",
                "status": "pending",
            }
        ]
    }

    payload = alert_evidence_payload(
        [coordinator],
        entry_id="entry-1",
        review_suggested_settings=True,
    )

    assert payload["status"] == "settings_recommendations"
    assert payload["requested_entry_id"] == "entry-1"
    assert [item["display_label"] for item in payload["setting_recommendations"]] == [
        "Raise daily spike threshold"
    ]


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
    assert payload["actions"]["pause_alerts"]["data"] == {"circuit_id": "car_charger"}
    assert payload["actions"]["pause_alerts"]["service"] == "start_maintenance"
    assert "start_maintenance" not in payload["actions"]
    assert "end_maintenance" not in payload["actions"]


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


def test_setup_health_payload_exposes_checklist_and_next_step() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        setup_health_payload,
    )

    coordinator = _coordinator(config=_config("hvac"))

    payload = setup_health_payload([coordinator])

    assert payload["status"] == "ok"
    assert payload["state"] == "Configure breaker amps"
    assert payload["next_step"] == "Configure breaker amps for HVAC"
    assert payload["checklist"][0] == {
        "item_id": "source_data_found",
        "status": "ok",
        "title": "Source data found",
        "why_it_matters": (
            "Confirms Home Assistant is receiving live readings for each circuit."
        ),
    }
    assert payload["checklist_total_count"] == 10
    assert payload["open_path"].startswith("/config/integrations/")


def test_setup_health_payload_links_checklist_actions_to_option_steps() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        setup_health_payload,
    )

    coordinator = _coordinator(config=_config("hvac"))
    coordinator.entry_id = "entry-hvac"

    payload = setup_health_payload([coordinator])

    capacity_issue = next(
        item
        for item in payload["issues"]
        if item["issue"] == "missing_capacity_setting"
    )
    capacity = urlparse(capacity_issue["open_path"])
    capacity_params = parse_qs(capacity.fragment)
    assert capacity_params["config_entry"] == ["entry-hvac"]
    assert capacity_params["options_step"] == ["advanced_settings"]
    assert capacity_params["circuit_id"] == ["hvac"]

    checklist = {item["item_id"]: item for item in payload["checklist"]}
    entity_detail = urlparse(checklist["entity_detail_level_selected"]["open_path"])
    dashboard = urlparse(checklist["dashboard_created"]["open_path"])
    assert parse_qs(entity_detail.fragment)["options_step"] == ["entity_detail"]
    assert parse_qs(dashboard.fragment)["options_step"] == ["dashboard"]


def test_setup_health_payload_uses_requested_entry_id() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        setup_health_payload,
    )

    first = _coordinator(config=_config("fridge"))
    first.entry_id = "entry-1"
    second = _coordinator(config=_config("hvac"))
    second.entry_id = "entry-2"

    payload = setup_health_payload([first, second], entry_id="entry-2")

    assert payload["status"] == "ok"
    assert payload["requested_entry_id"] == "entry-2"
    assert payload["next_step"] == "Configure breaker amps for HVAC"


def test_appliance_insights_payload_exposes_status_and_items() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_insights_payload,
    )

    coordinator = _coordinator(config=_config("hvac"))
    coordinator.entry_id = "entry-hvac"

    payload = appliance_insights_payload([coordinator])

    assert payload["status"] == "ok"
    assert payload["count"] == 1
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["appliance_key"] == "circuit:hvac"
    assert item["display_name"] == "HVAC"
    assert item["source_type"] == "direct_meter"
    assert item["detail_path"].endswith("appliance_detail=1&circuit_id=hvac")
    assert item["is_nilm"] is False


@pytest.mark.asyncio
async def test_panel_setup_registers_static_api_and_panel_once() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        PANEL_ELEMENT_NAME,
        PANEL_MODULE_VERSION,
        PANEL_URL_PATH,
        STATIC_URL_PATH,
        async_setup_panel,
        async_unload_panel,
    )
    from custom_components.circuitsetup_energy_analyzer.panel_contracts import (
        APPLIANCE_DETAIL_API_PATH,
        APPLIANCE_INSIGHTS_API_PATH,
        EVIDENCE_API_PATH,
        NILM_WORKSPACE_API_PATH,
        NILM_WORKSPACE_HISTORY_API_PATH,
        SETUP_HEALTH_API_PATH,
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
        APPLIANCE_DETAIL_API_PATH,
        APPLIANCE_INSIGHTS_API_PATH,
        SETUP_HEALTH_API_PATH,
        NILM_WORKSPACE_API_PATH,
        NILM_WORKSPACE_HISTORY_API_PATH,
    ]
    assert frontend.removed == [(PANEL_URL_PATH, {"warn_if_unknown": False})]
    assert len(panel_custom.panels) == 1
    assert panel_custom.panels[0]["frontend_url_path"] == PANEL_URL_PATH
    assert panel_custom.panels[0]["webcomponent_name"] == PANEL_ELEMENT_NAME
    assert panel_custom.panels[0].get("sidebar_title") is None
    assert panel_custom.panels[0].get("sidebar_icon") is None
    assert panel_custom.panels[0]["module_url"].endswith(f"?v={PANEL_MODULE_VERSION}")

    await async_unload_panel(hass)

    assert frontend.removed == [
        (PANEL_URL_PATH, {"warn_if_unknown": False}),
        (PANEL_URL_PATH, {"warn_if_unknown": False}),
    ]
    assert DOMAIN in hass.data


@pytest.mark.asyncio
async def test_panel_setup_supports_bound_panel_custom_helper() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
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

        async def async_register_panel(self, **kwargs) -> None:
            self.panels.append(kwargs)

    class FakeFrontend:
        def __init__(self) -> None:
            self.removed = []

        def async_remove_panel(self, frontend_url_path, **kwargs) -> None:
            self.removed.append((frontend_url_path, kwargs))

    panel_custom = FakePanelCustom()
    frontend = FakeFrontend()
    hass = SimpleNamespace(
        data={},
        http=FakeHttp(),
        components=SimpleNamespace(panel_custom=panel_custom, frontend=frontend),
    )

    assert await async_setup_panel(hass) is True
    assert panel_custom.panels[0]["frontend_url_path"] == PANEL_URL_PATH
    assert frontend.removed == [(PANEL_URL_PATH, {"warn_if_unknown": False})]

    await async_unload_panel(hass)

    assert frontend.removed == [
        (PANEL_URL_PATH, {"warn_if_unknown": False}),
        (PANEL_URL_PATH, {"warn_if_unknown": False}),
    ]


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
        services=SimpleNamespace(
            async_register=lambda *args, **kwargs: None,
            async_remove=lambda *args, **kwargs: None,
        ),
    )
    entry = SimpleNamespace(entry_id="entry-1", data={})

    assert await async_setup_entry(hass, entry) is True

    assert panel_custom.panels[0]["frontend_url_path"] == PANEL_URL_PATH
    assert len(http.static_paths) == 1
    assert len(http.views) == 6

    hass.data[DOMAIN][DATA_RELOAD_COUNT] = 1
    assert await async_unload_entry(hass, entry) is True
    assert frontend.removed == [PANEL_URL_PATH]
    assert "_services_setup" in hass.data[DOMAIN]

    hass.data[DOMAIN].pop(DATA_RELOAD_COUNT)
    assert await async_setup_entry(hass, entry) is True
    assert len(panel_custom.panels) == 1
    assert await async_unload_entry(hass, entry) is True

    assert frontend.removed == [PANEL_URL_PATH, PANEL_URL_PATH]
    assert "_services_setup" not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_active_reload_preserves_surfaces_during_other_entry_unload() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        async_setup_entry,
        async_unload_entry,
    )
    from custom_components.circuitsetup_energy_analyzer.panel import PANEL_URL_PATH

    class FakeConfigEntries:
        def __init__(self) -> None:
            self.unload_gate: tuple[asyncio.Event, asyncio.Event] | None = None

        async def async_forward_entry_setups(self, entry, platforms) -> None:
            return None

        async def async_unload_platforms(self, entry, platforms) -> bool:
            if self.unload_gate is not None:
                started, release = self.unload_gate
                started.set()
                await release.wait()
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
    config_entries = FakeConfigEntries()
    hass = SimpleNamespace(
        data={},
        http=FakeHttp(),
        components=SimpleNamespace(panel_custom=panel_custom, frontend=frontend),
        config_entries=config_entries,
        services=SimpleNamespace(
            async_register=lambda *args, **kwargs: None,
            async_remove=lambda *args, **kwargs: None,
        ),
    )
    first = SimpleNamespace(entry_id="entry-1", data={})
    second = SimpleNamespace(entry_id="entry-2", data={})

    async def _unload_after_counter_change(initial: int, current: int) -> None:
        if initial:
            hass.data[DOMAIN][DATA_RELOAD_COUNT] = initial
        else:
            hass.data[DOMAIN].pop(DATA_RELOAD_COUNT, None)
        started = asyncio.Event()
        release = asyncio.Event()
        config_entries.unload_gate = (started, release)
        task = asyncio.create_task(async_unload_entry(hass, second))
        await started.wait()
        if current:
            hass.data[DOMAIN][DATA_RELOAD_COUNT] = current
        else:
            hass.data[DOMAIN].pop(DATA_RELOAD_COUNT, None)
        release.set()
        assert await task is True
        config_entries.unload_gate = None

    assert await async_setup_entry(hass, first) is True
    assert await async_setup_entry(hass, second) is True

    assert [panel["frontend_url_path"] for panel in panel_custom.panels] == [
        PANEL_URL_PATH
    ]

    assert await async_unload_entry(hass, first) is True
    assert frontend.removed == [PANEL_URL_PATH]

    await _unload_after_counter_change(0, 1)
    assert frontend.removed == [PANEL_URL_PATH]
    assert "_services_setup" in hass.data[DOMAIN]

    hass.data[DOMAIN].pop(DATA_RELOAD_COUNT)
    assert await async_setup_entry(hass, second) is True
    assert len(panel_custom.panels) == 1

    await _unload_after_counter_change(1, 0)
    assert frontend.removed == [PANEL_URL_PATH, PANEL_URL_PATH]
    assert "_services_setup" not in hass.data[DOMAIN]


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
