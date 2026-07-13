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
from custom_components.circuitsetup_energy_analyzer.models import BaselineStats


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
    hass.states.async_set(
        "sensor.fridge_power",
        "84",
        {"unit_of_measurement": "W", "device_class": "power"},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="browser-entry",
        title="Browser Gate",
        data={
            "source_entities": ["sensor.fridge_power"],
            "circuits": [
                {
                    "circuit_id": "fridge",
                    "name": "Kitchen Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"}
                    ],
                }
            ],
        },
    )
    entry.add_to_hass(hass)

    assert await async_setup_component(hass, "frontend", {})
    hass.data["onboarding"].onboarded = True
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    client = await aiohttp_client(
        hass.http.app,
        connector=TCPConnector(resolver=ThreadedResolver()),
    )
    base_url = str(client.make_url("/")).rstrip("/")
    refresh_token = next(iter(hass_admin_user.refresh_tokens.values()))
    coordinator = hass.data[DOMAIN][entry.entry_id]
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
        "HA_CONFIG_ENTRY_ID": entry.entry_id,
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
    active_coordinator = hass.data[DOMAIN][entry.entry_id]
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
    assert not error_records


def _point_custom_components_at_worktree(monkeypatch: pytest.MonkeyPatch) -> None:
    import custom_components

    monkeypatch.setattr(
        custom_components,
        "__path__",
        [str(Path(__file__).parents[1] / "custom_components")],
    )
