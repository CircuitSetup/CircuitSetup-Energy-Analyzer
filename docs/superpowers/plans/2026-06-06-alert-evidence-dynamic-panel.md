# Alert Evidence Dynamic Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dynamic Home Assistant panel that opens from an Energy Analyzer notification and shows the specific alert evidence and graph context for that alert.

**Architecture:** Keep alert link generation pure, add a focused `panel.py` backend module for panel/static/API registration and evidence payload resolution, and ship a dependency-free JavaScript custom panel module under `custom_components/circuitsetup_energy_analyzer/frontend/`. The existing Lovelace dashboard remains a fallback; notification links point to the custom panel route `/circuitsetup-energy-analyzer-evidence`.

**Tech Stack:** Python Home Assistant custom integration, Home Assistant custom panel registration, Home Assistant authenticated API view, vanilla JavaScript web component, pytest, Ruff.

---

## File Structure

- Modify `custom_components/circuitsetup_energy_analyzer/alert_links.py`
  - Change the default notification target to the dynamic panel path.
  - Keep the old dashboard path available as a fallback constant.
- Create `custom_components/circuitsetup_energy_analyzer/panel.py`
  - Register frontend assets and the custom panel.
  - Register an authenticated evidence API view.
  - Build JSON-safe evidence payloads from loaded coordinators.
- Create `custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-panel.js`
  - Render the dynamic evidence page.
  - Read query parameters, fetch evidence, render graph iframe/history link, and call existing services.
- Modify `custom_components/circuitsetup_energy_analyzer/__init__.py`
  - Set up/unload the panel once across loaded config entries.
- Modify `custom_components/circuitsetup_energy_analyzer/ux.py`
  - Use the dynamic panel path in evidence attributes.
- Modify `custom_components/circuitsetup_energy_analyzer/notifications.py`
  - Use the dynamic panel path in persistent notification links.
- Modify `README.md`
  - Explain the dynamic Alert Evidence panel and keep the dashboard as fallback.
- Modify tests:
  - `tests/test_alert_links.py`
  - `tests/test_panel.py`
  - `tests/test_services.py`
  - `tests/test_user_facing_text.py`
  - `tests/test_ux.py`

---

### Task 1: Dynamic Evidence Path

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/alert_links.py`
- Modify: `tests/test_alert_links.py`
- Modify: `tests/test_services.py`
- Modify: `tests/test_ux.py`

- [ ] **Step 1: Write failing path tests**

Add assertions that the default `alert_evidence_path(_alert())` path is `/circuitsetup-energy-analyzer-evidence`, while the query parameters still include `alert_id`, `circuit_id`, and `feature`. Keep an explicit test for the Lovelace fallback by passing `dashboard_path=DEFAULT_ALERT_EVIDENCE_DASHBOARD_PATH`.

- [ ] **Step 2: Verify red**

Run:

```powershell
pytest tests/test_alert_links.py::test_alert_evidence_path_contains_alert_context tests/test_services.py::test_alert_notification_message_includes_evidence_link_and_graph_entities tests/test_ux.py::test_alert_evidence_detail_is_json_safe_and_explains_change -q
```

Expected: at least one assertion still sees `/circuitsetup-energy-analyzer/alert-evidence`.

- [ ] **Step 3: Implement path constants**

Set:

```python
DEFAULT_ALERT_EVIDENCE_PATH = "/circuitsetup-energy-analyzer-evidence"
DEFAULT_ALERT_EVIDENCE_DASHBOARD_PATH = "/circuitsetup-energy-analyzer/alert-evidence"
```

Update imports and documentation references in tests that intentionally mean the dashboard fallback.

- [ ] **Step 4: Verify green**

Run the same focused pytest command and confirm it passes.

---

### Task 2: Backend Panel Registration And Evidence Payload

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/panel.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/__init__.py`
- Create: `tests/test_panel.py`
- Modify: `tests/test_coordinator.py`
- Modify: `tests/test_services.py`

- [ ] **Step 1: Write failing payload tests**

Create tests for:

- exact `alert_id` returns `status == "matched_alert"`;
- missing old alert with a known circuit returns `status == "latest_for_circuit"`;
- unknown alert/circuit returns `status == "not_found"`;
- payload actions include `acknowledge_alert`, `mark_alert_expected`, and `mark_alert_unhelpful`;
- setup calls fake static-path, API-view, and panel registrars only once.

- [ ] **Step 2: Verify red**

Run:

```powershell
pytest tests/test_panel.py -q
```

Expected: fail because `custom_components.circuitsetup_energy_analyzer.panel` does not exist.

- [ ] **Step 3: Implement backend module**

Implement `alert_evidence_payload(coordinators, alert_id=None, circuit_id=None)`.

Implement `async_setup_panel(hass)` and `async_unload_panel(hass)` with graceful fallbacks for tests without Home Assistant installed:

- use `hass.http.async_register_static_paths` when available;
- register `/api/circuitsetup_energy_analyzer/alert_evidence`;
- call `panel_custom.async_register_panel` when Home Assistant is available, or fake `hass.components.panel_custom.async_register_panel` in tests;
- remove the panel on unload with `frontend.async_remove_panel` or fake equivalent.

- [ ] **Step 4: Wire setup/unload**

In `__init__.py`, call `async_setup_panel(hass)` only for the first loaded config entry and `async_unload_panel(hass)` after the last config entry unloads. Include rollback on setup failure.

- [ ] **Step 5: Verify green**

Run:

```powershell
pytest tests/test_panel.py tests/test_services.py::test_setup_entry_rolls_back_services_when_platform_forwarding_fails tests/test_services.py::test_setup_entry_rolls_back_services_when_coordinator_start_fails -q
```

Expected: all pass.

---

### Task 3: JavaScript Dynamic Panel

**Files:**
- Create: `custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-panel.js`
- Modify: `tests/test_user_facing_text.py`

- [ ] **Step 1: Write failing asset tests**

Assert the JavaScript asset exists and contains:

- `customElements.define("circuitsetup-energy-analyzer-panel"`;
- `URLSearchParams`;
- `/api/circuitsetup_energy_analyzer/alert_evidence`;
- `callService("circuitsetup_energy_analyzer"`;
- `acknowledge_alert`;
- `mark_alert_expected`;
- `mark_alert_unhelpful`;
- `/history?entity_id=`;
- user-facing text for `Matched alert`, `Latest evidence for circuit`, and `Historical alert not found`.

- [ ] **Step 2: Verify red**

Run:

```powershell
pytest tests/test_user_facing_text.py::test_dynamic_alert_evidence_panel_asset_is_user_facing -q
```

Expected: fail because the asset does not exist.

- [ ] **Step 3: Implement asset**

Build a vanilla custom element that:

- stores `hass` and `panel` values;
- reads the current URL query;
- uses `hass.callApi("GET", "circuitsetup_energy_analyzer/alert_evidence?...")`;
- falls back to `fetch("/api/circuitsetup_energy_analyzer/alert_evidence?...")` with a visible error if needed;
- renders summary/evidence/source/action sections;
- builds a Home Assistant history URL from `graph_entities`;
- disables action buttons while service calls are in flight.

- [ ] **Step 4: Verify green**

Run:

```powershell
pytest tests/test_user_facing_text.py::test_dynamic_alert_evidence_panel_asset_is_user_facing -q
```

Expected: pass.

---

### Task 4: README, Blueprint, Full Verification, And HA Install

**Files:**
- Modify: `README.md`
- Modify: `blueprints/automation/circuitsetup_energy_analyzer/energy_alert_notification.yaml`
- Modify: `tests/test_user_facing_text.py`

- [ ] **Step 1: Write failing user-facing tests**

Assert README and blueprint text refer to `/circuitsetup-energy-analyzer-evidence`, explain that the standard dashboard is fallback, and tell users that notification links dynamically select graph entities through the panel.

- [ ] **Step 2: Verify red**

Run:

```powershell
pytest tests/test_user_facing_text.py::test_readme_explains_notification_evidence_graph_links tests/test_user_facing_text.py::test_alert_blueprint_is_user_friendly_and_actionable -q
```

- [ ] **Step 3: Update docs and blueprint**

Revise README and blueprint comments/examples so mobile notification `url` and `clickAction` use `{{ evidence_path }}` for the new panel path.

- [ ] **Step 4: Verify local suite**

Run:

```powershell
pytest -q
python -m ruff check .
```

Expected: all tests pass and Ruff reports no issues.

- [ ] **Step 5: Commit and push**

Commit the spec revision, plan, code, frontend asset, docs, and tests. Push `master`.

- [ ] **Step 6: Install and verify on Home Assistant**

Use HACS/update entity to install the pushed commit. Restart or reload Home Assistant if required. Verify:

- the update entity reports the pushed commit as installed/latest;
- `/circuitsetup-energy-analyzer-evidence?alert_id=<known>&circuit_id=hvac&feature=<known>` loads the custom panel;
- the panel shows the matched/latest/not-found state correctly;
- action buttons call the existing services without frontend console errors.

