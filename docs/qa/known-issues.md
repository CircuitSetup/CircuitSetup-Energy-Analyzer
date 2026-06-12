# Known Issues

Date: 2026-06-12

## Editable install failed because setuptools discovered multiple top-level packages

Severity:
- Medium

Area:
- packaging / test setup

Environment:
- HA version: N/A
- Python version: 3.12.10
- Integration version: 0.7.5
- Test setup: `python -m pip install -e ".[test]"`

Steps to reproduce:
1. Check out the repository.
2. Run `python -m pip install -e ".[test]"`.

Expected:
Editable install resolves build metadata and installs test dependencies.

Actual:
Setuptools failed with `Multiple top-level packages discovered in a flat-layout: ['blueprints', 'custom_components']`.

Logs/traceback:
Setuptools refused automatic package discovery before editable metadata was generated.

Likely cause:
`pyproject.toml` did not explicitly configure setuptools package discovery for this custom integration layout.

Recommended fix:
Explicitly configure setuptools to include `custom_components*` as namespace packages and exclude unrelated top-level folders.

Status:
- fixed

## Test extra dependency range conflicted with pytest-homeassistant-custom-component

Severity:
- Medium

Area:
- packaging / test setup

Environment:
- HA version: 2025.1.4
- Python version: 3.12.10
- Integration version: 0.7.5
- Test setup: `.venv\Scripts\python.exe -m pip install -e ".[test]"`

Steps to reproduce:
1. Install from the repository with the previous test extra.
2. Let pip resolve `pytest-homeassistant-custom-component>=0.13.0`.

Expected:
Pip resolves a compatible test harness.

Actual:
Pip reported `ResolutionImpossible` because `pytest-homeassistant-custom-component==0.13.205` requires `pytest==8.3.4` and `pytest-asyncio==0.24.0`, while the project requested `pytest-asyncio>=0.25.0`.

Logs/traceback:
The wheel metadata for `pytest_homeassistant_custom_component-0.13.205` contains:

```text
Requires-Dist: pytest==8.3.4
Requires-Dist: pytest-asyncio==0.24.0
```

Likely cause:
The project test extra used broad ranges that did not match the pinned HA custom-component test plugin.

Recommended fix:
Pin `pytest`, `pytest-asyncio`, and `pytest-homeassistant-custom-component` together.

Status:
- fixed

## HA-backed pytest run is blocked on native Windows by pytest-socket and ProactorEventLoop

Severity:
- High

Area:
- test harness / Windows environment

Environment:
- HA version: 2025.1.4
- Python version: 3.12.10
- Integration version: 0.7.5
- Test setup: `.venv\Scripts\python.exe -m pytest -q`

Steps to reproduce:
1. Install the test extra in the repo `.venv`.
2. Run `.venv\Scripts\python.exe -m pytest -q` on native Windows.

Expected:
Tests execute and report application pass/fail results.

Actual:
Every test errors during event-loop fixture setup before test code runs.

Logs/traceback:

```text
pytest_socket.SocketBlockedError: A test tried to use socket.socket.
...
asyncio\windows_events.py ... ProactorEventLoop ... socket.socketpair()
```

Likely cause:
The HA test plugin enables socket blocking. On native Windows, event-loop creation uses `socket.socketpair()`, which the socket guard blocks before tests can run.

Recommended fix:
Run the HA-backed test harness in Linux, macOS, WSL, or a container. If native Windows support is desired, add a project-level test bootstrap that sets a compatible event-loop policy and socket policy before `pytest-socket` blocks loop creation.

Status:
- not fixed

## Real HA Core server validation is blocked on native Windows dependency/toolchain limitations

Severity:
- High

Area:
- runtime HA server / environment

Environment:
- HA version: 2025.1.4
- Python version: 3.12.10
- Integration version: 0.7.5
- Test setup: disposable HA config under `.codex\ha-qa-20260612-142549`

Steps to reproduce:
1. Copy the custom component into a disposable HA config directory.
2. Seed or create a `circuitsetup_energy_analyzer` config entry.
3. Start Home Assistant Core 2025.1.4 on native Windows.

Expected:
HA starts, loads the integration, forwards all platforms, and creates entities.

Actual:
Native Windows startup requires process-local shims for unsupported HA behavior. With the seeded entry, HA setup then fails while processing built-in dependency requirements:

```text
Setup failed for custom integration 'circuitsetup_energy_analyzer': Requirements for dhcp not found: ['aiodiscover==2.1.0'].
```

Attempting to install `aiodiscover==2.1.0` fails because `netifaces` requires Microsoft C++ Build Tools:

```text
error: Microsoft Visual C++ 14.0 or greater is required.
```

Likely cause:
Home Assistant Core is not supported on native Windows. The integration's `after_dependencies` include `esphome`, whose dependency/discovery stack pulls HA built-in components such as `dhcp` in this environment.

Recommended fix:
Run real-server QA in WSL, Linux, macOS, or Docker. Do not require HACS for this runtime test; copy/symlinking the custom component is sufficient.

Status:
- not fixed

## HACS install path was not tested

Severity:
- Low

Area:
- distribution / install UX

Environment:
- HA version: 2025.1.4 attempted
- Python version: 3.12.10
- Integration version: 0.7.5
- Test setup: disposable copied custom component

Steps to reproduce:
1. Perform this QA plan as written.
2. Observe that HACS is not installed.

Expected:
Runtime validation does not require HACS.

Actual:
HACS-specific install/update behavior remains untested.

Logs/traceback:
None.

Likely cause:
HACS tests a distribution path, while this QA focused on runtime behavior.

Recommended fix:
Add a separate HACS distribution smoke test if release/update UX is in scope.

Status:
- needs maintainer decision

## Real evidence panel actions were not exercised

Severity:
- Medium

Area:
- panel / UX / services

Environment:
- HA version: 2025.1.4 attempted
- Python version: 3.12.10
- Integration version: 0.7.5
- Test setup: disposable HA server blocked before loaded entry

Steps to reproduce:
1. Attempt to open the evidence panel or authenticated API endpoints in the disposable HA server.

Expected:
Panel loads, auth is required, valid actions work, invalid IDs return safe errors, and normal users do not type IDs.

Actual:
Not reached because the integration did not complete setup in the native Windows HA server.

Logs/traceback:
See the runtime HA server blocker above.

Likely cause:
Environment prevented config entry load and platform setup.

Recommended fix:
Retest in supported HA runtime.

Status:
- not fixed

