from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import pytest
from aiohttp import TCPConnector
from aiohttp.resolver import ThreadedResolver
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    BaselineStats,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.notifications import (
    notification_id_for_alert,
)


@pytest.mark.usefixtures("enable_custom_integrations", "socket_enabled")
@pytest.mark.asyncio
async def test_disposable_home_assistant_panel(
    hass: Any,
    hass_access_token: str,
    hass_admin_user: Any,
    aiohttp_client: Any,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Render the shipped panel against a real disposable HA HTTP server."""
    caplog.set_level(logging.INFO)
    _point_custom_components_at_worktree(monkeypatch)
    assert await async_setup_component(hass, "frontend", {})
    hass.data["onboarding"].onboarded = True
    for location in ("Kitchen", "Garage"):
        entity_id = f"sensor.{location.lower()}_fridge_power"
        hass.states.async_set(
            entity_id, "84", {"unit_of_measurement": "W", "device_class": "power"}
        )
        entry = MockConfigEntry(
            domain=DOMAIN,
            entry_id=f"browser-{location.lower()}",
            title=f"{location} meter",
            data={
                "source_entities": [entity_id],
                "circuits": [
                    {
                        "circuit_id": "fridge",
                        "name": f"{location} Fridge",
                        "mode": "single_phase",
                        "appliance_profile": "refrigerator",
                        "sensors": [{"entity_id": entity_id, "role": "real_power"}],
                    }
                ],
            },
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        meter = hass.data[DOMAIN][entry.entry_id]
        alert = AlertEvidence(
            timestamp=meter.current_time(),
            circuit_id="fridge",
            feature="daily_energy",
            severity=Severity.WARNING,
            message=f"{location} Fridge used more energy than usual.",
        )
        meter.store_data.alerts.append(alert)
        meter.state.active_alerts_by_circuit["fridge"] = [alert]
        meter.state.learning_by_circuit["fridge"] = False
    await hass.async_block_till_done()
    client = await aiohttp_client(
        hass.http.app,
        connector=TCPConnector(resolver=ThreadedResolver()),
    )
    base_url = str(client.make_url("/")).rstrip("/")
    refresh_token = next(iter(hass_admin_user.refresh_tokens.values()))
    coordinator = hass.data[DOMAIN]["browser-kitchen"]
    coordinator.store_data.baselines["fridge:real_power"] = BaselineStats(
        feature="real_power",
        sample_count=5,
        median=84.0,
        mad=2.0,
        p10=80.0,
        p90=88.0,
        confidence=0.8,
    )
    before = dict(coordinator.store_data.baselines)

    env = {
        **os.environ,
        "HA_BASE_URL": base_url,
        "HA_ACCESS_TOKEN": hass_access_token,
        "HA_REFRESH_TOKEN": refresh_token.token,
        "HA_CLIENT_ID": refresh_token.client_id or base_url,
        "HA_CONFIG_ENTRY_ID": coordinator.entry_id,
        "HA_SHARED_ALERT_ID": notification_id_for_alert(alert),
    }
    root = Path(__file__).parents[1]
    process = await asyncio.create_subprocess_exec(
        "node",
        str(root / "node_modules" / "@playwright" / "test" / "cli.js"),
        "test",
        "tests/e2e/ha-panel.spec.js",
        "--project=Home Assistant Chromium",
        cwd=root,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    timed_out = False
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=90)
    except TimeoutError:
        process.kill()
        stdout, _ = await process.communicate()
        timed_out = True
    active_coordinator = hass.data[DOMAIN][coordinator.entry_id]
    mutated = active_coordinator.store_data.baselines == {}
    dashboard_action = active_coordinator.store_data.dashboard_status.get("action")
    if dashboard_action is not None:
        await active_coordinator.async_remove_dashboard()
    active_coordinator.store_data.baselines = before
    await active_coordinator._store.async_save()
    error_records = [
        record for record in caplog.records if record.levelno >= logging.ERROR
    ]
    log_path = root / "test-results" / "browser" / "ha" / "home-assistant.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "\n".join(record.getMessage() for record in caplog.records),
        encoding="utf-8",
    )
    if timed_out:
        pytest.fail(f"Playwright timed out:\n{stdout.decode(errors='replace')}")
    assert process.returncode == 0, stdout.decode(errors="replace")
    assert mutated
    assert dashboard_action == "updated"
    assert not active_coordinator.store_data.alert_feedback
    garage = hass.data[DOMAIN]["browser-garage"]
    assert any(
        record["action"] == "expected"
        and record["source_alert_id"] == env["HA_SHARED_ALERT_ID"]
        for record in garage.store_data.alert_feedback.values()
    )
    assert not error_records


def _point_custom_components_at_worktree(monkeypatch: pytest.MonkeyPatch) -> None:
    import custom_components

    monkeypatch.setattr(
        custom_components,
        "__path__",
        [str(Path(__file__).parents[1] / "custom_components")],
    )
