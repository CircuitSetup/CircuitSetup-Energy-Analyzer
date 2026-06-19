from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

CONF_CIRCUITS = "circuits"
CONF_SOURCE_ENTITIES = "source_entities"
DOMAIN = "circuitsetup_energy_analyzer"
LIFECYCLE_LOG_BLOCKLIST = (
    "traceback",
    "duplicate entity",
    "duplicate service",
    "duplicate listener",
    "duplicate panel",
    "blocking i/o",
    "coroutine was never awaited",
    "was never awaited",
    "coroutine-not-awaited",
    "unhandled homeassistanterror",
    "translation failure",
    "invalid dashboard entity",
)


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.asyncio
async def test_config_entry_setup_reload_unload_lifecycle(
    hass: Any,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    recwarn: Any,
) -> None:
    """Exercise a real Home Assistant config-entry lifecycle."""

    caplog.set_level(logging.WARNING)

    import custom_components

    monkeypatch.setattr(
        custom_components,
        "__path__",
        [str(Path(__file__).parents[1] / "custom_components")],
    )
    hass.states.async_set(
        "sensor.fridge_power",
        "84",
        {"unit_of_measurement": "W", "device_class": "power"},
    )
    hass.states.async_set(
        "sensor.fridge_energy",
        "120.5",
        {"unit_of_measurement": "kWh", "device_class": "energy"},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="lifecycle-entry",
        title="Lifecycle Gate",
        data={
            CONF_SOURCE_ENTITIES: [
                "sensor.fridge_power",
                "sensor.fridge_energy",
            ],
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Kitchen Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {
                            "entity_id": "sensor.fridge_power",
                            "role": "real_power",
                        },
                        {
                            "entity_id": "sensor.fridge_energy",
                            "role": "energy",
                        },
                    ],
                }
            ],
        },
        options={},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.started is True
    assert coordinator.source_entities == (
        "sensor.fridge_power",
        "sensor.fridge_energy",
    )

    assert await hass.config_entries.async_reload(entry.entry_id) is True
    await hass.async_block_till_done()

    reloaded_coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.started is False
    assert reloaded_coordinator is not coordinator
    assert reloaded_coordinator.started is True
    assert reloaded_coordinator.source_entities == coordinator.source_entities

    assert await hass.config_entries.async_unload(entry.entry_id) is True
    await hass.async_block_till_done()

    assert reloaded_coordinator.started is False
    assert entry.entry_id not in hass.data[DOMAIN]

    remove_result = await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert remove_result.get("require_restart") is False
    assert hass.config_entries.async_get_entry(entry.entry_id) is None
    assert entry.entry_id not in hass.data.get(DOMAIN, {})
    assert _unexpected_lifecycle_log_messages(caplog.records) == []
    assert _unexpected_lifecycle_warning_messages(recwarn) == []


def _unexpected_lifecycle_log_messages(
    records: list[logging.LogRecord],
) -> list[str]:
    messages: list[str] = []
    for record in records:
        message = record.getMessage()
        if (
            record.levelno >= logging.ERROR
            or record.exc_info is not None
            or _contains_lifecycle_hazard(message)
        ):
            messages.append(message)
    return messages


def _unexpected_lifecycle_warning_messages(warnings: Any) -> list[str]:
    messages: list[str] = []
    for warning in warnings:
        message = str(warning.message)
        if _contains_lifecycle_hazard(message):
            messages.append(message)
    return messages


def _contains_lifecycle_hazard(message: str) -> bool:
    normalized = _normalize_lifecycle_hazard_text(message)
    return any(
        _normalize_lifecycle_hazard_text(fragment) in normalized
        for fragment in LIFECYCLE_LOG_BLOCKLIST
    )


def _normalize_lifecycle_hazard_text(message: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", message.lower()).split())
