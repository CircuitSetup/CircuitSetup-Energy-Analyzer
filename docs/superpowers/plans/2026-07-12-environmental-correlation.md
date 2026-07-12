# Environmental Correlation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct environmental evidence timing without changing configured appliance associations.

**Architecture:** Keep `EnvironmentalContextManager` as the sole orchestrator. It will derive active appliance durations from cycle evidence, aggregate only appliances sharing a configured flow source, and retain a last-rain timestamp in existing evidence.

**Tech Stack:** Python 3.12, Home Assistant helpers, pytest.

## Global Constraints

- Preserve current outdoor-temperature, rain, and water-flow profile sets.
- Add no dependency, scheduler, configuration field, or storage schema.
- Treat global flow sources as shared and linked flow sources as circuit-specific.
- Use `C:\Users\John\Documents\CS_energy_analyzer\.venv\Scripts\python.exe` for tests until this worktree installs its own dependencies.

---

### Task 1: Correct Flow Source State And Shared-Load Evaluation

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/water_correlations.py:39-249`
- Modify: `custom_components/circuitsetup_energy_analyzer/managers/environmental_context.py:326-448`
- Test: `tests/test_water_correlations.py`
- Test: `tests/test_coordinator.py`

**Interfaces:** Add `mapped_appliance_runtime_minutes: float = 0.0` and `flow_source_configured: bool = True` to `FlowCorrelationInput`. Add `active_runtime_minutes_for_circuit(circuit_id: str) -> float` and `mapped_water_appliance_context(flow_entities: Iterable[str]) -> tuple[int, float]` to `EnvironmentalContextManager`.

- [ ] **Step 1: Write failing evaluator tests**

```python
def test_flow_without_configured_sensor_is_unconfigured() -> None:
    evidence = evaluate_flow_correlation(
        FlowCorrelationInput(
            circuit_id="well", appliance_profile="well_pump",
            flow_active_minutes=0.0, appliance_runtime_minutes=12.0,
            recent_related_runtime_minutes=0.0, mapped_appliance_count=0,
            threshold_minutes=5, expects_water_flow=True,
            comparable_window_count=12, flow_source_configured=False,
        )
    )
    assert evidence["status"] == "unconfigured"

def test_shared_flow_is_explained_by_another_mapped_load() -> None:
    evidence = evaluate_flow_correlation(
        FlowCorrelationInput(
            circuit_id="washer", appliance_profile="washer",
            flow_active_minutes=8.0, appliance_runtime_minutes=0.0,
            recent_related_runtime_minutes=0.0, mapped_appliance_count=2,
            threshold_minutes=5, expects_water_flow=True,
            comparable_window_count=12, mapped_appliance_runtime_minutes=8.0,
        )
    )
    assert evidence["status"] == "normal"
```

- [ ] **Step 2: Verify red**

```powershell
& 'C:\Users\John\Documents\CS_energy_analyzer\.venv\Scripts\python.exe' -m pytest tests\test_water_correlations.py -q
```

Expected: the new input fields and expectations fail.

- [ ] **Step 3: Implement the smallest evaluator and manager change**

```python
@dataclass(frozen=True, slots=True)
class FlowCorrelationInput:
    # Existing required fields remain unchanged.
    mapped_appliance_runtime_minutes: float = 0.0
    flow_source_configured: bool = True

if not inputs.flow_source_configured:
    status = "unconfigured"
    friendly_summary = "No water-flow sensor is configured for this appliance."

if flow_active >= threshold_minutes and mapped_appliance_runtime <= 0.0:
    status = "possible_flow_without_load"

def active_runtime_minutes_for_circuit(self, circuit_id: str) -> float:
    evidence = self._coordinator.state.run_cycle_evidence_by_circuit.get(circuit_id, {})
    if evidence.get("status") != "running":
        return 0.0
    return round(float(evidence.get("active_cycle_seconds", 0.0)) / 60.0, 3)
```

Keep `appliance_runtime_minutes` for per-circuit load-without-flow evidence. Pass source availability and shared active runtime to the evaluator. Use `context_builder.flow_entity_active` for `flow_sensor_active` so positive numeric sources are active. In manager tests, prove an idle circuit with 120 minutes of daily runtime contributes 0 active minutes, a positive numeric source is active, and another active circuit sharing the global source suppresses an idle circuit's flow-without-load finding.

- [ ] **Step 4: Verify green and commit**

```powershell
& 'C:\Users\John\Documents\CS_energy_analyzer\.venv\Scripts\python.exe' -m pytest tests\test_water_correlations.py tests\test_coordinator.py -q
git add custom_components/circuitsetup_energy_analyzer/water_correlations.py custom_components/circuitsetup_energy_analyzer/managers/environmental_context.py tests/test_water_correlations.py tests/test_coordinator.py
git commit -m "fix: align water flow with active appliances"
```

Expected: focused tests pass before the commit.

### Task 2: Honor The Configured Rain Response Window

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/managers/environmental_context.py:251-321`
- Test: `tests/test_coordinator.py`

**Interfaces:** Add `_rain_response_context(circuit_id, now, rain_active, rain_intensity, rain_intensity_unit, response_window_minutes) -> tuple[bool | None, bool, datetime | None, datetime | None]`. Add `rain_response_active`, `rain_last_active_at`, and `rain_response_expires_at` to existing rain evidence; retain raw `rain_sensor_active`.

- [ ] **Step 1: Write failing response-window tests**

```python
coordinator.state.rain_pump_context_by_circuit["sump_pump"] = {
    "rain_last_active_at": (now - timedelta(minutes=30)).isoformat(),
}
settings["rain_response_window_minutes"] = 60
evidence = coordinator.environment_context.rain_pump_context_evidence(
    sump_config, settings, now
)
assert evidence["rain_sensor_active"] is False
assert evidence["rain_response_active"] is True
assert evidence["status"] == "rain_explained"
```

Also add a 61-minute expiry case and an unavailable or ambiguous source case that cannot start or extend the window.

- [ ] **Step 2: Verify red**

```powershell
& 'C:\Users\John\Documents\CS_energy_analyzer\.venv\Scripts\python.exe' -m pytest tests\test_coordinator.py -k rain -q
```

Expected: response metadata is absent and dry-state evidence is not rain-explained.

- [ ] **Step 3: Implement and verify green**

```python
rain_info = rain_context(rain_active, rain_intensity, unit=rain_intensity_unit)
current_rain = rain_info.state in {"raining", "heavy_rain"}
last_active = now if current_rain else _datetime_or_none(
    previous.get("rain_last_active_at")
)
expires_at = (
    last_active + timedelta(minutes=response_window_minutes)
    if last_active is not None
    else None
)
recent_rain = bool(expires_at is not None and now <= expires_at)
effective_rain = current_rain or recent_rain
```

Read `previous` from `state.rain_pump_context_by_circuit`. Pass only `effective_rain` to `RainPumpCorrelationInput`, retain raw sensor values in evidence, and set response metadata. Invalid, unavailable, and ambiguous rain readings must not replace `last_active`.

```powershell
& 'C:\Users\John\Documents\CS_energy_analyzer\.venv\Scripts\python.exe' -m pytest tests\test_coordinator.py tests\test_water_correlations.py -k rain -q
git add custom_components/circuitsetup_energy_analyzer/managers/environmental_context.py tests/test_coordinator.py
git commit -m "fix: honor configured rain response windows"
```

Expected: rain-focused tests pass before the commit.

### Task 3: Verify The Environmental Contract

**Files:**
- Review: `README.md:101-104,524-537,997-1000`
- Test: `tests/test_weather_context.py`
- Test: `tests/test_water_correlations.py`
- Test: `tests/test_coordinator.py`

- [ ] **Step 1: Add profile-boundary coverage and run environmental tests**

```python
assert ApplianceProfile.HVAC in HVAC_WEATHER_CONTEXT_PROFILES
assert ApplianceProfile.WATER_HEATER not in HVAC_WEATHER_CONTEXT_PROFILES
assert ApplianceProfile.SUMP_PUMP in PUMP_WATER_CONTEXT_PROFILES
```

```powershell
& 'C:\Users\John\Documents\CS_energy_analyzer\.venv\Scripts\python.exe' -m pytest tests\test_weather_context.py tests\test_water_correlations.py tests\test_coordinator.py -q
```

Expected: PASS.

- [ ] **Step 2: Review documentation and run the project gate**

```powershell
.\.codex\scripts\verify-pr.ps1
```

Keep the README unchanged if its current source requirements and rain-window wording remain accurate. Report the two known unrelated dashboard-controller failures separately if the complete gate reproduces them.
