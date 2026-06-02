# Power Quality Relationship Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-circuit reactive power, apparent power, power factor, and W/VAR/VA/PF relationship analysis with conservative evidence-based alerts.

**Architecture:** Add a pure Python `power_quality.py` module for feature extraction, multivariate scoring, and evidence selection. Extend the existing alert policy so it can carry custom evidence messages, then replace coordinator real-power-only observation with power-quality observation while preserving real-power-only behavior.

**Tech Stack:** Python 3.13, Home Assistant custom integration APIs, pytest, ruff, existing analyzer dataclasses, existing `BaselineStats`, existing `ConservativeAlertPolicy`.

---

## Source References

- Design spec: `docs/superpowers/specs/2026-06-02-power-quality-relationship-analysis-design.md`
- Current coordinator: `custom_components/circuitsetup_energy_analyzer/coordinator.py`
- Current alert policy: `custom_components/circuitsetup_energy_analyzer/alerting.py`
- Current baseline helpers: `custom_components/circuitsetup_energy_analyzer/baseline.py`
- Current diagnostic sensors: `custom_components/circuitsetup_energy_analyzer/sensor.py`
- IEEE 1459-2025: `https://standards.ieee.org/ieee/1459/7578/`
- NIST TN 2249 heat pump real/reactive power modeling: `https://nvlpubs.nist.gov/nistpubs/TechnicalNotes/NIST.TN.2249.pdf`
- HVAC electrical load monitoring paper: `https://emsg.mit.edu/wp-content/uploads/2024/05/21_Detection-and-Diagnosis-of-HVAC-Faults-via-Electrical-Load-Monitoring.pdf`
- Induction motor PF paper: `https://bura.brunel.ac.uk/handle/2438/16671`
- Multivariate NILM feature paper: `https://www.mdpi.com/1996-1073/18/9/2369`

## File Structure

Modify these files:

```text
custom_components/circuitsetup_energy_analyzer/
  alerting.py        # Add optional custom evidence message/features to Observation.
  coordinator.py     # Replace real-power-only observer with power-quality observer.
  sensor.py          # Add diagnostic power-quality sensors.

Create these files:

custom_components/circuitsetup_energy_analyzer/
  power_quality.py   # Pure feature extraction, scoring, and evidence selection.

Modify tests:

tests/
  test_alerting.py       # Custom alert evidence behavior.
  test_power_quality.py  # Pure unit tests for W/VAR/VA/PF relationships.
  test_coordinator.py    # Runtime learning, maturity, alerts, mixed circuit behavior.
  test_entities.py       # New diagnostic sensor helpers and entity setup.

Modify docs:

docs/dashboard-example.yaml
```

## Implementation Tasks

### Task 1: Alert Policy Can Preserve Custom Evidence

**Files:**
- Modify: `tests/test_alerting.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/alerting.py`

- [ ] **Step 1: Write the failing alerting test**

Append this test to `tests/test_alerting.py`:

```python
def test_policy_preserves_custom_power_quality_evidence() -> None:
    policy = ConservativeAlertPolicy(min_repeated=3, min_baseline_confidence=0.6)
    now = datetime(2026, 6, 2, tzinfo=UTC)
    message = (
        "Possible issue: reactive power increased while real power stayed near "
        "baseline across recent observations."
    )
    features = {
        "real_power": 0.4,
        "reactive_power": 4.2,
        "reactive_to_real_ratio": 3.8,
        "relationship_rms": 3.4,
    }

    for index in range(2):
        assert policy.observe(
            Observation(
                circuit_id="fridge",
                feature="reactive_shift_under_stable_real_power",
                score=3.4,
                baseline_confidence=1.0,
                observed_at=now + timedelta(minutes=index),
                observed_value=0.44,
                baseline_value=0.16,
                message=message,
                features=features,
            )
        ) is None

    alert = policy.observe(
        Observation(
            circuit_id="fridge",
            feature="reactive_shift_under_stable_real_power",
            score=3.5,
            baseline_confidence=1.0,
            observed_at=now + timedelta(minutes=2),
            observed_value=0.45,
            baseline_value=0.16,
            message=message,
            features=features,
        )
    )

    assert alert is not None
    assert alert.message == message
    assert alert.feature == "reactive_shift_under_stable_real_power"
    assert alert.features["reactive_power"] == 4.2
    assert alert.features["relationship_rms"] == 3.4
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m pytest tests/test_alerting.py::test_policy_preserves_custom_power_quality_evidence -q
```

Expected: FAIL with `TypeError: Observation.__init__() got an unexpected keyword argument 'message'`.

- [ ] **Step 3: Implement custom evidence fields**

In `custom_components/circuitsetup_energy_analyzer/alerting.py`, replace the imports and `Observation` class with:

```python
from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Self

from .models import AlertEvidence, Severity


@dataclass(frozen=True, slots=True)
class Observation:
    """Single scored baseline deviation observation."""

    circuit_id: str
    feature: str
    score: float
    baseline_confidence: float
    observed_at: datetime
    observed_value: float = 0.0
    baseline_value: float = 0.0
    message: str = ""
    features: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))
```

Then in `ConservativeAlertPolicy.observe`, replace the alert construction block from `feature_words = ...` through `features={last.feature: last.score},` with:

```python
        feature_words = observation.feature.replace("_", " ")
        message = last.message or (
            f"Possible issue: {feature_words} shows evidence of a "
            f"learned-baseline change across {len(observations)} recent "
            "observations."
        )
        features = dict(last.features) if last.features else {last.feature: last.score}

        return AlertEvidence(
            timestamp=last.observed_at,
            circuit_id=last.circuit_id,
            severity=Severity.WARNING,
            message=message,
            feature=last.feature,
            observed_value=last.observed_value,
            baseline_value=last.baseline_value,
            change_ratio=change_ratio,
            repeated_count=len(observations),
            first_seen=first.observed_at,
            last_seen=last.observed_at,
            features=features,
        )
```

- [ ] **Step 4: Run alerting tests**

Run:

```powershell
python -m pytest tests/test_alerting.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit alert policy support**

Run:

```powershell
git add custom_components/circuitsetup_energy_analyzer/alerting.py tests/test_alerting.py
git commit -m "feat: preserve custom power quality alert evidence"
```

### Task 2: Power Quality Feature Extraction And Evidence Selection

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/power_quality.py`
- Create: `tests/test_power_quality.py`

- [ ] **Step 1: Write failing pure unit tests**

Create `tests/test_power_quality.py`:

```python
from datetime import UTC, datetime

from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    BaselineStats,
    CircuitConfig,
    CircuitMode,
    CircuitSample,
)
from custom_components.circuitsetup_energy_analyzer.power_quality import (
    extract_power_quality_features,
    relationship_rms_score,
    score_power_quality_features,
    select_power_quality_evidence,
)


NOW = datetime(2026, 6, 2, tzinfo=UTC)


def sample(
    *,
    real_power: float | None = 500.0,
    reactive_power: float | None = 80.0,
    apparent_power: float | None = 506.0,
    power_factor: float | None = 0.98,
) -> CircuitSample:
    return CircuitSample(
        timestamp=NOW,
        circuit_id="fridge",
        real_power=real_power,
        reactive_power=reactive_power,
        apparent_power=apparent_power,
        power_factor=power_factor,
    )


def baseline(feature: str, median: float, mad: float = 5.0) -> BaselineStats:
    return BaselineStats(
        feature=feature,
        sample_count=20,
        median=median,
        mad=mad,
        p10=median - 10.0,
        p90=median + 10.0,
        confidence=1.0,
    )


def config(
    profile: ApplianceProfile = ApplianceProfile.REFRIGERATOR,
    mode: CircuitMode = CircuitMode.SINGLE_PHASE,
) -> CircuitConfig:
    return CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        appliance_profile=profile,
        mode=mode,
    )


def test_extract_power_quality_features_calculates_loaded_relationships() -> None:
    features = extract_power_quality_features(
        sample(real_power=500.0, reactive_power=100.0, apparent_power=510.0, power_factor=0.96)
    )

    assert features["real_power"] == 500.0
    assert features["reactive_power"] == 100.0
    assert features["apparent_power"] == 510.0
    assert features["power_factor"] == 0.96
    assert features["reactive_to_real_ratio"] == 0.2
    assert features["apparent_to_real_ratio"] == 1.02
    assert round(features["power_factor_deficit"], 3) == 0.04
    assert "apparent_power_residual" in features


def test_extract_power_quality_features_suppresses_relationships_below_load_floor() -> None:
    features = extract_power_quality_features(
        sample(real_power=25.0, reactive_power=40.0, apparent_power=47.0, power_factor=0.53)
    )

    assert features["real_power"] == 25.0
    assert features["reactive_power"] == 40.0
    assert "reactive_to_real_ratio" not in features
    assert "apparent_to_real_ratio" not in features
    assert "power_factor" not in features
    assert "power_factor_deficit" not in features


def test_score_power_quality_features_handles_missing_optional_baselines() -> None:
    features = extract_power_quality_features(
        sample(real_power=510.0, reactive_power=180.0, apparent_power=None, power_factor=None)
    )
    scores = score_power_quality_features(
        features,
        {
            "real_power": baseline("real_power", 500.0, 20.0),
            "reactive_power": baseline("reactive_power", 80.0, 10.0),
            "reactive_to_real_ratio": baseline("reactive_to_real_ratio", 0.16, 0.02),
        },
    )

    by_feature = {score.feature: score for score in scores}
    assert set(by_feature) == {"real_power", "reactive_power", "reactive_to_real_ratio"}
    assert by_feature["real_power"].score < 1.0
    assert by_feature["reactive_power"].score > 3.0
    assert relationship_rms_score(scores) > 2.0


def test_select_evidence_finds_reactive_shift_under_stable_real_power() -> None:
    features = extract_power_quality_features(
        sample(real_power=510.0, reactive_power=220.0, apparent_power=560.0, power_factor=0.91)
    )
    scores = score_power_quality_features(
        features,
        {
            "real_power": baseline("real_power", 500.0, 20.0),
            "reactive_power": baseline("reactive_power", 80.0, 10.0),
            "apparent_power": baseline("apparent_power", 506.0, 12.0),
            "power_factor": baseline("power_factor", 0.98, 0.01),
            "reactive_to_real_ratio": baseline("reactive_to_real_ratio", 0.16, 0.02),
            "apparent_to_real_ratio": baseline("apparent_to_real_ratio", 1.01, 0.01),
            "power_factor_deficit": baseline("power_factor_deficit", 0.02, 0.01),
        },
    )

    evidence = select_power_quality_evidence(config(), scores)

    assert evidence is not None
    assert evidence.feature == "reactive_shift_under_stable_real_power"
    assert "reactive power" in evidence.message
    assert "real power stayed" in evidence.message
    assert evidence.features["relationship_rms"] > 2.0


def test_select_evidence_flags_resistive_load_that_became_reactive() -> None:
    scores = score_power_quality_features(
        extract_power_quality_features(
            sample(real_power=4400.0, reactive_power=900.0, apparent_power=4492.0, power_factor=0.88)
        ),
        {
            "real_power": baseline("real_power", 4400.0, 80.0),
            "reactive_power": baseline("reactive_power", 20.0, 8.0),
            "power_factor": baseline("power_factor", 0.99, 0.01),
            "reactive_to_real_ratio": baseline("reactive_to_real_ratio", 0.005, 0.002),
            "power_factor_deficit": baseline("power_factor_deficit", 0.01, 0.005),
        },
    )

    evidence = select_power_quality_evidence(
        config(ApplianceProfile.WATER_HEATER, CircuitMode.DUAL_PHASE),
        scores,
    )

    assert evidence is not None
    assert evidence.feature == "resistive_load_became_reactive"
    assert "resistive" in evidence.message


def test_select_evidence_suppresses_mixed_circuit_appliance_alerts() -> None:
    scores = score_power_quality_features(
        extract_power_quality_features(
            sample(real_power=510.0, reactive_power=220.0, apparent_power=560.0, power_factor=0.91)
        ),
        {
            "real_power": baseline("real_power", 500.0, 20.0),
            "reactive_power": baseline("reactive_power", 80.0, 10.0),
            "reactive_to_real_ratio": baseline("reactive_to_real_ratio", 0.16, 0.02),
        },
    )

    assert select_power_quality_evidence(
        config(ApplianceProfile.MIXED, CircuitMode.MIXED),
        scores,
    ) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_power_quality.py -q
```

Expected: FAIL with import error for `custom_components.circuitsetup_energy_analyzer.power_quality`.

- [ ] **Step 3: Implement `power_quality.py`**

Create `custom_components/circuitsetup_energy_analyzer/power_quality.py`:

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import isfinite, sqrt
from types import MappingProxyType

from .baseline import score_deviation
from .models import ApplianceProfile, BaselineStats, CircuitConfig, CircuitMode, CircuitSample

DEFAULT_LOAD_FLOOR_W = 80.0
MIN_RELATIONSHIP_SCORE = 1.5
STABLE_REAL_POWER_SCORE = 1.2
STABLE_REAL_POWER_RATIO = 0.10

MOTOR_PROFILES = frozenset(
    {
        ApplianceProfile.REFRIGERATOR,
        ApplianceProfile.FREEZER,
        ApplianceProfile.HVAC,
        ApplianceProfile.POOL_PUMP,
        ApplianceProfile.WELL_PUMP,
        ApplianceProfile.SUMP_PUMP,
        ApplianceProfile.MOTOR_LOAD,
    }
)
RESISTIVE_PROFILES = frozenset(
    {
        ApplianceProfile.WATER_HEATER,
        ApplianceProfile.OVEN,
        ApplianceProfile.DRYER,
        ApplianceProfile.RESISTIVE_LOAD,
    }
)


@dataclass(frozen=True, slots=True)
class PowerQualityFeatureScore:
    """Deviation score for one power-quality feature."""

    feature: str
    observed_value: float
    baseline_value: float
    score: float
    baseline_confidence: float
    change_ratio: float


@dataclass(frozen=True, slots=True)
class PowerQualityEvidence:
    """Selected relationship evidence for one circuit observation."""

    feature: str
    message: str
    observed_value: float
    baseline_value: float
    change_ratio: float
    score: float
    baseline_confidence: float
    features: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))


def extract_power_quality_features(
    sample: CircuitSample,
    *,
    load_floor_w: float = DEFAULT_LOAD_FLOOR_W,
) -> dict[str, float]:
    """Extract direct and derived power-quality features from a sample."""
    values: dict[str, float] = {}
    real_power = _number_or_none(getattr(sample, "real_power", None))
    reactive_power = _number_or_none(getattr(sample, "reactive_power", None))
    apparent_power = _number_or_none(getattr(sample, "apparent_power", None))
    power_factor = _number_or_none(getattr(sample, "power_factor", None))

    if real_power is not None:
        values["real_power"] = real_power
    if reactive_power is not None:
        values["reactive_power"] = reactive_power
    if apparent_power is not None:
        values["apparent_power"] = apparent_power

    loaded = real_power is not None and abs(real_power) >= load_floor_w
    if power_factor is not None and loaded:
        values["power_factor"] = power_factor
        values["power_factor_deficit"] = 1.0 - abs(power_factor)

    if loaded and real_power is not None and real_power != 0.0:
        denominator = abs(real_power)
        if reactive_power is not None:
            values["reactive_to_real_ratio"] = reactive_power / denominator
        if apparent_power is not None:
            values["apparent_to_real_ratio"] = apparent_power / denominator

    if loaded and all(
        value is not None for value in (real_power, reactive_power, apparent_power)
    ):
        values["apparent_power_residual"] = apparent_power - sqrt(
            (real_power * real_power) + (reactive_power * reactive_power)
        )

    return values


def score_power_quality_features(
    features: Mapping[str, float],
    baselines: Mapping[str, BaselineStats],
    *,
    min_confidence: float = 0.6,
) -> list[PowerQualityFeatureScore]:
    """Score available power-quality features against learned baselines."""
    scores: list[PowerQualityFeatureScore] = []
    for feature, observed in features.items():
        baseline = baselines.get(feature)
        if baseline is None or baseline.confidence < min_confidence:
            continue
        scores.append(
            PowerQualityFeatureScore(
                feature=feature,
                observed_value=observed,
                baseline_value=baseline.median,
                score=score_deviation(observed, baseline),
                baseline_confidence=baseline.confidence,
                change_ratio=_change_ratio(observed, baseline.median),
            )
        )
    return scores


def relationship_rms_score(scores: Sequence[PowerQualityFeatureScore]) -> float:
    """Return robust RMS score across non-real-power relationship features."""
    relationship_scores = [
        score.score
        for score in scores
        if score.feature
        not in {
            "real_power",
            "apparent_power_residual",
        }
    ]
    if not relationship_scores:
        return 0.0
    return sqrt(sum(score * score for score in relationship_scores) / len(relationship_scores))


def select_power_quality_evidence(
    config: CircuitConfig,
    scores: Sequence[PowerQualityFeatureScore],
    *,
    min_relationship_score: float = MIN_RELATIONSHIP_SCORE,
) -> PowerQualityEvidence | None:
    """Select the strongest user-facing relationship evidence."""
    if config.appliance_profile is ApplianceProfile.MIXED or config.mode is CircuitMode.MIXED:
        return None

    by_feature = {score.feature: score for score in scores}
    real_score = by_feature.get("real_power")
    rms_score = relationship_rms_score(scores)
    if rms_score < min_relationship_score:
        return _real_power_fallback(by_feature)

    stable_real = _real_power_is_stable(real_score)
    evidence_features = {
        score.feature: score.score
        for score in scores
        if score.feature != "apparent_power_residual"
    }
    evidence_features["relationship_rms"] = rms_score

    reactive_score = _strongest(
        by_feature.get("reactive_to_real_ratio"),
        by_feature.get("reactive_power"),
    )
    apparent_score = _strongest(
        by_feature.get("apparent_to_real_ratio"),
        by_feature.get("apparent_power"),
    )
    pf_score = _strongest(
        by_feature.get("power_factor_deficit"),
        by_feature.get("power_factor"),
    )

    if config.appliance_profile in RESISTIVE_PROFILES and _score_high(
        reactive_score,
        min_relationship_score,
    ):
        return _evidence(
            "resistive_load_became_reactive",
            "Possible issue: a mostly resistive circuit shows repeated reactive "
            "power or power-factor behavior that differs from its learned baseline.",
            reactive_score,
            rms_score,
            evidence_features,
        )

    if stable_real and _score_high(reactive_score, min_relationship_score):
        return _evidence(
            "reactive_shift_under_stable_real_power",
            "Possible issue: reactive power changed while real power stayed near "
            "its learned baseline across recent observations.",
            reactive_score,
            rms_score,
            evidence_features,
        )

    if stable_real and _score_high(pf_score, min_relationship_score):
        return _evidence(
            "power_factor_shift_under_load",
            "Possible issue: power factor changed under a similar real-power load "
            "across recent observations.",
            pf_score,
            rms_score,
            evidence_features,
        )

    if stable_real and _score_high(apparent_score, min_relationship_score):
        return _evidence(
            "apparent_power_shift",
            "Possible issue: apparent power changed while real power stayed near "
            "baseline, suggesting more non-real-power burden for similar useful power.",
            apparent_score,
            rms_score,
            evidence_features,
        )

    if config.mode is CircuitMode.DUAL_PHASE and rms_score >= min_relationship_score:
        selected = _strongest(reactive_score, pf_score, apparent_score)
        return _evidence(
            "split_phase_relationship_changed",
            "Possible issue: the combined split-phase W/VAR/VA/PF relationship "
            "changed from its learned baseline across recent observations.",
            selected,
            rms_score,
            evidence_features,
        )

    if config.appliance_profile in MOTOR_PROFILES and rms_score >= min_relationship_score:
        selected = _strongest(reactive_score, pf_score, apparent_score)
        return _evidence(
            "motor_relationship_changed",
            "Possible issue: motor-load W/VAR/VA/PF behavior changed from its "
            "learned baseline across recent observations.",
            selected,
            rms_score,
            evidence_features,
        )

    return _real_power_fallback(by_feature)


def _evidence(
    feature: str,
    message: str,
    selected: PowerQualityFeatureScore | None,
    rms_score: float,
    features: Mapping[str, float],
) -> PowerQualityEvidence | None:
    if selected is None:
        return None
    confidence_values = [
        selected.baseline_confidence,
        *(
            1.0
            for feature_name in features
            if feature_name != "relationship_rms"
        ),
    ]
    return PowerQualityEvidence(
        feature=feature,
        message=message,
        observed_value=selected.observed_value,
        baseline_value=selected.baseline_value,
        change_ratio=selected.change_ratio,
        score=max(selected.score, rms_score),
        baseline_confidence=min(confidence_values) if confidence_values else selected.baseline_confidence,
        features=features,
    )


def _real_power_fallback(
    by_feature: Mapping[str, PowerQualityFeatureScore],
) -> PowerQualityEvidence | None:
    real_score = by_feature.get("real_power")
    if real_score is None or real_score.score < MIN_RELATIONSHIP_SCORE:
        return None
    return PowerQualityEvidence(
        feature="real_power",
        message="",
        observed_value=real_score.observed_value,
        baseline_value=real_score.baseline_value,
        change_ratio=real_score.change_ratio,
        score=real_score.score,
        baseline_confidence=real_score.baseline_confidence,
        features={"real_power": real_score.score},
    )


def _real_power_is_stable(score: PowerQualityFeatureScore | None) -> bool:
    if score is None:
        return True
    return (
        score.score <= STABLE_REAL_POWER_SCORE
        or abs(score.change_ratio) <= STABLE_REAL_POWER_RATIO
    )


def _score_high(score: PowerQualityFeatureScore | None, threshold: float) -> bool:
    return score is not None and score.score >= threshold


def _strongest(
    *scores: PowerQualityFeatureScore | None,
) -> PowerQualityFeatureScore | None:
    available = [score for score in scores if score is not None]
    if not available:
        return None
    return max(available, key=lambda score: score.score)


def _change_ratio(observed: float, baseline: float) -> float:
    if baseline == 0.0:
        return 0.0
    return (observed - baseline) / baseline


def _number_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not isfinite(number):
        return None
    return number
```

- [ ] **Step 4: Run pure power-quality tests**

Run:

```powershell
python -m pytest tests/test_power_quality.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit power-quality module**

Run:

```powershell
git add custom_components/circuitsetup_energy_analyzer/power_quality.py tests/test_power_quality.py
git commit -m "feat: add power quality relationship scoring"
```

### Task 3: Coordinator Learns And Alerts On Power Quality Relationships

**Files:**
- Modify: `tests/test_coordinator.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/coordinator.py`

- [ ] **Step 1: Write failing coordinator tests**

Append these tests to `tests/test_coordinator.py`:

```python
@pytest.mark.asyncio
async def test_runtime_learns_power_quality_baselines_for_optional_metrics() -> None:
    from custom_components.circuitsetup_energy_analyzer import coordinator as coordinator_module

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    holder = {"time": now}

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.fridge_power": "500",
                "sensor.fridge_var": "80",
                "sensor.fridge_va": "506",
                "sensor.fridge_pf": "0.98",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                        {"entity_id": "sensor.fridge_var", "role": "reactive_power"},
                        {"entity_id": "sensor.fridge_va", "role": "apparent_power"},
                        {"entity_id": "sensor.fridge_pf", "role": "power_factor"},
                    ],
                }
            ],
        },
        now_fn=lambda: holder["time"],
    )

    for offset in range(15):
        holder["time"] = now + timedelta(minutes=offset)
        await coordinator.async_process_update()

    assert "fridge:real_power" in coordinator.store_data.baselines
    assert "fridge:reactive_power" in coordinator.store_data.baselines
    assert "fridge:apparent_power" in coordinator.store_data.baselines
    assert "fridge:power_factor" in coordinator.store_data.baselines
    assert "fridge:reactive_to_real_ratio" in coordinator.store_data.baselines
    assert "fridge:apparent_to_real_ratio" in coordinator.store_data.baselines
    assert coordinator.state.learning_by_circuit["fridge"] is True


@pytest.mark.asyncio
async def test_runtime_notifies_power_quality_relationship_change_after_maturity(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import coordinator as coordinator_module

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    holder = {"time": now}
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.fridge_power": "510",
                "sensor.fridge_var": "220",
                "sensor.fridge_va": "560",
                "sensor.fridge_pf": "0.91",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=holder["time"],
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "fridge",
                    "name": "Fridge",
                    "mode": "single_phase",
                    "appliance_profile": "refrigerator",
                    "sensors": [
                        {"entity_id": "sensor.fridge_power", "role": "real_power"},
                        {"entity_id": "sensor.fridge_var", "role": "reactive_power"},
                        {"entity_id": "sensor.fridge_va", "role": "apparent_power"},
                        {"entity_id": "sensor.fridge_pf", "role": "power_factor"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=now - timedelta(hours=index + 1),
                    circuit_id="fridge",
                    event_type=EventType.START,
                )
                for index in range(20)
            ],
            baselines={
                "fridge:real_power": BaselineStats("real_power", 20, 500.0, 20.0, 470.0, 530.0, 1.0),
                "fridge:reactive_power": BaselineStats("reactive_power", 20, 80.0, 10.0, 65.0, 95.0, 1.0),
                "fridge:apparent_power": BaselineStats("apparent_power", 20, 506.0, 12.0, 490.0, 520.0, 1.0),
                "fridge:power_factor": BaselineStats("power_factor", 20, 0.98, 0.01, 0.96, 0.99, 1.0),
                "fridge:reactive_to_real_ratio": BaselineStats("reactive_to_real_ratio", 20, 0.16, 0.02, 0.12, 0.20, 1.0),
                "fridge:apparent_to_real_ratio": BaselineStats("apparent_to_real_ratio", 20, 1.01, 0.01, 1.0, 1.02, 1.0),
                "fridge:power_factor_deficit": BaselineStats("power_factor_deficit", 20, 0.02, 0.01, 0.01, 0.04, 1.0),
            },
        ),
        now_fn=lambda: holder["time"],
    )

    for offset in range(3):
        holder["time"] = now + timedelta(minutes=offset)
        await coordinator.async_process_update()

    assert notifications
    alert = notifications[0]
    assert alert.feature == "reactive_shift_under_stable_real_power"
    assert "reactive power" in alert.message
    assert "real power stayed" in alert.message
    assert alert.features["relationship_rms"] > 2.0
    assert coordinator.state.power_quality_score_by_circuit["fridge"] > 2.0
    assert coordinator.state.power_quality_evidence_by_circuit["fridge"]


@pytest.mark.asyncio
async def test_runtime_mixed_circuit_tracks_power_quality_without_notification(
    monkeypatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import coordinator as coordinator_module

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    notifications: list[AlertEvidence] = []

    async def fake_notification(hass, alert) -> None:
        notifications.append(alert)

    monkeypatch.setattr(
        coordinator_module.notifications,
        "async_create_alert_notification",
        fake_notification,
    )

    class FakeStates:
        def get(self, entity_id: str):
            values = {
                "sensor.mixed_power": "510",
                "sensor.mixed_var": "220",
            }
            return SimpleNamespace(
                state=values[entity_id],
                attributes={"unit_of_measurement": "W"},
                last_updated=now,
            )

    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "mixed",
                    "name": "Kitchen Mixed",
                    "mode": "mixed",
                    "appliance_profile": "mixed",
                    "sensors": [
                        {"entity_id": "sensor.mixed_power", "role": "real_power"},
                        {"entity_id": "sensor.mixed_var", "role": "reactive_power"},
                    ],
                }
            ],
        },
        store_data=FeatureStoreData(
            events=[
                CircuitEvent(
                    timestamp=now - timedelta(hours=index + 1),
                    circuit_id="mixed",
                    event_type=EventType.START,
                )
                for index in range(20)
            ],
            baselines={
                "mixed:real_power": BaselineStats("real_power", 20, 500.0, 20.0, 470.0, 530.0, 1.0),
                "mixed:reactive_power": BaselineStats("reactive_power", 20, 80.0, 10.0, 65.0, 95.0, 1.0),
                "mixed:reactive_to_real_ratio": BaselineStats("reactive_to_real_ratio", 20, 0.16, 0.02, 0.12, 0.20, 1.0),
            },
        ),
        now_fn=lambda: now,
    )

    for _ in range(3):
        await coordinator.async_process_update()

    assert notifications == []
    assert coordinator.state.power_quality_score_by_circuit["mixed"] > 0.0
    assert coordinator.state.power_quality_evidence_by_circuit["mixed"] == ""
```

- [ ] **Step 2: Run the new coordinator tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_coordinator.py::test_runtime_learns_power_quality_baselines_for_optional_metrics tests/test_coordinator.py::test_runtime_notifies_power_quality_relationship_change_after_maturity tests/test_coordinator.py::test_runtime_mixed_circuit_tracks_power_quality_without_notification -q
```

Expected: FAIL because `AnalyzerState` has no power-quality state fields and coordinator still calls `_observe_real_power`.

- [ ] **Step 3: Import power-quality helpers**

In `custom_components/circuitsetup_energy_analyzer/coordinator.py`, add this import block after the existing NILM imports:

```python
from .power_quality import (
    PowerQualityEvidence,
    extract_power_quality_features,
    relationship_rms_score,
    score_power_quality_features,
    select_power_quality_evidence,
)
```

- [ ] **Step 4: Add runtime state fields**

In `AnalyzerState`, after `data_quality_by_circuit`, add:

```python
    power_quality_score_by_circuit: dict[str, float] = field(default_factory=dict)
    power_quality_evidence_by_circuit: dict[str, str] = field(default_factory=dict)
    reactive_power_drift_by_circuit: dict[str, float] = field(default_factory=dict)
    apparent_power_drift_by_circuit: dict[str, float] = field(default_factory=dict)
    power_factor_drift_by_circuit: dict[str, float] = field(default_factory=dict)
```

- [ ] **Step 5: Replace the runtime observer call**

In `async_process_update`, replace:

```python
            alert = self._observe_real_power(config, sample, now)
```

with:

```python
            alert = self._observe_power_quality(config, sample, now)
```

- [ ] **Step 6: Replace `_observe_real_power` with `_observe_power_quality`**

Replace the whole `_observe_real_power` method with:

```python
    def _observe_power_quality(
        self: Self,
        config: CircuitConfig,
        sample: Any,
        now: datetime,
    ) -> AlertEvidence | None:
        features = extract_power_quality_features(sample)
        if not features:
            self.state.learning_by_circuit.setdefault(config.circuit_id, True)
            return None

        baselines: dict[str, Any] = {}
        learning_new_features = False
        for feature, value in features.items():
            key = _baseline_key(config.circuit_id, feature)
            baseline = self.store_data.baselines.get(key)
            if baseline is None:
                values = self._baseline_values[key]
                values.append(value)
                if len(values) >= 15:
                    baseline = build_baseline(feature, values)
                    self.store_data.baselines[key] = baseline
                    self._mark_store_dirty()
                learning_new_features = True
            if baseline is not None:
                baselines[feature] = baseline

        scores = score_power_quality_features(features, baselines)
        evidence = select_power_quality_evidence(config, scores)
        self._update_power_quality_state(config.circuit_id, scores, evidence)

        mature = self._learning_mature(config, now)
        has_confident_scores = any(score.baseline_confidence >= 0.6 for score in scores)
        self.state.learning_by_circuit[config.circuit_id] = (
            learning_new_features or not mature or not has_confident_scores
        )
        if learning_new_features or not mature or not has_confident_scores:
            return None
        if evidence is None:
            return None

        return self._alert_policy.observe(
            Observation(
                circuit_id=config.circuit_id,
                feature=evidence.feature,
                score=evidence.score,
                baseline_confidence=evidence.baseline_confidence,
                observed_at=now,
                observed_value=evidence.observed_value,
                baseline_value=evidence.baseline_value,
                message=evidence.message,
                features=evidence.features,
            )
        )
```

- [ ] **Step 7: Add power-quality state helper**

Add this method before `_learning_mature`:

```python
    def _update_power_quality_state(
        self: Self,
        circuit_id: str,
        scores: Iterable[Any],
        evidence: PowerQualityEvidence | None,
    ) -> None:
        scores = list(scores)
        by_feature = {score.feature: score for score in scores}
        self.state.power_quality_score_by_circuit[circuit_id] = relationship_rms_score(scores)
        self.state.power_quality_evidence_by_circuit[circuit_id] = (
            evidence.message if evidence is not None else ""
        )
        self.state.reactive_power_drift_by_circuit[circuit_id] = abs(
            by_feature.get("reactive_power", by_feature.get("reactive_to_real_ratio")).change_ratio
        ) if (
            by_feature.get("reactive_power") is not None
            or by_feature.get("reactive_to_real_ratio") is not None
        ) else 0.0
        self.state.apparent_power_drift_by_circuit[circuit_id] = abs(
            by_feature.get("apparent_power", by_feature.get("apparent_to_real_ratio")).change_ratio
        ) if (
            by_feature.get("apparent_power") is not None
            or by_feature.get("apparent_to_real_ratio") is not None
        ) else 0.0
        self.state.power_factor_drift_by_circuit[circuit_id] = abs(
            by_feature.get("power_factor", by_feature.get("power_factor_deficit")).change_ratio
        ) if (
            by_feature.get("power_factor") is not None
            or by_feature.get("power_factor_deficit") is not None
        ) else 0.0
```

If ruff complains about repeated conditional expressions, refactor inside this helper only by adding a local `_drift(primary, fallback)` nested function. Keep behavior identical.

- [ ] **Step 8: Run coordinator tests**

Run:

```powershell
python -m pytest tests/test_coordinator.py -q
```

Expected: PASS.

- [ ] **Step 9: Run related tests**

Run:

```powershell
python -m pytest tests/test_power_quality.py tests/test_alerting.py tests/test_storage.py tests/test_diagnostics.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit coordinator wiring**

Run:

```powershell
git add custom_components/circuitsetup_energy_analyzer/coordinator.py tests/test_coordinator.py
git commit -m "feat: wire power quality relationship analysis"
```

### Task 4: Diagnostic Sensors For Power Quality State

**Files:**
- Modify: `tests/test_entities.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/sensor.py`
- Modify: `docs/dashboard-example.yaml`

- [ ] **Step 1: Write failing entity tests**

In `tests/test_entities.py`, update the import list inside `test_sensor_helpers_return_diagnostic_values_and_defaults` to include:

```python
        apparent_power_drift_value,
        power_factor_drift_value,
        power_quality_evidence_value,
        power_quality_score_value,
        reactive_power_drift_value,
```

Update the `AnalyzerState` construction in that test with:

```python
        power_quality_score_by_circuit={"fridge": 3.25},
        power_quality_evidence_by_circuit={"fridge": "Possible issue: reactive power changed"},
        reactive_power_drift_by_circuit={"fridge": 0.38},
        apparent_power_drift_by_circuit={"fridge": 0.12},
        power_factor_drift_by_circuit={"fridge": 0.07},
```

Add these assertions after the existing helper assertions:

```python
    assert power_quality_score_value(state, "fridge") == 3.25
    assert power_quality_evidence_value(state, "fridge") == "Possible issue: reactive power changed"
    assert reactive_power_drift_value(state, "fridge") == 0.38
    assert apparent_power_drift_value(state, "fridge") == 0.12
    assert power_factor_drift_value(state, "fridge") == 0.07
    assert power_quality_score_value(state, "unknown") == 0.0
    assert power_quality_evidence_value(state, "unknown") == ""
```

Update `test_sensor_setup_entry_adds_diagnostic_entities_without_ha` expected names to:

```python
    assert [entity.name for entity in added_entities] == [
        "Kitchen Fridge Anomaly Score",
        "Kitchen Fridge Last Event",
        "Kitchen Fridge Power Quality Score",
        "Kitchen Fridge Power Quality Evidence",
        "Kitchen Fridge Reactive Power Drift",
        "Kitchen Fridge Apparent Power Drift",
        "Kitchen Fridge Power Factor Drift",
        "Kitchen Fridge NILM Discovered Signatures",
        "Kitchen Fridge NILM Unmatched Load Percentage",
    ]
```

Update the expected unique ids to:

```python
    assert [entity.unique_id for entity in added_entities] == [
        "entry-1_fridge_anomaly_score",
        "entry-1_fridge_last_event",
        "entry-1_fridge_power_quality_score",
        "entry-1_fridge_power_quality_evidence",
        "entry-1_fridge_reactive_power_drift",
        "entry-1_fridge_apparent_power_drift",
        "entry-1_fridge_power_factor_drift",
        "entry-1_fridge_nilm_signature_count",
        "entry-1_fridge_nilm_unmatched_load_percentage",
    ]
```

Update `test_sensor_setup_entry_uses_runtime_synthetic_mains` expected circuit IDs to nine `"mains"` entries:

```python
    assert [entity.circuit_id for entity in added_entities] == [
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
        "mains",
    ]
```

- [ ] **Step 2: Run entity tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_entities.py -q
```

Expected: FAIL with import errors for the new sensor helper functions.

- [ ] **Step 3: Add sensor helper functions**

In `custom_components/circuitsetup_energy_analyzer/sensor.py`, after `last_event_value`, add:

```python
def power_quality_score_value(state: Any, circuit_id: str) -> float:
    """Return the current power-quality relationship score for a circuit."""
    return float(
        getattr(state, "power_quality_score_by_circuit", {}).get(circuit_id, 0.0)
    )


def power_quality_evidence_value(state: Any, circuit_id: str) -> str:
    """Return the current power-quality evidence message for a circuit."""
    return str(
        getattr(state, "power_quality_evidence_by_circuit", {}).get(circuit_id, "")
    )


def reactive_power_drift_value(state: Any, circuit_id: str) -> float:
    """Return the current reactive-power drift ratio for a circuit."""
    return float(
        getattr(state, "reactive_power_drift_by_circuit", {}).get(circuit_id, 0.0)
    )


def apparent_power_drift_value(state: Any, circuit_id: str) -> float:
    """Return the current apparent-power drift ratio for a circuit."""
    return float(
        getattr(state, "apparent_power_drift_by_circuit", {}).get(circuit_id, 0.0)
    )


def power_factor_drift_value(state: Any, circuit_id: str) -> float:
    """Return the current power-factor drift ratio for a circuit."""
    return float(
        getattr(state, "power_factor_drift_by_circuit", {}).get(circuit_id, 0.0)
    )
```

- [ ] **Step 4: Add sensor descriptions**

In `SENSOR_DESCRIPTIONS`, insert these descriptions after the `last_event` description and before NILM descriptions:

```python
    DiagnosticSensorDescription(
        key="power_quality_score",
        name_suffix="Power Quality Score",
        value_fn=power_quality_score_value,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DiagnosticSensorDescription(
        key="power_quality_evidence",
        name_suffix="Power Quality Evidence",
        value_fn=power_quality_evidence_value,
    ),
    DiagnosticSensorDescription(
        key="reactive_power_drift",
        name_suffix="Reactive Power Drift",
        value_fn=reactive_power_drift_value,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DiagnosticSensorDescription(
        key="apparent_power_drift",
        name_suffix="Apparent Power Drift",
        value_fn=apparent_power_drift_value,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DiagnosticSensorDescription(
        key="power_factor_drift",
        name_suffix="Power Factor Drift",
        value_fn=power_factor_drift_value,
        state_class=SensorStateClass.MEASUREMENT,
    ),
```

- [ ] **Step 5: Update dashboard example**

In `docs/dashboard-example.yaml`, add these entities to the Refrigerator and HVAC entity lists after their anomaly score:

```yaml
          - entity: sensor.fridge_energy_analyzer_power_quality_score
          - entity: sensor.fridge_energy_analyzer_power_quality_evidence
          - entity: sensor.fridge_energy_analyzer_reactive_power_drift
          - entity: sensor.fridge_energy_analyzer_power_factor_drift
```

and:

```yaml
          - entity: sensor.hvac_energy_analyzer_power_quality_score
          - entity: sensor.hvac_energy_analyzer_power_quality_evidence
          - entity: sensor.hvac_energy_analyzer_reactive_power_drift
          - entity: sensor.hvac_energy_analyzer_power_factor_drift
```

- [ ] **Step 6: Run entity tests**

Run:

```powershell
python -m pytest tests/test_entities.py -q
```

Expected: PASS.

- [ ] **Step 7: Run coordinator and entity tests together**

Run:

```powershell
python -m pytest tests/test_coordinator.py tests/test_entities.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit diagnostic sensors**

Run:

```powershell
git add custom_components/circuitsetup_energy_analyzer/sensor.py tests/test_entities.py docs/dashboard-example.yaml
git commit -m "feat: expose power quality diagnostic sensors"
```

### Task 5: Final Validation And Cleanup

**Files:**
- Modify only files needed to fix validation failures.

- [ ] **Step 1: Run the full test suite**

Run:

```powershell
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 2: Run ruff**

Run:

```powershell
python -m ruff check .
```

Expected: PASS.

- [ ] **Step 3: Run JSON validation**

Run:

```powershell
@'
import json
from pathlib import Path

for path in Path(".").rglob("*.json"):
    json.loads(path.read_text())
print("json ok")
'@ | python -
```

Expected: prints `json ok`.

- [ ] **Step 4: Run whitespace validation**

Run:

```powershell
git diff --check
```

Expected: no output.

- [ ] **Step 5: Review changed files**

Run:

```powershell
git status --short
git diff --stat
```

Expected: either clean if every task committed, or only intentional validation-fix files remain.

- [ ] **Step 6: Commit validation fixes if needed**

If validation required fixes, run:

```powershell
git add custom_components/circuitsetup_energy_analyzer tests docs
git commit -m "fix: resolve power quality validation issues"
```

If no files changed, skip this commit.

## Plan Self-Review

Spec coverage:

- Per-circuit reactive power, apparent power, and PF tracking: Tasks 2 and 3.
- Derived W/VAR/VA/PF relationship features: Task 2.
- Multivariate internal scoring with readable evidence: Tasks 1, 2, and 3.
- Evidence grounded in real power-quality relationships: Task 2 evidence names and messages, backed by spec references.
- Conservative alerting and maturity gates: Tasks 1 and 3.
- Real-power-only backwards behavior: Task 2 fallback and Task 3 coordinator wiring.
- Mixed circuit diagnostic-only behavior: Tasks 2 and 3.
- Standard Home Assistant diagnostic entities: Task 4.
- TDD and validation: every task starts with failing tests, Task 5 validates all code.

Placeholder scan:

- No unresolved marker words or unspecified implementation steps remain.
- Every task identifies files, tests, commands, and expected results.

Type consistency:

- `PowerQualityEvidence` fields match `Observation` custom evidence fields.
- Coordinator state names match sensor helper names.
- Baseline keys continue using the existing `circuit_id:feature` format.
