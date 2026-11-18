import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.circuitsetup_energy_analyzer.const import CONF_CIRCUITS
from custom_components.circuitsetup_energy_analyzer.coordinator import (
    EnergyAnalyzerCoordinator,
)
from custom_components.circuitsetup_energy_analyzer.models import SensorRole
from custom_components.circuitsetup_energy_analyzer.normalize import STALE_AFTER


def _coordinator(now, readings, *, mode="dual_phase", store_data=None):
    states = {}
    refs = []
    for entity, role, leg, value, unit, updated_at in readings:
        refs.append({"entity_id": entity, "role": role, "leg": leg, "unit": unit})
        states[entity] = SimpleNamespace(
            state=str(value),
            attributes={"unit_of_measurement": unit},
            last_updated=updated_at,
        )
    return EnergyAnalyzerCoordinator(
        SimpleNamespace(states=states, data={}),
        now_fn=lambda: now[0],
        store_data=store_data,
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "dryer",
                    "name": "Dryer",
                    "appliance_profile": "dryer",
                    "mode": mode,
                    "sensors": refs,
                }
            ]
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reading", "age"),
    [("42", STALE_AFTER * 2), ("inf", timedelta()), ("nan", timedelta())],
)
async def test_capacity_history_uses_only_valid_leg_and_peak_currents(reading, age):
    now = [datetime(2026, 11, 1, 12, tzinfo=UTC)]
    coordinator = _coordinator(
        now,
        [
            ("sensor.a", "current", "a", reading, "A", now[0] - age),
            ("sensor.b", "current", "b", 12, "A", now[0]),
            ("sensor.peak", "peak_current", "b", reading, "A", now[0] - age),
        ],
    )
    await coordinator.async_process_update()
    evidence = coordinator.state.capacity_evidence_by_circuit["dryer"]
    assert evidence["current_amps"] == 12.0
    history = coordinator.store_data.demand_by_circuit["dryer"][
        "capacity_current_samples"
    ]
    assert [row["current_amps"] for row in history] == [12.0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("readings", "expected"),
    [
        ([("sensor.l1", "current", "L1", 24)], 24),
        (
            [("sensor.l2", "current", "L2", 24), ("sensor.total", "current", None, 32)],
            24,
        ),
        ([("sensor.total", "current", None, 32)], 16),
        (
            [
                ("sensor.a", "current", "a", 12),
                ("sensor.b", "current", "b", 10),
                ("sensor.peak", "peak_current", None, 31),
            ],
            31,
        ),
        (
            [
                ("sensor.a", "current", "a", 12),
                ("sensor.b", "current", "b", 10),
                ("sensor.peak", "peak_current", None, "nan"),
            ],
            12,
        ),
        (
            [
                ("sensor.a", "current", "a", 24),
                ("sensor.a2", "current", "a", 12),
                ("sensor.b", "current", "b", 10),
            ],
            24,
        ),
    ],
)
async def test_capacity_preserves_configured_current_coverage(readings, expected):
    now = [datetime(2026, 11, 1, 12, tzinfo=UTC)]
    coordinator = _coordinator(now, [(*reading, "A", now[0]) for reading in readings])
    await coordinator.async_process_update()
    assert (
        coordinator.state.capacity_evidence_by_circuit["dryer"]["current_amps"]
        == expected
    )
    history = coordinator.store_data.demand_by_circuit["dryer"][
        "capacity_current_samples"
    ]
    assert [row["current_amps"] for row in history] == [expected]


def test_valid_peak_current_is_normalized_separately_from_rms_current():
    now = [datetime(2026, 11, 1, 12, tzinfo=UTC)]
    coordinator = _coordinator(
        now,
        [
            ("sensor.a", "current", "a", 12, "A", now[0]),
            ("sensor.peak_a", "peak_current", "a", 42000, "mA", now[0]),
            ("sensor.b", "current", "b", 10, "A", now[0]),
            ("sensor.peak_b", "peak_current", "b", 8, "A", now[0]),
        ],
    )
    sample = coordinator.source_samples.sample_for_config(
        coordinator.circuit_configs[0], now[0]
    )
    assert (sample.peak_current, sample.leg_a_current, sample.leg_b_current) == (
        42,
        12,
        10,
    )
    assert sample.current == 22
    assert not sample.quality_issues


@pytest.mark.asyncio
@pytest.mark.parametrize("both_meters", [False, True])
async def test_dual_energy_fallback_depends_on_configured_leg_coverage(both_meters):
    now = [datetime(2026, 11, 1, 12, tzinfo=UTC)]
    readings = [
        ("sensor.a", "real_power", "a", 400, "W", now[0]),
        ("sensor.b", "real_power", "b", 800, "W", now[0]),
        ("sensor.kwh_a", "energy", "a", 100, "kWh", now[0] - timedelta(minutes=3)),
    ]
    if both_meters:
        readings.append(("sensor.kwh_b", "energy", "b", "unavailable", "kWh", now[0]))
    coordinator = _coordinator(now, readings)
    samples = []
    process = coordinator.pipeline._energy_usage_processor.process

    def capture(sample, config, context):
        samples.append(sample)
        return process(sample, config, context)

    coordinator.pipeline._energy_usage_processor.process = capture
    await coordinator.async_process_update()
    now[0] += timedelta(minutes=5)
    for key in ("sensor.a", "sensor.b"):
        coordinator.hass.states[key].last_updated = now[0]
    await coordinator.async_process_update()
    if both_meters:
        assert [s.energy for s in samples] == [None, None]
        coordinator.hass.states["sensor.kwh_b"].state = "300"
        await coordinator.async_process_update()
        assert samples[-1].energy == 400
        assert coordinator.state.daily_energy_usage_by_circuit["dryer"] == 0
    else:
        assert [s.energy for s in samples] == pytest.approx([0, 0.1])
        assert dict(samples[-1].source_updated_at_by_role)[SensorRole.ENERGY] == now[0]
        assert coordinator.state.daily_energy_usage_by_circuit[
            "dryer"
        ] == pytest.approx(0.1)


@pytest.mark.parametrize("mode", ["dual_phase", "mains_nilm"])
def test_power_factor_weights_leg_percentages_by_apparent_power(mode):
    now = [datetime(2026, 11, 1, 12, tzinfo=UTC)]
    coordinator = _coordinator(
        now,
        [
            ("sensor.pf_a", "power_factor", "a", 95, "%", now[0]),
            ("sensor.pf_b", "power_factor", "b", 0.5, None, now[0]),
            ("sensor.va_a", "apparent_power", "a", 900, "VA", now[0]),
            ("sensor.va_b", "apparent_power", "b", 100, "VA", now[0]),
        ],
        mode=mode,
    )

    def sample():
        return coordinator.source_samples.sample_for_config(
            coordinator.circuit_configs[0], now[0]
        )

    assert sample().power_factor == pytest.approx(0.905)
    coordinator.hass.states["sensor.va_b"].state = "unavailable"
    assert sample().power_factor is None


@pytest.mark.asyncio
async def test_startup_and_silent_expiry_refresh_only_displayed_power(monkeypatch):
    now = [datetime(2026, 11, 1, 12, tzinfo=UTC)]
    coordinator = _coordinator(
        now,
        [
            (
                "sensor.a",
                "real_power",
                "a",
                100,
                "W",
                now[0] - STALE_AFTER + timedelta(milliseconds=80),
            ),
            ("sensor.b", "real_power", "b", 200, "W", now[0]),
        ],
    )
    coordinator.async_process_update = AsyncMock()
    timers = []
    loop = asyncio.get_running_loop()
    call_later = loop.call_later

    def record_timer(delay, callback, *args, **kwargs):
        if callback == coordinator.refresh_source_values:
            handle = Mock()
            timers.append((delay, callback, handle))
            return handle
        return call_later(delay, callback, *args, **kwargs)

    monkeypatch.setattr(loop, "call_later", record_timer)
    await coordinator.async_start(("sensor.a", "sensor.b"))
    try:
        assert coordinator.state.latest_real_power_w_by_circuit == {"dryer": 300.0}
        delay, expire, _ = timers.pop()
        assert delay == pytest.approx(0.080001)
        now[0] += timedelta(seconds=1)
        expire()
        assert coordinator.state.latest_real_power_w_by_circuit == {}
        observation = coordinator.state.latest_real_power_observation_by_circuit[
            "dryer"
        ]
        assert not observation.available
        assert "sensor.a stale" in observation.quality_flags
        assert timers == []
        coordinator.async_process_update.assert_not_awaited()

        coordinator.hass.states["sensor.a"].last_updated = now[0]
        await coordinator.async_ingest_source_update(changed_entities=("sensor.a",))
        assert coordinator.state.latest_real_power_w_by_circuit == {"dryer": 300.0}
        delay, _, pending = timers.pop()
        assert delay == pytest.approx(STALE_AFTER.total_seconds() - 1 + 0.000001)
    finally:
        await coordinator.async_stop()
    pending.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_switching_meter_coverage_preserves_the_accumulated_usage():
    now = [datetime(2026, 11, 1, 12, tzinfo=UTC)]

    def configured(both_meters, history=None):
        readings = [
            ("sensor.a", "real_power", "a", 400, "W", now[0]),
            ("sensor.b", "real_power", "b", 800, "W", now[0]),
            ("sensor.kwh_a", "energy", "a", 100, "kWh", now[0]),
        ]
        if both_meters:
            readings.append(("sensor.kwh_b", "energy", "b", 300, "kWh", now[0]))
        return _coordinator(now, readings, store_data=history)

    measured = configured(True)
    await measured.async_process_update()
    assert (
        measured.store_data.energy_usage_by_circuit["dryer"]["last_energy_kwh"] == 400
    )

    derived = configured(False, measured.store_data)
    await derived.async_process_update()
    now[0] += timedelta(minutes=5)
    for key in ("sensor.a", "sensor.b"):
        derived.hass.states[key].last_updated = now[0]
    await derived.async_process_update()
    assert derived.store_data.energy_usage_by_circuit["dryer"][
        "last_energy_kwh"
    ] == pytest.approx(400.1)

    measured = configured(True, derived.store_data)
    measured.hass.states["sensor.kwh_b"].state = "900"
    await measured.async_process_update()
    assert measured.store_data.energy_usage_by_circuit["dryer"][
        "last_energy_kwh"
    ] == pytest.approx(400.1)
    now[0] += timedelta(minutes=1)
    measured.hass.states["sensor.kwh_b"].state = "900.2"
    await measured.async_process_update()
    assert measured.state.daily_energy_usage_by_circuit["dryer"] == pytest.approx(0.3)
    assert (
        "energy_source" not in measured.state.energy_usage_evidence_by_circuit["dryer"]
    )
