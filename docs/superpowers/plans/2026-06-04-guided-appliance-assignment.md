# Guided Appliance Assignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make automatic appliance classification visible and manually correctable in the Home Assistant setup/options flow before assignments are saved.

**Architecture:** Keep automatic grouping and profile inference as the default. Replace the multiline assignment editor with a guided review step that shows one detected circuit group at a time, displays its sensors in the step description, and lets the user edit name, appliance profile, mode, and include/exclude using normal Home Assistant form controls. Store the same internal `circuits` data as before.

**Tech Stack:** Home Assistant config/options flows, Voluptuous selectors, Python dataclasses/dicts, pytest, ruff.

---

### Task 1: Labels And Descriptions

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/strings.json`
- Modify: `custom_components/circuitsetup_energy_analyzer/translations/en.json`
- Modify: `tests/test_user_facing_text.py`

- [ ] **Step 1: Write failing text tests**

Update expected flow/options labels to use `"Source Devices"` for `source_devices` and keep `"Extra Source Entities"` for `extra_source_entities`. Assert both fields have short descriptions.

- [ ] **Step 2: Run text tests**

Run: `python -m pytest tests\test_user_facing_text.py -q`
Expected: FAIL until labels are updated.

- [ ] **Step 3: Update strings/translations**

Change both setup and options text so the frontend renders human labels and concise descriptions.

- [ ] **Step 4: Re-run text tests**

Run: `python -m pytest tests\test_user_facing_text.py -q`
Expected: PASS.

### Task 2: Guided Assignment Flow

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/config_flow.py`
- Modify: `tests/test_config_flow.py`

- [ ] **Step 1: Write failing config-flow tests**

Add tests proving that the assignment step shows one group at a time with `circuit_name`, `appliance_profile`, `circuit_mode`, and `include_circuit`, and that submitting each group preserves auto-classified defaults unless manually overridden.

- [ ] **Step 2: Run focused config-flow tests**

Run: `python -m pytest tests\test_config_flow.py -q`
Expected: FAIL until guided assignment state is implemented.

- [ ] **Step 3: Implement assignment session helpers**

Add helpers that build assignment groups from selected entities, track the current group index in pending flow state, accumulate reviewed circuits, and save final `circuits` plus `source_entities`.

- [ ] **Step 4: Implement guided setup/options steps**

Replace the multiline assignment schema with a per-group schema and dynamic description placeholders. Keep automatic classification as field defaults, and save user overrides.

- [ ] **Step 5: Re-run focused tests**

Run: `python -m pytest tests\test_config_flow.py tests\test_user_facing_text.py -q`
Expected: PASS.

### Task 3: Verification And Install

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run lint**

Run: `python -m ruff check .`
Expected: PASS.

- [ ] **Step 2: Run full tests**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 3: Commit and push**

Run:
```powershell
git add .
git commit -m "feat: guide appliance assignment flow"
git push
```

- [ ] **Step 4: Install on Home Assistant**

Refresh/download the HACS repository through the HA WebSocket API, restart Home Assistant, then verify HACS status is installed and the config entry is loaded.
