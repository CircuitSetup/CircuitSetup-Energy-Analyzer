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
