# Usage Pipeline Blocking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove avoidable persistence, Recorder, and retained-history work from source-driven usage updates without changing analyzer results.

**Architecture:** Use Home Assistant's delayed storage callback for off-loop serialization, keep utility comparison results in state while refreshing them on a fixed cadence, and build per-circuit event and alert lists once per coordinator update. Existing public coordinator and store interfaces remain unchanged.

**Tech Stack:** Python 3.12, Home Assistant `Store`, asyncio, pytest, Ruff.

## Global Constraints

- Keep all entity, storage schema, learning, alert, and utility calculation contracts unchanged.
- Add no dependency, background worker, scheduler, or compatibility path.
- Utility comparisons refresh immediately on first use or settings change and otherwise at most once per 15 minutes.
- Generated codegraph output remains local-only.

---

### Task 1: Defer Feature Store Serialization

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/storage.py:807`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: Home Assistant `Store.async_delay_save(data_func, delay)`.
- Produces: unchanged `FeatureStore.async_save() -> None` async interface.

- [ ] **Step 1: Write the failing delayed-save test**

Add a test that constructs `FeatureStore` without its Home Assistant constructor,
injects a fake HA store, and proves serialization is not performed until the
delayed callback runs:

```python
@pytest.mark.asyncio
async def test_feature_store_defers_serialization_to_ha_storage() -> None:
    scheduled: list[tuple[Callable[[], dict[str, Any]], float]] = []

    class FakeHAStore:
        def async_delay_save(
            self,
            data_func: Callable[[], dict[str, Any]],
            delay: float,
        ) -> None:
            scheduled.append((data_func, delay))

    store = FeatureStore.__new__(FeatureStore)
    store._store = FakeHAStore()
    store.data = FeatureStoreData()

    await store.async_save()

    assert len(scheduled) == 1
    data_func, delay = scheduled[0]
    assert delay == 0
    store.data.learning_started_at_by_circuit["fridge"] = "2026-07-25T12:00:00+00:00"
    assert data_func()["learning_started_at_by_circuit"] == {
        "fridge": "2026-07-25T12:00:00+00:00"
    }
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_storage.py::test_feature_store_defers_serialization_to_ha_storage -q
```

Expected: FAIL because the existing method calls `FakeHAStore.async_save`.

- [ ] **Step 3: Use Home Assistant's native delayed write**

Change `FeatureStore.async_save()` to:

```python
async def async_save(self: Self) -> None:
    """Schedule persistence without serializing on the event loop."""
    self._store.async_delay_save(
        lambda: feature_store_data_to_dict(self.data),
        delay=0,
    )
```

Do not add a custom lock or executor. The method contains no `await`, so
`StorePersistenceManager` cannot clear `dirty` after an intervening task switch.

- [ ] **Step 4: Run persistence tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_storage.py tests\test_coordinator.py -k "store or save or persistence" -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/circuitsetup_energy_analyzer/storage.py tests/test_storage.py
git commit -m "fix: defer feature store serialization"
```

---

### Task 2: Bound Utility Comparison Refreshes

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/managers/processing_pipeline.py:1-235`
- Test: `tests/test_processors.py:286`

**Interfaces:**
- Consumes: `ProcessingContext.now` and
  `store_data.utility_comparison_settings_by_circuit`.
- Produces: unchanged `async_process_cross_circuit(samples, context) -> list[Any]`.

- [ ] **Step 1: Write failing cadence tests**

Extend the cross-circuit pipeline fixture with an async utility processor that
counts calls. Add two tests:

```python
await pipeline.async_process_cross_circuit([], SimpleNamespace(now=now))
await pipeline.async_process_cross_circuit(
    [],
    SimpleNamespace(now=now + timedelta(minutes=5)),
)
assert utility.calls == 1
```

Then change the stored settings and advance time:

```python
coordinator.store_data.utility_comparison_settings_by_circuit["mains"] = {
    "tolerance_percent": 12.0,
}
await pipeline.async_process_cross_circuit(
    [],
    SimpleNamespace(now=now + timedelta(minutes=6)),
)
await pipeline.async_process_cross_circuit(
    [],
    SimpleNamespace(now=now + timedelta(minutes=21)),
)
assert utility.calls == 3
```

- [ ] **Step 2: Run the cadence tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_processors.py -k "cross_circuit and utility" -q
```

Expected: FAIL because the utility processor runs on every call.

- [ ] **Step 3: Add the minimal cadence state**

In `processing_pipeline.py`:

```python
from copy import deepcopy
from datetime import datetime, timedelta

UTILITY_COMPARISON_REFRESH_INTERVAL = timedelta(minutes=15)
```

Initialize two dictionaries in `ProcessingPipeline.__init__`:

```python
self._utility_comparison_refreshed_at: dict[str, datetime] = {}
self._utility_comparison_settings: dict[str, Any] = {}
```

Before the existing utility loop, remove keys for circuits no longer configured.
For each configured circuit, compare the current settings by value and skip the
processor unless the settings changed or the interval elapsed. Copy settings and
record `context.now` before awaiting the processor so Recorder failures are also
throttled.

- [ ] **Step 4: Run processor tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_processors.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/circuitsetup_energy_analyzer/managers/processing_pipeline.py tests/test_processors.py
git commit -m "fix: bound utility comparison refreshes"
```

---

### Task 3: Reuse Per-Circuit UX History

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/coordinator.py:364-479`
- Modify: `custom_components/circuitsetup_energy_analyzer/managers/ux_state.py:66-240`
- Modify: `custom_components/circuitsetup_energy_analyzer/managers/state_reducer.py:199-218`
- Test: `tests/test_coordinator.py:2501`

**Interfaces:**
- Consumes: retained `CircuitEvent` and `AlertEvidence` collections.
- Produces: optional `circuit_events` and `circuit_alerts` keyword arguments on
  internal UX refresh methods; existing callers may omit them.

- [ ] **Step 1: Write the failing one-pass grouping test**

Add a source-update test with one retained event and alert per circuit. Replace
`coordinator._refresh_ux_state` with a capture function accepting
`circuit_events` and `circuit_alerts`, then assert:

```python
assert {
    circuit_id: [item.circuit_id for item in items]
    for circuit_id, items in captured_events.items()
} == {
    "fridge": ["fridge"],
    "hvac": ["hvac"],
    "well_pump": [],
}
```

Use a `list` subclass that increments a counter in `__iter__` for the global
events and alerts collections, and assert each global collection is iterated
once while building the indexes.

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_coordinator.py -k "source_update_reuses_per_circuit_ux_history" -q
```

Expected: FAIL because `_refresh_ux_state` receives no prefiltered history.

- [ ] **Step 3: Group retained evidence once**

Add a private module helper:

```python
def _items_by_circuit(items: Iterable[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for item in items:
        grouped.setdefault(item.circuit_id, []).append(item)
    return grouped
```

After `process_events_into_state`, build event and alert mappings once. Pass the
matching lists into every `_refresh_ux_state` call.

Extend `UxStateManager.refresh_config()` with optional `circuit_events` and
`circuit_alerts`. Use the filtered events for `learning_progress()` and
`summarize_circuit_cycles()`. Choose the latest alert from active alerts first,
then the filtered stored alerts.

Extend `StateReducer.refresh_recent_activity_state()` with optional `events` and
`alerts`, passing them to `build_recent_activity_timeline()`. When omitted, use
the full store collections to preserve direct-call behavior.

- [ ] **Step 4: Run UX and coordinator tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_coordinator.py tests\test_activity_timeline.py tests\test_cycles.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/circuitsetup_energy_analyzer/coordinator.py custom_components/circuitsetup_energy_analyzer/managers/ux_state.py custom_components/circuitsetup_energy_analyzer/managers/state_reducer.py tests/test_coordinator.py
git commit -m "perf: reuse per-circuit UX history"
```

---

### Task 4: Verify PR 1

**Files:**
- Review: `README.md`
- Regenerate locally: `docs/codegraph/*`

**Interfaces:**
- Produces: a clean, verified `fix/usage-pipeline-blocking` branch.

- [ ] **Step 1: Regenerate the local codegraph**

Run:

```powershell
.\.codex\scripts\update-codegraph.ps1
```

Confirm generated codegraph files are not staged.

- [ ] **Step 2: Review documentation impact**

Read `README.md` sections covering storage, utility comparison, and retained
history. Do not edit it unless it promises per-source utility refreshes or
synchronous disk completion; the intended behavior and setup are unchanged.

- [ ] **Step 3: Run full PR verification**

Run:

```powershell
.\.codex\scripts\verify-pr.ps1 -HomeAssistant
```

Expected: Ruff clean, all unit tests pass, and Home Assistant contract tests
pass.

- [ ] **Step 4: Inspect the final diff**

Run:

```powershell
git diff --check origin/master...HEAD
git diff --stat origin/master...HEAD
git status --short
```

Confirm only the approved spec, plan, implementation, and regression tests are
tracked.
