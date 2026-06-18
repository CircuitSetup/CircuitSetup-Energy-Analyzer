from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

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
    assert len(fixture.samples) == 13


@pytest.mark.parametrize(
    "fixture_name",
    [
        "normal_refrigerator_week",
        "refrigerator_energy_drift",
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
    assert "| Fixtures | 2 |" in report
    assert "normal_refrigerator_week" in report
    assert "refrigerator_energy_drift" in report


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
