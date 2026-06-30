from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_DASHBOARD_LAYOUT,
    DASHBOARD_LAYOUT_EXPERT,
    DASHBOARD_LAYOUT_STANDARD,
)
from custom_components.circuitsetup_energy_analyzer.managers import (
    dashboard_controller,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    SensorRef,
    SensorRole,
)


class _FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def async_fire(self, event_type: str, payload: dict[str, object]) -> None:
        self.events.append((event_type, payload))


class _FakeConfigEntries:
    def __init__(self) -> None:
        self.updated: list[tuple[object, dict[str, object]]] = []

    def async_update_entry(self, entry: object, *, options: dict[str, object]) -> None:
        self.updated.append((entry, options))


class _DashboardCoordinator:
    def __init__(self) -> None:
        self.entry_id = "entry-1"
        self.dashboard_layout = DASHBOARD_LAYOUT_STANDARD
        self.options: dict[str, object] = {}
        self._config_entry = SimpleNamespace(options={})
        self.hass = SimpleNamespace(
            bus=_FakeBus(),
            config_entries=_FakeConfigEntries(),
        )
        self.circuit_configs = (
            CircuitConfig(
                circuit_id="fridge",
                name="Kitchen Fridge",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),),
            ),
        )
        self.state = SimpleNamespace()
        self.last_dashboard_create_request: dict[str, object] | None = None
        self.last_dashboard_remove_request: dict[str, object] | None = None
        self.created_payload: dict[str, object] | None = None
        self.updated_data: list[object] = []

    def _outdoor_temperature_entity(self) -> str:
        return "sensor.outdoor_temperature"

    async def _async_create_or_update_lovelace_dashboard(
        self,
        payload: dict[str, object],
    ) -> tuple[str, str | None]:
        self.created_payload = payload
        return "created", None

    async def _async_remove_lovelace_dashboard(self) -> tuple[str, str | None]:
        return "deleted", None

    def async_set_updated_data(self, state: object) -> None:
        self.updated_data.append(state)


@pytest.mark.asyncio
async def test_dashboard_controller_creates_dashboard_and_fires_event() -> None:
    coordinator = _DashboardCoordinator()
    controller = dashboard_controller.DashboardController(coordinator)

    payload = await controller.async_create_dashboard()

    assert payload["action"] == "created"
    assert payload["layout"] == DASHBOARD_LAYOUT_STANDARD
    assert coordinator.created_payload is not None
    assert coordinator.last_dashboard_create_request == payload
    assert coordinator.hass.bus.events == [
        ("circuitsetup_energy_analyzer_create_dashboard", payload)
    ]
    assert coordinator.updated_data == [coordinator.state]


@pytest.mark.asyncio
async def test_dashboard_controller_removes_dashboard_and_persists_layout() -> None:
    coordinator = _DashboardCoordinator()
    controller = dashboard_controller.DashboardController(coordinator)

    removed = await controller.async_remove_dashboard()
    await controller.async_set_dashboard_layout(DASHBOARD_LAYOUT_EXPERT)

    assert removed["action"] == "deleted"
    assert coordinator.last_dashboard_remove_request == removed
    assert coordinator.dashboard_layout == DASHBOARD_LAYOUT_EXPERT
    assert coordinator.options[CONF_DASHBOARD_LAYOUT] == DASHBOARD_LAYOUT_EXPERT
    assert coordinator.hass.config_entries.updated == [
        (coordinator._config_entry, {CONF_DASHBOARD_LAYOUT: DASHBOARD_LAYOUT_EXPERT})
    ]
