# User Experience Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Home Assistant-native readiness, health, evidence, maintenance, sensitivity, NILM review, data-quality, dashboard, and feedback UX features.

**Architecture:** Keep the coordinator as the source of runtime state, add a small `ux.py` helper module for deterministic summaries/checklists, persist user decisions in the existing feature store, and expose the UX through standard sensor/binary_sensor entities and services. Preserve conservative alert wording and Repairs-only-for-setup/data-quality behavior.

**Tech Stack:** Python 3.12, Home Assistant custom integration patterns, pytest, ruff, Home Assistant service schemas, JSON-safe integration storage.

---

## File Structure

- Create `custom_components/circuitsetup_energy_analyzer/ux.py`: pure helper functions for sensitivity normalization, data-quality checklists, learning progress, alert details, and health status selection.
- Modify `custom_components/circuitsetup_energy_analyzer/storage.py`: persist sensitivity overrides, maintenance windows, alert feedback, and richer NILM review fields.
- Modify `custom_components/circuitsetup_energy_analyzer/coordinator.py`: compute UX runtime state, honor maintenance and feedback suppression, support per-circuit sensitivity, and update diagnostics export.
- Modify `custom_components/circuitsetup_energy_analyzer/services.py`: register and dispatch the new UX services.
- Modify `custom_components/circuitsetup_energy_analyzer/services.yaml`: document the new services.
- Modify `custom_components/circuitsetup_energy_analyzer/sensor.py`: expose health summary, readiness, learning progress, data-quality checklist, alert evidence, and sensitivity sensors with useful attributes.
- Modify `custom_components/circuitsetup_energy_analyzer/binary_sensor.py`: expose maintenance state.
- Modify `custom_components/circuitsetup_energy_analyzer/config_flow.py`: make mapping suggestion text explicitly offer accept/edit/mixed/exclude decisions.
- Modify `custom_components/circuitsetup_energy_analyzer/strings.json`: add service/entity labels and setup text where needed.
- Modify `docs/dashboard-example.yaml`: expand the dashboard example into setup health, learning progress, circuit summaries, active evidence, power-quality diagnostics, and NILM review.
- Test files: `tests/test_ux.py`, `tests/test_storage.py`, `tests/test_coordinator.py`, `tests/test_services.py`, `tests/test_entities.py`, `tests/test_config_flow.py`.

## Shared Names And States

Use these values consistently:

- Health/readiness status values: `learning`, `ready`, `needs_data`, `paused`, `possible_issue`, `mixed_observation`, `nilm_review`.
- Health summary display values: `Learning`, `Ready`, `Needs data`, `Paused`, `Possible issue`, `Mixed observation`, `NILM review`.
- Friendly sensitivity presets: `quiet`, `balanced`, `sensitive`.
- Legacy sensitivity aliases: `low -> quiet`, `standard -> balanced`, `high -> sensitive`.
- NILM review states: `new`, `labeled`, `ignored`, `expected`, `merged`.
- Alert feedback actions: `expected`, `unhelpful`.

### Task 1: UX Helpers And Storage

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/ux.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/storage.py`
- Test: `tests/test_ux.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write failing UX helper tests**

Add `tests/test_ux.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    EventType,
    SensorRef,
    SensorRole,
    Severity,
)


def test_normalize_sensitivity_accepts_friendly_and_legacy_names() -> None:
    from custom_components.circuitsetup_energy_analyzer.ux import (
        alert_policy_name_for_sensitivity,
        normalize_sensitivity,
    )

    assert normalize_sensitivity("quiet") == "quiet"
    assert normalize_sensitivity("low") == "quiet"
    assert normalize_sensitivity("balanced") == "balanced"
    assert normalize_sensitivity("standard") == "balanced"
    assert normalize_sensitivity("sensitive") == "sensitive"
    assert normalize_sensitivity("high") == "sensitive"
    assert normalize_sensitivity("surprising") == "balanced"
    assert alert_policy_name_for_sensitivity("quiet") == "low"
    assert alert_policy_name_for_sensitivity("balanced") == "standard"
    assert alert_policy_name_for_sensitivity("sensitive") == "high"


def test_alert_evidence_detail_is_json_safe_and_explains_change() -> None:
    from custom_components.circuitsetup_energy_analyzer.ux import alert_evidence_detail

    alert = AlertEvidence(
        timestamp=datetime(2026, 6, 2, 12, 30, tzinfo=UTC),
        circuit_id="fridge",
        severity=Severity.WARNING,
        message="Possible issue",
        event_type=EventType.STEADY_WINDOW,
        feature="reactive_to_real_ratio",
        observed_value=0.42,
        baseline_value=0.24,
        change_ratio=0.75,
        repeated_count=4,
        first_seen=datetime(2026, 6, 2, 10, 0, tzinfo=UTC),
        last_seen=datetime(2026, 6, 2, 12, 30, tzinfo=UTC),
        features={"reactive_power": 2.1, "power_factor": 1.2},
    )

    assert alert_evidence_detail(alert) == {
        "alert_id": "circuitsetup_energy_analyzer_alert_fridge_reactive_to_real_ratio_8ae4630f45b0",
        "circuit_id": "fridge",
        "feature": "reactive_to_real_ratio",
        "severity": "warning",
        "message": "Possible issue",
        "baseline_value": 0.24,
        "observed_value": 0.42,
        "change_ratio": 0.75,
        "percent_change": 75.0,
        "repeated_count": 4,
        "first_seen": "2026-06-02T10:00:00+00:00",
        "last_seen": "2026-06-02T12:30:00+00:00",
        "time_window": "2026-06-02T10:00:00+00:00 to 2026-06-02T12:30:00+00:00",
        "contributing_metrics": {"power_factor": 1.2, "reactive_power": 2.1},
    }


def test_data_quality_checklist_reports_required_optional_and_sample_state() -> None:
    from custom_components.circuitsetup_energy_analyzer.normalize import (
        NormalizedCircuitSample,
    )
    from custom_components.circuitsetup_energy_analyzer.ux import data_quality_checklist

    config = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
        sensors=(
            SensorRef("sensor.fridge_w", SensorRole.REAL_POWER),
            SensorRef("sensor.fridge_var", SensorRole.REACTIVE_POWER),
            SensorRef("sensor.fridge_pf", SensorRole.POWER_FACTOR),
        ),
    )
    sample = NormalizedCircuitSample(
        timestamp=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_id="fridge",
        real_power=120.0,
        reactive_power=35.0,
        power_factor=0.91,
        source_entity_ids=("sensor.fridge_w", "sensor.fridge_var", "sensor.fridge_pf"),
    )

    checklist = data_quality_checklist(config, sample)

    assert checklist["required_sensors_present"] is True
    assert checklist["optional_sensors_present"] is True
    assert checklist["numeric_states_valid"] is True
    assert checklist["source_data_fresh"] is True
    assert checklist["quality_issues"] == []
    assert checklist["metric_roles_present"] == ["power_factor", "reactive_power", "real_power"]


def test_learning_progress_counts_age_cycles_and_baseline_confidence() -> None:
    from custom_components.circuitsetup_energy_analyzer.models import BaselineStats
    from custom_components.circuitsetup_energy_analyzer.ux import learning_progress

    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="fridge",
        name="Fridge",
        appliance_profile=ApplianceProfile.REFRIGERATOR,
        mode=CircuitMode.SINGLE_PHASE,
    )
    events = [
        CircuitEvent(now - timedelta(days=8), "fridge", EventType.START),
        CircuitEvent(now - timedelta(days=7), "fridge", EventType.STOP),
        CircuitEvent(now - timedelta(days=1), "fridge", EventType.START),
    ]
    baselines = {
        "fridge:real_power": BaselineStats("real_power", 18, 100.0, 5.0, 90.0, 110.0, 0.8),
        "other:real_power": BaselineStats("real_power", 18, 50.0, 4.0, 45.0, 55.0, 0.9),
    }

    progress = learning_progress(
        config,
        events=events,
        baselines=baselines,
        baseline_buffer_counts={"fridge:reactive_power": 4},
        now=now,
        learning=True,
        suppression_reason="waiting_for_optional_metrics",
    )

    assert progress["baseline_age_days"] == 8.0
    assert progress["cycle_count"] == 2
    assert progress["baseline_confidence"] == 0.8
    assert progress["learned_feature_count"] == 1
    assert progress["learning"] is True
    assert progress["alert_ready"] is False
    assert progress["suppression_reason"] == "waiting_for_optional_metrics"
    assert progress["pending_feature_samples"] == {"reactive_power": 4}


def test_health_status_priority_order_is_dashboard_friendly() -> None:
    from custom_components.circuitsetup_energy_analyzer.ux import health_summary

    assert health_summary(data_quality_problem=True) == ("needs_data", "Needs data")
    assert health_summary(paused=True) == ("paused", "Paused")
    assert health_summary(active_alerts=True) == ("possible_issue", "Possible issue")
    assert health_summary(nilm_review_count=2) == ("nilm_review", "NILM review")
    assert health_summary(mixed=True) == ("mixed_observation", "Mixed observation")
    assert health_summary(learning=True) == ("learning", "Learning")
    assert health_summary() == ("ready", "Ready")
```

- [ ] **Step 2: Run UX helper tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_ux.py -q
```

Expected: FAIL because `custom_components.circuitsetup_energy_analyzer.ux` does not exist.

- [ ] **Step 3: Implement `ux.py`**

Create `custom_components/circuitsetup_energy_analyzer/ux.py` with pure helper functions:

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from .models import AlertEvidence, CircuitConfig, CircuitEvent, CircuitMode, EventType, SensorRole
from .notifications import notification_id_for_alert

FRIENDLY_SENSITIVITY_ALIASES = {
    "low": "quiet",
    "quiet": "quiet",
    "standard": "balanced",
    "balanced": "balanced",
    "high": "sensitive",
    "sensitive": "sensitive",
}
POLICY_SENSITIVITY_ALIASES = {
    "quiet": "low",
    "balanced": "standard",
    "sensitive": "high",
}
REQUIRED_ROLES = {SensorRole.REAL_POWER}
OPTIONAL_ROLES = {
    SensorRole.VOLTAGE,
    SensorRole.CURRENT,
    SensorRole.REACTIVE_POWER,
    SensorRole.APPARENT_POWER,
    SensorRole.POWER_FACTOR,
    SensorRole.FREQUENCY,
}


def normalize_sensitivity(value: Any) -> str:
    return FRIENDLY_SENSITIVITY_ALIASES.get(str(value).strip().lower(), "balanced")


def alert_policy_name_for_sensitivity(value: Any) -> str:
    return POLICY_SENSITIVITY_ALIASES[normalize_sensitivity(value)]


def alert_evidence_detail(alert: AlertEvidence) -> dict[str, Any]:
    first_seen = alert.first_seen.isoformat() if alert.first_seen else None
    last_seen = alert.last_seen.isoformat() if alert.last_seen else None
    return {
        "alert_id": notification_id_for_alert(alert),
        "circuit_id": alert.circuit_id,
        "feature": alert.feature
        or (alert.event_type.value if alert.event_type is not None else "alert"),
        "severity": alert.severity.value,
        "message": alert.message,
        "baseline_value": alert.baseline_value,
        "observed_value": alert.observed_value,
        "change_ratio": alert.change_ratio,
        "percent_change": round(alert.change_ratio * 100.0, 3),
        "repeated_count": alert.repeated_count,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "time_window": f"{first_seen} to {last_seen}"
        if first_seen and last_seen
        else None,
        "contributing_metrics": dict(sorted(alert.features.items())),
    }
```

Also implement `data_quality_checklist`, `learning_progress`, and `health_summary` to satisfy the tests above.

- [ ] **Step 4: Run UX helper tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_ux.py -q
```

Expected: PASS.

- [ ] **Step 5: Write failing storage tests for UX persistence**

Extend `tests/test_storage.py` with:

```python
def test_feature_store_round_trips_user_experience_state() -> None:
    from custom_components.circuitsetup_energy_analyzer.storage import (
        feature_store_data_from_dict,
        feature_store_data_to_dict,
    )

    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    data = FeatureStoreData(
        sensitivity_by_circuit={"fridge": "quiet"},
        maintenance_by_circuit={
            "fridge": {
                "active": True,
                "note": "Cleaned coils",
                "started_at": now.isoformat(),
                "relearn_on_end": True,
            }
        },
        alert_feedback={
            "fridge:reactive_power": {
                "action": "expected",
                "alert_id": "alert-1",
                "created_at": now.isoformat(),
                "change_ratio": 0.42,
            }
        },
        nilm_signatures={
            "mains": [
                {
                    "signature_id": "on-1",
                    "review_state": "expected",
                    "user_label": "Microwave",
                }
            ]
        },
    )

    raw = feature_store_data_to_dict(data)
    restored = feature_store_data_from_dict(raw)

    assert restored.sensitivity_by_circuit == {"fridge": "quiet"}
    assert restored.maintenance_by_circuit["fridge"]["note"] == "Cleaned coils"
    assert restored.alert_feedback["fridge:reactive_power"]["action"] == "expected"
    assert restored.nilm_signatures["mains"][0]["review_state"] == "expected"
```

- [ ] **Step 6: Run storage test to verify it fails**

Run:

```powershell
python -m pytest tests/test_storage.py::test_feature_store_round_trips_user_experience_state -q
```

Expected: FAIL because `FeatureStoreData` has no UX persistence fields.

- [ ] **Step 7: Implement storage fields**

Modify `FeatureStoreData` in `storage.py`:

```python
sensitivity_by_circuit: dict[str, str] = field(default_factory=dict)
maintenance_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
alert_feedback: dict[str, dict[str, Any]] = field(default_factory=dict)
```

Update `feature_store_data_to_dict`, `feature_store_data_from_dict`, and `prune_events` so the new dictionaries are serialized and preserved.

- [ ] **Step 8: Run storage tests**

Run:

```powershell
python -m pytest tests/test_storage.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit Task 1**

Run:

```powershell
git add custom_components/circuitsetup_energy_analyzer/ux.py custom_components/circuitsetup_energy_analyzer/storage.py tests/test_ux.py tests/test_storage.py
git commit -m "feat: add ux helper and storage state"
```

### Task 2: Coordinator UX State, Maintenance, Sensitivity, And Feedback

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/coordinator.py`
- Modify: `tests/test_coordinator.py`
- Modify: `tests/test_services.py`

- [ ] **Step 1: Write failing coordinator tests**

Add focused tests to `tests/test_coordinator.py`:

```python
async def test_runtime_populates_readiness_health_and_checklist_state() -> None:
    # Build a coordinator with one refrigerator circuit and fake source states.
    # Process one update with valid W/VAR/PF data.
    # Assert state.health_status_by_circuit["fridge"] is "learning".
    # Assert state.health_summary_by_circuit["fridge"] is "Learning".
    # Assert readiness contains baseline_age_days, cycle_count, baseline_confidence,
    # required_metric_coverage, optional_metric_coverage, alert_ready, and suppression_reason.
    # Assert data_quality_checklist_by_circuit["fridge"]["required_sensors_present"] is True.


async def test_maintenance_mode_pauses_notifications_but_not_data_quality_repairs(monkeypatch) -> None:
    # Start maintenance with note "Changed filter".
    # Assert store_data.maintenance_by_circuit["fridge"]["active"] is True.
    # Assert "fridge" is in paused_circuits and state.maintenance_by_circuit["fridge"]["active"] is True.
    # Trigger data quality issue and assert repair helper is still called.


async def test_per_circuit_sensitivity_override_controls_alert_policy() -> None:
    # Store fridge sensitivity as "sensitive" and HVAC as "quiet".
    # Assert coordinator._alert_policy_for_circuit("fridge").min_repeated == 3.
    # Assert coordinator._alert_policy_for_circuit("hvac").min_repeated == 4.


async def test_expected_alert_feedback_suppresses_repeated_notification(monkeypatch) -> None:
    # Store feedback for fridge:reactive_power with action "expected".
    # Produce a matching alert and assert notification helper is not called.
    # Produce an alert for a different feature and assert notification helper is called.


async def test_export_diagnostics_includes_ux_state() -> None:
    # Populate readiness, health, checklist, alert detail, maintenance, and sensitivity.
    # Call async_export_diagnostics("fridge").
    # Assert last_exported_diagnostics includes those keys.
```

- [ ] **Step 2: Run the new coordinator tests to verify they fail**

Run each new test individually:

```powershell
python -m pytest tests/test_coordinator.py::test_runtime_populates_readiness_health_and_checklist_state -q
python -m pytest tests/test_coordinator.py::test_maintenance_mode_pauses_notifications_but_not_data_quality_repairs -q
python -m pytest tests/test_coordinator.py::test_per_circuit_sensitivity_override_controls_alert_policy -q
python -m pytest tests/test_coordinator.py::test_expected_alert_feedback_suppresses_repeated_notification -q
python -m pytest tests/test_coordinator.py::test_export_diagnostics_includes_ux_state -q
```

Expected: FAIL because the coordinator has no UX state fields or methods.

- [ ] **Step 3: Extend `AnalyzerState`**

Add these fields:

```python
health_status_by_circuit: dict[str, str] = field(default_factory=dict)
health_summary_by_circuit: dict[str, str] = field(default_factory=dict)
readiness_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
learning_progress_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
data_quality_checklist_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
alert_evidence_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
sensitivity_by_circuit: dict[str, str] = field(default_factory=dict)
maintenance_by_circuit: dict[str, dict[str, Any]] = field(default_factory=dict)
nilm_review_by_circuit: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
```

- [ ] **Step 4: Wire UX helper state into the coordinator**

In `coordinator.py`, import helpers from `ux.py`:

```python
from .ux import (
    alert_evidence_detail,
    alert_policy_name_for_sensitivity,
    data_quality_checklist,
    health_summary,
    learning_progress,
    normalize_sensitivity,
)
```

Add `_refresh_ux_state(config, sample, now, suppression_reason=None)` and call it after power-quality observation and after `process_events_into_state`. It should populate checklist, learning progress, readiness, health status, health summary, maintenance state, sensitivity state, alert evidence detail, and NILM review state.

- [ ] **Step 5: Add per-circuit sensitivity policy**

Add:

```python
def _sensitivity_for_circuit(self, circuit_id: str) -> str:
    return normalize_sensitivity(
        self.store_data.sensitivity_by_circuit.get(circuit_id, self._sensitivity)
    )


def _alert_policy_for_circuit(self, circuit_id: str) -> ConservativeAlertPolicy:
    return _alert_policy_for_sensitivity(
        alert_policy_name_for_sensitivity(self._sensitivity_for_circuit(circuit_id))
    )
```

Use that policy in `_observe_power_quality` and `_process_nilm_sample`.

- [ ] **Step 6: Add maintenance and feedback coordinator methods**

Add:

```python
async def async_set_circuit_sensitivity(self, circuit_id: str, preset: str) -> None: ...
async def async_start_maintenance(self, circuit_id: str, note: str = "", duration: str | None = None, relearn_on_end: bool = False) -> None: ...
async def async_end_maintenance(self, circuit_id: str, relearn: bool = False) -> None: ...
async def async_mark_alert_expected(self, alert_id: str) -> None: ...
async def async_mark_alert_unhelpful(self, alert_id: str) -> None: ...
```

Feedback keys should be `"{circuit_id}:{feature}"`. `_notify_alert` should suppress notifications for matching `expected` or `unhelpful` feedback, while leaving diagnostics and Repairs untouched.

- [ ] **Step 7: Run coordinator tests**

Run:

```powershell
python -m pytest tests/test_coordinator.py -q
```

Expected: PASS.

- [ ] **Step 8: Write and run failing service dispatch tests**

Extend `tests/test_services.py::test_service_handlers_mutate_loaded_coordinator_state` or add a new test that dispatches:

- `set_circuit_sensitivity`
- `start_maintenance`
- `end_maintenance`
- `mark_alert_expected`
- `mark_alert_unhelpful`

Expected before implementation: FAIL because services are not registered.

- [ ] **Step 9: Commit Task 2**

Run:

```powershell
git add custom_components/circuitsetup_energy_analyzer/coordinator.py tests/test_coordinator.py tests/test_services.py
git commit -m "feat: add coordinator ux state and feedback controls"
```

### Task 3: Services, Entities, Strings, And Dashboard

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/services.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/services.yaml`
- Modify: `custom_components/circuitsetup_energy_analyzer/sensor.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/binary_sensor.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/strings.json`
- Modify: `docs/dashboard-example.yaml`
- Test: `tests/test_entities.py`
- Test: `tests/test_services.py`

- [ ] **Step 1: Write failing entity tests**

Extend `tests/test_entities.py` so the sensor setup expected names include:

```python
"Kitchen Fridge Health Summary",
"Kitchen Fridge Readiness",
"Kitchen Fridge Learning Progress",
"Kitchen Fridge Data Quality Checklist",
"Kitchen Fridge Alert Evidence",
"Kitchen Fridge Sensitivity",
```

Extend binary sensor expected names with:

```python
"Well Pump Maintenance"
```

Add helper tests for:

```python
health_summary_value(state, "fridge") == "Possible issue"
readiness_value(state, "fridge") == "possible_issue"
learning_progress_value(state, "fridge") == 62.5
data_quality_checklist_value(state, "fridge") == "ok"
alert_evidence_value(state, "fridge") == "reactive_power"
sensitivity_value(state, "fridge") == "quiet"
is_maintenance_active(state, "fridge") is True
```

- [ ] **Step 2: Run entity tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_entities.py -q
```

Expected: FAIL because new entity descriptions do not exist.

- [ ] **Step 3: Add sensor values and attributes**

In `sensor.py`, add value helpers for health summary, readiness, learning progress, data quality checklist, alert evidence, and sensitivity. Extend `DiagnosticSensorDescription` with optional `attributes_fn`. Add `extra_state_attributes` to `CircuitAnalyzerSensor` and return the relevant state dict for readiness/progress/checklist/evidence/NILM signatures.

- [ ] **Step 4: Add maintenance binary sensor**

In `binary_sensor.py`, add `is_maintenance_active` and a `DiagnosticBinarySensorDescription` for key `maintenance` / suffix `Maintenance`.

- [ ] **Step 5: Add services and schemas**

In `services.py`, add constants and schema dispatch for:

- `set_circuit_sensitivity` with `circuit_id`, `preset`
- `start_maintenance` with `circuit_id`, optional `note`, optional `duration`, optional `relearn_on_end`
- `end_maintenance` with `circuit_id`, optional `relearn`
- `mark_alert_expected` with `alert_id`
- `mark_alert_unhelpful` with `alert_id`
- `mark_nilm_signature_expected` with `circuit_id`, `signature_id`
- `merge_nilm_signatures` with `circuit_id`, `source_signature_id`, `target_signature_id`

- [ ] **Step 6: Add service YAML and strings**

Add service descriptions and selectors to `services.yaml`. Add entity labels to `strings.json` for the new sensors and binary sensor.

- [ ] **Step 7: Expand dashboard example**

Update `docs/dashboard-example.yaml` with sections for setup health, learning progress, circuit summaries, active evidence, power-quality diagnostics, and experimental NILM review.

- [ ] **Step 8: Run service and entity tests**

Run:

```powershell
python -m pytest tests/test_entities.py tests/test_services.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

Run:

```powershell
git add custom_components/circuitsetup_energy_analyzer/services.py custom_components/circuitsetup_energy_analyzer/services.yaml custom_components/circuitsetup_energy_analyzer/sensor.py custom_components/circuitsetup_energy_analyzer/binary_sensor.py custom_components/circuitsetup_energy_analyzer/strings.json docs/dashboard-example.yaml tests/test_entities.py tests/test_services.py
git commit -m "feat: expose ux diagnostics and services"
```

### Task 4: NILM Signature Review And Mapping Review

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/coordinator.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/config_flow.py`
- Modify: `tests/test_coordinator.py`
- Modify: `tests/test_services.py`
- Modify: `tests/test_config_flow.py`

- [ ] **Step 1: Write failing NILM review tests**

Add tests asserting:

```python
await coordinator.async_mark_nilm_signature_expected("mains", "on-1")
assert signature["review_state"] == "expected"
assert signature["expected"] is True

await coordinator.async_merge_nilm_signatures("mains", "on-2", "on-1")
assert source["review_state"] == "merged"
assert source["merged_into"] == "on-1"
assert coordinator.state.nilm_review_by_circuit["mains"][0]["review_state"] in {"expected", "merged"}
```

Also assert `_refresh_nilm_state` excludes ignored and merged signatures from active discovered signature count, while expected/labeled signatures remain visible.

- [ ] **Step 2: Run NILM review tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_coordinator.py::test_nilm_signature_expected_and_merge_review_state -q
```

Expected: FAIL because the methods do not exist.

- [ ] **Step 3: Implement NILM review methods**

Add:

```python
async def async_mark_nilm_signature_expected(self, circuit_id: str, signature_id: str) -> None: ...
async def async_merge_nilm_signatures(self, circuit_id: str, source_signature_id: str, target_signature_id: str) -> None: ...
```

Update `_nilm_signature_payloads` to preserve `review_state`, `expected`, `merged_into`, `ignored`, and `user_label`. Update `_refresh_nilm_state` to set `state.nilm_review_by_circuit[circuit_id]`.

- [ ] **Step 4: Write failing mapping review text test**

Extend `tests/test_config_flow.py::test_format_mapping_suggestions_shows_confirmation_text` so it asserts the formatted text includes:

```python
"accept, edit, mark as mixed, or exclude"
"required metric availability"
"optional metric availability"
```

- [ ] **Step 5: Run config-flow test to verify it fails**

Run:

```powershell
python -m pytest tests/test_config_flow.py::test_format_mapping_suggestions_shows_confirmation_text -q
```

Expected: FAIL until the wording is enhanced.

- [ ] **Step 6: Implement mapping review wording**

Update `format_mapping_suggestions` to include the explicit review actions and mention required/optional metric availability as possible confidence reasons. Keep existing confidence/reasons output.

- [ ] **Step 7: Run NILM, config-flow, and service tests**

Run:

```powershell
python -m pytest tests/test_coordinator.py tests/test_services.py tests/test_config_flow.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

Run:

```powershell
git add custom_components/circuitsetup_energy_analyzer/coordinator.py custom_components/circuitsetup_energy_analyzer/config_flow.py tests/test_coordinator.py tests/test_services.py tests/test_config_flow.py
git commit -m "feat: add nilm and mapping review controls"
```

### Task 5: Full Verification And Cleanup

**Files:**
- Review all changed files.

- [ ] **Step 1: Run full tests**

Run:

```powershell
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run lint**

Run:

```powershell
python -m ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 3: Validate JSON**

Run:

```powershell
python -c "import json, pathlib; [json.loads(p.read_text()) for p in pathlib.Path('custom_components/circuitsetup_energy_analyzer').glob('*.json')]; print('json ok')"
```

Expected: `json ok`.

- [ ] **Step 4: Run git diff check**

Run:

```powershell
git diff --check
```

Expected: no output.

- [ ] **Step 5: Review final diff**

Run:

```powershell
git status --short
git diff --stat HEAD~4..HEAD
```

Expected: clean status after commits, with changes scoped to UX observability.

- [ ] **Step 6: Final code review**

Use a review pass focused on:

- Missing spec coverage.
- Broken Home Assistant entity naming or service dispatch.
- Alert feedback suppressing Repairs by mistake.
- Sensitivity aliases breaking existing `low/standard/high` configs.
- NILM review states disappearing when signatures are reclustered.

- [ ] **Step 7: Final commit if cleanup was needed**

If cleanup changed files:

```powershell
git add <changed-files>
git commit -m "fix: polish ux observability implementation"
```

---

## Self-Review Notes

- Spec coverage: All approved UX features map to tasks. Readiness/progress, health, evidence, setup review, maintenance, sensitivity, NILM review, data-quality checklist, dashboard, and feedback are covered.
- Scope: The plan remains Home Assistant-native and avoids a custom Lovelace card or external storage.
- Backward compatibility: Existing `low/standard/high` sensitivity strings remain accepted.
- Risk guard: Maintenance/feedback suppresses appliance notifications only; Repairs and data-quality state remain active.

