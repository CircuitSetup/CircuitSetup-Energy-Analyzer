# NILM Interval Review Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users select a closed, non-ambiguous NILM session for review and approval without automatically opening the interval editor.

**Architecture:** Separate focus-only session selection from explicit session editing in the NILM workspace frontend. Keep approval eligibility authoritative in the backend panel payload so ambiguous sessions never receive an assignment action, while explicit Adjust/Edit controls continue to open the existing editor.

**Tech Stack:** Python 3.13, Home Assistant panel payloads, browser-native JavaScript, Playwright, pytest, PowerShell verification scripts.

## Global Constraints

- Selecting a non-ambiguous session review item selects its review card and focuses the same interval on the graph.
- Selection keeps the interval editor closed.
- The selected session's existing approval and rejection actions remain available.
- Ambiguous sessions remain ineligible for approval.
- Editing starts only from an explicit **Adjust interval** or **Edit interval** action.
- Draft intervals and saved label intervals retain their current selection and editing behavior.
- Bump `panel_contracts.py::PANEL_MODULE_VERSION` for shipped frontend JavaScript.
- Do not change persisted data or the backend schema.

---

### Task 1: Enforce ambiguous-session approval eligibility

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/panel_nilm.py:3231-3283`
- Test: `tests/test_panel.py`

**Interfaces:**
- Consumes: `_nilm_session_payload_with_actions(payload, reviewed_session_ids=None) -> dict[str, Any]`
- Produces: session panel payloads whose `actions.assign` exists only for assignable, unassigned, non-ambiguous sessions.

- [ ] **Step 1: Write the failing backend regression**

Add this focused case beside the existing session-payload action tests:

```python
def test_nilm_workspace_ambiguous_session_is_not_assignable() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel_nilm import (
        _nilm_session_payload_with_actions,
    )

    payload = _nilm_session_payload_with_actions(
        {
            "session_id": "session-ambiguous",
            "mains_circuit_id": "mains",
            "signature_fingerprint": "direction=on|watts=800-900",
            "start": "2026-08-11T12:00:00+00:00",
            "end": "2026-08-11T12:30:00+00:00",
            "ambiguous": True,
        }
    )

    assert "assign" not in payload.get("actions", {})
```

- [ ] **Step 2: Run the regression and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_panel.py::test_nilm_workspace_ambiguous_session_is_not_assignable -q
```

Expected: FAIL because the current payload exposes `actions.assign`.

- [ ] **Step 3: Add the minimal eligibility guard**

Change the assignment-action condition in `_nilm_session_payload_with_actions` to:

```python
if (
    nilm_signature_is_assignable(signature_fingerprint)
    and not assignment_id
    and not bool(payload.get("ambiguous"))
):
```

Do not alter validation/rejection actions for already assigned sessions.

- [ ] **Step 4: Run the focused backend tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_panel.py::test_nilm_workspace_ambiguous_session_is_not_assignable tests\test_panel.py::test_nilm_workspace_lanes_review_only_assignable_unassigned_sessions -q
```

Expected: PASS.

- [ ] **Step 5: Commit the backend eligibility change**

```powershell
git add custom_components/circuitsetup_energy_analyzer/panel_nilm.py tests/test_panel.py
git commit -m "fix: block ambiguous NILM session approval"
```

### Task 2: Decouple session selection from interval editing

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-nilm-workspace.js:1369-1397`
- Modify: `custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-nilm-workspace.js:2540-2571`
- Modify: `custom_components/circuitsetup_energy_analyzer/panel_contracts.py:10`
- Test: `tests/e2e/panel.spec.js`

**Interfaces:**
- Consumes: `_loadNilmIntervalOnGraph(interval, { edit, assignment, clearSignature, scroll }) -> Promise<boolean>`
- Produces: `_loadNilmSessionInterval(session, { edit = false, scroll = true } = {}) -> Promise<boolean>`, where review selection is focus-only and explicit adjustment opts into editing.

- [ ] **Step 1: Write the failing browser regression**

Add a test using the existing NILM workspace fixture:

```javascript
test("non-ambiguous NILM review intervals select without opening the editor", async ({ page }) => {
  await mockPanelApi(page, async ({ route, url }) => {
    if (url.pathname.endsWith("/nilm_workspace_history")) {
      await route.fulfill({ json: nilmGraphFocusHistoryFixture() });
      return true;
    }
    if (!url.pathname.endsWith("/nilm_workspace")) return false;
    const payload = structuredClone(apiPayload(url.pathname));
    payload.lanes.needs_review = {
      ...payload.lanes.needs_review,
      signature_ids: [],
      session_ids: ["nilm-session-0"],
    };
    payload.lane_counts.needs_review = 1;
    await route.fulfill({ json: payload });
    return true;
  });
  const panel = await openPanel(page, "?nilm_workspace=1&circuit_id=mains");
  const reviewCard = panel.locator('[data-nilm-review-item="session:nilm-session-0"]');

  await reviewCard.click();

  await expect(reviewCard).toHaveAttribute("aria-pressed", "true");
  await expect(panel.locator("[data-nilm-interval-editor]")).toHaveCount(0);
  await expect(panel.locator('[data-nilm-decision][value="identify"]')).toBeVisible();
  await expect(
    panel.locator('.nilm-session-band[data-nilm-session-start="2026-07-13T16:00:00Z"][data-nilm-selected="true"]'),
  ).toHaveCount(1);
});
```

- [ ] **Step 2: Run the browser regression and verify RED**

Run:

```powershell
npx playwright test tests/e2e/panel.spec.js --grep "non-ambiguous NILM review intervals select without opening the editor"
```

Expected: FAIL because selecting the session currently calls the editor path with `edit: true`.

- [ ] **Step 3: Add an explicit edit option to session loading**

Change the session helper to default to focus-only behavior:

```javascript
async _loadNilmSessionInterval(session, options = {}) {
  const start = Date.parse(session && session.start || "");
  const end = Date.parse(session && session.end || "");
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return false;
  const assignment = ((this._nilmWorkspace && this._nilmWorkspace.assignments) || [])
    .find((item) => item.assignment_id === session.assignment_id);
  const edit = options.edit === true;
  const loaded = await this._loadNilmIntervalOnGraph(session, {
    edit,
    assignment,
    clearSignature: true,
    scroll: options.scroll !== false,
  });
  if (loaded !== true) return false;
  this._lastActionMessage = this._panelText("messages.loaded_nilm_session_interval");
  this._render();
  return true;
}
```

Keep graph-band and review-card selection focus-only. Change only the explicit adjustment path:

```javascript
_selectNilmSessionIntervalByIndex(index) {
  const sessions = Array.isArray(this._nilmWorkspace && this._nilmWorkspace.sessions)
    ? this._nilmWorkspace.sessions
    : [];
  return this._loadNilmSessionInterval(sessions[index], { edit: true });
}
```

For review items, preserve the caller's scroll preference:

```javascript
if (reviewItem.kind === "session") {
  return this._loadNilmSessionInterval(
    reviewItem.item,
    { scroll: options.scroll !== false },
  );
}
```

- [ ] **Step 4: Prove explicit adjustment still opens the editor**

Extend the session-validation browser test after locating a closed card:

```javascript
const closedCards = panel.locator('[data-nilm-session-validation-card][data-nilm-open="false"]');
await expect(closedCards).toHaveCount(4);
const closedCard = closedCards.first();
await closedCard.locator("[data-nilm-session-interval-index]").click();
await expect(panel.locator("[data-nilm-interval-editor]")).toBeVisible();
```

- [ ] **Step 5: Bump the frontend cache version**

Change:

```python
PANEL_MODULE_VERSION = "20260811-1"
```

- [ ] **Step 6: Run focused browser and panel-contract tests**

Run:

```powershell
npx playwright test tests/e2e/panel.spec.js --grep "non-ambiguous NILM review intervals select without opening the editor|NILM review supports decisions, validation, and interval labeling"
.\.venv\Scripts\python.exe -m pytest tests\test_panel.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the frontend behavior change**

```powershell
git add custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-nilm-workspace.js custom_components/circuitsetup_energy_analyzer/panel_contracts.py tests/e2e/panel.spec.js
git commit -m "fix: separate NILM interval review from editing"
```

### Task 3: Verify the complete branch

**Files:**
- Verify only; no planned source changes.

**Interfaces:**
- Consumes: committed backend eligibility and frontend selection behavior from Tasks 1 and 2.
- Produces: a clean, fully verified branch ready for review.

- [ ] **Step 1: Run repository verification**

```powershell
.\.codex\scripts\verify-pr.ps1
```

Expected: lint, unit tests, and browser checks pass.

- [ ] **Step 2: Check the final diff and worktree**

```powershell
rtk git diff --check master...HEAD
git status --short
git log --oneline master..HEAD
```

Expected: no whitespace errors, a clean worktree, and only the approved spec plus NILM interval-selection commits.
