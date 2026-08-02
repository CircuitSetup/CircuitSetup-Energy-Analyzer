from __future__ import annotations

import importlib
import sys
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

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


def _alert(feature: str = "leg_imbalance") -> AlertEvidence:
    return AlertEvidence(
        timestamp=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
        circuit_id="hvac",
        severity=Severity.WARNING,
        message="Possible issue: HVAC leg imbalance",
        feature=feature,
        observed_value=62.0,
        baseline_value=20.0,
        change_ratio=2.1,
        repeated_count=3,
        first_seen=datetime(2026, 6, 5, 10, 0, tzinfo=UTC),
        last_seen=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
        features={"leg_imbalance": 2.1, "real_power": 1.4},
    )


def _config() -> CircuitConfig:
    return CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(
            SensorRef("sensor.hvac_l1_watts", SensorRole.REAL_POWER, leg="a"),
            SensorRef("sensor.hvac_l2_watts", SensorRole.REAL_POWER, leg="b"),
            SensorRef("sensor.hvac_l1_current", SensorRole.CURRENT, leg="a"),
            SensorRef("sensor.hvac_l2_current", SensorRole.CURRENT, leg="b"),
            SensorRef(
                "sensor.hvac_l1_reactive_power", SensorRole.REACTIVE_POWER, leg="a"
            ),
            SensorRef(
                "sensor.hvac_l2_reactive_power", SensorRole.REACTIVE_POWER, leg="b"
            ),
            SensorRef("sensor.hvac_power_factor", SensorRole.POWER_FACTOR),
            SensorRef("sensor.hvac_energy", SensorRole.ENERGY),
            SensorRef("sensor.hvac_frequency", SensorRole.FREQUENCY),
        ),
    )


def test_alert_evidence_path_contains_alert_context() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        DEFAULT_ALERT_EVIDENCE_PATH,
        alert_evidence_path,
    )

    path = alert_evidence_path(_alert(), dashboard_path=DEFAULT_ALERT_EVIDENCE_PATH)
    parsed = urlparse(path)
    params = parse_qs(parsed.query)

    assert parsed.path == "/circuitsetup-energy-analyzer-evidence"
    assert params["circuit_id"] == ["hvac"]
    assert params["feature"] == ["leg_imbalance"]
    assert params["alert_id"][0].startswith("circuitsetup_energy_analyzer_alert_hvac_")


def test_alert_evidence_path_can_target_dashboard_fallback() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        DEFAULT_ALERT_EVIDENCE_DASHBOARD_PATH,
        alert_evidence_path,
    )

    path = alert_evidence_path(
        _alert(),
        dashboard_path=DEFAULT_ALERT_EVIDENCE_DASHBOARD_PATH,
    )

    assert urlparse(path).path == "/circuitsetup-energy-analyzer/alert-evidence"


def test_alert_evidence_path_uses_event_type_when_feature_missing() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_evidence_path,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
        circuit_id="hvac",
        severity=Severity.WARNING,
        message="Possible issue: HVAC leg imbalance",
        event_type=EventType.LEG_IMBALANCE,
        feature="",
    )

    params = parse_qs(urlparse(alert_evidence_path(alert)).query)

    assert params["feature"] == ["leg_imbalance"]
    assert params["alert_id"][0].startswith(
        "circuitsetup_energy_analyzer_alert_hvac_leg_imbalance_"
    )


def test_alert_links_does_not_import_notifications_at_module_load() -> None:
    alert_links_module = "custom_components.circuitsetup_energy_analyzer.alert_links"
    notifications_module = (
        "custom_components.circuitsetup_energy_analyzer.notifications"
    )

    sys.modules.pop(alert_links_module, None)
    sys.modules.pop(notifications_module, None)

    importlib.import_module(alert_links_module)

    assert notifications_module not in sys.modules


def test_alert_graph_entities_prefer_feature_related_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_graph_entities,
    )

    assert alert_graph_entities(_alert("leg_imbalance"), _config()) == (
        "sensor.hvac_l1_watts",
        "sensor.hvac_l2_watts",
        "sensor.hvac_l1_current",
        "sensor.hvac_l2_current",
    )
    assert alert_graph_entities(_alert("reactive_power"), _config()) == (
        "sensor.hvac_l1_reactive_power",
        "sensor.hvac_l2_reactive_power",
        "sensor.hvac_l1_watts",
        "sensor.hvac_l2_watts",
        "sensor.hvac_power_factor",
    )


def test_appliance_health_graph_entities_keep_all_relevant_phases() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_graph_entities,
    )

    assert alert_graph_entities(
        _alert("efficiency_degradation"),
        _config(),
    ) == (
        "sensor.hvac_energy",
        "sensor.hvac_l1_watts",
        "sensor.hvac_l2_watts",
    )
    assert alert_graph_entities(
        _alert("repeated_short_cycle"),
        _config(),
    ) == (
        "sensor.hvac_l1_watts",
        "sensor.hvac_l2_watts",
    )


def test_alert_graph_entities_prefers_relationship_metrics_for_split_phase_change() -> (
    None
):
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_graph_entities,
    )

    assert alert_graph_entities(
        _alert("split_phase_relationship_changed"),
        _config(),
    ) == (
        "sensor.hvac_l1_reactive_power",
        "sensor.hvac_l2_reactive_power",
        "sensor.hvac_l1_watts",
        "sensor.hvac_l2_watts",
        "sensor.hvac_power_factor",
    )


def test_alert_graph_entities_returns_empty_without_config() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_graph_entities,
    )

    assert alert_graph_entities(_alert(), None) == ()


def test_alert_graph_entities_uses_event_type_when_feature_missing() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_graph_entities,
    )

    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
        circuit_id="panel",
        severity=Severity.WARNING,
        message="Voltage sag detected",
        event_type=EventType.VOLTAGE_SAG,
        feature="",
    )
    config = CircuitConfig(
        circuit_id="panel",
        name="Panel",
        appliance_profile=ApplianceProfile.MIXED,
        mode=CircuitMode.MIXED,
        sensors=(
            SensorRef("sensor.panel_reactive", SensorRole.REACTIVE_POWER),
            SensorRef("sensor.panel_voltage", SensorRole.VOLTAGE),
            SensorRef("sensor.panel_watts", SensorRole.REAL_POWER),
            SensorRef("sensor.panel_current", SensorRole.CURRENT),
        ),
    )

    assert alert_graph_entities(alert, config) == (
        "sensor.panel_voltage",
        "sensor.panel_watts",
        "sensor.panel_current",
    )


def test_alert_source_entities_returns_unique_configured_sources() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_source_entities,
    )

    config = CircuitConfig(
        circuit_id="hvac",
        name="HVAC",
        appliance_profile=ApplianceProfile.HVAC,
        mode=CircuitMode.DUAL_PHASE,
        sensors=(
            SensorRef("sensor.hvac_l1_watts", SensorRole.REAL_POWER, leg="a"),
            SensorRef("sensor.hvac_l1_watts", SensorRole.REAL_POWER, leg="a"),
            SensorRef("sensor.hvac_l2_watts", SensorRole.REAL_POWER, leg="b"),
        ),
    )

    assert alert_source_entities(config) == (
        "sensor.hvac_l1_watts",
        "sensor.hvac_l2_watts",
    )


def test_alert_source_entities_returns_empty_without_config() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_source_entities,
    )

    assert alert_source_entities(None) == ()


def test_alert_graph_window_matches_sustained_evidence() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_graph_window,
    )

    assert alert_graph_window(_alert()) == (
        datetime(2026, 6, 5, 9, 50, tzinfo=UTC),
        datetime(2026, 6, 5, 12, 40, tzinfo=UTC),
    )


def test_alert_graph_entities_covers_current_alert_families() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_graph_entities,
    )

    assert alert_graph_entities(_alert("expected_schedule_missed"), _config()) == (
        "sensor.hvac_l1_watts",
        "sensor.hvac_l2_watts",
        "sensor.hvac_l1_current",
        "sensor.hvac_l2_current",
    )
    assert alert_graph_entities(_alert("nilm_model_drift"), _config()) == (
        "sensor.hvac_l1_watts",
        "sensor.hvac_l2_watts",
    )
    assert alert_graph_entities(_alert("solar_flow"), _config()) == (
        "sensor.hvac_l1_watts",
        "sensor.hvac_l2_watts",
    )
    assert alert_graph_entities(_alert("demand_monthly_peak"), _config()) == (
        "sensor.hvac_l1_watts",
        "sensor.hvac_l2_watts",
    )


def test_alert_graph_entities_uses_value_metric_when_feature_is_unknown() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_graph_entities,
    )

    alert = replace(
        _alert("future_diagnostic"),
        value_metric="frequency",
    )

    assert alert_graph_entities(alert, _config()) == ("sensor.hvac_frequency",)


def test_alert_graph_entities_omits_unknown_relationship() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_graph_entities,
    )

    assert alert_graph_entities(_alert("future_diagnostic"), _config()) == ()


def test_alert_graph_window_centers_point_alert() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_graph_window,
    )

    timestamp = datetime(2026, 6, 5, 12, 30, tzinfo=UTC)
    alert = replace(_alert(), first_seen=timestamp, last_seen=timestamp)

    assert alert_graph_window(alert) == (
        datetime(2026, 6, 5, 12, 15, tzinfo=UTC),
        datetime(2026, 6, 5, 12, 45, tzinfo=UTC),
    )


def test_alert_graph_window_uses_only_valid_demand_measurement_windows() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_graph_window,
    )

    timestamp = datetime(2026, 6, 5, 12, 30, tzinfo=UTC)
    cases = (
        (
            15.0,
            datetime(2026, 6, 5, 12, 5, tzinfo=UTC),
            datetime(2026, 6, 5, 12, 40, tzinfo=UTC),
        ),
        (
            "invalid",
            datetime(2026, 6, 5, 12, 15, tzinfo=UTC),
            datetime(2026, 6, 5, 12, 45, tzinfo=UTC),
        ),
        (
            float("nan"),
            datetime(2026, 6, 5, 12, 15, tzinfo=UTC),
            datetime(2026, 6, 5, 12, 45, tzinfo=UTC),
        ),
        (
            -15.0,
            datetime(2026, 6, 5, 12, 15, tzinfo=UTC),
            datetime(2026, 6, 5, 12, 45, tzinfo=UTC),
        ),
        (
            1e308,
            datetime(2026, 6, 5, 12, 15, tzinfo=UTC),
            datetime(2026, 6, 5, 12, 45, tzinfo=UTC),
        ),
    )
    for demand_window_minutes, expected_start, expected_end in cases:
        alert = replace(
            _alert("demand_monthly_peak"),
            timestamp=timestamp,
            first_seen=timestamp,
            last_seen=timestamp,
            features={"demand_window_minutes": demand_window_minutes},
        )

        assert alert_graph_window(alert) == (expected_start, expected_end)


def test_alert_graph_window_orders_reversed_evidence_timestamps() -> None:
    from custom_components.circuitsetup_energy_analyzer.alert_links import (
        alert_graph_window,
    )

    alert = replace(
        _alert(),
        first_seen=datetime(2026, 6, 5, 12, 30, tzinfo=UTC),
        last_seen=datetime(2026, 6, 5, 10, 0, tzinfo=UTC),
    )

    assert alert_graph_window(alert) == (
        datetime(2026, 6, 5, 9, 50, tzinfo=UTC),
        datetime(2026, 6, 5, 12, 40, tzinfo=UTC),
    )
