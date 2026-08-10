from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

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


def test_restore_nilm_item_schema_requires_one_scoped_identifier() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        _SERVICE_SCHEMAS,
        SERVICE_RESTORE_NILM_ITEM,
    )

    schema = _SERVICE_SCHEMAS[SERVICE_RESTORE_NILM_ITEM]
    assert (
        schema(
            {
                "entry_id": "entry-1",
                "circuit_id": "mixed",
                "signature_id": "signature-1",
            }
        )["signature_id"]
        == "signature-1"
    )
    for invalid in (
        {"entry_id": "entry-1", "circuit_id": "mixed"},
        {
            "entry_id": "entry-1",
            "circuit_id": "mixed",
            "signature_id": "signature-1",
            "assignment_id": "assignment-1",
        },
        {"circuit_id": "mixed", "signature_id": "signature-1"},
    ):
        with pytest.raises((ValueError, vol.Invalid)):
            schema(invalid)


@pytest.mark.asyncio
async def test_restore_nilm_item_service_targets_only_the_requested_entry() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_RESTORE_NILM_ITEM,
        _dispatch_service,
    )

    first = SimpleNamespace(
        has_circuit=lambda circuit_id: circuit_id == "mixed",
        async_set_updated_data=lambda _state: None,
        async_restore_nilm_item=AsyncMock(),
    )
    second = SimpleNamespace(
        has_circuit=lambda circuit_id: circuit_id == "mixed",
        async_set_updated_data=lambda _state: None,
        async_restore_nilm_item=AsyncMock(),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": first, "entry-2": second}})

    await _dispatch_service(
        hass,
        SERVICE_RESTORE_NILM_ITEM,
        {
            "entry_id": "entry-2",
            "circuit_id": "mixed",
            "assignment_id": "assignment-1",
        },
    )

    first.async_restore_nilm_item.assert_not_awaited()
    second.async_restore_nilm_item.assert_awaited_once_with(
        "mixed",
        assignment_id="assignment-1",
        signature_id=None,
    )


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


def test_nilm_finished_alert_links_to_its_response_view() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_evidence_path,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 8, 5, 12, 30, tzinfo=UTC),
        circuit_id="hvac_2",
        severity=Severity.INFO,
        message="Condensate Pump 2: a detected estimated run ended.",
        feature="nilm_appliance_finished",
        features={
            "assignment_id": "assignment-condensate-pump-2",
            "entry_id": "entry-1",
            "mains_circuit_id": "hvac_2",
            "notification_key": "assignment-condensate-pump-2:session-1",
        },
    )

    path = alert_evidence_path(alert)

    assert "alert_id=" in path
    assert "assignment_id=assignment-condensate-pump-2" in path
    assert "nilm_workspace=" not in path
    assert "appliance_detail=" not in path


def test_alert_notification_message_ends_with_one_evidence_link() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_evidence_path,
    )
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

    expected_order = (
        "**HVAC**",
        "Possible issue: HVAC leg imbalance",
        "Observed value: 62.0",
        "Baseline value: 20.0",
        "Repeated observations: 3",
        "[Open evidence](/circuitsetup-energy-analyzer-evidence?",
    )
    offsets = [message.index(value) for value in expected_order]
    assert offsets == sorted(offsets)
    expected_link = f"[Open evidence]({alert_evidence_path(alert)})"
    assert message.count("[Open evidence](") == 1
    assert message.splitlines()[-1] == expected_link
    assert "Open evidence graph" not in message
    assert "Graph entities" not in message
    assert "sensor.hvac_l1_watts" not in message
    assert "sensor.hvac_l2_current" not in message


@pytest.mark.parametrize(
    ("value_metric", "observed", "baseline", "expected"),
    (
        ("real_power", 125.0, 100.0, "Observed value (Real power): 125 W"),
        ("circuit_capacity", 14.25, 12.0, "Observed value (Circuit capacity): 14.25 A"),
        ("apparent_power", 140.0, 110.0, "Observed value (Apparent power): 140 VA"),
        ("reactive_power", 42.0, 30.0, "Observed value (Reactive power): 42 VAR"),
        ("power_factor", 0.82, 0.95, "Observed value (Power factor): 0.82"),
    ),
)
def test_alert_notification_message_uses_metric_qualifiers(
    value_metric: str,
    observed: float,
    baseline: float,
    expected: str,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        alert_notification_message,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
        circuit_id="appliance",
        severity=Severity.WARNING,
        message="Observed value changed.",
        feature="behavior_change",
        value_metric=value_metric,
        observed_value=observed,
        baseline_value=baseline,
    )

    assert expected in alert_notification_message(alert)


def test_alert_notification_message_adds_nilm_source_and_confidence() -> None:
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        alert_notification_message,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
        circuit_id="mains",
        severity=Severity.INFO,
        message="Dishwasher appears finished.",
        feature="nilm_appliance_finished",
        observed_value=0.45,
        baseline_value=0.8,
        features={
            "source": "nilm",
            "estimated": True,
            "assignment_id": "assignment-dishwasher",
            "confidence": 0.82,
        },
    )
    direct_alert = AlertEvidence(
        timestamp=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
        circuit_id="dishwasher",
        severity=Severity.INFO,
        message="Dishwasher appears finished.",
        feature="activity_finished",
        observed_value=0.45,
        baseline_value=0.8,
    )

    message = alert_notification_message(alert)
    direct_message = alert_notification_message(direct_alert)

    assert message.startswith("**mains**\n\n")
    assert "Estimated from aggregate circuit power by NILM." in message
    assert "Confidence: 82%." in message
    assert "Estimated from aggregate circuit power by NILM." not in direct_message
    assert "Confidence: 82%." not in direct_message


def test_alert_notification_message_explains_appliance_health_evidence() -> None:
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        alert_notification_message,
    )
    from custom_components.circuitsetup_energy_analyzer.safety import (
        ELECTRICAL_SAFETY_NOTICE,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 7, 28, 12, 30, tzinfo=UTC),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue: energy per runtime hour has remained elevated.",
        feature="efficiency_degradation",
        value_metric="energy_per_runtime_hour",
        observed_value=0.52,
        baseline_value=0.4,
        repeated_count=3,
        features={
            "notification_type": "appliance_health_issue",
            "confidence": 0.88,
        },
    )

    message = alert_notification_message(alert)

    assert "Confidence: 88%." in message
    assert "Recent value (Energy per runtime hour): 0.52 kWh/h" in message
    assert "Reference value (Energy per runtime hour): 0.4 kWh/h" in message
    assert (
        "This is an inspection prompt, not a component diagnosis or safety control."
        in message
    )
    assert ELECTRICAL_SAFETY_NOTICE not in message


def test_hvac_runtime_notification_uses_minutes() -> None:
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        alert_notification_message,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 7, 28, 12, 30, tzinfo=UTC),
        circuit_id="heat_pump",
        severity=Severity.WARNING,
        message="HVAC response is slower than normal.",
        feature="hvac_response_slower",
        value_metric="weather_normalized_runtime_minutes",
        observed_value=55.0,
        baseline_value=40.0,
    )

    message = alert_notification_message(alert)

    assert "Recent value (Weather-normalized runtime): 55 min" in message
    assert "Reference value (Weather-normalized runtime): 40 min" in message


def test_power_quality_notification_labels_values_and_limits_interpretation() -> None:
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        alert_notification_message,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
        circuit_id="water_heater",
        severity=Severity.WARNING,
        message=(
            "Possible issue: reactive power changed while real power stayed near "
            "its learned baseline across recent observations."
        ),
        feature="reactive_shift_under_stable_real_power",
        value_metric="reactive_to_real_ratio",
        observed_value=0.14248837235748318,
        baseline_value=0.10285714285714286,
        repeated_count=3,
    )

    message = alert_notification_message(alert)

    assert "Observed value (Reactive-to-real power ratio): 14.249%" in message
    assert "Baseline value (Reactive-to-real power ratio): 10.286%" in message
    assert "not an electrical safety diagnosis" in message


def test_alert_notification_message_ignores_non_finite_nilm_confidence() -> None:
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        alert_notification_message,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
        circuit_id="mains",
        severity=Severity.INFO,
        message="Dishwasher appears finished.",
        feature="nilm_appliance_finished",
        observed_value=0.45,
        baseline_value=0.8,
        features={
            "source": "nilm",
            "assignment_id": "assignment-dishwasher",
            "confidence": float("nan"),
        },
    )

    message = alert_notification_message(alert)

    assert "Estimated from aggregate circuit power by NILM." in message
    assert "Confidence:" not in message


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
    assert "Observed value (Demand monthly peak): 4100 W" in message


@pytest.mark.asyncio
async def test_daily_summary_describes_historical_observed_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import notifications

    calls: list[dict[str, object]] = []

    def fake_create(hass, message, *, title, notification_id):
        calls.append(
            {
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
        timestamp=datetime(2026, 7, 13, 12, tzinfo=UTC),
        circuit_id="dryer",
        severity=Severity.WARNING,
        message="Dryer energy changed",
        feature="daily_energy_spike",
    )

    await notifications.async_create_daily_summary_notification(
        SimpleNamespace(),
        [alert],
        summary_date="2026-07-13",
    )

    assert calls[0]["title"] == "Daily Appliance Summary"
    assert "Alerts observed on 2026-07-13." in str(calls[0]["message"])


@pytest.mark.asyncio
async def test_weekly_digest_notification_renders_every_non_empty_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import notifications

    messages: list[str] = []

    def fake_create(hass, message, *, title, notification_id):
        del hass, title, notification_id
        messages.append(str(message))

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
    digest = SimpleNamespace(
        week_start=date(2026, 7, 6),
        week_end=date(2026, 7, 12),
        biggest_changes=(SimpleNamespace(display_name="Dryer", change_ratio=0.25),),
        top_energy_users=(SimpleNamespace(display_name="EV Charger", energy_kwh=42.0),),
        observed_alerts=(SimpleNamespace(display_name="Dishwasher"),),
        unresolved_items=(SimpleNamespace(display_name="Refrigerator"),),
        nilm_review_items=(SimpleNamespace(display_name="Dehumidifier"),),
        load_shift_opportunities=(SimpleNamespace(display_name="Water Heater"),),
    )

    await notifications.async_create_weekly_digest_notification(
        SimpleNamespace(),
        digest,
    )

    message = messages[0]
    assert "**Observed alerts**" in message
    assert "**Unresolved items**" in message
    assert "**NILM review**" in message
    assert "**Load-shifting opportunities**" in message
    for display_name in (
        "Dryer",
        "EV Charger",
        "Dishwasher",
        "Refrigerator",
        "Dehumidifier",
        "Water Heater",
    ):
        assert message.count(display_name) == 1

    digest.observed_alerts = ()
    await notifications.async_create_weekly_digest_notification(
        SimpleNamespace(),
        digest,
    )
    assert "**Observed alerts**" not in messages[1]


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


def test_alert_notification_message_marks_nilm_as_not_safety_evidence() -> None:
    from custom_components.circuitsetup_energy_analyzer.notifications import (
        alert_notification_message,
    )
    from custom_components.circuitsetup_energy_analyzer.safety import (
        ELECTRICAL_SAFETY_NOTICE,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
        circuit_id="mains",
        severity=Severity.INFO,
        message=(
            "Dishwasher appears finished. Estimated from aggregate circuit power "
            "by NILM."
        ),
        feature="nilm_appliance_finished",
        observed_value=0.8,
        baseline_value=0.8,
    )

    message = alert_notification_message(alert)

    assert ELECTRICAL_SAFETY_NOTICE in message


def test_repair_issue_id_for_circuit_problem_is_stable() -> None:
    from custom_components.circuitsetup_energy_analyzer.repairs import (
        issue_id_for_circuit_problem,
    )

    issue_id = issue_id_for_circuit_problem("mains", "missing_source_entities")
    assert issue_id.startswith(f"{DOMAIN}_mains_missing_source_entities_")
    assert issue_id == issue_id_for_circuit_problem("mains", "missing_source_entities")


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


@pytest.mark.parametrize(
    ("schema_name", "data"),
    (
        ("NILM_LABEL_SERVICE_SCHEMA", {"signature_id": "signature", "label": "Load"}),
        (
            "NILM_LABEL_INTERVAL_SERVICE_SCHEMA",
            {
                "label": "Load",
                "start": "2026-06-02T12:00:00+00:00",
                "end": "2026-06-02T12:30:00+00:00",
            },
        ),
        ("NILM_DELETE_LABEL_INTERVAL_SERVICE_SCHEMA", {"interval_id": "interval"}),
        (
            "NILM_SENSOR_LABEL_INTERVAL_SERVICE_SCHEMA",
            {
                "label": "Load",
                "start": "2026-06-02T12:00:00+00:00",
                "end": "2026-06-02T12:30:00+00:00",
                "ground_truth_entity_id": "sensor.load",
            },
        ),
        (
            "NILM_ASSIGN_SIGNATURE_SERVICE_SCHEMA",
            {"signature_id": "signature", "label": "Load"},
        ),
        (
            "NILM_ASSIGN_SESSION_SERVICE_SCHEMA",
            {"session_id": "session", "label": "Load"},
        ),
        (
            "NILM_ASSIGN_INTERVAL_SERVICE_SCHEMA",
            {"interval_id": "interval", "label": "Load"},
        ),
        ("NILM_SESSION_VALIDATION_SERVICE_SCHEMA", {"session_id": "session"}),
        (
            "NILM_RENAME_APPLIANCE_SERVICE_SCHEMA",
            {"assignment_id": "assignment", "label": "Load"},
        ),
        (
            "NILM_CHANGE_APPLIANCE_PROFILE_SERVICE_SCHEMA",
            {"assignment_id": "assignment", "appliance_profile": "other"},
        ),
        (
            "NILM_DIRECT_METER_CONVERSION_SERVICE_SCHEMA",
            {"assignment_id": "assignment", "direct_circuit_id": "direct"},
        ),
        (
            "NILM_MERGE_ASSIGNMENTS_SERVICE_SCHEMA",
            {"source_assignment_id": "source", "target_assignment_id": "target"},
        ),
        ("NILM_ASSIGNMENT_ACTION_SERVICE_SCHEMA", {"assignment_id": "assignment"}),
        ("NILM_SIGNATURE_SERVICE_SCHEMA", {"signature_id": "signature"}),
        (
            "NILM_MERGE_SERVICE_SCHEMA",
            {"source_signature_id": "source", "target_signature_id": "target"},
        ),
    ),
)
def test_nilm_mutation_schemas_accept_entry_id(
    schema_name: str, data: dict[str, str]
) -> None:
    """Catches schemas that reject workspace entry-scoped NILM actions."""
    from custom_components.circuitsetup_energy_analyzer import services

    schema = getattr(services, schema_name)
    assert any(getattr(field, "schema", field) == "entry_id" for field in schema.schema)
    assert schema({**data, "entry_id": "entry-2"})["entry_id"] == "entry-2"


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


def test_nilm_sensor_label_interval_schema_accepts_generation_fields() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        NILM_SENSOR_LABEL_INTERVAL_SERVICE_SCHEMA,
    )

    data = NILM_SENSOR_LABEL_INTERVAL_SERVICE_SCHEMA(
        {
            "circuit_id": "mains",
            "label": "Dishwasher",
            "start": "2026-06-02T12:00:00+00:00",
            "end": "2026-06-02T14:00:00+00:00",
            "ground_truth_entity_id": "sensor.dishwasher_power",
            "assignment_id": "assignment-dishwasher",
            "threshold_w": 25,
        }
    )

    assert data["ground_truth_entity_id"] == "sensor.dishwasher_power"
    assert data["assignment_id"] == "assignment-dishwasher"
    assert data["threshold_w"] == 25


def test_nilm_sensor_label_interval_schema_accepts_stored_assignment_link() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        NILM_SENSOR_LABEL_INTERVAL_SERVICE_SCHEMA,
    )

    assert NILM_SENSOR_LABEL_INTERVAL_SERVICE_SCHEMA(
        {
            "circuit_id": "mains",
            "assignment_id": "assignment-dishwasher",
            "label": "Dishwasher",
            "start": "2026-06-02T12:00:00+00:00",
            "end": "2026-06-02T14:00:00+00:00",
        }
    )["assignment_id"] == "assignment-dishwasher"


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


def test_nilm_sensor_history_rows_generate_label_intervals() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        _nilm_sensor_label_intervals_from_history,
    )

    intervals = _nilm_sensor_label_intervals_from_history(
        [
            [
                {
                    "entity_id": "sensor.dishwasher_power",
                    "state": "0",
                    "last_changed": "2026-06-02T12:00:00+00:00",
                },
                {
                    "entity_id": "sensor.dishwasher_power",
                    "state": "80",
                    "last_changed": "2026-06-02T12:05:00+00:00",
                },
                {
                    "entity_id": "sensor.dishwasher_power",
                    "state": "82",
                    "last_changed": "2026-06-02T12:35:00+00:00",
                },
                {
                    "entity_id": "sensor.dishwasher_power",
                    "state": "3",
                    "last_changed": "2026-06-02T12:45:00+00:00",
                },
            ]
        ],
        "sensor.dishwasher_power",
        start="2026-06-02T12:00:00+00:00",
        end="2026-06-02T13:00:00+00:00",
        threshold_w=25,
    )

    assert intervals == [
        {
            "start": "2026-06-02T12:05:00+00:00",
            "end": "2026-06-02T12:45:00+00:00",
            "validation_start": "2026-06-02T12:00:00+00:00",
            "validation_end": "2026-06-02T13:00:00+00:00",
        }
    ]


def test_nilm_reference_intervals_generate_from_on_off_history() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        _nilm_reference_intervals_from_history,
    )

    intervals = _nilm_reference_intervals_from_history(
        [
            [
                {
                    "entity_id": "switch.dishwasher",
                    "state": "off",
                    "last_changed": "2026-08-01T00:00:00+00:00",
                },
                {
                    "entity_id": "switch.dishwasher",
                    "state": "on",
                    "last_changed": "2026-08-01T00:10:00+00:00",
                },
                {
                    "entity_id": "switch.dishwasher",
                    "state": "off",
                    "last_changed": "2026-08-01T00:40:00+00:00",
                },
            ]
        ],
        "switch.dishwasher",
        start="2026-08-01T00:00:00+00:00",
        end="2026-08-01T02:00:00+00:00",
    )

    assert intervals == [
        {
            "start": "2026-08-01T00:10:00+00:00",
            "end": "2026-08-01T00:40:00+00:00",
            "validation_start": "2026-08-01T00:00:00+00:00",
            "validation_end": "2026-08-01T02:00:00+00:00",
        }
    ]


def test_nilm_reference_intervals_do_not_fabricate_a_boundary_across_unknown_history(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        _nilm_reference_intervals_from_history,
    )

    intervals = _nilm_reference_intervals_from_history(
        [
            [
                {
                    "entity_id": "binary_sensor.dishwasher",
                    "state": "on",
                    "last_changed": "2026-08-01T00:10:00+00:00",
                },
                {
                    "entity_id": "binary_sensor.dishwasher",
                    "state": "unknown",
                    "last_changed": "2026-08-01T00:20:00+00:00",
                },
                {
                    "entity_id": "binary_sensor.dishwasher",
                    "state": "unavailable",
                    "last_changed": "2026-08-01T00:30:00+00:00",
                },
                {
                    "entity_id": "binary_sensor.dishwasher",
                    "state": "on",
                    "last_changed": "2026-08-01T00:40:00+00:00",
                },
                {
                    "entity_id": "binary_sensor.dishwasher",
                    "state": "off",
                    "last_changed": "2026-08-01T00:50:00+00:00",
                },
            ]
        ],
        "binary_sensor.dishwasher",
        start="2026-08-01T00:00:00+00:00",
        end="2026-08-01T01:00:00+00:00",
    )

    assert [(item["start"], item["end"]) for item in intervals] == [
        ("2026-08-01T00:40:00+00:00", "2026-08-01T00:50:00+00:00"),
    ]

    with pytest.raises(Exception, match="threshold"):
        _nilm_reference_intervals_from_history(
            [],
            "binary_sensor.dishwasher",
            start="2026-08-01T00:00:00+00:00",
            end="2026-08-01T01:00:00+00:00",
            threshold_w=-1,
        )


def test_nilm_reference_history_calculates_measured_power_and_energy() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        _nilm_reference_interval_id,
        _nilm_reference_power_metrics,
    )

    rows = [
        [
            {
                "entity_id": "sensor.pump_power",
                "state": state,
                "last_changed": timestamp,
            }
            for state, timestamp in (
                ("80", "2026-08-01T00:10:00+00:00"),
                ("100", "2026-08-01T00:20:00+00:00"),
                ("80", "2026-08-01T00:40:00+00:00"),
            )
        ]
    ]

    metrics = _nilm_reference_power_metrics(
        rows,
        "sensor.pump_power",
        start="2026-08-01T00:10:00+00:00",
        end="2026-08-01T00:40:00+00:00",
        unit="W",
    )
    assert metrics["power_coverage"] == 0.0
    assert "measured_energy_kwh" not in metrics
    interval_id = _nilm_reference_interval_id(
        "mixed",
        "assignment-pump",
        "switch.pump",
        "2026-08-01T00:10:00+00:00",
        "2026-08-01T00:40:00+00:00",
    )
    assert interval_id == _nilm_reference_interval_id(
        "mixed",
        "assignment-pump",
        "switch.pump",
        "2026-08-01T00:10:00+00:00",
        "2026-08-01T00:40:00+00:00",
    )
    assert interval_id.startswith("reference-")

    metrics = _nilm_reference_power_metrics(
        [
            [
                {
                    "entity_id": "sensor.pump_power",
                    "state": state,
                    "last_changed": timestamp,
                }
                for state, timestamp in (
                    ("80", "2026-08-01T00:10:00+00:00"),
                    ("unknown", "2026-08-01T00:20:00+00:00"),
                    ("80", "2026-08-01T00:40:00+00:00"),
                )
            ]
        ],
        "sensor.pump_power",
        start="2026-08-01T00:10:00+00:00",
        end="2026-08-01T00:40:00+00:00",
        unit="W",
    )
    assert metrics["power_coverage"] == 0.0
    assert "measured_energy_kwh" not in metrics


@pytest.mark.asyncio
async def test_nilm_reference_history_service_attaches_measured_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import services

    history = AsyncMock(
        side_effect=[
            [
                [
                    {
                        "entity_id": "switch.pump",
                        "state": "on",
                        "last_changed": "2026-08-01T00:10:00+00:00",
                    },
                    {
                        "entity_id": "switch.pump",
                        "state": "off",
                        "last_changed": "2026-08-01T00:40:00+00:00",
                    },
                ]
            ],
            [
                [
                    {
                        "entity_id": "sensor.pump_power",
                        "state": "80",
                        "last_changed": "2026-08-01T00:10:00+00:00",
                    },
                    {
                        "entity_id": "sensor.pump_power",
                        "state": "80",
                        "last_changed": "2026-08-01T00:40:00+00:00",
                    },
                ]
            ],
        ]
    )
    monkeypatch.setattr(services, "_async_nilm_sensor_history_rows", history)
    coordinator = SimpleNamespace(
        async_set_updated_data=lambda _: None,
        circuit_configs=[SimpleNamespace(circuit_id="mixed")],
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [
                    {
                        "assignment_id": "assignment-pump",
                        "reference_threshold_w": 25.0,
                        "reference_maximum_power_gap_seconds": 3600.0,
                    }
                ]
            }
        ),
        async_save_nilm_interval_changes=AsyncMock(),
    )
    other = SimpleNamespace(
        circuit_configs=[SimpleNamespace(circuit_id="mixed")],
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [{"assignment_id": "assignment-other"}]
            }
        ),
        async_save_nilm_interval_changes=AsyncMock(),
    )
    power_state = SimpleNamespace(
        state="80",
        attributes={"device_class": "power", "unit_of_measurement": "W"},
    )
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator, "entry-2": other}},
        states=SimpleNamespace(get=lambda entity_id: power_state),
    )

    await services._dispatch_service(
        hass,
        services.SERVICE_GENERATE_NILM_SENSOR_LABEL_INTERVALS,
        {
            "circuit_id": "mixed",
            "assignment_id": "assignment-pump",
            "label": "Pump",
            "start": "2026-08-01T00:00:00+00:00",
            "end": "2026-08-01T01:00:00+00:00",
            "ground_truth_entity_id": "switch.pump",
            "reference_power_entity_id": "sensor.pump_power",
        },
    )

    kwargs = coordinator.async_save_nilm_interval_changes.await_args.kwargs
    draft = kwargs["intervals"][0]
    assert kwargs["assignment_id"] == "assignment-pump"
    assert draft["source"] == "reference_sensor"
    assert draft["evidence"]["evidence_source"] == "reference_backend"
    assert draft["evidence"]["median_power_w"] == 80.0
    assert draft["evidence"]["measured_energy_kwh"] == 0.04
    assert draft["evidence"]["state_coverage"] == 1.0
    assert draft["evidence"]["resolved_reference_settings"] == {
        "on_threshold": 25.0,
        "off_threshold": 25.0,
        "on_dwell_seconds": 0.0,
        "off_dwell_seconds": 0.0,
        "minimum_interval_seconds": 0.0,
        "merge_gap_seconds": 0.0,
        "maximum_unknown_gap_seconds": 0.0,
        "maximum_power_gap_seconds": 3600.0,
    }
    assert draft["interval_id"].startswith("reference-")
    other.async_save_nilm_interval_changes.assert_not_awaited()


@pytest.mark.asyncio
async def test_nilm_reference_history_service_preserves_pre_window_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import services

    history = AsyncMock(
        return_value=[
            [
                {
                    "entity_id": "switch.pump",
                    "state": "on",
                    "last_changed": "2026-07-31T23:55:00+00:00",
                },
                {
                    "entity_id": "switch.pump",
                    "state": "off",
                    "last_changed": "2026-08-01T00:10:00+00:00",
                },
            ]
        ]
    )
    monkeypatch.setattr(services, "_async_nilm_sensor_history_rows", history)
    coordinator = SimpleNamespace(
        async_set_updated_data=lambda _: None,
        circuit_configs=[SimpleNamespace(circuit_id="mixed")],
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [
                    {
                        "assignment_id": "assignment-pump",
                        "reference_state_entity_id": "switch.pump",
                    }
                ]
            }
        ),
        async_save_nilm_interval_changes=AsyncMock(),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    await services._dispatch_service(
        hass,
        services.SERVICE_GENERATE_NILM_SENSOR_LABEL_INTERVALS,
        {
            "circuit_id": "mixed",
            "assignment_id": "assignment-pump",
            "label": "Pump",
            "start": "2026-08-01T00:00:00+00:00",
            "end": "2026-08-01T01:00:00+00:00",
        },
    )

    assert history.await_args.kwargs["include_start_time_state"] is True
    draft = coordinator.async_save_nilm_interval_changes.await_args.kwargs[
        "intervals"
    ][0]
    assert draft["start"] == "2026-08-01T00:00:00+00:00"
    assert draft["evidence"]["left_censored"] is True


@pytest.mark.asyncio
async def test_nilm_reference_import_explicit_fields_override_stored_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import services

    history = AsyncMock(
        side_effect=[
            [
                [
                    {
                        "entity_id": "switch.explicit",
                        "state": "on",
                        "last_changed": "2026-08-01T00:10:00+00:00",
                    },
                    {
                        "entity_id": "switch.explicit",
                        "state": "off",
                        "last_changed": "2026-08-01T00:40:00+00:00",
                    },
                ]
            ],
            [
                [
                    {
                        "entity_id": "sensor.explicit_power",
                        "state": "80",
                        "last_changed": "2026-08-01T00:10:00+00:00",
                    },
                    {
                        "entity_id": "sensor.explicit_power",
                        "state": "80",
                        "last_changed": "2026-08-01T00:40:00+00:00",
                    },
                ]
            ],
        ]
    )
    monkeypatch.setattr(services, "_async_nilm_sensor_history_rows", history)
    coordinator = SimpleNamespace(
        async_set_updated_data=lambda _: None,
        circuit_configs=[SimpleNamespace(circuit_id="mixed")],
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [
                    {
                        "assignment_id": "assignment-pump",
                        "reference_state_entity_id": "switch.stored",
                        "reference_power_entity_id": "sensor.stored_power",
                        "reference_on_threshold": 100.0,
                        "reference_off_threshold": 80.0,
                        "reference_maximum_power_gap_seconds": 3600.0,
                    }
                ]
            }
        ),
        async_save_nilm_interval_changes=AsyncMock(),
    )
    power_state = SimpleNamespace(
        state="80",
        attributes={"device_class": "power", "unit_of_measurement": "W"},
    )
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        states=SimpleNamespace(get=lambda _entity_id: power_state),
    )

    await services._dispatch_service(
        hass,
        services.SERVICE_GENERATE_NILM_SENSOR_LABEL_INTERVALS,
        {
            "circuit_id": "mixed",
            "assignment_id": "assignment-pump",
            "label": "Pump",
            "start": "2026-08-01T00:00:00+00:00",
            "end": "2026-08-01T01:00:00+00:00",
            "ground_truth_entity_id": "switch.explicit",
            "reference_power_entity_id": "sensor.explicit_power",
            "threshold_w": 25.0,
        },
    )

    assert [call.args[1] for call in history.await_args_list] == [
        "switch.explicit",
        "sensor.explicit_power",
    ]
    evidence = coordinator.async_save_nilm_interval_changes.await_args.kwargs[
        "intervals"
    ][0]["evidence"]
    assert evidence["ground_truth_entity_id"] == "switch.explicit"
    assert evidence["reference_power_entity_id"] == "sensor.explicit_power"
    assert evidence["resolved_reference_settings"]["on_threshold"] == 25.0
    assert evidence["resolved_reference_settings"]["off_threshold"] == 25.0


def _manual_evidence_config(*sensors: SensorRef) -> CircuitConfig:
    return CircuitConfig(
        circuit_id="mains",
        name="Mains",
        appliance_profile=ApplianceProfile.MAINS_NILM,
        mode=CircuitMode.MAINS_NILM,
        sensors=sensors,
    )


def _manual_evidence_rows(entity_id: str) -> list[list[dict[str, str]]]:
    return [
        [
            {
                "entity_id": entity_id,
                "state": "100",
                "last_changed": "2026-08-01T00:00:00+00:00",
            },
            {
                "entity_id": entity_id,
                "state": "200",
                "last_changed": "2026-08-01T00:00:20+00:00",
            },
            {
                "entity_id": entity_id,
                "state": "200",
                "last_changed": "2026-08-01T00:01:40+00:00",
            },
            {
                "entity_id": entity_id,
                "state": "100",
                "last_changed": "2026-08-01T00:02:00+00:00",
            },
        ]
    ]


def test_manual_power_sources_normalize_case_varied_units() -> None:
    """Catches valid real-power source units being dropped due to unit casing."""
    from custom_components.circuitsetup_energy_analyzer.services import (
        _configured_manual_power_sources,
    )

    config = _manual_evidence_config(
        SensorRef("sensor.configured_kw", SensorRole.REAL_POWER, unit="kw"),
        SensorRef("sensor.configured_milli", SensorRole.REAL_POWER, unit="mW"),
        SensorRef("sensor.configured_mega", SensorRole.REAL_POWER, unit="MW"),
        SensorRef("sensor.metadata", SensorRole.REAL_POWER),
    )
    hass = SimpleNamespace(
        states=SimpleNamespace(
            get=lambda entity_id: SimpleNamespace(
                attributes={
                    "device_class": "power",
                    "unit_of_measurement": (
                        "KW" if entity_id == "sensor.metadata" else ""
                    ),
                }
            )
        )
    )
    coordinator = SimpleNamespace(circuit_configs=[config])

    assert _configured_manual_power_sources(hass, coordinator, "mains") == (
        ("sensor.configured_kw", 1_000.0),
        ("sensor.configured_milli", 0.001),
        ("sensor.configured_mega", 1_000_000.0),
        ("sensor.metadata", 1_000.0),
    )


@pytest.mark.asyncio
async def test_manual_label_uses_configured_power_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches browser-supplied electrical claims bypassing recorder evidence."""
    from custom_components.circuitsetup_energy_analyzer import services

    history = AsyncMock(return_value=_manual_evidence_rows("sensor.configured_power"))
    monkeypatch.setattr(services, "_async_nilm_sensor_history_rows", history)
    coordinator = SimpleNamespace(
        circuit_configs=[
            _manual_evidence_config(
                SensorRef("sensor.configured_power", SensorRole.REAL_POWER, unit="W")
            )
        ],
        async_set_updated_data=lambda _: None,
        async_label_nilm_interval=AsyncMock(),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    await services._dispatch_service(
        hass,
        services.SERVICE_LABEL_NILM_INTERVAL,
        {
            "entry_id": "entry-1",
            "circuit_id": "mains",
            "label": "Load",
            "start": "2026-08-01T00:00:20+00:00",
            "end": "2026-08-01T00:01:40+00:00",
            "mains_entity_id": "sensor.browser_claim",
            "observed_transition_w": 9999,
        },
    )

    kwargs = coordinator.async_label_nilm_interval.await_args.kwargs
    assert history.await_args.args[1] == "sensor.configured_power"
    assert "observed_transition_w" not in kwargs
    assert kwargs["evidence"]["start_transition_w"] == 100.0
    assert kwargs["evidence"]["evidence_source"] == "manual_backend"


@pytest.mark.asyncio
async def test_manual_batch_fetches_each_configured_source_once_for_union_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches per-interval recorder queries that make atomic batch saves expensive."""
    from custom_components.circuitsetup_energy_analyzer import services

    history = AsyncMock(
        side_effect=[
            _manual_evidence_rows("sensor.leg_a"),
            _manual_evidence_rows("sensor.leg_b"),
        ]
    )
    monkeypatch.setattr(services, "_async_nilm_sensor_history_rows", history)
    coordinator = SimpleNamespace(
        circuit_configs=[
            _manual_evidence_config(
                SensorRef("sensor.leg_a", SensorRole.REAL_POWER, unit="W"),
                SensorRef("sensor.leg_b", SensorRole.REAL_POWER, unit="W"),
            )
        ],
        async_set_updated_data=lambda _: None,
        async_save_nilm_interval_changes=AsyncMock(),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    intervals = [
        {
            "interval_id": "one",
            "start": "2026-08-01T00:00:20+00:00",
            "end": "2026-08-01T00:01:40+00:00",
            "observed_transition_w": 9999,
        },
        {
            "interval_id": "two",
            "start": "2026-08-01T00:03:20+00:00",
            "end": "2026-08-01T00:04:40+00:00",
            "median_power_w": 9999,
        },
    ]

    await services._dispatch_service(
        hass,
        services.SERVICE_SAVE_NILM_INTERVAL_CHANGES,
        {
            "entry_id": "entry-1",
            "circuit_id": "mains",
            "label": "Load",
            "intervals": intervals,
        },
    )

    assert history.await_count == 2
    assert {call.args[1] for call in history.await_args_list} == {
        "sensor.leg_a",
        "sensor.leg_b",
    }
    assert {
        (call.args[2], call.args[3]) for call in history.await_args_list
    } == {
        (
            datetime(2026, 7, 31, 23, 59, 20, tzinfo=UTC),
            datetime(2026, 8, 1, 0, 5, 40, tzinfo=UTC),
        )
    }
    saved = coordinator.async_save_nilm_interval_changes.await_args.kwargs["intervals"]
    assert all(
        "evidence" in draft
        and "observed_transition_w" not in draft
        and "median_power_w" not in draft
        for draft in saved
    )


@pytest.mark.asyncio
async def test_manual_history_unavailable_saves_review_only_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches unavailable history becoming fabricated measured evidence."""
    from custom_components.circuitsetup_energy_analyzer import services

    monkeypatch.setattr(
        services, "_async_nilm_sensor_history_rows", AsyncMock(return_value=[])
    )
    coordinator = SimpleNamespace(
        circuit_configs=[
            _manual_evidence_config(
                SensorRef("sensor.mains", SensorRole.REAL_POWER, unit="W")
            )
        ],
        async_set_updated_data=lambda _: None,
        async_label_nilm_interval=AsyncMock(),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    await services._dispatch_service(
        hass,
        services.SERVICE_LABEL_NILM_INTERVAL,
        {
            "entry_id": "entry-1",
            "circuit_id": "mains",
            "label": "Load",
            "start": "2026-08-01T00:00:00+00:00",
            "end": "2026-08-01T00:01:00+00:00",
        },
    )

    evidence = coordinator.async_label_nilm_interval.await_args.kwargs["evidence"]
    assert evidence["evidence_confidence"] == 0.0
    assert evidence["measured_energy_kwh"] is None
    assert evidence["start_transition_w"] is None
    assert evidence["start_transition_eligible"] is False
    assert "history_unavailable" in evidence["quality_flags"]


@pytest.mark.asyncio
async def test_manual_evidence_excludes_non_real_or_incompatible_configured_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches apparent-power and unsupported-unit sensors entering trusted evidence."""
    from custom_components.circuitsetup_energy_analyzer import services

    history = AsyncMock(return_value=_manual_evidence_rows("sensor.real"))
    monkeypatch.setattr(services, "_async_nilm_sensor_history_rows", history)
    coordinator = SimpleNamespace(
        circuit_configs=[
            _manual_evidence_config(
                SensorRef("sensor.real", SensorRole.REAL_POWER, unit="kW"),
                SensorRef("sensor.apparent", SensorRole.APPARENT_POWER, unit="VA"),
                SensorRef("sensor.bad", SensorRole.REAL_POWER, unit="VA"),
            )
        ],
        async_set_updated_data=lambda _: None,
        async_label_nilm_interval=AsyncMock(),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    await services._dispatch_service(
        hass,
        services.SERVICE_LABEL_NILM_INTERVAL,
        {
            "entry_id": "entry-1",
            "circuit_id": "mains",
            "label": "Load",
            "start": "2026-08-01T00:00:20+00:00",
            "end": "2026-08-01T00:01:40+00:00",
        },
    )

    assert history.await_count == 1
    assert history.await_args.args[1] == "sensor.real"


def test_nilm_assignment_service_schemas_validate_required_fields() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        NILM_ASSIGN_INTERVAL_SERVICE_SCHEMA,
        NILM_ASSIGN_SESSION_SERVICE_SCHEMA,
        NILM_ASSIGN_SIGNATURE_SERVICE_SCHEMA,
    )

    assert (
        NILM_ASSIGN_SIGNATURE_SERVICE_SCHEMA(
            {
                "circuit_id": "mains",
                "signature_id": "signature_1",
                "label": "Dishwasher",
                "appliance_id": "dishwasher",
            }
        )["label"]
        == "Dishwasher"
    )
    assert (
        NILM_ASSIGN_SESSION_SERVICE_SCHEMA(
            {
                "circuit_id": "mains",
                "session_id": "session_1",
                "signature_fingerprint": "fingerprint_1",
                "label": "Dishwasher",
            }
        )["session_id"]
        == "session_1"
    )
    assert (
        NILM_ASSIGN_INTERVAL_SERVICE_SCHEMA(
            {
                "circuit_id": "mains",
                "interval_id": "label-1",
                "label": "Dishwasher",
            }
        )["interval_id"]
        == "label-1"
    )

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

    assert SENSITIVITY_SERVICE_SCHEMA({"circuit_id": "fridge", "preset": "quiet"}) == {
        "circuit_id": "fridge",
        "preset": "quiet",
    }
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
    ) == {"entity_id": "sensor.fridge_health_summary"}
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
    assert "mark_nilm_signature_expected" not in _SERVICE_SCHEMAS
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
    assert RECALCULATE_RECOMMENDATIONS_SERVICE_SCHEMA({"circuit_id": "fridge"}) == {
        "circuit_id": "fridge"
    }
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
        MARK_CIRCUIT_MIXED_SERVICE_SCHEMA,
        SERVICE_APPLY_SETTING_RECOMMENDATION,
        SERVICE_DENY_SETTING_RECOMMENDATION,
        SERVICE_DISMISS_SETTING_RECOMMENDATION,
        SERVICE_MARK_CIRCUIT_MIXED,
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
    assert hass.services.registered[(DOMAIN, SERVICE_MARK_CIRCUIT_MIXED)][1] is (
        MARK_CIRCUIT_MIXED_SERVICE_SCHEMA
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
        match=("circuit_id 'hvac' does not match entity_id target circuit 'fridge'"),
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
            "Could not derive circuit_id from entity_id 'sensor.unknown_health_summary'"
        ),
    ):
        await hass.services.registered[(DOMAIN, SERVICE_RELEARN_BASELINE)](
            SimpleNamespace(data={"entity_id": "sensor.unknown_health_summary"})
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
async def test_setting_recommendation_services_require_unique_or_explicit_entry() -> (
    None
):
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
async def test_setting_recommendation_services_accept_single_entity_target() -> None:
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
async def test_setting_recommendation_entity_target_ignores_stored_history() -> None:
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
async def test_setting_recommendation_entity_target_ignores_state_history() -> None:
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
            appliance_profile: str | None = None,
            assignment_id: str | None = None,
            mains_entity_id: str | None = None,
            ground_truth_entity_id: str | None = None,
            interval_id: str | None = None,
            source: str = "manual",
            confidence: float = 1.0,
            observed_transition_w=None,
            evidence=None,
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
                        appliance_profile,
                        assignment_id,
                        mains_entity_id,
                        ground_truth_entity_id,
                        interval_id,
                        source,
                        confidence,
                        observed_transition_w,
                        evidence,
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
                "appliance_profile": "washer",
                "assignment_id": "assignment-dishwasher",
                "mains_entity_id": "sensor.mains_power",
                "ground_truth_entity_id": "sensor.dishwasher_power",
            }
        )
    )
    await hass.services.registered[(DOMAIN, SERVICE_DELETE_NILM_LABEL_INTERVAL)](
        SimpleNamespace(data={"circuit_id": "mains", "interval_id": "label-1"})
    )

    call = coordinator.calls[0][1]
    assert call[:13] == (
        "mains",
        "Dishwasher",
        "2026-06-02T12:00:00+00:00",
        "2026-06-02T12:45:00+00:00",
        "dishwasher",
        "washer",
        "assignment-dishwasher",
        "sensor.mains_power",
        "sensor.dishwasher_power",
        None,
        "manual",
        1.0,
        None,
    )
    assert call[13]["evidence_source"] == "manual_backend"
    assert coordinator.calls[1] == (
        "async_delete_nilm_label_interval",
        ("mains", "label-1"),
    )


@pytest.mark.asyncio
async def test_nilm_label_interval_service_ignores_boolean_transition() -> None:
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock

    from custom_components.circuitsetup_energy_analyzer.managers import nilm_controller
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_LABEL_NILM_INTERVAL,
        async_setup_services,
    )

    class FakeServices:
        def __init__(self) -> None:
            self.registered = {}

        def async_register(self, domain, service, handler, schema=None) -> None:
            self.registered[(domain, service)] = handler

    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 8, 2, tzinfo=UTC),
        store_data=FeatureStoreData(),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=AsyncMock()
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
        circuit_configs=[SimpleNamespace(circuit_id="mains")],
        has_circuit=lambda circuit_id: circuit_id == "mains",
    )
    coordinator.async_label_nilm_interval = nilm_controller.NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    ).async_label_nilm_interval
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
                "label": "Pump",
                "start": "2026-08-02T10:00:00+00:00",
                "end": "2026-08-02T10:05:00+00:00",
                "observed_transition_w": True,
            }
        )
    )
    saved = coordinator.store_data.nilm_label_intervals_by_circuit["mains"][0]
    assert saved["evidence_source"] == "manual_backend"
    assert "observed_transition_w" not in saved


@pytest.mark.asyncio
async def test_nilm_sensor_label_interval_service_generates_from_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import services
    from custom_components.circuitsetup_energy_analyzer.services import (
        SERVICE_GENERATE_NILM_SENSOR_LABEL_INTERVALS,
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

        async def async_save_nilm_interval_changes(
            self,
            circuit_id: str,
            *,
            label: str,
            intervals,
            assignment_id=None,
            appliance_id=None,
            reference_import_summary=None,
        ) -> None:
            self.calls.append(
                (
                    "async_save_nilm_interval_changes",
                    (
                        circuit_id,
                        label,
                        intervals,
                        assignment_id,
                        appliance_id,
                        reference_import_summary,
                    ),
                )
            )

    async def fake_history_rows(
        hass, entity_id, start, end, *, include_start_time_state=False
    ):
        return [
            [
                {
                    "entity_id": entity_id,
                    "state": "0",
                    "last_changed": start.isoformat(),
                },
                {
                    "entity_id": entity_id,
                    "state": "90",
                    "last_changed": "2026-06-02T12:10:00+00:00",
                },
                {
                    "entity_id": entity_id,
                    "state": "0",
                    "last_changed": "2026-06-02T12:40:00+00:00",
                },
            ]
        ]

    monkeypatch.setattr(services, "_async_nilm_sensor_history_rows", fake_history_rows)

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )

    await async_setup_services(hass)
    await hass.services.registered[
        (DOMAIN, SERVICE_GENERATE_NILM_SENSOR_LABEL_INTERVALS)
    ](
        SimpleNamespace(
            data={
                "circuit_id": "mains",
                "label": "Dishwasher",
                "start": "2026-06-02T12:00:00+00:00",
                "end": "2026-06-02T13:00:00+00:00",
                "ground_truth_entity_id": "sensor.dishwasher_power",
                "threshold_w": 25,
            }
        )
    )

    assert len(coordinator.calls) == 1
    name, args = coordinator.calls[0]
    assert name == "async_save_nilm_interval_changes"
    assert args[:2] == ("mains", "Dishwasher")
    draft = args[2][0]
    assert draft["start"] == "2026-06-02T12:10:00+00:00"
    assert draft["end"] == "2026-06-02T12:40:00+00:00"
    assert draft["interval_id"] == services._nilm_reference_interval_id(
        "mains",
        "",
        "sensor.dishwasher_power",
        "2026-06-02T12:10:00+00:00",
        "2026-06-02T12:40:00+00:00",
    )
    assert draft["evidence"]["evidence_source"] == "reference_backend"
    assert args[5]["imported_interval_count"] == 1


@pytest.mark.asyncio
async def test_reference_generation_preserves_brief_unknown_gap_and_complete_power(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A short unavailable gap lowers state confidence without discarding power."""
    from custom_components.circuitsetup_energy_analyzer import services

    history = AsyncMock(
        side_effect=[
            [
                [
                    {
                        "entity_id": "switch.pump",
                        "state": "on",
                        "last_changed": "2026-08-01T00:10:00+00:00",
                    },
                    {
                        "entity_id": "switch.pump",
                        "state": "on",
                        "last_changed": "2026-08-01T00:15:00+00:00",
                    },
                    {
                        "entity_id": "switch.pump",
                        "state": "unavailable",
                        "last_changed": "2026-08-01T00:20:00+00:00",
                    },
                    {
                        "entity_id": "switch.pump",
                        "state": "on",
                        "last_changed": "2026-08-01T00:21:00+00:00",
                    },
                    {
                        "entity_id": "switch.pump",
                        "state": "off",
                        "last_changed": "2026-08-01T00:40:00+00:00",
                    },
                ]
            ],
            [
                [
                    {
                        "entity_id": "sensor.pump_power",
                        "state": "80",
                        "last_changed": "2026-08-01T00:10:00+00:00",
                    },
                    {
                        "entity_id": "sensor.pump_power",
                        "state": "80",
                        "last_changed": "2026-08-01T00:25:00+00:00",
                    },
                    {
                        "entity_id": "sensor.pump_power",
                        "state": "80",
                        "last_changed": "2026-08-01T00:40:00+00:00",
                    },
                ]
            ],
        ]
    )
    monkeypatch.setattr(services, "_async_nilm_sensor_history_rows", history)
    coordinator = SimpleNamespace(
        async_set_updated_data=lambda _: None,
        circuit_configs=[SimpleNamespace(circuit_id="mixed")],
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [
                    {
                        "assignment_id": "assignment-pump",
                        "reference_state_entity_id": "switch.pump",
                        "reference_power_entity_id": "sensor.pump_power",
                        "reference_maximum_unknown_gap_seconds": 120.0,
                        "reference_maximum_power_gap_seconds": 1800.0,
                    }
                ]
            }
        ),
        async_save_nilm_interval_changes=AsyncMock(),
    )
    power_state = SimpleNamespace(
        state="80",
        attributes={"device_class": "power", "unit_of_measurement": "W"},
    )
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        states=SimpleNamespace(get=lambda _: power_state),
    )

    await services._dispatch_service(
        hass,
        services.SERVICE_GENERATE_NILM_SENSOR_LABEL_INTERVALS,
        {
            "circuit_id": "mixed",
            "assignment_id": "assignment-pump",
            "label": "Pump",
            "start": "2026-08-01T00:00:00+00:00",
            "end": "2026-08-01T01:00:00+00:00",
        },
    )

    drafts = coordinator.async_save_nilm_interval_changes.await_args.kwargs["intervals"]
    assert len(drafts) == 1
    evidence = drafts[0]["evidence"]
    assert 0.0 < evidence["state_coverage"] < 1.0
    assert evidence["power_coverage"] == 1.0
    assert evidence["measured_energy_kwh"] == pytest.approx(0.04)
    assert evidence["evidence_confidence"] < 1.0


@pytest.mark.asyncio
async def test_reference_generation_long_power_gap_retains_partial_energy_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cadence fallback must not bridge a later long power-history gap."""
    from custom_components.circuitsetup_energy_analyzer import services

    history = AsyncMock(
        side_effect=[
            [
                [
                    {
                        "entity_id": "switch.pump",
                        "state": "on",
                        "last_changed": "2026-08-01T00:10:00+00:00",
                    },
                    {
                        "entity_id": "switch.pump",
                        "state": "off",
                        "last_changed": "2026-08-01T00:40:00+00:00",
                    },
                ]
            ],
            [
                [
                    {
                        "entity_id": "sensor.pump_power",
                        "state": "80",
                        "last_changed": "2026-08-01T00:10:00+00:00",
                    },
                    {
                        "entity_id": "sensor.pump_power",
                        "state": "80",
                        "last_changed": "2026-08-01T00:11:00+00:00",
                    },
                    {
                        "entity_id": "sensor.pump_power",
                        "state": "80",
                        "last_changed": "2026-08-01T00:40:00+00:00",
                    },
                ]
            ],
        ]
    )
    monkeypatch.setattr(services, "_async_nilm_sensor_history_rows", history)
    coordinator = SimpleNamespace(
        async_set_updated_data=lambda _: None,
        circuit_configs=[SimpleNamespace(circuit_id="mixed")],
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [
                    {
                        "assignment_id": "assignment-pump",
                        "reference_state_entity_id": "switch.pump",
                        "reference_power_entity_id": "sensor.pump_power",
                    }
                ]
            }
        ),
        async_save_nilm_interval_changes=AsyncMock(),
    )
    power_state = SimpleNamespace(
        state="80",
        attributes={"device_class": "power", "unit_of_measurement": "W"},
    )
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        states=SimpleNamespace(get=lambda _: power_state),
    )

    await services._dispatch_service(
        hass,
        services.SERVICE_GENERATE_NILM_SENSOR_LABEL_INTERVALS,
        {
            "circuit_id": "mixed",
            "assignment_id": "assignment-pump",
            "label": "Pump",
            "start": "2026-08-01T00:00:00+00:00",
            "end": "2026-08-01T01:00:00+00:00",
        },
    )

    evidence = coordinator.async_save_nilm_interval_changes.await_args.kwargs[
        "intervals"
    ][0]["evidence"]
    assert 0.0 < evidence["power_coverage"] < 1.0
    assert evidence["partial_energy_kwh"] == pytest.approx(80 / 60_000)
    assert evidence["measured_energy_kwh"] is None
    assert evidence["energy_complete"] is False
    assert "long_power_gap" in evidence["quality_flags"]


@pytest.mark.asyncio
async def test_reference_generation_censored_horizon_has_no_directional_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Horizon-censored reference activity is never presented as an observed edge."""
    from custom_components.circuitsetup_energy_analyzer import services

    history = AsyncMock(
        return_value=[
            [
                {
                    "entity_id": "switch.pump",
                    "state": "on",
                    "last_changed": "2026-08-01T00:00:00+00:00",
                }
            ]
        ]
    )
    monkeypatch.setattr(services, "_async_nilm_sensor_history_rows", history)
    coordinator = SimpleNamespace(
        async_set_updated_data=lambda _: None,
        circuit_configs=[SimpleNamespace(circuit_id="mixed")],
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [
                    {
                        "assignment_id": "assignment-pump",
                        "reference_state_entity_id": "switch.pump",
                    }
                ]
            }
        ),
        async_save_nilm_interval_changes=AsyncMock(),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    await services._dispatch_service(
        hass,
        services.SERVICE_GENERATE_NILM_SENSOR_LABEL_INTERVALS,
        {
            "circuit_id": "mixed",
            "assignment_id": "assignment-pump",
            "label": "Pump",
            "start": "2026-08-01T00:00:00+00:00",
            "end": "2026-08-01T01:00:00+00:00",
        },
    )

    evidence = coordinator.async_save_nilm_interval_changes.await_args.kwargs[
        "intervals"
    ][0]["evidence"]
    assert evidence["left_censored"] is True
    assert evidence["right_censored"] is True
    assert evidence["start_transition_eligible"] is False
    assert evidence["stop_transition_eligible"] is False
    assert evidence.get("start_transition_w") is None
    assert evidence.get("stop_transition_w") is None


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
                nilm_label_intervals_by_circuit={"mains": [{"interval_id": "label-1"}]},
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
        SERVICE_CONFIRM_NILM_CONFIGURED_PRIMARY,
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

        async def async_confirm_nilm_configured_primary(
            self,
            circuit_id: str,
            assignment_id: str,
        ) -> None:
            self.calls.append(
                (
                    "async_confirm_nilm_configured_primary",
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
        SERVICE_CONFIRM_NILM_CONFIGURED_PRIMARY,
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
            "async_confirm_nilm_configured_primary",
            ("mains", "assignment-dishwasher"),
        ),
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
        SERVICE_VALIDATE_NILM_ASSIGNMENT_HISTORY,
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

        async def async_validate_nilm_assignment_history(
            self,
            circuit_id: str,
            assignment_id: str,
        ) -> None:
            self.calls.append(
                (
                    "async_validate_nilm_assignment_history",
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
    await hass.services.registered[(DOMAIN, SERVICE_VALIDATE_NILM_ASSIGNMENT_HISTORY)](
        SimpleNamespace(
            data={
                "circuit_id": "mains",
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
        (
            "async_validate_nilm_assignment_history",
            ("mains", "assignment-dishwasher"),
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
async def test_nilm_interval_change_services_validate_and_dispatch() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        NILM_INTERVAL_CHANGES_SERVICE_SCHEMA,
        SERVICE_DELETE_NILM_APPLIANCE_ASSIGNMENT,
        SERVICE_SAVE_NILM_INTERVAL_CHANGES,
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
                }
            )

        def has_circuit(self, circuit_id: str) -> bool:
            return circuit_id == "mains"

        def async_set_updated_data(self, _data: object) -> None:
            return None

        async def async_save_nilm_interval_changes(
            self, circuit_id: str, **kwargs: object
        ) -> None:
            self.calls.append(("save", (circuit_id, kwargs)))

        async def async_delete_nilm_appliance_assignment(
            self, circuit_id: str, assignment_id: str
        ) -> None:
            self.calls.append(("delete", (circuit_id, assignment_id)))

    payload = {
        "circuit_id": "mains",
        "assignment_id": "assignment-dishwasher",
        "label": "Dishwasher",
        "intervals": [
            {
                "interval_id": "label-1",
                "start": "2026-06-02T12:00:00+00:00",
                "end": "2026-06-02T12:30:00+00:00",
            }
        ],
        "removed_interval_ids": ["label-old"],
    }
    assert NILM_INTERVAL_CHANGES_SERVICE_SCHEMA(payload) == payload
    with pytest.raises(ValueError):
        NILM_INTERVAL_CHANGES_SERVICE_SCHEMA({**payload, "intervals": [{}] * 51})

    coordinator = FakeCoordinator()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": coordinator}},
        services=FakeServices(),
        bus=SimpleNamespace(async_fire=lambda event_type, event_data=None: None),
    )
    await async_setup_services(hass)
    await hass.services.registered[(DOMAIN, SERVICE_SAVE_NILM_INTERVAL_CHANGES)](
        SimpleNamespace(data=payload)
    )
    await hass.services.registered[(DOMAIN, SERVICE_DELETE_NILM_APPLIANCE_ASSIGNMENT)](
        SimpleNamespace(
            data={"circuit_id": "mains", "assignment_id": "assignment-dishwasher"}
        )
    )

    save_circuit, save_kwargs = coordinator.calls[0][1]
    assert save_circuit == "mains"
    assert {key: value for key, value in save_kwargs.items() if key != "intervals"} == {
        "label": "Dishwasher",
        "removed_interval_ids": ["label-old"],
        "assignment_id": "assignment-dishwasher",
        "appliance_id": None,
        "appliance_profile": None,
    }
    assert (
        save_kwargs["intervals"][0]["evidence"]["evidence_source"] == "manual_backend"
    )
    assert coordinator.calls[1] == ("delete", ("mains", "assignment-dishwasher"))


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

        async def async_mark_alert_confirmed(self, alert_id: str) -> bool:
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
        services_module.SERVICE_MARK_ALERT_CONFIRMED,
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

        async def async_mark_alert_confirmed(self, alert_id: str) -> bool:
            self.calls.append(("async_mark_alert_confirmed", alert_id))
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
        services_module.SERVICE_MARK_ALERT_CONFIRMED,
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
        ("async_mark_alert_confirmed", expected_alert_id),
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
        SERVICE_MARK_ALERT_CONFIRMED,
        SERVICE_MARK_ALERT_EXPECTED,
        SERVICE_MARK_ALERT_UNHELPFUL,
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
        ) -> None:
            self.calls.append(
                (
                    "async_set_cost_settings",
                    (
                        circuit_id,
                        cycle_start_day,
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

        async def async_mark_alert_confirmed(self, alert_id: str) -> bool:
            self.calls.append(("async_mark_alert_confirmed", (alert_id,)))
            return True

        async def async_mark_alert_unhelpful(self, alert_id: str) -> bool:
            self.calls.append(("async_mark_alert_unhelpful", (alert_id,)))
            return True

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
    await hass.services.registered[(DOMAIN, SERVICE_MARK_ALERT_CONFIRMED)](
        SimpleNamespace(data={"alert_id": "alert-confirmed"})
    )
    await hass.services.registered[(DOMAIN, SERVICE_MARK_ALERT_UNHELPFUL)](
        SimpleNamespace(data={"alert_id": "alert-2"})
    )
    assert (DOMAIN, "mark_nilm_signature_expected") not in hass.services.registered
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
            ("fridge", 1),
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
        ("async_mark_alert_confirmed", ("alert-confirmed",)),
        ("async_mark_alert_unhelpful", ("alert-2",)),
        ("async_merge_nilm_signatures", ("mains", "signature_2", "signature_1")),
    ]


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
async def test_service_handlers_mutate_loaded_coordinator_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import coordinator
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

    monkeypatch.setattr(coordinator, "async_track_point_in_time", None)
    EnergyAnalyzerCoordinator = coordinator.EnergyAnalyzerCoordinator

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


def test_nilm_direct_meter_conversion_boolean_values_are_coerced_safely() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        _boolean_value,
    )

    assert _boolean_value("false") is False
    assert _boolean_value("true") is True
    assert _boolean_value(0) is False
    with pytest.raises(Exception, match="Expected a boolean"):
        _boolean_value("sometimes")


def test_nilm_helper_link_service_schemas_are_exact() -> None:
    from custom_components.circuitsetup_energy_analyzer import services

    set_schema = services._SERVICE_SCHEMAS[services.SERVICE_SET_NILM_HELPER_LINK]
    remove = services._SERVICE_SCHEMAS[services.SERVICE_REMOVE_NILM_HELPER_LINK]
    data = {
        "circuit_id": "mixed",
        "assignment_id": "assignment-load",
        "helper_circuit_id": "helper",
        "relationship": "corroborates",
        "entry_id": "entry-1",
    }
    assert set_schema(data) == data
    assert remove({k: v for k, v in data.items() if k != "relationship"})
    assert set_schema({**data, "relationship": "direct_component"})
    with pytest.raises(ValueError):
        set_schema({**data, "relationship": "other"})
    with pytest.raises(ValueError):
        set_schema({**data, "extra": "no"})


def test_nilm_reference_link_service_schemas_are_exact() -> None:
    from custom_components.circuitsetup_energy_analyzer import services

    set_schema = services._SERVICE_SCHEMAS[services.SERVICE_SET_NILM_REFERENCE_LINK]
    remove = services._SERVICE_SCHEMAS[services.SERVICE_REMOVE_NILM_REFERENCE_LINK]
    data = {
        "circuit_id": "mixed",
        "assignment_id": "assignment-load",
        "reference_state_entity_id": "switch.load",
        "reference_power_entity_id": "sensor.load_power",
        "reference_threshold_w": 12.5,
        "entry_id": "entry-1",
    }
    assert set_schema(data) == data
    assert remove(
        {
            "circuit_id": "mixed",
            "assignment_id": "assignment-load",
            "entry_id": "entry-1",
        }
    )
    with pytest.raises(ValueError):
        set_schema(
            {
                "circuit_id": "mixed",
                "assignment_id": "assignment-load",
            }
        )
    with pytest.raises(ValueError):
        set_schema({**data, "reference_threshold_w": -1})


def test_nilm_reference_link_service_schema_validates_canonical_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer import services

    set_schema = services._SERVICE_SCHEMAS[services.SERVICE_SET_NILM_REFERENCE_LINK]
    data = {
        "circuit_id": "mixed",
        "assignment_id": "assignment-load",
        "reference_power_entity_id": "sensor.load_power",
        "reference_on_threshold": 20,
        "reference_off_threshold": 12,
        "reference_on_dwell_seconds": 3,
        "reference_off_dwell_seconds": 4,
        "reference_minimum_interval_seconds": 5,
        "reference_merge_gap_seconds": 6,
        "reference_maximum_unknown_gap_seconds": 7,
        "reference_maximum_power_gap_seconds": 8,
    }

    expected = dict(data)
    expected.update(
        {
            key: float(value)
            for key, value in data.items()
            if key.startswith("reference_") and key != "reference_power_entity_id"
        }
    )
    assert set_schema(data) == expected
    with pytest.raises(ValueError, match="ordered"):
        set_schema({**data, "reference_off_threshold": 21})
    with pytest.raises(ValueError, match="durations"):
        set_schema({**data, "reference_on_dwell_seconds": -1})


@pytest.mark.asyncio
async def test_nilm_reference_link_services_are_entry_isolated() -> None:
    from custom_components.circuitsetup_energy_analyzer import services

    def coordinator() -> SimpleNamespace:
        return SimpleNamespace(
            async_set_updated_data=lambda _: None,
            circuit_configs=[SimpleNamespace(circuit_id="mixed")],
            store_data=FeatureStoreData(
                nilm_appliance_assignments_by_circuit={
                    "mixed": [{"assignment_id": "assignment-load"}]
                }
            ),
            async_set_nilm_reference_link=AsyncMock(),
            async_remove_nilm_reference_link=AsyncMock(),
        )

    first, second = coordinator(), coordinator()
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": first, "entry-2": second}})
    data = {
        "circuit_id": "mixed",
        "assignment_id": "assignment-load",
        "reference_state_entity_id": "switch.load",
        "reference_power_entity_id": "sensor.load_power",
        "reference_threshold_w": 12.5,
    }
    with pytest.raises(services.HomeAssistantError, match="ambiguous"):
        await services._dispatch_service(
            hass, services.SERVICE_SET_NILM_REFERENCE_LINK, data
        )

    await services._dispatch_service(
        hass,
        services.SERVICE_SET_NILM_REFERENCE_LINK,
        {**data, "entry_id": "entry-2"},
    )
    first.async_set_nilm_reference_link.assert_not_awaited()
    second.async_set_nilm_reference_link.assert_awaited_once_with(
        "mixed",
        "assignment-load",
        state_entity_id="switch.load",
        power_entity_id="sensor.load_power",
        threshold_w=12.5,
    )

    await services._dispatch_service(
        hass,
        services.SERVICE_REMOVE_NILM_REFERENCE_LINK,
        {
            "circuit_id": "mixed",
            "assignment_id": "assignment-load",
            "entry_id": "entry-2",
        },
    )
    second.async_remove_nilm_reference_link.assert_awaited_once_with(
        "mixed", "assignment-load"
    )


@pytest.mark.asyncio
async def test_nilm_reference_link_service_dispatches_canonical_settings() -> None:
    from custom_components.circuitsetup_energy_analyzer import services

    coordinator = SimpleNamespace(
        async_set_updated_data=lambda _: None,
        circuit_configs=[SimpleNamespace(circuit_id="mixed")],
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [{"assignment_id": "assignment-load"}]
            }
        ),
        async_set_nilm_reference_link=AsyncMock(),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})
    data = {
        "circuit_id": "mixed",
        "assignment_id": "assignment-load",
        "entry_id": "entry-1",
        "reference_power_entity_id": "sensor.load_power",
        "reference_on_threshold": 20.0,
        "reference_off_threshold": 12.0,
        "reference_on_dwell_seconds": 3.0,
        "reference_maximum_unknown_gap_seconds": 7.0,
    }

    await services._dispatch_service(
        hass, services.SERVICE_SET_NILM_REFERENCE_LINK, data
    )

    coordinator.async_set_nilm_reference_link.assert_awaited_once_with(
        "mixed",
        "assignment-load",
        state_entity_id=None,
        power_entity_id="sensor.load_power",
        threshold_w=None,
        on_threshold=20.0,
        off_threshold=12.0,
        on_dwell_seconds=3.0,
        maximum_unknown_gap_seconds=7.0,
    )


@pytest.mark.asyncio
async def test_nilm_helper_link_services_are_entry_isolated() -> None:
    from custom_components.circuitsetup_energy_analyzer import services

    def coordinator(helper: bool = True) -> SimpleNamespace:
        configs = [SimpleNamespace(circuit_id="mixed")]
        if helper:
            configs.append(SimpleNamespace(circuit_id="helper"))
        return SimpleNamespace(
            async_set_updated_data=lambda _: None,
            circuit_configs=configs,
            store_data=FeatureStoreData(
                nilm_appliance_assignments_by_circuit={
                    "mixed": [{"assignment_id": "assignment-load"}]
                }
            ),
            async_set_nilm_helper_link=AsyncMock(),
            async_remove_nilm_helper_link=AsyncMock(),
        )

    first, second = coordinator(), coordinator()
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": first, "entry-2": second}})
    data = {
        "circuit_id": "mixed",
        "assignment_id": "assignment-load",
        "helper_circuit_id": "helper",
    }
    with pytest.raises(services.HomeAssistantError, match="ambiguous"):
        await services._dispatch_service(
            hass,
            services.SERVICE_SET_NILM_HELPER_LINK,
            {**data, "relationship": "corroborates"},
        )
    first.async_set_nilm_helper_link.assert_not_awaited()
    await services._dispatch_service(
        hass,
        services.SERVICE_SET_NILM_HELPER_LINK,
        {**data, "relationship": "corroborates", "entry_id": "entry-2"},
    )
    second.async_set_nilm_helper_link.assert_awaited_once()
    hass.data[DOMAIN] = {"entry-1": coordinator(False), "entry-2": second}
    await services._dispatch_service(
        hass, services.SERVICE_REMOVE_NILM_HELPER_LINK, data
    )
    second.async_remove_nilm_helper_link.assert_awaited_once()


def test_mark_circuit_mixed_uses_dedicated_entry_scoped_schema() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        _SERVICE_SCHEMAS,
        ATTR_ENTRY_ID,
        CIRCUIT_SERVICE_SCHEMA,
        MARK_CIRCUIT_MIXED_SERVICE_SCHEMA,
        SERVICE_MARK_CIRCUIT_MIXED,
    )

    schema = _SERVICE_SCHEMAS[SERVICE_MARK_CIRCUIT_MIXED]
    assert schema is MARK_CIRCUIT_MIXED_SERVICE_SCHEMA
    assert schema is not CIRCUIT_SERVICE_SCHEMA
    assert schema({"circuit_id": "fridge", ATTR_ENTRY_ID: "entry-1"}) == {
        "circuit_id": "fridge",
        ATTR_ENTRY_ID: "entry-1",
    }


@pytest.mark.asyncio
async def test_mark_circuit_mixed_dispatches_to_coordinator() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        ATTR_CIRCUIT_ID,
        SERVICE_MARK_CIRCUIT_MIXED,
        _dispatch_service,
    )

    coordinator = SimpleNamespace(
        async_set_updated_data=lambda data: None,
        circuit_configs=[SimpleNamespace(circuit_id="fridge")],
        async_mark_circuit_mixed=AsyncMock(),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry": coordinator}})

    await _dispatch_service(
        hass, SERVICE_MARK_CIRCUIT_MIXED, {ATTR_CIRCUIT_ID: "fridge"}
    )

    coordinator.async_mark_circuit_mixed.assert_awaited_once_with("fridge")


@pytest.mark.asyncio
async def test_mark_circuit_mixed_scopes_duplicate_circuit_to_entry() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        ATTR_CIRCUIT_ID,
        ATTR_ENTRY_ID,
        SERVICE_MARK_CIRCUIT_MIXED,
        _dispatch_service,
    )

    first = SimpleNamespace(
        async_set_updated_data=lambda data: None,
        circuit_configs=[SimpleNamespace(circuit_id="fridge")],
        async_mark_circuit_mixed=AsyncMock(),
    )
    second = SimpleNamespace(
        async_set_updated_data=lambda data: None,
        circuit_configs=[SimpleNamespace(circuit_id="fridge")],
        async_mark_circuit_mixed=AsyncMock(),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": first, "entry-2": second}})

    await _dispatch_service(
        hass,
        SERVICE_MARK_CIRCUIT_MIXED,
        {ATTR_ENTRY_ID: "entry-2", ATTR_CIRCUIT_ID: "fridge"},
    )

    first.async_mark_circuit_mixed.assert_not_awaited()
    second.async_mark_circuit_mixed.assert_awaited_once_with("fridge")

    await _dispatch_service(
        hass, SERVICE_MARK_CIRCUIT_MIXED, {ATTR_CIRCUIT_ID: "fridge"}
    )
    first.async_mark_circuit_mixed.assert_awaited_once_with("fridge")
    assert second.async_mark_circuit_mixed.await_count == 2


def _entry_scoped_nilm_coordinator() -> SimpleNamespace:
    return SimpleNamespace(
        async_set_updated_data=lambda data: None,
        circuit_configs=[SimpleNamespace(circuit_id="mains")],
        store_data=FeatureStoreData(
            nilm_signatures={"mains": [{"signature_id": "signature-1"}]},
            nilm_label_intervals_by_circuit={"mains": [{"interval_id": "interval-1"}]},
        ),
        async_label_nilm_interval=AsyncMock(),
        async_label_nilm_signature=AsyncMock(),
        async_assign_nilm_interval=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_nilm_generic_action_scopes_duplicate_circuit_and_legacy_broadcasts() -> (
    None
):
    """Catches label actions mutating every entry with the same circuit ID."""
    from custom_components.circuitsetup_energy_analyzer.services import (
        ATTR_CIRCUIT_ID,
        ATTR_ENTRY_ID,
        SERVICE_LABEL_NILM_INTERVAL,
        _dispatch_service,
    )

    first = _entry_scoped_nilm_coordinator()
    second = _entry_scoped_nilm_coordinator()
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": first, "entry-2": second}})
    data = {
        ATTR_CIRCUIT_ID: "mains",
        "label": "Load",
        "start": "2026-06-02T12:00:00+00:00",
        "end": "2026-06-02T12:30:00+00:00",
    }

    await _dispatch_service(
        hass, SERVICE_LABEL_NILM_INTERVAL, {**data, ATTR_ENTRY_ID: "entry-2"}
    )

    first.async_label_nilm_interval.assert_not_awaited()
    second.async_label_nilm_interval.assert_awaited_once()

    await _dispatch_service(hass, SERVICE_LABEL_NILM_INTERVAL, data)

    first.async_label_nilm_interval.assert_awaited_once()
    assert second.async_label_nilm_interval.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service", "data", "method_name"),
    (
        (
            "label_nilm_signature",
            {"signature_id": "signature-1", "label": "Load"},
            "async_label_nilm_signature",
        ),
        (
            "assign_interval_to_appliance",
            {"interval_id": "interval-1", "label": "Load"},
            "async_assign_nilm_interval",
        ),
    ),
)
async def test_nilm_identity_actions_scope_duplicate_circuit_to_entry(
    service: str, data: dict[str, str], method_name: str
) -> None:
    """Catches signature and interval lookup bypassing an entry-scoped target."""
    from custom_components.circuitsetup_energy_analyzer.services import (
        ATTR_CIRCUIT_ID,
        ATTR_ENTRY_ID,
        _dispatch_service,
    )

    first = _entry_scoped_nilm_coordinator()
    second = _entry_scoped_nilm_coordinator()
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": first, "entry-2": second}})

    await _dispatch_service(
        hass,
        service,
        {ATTR_CIRCUIT_ID: "mains", ATTR_ENTRY_ID: "entry-2", **data},
    )

    getattr(first, method_name).assert_not_awaited()
    getattr(second, method_name).assert_awaited_once()

    await _dispatch_service(hass, service, {ATTR_CIRCUIT_ID: "mains", **data})

    getattr(first, method_name).assert_awaited_once()
    assert getattr(second, method_name).await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("entry_id", "circuit_id", "message"),
    (
        ("missing", "fridge", "Unknown entry_id 'missing'"),
        ("entry-1", "oven", "Unknown circuit_id 'oven'.*entry_id 'entry-1'"),
    ),
)
async def test_mark_circuit_mixed_rejects_invalid_scoped_target(
    entry_id: str, circuit_id: str, message: str
) -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        ATTR_CIRCUIT_ID,
        ATTR_ENTRY_ID,
        SERVICE_MARK_CIRCUIT_MIXED,
        HomeAssistantError,
        _dispatch_service,
    )

    coordinator = SimpleNamespace(
        async_set_updated_data=lambda data: None,
        circuit_configs=[SimpleNamespace(circuit_id="fridge")],
        async_mark_circuit_mixed=AsyncMock(),
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": coordinator}})

    with pytest.raises(HomeAssistantError, match=message):
        await _dispatch_service(
            hass,
            SERVICE_MARK_CIRCUIT_MIXED,
            {ATTR_ENTRY_ID: entry_id, ATTR_CIRCUIT_ID: circuit_id},
        )
