from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from custom_components.circuitsetup_energy_analyzer.models import EventType
from tests.helpers.calibration import (
    CALIBRATION_CONFIDENCE_BINS,
    assert_fixture_expectations,
    evaluate_replay_result,
    load_calibration_fixture,
    replay_fixture_processors,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "calibration"


def test_calibration_fixture_loader_expands_compact_segments() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_refrigerator_week.yaml")

    assert fixture.schema_version == 1
    assert fixture.id == "normal_refrigerator_week"
    assert fixture.circuits[0].circuit_id == "refrigerator"
    assert fixture.circuits[0].name == "Refrigerator"
    assert fixture.samples[0].timestamp == datetime(
        2026,
        1,
        1,
        0,
        0,
        tzinfo=UTC,
    )
    assert fixture.samples[-1].states["sensor.refrigerator_energy"] == pytest.approx(
        110.0
    )
    assert len(fixture.samples) == 15


@pytest.mark.parametrize(
    "fixture_name",
    [
        "normal_refrigerator_week",
        "refrigerator_energy_drift",
        "normal_washer_cycle",
        "normal_dishwasher_cycle",
        "normal_microwave_cycle",
        "normal_kettle_cycle",
        "normal_sump_pump_cycle",
        "normal_ev_charger_session",
        "normal_dryer_heat_cycle",
        "refrigerator_non_finite_power",
        "refrigerator_stale_power",
        "hvac_voltage_sag",
    ],
)
def test_calibration_fixture_replay_meets_expectations(fixture_name: str) -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / f"{fixture_name}.yaml")
    result = replay_fixture_processors(fixture)
    metrics = assert_fixture_expectations(fixture, result)

    assert metrics.fixture_id == fixture_name
    assert set(metrics.confidence_bins) == set(CALIBRATION_CONFIDENCE_BINS)


def test_normal_fixture_has_no_false_positive_alerts() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_refrigerator_week.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)

    assert result.alerts == []
    assert metrics.false_positive_alerts == 0
    assert metrics.true_negative_windows == 1


def test_abnormal_fixture_detects_expected_alert_with_latency() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "refrigerator_energy_drift.yaml")
    result = replay_fixture_processors(fixture)
    metrics = assert_fixture_expectations(fixture, result)

    assert [alert.feature for alert in result.alerts] == [
        "daily_energy_usage_spike"
    ]
    assert metrics.true_positive_alerts == 1
    assert metrics.false_negative_alerts == 0
    assert metrics.detection_latency_seconds == 172800.0
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0


def test_washer_fixture_exercises_pause_without_split_cycle() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_washer_cycle.yaml")
    pause_samples = [
        sample
        for sample in fixture.samples
        if 60 < sample.t < 300
        and float(sample.states.get("sensor.washer_power", 0.0)) < 8.0
    ]

    result = replay_fixture_processors(fixture)
    event_types = [
        event.event_type
        for event in result.events
        if event.circuit_id == "washer"
    ]

    assert pause_samples
    assert event_types == [EventType.START, EventType.STOP]


def test_dishwasher_fixture_exercises_wash_and_dry_cycle_without_alerts() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_dishwasher_cycle.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    events = [event for event in result.events if event.circuit_id == "dishwasher"]

    assert fixture.circuits[0].circuit_id == "dishwasher"
    assert fixture.circuits[0].name == "Dishwasher"
    assert [event.event_type for event in events] == [EventType.START, EventType.STOP]
    assert [
        int((event.timestamp - fixture.start_time).total_seconds())
        for event in events
    ] == [60, 3600]
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_microwave_fixture_exercises_short_heat_cycle_without_alerts() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_microwave_cycle.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    event_offsets = [
        int((event.timestamp - fixture.start_time).total_seconds())
        for event in result.events
        if event.circuit_id == "microwave"
    ]

    assert fixture.circuits[0].appliance_profile == "microwave"
    assert event_offsets == [60, 180]
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_kettle_fixture_exercises_short_resistive_cycle_without_alerts() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_kettle_cycle.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    event_offsets = [
        int((event.timestamp - fixture.start_time).total_seconds())
        for event in result.events
        if event.circuit_id == "kettle"
    ]

    assert fixture.circuits[0].name == "Kettle"
    assert fixture.circuits[0].appliance_profile == "resistive_load"
    assert event_offsets == [60, 240]
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_sump_pump_fixture_exercises_short_pump_cycle_without_alerts() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_sump_pump_cycle.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    event_offsets = [
        int((event.timestamp - fixture.start_time).total_seconds())
        for event in result.events
        if event.circuit_id == "sump_pump"
    ]

    assert fixture.circuits[0].appliance_profile == "sump_pump"
    assert event_offsets == [60, 180]
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_ev_charger_fixture_exercises_long_session_without_alerts() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_ev_charger_session.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    event_types = [
        event.event_type
        for event in result.events
        if event.circuit_id == "ev_charger"
    ]
    event_offsets = [
        int((event.timestamp - fixture.start_time).total_seconds())
        for event in result.events
        if event.circuit_id == "ev_charger"
    ]

    assert fixture.circuits[0].appliance_profile == "ev_charger"
    assert fixture.circuits[0].mode == "dual_phase"
    assert event_types == [EventType.START, EventType.STOP]
    assert event_offsets == [60, 3660]
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_dryer_fixture_exercises_heat_cycle_without_alerts() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "normal_dryer_heat_cycle.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    event_types = [
        event.event_type
        for event in result.events
        if event.circuit_id == "dryer"
    ]
    event_offsets = [
        int((event.timestamp - fixture.start_time).total_seconds())
        for event in result.events
        if event.circuit_id == "dryer"
    ]

    assert fixture.circuits[0].appliance_profile == "dryer"
    assert fixture.circuits[0].mode == "dual_phase"
    assert event_types == [EventType.START, EventType.STOP]
    assert event_offsets == [60, 3660]
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_non_finite_fixture_records_quality_issue_without_alerts() -> None:
    fixture = load_calibration_fixture(
        FIXTURE_DIR / "refrigerator_non_finite_power.yaml"
    )
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    event_offsets = [
        int((event.timestamp - fixture.start_time).total_seconds())
        for event in result.events
        if event.circuit_id == "refrigerator_non_finite"
    ]

    assert result.setup_issues == [
        {
            "timestamp": fixture.start_time.isoformat(),
            "circuit_id": "refrigerator_non_finite",
            "issue": "sensor.refrigerator_non_finite_power non_finite",
        }
    ]
    assert event_offsets == [120, 240]
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_stale_numeric_fixture_records_quality_issue_and_recovers() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "refrigerator_stale_power.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    event_offsets = [
        int((event.timestamp - fixture.start_time).total_seconds())
        for event in result.events
        if event.circuit_id == "refrigerator_stale"
    ]

    assert result.setup_issues == [
        {
            "timestamp": (
                fixture.start_time + timedelta(seconds=60)
            ).isoformat(),
            "circuit_id": "refrigerator_stale",
            "issue": "sensor.refrigerator_stale_power stale",
        }
    ]
    assert event_offsets == [120, 240]
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_voltage_sag_fixture_emits_power_quality_event_without_alerts() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "hvac_voltage_sag.yaml")
    result = replay_fixture_processors(fixture)
    metrics = evaluate_replay_result(fixture, result)
    events = [event for event in result.events if event.circuit_id == "hvac"]

    assert [event.event_type for event in events] == [
        EventType.START,
        EventType.VOLTAGE_SAG,
        EventType.STOP,
    ]
    assert [
        int((event.timestamp - fixture.start_time).total_seconds())
        for event in events
    ] == [60, 180, 300]
    assert events[1].features["voltage"] == pytest.approx(220.0)
    assert events[1].features["nominal_voltage"] == pytest.approx(240.0)
    assert events[1].features["real_power_w"] == pytest.approx(3600.0)
    assert result.alerts == []
    assert metrics.false_positive_alerts == 0


def test_duplicate_expected_feature_alert_counts_as_false_positive() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "refrigerator_energy_drift.yaml")
    result = replay_fixture_processors(fixture)
    result.alerts.append(result.alerts[0])

    metrics = evaluate_replay_result(fixture, result)

    assert metrics.true_positive_alerts == 1
    assert metrics.false_positive_alerts == 1
    assert metrics.precision == 0.5


def test_out_of_window_expected_feature_alert_counts_as_false_positive() -> None:
    fixture = load_calibration_fixture(FIXTURE_DIR / "refrigerator_energy_drift.yaml")
    result = replay_fixture_processors(fixture)
    expected = fixture.labels.expected_alerts[0]
    result.alerts.append(
        replace(
            result.alerts[0],
            timestamp=fixture.start_time
            + timedelta(seconds=expected.latest_t + 60),
        )
    )

    metrics = evaluate_replay_result(fixture, result)

    assert metrics.true_positive_alerts == 1
    assert metrics.false_positive_alerts == 1
    assert metrics.precision == 0.5


def test_calibration_report_markdown_lists_fixture_metrics() -> None:
    from scripts.calibrate_confidence import build_markdown_report, run_calibration

    metrics = run_calibration(FIXTURE_DIR)
    report = build_markdown_report(
        metrics,
        generated_at=datetime(2026, 6, 17, 12, 0, tzinfo=UTC),
    )

    assert "# Confidence Calibration Report" in report
    assert "| Fixtures | 12 |" in report
    assert "normal_refrigerator_week" in report
    assert "refrigerator_energy_drift" in report
    assert "normal_washer_cycle" in report
    assert "normal_dishwasher_cycle" in report
    assert "normal_microwave_cycle" in report
    assert "normal_kettle_cycle" in report
    assert "normal_sump_pump_cycle" in report
    assert "normal_ev_charger_session" in report
    assert "normal_dryer_heat_cycle" in report
    assert "refrigerator_non_finite_power" in report
    assert "refrigerator_stale_power" in report
    assert "hvac_voltage_sag" in report


def test_calibration_report_script_runs_directly() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/calibrate_confidence.py",
            "--fixtures",
            str(FIXTURE_DIR),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "# Confidence Calibration Report" in completed.stdout


def test_repository_does_not_keep_qa_docs() -> None:
    assert not (Path(__file__).parents[1] / "docs" / "qa").exists()
