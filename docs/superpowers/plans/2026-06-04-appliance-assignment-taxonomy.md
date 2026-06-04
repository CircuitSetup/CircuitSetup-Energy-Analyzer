# Appliance Assignment And Taxonomy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose appliance/circuit assignment in the Home Assistant setup and options UI, make large source selection manageable by meter device, and update appliance types for HVAC and pump cases.

**Architecture:** Keep the integration native to Home Assistant config/options flows. Setup/options first collect meter devices and extra source entities, expand them to source sensors, then show generated circuit assignment fields that save normal internal `circuits` entries. Existing `source_entities` remains backward compatible.

**Tech Stack:** Home Assistant config entries/options flow, voluptuous schemas, HA selectors, Python dataclasses/enums, pytest, Ruff.

---

### Task 1: Add Source Device Expansion

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/const.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/discovery.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/config_flow.py`
- Test: `tests/test_discovery.py`
- Test: `tests/test_config_flow.py`

- [ ] **Step 1: Write failing tests**

Add tests that prove:
- selected source device IDs expand to all energy-like sensor entities on those devices;
- extra source entities are merged with expanded device sensors;
- existing `source_entities` remains accepted for backward compatibility.

- [ ] **Step 2: Run focused tests**

Run:

```powershell
python -m pytest tests\test_discovery.py tests\test_config_flow.py -q
```

Expected: new tests fail because source devices and extra source entities are not implemented.

- [ ] **Step 3: Implement minimal code**

Add constants:
- `source_devices`
- `extra_source_entities`

Add discovery helper:
- `entity_ids_for_devices(hass, device_ids)`

Add config-flow normalization that stores merged `source_entities`.

- [ ] **Step 4: Verify focused tests pass**

Run the same focused tests and confirm the new behavior passes.

### Task 2: Add Circuit Assignment Builder

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/config_flow.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/mapping.py`
- Test: `tests/test_config_flow.py`
- Test: `tests/test_mapping.py`
- Test: `tests/test_coordinator.py`

- [ ] **Step 1: Write failing tests**

Add tests that prove:
- grouped source sensors produce assignment IDs like `assign__garage_vehicle_charging`;
- assignment values such as `hvac_compressor`, `hvac_blower`, `water_pump`, `mixed`, and `exclude` produce internal `circuits`;
- excluded groups stay out of `circuits` and `source_entities`;
- dual-phase L1/L2 groups are combined into one circuit with leg roles.

- [ ] **Step 2: Run focused tests**

Run:

```powershell
python -m pytest tests\test_config_flow.py tests\test_mapping.py tests\test_coordinator.py -q
```

Expected: new tests fail because the assignment step and builder do not exist.

- [ ] **Step 3: Implement minimal code**

Add grouping helpers that reuse existing sensor-role and circuit-id parsing. The assignment UI should be a generated select per discovered circuit group. Store regular `circuits` entries using the existing internal format.

- [ ] **Step 4: Verify focused tests pass**

Run the same focused tests and confirm assignment-generated circuits are accepted by the coordinator.

### Task 3: Update Appliance Taxonomy

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/models.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/profiles.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/coordinator.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/power_quality.py`
- Modify: `custom_components/circuitsetup_energy_analyzer/sensor.py`
- Test: `tests/test_profiles.py`
- Test: `tests/test_coordinator.py`
- Test: `tests/test_power_quality.py`
- Test: `tests/test_entities.py`

- [ ] **Step 1: Write failing tests**

Add tests that prove:
- `hvac_compressor`, `hvac_blower`, and `electric_heat` are accepted appliance profiles;
- `water_pump` is accepted and `well_pump` remains an alias;
- pool pump and sump pump remain distinct;
- compressor profiles get compressor/start-cycle/leg-imbalance behavior;
- blower and water pump profiles get motor-load behavior;
- electric heat gets resistive-load behavior.

- [ ] **Step 2: Run focused tests**

Run:

```powershell
python -m pytest tests\test_profiles.py tests\test_coordinator.py tests\test_power_quality.py tests\test_entities.py -q
```

Expected: new tests fail because the new profiles and aliases do not exist.

- [ ] **Step 3: Implement minimal code**

Add new `ApplianceProfile` values. Normalize old/manual aliases in the config parser. Update profile definitions and profile grouping sets used by diagnostic sensors and power-quality selection.

- [ ] **Step 4: Verify focused tests pass**

Run the same focused tests and confirm behavior matches the taxonomy.

### Task 4: Update UI Text, Docs, And Live Install

**Files:**
- Modify: `custom_components/circuitsetup_energy_analyzer/strings.json`
- Modify: `custom_components/circuitsetup_energy_analyzer/translations/en.json`
- Modify: `README.md`
- Optional live: Home Assistant HACS install and options-flow verification

- [ ] **Step 1: Add user-facing labels/descriptions**

Add clear labels for:
- Source Meter Devices
- Extra Source Entities
- Mains Source Entities
- Assign Circuits
- Appliance profile choices

- [ ] **Step 2: Run full verification**

Run:

```powershell
python -m pytest
python -m ruff check .
```

Expected: all tests pass and Ruff reports no issues.

- [ ] **Step 3: Commit, push, install, and verify live**

Commit the change, push to `origin/master`, refresh/download via HACS, restart Home Assistant, and verify:
- options flow shows device/extra/mains fields with formatted labels;
- assignment fields show detected circuit groups;
- selected source count is not lost;
- generated circuits load and analyzer entities exist.
