# Current Code Review

Date: 2026-06-12
Integration: `circuitsetup_energy_analyzer`
Version: 0.7.5

## Summary

The integration has a broad and thoughtful user-facing surface: guided setup, circuit assignment review, short control entities, service fallbacks for automation, evidence-panel concepts, setup-health summaries, and extensive processor-level tests. The main risks are not obvious logic gaps in individual processors; they are runtime confidence gaps around full Home Assistant setup, native HA API compatibility, and test harness drift.

The most concrete defects found in this pass were packaging/test-environment issues. Both were fixed in `pyproject.toml`: explicit setuptools package discovery and compatible pins for the HA custom-component test plugin.

## Strengths

- `PLATFORMS` includes all five intended platforms: `sensor`, `binary_sensor`, `button`, `select`, and `number`.
- Service descriptions clearly label script/service paths as advanced and point normal users toward button/select/number entities or panel/UI actions.
- The codebase has extensive tests across processors, config flow, services, panel behavior, UX text, profiles, storage, NILM, water/weather, solar, demand, capacity, utility comparison, and control entities.
- Entity detail level, setup-health, suggested settings, and guided assignment flows are represented in tests and code rather than left as docs-only UX.
- Runtime rollback paths exist in `async_setup_entry` for coordinator start and platform forwarding failures.

## High-Priority Issues

### HA-backed tests are not currently runnable on this native Windows machine

Installed HA-backed tests fail before test code executes because `pytest-socket` blocks Windows `ProactorEventLoop` socket creation. This prevents reliable local validation of HA internals and should be solved by running CI/QA in Linux/macOS/WSL/container, or by adding a Windows-specific test bootstrap if native Windows must be supported.

### Real HA server validation is incomplete

A disposable HA Core 2025.1.4 server was started partially, but a full loaded config entry could not be validated on native Windows. HA Core itself is unsupported on native Windows and the run hit `dhcp`/`aiodiscover`/`netifaces` native build prerequisites while processing HA dependency chains.

### Config-flow tests are brittle against real HA result shapes

The earlier HA-backed run with pytest 9/asyncio 1.4 showed failures where direct comparisons expected minimal flow-result dicts, but HA returned additional keys such as `flow_id`, `handler`, `context`, and `description_placeholders`. Tests should assert the semantic fields they care about unless the exact HA result object is the behavior under test.

## Medium-Priority Issues

### SimpleNamespace HA fakes are leaking into real HA internals

Several earlier HA-backed failures came from fake `hass` objects missing real attributes such as `config` and `bus` when code reached HA storage or frontend helpers. Prefer real Home Assistant test fixtures for setup/unload/panel/storage paths, or patch the integration boundary explicitly.

### Evidence panel runtime coverage needs a supported HA server

Panel unit tests exist, but the actual authenticated endpoint and frontend action paths were not exercised against a loaded entry. This is important because normal no-typing UX depends on the panel for alert and NILM actions.

### Service selector UX remains advanced/manual by design

`services.yaml` uses text selectors for IDs but descriptions say normal users should use UI entities or panel actions. This is acceptable if the UI paths are complete, but it makes real UI/panel validation mandatory.

## Low-Priority Issues

### HACS path not validated

HACS is not needed for runtime QA, but a separate release/distribution smoke should verify HACS install/update metadata if release UX is in scope.

### Native Windows HA execution is noisy

Running HA Core natively on Windows required shims for `os.fchmod`, signal handling, selector event-loop policy, and aiohttp DNS resolver selection. This should not be treated as a production support target unless explicitly desired.

## UX Concerns

- The intended UX avoids normal users typing `circuit_id`, `alert_id`, `signature_id`, `recommendation_id`, entity IDs, or YAML.
- Code and service descriptions support that intent, but this pass could not prove the full normal-user path in a real HA UI.
- Suggested Settings, Advanced Circuit Settings, entity detail level, and evidence panel actions should be tested as click/select/button workflows in a supported HA server.

## Home Assistant Convention Concerns

- `manifest.json` includes `after_dependencies` on `esphome`, `recorder`, and `sensor`. In this environment, the `esphome` dependency chain contributed to runtime setup blockers through HA built-in discovery requirements. Confirm whether `esphome` must be an after-dependency for all installs, or whether the integration can gracefully discover ESPHome sensors without pulling the full ESPHome setup path during analyzer entry setup.
- Panel registration should be validated against real HA frontend/panel registries rather than only fakes.
- Tests that assert config-flow result objects should account for HA's current result metadata.

## Potential Runtime Exceptions

- Panel setup/unload paths may behave differently with real HA frontend `DATA_PANELS` and event bus than with SimpleNamespace fakes.
- Feature store initialization depends on HA storage. Real storage behavior was not reached for this integration in the server attempt.
- Options-flow recommendation and entity-detail steps should be verified with real config entries because direct result shapes differ across HA versions.

## Potential Performance Concerns

- The integration creates multiple summary, feature, diagnostic, control, and source-materialized entities. Large setups should be tested at 6, 12, and 24 circuits for update duration, recorder churn, storage growth, and event-loop blocking.
- Storage writes should be reviewed for throttling/coalescing under frequent source state updates.

## Test Coverage Gaps

- Full HA runtime setup with all five platforms loaded.
- Real config flow and options flow through HA UI/API.
- Entity registry enabled/disabled defaults under Simple/Standard/Expert.
- Evidence panel authentication and action endpoints.
- Reload/restart/unload/remove lifecycle in a real HA server.
- Performance smoke with larger circuit counts.

## Recommended Fixes

1. Run full HA server QA in a supported runtime: WSL, Linux, macOS, or Docker.
2. Add CI or documented local workflow that installs `.[test]` and runs the HA custom-component harness in a supported OS.
3. Convert setup/unload/panel/storage tests that rely on `SimpleNamespace` to real HA test fixtures where practical.
4. Adjust config-flow tests to assert semantic result fields instead of exact dict equality where HA adds metadata.
5. Revisit `after_dependencies: ["esphome", "recorder", "sensor"]` and confirm `esphome` is necessary as an after-dependency rather than optional discovery context.

