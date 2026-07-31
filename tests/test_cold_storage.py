from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.alerting import (
    ConservativeAlertPolicy,
)
from custom_components.circuitsetup_energy_analyzer.cold_storage import (
    COLD_STORAGE_MEDIAN_CURRENT_FEATURE,
    COLD_STORAGE_MEDIAN_POWER_FEATURE,
    COLD_STORAGE_PF_PEAK_DELTA_FEATURE,
    COLD_STORAGE_SIGNATURE_FEATURE,
    ColdStorageWindowAccumulator,
    ColdStorageWindowSummary,
    select_cold_storage_signature_evidence,
)
from custom_components.circuitsetup_energy_analyzer.const import DOMAIN
from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    BaselineStats,
    CircuitConfig,
    CircuitMode,
    CircuitSample,
)
from custom_components.circuitsetup_energy_analyzer.normalize import (
    NormalizedCircuitSample,
)
from custom_components.circuitsetup_energy_analyzer.processors.base import (
    ProcessingContext,
)
from custom_components.circuitsetup_energy_analyzer.processors.cycles import (
    RunCycleProcessor,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData

START = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def _sample(minute: int, *, watts: float, amps: float, pf: float) -> CircuitSample:
    return CircuitSample(
        timestamp=START + timedelta(minutes=minute),
        circuit_id="fridge",
        real_power=watts,
        current=amps,
        power_factor=pf,
    )


def test_window_summary_captures_correlated_pf_power_current_pulse() -> None:
    accumulator = ColdStorageWindowAccumulator()
    for minute in (0, 5, 10, 15, 20, 25):
        pulse = minute in {0, 20}
        assert (
            accumulator.observe(
                _sample(
                    minute,
                    watts=160.0 if pulse else 100.0,
                    amps=1.9 if pulse else 1.2,
                    pf=0.86 if pulse else 0.60,
                )
            )
            is None
        )

    summary = accumulator.observe(_sample(30, watts=100.0, amps=1.2, pf=0.60))

    assert summary is not None
    assert summary.valid is True
    assert summary.sample_count == 6
    assert summary.coverage_seconds == 1500.0
    assert summary.max_sample_gap_seconds == 300.0
    assert summary.pf_peak_delta == 0.26
    assert summary.median_power_w == 100.0
    assert summary.median_current_a == 1.2
    assert summary.power_span_w == 60.0
    assert summary.current_span_a == 0.7


def test_window_summary_rejects_sparse_or_missing_three_signal_data() -> None:
    accumulator = ColdStorageWindowAccumulator()
    for minute in (0, 15, 25):
        accumulator.observe(_sample(minute, watts=100.0, amps=1.2, pf=0.60))

    summary = accumulator.observe(_sample(30, watts=100.0, amps=1.2, pf=0.60))

    assert summary is not None
    assert summary.valid is False
    assert (
        accumulator.observe(
            CircuitSample(
                timestamp=START + timedelta(minutes=35),
                circuit_id="fridge",
                real_power=100.0,
                current=1.2,
                power_factor=None,
            )
        )
        is None
    )
    missing_summary = accumulator.observe(_sample(60, watts=100.0, amps=1.2, pf=0.60))
    assert missing_summary is not None
    assert missing_summary.valid is False


def _baseline(feature: str, median_value: float) -> BaselineStats:
    return BaselineStats(
        feature=feature,
        sample_count=96,
        median=median_value,
        mad=max(abs(median_value) * 0.02, 0.001),
        p10=median_value * 0.95,
        p90=median_value * 1.05,
        confidence=1.0,
    )


def _signature_baselines() -> dict[str, BaselineStats]:
    return {
        COLD_STORAGE_PF_PEAK_DELTA_FEATURE: _baseline(
            COLD_STORAGE_PF_PEAK_DELTA_FEATURE, 0.26
        ),
        COLD_STORAGE_MEDIAN_POWER_FEATURE: _baseline(
            COLD_STORAGE_MEDIAN_POWER_FEATURE, 100.0
        ),
        COLD_STORAGE_MEDIAN_CURRENT_FEATURE: _baseline(
            COLD_STORAGE_MEDIAN_CURRENT_FEATURE, 1.2
        ),
    }


def _summary(
    *, pf_delta: float, power: float, current: float
) -> ColdStorageWindowSummary:
    return ColdStorageWindowSummary(
        started_at=START,
        ended_at=START + timedelta(minutes=30),
        sample_count=6,
        coverage_seconds=1500.0,
        max_sample_gap_seconds=300.0,
        pf_peak_delta=pf_delta,
        median_power_w=power,
        median_current_a=current,
        power_span_w=25.0,
        current_span_a=0.35,
        valid=True,
    )


def test_signature_evidence_requires_flattened_pf_and_higher_power_and_current() -> (
    None
):
    config = CircuitConfig(
        circuit_id="fridge",
        name="Basement Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )

    evidence = select_cold_storage_signature_evidence(
        config,
        _summary(pf_delta=0.01, power=150.0, current=1.8),
        _signature_baselines(),
    )

    assert evidence is not None
    assert evidence.feature == COLD_STORAGE_SIGNATURE_FEATURE
    assert evidence.observed_value == 0.01
    assert evidence.baseline_value == 0.26
    assert evidence.score >= 1.5
    assert evidence.features["signature_ready"] is True
    assert evidence.features["signature_baseline_windows"] == 96.0
    assert "doors" in evidence.message.lower()


def test_signature_evidence_rejects_one_signal_and_non_cold_profiles() -> None:
    refrigerator = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    washer = CircuitConfig(
        circuit_id="washer",
        name="Washer",
        appliance_profile=ApplianceProfile.WASHER,
        mode=CircuitMode.SINGLE_PHASE,
    )
    baselines = _signature_baselines()

    assert (
        select_cold_storage_signature_evidence(
            refrigerator,
            _summary(pf_delta=0.26, power=150.0, current=1.8),
            baselines,
        )
        is None
    )
    assert (
        select_cold_storage_signature_evidence(
            refrigerator,
            _summary(pf_delta=0.01, power=105.0, current=1.8),
            baselines,
        )
        is None
    )
    assert (
        select_cold_storage_signature_evidence(
            washer,
            _summary(pf_delta=0.01, power=150.0, current=1.8),
            baselines,
        )
        is None
    )
    baselines[COLD_STORAGE_PF_PEAK_DELTA_FEATURE] = _baseline(
        COLD_STORAGE_PF_PEAK_DELTA_FEATURE,
        0.05,
    )
    assert (
        select_cold_storage_signature_evidence(
            refrigerator,
            _summary(pf_delta=0.01, power=150.0, current=1.8),
            baselines,
        )
        is None
    )


def test_short_defrost_window_does_not_combine_with_later_signature_changes() -> (
    None
):
    state = AnalyzerState(learning_by_circuit={"fridge": True})
    store_data = FeatureStoreData(
        baselines={
            f"fridge:{feature}": baseline
            for feature, baseline in _signature_baselines().items()
        }
    )
    processor = RunCycleProcessor(
        alert_policy_for_circuit=lambda _circuit_id: ConservativeAlertPolicy(),
        learning_mature=lambda _config, _now: False,
    )
    config = CircuitConfig(
        circuit_id="fridge",
        name="Basement Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    alerts = []

    for minute in range(0, 151, 5):
        abnormal = minute <= 30 or minute >= 95
        pulse = minute % 20 == 0
        now = START + timedelta(minutes=minute)
        result = processor.process(
            NormalizedCircuitSample(
                timestamp=now,
                circuit_id="fridge",
                real_power=(
                    (125.0 if pulse else 150.0)
                    if abnormal
                    else (160.0 if pulse else 100.0)
                ),
                current=(
                    (1.45 if pulse else 1.8)
                    if abnormal
                    else (1.9 if pulse else 1.2)
                ),
                power_factor=0.60 if abnormal else (0.86 if pulse else 0.60),
            ),
            config,
            ProcessingContext(
                now=now,
                hass=SimpleNamespace(data={DOMAIN: {}}),
                state=state,
                store_data=store_data,
                options={},
                entry_data={},
                known_load_circuit_ids=frozenset(),
                sensitivity="standard",
            ),
        )
        alerts.extend(result.alerts)

    assert alerts == []
