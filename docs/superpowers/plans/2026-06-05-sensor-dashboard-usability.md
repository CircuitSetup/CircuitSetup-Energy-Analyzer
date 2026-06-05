# Sensor Dashboard Usability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CircuitSetup Energy Analyzer sensors easier to understand and make the sample dashboard show appliance health, unusual behavior, missing data, and evidence at a glance.

**Architecture:** Keep analysis state in the existing coordinator and expose clearer user-facing semantics through diagnostic entity states and attributes. Add an explicit energy-tracking state so `0 kWh` is not confused with "no data yet", then reorganize the standard Home Assistant dashboard YAML around appliance health summaries and drilldown sections.

**Tech Stack:** Home Assistant custom integration, Python 3.12 dataclasses/services/config flow, standard Home Assistant entities and dashboard YAML, pytest, Ruff.

---

## Current State Map

- `custom_components/circuitsetup_energy_analyzer/usage.py` derives daily kWh from cumulative energy deltas. The first cumulative sample records a baseline and returns `0.0` daily usage.
- `custom_components/circuitsetup_energy_analyzer/coordinator.py` stores energy usage evidence in `state.energy_usage_evidence_by_circuit`.
- `custom_components/circuitsetup_energy_analyzer/sensor.py` exposes `Daily Energy Usage`, `Energy Usage Share`, and `Energy Usage Status`, and already adds `status_label`, `raw_status`, and `status_explanation` for status sensors.
- `custom_components/circuitsetup_energy_analyzer/ux.py` already owns health summary, learning progress, and data-quality checklist logic.
- `docs/dashboard-example.yaml` already has overview, recent behavior, power quality, HVAC demand, energy usage, and mains NILM sections, but it still reads like a diagnostic sensor list rather than an appliance status surface.
- `README.md` already includes a Status Glossary and sensor reference. It should be expanded where sensor states are easy to misread.

## File Structure

- Modify `custom_components/circuitsetup_energy_analyzer/usage.py`: add explicit energy-tracking status fields to `EnergyUsageResult`.
- Modify `custom_components/circuitsetup_energy_analyzer/coordinator.py`: include the new energy-tracking status, label, explanation, and suggested next check in energy usage evidence.
- Modify `custom_components/circuitsetup_energy_analyzer/sensor.py`: reuse status-help attributes for energy usage sensors, add clear labels/explanations for new energy-tracking states, and keep raw machine values available.
- Modify `docs/dashboard-example.yaml`: reorganize the sample dashboard around "Needs attention", "Appliance overview", "Energy tracking", "Power quality", and "Mains, solar, and NILM".
- Modify `README.md`: document how to interpret `0 kWh`, learning states, missing metrics, and the dashboard layout.
- Add or replace `docs/images/readme/*.png`: refresh README screenshots from the actual Home Assistant UI, cropped to the relevant panel/window and excluding browser URL bars or the Windows taskbar.
- Modify `tests/test_usage.py`: cover first-sample, true-zero, learning-window, and spike states.
- Modify `tests/test_entities.py`: cover status attributes and readable entity behavior.
- Modify `tests/test_coordinator.py`: cover runtime evidence payloads.
- Modify `tests/test_user_facing_text.py`: cover README and dashboard wording.

---

### Task 1: Explicit Energy Tracking Semantics

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/usage.py`
- Test: `tests/test_usage.py`

- [ ] **Step 1: Write failing usage tests**

Add these tests to `tests/test_usage.py`:

```python
def test_record_energy_usage_marks_first_sample_waiting_for_delta() -> None:
    result = record_energy_usage(
        {},
        circuit_id="hvac",
        timestamp=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
        energy_kwh=108.4,
        settings=EnergyUsageSettings(),
    )

    assert result is not None
    assert result.daily_usage_kwh == 0.0
    assert result.tracking_status == "waiting_for_delta"
    assert result.status_reason == "first_cumulative_sample"


def test_record_energy_usage_distinguishes_true_zero_after_tracking() -> None:
    history = {
        "last_energy_kwh": 108.4,
        "last_sample_at": "2026-06-05T08:00:00+00:00",
        "days": [
            {"date": "2026-05-29", "usage_kwh": 7.1},
            {"date": "2026-05-30", "usage_kwh": 6.9},
            {"date": "2026-05-31", "usage_kwh": 7.4},
            {"date": "2026-06-01", "usage_kwh": 8.0},
            {"date": "2026-06-02", "usage_kwh": 7.8},
            {"date": "2026-06-03", "usage_kwh": 8.3},
            {"date": "2026-06-04", "usage_kwh": 7.5},
        ],
    }

    result = record_energy_usage(
        history,
        circuit_id="hvac",
        timestamp=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
        energy_kwh=108.4,
        settings=EnergyUsageSettings(),
    )

    assert result is not None
    assert result.daily_usage_kwh == 0.0
    assert result.baseline_day_count == 7
    assert result.tracking_status == "tracking"
    assert result.status_reason == "no_delta_today"
```

- [ ] **Step 2: Run tests to verify red**

Run:

```powershell
pytest -q tests/test_usage.py::test_record_energy_usage_marks_first_sample_waiting_for_delta tests/test_usage.py::test_record_energy_usage_distinguishes_true_zero_after_tracking
```

Expected: FAIL with `AttributeError` for `tracking_status` and `status_reason`.

- [ ] **Step 3: Add tracking fields to the result dataclass**

In `custom_components/circuitsetup_energy_analyzer/usage.py`, extend `EnergyUsageResult`:

```python
@dataclass(frozen=True, slots=True)
class EnergyUsageResult:
    """Latest compact usage summary for a circuit."""

    circuit_id: str
    date: str
    daily_usage_kwh: float
    baseline_total_kwh: float
    baseline_day_count: int
    window_days: int
    threshold_ratio: float
    threshold_kwh: float
    daily_usage_share: float
    tracking_status: str
    status_reason: str
    spike: EnergyUsageSpike | None = None
```

Compute the fields in `record_energy_usage` after `delta_kwh` is known:

```python
initial_sample = last_energy is None or last_sample_at is None
if initial_sample:
    tracking_status = "waiting_for_delta"
    status_reason = "first_cumulative_sample"
elif baseline_day_count < window_days:
    tracking_status = "learning"
    status_reason = "building_energy_window"
elif delta_kwh <= 0.0:
    tracking_status = "tracking"
    status_reason = "no_delta_today"
else:
    tracking_status = "tracking"
    status_reason = "observed_energy_delta"
```

When a spike is returned, use `replace(result, tracking_status="over_threshold", status_reason="daily_usage_above_threshold", spike=spike)`.

- [ ] **Step 4: Verify usage tests pass**

Run:

```powershell
pytest -q tests/test_usage.py
```

Expected: all usage tests pass.

---

### Task 2: Clear Energy Usage Evidence Attributes

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/coordinator.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/sensor.py`
- Test: `tests/test_coordinator.py`
- Test: `tests/test_entities.py`

- [ ] **Step 1: Write failing coordinator evidence test**

Add this test to `tests/test_coordinator.py` near the existing energy usage tests:

```python
async def test_runtime_marks_energy_usage_waiting_for_delta() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator as coordinator_module,
    )

    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            assert entity_id == "sensor.hvac_energy"
            return SimpleNamespace(
                state="108.4",
                attributes={"unit_of_measurement": "kWh"},
                last_updated=now,
            )

    hass = SimpleNamespace(states=FakeStates(), data={DOMAIN: {}})
    coordinator = coordinator_module.EnergyAnalyzerCoordinator(
        hass,
        entry_id="entry-1",
        entry_data={
            CONF_CIRCUITS: [
                {
                    "circuit_id": "hvac",
                    "name": "HVAC",
                    "appliance_profile": "hvac",
                    "sensors": [
                        {"entity_id": "sensor.hvac_energy", "role": "energy"},
                    ],
                }
            ],
        },
        now_fn=lambda: now,
    )

    await coordinator.async_process_update()

    evidence = coordinator.state.energy_usage_evidence_by_circuit["hvac"]
    assert evidence["status"] == "waiting_for_delta"
    assert evidence["status_label"] == "Waiting For Energy Change"
    assert evidence["status_reason"] == "first_cumulative_sample"
    assert "cumulative kWh" in evidence["status_explanation"]
    assert evidence["suggested_next_check"] == (
        "Let the analyzer see the energy sensor increase, or confirm the circuit "
        "has a cumulative kWh source."
    )
```

- [ ] **Step 2: Write failing entity attribute test**

Add this test to `tests/test_entities.py` near the status attribute tests:

```python
def test_energy_usage_sensors_explain_waiting_for_delta() -> None:
    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}
    circuit = CircuitInfo(circuit_id="hvac", name="HVAC")
    coordinator = SimpleNamespace(
        data=AnalyzerState(
            energy_usage_evidence_by_circuit={
                "hvac": {
                    "status": "waiting_for_delta",
                    "status_label": "Waiting For Energy Change",
                    "raw_status": "waiting_for_delta",
                    "status_explanation": (
                        "A cumulative kWh source is present, but the analyzer has "
                        "not observed it increase since tracking started."
                    ),
                    "suggested_next_check": (
                        "Let the analyzer see the energy sensor increase, or "
                        "confirm the circuit has a cumulative kWh source."
                    ),
                }
            },
            daily_energy_usage_by_circuit={"hvac": 0.0},
        )
    )

    attrs = CircuitAnalyzerSensor(
        coordinator,
        entry_id="entry-1",
        circuit=circuit,
        description=descriptions["daily_energy_usage"],
    ).extra_state_attributes

    assert attrs["status_label"] == "Waiting For Energy Change"
    assert attrs["raw_status"] == "waiting_for_delta"
    assert "cumulative kWh" in attrs["status_explanation"]
    assert "energy sensor increase" in attrs["suggested_next_check"]
```

- [ ] **Step 3: Run tests to verify red**

Run:

```powershell
pytest -q tests/test_coordinator.py::test_runtime_marks_energy_usage_waiting_for_delta tests/test_entities.py::test_energy_usage_sensors_explain_waiting_for_delta
```

Expected: FAIL because evidence does not include the new friendly fields.

- [ ] **Step 4: Add status copy and evidence fields**

In `sensor.py`, update `_STATUS_LABEL_OVERRIDES`:

```python
_STATUS_LABEL_OVERRIDES: Mapping[str, str] = {
    "nilm_review": "NILM Review",
    "tou_peak": "TOU Peak",
    "waiting_for_delta": "Waiting For Energy Change",
}
```

In `_STATUS_EXPLANATIONS`, add:

```python
"waiting_for_delta": (
    "A cumulative kWh source is present, but the analyzer has not observed it "
    "increase since tracking started."
),
```

In `coordinator.py`, update `_energy_usage_evidence_payload` to include:

```python
status = "over_threshold" if result.spike is not None else result.tracking_status
return {
    "date": result.date,
    "daily_usage_kwh": result.daily_usage_kwh,
    "baseline_total_kwh": result.baseline_total_kwh,
    "baseline_window_days": result.window_days,
    "baseline_day_count": result.baseline_day_count,
    "threshold_ratio": result.threshold_ratio,
    "threshold_kwh": result.threshold_kwh,
    "daily_usage_share_percent": round(result.daily_usage_share * 100, 1),
    "status": status,
    "raw_status": status,
    "status_label": _status_label_for_evidence(status),
    "status_explanation": _status_explanation_for_evidence(status),
    "status_reason": result.status_reason,
    "suggested_next_check": _energy_usage_next_check(status),
}
```

Add local helpers in `coordinator.py` so evidence payloads do not import entity classes:

```python
def _status_label_for_evidence(status: str) -> str:
    overrides = {"waiting_for_delta": "Waiting For Energy Change"}
    if status in overrides:
        return overrides[status]
    return " ".join(part.capitalize() for part in status.split("_"))


def _status_explanation_for_evidence(status: str) -> str:
    if status == "waiting_for_delta":
        return (
            "A cumulative kWh source is present, but the analyzer has not "
            "observed it increase since tracking started."
        )
    if status == "learning":
        return "The analyzer is still collecting the rolling daily kWh baseline."
    if status == "tracking":
        return "The analyzer is tracking daily usage from cumulative kWh changes."
    if status == "over_threshold":
        return "Today usage is above the configured rolling-window threshold."
    return f"{_status_label_for_evidence(status)} status reported by the analyzer."


def _energy_usage_next_check(status: str) -> str:
    if status == "waiting_for_delta":
        return (
            "Let the analyzer see the energy sensor increase, or confirm the "
            "circuit has a cumulative kWh source."
        )
    if status == "learning":
        return "Let the analyzer retain enough full days for the rolling baseline."
    if status == "tracking":
        return "No action is needed unless the usage looks wrong for the appliance."
    if status == "over_threshold":
        return "Review recent appliance runtime and confirm the mapped kWh source."
    return "Review the sensor attributes for the observed evidence."
```

- [ ] **Step 5: Verify targeted tests pass**

Run:

```powershell
pytest -q tests/test_usage.py tests/test_coordinator.py::test_runtime_marks_energy_usage_waiting_for_delta tests/test_entities.py::test_energy_usage_sensors_explain_waiting_for_delta
```

Expected: all targeted tests pass.

---

### Task 3: Sensor Meaning And Display Curation

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/sensor.py`
- Modify: `README.md`
- Test: `tests/test_entities.py`
- Test: `tests/test_user_facing_text.py`

- [ ] **Step 1: Write failing sensor display tests**

Add this test to `tests/test_entities.py`:

```python
def test_sensor_descriptions_classify_dashboard_vs_advanced_detail() -> None:
    descriptions = {description.key: description for description in SENSOR_DESCRIPTIONS}

    assert descriptions["health_summary"].entity_registry_visible_default is True
    assert descriptions["readiness"].entity_registry_visible_default is True
    assert descriptions["daily_energy_usage"].entity_registry_visible_default is True
    assert descriptions["energy_usage_status"].entity_registry_visible_default is True
    assert descriptions["power_quality_evidence"].entity_registry_visible_default is True

    assert descriptions["reactive_power_drift"].entity_category == EntityCategory.DIAGNOSTIC
    assert descriptions["apparent_power_drift"].entity_category == EntityCategory.DIAGNOSTIC
    assert descriptions["power_factor_drift"].entity_category == EntityCategory.DIAGNOSTIC
```

Add this test to `tests/test_user_facing_text.py`:

```python
def test_readme_explains_core_dashboard_sensors_and_zero_kwh() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Core Appliance Status Sensors" in readme_text
    assert "Daily Energy Usage can show 0 kWh for two different reasons" in readme_text
    assert "Waiting For Energy Change" in readme_text
    assert "true zero usage" in readme_text
    assert "not observed a cumulative kWh increase" in readme_text
```

- [ ] **Step 2: Run tests to verify red**

Run:

```powershell
pytest -q tests/test_entities.py::test_sensor_descriptions_classify_dashboard_vs_advanced_detail tests/test_user_facing_text.py::test_readme_explains_core_dashboard_sensors_and_zero_kwh
```

Expected: the README test fails until the new explanation exists. The entity test may pass already; keep it as regression coverage.

- [ ] **Step 3: Add README sensor guidance**

In `README.md`, add a section near the Status Glossary:

```markdown
## Core Appliance Status Sensors

Start with these entities on dashboards:

- Health Summary: one short state for the circuit, such as `Ready`, `Learning`, `Needs data`, or `Possible issue`.
- Readiness: machine-readable status plus attributes explaining learning progress and blocked checks.
- Alert Evidence: the strongest current evidence, written as observed behavior rather than diagnosis.
- Recent Activity: the most recent start, stop, or possible-issue event.
- Energy Usage Status: whether daily kWh tracking is waiting for a first increase, learning, tracking, or over threshold.
- Data Quality Checklist: missing, stale, or invalid source data that can block analysis.

Daily Energy Usage can show 0 kWh for two different reasons:

- True zero usage: the analyzer has already started tracking the cumulative kWh source and the source has not increased today.
- Waiting For Energy Change: a cumulative kWh source is present, but the analyzer has not observed a cumulative kWh increase since tracking started.

Use the `Energy Usage Status` entity and the `status_explanation` attribute to distinguish these cases.
```

- [ ] **Step 4: Verify sensor guidance tests pass**

Run:

```powershell
pytest -q tests/test_entities.py::test_sensor_descriptions_classify_dashboard_vs_advanced_detail tests/test_user_facing_text.py::test_readme_explains_core_dashboard_sensors_and_zero_kwh
```

Expected: both tests pass.

---

### Task 4: Appliance-First Dashboard Layout

**Files:**
- Modify: `docs/dashboard-example.yaml`
- Test: `tests/test_user_facing_text.py`

- [ ] **Step 1: Write failing dashboard structure test**

Add this test to `tests/test_user_facing_text.py`:

```python
def test_dashboard_example_is_appliance_first_and_explains_energy_tracking() -> None:
    dashboard_text = (ROOT / "docs" / "dashboard-example.yaml").read_text(
        encoding="utf-8"
    )
    dashboard = yaml.safe_load(dashboard_text)
    section_titles = {
        section.get("title")
        for section in dashboard.get("sections", [])
        if isinstance(section, dict)
    }

    assert {
        "Needs attention",
        "Appliance overview",
        "Energy tracking",
        "Power quality detail",
        "Mains, solar, and NILM",
    } <= section_titles
    assert "Waiting For Energy Change" in dashboard_text
    assert "sensor.hvac_energy_usage_status" in dashboard_text
    assert "sensor.hvac_daily_energy_usage" in dashboard_text
    assert "sensor.hvac_health_summary" in dashboard_text
    assert "sensor.hvac_alert_evidence" in dashboard_text
```

- [ ] **Step 2: Run dashboard structure test to verify red**

Run:

```powershell
pytest -q tests/test_user_facing_text.py::test_dashboard_example_is_appliance_first_and_explains_energy_tracking
```

Expected: FAIL until the dashboard sections are renamed and expanded.

- [ ] **Step 3: Replace dashboard sections with appliance-first sections**

Update `docs/dashboard-example.yaml` so the top-level sections follow this order:

```yaml
type: sections
title: Energy Analyzer
sections:
  - type: grid
    title: Needs attention
    cards:
      - type: entities
        title: Possible issues and blocked checks
        entities:
          - entity: sensor.refrigerator_health_summary
          - entity: sensor.refrigerator_alert_evidence
          - entity: sensor.hvac_health_summary
          - entity: sensor.hvac_alert_evidence
          - entity: sensor.mains_nilm_health_summary
          - entity: sensor.mains_nilm_alert_evidence
      - type: markdown
        title: Status wording
        content: >
          Alerts are possible issues based on repeated evidence. Repairs are
          reserved for setup, configuration, and data-quality problems.

  - type: grid
    title: Appliance overview
    cards:
      - type: glance
        title: Appliance health
        columns: 3
        entities:
          - entity: sensor.refrigerator_health_summary
            name: Refrigerator
          - entity: sensor.hvac_health_summary
            name: HVAC
          - entity: sensor.water_heater_health_summary
            name: Water heater
          - entity: sensor.pool_pump_health_summary
            name: Pool pump
          - entity: sensor.washer_health_summary
            name: Washer
          - entity: sensor.dryer_health_summary
            name: Dryer
      - type: entities
        title: Current classification
        entities:
          - entity: sensor.hvac_circuit_mode
          - entity: sensor.hvac_power_flow
          - entity: sensor.water_heater_circuit_mode
          - entity: sensor.water_heater_power_flow
          - entity: sensor.mains_nilm_circuit_mode
          - entity: sensor.mains_nilm_power_flow

  - type: grid
    title: Energy tracking
    cards:
      - type: entities
        title: Daily kWh status
        entities:
          - entity: sensor.refrigerator_daily_energy_usage
          - entity: sensor.refrigerator_energy_usage_status
          - entity: sensor.hvac_daily_energy_usage
          - entity: sensor.hvac_energy_usage_status
          - entity: sensor.water_heater_daily_energy_usage
          - entity: sensor.water_heater_energy_usage_status
      - type: markdown
        title: Reading 0 kWh
        content: >
          0 kWh can mean true zero usage today, or it can mean Waiting For
          Energy Change when the analyzer has not observed the cumulative kWh
          source increase yet. Check Energy Usage Status before assuming the
          appliance used no energy.

  - type: grid
    title: Power quality detail
    cards:
      - type: entities
        title: HVAC power quality
        entities:
          - entity: sensor.hvac_power_quality_score
          - entity: sensor.hvac_power_quality_evidence
          - entity: sensor.hvac_metric_consistency_status
          - entity: sensor.hvac_leg_imbalance_status
          - entity: sensor.hvac_run_cycle_status
      - type: entities
        title: Refrigerator power quality
        entities:
          - entity: sensor.refrigerator_power_quality_score
          - entity: sensor.refrigerator_power_quality_evidence
          - entity: sensor.refrigerator_metric_consistency_status
          - entity: sensor.refrigerator_run_cycle_status
          - entity: sensor.refrigerator_standby_status

  - type: grid
    title: Mains, solar, and NILM
    cards:
      - type: entities
        title: Mains overview
        entities:
          - entity: sensor.mains_nilm_readiness
          - entity: sensor.mains_nilm_balance_status
          - entity: sensor.mains_nilm_solar_flow_status
          - entity: sensor.mains_nilm_nilm_topology_status
          - entity: sensor.mains_nilm_nilm_unmatched_load_percentage
      - type: history-graph
        title: Mains power balance
        hours_to_show: 24
        entities:
          - entity: sensor.mains_nilm_balance_power
          - entity: sensor.mains_nilm_monitored_power
```

Keep the existing CSV export, alert philosophy, notifications and repairs, demand, capacity, billing, cost, standby, and solar cards by placing them after the five core sections or inside the matching section. Do not remove existing entity references that are covered by `test_dashboard_example_covers_configurable_analyzer_surfaces`.

- [ ] **Step 4: Verify dashboard tests pass**

Run:

```powershell
pytest -q tests/test_user_facing_text.py::test_dashboard_example_is_appliance_first_and_explains_energy_tracking tests/test_user_facing_text.py::test_dashboard_example_covers_configurable_analyzer_surfaces tests/test_user_facing_text.py::test_dashboard_example_uses_current_mains_nilm_entity_ids
```

Expected: all dashboard tests pass.

---

### Task 5: README Screenshot Refresh

**Files:**
- Modify: `README.md`
- Add or replace: `docs/images/readme/integration-overview.png`
- Add or replace: `docs/images/readme/options-menu.png`
- Add or replace: `docs/images/readme/assignment-editor.png`
- Add or replace: `docs/images/readme/mains-sensors.png`
- Add or replace: `docs/images/readme/advanced-settings.png`
- Add or replace: `docs/images/readme/circuit-modes.png`
- Add or replace: `docs/images/readme/power-flow.png`
- Add or replace: `docs/images/readme/energy-usage-spikes.png`
- Add or replace: `docs/images/readme/daily-energy-goals.png`
- Add or replace: `docs/images/readme/run-cycle-diagnostics.png`
- Add or replace: `docs/images/readme/recent-activity-timeline.png`
- Add or replace: `docs/images/readme/billing-cycle-forecasts.png`
- Add or replace: `docs/images/readme/cost-time-of-use.png`
- Add or replace: `docs/images/readme/history-csv-export.png`
- Add or replace: `docs/images/readme/peak-demand-tracking.png`
- Add or replace: `docs/images/readme/circuit-capacity-tracking.png`
- Add or replace: `docs/images/readme/dual-phase-leg-imbalance.png`
- Add or replace: `docs/images/readme/power-metric-consistency.png`
- Add or replace: `docs/images/readme/mains-balance.png`
- Add or replace: `docs/images/readme/solar-flow-diagnostics.png`
- Add or replace: `docs/images/readme/utility-comparison.png`
- Add or replace: `docs/images/readme/always-on-standby.png`
- Add or replace: `docs/images/readme/experimental-nilm.png`
- Add or replace: `docs/images/readme/alert-philosophy.png`
- Add or replace: `docs/images/readme/notifications-repairs.png`
- Add or replace: `docs/images/readme/demo-dashboard.png`
- Test: `tests/test_user_facing_text.py`

- [ ] **Step 1: Write failing README screenshot reference test**

Add `import struct` near the top of `tests/test_user_facing_text.py`, then add this test:

```python
def test_readme_screenshot_references_exist_and_are_cropped() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    refs = re.findall(
        r"!\[[^\]]+\]\((docs/images/readme/[^)]+\.png)\)",
        readme_text,
    )

    expected = {
        "docs/images/readme/integration-overview.png",
        "docs/images/readme/options-menu.png",
        "docs/images/readme/assignment-editor.png",
        "docs/images/readme/mains-sensors.png",
        "docs/images/readme/advanced-settings.png",
        "docs/images/readme/circuit-modes.png",
        "docs/images/readme/power-flow.png",
        "docs/images/readme/energy-usage-spikes.png",
        "docs/images/readme/daily-energy-goals.png",
        "docs/images/readme/run-cycle-diagnostics.png",
        "docs/images/readme/recent-activity-timeline.png",
        "docs/images/readme/billing-cycle-forecasts.png",
        "docs/images/readme/cost-time-of-use.png",
        "docs/images/readme/history-csv-export.png",
        "docs/images/readme/peak-demand-tracking.png",
        "docs/images/readme/circuit-capacity-tracking.png",
        "docs/images/readme/dual-phase-leg-imbalance.png",
        "docs/images/readme/power-metric-consistency.png",
        "docs/images/readme/mains-balance.png",
        "docs/images/readme/solar-flow-diagnostics.png",
        "docs/images/readme/utility-comparison.png",
        "docs/images/readme/always-on-standby.png",
        "docs/images/readme/experimental-nilm.png",
        "docs/images/readme/alert-philosophy.png",
        "docs/images/readme/notifications-repairs.png",
        "docs/images/readme/demo-dashboard.png",
    }

    assert expected <= set(refs)
    for ref in sorted(set(refs)):
        path = ROOT / ref
        assert path.exists(), f"{ref} is referenced by README but missing"
        width, height = _png_dimensions(path)
        assert width >= 500, f"{ref} is too narrow to show readable UI"
        assert height >= 250, f"{ref} is too short to show readable UI"
        assert not (
            width >= 1800 and height >= 1000
        ), f"{ref} looks like a full-screen capture rather than a cropped UI panel"
```

Add this helper near `_dashboard_entity_refs`:

```python
def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n"), f"{path} is not a PNG"
    return struct.unpack(">II", data[16:24])
```

- [ ] **Step 2: Run screenshot reference test to verify red if screenshots are stale**

Run:

```powershell
pytest -q tests/test_user_facing_text.py::test_readme_screenshot_references_exist_and_are_cropped
```

Expected: FAIL if a referenced screenshot is missing, too small, or still a full-screen capture. PASS is acceptable if all existing screenshots already meet the cropped-image criteria.

- [ ] **Step 3: Capture cropped Home Assistant screenshots**

Use the logged-in Chrome session or Browser plugin against `https://home.degster.com:8123`. Capture the Home Assistant content area or the specific dialog/card element, not the full browser window. Each screenshot must exclude:

- Browser URL bar.
- Browser tab strip.
- Windows taskbar or Start menu.
- Blank desktop margins.

Capture or replace these images with the matching UI target:

```text
docs/images/readme/integration-overview.png        Integration entry overview
docs/images/readme/options-menu.png                Integration options menu
docs/images/readme/assignment-editor.png           Review Circuit Assignments flow
docs/images/readme/mains-sensors.png               Mains sensor selection controls
docs/images/readme/advanced-settings.png           Advanced circuit settings panel
docs/images/readme/circuit-modes.png               Circuit Mode options
docs/images/readme/power-flow.png                  Power Flow options
docs/images/readme/energy-usage-spikes.png         Energy Usage Status / spike evidence card
docs/images/readme/daily-energy-goals.png          Daily Energy Goal card or service UI
docs/images/readme/run-cycle-diagnostics.png       Run cycle diagnostic entities
docs/images/readme/recent-activity-timeline.png    Recent Activity card
docs/images/readme/billing-cycle-forecasts.png     Billing-cycle forecast card
docs/images/readme/cost-time-of-use.png            Cost and TOU settings/card
docs/images/readme/history-csv-export.png          CSV export service/action
docs/images/readme/peak-demand-tracking.png        Peak demand card
docs/images/readme/circuit-capacity-tracking.png   Circuit capacity card
docs/images/readme/dual-phase-leg-imbalance.png    Dual-phase leg imbalance card
docs/images/readme/power-metric-consistency.png    Metric consistency evidence
docs/images/readme/mains-balance.png               Mains balance evidence
docs/images/readme/solar-flow-diagnostics.png      Solar flow diagnostics
docs/images/readme/utility-comparison.png          Utility/Opower comparison options with private text redacted
docs/images/readme/always-on-standby.png           Always On / standby card
docs/images/readme/experimental-nilm.png           Experimental NILM review/card
docs/images/readme/alert-philosophy.png            Alert philosophy dashboard card
docs/images/readme/notifications-repairs.png       Notifications and Repairs evidence
docs/images/readme/demo-dashboard.png              Updated appliance-first sample dashboard
```

When using browser automation, prefer element screenshots or a clipped viewport screenshot. Do not use a screenshot that includes the Chrome address bar and then rely on README cropping to hide it.

- [ ] **Step 4: Update README alt text and image placement**

In `README.md`, keep every screenshot close to the section it demonstrates. Update alt text so it names the actual UI surface, for example:

```markdown
![Energy usage status showing Waiting For Energy Change and daily kWh evidence](docs/images/readme/energy-usage-spikes.png)
```

For the sample dashboard screenshot near the dashboard section, use:

```markdown
![Appliance-first Energy Analyzer dashboard with health summaries and evidence cards](docs/images/readme/demo-dashboard.png)
```

- [ ] **Step 5: Verify screenshots and README references**

Run:

```powershell
pytest -q tests/test_user_facing_text.py::test_readme_screenshot_references_exist_and_are_cropped
git diff --check -- README.md docs/images/readme tests/test_user_facing_text.py
```

Expected: screenshot reference test passes and whitespace check exits 0.

---

### Task 6: Appliance Drilldown Guidance

**Files:**
- Modify: `README.md`
- Modify: `docs/dashboard-example.yaml`
- Test: `tests/test_user_facing_text.py`

- [ ] **Step 1: Write failing README drilldown test**

Add this test to `tests/test_user_facing_text.py`:

```python
def test_readme_describes_appliance_drilldown_pattern() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Appliance Drilldown Pattern" in readme_text
    assert "Current state" in readme_text
    assert "Energy tracking" in readme_text
    assert "Power quality evidence" in readme_text
    assert "Recent activity" in readme_text
    assert "Setup and data quality" in readme_text
```

- [ ] **Step 2: Run test to verify red**

Run:

```powershell
pytest -q tests/test_user_facing_text.py::test_readme_describes_appliance_drilldown_pattern
```

Expected: FAIL until the README section exists.

- [ ] **Step 3: Add drilldown guidance**

Add this README section near the dashboard example:

```markdown
## Appliance Drilldown Pattern

For each important appliance, use the same card order so the dashboard is easy to scan:

1. Current state: Health Summary, Readiness, Recent Activity, and Alert Evidence.
2. Energy tracking: Daily Energy Usage, Energy Usage Status, Daily Goal, Billing Cycle, and Cost.
3. Power quality evidence: Power Quality Score, Power Quality Evidence, Metric Consistency Status, and any drift sensors relevant to the appliance.
4. Run behavior: Run Cycle Status, Run Cycle Runtime, Run Cycle Duty Cycle, and Recent Activity Count.
5. Capacity and phase checks: Capacity Status, Demand Peak Status, and Dual-Phase Leg Imbalance for dual-phase appliances.
6. Setup and data quality: Data Quality Checklist, Energy Dashboard Status, Circuit Mode, and Power Flow.

This keeps the first card useful for daily use while leaving the detailed evidence nearby when something looks unusual.
```

- [ ] **Step 4: Verify README drilldown test passes**

Run:

```powershell
pytest -q tests/test_user_facing_text.py::test_readme_describes_appliance_drilldown_pattern
```

Expected: PASS.

---

### Task 7: Full Verification And Commit

**Files:**
- All touched files

- [ ] **Step 1: Run focused test set**

Run:

```powershell
pytest -q tests/test_usage.py tests/test_entities.py tests/test_coordinator.py::test_runtime_marks_energy_usage_waiting_for_delta tests/test_user_facing_text.py
```

Expected: all selected tests pass.

- [ ] **Step 2: Run full test suite**

Run:

```powershell
pytest -q
```

Expected: full suite passes.

- [ ] **Step 3: Run static and whitespace checks**

Run:

```powershell
ruff check .
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 4: Review diff**

Run:

```powershell
git diff --stat
git diff -- custom_components/circuitsetup_energy_analyzer/usage.py custom_components/circuitsetup_energy_analyzer/coordinator.py custom_components/circuitsetup_energy_analyzer/sensor.py docs/dashboard-example.yaml README.md docs/images/readme tests/test_user_facing_text.py
```

Expected: diff is limited to energy tracking clarity, status copy, dashboard YAML, README docs/screenshots, and matching tests.

- [ ] **Step 5: Commit and push**

Run:

```powershell
git add custom_components/circuitsetup_energy_analyzer/usage.py custom_components/circuitsetup_energy_analyzer/coordinator.py custom_components/circuitsetup_energy_analyzer/sensor.py README.md docs/dashboard-example.yaml docs/images/readme tests/test_usage.py tests/test_entities.py tests/test_coordinator.py tests/test_user_facing_text.py
git commit -m "feat: clarify energy analyzer sensor dashboard states"
git push origin master
```

Expected: commit succeeds and `master` is pushed.

---

## Self-Review

- Spec coverage: The plan addresses clearer sensor meaning, better status wording, the ambiguous `0 kWh` daily usage case, appliance-first dashboard organization, issue/evidence visibility, README screenshot refreshes, and README guidance.
- Existing work preserved: The plan builds on existing health summary, readiness, status glossary, dashboard coverage, and Home Assistant-native entities rather than replacing them with a custom card.
- Non-goals: This plan does not recreate Home Assistant's Energy Dashboard, does not add definitive appliance diagnosis wording, and does not remove raw diagnostic evidence for advanced users.
- Verification coverage: Unit tests cover the new energy-tracking semantics. Entity/coordinator tests cover the user-facing evidence. README/dashboard tests cover the visible wording, layout, screenshot references, and cropped-image dimensions. Full suite plus Ruff and `git diff --check` cover regression risk.
