from __future__ import annotations

import asyncio
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_ADVANCED_SETTINGS,
    CONF_BLOWER_REPRESENTS_GAS_HEAT,
    CONF_LINKED_THERMOSTAT_ENTITIES,
    CONF_THERMOSTAT_ENTITIES,
    CONF_THERMOSTAT_TEMPERATURE_SENSOR_MAP,
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
        state=SimpleNamespace(
            alert_evidence_by_circuit={},
            learning_by_circuit={default_config.circuit_id: False},
        ),
    )


def _hvac_association_coordinator(
    config: CircuitConfig,
    *,
    streams: dict[str, object] | None = None,
    settings: dict[str, object] | None = None,
    entry_id: str = "entry-1",
) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id=entry_id,
        entry_data={CONF_THERMOSTAT_ENTITIES: ["climate.downstairs"]},
        options={
            CONF_ADVANCED_SETTINGS: {
                config.circuit_id: {
                    CONF_LINKED_THERMOSTAT_ENTITIES: ["climate.downstairs"],
                    **(settings or {}),
                }
            }
        },
        circuit_configs=(config,),
        state=SimpleNamespace(
            hvac_efficiency_by_circuit={
                config.circuit_id: {"status": "ready", "streams": streams or {}}
            },
            hvac_thermostat_setup_issues_by_circuit={},
        ),
    )


def test_hvac_associations_payload_keeps_thermostats_and_modes_separate() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        hvac_associations_payload,
    )

    config = CircuitConfig(
        circuit_id="heat_pump",
        name="Heat Pump",
        appliance_profile=ApplianceProfile.HEAT_PUMP,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(),
    )
    streams = {
        "heat_pump|climate.downstairs|heating": {
            "status": "ready",
            "score": 92.0,
            "finding": "slower",
            "change_ratio": 0.087,
            "recent_runtime_minutes": 10.87,
            "context": {
                "mode": "heating",
                "thermostat_entity_id": "climate.downstairs",
            },
        },
        "heat_pump|climate.downstairs|cooling": {
            "status": "ready",
            "score": 108.0,
            "finding": "faster",
            "recent_runtime_minutes": 7.5,
            "context": {
                "mode": "cooling",
                "thermostat_entity_id": "climate.downstairs",
            },
        },
    }
    coordinator = _hvac_association_coordinator(config, streams=streams)
    coordinator.entry_data[CONF_THERMOSTAT_ENTITIES].append("climate.upstairs")
    coordinator.options[CONF_ADVANCED_SETTINGS]["heat_pump"][
        CONF_LINKED_THERMOSTAT_ENTITIES
    ].append("climate.upstairs")

    payload = hvac_associations_payload([coordinator], entry_id="entry-1")

    assert [item["thermostat_entity_id"] for item in payload["items"]] == [
        "climate.downstairs",
        "climate.upstairs",
    ]
    assert payload["items"][0]["modes"]["heating"]["score"] == 92.0
    assert payload["items"][0]["modes"]["heating"]["change_percent"] == 8.7
    assert payload["items"][0]["modes"]["cooling"]["score"] == 108.0
    assert payload["items"][1]["status"] == "learning"


def test_hvac_associations_payload_exposes_bounded_supporting_blowers() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        hvac_associations_payload,
    )

    config = CircuitConfig(
        "heat_pump",
        "Heat Pump",
        ApplianceProfile.HEAT_PUMP,
        CircuitMode.SINGLE_PHASE,
        (),
    )
    streams = {
        "heat_pump|climate.downstairs|cooling": {
            "status": "ready",
            "context": {
                "supporting_blower_ids": ["blower", "", "air_handler", "blower"]
            },
            "current_episode": {"unbounded": ["not", "for", "panel"]},
        }
    }

    payload = hvac_associations_payload(
        [_hvac_association_coordinator(config, streams=streams)]
    )

    mode = payload["items"][0]["modes"]["cooling"]
    assert mode["supporting_blower_ids"] == ["air_handler", "blower"]
    assert "current_episode" not in mode


@pytest.mark.parametrize(
    ("profile", "settings", "modes"),
    [
        (ApplianceProfile.HVAC_COMPRESSOR, {}, {"cooling"}),
        (ApplianceProfile.ELECTRIC_HEAT, {}, {"heating"}),
        (ApplianceProfile.HEAT_PUMP, {}, {"heating", "cooling"}),
        (ApplianceProfile.MINI_SPLIT, {}, {"heating", "cooling"}),
        (ApplianceProfile.HVAC, {}, {"heating", "cooling"}),
        (ApplianceProfile.HVAC_BLOWER, {}, set()),
        (
            ApplianceProfile.HVAC_BLOWER,
            {CONF_BLOWER_REPRESENTS_GAS_HEAT: True},
            {"heating"},
        ),
    ],
)
def test_hvac_associations_payload_exposes_only_applicable_modes(
    profile: ApplianceProfile, settings: dict[str, object], modes: set[str]
) -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        hvac_associations_payload,
    )

    config = CircuitConfig("hvac", "HVAC", profile, CircuitMode.SINGLE_PHASE, ())
    payload = hvac_associations_payload(
        [_hvac_association_coordinator(config, settings=settings)]
    )

    assert set(payload["items"][0]["modes"]) == modes


def test_hvac_associations_payload_marks_setup_issues_and_avoids_hass() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        hvac_associations_payload,
    )

    config = CircuitConfig(
        "hvac", "HVAC", ApplianceProfile.HVAC, CircuitMode.SINGLE_PHASE, ()
    )
    coordinator = _hvac_association_coordinator(config)

    class ForbiddenHassAccess:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"unexpected hass access: {name}")

    coordinator.hass = ForbiddenHassAccess()
    coordinator.state.hvac_thermostat_setup_issues_by_circuit = {
        "hvac": [{"issue": "missing_thermostat"}]
    }

    payload = hvac_associations_payload([coordinator])

    assert payload["items"][0]["status"] == "needs_attention"


def test_hvac_associations_payload_scopes_setup_issues_to_matching_mapping() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        hvac_associations_payload,
    )

    config = CircuitConfig(
        "hvac", "HVAC", ApplianceProfile.HVAC, CircuitMode.SINGLE_PHASE, ()
    )
    coordinator = _hvac_association_coordinator(
        config,
        streams={
            "hvac|climate.downstairs|heating": {
                "status": "ready",
                "context": {
                    "mode": "heating",
                    "thermostat_entity_id": "climate.downstairs",
                },
            }
        },
    )
    coordinator.entry_data[CONF_THERMOSTAT_ENTITIES].append("climate.upstairs")
    coordinator.options[CONF_ADVANCED_SETTINGS]["hvac"][
        CONF_LINKED_THERMOSTAT_ENTITIES
    ].append("climate.upstairs")
    coordinator.options[CONF_ADVANCED_SETTINGS]["hvac"][
        CONF_THERMOSTAT_TEMPERATURE_SENSOR_MAP
    ] = {"climate.upstairs": "sensor.upstairs_temperature"}

    class ForbiddenHassAccess:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"unexpected hass access: {name}")

    coordinator.hass = ForbiddenHassAccess()
    coordinator.state.hvac_thermostat_setup_issues_by_circuit = {
        "hvac": [{"source_entities": ["sensor.upstairs_temperature"]}]
    }

    payload = hvac_associations_payload([coordinator])

    assert [item["status"] for item in payload["items"]] == [
        "ready",
        "needs_attention",
    ]


def test_hvac_associations_payload_filters_coordinators_by_entry_id() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        hvac_associations_payload,
    )

    config = CircuitConfig(
        "hvac", "HVAC", ApplianceProfile.HVAC, CircuitMode.SINGLE_PHASE, ()
    )
    payload = hvac_associations_payload(
        [
            _hvac_association_coordinator(config, entry_id="entry-1"),
            _hvac_association_coordinator(config, entry_id="entry-2"),
        ],
        entry_id="entry-2",
    )

    assert payload["count"] == 1
    assert payload["items"][0]["entry_id"] == "entry-2"


def test_hvac_associations_payload_detail_links_keep_entry_identity() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        hvac_associations_payload,
    )

    config = CircuitConfig(
        "hvac", "HVAC", ApplianceProfile.HVAC, CircuitMode.SINGLE_PHASE, ()
    )
    payload = hvac_associations_payload(
        [
            _hvac_association_coordinator(config, entry_id="entry one"),
            _hvac_association_coordinator(config, entry_id="entry/two"),
        ]
    )

    assert [
        parse_qs(urlparse(item["detail_path"]).query)["entry_id"]
        for item in payload["items"]
    ] == [["entry one"], ["entry/two"]]
    for item in payload["items"]:
        query = parse_qs(urlparse(item["detail_path"]).query)
        assert query["circuit_id"] == ["hvac"]
        assert query["appliance_detail"] == ["1"]


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
    assert payload["actions"]["mark_confirmed"]["service"] == "mark_alert_confirmed"
    assert payload["actions"]["mark_unhelpful"]["service"] == "mark_alert_unhelpful"
    assert payload["actions"]["pause_alerts"] == {
        "domain": DOMAIN,
        "service": "start_maintenance",
        "label": "Pause Alerts",
        "icon": "mdi:bell-pause-outline",
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


@pytest.mark.parametrize(
    ("profile", "mode", "expected"),
    (
        (ApplianceProfile.REFRIGERATOR, CircuitMode.SINGLE_PHASE, True),
        (ApplianceProfile.MIXED, CircuitMode.MIXED, False),
        (ApplianceProfile.HVAC, CircuitMode.DUAL_PHASE, False),
        (ApplianceProfile.MAINS_NILM, CircuitMode.MAINS_NILM, False),
        (ApplianceProfile.SOLAR_INVERTER, CircuitMode.DUAL_PHASE, False),
    ),
)
def test_mixed_circuit_action_only_for_dedicated_single_phase_loads(
    profile: ApplianceProfile,
    mode: CircuitMode,
    expected: bool,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        _actions_for_context,
    )

    config = CircuitConfig(
        circuit_id="fridge",
        name="Kitchen Fridge",
        appliance_profile=profile,
        mode=mode,
        sensors=(),
    )
    coordinator = _coordinator(config=config)
    coordinator.entry_id = "entry-1"
    actions = _actions_for_context(
        coordinator,
        config=config,
        alert_id=None,
        circuit_id="fridge",
    )

    if expected:
        assert actions["mark_circuit_mixed"] == {
            "domain": DOMAIN,
            "service": "mark_circuit_mixed",
            "data": {"entry_id": "entry-1", "circuit_id": "fridge"},
        }
    else:
        assert "mark_circuit_mixed" not in actions


def test_panel_module_version_advances_combined_frontend() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_contracts import (
        PANEL_MODULE_VERSION,
    )

    assert PANEL_MODULE_VERSION == "20260805-2"


def test_nilm_finished_alert_exposes_completion_decisions() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 8, 5, 12, 30, tzinfo=UTC),
        circuit_id="hvac_2",
        severity=Severity.INFO,
        message="Condensate Pump 2: a detected estimated run ended.",
        feature="nilm_appliance_finished",
        observed_value=1.0,
        baseline_value=0.8,
        features={
            "source": "nilm",
            "assignment_id": "assignment-condensate-pump-2",
            "notification_key": "assignment-condensate-pump-2:session-1",
        },
    )

    payload = alert_evidence_payload(
        [_coordinator(alert, config=_config("hvac_2"))],
        alert_id=notification_id_for_alert(alert),
    )

    assert set(payload["actions"]) >= {
        "acknowledge",
        "mark_nilm_appliance_correct",
        "mark_nilm_appliance_wrong",
    }
    assert "mark_expected" not in payload["actions"]
    assert payload["actions"]["mark_nilm_appliance_correct"]["service"] == (
        "mark_nilm_appliance_correct"
    )
    assert payload["actions"]["mark_nilm_appliance_wrong"]["service"] == (
        "mark_nilm_appliance_wrong"
    )


def test_alert_evidence_payload_hides_alerts_while_circuit_is_learning() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert(circuit_id="hvac_2", feature="real_power")
    coordinator = _coordinator(alert, config=_config("hvac_2"))
    coordinator.state.learning_by_circuit["hvac_2"] = True
    coordinator.state.alert_evidence_by_circuit["hvac_2"] = {
        "alert_id": "stored-state-fallback",
        "feature": "real_power",
    }

    payload = alert_evidence_payload(
        [coordinator],
        circuit_id="hvac_2",
    )

    assert payload["status"] == "circuit_found_no_evidence"
    assert payload["alert"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action_name",
    (
        "async_acknowledge_alert",
        "async_mark_alert_expected",
        "async_mark_alert_confirmed",
        "async_mark_alert_unhelpful",
    ),
)
async def test_alert_evidence_payload_hides_retired_action_cache(
    action_name: str,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.managers import evidence_actions
    from custom_components.circuitsetup_energy_analyzer.panel import (
        alert_evidence_payload,
    )

    alert = _alert(feature="runtime")
    alert_id = notification_id_for_alert(alert)
    coordinator = _coordinator(alert)
    coordinator.state.active_alerts_by_circuit = {"hvac": [alert]}
    coordinator.state.anomaly_score_by_circuit = {"hvac": 2.1}
    coordinator.state.alert_evidence_by_circuit = {
        "hvac": {
            "alert_id": alert_id,
            "feature": "runtime",
            "message": "Possible issue",
        }
    }
    coordinator.store_data.alert_feedback = {}
    coordinator.current_time = lambda: datetime(2026, 6, 6, tzinfo=UTC)
    coordinator.refresh_all_ux_state = lambda now: None
    coordinator.async_set_updated_data = lambda state: None
    coordinator.apply_nilm_alert_feedback = lambda alert, action, now: None
    coordinator.circuit_registry = SimpleNamespace(config_for_circuit=lambda _: None)

    async def save_if_dirty(now: datetime) -> None:
        del now

    async def dismiss_alert(alert_id: str) -> None:
        del alert_id

    coordinator.store_persistence = SimpleNamespace(
        mark_dirty=lambda: None,
        async_save_if_dirty=save_if_dirty,
    )
    coordinator.notification_controller = SimpleNamespace(
        async_dismiss_alert_notification=dismiss_alert,
    )

    assert await getattr(
        evidence_actions.EvidenceActionController(coordinator),
        action_name,
    )(alert_id)

    assert (
        alert_evidence_payload(
            [coordinator],
            alert_id=alert_id,
            circuit_id="hvac",
        )["alert"]
        is None
    )


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
        "icon": "mdi:bell-pause-outline",
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
        "icon": "mdi:bell-pause-outline",
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
    assert selected["graph_entities"] == [
        "sensor.ev_charger_l1_watts",
        "sensor.ev_charger_l2_watts",
        "sensor.ev_charger_l1_current",
        "sensor.ev_charger_l2_current",
    ]
    assert selected["graph_entity_series"] == [
        {"entity_id": "sensor.ev_charger_l1_watts", "unit": "W"},
        {"entity_id": "sensor.ev_charger_l2_watts", "unit": "W"},
        {"entity_id": "sensor.ev_charger_l1_current", "unit": "A"},
        {"entity_id": "sensor.ev_charger_l2_current", "unit": "A"},
    ]
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
    coordinator.settings_controller = SimpleNamespace(
        sensitivity_for_circuit=lambda _circuit_id: "balanced",
        nilm_min_delta_w=lambda _circuit_id: 100.0,
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
                "assignment_id": "assignment-dishwasher",
                "observed_transition_w": 80.0,
            },
            {
                "interval_id": "label-2",
                "label": "Dishwasher",
                "assignment_id": "assignment-dishwasher",
                "start": "2026-06-06T10:10:00+00:00",
                "end": "2026-06-06T10:40:00+00:00",
                "observed_transition_w": 83.0,
            },
            {
                "interval_id": "label-3",
                "label": "Dishwasher",
                "assignment_id": "assignment-dishwasher",
                "start": "2026-06-06T11:10:00+00:00",
                "end": "2026-06-06T11:40:00+00:00",
                "observed_transition_w": 86.0,
            },
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
                "typical_power_w": None,
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
        known_load_circuit_ids=frozenset({"pool_pump"}),
        config_for_circuit={
            config.circuit_id: config
            for config in (mains_config, known_config, solar_config)
        }.get,
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
    assert payload["sensitivity"] == {
        "current": "balanced",
        "effective_minimum_edge_w": 100.0,
        "recommendation": "sensitive",
        "action": {
            "domain": DOMAIN,
            "service": "set_circuit_sensitivity",
            "data": {
                "circuit_id": "mains",
                "preset": "sensitive",
            },
        },
    }
    assert payload["history"]["hours"] == 24.0
    assert payload["history"]["entities"] == ["sensor.mains_power"]
    assert payload["history"]["entity_series"] == [
        {
            "entity_id": "sensor.mains_power",
            "effective_role": "real_power",
            "source_unit": "W",
        }
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
    assert payload["assignments"][0]["typical_power_w"] == 83.0
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
    assert "convert_to_direct_meter" not in payload["assignments"][0]["actions"]
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
    assert payload["virtual_appliances"][0]["is_running"] is None
    assert payload["virtual_appliances"][0]["estimated_power_w"] is None
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
    assert "assign" not in payload["sessions"][0]["actions"]
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
            {
                "assignment_id": "assignment-expected",
                "display_name": "Expected Pump",
                "lifecycle_state": "expected",
                "confidence": 0.9,
                "publish_entities": False,
            },
            {
                "assignment_id": "assignment-retired",
                "display_name": "Removed Pump",
                "lifecycle_state": "retired",
                "confidence": 0.9,
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
                {
                    "signature_id": "sig-expected",
                    "display_name": "Expected recurring load",
                    "typical_watts": 90.0,
                    "expected": True,
                },
            ]
        }
    }
    coordinator._nilm_unmatched_edges = {}

    payload = nilm_workspace_payload([coordinator], circuit_id="mains")

    assert payload["lanes"]["needs_review"]["signature_ids"] == []
    assert payload["lanes"]["assigned"]["assignment_ids"] == ["assignment-assigned"]
    assert payload["lanes"]["needs_review"]["assignment_ids"] == [
        "assignment-zero-confidence",
        "assignment-ready",
    ]
    assert payload["lanes"]["published"]["assignment_ids"] == [
        "assignment-validation",
        "assignment-published",
    ]
    assert payload["lanes"]["hidden"]["assignment_ids"] == [
        "assignment-ignored",
        "assignment-retired",
    ]
    assert payload["lanes"]["hidden"]["label"] == "Removed"
    assert payload["lanes"]["hidden"]["signature_ids"] == []
    assert payload["lanes"]["expected"]["assignment_ids"] == ["assignment-expected"]
    assert payload["lanes"]["expected"]["signature_ids"] == []
    assert payload["lane_counts"]["needs_review"] == 2
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
    virtual_ids = {
        appliance["assignment_id"] for appliance in payload["virtual_appliances"]
    }
    assert "assignment-ignored" not in virtual_ids
    assert "assignment-retired" not in virtual_ids


def test_nilm_workspace_lanes_only_show_complete_component_signatures() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        _nilm_workspace_lanes,
    )

    lanes = _nilm_workspace_lanes(
        [
            {
                "signature_id": "hidden-off-edge",
                "direction": "off",
                "review_state": "ignored",
            },
            {
                "signature_id": "hidden-component",
                "direction": "on",
                "review_state": "ignored",
                "session_ids": ["session-1"],
            },
            {
                "signature_id": "expected-without-session",
                "direction": "on",
                "review_state": "expected",
            },
        ],
        [],
    )

    assert lanes["hidden"]["signature_ids"] == ["hidden-component"]
    assert lanes["expected"]["signature_ids"] == []


def test_nilm_workspace_reviews_closed_components_and_maps_stale_assignment() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    config = CircuitConfig(
        circuit_id="hvac_2",
        name="HVAC 2",
        appliance_profile=ApplianceProfile.HVAC_BLOWER,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.hvac_2_w", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=config, configs=(config,))
    fingerprints = {
        "on-pump": "direction=on|watts=0-100|var=0-100|split=unknown|leg=unknown",
        "off-pump": "direction=off|watts=0-100|var=0-100|split=unknown|leg=unknown",
        "on-blower": "direction=on|watts=300-400|var=100-200|split=unknown|leg=unknown",
        "off-blower": (
            "direction=off|watts=300-400|var=100-200|split=unknown|leg=unknown"
        ),
        "on-open-185": "direction=on|watts=100-200|var=0-100|split=unknown|leg=unknown",
        "on-open-197": "direction=on|watts=100-200|var=0-100|split=unknown|leg=unknown",
    }
    coordinator.store_data.nilm_signatures = {
        "hvac_2": [
            {
                "signature_id": signature_id,
                "feedback_fingerprint": fingerprints[signature_id],
                "typical_watts": watts,
                "typical_var": var,
                "occurrence_count": 4,
                "confidence": 0.9,
            }
            for signature_id, watts, var in (
                ("on-pump", 84.0, 18.0),
                ("off-pump", 84.0, 18.0),
                ("on-blower", 319.0, 120.0),
                ("off-blower", 319.0, 120.0),
                ("on-open-185", 185.0, 50.0),
                ("on-open-197", 197.0, 55.0),
            )
        ]
    }
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "hvac_2": [
            {
                "assignment_id": "pump",
                "display_name": "Condensate Pump 2",
                "signature_fingerprints": [
                    "direction=on|watts=0-100|var=100-200|split=unknown|leg=unknown"
                ],
                "lifecycle_state": "published",
                "confidence": 0.95,
                "publish_entities": True,
            }
        ]
    }
    start = datetime(2026, 8, 4, tzinfo=UTC)
    coordinator._nilm_unmatched_edges = {
        "hvac_2": [
            NilmEdge(start, 84.0, 18.0, direction="on"),
            NilmEdge(start + timedelta(minutes=1), -84.0, -18.0, direction="off"),
            NilmEdge(start + timedelta(minutes=2), 319.0, 120.0, direction="on"),
            NilmEdge(start + timedelta(minutes=4), -319.0, -120.0, direction="off"),
            NilmEdge(start + timedelta(minutes=5), 185.0, 50.0, direction="on"),
            NilmEdge(start + timedelta(minutes=6), 197.0, 55.0, direction="on"),
        ]
    }

    payload = nilm_workspace_payload([coordinator], circuit_id="hvac_2")

    assert payload["lanes"]["needs_review"]["signature_ids"] == ["on-blower"]
    pump = next(
        item for item in payload["signatures"] if item["signature_id"] == "on-pump"
    )
    blower = next(
        item for item in payload["signatures"] if item["signature_id"] == "on-blower"
    )
    assert pump["matched_assignment_id"] == "pump"
    assert pump["direction"] == "on"
    assert len(blower["session_ids"]) == 1
    assert blower["latest_session"]["start"] == "2026-08-04T00:02:00+00:00"
    assert blower["latest_session"]["end"] == "2026-08-04T00:04:00+00:00"
    assert blower["latest_session"]["duration_seconds"] == 120.0


def test_nilm_workspace_payload_exposes_helper_evidence_and_scoped_actions() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    source = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_w", SensorRole.REAL_POWER),),
    )
    helper = CircuitConfig(
        circuit_id="ac2",
        name="AC2",
        appliance_profile=ApplianceProfile.HVAC_BLOWER,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.ac2_w", SensorRole.REAL_POWER),),
    )
    manual_helper = CircuitConfig(
        circuit_id="condensate",
        name="Condensate Pump",
        appliance_profile=ApplianceProfile.WATER_PUMP,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.condensate_w", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=source, configs=(source, helper, manual_helper))
    coordinator.entry_id = "entry-1"
    evidence = {
        "helper_circuit_id": "ac2",
        "matched_on_count": 9,
        "source_on_count": 10,
        "matched_off_count": 8,
        "source_off_count": 10,
        "source_coverage": 0.85,
        "start_coverage": 0.9,
        "stop_coverage": 0.8,
        "helper_precision": 0.95,
        "start_lag_seconds": 42.0,
        "stop_lag_seconds": -18.0,
        "start_lag_mad_seconds": 5.0,
        "stop_lag_mad_seconds": 7.0,
        "confidence": 0.91,
        "last_observed": "2026-08-02T12:00:00+00:00",
        "suggested": True,
    }
    coordinator.store_data.nilm_signatures = {
        "mains": [
            {
                "signature_id": "sig-1",
                "feedback_fingerprint": "fp-1",
                "helper_candidates": [
                    evidence,
                    {
                        "helper_circuit_id": "condensate",
                        "matched_on_count": 1,
                        "matched_off_count": 0,
                        "confidence": 0.2,
                        "suggested": False,
                    },
                ],
            }
        ]
    }
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {
                "assignment_id": "assignment-1",
                "display_name": "Air handler",
                "signature_fingerprints": ["fp-1"],
                "lifecycle_state": "assigned",
                "helper_links": [
                    {
                        **evidence,
                        "relationship": "direct_component",
                        "status": "confirmed",
                    }
                ],
            }
        ]
    }

    payload = nilm_workspace_payload(
        [coordinator], circuit_id="mains", entry_id="entry-1"
    )
    candidate = payload["assignments"][0]["helper_candidates"][0]
    link = payload["assignments"][0]["helper_links"][0]
    helper_options = payload["assignments"][0]["helper_options"]

    assert len(payload["assignments"][0]["helper_candidates"]) == 1
    assert {key: candidate[key] for key in evidence} == evidence
    assert candidate["state"] == "suggested"
    assert "relationship_options" not in candidate
    assert candidate["actions"]["set"]["data"] == {
        "entry_id": "entry-1",
        "circuit_id": "mains",
        "assignment_id": "assignment-1",
        "helper_circuit_id": "ac2",
        "relationship": "corroborates",
    }
    assert "requires" not in candidate["actions"]["set"]
    assert link["state"] == "confirmed"
    assert link["actions"]["remove"]["data"] == {
        "entry_id": "entry-1",
        "circuit_id": "mains",
        "assignment_id": "assignment-1",
        "helper_circuit_id": "ac2",
    }
    assert [option["helper_circuit_id"] for option in helper_options] == [
        "ac2",
        "condensate",
    ]
    assert all(
        option["actions"]["set"]["data"]["entry_id"] == "entry-1"
        for option in helper_options
    )
    assert all(
        option["actions"]["set"]["data"]["relationship"] == "corroborates"
        for option in helper_options
    )


def test_nilm_workspace_reference_options_are_bounded_and_metadata_safe() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    source = CircuitConfig(
        circuit_id="mixed",
        name="Mixed",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_w", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=source)
    coordinator.entry_id = "entry-1"
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mixed": [
            {
                "assignment_id": "assignment-pump",
                "display_name": "Pump",
                "lifecycle_state": "assigned",
                "reference_state_entity_id": "switch.pump",
            }
        ]
    }
    states = [
        SimpleNamespace(
            entity_id="switch.pump",
            state="on",
            attributes={"friendly_name": "AAA Pump"},
        ),
        *[
            SimpleNamespace(
                entity_id=f"binary_sensor.state_{index:03d}",
                state="off",
                attributes={"friendly_name": f"State {index:03d}"},
            )
            for index in range(512)
        ],
        SimpleNamespace(
            entity_id="sensor.pump_power",
            state="0.084",
            attributes={
                "friendly_name": "Pump Power",
                "device_class": "power",
                "unit_of_measurement": "kW",
            },
        ),
        SimpleNamespace(
            entity_id="sensor.pump_var",
            state="27",
            attributes={
                "friendly_name": "Pump VAR",
                "device_class": "reactive_power",
                "unit_of_measurement": "var",
            },
        ),
        SimpleNamespace(
            entity_id="sensor.conflicting_power",
            state="12",
            attributes={"device_class": "power", "unit_of_measurement": "A"},
        ),
        SimpleNamespace(
            entity_id="sensor.unknown_power",
            state="unknown",
            attributes={"device_class": "power", "unit_of_measurement": "W"},
        ),
    ]
    coordinator.hass = SimpleNamespace(
        states=SimpleNamespace(async_all=lambda: states),
        entity_registry=SimpleNamespace(
            entities={
                "switch.pump": SimpleNamespace(
                    entity_id="switch.pump", device_id="device-pump"
                ),
                "sensor.pump_power": SimpleNamespace(
                    entity_id="sensor.pump_power", device_id="device-pump"
                ),
            }
        ),
    )

    reference = nilm_workspace_payload(
        [coordinator], circuit_id="mixed", entry_id="entry-1"
    )["assignments"][0]["reference"]

    assert len(reference["state_options"]) == 512
    assert reference["state_options"][0]["entity_id"] == "switch.pump"
    assert [item["entity_id"] for item in reference["power_options"]] == [
        "sensor.pump_power"
    ]
    assert all(
        not item["entity_id"].startswith("sensor.")
        for item in reference["state_options"]
    )
    assert {item["entity_id"] for item in reference["power_options"]} == {
        "sensor.pump_power"
    }
    assert reference["power_options"][0]["role"] == "real_power"
    assert reference["suggested_power_entity_id"] == "sensor.pump_power"
    assert reference["actions"]["set"]["data"]["entry_id"] == "entry-1"


def test_nilm_workspace_placeholder_session_is_evidence_only() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        _nilm_session_payload_with_actions,
    )

    payload = _nilm_session_payload_with_actions(
        {
            "session_id": "session-unassigned",
            "mains_circuit_id": "mixed",
            "signature_fingerprint": "unassigned",
            "assignment_id": "broken-assignment",
        }
    )

    assert "actions" not in payload
    assert "assignment_id" not in payload


def test_recurring_placeholder_sessions_promote_three_reviewable_components() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    config = CircuitConfig(
        circuit_id="mixed",
        name="Mixed",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_w", SensorRole.REAL_POWER, unit="W"),),
    )
    coordinator = _coordinator(config=config, configs=(config,))
    coordinator.store_data.nilm_signatures = {
        "mixed": [
            {
                "signature_id": f"on-{index}",
                "feedback_fingerprint": f"direction=on|watts={bucket}",
                "direction": "on",
                "median_delta_w": watts,
                "median_delta_var": reactive,
                "occurrence_count": 3,
                "confidence": 0.6,
            }
            for index, (bucket, watts, reactive) in enumerate(
                [("0-100", 82.0, 19.0), ("100-200", 190.0, 68.0),
                 ("300-400", 320.0, 120.0)],
                start=1,
            )
        ]
    }
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mixed": [
            {
                "assignment_id": "broken-assignment",
                "display_name": "Wrong old label",
                "lifecycle_state": "published",
                "publish_entities": True,
                "signature_fingerprints": ["unassigned"],
            }
        ]
    }
    start = datetime(2026, 8, 4, tzinfo=UTC)
    coordinator.store_data.nilm_session_history_by_circuit = {
        "mixed": [
            {
                "session_id": f"raw-{group}-{occurrence}",
                "mains_circuit_id": "mixed",
                "signature_fingerprint": "unassigned",
                "assignment_id": "broken-assignment",
                "start": (
                    start + timedelta(minutes=group * 60 + occurrence * 10)
                ).isoformat(),
                "end": (
                    start + timedelta(minutes=group * 60 + occurrence * 10 + 5)
                ).isoformat(),
                "duration_seconds": 300.0,
                "median_power_w": watts,
                "estimated_energy_kwh": watts * 300.0 / 3_600_000.0,
                "on_delta_w": watts,
                "off_delta_w": -watts,
                "on_delta_var": reactive,
                "off_delta_var": -reactive,
            }
            for group, (watts, reactive) in enumerate(
                [(82.0, 19.0), (190.0, 68.0), (320.0, 120.0)]
            )
            for occurrence in range(3)
        ]
    }

    payload = nilm_workspace_payload([coordinator], circuit_id="mixed")

    assert payload["lanes"]["needs_review"]["signature_ids"] == [
        "on-1",
        "on-2",
        "on-3",
    ]
    assert all("actions" not in session for session in payload["sessions"])
    assert all(
        session.get("display_label") != "Wrong old label"
        for session in payload["sessions"]
    )


def test_nilm_workspace_hides_retired_and_reviews_unassigned_intervals() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        _nilm_workspace_lanes,
        _nilm_workspace_session_specs,
    )

    signatures = [
        {"signature_id": "sig-retired", "review_state": "assigned"},
        {
            "signature_id": "sig-new",
            "review_state": "new",
            "direction": "on",
            "session_ids": ["session-new"],
        },
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
    assert set(lanes) == {"needs_review", "assigned", "published", "expected", "hidden"}
    assert lanes["needs_review"]["signature_ids"] == ["sig-new"]
    assert lanes["needs_review"]["interval_ids"] == ["interval-new"]
    assert lanes["hidden"]["assignment_ids"] == ["assignment-retired"]


def test_nilm_workspace_hidden_items_restore_and_publish_blockers_are_explicit() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    config = CircuitConfig(
        circuit_id="mixed",
        name="Mixed",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_w", SensorRole.REAL_POWER, unit="W"),),
    )
    coordinator = _coordinator(config=config, configs=(config,))
    coordinator.entry_id = "entry-1"
    coordinator.store_data.nilm_signatures = {
        "mixed": [
            {
                "signature_id": "signature-ignored",
                "feedback_fingerprint": "fingerprint-ignored",
                "ignored": True,
                "review_state": "ignored",
            },
            {
                "signature_id": "signature-ready",
                "feedback_fingerprint": "fingerprint-ready",
                "confidence": 0.91,
            },
        ]
    }
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mixed": [
            {
                "assignment_id": "assignment-retired",
                "lifecycle_state": "retired",
                "signature_fingerprints": ["fingerprint-retired"],
                "confidence": 0.9,
            },
            {
                "assignment_id": "assignment-empty",
                "lifecycle_state": "assigned",
                "signature_fingerprints": [],
                "session_ids": [],
                "label_interval_ids": [],
                "confidence": 0.9,
            },
            {
                "assignment_id": "assignment-ready",
                "lifecycle_state": "assigned",
                "signature_fingerprints": ["fingerprint-ready"],
                "confidence": 0.91,
            },
            {
                "assignment_id": "assignment-converted",
                "lifecycle_state": "converted",
                "conversion_state": "direct_meter",
                "direct_circuit_id": "ac2",
                "signature_fingerprints": ["fingerprint-converted"],
                "confidence": 0.91,
            },
        ]
    }

    payload = nilm_workspace_payload(
        [coordinator], circuit_id="mixed", entry_id="entry-1"
    )
    ignored = next(
        item
        for item in payload["signatures"]
        if item["signature_id"] == "signature-ignored"
    )
    retired = next(
        item
        for item in payload["assignments"]
        if item["assignment_id"] == "assignment-retired"
    )
    empty = next(
        item
        for item in payload["assignments"]
        if item["assignment_id"] == "assignment-empty"
    )
    ready = next(
        item
        for item in payload["assignments"]
        if item["assignment_id"] == "assignment-ready"
    )
    converted = next(
        item
        for item in payload["assignments"]
        if item["assignment_id"] == "assignment-converted"
    )

    assert ignored["actions"]["restore"]["data"] == {
        "entry_id": "entry-1",
        "circuit_id": "mixed",
        "signature_id": "signature-ignored",
    }
    assert retired["actions"]["restore"]["data"] == {
        "entry_id": "entry-1",
        "circuit_id": "mixed",
        "assignment_id": "assignment-retired",
    }
    assert retired["publication"]["available"] is False
    assert empty["publication"] == {
        "available": False,
        "reason": "Assign at least one detected load before publishing.",
    }
    assert "publish" not in empty["actions"]
    assert ready["publication"]["available"] is True
    assert ready["actions"]["publish"]["service"] == (
        "publish_nilm_appliance_assignment"
    )
    assert converted["actions"]["restore"] == {
        "domain": DOMAIN,
        "service": "restore_nilm_item",
        "data": {
            "entry_id": "entry-1",
            "circuit_id": "mixed",
            "assignment_id": "assignment-converted",
        },
    }


@pytest.mark.parametrize(
    ("sensors", "expected", "has_requirement"),
    (
        (
            (SensorRef("sensor.load_w", SensorRole.REAL_POWER, unit="W"),),
            "not_applicable",
            False,
        ),
        (
            (
                SensorRef("sensor.load_l1_w", SensorRole.REAL_POWER, "a", "W"),
                SensorRef("sensor.load_l2_w", SensorRole.REAL_POWER, "b", "W"),
            ),
            "available",
            False,
        ),
        (
            (
                SensorRef("sensor.load_l1_w", SensorRole.REAL_POWER, "leg1", "W"),
                SensorRef("sensor.load_l2_w", SensorRole.REAL_POWER, "leg2", "W"),
            ),
            "available",
            False,
        ),
        (
            (SensorRef("sensor.load_l1_w", SensorRole.REAL_POWER, "a", "W"),),
            "unavailable",
            True,
        ),
    ),
)
def test_nilm_signature_topology_is_capability_gated(
    sensors: tuple[SensorRef, ...],
    expected: str,
    has_requirement: bool,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    config = CircuitConfig(
        circuit_id="load",
        name="Load",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=sensors,
    )
    coordinator = _coordinator(config=config, configs=(config,))
    coordinator.store_data.nilm_signatures = {
        "load": [
            {
                "signature_id": "signature-1",
                "voltage_class": "unknown" if expected != "available" else "240 V",
                "dominant_leg": "unknown" if expected != "available" else "a",
            }
        ]
    }

    signature = nilm_workspace_payload([coordinator], circuit_id="load")["signatures"][
        0
    ]

    assert signature["topology_applicability"] == expected
    assert ("topology_requirement" in signature) is has_requirement
    if expected != "available":
        assert "voltage_class" not in signature
        assert "dominant_leg" not in signature


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


def test_nilm_assignment_detail_links_keep_duplicate_assignment_entry_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import panel
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    coordinators = [
        _nilm_workspace_coordinator(
            entry_id=entry_id,
            name=name,
            entity_id=f"sensor.{entry_id}_mains_power",
        )
        for entry_id, name in (
            ("entry/one", "First Mains"),
            ("entry two", "Second Mains"),
        )
    ]
    for coordinator in coordinators:
        coordinator.store_data.nilm_appliance_assignments_by_circuit = {
            "mains": [
                {
                    "assignment_id": "shared-assignment",
                    "display_name": coordinator.circuit_configs[0].name,
                    "mains_circuit_id": "mains",
                    "lifecycle_state": "assigned",
                }
            ]
        }

    workspaces = [
        nilm_workspace_payload(
            coordinators,
            circuit_id="mains",
            entry_id=coordinator.entry_id,
        )
        for coordinator in coordinators
    ]

    for coordinator, workspace in zip(coordinators, workspaces, strict=True):
        for path in (
            workspace["assignments"][0]["appliance_detail_path"],
            workspace["virtual_appliances"][0]["appliance_detail_path"],
            workspace["virtual_appliances"][0]["appliance_detail_api_path"],
        ):
            assert parse_qs(urlparse(path).query)["entry_id"] == [coordinator.entry_id]
        assert all(
            action["data"]["entry_id"] == coordinator.entry_id
            for action in _nilm_service_actions(workspace)
        )

    selected: list[str] = []
    monkeypatch.setattr(
        panel,
        "appliance_detail_for_assignment",
        lambda coordinator, _assignment_id: (
            selected.append(coordinator.entry_id) or SimpleNamespace()
        ),
    )
    monkeypatch.setattr(
        panel,
        "_appliance_detail_payload",
        lambda coordinator, _detail, **_kwargs: {"entry_id": coordinator.entry_id},
    )
    for workspace in workspaces:
        for path in (
            workspace["assignments"][0]["appliance_detail_path"],
            workspace["virtual_appliances"][0]["appliance_detail_api_path"],
        ):
            query = parse_qs(urlparse(path).query)
            assert (
                panel.appliance_detail_payload(
                    coordinators,
                    assignment_id=query["assignment_id"][0],
                    entry_id=query["entry_id"][0],
                )["entry_id"]
                == query["entry_id"][0]
            )
    assert selected == ["entry/one", "entry/one", "entry two", "entry two"]


@pytest.mark.parametrize(
    ("profile", "mode", "expected"),
    [
        (
            ApplianceProfile.HVAC_BLOWER,
            CircuitMode.MIXED,
            [
                {
                    "value": "mixed-configured-primary",
                    "label": "Configured primary: Upstairs Blower",
                }
            ],
        ),
        (ApplianceProfile.MIXED, CircuitMode.MIXED, []),
        (ApplianceProfile.MAINS_NILM, CircuitMode.MAINS_NILM, []),
    ],
)
def test_nilm_workspace_only_offers_configured_primary_for_primary_mixed(
    profile: ApplianceProfile,
    mode: CircuitMode,
    expected: list[dict[str, str]],
) -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    config = CircuitConfig(
        circuit_id="mixed",
        name="Upstairs Blower",
        appliance_profile=profile,
        mode=mode,
        sensors=(SensorRef("sensor.mixed_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=config, configs=(config,))
    coordinator.entry_id = "entry-1"
    coordinator.store_data.nilm_signatures = {"mixed": [{"signature_id": "sig-1"}]}
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {}

    payload = nilm_workspace_payload([coordinator], circuit_id="mixed")

    assert (
        payload["signatures"][0]["actions"]["assign"].get("assignment_options", [])
        == expected
    )
    assert coordinator.store_data.nilm_appliance_assignments_by_circuit == {}
    assert "assignment_id" not in coordinator.store_data.nilm_signatures["mixed"][0]


def test_nilm_workspace_limits_known_loads_and_reuses_primary_options() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    primary_mixed = CircuitConfig(
        circuit_id="hvac_1",
        name="HVAC 1",
        appliance_profile=ApplianceProfile.HVAC_BLOWER,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.hvac_power", SensorRole.REAL_POWER),),
    )
    pure_mixed = CircuitConfig(
        circuit_id="mixed",
        name="Mixed",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_power", SensorRole.REAL_POWER),),
    )
    fridge = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(
        config=mains,
        configs=(mains, primary_mixed, pure_mixed, fridge),
    )
    coordinator.circuit_registry = SimpleNamespace(
        known_load_circuit_ids=frozenset({"fridge"}),
        config_for_circuit={
            config.circuit_id: config
            for config in (mains, primary_mixed, pure_mixed, fridge)
        }.get,
    )
    coordinator.store_data.nilm_signatures = {
        "hvac_1": [{"signature_id": "signature-1"}],
    }
    coordinator.store_data.nilm_label_intervals_by_circuit = {
        "hvac_1": [{"interval_id": "interval-1", "label": "Blower"}],
    }
    coordinator.store_data.nilm_session_history_by_circuit = {
        "hvac_1": [
            {
                "session_id": "session-complete",
                "mains_circuit_id": "hvac_1",
                "signature_fingerprint": "signature-1",
                "start": "2026-06-06T10:00:00+00:00",
                "end": "2026-06-06T10:30:00+00:00",
            },
            {
                "session_id": "session-open",
                "mains_circuit_id": "hvac_1",
                "signature_fingerprint": "signature-1",
                "assignment_id": "hvac_1-configured-primary",
                "start": "2026-06-06T11:00:00+00:00",
                "end": None,
            },
        ],
    }

    mains_payload = nilm_workspace_payload([coordinator], circuit_id="mains")
    primary_mixed_payload = nilm_workspace_payload(
        [coordinator], circuit_id="hvac_1"
    )
    pure_mixed_payload = nilm_workspace_payload([coordinator], circuit_id="mixed")

    assert mains_payload["known_load_overlays"]
    assert primary_mixed_payload["known_load_overlays"] == []
    assert pure_mixed_payload["known_load_overlays"] == []

    primary_value = "hvac_1-configured-primary"
    for row in (
        primary_mixed_payload["signatures"][0],
        primary_mixed_payload["label_intervals"][0],
        primary_mixed_payload["sessions"][0],
    ):
        options = row["actions"]["assign"]["assignment_options"]
        assert {option["value"] for option in options} >= {primary_value}

    open_session = next(
        item for item in primary_mixed_payload["sessions"] if not item["end"]
    )
    assert "validate" not in open_session.get("actions", {})
    assert "reject" not in open_session.get("actions", {})


def test_nilm_workspace_deduplicates_existing_configured_primary_target() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    config = CircuitConfig(
        circuit_id="mixed",
        name="Blower",
        appliance_profile=ApplianceProfile.HVAC_BLOWER,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=config, configs=(config,))
    coordinator.entry_id = "entry-1"
    coordinator.store_data.nilm_signatures = {"mixed": [{"signature_id": "sig-1"}]}
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mixed": [
            {
                "assignment_id": "mixed-configured-primary",
                "display_name": "Blower",
                "lifecycle_state": "assigned",
                "role": "primary",
            }
        ]
    }

    options = nilm_workspace_payload(
        [coordinator],
        circuit_id="mixed",
    )["signatures"][0]["actions"]["assign"]["assignment_options"]

    assert options == [
        {
            "value": "mixed-configured-primary",
            "label": "Configured primary: Blower",
        }
    ]


def test_nilm_workspace_can_confirm_the_configured_primary_assignment() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    config = CircuitConfig(
        circuit_id="mixed",
        name="Blower",
        appliance_profile=ApplianceProfile.HVAC_BLOWER,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=config, configs=(config,))
    coordinator.entry_id = "entry-1"
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mixed": [
            {
                "assignment_id": "mixed-configured-primary",
                "display_name": "Blower",
                "lifecycle_state": "needs_validation",
                "role": "primary",
                "signature_fingerprints": ["fingerprint-1"],
                "confidence": 0.9,
            }
        ]
    }

    assignment = nilm_workspace_payload(
        [coordinator],
        circuit_id="mixed",
        entry_id="entry-1",
    )["assignments"][0]

    assert assignment["display_name"] == "Blower (estimated)"
    assert assignment["actions"]["confirm_primary"] == {
        "domain": DOMAIN,
        "service": "confirm_nilm_configured_primary",
        "data": {
            "entry_id": "entry-1",
            "circuit_id": "mixed",
            "assignment_id": "mixed-configured-primary",
        },
    }


def test_nilm_workspace_suggests_largest_unassigned_recurring_primary() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    config = CircuitConfig(
        circuit_id="mixed",
        name="Blower",
        appliance_profile=ApplianceProfile.HVAC_BLOWER,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_w", SensorRole.REAL_POWER, unit="W"),),
    )
    coordinator = _coordinator(config=config, configs=(config,))
    coordinator.entry_id = "entry-1"
    coordinator.store_data.nilm_signatures = {
        "mixed": [
            {
                "signature_id": "signature-weak",
                "feedback_fingerprint": "fingerprint-weak",
                "typical_watts": 1400.0,
                "occurrence_count": 2,
                "confidence": 0.95,
            },
            {
                "signature_id": "signature-assigned",
                "feedback_fingerprint": "fingerprint-assigned",
                "typical_watts": 1200.0,
                "occurrence_count": 6,
                "confidence": 0.95,
            },
            {
                "signature_id": "signature-z",
                "feedback_fingerprint": "fingerprint-z",
                "typical_watts": 850.0,
                "occurrence_count": 5,
                "confidence": 0.9,
            },
            {
                "signature_id": "signature-a",
                "feedback_fingerprint": "fingerprint-a",
                "typical_watts": 850.0,
                "occurrence_count": 5,
                "confidence": 0.9,
            },
        ]
    }
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mixed": [
            {
                "assignment_id": "assignment-other",
                "signature_fingerprints": ["fingerprint-assigned"],
                "lifecycle_state": "assigned",
                "confidence": 0.95,
            }
        ]
    }

    payload = nilm_workspace_payload(
        [coordinator], circuit_id="mixed", entry_id="entry-1"
    )
    primary = payload["configured_primary"]

    assert primary["assignment_id"] == "mixed-configured-primary"
    assert primary["display_name"] == "Blower"
    assert primary["appliance_profile"] == ApplianceProfile.HVAC_BLOWER.value
    assert primary["current_binding"] is None
    assert primary["suggestion"]["signature_id"] == "signature-a"
    assert primary["suggestion"]["action"] == {
        "domain": DOMAIN,
        "service": "assign_signature_to_appliance",
        "data": {
            "entry_id": "entry-1",
            "circuit_id": "mixed",
            "signature_id": "signature-a",
            "assignment_id": "mixed-configured-primary",
            "label": "Blower",
            "appliance_profile": ApplianceProfile.HVAC_BLOWER.value,
        },
    }
    assert coordinator.store_data.nilm_appliance_assignments_by_circuit == {
        "mixed": [
            coordinator.store_data.nilm_appliance_assignments_by_circuit["mixed"][0]
        ]
    }


def test_nilm_workspace_suggests_larger_primary_when_current_binding_is_wrong() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    config = CircuitConfig(
        circuit_id="mixed",
        name="Blower",
        appliance_profile=ApplianceProfile.HVAC_BLOWER,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_w", SensorRole.REAL_POWER, unit="W"),),
    )
    coordinator = _coordinator(config=config, configs=(config,))
    coordinator.entry_id = "entry-1"
    coordinator.store_data.nilm_signatures = {
        "mixed": [
            {
                "signature_id": "signature-condensate",
                "feedback_fingerprint": "fingerprint-condensate",
                "typical_watts": 90.0,
                "occurrence_count": 6,
                "confidence": 0.9,
                "assignment_id": "mixed-configured-primary",
            },
            {
                "signature_id": "signature-blower",
                "feedback_fingerprint": "fingerprint-blower",
                "typical_watts": 850.0,
                "occurrence_count": 5,
                "confidence": 0.9,
            },
        ]
    }
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mixed": [
            {
                "assignment_id": "mixed-configured-primary",
                "signature_fingerprints": ["fingerprint-condensate"],
                "lifecycle_state": "assigned",
                "confidence": 0.9,
            }
        ]
    }

    primary = nilm_workspace_payload(
        [coordinator], circuit_id="mixed", entry_id="entry-1"
    )["configured_primary"]

    assert primary["current_binding"]["signature_id"] == "signature-condensate"
    assert primary["suggestion"]["signature_id"] == "signature-blower"
    assert primary["suggestion"]["action"]["data"]["assignment_id"] == (
        "mixed-configured-primary"
    )


def test_nilm_workspace_does_not_treat_off_edge_as_primary_binding() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    config = CircuitConfig(
        circuit_id="mixed",
        name="Blower",
        appliance_profile=ApplianceProfile.HVAC_BLOWER,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_w", SensorRole.REAL_POWER, unit="W"),),
    )
    coordinator = _coordinator(config=config, configs=(config,))
    coordinator.store_data.nilm_signatures = {
        "mixed": [
            {
                "signature_id": "off-blower",
                "feedback_fingerprint": "direction=off|watts=200-300",
                "direction": "off",
                "typical_watts": 275.0,
                "occurrence_count": 6,
                "confidence": 0.95,
                "assignment_id": "mixed-configured-primary",
            },
            {
                "signature_id": "on-blower",
                "feedback_fingerprint": "direction=on|watts=200-300",
                "direction": "on",
                "typical_watts": 300.0,
                "occurrence_count": 6,
                "confidence": 0.95,
            },
        ]
    }
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mixed": [
            {
                "assignment_id": "mixed-configured-primary",
                "signature_fingerprints": ["direction=off|watts=200-300"],
                "lifecycle_state": "validated",
                "confidence": 0.95,
            }
        ]
    }

    primary = nilm_workspace_payload([coordinator], circuit_id="mixed")[
        "configured_primary"
    ]

    assert primary["current_binding"] is None
    assert primary["suggestion"]["signature_id"] == "on-blower"


def test_nilm_workspace_can_merge_a_reviewed_detection_into_configured_primary(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    config = CircuitConfig(
        circuit_id="hvac_1",
        name="HVAC 1",
        appliance_profile=ApplianceProfile.HVAC_BLOWER,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.hvac_1_w", SensorRole.REAL_POWER, unit="W"),),
    )
    coordinator = _coordinator(config=config, configs=(config,))
    coordinator.entry_id = "entry-1"
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "hvac_1": [
            {
                "assignment_id": "hvac_1-configured-primary",
                "display_name": "HVAC 1",
                "lifecycle_state": "validated",
                "role": "primary",
                "signature_fingerprints": ["direction=off|watts=200-300"],
            },
            {
                "assignment_id": "assignment-hvac-1",
                "display_name": "HVAC 1",
                "lifecycle_state": "assigned",
                "signature_fingerprints": ["direction=on|watts=300-400"],
                "label_interval_ids": ["label-hvac-1"],
                "confidence": 0.95,
            },
        ]
    }

    assignment = next(
        item
        for item in nilm_workspace_payload(
            [coordinator], circuit_id="hvac_1", entry_id="entry-1"
        )["assignments"]
        if item["assignment_id"] == "assignment-hvac-1"
    )

    assert assignment["actions"]["confirm_primary"] == {
        "domain": DOMAIN,
        "service": "merge_nilm_assignments",
        "data": {
            "entry_id": "entry-1",
            "circuit_id": "hvac_1",
            "source_assignment_id": "assignment-hvac-1",
            "target_assignment_id": "hvac_1-configured-primary",
        },
    }
    coordinator.store_data.nilm_appliance_assignments_by_circuit["hvac_1"][1][
        "lifecycle_state"
    ] = "expected"
    hidden_assignment = next(
        item
        for item in nilm_workspace_payload(
            [coordinator], circuit_id="hvac_1", entry_id="entry-1"
        )["assignments"]
        if item["assignment_id"] == "assignment-hvac-1"
    )
    assert "confirm_primary" not in hidden_assignment["actions"]


def test_nilm_workspace_omits_configured_primary_for_pure_mixed() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    config = CircuitConfig(
        circuit_id="mixed",
        name="Mixed",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_w", SensorRole.REAL_POWER, unit="W"),),
    )
    coordinator = _coordinator(config=config, configs=(config,))
    coordinator.store_data.nilm_signatures = {
        "mixed": [
            {
                "signature_id": "signature-1",
                "typical_watts": 900.0,
                "occurrence_count": 5,
                "confidence": 0.9,
            }
        ]
    }

    assert "configured_primary" not in nilm_workspace_payload(
        [coordinator], circuit_id="mixed"
    )


@pytest.mark.asyncio
async def test_configured_primary_service_creation_is_entry_scoped() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_ASSIGN_SIGNATURE_TO_APPLIANCE,
        _dispatch_service,
    )
    from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData

    coordinators = {}
    for entry_id, name in (("entry-1", "First Blower"), ("entry-2", "Second Blower")):
        config = CircuitConfig(
            circuit_id="mixed",
            name=name,
            appliance_profile=ApplianceProfile.HVAC_BLOWER,
            mode=CircuitMode.MIXED,
        )
        coordinator = EnergyAnalyzerCoordinator(
            SimpleNamespace(data={}),
            entry_id=entry_id,
            store_data=FeatureStoreData(
                nilm_signatures={
                    "mixed": [
                        {
                            "signature_id": "sig-1",
                            "feedback_fingerprint": "fp-1",
                        }
                    ]
                }
            ),
        )
        coordinator.circuit_configs = (config,)
        coordinators[entry_id] = coordinator

    await _dispatch_service(
        SimpleNamespace(data={DOMAIN: coordinators}),
        SERVICE_ASSIGN_SIGNATURE_TO_APPLIANCE,
        {
            "entry_id": "entry-2",
            "circuit_id": "mixed",
            "signature_id": "sig-1",
            "label": "spoofed",
            "assignment_id": "mixed-configured-primary",
        },
    )

    first_store = coordinators["entry-1"].store_data
    second_store = coordinators["entry-2"].store_data
    assert first_store.nilm_appliance_assignments_by_circuit == {}
    assignment = second_store.nilm_appliance_assignments_by_circuit["mixed"][0]
    assert assignment["display_name"] == "Second Blower"
    assert assignment["role"] == "primary"


def _nilm_service_actions(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, dict):
        actions = (
            [payload]
            if payload.get("domain") == DOMAIN
            and isinstance(payload.get("service"), str)
            and isinstance(payload.get("data"), dict)
            else []
        )
        return actions + [
            action
            for value in payload.values()
            for action in _nilm_service_actions(value)
        ]
    if isinstance(payload, list):
        return [action for value in payload for action in _nilm_service_actions(value)]
    return []


def test_nilm_payload_actions_keep_selected_entry_id() -> None:
    """Catches nested workspace actions dropping their selected config entry."""
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        _nilm_payload_for_circuit,
        nilm_workspace_payload,
    )

    coordinator = _nilm_workspace_coordinator(
        entry_id="entry-2",
        name="Second Mains",
        entity_id="sensor.second_mains_power",
    )
    coordinator.store_data.nilm_signatures = {
        "mains": [{"signature_id": "signature-1"}]
    }
    coordinator.store_data.nilm_label_intervals_by_circuit = {
        "mains": [{"interval_id": "interval-1"}]
    }
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [{"assignment_id": "assignment-1", "lifecycle_state": "assigned"}]
    }

    workspace = nilm_workspace_payload(
        [coordinator], circuit_id="mains", entry_id="entry-2"
    )
    summary = _nilm_payload_for_circuit(coordinator, "mains")
    actions = _nilm_service_actions(workspace) + _nilm_service_actions(summary)

    assert actions
    assert all(action["data"]["entry_id"] == "entry-2" for action in actions)


def test_nilm_workspace_payload_rejects_missing_source_in_requested_entry() -> None:
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
        [first, second], circuit_id="mains", entry_id="missing-entry"
    )

    assert payload["status"] == "not_found"
    assert payload["requested_circuit_id"] == "mains"
    assert "circuit" not in payload


def test_nilm_workspace_missing_source_message_is_source_neutral() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    payload = nilm_workspace_payload([], circuit_id="mixed", entry_id="entry-1")

    assert payload["message"] == (
        "No Load Separation source is available for this workspace."
    )


def test_nilm_workspace_payload_lists_all_sources_for_requested_entry() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    mixed = CircuitConfig(
        circuit_id="mixed",
        name="Mixed Loads",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_power", SensorRole.REAL_POWER),),
    )
    hvac = CircuitConfig(
        circuit_id="hvac_2",
        name="HVAC 2",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.hvac_2_power", SensorRole.REAL_POWER),),
    )
    dedicated = CircuitConfig(
        circuit_id="fridge",
        name="Refrigerator",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
    )
    first = _coordinator(config=mains, configs=(mains, mixed, hvac, dedicated))
    first.entry_id = "entry-1"
    second = _nilm_workspace_coordinator(
        entry_id="entry-2",
        name="Other Mains",
        entity_id="sensor.other_mains_power",
    )

    payload = nilm_workspace_payload(
        [first, second], circuit_id="hvac_2", entry_id="entry-1"
    )

    assert payload["source"] == {
        "entry_id": "entry-1",
        "circuit_id": "hvac_2",
        "name": "HVAC 2",
        "source_kind": "primary_mixed",
    }
    assert payload["sources"] == [
        {
            "entry_id": "entry-1",
            "circuit_id": "mains",
            "name": "Mains",
            "source_kind": "mains",
            "path": (
                "/circuitsetup-energy-analyzer-evidence?"
                "nilm_workspace=1&entry_id=entry-1&circuit_id=mains"
            ),
        },
        {
            "entry_id": "entry-1",
            "circuit_id": "mixed",
            "name": "Mixed Loads",
            "source_kind": "pure_mixed",
            "path": (
                "/circuitsetup-energy-analyzer-evidence?"
                "nilm_workspace=1&entry_id=entry-1&circuit_id=mixed"
            ),
        },
        {
            "entry_id": "entry-1",
            "circuit_id": "hvac_2",
            "name": "HVAC 2",
            "source_kind": "primary_mixed",
            "path": (
                "/circuitsetup-energy-analyzer-evidence?"
                "nilm_workspace=1&entry_id=entry-1&circuit_id=hvac_2"
            ),
        },
    ]


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

    assert payload == [
        [
            {
                "entity_id": "sensor.second_mains_power",
                "effective_role": "real_power",
                "source_unit": "W",
            }
        ]
    ]


def test_nilm_workspace_payload_accepts_sensor_backed_mixed_source() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    fridge = CircuitConfig(
        circuit_id="fridge",
        name="Refrigerator",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=fridge, configs=(fridge,))
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "fridge": [{"assignment_id": "assignment-fridge", "appliance_id": "fridge"}]
    }
    coordinator.state.nilm_unknown_loads_by_circuit = {
        "fridge": {"unknown_loads": [{"signature_id": "signature-fridge"}]}
    }

    payload = nilm_workspace_payload([coordinator], circuit_id="fridge")

    assert payload["status"] == "ok"
    assert payload["assignments"][0]["assignment_id"] == "assignment-fridge"
    assert payload["signatures"][0]["signature_id"] == "signature-fridge"
    assert payload["history"]["entities"] == ["sensor.fridge_power"]


@pytest.mark.asyncio
async def test_nilm_workspace_history_view_queries_mixed_source_entity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import panel

    fridge = CircuitConfig(
        circuit_id="fridge",
        name="Refrigerator",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=fridge, configs=(fridge,))
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    request = SimpleNamespace(
        app={panel.KEY_HASS: hass}, query={"circuit_id": "fridge"}
    )
    queried: list[str] = []

    async def history_rows(_hass, _start, _end, entity_ids):
        queried.extend(entity_ids)
        return []

    monkeypatch.setattr(panel, "_async_history_rows", history_rows)
    monkeypatch.setattr(panel.web, "json_response", lambda payload: payload)

    await panel.NilmWorkspaceHistoryView().get(request)

    assert queried == ["sensor.fridge_power"]


@pytest.mark.asyncio
async def test_nilm_workspace_history_view_forwards_repeated_helper_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import panel

    class Query(dict):
        def getall(self, key, default):
            return ["helper-a", "helper-b"] if key == "helper_circuit_id" else default

    captured = None

    async def history_payload(_hass, _coordinators, **kwargs):
        nonlocal captured
        captured = kwargs
        return []

    request = SimpleNamespace(
        app={panel.KEY_HASS: SimpleNamespace()}, query=Query(circuit_id="mains")
    )
    monkeypatch.setattr(panel, "nilm_workspace_history_payload", history_payload)
    monkeypatch.setattr(panel, "_loaded_coordinators", lambda _hass: ())
    monkeypatch.setattr(panel.web, "json_response", lambda payload: payload)

    await panel.NilmWorkspaceHistoryView().get(request)

    assert captured["helper_circuit_ids"] == ["helper-a", "helper-b"]


@pytest.mark.asyncio
async def test_nilm_history_returns_requested_current_entry_real_power_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import panel

    source = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_w", SensorRole.REAL_POWER),),
    )
    helpers = tuple(
        CircuitConfig(
            circuit_id=f"helper-{index}",
            name=f"Helper {index}",
            appliance_profile=ApplianceProfile.MOTOR_LOAD,
            mode=CircuitMode.SINGLE_PHASE,
            sensors=(
                SensorRef(f"sensor.helper_{index}_w", SensorRole.REAL_POWER),
                SensorRef(f"sensor.helper_{index}_pf", SensorRole.POWER_FACTOR),
            ),
        )
        for index in range(1, 6)
    )
    coordinator = _coordinator(config=source, configs=(source, *helpers))
    coordinator.entry_id = "entry-1"
    coordinator.store_data.nilm_signatures = {
        "mains": [
            {
                "signature_id": "sig-1",
                "helper_candidates": [{"helper_circuit_id": "helper-2"}],
            }
        ]
    }
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {
                "assignment_id": "assignment-1",
                "helper_links": [{"helper_circuit_id": "helper-1"}],
            }
        ]
    }
    other = _nilm_workspace_coordinator(
        entry_id="entry-2", name="Other", entity_id="sensor.other"
    )
    other.circuit_configs += (
        CircuitConfig(
            circuit_id="cross-entry",
            name="Cross entry",
            appliance_profile=ApplianceProfile.MOTOR_LOAD,
            mode=CircuitMode.SINGLE_PHASE,
            sensors=(SensorRef("sensor.cross_entry_w", SensorRole.REAL_POWER),),
        ),
    )
    queried = []

    async def history_rows(_hass, _start, _end, entity_ids):
        queried.extend(entity_ids)
        return []

    monkeypatch.setattr(panel, "_async_history_rows", history_rows)
    await panel.nilm_workspace_history_payload(
        SimpleNamespace(),
        [coordinator, other],
        circuit_id="mains",
        entry_id="entry-1",
        helper_circuit_ids=[
            "helper-2",
            "mains",
            "unknown",
            "helper-2",
            "cross-entry",
            "helper-1",
            "helper-3",
            "helper-4",
            "helper-5",
        ],
    )

    assert queried == [
        "sensor.mains_w",
        "sensor.helper_2_w",
        "sensor.helper_1_w",
    ]


@pytest.mark.asyncio
async def test_nilm_history_ignores_malformed_persisted_helper_containers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import panel

    source = CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_w", SensorRole.REAL_POWER),),
    )
    helper = CircuitConfig(
        circuit_id="helper",
        name="Helper",
        appliance_profile=ApplianceProfile.MOTOR_LOAD,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.helper_w", SensorRole.REAL_POWER),),
    )
    arbitrary = CircuitConfig(
        circuit_id="arbitrary",
        name="Arbitrary",
        appliance_profile=ApplianceProfile.MOTOR_LOAD,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(SensorRef("sensor.arbitrary_w", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=source, configs=(source, helper, arbitrary))
    coordinator.store_data.nilm_signatures = {
        "mains": [
            {"helper_candidates": None},
            {"helper_candidates": "bad"},
            {"helper_candidates": [None, "bad"]},
        ]
    }
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {"helper_links": None},
            {"helper_links": "bad"},
            {"helper_links": [None, "bad", {"helper_circuit_id": "helper"}]},
        ]
    }
    queried = []

    async def history_rows(_hass, _start, _end, entity_ids):
        queried.extend(entity_ids)
        return []

    monkeypatch.setattr(panel, "_async_history_rows", history_rows)
    await panel.nilm_workspace_history_payload(
        SimpleNamespace(),
        [coordinator],
        circuit_id="mains",
        helper_circuit_ids=["arbitrary", "helper"],
    )

    assert queried == ["sensor.mains_w", "sensor.helper_w"]


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


def test_nilm_workspace_payload_rejects_untyped_runtime_history_source() -> None:
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
    assert payload["history"]["entities"] == []
    assert payload["history"]["missing_real_power_reason"] == (
        "Configure a real-power sensor measured in W, kW, mW, or MW."
    )


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
    assert virtual["is_running"] is None
    assert virtual["estimated_power_w"] is None
    assert virtual["estimated_energy_kwh_today"] == 0.0
    assert virtual["active_session_id"] is None
    assert virtual["last_seen"] == "2026-06-06T08:00:00+00:00"
    assert virtual["model_status"] == "learning"


def test_nilm_workspace_payload_exposes_reconciliation_health() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    mains = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=mains, configs=(mains,))
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mains": [
            {
                "assignment_id": "washer",
                "display_name": "Washer",
                "mains_circuit_id": "mains",
                "lifecycle_state": "published",
                "helper_links": [{"status": "degraded"}],
            }
        ]
    }
    coordinator.state.nilm_component_runtime_by_circuit = {
        "mains": {"washer": {"status": "uncertain", "consistent": False}}
    }
    coordinator.state.nilm_reconciliation_by_circuit = {
        "mains": {
            "residual_w": 42.0,
            "residual_energy_kwh": 0.25,
            "tolerance_w": 30.0,
            "consistent": False,
            "conflict": "over_allocation",
            "review_item": {"type": "model_conflict", "reason": "over_allocation"},
        }
    }

    payload = nilm_workspace_payload([coordinator], circuit_id="mains")
    virtual = payload["virtual_appliances"][0]
    assert virtual["model_status"] == "conflict"
    assert virtual["is_running"] is None
    assert virtual["estimated_power_w"] is None
    assert virtual["helper_status"] == "degraded"
    assert payload["reconciliation"] == {
        "residual_w": 42.0,
        "residual_energy_kwh": 0.25,
        "tolerance_w": 30.0,
        "state": "conflict",
        "review_action": {"type": "model_conflict", "reason": "over_allocation"},
    }

    coordinator.store_data.nilm_appliance_assignments_by_circuit["mains"][0][
        "lifecycle_state"
    ] = "conflict"
    coordinator.state.nilm_reconciliation_by_circuit["mains"].update(
        consistent=True, conflict=None
    )
    assert (
        nilm_workspace_payload([coordinator], circuit_id="mains")["virtual_appliances"][
            0
        ]["model_status"]
        == "conflict"
    )

    coordinator.store_data.nilm_appliance_assignments_by_circuit["mains"].append(
        {
            "assignment_id": "dryer",
            "display_name": "Dryer",
            "mains_circuit_id": "mains",
            "lifecycle_state": "published",
        }
    )
    coordinator.state.nilm_component_runtime_by_circuit["mains"] = {
        "washer": "bad",
        "dryer": {
            "status": "on",
            "consistent": True,
            "estimated_power_w": 700.0,
            "session_start": "2026-08-02T12:00:00+00:00",
        },
    }
    virtuals = {
        item["assignment_id"]: item
        for item in nilm_workspace_payload([coordinator], circuit_id="mains")[
            "virtual_appliances"
        ]
    }
    assert virtuals["washer"]["is_running"] is None
    assert virtuals["dryer"]["is_running"] is True


def test_nilm_reference_state_overrides_running_without_replacing_estimated_power() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    source = CircuitConfig(
        circuit_id="mixed",
        name="Mixed",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=source)
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mixed": [
            {
                "assignment_id": "pump",
                "display_name": "Pump",
                "mains_circuit_id": "mixed",
                "lifecycle_state": "published",
                "reference_state_entity_id": "switch.pump",
                "reference_power_entity_id": "sensor.pump_power",
            }
        ]
    }
    coordinator.state.nilm_component_runtime_by_circuit = {
        "mixed": {
            "pump": {
                "status": "on",
                "consistent": True,
                "estimated_power_w": 319,
                "session_start": "2026-08-04T12:00:00+00:00",
            }
        }
    }
    coordinator.state.nilm_reconciliation_by_circuit = {
        "mixed": {"consistent": True, "conflict": None}
    }
    rows = {
        "switch.pump": SimpleNamespace(
            entity_id="switch.pump", state="off", attributes={}
        ),
        "sensor.pump_power": SimpleNamespace(
            entity_id="sensor.pump_power",
            state="0.084",
            attributes={"device_class": "power", "unit_of_measurement": "kW"},
        ),
    }
    coordinator.hass = SimpleNamespace(
        states=SimpleNamespace(get=rows.get, async_all=lambda: list(rows.values())),
        entity_registry=SimpleNamespace(entities={}),
    )

    payload = nilm_workspace_payload([coordinator], circuit_id="mixed")

    assert payload["virtual_appliances"][0]["is_running"] is False
    assert payload["virtual_appliances"][0]["estimated_power_w"] == 319.0
    assert payload["assignments"][0]["reference"]["measured_power_w"] == 84.0
    assert payload["assignments"][0]["reference"]["fallback_to_nilm"] is False


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
        "measured_power_w": None,
        "estimated_power_w": 817.5,
        "power_error_w": None,
        "measured_energy_kwh": None,
        "estimated_energy_kwh": 0.341,
        "energy_error_kwh": None,
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
        "measured_power_w": None,
        "estimated_power_w": None,
        "power_error_w": None,
        "measured_energy_kwh": None,
        "estimated_energy_kwh": None,
        "energy_error_kwh": None,
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
        "measured_power_w": None,
        "estimated_power_w": None,
        "power_error_w": None,
        "measured_energy_kwh": None,
        "estimated_energy_kwh": None,
        "energy_error_kwh": None,
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
    assert appliances["assignment-dishwasher"]["is_running"] is None
    assert appliances["assignment-dishwasher"]["estimated_power_w"] is None
    assert appliances["assignment-dryer"]["is_running"] is None
    assert appliances["assignment-dryer"]["estimated_power_w"] is None


def test_nilm_workspace_pairs_overlapping_signatures_exclusively() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm import NilmEdge
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        _nilm_workspace_sessions,
    )

    start = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    sessions = _nilm_workspace_sessions(
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
        "mains",
        signatures=[
            {"signature_id": "120-w", "typical_watts": 120.0},
            {"signature_id": "187-w", "typical_watts": 187.0},
        ],
        assignments=[],
    )

    assert len(sessions) == 1
    assert sessions[0]["signature_fingerprint"] == "120-w"


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
    assert "actions" not in sessions["session-confirmed"]
    assert "actions" not in sessions["session-merged"]
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
                "session_ids": ["session-dishwasher", "session-rejected"],
                "rejected_session_ids": ["session-rejected"],
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
            },
            {
                "session_id": "session-rejected",
                "mains_circuit_id": "mains",
                "signature_fingerprint": "signature_1",
                "start": "2026-06-06T09:00:00+00:00",
                "end": "2026-06-06T09:45:00+00:00",
                "duration_seconds": 2700.0,
                "median_power_w": 3200.0,
                "estimated_energy_kwh": 2.4,
                "confidence": 0.9,
            },
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
            for index in range(2260)
        ]
    }

    bounded = _bounded_history_rows(rows)

    assert len(bounded) == 1
    assert len(bounded[0]) == 2160
    assert bounded[0][0]["entity_id"] == "sensor.mains_power"
    assert bounded[0][-1]["state"] == "2259"


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
        "icon": "mdi:bell-pause-outline",
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
    coordinator.data = SimpleNamespace(
        data_quality_checklist_by_circuit={
            "hvac": {
                "sample_observed": True,
                "required_sensors_present": True,
                "numeric_states_valid": True,
                "source_data_fresh": True,
            }
        }
    )

    payload = setup_health_payload([coordinator])

    assert payload["status"] == "ok"
    assert payload["state"] == "Configure breaker amps"
    assert payload["next_step"] == "Configure breaker amps for HVAC"
    assert payload["checklist"][0] == {
        "item_id": "source_data_found",
        "status": "ok",
        "title": "Source data is available and healthy",
        "why_it_matters": (
            "Confirms Home Assistant is receiving live readings for each circuit."
        ),
    }
    assert payload["checklist_total_count"] == 10
    assert payload["open_path"].startswith("/config/integrations/")


def test_setup_health_payload_surfaces_nilm_review_without_safety_severity() -> None:
    from custom_components.circuitsetup_energy_analyzer.const import (
        CONF_ENABLE_EXPERIMENTAL_NILM,
    )
    from custom_components.circuitsetup_energy_analyzer.panel import (
        setup_health_payload,
    )

    config = CircuitConfig(
        circuit_id="mixed",
        name="Mixed Loads",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=config)
    coordinator.entry_id = "entry-1"
    coordinator.options = {CONF_ENABLE_EXPERIMENTAL_NILM: True}
    coordinator.data = SimpleNamespace()
    coordinator.store_data.nilm_signatures = {"mixed": [{"signature_id": "sig-1"}]}
    coordinator.state.nilm_reconciliation_by_circuit = {
        "mixed": {"status": "conflict", "conflict_reason": "over_allocation"}
    }

    payload = setup_health_payload([coordinator])
    nilm_issues = [
        item for item in payload["issues"] if item["issue"].startswith("nilm_")
    ]

    assert {item["issue"] for item in nilm_issues} == {
        "nilm_model_conflict",
        "nilm_unreviewed_signatures",
    }
    assert all(item["severity"] == "review" for item in nilm_issues)
    assert all("entry_id=entry-1" in item["open_path"] for item in nilm_issues)
    assert all("circuit_id=mixed" in item["open_path"] for item in nilm_issues)

    coordinator.store_data.nilm_signatures = {
        "mixed": [{"signature_id": "sig-1", "assignment_id": "pump"}]
    }
    coordinator.state.nilm_reconciliation_by_circuit = {
        "mixed": {"status": "consistent"}
    }
    coordinator.store_data.nilm_appliance_assignments_by_circuit = {"mixed": []}

    healthy = setup_health_payload([coordinator])
    assert not [item for item in healthy["issues"] if item["issue"].startswith("nilm_")]

    coordinator.store_data.nilm_appliance_assignments_by_circuit = {
        "mixed": [{"helper_links": [{"status": "degraded"}]}]
    }

    reviewed = setup_health_payload([coordinator])
    reviewed_nilm = [
        item for item in reviewed["issues"] if item["issue"].startswith("nilm_")
    ]

    assert [item["issue"] for item in reviewed_nilm] == ["nilm_helper_degraded"]
    assert reviewed_nilm[0]["severity"] == "review"
    assert "safety" not in str(reviewed_nilm[0]).lower()


def test_nilm_sensitivity_uses_latest_three_ordered_observations() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        _nilm_sensitivity_recommendation,
    )

    intervals = [
        {
            "assignment_id": "pump",
            "label": "Pump",
            "start": start,
            "observed_transition_w": watts,
        }
        for start, watts in (
            ("2026-08-02T12:00:00+00:00", 82.0),
            ("2026-08-02T11:00:00+00:00", 80.0),
            ("2026-08-02T10:00:00+00:00", 78.0),
            ("2026-08-02T09:00:00+00:00", 140.0),
        )
    ]

    assert _nilm_sensitivity_recommendation("balanced", 100.0, intervals) == (
        "sensitive"
    )


def test_nilm_session_labels_keep_explicit_legacy_assignment_name() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        _add_nilm_session_display_labels,
        _nilm_session_display_labels,
    )

    session_id = "hvac_2_direction_off_watts_0_100_var_0_100"
    labels = _nilm_session_display_labels(
        [],
        [
            {
                "assignment_id": "assignment-pump",
                "display_name": "Condensate Pump 2",
                "signature_fingerprints": ["direction=off|watts=0-100|var=0-100"],
                "session_ids": [session_id],
            }
        ],
    )

    assert _add_nilm_session_display_labels(
        [{"session_id": session_id}], labels
    ) == [
        {"session_id": session_id, "display_label": "Condensate Pump 2"}
    ]


def test_nilm_sensitivity_orders_observations_by_absolute_time() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        _nilm_sensitivity_recommendation,
    )

    intervals = [
        {
            "assignment_id": "pump",
            "label": "Pump",
            "start": start,
            "observed_transition_w": watts,
        }
        for start, watts in (
            ("2026-11-01T01:30:00-05:00", 82.0),
            ("2026-11-01T01:45:00-04:00", 78.0),
            ("2026-11-01T01:15:00-05:00", 80.0),
            ("2026-11-01T00:30:00-05:00", 140.0),
        )
    ]

    assert _nilm_sensitivity_recommendation("balanced", 100.0, intervals) == "sensitive"


@pytest.mark.parametrize(
    ("current", "watts"),
    [
        ("balanced", [80.0]),
        ("balanced", [80.0, 82.0]),
        ("balanced", [60.0, 80.0, 100.0]),
        ("balanced", [0.0, 0.0, 0.0]),
        ("sensitive", [80.0, 82.0, 84.0]),
    ],
)
def test_nilm_sensitivity_does_not_recommend_insufficient_or_noisy_evidence(
    current: str, watts: list[float]
) -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        _nilm_sensitivity_recommendation,
    )

    intervals = [
        {
            "assignment_id": "pump",
            "label": "Pump",
            "start": f"2026-08-02T{index + 10:02d}:00:00+00:00",
            "observed_transition_w": value,
        }
        for index, value in enumerate(watts)
    ]

    assert _nilm_sensitivity_recommendation(current, 100.0, intervals) is None


def test_setup_health_payload_links_actions_to_supported_integration_page() -> None:
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
    integration_path = "/config/integrations/integration/circuitsetup_energy_analyzer"
    assert capacity_issue["open_path"] == integration_path

    checklist = {item["item_id"]: item for item in payload["checklist"]}
    assert checklist["entity_detail_level_selected"]["open_path"] == integration_path
    assert checklist["dashboard_created"]["open_path"] == integration_path


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
    coordinator.current_time = lambda: datetime(2026, 7, 23, 12, tzinfo=UTC)
    coordinator.store_data.energy_usage_by_circuit = {
        "hvac": {
            "days": [
                {
                    "date": "2026-07-22",
                    "usage_kwh": 8.5,
                    "complete": True,
                }
            ]
        }
    }
    coordinator.store_data.cost_by_circuit = {
        "hvac": {
            "days": [
                {
                    "date": "2026-07-22",
                    "cost": 1.7,
                    "complete": True,
                }
            ]
        }
    }
    coordinator.state.cost_today_by_circuit = {"hvac": 1.2}
    coordinator.state.cost_today_status_by_circuit = {"hvac": "actual"}
    coordinator.state.estimated_cost_today_by_circuit = {"hvac": 1.1}
    coordinator.state.average_cost_per_day_by_circuit = {"hvac": 1.5}
    coordinator.state.average_kwh_per_day_by_circuit = {"hvac": 7.5}

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
    assert item["cost_today"] == 1.2
    assert item["cost_today_status"] == "recorded"
    assert item["average_cost_per_day"] == 1.5
    assert item["average_kwh_per_day"] == 7.5
    assert item["daily_totals"] == [
        {
            "date": "2026-07-22",
            "energy_kwh": 8.5,
            "cost": 1.7,
            "cost_source": "recorded",
        }
    ]


def test_appliance_insights_payload_retains_all_available_daily_totals() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_insights_payload,
    )

    coordinator = _coordinator(config=_config("hvac"))
    coordinator.entry_id = "entry-hvac"
    coordinator.current_time = lambda: datetime(2026, 7, 23, 12, tzinfo=UTC)
    coordinator.store_data.energy_usage_by_circuit = {
        "hvac": {
            "days": [
                {
                    "date": (date(2026, 7, 22) - timedelta(days=day)).isoformat(),
                    "usage_kwh": 1.0,
                    "complete": True,
                }
                for day in range(61)
            ]
        }
    }

    (item,) = appliance_insights_payload([coordinator])["items"]

    assert len(item["daily_totals"]) == 61
    assert item["daily_totals"][0]["date"] == "2026-05-23"
    assert item["daily_totals"][-1]["date"] == "2026-07-22"


def test_appliance_insights_payload_exposes_primary_mains_daily_totals() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        appliance_insights_payload,
    )

    mains = CircuitConfig(
        circuit_id="mains",
        name="Whole home",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
    )
    hvac = _config("hvac")
    coordinator = _coordinator(config=mains, configs=(mains, hvac))
    coordinator.entry_id = "entry-home"
    coordinator.current_time = lambda: datetime(2026, 7, 23, 12, tzinfo=UTC)
    coordinator.store_data.energy_usage_by_circuit = {
        "mains": {
            "days": [
                {
                    "date": "2026-07-22",
                    "usage_kwh": 24.0,
                    "complete": True,
                }
            ]
        },
        "hvac": {
            "days": [
                {
                    "date": "2026-07-22",
                    "usage_kwh": 8.5,
                    "complete": True,
                }
            ]
        },
    }
    coordinator.store_data.cost_by_circuit = {
        "mains": {
            "days": [
                {
                    "date": "2026-07-22",
                    "cost": 4.8,
                    "complete": True,
                }
            ]
        }
    }

    payload = appliance_insights_payload([coordinator])

    assert payload["whole_house"] == [
        {
            "entry_id": "entry-home",
            "circuit_id": "mains",
            "display_name": "Whole home",
            "daily_totals": [
                {
                    "date": "2026-07-22",
                    "energy_kwh": 24.0,
                    "cost": 4.8,
                    "cost_source": "recorded",
                }
            ],
        }
    ]


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
        HVAC_ASSOCIATIONS_API_PATH,
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
        HVAC_ASSOCIATIONS_API_PATH,
        APPLIANCE_DETAIL_API_PATH,
        APPLIANCE_INSIGHTS_API_PATH,
        SETUP_HEALTH_API_PATH,
        NILM_WORKSPACE_API_PATH,
        NILM_WORKSPACE_HISTORY_API_PATH,
    ]
    assert {view.name for view in http.views} >= {
        "api:circuitsetup_energy_analyzer:hvac_associations"
    }
    assert HVAC_ASSOCIATIONS_API_PATH == (
        "/api/circuitsetup_energy_analyzer/hvac_associations"
    )
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
    from custom_components.circuitsetup_energy_analyzer.panel_contracts import (
        PANEL_MODULE_NAME,
        PANEL_MODULE_VERSION,
        STATIC_URL_PATH,
    )

    resource_url = f"{STATIC_URL_PATH}/{PANEL_MODULE_NAME}?v={PANEL_MODULE_VERSION}"
    resource_items = [
        {
            "id": "dashboard-graph-module",
            "type": "module",
            "url": f"{STATIC_URL_PATH}/{PANEL_MODULE_NAME}?v=old",
        }
    ]
    resource_updates: list[tuple[str, dict[str, str]]] = []

    async def async_update_item(item_id: str, data: dict[str, str]) -> None:
        resource_updates.append((item_id, data))
        resource_items[0] = {
            "id": item_id,
            "type": data["res_type"],
            "url": data["url"],
        }

    resources = SimpleNamespace(
        loaded=True,
        async_items=lambda: list(resource_items),
        async_update_item=async_update_item,
    )

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
        data={"lovelace": {"resources": resources}},
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
    assert len(http.views) == 7
    assert resource_updates == [
        (
            "dashboard-graph-module",
            {"res_type": "module", "url": resource_url},
        )
    ]

    hass.data[DOMAIN][DATA_RELOAD_COUNT] = 1
    assert await async_unload_entry(hass, entry) is True
    assert frontend.removed == [PANEL_URL_PATH]
    assert "_services_setup" in hass.data[DOMAIN]

    hass.data[DOMAIN].pop(DATA_RELOAD_COUNT)
    assert await async_setup_entry(hass, entry) is True
    assert len(panel_custom.panels) == 1
    assert len(resource_updates) == 1
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


@pytest.mark.parametrize("unit", ("var", "VA", "A"))
def test_nilm_workspace_history_rejects_non_watts_metadata(unit: str) -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        _nilm_workspace_history_payload,
    )

    config = CircuitConfig(
        circuit_id="mixed",
        name="Mixed",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(
            SensorRef(
                "sensor.mixed_bad_power",
                SensorRole.REAL_POWER,
                unit=unit,
            ),
        ),
    )

    history = _nilm_workspace_history_payload(config, [], [], hours=6)

    assert history["entities"] == []
    assert history["entity_series"] == []
    assert history["missing_real_power_reason"] == (
        "Configure a real-power sensor measured in W, kW, mW, or MW."
    )


@pytest.mark.parametrize("unit", ("W", "kW", "mW", "MW"))
def test_nilm_workspace_history_preserves_real_power_unit(unit: str) -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        _nilm_workspace_history_payload,
    )

    config = CircuitConfig(
        circuit_id="mixed",
        name="Mixed",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_power", SensorRole.REAL_POWER, unit=unit),),
    )

    history = _nilm_workspace_history_payload(config, [], [], hours=6)

    assert history["entity_series"] == [
        {
            "entity_id": "sensor.mixed_power",
            "effective_role": "real_power",
            "source_unit": unit,
        }
    ]


def test_nilm_workspace_history_includes_both_mains_real_power_legs() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        _nilm_workspace_history_payload,
    )

    config = CircuitConfig(
        circuit_id="mains",
        name="Mains NILM",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=(
            SensorRef(
                "sensor.mains_l1_watts", SensorRole.REAL_POWER, leg="a", unit="W"
            ),
            SensorRef(
                "sensor.mains_l2_watts", SensorRole.REAL_POWER, leg="b", unit="W"
            ),
        ),
    )

    history = _nilm_workspace_history_payload(config, [], [], hours=6)

    assert history["entities"] == [
        "sensor.mains_l1_watts",
        "sensor.mains_l2_watts",
    ]
    assert history["source_entities"] == [
        "sensor.mains_l1_watts",
        "sensor.mains_l2_watts",
    ]


@pytest.mark.asyncio
async def test_nilm_workspace_history_rows_include_role_and_unit_metadata(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import panel

    config = CircuitConfig(
        circuit_id="mixed",
        name="Mixed",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_power", SensorRole.REAL_POWER, unit="kW"),),
    )
    coordinator = _coordinator(config=config, configs=(config,))
    coordinator.entry_id = "entry-1"

    async def history_rows(_hass, _start, _end, _entity_ids):
        return [
            [
                {
                    "entity_id": "sensor.mixed_power",
                    "state": "1.2",
                    "last_changed": "2026-08-03T12:00:00+00:00",
                }
            ]
        ]

    monkeypatch.setattr(panel, "_async_history_rows", history_rows)

    rows = await panel.nilm_workspace_history_payload(
        SimpleNamespace(),
        [coordinator],
        circuit_id="mixed",
        entry_id="entry-1",
    )

    assert rows[0][0]["effective_role"] == "real_power"
    assert rows[0][0]["source_unit"] == "kW"


@pytest.mark.asyncio
async def test_nilm_workspace_history_uses_live_real_power_unit(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import panel

    config = CircuitConfig(
        circuit_id="mixed",
        name="Mixed",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=config, configs=(config,))
    coordinator.entry_id = "entry-1"
    hass = SimpleNamespace(
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                attributes={
                    "device_class": "power",
                    "unit_of_measurement": "kW",
                }
            )
        )
    )

    async def history_rows(_hass, _start, _end, _entity_ids):
        return [
            [
                {
                    "entity_id": "sensor.mixed_power",
                    "state": "1.2",
                    "last_changed": "2026-08-03T12:00:00+00:00",
                }
            ]
        ]

    monkeypatch.setattr(panel, "_async_history_rows", history_rows)

    rows = await panel.nilm_workspace_history_payload(
        hass,
        [coordinator],
        circuit_id="mixed",
        entry_id="entry-1",
    )

    assert rows[0][0]["source_unit"] == "kW"


@pytest.mark.asyncio
async def test_nilm_workspace_history_rejects_live_reactive_metadata(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import panel

    config = CircuitConfig(
        circuit_id="mixed",
        name="Mixed",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(SensorRef("sensor.mixed_power", SensorRole.REAL_POWER),),
    )
    coordinator = _coordinator(config=config, configs=(config,))
    coordinator.entry_id = "entry-1"
    hass = SimpleNamespace(
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                attributes={
                    "device_class": "reactive_power",
                    "unit_of_measurement": "var",
                }
            )
        )
    )

    async def history_rows(_hass, _start, _end, _entity_ids):
        return [
            [
                {
                    "entity_id": "sensor.mixed_power",
                    "state": "12",
                    "last_changed": "2026-08-03T12:00:00+00:00",
                }
            ]
        ]

    monkeypatch.setattr(panel, "_async_history_rows", history_rows)

    rows = await panel.nilm_workspace_history_payload(
        hass,
        [coordinator],
        circuit_id="mixed",
        entry_id="entry-1",
    )

    assert rows == []


@pytest.mark.asyncio
async def test_nilm_workspace_history_falls_through_to_live_watts(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import panel
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        nilm_workspace_payload,
    )

    config = CircuitConfig(
        circuit_id="mixed",
        name="Mixed",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(
            SensorRef("sensor.mixed_var", SensorRole.REAL_POWER),
            SensorRef("sensor.mixed_watts", SensorRole.REAL_POWER),
        ),
    )
    coordinator = _coordinator(config=config, configs=(config,))
    coordinator.entry_id = "entry-1"
    metadata = {
        "sensor.mixed_var": {
            "device_class": "reactive_power",
            "unit_of_measurement": "var",
        },
        "sensor.mixed_watts": {
            "device_class": "power",
            "unit_of_measurement": "W",
        },
    }
    hass = SimpleNamespace(
        states=SimpleNamespace(
            get=lambda entity_id: SimpleNamespace(attributes=metadata[entity_id])
        )
    )
    coordinator.hass = hass
    requested_entity_ids = []

    async def history_rows(_hass, _start, _end, entity_ids):
        requested_entity_ids.extend(entity_ids)
        return [
            [
                {
                    "entity_id": "sensor.mixed_watts",
                    "state": "420",
                    "last_changed": "2026-08-03T12:00:00+00:00",
                }
            ]
        ]

    monkeypatch.setattr(panel, "_async_history_rows", history_rows)

    payload = nilm_workspace_payload(
        [coordinator], circuit_id="mixed", entry_id="entry-1"
    )
    assert payload["history"]["entity_series"] == [
        {
            "entity_id": "sensor.mixed_watts",
            "effective_role": "real_power",
            "source_unit": "W",
        }
    ]

    rows = await panel.nilm_workspace_history_payload(
        hass,
        [coordinator],
        circuit_id="mixed",
        entry_id="entry-1",
    )

    assert requested_entity_ids == ["sensor.mixed_watts"]
    assert rows[0][0]["effective_role"] == "real_power"
    assert rows[0][0]["source_unit"] == "W"
