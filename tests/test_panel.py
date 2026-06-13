from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
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


def _coordinator(*alerts: AlertEvidence, config: CircuitConfig | None = None):
    default_config = config or _config(alerts[0].circuit_id if alerts else "hvac")
    return SimpleNamespace(
        store_data=SimpleNamespace(alerts=list(alerts)),
        circuit_configs=(default_config,),
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
    assert payload["actions"]["dismiss_setting_recommendation"]["data"] == {
        "recommendation_id": "hvac:daily_spike_ratio:v1",
        "entry_id": "entry-1",
    }


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
    assert payload["setting_recommendations"][0]["actions"]["deny"]["service"] == (
        "deny_setting_recommendation"
    )
    assert payload["setting_recommendations"][0]["actions"]["dismiss"]["service"] == (
        "dismiss_setting_recommendation"
    )
    assert payload["setting_recommendations"][0]["display_label"] == (
        "Raise daily spike threshold"
    )
    assert payload["setting_recommendations"][1]["actions"]["apply"]["data"] == {
        "recommendation_id": "hvac:standby_threshold_w:v1",
        "entry_id": "entry-1",
    }
    assert payload["setting_recommendations"][1]["display_label"] == (
        "Standby Threshold W"
    )


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
    assert payload["nilm"]["signatures"][0]["actions"]["ignore"] == {
        "domain": DOMAIN,
        "service": "ignore_nilm_signature",
        "data": {"circuit_id": "mains", "signature_id": "signature_1"},
    }
    assert payload["nilm"]["signatures"][0]["actions"]["mark_expected"]["data"] == {
        "circuit_id": "mains",
        "signature_id": "signature_1",
    }


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
                "Pool pump-like load, 1.1 kW, confidence 65%, "
                "first seen 2026-06-09"
            ),
        }
    ]


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
        "message": (
            "The requested alert or circuit evidence is no longer available."
        ),
        "next_step": (
            "Open a newer notification or review the appliance summary sensors."
        ),
    }


@pytest.mark.asyncio
async def test_panel_setup_registers_static_api_and_panel_once() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        EVIDENCE_API_PATH,
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
    assert len(http.views) == 1
    assert http.views[0].url == EVIDENCE_API_PATH
    assert len(panel_custom.panels) == 1
    assert panel_custom.panels[0]["frontend_url_path"] == PANEL_URL_PATH
    assert panel_custom.panels[0]["webcomponent_name"] == PANEL_ELEMENT_NAME
    assert panel_custom.panels[0].get("sidebar_title") is None
    assert panel_custom.panels[0].get("sidebar_icon") is None
    assert panel_custom.panels[0]["module_url"].endswith(
        f"?v={PANEL_MODULE_VERSION}"
    )

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
    assert len(http.views) == 1

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
    assert panel_custom.panels[0]["module_url"].endswith(
        f"?v={PANEL_MODULE_VERSION}"
    )
    assert frontend.removed == [PANEL_URL_PATH]

    await async_unload_panel(hass)

    assert frontend.removed == [PANEL_URL_PATH, PANEL_URL_PATH]
