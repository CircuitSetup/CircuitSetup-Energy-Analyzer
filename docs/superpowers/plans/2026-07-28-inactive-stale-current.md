# Inactive Stale Current Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Suppress stale-source warnings for optional current only while fresh real power confirms that the circuit is off.

**Architecture:** Keep stale values excluded in `build_circuit_sample`, but defer the optional-current stale issue until fresh real power and the resolved turn-off threshold are known. The coordinator passes its existing resolved operating threshold through `SourceSampleBuilder`, and live expected-schedule checks reuse the coordinator path for the same result.

**Tech Stack:** Python 3.13, Home Assistant coordinator APIs, pytest, Ruff

## Global Constraints

- Do not enable ESPHome `force_update`.
- Do not add a new threshold, setting, service, entity, or frontend control.
- Never use the stale current value in analysis.
- Required-source, non-current, missing, unavailable, invalid, and timestamp issues keep their existing behavior.
- Use the saved operating turn-off override when present; otherwise use the appliance-profile default.

---

### Task 1: Normalize Inactive Stale Current

**Files:**
- Modify: `tests/test_normalize.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/normalize.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/managers/source_samples.py`

**Interfaces:**
- Consumes: `CircuitConfig`, `SourceState`, and the resolved turn-off threshold in watts.
- Produces: `build_circuit_sample(..., inactive_power_threshold_w: float | None = None)` and `SourceSampleBuilder.sample_for_config(..., inactive_power_threshold_w: float | None = None)`.

- [ ] **Step 1: Write the failing normalization test**

Add one focused test that builds a circuit with fresh real power plus stale
current and voltage:

```python
def test_build_circuit_sample_suppresses_stale_current_only_while_inactive() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    config = CircuitConfig(
        circuit_id="dryer",
        name="Dryer",
        mode=CircuitMode.SINGLE_PHASE,
        appliance_profile=ApplianceProfile.DRYER,
        sensors=(
            SensorRef("sensor.dryer_power", SensorRole.REAL_POWER),
            SensorRef("sensor.dryer_current", SensorRole.CURRENT),
            SensorRef("sensor.dryer_voltage", SensorRole.VOLTAGE),
        ),
    )
    states = {
        "sensor.dryer_power": SourceState(
            "sensor.dryer_power", "10", "W", now
        ),
        "sensor.dryer_current": SourceState(
            "sensor.dryer_current", "0.001", "A", now - timedelta(minutes=30)
        ),
        "sensor.dryer_voltage": SourceState(
            "sensor.dryer_voltage", "240", "V", now - timedelta(minutes=30)
        ),
    }

    inactive = build_circuit_sample(
        config,
        states,
        now,
        inactive_power_threshold_w=10.0,
    )
    states["sensor.dryer_power"] = SourceState(
        "sensor.dryer_power", "11", "W", now
    )
    active = build_circuit_sample(
        config,
        states,
        now,
        inactive_power_threshold_w=10.0,
    )

    assert inactive.current is None
    assert "sensor.dryer_current stale" not in inactive.quality_issues
    assert "sensor.dryer_voltage stale" in inactive.quality_issues
    assert "sensor.dryer_current stale" in active.quality_issues
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_normalize.py::test_build_circuit_sample_suppresses_stale_current_only_while_inactive -q
```

Expected: FAIL because `build_circuit_sample` does not accept
`inactive_power_threshold_w`.

- [ ] **Step 3: Implement the minimal normalization policy**

Add the keyword-only parameter:

```python
def build_circuit_sample(
    config: CircuitConfig,
    states: dict[str, SourceState],
    now: datetime,
    *,
    inactive_power_threshold_w: float | None = None,
) -> NormalizedCircuitSample:
```

Collect stale current entity IDs instead of immediately adding their stale
issues. After all values are parsed, append those issues unless fresh raw real
power is available and satisfies:

```python
abs(raw_real_power) <= inactive_power_threshold_w
```

Always leave stale current as `None`. Pass the same optional keyword from
`SourceSampleBuilder.sample_for_config` to each single-phase build and both
dual-phase leg builds. Do not change the parallel mains aggregation path.

- [ ] **Step 4: Run normalization tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_normalize.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the normalization change**

```powershell
git add tests/test_normalize.py custom_components/circuitsetup_energy_analyzer/normalize.py custom_components/circuitsetup_energy_analyzer/managers/source_samples.py
git commit -m "fix: ignore inactive stale current warnings"
```

### Task 2: Supply the Resolved Threshold

**Files:**
- Modify: `tests/test_coordinator.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/coordinator.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/expected_schedule.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `resolve_operating_detection_from_settings(config, settings).profile.off_threshold_w`.
- Produces: Coordinator samples whose quality issues consistently honor the profile default or saved override.

- [ ] **Step 1: Write the failing coordinator boundary test**

Add a test with fresh 11 W power and stale current. Store a 12 W override, assert
the stale issue is absent, then store a 10 W override and assert it is present:

```python
def test_sample_for_config_uses_operating_off_threshold_for_stale_current() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

    class FakeStates:
        def get(self, entity_id: str):
            value, unit, updated = {
                "sensor.dryer_power": ("11", "W", now),
                "sensor.dryer_current": (
                    "0.001",
                    "A",
                    now - timedelta(minutes=30),
                ),
            }[entity_id]
            return SimpleNamespace(
                state=value,
                attributes={"unit_of_measurement": unit},
                last_updated=updated,
            )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(states=FakeStates(), data={}),
        entry_data={
            CONF_CIRCUITS: [{
                "circuit_id": "dryer",
                "name": "Dryer",
                "mode": "single_phase",
                "appliance_profile": "dryer",
                "sensors": [
                    {"entity_id": "sensor.dryer_power", "role": "real_power"},
                    {"entity_id": "sensor.dryer_current", "role": "current"},
                ],
            }]
        },
        now_fn=lambda: now,
    )
    config = coordinator.circuit_configs[0]
    settings = coordinator.store_data.operating_detection_settings_by_circuit

    settings["dryer"] = {"operating_off_threshold_w": 12.0}
    inactive = coordinator._sample_for_config(config, now)
    settings["dryer"] = {"operating_off_threshold_w": 10.0}
    active = coordinator._sample_for_config(config, now)

    assert "sensor.dryer_current stale" not in inactive.quality_issues
    assert "sensor.dryer_current stale" in active.quality_issues
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_coordinator.py::test_sample_for_config_uses_operating_off_threshold_for_stale_current -q
```

Expected: FAIL because the coordinator does not pass a threshold.

- [ ] **Step 3: Wire the existing operating threshold into sampling**

Import `resolve_operating_detection_from_settings` in `coordinator.py`. In
`_sample_for_config`, resolve the circuit settings from
`store_data.operating_detection_settings_by_circuit`, then pass
`profile.off_threshold_w` to `SourceSampleBuilder.sample_for_config`.

In `_live_source_checklist`, prefer the coordinator's `_sample_for_config`
method so expected-schedule readiness uses the identical live sample policy.
Retain the existing direct builder fallback for lightweight test doubles.

- [ ] **Step 4: Document the user-visible boundary**

After the Repairs behavior in `README.md`, add:

```markdown
An unchanged optional current source is not reported as stale while a fresh
real-power source remains at or below that circuit's configured turn-off
threshold. The warning returns when the load becomes active.
```

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_normalize.py tests\test_coordinator.py::test_sample_for_config_uses_operating_off_threshold_for_stale_current tests\test_coordinator.py::test_stale_source_repair_waits_for_learning_and_names_stale_sensor tests\test_expected_schedule.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Run project verification**

Run:

```powershell
.\.codex\scripts\verify-pr.ps1 -HomeAssistant
```

Expected: diff check, Ruff, unit tests, and Home Assistant contract tests pass.

- [ ] **Step 7: Review the final diff and commit**

Confirm no frontend files or version constants changed:

```powershell
git diff --check
git diff --stat HEAD
git status --short
```

Then commit:

```powershell
git add README.md tests/test_coordinator.py custom_components/circuitsetup_energy_analyzer/coordinator.py custom_components/circuitsetup_energy_analyzer/expected_schedule.py
git commit -m "fix: apply inactive current stale policy"
```
