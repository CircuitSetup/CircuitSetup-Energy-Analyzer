# Manual And Automated QA Results

Date: 2026-06-12
Host: Native Windows, PowerShell
Repo: `C:\Users\John\Documents\CS_energy_analyzer`
Integration version: 0.7.5
Home Assistant available locally: 2025.1.4 in `.venv`

## Summary

Overall status: Partial pass with environment blockers.

The no-Home-Assistant fallback unit run passed, Ruff passed, and the project packaging/test-extra setup was fixed so `python -m pip install -e ".[test]"` now succeeds. The HA-backed pytest run and real HA server workflow remain blocked by native Windows Home Assistant and pytest-socket/event-loop behavior, plus Home Assistant built-in dependency installation requiring native build tooling for `netifaces`.

HACS was not installed because it is not needed for runtime validation. A copied custom component in a disposable Home Assistant config is the correct runtime QA path.

## Commands Run

### Python And HA Versions

Command:

```powershell
.\.venv\Scripts\python.exe -c "from homeassistant.const import __version__; import pytest; print('ha', __version__); print('pytest', pytest.__version__)"
```

Result:

- Exit code: 0
- HA: 2025.1.4
- pytest before dependency correction: 9.0.3

### Editable Install Before Fix

Command:

```powershell
python -m pip install -e ".[test]"
```

Result before fix:

- Exit code: 1
- Failure: setuptools refused the flat layout because it discovered both `blueprints` and `custom_components`.

Command:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

Result after package-discovery fix but before test-extra pin fix:

- Exit code: 1
- Build metadata succeeded.
- Dependency resolution failed because `pytest-homeassistant-custom-component==0.13.205` requires `pytest==8.3.4` and `pytest-asyncio==0.24.0`, while the project requested `pytest-asyncio>=0.25.0`.

Command:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

Result after fixes:

- Exit code: 0
- Editable wheel built for `circuitsetup-energy-analyzer==0.7.5`.
- Test dependencies installed: `pytest==8.3.4`, `pytest-asyncio==0.24.0`, `pytest-homeassistant-custom-component==0.13.205`.

### Automated Tests Without HA Installed

Command:

```powershell
python -m pytest --cov=custom_components/circuitsetup_energy_analyzer --cov-report=term-missing --tb=short -q
```

Result:

- Exit code: 0
- 598 passed
- Coverage: 90 percent
- Caveat: global Python did not have Home Assistant installed, so this exercised the repo's fallback/no-HA test paths.

### HA-Backed Tests Before Dependency Correction

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Result before fixing test dependencies:

- Exit code: 1
- 543 passed, 55 failed
- Primary failure clusters:
  - Config-flow result shape changed under installed HA.
  - Fake `SimpleNamespace` tests reached HA storage/frontend internals and lacked `hass.config` or `hass.bus`.
  - Discovery and entity setup tests relied on no-HA assumptions.
  - Panel setup fakes did not satisfy HA frontend registration behavior.

### HA-Backed Tests After Dependency Correction

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Result:

- Exit code: 1
- All collected tests errored during setup.
- Root error: `pytest_socket.SocketBlockedError` while Windows `ProactorEventLoop` attempted `socket.socketpair()` during event-loop creation.

Follow-up commands:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --force-enable-socket
.\.venv\Scripts\python.exe -m pytest -q -p no:socket
```

Result:

- Exit code: 1
- Same pre-test event-loop/socket guard error.
- This is a native Windows HA test harness issue, not an application assertion failure.

### Coverage Command In `.venv`

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=custom_components/circuitsetup_energy_analyzer --cov-report=term-missing --tb=short -q
```

Result before installing the HA custom-component test plugin:

- Exit code: 1
- Failure: unrecognized `--cov` argument because `pytest-cov` was not installed.

After the install fix, the HA-backed pytest run is blocked before tests by the socket/event-loop guard, so HA-backed coverage was not produced.

### Ruff

Command:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
```

Result:

- Exit code: 0
- All checks passed.

## Disposable Home Assistant Server Attempt

Config directory:

```text
C:\Users\John\Documents\CS_energy_analyzer\.codex\ha-qa-20260612-142549
```

Actions completed:

- Copied `custom_components/circuitsetup_energy_analyzer` into the disposable config.
- Created a minimal `configuration.yaml` with `homeassistant`, `http`, `api`, `frontend`, `config`, `logger`, and template fake source entities.
- Added a local QA auth user.
- Seeded `core.config_entries` with a realistic `circuitsetup_energy_analyzer` entry containing fridge, HVAC, mains, solar, outdoor temperature, rain, and water-flow context entities.
- Started Home Assistant Core 2025.1.4 with process-local Windows shims for unsupported native Windows behavior.

Observed results:

- Initial HA startup reached HTTP 200 after process-local shims.
- Unmodified seeded-entry setup failed while processing HA built-in dependencies:
  - `Setup failed for custom integration 'circuitsetup_energy_analyzer': Requirements for dhcp not found: ['aiodiscover==2.1.0']`
- Attempting to install the reported `dhcp` requirement failed:
  - `aiodiscover==2.1.0` depends on `netifaces>=0.11.0`.
  - `netifaces` failed to build because Microsoft C++ Build Tools are not installed.
- HA Core itself is not supported on native Windows; the run also required shims for `os.fchmod`, signal handling, selector event-loop policy, and aiohttp DNS resolver behavior.

Minimum server validation status:

- HA starts with custom component present: Partial. Startup reached HTTP in a shimmed run before the seeded entry path.
- No import-time errors: Partial. Custom integration import warning only, but full seeded setup blocked by HA dependency installation.
- Config-flow integration appears: Not verified through UI/API due auth/browser/API limitations and server instability.
- Config entry created with fake entities: Seeded in storage, not created through UI.
- Platforms load: Not verified; setup blocked before platform forwarding completed.
- Entity creation: Not verified.
- Reload/unload/restart: Not verified.
- Logs checked: Yes; blocker documented above.

## Untested Items

The following require a supported HA runtime, preferably WSL, Linux, macOS, or a container:

- Full config flow through the HA UI.
- Options flow and Advanced Circuit Settings through HA UI.
- Entity detail level application against the entity registry.
- Real button/select/number entity actions.
- Services against a loaded config entry.
- Evidence panel/API with authenticated requests.
- Reload, restart, unload, remove, and persistence behavior.
- Performance smoke with 6, 12, and 24 circuits.

