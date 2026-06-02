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
    EventType,
    Severity,
)


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
