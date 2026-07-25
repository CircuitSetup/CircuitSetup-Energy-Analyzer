# Dashboard History Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Home dashboard totals, graphs, and activity timelines current while bounding Recorder history work.

**Architecture:** House Flow combines retained completed days with existing live daily entities, Context Graph uses statistics for multi-day ranges and incremental raw tails for one-day ranges, and timeline invalidation follows activity entity transitions. All behavior stays in the existing dashboard card module.

**Tech Stack:** JavaScript custom elements, Home Assistant REST/WebSocket APIs, Playwright, Python dashboard-contract tests.

## Global Constraints

- Preserve shared date controls, graph tooltips, comparison overlays, entity identities, and backend unit contracts.
- Use exact `daily_energy_usage` and recorded `cost_today` values; do not estimate whole-day time-of-use cost.
- Add no frontend dependency or background timer.
- Bump `panel_contracts.py::PANEL_MODULE_VERSION`.

---

### Task 1: Remove House Flow History Integration

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-dashboard-graphs.js:910-1236`
- Test: `tests/e2e/panel.spec.js:159-324`

**Interfaces:**
- Consumes: appliance `energy_today_entity` and `cost_today_entity`, plus mains
  `daily_energy_usage_entity` and `cost_today_entity`.
- Produces: existing `_rollingContributionByCircuit` and `_rangeSummary` values.

- [ ] **Step 1: Change the E2E expectation first**

Update `home energy card omits Active now and separates contribution` so it:

```javascript
expect(window.__apiCalls.filter(
  ({ apiPath }) => apiPath.includes("history/period/"),
)).toHaveLength(0);
```

Assert retained July 10-11 values are combined with the July 12 live energy
entities. Assert mains cost is `Unavailable` because its live `cost_today`
entity is unavailable. Change `sensor.fridge_energy` through
`window.__setDashboardState` and assert its contribution updates without a new
API call.

- [ ] **Step 2: Run the House Flow test and verify RED**

Run from `tests/e2e`:

```powershell
npx playwright test panel.spec.js -g "home energy card omits Active now"
```

Expected: FAIL because House Flow requests raw history and ignores the live
daily-energy entity.

- [ ] **Step 3: Replace history integration with live entity totals**

In the House Flow card:

- keep one appliance-insights request per range;
- store retained completed-day totals;
- during render, merge those totals with current daily energy and cost entity
  states when the range includes today;
- treat an explicitly required but unavailable live value as unavailable;
- remove `_refreshLiveData`, `_rollingTotals`, `_integratedEnergy`, and
  `_counterIncrease`, which become unused.

Use one helper with this shape:

```javascript
_liveRangeTotals(item, energyEntityKey, includesToday) {
  if (!includesToday) return {};
  const energyEntity = item && item[energyEntityKey];
  const costEntity = item && item.cost_today_entity;
  return {
    energy: energyEntity ? this._number(energyEntity) : null,
    cost: costEntity ? this._number(costEntity) : null,
  };
}
```

- [ ] **Step 4: Run House Flow tests and verify GREEN**

Run:

```powershell
npx playwright test panel.spec.js -g "home energy card|home totals use retained"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-dashboard-graphs.js tests/e2e/panel.spec.js
git commit -m "fix: use live dashboard total entities"
```

---

### Task 2: Bound Context Graph Refreshes

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-dashboard-graphs.js:668-870`
- Test: `tests/e2e/panel.spec.js:820-973`

**Interfaces:**
- Consumes: existing `_historyRequest(start, end, entityIds)`.
- Produces: raw REST history for one-day ranges and statistics rows for ranges
  longer than one day.

- [ ] **Step 1: Add failing statistics and tail-request assertions**

Change the DST range test so a 31-day selection expects one
`recorder/statistics_during_period` WebSocket request and no raw REST request.

Extend `dashboard graph combines dual-phase appliance power into one series`:

```javascript
const requestStart = (apiPath) => decodeURIComponent(
  apiPath.split("history/period/")[1].split("?")[0],
);
const initialRequest = historyPaths.at(-1);
await page.clock.fastForward("01:01");
window.__dashboardCard.hass = window.__dashboardHass;
await expect.poll(() => historyPaths.length).toBe(2);
expect(Date.parse(requestStart(historyPaths[1]))).toBeGreaterThan(
  Date.parse(requestStart(initialRequest)),
);
```

Return an overlapping tail row and assert the merged chart contains the new
point once.

- [ ] **Step 2: Run graph tests and verify RED**

Run:

```powershell
npx playwright test panel.spec.js -g "dual-phase appliance power|Recorder statistics for long ranges"
```

Expected: FAIL because 31-day ranges use REST and live refreshes repeat the
full-day start.

- [ ] **Step 3: Implement statistics threshold and raw-tail merging**

Change `_historyRequest()` to use REST only when `spanDays <= 1`; keep hourly
statistics through 90 days.

Keep `_historyKey` stable during live refresh. Add:

- `_historyRefreshDue` and `_historyRefreshInFlight` flags;
- a helper that finds the latest timestamp in the current payload;
- a helper that merges current and incoming rows by entity ID and timestamp;
- a one-second overlap before the latest timestamp to preserve boundary state.

On a one-day live refresh, request only the tail and merge it. On a multi-day
live refresh, reload the bounded statistics result. Ignore responses whose
captured range key no longer matches `_historyKey`. Clear the in-flight flag in
`finally`; after failures, leave refresh due so a later HA update retries.

- [ ] **Step 4: Run all graph-history tests and verify GREEN**

Run:

```powershell
npx playwright test panel.spec.js -g "dashboard graph|dashboard comparison|shared dashboard date"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-dashboard-graphs.js tests/e2e/panel.spec.js
git commit -m "fix: bound dashboard history refreshes"
```

---

### Task 3: Invalidate Timelines On Activity Changes

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-dashboard-graphs.js:1238-1367`
- Test: `tests/e2e/panel.spec.js:383-511`

**Interfaces:**
- Consumes: Home Assistant activity entity `last_changed`.
- Produces: the existing timeline history request and rendered running bands.

- [ ] **Step 1: Add the failing transition test**

Track activity history calls in the existing appliance-grid test. After selecting
`fridge`, update its state with a new transition timestamp:

```javascript
window.__setDashboardState("sensor.fridge_activity", {
  state: "Idle",
  last_changed: "2026-07-12T22:05:00.000Z",
  attributes: { is_running: false },
});
```

Assert the activity-history call count increases by one.

- [ ] **Step 2: Run the timeline test and verify RED**

Run:

```powershell
npx playwright test panel.spec.js -g "appliance grid filters live state"
```

Expected: FAIL because the range and entity-ID-only key remains unchanged.

- [ ] **Step 3: Include transition revisions in the key**

Build the timeline key from range, entity IDs, and each selected entity's
`last_changed` value:

```javascript
const revisions = ids.map((entityId) => {
  const state = this._state(entityId);
  return state && state.last_changed || "";
});
const key = `${range.start}:${range.end}:${ids.map(
  (entityId, index) => `${entityId}@${revisions[index]}`,
).join(",")}`;
```

Do not add a timer or reload on unrelated HA state changes.

- [ ] **Step 4: Run timeline tests and verify GREEN**

Run:

```powershell
npx playwright test panel.spec.js -g "activity timeline|appliance grid filters live state"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-dashboard-graphs.js tests/e2e/panel.spec.js
git commit -m "fix: refresh activity timelines on transitions"
```

---

### Task 4: Version And Verify PR 2

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/panel_contracts.py:9`
- Review: `README.md`
- Regenerate locally: `docs/codegraph/*`

**Interfaces:**
- Produces: a clean, verified `fix/dashboard-history-refresh` branch.

- [ ] **Step 1: Bump the frontend cache version**

Change:

```python
PANEL_MODULE_VERSION = "20260725-02"
```

- [ ] **Step 2: Run dashboard contract tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommended_dashboard.py tests\test_panel.py -q
```

Expected: PASS and payloads still expose daily energy, cost, and activity
entities.

- [ ] **Step 3: Run the full browser suite**

Run from `tests/e2e`:

```powershell
npx playwright test
```

Expected: all desktop and mobile projects pass with no console, layout, or
accessibility failures.

- [ ] **Step 4: Regenerate codegraph and review README**

Run:

```powershell
.\.codex\scripts\update-codegraph.ps1
```

Review `README.md` dashboard sections. Do not edit them unless they promise
raw-history integration for totals or raw history for every multi-day graph.
Keep generated codegraph output unstaged.

- [ ] **Step 5: Run full PR verification**

Run:

```powershell
.\.codex\scripts\verify-pr.ps1 -HomeAssistant
```

Expected: Ruff clean, all unit tests pass, and Home Assistant contract tests
pass.

- [ ] **Step 6: Commit the cache version**

```powershell
git add custom_components/circuitsetup_energy_analyzer/panel_contracts.py
git commit -m "chore: refresh dashboard module cache"
```

- [ ] **Step 7: Inspect the final diff**

Run:

```powershell
git diff --check origin/master...HEAD
git diff --stat origin/master...HEAD
git status --short
```

Confirm only the approved spec, plan, implementation, cache version, and
regression tests are tracked.
