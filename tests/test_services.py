from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace

import pytest
import voluptuous as vol

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_SOURCE_ENTITIES,
    DOMAIN,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    ApplianceProfile,
    BaselineStats,
    CircuitConfig,
    CircuitMode,
    EventType,
    SensorRef,
    SensorRole,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData


def test_notification_id_for_alert_uses_feature_or_event_type() -> None:
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        notification_id_for_alert,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Cycle duration changed",
        feature="cycle_duration_s",
    )
    event_alert = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 5, tzinfo=UTC),
        circuit_id="mains",
        severity=Severity.WARNING,
        message="Voltage sag",
        event_type=EventType.VOLTAGE_SAG,
    )

    assert notification_id_for_alert(alert).startswith(
        f"{DOMAIN}_alert_fridge_cycle_duration_s_"
    )
    assert notification_id_for_alert(alert) == notification_id_for_alert(alert)
    assert notification_id_for_alert(event_alert).startswith(
        f"{DOMAIN}_alert_mains_voltage_sag_"
    )


def test_notification_id_for_alert_does_not_collide_on_underscores() -> None:
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        notification_id_for_alert,
    )

    first = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="a_b",
        severity=Severity.WARNING,
        message="First tuple",
        feature="c",
    )
    second = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="a",
        severity=Severity.WARNING,
        message="Second tuple",
        feature="b_c",
    )

    assert notification_id_for_alert(first) != notification_id_for_alert(second)


def test_notification_id_for_alert_uses_nilm_notification_key() -> None:
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        notification_id_for_alert,
    )

    first = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="mains",
        severity=Severity.INFO,
        message="Dishwasher appears finished.",
        feature="nilm_appliance_finished",
        features={
            "source": "nilm",
            "assignment_id": "assignment-dishwasher",
            "notification_key": "assignment-dishwasher:session-1",
        },
    )
    second = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 13, 0, tzinfo=UTC),
        circuit_id="mains",
        severity=Severity.INFO,
        message="Dishwasher appears finished.",
        feature="nilm_appliance_finished",
        features={
            "source": "nilm",
            "assignment_id": "assignment-dishwasher",
            "notification_key": "assignment-dishwasher:session-2",
        },
    )

    assert notification_id_for_alert(first) != notification_id_for_alert(second)


def test_alert_notification_message_includes_evidence_link_and_graph_entities() -> None:
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        alert_notification_message,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
        circuit_id="hvac",
        severity=Severity.WARNING,
        message="Possible issue: HVAC leg imbalance",
        feature="leg_imbalance",
        observed_value=62.0,
        baseline_value=20.0,
        change_ratio=2.1,
        repeated_count=3,
    )
    config = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(
            SensorRef("sensor.hvac_l1_watts", SensorRole.REAL_POWER, leg="a"),
            SensorRef("sensor.hvac_l2_watts", SensorRole.REAL_POWER, leg="b"),
            SensorRef("sensor.hvac_l1_current", SensorRole.CURRENT, leg="a"),
            SensorRef("sensor.hvac_l2_current", SensorRole.CURRENT, leg="b"),
        ),
    )

    message = alert_notification_message(alert, config=config)

    assert "Possible issue: HVAC leg imbalance" in message
    assert message.startswith("**HVAC**\n\nPossible issue: HVAC leg imbalance")
    assert "## HVAC" not in message
    assert (
        "[Open evidence graph](/circuitsetup-energy-analyzer-evidence?"
        in message
    )
    assert "Observed value: 62.0" in message
    assert "Baseline value: 20.0" in message
    assert "Graph entities" not in message
    assert "sensor.hvac_l1_watts" not in message
    assert "sensor.hvac_l2_current" not in message


@pytest.mark.asyncio
async def test_alert_notification_uses_short_title_and_bold_appliance_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import notifications

    calls: list[dict[str, object]] = []

    def fake_create(hass, message, *, title, notification_id):
        calls.append(
            {
                "hass": hass,
                "message": message,
                "title": title,
                "notification_id": notification_id,
            }
        )

    homeassistant = ModuleType("homeassistant")
    components = ModuleType("homeassistant.components")
    persistent_notification = ModuleType(
        "homeassistant.components.persistent_notification",
    )
    persistent_notification.async_create = fake_create
    components.persistent_notification = persistent_notification
    homeassistant.components = components
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant)
    monkeypatch.setitem(sys.modules, "homeassistant.components", components)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        persistent_notification,
    )
    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
        circuit_id="water_heater",
        severity=Severity.WARNING,
        message="Possible issue: Water Heater demand was high",
        feature="demand_monthly_peak",
        observed_value=4100.0,
        baseline_value=4100.0,
    )
    config = CircuitConfig(
        circuit_id="water_heater",
        name="Water Heater",
        appliance_profile=ApplianceProfile.WATER_HEATER,
        mode=CircuitMode.SINGLE_PHASE,
    )

    await notifications.async_create_alert_notification(
        SimpleNamespace(),
        alert,
        config=config,
    )

    assert calls
    assert calls[0]["title"] == "Energy Analyzer Alert"
    message = str(calls[0]["message"])
    assert message.startswith(
        "**Water Heater**\n\nPossible issue: Water Heater demand was high"
    )
    assert "Baseline value" not in message
    assert "Comparison value: 4100.0" in message


def test_alert_notification_message_keeps_safety_notice_near_capacity_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        alert_notification_message,
    )
    from custom_components.circuitsetup_energy_analyzer.safety import (
        ELECTRICAL_SAFETY_NOTICE,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
        circuit_id="car_charger",
        severity=Severity.WARNING,
        message="Possible issue: car charger capacity usage is high",
        feature="capacity_usage",
        observed_value=85.0,
        baseline_value=80.0,
    )

    message = alert_notification_message(alert)

    assert ELECTRICAL_SAFETY_NOTICE in message


def test_repair_issue_id_for_circuit_problem_is_stable() -> None:
    from custom_components.circuitsetup_energy_analyzer.repairs import (
        issue_id_for_circuit_problem,
    )

    issue_id = issue_id_for_circuit_problem("mains", "missing_source_entities")
    assert issue_id.startswith(f"{DOMAIN}_mains_missing_source_entities_")
    assert issue_id == issue_id_for_circuit_problem(
        "mains", "missing_source_entities"
    )


def test_repair_issue_id_does_not_collide_on_underscores() -> None:
    from custom_components.circuitsetup_energy_analyzer.repairs import (
        issue_id_for_circuit_problem,
    )

    assert issue_id_for_circuit_problem("a_b", "c") != issue_id_for_circuit_problem(
        "a", "b_c"
    )


def test_repair_issue_severity_normalizes_unsupported_values_to_warning() -> None:
    from custom_components.circuitsetup_energy_analyzer.repairs import (
        _ha_issue_severity,
    )

    class FakeIssueSeverity:
        WARNING = "warning"
        ERROR = "error"

    fake_issue_registry = SimpleNamespace(IssueSeverity=FakeIssueSeverity)

    assert _ha_issue_severity(fake_issue_registry, Severity.WARNING) == "warning"
    assert _ha_issue_severity(fake_issue_registry, Severity.ERROR) == "error"
    assert _ha_issue_severity(fake_issue_registry, Severity.INFO) == "warning"
    assert _ha_issue_severity(fake_issue_registry, "surprising") == "warning"


@pytest.mark.asyncio
async def test_repair_issue_includes_actionable_guidance(monkeypatch) -> None:
    from custom_components.circuitsetup_energy_analyzer import repairs

    calls = []
    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    issue_registry_module = ModuleType("homeassistant.helpers.issue_registry")

    class FakeIssueSeverity:
        WARNING = "warning"
        ERROR = "error"

    def fake_create_issue(*args, **kwargs):
        calls.append((args, kwargs))

    issue_registry_module.IssueSeverity = FakeIssueSeverity
    issue_registry_module.async_create_issue = fake_create_issue
    helpers_module.issue_registry = issue_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.issue_registry",
        issue_registry_module,
    )

    await repairs.async_create_circuit_issue(
        SimpleNamespace(),
        "fridge",
        "missing_energy_source",
        source_entities=("sensor.fridge_power", "sensor.fridge_power"),
        data={
            "circuit_name": "Refrigerator",
            "reason": "Daily Energy Usage needs a cumulative energy source.",
            "recommended_action": "Add a cumulative kWh sensor to Refrigerator",
        },
    )

    _, kwargs = calls[0]
    assert kwargs["data"] == {
        "circuit_id": "fridge",
        "circuit_name": "Refrigerator",
        "problem": "missing_energy_source",
        "fix": "Add a cumulative kWh source for this circuit.",
        "open_path": "/config/integrations/integration/circuitsetup_energy_analyzer",
        "reason": "Daily Energy Usage needs a cumulative energy source.",
        "recommended_action": "Add a cumulative kWh sensor to Refrigerator",
        "source_entities": ["sensor.fridge_power"],
    }
    assert kwargs["translation_placeholders"] == {
        "circuit_id": "fridge",
        "circuit_name": "Refrigerator",
        "fix": "Add a cumulative kWh source for this circuit.",
        "open_path": "/config/integrations/integration/circuitsetup_energy_analyzer",
        "reason": "Daily Energy Usage needs a cumulative energy source.",
        "recommended_action": "Add a cumulative kWh sensor to Refrigerator",
        "source_entities": "sensor.fridge_power",
    }


@pytest.mark.asyncio
async def test_compact_entity_model_repair_is_single_integration_issue(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import repairs

    calls = []
    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    issue_registry_module = ModuleType("homeassistant.helpers.issue_registry")

    class FakeIssueSeverity:
        WARNING = "warning"
        ERROR = "error"

    def fake_create_issue(*args, **kwargs):
        calls.append((args, kwargs))

    issue_registry_module.IssueSeverity = FakeIssueSeverity
    issue_registry_module.async_create_issue = fake_create_issue
    helpers_module.issue_registry = issue_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers_module)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.issue_registry",
        issue_registry_module,
    )

    await repairs.async_create_compact_entity_model_issue(
        SimpleNamespace(),
        "entry-1",
        legacy_count=3,
    )

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[:3] == (
        SimpleNamespace(),
        DOMAIN,
        "compact_entity_model_available_entry-1",
    )
    assert kwargs["translation_key"] == "compact_entity_model_available"
    assert kwargs["is_fixable"] is False
    assert kwargs["is_persistent"] is True
    assert kwargs["data"]["legacy_count"] == 3
    assert "Migrate To Compact Entity Model" in kwargs["data"]["recommended_action"]


def test_nilm_label_schema_validates_required_fields() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        NILM_LABEL_SERVICE_SCHEMA,
    )

    data = NILM_LABEL_SERVICE_SCHEMA(
        {
            "circuit_id": "mains",
            "signature_id": "signature_1",
            "label": "Microwave",
        }
    )

    assert data == {
        "circuit_id": "mains",
        "signature_id": "signature_1",
        "label": "Microwave",
    }


def test_nilm_label_schema_raises_for_missing_required_field() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        NILM_LABEL_SERVICE_SCHEMA,
    )

    with pytest.raises(vol.Invalid):
        NILM_LABEL_SERVICE_SCHEMA(
            {
                "circuit_id": "mains",
                "signature_id": "signature_1",
            }
        )


def test_nilm_label_interval_schema_validates_manual_interval_fields() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        NILM_LABEL_INTERVAL_SERVICE_SCHEMA,
    )

    data = NILM_LABEL_INTERVAL_SERVICE_SCHEMA(
        {
            "circuit_id": "mains",
            "interval_id": "label-1",
            "label": "Dishwasher",
            "start": "2026-06-02T12:00:00+00:00",
            "end": "2026-06-02T12:45:00+00:00",
            "appliance_id": "dishwasher",
            "mains_entity_id": "sensor.mains_power",
            "ground_truth_entity_id": "sensor.dishwasher_power",
        }
    )

    assert data["interval_id"] == "label-1"
    assert data["label"] == "Dishwasher"
    assert data["appliance_id"] == "dishwasher"


def test_nilm_label_interval_schema_raises_for_missing_required_field() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        NILM_LABEL_INTERVAL_SERVICE_SCHEMA,
    )

    with pytest.raises(vol.Invalid):
        NILM_LABEL_INTERVAL_SERVICE_SCHEMA(
            {
                "circuit_id": "mains",
                "label": "Dishwasher",
                "start": "2026-06-02T12:00:00+00:00",
            }
        )


def test_nilm_assignment_service_schemas_validate_required_fields() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        NILM_ASSIGN_INTERVAL_SERVICE_SCHEMA,
        NILM_ASSIGN_SESSION_SERVICE_SCHEMA,
        NILM_ASSIGN_SIGNATURE_SERVICE_SCHEMA,
    )

    assert NILM_ASSIGN_SIGNATURE_SERVICE_SCHEMA(
        {
            "circuit_id": "mains",
            "signature_id": "signature_1",
            "label": "Dishwasher",
            "appliance_id": "dishwasher",
        }
    )["label"] == "Dishwasher"
    assert NILM_ASSIGN_SESSION_SERVICE_SCHEMA(
        {
            "circuit_id": "mains",
            "session_id": "session_1",
            "signature_fingerprint": "fingerprint_1",
            "label": "Dishwasher",
        }
    )["session_id"] == "session_1"
    assert NILM_ASSIGN_INTERVAL_SERVICE_SCHEMA(
        {
            "circuit_id": "mains",
            "interval_id": "label-1",
            "label": "Dishwasher",
        }
    )["interval_id"] == "label-1"

    with pytest.raises(vol.Invalid):
        NILM_ASSIGN_SIGNATURE_SERVICE_SCHEMA(
            {"circuit_id": "mains", "label": "Dishwasher"}
        )


def test_user_experience_service_schemas_validate_required_fields() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        _SERVICE_SCHEMAS,
        ALERT_FEEDBACK_SERVICE_SCHEMA,
        CAPACITY_SETTINGS_SERVICE_SCHEMA,
        MAINTENANCE_END_SERVICE_SCHEMA,
        MAINTENANCE_START_SERVICE_SCHEMA,
        NILM_ASSIGN_SIGNATURE_SERVICE_SCHEMA,
        NILM_LABEL_INTERVAL_SERVICE_SCHEMA,
        NILM_MERGE_SERVICE_SCHEMA,
        NILM_SIGNATURE_SERVICE_SCHEMA,
        SENSITIVITY_SERVICE_SCHEMA,
        SERVICE_ACKNOWLEDGE_ALERT,
        SERVICE_PAUSE_ALERTS,
        UTILITY_COMPARISON_SETTINGS_SERVICE_SCHEMA,
    )

    assert SENSITIVITY_SERVICE_SCHEMA(
        {"circuit_id": "fridge", "preset": "quiet"}
    ) == {"circuit_id": "fridge", "preset": "quiet"}
    assert MAINTENANCE_START_SERVICE_SCHEMA(
        {
            "circuit_id": "fridge",
            "note": "Changed filter",
            "duration": "02:00:00",
            "relearn_on_end": True,
        }
    ) == {
        "circuit_id": "fridge",
        "note": "Changed filter",
        "duration": "02:00:00",
        "relearn_on_end": True,
    }
    assert MAINTENANCE_END_SERVICE_SCHEMA(
        {"circuit_id": "fridge", "relearn": True}
    ) == {"circuit_id": "fridge", "relearn": True}
    assert ALERT_FEEDBACK_SERVICE_SCHEMA({"alert_id": "alert-1"}) == {
        "alert_id": "alert-1"
    }
    assert ALERT_FEEDBACK_SERVICE_SCHEMA(
        {"entity_id": "sensor.fridge_health_summary"}
    ) == {
        "entity_id": "sensor.fridge_health_summary"
    }
    assert NILM_SIGNATURE_SERVICE_SCHEMA(
        {"circuit_id": "mains", "signature_id": "signature_1"}
    ) == {"circuit_id": "mains", "signature_id": "signature_1"}
    assert NILM_MERGE_SERVICE_SCHEMA(
        {
            "circuit_id": "mains",
            "source_signature_id": "signature_2",
            "target_signature_id": "signature_1",
        }
    ) == {
        "circuit_id": "mains",
        "source_signature_id": "signature_2",
        "target_signature_id": "signature_1",
    }
    assert NILM_LABEL_INTERVAL_SERVICE_SCHEMA(
        {
            "circuit_id": "mains",
            "label": "Dishwasher",
            "start": "2026-06-02T12:00:00+00:00",
            "end": "2026-06-02T12:45:00+00:00",
        }
    ) == {
        "circuit_id": "mains",
        "label": "Dishwasher",
        "start": "2026-06-02T12:00:00+00:00",
        "end": "2026-06-02T12:45:00+00:00",
    }
    assert NILM_ASSIGN_SIGNATURE_SERVICE_SCHEMA(
        {
            "circuit_id": "mains",
            "signature_id": "signature_1",
            "label": "Dishwasher",
        }
    ) == {
        "circuit_id": "mains",
        "signature_id": "signature_1",
        "label": "Dishwasher",
    }
    assert UTILITY_COMPARISON_SETTINGS_SERVICE_SCHEMA(
        {
            "circuit_id": "mains",
            "utility_energy_entity": "sensor.opower_current_bill_usage",
            "utility_statistic_id": "opower:utility_elec_consumption",
            "utility_source_type": "auto",
            "utility_statistic_period": "day",
            "measured_energy_entities": ["sensor.panel_import_energy"],
            "tolerance_percent": 8.5,
        }
    ) == {
        "circuit_id": "mains",
        "utility_energy_entity": "sensor.opower_current_bill_usage",
        "utility_statistic_id": "opower:utility_elec_consumption",
        "utility_source_type": "auto",
        "utility_statistic_period": "day",
        "measured_energy_entities": ["sensor.panel_import_energy"],
        "tolerance_percent": 8.5,
    }
    assert CAPACITY_SETTINGS_SERVICE_SCHEMA(
        {"circuit_id": "ev", "breaker_amps": 40.0, "warning_ratio": 0.8}
    ) == {"circuit_id": "ev", "breaker_amps": 40.0, "warning_ratio": 0.8}
    assert _SERVICE_SCHEMAS[SERVICE_PAUSE_ALERTS](
        {"entity_id": "sensor.fridge_health_summary", "duration": "01:00:00"}
    ) == {
        "entity_id": "sensor.fridge_health_summary",
        "duration": "01:00:00",
    }
    assert _SERVICE_SCHEMAS[SERVICE_ACKNOWLEDGE_ALERT](
        {"entity_id": "sensor.fridge_health_summary"}
    ) == {
        "entity_id": "sensor.fridge_health_summary",
    }

    with pytest.raises(vol.Invalid):
        SENSITIVITY_SERVICE_SCHEMA({"circuit_id": "fridge"})
    with pytest.raises(vol.Invalid):
        NILM_MERGE_SERVICE_SCHEMA(
            {"circuit_id": "mains", "source_signature_id": "signature_2"}
        )


def test_advanced_circuit_service_schemas_accept_analyzer_entity_targets() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import _SERVICE_SCHEMAS

    entity_target_services = (
        "export_diagnostics",
        "export_history_csv",
        "set_energy_usage_settings",
        "set_energy_goal_settings",
        "set_activity_alert_settings",
        "set_billing_cycle_settings",
        "set_cost_settings",
        "set_demand_settings",
        "set_capacity_settings",
        "set_leg_imbalance_settings",
        "set_metric_consistency_settings",
        "set_mains_balance_settings",
        "set_solar_flow_settings",
        "set_standby_settings",
        "set_utility_comparison_settings",
        "recalculate_setting_recommendations",
    )

    for service_name in entity_target_services:
        schema = _SERVICE_SCHEMAS[service_name]
        assert schema is not None
        assert schema({"entity_id": "sensor.fridge_health_summary"}) == {
            "entity_id": "sensor.fridge_health_summary"
        }


def test_nilm_signature_service_schemas_accept_analyzer_entity_targets() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import _SERVICE_SCHEMAS

    assert _SERVICE_SCHEMAS["label_nilm_signature"](
        {
            "entity_id": "sensor.mains_health_summary",
            "signature_id": "signature_1",
            "label": "Microwave",
        }
    ) == {
        "entity_id": "sensor.mains_health_summary",
        "signature_id": "signature_1",
        "label": "Microwave",
    }
    assert _SERVICE_SCHEMAS["ignore_nilm_signature"](
        {"entity_id": "sensor.mains_health_summary", "signature_id": "signature_1"}
    ) == {
        "entity_id": "sensor.mains_health_summary",
        "signature_id": "signature_1",
    }
    assert _SERVICE_SCHEMAS["mark_nilm_signature_expected"](
        {"entity_id": "sensor.mains_health_summary", "signature_id": "signature_1"}
    ) == {
        "entity_id": "sensor.mains_health_summary",
        "signature_id": "signature_1",
    }
    assert _SERVICE_SCHEMAS["merge_nilm_signatures"](
        {
            "entity_id": "sensor.mains_health_summary",
            "source_signature_id": "signature_2",
            "target_signature_id": "signature_1",
        }
    ) == {
        "entity_id": "sensor.mains_health_summary",
        "source_signature_id": "signature_2",
        "target_signature_id": "signature_1",
    }


def test_setting_recommendation_service_schemas_validate_fields() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        ATTR_ENTITY_ID,
        ATTR_ENTRY_ID,
        ATTR_RECOMMENDATION_ID,
        RECALCULATE_RECOMMENDATIONS_SERVICE_SCHEMA,
        RECOMMENDATION_ACTION_SERVICE_SCHEMA,
    )

    assert RECALCULATE_RECOMMENDATIONS_SERVICE_SCHEMA({}) == {}
    assert RECALCULATE_RECOMMENDATIONS_SERVICE_SCHEMA(
        {"circuit_id": "fridge"}
    ) == {"circuit_id": "fridge"}
    assert RECOMMENDATION_ACTION_SERVICE_SCHEMA(
        {ATTR_RECOMMENDATION_ID: "recommendation-1"}
    ) == {ATTR_RECOMMENDATION_ID: "recommendation-1"}
    assert RECOMMENDATION_ACTION_SERVICE_SCHEMA(
        {ATTR_RECOMMENDATION_ID: "recommendation-1", ATTR_ENTRY_ID: "entry-1"}
    ) == {ATTR_RECOMMENDATION_ID: "recommendation-1", ATTR_ENTRY_ID: "entry-1"}
    assert RECOMMENDATION_ACTION_SERVICE_SCHEMA(
        {ATTR_ENTITY_ID: "sensor.fridge_health_summary"}
    ) == {ATTR_ENTITY_ID: "sensor.fridge_health_summary"}

    with pytest.raises(vol.Invalid):
        RECOMMENDATION_ACTION_SERVICE_SCHEMA({})


@pytest.mark.asyncio
async def test_setup_and_unload_services_with_fake_hass() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_APPLY_SETTING_RECOMMENDATION,
        SERVICE_DENY_SETTING_RECOMMENDATION,
        SERVICE_DISMISS_SETTING_RECOMMENDATION,
        SERVICE_RECALCULATE_SETTING_RECOMMENDATIONS,
        SERVICE_RELEARN_BASELINE,
        async_setup_services,
        async_unload_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}
            self.removed: list[tuple[str, str]] = []

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = (handler, schema)

        def async_remove(self, domain, service) -> None:
            self.removed.append((domain, service))
            self.registered.pop((domain, service), None)

    class FakeBus:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, object]]] = []

        def async_fire(self, event_type, event_data=None) -> None:
            self.events.append((event_type, dict(event_data or {})))

    hass = SimpleNamespace(services=FakeServices(), bus=FakeBus())

    await async_setup_services(hass)
    assert (DOMAIN, SERVICE_RECALCULATE_SETTING_RECOMMENDATIONS) in (
        hass.services.registered
    )
    assert (DOMAIN, SERVICE_APPLY_SETTING_RECOMMENDATION) in hass.services.registered
    assert (DOMAIN, SERVICE_DENY_SETTING_RECOMMENDATION) in hass.services.registered
    assert (DOMAIN, SERVICE_DISMISS_SETTING_RECOMMENDATION) in (
        hass.services.registered
    )

    handler, _schema = hass.services.registered[(DOMAIN, SERVICE_RELEARN_BASELINE)]
    await handler(SimpleNamespace(data={"circuit_id": "fridge"}))

    assert hass.bus.events == [
        (f"{DOMAIN}_{SERVICE_RELEARN_BASELINE}", {"circuit_id": "fridge"})
    ]

    await async_unload_services(hass)

    assert hass.services.registered == {}
    assert (DOMAIN, SERVICE_RELEARN_BASELINE) in hass.services.removed


@pytest.mark.asyncio
async def test_setting_recommendation_services_dispatch() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_APPLY_SETTING_RECOMMENDATION,
        SERVICE_DENY_SETTING_RECOMMENDATION,
        SERVICE_DISMISS_SETTING_RECOMMENDATION,
        SERVICE_RECALCULATE_SETTING_RECOMMENDATIONS,
        SERVICE_RESET_SETTING_RECOMMENDATION,
        SERVICE_UNDO_SETTING_RECOMMENDATION,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(
            self,
            circuits: set[str],
            recommendation_ids: set[str] | None = None,
        ) -> None:
            self.circuits = circuits
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.store_data = SimpleNamespace(
                settings_recommendations={
                    recommendation_id: SimpleNamespace()
                    for recommendation_id in recommendation_ids or set()
                }
            )

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id in self.circuits

        async def async_recalculate_setting_recommendations(
            self,
            circuit_id: str | None,
        ) -> None:
            self.calls.append(
                ("async_recalculate_setting_recommendations", (circuit_id,))
            )

        async def async_apply_setting_recommendation(
            self,
            recommendation_id: str,
        ) -> None:
            self.calls.append(
                ("async_apply_setting_recommendation", (recommendation_id,))
            )

        async def async_deny_setting_recommendation(
            self,
            recommendation_id: str,
        ) -> None:
            self.calls.append(
                ("async_deny_setting_recommendation", (recommendation_id,))
            )

        async def async_dismiss_setting_recommendation(
            self,
            recommendation_id: str,
        ) -> None:
            self.calls.append(
                ("async_dismiss_setting_recommendation", (recommendation_id,))
            )

        async def async_undo_setting_recommendation(
            self,
            recommendation_id: str,
        ) -> bool:
            self.calls.append(
                ("async_undo_setting_recommendation", (recommendation_id,))
            )
            return True

        async def async_reset_setting_recommendation(
            self,
            recommendation_id: str,
        ) -> bool:
            self.calls.append(
                ("async_reset_setting_recommendation", (recommendation_id,))
            )
            return True

    fridge_coordinator = FakeCoordinator(
        {"fridge"},
        {"rec-apply", "rec-deny", "rec-dismiss", "rec-undo", "rec-reset"},
    )
    mains_coordinator = FakeCoordinator({"mains"})
    hass = SimpleNamespace(
        data={
            DOMAIN: {
                "fridge-entry": fridge_coordinator,
                "mains-entry": mains_coordinator,
            }
        },
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    await hass.services.registered[
        (DOMAIN, SERVICE_RECALCULATE_SETTING_RECOMMENDATIONS)
    ](SimpleNamespace(data={}))
    await hass.services.registered[
        (DOMAIN, SERVICE_RECALCULATE_SETTING_RECOMMENDATIONS)
    ](SimpleNamespace(data={"circuit_id": "fridge"}))
    await hass.services.registered[(DOMAIN, SERVICE_APPLY_SETTING_RECOMMENDATION)](
        SimpleNamespace(data={"recommendation_id": "rec-apply"})
    )
    await hass.services.registered[(DOMAIN, SERVICE_DENY_SETTING_RECOMMENDATION)](
        SimpleNamespace(data={"recommendation_id": "rec-deny"})
    )
    await hass.services.registered[(DOMAIN, SERVICE_DISMISS_SETTING_RECOMMENDATION)](
        SimpleNamespace(data={"recommendation_id": "rec-dismiss"})
    )
    await hass.services.registered[(DOMAIN, SERVICE_UNDO_SETTING_RECOMMENDATION)](
        SimpleNamespace(data={"recommendation_id": "rec-undo"})
    )
    await hass.services.registered[(DOMAIN, SERVICE_RESET_SETTING_RECOMMENDATION)](
        SimpleNamespace(data={"recommendation_id": "rec-reset"})
    )

    assert fridge_coordinator.calls == [
        ("async_recalculate_setting_recommendations", (None,)),
        ("async_recalculate_setting_recommendations", ("fridge",)),
        ("async_apply_setting_recommendation", ("rec-apply",)),
        ("async_deny_setting_recommendation", ("rec-deny",)),
        ("async_dismiss_setting_recommendation", ("rec-dismiss",)),
        ("async_undo_setting_recommendation", ("rec-undo",)),
        ("async_reset_setting_recommendation", ("rec-reset",)),
    ]
    assert mains_coordinator.calls == [
        ("async_recalculate_setting_recommendations", (None,)),
    ]


@pytest.mark.asyncio
async def test_setting_recommendation_undo_requires_changed_recommendation() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_UNDO_SETTING_RECOMMENDATION,
        HomeAssistantError,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.store_data = SimpleNamespace(
                settings_recommendations={"rec-undo": object()}
            )
            self.state = SimpleNamespace(settings_recommendations_by_circuit={})

        def async_set_updated_data(self, data) -> None:
            return None

        async def async_undo_setting_recommendation(
            self,
            recommendation_id: str,
        ) -> bool:
            assert recommendation_id == "rec-undo"
            return False

    hass = SimpleNamespace(
        data={DOMAIN: {"entry": FakeCoordinator()}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)

    with pytest.raises(HomeAssistantError, match="could not be changed"):
        await hass.services.registered[(DOMAIN, SERVICE_UNDO_SETTING_RECOMMENDATION)](
            SimpleNamespace(data={"recommendation_id": "rec-undo"})
        )


@pytest.mark.asyncio
async def test_circuit_services_fail_fast_for_unknown_circuit_id() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_RELEARN_BASELINE,
        HomeAssistantError,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.store_data = SimpleNamespace(
                nilm_signatures={
                    "mains": [
                        {"signature_id": "signature_1"},
                        {"signature_id": "signature_2"},
                    ]
                }
            )

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "fridge"

        async def async_relearn_baseline(self, circuit_id: str) -> None:
            self.calls.append(("async_relearn_baseline", (circuit_id,)))

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)

    with pytest.raises(HomeAssistantError, match="Unknown circuit_id 'freezer'"):
        await hass.services.registered[(DOMAIN, SERVICE_RELEARN_BASELINE)](
            SimpleNamespace(data={"circuit_id": "freezer"})
        )

    assert coordinator.calls == []


@pytest.mark.asyncio
async def test_circuit_services_accept_analyzer_entity_target() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_RELEARN_BASELINE,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.circuit_configs = [SimpleNamespace(circuit_id="fridge")]

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "fridge"

        async def async_relearn_baseline(self, circuit_id: str) -> None:
            self.calls.append(("async_relearn_baseline", (circuit_id,)))

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    await hass.services.registered[(DOMAIN, SERVICE_RELEARN_BASELINE)](
        SimpleNamespace(data={"entity_id": "sensor.fridge_health_summary"})
    )

    assert coordinator.calls == [("async_relearn_baseline", ("fridge",))]


@pytest.mark.asyncio
async def test_circuit_services_accept_renamed_registry_entity_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.services as services
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_RELEARN_BASELINE,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeEntityRegistry:
        def async_get(self, entity_id: str):
            if entity_id == "sensor.kitchen_fridge_status":
                return SimpleNamespace(
                    platform=DOMAIN,
                    unique_id="entry-1_fridge_health_summary",
                )
            return None

    class FakeEntityRegistryModule:
        @staticmethod
        def async_get(hass):
            return FakeEntityRegistry()

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.circuit_configs = [SimpleNamespace(circuit_id="fridge")]

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "fridge"

        async def async_relearn_baseline(self, circuit_id: str) -> None:
            self.calls.append(("async_relearn_baseline", (circuit_id,)))

    monkeypatch.setattr(services, "er", FakeEntityRegistryModule)
    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    await hass.services.registered[(DOMAIN, SERVICE_RELEARN_BASELINE)](
        SimpleNamespace(data={"entity_id": "sensor.kitchen_fridge_status"})
    )

    assert coordinator.calls == [("async_relearn_baseline", ("fridge",))]


@pytest.mark.asyncio
async def test_maintenance_service_accepts_switch_entity_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.services as services
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_START_MAINTENANCE,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeEntityRegistry:
        def async_get(self, entity_id: str):
            if entity_id == "switch.kitchen_fridge_maintenance":
                return SimpleNamespace(
                    platform=DOMAIN,
                    unique_id="entry-1_fridge_maintenance",
                )
            return None

    class FakeEntityRegistryModule:
        @staticmethod
        def async_get(hass):
            return FakeEntityRegistry()

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.circuit_configs = [SimpleNamespace(circuit_id="fridge")]

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "fridge"

        async def async_start_maintenance(
            self,
            circuit_id: str,
            note: str,
            duration: object,
            relearn_on_end: bool,
        ) -> None:
            self.calls.append(
                (
                    "async_start_maintenance",
                    (circuit_id, note, duration, relearn_on_end),
                )
            )

    monkeypatch.setattr(services, "er", FakeEntityRegistryModule)
    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    await hass.services.registered[(DOMAIN, SERVICE_START_MAINTENANCE)](
        SimpleNamespace(data={"entity_id": "switch.kitchen_fridge_maintenance"})
    )

    assert coordinator.calls == [
        ("async_start_maintenance", ("fridge", "", None, False))
    ]


@pytest.mark.asyncio
async def test_circuit_services_reject_conflicting_circuit_and_entity_targets() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_RELEARN_BASELINE,
        HomeAssistantError,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        circuit_configs = [
            SimpleNamespace(circuit_id="fridge"),
            SimpleNamespace(circuit_id="hvac"),
        ]

        def async_set_updated_data(self, data) -> None:
            return None

        async def async_relearn_baseline(self, circuit_id: str) -> None:
            raise AssertionError("service should reject conflicting targets first")

    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": FakeCoordinator()}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)

    with pytest.raises(
        HomeAssistantError,
        match=(
            "circuit_id 'hvac' does not match entity_id target circuit "
            "'fridge'"
        ),
    ):
        await hass.services.registered[(DOMAIN, SERVICE_RELEARN_BASELINE)](
            SimpleNamespace(
                data={
                    "circuit_id": "hvac",
                    "entity_id": "sensor.fridge_health_summary",
                }
            )
        )


@pytest.mark.asyncio
async def test_circuit_services_reject_ambiguous_renamed_entity_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import custom_components.circuitsetup_energy_analyzer.services as services
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_RELEARN_BASELINE,
        HomeAssistantError,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeEntityRegistry:
        def async_get(self, entity_id: str):
            entries = {
                "sensor.kitchen_fridge_status": "entry-1_fridge_health_summary",
                "sensor.hvac_status": "entry-1_hvac_health_summary",
            }
            if entity_id in entries:
                return SimpleNamespace(platform=DOMAIN, unique_id=entries[entity_id])
            return None

    class FakeEntityRegistryModule:
        @staticmethod
        def async_get(hass):
            return FakeEntityRegistry()

    class FakeCoordinator:
        circuit_configs = [
            SimpleNamespace(circuit_id="fridge"),
            SimpleNamespace(circuit_id="hvac"),
        ]

        def async_set_updated_data(self, data) -> None:
            return None

        async def async_relearn_baseline(self, circuit_id: str) -> None:
            raise AssertionError("service should reject ambiguous targets first")

    monkeypatch.setattr(services, "er", FakeEntityRegistryModule)
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": FakeCoordinator()}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)

    with pytest.raises(
        HomeAssistantError,
        match="entity_id target resolved to multiple circuits: fridge, hvac",
    ):
        await hass.services.registered[(DOMAIN, SERVICE_RELEARN_BASELINE)](
            SimpleNamespace(
                data={
                    "entity_id": [
                        "sensor.kitchen_fridge_status",
                        "sensor.hvac_status",
                    ]
                }
            )
        )


@pytest.mark.asyncio
async def test_circuit_services_fail_fast_for_unknown_entity_target() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_RELEARN_BASELINE,
        HomeAssistantError,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.circuit_configs = [SimpleNamespace(circuit_id="fridge")]

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "fridge"

        async def async_relearn_baseline(self, circuit_id: str) -> None:
            self.calls.append(("async_relearn_baseline", (circuit_id,)))

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)

    with pytest.raises(
        HomeAssistantError,
        match=(
            "Could not derive circuit_id from entity_id "
            "'sensor.unknown_health_summary'"
        ),
    ):
        await hass.services.registered[(DOMAIN, SERVICE_RELEARN_BASELINE)](
            SimpleNamespace(
                data={"entity_id": "sensor.unknown_health_summary"}
            )
        )

    assert coordinator.calls == []


@pytest.mark.asyncio
async def test_recalculate_recommendations_all_target_remains_explicit() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_RECALCULATE_SETTING_RECOMMENDATIONS,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self, circuits: set[str]) -> None:
            self.circuits = circuits
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id in self.circuits

        async def async_recalculate_setting_recommendations(
            self,
            circuit_id: str | None,
        ) -> None:
            self.calls.append(
                ("async_recalculate_setting_recommendations", (circuit_id,))
            )

    fridge = FakeCoordinator({"fridge"})
    hvac = FakeCoordinator({"hvac"})
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": fridge, "entry-2": hvac}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    await hass.services.registered[
        (DOMAIN, SERVICE_RECALCULATE_SETTING_RECOMMENDATIONS)
    ](SimpleNamespace(data={}))

    assert fridge.calls == [
        ("async_recalculate_setting_recommendations", (None,)),
    ]
    assert hvac.calls == [
        ("async_recalculate_setting_recommendations", (None,)),
    ]


@pytest.mark.asyncio
async def test_setting_recommendation_services_require_unique_or_explicit_entry(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_APPLY_SETTING_RECOMMENDATION,
        HomeAssistantError,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.store_data = SimpleNamespace(
                settings_recommendations={"duplicate:daily_spike_ratio:v1": object()}
            )

        def async_set_updated_data(self, data) -> None:
            return None

        async def async_apply_setting_recommendation(
            self,
            recommendation_id: str,
        ) -> None:
            self.calls.append(
                ("async_apply_setting_recommendation", (recommendation_id,))
            )

    first = FakeCoordinator()
    second = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": first, "entry-2": second}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    handler = hass.services.registered[(DOMAIN, SERVICE_APPLY_SETTING_RECOMMENDATION)]

    with pytest.raises(
        HomeAssistantError,
        match="recommendation_id 'duplicate:daily_spike_ratio:v1' matched multiple",
    ):
        await handler(
            SimpleNamespace(
                data={"recommendation_id": "duplicate:daily_spike_ratio:v1"}
            )
        )

    assert first.calls == []
    assert second.calls == []

    with pytest.raises(
        HomeAssistantError,
        match="Unknown recommendation_id 'missing:daily_spike_ratio:v1'",
    ):
        await handler(
            SimpleNamespace(data={"recommendation_id": "missing:daily_spike_ratio:v1"})
        )

    await handler(
        SimpleNamespace(
            data={
                "recommendation_id": "duplicate:daily_spike_ratio:v1",
                "entry_id": "entry-2",
            }
        )
    )

    assert first.calls == []
    assert second.calls == [
        (
            "async_apply_setting_recommendation",
            ("duplicate:daily_spike_ratio:v1",),
        )
    ]


@pytest.mark.asyncio
async def test_setting_recommendation_services_accept_single_entity_target(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_APPLY_SETTING_RECOMMENDATION,
        SERVICE_DENY_SETTING_RECOMMENDATION,
        SERVICE_DISMISS_SETTING_RECOMMENDATION,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.circuit_configs = [SimpleNamespace(circuit_id="fridge")]
            self.store_data = SimpleNamespace(
                settings_recommendations={"fridge:daily_spike_ratio:v1": object()}
            )

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "fridge"

        async def async_apply_setting_recommendation(
            self,
            recommendation_id: str,
        ) -> None:
            self.calls.append(
                ("async_apply_setting_recommendation", (recommendation_id,))
            )

        async def async_deny_setting_recommendation(
            self,
            recommendation_id: str,
        ) -> None:
            self.calls.append(
                ("async_deny_setting_recommendation", (recommendation_id,))
            )

        async def async_dismiss_setting_recommendation(
            self,
            recommendation_id: str,
        ) -> None:
            self.calls.append(
                ("async_dismiss_setting_recommendation", (recommendation_id,))
            )

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)

    entity_data = {"entity_id": "sensor.fridge_health_summary"}
    await hass.services.registered[(DOMAIN, SERVICE_APPLY_SETTING_RECOMMENDATION)](
        SimpleNamespace(data=entity_data)
    )
    await hass.services.registered[(DOMAIN, SERVICE_DENY_SETTING_RECOMMENDATION)](
        SimpleNamespace(data=entity_data)
    )
    await hass.services.registered[(DOMAIN, SERVICE_DISMISS_SETTING_RECOMMENDATION)](
        SimpleNamespace(data=entity_data)
    )

    assert coordinator.calls == [
        (
            "async_apply_setting_recommendation",
            ("fridge:daily_spike_ratio:v1",),
        ),
        (
            "async_deny_setting_recommendation",
            ("fridge:daily_spike_ratio:v1",),
        ),
        (
            "async_dismiss_setting_recommendation",
            ("fridge:daily_spike_ratio:v1",),
        ),
    ]


@pytest.mark.asyncio
async def test_setting_recommendation_entity_target_ignores_stored_history(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_APPLY_SETTING_RECOMMENDATION,
        async_setup_services,
    )
    from custom_components.circuitsetup_energy_analyzer.settings_advisor import (
        RecommendationStatus,
        SettingRecommendation,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    def recommendation(
        recommendation_id: str,
        status: RecommendationStatus,
    ) -> SettingRecommendation:
        return SettingRecommendation(
            recommendation_id=recommendation_id,
            unique_key=recommendation_id.rsplit(":", 1)[0],
            circuit_id="fridge",
            circuit_name="Fridge",
            setting_key="daily_spike_ratio",
            setting_label="Daily Spike Ratio",
            current_value=0.25,
            suggested_value=0.3,
            unit="ratio",
            feature="energy_usage_spikes",
            group="Energy Usage",
            confidence=0.82,
            reason="Observed high daily energy spikes.",
            evidence={},
            apply_payload={"daily_spike_ratio": 0.3},
            status=status,
            created_at=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
            expires_at=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
        )

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.circuit_configs = [SimpleNamespace(circuit_id="fridge")]
            self.state = SimpleNamespace(
                settings_recommendations_by_circuit={
                    "fridge": [
                        {
                            "recommendation_id": "fridge:daily_spike_ratio:v1",
                            "circuit_id": "fridge",
                        }
                    ]
                }
            )
            self.store_data = SimpleNamespace(
                settings_recommendations={
                    "fridge:daily_spike_ratio:v1": recommendation(
                        "fridge:daily_spike_ratio:v1",
                        RecommendationStatus.PENDING,
                    ),
                    "fridge:standby_threshold_w:v1": recommendation(
                        "fridge:standby_threshold_w:v1",
                        RecommendationStatus.APPLIED,
                    ),
                }
            )

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "fridge"

        async def async_apply_setting_recommendation(
            self,
            recommendation_id: str,
        ) -> None:
            self.calls.append(
                ("async_apply_setting_recommendation", (recommendation_id,))
            )

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    await hass.services.registered[(DOMAIN, SERVICE_APPLY_SETTING_RECOMMENDATION)](
        SimpleNamespace(data={"entity_id": "sensor.fridge_health_summary"})
    )

    assert coordinator.calls == [
        ("async_apply_setting_recommendation", ("fridge:daily_spike_ratio:v1",))
    ]


@pytest.mark.asyncio
async def test_setting_recommendation_entity_target_ignores_state_history(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_APPLY_SETTING_RECOMMENDATION,
        async_setup_services,
    )
    from custom_components.circuitsetup_energy_analyzer.settings_advisor import (
        RecommendationStatus,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.circuit_configs = [SimpleNamespace(circuit_id="fridge")]
            self.state = SimpleNamespace(
                settings_recommendations_by_circuit={
                    "fridge": [
                        {
                            "recommendation_id": "fridge:daily_spike_ratio:v1",
                            "circuit_id": "fridge",
                            "status": RecommendationStatus.PENDING,
                            "expires_at": datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
                        },
                        {
                            "recommendation_id": "fridge:standby_threshold_w:v1",
                            "circuit_id": "fridge",
                            "status": RecommendationStatus.APPLIED,
                            "expires_at": datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
                        },
                        {
                            "recommendation_id": "fridge:max_active_minutes:v1",
                            "circuit_id": "fridge",
                            "status": RecommendationStatus.PENDING,
                            "expires_at": "2026-06-01T12:00:00+00:00",
                        },
                    ]
                }
            )
            self.store_data = SimpleNamespace(
                settings_recommendations={
                    "fridge:daily_spike_ratio:v1": SimpleNamespace(
                        circuit_id="fridge",
                        status=RecommendationStatus.PENDING,
                        expires_at=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
                    )
                }
            )

        def _now_fn(self) -> datetime:
            return datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "fridge"

        async def async_apply_setting_recommendation(
            self,
            recommendation_id: str,
        ) -> None:
            self.calls.append(
                ("async_apply_setting_recommendation", (recommendation_id,))
            )

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    await hass.services.registered[(DOMAIN, SERVICE_APPLY_SETTING_RECOMMENDATION)](
        SimpleNamespace(data={"entity_id": "sensor.fridge_health_summary"})
    )

    assert coordinator.calls == [
        ("async_apply_setting_recommendation", ("fridge:daily_spike_ratio:v1",))
    ]


@pytest.mark.asyncio
async def test_setting_recommendation_entity_target_rejects_ambiguous_recommendations(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_APPLY_SETTING_RECOMMENDATION,
        HomeAssistantError,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self, recommendation_ids: set[str]) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.circuit_configs = [SimpleNamespace(circuit_id="fridge")]
            self.store_data = SimpleNamespace(
                settings_recommendations={
                    recommendation_id: object()
                    for recommendation_id in recommendation_ids
                }
            )

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "fridge"

        async def async_apply_setting_recommendation(
            self,
            recommendation_id: str,
        ) -> None:
            self.calls.append(
                ("async_apply_setting_recommendation", (recommendation_id,))
            )

    coordinator = FakeCoordinator(
        {"fridge:daily_spike_ratio:v1", "fridge:standby_threshold_w:v1"}
    )
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    handler = hass.services.registered[(DOMAIN, SERVICE_APPLY_SETTING_RECOMMENDATION)]

    with pytest.raises(
        HomeAssistantError,
        match=(
            "entity_id target for circuit_id 'fridge' has multiple setting "
            "recommendations"
        ),
    ):
        await handler(
            SimpleNamespace(data={"entity_id": "sensor.fridge_health_summary"})
        )

    assert coordinator.calls == []


@pytest.mark.asyncio
async def test_nilm_signature_services_fail_fast_for_unknown_signature_id() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_IGNORE_NILM_SIGNATURE,
        SERVICE_MERGE_NILM_SIGNATURES,
        HomeAssistantError,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.store_data = SimpleNamespace(
                nilm_signatures={
                    "mains": [
                        {"signature_id": "signature_1"},
                        {"signature_id": "signature_2"},
                    ]
                }
            )

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "mains"

        async def async_ignore_nilm_signature(
            self,
            circuit_id: str,
            signature_id: str,
        ) -> None:
            self.calls.append(
                ("async_ignore_nilm_signature", (circuit_id, signature_id))
            )

        async def async_merge_nilm_signatures(
            self,
            circuit_id: str,
            source_signature_id: str,
            target_signature_id: str,
        ) -> None:
            self.calls.append(
                (
                    "async_merge_nilm_signatures",
                    (circuit_id, source_signature_id, target_signature_id),
                )
            )

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)

    with pytest.raises(
        HomeAssistantError,
        match="Unknown signature_id 'missing'. Known signature IDs for mains: "
        "signature_1, signature_2.",
    ):
        await hass.services.registered[(DOMAIN, SERVICE_IGNORE_NILM_SIGNATURE)](
            SimpleNamespace(data={"circuit_id": "mains", "signature_id": "missing"})
        )

    with pytest.raises(
        HomeAssistantError,
        match="Unknown signature_id 'missing-target'. Known signature IDs for mains: "
        "signature_1, signature_2.",
    ):
        await hass.services.registered[(DOMAIN, SERVICE_MERGE_NILM_SIGNATURES)](
            SimpleNamespace(
                data={
                    "circuit_id": "mains",
                    "source_signature_id": "signature_1",
                    "target_signature_id": "missing-target",
                }
            )
        )

    await hass.services.registered[(DOMAIN, SERVICE_IGNORE_NILM_SIGNATURE)](
        SimpleNamespace(data={"circuit_id": "mains", "signature_id": "signature_1"})
    )

    assert coordinator.calls == [
        ("async_ignore_nilm_signature", ("mains", "signature_1"))
    ]


@pytest.mark.asyncio
async def test_nilm_signature_services_accept_analyzer_entity_target() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_IGNORE_NILM_SIGNATURE,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.circuit_configs = [SimpleNamespace(circuit_id="mains")]
            self.store_data = SimpleNamespace(
                nilm_signatures={"mains": [{"signature_id": "signature_1"}]}
            )

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "mains"

        async def async_ignore_nilm_signature(
            self,
            circuit_id: str,
            signature_id: str,
        ) -> None:
            self.calls.append(
                ("async_ignore_nilm_signature", (circuit_id, signature_id))
            )

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    await hass.services.registered[(DOMAIN, SERVICE_IGNORE_NILM_SIGNATURE)](
        SimpleNamespace(
            data={
                "entity_id": "sensor.mains_health_summary",
                "signature_id": "signature_1",
            }
        )
    )

    assert coordinator.calls == [
        ("async_ignore_nilm_signature", ("mains", "signature_1"))
    ]


@pytest.mark.asyncio
async def test_nilm_label_interval_services_accept_create_update_and_delete() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_DELETE_NILM_LABEL_INTERVAL,
        SERVICE_LABEL_NILM_INTERVAL,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.circuit_configs = [SimpleNamespace(circuit_id="mains")]
            self.store_data = FeatureStoreData()

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "mains"

        async def async_label_nilm_interval(
            self,
            circuit_id: str,
            *,
            label: str,
            start,
            end,
            appliance_id: str | None = None,
            mains_entity_id: str | None = None,
            ground_truth_entity_id: str | None = None,
            interval_id: str | None = None,
            source: str = "manual",
            confidence: float = 1.0,
        ) -> None:
            self.calls.append(
                (
                    "async_label_nilm_interval",
                    (
                        circuit_id,
                        label,
                        start,
                        end,
                        appliance_id,
                        mains_entity_id,
                        ground_truth_entity_id,
                        interval_id,
                        source,
                        confidence,
                    ),
                )
            )

        async def async_delete_nilm_label_interval(
            self,
            circuit_id: str,
            interval_id: str,
        ) -> None:
            self.calls.append(
                ("async_delete_nilm_label_interval", (circuit_id, interval_id))
            )

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    await hass.services.registered[(DOMAIN, SERVICE_LABEL_NILM_INTERVAL)](
        SimpleNamespace(
            data={
                "circuit_id": "mains",
                "label": "Dishwasher",
                "start": "2026-06-02T12:00:00+00:00",
                "end": "2026-06-02T12:45:00+00:00",
                "appliance_id": "dishwasher",
                "mains_entity_id": "sensor.mains_power",
                "ground_truth_entity_id": "sensor.dishwasher_power",
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_DELETE_NILM_LABEL_INTERVAL)](
        SimpleNamespace(data={"circuit_id": "mains", "interval_id": "label-1"})
    )

    assert coordinator.calls == [
        (
            "async_label_nilm_interval",
            (
                "mains",
                "Dishwasher",
                "2026-06-02T12:00:00+00:00",
                "2026-06-02T12:45:00+00:00",
                "dishwasher",
                "sensor.mains_power",
                "sensor.dishwasher_power",
                None,
                "manual",
                1.0,
            ),
        ),
        ("async_delete_nilm_label_interval", ("mains", "label-1")),
    ]


@pytest.mark.asyncio
async def test_nilm_assignment_services_dispatch_to_matching_coordinator() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_ASSIGN_INTERVAL_TO_APPLIANCE,
        SERVICE_ASSIGN_SESSION_TO_APPLIANCE,
        SERVICE_ASSIGN_SIGNATURE_TO_APPLIANCE,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.circuit_configs = [SimpleNamespace(circuit_id="mains")]
            self.store_data = FeatureStoreData(
                nilm_signatures={"mains": [{"signature_id": "signature_1"}]},
                nilm_label_intervals_by_circuit={
                    "mains": [{"interval_id": "label-1"}]
                },
            )

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "mains"

        async def async_assign_nilm_signature(
            self,
            circuit_id: str,
            signature_id: str,
            *,
            label: str,
            appliance_id: str | None = None,
            appliance_profile: str | None = None,
            assignment_id: str | None = None,
        ) -> None:
            self.calls.append(
                (
                    "async_assign_nilm_signature",
                    (
                        circuit_id,
                        signature_id,
                        label,
                        appliance_id,
                        appliance_profile,
                        assignment_id,
                    ),
                )
            )

        async def async_assign_nilm_session(
            self,
            circuit_id: str,
            session_id: str,
            *,
            label: str,
            signature_fingerprint: str | None = None,
            appliance_id: str | None = None,
            appliance_profile: str | None = None,
            assignment_id: str | None = None,
        ) -> None:
            self.calls.append(
                (
                    "async_assign_nilm_session",
                    (
                        circuit_id,
                        session_id,
                        label,
                        signature_fingerprint,
                        appliance_id,
                        appliance_profile,
                        assignment_id,
                    ),
                )
            )

        async def async_assign_nilm_interval(
            self,
            circuit_id: str,
            interval_id: str,
            *,
            label: str,
            appliance_id: str | None = None,
            appliance_profile: str | None = None,
            assignment_id: str | None = None,
        ) -> None:
            self.calls.append(
                (
                    "async_assign_nilm_interval",
                    (
                        circuit_id,
                        interval_id,
                        label,
                        appliance_id,
                        appliance_profile,
                        assignment_id,
                    ),
                )
            )

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    await hass.services.registered[(DOMAIN, SERVICE_ASSIGN_SIGNATURE_TO_APPLIANCE)](
        SimpleNamespace(
            data={
                "circuit_id": "mains",
                "signature_id": "signature_1",
                "label": "Dishwasher",
                "appliance_id": "dishwasher",
                "appliance_profile": "dishwasher",
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_ASSIGN_SESSION_TO_APPLIANCE)](
        SimpleNamespace(
            data={
                "circuit_id": "mains",
                "session_id": "session_1",
                "signature_fingerprint": "fingerprint_1",
                "label": "Dishwasher",
                "appliance_id": "dishwasher",
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_ASSIGN_INTERVAL_TO_APPLIANCE)](
        SimpleNamespace(
            data={
                "circuit_id": "mains",
                "interval_id": "label-1",
                "label": "Dishwasher",
                "appliance_id": "dishwasher",
            }
        )
    )

    assert coordinator.calls == [
        (
            "async_assign_nilm_signature",
            (
                "mains",
                "signature_1",
                "Dishwasher",
                "dishwasher",
                "dishwasher",
                None,
            ),
        ),
        (
            "async_assign_nilm_session",
            (
                "mains",
                "session_1",
                "Dishwasher",
                "fingerprint_1",
                "dishwasher",
                None,
                None,
            ),
        ),
        (
            "async_assign_nilm_interval",
            (
                "mains",
                "label-1",
                "Dishwasher",
                "dishwasher",
                None,
                None,
            ),
        ),
    ]


@pytest.mark.asyncio
async def test_nilm_publish_services_dispatch_to_matching_coordinator() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_PUBLISH_NILM_APPLIANCE_ASSIGNMENT,
        SERVICE_RETIRE_NILM_APPLIANCE_ASSIGNMENT,
        SERVICE_UNPUBLISH_NILM_APPLIANCE_ASSIGNMENT,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.circuit_configs = [SimpleNamespace(circuit_id="mains")]
            self.store_data = FeatureStoreData(
                nilm_appliance_assignments_by_circuit={
                    "mains": [{"assignment_id": "assignment-dishwasher"}]
                },
            )

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "mains"

        def async_set_updated_data(self, data) -> None:
            return None

        async def async_publish_nilm_appliance_assignment(
            self,
            circuit_id: str,
            assignment_id: str,
        ) -> None:
            self.calls.append(
                (
                    "async_publish_nilm_appliance_assignment",
                    (circuit_id, assignment_id),
                )
            )

        async def async_unpublish_nilm_appliance_assignment(
            self,
            circuit_id: str,
            assignment_id: str,
        ) -> None:
            self.calls.append(
                (
                    "async_unpublish_nilm_appliance_assignment",
                    (circuit_id, assignment_id),
                )
            )

        async def async_retire_nilm_appliance_assignment(
            self,
            circuit_id: str,
            assignment_id: str,
        ) -> None:
            self.calls.append(
                (
                    "async_retire_nilm_appliance_assignment",
                    (circuit_id, assignment_id),
                )
            )

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    for service in (
        SERVICE_PUBLISH_NILM_APPLIANCE_ASSIGNMENT,
        SERVICE_UNPUBLISH_NILM_APPLIANCE_ASSIGNMENT,
        SERVICE_RETIRE_NILM_APPLIANCE_ASSIGNMENT,
    ):
        await hass.services.registered[(DOMAIN, service)](
            SimpleNamespace(
                data={
                    "circuit_id": "mains",
                    "assignment_id": "assignment-dishwasher",
                }
            )
        )

    assert coordinator.calls == [
        (
            "async_publish_nilm_appliance_assignment",
            ("mains", "assignment-dishwasher"),
        ),
        (
            "async_unpublish_nilm_appliance_assignment",
            ("mains", "assignment-dishwasher"),
        ),
        (
            "async_retire_nilm_appliance_assignment",
            ("mains", "assignment-dishwasher"),
        ),
    ]


@pytest.mark.asyncio
async def test_nilm_session_validation_services_dispatch() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_REJECT_NILM_SESSION,
        SERVICE_VALIDATE_NILM_SESSION,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.circuit_configs = [SimpleNamespace(circuit_id="mains")]
            self.store_data = FeatureStoreData(
                nilm_appliance_assignments_by_circuit={
                    "mains": [
                        {
                            "assignment_id": "assignment-dishwasher",
                            "session_ids": ["session_1"],
                        }
                    ]
                },
            )

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "mains"

        def async_set_updated_data(self, data) -> None:
            return None

        async def async_validate_nilm_session(
            self,
            circuit_id: str,
            session_id: str,
            *,
            assignment_id: str | None = None,
        ) -> None:
            self.calls.append(
                (
                    "async_validate_nilm_session",
                    (circuit_id, session_id, assignment_id),
                )
            )

        async def async_reject_nilm_session(
            self,
            circuit_id: str,
            session_id: str,
            *,
            assignment_id: str | None = None,
        ) -> None:
            self.calls.append(
                (
                    "async_reject_nilm_session",
                    (circuit_id, session_id, assignment_id),
                )
            )

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    for service in (SERVICE_VALIDATE_NILM_SESSION, SERVICE_REJECT_NILM_SESSION):
        await hass.services.registered[(DOMAIN, service)](
            SimpleNamespace(
                data={
                    "circuit_id": "mains",
                    "session_id": "session_1",
                    "assignment_id": "assignment-dishwasher",
                }
            )
        )

    assert coordinator.calls == [
        (
            "async_validate_nilm_session",
            ("mains", "session_1", "assignment-dishwasher"),
        ),
        (
            "async_reject_nilm_session",
            ("mains", "session_1", "assignment-dishwasher"),
        ),
    ]


@pytest.mark.asyncio
async def test_nilm_assignment_edit_services_dispatch() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_CHANGE_NILM_APPLIANCE_PROFILE,
        SERVICE_RENAME_NILM_APPLIANCE,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.circuit_configs = [SimpleNamespace(circuit_id="mains")]
            self.store_data = FeatureStoreData(
                nilm_appliance_assignments_by_circuit={
                    "mains": [{"assignment_id": "assignment-dishwasher"}]
                },
            )

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "mains"

        def async_set_updated_data(self, data) -> None:
            return None

        async def async_rename_nilm_appliance(
            self,
            circuit_id: str,
            assignment_id: str,
            *,
            label: str,
        ) -> None:
            self.calls.append(
                (
                    "async_rename_nilm_appliance",
                    (circuit_id, assignment_id, label),
                )
            )

        async def async_change_nilm_appliance_profile(
            self,
            circuit_id: str,
            assignment_id: str,
            *,
            appliance_profile: str,
        ) -> None:
            self.calls.append(
                (
                    "async_change_nilm_appliance_profile",
                    (circuit_id, assignment_id, appliance_profile),
                )
            )

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    await hass.services.registered[(DOMAIN, SERVICE_RENAME_NILM_APPLIANCE)](
        SimpleNamespace(
            data={
                "circuit_id": "mains",
                "assignment_id": "assignment-dishwasher",
                "label": "Kitchen Dishwasher",
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_CHANGE_NILM_APPLIANCE_PROFILE)](
        SimpleNamespace(
            data={
                "circuit_id": "mains",
                "assignment_id": "assignment-dishwasher",
                "appliance_profile": "dishwasher_heated_dry",
            }
        )
    )

    assert coordinator.calls == [
        (
            "async_rename_nilm_appliance",
            ("mains", "assignment-dishwasher", "Kitchen Dishwasher"),
        ),
        (
            "async_change_nilm_appliance_profile",
            ("mains", "assignment-dishwasher", "dishwasher_heated_dry"),
        ),
    ]


@pytest.mark.asyncio
async def test_nilm_assignment_merge_service_dispatch() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_MERGE_NILM_ASSIGNMENTS,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.circuit_configs = [SimpleNamespace(circuit_id="mains")]
            self.store_data = FeatureStoreData(
                nilm_appliance_assignments_by_circuit={
                    "mains": [
                        {"assignment_id": "assignment-source"},
                        {"assignment_id": "assignment-target"},
                    ]
                },
            )

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "mains"

        def async_set_updated_data(self, data) -> None:
            return None

        async def async_merge_nilm_assignments(
            self,
            circuit_id: str,
            source_assignment_id: str,
            target_assignment_id: str,
        ) -> None:
            self.calls.append(
                (
                    "async_merge_nilm_assignments",
                    (circuit_id, source_assignment_id, target_assignment_id),
                )
            )

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    await hass.services.registered[(DOMAIN, SERVICE_MERGE_NILM_ASSIGNMENTS)](
        SimpleNamespace(
            data={
                "circuit_id": "mains",
                "source_assignment_id": "assignment-source",
                "target_assignment_id": "assignment-target",
            }
        )
    )

    assert coordinator.calls == [
        (
            "async_merge_nilm_assignments",
            ("mains", "assignment-source", "assignment-target"),
        )
    ]


@pytest.mark.asyncio
async def test_nilm_signature_services_reject_self_merge() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_MERGE_NILM_SIGNATURES,
        HomeAssistantError,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        circuit_configs = [SimpleNamespace(circuit_id="mains")]
        store_data = SimpleNamespace(
            nilm_signatures={"mains": [{"signature_id": "signature_1"}]}
        )

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "mains"

        async def async_merge_nilm_signatures(
            self,
            circuit_id: str,
            source_signature_id: str,
            target_signature_id: str,
        ) -> None:
            raise AssertionError("service should reject self-merge first")

    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": FakeCoordinator()}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)

    with pytest.raises(
        HomeAssistantError,
        match="source_signature_id and target_signature_id must be different",
    ):
        await hass.services.registered[(DOMAIN, SERVICE_MERGE_NILM_SIGNATURES)](
            SimpleNamespace(
                data={
                    "circuit_id": "mains",
                    "source_signature_id": "signature_1",
                    "target_signature_id": "signature_1",
                }
            )
        )


@pytest.mark.asyncio
async def test_alert_feedback_services_reject_unknown_alert_ids() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        services as services_module,
    )

    SERVICE_MARK_NILM_APPLIANCE_CORRECT = getattr(
        services_module,
        "SERVICE_MARK_NILM_APPLIANCE_CORRECT",
        None,
    )
    SERVICE_MARK_NILM_APPLIANCE_WRONG = getattr(
        services_module,
        "SERVICE_MARK_NILM_APPLIANCE_WRONG",
        None,
    )
    assert SERVICE_MARK_NILM_APPLIANCE_CORRECT is not None
    assert SERVICE_MARK_NILM_APPLIANCE_WRONG is not None

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def async_set_updated_data(self, data) -> None:
            return None

        async def async_acknowledge_alert(self, alert_id: str) -> bool:
            return False

        async def async_mark_alert_expected(self, alert_id: str) -> bool:
            return False

        async def async_mark_alert_unhelpful(self, alert_id: str) -> bool:
            return False

        async def async_mark_nilm_appliance_correct(self, alert_id: str) -> bool:
            return False

        async def async_mark_nilm_appliance_wrong(self, alert_id: str) -> bool:
            return False

    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": FakeCoordinator()}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await services_module.async_setup_services(hass)

    for service in (
        services_module.SERVICE_ACKNOWLEDGE_ALERT,
        services_module.SERVICE_MARK_ALERT_EXPECTED,
        services_module.SERVICE_MARK_ALERT_UNHELPFUL,
        SERVICE_MARK_NILM_APPLIANCE_CORRECT,
        SERVICE_MARK_NILM_APPLIANCE_WRONG,
    ):
        with pytest.raises(
            services_module.HomeAssistantError,
            match="Unknown alert_id 'stale-alert'",
        ):
            await hass.services.registered[(DOMAIN, service)](
                SimpleNamespace(data={"alert_id": "stale-alert"})
            )


@pytest.mark.asyncio
async def test_alert_feedback_services_accept_single_alert_entity_target() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        services as services_module,
    )
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        notification_id_for_alert,
    )

    SERVICE_MARK_NILM_APPLIANCE_CORRECT = getattr(
        services_module,
        "SERVICE_MARK_NILM_APPLIANCE_CORRECT",
        None,
    )
    SERVICE_MARK_NILM_APPLIANCE_WRONG = getattr(
        services_module,
        "SERVICE_MARK_NILM_APPLIANCE_WRONG",
        None,
    )
    assert SERVICE_MARK_NILM_APPLIANCE_CORRECT is not None
    assert SERVICE_MARK_NILM_APPLIANCE_WRONG is not None

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        circuit_configs = [SimpleNamespace(circuit_id="fridge")]

        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []
            self.alert = AlertEvidence(
                timestamp=datetime(2026, 6, 13, 12, 0, tzinfo=UTC),
                circuit_id="fridge",
                severity=Severity.WARNING,
                message="Fridge door appears open.",
                feature="door_open",
            )
            self.state = SimpleNamespace(
                active_alerts_by_circuit={
                    "fridge": [self.alert],
                }
            )

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "fridge"

        async def async_acknowledge_alert(self, alert_id: str) -> bool:
            self.calls.append(("async_acknowledge_alert", alert_id))
            return True

        async def async_mark_alert_expected(self, alert_id: str) -> bool:
            self.calls.append(("async_mark_alert_expected", alert_id))
            return True

        async def async_mark_alert_unhelpful(self, alert_id: str) -> bool:
            self.calls.append(("async_mark_alert_unhelpful", alert_id))
            return True

        async def async_mark_nilm_appliance_correct(self, alert_id: str) -> bool:
            self.calls.append(("async_mark_nilm_appliance_correct", alert_id))
            return True

        async def async_mark_nilm_appliance_wrong(self, alert_id: str) -> bool:
            self.calls.append(("async_mark_nilm_appliance_wrong", alert_id))
            return True

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await services_module.async_setup_services(hass)

    for service in (
        services_module.SERVICE_ACKNOWLEDGE_ALERT,
        services_module.SERVICE_MARK_ALERT_EXPECTED,
        services_module.SERVICE_MARK_ALERT_UNHELPFUL,
        SERVICE_MARK_NILM_APPLIANCE_CORRECT,
        SERVICE_MARK_NILM_APPLIANCE_WRONG,
    ):
        await hass.services.registered[(DOMAIN, service)](
            SimpleNamespace(data={"entity_id": "sensor.fridge_health_summary"})
        )

    expected_alert_id = notification_id_for_alert(coordinator.alert)
    assert coordinator.calls == [
        ("async_acknowledge_alert", expected_alert_id),
        ("async_mark_alert_expected", expected_alert_id),
        ("async_mark_alert_unhelpful", expected_alert_id),
        ("async_mark_nilm_appliance_correct", expected_alert_id),
        ("async_mark_nilm_appliance_wrong", expected_alert_id),
    ]


@pytest.mark.asyncio
async def test_alert_feedback_services_reject_ambiguous_entity_target() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_MARK_ALERT_EXPECTED,
        HomeAssistantError,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        circuit_configs = [SimpleNamespace(circuit_id="fridge")]

        def __init__(self) -> None:
            self.state = SimpleNamespace(
                active_alerts_by_circuit={
                    "fridge": [
                        SimpleNamespace(alert_id="alert-a"),
                        SimpleNamespace(alert_id="alert-b"),
                    ],
                }
            )

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "fridge"

        async def async_mark_alert_expected(self, alert_id: str) -> bool:
            raise AssertionError("service should reject ambiguous target first")

    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": FakeCoordinator()}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)

    with pytest.raises(
        HomeAssistantError,
        match="entity_id target for circuit_id 'fridge' has multiple active alerts",
    ):
        await hass.services.registered[(DOMAIN, SERVICE_MARK_ALERT_EXPECTED)](
            SimpleNamespace(data={"entity_id": "sensor.fridge_health_summary"})
        )


@pytest.mark.asyncio
async def test_user_experience_services_dispatch_to_loaded_coordinators() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_END_MAINTENANCE,
        SERVICE_EXPORT_HISTORY_CSV,
        SERVICE_MARK_ALERT_EXPECTED,
        SERVICE_MARK_ALERT_UNHELPFUL,
        SERVICE_MARK_NILM_SIGNATURE_EXPECTED,
        SERVICE_MERGE_NILM_SIGNATURES,
        SERVICE_SET_ACTIVITY_ALERT_SETTINGS,
        SERVICE_SET_BILLING_CYCLE_SETTINGS,
        SERVICE_SET_CAPACITY_SETTINGS,
        SERVICE_SET_CIRCUIT_SENSITIVITY,
        SERVICE_SET_COST_SETTINGS,
        SERVICE_SET_DEMAND_SETTINGS,
        SERVICE_SET_ENERGY_GOAL_SETTINGS,
        SERVICE_SET_ENERGY_USAGE_SETTINGS,
        SERVICE_SET_LEG_IMBALANCE_SETTINGS,
        SERVICE_SET_MAINS_BALANCE_SETTINGS,
        SERVICE_SET_METRIC_CONSISTENCY_SETTINGS,
        SERVICE_SET_SOLAR_FLOW_SETTINGS,
        SERVICE_SET_STANDBY_SETTINGS,
        SERVICE_SET_UTILITY_COMPARISON_SETTINGS,
        SERVICE_START_MAINTENANCE,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []
            self.store_data = SimpleNamespace(
                nilm_signatures={
                    "mains": [
                        {"signature_id": "signature_1"},
                        {"signature_id": "signature_2"},
                    ]
                }
            )

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id in {"fridge", "hvac", "mains"}

        async def async_set_circuit_sensitivity(
            self,
            circuit_id: str,
            preset: str,
        ) -> None:
            self.calls.append(("async_set_circuit_sensitivity", (circuit_id, preset)))

        async def async_set_energy_usage_settings(
            self,
            circuit_id: str,
            window_days: object = None,
            daily_spike_ratio: object = None,
        ) -> None:
            self.calls.append(
                (
                    "async_set_energy_usage_settings",
                    (circuit_id, window_days, daily_spike_ratio),
                )
            )

        async def async_set_energy_goal_settings(
            self,
            circuit_id: str,
            daily_goal_kwh: object = None,
            goal_alert_ratio: object = None,
        ) -> None:
            self.calls.append(
                (
                    "async_set_energy_goal_settings",
                    (circuit_id, daily_goal_kwh, goal_alert_ratio),
                )
            )

        async def async_set_demand_settings(
            self,
            circuit_id: str,
            window_minutes: object = None,
            demand_limit_w: object = None,
        ) -> None:
            self.calls.append(
                (
                    "async_set_demand_settings",
                    (circuit_id, window_minutes, demand_limit_w),
                )
            )

        async def async_set_activity_alert_settings(
            self,
            circuit_id: str,
            max_active_minutes: object = None,
            max_idle_minutes: object = None,
        ) -> None:
            self.calls.append(
                (
                    "async_set_activity_alert_settings",
                    (circuit_id, max_active_minutes, max_idle_minutes),
                )
            )

        async def async_set_billing_cycle_settings(
            self,
            circuit_id: str,
            cycle_start_day: object = None,
            budget_kwh: object = None,
            budget_alert_ratio: object = None,
        ) -> None:
            self.calls.append(
                (
                    "async_set_billing_cycle_settings",
                    (
                        circuit_id,
                        cycle_start_day,
                        budget_kwh,
                        budget_alert_ratio,
                    ),
                )
            )

        async def async_set_cost_settings(
            self,
            circuit_id: str,
            cycle_start_day: object = None,
            default_rate_per_kwh: object = None,
            tou_rate_per_kwh: object = None,
            tou_start: object = None,
            tou_end: object = None,
            tou_weekdays: object = None,
            tou_name: object = None,
        ) -> None:
            self.calls.append(
                (
                    "async_set_cost_settings",
                    (
                        circuit_id,
                        cycle_start_day,
                        default_rate_per_kwh,
                        tou_rate_per_kwh,
                        tou_start,
                        tou_end,
                        tou_weekdays,
                        tou_name,
                    ),
                )
            )

        async def async_set_standby_settings(
            self,
            circuit_id: str,
            window_hours: object = None,
            standby_threshold_w: object = None,
            always_on_alert_w: object = None,
        ) -> None:
            self.calls.append(
                (
                    "async_set_standby_settings",
                    (
                        circuit_id,
                        window_hours,
                        standby_threshold_w,
                        always_on_alert_w,
                    ),
                )
            )

        async def async_set_capacity_settings(
            self,
            circuit_id: str,
            breaker_amps: object = None,
            warning_ratio: object = None,
        ) -> None:
            self.calls.append(
                (
                    "async_set_capacity_settings",
                    (circuit_id, breaker_amps, warning_ratio),
                )
            )

        async def async_set_leg_imbalance_settings(
            self,
            circuit_id: str,
            warning_ratio: object = None,
            minimum_total_power_w: object = None,
        ) -> None:
            self.calls.append(
                (
                    "async_set_leg_imbalance_settings",
                    (circuit_id, warning_ratio, minimum_total_power_w),
                )
            )

        async def async_set_metric_consistency_settings(
            self,
            circuit_id: str,
            apparent_power_tolerance_percent: object = None,
            power_factor_tolerance: object = None,
            minimum_apparent_power_va: object = None,
        ) -> None:
            self.calls.append(
                (
                    "async_set_metric_consistency_settings",
                    (
                        circuit_id,
                        apparent_power_tolerance_percent,
                        power_factor_tolerance,
                        minimum_apparent_power_va,
                    ),
                )
            )

        async def async_set_mains_balance_settings(
            self,
            circuit_id: str,
            negative_tolerance_w: object = None,
        ) -> None:
            self.calls.append(
                (
                    "async_set_mains_balance_settings",
                    (circuit_id, negative_tolerance_w),
                )
            )

        async def async_set_solar_flow_settings(
            self,
            circuit_id: str,
            export_tolerance_w: object = None,
            solar_surplus_threshold_w: object = None,
            high_solar_surplus_threshold_w: object = None,
            flexible_load_running_threshold_w: object = None,
        ) -> None:
            self.calls.append(
                (
                    "async_set_solar_flow_settings",
                    (
                        circuit_id,
                        export_tolerance_w,
                        solar_surplus_threshold_w,
                        high_solar_surplus_threshold_w,
                        flexible_load_running_threshold_w,
                    ),
                )
            )

        async def async_set_utility_comparison_settings(
            self,
            circuit_id: str,
            utility_energy_entity: object = None,
            measured_energy_entities: object = None,
            tolerance_percent: object = None,
            utility_statistic_id: object = None,
            utility_source_type: object = None,
            utility_statistic_period: object = None,
        ) -> None:
            self.calls.append(
                (
                    "async_set_utility_comparison_settings",
                    (
                        circuit_id,
                        utility_energy_entity,
                        measured_energy_entities,
                        tolerance_percent,
                        utility_statistic_id,
                        utility_source_type,
                        utility_statistic_period,
                    ),
                )
            )

        async def async_export_history_csv(self, circuit_id: str) -> None:
            self.calls.append(("async_export_history_csv", (circuit_id,)))

        async def async_start_maintenance(
            self,
            circuit_id: str,
            note: str = "",
            duration: str | None = None,
            relearn_on_end: bool = False,
        ) -> None:
            self.calls.append(
                (
                    "async_start_maintenance",
                    (circuit_id, note, duration, relearn_on_end),
                )
            )

        async def async_end_maintenance(
            self,
            circuit_id: str,
            relearn: bool = False,
        ) -> None:
            self.calls.append(("async_end_maintenance", (circuit_id, relearn)))

        async def async_mark_alert_expected(self, alert_id: str) -> bool:
            self.calls.append(("async_mark_alert_expected", (alert_id,)))
            return True

        async def async_mark_alert_unhelpful(self, alert_id: str) -> bool:
            self.calls.append(("async_mark_alert_unhelpful", (alert_id,)))
            return True

        async def async_mark_nilm_signature_expected(
            self,
            circuit_id: str,
            signature_id: str,
        ) -> None:
            self.calls.append(
                ("async_mark_nilm_signature_expected", (circuit_id, signature_id))
            )

        async def async_merge_nilm_signatures(
            self,
            circuit_id: str,
            source_signature_id: str,
            target_signature_id: str,
        ) -> None:
            self.calls.append(
                (
                    "async_merge_nilm_signatures",
                    (circuit_id, source_signature_id, target_signature_id),
                )
            )

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    await hass.services.registered[(DOMAIN, SERVICE_SET_CIRCUIT_SENSITIVITY)](
        SimpleNamespace(data={"circuit_id": "fridge", "preset": "quiet"})
    )
    await hass.services.registered[(DOMAIN, SERVICE_SET_ENERGY_USAGE_SETTINGS)](
        SimpleNamespace(
            data={
                "circuit_id": "fridge",
                "window_days": 14,
                "daily_spike_ratio": 0.2,
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_SET_ENERGY_GOAL_SETTINGS)](
        SimpleNamespace(
            data={
                "circuit_id": "fridge",
                "daily_goal_kwh": 12.0,
                "goal_alert_ratio": 1.0,
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_SET_DEMAND_SETTINGS)](
        SimpleNamespace(
            data={
                "circuit_id": "fridge",
                "window_minutes": 30,
                "demand_limit_w": 4500.0,
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_SET_ACTIVITY_ALERT_SETTINGS)](
        SimpleNamespace(
            data={
                "circuit_id": "fridge",
                "max_active_minutes": 45,
                "max_idle_minutes": 120,
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_SET_BILLING_CYCLE_SETTINGS)](
        SimpleNamespace(
            data={
                "circuit_id": "fridge",
                "cycle_start_day": 15,
                "budget_kwh": 300.0,
                "budget_alert_ratio": 0.9,
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_SET_COST_SETTINGS)](
        SimpleNamespace(
            data={
                "circuit_id": "fridge",
                "cycle_start_day": 1,
                "default_rate_per_kwh": 0.20,
                "tou_rate_per_kwh": 0.30,
                "tou_start": "17:00",
                "tou_end": "21:00",
                "tou_weekdays": "0,1,2,3,4",
                "tou_name": "Peak",
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_SET_STANDBY_SETTINGS)](
        SimpleNamespace(
            data={
                "circuit_id": "fridge",
                "window_hours": 24,
                "standby_threshold_w": 8.0,
                "always_on_alert_w": 25.0,
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_SET_CAPACITY_SETTINGS)](
        SimpleNamespace(
            data={
                "circuit_id": "fridge",
                "breaker_amps": 20.0,
                "warning_ratio": 0.8,
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_SET_LEG_IMBALANCE_SETTINGS)](
        SimpleNamespace(
            data={
                "circuit_id": "hvac",
                "warning_ratio": 0.4,
                "minimum_total_power_w": 800.0,
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_SET_METRIC_CONSISTENCY_SETTINGS)](
        SimpleNamespace(
            data={
                "circuit_id": "hvac",
                "apparent_power_tolerance_percent": 12.0,
                "power_factor_tolerance": 0.08,
                "minimum_apparent_power_va": 120.0,
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_SET_MAINS_BALANCE_SETTINGS)](
        SimpleNamespace(
            data={
                "circuit_id": "mains",
                "negative_tolerance_w": 250.0,
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_SET_SOLAR_FLOW_SETTINGS)](
        SimpleNamespace(
            data={
                "circuit_id": "mains",
                "export_tolerance_w": 150.0,
                "solar_surplus_threshold_w": 750.0,
                "high_solar_surplus_threshold_w": 2000.0,
                "flexible_load_running_threshold_w": 175.0,
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_SET_UTILITY_COMPARISON_SETTINGS)](
        SimpleNamespace(
            data={
                "circuit_id": "mains",
                "utility_energy_entity": "sensor.opower_current_bill_usage",
                "utility_statistic_id": "opower:utility_elec_consumption",
                "utility_source_type": "auto",
                "utility_statistic_period": "day",
                "measured_energy_entities": ["sensor.panel_import_energy"],
                "tolerance_percent": 8.5,
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_EXPORT_HISTORY_CSV)](
        SimpleNamespace(data={"circuit_id": "fridge"})
    )
    await hass.services.registered[(DOMAIN, SERVICE_START_MAINTENANCE)](
        SimpleNamespace(
            data={
                "circuit_id": "fridge",
                "note": "Changed filter",
                "duration": "02:00:00",
                "relearn_on_end": True,
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_END_MAINTENANCE)](
        SimpleNamespace(data={"circuit_id": "fridge", "relearn": True})
    )
    await hass.services.registered[(DOMAIN, SERVICE_MARK_ALERT_EXPECTED)](
        SimpleNamespace(data={"alert_id": "alert-1"})
    )
    await hass.services.registered[(DOMAIN, SERVICE_MARK_ALERT_UNHELPFUL)](
        SimpleNamespace(data={"alert_id": "alert-2"})
    )
    await hass.services.registered[(DOMAIN, SERVICE_MARK_NILM_SIGNATURE_EXPECTED)](
        SimpleNamespace(data={"circuit_id": "mains", "signature_id": "signature_1"})
    )
    await hass.services.registered[(DOMAIN, SERVICE_MERGE_NILM_SIGNATURES)](
        SimpleNamespace(
            data={
                "circuit_id": "mains",
                "source_signature_id": "signature_2",
                "target_signature_id": "signature_1",
            }
        )
    )

    assert coordinator.calls == [
        ("async_set_circuit_sensitivity", ("fridge", "quiet")),
        ("async_set_energy_usage_settings", ("fridge", 14, 0.2)),
        ("async_set_energy_goal_settings", ("fridge", 12.0, 1.0)),
        ("async_set_demand_settings", ("fridge", 30, 4500.0)),
        ("async_set_activity_alert_settings", ("fridge", 45, 120)),
        ("async_set_billing_cycle_settings", ("fridge", 15, 300.0, 0.9)),
        (
            "async_set_cost_settings",
            ("fridge", 1, 0.20, 0.30, "17:00", "21:00", "0,1,2,3,4", "Peak"),
        ),
        ("async_set_standby_settings", ("fridge", 24, 8.0, 25.0)),
        ("async_set_capacity_settings", ("fridge", 20.0, 0.8)),
        ("async_set_leg_imbalance_settings", ("hvac", 0.4, 800.0)),
        ("async_set_metric_consistency_settings", ("hvac", 12.0, 0.08, 120.0)),
        ("async_set_mains_balance_settings", ("mains", 250.0)),
        (
            "async_set_solar_flow_settings",
            ("mains", 150.0, 750.0, 2000.0, 175.0),
        ),
        (
            "async_set_utility_comparison_settings",
            (
                "mains",
                "sensor.opower_current_bill_usage",
                ["sensor.panel_import_energy"],
                8.5,
                "opower:utility_elec_consumption",
                "auto",
                "day",
            ),
        ),
        ("async_export_history_csv", ("fridge",)),
        ("async_start_maintenance", ("fridge", "Changed filter", "02:00:00", True)),
        ("async_end_maintenance", ("fridge", True)),
        ("async_mark_alert_expected", ("alert-1",)),
        ("async_mark_alert_unhelpful", ("alert-2",)),
        ("async_mark_nilm_signature_expected", ("mains", "signature_1")),
        ("async_merge_nilm_signatures", ("mains", "signature_2", "signature_1")),
    ]


@pytest.mark.asyncio
async def test_set_circuit_sensitivity_service_normalizes_legacy_presets() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_SET_CIRCUIT_SENSITIVITY,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "fridge"

        async def async_set_circuit_sensitivity(
            self,
            circuit_id: str,
            preset: str,
        ) -> None:
            self.calls.append((circuit_id, preset))

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)

    for legacy, canonical in (
        ("low", "quiet"),
        ("standard", "balanced"),
        ("high", "sensitive"),
    ):
        await hass.services.registered[(DOMAIN, SERVICE_SET_CIRCUIT_SENSITIVITY)](
            SimpleNamespace(data={"circuit_id": "fridge", "preset": legacy})
        )
        assert coordinator.calls[-1] == ("fridge", canonical)


@pytest.mark.asyncio
async def test_set_circuit_sensitivity_service_rejects_unknown_preset() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_SET_CIRCUIT_SENSITIVITY,
        HomeAssistantError,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    class FakeCoordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def async_set_updated_data(self, data) -> None:
            return None

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "fridge"

        async def async_set_circuit_sensitivity(
            self,
            circuit_id: str,
            preset: str,
        ) -> None:
            self.calls.append((circuit_id, preset))

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)

    with pytest.raises(HomeAssistantError, match="alert sensitivity"):
        await hass.services.registered[(DOMAIN, SERVICE_SET_CIRCUIT_SENSITIVITY)](
            SimpleNamespace(data={"circuit_id": "fridge", "preset": "noisy"})
        )

    assert coordinator.calls == []


@pytest.mark.asyncio
async def test_service_handlers_mutate_loaded_coordinator_state() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        notification_id_for_alert,
    )
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_ACKNOWLEDGE_ALERT,
        SERVICE_EXPORT_DIAGNOSTICS,
        SERVICE_EXPORT_HISTORY_CSV,
        SERVICE_IGNORE_NILM_SIGNATURE,
        SERVICE_LABEL_NILM_SIGNATURE,
        SERVICE_PAUSE_ALERTS,
        SERVICE_RELEARN_BASELINE,
        SERVICE_RUN_MAPPING_CHECKS,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue",
        feature="real_power",
    )
    store_data = FeatureStoreData(
        baselines={
            "fridge:real_power": BaselineStats(
                "real_power",
                20,
                100.0,
                5.0,
                90.0,
                110.0,
                1.0,
            )
        },
        alerts=[alert],
        energy_usage_by_circuit={
            "fridge": {"days": [{"date": "2026-06-01", "usage_kwh": 8.5}]}
        },
        nilm_signatures={"mains": [{"signature_id": "signature_1"}]},
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        entry_id="entry-1",
        entry_data={},
        store_data=store_data,
    )
    coordinator.state.active_alerts_by_circuit["fridge"] = [alert]
    coordinator.state.anomaly_score_by_circuit["fridge"] = 2.0
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    await hass.services.registered[(DOMAIN, SERVICE_ACKNOWLEDGE_ALERT)](
        SimpleNamespace(data={"alert_id": notification_id_for_alert(alert)})
    )
    await hass.services.registered[(DOMAIN, SERVICE_RELEARN_BASELINE)](
        SimpleNamespace(data={"circuit_id": "fridge"})
    )
    await hass.services.registered[(DOMAIN, SERVICE_PAUSE_ALERTS)](
        SimpleNamespace(data={"circuit_id": "fridge", "duration": "01:00:00"})
    )
    await hass.services.registered[(DOMAIN, SERVICE_EXPORT_DIAGNOSTICS)](
        SimpleNamespace(data={"circuit_id": "fridge"})
    )
    await hass.services.registered[(DOMAIN, SERVICE_EXPORT_HISTORY_CSV)](
        SimpleNamespace(data={"circuit_id": "fridge"})
    )
    await hass.services.registered[(DOMAIN, SERVICE_RUN_MAPPING_CHECKS)](
        SimpleNamespace(data={})
    )
    await hass.services.registered[(DOMAIN, SERVICE_LABEL_NILM_SIGNATURE)](
        SimpleNamespace(
            data={
                "circuit_id": "mains",
                "signature_id": "signature_1",
                "label": "Microwave",
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_IGNORE_NILM_SIGNATURE)](
        SimpleNamespace(data={"circuit_id": "mains", "signature_id": "signature_1"})
    )

    assert "fridge:real_power" not in coordinator.store_data.baselines
    assert "fridge" in coordinator.paused_circuits
    assert coordinator.store_data.alerts == []
    assert coordinator.state.active_alerts_by_circuit == {}
    assert coordinator.last_exported_diagnostics["circuit_id"] == "fridge"
    assert "daily_energy_usage" in coordinator.last_exported_history_csv
    assert coordinator.mapping_checks_run == 1
    assert coordinator.store_data.nilm_signatures["mains"][0]["user_label"] == (
        "Microwave"
    )
    assert ("mains", "signature_1") in coordinator.ignored_nilm_signatures


@pytest.mark.asyncio
async def test_setup_entry_rolls_back_services_when_platform_forwarding_fails() -> None:
    from custom_components.circuitsetup_energy_analyzer import async_setup_entry

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}
            self.removed: list[tuple[str, str]] = []

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

        def async_remove(self, domain, service) -> None:
            self.removed.append((domain, service))
            self.registered.pop((domain, service), None)

    class FakeConfigEntries:
        async def async_forward_entry_setups(self, entry, platforms) -> None:
            raise RuntimeError("forward failed")

    hass = SimpleNamespace(
        data={},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
        config_entries=FakeConfigEntries(),
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={CONF_SOURCE_ENTITIES: ["sensor.fridge_power"]},
    )

    with pytest.raises(RuntimeError, match="forward failed"):
        await async_setup_entry(hass, entry)

    assert hass.data[DOMAIN] == {}
    assert hass.services.registered == {}
    assert hass.services.removed


@pytest.mark.asyncio
async def test_setup_entry_rolls_back_services_when_coordinator_start_fails(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        async_setup_entry,
    )
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered: dict[tuple[str, str], object] = {}
            self.removed: list[tuple[str, str]] = []

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

        def async_remove(self, domain, service) -> None:
            self.removed.append((domain, service))
            self.registered.pop((domain, service), None)

    class FakeConfigEntries:
        async def async_forward_entry_setups(self, entry, platforms) -> None:
            raise AssertionError("platform forwarding should not run")

    async def fail_start(self, source_entities) -> None:
        raise RuntimeError("start failed")

    monkeypatch.setattr(
        coordinator_module.EnergyAnalyzerCoordinator,
        "async_start",
        fail_start,
    )

    hass = SimpleNamespace(
        data={},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
        config_entries=FakeConfigEntries(),
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={CONF_SOURCE_ENTITIES: ["sensor.fridge_power"]},
    )

    with pytest.raises(RuntimeError, match="start failed"):
        await async_setup_entry(hass, entry)

    assert hass.data[DOMAIN] == {}
    assert hass.services.registered == {}
    assert hass.services.removed
