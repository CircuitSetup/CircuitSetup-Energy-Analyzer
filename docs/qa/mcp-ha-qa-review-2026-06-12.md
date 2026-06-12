# MCP Home Assistant QA Review

Date: 2026-06-12
Repo: `C:\Users\John\Documents\CS_energy_analyzer`
Integration version: 0.7.5

## Summary

The Home Assistant MCP server is reachable and returns live state from the user's HA instance, but the CircuitSetup Energy Analyzer integration is not visible through the current MCP exposure. MCP returned normal household `sensor` and `binary_sensor` entities, including energy-class sensors, but no exposed entities matched `circuitsetup` or `energy analyzer`, and no `button`, `select`, or `number` entities were exposed.

This means MCP could verify live HA connectivity and source-like energy sensor visibility, but could not validate the analyzer config entry, platform setup, control entities, evidence panel, services, reload/unload lifecycle, or real UI flows.

## MCP Tools Available

- `mcp__home_assistant.GetLiveContext`
- `mcp__home_assistant.HassBroadcast`

No MCP tools were available for config-entry inspection, service calls, reloads, log reads, authenticated panel/API requests, or HA UI navigation.

## MCP Queries Run

```text
GetLiveContext(name="circuitsetup")
GetLiveContext(name="energy analyzer")
GetLiveContext(domain=["sensor", "binary_sensor", "button", "select", "number"], name="energy")
GetLiveContext(domain="sensor")
GetLiveContext(domain="binary_sensor")
GetLiveContext(domain="button")
GetLiveContext(domain="select")
GetLiveContext(domain="number")
```

## MCP Results

- Live HA connection: pass.
- `sensor` context: pass. MCP returned live household sensors, including energy-class sensors such as lights energy sensors.
- `binary_sensor` context: pass. MCP returned live household binary sensors such as doors, motion, battery, and vehicle sensors.
- Analyzer name lookup: fail. No exposed entities matched `circuitsetup` or `energy analyzer`.
- Analyzer `sensor` platform visibility: fail / not exposed.
- Analyzer `binary_sensor` platform visibility: fail / not exposed.
- Analyzer `button` platform visibility: fail / not exposed; no exposed `button` entities were found.
- Analyzer `select` platform visibility: fail / not exposed; no exposed `select` entities were found.
- Analyzer `number` platform visibility: fail / not exposed; no exposed `number` entities were found.

## Automated Checks

### Editable Install

Command:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

Red results before fixes:

- Failed because setuptools discovered multiple top-level packages: `blueprints` and `custom_components`.
- After explicit package discovery was added, failed again because `pytest-asyncio>=0.25.0` conflicted with the pinned requirements of `pytest-homeassistant-custom-component`.

Green result after fixes:

- Exit code: 0.
- Editable wheel built and installed for `circuitsetup-energy-analyzer==0.7.5`.
- Test harness dependencies resolved with `pytest==8.3.4`, `pytest-asyncio==0.24.0`, and `pytest-homeassistant-custom-component==0.13.205`.

### Fallback Unit Tests

Command:

```powershell
python -m pytest -q
```

Result:

- Exit code: 0.
- 598 passed in 3.16 seconds.

### Ruff

Command:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
```

Result:

- Exit code: 0.
- All checks passed.

### HA-Backed Pytest Harness

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Result:

- Exit code: 1.
- All tests errored during event-loop fixture setup before application assertions ran.
- Root error: `pytest_socket.SocketBlockedError` while native Windows `ProactorEventLoop` attempted to create a `socket.socketpair()`.

Interpretation:

This remains a native Windows HA test harness blocker. It does not prove the integration fails under HA; it proves this local Windows harness cannot currently run HA-backed tests.

## Fixes Made During This Review

- Added explicit setuptools package discovery for the Home Assistant custom integration layout:
  - include `custom_components*`
  - namespace package discovery enabled
- Pinned the HA test harness dependency trio to the versions required by `pytest-homeassistant-custom-component==0.13.205`.
- Ignored generated `*.egg-info/` metadata so editable installs do not dirty the worktree.

## QA Findings

1. The MCP-connected HA server is not currently a usable analyzer runtime QA target because the analyzer is not visible through MCP.
2. If the analyzer is installed on that server, its entities are probably not exposed to the MCP assistant, disabled/hidden, or named outside the expected search surface.
3. If the analyzer is not installed on that server, it needs to be installed and configured before MCP can validate runtime behavior.
4. MCP alone is insufficient for full QA because the available MCP surface cannot read config entries, call integration services, inspect logs, open the panel, or perform reload/unload lifecycle checks.
5. Packaging/test setup had real regressions after the previous QA commit was reverted; those have been fixed again and verified with a fresh editable install.

## Remaining Proper Runtime QA

To complete the HA runtime matrix, use one of these paths:

- Expose a configured CircuitSetup Energy Analyzer install to the current HA MCP server, then rerun the MCP entity/platform checks.
- Use HA WebSocket/REST or UI automation against an authenticated supported HA runtime for config entry, services, panel, logs, reload/unload, and lifecycle checks.
- Run HA-backed pytest in Linux, macOS, WSL, or a container rather than native Windows.

