from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_RAIN_SENSOR_ENTITY,
)
from custom_components.circuitsetup_energy_analyzer.managers.context import (
    ProcessingContextBuilder,
)


def _builder(
    *,
    states: dict[str, object] | None = None,
    entry_data: dict[str, object] | None = None,
    options: dict[str, object] | None = None,
    temperature_unit: str = "°F",
) -> ProcessingContextBuilder:
    state_map = states or {}
    hass = SimpleNamespace(
        states=SimpleNamespace(get=state_map.get),
        config=SimpleNamespace(
            time_zone="America/New_York",
            units=SimpleNamespace(temperature_unit=temperature_unit),
        ),
    )
    coordinator = SimpleNamespace(
        hass=hass,
        entry_data=entry_data or {},
        options=options or {},
    )
    return ProcessingContextBuilder(coordinator)


def test_context_builder_reads_configured_context_entities() -> None:
    builder = _builder(
        entry_data={CONF_RAIN_SENSOR_ENTITY: "binary_sensor.entry_rain"},
        options={
            CONF_RAIN_SENSOR_ENTITY: "binary_sensor.option_rain",
            CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.outdoor_temp",
        },
    )

    assert builder.configured_context_entity(CONF_RAIN_SENSOR_ENTITY) == (
        "binary_sensor.option_rain"
    )
    assert builder.outdoor_temperature_entity() == "sensor.outdoor_temp"


def test_context_builder_parses_binary_numeric_and_units() -> None:
    builder = _builder(
        states={
            "binary_sensor.rain": SimpleNamespace(state="wet", attributes={}),
            "sensor.flow": SimpleNamespace(
                state="2.5",
                attributes={"unit_of_measurement": "gal/min"},
            ),
            "sensor.unknown": SimpleNamespace(state="maybe", attributes=[]),
        },
    )

    assert builder.binary_entity_active("binary_sensor.rain") is True
    assert builder.binary_entity_active("sensor.unknown") is None
    assert builder.numeric_entity_value("sensor.flow") == 2.5
    assert builder.entity_unit_of_measurement("sensor.flow") == "gal/min"
    assert builder.entity_unit_of_measurement("sensor.unknown") is None


def test_context_builder_tracks_flow_activity_windows() -> None:
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    builder = _builder(
        states={
            "sensor.active_flow": SimpleNamespace(
                state="1.2",
                last_changed=now - timedelta(minutes=4),
                attributes={},
            ),
            "binary_sensor.recent_flow": SimpleNamespace(
                state="off",
                last_changed=now - timedelta(minutes=20),
                attributes={},
            ),
        },
    )

    assert builder.flow_entity_active("sensor.active_flow") is True
    assert builder.flow_entity_active_minutes("sensor.active_flow", now) == 4.0
    assert builder.max_flow_active_minutes(("sensor.active_flow",), now) == 4.0
    assert builder.recent_flow_context_minutes(
        ("binary_sensor.recent_flow",),
        now,
        10,
    ) == 10


def test_context_builder_normalizes_temperature_readings() -> None:
    builder = _builder(
        states={
            "sensor.outdoor": SimpleNamespace(
                state="20",
                attributes={"unit_of_measurement": "°C"},
            ),
        },
        temperature_unit="°C",
    )

    assert builder.temperature_reading_for_entity("sensor.outdoor") == {
        "temperature_f": 68.0,
        "display_temperature": 20.0,
        "display_unit": "°C",
        "source_unit": "°C",
    }
