from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

from custom_components.circuitsetup_energy_analyzer.models import (
    CircuitEvent,
    EventType,
)
from custom_components.circuitsetup_energy_analyzer.settings_preview import (
    SUPPORTED_SETTING_KEYS,
    build_setting_impact_preview,
    setting_preview_observations,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData

PANEL_JS = (
    Path(__file__).parents[1]
    / "custom_components"
    / "circuitsetup_energy_analyzer"
    / "frontend"
    / "energy-analyzer-panel-main.js"
)


def _observation(at: datetime, value: float, label: str) -> dict[str, object]:
    return {"timestamp": at.isoformat(), "value": value, "label": label}


def test_threshold_preview_counts_changes_without_mutating_history() -> None:
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    observations = [
        _observation(now - timedelta(days=3), 0.2, "Jul 10"),
        _observation(now - timedelta(days=2), 0.3, "Jul 11"),
        _observation(now - timedelta(days=1), 0.4, "Jul 12"),
    ]
    before = deepcopy(observations)

    preview = build_setting_impact_preview(
        "daily_spike_ratio",
        0.25,
        0.35,
        observations,
        now=now,
    )

    assert observations == before
    assert preview.observations_evaluated == 3
    assert preview.current_alert_count == 2
    assert preview.candidate_alert_count == 1
    assert preview.examples_removed == ("Jul 11",)
    assert preview.examples_added == ()
    assert preview.history_start == now - timedelta(days=3)
    assert preview.history_end == now - timedelta(days=1)


def test_preview_is_bounded_by_age_and_sample_count() -> None:
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    observations = [
        _observation(now - timedelta(days=20), 1000.0, "too old"),
        *[
            _observation(
                now - timedelta(minutes=501 - index),
                float(index),
                f"sample {index}",
            )
            for index in range(501)
        ],
    ]

    preview = build_setting_impact_preview(
        "demand_limit_w",
        200.0,
        300.0,
        observations,
        now=now,
    )

    assert preview.observations_evaluated == 500
    assert preview.history_start == now - timedelta(minutes=500)
    assert any("500" in limitation for limitation in preview.limitations)
    assert any("14 days" in limitation for limitation in preview.limitations)


def test_operating_threshold_preview_reports_state_changes() -> None:
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    observations = [
        _observation(now - timedelta(minutes=4), 10.0, "11:56"),
        _observation(now - timedelta(minutes=3), 30.0, "11:57"),
        _observation(now - timedelta(minutes=2), 20.0, "11:58"),
        _observation(now - timedelta(minutes=1), 40.0, "11:59"),
    ]

    preview = build_setting_impact_preview(
        "operating_on_threshold_w",
        25.0,
        35.0,
        observations,
        now=now,
    )

    assert preview.current_state_change_count == 3
    assert preview.candidate_state_change_count == 1


def test_nilm_confidence_threshold_uses_below_threshold_semantics() -> None:
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    observations = [
        _observation(now - timedelta(hours=3), 0.55, "low"),
        _observation(now - timedelta(hours=2), 0.72, "medium"),
        _observation(now - timedelta(hours=1), 0.9, "high"),
    ]

    preview = build_setting_impact_preview(
        "nilm_confidence_threshold",
        0.6,
        0.8,
        observations,
        now=now,
    )

    assert preview.current_alert_count == 1
    assert preview.candidate_alert_count == 2
    assert preview.examples_added == ("medium",)


def test_supported_settings_and_friendly_limitations() -> None:
    assert {
        "daily_spike_ratio",
        "operating_on_threshold_w",
        "operating_off_threshold_w",
        "standby_threshold_w",
        "warning_ratio",
        "capacity_warning_ratio",
        "demand_limit_w",
        "leg_imbalance_warning_ratio",
        "apparent_power_tolerance_percent",
        "power_factor_tolerance",
        "nilm_confidence_threshold",
    } <= SUPPORTED_SETTING_KEYS

    unsupported = build_setting_impact_preview(
        "unknown_setting",
        1,
        2,
        [],
        now=datetime(2026, 7, 13, tzinfo=UTC),
    )
    insufficient = build_setting_impact_preview(
        "standby_threshold_w",
        8,
        10,
        [],
        now=datetime(2026, 7, 13, tzinfo=UTC),
    )

    assert unsupported.available is False
    assert any("not supported" in item for item in unsupported.limitations)
    assert insufficient.available is True
    assert any(
        "Not enough retained history" in item for item in insufficient.limitations
    )


def test_retained_contextual_samples_feed_setting_preview() -> None:
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    store = FeatureStoreData(
        contextual_baseline_samples_by_circuit={
            "ev": [
                {
                    "timestamp": (now - timedelta(days=2)).isoformat(),
                    "feature": "peak_demand_w",
                    "value": 1800.0,
                },
                {
                    "timestamp": (now - timedelta(days=1)).isoformat(),
                    "feature": "peak_demand_w",
                    "value": 2400.0,
                },
            ]
        }
    )

    observations = setting_preview_observations(store, "ev", "demand_limit_w")
    preview = build_setting_impact_preview(
        "demand_limit_w",
        2000.0,
        2500.0,
        observations,
        now=now,
    )

    assert preview.observations_evaluated == 2
    assert preview.current_alert_count == 1
    assert preview.candidate_alert_count == 0


def test_operating_preview_reads_retained_transition_power() -> None:
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    store = FeatureStoreData(
        events=[
            CircuitEvent(
                timestamp=now - timedelta(minutes=2),
                circuit_id="pump",
                event_type=EventType.START,
                features={"startup_power_w": 85.0},
            ),
            CircuitEvent(
                timestamp=now - timedelta(minutes=1),
                circuit_id="pump",
                event_type=EventType.STOP,
                features={"stop_power_w": 12.0},
            ),
        ]
    )

    observations = setting_preview_observations(
        store,
        "pump",
        "operating_on_threshold_w",
    )

    assert [item["value"] for item in observations] == [85.0, 12.0]


def test_panel_renders_bounded_historical_preview_before_apply() -> None:
    source = PANEL_JS.read_text(encoding="utf-8")

    assert "_renderSettingImpactPreview(recommendation)" in source
    assert "recommendation.impact_preview" in source
    assert "recommendations.preview_history" in source
    assert "recommendations.preview_limitations" in source
