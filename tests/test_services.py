from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

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
    assert (
        "[Open evidence graph](/circuitsetup-energy-analyzer-evidence?"
        in message
    )
    assert "sensor.hvac_l1_watts" in message
    assert "sensor.hvac_l2_current" in message
    assert "Observed value: 62.0" in message
    assert "Baseline value: 20.0" in message


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


def test_user_experience_service_schemas_validate_required_fields() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
        ALERT_FEEDBACK_SERVICE_SCHEMA,
        CAPACITY_SETTINGS_SERVICE_SCHEMA,
        MAINTENANCE_END_SERVICE_SCHEMA,
        MAINTENANCE_START_SERVICE_SCHEMA,
        NILM_MERGE_SERVICE_SCHEMA,
        NILM_SIGNATURE_SERVICE_SCHEMA,
        SENSITIVITY_SERVICE_SCHEMA,
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

    with pytest.raises(vol.Invalid):
        SENSITIVITY_SERVICE_SCHEMA({"circuit_id": "fridge"})
    with pytest.raises(vol.Invalid):
        NILM_MERGE_SERVICE_SCHEMA(
            {"circuit_id": "mains", "source_signature_id": "signature_2"}
        )


@pytest.mark.asyncio
async def test_setup_and_unload_services_with_fake_hass() -> None:
    from custom_components.circuitsetup_energy_analyzer.services import (
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
    handler, _schema = hass.services.registered[(DOMAIN, SERVICE_RELEARN_BASELINE)]
    await handler(SimpleNamespace(data={"circuit_id": "fridge"}))

    assert hass.bus.events == [
        (f"{DOMAIN}_{SERVICE_RELEARN_BASELINE}", {"circuit_id": "fridge"})
    ]

    await async_unload_services(hass)

    assert hass.services.registered == {}
    assert (DOMAIN, SERVICE_RELEARN_BASELINE) in hass.services.removed


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

        async def async_mark_alert_expected(self, alert_id: str) -> None:
            self.calls.append(("async_mark_alert_expected", (alert_id,)))

        async def async_mark_alert_unhelpful(self, alert_id: str) -> None:
            self.calls.append(("async_mark_alert_unhelpful", (alert_id,)))

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
    await hass.services.registered[(DOMAIN, SERVICE_RELEARN_BASELINE)](
        SimpleNamespace(data={"circuit_id": "fridge"})
    )
    await hass.services.registered[(DOMAIN, SERVICE_PAUSE_ALERTS)](
        SimpleNamespace(data={"circuit_id": "fridge", "duration": "01:00:00"})
    )
    await hass.services.registered[(DOMAIN, SERVICE_ACKNOWLEDGE_ALERT)](
        SimpleNamespace(data={"alert_id": notification_id_for_alert(alert)})
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
